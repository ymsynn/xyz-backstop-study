"""Reproducible outputs for the prep pipeline: the same inputs give byte-identical files on any machine and thread count.
(tools/determinism_check.sh builds one coin-day with 1, 4 and 8 polars threads and compares every file.)

Loaded by path from each pipeline script (they run with python -I, which keeps the script directory off sys.path):
    detio = load("detio.py")          # see the two-line loader at the top of each script
Importing it replaces pl.DataFrame.write_ipc by a canonical writer:
  - one record batch (polars otherwise writes one per in-memory chunk, and chunks follow the thread count);
  - no validity bitmap on a column without nulls (polars keeps or drops an all-valid bitmap depending on the code path
    that built the column, so equal frames could differ in bytes).
ssum / fsum_by: exactly-rounded float sums (math.fsum). The result does not depend on the order of the rows; polars' own
sum adds in thread-dependent chunks, which moved fee rates in the last digit between runs.
Row order is each script's job: every sort that can tie is stable or keyed to a total order, and group_by / unique keep
the input order where a later step reads it."""
import math
import polars as pl

def canon(df: pl.DataFrame) -> pl.DataFrame:
    df = df.rechunk()
    out = []
    for s in df.get_columns():
        if s.null_count() == 0 and (s.dtype.is_numeric() or s.dtype == pl.Boolean) and not s.dtype.is_decimal():
            s = pl.Series(s.name, s.to_numpy(), dtype=s.dtype)          # rebuilt from the values: no bitmap
        elif s.null_count() == 0 and s.dtype == pl.String:
            s = pl.Series(s.name, s.to_list(), dtype=pl.String)
        out.append(s)
    return pl.DataFrame(out)

if not getattr(pl.DataFrame.write_ipc, "_canonical", False):     # once per process, however many scripts load this
    _write_ipc = pl.DataFrame.write_ipc
    def _canonical_write_ipc(self, file, *a, **k):
        return _write_ipc(canon(self), file, *a, **k)
    _canonical_write_ipc._canonical = True
    pl.DataFrame.write_ipc = _canonical_write_ipc

def ssum(s: pl.Series) -> float:
    return math.fsum(x for x in s.to_list() if x is not None)

def fsum_by(df: pl.DataFrame, keys, cols) -> pl.DataFrame:
    """per-group exact sums of float columns, one row per group, sorted by the keys"""
    g = df.group_by(keys, maintain_order=True).agg([pl.col(c) for c in cols]).sort(keys)
    return g.with_columns([pl.col(c).map_elements(lambda s: math.fsum(x for x in s if x is not None), return_dtype=pl.Float64) for c in cols])
