# Case study: identifiers that look numeric

The input contains values that ordinary type inference can silently reinterpret:
leading-zero identifiers, percentages, currency, dates and mixed numeric/text
columns.

```bash
data-master analyze examples/column_traps/traps_dirty.csv \
  --out outputs/identifier-traps \
  --title "Identifier integrity review"
```

data-master reads delimited text in text space, records proposed conversions in
`cleaning_plan.json` and holds ambiguous conversions for a human answer. The
cleaning validation compares untouched columns with the raw values and the
generated replay script must reproduce the cleaned bytes exactly.

- [Raw input](../../examples/column_traps/traps_dirty.csv)
- [Cleaning plan](../../examples/column_traps/outputs/cleaning_plan.json)
- [Validation evidence](../../examples/column_traps/outputs/cleaned/validation.json)
- [Cleaned output](../../examples/column_traps/outputs/cleaned/cleaned.csv)

The important outcome is the refusal: a postcode such as `02134` is not silently
converted to `2134` before an audit trail exists.
