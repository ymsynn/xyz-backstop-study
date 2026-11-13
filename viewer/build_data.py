"""Build the data files of the rule explorer (viewer/index.html) from engine outputs.

The explorer computes nothing: every line it draws is a replay the engine already ran. This script reads those outputs
(orc_, liq_, tk_, rd_, log_ files, written by the runners under sim/) and writes, for each test and each combination of
rules, one small file with the series in the test's time window and the summary figures.

  viewer/data/index.js                 the rule axes, the combinations, the tests and which combinations each test has
  viewer/data/<test>/<combination>.js  the series of one replay

The mark, the votes and the vault's figures are computed by the functions of sim/figs.py, so they are the paper's.
Usage: python viewer/build_data.py [RESULTS_DIR ...]     default: data/scen/final (the paper's run) and data/scen/explorer
                                                          (the extra combinations, viewer/run_grid.sh)
Needs polars, numpy and matplotlib (imported by sim/figs.py).
"""
import json, os, subprocess, sys
import numpy as np
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, f"{ROOT}/sim")
import figs  # noqa: E402

DIRS = [os.path.abspath(d) for d in (sys.argv[1:] or [f"{ROOT}/data/scen/final", f"{ROOT}/data/scen/explorer"])]
OUT = f"{ROOT}/viewer/data"

# ---- the rules a user can combine. Each axis: key, label, {value: (label, short label)}. "-" = does not apply to that mark formula.
AXES = [
    ("mark", "Start from", {"today": ("Today", "Today"), "three": ("Proposal", "Proposal")}),
    ("tau", "Anchor averaged over", {"-": ("n/a", ""), "300": ("5 min", "5 min anchor"), "1800": ("30 min", "30 min anchor"), "7200": ("2 h", "2 h anchor")}),
    ("anchor", "Correction step", {
        "-": ("n/a", ""), "none": ("Off", "no correction step"), "book": ("On, unless xyz's book is between the feed and the anchor", "correction step"), "always": ("Always on", "correction step always on")}),
    ("closed", "Feed not live", {"today": ("Today's rule", ""), "cap100": ("Steps capped at 1%", "")}),
    ("sizing", "Liquidation", {"slices": ("Today's sizing", "today's sizing"), "cutback": ("Cut-back", "cut-back")}),
]
# ---- the combinations that were replayed. des = tag of the liquidation replays (sim/runs/liqbook_runs.sh), mk = tag of the
# mark runs (sim/pkgm_env.zsh); None = that family was not run for this combination.
ANCHOR_TAG = {"none": "k", "book": "q", "always": "r"}   # the engine's letter for each anchor rule (sim/pkgm_env.zsh)
COMBOS = [
    dict(id="today", name="Today", mark="today", tau="-", anchor="-", closed="today", sizing="slices", des="today", mk="today"),
    dict(id="today_cutback", name=None, mark="today", tau="-", anchor="-", closed="today", sizing="cutback", des="rim", mk="todayc"),
]
for _tau in ("300", "1800", "7200"):
    for _anchor, _x in ANCHOR_TAG.items():
        for _sizing in ("slices", "cutback"):
            _prop = (_tau, _anchor, _sizing) == ("1800", "book", "cutback")   # the proposal: 30 minutes, book-aware, cut-back
            COMBOS.append(dict(id="proposal" if _prop else f"three_{_tau}_{_anchor}_{_sizing}", name="Proposal" if _prop else None,
                               mark="three", tau=_tau, anchor=_anchor, closed="cap100", sizing=_sizing,
                               des=f"lead3{_x}{_tau}" + ("s20" if _sizing == "slices" else ""),
                               mk=f"pkgm3{_x}{_tau}" + ("s20" if _sizing == "slices" else "")))
