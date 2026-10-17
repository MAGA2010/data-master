#!/usr/bin/env python3
"""Decide which figures the data actually warrants, and why.

A chart is not a picture of the data; it is an argument about it. This script
only emits a decision when the numbers support a sentence, and it writes that
sentence down as the figure's title -- because the title is the only part of a
figure most readers actually read.

Two rules shape the whole file:

  * A figure earns its place by answering an argument task from
    references/chart-decision-catalog.md. If no task fits, the answer is no
    figure. Padding a report with plots of nothing is a way of looking
    thorough while saying nothing.
  * The decision records what it rejected and why, so that the choice can be
    argued with later. A chart that was chosen silently cannot be questioned.

Titles are computed from the data, never written by hand, because a hand-written
title is a claim the pipeline has not checked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dm_types  # noqa: E402

# Colour-blind safer subset, and the one marker style per series the catalogue
# requires. Colour is a secondary channel throughout: every figure is also
# readable by line style and marker.
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
MARKERS = ["o", "s", "^", "D", "v"]


def _fmt(x: Optional[float], digits: int = 2) -> str:
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if v != 0 and (abs(v) < 1e-3 or abs(v) >= 1e5):
        return "%.*e" % (digits, v)
    return ("%%.%df" % digits) % v


def _n(x: Any) -> str:
    """Format a count without pretending to be precise about it."""
    try:
        i = int(x)
    except (TypeError, ValueError):
        return "n/a"
    return f"{i:,}"


# ---------------------------------------------------------------- candidates

def _numeric_stats(desc: Dict[str, Any], col: str) -> Dict[str, Any]:
    """The numeric table lives under desc["numeric"]; looking for it at the
    document root is why the histograms silently never appeared."""
    return (desc.get("numeric") or {}).get(col) or {}


def _distribution_panel(desc: Dict[str, Any], col: str) -> Optional[Dict[str, Any]]:
    st = _numeric_stats(desc, col)
    if not st or st.get("median") is None or st.get("q25") is None:
        return None
    n = int(st.get("n") or 0)
    if n < 20:
        return None
    mean, median = st.get("mean"), st.get("median")
    q1, q3 = st.get("q25"), st.get("q75")
    # Both skewness measures, because they fail differently. Pearson uses every
    # value and is dominated by the tails; Bowley uses only the quartiles and is
    # blind to outliers but sees where the median sits inside the IQR. On a
    # pooled distribution that is bimodal -- three species that do not overlap --
    # Pearson reports near zero and the figure then claims "roughly symmetric"
    # about a distribution with two humps, which is the kind of wrong that gets
    # copied into a paper.
    pearson = st.get("skew")
    bowley = None
    if q3 is not None and q1 is not None and q3 > q1:
        bowley = (q3 + q1 - 2 * median) / (q3 - q1)
    cand = [abs(v) for v in (pearson, bowley) if v is not None]
    worst = max(cand) if cand else 0.0
    sign = None
    for v in (bowley, pearson):
        if v is not None and abs(v) == worst:
            sign = v
            break
    if worst >= 1.0:
        shape = ("strongly right-skewed" if (sign or 0) > 0 else "strongly left-skewed")
    elif worst >= 0.5:
        shape = ("moderately right-skewed" if (sign or 0) > 0 else "moderately left-skewed")
    elif worst >= 0.25:
        shape = ("slightly right-skewed" if (sign or 0) > 0 else "slightly left-skewed")
    else:
        shape = "roughly symmetric"
    return {
        "column": col, "n": n, "shape": shape,
        "skew_pearson": pearson, "skew_bowley": bowley, "skew_used": worst,
        "median": median, "q25": q1, "q75": q3, "mean": mean,
        "min": st.get("min"), "max": st.get("max"),
        "title": f"{col} is {shape} (median {_fmt(median)}, IQR {_fmt(q1)} to {_fmt(q3)}, n = {_n(n)})",
    }


def _outcome_test(inf: Dict[str, Any], group: str, outcome: str) -> Optional[Dict[str, Any]]:
    for t in inf.get("tests", []):
        if t.get("outcome") == outcome:
            return t
    return None


def _comparison_panel(inf: Dict[str, Any], group: str,
                      t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not t.get("estimable", True):
        return None
    p_adj, p_raw = t.get("p_adjusted"), t.get("p_raw")
    means = t.get("group_means") or {}
    if len(means) < 2 or p_adj is None:
        return None
    eff = t.get("effect_sizes") or {}
    phrase = _effect_phrase(t)
    verdict = ("differs across" if p_adj < 0.05 else
               "is not distinguishable across")
    return {
        "outcome": t.get("outcome"), "group": group, "method": t.get("method"),
        "p_raw": p_raw, "p_adjusted": p_adj, "means": means,
        "group_n": t.get("group_n") or {}, "n_total": t.get("n_total"),
        "effect_phrase": phrase,
        "significant": p_adj < 0.05,
        "title": f"{t.get('outcome')} {verdict} {group} (adjusted p = {_fmt(p_adj, 3)})",
        "sentence": (f"{t.get('outcome')} differs across {group} by "
                     f"{phrase}, BH-adjusted p = {_fmt(p_adj, 3)}."
                     if p_adj < 0.05 else
                     f"{t.get('outcome')} is not distinguishable across {group} "
                     f"(adjusted p = {_fmt(p_adj, 3)})."),
    }


def _association_panel(inf: Dict[str, Any], x: str, y: str,
                       excluded: set) -> Optional[Dict[str, Any]]:
    if x in excluded or y in excluded:
        return None
    for c in ((inf.get("correlations") or {}).get("matrix") or []):
        if {c.get("x"), c.get("y")} != {x, y}:
            continue
        chosen = c.get("primary")
        src = c.get(chosen) or {}
        p = c.get("p_used") if c.get("p_used") is not None else src.get("p_raw")
        rho = src.get("spearman_rho") if chosen == "spearman" else src.get("pearson_r")
        if p is None or rho is None:
            return None
        lo, hi = _ci_bounds(src.get("ci95"))
        a = abs(rho)
        strength = ("negligible" if a < 0.1 else "weak" if a < 0.3 else
                    "moderate" if a < 0.5 else "strong")
        return {
            "x": x, "y": y, "n": c.get("n"), "statistic": chosen, "value": rho,
            "ci": [lo, hi], "p": p,
            "title": (f"{x} and {y} are {strength}ly associated "
                      f"({chosen} = {_fmt(rho)}, p = {_fmt(p, 3)})"),
            "sentence": (f"{x} and {y} move together ({chosen} = {_fmt(rho)}"
                         + (f", 95% CI {_fmt(lo)} to {_fmt(hi)}" if lo is not None else "")
                         + f", p = {_fmt(p, 3)}, n = {_n(c.get('n'))})."),
        }
    return None


# ---------------------------------------------------------------- assembly

def _join_sentences(parts: List[str]) -> str:
    """Join clauses into one sentence with exactly one terminal period.

    Panel sentences are written to stand alone, so each already ends in a period.
    Joining them with "; " and appending another period produced "p = 1e-70.;" --
    a cosmetic defect that trains a reader to distrust the rest of the number.
    """
    cleaned = [re.sub(r"[\s.;,]+$", "", str(x)).strip() for x in parts if str(x).strip()]
    if not cleaned:
        return ""
    return "; ".join(cleaned) + "."


def build_decisions(df, profile: Dict[str, Any], desc: Dict[str, Any],
                    inf: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []

    def add(dec: Dict[str, Any]) -> None:
        dec["id"] = "fig%02d_%s" % (len(out) + 1, dec["chart_type"])
        dec["output_path"] = "charts/%s.png" % dec["id"]
        dec["order"] = len(out) + 1
        out.append(dec)

    # ---- figure 1: the shapes the later tests will assume things about ----
    numeric = desc.get("numeric") or {}
    panels = [p_ for p_ in (_distribution_panel(desc, c) for c in numeric) if p_]
    # strongest skew first: that is the panel a reader most needs
    panels.sort(key=lambda r: r.get("skew_used") or 0, reverse=True)
    panels = panels[:3]
    if panels:
        skewed = [r for r in panels if r["shape"] != "roughly symmetric"]
        lead = (skewed or panels)[0]
        add({
            "argument_task": "establish the shape of each numeric variable before any test assumes one",
            "chart_type": "distribution_panel",
            "spec": {"panels": panels, "bins": "auto", "show_median_iqr": True},
            "uncertainty": "median and interquartile range marked on every panel",
            "title": ("%d of %d measured variables are skewed, so the analyses below "
                      "summarise them by median rather than mean"
                      % (len(skewed), len(panels))) if skewed
                     else "All measured variables are roughly symmetric; means and medians agree",
            "caption": ("Distribution of each numeric variable, with the median and interquartile "
                        "range marked. Panel order follows absolute skewness. Full box-and-whisker "
                        "statistics are in Table 2."),
            "body": {
                "fact": _join_sentences([r["title"] for r in panels]),
                "interpretation": ("Skewed variables are summarised by the median and IQR, and "
                                   "rank-based or Welch methods are preferred for them."
                                   if skewed else
                                   "Mean and median agree closely for every variable."),
                "implication": ("These summaries, not the raw shape, should carry into any "
                                "downstream model." if skewed else
                                "Standard parametric summaries are adequate here."),
            },
            "complexity_principles": ["1_one_argument", "6_uncertainty", "8_minimum_complexity"],
            "rationale": ("The shape of every numeric variable decides which test is legitimate "
                          "later, so it is one argument and belongs in one figure. Splitting it "
                          "across four would restate it four times."),
            "rejected": [
                {"chart_type": "one histogram per variable as separate figures",
                 "reason": "same argument repeated; the reader has to re-read the framing each time"},
                {"chart_type": "box plot only",
                 "reason": "understates the tail, which is precisely what decides the test choice"},
            ],
        })

    # ---- figure 2: does the grouping variable move the outcomes? -----------
    if inf and inf.get("group"):
        group = inf.get("group")
        # a column that is a relabelling of the grouping variable is not
        # evidence about it, and including it would inflate the family
        excluded = {c for c in numeric
                    if df is not None and c in df.columns
                    and all(df.loc[df[group] == lv, c].dropna().nunique() <= 1
                            for lv in inf.get("group_levels", []))}
        cpanels = []
        for t in inf.get("tests", []):
            if t.get("outcome") == group or t.get("outcome") in excluded:
                continue
            pnl = _comparison_panel(inf, group, t)
            if pnl:
                cpanels.append(pnl)
        # the strongest evidence first; cap at four panels so the grid stays readable
        cpanels.sort(key=lambda r: (r["p_adjusted"], r["n_total"] or 0))
        cpanels = cpanels[:4]
        if cpanels:
            fam = ((inf.get("multiple_comparisons") or {}).get("primary_family") or {})
            fam_n = fam.get("family_size")
            n_sig = sum(1 for r in cpanels if r["significant"])
            methods = sorted({r["method"] for r in cpanels})
            add({
                "argument_task": f"test whether {group} moves the measured outcomes",
                "chart_type": "small_multiples_ci",
                "spec": {"group": group, "panels": cpanels, "n_panels": len(cpanels)},
                "uncertainty": "95% confidence intervals on every group mean",
                "title": (f"{n_sig} of {len(cpanels)} measured outcomes differ across {group} "
                          f"after correction for multiple comparisons"),
                "caption": ("Mean of each outcome by %s with 95%% confidence intervals, %s. "
                            "%s. Raw p values are BH-corrected across a family of %s outcomes."
                            % (group,
                               ", ".join(inf.get("group_levels", [])),
                               "; ".join(methods),
                               fam_n if fam_n else "the")),
                "body": {
                    "fact": _join_sentences([r["sentence"] for r in cpanels]),
                    "interpretation": ("Each panel is one outcome; the intervals overlap where the "
                                       "difference is not distinguishable from noise."
                                       if n_sig < len(cpanels) else
                                       "Every tested outcome separates the groups."),
                    "implication": ("Carry the effect sizes forward, not the p values: a difference "
                                    "that is real can still be too small to matter."
                                    if n_sig else
                                    "No tested outcome separates the groups; report that plainly "
                                    "rather than reaching for a subgroup."),
                },
                "complexity_principles": ["1_one_argument", "6_uncertainty",
                                          "2_third_dimension_must_earn"],
                "rationale": ("One argument -- does the grouping variable move anything -- shown for "
                              "every outcome at once. Four separate bar charts would be one "
                              "argument told four times."),
                "rejected": [
                    {"chart_type": "pie chart", "reason": "group means are not parts of a whole"},
                    {"chart_type": "3D bar chart", "reason": "the third dimension encodes nothing"},
                    {"chart_type": "radar chart", "reason": "angle and area are hard to compare and "
                                                           "imply the axes are commensurate"},
                ],
            })

    # ---- figure 3: what else moves together? ------------------------------
    if inf:
        corr_block = inf.get("correlations") or {}
        cands = [c for c in (corr_block.get("matrix") or []) if c.get("primary")]
        excluded = {c for c in numeric
                    if df is not None and c in df.columns
                    and all(df.loc[df[inf["group"]] == lv, c].dropna().nunique() <= 1
                            for lv in inf.get("group_levels", []))} if inf.get("group") else set()
        ranked = []
        for c in cands:
            chosen = c.get("primary")
            src = c.get(chosen) or {}
            v = src.get("spearman_rho") if chosen == "spearman" else src.get("pearson_r")
            if v is not None and c.get("x") not in excluded and c.get("y") not in excluded:
                ranked.append((abs(v), c))
        ranked.sort(key=lambda t: t[0], reverse=True)
        apanels = []
        seen_pairs = set()
        for _v, c in ranked:
            pnl = _association_panel(inf, c["x"], c["y"], excluded)
            if not pnl:
                continue
            key = tuple(sorted((pnl["x"], pnl["y"])))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            apanels.append(pnl)
            if len(apanels) == 2:
                break
        if apanels:
            lead = apanels[0]
            add({
                "argument_task": "show which measured variables move together, and which do not",
                "chart_type": "scatter_panel",
                "spec": {"panels": apanels, "smoother": "LOWESS"},
                "uncertainty": "LOWESS smoother; coefficient and 95% CI in the caption",
                "title": (f"{lead['x']} and {lead['y']} are the strongest pair "
                          f"({lead['statistic']} = {_fmt(lead['value'])})"
                          + (", and the second-strongest is independent of it"
                             if len(apanels) == 2 and abs(apanels[1]["value"]) < 0.3
                             else "")),
                "caption": ("Each point is one observation. The line is a LOWESS smoother. "
                            "Association only: this figure carries no direction of causation. "
                            "Columns that restate the grouping variable are excluded."),
                "body": {
                    "fact": _join_sentences([r["sentence"] for r in apanels]),
                    "interpretation": ("A visible curve that a straight line would miss is the "
                                       "reason the smoother is drawn at all."
                                       if len(apanels) == 2 else
                                       "The relationship is close to monotone."),
                    "implication": ("Correlation here is a screening result. It says which "
                                    "relationships deserve a model, not which are real."),
                },
                "complexity_principles": ["1_one_argument", "4_numbers_recoverable",
                                          "8_minimum_complexity"],
                "rationale": ("Scatter shows the shape of a relationship, which a coefficient "
                              "cannot; a panel keeps the strongest pair and one contrast so the "
                              "figure is not a correlation matrix in disguise."),
                "rejected": [
                    {"chart_type": "3D scatter", "reason": "a third axis encodes nothing here"},
                    {"chart_type": "full correlation heatmap",
                     "reason": "with this many columns it becomes a grid of numbers rather than "
                               "an argument; the pairs that matter get their own panel"},
                ],
            })

    return {
        "schema_version": "1.1",
        "source": profile.get("source"),
        "palette": PALETTE,
        "markers": MARKERS,
        "n_decisions": len(out),
        "decisions": out,
        "rules": {
            "one_argument_per_figure": "panels, not repeats; a figure that cannot change the "
                                       "reader's understanding is not emitted",
            "uncertainty_mandatory": "every estimate carries an interval, a band or a smoother",
            "title_is_the_finding": "titles are computed from the numbers, never written by hand",
            "2d_before_3d": "a third dimension must change the ranking, and needs a 2D fallback",
            "no_pie_for_comparison": "pie and donut are excluded for >3 categories and for any time axis",
            "restatements_excluded": "a column determined by the grouping variable is not evidence "
                                     "about it, and is kept out of both the figures and the family",
        },
        "rule_source": "references/chart-decision-catalog.md",
    }


def _ci_bounds(ci: Any) -> tuple:
    """Effect sizes carry {"low":..,"high":..}; correlations carry [lo, hi].

    Two shapes for one concept is a nuisance the report should not inherit, so
    it is normalised here rather than at every call site.
    """
    if isinstance(ci, dict):
        return ci.get("low"), ci.get("high")
    if isinstance(ci, (list, tuple)) and len(ci) >= 2:
        return ci[0], ci[1]
    return None, None


def _effect_phrase(t: Dict[str, Any]) -> str:
    eff = t.get("effect_sizes") or {}
    for key in ("omega_squared", "eta_squared", "epsilon_squared", "cohens_d"):
        if key in eff:
            val = eff[key]
            lo, hi = _ci_bounds(eff.get(key + "_ci95"))
            label = key.replace("_", " ")
            if lo is not None:
                return f"{label} = {_fmt(val, 3)} (95% CI {_fmt(lo, 3)} to {_fmt(hi, 3)})"
            return f"{label} = {_fmt(val, 3)}"
    return "an effect size reported in the statistics appendix"


def main() -> int:
    p = argparse.ArgumentParser(description="decide which figures the data warrants")
    p.add_argument("--clean", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--descriptive", required=True)
    p.add_argument("--inferential", default=None)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    # load_cleaned returns (frame, provenance). The provenance matters here: a
    # figure drawn from guessed column types is a figure whose numbers nobody
    # has audited, and the report has to be able to say so.
    df, dtype_provenance = dm_types.load_cleaned(a.clean)
    profile = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    desc = json.loads(Path(a.descriptive).read_text(encoding="utf-8"))
    inf = (json.loads(Path(a.inferential).read_text(encoding="utf-8"))
           if a.inferential and Path(a.inferential).exists() else None)

    doc = build_decisions(df, profile, desc, inf)
    doc["dtype_provenance"] = dtype_provenance
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"chart_decision: {doc['n_decisions']} figure(s) justified -> {a.out}")
    for d in doc["decisions"]:
        print(f"  {d['id']}  {d['chart_type']:<20} {d['title'][:92]}")
    if doc["n_decisions"] == 0:
        print("  no figure is warranted by this data; that is a legitimate outcome, not a failure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
