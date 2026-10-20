#!/usr/bin/env python
"""Execute the cleaning plan deterministically, and emit a reproducible script + report.

Reads
-----
--in     raw data file (csv / tsv / xlsx / parquet / json / jsonl)
--plan   cleaning_plan.json produced by cleaning_plan.py

Writes (into --out)
-------------------
cleaned.csv          the cleaned data (additive-only: the raw file is never touched)
clean_<slug>.py      a standalone script that reproduces cleaned.csv byte-for-byte
cleaning_report.md   human-readable provenance for every decision
cleaning_run.json    machine-checkable evidence consumed by validate_clean.py

Contract
--------
The plan is the gate. Exactly the ops in plan["auto_actions"] are executed, in
order. Nothing else runs. Ops listed in plan["never_automatic_flags"] are NOT
executed; they are only surfaced as decisions requiring a human.

--only / --skip narrow that set for staged re-runs; every withheld op is written
into cleaning_run.json under "withheld" so an auditor can see what was held back.

Usage
-----
    python execute_cleaning.py --in data/sales.csv --plan outputs/cleaning_plan.json --out cleaned/
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import unicodedata
import warnings
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dm_types import (  # noqa: E402
    date_view, dtype_manifest, fold_case_map, hygiene_project, is_string_like,
    numeric_view, read_table, source_spec, write_table,
)


# --------------------------------------------------------------------------
# merge_case_variants accumulates its forward map here so main() can persist an
# exactly reversible record. Kept module-level (not df.attrs) because pandas does
# not guarantee attrs survive row drops or categorical casts.
# --------------------------------------------------------------------------
_CASE_MERGE_MAPS: List[Dict[str, Any]] = []


# ---------------- string-hygiene ops (lossless) ----------------

def _str_ops(s: pd.Series) -> pd.Series:
    """View a string-like column as a nullable string Series, preserving NA.

    Works for object, str (pandas>=3), string[python] and category-of-strings.
    Never coerces NA to the literal text 'nan'.
    """
    return s.astype("string")


def op_strip_whitespace(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            df[c] = _str_ops(df[c]).str.strip()
    return df


def op_collapse_whitespace(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            df[c] = _str_ops(df[c]).str.replace(r"\s+", " ", regex=True).str.strip()
    return df


def op_fix_unicode(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            df[c] = _str_ops(df[c]).map(
                lambda v: unicodedata.normalize("NFC", v) if isinstance(v, str) else v
            )
    return df


def op_trim_paired_quotes(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            df[c] = _str_ops(df[c]).str.strip('"').str.strip("'").str.strip()
    return df


def op_merge_case_variants(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """Fold labels that differ ONLY by case/whitespace into one canonical label.

    Lossless canonicalisation, not a semantic edit: no genuinely distinct label is
    ever merged. The folding rule lives in dm_types.fold_case_map so that the
    disclosure in cleaning_plan.md is computed by the same code that runs here.

    The forward map is recorded in cleaning_run.json under
    "case_variant_merge_map", which makes the operation byte-for-byte reversible.

    Contrast with the "lowercase" op, which stays never-automatic: lowercasing
    *rewrites every label* and destroys capitalisation that may carry meaning.
    """
    for c in cols:
        if c not in df.columns or not is_string_like(df[c].dtype):
            continue
        was_categorical = str(df[c].dtype).startswith("category")

        mapped, info = fold_case_map(df[c])
        if info is None:
            continue  # nothing would merge

        if was_categorical:
            df[c] = pd.Categorical(mapped,
                                  categories=sorted(str(v) for v in mapped.dropna().unique()))
        else:
            df[c] = mapped

        _CASE_MERGE_MAPS.append({"column": c, **info})
    return df

# ---------------- structural / dtype ops ----------------

def op_normalize_dtypes(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """Best-effort dtype inference: low-cardinality string -> category."""
    for c in cols:
        if c not in df.columns or not is_string_like(df[c].dtype):
            continue
        if str(df[c].dtype).startswith("category"):
            continue
        s = _str_ops(df[c])
        n = max(len(s), 1)
        uniq = int(s.nunique(dropna=True))
        if 2 <= uniq and uniq / n <= 0.05:
            df[c] = s.astype("category")
    return df


def op_coerce_numeric(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            # The same call the profiler made when it put this column in the plan.
            # numeric_view returns None unless every non-null value parses, so the
            # op can neither fire on a column the plan never promised to convert
            # nor convert only part of one it did. The plan holds the decision;
            # this is the refusal to act on a plan that has become incoherent.
            num, _diag = numeric_view(_str_ops(df[c]))
            if num is not None:
                df[c] = num
    return df


def op_coerce_dates(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            ts, _diag = date_view(_str_ops(df[c]))
            if ts is not None:
                df[c] = ts
    return df

def op_drop_all_null_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    return df.dropna(axis=1, how="all")


def op_drop_all_null_rows(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    return df.dropna(axis=0, how="all")


def op_rename_columns_append_cleaned(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """No-op: original column names are preserved so joins to other tables keep working."""
    return df


# ---------------- never-automatic implementations ----------------
# Registered so an explicit user flag can promote them. Nothing here runs unless
# the plan lists it in auto_actions, which only happens when the user opted in.

def _impute(df: pd.DataFrame, cols: List[str], method: str) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            continue
        s = df[c]
        if method in ("mean", "median") and pd.api.types.is_numeric_dtype(s):
            fill = s.mean() if method == "mean" else s.median()
            if pd.notna(fill):
                df[c] = s.fillna(fill)
        elif method == "mode" and is_string_like(s.dtype):
            modes = s.dropna().mode()
            if len(modes):
                df[c] = s.fillna(modes.iloc[0])
        # "mice" is intentionally a no-op here: MICE needs a model, a seed and a
        # missingness-mechanism argument, all of which are human decisions.
    return df


def _impute_knn(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    try:
        from sklearn.impute import KNNImputer
    except ImportError:
        return df
    present = [c for c in cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    if not present:
        return df
    block = df[present]
    if not block.isna().any().any():
        return df
    df[present] = KNNImputer(n_neighbors=5).fit_transform(block)
    return df


def _dedupe_key(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    present = [c for c in cols if c in df.columns]
    return df.drop_duplicates(subset=present).reset_index(drop=True) if present else df


def _drop_impossible(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """Drop non-positive values in columns whose name marks them as a positive measure."""
    positive_markers = ("length", "width", "height", "mass", "weight", "size",
                        "depth", "count", "age", "temp", "temperature", "area",
                        "volume", "distance", "duration")
    for c in cols:
        if c not in df.columns or not pd.api.types.is_numeric_dtype(df[c]):
            continue
        if any(m in str(c).lower() for m in positive_markers):
            df = df[(df[c] > 0) | df[c].isna()]
    return df.reset_index(drop=True)


def _coerce_bool(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    truthy = {"true", "yes", "y", "1", "t", "是", "真"}
    falsy = {"false", "no", "n", "0", "f", "否", "假"}
    for c in cols:
        if c not in df.columns or not is_string_like(df[c].dtype):
            continue
        norm = _str_ops(df[c]).str.strip().str.casefold()
        if len(norm) and bool(norm.dropna().isin(truthy | falsy).all()):
            df[c] = norm.map(lambda v: None if pd.isna(v) else (v in truthy)).astype("boolean")
    return df


def _flag_outliers(df: pd.DataFrame, cols: List[str], method: str) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns or not pd.api.types.is_numeric_dtype(df[c]):
            continue
        s = df[c]
        mu, sd = s.mean(), s.std(ddof=0)
        if not sd or np.isnan(sd):
            continue
        df[f"outlier_z_{c}"] = ((s - mu) / sd).abs() > 3
    return df


def _winsorize(df: pd.DataFrame, cols: List[str], q: float) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns or not pd.api.types.is_numeric_dtype(df[c]):
            continue
        s = df[c]
        df[c] = s.clip(s.quantile(q), s.quantile(1 - q))
    return df


def _onehot(df: pd.DataFrame, cols: List[str], max_card: int) -> pd.DataFrame:
    target = [c for c in cols
              if c in df.columns and int(df[c].nunique(dropna=True)) <= max_card]
    return pd.get_dummies(df, columns=target, dummy_na=False) if target else df


def _label_encode(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            df[c] = df[c].astype("category").cat.codes
    return df


def _zscore(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            s = df[c]
            mu, sd = s.mean(), s.std(ddof=0)
            if sd and not np.isnan(sd):
                df[c] = (s - mu) / sd
    return df


def _minmax(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            s = df[c]
            lo, hi = s.min(), s.max()
            if hi > lo:
                df[c] = (s - lo) / (hi - lo)
    return df


def _lower(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """NEVER AUTOMATIC. Rewrites every label; capitalisation may carry meaning."""
    for c in cols:
        if c in df.columns and is_string_like(df[c].dtype):
            df[c] = _str_ops(df[c]).str.lower()
    return df


def _comma_decimal(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """NEVER AUTOMATIC. "1,234" is ambiguous: thousands separator or decimal comma."""
    for c in cols:
        if c not in df.columns or not is_string_like(df[c].dtype):
            continue

        def fix(v):
            if not isinstance(v, str) or "," not in v or "." in v or v.count(",") != 1:
                return v
            a, b = v.split(",")
            if a.replace("-", "").isdigit() and b.isdigit() and len(b) <= 3:
                return f"{a}.{b}"
            return v

        df[c] = _str_ops(df[c]).map(fix)
    return df


def _drop_high_null_rows(df: pd.DataFrame, cols: List[str], threshold: float = 0.05) -> pd.DataFrame:
    if not len(df.columns):
        return df
    k = max(1, int(threshold * len(df.columns)))
    return df.dropna(thresh=k).reset_index(drop=True)


OP_REGISTRY = {
    # ---- automatic, lossless ----
    "strip_whitespace": op_strip_whitespace,
    "collapse_whitespace": op_collapse_whitespace,
    "fix_unicode": op_fix_unicode,
    "trim_paired_quotes": op_trim_paired_quotes,
    "merge_case_variants": op_merge_case_variants,
    # ---- automatic, structural ----
    "normalize_dtypes": op_normalize_dtypes,
    "coerce_numeric": op_coerce_numeric,
    "coerce_dates": op_coerce_dates,
    "drop_all_null_cols": op_drop_all_null_cols,
    "drop_all_null_rows": op_drop_all_null_rows,
    "rename_columns_append_cleaned": op_rename_columns_append_cleaned,
    # ---- never-automatic: reachable only via an explicit user flag in the plan ----
    "impute_mean": lambda df, cols: _impute(df, cols, "mean"),
    "impute_median": lambda df, cols: _impute(df, cols, "median"),
    "impute_mode": lambda df, cols: _impute(df, cols, "mode"),
    "impute_mice": lambda df, cols: _impute(df, cols, "mice"),
    "impute_knn": lambda df, cols: _impute_knn(df, cols),
    "dedupe_exact": lambda df, cols: df.drop_duplicates().reset_index(drop=True),
    "dedupe_key": lambda df, cols: _dedupe_key(df, cols),
    "drop_high_null_rows": lambda df, cols: _drop_high_null_rows(df, cols),
    "drop_impossible": lambda df, cols: _drop_impossible(df, cols),
    "coerce_bool": lambda df, cols: _coerce_bool(df, cols),
    "flag_outliers_zscore": lambda df, cols: _flag_outliers(df, cols, "z"),
    "winsorize": lambda df, cols: _winsorize(df, cols, 0.05),
    "onehot_encode": lambda df, cols: _onehot(df, cols, 10),
    "label_encode": lambda df, cols: _label_encode(df, cols),
    "normalize_zscore": lambda df, cols: _zscore(df, cols),
    "normalize_minmax": lambda df, cols: _minmax(df, cols),
    "lowercase": lambda df, cols: _lower(df, cols),
    "comma_decimal_to_dot": lambda df, cols: _comma_decimal(df, cols),
}

# Ops importable by name into the generated reproducibility script.
EXPORTED_OP_NAMES = [
    "op_strip_whitespace", "op_collapse_whitespace", "op_fix_unicode",
    "op_trim_paired_quotes", "op_merge_case_variants", "op_normalize_dtypes",
    "op_coerce_numeric", "op_coerce_dates", "op_drop_all_null_cols",
    "op_drop_all_null_rows", "op_rename_columns_append_cleaned",
]


# ---------------- io helpers ----------------

def profile_read_mode(src: Path) -> str:
    """Plans written before read_mode was recorded still have a correct answer.

    Formats whose schema states the types are read natively; everything else is
    read as text, which is the only mode where the cleaning decisions are the
    ones that end up on disk.
    """
    return "infer" if source_spec(src)["schema_declares_types"] else "text"


# Ops that may legitimately rewrite a cell. Listed explicitly so that an op
# nobody has thought about yet is audited rather than silently exempted.
HYGIENE_OPS = frozenset({
    "strip_whitespace", "collapse_whitespace", "fix_unicode", "trim_paired_quotes",
})

VALUE_CHANGING_OPS = frozenset({
    "merge_case_variants", "coerce_numeric", "coerce_dates",
    "impute", "impute_knn", "winsorize", "zscore", "minmax",
    "lowercase", "comma_decimal", "coerce_bool", "label_encode",
    "onehot_encode", "drop_impossible", "flag_outliers",
})


def converting_columns(applied: List[Dict[str, Any]]) -> List[str]:
    """Columns an operation was allowed to rewrite, and so cannot be audited.

    The blanket string-hygiene ops run over every text column; they are replayed
    exactly instead, by hygiene_project, which is the same projection the ops
    perform. Beyond those, only the ops listed above may change what a cell says.
    normalize_dtypes is deliberately absent: turning text into a category is a
    storage choice, and the values it stores must still match the raw file.
    """
    return sorted({c for a in applied
                   if a.get("op") in VALUE_CHANGING_OPS
                   for c in a.get("columns", [])})


def audit_untouched_columns(raw: pd.DataFrame, clean: pd.DataFrame,
                            touched: List[str]) -> Dict[str, Any]:
    """No column may gain a value that the raw file did not contain.

    This is the check that catches a reader quietly reinterpreting the file
    behind the plan's back. It compares the raw file against the cleaned output
    in text space, so a type guess made while loading -- the postcode "02134"
    becoming 2134 -- shows up as a brand new value in a column that no
    operation ever named.

    Values may legitimately disappear: a row-drop op removes them. A value may
    never appear, because no cleaning step invents data. When the row count is
    unchanged the comparison is exact in both directions, which also catches a
    value being silently altered into a different one.
    """
    touched_set = set(touched)
    same_rows = len(raw) == len(clean)
    violations: List[Dict[str, Any]] = []
    checked: List[str] = []

    def present_values(series: pd.Series) -> List[str]:
        # pd.NA and np.nan are both "no value"; `v == v` cannot test for them
        # because pd.NA refuses a boolean context, and a text column with
        # blanks crashes that check outright
        return [str(v) for v in series.tolist()
                if v is not None and not pd.isna(v)]

    for col in raw.columns:
        if col in touched_set or col not in clean.columns:
            continue
        checked.append(str(col))
        # Replay the automatic hygiene the plan promised, so the comparison is
        # against the state the ops are supposed to produce, not the raw bytes.
        projected = hygiene_project(raw[col])
        raw_vals = present_values(projected)
        cln_vals = present_values(clean[col])
        raw_counter = Counter(raw_vals)
        cln_counter = Counter(cln_vals)
        introduced = sorted((cln_counter - raw_counter).elements())
        missing = sorted((raw_counter - cln_counter).elements())
        if introduced or (same_rows and missing):
            violations.append({
                "column": str(col),
                "n_values_introduced": len(introduced),
                "sample_introduced": introduced[:5],
                "n_values_missing": len(missing),
                "sample_missing": missing[:5],
                "row_count_unchanged": same_rows,
            })

    return {
        "passed": not violations,
        "reason": ("every column no operation named kept exactly its raw values"
                   if not violations else
                   "a value appeared in a column no operation was asked to change"),
        "columns_checked": len(checked),
        "columns_violating": [v["column"] for v in violations],
        "violations": violations[:20],
    }


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _locate_skill_scripts() -> List[str]:
    """Candidate directories that hold execute_cleaning.py, most specific first."""
    cands: List[str] = []
    env = os.environ.get("DATA_MASTER_SCRIPTS")
    if env:
        cands.append(env)
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        c = parent / "scripts"
        if (c / "execute_cleaning.py").exists():
            cands.append(str(c))
    return cands


def _collect_inline(fn, seen: set, out: List[str], literals: Dict[str, Any]) -> bool:
    """Depth-first collect the source of fn plus everything it needs.

    Returns False when a dependency cannot be represented as standalone source,
    which tells the caller to fall back to importing from the skill directory.
    """
    if fn.__name__ in seen:
        return True
    seen.add(fn.__name__)
    # Names must be resolved in the globals of the module that DEFINES the
    # function, not in this module's globals. The ops here call helpers that live
    # in dm_types, and those helpers read module constants of their own (the
    # thousands separator, the currency character class). Looking them up here
    # finds nothing, the constant is silently dropped from the emitted header, and
    # the generated script dies with a NameError on the first row.
    own = getattr(fn, "__globals__", {})
    for dep in fn.__code__.co_names:
        g = own.get(dep, globals().get(dep))
        if g is None or inspect.ismodule(g):
            continue                      # builtin, or an import the header provides
        if inspect.isfunction(g):
            if not _collect_inline(g, seen, out, literals):
                return False
        elif inspect.isclass(g):
            # A class such as pathlib.Path is reproduced through its own module,
            # so the emitted script does not depend on the header's import list
            # happening to cover whatever the ops happen to touch.
            literals.setdefault(
                dep, "__import__(%r).%s" % (g.__module__, g.__qualname__))
        elif isinstance(g, (list, dict, tuple, set, frozenset)):
            literals.setdefault(dep, json.dumps(g, ensure_ascii=False))
        elif isinstance(g, bool):
            # bool is an int subclass, so it must be tested first: json.dumps(True)
            # yields the bare token "true", which is not valid Python in the
            # generated header.
            literals.setdefault(dep, repr(g))
        elif isinstance(g, (int, float)):
            literals.setdefault(dep, repr(g))
        elif isinstance(g, str):
            literals.setdefault(dep, json.dumps(g, ensure_ascii=False))
        elif g is None:
            literals.setdefault(dep, "None")
        else:
            return False
    out.append(inspect.getsource(fn).rstrip())
    return True


def emit_reproducible_script(plan: Dict, src: Path, out_csv: Path,
                             script_path: Path, executed: List[Dict[str, Any]],
                             read_mode: str = "text") -> None:
    """Write a standalone script that reproduces cleaned.csv from the raw file.

    Operations are inlined as source so the artifact works with no skill
    installed. Anything that cannot be inlined falls back to importing from the
    skill directory, located via DATA_MASTER_SCRIPTS or an upward search.

    Usage:
        python clean_<slug>.py [output.csv]
    """
    seen: set = set()
    sources: List[str] = []
    literals: Dict[str, Any] = {}
    fn_refs: List[str] = []
    fallback: List[str] = []
    unresolvable: List[str] = []
    fallback_keys: List[str] = []

    # The reader is part of the result, not part of the setup. A standalone
    # script that re-reads the raw file with pandas defaults would reproduce the
    # exact data loss the cleaning avoided, so read_table travels with the ops.
    _collect_inline(read_table, seen, sources, literals)

    for op in executed:
        fn = OP_REGISTRY[op["op"]]
        if inspect.isfunction(fn):
            if _collect_inline(fn, seen, sources, literals):
                fn_refs.append(repr(op["op"]) + ": " + fn.__name__)
            else:
                unresolvable.append(op["op"])
        else:
            unresolvable.append(op["op"])

    # registry lambdas wrap one module-level function; rebuild the wrapper source
    for name in unresolvable:
        fn = OP_REGISTRY[name]
        if inspect.isfunction(fn) or fn is None:
            continue
        lglobals = getattr(fn, "__globals__", {})
        deps = [d for d in getattr(getattr(fn, "__code__", None), "co_names", ())
                if inspect.isfunction(lglobals.get(d))]
        consts = [c for c in fn.__code__.co_consts if isinstance(c, str)]
        if len(deps) == 1 and len(consts) == 1:
            if _collect_inline(lglobals[deps[0]], seen, sources, literals):
                fn_refs.append(f"{name!r}: lambda df, cols: {deps[0]}(df, cols, {consts[0]!r})")
                continue
        fn_refs.append(f"{name!r}: None")
        fallback_keys.append(name)

    body: List[str] = [
        "#!/usr/bin/env python",
        "# AUTO-GENERATED by data-master/execute_cleaning.py -- do not edit by hand.",
        f"# Raw source : {src}",
        f"# Plan       : {plan.get('source', '')}",
        f"# Default out: {out_csv}",
        "#",
        "# Running this on the same raw file must reproduce cleaned.csv byte-for-byte.",
        "#   python " + script_path.name + " [output.csv]",
        "from __future__ import annotations",
        "",
        "import json, os, pathlib, sys, unicodedata, warnings",
        "import numpy as np",
        "import pandas as pd",
        "",
    ]
    if any(lit is not None for lit in literals.values()):
        # Every value already stored in the literals dict must be a valid Python
        # source expression: it is written verbatim above the inlined ops.
        body += ["# ---- module state ----"] + [f"{k} = {v}" for k, v in literals.items()] + [""]

    if sources:
        body += ["# ---- operations (inlined from execute_cleaning.py) ----"] + sources + [""]

    header = ", ".join(fn_refs)
    body += [f"FN = {{{header}}}", ""]

    if fallback_keys:
        body += [
            "# ---- fallback: ops that cannot be inlined ----",
            "def _resolve_skill_scripts():",
            "    cands = []",
            "    env = os.environ.get('DATA_MASTER_SCRIPTS')",
            "    if env:",
            "        cands.append(env)",
            "    here = pathlib.Path(__file__).resolve().parent",
            "    for parent in [here, *here.parents]:",
            "        c = parent / 'scripts'",
            "        if (c / 'execute_cleaning.py').exists():",
            "            cands.append(str(c))",
            "    return cands",
            "",
            "def _load(name):",
            "    for d in _resolve_skill_scripts():",
            "        if d not in sys.path:",
            "            sys.path.insert(0, d)",
            "    import execute_cleaning",
            "    return getattr(execute_cleaning, 'OP_REGISTRY')[name]",
            "",
        ]
        for key in fallback_keys:
            body.append(f"FN[{key!r}] = _load({key!r})")

    body += [
        "",
        "OPS = " + json.dumps(
            [(o["id"], o["op"], o.get("columns", [])) for o in executed],
            indent=4, ensure_ascii=False,
        ),
        "",
        "def _resolve(spec, *bases):",
        "    q = pathlib.Path(spec)",
        "    if q.is_absolute():",
        "        return q",
        "    for b in bases:",
        "        cand = pathlib.Path(b) / q",
        "        if cand.exists():",
        "            return cand.resolve()",
        "    return q",
        "",
        "_HERE = pathlib.Path(__file__).resolve().parent",
        "_BASES = (_HERE, *_HERE.parents, pathlib.Path.cwd())",
        f"RAW = _resolve({str(Path(src).resolve())!r}, *_BASES)",
        f"_DEFAULT_OUT = _resolve({str(Path(out_csv).resolve())!r}, *_BASES)",
        "OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_OUT",
        "",
        f"DF = read_table(RAW, read_mode={read_mode!r})",
        "applied = []",
        "for op_id, op_name, cols in OPS:",
        "    DF = FN[op_name](DF, cols)",
        "    applied.append(op_id)",
        "OUT.parent.mkdir(parents=True, exist_ok=True)",
        "DF.to_csv(OUT, index=False)",
        "print('cleaned rows:', len(DF))",
        "print('applied ops  :', applied)",
        "print('output       :', OUT)",
    ]
    script_path.write_text("\n".join(body) + "\n", encoding="utf-8")


def verify_reproducible(clean_py: Path, expected_hash: str) -> Dict[str, Any]:
    """Re-run the generated script in a fresh interpreter and compare the hash.

    This is the strongest available check that a cleaning run is auditable: if a
    reviewer cannot regenerate the identical bytes from the raw file, nothing
    else in the report can be trusted.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "repro.csv"
        proc = subprocess.run(
            [sys.executable, str(Path(clean_py).resolve()), str(target)],
            capture_output=True, text=True, cwd=td,
        )
        if proc.returncode != 0:
            return {"passed": False, "reason": "generated script exited non-zero",
                    "returncode": proc.returncode,
                    "stderr": proc.stderr.strip()[-2000:]}
        if not target.exists():
            return {"passed": False, "reason": "generated script produced no output"}
        got = _file_hash(target)
    passed = got == expected_hash
    return {
        "passed": passed,
        "reason": "hash matches" if passed else "regenerated hash differs",
        "expected_hash": expected_hash,
        "regenerated_hash": got,
    }


