"""Cross (and unified) account collateral outside the simulated coin: X(t) per account, for the clearing.

Usage: python crossacc.py PREP_DIR GLOBAL_DIR MISC_DIR XYZ_META COIN GLOBAL_NEXT_DIR ORACLE_PARQUET [MAX_FILLS]
Marks of the other coins, as of each moment (no lookahead): xyz coins median(m1, m2, last trade) at every relayer update
(ORACLE_PARQUET, the extract's oracle table: all xyz coins); other dexes' coins the last trade (per second). X is
re-evaluated every minute, and at every relayer update while the account is within CROSS_DANGER (default 2) times its
maintenance margin: HL liquidates a cross account at the update where the sum over its coins crosses MM (AMZN
0x05cc5c9c: eq < MM first at 13:32:28.689, the second of its real liquidation; per-minute marks missed it).

Fitted on the 18 real GOOGL cross liquidations of 2026-10-28 (account value at liquidation, misc ledger): 16 within $1,
14 to the cent. For an xyz cross account,
    account value = trading cash + sum over cross positions of q * mark - equity of isolated positions
    trading cash  = snapshot account value - sum q0 * mark0, then - buy / + sell notional, - fees, + funding (cross
                    positions only: an isolated position's funding moves its isolated margin), + USDC
                    transfers (send / spotTransfer / internal / subaccount / deposit / withdraw / vault)
unified (and unknown, i.e. new) accounts count every perp dex; standard accounts count the xyz dex only; portfolio-margin
accounts are left out (margined portfolio-wide). Isolated
equity = margin (snapshot: from the liquidation price; increases: notional / leverage; isolated-only assets at max
leverage) + unrealized PnL. Snapshot account values are equity at snapshot marks.

The clearing tracks COIN itself (its m - e*q evolves exactly like trading cash), so this script writes the rest:
    acc_x.arrow    u, x0      X at the snapshot (the clearing starts the account at m = x0 + e0*q0)
    acc_xev.arrow  h, u, dx   changes of X (other coins' fills, marks every minute, funding, transfers), by block
                   pre: another coin's liquidation fills (written one block late) on a coin HL liquidates before COIN
                   (lower xyz asset index): the clearing applies them before this coin's equity stop (AMZN 0xea3ce3e9:
                   INTC and AMZN rounds in one block, HL's AMZN round stopped after 0.006 shares)
Maintenance margin of the other cross positions sharing the collateral (HL's unified ratio: cross MM over all dexes per
collateral token) is tracked too: dmm in acc_xev, mmo0 in acc_x; the clearing tests MM(COIN) + MM(other).
Other coins' margin mode and isolated transfers (state table): a successful updateLeverage switches the coin's mode (an
open cross position moved to isolated takes margin |q| * mark / leverage out of the cross collateral), and
updateIsolatedMargin moves ntli between the cross collateral and the isolated position. The end-of-day validation cannot
see either (account value includes isolated equity): AMZN 0xd8e37894 had reopened GOOGL isolated and topped it up, and was
~$7k richer in cross collateral in the sim than on HL, so the sim never liquidated it.
Other dexes' coins have no action log here: a position reopened from flat takes the margin mode and leverage the next
snapshot shows for it (GOOGL 0x8b2d0bd7 closed a 1x isolated SOL long and reopened it at 10x: margined at 1x it locked
$2.0k instead of $0.2k and sank the account's GOOGL collateral at 03:20).
Spot (HL docs, account abstraction modes): in unified mode each asset's balance backs only cross positions margined in that
asset, so only USDC backs xyz; spot trades against USDC are USDC flows. Accounts absent from account_values start from their
spot USDC balance.
Portfolio margin (HL docs): liquidatable when PMR = (20 + sum of cross MM) / liquidation value > 0.95; liquidation value
counts HYPE / BTC collateral at liquidation thresholds 0.825 / 0.75 (0.5 + 0.5 LTV). The account's liquidation value is
calibrated on the snapshot's pm_ratio (LV0 = (20 + MM0) / pm_ratio0), then moved by flows, perp PnL and collateral prices;
validated on the next snapshot's pm_ratio. pm in acc_x: the clearing applies the PM trigger.
Validation: the next snapshot (GLOBAL_NEXT_DIR, taken at the tape's last block) gives every account's real value at the
end. The reconstruction's end value (X + this coin's part) must match within max($1, min(0.2% of the value,
CROSS_TOL_MM x the peak maintenance margin of the account's position in this coin)) (default 0.25): a large account's
error must stay small against the margin that decides its liquidation here (AMZN 0x4b8600a7: $681 on $2.8M passed 0.2%,
against $490 of AMZN MM, and produced two false takeovers). acc_x.ok marks the accounts that pass; the clearing margins
only those. Unified accounts' spot trades are USDC flows too.
Accounts with more than MAX_FILLS perp fills that day (market makers) are left out (replayed as before).
"""
import sys, os, glob, json, subprocess, collections, bisect, datetime as _dt
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, G, MISC, META, COIN, GN, ORC = sys.argv[1:8]
MAX_FILLS = int(sys.argv[8]) if len(sys.argv) > 8 else 20000
gp = lambda d: glob.glob(f"{G}/{d}/*.parquet")[0]
gn = lambda d: glob.glob(f"{GN}/{d}/*.parquet")[0]          # the same, in the NEXT day's snapshot
users = pl.read_ipc(f"{PREP}/users.arrow")
uid = dict(zip(users["user"], users["uid"]))
blocks = pl.read_ipc(f"{PREP}/blocks.arrow").sort("ms")
bms, bh = blocks["ms"].to_list(), blocks["h"].to_list()
t_end = bms[-1]
snap_file = os.path.basename(gp("perp_all"))
snap_ms = int(snap_file.split("_")[-1].split(".")[0])
meta = json.load(open(META))
ML = {u["name"]: u["maxLeverage"] for u in meta[0]["universe"]}
AIDX = {u["name"]: i for i, u in enumerate(meta[0]["universe"])}   # xyz asset index (HL liquidates a cross account's coins in this order)
ONLYISO = {u["name"] for u in meta[0]["universe"] if u.get("onlyIsolated")}
A2C = {110000 + i: u["name"] for i, u in enumerate(meta[0]["universe"])}
ML.update({"BTC": 40, "ETH": 25, "SOL": 20, "HYPE": 10})          # main-dex defaults (others: 10)

