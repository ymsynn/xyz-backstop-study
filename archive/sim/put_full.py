"""Attack 1 (free put on the vault) with the attacker's full costs, on the GOOGL 10-28 event.

Version A, xyz only: X long NTL at 20x isolated (margin = IM) and Y short NTL, crossed against each other at 19:55
(one maker, one taker fee). When X is taken over, Y is bought back at once through the replayed book (a market buy
of Y's size at the takeover update: ATTACK_SIDE=buy). Attacker PnL = Y's gain to the buy-back - X's margin and
top-ups (X ends at 0) - fees.
Version B, hedged on the underlying: X bought on the xyz book at 19:55 (slippage from the depth dump), the hedge
shorted on the stock at trade.xyz's external price and covered at X's takeover, at HEDGE_BP each way.
Variant without a takeover of X (V3): the legs are unwound against each other: PnL = - fees.
Inputs: ORC_CSV (a control run's ORC_OUT, for ext) and DEPTH_CSV (a DEPTH_OUT dump); defaults point at the session's
scratch files.
"""
import os, re, subprocess, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attack_suite as A

TAKER, MAKER = 0.00011, 0.000015
ORC = os.environ.get("ORC_CSV") or "$SCRATCH/oi/orc_GOOGL.csv"
DEPTH = os.environ.get("DEPTH_CSV") or "$SCRATCH/oi/atk/depth.csv"
ext = pl.read_csv(ORC).select("ms", (pl.col("ext") / 1e6).alias("ext")).sort("ms")
blk = pl.read_ipc(f"{A.SRC}/blocks.arrow")
dep = pl.read_csv(DEPTH).filter(pl.col("side") == "ask")

def ext_at(ms): return float(ext.filter(pl.col("ms") <= ms)["ext"][-1])
def buy_slip(ntl, ms):
    """average slippage (fraction) to buy ntl on the xyz book, from the depth dump minute at or before ms"""
    m = int(dep.filter(pl.col("ms") <= ms)["ms"].max())
    c = dep.filter(pl.col("ms") == m).sort("dbps")
    prev_n, prev_d, cost = 0.0, 0.0, 0.0
    for d, n in zip(c["dbps"].to_list(), c["ntl"].to_list()):
        take = min(ntl - prev_n, n - prev_n)
        if take > 0: cost += take * (prev_d + d) / 2 / 1e4; prev_n += take
        prev_d = d
        if prev_n >= ntl: break
    if prev_n < ntl: cost += (ntl - prev_n) * prev_d / 1e4   # beyond the dump: at the deepest level (lower bound)
    return cost / ntl

rows = []
for size, ntl in (("2M", 2e6), ("10M", 1e7)):
    log = open(f"{A.RUNS}/prep_put_{A.T - 300_000}_{int(ntl)}_20.log").read()
    m = re.search(r"X (\d+) long ([\d.]+) @ ([\d.]+)", log); x, q, p0 = int(m.group(1)), float(m.group(2)), float(m.group(3))
    y = x + 1
    margin = q * p0 / 20
    for v in ("V0_control", "V1_ownmark", "V2_own_cluster", "V3_own_cluster_lev10"):
        tk = pl.read_csv(f"{A.RUNS}/tk_{v}_1_put_{size}.csv").filter(pl.col("u") == x).join(blk, on="h")
        fee_in = ntl * (TAKER + MAKER)
        if tk.height == 0:
            rows.append(dict(size=size, variant=v, x_taken=False, A_pnl=round(-2 * fee_in), B_pnl=round(-2 * fee_in), note="X never liquidated: legs unwound against each other"))
            continue
        t_tk = int(tk["ms"][0])
        name = f"1_put_{size}_exit"
        prep = ("put", [str(A.T - 300_000), str(int(ntl)), "20"])
        env = {"ATTACK_AT": str(t_tk + 1), "ATTACK_NTL": str(q * float(tk["mark"][0])), "ATTACK_SIDE": "buy", "ATTACK_REPEAT": "1", "PRINT_U": f"{x},{y}"}
        d, _ = A.prep_for(prep)
        ve, va = A.VARIANTS[v]
        tag = f"{v}_{name}"
        e = {**os.environ, **A.BASE_ENV, **ve, **env, "RELAYER_RESID_IN": f"{A.SRC}/relayer_resid_endo0_policy.txt",
             "SIM_TK_OUT": f"{A.RUNS}/tk_{tag}.csv", "ROUNDS_OUT": f"{A.RUNS}/rd_{tag}.csv", "ATTACK_OUT": f"{A.RUNS}/atk_{tag}.csv"}
        out = subprocess.run([f"{A.ROOT}/tools/memguard.sh", "6000", A.ENGINE, "sim", d, str(A.ML), *va], env=e, capture_output=True, text=True).stdout
        topped = float(re.search(rf"ACCOUNT {x}: topped \$([\d.]+)", out).group(1))
        a = pl.read_csv(f"{A.RUNS}/atk_{tag}.csv")
        exit_px = float(a["filled_ntl"].sum() / a["filled_sz"].sum())
        filled = float(a["filled_sz"].sum())
        y_gain = filled * (p0 - exit_px) + (q - filled) * (p0 - exit_px)   # any unfilled remainder valued at the same price (optimistic)
        fee_out = float(a["filled_ntl"].sum()) * TAKER
        A_pnl = y_gain - margin - topped - fee_in - fee_out
        # B: X bought on the book at 19:55, hedge on the stock at ext, HEDGE_BP each way
        e0, e1 = ext_at(A.T - 300_000), ext_at(t_tk)
        slip_in = buy_slip(ntl, A.T - 300_000)
        Bs = {hb: q * (e0 - e1) - margin - topped - ntl * (slip_in + TAKER) - 2 * ntl * hb / 1e4 for hb in (2, 10, 25)}
        rows.append(dict(size=size, variant=v, x_taken=True, takeover_s_after_1600=round((t_tk - A.T) / 1000, 1), x_margin=round(margin), x_topups=round(topped),
                         y_buyback_px=round(exit_px, 2), y_buyback_slip_bp=round((exit_px / float(a["mid0"][0]) - 1) * 1e4, 1), y_filled_frac=round(filled / q, 3),
                         A_pnl=round(A_pnl), xyz_entry_slip_bp=round(slip_in * 1e4, 1), ext_drop_pct=round((1 - e1 / e0) * 100, 2),
                         B_pnl_hedge2bp=round(Bs[2]), B_pnl_hedge10bp=round(Bs[10]), B_pnl_hedge25bp=round(Bs[25])))
        print(rows[-1], flush=True)
pl.DataFrame(rows, infer_schema_length=None).write_csv(f"{A.ROOT}/data/scen/attack_put_full.csv")
