"""Scoreboard on the two takeover objectives (the vault's unwind cannot be tested on a replayed book):
  1. minimise the notional the vault inherits;
  2. maximise the position's value at takeover, q (F - px) against fair value F (Binance's stock perp by default).
Usage: [TK_DIR=dir] python sim/score/takeover_score.py SCENARIO [SCENARIO ...]   (reads TK_DIR/tk_{COIN}_{SCENARIO}.csv,
default data/scen/runs; the stuck-feed runs of the paper are in data/scen/final/stuck_f120)
FAIR_SRC=ext: score against trade.xyz's external price instead (needed when Binance is itself a mark input); it reads
ORC_DIR/orc_{COIN}.csv (control runs' ORC_OUT dumps). COINS=GOOGL,... restricts the coins.
"""
import os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
ORC = os.environ.get("ORC_DIR", f"{ROOT}/data/scen/orc")
COINS = {"GOOGL": "prep_GOOGL_1028", "INTC": "prep_INTC_1029", "AMZN": "prep_AMZN_1029"}
TK_DIR = os.environ.get("TK_DIR", f"{ROOT}/data/scen/runs")
rows = []
only = os.environ.get("COINS")   # e.g. COINS=GOOGL
for c, prep in COINS.items():
    if only and c not in only.split(","):
        continue
    b = pl.read_ipc(f"{ROOT}/data/{prep}/blocks.arrow")
    if os.environ.get("FAIR_SRC") == "ext":   # trade.xyz's external price (the replay's ORC_OUT dump)
        F = pl.read_csv(f"{ORC}/orc_{c}.csv").select("ms", (pl.col("ext") / 1e6).alias("F")).sort("ms")
    else:
        F = pl.read_parquet(f"{ROOT}/data/binance/{c}USDT_100ms.parquet").select("ms", pl.col("last").alias("F")).sort("ms")
    for s in sys.argv[1:]:
        f = f"{TK_DIR}/tk_{c}_{s}.csv"
        if not os.path.exists(f):
            print(f"takeover_score: no run {f}: skipped", file=sys.stderr); continue
        t = pl.read_csv(f).join(b, on="h").sort("ms").join_asof(F, on="ms", strategy="backward")
        # a position handed over at a negative bankruptcy price is counted at the mark (as sim/final/score_final.py)
        t = t.with_columns(ntl=pl.col("q").abs() * pl.when(pl.col("px") > 0).then(pl.col("px")).otherwise(pl.col("mark")), val=pl.col("q") * (pl.col("F") - pl.col("px")))
        rows.append(dict(coin=c, scenario=s, inherited_musd=round(t["ntl"].sum() / 1e6, 2), value_at_takeover=round(t["val"].sum()),
                         underwater=t.filter(pl.col("val") < 0).height, takeovers=t.height))
if not rows:
    sys.exit(f"takeover_score: no tk_<COIN>_<SCENARIO>.csv for {' '.join(sys.argv[1:]) or '(no scenario given)'} in {TK_DIR}")
d = pl.DataFrame(rows)
tot = d.group_by("scenario").agg(pl.col("inherited_musd").sum().round(2), pl.col("value_at_takeover").sum(), pl.col("underwater").sum(), pl.len().alias("coins"))
order = {s: i for i, s in enumerate(sys.argv[1:])}
pl.Config.set_tbl_rows(80); pl.Config.set_tbl_width_chars(200)
print(d.pivot(on="coin", index="scenario", values=["inherited_musd", "value_at_takeover"]).sort(pl.col("scenario").replace_strict(order)))
print(tot.sort(pl.col("scenario").replace_strict(order)))

dm = registry.design_map()
fair = "ext" if os.environ.get("FAIR_SRC") == "ext" else "binance"
registry.maybe_record([dict(design=dm.get(r["scenario"], r["scenario"]).split("|")[0], case=(dm.get(r["scenario"], "").split("|") + [None])[1], scenario=r["scenario"], coin=r["coin"],
                            inherited_musd=r["inherited_musd"], **{f"value_{fair}": r["value_at_takeover"], f"underwater_{fair}": r["underwater"]},
                            takeovers=r["takeovers"]) for r in rows],
                      kind="takeover_score", fair=fair, command=" ".join(f"{k}={__import__('shlex').quote(os.environ[k])}" for k in ("REG", "REG_MAP", "FAIR_SRC", "COINS") if os.environ.get(k)) + " python sim/score/takeover_score.py " + " ".join(sys.argv[1:]))
