"""The broadest selloff (11-05) replayed market by market under each design, scored jointly (ec2/days_job.sh with DAYS_DES,
X_COINS, CONTAGION -> data/scen/joint/).
Designs (every coin of the day):  today | lead (package_m_int); noCross coins always with the ADL backstop, except
  *_six: the six eligible coins (HOOD, MSTR, NBIS, AMD, EWY, SMSN) with the vault backstop (cross enabled)
  *_p2: contagion pass, each cross account's other xyz positions marked at the other coins' simulated inputs of that design
Per design: vault takeovers (notional, count, coins), ADL notional on noCross coins, and the vault's joint capital need: its
inventory on all coins at once (takeovers at the transfer price, then its unwind), marked at every relayer update at
median(m1, m2, mid) of each coin's run; C_MM = max(MM of inventory - equity), C_ADL = max(-equity) (the vault's equity,
relative to the day's start; a capital need, not PnL). Usage: python sim/score/joint_eval.py [DAY=1105]  (REG=joint-1105)"""
import glob, json, os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
J = os.environ.get("JOINT_DIR", f"{ROOT}/data/scen/joint")
DAY = sys.argv[1] if len(sys.argv) > 1 else "1105"
U = json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]
ML = {u["name"][4:]: u["maxLeverage"] for u in U}
NOX = {u["name"][4:] for u in U if u.get("marginMode") in ("noCross", "strictIsolated")}
SIX = {"HOOD", "MSTR", "NBIS", "AMD", "EWY", "SMSN"}
coins = sorted({os.path.basename(f)[4:].split(f"_{DAY}_")[0] for f in glob.glob(f"{J}/orc_*_{DAY}_today.csv")})
print(f"{len(coins)} coins on {DAY}")

def files(c, base, six, p2):
    d = base + ("x" if six and c in SIX else "")
    suf = "_p2" if p2 and not d.endswith("x") else ""
    return d, suf
def tkntl(t):
    """Notional handed to the vault: |q| at the transfer price, or at the mark where that price is negative (a position
    whose bankruptcy price is below zero), so that it adds to the total. Same rule as sim/final/score_final.py."""
    return t["q"].abs() * t.select(pl.when(pl.col("px") > 0).then(pl.col("px")).otherwise(pl.col("mark"))).to_series()



def coin_run(c, d, suf):
    n = f"{c}_{DAY}_{d}{suf}"
    o = pl.read_csv(f"{J}/orc_{n}.csv").select("h", "ms", ((pl.concat_list(pl.col("m1"), pl.col("m2"), (pl.col("bid") + pl.col("ask")) / 2).list.median()) / 1e6).alias("mark")).drop_nulls().sort("h")
    tk = pl.read_csv(f"{J}/tk_{n}.csv") if os.path.exists(f"{J}/tk_{n}.csv") else pl.DataFrame()
    lg = pl.read_csv(f"{J}/log_{n}.csv") if os.path.exists(f"{J}/log_{n}.csv") else pl.DataFrame()
    return o, tk, lg

BASES = os.environ.get("JOINT_DES", "today lead").split()   # JOINT_DES="today lead3q1800": the final rerun
OUTD = J if os.environ.get("JOINT_DIR") else f"{ROOT}/data/scen"   # JOINT_DIR: the summaries stay in that folder
designs = [(b, six, p2) for six, p2 in ((False, False), (True, False), (False, True)) for b in BASES]
rows, paths = [], {}
for base, six, p2 in designs:
    name = base + ("_six" if six else "") + ("_p2" if p2 else "")
    ev, mk, missing = [], [], []
    tk_v = tk_a = 0.0; n_v = n_a = 0; vcoins = set()
    for c in coins:
        d, suf = files(c, base, six, p2)
        if not os.path.exists(f"{J}/orc_{c}_{DAY}_{d}{suf}.csv"): missing.append(c); continue
        o, tk, lg = coin_run(c, d, suf)
        adl = c in NOX and not d.endswith("x")
        if tk.height:
            ntl = float(tkntl(tk).sum())
            if adl: tk_a += ntl; n_a += tk.height
            else: tk_v += ntl; n_v += tk.height; vcoins.add(c)
        mk.append(o.select("ms", "mark").with_columns(coin=pl.lit(c)))
        if lg.height and not adl:
            f = lg.join(o.select("h", "ms"), on="h", how="left").with_columns(pl.col("ms").forward_fill().backward_fill())
            ev.append(f.select("ms", coin=pl.lit(c), q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz")), px="px"))
    r = dict(design=name, coins=len(coins) - len(missing), missing=",".join(missing), vault_takeovers=n_v, vault_inherited_M=round(tk_v / 1e6, 3),
             vault_coins=len(vcoins), adl_events=n_a, adl_M=round(tk_a / 1e6, 3))
    if ev:
        E = pl.concat(ev).sort("ms"); M = pl.concat(mk).sort("ms")
        # joint path on the union of update times: inventory and cash from the vault's trades, each coin's last mark
        q = E.with_columns(cq=pl.col("q").cum_sum().over("coin"), cash=(-pl.col("q") * pl.col("px")).cum_sum())
        grid = M.select("ms").unique().sort("ms")
        V = pl.DataFrame({"ms": grid["ms"]}).join_asof(q.select("ms", "cash").sort("ms"), on="ms").with_columns(pl.col("cash").fill_null(0.0))
        val, mm = V["cash"].to_numpy().copy(), 0.0 * V["cash"].to_numpy()
        for c in E["coin"].unique().to_list():
            g = grid.join_asof(q.filter(pl.col("coin") == c).select("ms", "cq").sort("ms"), on="ms").join_asof(M.filter(pl.col("coin") == c).select("ms", "mark").sort("ms"), on="ms") \
                    .with_columns(pl.col("cq").fill_null(0.0), pl.col("mark").forward_fill().backward_fill())
            val += (g["cq"] * g["mark"]).to_numpy(); mm += (g["cq"].abs() * g["mark"] / (2 * ML.get(c, 10))).to_numpy()
        r.update(C_MM_M=round(max(0.0, float((mm - val).max())) / 1e6, 3), C_ADL_M=round(max(0.0, float((-val).max())) / 1e6, 3))
    rows.append(r)
R = pl.DataFrame(rows, infer_schema_length=None)
pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(12); print(R)
R.write_csv(f"{OUTD}/joint_{DAY}.csv")
per = []
for c in coins:
    for d in BASES:
        n = f"{c}_{DAY}_{d}"
        if os.path.exists(f"{J}/tk_{n}.csv"):
            t = pl.read_csv(f"{J}/tk_{n}.csv", schema_overrides={"q": pl.Float64, "px": pl.Float64}); per.append(dict(coin=c, design=d, takeovers=t.height, ntl_k=round(float(tkntl(t).sum()) / 1e3, 1) if t.height else 0.0, adl=c in NOX))
P = pl.DataFrame(per).pivot(on="design", index=["coin", "adl"], values="ntl_k").sort("today", descending=True)
print(P.head(20)); P.write_csv(f"{OUTD}/joint_{DAY}_coins.csv")
if os.environ.get("REG"):
    registry.maybe_record([dict(r, case=f"{DAY} {r['design']}", design={"today": "current", "lead": "package_m_int"}[r["design"].split("_")[0]] + r["design"][len(r["design"].split("_")[0]):]) for r in rows],
                          kind="joint_replay", command="ec2/days_launch.sh (DAYS_DES='today lead' X_COINS=... CONTAGION=1); python sim/score/joint_eval.py")
