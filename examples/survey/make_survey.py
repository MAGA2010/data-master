"""Build the synthetic survey-data case-study fixture.

No real participant data exists here: every value is drawn from a seeded
generator. The fixture gathers the traps a survey export typically carries:

  respondent_id      zero-padded numeric identifiers ("0042") that must stay
                    text -- converting them would delete the padding and
                    merge distinct respondents
  age_years          a numeric column that uses -999 as its explicit "not
                    answered" code; -999 parses as a number, so the column
                    converts and the impossible value is then held for a
                    human decision rather than silently dropped
  satisfaction      labelled ordinal categories with genuine blank cells
  visit_frequency   labelled ordinal categories
  recommend         labelled binary categories
  minutes_spent     a numeric measurement with blanks and a real
                    satisfaction-dependent difference

The expected integrity behaviour is asserted in tests/test_survey_case.py;
this file and that test must change together.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SATISFACTION = ["Very dissatisfied", "Dissatisfied", "Neutral",
                "Satisfied", "Very satisfied"]
FREQUENCY = ["Never", "Rarely", "Sometimes", "Often"]


def build(n: int = 120, seed: int = 23) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # satisfaction drives the outcome: more satisfied respondents stay longer
    sat_level = rng.integers(0, len(SATISFACTION), n)
    base_minutes = np.array([6.0, 9.0, 13.0, 18.0, 24.0])[sat_level]
    minutes = np.clip(rng.normal(base_minutes, 4.0), 0.5, None)

    age = rng.integers(18, 80, n).astype(float)
    # the explicit missing code: 12 respondents declined to state their age
    age[rng.choice(n, size=12, replace=False)] = -999
    # blanks in the numeric measurement
    minutes[rng.choice(n, size=9, replace=False)] = np.nan
    # blanks scattered through the labelled columns
    sat = np.array([SATISFACTION[i] for i in sat_level], dtype=object)
    sat[rng.choice(n, size=7, replace=False)] = ""
    freq = np.array([FREQUENCY[i] for i in rng.integers(0, len(FREQUENCY), n)],
                    dtype=object)
    freq[rng.choice(n, size=5, replace=False)] = ""
    rec = np.array(["Yes" if p else "No"
                    for p in rng.random(n) < (0.35 + 0.12 * sat_level)],
                   dtype=object)

    return pd.DataFrame({
        "respondent_id": ["%04d" % i for i in range(1, n + 1)],
        "age_years": [("" if np.isnan(a) else "%d" % int(a)) for a in age],
        "satisfaction": list(sat),
        "visit_frequency": list(freq),
        "recommend": list(rec),
        "minutes_spent": [("" if np.isnan(m) else "%.1f" % m) for m in minutes],
    })


if __name__ == "__main__":
    out = build()
    # next to this script, not next to the caller's cwd: the fixture is an
    # input to tests/ and must not depend on where the generator ran from
    path = Path(__file__).resolve().parent / "survey_responses.csv"
    out.to_csv(path, index=False)
    print("wrote %s: %d rows x %d cols" % (path, *out.shape))
    for c in out.columns:
        print("  %-16s n_unique=%d n_blank=%d"
              % (c, out[c].nunique(), int((out[c] == "").sum())))
