"""Closed-hours wick: a faithful attacker props xyz's book while the external venue is shut (E frozen by schedule).
Runs: sim/prop_runs.sh with PROP_AT inside the venue closure, S=data/scen/closed_faith, MARKS="today pkgv pkgk".
Per mark and attack: accounts liquidated or taken over only because of the attack (attackers excluded), the mark's
largest distance above E during the attack, and the attacker's capital and end equity (from the run log).
Records registry test `closed_wick` (REG=closed_wick). Usage: python sim/closed_attack_eval.py
"""
import glob, os, re, sys
import polars as pl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.environ.get("S", f"{ROOT}/data/scen/closed_faith")
A0 = int(os.environ["PROP_AT"])
ATT = 2**32 - 1 - 9
DM = {"today": "current", "pkgv": "package_v", "pkgk": "package_k", "pkgb": "package_b", "pkgm": "package_m", "pkgm050": "package_m_cap050", "pkgm100": "package_m_cap100", "pkgm200": "package_m_cap200"}
med3 = lambda x, y, z: pl.max_horizontal(pl.min_horizontal(x, y), pl.min_horizontal(pl.max_horizontal(x, y), z))


def hit(n):
    rd = pl.read_csv(f"{S}/rd_{n}.csv").filter(pl.col("sim_rounds") > 0)["u"].to_list()
    tk = pl.read_csv(f"{S}/tk_{n}.csv")["u"].to_list() if os.path.getsize(f"{S}/tk_{n}.csv") > 0 else []
    return {u for u in rd + tk if u < ATT - 100}   # attacker accounts sit just below 2^32


def lift(n, a, b):
    o = pl.read_csv(f"{S}/orc_{n}.csv").drop_nulls(["bid", "ask", "last"]).filter(pl.col("ms").is_between(a, b), pl.col("ext") > 0)
    m = o.select(((med3(pl.col("m1"), pl.col("m2"), med3(pl.col("bid"), pl.col("ask"), pl.col("last"))) / pl.col("ext") - 1) * 1e4).alias("bp"))
    return round(float(m["bp"].max()), 1) if m.height else None


acct = {}
log = f"{S}.log"
if os.path.exists(log):
    for ln in open(log):
        m = re.match(r"([A-Z]+)_(\w+?)_(c[\d.e+]+_f[\d.]+_d\d+): PROP ACCOUNT: capital \$(\d+) \| end position (-?[\d.]+) equity at last mark \$(-?\d+)", ln)
        if m: acct[(m.group(1), m.group(2), m.group(3))] = (int(m.group(4)), int(m.group(6)))
rows = []
for f in sorted(glob.glob(f"{S}/orc_*_c*_f*_d*.csv")):
    n = os.path.basename(f)[4:-4]
    coin, mk, atk = re.match(r"([A-Z]+)_(\w+?)_(c.+)$", n).groups()
    d = int(re.search(r"_d(\d+)", atk).group(1))
    base = f"{coin}_{mk}_base"
    if not os.path.exists(f"{S}/rd_{base}.csv"): continue
    extra = hit(n) - hit(base)
    cap, eq = acct.get((coin, mk, atk), (None, None))
    rows.append(dict(design=DM.get(mk, mk), coin=coin, attack=f"closed_{atk}", harmed_accounts=len(extra),
                     mark_lift_bp=lift(n, A0, A0 + (d + 60) * 1000), base_lift_bp=lift(base, A0, A0 + (d + 60) * 1000),
                     attacker_capital=cap, attacker_end_equity=eq))
R = pl.DataFrame(rows).sort("coin", "attack", "design")
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_width_chars(200)
print(R)
registry.maybe_record(R.to_dicts(), kind="attack", command="python sim/closed_attack_eval.py")
