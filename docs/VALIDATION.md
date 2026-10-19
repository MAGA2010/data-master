# Validation and release checks

Run these checks before publishing a release:

```bash
python tests/test_pipeline_invariants.py
python tests/test_reliability.py
python tests/test_pipeline_integrity.py
python tests/test_distribution.py
npm test
python -X utf8 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" .
python scripts/package_skill.py --out dist/data-master-0.2.0.skill
```

| Suite | Evidence provided | Limit |
|---|---|---|
| Pipeline invariants | Type preservation, cleaning replay, routing, statistical dispatch, audit behavior | Regression cases do not establish validity for every dataset |
| Numerical references | Mixed-model ML compared with independently profiled block GLS; ANCOVA with matrix least squares; paired-test equations | Deterministic fixtures, not a simulation study of error rates |
| Pipeline integrity | Full analysis, edited inference detection, downstream rebuild, PDF recovery, raw-input preservation | State ledger is the trust anchor |
| Distribution | Build a wheel, install into a venv, invoke the actual console command outside the checkout, run the bundled demo, verify and resume | Scientific dependencies are inherited from the test environment; this does not test clean dependency resolution |
| npm launcher | Pack and install the actual tarball outside the checkout, execute through npm, run the demo and verify/resume; check argument forwarding and setup failure recovery | Integration uses an existing Python environment; setup orchestration is tested without downloading the scientific stack |
| Skill distribution | Install through both entry points, refuse overwrite, build a deterministic `.skill` archive and validate required resources | Does not test behavior in every Agent Skills-compatible client |

The wheel test also rejects accidental inclusion of user outputs and repository
metadata, checks runtime-resource paths, and exercises paths containing spaces.
CI runs distribution checks on Windows and Linux with Python 3.13; the existing
regression matrix covers Python 3.11, 3.12 and 3.13.

To build an installable wheel locally:

```bash
python -m pip wheel . --no-deps --wheel-dir dist
```

No upload occurs. Install the resulting wheel into a test environment before
publishing. This package is versioned as `0.2.0`; a Git tag, hosted release and
PyPI upload are separate actions. The installed CLI is an entry point for the
same standalone scripts used by the skill, not an independent analysis engine.

The npm package is private to prevent accidental registry publication. GitHub
installation and `npm pack` remain supported. `npm install` never runs Python
installation hooks; explicit `data-master setup` owns its isolated environment.

Tagged releases are built by `.github/workflows/release.yml`. The workflow
creates the wheel, npm tarball, `.skill` archive and `SHA256SUMS`, validates the
skill archive, then attaches every artifact to the GitHub release.
