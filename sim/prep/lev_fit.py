"""Fit the leverage of accounts whose setting is not observed, on an isolated-only market.

Which accounts: those that trade the coin without a position at the day's snapshot, are not in the next snapshot, and
sent no updateLeverage before their first trade (PREP/lev_unknown.csv, written by sim/prep/acc_lev.py). The replay used to
give them the coin's maximum leverage.
Why it can be fitted: leverage is an integer from 1 to the maximum, and an isolated position's margin is notional /
leverage, so each candidate puts the account's first liquidation at a different mark update. The replay is run once per
candidate, on the REAL marks and today's rules, with every such account at that leverage, and each account takes the
candidate that reproduces what really happened to it:
  identified   really liquidated: the candidates whose first liquidation that trades (a book round with a fill, or the
               ADL) is of the same kind and on the same update as the real one (within TOL blocks); the highest if several
  nearest      really liquidated, no candidate lands on the real update: the one closest to it (reported, not exact)
  bounded      never liquidated in reality, and the maximum leverage would have liquidated it: every candidate that survives
               the day is consistent, so this is a ceiling, not an identification. The highest surviving one is taken
               (the account is as fragile as reality allows)
  free         never liquidated and survives at the maximum: the day carries no information, the maximum is kept
  unexplained  no candidate fits (liquidated at 1x, or really liquidated but never in the replay): kept at the maximum, listed
The fitted accounts are added to acc_init.arrow as flat isolated rows (q = 0) at their leverage; PREP/lev_fit.csv has the
per-account result. A calibration of one hidden constant per account on that account's own real outcome, like the
relayer's read lag; the report says how many accounts fall in each class.

Usage: python sim/prep/lev_fit.py PREP_DIR MAXLEV [engine args, e.g. backstop=adl]      (env LEV_FIT_PROCS, default 4)"""
import sys, os, subprocess, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor
import polars as pl
import importlib.util as _ilu0
_sp0 = _ilu0.spec_from_file_location("detio", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, MAXLEV, ARGS = sys.argv[1], int(float(sys.argv[2])), sys.argv[3:]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
ENGINE = os.path.join(ROOT, "engine/target/release/engine")
TOL = int(os.environ.get("LEV_FIT_TOL", "2"))
unk = pl.read_csv(f"{PREP}/lev_unknown.csv", schema={"u": pl.UInt32})["u"].to_list()
ai = pl.read_ipc(f"{PREP}/acc_init.arrow", memory_map=False)
ai = ai.filter(~pl.col("u").is_in(unk))                                   # rows of an earlier fit
if not unk:
    print("leverage fit: no account to fit"); pl.DataFrame(schema={"u": pl.UInt32, "lev": pl.Float64, "how": pl.String}).write_csv(f"{PREP}/lev_fit.csv"); sys.exit(0)
ae = pl.read_ipc(f"{PREP}/acc_events.arrow", memory_map=False)
# what really happened first to each account: (block, kind), kind 1 = ADL / backstop fill, 0 = a liquidation fill on the book
_rl = ae.filter(pl.col("k") == 4, pl.col("liq_side"), pl.col("u").is_in(unk)).sort("h", pl.col("bstop").cast(pl.Int8))
real = {u: (h, int(b)) for u, h, b in _rl.group_by("u", maintain_order=True).agg(pl.col("h").first(), pl.col("bstop").first()).iter_rows()}
tmp = tempfile.mkdtemp(prefix="levfit_")
flat = lambda levs: pl.DataFrame({"u": list(levs), "lev": [float(v) for v in levs.values()]}, schema={"u": ai.schema["u"], "lev": pl.Float64}).select(
    "u", pl.lit(0.0).alias("q"), pl.lit(0.0).alias("e"), pl.lit(float("nan")).alias("lp"), pl.lit(True).alias("iso"), "lev", pl.lit(float("nan")).alias("cm")).select(ai.columns)

def run(L):
    """the replay with every unfitted account at leverage L: each account's first liquidation block (round or ADL)"""
    f = f"{tmp}/acc_init_{L}.arrow"
    pl.concat([ai, flat({u: L for u in unk})], how="vertical_relaxed").write_ipc(f)
    env = dict(os.environ, MATCH="engine", TRIGGERS="simulate", SILENT="1", MARGIN="1", ENDO="0", ACC_INIT=f,
               LIQ_ROUNDS_OUT=f"{tmp}/liq_{L}.csv", SIM_TK_OUT=f"{tmp}/tk_{L}.csv")
    env.pop("MARK_SOURCE", None)                                           # the real marks
    r = subprocess.run([ENGINE, "sim", PREP, str(MAXLEV), *ARGS], env=env, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0: raise SystemExit(f"leverage fit: engine failed at leverage {L}: {r.stderr[-400:]}")
    # only rounds that filled: a liquidation order that fills nothing leaves no trace on the real tape either
    rd = pl.read_csv(f"{tmp}/liq_{L}.csv").filter(pl.col("filled") > 0).select(pl.col("u").cast(pl.Int64), "h", pl.lit(0).alias("kind"))
    tk = pl.read_csv(f"{tmp}/tk_{L}.csv").select(pl.col("u").cast(pl.Int64), "h", pl.lit(1).alias("kind"))
    ev = pl.concat([rd, tk]).sort("h", "kind").group_by("u", maintain_order=True).agg(pl.col("h").first(), pl.col("kind").first())
    return L, {u: (h, k) for u, h, k in ev.iter_rows()}

with ThreadPoolExecutor(int(os.environ.get("LEV_FIT_PROCS", "4"))) as ex:
    sim = dict(ex.map(run, range(1, MAXLEV + 1)))
rows = []
for u in unk:
    rh = real.get(u); sh = {L: sim[L].get(u) for L in sim}
    if rh is not None:
        near = lambda L: sh[L] is not None and abs(sh[L][0] - rh[0]) <= TOL
        exact = [L for L in sh if near(L) and sh[L][1] == rh[1]]            # same update and same kind of event
        block = [L for L in sh if near(L)]
        liq = [L for L in sh if sh[L] is not None]
        if exact: lev, how = max(exact), "identified"
        elif block: lev, how = max(block), "nearest"                        # same update, other kind (book round vs ADL)
        elif liq: lev, how = min(liq, key=lambda L: (abs(sh[L][0] - rh[0]), -L)), "nearest"
        else: lev, how = MAXLEV, "unexplained"
        nfit = len(exact)
    else:
        ok = [L for L in sh if sh[L] is None]
        if not ok: lev, how = MAXLEV, "unexplained"
        elif max(ok) == MAXLEV: lev, how = MAXLEV, "free"
        else: lev, how = max(ok), "bounded"
        nfit = len(ok)
    rows.append(dict(u=u, lev=float(lev), how=how, real_h=rh[0] if rh else None, sim_h=sh[lev][0] if sh.get(lev) else None, n_fit=nfit))
F = pl.DataFrame(rows, schema={"u": pl.UInt32, "lev": pl.Float64, "how": pl.String, "real_h": pl.Int64, "sim_h": pl.Int64, "n_fit": pl.Int64}).sort("u")
F.write_csv(f"{PREP}/lev_fit.csv")
pl.concat([ai, flat(dict(zip(F["u"].to_list(), F["lev"].to_list())))], how="vertical_relaxed").write_ipc(f"{PREP}/acc_init.arrow")
shutil.rmtree(tmp)
c = dict(F.group_by("how").len().iter_rows())
below = F.filter(pl.col("lev") < MAXLEV)
print(f"leverage fit: {len(unk)} accounts | identified {c.get('identified', 0)} | nearest {c.get('nearest', 0)} | bounded {c.get('bounded', 0)} "
      f"| free {c.get('free', 0)} | unexplained {c.get('unexplained', 0)} | below the maximum {MAXLEV}x: {below.height} "
      f"(leverages {sorted(below['lev'].cast(pl.Int64).to_list())[:12]}{'...' if below.height > 12 else ''})")
