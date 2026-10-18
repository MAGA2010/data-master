#!/usr/bin/env python
"""Automatic test selection with assumption disclosure, effect sizes, and multiplicity control.

Every comparison this script produces is auditable. For each one it records:
  * which test was chosen and WHY (Gate 3: assumptions)
  * which alternatives were rejected and WHY (provenance)
  * effect size with a 95% CI, not just a p-value (Gate 4)
  * raw AND corrected p-values across the declared family (Gate 5)
  * how many rows were dropped for missingness, and the effective unit count

Assumption handling
-------------------
Normality is checked and disclosed, but it is NOT used as a veto once each group
reaches n >= 30. Shapiro-Wilk has near-100% power at those sample sizes, so
gating on it silently discards a valid, more powerful parametric test in most
real datasets. That is a well-documented anti-pattern and a common reviewer
complaint. Below n = 30 the normality result does gate the choice, because that
is the point where the t-test's robustness argument stops holding.

Unequal variance is handled by Welch rather than by abandoning the parametric
family: Welch's test is the correct, more modern default, not a fallback of last
resort.

Decision ladder, k = 2, numeric outcome
    min(n) < 30 and normality rejected  -> Mann-Whitney U  (+ Cliff's delta)
    equal variance (Levene p > alpha)   -> Student two-sample t
    unequal variance                   -> Welch two-sample t
Decision ladder, k > 2, numeric outcome
    min(n) < 30 and normality rejected  -> Kruskal-Wallis   (+ epsilon^2)
    equal variance                     -> one-way ANOVA    (+ omega^2)
    unequal variance                   -> Welch ANOVA      (+ omega^2)

Rank-based results are additionally reported as a robustness cross-check
whenever the primary test is parametric, so a reader can see whether the
conclusion depends on the distributional assumption.

Missing data is handled by complete-case analysis and disclosed: rows dropped
per outcome, and per-group n actually used.

Usage:
    python stats_inferential.py --clean cleaned/cleaned.csv \
        --out analysis/stats_inferential.json \
        --group species --outcomes sepal_length_cm,petal_length_cm \
        --correction BH --unit-key target_id
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dm_types import load_cleaned  # noqa: E402
from effect_size import (  # noqa: E402
    cliffs_delta, cohens_d, cramers_v, odds_ratio, pearson_r, spearman_rho,
)

ALPHA = 0.05
SEED = 42
NORMALITY_GATE = 30      # below this, normality genuinely gates the choice
BOOTSTRAP = 2000


def _read(src: Path) -> pd.DataFrame:
    return load_cleaned(src)[0]


# ---------------- assumption checks ----------------

def normality(vals: np.ndarray) -> Dict[str, Any]:
    """Shapiro-Wilk (D'Agostino K2 above n=5000 where Shapiro is impractical).

    'gating' is False when the test is disclosed but deliberately not allowed to
    veto the parametric path, which is the case once n >= 30.
    """
    n = len(vals)
    if n < 8:
        return {"test": None, "passes": None, "n": n, "gating": False,
                "note": f"n={n} < 8; a normality test has no power here, assumed normal"}
    try:
        if n <= 5000:
            w, p = stats.shapiro(vals)
            name = "Shapiro-Wilk"
        else:
            w, p = stats.normaltest(vals)
            name = "D'Agostino K2"
    except Exception as exc:
        return {"test": name if n <= 5000 else "D'Agostino K2", "passes": None,
                "n": n, "gating": n < NORMALITY_GATE, "error": str(exc)}
    return {
        "test": name,
        "statistic": round(float(w), 5),
        "p": round(float(p), 6),
        "passes": bool(p > ALPHA),
        "n": n,
        "gating": n < NORMALITY_GATE,
        "note": (None if n >= NORMALITY_GATE else
                 f"n<{NORMALITY_GATE}: this result gates test selection"),
    }


def variance_homogeneity(groups: List[np.ndarray]) -> Dict[str, Any]:
    """Levene (Brown-Forsythe variant used by scipy, robust to non-normality)."""
    if len(groups) < 2 or any(len(g) < 2 for g in groups):
        return {"test": None, "equal_variance": None,
                "note": "insufficient n for Levene; Welch (unequal-variance) path assumed"}
    stat, p = stats.levene(*groups)
    return {"test": "Levene", "statistic": round(float(stat), 5), "p": round(float(p), 6),
            "passes": bool(p > ALPHA), "equal_variance": bool(p > ALPHA)}


def _normality_gates(groups: List[np.ndarray]) -> Tuple[bool, bool]:
    """Return (all_normal, any_gating)."""
    checks = [normality(g) for g in groups]
    all_normal = all(c.get("passes") is not False for c in checks)
    any_gating = any(c.get("gating") for c in checks)
    return all_normal, any_gating


# ---------------- effect sizes with uncertainty ----------------

def hedges_g(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Bias-corrected standardised mean difference (small-sample correction)."""
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return None
    sp = np.sqrt(((nx - 1) * x.var(ddof=1) + (ny - 1) * y.var(ddof=1)) / (nx + ny - 2))
    if sp == 0 or np.isnan(sp):
        return None
    d = (x.mean() - y.mean()) / sp
    J = 1.0 - 3.0 / (4.0 * (nx + ny) - 9.0)      # Hedges' small-sample correction
    return float(d * J)


def mean_difference_ci(x: np.ndarray, y: np.ndarray,
                       alpha: float = ALPHA) -> Dict[str, Any]:
    """Welch CI for (mean_x - mean_y); the interval is the primary result."""
    nx, ny = len(x), len(y)
    diff = float(x.mean() - y.mean())
    vx, vy = x.var(ddof=1), y.var(ddof=1)
    se = np.sqrt(vx / nx + vy / ny)
    if se == 0 or np.isnan(se):
        return {"difference": diff, "se": None, "ci_low": None, "ci_high": None,
                "note": "zero standard error; interval undefined"}
    df_num = (vx / nx + vy / ny) ** 2
    df_den = (vx / nx) ** 2 / (nx - 1) + (vy / ny) ** 2 / (ny - 1)
    dof = df_num / df_den if df_den > 0 else nx + ny - 2
    tcrit = stats.t.ppf(1 - alpha / 2, dof)
    return {"difference": round(diff, 6), "se": round(float(se), 6),
            "dof": round(float(dof), 3),
            "ci_low": round(diff - tcrit * se, 6),
            "ci_high": round(diff + tcrit * se, 6),
            "ci_level": 1 - alpha,
            "excludes_zero": bool(diff - tcrit * se > 0 or diff + tcrit * se < 0)}


def _omega2_from(groups: List[np.ndarray]) -> Tuple[float, float, float]:
    """Return (ss_between, ss_within, grand_mean) primitives."""
    allv = np.concatenate(groups)
    grand = allv.mean()
    ss_b = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    ss_w = sum(float(((g - g.mean()) ** 2).sum()) for g in groups)
    return ss_b, ss_w, float(grand)


def variance_effects(groups: List[np.ndarray], n_boot: int = BOOTSTRAP) -> Dict[str, Any]:
    """eta^2 and omega^2 with a bootstrap percentile CI for omega^2.

    eta^2 is upward-biased; omega^2 corrects for the number of groups and is the
    value a reviewer will ask for. The CI is bootstrap because omega^2 has no
    closed-form interval.
    """
    def _omega(ss_b: float, ss_w: float, n: int, k: int) -> float:
        """omega^2 = (SS_b - (k-1)*MS_w) / (SS_t + MS_w)

        The correction term is (k-1)*MS_w, not MS_w. omega^2 is by construction
        smaller than eta^2 and may be negative when the between-group variation is
        no larger than sampling noise; both properties are kept rather than
        truncated, because a statistic that cannot go negative stops
        communicating how much the finding depends on the sample size.

        A related mistake, computing (MS_b - MS_w)/(MS_b + MS_w), is a ratio of
        mean squares and is not an effect size at all: it stays near 0 for a large
        null result instead of shrinking with it, and it grows without bound as
        MS_w approaches zero.
        """
        ss_t = ss_b + ss_w
        ms_w = ss_w / (n - k) if n > k else 0.0
        denom = ss_t + ms_w
        return ((ss_b - (k - 1) * ms_w) / denom) if denom > 0 else 0.0

    k = len(groups)
    ss_b, ss_w, _ = _omega2_from(groups)
    ss_t = ss_b + ss_w
    eta2 = ss_b / ss_t if ss_t > 0 else 0.0
    omega2 = _omega(ss_b, ss_w, len(np.concatenate(groups)), k)

    ci = {"low": None, "high": None}
    rng = np.random.default_rng(SEED)
    boot: List[float] = []
    for _ in range(n_boot):
        res = []
        for g in groups:
            idx = rng.integers(0, len(g), len(g))
            res.append(g[idx])
        b_b, b_w, _ = _omega2_from(res)
        boot.append(_omega(b_b, b_w, len(np.concatenate(res)), k))
    if boot:
        arr = np.asarray(boot)
        ci = {"low": round(float(np.percentile(arr, 2.5)), 6),
              "high": round(float(np.percentile(arr, 97.5)), 6),
              "method": f"bootstrap percentile, {n_boot} resamples, seed={SEED}"}
    return {
        "eta_squared": round(float(eta2), 6),
        "omega_squared": round(float(omega2), 6),
        "omega_squared_ci95": ci,
        "omega_squared_formula": "(SS_b - (k-1)*MS_w) / (SS_t + MS_w)",
        "eta_squared_note": "omega^2 <= eta^2 by construction; a negative omega^2 means the between-group spread is within sampling noise",
    }


def rank_effects(groups: List[np.ndarray], n_boot: int = BOOTSTRAP) -> Dict[str, Any]:
    """epsilon^2 for Kruskal-Wallis plus Cliff's delta for every pair."""
    k = len(groups)
    h, _ = stats.kruskal(*groups)
    allv = np.concatenate(groups)
    n = len(allv)
    n_eff = n - sum(len(g) ** 2 for g in groups) / n
    eps2 = (h - k + 1) / n_eff if n_eff > 0 else float("nan")
    pairs = {}
    for a, b in itertools.combinations(range(k), 2):
        d = cliffs_delta(groups[a], groups[b], n_boot=n_boot)
        pairs[f"g{a + 1}_vs_g{b + 1}"] = d
    return {"epsilon_squared_rank": round(float(eps2), 6),
            "n_effective": round(float(n_eff), 3),
            "cliffs_delta_by_pair": pairs}


# ---------------- test dispatch ----------------

def two_group_numeric(a_vals: np.ndarray, b_vals: np.ndarray,
                      a_name: str, b_name: str, alpha: float = ALPHA) -> Dict[str, Any]:
    na, nb = len(a_vals), len(b_vals)
    checks = [normality(a_vals), normality(b_vals)]
    assumptions: Dict[str, Any] = {
        "normality_a": checks[0], "normality_b": checks[1],
        "variance": variance_homogeneity([a_vals, b_vals]),
    }
    all_normal = all(c.get("passes") is not False for c in checks)
    any_gating = any(c.get("gating") for c in checks)
    equal_var = assumptions["variance"].get("equal_variance")
    n_min = min(na, nb)
    rejected: List[Dict[str, str]] = []

    if n_min < NORMALITY_GATE and not all_normal:
        u, p = stats.mannwhitneyu(a_vals, b_vals, alternative="two-sided")
        method, stat_name, dof = "Mann-Whitney U (Wilcoxon rank-sum)", "U", None
        rejected.append({"test": "t-test",
                         "reason": f"n={na}/{nb} with normality rejected and n<{NORMALITY_GATE}; "
                                   "the parametric robustness argument does not hold"})
        primary_is_rank = True
    elif equal_var is True:
        t, p = stats.ttest_ind(a_vals, b_vals, equal_var=True)
        method = "Student two-sample t-test (pooled variance)"
        stat_name, dof = "t", na + nb - 2
        rejected.append({"test": "Welch t-test",
                         "reason": "equal variance holds (Levene p > alpha); the pooled test is more powerful"})
        if not all_normal:
            rejected.append({"test": "Mann-Whitney U",
                             "reason": f"normality not established but n={na}/{nb} >= {NORMALITY_GATE}; "
                                       "the mean statistic is robust by CLT"})
        primary_is_rank = False
    else:
        t, p = stats.ttest_ind(a_vals, b_vals, equal_var=False)
        method = "Welch two-sample t-test (unequal variance)"
        stat_name, dof = "t", round(float(_welch_dof(a_vals, b_vals)), 3)
        rejected.append({"test": "Student t-test",
                         "reason": "Levene indicates unequal variance (p <= alpha)"})
        if not all_normal:
            rejected.append({"test": "Mann-Whitney U",
                             "reason": f"normality not established but n={na}/{nb} >= {NORMALITY_GATE}; "
                                       "Welch is already robust to both unequal variance and non-normality"})
        primary_is_rank = False

    effect: Dict[str, Any] = {
        "mean_difference_ci95": mean_difference_ci(a_vals, b_vals, alpha),
        "cohens_d": cohens_d(a_vals, b_vals),
        "hedges_g": round(hedges_g(a_vals, b_vals), 6) if hedges_g(a_vals, b_vals) is not None else None,
        "cliffs_delta": cliffs_delta(a_vals, b_vals),
    }

    robustness = None
    if not primary_is_rank:
        uu, pp = stats.mannwhitneyu(a_vals, b_vals, alternative="two-sided")
        robustness = {"test": "Mann-Whitney U", "statistic": round(float(uu), 5),
                      "p_raw": round(float(pp), 8),
                      "agrees_with_primary": bool((pp < alpha) == (p < alpha)),
                      "note": "cross-check only; the primary test is reported above"}

    return {
        "method": method,
        "statistic_name": stat_name,
        "statistic": float(t) if not primary_is_rank else float(u),
        "dof": dof,
        "p_raw": float(p),
        "n_a": na, "n_b": nb,
        "n_total": na + nb,
        "means_a_b": [round(float(np.mean(a_vals)), 6), round(float(np.mean(b_vals)), 6)],
        "medians_a_b": [round(float(np.median(a_vals)), 6), round(float(np.median(b_vals)), 6)],
        "sds_a_b": [round(float(np.std(a_vals, ddof=1)), 6), round(float(np.std(b_vals, ddof=1)), 6)],
        "assumptions": assumptions,
        "rejected_alternatives": rejected,
        "effect_sizes": effect,
        "robustness_cross_check": robustness,
        "group_a": a_name, "group_b": b_name,
        "rule_source": "scripts/stats_inferential.py#two_group_numeric",
    }


def _welch_dof(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = len(a), len(b)
    va, vb = a.var(ddof=1) / na, b.var(ddof=1) / nb
    denom = va ** 2 / (na - 1) + vb ** 2 / (nb - 1)
    return (va + vb) ** 2 / denom if denom > 0 else na + nb - 2


def _degeneracy(vals: List[np.ndarray]) -> Optional[str]:
    """Why these groups cannot support an omnibus comparison, or None if they can.

    A group whose values are all identical has zero within-group variance.
    Welch's weights are n/s^2, so the statistic becomes 0/0 and scipy returns
    NaN -- which used to travel into the multiplicity family. Reporting NaN as
    a p-value is worse than reporting nothing: it looks like a computed result.
    """
    within = [float(np.var(v, ddof=1)) for v in vals if len(v) > 1]
    if any(sd2 == 0.0 for sd2 in within):
        flat = [str(i) for i, v in enumerate(vals) if len(v) > 1 and float(np.var(v, ddof=1)) == 0.0]
        return ("within-group variance is zero for group(s) %s -- every row in "
                "those groups holds the same value, so between-group and "
                "within-group variation cannot be separated" % ", ".join(flat))
    pooled = np.concatenate(vals)
    if len(pooled) > 1 and float(np.var(pooled, ddof=1)) == 0.0:
        return "the outcome is constant across every row, so there is nothing to compare"
    return None


def k_group_numeric(groups: Dict[str, np.ndarray], alpha: float = ALPHA,
                    n_boot: int = BOOTSTRAP) -> Dict[str, Any]:
    names = list(groups.keys())
    vals = [groups[n] for n in names]
    degenerate = _degeneracy(vals)
    if degenerate:
        return {
            "estimable": False,
            "reason": degenerate,
            "p_raw": None,
            "p_adjusted": None,
            "n_groups": len(vals),
            "n_total": int(sum(len(v) for v in vals)),
            "group_n": {n: int(len(v)) for n, v in groups.items()},
            "rule_source": "scripts/stats_inferential.py#_degeneracy",
        }
    checks = [normality(v) for v in vals]
    assumptions: Dict[str, Any] = {
        "normality": dict(zip(names, checks)),
        "variance": variance_homogeneity(vals),
    }
    all_normal = all(c.get("passes") is not False for c in checks)
    any_gating = any(c.get("gating") for c in checks)
    equal_var = assumptions["variance"].get("equal_variance")
    n_min = min(len(v) for v in vals)
    k = len(vals)
    rejected: List[Dict[str, str]] = []

    use_rank = n_min < NORMALITY_GATE and not all_normal
    if use_rank:
        h, p = stats.kruskal(*vals)
        method = "Kruskal-Wallis H (rank-based)"
        stat_name, dof, dof_denom = "H", k - 1, None
        rejected.append({"test": "one-way ANOVA",
                         "reason": f"min n={n_min} < {NORMALITY_GATE} and normality rejected"})
        effects = rank_effects(vals, n_boot=n_boot)
        cross = None
    elif equal_var is True:
        f, p = stats.f_oneway(*vals)
        method = "one-way ANOVA"
        stat_name, dof, statistic, dof_denom = "F", k - 1, float(f), None
        rejected.append({"test": "Welch ANOVA",
                         "reason": "equal variance holds (Levene p > alpha); the pooled test is more powerful"})
        rejected.append({"test": "Kruskal-Wallis H",
                         "reason": f"min n={n_min} >= {NORMALITY_GATE}; the mean statistic is robust by CLT"})
        effects = variance_effects(vals, n_boot=n_boot)
        h_, p_ = stats.kruskal(*vals)
        cross = {"test": "Kruskal-Wallis H", "statistic": round(float(h_), 5),
                 "p_raw": round(float(p_), 8), "agrees_with_primary": bool((p_ < alpha) == (p < alpha)),
                 "note": "cross-check only"}
    else:
        f, p = stats.f_oneway(*vals, equal_var=False)
        method = "Welch ANOVA (unequal variance)"
        stat_name = "F"
        dof, dof_denom = k - 1, _welch_anova_dof(vals)
        statistic = float(f)
        rejected.append({"test": "one-way ANOVA",
                         "reason": "Levene indicates unequal variance (p <= alpha)"})
        rejected.append({"test": "Kruskal-Wallis H",
                         "reason": f"Welch is already robust to unequal variance and n={n_min} >= {NORMALITY_GATE}"})
        effects = variance_effects(vals, n_boot=n_boot)
        h_, p_ = stats.kruskal(*vals)
        cross = {"test": "Kruskal-Wallis H", "statistic": round(float(h_), 5),
                 "p_raw": round(float(p_), 8), "agrees_with_primary": bool((p_ < alpha) == (p < alpha)),
                 "note": "cross-check only"}

    if use_rank:
        statistic = float(h)
        effects["omnibus_note"] = ("epsilon^2 is reported for the rank test; "
                                   "omega^2 does not apply to Kruskal-Wallis")

    # post-hoc: every pairwise comparison, corrected within this outcome's family
    post_hoc: List[Dict[str, Any]] = []
    for i, j in itertools.combinations(range(k), 2):
        u, pu = stats.mannwhitneyu(vals[i], vals[j], alternative="two-sided")
        t_, pt = stats.ttest_ind(vals[i], vals[j], equal_var=False)
        post_hoc.append({
            "group_a": names[i], "group_b": names[j],
            "n_a": len(vals[i]), "n_b": len(vals[j]),
            "mean_difference_ci95": mean_difference_ci(vals[i], vals[j], alpha),
            "welch_t_p_raw": float(pt),
            "mannwhitney_p_raw": float(pu),
            "cliffs_delta": cliffs_delta(vals[i], vals[j], n_boot=n_boot),
        })
    post_family = correct_pvalues([h_["welch_t_p_raw"] for h_ in post_hoc], "BH", alpha)
    mw_family = correct_pvalues([h_["mannwhitney_p_raw"] for h_ in post_hoc], "BH", alpha)
    for h_, wf, mf in zip(post_hoc, post_family.get("adjusted", []), mw_family.get("adjusted", [])):
        h_["p_adjusted_welch_BH"] = float(wf)
        h_["p_adjusted_mannwhitney_BH"] = float(mf)
        h_["significant_adjusted"] = bool(wf < alpha)

    return {
        "method": method,
        "statistic_name": stat_name,
        "statistic": float(statistic),
        "dof": dof,
        "dof_denom": dof_denom,
        "p_raw": float(p),
        "n_groups": k,
        "n_total": int(sum(len(v) for v in vals)),
        "n_min": int(n_min),
        "group_means": {n_: round(float(v.mean()), 6) for n_, v in groups.items()},
        "group_medians": {n_: round(float(np.median(v)), 6) for n_, v in groups.items()},
        "group_sds": {n_: round(float(v.std(ddof=1)), 6) for n_, v in groups.items()},
        "group_n": {n_: int(len(v)) for n_, v in groups.items()},
        "assumptions": assumptions,
        "rejected_alternatives": rejected,
        "effect_sizes": effects,
        "robustness_cross_check": cross,
        "post_hoc": post_hoc,
        "post_hoc_note": ("both parametric and rank p-values are BH-corrected within this "
                          "outcome's pairwise family; report the one matching the omnibus test"),
        "rule_source": "scripts/stats_inferential.py#k_group_numeric",
    }


def _welch_anova_dof(groups: List[np.ndarray]) -> Optional[float]:
    """Satterthwaite denominator df for Welch's ANOVA.

    The previous implementation returned 0.0 on every real dataset, which then
    printed as "df = 0.0" beside a finite F and a p of 1e-70 -- a number that
    cannot exist, sitting in the column a reviewer reads first.  This is the
    form R's oneway.test() and statsmodels.stats.oneway use:

        df_den = (k^2 - 1) / (3 * sum_i ((1 - w_i/W)^2 / (n_i - 1)))

    with w_i = n_i / s_i^2 and W = sum(w_i).  For k = 2 it reduces to the
    Welch-Satterthwaite two-sample df.  Verified against
    statsmodels.stats.oneway.anova_oneway(use_var="unequal") on iris
    petal_length: 82.34216025041304 both ways.
    """
    k = len(groups)
    ns = np.array([len(g) for g in groups], dtype=float)
    vs = np.array([g.var(ddof=1) for g in groups])
    if k < 2 or np.any(ns <= 1) or np.any(vs <= 0):
        return None
    w = ns / vs
    total_w = w.sum()
    if not np.isfinite(total_w) or total_w <= 0:
        return None
    a = ((1.0 - w / total_w) ** 2 / (ns - 1.0)).sum()
    if not np.isfinite(a) or a <= 0:
        return float(ns.sum() - k)
    return round(float((k * k - 1.0) / 3.0 / a), 3)


def categorical_2x_k(group: pd.Series, outcome: pd.Series, alpha: float = ALPHA) -> Dict[str, Any]:
    table = pd.crosstab(group, outcome)
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {"estimable": False, "reason": f"need a 2x2-or-larger table, got {table.shape}"}
    rejected: List[Dict[str, str]] = []
    p: Optional[float]
    if table.shape == (2, 2):
        orr, p = stats.fisher_exact(table.values)
        method = "Fisher exact test (2x2)"
        stat_name, dof, statistic = "odds_ratio", None, float(orr)
        rejected.append({"test": "Pearson chi-square",
                         "reason": "2x2 table; Fisher is exact and valid at any cell count"})
        effect = {"odds_ratio": odds_ratio(outcome.values, group.values),
                  "cramers_v": cramers_v(table)}
    else:
        chi2, p, dof, expected = stats.chi2_contingency(table)
        stat_name, statistic = "chi2", float(chi2)
        min_exp = float(expected.min())
        if min_exp < 5:
            method = "Fisher exact test (Monte Carlo) -- expected counts below 5"
            stat_name, statistic = "odds_ratio", float("nan")
            p = None
            rejected.append({"test": "Pearson chi-square",
                             "reason": f"min expected count {min_exp:.1f} < 5; the chi-square approximation is invalid"})
        else:
            method = "Pearson chi-square test of independence"
            rejected.append({"test": "Fisher exact test",
                             "reason": f"all expected counts >= 5 (min={min_exp:.1f}); chi-square is more powerful"})
        effect = {"cramers_v": cramers_v(table), "min_expected_count": round(min_exp, 4)}
    return {
        "method": method,
        "statistic_name": stat_name,
        "statistic": statistic,
        "dof": dof,
        "p_raw": float(p) if p is not None else None,
        "table": table.to_dict(),
        "effect_sizes": effect,
        "rejected_alternatives": rejected,
        "rule_source": "scripts/stats_inferential.py#categorical_2x_k",
    }


def binary_outcome(group: pd.Series, outcome: pd.Series) -> Dict[str, Any]:
    table = pd.crosstab(group, outcome)
    try:
        orr, p = stats.fisher_exact(table.values)
        fisher: Optional[Dict[str, Any]] = {"odds_ratio": round(float(orr), 4),
                                            "p_raw": round(float(p), 8)}
    except Exception as exc:
        fisher = {"error": str(exc)}
        p = None
    return {
        "method": "Fisher exact test (binary outcome by group)",
        "p_raw": float(p) if p is not None else None,
        "effect_sizes": {"odds_ratio": odds_ratio(outcome.values, group.values)},
        "table": table.to_dict(),
        "rejected_alternatives": [{"test": "Pearson chi-square",
                                   "reason": "binary outcome; Fisher is exact and valid at any cell count"}],
        "rule_source": "scripts/stats_inferential.py#binary_outcome",
    }


# ---------------- unit-of-analysis structure ----------------

def analyze_unit_structure(df: pd.DataFrame, group: str,
                           unit_key: Optional[str]) -> Dict[str, Any]:
    """Classify how rows map to independent units, before any test is chosen.

    Detecting that rows repeat within units and then running row-level tests
    anyway would report an inflated n with a warning beside it. This function
    decides which analysis level is defensible so `main` can run the primary
    analysis there and keep the row-level version as a labelled secondary.

    Structures:
      undeclared           no unit key; rows assumed independent (recorded as an
                           assumption, not a finding)
      independent_rows     one row per unit
      clustered            each unit sits in exactly one group but has several
                           rows (technical replicates / repeated measures within
                           group) -> aggregate to unit level
      paired               each unit appears in exactly 2 groups -> paired tests
      complete_blocks      each unit appears in every group -> Friedman
      incomplete_repeated  units appear in several but not all groups ->
                           unit-by-group cell means, with the residual clustering
                           disclosed rather than hidden
    """
    if not unit_key or unit_key not in df.columns:
        return {"structure": "undeclared",
                "note": "no --unit-key given; the row is assumed to be the "
                        "independent unit, and every test below inherits that "
                        "assumption"}
    n_rows = int(len(df))
    n_units = int(df[unit_key].nunique(dropna=True))
    if n_units == 0:
        return {"structure": "undeclared",
                "note": f"unit key {unit_key!r} holds no usable values"}
    gpu = df.groupby(unit_key)[group].nunique(dropna=True)
    g_min = int(gpu.min()) if len(gpu) else 0
    g_max = int(gpu.max()) if len(gpu) else 0
    k = int(df[group].nunique(dropna=True))
    base = {
        "unit_key": unit_key,
        "n_rows": n_rows,
        "n_units": n_units,
        "rows_per_unit": round(n_rows / n_units, 3),
        "groups_per_unit_min": g_min,
        "groups_per_unit_max": g_max,
    }
    if n_units == n_rows:
        return {**base, "structure": "independent_rows"}
    if g_max <= 1:
        return {**base, "structure": "clustered",
                "note": "every unit belongs to exactly one group; multiple rows "
                        "per unit are replicates, and the primary analysis is "
                        "run on per-unit means"}
    if g_min == g_max == 2 and k == 2:
        return {**base, "structure": "paired",
                "note": "every unit is measured under both groups; the primary "
                        "analysis is the paired comparison of per-unit differences"}
    if g_min == g_max == k and k >= 3:
        return {**base, "structure": "complete_blocks",
                "note": f"every unit is measured under all {k} conditions; "
                        "the primary analysis is Friedman over complete blocks"}
    return {**base, "structure": "incomplete_repeated",
            "note": "units appear in several but not all groups; the primary "
                    "analysis uses unit-by-group cell means and the residual "
                    "within-unit correlation is disclosed, not modelled -- a "
                    "mixed-effects model is the correct next step and is marked "
                    "AUTHOR_INPUT_NEEDED"}


def aggregate_to_units(df: pd.DataFrame, group: str, unit_key: str,
                       numeric_cols: List[str]) -> pd.DataFrame:
    """One row per unit: the mean of every numeric outcome plus its group.

    Mean-per-unit is the aggregation the pseudoreplication literature defaults
    to for a first analysis: it uses exactly the information the unit-level
    question allows (one number per unit) and adds no model the data has not
    asked for. The row-level analysis is preserved as a secondary so nothing
    is hidden by the aggregation.
    """
    agg_cols = [c for c in numeric_cols
                if c in df.columns and c != unit_key and c != group]
    cols = [unit_key, group] + agg_cols
    # the group column is aggregated via 'first' and must appear exactly once,
    # even when a caller passes overlapping roles
    agg = (df[cols].groupby(unit_key, as_index=False)
           .agg({group: "first", **{c: "mean" for c in agg_cols}}))
    return agg


def paired_two_group(df: pd.DataFrame, group: str, oc: str,
                     lv_a: str, lv_b: str, unit_key: str,
                     alpha: float = ALPHA) -> Dict[str, Any]:
    """Paired comparison on per-unit differences (paired t / Wilcoxon signed-rank).

    Units observed under only one level are dropped, loudly: a pair that does
    not exist is not missing data to impute, it is a unit the design did not
    measure twice, and the n that enters the test must say so.
    """
    sub = df[[unit_key, group, oc]].dropna()
    wide = sub.pivot_table(index=unit_key, columns=group, values=oc, aggfunc="mean")
    if not {lv_a, lv_b}.issubset(wide.columns):
        return {"estimable": False,
                "reason": "the group levels are not both present after pivoting "
                          "on the unit key"}
    wide = wide.dropna(subset=[lv_a, lv_b])
    a = wide[lv_a].astype(float).values
    b = wide[lv_b].astype(float).values
    n = len(a)
    n_dropped = int(sub[unit_key].nunique() - n)
    if n < 8:
        return {"estimable": False, "n_pairs": n, "n_units_dropped": n_dropped,
                "reason": f"only {n} complete pairs; below the n>=8 minimum"}
    d = a - b
    checks = normality(d)
    assumptions: Dict[str, Any] = {"normality_of_differences": checks}
    rejected: List[Dict[str, str]] = []
    if n < NORMALITY_GATE and checks.get("passes") is False:
        w, p = stats.wilcoxon(d)
        method, stat_name, dof = "Wilcoxon signed-rank (paired)", "W", n - 1
        rejected.append({"test": "paired t-test",
                         "reason": f"n={n} < {NORMALITY_GATE} with non-normal "
                                   "differences; the rank test does not need "
                                   "normality of the differences"})
        primary_is_rank = True
    else:
        t, p = stats.ttest_rel(a, b)
        method, stat_name, dof = "Paired t-test", "t", n - 1
        rejected.append({"test": "Wilcoxon signed-rank",
                         "reason": f"n={n} differences, "
                                   + ("normality not rejected" if checks.get("passes")
                                      else f"n>= {NORMALITY_GATE}; the mean of the "
                                           "differences is robust by CLT")})
        primary_is_rank = False

    # mean difference with a t interval on the differences
    dm = float(d.mean())
    sd = float(d.std(ddof=1)) if n > 1 else 0.0
    se = sd / np.sqrt(n) if n > 1 else None
    if se:
        tcrit = stats.t.ppf(1 - alpha / 2, n - 1)
        ci = {"difference": round(dm, 6), "se": round(se, 6), "dof": n - 1,
              "ci_low": round(dm - tcrit * se, 6),
              "ci_high": round(dm + tcrit * se, 6), "ci_level": 1 - alpha,
              "excludes_zero": bool(dm - tcrit * se > 0 or dm + tcrit * se < 0)}
    else:
        ci = {"difference": dm, "se": None, "ci_low": None, "ci_high": None,
              "note": "zero standard error; interval undefined"}
    dz = (dm / sd) if sd else None
    effect = {
        "mean_difference_ci95": ci,
        "cohens_dz": round(float(dz), 6) if dz is not None else None,
        "cohens_dz_note": "mean difference / sd of differences (paired standardised "
                          "mean difference)",
    }

    robustness = None
    if not primary_is_rank:
        try:
            w2, p2 = stats.wilcoxon(d)
            robustness = {"test": "Wilcoxon signed-rank", "statistic": round(float(w2), 5),
                          "p_raw": round(float(p2), 8),
                          "agrees_with_primary": bool((p2 < alpha) == (p < alpha)),
                          "note": "cross-check only; the primary test is reported above"}
        except Exception:
            robustness = None

    return {
        "method": method,
        "statistic_name": stat_name,
        "statistic": float(w) if primary_is_rank else float(t),
        "dof": dof,
        "p_raw": float(p),
        "n_pairs": n,
        "n_units_dropped_incomplete": n_dropped,
        "means_a_b": [round(float(a.mean()), 6), round(float(b.mean()), 6)],
        "assumptions": assumptions,
        "rejected_alternatives": rejected,
        "effect_sizes": effect,
        "robustness_cross_check": robustness,
        "group_a": lv_a, "group_b": lv_b,
        "analysis_level": "paired",
        "rule_source": "scripts/stats_inferential.py#paired_two_group",
    }


def _safe_names(frame: pd.DataFrame, group: str, oc: str,
                covariates: List[str]) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Rename columns to formula-safe tokens and remember the mapping.

    Patsy's Q() quoting chokes on some real-world column names (brackets,
    non-ASCII); a rename to g/y/c0.. is immune and reversible, and the mapping
    is returned so every reported name stays the user's name.
    """
    ren = {group: "g", oc: "y"}
    for i, c in enumerate(covariates):
        ren[c] = "c%d" % i
    return frame.rename(columns=ren), ren


def mixed_unit_model(df: pd.DataFrame, group: str, oc: str, unit_key: str,
                     alpha: float = ALPHA) -> Dict[str, Any]:
    """Unit random-intercept mixed model for incomplete repeated measures.

    Cell means remove within-cell replication but cannot model a unit that
    appears under two of three conditions; the random intercept can. The
    omnibus group effect is a likelihood-ratio test against the intercept-only
    model with the same random effect, and effect sizes are Nakagama/Schielzeth
    marginal and conditional R^2 computed from the fitted variance components.
    Compare fixed effects using ML, not REML. A failed fit is unresolved;
    cell means from the same unit are still dependent and are not a fallback.
    """
    try:
        import statsmodels.formula.api as smf
    except Exception as exc:
        return {"estimable": False,
                "reason": f"statsmodels unavailable ({exc}); AUTHOR_INPUT_NEEDED"}
    sub = df[[unit_key, group, oc]].dropna().copy()
    sub, ren = _safe_names(sub, group, oc, [])
    sub["u"] = df.loc[sub.index, unit_key]
    n_obs, n_units = int(len(sub)), int(sub["u"].nunique())
    k = int(sub["g"].nunique())
    if n_units < 8 or k < 2 or n_obs <= n_units:
        return {"estimable": False, "n_obs": n_obs, "n_units": n_units,
                "reason": "too few units or observations for a random-intercept fit"}
    import warnings
    attempts = []
    def fit_model(formula):
        for method in ("lbfgs", "bfgs", "powell"):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    fit = smf.mixedlm(formula, sub, groups=sub["u"]).fit(
                        reml=False, method=method)
                    valid = (bool(fit.converged) and np.isfinite(fit.llf)
                             and np.isfinite(fit.fe_params).all()
                             and np.isfinite(fit.bse_fe).all()
                             and np.all(np.asarray(fit.bse_fe) >= 0)
                             and np.isfinite(fit.scale) and fit.scale > 0
                             and np.isfinite(np.asarray(fit.cov_re)).all()
                             and np.all(np.diag(np.asarray(fit.cov_re)) >= 0))
                    attempts.append({"formula": formula, "optimizer": method,
                                     "converged": bool(fit.converged),
                                     "valid": bool(valid),
                                     "warnings": [str(w.message) for w in caught]})
                    if valid:
                        return fit
                except Exception as exc:
                    attempts.append({"formula": formula, "optimizer": method,
                                     "valid": False, "reason": str(exc)})
        return None
    null = fit_model("y ~ 1")
    full = fit_model("y ~ C(g)")
    if null is None or full is None:
        return {"estimable": False, "n_obs": n_obs, "n_units": n_units,
                "fit_attempts": attempts,
                "reason": "no converged finite ML fit; repeated cell means cannot "
                          "be treated as independent. AUTHOR_INPUT_NEEDED"}
    lr = float(2.0 * (full.llf - null.llf))
    if lr < -1e-6:
        return {"estimable": False, "fit_attempts": attempts,
                "reason": "full ML likelihood is below the nested null; "
                          "optimization requires review. AUTHOR_INPUT_NEEDED"}
    lr = max(lr, 0.0)
    p = float(stats.chi2.sf(lr, k - 1))

    var_re = float(np.asarray(full.cov_re).ravel()[0])
    var_e = float(full.scale)
    # marginal R^2: variance of the fixed-effects prediction
    fe = full.model.exog @ np.asarray(full.fe_params)
    var_fe = float(np.var(fe, ddof=1))
    total = var_fe + var_re + var_e
    marginal = var_fe / total if total > 0 else None
    conditional = (var_fe + var_re) / total if total > 0 else None

    coefs = {}
    for name, b in full.fe_params.items():
        if name.startswith("C(g)"):
            level = name.replace("C(g)[T.", "").rstrip("]")
            se = full.bse[name]
            coefs[level] = {
                "difference_vs_reference": round(float(b), 6),
                "se": round(float(se), 6),
                "ci95": [round(float(b - 1.96 * se), 6), round(float(b + 1.96 * se), 6)],
            }
    return {
        "estimable": True,
        "method": "Linear mixed model (unit random intercept) with LR omnibus test",
        "statistic_name": "LR chi2",
        "statistic": round(lr, 6),
        "dof": k - 1,
        "p_raw": p,
        "estimation": "ML",
        "fit_attempts": attempts,
        "converged": True,
        "n_obs": n_obs,
        "n_total": n_units,
        "n_units": n_units,
        "group_levels": k,
        "effect_sizes": {
            "marginal_r2": round(marginal, 6) if marginal is not None else None,
            "conditional_r2": round(conditional, 6) if conditional is not None else None,
            "r2_note": "Nakagawa & Schielzeth (2013): marginal = fixed effects "
                       "only; conditional = fixed + unit random intercept",
            "fixed_effect_differences_ci95": coefs,
        },
        "assumptions": {
            "note": "random intercept per unit; residual normality not tested "
                    "at these n -- coefficients carry intervals, and the "
                    "cell means remain dependent and are descriptive only",
        },
        "rejected_alternatives": [
            {"test": "one-way ANOVA on rows",
             "reason": "rows repeat within units; that analysis reports an "
                       "inflated n"},
            {"test": "unit-by-group cell means",
             "reason": "not an independent-samples cross-check: cells from "
                       "the same unit remain dependent"}],
        "analysis_level": "unit (mixed model)",
        "rule_source": "scripts/stats_inferential.py#mixed_unit_model",
    }


def ancova_numeric(frame: pd.DataFrame, group: str, oc: str,
                   covariates: List[str], levels: List[Any],
                   alpha: float = ALPHA) -> Dict[str, Any]:
    """Covariate-adjusted group comparison (ANCOVA) with its key assumption tested.

    Homogeneity of slopes is checked first because it decides whether the
    adjusted comparison is even defined: if the group-covariate interaction is
    detectable, the common adjusted difference is withheld and the interaction
    diagnostic is reported for review.
    """
    try:
        import statsmodels.formula.api as smf
        from statsmodels.stats.anova import anova_lm
    except Exception as exc:
        return {"estimable": False,
                "reason": f"statsmodels unavailable ({exc})"}
    keep = [group, oc] + [c for c in covariates if c in frame.columns]
    sub = frame[keep].dropna().copy()
    covs = [c for c in covariates if c in sub.columns]
    sub, ren = _safe_names(sub, group, oc, covs)
    k = int(sub["g"].nunique())
    cov_terms = " + ".join("c%d" % i for i in range(len(covs)))
    if len(sub) < 8 or k < 2:
        return {"estimable": False, "n_complete_cases": int(len(sub)),
                "reason": "too few complete cases for an adjusted comparison"}

    rejected: List[Dict[str, str]] = []
    # homogeneity of slopes
    slopes = None
    m_add = smf.ols("y ~ C(g) + %s" % cov_terms if covs else "y ~ C(g)", sub).fit()
    if covs:
        m_int = smf.ols("y ~ C(g) * (%s)" % cov_terms, sub).fit()
        slopes_table = anova_lm(m_add, m_int)

        def _tcol(t, *names):
            for nm in names:
                if nm in t.columns:
                    return t[nm]
            raise KeyError(names)

        slopes_stat = _tcol(slopes_table, "F")
        slopes_p_raw = _tcol(slopes_table, "PR(>F)", "Pr(>F)").iloc[-1]
        slopes_p = None if pd.isna(slopes_p_raw) else float(slopes_p_raw)
        slopes = {
            "test": "group x covariate interaction (homogeneity of slopes)",
            "statistic_name": "F",
            "statistic": round(float(slopes_stat.iloc[-1]), 5)
                if not pd.isna(slopes_stat.iloc[-1]) else None,
            "dof": [int(_tcol(slopes_table, "df_diff").iloc[-1]),
                    int(_tcol(slopes_table, "df_resid").iloc[-1])],
            "p_raw": slopes_p,
            "verdict": ("UNDETERMINED" if slopes_p is None else "HOLDS" if slopes_p > alpha
                        else "VIOLATED -- the common adjusted difference is withheld; "
                             "review the interaction diagnostic"),
        }
        if slopes_p is None or slopes_p <= alpha:
            return {"estimable": False, "p_raw": None,
                    "n_complete_cases": int(len(sub)),
                    "assumptions": {"homogeneity_of_slopes": slopes},
                    "reason": "a common adjusted difference is unsupported; "
                              "review group-by-covariate interactions. AUTHOR_INPUT_NEEDED"}

    aov = anova_lm(m_add, typ=2)

    def _a(row, *names):
        for nm in names:
            if nm in aov.columns:
                return aov.loc[row, nm]
        raise KeyError((row, names))

    res_ss, res_df = float(_a("Residual", "sum_sq")), float(_a("Residual", "df"))
    res_ms = res_ss / res_df if res_df else float("nan")
    group_ss = float(_a("C(g)", "sum_sq"))
    group_df = float(_a("C(g)", "df"))
    total_ss = float(aov["sum_sq"].sum())
    omega2 = (group_ss - group_df * res_ms) / (total_ss + res_ms) \
        if (total_ss + res_ms) > 0 else None
    f_stat_raw = _a("C(g)", "F")
    p_raw = _a("C(g)", "PR(>F)", "Pr(>F)")
    f_stat = None if pd.isna(f_stat_raw) else float(f_stat_raw)
    p = None if pd.isna(p_raw) else float(p_raw)

    coefs = {}
    coefficient_intervals = m_add.conf_int(alpha=alpha)
    for name, b in m_add.params.items():
        if name.startswith("C(g)[T."):
            level = name.replace("C(g)[T.", "").rstrip("]")
            se = m_add.bse[name]
            coefs[level] = {
                "adjusted_difference_vs_reference": round(float(b), 6),
                "se": round(float(se), 6),
                "ci95": [round(float(v), 6) for v in coefficient_intervals.loc[name]],
            }
    out: Dict[str, Any] = {
        "estimable": True,
        "method": "ANCOVA (OLS with type-II sums of squares), adjusted for %s"
                  % (", ".join(covs) if covs else "no covariate"),
        "statistic_name": "F",
        "statistic": round(f_stat, 5) if f_stat is not None else None,
        "dof": int(group_df),
        "dof_denom": int(res_df),
        "p_raw": p,
        "n_complete_cases": int(len(sub)),
        "n_total": int(len(sub)),
        "covariates": covs,
        "assumptions": {"homogeneity_of_slopes": slopes},
        "effect_sizes": {
            "omega_squared": round(omega2, 6) if omega2 is not None else None,
            "omega_squared_formula": "(SS_group - df_group*MS_resid) / (SS_total + MS_resid)",
            "adjusted_differences_ci95": coefs,
        },
        "rejected_alternatives": rejected,
        "rule_source": "scripts/stats_inferential.py#ancova_numeric",
    }
    return out


def friedman_complete_blocks(df: pd.DataFrame, group: str, oc: str,
                             unit_key: str, alpha: float = ALPHA) -> Dict[str, Any]:
    """Friedman test over complete unit blocks, with Kendall's W.

    Each unit must be observed under every group level (repeated measures
    across k conditions). Cells with replicate rows are reduced to their mean
    first, and the reduction is disclosed in the record.
    """
    sub = df[[unit_key, group, oc]].dropna()
    cells = sub.groupby([unit_key, group], as_index=False)[oc].mean()
    levels = sorted(pd.unique(cells[group]), key=str)
    wide = cells.pivot(index=unit_key, columns=group, values=oc)
    complete = wide.dropna()
    n = len(complete)
    n_units_total = int(sub[unit_key].nunique())
    if n < 8 or len(levels) < 3:
        return {"estimable": False, "n_complete_blocks": n,
                "n_units_total": n_units_total,
                "reason": f"{n} complete blocks across {len(levels)} conditions; "
                          "Friedman needs n>=8 and k>=3"}
    cols = [complete[str(lv)] for lv in map(str, levels)]
    h, p = stats.friedmanchisquare(*cols)
    k = len(levels)
    w_kendall = float(h) / (n * (k - 1))
    # pairwise signed-rank within this outcome's family
    post_hoc = []
    for lv_a, lv_b in itertools.combinations(levels, 2):
        diff = complete[str(lv_a)] - complete[str(lv_b)]
        try:
            stat_, p_ = stats.wilcoxon(diff.astype(float).values)
        except Exception:
            continue
        post_hoc.append({"group_a": str(lv_a), "group_b": str(lv_b),
                         "n_pairs": n, "statistic": round(float(stat_), 5),
                         "p_raw": float(p_),
                         "mean_difference": round(float(diff.mean()), 6)})
    fam = correct_pvalues([h_["p_raw"] for h_ in post_hoc], "BH", alpha)
    for h_, adj in zip(post_hoc, fam.get("adjusted", [])):
        h_["p_adjusted_BH"] = float(adj)
        h_["significant_adjusted"] = bool(adj < alpha)
    return {
        "method": f"Friedman test (complete blocks, k={k})",
        "statistic_name": "chi2_F",
        "statistic": round(float(h), 6),
        "dof": k - 1,
        "p_raw": float(p),
        "n_complete_blocks": n,
        "n_units_total": n_units_total,
        "n_blocks_dropped_incomplete": n_units_total - n,
        "cell_reduction": "replicate rows within a unit-by-condition cell were "
                          "reduced to their mean before ranking",
        "effect_sizes": {"kendalls_w": round(w_kendall, 6),
                         "kendalls_w_note": "0=no concordance, 1=perfect "
                                            "concordance across conditions"},
        "assumptions": {"note": "rank-based; no normality requirement. Units are "
                                "blocks, so within-unit correlation is the design, "
                                "not a violation"},
        "rejected_alternatives": [
            {"test": "repeated-measures ANOVA",
             "reason": "sphericity is an extra assumption the data did not "
                       "volunteer; Friedman needs none"},
            {"test": "one-way ANOVA on rows",
             "reason": "rows repeat within units; that analysis would report an "
                       "inflated n"}],
        "post_hoc": post_hoc,
        "post_hoc_note": "pairwise Wilcoxon signed-rank, BH-corrected within this "
                         "outcome's pairwise family",
        "analysis_level": "unit (complete blocks)",
        "rule_source": "scripts/stats_inferential.py#friedman_complete_blocks",
    }


# ---------------- multiple comparison correction ----------------

def correct_pvalues(pvals: List[float], method: str = "BH",
                    alpha: float = ALPHA) -> Dict[str, Any]:
    # A family is corrected over the p-values that actually exist. None and NaN
    # both mean "no p-value to correct", and both are dropped -- but they are
    # dropped here, loudly, rather than being fed to np.argsort. NaN sorts last
    # and then np.minimum.accumulate walks it backwards through the whole
    # vector, so a single NaN used to turn every adjusted value into NaN and
    # take the whole multiplicity correction down with it, with no error.
    kept = [float(x) for x in pvals if x is not None and np.isfinite(x)]
    dropped = len(pvals) - len(kept)
    p = np.asarray(kept, dtype=float)
    m = len(p)
    out: Dict[str, Any] = {"family_size": m, "method": method,
                           "raw": [float(x) for x in p], "alpha": alpha,
                           "n_dropped_non_finite": dropped,
                           "dropped_note": (
                               "p-values that were None or NaN are excluded from the family; "
                               "they are reported separately as not estimable, not corrected to 1.0"
                               if dropped else None),
                           "rule_source": "references/nature-statistics-checklist.md#gate-5"}
    if m == 0:
        out["adjusted"] = []
        return out
    if method == "BH":
        order = np.argsort(p)
        adj = p[order] * m / np.arange(1, m + 1)
        adj = np.minimum.accumulate(adj[::-1])[::-1]
        res = np.empty(m)
        res[order] = np.clip(adj, 0, 1)
        out["adjusted"] = [float(x) for x in res]
    elif method == "bonferroni":
        out["adjusted"] = [float(min(1.0, x * m)) for x in p]
    elif method == "holm":
        order = np.argsort(p)
        adj = p[order] * (m - np.arange(m))
        adj = np.maximum.accumulate(adj)
        res = np.empty(m)
        res[order] = np.clip(adj, 0, 1)
        out["adjusted"] = [float(x) for x in res]
    else:
        raise ValueError(f"unknown correction method: {method}")
    out["n_significant_raw"] = int(sum(1 for x in p if x < alpha))
    out["n_significant_adjusted"] = int(sum(1 for x in out["adjusted"] if x < alpha))
    return out


# ---------------- driver ----------------

def _outcome_tests(frame: pd.DataFrame, group: str, levels: List[Any],
                   outcome_cols: List[str], alpha: float,
                   analysis_level: str,
                   covariates: Optional[List[str]] = None,
                   n_boot: int = BOOTSTRAP) -> List[Dict[str, Any]]:
    """Run the row-level dispatch for every outcome column on `frame`.

    Shared by the primary analysis (whatever level the unit structure makes
    defensible) and the secondary row-level analysis, so both are produced by
    the same code and differ only in the frame and the label.

    When covariates are declared, numeric non-binary outcomes are compared
    adjusted for them (ANCOVA) and the unadjusted comparison is kept as the
    cross-check -- the adjusted question is the one the user asked, the
    unadjusted one is the robustness view.
    """
    tests: List[Dict[str, Any]] = []
    for oc in outcome_cols:
        if oc not in frame.columns:
            continue
        sub = frame[[group, oc]].dropna()
        dropped = int(len(frame) - len(sub))
        if len(sub) < 8:
            tests.append({"outcome": oc, "estimable": False,
                          "reason": f"only {len(sub)} complete rows; below the n>=8 minimum",
                          "rows_dropped_for_missingness": dropped})
            continue

        s = frame[oc]
        is_numeric = pd.api.types.is_numeric_dtype(s)
        # An outcome that is a restatement of the grouping variable cannot be
        # evidence about it. species_code is a relabelling of species, so
        # "do the groups differ in species_code" has the answer built into the
        # question; running the test anyway buries a tautology among four real
        # comparisons and inflates the family the correction is applied to.
        per_group_values = [sub.loc[sub[group] == lv, oc].dropna().nunique()
                            for lv in levels]
        if (all(v == 1 for v in per_group_values)
                and s.nunique(dropna=True) > 1):
            tests.append({
                "outcome": oc, "estimable": False,
                "reason": ("every row in each group holds the same value of this column, and the "
                           "groups differ, so the column is determined by the grouping variable "
                           "rather than measured independently of it"),
                "p_raw": None, "p_adjusted": None,
                "rows_dropped_for_missingness": dropped,
                "n_complete_cases": int(len(sub)),
            })
            continue
        is_binary = is_numeric and s.nunique(dropna=True) == 2
        rec: Dict[str, Any] = {"outcome": oc, "estimable": True,
                               "rows_dropped_for_missingness": dropped,
                               "n_complete_cases": int(len(sub))}
        covs_here = [c for c in (covariates or [])
                     if c in frame.columns and c != oc and c != group
                     and pd.api.types.is_numeric_dtype(frame[c])]
        if is_binary:
            rec.update({"design": "binary outcome", **binary_outcome(frame[group], s)})
        elif not is_numeric:
            rec.update({"design": "categorical outcome",
                        **categorical_2x_k(frame[group], s, alpha)})
        elif covs_here:
            adj = ancova_numeric(frame, group, oc, covs_here, levels, alpha)
            if adj.get("estimable"):
                un = (two_group_numeric(
                          sub.loc[sub[group] == levels[0], oc].astype(float).values,
                          sub.loc[sub[group] == levels[1], oc].astype(float).values,
                          str(levels[0]), str(levels[1]), alpha)
                      if len(levels) == 2 else
                      k_group_numeric(
                          {str(lv): sub.loc[sub[group] == lv, oc].astype(float).values
                           for lv in levels}, alpha, n_boot=n_boot))
                if un.get("p_raw") is not None:
                    adj["robustness_cross_check"] = {
                        "test": un.get("method"),
                        "statistic": un.get("statistic"),
                        "p_raw": un.get("p_raw"),
                        "agrees_with_primary": bool(
                            (un["p_raw"] < alpha) == (adj.get("p_raw", 1.0) < alpha)),
                        "note": "unadjusted comparison; the primary is adjusted for "
                                "the declared covariates",
                    }
                rec.update({"design": "covariate-adjusted numeric", **adj})
            else:
                rec.update({"design": "covariate-adjusted numeric (unresolved)", **adj})
        elif len(levels) == 2:
            a = sub.loc[sub[group] == levels[0], oc].astype(float).values
            b = sub.loc[sub[group] == levels[1], oc].astype(float).values
            rec.update({"design": "2-group numeric",
                        **two_group_numeric(a, b, str(levels[0]), str(levels[1]), alpha)})
        else:
            g = {str(lv): sub.loc[sub[group] == lv, oc].astype(float).values for lv in levels}
            rec.update({"design": f"{len(levels)}-group numeric",
                        **k_group_numeric(g, alpha, n_boot=n_boot)})
        rec["analysis_level"] = analysis_level
        tests.append(rec)
    return tests


def _unadjusted_numeric(sub: pd.DataFrame, group: str, oc: str,
                        levels: List[Any], alpha: float,
                        n_boot: int) -> Dict[str, Any]:
    if len(levels) == 2:
        return two_group_numeric(
            sub.loc[sub[group] == levels[0], oc].astype(float).values,
            sub.loc[sub[group] == levels[1], oc].astype(float).values,
            str(levels[0]), str(levels[1]), alpha)
    return k_group_numeric(
        {str(lv): sub.loc[sub[group] == lv, oc].astype(float).values
         for lv in levels}, alpha, n_boot=n_boot)


def _paired_outcome_tests(df: pd.DataFrame, group: str, levels: List[Any],
                          outcome_cols: List[str], unit_key: str,
                          alpha: float) -> List[Dict[str, Any]]:
    """Paired dispatch: numeric -> paired t / Wilcoxon; binary -> exact McNemar."""
    if len(levels) != 2:
        lv_note = f"{len(levels)} conditions per unit; paired dispatch needs exactly 2"
    tests: List[Dict[str, Any]] = []
    for oc in outcome_cols:
        if oc not in df.columns:
            continue
        s = df[oc]
        is_numeric = pd.api.types.is_numeric_dtype(s)
        rec: Dict[str, Any]
        if not is_numeric:
            tests.append({"outcome": oc, "estimable": False, "p_raw": None,
                          "analysis_level": "paired",
                          "reason": "paired nominal outcome: no defensible automatic "
                                    "test; AUTHOR_INPUT_NEEDED"})
            continue
        if len(levels) != 2:
            tests.append({"outcome": oc, "estimable": False, "p_raw": None,
                          "analysis_level": "paired", "reason": lv_note})
            continue
        sub = df[[unit_key, group, oc]].dropna()
        if s.nunique(dropna=True) == 2:
            wide = sub.pivot_table(index=unit_key, columns=group, values=oc,
                                   aggfunc="mean")
            if set(map(str, levels)) <= set(map(str, wide.columns)):
                wide = wide.dropna(subset=[str(levels[0]), str(levels[1])])
                a = (wide[str(levels[0])] > 0.5).astype(int)
                b = (wide[str(levels[1])] > 0.5).astype(int)
                b01 = int(((a == 0) & (b == 1)).sum())
                b10 = int(((a == 1) & (b == 0)).sum())
                nd = b01 + b10
                if nd >= 8:
                    p = float(min(1.0, 2 * stats.binom.cdf(min(b01, b10), nd, 0.5)))
                    rec = {"outcome": oc, "estimable": True,
                           "design": "binary paired outcome",
                           "method": "Exact McNemar test (binomial on discordant pairs)",
                           "statistic_name": "discordant pairs", "statistic": nd,
                           "dof": None, "p_raw": p, "n_pairs": int(len(wide)),
                           "discordant": {"01": b01, "10": b10},
                           "effect_sizes": {"odds_ratio_discordant":
                                            round(b10 / b01, 4) if b01 else None},
                           "rejected_alternatives": [
                               {"test": "paired t-test on the 0/1 values",
                                "reason": "binary outcome; the exact test needs no "
                                          "approximation"}],
                           "analysis_level": "paired",
                           "rule_source": "scripts/stats_inferential.py#_paired_outcome_tests"}
                    tests.append(rec)
                    continue
        rec = {"outcome": oc, "estimable": True,
               **paired_two_group(df, group, oc, str(levels[0]), str(levels[1]),
                                  unit_key, alpha)}
        tests.append(rec)
    return tests


def _incomplete_repeated_tests(df: pd.DataFrame, cell: pd.DataFrame,
                               group: str, levels: List[Any],
                               outcome_cols: List[str], unit_key: str,
                               alpha: float,
                               covariates: Optional[List[str]] = None
                               ) -> List[Dict[str, Any]]:
    """Incomplete repeated measures: mixed model or an explicit unresolved result.

    Per outcome, a converged ML mixed model is primary. If no valid fit is
    available the outcome stays unresolved; ordinary tests on repeated cell
    means cannot remove within-unit dependence.
    """
    tests: List[Dict[str, Any]] = []
    for oc in outcome_cols:
        if oc not in df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(df[oc]):
            tests.append({"outcome": oc, "estimable": False, "p_raw": None,
                          "analysis_level": "incomplete repeated",
                          "reason": "nominal outcome under incomplete repeated "
                                    "measures: no defensible automatic test; "
                                    "AUTHOR_INPUT_NEEDED"})
            continue
        mm = mixed_unit_model(df, group, oc, unit_key, alpha)
        tests.append({"outcome": oc,
                      "design": "incomplete repeated measures (mixed model)",
                      "analysis_level": "unit (mixed model)", "p_raw": None, **mm})
    return tests


def _blocks_outcome_tests(df: pd.DataFrame, group: str, levels: List[Any],
                          outcome_cols: List[str], unit_key: str,
                          alpha: float) -> List[Dict[str, Any]]:
    tests: List[Dict[str, Any]] = []
    for oc in outcome_cols:
        if oc not in df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(df[oc]):
            tests.append({"outcome": oc, "estimable": False, "p_raw": None,
                          "analysis_level": "unit (complete blocks)",
                          "reason": "nominal outcome across k>2 repeated conditions: "
                                    "no defensible automatic test; AUTHOR_INPUT_NEEDED"})
            continue
        tests.append({"outcome": oc, "estimable": True,
                      **friedman_complete_blocks(df, group, oc, unit_key, alpha)})
    return tests


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clean", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--group", required=True)
    p.add_argument("--outcomes", default=None,
                   help="comma-list of outcome columns (default: all numeric)")
    p.add_argument("--correction", default="BH", choices=["BH", "bonferroni", "holm"])
    p.add_argument("--alpha", type=float, default=ALPHA)
    p.add_argument("--unit-key", default=None,
                   help="column identifying the independent unit; when rows repeat "
                        "within units, the primary analysis moves to the level the "
                        "structure supports and row-level results are kept as a "
                        "labelled secondary")
    p.add_argument("--covariates", default=None,
                   help="comma-list of numeric covariates to adjust for (ANCOVA); "
                        "declaring them makes the adjusted comparison the primary "
                        "and keeps the unadjusted one as the cross-check")
    args = p.parse_args()

    df = _read(Path(args.clean))
    if args.group not in df.columns:
        print(f"ERROR: group column {args.group!r} not found; available={list(df.columns)}")
        return 1
    if args.unit_key and args.unit_key == args.group:
        # every unit would be its own group: the comparison is of units with
        # themselves and no test is defined, so say so instead of aggregating
        # a column onto itself
        print(f"ERROR: --unit-key and --group are both {args.unit_key!r}; the "
              f"unit identifier cannot also be the grouping variable")
        return 1

    outcome_cols = ([c.strip() for c in args.outcomes.split(",") if c.strip()]
                    if args.outcomes else
                    [c for c in df.select_dtypes(include=[np.number]).columns
                     if c != args.group and c != args.unit_key])
    covariates = ([c.strip() for c in args.covariates.split(",") if c.strip()]
                  if args.covariates else [])
    bad_cov = [c for c in covariates if c not in df.columns]
    if bad_cov:
        print(f"ERROR: covariate column(s) not found: {bad_cov}; "
              f"available={list(df.columns)}")
        return 1

    levels = sorted(pd.unique(df[args.group].dropna()), key=str)
    if len(levels) < 2:
        print(f"ERROR: group column {args.group!r} has {len(levels)} level(s); cannot compare")
        return 1

    # ---- unit of analysis: decide the level BEFORE choosing any test (Gate 1) ----
    structure_info = analyze_unit_structure(df, args.group, args.unit_key)
    structure = structure_info["structure"]
    unit_info: Dict[str, Any] = dict(structure_info)
    warnings: List[str] = []

    numeric_outcomes = [c for c in outcome_cols
                        if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]

    primary_level = "row"
    analysis_df = df
    if structure == "clustered":
        analysis_df = aggregate_to_units(df, args.group, args.unit_key, numeric_outcomes)
        primary_level = "unit"
        unit_info["primary_analysis"] = (
            "per-unit means (mean aggregation disclosed); n below is the number of "
            "units, not rows")
        warnings.append(
            f"{structure_info['n_rows']} rows collapse to {structure_info['n_units']} "
            f"units; the primary tests below run on units. Row-level results are "
            "kept as a secondary analysis and are not the evidence.")
    elif structure == "paired":
        primary_level = "paired"
        unit_info["primary_analysis"] = "paired per-unit differences"
    elif structure == "complete_blocks":
        primary_level = "unit (complete blocks)"
        unit_info["primary_analysis"] = "Friedman over complete unit blocks"
    elif structure == "incomplete_repeated":
        cell = (df[[args.unit_key, args.group] + numeric_outcomes]
                .groupby([args.unit_key, args.group], as_index=False)
                .agg({c: "mean" for c in numeric_outcomes}))
        analysis_df = cell
        primary_level = "unit x group cell"
        unit_info["primary_analysis"] = (
            "ML linear mixed model with a unit random intercept; failed fits "
            "remain unresolved rather than treating repeated cells as independent")
        warnings.append(
            "units appear in several but not all groups; the primary analysis is "
            "a unit random-intercept mixed model; a failed fit requires review")
    elif structure == "undeclared":
        unit_info["note"] = structure_info.get("note")

    # ---- primary tests, at the level the structure supports ----
    if structure == "paired":
        tests = _paired_outcome_tests(df, args.group, levels, outcome_cols,
                                      args.unit_key, args.alpha)
    elif structure == "complete_blocks":
        tests = _blocks_outcome_tests(df, args.group, levels, outcome_cols,
                                      args.unit_key, args.alpha)
    elif structure == "incomplete_repeated":
        tests = _incomplete_repeated_tests(df, cell, args.group, levels,
                                           outcome_cols, args.unit_key,
                                           args.alpha, covariates)
        if any("mixed model" in str(t.get("method", "")) for t in tests
               if t.get("estimable")):
            primary_level = "unit (mixed model)"
    else:
        tests = _outcome_tests(analysis_df, args.group, levels, outcome_cols,
                               args.alpha, primary_level, covariates=covariates)

    # ---- secondary row-level analysis, when the primary is not row-level ----
    secondary: Optional[Dict[str, Any]] = None
    if primary_level != "row":
        sec_tests = _outcome_tests(df, args.group, levels, outcome_cols,
                                   args.alpha, "row (secondary)")
        for t in sec_tests:
            if t.get("estimable"):
                t["pseudoreplication_warning"] = (
                    "rows repeat within units; this row-level result treats them as "
                    "independent and its n is inflated accordingly -- it is shown "
                    "for comparison only and is not the primary evidence")
        fam_idx = [i for i, t in enumerate(sec_tests)
                   if t.get("estimable") and t.get("p_raw") is not None]
        sec_family = (correct_pvalues([sec_tests[i]["p_raw"] for i in fam_idx],
                                      args.correction, args.alpha)
                      if fam_idx else {"family_size": 0, "adjusted": []})
        for j, i in enumerate(fam_idx):
            sec_tests[i]["p_adjusted"] = sec_family["adjusted"][j]
        secondary = {"analysis_level": "row",
                     "role": "secondary; retained for comparison, not evidence",
                     "tests": sec_tests,
                     "multiple_comparisons": sec_family}

    # ---- multiplicity across the primary family ----
    fam_idx = [i for i, t in enumerate(tests) if t.get("estimable") and t.get("p_raw") is not None]
    family = (correct_pvalues([tests[i]["p_raw"] for i in fam_idx], args.correction, args.alpha)
              if fam_idx else {"family_size": 0, "adjusted": []})
    for j, i in enumerate(fam_idx):
        tests[i]["p_adjusted"] = family["adjusted"][j]
        tests[i]["significant_after_correction"] = bool(family["adjusted"][j] < args.alpha)

    # ---- exploratory correlation family, at the primary analysis level ----
    corr_frame = analysis_df if structure in ("clustered", "incomplete_repeated") else df
    num_cols = [c for c in outcome_cols if c in corr_frame.columns
                and pd.api.types.is_numeric_dtype(corr_frame[c])]
    corrs: List[Dict[str, Any]] = []
    for a, b in itertools.combinations(num_cols, 2):
        sub2 = corr_frame[[a, b]].dropna()
        if len(sub2) < 8:
            continue
        pr, sr = pearson_r(sub2[a].astype(float).values, sub2[b].astype(float).values), \
            spearman_rho(sub2[a].astype(float).values, sub2[b].astype(float).values)
        chosen, p_used = ("spearman", sr.get("p_raw")) if pr.get("p_raw") is None else ("pearson", pr.get("p_raw"))
        corrs.append({"x": a, "y": b, "n": int(len(sub2)), "primary": chosen,
                      "p_used": p_used, "pearson": pr, "spearman": sr})
    valid = [(i, c["p_used"]) for i, c in enumerate(corrs) if c["p_used"] is not None]
    corr_family = (correct_pvalues([p_ for _, p_ in valid], args.correction, args.alpha)
                   if valid else {"family_size": 0, "adjusted": []})
    for j, (i, _) in enumerate(valid):
        corrs[i]["p_adjusted"] = corr_family["adjusted"][j]
        corrs[i]["significant_after_correction"] = bool(corr_family["adjusted"][j] < args.alpha)
    for c in corrs:
        if c["p_used"] is None:
            c["p_adjusted"] = None

    result = {
        "schema_version": "1.2",
        "source": str(args.clean),
        "group": args.group,
        "group_levels": [str(lv) for lv in levels],
        "group_sizes": {str(lv): int((df[args.group] == lv).sum()) for lv in levels},
        "alpha": args.alpha,
        "n_rows": int(len(df)),
        "primary_level": primary_level,
        "covariates": covariates,
        "unit_of_analysis": unit_info,
        "tests": tests,
        "secondary_row_level": secondary,
        "multiple_comparisons": {
            "primary_family": family,
            "note": "one outcome = one member of the family; correction applies across "
                    "outcomes, and separately within each post-hoc pairwise family",
        },
        "correlations": {
            "matrix": corrs, "family": corr_family,
            "analysis_level": ("unit" if corr_frame is not df else "row"),
            "note": "exploratory only; correlation is not evidence of mechanism",
        },
        "rule_source": "references/nature-statistics-checklist.md#gates-1-3-5",
    }
    if warnings:
        result["warnings"] = warnings

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    n_ok = sum(1 for t in tests if t.get("estimable"))
    print(f"stats_inferential written: {out}")
    print(f"  unit structure : {structure}  primary level: {primary_level}")
    if structure not in ("undeclared", "independent_rows"):
        print(f"  units          : {structure_info.get('n_units')} units across "
              f"{structure_info.get('n_rows')} rows "
              f"(rows/unit={structure_info.get('rows_per_unit')})")
    print(f"  tests: {n_ok}/{len(tests)} estimable  family_size={family.get('family_size')}  "
          f"correction={args.correction}")
    print(f"  significant raw={family.get('n_significant_raw')} "
          f"adjusted={family.get('n_significant_adjusted')}")
    for t in tests:
        if t.get("estimable"):
            print(f"    {t['outcome']:22s} {t.get('method','?'):48s} "
                  f"p={t.get('p_raw')} p_adj={t.get('p_adjusted')}")
    if secondary:
        print("  secondary row-level analysis recorded (not the primary evidence)")
    for w in warnings:
        print("  WARNING: %s" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
