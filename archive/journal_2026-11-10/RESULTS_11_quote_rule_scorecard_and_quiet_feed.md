# 2026-11-11: (1) the candidate's scorecard under Hyperliquid's one-sided-book rule, (2) a book push held for hours on a quiet feed
Runner: data/scen/tests_1110f/qq/run.sh (copy: run_quote_scorecard.sh), ONE_SIDED=quote throughout. Candidate = pkgm3q1800 / lead3q1800.

## 1. Scorecard under ONE_SIDED=quote: identical to RESULTS_7 on every line
3 crashes 0.589 / 0.351 $M (capital need / avoid ADL), inherited 10.98; SKHX 0.089 / 1.285; isolated-only ADL 100.3 $k; quiet days
57.5 $k; stuck feed 120 s 0.968 / 0.554 (inherited 17.64); out of sample 28 takeovers, 0.543 $M, 20.7 / 14.1 $k; bad print 0 extra
takeovers (-8 to -29 bp); walks by day and overnight 0 extra takeovers; closed CL 34 bp, GOLD 5-76 bp; normal sessions unchanged.
Why: in these runs the book is one-sided on a single update (AMZN 10-29, GOOGL 10-20, META 10-22) and never on SKHX. The rule
only matters where an attacker empties a side (RESULTS_10).

## 2. (SUPERSEDED by RESULTS_12: the internal oracle moved twice too fast on GOOGL, a rounding error in the engine) Quiet feed: E unchanged for 3 h from 04:30 UTC (GOOGL 10-28), $5M bids 6% above xyz's mid from 04:40
Mark lift vs the same design without the push, bp. Discovery bound at 20x: 500 bp.
| Push held | today             | previous candidate | candidate          |
|-----------|-------------------|--------------------|--------------------|
| 5 min     | 496               | 46                 | 31                 |
| 1 h       | 470               | 337                | 367                |
| 2.5 h     | 496               | 496                | 500                |
| after a 1 h push, 1.5 h later | 0     | 0                  | 86                 |
| extra takeovers, 2.5 h push   | $51k  | $57k               | $58k               |
Attacker: buys 40,224 shares in 1 h ($13.3M) and 92,955 in 2.5 h ($30.6M), about 1.4-1.7% above the mid before the push
($0.23M / $0.42M if closed at that mid); never liquidated.
Reading: under today's rules a $5M bid moves the mark to the 5% bound within 5 minutes. The candidate moves at the internal
oracle's pace, about 3.7% in the first hour (faster than the 2% per hour I had estimated), and reaches the same bound in under
2.5 h; it also comes back more slowly after the push (86 bp left 1.5 h later). The bound holds. Extra takeovers are small in
all three because few shorts sit within 5%. Upward only; the downward push (longs) is not run.
Replaces the 3 h frozen-feed row of RESULTS_3 ("no effect"), which was run without RELAYER_WARMUP_S=57600 and is not valid.