# ---------------------------------------------------------------- accounts: cross on COIN (or trading it), not isolated
pa = pl.scan_parquet(gp("perp_all"))
iso_coin = set(pa.filter((pl.col("market") == COIN) & (pl.col("leverage_type") == "isolated")).select("user").collect()["user"])
# isolated on COIN by any evidence: next snapshot, the real liquidation ledger, leverage / isolated-margin actions
# (a margin mode set on an earlier day persists without showing in the tape)
_tables = os.path.dirname(ORC)
_asset = 110000 + [u["name"] for u in meta[0]["universe"]].index(COIN)
iso_coin |= set(pl.scan_parquet(gn("perp_all")).filter((pl.col("market") == COIN) & (pl.col("leverage_type") == "isolated")).select("user").collect()["user"])
_ll = f"{_tables}/liq_ledger_{COIN.split(':')[1]}.parquet"
if os.path.exists(_ll):
    iso_coin |= set(pl.read_parquet(_ll).filter(pl.col("leverage_type") == "Isolated")["user"])
iso_coin |= set(pl.scan_parquet(f"{_tables}/state.parquet").filter(pl.col("asset") == _asset, pl.col("ok"),
                    (pl.col("type").is_in(["updateIsolatedMargin", "topUpIsolatedOnlyMargin"])) | ((pl.col("type") == "updateLeverage") & pl.col("fields").str.contains('"isCross": false')))
                .select("u").unique().collect()["u"])
traders = set(pl.scan_parquet(gp("fills_raw")).filter(pl.col("coin") == COIN, pl.col("timestamp").cast(pl.Int64) <= t_end)
              .select("address").unique().collect()["address"])
holders = set(pa.filter(pl.col("market") == COIN).select("user").collect()["user"])
cand = (traders | holders) - iso_coin
nf = (pl.scan_parquet(gp("fills_raw")).filter(pl.col("address").is_in(list(cand)), pl.col("asset_class") == "perp")
      .group_by("address").agg(pl.len().alias("n")).collect())
heavy = set(nf.filter(pl.col("n") > MAX_FILLS)["address"])
U = sorted(u for u in cand - heavy if u in uid)
Uset = set(U)
print(f"accounts: {len(U)} (cross on {COIN} or trading it; {len(heavy)} with > {MAX_FILLS} fills left out)", flush=True)

av = pl.scan_parquet(gp("account_values")).filter(pl.col("user").is_in(U), pl.col("dex") == "xyz").select("user", "account_value", "account_mode", "pm_ratio", "pm_total_account_value").collect()
AV0, MODE = dict(zip(av["user"], av["account_value"])), dict(zip(av["user"], av["account_mode"]))
PMR0 = dict(zip(av["user"], av["pm_ratio"]))
_spot0 = pl.scan_parquet(gp("spot")).filter(pl.col("user").is_in(U), pl.col("token").is_in(["USDC", "HYPE", "UBTC", "USDT0"])).select("user", "token", "balance").collect()
SPOT0 = collections.defaultdict(dict)
for _u, _t, _b in _spot0.iter_rows(): SPOT0[_u][_t] = _b
for _u in U:
    if _u not in AV0: AV0[_u] = SPOT0[_u].get("USDC", 0.0)     # new / unknown accounts: their spot USDC
