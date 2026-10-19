# Repeated-measures treatment comparison -- Statistical Report

> **Template**: nature | **Generated**: 2026-10-19 18:17 中国标准时间 | **Pipeline**: data-master
> **Raw input**: `measurements.csv` (sha256 `2519c6d2304dc381...`) | **Analysed file**: `cleaned.csv`
> **Rows**: 36 raw -> 36 analysed | **Columns**: 4 | **Modality**: tabular
> **Independent unit**: every unit belongs to exactly one group; multiple rows per unit are replicates, and the primary analysis is run on per-unit means
> **Types**: `cleaning_run.json` (4 columns replayed from the cleaning manifest, never re-guessed)

## Executive summary

**Setup.** 36 rows and 4 columns reached the analysis, of which 2 are numeric measurements, compared across 2 levels of `arm` (control, treatment).

**The conflict.** No defect capable of changing a conclusion was detected in the raw file.

**How it was resolved.** 9 documented operation(s) were applied, 36 rows became 36, and the cleaned file reproduces byte for byte. The clearest separation is that `response` is compared across arm: Cohen's d = -6.35, 95% CI -9.36 to -3.35, BH-adjusted p = 6.6e-07 across a family of 1 outcomes.

**The caveat that matters most.** No defect requiring a caveat was detected in this run. That is a statement about the checks that ran, not a guarantee that the data are fit for the conclusions drawn.

## 1. Setup

- **Source**: `measurements.csv`, read in `text` mode so that no column type was guessed at load time -- a reader that guesses turns a postcode `02134` into `2134` before any audit of the decision can exist.
- **Routing**: modality `tabular`; 4 columns profiled.
- **Grouping variable**: `arm`, which the router scored highest among the columns able to form groups (score 1.000, balance 1.00 as entropy normalised by log of the level count). Grouping by a column with a single level would have returned one group compared with itself and a confident, meaningless zero.
- **Row meaning**: the router suggests `row`; that is a heuristic, and the real answer is an open question below.
- **Pre-registration**: AUTHOR_INPUT_NEEDED. Nothing in the input says whether these analyses were planned in advance, and the outcome columns were chosen after the data were seen.

## 2. Methods

### 2.1 Cleaning

The raw file was never modified. 9 operation(s) were applied automatically and 0 were withheld for a human decision. Every applied operation names the columns it is permitted to touch; the run then compares raw against cleaned in text space and fails if any column no operation named gained a value. In this run: all 2 untouched columns kept exactly their raw values.

**Byte-level reproducibility**: passed -- hash matches. Cleaned sha256 `6f62b85a4cf5d537...`.

> high-risk operations are never silent; see references/never-automatic-list.md

### 2.2 Types

Types were decided once and replayed, never re-guessed: 4 columns were typed from the manifest in `cleaning_run.json`. A column that the cleaning stage declared textual cannot quietly become numeric in the analysis stage while the report still describes it as an identifier. Dtype source for the analysis stage: `cleaning_run.json`.

### 2.3 Missing data

No variable carries missing values.

### 2.4 Test selection

| Outcome | Design | Method | Statistic | df | p (raw) | p (corrected) | Alternatives rejected |
|---|---|---|---|---|---|---|---|
| `response` | 2-group numeric | Student two-sample t-test (pooled variance) | t = -10.999 | 10 | = 6.6e-07 | = 6.6e-07 | Welch t-test: equal variance holds (Levene p > alpha); the pooled test is more powerful |

### 2.5 Multiple comparisons

The primary family holds **1 outcomes**, one per measured variable, corrected by **BH** at alpha = 0.050. 1 of 1 survive the correction. one outcome = one member of the family; correction applies across outcomes, and separately within each post-hoc pairwise family

## 3. Results

### 3.1 What is in the table

| Column | Role after cleaning | n | % missing | Distinct values | Status |
|---|---|---|---|---|---|
| `subject` | categorical | 36 | 0.0 | 12 | kept |
| `arm` | categorical | 36 | 0.0 | 2 | kept |
| `visit` | numeric | 36 | 0.0 | continuous | kept |
| `response` | numeric | 36 | 0.0 | continuous | kept |


### 3.2 Descriptive statistics

