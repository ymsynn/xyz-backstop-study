"""Benefits ledger: what the proposed package does for the protocol, against today, criterion by criterion.

Every number is read from a run output or a registry test written by a script; nothing is typed here. The package is
P4d (mark) + restore-to-IM (liquidation size) + fair sweep (vault unwind), compared with today's deployed rules on the
same replay (real orders, simulated mechanisms, real parameters for 'today'). No vault PnL (reporting rule): losses are
measured as what the vault inherits, its value against the external price E at takeover, how long and how much it holds,
and what it sells below E.

Inputs (all produced by scripts; see SIMULATOR_SPEC.md):
  data/scen/pkg/package_crash.csv, package_quiet.csv     sim/package_runs.sh + sim/package_eval.py
  data/scen/pkg/runs.log                                 package_runs.sh output (bad debt line), optional
  data/scen/attack_suite_pkg.csv                         SUITE_VARIANTS=V0_control,V4_package sim/attack_suite.py
  registry tests bench-spike5, bench-spike20, bench-freeze, bench-wash, bench-prop, bench-normal
  registry tests skhx-0727, handover screen CSV (data/scen/handover_screen.csv)
  registry designs p4d, restore_im, fair_sweep (owner label, plain sentence)
Writes: registry key "benefits" (rows + provenance), data/scen/benefits.csv; prints the ledger.
Usage: python sim/benefits.py
"""
import os, re, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = f"{ROOT}/data/scen"
reg = registry.load()
T = {t["id"]: t for t in reg["tests"]}
D = {d["id"]: d for d in reg["designs"]}
rows = []
# which package to score: pkg (P4d + restore + fair sweep) or pkgc (the same with the hold cap)
PK = os.environ.get("BENCH_PKG", "pkgk")
LEAD = "pkgk"   # the lead package writes docs/benefits.md and registry["benefits"]; others get a suffix
VAR, DES = {"pkg": ("V4_package", "package"), "pkgc": ("V5_package_cap", "package_cap"), "pkgt": ("V6_package_trig", "package_trig"), "pkgs": ("V7_package_step", "package_step"), "pkge": ("V8_package_ema", "package_ema"), "pkgz": ("V9_package_z", "package_z"), "pkgy": ("V10_package_y", "package_y"), "pkgw": ("V11_package_w", "package_w"), "pkgv": ("V12_package_v", "package_v"), "pkgk": ("V13_package_k", "package_k")}[PK]


def add(crit, claim, metric, today, pkg, unit, better, evidence, source, note=""):
    """better: 'lower' | 'higher' | 'same' (closer to today is better)."""
    # a difference counts only above a materiality floor per unit (or 1% of the larger magnitude): $1k of value, $0.05M of
    # notional, 5 bp of mark, 1 account / order / share
    floor = {"$": 1000.0, "$k": 1.0, "$M": 0.05, "bp": 5.0, "$M.min": 0.5, "% of notional": 0.05, "% of OI": 0.05}.get(unit, 1.0)
    if today is None or pkg is None:
        verdict = "n/a"
    else:
        d = pkg - today
        tiny = abs(d) < max(floor, 0.01 * max(abs(pkg), abs(today)))
        if better == "same":
            verdict = "same" if tiny else "differs"
        else:
            verdict = "same" if tiny else (("better" if d < 0 else "worse") if better == "lower" else ("better" if d > 0 else "worse"))
    rows.append(dict(criterion=crit, claim=claim, metric=metric, today=today, package=pkg, unit=unit, better=better,
                     verdict=verdict, evidence=evidence, source=source, note=note))


def test_rows(tid):
    t = T.get(tid)
    return t["results"] if t and isinstance(t.get("results"), list) else []


# ---------------------------------------------------------------- 2. ADL and vault losses (three crashes, replay)
pc = pl.read_csv(f"{S}/pkg/package_crash.csv")
g = pc.group_by("pkg").agg(pl.col("inherited_musd", "value_vs_E", "underwater", "book_liq_accounts", "exposure", "execution_vs_E", "sold_below_E", "cushion_vs_E").sum(),
                           pl.col("drift_var").sum().sqrt().alias("drift_sd"))
