"""Shared dtype / column-role helpers for data-master.

Centralised here because pandas changed its string dtype behaviour:
  - pandas < 3.0: string columns are `object`
  - pandas >= 3.0: string columns default to `str` (StringDtype)
  - a column can also be `string[python]` or `category`

Every script in this skill must classify columns through these helpers so the
behaviour is identical across pandas versions.
"""
from __future__ import annotations

import pathlib
import sqlite3
import warnings

import pandas as pd


def dtype_name(dtype) -> str:
    return str(dtype)


def is_numeric(dtype) -> bool:
    """True for int/float/Int64/Float64 etc. False for bool and datetime.

    The comparison is case-folded on purpose. pandas spells its nullable dtypes
    with a leading capital -- Int64, Float64, UInt64 -- and this skill's own
    coercion produces Float64. Matching case-sensitively classifies every
    coerced measurement as non-numeric, and the failure is silent: the column is
    not missing, it is simply skipped by whatever was looking for numbers.
    """
    d = str(dtype).lower()
    if d.startswith("bool") or "bool" in d:
        return False
    return any(t in d for t in ("int", "float", "uint"))


def is_bool(dtype) -> bool:
    d = str(dtype).lower()
    return d.startswith("bool") or d == "boolean"


def is_datetime(dtype) -> bool:
    d = str(dtype)
    return d.startswith("datetime") or d.startswith("timedelta") or d.startswith("period") or d == "date"


def is_string_like(dtype) -> bool:
    """True for object, str, string[...], and category-of-strings."""
    d = str(dtype)
    if d.startswith("object") or d.startswith("str") or d.startswith("string"):
        return True
    if d.startswith("category"):
        return True
    return False


def is_categorical(dtype) -> bool:
    """True only for explicit category dtype (not plain strings)."""
    return str(dtype).startswith("category")


def is_column_string(series: pd.Series) -> bool:
    """Runtime check on a Series (handles category-of-strings too)."""
    d = series.dtype
    if is_categorical(d):
        return True
    return is_string_like(d) and not is_numeric(d) and not is_datetime(d)


def column_role(series: pd.Series) -> str:
    """Return one of: numeric | binary | categorical | datetime | text."""
    d = series.dtype
    if is_datetime(d):
        return "datetime"
    if is_bool(d):
        return "binary"
    if is_numeric(d):
        n_unique = series.nunique(dropna=True)
        return "binary" if n_unique == 2 else "numeric"
    if is_categorical(d):
        n_unique = series.nunique(dropna=True)
        return "binary" if n_unique == 2 else "categorical"
    if is_string_like(d):
        n = len(series)
        n_unique = series.nunique(dropna=True)
        if n_unique == 2:
            return "binary"
        # long free text -> 'text'; short repeated values -> 'categorical'
        if n and (n_unique / n) > 0.7 and series.dropna().astype(str).str.len().mean() > 120:
            return "text"
        return "categorical"
    return "unknown"


def numeric_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if is_numeric(df[c].dtype)]


def categorical_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if column_role(df[c]) in ("categorical", "binary")
            and not is_numeric(df[c].dtype)]


def text_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if column_role(df[c]) == "text"]


def datetime_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if is_datetime(df[c].dtype)]


def string_like_columns(df: pd.DataFrame) -> list:
    """Every column whose values should get whitespace/unicode hygiene."""
    return [c for c in df.columns if is_string_like(df[c].dtype)]


def fold_case_map(series: pd.Series) -> tuple:
    """Collapse values that differ only by case/whitespace into a canonical form.

    Returns (mapped_series, info) where info is None when folding would not reduce
    cardinality. The canonical surface form is the MODAL original spelling within
    each fold group, tie-broken lexicographically, so "Setosa" survives and
    "setosa" folds into it, rather than the whole column being shouted into lower
    case.

    This is the single implementation used by both profile_tabular.py (to detect)
    and execute_cleaning.py (to apply), so a disclosure can never disagree with
    what was actually done. It is deliberately lossless: every original value is
    recoverable from info["merged_groups"], so the caller can always write a
    reverse map.

    This differs from the "lowercase" cleaning op, which stays never-automatic.
    Lowercasing rewrites every label and destroys capitalisation that may carry
    meaning; this only merges values that were already the same label written two
    ways.
    """
    work = series.astype("string")

    stripped = work.str.strip()
    folded = stripped.str.casefold()
    n_exact = int(stripped.nunique())
    n_fold = int(folded.nunique())
    if n_fold >= n_exact or n_exact == 0:
        return series, None

    canonical: dict = {}
    for key in folded.dropna().unique():
        counts = stripped[folded == key].value_counts()
        modal = counts[counts == counts.max()].index
        canonical[str(key)] = sorted(str(v) for v in modal)[0]

    mapped = stripped.map(
        lambda v: canonical.get(v.casefold(), v) if isinstance(v, str) else v
    ).astype("string")

    groups = []
    for key in sorted(canonical):
        variants = sorted(str(v) for v in stripped[folded == key].dropna().unique())
        if len(variants) > 1:
            groups.append({
                "canonical": canonical[key],
                "variants": variants,
                "count": int((folded == key).sum()),
            })
    info = {
        "n_exact_levels": n_exact,
        "n_after_casefold": n_fold,
        "n_merged_groups": len(groups),
        # The full list, not a sample: this map is what makes the fold reversible,
        # and a truncated map silently drops the variants needed to undo it.
        "merged_groups": groups,
        "canonical_rule": "modal original spelling, lexicographic tie-break",
    }
    return mapped, info


