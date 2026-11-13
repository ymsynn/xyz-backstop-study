"""Vault capital as a function of all xyz positions: stress curve, worst case and probabilities.

C(positions, r) is the gap model of sim/study/joint_capital.py: every market moves by r_i at once (no time for book
liquidation), positions below 2/3 MM are taken over, C = MM of the inherited inventory - the equity inherited with it
(C_MM; C_ADL = -equity). It is evaluated on one morning snapshot of every xyz position (default 10-30).

Moves:
  stress    every market by the same x (down and up), x = 1..30%
  history   every real hour (and 4 hours) of the 1h candles of all xyz markets (~5,000 hours)
  scaled    the worst real hour, the broadest selloff hour and the worst real 4 hours, every move times 1, 1.5, 2, 3
Probabilities (extreme-value tail): today's need under each real hour, one peak per day (declustered); a generalized
  Pareto fitted to the daily peaks above their 85th percentile gives P(a day's need > K), so P(at least one in a year)
  = 1 - exp(-lambda_u * 365 * sf(K - u)) and the 1-in-Y-years need; 90% intervals from 500 bootstrap refits.
Backtest: fit on the first 60% of days, predicted vs observed days above K in the rest.
(A Student-t factor model was tried first and rejected: hourly tails fit with < 2 degrees of freedom, and it predicted
 22 hours above $0.93M where history has none.)
Limits: 208 days of history, so 10-100-year levels are extrapolations (see the intervals); an instant gap is an upper
bound on stock gaps (0.25-2.4x the measured need) and misses mark-path events (SKHX 07-27).
Usage: python sim/study/capital_risk.py [DAY=1030]  (REG=capital-risk to record) -> data/scen/capital_risk_*.csv"""
import os, sys
import numpy as np
import polars as pl
from scipy import stats
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry
from joint_capital import Book, positions, ROOT

DAY = sys.argv[1] if len(sys.argv) > 1 else "1030"
rng = np.random.default_rng(7)
s, f = positions(DAY); B = Book(s); mk = B.mk; nm = len(mk)
print(f"positions {os.path.basename(f)}: {s.height}, {nm} markets, cross accounts {B.nu}")

# ---- hourly returns, NaN where a market did not exist yet
c = pl.read_parquet(f"{ROOT}/data/candles/xyz_1h.parquet").filter(pl.col("coin").is_in(mk))
w = c.pivot(on="coin", index="t", values="c").sort("t")
for m in mk:
    if m not in w.columns: w = w.with_columns(pl.lit(None, dtype=pl.Float64).alias(m))
X = w.select(mk).to_numpy().astype(float)
R = X[1:] / X[:-1] - 1                                  # NaN before listing; 0 where unchanged
T = R.shape[0]; obs = ~np.isnan(R)
print(f"history: {T} hours, markets with data {int((obs.sum(0) > 200).sum())}")

R0 = np.where(obs, R, 0.0)

def run(Rm):
    out = np.empty((len(Rm), 3))
    for k, r in enumerate(Rm):
        g = B.gap(r); out[k] = (g["C_MM"], g["C_ADL"], g["adl_ntl"])
    return out

# ---- 1. stress curve: every market by the same x
rows = []
for x in (0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30):
    for sg in (-1, 1):
        g = B.gap(np.full(nm, sg * x))
        rows.append(dict(move_pct=sg * x * 100, C_MM_M=g["C_MM"] / 1e6, C_ADL_M=g["C_ADL"] / 1e6, inherits_M=g["v_ntl"] / 1e6, noCross_ADL_M=g["adl_ntl"] / 1e6))
SC = pl.DataFrame(rows).sort("move_pct").with_columns(pl.col(pl.Float64).round(2))
print("stress curve (every market by the same move):"); print(SC)

# ---- 2. history: every real hour and 4 hours
H1 = run(R0)
# the gaps are NaN, not null: fill_null alone would leave them
X4 = pl.DataFrame(X).fill_nan(None).fill_null(strategy="forward").to_numpy()
R4 = np.nan_to_num(X4[4:] / X4[:-4] - 1)
H4 = run(R4)

