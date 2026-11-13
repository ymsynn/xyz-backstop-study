# Worst case for the correction step: a lasting wrong price together with a push of xyz's book

Replayed 2026-11-12 on the final engine: Alphabet, October 28, the external price fed 20% low for 15 minutes from 18:30 ET
(`EXT_SPIKE`), and from 15 seconds in, a margined attacker pushes xyz's book 10% down for 45 seconds
(`sim/final/book_push_runs.sh`, `F=-0.10 DS=45`; output `data/scen/final/worstcase`). Compared with the same replay
with neither (`data/scen/final/longprint`, base runs). Figures are over the 25 minutes from the start of the wrong price.

| | Today | Proposal |
|---|---|---|
| Wrong price alone: mark moved after 2 / 5 / 15 min | 16.14% / 16.15% / 16.11% | 1.34% / 2.92% / 7.92% |
| Wrong price alone: extra through the book; extra to the vault | $14.12M (801 accounts); $7.44M (194) | $10.83M (559 accounts); $0 (1) |
| With the push, attacker capital $1M: xyz's book | dips 10% | does not dip (the attacker runs out of margin) |
| With the push, $1M: mark moved after 2 / 5 / 15 min | 16.14% / 16.15% / 16.11% | 1.34% / 2.92% / 7.92% |
| With the push, attacker capital $5M: xyz's book | dips 10% | dips 10% |
| With the push, $5M: mark moved after 2 / 5 / 15 min | 16.14% / 16.15% / 16.11% | 9.32% / 10.15% / 13.10% |
| With the push, $5M: extra through the book; extra to the vault | $3.09M (625 accounts); $22.17M (715) | $6.04M (587 accounts); $12.15M (784) |

What it shows. Under the proposal a lasting wrong price alone moves the mark slowly. If xyz's book also dips while the
price is wrong, the mark follows the book down, and when the book comes back the correction step pulls the average
down to the mark, which Hyperliquid's 1% limit has not yet let recover: the dip stays in the mark after the push has
ended (9.32% after two minutes, where the wrong price alone gives 1.34%). This is the worst case found for the
proposal's mark. It is still no worse than today's rules in the same replay: the mark moves 13.10% at most against
16.15%, and $18.2M is liquidated in all against $25.3M, of which $12.15M reaches the vault against $22.17M. With
$1M of capital the push does not move the book under the proposal, because the mark does not move in the attacker's
favor; under today's rules it does.

Limits: one market, one time of day, a book that does not react. The reference program reproduces the mechanism on a
synthetic series (book at 90% of the true price for 45 seconds under a price fed at 80%: the average falls from 99.5%
to 90.9% in one update when the book returns).
