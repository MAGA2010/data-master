---
name: data-profiler
description: "Profile a dataset without changing it: shape, dtypes, missingness, duplicates, distributions, anomalies, candidate group/target/time columns. Emits profile.json."
parent: data-master
stage: 1b
---

# data-profiler

**Stage 1b of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

After routing, before any cleaning plan exists. The profile is the only
artifact the rest of the pipeline is allowed to use to decide what a column *is*.

## Inputs

- the raw file, read as text for tabular formats (`read_mode="text"`)
- `route.json` from data-router

## Outputs

- `analysis/profile.json` for tabular:
  `schema_version, source, modality, sampled, read_mode, shape, columns, column_roles,
  anomalies, target_candidate, group_candidate, timeseries_candidate,
  independent_unit_hint`
- per-modality profiles for text / time-series / image-set / audio-set / geospatial

## Commands

```powershell
python scripts/profile_tabular.py --in <raw.csv> --out outputs/analysis/profile.json
```

## Gate (default FAIL)

Every column carries `dtype`, `n_missing`, `n_unique` **and** the raw text
evidence for its role. `group_candidate.rejected` must explain every rejected column --
including the ones rejected for having fewer than two observed levels.

## Failure modes seen in real runs

- **An all-null column wins the grouping score.** With `n_unique = 0`, a naive balance
  metric returns `1.0` and an entropy term divided by `max(nu,1)` returns `2.0` -- the
  highest score in the table. Reject `n_unique < 2` before scoring.
- **A numeric-looking code is profiled as a measurement.** `species_code` is a numeric
  restatement of `species`; profiling it as an outcome produces a duplicate test. The
  structural restatement check must catch it.
- **Reading with inferred dtypes destroys the evidence.** `02134` becomes `2134` before
  the profiler can see it.

## Do not

- do not modify the file being profiled;
- do not sample silently -- `sampled: true` must appear in the profile and the report;
- do not use the profiler's dtype guess as the final dtype; the cleaning plan decides.

## Upstream / downstream

- previous: `../data-router/SKILL.md`
- next: `../data-cleaner/SKILL.md`
- contract: `../../references/workflow-contract.md`
