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
| Deliverable exports | `report.html` is a self-contained rendering of `report.md`; altered or missing exports fail verification | The Markdown subset the reports generate |
| Held-conversion fixtures | Date-versus-number ambiguity and survey missing-codes surface as evidenced decisions, never silent conversions | One fixture per ambiguity shape |
| Distribution | Wheel installation outside the checkout, console entry point, bundled resources and demo | Windows, Linux and macOS, Python 3.13 |
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
| ZCode 3.14.4 (Windows) | Verified: skill installed through `skill install --target`, discovered by a fresh client session, and one full analysis (doctor -> analyze -> SUBMISSION-READY audit -> `verify --json` valid) completed from a skill invocation; see [`docs/VALIDATION.md`](docs/VALIDATION.md) |
| Claude Code, Cursor, Gemini CLI | Candidate Agent Skills compatibility; not yet claimed as verified |
| macOS | Distribution job runs in CI on Python 3.13; see [`docs/VALIDATION.md`](docs/VALIDATION.md) |

## Public acceptance targets

Before calling the project `1.0`, the project seeks:

- 20 external datasets completed from installation through artifact verification;
- at least one independent statistical-method review;
- clean-install evidence on Windows, macOS and Linux;
- documented first-report time and the five most common setup failures;
- no unresolved high-severity data-integrity defect.

No usage telemetry is collected. Adoption evidence comes from opt-in issue
reports, public examples and aggregate GitHub repository traffic.
