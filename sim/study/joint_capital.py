"""Vault capital for joint moves: what the xyz backstop vault needs when many xyz markets gap at once, and how much
ADL the isolated-only (noCross) markets would produce in the same moves.

Positions: a morning snapshot of every xyz position (data/xyzdata/snap{DAY}). Moves: every hour of the public 1h candles
of all xyz markets (data/candles/xyz_1h.parquet, sim/study/fetch_candles.py), close to close over W hours (W = 1, 4, 24), plus
two bounds: every market at once at its own worst W-hour move in the adverse direction for its net position side ("each
market like its worst", the old rule's assumption), and the single worst market alone.

Gap model (an instant move, no time for book liquidation; an upper bound on the inheritance at a given move):
  mark P = notional / |size|; MM rate r = mm_buffer / maxLev (0.5 / maxLev, one tier); backstop at 2/3 of MM (HL).
  isolated position: margin m from its liquidation price L (m + q (L - e) = r |q| L), equity m + q (P' - e).
  cross account: equity A + sum_xyz q (P' - P) against requirement sum_xyz r |q| P'. A (the account's value net of what its
    other collateral and positions require) is implied by HL's liquidation price L of its largest xyz position: at P_k = L
    the account sits exactly at MM. The snapshot's account_value is not used: for unified accounts it leaves out spot USDC
    and other dexes. No liquidation price: not liquidatable in this model.
  Below 2/3 of the requirement after the move: taken over. On a market with cross margin the vault inherits the position
  and the account's remaining equity eq'; on a noCross market the position is auto-deleveraged (ADL) instead.
  Vault: C_ADL = max(0, -sum eq'), C_MM = sum (inherited notional / (2 maxLev)) - sum eq' (the vault is itself liquidated
  below the MM of what it holds). noCross: ADL notional, and the shortfall sum max(0, -eq') taken from winners.
Validation: the event-day snapshot with the event's real move against the measured C_ADL of sim/study/vault_capital.py.
Usage: python sim/study/joint_capital.py [DAY=1030]  (REG=joint-capital to record) -> data/scen/joint_capital_{scen,top}.csv"""
import glob, json, os, sys
import numpy as np
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
U = json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]
ML = {u["name"]: u["maxLeverage"] for u in U}
NOX = {u["name"] for u in U if u.get("marginMode") in ("noCross", "strictIsolated")}
MMB, BSF = 0.5, 2.0 / 3.0


def positions(day):
    f = sorted(glob.glob(f"{ROOT}/data/xyzdata/snap{day}/*.parquet"))[0]
    s = pl.read_parquet(f).filter(pl.col("size") != 0, pl.col("market").is_in(list(ML)))
    s = s.with_columns(P=pl.col("notional") / pl.col("size").abs(), r=MMB / pl.col("market").replace_strict(ML, return_dtype=pl.Float64),
                       nox=pl.col("market").is_in(list(NOX)))
    return s, f


