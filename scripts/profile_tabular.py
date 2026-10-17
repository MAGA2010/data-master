"""Profile tabular data: CSV / TSV / Excel / JSON / Parquet.

Reads a file, emits analysis/profile.json compatible with cleaning_plan.py and the
stats_*.py scripts. All column-role decisions go through dm_types.py so behaviour
is stable across pandas versions (pandas 3.0 changed the string dtype default).

Usage:
    python profile_tabular.py --in data/sales.csv --out analysis/profile.json
    python profile_tabular.py --in data/sales.csv --out analysis/profile.json --n-sample 10000
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from dm_types import (  # noqa: E402
    column_role, date_view, datetime_columns, fold_case_map,
    hygiene_project, is_datetime, is_numeric, is_string_like,
    numeric_view, read_table, residual_case_variants,
)


def _sf(x: Any) -> Any:
    """Safe float -> JSON-friendly, NaN/inf become None."""
    try:
        f = float(x)
    except Exception:
        return None
    return None if not np.isfinite(f) else round(f, 6)


# ---------------- coercion probe ----------------

_LONG_STRING_CUTOFF = 40
_COMPACT_DATE_DIGITS = range(6, 9)      # 6-8 digits: YYMMDD, YMD, YYYYMMDD


def _looks_compact_date(projected: pd.Series, nd: Dict[str, Any]) -> bool:
    """True when every value is a bare integer of 6-8 digits.

    That shape is where a number and a date stop being distinguishable: "20240115"
    is the integer 20240115 and also 2024-01-15, and the file does not say which
    the author meant. Any wider or narrower span is unambiguous, so the test is
    kept narrow on purpose rather than treating all digits as ambiguous.
    """
    if not nd["all_parse"]:
        return False
    vals = projected.dropna().astype(str).str.replace(r"^[+-]", "", regex=True)
    lens = vals.str.replace(r"\.0+$", "", regex=True).str.len()
    if not len(lens):
        return False
    return bool(lens.between(min(_COMPACT_DATE_DIGITS), max(_COMPACT_DATE_DIGITS)).all())


def probe_coercion(projected: pd.Series) -> Dict[str, Any]:
    """Decide whether one already-hygienised string column may become numbers or
    timestamps -- and, when it may not, say exactly why and show the evidence.

    Every hold below is a case where the conversion would return a value the file
    does not contain, so each one is a question for a human rather than a default
    to be applied:

      leading_zero      "02134" -> 2134 deletes the zero and merges two postcodes
      currency_or_rate  "$1,200" / "12%" -- strip the symbol or divide by 100?
      numeric_or_date   "20240115" -- the integer, or 2024-01-15?
      mixed_with_text   90% numbers and 10% "unknown" -- the 10% would become NaN,
                        and a recorded category would be indistinguishable from a
                        value that was never collected
    """
    nn = projected.dropna()
    if not len(nn):
        return {"interesting": False, "auto_numeric": False, "auto_date": False, "hold": None}

    # A date is short. Running to_datetime over a field of 2,000-character
    # free text cannot produce a useful answer and is not cheap, so the probe is
    # skipped on length rather than on a sample.
    if int(nn.astype(str).str.len().max()) > _LONG_STRING_CUTOFF:
        return {"interesting": False, "auto_numeric": False, "auto_date": False, "hold": None}

    num, nd = numeric_view(projected)
    _, dd = date_view(projected)

    interesting = bool(nd["all_parse"] or nd["n_parsed"] > 0
                       or nd["has_currency_or_percent"]
                       or dd["all_parse"] or dd["n_parsed"] > 0)
    if not interesting:
        return {"interesting": False, "auto_numeric": False, "auto_date": False, "hold": None}

    auto_numeric = False
    auto_date = False
    hold = None

    if nd["all_parse"] and dd["all_parse"] and _looks_compact_date(projected, nd):
        hold = "numeric_or_date"
    elif nd["all_parse"]:
        if nd["leading_zero_suspected_id"]:
            hold = "leading_zero"
        elif nd["has_currency_or_percent"]:
            hold = "currency_or_rate"
        else:
            auto_numeric = True
    elif dd["all_parse"]:
        auto_date = True
    elif nd["has_currency_or_percent"] and (nd["would_parse_after_symbol_strip"] or 0.0) >= 1.0:
        hold = "currency_or_rate"
    elif nd["n_parsed"] > 0:
        hold = "mixed_with_text"

    out: Dict[str, Any] = {
        "interesting": True,
        "auto_numeric": auto_numeric,
        "auto_date": auto_date,
        "hold": hold,
        "numeric": nd,
        "date": dd,
    }
    if auto_numeric:
        out["role_hint"] = "numeric"
    elif auto_date:
        out["role_hint"] = "datetime"
    elif hold == "leading_zero":
        out["role_hint"] = "identifier"
    return out


def profile_columns(df: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    n = int(len(df))
    for col in df.columns:
        s = df[col]
        n_missing = int(s.isna().sum())
        n_unique = int(s.nunique(dropna=True))
        role = column_role(s)
        entry: Dict[str, Any] = {
            "dtype": str(s.dtype),
            "role": role,
            "n": n,
            "n_missing": n_missing,
            "n_unique": n_unique,
            "missing_pct": round(n_missing / max(n, 1) * 100, 2),
        }

        if role == "numeric":
            v = s.dropna()
            if len(v):
                entry.update({
                    "min": _sf(v.min()), "max": _sf(v.max()),
                    "mean": _sf(v.mean()), "median": _sf(v.median()),
                    "std": _sf(v.std()), "skew": _sf(v.skew()),
                    "zeros": int((v == 0).sum()),
                    "negatives": int((v < 0).sum()),
                    "n_outliers_iqr15": int(_iqr_outliers(v)),
                })
        elif role in ("categorical", "binary"):
            if is_string_like(s.dtype):
                v = s.dropna().astype(str)
                lens = v.str.len()
                if len(v):
                    entry.update({
                        "min_len": int(lens.min()), "max_len": int(lens.max()),
                        "mean_len": _sf(lens.mean()),
                        "top": {str(k): int(vv) for k, vv in v.value_counts().head(5).items()},
                    })
                # Case-variant detection runs on TWO views of the column, because
                # the answer genuinely differs and only the second one is true at
                # execution time. Whitespace stripping runs before case folding, so
                # a column that looks like 9 distinct levels on raw input is really
                # 6 by the time the case-merge op sees it. Reporting only the raw
                # count would make the report's disclosure disagree with the
                # cleaning that actually ran, which is the one thing this pipeline
                # must never do.
                cv_raw = residual_case_variants(s)
                if cv_raw:
                    entry["residual_case_variants_raw"] = cv_raw
                projected = hygiene_project(s)
                cv_post = fold_case_map(projected)[1]
                if cv_post:
                    entry["residual_case_variants_post_hygiene"] = cv_post

                # Does this column merely FAIL to parse as a number or a date?
                # Reported for every categorical/binary string column because
                # "stored as text but really numeric" is the most common structural
                # defect, and eyeballing the top-5 values misses it whenever the
                # unparseable rows are not among the most frequent ones.
                coercion = probe_coercion(projected)
                if coercion["interesting"]:
                    entry["coercion"] = coercion
            else:
                v = s.dropna()
                if len(v):
                    entry["top"] = {str(k): int(vv) for k, vv in v.value_counts().head(5).items()}
        elif role == "text":
            v = s.dropna().astype(str)
            if len(v):
                entry.update({
                    "min_len": int(v.str.len().min()), "max_len": int(v.str.len().max()),
                    "mean_len": _sf(v.str.len().mean()),
                })
        elif role == "datetime":
            v = s.dropna()
            if len(v):
                entry.update({
                    "min_dt": str(v.min()), "max_dt": str(v.max()),
                    "n_unique_dt": int(v.nunique()),
                    "monotonic_increasing": bool(v.is_monotonic_increasing),
                })
        out[str(col)] = entry
    return out


def _iqr_outliers(s: pd.Series) -> int:
    v = s.astype(float)
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    iqr = q3 - q1
    if not np.isfinite(iqr) or iqr == 0:
        return 0
    return int(((v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)).sum())


def detect_anomalies(df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
    flags: list = []
    for col, e in profile.items():
        if e["n"] > 0 and e["n_unique"] <= 1:
            flags.append({"type": "constant_column", "column": col, "severity": "P3"})
        if e["missing_pct"] == 100:
            flags.append({"type": "all_missing", "column": col, "severity": "P1"})
        elif e["missing_pct"] >= 95:
            flags.append({"type": "near_all_missing", "column": col,
                          "severity": "P3", "value": e["missing_pct"]})
        cv = e.get("residual_case_variants_post_hygiene")
        if cv:
            flags.append({
                "type": "residual_case_variants", "column": col, "severity": "P2",
                "n_exact_levels": cv["n_exact_levels"],
                "n_after_casefold": cv["n_after_casefold"],
                "n_merged_groups": cv["n_merged_groups"],
                "n_exact_levels_raw": (e.get("residual_case_variants_raw") or {}).get("n_exact_levels"),
                "note": "levels still differ only by case AFTER the automatic whitespace "
                        "and quote hygiene; this is the state the case-merge op will see",
            })
        if e.get("negatives", 0) > 0 and e["role"] == "numeric" and e["min"] is not None:
            if col.lower().startswith(("sepal", "petal", "age", "height", "width", "length", "size", "count", "weight")):
                flags.append({"type": "impossible_negative", "column": col, "severity": "P1",
                              "n_negatives": e["negatives"], "min": e["min"]})
        if "min_dt" in e:
            try:
                y0 = pd.Timestamp(e["min_dt"]).year
                y1 = pd.Timestamp(e["max_dt"]).year
                if y0 < 1900 or y1 > 2100:
                    flags.append({"type": "suspicious_dates", "column": col, "severity": "P3",
                                  "min_year": int(y0), "max_year": int(y1)})
            except Exception:
                pass

    dup_n = int(df.duplicated().sum())
    if dup_n > 0:
        flags.append({"type": "duplicate_rows", "count": dup_n, "severity": "P1",
                      "pct": round(dup_n / max(len(df), 1) * 100, 2)})

    # likely identifier columns
    for col, e in profile.items():
        if e["role"] in ("categorical", "text") and e["n"] > 50:
            ratio = e["n_unique"] / e["n"]
            if ratio > 0.95 and e.get("mean_len", 0) >= 12:
                flags.append({"type": "likely_id_column", "column": col, "severity": "P3",
                              "uniqueness_ratio": round(ratio, 3)})
    return {"flags": flags, "n_flags": len(flags)}


def detect_candidates(df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Heuristics for the grouping column and the target/label column."""
    roles = {c: e["role"] for c, e in profile.items()}
    cats = [c for c, r in roles.items() if r in ("categorical", "binary")]

    group_cands = []
    rejected_as_group = []
    for c in cats:
        nu = profile[c]["n_unique"]
        # A column with fewer than two observed levels cannot divide anything.
        # Ranking it first is worse than not ranking it at all: the agent would
        # group by it and every comparison would come back "no difference"
        # between one group and itself. An all-null column scored highest of
        # all on this profile before the guard existed.
        if nu < 2:
            rejected_as_group.append({"column": c, "n_unique": nu,
                                      "reason": "fewer than 2 observed levels; cannot form groups"})
            continue
        # Prefer few groups, evenly sized. Balance is measured as entropy
        # normalised by log(k) so it lives in [0, 1] and stays comparable across
        # different level counts -- raw entropy otherwise rewards columns
        # merely for having more levels.
        balanced = 0.0
        n_levels_observed = 0
        try:
            vc = df[c].value_counts(dropna=True)
            n_levels_observed = int(len(vc))
            if len(vc) and vc.sum():
                pr = vc / vc.sum()
                h = float(-(pr * pr.map(lambda x: math.log(x) if x > 0 else 0.0)).sum())
                balanced = h / math.log(len(vc)) if len(vc) > 1 else 0.0
        except Exception:
            balanced = 0.0
        score = (1.0 / float(nu)) * (1.0 + balanced)
        group_cands.append({"column": c, "n_unique": nu, "balance_entropy": round(balanced, 4),
                            "n_levels_observed": n_levels_observed,
                            "score": round(score, 6)})
    group_cands.sort(key=lambda x: -x["score"])

    target_cands = []
    for c, e in profile.items():
        if e["role"] in ("numeric", "categorical", "binary") and 2 <= e["n_unique"] <= 20:
            target_cands.append({"column": c, "n_unique": e["n_unique"],
                                "score": round(1.0 / e["n_unique"], 6)})
    target_cands.sort(key=lambda x: -x["score"])

    return {
        "group_candidate": {"candidates": group_cands[:5],
                            "rejected": rejected_as_group,
                            "note": ("low cardinality balanced categorical column; balance is "
                                     "entropy normalised by log(levels), columns with fewer "
                                     "than 2 observed levels are excluded")},
        "target_candidate": {"candidates": target_cands[:5],
                             "note": "integer-coded class label or small-cardinality outcome"},
    }


