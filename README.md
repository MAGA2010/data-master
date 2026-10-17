# data-master

**A data processing skill that decides how to analyse your data, then proves it.**

Drop in a file, a folder, or a glob. The agent routes it to a modality, profiles it
without changing it, cleans it under an auditable plan, runs the statistics the
data actually supports, renders one figure per argument, and delivers a
**PDF report** with a Markdown source and machine-readable provenance.

[中文说明](#中文) | [Design](docs/DESIGN.md) | [Journal standards](references/journal-reporting-standards.md) | [Workflow contract](references/workflow-contract.md)

---

## Why this exists

Most "AI data analysis" tools fail in the same three places:

1. **They guess the data.** `pd.read_csv` turns the postcode `02134` into `2134`,
   merges it with a genuinely different `2134`, and the evidence that any decision
   was made is gone before the first chart.
2. **They pick a test silently.** A Welch ANOVA and a Kruskal-Wallis test can
   disagree. Reporting only the one that ran hides the choice, and the choice is
   part of the result.
3. **They write a confident report.** "Highly significant", a mean with no
   interval, a p-value with no effect size, a causal verb on an observational
   design.

`data-master` is built backwards from those failures. Every stage has a gate that
starts **failed** and must be flipped by evidence: a saved JSON, a passing script
exit, a rendered figure with its source. A claim is not evidence.

## What you get

```
outputs/
├── report.pdf                  ← the primary deliverable
├── report.md                   ← the citable source text
├── executive_summary.md        ← one page, same numbers
├── report_build.json           ← provenance for every number + PDF backend trail
├── audit/final_audit.md        ← 8 Nature gates + your journal's checklist
├── charts/*.png                ← 200 dpi, colour-blind safe, ink-ratio checked
├── charts_rendered.json
├── cleaning_plan.json
├── cleaned/
│   ├── cleaned.csv
│   ├── clean_<slug>.py         ← standalone, re-runnable
│   ├── cleaning_run.json
│   └── validation.json
└── analysis/
    ├── profile.json
    ├── descriptive.json
    ├── inferential.json
    └── chart_decisions.json
```

## Quick start

```powershell
# 0. dependencies (nothing is installed silently)
python scripts/check_deps.py --modalities tabular

# 1. route every input to one modality
python scripts/route_input.py --in data/ --deep --out outputs/route.json

# 2. profile without changing anything
python scripts/profile_tabular.py --in data.csv --out outputs/analysis/profile.json

# 3. plan, then execute — the plan is the gate
python scripts/cleaning_plan.py --profile outputs/analysis/profile.json --out outputs/cleaning_plan.json
python scripts/execute_cleaning.py --in data.csv --plan outputs/cleaning_plan.json --out outputs/cleaned
python scripts/validate_clean.py --raw data.csv --clean outputs/cleaned/cleaned.csv --profile outputs/analysis/profile.json --out outputs/cleaned/validation.json

# 4. describe, then infer
python scripts/stats_descriptive.py --clean outputs/cleaned/cleaned.csv --out outputs/analysis/descriptive.json
python scripts/stats_inferential.py --clean outputs/cleaned/cleaned.csv --group <column> --out outputs/analysis/inferential.json

# 5. decide figures, then render them
python scripts/chart_decision.py --clean outputs/cleaned/cleaned.csv --profile outputs/analysis/profile.json --descriptive outputs/analysis/descriptive.json --inferential outputs/analysis/inferential.json --out outputs/analysis/chart_decisions.json
python scripts/render_chart.py --clean outputs/cleaned/cleaned.csv --decisions outputs/analysis/chart_decisions.json --outdir outputs/charts

# 6. assemble the PDF, then audit it
python scripts/assemble_report.py --raw data.csv --outdir outputs --title "Study title"
python scripts/final_audit.py --outdir outputs --journal nature
```

`assemble_report.py` renders the PDF through a cascade and records which tier ran:
**reportlab → fpdf2 → headless browser → BLOCKED**. A blocked PDF still leaves a
complete `report.md`; it does not pretend to have succeeded.

## Supported modalities (v1)

| Modality | Profiler | Status |
|---|---|---|
| tabular (CSV/TSV/Excel/JSON/Parquet) | `profile_tabular.py` | full pipeline: clean → stats → charts → report |
| time-series | `profile_timeseries.py` | profile: interval, gaps, regime change, trend/ADF screen |
| text corpus | `profile_text.py` | profile: length, duplicates, encoding, vocabulary, script mix |
| image set | `profile_media.py --kind image` | profile: decode, EXIF, brightness, aHash near-duplicates |
| audio set | `profile_media.py --kind audio` | profile: duration, rate, channels, clipping, silence |
| geospatial | `profile_geospatial.py` | profile: CRS, bounds, invalid coordinates, coincident points |
| PDF / DOCX / HTML / video | -- | **not in v1**, routed to `research-protocol.md` |

Modalities run **in parallel**: each branch writes disjoint artifacts and the report
merges them.

## The 8 Nature gates

Every run is audited against all eight; any mandatory failure means the report
exists but is **not submission-ready**.

| # | Gate | Machine evidence |
|---|---|---|
| 1 | n is explicit and the unit is defined | `unit_of_analysis.unit_key`, per-group n |
| 2 | Missingness mechanism declared | `missing_mechanism_screen` |
| 3 | Effect size accompanies p | effect size + `*_ci95` per test |
| 4 | Uncertainty visible | SE, figure intervals, CI beside every prose p |
| 5 | Multiple comparisons corrected | declared family, all adjusted p finite |
| 6 | Sensitivity tested | rank-based cross-check + Appendix A1 |
| 7 | No association → mechanism upgrade | 11 forbidden regexes over prose |
| 8 | Unknowns flagged | `AUTHOR_INPUT_NEEDED` + Appendix B |

Then it routes the run to the reporting checklist that matches the design --
**CONSORT, STROBE, PRISMA, MOOSE, STARD, ARRIVE, SQUIRE, CARE** -- and to the
journal family (**Nature, NEJM, Science, Lancet**).

```powershell
python scripts/final_audit.py --outdir outputs --journal nature
python scripts/final_audit.py --outdir outputs --journal nejm --design randomized_trial
python scripts/final_audit.py --outdir outputs --journal lancet --template standard
```

## The 10 sub-skills

The root skill routes; each sub-skill owns one stage, one artifact set and one gate.

| # | Sub-skill | Owns |
|---|---|---|
| 1 | [data-router](skills/data-router/SKILL.md) | modality + `route.json` |
| 2 | [data-profiler](skills/data-profiler/SKILL.md) | `profile.json` |
| 3 | [data-cleaner](skills/data-cleaner/SKILL.md) | `cleaning_plan.json`, `cleaned/*` |
| 4 | [data-explorer](skills/data-explorer/SKILL.md) | `descriptive.json` |
| 5 | [data-validator](skills/data-validator/SKILL.md) | `audit/final_audit.*` |
| 6 | [data-transformer](skills/data-transformer/SKILL.md) | `transform_ledger.json` |
| 7 | [statistical-analyzer](skills/statistical-analyzer/SKILL.md) | `inferential.json` |
| 8 | [deep-analyzer](skills/deep-analyzer/SKILL.md) | `model.json` |
| 9 | [visualizer](skills/visualizer/SKILL.md) | `chart_decisions.json`, `charts/*.png` |
| 10 | [report-generator](skills/report-generator/SKILL.md) | `report.md`, `report.pdf` |

## Install

```powershell
git clone https://github.com/<owner>/data-master.git
Copy-Item -Recurse data-master "$env:USERPROFILE\.codex\skills\data-master"
```

Or point your agent at the repository root; `SKILL.md` is the entry point.

## Tests

No test runner required:

```powershell
python tests/test_pipeline_invariants.py
```

The suite pins the guarantees that are easy to break silently: leading-zero
preservation, all-or-nothing conversion, untouched-column audit, byte-for-byte
replay, NaN-free multiplicity families, Welch denominator df, the shared
forbidden-phrase list, and one end-to-end render of the iris example.

## Examples

| Example | What it exercises |
|---|---|
| [examples/iris](examples/iris/) | dirty tabular data, two ANOVA branches, three figures, full PDF report |
| [examples/column_traps](examples/column_traps/) | leading zeros, currency, percent, mixed text, date ambiguity |
| [examples/timeseries](examples/timeseries/) | dropout, retransmission, sampling-regime change |
| [examples/text](examples/text/) | duplicate documents, empty file, GB18030 fallback |
| [examples/media](examples/media/) | corrupt image, re-encoded duplicate, blank frame |
| [examples/geo](examples/geo/) | out-of-range coordinates, null island, null point |

## License

MIT -- see [LICENSE](LICENSE).

## 中文

**data-master** 是一个通用数据处理 skill：把文件、文件夹或通配符交给它，Agent 会自动判断
数据类型与处理方法，完成基础清理、Nature 级别统计处理，最后交付 PDF 报告与图表。

核心承诺：

- **原始文件永不修改**（additive-only）；
- **类型只决定一次**，之后通过 manifest 重放，绝不二次猜测；
- **任何转换必须 100% 解析**才会执行，没有"解析率阈值"这种东西；
- **每个数字都可溯源**到脚本和 artifact；
- **报告是审计过的**：8 条 Nature gate 全部机器判定，失败时报告存在但标记为
  NOT SUBMISSION-READY；
- **未知就写 `AUTHOR_INPUT_NEEDED`**，绝不编造样本量、p 值或方法。

支持模态：表格、时间序列、文本语料、图像集、音频集、地理空间。PDF / DOCX / HTML / 视频
不在 v1 范围内，会明确转到 research-track，而不会偷偷当成表格处理。
