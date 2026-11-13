"""Adaptive attack (feed walk, then book push the same way): mark lift vs the pre-walk mark, and takeovers vs the walk alone.
Usage: python score_adapt.py DIR WALK_MS PUSH_MS FTAG   (FTAG e.g. f0.10 or f-0.10). Mark = Hyperliquid's: clip(med(m1, m2, med(bid, ask, last)), prev (1 +- 1%))."""
import sys, csv, re, os
D, W0, P0, FT = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
med = lambda a, b, c: sorted((a, b, c))[1]
def marks(f):
    out, m = [], None
    for r in csv.DictReader(open(f)):
        if not (r["bid"] and r["ask"] and r["last"]):   # one-sided book: ONE_SIDED as in the engine (clearing.rs book_px)
            o = os.environ.get("ONE_SIDED")
            if o == "quote" and (r["bid"] or r["ask"]): x = med(float(r["m1"]), float(r["m2"]), float(r["bid"] or r["ask"]))
            elif o == "last" and r["last"]: x = med(float(r["m1"]), float(r["m2"]), float(r["last"]))
            elif o == "drop": x = (float(r["m1"]) + float(r["m2"])) / 2
            else: out.append((int(r["ms"]), m)); continue
        else: x = med(float(r["m1"]), float(r["m2"]), med(float(r["bid"]), float(r["ask"]), float(r["last"])))
        m = x if m is None else min(max(x, m * 0.99), m * 1.01)
        out.append((int(r["ms"]), m))
    return out
def tk(f):
    return sum(abs(float(r["q"])) * float(r["px"]) for r in csv.DictReader(open(f)))
log = open(D + ".log").read()
print(f"{'run':38} {'walk':>6} {'peak':>6} {'+30s':>6} {'end':>6}  {'takeovers':>10} {'extra':>9}  attacker")
for mk in os.environ.get("MARKS", "today pkgmint pkgm3k1800 pkgm3r1800").split():
    b = tk(f"{D}/tk_GOOGL_{mk}_base.csv")
    for tag in ["base"] + [f"c{c}_{FT}_d{d}" for c in ("1e6", "5e6") for d in (15, 60)]:
        f = f"{D}/orc_GOOGL_{mk}_{tag}.csv"
        if not os.path.exists(f): continue
        ms = marks(f); m0 = [m for t, m in ms if t < W0][-1]
        bp = lambda m: (m / m0 - 1) * 1e4
        d = int(tag.split("_d")[1]) * 1000 if tag != "base" else 60000
        at = lambda T: [m for t, m in ms if t <= T][-1]
        win = [bp(m) for t, m in ms if P0 <= t <= P0 + d]
        peak = max(win, key=abs)
        t = tk(f"{D}/tk_GOOGL_{mk}_{tag}.csv")
        a = re.search(rf"GOOGL_{mk}_{re.escape(tag)}: PROP ACCOUNT: capital \$(\d+) \| end position (\S+) equity at last mark \$(-?\d+) \| liquidated (\S+) shares, taken over (\S+)", log)
        att = f"cap {int(a[1])/1e6:.0f}M end eq {int(a[3])/1e6:.2f}M pos {float(a[2]):.0f} liq {a[4]} tk {a[5]}" if a else ""
        print(f"{mk+' '+tag:38} {bp(at(P0)):6.0f} {peak:6.0f} {bp(at(P0 + d + 30000)):6.0f} {bp(at(W0 + 150000 + 120000)):6.0f}  {t/1e6:9.3f}M {(t-b)/1e3:8.0f}k  {att}")
