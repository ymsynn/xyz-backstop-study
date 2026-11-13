# How often the not-live rule is on, by session

The proposal treats the feed as not live when the external price has repeated a value twice (E_t = E_{t-1} = E_{t-2}).
Counted on the external price of six replayed market-days of the final run (Alphabet October 20 and 28, Intel October
21 and 29, Amazon October 21 and 29), about 7,800 updates per regular session and 9,500 per overnight session.
Regular hours 13:30 to 20:00 UTC; overnight 00:05 to 08:00 UTC. Computed 2026-11-12.

| | Regular hours | Overnight |
|---|---|---|
| Updates where the external price is unchanged | 6% to 27% | 39% to 87% |
| Updates where the rule is on | 0.6% to 8.9% | 20% to 79% |
| Times it switches on, per hour | 7 to 70 | 36 to 90 |
| Average length of a spell | 3 to 5 seconds | 7 to 36 seconds |

In regular hours the rule switches on often but for one or two updates at a time. In a spell that short the internal
price can move by at most about 0.002% per update (1% cap times the 3-second share of a 30-minute time constant), so
the vote barely differs from the external price. Overnight the rule is the normal state. The effect of the switching
on the mark in regular hours was not isolated in a replay; the recorded sessions were replayed with the rule as a
whole (scorecard, normal sessions).