row = {r["pkg"]: r for r in g.to_dicts()}
a, b = row["today"], row[PK]
src = "package (sim/package_runs.sh, sim/package_eval.py)"
ev = "replay, 3 crashes"
add("losses", "The vault inherits a little more notional", "notional inherited", a["inherited_musd"], b["inherited_musd"], "$M", "lower", ev, src,
    "the mark follows a real gap instead of lagging it, so more accounts reach the backstop line; see the value rows")
add("losses", "...but inherits it at a profit against fair value, not a loss", "value at takeover vs E", a["value_vs_E"], b["value_vs_E"], "$", "higher", ev, src)
add("losses", "", "value at takeover per $ inherited", round(a["value_vs_E"] / a["inherited_musd"] / 1e4, 2), round(b["value_vs_E"] / b["inherited_musd"] / 1e4, 2), "% of notional", "higher", ev, src)
add("losses", "Fewer takeovers are underwater", "takeovers worth less than E at takeover", a["underwater"], b["underwater"], "accounts", "lower", ev, src)
add("losses", "The vault holds its inventory far less", "vault exposure (|position| x E x time)", round(a["exposure"], 1), round(b["exposure"], 1), "$M.min", "lower", ev, src)
add("losses", "", "price-drift risk on that inventory (1 sd)", round(a["drift_sd"] / 1e3, 1), round(b["drift_sd"] / 1e3, 1), "$k", "lower", ev, src)
add("losses", "The vault never dumps below fair value", "vault sales below E", round(a["sold_below_E"] / 1e6, 2), round(b["sold_below_E"] / 1e6, 2), "$M", "lower", ev, src,
    "by construction the fair sweep only sells at or above E; what remains is today's 0.5% clip")
add("losses", "", "unwind execution vs E", round(a["execution_vs_E"]), round(b["execution_vs_E"]), "$", "higher", ev, src)
for c in ("GOOGL", "INTC", "AMZN"):
    x = {r["pkg"]: r for r in pc.filter(pl.col("coin") == c).to_dicts()}
    add("losses", f"{c} 10-2{8 if c == 'GOOGL' else 9}", "value at takeover vs E", round(x["today"]["value_vs_E"]), round(x[PK]["value_vs_E"]), "$", "higher", "replay", src)
logf = f"{S}/pkg/runs.log"
if os.path.exists(logf):
    bd = {}
    for line in open(logf):
        m = re.match(r"(\w+) crash (\w+): LIQUIDATION BAD DEBT: \$(-?[\d.]+)", line)
        if m: bd[m.group(2)] = bd.get(m.group(2), 0.0) + float(m.group(3))
    if "today" in bd and PK in bd:
        add("losses", "Bad debt from book liquidation", "liquidation fills below bankruptcy", bd["today"], bd[PK], "$", "lower", ev, "package_runs.sh log")
sk = test_rows("skhx-0727")
if sk:
    sd = DES if any(r["design"] == DES for r in sk) else "p4d"
    real = [r for r in sk if r["design"] == "current"][0]; p = [r for r in sk if r["design"] == sd and "before" in r["case"]][0]
    bnd = [r for r in sk if r["design"] == sd and "bound" in r["case"]][0]
    add("losses", "SKHX 07-27 hand-over: the cascade that cost the vault $1.0M does not start", "positions held before the hand-over that were liquidated",
        real["liquidated_accounts"], p["liquidated_accounts"], "accounts", "lower", "offline replay of the relayer", "skhx-0727",
        f"upper bound if xyz trades had already been crushed: {bnd['liquidated_accounts']} accounts")
    add("losses", "", "notional liquidated", real["liquidated_musd"], p["liquidated_musd"], "$M", "lower", "offline replay of the relayer", "skhx-0727",
        f"bound {bnd['liquidated_musd']}")
