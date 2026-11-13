# Final scorecard, local part (sim/final/run_final.sh + run_final_skhx.sh, scored by sim/final/score_final.py), 2026-11-11

203e38f9414f7f06cfad92ab27f30574624c896f | 909b426c2340aa51813212bab3e3bc36 | Wed Nov 11 08:35:04 UTC 2026
| Test                                                       | today                  | previous               | champion               |
| ---------------------------------------------------------- | ---------------------- | ---------------------- | ---------------------- |
| 3 crashes: capital need / avoid ADL / inherited $M         | 0.716 / 0.462 / 9.85   | 0.587 / 0.351 / 10.92  | 0.589 / 0.351 / 10.98  |
| SKHX: capital need / avoid ADL / inherited $M              | 2.598 / 1.429 / 17.73  | 1.044 / 0.000 / 17.52  | 1.044 / 0.000 / 17.53  |
| SKHX: updates with the mark > 2% / > 5% from xyz's book    | 0.4% / 0.1%            | 10.5% / 1.6%           | 10.5% / 1.6%           |
| 5 isolated-only replays: ADL $k                            | 305.0                  | 99.2                   | 100.4                  |
| 6 quiet days: inherited $k                                 | 57.5                   | 57.5                   | 57.5                   |
| Stuck feed 120 s: capital need / avoid ADL / inherited $M  | 0.931 / 0.585 / 13.99  | 0.936 / 0.561 / 15.30  | 0.964 / 0.554 / 17.45  |
|   same runs, feed not stuck: capital need / avoid ADL / inherited $M | 0.716 / 0.462 / 9.85   | 0.587 / 0.351 / 10.92  | 0.589 / 0.351 / 10.98  |
| Out of sample (7): takeovers / inherited $M                | 106 / 1.61             | 81 / 1.42              | 28 / 0.54              |
| Out of sample (7): capital need / avoid ADL $k             | 26.3 / 5.3             | 15.2 / 8.8             | 20.6 / 14.1            |
| Bad print -5% (a30s): extra takeovers $M / mark move bp    | 0.20 / -413            | 0.00 / -29             | 0.00 / -29             |
| Bad print -5% (a3s): extra takeovers $M / mark move bp     | 0.00 / -48             | 0.00 / -10             | 0.00 / -10             |
| Bad print -5% (q30s): extra takeovers $M / mark move bp    | 0.92 / -417            | 0.00 / -1              | 0.00 / -8              |
| Closed CL book push: mark lift bp / worst takeovers $M     | 207-656 / 5.62         | 100-121 / 0.71         | 10-81 / 0.32           |
| Closed GOLD book push: mark lift bp / worst takeovers $M   | 196-376 / 0.35         | 29-39 / 0.24           | 3-45 / 0.24            |
| Quiet feed, $5M book push +6%: move at 5 min / 1 h / 2.5 h bp | 496 / 470 / 496        | 46 / 172 / 496         | 16 / 186 / 491         |
| Quiet feed, $5M book push -6%: move at 5 min / 1 h / 2.5 h bp | -145 / -97 / -149      | -54 / -224 / -136      | -17 / -210 / -143      |
| Crash push $1e6 60 s: need $M (no push), attacker lost, its pos. taken over $M | 0.813 (0.329) 100% 9.0 | 0.857 (0.421) 100% 9.2 | 0.860 (0.419) 100% 9.3 |
| Crash push $1e6 300 s: need $M (no push), attacker lost, its pos. taken over $M | 0.813 (0.329) 100% 9.0 | 0.857 (0.421) 100% 9.2 | 0.860 (0.419) 100% 9.3 |
| Crash push $5e6 60 s: need $M (no push), attacker lost, its pos. taken over $M | 0.898 (0.329) 100% 39.3 | 0.362 (0.421) 96% 0.0  | 0.789 (0.419) 100% 29.4 |
| Crash push $5e6 300 s: need $M (no push), attacker lost, its pos. taken over $M | 0.898 (0.329) 100% 39.3 | 0.362 (0.421) 96% 0.0  | 0.839 (0.419) 100% 28.9 |

