"""Fit HL's liquidation equity stop: replay each stopped sim round's fills (STOP_DUMP of sim/liqfit_runs.sh) under candidate
stop rules and compare the predicted round size with HL's real one (RDETAIL_OUT).
Rules (x = size taken so far in the round, state after it valued at the mark):
  lin     the engine's rule: eq_before_fill - y (slip + fee px) >= bsf MM(remaining)      (no release inside a fill)
  post    the post-fill state (margin release included) >= bsf MM(remaining)
  orig    post-fill equity >= bsf MM(position at the round's start)
  pct     post-fill equity / MM(remaining) >= k, k fitted per round (prints the implied interval)
Usage: python liqfit_stop.py TAG [COIN ...]"""
import sys, numpy as np, polars as pl
TAG = sys.argv[1]; COINS = sys.argv[2:] or ["GOOGL", "INTC", "AMZN"]
LOT = {"GOOGL": 0.001, "INTC": 0.01, "AMZN": 0.001}

def after(r, y, iso):
    sgn = 1.0 if r["q"] > 0 else -1.0          # position side; the liquidation reduces it
    q, e, m, px = r["q"], r["e"], r["m"], r["px"]
    pnl = (px - e) * y * sgn
    m2 = m - r["fee"] * px * y + pnl
    if iso: m2 -= max(m + (px - e) * q, 0.0) * y / abs(q)
    q2 = q - sgn * y
    return m2 + (r["mark"] - e) * q2, abs(q2)

def mm(r, qabs):          # bsf * MM(remaining) = c_fix + c_thr * |q|
    return r["c_fix"] + r["c_thr"] * qabs

for c in COINS:
    lot = LOT[c]
    s = pl.read_csv(f"data/scen/liqfit/stop_{c}_{TAG}.csv")
    d = pl.read_csv(f"data/scen/liqfit/det_{c}_{TAG}.csv")
    real = d.filter(pl.col("src") == "real").group_by("u", "h").agg(rf=pl.col("filled").sum())
    sim = d.filter(pl.col("src") == "sim").select("u", "h", "req", sf="filled")
    rounds = sim.join(real, on=["u", "h"]).filter(pl.col("sf") < pl.col("req") - 1e-9)   # stopped in the sim, same block as HL
    res = []
    for (u, h, req, sf, rf) in rounds.iter_rows():
        rows = s.filter((pl.col("u") == u) & (pl.col("h") == h)).to_dicts()
        if not rows: continue
        # isolated if margin moved by more than pnl - fee between consecutive fills
        iso = True
        if len(rows) > 1:
            r0, r1 = rows[0], rows[1]
            sg = 1.0 if r0["q"] > 0 else -1.0
            cross_m1 = r0["m"] - r0["fee"] * r0["px"] * r0["f"] + (r0["px"] - r0["e"]) * r0["f"] * sg
            iso = abs(r1["m"] - cross_m1) > 1e-6 * max(1.0, abs(r0["m"]))
        q0 = abs(rows[0]["q0"])
        pred = {}
        for rule in ("lin", "post", "orig"):
            tot = 0.0; stopped = False
            for r in rows:
                def ok(y):
                    if rule == "lin":
                        eq = r["m"] + (r["mark"] - r["e"]) * r["q"]
                        slip = (r["mark"] - r["px"]) if r["q"] > 0 else (r["px"] - r["mark"])
                        return eq - y * (slip + r["fee"] * r["px"]) >= mm(r, abs(r["q"]) - y) - 1e-9
                    eq, qa = after(r, y, iso)
                    return eq >= (mm(r, qa) if rule == "post" else mm(r, q0)) - 1e-9
                n = int(round(r["f"] / lot)); lo, hi = 0, n
                if ok(n * lot): lo = n
                else:
                    while hi - lo > 1:
                        mid = (lo + hi) // 2
                        if ok(mid * lot): lo = mid
                        else: hi = mid
                tot += lo * lot
                if lo < n: stopped = True; break
            pred[rule] = (tot, stopped)
        # implied k for the post rule at HL's real size: k in (ratio(rf+lot), ratio(rf)]
        def ratio_at(x):
            acc = 0.0
            for r in rows:
                if x <= acc + r["f"] + 1e-9:
                    eq, qa = after(r, x - acc, iso); return eq / (mm(r, qa) / r["bsf"])
                acc += r["f"]
            return np.nan
        res.append(dict(u=u, h=h, iso=iso, req=req, rf=rf, sf=sf, lin=pred["lin"][0], post=pred["post"][0], post_cens=not pred["post"][1],
                        orig=pred["orig"][0], k_hi=ratio_at(rf), k_lo=ratio_at(rf + lot)))
    t = pl.DataFrame(res)
    print(f"\n{c}: stopped rounds {t.height} (iso {t['iso'].sum()})")
    for rule in ("lin", "post", "orig"):
        dif = t[rule] - t["rf"]
        print(f"  {rule:5s} exact {(dif.abs() < lot / 2).sum():4d}  over {(dif > lot / 2).sum():4d} ({dif.filter(dif > 0).sum():8.2f} sh)  under {(dif < -lot / 2).sum():4d} ({dif.filter(dif < 0).sum():8.2f} sh)")
    print("  implied k (eq / MM of remaining at HL's stop) quantiles: hi", [round(t["k_hi"].quantile(q), 4) for q in (.05, .25, .5, .75, .95)],
          " lo", [round(t["k_lo"].quantile(q), 4) for q in (.05, .25, .5, .75, .95)])
    t.write_csv(f"data/scen/liqfit/fit_{c}_{TAG}.csv")
