# trade.xyz backstop study

Suggestions for how trade.xyz prices and liquidates positions on Hyperliquid in stressed markets, studied from outside,
together with the replay engine and data pipeline that produced every number in them.

**[Rule explorer](https://ymsynn.github.io/xyz-backstop-study/)**: recorded market days replayed under today's rules
and the suggested ones, on the same charts. Pick a test, change a part of the formulas and compare, in the browser.

| Document | What it is |
|---|---|
| [docs/mark_formulas.pdf](docs/mark_formulas.pdf) | The paper: six suggestions, the tests, what they cost and what the study cannot tell (30 pages). Every rule, today's and the suggested one, is side by side on page 13. |
| [docs/variant_history.pdf](docs/variant_history.pdf) | A companion note: the variants tried before the proposal and why each was not kept. The paper does not depend on it. |
| [docs/formulas_now_vs_proposal.pdf](docs/formulas_now_vs_proposal.pdf) | One page: today's formulas and the suggested ones side by side, with every changed term highlighted. |
| [docs/spec/proposal_spec.md](docs/spec/proposal_spec.md) | The specification of the two values the relayer would publish, with a reference implementation and a test vector. |
| [docs/results/](docs/results/) | The result tables behind the paper, one file per test. |

## The suggestions in one paragraph

Today the prices trade.xyz publishes follow the external price in steps of 0.5% per update, so in a fast move the mark
arrives about a minute late, and a single wrong external price moves it on its own. The main suggestion is for the
mark (changes 1 and 2): the mark becomes the middle of three votes, the external price, a 30-minute anchor of it, and
xyz's own order book; and one capped rule prices the market whenever the external price is not live. Both are changes
to what trade.xyz's relayer publishes; Hyperliquid's own mark formula is unchanged. Four further suggestions have less
evidence behind them: a liquidation size that cuts a large position back to its initial margin (change 3, a Hyperliquid
change), a candidate list of six more markets for the backstop vault (4), a daily floor for the vault's capital (5),
and three items for the external price (6). In the paper, *the proposal* means changes 1 to 3, which were replayed
together.

## Results

Replayed on about 85 recorded market-days, under today's rules and under the proposal, with one build of the engine.
Today's figure comes first. The full table is in [docs/results/scorecard.md](docs/results/scorecard.md).

| Test | Today | Proposal |
|---|---|---|
| A 5% wrong external price for 30 seconds (Alphabet): how far the mark moves | 4.17% | 0.10% |
| The same test: healthy positions handed to the vault | $920k | $0 |
| Order-book push for 15 minutes while crude oil's market is closed: how far the mark moves | 6.56% | 0.81% |
| Five replays of isolated-only markets: ADL | $300.4k | $99.5k |
| Three earnings crashes together: money the vault needs to avoid ADL | $462k | $352k |
| Takeovers by the vault on two oil markets, September 10 | 95 | 13 |
| Takeovers by the vault on five other market-days held out of the design | 8 | 11 |
| Alphabet's earnings crash: positions the vault inherits | $6.96M | $10.28M |
| External price walked 10% overnight, with a push on xyz's book: positions liquidated | $15.5M | $16.0M |
| 33 markets on November 5: ADL on isolated-only markets | $154k | $64k |

## What it costs

The paper lists every case where the proposal does worse than today, does no better, or was not tested (page 21), and
the limits of the study (page 22). The main ones:

- **In most tests the vault inherits more than today** (Alphabet's crash: $6.96M today, $10.28M). It inherits less on
  Intel, on Amazon within the replay's error, and on the two oil markets of September 10.
- **When a market's venue is closed, the mark can sit above xyz's book for hours** (SK Hynix, July 27: up to 7.03%).
  The replay of that day is indeterminate: its result rests on a recorded book that today's rule had held in place.
- **A walked external price combined with a push on xyz's book does as much harm as today, or more.** A wrong price
  that lasts moves the mark slowly, not at all only when it is short.
- **The cut-back needs a Hyperliquid change**, and on its own it is not shown to do better than today.
- **The replay does not model market makers reacting** to a wrong published price, uses a reconstruction of today's
  relayer, and was tuned on the same days it was tested on, apart from the held-out and random ones.

## Layout

| Path | What it is |
|---|---|
| `engine/` | The replay engine (Rust): Hyperliquid's matching, margin, liquidation and backstop rules, and a model of trade.xyz's relayer. A suggested rule is a switch in this engine. |
| `sim/` | `pipe_day.sh`, which builds one replayable market-day by calling the steps in `sim/prep/`; `pkgm_env.zsh`, the proposal's engine settings; `figs.py`, every figure of the paper; `times.zsh`, the moments of the replayed market-days; `registry.py` and `detio.py`, shared by the rest. |
| `sim/prep/` | The steps of that pipeline: the extract tables and the chain's own records in, one typed, pre-sorted market-day out. |
| `sim/runs/` | The test runners: a market-day replayed under one or more rule sets (crashes, walked feeds, wrong prices, ordinary sessions). |
| `sim/score/` | The scorers: they read a replay's output and print the numbers the paper quotes. |
| `sim/study/` | Standalone studies behind changes 4 to 6: vault capital, which markets qualify for cross margin, the quality of the external price, the ADL record. |
| `sim/final/` | The run behind the paper: `run_final.sh` (every test, under today's rules and the proposal), `score_final.py`, the random sample, and the tests added afterwards. |
| `ec2/` | Jobs that read the raw archives in AWS Tokyo, where they live, and build market-days. Each terminates its own instance. |
| `tools/` | A memory guard and the reproducibility check. |
| `viewer/` | The rule explorer: a page that stacks replays of different rule combinations on the same charts. |
| `docs/` | The paper and the companion note (LaTeX and PDF), the figures, the specification, and the result tables. |
| `archive/` | Earlier designs, their scripts and the dated test journals. Kept as a record of what was tried; nothing above depends on it. |

## Reproducing the results

[REPRODUCE.md](REPRODUCE.md) has the data to get, where it lives, where to put it and the commands, written so that a
person or an automated agent can follow it top to bottom. In short:

1. Build the market-days from the two raw archives with the jobs in `ec2/` (a few hours, about $10 of AWS).
2. Fetch the rebuilt market-days and run `zsh sim/final/run_final.sh` (about an hour and a half on eight cores).
3. Score with `python sim/final/score_final.py` and compare with `docs/results/scorecard.md`.
4. Run the tests added after the final run (section 5 of REPRODUCE.md).

The pipeline is deterministic: the same inputs give byte-identical market-days whatever the number of processor
threads, and `tools/determinism_check.sh` verifies it.

## Checking the suggested mark without the engine

`docs/spec/three_vote_reference.py` is a short implementation of the two published values in plain Python, with no
dependency. It reproduces the engine's output on every one of the 29,010 updates of SK Hynix, July 27:

```bash
python3 docs/spec/three_vote_reference.py
```

## Rule explorer

**[ymsynn.github.io/xyz-backstop-study](https://ymsynn.github.io/xyz-backstop-study/)**: the explorer, online. `viewer/index.html` compares combinations of rules on the same charts: the mark and its gap to the external price, the
liquidations, the inputs of the mark, and a table of figures. Pick a test, change a part of the formula (how long the
anchor averages, the correction step, the liquidation sizing), and add the combination to your list. Today's rules and
the proposal are there from the start; the list is kept in your browser.

```bash
open viewer/index.html
```

The page computes nothing. Every line is a replay the engine ran, exported to `viewer/data/` by
`python viewer/build_data.py`; a combination that was not replayed cannot be picked. Today's rules and the proposal come
from `data/scen/final`, the other combinations from `zsh viewer/run_grid.sh` and `zsh viewer/run_attacks.sh`. The chart
and formula libraries (uPlot, KaTeX) are loaded from public CDNs, so the page needs a network connection.

## Names used in the code

The result tables say *today* and *proposal*. Inside the scripts and in output file names the two rule sets carry
short ids:

| In tables | Mark runs (`MARKS=`) | Liquidation replays (`DES=`) | Meaning |
|---|---|---|---|
| today | `today` | `today` | The rules deployed now, as we reconstruct them |
| proposal | `pkgm3q1800` | `lead3q1800` | The three-vote mark with a 30-minute anchor and the correction step, the capped rule when the external price is not live, and the cut-back |

`sim/pkgm_env.zsh` maps each id to the engine's settings: the proposal is five settings, and removing any one changes
the replay. Other letters and numbers in an id are the variants of the rule explorer (`k` no correction step, `r`
correction step always on; `300`, `7200` the anchor's averaging time in seconds; `s20` today's liquidation sizing).
