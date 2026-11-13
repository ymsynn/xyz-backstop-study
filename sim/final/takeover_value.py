"""What the vault is handed in the final run: for each takeover, the position valued at the external price at that
instant minus the price the vault takes it at, q (E - px). A takeover is "below the external price" when that value is
negative: the position was already worth less than the vault pays for it.

This is the state of the positions when they reach the vault, not the vault's result: what it makes or loses afterwards
depends on how it sells, which a replay cannot test.
Reads DIR/{crash,skhx,liqstudy}/tk_{COIN}_{DAY}_{design}.csv (u, h, q, px) and the matching orc_ file (h, ext).
Usage: python sim/final/takeover_value.py [DIR=data/scen/final]"""
import os, sys
import polars as pl

K = sys.argv[1] if len(sys.argv) > 1 else "data/scen/final"
ATT = 4294967286   # the injected attacker's account, never a liquidated trader
EVENTS = [("GOOGL", "1028", "crash", "Alphabet, October 28"), ("INTC", "1029", "crash", "Intel, October 29"),
          ("AMZN", "1029", "crash", "Amazon, October 29"), ("SKHX", "0727", "skhx", "SK Hynix, July 27")]
RULES = [("today", "today", None), ("today's mark, cut-back", "rim", "liqstudy"),
         ("proposal's mark, 20% slices", "lead3q1800s20", "liqstudy"), ("proposal", "lead3q1800", None)]


def one(folder, name):
    f = f"{K}/{folder}/tk_{name}.csv"
    if not os.path.exists(f) or os.path.getsize(f) == 0: return None
    o = pl.read_csv(f"{K}/{folder}/orc_{name}.csv").select("h", E=pl.col("ext") / 1e6).sort("h")
    t = (pl.read_csv(f, schema_overrides={"q": pl.Float64, "px": pl.Float64}).filter(pl.col("u") != ATT).sort("h").join_asof(o, on="h")
         .with_columns(ntl=pl.col("q").abs() * pl.col("px"), val=pl.col("q") * (pl.col("E") - pl.col("px"))))
    return dict(n=t.height, below=t.filter(pl.col("val") < 0).height, ntl=float(t["ntl"].sum()), val=float(t["val"].sum()))


print("| Event | Rules | Takeovers | Below the external price | Inherited $M | Value when handed to the vault $k |")
print("|---|---|---|---|---|---|")
tot = {}
for c, d, folder, label in EVENTS:
    for rules, tag, alt in RULES:
        r = one(alt or folder, f"{c}_{d}_{tag}")
        if r is None: continue
        print(f"| {label} | {rules} | {r['n']} | {r['below']} | {r['ntl'] / 1e6:.2f} | {r['val'] / 1e3:+.1f} |")
        if folder == "crash":
            a = tot.setdefault(rules, dict(n=0, below=0, ntl=0.0, val=0.0))
            for k in a: a[k] += r[k]
for rules, a in tot.items():
    print(f"| Three earnings crashes | {rules} | {a['n']} | {a['below']} | {a['ntl'] / 1e6:.2f} | {a['val'] / 1e3:+.1f} |")