| Variable | n | % miss | Mean (95% CI) | SD | Median (IQR) | Range | Skew |
|---|---|---|---|---|---|---|---|
| `visit` | 36 | 0.0 | 2.00 (1.73 to 2.27) | 0.83 | 2.00 (1.00-3.00) | [1.00, 3.00] | 0.00 |
| `response` | 36 | 0.0 | 10.71 (10.44 to 10.97) | 0.80 | 10.40 (10.10-11.43) | [9.70, 12.30] | 0.73 |

Mean and median are both given because they disagree wherever the distribution is skewed. The mean column carries a normal-approximation interval, which for a skewed variable is the least trustworthy number on this table; the median and IQR beside it are not.

### 3.3 Categorical variables

| Variable | n | Distinct | Mode | Distribution |
|---|---|---|---|---|
| `subject` | 36 | 12 | `c01` | c01 (3), c02 (3), c03 (3), c04 (3), c05 (3), c06 (3) |
| `arm` | 36 | 2 | `control` | control (18), treatment (18) |


### 3.4 Group comparison

| Outcome | Method | Statistic | n | Effect size (95% CI) | p (raw) | p (BH-adjusted) |
|---|---|---|---|---|---|---|
| `response` | Student two-sample t-test (pooled variance) | t = -11.00 | 12 | Cohen's d = -6.351 (95% CI -9.36 to -3.35) | = 6.6e-07 | = 6.6e-07 |


Read the effect-size column before the p column. `. The ordering by effect size and the ordering by p value are not the same statement, and at this sample size the p values are small enough that their exact magnitude carries no information beyond "smaller than this table can resolve".response` is compared across arm: Cohen's d = -6.35, 95% CI -9.36 to -3.35, BH-adjusted p = 6.6e-07 across a family of 1 outcomes

## 4. Discussion

**What the data supports.** The measurements differ across levels of `arm` by margins far larger than the sampling noise at this size: `response` is compared across arm: Cohen's d = -6.35, 95% CI -9.36 to -3.35, BH-adjusted p = 6.6e-07 across a family of 1 outcomes. The ordering of variables by effect size holds under both the parametric and the rank-based test (Appendix A3), so the finding is not an artefact of one distributional assumption. Two of the measured pairs are strongly associated and one is not, which is reported as association only.

**What the data does not support.** Nothing here establishes that the group label produced the measurement. The design compares existing groups rather than assigning them, and species, batch, site, instrument and operator all travel together with the group label -- this table cannot separate them. A claim of the form "X caused Y" is therefore not available from these data, and none is made in this report.

**Boundary conditions.** These results describe the rows in this file, at these measurement conditions, with this instrument. The intervals quantify sampling variation inside that set; they say nothing about another lot, another season or another population. The corrected family covers the outcomes tested here, so an outcome that was not tested is not thereby null.

## 5. Caveats and limitations

**C1. no defect detected.** No defect requiring a caveat was detected in this run. That is a statement about the checks that ran, not a guarantee that the data are fit for the conclusions drawn.
- *Limits*: all claims
- *Status*: not applicable

## 6. Reproducibility

Every number above is traceable to a script. Nothing in this report was typed by hand.

