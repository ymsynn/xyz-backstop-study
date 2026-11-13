"""Attack suite on the GOOGL 10-28 event: protocol variants (control = today's deployed rules) x attacks, each run
the event replay (ENDO=0, simulated relayer + residual, policy unwind) with the attack added; compared with the
same variant without attack. Results appended to data/scen/attack_suite.csv (done runs are skipped on rerun).

Usage: python attack_suite.py [ONLY_ATTACK ...]
"""
import os, re, subprocess, sys
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE, PY = f"{ROOT}/engine/target/release/engine", sys.executable
SRC, ML = f"{ROOT}/data/prep_GOOGL_1028", 20
T = 1793217600000                       # 16:00 ET = 20:00 UTC, out-of-hours rules from here
OUT = os.environ.get("SUITE_OUT", f"{ROOT}/data/scen/attack_suite.csv")
RUNS = f"{ROOT}/data/scen/attack_runs"
os.makedirs(RUNS, exist_ok=True)
FAIR = f"{ROOT}/data/binance/GOOGLUSDT_100ms.parquet"   # yardstick only (never a mark input)
EXT = (pl.read_parquet(f"{ROOT}/data/extract1028/tables/oracle.parquet").filter(pl.col("coin") == "xyz:GOOGL", pl.col("ext").is_not_null())
       .select(ms=pl.col("t").dt.epoch("ms"), E="ext").sort("ms"))
BASE_ENV = dict(MATCH="engine", TRIGGERS="simulate", SILENT="1", MARGIN="1", ENDO="0", MARK_SOURCE="simulate",
                TRIG_WIN=f"{T},{T + 180_000}")
OWN = {"MARK": "own_a", "OWN_FROM_MS": str(T)}
CL = ["tiers=0:20,0.05:10,0.15:5", "oi_tiers=lock", "cluster=0.02", "tier_topup=1"]
VARIANTS = {"V0_control": ({}, []), "V1_ownmark": (OWN, []), "V2_own_cluster": (OWN, CL),
            "V3_own_cluster_lev10": (OWN, ["tiers=0:10,0.05:5,0.15:3", "oi_tiers=lock", "cluster=0.02", "tier_topup=1"]),
            # the proposed package: P4d mark + restore-to-IM liquidation + fair-sweep vault unwind
            "V4_package": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                            "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1"}, ["liq_restore=2", "restore_big=1"]),
            # the package with the hold cap (OWN_HOLD_CAP=1)
            "V5_package_cap": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                                "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_CAP": "1"}, ["liq_restore=2", "restore_big=1"]),
            # the package with the hold-start condition (OWN_HOLD_TRIG=1)
            "V6_package_trig": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                                "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "1"}, ["liq_restore=2", "restore_big=1"]),
            # the package with the hold-start rule on a single-update jump (OWN_HOLD_TRIG=2): the lead
            "V7_package_step": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                                "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "2"}, ["liq_restore=2", "restore_big=1"]),
            # the package with the start rule and P through the 150 s EMA (OWN_P_EMA_S=150)
            "V8_package_ema": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                                "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "1", "OWN_P_EMA_S": "150"}, ["liq_restore=2", "restore_big=1"]),
            # today's relayer with the oracle unclamped; P4d's inputs only while a hold (single-update start rule) is active
            "V9_package_z": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                              "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "2", "OWN_ONLY_HOLD": "1", "CLAMP_O_BPS": "100000"}, ["liq_restore=2", "restore_big=1"]),
            # V9 refined: book input clamped against the oracle only (no creep), stuck feed after two unchanged updates
            "V10_package_y": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                               "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "2", "OWN_ONLY_HOLD": "1", "CLAMP_O_BPS": "100000",
                               "M2_REF": "oracle", "OWN_FROZEN_UPD": "2"}, ["liq_restore=2", "restore_big=1"]),
            # book input clamped around the current E; stuck-feed hold once xyz is 50 bp away
            "V11_package_w": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                               "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "2", "OWN_ONLY_HOLD": "1", "CLAMP_O_BPS": "100000",
                               "M2_REF": "ext", "OWN_FROZEN_UPD": "2", "OWN_FROZEN_GAP": "0.005"}, ["liq_restore=2", "restore_big=1"]),
            # + a jump-started hold needs only the clamp disagreement, and failure holds continue above it
            "V12_package_v": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                               "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "2", "OWN_ONLY_HOLD": "1", "CLAMP_O_BPS": "100000",
                               "M2_REF": "ext", "OWN_FROZEN_UPD": "2", "OWN_FROZEN_GAP": "0.005", "OWN_JUMP_GAP": "0.005"}, ["liq_restore=2", "restore_big=1"]),
            # package_v + the venue's scheduled closures: no frozen-feed hold while the venue is shut (OWN_CLOSED)
            "V13_package_k": ({"MARK": "own_et", "OWN_FROM_MS": str(T), "OWN_SELF": "1", "OWN_H_S": "30", "OWN_GATE": "2", "OWN_N": "6000",
                               "OWN_HOLD_S": "150", "OWN_HOLD_STEP": "1", "VAULT_FAIR": "1", "OWN_HOLD_TRIG": "2", "OWN_ONLY_HOLD": "1", "CLAMP_O_BPS": "100000",
                               "M2_REF": "ext", "OWN_FROZEN_UPD": "2", "OWN_FROZEN_GAP": "0.005", "OWN_JUMP_GAP": "0.005",
                               "OWN_CLOSED": subprocess.run([PY, f"{ROOT}/sim/closed_windows.py", "--prep", SRC], capture_output=True, text=True).stdout.strip()},
                              ["liq_restore=2", "restore_big=1"])}
