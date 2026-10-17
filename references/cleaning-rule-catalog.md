# Cleaning Rule Catalog

Every cleaning operation lives here as an entry with: `id`, `op`, `applies_to`, `auto_default`, `severity`, `rule_source`, `alternatives`. The agent reads this file to build `cleaning_plan.json`; it never invents cleaning ops.

> Inspired by yogaibhh/claude-clean-data-skill `references/tabular-rules.md` and Votee-AI/magic-data-cleaning. Re-implemented from scratch to keep the catalog compact and add Nature-grade provenance.

## Severity scale

```
P0  dangerous / data-loss risk             -> never-automatic
P1  changes sample size / distribution     -> never-automatic (opt-in only)
P2  changes encoding / scale, preserves evidence -> may run with explicit opt-in
P3  cosmetic only                          -> always OK
```

## Tabular (CSV / TSV / Excel / JSON / Parquet)

| id | op | applies_to | auto_default | severity | rationale |
|---|---|---|---|---|---|
| `t-norm-types` | Low-cardinality string col -> `category` (a storage choice only) | string cols | YES | P2 | shrinks memory; values are unchanged, so the untouched-column audit still applies |
| `t-strip-ws` | Strip leading/trailing whitespace on string cols | string cols | YES | P3 | common encoding bug |
| `t-lowercase` | Rewrite a string col to lower case, discarding the original spelling | string cols | NO (flag only) | P2 | **destroys information**: "Nord" and "nord" may be one region or two |
| `t-merge-case-variants` | Collapse levels that differ only by case onto one canonical spelling | string cols with case-only diffs | YES, as an INFO disclosure | P2 | **lossless**: the full merge map is written to `cleaning_run.json`, so any level can be restored |
| `t-dedupe-exact` | Drop exact-duplicate rows | all rows | YES | P1 | commonly wanted; flagged if > 1% |
| `t-dedupe-key` | Drop duplicates by a chosen key column | user-specified key | NO (opt-in) | P1 | can merge distinct rows |
| `t-drop-all-null-cols` | Drop cols with 100% null | cols | YES | P1 | no signal |
| `t-drop-all-null-rows` | Drop rows with 100% null | rows | YES | P1 | no signal |
| `t-drop-high-null-rows` | Drop rows with > 95% null (configurable) | rows | NO (opt-in) | P1 | preserves only extreme cases |
| `t-coerce-dates` | Convert to datetime **only if every non-null value parses** | string cols | YES, else HELD | P2 | gates time-series detection; see Hold classes below |
| `t-coerce-numeric` | Convert to numeric **only if every non-null value parses** | string cols | YES, else HELD | P2 | enables numeric stats; see Hold classes below |
| `t-coerce-bool` | Map {yes/no/true/false/0/1} -> bool | string cols with bool vocab | NO (opt-in) | P2 | irreversible |
| `t-flag-outliers-z` | Add `outlier_z_<col>` boolean col (|z| > 3) | numeric cols | NO (opt-in) | P2 | non-destructive flagging |
| `t-winsorize` | Clip values to [q_lo, q_hi] | numeric cols | NO (opt-in) | P1 | modifies data |
| `t-impute-mean` | Fill NaN with column mean | numeric cols with NaN | NO (opt-in) | P1 | injects signal |
| `t-impute-median` | Fill NaN with column median | numeric cols with NaN | NO (opt-in) | P1 | robust default |
| `t-impute-mode` | Fill NaN with column mode | categorical cols with NaN | NO (opt-in) | P1 | may create new majority |
| `t-impute-knn` | KNN imputation (k = 5) | numeric cols | NO (opt-in) | P1 | better than mean but expensive |
| `t-impute-mice` | MICE multiple imputation (m = 5) | numeric cols, n >= 50 | NO (opt-in) | P1 | best practice but slow |
| `t-onehot` | One-hot encode low-cardinality cats | cardinality <= 10 | NO (opt-in) | P2 | irreversible |
| `t-label-encode` | Label-encode category as int code | categorical cols | NO (opt-in) | P2 | risk of false ordering |
| `t-normalize-zscore` | Standardize (z-score) | numeric cols | NO (opt-in) | P2 | needed for some models |
| `t-normalize-minmax` | Min-max scale to [0,1] | numeric cols | NO (opt-in) | P2 | needed for some models |
| `t-rename-clean` | Append `_cleaned` to changed names; preserve original | affected cols | YES (when modified) | P2 | traceability |
| `t-collapse-whitespace` | Replace runs of whitespace with single space | string cols | YES | P3 | display fix |
| `t-fix-unicode` | Unicode normalize (NFC) + fix mojibake | string cols | YES | P3 | display fix |
| `t-trim-quotes` | Strip paired " or " around strings | string cols | YES | P3 | parsing artifact |
| `t-comma-decimal` | Detect "." vs "," decimals (by locale heuristic) | numeric-lookalike | NO (opt-in) | P2 | locale-dependent |

