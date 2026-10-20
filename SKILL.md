---
name: data-master
description: "Analyze datasets with preserved raw inputs, explicit cleaning decisions, reproducible figures and PDF reports. Full statistics for one tabular file; descriptive time-series analysis; integrity profiling for text, image, audio, geographic and mixed inputs. Use for data cleaning, EDA, group comparisons, statistical reports, 跑数据 or 数据分析 with a traceable evidence trail."
allowed-tools: Bash(python *), Bash(py *), PowerShell(python *), PowerShell(py *), WebSearch, WebFetch
---

# data-master — universal data processing pipeline

Turn **any data** into a **cleaned, audited, Nature-grade report + charts** with one command. The agent reads the data, decides modality, picks methods, runs the pipeline, and writes evidence-backed outputs. The user never has to choose a statistical test or a chart type.

## Contract

Installed CLI: `data-master analyze <file> --out <dir>`; use
`data-master doctor --json` to diagnose the environment and
`data-master verify <dir> --json` to check saved artifact hashes.
`data-master demo --out <new-dir>` runs a synthetic example, and
`data-master skill install` installs this skill atomically from the npm or
Python distribution. Existing
`python scripts/run_pipeline.py` commands below remain supported; installing
the CLI alone does not register the skill until `skill install` is run.

- **Input**: `$ARGUMENTS` = a file, a folder, or a glob. Optional flags:
  - `--report nature` (default) | `standard` | `executive` — report template.
  - `--out <dir>` — overrides the output root.
  - `--answers <file>` — answers `answers.template.json` decisions by id; every id and action is validated, and changing the file invalidates the stale cleaning stages on resume. The file may also carry a `run` block declaring `unit_key` / `group` / `outcomes` / `design` / `journal` / `covariates` (validated against the profile; explicit CLI values always win). A decision may name a single `column` of a multi-column flag.
  - `--covariates <a,b>` — declare numeric covariates; the adjusted (ANCOVA) comparison becomes primary, unadjusted stays as cross-check, and the homogeneity-of-slopes assumption is tested and reported.
  - `--max-input-mb <n>` — override the 300 MB in-memory input gate (readers hold files whole, as text).
  - `--export-lockfile` — writes `lockfile.txt` with the exact dependency versions that ran.
