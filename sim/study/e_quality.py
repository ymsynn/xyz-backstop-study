"""Quality of trade.xyz's external price E, from the tape, by session: where is E weakest, and so cheapest to walk?
For every xyz market on each of the five days in DAYS, from the relayer table (data/extract<DAY>/tables/oracle.parquet)
and xyz's fills (data/xyzdata/all<DAY>.parquet); the script stops if one of them is missing:
  per update: E stale (unchanged), |dE| (bp), jumps > 1%;
  per minute: xyz voluntary taker VWAP and notional; gap = xyz VWAP / E - 1 at that minute (bp);
  episodes: |gap| > 1% for 3+ consecutive traded minutes (E and xyz's own market disagree).
Sessions by UTC clock (US-listed names, EDT dates): overnight 00:05-08:00 (Blue Ocean ATS), pre 08:00-13:30,
regular 13:30-20:00, post 20:00-24:00. Rows where the published oracle differs from E for most of a session are
internal (trade.xyz's own oracle) and are reported apart.
Usage: python sim/study/e_quality.py  -> data/scen/e_quality_{coin_session,episodes}.csv"""
import os, sys
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
US = set("AAOI AAPL ACN AMAT AMD AMZN ARM AVGO BABA BB BE BIRD BMNR BX COIN COST CRCL CRWD CRWV CVX DELL DKNG EBAY GEV GLW GME "
         "GOOGL HIMS HOOD IBM INTC IREN LITE LLY LRCX META MRNA MRVL MSFT MSTR MU NBIS NET NFLX NOK NOW NU NVDA ORCL PLTR QCOM "
         "RDDT RIVN RKLB SNAP SNDK TSLA TSM TTWO TWST USAR WDC ZM EWJ EWT EWY EWZ MAGS SMH SOXL TLT URNM XBI XLE SP500 XYZ100".split())
def session(col):
    m = pl.col(col).dt.hour().cast(pl.Int32) * 60 + pl.col(col).dt.minute().cast(pl.Int32)
    return (pl.when(m < 5).then(pl.lit("gap")).when(m < 480).then(pl.lit("overnight")).when(m < 810).then(pl.lit("pre"))
            .when(m < 1200).then(pl.lit("regular")).otherwise(pl.lit("post")))

DAYS = ("0727", "1020", "1021", "1028", "1029")
need = [p for d in DAYS for p in (f"{ROOT}/data/extract{d}/tables/oracle.parquet", f"{ROOT}/data/xyzdata/all{d}.parquet") if not os.path.exists(p)]
if need:
    sys.exit("e_quality: missing inputs (fetch them before running; see REPRODUCE.md):\n  " + "\n  ".join(need))
rows, eps = [], []
for day in DAYS:
    f, fills = f"{ROOT}/data/extract{day}/tables/oracle.parquet", f"{ROOT}/data/xyzdata/all{day}.parquet"
    o = (pl.scan_parquet(f).filter(pl.col("ext").is_not_null()).select("coin", "t", "h", "oracle", "ext").collect()
         .sort("coin", "h").unique(["coin", "h"], keep="first", maintain_order=True)
         .with_columns(dE=(pl.col("ext") / pl.col("ext").shift(1).over("coin") - 1).abs() * 1e4,
                       stale=(pl.col("ext") == pl.col("ext").shift(1).over("coin")),
                       internal=(pl.col("oracle") - pl.col("ext")).abs() > pl.col("ext") * 1e-5, session=session("t")))
    upd = o.group_by("coin", "session").agg(updates=pl.len(), stale_pct=(pl.col("stale").mean() * 100).round(1),
                                            dE_p99_bp=pl.col("dE").quantile(0.99).round(1), dE_max_bp=pl.col("dE").max().round(0),
                                            jumps_1pct=(pl.col("dE") > 100).sum(), internal_pct=(pl.col("internal").mean() * 100).round(0))
    em = o.group_by("coin", pl.col("t").dt.truncate("1m").alias("m")).agg(E=pl.col("ext").last())
    x = (pl.scan_parquet(fills).filter(pl.col("crossed"), ~pl.col("is_liquidation").fill_null(False))
         .select("coin", m=pl.col("timestamp").dt.replace_time_zone(None).dt.cast_time_unit("ns").dt.truncate("1m"),
                 ntl=pl.col("price").cast(pl.Float64) * pl.col("size").cast(pl.Float64), sz=pl.col("size").cast(pl.Float64))
         .group_by("coin", "m").agg(pl.col("ntl").sum(), pl.col("sz").sum()).collect()
         .with_columns(vwap=pl.col("ntl") / pl.col("sz")))
    j = x.join(em, on=["coin", "m"], how="inner").with_columns(gap=(pl.col("vwap") / pl.col("E") - 1) * 1e4, session=session("m"))
    gm = j.group_by("coin", "session").agg(traded_min=pl.len(), ntl_per_min=pl.col("ntl").median().round(0),
                                          gap_med_bp=pl.col("gap").abs().median().round(1), gap_p95_bp=pl.col("gap").abs().quantile(0.95).round(1))
    rows.append(upd.join(gm, on=["coin", "session"], how="left").with_columns(day=pl.lit(day)))
    # episodes: |gap| > 100 bp on 3+ consecutive traded minutes
    j = j.sort("coin", "m").with_columns(big=pl.col("gap").abs() > 100)
    j = j.with_columns(run=(pl.col("big") != pl.col("big").shift(1).over("coin")).fill_null(True).cum_sum().over("coin"))
    ep = (j.filter("big").group_by("coin", "run").agg(start=pl.col("m").first(), minutes=pl.len(), gap_max_bp=pl.col("gap").abs().max().round(0),
                                                       side=pl.col("gap").mean().sign(), session=pl.col("session").first(), ntl=pl.col("ntl").sum().round(0))
          .filter(pl.col("minutes") >= 3).with_columns(day=pl.lit(day)))
    eps.append(ep)
R = pl.concat(rows, how="diagonal_relaxed").with_columns(coin=pl.col("coin").str.replace("xyz:", ""))
R = R.with_columns(us=pl.col("coin").is_in(list(US)))
E_ = pl.concat(eps, how="diagonal_relaxed").with_columns(coin=pl.col("coin").str.replace("xyz:", "")).drop("run")
R.write_csv(f"{ROOT}/data/scen/e_quality_coin_session.csv"); E_.write_csv(f"{ROOT}/data/scen/e_quality_episodes.csv")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(16)
ext = R.filter(pl.col("internal_pct") < 50)
print("US-listed names, external sessions: medians over coin-days")
print(ext.filter("us").group_by("session").agg(coin_days=pl.len(), stale_pct=pl.col("stale_pct").median(), dE_p99_bp=pl.col("dE_p99_bp").median(),
      jumps_1pct=pl.col("jumps_1pct").sum(), traded_min=pl.col("traded_min").median(), ntl_per_min=pl.col("ntl_per_min").median(),
      gap_med_bp=pl.col("gap_med_bp").median(), gap_p95_bp=pl.col("gap_p95_bp").median()).sort("session"))
print("episodes (|xyz VWAP - E| > 1% for 3+ traded minutes), US-listed, by session:")
eu = E_.filter(pl.col("coin").is_in(list(US)))
print(eu.group_by("session").agg(episodes=pl.len(), coins=pl.col("coin").n_unique(), minutes=pl.col("minutes").sum(), gap_max_bp=pl.col("gap_max_bp").max()).sort("session"))
print(eu.sort("minutes", descending=True).head(15))
