# Cleaning Report — measurements.csv

| | |
|---|---|
| Source | `D:\数据处理 skill\examples\repeated_measures\measurements.csv` |
| Rows | 36 → **36** (+0) |
| Columns | 4 → **4** |
| Raw sha256 | `2519c6d2304dc3810a044aa3d4dbc9fe96e92e73a78ae4293fc74680ec621ad7` |
| Cleaned sha256 | `6f62b85a4cf5d53709fdb9ffc95686bda19f7ed7b50f37f733e82dd570680585` |
| Reproducible script | `clean_measurements.py` |
| Ops applied | 9 |
| Decisions pending | 0 |
| Decisions answered via answers file | 0 |

> The raw file is never modified. Everything below is additive.

## 1. Applied operations

| ID | Op | Columns | Severity | Rule source | Rows |
|---|---|---|---|---|---|
| `t-fix-unicode` | `fix_unicode` | `arm`, `response`, `subject`, `visit` | P3 | references/cleaning-rule-catalog.md#tabular:t-fix-unicode | 36→36 |
| `t-strip-ws` | `strip_whitespace` | `arm`, `response`, `subject`, `visit` | P3 | references/cleaning-rule-catalog.md#tabular:t-strip-ws | 36→36 |
| `t-collapse-whitespace` | `collapse_whitespace` | `arm`, `response`, `subject`, `visit` | P3 | references/cleaning-rule-catalog.md#tabular:t-collapse-whitespace | 36→36 |
| `t-trim-quotes` | `trim_paired_quotes` | `arm`, `response`, `subject`, `visit` | P3 | references/cleaning-rule-catalog.md#tabular:t-trim-quotes | 36→36 |
| `t-coerce-numeric` | `coerce_numeric` | `response`, `visit` | P2 | references/cleaning-rule-catalog.md#tabular:t-coerce-numeric | 36→36 |
| `t-normalize-dtypes` | `normalize_dtypes` | `arm`, `response`, `subject`, `visit` | P2 | references/cleaning-rule-catalog.md#tabular:t-normalize-dtypes | 36→36 |
| `t-drop-all-null-cols` | `drop_all_null_cols` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-cols | 36→36 |
| `t-drop-all-null-rows` | `drop_all_null_rows` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-rows | 36→36 |
| `t-rename-clean` | `rename_columns_append_cleaned` | — | P2 | references/cleaning-rule-catalog.md#tabular:t-rename-clean | 36→36 |

## 2. Case-variant canonicalisation

No case-variant folding was needed.

## 3. Decisions requiring a human

None.

## 4. Disclosures (already applied, reversible)

None.

## Reproducing this result

```bash
python clean_measurements.py
```

The regenerated `cleaned.csv` must hash to `6f62b85a4cf5d53709fdb9ffc95686bda19f7ed7b50f37f733e82dd570680585`.
