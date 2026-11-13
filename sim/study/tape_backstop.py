"""Backstop and ADL on xyz from the fills tape alone, for any day (run where the tape is: an instance in ap-northeast-1).
Per market: book liquidation notional, backstop events and where each went (vault fill at the same time and coin, or ADL
fills), ADL notional. Vault across all markets: inventory per coin from the morning snapshot (if given) plus its fills,
marked every minute at the coin's last trade; equity V relative to the day's start, MM = sum |q| P / (2 maxLev);
C_MM = max(MM - V), C_ADL = max(-V) (as sim/study/vault_capital.py, with the last trade as the mark).
Usage: python sim/study/tape_backstop.py OUT_PREFIX FILLS.parquet [SNAPSHOT.parquet]
  -> OUT_PREFIX_markets.csv, OUT_PREFIX_vault_path.csv, OUT_PREFIX_summary.json, OUT_PREFIX_vault_fills.csv"""
import json, os, sys
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
U = json.load(open(f"{ROOT}/data/xyzmeta.json"))[0]["universe"]
ML = {u["name"]: float(u["maxLeverage"]) for u in U}
MODE = {u["name"]: (u.get("marginMode") or "cross") for u in U}
V = "0x4000000000000000000000000000000000000001"
out, fills = sys.argv[1], sys.argv[2]
snap = sys.argv[3] if len(sys.argv) > 3 else None

d = (pl.scan_parquet(fills).select("coin", "timestamp", "address", "direction", "liquidation_method", "price", "size", "side", "crossed")
     .with_columns(px=pl.col("price").cast(pl.Float64), sz=pl.col("size").cast(pl.Float64), ms=pl.col("timestamp").dt.epoch("ms"))
     .with_columns(ntl=pl.col("px") * pl.col("sz")).collect())
d = d.with_columns(mode=pl.col("coin").replace_strict(MODE, default="?"))
# both sides of a liquidation fill carry the method: the liquidated side is the taker of a market round, and the non-vault
# side of a backstop fill
liq = d.filter(((pl.col("liquidation_method") == "market") & pl.col("crossed"))
               | ((pl.col("liquidation_method") == "backstop") & (pl.col("address") != V) & pl.col("direction").str.starts_with("Liquidated")))
bs = liq.filter(pl.col("liquidation_method") == "backstop")
ev = bs.group_by("mode", "coin", "ms").agg(liq_ntl=pl.col("ntl").sum(), n=pl.len())
vf = d.filter(pl.col("address") == V)
adl = d.filter(pl.col("direction") == "Auto-Deleveraging")
ev = (ev.join(vf.group_by("coin", "ms").agg(vault=pl.len()), on=["coin", "ms"], how="left")
        .join(adl.group_by("coin", "ms").agg(adl=pl.col("ntl").sum()), on=["coin", "ms"], how="left")
        .with_columns(to=pl.when(pl.col("vault").is_not_null()).then(pl.lit("vault")).when(pl.col("adl").is_not_null()).then(pl.lit("ADL")).otherwise(pl.lit("?"))))
mk = (liq.group_by("mode", "coin").agg(book_liq_ntl=pl.col("ntl").filter(pl.col("liquidation_method") == "market").sum(),
                                       backstop_ntl=pl.col("ntl").filter(pl.col("liquidation_method") == "backstop").sum())
      .join(ev.group_by("coin").agg(bs_events=pl.len(), to_vault=(pl.col("to") == "vault").sum(), to_adl=(pl.col("to") == "ADL").sum(), unmatched=(pl.col("to") == "?").sum()), on="coin", how="left")
      .join(adl.group_by("coin").agg(adl_ntl=pl.col("ntl").sum(), adl_fills=pl.len()), on="coin", how="full", coalesce=True)
      .with_columns(mode=pl.col("coin").replace_strict(MODE, default="?")).sort("backstop_ntl", descending=True, nulls_last=True))
mk.write_csv(f"{out}_markets.csv")

# vault path across markets
q0 = {}
if snap:
    s = pl.read_parquet(snap).filter(pl.col("user") == V, pl.col("size") != 0)
    q0 = dict(zip(s["market"], s["size"]))
vf = vf.with_columns(dq=pl.when(pl.col("side") == "B").then(pl.col("sz")).otherwise(-pl.col("sz"))).sort("ms")
vf.select("ms", "coin", "direction", "px", "sz", "dq", "crossed").write_csv(f"{out}_vault_fills.csv")
coins = sorted(set(vf["coin"].to_list()) | set(q0))
mins = d.filter(pl.col("coin").is_in(coins)).with_columns(m=(pl.col("ms") // 60000) * 60000).group_by("coin", "m").agg(P=pl.col("px").last()).sort("m")
grid = pl.DataFrame({"m": sorted(set(mins["m"].to_list()) | set(((vf["ms"] // 60000) * 60000).to_list()))})
rows = None
for c in coins:
    p = grid.join(mins.filter(pl.col("coin") == c).select("m", "P"), on="m", how="left").with_columns(pl.col("P").forward_fill().backward_fill())
    f = vf.filter(pl.col("coin") == c).with_columns(m=(pl.col("ms") // 60000) * 60000).group_by("m").agg(dq=pl.col("dq").sum(), cash=(-pl.col("dq") * pl.col("px")).sum())
    p = p.join(f, on="m", how="left").with_columns(pl.col("dq").fill_null(0), pl.col("cash").fill_null(0)).sort("m")
    p = p.with_columns(q=q0.get(c, 0.0) + pl.col("dq").cum_sum(), cash=pl.col("cash").cum_sum())
    P0 = p["P"][0]
    p = p.select("m", v=pl.col("cash") + pl.col("q") * pl.col("P") - q0.get(c, 0.0) * P0, mm=pl.col("q").abs() * pl.col("P") / (2 * ML.get(c, 10.0)),
                 inv=pl.col("q").abs() * pl.col("P"))
    rows = p if rows is None else rows.join(p, on="m", suffix="_r").with_columns(v=pl.col("v") + pl.col("v_r"), mm=pl.col("mm") + pl.col("mm_r"), inv=pl.col("inv") + pl.col("inv_r")).drop("v_r", "mm_r", "inv_r")
summ = dict(fills=fills, vault_fills=vf.height, vault_coins=len(set(vf["coin"].to_list())),
            backstop_events=ev.height, to_vault=int((ev["to"] == "vault").sum()), to_adl=int((ev["to"] == "ADL").sum()),
            adl_ntl=float(adl["ntl"].sum()), adl_ntl_nocross=float(adl.filter(pl.col("mode") != "cross")["ntl"].sum()),
            book_liq_ntl=float(liq.filter(pl.col("liquidation_method") == "market")["ntl"].sum()),
            markets_with_backstop=int(ev["coin"].n_unique()), markets_with_adl=int(adl["coin"].n_unique()))
if rows is not None and rows.height:
    rows.write_csv(f"{out}_vault_path.csv")
    summ.update(C_MM=float((rows["mm"] - rows["v"]).max()), C_ADL=float(max(0.0, -rows["v"].min())), peak_inventory=float(rows["inv"].max()),
                start_inventory=float(sum(abs(q) for q in q0.values())))
json.dump(summ, open(f"{out}_summary.json", "w"), indent=1)
print(json.dumps(summ, indent=1)); pl.Config.set_tbl_rows(25); print(mk.head(20))
