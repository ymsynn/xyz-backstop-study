"""Hourly candles of every xyz market from Hyperliquid's public info API (no S3): data/candles/xyz_1h.parquet.
Usage: python sim/study/fetch_candles.py"""
import json, os, time, urllib.request, urllib.error
import polars as pl
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
U = json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]
def post(body):
    for k in range(8):   # back off on 429
        try:
            r = urllib.request.Request("https://api.hyperliquid.xyz/info", json.dumps(body).encode(), {"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(r, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(2 ** k)
    raise RuntimeError("rate limited")
end = int(time.time() * 1000); rows = []
for u in U:
    c = u["name"]; got = []
    t1 = end
    for _ in range(1):   # HL serves only the latest 5000 candles
        x = post({"type": "candleSnapshot", "req": {"coin": c, "interval": "1h", "startTime": t1 - 5000 * 3600_000, "endTime": t1}})
        if not x: break
        got += x; t0 = min(k["t"] for k in x)
        if len(x) < 4990: break
        t1 = t0 - 1
        time.sleep(0.2)
    for k in got: rows.append((c, k["t"], float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])))
    time.sleep(1.0)
d = pl.DataFrame(rows, schema=["coin", "t", "o", "h", "l", "c", "v"], orient="row").unique(["coin", "t"]).sort("coin", "t")
d.write_parquet(f"{ROOT}/data/candles/xyz_1h.parquet")
print(d.group_by("coin").agg(pl.len(), pl.col("t").min()).sort("len").head(5), d.height, d["coin"].n_unique())
