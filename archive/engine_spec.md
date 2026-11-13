# xyz block-level market simulator: spec

Goal: replay a HIP-3 market block by block, with the margin and mark rules as parameters.
- With today's parameters, the replay must reproduce the real event: the same fills, the same liquidations, and the same backstop PnL.
- With other parameters, it should show what would have happened.

Primary use: the trade.xyz backstop-loss events (GOOGL 2026-10-28, INTC and AMZN 2026-10-29, then the July–Sep events), to test (1) a deployer-set MM buffer and (2) changes to the relayer mark method.

## 1. What has to be simulated, per block

| Component | State | Driven by |
|---|---|---|
| **Order book** (per coin) | resting orders: oid, user, side, px, sz, tif, priority | replayed user orders, cancels and modifies; simulated liquidation and vault orders |
| **Matching** | fills (price-time, HL in-block order: non-order actions → cancels → orders in proposer order) | book + incoming orders |
| **Oracle / mark** | oracle px, mark components, mark | relayer `setOracle` (replayed, or re-simulated under a new relayer rule) + book component |
| **Clearinghouse** | per user: positions (size, entry), isolated margin per position, cross balance, leverage setting, margin mode, account mode (standard / unified) | fills, funding, ledger events, `updateLeverage`, `updateIsolatedMargin` |
| **Margin checks** | IM on order placement (orders rejected if IM is not met), MM per position or account | params + state |
| **Liquidation engine** | per account: equity vs MM and ⅔·MM, partial-liquidation cooldowns | mark + clearinghouse |
| **Backstop vault** (`0x4000…0001` on dex xyz) | inherited positions, equity, unwind orders | takeovers + unwind policy |
| **ADL** | triggered if the vault's (or any) account value < 0 | ranking per HL docs |

Outputs per block: book BBO, depth, mark, MM, IM, equity, liquidations and vault state, for the whole market and per account.

## 2. Parameters (everything the counterfactuals vary)

Default = today's mainnet value.

**Margin**
- `max_leverage[coin]` / margin table (today: single tier, GOOGL 20, AMZN 20, INTC 10)
- `mm_buffer_b[coin]`: MM rate = b / maxLev (today b = 0.5; proposal: b = max(0.5, deployer value))
- `im_rate[coin]`: 1 / maxLev; separable from MM in the sim, even though HL ties them today
- `backstop_factor`: takeover below this × MM (today ⅔)
- `partial_liq_threshold` ($100k), `partial_liq_fraction` (20%), `partial_liq_cooldown` (30s)
- **Schedule:** any of the above can be a function of time (switch, ramp, announcement lead time), plus a `transition_policy` for positions caught between the old and new MM: liquidate, ramp, or grandfather.

**Mark / oracle (relayer)**
- `mark_source`: `replay` (the real relayer `markPxs`) or `simulate` (rebuild the relayer from its inputs)
- `clamp_bps` per component (today ±50 bps per update, on the oracle and both mark components)
- `clamp_components`: which components are clamped (e.g. oracle-only widening)
- `ema_tau` for component 2 (today 150s)
- `update_interval` (today ~3s)
- `median_rule`: today the median of the 2 relayer components and the book median (bid, ask, last)
- `event_windows`: scheduled windows where clamp or MM differ

**Agents**
- `others_policy`: open-loop replay of every other user's actions (default). Later: response models (makers pull or widen; traders top up when MM rises).
- `trader_response` to an MM change: none / top-up to new IM / reduce to new IM (the three bounds we already use)
- `vault_unwind`: `replay` (real schedule), or a policy (TWAP over N min, taker clip size, maker posting)

## 3. Data inputs and status

| Need | Source | Status |
|---|---|---|
| All user actions per block (orders, cancels, modifies, leverage, isolated margin, TWAP) | `s3://hl-mainnet-node-data/replica_cmds/<snapshot>/<date>/<block>.lz4` (+ `resps` = order results) | ✅ available. 1.3–4.8 GB per 10k-block file (~12 min), so process in-region on EC2 (`quant_share/ec2/launch.sh` pattern, ~$1.5 per day) |
| **Relayer oracle and mark inputs** | same stream: `multiSig` (multiSigUser `0x1234…acec`) → `perpDeploy.setOracle{dex:"xyz", oraclePxs, markPxs:[comp1, comp2], externalPerpPxs}` | ✅ **verified**, one update every ~3s, e.g. GOOGL 00:02:11 oracle 323.35, comps [323.35, 323.83], ext 323.31 |
| Actual fills (for validation) | `node_fills_by_block`; hydromancer `by_dex/xyz/fills/perp/all` | ✅ (hydromancer pulled for Oct 28–29) |
| Ledger and funding events | `misc_events_by_block/hourly/<date>/<h>.lz4` (LedgerUpdate, Funding, …) | ✅ ~14 MB/h |
| Initial positions and margins | hydromancer `by_dex/xyz/snapshots/perp/date=D/<block>_<ms>.parquet` (daily, aligned to a block: size, entry, liq px, leverage type, account value, account mode). Isolated margin solved from liq px (validated: whale within 2%). | ✅ for xyz. ⚠ unified-mode cross accounts share margin across dexes, so the **main-dex snapshot for the same users** is also needed |
| Initial resting orders | not published. Warm-up: replay from snapshot block (00:02) so most resting orders are seen being placed | ⚠ orders older than the warm-up are invisible; measure against hydromancer `orderbook/1m` |
| Real mark (validation) | `liquidation.markPx` on liquidation fills; recompute from `markPxs` + book | ✅ partial |
| xyz rules not in docs | must be inferred from data (see §6) | ⚠ |
| `hyperliquid-archive/asset_ctxs` | main dex only, **no `xyz:` rows** | ❌ not usable |

## 4. Validation (baseline must reproduce reality before any counterfactual)

Run with default parameters, open-loop, `mark_source=simulate` using the real relayer components:
1. **Book:** simulated BBO matches the real one (hydromancer `orderbook/1m` snapshots, and the price on every real fill), with ≥ 99% of fills at the same px, size and block.
2. **Mark:** recomputed mark = `liquidation.markPx` on every liquidation fill (exact).
3. **Clearinghouse:** simulated liquidation price per position matches the next daily snapshot. Account value at each takeover matches the fill-derived value (whale: $65,170 at 20:02:46.731).
4. **Liquidations:** same accounts, same blocks, same sizes (whale: 20% at 20:02:40.745, then 8,269.612 at 20:02:43.804, takeover of 17,820.519 at 20:02:46.731).
5. **Backstop:** takeover notional and PnL per event (GOOGL $7.16M / −$183k, INTC $2.38M / −$101k, AMZN $1.47M / −$48k).

Any miss here means a rule is missing; it is not noise.

## 5. Standard views (every run produces the same set, baseline vs counterfactual overlaid)

Time axis is blocks; the default window is event −10 min → +90 min, with a zoom on the first 2 min.

1. **Book:** best bid, best ask, mid, trade prints; depth bands (notional within 0.5%, 1%, 2% of mid, each side).
2. **Price stack:** mark, mark comp1 (oracle), mark comp2 (oracle + EMA), book component, external perp px, mid. Shaded: mark − mid gap.
3. **Margin, market-wide:** Σ IM, Σ MM, Σ ⅔·MM, Σ equity at mark and at mid. Number of accounts and notional below MM and below ⅔·MM.
4. **Liquidation flow:** market-liquidation notional per block (requested vs filled), backstop takeovers, ADL.
5. **Backstop vault:** position, equity, unwind fills, cumulative PnL.
6. **Account drill-down** (any address): position, margin, equity at mark and at mid, MM, ⅔·MM, events. This is the whale table as a chart.
7. **Scenario summary table:** vault PnL, take notional, OI forced out, trader top-up needed, trader losses (liquidated equity), fills that diverged from baseline.

## 6. Rules to pin down from data (docs are silent or ambiguous)

- When the mark is applied: the block of the `setOracle`, or the next one. How "last trade" enters the book component.
- Where the liquidation check sits in the block: before or after user actions. Liquidation order type and price limit (we saw partial fills; no fixed floor found).
- Backstop transfer price rule (observed: px = entry − margin/size, i.e. the trader ends at 0).
- Isolated margin on voluntary reduce: released proportionally or retained (affects reconstruction).
- Funding formula and timing for HIP-3; fee schedule incl. deployer fee share.
- What happens to open positions when `maxLeverage` / margin table is lowered.
- The relayer's own rule (needed for `mark_source=simulate` with new clamps): its unclamped target from `externalPerpPxs` and impact prices, per the trade.xyz oracle and mark docs.

## 7. Known limits

- **Open loop.** Other users' orders are replayed as sent. In a counterfactual, makers would requote differently and stop orders could trigger at different times. Report the share of replayed fills that changed, and treat large divergence as low confidence. Response models come later.
- **No order-level book seed.** The warm-up from 00:02 leaves very old resting orders unseen; quantify against the 1-min book.
- **Cross-dex unified accounts** need main-dex state too. First version: xyz-only accounts exactly, unified accounts with a main-dex snapshot overlay.

## Phase 0 results (2026-11-03, Oct 28, extract from 00:02:09 = block 1199710001)

Tables live in the session scratchpad (`extract1028/tables/`, 378 MB) and on S3 (`<bucket>/backstop/xyz_extract/20261028/parts/`):
1.21M blocks; 3.77M GOOGL sub-orders; 4.27M cancels; 657k xyz state actions; 28,966 xyz setOracle updates (every 3.0s, max gap 6.1s).

**Fill coverage** (share of real GOOGL fill notional whose order is in the stream):

| | Maker | Taker |
|---|---|---|
| All day | 92.9% | 94.5% |
| Crash, 20:01:50–20:05 | 96.1% | 90.1% |

What is not in the stream during the crash:
- Backstop takeovers ($6.4M on the maker side) are engine transfers, not orders.
- **The vault's unwind orders ($1.36M of crash taker flow) are not user-signed actions.** The baseline replay must inject them from the fills, or model them.
- The rest: makers $1.23M (3.9%) and takers $1.77M (5.6%), likely `modify` results with no returned oid, plus orders resting since before 00:02.

**Where the missing orders were (resolved 2026-11-03, `sim/oidbind.py`):**
- **A single `modify` creates a new oid but its response is only `{"status":"ok"}`.** Every later fill or cancel then references an unknown oid. This was most of the gap.
- Trigger orders (`waitingForTrigger`) get their oid at placement but it is not returned either.
- **Fix:** oids come from one global counter in execution order (verified: 100% increasing on GOOGL). An unknown-oid action's new oid therefore lies strictly between its neighbouring known oids. A later reference by the same user to an oid inside that bracket is bound to it; ties are broken by client order id, then by price and side.
- **Accuracy, checked against client order ids:**
  - unique bracket: 99.7%, 2,616 checkable;
  - client-order-id tie-break: 100%;
  - still ambiguous: 2,160 oids, but only $0.24M of fills all day (mostly cancels).

**Coverage after binding:**

| | Maker | Taker |
|---|---|---|
| All day | 99.81% | 99.75% |
| Crash, 20:01:50–20:05 | 98.99% | 98.62% |

The rest is orders resting since before 00:02 (1.0% maker / 1.4% taker in the crash); 0.02% is unexplained. Extending the extract back into Oct 27 would cover the pre-window orders.

**Mark:**
- The real liquidation mark is always within [min(m1, m2), max(m1, m2)] (101/101 liquidation blocks), consistent with median(m1, m2, book).
- During the crash **m1 = m2 = oracle** (319.31 → 311.43 in 0.5% steps), while the relayer's own `externalPerpPxs` already showed 306.7 → 305.8. The mark was therefore set by the relayer alone: the book component could not move the median.
- The external price fed into the relayer tracked the book; the clamp is applied after it.

**State actions:** GOOGL had 10,727 `updateLeverage` and 637 `updateIsolatedMargin` actions; 971 of them by accounts that were later liquidated. The whale had none, so its 2% margin gap comes from funding or fees.

## Phase 1 results (2026-11-03): GOOGL book and mark, Oct 28 00:02 → 24:00

Code is in `sim/`:
- `book.py`: order-level book, integer px/sz, price-time, self-trade = expire maker.
- `replay_book.py`: block replay and all the checks.
- `oidbind.py`: unknown-oid binding.
- `mark_check.py`.

**Rules found in the data (none of them are in the docs):**
1. **In-block order:** within a bundle, orders run first (proposer order), then cancels and other non-order actions. Evidence: 213,903 cancelByCloid successes that hit an order placed later in the same bundle.
2. **Single `modify` and trigger orders get a new oid that the response does not return.** It is bound from the global oid counter, using modify chains as references and assigning oids in increasing execution order per user. Accuracy 100% where a cloid allows checking.
3. **`modify` failing with "Error placing new order during modify" still cancels the original.**
4. **Orders with no status were never placed:** "Action already expired", or batch entries after an error.
5. **Self-trade prevention expires the resting maker**, also when it is reached by the taker's leftover size.
6. **Match-time cancels:** a GTC whose real fills stop short of the book had its remainder cancelled (15.7k/day, probably margin). Makers a taker passes over stay live (their later cancels succeed).
7. **Mark = median(m1, m2, median(best bid, best ask, last trade)), computed when the relayer `setOracle` executes**, with the non-order actions after the bundle's orders. **Liquidations only fire in a block that has a relayer update** (97% of liquidation marks reproduced vs 2% otherwise), i.e. margin is re-checked every ~3s.

**Baseline replay** (tape-guided user takers, engine takers injected from the fills, evidence pruning):
- Pruning means an accepted post-only order or a rejection's bid/offer echo removes orders that cannot have existed. 4,189 orders were pruned all day (0.12% of resting orders), all logged.
- Results:

| Check | All day | 18:00–22:00 |
|---|---|---|
| Echoed bid/offer exact | 99.0% | 98.5% |
| 1-min book: best price | 99.5% | |
| 1-min book: top-5 prices | 98.7% | |
| 1-min book: top-5 prices and sizes exact | 94.5% | |
| Cancel outcomes | 99.7% | |
| Real makers found in the book | 98.3% | |
| User-taker size reproduced to the exact maker | 97.4% | 97.2% |

**Pure price-time engine** (what counterfactuals will use), 18:00–22:00:
- 86% of user-taker size matches the exact maker; 19% of simulated size has no real counterpart.
- 94% of filled sizes are right.
- The gap is the match-time skips and cancels (rule 6). Model them from account state in Phase 2.

**Mark:** 98/101 liquidation marks reproduced exactly; the 3 misses are 0.01–0.10 off.

## Phase 2a results (2026-11-03): GOOGL account state and liquidation triggers

The frozen Phase 1 replay is in `replay_v1/` (read-only, SHA256SUMS; data on S3 under `backstop/replay_v1/`).

Code: `sim/ledger.py` (funding and liquidation ledger from `misc_events_by_block`), `sim/clearinghouse.py`.

**Sources:**
- 00:02 snapshot. Isolated margin is solved from the liquidation price.
- Fills tape: all fills, including liquidation rounds and backstop transfers.
- Hourly funding (amount < 0 = paid, applied to isolated margin).
- `updateIsolatedMargin` (`ntli` in micro-USD) and `updateLeverage`.
- **Ground truth:** the ledger `liquidation` record of every backstop takeover (account value, size, leverage type).

**Accounting rules, chosen by fit to the 137 scorable isolated takeovers:**

| Rule | Choice | Evidence |
|---|---|---|
| Fill fees | paid from isolated margin | share within 1bp of notional: 61% vs 28% without |
| Adds | post notional at fill price / leverage | |
| Liquidation rounds | keep margin (margin += realized PnL) | |
| Voluntary reduce | **superseded in Phase 2b, see "Margin release on reduce" below** | |
| `updateLeverage` on an open isolated position | no measurable effect | |

**Results:**
- Position size at takeover: exact for 137/137.
- Account value at takeover: median error $0.00, 86% within $1, 61% within 1bp of notional.
- **The whale is +$6.6k (0.12% of its $5.55M notional), unexplained and flagged.** Forward from the snapshot gives $597.1k of margin at 20:02:37; the ledger anchor implies $590.4k.
- **Liquidation triggers:** isolated equity < MM at the mark computed at each relayer update (Phase 1 rule 7).
  - Of the 608 accounts both real and simulated, **94.2% trigger in the same block** and 95.4% within one update.
  - Book-first vs backstop-first agrees 99.8%.
  - 64 real liquidations are never triggered in the sim, and 9 sim triggers never happened. Likely cause: positions opened after the snapshot with an inferred margin mode or leverage.

**Next (Phase 2b):** one integrated engine (book + clearinghouse + liquidation orders + backstop vault):
- liquidation rounds (20% / 30s cooldown / full) sent as orders into the simulated book;
- takeover at ⅔·MM;
- vault unwind (replayed in the baseline, a policy in counterfactuals);
- validated on the whale's exact sequence and the vault's −$183k.

## Phase 2b results (2026-11-03): integrated liquidation engine (Rust `engine sim`)

The engine runs the book, the accounts and the liquidation engine in one block loop.
- Real liquidation fills of engine-handled accounts (isolated, margin known) are not injected; the engine generates them.
- Cross and unknown accounts keep their real liquidation fills, interleaved by address.
- The vault inherits the engine's takeovers; its unwind is replayed from the tape.

