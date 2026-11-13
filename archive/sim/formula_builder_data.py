"""Data for docs/formula_builder.html: every tested design as a combination of formula choices, and its results per
scenario from docs/registry.json, each next to the reference run of the same test (today where the test has it).
Usage: python sim/formula_builder_data.py   -> writes docs/formula_builder.html from docs/formula_builder.src.html"""
import json, os
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(f"{ROOT}/docs/registry.json"))
T = {t["id"]: pl.DataFrame(t["results"], infer_schema_length=None) for t in R["tests"] if t.get("results")}
DES = {d["id"]: d for d in R["designs"]}

DEFAULT = dict(c="c50", O="O_today", X1="X1_today", X2="X2_today", V="V_self30", R="R_E", H="H_na", Q="Q_int",
               L="L_today", BS="BS_23", MM="MM_12", LV="LV_today", U="U_05", DV="DV_none", ST="ST_150", FZ="FZ_na")
P4D = dict(O="O_E", X1="X1_O", X2="X2_P", R="R_p4d", H="H_always")
PKG = dict(P4D, L="L_rIM", U="U_fair")
ONLY = dict(O="O_E", X1="X1_O", R="R_p4d", L="L_rIM", U="U_fair", FZ="FZ_hold")      # today's prices outside a hold (package_z onward)
COMBO = {
    "current": {}, "p1": dict(O="O_E", X1="X1_O", X2="X2_free"), "clamp200": dict(c="c200"),
    "ext_ref": dict(O="O_E", X1="X1_O", X2="X2_E"), "band25": dict(X1="X1_band", X2="X2_band"),
    "venues": dict(O="O_E", X1="X1_O", X2="X2_bin"), "own_a": dict(X1="X1_imp", X2="X2_vwap"),
    "own_b": dict(X1="X1_impB", X2="X2_vwap"), "own_c": dict(X1="X1_impC", X2="X2_vwap"),
    "p2": dict(O="O_E", X1="X1_O", X2="X2_P"), "et_v1m": dict(O="O_E", X1="X1_O", X2="X2_P", V="V_1m60"),
    "et_vf1": dict(O="O_E", X1="X1_O", X2="X2_P", V="V_floor250"), "et_self60": dict(O="O_E", X1="X1_O", X2="X2_P", V="V_self60"),
    "p3": dict(O="O_E", X1="X1_O", X2="X2_P", R="R_med10"), "p3_n20": dict(O="O_E", X1="X1_O", X2="X2_P", R="R_med20"),
    "p4": dict(P4D, R="R_p4"), "p4b": dict(P4D, R="R_p4b"), "p4c": dict(P4D, R="R_p4c"), "p4d": dict(P4D),
    # margin and liquidation variants (measured with the P4 / P4d mark, or today's)
    "b075": dict(MM="MM_34"), "t1": dict(LV="LV_t1"), "o1lock": dict(LV="LV_o1lock"), "cluster": dict(LV="LV_cluster"),
    "band25_cluster": dict(X1="X1_band", X2="X2_band", LV="LV_cluster"),
    "p4_cut2": dict(P4D, R="R_p4", LV="LV_cut2"), "p4_cut2_w5": dict(P4D, R="R_p4", LV="LV_cut2w5"), "p4_cut4": dict(P4D, R="R_p4", LV="LV_cut4"),
    "p4_o1daily": dict(P4D, R="R_p4", LV="LV_o1daily"), "p4_cluster": dict(P4D, R="R_p4", LV="LV_cluster"),
    "p4_o1daily_cut2": dict(P4D, R="R_p4", LV="LV_o1daily_cut2"), "p4_t1": dict(P4D, R="R_p4", LV="LV_t1"),
    "p4_t3": dict(P4D, R="R_p4", LV="LV_t3"), "p4_t1_reduce": dict(P4D, R="R_p4", LV="LV_t1_reduce"),
    "p4_bs50": dict(P4D, R="R_p4", BS="BS_12"), "p4_bs33": dict(P4D, R="R_p4", BS="BS_13"), "p4_cd10": dict(P4D, R="R_p4", L="L_cd10"),
    "p4_bs50_cd10": dict(P4D, R="R_p4", BS="BS_12", L="L_cd10"),
    "p4d_b75": dict(P4D, MM="MM_34"), "p4d_b75k": dict(P4D, MM="MM_34k"), "p4d_dyn75k": dict(P4D, MM="MM_dyn"), "p4d_cd3": dict(P4D, L="L_cd3"),
    "p4d_pf1": dict(P4D, L="L_full"), "p4d_rs1": dict(P4D, L="L_rMMall"), "p4d_rs2": dict(P4D, L="L_rIMall"), "p4d_rb15": dict(P4D, L="L_r15"),
    "p4d_rb2": dict(P4D, L="L_rIM"), "p4d_rb3": dict(P4D, L="L_r3"), "p4d_rb2dyn": dict(P4D, L="L_rIMdyn"),
    # packages
    "package": dict(PKG), "package_cap": dict(PKG, R="R_p4d_cap"), "package_trig": dict(PKG, H="H_trig30"),
    "package_step": dict(PKG, H="H_step"), "package_ema": dict(PKG, X2="X2_Pema", H="H_trig30"), "package_x": dict(PKG, X2="X2_Pema_raw", H="H_step"),
    "package_z": dict(ONLY, X2="X2_today", H="H_z"), "package_y": dict(ONLY, X2="X2_anchO", H="H_y"), "package_w": dict(ONLY, X2="X2_anchE", H="H_w"),
    "package_v": dict(ONLY, X2="X2_anchE", H="H_v"), "package_k": dict(ONLY, X2="X2_anchE", H="H_k"),
    "package_b": dict(ONLY, X2="X2_anchE", H="H_k", Q="Q_holdDaily"),
    "package_m": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05"),
    "package_m_cap050": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", Q="Q_cap050"),
    "package_m_cap100": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", Q="Q_cap100"),
    "package_m_cap200": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", Q="Q_cap200"),
    "package_m_int": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", Q="Q_cap100", FZ="FZ_int"),
    "package_m_book": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", FZ="FZ_deep"),
    "package_m_div500": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", DV="DV_500"),
    "package_m_div250": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", DV="DV_250"),
    "package_m_div250_stale": dict(ONLY, X2="X2_anchE", H="H_k", U="U_05", DV="DV_250", ST="ST_stale"),
}
NAMES = {"current": "Today (deployed)", "p1": "P1: no clamp", "clamp200": "Clamp 200 bp", "ext_ref": "Mark = E (reference)",
         "band25": "External-anchored band", "venues": "Venues median", "own_a": "Own book A", "own_b": "Own book B", "own_c": "Own book C",
         "p2": "P2 (ET)", "et_v1m": "P2, $1M window", "et_vf1": "P2, $250k floor", "et_self60": "P2, 60 s window", "p3": "P3 (N = 10)",
         "p3_n20": "P3 (N = 20)", "p4": "P4", "p4b": "P4b", "p4c": "P4c", "p4d": "P4d", "b075": "MM buffer ¾", "t1": "Size tiers T1",
         "o1lock": "OI-share tiers (locked)", "cluster": "Cluster rule", "band25_cluster": "Band + cluster rule", "p4_cut2": "P4 + earnings cut ½",
         "p4_cut2_w5": "P4 + earnings cut ½ (5 min)", "p4_cut4": "P4 + earnings cut ¼", "p4_o1daily": "P4 + daily OI tiers",
         "p4_cluster": "P4 + cluster rule", "p4_o1daily_cut2": "P4 + daily OI tiers + cut ½", "p4_t1": "P4 + size tiers T1",
         "p4_t3": "P4 + size tiers T3", "p4_t1_reduce": "P4 + T1, traders reduce", "p4_bs50": "P4 + takeover at ½ MM",
         "p4_bs33": "P4 + takeover at ⅓ MM", "p4_cd10": "P4 + 10 s cooldown", "p4_bs50_cd10": "P4 + ½ MM + 10 s cooldown",
         "p4d_b75": "P4d + MM buffer ¾", "p4d_b75k": "P4d + MM ¾, takeover kept", "p4d_dyn75k": "P4d + MM ½→¾ with feed speed",
         "p4d_cd3": "P4d + 3 s cooldown", "p4d_pf1": "P4d + full liquidation", "p4d_rs1": "P4d + restore to MM (all sizes)",
         "p4d_rs2": "P4d + restore to IM (all sizes)", "p4d_rb15": "P4d + restore to 1.5 MM", "p4d_rb2": "P4d + restore to IM",
         "p4d_rb3": "P4d + restore to 3 MM", "p4d_rb2dyn": "P4d + restore to IM + speed buffer", "package": "Package (P4d + restore + fair sweep)",
         "package_cap": "Package + hold cap", "package_trig": "Package + 30 s hold-start rule", "package_step": "Package + one-update hold-start rule",
         "package_ema": "Package + trade price averaged", "package_x": "Package + averaged, raw in holds", "package_z": "Today's prices outside feed failures",
         "package_y": "… + book anchored to the oracle", "package_w": "… + book anchored to E", "package_v": "package_v", "package_k": "package_k",
         "package_b": "package_b (daily breaks hold E)", "package_m": "Core package", "package_m_cap050": "Core + closed-oracle cap 0.5%",
         "package_m_cap100": "Core + closed-oracle cap 1%", "package_m_cap200": "Core + closed-oracle cap 2%",
         "package_m_div500": "Core + divergence holds at 5%", "package_m_div250": "Core + divergence holds at 2.5%",
         "package_m_div250_stale": "Core + divergence holds + stale-only steps",
         "package_m_int": "Lead: core + a frozen E priced like a closed market (cap 1%)", "package_m_book": "Core + deeper book check in holds"}
