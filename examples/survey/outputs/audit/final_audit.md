# Final audit -- Synthetic survey responses

_Generated 2026-10-23 15:01 中国标准时间 by scripts/final_audit.py from the artifacts on disk. This audit reads the report; it does not trust it._

**Verdict: SUBMISSION-READY**

No mandatory gate failed. Warnings below are disclosed limits, not hidden failures.

| Gate | Name | Status |
|---|---|---|
| 1 | n explicit and unit-defined | **PASS** |
| 2 | missing data mechanism declared | **WARN** |
| 3 | effect size accompanies p | **PASS** |
| 4 | uncertainty visible | **PASS** |
| 5 | multiple comparisons corrected | **N/A** |
| 6 | sensitivity tested | **PASS** |
| 7 | no association-to-mechanism upgrade | **PASS** |
| 8 | unknowns flagged | **PASS** |

## Gate 1 -- n explicit and unit-defined   [PASS]

- **Evidence**: unit `respondent_id` declared; primary analysis at the row level; n=105 across 1 outcome(s).

## Gate 2 -- missing data mechanism declared   [WARN]

- **Evidence**: 3 variable(s) carry missing values and 3 have no declared mechanism.
- **Issues**:
  - AUTHOR_INPUT_NEEDED: missingness mechanism for: satisfaction, visit_frequency, minutes_spent
- **Fix**: record collection context and a justified assumption; a small missing fraction or an association screen cannot establish it.

## Gate 3 -- effect size accompanies p   [PASS]

- **Evidence**: all 1 estimable tests carry an effect size with a 95% CI.

## Gate 4 -- uncertainty visible   [PASS]

- **Evidence**: every descriptive statistic carries an SE, every comparison figure states its interval, and every prose p value sits beside a CI.

## Gate 5 -- multiple comparisons corrected   [N/A]

- **Evidence**: only 1 test was estimable, so there is no family to correct.

## Gate 6 -- sensitivity tested   [PASS]

- **Evidence**: 17 perturbation(s) ran across 1 outcome(s) (leave-one-group-out, block jackknife, extreme-value fence, strict complete cases) and every one agreed with the primary verdict at alpha=0.05. Appendix A1 reports them.

## Gate 7 -- no association-to-mechanism upgrade   [PASS]

- **Evidence**: no forbidden construction appears outside a disclaimer (11 patterns checked across 318 lines).

## Gate 8 -- unknowns flagged   [PASS]

- **Evidence**: every unknown the pipeline detected is written AUTHOR_INPUT_NEEDED and repeated in Appendix B (3 withheld decision(s)).

## Structural checks

| Check | Status | Detail |
|---|---|---|
| required sections | **PASS** | all 10 required sections present |
| at least one caveat | **PASS** | 3 caveat(s) |
| figure title / caption / body | **PASS** | all 2 figure(s) carry title, caption and a three-part body |
| number provenance | **PASS** | 4 registered claim(s) in report_build.json |
| PDF delivered | **PASS** | backend reportlab, 195991 bytes |
| writer self-audit | **PASS** | 0 forbidden phrases in the writer's own scan |

## Journal routing

- **Journal family**: Nature Portfolio
- **Reporting standards**: Nature Portfolio reporting standards + the 8 data-master statistical gates
- **Checklist for this design**: STROBE
- **Design inferred**: `observational`
  - no design was declared; inferred from the token 'survey'
  - checklist selected: STROBE
  - journal resolved to nature

| Reporting item | Status | How it is evidenced |
|---|---|---|
| n_and_unit | CHECKED BY THE 8 GATES | inferential.unit_of_analysis.unit_key is set and every estimable test reports n |
| missing_data | CHECKED BY THE 8 GATES | every column above 5% missing carries a declared mechanism |
| effect_size_ci | CHECKED BY THE 8 GATES | every estimable test carries an effect size with a 95% CI |
| confounders | AUTHOR INPUT NEEDED | author-supplied; the pipeline cannot know which variables were measured |
| selection_bias | AUTHOR INPUT NEEDED | author-supplied |
| data_availability | AUTHOR INPUT NEEDED | author-supplied |
| code_availability | AUTHOR INPUT NEEDED | author-supplied |
| funding | AUTHOR INPUT NEEDED | author-supplied |
| conflict_of_interest | AUTHOR INPUT NEEDED | author-supplied |
| author_contributions | AUTHOR INPUT NEEDED | author-supplied |
