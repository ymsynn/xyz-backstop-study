"""Backstop vault capital: how much the xyz backstop liquidator (0x4000...0001) needs so that it never falls below the
maintenance margin of what it holds (C_MM: below it the vault is itself liquidated, and what it cannot cover goes to ADL)
or below zero (C_ADL: HL's ADL trigger, "a user's account value ... becomes negative").

Per event, from the vault's fills and the mark path:
  inventory q_t, equity V_t = cash_t + q_t * mark_t (relative to the vault's value just before the event; a takeover fill at
  the transfer price brings the trader's remaining margin with it), MM_t = |q_t| mark_t / (2 maxLev)
  C_MM = max_t (MM_t - V_t),  C_ADL = max_t (-V_t)
Events:
  real (today's rules): the vault's own fills (data/bs_fills.json) with the real relayer path (extract oracle tables) and the
  last trade (fills tape) as the mark's book term; capital at the time from the vault's ledger and fills before the event
  replay: VAULT_LOG + ORC_OUT of archive/sim/package_runs.sh (today, pkgv) on the three crashes. The replay's unwind is a policy, so
  these are model numbers (reporting rule: no scenario vault PnL as a result; reported as capital need with the path's
  peak margin and drawdown, next to the real events)
OI: long-side notional per market from the morning snapshot of the event day (data/xyzdata/snap{day}); all xyz markets too.
Writes data/scen/vault_capital.csv and data/scen/vault_capital_oi.csv. Usage: python sim/study/vault_capital.py
"""
import glob, json, os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
S = f"{ROOT}/data/scen"
V = "0x4000000000000000000000000000000000000001"
ML = {u["name"]: u["maxLeverage"] for u in json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]}
med3 = lambda a, b, c: pl.max_horizontal(pl.min_horizontal(a, b), pl.min_horizontal(pl.max_horizontal(a, b), c))


def oi_of(day):
    f = sorted(glob.glob(f"{ROOT}/data/xyzdata/snap{day}/*.parquet"))[0]
    x = pl.read_parquet(f).filter(pl.col("size") > 0)
    return x.group_by("market").agg(pl.col("notional").sum().alias("oi")), int(os.path.basename(f).split("_")[1].split(".")[0])


def path(fills, marks, coins):
    """fills: ms, coin, q (signed), px; marks: ms, coin, mark. Returns per-event-time V, MM, inventory notional."""
    ev = fills.sort("ms")
    out = []
    q = {c: 0.0 for c in coins}; cash = 0.0
    mk = {c: marks.filter(pl.col("coin") == c).sort("ms") for c in coins}
    times = sorted(set(ev["ms"].to_list()) | set(marks["ms"].to_list()))
    fi = 0; evl = ev.to_dicts()
    last = {c: None for c in coins}
    mi = {c: 0 for c in coins}; ma = {c: (mk[c]["ms"].to_list(), mk[c]["mark"].to_list()) for c in coins}
    for t in times:
        while fi < len(evl) and evl[fi]["ms"] <= t:
            r = evl[fi]; q[r["coin"]] += r["q"]; cash -= r["q"] * r["px"]; fi += 1
        for c in coins:
            ts, vs = ma[c]
            while mi[c] < len(ts) and ts[mi[c]] <= t: last[c] = vs[mi[c]]; mi[c] += 1
        if any(last[c] is None for c in coins): continue
        val = cash + sum(q[c] * last[c] for c in coins)
        mm = sum(abs(q[c]) * last[c] * 0.5 / ML.get(c, 10) for c in coins)
        inv = sum(abs(q[c]) * last[c] for c in coins)
        out.append((t, val, mm, inv))
    return pl.DataFrame(out, schema=["ms", "V", "MM", "inv"], orient="row")


def summarize(p):
    need = p["MM"] - p["V"]
    return dict(c_mm=max(0.0, float(need.max())), c_adl=max(0.0, float((-p["V"]).max())), peak_mm=float(p["MM"].max()),
                peak_inventory_musd=round(float(p["inv"].max()) / 1e6, 2), worst_equity=float(p["V"].min()))


