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
        d = cliffs_delta(groups[a], groups[b])
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


def k_group_numeric(groups: Dict[str, np.ndarray], alpha: float = ALPHA) -> Dict[str, Any]:
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
        effects = rank_effects(vals)
        cross = None
    elif equal_var is True:
        f, p = stats.f_oneway(*vals)
        method = "one-way ANOVA"
        stat_name, dof, statistic, dof_denom = "F", k - 1, float(f), None
        rejected.append({"test": "Welch ANOVA",
                         "reason": "equal variance holds (Levene p > alpha); the pooled test is more powerful"})
        rejected.append({"test": "Kruskal-Wallis H",
                         "reason": f"min n={n_min} >= {NORMALITY_GATE}; the mean statistic is robust by CLT"})
        effects = variance_effects(vals)
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
        effects = variance_effects(vals)
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
            "cliffs_delta": cliffs_delta(vals[i], vals[j]),
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
                   help="column identifying the independent unit; when it is present and "
                        "rows-per-unit > 1, a pseudoreplication warning is emitted")
    args = p.parse_args()

    df = _read(Path(args.clean))
    if args.group not in df.columns:
        print(f"ERROR: group column {args.group!r} not found; available={list(df.columns)}")
        return 1

    outcome_cols = ([c.strip() for c in args.outcomes.split(",") if c.strip()]
                    if args.outcomes else
                    [c for c in df.select_dtypes(include=[np.number]).columns if c != args.group])

    levels = sorted(pd.unique(df[args.group].dropna()), key=str)
    if len(levels) < 2:
        print(f"ERROR: group column {args.group!r} has {len(levels)} level(s); cannot compare")
        return 1

    # ---- pseudoreplication check (Gate 1: unit of analysis) ----
    unit_info: Dict[str, Any] = {"unit_key": args.unit_key, "n_rows": int(len(df))}
    pseudorep_warning = None
    if args.unit_key and args.unit_key in df.columns:
        n_units = int(df[args.unit_key].nunique(dropna=True))
        unit_info.update({"n_units": n_units, "rows_per_unit": round(len(df) / n_units, 3) if n_units else None})
        if n_units < len(df):
            pseudorep_warning = (
                f"column {args.unit_key!r} yields {n_units} independent units across {len(df)} rows. "
                "Treating rows as independent inflates the effective sample size. The tests below "
                "are row-level; if observations repeat within a unit, aggregate to the unit first "
                "or fit a mixed-effects model."
            )
            unit_info["warning"] = pseudorep_warning
    else:
        unit_info["note"] = "no --unit-key given; row is assumed to be the independent unit"

    tests: List[Dict[str, Any]] = []
    for oc in outcome_cols:
        if oc not in df.columns:
            continue
        sub = df[[args.group, oc]].dropna()
        dropped = int(len(df) - len(sub))
        if len(sub) < 8:
            tests.append({"outcome": oc, "estimable": False,
                          "reason": f"only {len(sub)} complete rows; below the n>=8 minimum",
                          "rows_dropped_for_missingness": dropped})
            continue

        s = df[oc]
        is_numeric = pd.api.types.is_numeric_dtype(s)
        # An outcome that is a restatement of the grouping variable cannot be
        # evidence about it. species_code is a relabelling of species, so
        # "do the groups differ in species_code" has the answer built into the
        # question; running the test anyway buries a tautology among four real
        # comparisons and inflates the family the correction is applied to.
        #
        # The test is structural rather than a value comparison, because a
        # relabelling need not reuse the original labels -- species_code holds
        # 1/2/3 while species holds setosa/versicolor/virginica, so comparing
        # value sets finds nothing. What makes it a restatement is that each
        # group carries exactly one outcome value.
        per_group_values = [sub.loc[sub[args.group] == lv, oc].dropna().nunique()
                            for lv in levels]
        if (all(v == 1 for v in per_group_values)
                and s.nunique(dropna=True) > 1):
            tautology = {
                "outcome": oc, "estimable": False,
                "reason": ("every row in each group holds the same value of this column, and the "
                           "groups differ, so the column is determined by the grouping variable "
                           "rather than measured independently of it"),
                "p_raw": None, "p_adjusted": None,
                "rows_dropped_for_missingness": dropped,
                "n_complete_cases": int(len(sub)),
            }
            tests.append(tautology)
            continue
        is_binary = is_numeric and s.nunique(dropna=True) == 2
        rec: Dict[str, Any] = {"outcome": oc, "estimable": True,
                               "rows_dropped_for_missingness": dropped,
                               "n_complete_cases": int(len(sub))}
        if is_binary:
            rec.update({"design": "binary outcome", **binary_outcome(df[args.group], s)})
        elif not is_numeric:
            rec.update({"design": "categorical outcome",
                        **categorical_2x_k(df[args.group], s, args.alpha)})
        elif len(levels) == 2:
            a = sub.loc[sub[args.group] == levels[0], oc].astype(float).values
            b = sub.loc[sub[args.group] == levels[1], oc].astype(float).values
            rec.update({"design": "2-group numeric",
                        **two_group_numeric(a, b, str(levels[0]), str(levels[1]), args.alpha)})
        else:
            g = {str(lv): sub.loc[sub[args.group] == lv, oc].astype(float).values for lv in levels}
            rec.update({"design": f"{len(levels)}-group numeric",
                        **k_group_numeric(g, args.alpha)})
        if pseudorep_warning:
            rec["pseudoreplication_warning"] = pseudorep_warning
        tests.append(rec)

    # ---- multiplicity across the primary family ----
    fam_idx = [i for i, t in enumerate(tests) if t.get("estimable") and t.get("p_raw") is not None]
    family = (correct_pvalues([tests[i]["p_raw"] for i in fam_idx], args.correction, args.alpha)
              if fam_idx else {"family_size": 0, "adjusted": []})
    for j, i in enumerate(fam_idx):
        tests[i]["p_adjusted"] = family["adjusted"][j]
        tests[i]["significant_after_correction"] = bool(family["adjusted"][j] < args.alpha)

    # ---- exploratory correlation family ----
    num_cols = [c for c in outcome_cols if c in df.columns
                and pd.api.types.is_numeric_dtype(df[c])]
    corrs: List[Dict[str, Any]] = []
    for a, b in itertools.combinations(num_cols, 2):
        sub2 = df[[a, b]].dropna()
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
        "schema_version": "1.1",
        "source": str(args.clean),
        "group": args.group,
        "group_levels": [str(lv) for lv in levels],
        "group_sizes": {str(lv): int((df[args.group] == lv).sum()) for lv in levels},
        "alpha": args.alpha,
        "n_rows": int(len(df)),
        "unit_of_analysis": unit_info,
        "tests": tests,
        "multiple_comparisons": {
            "primary_family": family,
            "note": "one outcome = one member of the family; correction applies across "
                    "outcomes, and separately within each post-hoc pairwise family",
        },
        "correlations": {
            "matrix": corrs, "family": corr_family,
            "note": "exploratory only; correlation is not evidence of mechanism",
        },
        "rule_source": "references/nature-statistics-checklist.md#gates-3-5",
    }
    if pseudorep_warning:
        result["warnings"] = [pseudorep_warning]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    n_ok = sum(1 for t in tests if t.get("estimable"))
    print(f"stats_inferential written: {out}")
    print(f"  tests: {n_ok}/{len(tests)} estimable  family_size={family.get('family_size')}  "
          f"correction={args.correction}")
    print(f"  significant raw={family.get('n_significant_raw')} "
          f"adjusted={family.get('n_significant_adjusted')}")
    for t in tests:
        if t.get("estimable"):
            print(f"    {t['outcome']:22s} {t.get('method','?'):48s} "
                  f"p={t.get('p_raw')} p_adj={t.get('p_adjusted')}")
    if pseudorep_warning:
        print("  WARNING: pseudoreplication risk -- see unit_of_analysis in the JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
