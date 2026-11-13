"""Scorecard of the final run (sim/final/run_final.sh): today's rules and the proposal, one engine build.
python sim/final/score_final.py [DIR=data/scen/final]. Walks and normal sessions: sim/score/ramp_eval.py and sim/score/normal_eval.py on
DIR/r_dn, r_up, onw, normal (printed by `MARKS=... zsh sim/runs/ramp_runs.sh` and `sim/runs/normal_runs.sh`). Capital need = max(MM of the vault's position - its value),
need to avoid ADL = max(-value), marks recomputed with Hyperliquid's 1% per update and the lone-quote rule for a one-sided book."""
import sys, os, re, json, numpy as np, polars as pl
K = sys.argv[1] if len(sys.argv) > 1 else "data/scen/final"
DES = [("today", "today", "today"), ("proposal", "pkgm3q1800", "lead3q1800")]
# SCORE_EXTRA="label:mark tag:design tag ...": more rule sets beside the two, for a comparison (outputs in the same folder)
DES += [tuple(x.split(":")) for x in os.environ.get("SCORE_EXTRA", "").split()]
ML = {u["name"][4:]: u["maxLeverage"] for u in json.load(open("data/xyzmeta.json"))[0]["universe"]}
ATT = 4294967286

def marks(T, n):
    o = pl.read_csv(f"{T}/orc_{n}.csv").sort("h")
    bid, ask, last = (o[c].to_numpy().astype(float) for c in ("bid", "ask", "last"))   # nulls -> nan
    full = ~(np.isnan(bid) | np.isnan(ask) | np.isnan(last))
    bk = np.where(full, np.nanmedian(np.stack([bid, ask, last]), axis=0), np.where(np.isnan(bid), ask, bid))   # lone quote
    m1, m2 = o["m1"].to_numpy().astype(float), o["m2"].to_numpy().astype(float)
    raw = np.median(np.stack([m1, m2, np.where(np.isnan(bk), m1, bk)]), axis=0) / 1e6
    ok = ~np.isnan(bk); m = raw.copy(); prev = None
    for i in range(len(m)):
        if not ok[i]: m[i] = prev if prev is not None else raw[i]
        elif prev is not None: m[i] = min(max(raw[i], prev * 0.99), prev * 1.01)
        prev = m[i]
    return o.select("h", "ms").with_columns(mk=pl.Series(m))

def tkf(T, n):
    f = f"{T}/tk_{n}.csv"
    if not (os.path.exists(f) and os.path.getsize(f) > 0): return None
    # notional at the transfer price; a position whose bankruptcy price is negative (a cross account already in deficit from
    # its other markets) is counted at the mark, so that it adds to the total instead of subtracting from it
    t = pl.read_csv(f, schema_overrides={"q": pl.Float64, "px": pl.Float64, "mark": pl.Float64})
    return t.with_columns(ntl=pl.col("q").abs() * pl.when(pl.col("px") > 0).then(pl.col("px")).otherwise(pl.col("mark")))

