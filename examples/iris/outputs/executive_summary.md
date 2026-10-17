# Iris morphometrics -- Executive summary

_Generated 2026-10-17 17:47 中国标准时间 by scripts/assemble_report.py from the artifacts listed in `report_build.json`. Every statement below is a restatement of the full report, not a separate analysis._

**Headline.** `petal_length_cm` separates species by omega squared = 0.94 out of a possible 1, 95% CI 0.93 to 0.95, BH-adjusted p = 3.7e-69 across a family of 4 outcomes.

| | |
|---|---|
| Rows analysed | 158 (from 158 raw) |
| Columns | 7 after cleaning, 1 dropped |
| Grouping variable | `species`, setosa, versicolor, virginica |
| Outcomes tested | 4 of 5 estimable |
| Multiplicity | BH, family of 4, 4 surviving |
| Cleaning operations | 10 applied, 0 withheld |
| Byte-level reproducibility | passed |
| Caveats raised | 6 |
| Open questions | see Appendix B |

## The three things a reader should take away

1. **`petal_length_cm` separates species by omega squared = 0.94 out of a possible 1, 95% CI 0.93 to 0.95, BH-adjusted p = 3.7e-69 across a family of 4 outcomes**
2. **6 caveat(s) bound these results**, and the one that matters most is: 2 variable(s) carry missing values, the most at `sepal_width_cm` (3.8%). Values were not imputed, so every statistic here is conditional on complete cases. Listwise deletion removed rows from `sepal_width_cm` (6 rows, n = 152), `petal_width_cm` (6 rows, n = 152). The screening test returned MCAR-likely, which is a screening result and not proof of a mechanism -- confirm it against how the data were actually collected.
3. **This design compares groups that already exist.** The group label was not assigned here, so the differences reported are associations. No causal reading is available from this data, and none is offered.

## What to read next

- `report.pdf` (or `report.md`) -- the full report, with figures and appendices.
- Section 5 -- the caveats, each with its limits and its resolution status.
- Appendix A1.1 -- the sensitivity analyses that were *not* run.
- Appendix B -- the questions that only the data's author can answer.
- `report_build.json` -- machine-readable provenance for every number above.
