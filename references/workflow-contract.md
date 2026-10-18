# Workflow Contract — per-step rules

The agent follows this contract step by step. Each step lists: goal, inputs, outputs, scripts to call, and the gate that must pass before moving on.

## Step 0 — Interpreter & dependencies

Goal: pick a working Python and install only the libs we need.

```bash
python -V                       # record to outputs/env.txt
python scripts/check_deps.py --modalities <comma-list> --json
```

For each missing package: tell the user the install command from the JSON, then run it. Never silent-install. Never use `pip install -r requirements.txt` blindly.

Fallback: if a lib cannot be installed (e.g. binary wheel fails), record `SKIPPED (lib unavailable: X)` in the report and proceed without it.

## Step 1 — Input resolution

Goal: turn `$ARGUMENTS` into a concrete file list.

- Empty → list data-looking files in cwd; ask the user. This is the only allowed clarification.
- Single file → dataset = that file; `dataset_dir = parent`.
- Folder → enumerate supported extensions, skip any `outputs/` or `cleaned/` already present.
- Glob → expand and group by modality.
- `--out <dir>` → overrides `dataset_dir/outputs`.

Output: a manifest saved to `outputs/manifest.json`:

```json
{
  "files": [{"path": "data/sales.csv", "size_bytes": 12345, "extension": ".csv", "modified": "2026-09-20T10:00:00"}],
  "modality_groups": {"tabular": ["data/sales.csv"], "image-set": ["data/photo1.jpg"]},
  "dataset_dir": "data",
  "outputs_dir": "data/outputs",
  "template": "nature",
  "user_overrides": ["--impute median"]
}
```

Gate: at least one supported file present, else `AUTHOR_INPUT_NEEDED`.

## Step 2 — Route modality

Goal: pick one of 7 modalities per file.

Use the sniffers in [`modality-routing.md`](modality-routing.md). Write the decision to `analysis/routing_decisions.json`.

Gate: every file in manifest has a modality. Anything not classifiable falls to `research-track` (Step 2b).

## Step 2b — Research track (only when triggered)

Read [`research-protocol.md`](research-protocol.md). Use WebSearch to find a known library or spec for the format; document the source in `analysis/research_track.json`. Build an ad-hoc profiler; document it.

Gate: research-track decisions cite a public source.

## Step 3 — Check dependencies

Already done in Step 0; this is the re-check after routing.

## Step 4 — Profile

Run `scripts/profile_<modality>.py` per file or per group.

```bash
python scripts/profile_tabular.py --in data/sales.csv --out outputs/analysis/profile.json
```

Output: `analysis/profile.json` (per modality) and `analysis/profile_combined.json` (for mixed).

**The profiler reads as text.** For CSV / TSV / Excel every cell arrives as a string via
`dm_types.read_table(..., read_mode="text")`; the profiler then *probes* what each column
could become and records the evidence, but it does not decide. Type is decided in Step 5
and applied in Step 6. Reading is not type inference — `pd.read_csv` would turn the postcode
`02134` into `2134` and merge it with the real postcode `2134`, before any audit exists.
JSON and Parquet are exempt: their schemas state the types.

Gate: every column has `dtype`, `n_missing`, `n_unique` recorded, plus the `coercion`
block (`auto_numeric` / `auto_date` / `hold` + the numeric and date probes) for every
string column. Else fail. The probe block is what Step 5 reads; a profile without it
forces Step 5 to guess.

## Step 5 — Plan cleaning

Run `scripts/cleaning_plan.py` reading:

- `references/cleaning-rule-catalog.md`
- `references/never-automatic-list.md`
- `analysis/profile.json`
- `--impute`, `--remove-outliers`, `--dedupe-key`, etc. from user flags

```bash
python scripts/cleaning_plan.py --profile outputs/analysis/profile.json \
    --out outputs/cleaning_plan.json
```

Output: `outputs/cleaning_plan.json` (schema `1.2`) with `auto_actions`,
`never_automatic_flags`, `read_mode`, and per-action provenance
(`rule_source` / `alternative_considered` / `rejected_reason`).