def vault(T, n, L):
    t = tkf(T, n); r = dict(tk=t.height if t is not None else 0, ntl=float(t["ntl"].sum()) if t is not None and t.height else 0.0, need=0.0, adl=0.0)
    f = f"{T}/log_{n}.csv"
    if os.path.exists(f) and os.path.getsize(f) > 0:
        lg = pl.read_csv(f)
        if lg.height:
            o = marks(T, n)
            g = lg.join(o.select("h", "ms"), on="h", how="left").with_columns(pl.col("ms").forward_fill().backward_fill()).with_columns(q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz"))).sort("ms").with_columns(cq=pl.col("q").cum_sum(), cash=(-pl.col("q") * pl.col("px")).cum_sum())
            g = o.sort("ms").join_asof(g.select("ms", "cq", "cash"), on="ms").with_columns(pl.col("cq").fill_null(0.0), pl.col("cash").fill_null(0.0))
            val = (g["cash"] + g["cq"] * g["mk"]).to_numpy(); mm = (g["cq"].abs() * g["mk"] / (2 * L)).to_numpy()
            r.update(need=max(0.0, float((mm - val).max())), adl=max(0.0, float((-val).max())))
    return r

def tot(rows, keys): return {k: sum(r[k] for r in rows) for k in keys}
def lift(T, a, b):
    j = marks(T, a).join(marks(T, b), on="h", suffix="_b").with_columns(g=(pl.col("mk") / pl.col("mk_b") - 1) * 1e4)
    return j
def M(x): return f"{x/1e6:.3f}"
def row(name, vals): print(f"| {name:58} | " + " | ".join(f"{v:22}" for v in vals) + " |")
def have(p): return os.path.exists(p)

print(open(f"{K}/BUILD.txt").read().strip().replace("\n", " | ") if have(f"{K}/BUILD.txt") else "")
row("Test", [d[0] for d in DES]); row("-" * 58, ["-" * 22] * len(DES))
v = [tot([vault(f"{K}/crash", f"{c}_{d}_{ds}", ML[c]) for c, d in (("GOOGL", "1028"), ("INTC", "1029"), ("AMZN", "1029"))], ("need", "adl", "ntl")) for _, _, ds in DES]
row("3 crashes: capital need / avoid ADL / inherited $M", [f"{M(x['need'])} / {M(x['adl'])} / {x['ntl']/1e6:.2f}" for x in v])
for c, d in (("GOOGL", "1028"), ("INTC", "1029"), ("AMZN", "1029")):
    v = [vault(f"{K}/crash", f"{c}_{d}_{ds}", ML[c]) for _, _, ds in DES]
    row(f"  {c} {d}: capital need / avoid ADL / inherited $M", [f"{M(x['need'])} / {M(x['adl'])} / {x['ntl']/1e6:.2f}" for x in v])
v = [vault(f"{K}/skhx", f"SKHX_0727_{ds}", 10) for _, _, ds in DES]
row("SKHX: capital need / avoid ADL / inherited $M", [f"{M(x['need'])} / {M(x['adl'])} / {x['ntl']/1e6:.2f}" for x in v])
def off_book(T, n):
    o = pl.read_csv(f"{T}/orc_{n}.csv").drop_nulls(["bid", "ask", "last"]).select("h", mid=(pl.col("bid") + pl.col("ask")) / 2e6).join(marks(T, n), on="h")
    g = ((o["mk"] / o["mid"] - 1).abs() * 100); return f"{100*(g > 2).mean():.1f}% / {100*(g > 5).mean():.1f}%"
row("SKHX: updates with the mark > 2% / > 5% from xyz's book", [off_book(f"{K}/skhx", f"SKHX_0727_{ds}") for _, _, ds in DES])
row("5 isolated-only replays: ADL $k", [f"{sum(vault(f'{K}/iso', f'{c}_{d}_{ds}', 10)['ntl'] for c, d in (('NOW','1028'),('LITE','1028'),('MRVL','1028'),('RDDT','1029'),('NET','1105')))/1e3:.1f}" for _, _, ds in DES])
row("6 quiet days: inherited $k", [f"{sum(vault(f'{K}/quiet', f'{c}_{d}_{ds}', ML[c])['ntl'] for d in ('1020','1021') for c in ('GOOGL','INTC','AMZN'))/1e3:.1f}" for _, _, ds in DES])
L3 = {"GOOGL": 20, "INTC": 10, "AMZN": 20}
for f, lab in (("f120", "Stuck feed 120 s"), ("f0", "  same runs, feed not stuck")):
    v = [tot([vault(f"{K}/stuck_{f}", f"{c}_freeze_{mk}", L3[c]) for c in L3], ("need", "adl", "ntl")) for _, mk, _ in DES]
    row(f"{lab}: capital need / avoid ADL / inherited $M", [f"{M(x['need'])} / {M(x['adl'])} / {x['ntl']/1e6:.2f}" for x in v])
OOS = (("GOOGL", "1022"), ("META", "1022"), ("SILVER", "1022"), ("GOLD", "1030"), ("SPCX", "1030"), ("BRENTOIL", "0910"), ("CL", "0910"))
v = [tot([vault(f"{K}/oos", f"{c}_{d}_{mk}", ML[c]) for c, d in OOS], ("tk", "ntl", "need", "adl")) for _, mk, _ in DES]
row("Out of sample (7): takeovers / inherited $M", [f"{x['tk']} / {x['ntl']/1e6:.2f}" for x in v])
row("Out of sample (7): capital need / avoid ADL $k", [f"{x['need']/1e3:.1f} / {x['adl']/1e3:.1f}" for x in v])
for c, d in OOS:
    v = [vault(f"{K}/oos", f"{c}_{d}_{mk}", ML[c]) for _, mk, _ in DES]
    row(f"  {c} {d}: takeovers / inherited $k", [f"{x['tk']} / {x['ntl']/1e3:.0f}" for x in v])
T = f"{K}/spike"
for tg in ("a30s", "a3s", "q30s"):
    out = []
    for _, mk, _ in DES:
        mv = min(float(lift(T, f"{c}_{mk}_{tg}", f"{c}_{mk}_base")["g"].min()) for c in ("GOOGL", "AMZN"))
        ex = sum(tkf(T, f"{c}_{mk}_{tg}")["ntl"].sum() - tkf(T, f"{c}_{mk}_base")["ntl"].sum() for c in ("GOOGL", "AMZN"))
        out.append(f"{ex/1e6:.2f} / {mv:.0f}")
    row(f"Bad print -5% ({tg}): extra takeovers $M / mark move bp", out)
for c, Lc in (("CL", 20), ("GOLD", 25)):
    T = f"{K}/closed_{c}"; out = []
    for _, mk, _ in DES:
        ls = [float(lift(T, f"{c}_{mk}_c{cap}_f0.06_d{d}", f"{c}_{mk}_base")["g"].max()) for cap in ("1e6", "5e6") for d in (60, 240, 900)]
        out.append(f"{min(ls):.0f}-{max(ls):.0f} / {tkf(T, f'{c}_{mk}_c5e6_f0.06_d900')['ntl'].sum()/1e6:.2f}")
    row(f"Closed {c} book push: mark lift bp / worst takeovers $M", out)
for d, lab in (("quiet_up", "+6%"), ("quiet_dn", "-6%")):
    T = f"{K}/{d}"; P0 = 1793164200000; out = []
    for _, mk, _ in DES:
        j = lift(T, f"GOOGL_{mk}_c5e6_f{'0.06' if d == 'quiet_up' else '-0.06'}_d9000", f"GOOGL_{mk}_base")
        at = lambda s: float(j.filter(pl.col("ms") <= P0 + s * 1000)["g"][-1])
        out.append(f"{at(300):.0f} / {at(3600):.0f} / {at(9000):.0f}")
    row(f"Quiet feed, $5M book push {lab}: move at 5 min / 1 h / 2.5 h bp", out)
T = f"{K}/push"
for cap in ("1e6", "5e6"):
    for d in (60, 300):
        out = []
        for _, mk, _ in DES:
            n = f"GOOGL_{mk}_c{cap}_f0.06_d{d}"; b = f"GOOGL_{mk}_base"; x = vault(T, n, 20); xb = vault(T, b, 20)
            log = open(f"{K}/push.log").read(); m = re.search(rf"{n}: PROP ACCOUNT: capital \$(\d+) \| end position \S+ equity at last mark \$(-?\d+)", log)
            lost = (float(m[1]) - float(m[2])) / float(m[1]) * 100 if m else float("nan")
            t = tkf(T, n); own = float(t.filter(pl.col("u") == ATT)["ntl"].sum()) if t is not None else 0.0
            out.append(f"{M(x['need'])} ({M(xb['need'])}) {lost:.0f}% {own/1e6:.1f}")
        row(f"Crash push ${cap} {d} s: need $M (no push), attacker lost, its pos. taken over $M", out)
print()
print("Adaptive attack: positions liquidated in the 300 s from the start of the walk, book + vault, $M (walk alone / + push 15 s / + push 60 s)")
def liq300(T, n, W0):
    if not have(f"{T}/orc_{n}.csv"): return float("nan")
    o = pl.read_csv(f"{T}/orc_{n}.csv").select("h", "ms").sort("h")
    t = pl.read_csv(f"{T}/tk_{n}.csv", schema_overrides={"q": pl.Float64, "px": pl.Float64}).sort("h").join_asof(o, on="h").filter((pl.col("ms") >= W0) & (pl.col("ms") < W0 + 300000) & (pl.col("u") != ATT))
    r = pl.read_csv(f"{T}/rd_{n}.csv").filter((pl.col("sim_h1") > 0) & (pl.col("u") != ATT)).sort("sim_h1").join_asof(o.rename({"h": "sim_h1"}), on="sim_h1").filter((pl.col("ms") >= W0) & (pl.col("ms") < W0 + 300000))
    px = float(t["px"].mean() or 0) or float(pl.read_csv(f"{T}/orc_{n}.csv")["ext"].mean()) / 1e6
    return float((t["q"].abs() * t["px"]).sum()) + float(r["sim_filled"].sum()) * px
SL = [("GOOGL", "night", 1793163600000, "1e6"), ("GOOGL", "day", 1793226600000, "5e6"), ("AMZN", "night", 1793250000000, "1e6"), ("AMZN", "day", 1793313000000, "5e6"),
      ("INTC", "night", 1793250000000, "1e6"), ("INTC", "day", 1793313000000, "5e6"), ("SKHX", "day2", 1785121200000, "1e6")]
for c, slot, W0, cap in SL:
    for sgn, f in (("dn", "-0.10"), ("up", "+0.10")):
        T = f"{K}/adapt/{c}_{slot}_{sgn}"
        if not os.path.isdir(T): continue
        out = []
        for _, mk, _ in DES:
            a = [liq300(T, f"{c}_{mk}_{tg}", W0) for tg in ("base", f"c{cap}_f{f}_d15", f"c{cap}_f{f}_d60")]
            out.append(" / ".join("-" if x != x else f"{x/1e6:.2f}" for x in a))
        row(f"{c} {slot}, walk {'-' if sgn == 'dn' else '+'}10% then ${cap} push", out)
