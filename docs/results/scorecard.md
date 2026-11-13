# Final scorecard on the rebuilt market-days (sim/final/run_final.sh, scored by sim/final/score_final.py), 2026-11-13

203e38f9414f7f06cfad92ab27f30574624c896f | 90c8c036560f594eaf4f97c325e896c9 | Wed Nov 11 13:21:59 UTC 2026 | working tree not committed at run time; diff of engine/ sim/ ec2/ against HEAD, md5: 3333cd657fefe35115ce8889694c5fbc
| Test                                                       | today                  | proposal               |
| ---------------------------------------------------------- | ---------------------- | ---------------------- |
| 3 crashes: capital need / avoid ADL / inherited $M         | 0.715 / 0.462 / 10.75  | 0.589 / 0.352 / 11.90  |
|   GOOGL 1028: capital need / avoid ADL / inherited $M      | 0.329 / 0.185 / 6.96   | 0.419 / 0.219 / 10.28  |
|   INTC 1029: capital need / avoid ADL / inherited $M       | 0.244 / 0.166 / 2.24   | 0.045 / 0.033 / 0.30   |
|   AMZN 1029: capital need / avoid ADL / inherited $M       | 0.143 / 0.112 / 1.55   | 0.125 / 0.099 / 1.32   |
| SKHX: capital need / avoid ADL / inherited $M              | 2.598 / 1.430 / 15.90  | 2.273 / 0.892 / 19.05  |
| SKHX: updates with the mark > 2% / > 5% from xyz's book    | 0.4% / 0.1%            | 10.5% / 1.6%           |
| 5 isolated-only replays: ADL $k                            | 300.4                  | 99.5                   |
| 6 quiet days: inherited $k                                 | 0.2                    | 0.2                    |
| Stuck feed 120 s: capital need / avoid ADL / inherited $M  | 0.939 / 0.590 / 15.11  | 0.974 / 0.559 / 18.48  |
|   same runs, feed not stuck: capital need / avoid ADL / inherited $M | 0.715 / 0.462 / 10.75  | 0.589 / 0.352 / 11.90  |
| Out of sample (7): takeovers / inherited $M                | 103 / 1.25             | 24 / 0.18              |
| Out of sample (7): capital need / avoid ADL $k             | 24.5 / 0.0             | 0.9 / 0.1              |
|   GOOGL 1022: takeovers / inherited $k                     | 0 / 0                  | 0 / 0                  |
|   META 1022: takeovers / inherited $k                      | 2 / 4                  | 3 / 13                 |
|   SILVER 1022: takeovers / inherited $k                    | 0 / 0                  | 0 / 0                  |
|   GOLD 1030: takeovers / inherited $k                      | 0 / 0                  | 2 / 86                 |
|   SPCX 1030: takeovers / inherited $k                      | 6 / 1                  | 6 / 1                  |
|   BRENTOIL 0910: takeovers / inherited $k                  | 46 / 754               | 3 / 2                  |
|   CL 0910: takeovers / inherited $k                        | 49 / 496               | 10 / 82                |
| Bad print -5% (a30s): extra takeovers $M / mark move bp    | 0.20 / -413            | 0.00 / -29             |
| Bad print -5% (a3s): extra takeovers $M / mark move bp     | 0.00 / -48             | 0.00 / -10             |
| Bad print -5% (q30s): extra takeovers $M / mark move bp    | 0.92 / -417            | 0.00 / -10             |
| Closed CL book push: mark lift bp / worst takeovers $M     | 211-656 / 5.97         | 10-81 / 0.42           |
| Closed GOLD book push: mark lift bp / worst takeovers $M   | 196-376 / 0.04         | 3-45 / 0.09            |
| Quiet feed, $5M book push +6%: move at 5 min / 1 h / 2.5 h bp | 496 / 470 / 496        | 16 / 186 / 491         |
| Quiet feed, $5M book push -6%: move at 5 min / 1 h / 2.5 h bp | -147 / -97 / -149      | -17 / -210 / -123      |
| Crash push $1e6 60 s: need $M (no push), attacker lost, its pos. taken over $M | 0.771 (0.329) 100% 8.2 | 0.863 (0.419) 100% 9.4 |
| Crash push $1e6 300 s: need $M (no push), attacker lost, its pos. taken over $M | 0.771 (0.329) 100% 8.2 | 0.863 (0.419) 100% 9.4 |
| Crash push $5e6 60 s: need $M (no push), attacker lost, its pos. taken over $M | 0.899 (0.329) 100% 39.2 | 0.802 (0.419) 100% 29.5 |
| Crash push $5e6 300 s: need $M (no push), attacker lost, its pos. taken over $M | 0.899 (0.329) 100% 39.2 | 0.840 (0.419) 100% 28.8 |

