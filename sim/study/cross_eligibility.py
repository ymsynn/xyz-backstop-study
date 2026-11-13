"""Which isolated-only xyz markets are eligible for cross margin, by Hyperliquid's HIP-3 rules (validators enforce that a
deployer enables cross margin only on assets with "sufficient observable liquidity, a reliable external oracle source, and
resilience to price manipulation"; "assets where 50% daily moves are expected more than once a month are ineligible").

Criteria per market. Each bar is set by precedent, the weakest market already cross-enabled on xyz (validators accepted it),
so no threshold is chosen here:
  oracle       the spec references a listed, traded instrument (trade.xyz spec index; a live pre-IPO market fails)
  move_50      days whose high or low moved >= 50% from the day's open (1h candles, UTC days): rate < 1 per month (HL's rule)
  max_move     largest such daily move <= the largest among cross-enabled markets
  liquidity    median daily traded notional on xyz >= the smallest among cross-enabled markets
  history      at least one month of candles: the 50% rule is a monthly rate
Then the ADL risk and capital of sim/study/nocross_rank.py, for the eligible ones only.
Usage: python sim/study/cross_eligibility.py [DAY=1030] -> data/scen/cross_eligibility.csv  (REG=cross-eligibility to record)"""
import json, os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
SPEC = f"{ROOT}/data/xyz_spec_index.json"
# data/xyz_spec_index.json: trade.xyz's Specification Index (margin mode per market) and its pre-IPO table, saved from the
# public docs (https://docs.trade.xyz/llms-full.txt)
S = json.load(open(SPEC))
U = json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]
MODE = {u["name"]: (u.get("marginMode") or "cross") for u in U if not u.get("isDelisted")}
spec = {m["name"]: m for m in S["markets"]}
alias = {"WTIOIL": "CL", "SKHYNIX": "SKHX", "SAMSUNG": "SMSN", "HYUNDAI": "HYUNDAI"}
live_preipo = {k for k, v in S["preipo"].items() if v == "Live"}

c = pl.read_parquet(f"{ROOT}/data/candles/xyz_1h.parquet").with_columns(d=pl.col("t") // 86_400_000, ntl=pl.col("v") * pl.col("c"))
day = (c.sort("coin", "t").group_by("coin", "d").agg(o=pl.col("o").first(), h=pl.col("h").max(), l=pl.col("l").min(), ntl=pl.col("ntl").sum())
       .with_columns(mv=pl.max_horizontal(pl.col("h") / pl.col("o") - 1, 1 - pl.col("l") / pl.col("o"))))
st = day.group_by("coin").agg(days=pl.len(), d50=(pl.col("mv") >= 0.5).sum(), max_move_pct=(pl.col("mv").max() * 100), vol_day_M=pl.col("ntl").median() / 1e6)
st = st.with_columns(per_month=pl.col("d50") / (pl.col("days") / 30.44), mode=pl.col("coin").replace_strict(MODE, default=None)).filter(pl.col("mode").is_not_null())
def spec_of(coin):
    n = coin[4:]
    for k, v in alias.items():
        if v == n and k in spec: return spec[k]
    return spec.get(n)
st = st.with_columns(reference=pl.col("coin").map_elements(lambda x: (spec_of(x) or {}).get("reference", ""), return_dtype=pl.String),
                     oracle_ok=pl.col("coin").map_elements(lambda x: spec_of(x) is not None and x[4:] not in live_preipo, return_dtype=pl.Boolean))
cr = st.filter(pl.col("mode") == "cross")
bar_move, bar_vol = float(cr["max_move_pct"].max()), float(cr["vol_day_M"].min())
print(f"precedent from {cr.height} cross-enabled markets: max daily move {bar_move:.1f}% ({cr.sort('max_move_pct')['coin'][-1]}), "
      f"min median daily volume ${bar_vol:.2f}M ({cr.sort('vol_day_M')['coin'][0]}); 50%-move days on cross markets: {int(cr['d50'].sum())}")
E = (st.filter(pl.col("mode") != "cross")
     .with_columns(rule50=pl.col("per_month") < 1, move_ok=pl.col("max_move_pct") <= bar_move, liq_ok=pl.col("vol_day_M") >= bar_vol, hist_ok=pl.col("days") >= 30.44)
     .with_columns(eligible=pl.col("oracle_ok") & pl.col("rule50") & pl.col("move_ok") & pl.col("liq_ok") & pl.col("hist_ok")))
E = E.with_columns(fails=pl.concat_str([pl.when(~pl.col(k)).then(pl.lit(n)).otherwise(pl.lit("")) for k, n in
                    (("oracle_ok", "oracle "), ("rule50", "50%-rule "), ("move_ok", "max-move "), ("liq_ok", "liquidity "), ("hist_ok", "history "))]).str.strip_chars())
rk = f"{ROOT}/data/scen/nocross_rank.csv"
if os.path.exists(rk):
    E = E.join(pl.read_csv(rk).select(coin="market", oi_M="oi_M", adl_now_k="adl_now_k", capital_x_k="capital_x_k", adl_past_k="adl_past_k"), on="coin", how="left")
E = E.sort(["eligible", "adl_now_k", "coin"], descending=[True, True, False], nulls_last=True).with_columns(pl.col(pl.Float64).round(2))
E.write_csv(f"{ROOT}/data/scen/cross_eligibility.csv")
pl.Config.set_tbl_rows(120); pl.Config.set_tbl_width_chars(240); pl.Config.set_tbl_cols(14)
cols = ["coin", "days", "d50", "max_move_pct", "vol_day_M", "oi_M", "adl_now_k", "capital_x_k", "adl_past_k", "fails"]
el = E.filter("eligible"); ne = E.filter(~pl.col("eligible"))
print(f"eligible: {el.height} of {E.height} isolated-only markets"); print(el.select(cols))
print("not eligible (reason):"); print(ne.select(cols).head(60))
tot = lambda d: d.select(n=pl.len(), oi_M=pl.col("oi_M").sum(), adl_now_M=pl.col("adl_now_k").sum() / 1e3, capital_x_M=pl.col("capital_x_k").sum() / 1e3, adl_past_M=pl.col("adl_past_k").sum() / 1e3).to_dicts()[0]
print("eligible totals:", tot(el)); print("not eligible totals:", tot(ne))
print("failure counts:", ne.select([pl.col(k).not_().sum().alias(k) for k in ("oracle_ok", "rule50", "move_ok", "liq_ok", "hist_ok")]).to_dicts()[0])
if os.environ.get("REG"):
    recs = [dict(design="current", case=r["coin"], eligible=r["eligible"], fails=r["fails"], **{k: r[k] for k in ("days", "d50", "max_move_pct", "vol_day_M", "oi_M", "adl_now_k", "capital_x_k", "adl_past_k")}) for r in E.to_dicts()]
    recs.append(dict(design="current", case="precedent bars", max_move_pct=bar_move, vol_day_M=bar_vol))
    registry.maybe_record(recs, kind="cross_eligibility", command="python sim/study/cross_eligibility.py")
