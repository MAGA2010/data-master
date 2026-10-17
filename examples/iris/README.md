# iris: dirty data to audited report

This example exercises the full tabular path on a deliberately damaged copy of
the Iris dataset. The generated input is `158 x 8`; the original raw file is
never modified.

## Reproduce

```powershell
python examples/iris/make_dirty_iris.py
python scripts/run_pipeline.py `
  --in examples/iris/iris_dirty.csv `
  --out examples/iris/outputs `
  --title "Iris morphometrics" `
  --journal nature
```

Inspect the run:

```powershell
python scripts/state_keeper.py --state examples/iris/outputs/state.json --show
python scripts/state_keeper.py --state examples/iris/outputs/state.json --validate
```

## Injected defects

- `notes` is entirely null and must be removed through the cleaning plan.
- `height_m` contains a leading-zero value, so automatic numeric coercion is
  withheld instead of deleting evidence.
- `species` carries case variants. Cleaning merges them with a complete,
  reversible map before grouping.
- `petal_width_cm` and `sepal_width_cm` contain missing values. They are not
  imputed silently.
- Exact duplicate rows are flagged but retained until independence is declared.

## Expected result

- Cleaning: 10 documented operations, byte-for-byte replay passes and the
  untouched-column audit passes.
- Validation: all cleaning checks pass.
- Statistics: four real outcomes are compared across three Iris species, with
  effect sizes, 95% confidence intervals, BH-adjusted p-values and rank-based
  sensitivity checks.
- Deliverables: a multi-page `report.pdf`, figures, provenance and an 8-gate
  audit.
- Verdict: seven gates pass. Gate 1 remains open because the input does not say
  what one row represents; the report is therefore explicitly
  **not submission-ready**.

The checked-in `outputs/` directory shows a complete generated result. It is a
reference artifact, not a substitute for rerunning the pipeline.
