# The proposal with and without its correction step

The correction step brings the 30-minute average back between the feed's vote and the previous mark, unless xyz's book
alone decided that mark. Replayed 2026-11-12 on the final engine without it (mark tag `pkgm3k1800`, design `lead3k1800`),
on every test of the final run and on three side tests; output `data/scen/final_k`. Scored with
`SCORE_EXTRA="no_correction:pkgm3k1800:lead3k1800" python sim/final/score_final.py data/scen/final_k`.

| Test | Today | Proposal | Without the correction step |
|---|---|---|---|
| Three crashes: capital need / money to avoid ADL / inherited $M | 0.715 / 0.462 / 10.75 | 0.589 / 0.352 / 11.90 | 0.580 / 0.345 / 11.75 |
| SK Hynix, July 27: the same | 2.598 / 1.430 / 15.90 | 2.273 / 0.892 / 19.05 | 2.268 / 0.894 / 18.89 |
| Five isolated-only replays: ADL $k | 300.4 | 99.5 | 100.6 |
| Seven other market-days: takeovers / inherited $M | 104 / 1.26 | 25 / 0.19 | 24 / 0.19 |
| Stuck feed 120 s: capital need / money to avoid ADL / inherited $M | 0.939 / 0.590 / 15.11 | 0.974 / 0.559 / 18.48 | 0.926 / 0.552 / 16.73 |
| Wrong price 5% low for 30 s, 2.5 h after the crash: mark moved | 4.17% | 0.10% | 0.50% |
| Crude oil closed, book push: mark lift, range over the pushes | 2.11% to 6.56% | 0.10% to 0.81% | 0.09% to 0.81% |
| Quiet feed, $5M bid +6%: move at 5 min / 1 h / 2.5 h | 4.96 / 4.70 / 4.96% | 0.16 / 1.86 / 4.91% | 0.08 / 1.86 / 4.91% |
| Walk -10% overnight on Alphabet, then a $1M push: liquidated in 5 min, walk alone / + 15 s / + 60 s, $M | 15.23 / 15.10 / 15.52 | 0.00 / 14.03 / 16.02 | 0.00 / 13.96 / 16.01 |
| Walk -10% by day on Alphabet, then a $5M push: the same | 8.54 / 10.97 / 12.09 | 0.00 / 3.06 / 12.61 | 0.00 / 3.49 / 12.62 |
| Book push during the Alphabet crash, $5M for 60 s: vault capital need $M | 0.899 | 0.802 | 0.825 |
| Book push during the Alphabet crash, $5M for 300 s: vault capital need $M | 0.899 | 0.840 | 1.188 |
| Wrong price 20% low for 15 min: mark moved after 2 / 5 / 15 min | 16.14 / 16.15 / 16.11% | 1.34 / 2.92 / 7.92% | 1.57 / 3.10 / 8.15% |
| The same with a 45 s, $5M push of the book 10% down (the worst case): mark moved | 16.14 / 16.15 / 16.11% | 9.32 / 10.15 / 13.10% | 1.57 / 3.10 / 8.15% |
| Worst case: extra through the book / extra to the vault | $3.09M / $22.17M | $6.04M / $12.15M | $1.20M / $12.22M |
| Alphabet crash with the whole book frozen 5 min: largest gap of the mark / inherited / capital need | 4.78% / $11.41M / $0.498M | 8.65% / $16.26M / $0.540M | 7.84% / $14.78M / $0.506M |

What it shows.
- Without the step the worst case disappears: the dip of the book is no longer kept in the mark (1.57% after two
  minutes, as with the wrong price alone, against 9.32%).
- The walk-plus-push tests are the same with and without it, so the step is not what makes that attack succeed.
- The step earns its place in one test: a $5M push of the book held for five minutes during a real crash. Without it
  the vault needs $1.188M, more than under today's rules ($0.899M); with it, $0.840M, less than today.
- Elsewhere the two differ little: without the step a 30-second wrong price moves the mark 0.50% where the proposal
  gives 0.10% (no takeover either way), the frozen-book and stuck-feed cases are somewhat better, and the crashes are
  the same.

Each version has tests where it is the worse one. With the step the proposal is worse than today's rules with a stuck
feed (capital $0.974M against $0.939M) and a frozen book; without it, the five-minute crash push is worse than today
($1.188M against $0.899M), and so is the frozen book. The worst case of a wrong price with a book dip is better without
the step (8.15% against 13.10%; today 16.15%).

