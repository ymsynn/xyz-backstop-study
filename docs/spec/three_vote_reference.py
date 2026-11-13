"""Reference implementation of the proposed mark-price inputs (see proposal_spec.md), checked against the replay.

Reads july27_skhx_test_vector.csv (SK Hynix, July 27, 2026) and recomputes the feed's vote V, the average A and
Hyperliquid's mark at every update, from the update time, the external price and xyz's book only. Two runs:
  1. from the first update the replay simulates in full (06:00 UTC), with the state set from the replay's row just before
     (the only read of the replay's V, A and mark, apart from the comparison);
  2. from the first row of the file with no state from the replay at all (before 06:00 UTC the replay ran the average
     but not the live-feed rule, so the run does the same).

    python three_vote_reference.py [test_vector.csv] [closure_windows.txt]

Prices are handled as integers of 1e-6 USD ("micro") where the replay does, so that rounding is the same.
"""
import csv, math, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VECTOR = sys.argv[1] if len(sys.argv) > 1 else f"{HERE}/july27_skhx_test_vector.csv"
WINDOWS = sys.argv[2] if len(sys.argv) > 2 else f"{HERE}/july27_skhx_closures.txt"

# ---- constants -------------------------------------------------------------------------------------------------------
TAU = 1800.0          # s, time constant of the average A and of the internal price
KAPPA = 0.01          # the internal price sees the book mid at most 1% away from itself
STALE_N = 2           # the feed is not live once the external price has repeated on this many updates in a row
MAX_LEV = 10          # SK Hynix (data/xyzmeta.json); the bound around the external price is D = 1 / MAX_LEV
D = 1.0 / MAX_LEV
SZ_DECIMALS = 3       # SK Hynix; prices have at most 6 - SZ_DECIMALS decimals and 5 significant figures
MAX_DEC = 6 - SZ_DECIMALS
HL_STEP = 0.01        # Hyperliquid: the mark moves at most 1% per update
START_MS = 1785132000000   # July 27, 2026 06:00:00 UTC: the replay applies the live-feed rule from here


def tick(x):
    """Price grid at x (USD): 5 significant figures, at most MAX_DEC decimals."""
    return 10.0 ** -min(4 - math.floor(math.log10(abs(x))), MAX_DEC)


def to_grid(x, mode):
    """x (USD) on the grid, in micro: mode 0 nearest (half up), +1 up, -1 down."""
    q = x / tick(x)
    r = math.floor(q + 0.5) if mode == 0 else math.ceil(q - 1e-9) if mode > 0 else math.floor(q + 1e-9)
    return round(r * tick(x) * 1e6)


def median3(a, b, c):
    return sorted((a, b, c))[1]


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def book_price(bid, ask, last):
    """Hyperliquid's book price: median(bid, ask, last); the lone quote when one side is empty; None with no quote."""
    if bid is not None and ask is not None and last is not None: return median3(bid, ask, last)
    if (bid is None) != (ask is None): return bid if ask is None else ask
    return None


def hl_mark(v, a, book, prev_mark, rounded=True):
    """Hyperliquid's part (unchanged): median of the two inputs and the book, within 1% of the previous mark. All micro.
    rounded: the two bounds are rounded to 6 - szDecimals decimals, as the replay does (False: as the test vector's
    mark column was rebuilt). No book price: no mark (None), and the next update is not bounded."""
    if book is None: return None
    m = median3(v, a, book)
    if prev_mark is None: return m
    lo, hi = prev_mark * (1 - HL_STEP), prev_mark * (1 + HL_STEP)
    if rounded:
        st = 10 ** SZ_DECIMALS
        lo, hi = math.floor(lo / st + 0.5) * st, math.floor(hi / st + 0.5) * st
    return clip(m, lo, hi)


