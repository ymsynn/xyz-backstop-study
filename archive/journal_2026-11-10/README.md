# Design tests of 2026-11-10: from the three-vote mark to the candidate (pkgm3q1800 / lead3q1800, book-aware ratchet)

Copies of what produced `data/scen/tests_1110*` (git-ignored): the three scorecards in order, and the helper scripts as run.
The scripts write to `data/scen/tests_1110f`; preps for the seven out-of-sample market-days come from
`s3://.../backstop/oos/preps/` and need `reval_oos.sh` first (internal-session windows + relayer residual v2).

- `RESULTS_1_afternoon.md`: persistence, corroborated speed, three-vote (anchor reset on an unchanged feed).
- `RESULTS_2_discovery_bound.md`: the anchor inside trade.xyz's discovery bound gives the walk back; Hyperliquid's limits.
- `RESULTS_3_evening.md`: overnight walk, out of sample, closed sessions, one formula, ratchet, stuck feed.
- `score.py k|r|n`: scorecard of one variant folder. `ramp_overnight.sh`: sim/ramp_runs.sh with the own mark from 00:10 UTC
  (run with RELAYER_WARMUP_S=57600 and score with RAMP_AT_GOOGL / RAMP_AT_AMZN). `prop_runs_log.sh`: sim/prop_runs.sh + vault log.

Night of 2026-11-10 (candidate moved from pkgm3r1800, full ratchet, to pkgm3q1800, book-aware ratchet):
- `RESULTS_4_checks.md` (`run_checks.sh`): adaptive attack upward, normal sessions, anchor length.
- `RESULTS_5_adaptive_down.md` (`run_adaptive_down.sh`, `score_adapt.py`): downward adaptive attack; the full ratchet locks a book push in overnight.
- `RESULTS_6_ratchet_variants.md` (`run_ratchet_variants.sh`, `score_push.py`): book-aware and time-window ratchets.
- `RESULTS_7_book_aware_scorecard.md` (`run_book_aware.sh`): full scorecard of the book-aware ratchet.
- `RESULTS_8_day_walk_push.md`: the walk + $5M push by day liquidates the same positions in every design; the candidate's go to the vault (book emptied by the attacker).
- `RESULTS_9_one_sided_book.md` (`run_one_sided.sh`, `score_liquidated.py`): the overnight attack under three conventions for a one-sided book; Hyperliquid's rule unknown.
- `RESULTS_10_one_sided_tape.md` (`ec2/onesided_*.py`, `run_one_sided_quote.sh`): the tape shows the mark runs to the lone quote when a book side is empty; deciding tests rerun under that rule (ONE_SIDED=quote).
- `RESULTS_11_quote_rule_scorecard_and_quiet_feed.md` (`run_quote_scorecard.sh`): the scorecard is unchanged under ONE_SIDED=quote; a $5M book push on a quiet feed reaches the 5% bound in 5 min today, in under 2.5 h under the candidate.
- `RESULTS_12_skhx_gap_internal_oracle.md` (`run_internal_float.sh`): the SKHX gap was the capped internal oracle stepping from its rounded price (engine fix: unrounded state); SKHX now equals the previous candidate; quiet-feed push 2% per hour.
- `RESULTS_13_crash_push_split.md` (`run_crash_push_split.sh`, `score_push_split.py`): in the crash book push the attacker loses all its capital and no other account is liquidated; the vault's capital need rises because it inherits the attacker's own position.
