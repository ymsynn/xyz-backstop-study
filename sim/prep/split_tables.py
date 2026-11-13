"""Split a day's extract tables by asset once, so each coin's pipeline (sim/pipe_day.sh) reads only its own rows.

The tables are written in stream (time) order, so every `scan_parquet(...).filter(a == ASSET)` in oidbind, prep, prio,
silent (x4) and margin decodes the whole file: ~14 full scans of orders + cancels per coin. Here each coin's orders and
cancels are written once, row order kept (the pipeline indexes orders by row: seq). Every other table is linked, not
copied: state (crossacc reads other assets' rows), acts, blocks, oracle; the per-coin outputs written later (ledger,
oid_bind) land in the coin's own directory, never through a link.
Memory: one streaming pass per coin and table (scan, filter, sink), a few coins at a time. Loading every coin at once
needed more than 256 GB on the full 2026-11-05 day.
Check: each coin's row count equals the filtered count of the full table.
Usage: python sim/prep/split_tables.py TABLES_DIR OUT_ROOT COIN/ASSET[,COIN/ASSET...]  -> OUT_ROOT/{COIN}/*.parquet"""
import os, sys
import polars as pl


def one(job):
    T, OUT, name, c, a = job
    out = f"{OUT}/{c}/{name}.parquet"
    pl.scan_parquet(f"{T}/{name}.parquet").filter(pl.col("a") == a).sink_parquet(out, row_group_size=200_000)
    return name, c, a, pl.scan_parquet(out).select(pl.len()).collect().item()


if __name__ == "__main__":
    import multiprocessing as mp
    T, OUT, spec = sys.argv[1:4]
    coins = [(s.split("/")[0], int(s.split("/")[1])) for s in spec.split(",")]
    for c, _ in coins:
        os.makedirs(f"{OUT}/{c}", exist_ok=True)
    for name in ("state.parquet", "acts.parquet", "blocks.parquet", "oracle.parquet"):   # only the shared inputs: a link to an
        if os.path.exists(f"{T}/{name}"):                                                  # output would be written through
            for c, _ in coins:
                dst = f"{OUT}/{c}/{name}"
                if not os.path.lexists(dst): os.symlink(os.path.abspath(f"{T}/{name}"), dst)
    want = {name: dict(pl.scan_parquet(f"{T}/{name}.parquet").group_by("a").len().collect().iter_rows()) for name in ("orders", "cancels")}
    procs = max(1, min(int(os.environ.get("SPLIT_PROCS", "8")), len(coins)))
    os.environ["POLARS_MAX_THREADS"] = str(max(1, (os.cpu_count() or 1) // procs))   # read by the workers at import
    jobs = [(T, OUT, name, c, a) for name in ("orders", "cancels") for c, a in coins]
    got = {}
    with mp.get_context("spawn").Pool(procs) as pool:        # spawn: polars' thread pool does not survive a fork
        for name, c, a, n in pool.imap_unordered(one, jobs):
            assert n == want[name].get(a, 0), (name, c, n, want[name].get(a, 0))
            got[(name, c)] = n
    for name in ("orders", "cancels"):
        print(name, sum(got[(name, c)] for c, _ in coins), "rows ->", ", ".join(f"{c} {got[(name, c)]}" for c, _ in coins[:8]), "...")
    print("SPLIT DONE")
