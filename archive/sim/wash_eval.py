"""xyz push beyond the band (wash prints at a fixed price above the crashing feed): each run vs the same mark's base run.
Per run: the largest upward mark gap vs base during the attack (bp), how long the band held (from the engine log is not read:
counted here as updates where the attacked mark is above base by > 50 bp), takeovers and their notional, value at takeover
(q (F - px), F = Binance, a yardstick only) and book-liquidation shares, all vs base over the whole replay.
Usage: python wash_eval.py DIR   (DIR from sim/wash_runs.sh)   REG=push-wash to record
"""
import glob, os, sys
import polars as pl
import registry

D = sys.argv[1]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = 1793217718800
blk = pl.read_ipc(f"{ROOT}/data/prep_GOOGL_1028/blocks.arrow")
F = pl.read_parquet(f"{ROOT}/data/binance/GOOGLUSDT_100ms.parquet").select("ms", pl.col("last").alias("F")).sort("ms")
med = lambda a, b, c: pl.max_horizontal(pl.min_horizontal(a, b), pl.min_horizontal(pl.max_horizontal(a, b), c))
mark = lambda n: pl.read_csv(f"{D}/orc_GOOGL_{n}.csv").drop_nulls(["bid", "ask", "last"]).select("h", "ms", (med(pl.col("m1"), pl.col("m2"), med(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mk"))
def tk(n):
    t = pl.read_csv(f"{D}/tk_GOOGL_{n}.csv").join(blk, on="h").sort("ms").join_asof(F, on="ms")
    return t.with_columns(ntl=pl.col("q").abs() * pl.col("px"), val=pl.col("q") * (pl.col("F") - pl.col("px")))
rd = lambda n: float(pl.read_csv(f"{D}/rd_GOOGL_{n}.csv").filter(pl.col("sim_rounds") > 0)["sim_filled"].sum())
DM = {"today": "current", "et": "p2", "p4": "p4", "p4b": "p4b", "p4c": "p4c", "p4d": "p4d", "pkg": "package", "pkgc": "package_cap", "pkgt": "package_trig", "pkgs": "package_step", "pkge": "package_ema", "pkgz": "package_z", "pkgy": "package_y", "pkgw": "package_w", "pkgv": "package_v", "pkgk": "package_k", "pkgm": "package_m", "pkgmd250n": "div250_never_step", "pkgmd250s": "div250_step_if_no_trade", "pkgmd250v": "div250_step_if_low_volume"}
RUN_PREFIX = os.environ.get("RUN_PREFIX", "w")   # w: wash runs (wash_runs.sh), p: book-prop runs (prop_runs.sh)
rows = []
for mk in DM:
    b = f"{mk}_base"
    if not os.path.exists(f"{D}/orc_GOOGL_{b}.csv"):
        continue
    mb, tb, rb = mark(b), tk(b), rd(b)
    for f in sorted(glob.glob(f"{D}/orc_GOOGL_{mk}_{RUN_PREFIX}*.csv")):
        n = os.path.basename(f)[len("orc_GOOGL_"):-4]
        w, fr, d = n.split("_")[1:]
        dur = int(d[1:]) * 1000
        m = mark(n).join(mb.select("h", pl.col("mk").alias("mb")), on="h").filter(pl.col("ms").is_between(C - 5000, C + dur + 60_000))
        gap = (m["mk"] / m["mb"] - 1) * 1e4
        ta = tk(n)
        rows.append(dict(design=DM[mk], case=(f"{float(w[1:]) * 10 / 1e6:.0f}M$/30s" if RUN_PREFIX == "w" else f"buy limit {float(w[1:]) / 1e6:g}M$/block" if RUN_PREFIX == "p" else f"attacker capital {float(w[1:]) / 1e6:g}M$") + f" at +{float(fr[1:]) * 100:.0f}%, {dur // 60000 if dur >= 60000 else dur // 1000}{' min' if dur >= 60000 else ' s'}",
                         mark_up_max_bp=round(float(gap.max()), 1), mark_up_min=round(float((gap > 50).sum()) * 3 / 60, 1),
                         takeovers=ta.height - tb.height, inherited_musd=round((ta["ntl"].sum() - tb["ntl"].sum()) / 1e6, 2),
                         value_at_takeover_change=round(float(ta["val"].sum() - tb["val"].sum())), book_liq_shares=round(rd(n) - rb, 1)))
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(12)
print(pl.DataFrame(rows))
registry.maybe_record(rows, kind="push", command=(f"REG={os.environ['REG']} " if os.environ.get("REG") else "") + f"python sim/wash_eval.py {D}")
