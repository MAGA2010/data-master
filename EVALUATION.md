# Evaluation

data-master is evaluated as an analysis pipeline, an installable distribution
and an agent skill. Passing these checks shows that the implemented contracts
hold for the fixtures; it does not establish scientific validity for every
possible dataset.

## Current evidence

| Area | What is checked | Current scope |
|---|---|---|
| Data integrity | Raw inputs preserved, identifiers remain text, conversions are all-or-nothing, untouched columns do not change | Deterministic regression fixtures |
| Numerical references | Welch, paired, mixed-model and ANCOVA results are compared with independently calculated references | Known-answer synthetic datasets |
| Evidence integrity | Saved artifact hashes, changed-code invalidation, selective resume and missing-PDF recovery | Full pipeline integration test |
| Distribution | Wheel installation outside the checkout, console entry point, bundled resources and demo | Windows and Linux, Python 3.13 |
| Compatibility | Core suite and examples | Windows and Linux, Python 3.11–3.13 |
| npm launcher | Packed tarball installation, argument safety, explicit setup, demo, verify, resume and skill installation | Node.js 22 in CI; Node.js 20+ supported |
| Skill structure | Frontmatter, resource layout and unresolved placeholders | Official skill validator |

CI results are public in [GitHub Actions](https://github.com/MAGA2010/data-master/actions).
Detailed test boundaries and local commands live in
[`docs/VALIDATION.md`](docs/VALIDATION.md).

## Compatibility claims

| Surface | Status |
|---|---|
| Codex skill | Verified structure and local installation |
| Standalone Python CLI | Verified |
| GitHub npm launcher | Verified |
| Claude Code, Cursor, Gemini CLI | Candidate Agent Skills compatibility; not yet claimed as verified |
| macOS | Expected from the Python and Node stacks; dedicated CI runner still planned |

## Public acceptance targets

Before calling the project `1.0`, the project seeks:

- 20 external datasets completed from installation through artifact verification;
- at least one independent statistical-method review;
- clean-install evidence on Windows, macOS and Linux;
- documented first-report time and the five most common setup failures;
- no unresolved high-severity data-integrity defect.

No usage telemetry is collected. Adoption evidence comes from opt-in issue
reports, public examples and aggregate GitHub repository traffic.
