# Repeated-measures example

This synthetic fixture has 12 independent subjects and 36 rows. Each subject is
observed at three visits and belongs to one study arm. It is intended to verify
that the primary between-arm comparison uses subjects, not rows, as the
independent unit.

```bash
data-master analyze measurements.csv --out outputs \
  --group arm --unit-key subject --outcomes response \
  --title "Repeated-measures treatment comparison"
```

The values are synthetic and do not support a real treatment claim.
