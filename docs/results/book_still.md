# Alphabet's crash with xyz's whole book standing still for five minutes

`zsh sim/final/book_still.sh`, 2026-11-12. From the onset of the crash every recorded order, modify and cancel is
dropped for five minutes; the external price falls as recorded. Compared with the same replay on the recorded book
(`data/scen/final/crash`). The engine build with the switch reproduces the final run's Alphabet outputs byte for byte
when the switch is off.

| | Book as recorded: today | proposal | Book frozen: today | proposal |
|---|---|---|---|---|
| Largest gap, mark above the external price, in the five minutes | 4.78% | 1.57% | 4.78% | 8.65% |
| Largest gap, xyz's book above the external price | 1.26% | 1.26% | 9.32% | 9.31% |
| Mark back within 1% of the external price for good, seconds from the onset | 59 | 11 | 314 | 314 |
| Takeovers by the vault | 158 | 258 | 217 | 331 |
| Inherited by the vault, $M | 6.96 | 10.28 | 11.41 | 16.26 |
| Vault capital need, $M | 0.329 | 0.419 | 0.498 | 0.540 |
| Capital needed to avoid ADL, $M | 0.185 | 0.219 | 0.280 | 0.286 |
| Takeovers below the external price | 156 of 158 | 12 of 258 | 197 of 217 | 306 of 331 |
| Value when handed to the vault, $k (see takeover_value.md) | -46.8 | +77.7 | -44.8 | -210.7 |

With the book frozen both marks stay behind until the book moves again, and the proposal's mark stays further behind
(8.65% against 4.78%): two of its three votes are the frozen book and the average. The vault inherits 42% more than
under today's rules; its capital need is 8% higher and the capital needed to avoid ADL 2% higher.

Limits: one market, one crash, and a book that nobody touches at all for five minutes, takers included, which is more
than any recorded episode. The test with the 20 largest makers removed (`makers_pulled.md`) left the mark where it was.
