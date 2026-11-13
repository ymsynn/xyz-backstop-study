"""Contagion pass input: the extract's oracle table with each simulated coin's published inputs (m1, m2) replaced by the
first-pass run of one design (data/scen/joint/orc_{COIN}_{DAY}_{DES}.csv), matched by block h; other coins keep the real
ones. crossacc.py then marks every cross account's other xyz positions at median(m1, m2, last trade) of that design.
Usage: python sim/prep/orc_merge.py ORACLE_PARQUET JOINT_DIR DAY DES OUT_PARQUET"""
import glob, os, sys
import polars as pl
src, J, day, des, out = sys.argv[1:6]
o = pl.read_parquet(src)
n = 0
for f in sorted(glob.glob(f"{J}/orc_*_{day}_{des}.csv")):
    c = "xyz:" + os.path.basename(f)[4:].split(f"_{day}_")[0]
    r = pl.read_csv(f).select("h", (pl.col("m1") / 1e6).alias("m1s"), (pl.col("m2") / 1e6).alias("m2s")).unique("h", keep="last")
    o = (o.join(r.with_columns(coin=pl.lit(c)), on=["coin", "h"], how="left")
          .with_columns(pl.coalesce("m1s", "m1").alias("m1"), pl.coalesce("m2s", "m2").alias("m2")).drop("m1s", "m2s"))
    n += 1
o.write_parquet(out); print(f"orc_merge {des}: {n} coins replaced -> {out}")