# ---- 3. tail of today's need under history's moves: one peak per day (declustered), generalized Pareto above u
ts = w["t"].to_numpy()[1:]
day = (ts // 86_400_000)
Dm = pl.DataFrame({"d": day, "C": H1[:, 0], "A": H1[:, 1], "X": H1[:, 2]}).group_by("d").agg(pl.col("C").max(), pl.col("A").max(), pl.col("X").max()).sort("d")
peaks = Dm["C"].to_numpy(); ndays = len(peaks); years = ndays / 365.25
def fit(pk, q=0.85):
    u = np.quantile(pk, q); ex = pk[pk > u] - u
    xi, _, beta = stats.genpareto.fit(ex, floc=0)
    return u, xi, beta, len(ex) / (len(pk) / 365.25)          # threshold, shape, scale, exceedances per year
def level(par, Y):                                            # need exceeded once in Y years (on average)
    u, xi, beta, lam = par
    return u + stats.genpareto.ppf(max(0.0, 1 - 1 / (lam * Y)), xi, 0, beta)
def p_year(par, K):
    u, xi, beta, lam = par
    if K <= u: return float("nan")
    return 1 - np.exp(-lam * stats.genpareto.sf(K - u, xi, 0, beta))
par = fit(peaks)
boot = [fit(rng.choice(peaks, ndays, replace=True)) for _ in range(500)]
ci = lambda fn: np.quantile([fn(b) for b in boot], [0.05, 0.95])
print(f"{ndays} days ({years:.2f} years); tail above u=${par[0]/1e6:.2f}M: shape xi={par[1]:.2f}, {par[3]:.0f} exceedance days per year")
lv = []
for Y in (1, 2, 5, 10, 50, 100):
    lo, hi = ci(lambda b: level(b, Y))
    lv.append(dict(return_period_years=Y, C_MM_M=round(level(par, Y) / 1e6, 2), ci90_lo_M=round(lo / 1e6, 2), ci90_hi_M=round(hi / 1e6, 2)))
LV = pl.DataFrame(lv); print("capital need exceeded once in Y years (today's positions, history's hourly moves):"); print(LV)
tab = []
for K in (0.5e6, 0.93e6, 1.84e6, 3e6, 5e6, 10e6):
    lo, hi = ci(lambda b: p_year(b, K))
    tab.append(dict(K_M=K / 1e6, days_real=int((peaks > K).sum()), P_year=round(p_year(par, K), 4), ci90_lo=round(lo, 4), ci90_hi=round(hi, 4)))
EX = pl.DataFrame(tab); print("P(at least one hour in a year needs more than K):"); print(EX)
# backtest: fit on the first 60% of days, predicted vs observed days above K in the rest
cut = int(ndays * 0.6); pa = fit(peaks[:cut]); rest = peaks[cut:]; yr = len(rest) / 365.25
bt = [dict(K_M=K / 1e6, predicted_days=round(pa[3] * stats.genpareto.sf(K - pa[0], pa[1], 0, pa[2]) * yr, 2) if K > pa[0] else None,
           observed_days=int((rest > K).sum())) for K in (0.1e6, 0.2e6, 0.3e6, 0.5e6, 0.93e6)]
BT = pl.DataFrame(bt); print(f"backtest (fit on {cut} days, test on {len(rest)}; u=${pa[0]/1e6:.2f}M):"); print(BT)

# ---- worst case: the real joint crashes scaled up, and every market at its worst at once
net = s.group_by("market").agg(pl.col("size").sign().mul(pl.col("notional")).sum().alias("net"))
side = dict(zip(net["market"], net["net"]))
adv = np.nan_to_num(np.array([np.nanmin(R[:, j]) if side.get(m, 0) >= 0 else np.nanmax(R[:, j]) for j, m in enumerate(mk)]))
i1 = int(H1[:, 0].argmax())
iw = int(np.argmax([(R0[k] < -0.03).sum() for k in range(T)]))        # the broadest selloff hour
lab = lambda k: pl.from_epoch(pl.Series([int(ts[k])]), time_unit="ms").dt.strftime("%m-%d %H:%M")[0]
wc = []
for name, r in ((f"worst real hour ({lab(i1)})", R0[i1]), (f"broadest selloff hour ({lab(iw)}, {(R0[iw] < -0.03).sum()} markets down > 3%)", R0[iw]),
                (f"worst real 4 hours", R4[int(H4[:, 0].argmax())])):
    for lam in (1, 1.5, 2, 3):
        g = B.gap(np.clip(lam * r, -0.95, None)); wc.append(dict(case=name, scale=lam, C_MM_M=round(g["C_MM"] / 1e6, 2), C_ADL_M=round(g["C_ADL"] / 1e6, 2), noCross_ADL_M=round(g["adl_ntl"] / 1e6, 2)))
g = B.gap(adv); wc.append(dict(case="every market at its worst real hour, adverse side, at once", scale=1, C_MM_M=round(g["C_MM"] / 1e6, 2), C_ADL_M=round(g["C_ADL"] / 1e6, 2), noCross_ADL_M=round(g["adl_ntl"] / 1e6, 2)))
WC = pl.DataFrame(wc); print("worst cases (real joint moves, scaled):"); print(WC)
SC.write_csv(f"{ROOT}/data/scen/capital_risk_stress.csv"); EX.write_csv(f"{ROOT}/data/scen/capital_risk_exceed.csv"); BT.write_csv(f"{ROOT}/data/scen/capital_risk_backtest.csv")
LV.write_csv(f"{ROOT}/data/scen/capital_risk_levels.csv"); WC.write_csv(f"{ROOT}/data/scen/capital_risk_worst.csv")
if os.environ.get("REG"):
    recs = [dict(design="current", case=f"stress {r['move_pct']:+.1f}%", **{k: r[k] for k in ("C_MM_M", "C_ADL_M", "inherits_M", "noCross_ADL_M")}) for r in SC.to_dicts()]
    recs += [dict(design="current", case=f"P(year) need > ${r['K_M']}M", **{k: r[k] for k in ("days_real", "P_year", "ci90_lo", "ci90_hi")}) for r in EX.to_dicts()]
    recs += [dict(design="current", case=f"1-in-{r['return_period_years']}y need", **{k: r[k] for k in ("C_MM_M", "ci90_lo_M", "ci90_hi_M")}) for r in LV.to_dicts()]
    recs += [dict(design="current", case=f"{r['case']} x{r['scale']}", **{k: r[k] for k in ("C_MM_M", "C_ADL_M", "noCross_ADL_M")}) for r in WC.to_dicts()]
    recs += [dict(design="current", case=f"backtest K ${r['K_M']}M", predicted_days=r["predicted_days"], observed_days=r["observed_days"]) for r in BT.to_dicts()]
    registry.maybe_record(recs, kind="capital_risk", command=f"python sim/study/capital_risk.py {DAY}")
