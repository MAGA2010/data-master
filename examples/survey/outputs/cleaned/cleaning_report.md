# Cleaning Report — survey_responses.csv

| | |
|---|---|
| Source | `D:\数据处理 skill\examples\survey\survey_responses.csv` |
| Rows | 120 → **120** (+0) |
| Columns | 6 → **6** |
| Raw sha256 | `a023b82a29c35fa8d69e3e4d780db97134241d3a88c4aea6f47e3a11c563d274` |
| Cleaned sha256 | `a023b82a29c35fa8d69e3e4d780db97134241d3a88c4aea6f47e3a11c563d274` |
| Reproducible script | `clean_survey_responses.py` |
| Ops applied | 9 |
| Decisions pending | 3 |
| Decisions answered via answers file | 0 |

> The raw file is never modified. Everything below is additive.

## 1. Applied operations

| ID | Op | Columns | Severity | Rule source | Rows |
|---|---|---|---|---|---|
| `t-fix-unicode` | `fix_unicode` | `age_years`, `minutes_spent`, `recommend`, `respondent_id`, `satisfaction`, `visit_frequency` | P3 | references/cleaning-rule-catalog.md#tabular:t-fix-unicode | 120→120 |
| `t-strip-ws` | `strip_whitespace` | `age_years`, `minutes_spent`, `recommend`, `respondent_id`, `satisfaction`, `visit_frequency` | P3 | references/cleaning-rule-catalog.md#tabular:t-strip-ws | 120→120 |
| `t-collapse-whitespace` | `collapse_whitespace` | `age_years`, `minutes_spent`, `recommend`, `respondent_id`, `satisfaction`, `visit_frequency` | P3 | references/cleaning-rule-catalog.md#tabular:t-collapse-whitespace | 120→120 |
| `t-trim-quotes` | `trim_paired_quotes` | `age_years`, `minutes_spent`, `recommend`, `respondent_id`, `satisfaction`, `visit_frequency` | P3 | references/cleaning-rule-catalog.md#tabular:t-trim-quotes | 120→120 |
| `t-coerce-numeric` | `coerce_numeric` | `age_years`, `minutes_spent` | P2 | references/cleaning-rule-catalog.md#tabular:t-coerce-numeric | 120→120 |
| `t-normalize-dtypes` | `normalize_dtypes` | `age_years`, `minutes_spent`, `recommend`, `respondent_id`, `satisfaction`, `visit_frequency` | P2 | references/cleaning-rule-catalog.md#tabular:t-normalize-dtypes | 120→120 |
| `t-drop-all-null-cols` | `drop_all_null_cols` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-cols | 120→120 |
| `t-drop-all-null-rows` | `drop_all_null_rows` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-rows | 120→120 |
| `t-rename-clean` | `rename_columns_append_cleaned` | — | P2 | references/cleaning-rule-catalog.md#tabular:t-rename-clean | 120→120 |

## 2. Case-variant canonicalisation

No case-variant folding was needed.

## 3. Decisions requiring a human

These were **not** applied. Each one changes the analysis and needs an explicit choice.

### `coerce_numeric` (P1)

- **Columns**: `respondent_id`
- **Why flagged**: every value parses as a number, but 100.0% carry a leading zero (e.g. '0001', '0002', '0003'). Converting would delete the zero-padding and collapse distinct identifiers: in a postcode column, 02134 and 2134 would become one value
- **Question**: Choose: keep_as_text (default; correct for postcode / phone / product code), or coerce -- asserting the leading zeros are spurious, by re-running with --force-coerce-numeric respondent_id
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `coerce_numeric@respondent_id`) and re-run with `--answers`

### `drop_impossible` (P1)

- **Columns**: `age_years`
- **Why flagged**: `age_years` has 12 negative value(s) (min=-999.0) for a physically non-negative quantity
- **Question**: Choose: flag_only / drop_rows / winsorize / set_to_null
- **If you say nothing**: `flag_only`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `drop_impossible@age_years`) and re-run with `--answers`

### `impute_categorical` (P1)

- **Columns**: `minutes_spent`, `satisfaction`, `visit_frequency`
- **Why flagged**: categorical column(s) with missing values; adding a mode level invents a category
- **Question**: Choose: mode / sentinel_value / listwise_delete / leave_as_nan
- **If you say nothing**: `leave_as_nan`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `impute_categorical@minutes_spent,satisfaction,visit_frequency`) and re-run with `--answers`

## 4. Disclosures (already applied, reversible)

None.

## Reproducing this result

```bash
python clean_survey_responses.py
```

The regenerated `cleaned.csv` must hash to `a023b82a29c35fa8d69e3e4d780db97134241d3a88c4aea6f47e3a11c563d274`.
