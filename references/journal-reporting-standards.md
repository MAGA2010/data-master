# Journal reporting standards -- NEJM / Science / Lancet / Nature

This file answers one question: **when a run says "Nature-level", what exactly is being
asserted, and which part of it can a script verify?**

The machine-readable half of this document is
`references/journal-reporting-standards.json`. `scripts/final_audit.py` reads that JSON;
this file explains it. If the two ever disagree, the JSON wins and this file is wrong.

---

## 1. Why route by journal at all

The four journal families ask broadly the same statistical questions, but they weight
them differently and they attach different *house* requirements to the same paper.

- **A randomised trial** judged against STROBE is being judged against the wrong
  question, no matter how well it is written.
- **A generic association table** has no EQUATOR checklist of its own. Saying so is
  better than silently borrowing CONSORT.
- **Data availability, registration, funding and conflicts** cannot be derived from a
  CSV. They are author-supplied. A pipeline that prints "PASS" for them is lying.

Routing therefore produces three things per run:

1. the **EQUATOR checklist** that matches the study design (or an explicit
   `AUTHOR_INPUT_NEEDED` when the design is not stated);
2. the **journal-specific reporting items** layered on top;
3. a split between items the **8 statistical gates can check** and items only the
   **author** can supply.

---

## 2. The four journal families

| Journal | Core statistical posture | Design checklist | Machine-checkable here |
|---|---|---|---|
| **Nature Portfolio** | 8-gate statistical standard: n and unit, missingness, effect size + CI, visible uncertainty, multiplicity, sensitivity, no mechanism upgrade, unknowns flagged | Nature Portfolio reporting standards; EQUATOR checklist for the design | all 8 gates |
| **NEJM** | Registration and protocol for trials; exact p-values with effect sizes and CIs; pre-specified primary endpoint and multiplicity plan; CONSORT for trials, STROBE for observational work, PRISMA for reviews | CONSORT / STROBE / PRISMA / MOOSE | gates 1-8, plus presence of a declared primary outcome and family |
| **Science** | Explicit n and error-bar definition; named statistical test; exact p-values; data and code availability statements | EQUATOR checklist for the design | gates 1-5, 7, 8; reproducibility statement |
| **The Lancet** | CONSORT/STROBE/PRISMA adherence; protocol and registration; multiplicity for multiple endpoints; data-sharing statement | CONSORT / STROBE / PRISMA / MOOSE | gates 1-8, plus family declaration |

Official references (checked 2026-10-17):

- Nature Portfolio reporting standards -- <https://www.nature.com/nature-portfolio/editorial-policies/reporting-standards>
- Nature Portfolio statistics -- <https://www.nature.com/nature-portfolio/editorial-policies/statistics>
- NEJM author center -- <https://www.nejm.org/author-center/new-manuscripts>
- Science Journals editorial policies -- <https://www.science.org/content/page/science-journals-editorial-policies>
- The Lancet information for authors -- <https://www.thelancet.com/information-for-authors>
- EQUATOR Network (index of all checklists) -- <https://www.equator-network.org/>

> These policies change. The audit cites the URL it used and the date of this file, so a
> reviewer can see which version was in force when the run was audited. Re-check the
> URL before submission; do not treat this table as a substitute for the journal's own
> instructions.

---

## 3. Design -> checklist routing

`scripts/final_audit.py --design auto` scans the title, the source filename, the column
names and the first 6,000 characters of the report for design tokens.

