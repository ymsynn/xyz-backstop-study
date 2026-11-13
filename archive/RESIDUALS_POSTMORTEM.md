# Replay residuals: post mortem

2026-11-03. Covers GOOGL 2026-10-28 and INTC / AMZN 2026-10-29 (earnings-close crashes), after the two fixes of the same day (isolated opening margin at a gap, trigger modify by cloid; see `SIMULATOR_SPEC.md`, "INTC / AMZN validation").

## Summary

At real parameters with **real marks**, the replay reproduces the vault to within 0.4% on GOOGL and INTC and 8.6% on AMZN. Takeovers land in the same block 97–99% of the time. Every remaining dollar of vault gap is traced to named accounts below.

Four findings matter before any scenario runs:

1. **The simulated relayer failed the gate on INTC and AMZN. Fixed the same day (see R1).** `MARK_SOURCE=simulate` dropped same-block takeovers from 97% to 77% (INTC) and 45% (AMZN), even with the residual file. Two relayer rules that GOOGL never exercised were missing. With both added, the simulated relayer plus residual reproduces the real mark on 100% of scored updates on all three coins, in both modes.
2. **Liquidation and vault fills go to different makers in the sim.** This causes 85–98% of the ENDO=0 end-of-day position error, and it produced the largest false takeover on GOOGL.
3. **The cross-margin model has blind spots.**
   - A cross liquidation triggered by another coin's mark is missed at block resolution.
   - Very large multi-position accounts pass validation with errors bigger than the margin of their small position on this coin.
   - Accounts that fail validation are replayed rather than simulated: 15% of GOOGL's real takeover notional.
4. **The engine liquidated sub-lot sizes. Fixed 2026-11-04 (see R4).** Partial rounds and vault orders now sit on the coin's size grid. A smaller residual remains: the sim liquidates slightly more than HL.

## Method

All runs use `MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1` with default rules (including `iso_open=mark`). ENDO=0 replays users' real fills and simulates liquidations, triggers and the clearing. ENDO=1 also simulates the counterparties (endogenous makers). VAULT=replay replays the vault's real unwind fills; otherwise the vault follows the 0.5%-per-update policy.

Diagnostics written for this note:
- `SIM_TK_OUT` / `MISSED_OUT`: per-account takeovers.
- `ROUNDS_OUT` (new): market-liquidation rounds, real vs sim.
- `EOD_OUT` (now with entry price, margin and isolated flag).
- `TRIG_OUT`, `ORC_OUT`.

Analysis scripts are in the session scratchpad (`pm/`): `tkclass.py`, `tkpos.py`, `eodattr.py`, `vaultgap.py`.

## Scoreboard

| | GOOGL Oct 28 | INTC Oct 29 | AMZN Oct 29 |
|---|---|---|---|
| Real vault PnL | −$183.0k | −$100.7k | −$48.4k |
| Sim ENDO=0, real unwind | −$182.3k | −$100.9k | −$52.5k |
| Sim ENDO=0, policy unwind | −$181.9k | — | — |
| Sim ENDO=1, policy unwind | −$181.7k | −$97.6k | −$47.9k |
| Takeovers ENDO=0: both / sim-only / real-only | 150 / 9 / 3 | 256 / 8 / 5 | 398 / 6 / 1 |
| Same block, ENDO=0 | 99.3% | 97.7% | 97.2% |
| Same block, ENDO=0 with simulated relayer + residual | 99.3% | 76.6% → **97.7%** after fix | 45.0% → **97.2%** after fix |
| Takeovers ENDO=1: sim-only / real-only | 23 / 7 | 19 / 6 | 14 / 1 |
| End-of-day positions exact, ENDO=0 / ENDO=1 | 95.4% / 88.0% | 95.2% / 86.5% | 96.5% / 84.7% |
| Market-liquidated in both: same total filled / within 5% | 76.1% / 96.5% | 50.7% / 89.5% | 23.1% / 93.9% |
| Real trigger takers fired in the same block | 732 / 734 | 373 / 379 | 305 / 309 |

## Where each vault gap comes from

With the real unwind replayed, the vault's PnL difference equals the difference in what it inherited. The table values each account's takeover, sim minus real, at the day's last price. Accounts the engine does not simulate are inherited exactly as they happened, so they contribute zero.

| | GOOGL | INTC | AMZN |
|---|---|---|---|
| Both, size within 5% | +$703 | +$970 | +$12 |
| Both, size off by more than 5% | +$12 (19 accts) | −$1,166 (34) | +$333 (11) |
| Sim-only takeovers | −$317 (9) | −$2,656 (8) | **−$5,257 (6)** |
| Real-only, missed by the engine | +$26 (5) | +$2,581 (7) | +$508 (4) |
| **Sum** | **+$423** | **−$271** | **−$4,404** |
| Actual PnL gap (sim − real) | +$667 | −$161 | −$4,117 |

