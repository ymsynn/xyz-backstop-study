# Ratchet variants, 2026-11-10 night, local. Runner: data/scen/tests_1110i/run.sh (copy: run_ratchet_variants.sh)
Scorers: score_push.py (crash push), score_adapt.py (adaptive attack). GOOGL 10-28. Anchor 30 min in all.
- none (pkgm3k1800), full (pkgm3r1800, the candidate): A in [V, M(t-1)]
- book-aware (pkgm3q1800): the same, skipped at an update whose previous mark was decided by xyz's book (strictly between the two inputs)
- 30 s / 150 s (pkgm3x1800 / pkgm3y1800): A in [V, every mark of the last 30 / 150 s]

| Test                                              | today  | none   | full   | book-aware | 30 s   | 150 s  |
|---------------------------------------------------|--------|--------|--------|------------|--------|--------|
| Crash push $5M 60 s: lift bp / s above 100 bp     | 60 / 0 | 515/63 | 292/27 | 395 / 45   | 588/63 | 527/63 |
| Crash push $5M 60 s: inherited / capital need $M  | 44.3 / 0.90 | 40.3 / 0.82 | 16.9 / 0.50 | 39.3 / 0.79 | 41.0 / 0.84 | 40.4 / 0.82 |
| Crash push $5M 300 s: inherited / capital need $M | 44.3 / 0.90 | 59.5 / 1.18 | 16.9 / 0.50 | 38.8 / 0.84 | 60.1 / 1.21 | 59.6 / 1.19 |
| Walk down + $1M push 60 s, night: extra takeovers $M | 0.16 | 0.43 | 3.83 | 0.44 | 3.77 | 0.63 |
| ... mark 30 s after the push, bp                  | -648   | -43    | -425   | -231       | -416   | -55    |
| Walk down + $1M push 15 s, night: extra takeovers $M | 0.43 | 0.43 | 3.34 | 0.44 | 0.66 | 0.63 |
| Walk down + $5M push 60 s, day: extra takeovers $M | 6.18  | 11.45  | 11.35  | 11.44      | 11.43  | 11.43  |
| Walk down + $5M push 15 s, day: extra takeovers $M | 4.28  | 3.23   | 3.85   | 2.74       | 2.82   | 3.02   |
| Walk up + $5M push 60 s, day: extra takeovers $M  | 0.03   | 1.81   | 1.27   | 1.83       | 1.81   | 1.81   |
| Walk up + $1M push 60 s, night: extra takeovers $M | 0.21  | 0.31   | 0.31   | 0.31       | 0.28   | 0.28   |
(today's extra takeovers are on top of a walk that alone costs it 1.1-1.8 $M; the candidate's walk alone costs 0.)

Reading: no variant keeps both results. The crash push starts as the mark begins to fall, so only an anchor that follows the
mark at once blocks it; an anchor that follows at once is also what locks in a book push made on a walked feed. To the formula
the two cases are the same: feed and book agree. The time-window versions lose the crash result (150 s = no ratchet; 30 s has
both defects). The book-aware version removes the overnight lock-in (0.44 vs 3.83 $M) and keeps part of the crash result: the
push no longer grows with its length (capital need 0.79-0.84 vs 0.82-1.18 without ratchet, today 0.90).
Not run on the variants: the rest of the scorecard (3 crashes, SKHX, stuck feed, walks, bad print, out-of-sample, normal sessions).