# ---- the tests. fam = which tag names the run; run / base = file-name patterns ({c} coin, {tag} the combination's tag);
# base = the same replay without the attack; win = minutes shown before and after time zero.
CRASH = dict(kind="crash", fam="des", zero="End of the external price's fastest one-minute fall")
TESTS = [
    dict(id="crash_GOOGL_1028", group="Earnings crashes", title="Alphabet, October 28", sub="Earnings crash, as recorded", c="GOOGL", L=20,
         sub_dirs=("liqstudy", "crash"), run="GOOGL_1028_{tag}", win=(5, 30), **CRASH),
    dict(id="crash_INTC_1029", group="Earnings crashes", title="Intel, October 29", sub="Earnings crash, as recorded", c="INTC", L=10,
         sub_dirs=("liqstudy", "crash"), run="INTC_1029_{tag}", win=(5, 30), **CRASH),
    dict(id="crash_AMZN_1029", group="Earnings crashes", title="Amazon, October 29", sub="Earnings crash, as recorded", c="AMZN", L=20,
         sub_dirs=("liqstudy", "crash"), run="AMZN_1029_{tag}", win=(5, 30), **CRASH),
    dict(id="crash_SKHX_0727", group="A wrong price at a reopening", title="SK Hynix, July 27", sub="The whole day, as recorded", c="SKHX", L=10,
         sub_dirs=("skhx", "crash"), run="SKHX_0727_{tag}", win=(10, 60), **CRASH),
    dict(id="badprint_GOOGL", group="Attacks on the external price", title="Wrong external price", kind="attack", fam="mk", c="GOOGL", L=20,
         sub="Alphabet, October 28: the external price is 5% too low for 30 seconds", sub_dirs=("spike",), run="GOOGL_{tag}_q30s", base="GOOGL_{tag}_base",
         zero="First wrong price", t0="ext", win=(2, 10)),
    dict(id="walk_night_GOOGL", group="Attacks on the external price", title="External price walked overnight", kind="attack", fam="mk", c="GOOGL", L=20,
         sub="Alphabet, night of October 28: the external price is walked 10% lower over 30 seconds, held 2 minutes, then released", sub_dirs=("onw",),
         run="GOOGL_{tag}_w30", base="GOOGL_{tag}_base", zero="Start of the walk", t0="ext", win=(3, 15)),
    dict(id="push_closed_CL", group="Pushes on xyz's order book", title="Book pushed while crude oil is closed", kind="attack", fam="mk", c="CL", L=20,
         sub="Crude oil, daily break of September 10: a $5M bid 6% above the market, held 15 minutes", sub_dirs=("closed_CL",),
         run="CL_{tag}_c5e6_f0.06_d900", base="CL_{tag}_base", zero="Start of the push", t0="book", win=(4, 60)),
    dict(id="push_closed_GOLD", group="Pushes on xyz's order book", title="Book pushed while gold is closed", kind="attack", fam="mk", c="GOLD", L=25,
         sub="Gold, weekend of October 30: a $5M bid 6% above the market, held 15 minutes", sub_dirs=("closed_GOLD",),
         run="GOLD_{tag}_c5e6_f0.06_d900", base="GOLD_{tag}_base", zero="Start of the push", t0="book", win=(6, 120)),
    dict(id="push_quiet_GOOGL", group="Pushes on xyz's order book", title="Book pushed while the feed is quiet", kind="attack", fam="mk", c="GOOGL", L=20,
         sub="Alphabet overnight, external price unchanged: a $5M bid 6% above the market, held 2.5 hours", sub_dirs=("quiet_up",),
         run="GOOGL_{tag}_c5e6_f0.06_d9000", base="GOOGL_{tag}_base", zero="Start of the push", t0="book", win=(10, 180)),
]


def find(test, name):
    """Folder holding orc_<name>.csv, searching every results dir and the test's sub-folders in order."""
    for d in DIRS:
        for s in test["sub_dirs"]:
            if os.path.exists(f"{d}/{s}/orc_{name}.csv"): return f"{d}/{s}"
    return None


