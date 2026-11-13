"""Per-user liquidation fee rate -> a `liq` column in PREP/fees.arrow (also written by prep.py for new preps).

HL charges a liquidated account its own base taker rate (net of builder fees): 0.9 bp, 0.864 bp with the 4% discount, etc.
(GOOGL 10-28: the liquidated side's rate equals the user's net taker rate on every account that has both.)
The rate is a property of the account (its fee tier), not an outcome. Per user, in order:
  1. its net rate on its liquidation fills (liquidated side) on any xyz coin that day,
  2. its net taker rate on any xyz coin that day (fills > $100, so fee rounding does not move it),
  3. the median of 1. over all liquidated accounts that day.
Before: one per-coin rate from both sides of the liquidation fills, makers included: 0.43-0.56 bp instead of 0.86-0.9.
Usage: python fees_liq.py PREP_DIR FILLS_PARQUET [FILLS_PARQUET ...]"""
import sys, polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)
ssum, fsum_by = detio.ssum, detio.fsum_by
PREP, FILES = sys.argv[1], sys.argv[2:]

def liq_rates(fills: pl.DataFrame, users: pl.DataFrame) -> pl.DataFrame:
    a = fills.filter(pl.col("crossed")).with_columns(ntl=pl.col("price").cast(float) * pl.col("size").cast(float),
                                                    net=pl.col("fee").cast(float) - pl.col("builder_fee").cast(float).fill_null(0.0))
    lq = a.filter(pl.col("is_liquidation").fill_null(False), pl.col("liquidation_method") == "market")
    lq = fsum_by(lq, ["address"], ["net", "ntl"]).select("address", r1=pl.col("net") / pl.col("ntl"))
    tk = a.filter(pl.col("liquidation_method").is_null(), pl.col("ntl") > 100)
    tk = fsum_by(tk, ["address"], ["net", "ntl"]).select("address", r2=pl.col("net") / pl.col("ntl"))
    med = float(lq["r1"].median()) if lq.height else None
    return (users.join(lq, left_on="user", right_on="address", how="left").join(tk, left_on="user", right_on="address", how="left")
            .select("uid", pl.coalesce("r1", "r2", pl.lit(med)).alias("liq"), src=pl.when(pl.col("r1").is_not_null()).then(1).when(pl.col("r2").is_not_null()).then(2).otherwise(3)))

if __name__ == "__main__":
    cols = ["coin", "address", "price", "size", "fee", "builder_fee", "crossed", "is_liquidation", "liquidation_method"]
    fills = pl.concat([pl.scan_parquet(f).select(cols) for f in FILES]).collect()
    users = pl.read_ipc(f"{PREP}/users.arrow")
    r = liq_rates(fills, users)
    fe = pl.read_ipc(f"{PREP}/fees.arrow", memory_map=False)
    fe = fe.drop("liq", strict=False).join(r.select(pl.col("uid").alias("u"), "liq"), on="u", how="left")
    fe = fe.with_columns(pl.col("liq").fill_null(r["liq"].median()))
    fe.write_ipc(f"{PREP}/fees.arrow")
    print(PREP, "liq fee rate by source (1 own liquidations, 2 own taker fills, 3 median):", r.group_by("src").len().sort("src").rows(),
          " median bp", round(r["liq"].median() * 1e4, 3))
