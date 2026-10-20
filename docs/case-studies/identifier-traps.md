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

## Benchmark: date or number?

A second, minimal fixture isolates one ambiguity: values that parse as dates
and as numbers at the same time.

```bash
data-master analyze examples/date_number_ambiguity/session_export.csv \
  --out outputs/date-number-ambiguity \
  --title "Date-versus-number ambiguity"
```

Every `session_stamp` value is a bare 8-digit integer such as `20240115`. As an
integer it is 20,240,115; parsed as YYYYMMDD it is 2024-01-15. The file does
not record which one the author meant, and the two readings support different
analyses (a time ordering versus a numeric distribution).

The observed behaviour:

- the profile probes both parsers, finds both succeed on every value, and
  records the evidence in `analysis/profile.json` under
  `columns.session_stamp.coercion`;
- `cleaning_plan.json` raises a `coerce_numeric_or_date@session_stamp` flag
  with `default_if_silent = keep_as_text`, and `answers.template.json` offers
  exactly three actions: `keep_as_text`, `integers`, `dates`;
- automatic cleaning leaves the column byte-identical to the raw input
  (see [validation evidence](../../examples/date_number_ambiguity/outputs/cleaned/validation.json));
- one explicit answer converts it. An answers file holding
  `{"id": "coerce_numeric_or_date@session_stamp", "action": "dates"}` resolves
  the flag with provenance and the column becomes ISO dates through the same
  audited operation path. This resolution is exercised by
  `tests/test_date_number_ambiguity.py`.

- [Raw input](../../examples/date_number_ambiguity/session_export.csv)
- [Generator](../../examples/date_number_ambiguity/make_fixture.py)
- [Cleaning plan](../../examples/date_number_ambiguity/outputs/cleaning_plan.json)
- [Report](../../examples/date_number_ambiguity/outputs/report.md)