def r6(a):
    """Six significant digits, NaN -> null: what a chart can show, a third of the bytes."""
    return [None if (v is None or v != v) else float(f"{v:.6g}") for v in np.asarray(a, dtype=float).tolist()]


def cum_on(grid, when, amount):
    """Running total of `amount` (events at times `when`) at each time of `grid`."""
    if len(when) == 0: return np.zeros(len(grid))
    o = np.argsort(when); c = np.concatenate([[0.0], np.cumsum(np.asarray(amount, dtype=float)[o])])
    return c[np.searchsorted(np.asarray(when)[o], grid, side="right")]


def time_zero(test, T, name, base_name, m):
    z = test.get("t0")
    if isinstance(z, int): return z
    if z == "ext":      # first update where the external price differs from the replay without the attack
        b = figs.fmarks(T, base_name).select("h", E_b="E")
        return m.join(b, on="h").filter(pl.col("E") != pl.col("E_b"))["ms"][0]
    if z == "book":     # first update where the book differs (figs.flift), brought back to the minute the push starts on
        t0 = figs.flift(T, name, base_name)[1]
        if t0 is None: raise SystemExit(f"{name}: the pushed book never differs from the base run")
        return t0 // 60000 * 60000
    # a crash: the end of the external price's fastest 60 s fall (20 updates), as in the paper's crash figure
    return m.with_columns(r=pl.col("E") / pl.col("E").shift(20) - 1).drop_nulls("r").sort("r").head(1)["ms"][0]


def one_run(test, combo, t0_ref):
    tag = combo[test["fam"]]
    if tag is None: return None, t0_ref
    name = test["run"].format(tag=tag); T = find(test, name)
    if T is None: return None, t0_ref
    base_name = test["base"].format(tag=tag) if test.get("base") else None
    m = figs.fmarks(T, name)
    # time zero is fixed by the first combination of the test (today's rules), so every line shares one clock
    t0 = t0_ref if t0_ref is not None else time_zero(test, T, name, base_name, m)
    lo, hi = t0 - test["win"][0] * 60e3, t0 + test["win"][1] * 60e3
    w = m.filter(pl.col("ms").is_between(lo, hi))
    ms = w["ms"].to_numpy()
    out = dict(t=[round(float(x), 1) for x in (ms - t0) / 1e3], E=r6(w["E"]), V=r6(w["V"]), A=r6(w["A"]), B=r6(w["B"]), M=r6(w["mk"]))
    summary = {}
    if base_name:
        j = figs.flift(T, name, base_name)[0].filter(pl.col("ms").is_between(lo, hi))
        out["lift"] = r6(j["g"]); out["t_lift"] = [round(float(x), 1) for x in (j["ms"].to_numpy() - t0) / 1e3]
        g = j.filter(pl.col("ms") >= t0)["g"]
        summary["lift"] = float(g.max()) if g.max() >= -g.min() else float(g.min())   # the largest move, with its sign
    gap = (w["mk"] / w["E"] - 1) * 100
    summary["gap_max"] = float(gap.abs().max())
    # liquidations inside the window. Through the book: every round of liq_ (filled size at its average price); where the
    # runner wrote no liq_ file, the first round of each account from rd_ at the external price. To the vault: tk_.
    orc = m.select("h", "ms", "E").sort("h")
    if os.path.exists(f"{T}/liq_{name}.csv") and os.path.getsize(f"{T}/liq_{name}.csv") > 0:
        q = pl.read_csv(f"{T}/liq_{name}.csv", schema_overrides={"filled": pl.Float64, "avg_px": pl.Float64}).filter(pl.col("u") != figs.ATT)
        bt, ba = q["ms"].to_numpy(), (q["filled"] * q["avg_px"]).fill_nan(0).fill_null(0).to_numpy()   # nothing filled: no average price
    else:
        q = (pl.read_csv(f"{T}/rd_{name}.csv").filter((pl.col("sim_h1") > 0) & (pl.col("u") != figs.ATT)).sort("sim_h1")
             .join_asof(orc.rename({"h": "sim_h1"}), on="sim_h1"))
        bt, ba = q["ms"].to_numpy(), (q["sim_filled"] * q["E"]).fill_nan(0).fill_null(0).to_numpy()
    tk = figs.ftk(T, name)
    if tk is not None and tk.height:
        tk = tk.filter(pl.col("u") != figs.ATT).sort("h").join_asof(orc, on="h")
        vt, va = tk["ms"].to_numpy(), tk["ntl"].to_numpy()
    else:
        vt, va = np.array([]), np.array([])
    inw = lambda t: (t >= lo) & (t <= hi)
    out["book"] = r6(cum_on(ms, bt[inw(bt)], ba[inw(bt)]) / 1e6)       # $M, running total from the left edge of the window
    out["vault"] = r6(cum_on(ms, vt[inw(vt)], va[inw(vt)]) / 1e6)
    summary.update(book_win=float(ba[inw(bt)].sum()) / 1e6, vault_win=float(va[inw(vt)].sum()) / 1e6, vault_n_win=int(inw(vt).sum()))
    v = figs.fvault(T, name, test["L"])                                 # whole replay: capital need, money needed to avoid ADL
    summary.update(takeovers=v["tk"], inherited=v["ntl"] / 1e6)
    if os.path.exists(f"{T}/log_{name}.csv"):                           # the vault's trades were logged: its needs can be computed
        summary.update(need=v["need"] / 1e6, adl=v["adl"] / 1e6)
    if base_name and find(test, base_name):
        vb = figs.fvault(T, base_name, test["L"])
        summary.update(inherited_added=(v["ntl"] - vb["ntl"]) / 1e6, takeovers_added=v["tk"] - vb["tk"])
    out["summary"] = {k: (round(x, 4) if isinstance(x, float) else x) for k, x in summary.items()}
    return out, t0


