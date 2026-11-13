"""Attack preps: a copy of a prep directory with synthetic attacker accounts added to the account events (the book
is untouched: the attacker's legs cross each other, so they print nothing on other people's orders).

Usage: python attack_prep.py SRC OUT MODE ARGS...
  put T_MS NTL LEV   free put on the vault: X opens long NTL isolated at LEV (margin = IM: the most it may withdraw
                     down to), Y opens the same short, cross, unmargined in the sim (never liquidated), at T_MS at
                     the external price
  washoi T0 T1 NTL   wash OI: X long / Y short NTL, both cross, opened at T0 and closed at T1 (inflates OI between)
  ladder ADDR K STEP the account split into K accounts whose start liquidation prices are STEP apart (more margin on
                     the lower ones), the day's fills split equally: liquidation prices beyond the cluster band
Prints the synthetic uids. Every other file is linked from SRC.
"""
import os, sys
import polars as pl

src, out, mode, args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
os.makedirs(out, exist_ok=True)
users = pl.read_ipc(f"{src}/users.arrow")
ev = pl.read_ipc(f"{src}/acc_events.arrow")
blk = pl.read_ipc(f"{src}/blocks.arrow").sort("ms")
done = set()
def write(name, t): t.write_ipc(f"{out}/{name}.arrow"); done.add(f"{name}.arrow")
def h_at(ms): return int(blk.filter(pl.col("ms") >= ms)["h"][0])
def ext_at(ms):
    # the relayer's external price at the last update before ms (events type 5 carry it); fall back to the last fill
    f = pl.read_ipc(f"{src}/real_fills.arrow").filter(pl.col("ms") <= ms).sort("ms")
    return float(f["px"][-1]) / 1e6
def row(h, u, k, cross, lev, amt, fee=0.0, dir_iso=False):
    return dict(h=h, b=0, i=0, u=u, k=k, cross=cross, lev=float(lev), amt=float(amt), fee=float(fee), bstop=False, dir_iso=dir_iso,
                dir_liq=False, lmark=float("nan"), phase={1: 0, 2: 0, 3: 1, 4: 2}.get(k, 3), liq_side=False)
new_u = []
def uid():
    u = int(users["uid"].max()) + 1 + len(new_u); new_u.append(u); return u
rows = []
if mode == "put":
    t, ntl, lev = int(args[0]), float(args[1]), float(args[2])
    h, px = h_at(t), ext_at(t)
    x, y = uid(), uid()
    q = round(ntl / px, 3)
    rows += [row(h, x, 1, False, lev, 0), row(h, y, 1, True, 20, 0),
             row(h, x, 3, True, px, q, dir_iso=True), row(h, y, 3, False, px, q)]
    print(f"put: X {x} long {q} @ {px} lev {lev} (margin ${q * px / lev:,.0f}), Y {y} short")
elif mode == "washoi":
    t0, t1, ntl = int(args[0]), int(args[1]), float(args[2])
    x, y = uid(), uid()
    for t, buy in ((t0, True), (t1, False)):
        h, px = h_at(t), ext_at(t)
        q = round(ntl / px, 3) if buy else q
        rows += [row(h, x, 1, True, 20, 0), row(h, y, 1, True, 20, 0), row(h, x, 3, buy, px, q), row(h, y, 3, not buy, px, q)]
    print(f"washoi: {x}/{y} {q} shares from {t0} to {t1}")
elif mode == "ladder":
    prefix, k, step = args[0], int(args[1]), float(args[2])
    w = int(users.filter(pl.col("user").str.starts_with(prefix))["uid"][0])
    ids = [w] + [uid() for _ in range(k - 1)]
    ai = pl.read_ipc(f"{src}/acc_init.arrow")
    r = ai.filter(pl.col("u") == w)
    parts = [r.with_columns(pl.lit(u, pl.UInt32).alias("u"), pl.col("q") / k, pl.col("cm") / k,
                            (pl.col("lp") * (1 - j * step) if r["q"][0] > 0 else pl.col("lp") * (1 + j * step)).alias("lp")) for j, u in enumerate(ids)]
    write("acc_init", pl.concat([ai.filter(pl.col("u") != w)] + parts))
    we = ev.filter(pl.col("u") == w)
    ev = pl.concat([ev.filter(pl.col("u") != w)] + [we.with_columns(pl.lit(u, pl.UInt32).alias("u"), pl.col("amt") / k, pl.col("fee") / k) for u in ids])
    print(f"ladder: {w} -> {ids}, start liquidation prices {step:.1%} apart")
if rows:
    ev = pl.concat([ev, pl.DataFrame(rows, schema=ev.schema)])
ev = ev.sort(["h", "phase", "b", "i"], maintain_order=True)
write("acc_events", ev)
addr = [f"0xattack{u:08d}" for u in new_u]
write("users", pl.concat([users, pl.DataFrame({"uid": new_u, "user": addr}, schema=users.schema)]))
fees = pl.read_ipc(f"{src}/fees.arrow")
write("fees", pl.concat([fees, pl.DataFrame({"u": new_u, "taker": [0.0] * len(new_u), "maker": [0.0] * len(new_u)}, schema=fees.schema)]))
for f in os.listdir(src):
    if f not in done and not os.path.exists(f"{out}/{f}"):
        os.symlink(os.path.abspath(f"{src}/{f}"), f"{out}/{f}")
print("uids", new_u)