The sums match the PnL gaps to within $300, so no dollars are unaccounted for. The AMZN gap is two sim-only accounts: 0x05cc5c9c (−$3,755) and 0x4b8600a7 (−$1,590); see R3. The INTC figure nets two larger opposing terms: sim-only 0xa38f19c4 (−$3,287) against the missed 0xea3ce3e9 (+$2,158).

## Residuals, by impact on what scenarios measure

### R1. Oracle chain at the crash onset (relayer model, INTC / AMZN) — fixed

**Resolution:** two rules were missing.
- **External-price cap:** the oracle and m2 stay within 1 / maxLeverage of ext, and the cap overrides the 50 bp clamp. INTC published exactly ext × 1.10 and AMZN ext × 1.05 for ~25 updates. Prep's lag search knew neither the cap nor exact rounding, so it fell back to k = 1.
- **m2's band** is the hull of the bands around the lagged oracle and around m2's own lagged value.

**After the fix:**
- m1 is exact on 100% / 99.98% (1 update) of scored updates.
- With the residual, the mark is exact on 100% for GOOGL, INTC and AMZN, in ENDO=0 and ENDO=1.
- Takeovers and vault PnL equal the real-mark runs.

Details are in `SIMULATOR_SPEC.md`, "Relayer reconstruction". The original analysis follows.

- **Symptom:** with `MARK_SOURCE=simulate`, m1 is exact on 98.65% (INTC) and 99.15% (AMZN) of updates in the 18:00–22:00 window; GOOGL was 100%. m2 is exact on 36% / 73% without the residual and 90% / 99.6% with it. Takeovers in the same block fall to 77% / 45% whether or not the residual is applied.
- **Where:**

  | Coin | Crash misses | Window | Late misses |
  |---|---|---|---|
  | INTC | 65 | 20:01:33–20:43:12 | 96, within 8 bp |
  | AMZN | 41 | 20:01:06–20:43:54 | 93, within 8 bp |

  The late misses come from the next day's 00:00–00:05 at the end of the tape and don't affect anything.
- **Mechanism:**
  - In the first 10–15 crash updates the sim's m1 is off by up to ±50 bp (one full clamp step) on some updates. For example, INTC 20:01:33 gives 90.489 vs 90.911 real.
  - After that, every update is a clamped step from the previously published oracle. A single wrong step locks in a constant offset for the rest of the descent: INTC +4.6 bp, AMZN −17 bp, for about 40 minutes.
  - The residual file only corrects m2. Its lag override applies only when the real m2 falls outside the band, so it cannot fix m1.
- **Likely cause:** the read lag k that prep infers at the crash onset is wrong on some updates; the relayer read an older or newer on-chain oracle than the one inferred. On GOOGL all 22 crash updates fit the lag rule. The sequences 1,1,1… then 2,3,1,2,3 seen here suggest the relayer's read cadence differs on these coins.
- **Fix candidates:**
  1. For parity, record per update the lag (or reference) that reproduces the real m1, and replay it in scenarios as the relayer's observed read timing, just as the m2 residual keeps the relayer's view error.
  2. Separately, refit the lag rule on the INTC / AMZN crash onsets.
- **Why it matters:** a clamp scenario moves exactly this chain. Until m1 parity holds on all three coins, a change in the clamp cannot be separated from model error.

### R2. Liquidation and vault fills reallocated to other makers — fixed 2026-11-04 (it was a bug, not the design)

**Resolution:**
- In ENDO=0 the clearing dropped a real liquidation fill for any margined account, the maker side included, and the simulated rounds do not credit makers in ENDO=0. The analysis below took this for an inherent effect of the hybrid mode.
- Both sides carry the liquidation method, and only `is_liquidation` tells them apart, so acc_events now carries a `liq_side` flag (`sim/liqside.py`). Counterparties keep their real fill.
- **Results:**
  - End-of-day positions exact: 99.6 / 99.4 / 99.7% (was 95.6 / 95.6 / 97.2%); position error 0.12 / 0.05 / 0.01% of gross.
  - INTC sim-only takeovers 0.
  - Vault −$182.6k / −$99.5k / −$48.5k against −$183.0k / −$100.7k / −$48.4k.
- The original analysis follows.

