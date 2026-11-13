"""Walking external feed (sim/runs/ramp_runs.sh): each walked run against the same mark without the walk. Window: from the
start of the walk to 120 s after E snaps back. Per run: the mark's largest move vs the baseline (bp, negative = down),
backstop notional taken over, book-liquidated shares and stop orders the walk added, and the change in value at takeover
against the external price as it really was (not the walked one).
Records registry test `walking-feed` (REG=walking-feed). Usage: python sim/score/ramp_eval.py [DIR]"""
import glob, os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
D = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/scen/ramp"
PREP = {"GOOGL": ("prep_GOOGL_1028", "extract1028", 1793226600000), "AMZN": ("prep_AMZN_1029", "extract1029", 1793313000000)}
# RAMP_AT_GOOGL / RAMP_AT_AMZN: the walk start of a run made with RAMP_AT (e.g. the overnight session)
PREP = {c: (a, b, int(os.environ.get(f"RAMP_AT_{c}", q))) for c, (a, b, q) in PREP.items()}
HOLD = int(os.environ.get("HOLD_S", 120)) * 1000
DM = {"pkgm3q1800": "three_vote_30min_ratchet_book", "today": "current", "pkgm": "package_m", "pkgmint": "package_m_int", "pkgmintc": "lead_corroborated", "pkgm3a50": "three_vote_50bp", "pkgm3e1800": "three_vote_30min", "pkgm3n1800": "three_vote_30min_nostale", "pkgm3k1800": "three_vote_30min_onerule", "pkgm3r1800": "three_vote_30min_ratchet", "pkgm3r900": "three_vote_15min_ratchet", "pkgm3r3600": "three_vote_60min_ratchet", "pkgm3a0": "three_vote_frozen", **{f"pkgmintp250w{w}": f"lead_persist_250bp_{w}s" for w in (30, 60, 150, 300)}, "pkgmd500": "package_m_div500", "pkgmd250": "package_m_div250", "pkgmd250n": "div250_never_step", "pkgmd250s": "div250_step_if_no_trade", "pkgmd250v": "div250_step_if_low_volume", "pkgmc": "package_m_corrob"}
UP = float(os.environ.get("FRAC", "-0.10")) > 0   # walk direction: the mark move is read on that side
med = lambda a, b, c: pl.max_horizontal(pl.min_horizontal(a, b), pl.min_horizontal(pl.max_horizontal(a, b), c))
mark = lambda f: pl.read_csv(f).drop_nulls(["bid", "ask", "last"]).select("h", "ms", (med(pl.col("m1"), pl.col("m2"), med(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mk"))
rows = []
for c, (prep, ext, t0) in PREP.items():
    blk = pl.read_ipc(f"{ROOT}/data/{prep}/blocks.arrow")
    E = (pl.read_parquet(f"{ROOT}/data/{ext}/tables/oracle.parquet").filter(pl.col("coin") == f"xyz:{c}", pl.col("ext").is_not_null())
         .select(ms=pl.col("t").dt.epoch("ms"), E="ext").sort("ms"))
    tk = lambda n: (pl.read_csv(f"{D}/tk_{n}.csv").join(blk, on="h").sort("ms").join_asof(E, on="ms")
                    .with_columns(ntl=pl.col("q").abs() * pl.col("px"), val=pl.col("q") * (pl.col("E") - pl.col("px"))))
    for mk in DM:
        b = f"{c}_{mk}_base"
        if not os.path.exists(f"{D}/orc_{b}.csv"):
            print(f"ramp_eval: no base run {b} in {D}: skipped", file=sys.stderr); continue
        mb, tb = mark(f"{D}/orc_{b}.csv"), tk(b)
        rb = pl.read_csv(f"{D}/rd_{b}.csv").filter(pl.col("sim_rounds") > 0).join(blk.rename({"h": "sim_h1"}), on="sim_h1")
        gb = pl.read_csv(f"{D}/trig_{b}.csv", infer_schema_length=None)
        for f in sorted(glob.glob(f"{D}/orc_{c}_{mk}_w*.csv")):
            tag = os.path.basename(f)[:-4].split("_")[-1]
            ramp = int(tag[1:]) * 1000
            w0, w1 = t0, t0 + ramp + HOLD + 120_000
            n = f"{c}_{mk}_{tag}"
            m = mark(f).join(mb.select("h", pl.col("mk").alias("mb")), on="h").filter(pl.col("ms").is_between(w0, w1))
            ta = tk(n); win = lambda t: t.filter(pl.col("ms").is_between(w0, w1))
            ra = pl.read_csv(f"{D}/rd_{n}.csv").filter(pl.col("sim_rounds") > 0).join(blk.rename({"h": "sim_h1"}), on="sim_h1")
            liq = lambda r: float(r.filter(pl.col("ms").is_between(w0, w1))["sim_filled"].sum())
            ga = pl.read_csv(f"{D}/trig_{n}.csv", infer_schema_length=None); stops = lambda g: g.filter(pl.col("ms").is_between(w0, w1)).height
            rows.append(dict(coin=c, mark=mk, design=DM[mk], case=f"{'+' if UP else '-'}10% over {ramp // 1000} s, held 2 min",
                             per_update_pct=round(10 * 3 / (ramp / 1000), 2),
                             mark_move_bp=round(float(((m["mk"] / m["mb"] - 1) * 1e4).max() if UP else ((m["mk"] / m["mb"] - 1) * 1e4).min()), 1),
                             extra_takeover_usd=round(win(ta)["ntl"].sum() - win(tb)["ntl"].sum()),
                             extra_book_liq_shares=round(liq(ra) - liq(rb), 1), extra_stops=stops(ga) - stops(gb),
                             value_at_takeover_change=round(float(ta["val"].sum() - tb["val"].sum()))))
R = pl.DataFrame(rows)
pl.Config.set_tbl_rows(80); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(12)
print(R.sort("case", "coin", "mark"))
print(R.group_by("design", "case").agg(pl.col("mark_move_bp").min(), pl.col("extra_takeover_usd").sum(), pl.col("extra_stops").sum(),
                                       pl.col("extra_book_liq_shares").sum(), pl.col("value_at_takeover_change").sum()).sort("case", "design"))
registry.maybe_record(R.to_dicts(), kind="spike", command="zsh sim/runs/ramp_runs.sh; FRAC=+0.10 S=data/scen/ramp_up zsh sim/runs/ramp_runs.sh; python sim/score/ramp_eval.py [DIR]")
