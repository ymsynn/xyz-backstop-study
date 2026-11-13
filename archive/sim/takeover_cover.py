"""Does the takeover premium cover the gap to fair value? For each backstop takeover of a run: the vault receives q at
the transfer price px (the trader ends at 0), so its cushion at the mark is eq = q (mark - px), and against fair value F
(trade.xyz's external price at that update, or another source) it starts at q (F - px) = eq + q (F - mark). A takeover
is covered when that is >= 0. Also q (F(t + dt) - px) a little later (price path, not the takeover).

Usage: python takeover_cover.py ORC_CSV PREP_DIR TK_CSV [TK_CSV ...]   (ORC_CSV: the replay's ORC_OUT, for ext)
FAIR=path.parquet (columns ms, last): use that series as F instead (e.g. Binance's stock perp, data/binance/*_100ms),
and also report its basis to ext at the takeovers.
"""
import os
import sys
import polars as pl

orc, prep, tks = sys.argv[1], sys.argv[2], sys.argv[3:]
ext = pl.read_csv(orc).select("ms", (pl.col("ext") / 1e6).alias("ext")).sort("ms")
fair = os.environ.get("FAIR")
o = pl.read_parquet(fair).select("ms", pl.col("last").alias("F")).sort("ms") if fair else ext.rename({"ext": "F"})
b = pl.read_ipc(f"{prep}/blocks.arrow")
rows = []
for f in tks:
    t = pl.read_csv(f).join(b, on="h").sort("ms")
    t = t.join_asof(o, on="ms", strategy="backward").join_asof(ext, on="ms", strategy="backward")
    for dt in (60, 300):
        t = t.join_asof(o.rename({"F": f"F{dt}"}).with_columns(pl.col("ms") - dt * 1000), on="ms", strategy="backward")
    t = t.with_columns(gap=pl.col("q") * (pl.col("F") - pl.col("mark")), net=pl.col("q") * (pl.col("F") - pl.col("px")),
                       net60=pl.col("q") * (pl.col("F60") - pl.col("px")), net300=pl.col("q") * (pl.col("F300") - pl.col("px")),
                       ntl=pl.col("q").abs() * pl.col("px"))
    u = t.filter(pl.col("net") < 0)
    rows.append(dict(run=f.split("/")[-1].removeprefix("tk_").removesuffix(".csv"), takeovers=t.height, ntl_musd=round(t["ntl"].sum() / 1e6, 2),
                     premium_at_mark=round(t["eq"].sum()), gap_to_fair=round(t["gap"].sum()), net_at_takeover=round(t["net"].sum()),
                     underwater_n=u.height, underwater_ntl_musd=round(u["ntl"].sum() / 1e6, 2), underwater_usd=round(u["net"].sum()),
                     net_after_60s=round(t["net60"].sum()), net_after_300s=round(t["net300"].sum()),
                     basis_to_ext_bp=round(float(((t["F"] - t["ext"]) / t["ext"] * 1e4 * t["ntl"]).sum() / t["ntl"].sum()), 1)))
pl.Config.set_tbl_width_chars(250); pl.Config.set_tbl_cols(20)
print(pl.DataFrame(rows))
