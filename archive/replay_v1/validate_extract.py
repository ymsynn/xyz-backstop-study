"""Phase-0 checks on the reduced extract (tables from reduce.py) for xyz:GOOGL on 2026-10-28.

Usage: python validate_extract.py TABLES_DIR FILLS_PARQUET LIQ_PARQUET
  FILLS_PARQUET  hydromancer by_dex/xyz/fills/perp/all/date=2026-10-28/fills.parquet
  LIQ_PARQUET    hydromancer by_dex/xyz/fills/perp/liquidations/date=2026-10-28/fills.parquet
1. coverage: share of real GOOGL fills whose order id appears in the stream (resting / filled / modified),
   all day and in the crash window, maker vs taker
2. mark: liquidation markPx vs the last relayer components (m1, m2) before that block
3. state: margin-state actions on GOOGL by the accounts that were liquidated, and the whale's
"""
import sys, json, datetime as dt
import polars as pl

T, FILLS, LIQ = sys.argv[1:4]
COIN, ASSET = "xyz:GOOGL", 110012
WHALE = "0x30afce2f6842bf183c7e3fe7162e279ff0b6393e"
o = pl.read_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET)
known = set(o["oid"].drop_nulls().cast(pl.Int64).to_list())
blocks = pl.read_parquet(f"{T}/blocks.parquet")
print("blocks", blocks.height, blocks["t"].min(), "->", blocks["t"].max(), "| GOOGL sub-orders", o.height, "known oids", len(known))

f = (pl.scan_parquet(FILLS).filter(pl.col("coin") == COIN)
     .with_columns(pl.col("timestamp").dt.replace_time_zone(None).alias("t")).collect()
     .with_columns((pl.col("price").cast(float) * pl.col("size").cast(float)).alias("ntl"),
                   pl.col("order_id").cast(pl.Int64).is_in(list(known)).alias("seen")))
f = f.filter(pl.col("t") >= blocks["t"].min())
crash = (pl.col("t") >= dt.datetime(2026, 10, 28, 20, 1, 50)) & (pl.col("t") <= dt.datetime(2026, 10, 28, 20, 5))
print("\n1. coverage (notional-weighted share of fills whose order id is in the stream)")
for name, flt in [("all day", pl.lit(True)), ("crash 20:01:50-20:05", crash)]:
    g = f.filter(flt, pl.col("liquidation_method").is_null()).group_by("crossed").agg(
        pl.len().alias("fills"), pl.col("ntl").sum().alias("ntl"), (pl.col("ntl") * pl.col("seen")).sum().alias("ntl_seen"))
    g = g.with_columns((pl.col("ntl_seen") / pl.col("ntl")).round(4).alias("share_seen"),
                       pl.when(pl.col("crossed")).then(pl.lit("taker")).otherwise(pl.lit("maker")).alias("side"))
    print(" ", name); print(g.select("side", "fills", pl.col("ntl").round(0), "share_seen"))
# unseen maker orders in the crash: how old could they be (first fill time) and how big
um = f.filter(crash, ~pl.col("crossed"), ~pl.col("seen")).group_by("order_id", "address").agg(pl.col("ntl").sum(), pl.col("price").cast(float).min().alias("px"))
VAULT = "0x4000000000000000000000000000000000000001"
for side, cr in [("maker", False), ("taker", True)]:
    u = f.filter(crash, pl.col("liquidation_method").is_null(), pl.col("crossed") == cr, ~pl.col("seen"))
    cause = (pl.when(pl.col("address") == VAULT).then(pl.lit("vault"))
             .when(pl.col("twap_id").is_not_null()).then(pl.lit("twap slice"))
             .when(pl.col("address").is_in(list(set(pl.read_parquet(LIQ).filter(pl.col("liquidation_method") == "backstop")["address"].to_list())))
                   & (pl.col("price").cast(float) > 0)).then(pl.lit("backstop takeover counterparty?"))
             .otherwise(pl.lit("other")))
    print("  unseen", side, "by cause:", u.with_columns(cause.alias("c")).group_by("c").agg(pl.len(), pl.col("ntl").sum().round(0)).sort("ntl", descending=True).to_dicts())
print("  unseen maker orders in crash:", um.height, "ntl", round(um["ntl"].sum()), "top:", um.sort("ntl", descending=True).head(5).to_dicts())

print("\n2. mark vs relayer components")
orc = pl.read_parquet(f"{T}/oracle.parquet").filter(pl.col("coin") == COIN).with_columns(pl.col("t").cast(pl.Datetime("ms"))).sort("h", "b", "i")
gap = orc["t"].diff().dt.total_milliseconds().drop_nulls()
print("  setOracle updates", orc.height, "interval ms p50/p90/max", gap.median(), gap.quantile(0.9), gap.max())
L = (pl.read_parquet(LIQ).filter(pl.col("coin") == COIN)
     .with_columns(pl.col("timestamp").dt.replace_time_zone(None).alias("t"), pl.col("liquidation_mark_px").cast(float).alias("mk"))
     .group_by("t").agg(pl.col("mk").first()).sort("t"))
j = L.join_asof(orc.select("t", "m1", "m2", "oracle", "ext").sort("t"), on="t", strategy="backward")
j = j.with_columns(pl.min_horizontal("m1", "m2").alias("mn"), pl.max_horizontal("m1", "m2").alias("mx"))
j = j.with_columns(((pl.col("mk") - pl.col("mn")).abs() < 1e-6).alias("eq_min"), ((pl.col("mk") - pl.col("mx")).abs() < 1e-6).alias("eq_max"),
                   ((pl.col("mk") >= pl.col("mn") - 1e-6) & (pl.col("mk") <= pl.col("mx") + 1e-6)).alias("between"))
print("  liquidation blocks", j.height, "| mark == min(m1,m2):", j["eq_min"].mean(), "== max:", j["eq_max"].mean(), "within [min,max]:", j["between"].mean())
print(j.filter(pl.col("t") < dt.datetime(2026, 10, 28, 20, 3)).select("t", "mk", "m1", "m2", "oracle", "ext").head(12))

print("\n3. margin-state actions on GOOGL")
s = pl.read_parquet(f"{T}/state.parquet").filter(pl.col("asset") == ASSET)
liqd = set(pl.read_parquet(LIQ).filter(pl.col("coin") == COIN)["address"].to_list())
print("  actions", s.height, "by", s["u"].n_unique(), "accounts | by liquidated accounts:", s.filter(pl.col("u").is_in(list(liqd))).height,
      "| types", s["type"].value_counts().to_dicts())
print("  whale:", s.filter(pl.col("u") == WHALE).select("t", "type", "fields", "ok").to_dicts())
