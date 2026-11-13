"""Bind order ids that the command stream never returns (single `modify`, trigger orders) to the action that created them.

HL assigns oids from one global counter in execution order, so an order created by action k gets an oid strictly between
the last known oid before k and the first known oid after k (known = returned in a resting / filled status, on this
coin). A later reference (fill, cancel, or a modify / batchModify targeting it) to an unknown oid X by user U is bound to U's unknown-oid action whose
bracket contains X; ties are broken by client order id, then by price and side, when the reference is a fill; what is left is
flagged ambiguous_first. Validated on xyz:GOOGL 2026-10-28:
94% of unseen fill notional binds uniquely, 0 client-order-id mismatches.

Two refinements (2026-11-03), from the TP/SL pairs that were bound to the wrong child:
- sibling: the sub-orders of one action take consecutive oids in j order (99.5% of actions with >= 2 known oids), so an
  unknown sub-order sits at known_oid + (j - j_known) from a known sibling on the same asset.
- trigger tie-break: when several trigger children of one action fit a fill reference, keep the one whose trigger
  condition holds at the oracle of that moment (sell tp / buy sl: oracle >= triggerPx; buy tp / sell sl: oracle <= it).

Usage: python oidbind.py TABLES_DIR FILLS_PARQUET COIN ASSET OUT_PARQUET
Writes one row per bound oid: oid, seq (row of orders.parquet, execution order), u, kind, how
(unique / price / ambiguous_first), plus a coverage report.
"""
import sys, bisect, collections
import polars as pl

T, FILLS, COIN, ASSET, OUT = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]