PM_TOK = {"HYPE": ("HYPE", 0.825), "UBTC": ("BTC", 0.75), "USDT0": (None, 1.0)}      # token -> (perp mark, liquidation threshold)
def mmr_of(c): return 0.5 / ML.get(c, 10)
pos0 = pa.filter(pl.col("user").is_in(U)).collect()

# ---------------------------------------------------------------- misc ledger: USDC transfers and funding (one pass)
def tms(s):   # "2026-10-28T19:14:48.922197475" (UTC, ns) -> ms
    return int(_dt.datetime.fromisoformat(s[:26]).replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)
flows = collections.defaultdict(list)      # user -> [(ms, usdc delta)]
fund = collections.defaultdict(list)       # user -> [(ms, coin, amount)]
def lflow(u, d):
    t = d.get("type"); a = 0.0
    if t in ("send", "spotTransfer") and d.get("token", "USDC") == "USDC":
        x = float(d["amount"]); fee = float(d.get("fee", 0) or 0)
        src, dst = d["user"].lower(), d["destination"].lower()
        if src == u and dst == u: return 0.0
        if src == u: a -= x + fee
        if dst == u: a += x
    elif t in ("internalTransfer", "subAccountTransfer"):
        x = float(d.get("usdc", 0))
        if d["user"].lower() == u: a -= x + float(d.get("fee", 0) or 0)
        if d["destination"].lower() == u: a += x
    elif t == "deposit": a += float(d["usdc"])
    elif t == "withdraw": a -= float(d["usdc"]) + float(d.get("fee", 0) or 0)
    elif t == "vaultDeposit": a -= float(d["usdc"])
    elif t == "vaultWithdraw": a += float(d.get("netWithdrawnUsd", d.get("usdc", 0)))
    return a
for fp in sorted(glob.glob(os.path.join(MISC, "*.lz4")), key=lambda p: int(os.path.basename(p).split(".")[0])):
    p = subprocess.Popen(["unlz4", "-c", fp], stdout=subprocess.PIPE)
    for line in p.stdout:
        if b"LedgerUpdate" not in line and b"Funding" not in line:
            continue
        o = json.loads(line)
        for e in o["events"]:
            inn = e["inner"]
            ms = None
            if "Funding" in inn:
                for d in inn["Funding"]["deltas"]:
                    u = d["user"].lower()
                    if u in Uset:
                        ms = ms or tms(e["time"])
                        fund[u].append((ms, d["coin"], float(d["funding_amount"])))
            elif "LedgerUpdate" in inn:
                us = [x.lower() for x in inn["LedgerUpdate"]["users"]]
                hit = [u for u in us if u in Uset]
                if hit:
                    d = inn["LedgerUpdate"]["delta"]
                    ms = tms(e["time"])
                    for u in hit:
                        a = lflow(u, d)
                        if a: flows[u].append((ms, a))
    rc = p.wait()
    # a truncated ledger would silently under-count transfers and funding, and only show up as fewer validated accounts
    if rc: sys.exit(f"crossacc: unlz4 failed on {fp} (exit {rc})")
print("ledger flows", sum(map(len, flows.values())), "funding rows", sum(map(len, fund.values())), flush=True)

# ---------------------------------------------------------------- fills (all dexes), minute marks of the coins involved
F = (pl.scan_parquet(gp("fills_raw")).filter(pl.col("address").is_in(U), (pl.col("asset_class") == "perp") | (pl.col("quote_symbol") == "USDC"),
                                               pl.col("timestamp").cast(pl.Int64) > snap_ms, pl.col("timestamp").cast(pl.Int64) <= t_end)
     .select("address", "coin", "asset_class", "base_symbol", "fee_token", pl.col("timestamp").cast(pl.Int64).alias("ms"), "side", pl.col("price").cast(pl.Float64).alias("px"),
             pl.col("size").cast(pl.Float64).alias("sz"), pl.col("fee").cast(pl.Float64).alias("fee"),
             pl.col("is_liquidation").fill_null(False).alias("liq"))
     .collect().sort("address", "ms", maintain_order=True))
