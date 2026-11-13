"""Clamp / MM-buffer scenario grid on the validated engine.

Usage: python scen_grid.py OUT_CSV [--set grid1|clamp_x_b|tiers|tiers_intc|tiers_amzn|tiers_oi] [COIN ...]
grid1: the base, four clamps at b 0.5, three buffers at 50 bp. clamp_x_b: the clamp x buffer combinations grid1 lacks
(clamps 25 / 100 / 200 / 500 bp x b 0.6 / 0.75).
Each scenario runs `engine sim` per coin in ENDO=0 (users' real orders replayed, liquidations / triggers / vault
simulated) with the simulated relayer + its recorded residual (relayer_resid_endo0_policy.txt: recorded in this same configuration at
real parameters, so the baseline is exact; in scenarios the relayer's view error is kept as it was) and the vault's
policy unwind (VAULT_FRAC of inventory per relayer update: the real unwind cannot be replayed once inventory differs).
One run at a time (memory). Results: vault PnL, inherited notional, takeovers, market-liquidated size.
"""
import os, re, subprocess, sys
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = f"{ROOT}/engine/target/release/engine"
COINS = {"GOOGL": ("prep_GOOGL_1028", 20), "INTC": ("prep_INTC_1029", 10), "AMZN": ("prep_AMZN_1029", 20)}
# split-whale preps (split_prep.py): data/prep_GOOGL_1028_split{N} -> coin "GOOGL_s{N}"
for _n in (2, 5, 10):
    if os.path.isdir(f"{ROOT}/data/prep_GOOGL_1028_split{_n}"):
        COINS[f"GOOGL_s{_n}"] = (f"prep_GOOGL_1028_split{_n}", 20)
BASE_ENV = dict(MATCH="engine", TRIGGERS="simulate", SILENT="1", MARGIN="1", ENDO="0", MARK_SOURCE="simulate")
# (name, extra env, extra engine rule args)
SCENARIOS = [
    ("base", {}, []),
    ("clamp_25", {"CLAMP_BPS": "25"}, []),
    ("clamp_100", {"CLAMP_BPS": "100"}, []),
    ("clamp_200", {"CLAMP_BPS": "200"}, []),
    ("clamp_500", {"CLAMP_BPS": "500"}, []),
    ("b_0.6", {}, ["mm_buffer=0.6"]),
    ("b_0.75", {}, ["mm_buffer=0.75"]),
    ("b_1.0", {}, ["mm_buffer=1.0"]),
]
CLAMP_X_B = [(f"clamp_{c}_b_{b}", {"CLAMP_BPS": str(c)}, [f"mm_buffer={b}"]) for b in ("0.6", "0.75") for c in (25, 100, 200, 500)]
# deployer-controlled margin tables (GOOGL, 20x): T1 20x to $1M then 10x; T2 + 5x above $5M; T3 20x to $500k, 10x to
# $2M, then 5x; with no trader response or traders topping up the extra initial margin; at the 50 bp and 200 bp clamps
TIERS = {"T1": "0:20,1000000:10", "T2": "0:20,1000000:10,5000000:5", "T3": "0:20,500000:10,2000000:5"}
TIERS_X = [(f"{t}_{resp}_clamp_{c}", {"CLAMP_BPS": str(c)}, [f"tiers={v}"] + (["tier_topup=1"] if resp == "topup" else []))
           for t, v in TIERS.items() for resp in ("none", "topup") for c in (50, 200)]
# INTC (10x): I1 5x above $1M, I2 5x above $500k, I3 5x above $250k and 3x above $1M; at 50 and 200 bp
TIERS_INTC = {"I1": "0:10,1000000:5", "I2": "0:10,500000:5", "I3": "0:10,250000:5,1000000:3"}
TIERS_INTC_X = [(f"{t}_{resp}_clamp_{c}", {"CLAMP_BPS": str(c)}, [f"tiers={v}"] + (["tier_topup=1"] if resp == "topup" else []))
                for t, v in TIERS_INTC.items() for resp in ("none", "topup") for c in (50, 200)]
