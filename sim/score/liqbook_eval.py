"""Liquidation-size study (sim/runs/liqbook_runs.sh): what each liquidation rule does to xyz's book for big positions.
Big position = an account whose first liquidation round starts above $100k of notional. Per round of a big position:
  sold notional, sold / depth within 1% of the best price on the hit side, levels walked,
  impact = move of the hit-side best price across the round (bp, positive = against the liquidated side),
  slippage = average fill vs the hit-side best before (bp), fill vs the external price E (bp),
  recovery = time until the hit-side best (relayer-update snapshots, ~3 s) recovers half the impact (censored at 10 min),
  cascade = other accounts' liquidation rounds on the same side within 60 s.
Per big position: notional sold on the book, taken by the vault (and its value vs E), still open at the end.
Usage: python sim/score/liqbook_eval.py  (REG=liq-book to record)  -> data/scen/liqbook_{rounds,positions,summary}.csv"""
import glob, os, sys
import numpy as np
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
S = os.environ.get("LIQBOOK_DIR", f"{ROOT}/data/scen/liqbook")   # LIQBOOK_DIR: another run folder (the final rerun)
DES = {"today": "today", "rim": "today mark + restore-to-IM", "lead20": "lead mark + today's sizing", "lead": "lead (package_m_int)",
       "lead3q1800s20": "three-vote mark + today's sizing", "lead3q1800": "three-vote mark + restore-to-IM (the proposal)"}
CRASH = {"GOOGL_1028", "INTC_1029", "AMZN_1029"}
OOS = {"CL_0910", "BRENTOIL_0910", "SILVER_1022", "GOLD_1030"}   # oil and metals, out of sample (EC2)
group = lambda ev: "crashes" if ev in CRASH else ("oil and metals" if ev in OOS else "quiet days")
BIG, CAS_MS, REC_MS = 100_000.0, 60_000, 600_000
rr, pp = [], []
for f in sorted(glob.glob(f"{S}/liq_*.csv")):
    c, day, des = os.path.basename(f)[4:-4].split("_", 2)
    ev = f"{c}_{day}"
    L = pl.read_csv(f)
    if L.height == 0: continue
    orc = (pl.read_csv(f"{S}/orc_{ev}_{des}.csv").select("ms", (pl.col("ext") / 1e6).alias("E"), (pl.col("bid") / 1e6).alias("b"), (pl.col("ask") / 1e6).alias("a"))
           .drop_nulls().sort("ms"))
    om, ob, oa = orc["ms"].to_numpy(), orc["b"].to_numpy(), orc["a"].to_numpy()
    L = L.sort("ms").join_asof(orc.select("ms", "E"), on="ms")
    first = L.group_by("u").agg(pl.col("ntl").first().alias("ntl0"), pl.col("sell").first().alias("side"))
    big = set(first.filter(pl.col("ntl0") > BIG)["u"])
    allr = L.to_dicts()
    for r in allr:
        if r["u"] not in big: continue
        sell = r["sell"] == 1
        pre = r["bid0"] if sell else r["ask0"]; post = r["bid1"] if sell else r["ask1"]
        sold = r["filled"] * (r["avg_px"] if r["filled"] > 0 else 0)
        imp = None if pre is None or post is None or pre != pre or post != post else (pre - post) / pre * 1e4 * (1 if sell else -1)
        slip = None if r["filled"] <= 0 or pre is None or pre != pre else (pre - r["avg_px"]) / pre * 1e4 * (1 if sell else -1)
        vsE = None if r["filled"] <= 0 or r["E"] is None else (r["E"] - r["avg_px"]) / r["E"] * 1e4 * (1 if sell else -1)
        rec = None
        if imp is not None and imp > 0:
            target = pre - (pre - post) * 0.5 if sell else pre + (post - pre) * 0.5
            i0 = np.searchsorted(om, r["ms"], side="right")
            for k in range(i0, len(om)):
                if om[k] - r["ms"] > REC_MS: break
                if (sell and ob[k] >= target) or ((not sell) and oa[k] <= target):
                    rec = (om[k] - r["ms"]) / 1000; break
            if rec is None: rec = REC_MS / 1000 + 1   # censored
        cas = sum(1 for x in allr if x["u"] != r["u"] and x["sell"] == r["sell"] and r["ms"] < x["ms"] <= r["ms"] + CAS_MS)
        rr.append(dict(event=ev, group=group(ev), design=des, u=r["u"], ms=r["ms"], sold=sold, ntl=r["ntl"], req=r["req"], filled=r["filled"],
                       depth1=r["depth1pct"], share_of_depth=sold / r["depth1pct"] if r["depth1pct"] > 0 else None, levels=r["levels"],
                       impact_bp=imp, slip_bp=slip, fill_vs_E_bp=vsE, half_recovery_s=rec, cascade_60s=cas, full=r["full"]))
    tk = pl.read_csv(f"{S}/tk_{ev}_{des}.csv")
    tkb = tk.with_columns(pl.col("u").cast(pl.Int64)).filter(pl.col("u").is_in(list(big))) if tk.height else tk
    if tkb.height:
        # a position handed over at a negative bankruptcy price is counted at the mark (as sim/final/score_final.py)
        tkb = tkb.sort("h").with_columns(ntl=pl.col("q").abs() * pl.when(pl.col("px") > 0).then(pl.col("px")).otherwise(pl.col("mark")))
    for u in big:
        rows = [x for x in rr if x["event"] == ev and x["design"] == des and x["u"] == u]
        t = tkb.filter(pl.col("u") == u) if tkb.height else tkb
        pp.append(dict(event=ev, group=group(ev), design=des, u=u, ntl0=float(first.filter(pl.col("u") == u)["ntl0"][0]),
                       rounds=len(rows), sold_book=sum(x["sold"] for x in rows), taken_vault=float(t["ntl"].sum()) if t.height else 0.0))
