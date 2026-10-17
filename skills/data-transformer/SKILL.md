---
name: data-transformer
description: "Derive analysis variables from cleaned data under an explicit, reversible transformation ledger. No silent recoding, no leakage."
parent: data-master
stage: 2b
---

# data-transformer

**Stage 2b of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

When the analysis needs a derived variable (log transform, ratio, binning, unit
conversion, date parts) that is not already a column. Optional: a run with no derived
variables skips this skill and records that it did.

## Inputs

- cleaned data (manifest replayed)
- an explicit transformation spec: source columns, operation, parameters, output name

## Outputs

- `analysis/transformed.csv` (or an in-memory frame recorded in the ledger)
- `analysis/transform_ledger.json`: one record per derived column with
  `{output, operation, inputs, parameters, reversible, rule_source,
  alternative_considered, rejected_reason}`

## Commands

```powershell
# transformations are declared in the run spec, not typed at a prompt
python -c "import json,sys; print(json.dumps(json.load(open('outputs/analysis/transform_ledger.json')), indent=2))
```

## Gate (default FAIL)

Every derived column has a ledger record **and** a stated inverse (or
`reversible: false` with the reason). A derived column may not be created from the
outcome it will later predict -- that is leakage, and it is the single most common way a
clean pipeline produces an impressive, meaningless result.

## Failure modes seen in real runs

- **Target leakage.** A feature computed from the outcome inflates the effect to
  implausibility; the ledger makes the input columns visible so the leak can be caught.
- **Silent recoding.** `M/F` -> `0/1` without a mapping record makes the direction of
  the effect unrecoverable.
- **Transforming after cleaning.** A log transform applied to the raw column while the
  cleaned column keeps its original scale produces two incompatible reports.

## Do not

- do not derive a variable inside the statistical script and forget to record it;
- do not transform the grouping variable into the outcome;
- do not transform a column the cleaning plan withheld.

## Upstream / downstream

- previous: `../data-cleaner/SKILL.md`
- next: `../statistical-analyzer/SKILL.md`
- contract: `../../references/workflow-contract.md`
