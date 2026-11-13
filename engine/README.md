# engine: xyz HIP-3 market simulator (Rust)

Rust port of the validated Python replay (`../replay_v1/`) and account replay (`../archive/sim/clearinghouse.py`). This is the engine Phase 2b and the counterfactual sweeps build on.

## Build and run

```bash
cargo build --release
# 1. prep (Python/polars, once per coin-day): extract tables -> typed, pre-sorted Arrow IPC
python ../sim/prep/prep.py TABLES FILLS OB1M LIQ "SNAP_GLOB" xyz:GOOGL 110012 PREP_DIR
# 2. book replay + mark check
./target/release/engine replay PREP_DIR [tape_walk|engine]
# 3. book + mark + account state + liquidation triggers
./target/release/engine accounts PREP_DIR 20 reduce=keep        # rules: fee_iso, reduce, liq_reduce, lev_change
```

## Parity with the Python reference (xyz:GOOGL 2026-10-28)

- **`replay tape_walk`:** every check is identical to `replay_v1`:
  - echo 320,481 / 3,219;
  - cancels 876,629 / 2,675;
  - user-taker size 0.9737 (day) and 0.9724 (18:00–22:00);
  - pruned 2,176 + 2,013;
  - 1-min book 2,859/15, 2,716/158 and 2,836/38;
  - marks 98/101.
- **`replay engine`:** identical to within ties between duplicate synthetic oids (e.g. inject found 8,394 vs 8,398 in the window; matched 0.8623 vs 0.8622).
- **`accounts`:** identical to `clearinghouse.py reduce=keep`:
  - 137 takeovers, positions 100% exact, median error $0.00, 85% within $1;
  - triggers 672 / 617 / 608, 94.2% same block, 64 missed, 9 false.
  - Only the p90 label differs ($4.75 vs $4.17): nearest-rank vs interpolated percentile.

## Cost

| Run | Python | Rust |
|---|---|---|
| Book replay | 56 s, 3.5 GB | 3.0 s, 236 MB |
| Book + accounts | ~84 s total | 5.1 s, 188 MB |

`prep.py` still peaks at ~5 GB once per coin-day; switching it to lazy / streaming polars is a later step.

## Layout

- `src/book.rs`: order book (slab + lazy deletion, integer px/sz).
- `src/replay.rs`: block replay, checks, relayer-update log, mark.
- `src/clearing.rs`: accounts, takeover scoring, triggers.
- `src/io.rs`: Arrow IPC readers.
