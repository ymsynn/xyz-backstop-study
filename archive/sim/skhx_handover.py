"""SKHX 07-27 hand-over: the real oracle path vs P4d carried across the hand-over (offline, on the tape).

Inputs: data/extract0727/tables/oracle.parquet (relayer setOracle: oracle, m1 = mark component, m2, ext = E),
data/xyzdata/all0727.parquet (fills), data/bs_fills.json (vault). Window 22:50-23:15 UTC.
P4d at each relayer update (d = 1/maxLev = 10%, step every 150 s):
  hold  = |E - P| > d E  (P = voluntary-trade median, P2/P4's rule); the book condition is checked on the last trades
          before the cascade (the 1-min book is too coarse); R carries over from the last internal oracle
  R     = R + clip(E - R, +-d R) every 150 s while held, else E
  mark  = clip(median(D(E), D(P), D(P)), M_prev (1 +- 1%))   (the book vote = P: no book replay here; conservative
          only in the sense that it is the trades' price, see the two P variants)
Two P variants: 'tape' = P from the real voluntary fills (they include fills in the crushed book, after the cascade
the real mark caused); 'pre' = P frozen at its last value before the first liquidation (no cascade).
A liquidated account would still be liquidated under P4d if P4d's mark falls to the mark at which it was first
liquidated in reality (the real mark fell 1% per update, so that is its threshold to within 1%).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C, D, STEP = "xyz:SKHX", 0.10, 150_000
TRIG = os.environ.get("TRIG") in ("1", "2", "4", "5")   # the hold-start rule (2: the jump is between two consecutive updates)
TRIG_STEP = os.environ.get("TRIG") in ("2", "4", "5")
# TRIG=4: the lead design (package_v): outside a hold the mark follows E with xyz allowed within the clamp c; after a feed
# failure (single-update jump > d, or 2 unchanged updates) a hold needs only a disagreement > c, and continues above it
# TRIG=5: package_k = package_v + venue closures. Here the frozen rule already ignores the scheduled internal session
# (stuck only while oracle = E), which is the closure of SKHX's venue, so package_k follows the same path by construction
V = os.environ.get("TRIG") in ("4", "5"); CC = 0.005
T0, T1 = 1785192600000, 1785194100000          # 22:50 - 23:15 UTC
o = (pl.read_parquet(f"{ROOT}/data/extract0727/tables/oracle.parquet").filter(pl.col("coin") == C)
     .select("oracle", "m1", "m2", ms=pl.col("t").dt.epoch("ms"), E="ext").filter(pl.col("ms").is_between(T0, T1)).sort("ms"))
f = (pl.scan_parquet(f"{ROOT}/data/xyzdata/all0727.parquet").filter(pl.col("coin") == C, pl.col("crossed"))
     .select(ms=pl.col("timestamp").dt.epoch("ms"), px=pl.col("price").cast(pl.Float64), sz=pl.col("size").cast(pl.Float64),
             liq=pl.col("is_liquidation").fill_null(False), mark=pl.col("liquidation_mark_px").cast(pl.Float64), user=pl.col("address"))
     .filter(pl.col("ms").is_between(T0 - 3_600_000, T1)).sort("ms").collect())
vol = f.filter(~pl.col("liq"))
tm, px, nt = vol["ms"].to_numpy(), vol["px"].to_numpy(), (vol["px"] * vol["sz"]).to_numpy()
cum = np.concatenate([[0.0], np.cumsum(nt)]); avg30 = nt.sum() * 30_000 / (tm[-1] - tm[0])
def P_at(t):
    k = np.searchsorted(tm, t, side="right")
    V = max(cum[k] - cum[np.searchsorted(tm, t - 30_000)], avg30)
    s = max(np.searchsorted(cum, cum[k] - V, side="right") - 1, 0)
    w, p = nt[s:k], px[s:k]; q = np.argsort(p); cw = np.cumsum(w[q])
    return p[q][np.searchsorted(cw, cw[-1] / 2)]
first_liq = f.filter("liq")["ms"].min()
P_pre = P_at(first_liq - 1)
om, E, orc, m1 = o["ms"].to_numpy(), o["E"].to_numpy(), o["oracle"].to_numpy(), o["m1"].to_numpy()
out = {}
for var in ("tape", "pre"):
    R = None; held_since = None; M = None; path = []; win = []; last_e = None; chg = None; holding = False; unch = 0; fail = False
    for t, e, oc in zip(om, E, orc):
        P = P_at(t) if (var == "tape" or t < first_liq) else P_pre
        if R is None:
            R = oc; M = oc
        want = abs(e - P) > D * e
        if TRIG:   # start rule (OWN_HOLD_TRIG): a hold starts only on a jump of E > d within 30 s or a feed unchanged for 30 s
            win = [(a, b) for a, b in win if a >= t - 30_000] + [(t, e)]
            last_e_prev = last_e
            if last_e is not None and e != last_e: chg = t
            last_e = e
            jumped = (last_e_prev is not None and abs(e - last_e_prev) > D * e) if TRIG_STEP else (max(b for _, b in win) - min(b for _, b in win) > D * e)
            frozen = chg is not None and t - chg >= 30_000
            if V:
                unch = unch + 1 if (last_e_prev is not None and e == last_e_prev) else 0
                frozen = unch >= 2 and abs(oc / e - 1) < 5e-5   # stuck only in an external session (oracle = E); the internal
                                                                # session freezes E on purpose and is priced by trade.xyz's internal oracle
                dis = abs(e - P) > CC * e
                if not holding:
                    fail = False
                    want = (want or dis) and (jumped or frozen)
                    if want: fail = True
                else:
                    want = want or (dis and (fail or frozen))
            elif want and not holding and not (jumped or frozen): want = False
            holding = want
        if want:
            if held_since is None: held_since = t
            if t - held_since >= STEP:
                R = R + np.clip(e - R, -D * R, D * R); held_since = t
        else:
            R = e; held_since = None
        lo, hi = R * (1 - D), R * (1 + D)
        x = np.median([np.clip(e, lo, hi), np.clip(P, lo, hi), np.clip(P, lo, hi)])
        if V and not want: x = float(np.clip(P, e * (1 - CC), e * (1 + CC)))   # outside a hold: E, with xyz within c
        M = float(np.clip(x, M * 0.99, M * 1.01))
        path.append((t, e, oc, P, R, M, want))
    out[var] = pl.DataFrame(path, schema=["ms", "E", "oracle", "P", "R", "mark_p4d", "held"], orient="row")
# real mark: the takeover / liquidation marks on the tape, per update
real = f.filter("liq").group_by("ms").agg(pl.col("mark").first()).sort("ms")
pl.Config.set_tbl_rows(70); pl.Config.set_tbl_width_chars(220)
w = out["tape"].join(out["pre"].select("ms", pl.col("mark_p4d").alias("mark_p4d_pre"), pl.col("held").alias("held_pre"), pl.col("R").alias("R_pre")), on="ms")
w = w.join_asof(real.rename({"mark": "real_liq_mark"}), on="ms", strategy="backward", tolerance=3000)
print(w.with_columns(utc=pl.from_epoch("ms", "ms").dt.strftime("%H:%M:%S")).filter(pl.col("ms").is_between(1785193180000, 1785193420000)).select("utc", "E", "oracle", "P", "R", "mark_p4d", "held", "mark_p4d_pre", "R_pre", "real_liq_mark"))
# accounts liquidated in reality, and under P4d. Only positions held before the hand-over count (shorts opened in
# the crash and liquidated on the rebound would not exist without it): the start position of the account's first fill
# after the hand-over.
H0 = int(om[np.searchsorted(E, E[0]) if False else np.argmax(np.abs(np.diff(E)) > 0) + 1])   # first E move = hand-over
pre_mark = float(m1[np.searchsorted(om, H0) - 1])
allf = (pl.scan_parquet(f"{ROOT}/data/xyzdata/all0727.parquet").filter(pl.col("coin") == C, pl.col("timestamp").dt.epoch("ms") >= H0)
        .select(user=pl.col("address"), ms=pl.col("timestamp").dt.epoch("ms"), q0=pl.col("start_position").cast(pl.Float64)).sort("ms").collect()
        .group_by("user").agg(pl.col("q0").first()))
lq = f.filter("liq", pl.col("ms").is_between(H0, T1)).group_by("user").agg(pl.col("ms").min(), pl.col("mark").first(), (pl.col("px") * pl.col("sz")).sum().alias("ntl")).join(allf, on="user", how="left")
held = lq.filter(((pl.col("mark") < pre_mark) & (pl.col("q0") > 0)) | ((pl.col("mark") >= pre_mark) & (pl.col("q0") < 0)))
print(f"hand-over at {H0} | pre-hand-over mark {pre_mark:.1f} | liquidated accounts {lq.height} (${lq['ntl'].sum()/1e6:.1f}M), "
      f"of which held before the hand-over {held.height} (${held['ntl'].sum()/1e6:.1f}M); longs {held.filter(pl.col('q0')>0).height}, shorts {held.filter(pl.col('q0')<0).height}")
rows = []
DES = {"": "p4d", "1": "package_trig", "2": "package_step", "4": "package_v", "5": "package_k"}[os.environ.get("TRIG", "")]
for var in ("tape", "pre"):
    lo = out[var]["mark_p4d"].min(); hi = out[var]["mark_p4d"].max()
    still = held.filter(((pl.col("q0") > 0) & (pl.col("mark") >= lo)) | ((pl.col("q0") < 0) & (pl.col("mark") <= hi)))
    print(f"P4d ({var}): mark range {lo:.1f}..{hi:.1f}; still liquidated {still.height} (${still['ntl'].sum()/1e6:.2f}M)")
    rows.append(dict(design=DES, case=("P4d across the hand-over, P before the cascade" if var == "pre" else "bound: P fed by the crushed book"),
                     liquidated_accounts=still.height, liquidated_musd=round(still["ntl"].sum() / 1e6, 2)))
registry.maybe_record(rows, kind="mark", command=f"TRIG={os.environ.get('TRIG', '')} python sim/skhx_handover.py")
w.write_csv(f"{ROOT}/data/scen/skhx_handover{'_trig' if TRIG else ''}.csv")