# ---------------- reporting ----------------

def split_flags(flags: List[Dict[str, Any]]) -> tuple:
    """INFO entries are already-applied disclosures; the rest are open decisions."""
    return ([f for f in flags if f.get("severity") != "INFO"],
            [f for f in flags if f.get("severity") == "INFO"])


# How many merge groups to print before pointing at cleaning_run.json. The JSON
# always holds every group, because that file is what makes the fold reversible;
# only this table is bounded.
_CASE_TABLE_ROWS = 10


def build_report(src: Path, n_raw: int, n_clean: int, raw_hash: str, clean_hash: str,
                 script_name: str, applied: List[Dict[str, Any]],
                 case_maps: List[Dict[str, Any]], plan: Dict[str, Any],
                 withheld: List[Dict[str, Any]],
                 col_before: List[str], col_after: List[str]) -> str:
    all_flags = plan.get("never_automatic_flags", [])
    decisions, disclosures = split_flags(all_flags)
    decisions = [f for f in decisions if not f.get("resolved")]
    resolved = [f for f in all_flags if f.get("resolved")]

    L: List[str] = [
        f"# Cleaning Report — {src.name}",
        "",
        "| | |",
        "|---|---|",
        f"| Source | `{src}` |",
        f"| Rows | {n_raw} → **{n_clean}** ({n_clean - n_raw:+d}) |",
        f"| Columns | {len(col_before)} → **{len(col_after)}** |",
        f"| Raw sha256 | `{raw_hash}` |",
        f"| Cleaned sha256 | `{clean_hash}` |",
        f"| Reproducible script | `{script_name}` |",
        f"| Ops applied | {len(applied)} |",
        f"| Decisions pending | {len(decisions)} |",
        f"| Decisions answered via answers file | {len(resolved)} |",
        "",
        "> The raw file is never modified. Everything below is additive.",
        "",
        "## 1. Applied operations",
        "",
        "| ID | Op | Columns | Severity | Rule source | Rows |",
        "|---|---|---|---|---|---|",
    ]
    for op in applied:
        cols = ", ".join(f"`{c}`" for c in op["columns"]) or "—"
        L.append(
            f"| `{op['id']}` | `{op['op']}` | {cols} | {op['severity']} "
            f"| {op['rule_source']} | {op['n_before']}→{op['n_after']} |"
        )

    L += ["", "## 2. Case-variant canonicalisation", ""]
    if case_maps:
        L.append("Labels differing only by case/whitespace were folded. "
                 "No distinct category was merged; the map below reverses it exactly.")
        L.append("")
        for m in case_maps:
            shown = m.get("merged_groups") or []
            L.append(f"### `{m['column']}` — {m['n_exact_levels']} → "
                     f"{m['n_after_casefold']} levels ({m['n_merged_groups']} groups merged)")
            L.append("")
            L.append("| Canonical | Folded variants | n |")
            L.append("|---|---|---|")
            for g in shown[:_CASE_TABLE_ROWS]:
                variants = ", ".join(f"`{v}`" for v in g["variants"] if v != g["canonical"])
                L.append(f"| `{g['canonical']}` | {variants} | {g['count']} |")
            if len(shown) > _CASE_TABLE_ROWS:
                L.append(f"| … | {len(shown) - _CASE_TABLE_ROWS} further groups, "
                         f"see `case_variant_merge_map` in cleaning_run.json | |")
            L.append("")
            L.append(f"_Canonical rule: {m['canonical_rule']}._")
            L.append("")
    else:
        L.append("No case-variant folding was needed.")
        L.append("")

    L += ["## 3. Decisions requiring a human", ""]
    if decisions:
        L.append("These were **not** applied. Each one changes the analysis and needs "
                 "an explicit choice.")
        L.append("")
        for f in decisions:
            cols = ", ".join(f"`{c}`" for c in f.get("columns", [])) or "n/a"
            L += [
                f"### `{f['op']}` ({f['severity']})",
                "",
                f"- **Columns**: {cols}",
                f"- **Why flagged**: {f.get('reason', '')}",
                f"- **Question**: {f.get('ask_user', '')}",
                f"- **If you say nothing**: `{f.get('default_if_silent', '')}`",
                f"- **Rule**: {f.get('rule_source', '')}",
                f"- **Answer with**: fill `answers.template.json` (id `{f.get('id', '--')}`) and re-run with `--answers`",
                "",
            ]
    else:
        L.append("None.")
        L.append("")

    if resolved:
        L += ["## 3b. Decisions answered through the answers file", ""]
        L.append("Each was held by policy, then decided by a recorded human "
                 "decision. The full provenance (who, when, why, which file) is in "
                 "`cleaning_plan.json` under `user_decisions`.")
        L.append("")
        for f in resolved:
            r = f["resolved"]
            cols = ", ".join(f"`{c}`" for c in f.get("columns", [])) or "rows"
            L.append(f"- `{f['op']}` on {cols} -- decided `{r.get('action')}` by "
                     f"{r.get('decided_by')}"
                     + (f" -- {r['rationale']}" if r.get("rationale") else ""))
        L.append("")

    L += ["## 4. Disclosures (already applied, reversible)", ""]
    if disclosures:
        L.append("Applied automatically. Listed here so the automatic choice is never silent.")
        L.append("")
        for f in disclosures:
            cols = ", ".join(f"`{c}`" for c in f.get("columns", [])) or "n/a"
            L += [
                f"### `{f['op']}`",
                "",
                f"- **Columns**: {cols}",
                f"- **Detail**: {f.get('reason', '')}",
                f"- **Undo**: {f.get('ask_user', '')}",
                "",
            ]
    else:
        L.append("None.")
        L.append("")

    if withheld:
        L += ["## 5. Withheld by --skip/--only", ""]
        for w in withheld:
            cols = ", ".join(f"`{c}`" for c in w.get("columns", [])) or "—"
            L.append(f"- `{w['id']}` (`{w['op']}`) — withheld, columns: {cols}")
        L.append("")

    L += [
        "## Reproducing this result",
        "",
        "```bash",
        f"python {script_name}",
        "```",
        "",
        f"The regenerated `cleaned.csv` must hash to `{clean_hash}`.",
        "",
    ]
    return "\n".join(L)