def residual_case_variants(series: pd.Series, min_len: int = 1) -> dict | None:
    """Detect values that differ only by case/whitespace.

    Thin wrapper over fold_case_map so detection and execution cannot drift apart.
    Returns None when collapsing case would not reduce cardinality.
    """
    s = series.dropna().astype(str)
    if len(s) == 0:
        return None
    if s.str.len().mean() < min_len:
        return None
    return fold_case_map(series)[1]


def hygiene_project(series: pd.Series) -> pd.Series:
    """Apply the AUTOMATIC string-hygiene ops in exactly the order
    cleaning_plan emits them, so a post-hygiene preview equals what execution
    will actually produce.

    Order (mirrors execute_cleaning ops):
        fix_unicode (NFC) -> strip -> collapse internal whitespace -> trim quotes

    Case folding is deliberately excluded: it is a separate op with its own
    decision record, so folding it in here would hide that decision from the
    reader of the profile.
    """
    import unicodedata

    s = series.astype("string")
    s = s.map(lambda v: unicodedata.normalize("NFC", v) if isinstance(v, str) else v)
    s = s.str.strip()
    s = s.str.replace(r"\s+", " ", regex=True).str.strip()
    s = s.str.strip('"').str.strip("'").str.strip()
    return s

# ---------------------------------------------------------------------------
# Type coercion: one implementation, shared by the profiler and the executor
# ---------------------------------------------------------------------------
# Design rule: a string column is converted to a number or a date ONLY when
# every non-null value parses. There is deliberately no "X% is enough" threshold.
#
# The threshold approach fails in the direction that matters. A column that is 90%
# numbers and 10% the literal string "unknown" passes a 70% gate, and coercion then
# converts those 10% into NaN. The result is a clean-looking numeric column in
# which a recorded, meaningful category has silently become a missing value, and
# nothing downstream can tell the difference. A lower threshold does not fix this,
# it only picks how many values to destroy. So the question is not "how much may I
# throw away" but "is anything thrown away at all".
#
# The same rule removes a whole class of disagreement: there is no second copy of
# a threshold in execute_cleaning to drift out of step with this one.

# Stripped automatically: thousands separators only. Currency and percent symbols
# are NOT stripped, because "$1,200" and "12%" need a human to choose between
# strip_symbol, divide_by_100 and leave_as_text -- three different numbers, and the
# file itself does not record which one was meant.
_THOUSANDS_SEP = ","
_MONEY_OR_RATE_CHARS = "$€£¥₹%"
# Used as pandas regex pattern strings, not compiled objects, so this module
# stays free of `re` and can be inlined into a standalone cleaning script.
_MONEY_OR_RATE_CLASS = "[" + _MONEY_OR_RATE_CHARS + "]"
_BLANK_OR_SENTINEL_PATTERN = r"^[\s\-_?.]*$"


def _probe_numeric(candidate: pd.Series) -> pd.Series:
    return pd.to_numeric(candidate, errors="coerce")


