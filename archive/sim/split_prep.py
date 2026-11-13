"""Split-whale attack harness: a prep directory where one account is split into N identical accounts.

Usage: python split_prep.py SRC_PREP ADDR_PREFIX N OUT_DIR
The account's start position (acc_init: q, cm) and every account event (acc_events: fills' size and fee, margin
amounts) are divided by N over N accounts with the same entry, leverage and margin mode: the same position, held as N
accounts with the same liquidation price. The first keeps the original uid (the book's orders and triggers stay on it);
the others get new uids (users / fees / acc_av extended). Every other file is linked from SRC_PREP.
"""
import os, sys
import polars as pl

src, prefix, n, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
os.makedirs(out, exist_ok=True)
users = pl.read_ipc(f"{src}/users.arrow")
w = users.filter(pl.col("user").str.starts_with(prefix))["uid"]
assert w.len() == 1, f"{prefix}: {w.len()} matches"
w = int(w[0])
new = [int(users["uid"].max()) + 1 + k for k in range(n - 1)]
ids = [w] + new
done = set()

def clones(t, col="u", scale=()):
    """rows of uid w replaced by n rows (one per clone, in order), `scale` columns divided by n"""
    t = t.with_row_index("_r")
    wr = t.filter(pl.col(col) == w)
    parts = [wr.with_columns(pl.lit(u, pl.UInt32).alias(col), *[(pl.col(c) / n) for c in scale], pl.lit(k, pl.UInt32).alias("_k"))
             for k, u in enumerate(ids)]
    rest = t.filter(pl.col(col) != w).with_columns(pl.lit(0, pl.UInt32).alias("_k"))
    return pl.concat([rest] + parts).sort("_r", "_k").drop("_r", "_k")

def write(name, t):
    t.write_ipc(f"{out}/{name}.arrow"); done.add(f"{name}.arrow")

write("acc_init", clones(pl.read_ipc(f"{src}/acc_init.arrow"), scale=("q", "cm")))
write("acc_events", clones(pl.read_ipc(f"{src}/acc_events.arrow"), scale=("amt", "fee")))  # k 1: leverage (amt unused)
av = pl.read_ipc(f"{src}/acc_av.arrow")
write("acc_av", clones(av, scale=("av",)) if av.filter(pl.col("u") == w).height else av)
write("fees", clones(pl.read_ipc(f"{src}/fees.arrow")))
addr = users.filter(pl.col("uid") == w)["user"][0]
write("users", pl.concat([users, pl.DataFrame({"uid": new, "user": [f"{addr}_split{k + 1}" for k in range(n - 1)]}, schema=users.schema)]))
for f in os.listdir(src):
    if f not in done and not os.path.exists(f"{out}/{f}"):
        os.symlink(os.path.abspath(f"{src}/{f}"), f"{out}/{f}")
print(f"split uid {w} into {ids}")
