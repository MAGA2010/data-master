"""Check the dependencies this skill actually imports.

An earlier version listed libraries the pipeline never imports (wordcloud,
langdetect, librosa, rasterio) as requirements, so `--modalities text` reported
four missing packages and exited 2 on a machine where the text profiler runs
fine.  A dependency checker that over-reports is worse than none: it teaches the
user to ignore it.

Each entry records whether the package is *required* for the modality or only
*optional* (an upgrade path).  Only a missing required package makes the check
fail.

Usage
    python scripts/check_deps.py --modalities tabular
    python scripts/check_deps.py --modalities tabular,text,time-series --json
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from importlib import metadata
from typing import Dict, List

# (import name, pip name, modalities, required, why)
DEPS = [
    ("pandas", "pandas", ["tabular", "text-corpus", "time-series", "geospatial"], True,
     "every reader and every stats stage"),
    ("numpy", "numpy", ["tabular", "text-corpus", "time-series", "image-set",
                        "audio-set", "geospatial"], True,
     "numeric core"),
    ("scipy", "scipy", ["tabular", "time-series"], True,
     "inferential tests"),
    ("matplotlib", "matplotlib", ["tabular", "time-series"], False,
     "figure rendering; the report still builds without it"),
    ("statsmodels", "statsmodels", ["tabular", "time-series"], False,
     "ADF / trend screens and modelled effects; a documented fallback exists"),
    ("openpyxl", "openpyxl", ["tabular"], False,
     "reading .xlsx; CSV/TSV/Parquet do not need it"),
    ("pyarrow", "pyarrow", ["tabular"], False,
     "reading .parquet"),
    ("PIL", "Pillow", ["image-set"], True,
     "image decoding, EXIF, brightness and aHash"),
    ("shapefile", "pyshp", ["geospatial"], False,
     "only for .shp; GeoJSON and CSV need nothing extra"),
    ("reportlab", "reportlab", ["report"], False,
     "PDF tier 1; the cascade falls through to fpdf2 or the browser"),
    ("fpdf", "fpdf2", ["report"], False,
     "PDF tier 2"),
    ("pypdf", "pypdf", ["report"], False,
     "PDF page count and text extraction for QA"),
]

ALIASES = {
    "tabular": "tabular",
    "text": "text-corpus", "text-corpus": "text-corpus", "text_corpus": "text-corpus",
    "timeseries": "time-series", "time-series": "time-series", "time_series": "time-series",
    "image": "image-set", "image-set": "image-set", "images": "image-set",
    "audio": "audio-set", "audio-set": "audio-set",
    "geo": "geospatial", "geospatial": "geospatial", "gis": "geospatial",
    "report": "report", "pdf": "report",
}


def version_of(pip_name: str) -> str:
    for cand in (pip_name, pip_name.replace("-", "_"), pip_name.replace("_", "-")):
        try:
            return metadata.version(cand)
        except metadata.PackageNotFoundError:
            continue
    return ""


def check(modalities: List[str]) -> Dict:
    wanted = set(modalities)
    out: Dict[str, Dict] = {}
    missing_required: List[str] = []
    missing_optional: List[str] = []
    for import_name, pip_name, used_by, required, why in DEPS:
        if not any(m in wanted for m in used_by):
            continue
        v = version_of(pip_name)
        # PIL is installed as Pillow; the metadata name and the import differ.
        installed = bool(v)
        out[import_name] = {
            "installed": installed,
            "version": v,
            "pip_name": pip_name,
            "install_cmd": "pip install %s" % pip_name,
            "required": required,
            "why": why,
            "used_by": used_by,
        }
        if not installed:
            (missing_required if required else missing_optional).append(pip_name)
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "modalities_checked": sorted(wanted),
        "deps": out,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        # kept for compatibility with callers that read `missing`
        "missing": missing_required,
        "ffprobe": bool(shutil.which("ffprobe")),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modalities",
                   default="tabular,text-corpus,time-series,image-set,audio-set,geospatial,report",
                   help="comma list; aliases such as text/timeseries/image/geo are accepted")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    raw = [m.strip() for m in args.modalities.split(",") if m.strip()]
    unknown = [m for m in raw if m not in ALIASES]
    if unknown:
        print("unknown modality name(s): %s\nknown: %s"
              % (", ".join(unknown), ", ".join(sorted(ALIASES))), file=sys.stderr)
        return 2
    result = check([ALIASES[m] for m in raw])

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Python: %s" % result["python_version"])
        print("Modalities: %s" % ", ".join(result["modalities_checked"]))
        print("Required missing: %d | optional missing: %d | ffprobe: %s"
              % (len(result["missing_required"]), len(result["missing_optional"]),
                 "yes" if result["ffprobe"] else "no"))
        for name, info in result["deps"].items():
            if info["installed"]:
                mark = "OK "
            else:
                mark = "MISS" if info["required"] else "opt "
            print("  [%s] %-12s %-10s %s" % (mark, name, info["version"] or "-",
                                             info["why"]))
        if result["missing_optional"]:
            print("\nOptional, not installed: %s" % ", ".join(result["missing_optional"]))
    return 0 if not result["missing_required"] else 2


if __name__ == "__main__":
    sys.exit(main())
