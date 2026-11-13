"""Aggregate the tape scan (ec2/tape_job.sh -> data/scen/tape/out/): every xyz day's backstop events, where they went
(vault or ADL), ADL notional by market and margin mode, and the vault's capital need across all markets that day
(C_MM, C_ADL from its own fills marked at the last trade; sim/study/tape_backstop.py).
Usage: aws s3 sync s3://.../backstop/tape/out/ data/scen/tape/out/ ; python sim/score/tape_eval.py  (REG=tape-backstop to record)"""
import glob, json, os, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # sim/: registry.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # this folder
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
O = f"{ROOT}/data/scen/tape/out"
S = []
for f in sorted(glob.glob(f"{O}/t*_summary.json")):
    x = json.load(open(f)); x["day"] = os.path.basename(f)[1:9]; S.append(x)
D = pl.DataFrame(S, infer_schema_length=None).with_columns(pl.col("day").str.to_date("%Y%m%d"))
for c in ("C_MM", "C_ADL", "peak_inventory"):
    if c not in D.columns: D = D.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
M = pl.concat([pl.read_csv(f, infer_schema_length=None).with_columns(day=pl.lit(os.path.basename(f)[1:9]))
               for f in sorted(glob.glob(f"{O}/t*_markets.csv")) if os.path.getsize(f) > 0], how="diagonal_relaxed")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(220); pl.Config.set_tbl_cols(16)
print(f"{D.height} days {D['day'].min()} .. {D['day'].max()}")
print("totals:", D.select(pl.col("backstop_events").sum(), pl.col("to_vault").sum(), pl.col("to_adl").sum(),
                          (pl.col("adl_ntl").sum() / 1e6).round(2).alias("adl_M"), (pl.col("adl_ntl_nocross").sum() / 1e6).round(2).alias("adl_noCross_M"),
                          (pl.col("book_liq_ntl").sum() / 1e6).round(1).alias("book_liq_M")).to_dicts())
print("days with ADL:")
print(D.filter(pl.col("adl_ntl") > 0).select("day", "to_vault", "to_adl", "markets_with_adl", (pl.col("adl_ntl") / 1e3).round(0).alias("adl_k"),
      (pl.col("adl_ntl_nocross") / 1e3).round(0).alias("adl_noCross_k"), (pl.col("C_ADL") / 1e3).round(0).alias("vault_C_ADL_k")).sort("day"))
print("worst vault days (capital need across all markets):")
top = D.sort("C_MM", descending=True, nulls_last=True).head(12).select("day", "vault_coins", "to_vault", (pl.col("peak_inventory") / 1e6).round(2).alias("peak_inv_M"),
      (pl.col("C_MM") / 1e6).round(2).alias("C_MM_M"), (pl.col("C_ADL") / 1e6).round(2).alias("C_ADL_M"), (pl.col("book_liq_ntl") / 1e6).round(1).alias("book_liq_M"),
      (pl.col("adl_ntl") / 1e3).round(0).alias("adl_k"))
print(top)
mk = M.with_columns(pl.col("adl_ntl").cast(pl.Float64, strict=False)).filter(pl.col("adl_ntl").is_not_null(), pl.col("adl_ntl") > 0).group_by("mode", "coin").agg(days=pl.col("day").n_unique(), adl_k=(pl.col("adl_ntl").sum() / 1e3).round(0)).sort(["adl_k", "mode", "coin"], descending=[True, False, False])
print("ADL by market:"); print(mk.head(25))
D.write_csv(f"{ROOT}/data/scen/tape_days.csv"); top.write_csv(f"{ROOT}/data/scen/tape_top.csv"); mk.write_csv(f"{ROOT}/data/scen/tape_adl_markets.csv")
if os.environ.get("REG"):
    recs = [dict(design="current", case=str(r["day"]), **{k: r[k] for k in ("vault_coins", "to_vault", "peak_inv_M", "C_MM_M", "C_ADL_M", "adl_k")}) for r in top.to_dicts()]
    recs += [dict(design="current", case=f"ADL {r['coin']} ({r['mode']})", adl_k=r["adl_k"], days=r["days"]) for r in mk.head(15).to_dicts()]
    registry.maybe_record(recs, kind="tape_backstop", command="ec2/tape_launch.sh; python sim/score/tape_eval.py")
