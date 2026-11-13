"""Rewrite the merge key of a prep folder's event streams for another in-block ordering (other files are hard-linked).

Usage: python rekey.py PREP_DIR OUT_DIR ORDERING
  bundle_orders_first  per bundle: orders, then cancels / schedules / relayer updates (prep.py default)
  hl                   per bundle: cancels and schedules, then post-only (Alo) orders, then the rest (other orders,
                       relayer updates) in action order
  hl_block             same classes, per block (all cancels of the block first, ...)
  proposer             action order (b, i, j)
  cancels_first        per bundle: cancels (by oid / cloid), then orders, then schedules / relayer updates
  cancels_first_seq    per bundle: cancels, then everything else in action order
  cloid_first          per bundle: cancelByCloid, then orders, then cancels by oid / schedules / relayer updates
  alo_cancel_rest      per bundle: post-only placements, then cancels, then everything else in action order
  alocancel_rest       per bundle: post-only placements and cancels together in action order, then everything else
Sources whose rows get different priorities are split so that every output stream stays sorted on the new key
(the orders stream becomes events_0 = other orders and events_4 = post-only orders).
key = ((h*64 + b)*4 + pri) * 2^24 + i*2^10 + j   (per-block variant: ((h*4 + pri)*64 + b) * 2^24 + ...)
"""
import sys, os, glob
import polars as pl
SRC, OUT, ORD = sys.argv[1:4]
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(SRC):
    if not f.startswith("events_") and not os.path.exists(os.path.join(OUT, f)):
        os.link(os.path.join(SRC, f), os.path.join(OUT, f))
k, tif = pl.col("k"), pl.col("tif")
if ORD == "bundle_orders_first":
    pri = pl.when(k == 3).then(0).otherwise(1)
elif ORD in ("hl", "hl_block"):
    pri = pl.when(k.is_in([0, 1, 2])).then(0).when((k == 3) & (tif == 0)).then(1).otherwise(2)
elif ORD == "cancels_first":
    pri = pl.when(k.is_in([0, 1])).then(0).when(k == 3).then(1).otherwise(2)
elif ORD == "cancels_first_seq":
    pri = pl.when(k.is_in([0, 1])).then(0).otherwise(1)
elif ORD == "cloid_first":
    pri = pl.when(k == 1).then(0).when(k == 3).then(1).otherwise(2)
elif ORD == "alo_cancel_rest":
    pri = pl.when((k == 3) & (tif == 0)).then(0).when(k.is_in([0, 1])).then(1).otherwise(2)
elif ORD == "alocancel_rest":
    pri = pl.when(((k == 3) & (tif == 0)) | k.is_in([0, 1])).then(0).otherwise(1)
elif ORD == "proposer":
    pri = pl.lit(0)
elif ":" in ORD:
    # explicit spec, e.g. "alo:0,cancel:1,sched:2,order:2,oracle:2" (classes: alo, order, cancel, sched, oracle)
    cls = dict(x.split(":") for x in ORD.split(","))
    P = lambda c: pl.lit(int(cls[c]))
    pri = (pl.when((k == 3) & (tif == 0)).then(P("alo")).when(k == 3).then(P("order")).when(k.is_in([0, 1])).then(P("cancel"))
           .when(k == 2).then(P("sched")).otherwise(P("oracle")))
else:
    sys.exit(f"unknown ordering {ORD}")
pri = pri.cast(pl.Int64)
h, b, i, j = (pl.col(c).cast(pl.Int64) for c in "hbij")
key = (((h * 4 + pri) * 64 + b) if ORD == "hl_block" else ((h * 64 + b) * 4 + pri)) * (1 << 24) + i * (1 << 10) + j
for f in sorted(glob.glob(os.path.join(SRC, "events_*.arrow"))):
    name = os.path.basename(f)
    lf = pl.scan_ipc(f).with_columns(key.alias("key"))
    if name.startswith("events_0_"):
        # orders: post-only and the rest in separate streams (each stays in execution order, hence sorted)
        lf.filter(pl.col("tif") != 0).sink_ipc(os.path.join(OUT, name), compression="lz4")
        lf.filter(pl.col("tif") == 0).sink_ipc(os.path.join(OUT, name.replace("events_0_", "events_4_")), compression="lz4")
    else:
        lf.sink_ipc(os.path.join(OUT, name), compression="lz4")
print("rekeyed", ORD)