## Conversion is all-or-nothing, and everything else is a hold

`t-coerce-numeric` and `t-coerce-dates` are not "best effort". A conversion runs
only when **every** non-null value parses. There is no parse-rate threshold, and
that is deliberate: a threshold does not make the decision safer, it only chooses
how much to destroy quietly. At 90% numeric, a 70% threshold passes a column that
contains ten percent words; the conversion then turns those words into NaN, and
from that point on a category the study recorded ("unknown") is indistinguishable
from a value nobody ever collected. Lowering the threshold to 99% does not fix
this. It moves the threshold.

Four situations hold the conversion and hand the choice to a person. Each is
recorded in `never_automatic_flags` with the evidence behind it, and each has a
real decision path rather than a dead end.

| hold | evidence shown to the user | the choice |
|---|---|---|
| `leading_zero` | e.g. `02134`, and the share of values carrying one | the zero is padding, or part of the identifier? |
| `currency_or_rate` | e.g. `$1,200`, `12%` | strip the symbol, divide by 100, or keep as text — three different numbers |
| `numeric_or_date` | a 6-8 digit integer such as `20240115` | an integer that is also a date; the file does not say which was meant |
| `mixed_with_text` | e.g. 5 of 158 values are `--` | "not recorded" is a claim about the study, not a formatting fact |

Decision paths: `--force-coerce-numeric COLS` / `--force-coerce-dates COLS`
(recorded as `user_opt_in`), or leave the column as text.

## Reading is not type inference

Every stage reads through one function, and for CSV / TSV / Excel that function
reads **every cell as a string** (`dm_types.read_table`, `read_mode="text"`).
Types are then decided by an op in the plan, which means they are disclosed,
reviewed and reversible.

This is not caution about a rare edge case. `pd.read_csv` turns the postcode
`02134` into `2134`, which then collides with the genuinely different postcode
`2134`. The inference happens *before any audit exists*, so the leading zero and
the evidence that a decision was made are both gone before the profiler can
report them, and neither is recoverable from the output. This actually shipped:
the profiler read text while the cleaning stage re-read with pandas defaults and
silently destroyed the column. `tests/test_pipeline_invariants.py` now pins it,
including a negative control that fails on purpose.

JSON and Parquet are exempt — their schemas state the types, so there is nothing
to guess. `--read-mode infer` remains available as an explicit escape hatch.

Downstream stages do not guess either. `cleaning_run.json` records a
`dtype_manifest`, and `dm_types.load_cleaned` re-applies it instead of inferring
again, so an identifier cannot quietly become an integer in the analysis after
the report said it was text. When no manifest is found, the read is labelled as
a guess in the output rather than presented as fact.

## Time-series

| id | op | applies_to | auto_default | severity |
|---|---|---|---|---|
| `ts-parse-dt` | Parse timestamp column | datetime cols | YES (best-effort) | P2 |
| `ts-detect-freq` | Infer frequency (`pd.infer_freq`) | datetime cols | YES (info only) | P3 |
| `ts-resample` | Resample to inferred / user freq | datetime index | NO (opt-in) | P1 |
| `ts-fill-forward` | Forward-fill NaN within series | numeric cols | NO (opt-in) | P2 |
| `ts-fill-interp` | Linear interpolation across small gaps (<= 3) | numeric cols | YES (when gap small) | P2 |
| `ts-detect-outlier` | Flag outliers by z > 3 | numeric cols | YES (info only) | P3 |
| `ts-detect-seasonality` | Run seasonal decompose (period hint) | numeric cols | YES (info only) | P3 |
| `ts-detect-stationarity` | ADF + KPSS tests | numeric cols | YES (info only) | P3 |
| `ts-detect-changepoint` | PELT changepoint detection | numeric cols | YES (info only) | P3 |
| `ts-forecast` | Naive / seasonal-naive / ARIMA baseline forecast | numeric cols | NO (opt-in) | P2 |

## Text-corpus

