# Checks on the candidate (pkgm3r1800), 2026-11-10 night, local. Runner: data/scen/tests_1110g/run.sh

## 1. Adaptive attack: feed walked +10% over 30 s and held 120 s, then an attacker bids 10% above xyz's mid (GOOGL 10-28)
Mark lift vs the pre-walk mark (Hyperliquid's 1% per update applied). "after" = 30 s after the push ended, walk still held.
| Case                         | today        | previous     | candidate, no ratchet | candidate      |
|------------------------------|--------------|--------------|-----------------------|----------------|
| Walk alone, day / night      | 810 / 794 bp | 942 / 941 bp | 36 / 83 bp            | 88 / 77 bp     |
| Day, $1M push 15 or 60 s     | 865-996      | 995-997      | 36 (no effect)        | 88 (no effect) |
| Day, $5M push 60 s: peak / after | 996 / 736 | 997 / 918   | 1014 / 36             | 1011 / 983     |
| Day, $5M push 60 s: extra takeovers vs the walk alone | $25k | $451k | $1.81M      | $1.27M         |
| Night, $1M push 15 s: peak / after | 869 / 744 | 993 / 941 | 637 / 83              | 649 / 649      |
| Night, $1M push 60 s: peak / after | 994 / 759 | 994 / 941 | 994 / 83              | 998 / 997      |
| Night, $1M push 60 s: extra takeovers | $206k | $69k      | $312k                 | $311k          |
| Attacker's loss (of $1M night / $5M day, 60 s) | 0.71M / 0.32M | 0.69M / 0.30M | 0.80M / 0.46M | 0.80M / 0.46M |
Feed + book together move the mark in every design. The ratchet keeps the mark at the pushed level after the push ends (until
the feed is released) where the version without it returns; extra takeovers are the same or lower with the ratchet.
Downward case: RESULTS_5_adaptive_down.md. The "attacker's loss" row above is equity at the day's last mark and includes the
real crash later that day; execution cost against the pre-push mid is 0.59M (day, $5M) / 0.13M (night, $1M) for the candidate.

## 2. Normal sessions (out-of-hours, crash windows excluded), candidate vs today's mark
| Coin  | hours | mark vs today's p50 / p99 / max bp | distance to E, p50: today -> candidate | per-update step p99: today -> candidate | accounts liquidated: today -> candidate |
|-------|-------|------------------------------------|----------------------------------------|------------------------------------------|------------------------------------------|
| GOOGL | 17.1  | 3.8 / 15.4 / 57.6                  | 7.1 -> 2.7                             | 6.5 -> 4.0                               | 183 -> 177 (1 only under the candidate)  |
| INTC  | 16.9  | 1.3 / 15.0 / 40.6                  | 2.4 -> 0.5                             | 15.9 -> 14.4                             | 56 -> 55 (0)                             |
| AMZN  | 16.9  | 1.2 / 6.3 / 55.4                   | 2.4 -> 1.2                             | 10.4 -> 9.1                              | 22 -> 20 (0)                             |

## 3. Anchor length 15 / 30 / 60 min
Identical at the three lengths: 3 crashes (capital need 0.579, avoid ADL 0.346 $M), SKHX (1.285 / 0.09), crash book push $5M
(lift 290-293 bp for 27 s, capital need 0.50), bad print ($0 extra takeovers), walks by day and overnight ($0 extra takeovers).
Only the drift of the mark during a -10% walk changes: 15 min -1.3 to -2.5%, 30 min -0.7 to -1.4%, 60 min -0.3 to -0.7%.
