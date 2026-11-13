"""Phase 1: replay the xyz:GOOGL order book block by block from the command-stream extract and check it against reality.

Usage: python replay_book.py TABLES_DIR FILLS_PARQUET OB1M_PARQUET [ORDERING] [ENGINE_POS]
  ORDERING    proposer (actions in bundle / action order) | hl (per bundle: cancels, then post-only, then the rest)
  ENGINE_POS  end | start   where engine-generated takers (liquidations, vault, TWAP, triggered stops) sit in a block

Status-driven: an order the protocol rejected for a non-book reason (margin, reduce-only, ...) is skipped; every
other order is matched against the simulated book and its outcome is compared with the real one.
Checks (all day and 18:00-22:00):
  orders   real status vs simulated (post-only reject, IOC no-match, filled size)
  trades   real (taker oid, maker oid) fills vs simulated, notional-weighted
  echo     best bid / ask quoted in post-only rejections vs the simulated book at that moment
  l2       hydromancer 1-min book (top 5 levels) vs the simulated book after that block
"""
import sys, os, re, json, heapq, collections, datetime as dt
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from book import Book, Order, q, SCALE

T, FILLS, OB1M = sys.argv[1:4]
ORDERING = sys.argv[4] if len(sys.argv) > 4 else "proposer"
ENGINE_POS = sys.argv[5] if len(sys.argv) > 5 else "end"
COIN, ASSET = "xyz:GOOGL", 110012
VAULT = "0x4000000000000000000000000000000000000001"
W0, W1 = dt.datetime(2026, 10, 28, 18), dt.datetime(2026, 10, 28, 22)

