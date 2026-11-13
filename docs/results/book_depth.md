# What it costs to clear one side of xyz's book (2026-11-11)

Runner sim/final/depth_runs.sh (the real book rebuilt from the tape on the 22 local market-days, sampled every minute), scorer sim/final/depth_eval.py.
Depth = resting notional within 10% of the mid on one side. Capital = depth / max leverage: what a margined account needs to take all of it.
Market makers' replenishment is ignored, so this is a lower bound on the cost. Low = the 10th percentile of minutes (the lowest day when several).

| Market | Max lev. | Session | Days | Bids within 5%, median $M | Bids within 10%: median / low $M | Asks within 10%: low $M | Capital to clear 10% of bids: median / low $M |
|---|---|---|---|---|---|---|---|
| AMZN | 20x | overnight | 3 | 2.58 | 2.77 / 2.28 | 2.21 | 0.14 / 0.11 |
| AMZN | 20x | pre-market | 3 | 3.59 | 3.70 / 3.13 | 3.31 | 0.18 / 0.16 |
| AMZN | 20x | regular | 3 | 4.88 | 5.16 / 4.53 | 4.63 | 0.26 / 0.23 |
| AMZN | 20x | post-market | 3 | 3.24 | 3.46 / 2.96 | 2.24 | 0.17 / 0.15 |
| BRENTOIL | 20x | venue open | 1 | 9.00 | 10.79 / 8.13 | 9.53 | 0.54 / 0.41 |
| BRENTOIL | 20x | venue closed | 1 | 6.84 | 11.36 / 10.27 | 7.48 | 0.57 / 0.51 |
| CL | 20x | venue open | 1 | 16.03 | 16.96 / 13.38 | 17.32 | 0.85 / 0.67 |
| CL | 20x | venue closed | 1 | 12.91 | 16.32 / 15.59 | 12.74 | 0.82 / 0.78 |
| GOLD | 25x | venue open | 1 | 20.26 | 20.55 / 14.82 | 12.79 | 0.82 / 0.59 |
| GOLD | 25x | venue closed | 1 | 19.85 | 20.70 / 19.27 | 12.45 | 0.83 / 0.77 |
| GOOGL | 20x | overnight | 4 | 6.00 | 6.14 / 3.81 | 3.16 | 0.31 / 0.19 |
| GOOGL | 20x | pre-market | 4 | 7.20 | 7.37 / 5.78 | 4.94 | 0.37 / 0.29 |
| GOOGL | 20x | regular | 4 | 9.04 | 9.18 / 8.23 | 7.55 | 0.46 / 0.41 |
| GOOGL | 20x | post-market | 4 | 6.74 | 7.01 / 6.54 | 6.11 | 0.35 / 0.33 |
| INTC | 10x | overnight | 3 | 4.14 | 4.49 / 3.82 | 3.50 | 0.45 / 0.38 |
| INTC | 10x | pre-market | 3 | 5.34 | 5.93 / 4.96 | 4.44 | 0.59 / 0.50 |
| INTC | 10x | regular | 3 | 7.05 | 7.51 / 6.86 | 6.34 | 0.75 / 0.69 |
| INTC | 10x | post-market | 3 | 5.44 | 6.00 / 4.19 | 4.53 | 0.60 / 0.42 |
| LITE | 10x | overnight | 1 | 2.27 | 2.41 / 2.05 | 2.06 | 0.24 / 0.20 |
| LITE | 10x | pre-market | 1 | 3.13 | 3.27 / 2.26 | 2.35 | 0.33 / 0.23 |
| LITE | 10x | regular | 1 | 4.15 | 4.22 / 3.75 | 3.19 | 0.42 / 0.37 |
| LITE | 10x | post-market | 1 | 2.99 | 3.20 / 2.50 | 2.11 | 0.32 / 0.25 |
| META | 20x | overnight | 1 | 6.13 | 6.79 / 6.23 | 4.66 | 0.34 / 0.31 |
| META | 20x | pre-market | 1 | 7.19 | 7.66 / 7.17 | 7.75 | 0.38 / 0.36 |
| META | 20x | regular | 1 | 15.84 | 20.42 / 18.40 | 13.10 | 1.02 / 0.92 |
| META | 20x | post-market | 1 | 9.01 | 13.94 / 13.37 | 23.20 | 0.70 / 0.67 |
| MRVL | 10x | overnight | 1 | 2.70 | 2.70 / 2.22 | 2.10 | 0.27 / 0.22 |
| MRVL | 10x | pre-market | 1 | 3.18 | 3.19 / 2.78 | 2.81 | 0.32 / 0.28 |
| MRVL | 10x | regular | 1 | 4.31 | 4.32 / 3.79 | 3.84 | 0.43 / 0.38 |
| MRVL | 10x | post-market | 1 | 3.49 | 3.53 / 2.92 | 2.81 | 0.35 / 0.29 |
| NET | 10x | overnight | 1 | 0.87 | 1.24 / 0.67 | 0.59 | 0.12 / 0.07 |
| NET | 10x | pre-market | 1 | 0.90 | 1.21 / 1.10 | 1.01 | 0.12 / 0.11 |
| NET | 10x | regular | 1 | 0.99 | 1.21 / 0.87 | 0.97 | 0.12 / 0.09 |
| NET | 10x | post-market | 1 | 1.02 | 1.21 / 1.01 | 1.15 | 0.12 / 0.10 |
| NOW | 10x | overnight | 1 | 0.63 | 0.63 / 0.56 | 0.74 | 0.06 / 0.06 |
| NOW | 10x | pre-market | 1 | 0.99 | 0.99 / 0.90 | 0.93 | 0.10 / 0.09 |
| NOW | 10x | regular | 1 | 1.02 | 1.03 / 0.95 | 1.01 | 0.10 / 0.09 |
| NOW | 10x | post-market | 1 | 0.95 | 1.18 / 0.46 | 1.19 | 0.12 / 0.05 |
| RDDT | 10x | overnight | 1 | 0.28 | 0.28 / 0.20 | 0.18 | 0.03 / 0.02 |
| RDDT | 10x | pre-market | 1 | 0.39 | 0.39 / 0.32 | 0.31 | 0.04 / 0.03 |
| RDDT | 10x | regular | 1 | 0.57 | 0.58 / 0.37 | 0.38 | 0.06 / 0.04 |
| RDDT | 10x | post-market | 1 | 0.45 | 0.47 / 0.31 | 0.32 | 0.05 / 0.03 |
| SILVER | 25x | venue open | 1 | 16.05 | 16.39 / 14.61 | 15.54 | 0.66 / 0.58 |
| SILVER | 25x | venue closed | 1 | 12.56 | 13.00 / 12.48 | 18.71 | 0.52 / 0.50 |
| SKHX | 10x | venue open | 1 | 9.31 | 12.24 / 10.42 | 9.55 | 1.22 / 1.04 |
| SKHX | 10x | venue closed | 1 | 8.24 | 11.51 / 10.88 | 14.01 | 1.15 / 1.09 |
| SPCX | 20x | overnight | 1 | 9.21 | 9.52 / 8.88 | 7.01 | 0.48 / 0.44 |
| SPCX | 20x | pre-market | 1 | 10.75 | 11.10 / 10.49 | 7.74 | 0.56 / 0.52 |
| SPCX | 20x | regular | 1 | 14.43 | 14.86 / 13.08 | 11.31 | 0.74 / 0.65 |
| SPCX | 20x | post-market | 1 | 9.19 | 9.46 / 9.11 | 7.73 | 0.47 / 0.46 |

Reading:
- The book lever is cheap everywhere: clearing 10% of the bid side takes $0.02M (RDDT overnight) to $1.2M (SK Hynix) of margin; on the US names $0.1-0.5M overnight.
- It agrees with the replays: GOOGL overnight has $6.1M of bids within 10% (low $3.8M) and the $1M attacker at 20x emptied them with $7.2M of sales; SK Hynix has $10-12M, needs $1.0-1.2M at 10x, and the $1M attacker fell just short ($10.2M sold).
- So SK Hynix did not resist because it is safe: the test sat just under the threshold. About $1.2M would have cleared it.
- Depth falls by a third to a half outside regular hours on the US names; on oil, gold and silver the closed session is as deep as the open one.
- What protects against the combined attack is therefore the feed, not the depth of xyz's book: the second lever costs well under $1.5M of margin on every market measured.
Limits: one day for most markets (GOOGL 4, AMZN and INTC 3); a static book (no replenishment, no arbitrage); the attacker's trading loss is not in the capital figure.