STATUS = {k: DES.get(k, {}).get("status", "") for k in COMBO}
STATUS.update({"package_m_int": "lead", "package_m_book": "rejected", "package_m_cap050": "rejected", "package_m_cap200": "rejected", "package_m_cap100": "superseded", "package_m_div500": "rejected", "package_m_div250": "rejected", "package_m_div250_stale": "rejected", "package_m": "superseded", "package_m_cap050": "running", "package_m_cap100": "running", "package_m_cap200": "running",
               "package_ema": "rejected", "package_x": "rejected", "package_z": "superseded", "package_y": "superseded", "package_w": "superseded"})
for k in COMBO:
    if not STATUS[k]:
        STATUS[k] = "rejected" if k.startswith(("p4_", "p4d_b", "p4d_dyn", "p4d_cd", "p4d_pf", "p4d_rs", "p4d_rb1", "p4d_rb3", "p4d_rb2dyn")) else "tested"
STATUS["p4d_rb2"] = "in the core package"

res = {k: {} for k in COMBO}
def put(design, scen, val, ref, refname, unit, src, note=""):
    if design in res and val is not None:
        res[design][scen] = dict(v=val, ref=ref, refname=refname, unit=unit, src=src, note=note)

def num(x, r=2):
    return None if x is None else round(float(x), r)

