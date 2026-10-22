# Modality Routing Reference

The router decides how to handle each file. Always follow: **extension → sniff → fallback to research-track**.

## Master routing table

What ships in v1 is the authority, not the wishlist. A row marked **not in v1**
routes to `references/research-protocol.md` and says so; it does not silently
fall back to tabular.

| Input | Modality | Decision rule | Profiler / command |
|---|---|---|---|
| `.csv` `.tsv` | tabular | delimiter sniff succeeds | `scripts/profile_tabular.py` |
| `.csv` `.tsv` with a timestamp column | time-series | a column named time/date/timestamp (or whose first 3 columns parse as ISO dates) parses in >= 90% of sampled rows | `scripts/profile_timeseries.py` |
| `.csv` `.tsv` with a lat/lon pair | geospatial | headers match `lat|latitude|y` and `lon|lng|longitude|x` | `scripts/profile_geospatial.py` |
| `.xlsx` `.xls` | tabular | `openpyxl` opens it | `scripts/profile_tabular.py` |
| `.json` (array of records, or a `data`/`rows`/`records` list) | tabular | top level is a list of objects | `scripts/profile_tabular.py` |
| `.json` (GeoJSON `FeatureCollection` / `Feature`) | geospatial | `type` field says so | `scripts/profile_geospatial.py` |
| `.json` (nested document) | unknown | not a table and not geometry | `references/research-protocol.md` |
| `.jsonl` `.ndjson` | tabular | one record per line | `scripts/profile_tabular.py` |
| `.parquet` `.feather` | tabular | `pyarrow` reads it | `scripts/profile_tabular.py` |
| `.sqlite` `.sqlite3` `.db` | tabular | exactly one user table is present | `scripts/profile_tabular.py` |
| `.txt` (delimiter detected) | tabular | `csv.Sniffer` positive with >= 3 columns | `scripts/profile_tabular.py` |
| `.txt` `.md` `.rst` `.log` | text-corpus | sniffer negative | `scripts/profile_text.py` |
| a table column holding one document per row | text-corpus | explicit `--text-col` | `scripts/profile_text.py --text-col` |
| `.jpg` `.jpeg` `.png` `.webp` `.bmp` `.gif` `.tif` `.tiff` | image-set | `PIL.Image.open` succeeds | `scripts/profile_media.py --kind image` |
| `.wav` `.mp3` `.flac` `.m4a` `.ogg` `.aac` `.wma` | audio-set | `wave` for WAV, `ffprobe` for compressed | `scripts/profile_media.py --kind audio` |
| `.geojson` | geospatial | JSON FeatureCollection | `scripts/profile_geospatial.py` |
| `.shp` | geospatial | needs `pyshp` | `scripts/profile_geospatial.py` |
| `.csv` of coordinates | geospatial | `--lat` / `--lon`, or the header pair above | `scripts/profile_geospatial.py` |
| `.pdf` `.docx` `.html` | **not in v1** | no profiler ships | `references/research-protocol.md` |
| `.mp4` `.mov` `.avi` | **not in v1** | no video profiler ships | `references/research-protocol.md` |
| `.gpkg` `.kml` `.gpx` | **not in v1** | no reader ships | `references/research-protocol.md` |
| anything else / no extension | unknown | no rule matched | `references/research-protocol.md` |

### Running the router

`scripts/route_input.py` implements the first two passes and writes one record per
file, with the evidence and the rejected alternatives:

```powershell
python scripts/route_input.py --in data/ --deep --out outputs/route.json
python scripts/route_input.py --in "*.csv" --deep --out outputs/route.json
python scripts/route_input.py --in data/ --modality tabular --out outputs/route.json   # override, recorded
```

`--deep` is what separates a timestamped table from a plain one. Without it the
router uses the extension only and a sensor log is routed to `tabular`.

A mixed folder produces one branch per modality, and every branch is marked
`parallel: true`. The branches write disjoint artifacts and are merged only at
the report stage.

### What each modality costs

