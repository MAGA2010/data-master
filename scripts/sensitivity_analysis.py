#!/usr/bin/env python3
"""Perturb the primary analysis and report whether the conclusion survives.

Gate 6 used to be satisfied by a rank-based cross-check of the primary test.
That is an assumption-robustness check, not a sensitivity analysis: it asks
"does the test survive a different distributional assumption", never "does the
conclusion survive the data being slightly different". This script runs the
second kind of question and writes the artifact gate 6 now reads:

  leave_one_group_out   k >= 3 groups: drop each group, refit, and ask whether
                        the remaining groups still separate
  block_jackknife       10 seeded blocks of the analysis units; drop each in
                        turn and refit
  exclude_extremes      pre-specified 1.5*IQR fence per group, applied and
                        disclosed -- never a silent trim
  strict_complete_case  one listwise-complete frame across every numeric
                        outcome, versus the primary's per-outcome complete cases
  imputation_sensitivity  when the cleaning plan imputed anything, the
                        complete-case refit on the imputed columns
  row_level_comparison  when the primary analysis is at the unit level, the
                        row-level secondary from inferential.json

Agreement is defined on the significance verdict at the same alpha as the
primary analysis, and every disagreement is reported as a conflict, never
averaged away. A perturbation that could not run is recorded as not runnable;
it never counts as agreeing.

Usage:
    python sensitivity_analysis.py --clean cleaned/cleaned.csv \
        --inferential analysis/inferential.json --out analysis/sensitivity.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dm_types import load_cleaned  # noqa: E402
import stats_inferential as si  # noqa: E402

JACKKNIFE_BLOCKS = 10
SEED = 42
EFFECT_KEYS = ("cohens_d", "omega_squared", "kendalls_w", "cohens_dz",
               "cliffs_delta", "cramers_v", "odds_ratio")


def _effect(rec: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
    es = rec.get("effect_sizes") or {}
    for key in EFFECT_KEYS:
        if key in es and es[key] is not None:
            return key, es[key]
    return None, None


def run_primary(frame: pd.DataFrame, group: str, oc: str, levels: List[Any],
                alpha: float, structure: str, unit_key: Optional[str],
                level: str) -> Dict[str, Any]:
    """Re-run the primary dispatch for one outcome on (possibly filtered) data."""
    if structure == "paired":
        return si.paired_two_group(frame, group, oc, str(levels[0]),
                                   str(levels[1]), unit_key, alpha)
    if structure == "complete_blocks":
        return si.friedman_complete_blocks(frame, group, oc, unit_key, alpha)
    return si._outcome_tests(frame, group, levels, [oc], alpha, level)[0]


def frame_at_level(df: pd.DataFrame, group: str, numeric_cols: List[str],
                   structure: str, unit_key: Optional[str]) -> pd.DataFrame:
    """Rebuild the analysis frame the way stats_inferential built the primary."""
    if structure == "clustered" and unit_key:
        return si.aggregate_to_units(df, group, unit_key, numeric_cols)
    if structure == "incomplete_repeated" and unit_key:
        return (df[[unit_key, group] + [c for c in numeric_cols if c in df.columns]]
                .groupby([unit_key, group], as_index=False)
                .agg({c: "mean" for c in numeric_cols if c in df.columns}))
    return df


def _agree(p_primary: Optional[float], p_perturbed: Optional[float],
           alpha: float) -> Optional[bool]:
    if p_primary is None or p_perturbed is None:
        return None
    return bool((p_primary < alpha) == (p_perturbed < alpha))


def _record(name: str, description: str, rec: Dict[str, Any],
            p_primary: Optional[float], alpha: float,
            parameter: Any = None) -> Dict[str, Any]:
    if not rec.get("estimable", True):
        return {"name": name, "description": description, "parameter": parameter,
                "status": "not_runnable", "reason": rec.get("reason"),
                "agrees": None}
    key, val = _effect(rec)
    agrees = _agree(p_primary, rec.get("p_raw"), alpha)
    return {
        "name": name,
        "description": description,
        "parameter": parameter,
        "status": "ran",
        "method": rec.get("method"),
        "statistic": rec.get("statistic"),
        "p_raw": rec.get("p_raw"),
        "effect_key": key,
        "effect_value": val,
        "n": rec.get("n_total") or rec.get("n_pairs") or rec.get("n_complete_blocks"),
        "agrees": agrees,
    }


def _outcome_frame(df: pd.DataFrame, group: str, oc: str,
                   levels: List[Any]) -> pd.DataFrame:
    return df[[group, oc]].dropna()


def perturbations_for(df: pd.DataFrame, group: str, oc: str, levels: List[Any],
                      alpha: float, structure: str, unit_key: Optional[str],
                      level: str, primary: Dict[str, Any],
                      numeric_cols: List[str],
                      cleaning_run: Dict[str, Any],
                      secondary: Optional[Dict[str, Any]]
                      ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    p0 = primary.get("p_raw")
    numeric_outcome = pd.api.types.is_numeric_dtype(df[oc]) \
        if oc in df.columns else False

    # 1. leave one group out (k >= 3)
    if len(levels) >= 3:
        for lv in levels:
            part = df[df[group] != lv]
            kept = [x for x in levels if x != lv]
            frame = frame_at_level(part, group, numeric_cols, structure, unit_key)
            rec = run_primary(frame, group, oc, kept, alpha, structure,
                              unit_key, level)
            out.append(_record(
                "leave_one_group_out", "drop one group and refit on the rest",
                rec, p0, alpha, parameter=str(lv)))
    else:
        out.append({"name": "leave_one_group_out",
                    "description": "drop one group and refit on the rest",
                    "status": "not_applicable",
                    "reason": f"k={len(levels)} groups; dropping one leaves a single group"})

    # 2. block jackknife over the analysis units
    rng = np.random.default_rng(SEED)
    has_units = unit_key and unit_key in df.columns
    unit_view = (df[[unit_key]].drop_duplicates() if has_units
                 else df.reset_index(drop=True))
    n_units = len(unit_view)
    # with a declared unit the block size is what matters (each drop must leave
    # an estimable remainder), so the bar is lower than for row-level deletion
    min_units = 40 if has_units else 80
    if n_units >= min_units:
        order = rng.permutation(n_units)
        blocks = np.array_split(order, JACKKNIFE_BLOCKS)
        for bi, block in enumerate(blocks, 1):
            if unit_key and unit_key in df.columns:
                dropped = set(unit_view.iloc[block][unit_key].astype(str))
                part = df[~df[unit_key].astype(str).isin(dropped)]
            else:
                part = df.drop(index=df.index[block])
            frame = frame_at_level(part, group, numeric_cols, structure, unit_key)
            rec = run_primary(frame, group, oc, levels, alpha, structure,
                              unit_key, level)
            out.append(_record(
                "block_jackknife",
                f"drop 1/{JACKKNIFE_BLOCKS} of the analysis units and refit",
                rec, p0, alpha, parameter=f"block {bi}"))
    else:
        out.append({"name": "block_jackknife",
                    "description": f"drop 1/{JACKKNIFE_BLOCKS} of the analysis units and refit",
                    "status": "not_applicable",
                    "reason": f"only {n_units} units; block deletion leaves too few per block"})

    # 3. pre-specified extreme-value fence (1.5 IQR per group), numeric only
    if numeric_outcome and structure == "paired":
        # for a paired design the extremes that matter are extreme differences:
        # a unit whose change is unlike the others moves the mean difference
        # and the rank test alike, and the fence must be judged on d, not on
        # the raw per-condition values
        sub = df[[unit_key, group, oc]].dropna()
        wide = sub.pivot_table(index=unit_key, columns=group, values=oc,
                               aggfunc="mean")
        if set(map(str, levels)) <= set(map(str, wide.columns)):
            wide = wide.dropna(subset=[str(levels[0]), str(levels[1])])
            d = (wide[str(levels[0])] - wide[str(levels[1])]).astype(float)
            q1, q3 = d.quantile([0.25, 0.75])
            lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            keep = d[(d >= lo) & (d <= hi)].index
            n_excluded = len(d) - len(keep)
            if len(keep) >= 8 and n_excluded > 0:
                part = df[df[unit_key].astype(str).isin(set(map(str, keep)))]
                rec = run_primary(part, group, oc, levels, alpha, structure,
                                  unit_key, level)
                out.append(_record(
                    "exclude_extremes",
                    "exclude units whose paired difference lies outside the "
                    "1.5*IQR fence (pre-specified, disclosed)",
                    rec, p0, alpha,
                    parameter=f"{n_excluded} unit difference(s) excluded"))
            else:
                out.append({"name": "exclude_extremes",
                            "description": "exclude units whose paired difference "
                                           "lies outside the 1.5*IQR fence",
                            "status": "not_applicable",
                            "reason": "no paired difference fell outside the fence"
                                      if n_excluded == 0 else
                                      "too few units would remain"})
        else:
            out.append({"name": "exclude_extremes",
                        "description": "exclude units whose paired difference lies "
                                       "outside the 1.5*IQR fence",
                        "status": "not_applicable",
                        "reason": "paired differences could not be formed"})
    elif numeric_outcome and structure in ("undeclared", "independent_rows",
                                           "clustered", "incomplete_repeated",
                                           "unit", "unit x group cell", "row"):
        keep_cols = [c for c in (([unit_key] if unit_key else []) + [group, oc])
                     if c in df.columns]
        sub = df[keep_cols].dropna().copy()
        keep_mask = pd.Series(True, index=sub.index)
        n_excluded = 0
        for lv in levels:
            vals = pd.to_numeric(sub.loc[sub[group] == lv, oc], errors="coerce")
            q1, q3 = vals.quantile([0.25, 0.75])
            fence_lo, fence_hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            inside = (vals >= fence_lo) & (vals <= fence_hi)
            n_excluded += int((~inside).sum())
            keep_mask.loc[inside.index] = keep_mask.loc[inside.index] & inside
        part = sub[keep_mask]
        if len(part) >= 8 and n_excluded > 0:
            frame = frame_at_level(part, group, numeric_cols, structure, unit_key)
            rec = run_primary(frame, group, oc, levels, alpha, structure,
                              unit_key, level)
            out.append(_record(
                "exclude_extremes",
                "exclude values outside the 1.5*IQR fence of their own group "
                "(pre-specified, disclosed)",
                rec, p0, alpha, parameter=f"{n_excluded} value(s) excluded"))
        else:
            out.append({"name": "exclude_extremes",
                        "description": "exclude values outside the 1.5*IQR fence of "
                                       "their own group (pre-specified, disclosed)",
                        "status": "not_applicable",
                        "reason": "no value fell outside its group's fence"
                                  if n_excluded == 0 else
                                  f"only {len(part)} rows would remain"})
    else:
        out.append({"name": "exclude_extremes",
                    "description": "exclude values outside the 1.5*IQR fence of their "
                                   "own group (pre-specified, disclosed)",
                    "status": "not_applicable",
                    "reason": "extreme-value exclusion is defined for numeric "
                              "between-group comparisons only"})

    # 4. strict complete-case across all numeric outcomes
    if len(numeric_cols) > 1:
        part = df.dropna(subset=[group] + [c for c in numeric_cols if c in df.columns])
        frame = frame_at_level(part, group, numeric_cols, structure, unit_key)
        rec = run_primary(frame, group, oc, levels, alpha, structure,
                          unit_key, level)
        out.append(_record(
            "strict_complete_case",
            "restrict to rows complete across every numeric outcome "
            "(listwise), versus the primary's per-outcome complete cases",
            rec, p0, alpha,
            parameter=f"n={len(part)} of {len(df)} rows"))
    else:
        out.append({"name": "strict_complete_case",
                    "description": "restrict to rows complete across every numeric "
                                   "outcome (listwise)",
                    "status": "not_applicable",
                    "reason": "only one numeric outcome; per-outcome and listwise "
                              "complete cases are identical"})

    # 5. imputation sensitivity, only when something was imputed
    imputed_cols = sorted({c for op in (cleaning_run.get("applied_ops") or [])
                           if "impute" in str(op.get("op", ""))
                           for c in (op.get("columns") or [])})
    if imputed_cols:
        part = df.dropna(subset=[c for c in imputed_cols if c in df.columns])
        if len(part) >= 8:
            frame = frame_at_level(part, group, numeric_cols, structure, unit_key)
            rec = run_primary(frame, group, oc, levels, alpha, structure,
                              unit_key, level)
            out.append(_record(
                "imputation_sensitivity",
                "complete-case refit on the columns the cleaning plan imputed",
                rec, p0, alpha,
                parameter="imputed: %s" % ", ".join(imputed_cols)))
        else:
            out.append({"name": "imputation_sensitivity",
                        "description": "complete-case refit on the columns the "
                                       "cleaning plan imputed",
                        "status": "not_runnable",
                        "reason": "too few rows remain complete on the imputed columns"})
    else:
        out.append({"name": "imputation_sensitivity",
                    "description": "complete-case refit on the columns the cleaning "
                                   "plan imputed",
                    "status": "not_applicable",
                    "reason": "nothing was imputed; every analysed value was observed"})

    # 6. row-level comparison when the primary moved off the row
    if secondary:
        row_rec = next((t for t in (secondary.get("tests") or [])
                        if t.get("outcome") == oc), None)
        if row_rec and row_rec.get("estimable"):
            key, val = _effect(row_rec)
            out.append({
                "name": "row_level_comparison",
                "description": "the row-level secondary analysis from "
                               "inferential.json, kept for comparison; it treats "
                               "repeated rows as independent and its n is inflated",
                "status": "ran",
                "method": row_rec.get("method"),
                "statistic": row_rec.get("statistic"),
                "p_raw": row_rec.get("p_raw"),
                "effect_key": key, "effect_value": val,
                "n": row_rec.get("n_total"),
                "agrees": _agree(p0, row_rec.get("p_raw"), alpha),
            })
        else:
            out.append({"name": "row_level_comparison",
                        "description": "the row-level secondary analysis from "
                                       "inferential.json",
                        "status": "not_runnable",
                        "reason": (row_rec or {}).get("reason") if row_rec else
                                  "no secondary record for this outcome",
                        "agrees": None})

    # 7. the rank cross-check already recorded on the primary, referenced not recomputed
    rc = primary.get("robustness_cross_check")
    if rc and rc.get("test"):
        out.append({
            "name": "rank_cross_check",
            "description": "the rank-based cross-check recorded on the primary "
                           "test in inferential.json (assumption robustness)",
            "status": "ran",
            "method": rc.get("test"),
            "statistic": rc.get("statistic"),
            "p_raw": rc.get("p_raw"),
            "agrees": rc.get("agrees_with_primary"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", required=True)
    ap.add_argument("--inferential", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--group", default=None,
                    help="grouping column; default is the one inferential.json used")
    ap.add_argument("--alpha", type=float, default=None,
                    help="family alpha; default is the one inferential.json used")
    args = ap.parse_args()

    inf = json.loads(Path(args.inferential).read_text(encoding="utf-8"))
    group = args.group or inf.get("group")
    alpha = args.alpha if args.alpha is not None else float(inf.get("alpha", 0.05))
    level = inf.get("primary_level") or "row"
    structure = (inf.get("unit_of_analysis") or {}).get("structure", "undeclared")
    unit_key = (inf.get("unit_of_analysis") or {}).get("unit_key")
    secondary = inf.get("secondary_row_level")

    if inf.get("skipped"):
        payload = {
            "schema_version": "1.0", "source": args.clean, "group": group,
            "alpha": alpha, "outcomes": [], "skipped": inf.get("skipped"),
            "summary": {"n_outcomes": 0, "n_perturbations": 0,
                        "n_agreeing": 0, "n_conflicting": 0, "conflicts": []},
            "rule_source": "references/nature-statistics-checklist.md#gate-6",
        }
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        print("sensitivity: skipped -- no inferential family was formed")
        return 0

    df, _ = load_cleaned(Path(args.clean))
    if group not in df.columns:
        print(f"ERROR: group column {group!r} not in {args.clean}", file=sys.stderr)
        return 1
    levels = sorted(pd.unique(df[group].dropna()), key=str)
    if len(levels) < 2:
        print(f"ERROR: group column {group!r} has {len(levels)} level(s)", file=sys.stderr)
        return 1

    cleaning_run_path = Path(args.clean).parent / "cleaning_run.json"
    cleaning_run: Dict[str, Any] = {}
    if cleaning_run_path.exists():
        try:
            cleaning_run = json.loads(cleaning_run_path.read_text(encoding="utf-8"))
        except Exception:
            cleaning_run = {}

    numeric_cols = [c for c in df.columns
                    if c != group and c != unit_key
                    and pd.api.types.is_numeric_dtype(df[c])]

    outcomes: List[Dict[str, Any]] = []
    n_agree_total = n_conflict_total = 0
    conflicts_all: List[Dict[str, Any]] = []
    for t in (inf.get("tests") or []):
        oc = t.get("outcome")
        if not oc or not t.get("estimable"):
            continue
        primary = run_primary(df, group, oc, levels, alpha, structure,
                              unit_key, level) if structure in ("paired",
                                                                "complete_blocks") else \
            run_primary(frame_at_level(df, group, numeric_cols, structure, unit_key),
                        group, oc, levels, alpha, structure, unit_key, level)
        perts = perturbations_for(df, group, oc, levels, alpha, structure,
                                  unit_key, level, t, numeric_cols, cleaning_run,
                                  secondary)
        ran = [x for x in perts if x.get("status") == "ran" and x.get("agrees") is not None]
        agree = [x for x in ran if x["agrees"] is True]
        conflict = [x for x in ran if x["agrees"] is False]
        n_agree_total += len(agree)
        n_conflict_total += len(conflict)
        for x in conflict:
            conflicts_all.append({
                "outcome": oc, "perturbation": x["name"],
                "primary_p": (t.get("p_raw") if t.get("p_raw") is not None
                              else primary.get("p_raw")),
                "perturbed_p": x.get("p_raw"),
            })
        outcomes.append({
            "outcome": oc,
            "design": t.get("design"),
            "primary": {"method": t.get("method"), "statistic": t.get("statistic"),
                        "p_raw": t.get("p_raw"), "p_adjusted": t.get("p_adjusted"),
                        "analysis_level": level},
            "perturbations": perts,
            "n_perturbations_ran": len(ran),
            "n_agreeing": len(agree),
            "n_conflicting": len(conflict),
        })

    payload = {
        "schema_version": "1.0",
        "source": args.clean,
        "group": group,
        "alpha": alpha,
        "analysis_level": level,
        "jackknife": {"blocks": JACKKNIFE_BLOCKS, "seed": SEED},
        "outcomes": outcomes,
        "summary": {
            "n_outcomes": len(outcomes),
            "n_perturbations": n_agree_total + n_conflict_total,
            "n_agreeing": n_agree_total,
            "n_conflicting": n_conflict_total,
            "conflicts": conflicts_all,
        },
        "rule_source": "references/nature-statistics-checklist.md#gate-6",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"sensitivity written: {out}")
    print(f"  outcomes: {len(outcomes)}  perturbations: {n_agree_total + n_conflict_total}  "
          f"agreeing: {n_agree_total}  conflicting: {n_conflict_total}")
    for c in conflicts_all:
        print(f"  CONFLICT {c['outcome']} / {c['perturbation']}: "
              f"p {c['primary_p']} -> {c['perturbed_p']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
