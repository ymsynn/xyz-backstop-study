"""Check ec2/extract_explorer.py against the replica_cmds extract on blocks that both sources hold.
1. Actions: per block, the sequence of (user, action) and of setOracle (oracle, mark components, external) must be equal,
   and the block time and proposer too (responses, bundle index, nonce are not in explorer_blocks: not compared).
2. Inference (INFER=1 rule): how the inferred responses compare with the real ones of replica_cmds on the same blocks.
Usage: python sim/prep/explorer_check.py REPLICA_PART.jsonl.gz EXPLORER_EXTRACT.jsonl.gz H_LO H_HI"""
import sys, os, gzip, json, collections
rep, exp, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
def load(fp):
    by = collections.defaultdict(lambda: {"blk": None, "act": [], "orc": []})
    with gzip.open(fp, "rt") as f:
        for line in f:
            d = json.loads(line)
            if lo <= d["h"] <= hi:
                if d["k"] == "blk": by[d["h"]]["blk"] = d
                else: by[d["h"]][d["k"]].append(d)
    return by
canon = lambda a: json.dumps(a, sort_keys=True)
STATE = {"updateIsolatedMargin", "updateLeverage", "topUpIsolatedOnlyMargin"}
def rows(blk):
    alo = lambda od: 0 if ((od.get("t") or {}).get("limit") or {}).get("tif") == "Alo" else 2
    out = []
    for d in blk["act"]:
        a = d["a"]; ty = a["type"]; key = lambda p, j: (d["b"], p, d["i"], j)
        if ty == "order":
            # ACTION_RULE=1: Hyperliquid's rule, the whole action after the cancels unless every order of it is post-only;
            # 0: the pipeline's rule before 2026-11-10, each order row on its own
            pa = max(alo(o) for o in a["orders"]) if os.environ.get("ACTION_RULE", "1") == "1" else None
            out += [(key(pa if pa is not None else alo(o), j), d["u"], "order", canon(o), canon(a.get("grouping"))) for j, o in enumerate(a["orders"])]
        elif ty in ("cancel", "cancelByCloid"): out += [(key(1, j), d["u"], ty, canon(c)) for j, c in enumerate(a["cancels"])]
        elif ty == "modify": out.append((key(alo(a.get("order") or {}), 0), d["u"], ty, canon(a)))
        elif ty == "batchModify":
            pa = max(alo(m.get("order") or {}) for m in a["modifies"]) if os.environ.get("ACTION_RULE", "1") == "1" else None
            out += [(key(pa if pa is not None else alo(m.get("order") or {}), j), d["u"], ty, canon(m)) for j, m in enumerate(a["modifies"])]
        elif ty not in STATE: out.append((key(2, 0), d["u"], ty, canon(a)))
    out += [((d["b"], 2, d["i"], 0), "relayer", "setOracle", canon(d["o"]), canon(d["m"]), canon(d["x"])) for d in blk["orc"]]
    return [z[1:] for z in sorted(out, key=lambda z: z[0])]
R, X = load(rep), load(exp)
st = collections.Counter(); ex = []; real = collections.Counter()
for h in range(lo, hi + 1):
    r, x = R.get(h), X.get(h)
    if r is None or x is None:
        st["blocks missing in " + ("replica" if r is None else "explorer")] += 1; continue
    st["blocks"] += 1
    st["block time and proposer equal"] += (r["blk"]["t"] == x["blk"]["t"] and r["blk"]["p"] == x["blk"]["p"])
    # the pipeline's event rows in its execution order (sim/prep/prep.py KEY: bundle, priority, action, item), from each source
    ra, xa = rows(r), rows(x)
    st["event rows replica"] += len(ra); st["event rows explorer"] += len(xa)
    if ra == xa: st["blocks with identical rows in identical order"] += 1
    else:
        st["blocks DIFFERING"] += 1
        if sorted(ra) == sorted(xa): st["  of which same rows, different order"] += 1
        if len(ex) < 3:
            k = next((n for n, (p, q) in enumerate(zip(ra, xa)) if p != q), min(len(ra), len(xa)))
            ex.append((h, [z[:160] for z in map(str, ra[k:k + 2])], [z[:160] for z in map(str, xa[k:k + 2])]))
    ro = [(canon(d["o"]), canon(d["m"]), canon(d["x"])) for d in r["orc"]]; xo = [(canon(d["o"]), canon(d["m"]), canon(d["x"])) for d in x["orc"]]
    st["setOracle replica"] += len(ro); st["setOracle explorer"] += len(xo); st["blocks with equal setOracle"] += (ro == xo)
    # the real responses, by kind: what the inference replaces
    for d in r["act"]:
        a, s = d["a"], d["s"]; ty = a["type"]
        if ty == "order":
            sl = s if isinstance(s, list) else [None] * len(a["orders"])
            for o, z in zip(a["orders"], sl):
                kind = "action error" if not isinstance(s, list) else ("resting" if isinstance(z, dict) and "resting" in z else "filled" if isinstance(z, dict) and "filled" in z
                        else "error: " + str(z.get("error"))[:38] if isinstance(z, dict) and "error" in z else str(z)[:30])
                real[("order", kind)] += 1
        elif ty in ("cancel", "cancelByCloid"):
            sl = s if isinstance(s, list) else [None] * len(a["cancels"])
            for z in sl:
                real[("cancel", "action error" if not isinstance(s, list) else "success" if z == "success" else "failed (already gone)" if isinstance(z, dict) else str(z)[:30])] += 1
print(f"blocks {lo}..{hi}")
for k, v in st.items(): print("  ", k, v)
for e in ex: print("   first difference in block", e[0], "\n     replica: ", e[1], "\n     explorer:", e[2])
tot = collections.Counter()
for (a, k), v in real.items(): tot[a] += v
print("real responses on these blocks (what the hole lacks):")
for (a, k), v in sorted(real.items(), key=lambda z: (z[0][0], -z[1])): print(f"   {a:7s} {k:42s} {v:7d}  {v / tot[a]:6.1%}")
