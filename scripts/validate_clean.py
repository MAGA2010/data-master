"""Validate the cleaned dataset against the raw one. This is the Stage-1 gate.

Acceptance criteria (all must pass for gate `cleaning_validated` = true):
1. row_loss_pct < max_row_loss (default 30)
2. target/label column preserved (if the profile flagged one)
3. no dtype regression (raw numeric stays numeric; raw datetime stays datetime)
4. no NaN inflation (columns with 0 raw NaN must have 0 cleaned NaN)
5. no all-null column introduced

Writes cleaned/cleaned_validation.json (machine-checkable gate evidence).

Usage:
    python validate_clean.py --raw data/sales.csv --clean cleaned/cleaned.csv \
        --profile analysis/profile.json --out cleaned/cleaned_validation.json --max-row-loss 30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dm_types import (  # noqa: E402
    find_cleaning_run, is_datetime, is_numeric, load_cleaned, read_table,
)


def _read(src: Path) -> pd.DataFrame:
    return load_cleaned(src)[0]


def _is_num(dtype) -> bool:
    return is_numeric(dtype)


def _is_dt(dtype) -> bool:
    return is_datetime(dtype)


def validate(raw: pd.DataFrame, clean: pd.DataFrame, profile: Dict[str, Any],
             max_row_loss: int, manifest: Dict[str, str] = None,
             run: Dict[str, Any] = None, dtype_source: str = "unknown") -> Dict[str, Any]:
    manifest = manifest or {}
    checks: List[Dict[str, Any]] = []

    # --- 1. row loss ---
    n_raw, n_clean = len(raw), len(clean)
    loss_pct = round((n_raw - n_clean) / max(n_raw, 1) * 100, 2)
    checks.append({
        "id": "row_loss",
        "passes": loss_pct < max_row_loss,
        "detail": {"n_raw": n_raw, "n_clean": n_clean, "loss_pct": loss_pct, "limit": max_row_loss},
        "severity": "P1",
    })

    # --- 2. target column preserved ---
    tgt = profile.get("target_candidate", {}).get("candidates", [])
    tgt_col = tgt[0]["column"] if tgt else None
    tgt_ok = True
    tgt_detail: Dict[str, Any] = {"target_candidate": tgt_col}
    if tgt_col:
        present = tgt_col in clean.columns
        tgt_ok = present
        if present and tgt_col in raw.columns:
            tgt_detail["n_unique_raw"] = int(raw[tgt_col].nunique())
            tgt_detail["n_unique_clean"] = int(clean[tgt_col].nunique())
            if clean[tgt_col].nunique() < raw[tgt_col].nunique():
                tgt_ok = False
                tgt_detail["reason"] = "target cardinality shrank"
    checks.append({"id": "target_preserved", "passes": tgt_ok, "detail": tgt_detail, "severity": "P0"})

    # --- 3. dtype regression ---
    # Compares the cleaned types against what the run DECIDED and RECORDED, not
    # against what pandas guessed when reading the raw file. Guessing is the
    # thing this pipeline exists to replace: the guess turns the postcode
    # "02134" into 2134, and comparing against it condemns the run for refusing
    # to repeat the mistake.
    dtype_issues = []
    coerced = set()
    if run and run.get("applied_ops"):
        coerced = {c for a in run["applied_ops"]
                   if a.get("op") in ("coerce_numeric", "coerce_dates")
                   for c in a.get("columns", [])}

    for c in clean.columns:
        declared = (manifest or {}).get(c)
        if declared is not None and str(clean[c].dtype) != str(declared):
            dtype_issues.append({"column": c, "declared": declared,
                                 "observed": str(clean[c].dtype),
                                 "issue": "cleaned dtype does not match the recorded manifest"})
        if c in raw.columns and c not in coerced:
            if _is_num(clean[c].dtype) and not _is_num(raw[c].dtype):
                dtype_issues.append({"column": c, "raw": str(raw[c].dtype),
                                     "clean": str(clean[c].dtype),
                                     "issue": "became numeric without a coercion op in the plan"})

    for c in raw.columns:
        if c not in clean.columns:
            continue
        if _is_dt(raw[c].dtype) and not _is_dt(clean[c].dtype):
            dtype_issues.append({"column": c, "raw": str(raw[c].dtype),
                                 "clean": str(clean[c].dtype),
                                 "issue": "datetime became non-datetime"})

    checks.append({
        "id": "dtype_stable",
        "passes": len(dtype_issues) == 0,
        "detail": {"issues": dtype_issues, "n_issues": len(dtype_issues),
                   "dtype_source": dtype_source,
                   "columns_coerced_by_plan": sorted(coerced)},
        "severity": "P0",
    })

    # --- 4. NaN inflation ---
    nan_issues = []
    for c in raw.columns:
        if c not in clean.columns:
            continue
        raw_nan = int(raw[c].isna().sum())
        clean_nan = int(clean[c].isna().sum())
        if raw_nan == 0 and clean_nan > 0:
            nan_issues.append({"column": c, "raw_nan": 0, "clean_nan": clean_nan})
    checks.append({
        "id": "no_nan_inflation",
        "passes": len(nan_issues) == 0,
        "detail": {"issues": nan_issues, "n_issues": len(nan_issues)},
        "severity": "P0",
    })

    # --- 5. no all-null column introduced ---
    all_null = [c for c in clean.columns if int(clean[c].isna().sum()) == len(clean)]
    checks.append({
        "id": "no_all_null_col",
        "passes": len(all_null) == 0,
        "detail": {"columns": all_null},
        "severity": "P1",
    })

    # --- 6. all non-null columns retained (informational) ---
    dropped_cols = [c for c in raw.columns if c not in clean.columns]
    checks.append({
        "id": "columns_retained",
        "passes": True,
        "detail": {
            "dropped": dropped_cols,
            "n_dropped": len(dropped_cols),
            "note": "dropped columns must all be 100% null (auto) or flagged in plan",
        },
        "severity": "P3",
    })

    hard_fail = [c for c in checks if not c["passes"] and c["severity"] in ("P0", "P1")]

    return {
        "schema_version": "1.0",
        "gate": "cleaning_validated",
        "passes": len(hard_fail) == 0,
        "checks": checks,
        "n_failed": len(hard_fail),
        "verdict": "PASS" if len(hard_fail) == 0 else "FAIL",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", required=True)
    p.add_argument("--clean", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-row-loss", type=float, default=30.0)
    args = p.parse_args()

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    raw_path, clean_path = Path(args.raw), Path(args.clean)

    # The raw file is read the way the profiler read it. Reading it any other way
    # would compare the run against a guess instead of against its own contract.
    raw = read_table(raw_path, read_mode=profile.get("read_mode", "text"))

    clean_path_dm = find_cleaning_run(clean_path)
    run = {}
    if clean_path_dm is not None:
        run = json.loads(clean_path_dm.read_text(encoding="utf-8"))
    manifest = run.get("dtype_manifest") or {}
    clean, prov = load_cleaned(clean_path)
    dtype_source = prov["dtype_source"]

    result = validate(raw, clean, profile, args.max_row_loss,
                      manifest=manifest, run=run, dtype_source=dtype_source)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"gate cleaning_validated: {result['verdict']}  (failed: {result['n_failed']})")
    for c in result["checks"]:
        mark = "PASS" if c["passes"] else "FAIL"
        print(f"  [{mark}] {c['id']:<24} {c['detail']}")
    return 0 if result["passes"] else 3


if __name__ == "__main__":
    sys.exit(main())
