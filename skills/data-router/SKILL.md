---
name: data-router
description: "Classify any input path into one of eight modalities and emit a route manifest. First stage of data-master; no statistics, no cleaning."
parent: data-master
stage: 1a
---

# data-router

**Stage 1a of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

The moment a user hands over a file, a folder, or a glob. Never skip it: a CSV
with a timestamp column and a free-text corpus are both `.csv`/`.txt`, and the wrong
branch produces a technically valid report about the wrong object.

## Inputs

- a path, folder, or glob
- an optional `--modality` override, recorded as `origin: user`

## Outputs

- `outputs/route.json` -- one entry per input file:
  `{path, modality, evidence, confidence, branch, alternatives_rejected}`

## Commands

```powershell
# inspect what will be routed; prints the decision table without writing anything
python scripts/check_deps.py --explain

# the decision table itself
Get-Content references/modality-routing.md
```

## Gate (default FAIL)

`route.json` exists **and** every input file has a `modality` in
`{tabular, text-corpus, time-series, image-set, audio-set, geospatial, mixed, unknown}`.
A file with `modality: unknown` routes to `references/research-protocol.md` and stops the
automatic branch -- it does not silently fall back to tabular.

## Failure modes seen in real runs

- **A `.csv` of free text** is routed to tabular, then every column is reported as
  categorical. Sniff the delimiter and the fraction of unique tokens per row before
  committing.
- **A timestamped table** is routed to tabular, so the trend is reported as a static
  association. If a column parses as datetime and is monotonic or near-monotonic, route
  to time-series.
- **A glob silently matching zero files** reports "no data" instead of failing the
  gate. Count matched files and fail loudly on zero.

## Do not

- do not infer modality from the extension alone;
- do not let a mixed folder collapse into one modality -- route each file, then merge
  reports;
- do not overwrite a user-supplied `--modality`; record it as an override with its
  evidence.

## Upstream / downstream

- next: `../data-profiler/SKILL.md`
- table: `../../references/modality-routing.md`
- unknown inputs: `../../references/research-protocol.md`
