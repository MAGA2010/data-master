# Case study: repeated rows are not independent samples

The dataset records three visits for every subject. A row-level test would claim
three times as many independent observations as the study actually contains.

```bash
data-master analyze examples/repeated_measures/measurements.csv \
  --out examples/repeated_measures/outputs \
  --group arm --unit-key subject --outcomes response \
  --title "Repeated-measures treatment comparison"
```

With `--unit-key subject`, data-master classifies the repeated structure and
runs the primary comparison at the subject level. The row-level result is kept
only as a labelled secondary analysis.

- [Raw input](../../examples/repeated_measures/measurements.csv)
- [Generated report](../../examples/repeated_measures/outputs/report.pdf)
- [Inferential evidence](../../examples/repeated_measures/outputs/analysis/inferential.json)
- [Final audit](../../examples/repeated_measures/outputs/audit/final_audit.md)

This case demonstrates the main statistical safety boundary: more rows do not
automatically mean more independent evidence.
