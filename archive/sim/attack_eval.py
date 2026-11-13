"""Mark-push attack evaluation: each attack (ATTACK_OUT log of the attacked run) against the same run without attacks.
Per attack: what the sweeps cost (slippage vs the mid before each sweep), the largest mark move vs the baseline in the
next 60 s (bp, in the attack's direction), how long the mark stayed 25+ bp off, and the takeovers / book-liquidation
size the attack added in the next 120 s.

Usage: python attack_eval.py PREP BASE_ORC BASE_TK BASE_RD ATK_ORC ATK_TK ATK_RD ATK_LOG
"""
import sys
import polars as pl

prep, bo, btk, brd, ao, atk, ard, log = sys.argv[1:9]
import os
FAIR = os.environ.get("FAIR")
blk = pl.read_ipc(f"{prep}/blocks.arrow")
med = lambda a, b, c: pl.max_horizontal(pl.min_horizontal(a, b), pl.min_horizontal(pl.max_horizontal(a, b), c))
def mark(f):
    o = pl.read_csv(f).drop_nulls(["bid", "ask", "last"])
    return o.select("h", "ms", (med(pl.col("m1"), pl.col("m2"), med(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mark"))
m = mark(ao).join(mark(bo).select("h", pl.col("mark").alias("base")), on="h").with_columns(d=(pl.col("mark") / pl.col("base") - 1) * 1e4)
def liq(tk, rd):
    t = pl.read_csv(tk).join(blk, on="h").select("ms", (pl.col("q").abs() * pl.col("px")).alias("ntl"))
    return t
L = pl.read_csv(log)
rows = []
for i, g in L.group_by("id", maintain_order=True):
    t0, sell = g["ms"].min(), True
    w = m.filter((pl.col("ms") >= t0) & (pl.col("ms") <= t0 + 60_000))
    dmax = float((-w["d"]).max()) if w.height else 0.0
    off = w.filter(-pl.col("d") >= 25)
    span = (off["ms"].max() - off["ms"].min()) / 1000 + 3 if off.height else 0.0
    tk_a = liq(atk, ard).filter((pl.col("ms") >= t0) & (pl.col("ms") <= t0 + 120_000))
    tk_b = liq(btk, brd).filter((pl.col("ms") >= t0) & (pl.col("ms") <= t0 + 120_000))
    def rounds(rd):
        r = pl.read_csv(rd).filter(pl.col("sim_rounds") > 0).join(blk.rename({"h": "sim_h1"}), on="sim_h1")
        return float(r.filter((pl.col("ms") >= t0) & (pl.col("ms") <= t0 + 120_000))["sim_filled"].sum())
    # whole run: takeover notional and value at takeover vs fair (FAIR parquet, if given)
    def whole(tk):
        t = pl.read_csv(tk).join(blk, on="h").sort("ms")
        v = None
        if FAIR:
            t = t.join_asof(pl.read_parquet(FAIR).select("ms", pl.col("last").alias("F")).sort("ms"), on="ms")
            v = float((t["q"] * (t["F"] - t["px"])).sum())
        return float((t["q"].abs() * t["px"]).sum()), v
    (na, va), (nb, vb) = whole(atk), whole(btk)
    rows.append(dict(attack_ntl=g["ntl"][0], sweeps=g.height, filled_usd=round(g["filled_ntl"].sum()), cost_usd=round(g["cost"].sum()),
                     mark_move_bp=round(dmax, 1), secs_25bp_off=round(span, 1),
                     extra_takeover_usd_120s=round(tk_a["ntl"].sum() - tk_b["ntl"].sum()),
                     extra_book_liq_shares_120s=round(rounds(ard) - rounds(brd), 1),
                     extra_inherited_usd=round(na - nb), value_at_takeover_change=round(va - vb) if FAIR else None))
pl.Config.set_tbl_width_chars(200)
print(pl.DataFrame(rows)) if not os.environ.get("ROWS") else [print(r) for r in rows]