R = pl.DataFrame(rr, infer_schema_length=None); P = pl.DataFrame(pp, infer_schema_length=None)
OUTP = f"{S}/liqbook" if os.environ.get("LIQBOOK_DIR") else f"{ROOT}/data/scen/liqbook"   # LIQBOOK_DIR: results stay in that folder
R.write_csv(f"{OUTP}_rounds.csv"); P.write_csv(f"{OUTP}_positions.csv")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(240); pl.Config.set_tbl_cols(20)
def summ(df_r, df_p):
    a = df_r.group_by("design").agg(rounds=pl.len(), sold_musd=(pl.col("sold").sum() / 1e6).round(2), sold_med_k=(pl.col("sold").median() / 1e3).round(0),
            share_depth_med=pl.col("share_of_depth").median().round(2), share_depth_p90=pl.col("share_of_depth").quantile(0.9).round(2),
            levels_med=pl.col("levels").median(), impact_med_bp=pl.col("impact_bp").median().round(1), impact_p90_bp=pl.col("impact_bp").quantile(0.9).round(1),
            slip_med_bp=pl.col("slip_bp").median().round(1), fill_vs_E_bp=(pl.col("fill_vs_E_bp") * pl.col("sold")).sum() / pl.col("sold").sum(),
            half_rec_med_s=pl.col("half_recovery_s").median(), cascade_60s=pl.col("cascade_60s").sum())
    b = df_p.group_by("design").agg(positions=pl.len(), ntl0_musd=(pl.col("ntl0").sum() / 1e6).round(2), book_musd=(pl.col("sold_book").sum() / 1e6).round(2),
            vault_musd=(pl.col("taken_vault").sum() / 1e6).round(2), reached_vault=(pl.col("taken_vault") > 0).sum())
    return a.join(b, on="design", how="full", coalesce=True).with_columns(pl.col("fill_vs_E_bp").round(1)).sort("design")
out = []
for lab in ("crashes", "quiet days", "oil and metals"):
    if R.filter(pl.col("group") == lab).height == 0: continue
    x = summ(R.filter(pl.col("group") == lab), P.filter(pl.col("group") == lab)).with_columns(events=pl.lit(lab))
    print(f"== {lab}: big positions (first round > $100k)"); print(x); out.append(x)
pl.concat(out, how="diagonal_relaxed").write_csv(f"{OUTP}_summary.csv")
if os.environ.get("REG"):
    registry.maybe_record([dict(r, design={"today": "current", "rim": "current+restore_im", "lead20": "package_m_int_today_sizing", "lead": "package_m_int"}.get(r["design"], r["design"]), case=r["events"]) for r in pl.concat(out, how="diagonal_relaxed").to_dicts()],
                          kind="liq_book", command="zsh sim/runs/liqbook_runs.sh; python sim/score/liqbook_eval.py")