def bind(orders, refs, orc=None):
    """orders: orders.parquet rows on one asset (execution order). refs: rows (u, oid, px, side_buy, crossed, cloid) that
    reference oids; px/side may be None for cancels. Returns {oid: (seq, kind, how)} for oids not already known.
    The bracket of each unknown-oid action (previous / next known oid in execution order) is computed in polars, so
    only those actions reach Python."""
    unk = (orders.lazy().with_row_index("seq")
           .with_columns(pl.col("oid").cast(pl.Int64).alias("ko"))
           .with_columns(pl.col("ko").shift(1).forward_fill().fill_null(0).alias("lo"),
                         pl.col("ko").shift(-1).backward_fill().fill_null(1 << 62).alias("hi"))
           .filter(((pl.col("type") == "modify") & (pl.col("status").str.contains('"ok"') | pl.col("status").is_null()))
                   | pl.col("status").is_in(["waitingForTrigger", "waitingForFill"])
                   # orders of a stream hole filled from explorer_blocks (ec2/extract_explorer.py): placed, id not returned
                   | ((pl.col("status") == "resting") & pl.col("oid").is_null()))
           .select("seq", "u", "px", "side_buy", "type", "cloid", "lo", "hi", "h", "b", "i", "j",
                   pl.col("trigger").str.json_path_match("$.triggerPx").cast(pl.Float64).alias("tpx"),
                   pl.col("trigger").str.json_path_match("$.tpsl").alias("tpsl")).collect())
    # sibling offsets: unknown sub-order at known_oid + (j - j_known), nearest known sibling of the same action
    kn_rows = (orders.lazy().filter(pl.col("oid").is_not_null()).select("h", "b", "i", pl.col("j").alias("jk"), pl.col("oid").cast(pl.Int64).alias("ok")))
    sib = (unk.lazy().select("seq", "u", "h", "b", "i", "j").join(kn_rows, on=["h", "b", "i"])
           .with_columns((pl.col("j") - pl.col("jk")).abs().alias("dj"))
           .sort("seq", "dj", "jk").unique("seq", keep="first", maintain_order=True)
           .select("seq", "u", (pl.col("ok") + pl.col("j") - pl.col("jk")).alias("cand")).collect())
    cand = {(u, c): sq for sq, u, c in sib.iter_rows()}
    trig_info = {r[0]: (r[2], r[3], r[12], r[13]) for r in unk.iter_rows()}   # seq -> (px, buy, tpx, tpsl)
    act_of = {r[0]: (r[8], r[9], r[10]) for r in unk.iter_rows()}
    known = set()
    by_user = collections.defaultdict(list)
    for r in unk.iter_rows():
        s, u, px, buy, ty, cl, lo, hi = r[:8]
        by_user[u].append((lo, hi, s, px, buy, "modify" if ty == "modify" else "trigger", cl))
    # first reference of each unknown oid, per user; bind in increasing oid order so that a user's bound oids
    # increase with execution order (the counter is global, so it is monotone within any user's subset too)
    first_ref = {}
    for u, x, px, buy, crossed, cl, *t in refs:
        if x in known or (u, x) in first_ref:
            continue
        first_ref[(u, x)] = (px, buy, crossed, cl, *t)
    refs_by_user = collections.defaultdict(list)
    for (u, x), info in first_ref.items():
        refs_by_user[u].append((x, info))
    out = {}
    used = set()
    kind_of = {r[2]: r[5] for rows in by_user.values() for r in rows}
    for (u, x), info in first_ref.items():
        sq = cand.get((u, x))
        if sq is not None:
            out[x] = (sq, kind_of[sq], "sibling")
            used.add(sq)
    oracle_at = None
    if orc is not None:
        import bisect as _b
        ot, op = orc
        oracle_at = lambda t: op[max(0, _b.bisect_right(ot, t) - 1)]
    for u, xs in refs_by_user.items():
        acts = sorted((r for r in by_user.get(u, []) if r[2] not in used), key=lambda r: r[2])
        last = -1                                   # index in acts of the last bound action
        # the brackets (lo, hi) grow with execution order (one global oid counter), so the actions whose bracket holds x
        # are a contiguous run of acts: found by bisection, the same set and order as scanning every action (which the
        # market makers' thousands of modifies made quadratic). Checked, with the scan as fallback.
        los, his = [r[0] for r in acts], [r[1] for r in acts]
        mono = all(los[k] <= los[k + 1] and his[k] <= his[k + 1] for k in range(len(acts) - 1))
        for x, (px, buy, crossed, cl, *rest) in sorted(xs):
            if x in out:
                continue
            if mono:
                ka, kb = max(last + 1, bisect.bisect_right(his, x)), bisect.bisect_left(los, x)
                c = [(k, acts[k]) for k in range(ka, kb)]
            else:
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
            if len(c) > 1 and crossed and oracle_at is not None and rest and rest[0] is not None:
                # trigger children of one action: the one whose condition held when it filled
                ref_px = oracle_at(rest[0])
                def fires(z):
                    _, b_, tpx, tpsl = trig_info[z[1][2]]
                    if tpx is None:
                        return False
                    return ref_px <= tpx if (b_ == (tpsl == "tp")) else ref_px >= tpx
                c2 = [z for z in c if fires(z)]
                if len(c2) == 1 or (c2 and len({act_of[z[1][2]] for z in c}) == 1):
                    c, how = c2, "trigger"
            if len(c) > 1:
                how = "ambiguous_first"
            if c:
                k, r = c[0]
                out[x] = (r[2], r[5], how)
                last = k
    # siblings of a bound sub-order: consecutive oids in j order (overrides an ambiguous guess)
    rows_of_act = collections.defaultdict(list)
    for r in unk.iter_rows():
        rows_of_act[(r[8], r[9], r[10])].append((r[11], r[0], r[1]))
    seq_j = {r[0]: r[11] for r in unk.iter_rows()}
    for x, (sq, kind, how) in list(out.items()):
        if how == "ambiguous_first":
            continue
        for j2, sq2, u2 in rows_of_act[act_of[sq]]:
            if sq2 == sq:
                continue
            x2 = x + j2 - seq_j[sq]
            if (u2, x2) in first_ref and (x2 not in out or out[x2][2] == "ambiguous_first"):
                out[x2] = (sq2, kind_of[sq2], "sibling")
    return out