# 1. three earnings crashes
d = T["score3-ext"].group_by("design").agg(pl.col("takeovers").sum(), pl.col("inherited_musd").sum(), pl.col("value_ext").sum(), pl.col("underwater_ext").sum())
cur = d.filter(pl.col("design") == "current").to_dicts()[0]
for x in d.to_dicts():
    put(x["design"], "crash_takeovers", x["takeovers"], cur["takeovers"], "today", "", "score3-ext")
    put(x["design"], "crash_inherited", num(x["inherited_musd"]), num(cur["inherited_musd"]), "today", "$M", "score3-ext")
    put(x["design"], "crash_value", round(x["value_ext"]), round(cur["value_ext"]), "today", "$", "score3-ext")
    put(x["design"], "crash_underwater", x["underwater_ext"], cur["underwater_ext"], "today", "", "score3-ext")
pk = {x["design"]: x for x in T["package"].to_dicts()}
for des, row in (("p4d", "p4d"), ("p4d_rb2", "restore_im"), ("package", "fair_sweep")):
    x, c0 = pk[row], pk["current"]
    put(des, "crash_inherited", num(x["inherited_musd"]), num(c0["inherited_musd"]), "today", "$M", "package")
    put(des, "crash_value", x["value_ext"], c0["value_ext"], "today", "$", "package")
    put(des, "crash_underwater", x["underwater_ext"], c0["underwater_ext"], "today", "", "package")
