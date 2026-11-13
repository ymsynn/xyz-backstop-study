# Change 2 on its own, under today's mark

`zsh sim/final/change2_alone.sh`, 2026-11-12. Today's mark formula and liquidation sizing, with only the proposal's rule
for a feed that is not live (internal price steps capped at 1%, also when the external price repeats a value twice).
Compared with today's rules and with the full proposal from the final run (`data/scen/final`).

| Test | Today | Change 2 alone | Proposal |
|---|---|---|---|
| Crude oil closed, $5M bid 6% above the market for 15 min: largest lift of the mark | 6.56% | 6.48% | 0.81% |
| Same, $1M of attacker capital | 6.56% | 6.25% | 0.23% |
| Gold closed, $5M bid for 15 min | 3.76% | 3.76% | 0.45% |
| Quiet feed, $5M bid held 2.5 h: lift at 5 min / 1 h / 2.5 h | 4.96% / 4.70% / 4.96% | 4.96% / 4.70% / 4.96% | 0.16% / 1.86% / 4.91% |
| Alphabet crash: takeovers, capital need, capital to avoid ADL | 158, $0.329M, $0.185M | 158, $0.329M, $0.185M | 258, $0.419M, $0.219M |
| Intel crash | 258, $0.244M, $0.166M | 258, $0.244M, $0.166M | 29, $0.045M, $0.033M |
| Amazon crash | 403, $0.143M, $0.112M | 403, $0.143M, $0.112M | 296, $0.125M, $0.099M |
| SK Hynix, July 27 | 352, $2.598M, $1.430M | 351, $2.598M, $1.430M | 595, $2.273M, $0.892M |

The cap alone does not protect today's mark. Under today's formula two of the mark's three inputs follow xyz's book
whatever the internal price does: the second published input is the external price plus a 150-second average of the
book's distance from it, and the third is the book itself. The first input is the internal price, but it is kept within
0.5% of the previous mark, so it is dragged along too (in the crude oil push it still rises 5.43%, against 6.10% without
the cap). The cap protects only once the mark's inputs are the feed's vote and its average, which is change 1.

On the recorded crashes the rule changes nothing under today's mark.
