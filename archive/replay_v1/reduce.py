"""Turn the extract.py parts of one day into parquet tables for the simulator.

Usage: python reduce.py PARTS_DIR OUT_DIR
Writes OUT_DIR/{blocks,acts,orders,cancels,state,oracle}.parquet:
  blocks   h, t (block time), r, p
  acts     every kept action: h, t, b, i, u, type, json (raw action + statuses)
  orders   one row per sub-order (order / modify / batchModify): h, t, b, i, j, u, type, oid_in (modify target),
           a, side_buy, px, sz, reduce_only, tif, trigger, cloid, grouping, status, oid, filled_sz, avg_px, err
  cancels  one row per cancel: h, t, b, i, j, u, type, a, oid / cloid, status
  state    updateIsolatedMargin / updateLeverage / topUpIsolatedOnlyMargin: h, t, b, i, u, type, asset, fields, ok
  oracle   one row per (setOracle, coin): h, t, b, i, coin, oracle, m1, m2, ext
Rows are sorted in block execution order (h, b, i, j).
"""
import sys, os, glob, gzip, json
import polars as pl

PARTS, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
blocks, acts, orders, cancels, state, oracle = [], [], [], [], [], []


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


def order_row(base, j, od, s, oid_in=None):
    lim = (od.get("t") or {}).get("limit")
    trg = (od.get("t") or {}).get("trigger")
    r = dict(base, j=j, oid_in=str(oid_in) if oid_in is not None else None, a=od.get("a"), side_buy=od.get("b"),
             px=float(od.get("p") or 0), sz=float(od.get("s") or 0), reduce_only=bool(od.get("r")),
             tif=lim.get("tif") if lim else None, trigger=json.dumps(trg) if trg else None, cloid=od.get("c"))
    r.update(st_fields(s))
    return r


for fp in sorted(glob.glob(os.path.join(PARTS, "*.jsonl.gz"))):
    for line in gzip.open(fp, "rt"):
        d = json.loads(line)
        k = d["k"]
        if k == "blk":
            blocks.append(dict(h=d["h"], t=d["t"], r=d.get("r"), p=d.get("p")))
        elif k == "orc":
            m = d["m"] + [{}, {}]
            for coin, px in d["o"].items():
                oracle.append(dict(h=d["h"], t=d["t"], b=d["b"], i=d["i"], coin=coin, oracle=float(px),
                                   m1=float(m[0][coin]) if coin in m[0] else None, m2=float(m[1][coin]) if coin in m[1] else None,
                                   ext=float(d["x"][coin]) if coin in d["x"] else None))
        elif k == "act":
            a, s = d["a"], d["s"]; ty = a["type"]
            base = dict(h=d["h"], t=d["t"], b=d["b"], i=d["i"], u=d["u"], type=ty)
            acts.append(dict(base, fe=d.get("fe"), n=d.get("n"), json=json.dumps({"a": a, "s": s})))
            sl = s if isinstance(s, list) else []
            if ty == "order":
                g = json.dumps(a.get("grouping"))
                for j, od in enumerate(a["orders"]):
                    orders.append(dict(order_row(base, j, od, sl[j] if j < len(sl) else None), grouping=g))
            elif ty == "modify":
                orders.append(order_row(base, 0, a["order"], sl[0] if sl else s, oid_in=a.get("oid")))
            elif ty == "batchModify":
                for j, m in enumerate(a["modifies"]):
                    orders.append(order_row(base, j, m["order"], sl[j] if j < len(sl) else None, oid_in=m.get("oid")))
            elif ty in ("cancel", "cancelByCloid"):
                for j, c in enumerate(a["cancels"]):
                    cancels.append(dict(base, j=j, a=c.get("a", c.get("asset")), oid=str(c.get("o")) if "o" in c else None,
                                        cloid=c.get("cloid"), status=json.dumps(sl[j]) if j < len(sl) else None))
            elif ty in ("updateIsolatedMargin", "updateLeverage", "topUpIsolatedOnlyMargin"):
                ok = isinstance(s, dict) and s.get("status") == "ok"
                state.append(dict(base, asset=a.get("asset"), fields=json.dumps({x: v for x, v in a.items() if x not in ("type", "asset")}), ok=ok))

order_key = ["h", "b", "i", "j"]
for name, rows, key in [("blocks", blocks, ["h"]), ("acts", acts, ["h", "b", "i"]), ("orders", orders, order_key),
                        ("cancels", cancels, order_key), ("state", state, ["h", "b", "i"]), ("oracle", oracle, ["h", "b", "i", "coin"])]:
    df = pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()
    if df.height:
        df = df.with_columns(pl.col("t").str.to_datetime(time_unit="ns")).unique(subset=key, keep="first").sort(key)
    df.write_parquet(os.path.join(OUT, f"{name}.parquet"))
    print(name, df.height)