| id | op | applies_to | auto_default | severity |
|---|---|---|---|---|
| `txt-detect-lang` | langdetect on each doc / first 10k chars | text rows | YES | P3 |
| `txt-detect-encoding` | chardet on raw bytes | file | YES | P3 |
| `txt-norm-unicode` | Unicode NFC | text cols | YES | P3 |
| `txt-strip-ws` | Strip whitespace + collapse internal whitespace | text cols | YES | P3 |
| `txt-dedupe-near` | Drop near-duplicates (MinHash sim > 0.9) | text rows | NO (opt-in) | P1 |
| `txt-tokenize` | Tokenize via simple whitespace + regex | text cols | YES | P3 |
| `txt-stats` | Per-row: char count, token count, type-token ratio, top tokens | text cols | YES | P3 |
| `txt-redact-pii` | Regex-based PII masking (email, phone, ID) | text cols | NO (opt-in) | P0 |

## Image-set

| id | op | applies_to | auto_default | severity |
|---|---|---|---|---|
| `img-corrupt-check` | PIL.Image.open verifies + np.std > 0 | files | YES | P1 (drop unreadable) |
| `img-dedup-hash` | SHA256 dedupe | files | YES | P1 |
| `img-dedup-phash` | Perceptual hash dedupe (pHash) | files | NO (opt-in) | P1 |
| `img-stats` | Width, height, channels, aspect ratio, file size | files | YES | P3 |
| `img-exif` | Extract EXIF + GPS + camera info | files | YES | P3 (info only) |

## Audio-set

| id | op | applies_to | auto_default | severity |
|---|---|---|---|---|
| `aud-decode-check` | soundfile.info reads + duration > 0 | files | YES | P1 (drop unreadable) |
| `aud-stats` | Duration, channels, sample rate, bit depth | files | YES | P3 |
| `aud-silence` | Compute silence ratio (RMS < threshold) | files | YES (info only) | P3 |
| `aud-clipping` | Detect clipping (samples at max) | files | YES (info only) | P3 |
| `aud-dedup` | SHA256 dedupe | files | YES | P1 |

## Geospatial (GeoTIFF / GeoJSON)

| id | op | applies_to | auto_default | severity |
|---|---|---|---|---|
| `geo-crs-check` | Read CRS (rasterio / fiona) | files | YES | P3 |
| `geo-bbox` | Read bounding box | files | YES | P3 |
| `geo-overlap` | Pairwise bbox overlap | files | YES (info only) | P3 |
| `geo-valid` | Geometry validity (GeoJSON) | files | YES (info only) | P3 |

## Document (PDF / DOCX / MD / HTML)

Routes to text-corpus after extraction. PDF: pdfplumber. DOCX: python-docx. MD: markdown. HTML: beautifulsoup4.

## Plan construction rules

1. **Always include the safe set** (`t-norm-types`, `t-strip-ws`, `t-collapse-whitespace`, `t-fix-unicode`, `t-trim-quotes`, `t-coerce-dates` best-effort, `t-coerce-numeric` best-effort, `t-dedupe-exact`, `t-drop-all-null-cols`, `t-drop-all-null-rows`).
2. **Never include an op with severity P1 or P0 unless the user opted in** (`--impute`, `--remove-outliers`, `--dedupe-key`, `--publish`, etc.).
3. **Every op must cite its `rule_source`** = this file path + section + id.
4. **Plan must be reproducible**: same input + same flags + same plan file → identical cleaned output. Determinism is a hard requirement.

## Rule provenance in plan

```json
{
  "ops": [
    {
      "id": "t-strip-ws",
      "op": "strip_whitespace",
      "columns": ["name", "city"],
      "rule_source": "references/cleaning-rule-catalog.md#tabular:t-strip-ws",
      "auto": true,
      "severity": "P3",
      "rejected_alternatives": []
    },
    {
      "id": "t-impute-mean",
      "op": "impute_mean",
      "columns": ["age"],
      "rule_source": "references/cleaning-rule-catalog.md#tabular:t-impute-mean",
      "auto": false,
      "severity": "P1",
      "user_decision": "AUTHOR_INPUT_NEEDED",
      "default_if_silent": "leave_as_nan",
      "rejected_alternatives": [
        {"op": "impute_median", "reason": "median may over-smooth for skewed age"},
        {"op": "impute_mice", "reason": "n too small (n=42) for MICE"}
      ]
    }
  ]
}
```

## v1 coverage

- Tabular: full
- Time-series: full
- Text-corpus: full
- Image-set: profiler + basic cleaning
- Audio-set: profiler + basic cleaning
- Geospatial: profiler only
- Document: routes to text-corpus
