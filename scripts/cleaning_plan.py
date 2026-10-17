"""Build a deterministic cleaning plan from profile.json.

The plan is the auditable contract between profiling and cleaning. It has two
halves:
  - auto_actions        : ops that may run without asking (severity P2/P3 only,
                          plus a small set of P1 ops that destroy no information)
  - never_automatic_flags : ops a human must decide, each with the default that
                          would apply if the user stays silent

Every op carries `rule_source` pointing at references/cleaning-rule-catalog.md so
the report can prove where the decision came from.

Usage:
    python cleaning_plan.py --profile analysis/profile.json --out outputs/cleaning_plan.json
    python cleaning_plan.py --profile analysis/profile.json --out outputs/cleaning_plan.json \
        --impute median --remove-outliers zscore --dedupe-key patient_id
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

CATALOG = "references/cleaning-rule-catalog.md"
NEVER_LIST = "references/never-automatic-list.md"

# id -> (op, severity, default, applies_to_roles)
# applies_to_roles uses dm_types.column_role() values.
TABLE_RULES: Dict[str, Dict[str, Any]] = {
    "t-fix-unicode":        {"op": "fix_unicode",              "severity": "P3", "default": "auto",  "roles": ["categorical", "binary", "text"]},
    "t-strip-ws":           {"op": "strip_whitespace",         "severity": "P3", "default": "auto",  "roles": ["categorical", "binary", "text"]},
    "t-collapse-whitespace":{"op": "collapse_whitespace",      "severity": "P3", "default": "auto",  "roles": ["categorical", "binary", "text"]},
    "t-trim-quotes":        {"op": "trim_paired_quotes",       "severity": "P3", "default": "auto",  "roles": ["categorical", "binary", "text"]},
    "t-coerce-numeric":     {"op": "coerce_numeric",           "severity": "P2", "default": "auto",  "roles": ["categorical"]},
    "t-coerce-dates":       {"op": "coerce_dates",             "severity": "P2", "default": "auto",  "roles": ["categorical"]},
    "t-normalize-dtypes":   {"op": "normalize_dtypes",         "severity": "P2", "default": "auto",  "roles": ["categorical", "binary"]},
    "t-drop-all-null-cols": {"op": "drop_all_null_cols",       "severity": "P1", "default": "auto",  "roles": ["__cols__"]},
    "t-drop-all-null-rows": {"op": "drop_all_null_rows",       "severity": "P1", "default": "auto",  "roles": ["__rows__"]},
    "t-rename-clean":       {"op": "rename_columns_append_cleaned", "severity": "P2", "default": "auto", "roles": ["__cols__"]},
    # ---- never automatic unless the user opts in ----
    "t-lowercase":          {"op": "lowercase",                "severity": "P2", "default": "never", "roles": ["categorical", "binary"]},
    "t-merge-case-variants":{"op": "merge_case_variants",      "severity": "P2", "default": "auto",  "roles": ["categorical", "binary"]},
    "t-dedupe-exact":       {"op": "dedupe_exact",             "severity": "P1", "default": "never", "roles": ["__rows__"]},
    "t-dedupe-key":         {"op": "dedupe_key",               "severity": "P1", "default": "never", "roles": ["__by_key__"]},
    "t-drop-high-null-rows":{"op": "drop_high_null_rows",      "severity": "P1", "default": "never", "roles": ["__rows__"]},
    "t-coerce-bool":        {"op": "coerce_bool",              "severity": "P2", "default": "never", "roles": ["categorical"]},
    "t-flag-outliers-z":    {"op": "flag_outliers_zscore",     "severity": "P2", "default": "never", "roles": ["numeric"]},
    "t-winsorize":          {"op": "winsorize",                "severity": "P1", "default": "never", "roles": ["numeric"]},
    "t-impute-mean":        {"op": "impute_mean",              "severity": "P1", "default": "never", "roles": ["numeric"]},
    "t-impute-median":      {"op": "impute_median",            "severity": "P1", "default": "never", "roles": ["numeric"]},
    "t-impute-mode":        {"op": "impute_mode",              "severity": "P1", "default": "never", "roles": ["categorical", "binary"]},
    "t-impute-knn":         {"op": "impute_knn",               "severity": "P1", "default": "never", "roles": ["numeric"]},
    "t-impute-mice":        {"op": "impute_mice",              "severity": "P1", "default": "never", "roles": ["numeric"]},
    "t-onehot":             {"op": "onehot_encode",            "severity": "P2", "default": "never", "roles": ["categorical", "binary"]},
    "t-label-encode":       {"op": "label_encode",             "severity": "P2", "default": "never", "roles": ["categorical", "binary"]},
    "t-normalize-zscore":   {"op": "normalize_zscore",         "severity": "P2", "default": "never", "roles": ["numeric"]},
    "t-normalize-minmax":   {"op": "normalize_minmax",         "severity": "P2", "default": "never", "roles": ["numeric"]},
    "t-comma-decimal":      {"op": "comma_decimal_to_dot",     "severity": "P2", "default": "never", "roles": ["categorical"]},
    "t-drop-impossible":    {"op": "flag_impossible_values",   "severity": "P1", "default": "never", "roles": ["numeric"]},
}

USER_FLAGS = {
    "--impute":                ("method", ["t-impute-mean", "t-impute-median", "t-impute-mode", "t-impute-knn", "t-impute-mice"]),
    "--remove-outliers":       ("method", ["t-flag-outliers-z", "t-winsorize"]),
    "--winsorize":             ("q",      ["t-winsorize"]),
    "--onehot":                ("max_card", ["t-onehot"]),
    "--normalize":             ("method", ["t-normalize-zscore", "t-normalize-minmax"]),
    "--dedupe-key":            ("key",    ["t-dedupe-key"]),
    "--drop-high-null-rows":   ("threshold", ["t-drop-high-null-rows"]),
    "--lowercase":             ("value",  ["t-lowercase"]),
    "--merge-case-variants":   ("value",  ["t-merge-case-variants"]),
    "--drop-impossible":       ("value",  ["t-drop-impossible"]),
    "--dedupe-exact":          ("value",  ["t-dedupe-exact"]),
    "--coerce-bool":           ("value",  ["t-coerce-bool"]),
    "--label-encode":          ("value",  ["t-label-encode"]),
    "--comma-decimal":         ("value",  ["t-comma-decimal"]),
    # Overrides the leading-zero / currency hold on t-coerce-numeric. Comma-separated
    # column list, e.g. --force-coerce-numeric "zip,phone". Recorded in the action
    # as user_opt_in so the report can prove a human authorised it.
    "--force-coerce-numeric":  ("columns", ["t-coerce-numeric"]),
    "--force-coerce-dates":    ("columns", ["t-coerce-dates"]),
}


def _targets_for(roles: List[str], df_roles: Dict[str, str], specific: List[str]) -> List[str]:
    """Resolve which columns a rule applies to."""
    want = set(roles)
    return sorted([c for c, r in df_roles.items() if r in want] + [c for c in specific if c in df_roles])


def build_plan(profile: Dict[str, Any], user_opts: Dict[str, str]) -> Dict[str, Any]:
    roles: Dict[str, str] = profile.get("column_roles") or {c: e["role"] for c, e in profile["columns"].items()}
    n_rows = int(profile["shape"]["n_rows"])
    flags_in: List[Dict[str, Any]] = profile.get("anomalies", {}).get("flags", [])

    auto: List[Dict[str, Any]] = []
    never: List[Dict[str, Any]] = []

    def add(rule_id: str, columns: List[str], via: str | None = None, param: Any = None) -> None:
        r = TABLE_RULES[rule_id]
        entry = {
            "id": rule_id,
            "op": r["op"],
            "columns": columns,
            "severity": r["severity"],
            "rule_source": f"{CATALOG}#tabular:{rule_id}",
        }
        if via:
            entry["user_opt_in"] = {"flag": via, "param": param}
        auto.append(entry)

    def flag(op: str, columns: List[str], reason: str, ask: str, default: str,
             severity: str = "P1", detail: Any = None) -> None:
        e = {"op": op, "columns": columns, "reason": reason, "ask_user": ask,
             "default_if_silent": default, "severity": severity,
             "rule_source": f"{NEVER_LIST}#conditional-never"}
        if detail is not None:
            e["detail"] = detail
        never.append(e)

    # columns that carry no information at all: never a target for any op
    all_null_cols = [f["column"] for f in flags_in if f["type"] == "all_missing"]
    live_roles = {c: r for c, r in roles.items() if c not in all_null_cols}

    cat_cols = _targets_for(["categorical", "binary"], live_roles, [])
    num_cols = _targets_for(["numeric"], live_roles, [])

    # ---------- automatic hygiene (P3) ----------
    for rid in ("t-fix-unicode", "t-strip-ws", "t-collapse-whitespace", "t-trim-quotes"):
        add(rid, _targets_for(TABLE_RULES[rid]["roles"], live_roles, []))

    # ---------- best-effort coercion (P2, automatic) ----------
    # Gated on the per-column coercion block that profile_tabular built with
    # dm_types.numeric_view / date_view -- the same functions execute_cleaning calls
    # to do the conversion. There is no threshold to tune and no second copy of the
    # rule: a column appears here exactly when the conversion would be lossless.
    coerceable_num: List[str] = []
    coerceable_date: List[str] = []
    holds: Dict[str, str] = {}
    for c in cat_cols:
        co = profile["columns"][c].get("coercion") or {}
        if co.get("auto_numeric"):
            coerceable_num.append(c)
        if co.get("auto_date"):
            coerceable_date.append(c)
        if co.get("hold"):
            holds[c] = co["hold"]
    if coerceable_num:
        add("t-coerce-numeric", coerceable_num)
    if coerceable_date:
        add("t-coerce-dates", coerceable_date)

    # ---------- never-automatic: conversions that would change the value ----------
    # Each hold is a case where the conversion succeeds and returns the wrong number.
    # Nothing here can be caught by a crash test, so the flag carries the evidence
    # (which values, how many, what the options are) instead of just a warning.
    for c, hold in holds.items():
        co = profile["columns"][c].get("coercion") or {}
        nd = co.get("numeric") or {}
        detail: Dict[str, Any] = {"hold": hold, "numeric_probe": nd,
                                  "date_probe": co.get("date")}

        if hold == "leading_zero":
            samples = ", ".join(repr(x) for x in nd.get("leading_zero_samples", [])[:3])
            flag("coerce_numeric", [c],
                 f"every value parses as a number, but {nd.get('leading_zero_fraction', 0):.1%} carry a "
                 f"leading zero (e.g. {samples}). Converting would delete the zero-padding and collapse "
                 f"distinct identifiers: in a postcode column, 02134 and 2134 would become one value",
                 "Choose: keep_as_text (default; correct for postcode / phone / product code), or "
                 f"coerce -- asserting the leading zeros are spurious, by re-running with "
                 f"--force-coerce-numeric {c}",
                 "keep_as_text", detail={**detail, "override": f"--force-coerce-numeric {c}"})

        elif hold == "currency_or_rate":
            samples = ", ".join(repr(x) for x in nd.get("currency_or_percent_samples", [])[:3])
            flag("coerce_numeric_currency", [c],
                 "values parse as numbers only once a currency or percent symbol is removed, and the "
                 f"plausible readings give different numbers (e.g. {samples}; "
                 f"{nd.get('would_parse_after_symbol_strip')} of non-null values would parse after "
                 "stripping the symbol)",
                 "Choose: strip_symbol / divide_by_100 / keep_as_text. This skill ships no automatic op "
                 "here on purpose: the unit is a fact about the dataset that the file itself does not "
                 "encode, so any automatic choice would be a guess presented as a result",
                 "keep_as_text", detail=detail)

        elif hold == "numeric_or_date":
            samples = ", ".join(repr(x) for x in nd.get("sample_failed", [])[:2]) or "e.g. '20240115'"
            flag("coerce_numeric_or_date", [c],
                 f"every value parses both as an integer and as a date ({samples}), and the file does not "
                 "record which one was meant. Reading a study's dates as integers is the kind of error "
                 "that survives every later check",
                 f"Choose: keep_as_text (default) / integers --force-coerce-numeric {c} / "
                 f"dates --force-coerce-dates {c}",
                 "keep_as_text",
                 detail={**detail, "numeric_override": f"--force-coerce-numeric {c}",
                         "date_override": f"--force-coerce-dates {c}"})

        elif hold == "mixed_with_text":
            failed = nd.get("sample_failed", [])
            samples = ", ".join(repr(x) for x in failed[:3])
            sentinel = nd.get("failed_are_blank_or_sentinel")
            extra = ("" if not sentinel else
                     " The failures are all blank or conventional sentinels, so treating them as missing "
                     "is defensible -- but 'not recorded' is a claim about the study, not a formatting "
                     "detail, and it stays yours to make.")
            flag("coerce_numeric", [c],
                 f"{nd.get('n_parsed')} of {nd.get('n_non_null')} non-null values parse as numbers and the "
                 f"other {nd.get('n_failed')} do not (e.g. {samples}). Converting would turn those into "
                 f"missing values, after which a recorded category (say 'unknown') would be "
                 f"indistinguishable from a value that was never collected.{extra}",
                 f"Choose: keep_as_text (default) / coerce and accept the loss --force-coerce-numeric {c} / "
                 "map the listed tokens to missing by editing the source file",
                 "keep_as_text",
                 detail={**detail, "override": f"--force-coerce-numeric {c}"})

    # ---------- dtype normalisation (P2, automatic) ----------
    # Low-cardinality text becomes a category dtype, which is a storage and speed
    # decision only: it changes no value, so it is safe to run unattended.
    add("t-normalize-dtypes", cat_cols)

    # ---------- lossless canonicalisation (P2, automatic, fully disclosed) ----------
    # Labels that differ ONLY by case after whitespace stripping collapse to one level.
    # This removes no genuine category; the merge map is written to the report so a
    # human can reverse it. Distinct labels are never merged on judgement.
    case_variant_cols = [c for c in cat_cols
                         if profile["columns"][c].get("residual_case_variants_post_hygiene")]
    if case_variant_cols:
        add("t-merge-case-variants", case_variant_cols)

    # ---------- information-free structures (P1, automatic) ----------
    add("t-drop-all-null-cols", all_null_cols)
    add("t-drop-all-null-rows", [])
    add("t-rename-clean", [])

    # ---------- never-automatic: residual case variants ----------
    for c in cat_cols:
        cv = profile["columns"][c].get("residual_case_variants_post_hygiene")
        if not cv:
            continue
        raw_n = (profile["columns"][c].get("residual_case_variants_raw") or {}).get("n_exact_levels")
        counts = f"{cv['n_exact_levels']} levels -> {cv['n_after_casefold']} after casefold"
        if raw_n and raw_n != cv["n_exact_levels"]:
            counts += f" ({raw_n} levels on raw input, before the automatic whitespace/quote hygiene)"
        never.append({
            "op": "merge_case_variants",
            "columns": [c],
            "reason": f"once the automatic whitespace/quote hygiene has run, {cv['n_merged_groups']} label "
                      f"group(s) still differ only by case ({counts}); collapsed automatically because this "
                      f"is a lossless canonicalisation",
            "ask_user": "Choose: keep_asis (undo the collapse) / merge (default, already applied)",
            "default_if_silent": "merge",
            "severity": "INFO",
            "rule_source": f"{CATALOG}#tabular:t-merge-case-variants",
            "detail": cv,
        })

    # ---------- never-automatic: duplicates ----------
    dup = next((f for f in flags_in if f["type"] == "duplicate_rows"), None)
    if dup:
        flag("dedupe_exact", [],
             f"{dup['count']} exact-duplicate rows ({dup['pct']}% of rows)",
             "Choose: drop_duplicates / keep_all",
             "keep_all",
             detail={"count": dup["count"], "pct": dup["pct"]})

    # ---------- never-automatic: impossible values ----------
    imp = [f for f in flags_in if f["type"] == "impossible_negative"]
    if imp:
        flag("drop_impossible", [f["column"] for f in imp],
             "; ".join(f"`{f['column']}` has {f['n_negatives']} negative value(s) (min={f['min']}) for a "
                       f"physically non-negative quantity" for f in imp),
             "Choose: flag_only / drop_rows / winsorize / set_to_null",
             "flag_only")

    # ---------- never-automatic: missing values ----------
    num_missing = [c for c in num_cols if profile["columns"][c]["n_missing"] > 0]
    cat_missing = [c for c in cat_cols if profile["columns"][c]["n_missing"] > 0]
    if num_missing:
        worst = max(num_missing, key=lambda c: profile["columns"][c]["missing_pct"])
        flag("impute_numeric", num_missing,
             "numeric column(s) with missing values; mechanism not established "
             f"(worst: `{worst}` at {profile['columns'][worst]['missing_pct']}%)",
             "Choose: mean / median / mode / knn / mice / listwise_delete / leave_as_nan",
             "leave_as_nan",
             detail={c: profile["columns"][c]["missing_pct"] for c in num_missing})
    if cat_missing:
        flag("impute_categorical", cat_missing,
             "categorical column(s) with missing values; adding a mode level invents a category",
             "Choose: mode / sentinel_value / listwise_delete / leave_as_nan",
             "leave_as_nan",
             detail={c: profile["columns"][c]["missing_pct"] for c in cat_missing})

    # ---------- never-automatic: outliers ----------
    skewed = [c for c in num_cols
              if abs(profile["columns"][c].get("skew") or 0) > 2
              or profile["columns"][c].get("n_outliers_iqr15", 0) > 0]
    if skewed:
        flag("outliers", skewed,
             "outliers / strong skew detected; removing them changes the distribution",
             "Choose: flag_zscore_3 / flag_iqr_1.5 / winsorize / remove / leave",
             "leave",
             detail={c: {"skew": profile["columns"][c].get("skew"),
                         "n_outliers_iqr15": profile["columns"][c].get("n_outliers_iqr15", 0)} for c in skewed})

    # ---------- user opt-ins ----------
    for flag_name, value in user_opts.items():
        if flag_name not in USER_FLAGS:
            continue
        _, rule_ids = USER_FLAGS[flag_name]
        method = str(value)
        for rid in rule_ids:
            if rid == "t-drop-impossible":
                add(rid, [f["column"] for f in imp], via=flag_name, param=method)
            elif rid == "t-dedupe-exact":
                add(rid, [], via=flag_name, param=method)

            elif rid == "t-impute-*" or rid.startswith("t-impute"):
                add(rid, _targets_for(TABLE_RULES[rid]["roles"], roles, []), via=flag_name, param=method)
            elif rid == "t-normalize-zscore":
                if method in ("zscore", "standard"):
                    add(rid, num_cols, via=flag_name, param=method)
                else:
                    add("t-normalize-minmax", num_cols, via=flag_name, param=method)
            elif rid == "t-flag-outliers-z":
                add(rid, num_cols, via=flag_name, param=method)
            elif rid == "t-winsorize":
                add(rid, num_cols, via=flag_name, param=method)
            elif rid == "t-onehot":
                add(rid, cat_cols, via=flag_name, param=method)
            elif rid == "t-lowercase":
                add(rid, cat_cols, via=flag_name, param=method)
            elif rid == "t-coerce-numeric":
                cols = [x.strip() for x in str(value).split(",") if x.strip()]
                add(rid, cols, via=flag_name, param="forced")
            elif rid == "t-coerce-dates":
                cols = [x.strip() for x in str(value).split(",") if x.strip()]
                add(rid, cols, via=flag_name, param="forced")
            elif rid == "t-dedupe-key":
                add(rid, [str(value)], via=flag_name, param=method)
            elif rid == "t-drop-high-null-rows":
                add(rid, [], via=flag_name, param=method)
            else:
                add(rid, _targets_for(TABLE_RULES[rid]["roles"], roles, []), via=flag_name, param=method)

    # de-duplicate the auto list, keeping first occurrence
    seen = set()
    auto_dedup = []
    for a in auto:
        k = (a["id"], tuple(a["columns"]))
        if k in seen:
            continue
        seen.add(k)
        auto_dedup.append(a)

    return {"auto_actions": auto_dedup, "never_automatic_flags": never, "n_rows": n_rows}


# NOTE: the old _can_be_number / _can_be_date keyword heuristics were deleted here.
# They were a second, independent implementation of a decision that execute_cleaning
# already makes by actually parsing the column. Two implementations of one rule drift,
# and here they had already drifted: the heuristic could approve a coercion that
# execution then declined, so the plan promised an op the report could not show.
# dm_types.numeric_like_report / date_like_report is now the only implementation.


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--impute")
    p.add_argument("--remove-outliers")
    p.add_argument("--winsorize")
    p.add_argument("--onehot")
    p.add_argument("--normalize")
    p.add_argument("--dedupe-key")
    p.add_argument("--drop-high-null-rows")
    p.add_argument("--lowercase", action="store_true")
    p.add_argument("--merge-case-variants", action="store_true")
    p.add_argument("--drop-impossible", action="store_true")
    p.add_argument("--dedupe-exact", action="store_true")
    p.add_argument("--coerce-bool", action="store_true")
    p.add_argument("--label-encode", action="store_true")
    p.add_argument("--comma-decimal", action="store_true")
    p.add_argument("--force-coerce-dates", default=None,
                   help="comma-separated columns to coerce to dates despite also parsing as numbers")
    p.add_argument("--force-coerce-numeric", default=None,
                   help="comma-separated columns to coerce to numeric despite leading zeros / currency symbols")
    args = p.parse_args()

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))

    user_opts: Dict[str, str] = {}
    for name in ("impute", "remove_outliers", "winsorize", "onehot", "normalize", "dedupe_key",
                 "drop_high_null_rows", "lowercase", "merge_case_variants", "drop_impossible",
                 "dedupe_exact", "coerce_bool", "label_encode", "comma_decimal",
                 "force_coerce_numeric", "force_coerce_dates"):
        val = getattr(args, name)
        if val is not None and val is not False:
            user_opts[f"--{name.replace('_', '-')}"] = str(val)

    plan = build_plan(profile, user_opts)
    plan.update({
        "schema_version": "1.2",
        "source": profile["source"],
        # The executor must re-read the raw file exactly as the profiler did, or
        # the plan describes a dataset that never existed on disk.
        "read_mode": profile.get("read_mode", "text"),
        "user_flags": user_opts,
        "n_auto_actions": len(plan["auto_actions"]),
        "n_never_automatic_flags": len(plan["never_automatic_flags"]),
        "principle": "high-risk operations are never silent; see " + NEVER_LIST,
    })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"cleaning_plan written: {args.out}")
    print(f"  auto actions        : {len(plan['auto_actions'])}")
    print(f"  never-automatic     : {len(plan['never_automatic_flags'])}  (default_if_silent = keep data as-is)")
    for f in plan["never_automatic_flags"]:
        print(f"    [{f['severity']}] {f['op']}: {f['columns'] or 'rows'} -> default={f['default_if_silent']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

