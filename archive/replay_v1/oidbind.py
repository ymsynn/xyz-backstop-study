"""Bind order ids that the command stream never returns (single `modify`, trigger orders) to the action that created them.

HL assigns oids from one global counter in execution order, so an order created by action k gets an oid strictly between
the last known oid before k and the first known oid after k (known = returned in a resting / filled status, on this
coin). A later reference (fill, cancel, or a modify / batchModify targeting it) to an unknown oid X by user U is bound to U's unknown-oid action whose
bracket contains X; ties are broken by client order id, then by price and side, when the reference is a fill; what is left is
flagged ambiguous_first. Validated on xyz:GOOGL 2026-10-28:
94% of unseen fill notional binds uniquely, 0 client-order-id mismatches.

Usage: python oidbind.py TABLES_DIR FILLS_PARQUET COIN ASSET OUT_PARQUET
Writes one row per bound oid: oid, seq (row of orders.parquet, execution order), u, kind, how
(unique / price / ambiguous_first), plus a coverage report.
"""
import sys, bisect, collections
import polars as pl

T, FILLS, COIN, ASSET, OUT = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]


def bind(orders, refs):
    """orders: orders.parquet rows on one asset (execution order). refs: rows (u, oid, px, side_buy, crossed) that reference
    oids; px/side may be None for cancels. Returns {oid: (seq, kind, how)} for oids not already known."""
    o = orders.with_row_index("seq")
    k = o.filter(pl.col("oid").is_not_null())
    seqs, oids = k["seq"].to_list(), k["oid"].cast(pl.Int64).to_list()
    known = set(oids)
    unk = o.filter(((pl.col("type") == "modify") & (pl.col("status").str.contains('"ok"') | pl.col("status").is_null()))
                   | pl.col("status").is_in(["waitingForTrigger", "waitingForFill"]))
    by_user = collections.defaultdict(list)
    for s, u, px, buy, ty, cl in unk.select("seq", "u", "px", "side_buy", "type", "cloid").iter_rows():
        i = bisect.bisect_left(seqs, s)
        lo = oids[i - 1] if i > 0 else 0
        hi = oids[i] if i < len(oids) else 1 << 62
        by_user[u].append((lo, hi, s, px, buy, "modify" if ty == "modify" else "trigger", cl))
    # first reference of each unknown oid, per user; bind in increasing oid order so that a user's bound oids
    # increase with execution order (the counter is global, so it is monotone within any user's subset too)
    first_ref = {}
    for u, x, px, buy, crossed, cl in refs:
        if x in known or (u, x) in first_ref:
            continue
        first_ref[(u, x)] = (px, buy, crossed, cl)
    refs_by_user = collections.defaultdict(list)
    for (u, x), info in first_ref.items():
        refs_by_user[u].append((x, info))
    out = {}
    for u, xs in refs_by_user.items():
        acts = sorted(by_user.get(u, []), key=lambda r: r[2])
        last = -1                                   # index in acts of the last bound action
        for x, (px, buy, crossed, cl) in sorted(xs):
            c = [(k, r) for k, r in enumerate(acts) if k > last and r[0] < x < r[1]]
            how = "unique"
            if len(c) > 1 and cl is not None:
                c2 = [z for z in c if z[1][6] == cl]
                if c2:
                    c, how = c2, "cloid"
            if len(c) > 1 and px is not None:
                c2 = [z for z in c if z[1][4] == buy and (abs(z[1][3] - px) < 1e-9 if not crossed else True)]
                if c2:
                    c, how = c2, "price"
            if len(c) > 1:
                how = "ambiguous_first"
            if c:
                k, r = c[0]
                out[x] = (r[2], r[5], how)
                last = k
    return out


if __name__ == "__main__":
    orders = pl.read_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET)
    t0 = orders["t"].min()
    f = (pl.scan_parquet(FILLS).filter(pl.col("coin") == COIN).collect()
         .with_columns(pl.col("timestamp").dt.replace_time_zone(None).cast(pl.Datetime("ns")).alias("t"),
                       pl.col("order_id").cast(pl.Int64).alias("oid"), pl.col("price").cast(float).alias("px"),
                       (pl.col("side") == "buy").alias("buy"), (pl.col("price").cast(float) * pl.col("size").cast(float)).alias("ntl"))
         .filter(pl.col("t") >= t0).sort("t"))
    c = pl.read_parquet(f"{T}/cancels.parquet").filter(pl.col("a") == ASSET, pl.col("oid").is_not_null())
    mref = orders.filter(pl.col("type").is_in(["modify", "batchModify"]), pl.col("oid_in").str.contains(r"^[0-9]+$"))
    refs = sorted([tuple(r) for r in f.select("t", "address", "oid", "px", "buy", "crossed", "client_order_id").iter_rows()]
                  + [(r[0], r[1], int(r[2]), None, None, None, None) for r in c.select("t", "u", "oid").iter_rows()]
                  + [(r[0], r[1], int(r[2]), None, None, None, None) for r in mref.select("t", "u", "oid_in").iter_rows()], key=lambda z: z[0])
    m = bind(orders, [r[1:] for r in refs])
    pl.DataFrame([dict(oid=k, seq=v[0], kind=v[1], how=v[2]) for k, v in m.items()]).write_parquet(OUT)
    known = set(orders["oid"].drop_nulls().cast(pl.Int64).to_list()) | set(m)
    VAULT = "0x4000000000000000000000000000000000000001"
    base = f.filter(pl.col("liquidation_method").is_null(), pl.col("address") != VAULT, pl.col("twap_id").is_null())
    first_oid = orders["oid"].drop_nulls().cast(pl.Int64).min()
    hows = collections.Counter(v[2] for v in m.values())
    print("bound oids", len(m), dict(hows))
    import datetime as dt
    crash = (pl.col("t") >= dt.datetime(2026, 10, 28, 20, 1, 50)) & (pl.col("t") <= dt.datetime(2026, 10, 28, 20, 5))
    for name, flt in [("all day", pl.lit(True)), ("crash", crash)]:
        g = base.filter(flt).with_columns(pl.col("oid").is_in(list(known)).alias("seen"), (pl.col("oid") < first_oid).alias("pre")).group_by("crossed").agg(
            (pl.col("ntl") * pl.col("seen")).sum().truediv(pl.col("ntl").sum()).round(4).alias("seen"),
            (pl.col("ntl") * (~pl.col("seen") & pl.col("pre"))).sum().truediv(pl.col("ntl").sum()).round(4).alias("pre_window"),
            (pl.col("ntl") * (~pl.col("seen") & ~pl.col("pre"))).sum().truediv(pl.col("ntl").sum()).round(4).alias("still_missing"))
        print(name, g.sort("crossed").to_dicts())
