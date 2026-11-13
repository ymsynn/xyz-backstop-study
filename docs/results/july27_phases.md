# SK Hynix, July 27, 2026, phase by phase

`python sim/final/july27_phases.py`, on the final run (proposal without the earlier hold rule), 2026-11-12. The
update-by-update series of the day is `docs/spec/july27_skhx_test_vector.csv`.

| Phase (UTC) | Rules | Through the book $M | Accounts | Takeovers | Taken over $M | Value at the external price $k |
|---|---|---|---|---|---|---|
| 00:00-11:00, venue open | today | 0.04 | 6 | 0 | 0.00 | +0.0 |
| 11:00-17:17, closure, book falling | today | 1.42 | 156 | 0 | 0.00 | +0.0 |
| 17:17-23:00 | today | 0.00 | 0 | 0 | 0.00 | +0.0 |
| 23:00-23:10, false price | today | 28.04 | 901 | 351 | 15.90 | -1786.6 |
| after 23:10 | today | 0.00 | 0 | 1 | 0.01 | -0.1 |
| 00:00-11:00, venue open | proposal | 0.03 | 5 | 0 | 0.00 | +0.0 |
| 11:00-17:17, closure, book falling | proposal | 1.10 | 101 | 4 | 0.01 | -0.5 |
| 17:17-23:00 | proposal | 0.07 | 23 | 1 | 0.00 | -0.0 |
| 23:00-23:10, false price | proposal | 17.38 | 765 | 586 | 18.97 | -2446.3 |
| after 23:10 | proposal | 0.10 | 1 | 4 | 0.07 | +1.2 |

| Between 11:00 and 23:00 UTC | today | proposal |
|---|---|---|
| Updates with the mark more than 2% from xyz's book | 0.0% | 20.9% |
| Updates with the mark more than 5% from xyz's book | 0.0% | 3.2% |
| Largest distance of the mark above xyz's book | 0.93% | 7.03% |
| Highest mark from 23:02 to 23:06 (external price 1,198.50, book near 1,110) | 1,197.10 | 1,124.69 |
| Lowest mark from 23:00 to 23:10 (external price 868.18 at 23:00:03.9, then 868.17) | 917.28 | 954.80 |
