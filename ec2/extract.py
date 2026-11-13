"""Extract the xyz market-simulator inputs from one replica_cmds file (decompressed JSON lines on stdin).

Usage: lz4 -dc <file> | python3 extract.py MIN_HEIGHT out.jsonl.gz [ASSETS]
  MIN_HEIGHT  first block kept (the snapshot block, so state replays from the snapshot)
  ASSETS      comma-separated HIP-3 asset ids for the order book (default 110012 = xyz:GOOGL)

One JSON object per line, field `k` says the kind:
  blk  every block:   h height, t block time, r round, p proposer
  act  one signed action that touches the book of ASSETS (order, cancel, cancelByCloid, modify,
       batchModify, twapOrder, twapCancel; only the sub-orders on ASSETS are kept, with their
       statuses) or that every book needs (scheduleCancel), or that changes margin state on any xyz
       asset (updateIsolatedMargin, updateLeverage, topUpIsolatedOnlyMargin):
       h, t, b bundle index, i action index (in-block order), u account, fe isFrontend, n nonce,
       a the action (pruned), s statuses / response
  orc  one relayer setOracle on dex xyz: h, t, b, i, o oracle px, m mark components (list of
       {coin: px}), x external perp px
"""
import sys, json, gzip

try:
    import orjson
    loads = orjson.loads
except ImportError:
    loads = json.loads

MIN_H, OUT = int(sys.argv[1]), sys.argv[2]
ASSETS = {int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "110012").split(",")}
XYZ_LO, XYZ_HI = 110000, 120000          # HIP-3 asset id = 100000 + dex_index*10000 + index; xyz = dex 1
STATE = {"updateIsolatedMargin", "updateLeverage", "topUpIsolatedOnlyMargin"}

out = gzip.open(OUT, "wt", compresslevel=5)
w = lambda d: out.write(json.dumps(d, separators=(",", ":")) + "\n")


def statuses(res):
    try:
        return res["response"]["data"]["statuses"]
    except (KeyError, TypeError):
        return None


def pick(items, key, st):
    """Keep the entries of `items` on ASSETS, with the status at the same index."""
    kept = [(j, it) for j, it in enumerate(items) if key(it) in ASSETS]
    if not kept:
        return None, None
    return [it for _, it in kept], ([st[j] if st and j < len(st) else None for j, _ in kept] if st is not None else None)


def act_pri(ty, a):
    """Hyperliquid's execution group of an action inside a bundle, on the WHOLE action (every asset, before the cut to
    ASSETS): 0 an order action whose orders are all post-only, 1 cancels, 2 the rest (an action with one GTC / IOC /
    trigger order runs after the cancels as a whole). Checked against explorer_blocks: sim/prep/explorer_check.py."""
    alo = lambda od: 0 if ((od.get("t") or {}).get("limit") or {}).get("tif") == "Alo" else 2
    if ty == "order": return max([alo(o) for o in a.get("orders") or []] or [2])
    if ty in ("cancel", "cancelByCloid"): return 1
    if ty == "modify": return alo(a.get("order") or {})
    if ty == "batchModify": return max([alo(m.get("order") or {}) for m in a.get("modifies") or []] or [2])
    return 2


bad = 0
for line in sys.stdin.buffer:
    if not line.strip():
        continue
    try:
        o = loads(line)
    except ValueError:
        bad += 1
        continue
    h = o.get("height")
    if h is None or h < MIN_H:
        continue
    ab = o["abci_block"]; t = ab["time"]
    w({"k": "blk", "h": h, "t": t, "r": ab.get("round"), "p": ab.get("proposer")})
    resp = {hh: r for hh, r in (o.get("resps") or {}).get("Full", [])}
    for bi, (bh, b) in enumerate(ab["signed_action_bundles"]):
        rs = resp.get(bh, [])
        for ai, sa in enumerate(b["signed_actions"]):
            a = sa.get("action") or {}
            ty = a.get("type")
            r = rs[ai] if ai < len(rs) else {}
            u = str(r.get("user") or "?").lower()
            res = r.get("res")
            base = {"h": h, "t": t, "b": bi, "i": ai, "u": u, "fe": bool(sa.get("isFrontend")), "n": sa.get("nonce")}
            if ty == "multiSig":
                inner = ((a.get("payload") or {}).get("action") or {})
                so = inner.get("setOracle") if inner.get("type") == "perpDeploy" else None
                if so and so.get("dex") == "xyz":
                    w({"k": "orc", "h": h, "t": t, "b": bi, "i": ai, "su": (a.get("payload") or {}).get("multiSigUser"),
                       "o": dict(so.get("oraclePxs") or []), "m": [dict(m) for m in (so.get("markPxs") or [])],
                       "x": dict(so.get("externalPerpPxs") or [])})
                continue
            st = statuses(res)
            keep = None
            if ty == "order":
                ords, s2 = pick(a.get("orders") or [], lambda x: x.get("a"), st)
                if ords:
                    keep = dict(a, orders=ords); st = s2
            elif ty in ("cancel", "cancelByCloid"):
                cs, s2 = pick(a.get("cancels") or [], lambda x: x.get("a", x.get("asset")), st)
                if cs:
                    keep = dict(a, cancels=cs); st = s2
            elif ty == "modify":
                if (a.get("order") or {}).get("a") in ASSETS:
                    keep = a
            elif ty == "batchModify":
                ms, s2 = pick(a.get("modifies") or [], lambda x: (x.get("order") or {}).get("a"), st)
                if ms:
                    keep = dict(a, modifies=ms); st = s2
            elif ty in ("twapOrder", "twapCancel"):
                tw = a.get("twap") or a
                if tw.get("a") in ASSETS:
                    keep = a
            elif ty == "scheduleCancel":
                keep = a
            elif ty in STATE:
                if XYZ_LO <= (a.get("asset") or 0) < XYZ_HI:
                    keep = a
            if keep is not None:
                w(dict(base, k="act", pa=act_pri(ty, a), a=keep, s=st if st is not None else res))
if bad:
    w({"k": "bad", "n": bad})
out.close()
