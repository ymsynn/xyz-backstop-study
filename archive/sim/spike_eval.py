"""External-price spike: each spiked run against the same mark without the spike.
Per run: the largest mark move vs the baseline in the 60 s from the spike (bp, negative = down), takeovers, book
liquidation and stop orders the spike added in the next 120 s, and the change in value at takeover (fair = Binance).
Usage: python spike_eval.py DIR   (DIR from spike_runs.sh: {orc,tk,rd,trig}_{COIN}_{MARK}_{TAG}.csv)
"""
import sys
import polars as pl
import os, registry

D = sys.argv[1]
ROOT = os.environ.get("REPO", os.getcwd())   # run from the repository root
PREP = {"GOOGL": "prep_GOOGL_1028", "AMZN": "prep_AMZN_1029"}
SPIKE = {("GOOGL", "a"): 1793218200000, ("GOOGL", "q"): 1793226600000, ("AMZN", "a"): 1793304600000, ("AMZN", "q"): 1793313000000}
med = lambda a, b, c: pl.max_horizontal(pl.min_horizontal(a, b), pl.min_horizontal(pl.max_horizontal(a, b), c))
def mark(f):
    o = pl.read_csv(f).drop_nulls(["bid", "ask", "last"])
    return o.select("h", "ms", (med(pl.col("m1"), pl.col("m2"), med(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mk"))
rows = []
for c in PREP:
    blk = pl.read_ipc(f"{ROOT}/data/{PREP[c]}/blocks.arrow")
    F = pl.read_parquet(f"{ROOT}/data/binance/{c}USDT_100ms.parquet").select("ms", pl.col("last").alias("F")).sort("ms")
    def tk(n):
        t = pl.read_csv(f"{D}/tk_{n}.csv").join(blk, on="h").sort("ms").join_asof(F, on="ms")
        return t.with_columns(ntl=pl.col("q").abs() * pl.col("px"), val=pl.col("q") * (pl.col("F") - pl.col("px")))
    def rd(n, t0, dur=0):
        r = pl.read_csv(f"{D}/rd_{n}.csv").filter(pl.col("sim_rounds") > 0).join(blk.rename({"h": "sim_h1"}), on="sim_h1")
        return float(r.filter(pl.col("ms").is_between(t0, t0 + dur + 120_000))["sim_filled"].sum())
    def trig(n, t0, dur=0):
        x = pl.read_csv(f"{D}/trig_{n}.csv").filter(pl.col("ms").is_between(t0, t0 + dur + 120_000))
        return x.height, float(x["taker_sz"].sum())
    for mk in [m for m in ("today", "noclamp", "et", "p3", "p4", "p4b", "p4c", "p4d", "pkg", "pkgc", "pkgt", "pkgs", "pkge", "pkgx", "pkgz", "pkgy", "pkgw", "pkgv", "pkgk", "pkgm", "pkgmd250", "pkgmd250s", "pkgmint", "pkgmbook") if os.path.exists(f"{D}/orc_{c}_{m}_base.csv")]:
        b = f"{c}_{mk}_base"
        mb, tb = mark(f"{D}/orc_{b}.csv"), tk(b)
        tags = sorted({os.path.basename(f).split("_")[-1][:-4] for f in __import__("glob").glob(f"{D}/orc_{c}_{mk}_*.csv")} - {"base"}, key=lambda t: (t[0], int(t[1:-1])))
        for tag in tags:
            n = f"{c}_{mk}_{tag}"
            t0 = SPIKE[(c, tag[0])]
            dur = int(tag[1:-1]) * 1000
            m = mark(f"{D}/orc_{n}.csv").join(mb.select("h", pl.col("mk").alias("mb")), on="h").filter(pl.col("ms").is_between(t0, t0 + dur + 60_000))
            d = ((m["mk"] / m["mb"] - 1) * 1e4)
            ta = tk(n)
            win = lambda t: t.filter(pl.col("ms").is_between(t0, t0 + dur + 120_000))
            ca, cb = trig(n, t0, dur), trig(b, t0, dur)
            rows.append(dict(coin=c, mark=mk, spike=("16:10 ET, " if tag[0] == "a" else "18:30 ET, ") + (f"{dur // 60000} min" if dur >= 60000 else f"{dur // 1000} s"),
                             mark_move_bp=round(float(d.min()), 1), extra_takeover_usd=round(win(ta)["ntl"].sum() - win(tb)["ntl"].sum()),
                             extra_book_liq_shares=round(rd(n, t0, dur) - rd(b, t0, dur), 1), extra_stops=ca[0] - cb[0], extra_stop_size=round(ca[1] - cb[1], 1),
                             value_at_takeover_change=round(float(ta["val"].sum() - tb["val"].sum()))))
pl.Config.set_tbl_rows(200); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(12)
print(pl.DataFrame(rows))

dm = {"today": "current", "noclamp": "p1", "et": "p2", "p3": "p3", "p4": "p4", "p4b": "p4b", "p4c": "p4c", "p4d": "p4d", "pkg": "package", "pkgc": "package_cap", "pkgt": "package_trig", "pkgs": "package_step", "pkge": "package_ema", "pkgx": "package_x", "pkgz": "package_z", "pkgy": "package_y", "pkgw": "package_w", "pkgv": "package_v", "pkgk": "package_k", "pkgm": "package_m", "pkgmd250": "package_m_div250", "pkgmd250s": "package_m_div250_stale", "pkgmint": "package_m_int", "pkgmbook": "package_m_book", **registry.design_map()}
registry.maybe_record([dict(r, design=dm[r["mark"]], case=r["spike"]) for r in rows], kind="spike",
                      command=" ".join(f"{k}={__import__('shlex').quote(__import__('os').environ[k])}" for k in ("REG", "REG_MERGE", "REG_MAP") if __import__('os').environ.get(k)) + " python sim/spike_eval.py " + D)
