"""Every internal -> external hand-over in the local extract days: the jump of the oracle onto the external price.

Regime per relayer update: internal when |oracle/E - 1| > 0.5 bp (E frozen at the close, oracle = book EMA), external
otherwise. A hand-over is the first update where E moves after being frozen >= 10 min with the oracle off E (internal). At each hand-over:
  jump     = E_first / oracle_last - 1             (the gap today's oracle walks at 50 bp per update)
  gap_P    = E_first / P - 1,  P = P2/P4's trade price (volume-weighted median of the latest voluntary xyz fills)
  hold     = P4b/P4d's hold condition at the first external update: |E - P| > d E (book not checked here)
Also the reverse (external -> internal) for completeness. Usage: python handover_screen.py DAY [DAY ...]
"""
import json, os, sys
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = "0x4000000000000000000000000000000000000001"
LEV = {u["name"]: u["maxLeverage"] for u in json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]}
rows = []
for day in sys.argv[1:]:
    fills = (pl.scan_parquet(f"{ROOT}/data/xyzdata/all{day}.parquet")
             .filter(pl.col("crossed"), ~pl.col("is_liquidation").fill_null(False), pl.col("address") != VAULT)
             .select("coin", ms=pl.col("timestamp").dt.epoch("ms"), px=pl.col("price").cast(pl.Float64),
                     ntl=pl.col("price").cast(pl.Float64) * pl.col("size").cast(pl.Float64)).sort("coin", "ms").collect())
    fg = {k[0]: v for k, v in fills.group_by("coin")}
    orc = (pl.scan_parquet(f"{ROOT}/data/extract{day}/tables/oracle.parquet").filter(pl.col("ext").is_not_null())
           .select("coin", ms=pl.col("t").dt.epoch("ms"), e="ext", o="oracle", m2="m2").sort("coin", "ms").collect())
    for (c,), o in orc.group_by("coin"):
        if c not in LEV:
            continue
        d = 1.0 / LEV[c]
        t, e, oo = o["ms"].to_numpy(), o["e"].to_numpy(), o["o"].to_numpy()
        intl = np.abs(oo / e - 1) > 5e-5
        f = fg.get(c)
        frozen_since = 0
        for i in range(1, len(t)):
            if e[i] == e[i - 1]:
                continue
            # E moves at i; it was frozen over [frozen_since, i-1]
            j = frozen_since; frozen_since = i
            if t[i - 1] - t[j] < 600_000 or not intl[i - 1]:
                continue
            kind = "int->ext"
            P = np.nan; age = np.nan
            if f is not None and f.height:
                tm, px, nt = f["ms"].to_numpy(), f["px"].to_numpy(), f["ntl"].to_numpy()
                k = np.searchsorted(tm, t[i], side="right")
                if k > 0:
                    cum = np.concatenate([[0.0], np.cumsum(nt)])
                    avg30 = nt.sum() * 30_000 / max(tm[-1] - tm[0], 1)
                    V = max(cum[k] - cum[np.searchsorted(tm, t[i] - 30_000)], avg30)
                    s = max(np.searchsorted(cum, cum[k] - V, side="right") - 1, 0)
                    w, p = nt[s:k], px[s:k]; q = np.argsort(p); cw = np.cumsum(w[q])
                    P = p[q][np.searchsorted(cw, cw[-1] / 2)]; age = (t[i] - tm[k - 1]) / 60_000
            # where E goes in the next 30 min (does the jump stick?)
            k30 = np.searchsorted(t, t[i] + 1_800_000)
            e30 = e[min(k30, len(e) - 1)]
            rows.append(dict(day=day, coin=c, lev=LEV[c], kind=kind, utc=str(np.datetime64(int(t[i]), "ms"))[11:19],
                             prev_min=round((t[i - 1] - t[j]) / 60_000), jump_pct=round((e[i] / oo[i - 1] - 1) * 100, 2),
                             gap_P_pct=round((e[i] / P - 1) * 100, 2) if P == P else None, p_age_min=round(age, 1) if age == age else None,
                             E_30m_vs_first_pct=round((e30 / e[i] - 1) * 100, 2), band_pct=round(d * 100, 1),
                             hold=bool(P == P and abs(e[i] - P) > d * e[i])))
r = pl.DataFrame(rows)
r.write_csv(f"{ROOT}/data/scen/handover_screen.csv")
pl.Config.set_tbl_rows(80); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(20)
h = r.filter(pl.col("kind") == "int->ext")
print("hand-overs int->ext:", h.height, "coins", h["coin"].n_unique(), "| ext->int:", r.height - h.height)
print(h.with_columns(a=pl.col("jump_pct").abs()).sort("a", descending=True).drop("a").head(25))
print("hold would fire:", h["hold"].sum())
print(h.select(pl.col("jump_pct").abs().quantile(q).alias(f"q{q}") for q in (0.5, 0.9, 0.99)), h.select((pl.col("jump_pct").abs() / pl.col("band_pct")).max()))