| Stage | Script | Artifact | sha256 (first 16) |
|---|---|---|---|
| Profile | scripts/profile_tabular.py | analysis/profile.json | bb4737ea248965fe |
| Plan | scripts/cleaning_plan.py | cleaning_plan.json | 7ac8130efd147906 |
| Clean | scripts/execute_cleaning.py | cleaned/cleaned.csv | 6f62b85a4cf5d537 |
| Validate | scripts/validate_clean.py | cleaned/validation.json | ad2137c384c90c6e |
| Describe | scripts/stats_descriptive.py | analysis/descriptive.json | 6cbb044156c80a75 |
| Infer | scripts/stats_inferential.py | analysis/inferential.json | 777cf97debe33ea1 |
| Decide figures | scripts/chart_decision.py | analysis/chart_decisions.json | a6d3103be5b99c94 |
| Render figures | scripts/render_chart.py | charts/*.png | e1a6abf058364938 |
| Assemble | scripts/assemble_report.py | report.md / report.pdf | self-referential -- see report_build.json |


A document cannot contain its own hash, so the hash of `report.md` and `report.pdf` is recorded in `report_build.json` rather than on this page. Every other hash above was computed from the artifact as it exists now.

- **Interpreter**: Python 3.13.15 on Windows-11-10.0.26200-SP0
- **Libraries**: numpy 2.4.6, pandas 3.0.3, scipy 1.18.1
- **Pipeline code**: data-master commit `028ac9a03e9b` (working tree was dirty; the commit alone does not reproduce it) -- this report names the exact code that produced every number in it.
- **Exact versions**: `lockfile.txt` beside this report pins every dependency to the version that ran.
- **Random seeds**: 42 -- every resampling interval is seeded, so it reproduces exactly.
- **Columns any operation was permitted to touch**: `response`, `visit`

- **PDF backend**: `reportlab`. The page count, byte count and sha256 of the delivered PDF are recorded in `report_build.json` under `pdf`; the probe that established this backend is under `pdf_probe`. They are not printed here because a document cannot contain its own hash, and a page count measured before the last line changed is not the page count of the file you are reading.
  The data contains non-Latin characters, so the renderer was asked for a CJK-capable font; one was embedded.
## 7. Figures

Each figure carries one argument and its title states that argument as a finding computed from the data rather than as a topic label. The chart types considered and rejected are listed under each one, because choosing a chart is itself a claim about what matters.

### Figure 1 -- 1 of 2 measured variables are skewed, so the analyses below summarise them by median rather than mean

*Distribution of each numeric variable, with the median and interquartile range marked. Panel order follows absolute skewness. Full box-and-whisker statistics are in Table 2.*

![Figure 1: 1 of 2 measured variables are skewed, so the analyses below summarise them by median rather than mean](charts/fig01_distribution_panel.png)

- **What it shows**: response is moderately right-skewed (median 10.40, IQR 10.10 to 11.43, n = 36); visit is roughly symmetric (median 2.00, IQR 1.00 to 3.00, n = 36).
- **How to read it**: Skewed variables are summarised by the median and IQR, and rank-based or Welch methods are preferred for them.
- **What follows**: These summaries, not the raw shape, should carry into any downstream model.
- **Uncertainty shown**: median and interquartile range marked on every panel
- **Chart alternatives rejected**: one histogram per variable as separate figures -- same argument repeated; the reader has to re-read the framing each time; box plot only -- understates the tail, which is precisely what decides the test choice
- **Source**: `scripts/chart_decision.py` -> `charts/fig01_distribution_panel.png` rendered by `scripts/render_chart.py`, 89,713 bytes, ink ratio 0.4227

## 8. Figure specifications

| # | ID | Chart type | Specification |
|---|---|---|---|
| 1 | `fig01_distribution_panel` | distribution_panel | 2 panels; bins = auto; show_median_iqr = True |


## Appendix A1. Sensitivity and stability

The primary analysis was re-run under perturbation by `scripts/sensitivity_analysis.py` (seed 42, 10 blocks for the jackknife). Agreement means the significance verdict did not flip at alpha=0.05.

| Outcome | Perturbation | Statistic | p | Verdict |
|---|---|---|---|---|
| `response` | strict_complete_case (n=36 of 36 rows) | Student two-sample t-test (pooled variance) = -11.00 | = 6.6e-07 | agrees |
| `response` | row_level_comparison | Welch two-sample t-test (unequal variance) = -6.97 | = 8.3e-07 | agrees |
| `response` | rank_cross_check | Mann-Whitney U = 0.00 | = 0.002 | agrees |


Assumption robustness (distinct from the perturbations above):

| Outcome | Check | Statistic | p | Verdict |
|---|---|---|---|---|
| `response` | rank-based cross-check of the primary test | Mann-Whitney U = 0.00 | = 0.002 | agrees |

Each primary parametric test was repeated with its rank-based equivalent. Agreement means the conclusion does not depend on the normality assumption the parametric test makes; a disagreement would have meant the parametric test had to go, not be defended.

### A1.1 Sensitivity analyses not run

None -- every perturbation that applies to this design ran, and the ones that do not apply are marked as such in `analysis/sensitivity.json`.

## Appendix A2. Cleaning ledger

Every operation that ran, in order, with the catalogue rule it came from. Nothing below was chosen by the model at run time: the plan is the gate, and only `plan["auto_actions"]` may execute.

| # | Operation | Columns | Sev. | Rows | Rule |
|---|---|---|---|---|---|
| 1 | `fix_unicode` | `arm`, `response`, `subject` (+1 more) | P3 | 36->36 | `t-fix-unicode` |
| 2 | `strip_whitespace` | `arm`, `response`, `subject` (+1 more) | P3 | 36->36 | `t-strip-ws` |
| 3 | `collapse_whitespace` | `arm`, `response`, `subject` (+1 more) | P3 | 36->36 | `t-collapse-whitespace` |
| 4 | `trim_paired_quotes` | `arm`, `response`, `subject` (+1 more) | P3 | 36->36 | `t-trim-quotes` |
| 5 | `coerce_numeric` | `response`, `visit` | P2 | 36->36 | `t-coerce-numeric` |
| 6 | `normalize_dtypes` | `arm`, `response`, `subject` (+1 more) | P2 | 36->36 | `t-normalize-dtypes` |
| 7 | `drop_all_null_cols` | (file-level) | P1 | 36->36 | `t-drop-all-null-cols` |
| 8 | `drop_all_null_rows` | (file-level) | P1 | 36->36 | `t-drop-all-null-rows` |
| 9 | `rename_columns_append_cleaned` | (file-level) | P2 | 36->36 | `t-rename-clean` |


The `Rule` column names the catalogue anchor; the full path, the operation id and the exact column list for every row above are in `cleaned/cleaning_run.json` under `applied_ops`.

**Withheld -- proposed but deliberately not applied.**

Nothing was withheld.

**Failed -- attempted and did not complete.**

No operation failed.

**Additive-only audit.** The contract forbids modifying the raw file and permits an operation to touch only the columns it names. Columns no operation named: **2, and each kept exactly its raw values -- audit passed**.

## Appendix A3. Alternatives considered and not used

A test is a choice. Listing only the test that was run hides the fact that a different, defensible analysis was available, so every rejected alternative is recorded here with the reason it lost.

| Outcome | Design | Rejected test | Reason |
|---|---|---|---|
| `response` | 2-group numeric | `Welch t-test` | equal variance holds (Levene p > alpha); the pooled test is more powerful |


The rule that made these choices is `references/nature-statistics-checklist.md#gates-1-3-5`. It was applied mechanically; there is no per-dataset override, because a rule that is quietly overridden is a rule that cannot be checked.

## Appendix A4. Where every number came from

Each value below was registered by the code that read it from an artifact on disk. A sentence in this report that is not backed by a row here is a sentence that should not have been written.

| Kind | Value | What it means | Source: script -> artifact | Rule anchor |
|---|---|---|---|---|
| `header` | 36 | rows analysed | `execute_cleaning.py` -> `cleaning_run.json` | `--` |
| `headline` | `response` is compared across arm: Cohen's d = -6.35, 95% CI... | strongest group separation | `stats_inferential.py` -> `inferential.json` | `--` |
| `rejected test` | Welch t-test | rejected for response | `stats_inferential.py` -> `inferential.json` | `two_group_numeric` |
| `correction` | BH | family correction method | `stats_inferential.py` -> `inferential.json` | `gate-5` |

Only the basename of each artifact and script is shown here; the full path, the untruncated value and the complete claim record for every row are in `report_build.json` under `provenance`. Each record carries `rule_source`, and where a rule had an alternative the record names it and why it lost -- a claim with no alternative says so rather than leaving the field blank.

## Appendix B. Open questions the data cannot answer

1 question must be answered by someone who knows how the data were collected. They are listed with the consequence of leaving them unanswered, because an unanswered question that carries no stated cost is one nobody will prioritise.

| # | Question | Why it matters | Cost of leaving it open |
|---|---|---|---|
| 1 | Were these outcomes chosen in advance? | Nothing in the input records a pre-specified analysis plan, and the outcome family was assembled from the columns present. Without that, the family-size correction controls multiplicity within this report but cannot address selection across reports. | HIGH -- determines whether the correction is the right one |


### What this report does not claim

- It does not claim the group label produced the measurement.
- It does not claim the analysis was pre-specified.
- It does not claim the rows are independent observations.
- It does not claim any mechanism for the missingness it reports; the screening test in 2.3 is a description, not a diagnosis.

---

*End of report. Generated 2026-10-19 18:17 中国标准时间 by data-master. The raw input was never modified: every value above was read from the cleaned file or from a recorded artifact. Each number is registered in `report_build.json`; the gate verdict, including anything that failed, is in `audit/final_audit.md`.*
