"""Offline screen over every xyz coin: P4's trade price P vs the relayer's external price E, minute by minute.

P_t = volume-weighted median of the latest voluntary xyz taker fills covering V_t = max(volume of the last 30 s, the
day's average volume per 30 s) (P2/P4's rule, no age limit). E_t = the relayer's externalPerpPx at its last update.
Every minute is labelled by regime from the relayer itself: 'external' when the published oracle equals E (live feed,
the session P4 changes), 'internal' when it does not (closed home market / weekend: E frozen at the close, oracle = EMA of
the book). US regular hours (13:30-20:00 UTC) are flagged separately (P4 keeps today's formula there).

1. Gate: minutes where |P - E| > d E (d = 1/maxLev), i.e. where P4's band would hold. Also the staleness of P (age of its
   newest trade) when it happens.
2. Discovery screen: episodes where |P - E| / E > THR (default 1%) for at least 2 minutes. Each episode is resolved over
   the next 30 min: 'xyz led' if E moved at least half the gap toward P's side, 'xyz reverted' if P came back to within
   a quarter of the gap of E without E moving, else 'unresolved'.
Usage: python gate_screen.py DAY [DAY ...]   (needs data/xyzdata/all{DAY}.parquet, data/extract{DAY}/tables/oracle.parquet)
"""
import json, os, sys
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THR = float(os.environ.get("THR", "0.01"))
VAULT = "0x4000000000000000000000000000000000000001"
meta = json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]
LEV = {u["name"]: u["maxLeverage"] for u in meta}
gate_rows, ep_rows = [], []
for day in sys.argv[1:]:
    fills = (pl.scan_parquet(f"{ROOT}/data/xyzdata/all{day}.parquet")
             .filter(pl.col("crossed"), ~pl.col("is_liquidation").fill_null(False), pl.col("address") != VAULT)
             .select("coin", ms=pl.col("timestamp").dt.epoch("ms"), px=pl.col("price").cast(pl.Float64),
                     ntl=pl.col("price").cast(pl.Float64) * pl.col("size").cast(pl.Float64))
             .sort("coin", "ms").collect())
    orc = (pl.scan_parquet(f"{ROOT}/data/extract{day}/tables/oracle.parquet").filter(pl.col("ext").is_not_null())
           .select("coin", ms=pl.col("t").dt.epoch("ms"), e="ext", orc="oracle").sort("coin", "ms").collect())
    t0 = int(orc["ms"].min() // 60_000 * 60_000) + 60_000
    grid = np.arange(t0, int(orc["ms"].max()), 60_000)
    hh = (grid % 86_400_000) / 3_600_000
    usreg = (hh >= 13.5) & (hh < 20)
    fg = {c: d for c, d in fills.group_by("coin")}
    for (c,), o in orc.group_by("coin"):
        f = fg.get((c,))
        if f is None or f.height < 2 or c not in LEV:
            continue
        d = 1.0 / LEV[c]
        tm, px, nt = f["ms"].to_numpy(), f["px"].to_numpy(), f["ntl"].to_numpy()
        cum = np.concatenate([[0.0], np.cumsum(nt)])
        avg30 = nt.sum() * 30_000 / max(tm[-1] - tm[0], 1)
        oe_t, oe, oo = o["ms"].to_numpy(), o["e"].to_numpy(), o["orc"].to_numpy()
        P, E, AGE, INT = [], [], [], []
        for t in grid:
            i = np.searchsorted(tm, t, side="right")          # trades [0, i) are at or before t
            k = np.searchsorted(oe_t, t, side="right") - 1
            if i == 0 or k < 0:
                P.append(np.nan); E.append(np.nan); AGE.append(np.nan); INT.append(False); continue
            INT.append(abs(oo[k] / oe[k] - 1) > 5e-5)
            j30 = np.searchsorted(tm, t - 30_000, side="left")
            V = max(cum[i] - cum[j30], avg30)
            s = max(np.searchsorted(cum, cum[i] - V, side="right") - 1, 0)
            w, p = nt[s:i], px[s:i]
            o_ = np.argsort(p); cw = np.cumsum(w[o_])
            P.append(p[o_][np.searchsorted(cw, cw[-1] / 2)]); E.append(oe[k]); AGE.append((t - tm[i - 1]) / 60_000)
        P, E, AGE, INT = np.array(P), np.array(E), np.array(AGE), np.array(INT)
        gap = (P - E) / E
        okall = ~np.isnan(gap)
        ok = okall & ~INT & ~usreg          # P4's regime: external session outside US regular hours
        hold = ok & (np.abs(gap) > d)
        gate_rows.append(dict(day=day, coin=c, lev=LEV[c], minutes=int(ok.sum()), internal_min=int((okall & INT).sum()), vol_kusd=round(nt.sum() / 1e3),
                              gap_p50_bp=round(float(np.median(np.abs(gap[ok]))) * 1e4, 1) if ok.any() else None, gap_max_pct=round(float(np.max(np.abs(gap[ok]))) * 100, 2) if ok.any() else None,
                              hold_min=int(hold.sum()), stale_p95_min=round(float(np.nanquantile(AGE, .95)), 1)))
        # discovery episodes
        big = okall & ~usreg & (np.abs(gap) > THR)
        n = len(grid); a = 0
        while a < n:
            if not big[a]:
                a += 1; continue
            b = a
            while b + 1 < n and big[b + 1] and np.sign(gap[b + 1]) == np.sign(gap[a]):
                b += 1
            if b - a + 1 >= 2:
                g0, e0, p0 = gap[a], E[a], P[a]
                # was the feed live during the episode? (distinct E values; a frozen feed = closed home market, internal mode)
                e_live = int(len(np.unique(E[a:b + 1])))
                regime = "internal" if INT[a:b + 1].mean() > 0.5 else "external"
                fut = slice(b + 1, min(n, b + 31))
                ef, pf = E[fut], P[fut]
                led = np.any(np.sign(g0) * (ef - e0) >= 0.5 * abs(p0 - e0))
                rev = np.any(np.abs(pf - ef) <= 0.25 * abs(p0 - e0)) and not led
                ep_rows.append(dict(day=day, coin=c, regime=regime, start_utc=str(np.datetime64(int(grid[a]), "ms"))[:16], minutes=b - a + 1,
                                    gap_pct=round(float(g0 * 100), 2), max_gap_pct=round(float(np.max(np.abs(gap[a:b + 1])) * 100), 2),
                                    p_age_min=round(float(AGE[a]), 1), e_values=e_live, outcome="xyz led" if led else ("xyz reverted" if rev else "unresolved")))
            a = b + 1
g = pl.DataFrame(gate_rows); e = pl.DataFrame(ep_rows)
g.write_csv(f"{ROOT}/data/scen/gate_screen.csv"); e.write_csv(f"{ROOT}/data/scen/discovery_episodes.csv")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(200); pl.Config.set_tbl_cols(12)
print("coin-days", g.height, "| minutes", g["minutes"].sum(), "| gate would hold:", g["hold_min"].sum(), "minutes on", (g["hold_min"] > 0).sum(), "coin-days")
print("internal minutes (oracle != E):", g["internal_min"].sum())
print(g.sort("gap_max_pct", descending=True, nulls_last=True).head(15))
print("episodes |P-E| >", THR * 100, "% for 2+ min:", e.height)
if e.height:
    print(e.group_by("outcome").agg(pl.len(), pl.col("max_gap_pct").median()))
    print(e.group_by("regime", "outcome").agg(pl.len(), pl.col("minutes").median().alias("min_p50"), pl.col("minutes").max().alias("min_max"),
                                             pl.col("max_gap_pct").median().alias("gap_p50"), pl.col("max_gap_pct").max().alias("gap_max")).sort("regime", "outcome"))
    for r in ("external", "internal"):
        print(r, "- largest episodes"); print(e.filter(pl.col("regime") == r).sort("max_gap_pct", descending=True).head(12))
