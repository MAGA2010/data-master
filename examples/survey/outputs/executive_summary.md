# Synthetic survey responses -- Executive summary

_Generated 2026-10-23 15:01 中国标准时间 by scripts/assemble_report.py from the artifacts listed in `report_build.json`. Every statement below is a restatement of the full report, not a separate analysis._

**Headline.** `minutes_spent` is compared across satisfaction: rank epsilon squared = 0.86, 95% CI 0.75 to 0.96, BH-adjusted p = 1.4e-15 across a family of 1 outcomes.

| | |
|---|---|
| Rows analysed | 120 (from 120 raw) |
| Columns | 6 after cleaning, 0 dropped |
| Grouping variable | `satisfaction`, Dissatisfied, Neutral, Satisfied, Very dissatisfied, Very satisfied |
| Outcomes tested | 1 of 1 estimable |
| Multiplicity | BH, family of 1, 1 surviving |
| Cleaning operations | 9 applied, 0 withheld |
| Byte-level reproducibility | passed |
| Caveats raised | 3 |
| Open questions | see Appendix B |

## The three things a reader should take away

1. **`minutes_spent` is compared across satisfaction: rank epsilon squared = 0.86, 95% CI 0.75 to 0.96, BH-adjusted p = 1.4e-15 across a family of 1 outcomes**
2. **3 caveat(s) bound these results**, and the one that matters most is: 3 variable(s) carry missing values, the most at `minutes_spent` (7.5%). Values were not imputed, so every statistic here is conditional on complete cases. Listwise deletion removed rows from `minutes_spent` (15 rows, n = 105). The screening test returned undetermined, which is a screening result and not proof of a mechanism -- confirm it against how the data were actually collected.
3. **This design compares groups that already exist.** The group label was not assigned here, so the differences reported are associations. No causal reading is available from this data, and none is offered.

## What to read next

- `report.pdf` (or `report.md`) -- the full report, with figures and appendices.
- Section 5 -- the caveats, each with its limits and its resolution status.
- Appendix A1.1 -- the sensitivity analyses that were *not* run.
- Appendix B -- the questions that only the data's author can answer.
- `report_build.json` -- machine-readable provenance for every number above.