ben = {(b["claim"], b["metric"]): b for b in R["benefits"]["rows"]}
for des in ("package_v", "package_k", "package_m", "package_m_cap050", "package_m_cap100", "package_m_cap200", "package_b", "package_trig", "package_step", "package_cap"):
    note = "" if des in ("package_v", "package_k") else "no closed market or vault-unwind effect on these crash days: same as package_k"
    if des in ("package_trig", "package_step", "package_cap"): note = "these rules only act on feed failures: same as the package on the crashes"
    src = ben[("The vault inherits a little more notional", "notional inherited")] if des.startswith(("package_v", "package_k", "package_m", "package_b")) else None
    if src:
        put(des, "crash_inherited", num(src["package"]), num(src["today"]), "today", "$M", "benefits ledger", note)
        b2 = ben[("...but inherits it at a profit against fair value, not a loss", "value at takeover vs E")]
        put(des, "crash_value", round(b2["package"]), round(b2["today"]), "today", "$", "benefits ledger", note)
        b3 = ben[("Fewer takeovers are underwater", "takeovers worth less than E at takeover")]
        put(des, "crash_underwater", b3["package"], b3["today"], "today", "", "benefits ledger", note)
    else:
        x, c0 = pk["fair_sweep"], pk["current"]
        put(des, "crash_inherited", num(x["inherited_musd"]), num(c0["inherited_musd"]), "today", "$M", "package", note)
        put(des, "crash_value", x["value_ext"], c0["value_ext"], "today", "$", "package", note)
        put(des, "crash_underwater", x["underwater_ext"], c0["underwater_ext"], "today", "", "package", note)
# margin / liquidation tests: vs Binance, against their own base
for tid, base, bname in (("margin-p4", "p4", "P4"), ("margin-p4b", "p4", "P4")):
    d = T[tid].filter(pl.col("case") == "N=1").group_by("design").agg(pl.col("inherited_musd").sum(), pl.col("value_binance").sum(), pl.col("topups_musd").sum())
    b0 = d.filter(pl.col("design") == base).to_dicts()[0]
    for x in d.to_dicts():
        if x["design"] == base: continue
        put(x["design"], "crash_inherited", num(x["inherited_musd"]), num(b0["inherited_musd"]), bname, "$M", tid)
        put(x["design"], "crash_value_bin", round(x["value_binance"]), round(b0["value_binance"]), bname, "$", tid)
        put(x["design"], "topups", num(x["topups_musd"]), 0.0, bname, "$M", tid)
for tid in ("restore-im", "mm-buffer-p4d"):
    rows = T[tid].to_dicts(); b0 = [x for x in rows if x["design"] == "p4d"][0]
    for x in rows:
        if x["design"] == "p4d": continue
        put(x["design"], "crash_inherited", num(x["inherited_musd"]), num(b0["inherited_musd"]), "P4d", "$M", tid)
        put(x["design"], "crash_value_bin", round(x["value_binance"]), round(b0["value_binance"]), "P4d", "$", tid)
        put(x["design"], "crash_underwater", x["underwater_binance"], b0["underwater_binance"], "P4d", "", tid)
# 2-3. bad prints
for tid, scen, case in (("spike-5pct", "print5", "18:30 ET, 30 s"), ("spike-20pct", "print20", "18:30 ET, 5 min"),
                        ("bench-spike5", "print5", "18:30 ET, 30 s"), ("bench-spike20", "print20", "18:30 ET, 5 min")):
    d = T[tid].filter(pl.col("case") == case).group_by("design").agg(pl.col("extra_takeover_usd").sum(), pl.col("extra_stops").sum())
    c0 = d.filter(pl.col("design") == "current").to_dicts()
    if not c0: continue
    c0 = c0[0]
    for x in d.to_dicts():
        if scen in res.get(x["design"], {}): continue
        put(x["design"], scen, round(x["extra_takeover_usd"]), round(c0["extra_takeover_usd"]), "today", "$", tid)
        put(x["design"], scen + "_stops", x["extra_stops"], c0["extra_stops"], "today", "", tid)