- **Output** (all under `<dataset_dir>\outputs\`):
  - `cleaned/` — cleaned data + `cleaning_plan.json` + `cleaning_report.md` + reproducible `clean_*.py`
  - `analysis/` — `profile.json`, `stats.json`, `validation_report.md`, `chart_decisions.json`, `sensitivity.json`
  - `charts/` — `*.png` figures
  - `report.md` — main report (the citable source text)
  - `report.html` — self-contained shareable export of report.md (figures embedded; verification hashes it)
  - `report.pdf` — **primary deliverable**; rendered by a three-tier cascade
  - `executive_summary.md` — 1-page TL;DR
  - `report_build.json` — provenance for every number + PDF backend trail + self-audit + pipeline commit
  - `audit/final_audit.md` — 8-gate + journal-checklist verdict
  - `charts_rendered.json` — per-figure ink ratio and blank-page check
  - `answers.template.json` — the never-automatic decisions this dataset raised, fillable and fed back with `--answers`
  - `lockfile.txt` — (with `--export-lockfile`) exact dependency versions that ran
- **Invariant — additive only**: NEVER modify, move, or delete any raw input file. Re-runs may overwrite `outputs/`.
- **Full-auto with gates**: never block on a method choice; always pick the most defensible default and document. ONLY ask the user when the input itself is ambiguous.
- **Method provenance**: every AI judgment records `rule_source` + `alternative_considered` + `rejected_reason`. Every number cites the script that produced it.

## Data integrity contract

These four rules are what make the output worth trusting. They are not
precautions; each one exists because the alternative has already produced a
plausible-looking report about data that was no longer there.

**1. The reader never guesses a type.** CSV / TSV / Excel are read with every
cell as a string (`dm_types.read_table`, `read_mode="text"`). `pd.read_csv`
turns the postcode `02134` into `2134`, which then collides with the genuinely
different postcode `2134` — and it does so *before any audit exists*, so the
leading zero and the evidence that a decision was made are both unrecoverable.
Types are instead decided by an op in the plan, where they are disclosed and
reversible. JSON and Parquet are exempt: their schemas state the types.
`--read-mode infer` is an explicit escape hatch.

**2. A conversion runs only if every value parses.** No parse-rate threshold
exists in this skill, by design. A threshold does not make the decision safer; it
only chooses how much to destroy quietly. Four situations hold the conversion and
ask instead — `leading_zero`, `currency_or_rate`, `numeric_or_date`,
`mixed_with_text` — each with the evidence attached. See
[references/cleaning-rule-catalog.md](references/cleaning-rule-catalog.md).

**3. A value may only change in a column an operation named.** After cleaning,
`execute_cleaning.py` compares the raw file against the output in text space and
fails the run if any untouched column gained a value. The blanket hygiene ops are
replayed exactly, so the check is not vacuous. This is what catches a reader
reinterpreting the file behind the plan's back.

**4. Types are decided once and re-applied, never re-guessed.** The run records
a `dtype_manifest`; `dm_types.load_cleaned` applies it. An identifier cannot
quietly become an integer in the analysis after the report said it was text. With
no manifest, the read is labelled as a guess rather than presented as fact.

Every cleaning run is also checked for **byte-for-byte reproducibility**: the
generated standalone script re-reads the raw file and must reproduce the output
hash exactly.

## Three-stage pipeline

```
[Stage 1: Detect & Clean]              [Stage 2: Analyze (Nature)]              [Stage 3: Deliver]
--------------------------              ----------------------------              ---------------------
data-router            (modality)        data-explorer            (EDA)           visualizer            (charts)
  |                                     |                                          |
data-profiler          (profile)        data-validator           (gates)         report-generator      (report)
  |                                     |
data-cleaner           (clean)          data-transformer         (transform)
                                        |
                                        statistical-analyzer    (stats)
                                        |
                                        deep-analyzer           (model — optional)
```

Every stage has a **gate**. A gate fails when evidence is missing, the data is too dirty, or a Nature requirement is unmet. A failed gate freezes the run to `audit/` with an actionable message; the user can fix the input and re-run.

### The 10 sub-skills

The router in this file owns the run; each sub-skill owns one stage, one artifact set and
one gate. Load only the stage you are executing, plus the reference it names.

| # | Sub-skill | Stage | Owns | Gate |
|---|---|---|---|---|
| 1 | [data-router](skills/data-router/SKILL.md) | 1a | modality + `route.json` | every input has a modality |
| 2 | [data-profiler](skills/data-profiler/SKILL.md) | 1b | `profile.json` | every column typed, every rejected group explained |
| 3 | [data-cleaner](skills/data-cleaner/SKILL.md) | 1c | `cleaning_plan.json` + `cleaned/*` | reproducibility + untouched-column audit |
| 4 | [data-explorer](skills/data-explorer/SKILL.md) | 2a | `descriptive.json` | mean *and* median, missingness screened |
| 5 | [data-validator](skills/data-validator/SKILL.md) | 3c | `audit/final_audit.*` | 8 Nature gates + journal checklist |
| 6 | [data-transformer](skills/data-transformer/SKILL.md) | 2b | `transform_ledger.json` | every derived column reversible and recorded |
| 7 | [statistical-analyzer](skills/statistical-analyzer/SKILL.md) | 2c | `inferential.json` | effect size + CI, family corrected, no NaN p, primary at the unit level the structure supports |
| 8 | [deep-analyzer](skills/deep-analyzer/SKILL.md) | 2d | `model.json` | every coefficient has a CI and a diagnostic |
| 9 | [visualizer](skills/visualizer/SKILL.md) | 3a | `chart_decisions.json` + `charts/*.png` | one argument per figure, blank-page check |
| 10 | [report-generator](skills/report-generator/SKILL.md) | 3b | `report.md` + `report.pdf` | every number traced, no forbidden phrasing |

Stages 2a-2d may run **in parallel** across modalities; they all read the same cleaned
artifact and write disjoint JSON. Stage 3 is sequential: figures before report, report
before audit.

## Routing

The table states what ACTUALLY runs today. Non-tabular modalities take the
profile-only branch: routing, profiling, a profile-only PDF and an integrity
audit — no inferential claim. Do not improvise the unimplemented stages; a
reference file that does not exist is a stop, not a suggestion.

| File pattern | Modality | Stage 1 rule | Stage 2 stack (as implemented) |
|---|---|---|---|
| `*.csv *.tsv *.xlsx *.json *.jsonl *.parquet` | tabular | `references/cleaning-rule-catalog.md#tabular` | profiler → stats (unit-aware) → sensitivity → charts |
| `*.txt` (free text, no delimiter) | text-corpus | `references/cleaning-rule-catalog.md#text` | profiler (duplicates / empty / encoding) — **profile-only** |
| timestamped tabular / `*.csv` with date column | time-series | `references/cleaning-rule-catalog.md#timeseries` | profiler (gaps / duplicate stamps / regime change / ADF screen) → **audited descriptive statistics**: Mann-Kendall trend + Theil-Sen slope with CI, ACF/PACF with white-noise bounds, STL strengths, seeded CUSUM changepoint screen (`analysis/timeseries.json`). Descriptive scope: NO forecast, NO ARIMA, NO causal claim |
| `*.jpg *.png *.webp` | image-set | `references/cleaning-rule-catalog.md#image` | profiler (corrupt / near-duplicate / blank) — **profile-only** |
| `*.wav *.mp3 *.flac` | audio-set | `references/cleaning-rule-catalog.md#audio` | profiler (duration / clipping / silence) — **profile-only** |
| `*.tif` with geo tag | geospatial | `references/cleaning-rule-catalog.md#geo` | profiler (CRS / bounds / null island / coincidence) — **profile-only** |
| anything else / no extension | research-track | `references/research-protocol.md` | ad-hoc via WebSearch / WebFetch |

Full table in [references/modality-routing.md](references/modality-routing.md).

## Workflow (agent-side)

The agent executing this skill should follow this loop. Each step has full instructions in the linked reference.

0. **Prefer the one-command runner** (`scripts/run_pipeline.py`). It wraps every
   deterministic stage, records `state.json`, auto-selects the highest-ranked
   grouping column for a single tabular file, and resumes without repeating
   stages whose evidence still exists:
   ```powershell
   python scripts/run_pipeline.py --in <file|folder|glob> --out outputs --title "<title>"
   python scripts/run_pipeline.py --resume outputs/state.json
   ```
   Use the step-by-step commands below only when debugging or overriding a stage.
   Non-tabular and multi-file inputs take the documented profile-only path: they
   receive a PDF report and integrity audit, but no inferential claim.
1. **Resolve input** (`references/workflow-contract.md#step-1`). If $ARGUMENTS is empty, list data-looking files in cwd and ask the user which to process. This is the only allowed clarification.
2. **Route modality** (`references/modality-routing.md`). Read file extensions, sniff a small sample, pick one of the 7 modalities. Mixed folder → run one branch per modality and merge reports.
3. **Check dependencies** (`scripts/check_deps.py --modalities <list>`). Install missing libs one at a time, never silent-install.
4. **Profile** (`scripts/profile_<modality>.py`). Produce `profile.json`. Always do this; it grounds every later decision.
5. **Plan cleaning** (`scripts/cleaning_plan.py`). Read `references/cleaning-rule-catalog.md` and `references/never-automatic-list.md`. Produce `cleaning_plan.json`. Any never-automatic item becomes a USER_INPUT_NEEDED flag — and `answers.template.json` is written beside the plan so the user can answer every flag by id and re-run with `--answers <file>`. Every answer is validated against the flag it names and recorded with who/when/why.
6. **Execute cleaning** (`scripts/execute_cleaning.py`). Run only the safe subset automatically. Write `clean_<slug>.py` so the user can re-run. Write `cleaning_report.md`.
7. **Validate** (`scripts/validate_clean.py`). Gate: row loss < 30% (else fail), no NaN inflation, target/label cardinality preserved, no column dropped without a plan entry, and every dtype matches the recorded manifest. Note what `dtype_stable` compares: the cleaned types against **what the run decided and recorded**, not against what pandas guessed about the raw file. Comparing against the guess condemns the run for refusing to repeat the guess.
8. **Re-derive, do not re-read.** Every analysis stage opens the cleaned data through `dm_types.load_cleaned`, which applies the manifest. Never call `read_csv` on a cleaned file directly — that is the same type-guessing mistake one stage earlier.
9. **Stats** (`scripts/stats_descriptive.py` + `scripts/stats_inferential.py` + `scripts/effect_size.py`). Always run descriptive; run inferential only when the data has a comparison structure. When `--unit-key` shows rows repeating within units, the inferential stage classifies the structure (clustered / paired / complete blocks / incomplete repeated) and runs the primary analysis at the level the structure supports — per-unit means, paired tests, Friedman, or a unit random-intercept mixed model fitted by maximum likelihood with convergence checks; failed fits remain unresolved. Declared `--covariates` make the ANCOVA comparison primary with the slopes assumption tested. Cite every p-value with test name, n, df, CI, effect size.
9b. **Time-series inputs** take their own mode: after profiling, `scripts/timeseries_analysis.py` computes Mann-Kendall + Theil-Sen slope with CI, ACF/PACF with white-noise bounds, STL strengths, and a seeded CUSUM changepoint screen into `analysis/timeseries.json`, rendered into the report with an overview figure and a phrase-scanned audit. Descriptive scope only.
10. **Sensitivity** (`scripts/sensitivity_analysis.py`). Perturb the primary analysis — leave-one-group-out, block jackknife, pre-specified extreme-value fence, strict complete cases, imputation sensitivity — and write `analysis/sensitivity.json`. Gate 6 reads this artifact; the rank cross-check alone no longer satisfies it.
11. **Charts** (`scripts/chart_decision.py` + `scripts/render_chart.py`). 1 chart per argument task. 2D preferred; 3D only when it changes the ranking. Title = conclusion, caption = definition, body = fact → interpretation → implication. Scatter panels carry a bootstrap band on the smoother and a CI on r.
12. **Report** (`scripts/assemble_report.py`). Builds `report.md`, `executive_summary.md`,
    `report_build.json`, then renders `report.pdf` through reportlab -> fpdf2 ->
    headless browser -> BLOCKED. The backend that actually ran is recorded, never assumed:
    ```powershell
    python scripts/assemble_report.py --raw <raw.csv> --outdir outputs --title "<title>"
    ```
13. **Audit** (`scripts/final_audit.py`). Re-derives all 8 gates from the artifacts (it
    does not trust the prose), routes the run to its EQUATOR checklist and journal family,
    and writes `audit/final_audit.md`. Exit 1 means the report exists but is not
    submission-ready:
    ```powershell
    python scripts/final_audit.py --outdir outputs --journal nature
    python scripts/final_audit.py --outdir outputs --journal nejm --design randomized_trial
    ```
14. **State** (`scripts/state_keeper.py`). Inspect or validate `state.json`; resume
    with either `state_keeper.py --resume` or `run_pipeline.py --resume <state>`. Saved artifacts are checked by SHA-256; altered evidence, code, dependencies, or options invalidate dependent stages. Verify without rebuilding using `python scripts/verify_artifacts.py --outdir outputs --json`. Legacy state without hashes is rebuilt.
    `--export-lockfile` writes `lockfile.txt` pinning the exact versions that ran.

Agent meta-rules:
- If a step is missing a reference, stop and read the linked file — do NOT improvise on methods.
- If a Python script fails with ImportError, fall back per workflow-contract step 0 (use py -3.12).
- If the user explicitly asks for a non-default method (e.g. Welch t-test), record the override in `cleaning_plan.json` and proceed.

## Nature-grade standards (default)

Drawn from `nature-statistics` and applied as a gate, not decoration:

1. **n is explicit and unit-defined.** Independent experimental unit ≠ technical replicate ≠ repeated measure. Always distinguished — and when rows repeat within the declared unit, the primary analysis runs at the level the structure supports (unit means / paired / blocks), with the row-level results demoted to a labelled secondary.
2. **Missingness assumptions are explicit.** The mechanism stays undetermined without collection context; missing fractions never establish MCAR. Any imputation is labelled.
3. **Effect size > p-value.** Cohen d / Cliff delta / odds ratio + 95% CI always reported.
4. **Uncertainty is visible.** Every number has a CI / SE / IQR; every chart has error bars, a band, or a stated smoother interval.
5. **Multiple comparisons corrected.** Bonferroni / BH / Holm as appropriate.
6. **Sensitivity tested — for real.** `scripts/sensitivity_analysis.py` re-runs the primary question on perturbed data (leave-one-group-out, block jackknife, extreme-value fence, strict complete cases, imputation sensitivity) and writes `analysis/sensitivity.json`; Appendix A1 reports every conflict. The rank cross-check alone is assumption robustness, not sensitivity, and no longer passes this gate.
7. **No upgrade from association to mechanism.** Claims stay bounded to evidence.
8. **Unknowns are flagged AUTHOR_INPUT_NEEDED.** Never invented sample sizes, p-values, or methods.

For `standard` or `executive` templates, gates 3-6 are relaxed but 1, 2, 7, 8 remain.

## Default-FAIL contract (from my-mathmodel-agent)

Every gate starts `passes: false`. A gate flips to `true` only when its acceptance criterion has machine-checkable evidence: a saved JSON, a passing script exit, a rendered figure with its source script. A claim is not evidence.

## File map

```
data-master/
|-- SKILL.md                            # this file
|-- docs/DESIGN.md                      # architectural design
|-- references/
|   |-- modality-routing.md             # full routing table + sample sniffers
|   |-- cleaning-rule-catalog.md        # rule catalog per modality
|   |-- never-automatic-list.md         # ops that always require human decision
|   |-- nature-statistics-checklist.md  # 8 Nature-grade gates
|   |-- journal-reporting-standards.md  # NEJM / Science / Lancet / Nature routing
|   |-- journal-reporting-standards.json# machine-readable routing table
|   |-- chart-decision-catalog.md       # 25 chart types + 8 complexity principles
|   |-- report-template-catalog.md      # 3 report templates
|   |-- workflow-contract.md            # per-step agent contract
|   `-- research-protocol.md            # how to handle unknown modalities
|-- skills/                             # 10 sub-skills, one stage each
|-- scripts/                            # deterministic Python tools
|   |-- assemble_report.py              # markdown + PDF cascade + provenance
|   |-- sensitivity_analysis.py         # LOGO / jackknife / fence / complete-case perturbations
|   |-- final_audit.py                  # 8 gates + journal checklist
|   `-- profile_tabular.py ...          # profiler, cleaner, stats, charts
|-- examples/iris/                      # end-to-end iris example
|-- docs/assets/                        # README screenshots
`-- .github/workflows/ci.yml            # cross-platform regression CI
```

## Related files

| Topic | File | Load when |
|---|---|---|
| Modality routing + sniffers | references/modality-routing.md | Step 2 — picking the modality |
| Cleaning rule catalog | references/cleaning-rule-catalog.md | Step 5 — building cleaning plan |
| Never-automatic operations | references/never-automatic-list.md | Step 5 — flagging ops for human |
| Nature checklist | references/nature-statistics-checklist.md | Step 7 + 12 — validation + audit |
| Journal standards (NEJM / Science / Lancet / Nature) | references/journal-reporting-standards.md | Step 12 — choosing the EQUATOR checklist |
| Chart decision catalog | references/chart-decision-catalog.md | Step 10 — picking the figure |
| Report templates | references/report-template-catalog.md | Step 11 — assembling the report |
| Workflow contract | references/workflow-contract.md | always — the per-step rules |
| Research protocol | references/research-protocol.md | Step 2 — unknown modality |
| Design document | docs/DESIGN.md | when user wants the why |

## Source hierarchy

1. User-supplied data + their override request (highest priority).
2. Nature Portfolio reporting standards + CONSORT / STROBE / PRISMA / ARRIVE when relevant.
3. This skill's reference files (built from nature-statistics, himcm-chart-system, data-storytelling, my-mathmodel-agent, clean-data, magic-data).
4. Industry tools (ydata-profiling / great-expectations / deepchecks) as inspiration, not blind adoption.
5. Conservative statistical reporting practice.

If the supplied material is insufficient for a defensible decision, leave the field as AUTHOR_INPUT_NEEDED rather than guessing.

## Red lines

- Never modify, move, or delete the user's raw data files.
- Never invent p-values, sample sizes, effect sizes, CIs, or test names.
- Never call a comparison "significant" without n, test, df, p, effect size, and CI.
- Never silently drop rows, impute, merge, deduplicate across datasets, or publish.
- Never let Nature standards silently decay to "standard" without telling the user.
- Never start writing the report before every gate has machine-checkable proof.
