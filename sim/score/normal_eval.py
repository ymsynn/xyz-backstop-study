"""Normal markets: a design vs today's formula over the out-of-hours sessions, crash windows excluded.
Reads DIR/{orc,tk,rd,trig}_{COIN}_{MARK}.csv from sim/runs/normal_runs.sh. Crash window = onset - 60 s .. onset + 30 min.
Per coin and session (overnight 00:00-08:00 UTC, pre-market 08:00-13:30, post-market 20:00-24:00):
  mark distance to today's (bp), mark distance to E, per-update mark change, oracle gap |O_today - E| (what P4's O = E would change
  in funding), and liquidations / takeovers / stops that fire under one mark and not the other.
Usage: python normal_eval.py DIR [MARK=p4]   (REG=normal-markets to record)
"""
import json, math, os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
import registry

D = sys.argv[1]
MK = sys.argv[2] if len(sys.argv) > 2 else "p4"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
DAY = os.environ.get("DAY")   # quiet day (1020, 1021): no crash window to exclude
if DAY:
    T = {"1020": 1792526400000, "1021": 1792612800000}[DAY]
    CO = {c: (f"prep_{c}_{DAY}", T, None) for c in ("GOOGL", "INTC", "AMZN")}
else:
    CO = {"GOOGL": ("prep_GOOGL_1028", 1793217600000, 118_800), "INTC": ("prep_INTC_1029", 1793304000000, 66_800), "AMZN": ("prep_AMZN_1029", 1793304000000, 63_900)}
DESIGN = {"pkgm3q1800": "three_vote_30min_ratchet_book", "p4": "p4", "p2": "p2", "pkg": "package", "pkgc": "package_cap", "pkgt": "package_trig", "pkgs": "package_step", "pkge": "package_ema", "pkgz": "package_z", "pkgy": "package_y", "pkgw": "package_w", "pkgv": "package_v", "pkgk": "package_k", "pkgm": "package_m", "pkgmd500": "package_m_div500", "pkgmd250": "package_m_div250", "pkgmd250s": "package_m_div250_stale", "pkgmint": "package_m_int", "pkgm3k1800": "three_vote_30min_onerule", "pkgm3r1800": "three_vote_30min_ratchet", "pkgmbook": "package_m_book"}[MK]


def engine_mark(o, step):
    """The mark at each relayer update, as the engine forms it (engine/src/clearing.rs, mark_of and book_px), in price
    micro-units: the median of the two published values and xyz's book price, within 1% of the previous update's mark.
    The book price is the median of best bid, best ask and last trade; with one side of the book empty, the lone quote.
    An update with no book price has no mark, and the next update is then not clamped. `step`: the clamp's rounding step."""
    out, prev = [], None
    for m1, m2, b, a, l in o.select("m1", "m2", "bid", "ask", "last").iter_rows():
        if b is not None and a is not None and l is not None:
            bk = sorted((b, a, l))[1]
        elif (b is None) != (a is None):
            bk = b if b is not None else a
        else:
            bk = None
        if bk is None:
            out.append(None); prev = None; continue
        x = sorted((m1, m2, bk))[1]
        if prev is not None:   # rounded half away from zero, as Rust's f64::round
            pm = prev / 1e6
            lo = math.floor(pm * 0.99 * 1e6 / step + 0.5) * step
            hi = math.floor(pm * 1.01 * 1e6 / step + 0.5) * step
            x = min(max(x, lo), hi)
        out.append(x); prev = x
    return out


def session(ms):
    h = (pl.col(ms) % 86_400_000) / 3_600_000
    return pl.when(h < 8).then(pl.lit("overnight")).when(h < 13.5).then(pl.lit("pre-market")).when(h < 20).then(pl.lit("regular")).otherwise(pl.lit("post-market"))


def q(s, p):
    return round(float(s.quantile(p)), 2) if len(s) else None


