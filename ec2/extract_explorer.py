"""Fill a hole of the replica_cmds stream from the node archive's explorer_blocks (same extract format as extract.py).

Why: replica_cmds is cut into folders at the archive node's snapshots, and the stream can stop a few minutes before the
next folder starts (2026-11-05: blocks 1209897580-1209901624, 09:45:08-09:49:50 UTC, are in neither folder).
explorer_blocks (s3://hl-mainnet-node-data/explorer_blocks/<1e8>/<1e5>/<last block>.rmp.lz4, 100 blocks per file:
MessagePack, lz4 frame) has every block: header (height, block_time, proposer) and txs (user, actions, error).

What it has and has not, against replica_cmds:
  same     every signed action, in execution order, with its user: orders, cancels, modifies, scheduleCancel, the margin
           state actions and the relayer's setOracle (oracle, mark components, external prices)
  missing  the exchange's response to each action (order ids, resting / filled / rejected per order, cancel success);
           only a transaction-level error. Bundle structure, nonce, isFrontend and round are not there either.
A signed action with several orders or cancels is listed there as one entry per item: they are merged back (merged()).
So i = the transaction's index in the block and b is rebuilt so that the pipeline's sort keeps the executed order
(see the loop), fe / n / r are null, and the response `s` is INFERRED (INFER=1, the default for a hole):
  transaction error      -> the action did nothing (s = the error: every order skipped, every cancel failed)
  order                  -> placed (resting, order id unknown: sim/prep/oidbind.py binds it from later fills and cancels,
                            as it does for trigger children); the simulator then matches it itself
  cancel / cancelByCloid -> success (if the order is no longer in the book the simulator's cancel is a no-op)
  modify / batchModify   -> ok / placed
INFER=0 writes s = null: the comparison mode, where only the actions are checked against replica_cmds
(sim/prep/explorer_check.py measures both the actions and the inference on blocks present in both sources).

Usage: python extract_explorer.py H_LO H_HI OUT.jsonl.gz ASSETS FILE.rmp.lz4 [FILE ...]   (blocks H_LO..H_HI inclusive)
"""
import sys, os, json, gzip
import msgpack, lz4.frame

H_LO, H_HI, OUT = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
ASSETS = {int(x) for x in sys.argv[4].split(",")}
FILES = sorted(sys.argv[5:], key=lambda f: int(os.path.basename(f).split(".")[0]))
INFER = os.environ.get("INFER", "1") != "0"
XYZ_LO, XYZ_HI = 110000, 120000
STATE = {"updateIsolatedMargin", "updateLeverage", "topUpIsolatedOnlyMargin"}
out = gzip.open(OUT, "wt", compresslevel=5)
w = lambda d: out.write(json.dumps(d, separators=(",", ":")) + "\n")


def pick(items, key):
    return [it for it in items if key(it) in ASSETS]


def infer(ty, keep, err):
    """the response the pipeline reads (ec2/reduce.py), inferred: see the module docstring"""
    if err is not None:
        return {"status": "err", "response": err}
    if not INFER:
        return None
    if ty == "order":
        return [{"resting": {}} for _ in keep["orders"]]
    if ty in ("cancel", "cancelByCloid"):
        return ["success" for _ in keep["cancels"]]
    if ty == "modify":
        return {"status": "ok"}
    if ty == "batchModify":
        return [{"resting": {}} for _ in keep["modifies"]]
    return None


LISTS = {"order": "orders", "cancel": "cancels", "cancelByCloid": "cancels", "batchModify": "modifies"}


def merged(actions):
    """explorer_blocks lists one entry per order / cancel of a signed action (same type, same other fields, one item
    each); replica_cmds keeps the signed action whole. Put them back together, items in their order."""
    if len(actions) <= 1:
        return actions
    ty = actions[0].get("type"); k = LISTS.get(ty)
    rest = lambda a: {x: v for x, v in a.items() if x != k}
    if k is None or any(a.get("type") != ty or rest(a) != rest(actions[0]) for a in actions):
        raise SystemExit(f"explorer transaction with {len(actions)} actions that are not one split action: {[a.get('type') for a in actions]}")
    return [dict(actions[0], **{k: [it for a in actions for it in a[k]]})]


