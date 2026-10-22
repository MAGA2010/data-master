# Changelog

All notable changes are recorded here. The project follows semantic versioning.

## [Unreleased]

### Added

- Single-table SQLite inputs (`.sqlite`, `.sqlite3`, `.db`) now follow the
  audited tabular pipeline. Multi-table databases fail clearly instead of
  silently selecting a table; coverage is pinned by `tests/test_sqlite_input.py`.

## [0.3.0] - 2026-10-20

### Added

- `report.html`: a self-contained shareable export of `report.md` on both the
  full-analysis and profile-only report paths. Figures are embedded as data
  URIs, the source markdown hash is stamped into the file, artifact
  verification owns and hashes it, and an altered or missing export fails
  verification (`tests/test_html_export.py`).
- Date-versus-number ambiguity benchmark: `examples/date_number_ambiguity`
  holds a `coerce_numeric_or_date` column with evidence, preserves it under
  automatic cleaning, and resolves through an answers file
  (`tests/test_date_number_ambiguity.py`); documented in the identifier-traps
  case study.
- Synthetic survey case study: labelled categories, a `-999` missing code and
  zero-padded identifiers each surface as an evidenced never-automatic decision
  (`examples/survey`, `tests/test_survey_case.py`,
  `docs/case-studies/survey-data.md`).
- macOS Python 3.13 distribution job in CI; platform coverage recorded in
  `docs/VALIDATION.md`.
- Agent Skills client validation record for ZCode 3.14.4 on Windows
  (installation, discovery and one full analysis; `docs/VALIDATION.md`).

### Corrected

- Report prose no longer claims a group separation the data does not show: the
  executive summary and discussion word null results as null results, the
  discussion's association sentence is derived from the actual correlation
  matrix instead of hardcoded counts, and a `%`-formatting precedence bug that
  garbled one paragraph of every delivered report is fixed.
- Rank-based omnibus results now carry a bootstrap 95% CI for epsilon squared,
  so rank-path reports can satisfy the effect-size and uncertainty-visible
  gates exactly like parametric ones.
- A group with fewer than two observations no longer pushes a NaN p-value
  through the omnibus test into the multiplicity correction (which crashed);
  the comparison is reported as not estimable with the reason.
- Impossible negative values in text columns that will auto-coerce (for
  example a `-999` "not answered" code) are now profiled and raised as a
  `drop_impossible` hold instead of reaching the analysis silently.
- The untouched-column audit no longer crashes on pandas `NA` in text columns
  with blanks.

## [0.2.0] - 2026-10-19

### Added

- Installable Python package and GitHub npm launcher.
- One-command Codex skill installation for npm and Python users.
- Unit-aware analyses for clustered, paired and repeated-measures data.
- Covariate-adjusted comparisons with assumption checks.
- Time-series descriptive analysis, sensitivity artifacts and report audit gates.
- Hash-verified resume, read-only artifact verification and exact dependency lock export.
- Cross-platform distribution, launcher and end-to-end tests.
- Deterministic `.skill` packaging and tagged GitHub release automation.

### Corrected

- Mixed-model comparisons now use maximum likelihood and require valid convergence evidence.
- Invalid repeated-measures and ANCOVA fallbacks are withheld instead of overstated.
- Missingness mechanisms remain undetermined without collection context.

[0.2.0]: https://github.com/MAGA2010/data-master/releases/tag/v0.2.0
[0.3.0]: https://github.com/MAGA2010/data-master/releases/tag/v0.3.0