if __name__ == "__main__":
    # bounded memory: only the needed columns, and only references to oids the stream never returned reach Python
    orders = (pl.scan_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET)
              .select("t", "h", "b", "i", "j", "u", "type", "status", "oid", "px", "side_buy", "cloid", "oid_in", "trigger").collect())
    orders = orders.with_columns(pl.col("type").cast(pl.Categorical))
    t0 = orders["t"].min()
    known_s = orders["oid"].drop_nulls().cast(pl.Int64).unique()
    f = (pl.scan_parquet(FILLS).filter(pl.col("coin") == COIN)
         .select("timestamp", "order_id", "price", "size", "side", "address", "crossed", "client_order_id", "liquidation_method", "twap_id")
         .with_columns(pl.col("timestamp").dt.replace_time_zone(None).cast(pl.Datetime("ns")).alias("t"),
                       pl.col("order_id").cast(pl.Int64).alias("oid"), pl.col("price").cast(float).alias("px"),
                       (pl.col("side") == "buy").alias("buy"), (pl.col("price").cast(float) * pl.col("size").cast(float)).alias("ntl"))
         .filter(pl.col("t") >= t0).collect())
    rs = {"t": pl.Datetime("ns"), "u": pl.String, "oid": pl.Int64, "px": pl.Float64, "buy": pl.Boolean, "crossed": pl.Boolean, "cl": pl.String}
    kn = known_s.implode()
    r_fill = (f.filter(~pl.col("oid").is_in(kn))
              .select("t", pl.col("address").alias("u"), "oid", "px", "buy", "crossed", pl.col("client_order_id").alias("cl")))
    r_canc = (pl.scan_parquet(f"{T}/cancels.parquet").filter(pl.col("a") == ASSET, pl.col("oid").is_not_null())
              .select("t", "u", pl.col("oid").cast(pl.Int64)).filter(~pl.col("oid").is_in(kn)).collect())
    r_mod = (orders.filter(pl.col("type").is_in(["modify", "batchModify"]), pl.col("oid_in").str.contains(r"^[0-9]+$"))
             .select("t", "u", pl.col("oid_in").cast(pl.Int64).alias("oid")).filter(~pl.col("oid").is_in(kn)))
    refs = (pl.concat([r_fill.cast(rs), r_canc.with_columns(px=None, buy=None, crossed=None, cl=None).cast(rs),
                       r_mod.with_columns(px=None, buy=None, crossed=None, cl=None).cast(rs)], how="vertical")
            .filter(~pl.col("oid").is_in(known_s.implode()))
            .sort("t", maintain_order=True).unique(subset=["u", "oid"], keep="first", maintain_order=True))
    del r_canc, r_mod
    # millisecond resolution on both sides: fill times are block times truncated to ms, so the relayer update of the
    # same block (ns-stamped) must count as "at" the fill
    oc = pl.scan_parquet(f"{T}/oracle.parquet").filter(pl.col("coin") == COIN).select((pl.col("t").cast(pl.Int64) // 10**6).alias("t"), "oracle").sort("t").collect()
    m = bind(orders, [(u, x, px, buy, cr, cl, t) for t, u, x, px, buy, cr, cl in
                      refs.select((pl.col("t").cast(pl.Int64) // 10**6).alias("t"), "u", "oid", "px", "buy", "crossed", "cl").iter_rows()],
             orc=(oc["t"].to_list(), oc["oracle"].to_list()))
    pl.DataFrame([dict(oid=k, seq=v[0], kind=v[1], how=v[2]) for k, v in m.items()], schema={"oid": pl.Int64, "seq": pl.Int64, "kind": pl.String, "how": pl.String}).write_parquet(OUT)
    known_all = pl.concat([known_s, pl.Series(list(m.keys()), dtype=pl.Int64)])
    VAULT = "0x4000000000000000000000000000000000000001"
    base = f.filter(pl.col("liquidation_method").is_null(), pl.col("address") != VAULT, pl.col("twap_id").is_null())
    first_oid = known_s.min()
    hows = collections.Counter(v[2] for v in m.values())
    print("bound oids", len(m), dict(hows), "| unknown-oid references", refs.height)
    g = base.with_columns(pl.col("oid").is_in(known_all.implode()).alias("seen"), (pl.col("oid") < first_oid).alias("pre")).group_by("crossed").agg(
        (pl.col("ntl") * pl.col("seen")).sum().truediv(pl.col("ntl").sum()).round(4).alias("seen"),
        (pl.col("ntl") * (~pl.col("seen") & pl.col("pre"))).sum().truediv(pl.col("ntl").sum()).round(4).alias("pre_window"),
        (pl.col("ntl") * (~pl.col("seen") & ~pl.col("pre"))).sum().truediv(pl.col("ntl").sum()).round(4).alias("still_missing"))
    print("all day", g.sort("crossed").to_dicts())
