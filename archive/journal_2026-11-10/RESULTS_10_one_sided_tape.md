# What Hyperliquid's mark does with a one-sided book: evidence from the tape (2026-11-11)
Jobs (Tokyo spot instances, self-terminated, about $0.40 in all): ec2/onesided_screen.py (ec2/onesided_launch.sh) and
ec2/onesided_confirm.py (ec2/onesided_confirm_launch.sh). Small outputs in data/onesided/ (git-ignored) and
s3://<bucket>/backstop/onesided/.

Screen: 9 HIP-3 dexes on the hydromancer tape (native perps left out: another mark formula), 1.40M liquidation fills, 18,680
coin-days (every coin-day with a liquidation + the first 3 days of the 225 markets listed after the tape starts).
276 coin-days have a 1-minute snapshot with an empty side (xyz: 59 coin-days, 436 minutes, almost all at new listings, no
liquidation next to them). 168 liquidation fills sit next to a one-sided snapshot on 39 coin-days; 55 (33 blocks) sit between
two consecutive one-sided snapshots: hyna 28 blocks, km 3, cash 2 (data/onesided/between_events.csv).
The archive has no mark series outside liquidation fills (no asset contexts).

Confirmation: the deployer's setOracle (oracle, mark inputs, external) around each hit, from explorer_blocks.
| Event (UTC)                  | Book                         | Oracle  | Deployer mark input(s) | Liquidation marks              | Mark vs oracle |
|------------------------------|------------------------------|---------|------------------------|--------------------------------|----------------|
| hyna:ENA 2026-03-14 07:08    | no bids, one ask at 0.20     | 0.10755 | follows the mark       | 0.1199 -> 0.1392 in 54 s       | +11% to +29%   |
| hyna:BCH 2026-05-21          | no bids, one ask at 1000     | 379.35  | 379.33                 | 407 -> 454 -> 482 -> 496       | +7% to +31%    |
| hyna:PUMP 2026-01-15         | no bids, one ask at 0.01     | 0.002904| 0.0029026              | 0.004249                       | +46%           |
| hyna:FARTCOIN 2026-05-20     | no bids, one ask at 0.60     | 0.19039 | 0.188047               | 0.27663                        | +45%           |
| hyna:XPL 2026-02-06 / 02-07  | no bids, one ask at 0.17567  | 0.0750 / 0.0813 | 0.0749 / 0.0813 | 0.0936 / 0.0912, 0.1071        | +12% to +32%   |
| hyna:XPL 2026-02-10          | no asks, one bid at 0.008775 | 0.08105 | (stale)                | 0.0526, 0.0462                 | -35%, -43%     |
| cash:GOLD 2026-06-27         | no bids, one ask at 4700.5   | 4094.23 | 4094.23, 4094.23 (87 s old) | 4176.52 -> 4218.29 (= x 1.01) | +2%, +3%       |
| km:USBOND 2026-03-27         | no bids, one ask at 78.72    | 86.23   | 86.23, 79.64           | 79.64 = the second input       | -7.6%          |

What it shows:
- The mark does not freeze. With a side empty it leaves the oracle and the deployer's inputs and runs toward the lone
  remaining quote, at Hyperliquid's 1% per update when the deployer keeps publishing (ENA, GOLD), up to 30-46% away.
- It goes past the last trade (ENA: last trades 0.123-0.132, mark on to 0.139; GOLD: mark 4218.29 above the last fill 4214.39),
  so the last trade does not stand in for the book either: the lone quote does (alone or averaged with the last trade; the
  data cannot tell these two apart).
- One deployer input (hyna) is no protection; with two inputs that agree (km:USBOND) the median holds at an input. cash:GOLD
  has two inputs but they were 87 s old: Hyperliquid's 10 s stale rule had handed the mark to the local price.
- These are real losses: ENA 2026-03-14, shorts liquidated by the backstop and auto-deleveraged at 11-29% above an oracle that
  never moved, in one minute, because market makers had pulled their bids.
Limits: the book state is known per minute, not per block; events are kept only when the snapshots before and after are both
one-sided. Fills with method "market" are left out of the reading (the liquidation found a counterparty, so the book had that side).

For the engine: ONE_SIDED=quote (clearing.rs book_px): the remaining best quote stands for the book price. In the attack tests
the attacker's own resting order is that quote, so quote = last there.

## The deciding tests under the lone-quote rule (ONE_SIDED=quote; data/scen/tests_1110k, run.sh copied as run_one_sided_quote.sh)
Positions liquidated in the 300 s from the start of the walk, book + vault, $M (mark 30 s after the push, bp); GOOGL 10-28.
| Test                                         | today        | previous     | no ratchet   | full ratchet | book-aware   |
|----------------------------------------------|--------------|--------------|--------------|--------------|--------------|
| Overnight walk -10% alone                    | 14.8         | 15.0         | 0            | 0            | 0            |
| Overnight walk + $1M push 15 s               | 14.7 (-703)  | 15.0 (-961)  | 13.2 (-20)   | 14.0 (-505)  | 13.3 (-401)  |
| Overnight walk + $1M push 60 s               | 15.2 (-635)  | 15.0 (-961)  | 15.3 (-57)   | 15.6 (-995)  | 15.3 (-910)  |
| Overnight walk +10% + $1M push 60 s          | 0.43         | 0.43         | 0.41         | 0.41         | 0.41         |
| Day walk -10% + $5M push 60 s                | 11.3         | 12.0         | 11.9         | 12.7         | 11.9         |
| Crash push $5M 60 s / 300 s: capital need $M | 0.90 / 0.90  | 0.36 / 0.36  | 0.82 / 1.18  | 0.50 / 0.50  | 0.79 / 0.84  |
| Crash push $5M 60 s / 300 s: inherited $M    | 44.3 / 44.3  | 8.6 / 8.6    | 40.3 / 59.5  | 16.9 / 16.9  | 39.3 / 38.8  |
One-sided updates in these runs: overnight 187, day 44, crash push 0 (its numbers are unchanged from RESULTS_6).

Reading: with the real rule, once the attacker has emptied the bids and the feed is walked, two of the three votes sit 10% low
and every design marks 10% low: the ratchet versions no longer differ in what is liquidated overnight (13.2-15.6 $M, as much
as today's rules lose to the walk alone). They differ only in how long the mark stays there after the push (no ratchet: back in
30 s; full: until the feed is released) and in the crash push, where the full ratchet is clearly best. The reason to leave the
full ratchet (RESULTS_5: overnight lock-in) came from the engine's old rule for a one-sided book and does not hold.
What the three-vote mark still buys overnight: the walk alone liquidates nothing (today 14.8 $M); the attacker needs the feed
and $1M on xyz's book.
