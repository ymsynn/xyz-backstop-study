"""Phase 2a: per-account state for one HIP-3 coin, replayed block by block from the 00:02 snapshot.

State per user: position Q (signed), entry E, margin mode, leverage, isolated margin M (isolated positions only).
Events: real fills (fills tape, including liquidation rounds and backstop transfers), funding, updateIsolatedMargin,
updateLeverage. Undocumented accounting rules are switches (RULES below) and are scored against the ledger's
backstop-takeover records (position size and account value of the liquidated isolated account at takeover).

Usage: python clearinghouse.py TABLES SNAP_GLOB FILLS COIN ASSET MAXLEV [rule=value ...]
"""
import sys, json, collections, statistics
import polars as pl

T, SNAP, FILLS, COIN, ASSET, MAXLEV = sys.argv[1:7]
ASSET, MAXLEV = int(ASSET), float(MAXLEV)
RULES = dict(fee_iso="1",            # fill fee paid from isolated margin
             reduce="prop_after",    # voluntary reduce: prop_after (M=(M+pnl)*Qn/Qo) | prop_before | keep (M+=pnl)
             liq_reduce="keep",      # market-liquidation rounds: keep (M+=pnl) | prop_after
             lev_change="none",      # updateLeverage on an open isolated position: none | adjust (M += N/new - N/old)
             open_px="fill")         # margin posted on adds: notional at fill px / leverage
for kv in sys.argv[7:]:
    k, v = kv.split("="); RULES[k] = v
MMR = 1 / (2 * MAXLEV)

