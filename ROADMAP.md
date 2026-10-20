# Roadmap

The roadmap is driven by successful external analyses, not feature count.

## Now: first 50 users

- Make install-to-first-report reliable in under five minutes.
- Publish three reproducible case studies with inspectable artifacts. (five now published, including survey data and date-number ambiguity)
- Collect the first ten external dataset reports and document setup failures.

## Next: 50–200 users

- Publish a benchmark corpus of dirty and statistically deceptive datasets.
- Complete an independent statistical-method review.
- Add a safe skill update command with rollback.
- Improve Excel workbook and survey-data workflows based on reported demand.

## Later: 200–1,000 users

- Publish the prepared npm and PyPI packages after registry ownership and trusted publishing are configured.
- Add a hosted, privacy-preserving demo with synthetic data.
- Translate the quick start with community maintainers.
- Establish a regular release cadence and maintainer group.

## Contribution-sized tasks

The first five contribution-sized tasks are complete (macOS distribution job,
HTML export, survey case study, date-number ambiguity fixture, and client
validation in ZCode 3.14.4); see the [changelog](CHANGELOG.md). Small focused
contributions are still welcome:

1. Report an external dataset analysis (input, command, artifacts) to grow the
   public acceptance evidence.
2. Validate the skill in a further Agent Skills client and record only
   observed behavior.
3. Add a fixture for an ambiguity shape not yet covered (for example mixed
   locale decimal commas in an identifier column).

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing statistical decisions.
