# A random sample of market-days

Days we did not choose. Drawn by `sim/final/random_sample.py` (seed 20261111) from every market that has a one-minute book on a
given day between July 1 and November 8, 2026, excluding the nine days used elsewhere in the study: six days at random, five
markets at random on each, three reserve days drawn in the same pass. 122 days and 12,362 market-days were eligible.

Three of the drawn days (July 19, July 10 and the first reserve, July 14) could not be built: the command stream before about
July 20 has a layout our extractor does not read. The next two reserve days, August 4 and 5, replaced them, in draw order.

Each market-day was rebuilt from the raw archives and replayed under today's rules and under the proposal, with the relayer
simulated for the whole day (`RELAYER_WARMUP_S=86400`). Scored by `sim/final/score_random.py`.

## Totals over the 30 market-days

| | Today | Proposal |
|---|---|---|
| Positions taken over by the backstop | $0.0k (2 dust positions) | $0.0k (2) |
| Accounts liquidated in the order book | 155 | 154 |
| Market-days where the proposal takes over more / the same / less than today | | 0 / 30 / 0 |

Real takeovers on the chain on these market-days: $0.0k.

Distance between the proposal's mark and today's, in basis points:

- median over the day: 3.4 bp on the median market-day, 13.7 bp on the worst;
- 99th percentile within a day: 17.4 bp on the median market-day, 160.2 bp on the worst.

## Per market-day

| Day | Market | Isolated-only | Accounts liquidated, today / proposal | Mark distance: median / 99th pct / max bp |
|---|---|---|---|---|
| 2026-08-04 | BOT | yes | 3 / 1 | 13.7 / 82.5 / 312.9 |
| 2026-08-04 | CRCL | no | 7 / 6 | 0.9 / 8.5 / 29.8 |
| 2026-08-04 | GOOGL | no | 13 / 13 | 0.5 / 5.0 / 10.5 |
| 2026-08-04 | KR200 | yes | 21 / 21 | 7.0 / 49.3 / 98.7 |
| 2026-08-04 | SHAZ | yes | 30 / 30 | 11.7 / 145.6 / 220.7 |
| 2026-08-05 | COST | yes | 1 / 1 | 1.3 / 9.9 / 21.0 |
| 2026-08-05 | PALLADIUM | yes | 4 / 4 | 1.4 / 11.6 / 34.4 |
| 2026-08-05 | SMSN | yes | 12 / 12 | 9.2 / 160.2 / 238.1 |
| 2026-08-05 | WDC | yes | 46 / 49 | 2.0 / 16.8 / 490.9 |
| 2026-08-05 | XLE | yes | 3 / 2 | 2.6 / 11.9 / 18.8 |
| 2026-08-10 | IBM | yes | 1 / 1 | 1.3 / 8.3 / 22.0 |
| 2026-08-10 | MU | no | 3 / 3 | 0.7 / 8.5 / 18.4 |
| 2026-08-10 | PLATINUM | yes | 1 / 1 | 1.1 / 15.9 / 19.9 |
| 2026-08-10 | PURRDAT | yes | 0 / 0 | 3.9 / 29.7 / 97.8 |
| 2026-08-10 | SKHY | no | 2 / 2 | 0.8 / 8.7 / 24.4 |
| 2026-09-19 | AAPL | no | 0 / 0 | 0.9 / 5.1 / 6.6 |
| 2026-09-19 | KSTR | yes | 0 / 0 | 10.3 / 31.2 / 40.2 |
| 2026-09-19 | RDDT | yes | 0 / 0 | 3.9 / 15.1 / 20.3 |
| 2026-09-19 | SHEIN | yes | 0 / 0 | 12.0 / 87.6 / 140.9 |
| 2026-09-19 | SOFTBANK | yes | 0 / 0 | 10.0 / 99.9 / 199.9 |
| 2026-09-27 | AAOI | yes | 0 / 0 | 3.9 / 31.3 / 44.1 |
| 2026-09-27 | DRAM | no | 3 / 3 | 4.8 / 83.4 / 121.6 |
| 2026-09-27 | HOOD | yes | 0 / 0 | 5.0 / 24.5 / 31.1 |
| 2026-09-27 | PURRDAT | yes | 0 / 0 | 5.5 / 44.1 / 61.1 |
| 2026-09-27 | TLT | yes | 0 / 0 | 4.4 / 31.0 / 54.3 |
| 2026-10-01 | BE | yes | 4 / 4 | 1.7 / 13.5 / 23.0 |
| 2026-10-01 | BMNR | yes | 0 / 0 | 3.0 / 17.9 / 23.9 |
| 2026-10-01 | GBP | yes | 0 / 0 | 0.8 / 4.6 / 7.6 |
| 2026-10-01 | KSTR | yes | 1 / 1 | 9.4 / 51.8 / 85.3 |
| 2026-10-01 | SKHY | no | 0 / 0 | 0.5 / 8.5 / 12.3 |

Reading: on days nobody picked, only two dust positions ($0.0k) reach the backstop under either rule set and about as many accounts are liquidated
(155 against 154). The proposal's mark stays within a few basis points of today's for most of each day; the larger gaps are on
thin markets on days when the external market is closed, where the proposal follows xyz's book at a capped pace by design.
