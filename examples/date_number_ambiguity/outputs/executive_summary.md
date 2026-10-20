# Date-versus-number ambiguity -- Executive summary

_Generated 2026-10-19 20:07 中国标准时间 by scripts/assemble_report.py from the artifacts listed in `report_build.json`. Every statement below is a restatement of the full report, not a separate analysis._

**Headline.** `latency_s` is compared across subject_id: omega squared = 0.87, 95% CI 0.84 to 0.93, BH-adjusted p = 3.5e-17 across a family of 1 outcomes.

| | |
|---|---|
| Rows analysed | 48 (from 48 raw) |
| Columns | 3 after cleaning, 0 dropped |
| Grouping variable | `subject_id`, P001, P002, P003, P004, P005, P006, P007, P008 |
| Outcomes tested | 1 of 1 estimable |
| Multiplicity | BH, family of 1, 1 surviving |
| Cleaning operations | 9 applied, 0 withheld |
| Byte-level reproducibility | passed |
| Caveats raised | 1 |
| Open questions | see Appendix B |

## The three things a reader should take away

1. **`latency_s` is compared across subject_id: omega squared = 0.87, 95% CI 0.84 to 0.93, BH-adjusted p = 3.5e-17 across a family of 1 outcomes**
2. **1 caveat(s) bound these results**, and the one that matters most is: The independent unit was never declared, so each row was treated as one observation. If a row pools several plants, fields, patients or technical replicates, the effective n is smaller than the row count and every interval below is too narrow -- usually by more than the replication factor. The groups were also not assigned, so differences between them are associations and this data cannot support a reading in which the group label produced the measurement.
3. **This design compares groups that already exist.** The group label was not assigned here, so the differences reported are associations. No causal reading is available from this data, and none is offered.

## What to read next

- `report.pdf` (or `report.md`) -- the full report, with figures and appendices.
- Section 5 -- the caveats, each with its limits and its resolution status.
- Appendix A1.1 -- the sensitivity analyses that were *not* run.
- Appendix B -- the questions that only the data's author can answer.
- `report_build.json` -- machine-readable provenance for every number above.
