# The proposed mark-price inputs: specification

This document specifies the two values the relayer would publish at each update, exactly as the replay engine computes
them. It was written from the engine's source, and a separate Python implementation (`three_vote_reference.py`, same
folder) was checked against the engine's output on SK Hynix, July 27, 2026 (`july27_skhx_test_vector.csv`). Where the
engine and this text could not be made to agree exactly, or where the engine does something a reader would not expect,
it is listed in the last two sections.

Hyperliquid's side does not change. Only the meaning of the two published inputs changes:

- **V, the feed's vote** (published as the first input): the external price while the feed is live, otherwise an
  internal price that follows xyz's own book slowly.
- **A, the average** (published as the second input): a 30-minute exponential average of V, with one correction step.

## 1. Notation and units

| Symbol | Meaning |
|---|---|
| t | time of the update, in milliseconds |
| E | external price at the update |
| bid, ask, last | xyz's best bid, best ask and last trade price at the update |
| mid | (bid + ask) / 2, only when both sides are present |
| B | the book price: median(bid, ask, last); see section 6 for an empty side |
| M | Hyperliquid's mark |
| V, A | the two published inputs |
| O | the internal price (unrounded) |
| x' | the value of x at the previous update |

All arithmetic is in IEEE double precision. The engine holds A in units of 1e-6 USD and O in USD; the reference does
the same so that rounding falls on the same side.

## 2. Constants

| Constant | Value | Engine setting |
|---|---|---|
| Time constant of the average A | tau = 1800 s | `MARK3="e;1800"` |
| Time constant of the internal price | tau = 1800 s | `INTERNAL_TAU` (not set; default 1800) |
| Largest time step counted by the internal price | tau / 10 = 180 s | fixed in the code |
| Largest gap to the book mid the internal price sees | kappa = 1% of O | `INTERNAL_CAP=0.01` |
| Repeats of E after which the feed is not live | 2 updates in a row | `RELAYER_STALE_INTERNAL=2` |
| Bound of the internal price around E | d = 1 / max leverage (SK Hynix: 10x, d = 10%) | engine argument; `ORACLE_CAP` not set |
| V is the internal price when the feed is not live; A is never restarted | on | `MARK3_INT=1` |
| Correction step of A, skipped when the book decided the previous mark | on | `MARK3_RATCHET=b` |
| Per-update limit on the relayer's own price | effectively none (factor 10) | `CLAMP_O_BPS=100000` |
| Bound of A around E | none | `MARK3_D` not set |
| Band around the plain average | none | `MARK3_BAND` not set |
| One side of the book empty: the lone quote is the book price | on | `ONE_SIDED` not set (default) |
| Hyperliquid: largest move of the mark per update | 1% | `HL_CAP` not set (default on) |
| Price grid | 5 significant figures, at most 6 - szDecimals decimals (SK Hynix: szDecimals 3) | from the asset's metadata |
| Scheduled closures | list of [from, to) in ms (SK Hynix: 20:00 to 08:00 Seoul time, on July 27: 11:00 to 23:00 UTC) | `july27_skhx_closures.txt` (same folder) |

The run scripts pass five settings for this rule and nothing from earlier candidates: `CLAMP_O_BPS=100000`,
`RELAYER_STALE_INTERNAL=2`, `INTERNAL_CAP=0.01`, `MARK3="e;1800"` with `MARK3_INT=1`, and `MARK3_RATCHET=b`
(`sim/pkgm_env.zsh`). Removing any one of them changes the replay; a configuration with only these reproduces the final
run byte for byte. The fitted residual file (`RELAYER_RESID_IN`) does not affect V or A:
its first column corrects today's second input, which the proposal replaces; its third column shifts a limit that
`CLAMP_O_BPS=100000` makes inactive; its second column can override the read delay (section 9, item 3), and is zero on
every row for this day.

## 3. Rounding

**Grid.** The tick at price x is 10^-min(4 - floor(log10 |x|), 6 - szDecimals). For SK Hynix: 0.1 from 1,000 up, 0.01
from 100 to 999.99.

- *nearest*: floor(x / tick + 0.5) x tick (halves go up)
- *up*: ceil(x / tick - 1e-9) x tick
- *down*: floor(x / tick + 1e-9) x tick