def numeric_view(series: pd.Series) -> tuple:
    """Parse a string column to numbers exactly the way execute will.

    Returns (converted, diag). converted is None when at least one non-null value
    fails to parse, and that answer is final: a non-numeric value can never be
    turned into the right number, so no flag or override may wave it through.

    profile_tabular stores diag in the profile and lets cleaning_plan decide from
    it; execute_cleaning calls this same function and writes converted when it is
    not None. One parser, one rule (all of them or none), and no room for the
    disclosure and the action to disagree.
    """
    s = series.astype("string")
    candidate = s.str.replace(_THOUSANDS_SEP, "", regex=False)
    num = _probe_numeric(candidate)

    non_null = int(s.notna().sum())
    parsed = int(num.notna().sum())
    failed = num.isna() & s.notna()
    all_parse = bool(non_null > 0 and int(failed.sum()) == 0)

    # ---- diagnostics that only a human can act on ----
    nn = s.dropna()
    if len(nn):
        idish = nn.str.replace(r"[\s()\-]", "", regex=True)
        lead = idish.str.match(r"^[+-]?0\d")
        n_lead = int(lead.sum())
        lead_frac = n_lead / len(nn)
        lead_samples = [str(v) for v in nn[lead].head(5)]
        money = nn.str.contains(_MONEY_OR_RATE_CLASS, regex=True)
        has_money = bool(money.any())
        money_samples = [str(v) for v in nn[money].head(5)]
    else:
        n_lead, lead_frac, lead_samples, has_money, money_samples = 0, 0.0, [], False, []

    # How much would parse once the currency/percent symbols were also removed?
    # Reported so the plan can tell "this is a money column" apart from "this is a
    # text column that happens to contain a few digits".
    if has_money and non_null:
        stripped = (s.str.replace(_MONEY_OR_RATE_CLASS, "", regex=True)
                     .str.replace(_THOUSANDS_SEP, "", regex=False))
        money_parse_fraction = int(_probe_numeric(stripped).notna().sum()) / non_null
    else:
        money_parse_fraction = None

    diag = {
        "n_non_null": non_null,
        "n_parsed": parsed,
        "n_failed": int(failed.sum()),
        "all_parse": all_parse,
        "parse_fraction_of_non_null": round(parsed / non_null, 4) if non_null else 0.0,
        "sample_failed": [str(v) for v in s[failed].dropna().head(5)],
        "failed_are_blank_or_sentinel": bool(
            failed.any()
            and s[failed].dropna().astype(str).str.match(_BLANK_OR_SENTINEL_PATTERN, na=False).all()
        ),
        "has_currency_or_percent": has_money,
        "currency_or_percent_samples": money_samples,
        "would_parse_after_symbol_strip": (
            round(money_parse_fraction, 4) if money_parse_fraction is not None else None
        ),
        "leading_zero_suspected_id": bool(n_lead > 0),
        "leading_zero_fraction": round(lead_frac, 4),
        "leading_zero_samples": lead_samples,
        "parser": "pd.to_numeric(errors='coerce') after removing thousands separators",
    }
    return (num if all_parse else None), diag


def date_view(series: pd.Series) -> tuple:
    """Parse a string column to timestamps exactly the way execute will.

    Returns (converted, diag) with the same all-or-nothing contract as
    numeric_view. Per-element format inference is unavoidable here (the executor
    must issue the identical call to stay in step), so it is disclosed as
    parser.format rather than left as an unstated dependency on dateutil.
    """
    s = series.astype("string")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ts = pd.to_datetime(s, errors="coerce")

    non_null = int(s.notna().sum())
    parsed = int(ts.notna().sum())
    failed = ts.isna() & s.notna()
    all_parse = bool(non_null > 0 and int(failed.sum()) == 0)

    diag = {
        "n_non_null": non_null,
        "n_parsed": parsed,
        "n_failed": int(failed.sum()),
        "all_parse": all_parse,
        "parse_fraction_of_non_null": round(parsed / non_null, 4) if non_null else 0.0,
        "sample_failed": [str(v) for v in s[failed].dropna().head(5)],
        "parser": "pd.to_datetime(errors='coerce'), per-element format inference",
    }
    return (ts if all_parse else None), diag


# ---------------------------------------------------------------------------
# Canonical tabular IO
# ---------------------------------------------------------------------------
#
# Every stage reads data through this one function. That is not tidiness, it is
# correctness: the reader decides the types, so two readers means two different
# datasets coming out of one file, and the difference is invisible downstream.
#
# read_mode="text" reads every cell as a string and lets this skill decide the
# types, so every conversion becomes an auditable op in the plan. pandas's
# default guessing is not a neutral fallback: it turns the postcode "02134"
# into 2134, which then collides with the genuinely different postcode "2134".
# By the time any audit runs, the zero and the evidence that a decision was made
# are both gone, and neither is recoverable from the output. JSON and Parquet
# are exempt -- their schemas state the types, so there is nothing to guess.


def source_spec(path, read_mode: str = "text") -> dict:
    """The minimum needed to re-read this file the way the run did."""
    p = pathlib.Path(path)
    ext = p.suffix.lower()
    declared = ext in (".parquet", ".json", ".jsonl", ".ndjson",
                       ".sqlite", ".sqlite3", ".db")
    return {
        "path": str(p),
        "extension": ext,
        "read_mode": "native" if declared else read_mode,
        "schema_declares_types": declared,
    }


