"""Screen the hydromancer tape for liquidations printed while one side of the book was empty (every HIP-3 dex, every day).

Why: Hyperliquid's local mark is med(best bid, best ask, last trade); its rule with an empty side is not documented. A
liquidation fill carries the mark at that block (liquidation_mark_px), so a liquidation during a one-sided book shows it.
Inputs (requester-pays, read in ap-northeast-1 only): s3://hydromancer-reservoir/by_dex/{dex}/fills/perp/liquidations/date=D/*.parquet
and .../orderbook/1m/perps/date=D/{COIN}.parquet (one top-of-book snapshot per minute).
A hit = a liquidation fill within 60 s after / before a snapshot with no bids or no asks. The 1-minute grid is coarse, so hits
are candidates: the exact book at the block needs the replay of that market-day.
Outputs to s3://$BUCKET/backstop/onesided/: hits.csv, onesided_days.csv (coin-days with one-sided snapshots), summary.txt.
Usage (on the instance): python onesided_screen.py"""
import os, io, sys, re, collections
from concurrent.futures import ThreadPoolExecutor
import boto3, polars as pl

SRC = "hydromancer-reservoir"; BUCKET = os.environ["BUCKET"]; OUT = "backstop/onesided"
s3 = boto3.client("s3", region_name=os.environ.get("REGION", "ap-northeast-1"))
RP = dict(RequestPayer="requester")


def ls(prefix, delim="/"):
    out, tok = [], None
    while True:
        kw = dict(Bucket=SRC, Prefix=prefix, Delimiter=delim, **RP)
        if tok: kw["ContinuationToken"] = tok
        r = s3.list_objects_v2(**kw)
        out += [p["Prefix"] for p in r.get("CommonPrefixes", [])] + [o["Key"] for o in r.get("Contents", [])]
        tok = r.get("NextContinuationToken")
        if not tok: return out


def get(key):
    return io.BytesIO(s3.get_object(Bucket=SRC, Key=key, **RP)["Body"].read())


def put(name, text):
    s3.put_object(Bucket=BUCKET, Key=f"{OUT}/{name}", Body=text.encode())


def beat(msg):
    print(msg, flush=True); put("HEARTBEAT.txt", msg)


# "hyperliquid" = the native perps: another mark formula (three inputs with the CEX median) and 6M liquidation fills; HIP-3 only
dexes = [d for d in (p.split("/")[1] for p in ls("by_dex/")) if d != "hyperliquid"]
beat(f"dexes: {dexes}")
log = [f"dexes: {dexes}"]
liq = []
for dex in dexes:
    days = [p for p in ls(f"by_dex/{dex}/fills/perp/liquidations/") if "date=" in p]
    keys = [k for d in days for k in ls(d) if k.endswith(".parquet")]
    def rd(k):
        try:
            d = pl.read_parquet(get(k)).filter(pl.col("liquidation_mark_px").is_not_null())
            return d.select(pl.lit(dex).alias("dex"), "coin", pl.col("timestamp").dt.epoch("ms").alias("ms"), pl.col("price").cast(pl.Float64), pl.col("size").cast(pl.Float64),
                            "side", "direction", pl.col("liquidation_mark_px").cast(pl.Float64).alias("mark"), "liquidation_method", "address", "tx_hash",
                            pl.lit(re.search(r"date=(\d{4}-\d{2}-\d{2})", k)[1]).alias("date"))
        except Exception as e:
            return f"FAIL {k}: {e}"
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(rd, keys))
    bad = [r for r in res if isinstance(r, str)]; ok = [r for r in res if not isinstance(r, str) and r.height]
    log.append(f"{dex}: liquidation days {len(days)}, files {len(keys)}, failed {len(bad)}, liquidation fills {sum(r.height for r in ok)}"); log += bad[:5]
    liq += ok
    beat(log[-1] if not bad else log[-len(bad[:5]) - 1])
