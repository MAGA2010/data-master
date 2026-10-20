# Launch kit

Use these drafts when sharing `data-master`. Keep the demo, release, and case
study links in the post so readers can verify the claims without installing the
project first.

## One-line description

`data-master` turns raw datasets into auditable PDF reports with reproducible
cleaning, unit-aware statistics, sensitivity checks, and machine-verifiable
evidence.

## Hacker News

**Title**

> Show HN: data-master – Auditable data analysis from one command

**Text**

> I built data-master because a polished chart can hide basic analysis failures:
> identifiers silently converted to numbers, repeated rows counted as independent
> samples, or a p-value reported without the test and effect size that produced it.
>
> It is an open-source Codex skill and cross-platform CLI. It preserves the raw
> input, writes a replayable cleaning program, runs analysis at the declared unit,
> saves sensitivity checks, and produces a PDF plus a separate audit that can
> refuse a “submission-ready” verdict.
>
> The repository includes five synthetic failure-case studies, Windows/Linux CI
> on Python 3.11–3.13, macOS distribution coverage, an evaluation dashboard, and
> a v0.3.0 release with a wheel,
> npm archive, `.skill` archive, and checksums.
>
> Repository: https://github.com/MAGA2010/data-master
>
> I would especially value feedback on the audit gates and datasets that should be
> added to the evaluation suite.

## Reddit

**Suggested communities:** r/opensource, r/datascience, r/Python

**Title**

> I made an open-source tool that audits the analysis, not just the code

**Text**

> `data-master` is a Codex skill and CLI that turns raw datasets into reproducible
> Markdown/PDF reports. The main idea is that each cleaning and statistical claim
> should leave inspectable evidence.
>
> It catches conversion traps such as leading-zero identifiers, distinguishes rows
> from independent units, records effect sizes and intervals, runs sensitivity
> checks, and emits a separate audit verdict. If a critical study decision is
> missing, it delivers the report but refuses to call it submission-ready.
>
> The repository has a 24-second demo, five reproducible case studies, a public
> evaluation dashboard, and release artifacts for the CLI and skill package:
> https://github.com/MAGA2010/data-master
>
> Feedback and small contribution-sized issues are welcome, especially real-world
> failure cases that can be turned into synthetic regression fixtures.

## LinkedIn

> A polished data report can still be wrong in quiet ways: `02134` becomes `2134`,
> repeated observations inflate the sample size, or an unresolved design decision
> disappears behind a finished PDF.
>
> I built **data-master**, an open-source Codex skill and cross-platform CLI that
> turns raw data into an auditable report. It preserves raw inputs, records every
> cleaning decision, uses unit-aware statistics, runs sensitivity checks, and
> produces machine-verifiable evidence alongside the PDF.
>
> Version 0.3.0 includes one-command GitHub installation, five reproducible
> case studies, an evaluation dashboard, Windows/Linux CI, macOS distribution
> coverage, and signed-by-checksum
> release artifacts.
>
> Explore it or contribute a failure case: https://github.com/MAGA2010/data-master
>
> #OpenSource #DataScience #ReproducibleResearch #Python

## X

> I built data-master: an open-source Codex skill + CLI that turns messy datasets
> into auditable PDF reports. Reproducible cleaning, unit-aware stats, sensitivity
> checks, and evidence you can verify. v0.3.0: https://github.com/MAGA2010/data-master

## Maintainer outreach

Use this short note only when a project or community is directly relevant.

> I maintain data-master, an open-source Codex skill and CLI for auditable data
> analysis. Your work on [specific project/topic] overlaps with its [specific
> feature or case study]. I would value a technical review of that part; the
> relevant evidence is at [direct link]. No promotion is expected.

## Links to rotate

- Repository: https://github.com/MAGA2010/data-master
- Release: https://github.com/MAGA2010/data-master/releases/tag/v0.3.0
- Date-or-number benchmark: https://github.com/MAGA2010/data-master/blob/main/docs/case-studies/identifier-traps.md#benchmark-date-or-number
- Synthetic survey: https://github.com/MAGA2010/data-master/blob/main/docs/case-studies/survey-data.md
- Evaluation: https://github.com/MAGA2010/data-master/blob/main/EVALUATION.md
- Identifier traps: https://github.com/MAGA2010/data-master/blob/main/docs/case-studies/identifier-traps.md
- Repeated rows: https://github.com/MAGA2010/data-master/blob/main/docs/case-studies/unit-aware-comparison.md
- Audit refusal: https://github.com/MAGA2010/data-master/blob/main/docs/case-studies/audit-refusal.md
- Good first issues: https://github.com/MAGA2010/data-master/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22

## Launch checklist

- Use one audience-specific draft rather than posting identical text everywhere.
- Show the failure case and evidence before listing features.
- Answer every technical question with a direct artifact or source link.
- Record traffic sources with GitHub Insights and review stars, clones, release
  downloads, issue authors, and returning contributors each week.
- Turn repeated questions into documentation, fixtures, or `good first issue`
  tasks within 48 hours.