**Conversion is all-or-nothing.** `coerce_numeric` / `coerce_dates` appear in
`auto_actions` only when *every* non-null value parses. There is no parse-rate
threshold to tune. Everything else is a hold — one of four classes, each carrying the
evidence that triggered it and a real decision path rather than a dead end:

| hold | example | the decision that is owed to a human |
|---|---|---|
| `leading_zero` | `02134` | is the zero padding, or part of the identifier? |
| `currency_or_rate` | `$1,200`, `12%` | strip / divide by 100 / keep as text — three different numbers |
| `numeric_or_date` | `20240115` | an integer that is also a date; the file does not say which was meant |
| `mixed_with_text` | 5 of 158 values are `--` | "not recorded" is a claim about the study, not a formatting fact |

Resolve a hold by re-running with `--force-coerce-numeric COLS` / `--force-coerce-dates COLS`
(recorded as `user_opt_in`), or leave the column as text.

Gate: plan is reproducible (same input + same flags → same plan). Every column the
profiler held appears in `never_automatic_flags` with evidence, and no held column also
appears in an auto action.

## Step 6 — Execute cleaning

Run `scripts/execute_cleaning.py --plan cleaning_plan.json --in <raw> --out cleaned/`.

The executor reads the raw file through `dm_types.read_table(..., read_mode=<plan.read_mode>)`
— **not** `pd.read_csv`. The plan is the authority on how the file is read, which is why
`read_mode` is a plan field rather than an executor constant: a stage that re-reads with
pandas defaults silently undoes every type decision the plan made.

The script writes a `clean_<slug>.py` that reproduces the cleaning deterministically, then
re-runs it and compares SHA-256 against the file it just wrote.

Output:
- `cleaned/cleaned_<modality>.csv` (or parquet)
- `cleaned/clean_<slug>.py` (reproducible)
- `cleaned/cleaning_report.md`

**The untouched-column audit runs here**, at the moment values could still change:
`audit_untouched_columns(raw, cleaned, touched)` replays the whitespace hygiene operations
exactly and compares every column no action named, byte for byte. It is written to
`cleaning_run.json` under `untouched_column_audit`.

Gate:
- Byte-level reproducible — the regenerated script reproduces `cleaned.csv` with the same SHA-256.
- All `auto_actions` applied; all `never_automatic_flags` left untouched and reported.
- `untouched_column_audit.passed` is true.

The safe default here is that an *unrecognised* operation is treated as value-changing and
held to account: `VALUE_CHANGING_OPS` enumerates the exemptions, and anything not on that
list must justify itself in the audit.

## Step 7 — Validate cleaning

Run `scripts/validate_clean.py --raw <raw> --clean <cleaned>`. Compares the cleaned data
against the **recorded** `dtype_manifest` in `cleaning_run.json` and against the raw bytes.

Six checks, all of which must pass (`validation.json`, `verdict: PASS`):

| check | severity | what it catches |
|---|---|---|
| `row_loss` | P1 | row loss beyond `--max-row-loss` (default 30%) |
| `target_preserved` | P0 | a lost label / outcome column |
| `dtype_stable` | P0 | a column that became numeric **without** plan authorisation |
| `no_nan_inflation` | P0 | NaN appearing where the raw had none |
| `no_all_null_col` | P1 | an all-null column that should have been dropped |
| `columns_retained` | P3 | a dropped or renamed column the plan did not name |

`dtype_stable` judges the cleaned data against the **recorded `dtype_manifest`**, not against
pandas' guess of the raw file, because guessing is the very act that destroys data — an
earlier version compared against the guess and reported `int64 → category` as "numeric became
non-numeric", failing a run that had in fact preserved everything.

If any gate fails, freeze the run to `audit/` with the actionable fix. `report.md` becomes
`report.PENDING.md`.

## Step 8 — Transform (optional)

Only run when the user opts in (e.g. `--onehot`, `--normalize`).

`scripts/transform.py --clean <cleaned> --flags <opts>`.

Gate: idempotent.

## Step 9 — Stats

Run descriptive always:

```bash
python scripts/stats_descriptive.py --clean <cleaned> --modality <m> --out analysis/stats_descriptive.json
```

Run inferential when:

- At least 1 categorical column (group) AND
- At least 1 numeric column (outcome) AND
- n >= 5 per group.

```bash
python scripts/stats_inferential.py --clean <cleaned> --modality <m> --out analysis/stats_inferential.json
```

Run effect size for every comparison.

Run missing-data analyzer and sensitivity.

Output: `analysis/stats.json` (combined) + separate JSON per sub-step.

Gate:
- Every comparison has n, test, df, effect size, CI, raw p, corrected p.
- Every column has descriptive stats (mean, median, sd, q25, q75, min, max, missing).
- Missing > 5% classified by mechanism.
- Sensitivity table present.

## Step 10 — Charts

Run `scripts/chart_decision.py` to produce `analysis/chart_decisions.json` (uses chart-decision-catalog).

Run `scripts/render_chart.py` per decision to produce PNGs in `outputs/charts/`.

Gate:
- 1 chart per argument task (no duplicates).
- 2D preferred; 3D only when it changes ranking (and paired with 2D fallback).
- Every bar / line / scatter has uncertainty marks.
- Color-blind safe palette.

## Step 11 — Report

Run `scripts/assemble_report.py --template <nature|standard|executive>`.

Gate:
- All required sections present.
- At least 1 caveat in Caveats and limitations.
- Every `p =` and `mean ±` has CI in same sentence.
- No forbidden phrasing (regex check).
- All charts embedded with title-caption-body triplet.

## Step 12 — Audit

Run `scripts/final_audit.py` against the report + all artifacts.

Output: `audit/final_audit.md` and `audit/final_audit.json`. Each gate =
PASS / WARN / FAIL with evidence.

Final verdict:
- All PASS / WARN only → `report.md` becomes the deliverable.
- Any FAIL on gates 1, 2, 7, 8 -> the report remains available, but the verdict
  is `NOT SUBMISSION-READY`; `audit/final_audit.md` carries the actionable list.

## Step 13 — State snapshot

`scripts/run_pipeline.py` writes `state.json` after every stage. Inspect it with:

```powershell
python scripts/state_keeper.py --state outputs/state.json --show
python scripts/state_keeper.py --state outputs/state.json --validate
```

State schema:

```json
{
  "schema_version": "1.0",
  "status": "completed",
  "input": {"kind": "file", "path": "...", "sha256": "...", "files": 1},
  "outdir": "...",
  "options": {"title": "...", "group": null, "journal": "nature"},
  "stage_order": ["input", "route", "profile", "..."],
  "stages": {
    "profile": {
      "status": "completed",
      "evidence": [".../analysis/profile.json"],
      "command": ["python", "scripts/profile_tabular.py", "..."],
      "duration_ms": 812
    }
  },
  "audit_verdict": "NOT SUBMISSION-READY"
}
```

To cold-resume:

```powershell
python scripts/run_pipeline.py --resume outputs/state.json
# or, from the output directory:
python ../../scripts/state_keeper.py --resume
```

The runner reads the stage ledger, verifies the input fingerprint and starts at
the first stage whose evidence is missing or incomplete.

## Cold-resume semantics

A re-run must:

- Reuse a stage only when its SHA-256 evidence and execution context match.
- Re-execute a changed or missing artifact's producing stage and all downstream stages.
- Invalidate derived stages after code, dependency versions, or run options change.
- Rebuild legacy state without artifact hashes rather than silently trusting it.
- Refuse to resume when the input fingerprint changed.
- Re-run the audit when the user passes `--force` or when audit evidence is absent.

Read-only verification: `python scripts/verify_artifacts.py --outdir outputs --json`.
The state ledger is the trust anchor; these hashes detect changed files, not
malicious rewriting of both files and ledger, and do not certify scientific validity.

## Determinism

- Set `PYTHONHASHSEED=0` in `outputs/env.txt`.
- All random ops use seed `42` by default.
- Profile + cleaning + stats + chart decisions are deterministic functions of (input, flags).