def detect_timeseries(df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
    for col, e in profile.items():
        if "min_dt" not in e:
            continue
        if e.get("n_unique_dt", 0) < 30:
            continue
        try:
            ts = pd.to_datetime(df[col])
            freq = pd.infer_freq(ts.head(min(len(ts), 300))) if len(ts) >= 4 else None
        except Exception:
            freq = None
        return {"is_timeseries": True, "time_column": col,
                "n_unique": e["n_unique_dt"], "inferred_freq": freq}
    return {"is_timeseries": False}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n-sample", type=int, default=0)
    p.add_argument("--read-mode", choices=["text", "infer"], default="text",
                   help="text (default): read every cell as a string and let this skill "
                        "decide types, so every conversion is auditable. "
                        "infer: let pandas guess dtypes (faster, but the guess happens "
                        "before any audit exists and cannot be reviewed or undone)")
    args = p.parse_args()

    src = Path(args.inp)
    df = read_table(src, read_mode=args.read_mode)
    sampled = False
    if args.n_sample and len(df) > args.n_sample:
        df = df.sample(n=args.n_sample, random_state=42).reset_index(drop=True)
        sampled = True

    cols = profile_columns(df)
    anomalies = detect_anomalies(df, cols)
    cands = detect_candidates(df, cols)
    ts = detect_timeseries(df, cols)

    out = {
        "schema_version": "1.1",
        "source": str(src),
        "modality": "tabular",
        "sampled": sampled,
        "read_mode": args.read_mode,
        "shape": {"n_rows": int(df.shape[0]), "n_cols": int(df.shape[1])},
        "memory_bytes": int(df.memory_usage(deep=True).sum()),
        "columns": cols,
        "column_roles": {c: e["role"] for c, e in cols.items()},
        "anomalies": anomalies,
        "target_candidate": cands["target_candidate"],
        "group_candidate": cands["group_candidate"],
        "timeseries_candidate": ts,
        "independent_unit_hint": "row",
        "pandas_version": pd.__version__,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"profile written: {args.out}  ({df.shape[0]} rows x {df.shape[1]} cols, {anomalies['n_flags']} flags)")
    for f in anomalies["flags"]:
        print(f"   - [{f['severity']}] {f['type']}: {f.get('column', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
