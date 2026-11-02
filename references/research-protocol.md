# Research Protocol — handling unknown modalities

When a file extension / format does not match any entry in the master routing table, the router falls back to **research-track**. This file defines how to handle that case safely.

> Inspired by yogaibhh/claude-clean-data-skill `references/research-protocol.md` — extended with provenance requirements and Nature-gate compatibility.

## When to enter research-track

Triggered when:

1. Extension is unknown (e.g. `.fasta`, `.hdf5`, `.avro`, `.msg`).
2. Sniffer fails (file magic mismatch, binary inside a `.txt`, corrupted header).
3. JSON is nested > 3 levels deep (tabular flattening breaks structure).
4. User explicitly says `--research <format>`.

## Protocol

### R1 — Identify the format without disclosing file contents

1. Inspect a bounded prefix locally, if format identification requires it. Keep the
   observed bytes and any decoded header in the local process; do not copy them into
   run artifacts.
2. Search only public format names, extensions, and library names, for example:
   `HDF5 file format specification` or `FASTA Python parser documentation`.
3. Never send or paste observed magic bytes, file headers, metadata, records, paths,
   or user values to WebSearch, WebFetch, or another external service. If the public
   format name is unknown, ask the user to identify it or continue with profile-only
   handling; do not share file-derived detail.
4. Capture candidate libraries and their official documentation sources. A second
   candidate is useful only when the format has genuine parser alternatives.

### R2 — Pick an available library

For each candidate:

```bash
python -c "import <lib>; print(<lib>.__version__)"
```

Use an already installed library when available. If no suitable parser is installed,
record the missing dependency and stop at a local profile-only result. Do not run
`pip install` directly and do not install into the system or ambient Python. If the
user wants the format parser, ask before installing it into the data-master managed
environment with the **npm launcher** command `data-master setup --extra <package>`;
then run the analysis through that launcher. If it is unavailable, keep the branch
profile-only. Use only a package name selected from the parser's official documentation.

### R3 — Document provenance

Write `analysis/research_track.json`:

```json
{
  "format": "FASTA",
  "format_signature": "FASTA text marker (standard signature; no observed file bytes)",
  "extension": ".fasta",
  "candidate_libraries": [
    {"name": "Bio", "installed": true, "version": "1.81", "source": "https://biopython.org/"},
    {"name": "pyfaidx", "installed": true, "version": "0.7", "source": "https://github.com/mdshw5/pyfaidx"}
  ],
  "chosen": {"name": "Bio", "reason": "more comprehensive; matches Nature audit needs"},
  "alternatives_rejected": [
    {"name": "pyfaidx", "reason": "read-only index; we may want to write cleaned sequences"}
  ],
  "web_sources": [
    "https://en.wikipedia.org/wiki/FASTA_format",
    "https://biopython.org/wiki/SeqIO"
  ]
}
```

### R4 — Build a minimal ad-hoc profiler

A Python script at `scripts/profile_research_<format>.py` that:

1. Opens the file with the chosen library, in **text mode** wherever the format allows it.
2. Returns shape (n_records), per-record schema, missingness, value ranges.
3. Writes `analysis/profile.json` in the standard schema (compatible with cleaning_plan.py).

The reading contract of Step 4 applies here too, and it is the part most likely to be
skipped: a format-specific reader that infers types on the way in reproduces the exact
failure the skill exists to prevent. `§ R2` justifies the library choice, not the
choice of types. Concretely —

- If the format is schema-bearing (NetCDF, HDF5 with typed datasets, Parquet, Arrow),
  the declared types **are** the schema; replay them and record them in `dtype_manifest`.
- If it is not (FASTA headers, log lines, free text, CSV, YAML), read every field as a
  string and let Step 5 decide, exactly as `dm_types.read_table(read_mode="text")` does
  for the tabular path.
- Whichever applies, the profiler records what it chose under `read_mode` so that
  `validate_clean.py` can tell a deliberate replay from an accidental re-inference.

An identifier field is not a number just because the format would let it be one. A FASTA
header like `>seq1` and a log line `ERROR 404` are both text, and a reader that "helpfully"
strips the prefix has made a decision the file never recorded.

### R5 — Define cleaning ops

If the research format has well-known cleaning ops, list them in `cleaning_plan.json` with the same provenance format (rule_source = this file + section).

If not, **do not invent ops**. Profile only; mark `AUTHOR_INPUT_NEEDED` for every cleaning decision.

The Step 5 holds apply unchanged, and on an unknown format they bind harder: any column
whose conversion is not provably lossless is held, not coerced. "We do not know what this
format means" is a reason to ask, never a reason to guess.

### R6 — Nature-gate compatibility

The same 8 Nature gates apply. The audit will FAIL gate 1 if the independent unit is unclear. The research-track run must explicitly document the unit (or fail loudly with `AUTHOR_INPUT_NEEDED`).

## Common research-track formats

| Format | Magic | Library | Likely unit |
|---|---|---|---|
| FASTA / FASTQ | `> ` / `@` | Bio / pyfastx | sequence, read |
| HDF5 | `89HDF` | h5py | dataset (user-named) |
| NetCDF | `CDF\x01` | netCDF4 / xarray | variable / time-step |
| Parquet | `PAR1` | pyarrow | row (but should re-route to tabular) |
| Arrow IPC | `ARROW1` | pyarrow | row |
| Avro | `Obj\x01` | fastavro | record |
| MATLAB .mat | MATL | scipy.io | variable |
| TSV / delimited variant | Sniffer | pandas | row |
| LaTeX / Typst | document char class | textract | document |
| YAML / TOML | document | pyyaml / tomli | document |
| SQL dump | keywords | sqlparse | table |
| Email .mbox | `From ` | mailbox | message |
| GeoJSON | `{`+`"type":"Feature"` | geopandas | feature |
| KML | `<kml>` | pykml | placemark |

For each format, the agent must find at least one public specification page and cite it.

### Unsafe Python object serialization

Python Pickle and formats implemented on top of Pickle (including `.pkl`, `.pickle`,
`.joblib`, and `.dill`) are **not supported for automatic loading**. Deserializing one
can execute code from the file. Route these files to `unknown`, report that loading was
refused, and do not call `pickle`, `joblib.load`, `dill`, or a wrapper that may unpickle
the input. This refusal applies even when the file is labelled as a dataset. A trusted
user may convert it outside this pipeline and provide a non-executable interchange
format such as CSV or Parquet.

## Fallback hierarchy

1. Bounded, local signature lookup against known public format signatures.
2. Local sniffer (CSV / JSON).
3. WebSearch using only a public extension or format name.
4. Ask the user when identification remains uncertain. Never disclose file-derived
   content to exhaust the lookup steps.

## Risk control

Research-track is the most failure-prone branch. Mitigation:

- Always write `analysis/research_track.json` before doing any data work.
- Keep all observed file content local. Store only the public format signature or a
  short local identification result in the report; never store or transmit a raw prefix.
- Refuse Pickle-based deserialization as described above.
- Never install a parser automatically. User-approved optional parsers go only into
  the data-master managed environment.
- Never let the research-track reader infer types; see R4. An unknown format is exactly
  where a confident-looking automatic conversion does the most damage.
- Limit processing to n = 1000 records for the profile (full set for cleaning).
- The cleaning plan must mark **all** ops as `auto: false` until the format is well understood.
- Final report must say "RESEARCH-TRACK" in the header so the user knows.
- Audit verdict: warn if no well-known Nature-grade practice exists for this format.
