---
name: data-explorer
description: "Descriptive analysis and EDA on cleaned data: distributions, missingness mechanism screen, correlations, categorical structure. No p-values for group comparisons."
parent: data-master
stage: 2a
---

# data-explorer

**Stage 2a of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

After cleaning passes its gate. Run this before inferential statistics so the
test choice is informed by the actual distributions, not assumed.

## Inputs

- `outputs/cleaned/cleaned.csv` via `dm_types.load_cleaned` (manifest replayed)
- `analysis/profile.json`

## Outputs

- `analysis/descriptive.json`:
  `numeric` (mean, SD, SE, median, IQR, range, skew, missing_pct),
  `categorical` (levels, counts, mode),
  `missing_mechanism_screen`, `correlation_pearson`

## Commands

```powershell
python scripts/stats_descriptive.py --clean outputs/cleaned/cleaned.csv --out outputs/analysis/descriptive.json
```

## Gate (default FAIL)

Every numeric variable carries `n`, `missing_pct`, mean **and** median, SD, IQR and
skew. Reporting only the mean for a strongly skewed variable is a fail, because the
mean is then the least trustworthy number on the page.

## Failure modes seen in real runs

- **Mean without median** hides a 3 SD outlier.
- **A missingness screen presented as a mechanism proof.** Little's test describes the
  pattern; it cannot prove MCAR. The wording must say "screening result".
- **Pearson only** on a monotone-but-curved pair understates the association; Spearman
  is reported alongside, and its use is recorded.

## Do not

- do not compute group p-values here -- that is the statistical-analyzer's job;
- do not read the cleaned file with `pd.read_csv`; that re-guesses the types;
- do not drop the median because the mean was requested.

## Upstream / downstream

- previous: `../data-cleaner/SKILL.md`
- next: `../statistical-analyzer/SKILL.md`
- contract: `../../references/workflow-contract.md`