class Book:
    """Vectorised positions: isolated rows and cross accounts."""
    def __init__(self, s):
        self.mk = sorted(s["market"].unique().to_list()); ix = {m: i for i, m in enumerate(self.mk)}
        iso = s.filter(pl.col("leverage_type") == "isolated", pl.col("liquidation_price").is_not_null())
        q = iso["size"].to_numpy(); L = iso["liquidation_price"].to_numpy(); e = iso["entry_price"].to_numpy(); r = iso["r"].to_numpy()
        self.iq, self.iP, self.ir, self.ie = q, iso["P"].to_numpy(), r, e
        self.im = r * np.abs(q) * L - q * (L - e)                       # isolated margin from the liquidation price
        self.ik = np.array([ix[m] for m in iso["market"]]); self.inox = iso["nox"].to_numpy(); self.iml = iso["market"].replace_strict(ML, return_dtype=pl.Float64).to_numpy()
        cr = s.filter(pl.col("leverage_type") == "cross")
        # A from the largest xyz position with a liquidation price: A + q_k (L - P_k) = r_k |q_k| L + sum_{i != k} r_i |q_i| P_i
        big = cr.filter(pl.col("liquidation_price").is_not_null()).sort("notional", descending=True).unique("user", keep="first")
        tot = cr.group_by("user").agg(mm=(pl.col("r") * pl.col("notional")).sum())
        big = big.join(tot, on="user").with_columns(
            A=pl.col("r") * pl.col("size").abs() * pl.col("liquidation_price") + (pl.col("mm") - pl.col("r") * pl.col("notional"))
              - pl.col("size") * (pl.col("liquidation_price") - pl.col("P")))
        cr = cr.join(big.select("user", "A"), on="user", how="inner")      # accounts with no liquidation price: not liquidatable
        users = sorted(cr["user"].unique().to_list()); ux = {u: i for i, u in enumerate(users)}
        self.cu = np.array([ux[u] for u in cr["user"]]); self.cq = cr["size"].to_numpy(); self.cP = cr["P"].to_numpy(); self.cr = cr["r"].to_numpy()
        self.ck = np.array([ix[m] for m in cr["market"]]); self.cnox = cr["nox"].to_numpy(); self.cml = cr["market"].replace_strict(ML, return_dtype=pl.Float64).to_numpy()
        first = cr.unique("user", keep="first", maintain_order=True)
        self.nu = len(users)
        self.cAV = np.zeros(self.nu); self.cRo = np.zeros(self.nu)
        fu = np.array([ux[u] for u in first["user"]]); self.cAV[fu] = first["A"].to_numpy()

    def gap(self, ret):
        """ret: array of moves per market (self.mk order). Returns vault and ADL figures."""
        # isolated
        P1 = self.iP * (1 + ret[self.ik]); n1 = np.abs(self.iq) * P1
        eq = self.im + self.iq * (P1 - self.ie)
        tk = eq < BSF * self.ir * n1
        v = tk & ~self.inox; a = tk & self.inox
        out = dict(v_ntl=n1[v].sum(), v_eq=eq[v].sum(), v_mm=(n1[v] / (2 * self.iml[v])).sum(), v_n=int(v.sum()),
                   adl_ntl=n1[a].sum(), adl_short=np.maximum(-eq[a], 0).sum(), adl_n=int(a.sum()))
        # cross accounts
        P1 = self.cP * (1 + ret[self.ck]); n1 = np.abs(self.cq) * P1
        eqa = self.cAV + np.bincount(self.cu, self.cq * (P1 - self.cP), self.nu)
        req = self.cRo + np.bincount(self.cu, self.cr * n1, self.nu)
        tka = eqa < BSF * req
        rows = tka[self.cu]
        # the account's xyz positions on cross-enabled markets go to the vault with the account's equity (split by notional
        # if it also holds noCross positions; cross positions on noCross markets do not exist: noCross forbids cross)
        out["v_ntl"] += n1[rows].sum(); out["v_mm"] += (n1[rows] / (2 * self.cml[rows])).sum()
        out["v_eq"] += eqa[tka].sum(); out["v_n"] += int(tka.sum())
        out["C_ADL"] = max(0.0, -out["v_eq"]); out["C_MM"] = max(0.0, out["v_mm"] - out["v_eq"])
        # cross margin enabled on the noCross markets too: the vault also takes their positions (eq' with them)
        Pi = self.iP * (1 + ret[self.ik]); ni = np.abs(self.iq) * Pi; ei = self.im + self.iq * (Pi - self.ie)
        mm_a = (ni[a] / (2 * self.iml[a])).sum(); eq_a = ei[a].sum()
        out["C_ADL_x"] = max(0.0, -(out["v_eq"] + eq_a)); out["C_MM_x"] = max(0.0, out["v_mm"] + mm_a - out["v_eq"] - eq_a)
        return out


def moves(mk, W):
    c = pl.read_parquet(f"{ROOT}/data/candles/xyz_1h.parquet").filter(pl.col("coin").is_in(mk))
    w = c.pivot(on="coin", index="t", values="c").sort("t")
    for m in mk:
        if m not in w.columns: w = w.with_columns(pl.lit(None, dtype=pl.Float64).alias(m))
    t = w["t"].to_numpy(); X = w.select(mk).to_numpy().astype(float)
    X = pl.DataFrame(X).fill_null(strategy="forward").to_numpy()      # closed hours: no candle, price unchanged
    R = X[W:] / X[:-W] - 1
    return t[W:], np.nan_to_num(R, nan=0.0)