TOP5 = "2055,5301,1080,4402,3547"       # largest makers 20:00-20:05 (26% of maker volume)
SWEEP = {"ATTACK_AT": str(T + 15_000), "ATTACK_NTL": "1000000", "ATTACK_REPEAT": "1"}
ALL, OWNV = list(VARIANTS), ["V1_ownmark", "V2_own_cluster"]
# (name, prep (mode, args) or None, env, variants)
ATTACKS = [
    ("none", None, {}, ALL),
    ("1_put_2M", ("put", [str(T - 300_000), "2000000", "20"]), {}, ALL),
    ("1_put_10M", ("put", [str(T - 300_000), "10000000", "20"]), {}, ALL),
    ("2_pull1_sweep", None, {"ATTACK_PULL": f"2055;{T};60", **SWEEP}, ["V0_control", "V1_ownmark"]),
    ("2_pull5_sweep", None, {"ATTACK_PULL": f"{TOP5};{T};60", **SWEEP}, ["V0_control", "V1_ownmark", "V2_own_cluster"]),
    ("3_stophunt_1M", None, SWEEP, ["V0_control", "V1_ownmark"]),
    ("3_stophunt_5x500k", None, {**SWEEP, "ATTACK_NTL": "500000", "ATTACK_REPEAT": "5"}, ["V0_control", "V1_ownmark"]),
    ("4_starve_pull5", None, {"ATTACK_PULL": "STARVE"}, ["V0_control", "V1_ownmark", "V2_own_cluster"]),
    ("6_outage30s", None, {"RELAYER_OUT": f"{T - 5_000};30"}, ["V0_control", "V1_ownmark", "V2_own_cluster"]),
    ("6_outage30s_push", None, {"RELAYER_OUT": f"{T - 5_000};30", **SWEEP}, ["V0_control", "V1_ownmark", "V2_own_cluster"]),
    ("7_wash_oi", ("washoi", [str(T - 18 * 3600_000), str(T - 17 * 3600_000), "60000000"]), {}, ["V2_own_cluster"]),
    ("7_ladder3", ("ladder", ["0x30afce", "3", "0.025"]), {}, ["V0_control", "V2_own_cluster"]),
    ("8_cross_shock10", None, {"CROSS_SHOCK": f"{T + 10_000};0.10"}, ["V0_control", "V1_ownmark", "V2_own_cluster"]),
    ("9_wall2M", None, {"ATTACK_WALL": f"{T + 10_000};60;2000000"}, OWNV),
    ("9_wash500k", None, {"ATTACK_WASH": f"{T + 10_000};60;500000"}, OWNV),
    ("9_wall_wash_sweep", None, {"ATTACK_WALL": f"{T + 10_000};60;2000000", "ATTACK_WASH": f"{T + 10_000};60;500000",
                                 **SWEEP, "ATTACK_NTL": "500000", "ATTACK_REPEAT": "5"}, OWNV),
]

def prep_for(p):
    if p is None: return SRC, []
    mode, args = p
    d = f"{RUNS}/prep_{mode}_{'_'.join(args)}".replace(".", "p")
    log = f"{d}.log"
    if not os.path.exists(log):
        r = subprocess.run([PY, "-I", f"{ROOT}/sim/attack_prep.py", SRC, d, mode, *args], capture_output=True, text=True, check=True)
        open(log, "w").write(r.stdout)
    uids = [int(x) for x in re.search(r"uids \[([\d, ]*)\]", open(log).read()).group(1).split(",") if x.strip()]
    return d, uids

def starve_ms(variant):
    """the whale's first simulated liquidation round in this variant's baseline"""
    r = pl.read_csv(f"{RUNS}/rd_{variant}_none.csv").filter(pl.col("u") == 1410)
    b = pl.read_ipc(f"{SRC}/blocks.arrow")
    return int(b.filter(pl.col("h") == r["sim_h1"][0])["ms"][0])