Adaptive attack: positions liquidated in the 300 s from the start of the walk, book + vault, $M (walk alone / + push 15 s / + push 60 s)
| GOOGL night, walk -10% then $1e6 push                      | 15.23 / 15.10 / 15.52  | 0.00 / 14.03 / 16.02   |
| GOOGL night, walk +10% then $1e6 push                      | 0.17 / 0.31 / 0.43     | 0.00 / 0.15 / 0.41     |
| GOOGL day, walk -10% then $5e6 push                        | 8.54 / 10.97 / 12.09   | 0.00 / 3.06 / 12.61    |
| GOOGL day, walk +10% then $5e6 push                        | 0.28 / 0.37 / 1.01     | 0.00 / 0.18 / 2.64     |
| AMZN night, walk -10% then $1e6 push                       | 0.64 / 0.63 / 0.69     | 0.00 / 0.30 / 0.60     |
| AMZN night, walk +10% then $1e6 push                       | 0.18 / 0.21 / 0.21     | 0.00 / 0.04 / 0.22     |
| AMZN day, walk -10% then $5e6 push                         | 0.20 / 0.22 / 0.26     | 0.00 / 0.14 / 0.30     |
| AMZN day, walk +10% then $5e6 push                         | 0.08 / 0.08 / 0.09     | 0.00 / 0.06 / 0.10     |
| INTC night, walk -10% then $1e6 push                       | 0.45 / 0.47 / 0.50     | 0.00 / 0.03 / 0.51     |
| INTC night, walk +10% then $1e6 push                       | 0.64 / 0.67 / 0.66     | 0.00 / 0.30 / 0.71     |
| INTC day, walk -10% then $5e6 push                         | 2.51 / 1.90 / 1.94     | 0.00 / 1.22 / 1.99     |
| INTC day, walk +10% then $5e6 push                         | 0.05 / 0.05 / 0.15     | 0.00 / 0.03 / 0.03     |
| SKHX day2, walk -10% then $1e6 push                        | 9.40 / 8.82 / 12.23    | 0.00 / 0.00 / 0.00     |
| SKHX day2, walk +10% then $1e6 push                        | 1.47 / 1.33 / 1.35     | 0.00 / 0.00 / 0.00     |

## Walks (sim/score/ramp_eval.py): extra takeovers by design, largest mark move
### r_dn
│ AMZN    pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  -29.8         | extra takeover $  0                  
│ AMZN    today       |  -10% over 15 s, held 2 min   | mark move bp  -798.6        | extra takeover $  3457               
│ GOOGL   pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  -68.7         | extra takeover $  0                  
│ GOOGL   today       |  -10% over 15 s, held 2 min   | mark move bp  -807.6        | extra takeover $  3248805            
│ AMZN    pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  -35.4         | extra takeover $  0                  
│ AMZN    today       |  -10% over 30 s, held 2 min   | mark move bp  -796.2        | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  -78.6         | extra takeover $  0                  
│ GOOGL   today       |  -10% over 30 s, held 2 min   | mark move bp  -799.6        | extra takeover $  1428138            
│ AMZN    pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  -97.1         | extra takeover $  0                  
│ AMZN    today       |  -10% over 300 s, held 2 min  | mark move bp  -556.4        | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  -134.7        | extra takeover $  0                  
│ GOOGL   today       |  -10% over 300 s, held 2 min  | mark move bp  -566.2        | extra takeover $  133                
│ AMZN    pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  -47.4         | extra takeover $  0                  
│ AMZN    today       |  -10% over 60 s, held 2 min   | mark move bp  -811.4        | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  -89.2         | extra takeover $  0                  
│ GOOGL   today       |  -10% over 60 s, held 2 min   | mark move bp  -806.1        | extra takeover $  304028             
### r_up
│ AMZN    pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    today       |  -10% over 15 s, held 2 min   | mark move bp  -7.9          | extra takeover $  2400               
│ GOOGL   pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   today       |  -10% over 15 s, held 2 min   | mark move bp  -17.5         | extra takeover $  45998              
│ AMZN    pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    today       |  -10% over 30 s, held 2 min   | mark move bp  -7.9          | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   today       |  -10% over 30 s, held 2 min   | mark move bp  -17.5         | extra takeover $  0                  
│ AMZN    pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    today       |  -10% over 300 s, held 2 min  | mark move bp  -5.3          | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   today       |  -10% over 300 s, held 2 min  | mark move bp  -12.7         | extra takeover $  0                  
│ AMZN    pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    today       |  -10% over 60 s, held 2 min   | mark move bp  -7.9          | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   today       |  -10% over 60 s, held 2 min   | mark move bp  -17.5         | extra takeover $  0                  
### overnight (GOOGL)
 pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  -62.9         | extra takeover $  0                  
 today       |  -10% over 30 s, held 2 min   | mark move bp  -815.6        | extra takeover $  7848819            
 pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  -120.0        | extra takeover $  0                  
 today       |  -10% over 300 s, held 2 min  | mark move bp  -557.0        | extra takeover $  5111242            

