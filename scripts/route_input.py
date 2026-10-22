#!/usr/bin/env python3
"""Route every input file to exactly one modality and write route.json.

The router is a stage, not a vibe.  It emits one record per file with the evidence
that decided the branch, the alternatives it rejected, and -- when a folder holds
more than one modality -- a parallel plan with one branch per modality.

Classification is two-pass:

  1. extension, which is cheap and almost always right for media;
  2. a bounded sniff, which is what catches the cases the extension gets wrong:
     a `.csv` whose first column is a full timestamp (time-series, not a table),
     a `.csv` with lat/lon columns (geospatial), a `.json` that is a
     FeatureCollection (geospatial), a `.txt` that is really a delimited table.

Usage
    python scripts/route_input.py --in data/ --out outputs/route.json
    python scripts/route_input.py --in "*.csv" --deep --out outputs/route.json
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCHEMA_VERSION = "1.0"
SNIFF_ROWS = 40

SUFFIX = {
    "tabular": {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".feather", ".jsonl",
                ".sqlite", ".sqlite3", ".db"},
    "text-corpus": {".txt", ".md", ".markdown", ".rst", ".log", ".srt"},
    "image-set": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"},
    "audio-set": {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma"},
    "geospatial": {".geojson", ".shp", ".gpkg", ".kml", ".gpx"},
}

LAT_RE = re.compile(r"^(lat|latitude|y)$", re.I)
LON_RE = re.compile(r"^(lon|lng|long|longitude|x)$", re.I)
TS_RE = re.compile(r"^(time|timestamp|datetime|date|ts|event_time)$", re.I)
DATEISH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")
GENERATED_DIRS = {
    "outputs", "audit", "state", "__pycache__", ".git", ".hg", ".svn",
    ".pytest_cache", ".ruff_cache", ".codex-preview", "branch_inputs",
}


def expand(pattern: str) -> List[Path]:
    p = Path(pattern)
    if p.is_dir():
        files = []
        for path in p.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(p)
            if any(part in GENERATED_DIRS or part.startswith(".") for part in rel.parts):
                continue
            files.append(path)
        return sorted(files)
    if p.is_file():
        return [p]
    hits = sorted(Path(h) for h in glob.glob(pattern, recursive=True))
    return [h for h in hits if h.is_file()]


def sniff_delimited(path: Path) -> Optional[Dict[str, Any]]:
    """Read the header and a few rows without committing to a dtype."""
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            sample = fh.read(65536)
    except Exception:
        return None
    if not sample.strip():
        return {"empty": True}
    try:
        dialect = csv.Sniffer().sniff(sample[:8192], delimiters=",\t;|")
    except Exception:
        return {"delimiter": None}
    rows = list(csv.reader(sample.splitlines()[:SNIFF_ROWS], dialect))
    if not rows:
        return {"empty": True}
    header = [h.strip() for h in rows[0]]
    body = rows[1:]
    return {"delimiter": dialect.delimiter, "header": header, "n_sample_rows": len(body),
            "n_cols": len(header)}


def has_time_column(header: List[str], body: List[List[str]]) -> Tuple[bool, str]:
    for i, name in enumerate(header):
        if not TS_RE.match(name.strip()):
            continue
        vals = [r[i].strip() for r in body if i < len(r) and r[i].strip()]
        if vals and sum(bool(DATEISH_RE.match(v)) for v in vals) / len(vals) >= 0.9:
            return True, name
    # a column not named like time can still be one; check the first three columns
    for i in range(min(3, len(header))):
        vals = [r[i].strip() for r in body if i < len(r) and r[i].strip()]
        if len(vals) >= 5 and sum(bool(DATEISH_RE.match(v)) for v in vals) / len(vals) >= 0.95:
            return True, header[i]
    return False, ""


def has_latlon(header: List[str]) -> Tuple[bool, str]:
    lat = next((h for h in header if LAT_RE.match(h.strip())), None)
    lon = next((h for h in header if LON_RE.match(h.strip())), None)
    return bool(lat and lon), "%s/%s" % (lat or "?", lon or "?")


def classify(path: Path, deep: bool) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    rec: Dict[str, Any] = {"path": str(path), "name": path.name,
                           "suffix": suffix, "bytes": path.stat().st_size,
                           "alternatives_rejected": []}

    # JSON is decided by content, not extension: a GeoJSON, a list of records and
    # a nested configuration document all end in .json and belong in three
    # different branches.
    if suffix == ".json":
        try:
            doc = json.loads(path.read_text(encoding="utf-8")[:200_000])
        except Exception:
            doc = None
        if isinstance(doc, dict) and doc.get("type") in ("FeatureCollection", "Feature"):
            rec.update({"modality": "geospatial",
                        "evidence": "GeoJSON %s" % doc.get("type"),
                        "confidence": 1.0,
                        "rule_source": "route_input.py#json-content"})
            return rec
        if isinstance(doc, list) and doc and isinstance(doc[0], dict):
            rec.update({"modality": "tabular",
                        "evidence": "JSON array of %d record object(s)" % len(doc),
                        "confidence": 0.95,
                        "rule_source": "route_input.py#json-records"})
            return rec
        if isinstance(doc, dict):
            for key in ("data", "rows", "records", "items", "results"):
                v = doc.get(key)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rec.update({"modality": "tabular",
                                "evidence": "JSON object with %d record(s) under %r"
                                            % (len(v), key),
                                "confidence": 0.9,
                                "rule_source": "route_input.py#json-records"})
                    return rec
        rec.update({"modality": "unknown",
                    "evidence": "a nested JSON document, not a table or a geometry",
                    "confidence": 0.6,
                    "rule_source": "route_input.py#json-nested"})
        return rec

    for modality, suffixes in SUFFIX.items():
        if suffix in suffixes:
            if modality == "tabular" and deep and suffix in (".csv", ".tsv"):
                sniff = sniff_delimited(path) or {}
                header = sniff.get("header") or []
                body = []
                if header:
                    try:
                        with path.open("r", encoding="utf-8-sig", errors="replace",
                                       newline="") as fh:
                            rows = list(csv.reader(fh, delimiter=sniff.get("delimiter") or ","))
                        body = rows[1:SNIFF_ROWS]
                    except Exception:
                        body = []
                    is_ts, ts_col = has_time_column(header, body)
                    is_geo, geo_cols = has_latlon(header)
                    if is_ts:
                        rec.update({"modality": "time-series",
                                    "evidence": "timestamp column %r parses in >=90%% of "
                                                "the sampled rows" % ts_col,
                                    "confidence": 0.9,
                                    "rule_source": "route_input.py#sniff-time"})
                        rec["alternatives_rejected"] = [
                            {"modality": "tabular", "reason": "a regular time index changes "
                                                              "the questions that can be "
                                                              "asked (gaps, trend, seasonality)"}]
                        return rec
                    if is_geo:
                        rec.update({"modality": "geospatial",
                                    "evidence": "lat/lon column pair %s" % geo_cols,
                                    "confidence": 0.85,
                                    "rule_source": "route_input.py#sniff-latlon"})
                        rec["alternatives_rejected"] = [
                            {"modality": "tabular", "reason": "coordinates are a geometry, "
                                                              "not two independent measurements"}]
                        return rec
            rec.update({"modality": modality, "evidence": "extension %s" % suffix,
                        "confidence": 0.99,
                        "rule_source": "route_input.py#extension"})
            return rec

    if suffix == ".txt" and deep and path.stat().st_size > 0:
        sniff = sniff_delimited(path)
        if sniff and sniff.get("n_cols", 0) >= 3:
            rec.update({"modality": "tabular",
                        "evidence": "delimited text with %d columns" % sniff["n_cols"],
                        "confidence": 0.7,
                        "rule_source": "route_input.py#sniff-delimited"})
            return rec

    rec.update({"modality": "unknown", "evidence": "no rule matched suffix %r" % suffix,
                "confidence": 0.0, "rule_source": "route_input.py#fallback"})
    return rec


def branch(modality: str) -> Dict[str, Any]:
    return {
        "tabular": {"profiler": "scripts/profile_tabular.py", "next": "cleaning_plan.py"},
        "text-corpus": {"profiler": "scripts/profile_text.py", "next": "cleaning_plan.py"},
        "time-series": {"profiler": "scripts/profile_timeseries.py", "next": "cleaning_plan.py"},
        "image-set": {"profiler": "scripts/profile_media.py --kind image", "next": "cleaning_plan.py"},
        "audio-set": {"profiler": "scripts/profile_media.py --kind audio", "next": "cleaning_plan.py"},
        "geospatial": {"profiler": "scripts/profile_geospatial.py", "next": "cleaning_plan.py"},
        "unknown": {"profiler": None, "next": "references/research-protocol.md"},
    }.get(modality, {"profiler": None, "next": None})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="route input files to modalities")
    ap.add_argument("--in", dest="inp", required=True, help="file, folder, or glob")
    ap.add_argument("--out", required=True)
    ap.add_argument("--deep", action="store_true",
                    help="sniff CSV/TSV headers to separate time-series and geospatial "
                         "from plain tabular")
    ap.add_argument("--modality", default=None,
                    help="force one modality for every input; recorded as an override")
    args = ap.parse_args(argv)

    files = expand(args.inp)
    if not files:
        print("no files matched %r" % args.inp, file=sys.stderr)
        return 2

    records = []
    for path in files:
        rec = classify(path, args.deep)
        if args.modality:
            rec["user_override"] = args.modality
            rec["auto_modality"] = rec["modality"]
            rec["modality"] = args.modality
            rec["evidence"] = "user override (auto said %s)" % rec["auto_modality"]
            rec["rule_source"] = "route_input.py#user-override"
        records.append(rec)

    by = Counter(r["modality"] for r in records)
    plan = []
    for modality in sorted(by):
        b = branch(modality)
        plan.append({"modality": modality, "n_files": by[modality],
                     "files": [r["path"] for r in records if r["modality"] == modality],
                     "profiler": b["profiler"], "next": b["next"],
                     "parallel": True})

    flags = []
    if by.get("unknown"):
        flags.append({"type": "unknown_modality", "severity": "P1",
                      "count": by["unknown"],
                      "detail": "these inputs match no rule; route them through "
                                "references/research-protocol.md explicitly"})
    if len(by) > 1:
        flags.append({"type": "mixed_modalities", "severity": "P3",
                      "detail": "one branch per modality; the report merges the "
                                "per-branch results and says so"})

    doc = {
        "schema_version": SCHEMA_VERSION,
        "source": args.inp,
        "generated": datetime.now(timezone.utc).isoformat(),
        "deep_sniff": bool(args.deep),
        "n_files": len(records),
        "by_modality": dict(by),
        "is_mixed": len(by) > 1,
        "files": records,
        "plan": plan,
        "flags": flags,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print("route_input: %d file(s) -> %s" % (len(records), ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(by.items()))))
    return 0 if not by.get("unknown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
