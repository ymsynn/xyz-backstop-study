"""What it costs to clear one side of xyz's book: resting notional within 5% and 10% of the mid, by market and session.
Reads data/scen/depth/depth_{COIN}_{DAY}.csv (sim/final/depth_runs.sh: the real book rebuilt from the tape, sampled every minute).
An attacker who wants xyz's book price 10% away must take every resting order within 10% on that side; with a margined account
the capital that takes is that notional / max leverage. Replenishment by market makers is ignored (a lower bound on the cost).
Sessions (UTC): US-listed names: overnight 00:00-08:00, pre-market 08:00-13:30, regular 13:30-20:00, post-market 20:00-24:00;
other markets: venue open / venue closed from the prep's internal-session windows. Writes data/scen/depth_by_session.csv."""
import glob, os, json, polars as pl
ML = {u["name"][4:]: u["maxLeverage"] for u in json.load(open("data/xyzmeta.json"))[0]["universe"]}
NONUS = {"CL", "BRENTOIL", "GOLD", "SILVER", "SKHX"}
rows = []
for f in sorted(glob.glob("data/scen/depth/depth_*.csv")):
    c, day = os.path.basename(f)[6:-4].rsplit("_", 1)
    d = pl.read_csv(f).filter(pl.col("dbps").is_in([500.0, 1000.0]))
    d = d.pivot(on=["side", "dbps"], index=["h", "ms", "mid"], values="ntl")
    d = d.rename({k: k.replace('{"', "").replace('",', "_").replace("}", "").replace(".0", "") for k in d.columns})
    t0 = int(d["ms"].min()) // 86400000 * 86400000
    hr = ((pl.col("ms") - t0) / 3.6e6)
    if c in NONUS:
        w = open(f"data/prep_{c}_{day}/internal_windows.txt").read().strip() if os.path.exists(f"data/prep_{c}_{day}/internal_windows.txt") else ""
        win = [tuple(int(x) for x in s.split(";")) for s in w.split(",") if s]
        closed = pl.any_horizontal([(pl.col("ms") >= a) & (pl.col("ms") < b) for a, b in win]) if win else pl.lit(False)
        d = d.with_columns(session=pl.when(closed).then(pl.lit("venue closed")).otherwise(pl.lit("venue open")))
    else:
        d = d.with_columns(session=pl.when(hr < 8).then(pl.lit("overnight")).when(hr < 13.5).then(pl.lit("pre-market")).when(hr < 20).then(pl.lit("regular")).otherwise(pl.lit("post-market")))
    for (s,), g in d.group_by("session"):
        L = ML[c]
        rows.append(dict(coin=c, day=day, max_lev=L, session=s, minutes=g.height,
                         bid5_med=g["bid_500"].median(), bid10_med=g["bid_1000"].median(), bid10_p10=g["bid_1000"].quantile(0.1), bid10_min=g["bid_1000"].min(),
                         ask10_med=g["ask_1000"].median(), ask10_p10=g["ask_1000"].quantile(0.1),
                         capital_bid10_med=g["bid_1000"].median() / L, capital_bid10_p10=g["bid_1000"].quantile(0.1) / L, capital_ask10_p10=g["ask_1000"].quantile(0.1) / L))
R = pl.DataFrame(rows).sort("coin", "day", "session"); R.write_csv("data/scen/depth_by_session.csv")
ORD = {"overnight": 0, "pre-market": 1, "regular": 2, "post-market": 3, "venue open": 4, "venue closed": 5}
A = (R.group_by("coin", "max_lev", "session").agg(pl.col("day").n_unique().alias("days"), pl.col("minutes").sum(), pl.col("bid10_med").median(), pl.col("bid10_p10").min(), pl.col("ask10_p10").min(),
                                                 pl.col("capital_bid10_med").median(), pl.col("capital_bid10_p10").min(), pl.col("capital_ask10_p10").min())
     .with_columns(o=pl.col("session").replace_strict(ORD)).sort("coin", "o").drop("o"))
pl.Config.set_tbl_rows(100); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(20); pl.Config.set_float_precision(2)
print(A.with_columns([(pl.col(k) / 1e6).round(2) for k in ("bid10_med", "bid10_p10", "ask10_p10", "capital_bid10_med", "capital_bid10_p10", "capital_ask10_p10")]))