# ---------------- driver ----------------

def main() -> int:
    p = argparse.ArgumentParser(description="Execute a cleaning plan deterministically.",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in", dest="inp", required=True, help="raw data file")
    p.add_argument("--plan", required=True, help="cleaning_plan.json")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--only", action="append", default=[],
                   help="run only these rule ids (repeatable); staged re-runs")
    p.add_argument("--skip", action="append", default=[],
                   help="withhold these rule ids (repeatable); recorded as withheld")
    p.add_argument("--no-verify", action="store_true",
                   help="skip the self-check that regenerates cleaned.csv from raw")
    args = p.parse_args()

    _CASE_MERGE_MAPS.clear()

    src = Path(args.inp)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    read_mode = plan.get("read_mode") or profile_read_mode(src) or "text"
    raw_df = read_table(src, read_mode=read_mode)
    df = raw_df.copy()
    n_raw = len(df)
    col_before = list(df.columns)
    raw_hash = _file_hash(src)

    actions = plan["auto_actions"]
    if args.only:
        wanted = set(args.only)
        actions = [a for a in actions if a["id"] in wanted]
    withheld: List[Dict[str, Any]] = []
    if args.skip:
        skip = set(args.skip)
        withheld = [a for a in actions if a["id"] in skip]
        actions = [a for a in actions if a["id"] not in skip]

    applied: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    case_maps: List[Dict[str, Any]] = []

    for op in actions:
        fn = OP_REGISTRY.get(op["op"])
        if fn is None:
            failed.append({**op, "reason": f"no implementation registered for op '{op['op']}'"})
            continue
        before = len(df)
        maps_before = len(_CASE_MERGE_MAPS)
        try:
            df = fn(df, list(op.get("columns", [])))
        except Exception as exc:
            failed.append({**op, "reason": f"raised {type(exc).__name__}: {exc}"})
            continue
        applied.append({
            "id": op["id"],
            "op": op["op"],
            "columns": op.get("columns", []),
            "severity": op.get("severity"),
            "rule_source": op.get("rule_source"),
            "origin": op.get("origin", "rule"),
            "n_before": before,
            "n_after": len(df),
        })
        case_maps.extend(_CASE_MERGE_MAPS[maps_before:])

    cleaned_csv = out_dir / "cleaned.csv"
    df.to_csv(cleaned_csv, index=False)
    clean_hash = _file_hash(cleaned_csv)
    col_after = list(df.columns)

    clean_py = out_dir / f"clean_{_slug(src.stem)}.py"
    emit_reproducible_script(plan, src, cleaned_csv, clean_py, applied,
                             read_mode=read_mode)

    touched = converting_columns(applied)
    untouched_audit = audit_untouched_columns(raw_df, df, touched)

    (out_dir / "cleaning_report.md").write_text(
        build_report(src, n_raw, len(df), raw_hash, clean_hash, clean_py.name,
                     applied, case_maps, plan, withheld, col_before, col_after),
        encoding="utf-8",
    )

    verification = ({"passed": None, "reason": "skipped via --no-verify"}
                    if args.no_verify else verify_reproducible(clean_py, clean_hash))

    run = {
        "schema_version": "1.1",
        "reproducibility_check": verification,
        "source": str(src),
        "n_raw": n_raw,
        "n_clean": len(df),
        "columns_before": col_before,
        "columns_after": col_after,
        "columns_dropped": [c for c in col_before if c not in col_after],
        "raw_hash": raw_hash,
        "cleaned_hash": clean_hash,
        "source_spec": source_spec(src, read_mode),
        "read_mode": read_mode,
        "columns_touched_by_ops": touched,
        "dtype_manifest": dtype_manifest(df),
        "untouched_column_audit": untouched_audit,
        "applied_ops": applied,
        "case_variant_merge_map": case_maps,
        "withheld": withheld,
        "failed": failed,
        "never_automatic_flags": plan.get("never_automatic_flags", []),
        "user_flags": plan.get("user_flags", {}),
    }
    (out_dir / "cleaning_run.json").write_text(
        json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"cleaned : {n_raw} -> {len(df)} rows, {len(col_before)} -> {len(col_after)} cols")
    print(f"output  : {cleaned_csv}")
    print(f"script  : {clean_py}")
    print(f"applied : {len(applied)} ops | withheld: {len(withheld)} | failed: {len(failed)}")
    for f in failed:
        print(f"  FAILED {f['id']}: {f['reason']}")
    if verification["passed"] is True:
        print(f"verify  : PASS byte-for-byte reproducible ({clean_hash[:16]}...)")
    elif verification["passed"] is False:
        print(f"verify  : FAIL {verification['reason']}")
        print(f"          {verification.get('stderr', '')[:500]}")
    else:
        print(f"verify  : SKIPPED ({verification['reason']})")
    if untouched_audit["passed"]:
        print(f"audit   : PASS {untouched_audit['columns_checked']} untouched columns "
              f"kept their raw values exactly")
    else:
        print(f"audit   : FAIL values appeared in {untouched_audit['columns_violating']}")
        for v in untouched_audit["violations"][:5]:
            print(f"          {v['column']}: +{v['sample_introduced'][:3]} "
                  f"-{v['sample_missing'][:3]}")

    bad = bool(failed or verification["passed"] is False
               or not untouched_audit["passed"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
