"""OWN_CLOSED for one coin over a UTC date range: the venue's scheduled closures (data/venue_hours.json) as "a;b,a;b" ms.
A quiet external feed inside them is expected (the venue is shut), so package_v's frozen-feed trigger must not fire there.
Usage: python sim/prep/closed_windows.py [--internal] COIN YYYY-MM-DD [DAYS=3]  |  [--internal] --prep data/prep_COIN_MMDD   (prints nothing for a coin without a venue entry)"""
import datetime as dt, json, os, sys
from zoneinfo import ZoneInfo
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository root
H = json.load(open(f"{ROOT}/data/venue_hours.json"))
INTERNAL = "--internal" in sys.argv   # only the closures priced on trade.xyz's internal oracle (venue "internal")
WEEKEND = "--weekend-only" in sys.argv   # only weekend closures (package_b: daily breaks keep the last external price)
sys.argv = [x for x in sys.argv if x not in ("--internal", "--weekend-only")]
if sys.argv[1] == "--prep":  # data/prep_COIN_MMDD[_suffix] (2026)
    _, coin, md = os.path.basename(sys.argv[2].rstrip("/")).split("_")[:3]
    sys.argv = [sys.argv[0], coin, f"2026-{md[:2]}-{md[2:]}", "2"]
coin, d0 = sys.argv[1], dt.date.fromisoformat(sys.argv[2]); n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
v = H["venues"].get(H["coins"].get(coin, ""))
if not v: sys.exit(0)
tz = ZoneInfo(v["tz"]); t = lambda s: dt.time.fromisoformat(s)
ms = lambda d, s: int(dt.datetime.combine(d, t(s), tz).timestamp() * 1000)
out = []
for k in range(-1, n + 1):
    d = d0 + dt.timedelta(days=k); wd = d.weekday()  # Mon 0 .. Sun 6
    kinds = v.get("internal", []) if INTERNAL else ["daily", "weekend"]
    if WEEKEND: kinds = [k for k in kinds if k == "weekend"]
    if wd == 4 and "weekend" in kinds:  # Friday close -> Sunday open
        out.append((ms(d, v["weekend"][0]), ms(d + dt.timedelta(days=3 if v.get("weekend_reopen") == "Mon" else 2), v["weekend"][1])))
    elif wd < 4 and "daily" in kinds:  # Mon-Thu daily break (an open time earlier than the close falls on the next day)
        a, b = v["daily"]; e = d + dt.timedelta(days=1) if t(b) <= t(a) else d
        out.append((ms(d, a), ms(e, b)))
print(",".join(f"{a};{b}" for a, b in out))
