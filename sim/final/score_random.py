"""The random sample of market-days (sim/final/random_sample.py), replayed under today's rules and the proposal
(ec2/days_job.sh with RUN_TAG=random, DAYS_DES="today lead3q1800"): one row per market-day and the totals.
Per market-day: real takeovers on the chain against the replay of today's rules (is the replay faithful there?), then today
against the proposal: accounts liquidated, notional taken over by the backstop (vault, or ADL on isolated-only markets), and how
far the proposal's mark sits from today's over the day. Usage: python sim/final/score_random.py [DIR=data/scen/joint_random]"""
import sys, os, re, csv, json, numpy as np, polars as pl
J = sys.argv[1] if len(sys.argv) > 1 else "data/scen/joint_random"
U = json.load(open("data/xyzmeta.json"))[0]["universe"]; NOX = {u["name"][4:] for u in U if u.get("marginMode") in ("noCross", "strictIsolated")}
S = [r for r in csv.DictReader(open("sim/final/random_sample.csv"))]
def marks(n):
    o = pl.read_csv(f"{J}/orc_{n}.csv").sort("h")
    bid, ask, last = (o[c].to_numpy().astype(float) for c in ("bid", "ask", "last"))
    full = ~(np.isnan(bid) | np.isnan(ask) | np.isnan(last)); bk = np.where(full, np.nanmedian(np.stack([bid, ask, last]), axis=0), np.where(np.isnan(bid), ask, bid))
    m1, m2 = o["m1"].to_numpy().astype(float), o["m2"].to_numpy().astype(float)
    raw = np.median(np.stack([m1, m2, np.where(np.isnan(bk), m1, bk)]), axis=0); m = raw.copy()
    for i in range(1, len(m)): m[i] = min(max(raw[i], m[i - 1] * 0.99), m[i - 1] * 1.01)
    return o.select("h").with_columns(mk=pl.Series(m))
def tk(n):
    f = f"{J}/tk_{n}.csv"
    if not (os.path.exists(f) and os.path.getsize(f) > 0): return 0, 0.0
    t = pl.read_csv(f, schema_overrides={"q": pl.Float64, "px": pl.Float64}); return t.height, float((t["q"].abs() * t["px"]).sum())
def liq(n):
    f = f"{J}/rd_{n}.csv"
    if not os.path.exists(f): return 0
    r = pl.read_csv(f, schema_overrides={"sim_rounds": pl.Float64}); return r.filter(pl.col("sim_rounds") > 0).height
rows = []
for r in S:
    c, day = r["coin"], r["date"][5:7] + r["date"][8:]; a, b = f"{c}_{day}_today", f"{c}_{day}_lead3q1800"
    row = dict(order=int(r["order"]), role=r["role"], date=r["date"], coin=c, isolated_only=c in NOX)
    if not os.path.exists(f"{J}/orc_{a}.csv"): row["status"] = "not built"; rows.append(row); continue
    lg = open(f"{J}/joint_{c}_{day}.log").read() if os.path.exists(f"{J}/joint_{c}_{day}.log") else ""
    m = re.search(rf"{a}:\s+takeover notional: sim \$(-?[\d.]+)M\s+real \$(-?[\d.]+)M", lg)
    n0, v0 = tk(a); n1, v1 = tk(b)
    j = marks(a).join(marks(b), on="h", suffix="_p"); d = ((j["mk_p"] / j["mk"] - 1).abs() * 1e4)
    row.update(status="ok", real_takeover_k=float(m[2]) * 1e3 if m else None, today_takeovers=n0, today_takeover_k=round(v0 / 1e3, 1), proposal_takeovers=n1, proposal_takeover_k=round(v1 / 1e3, 1),
               today_liquidated=liq(a), proposal_liquidated=liq(b), mark_gap_med_bp=round(float(d.median()), 2), mark_gap_p99_bp=round(float(d.quantile(0.99)), 1), mark_gap_max_bp=round(float(d.max()), 1))
    rows.append(row)
R = pl.DataFrame(rows, infer_schema_length=None); R.write_csv(f"{J}/random_sample_scored.csv")
pl.Config.set_tbl_rows(60); pl.Config.set_tbl_width_chars(240); pl.Config.set_tbl_cols(20); print(R)
ok = R.filter(pl.col("status") == "ok")
if ok.height:
    print(f"market-days built {ok.height} of {R.filter(pl.col('role') == 'sample').height} sampled (+ reserve used: {ok.filter(pl.col('role') == 'reserve').height})")
    print(f"real takeovers ${ok['real_takeover_k'].sum():.1f}k | today's rules replayed ${ok['today_takeover_k'].sum():.1f}k ({ok['today_takeovers'].sum()}) | proposal ${ok['proposal_takeover_k'].sum():.1f}k ({ok['proposal_takeovers'].sum()})")
    print(f"accounts liquidated: today {ok['today_liquidated'].sum()} | proposal {ok['proposal_liquidated'].sum()}")
    print(f"market-days where the proposal takes over more / the same / less notional than today: {ok.filter(pl.col('proposal_takeover_k') > pl.col('today_takeover_k')).height} / {ok.filter(pl.col('proposal_takeover_k') == pl.col('today_takeover_k')).height} / {ok.filter(pl.col('proposal_takeover_k') < pl.col('today_takeover_k')).height}")
    print(f"proposal's mark vs today's, median over the day: median of market-days {ok['mark_gap_med_bp'].median():.2f} bp, largest {ok['mark_gap_med_bp'].max():.2f} bp; 99th percentile within a day: median {ok['mark_gap_p99_bp'].median():.1f} bp, largest {ok['mark_gap_p99_bp'].max():.1f} bp")
