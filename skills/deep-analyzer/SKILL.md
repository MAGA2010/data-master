---
name: deep-analyzer
description: "Optional modelling stage: regression, mixed effects, clustering, dimensionality reduction, forecasting. Only runs when the design supports it; every model carries diagnostics."
parent: data-master
stage: 2d
---

# deep-analyzer

**Stage 2d of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

Only when the user asks for a model, or when a stated question cannot be answered
by a group comparison. Never the default: a model adds assumptions that must be
defended.

## Inputs

- cleaned data
- a declared model specification: outcome, predictors, random effects, family, link

## Outputs

- `analysis/model.json`: coefficients with CIs, fit statistics, diagnostics,
  `n`, `unit_of_analysis`, `rule_source`
- `analysis/model_residuals.png` when diagnostics are visual

## Commands

```powershell
# v1 ships no model-fitting script: a deep-analysis run is an explicit,
# supervised step that must leave analysis/model.json in place.
python -c "import json; d=json.load(open('outputs/analysis/model.json',encoding='utf-8')); assert d.get('rule_source'); print('model artifact OK')"
```

## Gate (default FAIL)

Every coefficient has an estimate, a CI and the unit it applies to. Every model
reports at least one diagnostic appropriate to its family (residual vs fitted,
overdispersion, VIF, convergence). A model that did not converge is reported as such,
never as a fit.

## Failure modes seen in real runs

- **Pseudo-replication.** Rows that share a subject are modelled as independent,
  so every standard error is too small. Random effects are required when the design is
  nested.
- **A converged-looking fit with separation.** Logistic regression on a rare outcome
  can produce enormous coefficients; the diagnostic must be printed, not skipped.
- **Comparing models on different n.** AIC across different complete-case sets is not
  a comparison.

## Do not

- do not run a model because it is available;
- do not report a coefficient without its scale and CI;
- do not drop the diagnostics to keep the table short.

## Upstream / downstream

- previous: `../statistical-analyzer/SKILL.md`
- next: `../visualizer/SKILL.md`
- contract: `../../references/workflow-contract.md`