rows = []
# ---------------------------------------------------------------- real events (today's rules), the vault's own fills
bf = pl.DataFrame(json.load(open(f"{ROOT}/data/bs_fills.json"))).with_columns(
    ms=pl.col("time").cast(pl.Int64), px=pl.col("px").cast(float), sz=pl.col("sz").cast(float), q=pl.when(pl.col("side") == "B").then(pl.col("sz").cast(float)).otherwise(-pl.col("sz").cast(float)),
    pnl=pl.col("closedPnl").cast(float) - pl.col("fee").cast(float))
led = json.load(open(f"{ROOT}/data/bs_ledger.json"))
dep = [(x["time"], float(x["delta"]["amount"]) if x["delta"]["type"] == "hip3LiquidatorDeposit" else float(x["delta"].get("usdcValue", x["delta"].get("amount", 0)))) for x in led]
REAL = [("SKHX 07-27", "0727", ["xyz:SKHX", "xyz:SKHY"], 1785192600000, 1785196200000),
        ("GOOGL 10-28", "1028", ["xyz:GOOGL"], 1793217300000, 1793226000000),
        ("INTC 10-29", "1029", ["xyz:INTC"], 1793303700000, 1793312400000),
        ("AMZN 10-29", "1029", ["xyz:AMZN"], 1793303700000, 1793312400000)]
for name, day, coins, t0, t1 in REAL:
    f = bf.filter(pl.col("coin").is_in(coins), pl.col("ms").is_between(t0, t1)).select("ms", "coin", "q", "px")
    o = (pl.read_parquet(f"{ROOT}/data/extract{day}/tables/oracle.parquet").filter(pl.col("coin").is_in(coins))
         .select("coin", ms=pl.col("t").dt.epoch("ms"), m1="m1", m2="m2").filter(pl.col("ms").is_between(t0 - 60_000, t1)).sort("ms"))
    tr = (pl.scan_parquet(f"{ROOT}/data/xyzdata/all{day}.parquet").filter(pl.col("coin").is_in(coins), pl.col("timestamp").dt.epoch("ms").is_between(t0 - 60_000, t1))
          .select("coin", ms=pl.col("timestamp").dt.epoch("ms"), last=pl.col("price").cast(float)).sort("ms").collect())
    mk = o.join_asof(tr, on="ms", by="coin", strategy="backward").with_columns(mark=med3(pl.col("m1"), pl.col("m2"), pl.col("last").fill_null(pl.col("m1")))).select("ms", "coin", "mark")
    p = path(f, mk, coins)
    cap = sum(a for t, a in dep if t < t0) + float(bf.filter(pl.col("ms") < t0)["pnl"].sum())
    oi, _ = oi_of(day)
    oi_m = float(oi.filter(pl.col("market").is_in(coins))["oi"].sum())
    adl = pl.scan_parquet(f"{ROOT}/data/xyzdata/all{day}.parquet").filter(pl.col("direction") == "Auto-Deleveraging", pl.col("coin").is_in(coins)).select((pl.col("price").cast(float) * pl.col("size").cast(float)).sum()).collect().item()
    rows.append(dict(design="current", case=f"{name} (real vault)", coins=",".join(c[4:] for c in coins), oi_musd=round(oi_m / 1e6, 2), capital_then=round(cap),
                     adl_musd=round((adl or 0) / 1e6, 2), **summarize(p)))
