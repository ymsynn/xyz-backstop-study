"""Score the full package (sim/package_runs.sh) layer by layer, without vault PnL (reporting rule).

Crashes: inherited notional, value at takeover vs E, underwater takeovers (as takeover_score.py with FAIR_SRC=ext);
book liquidation (accounts, rounds, shares sold); vault unwind vs E (exposure $M.min, drift risk 1 sd, execution, sold
below E). Quiet days: accounts liquidated, rounds, takeovers.
Usage: python package_eval.py
"""
import os
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS, Q = f"{ROOT}/data/scen/runs", f"{ROOT}/data/scen/pkg"
PREP = {"GOOGL": "prep_GOOGL_1028", "INTC": "prep_INTC_1029", "AMZN": "prep_AMZN_1029"}
PKS = ["today", "p4d", "p4d_rb2", "pkg"] + [p for p in ("pkgc", "pkgt", "pkgs", "pkge", "pkgx", "pkgz", "pkgy", "pkgw", "pkgv", "pkgk", "pkgm", "pkgmd500", "pkgmd250", "pkgmd250s", "pkgmint", "pkgmbook") if os.path.exists(f"{ROOT}/data/scen/runs/tk_GOOGL_pk_{p}.csv")]
def vault(log, b, E):
    em, ev = E["ms"].to_numpy(), E["E"].to_numpy()
    d = (pl.read_csv(log).join(b, on="h", how="left").sort("ms", maintain_order=True).join_asof(E, on="ms", strategy="backward")
         .with_columns(q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz"))))
    tk, uw = d.filter(pl.col("kind") == 0), d.filter(pl.col("kind") == 1)
    dm, cq = d["ms"].to_numpy(), np.cumsum(d["q"].to_numpy())
    k = np.searchsorted(dm, em, side="right") - 1; Qv = np.where(k >= 0, cq[np.clip(k, 0, None)], 0.0)
    X = Qv[:-1] * ev[:-1]; r = np.diff(np.log(ev)); m = X != 0
    below = uw.filter(((pl.col("q") < 0) & (pl.col("px") < pl.col("E"))) | ((pl.col("q") > 0) & (pl.col("px") > pl.col("E"))))
    return dict(cushion_vs_E=tk.select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item(),
                exposure=float(np.sum(np.abs(X) * np.diff(em) / 60000) / 1e6),
                drift_var=float(np.sum(X[m] ** 2) * np.var(r[m])) if m.any() else 0.0,
                execution_vs_E=uw.select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item(),
                sold_below_E=below.select((pl.col("sz") * pl.col("px")).sum()).item())
rows = []
for c, prep in PREP.items():
    b = pl.read_ipc(f"{ROOT}/data/{prep}/blocks.arrow").select("h", "ms")
    E = pl.read_csv(f"{Q}/orc_{c}.csv").select("ms", (pl.col("ext") / 1e6).alias("E")).filter(pl.col("E") > 0).sort("ms")
    for pk in PKS:
        tk = (pl.read_csv(f"{RUNS}/tk_{c}_pk_{pk}.csv").join(b, on="h").sort("ms").join_asof(E, on="ms", strategy="backward")
              .with_columns(ntl=pl.col("q").abs() * pl.col("px"), val=pl.col("q") * (pl.col("E") - pl.col("px"))))
        rd = pl.read_csv(f"{RUNS}/rd_{c}_pk_{pk}.csv").filter(pl.col("sim_rounds") > 0)
        v = vault(f"{Q}/log_{c}_pk_{pk}.csv", b, E)
        rows.append(dict(coin=c, pkg=pk, inherited_musd=tk["ntl"].sum() / 1e6, value_vs_E=tk["val"].sum(), underwater=tk.filter(pl.col("val") < 0).height,
                         book_liq_accounts=rd.height, book_liq_shares=rd["sim_filled"].sum(), **v))
r = pl.DataFrame(rows)
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(240); pl.Config.set_tbl_cols(20)
tot = (r.group_by("pkg").agg(pl.col("inherited_musd", "value_vs_E", "underwater", "book_liq_accounts", "cushion_vs_E", "exposure", "execution_vs_E", "sold_below_E").sum(),
                             pl.col("drift_var").sum().sqrt().alias("drift_sd"))
       .with_columns(pl.col("pkg").replace_strict({p: i for i, p in enumerate(PKS)}).alias("o")).sort("o").drop("o"))
print(r.select("coin", "pkg", pl.col("inherited_musd").round(2), pl.col("value_vs_E").round(0), "underwater", "book_liq_accounts", pl.col("exposure").round(1),
               (pl.col("drift_var").sqrt() / 1e3).round(1).alias("drift_sd_k"), pl.col("execution_vs_E").round(0), (pl.col("sold_below_E") / 1e6).round(2).alias("below_E_musd")))
print(tot.with_columns(pl.col("inherited_musd").round(2), pl.col("exposure").round(1), (pl.col("drift_sd") / 1e3).round(1), (pl.col("sold_below_E") / 1e6).round(2), pl.col("value_vs_E", "cushion_vs_E", "execution_vs_E").round(0)))
r.write_csv(f"{Q}/package_crash.csv")
# quiet days
qr = []
for day in ("1020", "1021"):
    for c in PREP:
        for pk in PKS:
            if not os.path.exists(f"{Q}/rd_{c}_{day}_{pk}.csv"): continue   # variants never run on the quiet days
            rd = pl.read_csv(f"{Q}/rd_{c}_{day}_{pk}.csv"); rd = rd.filter(pl.col("sim_rounds") > 0) if rd.height else rd
            tk = pl.read_csv(f"{Q}/tk_{c}_{day}_{pk}.csv")
            qr.append(dict(day=day, coin=c, pkg=pk, liquidated=rd.height, rounds=int(rd["sim_rounds"].sum()) if rd.height else 0,
                           takeovers=tk.height, takeover_kusd=(tk["q"].abs() * tk["px"]).sum() / 1e3 if tk.height else 0.0))
qd = pl.DataFrame(qr)
print(qd.group_by("pkg").agg(pl.col("liquidated", "rounds", "takeovers").sum(), pl.col("takeover_kusd").sum().round(1)).with_columns(pl.col("pkg").replace_strict({p: i for i, p in enumerate(PKS)}).alias("o")).sort("o").drop("o"))
qd.write_csv(f"{Q}/package_quiet.csv")