**Liquidation rules found in the data:**
1. **Liquidations run at the relayer update's position in the block**, with the new mark. Orders later in the block are not in the book yet: the whale's round 2 never met a 7,892-share bid placed later in its block.
2. **Within a block, accounts are liquidated in ascending address order** (Spearman 1.0 across all 58 multi-account blocks, from the liquidation orders' oids).
3. **A liquidation order has no price band.** It fills while the account's equity stays at or above ⅔·MM of the remaining position (at the mark) and stops at the level where the next fill would cross.
   - Evidence: the whale ended round 2 $9 above ⅔·MM.
   - Partial rounds in the same block stop at different prices, one per account; no fixed percentage of mark, oracle or external price fits.
4. Partial first round = 20% for positions above $100k notional, then full-size orders during the 30s cooldown. Takeover below ⅔·MM at px = entry − margin/size (trader ends at 0).
5. Liquidation fee ≈ 0.56 bp of notional (from the tape).
6. **Triggered stop / take-profit orders fire on the same mark update and run before the liquidations.**
   - Takeovers matched: 80 → 116; missed: 54 → 18.
   - Running them after the liquidations or at the end of the block gives no gain.

**Validation (GOOGL):**

| Whale | Real | Sim |
|---|---|---|
| Round 1 | 6,522.532 | 6,522.533 (same block) |
| Round 2 filled | 8,269.6 | 9,201.8 (same block) |
| Takeover | 17,820.5 @ 307.773 | 16,888.4 @ 307.7735 (same block) |

The whale's round-2 excess is about the size its +$7.4k margin offset allows.

**All accounts (after rule 6):**
- Takeovers: **116 in both, 98.3% in the same block**, size within 5% for 72% (median size error 1.5%), median price error 0.11 bp.
- 18 real-only, totalling $23.7k of notional (0.4%): small margin-reconstruction errors (later or no trigger) and slightly deeper same-block fills. 5 sim-only.
- Takeover notional: $5.49M sim vs $5.75M real.
- Whale: round 1 exact; round 2 9,087 vs 8,270; takeover 17,003 vs 17,820 at 307.7735 vs 307.773.
- Market rounds: 622 accounts in both; first round in the same block for 92.4%, same number of rounds for 90.4%, same total filled for 76.4%.

**Open:**
- Fix the whale's margin offset.
- Explain the 54 real-only takeovers.
- A vault unwind policy (needed for counterfactuals; today the unwind is replayed).
- Make maker accounts follow the engine's fills (full endogeneity).

### Margin release on reduce (2026-11-03, fixes the whale's offset)

On any reduce of an isolated position, realized PnL goes to the isolated margin, then this amount is released to cross:

> **max(0, margin + (fill px − entry) × position) × reduced size / position size**

When the equity at the fill price is positive, this equals margin × remaining / original (the PnL is netted out of the release). When it is negative, nothing is released.
- Fitted on the 15 rule-sensitive accounts: every single-partial-reduce account matches to cents (e.g. $7.14 vs $7.14, $32.26 vs $32.34; $0 for the two with negative equity).
- Liquidation rounds follow the same rule (their equity at the fill price is negative, so nothing is released).

| | Before | After |
|---|---|---|
| Takeover equity within $1 | 85% | **93%** |
| p90 error | $4.75 | **$0.35** |
| Whale equity error | +$6,634 | **−$1,159** (0.02% of notional) |
| Never-triggered liquidations | 64 | 37 |

**Integrated sim after the fix:**
- Whale: round 1 6,522.533 vs 6,522.532; round 2 8,193.5 vs 8,269.6; takeover 17,896.7 @ 307.7735 vs 17,820.5 @ 307.773, all in the same blocks.
- Takeovers: 126 in both, 98.4% same block, 11 real-only, 6 sim-only.
- Takeover notional $5.78M vs $5.75M.

### Vault unwind policy (2026-11-03)

The vault's orders are not in the command stream; they are rebuilt from the 3,723 vault fills (1,783 orders).

**Policy:**
- One taker IOC per relayer update (gap median 3,006 ms, p10–p90 2.9–3.1 s).
- Size **0.5% of current inventory** (median 0.5007%), with HL's $10 minimum order value.
- Hits the best bid (median 0 bp from it); no tight price limit (deepest fill −151 bp vs mark); fills fully.
- Fee 0.90 bp of notional.

Engine: `VAULT=policy` (default; `VAULT_FRAC`, `VAULT_LIMIT`, `VAULT_EVERY`, `VAULT_MIN_NTL`) or `VAULT=replay`. The vault also inherits the real takeovers of accounts the engine does not simulate (cross / unknown).

**Validation (GOOGL):**

| Minutes after first takeover | 2 | 5 | 10 | 20 | 30 | 60 |
|---|---|---|---|---|---|---|
| Real, share unwound | 18% | 39% | 63% | 86% | 95% | 100% |
| Sim, share unwound | 19% | 40% | 63% | 87% | 95% | 100% |

- Last fill at +91 min (real +89); 1,834 orders (real 1,783).
- Inherited $7.19M (real $7.16M).
- **Vault PnL −$180.6k (real −$183.0k, −1.3%)**; fees $628 (real $628).

### Endogenous makers (2026-11-03)

`ENDO=1` (default in `engine sim`): every account's position comes from the simulator's own fills, through a fill bus carrying both counterparties. Fill sources:
- user takers (tape-guided, or pure engine);
- engine liquidation rounds;
- replayed liquidation rounds of cross accounts;
- triggered stops and other injected engine takers;
- the vault's unwind.

Fees use each user's own maker and taker rates from the tape (global 1.11 bp taker, 0.15 bp maker). The tape's fill rows are ignored; only position transfers (takeovers of accounts the engine does not simulate) are still replayed.

**Check: every account's end-of-day position vs the next-day snapshot** (Oct 29 00:09, rolled back to midnight with the 3,626 fills in between):

| Mode | Accounts | Exact | Error (share of gross position) |
|---|---|---|---|
| Tape-driven makers (`ENDO=0`) | 3,962 | 98.3% | 0.43% |
| **Endogenous (`ENDO=1`, 128,932 bus fills)** | 4,003 | 94.7% | 0.66% |

Of the endogenous error, 0.52 points come from the 168 accounts that traded with, or were, the engine's own liquidations. That is by design: engine liquidation orders take liquidity by price-time in the simulated book, not the real makers. Every other account is off by 0.14%.

Liquidation results are unchanged: takeovers 123 in both, 98.4% same block; whale identical; vault PnL −$180.4k (real −$183.0k).

## Readiness gate: parameter-exact closed loop (user directive, 2026-11-03)

The replay must be parametrizable, and **with the real parameters it must reproduce the real data exactly.** Only then are other parameters tested.

Users' own actions (orders, cancels, margin, leverage) stay replayed as sent; they are the scenario input. Every protocol mechanism must be computed by the engine. Each crutch that still uses real outcomes is replaced by its mechanism, with a counter of residual tape use:

| Crutch today | Mechanism | Gate at real params |
|---|---|---|
| Relayer components m1/m2 replayed | Recompute from `externalPerpPxs`: clamp ±50 bps/update, 150s EMA of (mid − oracle); params `clamp_bps`, `ema_tau`, which components are clamped | m1, m2, mark exact at every update |
| User takers follow the real makers (`tape_walk`) | Pure price-time + HL match-time margin checks (skip / cancel makers without margin) | every fill exact (taker, maker, px, sz); today 86% |
| Evidence pruning from real BBO echoes | none (unneeded once the book is exact) | 0 pruned |
| Triggered stops injected | Trigger on mark crossing triggerPx, then a market order | same trigger blocks and fills — **done (GOOGL): 727/731 same block, parity exact** |
| TWAP slices injected | HL TWAP slicer | same slices |
| Cross-account liquidations / takeovers replayed | Cross and unified margin accounts, same liquidation engine | same rounds and takeovers |
| Vault unwind | done: policy, 0.5% of inventory per update | vault PnL exact |

**Parameters:**
- MM buffer b (with schedule, transition policy, trader response);
- backstop fraction;
- partial threshold, fraction and cooldown;
- liquidation equity stop;
- mark (clamp width, clamped components, EMA tau, median rule);
- vault policy.

**Order:** relayer → triggers → match-time margin → cross accounts → TWAP.

### Relayer reconstruction (in progress, GOOGL 2026-10-28)

trade.xyz docs (read 2026-11-03):
- US equities use external prices 24/5, including pre- and post-market; overnight comes from BOATS.
- Internal pricing (EMA of impact prices, τ 30 min, Δt* = min(Δt, 0.1τ)) applies only Fri 8 PM – Sun 8:05 PM ET and on holidays.
- Relayer updates are clamped to ±50 bps "of the current value".
- Mark = median(oracle, oracle + 150s EMA(mid − oracle), median(bid, ask, last)).

What the data shows:
- **Oracle target = `externalPerpPxs`**: the oracle equals it on 99.4% of updates and converges to it after the crash.
- **Clamp reference = the oracle the relayer last saw on-chain, lagging 1–3 updates.** `oracle_n = clamp(ext_n, S[n−k] · (1 ± 50 bp))` explains **22/22** crash updates, including the 0 bp and +3 bp steps (e.g. 327.49 × 0.995 = 325.85 vs 325.86).
- The read lag k_n is timing, not design: infer it once from the data, hold it fixed across scenarios.
- **Clamp edges are rounded inward** (lower edge up, upper edge down) on HL's price grid (5 significant figures, at most 6 − szDecimals decimals). With the read lags inferred in prep, this reproduces **24/24** clamped updates in 18:00–22:00 and m1 on **4,798/4,798** updates.
- **Component 2 = clamp(ext + e, same band as the oracle)**, with e = EMA_τ(mid − **ext**), τ = 150 s. The EMA tracks the unclamped external price, not the oracle: that is why m2 = m1 at every clamped crash update, and why m2 is back above the oracle right after the crash (20:03:01: oracle 305.27, m2 305.88). With (mid − oracle) the EMA would have been dragged ~2 below.
- The mid is sampled every 500 ms, and samples since the last update are netted against the ext of the update being published. Sampling at 100–500 ms is equivalent; τ is sharp (120 s: 67%, 150 s: 74%, 180 s: 69% exact).
- **The relayer sees the book with the same read lag as the oracle**: as of (k − 1) updates back. During the crash k = 2–3, so its mid was older and higher than ours. Within one tick goes from 96.6% to 98.0%, and big misses from 162 to 95.
- The 00:02–00:10 UTC updates (8 PM ET switch to overnight) follow another regime: ext is frozen and the oracle drifts one tick at a time. The relayer simulation therefore starts at w0 − 15 min, seeded from the real m2 − ext.

**Engine: `MARK_SOURCE=simulate`** (`engine/src/relayer.rs`; params `CLAMP_BPS` 50, `CLAMP_M2` 1, `EMA_TAU` 150, `EMA_P` 500, `RELAYER_WARMUP_S` 900).

**Residual term** (`RELAYER_RESID_OUT` / `RELAYER_RESID_IN`). The relayer's private view of the book drifts ±1 tick from ours, so a baseline run at real parameters writes one value per update:
- r_n = (real m2 − ext) − e_n where the real m2 is strictly inside the rounded band;
- on a band edge, the smallest r that lands on the same edge (0 if the plain simulation already does);
- NaN (applied as 0) where the real m2 is outside the band;
- plus a lag override where the real m2 reveals the read lag.

Scenario runs add r_n at each update, never carried over to the next. Each mode needs its own baseline file (`data/prep_<COIN>_<day>/relayer_resid_{tape_walk,engine,sim0,sim1}.txt`), because e depends on the book that mode builds.

GOOGL, scored 18:00–22:00:

| | replayed relayer | simulated | simulated + residual |
|---|---|---|---|
| m1 exact | — | 100.0% | 100.0% |
| m2 exact / within 1 tick | — | 77.5% / 98.0% | **99.98% / 99.98%** (4,797/4,798) |
| mark exact (same book component) | — | 88.4% | 99.98% |
| liquidation marks reproduced | 98/101 | 94/101 | 98/101 |
| takeovers, both (ENDO 0 / 1) | 126 / 123 | 126 / 123 | 126 / 123 |
| vault PnL (ENDO 0 / 1) | −$180,642 / −$180,435 | −$180,694 / −$180,438 | **−$180,642 / −$180,435** |

- **The one unexplained update is 24278 (20:15:25).** The ext jumps +47 bp and the real m2 (299.78) sits above the ±50 bp band of every recent oracle (edge 299.63). The mark is unaffected.
- **Residuals are small:** |r| median 0.003, p99 0.07.
- **Two are large: +4.3 at 20:01:58 and +9.5 at 20:02:01, the crash onset.** There the real m2 stayed at oracle + 0.2 while ext had already fallen $6–11. The rule does not capture this; the residual keeps it as it was.
- Scenario effect: with no clamp, vault PnL is −$169k with residuals vs −$159k without. The difference comes from those two updates.

**INTC / AMZN (2026-10-29): two rules the GOOGL crash never exercised.**

| | GOOGL | INTC | AMZN |
|---|---|---|---|
| Before: m1 exact (plain) | 100% | 98.65% | 99.15% |
| Before: same-block takeovers, simulated relayer + residual | 99.3% | 76.6% | 45.0% |
| After: m1 exact (plain) | 100% | **100%** | **99.98%** (1 update) |
| After: mark exact with residual, ENDO=0 and ENDO=1 | **100%** | **100%** | **100%** |
| After: takeovers and vault PnL | = real-mark run | = real-mark run | = real-mark run |

1. **External-price cap = trade.xyz's documented *discovery bound*** (docs.trade.xyz, perpetuals/mechanics/discovery-bounds: the mark stays within ±(1/max leverage) of the live external price in external sessions, 24/7). In internal (weekend / holiday) sessions it re-anchors up to the market's reset count (GOOGL / AMZN 2, INTC 1); that part is not modelled yet, since our three days are external sessions. Fitted behaviour: The oracle and m2 both stay within d = 1 / maxLeverage of ext, rounded toward ext, and the cap overrides the 50 bp clamp.
   - INTC (10x) published exactly ext × 1.1000 and AMZN (20x) ext × 1.0500 for ~25 updates at 20:01. Ext had run more than d ahead of the clamped chain, and the oracle then moved up to 116 bp in one update.
   - GOOGL's gap never reached 5%.
   - prep's read-lag search knew neither the cap nor exact grid rounding. It found no lag at the crash onset and fell back to k = 1, and one wrong step carried a constant offset (+4.6 bp / −17 bp) through a 40-minute descent.
   - The rule now lives in `sim/relayer_lag.py` (prep loads it; it also re-infers an existing prep's lags in place). `ORACLE_CAP` (fraction) is the scenario knob; 0 disables the cap.
2. **m2's band is the hull of two bands:** the one around the lagged oracle and the one around m2's own lagged value. Every real m2 of the three coins in 18:00–22:00 lies in it (14,396 / 14,396), while 47 lie outside the oracle band alone. On INTC m2 ran 12 ticks below the oracle's lower edge through the descent, so the residual could not be observed there (421 misses). `M2_REF=oracle` restores the old band.

Residual files are kept with each prep: `data/prep_*/relayer_resid_endo{0,1}.txt`. The plain m2 model (EMA of mid − ext) is weaker on INTC: m2 exact 37.6% vs 77.8% on GOOGL and 73.9% on AMZN, within one tick 72.6%. Scenarios therefore lean on the residual there.

**After the gate:**
- Phase 3, mechanisms: b schedules and mark designs on all events plus injected shocks.
- Phase 4, attacks: an attacker-agent API and a book-recovery model. Scenarios: wick-to-liquidate, EMA holding, a thin external feed, backstop extraction with offsetting accounts, dynamic-b gaming, relayer timing.
- Combined output: a frontier of vault loss vs trader cost, subject to no profitable attack up to a budget.

## 8. Build order

1. **Phase 0 (data, EC2):** extract xyz-only actions and `setOracle` for Oct 28 00:00 → Oct 29 23:59 from `replica_cmds` into parquet (per block: actions + resps). Check coverage: every real xyz fill is explained by an order in the stream.
2. **Phase 1 (book + mark):** order-level book rebuild + matching for one coin (GOOGL). Validation steps 1–2.
3. **Phase 2 (clearinghouse + liquidations + vault):** validation steps 3–5 on GOOGL, then INTC and AMZN.
4. **Phase 3 (parameters + views):** the parameter interface, the standard charts, and the first counterfactuals (MM buffer b, clamp width).
5. **Phase 4:** extend to the July–Sep events; add response models.

### Pure matching (in progress, GOOGL 2026-10-28)

Goal: user takers matched by price-time priority on the simulated book (no real fill lists) and still reproduce the
real fills. Diagnostic `PM_DIAG=<csv>` runs a dry pure match before each tape-walked taker and compares it with the
real fills **maker by maker**. Within a taker, real fills ordered by `trade_id` are not in matching order.

**1. In-block execution order, corrected.** Per bundle: post-only (Alo) placements, then cancels (by oid / cloid), then everything else (other orders, scheduleCancel, relayer updates) in action order.
- Evidence: a taker never fills a maker that is cancelled in the same bundle, before or after. Post-only echoes show the book before that bundle's cancels.
- Relayer updates in action order with the rest: putting them earlier drops liquidation marks to 89–90 / 101.
- This replaces Phase 1's orders-first. Phase 1's "hl" test, and the first retest here, were invalid: giving post-only and other orders different priorities inside the single orders stream breaks the merge's sorted-stream assumption.
- prep now writes post-only orders as their own stream (`events_4`). `sim/rekey.py` re-keys a prep folder for any ordering spec.

| tape-walk checks (window) | orders-first | post-only → cancels → rest |
|---|---|---|
| echo BBO exact | 98.50% | **99.44%** |
| post-only rejects the sim agrees cross | 99.27% | **99.83%** |
| IOC no-match agreement | 95.53% | **98.37%** |
| liquidation marks reproduced | 98/101 | **100/101** |
| pure-match exact user takers | 99,056 / 113,138 | **105,197** |

Sim parity unchanged: 126 takeovers, vault −$180,642.

**2. HL's silent cancels.**
- HL cancels resting orders without a command (margin at match time, reduce-only, ...). The order-status stream that would show it is in neither the HL bucket nor hydromancer.
- Evidence: a market maker's later cloid cancels **fail** ("never placed, already canceled, or filled"), and its vanished quotes are never cancelled.
- `sim/silent.py` recovers them from a PM_DIAG run, iterated to convergence. A maker is treated as cancelled right before the taker that reveals it when:
  - pure matching would take it, and
  - the real taker skipped it, and
  - it is never filled, modified or successfully cancelled again (or its next cancel fails).
- Result: `silent_cancels.arrow`, 5,301 cancels on GOOGL; the engine reads it with `SILENT=1`. It is a property of the real day: like users' own cancels, it is replayed as given.
- **L2 veto** (2026-11-03). Some "never referenced again" orders were still resting: L2 top-5 exact had slipped 2,721 → 2,693.
  - Rule: the engine records each silent removal (side, px, size, block). At every 1-min L2 snapshot, a top-5 level that holds more than our book by exactly one removed order's size (or all of that level's removed orders) vetoes those removals. Output: `VETO_OUT`, accumulated in `silent_vetoes.csv`.
  - `silent.py` then only lets such an order be cancelled by a taker after the vetoing snapshot.
  - Result: 50 vetoes, converged after 4 passes; about 4,000 silent cancels. Tape-walk L2 top-5 exact **2,731** (above the 2,721 without any silent cancel); echo mismatches about 650; pure-match exact takers 108,468 / 113,140.
  - Outcome metrics unchanged: engine-mode real size matched 97.34%, sim vault −$181,309.

**Results, GOOGL:**
- Tape-walk pure-match check: 107,883 / 113,138 takers exact (95.4%), 85.5% of real size in exactly-matched takers.
- **Engine mode (pure matching end to end):**

| | before | new ordering | + silent cancels |
|---|---|---|---|
| real size matched, all day | 89.4% | 95.2% | **96.6%** |
| sim extra, all day | 14.5% | 6.2% | **4.1%** |
| real size matched, 18:00–22:00 | 86.2% | 93.9% | **95.6%** |

**Left, by size** (tape-walk diagnostic):
- reduce-only takers filling more than the position allows (133 takers, 31.7k sim vs 3.0k real): needs positions from the clearing;
- other takers filling more (1,559 takers, 20.9k sim vs 10.0k real): taker margin at match time;
- takers with the right total but other makers (3,387, 42k): remaining phantoms and priority;
- reduce-only makers capped by position;
- 256 real makers missing from the book (4.5k).

Triggers in engine mode overfill (43k vs 21k real) for the same reduce-only reason.

**3. Match-time caps** (2026-11-03). They need positions: the replay now keeps a **shadow position per user**, seeded from the snapshot and moved by every fill path (user takers, triggers, injected takers, vault unwind, the clearing's liquidation fills via `Clearing::book_fills`, backstop takeovers). prep carries the reduce-only flag (`ro`) on every order.
- **Reduce-only taker:** fills at most its position, on the reducing side; rejected when there is nothing to reduce.
- **Reduce-only maker:** fills at most its position. Cancelled at match when it would not reduce (HL `reduceOnlyCanceled`).
- **Triggered orders run smallest first:** 839 / 839 ordered pairs, from real fills of triggers firing at the same update (oid order 41%, trigger price 62%, address 53%). The whale's 37,577-share stop ran after 21 smaller ones, which took the best bids.
- **An isolated account's taker order never fills beyond the account's bankruptcy price** e − m/q. With the proportional margin release, that price is invariant under reduces.
  - The whale's stop stopped at 305.77, its bankruptcy price 305.79, although bids at 305.71 and below were resting and the next liquidations took them.
  - No price band (taker fills reach 4.8% from the mark), no notional cap ($10.4M orders) and no sweep cap (8% sweeps) explain it otherwise.
  - Only 5 of 668 fired market triggers fill short of their expected size.
  - Applied to IOC and market orders, including market triggers, in pure matching with the clearing.
- `MATCH=engine` makes the `sim` command use pure matching.

**Results, pure matching, GOOGL:**
- **Replay, engine mode** (shadow positions, no clearing): real size matched **97.2%**, sim extra 2.95% (window 96.4% / 3.7%); liquidation marks 100/101.
- **Full sim**, `MATCH=engine TRIGGERS=simulate SILENT=1`:

| | tape-walk sim | pure matching, ENDO=0 | pure matching, ENDO=1 | real |
|---|---|---|---|---|
| takeovers, both / sim-only / real-only | 126 / 6 / 11 | **134 / 6 / 3** | 128 / 10 / 7 | |
| trigger taker size (window) | (walked) | 20.3k | 20.3k | 21.3k |
| whale round 1 / round 2 / takeover | 6,522.5 / 8,188 / 17,902 | **6,522.5** / 8,160 / 17,931 | 6,513 / 8,154 / 17,898 | 6,522.5 / 8,270 / 17,821 |
| vault PnL | −$180,642 | **−$181,376** | −$179,434 | −$183.0k |
| end-of-day positions exact | 94.6% (ENDO=1) | 98.3% (replayed) | 85.7% | |

**4. Post-midnight fills and initial margin** (2026-11-03).
- **Data bug:** the GOOGL tape runs to 00:09:49 on Oct 29 (8,267 blocks), but prep read fills from the Oct 28 file only, so every taker after midnight looked unfilled. prep now adds the next day's fills up to the tape's last block. The next-day snapshot is at that block, so no roll-back is needed.
- Effect: user-taker fills 109,252 → 110,878; pure-match exact takers 108,500 / 113,140 (95.9%). Silent cancels drop to 3,919 (part were artifacts). End-of-day positions exact 98.3% → 99.0% (replayed) and 85.7% → 88.1% (ENDO=1).
- **Initial margin at match time is small on GOOGL:** 84 opening orders stop early with liquidity left (≈4,300 shares, 0.5% of real size; one account ≈4,000). 40 of them (1,202 shares) are around the crash, mostly dip buyers.
- Free collateral is not observable from one asset, so `sim/margin.py` takes the binding cap from the real outcome, **in notional** (margin = notional / leverage). The same dollar cap then holds at counterfactual prices.
- Result: 53 caps, $3.5M (`margin_caps.arrow`, `MARGIN=1`). Engine-mode real size matched 97.32%, sim extra 2.65%. ENDO=1 end-of-day error 0.82%. Pure-matching sim vault −$181,308 (ENDO=0) / −$180,097 (ENDO=1) vs −$183.0k real; takeovers 134 / 6 / 3 (ENDO=0).

**5. Cross accounts** (2026-11-03).
- **Size on GOOGL:** 18 of 171 takeovers are cross accounts, $311k of $7.16M (4%). All held a single xyz position at liquidation.
- **Rule:** a cross account with at most one xyz position at the snapshot, and no fills in other xyz coins during the tape, is margined like an isolated account. Collateral cm = account_value − (mark₀ − e)·q from the snapshot (prep: `acc_init.cm`; `CROSS=0` turns it off).
  - Cross semantics in `fill()`: opening adds no margin, realized PnL stays in the collateral, nothing is released, going flat keeps the collateral; funding goes to the collateral.
  - These accounts join the liquidation engine and the bankruptcy limit on takers.
- **Validation:** 174 of 1,308 cross accounts qualify. The 5 real cross takeovers among them ($61k) reach takeover with simulated equity equal to the ledger account value **to the cent**.
- **Sim, pure matching, ENDO=0:** takeovers 139 / 7 / 3 (both / sim-only / real-only; was 134 / 6 / 3); market-round accounts 666 (was 639); vault −$181,617 (real −$183.0k). ENDO=1: 134 / 9 / 6, −$181,219.
- **Not covered: 13 cross takeovers, $254k.**
  - Rotators traded other xyz coins earlier, so their account value carries other coins' PnL.
  - New accounts were absent from the snapshot.
  - Most xyz cross accounts are in **unified** mode (13.7k of 15.7k), where spot USDC backs every perp dex. The misc ledger shows these users moving USDC within spot (`send`, `spotTransfer`, with `sourceDex` / `destinationDex`), not into xyz directly.
  - Their collateral is spot balance + positions on every dex, which needs a multi-dex, spot-aware account reconstruction (all fills of all dexes, spot balances, transfers). Until then their liquidations stay replayed.

**6. Multi-dex cross / unified collateral** (2026-11-03; `sim/crossacc.py`).
- **Data:** hydromancer `global` snapshots (account values per user and dex, positions on all dexes, spot balances) at the tape's first and last block, global fills (perps on all dexes + spot), and the node's misc ledger (USDC transfers, funding on all coins). Requester-pays, about $0.13 for Oct 28–29.
- **Account value, fitted on the 18 real cross liquidations** (ledger `accountValue`): 16 within $1, 14 to the cent.
  - **Account value** = trading cash + Σ q·mark over cross positions − isolated equity.
  - **Trading cash** = snapshot account value − Σ q₀·mark₀; it changes by −buy / +sell notional, fees, funding and USDC transfers. The order-independent identity avoids entry prices: fills within a block are not in `trade_id` order.
  - **Which positions count:** unified and new accounts count every dex; standard accounts count xyz only.
  - **Isolated equity** = margin (from the snapshot liquidation price; plus notional / leverage on increases; isolated-only assets at max leverage) + unrealized PnL.
  - **Snapshot account values are equity,** isolated equity included.
- **Into the sim:** everything except GOOGL becomes an exogenous collateral path X(t) per account. The clearing's cross bookkeeping already handles GOOGL itself (m − e·q evolves like cash), so it starts the account at m = x₀ + e₀·q₀ and applies X's changes block by block (`acc_x.arrow`, `acc_xev.arrow`).
  - X updates at each fill on other coins, transfer and funding payment, and every minute while other positions are open.
  - Other coins' marks: for xyz coins, median(m1, m2, last trade) from every relayer update; for other dexes, the last trade.
- **Validation against the next snapshot** (taken at the tape's last block): an account is margined only if its reconstructed end value matches within max($1, 0.2%).
  - With the snapshot's own end marks, idle accounts match to 3–4 cents, which confirms flows and funding.
  - **1,939 of 2,898 accounts validate (median error $0.07).**
- **Left out** (replayed): accounts isolated on GOOGL by any evidence (either snapshot, the liquidation ledger, leverage or isolated-margin actions; a margin mode set on an earlier day persists unseen), portfolio-margin accounts (margined portfolio-wide; per-dex values can be negative), accounts with non-USDC spot exposure (spot collateral rule not modelled: a new account carried a $310k GOOGL long on spot tokens), and 34 market makers with more than 20k fills.
  - Two bugs found on the way: portfolio-margin and isolated-on-GOOGL accounts had validated on meaningless numbers. Without these exclusions the sim produced 132 false takeovers and a −$4.25M vault.
- **Result, GOOGL:** 16 of the 18 real cross takeovers are simulated, 15 within $1 of the ledger.
  - Pure-matching sim, ENDO=0: takeovers 150 / 14 / 3 (both / sim-only / real-only), vault **−$182,362** (real −$183.0k).
  - ENDO=1: 144 / 23 / 6, −$181,709.
  - Sim-only takeovers: 12 cross ($8k notional) and 6 isolated ($17.5k).
- Peak memory: crossacc.py 2.7 GB, engine < 0.5 GB with 2.5M collateral changes.

**7. Spot collateral, other positions' MM, portfolio margin** (2026-11-03).
- **Spot (HL docs, account abstraction modes):** in unified mode each asset's balance backs only cross positions margined in that asset, so only USDC backs xyz; other spot tokens are not collateral.
  - The account that looked "spot-backed" had no `account_values` row and had started from $0. Such accounts now start from their **spot USDC balance**.
  - Spot trades against USDC are USDC flows. The spot exclusion is removed.
- **Other positions' maintenance margin:** HL's unified ratio sums cross MM over all dexes per collateral token. crossacc.py now tracks the MM of each account's other cross positions (`mmo0`, `dmm`). The clearing tests R = MM(GOOGL) + MM(other), in the trigger, the takeover threshold (⅔·R) and the liquidation equity stop.
- **Portfolio margin (HL docs):**
  - Liquidatable when PMR = (20 + Σ cross MM) / liquidation value > 0.95.
  - Liquidation value counts HYPE / UBTC collateral at liquidation thresholds 0.825 / 0.75 (0.5 + 0.5·LTV) and USDT0 at 1.
  - Per account, LV₀ is calibrated on the snapshot `pm_ratio` (LV₀ = (20 + MM₀)/pm_ratio₀). LV then moves with flows, perp PnL, spot trades and collateral prices, and is validated on the next snapshot's `pm_ratio` (within 0.02 or 10%).
  - The clearing applies R = (MM + mmo)/0.95 + 20/0.95.
  - PM perp positions do go through market liquidation on xyz (148 fills on Oct 28, e.g. a $175k GOOGL round). The docs' PM backstop (`0xbbb…b`) never traded that day.
- **Validation:** 2,699 of 2,898 accounts. Unified 2,361 / 2,433, new 108 / 123, standard 162 / 210, portfolio margin 68 / 132. Accounts that fail are replayed.
- **Sim, pure matching:** ENDO=0: takeovers 150 / 15 / 3, market-round accounts 716, vault −$181,734. ENDO=1: 144 / 25 / 6, −$182,345 (real −$183.0k). 16 / 18 real cross takeovers simulated, 15 within $1.

**8. Position drift with simulated makers** (ENDO=1 end-of-day exact 87.9% under pure matching vs 94.2% under tape-walk).
- **Maker volume** differs by ~28k shares in both modes. That comes from the vault's unwind policy: replaying the real vault trades lifts tape-walk to 96.8% but pure matching only to 88.2%.
- **Pure-matching drift** comes from taker fill sizes (4.6k under / 3.8k over, ~0.9% of real taker size) and maker identity (2.7% of size goes to other makers).
  - Reduce-only takers fill less where the simulated position has already drifted: a legitimate feedback.
- **Every mechanism reduces drift.** Removing reduce-only caps: 87.1% exact and error 1.71%. Removing the bankruptcy limit: 86.4% and a −$303k vault. Removing margin caps or silent cancels: errors 1.19%.
- **The main unexplained residual is 1,388 same-price priority exceptions** (185 between orders of the same user). HL fills a newer order (always newer by oid) before an older live order at the same price, and the older one fills later (median 3 blocks), at the same price.
  - Ruled out: repricing, reduce-only (18% of cases), maker margin (opening share 43% vs 41%), nonce order (46%).

**9. Same-price priority exceptions** (2026-11-03; `QUEUE_DIAG=<csv>` with `PM_DIAG`). At every level a real taker only partly consumes, our queue (insertion order) is compared with which orders really filled:
- **FIFO prefix in 90% of levels** (19,724); clean suffix 1,074; other 1,095, mostly a skipped head (`.F`, `.F.`).
- Of 4,591 skipped-ahead / filled-behind pairs:
  - ~960 skipped makers are reduce-only (pure matching caps them by position);
  - 624 are pre-tape seeded orders;
  - **2,722 are genuine exceptions**: the filled order is newer (always by oid) or from the same block. The skipped one is live and fills later at the same price (median 3 blocks).
- **Ruled out:** repricing, missed modifies (by oid or cloid: 32 of 2,258), oid order, client nonce (46%), size fit (the filled order is fully consumed in only 9.5%), the maker's GOOGL direction (opening 43% vs 41%), open-interest caps (OI-increasing fills 276 vs 261).
- **Not concentrated in one account:** 87 accounts at skip rates of 7–29%. The top ones are standard-mode market makers with $79k–$207k of xyz account value, quoting 50–124 coins with 60k–220k fills a day: exactly the heavy accounts crossacc.py leaves out.
- **Account-wide margin: rejected.** The xyz accounts of the 8 top-skipped market makers were rebuilt from 454k xyz fills, xyz funding, and sends into / out of the xyz dex.
  - **Rebuild is accurate:** end values match the next snapshot within 0.1–0.4% (e.g. −$593 on $150k).
  - **No difference between skips and fills:** at skips and at fills alike, margin used is a median 8.3% of account value, free margin is ~$147k vs ~$150k, and no fill ever needed more margin than was free.
- **Status:** the exceptions are characterized (≈2.7k makers, concentrated in high-frequency market-maker quotes, no account-state signal) but no deterministic rule was found in the data. They stay a known residual of pure matching. Resolving them likely needs HL's matching source or confirmation from the team.

**Still to do:**
- the same-price priority exceptions (no rule found; margin, OI caps, modifies, nonce, size fit ruled out); portfolio-margin accounts that do not validate (64);
- the ENDO=1 position drift under pure matching.
- (INTC / AMZN: done, see "INTC / AMZN validation".)

### Trigger orders (TP/SL), `TRIGGERS=simulate` (GOOGL 2026-10-28)

**Rule found:**
- A trigger fires at the **first relayer update whose mark crosses triggerPx**, before that update's liquidations: buy tp / sell sl when mark ≤ triggerPx, sell tp / buy sl when mark ≥ triggerPx.
  - 687 / 694 fired triggers fire exactly there.
  - Other prices fit far worse: oracle 316, m2 491, last trade 407, mid 286.
- It then runs as an order of its own: IOC at the user's limit price when `isMarket`, GTC otherwise. Limit triggers rest and fill later as makers.
- Size 0 = the whole position (`positionTpsl` and close-all orders). Reduce-only triggers are capped at the position and dropped when there is nothing to reduce. Real HL shows no fill and no cancel for those 234 cases either.
- **`normalTpsl` children** (`waitingForFill`) activate when their parent fills, by any path: tape, matching, liquidation, vault unwind. The engine's book logs every maker fill for this.
  - They follow the parent through a modify: the 100-share SL at 20:02:40 belonged to a parent modified into a new oid.
  - They are dropped when the parent is cancelled, or when a modify fails and cancels it.
- `scheduleCancel` also cancels triggers. Cancels by oid or cloid apply to the trigger book.

**oid binding fixes** (`sim/oidbind.py`):
- **Sibling rule:** sub-orders of one action take consecutive oids in j order, true for 99.5% of actions with ≥ 2 known oids. This binds 413 oids from a known sibling.
- **Trigger tie-break:** in a TP/SL pair, the child whose trigger condition held at the oracle when it filled. Compared at ms resolution: fills are stamped at the block's ms, so the same block's relayer update counts.
- 32 GOOGL oids changed, all TP/SL pairs that had gone to the wrong child (`ambiguous_first`).
- **INTC / AMZN binds and preps must be rerun with this version.**

**Prep:** trigger rows carry triggerPx (`e_bid`), flags (`e_ask`: isMarket, tp, reduceOnly, grouping, waitingForFill) and parent oid (`x`). Real trigger-taker fills go to `trig_fills.arrow`, which tape-walk follows once the engine fires the trigger.

**Gate, GOOGL:**

| | all day | 18:00–22:00 |
|---|---|---|
| real triggers that fired as taker | 731 | 626 |
| fired in the same block in the sim | **727** | **623** |
| fired in another block (1–2 updates late; one 24 min late) | 4 | 3 |
| real-only (never fired in the sim) | 0 | 0 |
| sim-only | 576 | 384 |

- The sim-only firings are benign:
  - 234 reduce-only drops;
  - about 250 limit triggers that rest (56 of them have real maker fills; 190 leave no trace);
  - 81 market triggers with no real fill.
- Book checks with simulated triggers are unchanged or better: cancel-status mismatches 1,366 → 701, echoes and L2 the same, +22 pruned.
- **Sim parity is exact**, alone and combined with the simulated relayer + residual (residual rebuilt with triggers simulated: `relayer_resid_sim{0,1}_trig.txt`): vault PnL −$180,642 / −$180,435, takeovers 126 / 123.
- **Scenario effect:** triggers now react to the counterfactual mark (198 window triggers fire in another block under a wider clamp). Vault PnL with simulated triggers vs replayed: 100 bp −$185.6k (vs −$206.9k), 200 bp −$179.1k (−$202.3k), no clamp −$145.5k (−$169.4k).
- **Limitation:** a moved trigger still walks its real fill list (the tape-walk crutch). That ends with the next gate item, pure matching with match-time margin.

### INTC / AMZN validation, and two fixes (2026-11-03)

Full pipeline rerun on INTC and AMZN (Oct 29, earnings close): oidbind, prep, silent cancels, L2 vetoes, margin caps, crossacc. The two coins found two engine errors, both fixed and now default.

**1. Isolated opening margin at a gap (`iso_open=mark`, default; `iso_open=off` restores notional / leverage).**
- **Symptom:** on INTC the sim took over market maker 0x79366057 (−1,437 shares) at 20:02 while HL did not. The position matched reality exactly; the isolated margin did not.
- **Cause:** during the crash the book traded ~7% under the lagging mark. A short opened at $80.38 against an $86.90 mark is under water at once. The engine moved only notional / leverage into isolated margin, which left the account below 2/3 MM on its first update.
- **Rule (fitted):** HL also moves the opened size's loss at the mark: margin += sz·px/lev + max(0, side·(px − mark)·sz).
- **Alternatives tested:**
  - oracle as reference: worse fit;
  - top up the whole position to IM: wrong (vault −$9.8k);
  - only the loss beyond the position's surplus over IM ("slack"): tied with the chosen rule.
- **End-of-day isolated margins vs the next snapshot (|Δ| < $1):**

  | | without rule | with rule |
  |---|---|---|
  | INTC | 983 / 1,129 | 988 / 1,131 |
  | GOOGL | 1,508 / 1,668 | 1,536 / 1,670 |
  | AMZN | 588 / 623 | 605 / 626 |

  Accounts where the sim under-margins fall from 117 to 11 (GOOGL) and from 34 to 2 (AMZN).

**2. Trigger modify by cloid.**
- **Symptom:** AMZN ENDO=1 took over $3.81M (real $1.55M). One bot (0x821ac5e0, about $28k of collateral) ended −8,470 shares short in the sim. In reality it never held more than 48.
- **Cause:** the bot places pairs of ~1,000-share limit triggers with a cloid, batch-modifies them by cloid, then cancels them by cloid (all 666 cancels succeed). The trigger book handled modifies by oid only. The original trigger stayed live and fired ~300 blocks after the real cancel.
- **Fix:** a modify by cloid now replaces the trigger the cloid points at.
- **Also tested and left off:** an initial-margin check of triggered orders against modelled free collateral (`TRIG_IM=1`). It also rejected 9 AMZN triggers that did fill: unified accounts with ~$300 opened $38k shorts through triggered market orders. HL evidently does not apply a plain IM check there.

**Results at real parameters** (MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1; ENDO=0 replays the real vault unwind on INTC/AMZN, GOOGL uses the policy):

| | GOOGL Oct 28 | INTC Oct 29 | AMZN Oct 29 |
|---|---|---|---|
| real vault PnL | −$183.0k | −$100.7k | −$48.4k |
| sim ENDO=0 vault | −$181.9k | **−$100.9k** (was −$66.7k) | −$52.5k |
| sim ENDO=1 vault (policy unwind) | −$181.7k | −$97.6k | **−$47.9k** |
| takeovers ENDO=0: both / sim-only / real-only | 150 / 9 / 3 (was 15 sim-only) | 256 / 8 / 5 (was 17) | 398 / 6 / 1 (was 16) |
| same block | 99.3% | 97.7% | 97.2% |
| takeover notional ENDO=0, sim vs real | $6.11M / $6.06M | $2.29M / $2.25M | $1.61M / $1.55M |
| takeover notional ENDO=1, sim vs real | $6.13M / $6.06M | $2.30M / $2.25M | **$1.71M** (was $3.81M) / $1.55M |
| end-of-day positions exact, ENDO=0 / ENDO=1 | 95.4% / 88.0% | 95.2% / 86.5% | 96.5% / 84.7% |

**3. Liquidation and vault sizes on the size grid (`lot_round`, default; `lot_round=0` = µ-units), 2026-11-04.**
- **Rule:** HL floors the partial round size (20% of the position) to the coin's lot. Of the partial rounds that filled their whole 20%, 10 match only the floored size and none only the nearest. The equity-stop cap is floored to the lot, and the vault's policy order floors its 0.5% and rounds the $10 minimum up.
- **Before:** the engine liquidated sub-lot sizes, e.g. 14,820.0357 GOOGL shares vs 14,792.144 real.

| ENDO=0 (real unwind) | GOOGL | INTC | AMZN |
|---|---|---|---|
| Market-liquidated in both, same total filled | 76.1% → **80.6%** | 50.7% → **68.8%** | 23.1% → **37.8%** |
| Takeover size within 5% | 87.3% → **90.0%** | 86.7% → **92.2%** | 97.2% → **98.0%** |
| Takeover same block | 99.3% | 97.7% → **98.4%** | 97.2% → **97.5%** |
| Vault PnL | −$182,334 | −$100,868 | −$52,547 |

- **Vault PnL** moves less than $10. ENDO=1: −$181,665 / −$97,618 / −$47,903.
- **What remains:** the sim liquidates slightly more than HL. Of the mismatched accounts, 123 / 141 / 284 fill more and 16 / 28 / 20 fill less, often with extra rounds (53 / 50 / 130 accounts).
- **Size:** excluding the top 3 accounts per coin, the excess is 34 / 58 / 13 shares, against 31.7k / 50.2k / 3.6k shares liquidated by HL. The big ones are INTC u3016 (2,801 vs 1,157), GOOGL u3924 (179 vs 99) and accounts whose real round stopped after a few lots.
- **Likely causes:** the equity stop, or margin released on reduce, is slightly looser than HL's. Not investigated further.

**4. Cross accounts: other coins at block resolution, joint liquidation (crossacc.py), 2026-11-04.**
- **Case:** HL liquidated AMZN 0x05cc5c9c (AMZN 188 + GOOGL 137 cross, $5.1k USDC) on both coins at 13:32:28.689. With every relayer update, equity first falls below the summed MM at exactly that update ($2,123 vs $2,125). The sim missed it and took the account over 40 minutes later, after a real withdrawal.
- **Four fixes:**
  1. Other xyz coins are marked at every relayer update: median(m1, m2, exact last trade before the update). This reproduces HL's GOOGL liquidation mark (283.24).
  2. Marks no longer look ahead. The minute mark used to be the last price *of* the minute.
  3. X is re-evaluated at every relayer update while the account is within `CROSS_DANGER` (default 2) × its MM, otherwise every minute. Cost: 2.6–4.8M collateral changes (was 2.0–3.6M), crossacc peak 2.7–3.6 GB.
  4. Another coin's liquidation fills enter X one block later, after the relayer update of the same ms. HL liquidates the whole account at once, so this coin must be tested against the state before them.
- Validation is unchanged: 2,699 / 2,898, 1,266 / 1,412, 1,127 / 1,249.

| ENDO=0, real unwind | GOOGL | INTC | AMZN |
|---|---|---|---|
| Takeovers: sim-only / real-only | 9 / 3 → **7 / 3** | 8 / 5 → **6 / 4** | 6 / 1 → **4 / 0** |
| Takeover notional, sim vs real | $6.11M / $6.06M | $2.29M / $2.25M | **$1.55M / $1.55M** |
| Vault PnL (real) | −$182.3k (−$183.0k) | −$102.4k (−$100.7k) | **−$51.2k** (−$48.4k) |
| ENDO=1 vault | −$181.6k | −$98.5k | −$49.9k |

- **AMZN:** 0x05cc5c9c is now market-liquidated in the same block for its full 188.126 shares, as on HL.
- **INTC:** the vault moved *away* from reality ($1.5k) for a good reason. The real takeover of 0xea3ce3e9, previously missed, is now reproduced; the miss had been offsetting the sim-only takeover of 0xa38f19c4 (−$3.3k, maker reallocation, R2). 0xef23b47d's takeover size went from 246 to 133 shares (real 133).
- **Relayer:** the residual files were regenerated, and parity holds in all six configurations.

**5. Validation tolerance scaled to this coin's margin (crossacc.py, `CROSS_TOL_MM`, default 0.25), 2026-11-04.**
- **Rule:** an account validates when its end-of-day error is within max($1, min(0.2% of its value, 0.25 × the peak MM of its position in this coin)).
- **Why:** before, a $2.8M account could pass with a $681 error against $490 of AMZN MM (0x4b8600a7, two false takeovers).
- **Validated:** GOOGL 2,699 → 2,665, INTC 1,266 → 1,244, AMZN 1,127 → 1,078. The newly rejected accounts are replayed; none had a real takeover, so the real takeover notional of modelled accounts is unchanged ($6.06M / $2.25M / $1.55M).
- **Tighter is worse:** at 10% of MM, $1.6–3.0M of peak notional per coin would drop out.
- **Results:** GOOGL and INTC takeovers and vault are unchanged. AMZN ENDO=0: sim-only takeovers 4 → 3, vault −$51.2k → **−$48.1k (real −$48.4k)**; ENDO=1 −$46.5k.
- **Relayer:** residuals regenerated; parity holds in all six configurations.
- **Memory:** GOOGL crossacc peaked at 5.1 GB once (3.6 GB the run before), under the 6 GB guard. Keep running it alone.

**6. Other coins' margin mode and isolated transfers (crossacc.py), 2026-11-04.** The end-of-day validation cannot see either, because account value includes isolated equity.
- **xyz coins:** successful `updateLeverage` actions from the state table switch the coin's mode. An open cross position moved to isolated takes |q| × mark / leverage out of the cross collateral, and `updateIsolatedMargin` moves ntli between the two. That is 142k / 64k / 108k actions on GOOGL / INTC / AMZN days.
  - Case: AMZN 0xd8e37894 had switched GOOGL to isolated and topped it up. The sim left ~$7k of locked margin in its cross collateral and never liquidated it; HL took it over at 20:01:16.
  - Now the sim takes over 40.78 shares (real 40.28), one relayer update before HL.
- **Other dexes** (no action log in the extract): a position reopened from flat takes the mode and leverage the next snapshot shows for it.
  - Case: GOOGL 0x8b2d0bd7 reopened SOL isolated at 10x. Margined at the snapshot's 1x, it locked $2.0k instead of $0.2k, and the sim took over its GOOGL position at 03:20. Now there is no takeover.
- Cross entry prices are now tracked too, for a later switch to isolated.

| ENDO=0, real unwind | GOOGL | INTC | AMZN |
|---|---|---|---|
| Takeovers: both / sim-only / real-only | 150 / 6 / 3 | 258 / 6 / 3 | 400 / 3 / 0 |
| Vault PnL (real) | −$180.9k (−$183.0k) | −$103.0k (−$100.7k) | **−$48.5k** (−$48.4k) |
| Of the gap, the one R2 account | 0x4dbda869 +$1.2k of +$1.95k | 0xa38f19c4 −$3.3k of −$2.5k | — |

- **Vault gaps after this:** apart from the two R2 accounts, every remaining mismatch is under $410 of vault value.
  - GOOGL and INTC moved away from reality: removing false takeovers exposed the R2 errors those takeovers had been offsetting.
- **ENDO=1 vault:** −$180.4k / −$98.8k / −$47.1k.
- **Validated accounts:** 2,666 / 1,244 / 1,079.
- **Relayer:** residuals regenerated; parity holds in all six configurations.
- **Reporting:** the engine's summary "real only" count leaves out engine-handled accounts that were never liquidated in the sim (MISSED_OUT lists them). At the time of the R3b runs it printed 3 / 4 / 0 against 5 / 5 / 3.

**7. Counterparties of real liquidations keep their real fills (R2), 2026-11-04.**
- **Bug:** in ENDO=0 the clearing skipped a real liquidation fill for *any* account it margins, the liquidated side but also the maker on the other side. The simulated rounds credit makers only in ENDO=1, so in ENDO=0 a margined maker of a liquidation simply lost the fill.
- **Why it wasn't visible:** both sides carry the liquidation method, and a market round's direction doesn't say which side was liquidated; only the fill's `is_liquidation` does.
- **Fix:** acc_events now has `liq_side` (prep.py; `sim/liqside.py` adds it to an existing prep after checking row alignment). Only the liquidated side of an engine-handled account is skipped; counterparties take their real fill as an ordinary fill. Real-round statistics count the liquidated side only.

| ENDO=0, real unwind | GOOGL | INTC | AMZN |
|---|---|---|---|
| End-of-day positions exact | 95.6% → **99.6%** | 95.6% → **99.4%** | 97.2% → **99.7%** |
| \|position error\| / gross | 2.48% → **0.12%** | 3.40% → **0.05%** | 1.31% → **0.01%** |
| Takeovers: both / sim-only / real-only | 150 / 5 / 3 | 258 / **0** / 3 | 400 / 3 / 0 |
| Vault PnL (real) | **−$182.6k** (−$183.0k) | **−$99.5k** (−$100.7k) | **−$48.5k** (−$48.4k) |

- **Two accounts now match:** GOOGL 0x4dbda869 and INTC 0xa38f19c4 are no longer taken over.
- **Remaining vault gaps** are diffuse:
  - INTC +$1.4k: mostly takeover sizes (+$536 on 0xbfab6592: 19,165 vs 19,274 shares) and four small missed takeovers.
  - GOOGL −$95 net; its largest piece is 0x046f3cb6, 1.6 shares at a far-off bankruptcy price (−$799, a collateral error).
- **ENDO=1** is unchanged (makers come from the simulated book there).
- **Relayer:** residuals regenerated; parity holds in all six configurations.

**8. Sanity cap on triggered orders (R7, `ORDER_CAP_X`, default 5; 0 = off), 2026-11-04.**
- **Rule:** a triggered order is rejected when its opening notional (beyond what closes the position) exceeds 5 × max leverage × max(the account's xyz value, $1k). The value is the larger of the day's two snapshots, in `acc_av.arrow` (`sim/accav.py`).
- **Calibration:** real trigger fills open at most 26.6x / 3.3x / 8.2x account value (GOOGL / INTC / AMZN). The cap is 100x / 50x / 100x.
- **What it catches:**
  - INTC: 1,378 triggers from 3 accounts, ~$27.6B of buy take-profits at a $10 limit from accounts holding $1.4k, $0 and $0. They would have rested as a phantom bid that any crash scenario would hit.
  - GOOGL and AMZN: none.
- **Safety:** no trigger that filled in reality is rejected.
- **Effect at real parameters:** results are identical, because the bids sat far below the market. Relayer parity holds with the existing residual files.

**10. Maker queue: FIFO with a 399 ms bid window (R5 resolved), 2026-11-04.** Supersedes the "not a queue rule" conclusion of item 9 below.
- **Rule:** at one price makers are FIFO by arrival, and a modify re-queues at the back (it is a new order; the engine already did this). The exception: a new order with a higher priority bid goes ahead of lower-bid orders that arrived **less than 399 ms** before it.
- **Bid ranks:** "na" = {"p": 0} (no bid) < p 1 < p 2 < …
- **GOOGL fit:** every real jump came within 398.8 ms, and FIFO held from 399.1 ms. The earlier failures had two causes: no window, and p 0 ranked below "na" (443 wrong jumps).
- **Code:** `sim/prio.py` writes `prio.arrow` per prep. `PRIO=0` restores plain price-time; `PRIO_WINDOW_MS` sets the window.

| Pure matching, maker by maker | GOOGL (fit) | INTC | AMZN |
|---|---|---|---|
| Exact takers, FIFO → window rule | 95.63% → **97.28%** | 96.99% → **98.08%** | 95.53% → **97.47%** |
| Same-price skips | 2,367 → **878** | 1,084 → **104** | 1,161 → **175** |
| ENDO=1 end-of-day exact | 88.3% → 88.5% | 86.9% → 87.3% | 85.2% → 85.6% |

- **ENDO=0** is unchanged.
- **Relayer:** residuals regenerated; parity holds in all six configurations.
- **GOOGL's 878 remaining skips:** triggered orders the sim fires at another time or size (~220), orders already in the book at the snapshot (176, arrival and bid unknown), same-bid cases (212), and stale bids. In one case a 2,500-share sell placed by a modify crossed bids the sim still held, where HL let it rest.
- **ENDO=1 drift:** it shrinks only slightly, so it is mostly book-state divergence (stale or phantom orders, trigger timing), not queue order.

**11. Trigger sizing and the snapshot-order skips, 2026-11-04.**
- **Triggers (the ~220 GOOGL skips):**
  - All of them are one whole-position trigger, 0x736850ee's take-profit/stop-loss sell at 289.
  - The engine sized it from the book's running position, which matching differences had left 8.056 shares short (4,171.086 vs HL's 4,179.142). The sim's copy ran out before HL's, and HL's last 4 fills went to other makers.
  - **Fix:** in ENDO=0, triggers are now sized and reduce-only-capped from the clearing's replayed position *at the start of the block*. The clearing applies a block's tape fills before its relayer update, so its current position would already include the trigger's own real fill: a first attempt collapsed trigger taker volume to 5.9k of 22.6k shares.
  - ENDO=1 keeps the simulated position. The trigger now fires for exactly 4,179.142.
  - Trigger taker volume, sim vs real: 21.5k / 22.6k, 14.2k / 15.6k, 7.5k / 7.8k shares.
- **Snapshot orders (176 GOOGL skips): a diagnostic counting artifact, not an engine error.**
  - 170 are one pre-snapshot 83.9-share bid at $298 (0x6d976c6a). Through the 20:03 crash the sim gave it 0.052 shares less than HL.
  - At block …2460 HL's taker took the 7.303 shares HL had left, while the sim still had 7.355. The tape walk follows HL's fills, so a 52-lot remainder stayed in the sim's book, and 170 small 52-lot sell IOCs each "dry-matched" it.
  - In engine mode the bid is filled by the same 5 takers as HL (28.85 vs 28.798 shares).
  - The resting-side margin hypothesis is rejected: the owner had used $100k of $229k at 20:03, and the bid filled in full at 20:13.
  - **Diagnostic fix:** the dry match now uses the engine's bankruptcy-price limit for margined accounts' IOC / market takers and market triggers (`diag_px`). The whale's 20:03 stop is now dry-matched to $305.749; HL stopped at $305.77, the engine filled 5,024 vs HL's 4,965 shares. This did not change the counts: the residue, not the stop, drove them.
  - **Count distinct orders, not taker × order pairs.** Same-price residual: GOOGL 214 orders (852 pairs, of which 526 on 9 orders), INTC 84 (103), AMZN 130 (177).
- **Silent-cancel re-iteration** with the current engine (3 passes per coin; still converging): GOOGL 3,700 → 4,116 cancels.
- **Pure matching now:** 97.29 / 98.09 / 97.49% exact takers; same-price skips 852 / 103 / 177.
- **Results:** vault and takeovers unchanged; relayer parity holds in all six configurations.

**9. Priority orders and the ENDO=1 drift (R5), 2026-11-04: explained in part, not fixed.**
- **Finding:** the order table's `grouping` carries `{"p": N}` on HL priority orders (fills carry `priority_gas`; rejections read "Insufficient delegatable balance for priority order").
  - In GOOGL's same-price exceptions the newer order that HL filled first has the higher rank in 1,384 of 1,601 cases, against 10 the other way.
  - Ranking: p 0 < "na" < p 1 < p 2 < …
- **Not a queue rule:**
  - As a persistent queue rank (`PRIO=1`, `sim/prio.py` writes `prio.arrow`), maker-by-maker exactness falls from 95.63% to 94.36%, and ENDO=1 end-of-day exactness from 88.3% to 87.7%.
  - In ~60% of cases a newer higher-rank order does *not* jump.
  - Expiry by age does not separate the cases (the wrong and real jumps have the same age profile).
  - Whatever decides it (plausibly the delegated balance backing the priority) is not in our data. Default off.
- **ENDO=1 drift on GOOGL:** 477 of 4,061 accounts are off, 5,846 shares in total.
  - By account: 251 accounts only through their taker fills (844 sh), 56 only through maker fills (223 sh), 19 only through liquidation / other (457 sh), 151 mixed (4,322 sh).
  - Over the day the sim makes 45.7k shares of maker fills against different orders than HL (~5% of 895k), and the drift cascades from there.
  - Silent cancels hit before their revealing taker (the drifted sim reaches an already-cancelled order earlier) account for only 1.5k of those shares.
- **Priority bids checked against HL docs and barq's logs (2026-11-04):**
  - The rate is p / 10⁸ of filled notional (1 unit = 10⁻⁴ bp), charged to takers only; makers' fills never carry `priority_gas`.
  - Docs: priority grouping is for IOC actions; max 8 bp; higher bids are processed earlier.
  - barq: "within one arrival bucket HL sorts by bid"; its misses are "queue position within the block (orders ahead of us)".
  - On GOOGL, bids above 8 bp (p > 80,000) appear only on IOC takers: 12,316 orders, 605 filled, involved in 7 of the ~2,000 exceptions.
  - The in-block taker order the bids buy is already in our event order: on 68,602 same-block taker pairs whose HL execution order is known (a shared maker's position chain), our order agrees 99.4%.
  - So priority bids explain the takers' queue, not the same-price breaks between *resting* makers, which pay no priority.
- **Status:** the drift stays a known limit of ENDO=1. At real parameters ENDO=1's takeover notional is within 1–5% of real ($6.12M / $2.30M / $1.62M vs $6.06M / $2.25M / $1.55M). ENDO=0 is the primary mode for scenario baselines.

**Left:** full analysis in `RESIDUALS_POSTMORTEM.md`. Its blocking item (the simulated relayer on INTC / AMZN) is fixed; see "Relayer reconstruction".
- AMZN ENDO=0 with the real unwind is $4.1k below reality: it inherits $1.64M against $1.55M real takeovers.
- ENDO=1 sim-only takeovers: 23 / 19 / 14.
- The priority-exception drift.

## Scenarios, grid 1 (2026-11-04): mark clamp and MM buffer

**Runner:** `sim/scen_grid.py` (results in `data/scen/grid1.csv`, runs in `data/scen/runs/`).
- **Mode:** ENDO=0. Users' real orders are replayed open loop (nobody tops up or reacts); liquidations, triggers and the vault are simulated.
- **Relayer:** simulated, with the residual recorded in this same configuration (`relayer_resid_endo0_policy.txt`).
- **Vault:** policy unwind of 0.5% of inventory per relayer update.
- **Baseline check:** each coin's base run reproduces its real-mark policy run to the dollar (−$182,058 / −$98,473 / −$53,091).

| Vault PnL (takeover notional) | GOOGL Oct 28 | INTC Oct 29 | AMZN Oct 29 |
|---|---|---|---|
| **base** (clamp 50 bp, b 0.5) | −$182.1k ($6.05M) | −$98.5k ($2.24M) | −$53.1k ($1.53M) |
| clamp 25 bp | −$246.2k ($9.03M) | −$125.4k ($2.78M) | −$52.8k ($1.53M) |
| clamp 100 bp | −$236.0k ($11.05M) | −$73.1k ($2.52M) | −$52.6k ($1.52M) |
| clamp 200 bp | −$229.4k ($10.95M) | −$32.6k ($0.36M) | −$52.7k ($1.43M) |
| clamp 500 bp | −$208.7k ($8.84M) | −$43.6k ($0.45M) | −$53.6k ($1.49M) |
| b 0.6 | −$202.7k ($7.95M) | −$79.3k ($1.27M) | −$49.7k ($1.37M) |
| b 0.75 | −$158.1k ($4.61M) | −$47.2k ($0.41M) | −$38.8k ($1.02M) |
| b 1.0 | −$168.5k ($5.33M) | −$15.8k ($0.12M) | −$0.0k ($0.09M) |

**Readings:**
- **The clamp is not monotone and depends on the coin.**
  - GOOGL loses more with any change from 50 bp: a wider clamp lets the mark reach the crash faster and hands the vault bigger positions into a thin book ($6M → $11M taken over).
  - INTC loses far less with 200 bp ($0.4M taken over instead of $2.2M): the mark keeps up and the market rounds absorb the liquidations (85k shares vs 53k).
  - AMZN barely moves.
- **A higher buffer cuts vault losses but shifts them to traders as forced liquidation.**
  - Market-liquidated size, base → b 0.75: GOOGL 31k → 47k shares, INTC 53k → 123k, AMZN 4k → 9k.
  - b 0.6 is worse than the base on GOOGL: some takeovers are simply brought forward into a worse book.
- **Switch effect (b 1.0 is not usable as is):** b 1.0 puts MM equal to IM, so accounts at max leverage are liquidatable at once. In the first 15 minutes of the tape it market-liquidates 54.6k (GOOGL), 115.5k (INTC) and 12.0k (AMZN) shares. b ≤ 0.75 has almost no start-of-day effect (≤ 92 shares).

**Limits:**
- Open loop: no top-ups, no maker response, so the b results overstate forced liquidation.
- One day per coin.
- A fixed 0.5% unwind.
- The relayer's view error is kept per update as it was.

## Scenarios, clamp × buffer (2026-11-04)

**Setup:** same runner and setup as grid 1 (`sim/scen_grid.py --set clamp_x_b`); full table in `data/scen/clamp_x_b_full.csv`. b 1.0 is left out (start-of-day switch effect).

**Vault PnL, $k** (rows: clamp; columns: b 0.5 / 0.6 / 0.75):

| clamp | GOOGL | INTC | AMZN | 3-event total |
|---|---|---|---|---|
| 25 bp | −246.2 / −212.6 / −164.7 | −125.4 / −112.6 / −93.3 | −52.8 / −49.6 / −41.6 | −424.4 / −374.8 / −299.6 |
| **50 bp** | **−182.1** / −202.7 / −158.1 | **−98.5** / −79.3 / −47.2 | **−53.1** / −49.7 / −38.8 | **−333.6** / −331.7 / **−244.1** |
| 100 bp | −236.0 / −217.8 / −209.2 | −73.1 / −49.7 / −29.7 | −52.6 / −51.6 / −35.1 | −361.6 / −319.1 / −273.9 |
| 200 bp | −229.4 / −259.7 / −238.4 | −32.6 / −25.6 / −17.2 | −52.7 / −45.5 / −38.9 | −314.7 / −330.9 / −294.5 |
| 500 bp | −208.7 / −255.1 / −237.7 | −43.6 / −19.8 / −57.0 | −53.6 / −46.7 / −40.4 | −305.9 / −321.5 / −335.1 |

**Market-liquidated size vs today** (same layout; GOOGL / INTC / AMZN at b 0.75): ×1.51 / ×2.31 / ×2.30 at 50 bp.

**Readings:**
- **Best over the three events:** 50 bp with b 0.75. Total −$244k against −$334k today (−27%); worst single event −$158k against −$182k.
- **The cost:** forced market liquidation rises 1.5–2.3x, an open-loop upper bound since nobody tops up here.
- **A wider clamp does not combine well with a higher buffer on GOOGL.** At 100–500 bp, b 0.75 still loses $209–238k there.
- **INTC alone would favour a wide clamp at any b:** 200 bp loses $17–33k. AMZN is driven by b only.
- **No clamp setting wins on all three events.** A per-event or regime-dependent clamp (e.g. tied to the gap between external and mark) is the open design question.

## Scenarios, margin tiers on GOOGL (2026-11-04, deployer-controlled)

**Engine:** HL margin tables in the clearing (`tiers=lb:maxLev,…`, ≤ 3 tiers).
- Per tier: MM rate = b / maxLev, IM rate = 1 / maxLev, MM = notional · rate − deduction (continuous).
- This is used in the liquidation trigger, the takeover test, the equity stop and trigger scanning. With one tier it reproduces the previous result exactly (−$182,058).
- **Trader response bound `tier_topup=1`:** margined accounts post the extra tiered initial margin over the base tier, at the start and on each opening fill. Never withdrawn; total reported as the traders' cost.

**Setup:** same as grid 1 (ENDO=0, simulated relayer + policy residual, 0.5% unwind). Results in `data/scen/tiers_googl.csv` (`sim/scen_grid.py --set tiers GOOGL`).

| GOOGL | clamp 50 bp | clamp 200 bp | trader top-ups |
|---|---|---|---|
| today | −$182.1k ($6.05M taken over) | −$229.4k | — |
| b 0.75 (needs HL) | −$158.1k | — | — |
| T1 20x → 10x above $1M, top-up | **−$48.8k** ($0.56M) | −$79.9k | $3.37M |
| T2 + 5x above $5M, top-up | **−$48.7k** ($0.54M) | −$80.2k | $5.26M |
| T3 20x → 10x above $500k → 5x above $2M, top-up | **−$43.4k** ($0.39M) | −$57.2k | $8.89M |
| T1 / T2 / T3, no response | −$184.5k / −$44.2k / −$38.6k | −$225.3k / −$139.7k / −$63.2k | — |

**Readings:**
- **With traders topping up, tiers cut GOOGL's vault loss by 73–76%.** That is far more than the HL-change buffer b 0.75 (−13%), because the margin falls on the one concentrated position (the 0x30afce2f whale, $11M) instead of everyone.
- **The no-response rows are mostly switch effects, not usable:**
  - T3 liquidates the whale in the tape's first minute (37.6k shares);
  - T2 does so an hour in, before the crash;
  - only T1 leaves it to the crash, and then nothing improves (−$184.5k).
  - The real trader response sits between "no response" and "top-up", or is a smaller position, which also helps the vault.
- **A wider clamp still hurts with tiers on GOOGL** (−$57–80k at 200 bp vs −$43–49k at 50 bp). So the "tiers make a faster mark safe" hypothesis is rejected on GOOGL.
- **Cost:** $3.4–8.9M of extra margin, almost all from the whale. Smaller accounts are untouched below $500k–$1M.
- **Still to check:** INTC and AMZN with tables scaled to their books (INTC 10x max); a "reduce instead of top-up" response; and robustness: tiers also cap an attacker's leverage per account, but splitting across accounts escapes them, so they need OI caps or per-entity limits alongside.

## Scenarios, margin tiers on INTC and AMZN (2026-11-04, deployer-controlled)

Same setup as the GOOGL tier runs (ENDO=0, simulated relayer + policy residual, policy unwind; `sim/scen_grid.py --set tiers_intc|tiers_amzn`; results in data/scen/tiers_{intc,amzn}.csv).
Baselines (policy unwind, today's parameters): INTC −$98,473 ($2.24M taken over), AMZN −$53,091 ($1.53M).
Start-of-day switch check: no shares were market-liquidated in the first 15 minutes in any run, so unlike GOOGL the "none" (no trader response) results here are not switch artifacts.

**INTC (10x).** I1 5x above $1M; I2 5x above $500k; I3 5x above $250k, 3x above $1M.

| table | response | 50 bp | 200 bp | top-ups |
|---|---|---|---|---|
| I1 | none | −$67.7k | −$65.9k | – |
| I1 | top-up | −$67.5k | −$32.5k | $3.9M |
| I2 | none | −$87.5k | −$48.7k | – |
| I2 | top-up | −$67.5k | −$32.5k | $5.3M |
| I3 | none | −$68.2k | −$51.2k | – |
| I3 | top-up | −$67.4k | −$32.5k | $11.9M |

- At 50 bp, every table cuts the loss by about 31% (takeovers $2.24M → $0.77M), and the three tables give the same result with top-ups: what matters is that the largest account holds more equity, not which table.
- At 200 bp, tiers with top-ups give −$32.5k, the same as the 200 bp clamp alone (−$32.6k). Tiers add nothing on INTC once the clamp is 200 bp.
- With no response at 200 bp, tiers make things worse than the clamp alone (−$48.7k to −$65.9k), with more market-liquidated shares (88k–208k vs 85k): higher MM forces earlier book liquidations.

**AMZN (20x).** GOOGL's T1–T3, plus T4: 10x above $100k, 5x above $500k. 50 bp.

| table | none | top-up | top-ups |
|---|---|---|---|
| T1 / T2 / T3 | −$53.1k | −$53.1k | $0.13M / $0.13M / $0.36M |
| T4 | −$51.8k | −$50.9k | $1.14M |

- T1–T3 change nothing: no liquidated AMZN account reached the $500k–$1M tier bounds.
- T4 gains only 2–4%. AMZN's loss is spread over small accounts (largest 8%), and size tiers cannot reach it.
- For comparison, b 0.75 (needs Hyperliquid) gives −$38.8k (−27%); the 200 bp clamp alone gives −$52.7k.

**Across the three events.**

| coin | today | best deployer-only | best with HL change (b 0.75) |
|---|---|---|---|
| GOOGL | −$182.1k | −$43.4k (T3 + top-up, 50 bp) | −$158.1k |
| INTC | −$98.5k | −$32.5k (200 bp clamp, tiers optional) | −$47.2k |
| AMZN | −$53.1k | −$50.9k (T4 + top-up) / −$52.7k (200 bp) | −$38.8k |
| total | −$333.7k | −$126.8k (−62%) | −$244.1k |

- The best setting is per asset (tables and the relayer clamp can both be set per asset). Picked after seeing the outcome, so it is an upper bound on what tuning gives.
- Tiers work where the loss is concentrated (GOOGL 89%, INTC 51% from one account) and do nothing on diffuse losses (AMZN).
- The top-up response is an optimistic bound. Tiers apply per account, so splitting a position across accounts escapes them; robustness needs OI caps or per-entity limits as well.

## Scenarios, margin tiers on OI share (2026-11-04)

Engine: `oi_tiers=live|lock|daily` makes the `tiers=` lower bounds shares of open interest (OI = (Σ|q| + |vault q|) / 2, measured at each relayer update).
- `lock`: an account's reference is the 24 h average OI (seeded with the start-of-day OI) at its last increase, kept on reductions. Others' trading cannot move its tier. Needs a Hyperliquid change.
- `daily`: everyone is measured against the start-of-day OI for the whole day. trade.xyz can emulate this by inserting a dollar table each day from that morning's OI.
- `live`: OI now. Reference only, since closing positions raises others' shares (the attack).
Tables ({L} = max leverage): O1 L/2 above 5% of OI, L/4 above 15%; O2 above 2% / 8%. 50 bp clamp, `sim/scen_grid.py --set tiers_oi`, data/scen/tiers_oi.csv.
Regression: base GOOGL −$182,058 and T3 + top-up −$43,417 reproduce exactly.

**Shares of OI (tape).**
- OI was flat until the earnings close, then roughly doubled on all three coins (GOOGL 183k → 374k shares, INTC 377k → 686k, AMZN 47k → 68k).
- GOOGL 0x30afce held 18.9% of OI at its last increase (02:34 UTC) and 17.0% at the crash. INTC 0xbfab6592 held 7.6% at the start and 8.7% at the crash. AMZN's losers each held below 0.1%.
- The largest holders were not liquidated: AMZN 0x46921f69 at 44%, INTC 0x49e96e25 at 29–44%. They appear on several coins, probably market makers.

**Results (vault PnL; top-ups in $M).**

| coin | today | O1 lock + top-up | O1 daily + top-up | O1 live + top-up | O2 lock + top-up | best dollar table |
|---|---|---|---|---|---|---|
| GOOGL | −$182.1k | −$48.7k (1.92) | −$48.7k (2.18) | −$48.7k (1.63) | −$48.7k (5.01) | T3 −$43.4k (8.89), T1 −$48.8k (3.37) |
| INTC | −$98.5k | −$67.5k (4.04) | −$67.5k (4.07) | −$67.5k (3.73) | −$67.5k (7.29) | I1 −$67.5k (3.95) |
| AMZN | −$53.1k | −$53.1k (0.36) | −$53.1k (0.37) | −$53.1k (0.34) | −$53.1k (0.69) | T4 −$50.9k (1.14) |

- Lock, daily and live give the same losses on these events, because OI did not move before the crash. Locking costs nothing here and removes the attack.
- One OI rule for all coins matches the best per-coin dollar tables at 50 bp. On GOOGL it reaches T1's loss with 43% less top-up ($1.92M vs $3.37M).
- No response: O1 GOOGL −$122.8k (the whale is market-liquidated before the crash: 33k shares); O2 GOOGL −$44.2k; O2 INTC −$89.6k. With a lock-at-open rule the tier is known when the position is built, so "no response" is unrealistic. The real alternatives are top-up or a smaller position (not yet modelled).
- AMZN: no change. Diffuse losses are out of reach of any concentration rule.

## Scenarios, tiers with the reduce response (2026-11-04)

`tier_reduce=1`: margined accounts post no extra margin. They hold the largest position whose tiered IM equals the base IM (notional / coin max leverage) of the position they really built. The excess is never opened; start positions are shed at the first update with margin kept. Its tape fills stay, so book flow is unchanged and someone else holds that size. Like top-up, this treats every account as posting exactly the base IM. "Shed" is the peak notional across accounts not held.
Sets tiers_red_oi / tiers_red_googl / tiers_red_intc (50 bp); data/scen/tiers_red_*.csv.

| coin | table | top-up: vault (top-ups) | reduce: vault (size shed) |
|---|---|---|---|
| GOOGL | O1 lock | −$48.7k ($1.9M) | −$48.6k ($14.2M) |
| GOOGL | O2 lock | −$48.7k ($5.0M) | −$48.4k ($24.0M) |
| GOOGL | T1 | −$48.8k ($3.4M) | −$48.6k ($24.2M) |
| GOOGL | T3 | −$43.4k ($8.9M) | −$42.9k ($36.7M) |
| INTC | O1 lock | −$67.5k ($4.0M) | −$67.5k ($13.1M) |
| INTC | O2 lock | −$67.5k ($7.3M) | −$67.4k ($22.1M) |
| INTC | I1 | −$67.5k ($3.9M) | −$67.4k ($15.6M) |
| INTC | I3 | −$67.4k ($11.9M) | −$67.4k ($28.6M) |
| AMZN | O1 / O2 lock | −$53.1k | −$53.1k ($1.8M / $3.4M) |

- The vault result is the same under both responses (within $0.6k). The tier result does not hinge on how traders respond, as long as they respond.
- Daily and lock again match (GOOGL O1 −$48.6k both).
- At equal vault loss, the OI tables cost traders less than the dollar tables: GOOGL O1 sheds $14.2M vs T1 $24.2M; INTC O1 sheds $13.1M vs I1 $15.6M.
- Losses stop at about −$48.6k on GOOGL and −$67.4k on INTC whatever the table. Stricter tables only add trader cost, except T3, which gains $5.7k for 2.6x the shed size. Not decomposed yet into which accounts make up the floor.

## Scenarios, split-whale attack and the liquidation-cluster rule (2026-11-04)

Harness: `sim/split_prep.py SRC ADDR N OUT` builds a prep in which one account is held as N identical accounts: start position, fills, fees and margin moves divided by N, same entry, leverage and liquidation price. The first copy keeps the uid, so the book's orders and triggers stay on it. Used here for GOOGL 0x30afce (isolated 20x, 19,238 shares, ~$6.1M), N = 2 / 5 / 10 (data/prep_GOOGL_1028_split{N}; scen_grid coins GOOGL_s{N}, `--set split`, data/scen/split.csv).

Cluster rule (`cluster=k`, needs a Hyperliquid change): at each increase an account locks the size of its liquidation cluster, i.e. the same-side margined positions (itself included) whose liquidation price at the base MM rate is within k of its own. Its MM and IM are its notional times the cluster's average tiered rate. k = 2%, with the T1 table or the O1 OI table (locked), top-up response.

Vault PnL ($k), top-ups in brackets ($M):

| design | N=1 | N=2 | N=5 | N=10 |
|---|---|---|---|---|
| today | −182.1 | −181.9 | −181.7 | −177.7 |
| T1 per account | −48.8 (3.37) | −48.7 (3.32) | −48.0 (3.17) | −90.0 (2.92) |
| O1 lock per account | −48.7 (1.92) | −48.5 (1.44) | −181.7 (1.13) | −177.7 (1.13) |
| T1 cluster | −36.5 (5.36) | −36.4 (5.36) | −35.9 (5.36) | −34.9 (5.36) |
| O1 lock cluster | −36.9 (3.57) | −36.8 (3.57) | −36.3 (3.57) | −35.1 (3.57) |

- Splitting alone does not change today's outcome (−$178k to −$182k).
- Per-account tiers fail once each piece is below the first bound. T1 ($1M) holds to N=5 ($1.2M each) and fails at N=10 ($0.6M each). O1 (5% of OI) fails at N=5 (the whale's 18.9% / 5 = 3.8%) and is back to today's loss.
- The cluster rule is split-proof: same top-ups at every N, loss −$35k to −$37k. It also beats every per-account table unsplit (−$36.5k vs −$48.8k for T1): accounts liquidating with the whale are margined as part of its cluster.
- Cluster + O1 needs $1.8M less margin than cluster + T1 for the same loss.
- Not yet tested: an attacker inflating a cluster (positions placed at a victim's liquidation price); clusters spread just beyond k (a whale laddering liquidation prices 2%+ apart).

## Mark redesign: the external-anchored band (2026-11-04, deployer-controlled)

HL (setOracle docs): mark = median(markPxs (0-2 values), local book mark = median(bid, ask, last)); moves are clamped to 1% of the previous mark per update. With two inputs a < b the mark is the local mark clamped to [a, b], so the deployer sets the band and the book picks the point inside it.
- Today trade.xyz publishes a = oracle and b = oracle + 150 s EMA(mid − oracle), both clamped 50 bp per update.
- `MARK=band` (relayer.rs) publishes C ± w instead, with C = ext + clamp(EMA_{BAND_TAU}(mid − ext), ±BAND_PMAX) and w = BAND_W. There is no per-update clamp on C beyond HL's 1% (modelled in this mode) and the external-price cap.
- Defaults: w 25 bp, premium cap 50 bp, tau 1800 s. Set `mark_band` (data/scen/mark_band.csv). Today's formula reproduces exactly (−$182,058).

**At the GOOGL release:**
- ext fell 325 → 307 in ~25 s.
- Today's mark stayed near 322 and caught up at 50 bp per update about a minute later.
- The band mark followed in ~1% steps (HL's limit), within seconds.

**Vault PnL:**

| coin | today | band 10 | band 25 | band 50 | today + cluster (O1 lock) | band 25 + cluster |
|---|---|---|---|---|---|---|
| GOOGL | −$182.1k | −$234.2k | −$234.0k | −$234.0k | −$36.9k | −$52.0k |
| INTC | −$98.5k | −$23.8k | −$23.8k | −$17.7k | −$60.6k | −$23.9k |
| AMZN | −$53.1k | −$51.6k | −$51.2k | −$51.5k | −$30.9k | −$22.9k |
| total | −$333.7k | −$309.6k | −$309.0k | −$303.2k | −$128.4k | −$98.7k |

**Liquidation shortfall (corrected).** No market liquidation closes an account below its bankruptcy price in any of these runs. This matches the tape: no auto-deleveraging on GOOGL / INTC / AMZN (there was some on NOW, LITE, MRVL on 10-28 and RDDT on 10-29). A first version counted per fill and double-counted losses that takeovers then pass to the vault through the transfer price; it reported $47k on GOOGL, which was wrong.

**Why the faster mark costs GOOGL and saves INTC.** The vault's loss is inventory taken over × (transfer price − unwind price). Two mechanics set the inventory:
- Book liquidation starts below MM (20% partial above $100k, then 30 s cooldown).
- Takeover comes below 2/3 MM.
So what matters is how long an account stays between the two thresholds, and whether the book still trades above its bankruptcy price meanwhile.

- **GOOGL whale.**
  - Today: two book rounds absorbed 14,820 shares, then the vault took over 17,793 shares at 20:00:37 (transfer 307.77).
  - Band: the 1% steps crossed MM and 2/3 MM on consecutive updates, so one 20% round (7,515 shares) was followed by a takeover of 30,062 shares at 20:00:04 (transfer 305.90).
  - Vault inventory: 19,645 shares (today) vs 35,963 (band). Implied unwind price ~299 in both (the price kept falling to 299 over the next minutes), so the per-share loss was $9.3 vs $6.5 but on 1.83x the shares.
  - The lag gave the book time to absorb the whale above bankruptcy.
- **INTC.**
  - Today's mark ran up to 10% above ext (the discovery cap) for ~25 updates while the price fell. By the time it reached accounts' liquidation prices, the book was far below their bankruptcy prices, so the equity stop blocked book fills and 258 accounts went straight to the vault ($2.24M).
  - Band: liquidations started while the book was still near the mark: 88k shares sold on the book, 24 takeovers ($0.23M).
  - Here the lag removed the book's chance to absorb.
- The mark's speed is therefore not good or bad in itself. Losses fall when book liquidation starts while the book still trades above bankruptcy, and when there is enough time between the book-liquidation trigger and the backstop for the book to absorb. Today's lag gives that time only by accident (GOOGL) and destroys it when the lag exceeds the margin (INTC).
- Band width w barely matters on these events (10 / 25 / 50 bp within $6k), since the external price dominates.
- Best total so far: band 25 + cluster rule (O1 lock, top-up), −$98.7k vs −$333.7k today (−70%).

### Does the takeover premium cover the gap to fair value? (sim/takeover_cover.py)

The vault receives q at the transfer price px (the trader ends at 0). Its cushion at the mark is eq = q (mark − px), and against fair value F (trade.xyz's external price at that update) it starts at q (F − px) = eq + q (F − mark). Covered = ≥ 0.

| run | takeovers | premium at mark | gap mark → fair | net at takeover | underwater takeovers | net 60 s later |
|---|---|---|---|---|---|---|
| GOOGL today | 158 ($6.05M) | +$71.1k | −$111.9k | **−$40.8k** | 153 | −$128.5k |
| GOOGL band 25 | 255 ($11.13M) | +$114.6k | −$14.9k | **+$99.7k** | 12 ($0.8k) | −$148.9k |
| INTC today | 258 ($2.24M) | +$66.3k | −$127.2k | **−$60.9k** | 258 | −$114.1k |
| INTC band 25 | 24 ($0.23M) | +$6.3k | −$0.5k | **+$5.8k** | 20 ($0.3k) | −$4.1k |
| AMZN today | 403 ($1.53M) | +$20.9k | −$71.1k | **−$50.1k** | 399 | −$103.9k |
| AMZN band 25 | 291 ($1.27M) | +$10.5k | −$32.2k | **−$21.8k** | 286 | −$85.2k |

- With today's mark almost every takeover starts underwater: the lag (mark above fair for these longs) is larger than the margin the vault keeps.
- The band removes that on GOOGL and INTC: their takeovers start in profit.
- AMZN is not fixed. ext fell 244.22 → 230.65 in two updates (−166 bp, −396 bp, ~19:51:15 UTC). HL clamps the mark to 1% per update, so even the band mark took ~6 updates to catch up. The median takeover was 255 bp above fair, against a 68 bp cushion. A jump larger than 1% per update cannot be followed by any deployer mark formula. Covering it needs margin ≥ the jump (lower leverage around scheduled events) or an HL change to the 1% clamp (e.g. when externalPerpPx supports the move).
- 60 s later every run is negative: the vault keeps losing while it unwinds into the continuing fall. That is the unwind, a separate lever from the mark.
- **Independent check against Binance's stock perps.** Files: data/binance (GOOGLUSDT 10-28 trades, INTCUSDT / AMZNUSDT 10-29 aggTrades from data.binance.vision, checksums OK, kept as zips plus 100 ms last / VWAP bars). Run as `FAIR=data/binance/{COIN}USDT_100ms.parquet python sim/takeover_cover.py ...`.

  | run | net at takeover vs Binance | underwater | Binance − ext at the takeovers (ntl-weighted) |
  |---|---|---|---|
  | GOOGL today / band | −$28.3k / **+$96.3k** | 154 / 10 | +21 bp / −3 bp |
  | INTC today / band | −$52.5k / **+$4.7k** | 258 / 20 | +38 bp / −54 bp |
  | AMZN today / band | −$48.5k / **−$26.6k** | 399 / 286 | +11 bp / −39 bp |

  Same verdict as against ext: today's takeovers start underwater on all three coins; the band covers GOOGL and INTC, not AMZN. The two fair-value sources differ by at most ~0.5% during the crashes.

## Objectives for takeovers, and the scoreboard (2026-11-04)

The vault's unwind cannot be tested on a replayed book: the book does not react to the vault's selling. So designs are scored on two takeover objectives, set by the user:
1. **Minimise the notional the liquidation vault inherits.**
2. **Maximise the position's value at takeover**: q (F − px) against fair value F, Binance's stock perp at that 100 ms (sim/takeover_score.py).

Constraints to keep alongside: no shortfall pushed to ADL (engine liq_bad_debt = 0), and trader cost (extra margin, earlier liquidation).

| design | class | inherited GOOGL / INTC / AMZN ($M) | total | value at takeover GOOGL / INTC / AMZN | total | underwater takeovers |
|---|---|---|---|---|---|---|
| today | – | 6.05 / 2.24 / 1.53 | 9.82 | −28.3k / −52.5k / −48.5k | −129.3k | 811 |
| clamp 200 bp | deployer | 10.95 / 0.36 / 1.43 | 12.74 | +97.4k / +2.3k / −24.1k | +75.6k | 358 |
| band 25 bp | deployer | 11.13 / 0.23 / 1.27 | 12.63 | +96.3k / +4.7k / −26.6k | +74.3k | 316 |
| MM buffer b 0.75 | HL | 4.61 / 0.41 / 1.02 | 6.04 | −12.5k / −15.8k / −26.2k | −54.5k | 641 |
| O1 OI tiers, lock, top-up | HL | 0.54 / 0.77 / 1.53 | 2.84 | −4.8k / −30.2k / −48.5k | −83.5k | 801 |
| today + cluster (O1 lock) | HL | 0.16 / 0.55 / 1.32 | 2.03 | −1.9k / −25.6k / −36.2k | −63.7k | 673 |
| **band 25 + cluster** | deployer + HL | 0.72 / 0.23 / 0.62 | **1.57** | +1.0k / +4.6k / −10.3k | **−4.7k** | 211 |

- A faster mark (band, or simply a wider clamp) fixes the takeover value but raises the inherited notional on GOOGL: the whale goes to the vault whole instead of partly through the book.
- Margin rules cut the notional but leave takeovers underwater, since they still happen at a lagging mark.
- Together they do both: −84% inherited notional, value at takeover −$129k → −$5k.
- What is left is AMZN: a 5.6% jump in two updates outruns HL's 1% per-update mark clamp.
- Band width does not matter on these events. A 200 bp clamp on today's formula scores about the same as the band.

## Mark from independent venues: median(ext, Binance, book) (2026-11-04, deployer-controlled; REJECTED)

Rejected by trade.xyz: Binance is a competitor and must never be a mark input. Kept for what it shows: anchoring to an external price is what removes the lag. Binance data stays only as a fair-value yardstick for scoring.

`MARK=venues` publishes markPxs = [ext, Binance stock perp] (VENUE_PX, 100 ms bars, read with no latency). HyperCore's own median with the local book then gives mark = median(ext, Binance, book).
- No parameters. The book's room is the venues' disagreement. Moving the mark takes two of the three markets.
- A venue silent > 10 s falls back to ext. The external-price cap and HL's 1% per update are kept.
- `MARK=ext` (markPxs = [ext, ext], mark = ext) is the reference. Set `mark_venues`, data/scen/mark_venues.csv. Binance is now an input, so scores are shown against both fair sources.

| design | inherited ($M) | value at takeover vs Binance | vs ext | underwater (vs Binance) |
|---|---|---|---|---|
| today | 9.82 | −$129.3k | −$151.9k | 811 |
| mark = ext | 12.91 | +$77.3k | +$87.3k | 320 |
| band 25 bp | 12.63 | +$74.3k | +$83.8k | 316 |
| **venues median** | 12.64 | **+$79.2k** | **+$91.0k** | **291** |
| band 25 + cluster | 1.57 | −$4.7k | +$0.5k | 211 |
| **venues + cluster** | 1.72 | **−$1.4k** | **+$4.0k** | **193** |

- Vault PnL (policy unwind, for reference): venues GOOGL −$234.8k, INTC −$28.6k, AMZN −$47.1k; venues + cluster −$52.0k / −$28.6k / −$22.7k.
- The venues median scores at least as well as the band against either fair source, with no tuned parameter. AMZN improves most: −$23.1k vs −$26.6k alone, −$7.3k vs −$10.3k with the cluster rule.
- On these events most of the gain is from anchoring to an external price at all (mark = ext is close). The median's case is robustness, not speed: a book push alone cannot leave [ext, Binance].
- Open:
  - Binance is a perp with its own basis and depth, so moving the mark = moving the xyz book plus Binance's book. That cost has not been measured.
  - Real relayer latency to Binance, outages, and the dependency on a third-party feed.

## Own-book marks out of market hours (2026-11-04, deployer-controlled)

Constraint (trade.xyz): the out-of-hours mark must come from the xyz book, not an external price (the venue aims to lead price discovery outside US hours). Regular hours keep today's formula. Engine: `MARK=own_a|own_b|own_c` with `OWN_FROM_MS` = 16:00 ET (GOOGL 10-28: 1793217600000). Before that the relayer is simulated as today. All three keep the discovery bound (±1/maxLev of ext) and HL's 1% per update. Set `mark_own`.
- **A:** markPxs = [impact mid at $100k (`OWN_N`), time-averaged over the update interval; trade VWAP over 10 s (`OWN_W_S`)] → mark = median(A1, A2, local book).
- **B:** A, but a step may cross at most $1M (`OWN_L0`) of liquidation prices per update (min step 0.1%).
- **C:** A, but when the external price confirms the move, both inputs = the instantaneous impact mid.

GOOGL 10-28:

| mark | inherited | value at takeover vs Binance / vs ext | underwater (Binance / ext) | whale |
|---|---|---|---|---|
| today | $6.05M | −$28.3k / −$40.8k | 154 / 153 | 20:00:37, 17,793 sh @ 307.77, after 2 book rounds (14,820 sh) |
| band 25 (external-anchored) | $11.13M | +$96.3k / +$99.7k | 10 / 12 | 20:00:04, 30,062 sh @ 305.90, 1 round (7,515 sh) |
| **A own book** | $11.13M | **+$96.3k / +$99.7k** | **10 / 12** | same as band |
| B (liquidation-aware) | $9.93M | +$115.8k / +$53.8k | 126 / 137 | 20:00:10, 30,062 sh @ 305.79 |
| C (ext confirmation) | $11.12M | +$96.0k / +$99.4k | 10 / 12 | same as band |

- **The own book alone fixes the takeover value.** A gives the same result as the external-anchored band: the xyz book moved with (or before) the external feed, so no external input is needed for this.
- **C adds nothing.** A already moves as fast as HL's 1% cap allows (2,009 updates confirmed by ext, same outcome).
- **B does what lag does.** It inherits less ($9.93M), but takeovers go underwater again (126–137), and its score swings with the fair source. It is also exploitable by the cluster's owner. Rejected.
- Caveats:
  - The crash began at 19:59:49, 11 s before the 16:00 ET switch, so the first seconds ran on today's regular-hours mark and the own-book mark caught up in 1% steps from 20:00:00.
  - N and W are untuned.
  - The cost to push A (sweeping $100k-impact depth and 10 s of volume) has not been measured yet.
- **Still open: inherited notional** ($11.1M vs $6.05M today). The whale crosses MM and 2/3 MM on consecutive 1% steps, so the book gets one 20% round. That is the margin / liquidation-window side (cluster rule), not the mark.

### Mark-push attack on own-book mark A (GOOGL 10-28, after the close)

Harness: `ATTACK_AT` / `ATTACK_NTL` / `ATTACK_REPEAT` / `ATTACK_SIDE` / `ATTACK_OUT` (replay.rs). A fresh account market-sells the notional into the xyz book at block start, optionally repeated every 3 s. `sim/attack_eval.py` compares each attack with the same run without attacks: slippage cost against the pre-sweep mid, largest mark move in the next 60 s, seconds ≥ 25 bp off, and takeovers added in the next 120 s. Six attacks at 20:30–22:10 UTC ($50k … $2M), single or 5 sweeps over 15 s, under today's mark and under A.

Engine book depth after the close (bids, median over minutes): $2.2M within 25 bp, $4.1M within 50 bp, $6.3M within 100 bp (asks $1.6M / $3.3M / $6.0M). The real l2 snapshots keep only 5 levels, so deeper depth is the replay's.

| attack | slippage cost | mark move, today | mark move, A | A ≥ 25 bp off |
|---|---|---|---|---|
| single $100k / $500k / $2M | $28 / $284 / $1.5k | 0 / 3 / 0 bp | 0.7 / 3.9 / 2.0 bp | – |
| 5 × $100k (15 s) | $153 | 0 | 2.0 bp | – |
| 5 × $500k | $1.8k | 2.8 bp | 4.6 bp | – |
| 5 × $1M | $5.2k | 0 | 1.9 bp | – |
| 5 × $2M ($10M sold) | $46.9k | 0.7 bp | 32.3 bp | 3 s |

- No attack triggered any takeover: nothing sat that close to liquidation at those times.
- Under A, a single sweep of $2M moves the mark by under 4 bp. The replayed book refills within the update interval, and A's time-averaged impact mid and VWAP absorb the spike.
- Holding it costs real money: selling $10M over 15 s bought 32 bp for 3 s at $47k of slippage, plus a $10M short the attacker then has to cover.
- Today's mark barely moves at all: it is tied to the external price. That is the robustness A gives up in exchange for leading price discovery.
- Caveats:
  - Replayed makers do not react. Real makers could widen or pull after a sweep, so the push could go further, or re-quote around the external price faster.
  - Quiet times only, not during the earnings minute when the book is thin.
  - The attacker's cost of covering the position is not counted.

**During the earnings minute** (mark A from 20:00:00; one attack per run so effects do not overlap; vs the same run without attack):

| attack | cost | mark move | ≥ 25 bp off | extra takeovers (120 s) | extra inherited, whole run | value at takeover change (vs Binance) |
|---|---|---|---|---|---|---|
| $250k / $1M at 20:00:02 | $196 / $3.4k | 0.5 / 1.4 bp | – | 0 | ~0 | ~0 |
| $250k / $1M at 20:00:15 | $114 / $2.4k | 1.6 / 2.7 bp | – | 0 | 0 | 0 |
| $250k / $1M at 20:00:45 | $121 / $1.9k | 2.2 / 3.3 bp | – | 0 | 0 | 0 |
| $250k / $1M at 20:02:00 | $402 / $3.6k | 0.3 / 2.3 bp | – | 0 / $4.7k | 0 / $4.7k | 0 / +$148 |
| 5 × $500k from 20:00:15 | $4.5k | 6.6 bp | – | $38.0k | $38.0k | +$152 |
| today's mark, $1M at 20:00:15 | $2.4k | 0 | – | 0 | $10 | 0 |

- Even in the crash minute the push stays within a few bp. The worst case was $2.5M sold over 15 s: 6.6 bp, which tipped $38k of positions into takeover, and those were taken over at a profit to the vault (+$152 vs Binance).
- Vault PnL moved by at most −$1.1k. The book the replay rebuilds in the crash minute is still deep enough to absorb these sizes.
- The main caveat stands: replayed makers do not react to the sweep. Real makers pulling quotes in the crash minute would make a push go further.

## Attack suite on the GOOGL event (2026-11-04)

`sim/attack_suite.py` replays the 10-28 event once per (protocol variant, attack) and compares it with the same variant without the attack. Results are in data/scen/attack_suite.csv; runs, preps and logs in data/scen/attack_runs. `sim/attack_prep.py` adds synthetic attacker accounts (put / washoi / ladder). Engine hooks: ATTACK_AT/NTL/REPEAT (sweep), ATTACK_PULL (makers pull and stop quoting), RELAYER_OUT (outage with HL's 10 s fallback to the local mark), ATTACK_WALL, ATTACK_WASH, CROSS_SHOCK, TRIG_WIN (trigger firings). Control reproduces exactly (−$182,058).

Variants:
- **V0** today's deployed rules (control).
- **V1** own-book mark A from 16:00 ET.
- **V2** V1 + cluster rule (O1 OI tiers locked, 2% band, top-up).
- **V3** V2 with a pre-event leverage cut (tiers from 10x).

Baselines:

| variant | vault PnL | inherited | value at takeover (Binance) | underwater | trader top-ups |
|---|---|---|---|---|---|
| V0 | −$182.1k | $6.05M | −$28.3k | 154 | 0 |
| V1 | −$234.1k | $11.13M | +$96.3k | 10 | 0 |
| V2 | −$52.0k | $0.72M | +$1.0k | 6 | $3.56M |
| V3 | −$31.9k | $0.02M | −$0.4k | 2 | $17.1M |

Attacks (change vs the variant's own baseline; "attacker" = profit at takeover = −(vault's value on X)):

| attack | V0 control | V1 own mark | V2 + cluster | V3 + 10x cut |
|---|---|---|---|---|
| 1 free put $10M (X long 20x at IM, Y short, 19:55) | **attacker +$52.7k**, inherited +$6.1M | attacker −$20.4k, inherited +$8.8M | attacker −$34.8k, inherited +$1.2M | X never liquidated: attack fails |
| 1 free put $2M | attacker +$7.8k, +$0.9M | attacker −$4.0k, +$1.7M | attacker −$4.3k, +$1.9M | fails |
| 2 top maker pulls 60 s + $1M sweep | 0 | 0 | – | – |
| 2 top-5 makers pull ($1.48M of orders) + sweep | 0 | value +$0.1k | 0 | – |
| 3 stop hunt, $1M / 5 × $500k | 0 / 0 | 0 / −$1.1k PnL, no extra stops | – | – |
| 4 starve: top-5 pull 1 s before the whale's first round | **inherited +$0.64M, value −$2.8k, PnL −$15.9k** | value −$5.2k, PnL −$5.7k | 0 | – |
| 6 relayer outage 30 s (± push) | −$55 | ~0 | ~0 | – |
| 7 ladder (whale split 3, liq prices 2.5% apart) | +$91k for the vault (more margin) | – | +$0.9k (escapes nothing) | – |
| 7 wash OI $60M for 1 h (lock a loose tier) | – | – | 0 | – |
| 8 cross shock: all cross accounts lose 10% of other-coin notional ($90.7M collateral) | **PnL −$1.71M, inherited +$29.7M, 797 underwater** | −$1.75M | −$1.44M, +$17.4M | – |
| 9 sell wall $2M / wash $500k per update / both + 5 × $500k sweep | – | 0 / 0 / −$1.1k | 0 / 0 / −$1.1k | – |

- **The free put is the real threat to today's protocol.** It needs no manipulation. $10M of matched positions earned the attacker $52.7k at takeover.
  - The own-book mark turns it into a loss: takeover happens before the price passes X's bankruptcy.
  - The cluster rule cuts what the vault inherits from X.
  - The 10x pre-event cut makes it fail outright, at a high trader cost ($17.1M of extra margin).
  - Vault PnL in V1/V2 is dominated by the untestable unwind of the extra inventory.
- **Starving the book liquidation** hurts the control (whale inventory to the vault). V2 is immune.
- **Book manipulation** (maker pulls, stop hunts, outage, wall, wash) moved nothing material in any variant. The replayed book is deep and maker volume is spread out (top maker 6.6%, top 5 26% in 20:00–20:05).
- **Cross-margin contagion is the largest exposure and no variant fixes it.** The shock was crude: every cross account hit at once, other-coin notional estimated as 40× their MM. It models a broad xyz sell-off, not one thin coin. It still shows GOOGL's liquidations depend heavily on what happens on the other xyz coins. Needs a per-coin model.
- Untested here:
  - 5 (discovery-bound immunity) needs a weekend session.
  - 10 (ADL as a weapon) is not modelled, and no run leaves a shortfall.
  - Replayed makers never react, for every attack.

## Reporting rule: no vault PnL for scenarios (2026-11-04)

The vault's PnL in a scenario depends on how it unwinds, and that cannot be simulated: the policy unwind (0.5% of inventory per relayer update) sells into a replayed book whose makers do not react. Scenario vault PnL figures in this file (grids, tiers, marks, attack suite) are therefore an artefact of that assumption, not a result.

Only the parity runs at real parameters, which replay the real unwind, give a real vault PnL.

Scenarios are reported on:
1. the notional the vault inherits;
2. the position value at takeover, q (fair − transfer price), with fair = Binance or trade.xyz's external price;
3. constraints: liquidation shortfall (ADL), and trader cost (extra margin, size shed).

### Correction: the free put (attack 1) was scored gross

"Attacker profit at takeover" = −(vault's value on X) is the gross value the vault hands over. It leaves out costs that would wipe it out on this book:
- **Entry:** the two legs cross each other, one maker and one taker: ~1.25 bp (median fees taker 1.1 bp, maker 0.15 bp), $1.25k on $10M.
- **Exit:** after X is taken over, the attacker is simply short Y, unhedged. Locking the gain means buying Y back in the crash minute. At 20:00:14 the engine book held $0.57M of asks within 25 bp, $2.4M within 100 bp and $6.7M within 500 bp, so a $10M buy-back costs several hundred bp (far more than the $52.7k gross), and $2M about 50 bp (~$10k vs $7.8k gross).

**Corrected verdict:** the two-account version on xyz alone is not profitable on this event. What stands is the transfer itself: when takeovers happen past the bankruptcy price, the vault pays whoever holds the other side. A variant that hedges or exits on a deeper venue (e.g. the underlying stock) would avoid the exit cost. The own-book mark removes the transfer (takeovers before bankruptcy) and the leverage cut removes the takeover.

### Attack 1 rerun with the attacker's full costs (sim/put_full.py, data/scen/attack_put_full.csv)

- **A (xyz only):** X long at 20x with the minimum margin and Y short, crossed against each other at 19:55 (maker + taker fee). Y is bought back through the replayed book at X's takeover update, sized at the takeover mark. Profit = Y's gain − X's margin − X's top-ups − fees.
- **B (hedged on the stock):** X bought on the xyz book at 19:55 (slippage from the depth dump), hedge short at ext, covered at X's takeover, 2 / 10 / 25 bp per side.

| size | variant | X taken over (s after 16:00) | A: Y buy-back slippage | A profit | B profit (2 / 10 / 25 bp hedge) |
|---|---|---|---|---|---|
| $2M | V0 control | 157.7 | 171 bp | −$18.6k | −$2.1k / −$5.3k / −$11.3k |
| $2M | V1 own mark | 130.8 | 352 bp | −$61.5k | −$20.1k / −$23.3k / −$29.3k |
| $2M | V2 + cluster | 130.8 | 241 bp | −$60.9k | −$20.1k / … |
| $2M | V3 + 10x cut | never | – | −$0.5k (fees) | −$0.5k |
| $10M | V0 control | 157.7 | 822 bp (72% filled) | −$706k | −$181k / −$197k / −$227k |
| $10M | V1 own mark | 130.8 | 893 bp (64%) | −$819k | −$271k / … |
| $10M | V2 + cluster | 142.7 | 824 bp (62%) | −$1.20M (incl. $453k top-ups) | −$607k / … |
| $10M | V3 + 10x cut | never | – | −$2.5k (fees) | −$2.5k |

The free put is not profitable on this event in any variant. Buying back on xyz is ruinous (the crash book is thin), and the hedged version is closest to break-even on the control (−$2.1k at $2M with a 2 bp hedge).
- **Control:** the hedge gains ~5.1% (takeover at 20:02:37) against X's 5% margin. The value the vault transfers roughly equals the costs; a larger or faster gap would make it pay.
- **Own-book mark:** X is taken over earlier (at a 4.2% drop, before its bankruptcy), so the hedge gains less than the margin lost: −$20k. The mark removes the transfer, as the takeover-value objective said.
- Remaining caveats:
  - The 10M buy-backs exhaust the book; the unfilled part is valued at the same price, which is optimistic.
  - The hedge venue's liquidity is assumed.

## Correction: clock times in the scenario sections (2026-11-04)

Several analyses converted times as (ms − first block of the prep) + midnight. The preps start at 00:02:09.4 UTC (GOOGL 10-28) and 00:09:49.3 UTC (INTC / AMZN 10-29), so every clock time quoted from those analyses is early by 2m09s (GOOGL) or 9m49s (INTC / AMZN).
- Examples: the GOOGL whale takeovers "20:00:04" / "20:00:37" UTC are really ~20:02:13 / ~20:02:46 UTC. The AMZN "19:51:15" jump is ~20:01:04 UTC.
- True crash onsets (first update with the external price down ≥ 50 bp): GOOGL 16:01:58.8 ET, INTC 16:01:06.8 ET, AMZN 16:01:03.9 ET. All are in post-market, so the out-of-hours rules (switched on in absolute time at 16:00 ET) covered all three crashes from their start. The "crash began 11 s before the switch" caveat in the own-book mark section is wrong.

Unaffected (absolute times):
- protocol switches (OWN_FROM_MS);
- the free put's entry at 19:55 UTC (6m59s before the GOOGL onset);
- the starve attack (keyed to the whale's real first round);
- all takeover scores.

Affected (the attack fired before the crash, not in it; rerun at onset-relative times):
- the "earnings minute" pushes at 20:00:02–20:00:45 UTC (only the 20:02:00 one was in the crash);
- the attack suite's maker pulls, stop hunts, outage, cross shock, wall and wash (all set at 20:00:00–20:01:10 UTC).

## Trade-based mark ET: median(E, trade price, book) (2026-11-04, deployer-controlled)

`MARK=own_et` from 16:00 ET publishes markPxs = [E, P]. E is trade.xyz's own external price. P is the volume-weighted median of the last `OWN_V` ($1M; also $250k) of voluntary xyz trades no older than `OWN_TMAX_S` (60 s), falling back to E if there are none. Liquidation, backstop and vault fills are excluded, as forced. No book input of our own; HyperCore adds the local book. Set `mark_et` (data/scen/mark_et.csv); GOOGL/INTC/AMZN own_a rerun alongside.

Objectives (fair = Binance; vs ext in brackets):

| mark | inherited GOOGL / INTC / AMZN | value at takeover GOOGL / INTC / AMZN | total value | underwater |
|---|---|---|---|---|
| today | 6.05 / 2.24 / 1.53 | −28.3k / −52.5k / −48.5k | −$129.3k (−$151.9k) | 811 |
| A (impact mid + VWAP) | 11.13 / 0.14 / 1.26 | +96.3k / +3.1k / −26.5k | +$72.8k (+$82.1k) | 293 |
| **ET, V $1M** | 11.25 / 0.14 / 1.25 | +98.8k / +3.1k / −26.5k | **+$75.5k (+$85.9k)** | 297 |
| ET, V $250k | 11.20 / 0.14 / 1.26 | +97.2k / +3.1k / −26.5k | +$73.9k (+$83.2k) | 295 |

ET matches A and the earlier external-anchored designs without any book input. V barely matters for the objectives.

Pushes on GOOGL timed from the true onset C = 16:01:58.8 ET (vs the same mark without attack):

| push | today | A | ET |
|---|---|---|---|
| $1M at C+2 s (cost $8.0k) | 0 bp | 2.8 bp | 0 bp |
| $1M at C+15 s ($10.4–10.7k) | 0 | 19.1 bp | 0 |
| $1M at C+45 s ($1.4k) | 0 | 7.2 bp | 32.0 bp, 3 s |
| 5 × $500k from C+15 s ($8.2–9.8k) | 0 | 19.1 bp | 36.0 bp, 3 s |

No push in any mark added takeovers or changed value at takeover materially (largest: A at C+2 s, −$17.9k inherited).

Quiet times (ET): a single $2M sweep moves it 11.7 bp (A: 2.0), and 5 × $2M 13.1 bp (A: 32.3).

- **What moves ET:** a sweep larger than V/2 prints enough volume to move P, and the sweep moves the local book too. Two of three inputs agree, so the mark follows; that is the design treating real trades as real price.
- **The robustness lever is V.** $1M is small against GOOGL's crash flow ($28.8M of maker volume in 5 min). V scaled to recent voluntary volume (e.g. the median of the last N minutes) would raise the cost with activity.

### ET with the trade window scaled to activity (OWN_VF, OWN_VMIN)

V = max($250k, f × voluntary notional traded in the last 60 s), for f = 0.25 / 0.5 / 1.0 (set `mark_ets`, data/scen/mark_ets.csv). Peak V in the crash: GOOGL $3.5M / $7.1M / $14.2M, INTC $2.7M / $5.3M / $10.6M, AMZN $1.9M / $3.9M / $7.7M.

| f | inherited (3 events) | value at takeover vs Binance (vs ext) | underwater | GOOGL push $1M at C+15 s / $1M at C+45 s / 5 × $500k |
|---|---|---|---|---|
| fixed $1M | $12.64M | +$75.5k (+$85.9k) | 297 | 0 / 32.0 / 36.0 bp |
| 0.25 | $12.89M | +$77.2k (+$89.0k) | 293 | 23.0 / 10.5 / 28.8 bp |
| 0.5 | $12.76M | +$75.1k (+$85.4k) | 296 | 4.9 / 5.9 / 16.8 bp |
| **1.0** | $12.78M | +$75.4k (+$85.6k) | 298 | **0 / 0 / 13.7 bp** |

- **Scaling V costs nothing on the objectives,** even at f = 1.0 (a $14M window in the crash). In a real move the external price and the book move together, so they outvote a slower P; P only has to hold when one of them is pushed alone.
- **The larger window makes pushes much weaker:** 5 × $500k moves the mark 13.7 bp instead of 36, and single $1M sweeps not at all. The attacker's own sweep also counts toward V.
- No push added takeovers or changed value at takeover.
- **Retained rule:** P = the volume-weighted median price of the last minute of voluntary xyz trades (f = 1.0, at least $250k, never older than 60 s), and markPxs = [E, P].

### ET without dollar or age constants (OWN_SELF=1, OWN_H_S)

Over a horizon H: V = max(voluntary volume of the last H, the day's average voluntary volume per H), and P reaches back as far as needed to collect V. No floor, no age limit. H = 30 s (HL's partial-liquidation cooldown, a protocol constant) or 60 s. Set `mark_etsc` (data/scen/mark_etsc.csv). Peak V in the crash: GOOGL $10.3M / $14.2M, INTC $6.2M / $10.6M, AMZN $4.2M / $7.7M.

| ET window | inherited | value at takeover vs Binance (vs ext) | underwater | crash pushes $1M at C+15 / $1M at C+45 / 5 × $500k | quiet, worst (5 × $2M) |
|---|---|---|---|---|---|
| f = 1.0, $250k floor, 60 s age | $12.78M | +$75.4k (+$85.6k) | 298 | 0 / 0 / 13.7 bp | 13.1 bp |
| **self-calibrated, H = 30 s** | $12.76M | +$75.3k (+$85.6k) | 298 | 4.5 / 6.2 / 11.4 bp | 13.1 bp |
| self-calibrated, H = 60 s | $12.78M | +$75.4k (+$85.6k) | 298 | 0 / 0 / 13.7 bp | 13.1 bp |

- Removing the floor and the age limit changes nothing on the objectives or on push resistance.
- No push added takeovers.
- **Retained:** H = 30 s, so the only number in the rule is a Hyperliquid protocol constant.
- **Rule:** P = the volume-weighted median of the most recent voluntary xyz trades, covering at least the larger of the last 30 s of volume and the day's average 30 s of volume; markPxs = [E, P].

### Today's formula without the 50 bp clamp (CLAMP_BPS=100000, HL_CLAMP=1)

`HL_CLAMP=1` adds HyperCore's 1% per-update limit to today's relayer path. It never binds under the 50 bp clamp, so parity is unchanged without it. *(Superseded 2026-11-06: the cap does bind, and it applies to the final mark, not to the relayer's components; see "Parity: HyperCore's 1% cap on the final mark". HL_CLAMP should no longer be set.)*

Removing the clamp all day (regular hours move by at most 0.3 bp) gives, on the three events:

| mark | inherited | value at takeover vs Binance (vs ext) | underwater |
|---|---|---|---|
| today | $9.82M | −$129.3k (−$151.9k) | 811 |
| **today without the clamp** | $12.72M | +$74.7k (+$84.5k) | 320 |
| ET self-calibrated | $12.76M | +$75.3k (+$85.6k) | 298 |

- On these events the 50 bp clamp is the whole lag. Without it, today's formula tracks the drop as fast as ET, and both are limited by HL's 1%.
- The difference is when the inputs disagree. Without the clamp, two of today's three inputs come from E (E, and E + the 150 s premium average), so a bad, frozen or manipulated E moves the mark. Its only own-market input is the book mid, which can be held off-market without trading.
- In ET only one vote is E, and the xyz vote comes from executed trades.

## Bad external print: E off by −5% for 3 s or 30 s (EXT_SPIKE, sim/spike_eval.py)

`EXT_SPIKE="ms;secs;frac"` multiplies the external price the relayer reads; the xyz book and trades replay unchanged. Spikes at 16:10 ET (positions stressed after the crash) and 18:30 ET (quiet), on GOOGL (10-28) and AMZN (10-29), both 20x (discovery bound ±5%). `TRIG_FIRED_OUT` dumps fired triggers.

Marks:
- **today** (50 bp clamp);
- **noclamp** (today without the clamp, HL 1% per update; follows E);
- **et** (ET self-calibrated).

Results vs the same mark without the spike:

| coin | spike | mark move today / noclamp / ET | extra takeovers (120 s) | extra book-liquidated shares | extra stops fired (size) |
|---|---|---|---|---|---|
| GOOGL | 16:10, 3 s | −54 / −99 / −26 bp | 0 / 0 / 0 | 0 / 130 / 0 | 0 / 5 (49) / 0 |
| GOOGL | 16:10, 30 s | −413 / −447 / −35 bp | 0 / $605k / 0 | 7,202 / 5,545 / 0 | 66 (408) / 66 (391) / 0 |
| GOOGL | 18:30, 30 s | −417 / −452 / −43 bp | $88k / $2.21M / 0 | 13,116 / 4,877 / 0 | 147 (9,581) / 165 (11,021) / 1 (0.5) |
| AMZN | 16:10, 3 s | −28 / −47 / −25 bp | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| AMZN | 16:10, 30 s | −394 / −444 / −30 bp | $0.4k / $1.0k / 0 | 177 / 177 / 0.6 | 13 (475) / 12 (475) / 2 (149) |
| AMZN | 18:30, 30 s | −417 / −452 / −36 bp | 0 / $10.5k / 0 | 397 / 452 / 0 | 56 (1,577) / 60 (1,571) / 0 |

- **The 50 bp clamp only protects against a one-update spike.** A 30 s bad print walks today's mark down 50 bp per update to −4.1% (the spike, capped by the bound around the spiked E). It force-liquidated healthy positions on the book (GOOGL 13,116 shares at 18:30) and fired 147 stops, almost as much as without the clamp.
- **Without the clamp,** the same print also sends healthy positions to the vault: GOOGL $2.21M, taken over at prices ~$127k below fair. That is the traders' loss, not the vault's.
- **ET ignores both spikes:** xyz trades and the book outvote E. It moves 25–43 bp, with no takeovers, book liquidations or material stops.
- **The residual 25 bp is the discovery bound leaking the bad print.** The bound is anchored on E, so a −5% E caps the mark at E·0.95·1.05 = −0.25%. A spike larger than 1/maxLev would force ET down to E_spiked × (1 + 1/maxLev). The bound should be anchored on something slower than the instantaneous E (e.g. its own median over a few updates) for ET to be fully immune.

## Design registry and explorer (2026-11-05)

`docs/registry.json` holds the formula terms, every design (as edits to the design it builds on), every test and the open gaps. `docs/explorer.html` embeds a copy and opens from disk.
- Scripts record results with `REG=<test id>` (and `REG_MAP="scenario=design[|case],..."` for takeover_score.py); `sim/registry.py` upserts the test with date, commit and command, and refreshes the embedded copy. It refuses any vault PnL field.
- Recorded by script: score3-binance, score3-ext, split-googl, spike-5pct. Transcribed from this file: push-crash, push-quiet, put-full, attack-suite.
- Spike runs and the control ORC dumps now live in data/scen/spike and data/scen/orc (moved out of the session scratchpad).

## P3: the discovery bound anchored on a median of E (OWN_ANCHOR_N), and prints larger than the band (2026-11-05)

`OWN_ANCHOR_N=N` (own marks) centres the discovery bound on the median of the last N external prices instead of the instantaneous one. Sets `mark_p3` (N = 10, 20); spike runs via `MARKS=p3 ANCHOR_N=N FRAC=… sim/spike_runs.sh`. Today's formula now runs with HL_CLAMP=1 in spike runs (the 1% per update binds once a print exceeds the band).

- **Crashes:** N = 10 identical to P2; N = 20 inherited $12.64M vs $12.76M, value at takeover +$73.8k vs +$75.3k (Binance), 303 vs 298 underwater.
- **−5% print:** N = 10 blocks 3 s prints (0 / −9.7 bp), not 30 s ones (−31 to −46 bp). N = 20 blocks both on GOOGL (0 / −3 / 0 bp); AMZN 16:10 30 s still −29 bp.
- **−20% print (larger than the ±5% band):** today, P1 and P2 all walk −9.4 to −9.6% in 30 s (one 1% step for 3 s). GOOGL 18:30: $5.3M of healthy positions taken over, ~231 stops. P3 N = 10 the same; N = 20 −5.5 to −5.7%, $2.6M.
- **Reading:** the bound centred on E is a shared channel for any print larger than d, whatever the formula. A median anchor protects only against prints shorter than half its window.

## P4: the band follows the feed only while xyz trades agree (OWN_GATE=1), and a stuck feed (EXT_FREEZE) (2026-11-05)

`OWN_GATE=1` (own_et): the discovery bound's centre R_t = E_t while |E_t − P_t| ≤ d·E_t, else R_{t−1}. `EXT_FREEZE="ms;secs"` holds the feed at its last value before ms. Scripts: sim/p4_runs.sh (spikes incl. 5 min), sim/freeze_runs.sh (feed stuck 5 s before onset for 120 s). Set `mark_p4`.

- **Crashes:** identical to P2 on all three; the band was never held (0 updates), nor in the rest of those days' out-of-hours sessions.
- **Bad prints** (−5% / −20%; 3 s, 30 s at 16:10 ET; 30 s, 5 min at 18:30 ET): P4 moves at most 29 bp, no takeovers, book liquidations or extra stops. A 5 min −20% print takes today, P2 and P3 N = 20 to about −16%: $6.9–7.0M of healthy GOOGL positions to the vault, ≈276 stops.
- **Stuck feed at onset** (Binance fair, 3 events): today −$375k value at takeover (990 underwater, $13.94M); P2 = P4 +$66.5k (661, $13.91M); P3 N = 20 +$48.1k (669, $15.16M).

## Normal markets: P4 vs today (OWN_SKIP, sim/normal_runs.sh, sim/normal_eval.py) (2026-11-05)

P4 (and P2) applied in every out-of-hours session (overnight, pre-market, post-market; ≈17 h per coin), regular hours [13:30, 20:00) UTC kept on today's formula via `OWN_SKIP`; HL_CLAMP=1 in both. Crash window onset − 60 s .. onset + 30 min excluded.
- P4's band was never held (≈21k updates per coin), so P4 = P2.
- Mark vs today: median 0.6–0.9 bp, p99 6–15 bp, max 36–49 bp. Mark vs E median 1.7–6.8 bp (today 2.4–7.1). p99 step per update 6–15 bp (today 7–16).
- Accounts liquidated: 252 vs 261 (today); 1 only under P4. Stops differing are dust (GOOGL: 0.7 shares only under P4, 4.6 only under today).
- Today's oracle equals E outside gaps (p99 0 bp): funding unchanged.
- Crash scores with P4 all day: +$75.3k value at takeover, 300 underwater, $12.77M (vs from-16:00 +$75.3k, 298, $12.76M).

## Margin rules with P4: earnings leverage cut, daily OI table, cluster rule (2026-11-05)

Engine: `lev_cut=L cut_win=a:b` caps every tier's max leverage at L during [a, b); with `tier_topup=1` margined accounts post the extra IM at the window start and withdraw it at the end down to the base requirement (as far as equity stays above base IM). Fix: an account taken over has its top-up record cleared, so if the replay reopens it, it posts again (before, market makers were taken over hundreds of times at 5x with zero margin). Set `margin_p4` (data/scen/margin_p4.csv), coins GOOGL, INTC, AMZN, GOOGL_s5, GOOGL_s10. Scores count simulated takeovers (fair = Binance).

| P4 + | inherited (3 events) | value at takeover | underwater | split N = 5 / 10 (GOOGL) | trader margin |
|---|---|---|---|---|---|
| nothing | $12.76M | +$75.3k | 298 | $11.14M / $11.11M (GOOGL alone: $11.22M) | 0 |
| daily OI table O1 | $3.49M | −$14.6k | 297 | $11.14M / $11.11M | $6.6M all day |
| cluster rule (HL) | $1.51M | −$5.3k | 193 | $0.72M / $0.66M | $10.5M all day |
| **half leverage, close − 30 min to + 60 min** | **$0.02M** | **−$0.3k** | **10** | **$0 / $0** | **$17.3M for 1.5 h** |
| half leverage, from close − 5 min | $0.02M | −$0.3k | 10 | $0 / $0 | $17.4M |
| quarter leverage | $5.29M (market makers) | – | 6 | – | $49.8M |
| O1 + half leverage | $0.02M | −$0.3k | 10 | $0 / $0 | $19.8M |

- No ADL shortfall in any run.
- The cut liquidates fewer accounts (1,857 vs 1,938) but more shares (GOOGL +29%, INTC +78%, AMZN +68%), concentrated in a few large accounts; on GOOGL three market makers whose replayed fills are forced at the lower leverage account for the extra. Open loop overstates this.

## Size tiers and liquidation timing with P4, no event cuts (2026-11-05)

Set `margin_p4b` (data/scen/margin_p4b.csv, scored data/scen/margin_p4b_scored.csv). Event leverage cuts are excluded by product decision (earnings is when traders want to take a view).

| P4 + | inherited (3 events) | value at takeover | underwater | GOOGL split N = 5 / 10 | trader cost |
|---|---|---|---|---|---|
| nothing | $12.76M | +$75.3k | 298 | $11.14M / $11.11M | – |
| T1 (10x above $1M), top-up | $3.50M | −$14.4k | 297 | $2.01M / $7.20M | $7.5M margin |
| T1, reduce | $3.49M | −$14.6k | 297 | $1.99M / $7.85M | $41M size not held |
| T3 (10x above $500k, 5x above $2M), top-up | $2.67M | −$17.4k | 297 | $1.22M / $1.15M | $21.2M margin |
| takeover at ½ MM (HL) | $12.07M | +$63.0k | 456 | $10.81M / $10.80M | – |
| takeover at ⅓ MM (HL) | $9.68M | +$5.4k | 516 | $8.71M / $8.69M | – |
| cooldown 10 s (HL) | $12.76M | +$75.3k | 298 | unchanged | – |
| cluster rule (HL, reference) | $1.51M | −$5.3k | 193 | $0.72M / $0.66M | $10.5M margin |

- At 20x the MM zone (2.5% of notional; takeover at 1.7%) is two or three 1% mark steps: with an on-time mark there is no time to give the book, so liquidation timing does not help.
- Size rules reach the whale only; AMZN stays at $1.25M. No ADL shortfall anywhere.

## Quiet days: Oct 20 and 21, GOOGL / INTC / AMZN (2026-11-05)

Data: EC2 extracts of replica_cmds `2026-10-10T08:17:54Z/20261020|20261021` (120 files each, no failures), hydromancer xyz + global snapshots, fills, liquidations, 1-min books, node misc ledger (`ec2/pull_quiet.sh`). Pipeline per coin-day: `sim/pipe_day.sh DAY NEXT COIN ASSET MAXLEV` (ledger, oidbind, prep, silent cancels with L2 vetoes, margin, prio, liqside, accav, crossacc, relayer residual, validation). Quiet-day fixes: ledger.py writes an empty liquidation table; prep.py falls back to LIQ_FEE_RATE (5e-5) and a 0.9 bp vault fee when the day has no market liquidation or vault fill.

Validation at real parameters (ENDO=0, residual in): relayer mark exact 4,800/4,800 on all six; end-of-day positions 99.9–100% exact; liquidation rounds reproduced (GOOGL 10-21: 107 accounts, same total filled 100%); at most one sim-only takeover per coin-day ($0.03M on AMZN).

P4 vs today in every out-of-hours session (`DAY=… sim/normal_runs.sh`, `DAY=… sim/normal_eval.py`): band never held; mark vs today median 0.3–0.9 bp, p99 3.5–8.2 bp, max 11–26 bp; mark vs E as close or closer on 5 of 6; p99 step 2.0–6.0 bp vs 2.6–6.5 bp; accounts liquidated 35 vs 36 (none only under P4); stops only under P4 22 shares vs about 2,010 only under today; today's oracle lagged E by up to 21 bp (p99) on 10-21 overnight.

## Illiquid coins and the price-discovery screen (2026-11-05, sim/gate_screen.py)

Offline, no new data: P (self-calibrated window, voluntary taker fills, no age limit) and E (relayer externalPerpPx) per minute for every xyz coin with a feed, US out-of-hours minutes, Oct 20, 21, 28, 29: 469 coin-days, 489k minutes (data/scen/gate_screen.csv, discovery_episodes.csv).
- **P4's gate would never hold** (|P − E| > 1/maxLev): 0 minutes. Largest gap 9.5% (KIOXIA, 10x). Coins with trades hours old (RELIANCE, CAMBRICON: p95 age 2–5 h) never drift past the band. On thin coins P4 = P2; no illiquid-coin extract needed.
- **Discovery episodes** (|P − E| > 1% for 2+ min, resolved over 30 min): 522; xyz led 199, reverted 121, unresolved 202. Almost all Asian stocks; the largest happen with the home market closed and the feed frozen (SKHX ext 1132.9 for 4 h while xyz fell 5%; KIOXIA ext 90.916 while xyz fell 9.5%, the feed reopening where xyz was), i.e. trade.xyz's internal pricing, outside P4's scope.
- US stocks out of hours with a live feed: 48 episodes, median 3 min (max 18), median gap 1.2% (max 3.2%); 15 led, 24 reverted, 9 unresolved.

### Re-split by regime (2026-11-05)
Out-of-hours and closed-market are different regimes. The relayer is in an external session when its published oracle equals E (live feed). It is internal when the oracle differs from E (E frozen at the close, oracle = 30 min EMA of the book). US stocks are external 24/5, including pre-market, post-market and overnight. Asian stocks switch to internal every weekday after their extended session (SKHX at 11:00 UTC). `gate_screen.py` now labels each minute with this regime (|oracle/E − 1| > 0.5 bp means internal), excludes US regular hours, and computes the gate over external minutes only. Each episode carries `regime`, decided by majority.
- Gate: 0 of 417,690 external minutes would hold. Closest is JIO 10-28 at 8.48% on a 10% band: E jumped 9% at the Indian open and xyz stayed 6–8.5% below it for about 9 h. KIOXIA's 9.54% was internal. 87,221 internal minutes were set aside.
- Episodes: 529, of which 238 external and 291 internal. The internal ones are the long, large ones (median 17 min, up to 800). The external Asian coins in their own session include JIO and UNITREE (up to 6.4%). Every other external coin: 74 episodes, median 3 min, median gap 1.2%, max 2.2%.
- The tapes contain no weekend, so US internal pricing is untested.

## xyz push beyond the band (2026-11-05, sim/wash_runs.sh, sim/wash_eval.py)
`WASH="start_ms;secs;frac;ntl"` (engine OwnMark) injects synthetic voluntary prints of `ntl` per relayer update. Their price is fixed at the external price at `start` × (1 + frac). They enter P and the self-calibrated volume, but not the book. This is the best case for the attacker: no sweep is needed and the cost is fees only. `OWN_GATE=2` (P4b) holds the band only if the book's impact mid at `OWN_N` (6,000 USDC, Hyperliquid's funding impact notional) is also beyond d on P's side. Runs on GOOGL 10-28, from C − 5 s, frac +6%:
- $10M per 30 s: no design moves more than 37 bp. The crash volume pulls P back, and P4's centre follows E to 311 and holds there; the crash to 300 stays inside the band.
- $50M per 30 s: P4 holds for the whole attack (1, 5, 15 min), mark +297 / +374 / +444 bp above base, book liquidations −810 to −917 shares, takeovers +$0.07–0.18M. P2 and P4b ≤37 bp; today 0.
- P4b equals P4 on the spike runs (−5% and −20%, 3 s to 5 min) and on the stuck feed (identical takeover scores).
- Untested: an attacker who also moves the book's impact mid.

### Book prop beyond the band (2026-11-05, sim/prop_runs.sh)
`ATTACK_PROP="ms;secs;frac;ntl"`: a fresh account sends, every block, a buy limit at P0 = mid at start × (1 + frac) for ntl. It lifts every ask ≤ P0 and rests the remainder at P0. Post-only asks at or below P0 sell to it (instead of the replay's pruning of crossing bids). Engine prints `PROP:` with shares bought, cash and peak position.
- GOOGL 10-28, frac +6% (347.36), 60 s, $0.2M / $1M / $5M per block: it buys 359–421k shares ($112–132M), but its bid is never standing at a relayer update and P4b never holds. The open-loop makers keep re-quoting near E, so this volume is not a cost estimate.
- Lower bound from the real tape (real taker sells fill at P0, valued at E at the end): ≥ $2.8M loss in 60 s, $5.0M in 5 min, $7.5M in 15 min.
- If the book and P are both held at P0 (analytic): P4/P4b mark = R0(1 + d) = 343.9, while today and P2 give E(1 + d) ≈ 320.

### Hold limit (2026-11-05)
`OWN_HOLD_S=s` limits a P4b hold to s seconds. On its own (P4c), the centre then jumps to E. With `OWN_HOLD_STEP=1` (P4d), the centre instead steps toward E by at most d·R and the hold restarts. Engine prints "hold expired" counts. s = 150, which is trade.xyz's mark EMA time constant.
- P4c: the −20% 5-min print gives GOOGL −1619 bp and +$8.1M takeovers (today: −1615 bp, +$7.0M). Rejected.
- P4d: all spike runs ≤ 34 bp. Stuck feed, crash base and $50M/30 s wash are identical to P4b.

## Liquidation sizing and vault unwind (2026-11-06)

**Restore-to-IM liquidation** (`liq_restore=k`, `restore_big=1`): above $100k a liquidation round sells the size that brings the account back to k × MM at the mark (k=2: initial margin), every mark update, no cooldown; smaller positions close in full. On P4d: inherited $12.76M → $10.98M; quiet days unchanged. Registry test `restore-im`.

**Vault unwind** (`VAULT_FAIR=1`: after the 0.5% clip, the vault takes every resting order at or better than the external price; `VAULT_LOG=path`: every vault inventory change, kind 0 takeover / 1 unwind). Decomposition against E (`sim/unwind_decomp.py` real fills, `sim/vault_decomp.py` sim logs): PnL = cushion + drift + execution − fees, exact on the real fills (within $1.5k). Drift is exact for a given schedule; the execution term relies on the open-loop book, so the reporting rule still applies (no scenario vault PnL). Registry test `vault-unwind`.

### SKHX hand-over (2026-11-06)

Data: EC2 extract of replica_cmds `2026-07-25T07:35:28Z/20260727` (122 files, no failures; only the setOracle rows of SKHX/SKHY reduced, `data/extract0727/tables/oracle.parquet`), hydromancer xyz fills / 1-min books / snapshot / liquidations for 07-27. `sim/handover_screen.py` (640 hand-overs, 4 days) and `sim/skhx_handover.py` (offline P4d across the hand-over). At 23:00:03.9 E returned at 868.18 (−22%) with xyz at 1,128; the oracle went straight to E × 1.1 (no 50 bp clamp at the hand-over) and the mark fell 1% per update. P4d with R carried over from the internal session holds at the first update and keeps the mark at 1,128–1,130: no pre-existing position liquidated (real: 945 accounts, $31.5M). Registry test `skhx-0727`.

### Package run (2026-11-06)

`sim/package_runs.sh` (today → + P4d → + restore-to-IM → + fair sweep; crashes and quiet days) and `sim/package_eval.py`. The fair sweep leaves every takeover unchanged. Package vs today on the crashes: inherited $10.98M vs $9.83M, value at takeover vs E +$57k vs −$152k, underwater 300 vs 812, vault exposure $9.5M·min vs $107M·min, sold below E $0.47M vs $3.38M. Quiet days identical. Registry test `package`. *(Rerun 2026-11-06 with the per-user liquidation fee and the final-mark cap, commit 30f829f: every number within 0.1% of the first run; underwater 810 → 812, sold below E $3.37M → $3.38M; quiet days identical. Old scores: data/scen/old_pre30f/.)*

## Parity: liquidation over-fill (2026-11-06, sim/liqfit_runs.sh, sim/liqfit_eval.py, sim/liqfit_stop.py)

**Question.** At real parameters the sim liquidated slightly more than HL in 117 / 142 / 295 accounts (GOOGL / INTC / AMZN). Which rule is loose?

**Where.** Round by round (RDETAIL_OUT), every round that ran to its requested size matches HL exactly (568/571, 285/287, 132/132). The whole excess is in rounds the **equity stop** ended early. In those rounds HL fills at the same prices and in the same order as the sim (checked against the real fills), and it stops mid-order. So the stop computes a size; it is not a price limit. The equity is valued at the mark (an implied threshold at the mark has a hard floor at exactly 2/3 MM; valuing at the fill price gives nonsense). Margin release inside a fill changes nothing (an isolated release keeps the equity/MM ratio).

**Fix: the liquidation fee is the account's own base taker rate.**
- HL charges the liquidated side its own taker rate net of builder fees: 0.864 bp (the 4% discount) or 0.9 bp on almost every fill, and other tiers (0.81, 0.82, …) for a few. It equals the user's net taker rate on other fills for every account that has both.
- prep.py averaged the fee over **both** sides of the liquidation fills, makers included: 0.56 / 0.43 / 0.45 bp. A cheaper fill leaves a little more equity, so the stop fired late.
- Now `fees.arrow` has a `liq` column per user (sim/fees_liq.py, also called by prep.py): (1) its own liquidation fills on any xyz coin that day, else (2) its net taker rate on any xyz coin that day (fills > $100), else (3) the day's median liquidation rate (0.864 bp on every prep). The engine uses it for its own liquidation fills and for replayed ones. `LIQ_FEE_COIN=1` restores the old per-coin rate.
- prep.py's per-coin fallback rate now counts the liquidated side only, net of builder fees.

| ENDO=0, simulated relayer, policy unwind | GOOGL | INTC | AMZN |
|---|---|---|---|
| accounts with market rounds in both: same total filled | 83.4% → **89.0%** | 70.7% → **82.1%** | 38.7% → **54.7%** |
| stopped rounds exact (same block) | 42 → 87 of 162 | 102 → 166 of 256 | 69 → 152 of 392 |
| takeover size within 5% | 90.0% → **95.4%** | 93.4% → **96.1%** | 98.2% → **99.0%** |
| takeovers both / sim-only / real-only | 150/5/3 → 152/5/1 | 258/0/3 → 258/0/3 | 400/3/0 → 400/3/0 |
| takeover notional sim / real | $6.05M → $6.06M / $6.06M | $2.24M / $2.25M | $1.53M / $1.55M |

**Residual (open).** The remaining stopped rounds still over-fill by a median 0.4% / 1.9% / 0.35% of the round.
- It behaves like the sim's equity before the round being too high by ~0.1–2 bp of notional, varying by account. It is not one price per block: the implied stop price differs between accounts in the same block. One exception is AMZN block …2264, where all ten accounts fit 233.115 = 235.47 × 0.99: the previous mark less HL's 1% per-update cap, while the published move was −1.05%.
- Ruled out: the mark (equal to `liquidation_mark_px` on every round), funding (the 20:00 payment is applied before the crash and does not scale with the gap), the snapshot margin solve (positions opened intraday over-fill as often), and the liquidation release rule (replay mode: eq_release = keep, and prop_before / prop_after are far worse against the ledger).
- *Correction (same day):* a first lead, that positions opened intraday sit below the ledger at takeover in replay mode, was an artifact. `engine accounts` never feeds the mark to the clearing (mark = NaN), so the opening gap term is skipped there. In the full sim the same accounts match the ledger to cents (AMZN u2028: $11.316 vs $11.312).

**Effect on earlier results.** Every scenario run before this used the half-size liquidation fee. Liquidated accounts now pay about $0.4 per $10k more, and partial rounds stop slightly earlier. Takeover notional moves by under 1%. The scenario tables (package, restore, fair sweep) need regenerating under the new fee before the benefits ledger.

## Parity: HyperCore's 1% cap on the final mark (2026-11-06)

**Finding.** At AMZN 10-29 block …2264 the relayer published m1 = m2 = 233.0, a −1.05% move from the previous mark 235.47. Hyperliquid's liquidation fills in that block record a mark of **233.115** = 235.47 × 0.99. The sim used 233.0. INTC has the same case: 90.223 → published 89.177, real 89.3208 = 90.223 × 0.99. So HyperCore clamps the *final* mark, median(m1, m2, median(bid, ask, last)), to ±1% of the previous final mark, rounded to 6 − szDecimals decimals. The old `HL_CLAMP` capped the relayer's components instead, which also fed back into the relayer's own history, and it was off by default ("never binds"). It does bind on fast crashes.

**Engine.** `OrcRec` carries the cap band [lo, hi] from the previous final mark, and `mark_of`, the trigger mark and `mark_check` all clamp to it. It is on by default, since it is a protocol constant; `HL_CAP=0` turns it off. `mark_check` now also reports exact matches. The scripts that set `HL_CLAMP=1` (package, normal, prop, wash, vault, spike, freeze runs) should drop it when they are rerun.

**Also tested and rejected:** isolated opening margin on the notional at the mark (`iso_im=mark`), or at the mark only when the fill beats it (`iso_im=better`). Both worsen first-round timing on every coin (GOOGL 97.5 → 93.7%, INTC 96.9 → 89.7%). The fill-price rule stays.

**Parity now** (real parameters, ENDO=0, simulated relayer, per-user liquidation fee, cap on):

| | GOOGL | INTC | AMZN |
|---|---|---|---|
| mark exact at liquidation blocks | 100/101 | 102 → **103/103** | 82 → **83/83** |
| same total filled (accounts with rounds in both) | 83.4 → 89.0 → **89.0%** | 70.7 → 82.1 → **83.1%** | 38.7 → 54.7 → **58.1%** |
| takeover same block | 99.3% | 98.8 → **99.2%** | 98.0 → **99.8%** |
| takeover size within 5% | 90.0 → **95.4%** | 93.4 → **96.5%** | 98.2 → **99.5%** |

(Each arrow chain is: before the fee fix → fee fix → fee fix + cap.)

**What is left, in dollars.** The excess liquidated notional is concentrated in a few accounts:
- **GOOGL:** $43.7k, 97% of it in 6 accounts. Two are cross-dex accounts the sim liquidates and HL does not (u646, u1657, both on other-dex requirements), plus the whale ($9.0k).
- **INTC:** $295k, 95% of it in one market maker, 0xa38f19c4. The sim liquidates it about 70 s before HL on the same position, with no margin action in between; it is already listed as an R2 account.
- **AMZN:** $15.2k, mostly the cross-dex accounts u3177 and u2051. Their ledger values match accounts on INTC, i.e. one shared multi-dex balance.

The remaining hundreds of small over-fills are a few cents to a few dollars each. The next parity item is cross-dex accounts (g-cross), not liquidation rules.

### Rerun under the parity fixes (2026-11-06)

`sim/package_runs.sh` (crashes and quiet days) and `sim/vault_runs.sh` were rerun with commit 30f829f: per-user liquidation fee, HyperCore's 1% cap on the final mark, and `HL_CLAMP` removed from every run script. Scores: `data/scen/package_eval_30f.txt` and `vault_decomp_30f.txt`; the old ones are in `data/scen/old_pre30f/`.
- **Package, crashes (today vs package):** inherited $9.83M vs $10.98M (unchanged); value at takeover vs E −$152.0k vs +$56.5k (was +$56.6k); underwater 812 vs 300 (was 810); exposure 107.0 vs 9.5 $M·min; sold below E $3.38M vs $0.47M.
- **Quiet days:** identical on every layer.
- **Vault policies:** every row within $100 or 0.1%.
- The fee and cap fixes change parity at the account level, not the protocol comparison: the cap binds on only 2 updates across the three crashes, and the fee moves liquidated equity by about 0.4 bp of notional.

## Parity: cross-dex accounts (2026-11-06)

Three fixes to how the clearing sees an account's other positions (`sim/crossacc.py` rerun on the three crash preps; validation unchanged at 2,666 / 1,244 / 1,079 accounts).

**1. Other-position MM was clamped event by event.**
- `acc_xev` rows were written with `sort("h", "u")`, which does not keep order among ties. An account with many fills in one block got its MM changes shuffled inside the block.
- The clearing clamped other-position MM at 0 after each row, so a shuffled block that ran negative partway through lost that amount permanently. In 325 / 251 / 183 validated accounts the clamp added phantom MM, up to $240 / $301 / $318.
- GOOGL u1657 (an xyz SPCX long elsewhere) was liquidated on $76.98 of other MM against a real $75.84.
- Fix: the clearing sums the raw changes and clamps only where the requirement is computed (`mmo_pos`). crossacc keeps time order (`maintain_order=True`).

**2. A cross account is liquidated on all its coins at once, in asset order.**
- AMZN 0xea3ce3e9 (u3177) held INTC and AMZN cross. HL ran both rounds in one block, and its AMZN round stopped after 0.006 shares: the INTC fills had already used the equity. On INTC the same account already matched, with its stop not seeing AMZN.
- So HL processes the account's coins by asset index (INTC 110005 before AMZN 110013).
- crossacc writes the other coin's liquidation fills one block late (so the trigger tests the state before them) and now flags them `pre` when that coin's xyz asset index is lower. The engine applies the account's `pre` rows after the trigger and takeover tests and before this coin's equity stop. `XPRE=0` turns it off.
- u3177: 53.667 → **0.006** shares (real 0.006). u2051: 2.69 → 0 (real 0.005).

**3. Funding on another coin's isolated position.** It now moves that position's isolated margin as well as cash (X = cash + E·q − IM for an isolated coin, so cross X does not move). Before, it went to cross cash only. End-of-day validation cannot see the difference, because account value includes isolated equity.

| real parameters, ENDO=0 | GOOGL | INTC | AMZN |
|---|---|---|---|
| same total filled | 89.0 → **89.2%** | 83.1 → **83.6%** | 58.1 → **58.7%** |
| first round same block | 97.5 → **98.3%** | 96.9 → **97.2%** | 97.6% |
| takeover size within 5% | 95.4 → **96.7%** | 96.5 → **96.9%** | 99.5 → **100.0%** |
| takeover notional sim / real (incl. cross) | $7.16M / $7.16M | $2.38M / $2.38M | **$1.57M / $1.57M** |
| excess liquidated notional | $43.7k → $38.1k | $295.2k → $295.1k | $15.2k → **$2.2k** |

**Left.**
- **GOOGL u646 ($27k) and INTC u2887 ($6k):** sim-only liquidations on a margin of about $2. Both are inside the cross reconstruction's validation tolerance (u646's end-of-day error is $1.34), so the reconstruction cannot decide these cases.
- **The whale's partial round:** $9.0k.
- **INTC 0xa38f19c4:** the R2 market maker, $280k.

## Benefits ledger (2026-11-07, sim/benefits.py → docs/benefits.md, data/scen/benefits.csv, registry key `benefits`)

The package (P4d + restore-to-IM + fair sweep) against today, on every test that exists, with every number read from a run output or a registry test.
- **New runs.** The attack suite (V4_package added, 15 attacks + base), bad prints −5% / −20%, the stuck feed, wash prints, a book prop and normal markets, each for `today` and `pkg`: 106 engine runs. `pkg` is a new mark option in spike / freeze / wash / prop / normal runs. Registry tests `bench-*` and the `package` design.
- **Inputs refreshed.** Quiet-day cross files regenerated under the cross-dex fixes (validation 1,155 / 543 / 687 / 1,311 / 488 / 675). Package runs rerun, now logging bad debt (`data/scen/pkg/runs.log`): $0 in every run, today and package.
- **Verdict rule.** A difference counts only above a floor ($1k, $0.05M, 5 bp, 1 unit, or 1% of the larger value).

**What it shows** (see docs/benefits.md for every row):
- **Losses.** On the three crashes the vault inherits more notional ($10.98M vs $9.85M) but at a value of +$56.6k against E instead of −$152.0k (+0.52% vs −1.54% of notional). Underwater takeovers 300 vs 812, exposure 9.5 vs 107.1 $M·min, sold below E $0.47M vs $3.38M. SKHX 07-27: 0 vs 945 positions liquidated at the hand-over.
- **Attacks (suite, GOOGL).**
  - Under every attack the package ends with more value against E than today, and with 12 underwater takeovers instead of 153–157 (cross-collateral shock: 846 vs 992).
  - The matched-position put turns from a gain for the attacker into a loss (gross: +$7.8k → −$5.3k at $2M, +$52.7k → −$26.7k at $10M).
  - Maker pulls, stop hunts, walls and wash OI change nothing under either rule set in the replay (open-loop makers).
- **Bad prints and stuck feed.**
  - A −20% print moves today's mark −1,782 bp and causes $14.6M of takeovers and 902 stop orders; the package moves it at most −34 bp, with no takeovers or stops caused.
  - Stuck feed at onset: value vs E −$382k → +$7.7k.
- **Where the package is weaker.**
  - Wash prints, which today ignores, lift its mark 33–37 bp. That is inside the band, and they cause no extra takeovers.
  - A buy wall at +6% lifts it 209–621 bp, against 20–162 bp today, and costs the vault up to $111k of value at takeover. The attacker loses $7.5M–$29.9M at E doing it.
- **Traders.**
  - Quiet days identical (119 accounts liquidated, 6 takeovers).
  - In normal out-of-hours markets the mark is within 15 bp of today's at p99. Accounts liquidated 252 vs 260; 1 account only under the package vs 9 only under today. Stop orders fired by one side only: 272 vs 137, but 30 shares vs 834.
  - Crashes: 1,851 vs 1,785 accounts go through book liquidation.
- **Hyperliquid changes.** The mark is the relayer's (trade.xyz). Restore-to-IM and the fair sweep each need a HyperCore change.
- **Not measured.** ADL (the vault's capital is not modelled); maker reactions (out of scope by rule).

### Hold cap on P4d: tested and rejected (2026-11-07, OWN_HOLD_CAP=1, design `package_cap`)

**Why it was tried.** The ledger's weakest robustness row is the +6% buy wall. During a hold the band is clipped to R(1 ± d) around the held centre, and a wall that props both xyz trades (P) and the book lets the median rise toward R(1 + d): +621 bp at $1M and $5M per block, against 57–162 bp today.

**Rule.** While held, the band ends at R0 on the side away from E, so a hold can stop the mark following E but cannot push it further away. Engine: `OWN_HOLD_CAP=1` (off by default); `pkgc` mark in the run scripts; `V5_package_cap` in the attack suite.

**Three versions, each breaking another protection:**

| R0 = | wall $1M / $5M per block | −5% print, worst case | stuck feed, value vs E |
|---|---|---|---|
| the stepped centre | 115 / 115 bp | −507 bp (followed after one 150 s step) | −$283k |
| the centre when the hold began | 115 / 115 bp | −475 bp (AMZN 16:10, 30 s: a hold confirmed one update late starts from the bad print) | −$283k |
| the last agreeing centre, capped only while E changed since the last update | 621 / 115 bp | −29 bp | +$7.7k |
| (package, no cap) | 621 / 621 bp | −32 bp | +$7.7k |

**Conclusion.**
- A stuck feed needs the hold to follow xyz *away* from a frozen E; the wall needs it not to. The only signal that separates them (E moving) is too noisy over one 3 s update and too slow over 150 s, against the 120 s freeze tested.
- The package keeps P4d unchanged. The wall's cost to its author ($26–30M at E) against the vault's loss (≤ $111k) is reported in the ledger.
- The `package_cap` rows were removed from the bench tests (they mixed versions); the design entry keeps the numbers above.

## Buy wall with a faithful attacker, and the hold-start rule (2026-11-07)

**The attack did not follow the engine.** `ATTACK_PROP` (prop_runs.sh) used a phantom buyer outside the clearing (no collateral, no margin check, no liquidation), and filled post-only asks that crossed its bid. HyperCore rejects such asks.
- Now, with a 5th field (capital), the attacker is an ordinary cross account at max leverage (`Clearing::add_attacker`). Each block it bids only what its free margin allows (`free_margin × maxLev`). Its fills go through `fill()` like everyone's, and the clearing liquidates it or hands it to the backstop by the same rules.
- Post-only asks that would cross its bid are rejected (559 to 31,352 per run).
- Runs: `CAPS="1e6 5e6 25e6"` in prop_runs.sh, data/scen/prop_faith; the engine prints `PROP ACCOUNT`.
- The open-interest cap is not modelled (its value for xyz is not in our data); it could only make the attack harder.

**Result.**
- With $1M of capital the attacker is liquidated and taken over within the first minute.
- At $5M+ the package's mark was held up 592 bp for about a minute (today 60–162 bp). That liquidated 73 accounts that are not liquidated otherwise (today 1), with 151 extra stops.

**Fix adopted: the hold-start rule** (`OWN_HOLD_TRIG=1`, design `package_trig`, now the lead).
- A P4d hold may start only when E moved by more than d within the trade window (30 s, `OWN_H_S`), or has not changed for that window. Once started, it continues as P4d. No new constant.
- Bad prints (16 cases), the stuck feed, SKHX 07-27 (0 of 945 pre-hand-over positions liquidated), crashes and quiet days: identical to the package.
- $5M wall: 73 → 33 extra liquidations.

**Tested and not adopted:**
- **Single-update jump** (`OWN_HOLD_TRIG=2`, `package_step`). It blocks the wall's hold entirely (no hold starts) but leaves the mark at the band edge: 485 bp, 37 accounts, vault −$71k, vs 592 bp, 33 accounts, −$26k.
- **Hold cap** (`OWN_HOLD_CAP=1`, live feed over 30 s). 412 bp, 34 accounts; with the start rule, no better.

**What remains** (ledger rows "buy wall …").
- Within the band P4d trusts xyz's own trades and book: trade.xyz's own-book constraint out of hours. A wall with $5M or more of capital can keep the mark up to ~5–6% above a crashing feed for about a minute: 33 extra liquidations, vault −$26k against E. The attacker loses about all its capital.
- From E and xyz alone, a real move of more than d in 30 s with a wall cannot be told from a bad print in a calm market.

**Also not yet faithful.** The suite's sweeps (`ATTACK_AT`), ask wall (`ATTACK_WALL`) and wash prints (`WASH`, `ATTACK_WASH`) still use phantom accounts or inject prints. They change nothing under either rule set, but they should be redone with margined accounts.

## Faithful attackers everywhere, and the lead design (2026-11-07)

**Every injected attacker now obeys the engine** (`ATTACK_CAP`).
- The sweeper, ask wall and wash accounts are ordinary cross accounts in the clearing. Their orders are capped by free margin, and they are liquidated and taken over like anyone.
- Wash prints are real trades between two attacker accounts: A rests an ask, B lifts it. A +6% wash (`WASH`) is therefore a buy that walks every real ask up to +6% first; no print at +6% with the book untouched is possible.
- Suite: `SUITE_FAITHFUL=1` gives each attacker capital = the largest notional its attack places (data/scen/attack_suite_faith.csv). Wash: `CAP=5e6` per account (data/scen/wash_faith).
- Result: sweeps, stop hunts, walls and the in-spread wash change nothing under either rule set.
- The faithful +6% wash exposed the trade-led mark. It lifted P4d's mark 397–663 bp, liquidated 36–41 accounts that are not liquidated otherwise, and the vault took over the buying account at −$1.16M against E. Today: 7 bp, 0 accounts, −$97k.

**Why today resists it.** Today's book input is clamped to 50 bp around the oracle path, so xyz's book can pull the mark only slowly. The same clamp makes the oracle lag a real crash and follow a bad print (812 underwater takeovers on the crashes; −1,782 bp on a −20% print). The package had removed the clamp from both.

**The lead design: `package_v`** (mark switches `CLAMP_O_BPS=100000 M2_REF=ext OWN_ONLY_HOLD=1 OWN_HOLD_TRIG=2 OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005`; with restore-to-IM and the fair sweep).
- **Outside a hold:** today's relayer, with the oracle input following E with no clamp, and the book input clamped within 50 bp of the current E.
- **Starting a hold:** a feed failure, i.e. a single-update jump of E by more than d, or E unchanged for two updates in an external session, *and* xyz and its book disagreeing with E by more than the clamp.
- **During a hold:** P4d's xyz-led inputs, kept while the disagreement stays above the clamp.
- **Constants:** d and today's 50 bp clamp only.

| | today | package (P4d + start rule) | **package_v** |
|---|---|---|---|
| crashes: value at takeover vs E / underwater | −$152k / 812 | +$56.6k / 300 | **+$53.9k / 322** |
| −5% / −20% bad print, worst case | −417 / −1,782 bp | −32 / −34 bp | **−42 / −42 bp** |
| stuck feed at onset, value vs E | −$382k | +$7.7k | **+$7.5k** |
| +6% wash $1M–5M/update: lift, accounts hit only by it | 7–24 bp, 0 | 397–663 bp, 36–41 | **50 bp, 0** |
| $5M buy wall, 1 min: lift, accounts hit only by it | 60 bp, 1 | 592 bp, 33 | **50 bp, 1** |
| vault taking over the wash attacker | −$97k | −$1.16M | **+$253k** |
| normal markets: mark vs today p99, stops only one side | — | 11–15 bp, 272 | **0 bp, 0** |
| SKHX 07-27: pre-hand-over positions liquidated | 945 | 0 | **0** |

**What a push still does:** it lifts the mark by the clamp (50 bp) and shifts the vault's takeover values by −$11k to −$23k.

**Measurement fixes on the way:**
- "Accounts hit only by the attack" now counts book rounds *and* takeovers. The earlier count flagged accounts that are taken over in both runs and only got a round first under the attack.
- The SKHX replay treats only an external-session freeze as a stuck feed; the internal session freezes E on purpose. The relayer must apply the rule the same way.

**Tested and not adopted on the way:**
- P through a 150 s EMA (`pkge`, `pkgx`).
- Today's relayer with only the oracle unclamped (`pkgz`).
- The same with an oracle-only book clamp and a two-update freeze (`pkgy`).
- The same without the jump gap (`pkgw`, which leaves AMZN's −5% print at −470 bp).

## Backstop vault capital and ADL (2026-11-07, sim/vault_capital.py, registry test `vault-capital`)

**Rule (HL docs).**
- Each HIP-3 dex's backstop liquidator is an ordinary account. A takeover transfers the trader's positions with their remaining margin, and ADL fires when any account's value goes negative, the vault's included.
- Two capital levels per event:
  - C_MM = the capital to keep the vault's equity above the maintenance margin of its inventory. Below it, the vault is itself liquidated.
  - C_ADL = the capital to keep its equity above zero.

**ADL on xyz, from the tapes.**
- **SKHX 07-27:** 108 ADL fills, all against the vault ($25.4M SKHX, $0.16M SKHY, 23:01–23:02 UTC). The vault held $1.01M against a need of $1.24M (C_ADL; C_MM $2.49M), so it ran out. This was the "−$1.00M at 931.36" in the loss record.
- **NOW, LITE, MRVL (10-28) and RDDT (10-29):** ADL against isolated positions on markets where the backstop cannot take positions (no cross margin). Capital cannot help there; enabling cross margin on those markets would.

**Validation.** On the three crashes the replay's need (today's rules, policy unwind) matches the real vault's own fills: 0.56 vs 0.57%, 0.69 vs 0.74%, 1.19 vs 1.18% of the market's OI (C_MM).

| capital as % of the market's OI (C_MM / C_ADL) | today | package_v |
|---|---|---|
| GOOGL 10-28 (OI $59M) | 0.56 / 0.31 | 0.28 / 0.06 |
| INTC 10-29 (OI $35M) | 0.69 / 0.47 | 0.02 / 0.01 |
| AMZN 10-29 (OI $12M) | 1.19 / 0.93 | 0.84 / 0.73 |
| SKHX 07-27 (OI $311M, real) | 0.80 / 0.40 | ≈ 0 (no cascade: 0 of 945 positions) |

**Capital rule** (worst observed share × the OI of markets that can gap together; xyz OI $2,019M on 119 markets on 10-29, largest single market $248M; `data/scen/vault_capital_rule.csv`):

| OI at risk | today C_MM / C_ADL | package_v C_MM / C_ADL |
|---|---|---|
| largest single market ($248M) | $2.95M / $2.31M | $2.08M / $1.81M |
| 25% of xyz OI | $6.0M / $4.7M | $4.2M / $3.7M |
| 50% of xyz OI | $12.0M / $9.4M | $8.5M / $7.4M |
| all xyz OI | $24.0M / $18.8M | $17.0M / $14.7M |

**Against the vault's $1.84M (11-02).**
- Under today's rules it covers one market gapping with OI up to about $155M (C_MM) or $198M (C_ADL).
- Under package_v, up to about $219M / $252M.
- SP500 ($200M) and SKHX ($248M) are already near or past that.

**Limits.**
- Four events. The worst share is AMZN's (a 5.6% gap in two updates that outruns HyperCore's 1% per-update cap, so the vault inherits underwater positions under any mark rule).
- The package's numbers rest on the replay's unwind (fair sweep).
- The scaling to several markets at once assumes each moves like the worst observed event. That is an upper envelope, not a forecast.
- The capital is the vault's equity, not its deposits: past losses reduce it.
