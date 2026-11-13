"""Crash book push, split three ways: the attacker, the other traders, the vault. python score_push_split.py DIR MARK [MARK ...]
DIR holds {orc,tk,rd,log}_GOOGL_{MARK}_{base|cCAP_f0.06_dSECS}.csv and log_{MARK}.txt (sim/prop_runs.sh with the vault log)."""
import sys, os, re, json, numpy as np, polars as pl
T = sys.argv[1]; ATT = 4294967286; L = 20
def marks(n):
    o = pl.read_csv(f"{T}/orc_{n}.csv").drop_nulls(["bid", "ask", "last"]).sort("h")
    raw = np.median(np.stack([o["m1"].to_numpy(), o["m2"].to_numpy(), np.median(np.stack([o["bid"].to_numpy(), o["ask"].to_numpy(), o["last"].to_numpy()]), axis=0)]), axis=0) / 1e6
    m = raw.copy()
    for i in range(1, len(m)): m[i] = min(max(raw[i], m[i - 1] * 0.99), m[i - 1] * 1.01)
    return o.select("h", "ms").with_columns(mk=pl.Series(m))
def need(n):
    lg = pl.read_csv(f"{T}/log_{n}.csv"); o = marks(n)
    f = lg.join(o.select("h", "ms"), on="h", how="left").with_columns(pl.col("ms").forward_fill().backward_fill()).with_columns(q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz"))).sort("ms").with_columns(cq=pl.col("q").cum_sum(), cash=(-pl.col("q") * pl.col("px")).cum_sum())
    g = o.sort("ms").join_asof(f.select("ms", "cq", "cash"), on="ms").with_columns(pl.col("cq").fill_null(0.0), pl.col("cash").fill_null(0.0))
    val = (g["cash"] + g["cq"] * g["mk"]).to_numpy(); mm = (g["cq"].abs() * g["mk"] / (2 * L)).to_numpy()
    return max(0.0, float((mm - val).max())), max(0.0, float((-val).max()))
def tk(n):
    t = pl.read_csv(f"{T}/tk_{n}.csv").with_columns(ntl=pl.col("q").abs() * pl.col("px"))
    return t.filter(pl.col("u") == ATT), t.filter(pl.col("u") != ATT)
def liq(n):
    r = pl.read_csv(f"{T}/rd_{n}.csv").filter((pl.col("sim_rounds") > 0) & (pl.col("u") != ATT))
    return set(r["u"].to_list()), float(r["sim_filled"].sum())
print(f"{'design / case':30} | lift bp, s>1% | attacker: bought $M, sold by liquidation sh, taken over $M, left of capital | others: extra accounts liquidated, extra taken over $M | vault: capital need $M (no push), avoid ADL $M (no push), inherited $M")
for MK in sys.argv[2:]:
    b = f"GOOGL_{MK}_base"; nb, ab = need(b); _, ob = tk(b); ub, _ = liq(b); tb = set(ob["u"].to_list()); mb = marks(b)
    log = open(f"{T}/log_{MK}.txt").read()
    for cap in ("1e6", "5e6"):
        for d in (60, 300):
            tag = f"c{cap}_f0.06_d{d}"; n = f"GOOGL_{MK}_{tag}"
            if not os.path.exists(f"{T}/tk_{n}.csv"): continue
            j = marks(n).join(mb, on="h", suffix="_b").with_columns(g=(pl.col("mk") / pl.col("mk_b") - 1) * 1e4)
            a, o = tk(n); u, _ = liq(n); nn, an = need(n)
            m = re.search(rf"{n}: PROP ACCOUNT: capital \$(\d+) \| end position (\S+) equity at last mark \$(-?\d+) \| liquidated (\S+) shares, taken over (\S+)", log)
            p = re.search(rf"{n}: PROP: price \S+ \| bought (\S+) shares for \$(\d+)", log)
            C = float(m[1]); left = float(m[3])
            newacc = (u | set(o["u"].to_list())) - (ub | tb)
            print(f"{MK+' '+tag:30} | {j['g'].max():4.0f} {j.filter(pl.col('g') > 100).height*3:4} | {float(p[2])/1e6:6.1f} {float(m[4]):9.0f} {a['ntl'].sum()/1e6:6.2f}  {left/C*100:5.1f}% (${(C-left)/1e6:.2f}M lost) | {len(newacc):4} {(o['ntl'].sum()-ob['ntl'].sum())/1e6:6.2f} | {nn/1e6:5.2f} ({nb/1e6:.2f}) {an/1e6:5.2f} ({ab/1e6:.2f}) {(a['ntl'].sum()+o['ntl'].sum())/1e6:6.1f}")
