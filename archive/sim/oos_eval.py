"""Out-of-sample scoring: today vs package_v, unchanged, on coin-days never used to design it (ec2/oos_job.sh).

Inputs (from s3://.../backstop/oos/ into data/scen/oos/): results/{tk,rd,log,orc}_{COIN}_{DAY}_{today,pkgv}.csv, run_*.log,
logs/pipe_{COIN}_{DAY}.log (prep + real-parameter validation). Blocks are timed by the relayer updates of the run's mark
dump (h -> ms as of the last update, <= ~3 s), which is enough to read E at takeover.
Per coin-day: parity at real parameters (from the pipeline's validation run), then for each rule set the crash metrics of
package_eval (inherited, value at takeover vs E, underwater, book-liquidated accounts, vault exposure, sold below E) and the
vault capital need of vault_capital (C_MM, C_ADL as % of the market's long OI from the day's snapshot, if present).
Records registry test `oos` (REG=oos). Usage: python sim/oos_eval.py
"""
import glob, json, os, re, sys
import numpy as np
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
O = os.environ.get("OOS_DIR", f"{ROOT}/data/scen/oos")
ML = {u["name"]: u["maxLeverage"] for u in json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]}
med3 = lambda a, b, c: pl.max_horizontal(pl.min_horizontal(a, b), pl.min_horizontal(pl.max_horizontal(a, b), c))
OI = json.load(open(f"{O}/oi.json")) if os.path.exists(f"{O}/oi.json") else {}


def parity(c, day):
    f = f"{O}/logs/pipe_{c}_{day}.log"
    if not os.path.exists(f): return {}
    s = open(f).read().split("== validation")[-1]
    g = lambda pat: (re.search(pat, s).group(1) if re.search(pat, s) else None)
    return dict(mark_exact=g(r"mark reproduced at liquidation blocks: (\d+/\d+)"), same_total_filled=g(r"same total filled ([\d.]+)%"),
                tk_both=g(r"takeovers: both (\d+)"), tk_sim_only=g(r"sim only (\d+)"), tk_real_only=g(r"real only (\d+)"),
                tk_ntl=g(r"takeover notional: (sim \$[\d.]+M\s+real \$[\d.]+M)"))


def score(c, day, pk):
    n = f"{c}_{day}_{pk}"
    if not os.path.exists(f"{O}/orc_{n}.csv"): return None
    orc = pl.read_csv(f"{O}/orc_{n}.csv").sort("h")
    E = orc.filter(pl.col("ext") > 0).select("ms", (pl.col("ext") / 1e6).alias("E")).sort("ms")
    hm = orc.select("h", "ms").sort("h")
    tk = pl.read_csv(f"{O}/tk_{n}.csv")
    tk = (tk.sort("h").join_asof(hm, on="h").sort("ms").join_asof(E, on="ms")
          .with_columns(ntl=pl.col("q").abs() * pl.col("px"), val=pl.col("q") * (pl.col("E") - pl.col("px")))) if tk.height else tk
    rd = pl.read_csv(f"{O}/rd_{n}.csv").filter(pl.col("sim_rounds") > 0)
    lg = pl.read_csv(f"{O}/log_{n}.csv") if os.path.exists(f"{O}/log_{n}.csv") and os.path.getsize(f"{O}/log_{n}.csv") > 20 else None
    out = dict(coin=c, day=day, design={"today": "current", "pkgv": "package_v", "pkgk": "package_k", "pkgb": "package_b", "pkgm": "package_m", "pkgm050": "package_m_cap050", "pkgm100": "package_m_cap100", "pkgm200": "package_m_cap200", "pkgmint": "package_m_int"}[pk], takeovers=tk.height,
               inherited_musd=round(float(tk["ntl"].sum()) / 1e6, 3) if tk.height else 0.0,
               value_vs_E=round(float(tk["val"].sum())) if tk.height else 0, underwater=int((tk["val"] < 0).sum()) if tk.height else 0,
               book_liq_accounts=rd.height)
    if lg is not None and lg.height:
        mk = orc.drop_nulls(["bid", "ask", "last"]).select("ms", (med3(pl.col("m1"), pl.col("m2"), med3(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6).alias("mark"))
        f = (lg.sort("h").join_asof(hm, on="h").sort("ms").join_asof(E, on="ms")
             .with_columns(q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz"))))
        uw = f.filter(pl.col("kind") == 1)
        out["sold_below_E_musd"] = round(float(uw.filter(((pl.col("q") < 0) & (pl.col("px") < pl.col("E"))) | ((pl.col("q") > 0) & (pl.col("px") > pl.col("E")))).select((pl.col("sz") * pl.col("px")).sum()).item()) / 1e6, 3)
        # vault equity path at the mark, and its capital need (vault_capital.py's definition)
        ev = f.select("ms", "q", "px").to_dicts(); mm = mk.to_dicts()
        q = cash = 0.0; i = 0; need = adl = 0.0; expo = 0.0; last_t = None
        for m in mm:
            while i < len(ev) and ev[i]["ms"] <= m["ms"]:
                q += ev[i]["q"]; cash -= ev[i]["q"] * ev[i]["px"]; i += 1
            V = cash + q * m["mark"]; MMv = abs(q) * m["mark"] * 0.5 / ML.get(f"xyz:{c}", 10)
            need = max(need, MMv - V); adl = max(adl, -V)
            if last_t is not None: expo += abs(q) * m["mark"] * (m["ms"] - last_t) / 60_000
            last_t = m["ms"]
        oi = OI.get(f"{c}_{day}")
        out.update(vault_exposure_musd_min=round(expo / 1e6, 2), c_mm=round(need), c_adl=round(adl),
                   c_mm_pct_oi=round(need / oi * 100, 3) if oi else None, c_adl_pct_oi=round(adl / oi * 100, 3) if oi else None)
    return out


rows, par = [], []
for f in sorted(glob.glob(f"{O}/orc_*_today.csv")):
    c, day = os.path.basename(f)[4:-10].rsplit("_", 1)
    par.append(dict(coin=c, day=day, **parity(c, day)))
    for pk in ("today", "pkgv", "pkgk", "pkgb", "pkgm", "pkgm050", "pkgm100", "pkgm200", "pkgmint"):
        r = score(c, day, pk)
        if r: rows.append(r)
pl.Config.set_tbl_rows(60); pl.Config.set_tbl_width_chars(250); pl.Config.set_tbl_cols(20)
P = pl.DataFrame(par, infer_schema_length=None); R = pl.DataFrame(rows, infer_schema_length=None)
print("== parity at real parameters"); print(P)
print("== today vs package_v"); print(R)
tot = R.group_by("design").agg(pl.col("inherited_musd", "value_vs_E", "underwater", "book_liq_accounts", "takeovers").sum())
print(tot)
R.write_csv(f"{O}/oos_scores.csv"); P.write_csv(f"{O}/oos_parity.csv")
registry.maybe_record(R.to_dicts(), kind="oos", command="python sim/oos_eval.py")
