# Never-Automatic Operations

These operations are **NEVER** performed without explicit user confirmation. The agent records each one in `cleaning_plan.json` under `never_automatic_flags` and surfaces them in the cleaning report.

## Why this list exists

Data cleaning is high-stakes. A silently dropped row, an imputed value, or a cross-dataset merge can destroy downstream conclusions. Inspired by:

- `yogaibhh/claude-clean-data-skill` "never automatic" section
- `great-expectations` action-level severities
- `nature-statistics` `AUTHOR_INPUT_NEEDED` discipline

## The list

### Always-never (no override)

| Op | Risk | What we do instead |
|---|---|---|
| **Delete original input files** | Data loss | Refuse. All outputs go to `outputs/` |
| **Rename user columns** | Breaks downstream joins | Append `_cleaned`; original kept in profile |
| **Replace NaN with 0 / mean / median silently** | Injects false signal | Profile + flag; offer as opt-in in cleaning_plan |
| **Drop rows silently** | Hides sample-size changes | Only drop when rule = `auto_drop_high_null_rows` AND null% > 95 (configurable) |
| **Remove duplicates silently** | May merge distinct observations (different timestamps) | Only dedupe on exact (subset, value) tuples the user picked |
| **Merge with another dataset** | Cardinality explosion + silent joins | Profile-only; require user `--join <other>` |
| **Publish / upload data** | Privacy + distribution | Disabled unless `--publish` + confirmation |
| **Change data types silently** (e.g. string → int) | Loses category info | Convert only when every non-null value parses; otherwise hold with the evidence |
| **Rewrite a column's spelling** (e.g. lower-case) | Destroys "Nord" vs "nord" | Merge case-only variants onto one canonical level, record the full map, keep it reversible |
| **Guess a column type at read time** | `02134` → `2134`, colliding with a real `2134` | Read text, decide types in a disclosed op; JSON/Parquet exempt (their schemas declare types) |
| **Resolve entity names** (e.g. "NYC" / "New York" / "NY") | Domain knowledge | Flag as `ENTITY_RESOLUTION_NEEDED` |
| **Treat timezone-naive as UTC** | Off-by-hours errors | Always flag with `AUTHOR_INPUT_NEEDED` |

### Two rules that look alike and are not

`t-lowercase` and `t-merge-case-variants` both respond to the same evidence —
levels that differ only by case. They are opposites, and the difference is
entirely whether the original can be recovered.

| | `t-lowercase` | `t-merge-case-variants` |
|---|---|---|
| What it does | rewrites the column, discarding original spelling | maps every variant onto one canonical level |
| In `case_variant_merge_map`? | no — the original is gone | yes, in full, in `cleaning_run.json` |
| Default | never | automatic, INFO disclosure |

The merge is judged on the post-hygiene view, and the raw count is quoted
alongside it. A column can hold many raw levels that collapse to far fewer once
the automatic whitespace and quote hygiene runs; measuring on the raw values and
then reporting the post-hygiene number would misdescribe what happened.

### Conversions that change a value are held, not guessed

Four hold classes block a conversion that would otherwise run automatically. Each
appears in `never_automatic_flags` with the evidence and the options:

| hold | why it is held |
|---|---|
| `leading_zero` | `02134` → `2134` merges two different identifiers |
| `currency_or_rate` | `$1,200`, `12%` — strip / divide / keep are three different numbers |
| `numeric_or_date` | `20240115` is both an integer and a date |
| `mixed_with_text` | partial parses become NaN, so a recorded category is lost |

There is no parse-rate threshold anywhere in this skill. See
`cleaning-rule-catalog.md` for why lowering it does not help.

### Conditional-never (rule may apply with explicit opt-in)

| Op | Default | Opt-in trigger |
|---|---|---|
| Imputation (mean / median / mode / KNN / MICE) | profile-only | `--impute mean` etc. in user request |
| Outlier removal (z > 3 / IQR * 1.5 / isolation-forest) | profile-only | `--remove-outliers zscore` |
| Outlier capping (winsorize) | profile-only | `--winsorize 0.05` |
| Normalization / Standardization | profile-only | `--normalize` |
| One-hot encoding | profile-only | `--onehot` |
| Train/test split | profile-only | `--split 0.8` |
| Sample row reduction (down-sample) | profile-only | `--downsample 10000` |
| Date parsing assumptions | detect but not auto-fix | `--parse-dates strict` |
| Currency conversion | flag | `--fx-rate <rate>` |

## How it is recorded

In `cleaning_plan.json`:

```json
{
  "auto_actions": [
    {"op": "strip_whitespace", "columns": ["name"], "rule_source": "..."}
  ],
  "never_automatic_flags": [
    {
      "op": "impute_median",
      "column": "age",
      "reason": "8.2% missing, mechanism unclear (MAR vs MNAR)",
      "ask_user": "Choose: drop / mean / median / mode / KNN / MICE / leave-as-NaN",
      "default_if_silent": "leave_as_nan"
    }
  ]
}
```

In `cleaning_report.md` a dedicated `## Human Decisions Needed` section lists each flag with the options. The user re-runs the skill with their picks (e.g. `--impute median`); the cleaner then performs only the now-opted-in actions.

## Severity ladder (for the audit)

```
P0  — would silently destroy evidence (data loss, wrong types, false imputation)
P1  — would change sample size or distribution without notice (drop, dedupe, outlier remove)
P2  — would change encoding or scale but preserve evidence (normalize, onehot, cast)
P3  — presentation-level only (chart font, color)
```

Only P3 may proceed without a flag. P2 may proceed if the user has explicitly named the op. P1 and P0 are always never-automatic.

## What "the agent picks" the default to

When the user does NOT answer, the cleaner uses the **least-invasive** choice that still produces a usable dataset:

- Missing values → leave as NaN + flag
- Outliers → flag only + add `outlier_score` column
- Type inference → preserve string; offer category only when cardinality < 50
- Dedupe → only on exact full-row match, never partial
- Date parsing → try `pd.to_datetime(errors="coerce")`; if > 5% NaT, escalate to user

These defaults are themselves a rule entry and the rule_source is this file.