Adaptive attack: positions liquidated in the 300 s from the start of the walk, book + vault, $M (walk alone / + push 15 s / + push 60 s)
| GOOGL night, walk -10% then $1e6 push                      | 14.83 / 14.73 / 15.15  | 14.98 / 14.97 / 14.97  | 0.00 / 13.29 / 15.29   |
| GOOGL night, walk +10% then $1e6 push                      | 0.17 / 0.31 / 0.43     | 0.42 / 0.43 / 0.43     | 0.00 / 0.16 / 0.41     |
| GOOGL day, walk -10% then $5e6 push                        | 7.84 / 10.22 / 11.33   | 11.48 / 11.95 / 11.95  | 0.00 / 2.93 / 11.85    |
| GOOGL day, walk +10% then $5e6 push                        | 0.28 / 0.37 / 0.38     | 0.64 / 1.09 / 1.09     | 0.00 / 0.18 / 2.01     |
| AMZN night, walk -10% then $1e6 push                       | 0.64 / 0.63 / 0.69     | 0.61 / 0.64 / 0.64     | 0.00 / 0.30 / 0.60     |
| AMZN night, walk +10% then $1e6 push                       | 0.18 / 0.21 / 0.21     | 0.19 / 0.19 / 0.19     | 0.00 / 0.04 / 0.22     |
| AMZN day, walk -10% then $5e6 push                         | 0.18 / 0.21 / 0.25     | 0.21 / 0.21 / 0.22     | 0.00 / 0.13 / 0.28     |
| AMZN day, walk +10% then $5e6 push                         | 0.04 / 0.04 / 0.04     | 0.04 / 0.04 / 0.04     | 0.00 / 0.05 / 0.06     |
| INTC night, walk -10% then $1e6 push                       | 0.45 / 0.47 / 0.50     | 0.54 / 0.54 / 0.54     | 0.00 / 0.03 / 0.51     |
| INTC night, walk +10% then $1e6 push                       | 0.64 / 0.67 / 0.66     | 1.62 / 1.62 / 1.62     | 0.00 / 0.30 / 0.71     |
| INTC day, walk -10% then $5e6 push                         | 2.46 / 1.86 / 1.90     | 1.88 / 1.89 / 1.89     | 0.00 / 1.22 / 1.95     |
| INTC day, walk +10% then $5e6 push                         | 0.05 / 0.05 / 0.05     | 0.03 / 0.03 / 0.03     | 0.00 / 0.03 / 0.03     |
| SKHX day2, walk -10% then $1e6 push                        | 9.34 / 8.75 / 13.71    | 8.03 / 10.95 / 10.98   | 0.00 / 0.00 / 0.00     |
| SKHX day2, walk +10% then $1e6 push                        | 1.22 / 1.07 / 1.08     | 1.39 / 1.39 / 1.39     | 0.00 / 0.00 / 0.00     |

SK Hynix (day2): relayer simulated from the start of the day; the folders adapt/SKHX_day_* of the first run are not valid (relayer not simulated at 03:00).
SK Hynix, champion: with $1M at 10x the attacker sells $10.2M and cannot move xyz's book 10%: the book never goes one-sided and the mark does not move.