| Modality | Required | Optional | What the optional package buys |
|---|---|---|---|
| tabular | pandas, numpy, scipy | matplotlib, statsmodels, openpyxl, pyarrow | figures, ADF/modelled effects, xlsx, parquet |
| text-corpus | pandas | -- | nothing: the profiler is stdlib + pandas |
| time-series | pandas, numpy | statsmodels | ADF and trend screens |
| image-set | numpy, Pillow | -- | nothing |
| audio-set | numpy, stdlib `wave` | ffmpeg / ffprobe | decoding mp3/m4a for clipping and silence |
| geospatial | pandas, numpy | pyshp | reading `.shp`; GeoJSON and CSV need nothing |

Run `python scripts/check_deps.py --modalities <list>` to check exactly these;
it distinguishes required from optional and fails only on a missing requirement.

## Sniffer snippets (deterministic)

### csv delimiter sniff

```python
import csv
from pathlib import Path

def sniff_csv(path: Path, sample_bytes: int = 8192) -> dict:
    with open(path, "rb") as f:
        sample = f.read(sample_bytes)
    try:
        dialect = csv.Sniffer().sniff(sample.decode("utf-8", errors="replace"))
        has_header = csv.Sniffer().has_header(sample.decode("utf-8", errors="replace"))
        return {
            "delimiter": dialect.delimiter,
            "quotechar": dialect.quotechar,
            "has_header": has_header,
            "modality": "tabular",
        }
    except csv.Error:
        return {"modality": "text-corpus", "fallback_encoding": "utf-8"}
```

### tabular vs nested json

```python
import json
import pandas as pd

def json_modality(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith((".jsonl", ".ndjson")):
            rows = [json.loads(line) for line in f if line.strip()]
        else:
            data = json.load(f)
            rows = data if isinstance(data, list) else [data]
    try:
        df = pd.json_normalize(rows, max_level=3)
        return "tabular" if df.shape[1] > 1 else "nested"
    except Exception:
        return "research-track"
```

### time-series detection in tabular

```python
import pandas as pd

def detect_timeseries(df: pd.DataFrame) -> dict:
    for col in df.columns:
        s = df[col]
        try:
            ts = pd.to_datetime(s, errors="raise")
        except Exception:
            continue
        # monotone or sortable; allow small reorder
        if ts.is_monotonic_increasing or ts.is_monotonic_decreasing:
            return {
                "is_timeseries": True,
                "time_column": col,
                "n": len(ts),
                "freq_hint": pd.infer_freq(ts.head(min(len(ts), 200))),
                "span_days": (ts.max() - ts.min()).days,
            }
    return {"is_timeseries": False}
```

### geo tiff sniff

```python
import tifffile

def sniff_geotiff(path: str) -> bool:
    try:
        with tifffile.TiffFile(path) as tif:
            for page in tif.pages:
                tags = page.tags
                if any(k in tags for k in ("ModelTiepointTag", "ModelPixelScaleTag", "GeoKeyDirectoryTag")):
                    return True
        return False
    except Exception:
        return False
```

## Mixed folder handling

If a folder contains files from >1 modality, the router must:

1. Group files by modality (one report per modality).
2. Run the full pipeline per group.
3. Produce a top-level `outputs/INDEX.md` that lists each modality run and links to its report.
4. Never silently merge modalities.

## Routing decision log

Every routing decision writes to `analysis/routing_decisions.json` with the structure:

```json
{
  "decisions": [
    {
      "file": "data/sales.csv",
      "extension": ".csv",
      "sniffer_used": "csv.Sniffer",
      "sniffer_result": {"delimiter": ",", "has_header": true},
      "modality": "tabular",
      "rule_source": "references/modality-routing.md#master-routing-table",
      "alternative_considered": "text-corpus (because first row had commas inside quoted strings)",
      "rejected_reason": "Sniffer succeeded with has_header=true, so delimiter-light"
    }
  ]
}
```

## v1 coverage

| Modality | v1 status |
|---|---|
| tabular | full (profiler + cleaner + stats + charts) |
| text-corpus | full (profiler + cleaner + token stats + wordcloud chart) |
| time-series | full (profiler + cleaner + decomposition + ACF/PACF + forecast) |
| image-set | profiler only (corrupt check, dedup, size histogram) |
| audio-set | profiler only (decode check, duration, silence) |
| geo | profiler only (CRS + bbox + overlap) |
| video-set | v2 |
| document (pdf/docx/md/html) | v2 (currently routes to text-corpus with a warning) |
| research-track | full (WebSearch + WebFetch + ad-hoc script) |