| Design id | Checklist | Typical trigger tokens |
|---|---|---|
| `randomized_trial` | CONSORT 2025 | randomised, randomized, placebo, 1:1, trial |
| `observational` | STROBE | cohort, cross-sectional, case-control, survey |
| `systematic_review` | PRISMA 2020 | systematic review, meta-analysis, heterogeneity, I2 |
| `observational_meta` | MOOSE | meta-analysis + observational design words |
| `diagnostic_accuracy` | STARD 2015 | sensitivity, specificity, AUC, index test |
| `animal_preclinical` | ARRIVE 2.0 | mice, rats, in vivo, xenograft |
| `quality_improvement` | SQUIRE 2.0 | PDSA, quality improvement, intervention cycle |
| `case_report` | CARE | case report, single patient, `n = 1` |
| `analytical_chemistry` | Nature Portfolio reporting standards | calibration, LOD, LOQ, recovery, precision |
| `generic` | Nature Portfolio reporting standards + `AUTHOR_INPUT_NEEDED` | no design statement found |

Two rules make the routing trustworthy:

- **Boundary-aware matching.** Token matching is anchored on word boundaries. An
  earlier version used plain substring matching and classified an iris dataset as a
  CARE case report because `n = 1` is a substring of `n = 158`.
- **Ambiguity is reported, not resolved.** If two designs match, the audit returns
  `generic` and lists both token hits. Choosing between CONSORT and STROBE is an author
  decision, not a guess the tool should make.

---

## 4. What the 8 gates actually check

Full definitions live in `references/nature-statistics-checklist.md`. The audit
implements them as follows.

| Gate | Machine evidence | FAIL condition |
|---|---|---|
| 1. n explicit, unit defined | `inferential.unit_of_analysis.unit_key`, per-group n | unit not declared, or any estimable test lacks n |
| 2. Missingness declared | `descriptive.missing_mechanism_screen` | a variable with missing values has no mechanism |
| 3. Effect size > p | `effect_sizes` keys with `*_ci95` | an estimable test carries a p value but no effect size |
| 4. Uncertainty visible | SE on every numeric descriptive; `uncertainty` on every comparison figure; every prose `p =` sentence also carries a CI | a prose p value with no interval in its sentence |
| 5. Multiple comparisons | `multiple_comparisons.primary_family` | >1 test and no family, or family size disagrees with the adjusted vector |
| 6. Sensitivity tested | `robustness_cross_check` on each test + Appendix A1 | no cross-check, or no appendix |
| 7. No mechanism upgrade | 11 forbidden regexes over prose, disclaimer lines skipped | any surviving construction |
| 8. Unknowns flagged | `AUTHOR_INPUT_NEEDED` + Appendix B | a known unknown is not flagged |

Gate 4 deliberately only fails on **prose**. A results table may list a p value in a
column headed "p (corrected)" without repeating the CI in the same cell; the sentence
that *interprets* it must carry the interval.

---

## 5. Relaxation profiles

`--template` controls how much of the checklist is enforced. The relaxation is printed
in the audit, never applied silently.

| Gate | `nature` | `standard` | `executive` |
|---|---|---|---|
| 1. n + unit | required | required | required |
| 2. missingness | required | required | required |
| 3. effect size | required | required | optional |
| 4. uncertainty | required | required | optional |
| 5. multiplicity | required | required | optional |
| 6. sensitivity | required | optional | skipped |
| 7. no upgrade | required | required | required |
| 8. unknowns | required | required | required |

A `standard` or `executive` run is legitimate for a business question. It is not
legitimate to describe its output as Nature-level, and the report header records which
profile produced it.

---

## 6. Items no script can verify

The audit prints these as `AUTHOR INPUT NEEDED` rather than `PASS`:

- trial or review **registration** id, and whether it was registered before enrolment;
- **protocol** and any protocol deviations;
- **randomisation sequence** and **allocation concealment**;
- **blinding** of participants, carers, assessors;
- **data availability** and **code availability** statements, and the access route;
- **funding**, **conflict of interest**, **author contributions**;
- **consent** and ethics approval;
- **confounders measured** -- the pipeline sees the columns it was given, not the ones
  that were never collected;
- **harms** and **adverse events**;
- **search strategy**, **risk of bias**, **publication bias**, **certainty of evidence**
  for reviews.

A report that leaves these blank is incomplete, not clean.
