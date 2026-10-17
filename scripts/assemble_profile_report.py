#!/usr/bin/env python3
"""Build an honest report for profile-only modalities.

This report deliberately stops before inference. It describes what was found,
what could not be decoded or trusted, and which questions the profile cannot
answer. A readable PDF is useful here only if it does not imply that a rank test
or a group comparison was run when the modality branch never got that far.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from assemble_report import (  # noqa: E402
    DISCLAIMER_MARKERS,
    FORBIDDEN,
    render_pdf_cascade,
)

SCHEMA_VERSION = "1.0"


def load_json(path: Optional[Path]) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def md_table(headers: List[str], rows: Iterable[List[Any]]) -> str:
    body = list(rows)
    if not body:
        return "_No rows._\n"
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in body:
        cells = ["" if value is None else str(value) for value in row]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def fmt(value: Any) -> str:
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != value:
            return "--"
        return f"{value:.4g}"
    return str(value)


def branches(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    if profile.get("branches"):
        return list(profile["branches"])
    return [{
        "modality": profile.get("modality", "unknown"),
        "source": profile.get("source", ""),
        "profile": profile,
    }]


def hydrate_branch_profiles(profile: Dict[str, Any],
                            aggregate_path: Path) -> Dict[str, Any]:
    """Load branch profiles referenced by a mixed aggregate without duplicating
    their full contents back into the aggregate JSON."""
    for branch in profile.get("branches") or []:
        if branch.get("profile"):
            continue
        raw = branch.get("profile_path")
        if not raw:
            branch["profile"] = {}
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (aggregate_path.parent / candidate).resolve()
        branch["profile"] = load_json(candidate)
    return profile


def anomalies(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list((profile.get("anomalies") or {}).get("flags") or [])


def summary_lines(profile: Dict[str, Any]) -> List[str]:
    modality = profile.get("modality", "unknown")
    shape = profile.get("shape") or {}
    anomalies_ = anomalies(profile)
    top_severity = "none"
    for level in ("P0", "P1", "P2", "P3"):
        if any(flag.get("severity") == level for flag in anomalies_):
            top_severity = level
            break
    return [
        "| Field | Value |",
        "|---|---|",
        "| Modality | `%s` |" % modality,
        "| Source | `%s` |" % Path(str(profile.get("source", ""))).name,
        "| Records inspected | %s |" % fmt(shape.get("n_rows")),
        "| Fields | %s |" % fmt(shape.get("n_cols")),
        "| Independent-unit hint | %s (heuristic, not a declaration) |"
        % fmt(profile.get("independent_unit_hint")),
        "| Anomaly flags | %d |" % len(anomalies_),
        "| Highest severity | %s |" % top_severity,
    ]


def modality_findings(profile: Dict[str, Any]) -> List[str]:
    modality = profile.get("modality")
    lines: List[str] = []
    if modality == "time-series":
        ts = profile.get("timeseries_candidate") or {}
        lines.extend([
            "### Time-series structure",
            "",
            md_table(
                ["Property", "Observed"],
                [
                    ["Time column", "`%s`" % fmt(profile.get("time_column"))],
                    ["Modal interval", fmt(ts.get("step_human"))],
                    ["Regular sampling", fmt(ts.get("regular"))],
                    ["Detected gaps", fmt(ts.get("n_gaps"))],
                    ["Regime change suspected", fmt(ts.get("regime_change_suspected"))],
                    ["First timestamp", fmt(ts.get("first_timestamp"))],
                    ["Last timestamp", fmt(ts.get("last_timestamp"))],
                ],
            ),
        ])
        numeric = [
            (name, info) for name, info in (profile.get("columns") or {}).items()
            if info.get("kind") == "numeric"
        ]
        if numeric:
            lines.extend([
                "### Numeric series",
                "",
                md_table(
                    ["Column", "n", "Missing", "Mean", "SD", "Min", "Max"],
                    [
                        [f"`{name}`", fmt(info.get("n_numeric")),
                         fmt(info.get("n_missing")), fmt(info.get("mean")),
                         fmt(info.get("sd")), fmt(info.get("min")),
                         fmt(info.get("max"))]
                        for name, info in numeric
                    ],
                ),
            ])
    elif modality == "text-corpus":
        corpus = profile.get("corpus") or {}
        lines.extend([
            "### Corpus structure",
            "",
            md_table(
                ["Property", "Observed"],
                [
                    ["Documents", fmt(corpus.get("n_documents"))],
                    ["Tokens", fmt(corpus.get("n_tokens"))],
                    ["Vocabulary", fmt(corpus.get("vocabulary_size"))],
                    ["Type/token ratio", fmt(corpus.get("type_token_ratio"))],
                    ["Empty documents", len(corpus.get("empty_documents") or [])],
                    ["Duplicate groups", fmt(corpus.get("duplicate_document_groups"))],
                    ["Dominant script", fmt((corpus.get("language") or {}).get("script"))],
                ],
            ),
        ])
        terms = corpus.get("top_content_terms") or []
        if terms:
            lines.extend([
                "### Frequent content terms",
                "",
                md_table(["Term", "Count"],
                         [["`%s`" % item.get("term"), fmt(item.get("count"))]
                          for item in terms[:10]]),
            ])
    elif modality in ("image-set", "audio-set"):
        summary = profile.get("summary") or {}
        rows = [
            ["Files", fmt(summary.get("n_files"))],
            ["Readable", fmt(summary.get("n_ok"))],
            ["Unreadable", fmt(summary.get("n_unreadable"))],
        ]
        if modality == "image-set":
            rows.extend([
                ["Formats", ", ".join(
                    f"{k}={v}" for k, v in sorted((summary.get("formats") or {}).items())
                ) or "--"],
                ["Nearly blank", ", ".join(summary.get("nearly_blank") or []) or "none"],
                ["Near-duplicate pairs",
                 fmt(len(summary.get("near_duplicate_pairs") or []))],
            ])
        else:
            for key in ("duration_s", "sample_rate_hz", "channels",
                        "clipping_files", "silent_files"):
                if key in summary:
                    rows.append([key.replace("_", " ").title(), fmt(summary.get(key))])
        lines.extend([
            "### Media inventory",
            "",
            md_table(["Property", "Observed"], rows),
        ])
    elif modality == "geospatial":
        geometry = profile.get("geometry") or {}
        summary = profile.get("summary") or {}
        lines.extend([
            "### Geometry and validity",
            "",
            md_table(
                ["Property", "Observed"],
                [
                    ["CRS", fmt((profile.get("crs") or {}).get("crs"))],
                    ["Features", fmt(geometry.get("n_features"))],
                    ["Points", fmt(geometry.get("n_points"))],
                    ["Valid points", fmt(summary.get("n_valid_points"))],
                    ["Invalid points", fmt(summary.get("n_invalid_points"))],
                    ["Null-island points", fmt(summary.get("n_null_island"))],
                    ["Coincident locations", fmt(summary.get("n_coincident_locations"))],
                ],
            ),
        ])
        bounds = geometry.get("bounds") or {}
        if bounds:
            lines.extend([
                "### Bounds",
                "",
                md_table(
                    ["min lon", "max lon", "min lat", "max lat", "diagonal km"],
                    [[fmt(bounds.get("min_lon")), fmt(bounds.get("max_lon")),
                      fmt(bounds.get("min_lat")), fmt(bounds.get("max_lat")),
                      fmt(geometry.get("diagonal_km"))]],
                ),
            ])
    else:
        cols = profile.get("columns") or {}
        if cols:
            lines.extend([
                "### Column profile",
                "",
                md_table(
                    ["Column", "Role", "n", "Missing %", "Unique"],
                    [[f"`{name}`", fmt(info.get("role")), fmt(info.get("n")),
                      fmt(info.get("missing_pct")), fmt(info.get("n_unique"))]
                     for name, info in cols.items()],
                ),
            ])
    return lines


def build_markdown(profile: Dict[str, Any], route: Dict[str, Any],
                   title: str) -> str:
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    branch_list = branches(profile)
    total_anomalies = sum(len(anomalies(b.get("profile") or {})) for b in branch_list)
    p1 = sum(
        1 for b in branch_list for flag in anomalies(b.get("profile") or {})
        if flag.get("severity") in ("P0", "P1")
    )
    lines: List[str] = [
        "# %s" % title,
        "",
        "_Profile-only report generated %s by `scripts/assemble_profile_report.py` "
        "from the artifacts listed in `report_build.json`. No statistical test is "
        "reported here._" % generated,
        "",
        "## Executive summary",
        "",
        "The input was routed to %d branch%s and profiled without changing the raw "
        "files. The profile found **%d anomaly flag(s)**, including **%d at P0/P1**. "
        "This report describes those findings and stops before inference because "
        "the selected branch does not implement a defensible statistical model for "
        "this modality." % (
            len(branch_list), "" if len(branch_list) == 1 else "es",
            total_anomalies, p1,
        ),
        "",
        "## 1. Scope and routing",
        "",
        "The router recorded the following evidence:",
        "",
        md_table(
            ["Modality", "Files", "Profiler", "Next stage"],
            [[f"`{plan.get('modality')}`", fmt(plan.get("n_files")),
              f"`{plan.get('profiler') or '--'}`",
              f"`{plan.get('next') or '--'}`"]
             for plan in (route.get("plan") or [])],
        ),
        "Profile-only mode inspects and reports. It does not clean, impute, "
        "deduplicate, transform, test or draw inferential conclusions.",
        "",
        "## 2. Profile findings",
        "",
    ]
    for index, branch in enumerate(branch_list, 1):
        branch_profile = branch.get("profile") or {}
        lines.extend([
            "### 2.%d %s" % (index, branch.get("modality") or "unknown"),
            "",
            *summary_lines(branch_profile),
            "",
            *modality_findings(branch_profile),
            "",
        ])

    lines.extend([
        "## 3. Anomalies",
        "",
    ])
    anomaly_rows = []
    for branch in branch_list:
        for flag in anomalies(branch.get("profile") or {}):
            anomaly_rows.append([
                f"`{branch.get('modality')}`",
                f"`{flag.get('severity')}`",
                f"`{flag.get('type')}`",
                fmt(flag.get("column")),
                fmt(flag.get("count")),
                flag.get("detail") or "",
            ])
    lines.extend([
        md_table(["Branch", "Severity", "Type", "Column", "Count", "Meaning"],
                 anomaly_rows),
        "## 4. What was and was not done",
        "",
        "**Completed.** Format routing, bounded decoding, structural profiling, "
        "missingness counts, duplicate checks and modality-specific integrity flags.",
        "",
        "**Not performed.** Statistical inference, causal interpretation, "
        "automatic row deletion, imputation, deduplication, feature engineering "
        "and model fitting. Their absence is a scope boundary, not a passing result.",
        "",
        "## 5. Reproducibility",
        "",
        "The run used Python %s on %s. The profile and route JSON are the evidence "
        "for every statement in this report; their hashes and the PDF backend trail "
        "are stored in `report_build.json`." % (
            platform.python_version(), platform.platform(),
        ),
        "",
        "## 6. Open questions",
        "",
        "1. **AUTHOR_INPUT_NEEDED: what does one independent unit represent?** "
        "The profiler's unit hint is a heuristic based on the input shape, not a "
        "study-design declaration.",
        "2. **AUTHOR_INPUT_NEEDED: which anomalies are genuine defects?** "
        "Duplicate documents, near-duplicate images, repeated timestamps and "
        "coincident points can be either technical repeats or independent "
        "observations; the data alone cannot decide.",
        "3. **AUTHOR_INPUT_NEEDED: what comparison or prediction question is the "
        "report meant to answer?** A profile can support exploratory decisions but "
        "cannot choose a model without a stated estimand.",
        "",
        "---",
        "",
        "_End of profile-only report. No value in the raw input was modified._",
        "",
    ])
    return "\n".join(lines)


def own_audit(text: str) -> Dict[str, Any]:
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if any(marker in low for marker in DISCLAIMER_MARKERS):
            continue
        for pattern, why in FORBIDDEN:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                hits.append({
                    "line": number,
                    "phrase": match.group(0),
                    "why": why,
                    "text": line.strip()[:160],
                })
    return {
        "n_forbidden": len(hits),
        "findings": hits,
        "n_lines_scanned": len(text.splitlines()),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--route", default=None)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--title", default="Dataset profile")
    ap.add_argument("--pdf-backend", default="auto",
                    choices=["auto", "reportlab", "fpdf2", "headless-browser"])
    args = ap.parse_args(argv)

    profile_path = Path(args.profile)
    route_path = Path(args.route) if args.route else None
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    profile = hydrate_branch_profiles(load_json(profile_path), profile_path)
    route = load_json(route_path)
    if not profile:
        print("profile not found or empty: %s" % profile_path, file=sys.stderr)
        return 2

    md_path = outdir / "report.md"
    pdf_path = outdir / "report.pdf"
    md = build_markdown(profile, route, args.title)
    md_path.write_text(md, encoding="utf-8")

    summary = branches(profile)
    executive = [
        "# %s -- Executive summary" % args.title,
        "",
        "_Profile-only scope. No inferential test was run._",
        "",
        "- Branches inspected: **%d**." % len(summary),
        "- Total anomaly flags: **%d**." % sum(
            len(anomalies(branch.get("profile") or {})) for branch in summary
        ),
        "- Primary evidence: `analysis/profile.json` and `route.json`.",
        "- Limits: one row or file is not established as an independent unit; "
        "anomalies are descriptions, not automatic deletion decisions.",
        "",
        "Read `report.md` for modality-specific findings and the full open-question list.",
        "",
    ]
    (outdir / "executive_summary.md").write_text(
        "\n".join(executive), encoding="utf-8"
    )

    pdf = render_pdf_cascade(md_path, pdf_path, prefer=args.pdf_backend)
    audit = own_audit(md)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "title": args.title,
        "mode": "profile-only",
        "generated": datetime.now().astimezone().isoformat(),
        "report_md": str(md_path),
        "report_md_sha256": sha256_of(md_path),
        "report_pdf": str(pdf_path) if pdf.get("pdf_written") else None,
        "pdf": pdf,
        "profile": str(profile_path),
        "profile_sha256": sha256_of(profile_path),
        "route": str(route_path) if route_path else None,
        "route_sha256": sha256_of(route_path) if route_path else None,
        "provenance": [
            {
                "kind": "profile",
                "value": profile.get("modality"),
                "meaning": "routed modality",
                "artifact": str(profile_path),
                "script": "scripts/route_input.py + profile_*.py",
            },
            {
                "kind": "anomaly_count",
                "value": sum(
                    len(anomalies(branch.get("profile") or {}))
                    for branch in summary
                ),
                "meaning": "number of integrity flags",
                "artifact": str(profile_path),
                "script": "profile_*.py",
            },
        ],
        "self_audit": audit,
    }
    (outdir / "report_build.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    print("[profile-report] report.md  %d bytes" % md_path.stat().st_size)
    if pdf.get("pdf_written"):
        print("[profile-report] report.pdf %s bytes, backend=%s"
              % (pdf.get("bytes"), pdf.get("backend")))
    else:
        print("[profile-report] PDF BLOCKED: %s" % pdf.get("blocked_reason"))
    if audit["n_forbidden"]:
        print("[profile-report] forbidden phrases: %d" % audit["n_forbidden"],
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
