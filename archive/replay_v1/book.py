"""Order-level limit order book with HL-style price-time matching, for one coin.

Prices and sizes are integers (scaled by SCALE) so levels and remaining sizes are exact.
Time priority = arrival order in the simulation (a modify creates a new order and loses priority).
"""
from collections import deque
from sortedcontainers import SortedDict

SCALE = 10 ** 6


def q(x):
    return int(round(float(x) * SCALE))


class Order:
    __slots__ = ("oid", "user", "buy", "px", "sz", "tif", "cloid", "seq", "live")

    def __init__(self, oid, user, buy, px, sz, tif, cloid, seq):
        self.oid, self.user, self.buy, self.px, self.sz, self.tif, self.cloid, self.seq = oid, user, buy, px, sz, tif, cloid, seq
        self.live = True


class Book:
    def __init__(self):
        self.bids = SortedDict()          # px -> deque[Order]; best = last key
        self.asks = SortedDict()          # best = first key
        self.by_oid = {}
        self.by_cloid = {}                # (user, cloid) -> oid
        self.by_user = {}                 # user -> set(oid)
        self.gone = {}                    # oid -> reason it left the book (diagnostics)

    # --- queries -------------------------------------------------------------------------
    def best_bid(self):
        while self.bids:
            px, dq = self.bids.peekitem(-1)
            if dq:
                return px
            del self.bids[px]
        return None

    def best_ask(self):
        while self.asks:
            px, dq = self.asks.peekitem(0)
            if dq:
                return px
            del self.asks[px]
        return None

    def levels(self, buy, n):
        side = self.bids if buy else self.asks
        keys = reversed(side.keys()) if buy else iter(side.keys())
        out = []
        for px in keys:
            s = sum(o.sz for o in side[px])
            if s > 0:
                out.append((px, s, len(side[px])))
                if len(out) >= n:
                    break
        return out

    # --- mutations -----------------------------------------------------------------------
    def rest(self, o):
        side = self.bids if o.buy else self.asks
        side.setdefault(o.px, deque()).append(o)
        self.by_oid[o.oid] = o
        if o.cloid:
            self.by_cloid[(o.user, o.cloid)] = o.oid
        self.by_user.setdefault(o.user, set()).add(o.oid)

    def remove(self, oid, reason="cancel"):
        o = self.by_oid.pop(oid, None)
        if o is None:
            return None
        self.gone[oid] = reason
        o.live = False
        side = self.bids if o.buy else self.asks
        dq = side.get(o.px)
        if dq is not None:
            try:
                dq.remove(o)
            except ValueError:
                pass
            if not dq:
                del side[o.px]
        if o.cloid and self.by_cloid.get((o.user, o.cloid)) == oid:
            del self.by_cloid[(o.user, o.cloid)]
        us = self.by_user.get(o.user)
        if us:
            us.discard(oid)
        return o

    def would_cross(self, buy, px):
        if buy:
            a = self.best_ask()
            return a is not None and px >= a
        b = self.best_bid()
        return b is not None and px <= b

    def match(self, buy, px, sz, taker_user=None):
        """Take liquidity up to limit px. Returns (fills [(maker Order, px, sz)], remaining sz).
        Self-trade: HL cancels the resting maker order of the same user (expire maker)."""
        fills = []
        side = self.asks if buy else self.bids
        while sz > 0 and side:
            lvl = side.peekitem(0 if buy else -1)[0]
            if (buy and lvl > px) or ((not buy) and lvl < px):
                break
            dq = side[lvl]
            while dq and sz > 0:
                m = dq[0]
                if taker_user is not None and m.user == taker_user:
                    self.remove(m.oid, "selftrade")
                    continue
                f = min(sz, m.sz)
                fills.append((m, lvl, f))
                m.sz -= f
                sz -= f
                if m.sz == 0:
                    self.remove(m.oid, "filled")
            if not dq and lvl in side:
                del side[lvl]
        return fills, sz

    def fill_maker(self, oid, sz):
        """Apply an externally given fill (engine taker) to a resting maker order."""
        o = self.by_oid.get(oid)
        if o is None:
            return False
        o.sz -= sz
        if o.sz <= 0:
            self.remove(oid, "filled_engine")
        return True

    def cancel_user(self, user):
        n = 0
        for oid in list(self.by_user.get(user, ())):
            self.remove(oid, "schedule")
            n += 1
        return n
