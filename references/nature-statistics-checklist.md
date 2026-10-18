# Nature Statistics Checklist

The 8 Nature-grade gates that every audit must pass when `--report nature` (default). For `standard` / `executive` templates, gates 3-6 are relaxed but 1, 2, 7, 8 remain mandatory.

> Source basis: nature-statistics skill (`references/source-basis.md`), Nature Portfolio reporting standards, CONSORT / STROBE / PRISMA / ARRIVE when relevant.

## Gate 1 — n is explicit and unit-defined

**Requirement**: For every comparison / model / effect size, the script records:

- `independent_unit` — what each row counts as (e.g. "patient", "cell-line", "session")
- `n_independent` — number of independent units
- `n_technical_replicates` — number of technical replicates per independent unit (if any)
- `n_repeated_measures` — number of repeated measures per independent unit (if any)
- `hierarchy` — when nested (e.g. cells within patients), explicit

**How the skill enforces it**: `scripts/stats_descriptive.py` reads the user-provided `experimental_unit_hint` (default: `row`). If unknown, it auto-detects repeated measures from `*_rep` / `*_replicate` columns and surfaces `AUTHOR_INPUT_NEEDED` to ask.

**Failure example**:
> "n = 120"  (no unit specified) → FAIL
> "n = 120 (120 microscopy fields from 6 patients, 20 fields per patient)" → PASS

## Gate 2 — Missing data mechanism declared

**Requirement**: For every column with missing values, the report includes:

- Missing fraction, observed associations, and any collection-context assumptions
- Mechanism remains undetermined unless justified by author-supplied context
- If imputed: method, fraction imputed, sensitivity analysis
- If dropped: rule, fraction dropped, sensitivity

**How the skill enforces it**: `scripts/stats_descriptive.py` writes an exploratory
screen to `analysis/descriptive.json`. A low missing fraction does not establish
MCAR; observed associations cannot distinguish MAR from MNAR. The mechanism is
`undetermined`, with `AUTHOR_INPUT_NEEDED` and a Gate 2 warning. Categorical
columns are included. No unimplemented Little test or automatic mechanism
classification is claimed.

**Reference text in report**:
> "Age had 8.2% missing values. The mechanism is undetermined.
> AUTHOR_INPUT_NEEDED: how missing values arose. The observed association screen
> is exploratory; it cannot establish MAR or rule out MNAR."

Method basis: [National Academies missing-data guidance](https://www.ncbi.nlm.nih.gov/books/NBK209904/pdf/Bookshelf_NBK209904.pdf).

## Gate 3 — Effect size > p-value

**Requirement**: Every comparison report must contain:

- Point estimate of effect size (Cohen d / Cliff delta / odds ratio / hazard ratio / R²)
- 95% confidence interval on the effect size
- Test name + statistic + df + p-value
- n per group

**How the skill enforces it**: `scripts/effect_size.py` computes Cohen d (parametric), Cliff delta (non-parametric), bootstrapped 95% CI. `scripts/stats_inferential.py` refuses to print a p-value without an effect size.

Gate 3 checks finite estimates and finite, ordered interval endpoints linked to
that estimate. A coefficient interval is not an interval for R² or omega-squared;
models without intervals for those effect sizes retain a warning.

**Forbidden phrasing**: "highly significant", "very significant", "trending toward significant". Use exact p (e.g. "p = 0.013") and effect magnitude language ("small / medium / large per Cohen 1988 thresholds").

## Gate 4 — Uncertainty visible

**Requirement**:

- Every numeric result has a CI, SE, or IQR.
- Every figure with a comparison has error bars, bands, or shaded intervals.
- Sampling count and method stated (n, k-fold, bootstrap).

**How the skill enforces it**:

- `scripts/render_chart.py` rejects bar / line / scatter plots that lack error bars when comparison > 1.
- `scripts/assemble_report.py` finds every `p =` and `mean ±` and demands CI in the same sentence.

## Gate 5 — Multiple comparisons corrected

**Requirement**: When > 1 hypothesis test is reported:

- Family of tests stated
- Correction method stated (Bonferroni / BH / Holm / Benjamini-Yekutieli)
- Both raw and corrected p reported
- Or: pre-registered primary + secondary distinction stated

**How the skill enforces it**: `scripts/stats_inferential.py` defaults to Benjamini-Hochberg FDR. Raw p kept in `stats.json` for transparency; corrected p in the report.

## Gate 6 — Sensitivity tested

**Requirement**: Report contains an `Appendix A1 — Sensitivity Analysis` that re-runs the primary analysis under:

- Leave-one-out
- Subset (e.g. drop top 5% by some metric, drop bottom 5%)
- Alternative imputation (mean vs MICE vs leave-as-NaN)
- Alternative test (parametric vs non-parametric)

And shows: did the conclusion change?

**How the skill enforces it**: `scripts/sensitivity_analysis.py` runs these 4 perturbations by default; appends to report.md.

## Gate 7 — No upgrade from association to mechanism

**Requirement**: Every claim must use language bounded to what the data supports.

**Forbidden upgrade patterns**:

| Association (allowed) | Mechanism (not allowed) |
|---|---|
| "X is associated with Y" | "X causes Y" |
| "X predicts Y" | "X drives Y" |
| "Patients with X had higher Y" | "X led to higher Y" |
| "Group A scored higher than B" | "Group A outperformed B because of X" |
| "After adjusting for Z, X still correlated" | "Z does not confound X-Y relationship" |

**How the skill enforces it**: `scripts/assemble_report.py` runs a simple regex / dictionary check on the draft report; flags any forbidden upgrade; replaces with bounded alternative.

## Gate 8 — Unknowns flagged

**Requirement**: Any field the agent does not have evidence for is written as `AUTHOR_INPUT_NEEDED` in the report, never invented. The user fills the gap.

**Examples**:

- Sample size unknown → `n = AUTHOR_INPUT_NEEDED`
- Randomization unknown → `randomization: AUTHOR_INPUT_NEEDED`
- Blinding unknown → `blinding: AUTHOR_INPUT_NEEDED`
- Test choice uncertain → "Two defensible tests exist (Welch t-test vs Mann-Whitney). The audit recommends Welch given approximate normality (Shapiro p = 0.21) and unequal variance (Levene p = 0.04); Mann-Whitney results in Appendix A3."

**How the skill enforces it**: `scripts/final_audit.py` scans the report for any number without provenance; if provenance is empty, replaces with `AUTHOR_INPUT_NEEDED` placeholder.

## Audit output

The audit script writes `audit/final_audit.md` and `audit/final_audit.json` with
one section per gate:

```markdown
# Nature Audit Report

## Gate 1 — n explicit        [PASS|FAIL|WARN]
- Evidence: ...
- Issues: ...

## Gate 2 — Missing declared  [PASS|FAIL|WARN]
...
```

A run with any FAIL on gates 1, 2, 7, 8 cannot produce a `report.md`; the run freezes to `audit/` and `outputs/report.md` becomes `outputs/report.PENDING.md` with the audit's actionable fixes.

## Standard / Executive relaxation

| Gate | nature | standard | executive |
|---|---|---|---|
| 1. n explicit | required | required |
| 2. Missing declared | required | required |
| 3. Effect size | required | optional |
| 4. Uncertainty visible | required | optional |
| 5. Multi-comparison | required | optional |
| 6. Sensitivity | required | skipped |
| 7. No mechanism upgrade | required | required |
| 8. Unknowns flagged | required | required |

The relaxation is **announced** in the report header so the user knows what they got.
