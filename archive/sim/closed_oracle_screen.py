"""Screen a capped internal oracle against trade.xyz's real internal sessions (all xyz markets, local oracle tables).
An internal session = E unchanged for at least MIN_MIN minutes while the oracle moves. Rule R2: the internal oracle's
input is capped at c (today's 50 bp per-update clamp) from the current oracle, so each update moves it by at most
(1 - exp(-dt/tau)) c (tau = trade.xyz's 30 min). Replayed by following the real internal oracle with each step capped
there (a slight underestimate of R2's catch-up). Per session: how far the real oracle moved, R2's largest lag behind it,
and at reopen the gap from each oracle (and from the frozen last E) to the first external price.
Usage: python sim/closed_oracle_screen.py   -> data/scen/closed_oracle_screen.csv"""
import glob, math, os
import polars as pl
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C, TAU, MIN_MIN = 0.005, 1800.0, float(os.environ.get("MIN_MIN", 30))
rows = []
for f in sorted(glob.glob(f"{ROOT}/data/extract*/tables/oracle.parquet")):
    day = f.split("extract")[1][:4]
    o = pl.read_parquet(f).filter(pl.col("ext").is_not_null()).sort("coin", "h")
    for coin, g in o.group_by("coin"):
        g = g.unique("h", keep="first", maintain_order=True).sort("h")
        E, O, T = g["ext"].to_list(), g["oracle"].to_list(), g["t"].dt.epoch("ms").to_list()
        n, i = len(E), 1
        while i < n:
            j = i
            while j < n and E[j] == E[j - 1]: j += 1
            # run [i-1, j-1] has constant E; internal if long enough and the oracle moved
            if (T[j - 1] - T[i - 1]) / 60000 >= MIN_MIN and max(O[i - 1:j]) != min(O[i - 1:j]):
                s0, r2, lag = O[i - 1], O[i - 1], 0.0
                for k in range(i, j):
                    a = 1 - math.exp(-min((T[k] - T[k - 1]) / 1000, 0.1 * TAU) / TAU)
                    step = O[k] - r2
                    cap = a * C * r2
                    r2 += max(-cap, min(cap, step))
                    lag = max(lag, abs(O[k] - r2) / O[k] * 1e4)
                reopen = E[j] if j < n else None
                bp = lambda x: None if reopen is None else round(abs(x - reopen) / reopen * 1e4, 1)
                rows.append(dict(day=day, coin=coin[0].replace("xyz:", ""), start=T[i - 1], minutes=round((T[j - 1] - T[i - 1]) / 60000),
                                 real_move_bp=round((O[j - 1] - s0) / s0 * 1e4, 1), r2_lag_max_bp=round(lag, 1),
                                 reopen_gap_real_bp=bp(O[j - 1]), reopen_gap_r2_bp=bp(r2), reopen_gap_frozen_bp=bp(E[i - 1])))
            i = j + 1
R = pl.DataFrame(rows).with_columns(start=pl.from_epoch("start", time_unit="ms").dt.strftime("%m-%d %H:%M"))
R.write_csv(f"{ROOT}/data/scen/closed_oracle_screen.csv")
pl.Config.set_tbl_rows(20); pl.Config.set_tbl_width_chars(200)
print("internal sessions:", R.height, "| coins:", R["coin"].n_unique(), "| with a reopen in the data:", R.filter(pl.col("reopen_gap_real_bp").is_not_null()).height)
print(R.select(pl.col("minutes").median().alias("median_min"), pl.col("real_move_bp").abs().median().alias("median_|move|"), pl.col("real_move_bp").abs().quantile(0.9).alias("p90_|move|"),
               pl.col("real_move_bp").abs().max().alias("max_|move|"), pl.col("r2_lag_max_bp").median().alias("median_r2_lag"), pl.col("r2_lag_max_bp").quantile(0.9).alias("p90_r2_lag"), pl.col("r2_lag_max_bp").max().alias("max_r2_lag")))
ro = R.filter(pl.col("reopen_gap_real_bp").is_not_null())
print("at reopen (gap to the first external price, bp):")
print(ro.select(*[pl.col(c).median().alias(f"median_{c[11:-3]}") for c in ("reopen_gap_real_bp", "reopen_gap_r2_bp", "reopen_gap_frozen_bp")],
                *[pl.col(c).mean().round(1).alias(f"mean_{c[11:-3]}") for c in ("reopen_gap_real_bp", "reopen_gap_r2_bp", "reopen_gap_frozen_bp")],
                (pl.col("reopen_gap_r2_bp") <= pl.col("reopen_gap_real_bp")).mean().round(3).alias("r2_closer_or_equal_share")))
print(R.sort("r2_lag_max_bp", descending=True).head(10))
