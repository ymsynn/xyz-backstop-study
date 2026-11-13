"""Extract per-user funding and liquidation ledger events for one coin from misc_events_by_block hourly files.
Usage: python ledger.py MISC_DIR COIN OUT_DIR  ->  funding_<COIN>.parquet (t, h, user, amount, szi, rate),
       liq_ledger.parquet (t, h, user, account_value, ntl, leverage_type, szi, n_positions)"""
import sys, os, glob, json, subprocess
import polars as pl
MISC, COIN, OUT = sys.argv[1:4]
fund, liq = [], []
for fp in sorted(glob.glob(os.path.join(MISC, "*.lz4")), key=lambda p: int(os.path.basename(p).split(".")[0])):
    p = subprocess.Popen(["unlz4", "-c", fp], stdout=subprocess.PIPE)
    for line in p.stdout:
        o = json.loads(line)
        h = o["block_number"]
        for e in o["events"]:
            inn = e["inner"]
            if "Funding" in inn:
                for d in inn["Funding"]["deltas"]:
                    if d["coin"] == COIN:
                        fund.append(dict(t=e["time"], h=h, user=d["user"].lower(), amount=float(d["funding_amount"]), szi=float(d["szi"]), rate=float(d["funding_rate"])))
            elif "LedgerUpdate" in inn:
                dl = inn["LedgerUpdate"]["delta"]
                if dl.get("type") == "liquidation":
                    pos = [x for x in dl.get("liquidatedPositions", []) if x["coin"] == COIN]
                    if pos:
                        for u in inn["LedgerUpdate"]["users"]:
                            liq.append(dict(t=e["time"], h=h, user=u.lower(), account_value=float(dl["accountValue"]), ntl=float(dl["liquidatedNtlPos"]),
                                            leverage_type=dl.get("leverageType"), szi=float(pos[0]["szi"]), n_positions=len(dl.get("liquidatedPositions", []))))
    p.wait()
os.makedirs(OUT, exist_ok=True)
tag = COIN.split(":")[1]
pl.DataFrame(fund).with_columns(pl.col("t").str.to_datetime(time_unit="ns")).write_parquet(f"{OUT}/funding_{tag}.parquet")
# quiet days can have no liquidation at all: write an empty table with the columns
LIQ_SCHEMA = {"t": pl.String, "h": pl.Int64, "user": pl.String, "account_value": pl.Float64, "ntl": pl.Float64,
              "leverage_type": pl.String, "szi": pl.Float64, "n_positions": pl.Int64}
pl.DataFrame(liq, schema=LIQ_SCHEMA).with_columns(pl.col("t").str.to_datetime(time_unit="ns")).write_parquet(f"{OUT}/liq_ledger_{tag}.parquet")
print("funding rows", len(fund), "liquidation ledger rows", len(liq))