# ---------------------------------------------------------------- replay (today, pkgv), VAULT_LOG + ORC_OUT
SIM = [("GOOGL 10-28", "1028", "GOOGL", "prep_GOOGL_1028"), ("INTC 10-29", "1029", "INTC", "prep_INTC_1029"), ("AMZN 10-29", "1029", "AMZN", "prep_AMZN_1029")]
for pk, des in (("today", "current"), ("pkgv", "package_v"), ("pkgk", "package_k")):
    for name, day, c, prep in SIM:
        lf, of = f"{S}/pkg/log_{c}_pk_{pk}.csv", f"{S}/pkg/orc_{c}_{pk}.csv"
        if not (os.path.exists(lf) and os.path.exists(of)):
            print(f"vault_capital: no replay of {name} under {pk} ({lf}): skipped", file=sys.stderr); continue
        b = pl.read_ipc(f"{ROOT}/data/{prep}/blocks.arrow").select("h", "ms")
        f = (pl.read_csv(lf).join(b, on="h").select("ms", coin=pl.lit(f"xyz:{c}"), q=pl.when(pl.col("buy") == 1).then(pl.col("sz")).otherwise(-pl.col("sz")), px="px"))
        o = pl.read_csv(of).drop_nulls(["bid", "ask", "last"]).select("ms", coin=pl.lit(f"xyz:{c}"), mark=med3(pl.col("m1"), pl.col("m2"), med3(pl.col("bid"), pl.col("ask"), pl.col("last"))) / 1e6)
        p = path(f, o, [f"xyz:{c}"])
        oi, _ = oi_of(day)
        rows.append(dict(design=des, case=f"{name} (replay)", coins=c, oi_musd=round(float(oi.filter(pl.col("market") == f"xyz:{c}")["oi"].sum()) / 1e6, 2),
                         capital_then=None, adl_musd=None, **summarize(p)))
r = pl.DataFrame(rows, infer_schema_length=None).with_columns(
    c_mm_pct_oi=(pl.col("c_mm") / (pl.col("oi_musd") * 1e6) * 100).round(2), c_adl_pct_oi=(pl.col("c_adl") / (pl.col("oi_musd") * 1e6) * 100).round(2))
r.write_csv(f"{S}/vault_capital.csv")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(240); pl.Config.set_tbl_cols(14)
print(r.select("design", "case", "oi_musd", "capital_then", "adl_musd", "peak_inventory_musd", "peak_mm", "worst_equity", "c_mm", "c_adl", "c_mm_pct_oi", "c_adl_pct_oi"))
# ---------------------------------------------------------------- all-markets OI
ois = []
for day in ("0727", "1020", "1021", "1028", "1029"):
    oi, ms = oi_of(day)
    ois.append(dict(day=day, markets=oi.height, total_oi_musd=round(float(oi["oi"].sum()) / 1e6, 1), largest=oi.sort("oi", descending=True)["market"][0],
                    largest_oi_musd=round(float(oi["oi"].max()) / 1e6, 1)))
oid = pl.DataFrame(ois); oid.write_csv(f"{S}/vault_capital_oi.csv"); print(oid)
registry.maybe_record(r.to_dicts(), kind="vault_capital", command="python sim/study/vault_capital.py")
# ---------------------------------------------------------------- the capital rule: worst observed share of OI x OI at risk
# OI at risk = OI of the markets that can gap together (a single market up to all of them); shares from the replays (today:
# matched by the real vault) and SKHX's real need; xyz-wide OI from the latest snapshot
latest = oid.sort("day")[-1].to_dicts()[0]
tot, big = latest["total_oi_musd"] * 1e6, max(o["largest_oi_musd"] for o in ois) * 1e6
rule = []
for des in ("current", "package_v"):
    x = r.filter(pl.col("design") == des)
    cm, ca = float(x["c_mm_pct_oi"].max()) / 100, float(x["c_adl_pct_oi"].max()) / 100
    for lab, oi_r in (("largest single market", big), ("25% of xyz OI", 0.25 * tot), ("50% of xyz OI", 0.5 * tot), ("all xyz OI", tot)):
        rule.append(dict(design=des, oi_at_risk=lab, oi_at_risk_musd=round(oi_r / 1e6, 1), worst_share_mm_pct=round(cm * 100, 2), worst_share_adl_pct=round(ca * 100, 2),
                         capital_mm_musd=round(cm * oi_r / 1e6, 2), capital_adl_musd=round(ca * oi_r / 1e6, 2)))
ru = pl.DataFrame(rule); ru.write_csv(f"{S}/vault_capital_rule.csv"); print(ru)