# ---------------------------------------------------------------- load
blocks = pl.read_parquet(f"{T}/blocks.parquet").select("h", "t")
h_of_ms = dict(zip((blocks["t"].cast(pl.Int64) // 10**6).to_list(), blocks["h"].to_list()))
t_of_h = dict(zip(blocks["h"].to_list(), (blocks["t"].cast(pl.Int64) // 10**6).to_list()))
H0 = blocks["h"].min()
orders = pl.read_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET).with_row_index("seq")
bind = dict(pl.read_parquet(f"{T}/oid_bind_{COIN.split(':')[1]}.parquet").select("seq", "oid").iter_rows())
cancels = pl.read_parquet(f"{T}/cancels.parquet").filter(pl.col("a") == ASSET)
users = set(orders["u"].unique().to_list())
sched = (pl.read_parquet(f"{T}/acts.parquet", columns=["h", "b", "i", "u", "type", "json"])
         .filter(pl.col("type") == "scheduleCancel", pl.col("u").is_in(list(users))))
first_oid = orders["oid"].drop_nulls().cast(pl.Int64).min()

f = (pl.scan_parquet(FILLS).filter(pl.col("coin") == COIN).collect()
     .with_columns((pl.col("timestamp").cast(pl.Int64)).alias("ms"), pl.col("order_id").cast(pl.Int64).alias("oid"),
                   pl.col("price").cast(float).alias("px"), pl.col("size").cast(float).alias("sz")))
mk = f.filter(~pl.col("crossed")).select("trade_id", "ms", "px", "sz", pl.col("oid").alias("m_oid"), pl.col("address").alias("m_u"), pl.col("side").alias("m_side"))
tk = f.filter(pl.col("crossed")).select("trade_id", pl.col("oid").alias("t_oid"), pl.col("address").alias("t_u"), "twap_id", "liquidation_method")
trades = mk.join(tk, on="trade_id", how="inner").filter(pl.col("liquidation_method").fill_null("") != "backstop")
trades = trades.with_columns(pl.col("ms").replace_strict(h_of_ms, default=None).alias("h")).filter(pl.col("h").is_not_null())
print(f"trades {trades.height} (unmapped to a block dropped), orders {orders.height}, cancels {cancels.height}, scheduleCancel {sched.height}")

# oids of user orders the simulator executes itself (non-trigger)
def real_oid(seq, oid):
    if oid is not None:
        return int(oid)
    return bind.get(seq, -(seq + 1))          # synthetic (negative) when never referenced again
sim_taker = set()
trigger_oids = set()
for seq, oid, trg in orders.select("seq", "oid", "trigger").iter_rows():
    ro = real_oid(seq, oid)
    (trigger_oids if trg else sim_taker).add(ro)
inject = trades.filter(~pl.col("t_oid").is_in(list(sim_taker)))
inject_by_h = collections.defaultdict(list)
for r in inject.select("h", "m_oid", "sz", "trade_id").iter_rows():
    inject_by_h[r[0]].append((r[1], q(r[2]), r[3]))
real_tr = trades.filter(pl.col("t_oid").is_in(list(sim_taker)))
MATCH = os.environ.get("MATCH", "tape")      # tape: follow the real makers (baseline replay) | engine: pure price-time
real_fills = collections.defaultdict(list)
for t_oid, m_oid, sz in real_tr.sort("trade_id").select("t_oid", "m_oid", "sz").iter_rows():
    real_fills[t_oid].append((m_oid, q(sz)))
match_cancels = collections.Counter()
miss_why = collections.Counter()
mc_log = []
prio_log = []
print(f"engine-taker trades injected {inject.height} (${(inject['px']*inject['sz']).sum()/1e6:.1f}M), user-taker trades to reproduce {real_tr.height}")

# ---------------------------------------------------------------- events
# kind: 0 cancel, 1 cancelByCloid, 2 schedule, 3 order-like (order / modify / batchModify item)
ev = []
for r in cancels.select("h", "b", "i", "j", "u", "type", "oid", "cloid", "status").iter_rows():
    ev.append((r[0], r[1], r[2], r[3], 0 if r[5] == "cancel" else 1, r))
for r in sched.select("h", "b", "i", "u", "json").iter_rows():
    tm = json.loads(r[4])["a"].get("time")
    ev.append((r[0], r[1], r[2], 0, 2, (r[3], tm)))
cols = ["seq", "h", "b", "i", "j", "u", "type", "oid_in", "side_buy", "px", "sz", "tif", "trigger", "cloid", "status", "oid", "filled_sz", "err", "t"]
for r in orders.select(cols).iter_rows():
    ev.append((r[1], r[2], r[3], r[4], 3, r))


ORC_POS = os.environ.get("ORC_POS", "with_nonorders")   # with_nonorders | before_orders
if os.environ.get("ORC_LOG"):
    for r in pl.read_parquet(f"{T}/oracle.parquet").filter(pl.col("coin") == COIN).select("h", "b", "i", "m1", "m2").iter_rows():
        ev.append((r[0], r[1], r[2], 0, 5, r))


def ordkey(e):
    h, b, i, j, k, r = e
    if k == 5 and ORDERING.startswith("orders_first") and ORC_POS == "before_orders":
        return (h, b, -1, i, j) if ORDERING == "orders_first_bundle" else (h, -1, b, i, j)
    if ORDERING == "orders_first_bundle":       # per bundle: orders (proposer order), then cancels / schedules
        return (h, b, 0 if k == 3 else 1, i, j)
    if ORDERING == "orders_first_block":        # per block: all orders, then all cancels / schedules
        return (h, 0 if k == 3 else 1, b, i, j)
    if ORDERING == "hl":
        if k in (0, 1, 2):
            pri = 0
        elif k == 3 and r[11] == "Alo":
            pri = 1
        else:
            pri = 2
        return (h, b, pri, i, j)
    return (h, b, i, j)


ev.sort(key=ordkey)
print("events", len(ev))

# ---------------------------------------------------------------- replay
B = Book()
# seed orders resting since before the extract starts (seen only as makers in the tape)
pre = trades.filter(pl.col("m_oid") < first_oid).group_by("m_oid").agg(pl.col("m_u").first(), pl.col("m_side").first(), pl.col("px").first(), pl.col("sz").sum())
for oid, u, side, px, sz in pre.iter_rows():
    B.rest(Order(oid, u, side == "buy", q(px), q(sz), "Gtc", None, -1))
print("seeded pre-window resting orders", pre.height)

last_px = [None]
orc_log = []
schedule = {}                      # user -> time ms
sheap = []
sim_tr = collections.Counter()     # (taker oid, maker oid) -> sz
chk = collections.Counter()
_w0 = int(W0.replace(tzinfo=dt.timezone.utc).timestamp() * 1000); _w1 = int(W1.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
inwin = lambda h: _w0 <= t_of_h.get(h, 0) < _w1
ob = pl.read_parquet(OB1M)
ob_at = {r[0]: r for r in ob.select("block_number", "bids", "asks").iter_rows()}
l2c = collections.Counter()
ECHO = re.compile(r"bbo was ([0-9]+(?:\.[0-9]+)?)@([0-9]+(?:\.[0-9]+)?)")
cur_h = None


def tick(name, ok, h):
    chk[(name, ok)] += 1
    if inwin(h):
        chk[(name + "_win", ok)] += 1


bbo_log = []
liq_blocks = set()
if os.environ.get("BBO_LOG"):
    _L = pl.read_parquet(os.environ["LIQ"]).filter(pl.col("coin") == COIN)
    liq_blocks = set(_L.with_columns(pl.col("timestamp").cast(pl.Int64).replace_strict(h_of_ms, default=None).alias("h"))["h"].drop_nulls().to_list())


def end_block(h):
    if os.environ.get("BBO_LOG"):
        bbo_log.append((h, B.best_bid(), B.best_ask()))
    if ENGINE_POS == "end":
        for m_oid, sz, _ in inject_by_h.get(h, ()):
            mo = B.by_oid.get(m_oid)
            if mo is not None:
                last_px[0] = mo.px
            tick("inject_maker_found", B.fill_maker(m_oid, sz) or m_oid in trigger_oids, h)
    snap = ob_at.get(h)
    if snap is not None:
        for buy, lv in ((True, snap[1]), (False, snap[2])):
            real = [(q(x["px"]), q(x["sz"])) for x in lv[:5]]
            sim = [(px, s) for px, s, _ in B.levels(buy, 5)]
            l2c[("best_px", real[:1] and sim[:1] and real[0][0] == sim[0][0])] += 1
            l2c[("top5_exact", real == sim)] += 1
            l2c[("top5_px", [p for p, _ in real] == [p for p, _ in sim])] += 1


def start_block(h):
    t = t_of_h.get(h)
    while sheap and t is not None and sheap[0][0] <= t:
        tm, u = heapq.heappop(sheap)
        if schedule.get(u) == tm:
            B.cancel_user(u)
            del schedule[u]
    if ENGINE_POS == "start":
        for m_oid, sz, _ in inject_by_h.get(h, ()):
            tick("inject_maker_found", B.fill_maker(m_oid, sz) or m_oid in trigger_oids, h)


def tape_match(oid, u, buy, p, s, h):
    """Walk the book in priority order; fill the makers the tape says this taker hit; a better-priority maker the
    taker skipped was cancelled at match time (margin / reduce-only / self-trade): remove it and count it."""
    want = collections.OrderedDict()
    for m_oid, sz in real_fills.get(oid, ()):
        want[m_oid] = want.get(m_oid, 0) + sz
    fills, rem = [], s
    side = B.asks if buy else B.bids
    while want and rem > 0 and side:
        lvl = side.peekitem(0 if buy else -1)[0]
        if (buy and lvl > p) or ((not buy) and lvl < p):
            break
        dq = side[lvl]
        if not dq:
            del side[lvl]; continue
        m = dq[0]
        if m.oid in want:
            if os.environ.get("PRIO_LOG") and len(prio_log) < 300000:
                older = [x for x in dq if x.oid < m.oid and x.oid not in want and x is not m]
                prio_log.append((h, oid, m.oid, m.seq, lvl, len(older), older[0].oid if older else None, older[0].seq if older else None, len(dq)))
            f = min(want.pop(m.oid), m.sz, rem)
            fills.append((m, lvl, f)); m.sz -= f; rem -= f
            if m.sz <= 0:
                B.remove(m.oid, "filled")
        else:
            match_cancels["self" if m.user == u else "other"] += 1
            if len(mc_log) < 200000:
                mc_log.append((h, oid, m.oid, m.seq, m.user, m.buy, m.px, m.sz, lvl, p, tuple(want.keys())[:3]))
            tick("match_cancel_window", True, h)
            B.remove(m.oid, "match_cancel")
    for m_oid, sz in want.items():               # real makers the simulated book does not have at a reachable price
        tick("tape_maker_in_book", False, h)
        mo = B.by_oid.get(m_oid)
        miss_why[("in_book_unreachable" if mo else "gone:" + B.gone.get(m_oid, "never_placed")) +
                 ("" if mo is None else (":worse_px" if (mo.px > p if buy else mo.px < p) else ":same_side?"))] += 1
        if B.fill_maker(m_oid, sz):
            pass
    if fills:
        tick("tape_maker_in_book", True, h)
    if real_fills.get(oid) is None and rem == s:
        pass
    return fills, rem


PRUNE = os.environ.get("PRUNE", "1") == "1"
pruned = collections.Counter()
pruned_log = []


def prune_better(buy_side, px, h, why):
    """Remove resting orders on side `buy_side` strictly better than px (they cannot have existed in reality)."""
    side = B.bids if buy_side else B.asks
    while side:
        lvl = side.peekitem(-1 if buy_side else 0)[0]
        if (buy_side and lvl <= px) or ((not buy_side) and lvl >= px):
            break
        for m in list(side[lvl]):
            pruned[(why, m.tif)] += 1
            if len(pruned_log) < 500000:
                pruned_log.append((h, m.oid, m.seq, m.user, buy_side, m.px, m.sz, why))
            B.remove(m.oid, "pruned_" + why)
        if lvl in side and not side[lvl]:
            del side[lvl]


def tape_walk(oid, u, buy, p, s, h):
    if os.environ.get("TRACE") and int(os.environ["TRACE"]) == oid:
        lv = (B.asks if buy else B.bids)
        print("TRACE taker", oid, u, "buy" if buy else "sell", p / SCALE, s / SCALE, "real", real_fills.get(oid))
        for L in (list(lv.keys())[:4] if buy else list(reversed(lv.keys()))[:4]):
            print("   lvl", L / SCALE, [(o.oid, o.user[:8], o.sz / SCALE) for o in lv[L]])
    """Real fills, applied while walking the book in priority order up to the limit: the taker's own resting orders
    met on the way are cancelled (self-trade prevention, expire maker); other makers the taker did not hit stay live."""
    want = {}
    for m_oid, sz in real_fills.get(oid, ()):
        want[m_oid] = want.get(m_oid, 0) + sz
    fills, rem, stp = [], s, []
    side = B.asks if buy else B.bids
    levels = list(side.keys()) if buy else list(reversed(side.keys()))
    for lvl in levels:
        if not want:
            break
        if (buy and lvl > p) or ((not buy) and lvl < p):
            break
        for m in list(side.get(lvl, ())):
            if not want:
                break
            if m.user == u:
                stp.append(m.oid)
            elif m.oid in want:
                f = want.pop(m.oid)
                fills.append((m, lvl, f)); rem -= f
                B.fill_maker(m.oid, f)
                last_px[0] = lvl
    for m_oid, sz in want.items():
        tick("tape_maker_in_book", False, h)
        B.fill_maker(m_oid, sz); rem -= sz
    if real_fills.get(oid):
        tick("tape_maker_in_book", True, h)
    if rem > 0:                                  # size left: matching went on; own orders met are expired (STP),
        done = False                             # the first other maker means the book stopped there for real
        for lvl in levels:
            if done or ((buy and lvl > p) or ((not buy) and lvl < p)):
                break
            for m in list(side.get(lvl, ())):
                if m.user == u:
                    if m.oid not in stp:
                        stp.append(m.oid)
                elif m.live and m.oid in B.by_oid:
                    done = True
                    break
    for x in stp:
        if B.remove(x, "selftrade") is not None:
            tick("stp_cancel", True, h)
    if os.environ.get("TRACE") and int(os.environ["TRACE"]) == oid:
        print("TRACE after: rem", rem / SCALE, "stp", stp, "live after:", [x for x in stp if x in B.by_oid])
    return fills, rem


def place(r, oid):
    seq, h, b, i, j, u, ty, oid_in, buy, px, sz, tif, trg, cloid, status, _, filled_sz, err, t = r
    p, s = q(px), q(sz)
    if tif == "Alo":
        if B.would_cross(buy, p):
            tick("alo_accepted_but_sim_crosses", False, h)
            if PRUNE:
                prune_better(not buy, p + (1 if buy else -1), h, "alo_accepted")
        B.rest(Order(oid, u, buy, p, s, tif, cloid, seq))
        return
    if MATCH == "tape_walk":
        fills, rem = tape_walk(oid, u, buy, p, s, h)
    elif MATCH == "tape_direct":
        fills, rem = [], s
        for m_oid, fsz in real_fills.get(oid, ()):
            mo = B.by_oid.get(m_oid)
            tick("tape_maker_in_book", mo is not None, h)
            if mo is not None:
                fills.append((mo, mo.px, fsz)); B.fill_maker(m_oid, fsz)
            rem -= fsz
    elif MATCH == "tape":
        fills, rem = tape_match(oid, u, buy, p, s, h)
    else:
        fills, rem = B.match(buy, p, s, taker_user=u)
    for m, fpx, fsz in fills:
        sim_tr[(oid, m.oid)] += fsz
    if status == "filled" and filled_sz is not None:
        tick("filled_size", abs((s - rem) - q(filled_sz)) <= 1, h)
    if rem > 0 and tif == "Gtc":
        if MATCH in ("tape_direct", "tape_walk") and B.would_cross(buy, p):
            tick("gtc_remainder_cancelled_at_match", True, h)   # real fills stopped short of the book: HL cancelled the rest
        else:
            B.rest(Order(oid, u, buy, p, rem, tif, cloid, seq))


DEBUG = os.environ.get("DEBUG_CROSS")
nev = 0
for h, b, i, j, k, r in ev:
    nev += 1
    if DEBUG and nev % 50 == 0:
        bb, ba = B.best_bid(), B.best_ask()
        if bb is not None and ba is not None and bb >= ba:
            print("FIRST CROSS after event", nev, "h", h, "bid", bb/SCALE, "ask", ba/SCALE)
            for side, px in ((True, bb), (False, ba)):
                for o in list((B.bids if side else B.asks)[px])[:5]:
                    print("  ", "BID" if side else "ASK", o.oid, o.user, o.px/SCALE, o.sz/SCALE, o.tif, "seq", o.seq)
            raise SystemExit
    if h != cur_h:
        if cur_h is not None:
            end_block(cur_h)
            for hh in range(cur_h + 1, h):      # blocks with no GOOGL action still get their engine fills / snapshots
                start_block(hh); end_block(hh)
        cur_h = h
        start_block(h)
    if k == 0:                       # cancel by oid
        st = r[8] or ""
        o = B.remove(int(r[6]), "cancel") if r[6] is not None else None
        real_ok = '"success"' in st
        tick("cancel_status", (o is not None) == real_ok or (not real_ok and o is None), h)
    elif k == 1:                     # cancel by cloid
        oid = B.by_cloid.get((r[4], r[7]))
        if oid is not None:
            B.remove(oid, "cancelByCloid")
    elif k == 5:                     # relayer setOracle: record the book component inputs at this exact point
        orc_log.append((h, b, i, r[3], r[4], B.best_bid(), B.best_ask(), last_px[0]))
    elif k == 2:                     # scheduleCancel
        u, tm = r
        if tm is None:
            schedule.pop(u, None)
        else:
            schedule[u] = tm
            heapq.heappush(sheap, (tm, u))
    else:
        seq, h_, b_, i_, j_, u, ty, oid_in, buy, px, sz, tif, trg, cloid, status, oid, filled_sz, err, t = r
        if trg:                      # trigger orders live outside the book until triggered (engine-injected)
            if ty in ("modify", "batchModify") and oid_in is not None and str(oid_in).isdigit():
                B.remove(int(oid_in), "trigger_modify")
            continue
        ok_modify = ty == "modify" and status is not None and '"ok"' in status
        if ty in ("modify", "batchModify"):
            msg = (status or "") if ty == "modify" else (err or "")
            placed_failed = "Error placing new order during modify" in msg   # HL cancels the original first
            if placed_failed and oid_in is not None:
                if str(oid_in).isdigit():
                    B.remove(int(oid_in), "modify_failed")
                else:
                    o2 = B.by_cloid.get((u, oid_in))
                    if o2 is not None:
                        B.remove(o2, "modify_failed")
                continue
            if ty == "modify" and not ok_modify:
                continue
            if ty == "batchModify" and status == "error":
                continue
            if oid_in is not None:
                if str(oid_in).isdigit():
                    B.remove(int(oid_in), "modified")
                else:
                    o2 = B.by_cloid.get((u, oid_in))
                    if o2 is not None:
                        B.remove(o2, "modified")
        if status is None and ty == "order":     # action rejected as a whole (expired, ...) or batch entry after an error
            continue
        if status == "error":
            e = err or ""
            if e.startswith("Post only"):
                tick("alo_reject_sim_crosses", B.would_cross(buy, q(px)), h)
                mm = ECHO.search(e)
                if mm:
                    rb, ra = q(mm.group(1)), q(mm.group(2))
                    tick("echo_bbo_exact", (B.best_bid(), B.best_ask()) == (rb, ra), h)
                    if PRUNE:
                        prune_better(True, rb, h, "echo"); prune_better(False, ra, h, "echo")
            elif e.startswith("Order could not immediately match"):
                tick("ioc_nomatch_sim_agrees", not B.would_cross(buy, q(px)), h)
            continue
        place(r, real_oid(seq, oid))
end_block(cur_h)

# ---------------------------------------------------------------- trade comparison
def trade_score(df, label):
    real = collections.Counter()
    for t_oid, m_oid, sz in df.select("t_oid", "m_oid", "sz").iter_rows():
        real[(t_oid, m_oid)] += q(sz)
    takers = {kk[0] for kk in real}
    keys = set(real) | {k for k in sim_tr if k[0] in takers}
    both = sum(min(real[k], sim_tr.get(k, 0)) for k in real)
    tot_r = sum(real.values())
    tot_s = sum(sim_tr.get(k, 0) for k in keys)
    print(f"  {label}: real size {tot_r/SCALE:.1f}, matched {both/tot_r:.4f} of real, sim extra {(tot_s-both)/max(tot_s,1):.4f} of sim")


print(f"\nORDERING={ORDERING} ENGINE_POS={ENGINE_POS}")
for name in sorted({k[0] for k in chk}):
    y, n = chk[(name, True)], chk[(name, False)]
    print(f"  {name:34s} ok {y:9d}  bad {n:8d}  rate {y/max(y+n,1):.4f}")
print("trades (user takers, size-weighted)")
trade_score(real_tr, "all day")
win_ms = (int(W0.replace(tzinfo=dt.timezone.utc).timestamp()*1000), int(W1.replace(tzinfo=dt.timezone.utc).timestamp()*1000))
trade_score(real_tr.filter(pl.col("ms").is_between(*win_ms)), "18:00-22:00")
print("match-time cancels (tape mode):", dict(match_cancels))
if os.environ.get("ORC_LOG"):
    pl.DataFrame(orc_log, schema={"h": pl.Int64, "b": pl.Int64, "i": pl.Int64, "m1": pl.Float64, "m2": pl.Float64, "bid": pl.Int64, "ask": pl.Int64, "last": pl.Int64}, orient="row").write_parquet(os.environ["ORC_LOG"])
if os.environ.get("BBO_LOG"):
    pl.DataFrame(bbo_log, schema={"h": pl.Int64, "bid": pl.Int64, "ask": pl.Int64}, orient="row").write_parquet(os.environ["BBO_LOG"])
print("pruned (evidence, tif):", pruned.most_common(8))
if os.environ.get("PRUNE_LOG"):
    pl.DataFrame(pruned_log, schema={"h": pl.Int64, "oid": pl.Int64, "seq": pl.Int64, "u": pl.String, "buy": pl.Boolean, "px": pl.Int64, "sz": pl.Int64, "why": pl.String}, orient="row").write_parquet(os.environ["PRUNE_LOG"])
print("missing tape makers by reason:", miss_why.most_common(12))
if os.environ.get("PRIO_LOG"):
    pl.DataFrame(prio_log, schema={c: pl.Int64 for c in ["h","t_oid","m_oid","m_seq","lvl","n_older_unhit","older_oid","older_seq","q_len"]}, orient="row").write_parquet(os.environ["PRIO_LOG"])
if os.environ.get("MC_LOG"):
    pl.DataFrame(mc_log, schema=["h","t_oid","m_oid","m_seq","m_u","m_buy","m_px","m_sz","lvl","t_px","want"], orient="row").with_columns(pl.col("want").cast(pl.List(pl.Int64))).write_parquet(os.environ["MC_LOG"])
print("1-min L2 snapshots:", {k: v for k, v in sorted(l2c.items())})
