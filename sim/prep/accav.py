"""Account values for the engine's sanity cap on triggered orders.

Usage: python accav.py PREP_DIR GLOBAL_DIR GLOBAL_NEXT_DIR
Writes PREP_DIR/acc_av.arrow (u, av): each prep user's xyz account value, the larger of the day's two snapshots (0 when
absent from both). The engine rejects a triggered order whose opening notional exceeds ORDER_CAP_X (default 5) x max
leverage x max(av, $1,000): an order no account could margin (INTC: ~$27.6B of $10 buy triggers from accounts holding
$1.4k or nothing). Real trigger fills open at most 26.6x account value (GOOGL), far under the cap.
"""
import sys, glob
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, G, GN = sys.argv[1:4]
users = pl.read_ipc(f"{PREP}/users.arrow")
av = lambda d: (pl.scan_parquet(glob.glob(f"{d}/account_values/*.parquet")[0]).filter(pl.col("dex") == "xyz")
                .select("user", "account_value").collect())
x = (users.join(av(G).rename({"account_value": "a0"}), on="user", how="left").join(av(GN).rename({"account_value": "a1"}), on="user", how="left")
     .select(pl.col("uid").alias("u"), pl.max_horizontal(pl.col("a0").fill_null(0.0), pl.col("a1").fill_null(0.0)).alias("av")))
x.write_ipc(f"{PREP}/acc_av.arrow")
print(f"{PREP}: {x.height} accounts, {x.filter(pl.col('av') > 0).height} with an account value")
