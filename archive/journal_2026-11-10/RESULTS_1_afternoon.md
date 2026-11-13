# Design tests of 2026-11-10 (local, engine at f2564d1 + uncommitted MARK3 / EXT_PERSIST)

Designs: today | proposal (package_m_int, "lead") | three-vote mark, anchor = 30 min average (pkgm3e1800 / lead3e1800)
| three-vote, anchor 0.5% per update (pkgm3a50 / lead3a50). Inputs: local preps (old pipeline for 10-20..10-29, SKHX; CL / NET 11-05 new).

| Test (folder)                                         | today   | proposal | 3-vote 30 min | 3-vote 0.5%/upd |
|-------------------------------------------------------|---------|----------|---------------|-----------------|
| Walk -10% over 15 s, extra takeovers $M (rp_dn,r3_dn) | 3.25    | 4.19     | 0             | 1.25            |
| Walk -10% over 30 s                                   | 1.11    | 4.66     | 0             | 1.25            |
| Walk -10% over 60 s                                   | 0.30    | 1.11     | 0             | 0               |
| Walk +10% over 15 s (rp_up,r3_up)                     | 0.05    | 0.18     | 0             | 0.66            |
| Walk +10% over 30 s                                   | 0       | 0.36     | 0             | 0.66            |
| Bad print -5% 30 s, extra takeovers $M (t3/spike q30s)| 0.92    | 0        | 0             | 0               |
| Bad print -5% 30 s (a30s)                             | 0.20    | 0        | 0             | 0.11            |
| 3 crashes, vault capital need $M (crash)              | 0.717   | 0.587    | 0.581         | 0.594           |
| 3 crashes, need to avoid ADL $M                       | 0.463   | 0.352    | 0.346         | 0.352           |
| SKHX 07-27, need to avoid ADL $M (t3/skhx)            | 1.43    | 0        | 0             | 0               |
| SKHX 07-27, capital need $M                           | 2.65    | 1.03     | 1.03          | 1.03            |
| 5 isolated-only replays, ADL $k (t3/iso)              | 305.0   | 99.2     | 91.1          | 99.0            |
| Stuck feed 120 s at 3 crash onsets, inherited $M      | 13.98   | 15.29    | 15.21         | 15.21           |
| Quiet days 10-20 / 10-21, inherited $k (t3/quiet)     | 57.5    | 57.5     | 57.5          | 57.5            |
| Normal sessions, mark vs today's, median / p99 bp     | -       | 0 / 0    | 0.9-2.7 / 7-13| 2.1-6.5 / 7-16  |
| Prop attack $1M, largest mark lift bp (prop3)         | 20      | 20       | 7             | 0               |
| Prop attack $5M, largest mark lift bp                 | 60      | 50       | 617 (~30 s)   | 279 (~12 s)     |

Persistence rule on the feed (EXT_PERSIST, rp_*): 300 s window stops the 15 / 30 s walks but 3-crash capital need 0.855 (worse than today).
Corroborated speed (rc_*): crashes = proposal; walks 2.18 / 0.90 / 1.11 down, 0.33 / 0.26 / 0.27 up.
Isolated-only parity under today's rules (iso_parity): 62 of 63 real ADL events, $305.0k replayed vs $307.7k real.
Not run: closed-session wick attacks, out-of-sample set, overnight walk, oracle side and Hyperliquid's limits on the inputs.
