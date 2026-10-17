---
name: data-cleaner
description: "Turn profile.json into a deterministic cleaning plan, execute only the planned operations, and prove byte-for-byte reproducibility. Additive-only."
parent: data-master
stage: 1c
---

# data-cleaner

**Stage 1c of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

Whenever `profile.json` exists. Cleaning is never ad hoc: the plan is the gate,
and only `plan["auto_actions"]` may execute.

## Inputs

- `analysis/profile.json`
- `references/cleaning-rule-catalog.md`
- `references/never-automatic-list.md`

## Outputs

- `cleaning_plan.json` -- `auto_actions`, `never_automatic_flags`, `principle`
- `cleaned/cleaned.csv`
- `cleaned/clean_<slug>.py` -- standalone, re-runnable
- `cleaned/cleaning_run.json` -- `applied_ops, withheld, failed, dtype_manifest,
  columns_touched_by_ops, untouched_column_audit, reproducibility_check,
  case_variant_merge_map`
- `cleaned/cleaning_report.md`

## Commands

```powershell
python scripts/cleaning_plan.py --profile outputs/analysis/profile.json --out outputs/cleaning_plan.json
python scripts/execute_cleaning.py --in <raw.csv> --plan outputs/cleaning_plan.json --out outputs/cleaned
python scripts/validate_clean.py --raw <raw.csv> --clean outputs/cleaned/cleaned.csv --profile outputs/analysis/profile.json --out outputs/cleaned/validation.json
```

## Gate (default FAIL)

All five must hold, or the run freezes to `audit/`:
1. `reproducibility_check.passed` -- the generated script reproduces the cleaned hash;
2. `untouched_column_audit.passed` -- no unnamed column changed;
3. no conversion ran unless **every** non-null value parsed (no parse-rate threshold);
4. every never-automatic item is recorded in `withheld` with its evidence;
5. `dtype_manifest` exists and is replayed by the analysis stage.

## Failure modes seen in real runs

- **A 96%% parse rate looks like a green light.** Converting the remaining 4%% turns
  recorded sentinels (`--`, `unknown`) into missing values, which are then
  indistinguishable from values that were never collected. Hold the whole conversion.
- **Case variants split a group.** `Setosa` / `setosa` halves both n and narrows every
  interval without losing information; merge with an explicit `case_variant_merge_map`.
- **A rule rewrites a column it did not name.** The untouched-column audit compares raw
  and cleaned in text space, so this is caught rather than shipped.

## Do not

- do not modify, move, or delete the raw file;
- do not impute, deduplicate, or merge datasets automatically;
- do not add a parse-rate threshold -- the only safe threshold is 100%%.

## Upstream / downstream

- previous: `../data-profiler/SKILL.md`
- next: `../data-explorer/SKILL.md`, `../statistical-analyzer/SKILL.md`
- rules: `../../references/cleaning-rule-catalog.md`
