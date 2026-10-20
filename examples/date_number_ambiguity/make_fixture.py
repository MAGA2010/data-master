"""Build the date-versus-number ambiguity benchmark fixture.

The single interesting column, `session_stamp`, holds bare 8-digit integers
such as 20240115. Every value parses as an integer AND as a YYYYMMDD date,
and the file itself carries no hint of which one the author meant:

  - as a date, 20240115 is 2024-01-15 and the column orders the visits;
  - as a number, 20240115 is just an integer reading or run counter.

A cleaner that guesses silently produces a confident analysis of the wrong
variable. data-master must hold the conversion, record the ambiguity with
evidence, and preserve the original text until a human answers.

The expected behaviour is asserted in tests/test_date_number_ambiguity.py;
this file and that test must change together.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SUBJECTS = ["P%03d" % i for i in range(1, 9)]


def build(n: int = 48, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # eight subjects, six rows each: every group keeps at least two
    # observations, so the pipeline reaches a real (unit-gated) comparison
    # instead of stopping at an estimability refusal
    subj = [SUBJECTS[i] for i in rng.integers(0, len(SUBJECTS), n)]
    while min(pd.Series(subj).value_counts()) < 2:
        subj = [SUBJECTS[i] for i in rng.integers(0, len(SUBJECTS), n)]
    # every stamp is a real calendar day so both readings stay plausible;
    # spanning several months keeps the values from looking like a counter
    # that merely starts high
    base = np.datetime64("2024-01-02")
    days = np.concatenate([
        rng.integers(0, 28, 18),      # January
        rng.integers(28, 56, 18),     # February
        rng.integers(56, 91, n - 36), # March
    ])
    stamps = [str(base + np.timedelta64(int(d), "D")).replace("-", "")
              for d in days]
    # genuine per-subject differences: the report can then state a real
    # separation instead of a null result, keeping the case study about the
    # conversion hold rather than about estimability
    offset = {s: 28.0 * i for i, s in enumerate(SUBJECTS)}
    return pd.DataFrame({
        "subject_id": subj,
        "session_stamp": stamps,
        "latency_s": [f"{v:.2f}" for v in np.clip(
            rng.normal(310, 25, n) + [offset[s] for s in subj], 120, None)],
    })


if __name__ == "__main__":
    out = build()
    # next to this script, not next to the caller's cwd: the fixture is an
    # input to tests/ and must not depend on where the generator ran from
    path = Path(__file__).resolve().parent / "session_export.csv"
    out.to_csv(path, index=False)
    print("wrote %s: %d rows x %d cols" % (path, *out.shape))
    print(out["session_stamp"].head(3).tolist(), "...")
