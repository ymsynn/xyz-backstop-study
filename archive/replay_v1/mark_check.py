"""Recompute the xyz mark = median(m1, m2, median(best bid, best ask, last trade)) at every real liquidation block and
compare with liquidation.markPx. Inputs: extract tables (oracle, blocks), the replay's BBO log, fills tape, liquidation tape."""
import sys, statistics
import polars as pl
T, BBO, FILLS, LIQ = sys.argv[1:5]
COIN = "xyz:GOOGL"; SC = 1e6
blocks = pl.read_parquet(f"{T}/blocks.parquet").select("h", (pl.col("t").cast(pl.Int64) // 10**6).alias("ms"))
h_of_ms = dict(zip(blocks["ms"].to_list(), blocks["h"].to_list()))
orc = pl.read_parquet(f"{T}/oracle.parquet").filter(pl.col("coin") == COIN).sort("h", "b", "i").select("h", "m1", "m2", "oracle")
bbo = pl.read_parquet(BBO).with_columns((pl.col("bid") / SC), (pl.col("ask") / SC))
tr = (pl.scan_parquet(FILLS).filter(pl.col("coin") == COIN, pl.col("crossed")).select("timestamp", pl.col("price").cast(float).alias("last")).collect()
      .with_columns(pl.col("timestamp").cast(pl.Int64).replace_strict(h_of_ms, default=None).alias("h")).drop_nulls("h").group_by("h").agg(pl.col("last").last()).sort("h"))
L = (pl.read_parquet(LIQ).filter(pl.col("coin") == COIN)
     .with_columns(pl.col("timestamp").cast(pl.Int64).replace_strict(h_of_ms, default=None).alias("h"), pl.col("liquidation_mark_px").cast(float).alias("mk"))
     .drop_nulls("h").group_by("h").agg(pl.col("mk").first()).sort("h"))
import itertools
res = {}
for strict, prevbook, prevlast in itertools.product((True, False), (False, True), (False, True)):           # oracle update strictly before the block, or within it
    o2 = orc.with_columns((pl.col("h") + (1 if strict else 0)).alias("h"))
    bb = bbo.with_columns((pl.col("h") + (1 if prevbook else 0)).alias("h"))
    tt = tr.with_columns((pl.col("h") + (1 if prevlast else 0)).alias("h"))
    j = (L.join_asof(o2, on="h", strategy="backward").join(bb, on="h", how="left").join_asof(tt, on="h", strategy="backward"))
    ok = 0; n = 0; rows = []
    for h, mk, m1, m2, orac, bid, ask, last in j.select("h", "mk", "m1", "m2", "oracle", "bid", "ask", "last").iter_rows():
        if None in (m1, m2, bid, ask, last):
            continue
        book = statistics.median([bid, ask, last])
        sim = statistics.median([m1, m2, book])
        n += 1; ok += abs(sim - mk) < 0.005
        rows.append((h, mk, sim, m1, m2, book))
    res[(strict, prevbook, prevlast)] = (ok, n, rows)
    print(f"oracle {'<h' if strict else '<=h'} | book end of {'h-1' if prevbook else 'h'} | last trade up to {'h-1' if prevlast else 'h'}: {ok}/{n} = {ok/max(n,1):.1%}")
best = max(res, key=lambda k: res[k][0])
bad = [r for r in res[best][2] if abs(r[1] - r[2]) >= 0.005][:8]
print("misses (h, real, sim, m1, m2, book):"); [print("  ", r) for r in bad]
