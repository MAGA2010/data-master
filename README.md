# data-master

**One command. Any data type. A report that shows its work.**

`data-master` is a Codex skill and a standalone Python pipeline for people who
want data analysed without silent type guessing, silent test selection or a
confident report that cannot be reproduced.

Give it a file, folder or glob. It routes each input to a modality, profiles it
without modifying it, cleans and analyses supported tabular data, renders one
figure per argument, and delivers a PDF plus machine-readable evidence.

![Generated iris report](docs/assets/iris-report.png)

[中文说明](#中文) | [Design](docs/DESIGN.md) | [Journal standards](references/journal-reporting-standards.md) | [Workflow contract](references/workflow-contract.md)

## Quick start

```powershell
git clone https://github.com/<owner>/data-master.git
cd data-master
python -m pip install -r requirements.txt

python scripts/run_pipeline.py `
  --in examples/iris/iris_dirty.csv `
  --out examples/iris/outputs `
  --title "Iris morphometrics" `
  --journal nature
```

The runner writes `report.pdf`, `report.md`, `executive_summary.md`, figures,
cleaning artifacts, an audit and `state.json`.

Use it as a Codex skill:

```powershell
Copy-Item -Recurse data-master "$env:USERPROFILE\.codex\skills\data-master"
```

Then ask Codex to clean and analyse a dataset. The root [SKILL.md](SKILL.md) is
the routing entry point.

## What makes it different

Most "AI data analysis" tools fail in the same places. `data-master` treats those
failures as the product requirements:

| Failure | Contract in this repository |
|---|---|
| A reader turns `02134` into `2134` before any audit exists | Every text cell is read as text; conversions are explicit, all-or-nothing plan operations |
| A statistical test is chosen silently | Test selection, rejected alternatives and assumptions are written to `inferential.json` |
| A p-value appears without effect size or uncertainty | Nature gates require effect size plus a 95% CI |
| A report claims more than the design supports | Causal-upgrade phrases fail the audit; unknowns become `AUTHOR_INPUT_NEEDED` |
| The result cannot be reproduced | Cleaning is byte-replayable; every reported number is registered in `report_build.json` |
| A crash means starting over | `state.json` records stage evidence and supports cold resume |

## Execution modes

| Input | What runs |
|---|---|
| One tabular file | Route -> profile -> clean -> validate -> describe -> infer -> charts -> PDF -> 8-gate audit |
| Time series, text, image, audio or geospatial | Route -> profile -> PDF profile report -> integrity audit |
| Mixed folder or multi-file input | One branch per modality/file -> profile-only report |
| Unknown format | Stops with a route record and points to the research protocol |

Profile-only is a deliberate scope boundary, not a claim that statistics ran.
The report says so on its first page.

## Automatic decisions, explicit evidence

For tabular data the runner chooses the highest-ranked grouping column from the
profiler. Override it when the study design says otherwise:

```powershell
python scripts/run_pipeline.py `
  --in data/measurements.csv `
  --out outputs `
  --group treatment `
  --unit-key participant_id `
  --outcomes response_time,accuracy
```

Without `--unit-key`, the output still builds, but Gate 1 remains open and the
report is marked **not submission-ready**. That is intentional. The pipeline
does not invent what one row represents.

## Resume and inspect

Every completed stage records its command, duration, evidence paths and status:

```powershell
python scripts/state_keeper.py --state outputs/state.json --show
python scripts/state_keeper.py --state outputs/state.json --validate
python scripts/run_pipeline.py --resume outputs/state.json
```

A resume is accepted only when the input fingerprint is unchanged. Completed
stages are reused when their evidence still exists; `--force` re-runs them.

## Output

```text
outputs/
|-- report.pdf                  primary deliverable
|-- report.md                   citable Markdown source
|-- executive_summary.md        one page, same numbers
|-- report_build.json           provenance, hashes and PDF backend trail
|-- state.json                  resumable run ledger
|-- route.json                  modality decisions and alternatives
|-- preflight.json              dependency evidence
|-- audit/
|   |-- final_audit.md          8 Nature gates + journal checklist
|   `-- final_audit.json        machine-readable verdict
|-- analysis/
|   |-- profile.json
|   |-- descriptive.json
|   |-- inferential.json
|   `-- chart_decisions.json
|-- cleaning_plan.json
|-- cleaned/
|   |-- cleaned.csv
|   |-- clean_<slug>.py         standalone replay script
|   |-- cleaning_run.json
|   `-- validation.json
|-- charts/*.png
`-- charts_rendered.json
```

## The 8 Nature gates

Any mandatory failure means the report exists but is **not submission-ready**.

| # | Gate | Machine evidence |
|---|---|---|
| 1 | n and independent unit are explicit | `unit_of_analysis`, per-group n |
| 2 | Missingness mechanism declared | `missing_mechanism_screen` |
| 3 | Effect size accompanies p | effect size plus `*_ci95` |
| 4 | Uncertainty is visible | SE, intervals, CI beside prose p-values |
| 5 | Multiple comparisons corrected | declared family and finite adjusted p-values |
| 6 | Sensitivity tested | rank-based cross-check plus Appendix A1 |
| 7 | No association-to-mechanism upgrade | shared forbidden-phrase scan |
| 8 | Unknowns flagged | `AUTHOR_INPUT_NEEDED` plus Appendix B |

Journal routing supports **Nature, NEJM, Science and Lancet**, with EQUATOR
checklists such as CONSORT, STROBE, PRISMA, MOOSE, STARD, ARRIVE, SQUIRE and CARE.

```powershell
python scripts/final_audit.py --outdir outputs --journal nature
python scripts/final_audit.py --outdir outputs --journal nejm --design randomized_trial
python scripts/final_audit.py --outdir outputs --journal lancet --template standard
```

## The 10 sub-skills

The root skill routes. Each sub-skill owns one stage, one artifact set and one
gate.

| # | Sub-skill | Owns |
|---|---|---|
| 1 | [data-router](skills/data-router/SKILL.md) | `route.json` |
| 2 | [data-profiler](skills/data-profiler/SKILL.md) | `profile.json` |
| 3 | [data-cleaner](skills/data-cleaner/SKILL.md) | `cleaning_plan.json`, `cleaned/*` |
| 4 | [data-explorer](skills/data-explorer/SKILL.md) | `descriptive.json` |
| 5 | [data-validator](skills/data-validator/SKILL.md) | `audit/final_audit.*` |
| 6 | [data-transformer](skills/data-transformer/SKILL.md) | `transform_ledger.json` |
| 7 | [statistical-analyzer](skills/statistical-analyzer/SKILL.md) | `inferential.json` |
| 8 | [deep-analyzer](skills/deep-analyzer/SKILL.md) | supervised modelling |
| 9 | [visualizer](skills/visualizer/SKILL.md) | `charts/*.png` |
| 10 | [report-generator](skills/report-generator/SKILL.md) | `report.md`, `report.pdf` |

## Examples

| Example | What it exercises |
|---|---|
| [iris](examples/iris/) | Dirty tabular data, two ANOVA branches, figures, full PDF |
| [column_traps](examples/column_traps/) | Leading zeros, currency, percent, mixed text, date ambiguity |
| [timeseries](examples/timeseries/) | Dropout, retransmission, sampling-regime change |
| [text](examples/text/) | Duplicates, empty files, GB18030 fallback |
| [media](examples/media/) | Corrupt image, re-encoded duplicate, blank frame |
| [geo](examples/geo/) | Out-of-range coordinates, null island, missing coordinate |

## Verification

```powershell
python tests/test_pipeline_invariants.py
```

The suite pins the guarantees that are easy to break silently: leading-zero
preservation, all-or-nothing conversion, untouched-column audit, dtype-manifest
replay, byte-level reproducibility, multiplicity with non-finite safeguards,
Welch denominator degrees of freedom, forbidden-phrase consistency, state
transitions and a complete iris PDF build.

GitHub Actions runs the suite on Windows and Linux across Python 3.11, 3.12 and
3.13, plus the modality profilers.

## Scope

Implemented: tabular full pipeline; time-series, text, image, audio and
geospatial profiling; PDF delivery through `reportlab -> headless browser ->
fpdf2 -> BLOCKED`; journal and EQUATOR routing; resumable state.

Not implemented in v1: leave-one-group-out sensitivity automation, mixed-effects
model selection, document/video format conversion, and inferential analysis for
non-tabular modalities. The reports mark these as gaps rather than passing checks.

## License

MIT. See [LICENSE](LICENSE).

## 中文

**data-master** 是一个通用数据处理 skill：输入文件、目录或 glob，自动判断数据模态，
执行可审计的画像、清理、统计、图表和 PDF 报告流程。

一条命令开始：

```powershell
python -m pip install -r requirements.txt
python scripts/run_pipeline.py --in data.csv --out outputs --title "分析报告"
```

核心承诺：

- 原始文件永不修改，清理前后字节级可复现；
- 类型只决定一次，后续通过 manifest 重放；
- 分组和方法选择有证据，无法判断的内容写 `AUTHOR_INPUT_NEEDED`；
- 表格数据交付完整统计 PDF；其他模态交付明确的 profile-only PDF，不冒充推断分析；
- 每个阶段写入 `state.json`，输入未变时可冷恢复；
- 报告存在不等于可提交，Nature 8 道 gate 会给出明确 verdict。
