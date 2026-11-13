"""Turn the extract.py parts of one day into parquet tables for the simulator, in bounded memory.

Usage: python reduce.py PARTS_DIR OUT_DIR
Each part (one 10k-block file, already in execution order) is converted on its own into small per-table parquet files
(OUT_DIR/_parts/<table>/<part>_<chunk>.parquet, flushed every 200k rows); each table is then streamed into OUT_DIR/<table>.parquet with polars
sink_parquet, in part order. Peak memory = one part (a few hundred MB), whatever the day size.

Tables:
  blocks   h, t (block time), r, p
  acts     every kept action, slim: h, t, b, i, u, type, fe, n, time (scheduleCancel time, ms; null otherwise)
  orders   one row per sub-order (order / modify / batchModify): h, t, b, i, j, u, type, oid_in (modify target), a, pa,
           side_buy, px, sz, reduce_only, tif, trigger, cloid, grouping, status, oid, filled_sz, avg_px, err
  cancels  one row per cancel: h, t, b, i, j, u, type, a, oid / cloid, status
  state    updateIsolatedMargin / updateLeverage / topUpIsolatedOnlyMargin: h, t, b, i, u, type, asset, fields, ok
  oracle   one row per (setOracle, coin): h, t, b, i, coin, oracle, m1, m2, ext
"""
import sys, os, glob, gzip, json, shutil
import polars as pl

PARTS, OUT = sys.argv[1], sys.argv[2]
TMP = os.path.join(OUT, "_parts")
os.makedirs(OUT, exist_ok=True)

S, I, F, B = pl.String, pl.Int64, pl.Float64, pl.Boolean
SCHEMA = {
    "blocks": {"h": I, "t": S, "r": I, "p": S},
    "acts": {"h": I, "t": S, "b": I, "i": I, "u": S, "type": S, "fe": B, "n": I, "time": I},
    "orders": {"h": I, "t": S, "b": I, "i": I, "j": I, "u": S, "type": S, "oid_in": S, "a": I, "side_buy": B, "px": F, "sz": F,
               "reduce_only": B, "tif": S, "trigger": S, "cloid": S, "grouping": S, "status": S, "oid": I, "filled_sz": F,
               "avg_px": F, "err": S, "pa": I},
    "cancels": {"h": I, "t": S, "b": I, "i": I, "j": I, "u": S, "type": S, "a": I, "oid": S, "cloid": S, "status": S},
    "state": {"h": I, "t": S, "b": I, "i": I, "u": S, "type": S, "asset": I, "fields": S, "ok": B},
    "oracle": {"h": I, "t": S, "b": I, "i": I, "coin": S, "oracle": F, "m1": F, "m2": F, "ext": F},
}


def st_fields(s):
    if not isinstance(s, dict):
        return dict(status=str(s) if s is not None else None)
    if "resting" in s:
        return dict(status="resting", oid=s["resting"].get("oid"))
    if "filled" in s:
        f = s["filled"]
        return dict(status="filled", oid=f.get("oid"), filled_sz=float(f.get("totalSz") or 0), avg_px=float(f.get("avgPx") or 0))
    if "error" in s:
        return dict(status="error", err=s["error"])
    return dict(status=json.dumps(s)[:80])


def order_row(base, j, od, s, oid_in=None, grouping=None):
    lim = (od.get("t") or {}).get("limit")
    trg = (od.get("t") or {}).get("trigger")
    r = dict(base, j=j, oid_in=str(oid_in) if oid_in is not None else None, a=od.get("a"), side_buy=od.get("b"),
             px=float(od.get("p") or 0), sz=float(od.get("s") or 0), reduce_only=bool(od.get("r")),
             tif=lim.get("tif") if lim else None, trigger=json.dumps(trg) if trg else None, cloid=od.get("c"), grouping=grouping)
    r.update(st_fields(s))
    return r


CHUNK = 200_000


def flush(rows, tag, counts, force=False):
    """Write every table buffer that reached CHUNK rows (or all of them when force) to its own small parquet file."""
    for name, rs in rows.items():
        if rs and (force or len(rs) >= CHUNK):
            os.makedirs(os.path.join(TMP, name), exist_ok=True)
            k = counts[name] = counts.get(name, 0) + 1
            (pl.DataFrame(rs, schema=SCHEMA[name]).with_columns(pl.col("t").str.to_datetime(time_unit="ns"))
             .write_parquet(os.path.join(TMP, name, f"{tag}_{k:04d}.parquet")))
            rs.clear()