for x in T["hold-limit"].to_dicts():
    if x["case"].endswith("(GOOGL)") and x["design"] in ("p4c", "p4d"):
        put(x["design"], "print20_googl", x["extra_takeover_usd"], 6980063, "today", "$", "hold-limit", "GOOGL only")
# 4. stuck feed
d = T["bench-freeze"].group_by("design").agg(pl.col("inherited_musd").sum(), pl.col("value_ext").sum())
c0 = d.filter(pl.col("design") == "current").to_dicts()[0]
for x in d.to_dicts():
    put(x["design"], "freeze_inherited", num(x["inherited_musd"]), num(c0["inherited_musd"]), "today", "$M", "bench-freeze")
    put(x["design"], "freeze_value", round(x["value_ext"]), round(c0["value_ext"]), "today", "$", "bench-freeze")
d = T["freeze-feed"].filter(pl.col("case") == "feed stuck 2 min").group_by("design").agg(pl.col("inherited_musd").sum(), pl.col("value_binance").sum())
c0 = d.filter(pl.col("design") == "current").to_dicts()[0]
for x in d.to_dicts():
    if "freeze_inherited" not in res.get(x["design"], {}):
        put(x["design"], "freeze_inherited", num(x["inherited_musd"]), num(c0["inherited_musd"]), "today", "$M", "freeze-feed")
# 5. book push at the crash
for x in T["push-crash"].filter(pl.col("case") == "5 × $500k from C+15 s").to_dicts():
    put(x["design"], "push_crash", x["mark_move_bp"], 0.0, "today", "bp", "push-crash")
# 6. wash trades: faithful where run, else the earlier non-faithful version
d = T["bench-wash-faith"].group_by("design").agg(pl.col("mark_up_max_bp").max())
c0 = d.filter(pl.col("design") == "current").to_dicts()[0]
for x in d.to_dicts():
    put(x["design"], "wash", x["mark_up_max_bp"], c0["mark_up_max_bp"], "today", "bp", "bench-wash-faith")
d = T["push-wash"].group_by("design").agg(pl.col("mark_up_max_bp").max())
for x in d.to_dicts():
    if "wash" not in res.get(x["design"], {}):
        put(x["design"], "wash", x["mark_up_max_bp"], 0.0, "today", "bp", "push-wash", "earlier attacker that could not be liquidated")
for x in T["bench-wash"].group_by("design").agg(pl.col("mark_up_max_bp").max()).to_dicts():
    if "wash" not in res.get(x["design"], {}):
        put(x["design"], "wash", x["mark_up_max_bp"], 0.0, "today", "bp", "bench-wash", "earlier attacker that could not be liquidated")
# 7. normal markets
for tid in ("bench-normal", "normal-markets"):
    d = T[tid].filter(pl.col("case") == "all").group_by("design").agg(pl.col("stops_only_new").sum(), pl.col("liq_only_new").sum(), pl.col("liq_only_today").sum())
    for x in d.to_dicts():
        if "normal_stops" in res.get(x["design"], {}): continue
        put(x["design"], "normal_stops", x["stops_only_new"], 0, "today", "", tid)
        put(x["design"], "normal_liq", x["liq_only_new"], 0, "today", "", tid)
# 8. out of sample
d = T["oos"]
mk4 = ["BRENTOIL", "CL", "GOLD", "SILVER"]
def oos(design, coins=None):
    x = d.filter(pl.col("design") == design)
    if coins: x = x.filter(pl.col("coin").is_in(coins))
    return x.select(pl.col("takeovers").sum(), pl.col("inherited_musd").sum(), pl.col("book_liq_accounts").sum(), pl.col("c_adl").sum()).to_dicts()[0], x.height
