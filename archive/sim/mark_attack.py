"""Mark-push attack: how far a book push moves the mark under today's formula vs the external-anchored band, what the
push costs, and how much position it could liquidate.

Usage: python mark_attack.py DEPTH_CSV PREP_DIR MAXLEV [W_BP PMAX_BP TAU_S]
DEPTH_CSV: the replay's DEPTH_OUT (book notional within d bp of mid, per side, every minute).
Formulas (the attack moves the perp book only; the external price is unaffected; per-update clamps do not bind at
these speeds):
  today: mark = median(oracle ~ ext, ext + e, local); e = EMA_150s(mid - ext). A push of d held T s moves the mark by
         min(d, d (1 - exp(-T/150))), capped at 1/maxLev.
  band:  mark = clamp(local, C - w, C + w), C = ext + clamp(P, +-pmax), P = EMA_tau(mid - ext): min(d, w + min(pmax,
         d (1 - exp(-T/tau)))).
Cost (lower bound): one sweep of the book to d below mid (notional), losing about d/2 on it; holding the push longer
costs more (replenished liquidity), not counted. Target: notional of margined positions whose liquidation price (start
of day) is within the mark move.
"""
import math, sys
import polars as pl

depth_csv, prep, maxlev = sys.argv[1], sys.argv[2], float(sys.argv[3])
w, pmax, tau = (float(x) for x in (sys.argv[4:7] if len(sys.argv) > 6 else (25, 50, 1800)))
dep = pl.read_csv(depth_csv)
a = pl.read_ipc(f"{prep}/acc_init.arrow").filter(pl.col("q") != 0, pl.col("lp").is_not_nan())
m0 = float(dep["mid"][0])

def today(d, T): return min(d, d * (1 - math.exp(-T / 150)), 1e4 / maxlev)
def band(d, T): return min(d, w + min(pmax, d * (1 - math.exp(-T / tau))))
def target(move_bp):  # longs liquidated by a downward mark move of move_bp (start-of-day positions)
    lim = m0 * (1 - move_bp / 1e4)
    x = a.filter(pl.col("q") > 0, pl.col("lp") >= lim)
    return float((x["q"] * m0).sum())

cost = dep.filter(pl.col("side") == "bid").group_by("dbps").agg(pl.col("ntl").median().alias("sweep_med"), pl.col("ntl").quantile(0.1).alias("sweep_p10")).sort("dbps")
print(f"book: notional to sweep the bids to d bp below mid (median / 10th percentile over the day's minutes); mid {m0:.2f}")
print(cost)
rows = []
for d in (25, 50, 100, 200, 500):
    c = cost.filter(pl.col("dbps") == d)
    sw = float(c["sweep_med"][0]) if c.height else float("nan")
    for T in (3, 30, 150, 600):
        mt, mb = today(d, T), band(d, T)
        rows.append(dict(push_bp=d, hold_s=T, sweep_usd=round(sw), slip_cost_usd=round(sw * d / 2e4), move_today_bp=round(mt, 1),
                         move_band_bp=round(mb, 1), target_today_usd=round(target(mt)), target_band_usd=round(target(mb))))
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(220)
print(f"band: w {w} bp, premium cap {pmax} bp, tau {tau} s")
print(pl.DataFrame(rows))
