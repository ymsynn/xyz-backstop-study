# Full scorecard of the book-aware ratchet (pkgm3q1800 / lead3q1800), 2026-11-10 night, local
Runner: data/scen/tests_1110f/q/run.sh (copy: run_book_aware.sh). Scorers: score.py q, score_push.py, score_adapt.py, sim/ramp_eval.py, sim/normal_eval.py.
Rule: A_t = clip(A~_t, [V_t, M_(t-1)]), except at an update where xyz's book price was strictly between the two published
inputs at t-1 (the book decided the previous mark): then A_t = A~_t.

| Test                                                  | today       | previous    | no ratchet    | full ratchet  | book-aware    |
|-------------------------------------------------------|-------------|-------------|---------------|---------------|---------------|
| Daytime walks +-10%, 15-300 s: extra takeovers $M     | 0-3.25      | 0.02-4.66   | 0             | 0             | 0             |
| Overnight walk -10%, 30 / 300 s: extra takeovers $M   | 7.66 / 5.58 | 8.01 / 5.60 | 0 / 0         | 0 / 0         | 0 / 0         |
| Bad print -5% 30 s: extra takeovers $M / mark move bp | 0.92        | 0           | 0 / -48       | 0 / -9        | 0 / -8        |
| 3 crashes: capital need / need to avoid ADL $M        | 0.717/0.463 | 0.587/0.352 | 0.581 / 0.346 | 0.579 / 0.346 | 0.589 / 0.351 |
| SKHX: need to avoid ADL / capital need $M             | 1.43 / 2.65 | 0 / 1.03    | 0.09 / 1.29   | 0.09 / 1.28   | 0.09 / 1.28   |
| 5 isolated-only replays, ADL $k                       | 305.0       | 99.2        | 101.4         | 101.1         | 100.3         |
| Stuck feed 120 s: capital need / avoid ADL $M         | 0.931/0.585 | 0.936/0.561 | 0.917 / 0.546 | 0.967 / 0.554 | 0.968 / 0.554 |
| Out of sample: takeovers / inherited $M               | 106 / 1.61  | 61 / 1.41   | 28 / 0.55     | 28 / 0.54     | 28 / 0.54     |
| Out of sample: capital need / avoid ADL $k            | 26.2 / 5.3  | 15.0 / 8.8  | 20.6 / 14.0   | 20.4 / 14.1   | 20.7 / 14.1   |
| Closed CL / GOLD book push, mark lift bp              | 207-656 / 196-376 | 100 / 29-52 | 34 / 5-76 | 34 / 5-76     | 34 / 5-76     |
| Quiet days, inherited $k                              | 57.5        | 57.5        | 57.5          | 57.5          | 57.5          |
| Crash push $5M: capital need $M (60 s / 300 s)        | 0.90 / 0.90 | 0.36 / 0.36 | 0.82 / 1.18   | 0.50 / 0.50   | 0.79 / 0.84   |
| Crash push $5M: inherited $M (60 s / 300 s)           | 44.3 / 44.3 | 8.6 / 8.6   | 40.3 / 59.5   | 16.9 / 16.9   | 39.3 / 38.8   |
| Overnight walk down + $1M push 60 s: extra takeovers $M | 0.16      | 0           | 0.43          | 3.83          | 0.44          |
| Day walk down + $5M push 60 s: extra takeovers $M     | 6.18        | 0.75        | 11.45         | 11.35         | 11.44         |
| Day walk up + $5M push 60 s: extra takeovers $M       | 0.03        | 0.45        | 1.81          | 1.27          | 1.83          |
(adaptive rows: extra on top of the walk alone, which costs today and the previous candidate 1.1-8.0 $M and the three-vote versions 0)

Normal sessions (out-of-hours, crash windows excluded), vs today's mark:
| Coin  | mark vs today's p50 / p99 / max bp: full -> book-aware | distance to E p50: today -> full -> book-aware | accounts liquidated: today -> full -> book-aware |
|-------|--------------------------------------------------------|------------------------------------------------|--------------------------------------------------|
| GOOGL | 3.8 / 15.4 / 57.6 -> 1.0 / 14.0 / 38.8                 | 7.1 -> 2.7 -> 5.8                              | 183 -> 177 -> 179 (only under the design: 1 -> 0) |
| INTC  | 1.3 / 15.0 / 40.6 -> 0.9 / 11.8 / 36.4                 | 2.4 -> 0.5 -> 1.3                              | 56 -> 55 -> 55 (0 -> 0)                          |
| AMZN  | 1.2 / 6.3 / 55.4 -> 0.8 / 6.7 / 55.4                   | 2.4 -> 1.2 -> 2.0                              | 22 -> 20 -> 21 (0 -> 1)                          |

Reading: the book-aware version equals the full ratchet everywhere except the two tests that separated them: it gives up most
of the crash-push gain (capital need 0.79-0.84 vs 0.50, still under today's 0.90 and not growing with the push) and removes
the overnight lock-in (0.44 vs 3.83). 3 crashes: +$10k of capital need. Normal sessions: nearer to today's mark, a little
further from E than the full ratchet.
Open in every three-vote version: walk + $5M book push by day (11.4 $M extra takeovers, today 6.2).