class Relayer:
    """The relayer's side: V and A at each update. State kept between updates is in __init__."""

    def __init__(self, windows, rule_from=0):
        self.windows = windows      # scheduled closures [(from_ms, to_ms)]
        self.rule_from = rule_from  # the live-feed rule applies from this time (0: always)
        self.t = None               # time of the previous update (ms)
        self.e_prev = None          # external price at the previous update (micro)
        self.repeats = 0            # consecutive updates on which the external price repeated
        self.o_pub = None           # the feed's price as published at the previous update, on the grid (micro)
        self.o = None               # internal price, unrounded (USD); None while the feed is live
        self.a = None               # the average, unrounded (micro)
        self.mid = None             # last two-sided book mid (USD)
        self.prev = None            # previous update as published: dict(v, a, book, mark), micro

    def update(self, ms, ext, bid, ask):
        dt = (ms - self.t) / 1000.0 if self.t is not None else 0.0
        e = ext / 1e6
        if bid is not None and ask is not None: self.mid = (bid + ask) / 2e6
        # 1. is the feed live?
        live = True
        if ms >= self.rule_from:
            self.repeats = self.repeats + 1 if ext == self.e_prev else 0
            self.e_prev = ext
            closed = any(a <= ms < b for a, b in self.windows)
            live = not closed and self.repeats < STALE_N
        # 2. the feed's vote V
        if live:
            self.o, v = None, ext                                       # the external price as received
            self.o_pub = to_grid(e, 0)
        else:
            o0 = self.o if self.o is not None else self.o_pub / 1e6     # restart from the last published value
            w = 1.0 - math.exp(-min(dt, TAU / 10) / TAU)
            mid = self.mid if self.mid is not None else o0
            o = o0 + w * clip(mid - o0, -KAPPA * o0, KAPPA * o0)
            v = clip(to_grid(o, 0), to_grid(e * (1 - D), +1), to_grid(e * (1 + D), -1))   # published: on the grid
            self.o = clip(o, e * (1 - D), e * (1 + D))                                      # kept: unrounded
            self.o_pub = v
        # 3. the average A: one step toward V, then the ratchet
        a = v if self.a is None else self.a + (1.0 - math.exp(-dt / TAU)) * (v - self.a)
        p = self.prev
        if p is not None and p["mark"] is not None and not min(p["v"], p["a"]) < p["book"] < max(p["v"], p["a"]):
            a = clip(a, min(v, p["mark"]), max(v, p["mark"]))
        self.a, self.t = a, ms
        return v, math.floor(a + 0.5)                                   # A is published to 1e-6, not on the grid


def load(path):
    px = lambda s: None if s == "" else round(float(s) * 1e6)
    rows = []
    for r in csv.DictReader(open(path)):
        t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        rows.append(dict(time=r["time_utc"], ms=round(t.timestamp() * 1000), ext=px(r["external_price"]),
                         bid=px(r["proposal_bid"]), ask=px(r["proposal_ask"]), last=px(r["proposal_last"]),
                         V=px(r["proposal_vote_V"]), A=px(r["proposal_average_A"]), M=px(r["proposal_mark"])))
    return rows


def report(name, rows, got, want, sel=lambda r: True):
    d = [(abs(g - r[want]), r) for r, g in zip(rows, got) if sel(r) and g is not None and r[want] is not None]
    n = len(d)
    worst = max(d, key=lambda x: x[0])
    one = lambda x, r: x <= round(tick(r[want] / 1e6) * 1e6)
    print(f"    {name:33s} updates {n:6d} | exact {sum(x < 0.5 for x, _ in d) / n:8.4%} | within one tick {sum(one(x, r) for x, r in d) / n:8.4%}"
          f" | largest difference {worst[0] / 1e6:.6f} at {worst[1]['time']}")


def run(rows, windows, i0, seeded):
    rel = Relayer(windows, START_MS)
    if seeded:                      # the only read of the replay's V, A and mark: the state before the first update
        p = rows[i0 - 1]
        rel.t, rel.a, rel.o_pub = p["ms"], float(p["A"]), to_grid(p["ext"] / 1e6, 0)
        rel.prev = dict(v=p["V"], a=p["A"], book=book_price(p["bid"], p["ask"], p["last"]), mark=p["M"])
    V, A, M, M2, m2 = [], [], [], [], rel.prev and rel.prev["mark"]
    for r in rows[i0:]:
        v, a = rel.update(r["ms"], r["ext"], r["bid"], r["ask"])
        book = book_price(r["bid"], r["ask"], r["last"])
        m = hl_mark(v, a, book, rel.prev and rel.prev["mark"])
        m2 = hl_mark(v, a, book, m2, rounded=False) if book is not None else m2   # the test vector's column holds it
        rel.prev = dict(v=v, a=a, book=book, mark=m)
        V.append(v); A.append(a); M.append(m); M2.append(m2)
    sim = rows[i0:]
    event = lambda r: "22:55:00" <= r["time"][11:19] < "23:10:00"
    for title, sel in (("  all updates", lambda r: True), ("  22:55-23:10 UTC (the event)", event)):
        print(title)
        report("V", sim, V, "V", sel); report("A", sim, A, "A", sel)
        report("mark, 1% bounds rounded (replay)", sim, M, "M", sel)
        report("mark, 1% bounds not rounded", sim, M2, "M", sel)


def main():
    rows = load(VECTOR)
    windows = [tuple(int(x) for x in w.split(";")) for w in open(WINDOWS).read().strip().split(",") if w]
    i0 = next(i for i, r in enumerate(rows) if r["ms"] >= START_MS)
    print(f"Run 1: from the first fully simulated update, row {i0 + 1} of {len(rows)} ({rows[i0]['time']} UTC), state from row {i0}")
    run(rows, windows, i0, True)
    print(f"Run 2: from row 1 ({rows[0]['time']} UTC), no state from the replay")
    run(rows, windows, 0, False)


if __name__ == "__main__":
    main()