## Normal sessions (sim/score/normal_eval.py), vs today's mark
### pkgm3q1800
 GOOGL  | mark vs today p50/p99/max bp  1.02         14.03        38.8        | dist to E p50 today -> design  7.07         5.84        | accounts liquidated today -> design  184         180        | only today / only design  4           0         
 INTC   | mark vs today p50/p99/max bp  0.87         11.75        36.4        | dist to E p50 today -> design  2.37         1.29        | accounts liquidated today -> design  56          55         | only today / only design  1           0         
 AMZN   | mark vs today p50/p99/max bp  0.8          6.73         47.5        | dist to E p50 today -> design  2.42         1.96        | accounts liquidated today -> design  21          20         | only today / only design  2           1         

## Liquidation study (data/scen/final/liqstudy, sim/score/liqbook_eval.py with LIQBOOK_DIR): 23 large positions of the three crashes
| Mark x sizing                              | sold on the book $M | left to the vault $M | median sale $k | sale / nearby depth, worst tenth | best-price move, worst tenth bp | fill vs E bp |
|--------------------------------------------|---------------------|----------------------|----------------|----------------------------------|---------------------------------|--------------|
| today's mark, 20% every 30 s (today)       | 9.70                | 8.72                 | 47             | 26%                              | 50.3                            | 61.9         |
| today's mark, cut-back (cut-back alone)    | 9.00                | 9.32                 | 66             | 22%                              | 30.1                            | 81.6         |
| three-vote mark, 20% every 30 s (mark alone) | 8.16              | 11.76                | 53             | 116%                             | 105.0                           | 144.4        |
| three-vote mark, cut-back (the proposal)   | 10.06               | 9.78                 | 77             | 36%                              | 72.7                            | 128.9        |

ADL on the five isolated-only replays, same four combinations: today $300.4k | cut-back alone $301.1k | mark alone $135.3k | the proposal $99.5k.

## 33 markets on 2026-11-05 (EC2, preps rebuilt, data/scen/joint_final, sim/score/joint_eval.py with JOINT_DIR and JOINT_DES)
| Design          | ADL on isolated-only markets $M (events) | with the vault in the six eligible markets | inherited by the vault $M | vault capital need, jointly $M |
|-----------------|------------------------------------------|--------------------------------------------|---------------------------|--------------------------------|
| today           | 0.154 (38)                               | 0.153 (37)                                 | 0.54                      | 0                              |
| proposal        | 0.064 (38)                               | 0.060 (14)                                 | 1.15                      | 0.008                          |
Backstop events on the chain that day: $0.16M, all of them ADL on isolated-only markets (the vault took over nothing). Of the $0.54M simulated under today's rules, $0.51M is one takeover on SP500 that did not
happen on the chain; it is identical under both sets of rules. Second pass (cross accounts see the other markets' simulated
prices): no material change. The earlier 11-05 figures (1,166 takeovers, $17.2M, ADL $2.49M) came from preps built before
the leverage inference and are withdrawn.

## Rebuild
22 market-days rebuilt with the reproducible pipeline on 2026-11-11 (9 on the Mac, 13 on EC2) and 33 for 11-05 on EC2.
On-instance check (1, 2, 8 threads): identical files on NET, BIRD, SP500. Across instances: CL and NET, the two stored preps
built with the final pipeline, are byte-identical to their rebuild except NET's engine-written residual, which the current
engine and the two previous commits all reproduce on the Mac and on EC2.
What the rebuild moved against this morning's run on the old preps (FINAL_LOCAL_old_preps.md): quiet days inherited 57.5k -> 0.2k;
out of sample inherited today 1.61 -> 1.25 $M, proposal 0.54 -> 0.18 $M (28 -> 25 takeovers); three crashes inherited +0.9 $M in
under both sets of rules with capital needs unchanged; SK Hynix inherited 17.7 -> 15.9 $M, needs unchanged; isolated-only ADL 305.0 -> 300.4 $k.
