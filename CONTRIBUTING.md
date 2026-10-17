# Contributing

## The one rule

**A change to a statistical decision needs a test that would have failed before it.**

This repository exists because plausible-looking analysis is easy to produce and
hard to check. A pull request that changes a test selection, a cleaning rule, an
effect-size formula or a report sentence without a regression test will be asked
for one.

## Before you open a PR

```powershell
python tests/test_pipeline_invariants.py          # 33 checks, no pytest needed
python scripts/assemble_report.py --raw examples/iris/iris_dirty.csv --outdir examples/iris/outputs --title "Iris morphometrics"
python scripts/final_audit.py --outdir examples/iris/outputs
```

The audit exits 1 on the iris example **by design**: the independent unit is not
declared, so Gate 1 fails. That is the expected state, not a broken build. What
must hold is that every other gate passes and `structural` is 6/6.

## Adding a cleaning rule

1. Add the rule to `references/cleaning-rule-catalog.md` with an id, the columns
   it may touch, and the hold conditions.
2. Decide whether it is automatic or belongs in
   `references/never-automatic-list.md`.
3. Implement it in `scripts/cleaning_plan.py` (plan) and
   `scripts/execute_cleaning.py` (execution).
4. Add a case to `examples/column_traps/make_traps.py` and a test.

A rule that cannot state which columns it touches will not be merged: the
untouched-column audit depends on that list being exact.

## Adding a modality

A new profiler must:

- never modify the input;
- write `profile.json` with `modality`, `shape`, `columns`, `column_roles`,
  `anomalies.flags`, `independent_unit_hint`;
- report a **flag** rather than dropping a bad record;
- declare its dependencies in `scripts/check_deps.py` as required or optional.

## Adding a journal or checklist

Edit `references/journal-reporting-standards.json` (the machine-readable source)
and `references/journal-reporting-standards.md` (the explanation) together. The
audit reads the JSON; the markdown that nobody can execute is the one that drifts.

## Style

- Python 3.10+, standard library preferred, pandas/numpy/scipy where they earn it.
- No silent `except Exception: pass`. Catch what you expect and say what happened.
- Comments explain *why*, especially where the obvious implementation is wrong.
- Keep a stage's script runnable on its own; the pipeline calls scripts, not
  imports of a monolith.

## Reporting a statistical bug

Open an issue with the smallest input that reproduces it, the artifact that shows
the wrong number, and what the number should have been. If you can, cite the
formula or the reference implementation you checked against -- the Welch df fix
was accepted because it matched `statsmodels.stats.oneway` to six decimals.
