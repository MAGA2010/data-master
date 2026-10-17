# Report Template Catalog

Three templates, each with a different rigor-vs-clarity trade-off. The user picks via `--report nature|standard|executive`. The agent picks default = `nature`.

## 1. `report.md` — Nature-grade report

Drawn from `nature-statistics` output format + `data-storytelling` setup→conflict→resolution structure.

```markdown
# [Dataset short name] — Statistical Report

> **Template**: Nature-grade | **Generated**: YYYY-MM-DD HH:MM | **Pipeline state**: state.json
> **Source**: <file> | **Independent unit**: <unit| AUTHOR_INPUT_NEEDED> | **n = X (technical Y, repeated Z)**
> **Data time span**: from A to B (where applicable)

## Executive summary
One paragraph: setup → conflict → resolution, with one numeric headline + one caveat.

## 1. Setup
- Data origin, modality, profile summary.
- Independent unit and hierarchy.
- Pre-registered or post-hoc (flag AUTHOR_INPUT_NEEDED if unsure).

## 2. Methods
- Cleaning: list of auto-applied ops (severity <= P2) + flagged ops (severity >= P1) with user status.
- Type inference rules and exceptions.
- Missing data mechanism (Gate 2) with evidence.
- Test selection rationale: which test, why, alternatives rejected.
- Multiple comparison correction (Gate 5) method.
- Randomization / blinding: AUTHOR_INPUT_NEEDED if unknown.

## 3. Results
- Descriptive statistics (per variable).
- Comparison(s) with effect size + 95% CI + corrected p.
- Each figure cited as: "Figure 1 shows..." with body sentence.

## 4. Discussion (cautious)
- What the data supports (association / prediction).
- What it does NOT support (mechanism / causation).
- Boundary conditions and generalization limits.

## 5. Caveats and limitations
- Minimum 1, ideally 3 (sample size, missing mechanism, generalization).
- Each caveat cites the affected claim.

## 6. Reproducibility
- Script paths (one per result).
- Random seeds (when applicable).
- Python + library versions (from `outputs/env.txt`).

## Figures
[Embedded PNGs with title-caption-body triplet above each]

## Tables
[Auto-generated markdown tables with the same headers as in analysis/stats.json]

## Appendix A1 — Sensitivity analysis
- Leave-one-out, subset, alternative imputation, alternative test.
- Did the conclusion change? (Yes/No per perturbation.)

## Appendix A2 — Cleaning report
- Full op list + flag list.
- Each op severity + rule_source.

## Appendix A3 — Alternative tests
- For each primary test, the runner-up test and its result.

## AUTHOR_INPUT_NEEDED
- [factually-grounded factual questions only]
```

## 2. `executive_summary.md` — 1-page TL;DR

```markdown
# TL;DR — [Dataset name]

> One sentence headline result with effect size + CI.
> One sentence headline caveat.

## What we analyzed
- Source: <file>
- n: <n> <unit>
- Modality: <tabular|text|timeseries>

## Top 3 findings
1. <Finding 1 with number + CI + caveat>
2. <Finding 2 ...>
3. <Finding 3 ...>

## What we did NOT do
- <Any non-applicable Nature gate>
- <Any non-applicable stage 3 element>

## Next steps
- <Action 1 (user-decision needed?)>
- <Action 2>
```

## 3. `audit_report.md` — Nature audit

```markdown
# Nature Audit Report — [dataset]

## Gate 1 — n explicit                       [PASS|WARN|FAIL]
- ...
## Gate 2 — Missing declared                 [PASS|WARN|FAIL]
- ...
## Gate 3 — Effect size + p                  [PASS|WARN|FAIL]
- ...
## Gate 4 — Uncertainty visible              [PASS|WARN|FAIL]
- ...
## Gate 5 — Multiple comparisons             [PASS|WARN|FAIL]
- ...
## Gate 6 — Sensitivity tested               [PASS|WARN|FAIL]
- ...
## Gate 7 — No mechanism upgrade             [PASS|WARN|FAIL]
- ...
## Gate 8 — Unknowns flagged                 [PASS|WARN|FAIL]
- ...

## Final verdict
- All gates PASS / WARN only / some FAIL
- If FAIL: list actionable fixes
```

## Templates per modality

| Modality | Report focus |
|---|---|
| tabular | stats + comparisons + uncertainty (default) |
| text-corpus | corpus stats + dedupe + token + PII flag |
| time-series | trend + seasonality + changepoints + forecast band |
| image-set | dedup + size distribution + EXIF highlights |
| audio-set | duration + silence + clipping + dedup |
| geo | CRS + bbox + overlap summary |
| mixed | one section per modality, then cross-modality joins (only if user opted in) |

## Uncertainty language templates

Use these exact phrases when reporting numbers:

| Context | Phrase |
|---|---|
| Comparison | "Group A scored M (95% CI: [lo, hi], n = X) compared to Group B (M, 95% CI: [lo, hi], n = Y); difference = D (95% CI: [lo, hi]), Cohen d = D (95% CI: [lo, hi]), p_corrected = P (test name)." |
| Effect size | "Effect size: Cohen d = 0.42 (95% CI: [0.18, 0.66]) — small-to-medium per Cohen 1988." |
| Trend | "Trend: linear slope = B per unit (95% CI: [lo, hi]); n = X; p = P." |
| Forecast | "Forecast: next k periods expected Y (90% prediction interval [lo, hi]); based on seasonal-naive model." |
| Missing | "Missing data: col `x` 8.2% missing; Little MCAR p = 0.04; mechanism = MAR conditional on `dep`; MICE imputation used; sensitivity in Appendix A1." |
| Unknown | "AUTHOR_INPUT_NEEDED: <fact>." |

## Forbidden phrasing

| Forbidden | Use instead |
|---|---|
| "highly significant" | "p < 0.001 (test name)" |
| "trending toward significant" | "p = 0.07" or "weak evidence" |
| "X causes Y" | "X is associated with Y" |
| "X drives Y" | "X predicts Y in this sample" |
| "outperforms" | "scores higher than" |
| "robust" | describe the specific perturbation that did not change the result |
| "significant difference" | exact test, n, effect, CI, p |