## Walks (sim/ramp_eval.py): extra takeovers by design, largest mark move
### r_dn
│ AMZN    pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  -29.8         | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 15 s, held 2 min   | mark move bp  -961.8        | extra takeover $  40353              
│ AMZN    today       |  -10% over 15 s, held 2 min   | mark move bp  -798.6        | extra takeover $  3457               
│ GOOGL   pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  -68.7         | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 15 s, held 2 min   | mark move bp  -970.0        | extra takeover $  4144388            
│ GOOGL   today       |  -10% over 15 s, held 2 min   | mark move bp  -807.6        | extra takeover $  3248805            
│ AMZN    pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  -35.4         | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 30 s, held 2 min   | mark move bp  -962.1        | extra takeover $  1855               
│ AMZN    today       |  -10% over 30 s, held 2 min   | mark move bp  -796.2        | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  -78.6         | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 30 s, held 2 min   | mark move bp  -970.3        | extra takeover $  4654620            
│ GOOGL   today       |  -10% over 30 s, held 2 min   | mark move bp  -799.6        | extra takeover $  1106805            
│ AMZN    pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  -97.1         | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 300 s, held 2 min  | mark move bp  -961.4        | extra takeover $  0                  
│ AMZN    today       |  -10% over 300 s, held 2 min  | mark move bp  -556.4        | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  -134.7        | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 300 s, held 2 min  | mark move bp  -970.8        | extra takeover $  15023              
│ GOOGL   today       |  -10% over 300 s, held 2 min  | mark move bp  -566.2        | extra takeover $  133                
│ AMZN    pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  -47.4         | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 60 s, held 2 min   | mark move bp  -962.2        | extra takeover $  0                  
│ AMZN    today       |  -10% over 60 s, held 2 min   | mark move bp  -811.4        | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  -89.2         | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 60 s, held 2 min   | mark move bp  -970.5        | extra takeover $  1111747            
│ GOOGL   today       |  -10% over 60 s, held 2 min   | mark move bp  -806.1        | extra takeover $  304028             
### r_up
│ AMZN    pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 15 s, held 2 min   | mark move bp  -7.9          | extra takeover $  30570              
│ AMZN    today       |  -10% over 15 s, held 2 min   | mark move bp  -7.9          | extra takeover $  2400               
│ GOOGL   pkgm3q1800  |  -10% over 15 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 15 s, held 2 min   | mark move bp  -17.5         | extra takeover $  153502             
│ GOOGL   today       |  -10% over 15 s, held 2 min   | mark move bp  -17.5         | extra takeover $  45998              
│ AMZN    pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 30 s, held 2 min   | mark move bp  -7.9          | extra takeover $  261                
│ AMZN    today       |  -10% over 30 s, held 2 min   | mark move bp  -7.9          | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 30 s, held 2 min   | mark move bp  -17.5         | extra takeover $  357918             
│ GOOGL   today       |  -10% over 30 s, held 2 min   | mark move bp  -17.5         | extra takeover $  0                  
│ AMZN    pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 300 s, held 2 min  | mark move bp  -5.7          | extra takeover $  0                  
│ AMZN    today       |  -10% over 300 s, held 2 min  | mark move bp  -5.3          | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 300 s, held 2 min  | mark move bp  -14.4         | extra takeover $  0                  
│ GOOGL   today       |  -10% over 300 s, held 2 min  | mark move bp  -12.7         | extra takeover $  0                  
│ AMZN    pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ AMZN    pkgmint     |  -10% over 60 s, held 2 min   | mark move bp  -7.9          | extra takeover $  0                  
│ AMZN    today       |  -10% over 60 s, held 2 min   | mark move bp  -7.9          | extra takeover $  0                  
│ GOOGL   pkgm3q1800  |  -10% over 60 s, held 2 min   | mark move bp  0.0           | extra takeover $  0                  
│ GOOGL   pkgmint     |  -10% over 60 s, held 2 min   | mark move bp  -17.5         | extra takeover $  272151             
│ GOOGL   today       |  -10% over 60 s, held 2 min   | mark move bp  -17.5         | extra takeover $  0                  
### overnight (GOOGL)
 pkgm3q1800  |  -10% over 30 s, held 2 min   | mark move bp  -62.9         | extra takeover $  0                  
 pkgmint     |  -10% over 30 s, held 2 min   | mark move bp  -961.8        | extra takeover $  8005542            
 today       |  -10% over 30 s, held 2 min   | mark move bp  -815.6        | extra takeover $  7659408            
 pkgm3q1800  |  -10% over 300 s, held 2 min  | mark move bp  -120.0        | extra takeover $  0                  
 pkgmint     |  -10% over 300 s, held 2 min  | mark move bp  -961.6        | extra takeover $  5603348            
 today       |  -10% over 300 s, held 2 min  | mark move bp  -557.0        | extra takeover $  5576381            

## Normal sessions (sim/normal_eval.py), vs today's mark
### pkgmint
 GOOGL  | mark vs today p50/p99/max bp  0.0          0.0          18.7        | dist to E p50 today -> design  7.07         7.07        | accounts liquidated today -> design  183         180        | only today / only design  3           0         
 INTC   | mark vs today p50/p99/max bp  0.0          0.0          25.4        | dist to E p50 today -> design  2.37         2.37        | accounts liquidated today -> design  56          56         | only today / only design  0           0         
 AMZN   | mark vs today p50/p99/max bp  0.0          0.0          48.5        | dist to E p50 today -> design  2.42         2.42        | accounts liquidated today -> design  22          21         | only today / only design  1           0         
### pkgm3q1800
 GOOGL  | mark vs today p50/p99/max bp  1.02         14.03        38.8        | dist to E p50 today -> design  7.07         5.84        | accounts liquidated today -> design  183         179        | only today / only design  4           0         
 INTC   | mark vs today p50/p99/max bp  0.87         11.75        36.4        | dist to E p50 today -> design  2.37         1.29        | accounts liquidated today -> design  56          55         | only today / only design  1           0         
 AMZN   | mark vs today p50/p99/max bp  0.8          6.73         47.5        | dist to E p50 today -> design  2.42         1.96        | accounts liquidated today -> design  22          21         | only today / only design  2           1         
