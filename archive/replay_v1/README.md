# replay v1: frozen 2026-11-03

This is the block-level replay of the xyz:GOOGL order book and mark for 2026-10-28, frozen after Phase 1 validation. Do not edit these files. Development continues in `../sim/`.

## Reproduce

Paths are relative to the session scratchpad.

```bash
# 1. extract (EC2, in-region, ~12 min, ~$1)
AWS_PROFILE=<your-profile> bash launch.sh                     # DAY=20261028 SNAP=2026-10-25T09:33:07Z MIN_H=1199710000 ASSETS=110012
# 2. tables
python reduce.py extract1028/parts extract1028/tables
# 3. bind unreturned oids (modify / trigger)
python oidbind.py extract1028/tables xyzdata/all1028.parquet xyz:GOOGL 110012 extract1028/tables/oid_bind_GOOGL.parquet
# 4. replay + checks (tape_walk = baseline; engine = pure price-time)
MATCH=tape_walk python replay_book.py extract1028/tables xyzdata/all1028.parquet xyzdata/ob1m_GOOGL_1028.parquet orders_first_bundle end
# 5. mark (records the book at each relayer update)
ORC_LOG=extract1028/orc_with_nonorders.parquet MATCH=tape_walk python replay_book.py ...   # then the mark check (inline in Phase-1 notes)
```

Inputs:
- hydromancer `by_dex/xyz/fills/perp/all/date=2026-10-28`
- hydromancer `orderbook/1m/perps/date=2026-10-28/GOOGL.parquet`
- hydromancer `fills/perp/liquidations/date=2026-10-28`

## Validated results

Full detail is in `../SIMULATOR_SPEC.md`, "Phase 1 results".

| Check | All day | 18:00–22:00 |
|---|---|---|
| Echoed bid/offer exact | 99.0% | 98.5% |
| 1-min book: best price | 99.5% | |
| 1-min book: top-5 prices | 98.7% | |
| 1-min book: top-5 prices and sizes exact | 94.5% | |
| Cancel outcomes | 99.7% | |
| User-taker size reproduced to the exact maker | 97.4% | 97.2% |
| Liquidation marks reproduced | 98 / 101 | |

The pure engine reproduces 86% of user-taker size to the exact maker (18:00–22:00).
Data snapshot: s3://<bucket>/backstop/replay_v1/ (tables_20261028/ incl. oid_bind_GOOGL.parquet, orc_with_nonorders.parquet)
