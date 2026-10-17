#!/usr/bin/env python3
"""Profile geospatial data without changing it.

Coordinates fail quietly.  A latitude of 91, a longitude of -181, a point at
(0, 0), the same station recorded twice, a geometry that self-intersects, a file
whose coordinates are in metres but whose CRS says degrees -- each of these
produces a map that renders and a distance that is wrong.

Three input shapes are accepted:

    GeoJSON  (.geojson / .json with a FeatureCollection)
    CSV      (--lat-col / --lon-col; defaults: lat/latitude, lon/lng/longitude)
    Shapefile(.shp, requires pyshp; reported clearly when it is absent)

Usage
    python scripts/profile_geospatial.py --in points.geojson --out profile.json
    python scripts/profile_geospatial.py --in stations.csv --lat lat --lon lon --out profile.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402

import dm_types                         # noqa: E402

SCHEMA_VERSION = "1.0"
LAT_NAMES = ("lat", "latitude", "y", "lat_dd")
LON_NAMES = ("lon", "lng", "long", "longitude", "x", "lon_dd")


def _round(v: Any, d: int = 6) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, d)


def load_geojson(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("type") == "FeatureCollection":
        features = doc.get("features") or []
        crs = (doc.get("crs") or {}).get("properties", {}).get("name")
    elif doc.get("type") == "Feature":
        features, crs = [doc], None
    else:
        features, crs = [], None
    out = []
    for i, f in enumerate(features):
        geom = f.get("geometry") or {}
        out.append({
            "id": str((f.get("properties") or {}).get("id", i)),
            "geometry_type": geom.get("type"),
            "coordinates": geom.get("coordinates"),
            "properties": f.get("properties") or {},
        })
    return out, {"crs": crs or "not declared (GeoJSON is WGS84 by RFC 7946)",
                 "declared_crs_from_file": bool(crs)}


def load_shapefile(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        import shapefile  # pyshp
    except Exception:
        raise SystemExit("reading a shapefile needs pyshp: pip install pyshp")
    reader = shapefile.Reader(str(path))
    out = []
    for i, shape in enumerate(reader.shapes()):
        out.append({"id": str(i), "geometry_type": shape.shapeTypeName,
                    "coordinates": list(shape.points),
                    "properties": dict(zip([f[0] for f in reader.fields[1:]],
                                           list(reader.records()[i]))) })
    return out, {"crs": "read from the .prj file if present; pyshp does not parse it",
                 "declared_crs_from_file": (path.with_suffix(".prj")).exists()}


def load_csv(path: Path, lat: Optional[str], lon: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    df = dm_types.read_table(path, read_mode="text")
    lat_col = lat or next((c for c in df.columns if c.lower() in LAT_NAMES), None)
    lon_col = lon or next((c for c in df.columns if c.lower() in LON_NAMES), None)
    if not lat_col or not lon_col:
        raise SystemExit("could not find latitude/longitude columns; pass --lat and --lon "
                         "(columns: %s)" % ", ".join(df.columns))
    out = []
    for i, (a, b) in enumerate(zip(df[lat_col], df[lon_col])):
        la, lo = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
        out.append({"id": str(i), "geometry_type": "Point",
                    "coordinates": [None if pd.isna(lo) else float(lo),
                                    None if pd.isna(la) else float(la)],
                    "properties": {}})
    return out, {"crs": "unknown -- a CSV of lat/lon is assumed WGS84 degrees; "
                        "verify before measuring distance",
                 "lat_col": lat_col, "lon_col": lon_col}


def flatten_points(coords: Any, out: List[Tuple[float, float]]) -> None:
    """Collect (lon, lat) pairs, keeping nulls as NaN instead of dropping them.

    Dropping a null coordinate silently removes a feature from the denominator:
    the profile then reports six valid points where the file has seven, and the
    missing one is never mentioned.  A NaN pair keeps the count honest and lets
    the caller flag it.
    """
    if not isinstance(coords, (list, tuple)) or not coords:
        return
    if not isinstance(coords[0], (list, tuple)) and len(coords) >= 2:
        try:
            out.append((float(coords[0]), float(coords[1])))
        except (TypeError, ValueError):
            out.append((float("nan"), float("nan")))
        return
    for c in coords:
        flatten_points(c, out)


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="profile geospatial data")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--lat", default=None)
    ap.add_argument("--lon", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    path = Path(args.inp)
    if not path.exists():
        print("input not found: %s" % path, file=sys.stderr)
        return 2

    suffix = path.suffix.lower()
    if suffix in (".geojson", ".json"):
        features, crs = load_geojson(path)
    elif suffix == ".shp":
        features, crs = load_shapefile(path)
    elif suffix in (".csv", ".tsv"):
        features, crs = load_csv(path, args.lat, args.lon)
    else:
        print("unsupported geospatial input: %s (use .geojson, .json, .shp, .csv)"
              % suffix, file=sys.stderr)
        return 2

    flags: List[Dict[str, Any]] = []
    types = Counter(f.get("geometry_type") or "Unknown" for f in features)
    all_points: List[Tuple[float, float]] = []
    per_feature = []
    invalid_coord, zero_zero, out_of_range = [], [], []
    for i, f in enumerate(features):
        pts: List[Tuple[float, float]] = []
        flatten_points(f.get("coordinates"), pts)
        all_points.extend(pts)
        per_feature.append(len(pts))
        for lon, lat in pts:
            if not (math.isfinite(lon) and math.isfinite(lat)):
                invalid_coord.append(i)
            elif abs(lat) > 90 or abs(lon) > 180:
                out_of_range.append({"feature": f.get("id"), "lon": lon, "lat": lat})
            elif abs(lat) < 1e-9 and abs(lon) < 1e-9:
                zero_zero.append(f.get("id"))

    if not features:
        flags.append({"type": "no_geometries", "severity": "P1",
                      "detail": "the file parsed but contains no features"})
    if invalid_coord:
        flags.append({"type": "non_numeric_coordinates", "severity": "P1",
                      "count": len(invalid_coord),
                      "detail": "a coordinate is null or non-numeric; the feature cannot "
                                "be placed and must not be dropped silently"})
    if out_of_range:
        flags.append({"type": "out_of_range_coordinates", "severity": "P1",
                      "count": len(out_of_range), "examples": out_of_range[:5],
                      "detail": "latitude outside [-90, 90] or longitude outside "
                                "[-180, 180]; the CRS or the column order is probably wrong"})
    if zero_zero:
        flags.append({"type": "null_island", "severity": "P2",
                      "count": len(zero_zero), "examples": zero_zero[:5],
                      "detail": "points at exactly (0, 0) are almost always a failed "
                                "geocode, not a location in the Gulf of Guinea"})

    valid = [(lon, lat) for lon, lat in all_points
             if math.isfinite(lon) and math.isfinite(lat)
             and abs(lat) <= 90 and abs(lon) <= 180]
    bounds = None
    span_km = None
    if valid:
        lons = [p[0] for p in valid]
        lats = [p[1] for p in valid]
        bounds = {"min_lon": _round(min(lons)), "max_lon": _round(max(lons)),
                  "min_lat": _round(min(lats)), "max_lat": _round(max(lats))}
        span_km = _round(haversine_km((min(lons), min(lats)),
                                      (max(lons), max(lats))), 3)

    # duplicate locations (rounded to ~11 m) across features
    rounded = Counter((round(lon, 4), round(lat, 4)) for lon, lat in valid)
    dup_sites = sum(1 for c in rounded.values() if c > 1)
    if dup_sites:
        flags.append({"type": "coincident_points", "severity": "P3",
                      "count": dup_sites,
                      "detail": "distinct features share a location to ~11 m; confirm "
                                "these are repeated measurements and not duplicated rows"})

    if span_km is not None and span_km < 1 and len(valid) > 1:
        flags.append({"type": "tiny_extent", "severity": "P3",
                      "detail": "all points fall within %.3f km; a national or regional "
                                "map would be misleading" % span_km})
    if crs.get("crs", "").lower().startswith("unknown"):
        flags.append({"type": "crs_undeclared", "severity": "P2",
                      "detail": crs["crs"]})

    profile = {
        "schema_version": SCHEMA_VERSION,
        "source": str(path),
        "modality": "geospatial",
        "generated": datetime.now(timezone.utc).isoformat(),
        "read_mode": "text",
        "shape": {"n_rows": len(features), "n_cols": 1},
        "crs": crs,
        "geometry": {
            "types": dict(types),
            "n_features": len(features),
            "n_points": len(all_points),
            "points_per_feature": {"min": min(per_feature) if per_feature else None,
                                   "max": max(per_feature) if per_feature else None,
                                   "median": float(np.median(per_feature)) if per_feature else None},
            "bounds": bounds,
            "diagonal_km": span_km,
        },
        "summary": {
            "n_valid_points": len(valid),
            "n_invalid_points": len(all_points) - len(valid),
            "n_features_invalid": len(set(invalid_coord)),
            "n_null_island": len(zero_zero),
            "n_coincident_locations": dup_sites,
        },
        "features": [{"id": f.get("id"), "geometry_type": f.get("geometry_type"),
                      "n_points": n} for f, n in zip(features, per_feature)],
        "columns": {}, "column_roles": {},
        "anomalies": {"flags": flags},
        "target_candidate": None,
        "group_candidate": {"candidates": [], "rejected": [
            {"column": "coordinates", "reason": "a location is not a grouping variable; "
                                                "spatial clusters need a declared method"}]},
        "independent_unit_hint": "one feature" if suffix != ".csv" else "one row",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print("profile_geospatial: %d feature(s), %d valid point(s), %d flag(s) -> %s"
          % (len(features), len(valid), len(flags), args.out))
    return 0 if features and valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
