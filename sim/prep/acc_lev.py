"""Leverage and margin mode of accounts that hold no position on the coin at the day's snapshot.

The snapshot lists positions, so it shows an account's leverage on a coin only if it holds the coin. An account that opens
during the day was given the coin's maximum leverage (and, on an isolated-only market, margin = notional / max leverage):
too little margin when its real setting is lower, hence liquidations the real account never had (xyz:NOW 2026-10-28:
replay 10x, next snapshot 2x; xyz:MRVL: 4x and 2x).

The setting is per account and coin and only changes by an updateLeverage action, which the command stream shows. So for an
account that (a) is not in the day's snapshot on this coin, (b) holds the coin in the NEXT snapshot, and (c) sent no
updateLeverage on it during the day (acc_events k = 1), the next snapshot's leverage and margin mode already applied at
the start of the day. Those accounts are added to acc_init.arrow as flat rows (q = 0) carrying them.
Not covered, and reported: accounts that open and close within the day (absent from both snapshots) and accounts whose
first updateLeverage of the day comes after their first trade.

Usage: python sim/prep/acc_lev.py PREP_DIR "SNAP_NEXT_GLOB" COIN      (after prep.py; idempotent)"""
import sys, glob
import polars as pl
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, SNAP_NEXT, COIN = sys.argv[1:4]
users = pl.read_ipc(f"{PREP}/users.arrow", memory_map=False)
ai = pl.read_ipc(f"{PREP}/acc_init.arrow", memory_map=False)
ai = ai.filter(~((pl.col("q") == 0) & pl.col("e").eq(0) & pl.col("lp").is_nan() & pl.col("cm").is_nan()))   # rows of an earlier run
ae = pl.read_ipc(f"{PREP}/acc_events.arrow", memory_map=False)
lev_users = set(ae.filter(pl.col("k") == 1)["u"].unique().to_list())
trade = ae.filter(pl.col("k") == 3)
first_trade = trade.group_by("u").agg(pl.col("h").min().alias("h_trade"))
first_lev = ae.filter(pl.col("k") == 1).group_by("u").agg(pl.col("h").min().alias("h_lev"))
in_snap = set(ai["u"].to_list())
new = sorted(set(trade["u"].unique().to_list()) - in_snap)                 # trade the coin, no position at the snapshot
sn = (pl.concat([pl.read_parquet(f) for f in sorted(glob.glob(SNAP_NEXT))]).filter(pl.col("market") == COIN, pl.col("size") != 0)
      .join(users, on="user", how="inner").select(pl.col("uid").alias("u"), pl.col("leverage").cast(pl.Float64).alias("lev"),
                                                  (pl.col("leverage_type") == "isolated").alias("iso")).unique("u", keep="first", maintain_order=True))
add = sn.filter(pl.col("u").is_in(new), ~pl.col("u").is_in(list(lev_users))).sort("u")
rows = add.select(pl.col("u").cast(ai.schema["u"]), pl.lit(0.0).alias("q"), pl.lit(0.0).alias("e"), pl.lit(float("nan")).alias("lp"),
                  "iso", "lev", pl.lit(float("nan")).alias("cm")).select(ai.columns)
pl.concat([ai, rows], how="vertical_relaxed").write_ipc(f"{PREP}/acc_init.arrow")
# what is known about the leverage of the accounts that open during the day
ft = pl.DataFrame({"u": new}, schema={"u": first_trade.schema["u"]}).join(first_trade, on="u", how="left").join(first_lev, on="u", how="left")
before = ft.filter(pl.col("h_lev").is_not_null() & (pl.col("h_lev") <= pl.col("h_trade"))).height
after = ft.filter(pl.col("h_lev").is_not_null() & (pl.col("h_lev") > pl.col("h_trade"))).height
# the accounts whose leverage at their first trade is not observed: sim/prep/lev_fit.py fits it on isolated-only markets
known = set(add["u"].to_list()) | set(ft.filter(pl.col("h_lev").is_not_null() & (pl.col("h_lev") <= pl.col("h_trade")))["u"].to_list())
pl.DataFrame({"u": [u for u in new if u not in known]}, schema={"u": pl.UInt32}).write_csv(f"{PREP}/lev_unknown.csv")
maxlev = float(ai["lev"].max()) if ai.height else float("nan")
print(f"accounts trading {COIN} without a position at the snapshot: {len(new)} | leverage from the next snapshot: {add.height} "
      f"(below the snapshot's highest {maxlev:g}x: {add.filter(pl.col('lev') < maxlev).height}) | from an updateLeverage before the first trade: {before} "
      f"| updateLeverage only after the first trade: {after} | no evidence (kept at the maximum): {len(new) - add.height - before - after}")