The tick is taken at x before rounding.

**What is rounded how.**

| Value | Rounding |
|---|---|
| V, feed live | E as received, no rounding (E was on the grid on all 29,010 updates of the test vector) |
| V, feed not live | O to the nearest tick, then kept inside [E(1 - d) rounded up, E(1 + d) rounded down] |
| O, kept between updates | not rounded; kept inside [E(1 - d), E(1 + d)] |
| A, kept between updates | not rounded |
| A, published | to the nearest 1e-6 USD. **Not on the grid** (see section 10, item 1) |

## 4. State kept between updates

| State | Initial value |
|---|---|
| t' : time of the previous update | none |
| E' : external price at the previous update | none |
| n : number of updates in a row with E equal to E' | 0 |
| P' : price the relayer's feed side published at the previous update, on the grid | none |
| O : internal price, unrounded; exists only while the feed is not live | none |
| A : the average, unrounded | none (the first update sets A = V) |
| last two-sided mid | none |
| V', A' as published, B', M' : the previous update as Hyperliquid saw it | none |

## 5. One update, in order

Inputs read: t, E, bid, ask (now); and from the previous update V', A' as published, B' and M'.

**Step 1. Is the feed live?**

    n = n + 1 if E == E' else 0          (exact equality of the received values)
    E' = E
    closed = t is inside a scheduled closure  (from <= t < to)
    live = not closed and n < 2

So the feed stops being live at the third update in a row carrying the same E, and is live again at the first update
with a different E, unless the venue is in a scheduled closure.

**Step 2. The feed's vote V.**

If live:

    V = E
    O is dropped
    P' = E rounded to the nearest tick

