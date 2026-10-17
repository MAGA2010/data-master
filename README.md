# data-master

**Auditable data analysis from one command.**

[![CI](https://github.com/MAGA2010/data-master/actions/workflows/ci.yml/badge.svg)](https://github.com/MAGA2010/data-master/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-2EA44F)](LICENSE)
[![Codex Skill](https://img.shields.io/badge/Codex-skill-111827)](SKILL.md)

`data-master` is a Codex skill and standalone Python pipeline for transforming
raw data into a reproducible report with a complete evidence trail. It identifies
the input modality, profiles the data without modifying it, plans and executes
safe cleaning, runs statistics where the data supports them, creates figures,
and delivers Markdown and PDF reports.

It is built for workflows where an answer must survive inspection: research
analysis, data quality review, exploratory reporting, and AI-assisted work that
still needs transparent decisions.

![Generated data-master report](docs/assets/iris-report.png)

## Why data-master

Most automated analysis tools optimize for the shortest path to a polished answer.
`data-master` optimizes for an answer that can be traced, repeated, and challenged.

| Common failure | data-master control |
|---|---|
| A reader silently changes `02134` to `2134` | All text cells are read as text; conversions are explicit plan operations |
| Cleaning changes columns nobody approved | Every changed value must belong to a named operation; untouched columns are audited |
| A statistical test is selected without explanation | Tests, assumptions, alternatives, effect sizes, and confidence intervals are recorded |
| A report overstates the study design | A shared phrase audit blocks unsupported causal upgrades |
| Outputs cannot be reproduced | Cleaning replay is checked byte-for-byte; inputs are fingerprinted |
| A failed run starts from zero | `state.json` records stage status, commands, duration, and evidence for resume |
| Non-tabular data receives invented inference | Unsupported modalities receive an explicitly labelled profile-only report |

The project does not replace statistical judgment or peer review. It makes the
judgment that was actually applied visible, testable, and easier to correct.

## Installation

### Requirements

- Python 3.11, 3.12, or 3.13
- Git
- A platform supported by the Python scientific stack

```bash
git clone https://github.com/MAGA2010/data-master.git
cd data-master
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The pipeline never installs packages silently. It records a dependency preflight
and stops with the missing requirements when a selected stage cannot run.

### Use as a Codex skill

Clone the repository:

```bash
git clone https://github.com/MAGA2010/data-master.git
```

Then copy or link it into your Codex skills directory. On PowerShell:

```powershell
Copy-Item -Recurse data-master "$env:USERPROFILE\.codex\skills\data-master"
```

On macOS or Linux:

```bash
cp -R data-master ~/.codex/skills/data-master
```

The root [SKILL.md](SKILL.md) is the Codex routing entry point. It coordinates
the ten stage-specific skills under [`skills/`](skills/).

## Quick start

Run the included Iris example:

```bash
python scripts/run_pipeline.py \
  --in examples/iris/iris_dirty.csv \
  --out examples/iris/outputs \
  --title "Iris morphometrics" \
  --journal nature
```

The command produces a complete report, figures, cleaning artifacts, statistics,
an audit, and a resumable state ledger.

For a smaller and more explicit analysis:

```bash
python scripts/run_pipeline.py \
  --in data/measurements.csv \
  --out outputs \
  --title "Treatment response" \
  --group treatment \
  --unit-key participant_id \
  --outcomes response_time,accuracy \
  --journal nature
```

`--unit-key` is not decorative. Without a valid declaration of what one
independent unit represents, the report is deliberately marked
`NOT SUBMISSION-READY`.

## Execution modes

The runner selects a mode from the route result and records that decision.

| Input shape | What runs |
|---|---|
| One tabular file | Route, profile, clean, validate, describe, infer, chart, report, audit |
| One text, image, audio, geospatial, or time-series input | Route, profile, profile-only PDF, integrity audit |
| Mixed folder or multiple files | One profile branch per modality or file, followed by a merged profile-only report |
| Unknown format | Stops with a route record and points to the research protocol |

Profile-only is an explicit scope boundary. It reports structure, integrity
issues, missingness, duplicates, and modality-specific findings without claiming
that a statistical model or causal analysis was performed.

## Command-line reference

| Option | Purpose |
|---|---|
| `--in PATH` | File, directory, or glob input |
| `--out DIR` | Output directory |
| `--title TEXT` | Report title |
| `--group COLUMN` | Override automatic grouping selection |
| `--outcomes A,B` | Restrict inferential outcomes |
| `--unit TEXT` | Describe what one row represents |
| `--unit-key COLUMN` | Declare the independent-unit identifier |
| `--journal auto|nature|nejm|science|lancet` | Journal checklist family |
| `--design ID` | EQUATOR study-design identifier |
| `--modality NAME` | Force a routing modality |
| `--profile-only` | Stop after profiling and report generation |
| `--pdf-backend auto|reportlab|fpdf2|headless-browser` | Select the PDF backend |
| `--resume STATE` | Resume an existing `state.json` |
| `--force` | Re-run stages instead of reusing completed evidence |

View the built-in help:

```bash
python scripts/run_pipeline.py --help
```

## Pipeline architecture

```text
input file / folder / glob
        |
        v
  route -> preflight -> profile
        |                  |
        |                  +---- non-tabular / mixed ----> profile report -> audit
        |
        +---- one tabular file
                 |
                 v
             cleaning plan
                 |
                 v
      execute -> validate -> describe
                 |
                 v
           inferential analysis
                 |
                 v
        chart decisions -> charts
                 |
                 v
          report.md / report.pdf
                 |
                 v
           structural + 8-gate audit
```

Every stage writes evidence to disk before it is considered complete. The runner
uses that evidence, rather than console output or an in-memory flag, to decide
whether a stage can be reused.

### Core components

| Component | Responsibility |
|---|---|
| [`scripts/run_pipeline.py`](scripts/run_pipeline.py) | One-command orchestration and execution mode selection |
| [`scripts/route_input.py`](scripts/route_input.py) | File inspection and modality routing |
| [`scripts/profile_*.py`](scripts/) | Modality-specific structural profiling |
| [`scripts/cleaning_plan.py`](scripts/cleaning_plan.py) | Explicit, reviewable cleaning plan |
| [`scripts/execute_cleaning.py`](scripts/execute_cleaning.py) | Additive cleaning with a replayable script |
| [`scripts/stats_*.py`](scripts/) | Descriptive and inferential statistics |
| [`scripts/final_audit.py`](scripts/final_audit.py) | Machine-derived report and journal audit |
| [`scripts/pipeline_state.py`](scripts/pipeline_state.py) | Input fingerprints and stage ledger |
| [`scripts/state_keeper.py`](scripts/state_keeper.py) | State inspection, evidence validation, and resume entry point |

## Supported inputs

| Modality | Formats and examples | Current depth |
|---|---|---|
| Tabular | CSV, TSV, Excel, JSON, JSONL, Parquet | Full analysis pipeline |
| Time series | Timestamped tabular data | Structural profiling |
| Text corpus | TXT and mixed-encoding document sets | Corpus profiling |
| Image set | PNG, JPEG, WebP, TIFF | Decode, metadata, brightness, near-duplicate profiling |
| Audio set | WAV, MP3, FLAC and related formats | Duration, rate, channel, clipping, and silence profiling |
| Geospatial | GeoJSON, shapefiles, coordinate tables | CRS, bounds, coordinate validity, coincidence profiling |
| Mixed input | Folders containing several supported modalities | Branch profiling and combined profile-only report |

Unknown and unsupported formats are routed to
[`references/research-protocol.md`](references/research-protocol.md) rather than
being treated as tabular data by default.

## Output contract

```text
outputs/
|-- report.pdf
|-- report.md
|-- executive_summary.md
|-- report_build.json
|-- state.json
|-- route.json
|-- preflight.json
|-- cleaning_plan.json
|-- charts_rendered.json
|-- audit/
|   |-- final_audit.json
|   `-- final_audit.md
|-- analysis/
|   |-- profile.json
|   |-- descriptive.json
|   |-- inferential.json
|   `-- chart_decisions.json
|-- cleaned/
|   |-- cleaned.csv
|   |-- clean_<dataset>.py
|   |-- cleaning_run.json
|   `-- validation.json
`-- charts/
    `-- *.png
```

The important files are:

- `report.pdf`: the primary human-readable deliverable.
- `report.md`: the citable report source.
- `report_build.json`: hashes, provenance, PDF backend, and registered report values.
- `analysis/*.json`: machine-readable statistical and chart decisions.
- `audit/final_audit.*`: the final audit verdict and actionable failures.
- `state.json`: completed stages, commands, durations, and evidence paths.

## Reproducibility and data safety

The pipeline applies four non-negotiable data-integrity rules.

1. **Raw input is never modified.** Outputs are additive and generated under the
   selected output directory.
2. **Types are explicit.** Text cells remain text until a recorded operation
   proves that every value can be converted. Conversions are all-or-nothing.
3. **Only approved columns may change.** The cleaned output is compared against
   the raw input in text space, and an unexpected value change fails validation.
4. **Types are decided once.** A dtype manifest is saved and replayed by every
   downstream stage instead of being guessed again.

Cleaning also produces a standalone replay script. Re-running that script on the
raw input must reproduce the cleaned output hash exactly.

## Resume and inspection

Inspect a run:

```bash
python scripts/state_keeper.py --state outputs/state.json --show
```

Validate every recorded evidence path:

```bash
python scripts/state_keeper.py --state outputs/state.json --validate
```

Resume an interrupted run:

```bash
python scripts/run_pipeline.py --resume outputs/state.json
```

Completed stages are reused only when their evidence still exists and the input
fingerprint is unchanged. Use `--force` when the intent is to rebuild artifacts.

## Report audit

The default audit is journal-oriented and derives results from saved artifacts,
not from the report's own claims.

| Gate | Requirement |
|---|---|
| 1 | Sample size and independent unit are explicit |
| 2 | Missingness mechanism is declared |
| 3 | Effect size accompanies p-values |
| 4 | Uncertainty is visible |
| 5 | Multiple comparisons are corrected |
| 6 | Sensitivity analysis is reported |
| 7 | Association is not upgraded to mechanism |
| 8 | Unknowns are marked `AUTHOR_INPUT_NEEDED` |

Journal profiles include Nature, NEJM, Science, and Lancet. Design routing covers
common EQUATOR checklists such as CONSORT, STROBE, PRISMA, MOOSE, STARD, ARRIVE,
SQUIRE, and CARE.

Run the audit independently:

```bash
python scripts/final_audit.py --outdir outputs --journal nature
python scripts/final_audit.py --outdir outputs --journal nejm --design randomized_trial
python scripts/final_audit.py --outdir outputs --journal lancet --template standard
```

A report can exist while the audit says `NOT SUBMISSION-READY`. This is an
intentional outcome, not a missing output. The audit identifies what still needs
to be resolved.

## Examples

| Example | Demonstrates |
|---|---|
| [`examples/iris`](examples/iris/) | Full tabular analysis, automatic grouping, effect sizes, figures, and PDF |
| [`examples/column_traps`](examples/column_traps/) | Leading zeros, currency, percentages, mixed values, and date ambiguity |
| [`examples/timeseries`](examples/timeseries/) | Sampling gaps, duplicate timestamps, and regime change |
| [`examples/text`](examples/text/) | Duplicate and empty documents, plus legacy encoding fallback |
| [`examples/media`](examples/media/) | Corrupt images, re-encoded near-duplicates, and blank frames |
| [`examples/geo`](examples/geo/) | Invalid coordinates, null island, and missing geometry |

Run any supported example through the one-command interface:

```bash
python scripts/run_pipeline.py \
  --in examples/timeseries/sensor_log.csv \
  --out outputs/timeseries \
  --title "Sensor stability review"
```

## Development

Run the invariant and regression suite:

```bash
python tests/test_pipeline_invariants.py
```

Check syntax:

```bash
python -m compileall scripts tests
```

The suite covers type preservation, all-or-nothing conversions, untouched-column
auditing, dtype replay, byte-reproducible cleaning, multiplicity safeguards,
Welch denominator degrees of freedom, causal-language consistency, routing,
profile-only scope, state transitions, and end-to-end report generation.

GitHub Actions runs the project on Windows and Linux with Python 3.11, 3.12, and
3.13, including the one-command tabular and profile-only paths.

## Project structure

```text
.
|-- SKILL.md                  Codex entry point and routing contract
|-- scripts/                  Deterministic pipeline implementation
|-- skills/                   Ten stage-specific Codex skills
|-- references/               Methodological and reporting references
|-- examples/                 Reproducible demonstration datasets
|-- tests/                    Invariant and end-to-end tests
|-- docs/                     Architecture notes and README assets
|-- requirements.txt          Runtime dependencies
|-- CONTRIBUTING.md           Contribution workflow
|-- SECURITY.md               Security and disclosure policy
`-- LICENSE                   MIT
```

## Scope and limitations

Current limitations are explicit:

- Full inferential analysis currently applies to a single tabular file.
- Non-tabular and mixed inputs produce profile-only reports.
- Leave-one-group-out sensitivity automation is not complete.
- Mixed-effects model selection is not automated.
- PDF, DOCX, HTML, and video conversion are outside the v1 scope.
- The audit supports reporting discipline; it does not validate scientific truth.

These boundaries are part of the output contract. Unsupported analysis is marked
as unsupported instead of being silently replaced with a weaker claim.

## Contributing

Contributions are welcome when they preserve the evidence contract. Start with
[`CONTRIBUTING.md`](CONTRIBUTING.md), add regression coverage for behavior
changes, and keep generated user data out of commits.

For security and data-disclosure concerns, follow [`SECURITY.md`](SECURITY.md).

## Citation

If you use `data-master` in research or technical work, cite the repository and
the exact commit used for the analysis:

```text
Wang, S. data-master: Auditable data analysis from one command.
https://github.com/MAGA2010/data-master
```

## License

Released under the [MIT License](LICENSE).

## 中文简介

`data-master` 是一个可审计的数据分析 Skill 与 Python 流水线。输入文件、目录或
glob 后，它会自动判断数据模态、完成画像与安全清理、运行适用的统计分析、生成图表，
并输出 Markdown、PDF、审计结果和完整证据链。

```bash
python scripts/run_pipeline.py \
  --in data.csv \
  --out outputs \
  --title "数据分析报告"
```

核心原则：

- 永不修改原始文件；
- 类型转换显式、可逆、全量可解析才执行；
- 统计方法和清理操作均记录证据；
- 无法确定的单位或设计问题标记为 `AUTHOR_INPUT_NEEDED`；
- 非表格与混合输入只交付明确标注的 profile-only 报告；
- 报告存在不等于可提交，必须通过机器可核验的审计门禁。
