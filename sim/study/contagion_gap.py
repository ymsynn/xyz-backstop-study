"""Cross-margin contagion in the gap model: does moving the six eligible markets to cross margin make joint moves worse?

Contagion = an account taken over in a joint move although no single market's move alone would take it over (shared
equity carries one market's loss into another's margin). Counted on the worst real hours (1h and 4h moves of all xyz
markets, sim/study/joint_capital.py) on the 10-30 positions, for:
  today      positions as they are
  six_x      HOOD, MSTR, NBIS, AMD, EWY, SMSN cross-enabled, and every trader who already has a cross account on xyz moves
             their isolated positions there into it (margin joins the account's equity): the upper bound on new sharing
Also the vault's need (C_MM) and noCross ADL for both.
Usage: python sim/study/contagion_gap.py [DAY=1030] [TOP=5]  (REG=contagion-gap to record) -> data/scen/contagion_gap.csv"""
import os, sys
import numpy as np
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry
from joint_capital import Book, positions, moves, ROOT, BSF

DAY = sys.argv[1] if len(sys.argv) > 1 else "1030"
TOP = int(sys.argv[2]) if len(sys.argv) > 2 else 5
SIX = ["xyz:HOOD", "xyz:MSTR", "xyz:NBIS", "xyz:AMD", "xyz:EWY", "xyz:SMSN"]
s0, _ = positions(DAY)

def migrate(s):
    """isolated positions in SIX of users with a cross account -> cross positions of that account (margin into A via the
    liquidation price of the account's largest position, recomputed by Book from the new set)"""
    cu = set(s.filter(pl.col("leverage_type") == "cross", pl.col("liquidation_price").is_not_null())["user"].to_list())
    mv = (pl.col("market").is_in(SIX)) & (pl.col("leverage_type") == "isolated") & pl.col("user").is_in(list(cu))
    # the isolated margin joins the account: shift the largest cross position's liquidation price by margin / |q|
    iso = s.filter(mv).with_columns(m=(pl.col("r") * pl.col("size").abs() * pl.col("liquidation_price") - pl.col("size") * (pl.col("liquidation_price") - pl.col("entry_price"))) + pl.col("size") * (pl.col("P") - pl.col("entry_price")))
    add = iso.group_by("user").agg(pl.col("m").sum().alias("add_m"))
    s = s.with_columns(pl.when(mv).then(pl.lit("cross")).otherwise(pl.col("leverage_type")).alias("leverage_type"),
                       pl.when(mv).then(None).otherwise(pl.col("liquidation_price")).alias("liquidation_price"),
                       pl.when(pl.col("market").is_in(SIX)).then(False).otherwise(pl.col("nox")).alias("nox"))
    big = s.filter(pl.col("leverage_type") == "cross", pl.col("liquidation_price").is_not_null()).sort("notional", descending=True).unique("user", keep="first").select("user", "market")
    s = (s.join(add, on="user", how="left").join(big.with_columns(top=pl.lit(True)), on=["user", "market"], how="left")
          .with_columns(liquidation_price=pl.when(pl.col("top").fill_null(False) & pl.col("add_m").is_not_null())
                        .then(pl.col("liquidation_price") - pl.col("size").sign() * pl.col("add_m") / pl.col("size").abs()).otherwise(pl.col("liquidation_price")))
          .drop("add_m", "top"))
    return s, iso.height, float(iso["notional"].sum())

def taken_accounts(B, ret):
    """cross accounts taken over (index set) and isolated rows taken over (index set) for a move vector"""
    P1 = B.cP * (1 + ret[B.ck]); n1 = np.abs(B.cq) * P1
    eqa = B.cAV + np.bincount(B.cu, B.cq * (P1 - B.cP), B.nu); req = np.bincount(B.cu, B.cr * n1, B.nu)
    Pi = B.iP * (1 + ret[B.ik]); ei = B.im + B.iq * (Pi - B.ie)
    return set(np.where(eqa < BSF * req)[0]), set(np.where(ei < BSF * B.ir * np.abs(B.iq) * Pi)[0])

rows = []
for lab, s in (("today", s0), ("six_x", None)):
    extra = {}
    if s is None:
        s, nmv, ntl = migrate(s0); extra = dict(moved_positions=nmv, moved_ntl_M=round(ntl / 1e6, 2))
    B = Book(s)
    for W in (1, 4):
        t, R = moves(B.mk, W)
        C = np.array([B.gap(r)["C_MM"] for r in R]); top = np.argsort(-C)[:TOP]
        for k in top:
            r = R[k]; ca, ia = taken_accounts(B, r)
            single_c, single_i = set(), set()
            for j in np.where(r != 0)[0]:
                e = np.zeros_like(r); e[j] = r[j]; c1, i1 = taken_accounts(B, e); single_c |= c1; single_i |= i1
            cont = ca - single_c
            cn = float(sum(np.abs(B.cq[B.cu == u]) @ (B.cP[B.cu == u] * (1 + r[B.ck[B.cu == u]])) for u in cont))
            g = B.gap(r)
            rows.append(dict(case=lab, W=W, when=pl.from_epoch(pl.Series([int(t[k])]), time_unit="ms").dt.strftime("%m-%d %H:%M")[0],
                             cross_taken=len(ca), contagion_accounts=len(cont), contagion_ntl_M=round(cn / 1e6, 2),
                             C_MM_M=round(g["C_MM"] / 1e6, 2), noCross_ADL_M=round(g["adl_ntl"] / 1e6, 2), **extra))
D = pl.DataFrame(rows, infer_schema_length=None)
D.write_csv(f"{ROOT}/data/scen/contagion_gap.csv")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(200); print(D)
print(D.group_by("case", "W").agg(pl.col("contagion_accounts").max(), pl.col("contagion_ntl_M").max(), pl.col("C_MM_M").max(), pl.col("noCross_ADL_M").max()).sort("W", "case"))
if os.environ.get("REG"):
    registry.maybe_record([dict(design="current" if r["case"] == "today" else "six_cross_migrated", **{k: v for k, v in r.items() if k != "case"}, case=f"W={r['W']}h {r['when']}") for r in D.to_dicts()],
                          kind="contagion_gap", command=f"python sim/study/contagion_gap.py {DAY} {TOP}")