- **Symptom:** end-of-day position errors in ENDO=0 concentrate almost entirely in accounts that were real makers of liquidation or vault fills.

  | | GOOGL | INTC | AMZN |
  |---|---|---|---|
  | Share of total \|position error\| | 93.2% | 98.3% | 85.2% |
  | Accounts in that group mismatched | 157 / 291 | 84 / 166 | 38 / 94 |
  | Other accounts mismatched | 4 / 3,585 | 1 / 1,901 | 1 / 1,367 |

- **Mechanism:** ENDO=0 replays users' own fills but simulates liquidations and (in policy mode) the vault. The engine skips the real liquidation-fill events of accounts it margins, expecting its own liquidation to recreate the fill. When the simulated round or unwind meets a slightly different book, it fills other resting orders. The real maker never gets its fill, and its later real trades are then replayed on top of a position it never had.
- **Worst case:** GOOGL 0x4dbda869.
  - At 20:03:37 it bought ~168 shares from liquidations and ~134 from the vault unwind as a maker. The sim gave those fills to others.
  - At 20:06 it sold its real long of 58.9 shares, which in the sim left it 167.9 short.
  - At 20:27:54 a real $20,338 USDC send to the HyperEVM system address left that phantom short under-collateralized, and the sim took it over ($50k notional; it held nothing in reality).
- **Also:** INTC 0xa38f19c4 (sim 718 shares vs real 2,566 at the takeover; maker of 644 liquidation shares) and the INTC market maker found earlier.
- **Status:** inherent to the hybrid mode, not a rule error. In ENDO=0 it costs at most one or two false takeovers per coin, but it inflates every position-based metric.
- **Fix candidates:**
  1. Hard parity mode: credit real liquidation and vault maker fills to the real makers whenever the sim's round fills at the same block and price level.
  2. Report ENDO=0 position metrics excluding these makers, since the error is structural.

### R3. Cross-margin collateral model — the AMZN gap and a scenario blind spot

**(a) Liquidations triggered from another coin — fixed 2026-11-04.**
- crossacc now marks other xyz coins at every relayer update with no lookahead, re-evaluates near-liquidation accounts every update, and delays other coins' liquidation fills by one block.
- 0x05cc5c9c is now liquidated at 13:32:28.689 like on HL.
- AMZN takeovers now match reality ($1.55M vs $1.55M, 0 real-only); its vault gap went from −$4.1k to −$2.8k.
- Details in the spec, "INTC / AMZN validation" item 4. Original analysis:
- AMZN 0x05cc5c9c is a unified account with AMZN 188 and GOOGL 137 cross and $5.1k USDC. HL market-liquidated both positions at 13:32:28.
- The single-coin engine sees GOOGL only through crossacc's minute marks, so it never triggered.
- At 14:11 a real $2,087 withdrawal of what was left pushed the still-open sim position below zero equity → a sim-only takeover, −$3,755 on the vault.
- **Fix candidate:** feed other coins' marks at block resolution (every xyz relayer update is in the node data), or as a parity crutch, mark real cross liquidations of other coins as events that close this coin too.

**(b) Large multi-position accounts — fixed 2026-11-04.**
- The validation tolerance is now capped at 25% of the peak MM of the account's position in this coin (`CROSS_TOL_MM`).
- 0x4b8600a7 and 33 / 22 / 49 accounts on GOOGL / INTC / AMZN are now replayed; none had a real takeover.
- AMZN's vault is now −$48.1k vs −$48.4k real.
- The underlying error (isolated margin on another coin solved from its liquidation price) is not modelled better, only kept out of the simulation. Original analysis:
- AMZN 0x4b8600a7 holds $3.58M USDC almost entirely as margin for a $10.5M isolated SMSN position. Its modelled cross collateral starts at $0.02.
- It opened 89 AMZN cross shares ($20k notional, ~$1k IM) that HL accepted, but the sim showed equity −$4.2k → two sim-only takeovers, −$1,590.
- Validation passed with a $681 error, because the tolerance (0.2% of account value, $5.7k here) exceeds the AMZN position's whole margin.
- **Probable cause:** the isolated SMSN margin is solved from the snapshot liquidation price, and a 0.15% error on $2.6M swamps this account's cross balance. Not proven.
- **Fix candidate:** scale the validation tolerance to the coin position's maintenance margin, not to account value.

**(b2) Other coins' margin mode and isolated margin — found and fixed 2026-11-04.**
- crossacc ignored margin-mode switches and isolated-margin transfers on other coins, and reopened main-dex positions at the snapshot's leverage.
- Two accounts were affected: AMZN 0xd8e37894 (HL takeover missed, $9.5k) and GOOGL 0x8b2d0bd7 (false takeover).
- Both now match HL. AMZN's ENDO=0 vault is −$48.5k vs −$48.4k.
- The remaining GOOGL / INTC vault gaps are the two R2 accounts (0x4dbda869, 0xa38f19c4); everything else is under $410.
- Details in the spec, "INTC / AMZN validation" item 6.