def run(variant, name, prep, env_x):
    d, uids = prep_for(prep)
    ve, va = VARIANTS[variant]
    env_x = dict(env_x)
    if env_x.get("ATTACK_PULL") == "STARVE":
        env_x["ATTACK_PULL"] = f"{TOP5};{starve_ms(variant) - 1000};60"
    tag = f"{variant}_{name}"
    tk, rd = f"{RUNS}/tk_{tag}.csv", f"{RUNS}/rd_{tag}.csv"
    if os.environ.get("SUITE_FAITHFUL") == "1":
        # synthetic attackers (sweeper, ask wall, wash accounts) as margined accounts with capital = the largest notional
        # the attack places (HL's order margin check binds, the accounts can be liquidated and taken over)
        ns = [float(x) for k in ("ATTACK_NTL",) if k in env_x for x in env_x[k].split(",")]
        ns += [float(env_x[k].split(";")[-1]) for k in ("ATTACK_WALL", "ATTACK_WASH") if k in env_x]
        if ns: env_x["ATTACK_CAP"] = str(max(ns))
    env = {**os.environ, **BASE_ENV, **ve, **env_x, "RELAYER_RESID_IN": f"{SRC}/relayer_resid_endo0_policy.txt",
           "SIM_TK_OUT": tk, "ROUNDS_OUT": rd, "ATTACK_OUT": f"{RUNS}/atk_{tag}.csv"}
    cmd = [f"{ROOT}/tools/memguard.sh", "6000", ENGINE, "sim", d, str(ML), *va]
    out = subprocess.run(cmd, env=env, capture_output=True, text=True).stdout
    g = lambda pat, f=float: (lambda m: f(m.group(1)) if m else None)(re.search(pat, out))
    t = pl.read_csv(tk).join(pl.read_ipc(f"{SRC}/blocks.arrow"), on="h").sort("ms")
    t = t.join_asof(pl.read_parquet(FAIR).select("ms", pl.col("last").alias("F")).sort("ms"), on="ms")
    t = t.join_asof(EXT, on="ms")
    t = t.with_columns(val=pl.col("q") * (pl.col("F") - pl.col("px")), val_E=pl.col("q") * (pl.col("E") - pl.col("px")))
    xs = t.filter(pl.col("u").is_in(uids[:1])) if prep and prep[0] == "put" else None
    sweep = pl.read_csv(f"{RUNS}/atk_{tag}.csv") if os.path.exists(f"{RUNS}/atk_{tag}.csv") else None
    return dict(variant=variant, attack=name, vault_pnl=g(r"=> PnL \$(-?[\d.]+)"), inherited_musd=g(r"inherited \$([\d.]+)M"),
                takeovers=t.height, takeover_ntl_musd=round(float((t["q"].abs() * t["px"]).sum()) / 1e6, 3),
                value_at_takeover=round(float(t["val"].sum())), underwater=t.filter(pl.col("val") < 0).height,
                value_vs_E=round(float(t["val_E"].sum())), underwater_E=t.filter(pl.col("val_E") < 0).height,
                trig_fired=g(r"TRIG WINDOW: fired (\d+)", int), trig_size=g(r"TRIG WINDOW: fired \d+ taker size ([\d.]+)"),
                topups_usd=g(r"trader top-ups \$([\d.]+)") or 0.0,
                attacker_x_taken=(xs.height > 0) if xs is not None else None,
                attacker_profit_at_takeover=round(-float(xs["val"].sum())) if xs is not None and xs.height else None,
                sweep_cost=round(float(sweep["cost"].sum())) if sweep is not None and sweep.height else None,
                attacker_cap=float(env_x["ATTACK_CAP"]) if "ATTACK_CAP" in env_x else None,
                attackers_liquidated=len(re.findall(r"ATTACKER [^:]+: .*taken over [1-9]|ATTACKER [^:]+: .*liquidated [1-9]", out)),
                pulled_usd=g(r"cancelled \$([\d.]+) of resting"), cross_shock_usd=g(r"collateral removed \$([\d.]+)"))

if __name__ == "__main__":
    os.makedirs(RUNS, exist_ok=True)
    only = sys.argv[1:]
    done = pl.read_csv(OUT) if os.path.exists(OUT) else None
    rows = done.to_dicts() if done is not None else []
    have = {(r["variant"], r["attack"]) for r in rows}
    for name, prep, env_x, vs in ATTACKS:
        if only and name not in only and name != "none": continue
        sv = os.environ.get("SUITE_VARIANTS")
        vs = sv.split(",") if sv else vs
        for v in vs:
            if (v, name) in have: continue
            r = run(v, name, prep, env_x)
            print(r, flush=True)
            rows.append(r)
            pl.DataFrame(rows, infer_schema_length=None).write_csv(OUT)
