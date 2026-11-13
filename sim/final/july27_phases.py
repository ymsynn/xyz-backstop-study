"""SK Hynix on July 27, 2026, phase by phase, under today's rules and the proposal (final run, data/scen/final/skhx).
For each phase: liquidated through the book (every round of liq_, filled size at its average price; accounts), taken over
by the vault (tk_; count, notional, value at the external price at that instant). Then how far each mark sat above xyz's
book between 11:00 and 23:00 UTC, and the second false price at 23:02.
Usage: python sim/final/july27_phases.py [DIR=data/scen/final/skhx]"""
import calendar, sys
import polars as pl
sys.path.insert(0, "sim")
import figs

T = sys.argv[1] if len(sys.argv) > 1 else "data/scen/final/skhx"
D = lambda h, m=0, s=0: calendar.timegm((2026, 7, 27, h, m, s)) * 1000
PHASES = [("00:00-11:00, venue open", 0, D(11)), ("11:00-17:17, closure, book falling", D(11), D(17, 17, 45)), ("17:17-23:00", D(17, 17, 45), D(23)),
          ("23:00-23:10, false price", D(23), D(23, 10)), ("after 23:10", D(23, 10), 10**14)]
print("| Phase (UTC) | Rules | Through the book $M | Accounts | Takeovers | Taken over $M | Value at the external price $k |")
print("|---|---|---|---|---|---|---|")
marks = {}
for rules, d in (("today", "today"), ("proposal", "lead3q1800")):
    m = figs.fmarks(T, f"SKHX_0727_{d}").sort("h"); marks[rules] = m
    tk = figs.ftk(T, f"SKHX_0727_{d}").sort("h").join_asof(m.select("h", "ms", "E"), on="h")
    lq = pl.read_csv(f"{T}/liq_SKHX_0727_{d}.csv", schema_overrides={"filled": pl.Float64, "avg_px": pl.Float64}).with_columns(n=(pl.col("filled") * pl.col("avg_px")).fill_nan(0).fill_null(0))
    for name, a, b in PHASES:
        t = tk.filter(pl.col("ms").is_between(a, b, closed="left")); l = lq.filter(pl.col("ms").is_between(a, b, closed="left"))
        print(f"| {name} | {rules} | {l['n'].sum() / 1e6:.2f} | {l['u'].n_unique()} | {t.height} | {t['ntl'].sum() / 1e6:.2f} | {float((t['q'] * (t['E'] - t['px'])).sum()) / 1e3:+.1f} |")
print()
print("| Between 11:00 and 23:00 UTC | today | proposal |")
print("|---|---|---|")
g = {k: (v.filter(pl.col("ms").is_between(D(11), D(23)))["mk"] / v.filter(pl.col("ms").is_between(D(11), D(23)))["B"] - 1) * 100 for k, v in marks.items()}
print(f"| Updates with the mark more than 2% from xyz's book | {100 * (g['today'].abs() > 2).mean():.1f}% | {100 * (g['proposal'].abs() > 2).mean():.1f}% |")
print(f"| Updates with the mark more than 5% from xyz's book | {100 * (g['today'].abs() > 5).mean():.1f}% | {100 * (g['proposal'].abs() > 5).mean():.1f}% |")
print(f"| Largest distance of the mark above xyz's book | {g['today'].max():.2f}% | {g['proposal'].max():.2f}% |")
w = {k: v.filter(pl.col("ms").is_between(D(23, 2), D(23, 6))) for k, v in marks.items()}
print(f"| Highest mark from 23:02 to 23:06 (external price 1,198.50, book near {w['today']['B'].median():,.0f}) | {w['today']['mk'].max():,.2f} | {w['proposal']['mk'].max():,.2f} |")
lo = {k: v.filter(pl.col("ms").is_between(D(23), D(23, 10)))["mk"].min() for k, v in marks.items()}
print(f"| Lowest mark from 23:00 to 23:10 (external price 868.17) | {lo['today']:,.2f} | {lo['proposal']:,.2f} |")