def act_pri(ty, a):
    """Hyperliquid's execution group of an action inside a bundle, on the WHOLE action (every asset): 0 an order action
    whose orders are all post-only, 1 cancels, 2 the rest (an action with one GTC / IOC / trigger order runs after the
    cancels as a whole). Checked against explorer_blocks' executed order: sim/prep/explorer_check.py."""
    alo = lambda od: 0 if ((od.get("t") or {}).get("limit") or {}).get("tif") == "Alo" else 2
    if ty == "order": return max([alo(o) for o in a.get("orders") or []] or [2])
    if ty in ("cancel", "cancelByCloid"): return 1
    if ty == "modify": return alo(a.get("order") or {})
    if ty == "batchModify": return max([alo(m.get("order") or {}) for m in a.get("modifies") or []] or [2])
    return 2


nb = na = no = 0
for fp in FILES:
    blocks = msgpack.unpackb(lz4.frame.decompress(open(fp, "rb").read()), raw=False)
    for blk in blocks:
        hd = blk["header"]; h = hd["height"]
        if h < H_LO or h > H_HI:
            continue
        t = hd["block_time"]
        w({"k": "blk", "h": h, "t": t, "r": None, "p": hd.get("proposer")}); nb += 1
        # b: explorer_blocks lists a block's actions as executed: bundle after bundle and, inside a bundle, post-only
        # placements, then cancels, then the rest. The pipeline sorts each bundle of replica_cmds the same way, by
        # (b, action priority, i, j). A new b starts wherever the priority goes down, so that sort leaves this order unchanged.
        bb, top = 0, 0
        for i, tx in enumerate(blk["txs"]):
            u = str(tx.get("user") or "?").lower(); err = tx.get("error")
            for a in merged(tx["actions"]):
                ty = a.get("type")
                if ty == "perpDeploy":
                    so = a.get("setOracle")
                    if so and so.get("dex") == "xyz" and err is None:
                        if 2 < top: bb += 1
                        top = 2
                        w({"k": "orc", "h": h, "t": t, "b": bb, "i": i, "su": u, "o": dict(so.get("oraclePxs") or []),
                           "m": [dict(m) for m in (so.get("markPxs") or [])], "x": dict(so.get("externalPerpPxs") or [])}); no += 1
                    continue
                keep = None
                if ty == "order":
                    ords = pick(a.get("orders") or [], lambda x: x.get("a"))
                    if ords: keep = dict(a, orders=ords)
                elif ty in ("cancel", "cancelByCloid"):
                    cs = pick(a.get("cancels") or [], lambda x: x.get("a", x.get("asset")))
                    if cs: keep = dict(a, cancels=cs)
                elif ty == "modify":
                    if (a.get("order") or {}).get("a") in ASSETS: keep = a
                elif ty == "batchModify":
                    ms = pick(a.get("modifies") or [], lambda x: (x.get("order") or {}).get("a"))
                    if ms: keep = dict(a, modifies=ms)
                elif ty in ("twapOrder", "twapCancel"):
                    tw = a.get("twap") or a
                    if tw.get("a") in ASSETS: keep = a
                elif ty == "scheduleCancel":
                    keep = a
                elif ty in STATE:
                    if XYZ_LO <= (a.get("asset") or 0) < XYZ_HI: keep = a
                if keep is not None:
                    pa = act_pri(ty, a)                      # on the whole action, before the cut to ASSETS
                    if ty not in STATE:                      # state actions are not events of the book stream
                        if pa < top: bb += 1
                        top = pa
                    if bb >= 64 or i >= (1 << 14): raise SystemExit(f"block {h}: b {bb} or i {i} beyond the pipeline's key range")
                    base = {"h": h, "t": t, "b": bb, "i": i, "u": u, "fe": None, "n": None}
                    w(dict(base, k="act", pa=pa, a=keep, s=infer(ty, keep, err))); na += 1
out.close()
print(f"explorer extract: blocks {nb} (asked {H_LO}..{H_HI}), actions {na}, setOracle {no}", file=sys.stderr)
