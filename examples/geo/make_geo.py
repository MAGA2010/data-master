"""Build a small GeoJSON with the four coordinate defects that matter."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "stations.geojson"

features = [
    {"type": "Feature", "properties": {"id": "S1", "name": "Harbour"},
     "geometry": {"type": "Point", "coordinates": [114.1694, 22.3193]}},
    {"type": "Feature", "properties": {"id": "S2", "name": "Kowloon"},
     "geometry": {"type": "Point", "coordinates": [114.1694, 22.3193]}},   # coincident
    {"type": "Feature", "properties": {"id": "S3", "name": "Bad geocode"},
     "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},            # null island
    {"type": "Feature", "properties": {"id": "S4", "name": "Swapped lat/lon"},
     "geometry": {"type": "Point", "coordinates": [22.3193, 114.1694]}},   # out of range
    {"type": "Feature", "properties": {"id": "S5", "name": "Missing"},
     "geometry": {"type": "Point", "coordinates": [None, None]}},          # non-numeric
    {"type": "Feature", "properties": {"id": "S6", "name": "New Territories"},
     "geometry": {"type": "LineString",
                  "coordinates": [[114.10, 22.40], [114.20, 22.45], [114.30, 22.42]]}},
]

OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                          indent=2), encoding="utf-8")
print("wrote", OUT)