# AMZN (20x): GOOGL's tables plus T4 10x above $100k, 5x above $500k (its losses are spread over small accounts); 50 bp
TIERS_AMZN = {**TIERS, "T4": "0:20,100000:10,500000:5"}
TIERS_AMZN_X = [(f"{t}_{resp}_clamp_50", {}, [f"tiers={v}"] + (["tier_topup=1"] if resp == "topup" else []))
                for t, v in TIERS_AMZN.items() for resp in ("none", "topup")]
# OI-share tables (oi_tiers, Hyperliquid change): bounds are shares of OI; {L} = the coin's max leverage, {L2} / {L4}
# its half / quarter (rounded up to whole leverage). O1: 1/2 lev above 5% of OI, 1/4 above 15%; O2: above 2% / 8%.
# Modes: live (reference only: attackable), lock (24 h average OI, fixed per account at each increase), daily.
TIERS_OI = {"O1": "0:{L},0.05:{L2},0.15:{L4}", "O2": "0:{L},0.02:{L2},0.08:{L4}"}
TIERS_OI_X = [(f"{t}_{m}_{resp}", {}, [f"tiers={v}", f"oi_tiers={m}"] + (["tier_topup=1"] if resp == "topup" else []))
              for t, v in TIERS_OI.items() for m in ("lock", "daily", "live") for resp in ("none", "topup")
              if not (m == "live" and resp == "none")]
# reduce response (tier_reduce=1): traders shed the size their margin no longer carries instead of topping up
TIERS_RED_OI = [(f"{t}_{m}_reduce", {}, [f"tiers={TIERS_OI[t]}", f"oi_tiers={m}", "tier_reduce=1"]) for t in ("O1", "O2") for m in ("lock", "daily")]
TIERS_RED_GOOGL = [(f"{t}_reduce_clamp_50", {}, [f"tiers={TIERS[t]}", "tier_reduce=1"]) for t in ("T1", "T3")]
TIERS_RED_INTC = [(f"{t}_reduce_clamp_50", {}, [f"tiers={TIERS_INTC[t]}", "tier_reduce=1"]) for t in ("I1", "I3")]
# split-whale grid: today, the dollar table T1, the OI table O1 locked, and the cluster rule (2% band) on T1 / O1,
# all with top-ups; run on GOOGL and GOOGL_s{2,5,10}
SPLIT_X = [("base", {}, []),
           ("T1_topup", {}, [f"tiers={TIERS['T1']}", "tier_topup=1"]),
           ("O1_lock_topup", {}, [f"tiers={TIERS_OI['O1']}", "oi_tiers=lock", "tier_topup=1"]),
           ("T1_cluster_topup", {}, [f"tiers={TIERS['T1']}", "cluster=0.02", "tier_topup=1"]),
           ("O1_lock_cluster_topup", {}, [f"tiers={TIERS_OI['O1']}", "oi_tiers=lock", "cluster=0.02", "tier_topup=1"])]
# mark redesign (MARK=band, deployer-controlled): mark = book clamped to C +- w, C = ext + capped slow premium; half-width
# 10 / 25 / 50 bp with today's margin; 25 bp and today's formula with the cluster rule (O1 locked, top-up)
CLUSTER_O1 = [f"tiers={TIERS_OI['O1']}", "oi_tiers=lock", "cluster=0.02", "tier_topup=1"]
MARK_BAND = [("base", {}, [])] + [(f"band_{w}", {"MARK": "band", "BAND_W": str(w)}, []) for w in (10, 25, 50)] + [
    ("band_25_cluster", {"MARK": "band", "BAND_W": "25"}, CLUSTER_O1), ("today_cluster", {}, CLUSTER_O1)]
