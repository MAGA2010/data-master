# Case study: a report exists, but the audit refuses submission

The Iris example completes profiling, cleaning, analysis, sensitivity checks,
figures and a PDF. It deliberately omits a declaration of the independent unit.

```bash
data-master analyze examples/iris/iris_dirty.csv \
  --out examples/iris/outputs \
  --title "Iris morphometrics" --journal nature
```

The report is generated, while audit gate 1 remains failed and missingness gate
2 remains a warning. This prevents a polished report from being confused with a
fully specified study.

- [Raw input](../../examples/iris/iris_dirty.csv)
- [Generated report](../../examples/iris/outputs/report.pdf)
- [Sensitivity evidence](../../examples/iris/outputs/analysis/sensitivity.json)
- [Final audit](../../examples/iris/outputs/audit/final_audit.md)

The refusal is a feature: decisions that require study context remain visible
instead of being invented by the pipeline.
