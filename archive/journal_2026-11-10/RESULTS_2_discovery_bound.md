# Three-vote mark (30 min anchor) with trade.xyz's discovery bound on the published anchor: X2 = D(A) = clip(A, E(1 +- 1/maxLev))
Run 2026-11-10 evening, local. Engine: f2564d1 + uncommitted MARK3 (bound on by default, MARK3_D=0 = the afternoon tests in ../tests_1110).

| Test                                        | today | proposal | 3-vote, no bound | 3-vote, bound |
|---------------------------------------------|-------|----------|------------------|---------------|
| Walk -10% over 15 s, extra takeovers $M     | 3.25  | 4.19     | 0                | 2.01          |
| Walk -10% over 30 s                         | 1.11  | 4.66     | 0                | 2.69          |
| Walk -10% over 60 s                         | 0.30  | 1.11     | 0                | 1.54          |
| Walk -10% over 300 s                        | 0     | 0.02     | 0                | 1.41          |
| Walk +10% over 15 / 30 / 60 / 300 s         | 0.05 / 0 / . / . | 0.18 / 0.36 / . / . | 0 | 0.10 / 0.07 / 0.07 / 0.08 |
| Bad print -5% 30 s, extra takeovers $M      | 0.92  | 0        | 0                | 0 (mark -42 bp, was -7) |
| 3 crashes, capital need $M                  | 0.717 | 0.587    | 0.581            | 0.580         |
| 3 crashes, need to avoid ADL $M             | 0.463 | 0.352    | 0.346            | 0.346         |
| SKHX 07-27, need to avoid ADL / capital $M  | 1.43 / 2.65 | 0 / 1.03 | 0 / 1.03   | 0 / 0.99      |
| 5 isolated-only replays, ADL $k             | 305.0 | 99.2     | 91.1             | 91.1          |

Hyperliquid's limits: docs give one numeric rule on the mark (1% per update from the previous mark), already in the engine.
Tape check for an undocumented band around externalPerpPx: SKHX 07-27, 192 of 192 real liquidation marks reproduced exactly by
median + 1% rule, at -17.8% .. +27.4% from the published external price (MARKDBG=1 engine replay data/prep_SKHX_0727).
Book push during the GOOGL 10-28 crash ($5M, +6%): the mark returns to the anchor (pre-crash level), never above it; attacker
ends at $0 in every design; vault takes over $40.3M (60 s) / $59.5M (300 s), today $44.3M, proposal $8.6M (no-bound runs, ../tests_1110/prop3).
