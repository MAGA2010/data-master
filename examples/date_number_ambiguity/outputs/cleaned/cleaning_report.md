# Cleaning Report — session_export.csv

| | |
|---|---|
| Source | `D:\数据处理 skill\examples\date_number_ambiguity\session_export.csv` |
| Rows | 48 → **48** (+0) |
| Columns | 3 → **3** |
| Raw sha256 | `62619a7e5b45c756238f3bdfc280fd7d97b4666352a6e11c7bcc0a5b01cc07fe` |
| Cleaned sha256 | `45480b1e8fbbdd691cb92ee6d335f63cd664a6791f9f578481b114ce8ae9dff6` |
| Reproducible script | `clean_session_export.py` |
| Ops applied | 9 |
| Decisions pending | 1 |
| Decisions answered via answers file | 0 |

> The raw file is never modified. Everything below is additive.

## 1. Applied operations

| ID | Op | Columns | Severity | Rule source | Rows |
|---|---|---|---|---|---|
| `t-fix-unicode` | `fix_unicode` | `latency_s`, `session_stamp`, `subject_id` | P3 | references/cleaning-rule-catalog.md#tabular:t-fix-unicode | 48→48 |
| `t-strip-ws` | `strip_whitespace` | `latency_s`, `session_stamp`, `subject_id` | P3 | references/cleaning-rule-catalog.md#tabular:t-strip-ws | 48→48 |
| `t-collapse-whitespace` | `collapse_whitespace` | `latency_s`, `session_stamp`, `subject_id` | P3 | references/cleaning-rule-catalog.md#tabular:t-collapse-whitespace | 48→48 |
| `t-trim-quotes` | `trim_paired_quotes` | `latency_s`, `session_stamp`, `subject_id` | P3 | references/cleaning-rule-catalog.md#tabular:t-trim-quotes | 48→48 |
| `t-coerce-numeric` | `coerce_numeric` | `latency_s` | P2 | references/cleaning-rule-catalog.md#tabular:t-coerce-numeric | 48→48 |
| `t-normalize-dtypes` | `normalize_dtypes` | `latency_s`, `session_stamp`, `subject_id` | P2 | references/cleaning-rule-catalog.md#tabular:t-normalize-dtypes | 48→48 |
| `t-drop-all-null-cols` | `drop_all_null_cols` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-cols | 48→48 |
| `t-drop-all-null-rows` | `drop_all_null_rows` | — | P1 | references/cleaning-rule-catalog.md#tabular:t-drop-all-null-rows | 48→48 |
| `t-rename-clean` | `rename_columns_append_cleaned` | — | P2 | references/cleaning-rule-catalog.md#tabular:t-rename-clean | 48→48 |

## 2. Case-variant canonicalisation

No case-variant folding was needed.

## 3. Decisions requiring a human

These were **not** applied. Each one changes the analysis and needs an explicit choice.

### `coerce_numeric_or_date` (P1)

- **Columns**: `session_stamp`
- **Why flagged**: every value parses both as an integer and as a date (e.g. '20240115'), and the file does not record which one was meant. Reading a study's dates as integers is the kind of error that survives every later check
- **Question**: Choose: keep_as_text (default) / integers --force-coerce-numeric session_stamp / dates --force-coerce-dates session_stamp
- **If you say nothing**: `keep_as_text`
- **Rule**: references/never-automatic-list.md#conditional-never
- **Answer with**: fill `answers.template.json` (id `coerce_numeric_or_date@session_stamp`) and re-run with `--answers`

## 4. Disclosures (already applied, reversible)

None.

## Reproducing this result

```bash
python clean_session_export.py
```

The regenerated `cleaned.csv` must hash to `45480b1e8fbbdd691cb92ee6d335f63cd664a6791f9f578481b114ce8ae9dff6`.
