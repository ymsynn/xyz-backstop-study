"""Which isolated-only (noCross) markets to move to cross margin first.
Per noCross market, on today's positions (snapshot DAY) and the gap model of sim/study/joint_capital.py:
  oi            open interest, both sides (snapshot)
  adl_past      ADL on the tape, all days (sim/score/tape_eval.py -> data/scen/tape_adl_markets.csv)
  worst_hour    the market's own worst real hour in the adverse direction for its net position side (1h candles)
  adl_now       ADL that move would cause today (positions taken over at 2/3 MM, all ADL on a noCross market)
  capital_x     the vault's capital need for the same move if the market had cross margin (MM of inherited - equity)
  vol_day       median daily traded notional (1h candles), a liquidity proxy for Hyperliquid's cross eligibility review
Ranked by ADL avoided per dollar of capital added, among markets with ADL now or in the past.
Usage: python sim/study/nocross_rank.py [DAY=1030] -> data/scen/nocross_rank.csv  (REG=nocross-rank to record)"""
import os, sys
import numpy as np
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry
from joint_capital import Book, positions, ROOT, NOX, ML

DAY = sys.argv[1] if len(sys.argv) > 1 else "1030"
s, _ = positions(DAY); B = Book(s); mk = B.mk
c = pl.read_parquet(f"{ROOT}/data/candles/xyz_1h.parquet").filter(pl.col("coin").is_in(mk)).sort("coin", "t")
r = c.with_columns(ret=pl.col("c") / pl.col("c").shift(1).over("coin") - 1, ntl=pl.col("v") * pl.col("c"),
                   d=pl.col("t") // 86_400_000)
worst = r.group_by("coin").agg(dn=pl.col("ret").min(), up=pl.col("ret").max())
vol = r.group_by("coin", "d").agg(pl.col("ntl").sum()).group_by("coin").agg(vol_day=pl.col("ntl").median())
oi = s.group_by("market").agg(oi=pl.col("notional").sum(), net=(pl.col("size").sign() * pl.col("notional")).sum(), accounts=pl.col("user").n_unique())
past = pl.read_csv(f"{ROOT}/data/scen/tape_adl_markets.csv").select(market="coin", adl_past_k="adl_k", adl_days="days") if os.path.exists(f"{ROOT}/data/scen/tape_adl_markets.csv") else None
W = dict(zip(worst["coin"], zip(worst["dn"], worst["up"])))
rows = []
for m in mk:
    if m not in NOX: continue
    j = mk.index(m); o = oi.filter(pl.col("market") == m)
    net = float(o["net"][0]) if o.height else 0.0
    dn, up = W.get(m, (0.0, 0.0)); mv = (dn if net >= 0 else up) or 0.0
    ret = np.zeros(len(mk)); ret[j] = mv
    g = B.gap(ret)
    rows.append(dict(market=m, maxLev=ML[m], oi_M=float(o["oi"][0]) / 1e6 if o.height else 0.0, accounts=int(o["accounts"][0]) if o.height else 0,
                     worst_hour_pct=round(mv * 100, 1), adl_now_k=g["adl_ntl"] / 1e3, adl_short_k=g["adl_short"] / 1e3, capital_x_k=g["C_MM_x"] / 1e3))
R = pl.DataFrame(rows).join(vol.rename({"coin": "market"}), on="market", how="left")
# without the record of past ADL the columns must still exist: the line below reads adl_past_k
if past is not None: R = R.join(past, on="market", how="left").with_columns(pl.col("adl_past_k").fill_null(0), pl.col("adl_days").fill_null(0))
else: R = R.with_columns(adl_past_k=pl.lit(0.0), adl_days=pl.lit(0))
R = R.with_columns(vol_day_M=pl.col("vol_day") / 1e6, adl_per_capital=(pl.col("adl_now_k") + pl.col("adl_past_k")) / pl.col("capital_x_k").clip(lower_bound=1.0)).drop("vol_day")
R = R.sort(["adl_now_k"], descending=True).with_columns(pl.col(pl.Float64).round(2))
R.write_csv(f"{ROOT}/data/scen/nocross_rank.csv")
pl.Config.set_tbl_rows(30); pl.Config.set_tbl_width_chars(230); pl.Config.set_tbl_cols(14)
tot = R.select(n=pl.len(), oi_M=pl.col("oi_M").sum(), adl_now_M=pl.col("adl_now_k").sum() / 1e3, capital_x_M=pl.col("capital_x_k").sum() / 1e3, adl_past_M=pl.col("adl_past_k").sum() / 1e3)
print("noCross markets, each at its own worst real hour on today's positions:"); print(tot)
top = R.filter((pl.col("adl_now_k") > 0) | (pl.col("adl_past_k") > 0)).sort("adl_now_k", descending=True).head(20)
print(top)
cum = R.sort("adl_now_k", descending=True).with_columns(cum_adl=pl.col("adl_now_k").cum_sum() / pl.col("adl_now_k").sum(), rank=pl.int_range(1, pl.len() + 1))
for k in (5, 10, 20): print(f"top {k} markets: {cum['cum_adl'][k-1]:.0%} of single-market ADL now, capital added ${cum.head(k)['capital_x_k'].sum()/1e3:.2f}M, OI ${cum.head(k)['oi_M'].sum():.0f}M")
if os.environ.get("REG"):
    recs = [dict(design="current", case=r_["market"], **{k: r_[k] for k in ("oi_M", "worst_hour_pct", "adl_now_k", "capital_x_k", "adl_past_k", "vol_day_M")}) for r_ in top.to_dicts()]
    registry.maybe_record(recs, kind="nocross_rank", command=f"python sim/study/nocross_rank.py {DAY}")
