"""For each one-sided-book liquidation found by ec2/onesided_screen.py: the deployer's setOracle inputs (oracle, mark inputs,
external price) block by block around it, from the node archive's explorer_blocks, and every fill of the coin in the window
(last trade) from the hydromancer tape. With the liquidation fill's mark this tells which rule Hyperliquid applies to the
local mark when a book side is empty. Reads s3://$BUCKET/backstop/onesided/hits.csv; writes oracle_rows.csv, fills_rows.csv,
book_rows.csv (the 1-minute snapshots of the window, top 3 levels) and confirm_summary.txt there. Requester-pays: ap-northeast-1 only."""
import os, io, json
from concurrent.futures import ThreadPoolExecutor
import boto3, polars as pl, msgpack, lz4.frame

BUCKET = os.environ["BUCKET"]; OUT = "backstop/onesided"; PAD = int(os.environ.get("PAD_BLOCKS", 1500))
s3 = boto3.client("s3", region_name="ap-northeast-1"); RP = dict(RequestPayer="requester")
H = pl.read_csv(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=f"{OUT}/hits.csv")["Body"].read()), infer_schema_length=None)
ev = H.group_by("dex", "coin", "date").agg(pl.col("h_prev").min().alias("lo"), pl.col("h_next").max().alias("hi"), pl.col("ms").min().alias("t0"), pl.col("ms").max().alias("t1"), pl.len().alias("fills"))
log = [f"coin-days {ev.height}"]; orows, frows, brows = [], [], []


def blocks(arg):
    """one explorer_blocks file -> the setOracle rows of (dex, coin); parsed and dropped inside the worker (a file is all of
    Hyperliquid's transactions for 100 blocks: keeping them in memory killed the first run)"""
    n, dex, coin, date = arg
    d1 = (n - 1) // 100000000 * 100000000; d2 = (n - 1) // 100000 * 100000
    try:
        bl = msgpack.unpackb(lz4.frame.decompress(s3.get_object(Bucket="hl-mainnet-node-data", Key=f"explorer_blocks/{d1}/{d2}/{n}.rmp.lz4", **RP)["Body"].read()), raw=False)
    except Exception as e:
        return f"FAIL {n}: {e}"
    out = []
    for blk in bl:
        h, t = blk["header"]["height"], blk["header"]["block_time"]
        for tx in blk["txs"]:
            for a in tx["actions"]:
                so = a.get("setOracle") if a.get("type") == "perpDeploy" else None
                if not so or so.get("dex") != dex: continue
                o = dict(so.get("oraclePxs") or []).get(coin); x = dict(so.get("externalPerpPxs") or []).get(coin)
                m = [dict(mm).get(coin) for mm in (so.get("markPxs") or [])]
                out.append((dex, coin, date, h, str(t), o, json.dumps(m), x, tx.get("error")))
    return out


for dex, coin, date, lo, hi, t0, t1, nf in ev.iter_rows():
    if lo is None or hi is None: log.append(f"{coin} {date}: no block range"); continue
    if hi - lo > 40000: log.append(f"{coin} {date}: range {hi - lo} blocks, cut to 40000"); hi = lo + 40000
    files = list(range(-(-(lo - PAD) // 100) * 100, -(-(hi + PAD) // 100) * 100 + 1, 100))
    with ThreadPoolExecutor(4) as ex: res = list(ex.map(blocks, [(n, dex, coin, date) for n in files]))
    bad = [r for r in res if isinstance(r, str)]; n0 = len(orows)
    for r in res:
        if not isinstance(r, str): orows += r
    log.append(f"{coin} {date}: blocks {lo}..{hi}, files {len(files)} (failed {len(bad)}), setOracle rows {len(orows) - n0}, liquidation fills {nf}" + (f" | {bad[0]}" if bad else ""))
    try:
        f = pl.read_parquet(io.BytesIO(s3.get_object(Bucket="hydromancer-reservoir", Key=f"by_dex/{dex}/fills/perp/all/date={date}/fills.parquet", **RP)["Body"].read()))
        f = f.filter(pl.col("coin") == coin).with_columns(ms=pl.col("timestamp").dt.epoch("ms")).filter((pl.col("ms") >= t0 - 600000) & (pl.col("ms") <= t1 + 600000))
        frows.append(f.select(pl.lit(dex).alias("dex"), "coin", pl.lit(date).alias("date"), "ms", pl.col("price").cast(pl.Float64), pl.col("size").cast(pl.Float64), "side", "direction", "crossed", "trade_id", "tx_hash",
                              "is_liquidation", pl.col("liquidation_mark_px").cast(pl.Float64).alias("mark"), "liquidation_method"))
    except Exception as e: log.append(f"{coin} {date}: fills {str(e)[:100]}")
    try:
        b = pl.read_parquet(io.BytesIO(s3.get_object(Bucket="hydromancer-reservoir", Key=f"by_dex/{dex}/orderbook/1m/perps/date={date}/{coin.split(':')[-1]}.parquet", **RP)["Body"].read()))
        b = b.filter((pl.col("block_time_ms") >= t0 - 600000) & (pl.col("block_time_ms") <= t1 + 600000))
        for ms, h, bids, asks in b.select("block_time_ms", "block_number", "bids", "asks").iter_rows():
            brows.append((dex, coin, date, ms, h, json.dumps([(x["px"], x["sz"]) for x in bids[:3]]), json.dumps([(x["px"], x["sz"]) for x in asks[:3]])))
    except Exception as e: log.append(f"{coin} {date}: book {str(e)[:100]}")
    s3.put_object(Bucket=BUCKET, Key=f"{OUT}/HEARTBEAT.txt", Body=log[-1].encode())


def put(name, df):
    b = io.BytesIO(); df.write_csv(b); s3.put_object(Bucket=BUCKET, Key=f"{OUT}/{name}", Body=b.getvalue())


put("oracle_rows.csv", pl.DataFrame(orows, schema=["dex", "coin", "date", "h", "t", "oracle", "marks", "ext", "err"], orient="row"))
if frows: put("fills_rows.csv", pl.concat(frows))
put("book_rows.csv", pl.DataFrame(brows, schema=["dex", "coin", "date", "ms", "h", "bids", "asks"], orient="row"))
s3.put_object(Bucket=BUCKET, Key=f"{OUT}/confirm_summary.txt", Body="\n".join(log).encode())
s3.put_object(Bucket=BUCKET, Key=f"{OUT}/HEARTBEAT.txt", Body=b"CONFIRM DONE")
