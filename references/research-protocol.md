# Research Protocol — handling unknown modalities

When a file extension / format does not match any entry in the master routing table, the router falls back to **research-track**. This file defines how to handle that case safely.

> Inspired by yogaibhh/claude-clean-data-skill `references/research-protocol.md` — extended with provenance requirements and Nature-gate compatibility.

## When to enter research-track

Triggered when:

1. Extension is unknown (e.g. `.fasta`, `.hdf5`, `.avro`, `.pkl`, `.msg`).
2. Sniffer fails (file magic mismatch, binary inside a `.txt`, corrupted header).
3. JSON is nested > 3 levels deep (tabular flattening breaks structure).
4. User explicitly says `--research <format>`.

## Protocol

### R1 — Identify the format

1. Read first 256 bytes; compute magic bytes.
2. Search WebSearch with the magic bytes + common interpretations: `"<hex>" file format specification`.
3. Search WebSearch: `<extension> python library parser`.
4. Capture candidate libraries: at least 2 to allow fallback.

### R2 — Pick a working library

For each candidate:

```bash
python -c "import <lib>; print(<lib>.__version__)"
```

Pick the first that imports. If none, record the failure and try `pip install <lib>` for each candidate in order.

### R3 — Document provenance

Write `analysis/research_track.json`:

```json
{
  "format": "FASTA",
  "magic_bytes": "3C3E...",
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
| Pickle | `\x80\x04` or `\x80\x05` | pickle | varies |
| MATLAB .mat | MATL | scipy.io | variable |
| TSV / delimited variant | Sniffer | pandas | row |
| LaTeX / Typst | document char class | textract | document |
| YAML / TOML | document | pyyaml / tomli | document |
| SQL dump | keywords | sqlparse | table |
| Email .mbox | `From ` | mailbox | message |
| GeoJSON | `{`+`"type":"Feature"` | geopandas | feature |
| KML | `<kml>` | pykml | placemark |

For each format, the agent must find at least one public specification page and cite it.

## Fallback hierarchy

1. Magic-byte lookup (fastest).
2. Sniffer (csv / json).
3. WebSearch magic + extension.
4. Ask user (only after exhausting 1-3).

## Risk control

Research-track is the most failure-prone branch. Mitigation:

- Always write `analysis/research_track.json` before doing any data work.
- Never let the research-track reader infer types; see R4. An unknown format is exactly
  where a confident-looking automatic conversion does the most damage.
- Limit processing to n = 1000 records for the profile (full set for cleaning).
- The cleaning plan must mark **all** ops as `auto: false` until the format is well understood.
- Final report must say "RESEARCH-TRACK" in the header so the user knows.
- Audit verdict: warn if no well-known Nature-grade practice exists for this format.
