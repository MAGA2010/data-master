# Cleaning Report — iris_dirty.csv

| | |
|---|---|
| Source | `D:\数据处理 skill\examples\iris\iris_dirty.csv` |
| Rows | 158 → **158** (+0) |
| Columns | 8 → **7** |
| Raw sha256 | `d5e5668ecd92e4d30c13aa6ee875a6dd6a40ded6517d69a97800b67540f2ec86` |
| Cleaned sha256 | `7c1b8a3004c28c85cfb2ff94ee43d4cf0f7be37b60dbe361f9d55160208592df` |
| Reproducible script | `clean_iris_dirty.py` |
| Ops applied | 10 |
| Decisions pending | 4 |
| Decisions answered via answers file | 0 |

> The raw file is never modified. Everything below is additive.

## 1. Applied operations

| ID | Op | Columns | Severity | Rule source | Rows |
|---|---|---|---|---|---|
| `t-fix-unicode` | `fix_unicode` | `height_m`, `petal_length_cm`, `petal_width_cm`, `sepal_length_cm`, `sepal_width_cm`, `species`, `species_code` | P3 | references/cleaning-rule-catalog.md#tabular:t-fix-unicode | 158→158 |
| `t-strip-ws` | `strip_whitespace` | `height_m`, `petal_length_cm`, `petal_width_cm`, `sepal_length_cm`, `sepal_width_cm`, `species`, `species_code` | P3 | references/cleaning-rule-catalog.md#tabular:t-strip-ws | 158→158 |
| `t-collapse-whitespace` | `collapse_whitespace` | `height_m`, `petal_length_cm`, `petal_width_cm`, `sepal_length_cm`, `sepal_width_cm`, `species`, `species_code` | P3 | references/cleaning-rule-catalog.md#tabular:t-collapse-whitespace | 158→158 |
| `t-trim-quotes` | `trim_paired_quotes` | `height_m`, `petal_length_cm`, `petal_width_cm`, `sepal_length_cm`, `sepal_width_cm`, `species`, `species_code` | P3 | references/cleaning-rule-catalog.md#tabular:t-trim-quotes | 158→158 |
| `t-coerce-numeric` | `coerce_numeric` | `petal_length_cm`, `petal_width_cm`, `sepal_length_cm`, `sepal_width_cm`, `species_code` | P2 | references/cleaning-rule-catalog.md#tabular:t-coerce-numeric | 158→158 |
| `t-normalize-dtypes` | `normalize_dtypes` | `height_m`, `petal_length_cm`, `petal_width_cm`, `sepal_length_cm`, `sepal_width_cm`, `species`, `species_code` | P2 | references/cleaning-rule-catalog.md#tabular:t-normalize-dtypes | 158→158 |
| `t-merge-case-variants` | `merge_case_variants` | `species` | P2 | references/cleaning-rule-catalog.md#tabular:t-merge-case-variants | 158→158 |
| `t-drop-all-null-cols` | `drop_all_null_cols` | `notes` | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-cols | 158→158 |
| `t-drop-all-null-rows` | `drop_all_null_rows` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-rows | 158→158 |
| `t-rename-clean` | `rename_columns_append_cleaned` | — | P2 | references/cleaning-rule-catalog.md#tabular:t-rename-clean | 158→158 |

## 2. Case-variant canonicalisation

Labels differing only by case/whitespace were folded. No distinct category was merged; the map below reverses it exactly.

### `species` — 6 → 3 levels (3 groups merged)

| Canonical | Folded variants | n |
|---|---|---|
| `setosa` | `Setosa` | 52 |
| `versicolor` | `Versicolor` | 53 |
| `virginica` | `Virginica` | 53 |

_Canonical rule: modal original spelling, lexicographic tie-break._

## 3. Decisions requiring a human

These were **not** applied. Each one changes the analysis and needs an explicit choice.

### `coerce_numeric` (P1)

- **Columns**: `height_m`
- **Why flagged**: 153 of 158 non-null values parse as numbers and the other 5 do not (e.g. '--', '--', '--'). Converting would turn those into missing values, after which a recorded category (say 'unknown') would be indistinguishable from a value that was never collected. The failures are all blank or conventional sentinels, so treating them as missing is defensible -- but 'not recorded' is a claim about the study, not a formatting detail, and it stays yours to make.
- **Question**: Choose: keep_as_text (default) / coerce and accept the loss --force-coerce-numeric height_m / map the listed tokens to missing by editing the source file
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `coerce_numeric@height_m`) and re-run with `--answers`

### `dedupe_exact` (P1)

- **Columns**: n/a
- **Why flagged**: 9 exact-duplicate rows (5.7% of rows)
- **Question**: Choose: drop_duplicates / keep_all
- **If you say nothing**: `keep_all`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `dedupe_exact@__rows__`) and re-run with `--answers`

### `drop_impossible` (P1)

- **Columns**: `sepal_length_cm`
- **Why flagged**: `sepal_length_cm` has 1 negative value(s) (min=-1.0) for a physically non-negative quantity
- **Question**: Choose: flag_only / drop_rows / winsorize / set_to_null
- **If you say nothing**: `flag_only`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `drop_impossible@sepal_length_cm`) and re-run with `--answers`

### `impute_categorical` (P1)

- **Columns**: `petal_width_cm`, `sepal_width_cm`
- **Why flagged**: categorical column(s) with missing values; adding a mode level invents a category
- **Question**: Choose: mode / sentinel_value / listwise_delete / leave_as_nan
- **If you say nothing**: `leave_as_nan`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `impute_categorical@petal_width_cm,sepal_width_cm`) and re-run with `--answers`

## 4. Disclosures (already applied, reversible)

Applied automatically. Listed here so the automatic choice is never silent.

### `merge_case_variants`

- **Columns**: `species`
- **Detail**: once the automatic whitespace/quote hygiene has run, 3 label group(s) still differ only by case (6 levels -> 3 after casefold); collapsed automatically because this is a lossless canonicalisation
- **Undo**: Choose: keep_asis (undo the collapse) / merge (default, already applied)

## Reproducing this result

```bash
python clean_iris_dirty.py
```

The regenerated `cleaned.csv` must hash to `7c1b8a3004c28c85cfb2ff94ee43d4cf0f7be37b60dbe361f9d55160208592df`.
