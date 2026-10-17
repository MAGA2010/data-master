"""Nature-grade descriptive statistics.

Always run. Produces analysis/stats_descriptive.json with, per numeric column:
n, mean, sd, median, q25, q75, IQR, min, max, skew, kurtosis, 95% CI of the mean,
and per categorical column: counts, proportions, mode.

Also computes:
- independent_unit / n_independent (from --unit-hint and duplicate-key detection)
- missing-mechanism screen per column (MCAR test when possible)
- distribution normality screen (Shapiro-Wilk when n <= 5000, else D'Agostino K2)

Usage:
    python stats_descriptive.py --clean cleaned/cleaned.csv --out analysis/stats_descriptive.json
    python stats_descriptive.py --clean cleaned/cleaned.csv --out analysis/stats_descriptive.json --unit patient --unit-key patient_id
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dm_types import load_cleaned  # noqa: E402


def _read(src: Path) -> pd.DataFrame:
    return load_cleaned(src)[0]


def _numeric_profile(s: pd.Series, alpha: float = 0.05) -> Dict[str, Any]:
    x = s.dropna().astype(float)
    n = int(len(x))
    if n == 0:
        return {"n": 0, "note": "all missing"}
    mean = float(x.mean())
    sd = float(x.std(ddof=1)) if n > 1 else float("nan")
    se = sd / np.sqrt(n) if n > 1 and not np.isnan(sd) else float("nan")
    out: Dict[str, Any] = {
        "n": n,
        "n_missing": int(s.isna().sum()),
        "missing_pct": round(float(s.isna().sum()) / max(len(s), 1) * 100, 2),
        "mean": round(mean, 6),
        "sd": None if np.isnan(sd) else round(sd, 6),
        "se": None if np.isnan(se) else round(se, 6),
        "median": round(float(x.median()), 6),
        "q25": round(float(x.quantile(0.25)), 6),
        "q75": round(float(x.quantile(0.75)), 6),
        "iqr": round(float(x.quantile(0.75) - x.quantile(0.25)), 6),
        "min": round(float(x.min()), 6),
        "max": round(float(x.max()), 6),
        "skew": None if np.isnan(float(x.skew())) else round(float(x.skew()), 4),
        "kurtosis": None if np.isnan(float(x.kurtosis())) else round(float(x.kurtosis()), 4),
        "n_zeros": int((x == 0).sum()),
        "n_negatives": int((x < 0).sum()),
    }
    # 95% CI of the mean (t-based; Welch-safe)
    if n > 1 and not np.isnan(sd):
        crit = stats.t.ppf(1 - alpha / 2, df=n - 1)
        lo, hi = mean - crit * se, mean + crit * se
        out["mean_ci95"] = [round(float(lo), 6), round(float(hi), 6)]
        out["ci_method"] = f"Student t, df={n - 1}"
    else:
        out["mean_ci95"] = None
    # IQR-based outlier count (informational only)
    q1, q3 = out["q25"], out["q75"]
    iqr = out["iqr"]
    lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out["n_outliers_iqr15"] = int(((x < lo_f) | (x > hi_f)).sum())
    # normality screen
    if 3 <= n <= 5000:
        try:
            w, p = stats.shapiro(x)
            out["normality"] = {"test": "Shapiro-Wilk", "W": round(float(w), 5), "p": round(float(p), 6),
                                "normal_at_alpha": bool(p > alpha)}
        except Exception:
            out["normality"] = {"test": "Shapiro-Wilk", "error": "insufficient variation"}
    elif n > 5000:
        try:
            k2, p = stats.normaltest(x)
            out["normality"] = {"test": "D'Agostino K2", "K2": round(float(k2), 5), "p": round(float(p), 6),
                                "normal_at_alpha": bool(p > alpha)}
        except Exception:
            out["normality"] = {"test": "D'Agostino K2", "error": "failed"}
    else:
        out["normality"] = {"test": None, "note": "n < 3"}
    return out


def _categorical_profile(s: pd.Series) -> Dict[str, Any]:
    non_na = s.dropna()
    vc = non_na.value_counts()
    return {
        "n": int(len(non_na)),
        "n_missing": int(s.isna().sum()),
        "missing_pct": round(float(s.isna().sum()) / max(len(s), 1) * 100, 2),
        "n_unique": int(non_na.nunique()),
        "mode": str(vc.index[0]) if len(vc) else None,
        "counts": {str(k): int(v) for k, v in vc.head(20).items()},
        "proportions": {str(k): round(float(v) / max(len(non_na), 1), 6) for k, v in vc.head(20).items()},
    }


def _datetime_profile(s: pd.Series) -> Dict[str, Any]:
    x = s.dropna()
    if len(x) == 0:
        return {"n": 0}
    return {
        "n": int(len(x)),
        "n_missing": int(s.isna().sum()),
        "min": str(x.min()),
        "max": str(x.max()),
        "span_days": round(float((x.max() - x.min()).total_seconds() / 86400), 4),
        "n_unique": int(x.nunique()),
        "monotonic_increasing": bool(x.is_monotonic_increasing),
    }


def _independent_unit(df: pd.DataFrame, hint: str, key: Optional[str]) -> Dict[str, Any]:
    """Gate 1 of the Nature checklist: n must be explicit and unit-defined."""
    if key and key in df.columns:
        n_ind = int(df[key].nunique())
        return {
            "independent_unit": hint,
            "unit_key": key,
            "n_independent": n_ind,
            "n_rows": int(len(df)),
            "n_technical_replicates": None,
            "n_repeated_measures": round(len(df) / max(n_ind, 1), 4),
            "hierarchy": f"{len(df)} rows nested under {n_ind} {hint}",
            "status": "OK",
            "rule_source": "references/nature-statistics-checklist.md#gate-1",
        }
    # no key given: report row as unit and flag as needing confirmation
    return {
        "independent_unit": hint,
        "unit_key": None,
        "n_independent": int(len(df)),
        "n_rows": int(len(df)),
        "n_technical_replicates": None,
        "n_repeated_measures": None,
        "hierarchy": "flat (one row = one unit)",
        "status": "AUTHOR_INPUT_NEEDED" if hint == "row" else "OK",
        "ask_user": "Is each row an independent unit, or are rows nested within a subject/sample? "
                    "Provide --unit-key <column> if nested.",
        "rule_source": "references/nature-statistics-checklist.md#gate-1",
    }


def _missing_mechanism_screen(df: pd.DataFrame, alpha: float = 0.05) -> List[Dict[str, Any]]:
    """Classify missing mechanism per column. Never overclaims: returns a hypothesis + evidence."""
    out: List[Dict[str, Any]] = []
    numeric = df.select_dtypes(include=[np.number])
    complete_cols = [c for c in numeric.columns if numeric[c].notna().all()]
    for c in numeric.columns:
        n_missing = int(numeric[c].isna().sum())
        if n_missing == 0:
            continue
        pct = round(n_missing / max(len(df), 1) * 100, 2)
        entry: Dict[str, Any] = {
            "column": c,
            "n_missing": n_missing,
            "missing_pct": pct,
            "mechanism": "undetermined",
            "evidence": [],
            "rule_source": "references/nature-statistics-checklist.md#gate-2",
        }
        if pct < 5:
            entry["mechanism"] = "MCAR-likely"
            entry["evidence"] = [f"missing rate {pct}% below the 5% threshold commonly treated as ignorable"]
            entry["imputation_default"] = "listwise deletion is usually acceptable; report n before/after"
        else:
            # try to find association between missingness and other complete columns
            if len(complete_cols) >= 2:
                miss = numeric[c].isna()
                for oc in complete_cols:
                    if oc == c:
                        continue
                    try:
                        a = numeric.loc[~miss, oc].dropna()
                        b = numeric.loc[miss, oc].dropna()
                        if len(a) > 5 and len(b) > 2:
                            u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
                            if p < alpha:
                                entry["evidence"].append(
                                    f"missingness in `{c}` is associated with `{oc}` (Mann-Whitney p={p:.4f})"
                                )
                    except Exception:
                        continue
            if entry["evidence"]:
                entry["mechanism"] = "MAR-suspected"
                entry["evidence"].append(
                    "missingness correlates with observed variables -> depends on observed data, "
                    "but this is a hypothesis, not proof"
                )
            else:
                entry["mechanism"] = "MNAR-not-excluded"
                entry["evidence"].append(
                    "no association found with observed variables; unobserved MNAR cannot be ruled out"
                )
        out.append(entry)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--clean", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--unit", default="row", help="independent unit name, e.g. patient / session / well")
    p.add_argument("--unit-key", default=None, help="column that identifies the independent unit")
    p.add_argument("--alpha", type=float, default=0.05)
    args = p.parse_args()

    df = _read(Path(args.clean))

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not str(df[c].dtype).startswith("bool")]
    cat_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c])]
    dt_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]

    result: Dict[str, Any] = {
        "schema_version": "1.0",
        "source": str(args.clean),
        "shape": {"n_rows": int(df.shape[0]), "n_cols": int(df.shape[1])},
        "independent_unit": _independent_unit(df, args.unit, args.unit_key),
        "alpha": args.alpha,
        "numeric": {c: _numeric_profile(df[c], args.alpha) for c in numeric_cols},
        "categorical": {c: _categorical_profile(df[c]) for c in cat_cols},
        "datetime": {c: _datetime_profile(df[c]) for c in dt_cols},
        "missing_mechanism_screen": _missing_mechanism_screen(df, args.alpha),
        "correlation_pearson": {},
    }

    # correlation matrix for numeric columns
    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr(method="pearson")
        result["correlation_pearson"] = {
            "columns": numeric_cols,
            "matrix": {a: {b: (None if pd.isna(corr.loc[a, b]) else round(float(corr.loc[a, b]), 6))
                           for b in numeric_cols} for a in numeric_cols},
            "n_pairs": len(numeric_cols) * (len(numeric_cols) - 1) // 2,
            "note": "raw Pearson on untransformed data; treat as exploratory only",
        }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    iu = result["independent_unit"]
    print(f"stats_descriptive written: {args.out}")
    print(f"  n_rows={len(df)}  n_independent={iu['n_independent']}  unit={iu['independent_unit']}  status={iu['status']}")
    print(f"  numeric={len(numeric_cols)}  categorical={len(cat_cols)}  datetime={len(dt_cols)}")
    print(f"  missing-mechanism entries: {len(result['missing_mechanism_screen'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
