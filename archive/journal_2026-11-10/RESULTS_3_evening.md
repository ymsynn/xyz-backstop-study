# Tests of 2026-11-10 evening (local). Anchor exempt from the discovery bound in every three-vote run here.
Designs: today | previous candidate (pkgmint / lead) | three-vote as specified (pkgm3e1800 / lead3e1800: unchanged feed -> lead's
inputs, anchor restarted) | no unchanged-feed rule (pkgm3n1800, folder n/) | one formula (pkgm3k1800, folder k/: feed not live ->
its vote is the internal oracle, anchor keeps running; MARK3_INT=1).
Overnight runs need RELAYER_WARMUP_S=57600 (relayer simulated from 04:00 UTC) and RAMP_AT_* for sim/ramp_eval.py.
The 7 out-of-sample preps came from S3 without internal windows / residual v2: reval_oos.sh regenerates them (as ec2/oos_job.sh REVAL).

| Test                                                  | today      | previous | 3-vote spec | no rule | one formula |
|-------------------------------------------------------|------------|----------|-------------|---------|-------------|
| Overnight walk -10% 30 s / 300 s, GOOGL extra tk $M   | 7.66 / 5.58| 8.01 / 5.60 | 7.69 / 7.85 | 0 / 0 | 0 / 0      |
| Daytime walk +-10%, 15-300 s, extra takeovers $M      | 0-3.25     | 0.02-4.66| 0           | 0       | 0           |
| Bad print -5% 30 s, extra takeovers $M                | 0.92       | 0        | 0           | 0       | 0           |
| 3 crashes, capital need / need to avoid ADL $M        | 0.717 / 0.463 | 0.587 / 0.352 | 0.581 / 0.346 | 0.581 / 0.346 | 0.581 / 0.346 |
| SKHX 07-27, need to avoid ADL / capital need $M       | 1.43 / 2.65| 0 / 1.03 | 0 / 1.03    | 1.00 / 2.28 | 0.09 / 1.29 |
| 5 isolated-only replays, ADL $k                       | 305.0      | 99.2     | 91.1        | 101.4   | 101.4       |
| Stuck feed 120 s at 3 crash onsets, inherited $M      | 13.99      | 15.30    | 15.21       | 15.77   | 15.79       |
| Quiet days, inherited $k                              | 57.5       | 57.5     | 57.5        | 57.5    | 57.5        |
| Out of sample (7 market-days): takeovers              | 106        | 61       | 62          | -       | 28          |
| Out of sample: inherited $M                           | 1.61       | 1.41     | 1.39        | -       | 0.55        |
| Out of sample: capital need / need to avoid ADL $k    | 26.2 / 5.3 | 15.0 / 8.8 | 15.4 / 9.3 | -      | 20.6 / 14.0 |
| Closed CL (daily close) book push, mark lift bp       | 207-656    | 100      | 100         | -       | 34          |
| Closed CL, worst vault takeovers $M                   | 74.6       | 0.70     | 0.66        | -       | 0.32        |
| Closed GOLD (weekend) book push, mark lift bp         | 196-376    | 29-52    | 29-52       | -       | 5-76        |
| 3 h frozen feed overnight + $5M push 300 s / 3600 s   | no effect  | no effect| no effect   | -       | -           |
(row above NOT VALID: run without RELAYER_WARMUP_S=57600; see RESULTS_11)
| Book push in the GOOGL crash, $5M: vault takes over $M (60 s / 300 s) | 44.3 / 44.3 | 8.6 / 8.6 | 40.3 / 59.5 | - | 40.3 / 59.5 |

Open: book push during a crash (vault inherits the attacker's position); SKHX slightly worse than the previous candidate.
Invalid, kept only because deletion was blocked: ../tests_1110e, oos/ (no internal windows, SPCX at 10x).

## Book push during the GOOGL 10-28 crash, and the anchor ratchet (folder push/, r/; scorer: python data/scen/tests_1110f/score.py k|r)
Marks below include Hyperliquid's 1% per update. Candidate adopted 2026-11-10 = one formula (pkgm3k1800).
Ratchet (pkgm3r1800, MARK3_RATCHET=1): after its averaging step the anchor is brought inside [vote, previous mark].

| Test                                              | today       | previous    | one formula   | + ratchet   |
|---------------------------------------------------|-------------|-------------|---------------|-------------|
| Crash push $5M: largest mark lift bp / secs > 1%  | 60 / 0      | 48 / 0      | 515 / 63      | 292 / 27    |
| Crash push $5M: vault inherits $M (60 s / 300 s)  | 44.3 / 44.3 | 8.6 / 8.6   | 40.3 / 59.5   | 16.9 / 16.9 |
| Crash push $5M: capital need $M (60 s / 300 s)    | 0.90 / 0.90 | 0.36 / 0.36 | 0.82 / 1.18   | 0.50 / 0.50 |
| Crash push $1M: capital need $M                   | 0.81        | 0.86        | 0.86          | 0.86        |
| Daytime and overnight walks +-10%, extra tk $M    | 0-7.66      | 0.02-8.01   | 0             | 0           |
| 3 crashes, capital need / avoid ADL $M            | 0.717/0.463 | 0.587/0.352 | 0.581 / 0.346 | 0.579 / 0.346 |
| SKHX, avoid ADL / capital need $M                 | 1.43 / 2.65 | 0 / 1.03    | 0.09 / 1.29   | 0.09 / 1.28 |
| 5 isolated-only replays, ADL $k                   | 305.0       | 99.2        | 101.4         | 101.1       |
| Stuck feed 120 s, inherited $M                    | 13.99       | 15.30       | 15.79         | 17.62       |
| Bad print -5% 30 s: extra tk $M / mark move bp    | 0.92        | 0           | 0 / -48       | 0 / -9      |
| Out of sample: takeovers / inherited $M           | 106 / 1.61  | 61 / 1.41   | 28 / 0.55     | 28 / 0.54   |
| Closed CL / GOLD book push, mark lift bp          | 207-656 / 196-376 | 100 / 29-52 | 34 / 5-76 | 34 / 5-76 |
| Quiet days, inherited $k                          | 57.5        | 57.5        | 57.5          | 57.5        |
Open with the ratchet: stuck feed inherits 12% more than without it (not explained yet; only inherited notional is measured there).

## Stuck feed explained (folder stuck/: f120 = feed frozen 120 s at the 3 crash onsets, f0 = same runs, no freeze)
| 3 crashes, feed stuck 120 s            | today | previous | one formula | + ratchet |
|----------------------------------------|-------|----------|-------------|-----------|
| Inherited $M (no freeze)               | 13.98 (9.85) | 15.29 (10.92) | 15.78 (10.81) | 17.62 (10.81) |
| Capital need $M (no freeze)            | 0.931 (0.716) | 0.936 (0.587) | 0.917 (0.580) | 0.968 (0.579) |
| Need to avoid ADL $M (no freeze)       | 0.585 (0.463) | 0.561 (0.351) | 0.546 (0.345) | 0.554 (0.346) |
GOOGL: during the freeze the book falls 8% (327 -> 301). Internal oracle (tau 30 min, cap 1%) moves 0.1% in 120 s, so vote and
anchor both sit at the stale price and outvote the book: mark 327.3 (ratchet), 324.8 (no ratchet: its anchor happened to lag
0.8% below the feed before the freeze, a coincidence), today's mark drifts to 316 through its 150 s premium term. When the feed
returns the mark falls 8% at 1% per update (24 s). The ratchet's extra inherited notional is that 0.8%, not a new mechanism.
