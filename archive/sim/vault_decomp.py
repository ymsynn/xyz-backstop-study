"""Vault unwind policies decomposed against trade.xyz's external price E (sim/vault_runs.sh logs).

cushion   = sum over takeovers q (E - px)       position value vs E when inherited
drift     = sum over E updates Q (E' - E)        inventory carried while E moves: exact for any schedule (E is the
                                                 underlying's price, exogenous to xyz)
execution = sum over unwind fills q (E - px)     sold vs E at the fill: depends on the replayed book (open loop)
Not a vault PnL result (reporting rule): the execution term relies on a book whose makers do not react.
Usage: python vault_decomp.py
"""
import os
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = f"{ROOT}/data/scen/vault"
PREP = {"GOOGL": "prep_GOOGL_1028", "INTC": "prep_INTC_1029", "AMZN": "prep_AMZN_1029"}
rows = []
for c, prep in PREP.items():
    b = pl.read_ipc(f"{ROOT}/data/{prep}/blocks.arrow").select("h", "ms")
    E = pl.read_csv(f"{V}/orc_{c}.csv").select("ms", (pl.col("ext") / 1e6).alias("E")).filter(pl.col("E") > 0).sort("ms")
    em, ev = E["ms"].to_numpy(), E["E"].to_numpy()
    for pkg in ("today", "p4d_rb2"):
        for pol in ("clip", "c2", "c5", "fair", "fair0"):
            f = f"{V}/log_{c}_{pkg}_{pol}.csv"
            if not os.path.exists(f):
                continue
            d = (pl.read_csv(f).join(b, on="h", how="left").sort("ms", maintain_order=True)
                 .join_asof(E, on="ms", strategy="backward")
                 .with_columns(q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz"))))
            tk, uw = d.filter(pl.col("kind") == 0), d.filter(pl.col("kind") == 1)
            cush = tk.select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item()
            exe = uw.select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item()
            dm, cq = d["ms"].to_numpy(), np.cumsum(d["q"].to_numpy())
            k = np.searchsorted(dm, em, side="right") - 1
            Q = np.where(k >= 0, cq[np.clip(k, 0, None)], 0.0)
            drift = float(np.sum(Q[:-1] * np.diff(ev)))
            inh = tk.select((pl.col("q").abs() * pl.col("px")).sum()).item()
            # time from first takeover until 90% of the inherited shares are sold
            t0 = tk["ms"].min(); tot = tk["sz"].sum()
            cs = uw.with_columns(c=pl.col("sz").cum_sum()).filter(pl.col("c") >= 0.9 * tot)
            t90 = (cs["ms"].min() - t0) / 60_000 if cs.height else None
            below = uw.filter(((pl.col("q") < 0) & (pl.col("px") < pl.col("E"))) | ((pl.col("q") > 0) & (pl.col("px") > pl.col("E"))))
            rows.append(dict(coin=c, pkg=pkg, policy=pol, inherited_musd=round(inh / 1e6, 2), cushion=round(cush), drift=round(drift), execution=round(exe),
                             exec_bp=round(exe / max(uw.select((pl.col("sz") * pl.col("px")).sum()).item(), 1) * 1e4, 1),
                             worse_than_E_musd=round(below.select((pl.col("sz") * pl.col("px")).sum()).item() / 1e6, 2), t90_min=None if t90 is None else round(t90, 1)))
r = pl.DataFrame(rows)
r.write_csv(f"{V}/decomp.csv")
pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(20); pl.Config.set_tbl_rows(60)
print(r)
print(r.group_by("pkg", "policy").agg(pl.col("inherited_musd", "cushion", "drift", "execution").sum(), pl.col("t90_min").max()).with_columns(after_takeover=pl.col("drift") + pl.col("execution")).sort("pkg", "policy"))