# mark = median(ext, Binance's stock perp, local book) (markPxs = [ext, venue]); MARK=ext: the mark is ext
VEN = {"MARK": "venues", "VENUE_PX": "{ROOT}/data/binance/{C}USDT_100ms.arrow"}
MARK_VENUES = [("venues", VEN, []), ("venues_cluster", VEN, CLUSTER_O1), ("ext", {"MARK": "ext"}, [])]
# own-book marks out of market hours (from 16:00 ET = 20:00 UTC on 10-28; today's relayer before): A median(impact mid
# $100k time-averaged, 10 s VWAP, book); B A with at most $1M of liquidation prices crossed per update; C A, instant
# impact mid when the external price confirms the move
OWN_FROM = {"GOOGL": "1793217600000", "INTC": "1793304000000", "AMZN": "1793304000000"}
MARK_OWN = [(f"own_{m}", {"MARK": f"own_{m}", "OWN_FROM_MS": "{FROM}"}, []) for m in ("a", "b", "c")]
# trade-based mark: markPxs = [ext, volume-weighted median of the last OWN_V of voluntary trades] (A again for INTC/AMZN)
MARK_ET = [("own_a", {"MARK": "own_a", "OWN_FROM_MS": "{FROM}"}, []),
           ("own_et", {"MARK": "own_et", "OWN_FROM_MS": "{FROM}", "OWN_V": "1000000"}, []),
           ("own_et_v250k", {"MARK": "own_et", "OWN_FROM_MS": "{FROM}", "OWN_V": "250000"}, [])]