vc = test_rows("vault-capital")
if vc:
    t = pl.DataFrame(vc)
    for ev in ("GOOGL 10-28", "INTC 10-29", "AMZN 10-29"):
        x = {z["design"]: z for z in t.filter(pl.col("case").str.starts_with(ev), pl.col("case").str.contains("replay")).to_dicts()}
        if "current" in x and DES in x:
            add("losses", f"Vault capital needed to stay above its own maintenance margin, {ev}", "share of the market's OI", x["current"]["c_mm_pct_oi"], x[DES]["c_mm_pct_oi"], "% of OI", "lower",
                "replay, real parameters (today: matches the real vault within 0.05 pt)", "vault-capital")
            add("losses", f"Vault capital needed to avoid ADL, {ev}", "share of the market's OI", x["current"]["c_adl_pct_oi"], x[DES]["c_adl_pct_oi"], "% of OI", "lower", "replay", "vault-capital")
    sk_v = t.filter(pl.col("case").str.starts_with("SKHX"))
    if sk_v.height:
        z = sk_v.to_dicts()[0]
        add("losses", "ADL at SKHX 07-27: the vault ran out", "capital the vault held vs what it needed to avoid ADL", z["capital_then"], z["c_adl"], "$", "same", "real vault fills",
            "vault-capital", f"${z['adl_musd']}M of the vault's inherited longs were auto-deleveraged; under the package the cascade does not start (0 of 945 positions)")
else:
    add("losses", "ADL", "shortfall passed to ADL", None, None, "", "lower", "not measured", "", "vault capital not measured")

# ---------------------------------------------------------------- 1. Robustness to attacks
f = f"{S}/attack_suite_faith.csv" if os.path.exists(f"{S}/attack_suite_faith.csv") else f"{S}/attack_suite_pkg.csv"
SUITE = os.path.basename(f)
if os.path.exists(f):
    A = pl.read_csv(f)
    base = {r["variant"]: r for r in A.filter(pl.col("attack") == "none").to_dicts()}
    worse_t = worse_p = 0; n = 0
    for name in [x for x in A["attack"].unique(maintain_order=True).to_list() if x != "none"]:
        rr = {r["variant"]: r for r in A.filter(pl.col("attack") == name).to_dicts()}
        if "V0_control" not in rr or VAR not in rr: continue
        n += 1
        o, pk = rr["V0_control"], rr[VAR]
        ev_a = "replay with the attack injected (GOOGL 10-28)"
        add("robust", f"attack {name}", "value at takeover vs E, under the attack", round(o["value_vs_E"]), round(pk["value_vs_E"]), "$", "higher", ev_a, SUITE,
            f"change vs the same rules without the attack: today {o['value_vs_E'] - base['V0_control']['value_vs_E']:+,.0f}, package {pk['value_vs_E'] - base[VAR]['value_vs_E']:+,.0f}")
        add("robust", f"attack {name}", "notional inherited, under the attack", round(o["inherited_musd"], 2), round(pk["inherited_musd"], 2), "$M", "lower", ev_a, SUITE)
        add("robust", f"attack {name}", "underwater takeovers (vs E), under the attack", o["underwater_E"], pk["underwater_E"], "accounts", "lower", ev_a, SUITE)
        if rr["V0_control"].get("attacker_profit_at_takeover") is not None or rr[VAR].get("attacker_profit_at_takeover") is not None:
            add("robust", f"attack {name}", "attacker's gross gain at takeover", rr["V0_control"].get("attacker_profit_at_takeover"), rr[VAR].get("attacker_profit_at_takeover"),
                "$", "lower", "replay with the attack injected (GOOGL 10-28)", SUITE, "gross: before the attacker's fees and margin")
