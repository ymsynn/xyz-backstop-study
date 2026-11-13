# A wrong external price that lasts: 20% low for 2, 5 and 15 minutes

`COINS=GOOGL TAGS="q120s q300s q900s" FRAC=-0.20 MARKS=... zsh sim/runs/spike_runs.sh`, output `data/scen/final/longprint`,
2026-11-12. Alphabet, October 28, the external price fed 20% low from 18:30 ET, xyz's book as recorded. Compared with the
same replay without the wrong price.

| | Today | Proposal |
|---|---|---|
| 2 minutes: largest move of the mark | -16.14% | -1.35% |
| 2 minutes: extra taken over by the vault | $7.40M (190 positions) | $0 |
| 2 minutes: extra liquidated through the order book | $13.47M (790 accounts) | $0 |
| 5 minutes: largest move of the mark | -16.15% | -2.92% |
| 5 minutes: extra taken over by the vault | $7.41M (193) | $0 |
| 5 minutes: extra liquidated through the order book | $13.56M (797 accounts) | $2.94M (150 accounts) |
| 15 minutes: largest move of the mark | -16.15% | -7.92% |
| 15 minutes: extra taken over by the vault | $7.49M (201) | $0 (1 position) |
| 15 minutes: extra liquidated through the order book | $14.11M (801 accounts) | $10.82M (559 accounts) |

Under the proposal a wrong price that lasts does move the mark, at the pace of the 30-minute average: the average is
built from the feed's vote, so the feed has one vote and slowly gains a second. A 20% error moves the mark 1.35% in two
minutes and 7.92% in fifteen. Under today's rules the same error moves it 16% within the first two minutes.

The vault takes nothing extra under the proposal, but healthy accounts are liquidated through the order book once the
error has lasted: none after two minutes, 150 accounts ($2.94M) after five, 559 accounts ($10.82M) after fifteen,
against about 800 accounts ($13.5M to $14.1M) under today's rules whatever the duration. Book liquidations are the
accounts whose first liquidation falls in the print or the ten minutes after it and that are not liquidated in the
same replay without the wrong price, valued at the true external price. The
30-second test of the scorecard (5% low: 0.10% against 4.17%) is the short end of the same curve.
