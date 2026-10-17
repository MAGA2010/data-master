---
name: data-validator
description: "Run the 8 Nature statistical gates and the journal checklist against the finished artifacts. Writes audit/final_audit.md and refuses the label submission-ready on a mandatory FAIL."
parent: data-master
stage: 3c
---

# data-validator

**Stage 3c of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

After the report exists. Also run it on a partially finished run to see which
gate is still open -- the audit reads artifacts, so missing ones surface as FAIL/N/A
rather than as an exception.

## Inputs

- `outputs/report.md`
- `outputs/report_build.json`
- `outputs/analysis/*.json`
- `outputs/cleaned/cleaning_run.json`
- `references/journal-reporting-standards.json`

## Outputs

- `outputs/audit/final_audit.md`
- `outputs/audit/final_audit.json`
- exit code 0 (submission-ready), 1 (mandatory gate failed), 2 (cannot run)

## Commands

```powershell
python scripts/final_audit.py --outdir outputs --journal nature
python scripts/final_audit.py --outdir outputs --journal nejm --design randomized_trial
python scripts/final_audit.py --outdir outputs --template standard --json
```

## Gate (default FAIL)

Gates 1, 2, 7 and 8 are mandatory at every template. Gates 3-6 are mandatory for
`nature` and relax only where the selected template says so -- and the relaxation is
printed, never silent.

## Failure modes seen in real runs

- **An audit that trusts the report.** Gate 3 must read `effect_sizes` from
  `inferential.json`, not the sentence the report wrote about it.
- **A checklist borrowed from the wrong design.** CONSORT applied to a cross-sectional
  survey produces a page of N/A and a false sense of coverage.
- **`n = 1` matching inside `n = 158`.** Token matching is boundary-aware for a reason.

## Do not

- do not edit the report to make the audit pass;
- do not turn a FAIL into a WARN because the run is late;
- do not print PASS for registration, funding, consent or data availability -- those
  are author-supplied and are reported as AUTHOR INPUT NEEDED.

## Upstream / downstream

- checklist: `../../references/nature-statistics-checklist.md`
- journals: `../../references/journal-reporting-standards.md`
- script: `../../scripts/final_audit.py`