If not live:

    O0 = O if it exists, otherwise P'               (start from the price published at the previous update)
    dt = (t - t') / 1000
    w  = 1 - exp(-min(dt, 180) / 1800)
    m  = mid if both sides of the book are present, otherwise the last two-sided mid, otherwise O0
    O1 = O0 + w x clip(m - O0, -0.01 x O0, +0.01 x O0)
    V  = clip(nearest(O1), up(E(1 - d)), down(E(1 + d)))
    O  = clip(O1, E(1 - d), E(1 + d))
    P' = V

The internal price already takes one step at the first update that is not live.

**Step 3. The average A.**

    dt = (t - t') / 1000
    A~ = A + (1 - exp(-dt / 1800)) x (V - A)         (first update ever: A~ = V)

    if a previous mark M' exists and B' is NOT strictly between V' and A':
        A = clip(A~, min(V, M'), max(V, M'))
    else:
        A = A~

"Strictly between" is min(V', A') < B' < max(V', A'), with V' and A' as they were published. When V' = A' the test
is false, so the clip applies. V in the clip is the current V; M' is the previous mark. There is no cap on dt here.

**Step 4. Publish** V and A rounded to 1e-6 USD, set t' = t.

**Step 5 (Hyperliquid, unchanged).** With the two inputs and its own book:

    B = median(bid, ask, last)
    M = clip(median(V, A, B), lo, hi)
    lo = M' x 0.99 and hi = M' x 1.01, each rounded to the nearest 10^-(6 - szDecimals)   (SK Hynix: 0.001)

The rounding of lo and hi is what the engine does; see section 10, item 2.

## 6. Special cases

**Scheduled closure.** The feed is not live for the whole closure, whatever E does. On entering it, the internal price
starts from the price published at the update before (or simply continues, if E had already repeated twice). A change
of E inside a closure does not restart the internal price; it only moves the bound E(1 +- d). At the end of a closure
the feed is live again only once n < 2: if E is still repeating, the internal price continues until E changes.

**The external price repeats.** Updates 1 and 2 with the same E: V = E. From the third on: V is the internal price,
starting from E rounded to the grid and already one step toward the book mid.

**The external price jumps (outside a closure).** Any change of E makes the feed live at that update: V = E at once,
whatever the size of the change, and the internal price is dropped. The next time the feed is not live, the internal
price starts from the newly published value. Confirmed in the code, with the closure exception above. A is not
restarted: it continues its 30-minute average toward the new V.

**Restart of the relayer.** The engine has no restart. At its own start it behaves as in the "Initial value" column:
A = the first V, n = 0, no internal price, no correction step at the first update. A relayer that restarts with this
state publishes A = V, so the mark becomes V on that update (within Hyperliquid's 1%). If that is not wanted, A has to
be stored or rebuilt; the engine does not say how.

**One side of the book empty.** The book price is the lone quote. The internal price keeps using the last mid seen
while both sides were present, however old. Not exercised by the test vector (both sides and a last trade are present
on all 29,010 updates).

**Both sides empty, or no trade yet.** The engine gives no book price whenever bid and ask are both missing, and also
when both are present but there has been no trade. With no book price there is no mark at that update; at the next
update the correction step of A is skipped and Hyperliquid's 1% limit is not applied, because both need a previous
mark. Not exercised by the test vector.

## 7. Hyperliquid's part

Unchanged: mark = median of the two published inputs and the book price, moved at most 1% per update from the previous
mark. The proposal needs no new field and no new rule on Hyperliquid's side, subject to section 10, item 1 (whether an
input with six decimals is accepted).

## 8. Checked against the replay

`python three_vote_reference.py` reads the update time, E, bid, ask and last from the test vector, the closure list and
the maximum leverage, and prints:

Run 1: from the first update at which the engine applies the whole rule (row 7239 of 29,010, block 1087720890,
06:00:00.689 UTC), with A, V', A', B', M' taken from row 7238.

| | Updates | Exact | Within one tick | Largest difference |
|---|---|---|---|---|
| V | 21,772 | 100% | 100% | 0 |
| A | 21,772 | 99.9633% (8 differ) | 100% | 0.000001 at 06:00:12.662 |
| Mark, 1% bounds rounded (the engine's rule) | 21,772 | 99.8392% (35 differ) | 100% | 0.000836 at 23:00:24.685 |
| Mark, 1% bounds not rounded (how the test vector's column was built) | 21,772 | 99.9770% (5 differ) | 100% | 0.000001 at 06:00:12.662 |
| V, 22:55 to 23:10 UTC | 300 | 100% | 100% | 0 |
| A, 22:55 to 23:10 UTC | 300 | 100% | 100% | 0 |
| Mark, bounds rounded, 22:55 to 23:10 UTC | 300 | 90% (30 differ) | 100% | 0.000836 at 23:00:24.685 |
| Mark, bounds not rounded, 22:55 to 23:10 UTC | 300 | 100% | 100% | 0 |

Run 2: from the first row of the file (00:01:46.062 UTC), with no value taken from the engine, and with step 1 switched
off before 06:00 UTC as in the engine (section 10, item 3).

| | Updates | Exact | Largest difference |
|---|---|---|---|
| V | 29,010 | 100% | 0 |
| A | 29,010 | 100% | 0 |
| Mark, 1% bounds rounded | 29,010 | 99.8966% (30 differ) | 0.000836 at 23:00:24.685 |
| Mark, 1% bounds not rounded | 29,010 | 100% | 0 |

"Exact" means equal to the published 1e-6 USD. One tick is 0.1 at this price, so "within one tick" says little for A
and the mark; the exact column is the one to read.

What the test vector exercises (from 06:00 UTC): 17,322 updates not live (14,400 in the closure, 2,922 from a repeated
E), 733 starts of the internal price, the 1% gap limit active on 4,910 updates, the correction step moving A on
2,061 updates and skipped on 7,873 because the book was between, E changing inside the closure on 4 updates,
Hyperliquid's 1% limit active on 31 updates (23:00:12 to 23:02:45 UTC).

What it does not exercise: the bound E(1 +- d) (largest distance of V from E: 8.28% at 17:17 UTC, against 10%); the 180 s
cap on the time step (longest gap between updates: 4.5 s); an empty side of the book; a read delay on an update that is
not live; a restart.

## 9. Not exact, and why

1. **The mark column of the test vector.** It was rebuilt with 1% bounds that are not rounded; the engine rounds them
   to 0.001. The two differ on 30 updates between 23:00:15 and 23:02:46 UTC, by at most 0.000836. V and A are the same under
   both on this day. The engine does not write its own mark to the file, so the engine's mark is checked only through
   A (the correction step reads it).
2. **Starting in the middle (run 1).** The file has A rounded to 1e-6; the engine's unrounded A is not available. This
   gives 8 differences of 0.000001 in A in the first 75 seconds, and 5 in the mark. Run 2 has none.
3. **The read delay.** The engine lets the relayer read the book mid as of an earlier update when the recorded tape
   shows a delay of two updates. The test vector does not carry this delay. It occurs on 2 updates (23:00:06.653 and
   23:02:06.689 UTC), both live, so the mid was not used and nothing differs. On a day where a delayed update is not
   live, the reference would use the current mid and the engine the previous update's.
4. **The book mid between updates.** Not a difference: the internal price reads the mid once per update, at the
   update's time. On all 17,322 updates that are not live, the mid of the test vector's row gives the
   engine's V exactly. The mid sampled every 500 ms inside the engine feeds only today's second input.
5. **An empty side of the book between two updates.** The engine keeps the last two-sided mid seen at any block; the
   reference keeps the last one seen at an update. They can differ if a side empties between updates. Not present on
   this day.
6. **Floating point.** exp and the products are in double precision in both. An implementation in fixed point or with
   another exp may differ by 0.000001 in A now and then. None seen between Rust and Python here.
7. **What a real relayer can read.** The engine gives the relayer the book mid at the instant its update executes,
   the block time as its clock, and the book price and mark exactly as Hyperliquid computed them at the previous
   update. A real relayer reads these a moment earlier. The specification cannot remove this; it is the same kind of
   error the fitted residuals absorb for today's rules.
8. **Maximum leverage.** Passed to the engine on the command line; 10 is taken from the metadata. The bound never acts
   on this day, so the numbers do not confirm it.

## 10. Engine behavior an implementer might not expect

1. **A is published with six decimals, off the price grid** (14,675 of 29,010 updates). Nothing in the engine rounds
   it to 5 significant figures. If Hyperliquid requires the inputs on the grid, A must be rounded, and then the
   "strictly between" test, the median and the match figures above all change. This needs a decision before
   implementation.
2. **Two versions of Hyperliquid's 1% limit exist in the repository**: the engine rounds the bounds to
   6 - szDecimals decimals (its comment cites real liquidation fills); the chart helper that built the test vector's
   mark column does not. Hyperliquid knows which is right.
3. **The proposal is not "the recorded tape" before 06:00 UTC.** From the first row of the file the engine already
   publishes V = E and A = the 30-minute average with its correction step, and builds the mark from them. Only step 1
   (closures and repeats) and the internal price start at 06:00:00.689 UTC (row 7239). Before that, E repeats twice or
   more on 341 updates and V stays E. The recorded first input equals V on 7,193 of the 7,238 earlier rows; the
   recorded second input never equals A.
4. **A change of E inside a scheduled closure does not restart the internal price** (4 updates on this day). The
   summary's "when it jumps, the internal price restarts" holds only outside closures.
5. **At the end of a closure, the first changed E is taken at once.** The closure ended at 23:00:00.000 UTC; E was still repeating
   (1,113.6), so V stayed the internal price (1,131.3) at 23:00:00.748. At 23:00:03.946 E arrived at 868.18 and V
   became 868.18 on that update. This is the rule as written (a changed E is
   live), and it is the start of the event in the test vector.
6. **With no book price the engine has no mark, it does not hold the previous one.** The update after it has no 1%
   limit and no correction step. The chart helper holds the mark instead. Also, with both quotes present but no trade
   yet, the engine has no book price while the chart helper uses the bid.
7. **An empty side freezes the mid the internal price follows**, at the last two-sided value, with no time limit.
8. **The two time steps are treated differently.** The internal price counts at most 180 s per update; the average A
   counts the whole gap. After a long gap between updates A moves most of the way to V in one step.
9. **"Repeats" compares the received values exactly**, not the values rounded to the grid.
10. **The live V bypasses the relayer's own output.** The engine's relayer computes E rounded to the grid and bounded;
    the proposal's code then replaces it with E as received. Same number whenever E is on the grid.
11. **A starts equal to the first V** and the correction step is skipped at the first update. See "Restart" in section 6.