rows = []
for c, (prep, T, onset) in CO.items():
    blk = pl.read_ipc(f"{ROOT}/data/{prep}/blocks.arrow")
    c0, c1 = (T + onset - 60_000, T + onset + 1_800_000) if onset is not None else (0, -1)
    normal = lambda df, col="ms": df.with_columns(sess=session(col)).filter((pl.col("sess") != "regular") & ~pl.col(col).is_between(c0, c1))

    def mark(m):
        o = pl.read_csv(f"{D}/orc_{c}_{m}.csv")
        mk = engine_mark(o, 10 ** json.load(open(f"{ROOT}/data/{prep}/meta.json"))["sz_decimals"])
        return o.with_columns(mk=pl.Series(mk, dtype=pl.Float64)).drop_nulls("mk").select("h", "ms", "ext", "m1", pl.col("mk") / 1e6)
    a, b = mark("today"), mark(MK)
    j = normal(a.join(b.select("h", pl.col("mk").alias("mk2")), on="h")).sort("ms")
    j = j.with_columns(e=pl.col("ext") / 1e6, o=pl.col("m1") / 1e6)
    j = j.with_columns(diff=((pl.col("mk2") / pl.col("mk") - 1) * 1e4).abs(), te=((pl.col("mk") / pl.col("e") - 1) * 1e4).abs(),
                       te2=((pl.col("mk2") / pl.col("e") - 1) * 1e4).abs(), og=((pl.col("o") / pl.col("e") - 1) * 1e4).abs(),
                       dm=((pl.col("mk") / pl.col("mk").shift(1) - 1) * 1e4).abs(), dm2=((pl.col("mk2") / pl.col("mk2").shift(1) - 1) * 1e4).abs())

    def events(m):
        # quiet days can have no takeover: fix the column types of an empty file
        tk = pl.read_csv(f"{D}/tk_{c}_{m}.csv", schema_overrides={"u": pl.Int64, "h": pl.Int64, "q": pl.Float64, "px": pl.Float64}).join(blk, on="h")
        rd = pl.read_csv(f"{D}/rd_{c}_{m}.csv", schema_overrides={"u": pl.Int64, "sim_h1": pl.Int64, "sim_rounds": pl.Int64, "sim_filled": pl.Float64}).filter(pl.col("sim_rounds") > 0).join(blk.rename({"h": "sim_h1", "ms": "ms"}), on="sim_h1")
        tg = pl.read_csv(f"{D}/trig_{c}_{m}.csv", schema_overrides={"h": pl.Int64, "ms": pl.Int64, "oid": pl.Int64, "taker_sz": pl.Float64})
        return normal(tk), normal(rd), normal(tg)
    (tka, rda, tga), (tkb, rdb, tgb) = events("today"), events(MK)
    for s in ("overnight", "pre-market", "post-market", "all"):
        f = (lambda d: d) if s == "all" else (lambda d, s=s: d.filter(pl.col("sess") == s))
        x = f(j)
        if x.height == 0:
            continue
        ua, ub = set(f(rda)["u"]) | set(f(tka)["u"]), set(f(rdb)["u"]) | set(f(tkb)["u"])
        oa, ob = set(f(tga)["oid"]), set(f(tgb)["oid"])
        sz = lambda t, keep: round(float(t.filter(pl.col("oid").is_in(list(keep)))["taker_sz"].sum()), 1)
        rows.append(dict(design=DESIGN, coin=c, case=(f"10-{DAY[2:]} " if DAY else "") + s, hours=round(x.height * 3 / 3600, 1),
                         mark_vs_today_p50_bp=q(x["diff"], .5), mark_vs_today_p99_bp=q(x["diff"], .99), mark_vs_today_max_bp=round(float(x["diff"].max()), 1),
                         mark_vs_E_today_p50_bp=q(x["te"], .5), mark_vs_E_p50_bp=q(x["te2"], .5),
                         step_today_p99_bp=q(x["dm"].drop_nulls(), .99), step_p99_bp=q(x["dm2"].drop_nulls(), .99),
                         oracle_gap_p99_bp=q(x["og"], .99),
                         liq_accounts_today=len(ua), liq_accounts=len(ub), liq_only_today=len(ua - ub), liq_only_new=len(ub - ua),
                         stops_today=len(oa), stops=len(ob), stops_only_today=len(oa - ob), stops_only_new=len(ob - oa),
                         stops_only_today_size=sz(f(tga), oa - ob), stops_only_new_size=sz(f(tgb), ob - oa)))

pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(260); pl.Config.set_tbl_cols(30)
print(pl.DataFrame(rows))
registry.maybe_record(rows, kind="normal", command=" ".join(f"{k}={os.environ[k]}" for k in ("REG",) if os.environ.get(k)) + f" python sim/score/normal_eval.py {D} {MK}")