def read_table(path, read_mode: str = "text") -> "pd.DataFrame":
    """Load a table without letting the reader silently reinterpret the data.

    read_mode
      text  (default) every cell arrives as a string.
      infer let pandas guess. Faster to write, unreviewable and irreversible.
    """
    p = pathlib.Path(path)
    ext = p.suffix.lower()
    if ext == ".parquet":
        return pd.read_parquet(p)
    if ext == ".json":
        return pd.read_json(p)
    if ext in (".jsonl", ".ndjson"):
        return pd.read_json(p, lines=True)
    if ext in (".sqlite", ".sqlite3", ".db"):
        conn = sqlite3.connect(str(p))
        try:
            tables = pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                conn,
            )["name"].tolist()
            if len(tables) != 1:
                raise ValueError(
                    "SQLite input must contain exactly one user table; found %d (%s). "
                    "Export one table to a supported tabular file before analysis."
                    % (len(tables), ", ".join(str(t) for t in tables[:20]))
                )
            table = tables[0].replace('"', '""')
            return pd.read_sql_query('SELECT * FROM "%s"' % table, conn)
        finally:
            conn.close()
    dt = str if read_mode == "text" else None
    if ext == ".csv":
        return pd.read_csv(p, dtype=dt, low_memory=False)
    if ext == ".tsv":
        return pd.read_csv(p, sep="\t", dtype=dt, low_memory=False)
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(p, dtype=dt)
    raise ValueError("Unsupported tabular extension: %s" % ext)


def write_table(df, path) -> None:
    """Write a table, routing on the extension so the output stays loadable."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix.lower()
    if ext in (".tsv", ".tab"):
        df.to_csv(p, sep="\t", index=False)
    elif ext == ".parquet":
        df.to_parquet(p, index=False)
    elif ext in (".xlsx", ".xlsm"):
        df.to_excel(p, index=False)
    elif ext == ".json":
        df.to_json(p, orient="records", date_format="iso")
    else:
        df.to_csv(p, index=False)


def dtype_manifest(df) -> dict:
    """Record the dtype of every column so a later stage can re-apply it."""
    return {str(c): str(df[c].dtype) for c in df.columns}


def apply_dtype_manifest(df, manifest) -> "pd.DataFrame":
    """Re-apply the dtypes a cleaning run already decided, instead of guessing.

    A CSV carries no type information, so every downstream stage that opens the
    cleaned file has to make the same choice the run recorded. Guessing again
    locally is how an identifier quietly becomes a float in the analysis after
    the report said it was text.
    """
    for col, dtype in (manifest or {}).items():
        if col not in df.columns:
            continue
        try:
            df[col] = df[col].astype(dtype)
        except (TypeError, ValueError):
            # A manifest that no longer fits the data is a finding, not a crash.
            # Staying text is the only non-destructive fallback.
            df[col] = df[col].astype(str)
    return df


def find_cleaning_run(path):
    """Locate the cleaning_run.json that produced this cleaned table."""
    here = pathlib.Path(path).resolve().parent
    for candidate in (here / "cleaning_run.json",):
        if candidate.exists():
            return candidate
    return None


def load_cleaned(path, run_json=None):
    """Load a cleaned table with the types the audited run decided.

    A CSV carries no type information, so every stage that opens a cleaned file
    has to make the same choice again. Making it locally is how an identifier
    quietly becomes an integer in the analysis after the report said it was text:
    the postcode "02134" is reported as 2134, and every reader of the figure
    believes the file held 2134.

    With a manifest the types are recorded facts. Without one the types are a
    guess, so they are labelled as a guess rather than presented as fact.

    Returns (frame, provenance).
    """
    import json as _json

    run_path = pathlib.Path(run_json) if run_json else find_cleaning_run(path)
    manifest = {}
    if run_path is not None:
        try:
            manifest = (_json.loads(pathlib.Path(run_path).read_text(encoding="utf-8"))
                        .get("dtype_manifest") or {})
        except Exception:
            manifest = {}

    if manifest:
        df = read_table(path, read_mode="text")
        df = apply_dtype_manifest(df, manifest)
        return df, {
            "dtype_source": "cleaning_run.json",
            "dtype_manifest_path": str(run_path),
            "n_columns_typed_from_manifest": len(manifest),
            "read_mode": "text",
        }

    df = read_table(path, read_mode="infer")
    return df, {
        "dtype_source": "pandas inference (NO cleaning_run.json found)",
        "dtype_manifest_path": None,
        "n_columns_typed_from_manifest": 0,
        "read_mode": "infer",
        "warning": ("column types were guessed, not audited; identifiers with "
                    "leading zeros or formatting cannot survive this"),
    }
