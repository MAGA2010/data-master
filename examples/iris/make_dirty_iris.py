#!/usr/bin/env python
"""Generate a deliberately messy iris table to exercise the data-master pipeline.

This is the regression fixture. It starts from clean sklearn iris data, then
injects exactly the problems the cleaning stage is supposed to detect:

  1. whitespace padding in the species label
  2. case inconsistency ("setosa" vs "Setosa")      -> merge_case_variants
  3. missing values in two numeric columns          -> never-automatic impute flag
  4. exact duplicate rows                           -> never-automatic dedupe flag
  5. a fully-null column (notes)                    -> drop_all_null_cols (auto)
  6. a mixed-type column: numeric strings + junk    -> coerce_numeric (auto)
  7. one impossible value (negative sepal length)   -> never-automatic drop flag

Note on (6): the junk token is "--", NOT "n/a". pandas' default NA token list
contains "n/a", so a "n/a" sentinel is silently parsed back to NaN and the column
arrives already-numeric, which would make this fixture test nothing.

Run:  python make_dirty_iris.py
Out:  iris_dirty.csv  (seeded; byte-identical on every run)
"""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.datasets import load_iris

HERE = Path(__file__).parent
SEED = 42
JUNK = "--"          # deliberately outside pandas' default NA token list
N_DUPES = 8


def main() -> int:
    iris = load_iris(as_frame=True)
    df = iris.frame.rename(columns={
        "sepal length (cm)": "sepal_length_cm",
        "sepal width (cm)": "sepal_width_cm",
        "petal length (cm)": "petal_length_cm",
        "petal width (cm)": "petal_width_cm",
        # NOT "target_id": this is a 3-level class code, not a row identifier.
        # Naming it *_id would make the profiler treat it as a unit key.
        "target": "species_code",
    })

    rng = np.random.default_rng(SEED)
    n = len(df)

    # 1 + 2. messy species labels: padding and case drift
    def mess_species(name: str, idx: int) -> str:
        if idx % 17 == 0:
            return f"  {name}  "
        if idx % 23 == 0:
            return name.capitalize()
        return name

    df["species"] = [mess_species(nm, i) for i, nm in enumerate(iris.target_names[iris.target])]

    # 3. realistic missing values (MAR: petal width missing more often for setosa)
    miss_pw = np.where(df["species"].str.strip().str.lower() == "setosa", 0.09, 0.03)
    df.loc[rng.random(n) < miss_pw, "petal_width_cm"] = np.nan
    df.loc[rng.random(n) < 0.04, "sepal_width_cm"] = np.nan

    # 4. exact duplicate rows (re-append real rows, so dedupe is genuinely lossless)
    df = pd.concat([df, df.iloc[rng.choice(n, size=N_DUPES, replace=False)]], ignore_index=True)

    # 5. fully-null column (carries no signal)
    df["notes"] = np.nan

    # 6. mixed-type column: formatted numeric strings with a few junk tokens.
    #    height_m is a DISTINCT quantity from sepal_length_cm, not a copy, so that
    #    coercing it does not create a redundant duplicate column.
    df["height_m"] = (df["sepal_length_cm"] * 0.7).round(2).map(lambda v: f"{v:.1f}")
    df.loc[rng.choice(len(df), size=5, replace=False), "height_m"] = JUNK

    # 7. one impossible value (a sepal length cannot be negative)
    df.loc[3, "sepal_length_cm"] = -1.0

    df = df.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    out = HERE / "iris_dirty.csv"
    df.to_csv(out, index=False)
    print(f"wrote {out}  ({df.shape[0]} rows x {df.shape[1]} cols)")
    print(f"  species levels (raw) : {sorted(df['species'].unique())}")
    print(f"  height_m sample      : {df['height_m'].head(4).tolist()}")
    print(f"  notes all-null       : {df['notes'].isna().all()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
