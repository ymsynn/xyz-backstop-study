# Downward adaptive attack on the candidate (pkgm3r1800), 2026-11-10 night, local
Runner: data/scen/tests_1110h/run.sh. Scorer: score_adapt.py (reproduces the upward table of RESULTS_4).
Engine change: ATTACK_PROP with frac < 0 = a sell limit below the mid (hits every bid at or above it, rests as an ask).

Feed walked -10% over 30 s and held 120 s; once the walk is complete a margined attacker offers 10% below xyz's mid (GOOGL 10-28).
Mark move vs the pre-walk mark. "after" = 30 s after the push ended, walk still held. Takeovers: extra vs the walk alone (total).

| Case                                   | today            | previous        | candidate, no ratchet | candidate        |
|----------------------------------------|------------------|-----------------|-----------------------|------------------|
| Walk alone, day / night: peak          | -790 / -816 bp   | -967 / -962 bp  | -78 / -28 bp          | -41 / -40 bp     |
| Walk alone, day / night: takeovers     | 7.16 / 7.87 $M   | 14.09 / 8.61 $M | 9.23 / 9.23 $M        | 9.31 / 9.31 $M   |
| Day, $1M push 60 s: extra (total)      | 6.18M (13.35M)   | 0.75M (14.84M)  | 0 (9.23M)             | 0 (9.31M)        |
| Day, $5M push 15 s: peak / after       | -752 / -741      | -999 / -959     | -343 / -70            | -402 / -411      |
| Day, $5M push 15 s: extra (total)      | 4.28M (11.44M)   | 0.75M (14.84M)  | 3.23M (12.47M)        | 3.85M (13.16M)   |
| Day, $5M push 60 s: peak / after       | -981 / -692      | -999 / -977     | -817 / -93            | -780 / -985      |
| Day, $5M push 60 s: extra (total)      | 6.18M (13.35M)   | 0.75M (14.84M)  | 11.45M (20.68M)       | 11.35M (20.66M)  |
| Night, $1M push 15 s: peak / after     | -475 / -703      | -772 / -961     | -392 / -20            | -402 / -412      |
| Night, $1M push 15 s: extra (total)    | 0.43M (8.29M)    | 0 (8.61M)       | 0.43M (9.66M)         | 3.34M (12.65M)   |
| Night, $1M push 60 s: peak / after     | -475 / -648      | -772 / -961     | -392 / -43            | -402 / -425      |
| Night, $1M push 60 s: extra (total)    | 0.16M (8.02M)    | 0 (8.61M)       | 0.43M (9.66M)         | 3.83M (13.14M)   |
| Attacker's execution cost, day $5M 60 s / night $1M 60 s | 0.46M / 0.01M | 0.46M / 0.00M | 0.47M / 0.13M | 0.47M / 0.13M |
$5M and $1M give the same result overnight in every design (the book is thin: $7.2M of sales empties the bid side).
Takeovers with no attack: today 6.06 $M (the tape), candidate 9.31, no ratchet 9.23.

Reading:
- Overnight the ratchet costs $2.9-3.4M of takeovers the version without it does not have (3.34-3.83M vs 0.43M): after the push
  ends the anchor has followed the mark down, so the mark stays 4% low until the feed is released; without the ratchet it is back
  within 15 s. By day the two are equal at 60 s (the damage is done during the push) and the ratchet adds 0.6M at 15 s.
- Against today and the previous candidate the candidate is still better by day at $1M (no effect vs 13-15 $M in total) and
  overnight in total only without the ratchet; at $5M by day both versions of the candidate end above today (20.7 vs 13.3 $M).
- Under today's rules and the previous candidate the walk alone has already emptied the bid side overnight: the attacker's
  offer finds almost nothing to hit (142-396 shares).

Limits:
- One-sided book: when the attacker has emptied the bid side the engine leaves the mark unchanged (mark_of needs bid, ask and
  last). 10-11 updates by day, 19-28 overnight. That is why the peak stops at about -400 bp overnight in every design; what
  Hyperliquid does with a one-sided book is not known to us, so the overnight peak may be understated.
- The replayed book does not react (no arbitrage against an offer 10% below the external price): market-maker reactions are
  out of scope, which favours the attacker.

Correction to RESULTS_4 (upward case): the "attacker's loss" row there was equity at the day's last mark, which includes the
real crash later that day. Execution cost against the mid before the push (60 s, candidate): 0.59M of $5M by day, 0.13M of $1M
overnight (upward); 0.47M / 0.13M (downward). It assumes the position can be closed at the pre-attack price.
