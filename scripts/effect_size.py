"""Effect sizes with confidence intervals. Nature Gate 3 requires effect size > p-value.

Computes:
- Cohen's d (pooled SD) + Hedges' g correction + 95% CI (bootstrap)
- Cliff's delta (non-parametric) + 95% CI (bootstrap)
- Odds ratio + 95% CI (Woolf) for 2x2 binary tables
- Point-biserial / Pearson r + 95% CI (Fisher z)
- Cramér's V for categorical association

Every estimate ships with a CI. Nothing here reports a bare effect magnitude.

Usage:
    python effect_size.py --clean cleaned/cleaned.csv --outcome sepal_length --group species --out analysis/effect_sizes.json
    python effect_size.py --clean cleaned/cleaned.csv --outcome survived --group sex --binary --out analysis/effect_sizes.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dm_types import load_cleaned  # noqa: E402

BOOT_N = 10000
SEED = 42


def _read(src: Path) -> pd.DataFrame:
    return load_cleaned(src)[0]


def cohens_d(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return {"estimable": False, "reason": "n < 2 in one group"}
    mx, my = np.mean(x), np.mean(y)
    sp2 = ((nx - 1) * np.var(x, ddof=1) + (ny - 1) * np.var(y, ddof=1)) / (nx + ny - 2)
    sp = math.sqrt(sp2)
    if sp == 0:
        return {"estimable": False, "reason": "zero pooled SD"}
    d = (mx - my) / sp
    # Hedges' g small-sample correction
    df = nx + ny - 2
    J = 1 - 3 / (4 * df - 1) if df > 1 else 1.0
    g = d * J
    # analytic CI for d
    se_d = math.sqrt((nx + ny) / (nx * ny) + d ** 2 / (2 * (nx + ny - 2)))
    lo_d = d - 1.96 * se_d
    hi_d = d + 1.96 * se_d
    return {
        "estimable": True,
        "cohens_d": round(float(d), 4),
        "hedges_g": round(float(g), 4),
        "ci95": [round(float(lo_d), 4), round(float(hi_d), 4)],
        "ci_method": "analytic (z approx)",
        "n1": nx, "n2": ny,
        "mean1": round(float(mx), 6), "mean2": round(float(my), 6),
        "magnitude": _d_magnitude(abs(d)),
        "n_zero_variance_groups": 0,
    }


def _d_magnitude(d: float) -> str:
    if d < 0.2:
        return "negligible"
    if d < 0.5:
        return "small"
    if d < 0.8:
        return "medium"
    return "large"


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return {"estimable": False, "reason": "empty group"}
    # efficient rank-based computation
    allv = np.concatenate([x, y])
    order = allv.argsort()
    ranks = np.empty(len(allv), dtype=float)
    ranks[order] = np.arange(1, len(allv) + 1)
    # handle ties with average ranks
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    if np.any(cnt > 1):
        sums = np.zeros(len(cnt))
        np.add.at(sums, inv, ranks)
        avg = sums / cnt
        ranks = avg[inv]
    rx = ranks[:nx].sum()
    u = rx - nx * (nx + 1) / 2
    delta = 2 * u / (nx * ny) - 1
    # bootstrap CI, fully vectorised across resamples
    rng = np.random.default_rng(SEED)
    B = BOOT_N
    bx = x[rng.integers(0, nx, size=(B, nx))]
    by = y[rng.integers(0, ny, size=(B, ny))]
    allv = np.concatenate([bx, by], axis=1)          # (B, nx+ny)
    order = np.argsort(allv, axis=1, kind="stable")
    ranks = np.empty_like(allv, dtype=float)
    np.put_along_axis(ranks, order,
                      np.broadcast_to(np.arange(1, nx + ny + 1, dtype=float), (B, nx + ny)), axis=1)
    # average ranks for ties, vectorised
    for b in range(B):
        row = allv[b]
        vals, inv, cnt = np.unique(row, return_inverse=True, return_counts=True)
        if np.any(cnt > 1):
            sums = np.zeros(len(cnt))
            np.add.at(sums, inv, ranks[b])
            ranks[b] = (sums / cnt)[inv]
    u = ranks[:, :nx].sum(axis=1) - nx * (nx + 1) / 2
    deltas = 2 * u / (nx * ny) - 1
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return {
        "estimable": True,
        "cliffs_delta": round(float(delta), 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "ci_method": f"bootstrap, {BOOT_N} resamples, seed={SEED}",
        "n1": nx, "n2": ny,
        "magnitude": _delta_magnitude(abs(delta)),
    }


def _delta_magnitude(d: float) -> str:
    if d < 0.147:
        return "negligible"
    if d < 0.33:
        return "small"
    if d < 0.474:
        return "medium"
    return "large"


def odds_ratio(binary_outcome: np.ndarray, group: np.ndarray) -> Dict[str, Any]:
    """2x2 odds ratio (group1 vs group0) with Woolf 95% CI."""
    levels = sorted(pd.unique(group))
    if len(levels) != 2:
        return {"estimable": False, "reason": f"need exactly 2 group levels, got {len(levels)}"}
    g1, g0 = levels[1], levels[0]
    pos_vals = sorted(pd.unique(binary_outcome))
    if len(pos_vals) != 2:
        return {"estimable": False, "reason": f"need binary outcome, got {len(pos_vals)} levels"}
    p1, p0 = pos_vals[1], pos_vals[0]
    a = int(np.sum((group == g1) & (binary_outcome == p1)))
    b = int(np.sum((group == g1) & (binary_outcome == p0)))
    c = int(np.sum((group == g0) & (binary_outcome == p1)))
    d_ = int(np.sum((group == g0) & (binary_outcome == p0)))
    if min(a, b, c, d_) == 0:
        # Haldane-Anscombe 0.5 correction
        a, b, c, d_ = a + 0.5, b + 0.5, c + 0.5, d_ + 0.5
        corrected = True
    else:
        corrected = False
    or_ = (a * d_) / (b * c)
    se_log = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d_)
    lo, hi = math.exp(math.log(or_) - 1.96 * se_log), math.exp(math.log(or_) + 1.96 * se_log)
    return {
        "estimable": True,
        "odds_ratio": round(float(or_), 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "ci_method": "Woolf log-OR" + (" with Haldane-Anscombe 0.5 correction" if corrected else ""),
        "table": {"g_pos": a, "g_neg": b, "ref_pos": c, "ref_neg": d_,
                  "group1": str(g1), "group0": str(g0)},
    }


def pearson_r(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    n = len(x)
    if n < 4:
        return {"estimable": False, "reason": "n < 4"}
    r, p = stats.pearsonr(x, y)
    if abs(r) >= 1.0:
        return {"estimable": False, "reason": "perfect correlation; CI undefined"}
    z = np.arctanh(r)
    se = 1 / math.sqrt(n - 3)
    lo, hi = np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)
    return {
        "estimable": True,
        "pearson_r": round(float(r), 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "ci_method": "Fisher z transform",
        "n": n,
        "r_squared": round(float(r ** 2), 4),
        "magnitude": _r_magnitude(abs(r)),
    }


def _r_magnitude(r: float) -> str:
    if r < 0.1:
        return "negligible"
    if r < 0.3:
        return "small"
    if r < 0.5:
        return "medium"
    return "large"


def cramers_v(table: pd.DataFrame) -> Dict[str, Any]:
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {"estimable": False, "reason": "need >= 2x2 table"}
    chi2, p, dof, _ = stats.chi2_contingency(table)
    n = table.values.sum()
    phi2 = chi2 / n
    r, k = table.shape
    # bias-corrected Cramer's V
    phi2corr = max(0.0, phi2 - ((k - 1) * (r - 1)) / (n - 1))
    rcorr = r - ((r - 1) ** 2) / (n - 1)
    kcorr = k - ((k - 1) ** 2) / (n - 1)
    denom = min(kcorr - 1, rcorr - 1)
    v = math.sqrt(phi2corr / denom) if denom > 0 else 0.0
    return {
        "estimable": True,
        "cramers_v": round(float(v), 4),
        "chi2": round(float(chi2), 4),
        "dof": int(dof),
        "p_raw": float(p),
        "magnitude": _v_magnitude(v),
        "shape": [int(r), int(k)],
    }


def _v_magnitude(v: float) -> str:
    if v < 0.1:
        return "negligible"
    if v < 0.3:
        return "small"
    if v < 0.5:
        return "medium"
    return "large"


def spearman_rho(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    n = len(x)
    if n < 4:
        return {"estimable": False, "reason": "n < 4"}
    rho, p = stats.spearmanr(x, y)
    out: Dict[str, Any] = {"estimable": True, "spearman_rho": round(float(rho), 4), "n": n,
                           "p_raw": float(p), "magnitude": _r_magnitude(abs(rho))}
    if abs(rho) < 1.0:
        z = np.arctanh(rho)
        se = 1 / math.sqrt(n - 3)
        out["ci95"] = [round(float(np.tanh(z - 1.96 * se)), 4), round(float(np.tanh(z + 1.96 * se)), 4)]
        out["ci_method"] = "Fisher z transform"
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--clean", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--outcome", required=True, help="numeric or binary outcome column")
    p.add_argument("--group", required=True, help="categorical grouping column")
    p.add_argument("--binary", action="store_true", help="outcome is binary -> use odds ratio")
    p.add_argument("--all-pairs", action="store_true", help="all pairwise group comparisons")
    args = p.parse_args()

    df = _read(Path(args.clean))
    outcome, group = args.outcome, args.group
    if outcome not in df.columns or group not in df.columns:
        print(f"ERROR: columns not found. available={list(df.columns)}")
        return 1

    result: Dict[str, Any] = {
        "schema_version": "1.0",
        "outcome": outcome,
        "group": group,
        "n_rows": int(len(df)),
        "comparisons": [],
        "rule_source": "references/nature-statistics-checklist.md#gate-3",
    }

    levels = sorted(pd.unique(df[group].dropna()))
    pairs = list(itertools.combinations(levels, 2)) if args.all_pairs else [(levels[0], levels[1])] if len(levels) >= 2 else []

    if args.binary:
        # pooled odds ratio across all levels using first as reference
        res = odds_ratio(df[outcome].values, df[group].values)
        result["pooled"] = res
    elif not pd.api.types.is_numeric_dtype(df[outcome]):
        # categorical outcome x categorical group -> Cramer's V
        table = pd.crosstab(df[group], df[outcome])
        result["cramers_v"] = cramers_v(table)
    else:
        for a, b in pairs:
            xa = df.loc[df[group] == a, outcome].dropna().astype(float).values
            xb = df.loc[df[group] == b, outcome].dropna().astype(float).values
            comp = {
                "group_a": str(a), "group_b": str(b),
                "n_a": len(xa), "n_b": len(xb),
                "cohens_d": cohens_d(xa, xb),
                "cliffs_delta": cliffs_delta(xa, xb),
            }
            result["comparisons"].append(comp)

        # continuous-continuous correlations across all numeric columns
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        corrs = []
        for i, j in itertools.combinations(num_cols, 2):
            sub = df[[i, j]].dropna()
            if len(sub) < 4:
                continue
            x, y = sub[i].astype(float).values, sub[j].astype(float).values
            corrs.append({
                "x": i, "y": j,
                "pearson": pearson_r(x, y),
                "spearman": spearman_rho(x, y),
            })
        result["correlations"] = corrs

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    n_comp = len(result["comparisons"]) or len(result.get("correlations", []))
    print(f"effect_size written: {args.out}  ({n_comp} comparisons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

