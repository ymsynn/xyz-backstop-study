"""Infer match-time margin caps of opening takers from a PM_DIAG run (tape-walk).

Usage: python margin.py PREP_DIR TABLES_DIR ASSET FILLS PM_DIAG_CSV
An opening (non reduce-only, non trigger) taker whose real fills stop short of its order size while pure matching finds
liquidity beyond its real worst price ran out of margin: HL stops filling once the order's initial margin exceeds what
the account has free. The account's free collateral is not observable from one asset, so the binding cap is taken
from the real outcome, in notional: PREP_DIR/margin_caps.arrow (t_oid, cap_ntl in 1e6 * $). With a fixed leverage,
margin = notional / leverage, so the same notional cap holds at counterfactual prices.
"""
import sys
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)
ssum, fsum_by = detio.ssum, detio.fsum_by

PREP, T, ASSET, FILLS, DIAG = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
d = pl.read_csv(DIAG).filter(pl.col("m") >= 0)
rf = pl.read_ipc(f"{PREP}/real_fills.arrow").rename({"t_oid": "oid"})
tot = (rf.group_by("oid").agg(pl.col("sz").sum().alias("rtot"), pl.col("px").max().alias("rhi"), pl.col("px").min().alias("rlo"))
       .join(fsum_by(rf.with_columns((pl.col("px").cast(pl.Float64) * pl.col("sz").cast(pl.Float64) / 1e6).alias("rntl")), ["oid"], ["rntl"]), on="oid"))
x = d.join(tot, on="oid").filter(pl.col("sim_sz") > pl.col("real_sz"))
x = x.filter((pl.col("buy") & (pl.col("mpx") > pl.col("rhi"))) | (~pl.col("buy") & (pl.col("mpx") < pl.col("rlo"))))
o = (pl.scan_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET)
     .select("oid", "reduce_only", "trigger", (pl.col("sz") * 1e6).round().cast(pl.Int64).alias("osz")).collect())
x = x.join(o, on="oid", how="left").filter(~pl.col("reduce_only").fill_null(False) & pl.col("trigger").is_null())
# opening: the real fills open or extend a position
dirs = (pl.scan_parquet(FILLS).filter(pl.col("crossed")).select(pl.col("order_id").cast(pl.Int64).alias("oid"), "direction")
        .filter(pl.col("oid").is_in(x["oid"].unique().implode())).collect()
        .group_by("oid").agg(pl.col("direction").str.starts_with("Open").all().alias("opening")))
caps = (x.join(dirs, on="oid").filter(pl.col("opening") & (pl.col("rtot") < pl.col("osz")))
        .group_by("oid").agg(pl.col("rntl").first()).select(pl.col("oid").alias("t_oid"), pl.col("rntl").round(0).cast(pl.Int64).alias("cap_ntl")).sort("t_oid"))
caps.write_ipc(f"{PREP}/margin_caps.arrow")
print("margin caps:", caps.height, "takers, total capped notional $", round(caps["cap_ntl"].sum() / 1e6))
