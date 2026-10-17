# Cleaning Report — traps_dirty.csv

| | |
|---|---|
| Source | `D:\数据处理 skill\examples\column_traps\traps_dirty.csv` |
| Rows | 240 → **240** (+0) |
| Columns | 10 → **10** |
| Raw sha256 | `70406770bbcdfea3f73ac47227876651621765ef09e9208ed781b2eb42acddee` |
| Cleaned sha256 | `b28632ff5d33b58fd3d2f26304e306bdfaec13273bc23c1ff4f01b204c808b5d` |
| Reproducible script | `clean_traps_dirty.py` |
| Ops applied | 11 |
| Decisions pending | 4 |

> The raw file is never modified. Everything below is additive.

## 1. Applied operations

| ID | Op | Columns | Severity | Rule source | Rows |
|---|---|---|---|---|---|
| `t-fix-unicode` | `fix_unicode` | `batch_code`, `growth_pct`, `mostly_text`, `phone`, `postcode`, `region`, `revenue`, `signup_date`, `turnover`, `weight_kg` | P3 | references/cleaning-rule-catalog.md#tabular:t-fix-unicode | 240→240 |
| `t-strip-ws` | `strip_whitespace` | `batch_code`, `growth_pct`, `mostly_text`, `phone`, `postcode`, `region`, `revenue`, `signup_date`, `turnover`, `weight_kg` | P3 | references/cleaning-rule-catalog.md#tabular:t-strip-ws | 240→240 |
| `t-collapse-whitespace` | `collapse_whitespace` | `batch_code`, `growth_pct`, `mostly_text`, `phone`, `postcode`, `region`, `revenue`, `signup_date`, `turnover`, `weight_kg` | P3 | references/cleaning-rule-catalog.md#tabular:t-collapse-whitespace | 240→240 |
| `t-trim-quotes` | `trim_paired_quotes` | `batch_code`, `growth_pct`, `mostly_text`, `phone`, `postcode`, `region`, `revenue`, `signup_date`, `turnover`, `weight_kg` | P3 | references/cleaning-rule-catalog.md#tabular:t-trim-quotes | 240→240 |
| `t-coerce-numeric` | `coerce_numeric` | `turnover`, `weight_kg` | P2 | references/cleaning-rule-catalog.md#tabular:t-coerce-numeric | 240→240 |
| `t-coerce-dates` | `coerce_dates` | `signup_date` | P2 | references/cleaning-rule-catalog.md#tabular:t-coerce-dates | 240→240 |
| `t-normalize-dtypes` | `normalize_dtypes` | `batch_code`, `growth_pct`, `mostly_text`, `phone`, `postcode`, `region`, `revenue`, `signup_date`, `turnover`, `weight_kg` | P2 | references/cleaning-rule-catalog.md#tabular:t-normalize-dtypes | 240→240 |
| `t-merge-case-variants` | `merge_case_variants` | `region` | P2 | references/cleaning-rule-catalog.md#tabular:t-merge-case-variants | 240→240 |
| `t-drop-all-null-cols` | `drop_all_null_cols` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-cols | 240→240 |
| `t-drop-all-null-rows` | `drop_all_null_rows` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-rows | 240→240 |
| `t-rename-clean` | `rename_columns_append_cleaned` | — | P2 | references/cleaning-rule-catalog.md#tabular:t-rename-clean | 240→240 |

## 2. Case-variant canonicalisation

Labels differing only by case/whitespace were folded. No distinct category was merged; the map below reverses it exactly.

### `region` — 8 → 4 levels (4 groups merged)

| Canonical | Folded variants | n |
|---|---|---|
| `East` | `EAST` | 64 |
| `North` | `NORTH` | 54 |
| `South` | `SOUTH` | 56 |
| `West` | `WEST` | 66 |

_Canonical rule: modal original spelling, lexicographic tie-break._

## 3. Decisions requiring a human

These were **not** applied. Each one changes the analysis and needs an explicit choice.

### `coerce_numeric_currency` (P1)

- **Columns**: `growth_pct`
- **Why flagged**: values parse as numbers only once a currency or percent symbol is removed, and the plausible readings give different numbers (e.g. '-8.1%', '9.7%', '14.1%'; 1.0 of non-null values would parse after stripping the symbol)
- **Question**: Choose: strip_symbol / divide_by_100 / keep_as_text. This skill ships no automatic op here on purpose: the unit is a fact about the dataset that the file itself does not encode, so any automatic choice would be a guess presented as a result
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never

### `coerce_numeric` (P1)

- **Columns**: `mostly_text`
- **Why flagged**: 216 of 240 non-null values parse as numbers and the other 24 do not (e.g. 'unknown', 'unknown', 'unknown'). Converting would turn those into missing values, after which a recorded category (say 'unknown') would be indistinguishable from a value that was never collected.
- **Question**: Choose: keep_as_text (default) / coerce and accept the loss --force-coerce-numeric mostly_text / map the listed tokens to missing by editing the source file
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never

### `coerce_numeric` (P1)

- **Columns**: `postcode`
- **Why flagged**: every value parses as a number, but 35.4% carry a leading zero (e.g. '02134', '02134', '02139'). Converting would delete the zero-padding and collapse distinct identifiers: in a postcode column, 02134 and 2134 would become one value
- **Question**: Choose: keep_as_text (default; correct for postcode / phone / product code), or coerce -- asserting the leading zeros are spurious, by re-running with --force-coerce-numeric postcode
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never

### `coerce_numeric_currency` (P1)

- **Columns**: `revenue`
- **Why flagged**: values parse as numbers only once a currency or percent symbol is removed, and the plausible readings give different numbers (e.g. '$67,887.87', '$8,342.54', '$25,176.74'; 1.0 of non-null values would parse after stripping the symbol)
- **Question**: Choose: strip_symbol / divide_by_100 / keep_as_text. This skill ships no automatic op here on purpose: the unit is a fact about the dataset that the file itself does not encode, so any automatic choice would be a guess presented as a result
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never

## 4. Disclosures (already applied, reversible)

Applied automatically. Listed here so the automatic choice is never silent.

### `merge_case_variants`

- **Columns**: `region`
- **Detail**: once the automatic whitespace/quote hygiene has run, 4 label group(s) still differ only by case (8 levels -> 4 after casefold); collapsed automatically because this is a lossless canonicalisation
- **Undo**: Choose: keep_asis (undo the collapse) / merge (default, already applied)

## Reproducing this result

```bash
python clean_traps_dirty.py
```

The regenerated `cleaned.csv` must hash to `b28632ff5d33b58fd3d2f26304e306bdfaec13273bc23c1ff4f01b204c808b5d`.
