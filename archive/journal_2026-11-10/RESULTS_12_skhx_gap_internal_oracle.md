# 2026-11-11: the SKHX gap, and the capped internal oracle's rounding (engine fix)
Runner: data/scen/tests_1110f/fl/run.sh (copy: run_internal_float.sh). ONE_SIDED=quote. Candidate = pkgm3q1800 / lead3q1800.

## Cause
SKHX 07-27: the external feed is frozen from about 11:14 to 23:00 UTC (1,237.3, then 1,113.6) while xyz's book falls to
1,120-1,140. The proposal's internal oracle moves toward the book by (1 - e^(-dt/tau)) x the gap, gap capped at kappa = 1%:
about 0.17 bp per update. The engine stepped from the published, rounded oracle (as it replays today's uncapped rule), so the
result depended on the tick: SKHX (tick 0.1 at 1,237, step 0.02) rounds back every time, the oracle never moves, and both of
the candidate's votes sit at the stale level; GOOGL (tick 0.01 at 300, step 0.005) rounds to a full tick, twice too fast.
Fix (engine/src/relayer.rs, int_state): the capped internal oracle keeps its own unrounded value and publishes it rounded
(default when INTERNAL_CAP > 0; INTERNAL_FLOAT=0 restores the old behaviour). The proposal must say so: a relayer that steps
from its published price would stall the same way.

## SKHX 07-27 (feed frozen 12 h, then a 22% bad print)
| Design                         | capital need $M | need to avoid ADL $M | inherited $M | mark more than 5% from xyz's book (share of updates) |
|--------------------------------|-----------------|----------------------|--------------|------------------------------------------------------|
| today                          | 2.598           | 1.429                | 17.73        | 0.1%                                                 |
| previous candidate, old engine | 1.032           | 0                    | 17.96        | 13.5%                                                |
| previous candidate, fixed      | 1.044           | 0                    | 17.52        | 1.6%                                                 |
| candidate, old engine          | 1.285           | 0.089                | 20.64        | 37.5%                                                |
| candidate, fixed               | 1.044           | 0                    | 17.53        | 1.6%                                                 |
The gap is closed: the candidate now equals the previous candidate. The remaining 1.6% is the time the oracle needs to
catch a 10% move of the book at about 2% per hour, and the discovery bound around the frozen feed.

## Other tests that lean on the internal oracle, fixed engine
| Test                                              | previous candidate | candidate          | candidate, old engine |
|---------------------------------------------------|--------------------|--------------------|-----------------------|
| Quiet feed + $5M bid: lift at 5 min / 1 h / 2.5 h | 46 / 172 / 496 bp  | 16 / 186 / 491 bp  | 31 / 367 / 500 bp     |
| ... 1.5 h after a 1 h push ends                   | 0                  | 11 bp              | 86 bp                 |
| Closed CL book push, lift (60 s to 900 s)         | 100-121 bp         | 10-81 bp           | 34 bp                 |
| Closed GOLD book push, lift                       | 29-39 bp           | 3-45 bp            | 5-76 bp               |
| Overnight walk -10%, 30 / 300 s: extra takeovers  |                    | 0 / 0              | 0 / 0                 |
| Overnight walk + $1M push 15 / 60 s: liquidated   |                    | 13.3 / 15.3 $M     | 13.3 / 15.3 $M        |
| 3 crashes: capital need / avoid ADL $M            |                    | 0.589 / 0.351      | 0.589 / 0.351         |
Quiet feed: about 2% per hour (the arithmetic), not the 3.7% of RESULTS_11 section 2, which is superseded.
Not rerun with the fix: the rest of the scorecard (normal sessions, out of sample, stuck feed, isolated-only, bad print, daytime
walks, crash push). Overnight the feed is unchanged on 3 updates out of 4, so those belong in the final rerun.

## The full scorecard with both engine fixes (unrounded internal oracle, ONE_SIDED=quote); data/scen/tests_1110f/fl, run.sh + run2.sh
| Test                                                  | today       | previous    | candidate before | candidate, both fixes |
|-------------------------------------------------------|-------------|-------------|------------------|-----------------------|
| Daytime walks +-10%, 15-300 s: extra takeovers $M     | 0-3.25      | 0.02-4.66   | 0                | 0                     |
| Overnight walk -10%, 30 / 300 s: extra takeovers $M   | 7.66 / 5.58 | 8.01 / 5.60 | 0 / 0            | 0 / 0                 |
| Bad print -5% 30 s: extra takeovers $M / mark move bp | 0.92        | 0           | 0 / -8           | 0 / -8                |
| 3 crashes: capital need / need to avoid ADL $M        | 0.717/0.463 | 0.587/0.352 | 0.589 / 0.351    | 0.589 / 0.351         |
| SKHX: need to avoid ADL / capital need $M             | 1.43 / 2.60 | 0 / 1.04 (fixed) | 0.09 / 1.28 | 0 / 1.04              |
| 5 isolated-only replays, ADL $k                       | 305.0       | 99.2        | 100.3            | 100.3                 |
| Stuck feed 120 s: capital need / avoid ADL $M         | 0.931/0.585 | 0.936/0.561 | 0.968 / 0.554    | 0.964 / 0.554         |
| Out of sample: takeovers / inherited $M               | 106 / 1.61  | 61 / 1.41   | 28 / 0.54        | 28 / 0.54             |
| Out of sample: capital need / avoid ADL $k            | 26.2 / 5.3  | 15.0 / 8.8  | 20.7 / 14.1      | 20.7 / 14.1           |
| Closed CL / GOLD book push, mark lift bp              | 207-656 / 196-376 | 100-121 / 29-39 (fixed) | 34 / 5-76 | 10-81 / 3-45  |
| Quiet days, inherited $k                              | 57.5        | 57.5        | 57.5             | 57.5                  |
| Crash push $5M: capital need $M (60 s / 300 s)        | 0.90 / 0.90 | 0.36 / 0.36 | 0.79 / 0.84      | 0.79 / 0.84           |
| Quiet feed + $5M bid: lift at 5 min / 1 h / 2.5 h, bp | 496 / 470 / 496 | 46 / 172 / 496 (fixed) | 31 / 367 / 500 | 16 / 186 / 491 |
| Overnight walk + $1M push 15 / 60 s: liquidated $M    | 14.7 / 15.2 | 15.0 / 15.0 | 13.3 / 15.3      | 13.3 / 15.3           |
Normal sessions (GOOGL / INTC / AMZN): unchanged to the second decimal (mark vs today's median 1.0 / 0.9 / 0.8 bp; accounts
liquidated 179 / 55 / 21 vs today's 183 / 56 / 22), AMZN's largest gap 47.5 bp (was 55.4).
What moved with the fixes: SKHX, the closed-session pushes, the quiet-feed push, stuck feed by $4k. Nothing else.
today and previous columns: earlier runs (old engine) except where marked fixed; today's rule has no cap and is not affected.
