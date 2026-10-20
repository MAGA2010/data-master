# Case study: synthetic survey data

Survey exports mix labelled answers, coded non-responses and identifiers in
one file. This case study runs a fully synthetic survey (no real participant
data) through the pipeline and shows which decisions data-master makes alone
and which it refuses to make.

```bash
data-master analyze examples/survey/survey_responses.csv \
  --out outputs/survey \
  --group satisfaction --unit-key respondent_id \
  --outcomes minutes_spent \
  --title "Synthetic survey responses"
```

- [Raw input](../../examples/survey/survey_responses.csv) (seeded generator:
  [make_survey.py](../../examples/survey/make_survey.py))
- [Generated report](../../examples/survey/outputs/report.md) ·
  [HTML export](../../examples/survey/outputs/report.html) ·
  [PDF](../../examples/survey/outputs/report.pdf)
- [Audit verdict](../../examples/survey/outputs/audit/final_audit.md)
- [Cleaning plan](../../examples/survey/outputs/cleaning_plan.json)

## What the pipeline decided on its own

- `minutes_spent` converted to numeric, and its Kruskal-Wallis comparison
  across the five satisfaction levels is the primary result (rank epsilon
  squared = 0.86, bootstrap 95% CI 0.75 to 0.96). The rank test was selected
  because group sizes sit below the normality gate.
- Blanks stayed missing. No imputation ran, so every statistic is conditional
  on complete cases, and the audit keeps the missingness mechanism as an open
  question (gate 2 WARN) rather than inventing one.
- Labels stayed labels. No one-hot or integer encoding was applied, so
  "Very dissatisfied" never quietly became a 1 that a mean would average.

## Decisions held for user input

`answers.template.json` lists exactly three, each with the evidence:

1. `coerce_numeric@respondent_id` -- every id parses as a number, but all of
   them carry a leading zero ("0042"). Converting would delete the padding and
   could merge two respondents. Default: keep as text.
2. `drop_impossible@age_years` -- the column's `-999` "not answered" code
   parses as a number, so the column converts cleanly and the profiler then
   finds 12 impossible negative ages. Dropping, nulling or keeping them is a
   claim about how the survey was administered; the default keeps every row
   and flags the values, which is why the descriptive table shows a negative
   minimum age. Resolve it with an answers file before quoting any age
   statistic.
3. `impute_categorical@minutes_spent,satisfaction,visit_frequency` -- blanks
   in the labelled and measured columns. Default: leave as missing.

Filling the template and resuming with `--answers` records who decided, when
and why, and re-runs the affected stages through the same audited path.

The regression pins for this case live in
[`tests/test_survey_case.py`](../../tests/test_survey_case.py).