L = pl.concat(liq) if liq else None
if L is None: put("summary.txt", "\n".join(log + ["no liquidations found"])); sys.exit(0)
cd = L.group_by("dex", "coin", "date").agg(pl.len().alias("n")).sort("dex", "date", "coin")
beat(f"coin-days with liquidations: {cd.height}")
# newly listed markets (before market makers arrive): the first NEW_DAYS days of every coin's 1-minute book, on every dex
NEW_DAYS = int(os.environ.get("NEW_DAYS", 3)); new = []
for dex in dexes:
    first = collections.defaultdict(list)
    dd = sorted(p for p in ls(f"by_dex/{dex}/orderbook/1m/perps/") if "date=" in p)
    with ThreadPoolExecutor(16) as ex: per = list(ex.map(ls, dd))
    for d, keys in zip(dd, per):
        date = re.search(r"date=(\d{4}-\d{2}-\d{2})", d)[1]
        for k in keys:
            if k.endswith(".parquet"): first[k.split("/")[-1][:-8]].append(date)
    t0 = min((min(v) for v in first.values()), default=None)
    for base, v in first.items():
        v = sorted(v)
        if v[0] == t0: continue          # present on the tape's first day: its listing is not observed
        new += [(dex, f"{dex}:{base}", x, 0) for x in v[:NEW_DAYS]]
    log.append(f"{dex}: 1-minute book days {len(dd)} (from {t0}), coins {len(first)}, listed after the first day {sum(1 for v in first.values() if min(v) != t0)}")
    beat(log[-1])
newdf = pl.DataFrame(new, schema=["dex", "coin", "date", "n"], orient="row").with_columns(pl.col("n").cast(cd.schema["n"])) if new else cd.clear()
newkeys = set(newdf.select(pl.concat_str(["dex", "coin", "date"], separator="|")).to_series().to_list())
cd = pl.concat([cd, newdf.join(cd, on=["dex", "coin", "date"], how="anti")]).sort("dex", "date", "coin")
beat(f"coin-days to screen: {cd.height} (new-listing days {len(newkeys)})")
# which datasets exist (to find a mark-price source for moments without a liquidation)
ds = []
for pre in ["", "global/", "by_dex/xyz/", "by_dex/xyz/snapshots/", "by_dex/xyz/orderbook/", "by_dex/xyz/fills/perp/"]:
    try: ds.append(f"[{SRC}/{pre}] " + " ".join(x[len(pre):] for x in ls(pre)[:60]))
    except Exception as e: ds.append(f"[{pre}] {e}")
try:
    r = s3.list_objects_v2(Bucket="hl-mainnet-node-data", Delimiter="/", **RP); ds.append("[hl-mainnet-node-data/] " + " ".join(p["Prefix"] for p in r.get("CommonPrefixes", [])))
    for pre in ["asset_ctxs/", "market_data/", "misc_events_by_block/"]:
        r = s3.list_objects_v2(Bucket="hl-mainnet-node-data", Prefix=pre, Delimiter="/", MaxKeys=30, **RP)
        ds.append(f"[hl-mainnet-node-data/{pre}] " + " ".join([p["Prefix"] for p in r.get("CommonPrefixes", [])][-8:] + [o["Key"] + f"({o['Size']})" for o in r.get("Contents", [])][-8:]))
except Exception as e: ds.append(f"node archive listing: {e}")
put("datasets.txt", "\n".join(ds))


LP = {k: v.sort("ms") for k, v in L.partition_by("dex", "coin", "date", as_dict=True).items()}
del L


