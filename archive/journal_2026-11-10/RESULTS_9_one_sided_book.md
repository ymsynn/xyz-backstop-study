# One-sided book: what the mark does when the attacker has emptied the bid side (2026-11-10/11 night, local)
Runner: data/scen/tests_1110j/run.sh (copy: run_one_sided.sh). Scorers: score_adapt.py (ONE_SIDED as in the run), score_liquidated.py.
Hyperliquid's rule is not known: its docs give med(best bid, best ask, last trade) and say nothing of an empty side
(robust-price-indices, hip-3-deployer-actions, read 2026-11-11); on the 22 local market-days no real liquidation mark (about
1,700) was printed with a one-sided book (engine replay, MARKDBG, line MARKONE). Three conventions in the engine (clearing.rs book_px):
  hold  the mark is left unchanged (the engine's rule so far)
  last  the last trade stands for the book price
  drop  the book vote drops out: mark = mean of the two published inputs

Overnight, GOOGL 10-28 04:30 UTC: feed walked -10% and held 120 s, then $1M offers 10% below the mid for 60 s.
Positions liquidated in the 300 s from the start of the walk, book + vault, $M (mark 30 s after the push, bp):
| Design                     | walk alone | + push, hold  | + push, last  | + push, drop   |
|----------------------------|------------|---------------|---------------|----------------|
| today                      | 14.8       | 14.7 (-648)   | 15.1 (-635)   | 14.7 (-665)    |
| previous candidate         | 15.0       | 15.0 (-961)   | 15.0 (-961)   | 15.0 (-983)    |
| three-vote, no ratchet     | 0          | 5.1 (-43)     | 5.2 (-45)     | 13.3 (-233)    |
| three-vote, full ratchet   | 0          | 13.4 (-425)   | 15.6 (-994)   | 15.6 (-1001)   |
| candidate (book-aware)     | 0          | 4.9 (-231)    | 14.0 (-508)   | 15.6 (-1005)   |
By day ($5M, 60 s) the three conventions give the same result in every design (20.7 $M of takeovers in the three-vote
versions with ratchet; 18.4-20.7 without), see RESULTS_8.

Reading:
- Walk alone: today and the previous candidate lose about $15M whatever the convention; every three-vote version loses nothing.
- Walk + $1M book push: the candidate is between $4.9M and $15.6M depending on a rule we do not know. At worst it equals today
  (which needs no push); it is never worse.
- The book-aware ratchet's advantage over the full ratchet holds only under "hold". Under "last" the last trade sits at the
  attacker's price, beyond the feed's vote, so the feed is the deciding vote and the anchor follows: 14.0 vs 5.2 with no ratchet.
- The version without ratchet is the most robust overnight (5.1-5.2 under hold / last), and fails only under "drop".
Note: "extra takeovers vs the walk alone" (RESULTS_5, 6, 7) nets out positions the real crash of that day liquidates later
anyway (the overnight attack is 15.5 h before it); the window totals above are the cleaner measure.