def main():
    os.makedirs(OUT, exist_ok=True)
    tests = []
    for test in TESTS:
        os.makedirs(f"{OUT}/{test['id']}", exist_ok=True)
        have, t0 = [], None
        for combo in COMBOS:
            run, t0 = one_run(test, combo, t0)
            if run is None: continue
            with open(f"{OUT}/{test['id']}/{combo['id']}.js", "w") as f:
                f.write(f"BS.run({json.dumps(test['id'])},{json.dumps(combo['id'])},{json.dumps(run, separators=(',', ':'))});\n")
            have.append(combo["id"])
            s = run["summary"]
            print(f"{test['id']:20s} {combo['id']:24s} points {len(run['t']):5d}  inherited {s['inherited']:.2f}"
                  + (f"  need {s['need']:.3f}  avoid ADL {s['adl']:.3f}" if "need" in s else "")
                  + (f"  moved {s['lift']:+.2f}%" if "lift" in s else f"  gap {s['gap_max']:.2f}%")
                  + (f"  added to the vault {s['inherited_added']:+.2f}" if "inherited_added" in s else ""))
        tests.append({k: test[k] for k in ("id", "group", "title", "sub", "kind", "zero", "win")} | dict(combos=have, has_base=bool(test.get("base"))))
    try: commit = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception: commit = ""
    idx = dict(axes=[dict(key=k, label=l, values={x: dict(label=a, short=b) for x, (a, b) in v.items()}) for k, l, v in AXES],
               combos=[{k: c[k] for k in ("id", "name", "mark", "tau", "anchor", "closed", "sizing")} for c in COMBOS
                       if any(c["id"] in t["combos"] for t in tests)],
               tests=tests, commit=commit)
    with open(f"{OUT}/index.js", "w") as f:
        f.write(f"BS.index({json.dumps(idx, separators=(',', ':'))});\n")
    print(f"wrote {OUT}: {sum(len(t['combos']) for t in tests)} replays in {len(tests)} tests")


if __name__ == "__main__":
    main()
