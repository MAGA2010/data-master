#!/usr/bin/env python3
"""Build a small, deliberately awkward hourly sensor log.

The point is not the noise.  The point is that a naive reader of this file will
report a mean over rows and call it a mean over time, even though:

  * the sensor drops out for six hours in the middle;
  * two rows share a timestamp (a retransmission, not a repeated measurement);
  * the logging interval changes from hourly to 15-minute near the end.

Run:  python examples/timeseries/make_series.py
"""
from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "sensor_log.csv"


def main() -> int:
    rng = random.Random(7)
    start = datetime(2026, 1, 1, 0, 0)
    rows = []
    for i in range(96):
        if 48 <= i <= 53:                    # six-hour dropout
            continue
        t = start + timedelta(hours=i)
        temp = 20 + 3 * math.sin(i / 24 * 2 * math.pi) + rng.gauss(0, 0.35)
        rows.append((t, "%.2f" % temp, "%.1f" % (55 + rng.gauss(0, 2))))

    rows.append((start + timedelta(hours=10), "20.31", "54.9"))   # retransmission

    last = start + timedelta(hours=95)                            # regime change
    for k in range(1, 13):
        t = last + timedelta(minutes=15 * k)
        temp = 20 + 3 * math.sin((95 + k / 4) / 24 * 2 * math.pi) + rng.gauss(0, 0.3)
        rows.append((t, "%.2f" % temp, "%.1f" % (55 + rng.gauss(0, 2))))

    rows.sort(key=lambda r: r[0])
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "temperature_c", "humidity_pct", "site"])
        for t, temp, hum in rows:
            w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), temp, hum, "lab-A"])
    print("wrote %s (%d rows)" % (OUT, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
