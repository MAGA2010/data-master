# Final audit -- Date-versus-number ambiguity

_Generated 2026-10-19 20:08 中国标准时间 by scripts/final_audit.py from the artifacts on disk. This audit reads the report; it does not trust it._

**Verdict: NOT SUBMISSION-READY**

Blocking issues:
- Gate 1 (n explicit and unit-defined): independent unit not declared: no --unit-key given; the row is assumed to be the independent unit, and every test below inherits that assumption

| Gate | Name | Status |
|---|---|---|
| 1 | n explicit and unit-defined | **FAIL** |
| 2 | missing data mechanism declared | **PASS** |
| 3 | effect size accompanies p | **PASS** |
| 4 | uncertainty visible | **PASS** |
| 5 | multiple comparisons corrected | **N/A** |
| 6 | sensitivity tested | **PASS** |
| 7 | no association-to-mechanism upgrade | **PASS** |
| 8 | unknowns flagged | **PASS** |

## Gate 1 -- n explicit and unit-defined   [FAIL]

- **Evidence**: n is recorded per outcome (e.g. n=48) and per group, but the independent unit is not declared in the input.
- **Issues**:
  - independent unit not declared: no --unit-key given; the row is assumed to be the independent unit, and every test below inherits that assumption
- **Fix**: pass --unit-key with what one row represents, or record it in the run manifest; the report already marks this AUTHOR_INPUT_NEEDED.

## Gate 2 -- missing data mechanism declared   [PASS]

- **Evidence**: no variable carries missing values (n=48 analysed).

## Gate 3 -- effect size accompanies p   [PASS]

- **Evidence**: all 1 estimable tests carry an effect size with a 95% CI.

## Gate 4 -- uncertainty visible   [PASS]

- **Evidence**: every descriptive statistic carries an SE, every comparison figure states its interval, and every prose p value sits beside a CI.

## Gate 5 -- multiple comparisons corrected   [N/A]

- **Evidence**: only 1 test was estimable, so there is no family to correct.

## Gate 6 -- sensitivity tested   [PASS]

- **Evidence**: 9 perturbation(s) ran across 1 outcome(s) (leave-one-group-out, block jackknife, extreme-value fence, strict complete cases) and every one agreed with the primary verdict at alpha=0.05. Appendix A1 reports them.

## Gate 7 -- no association-to-mechanism upgrade   [PASS]

- **Evidence**: no forbidden construction appears outside a disclaimer (11 patterns checked across 315 lines).

## Gate 8 -- unknowns flagged   [PASS]

- **Evidence**: every unknown the pipeline detected is written AUTHOR_INPUT_NEEDED and repeated in Appendix B (unit undeclared).

## Structural checks

| Check | Status | Detail |
|---|---|---|
| required sections | **PASS** | all 10 required sections present |
| at least one caveat | **PASS** | 1 caveat(s) |
| figure title / caption / body | **PASS** | all 2 figure(s) carry title, caption and a three-part body |
| number provenance | **PASS** | 5 registered claim(s) in report_build.json |
| PDF delivered | **PASS** | backend reportlab, 171285 bytes |
| writer self-audit | **PASS** | 0 forbidden phrases in the writer's own scan |

## Journal routing

- **Journal family**: Nature Portfolio
- **Reporting standards**: Nature Portfolio reporting standards + the 8 data-master statistical gates
- **Checklist for this design**: Nature Portfolio reporting standards (design checklist AUTHOR_INPUT_NEEDED)
- **Design inferred**: `generic`
  - no design statement was found in the data or the report; pass --design to select the EQUATOR checklist that applies
  - checklist selected: Nature Portfolio reporting standards (design checklist AUTHOR_INPUT_NEEDED)
  - journal resolved to nature

| Reporting item | Status | How it is evidenced |
|---|---|---|
| n_and_unit | CHECKED BY THE 8 GATES | inferential.unit_of_analysis.unit_key is set and every estimable test reports n |
| missing_data | CHECKED BY THE 8 GATES | every column above 5% missing carries a declared mechanism |
| effect_size_ci | CHECKED BY THE 8 GATES | every estimable test carries an effect size with a 95% CI |
| multiplicity | CHECKED BY THE 8 GATES | a multiplicity family is declared whenever more than one test is reported |
| data_availability | AUTHOR INPUT NEEDED | author-supplied |
| code_availability | AUTHOR INPUT NEEDED | author-supplied |
| funding | AUTHOR INPUT NEEDED | author-supplied |
| conflict_of_interest | AUTHOR INPUT NEEDED | author-supplied |
| author_contributions | AUTHOR INPUT NEEDED | author-supplied |

## What must change before this is submitted

1. **Gate 1 (n explicit and unit-defined)** -- pass --unit-key with what one row represents, or record it in the run manifest; the report already marks this AUTHOR_INPUT_NEEDED.