def screen(row):
    dex, coin, date, _ = row
    base = coin.split(":")[-1]
    key = f"by_dex/{dex}/orderbook/1m/perps/date={date}/{base}.parquet"
    try:
        o = pl.read_parquet(get(key))
    except Exception as e:
        return ("nobook", dex, coin, date, str(e)[:80])
    o = o.select(pl.col("block_time_ms").alias("sms"), pl.col("block_number").alias("h"), pl.col("bids").list.len().alias("nb"), pl.col("asks").list.len().alias("na"),
                 pl.col("bids").list.first().struct.field("px").alias("bid"), pl.col("asks").list.first().struct.field("px").alias("ask")).sort("sms")
    one = o.filter((pl.col("nb") == 0) | (pl.col("na") == 0))
    if one.height == 0: return ("ok", dex, coin, date, o.height, 0, None, "")
    span = f"{one['sms'].min()}-{one['sms'].max()} nb0={one.filter(pl.col('nb') == 0).height} na0={one.filter(pl.col('na') == 0).height}"
    l = LP.get((dex, coin, date))
    if l is None: return ("ok", dex, coin, date, o.height, one.height, None, span)
    # the snapshot before and the snapshot after each liquidation fill
    a = l.join_asof(o.rename({c: c + "_prev" for c in o.columns if c != "sms"}).with_columns(pl.col("sms").alias("sms_prev")), left_on="ms", right_on="sms", strategy="backward").drop("sms")
    a = a.join_asof(o.rename({c: c + "_next" for c in o.columns if c != "sms"}).with_columns(pl.col("sms").alias("sms_next")), left_on="ms", right_on="sms", strategy="forward").drop("sms")
    hit = a.filter(((pl.col("nb_prev") == 0) | (pl.col("na_prev") == 0) | (pl.col("nb_next") == 0) | (pl.col("na_next") == 0)))
    return ("ok", dex, coin, date, o.height, one.height, hit if hit.height else None, span)


def screen_safe(row):
    try: return screen(row)
    except Exception as e: return ("nobook", row[0], row[1], row[2], "ERR " + str(e)[:120])


done = [0]
def prog(row):
    r = screen_safe(row); done[0] += 1
    if done[0] % 2000 == 0: beat(f"screened {done[0]} of {cd.height}")
    return r


with ThreadPoolExecutor(8) as ex: res = list(ex.map(prog, cd.iter_rows()))
nobook = [r for r in res if r[0] == "nobook"]; ok = [r for r in res if r[0] == "ok"]
days = pl.DataFrame([(r[1], r[2], r[3], r[4], r[5], r[6].height if r[6] is not None else 0, f"{r[1]}|{r[2]}|{r[3]}" in newkeys, r[7]) for r in ok if r[5] > 0],
                    schema=["dex", "coin", "date", "snapshots", "one_sided_snapshots", "liquidation_fills_next_to_one", "new_listing", "one_sided_ms_span"], orient="row")
hits = [r[6] for r in ok if r[6] is not None]
buf = io.BytesIO(); days.sort("liquidation_fills_next_to_one", "one_sided_snapshots", descending=True).write_csv(buf); put("onesided_days.csv", buf.getvalue().decode())
if hits:
    H = pl.concat(hits, how="diagonal_relaxed").sort("dex", "coin", "ms"); buf = io.BytesIO(); H.write_csv(buf); put("hits.csv", buf.getvalue().decode())
    both = H.filter(((pl.col("nb_prev") == 0) | (pl.col("na_prev") == 0)) & ((pl.col("nb_next") == 0) | (pl.col("na_next") == 0)))
    log.append(f"hits: {H.height} liquidation fills next to a one-sided snapshot ({both.height} between two one-sided snapshots), {H.select('dex','coin','date').unique().height} coin-days")
    log.append(str(H.group_by("dex", "coin", "date").agg(pl.len().alias("fills"), pl.col("tx_hash").n_unique().alias("txs")).sort("fills", descending=True).head(40)))
else:
    log.append("hits: none")
log.append(f"new-listing coin-days with a one-sided snapshot: {days.filter(pl.col('new_listing')).height}, one-sided minutes {days.filter(pl.col('new_listing'))['one_sided_snapshots'].sum()}")
log.append(f"coin-days screened {cd.height} | 1-minute book missing {len(nobook)} | coin-days with a one-sided snapshot {days.height}")
log += [f"nobook example: {r[1:]}" for r in nobook[:5]]
put("summary.txt", "\n".join(log)); beat("SCREEN DONE")