def convert(fp, tag):
    rows = {k: [] for k in SCHEMA}
    counts, n = {}, {k: 0 for k in SCHEMA}
    with gzip.open(fp, "rt") as fh:
        for line in fh:
            if sum(len(v) for v in rows.values()) >= CHUNK:
                for k2, v in rows.items():
                    n[k2] += len(v)
                flush(rows, tag, counts, force=True)
            d = json.loads(line)
            k = d["k"]
            if k == "blk":
                rows["blocks"].append(dict(h=d["h"], t=d["t"], r=d.get("r"), p=d.get("p")))
            elif k == "orc":
                m = d["m"] + [{}, {}]
                for coin, px in d["o"].items():
                    rows["oracle"].append(dict(h=d["h"], t=d["t"], b=d["b"], i=d["i"], coin=coin, oracle=float(px),
                                               m1=float(m[0][coin]) if coin in m[0] else None, m2=float(m[1][coin]) if coin in m[1] else None,
                                               ext=float(d["x"][coin]) if coin in d["x"] else None))
            elif k == "act":
                a, s = d["a"], d["s"]; ty = a["type"]
                base = dict(h=d["h"], t=d["t"], b=d["b"], i=d["i"], u=d["u"], type=ty)
                pa = d.get("pa")       # the action's execution group (extract.py act_pri); null in parts made before it
                rows["acts"].append(dict(base, fe=d.get("fe"), n=d.get("n"), time=a.get("time") if ty == "scheduleCancel" else None))
                sl = s if isinstance(s, list) else []
                if ty == "order":
                    g = json.dumps(a.get("grouping"))
                    for j, od in enumerate(a["orders"]):
                        rows["orders"].append(dict(order_row(base, j, od, sl[j] if j < len(sl) else None, grouping=g), pa=pa))
                elif ty == "modify":
                    rows["orders"].append(dict(order_row(base, 0, a["order"], sl[0] if sl else s, oid_in=a.get("oid")), pa=pa))
                elif ty == "batchModify":
                    for j, m in enumerate(a["modifies"]):
                        rows["orders"].append(dict(order_row(base, j, m["order"], sl[j] if j < len(sl) else None, oid_in=m.get("oid")), pa=pa))
                elif ty in ("cancel", "cancelByCloid"):
                    for j, c in enumerate(a["cancels"]):
                        rows["cancels"].append(dict(base, j=j, a=c.get("a", c.get("asset")), oid=str(c.get("o")) if "o" in c else None,
                                                    cloid=c.get("cloid"), status=json.dumps(sl[j]) if j < len(sl) else None))
                elif ty in ("updateIsolatedMargin", "updateLeverage", "topUpIsolatedOnlyMargin"):
                    ok = isinstance(s, dict) and s.get("status") == "ok"
                    rows["state"].append(dict(base, asset=a.get("asset"), fields=json.dumps({x: v for x, v in a.items() if x not in ("type", "asset")}), ok=ok))
    for k2, v in rows.items():
        n[k2] += len(v)
    flush(rows, tag, counts, force=True)
    return n


def _one(fp):
    return convert(fp, os.path.basename(fp).split(".")[0])


def _order(path):   # (first block of the part, chunk number): execution order, whatever the digits of the block number
    a, k = os.path.basename(path).rsplit(".", 1)[0].rsplit("_", 1)
    return int(a), int(k)


if __name__ == "__main__":
    import multiprocessing as mp
    parts = sorted(glob.glob(os.path.join(PARTS, "*.jsonl.gz")), key=lambda f: int(os.path.basename(f).split(".")[0]))
    tot = {k: 0 for k in SCHEMA}
    # parts are independent (each writes its own files, named by its first block), so they convert in parallel; the
    # tables are then assembled in part order, so the result does not depend on the number of workers
    # spawn, not fork: polars' thread pool does not survive a fork
    with mp.get_context("spawn").Pool(int(os.environ.get("REDUCE_PROCS", os.cpu_count() or 1))) as pool:
        for n, res in enumerate(pool.imap(_one, parts)):
            for k, v in res.items():
                tot[k] += v
            if n % 20 == 0:
                print(f"  part {n + 1}/{len(parts)}", flush=True)
    for name in SCHEMA:
        files = sorted(glob.glob(os.path.join(TMP, name, "*.parquet")), key=_order)
        out = os.path.join(OUT, f"{name}.parquet")
        if not files:
            pl.DataFrame(schema=SCHEMA[name]).write_parquet(out)
            continue
        pl.scan_parquet(files).sink_parquet(out)
        print(name, tot[name])
    shutil.rmtree(TMP)