coins = set(F.filter(pl.col("asset_class") == "perp")["coin"].unique()) | set(pos0["market"].unique()) | {COIN, "HYPE", "BTC"}
# every perp trade of the coins involved, once: the heaviest file here, and both tables below come from it
trades = (pl.scan_parquet(gp("fills_raw")).filter(pl.col("coin").is_in(list(coins)), pl.col("asset_class") == "perp")
          .select("coin", pl.col("timestamp").cast(pl.Int64).alias("ms"), pl.col("price").cast(pl.Float64).alias("px"))
          .collect().sort("ms", maintain_order=True))
# last trade per coin and second, valid from the end of that second (no lookahead)
tr = (trades.with_columns(m=pl.col("ms") // 1000 * 1000 + 999)
      .group_by("coin", "m").agg(pl.col("px").last()).sort("coin", "m"))
# xyz coins: every relayer update, mark = median(m1, m2, last trade as of the update)
orc = (pl.scan_parquet(ORC).filter(pl.col("coin").is_in(list(coins)))
       .select("coin", (pl.col("t").cast(pl.Int64) // 10**6).alias("m"), "m1", "m2").collect().sort("coin", "m"))
UPD = sorted(set(orc.filter(pl.col("coin") == COIN)["m"].to_list()))      # relayer update times (all coins update together)
# the exact last trade before each update (HL's mark: median of oracle, m2 and the book; GOOGL at 13:32:28.689 was 283.24)
tr_x = (trades.filter(pl.col("coin").is_in(list(set(orc["coin"].unique()))))
        .select("coin", pl.col("ms").alias("m"), pl.col("px").alias("last"))
        .group_by("coin", "m").agg(pl.col("last").last()).sort("coin", "m"))
orc = (orc.join_asof(tr_x, on="m", by="coin", strategy="backward", allow_exact_matches=False)
       .with_columns(pl.when(pl.col("last").is_not_null()).then(pl.concat_list("m1", "m2", "last").list.median())
                     .otherwise(pl.concat_list("m1", "m2").list.mean()).alias("px")).select("coin", "m", "px"))
xyz_c = set(orc["coin"].unique())
mk = pl.concat([orc, tr.filter(~pl.col("coin").is_in(list(xyz_c)))]).sort("coin", "m", maintain_order=True)
MK = {c: (g["m"].to_list(), g["px"].to_list()) for (c,), g in mk.group_by(["coin"])}
def mark(c, t, default):
    if c not in MK: return default
    ts, ps = MK[c]; i = bisect.bisect_right(ts, t) - 1
    return ps[i] if i >= 0 else default
# the same lookup, cached on the minute grid: every account holding a coin asks for its mark at the same minutes
# (165 million lookups for 6.7 million account steps on GOOGL 2026-10-28). None = no mark yet (the caller's default applies).
_MC = {}
def mark_at(c, t):
    if t % 60000 == 0:
        k = (c, t)
        if k in _MC: return _MC[k]
    if c not in MK: v = None
    else:
        ts, ps = MK[c]; i = bisect.bisect_right(ts, t) - 1
        v = ps[i] if i >= 0 else None
    if t % 60000 == 0: _MC[k] = v
    return v
print("fills", F.height, "coins with marks", len(MK), "relayer updates", len(UPD), flush=True)
_st = (pl.scan_parquet(f"{_tables}/state.parquet").filter(pl.col("u").is_in(U), pl.col("ok"), pl.col("asset") != _asset,
                                                         pl.col("type").is_in(["updateLeverage", "updateIsolatedMargin"]))
       .select("u", (pl.col("t").cast(pl.Int64) // 10**6).alias("ms"), "asset", "type", "fields").collect())
STATE = collections.defaultdict(list)
for _u, _ms, _a, _ty, _f in _st.iter_rows():
    if _a in A2C and snap_ms < _ms <= t_end: STATE[_u].append((_ms, A2C[_a], _ty, json.loads(_f)))
print("margin-mode / isolated-margin actions on other coins:", _st.height, flush=True)
_pn = (pl.scan_parquet(gn("perp_all")).filter(pl.col("user").is_in(U), ~pl.col("market").str.starts_with("xyz:"))
       .select("user", "market", "leverage_type", "leverage").collect())
NEXT_MODE = {(a, m): (lt, float(lv)) for a, m, lt, lv in _pn.iter_rows()}
DANGER = float(os.environ.get("CROSS_DANGER", "2"))
TOL_MM = float(os.environ.get("CROSS_TOL_MM", "0.25"))
avn = pl.scan_parquet(gn("account_values")).filter(pl.col("user").is_in(U), pl.col("dex") == "xyz").select("user", "account_value", "pm_ratio").collect()
AVN = dict(zip(avn["user"], avn["account_value"]))
PMRN = dict(zip(avn["user"], avn["pm_ratio"]))
# accounts absent from the next snapshot with no position left there are empty: real end value 0
_pn_users = set(pl.scan_parquet(gn("perp_all")).filter(pl.col("user").is_in(U)).select("user").unique().collect()["user"])
for _u in U:
    if _u not in AVN and _u not in _pn_users: AVN[_u] = 0.0
# spot exposure: non-USDC spot holdings may back unified accounts (collateral rule not modelled): such accounts are left out
_sp = pl.scan_parquet(gp("spot")).filter(pl.col("user").is_in(U), pl.col("token") != "USDC", pl.col("balance") > 0, pl.col("entry_value") > 1.0).select("user").unique().collect()["user"]
SPOT = set(_sp) | set(F.filter(pl.col("asset_class") != "perp")["address"].unique())
# end marks: the next snapshot's own (position notional / size), so the validation tests the flows, not the mark proxy
pn = (pl.scan_parquet(gn("perp_all")).filter(pl.col("size") != 0)
      .group_by("market").agg((pl.col("notional") / pl.col("size").abs()).median().alias("m")).collect())
MEND = dict(zip(pn["market"], pn["m"]))

def to_h(ms):
    i = bisect.bisect_left(bms, ms)
    return bh[min(i, len(bh) - 1)]

# ---------------------------------------------------------------- X(t) per account
x0_rows, ev_rows = [], []
PATH_WIN = int(os.environ.get("CROSS_PATH_WIN_MS", "120000"))     # a real liquidation within 2 minutes explains it
PATH_TOL = float(os.environ.get("CROSS_PATH_TOL", "1.0"))        # dollars below the line
n_path = 0
Fg = {u: g for (u,), g in F.group_by(["address"])}
Pg = {u: g for (u,), g in pos0.group_by(["user"])}
for u in U:
    mode = MODE.get(u, "unified")
    keep = (lambda c: c.startswith("xyz:")) if mode == "standard" else (lambda c: True)
    Q, LT, E, IM, LEV, M0 = {}, {}, {}, {}, {}, {}
    q0_coin, m0_coin = 0.0, 0.0
    for p in (Pg[u].iter_rows(named=True) if u in Pg else []):
        c = p["market"]
        if not keep(c) or not p["size"]: continue
        m0 = p["notional"] / abs(p["size"])
        if c == COIN:
            q0_coin, m0_coin = p["size"], m0
            continue
        Q[c], LT[c], E[c], M0[c] = p["size"], p["leverage_type"], p["entry_price"], m0
        if p["leverage_type"] == "isolated" and p["liquidation_price"] is not None:
            lp = p["liquidation_price"]; sd = 1 if p["size"] > 0 else -1; mm = 0.5 / ML.get(c, 10)
            IM[c] = abs(p["size"]) * (mm * lp - sd * (lp - p["entry_price"])); LEV[c] = float(p["leverage"])
    cash = AV0.get(u, 0.0) - sum(Q[c] * M0[c] for c in Q) - q0_coin * m0_coin
    pm = mode == "portfolio_margin"
    TOK = {t: SPOT0[u].get(t, 0.0) for t in PM_TOK} if pm else {}
    def tok_val(t):   # PM collateral at liquidation thresholds (stables at 1)
        z = 0.0
        for tk, b in TOK.items():
            pc, thr = PM_TOK[tk]
            z += b * thr * (mark(pc, t, 0.0) if pc else 1.0)
        return z
    def MMO(t, end=False):   # maintenance margin of the other cross positions sharing the collateral
        z = 0.0
        for c, q in Q.items():
            if abs(q) > 1e-12 and LT.get(c) != "isolated":
                m = MEND.get(c, mark(c, t, M0.get(c, 0.0))) if end else mark(c, t, M0.get(c, 0.0))
                z += abs(q) * m * mmr_of(c)
        return z
    def XM(t):
        """X(t) and MMO(t) in one pass over the positions (same terms, same order as the two functions below)"""
        tot = 0.0; z = 0.0
        for c, q in Q.items():
            aq = abs(q)
            if aq < 1e-12: continue
            mv = mark_at(c, t)
            m = mv if mv is not None else M0.get(c, E.get(c, 0.0))
            tot += q * m
            iso = LT.get(c) == "isolated"
            if iso: tot -= IM.get(c, 0.0) + (m - E[c]) * q
            elif aq > 1e-12:
                z += aq * (mv if mv is not None else M0.get(c, 0.0)) * mmr_of(c)
        return cash + tot + (tok_val(t) if pm else 0.0), z
    def iso_eq(t, end=True):
        z = 0.0
        for c, q in Q.items():
            if abs(q) > 1e-12 and LT.get(c) == "isolated":
                m = MEND.get(c, mark(c, t, M0.get(c, E.get(c, 0.0)))) if end else mark(c, t, M0.get(c, E.get(c, 0.0)))
                z += IM.get(c, 0.0) + (m - E[c]) * q
        return z
    def X(t, end=False):
        tot = 0.0
        for c, q in Q.items():
            if abs(q) < 1e-12: continue
            m = MEND.get(c, mark(c, t, M0.get(c, E.get(c, 0.0)))) if end else mark(c, t, M0.get(c, E.get(c, 0.0)))
            tot += q * m
            if LT.get(c) == "isolated": tot -= IM.get(c, 0.0) + (m - E[c]) * q
        return cash + tot + (tok_val(t) if pm else 0.0)
    if pm:
        # PM: X is the liquidation value outside COIN; calibrate on the snapshot ratio (absorbs supply / borrow terms)
        pr0 = PMR0.get(u) or 0.0
        mm0 = 20.0 + MMO(snap_ms) + abs(q0_coin) * m0_coin * mmr_of(COIN)
        lv_model = cash + sum(Q[c] * M0[c] for c in Q) + q0_coin * m0_coin + tok_val(snap_ms) - iso_eq(snap_ms, end=False)
        if pr0 > 1e-4: cash += mm0 / pr0 - lv_model
    x_prev = X(snap_ms); mmo_prev = MMO(snap_ms)
    x0_rows.append((uid[u], x_prev, mmo_prev))
    # event times: own fills, flows, funding, and every minute while other positions are open
    evs = []
    cq, ccash = q0_coin, 0.0          # this coin, for the end-of-tape validation only (the clearing tracks it)
    if u in Fg:
        for r in Fg[u].iter_rows(named=True):
            if r["asset_class"] != "perp":
                if mode != "standard":   # unified / PM: spot trades against USDC move USDC (PM: and the collateral token)
                    s_ = r["sz"] if r["side"] == "buy" else -r["sz"]
                    evs.append((r["ms"], 2 if pm and r["base_symbol"] in PM_TOK else 1,
                                (-s_ * r["px"] - (r["fee"] if r["fee_token"] == "USDC" else 0.0), r["base_symbol"], s_ - (r["fee"] if r["fee_token"] == r["base_symbol"] else 0.0))))
            elif r["coin"] == COIN:
                s_ = r["sz"] if r["side"] == "buy" else -r["sz"]; cq += s_; ccash -= s_ * r["px"] + r["fee"]
                evs.append((r["ms"], 3, (s_, -(s_ * r["px"] + r["fee"]))))   # this coin, as of each moment (danger test only)
            elif keep(r["coin"]): evs.append((r["ms"], 0, r))
    for ms, a in flows.get(u, []):
        if snap_ms < ms <= t_end: evs.append((ms, 1, a))
    for ms, c, a in fund.get(u, []):
        if not (snap_ms < ms <= t_end): continue
        if c == COIN: ccash += a
        elif keep(c): evs.append((ms, 5, (c, a)))   # another coin's funding: its isolated margin if isolated, else cash
    for ms, c, ty, fd in STATE.get(u, []):
        if keep(c): evs.append((ms, 4, (c, ty, fd)))
    evs.sort(key=lambda z: (z[0], z[1]))
    nxt_min = (snap_ms // 60000 + 1) * 60000
    k = 0
    t_last, danger, liq_now, liq_pre = snap_ms, False, False, False
    # path check: the times the account was really liquidated (any coin), and the worst moment where the reconstruction
    # puts it below the takeover line (2/3 of its maintenance margin) with no real liquidation within PATH_WIN
    liq_ms = sorted(r["ms"] for r in (Fg[u].iter_rows(named=True) if u in Fg else []) if r["asset_class"] == "perp" and r["liq"])
    path_bad, path_worst = 0, 0.0
    cq_t, ccash_t = q0_coin, 0.0
    mm_peak = abs(q0_coin) * m0_coin * mmr_of(COIN)
    while True:
        t_ev = evs[k][0] if k < len(evs) else None
        has_pos = any(abs(q) > 1e-12 for q in Q.values())
        t_min = nxt_min if has_pos and nxt_min <= t_end else None
        # near liquidation: every relayer update
        t_up = None
        if has_pos and danger:
            iu = bisect.bisect_right(UPD, t_last)
            if iu < len(UPD) and UPD[iu] <= t_end: t_up = UPD[iu]
        # a relayer update goes before fills stamped at the same ms (marks move first, then the block's fills)
        if t_up is not None and (t_min is None or t_up < t_min) and (t_ev is None or t_up <= t_ev):
            t = t_up
        elif t_ev is None and t_min is None: break
        elif t_min is not None and (t_ev is None or t_min < t_ev):
            t = t_min; nxt_min += 60000
        else:
            t, kind, r = evs[k]; k += 1
            if kind == 3:
                cq_t += r[0]; ccash_t += r[1]
            elif kind == 4:   # another coin's margin mode / isolated margin
                c, ty, fd = r; q0 = Q.get(c, 0.0)
                if ty == "updateLeverage":
                    lev = float(fd.get("leverage", ML.get(c, 10))); iso = not fd.get("isCross", True)
                    if iso and LT.get(c) != "isolated":
                        IM[c] = abs(q0) * mark(c, t, M0.get(c, E.get(c, 0.0))) / lev if abs(q0) > 1e-12 else 0.0
                        if abs(q0) > 1e-12: E.setdefault(c, M0.get(c, 0.0))
                    LT[c] = "isolated" if iso else "cross"; LEV[c] = lev
                elif LT.get(c) == "isolated" and abs(q0) > 1e-12:
                    IM[c] = IM.get(c, 0.0) + float(fd.get("ntli", 0)) / 1e6
            elif kind == 5:   # funding on an isolated position is paid from / into its isolated margin (not cross cash)
                c, a = r
                # X counts an isolated coin as cash + E q - IM (IM came out of cash): funding into the isolated margin
                # raises both, so cross X does not move and account value (X + isolated equity) gains it
                cash += a
                if LT.get(c) == "isolated" and abs(Q.get(c, 0.0)) > 1e-12: IM[c] = IM.get(c, 0.0) + a
            elif kind == 1:
                cash += r if not isinstance(r, tuple) else r[0]
            elif kind == 2:
                cash += r[0]; TOK[r[1]] = TOK.get(r[1], 0.0) + r[2]
            else:
                if r["liq"]:
                    liq_now = True
                    if AIDX.get(r["coin"], 1 << 30) < AIDX.get(COIN, -1): liq_pre = True
                c = r["coin"]; s = r["sz"] if r["side"] == "buy" else -r["sz"]; q0 = Q.get(c, 0.0)
                if abs(q0) < 1e-12 and (u, c) in NEXT_MODE:   # other dex, reopened: the mode it ends the day in
                    LT[c], LEV[c] = NEXT_MODE[(u, c)]; IM[c] = 0.0
                if abs(q0) < 1e-12 and c not in LEV and c in ONLYISO:
                    LT[c] = "isolated"; IM[c] = 0.0; LEV[c] = float(ML.get(c, 10)); E[c] = r["px"]
                if LT.get(c) == "isolated":
                    if abs(q0) < 1e-12 or (q0 > 0) == (s > 0):
                        IM[c] = IM.get(c, 0.0) + abs(s) * r["px"] / LEV.get(c, ML.get(c, 10))
                        E[c] = (abs(q0) * E.get(c, r["px"]) + abs(s) * r["px"]) / abs(q0 + s)
                    else:
                        red = min(abs(s), abs(q0)); IM[c] = IM.get(c, 0.0) * (abs(q0) - red) / abs(q0)
                elif abs(q0) < 1e-12 or (q0 > 0) == (s > 0):   # cross: entry kept too, for a later switch to isolated
                    E[c] = (abs(q0) * E.get(c, r["px"]) + abs(s) * r["px"]) / abs(q0 + s)
                elif abs(s) > abs(q0):
                    E[c] = r["px"]
                Q[c] = q0 + s; M0.setdefault(c, r["px"])
                cash -= s * r["px"] + r["fee"]
                if abs(Q[c]) < 1e-12 and LT.get(c) == "isolated": IM[c] = 0.0
            if t_min is not None and t_min == t: nxt_min += 60000
        t_last = t
        x, mmo = XM(t)
        if abs(x - x_prev) > 0.005 or abs(mmo - mmo_prev) > 0.01:
            # another coin's liquidation fills land one block later: HL liquidates the whole cross account at once, so the
            # engine must test this coin against the state before them (AMZN 0x05cc5c9c, GOOGL and AMZN sold at 13:32:28.689)
            ev_rows.append((to_h(t) + (1 if liq_now else 0), uid[u], x - x_prev, mmo - mmo_prev, liq_pre)); x_prev, mmo_prev = x, mmo
        liq_now = liq_pre = False
        mc = mark(COIN, t, m0_coin)
        mm_peak = max(mm_peak, abs(cq_t) * mc * mmr_of(COIN))
        danger = x + cq_t * mc + ccash_t < DANGER * (mmo + abs(cq_t) * mc * mmr_of(COIN))
        # the same path check for portfolio-margin accounts, on the line the clearing applies to them: liquidation value
        # below 2/3 of (20 + cross MM) / 0.95 (xyz:BRENTOIL 2026-09-10, one PM account: liquidation value $73 at the
        # snapshot, -$24k from the first flow on; it opened a 94.55 short the chain let it keep, and the replay handed it
        # to the vault ten blocks later at a negative price, under every rule set)
        eq_t, req_t = x + cq_t * mc + ccash_t, mmo + abs(cq_t) * mc * mmr_of(COIN)
        if pm and req_t > 0: req_t = (20.0 + req_t) / 0.95
        if req_t > 0 and eq_t < (2.0 / 3.0) * req_t - PATH_TOL:
            il = bisect.bisect_left(liq_ms, t - PATH_WIN)
            if not (il < len(liq_ms) and liq_ms[il] <= t + PATH_WIN):
                path_bad += 1; path_worst = min(path_worst, eq_t - (2.0 / 3.0) * req_t)
    # validation against the next snapshot: X(end) + this coin's position at the end mark + its trading cash
    # snapshot account values include isolated equity; the cross value used for margining (X) does not
    av_end = X(t_end, end=True) + iso_eq(t_end) + cq * MEND.get(COIN, mark(COIN, t_end, m0_coin)) + ccash
    real = AVN.get(u)
    err = (av_end - real) if real is not None else float("nan")
    # portfolio-margin accounts are margined portfolio-wide (their per-dex value can be negative): not modelled here
    ok = real is not None and abs(err) <= max(1.0, min(0.002 * abs(real), TOL_MM * mm_peak))
    # ... and its path must be possible: an account below the takeover line is liquidated by HL at that update. A
    # reconstruction that puts it there while the real account was not being liquidated is wrong on the way, even with
    # the right end value (xyz:CL 2026-11-05, 0x721ee345: +$79 at the snapshot, -$36 half a minute later and for most
    # of the day, +$85 at the end; margined on that path it was taken over 62 times)
    if ok and path_bad > 0: ok = False; n_path += 1
    if pm:   # portfolio margin: validate the ratio itself
        # X already holds the collateral tokens at their thresholds (it is the liquidation value outside COIN), so the end
        # liquidation value is av_end less the isolated equity added for the account-value check; adding tok_val again
        # counted the tokens twice and let a wrong path through
        lv_end = av_end - iso_eq(t_end)
        mm_end = 20.0 + MMO(t_end, end=True) + abs(cq) * MEND.get(COIN, mark(COIN, t_end, m0_coin)) * mmr_of(COIN)
        pr, rr = mm_end / lv_end if lv_end > 0 else 9.9, PMRN.get(u)
        err = (pr - rr) if rr is not None else float("nan")
        ok = rr is not None and abs(err) <= max(0.02, 0.1 * rr)
        if ok and path_bad > 0: ok = False; n_path += 1
    x0_rows[-1] = (uid[u], x0_rows[-1][1], x0_rows[-1][2], pm, ok, err, real if real is not None else float("nan"))
ax = pl.DataFrame(x0_rows, schema={"u": pl.UInt32, "x0": pl.Float64, "mmo0": pl.Float64, "pm": pl.Boolean, "ok": pl.Boolean, "err": pl.Float64, "av_end": pl.Float64}, orient="row")
ax.write_ipc(f"{PREP}/acc_x.arrow")
print("rejected on the path check (below the takeover line with no real liquidation):", n_path)
print("validated at the next snapshot:", ax["ok"].sum(), "of", ax.height,
      "| |err| quantiles:", ax.filter(pl.col("err").is_not_nan()).select(pl.col("err").abs().quantile(q).alias(str(q)) for q in (0.5, 0.9, 0.99)).row(0))
pl.DataFrame(ev_rows, schema={"h": pl.Int64, "u": pl.UInt32, "dx": pl.Float64, "dmm": pl.Float64, "pre": pl.Boolean}, orient="row").sort("h", "u", maintain_order=True).write_ipc(f"{PREP}/acc_xev.arrow")
print("by mode:", ax.join(pl.DataFrame({"u": [uid[x] for x in U], "mode": [MODE.get(x, "new") for x in U]}, schema={"u": pl.UInt32, "mode": pl.String}), on="u")
      .group_by("mode").agg(pl.len(), pl.col("ok").sum()).to_dicts())
print("acc_x", len(x0_rows), "acc_xev", len(ev_rows))
