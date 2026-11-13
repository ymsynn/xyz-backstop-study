# A real crash with the largest market makers removed

The three-vote mark assumes that xyz's order book follows a real move of the external price. This test tries to break
that: at the onset of the Alphabet crash of 28 October, the resting orders of the largest market makers are cancelled
and their new orders dropped for five minutes. Runner: `sim/final/pull_check.sh`.

The 5 largest makers account for 31% of maker volume around the crash, the 20 largest for 68%.

| Makers removed | Rules | Vault capital need | Needed to avoid ADL | Inherited | Mark above the external price, largest | Seconds with the mark more than 2% above it |
|---|---|---|---|---|---|---|
| none | today | $0.329M | $0.185M | $6.96M | 4.78% | 39 |
| none | proposal | $0.419M | $0.219M | $10.28M | 1.57% | 0 |
| 5 largest | today | $0.334M | $0.188M | $7.05M | 4.78% | 39 |
| 5 largest | proposal | $0.422M | $0.222M | $10.37M | 1.57% | 0 |
| 20 largest | today | $0.373M | $0.211M | $7.87M | 4.78% | 39 |
| 20 largest | proposal | $0.478M | $0.250M | $11.91M | 1.57% | 0 |

Mark against the external price over the ten minutes from the onset.

Reading: with two thirds of maker volume gone, the remaining book still follows the fall, and the proposal's mark stays
within 1.57% of the external price, as without the removal. The book never becomes one-sided. Both rule sets cost the
vault somewhat more with the makers gone, in the same proportion. The test removes named makers; it cannot make the
whole book stand still, so it does not show what happens if nobody on xyz follows the move.
