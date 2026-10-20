# Validation and release checks

Run these checks before publishing a release:

```bash
python tests/test_pipeline_invariants.py
python tests/test_reliability.py
python tests/test_pipeline_integrity.py
python tests/test_html_export.py
python tests/test_date_number_ambiguity.py
python tests/test_survey_case.py
python tests/test_distribution.py
npm test
python -X utf8 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" .
python scripts/package_skill.py --out dist/data-master-0.3.0.skill
```

| Suite | Evidence provided | Limit |
|---|---|---|
| Pipeline invariants | Type preservation, cleaning replay, routing, statistical dispatch, audit behavior | Regression cases do not establish validity for every dataset |
| Numerical references | Mixed-model ML compared with independently profiled block GLS; ANCOVA with matrix least squares; paired-test equations | Deterministic fixtures, not a simulation study of error rates |
| Pipeline integrity | Full analysis, edited inference detection, downstream rebuild, PDF recovery, raw-input preservation | State ledger is the trust anchor |
| HTML export | Self-contained `report.html` derived from `report.md`, source hash stamped into the file, altered/missing export fails verification | Rendering fidelity of the Markdown subset the reports use, not arbitrary Markdown |
| Date-number ambiguity | The `coerce_numeric_or_date` hold fires with evidence, automatic cleaning preserves the values, one answers-file resolution converts through the audited path | One 8-digit fixture shape (YYYYMMDD); other ambiguity shapes are untested |
| Survey case | Zero-padded identifiers stay text, -999 codes surface as an impossible-value hold, labels survive unencoded, blanks stay missing | One synthetic fixture; no real survey instrument semantics |
| Distribution | Build a wheel, install into a venv, invoke the actual console command outside the checkout, run the bundled demo, verify and resume | Scientific dependencies are inherited from the test environment; this does not test clean dependency resolution |
| npm launcher | Pack and install the actual tarball outside the checkout, execute through npm, run the demo and verify/resume; check argument forwarding and setup failure recovery | Integration uses an existing Python environment; setup orchestration is tested without downloading the scientific stack |
| Skill distribution | Install through both entry points, refuse overwrite, build a deterministic `.skill` archive and validate required resources | Does not test behavior in every Agent Skills-compatible client |

The wheel test also rejects accidental inclusion of user outputs and repository
metadata, checks runtime-resource paths, and exercises paths containing spaces.
CI runs distribution checks on Windows, Linux and macOS with Python 3.13; the
existing regression matrix covers Windows and Linux with Python 3.11, 3.12 and
3.13. The macOS job is the same `tests/test_distribution.py` suite as the other
platforms; a macOS-specific failure is a bug in the distribution, not a
platform note to route around, so none is currently documented.

To build an installable wheel locally:

```bash
python -m pip wheel . --no-deps --wheel-dir dist
```

No upload occurs. Install the resulting wheel into a test environment before
publishing. This package is versioned as `0.3.0`; a Git tag, hosted release and
PyPI upload are separate actions. The installed CLI is an entry point for the
same standalone scripts used by the skill, not an independent analysis engine.

The npm package is configured for public registry publication. GitHub
installation and `npm pack` remain supported. `npm install` never runs Python
installation hooks; explicit `data-master setup` owns its isolated environment.

Tagged releases are built by `.github/workflows/release.yml`. The workflow
creates the wheel, npm tarball, `.skill` archive and `SHA256SUMS`, validates the
skill archive, then attaches every artifact to the GitHub release.

## Agent Skills client validation: ZCode 3.14.4 (Windows)

Recorded 2026-10-19; every statement below was observed, none inferred.

| Item | Observation |
|---|---|
| Client and version | ZCode desktop 3.14.4 (Windows), version read from the client's own startup log |
| Skill location | `C:\Users\华为\.zcode\skills\data-master` (ZCode's per-user skills directory; differs from the Codex default `~/.codex/skills`) |
| Installation path exercised | wheel built from this repository, installed into an isolated venv outside the checkout, then `data-master skill install --target <dir>` |
| Discovery | a freshly spawned agent session in the client listed `data-master` among its available skills with the SKILL.md path; frontmatter (`name`, `description`, `allowed-tools`) parsed unchanged, non-standard fields tolerated |
| Invocation prompt | "Use the data-master skill to analyze `page_load.csv` (64-row synthetic A/B page-load data) with `--group variant --unit-key session_id --outcomes load_time_ms`; run doctor, analyze, then verify" |
| Produced artifacts | doctor `healthy: true` (v0.2.0); analyze exit 0, audit verdict SUBMISSION-READY; `verify --json` returned `valid: true`; delivered `report.md`, `report.html`, `report.pdf`, `executive_summary.md`, `analysis/`, `cleaned/`, `charts/`, `audit/`, `state.json` |
| Incompatibilities noted | none functional. Cosmetic: the CLI's post-install message says "Restart Codex", which is client-specific wording; the `--target` flag installs into any client's skills directory |

The compatibility claim added to `EVALUATION.md` covers only this client and
version. It does not extend to other ZCode releases, other platforms, or other
Agent Skills clients.
