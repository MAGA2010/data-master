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

## Compact dates or numbers

The six-row [compact-date fixture](../../examples/column_traps/compact_date_or_number.csv)
contains values such as `20240115` and `20240229`: each parses as both an
integer and a calendar date. The plan records a `numeric_or_date` hold with
both parser probes under `coerce_numeric_or_date@compact_value`. By default,
cleaning keeps the original strings.

If a codebook confirms YYYYMMDD dates, an answers file can explicitly resolve
that hold:

```json
{
  "decisions": [{
    "id": "coerce_numeric_or_date@compact_value",
    "action": "dates",
    "decided_by": "dataset-owner",
    "rationale": "The codebook declares YYYYMMDD calendar dates."
  }]
}
```

Pass the file with `--answers` when rebuilding the cleaning plan. The plan and
cleaning run retain who decided, when, why and which file supplied the answer.
The regression tests verify the default hold and this explicit resolution,
including replay reproducibility and preservation of the leading-zero
`sample_code` and text `note` controls. If the codebook declares integers,
`integers` is also an allowed answer; the values alone cannot choose for you.
