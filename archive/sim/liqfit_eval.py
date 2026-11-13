"""Over-fill study: per account, real vs sim market-liquidation rounds (from RDETAIL_OUT dumps of sim/liqfit_runs.sh).
Usage: python liqfit_eval.py TAG [COIN ...]"""
import sys, polars as pl
TAG = sys.argv[1]; COINS = sys.argv[2:] or ["GOOGL", "INTC", "AMZN"]
for c in COINS:
    d = pl.read_csv(f"data/scen/liqfit/det_{c}_{TAG}.csv")
    g = d.group_by("u").agg(
        rr=(pl.col("src") == "real").sum(), sr=(pl.col("src") == "sim").sum(),
        rf=pl.col("filled").filter(pl.col("src") == "real").sum(), sf=pl.col("filled").filter(pl.col("src") == "sim").sum(),
        rh=pl.col("h").filter(pl.col("src") == "real").min(), sh=pl.col("h").filter(pl.col("src") == "sim").min())
    b = g.filter((pl.col("rr") > 0) & (pl.col("sr") > 0))
    b = b.with_columns(diff=pl.col("sf") - pl.col("rf"), rel=(pl.col("sf") - pl.col("rf")) / pl.col("rf"))
    same = (b["diff"].abs() < 1e-6).sum()
    more, less = b.filter(pl.col("diff") > 1e-6), b.filter(pl.col("diff") < -1e-6)
    print(f"{c}: both {b.height}  same {same}  sim more {more.height} ({more['diff'].sum():.1f} sh)  sim less {less.height} ({less['diff'].sum():.1f} sh)  | real filled {b['rf'].sum():.0f}")
    print("   more: extra rounds", (more["sr"] > more["rr"]).sum(), " same rounds", (more["sr"] == more["rr"]).sum(), " fewer", (more["sr"] < more["rr"]).sum(),
          "| rel diff quantiles", [round(x, 4) for x in [more["rel"].quantile(q) for q in (.1, .5, .9)]] if more.height else "")
    print("   less: extra rounds", (less["sr"] > less["rr"]).sum(), " same rounds", (less["sr"] == less["rr"]).sum(), " fewer", (less["sr"] < less["rr"]).sum())
    print("   only sim:", g.filter((pl.col("rr") == 0) & (pl.col("sr") > 0)).height, " only real:", g.filter((pl.col("rr") > 0) & (pl.col("sr") == 0)).height)
