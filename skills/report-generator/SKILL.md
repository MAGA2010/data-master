---
name: report-generator
description: "Assemble report.md, executive_summary.md and report.pdf from the artifacts. Every number is registered against its source; the PDF is the primary deliverable and the Markdown is the citable source."
parent: data-master
stage: 3b
---

# report-generator

**Stage 3b of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

After figures render. Never before the statistical gates have artifacts to read --
a report written first is a report that has to be edited to fit the numbers.

## Inputs

- all of `outputs/analysis/*.json`
- `outputs/cleaned/cleaning_run.json`
- `outputs/charts_rendered.json`

## Outputs

- `report.md` -- full report, 6 sections + 4 appendices
- `executive_summary.md` -- one page, same numbers
- `report.pdf` -- A4, CJK-capable, page numbers, table of contents
- `report_build.json` -- provenance for every number, PDF backend trail, self-audit

## Commands

```powershell
python scripts/assemble_report.py --raw <raw.csv> --outdir outputs --title "<title>"
```

## Gate (default FAIL)

- every number in the prose appears in the provenance table;
- every forbidden construction is absent outside a disclaimer;
- the PDF cascade records which backend ran and why earlier tiers were skipped;
- `report.md` is complete even when the PDF is BLOCKED.

## Failure modes seen in real runs

- **Self-referential hash.** A document cannot contain its own sha256; the report
  points at `report_build.json` instead of printing a stale value.
- **A PDF backend that "works" but drops images.** The browser tier embeds images as
  data URIs because `file://` sandboxing silently loses them.
- **A missing CJK font rendered as black boxes.** The reportlab tier falls back to a
  CID font and records whether it was embedded.

## Do not

- do not type a number into the report that was not read from an artifact;
- do not treat a BLOCKED PDF as success -- the markdown is complete, the deliverable is
  not;
- do not duplicate the executive summary's argument in the full report with different
  wording.

## Upstream / downstream

- previous: `../visualizer/SKILL.md`
- next: `../data-validator/SKILL.md`
- templates: `../../references/report-template-catalog.md`