for des in d["design"].unique().to_list():
    _, n = oos(des)
    coins = None if n >= 7 else mk4
    x, _ = oos(des, coins); c0, _ = oos("current", coins)
    note = "" if coins is None else "4 CME markets only (CL, BRENTOIL, SILVER, GOLD)"
    put(des, "oos_takeovers", x["takeovers"], c0["takeovers"], "today", "", "oos", note)
    put(des, "oos_inherited", num(x["inherited_musd"], 3), num(c0["inherited_musd"], 3), "today", "$M", "oos", note)
    put(des, "oos_bookliq", x["book_liq_accounts"], c0["book_liq_accounts"], "today", "", "oos", note)
    put(des, "oos_cadl", round(x["c_adl"]), round(c0["c_adl"]), "today", "$", "oos", note)
# 9-11. closed-hours attacks: worst case over sizes and lengths
for tid, scen in (("closed_wick", "wick_googl"), ("closed_wick_cl", "wick_cl"), ("closed_wick_gold_weekend", "wick_gold")):
    dd = T[tid].group_by("design").agg(pl.col("harmed_accounts").max(), pl.col("mark_lift_bp").max())
    c0 = dd.filter(pl.col("design") == "current").to_dicts()[0]
    for x in dd.to_dicts():
        put(x["design"], scen, x["harmed_accounts"], c0["harmed_accounts"], "today", "", tid)
        put(x["design"], scen + "_bp", round(x["mark_lift_bp"]), round(c0["mark_lift_bp"]), "today", "bp", tid)
# 12. vault capital to avoid ADL (worst of the three crashes, replay)
vc = T["vault-capital"].filter(pl.col("case").str.contains("replay"))
c0 = vc.filter(pl.col("design") == "current")["c_adl_pct_oi"].max()
for des in vc["design"].unique().to_list():
    put(des, "cap_adl", vc.filter(pl.col("design") == des)["c_adl_pct_oi"].max(), c0, "today", "% of OI", "vault-capital")
# 13. SKHX hand-over (offline replay of the relayer)
for x in T["skhx-0727"].to_dicts():
    if "P before" in x["case"] or x["design"] == "current":
        put(x["design"], "skhx", x["liquidated_accounts"], 945, "today", "", "skhx-0727", "offline replay of the relayer")
# 15. walking external feed (down and up), healthy positions taken over, GOOGL + AMZN
for tid, sign in (("walking-feed", "-"), ("walking-feed-up", "+")):
    w = T[tid].group_by("design", "case").agg(pl.col("extra_takeover_usd").sum(), pl.col("mark_move_bp").min().alias("lo"), pl.col("mark_move_bp").max().alias("hi"))
    for secs in (15, 30, 60, 300):
        case = f"{sign}10% over {secs} s, held 2 min"; ww = w.filter(pl.col("case") == case)
        c0 = ww.filter(pl.col("design") == "current").to_dicts()
        if not c0: continue
        for x in ww.to_dicts():
            put(x["design"], f"walk{'up' if sign == '+' else 'down'}{secs}", round(x["extra_takeover_usd"]), round(c0[0]["extra_takeover_usd"]), "today", "$", tid)
# crashes for the divergence variants (sim/package_eval.py, 11-09, current engine): same runs as the core package
for des, (inh, val, uw) in {"package_m_div500": (10.92, 53929, 322), "package_m_div250": (10.99, 55090, 308), "package_m_div250_stale": (10.99, 55090, 308)}.items():
    put(des, "crash_inherited", inh, 9.85, "today", "$M", "package_eval 11-09"); put(des, "crash_value", val, -151986, "today", "$", "package_eval 11-09")
    put(des, "crash_underwater", uw, 812, "today", "", "package_eval 11-09")