**(c) Accounts the engine does not simulate.**
- Accounts that fail validation, portfolio-margin accounts that don't validate (64 on GOOGL), and market makers with more than 20k fills are replayed: their positions come from the tape and any real takeover is inherited as it happened.
- That is 16 / 20 / 21 takeovers, or **$1.10M of $7.16M (15%) on GOOGL**, $0.13M of $2.38M on INTC and $0.02M of $1.57M on AMZN.
- At real parameters this is exact by construction. In a scenario these accounts cannot react, so GOOGL's vault result carries a fixed 15% block.

**(d) Unexplained.** HL accepted triggered market orders that opened $38k AMZN shorts from unified accounts holding about $300 (9 cases, all filled for real). A plain initial-margin check at trigger time would reject them. Either their collateral is larger than modelled, or HL skips the check for triggered market orders. The 1,000-share triggers of 0x821ac5e0 left no fill at all, which is consistent with both. The `TRIG_IM=1` option exists but stays off.

### R4. Market-liquidation rounds — sub-lot sizes fixed

**Resolution (2026-11-04):** liquidation sizes now sit on the size grid (`lot_round`, default).
- The partial 20% is floored to the lot; of the partial rounds that filled in full, 10 match only the floored size and none only the nearest.
- The equity-stop cap is floored to the lot.
- The vault policy order floors its size and rounds the $10 minimum up.

Results:
- Same total filled: 76.1 → 80.6% (GOOGL), 50.7 → 68.8% (INTC), 23.1 → 37.8% (AMZN).
- Takeover sizes within 5%: 90.0 / 92.2 / 98.0%.
- Vault PnL moves less than $10.

**Left:** the sim fills more than HL in 123 / 141 / 284 accounts (fewer in 16 / 28 / 20), often over extra rounds. Excluding the top 3 accounts per coin, that is 34 / 58 / 13 shares of excess, against 31.7k / 50.2k / 3.6k shares liquidated. The likely cause is an equity stop or margin release slightly looser than HL's. The original analysis follows.

- **Sub-lot sizes (engine error, fixable):**
  - Partial rounds (20% of positions over $100k) are not rounded to the coin's size grid, e.g. 14,820.0357 GOOGL shares vs 14,792.144 real.
  - Of the accounts whose round totals differ, the difference is at most 10 lots for 88 / 171 (GOOGL), 204 / 267 (INTC) and 255 / 376 (AMZN). This is why "same total filled" reads only 23% on AMZN while 94% are within 5%.
  - Dollar effect: small. Sum of |difference| is 987 GOOGL shares (mostly a few accounts, below) and 107 AMZN shares.
- **Round vs takeover split:**
  - Real-only takeovers are cases where the sim's market round filled what HL backstopped. INTC 0xea3ce3e9: the real round filled 73 shares, then a 125-share takeover; the sim's round filled all 198.
  - So does the largest round difference, INTC u3016 (sim filled 2,801 vs 1,157 real).
  - Either the sim book held more bids inside the round's limit than HL's, or HL's equity stop cut earlier. Seven accounts on INTC, $2,581 of vault value.
  - The reverse also occurs. Several small isolated accounts were market-liquidated by HL in an earlier block, while in the sim the round didn't fill and they were taken over at the next update (equity at 0.70–0.85× the backstop threshold).

### R5. ENDO=1 drift and same-price priority exceptions — queue rule found (2026-11-04)

**Resolution:**
- Makers are FIFO, and a modify re-queues at the back. A higher priority bid ("na" = p 0 < p 1 < …) queues ahead of lower bids that arrived less than 399 ms before it.
- Fitted on GOOGL, it cuts same-price skips by 63% on GOOGL, 90% on INTC and 85% on AMZN, and pure matching reaches 97.3 / 98.1 / 97.5% exact takers.
- The ENDO=1 drift improves only ~0.4 points; it is mostly book-state divergence.
- The two update notes below (written earlier the same day) are superseded.


**Update:**
- HL priority orders (`grouping` `{"p": N}`) predict *who* wins when HL breaks FIFO at a price (1,384 / 1,601 GOOGL exceptions). They don't predict *whether* it does: as a queue rank they make matching worse (95.63% → 94.36% maker-by-maker), and an age window doesn't help. Code kept behind `PRIO=1`.
- The ENDO=1 drift is a cascade: ~5% of maker volume (45.7k of 895k GOOGL shares) goes to different orders, then takers and positions follow. Silent-cancel timing explains 1.5k shares of it.
- ENDO=0 stays the primary mode for scenario baselines. Original analysis:

- With endogenous makers, end-of-day positions are exact for 84.7–88.0% of accounts.
- Sim-only takeovers rise to 23 / 19 / 14. In 18 / 23, 18 / 19 and 11 / 14 of them, the sim position at the takeover already differs from reality, so they are a consequence of drift, not a separate error.
- Total takeover notional stays within 1–10%: $6.13M vs $6.06M, $2.30M vs $2.25M, $1.71M vs $1.55M.
- The root residual measured on GOOGL is the 2,722 same-price priority exceptions: HL fills a newer order before an older one at the same price.
  - Ruled out as explanations: margin, OI caps, modifies, oid or nonce order, size fit, maker direction.
  - No rule found; they concentrate in high-frequency market makers.
  - Not yet counted on INTC / AMZN.

### R6. Isolated margin rule

The opening rule (`iso_open=mark`) fits the next snapshot within $1 for 988 / 1,131 (INTC), 1,536 / 1,670 (GOOGL) and 605 / 626 (AMZN) isolated positions. It now errs on the safe side more often (over-margins 105 / 123 / 19, under-margins 38 / 11 / 2). It uses the oracle-update mark, which can be stale at fill time.

The "slack" variant (only the loss beyond the position's surplus over IM) fits about as well. The data does not separate the two, which would matter in scenarios with larger gaps.

### R7. Triggers

- Real trigger takers fire in the same block 99.7% / 98.4% / 98.7% of the time. None are missed.
- Sim-only firings (546 / 1,698 / 340) fall into three groups:
  - reduce-only drops with nothing to reduce (232 / 212 / 84; HL shows nothing for them either);
  - limit triggers that rest in the book (229 / 1,398 / 123);
  - market triggers with no real fill (85 / 88 / 133).
- **Phantom liquidity (fixed 2026-11-04 by a sanity cap on triggered orders, `ORDER_CAP_X`; all 1,378 rejected, no real fill affected):** 1,030 of INTC's sim-only resting triggers belong to one account. They are buy take-profits for ~2M shares at a $10 limit. They are harmless at real prices, but in a crash scenario they would stand as a ~$20M bid at $10 that HL would almost certainly reject for margin. Scenario runs should exclude or cap orders whose notional exceeds any plausible collateral.
- Fixed this session: modifies by cloid now replace the trigger (it was the AMZN ENDO=1 blow-up).

### R8. Vault unwind

- With the real unwind replayed, the vault gap is purely inheritance (see the gap table).
- The GOOGL policy unwind (0.5% of inventory per update) lands at −$181.9k vs −$182.3k replayed, which makes it a reasonable stand-in at real parameters.
- Policy runs on INTC / AMZN (ENDO=1) land at −$97.6k and −$47.9k against −$100.7k and −$48.4k. Part of that is the policy, not the inheritance. ENDO=1 itself changes INTC's inheritance by only $1k, so most of INTC's $3.1k gap is likely the policy; not run separately.

## What this means for the next step

- **Ready:** b / mark-buffer scenarios. The liquidation engine, isolated margin, triggers and inheritance are within a few $k at real parameters on all three coins.
- **Ready since the R1 fix:** clamp and cap scenarios, on all three coins. Two cautions:
  - On INTC the plain m2 model is weak (37.6% exact), so results there lean on the recorded residual.
  - The new external-price cap (`ORACLE_CAP`) binds in a crash and interacts with any clamp change.
- **Read with care:** GOOGL scenario results carry a fixed 15% of takeover notional that cannot respond (R3c). ENDO=1 position metrics carry the R2 / R5 drift.

## Recommended order

1. ~~**R1**~~: done (external-price cap, m2 hull band). Gate met: m1 100% / 99.98%, mark 100% with the residual, takeovers as with real marks.
2. ~~**R4**~~: done (size grid). Same total filled 80.6 / 68.8 / 37.8%. The over-liquidation left in a few accounts is small.
3. ~~**R3a**~~: done (block-resolution marks for other coins, joint liquidation). AMZN's largest false takeover is gone.
4. ~~**R3b**~~: done (tolerance ≤ 25% of the coin position's MM). AMZN vault −$48.1k vs −$48.4k real.
5. ~~**R7**~~: done (triggered orders capped at 5 × max leverage × account value; 1,378 INTC phantoms rejected, no real fill affected).
6. ~~R2~~: done (counterparties keep their real liquidation fills). The R5 priority exceptions only if scenario results turn out to be sensitive to them.
