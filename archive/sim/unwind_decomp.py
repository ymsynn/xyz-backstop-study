"""Real vault unwind, decomposed against trade.xyz's external price E (no simulation; the vault's own fills).

PnL = cushion + drift + execution - fees, exactly:
  cushion   = sum over takeovers q (E_t - px)        (position value vs E when inherited)
  drift     = sum over updates Q_t (E_t+1 - E_t)     (inventory held while E moves)
  execution = sum over unwind fills q_sold (px - E_t) signed (sold vs E at the fill)
Counterfactual schedules (exponential, constant fraction per 3 s update): the drift term is exact for any schedule
(E is exogenous: the Nasdaq price does not react to xyz's vault); the execution term is reported as the real one per
unit sold, scaled, i.e. NOT modelled for faster selling (a lower bound on the cost of speed).
Usage: python unwind_decomp.py
"""
import json, os
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = {"GOOGL": "1028", "INTC": "1029", "AMZN": "1029"}
f = json.load(open(f"{ROOT}/data/bs_fills.json"))
rows, sched = [], []
for c, day in EV.items():
    x = [r for r in f if r["coin"] == f"xyz:{c}" and pl.datetime(2026, 1, 1) is not None]
    d = pl.DataFrame([{"ms": r["time"], "px": float(r["px"]), "sz": float(r["sz"]), "buy": r["side"] == "B", "liq": bool(r.get("liquidation")),
                       "fee": float(r["fee"])} for r in x]).sort("ms")
    d = d.filter(pl.from_epoch("ms", "ms").dt.strftime("%m%d") == day)
    E = (pl.read_parquet(f"{ROOT}/data/extract{day}/tables/oracle.parquet").filter(pl.col("coin") == f"xyz:{c}", pl.col("ext").is_not_null())
         .select(ms=pl.col("t").dt.epoch("ms"), E="ext").sort("ms"))
    d = d.join_asof(E, on="ms", strategy="backward").with_columns(q=pl.when("buy").then(pl.col("sz")).otherwise(-pl.col("sz")))
    cush = d.filter("liq").select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item()
    exe = d.filter(~pl.col("liq")).select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item()
    fees = d["fee"].sum()
    # inventory path on E's grid
    t0, t1 = d["ms"].min(), d["ms"].max()
    g = E.filter(pl.col("ms") >= t0 - 1, pl.col("ms") <= t1 + 1)
    em, ev = g["ms"].to_numpy(), g["E"].to_numpy()
    cq = np.cumsum(d["q"].to_numpy()); dm = d["ms"].to_numpy()
    Q = np.array([cq[np.searchsorted(dm, t, side="right") - 1] if np.searchsorted(dm, t, side="right") > 0 else 0.0 for t in em])
    drift = float(np.sum(Q[:-1] * np.diff(ev)))
    # residual: E at fill vs E on the grid (timing between fills and updates)
    pnl_real = sum(float(r["closedPnl"]) for r in x if pl.from_epoch(pl.Series([r["time"]]), "ms").dt.strftime("%m%d")[0] == day) - fees
    inh = d.filter("liq").select((pl.col("q").abs() * pl.col("px")).sum()).item()
    end_q = float(cq[-1])
    rows.append(dict(coin=c, inherited_musd=round(inh / 1e6, 2), cushion=round(cush), drift=round(drift), execution=round(exe), fees=round(fees),
                     sum=round(cush + drift + exe - fees), realized=round(pnl_real), end_q=round(end_q, 3),
                     exec_bp=round(exe / d.filter(~pl.col("liq")).select((pl.col("sz") * pl.col("px")).sum()).item() * 1e4, 1)))
    # counterfactual exponential schedules on the same takeovers (drift exact; execution at the real bp per unit)
    tk = d.filter("liq")
    tkm, tkq = tk["ms"].to_numpy(), tk["q"].to_numpy()
    for frac in (0.0025, 0.005, 0.01, 0.02, 0.05, 0.2, 1.0):
        inv, k, dr, sold = 0.0, 0, 0.0, 0.0
        for j in range(len(em) - 1):
            while k < len(tkm) and tkm[k] <= em[j]:
                inv += tkq[k]; k += 1
            s = frac * inv; inv -= s; sold += abs(s) * ev[j]
            dr += inv * (ev[j + 1] - ev[j])
        sched.append(dict(coin=c, frac_per_update=frac, half_life_s=round(3 * np.log(0.5) / np.log(1 - frac)) if frac < 1 else 0, drift=round(dr)))
r = pl.DataFrame(rows); s = pl.DataFrame(sched)
pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(20); pl.Config.set_tbl_rows(60)
print(r)
print(s.pivot(on="coin", index=["frac_per_update", "half_life_s"], values="drift").with_columns(total=pl.col("GOOGL") + pl.col("INTC") + pl.col("AMZN")))
r.write_csv(f"{ROOT}/data/scen/unwind_decomp.csv"); s.write_csv(f"{ROOT}/data/scen/unwind_sched.csv")
