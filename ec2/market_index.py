"""Index of xyz markets per day on the hydromancer tape: one row per (date, market) with the size of its 1-minute book file
(a market exists on a day if it has one). Used to draw a random sample of market-days (sim/final/random_sample.py).
Requester-pays listing: run in ap-northeast-1 only. Writes s3://$BUCKET/backstop/random/market_index.csv."""
import os, re, io
from concurrent.futures import ThreadPoolExecutor
import boto3
s3 = boto3.client("s3", region_name="ap-northeast-1"); RP = dict(RequestPayer="requester"); SRC = "hydromancer-reservoir"
def ls(prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=SRC, Prefix=prefix, Delimiter="/", **RP)
        if tok: kw["ContinuationToken"] = tok
        r = s3.list_objects_v2(**kw)
        out += [(p["Prefix"], 0) for p in r.get("CommonPrefixes", [])] + [(o["Key"], o["Size"]) for o in r.get("Contents", [])]
        tok = r.get("NextContinuationToken")
        if not tok: return out
days = sorted(p for p, _ in ls("by_dex/xyz/orderbook/1m/perps/") if "date=" in p)
with ThreadPoolExecutor(16) as ex: per = list(ex.map(ls, days))
rows = ["date,coin,ob1m_bytes"]
for d, keys in zip(days, per):
    date = re.search(r"date=(\d{4}-\d{2}-\d{2})", d)[1]
    rows += [f"{date},{k.split('/')[-1][:-8]},{sz}" for k, sz in keys if k.endswith(".parquet")]
s3.put_object(Bucket=os.environ["BUCKET"], Key="backstop/random/market_index.csv", Body="\n".join(rows).encode())
s3.put_object(Bucket=os.environ["BUCKET"], Key="backstop/random/HEARTBEAT.txt", Body=f"INDEX DONE {len(days)} days {len(rows) - 1} market-days".encode())
