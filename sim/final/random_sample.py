"""A random sample of market-days for the proposal's last check: days we did not choose.
Universe: every (market, day) with a 1-minute book file on the hydromancer tape (ec2/market_index.py), from 2026-07-01 to
2026-11-08, the market also listed the next day, and the day not one of the days already used in this study.
Draw (numpy RandomState, SEED): N_DAYS + RESERVE days uniformly without replacement, kept in draw order; on each day
PER_DAY markets uniformly without replacement. Days are the cluster because the chain's command stream is extracted a day at
a time. A day that cannot be built (a hole in the node archive) is replaced by the next reserve day, in order.
Usage: python sim/final/random_sample.py INDEX.csv  -> prints the DAYS spec for ec2/days_launch.sh, writes sim/final/random_sample.csv"""
import sys, json, csv, datetime as dt, numpy as np
SEED, N_DAYS, RESERVE, PER_DAY = 20261111, 6, 3, 5
USED = {"2026-07-27", "2026-09-10", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-05"}
U = json.load(open("data/xyzmeta.json"))[0]["universe"]; IDX = {u["name"][4:]: (110000 + i, u["maxLeverage"]) for i, u in enumerate(U)}
by = {}
for r in csv.DictReader(open(sys.argv[1])): by.setdefault(r["date"], set()).add(r["coin"])
nxt = lambda d: (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
days = sorted(d for d in by if "2026-07-01" <= d <= "2026-11-08" and d not in USED and nxt(d) in by)
rs = np.random.RandomState(SEED)
pick = [days[i] for i in rs.choice(len(days), N_DAYS + RESERVE, replace=False)]
rows, spec = [], []
for k, d in enumerate(pick):
    coins = sorted(c for c in by[d] if c in by[nxt(d)] and c in IDX)
    cs = [coins[i] for i in rs.choice(len(coins), PER_DAY, replace=False)]
    for c in cs: rows.append(dict(order=k + 1, role="sample" if k < N_DAYS else "reserve", date=d, coin=c, asset=IDX[c][0], max_lev=IDX[c][1], markets_that_day=len(coins)))
    spec.append(f"{d[5:7]}{d[8:]}@{nxt(d)[5:7]}{nxt(d)[8:]}@auto@auto@" + ",".join(f"{c}/{IDX[c][0]}/{IDX[c][1]}" for c in cs))
w = csv.DictWriter(open("sim/final/random_sample.csv", "w"), fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(f"universe: {len(days)} days, {sum(len(by[d]) for d in days)} market-days; seed {SEED}")
for k, s in enumerate(spec): print(("sample " if k < N_DAYS else "reserve"), s)
print("DAYS=" + " ".join(spec[:N_DAYS]))
print("RESERVE=" + " ".join(spec[N_DAYS:]))
