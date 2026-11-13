"""Positions liquidated in the 300 s from the start of a walk, on the book and by the vault: python score_liquidated.py W0_MS DIR:NAME [...]"""
import sys, polars as pl
W0 = int(sys.argv[1])
for a in sys.argv[2:]:
    d, n = a.split(":")
    o = pl.read_csv(f"{d}/orc_{n}.csv").select("h", "ms").sort("h")
    tk = pl.read_csv(f"{d}/tk_{n}.csv").sort("h").join_asof(o, on="h").filter((pl.col("ms") >= W0) & (pl.col("ms") < W0 + 300000))
    rd = pl.read_csv(f"{d}/rd_{n}.csv").filter(pl.col("sim_h1") > 0).sort("sim_h1").join_asof(o.rename({"h": "sim_h1"}), on="sim_h1").filter((pl.col("ms") >= W0) & (pl.col("ms") < W0 + 300000))
    acc = set(tk["u"].to_list()) | set(rd["u"].to_list())
    vn = float((tk["q"].abs() * tk["px"]).sum()); px = float(tk["px"].mean() or 0) or 300.0
    bk = float(rd["sim_filled"].sum())
    print(f"{d.split('/')[-1]:12} {n:36} accounts {len(acc):4} | vault ${vn/1e6:6.2f}M | book {bk:8.0f} sh (~${bk*px/1e6:5.2f}M) | total ~${(vn+bk*px)/1e6:6.2f}M")