# 16. faithful attacks on the divergence variants (divergence-attacks): worst case
da = T["divergence-attacks"]
for kind, scen in (("wash", "wash"), ("prop", "prop")):
    x = da.filter(pl.col("attack").str.starts_with(kind)).group_by("design").agg(pl.col("mark_lift_bp").max(), pl.col("harmed_accounts").max())
    c0 = x.filter(pl.col("design") == "current").to_dicts()[0]
    for row in x.to_dicts():
        des = {"div250_step_if_no_trade": "package_m_div250_stale", "div250_never_step": "package_m_div250"}.get(row["design"], row["design"])
        if des not in res: continue
        res[des].pop(scen, None)
        put(des, scen, row["mark_lift_bp"], c0["mark_lift_bp"], "today", "bp", "divergence-attacks", "faithful attackers, GOOGL crash")
        put(des, scen + "_hurt", row["harmed_accounts"], c0["harmed_accounts"], "today", "", "divergence-attacks", "faithful attackers, GOOGL crash")
# 17. stale E (10 min frozen at 18:30 ET) + faithful attacks: worst case
sa = T["stale-e-attacks"]
for kind in ("prop", "wash"):
    x = sa.filter(pl.col("attack").str.contains(kind)).group_by("design").agg(pl.col("mark_lift_bp").max(), pl.col("harmed_accounts").max())
    c0 = x.filter(pl.col("design") == "current").to_dicts()[0]
    for row in x.to_dicts():
        put(row["design"], f"stale_{kind}", row["harmed_accounts"], c0["harmed_accounts"], "today", "", "stale-e-attacks")
        put(row["design"], f"stale_{kind}_bp", row["mark_lift_bp"], c0["mark_lift_bp"], "today", "bp", "stale-e-attacks")
# 18. SKHX 07-27 in the engine: capital to avoid ADL
for row in T["skhx-0727-engine"].to_dicts():
    put(row["design"], "skhx_cadl", row["c_adl_usd"], 1426895, "today", "$", "skhx-0727-engine", "engine replay; the real vault held $1.01M")
# B on the crashes / natural days: same runs as the core package (frozen E and closures only)
for k in ("crash_inherited", "crash_value", "crash_underwater", "oos_takeovers", "oos_inherited", "oos_bookliq", "oos_cadl"):
    if k in res.get("package_m", {}) and k not in res["package_m_int"]:
        c = dict(res["package_m"][k]); c["note"] = "same runs as the core package (B changes only frozen E and closures)"; res["package_m_int"][k] = c
for k in ("wick_cl", "wick_cl_bp", "wick_gold", "wick_gold_bp", "skhx_cadl", "screen_push", "screen_reopen", "screen_skhx"):
    if k in res.get("package_m_cap100", {}) and k not in res["package_m_int"]:
        c = dict(res["package_m_cap100"][k]); c["note"] = "from core + 1% cap: B applies the same capped oracle in closures"; res["package_m_int"][k] = c
# 14. closed-oracle screen
scr = {x["design"]: x for x in T["closed-oracle-screen"].to_dicts()}
for des, key in (("package_m_cap050", "capped_internal_c50"), ("package_m_cap100", "capped_internal_c100"), ("package_m_cap200", "capped_internal_c200")):
    put(des, "screen_push", scr[key]["push_bound_15min_bp"], scr["current"]["push_bound_15min_bp"], "today", "bp", "closed-oracle-screen")
    put(des, "screen_reopen", scr[key]["reopen_gap_mean_bp"], scr["current"]["reopen_gap_mean_bp"], "today", "bp", "closed-oracle-screen")
    put(des, "screen_skhx", scr[key]["skhx_reopen_gap_bp"], scr["current"]["skhx_reopen_gap_bp"], "today", "bp", "closed-oracle-screen")

designs = [dict(id=k, name=NAMES.get(k, k), status=STATUS[k], combo={**DEFAULT, **v}, results=res[k]) for k, v in COMBO.items()]
data = dict(generated=R.get("updated"), designs=designs)
src = open(f"{ROOT}/docs/formula_builder.src.html").read()
open(f"{ROOT}/docs/formula_builder.html", "w").write(src.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False)))
print("designs", len(designs), "| with results", sum(1 for x in designs if x["results"]), "| cells", sum(len(x["results"]) for x in designs))
for x in designs:
    if not x["results"]: print("  no results:", x["id"])
