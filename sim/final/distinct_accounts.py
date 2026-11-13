"""Distinct traders, by wallet address, where the paper counts accounts over several markets.

Every rebuilt market-day numbers its accounts from 0 (sim/prep/prep.py writes users.arrow: uid, user), so an account number
means nothing across markets: the same number is a different trader in each market, and one trader has a different
number in each. This script maps the numbers to wallet addresses (data/users/users_{COIN}_{MMDD}.arrow, collected from
the market-day archives by ec2/users_launch.sh) and prints, today's rules then the proposal:

  - November 5, 33 markets: accounts liquidated counted market by market, and distinct wallets among them
    (data/scen/joint_nohold/rd_{COIN}_1105_{design}.csv, sim_rounds > 0);
  - the seven held-out market-days: takeovers by the vault (events), accounts counted market by market, and distinct
    wallets, for the two oil markets of September 10 and for the five other market-days
    (data/scen/final/oos/tk_{COIN}_{MMDD}_{mark}.csv).

Usage: python sim/final/distinct_accounts.py        (prints a table; writes nothing)"""
import os, sys
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SC = f"{ROOT}/data/scen"


def wallets(coin, day):
    p = f"{ROOT}/data/users/users_{coin}_{day}.arrow"
    if not os.path.exists(p):
        sys.exit(f"{p} is missing: fetch the address tables (ec2/users_launch.sh, see REPRODUCE.md)")
    t = pl.read_ipc(p, columns=["uid", "user"])
    return dict(zip(t["uid"].to_list(), t["user"].to_list()))


def addresses(coin, day, uids):
    m = wallets(coin, day)
    miss = [u for u in uids if u not in m]
    if miss:
        sys.exit(f"{len(miss)} account numbers of {coin} {day} have no address")
    return [m[u] for u in uids]


def row(label, vals):
    print(f"| {label:<58} | {vals[0]:>14} | {vals[1]:>14} |")


def main():
    print(f"| {'Count':<58} | {'today':>14} | {'proposal':>14} |")
    print(f"| {'-' * 58} | {'-' * 14} | {'-' * 14} |")

    # ---- November 5, 33 markets: accounts liquidated
    J = f"{SC}/joint_nohold"
    coins = pl.read_csv(f"{J}/joint_1105_coins.csv")["coin"].unique(maintain_order=True).to_list()
    per_market, distinct = [], []
    for des in ("today", "lead3q1800"):
        n, seen = 0, set()
        for c in coins:
            u = pl.read_csv(f"{J}/rd_{c}_1105_{des}.csv").filter(pl.col("sim_rounds").cast(pl.Float64) > 0)["u"].to_list()
            n += len(u); seen.update(addresses(c, "1105", u))
        per_market.append(f"{n:,}"); distinct.append(f"{len(seen):,}")
    row(f"November 5, {len(coins)} markets: accounts liquidated, market by market", per_market)
    row("November 5: distinct wallets among them", distinct)

    # ---- the seven held-out market-days: takeovers by the vault
    OIL = (("BRENTOIL", "0910"), ("CL", "0910"))
    REST = (("GOOGL", "1022"), ("META", "1022"), ("SILVER", "1022"), ("GOLD", "1030"), ("SPCX", "1030"))
    for name, group in (("Two oil markets, September 10", OIL), ("Five other held-out market-days", REST)):
        ev, acc, wal = [], [], []
        for mk in ("today", "pkgm3q1800"):
            e, a, seen = 0, 0, set()
            for c, d in group:
                t = pl.read_csv(f"{SC}/final/oos/tk_{c}_{d}_{mk}.csv")
                u = t["u"].to_list()
                e += len(u); a += len(set(u)); seen.update(addresses(c, d, sorted(set(u))))
            ev.append(f"{e:,}"); acc.append(f"{a:,}"); wal.append(f"{len(seen):,}")
        row(f"{name}: takeovers (events)", ev)
        row(f"{name}: accounts, market by market", acc)
        row(f"{name}: distinct wallets", wal)


if __name__ == "__main__":
    main()
