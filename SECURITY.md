# Security

## What this skill does with your data

`data-master` runs locally. The scripts read the files you pass them and write
artifacts under the output directory. They do not upload data, and they do not
make network requests. `scripts/final_audit.py` and the profilers are pure
local code.

The agent runtime around the scripts may have its own network policy; that is
outside this repository.

## Reporting a vulnerability

If you find a way for a crafted input file to make a script:

- write outside the output directory,
- execute code from the data (for example through a pickle or a formula),
- or read a file it was not given,

please open a private security advisory rather than a public issue.

## Known boundaries

- `.parquet` and `.feather` are read through `pyarrow`; a malicious file could
  exploit a parser vulnerability in that library. Keep `pyarrow` patched.
- The PDF cascade invokes a locally installed browser (`msedge`/`chrome`) with a
  temporary user-data directory. It does not navigate to a URL; it prints a local
  HTML file.
- `execute_cleaning.py` writes and then executes a generated Python script. The
  script is generated from the plan, never from raw cell values interpolated into
  code. Review `cleaned/clean_<slug>.py` if you are processing untrusted input.
- Text profiles report encoding fallbacks; they do not attempt to interpret
  binary files as text.