blocks = pl.read_parquet(f"{T}/blocks.parquet").select("h", (pl.col("t").cast(pl.Int64) // 10**6).alias("ms"))
h_of_ms = dict(zip(blocks["ms"].to_list(), blocks["h"].to_list()))
snap_files = sorted(__import__("glob").glob(SNAP))
snap_block = int(snap_files[0].split("/")[-1].split("_")[0])

# ---- initial state from the snapshot (isolated margin solved from the liquidation price; exact for single-tier MM)
st = {}
s = pl.read_parquet(SNAP).filter(pl.col("market") == COIN)
for r in s.iter_rows(named=True):
    Q = float(r["size"]); E = float(r["entry_price"]); lp = r["liquidation_price"]; iso = r["leverage_type"] == "isolated"
    M = None
    if iso and lp is not None and Q != 0:
        sd = 1 if Q > 0 else -1; lp = float(lp)
        M = abs(Q) * (MMR * lp - sd * (lp - E))
    st[r["user"]] = dict(Q=Q, E=E, M=M, iso=iso, lev=float(r["leverage"]), known=True, mode=r["account_mode"])

# ---- events, keyed (h, order) : 0 state actions, 1 fills, 2 funding
ev = []
sa = pl.read_parquet(f"{T}/state.parquet").filter(pl.col("asset") == ASSET, pl.col("ok"), pl.col("h") > snap_block)
for h, b, i, u, ty, fields in sa.select("h", "b", "i", "u", "type", "fields").iter_rows():
    ev.append((h, 0, b, i, ty, u, json.loads(fields)))
f = (pl.scan_parquet(FILLS).filter(pl.col("coin") == COIN).collect()
     .with_columns(pl.col("timestamp").cast(pl.Int64).replace_strict(h_of_ms, default=None).alias("h"))
     .filter(pl.col("h") > snap_block).sort("h", "trade_id"))
for r in f.select("h", "address", "side", "price", "size", "fee", "realized_pnl", "direction", "liquidation_method", "start_position", "liquidation_mark_px").iter_rows():
    ev.append((r[0], 1, 0, 0, "fill", r[1], r))
fu = pl.read_parquet(f"{T}/funding.parquet").filter(pl.col("h") > snap_block)
for h, u, amt in fu.select("h", "user", "amount").iter_rows():
    ev.append((h, 2, 0, 0, "funding", u, amt))
ev.sort(key=lambda e: e[:4])
LL = pl.read_parquet(f"{T}/liq_ledger.parquet")
ledger = {(r[0], r[1]): (r[2], r[3], r[4]) for r in LL.select("h", "user", "account_value", "szi", "leverage_type").iter_rows()}

import os, statistics as _st
MARKS = {}
if os.environ.get("ORC_LOG"):
    for h, m1, m2, bid, ask, last in pl.read_parquet(os.environ["ORC_LOG"]).sort("h", "b", "i").select("h", "m1", "m2", "bid", "ask", "last").iter_rows():
        if None not in (bid, ask, last):
            MARKS[h] = _st.median([m1, m2, _st.median([bid / 1e6, ask / 1e6, last / 1e6])])
    for h in MARKS:
        ev.append((h, 1.5, 0, 0, "mark", None, MARKS[h]))      # after the block's user fills, before its liquidation fills
    for e in list(ev):
        pass
    ev = [(e[0], 1.6, e[2], e[3], e[4], e[5], e[6]) if (e[4] == "fill" and e[6][8] is not None) else e for e in ev]
    ev.sort(key=lambda e: e[:4])
first_trig = {}            # user -> (h, eq/ntl, below 2/3 MM)
res = []
chk = collections.Counter()
for h, kind, b, i, ty, u, x in ev:
    if ty == "mark":
        for uu, dd in st.items():
            if dd["Q"] != 0 and dd["iso"] and dd["M"] is not None and uu not in first_trig:
                N = abs(dd["Q"]) * x; eq = dd["M"] + (x - dd["E"]) * dd["Q"]
                if eq < MMR * N:
                    first_trig[uu] = (h, eq / N, eq < (2 / 3) * MMR * N)
        continue
    d = st.get(u)
    if d is None:
        d = st[u] = dict(Q=0.0, E=0.0, M=None, iso=None, lev=MAXLEV, known=False, mode=None)
    if ty == "updateLeverage":
        newlev = float(x["leverage"]); iso_new = not x["isCross"]
        if d["Q"] != 0 and d["iso"] and iso_new and RULES["lev_change"] == "adjust" and d["M"] is not None:
            N = abs(d["Q"]) * d["E"]
            d["M"] += N / newlev - N / d["lev"]
        if d["Q"] == 0:
            d["iso"] = iso_new
            d["M"] = 0.0 if iso_new else None
        d["lev"] = newlev
    elif ty == "updateIsolatedMargin":
        if d["M"] is not None:
            d["M"] += x["ntli"] / 1e6
    elif ty == "funding":
        if d["M"] is not None and d["iso"]:
            d["M"] += x
    elif ty == "fill":
        _, _, side, px, sz, fee, rpnl, direction, lmeth, startpos, lmark = x
        px, sz, fee, rpnl = float(px), float(sz), float(fee), float(rpnl)
        sgn = 1 if side == "buy" else -1
        if direction and direction.startswith("Liquidated") and lmeth == "backstop":
            # takeover: compare the replayed equity with the ledger's account value, then hand the position over
            led = ledger.get((h, u))
            mk = float(lmark)
            if d["M"] is not None and led is not None and led[2] == "Isolated":
                eq = d["M"] + (mk - d["E"]) * d["Q"]
                res.append(dict(user=u, h=h, sim_Q=d["Q"], led_Q=led[1], sim_eq=eq, led_eq=led[0], ntl=abs(d["Q"]) * mk, known=d["known"], mode=d["mode"], n_open_fills=d.get("n_open", 0)))
            d.update(Q=0.0, E=0.0, M=(0.0 if d["iso"] else None))
            continue
        if d["iso"] is None:
            d["iso"] = bool(direction and "Isolated" in direction)
            d["M"] = 0.0 if d["iso"] else None
        Q0 = d["Q"]; Q1 = Q0 + sgn * sz
        if d["M"] is not None and RULES["fee_iso"] == "1":
            d["M"] -= fee
        if Q0 == 0 or (Q0 > 0) == (sgn > 0):                      # open / add
            d["n_open"] = d.get("n_open", 0) + 1
            d["E"] = (abs(Q0) * d["E"] + sz * px) / abs(Q1)
            if d["M"] is not None:
                d["M"] += sz * px / d["lev"]
        else:                                                     # reduce (maybe flip)
            red = min(sz, abs(Q0)); pnl = (px - d["E"]) * red * (1 if Q0 > 0 else -1)
            rule = RULES["liq_reduce"] if lmeth == "market" else RULES["reduce"]
            if d["M"] is not None:
                rem = abs(Q0) - red
                if rule == "keep":
                    d["M"] += pnl
                elif rule == "prop_before":
                    d["M"] = d["M"] * rem / abs(Q0) + pnl
                else:
                    d["M"] = (d["M"] + pnl) * rem / abs(Q0)
            if sz > abs(Q0):                                      # flip
                d["E"] = px
                if d["M"] is not None:
                    d["M"] += (sz - abs(Q0)) * px / d["lev"]
        d["Q"] = Q1 if abs(Q1) > 1e-9 else 0.0
        if d["Q"] == 0:
            d["E"] = 0.0
            if d["M"] is not None:
                d["M"] = 0.0

R = pl.DataFrame(res)
R = R.with_columns((pl.col("sim_eq") - pl.col("led_eq")).alias("err"), ((pl.col("sim_Q") - pl.col("led_Q")).abs() < 1e-6).alias("Q_ok"))
R = R.with_columns((pl.col("err").abs() / pl.col("ntl") * 1e4).alias("err_bp"))
print("RULES", RULES)
print(f"isolated takeovers scored {R.height}  position exact {R['Q_ok'].mean():.1%}")
for lab, sub in [("all", R), ("in snapshot", R.filter(pl.col("known"))), ("opened after snapshot", R.filter(~pl.col("known")))]:
    if sub.height:
        print(f"  {lab:24s} n={sub.height:4d}  |equity err| median ${sub['err'].abs().median():9.2f}  p90 ${sub['err'].abs().quantile(0.9):10.2f}"
              f"  within $1: {(sub['err'].abs() < 1).mean():.0%}  within 1bp of ntl: {(sub['err_bp'] < 1).mean():.0%}")
print(R.filter(pl.col("known")).group_by("mode").agg(pl.len(), pl.col("err").abs().median().alias("med_abs_err"), (pl.col("err").abs() < 1).mean().alias("within_1"), pl.col("err").median().alias("med_err")))
print(R.with_columns((pl.col("n_open_fills") > 0).alias("added_after_snap")).group_by("known", "added_after_snap").agg(pl.len(), pl.col("err").abs().median(), (pl.col("err").abs() < 1).mean().alias("within_1"), pl.col("err").median().alias("med_signed")))
R.write_parquet(sys.argv[0].replace("clearinghouse.py", "") + "/takeover_check.parquet") if False else None
if MARKS:
    real = (f.filter(pl.col("liquidation_method").is_not_null(), pl.col("direction").str.contains("Isolated") | (pl.col("liquidation_method") == "market"))
            .group_by("address").agg(pl.col("h").min().alias("h_real"), pl.col("liquidation_method").sort_by("h").first().alias("first_method")))
    iso_users = {uu for uu, dd in st.items() if dd["iso"]}
    real = real.filter(pl.col("address").is_in(list(iso_users)))
    P = pl.DataFrame([dict(address=k, h_sim=v[0], eq_pct=v[1], sim_backstop_first=v[2]) for k, v in first_trig.items()]) if first_trig else pl.DataFrame()
    J = real.join(P, on="address", how="full", coalesce=True)
    J = J.with_columns((pl.col("h_sim") - pl.col("h_real")).alias("dh"))
    both = J.filter(pl.col("h_real").is_not_null(), pl.col("h_sim").is_not_null())
    print(f"\nLIQUIDATION TRIGGERS (isolated): real liquidated {real.height}, sim triggered {P.height}, both {both.height}")
    print(f"  same block {(both['dh'] == 0).mean():.1%}   within 1 relayer update (|dh|<=45 blocks) {(both['dh'].abs() <= 45).mean():.1%}   sim early {(both['dh'] < -45).mean():.1%}  sim late {(both['dh'] > 45).mean():.1%}")
    print("  real liquidated but sim never triggered:", J.filter(pl.col("h_sim").is_null(), pl.col("h_real").is_not_null()).height,
          "| sim triggered but never liquidated:", J.filter(pl.col("h_real").is_null(), pl.col("h_sim").is_not_null()).height)
    print("  first action: real backstop-first", both.filter(pl.col("first_method") == "backstop").height, " sim backstop-first", both["sim_backstop_first"].sum(),
          " agree", (both["sim_backstop_first"] == (both["first_method"] == "backstop")).mean())
    J.write_parquet(os.environ.get("TRIG_OUT", "/dev/null")) if os.environ.get("TRIG_OUT") else None
w = R.filter(pl.col("user").str.starts_with("0x30afce"))
if w.height:
    print("  whale: sim equity", round(w["sim_eq"][0], 2), "ledger", w["led_eq"][0], "Q", w["sim_Q"][0], "vs", w["led_Q"][0])