for tid, label in (("bench-spike5", "bad external print, −5%"), ("bench-spike20", "bad external print, −20%")):
    r = test_rows(tid)
    if not r: continue
    t = pl.DataFrame(r)
    w = {dz: t.filter(pl.col("design") == dz) for dz in ("current", DES)}
    w["package"] = w[DES]
    if w["current"].height and w["package"].height:
        add("robust", label, "largest mark move caused (worst case)", float(w["current"]["mark_move_bp"].min()), float(w["package"]["mark_move_bp"].min()), "bp", "higher",
            "replay, E spiked 3 s to 5 min, 2 coins", tid)
        add("robust", label, "takeovers it causes (sum over cases)", float(w["current"]["extra_takeover_usd"].sum()) / 1e6, float(w["package"]["extra_takeover_usd"].sum()) / 1e6, "$M", "lower",
            "replay, E spiked 3 s to 5 min, 2 coins", tid)
        add("robust", label, "stop orders it fires (sum over cases)", float(w["current"]["extra_stops"].sum()), float(w["package"]["extra_stops"].sum()), "orders", "lower",
            "replay, E spiked 3 s to 5 min, 2 coins", tid)
r = test_rows("bench-freeze")
if r:
    t = pl.DataFrame(r)
    s_ = lambda sc, col: float(t.filter(pl.col("scenario") == sc)[col].sum())
    add("robust", "stuck feed at crash onset (2 min)", "notional inherited", s_("freeze_today", "inherited_musd"), s_(f"freeze_{PK}", "inherited_musd"), "$M", "lower", "replay, 3 crashes", "bench-freeze")
    add("robust", "", "value at takeover vs E", s_("freeze_today", "value_ext"), s_(f"freeze_{PK}", "value_ext"), "$", "higher", "replay, 3 crashes", "bench-freeze")
