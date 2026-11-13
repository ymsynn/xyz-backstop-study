"""Add the liquidated-side flag (liq_side) to an existing prep's acc_events, so it does not have to be rebuilt.

Usage: python liqside.py PREP_DIR COIN FILLS [FILLS_NEXT]
Both sides of a liquidation fill carry its liquidation_method, and a market round's direction does not say which side
was liquidated; only the fill's is_liquidation does. The clearing needs it: in ENDO=0 the liquidated account's fills are
simulated, while its counterparties' fills are the real ones (prep.py writes the same column).
The liquidation rows (k = 4) of acc_events are rebuilt in prep's order (fills by block and trade_id, stable by block) and
checked row by row against the stored ones before the column is written.
"""
import sys
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, COIN, FILLS = sys.argv[1:4]
FN = sys.argv[4] if len(sys.argv) > 4 else None
blocks = pl.read_ipc(f"{PREP}/blocks.arrow")
users = pl.read_ipc(f"{PREP}/users.arrow")
uid = dict(zip(users["user"], users["uid"]))
h_of_ms = dict(zip(blocks["ms"], blocks["h"]))
snap_block = __import__("json").load(open(f"{PREP}/meta.json"))["snap_block"]
cols = ["price", "size", "side", "timestamp", "address", "trade_id", "crossed", "liquidation_method", "is_liquidation"]
fills = (pl.concat([pl.scan_parquet(f).filter(pl.col("coin") == COIN).select(cols) for f in [FILLS] + ([FN] if FN else [])])
         .with_columns(pl.col("timestamp").cast(pl.Int64).alias("ms"))
         .filter(pl.col("ms") <= blocks["ms"].max()).unique(["trade_id", "crossed"], keep="first", maintain_order=True).collect())
fl = (fills.with_columns(pl.col("ms").replace_strict(h_of_ms, default=None).alias("h")).filter(pl.col("h") > snap_block).sort("h", "trade_id", maintain_order=True)
      .filter(pl.col("liquidation_method").is_not_null())
      .select("h", pl.col("address").replace_strict(uid, return_dtype=pl.UInt32).alias("u"), (pl.col("side") == "buy").alias("cross"),
              pl.col("price").cast(pl.Float64).alias("lev"), pl.col("size").cast(pl.Float64).alias("amt"),
              pl.col("is_liquidation").fill_null(False).alias("liq_side")))
acc = pl.read_ipc(f"{PREP}/acc_events.arrow", memory_map=False).with_row_index("_r")
k4 = acc.filter(pl.col("k") == 4)
assert k4.height == fl.height, (k4.height, fl.height)
same = ((k4["h"] == fl["h"]) & (k4["u"] == fl["u"]) & (k4["cross"] == fl["cross"])
        & ((k4["lev"] - fl["lev"]).abs() < 1e-9) & ((k4["amt"] - fl["amt"]).abs() < 1e-9))
assert same.all(), f"{(~same).sum()} liquidation rows do not line up"
flag = pl.DataFrame({"_r": k4["_r"], "liq_side": fl["liq_side"]})
acc = acc.drop("liq_side", strict=False).join(flag, on="_r", how="left").with_columns(pl.col("liq_side").fill_null(False)).sort("_r").drop("_r")
acc.write_ipc(f"{PREP}/acc_events.arrow")
print(f"{PREP}: {k4.height} liquidation rows, {int(fl['liq_side'].sum())} on the liquidated side, {k4.height - int(fl['liq_side'].sum())} counterparties")
