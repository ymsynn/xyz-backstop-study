"""Order priority for the engine's book (HL priority orders): PREP_DIR/prio.arrow (oid, rank).

Usage: python prio.py PREP_DIR TABLES_DIR ASSET
The order table's `grouping` field carries {"p": N}, the priority bid (rate N / 1e8). At one price HL queues by arrival,
except that an order goes ahead of lower-bid orders that arrived less than ~399 ms before it (the engine's book):
    "na" = {"p": 0} (no bid) < {"p": 1} < {"p": 2} < ...       rank = 1, 1, N + 1
Fitted on GOOGL 2026-10-28's same-price exceptions: every real jump of a newer, higher-bid order came within 398.8 ms,
FIFO held from 399.1 ms; treating p 0 below "na" made 443 wrong jumps (they are the same: no bid).
Only ranks other than 1 are written. A modify keeps its original's rank (its own row has no grouping).
"""
import sys
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, T, ASSET = sys.argv[1], sys.argv[2], int(sys.argv[3])
o = (pl.scan_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET, pl.col("oid").is_not_null())
     .select("h", "b", "i", "j", "oid", "oid_in", "type", "grouping").collect().sort("h", "b", "i", "j"))
rank = (pl.when(pl.col("grouping").is_null()).then(None).when(pl.col("grouping") == '"na"').then(1)
        .otherwise(pl.col("grouping").str.extract(r'"p":\s*(\d+)').cast(pl.Int64).map_elements(lambda p: 1 if p == 0 else p + 1, return_dtype=pl.Int64)))
o = o.with_columns(rank.alias("rank"))
r = dict(zip(*o.filter(pl.col("rank").is_not_null()).select("oid", "rank").get_columns()))
# modifies: inherit along the chain, in order
inherited = 0
for oid, oin, rk in o.filter(pl.col("rank").is_null() & pl.col("oid_in").is_not_null()).select("oid", "oid_in", "rank").iter_rows():
    try:
        src = int(oin)
    except (TypeError, ValueError):
        continue
    if src in r and oid not in r:
        r[oid] = r[src]; inherited += 1
out = pl.DataFrame({"oid": list(r.keys()), "rank": list(r.values())}, schema={"oid": pl.Int64, "rank": pl.Int32}).filter(pl.col("rank") != 1)
out.write_ipc(f"{PREP}/prio.arrow")
print(f"{PREP}: {len(r)} orders with a known grouping ({inherited} by modify), {out.height} written with rank != 1;",
      "rank counts", sorted(out.group_by("rank").len().rows())[:8])