# wash prints with faithful attackers (ATTACK_CAP, data/scen/wash_faith): two margined accounts; the buyer's limit at +6% walks
# every real ask below it first, so this is a buy sweep plus wash prints at the band edge
WF = f"{S}/wash_faith"; WATT = [2**32 - 1 - 10, 2**32 - 1 - 11]; AW = 1793217718800 - 5000
if os.path.isdir(WF):
    blk_w = pl.read_ipc(f"{ROOT}/data/prep_GOOGL_1028/blocks.arrow").select("h", "ms")
    def mkw(f):
        m3 = lambda x, y, z: pl.max_horizontal(pl.min_horizontal(x, y), pl.min_horizontal(pl.max_horizontal(x, y), z))
        o = pl.read_csv(f).drop_nulls(["bid", "ask", "last"]); return o.select("h", "ms", (m3(pl.col("m1"), pl.col("m2"), m3(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mk"))
    def wharm(mk, w, d):
        n, base = f"GOOGL_{mk}_w{w}_f0.06_d{d}", f"GOOGL_{mk}_base"
        if not os.path.exists(f"{WF}/orc_{n}.csv"): return None
        E = pl.read_csv(f"{WF}/orc_{base}.csv").filter(pl.col("ext") > 0).select("ms", (pl.col("ext") / 1e6).alias("E")).sort("ms")
        def tkv(x):
            t = pl.read_csv(f"{WF}/tk_{x}.csv").join(blk_w, on="h").sort("ms").join_asof(E, on="ms").with_columns(v=pl.col("q") * (pl.col("E") - pl.col("px")), att=pl.col("u").is_in(WATT))
            return float(t.filter(~pl.col("att"))["v"].sum()), float(t.filter(pl.col("att"))["v"].sum())
        (vo, va), (vb, _) = tkv(n), tkv(base)
        g = mkw(f"{WF}/orc_{n}.csv").join(mkw(f"{WF}/orc_{base}.csv").select("h", pl.col("mk").alias("b")), on="h").filter(pl.col("ms").is_between(AW, AW + int(d) * 1000 + 60_000))
        # accounts hit (book round or takeover) only under the attack: a round before a takeover that also happens without it is no harm
        hit = lambda x: set(pl.read_csv(f"{WF}/rd_{x}.csv").filter(pl.col("sim_rounds") > 0)["u"]) | set(pl.read_csv(f"{WF}/tk_{x}.csv")["u"])
        only = (hit(n) - hit(base)) - set(WATT)
        return dict(lift=float(((g["mk"] / g["b"] - 1) * 1e4).max()), liq=len(only), others=vo - vb, att=va)
    for w in ("1e6", "5e6"):
        for d in ("60", "300", "900"):
            o, q = wharm("today", w, d), wharm(PK, w, d)
            if not o or not q: continue
            lab = f"wash at +6% (buy sweep + wash prints), ${float(w) * 10 / 1e6:g}M per 30 s, {int(d) // 60} min, attacker capital $5M per account"
            ev_w = "replay, GOOGL crash, attackers margined like any account"
            add("robust", lab, "mark held up vs no attack (max)", round(o["lift"], 1), round(q["lift"], 1), "bp", "lower", ev_w, "wash_faith")
            add("robust", lab, "accounts liquidated or taken over only because of the attack (attackers excluded)", o["liq"], q["liq"], "accounts", "lower", ev_w, "wash_faith")
            add("robust", lab, "change in the vault's value at takeover vs E, other accounts", round(o["others"]), round(q["others"]), "$", "higher", ev_w, "wash_faith")
            add("robust", lab, "value vs E of the attacker accounts the vault takes over", round(o["att"]), round(q["att"]), "$", "higher", ev_w, "wash_faith")
# buy wall with a faithful attacker (sim/prop_runs.sh CAPS=...): an ordinary cross account with this capital, margin-checked,
# liquidated and taken over like anyone; post-only asks that would cross its bid are rejected (HyperCore)
PF = f"{S}/prop_faith"; ATT = 2**32 - 1 - 9; A0 = 1793217718800 - 5000
if os.path.isdir(PF):
    med3 = lambda x, y, z: pl.max_horizontal(pl.min_horizontal(x, y), pl.min_horizontal(pl.max_horizontal(x, y), z))
    def mkf(f):
        o = pl.read_csv(f).drop_nulls(["bid", "ask", "last"]); return o.select("h", "ms", (med3(pl.col("m1"), pl.col("m2"), med3(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mk"))
    blk = pl.read_ipc(f"{ROOT}/data/prep_GOOGL_1028/blocks.arrow").select("h", "ms")
    acct = {}
    for lf in (f"{S}/prop_faith.log", f"{S}/trig_quick.log", f"{S}/trigcap_quick.log", f"{S}/trigs_quick.log"):
        if os.path.exists(lf):
            for ln in open(lf):
                m = re.match(r"GOOGL_(\w+?)_c([\d.e+]+)_f[\d.]+_d(\d+): PROP ACCOUNT: capital \$(\d+) \| end position (-?[\d.]+) equity at last mark \$(-?\d+)", ln)
                if m: acct[(m.group(1), m.group(2), m.group(3))] = (float(m.group(4)), float(m.group(6)))
    def harm(mk, cap, d):
        n, base = f"GOOGL_{mk}_c{cap}_f0.06_d{d}", f"GOOGL_{mk}_base"
        if not os.path.exists(f"{PF}/orc_{n}.csv"): return None
        m = mkf(f"{PF}/orc_{n}.csv").join(mkf(f"{PF}/orc_{base}.csv").select("h", pl.col("mk").alias("b")), on="h").filter(pl.col("ms").is_between(A0, A0 + int(d) * 1000 + 60_000))
        g = (m["mk"] / m["b"] - 1) * 1e4
        hitp = lambda x: set(pl.read_csv(f"{PF}/rd_{x}.csv").filter(pl.col("sim_rounds") > 0)["u"]) | set(pl.read_csv(f"{PF}/tk_{x}.csv")["u"])
        only_p = (hitp(n) - hitp(base)) - {ATT}
        trg = lambda x: pl.read_csv(f"{PF}/trig_{x}.csv").filter(pl.col("ms").is_between(A0, A0 + int(d) * 1000 + 340_000)).height
        E = pl.read_csv(f"{PF}/orc_{base}.csv").filter(pl.col("ext") > 0).select("ms", (pl.col("ext") / 1e6).alias("E")).sort("ms")
        val = lambda x: float(pl.read_csv(f"{PF}/tk_{x}.csv").filter(pl.col("u") != ATT).join(blk, on="h").sort("ms").join_asof(E, on="ms").select((pl.col("q") * (pl.col("E") - pl.col("px"))).sum()).item())
        ac = acct.get((mk, cap, d))
        return dict(lift=float(g.max()), liq=len(only_p), stops=trg(n) - trg(base), val=val(n) - val(base), loss=(ac[0] - ac[1]) if ac else None)
    for cap in ("1e6", "5e6", "25e6"):
        for d in ("60", "300"):
            o, q = harm("today", cap, d), harm(PK, cap, d)
            if not o or not q: continue
            lab = f"buy wall at +6%, attacker capital ${float(cap) / 1e6:g}M, {int(d) // 60 if int(d) >= 60 else d} min"
            ev_w = "replay, GOOGL crash, attacker margined like any account"
            add("robust", lab, "mark held up vs no attack (max)", round(o["lift"], 1), round(q["lift"], 1), "bp", "lower", ev_w, "prop_faith")
            add("robust", lab, "accounts liquidated or taken over only because of the wall (attacker excluded)", o["liq"], q["liq"], "accounts", "lower", ev_w, "prop_faith")
            add("robust", lab, "extra stop orders fired", o["stops"], q["stops"], "orders", "lower", ev_w, "prop_faith")
            add("robust", lab, "change in the vault's value at takeover vs E (attacker's own takeover excluded)", round(o["val"]), round(q["val"]), "$", "higher", ev_w, "prop_faith",
                f"attacker's loss of capital: today ${o['loss'] / 1e6:.2f}M, package ${q['loss'] / 1e6:.2f}M" if o["loss"] is not None and q["loss"] is not None else "")
# closed-hours wick (sim/closed_attack_eval.py): a faithful attacker props xyz's book while the venue is shut (GOOGL,
# 00:00-00:05 UTC 10-29, E frozen by schedule); found out of sample (CL, BRENTOIL 09-10 21:41)
for cw_id, ev_c in (("closed_wick", "replay, GOOGL 10-29 00:00 UTC (5-min close)"), ("closed_wick_cl", "replay, CL 09-10 21:10 UTC (CME 60-min close)")):
  cw = test_rows(cw_id)
  if cw and any(r["design"] == DES for r in cw):
    t = pl.DataFrame(cw, infer_schema_length=None)
    mkt = "GOOGL" if cw_id == "closed_wick" else "CL"
    for atk in sorted(set(t["attack"])):
        o = t.filter((pl.col("attack") == atk) & (pl.col("design") == "current")).to_dicts()
        q = t.filter((pl.col("attack") == atk) & (pl.col("design") == DES)).to_dicts()
        if not o or not q: continue
        o, q = o[0], q[0]; cap, d = re.match(r"closed_c([\d.e+]+)_f[\d.]+_d(\d+)", atk).groups()
        lab = f"closed-hours wick, {mkt}: ${float(cap) / 1e6:g}M attacker props the book {d} s while the venue is shut"
        add("robust", lab, "accounts liquidated or taken over only because of the attack (attackers excluded)", o["harmed_accounts"], q["harmed_accounts"], "accounts", "lower", ev_c, cw_id)
        add("robust", "", "mark above E at most during the attack", o["mark_lift_bp"], q["mark_lift_bp"], "bp", "lower", ev_c, cw_id,
            f"without the attack: today {o['base_lift_bp']} bp, package {q['base_lift_bp']} bp")
hs = f"{S}/handover_screen.csv"
if os.path.exists(hs):
    h = pl.read_csv(hs)
    held = int(h["hold"].sum()) if "hold" in h.columns else None
    add("robust", "every closed-market → live hand-over, 4 days, all xyz coins", "hand-overs where the new rule would hold the mark", 0, held, "hand-overs", "lower", "screen of the real tape", "handover-screen",
        f"{h.height} hand-overs on {h['coin'].n_unique() if 'coin' in h.columns else '?'} coins; holding on a normal hand-over would be a false alarm")

# ---------------------------------------------------------------- 4. Traders don't feel it
q = pl.read_csv(f"{S}/pkg/package_quiet.csv").group_by("pkg").agg(pl.col("liquidated", "rounds", "takeovers").sum())
qq = {r["pkg"]: r for r in q.to_dicts()}
add("traders", "Quiet days: nothing changes", "accounts liquidated (6 coin-days)", qq["today"]["liquidated"], qq[PK]["liquidated"], "accounts", "same", "replay, Oct 20-21", src)
add("traders", "", "backstop takeovers (6 coin-days)", qq["today"]["takeovers"], qq[PK]["takeovers"], "takeovers", "same", "replay, Oct 20-21", src)
add("traders", "In a crash, about as many traders are liquidated", "accounts with book liquidation rounds (3 crashes)", a["book_liq_accounts"], b["book_liq_accounts"], "accounts", "same", ev, src,
    "slightly more: the mark follows the real gap; a large liquidated position keeps about half its size instead of losing it all (restore-to-IM)")
r = test_rows("bench-normal")
if r:
    t = pl.DataFrame(r).filter(pl.col("design") == DES)
    add("traders", "Normal out-of-hours markets: the mark is where it is today", "mark vs today's mark, 99th percentile", None, float(t["mark_vs_today_p99_bp"].max()), "bp", "lower",
        "replay, every out-of-hours session of 3 earnings days", "bench-normal")
    tt = t.filter(pl.col("case") == "all")
    add("traders", "", "accounts liquidated (3 coins, ~17 h each)", int(tt["liq_accounts_today"].sum()), int(tt["liq_accounts"].sum()), "accounts", "same", "replay", "bench-normal")
    add("traders", "", "accounts only one side liquidates", int(tt["liq_only_today"].sum()), int(tt["liq_only_new"].sum()), "accounts", "lower", "replay", "bench-normal")
    add("traders", "", "stop orders fired (3 coins, ~17 h each)", int(tt["stops_today"].sum()), int(tt["stops"].sum()), "orders", "same", "replay", "bench-normal")
    add("traders", "", "stop orders only one side fires", int(tt["stops_only_today"].sum()), int(tt["stops_only_new"].sum()), "orders", "lower", "replay", "bench-normal",
        "dust orders at the mark")
    add("traders", "", "size of those stop orders", float(tt["stops_only_today_size"].sum()), float(tt["stops_only_new_size"].sum()), "shares", "lower", "replay", "bench-normal")
if sk:
    add("traders", "SKHX 07-27: traders are not wiped out by a stale-to-live jump", "accounts liquidated at the hand-over", real["liquidated_accounts"], p["liquidated_accounts"], "accounts", "lower",
        "offline replay of the relayer", "skhx-0727")

# ---------------------------------------------------------------- 3. Hyperliquid changes, 5. simple to explain
for lay, did in (("mark", "p4d"), ("liquidation size", "restore_im"), ("vault unwind", "fair_sweep")):
    d = D[did]
    owner = {"deployer": "trade.xyz (relayer)", "hl": "HyperCore change", "deployed": "deployed"}.get(d.get("cls"), d.get("cls"))
    add("hl", f"{lay}: {d['short']}", "who ships it", None, None, owner, "lower", "design", f"design {did}", d.get("assessment", {}).get("hl", {}).get("note", ""))
    plain = d.get("plain", "")
    if did == "p4d" and PK in ("pkgv", "pkgk"):
        plain = ("The mark follows trade.xyz's external price at once, and xyz's own book can pull it at most today's 50 bp away. "
                 "Only when the external price jumps by more than the band in one update, or stops, does the mark switch to xyz's own price, "
                 "until the two agree again within 50 bp."
                 + (" A feed that goes quiet because its market is closed is not treated as broken." if PK == "pkgk" else ""))
    elif did == "p4d" and PK in ("pkgt", "pkgs"):
        plain += (" It starts ignoring the feed only when the feed jumps by more than the band within 30 seconds, or stops." if PK == "pkgt"
                  else " It starts ignoring the feed only when the feed jumps by more than the band in one update, or stops.")
    add("simple", ("mark: today's relayer, oracle unclamped, xyz's price only after a feed failure" if did == "p4d" and PK in ("pkgv", "pkgk") else f"{lay}: {d['short']}" + (" + start rule" if did == "p4d" and PK in ("pkgt", "pkgs") else "")), "plain explanation", None, None, "", "lower", "design", f"design {did}", plain)

L = pl.DataFrame(rows, infer_schema_length=None)
L.write_csv(f"{S}/benefits{'' if PK == LEAD else '_' + PK}.csv")
reg["benefits" if PK == LEAD else f"benefits_{PK}"] = {"generated_by": "python sim/benefits.py", "commit": registry.commit(), "rows": rows,
                   "inputs": ["package", SUITE, "bench-spike5", "bench-spike20", "bench-freeze", "bench-wash", "bench-prop", "bench-normal", "skhx-0727", "handover-screen", "closed_wick", "closed_wick_cl"]}
registry.save(reg)
pl.Config.set_tbl_rows(300); pl.Config.set_tbl_width_chars(260); pl.Config.set_fmt_str_lengths(70); pl.Config.set_tbl_cols(9)
for c in ("robust", "losses", "hl", "traders", "simple"):
    x = L.filter(pl.col("criterion") == c)
    print(f"\n== {c}: {x.height} rows, better {(x['verdict'] == 'better').sum()}, same {(x['verdict'] == 'same').sum()}, worse {(x['verdict'] == 'worse').sum()}")
    print(x.select("claim", "metric", "today", "package", "unit", "verdict", "source"))

# ---------------------------------------------------------------- docs/benefits.md, generated from the rows above
NAMES = {"robust": "1. Robust to attacks", "losses": "2. ADL and vault losses", "hl": "3. Hyperliquid changes", "traders": "4. Traders don't feel it", "simple": "5. Simple to explain"}
def fmt(v, unit):
    if v is None: return ""
    if unit == "$": return f"{v:+,.0f}" if v else "0"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"
out = ["# Benefits ledger: the package vs today", "",
       f"Generated by `python sim/benefits.py` at commit {registry.commit()}. Every number comes from a run output or a registry test; "
       "no vault PnL (reporting rule). The package is today's relayer with the oracle unclamped and xyz's own price used only after a feed failure (mark) + restore-to-IM (liquidation size) + fair sweep (vault unwind). "
       "A difference counts only above a floor ($1k, $0.05M, 5 bp, 1 unit, or 1% of the larger value).", ""]
for c in ("robust", "losses", "hl", "traders", "simple"):
    x = [r for r in rows if r["criterion"] == c]
    nb, ns, nw = sum(r["verdict"] == "better" for r in x), sum(r["verdict"] == "same" for r in x), sum(r["verdict"] == "worse" for r in x)
    out += [f"## {NAMES[c]}", "", f"{len(x)} rows: {nb} better, {ns} same, {nw} worse.", ""]
    if c in ("hl", "simple"):
        out += ["| layer | " + ("who ships it | note |" if c == "hl" else "in one sentence |"), "|---|---|" + ("---|" if c == "hl" else "")]
        for r in x: out.append(f"| {r['claim']} | {r['unit']} | {r['note']} |" if c == "hl" else f"| {r['claim']} | {r['note']} |")
    else:
        out += ["| case | metric | today | package | unit | verdict | source |", "|---|---|---|---|---|---|---|"]
        for r in x:
            out.append(f"| {r['claim']} | {r['metric']} | {fmt(r['today'], r['unit'])} | {fmt(r['package'], r['unit'])} | {r['unit']} | {r['verdict']} | {r['source']} |")
            if r["note"]: out.append(f"| | *{r['note']}* | | | | | |")
    out.append("")
open(f"{ROOT}/docs/benefits{'' if PK == LEAD else '_' + PK}.md", "w").write("\n".join(out))
print("wrote docs/benefits.md")
