"""Re-infer the relayer read lag k of an existing prep (events_3) with the external-price cap.

Usage: python relayer_lag.py PREP_DIR MAX_LEVERAGE [CLAMP_BPS]
Rewrites the lag column (e_ask) of PREP_DIR/events_3_*.arrow in place, so an existing prep does not have to be rebuilt.
prep.py loads `read_lags` from this file (env MAX_LEV sets the cap there): oracle_n = cap(clamp(ext_n, S[n-k] * (1 +- c)), ext_n * (1 +- 1/maxLev)),
both edges rounded inward on the perp price grid; k = the smallest lag that reproduces the real oracle exactly.
"""
import sys, glob, json, math
import polars as pl


def read_lags(S, X, szd, c, d, kmax=6):
    """Read lag per update (1 where no lag explains the real oracle) and the number of such updates."""
    maxd = 6 - szd
    def tick(x): return 10.0 ** -min(4 - math.floor(math.log10(abs(x))), maxd)
    def rnd(x, mode):   # to µ-units on the grid: -1 down, +1 up, 0 nearest
        t = tick(x); q = x / t
        r = math.floor(q + 1e-9) if mode < 0 else math.ceil(q - 1e-9) if mode > 0 else round(q)
        return round(r * t * 1e6)
    def clamp(x, R):
        lo, hi = R * (1 - c), R * (1 + c)
        v = rnd(lo, 1) if x < lo else rnd(hi, -1) if x > hi else rnd(x, 0)
        if d > 0: v = min(max(v, rnd(x * (1 - d), 1)), rnd(x * (1 + d), -1))
        return v
    lags, miss = [], 0
    for n in range(len(S)):
        k_found = 1
        if X[n] is not None and n > 0 and abs(S[n] - X[n]) > 1e-9:
            target = round(S[n] * 1e6)
            ks = [k for k in range(1, kmax + 1) if n - k >= 0 and clamp(X[n], S[n - k]) == target]
            if ks: k_found = ks[0]
            else: miss += 1
        lags.append(k_found)
    return lags, miss


if __name__ == "__main__":
    PREP, ML = sys.argv[1], float(sys.argv[2])
    C = (float(sys.argv[3]) if len(sys.argv) > 3 else 50.0) / 1e4
    SZD = json.load(open(f"{PREP}/meta.json"))["sz_decimals"]
    for f in sorted(glob.glob(f"{PREP}/events_3_*.arrow")):
        e = pl.read_ipc(f, memory_map=False)
        S = (e["x"] / 1e6).to_list(); X = (e["e_bid"] / 1e6).to_list()
        old = e["e_ask"].to_list()
        lags, miss = read_lags(S, X, SZD, C, 1.0 / ML)
        changed = sum(a != b for a, b in zip(old, lags))
        e.with_columns(pl.Series("e_ask", lags, dtype=pl.Int64)).write_ipc(f, compression="lz4")
        print(f"{f}: {len(lags)} updates, lag changed on {changed}, unexplained {miss}; k distribution {sorted(pl.Series(lags).value_counts().rows())}")
