---
name: statistical-analyzer
description: "Choose and run the inferential test from the data structure, with effect sizes, CIs, multiplicity correction and explicit rejected alternatives. Refuses to report a p-value it cannot estimate."
parent: data-master
stage: 2c
---

# statistical-analyzer

**Stage 2c of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

When the data has a comparison or association structure. If there is no natural
grouping variable, run descriptive analysis only and say so -- inventing a grouping
variable is worse than reporting none.

## Inputs

- cleaned data with `--group <column>`
- `analysis/descriptive.json` for distributional context

## Outputs

- `analysis/inferential.json`:
  `group, group_levels, group_sizes, alpha, n_rows, unit_of_analysis, tests,
  multiple_comparisons, correlations, rule_source`
- each test: `outcome, estimable, method, statistic_name, statistic, dof, dof_denom,
  p_raw, p_adjusted, effect_sizes, rejected_alternatives, robustness_cross_check,
  post_hoc`

## Commands

```powershell
python scripts/stats_inferential.py --clean outputs/cleaned/cleaned.csv --group <column> --out outputs/analysis/inferential.json
```

## Gate (default FAIL)

- more than one test implies a declared multiplicity family with finite adjusted
  values (a single NaN poisons a whole BH family);
- every estimable test carries an effect size and a 95%% CI;
- a non-estimable outcome returns `estimable: false` with a reason and **no p-value**;
- Welch ANOVA records both numerator and denominator df.

## Failure modes seen in real runs

- Compare nested mixed models with different fixed effects using ML
  (`reml=False`), with convergence and finite-result checks. Preserve optimizer
  diagnostics. If the model cannot be fitted, report `AUTHOR_INPUT_NEEDED`;
  ordinary tests on repeated cell means are not an independent-samples fallback.
- A failed or violated ANCOVA slopes check leaves the adjusted question
  unresolved. Do not silently substitute an unadjusted question. OLS coefficient
  intervals use the residual t distribution.

Method basis: [lme4 model-comparison guidance](https://lme4.github.io/lme4/articles/lmer.pdf).

- **`df = 0.0` beside a p of 1e-70.** The Welch ANOVA denominator df was computed
  with a formula that collapsed to zero; the Satterthwaite form must be used and checked
  against `statsmodels.stats.oneway`.
- **A synonym column enters the family.** `species_code` restates `species`; including
  it double-counts one hypothesis and shrinks the corrected p-values for the others.
- **A NaN p-value is corrected as if it were a number.** One NaN propagates through the
  step-down correction and nulls the entire family.

## Do not

- do not report a p-value for a degenerate or constant group;
- do not "fix" non-normality by switching tests when n >= 30 -- use Welch and
  cross-check with the rank test;
- do not correct a subset of the family and present it as the family.

## Upstream / downstream

- previous: `../data-explorer/SKILL.md`
- next: `../visualizer/SKILL.md`
- checklist: `../../references/nature-statistics-checklist.md`