def main():
    global B
    # ---- validation: each real event's move (close before the window -> the window's low) on that day's snapshot
    VAL = [("0727", "xyz:SKHX", "2026-07-27 00:00", "2026-07-27 12:00", 1235843), ("1028", "xyz:GOOGL", "2026-10-28 20:00", "2026-10-29 00:00", 185568),
           ("1029", "xyz:INTC", "2026-10-29 20:00", "2026-10-30 00:00", 174503), ("1029", "xyz:AMZN", "2026-10-29 20:00", "2026-10-30 00:00", 108178)]
    C1 = pl.read_parquet(f"{ROOT}/data/candles/xyz_1h.parquet").with_columns(ts=pl.from_epoch("t", time_unit="ms"))
    val = []
    for day, coin, a, b, real in VAL:
        sv, _ = positions(day); Bv = Book(sv)
        w = C1.filter(pl.col("coin") == coin).sort("t")
        pre = w.filter(pl.col("ts") < pl.lit(a).str.to_datetime())["c"][-1]
        lo = w.filter(pl.col("ts") >= pl.lit(a).str.to_datetime(), pl.col("ts") < pl.lit(b).str.to_datetime())["l"].min()
        mv = lo / pre - 1
        g = Bv.gap(np.where(np.array(Bv.mk) == coin, mv, 0.0))
        val.append(dict(event=f"{coin[4:]} {day}", move_pct=round(mv * 100, 1), model_C_ADL=round(g["C_ADL"]), real_C_ADL=real, model_inherits_M=round(g["v_ntl"] / 1e6, 2)))
    V = pl.DataFrame(val); print("validation (instant gap of the real move vs the vault's measured need):"); print(V)

    DAY = sys.argv[1] if len(sys.argv) > 1 else "1030"
    s, f = positions(DAY)
    B = Book(s)
    oi = s.group_by("nox").agg((pl.col("notional").sum() / 1e6).round(1)).to_dicts()
    print(f"snapshot {os.path.basename(f)}: {s.height} positions, OI $M {oi}; cross accounts modelled {B.nu}")
    net = s.group_by("market").agg(pl.col("size").sign().mul(pl.col("notional")).sum().alias("net"))
    side = {m: (1 if v >= 0 else -1) for m, v in zip(net["market"], net["net"])}
    rows = []
    for W in (1, 4, 24):
        t, R = moves(B.mk, W)
        res = [B.gap(R[i]) for i in range(len(t))]
        df = pl.DataFrame(res).with_columns(t=pl.Series(t), W=pl.lit(W), n_down5=pl.Series((R < -0.05).sum(1)), n_up5=pl.Series((R > 0.05).sum(1)))
        rows.append(df)
        # bounds: every market at its own worst adverse W-hour move at once; and the single worst market alone
        adv = np.array([R[:, j].min() if side.get(m, 1) > 0 else R[:, j].max() for j, m in enumerate(B.mk)])
        allw = B.gap(adv); allw.update(t=-1, W=W, n_down5=int((adv < -0.05).sum()), n_up5=int((adv > 0.05).sum()))
        rows.append(pl.DataFrame([allw]))
        one = max((B.gap(np.where(np.arange(len(adv)) == j, adv, 0.0)) | {"m": m} for j, m in enumerate(B.mk)), key=lambda x: x["C_MM"])
        print(f"W={W}h  single worst market alone: {one['m']} C_MM ${one['C_MM']/1e6:.2f}M C_ADL ${one['C_ADL']/1e6:.2f}M")
        rows.append(pl.DataFrame([{k: v for k, v in one.items() if k != "m"} | dict(t=-2, W=W, n_down5=0, n_up5=0)]))
    D = pl.concat(rows, how="diagonal_relaxed").with_columns(
        when=pl.when(pl.col("t") == -1).then(pl.lit("all markets at their worst")).when(pl.col("t") == -2).then(pl.lit("worst single market"))
            .otherwise(pl.from_epoch(pl.col("t").clip(0), time_unit="ms").dt.strftime("%Y-%m-%d %H:%M")))
    D.write_csv(f"{ROOT}/data/scen/joint_capital_scen.csv")
    pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(14)
    fmt = lambda d: d.select("W", "when", "n_down5", "n_up5", (pl.col("v_ntl") / 1e6).round(2).alias("vault_inherits_M"), (pl.col("C_ADL") / 1e6).round(2).alias("C_ADL_M"),
                             (pl.col("C_MM") / 1e6).round(2).alias("C_MM_M"), (pl.col("C_MM_x") / 1e6).round(2).alias("C_MM_if_cross_M"), (pl.col("adl_ntl") / 1e6).round(2).alias("noCross_ADL_M"), (pl.col("adl_short") / 1e6).round(3).alias("noCross_short_M"))
    top = pl.concat([D.filter(pl.col("W") == W, pl.col("t") >= 0).sort("C_MM", descending=True).head(5) for W in (1, 4, 24)]
                    + [D.filter(pl.col("t") < 0)])
    print("worst historical hours applied to today's positions, and the bounds:"); print(fmt(top))
    topa = pl.concat([D.filter(pl.col("W") == W, pl.col("t") >= 0).sort("adl_ntl", descending=True).head(3) for W in (1, 4, 24)])
    print("worst for noCross ADL:"); print(fmt(topa))
    q = D.filter(pl.col("t") >= 0).group_by("W").agg(hours=pl.len(), C_MM_p99=pl.col("C_MM").quantile(0.99) / 1e6, C_MM_p999=pl.col("C_MM").quantile(0.999) / 1e6,
                                                      C_MM_max=pl.col("C_MM").max() / 1e6, ADL_hours=(pl.col("adl_ntl") > 0).sum(), ADL_max=pl.col("adl_ntl").max() / 1e6).sort("W")
    print(q)
    fmt(top).write_csv(f"{ROOT}/data/scen/joint_capital_top.csv")
    if os.environ.get("REG"):
        recs = [dict(design="current", case=f"W={r['W']}h {r['when']}", **{k: r[k] for k in ("vault_inherits_M", "C_ADL_M", "C_MM_M", "C_MM_if_cross_M", "noCross_ADL_M", "noCross_short_M", "n_down5", "n_up5")})
                for r in fmt(top).to_dicts()]
        registry.maybe_record(recs, kind="joint_capital", command=f"python sim/study/fetch_candles.py; python sim/study/joint_capital.py {DAY}")


if __name__ == "__main__":
    main()