# ET with V scaled to activity: V = max($250k, f x voluntary notional of the last 60 s)
MARK_ETS = [(f"own_et_vf{f}", {"MARK": "own_et", "OWN_FROM_MS": "{FROM}", "OWN_VF": f, "OWN_VMIN": "250000"}, []) for f in ("0.25", "0.5", "1.0")]
# ET self-calibrated (no dollar or age constant): horizon H = 30 s (HL's partial-liquidation cooldown) or 60 s
MARK_ETSC = [(f"own_et_self{h}", {"MARK": "own_et", "OWN_FROM_MS": "{FROM}", "OWN_SELF": "1", "OWN_H_S": h}, []) for h in ("30", "60")]
MARK_P3 = [(f"p3_n{n}", {"MARK": "own_et", "OWN_FROM_MS": "{FROM}", "OWN_SELF": "1", "OWN_H_S": "30", "OWN_ANCHOR_N": n}, []) for n in ("10", "20")]
MARK_P4 = [("p4", {"MARK": "own_et", "OWN_FROM_MS": "{FROM}", "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "1"}, [])]
P4E = MARK_P4[0][1]
CUT = lambda lev, a: [f"lev_cut={lev}", f"cut_win={a}:{{CB}}", "tier_topup=1"]
O1D = [f"tiers={TIERS_OI['O1']}", "oi_tiers=daily", "tier_topup=1"]
MARGIN_P4 = [("p4_o1daily", P4E, O1D), ("p4_cluster", P4E, CLUSTER_O1),
             ("p4_cut2_w30", P4E, CUT("{L2}", "{CA30}")), ("p4_cut4_w30", P4E, CUT("{L4}", "{CA30}")), ("p4_cut2_w5", P4E, CUT("{L2}", "{CA5}")),
             ("p4_o1daily_cut2_w30", P4E, O1D[:2] + CUT("{L2}", "{CA30}")), ("p4", P4E, [])]
MARGIN_P4B = [("p4_T1_topup", P4E, ["tiers={T1}", "tier_topup=1"]), ("p4_T3_topup", P4E, ["tiers={T3}", "tier_topup=1"]),
              ("p4_T1_reduce", P4E, ["tiers={T1}", "tier_reduce=1"]),
              ("p4_bs50", P4E, ["backstop_frac=0.5"]), ("p4_bs33", P4E, ["backstop_frac=0.3333"]),
              ("p4_cd10", P4E, ["cooldown_ms=10000"]), ("p4_bs50_cd10", P4E, ["backstop_frac=0.5", "cooldown_ms=10000"])]
SETS = {"margin_p4b": MARGIN_P4B, "margin_p4": MARGIN_P4, "mark_p4": MARK_P4, "mark_p3": MARK_P3, "mark_etsc": MARK_ETSC, "mark_ets": MARK_ETS, "mark_et": MARK_ET, "mark_own": MARK_OWN, "mark_venues": MARK_VENUES, "mark_band": MARK_BAND, "split": SPLIT_X, "tiers_red_oi": TIERS_RED_OI, "tiers_red_googl": TIERS_RED_GOOGL, "tiers_red_intc": TIERS_RED_INTC, "tiers_oi": TIERS_OI_X, "grid1": SCENARIOS, "clamp_x_b": CLAMP_X_B, "tiers": TIERS_X, "tiers_intc": TIERS_INTC_X, "tiers_amzn": TIERS_AMZN_X}


def run(coin, name, env_x, args_x, tmp):
    prep, ml = COINS[coin]
    d = f"{ROOT}/data/{prep}"
    tk, rd = f"{tmp}/tk_{coin}_{name}.csv", f"{tmp}/rounds_{coin}_{name}.csv"
    env_x = {k: v.format(C=coin.split("_")[0], ROOT=ROOT, FROM=OWN_FROM.get(coin.split("_")[0], "0")) if "{" in v else v for k, v in env_x.items()}
    env = {**os.environ, **BASE_ENV, **env_x, "RELAYER_RESID_IN": f"{d}/relayer_resid_endo0_policy.txt", "SIM_TK_OUT": tk, "ROUNDS_OUT": rd}
    fr = int(OWN_FROM.get(coin.split("_")[0], "0"))
    lv = {"L": ml, "L2": -(-ml // 2), "L4": -(-ml // 4), "CA30": fr - 1_800_000, "CA5": fr - 300_000, "CB": fr + 3_600_000,
          "T1": TIERS["T1"] if ml == 20 else TIERS_INTC["I1"], "T3": TIERS["T3"] if ml == 20 else TIERS_INTC["I3"]}
    args_x = [a.format(**lv) if "{" in a else a for a in args_x]
    cmd = [f"{ROOT}/tools/memguard.sh", "6000", ENGINE, "sim", d, str(ml), *args_x]
    out = subprocess.run(cmd, env=env, capture_output=True, text=True).stdout
    for l in out.splitlines():
        if l.startswith("OWN MARK"): print("  ", coin, name, l, flush=True)
    pnl = re.search(r"=> PnL \$(-?[\d.]+)", out)
    inh = re.search(r"inherited \$([\d.]+)M", out)
    top = re.search(r"trader top-ups \$([\d.]+)", out)
    shed = re.search(r"size shed \(peak\) \$([\d.]+)", out)
    bd = re.search(r"LIQUIDATION BAD DEBT: \$([\d.]+)", out)
    t = pl.read_csv(tk) if os.path.exists(tk) else pl.DataFrame({"q": [], "px": []})
    r = pl.read_csv(rd) if os.path.exists(rd) else pl.DataFrame({"sim_filled": []})
    return dict(coin=coin, scenario=name, vault_pnl=float(pnl.group(1)) if pnl else None,
                inherited_musd=float(inh.group(1)) if inh else None, takeovers=t.height,
                takeover_ntl_musd=round(float((t["q"].abs() * t["px"]).sum()) / 1e6, 3) if t.height else 0.0,
                market_liq_shares=round(float(r["sim_filled"].sum()), 1) if r.height else 0.0,
                topups_usd=float(top.group(1)) if top else 0.0, shed_peak_usd=float(shed.group(1)) if shed else 0.0,
                bad_debt_usd=float(bd.group(1)) if bd else None)


if __name__ == "__main__":
    out_csv, rest = sys.argv[1], sys.argv[2:]
    scen = SCENARIOS
    if rest[:1] == ["--set"]:
        scen, rest = SETS[rest[1]], rest[2:]
    coins = rest or list(COINS)
    tmp = os.path.join(os.path.dirname(os.path.abspath(out_csv)), "runs")
    os.makedirs(tmp, exist_ok=True)
    rows = []
    for name, env_x, args_x in scen:
        for c in coins:
            rows.append(run(c, name, env_x, args_x, tmp))
            print(rows[-1], flush=True)
            pl.DataFrame(rows).write_csv(out_csv)
