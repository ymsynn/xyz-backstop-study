"""Prep for the Rust engine: one coin-day of extract tables -> compact, typed, pre-sorted Arrow IPC files.

In-block execution order (2026-11-03, replaces replay_v1's orders_first_bundle): per bundle, post-only (Alo) placements,
then cancels (by oid / cloid), then everything else (other orders, scheduleCancel, relayer updates) in action order.
Was mirroring replay_v1/replay_book.py (ORDERING=orders_first_bundle, oracle events with the non-order actions,
status-driven classification), so the Rust engine reproduces the frozen numbers.

Usage: python prep.py TABLES FILLS OB1M LIQ SNAP_GLOB COIN ASSET OUT_DIR
Writes OUT_DIR/{events,real_fills,inject,seeds,blocks,l2,liqmarks,users, acc_init,acc_events,ledger}.arrow
Prices / sizes are i64 scaled by 1e6. Users are u32 ids (users.arrow maps them back).
"""
import sys, os, json, glob, resource
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)
ssum, fsum_by = detio.ssum, detio.fsum_by


def mem(tag):  # peak RSS so far (macOS ru_maxrss is in bytes)
    print(f"  [mem] {tag}: peak {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30:.2f} GB", flush=True)

T, FILLS, OB1M, LIQ, SNAP, COIN, ASSET, OUT = sys.argv[1:9]
SNAP_NEXT = sys.argv[9] if len(sys.argv) > 9 else None
META_JSON = os.environ.get("XYZ_META")   # dex meta (metaAndAssetCtxs) for szDecimals
ASSET = int(ASSET)
os.makedirs(OUT, exist_ok=True)
SC = 10**6
q = lambda c: (pl.col(c).cast(pl.Float64) * SC).round(0).cast(pl.Int64)

blocks = pl.read_parquet(f"{T}/blocks.parquet").select("h", (pl.col("t").cast(pl.Int64) // 10**6).alias("ms")).sort("h")
TAG = COIN.split(":")[1]
def ledger_file(name):  # per-coin ledger files (ledger.py), falling back to the old unsuffixed name
    f = f"{T}/{name}_{TAG}.parquet"
    return f if os.path.exists(f) else f"{T}/{name}.parquet"
import datetime as _dt
_day = _dt.datetime.fromtimestamp(int(blocks["ms"].median()) / 1000, _dt.timezone.utc).date()
W0_MS = int(_dt.datetime(_day.year, _day.month, _day.day, 18, tzinfo=_dt.timezone.utc).timestamp() * 1000)
W1_MS = W0_MS + 4 * 3600 * 1000
blocks.write_ipc(f"{OUT}/blocks.arrow")
h_of_ms = dict(zip(blocks["ms"].to_list(), blocks["h"].to_list()))

# ---------------------------------------------------------------- users / cloids dictionaries
# Bounded memory: orders and cancels (tens of millions of rows of strings) are never materialized; the event table is
# built as one lazy plan (string -> int ids through joins against small lookup tables) and streamed to disk.
OCOLS = ["h", "b", "i", "j", "u", "type", "oid_in", "side_buy", "px", "sz", "reduce_only", "tif", "trigger", "grouping", "cloid", "status", "oid", "filled_sz", "err"]
CCOLS = ["h", "b", "i", "j", "u", "type", "oid", "cloid", "status"]
TMPD = os.path.join(OUT, "_tmp"); os.makedirs(TMPD, exist_ok=True)
# pa: the execution group of the order's whole action (ec2/extract.py act_pri). Tables made before 2026-11-10 lack it
HAS_PA = "pa" in pl.scan_parquet(f"{T}/orders.parquet").collect_schema().names()
if HAS_PA: OCOLS = OCOLS + ["pa"]
pl.scan_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET).select(OCOLS).sink_parquet(f"{TMPD}/orders.parquet", row_group_size=200_000)
pl.scan_parquet(f"{T}/cancels.parquet").filter(pl.col("a") == ASSET).select(CCOLS).sink_parquet(f"{TMPD}/cancels.parquet", row_group_size=200_000)
N_ORD = pl.scan_parquet(f"{TMPD}/orders.parquet").select(pl.len()).collect().item()
N_CAN = pl.scan_parquet(f"{TMPD}/cancels.parquet").select(pl.len()).collect().item()
orders_lf = pl.scan_parquet(f"{TMPD}/orders.parquet").with_row_index("seq")
cancels_lf = pl.scan_parquet(f"{TMPD}/cancels.parquet")
mem("after per-asset copies")
FCOLS = ["coin", "price", "size", "side", "timestamp", "direction", "order_id", "trade_id", "fee", "builder_fee", "address", "crossed", "twap_id", "liquidation_mark_px", "liquidation_method", "is_liquidation"]
# the tape runs a few minutes past midnight: the next day's fills up to the tape's last block belong to it
_FN = sys.argv[10] if len(sys.argv) > 10 else None
_tape_end = blocks["ms"].max()
fills = (pl.concat([pl.scan_parquet(f).filter(pl.col("coin") == COIN).select(FCOLS) for f in [FILLS] + ([_FN] if _FN else [])])
         .with_columns(pl.col("timestamp").cast(pl.Int64).alias("ms"), pl.col("order_id").cast(pl.Int64).alias("oid"))
         .filter(pl.col("ms") <= _tape_end).unique(["trade_id", "crossed"], keep="first", maintain_order=True).collect())
book_users = orders_lf.select(pl.col("u").unique()).collect()["u"]
mem("after book users / fills")
sched = (pl.scan_parquet(f"{T}/acts.parquet").filter(pl.col("type") == "scheduleCancel", pl.col("u").is_in(book_users.implode()))
         .select("h", "b", "i", "u", "time").collect())
snap = pl.scan_parquet(SNAP).filter(pl.col("market") == COIN).collect()
all_users = sorted(set(book_users.to_list()) | set(cancels_lf.select(pl.col("u").unique()).collect()["u"].to_list())
                   | set(fills["address"].to_list()) | set(snap["user"].to_list())
                   | set(pl.scan_parquet(f"{T}/state.parquet").filter(pl.col("asset") == ASSET).select("u").unique().collect()["u"].to_list())
                   | set(pl.read_parquet(ledger_file("funding"))["user"].unique().to_list()))
uid = {u: k for k, u in enumerate(all_users)}
uid_tab = pl.DataFrame({"u": all_users, "uid": list(range(len(all_users)))}, schema={"u": pl.String, "uid": pl.UInt32}).lazy()
pl.DataFrame({"uid": list(range(len(all_users))), "user": all_users}, schema={"uid": pl.UInt32, "user": pl.String}).write_ipc(f"{OUT}/users.arrow")
U = lambda c: pl.col(c).replace_strict(uid, return_dtype=pl.UInt32)       # for the small frames only
mem("after user set")
# client order ids -> u64 by hashing inside polars (no string lookup table; 64-bit collisions negligible), 0 = none
HC = lambda e: pl.when(e.is_null()).then(pl.lit(0, pl.UInt64)).otherwise(e.hash(seed=7))
mem("after cloid table")


# ---------------------------------------------------------------- oid resolution (known / bound / synthetic)
bind = pl.scan_parquet(f"{T}/oid_bind_{COIN.split(':')[1]}.parquet").select(pl.col("seq").cast(pl.UInt32), pl.col("oid").alias("boid"))
orders_lf = orders_lf.join(bind, on="seq", how="left").with_columns(
    pl.coalesce(pl.col("oid").cast(pl.Int64), pl.col("boid"), -(pl.col("seq").cast(pl.Int64) + 1)).alias("roid"))
small = orders_lf.select("roid", pl.col("trigger").is_not_null().alias("is_trig"), pl.col("oid").cast(pl.Int64)).collect()
sim_taker = small.filter(~pl.col("is_trig"))["roid"]
trig = small.filter(pl.col("is_trig"))["roid"]
first_oid = small["oid"].drop_nulls().min()
del small
# normalTpsl children (waitingForFill) activate when their parent order fills: parent = the non-trigger sub-order of the
# same action
_wff = orders_lf.filter(pl.col("status") == "waitingForFill").select("seq", "h", "b", "i")
tparent = (_wff.join(orders_lf.join(_wff.select("h", "b", "i").unique(), on=["h", "b", "i"], how="semi")
                     .filter(pl.col("trigger").is_null()).group_by("h", "b", "i").agg(pl.col("roid").first().alias("tparent")),
                     on=["h", "b", "i"], how="left").select(pl.col("seq").cast(pl.UInt32), "tparent").collect())
mem("after oid resolution")

# status code (see engine/src/replay.rs): 0 PLACE 1 SKIP_NOPLACE 2 ALO_REJECT 3 IOC_NOMATCH 4 ERR_SKIP 5 MOD_OK 6 MOD_FAILPLACE 7 MOD_ERR
ECHO = r"bbo was ([0-9]+(?:\.[0-9]+)?)@([0-9]+(?:\.[0-9]+)?)"
st = (pl.when(pl.col("type") == "order").then(
        pl.when(pl.col("status").is_null()).then(1)
        .when(pl.col("status") == "error").then(
            pl.when(pl.col("err").str.starts_with("Post only")).then(2)
            .when(pl.col("err").str.starts_with("Order could not immediately match")).then(3).otherwise(4))
        .otherwise(0))
      .when(pl.col("type") == "modify").then(
        pl.when(pl.col("status").str.contains("Error placing new order during modify")).then(6)
        .when(pl.col("status").str.contains('"ok"')).then(5).otherwise(7))
      .otherwise(  # batchModify
        pl.when(pl.col("err").fill_null("").str.contains("Error placing new order during modify")).then(6)
        .when(pl.col("status") == "error").then(7).otherwise(0)))
tif = pl.col("tif").replace_strict({"Alo": 0, "Gtc": 1, "Ioc": 2, "FrontendMarket": 3}, default=4, return_dtype=pl.UInt8)
EV_SCHEMA = {"h": pl.Int64, "b": pl.Int64, "i": pl.Int64, "j": pl.Int64, "k": pl.UInt8, "seq": pl.Int64, "u": pl.UInt32, "ty": pl.UInt8,
             "oid_in": pl.Int64, "oid_in_cl": pl.UInt64, "buy": pl.Boolean, "px": pl.Int64, "sz": pl.Int64, "tif": pl.UInt8, "trg": pl.Boolean,
             "cl": pl.UInt64, "st": pl.UInt8, "oid": pl.Int64, "filled": pl.Int64, "e_bid": pl.Int64, "e_ask": pl.Int64, "x": pl.Int64,
             "ro": pl.Boolean}
cols = list(EV_SCHEMA)
zero = dict(seq=pl.lit(-1, pl.Int64), ty=pl.lit(0, pl.UInt8), oid_in=pl.lit(-1, pl.Int64), oid_in_cl=pl.lit(0, pl.UInt64),
            buy=pl.lit(False), px=pl.lit(0, pl.Int64), sz=pl.lit(0, pl.Int64), tif=pl.lit(4, pl.UInt8), trg=pl.lit(False),
            cl=pl.lit(0, pl.UInt64), st=pl.lit(0, pl.UInt8), oid=pl.lit(-1, pl.Int64), filled=pl.lit(-1, pl.Int64),
            e_bid=pl.lit(-1, pl.Int64), e_ask=pl.lit(-1, pl.Int64), x=pl.lit(-1, pl.Int64), ro=pl.lit(False))


def finish(lf, **over):
    z = dict(zero, **over)
    names = lf.collect_schema().names()
    return lf.with_columns(**{k: v for k, v in z.items() if k not in names}).select(cols).cast(EV_SCHEMA)


uid_u = uid_tab.rename({"uid": "u_id"})
TPX = (pl.col("trigger").str.json_path_match("$.triggerPx").cast(pl.Float64) * SC).round(0).cast(pl.Int64)
TFLAGS = ((pl.col("trigger").str.json_path_match("$.isMarket") == "true").cast(pl.Int64)
          + (pl.col("trigger").str.json_path_match("$.tpsl") == "tp").cast(pl.Int64) * 2
          + pl.col("reduce_only").fill_null(False).cast(pl.Int64) * 4
          + pl.col("grouping").replace_strict({'"na"': 0, '"normalTpsl"': 1, '"positionTpsl"': 2}, default=3, return_dtype=pl.Int64) * 8
          + (pl.col("status") == "waitingForFill").fill_null(False).cast(pl.Int64) * 32)
OEV_EXPR = [
    "h", "b", "i", "j", pl.lit(3, pl.UInt8).alias("k"), pl.col("seq").cast(pl.Int64), pl.col("u_id").alias("u"),
    pl.col("type").replace_strict({"order": 0, "modify": 1, "batchModify": 2}, return_dtype=pl.UInt8).alias("ty"),
    pl.when(pl.col("oid_in").str.contains(r"^[0-9]+$")).then(pl.col("oid_in").cast(pl.Int64, strict=False)).otherwise(-1).alias("oid_in"),
    pl.when(pl.col("oid_in").str.contains(r"^[0-9]+$")).then(pl.lit(0, pl.UInt64)).otherwise(HC(pl.col("oid_in"))).alias("oid_in_cl"),
    pl.col("side_buy").fill_null(False).alias("buy"), q("px").alias("px"), q("sz").alias("sz"), tif.alias("tif"),
    pl.col("trigger").is_not_null().alias("trg"), HC(pl.col("cloid")).alias("cl"), st.cast(pl.UInt8).alias("st"),
    pl.col("roid").alias("oid"), (pl.col("filled_sz").fill_null(-1.0) * SC).round(0).cast(pl.Int64).alias("filled"),
    # trigger rows reuse the echo columns: e_bid = triggerPx, e_ask = flags (bit 0 isMarket, 1 tp, 2 reduceOnly,
    # 3-4 grouping: 0 na / 1 normalTpsl / 2 positionTpsl / 3 other, 5 waitingForFill), x = parent oid (waitingForFill)
    pl.when(pl.col("trigger").is_not_null()).then(TPX).otherwise(
        ((pl.col("err").str.extract(ECHO, 1).cast(pl.Float64) * SC).round(0).cast(pl.Int64)).fill_null(-1)).alias("e_bid"),
    pl.when(pl.col("trigger").is_not_null()).then(TFLAGS).otherwise(
        ((pl.col("err").str.extract(ECHO, 2).cast(pl.Float64) * SC).round(0).cast(pl.Int64)).fill_null(-1)).alias("e_ask"),
    pl.col("tparent").fill_null(-1).cast(pl.Int64).alias("x"), pl.col("reduce_only").fill_null(False).alias("ro")]
CEV_EXPR = [
    "h", "b", "i", "j", pl.when(pl.col("type") == "cancel").then(0).otherwise(1).cast(pl.UInt8).alias("k"),
    pl.col("u_id").alias("u"), pl.col("oid").cast(pl.Int64).fill_null(-1).alias("oid"), HC(pl.col("cloid")).alias("cl"),
    pl.col("status").fill_null("").str.contains('"success"').cast(pl.Int64).alias("x")]
sev = finish(sched.lazy().select("h", "b", "i", pl.lit(0, pl.Int64).alias("j"), pl.lit(2, pl.UInt8).alias("k"), U("u").alias("u"),
                                 pl.col("time").cast(pl.Int64).fill_null(-1).alias("x")))
orc = pl.scan_parquet(f"{T}/oracle.parquet").filter(pl.col("coin") == COIN).collect().sort("h", "b", "i")
# relayer inputs for the engine's relayer simulation: external px, and the read lag k of each update (the relayer clamps
# against the oracle it last saw on-chain, S[n-k]; k inferred from the real outputs, held fixed across scenarios)
# the rule lives in relayer_lag.py: 50 bp clamp, exact grid rounding, external-price cap 1 / maxLeverage (from XYZ_META;
# MAX_LEV overrides; neither = no cap, and relayer_lag.py must be run after)
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("relayer_lag", os.path.join(os.path.dirname(os.path.abspath(__file__)), "relayer_lag.py"))
_rl = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_rl)
_un = {u["name"]: u for u in json.load(open(META_JSON))[0]["universe"]} if META_JSON else {}
_ml = float(os.environ.get("MAX_LEV") or _un.get(COIN, {}).get("maxLeverage", 0))
if not _ml: print("WARNING: no maxLeverage (XYZ_META / MAX_LEV): relayer lags inferred without the external-price cap")
_lag, _miss = _rl.read_lags(orc["oracle"].to_list(), orc["ext"].to_list(), _un.get(COIN, {}).get("szDecimals", 3), 0.005, 1.0 / _ml if _ml else 0.0)
print(f"relayer read lag: {_miss} updates no lag explains")
orc = orc.with_columns(pl.Series("lag", _lag, dtype=pl.UInt8), pl.col("ext").fill_null(pl.col("oracle")))
print("relayer read lag k distribution:", orc.group_by("lag").len().sort("lag").to_dicts())
rev = finish(orc.lazy().select("h", "b", "i", pl.lit(0, pl.Int64).alias("j"), pl.lit(5, pl.UInt8).alias("k"), pl.lit(0, pl.UInt32).alias("u"),
                               q("m1").alias("x"), q("m2").alias("px"), q("ext").alias("e_bid"), pl.col("lag").cast(pl.Int64).alias("e_ask"),
                               (pl.col("t").cast(pl.Int64) // 10**6).alias("filled")))
# every source is already in execution order: merge them on a packed key instead of sorting (streaming, bounded memory)
# key = ((h*64 + b)*4 + pri) * 2^24 + i * 2^10 + j   (b < 64, i < 2^14, j < 2^10: checked on the Oct 28/29 extracts)
# pri: 0 post-only placements, 1 cancels, 2 the rest. Post-only orders get their own stream (events_4) so that every
# stream stays sorted on the key (the engine merges them).
def key_fits(df, where):
    """The merge key packs b, i and j into bit fields. If any overflows, the streams merge in the wrong execution
    order and the replay is silently different, so check it rather than trust the bound."""
    mx = df.select(pl.col("b").max(), pl.col("i").max(), pl.col("j").max()).collect().row(0)
    assert mx[0] is None or (mx[0] < 64 and mx[1] < 1 << 14 and mx[2] < 1 << 10), f"event key overflow in {where}: b/i/j max {mx}"


KEY = lambda pri: ((((pl.col("h") * 64 + pl.col("b")) * 4 + pri) * (1 << 24)) + pl.col("i") * (1 << 10) + pl.col("j")).alias("key")
CHUNK_ROWS = 1_500_000


def orders_events(lf):
    return finish(lf.join(uid_u, on="u", how="left", maintain_order="left").select(*OEV_EXPR))


def cancels_events(lf):
    return finish(lf.join(uid_u, on="u", how="left", maintain_order="left").select(*CEV_EXPR))


for f_ in glob.glob(f"{OUT}/events_*.arrow"):
    os.remove(f_)
n_files = {0: 0, 1: 0}
for src, (n_rows, path) in enumerate(((N_ORD, f"{TMPD}/orders.parquet"), (N_CAN, f"{TMPD}/cancels.parquet"))):
    for c0 in range(0, max(n_rows, 1), CHUNK_ROWS):
        lf = pl.scan_parquet(path).slice(c0, CHUNK_ROWS)
        if src == 0:
            lf = (lf.with_row_index("seq", offset=c0)
                  .join(bind.filter(pl.col("seq").is_between(c0, c0 + CHUNK_ROWS - 1)), on="seq", how="left", maintain_order="left")
                  .join(tparent.lazy().filter(pl.col("seq").is_between(c0, c0 + CHUNK_ROWS - 1)), on="seq", how="left", maintain_order="left")
                  .with_columns(pl.coalesce(pl.col("oid").cast(pl.Int64), pl.col("boid"), -(pl.col("seq").cast(pl.Int64) + 1)).alias("roid")))
            # Hyperliquid runs a bundle's actions in three groups: order actions whose orders are ALL post-only, then
            # cancels, then the rest; an action mixing post-only and GTC / IOC orders runs after the cancels as a whole
            # (explorer_blocks lists the executed order: sim/prep/explorer_check.py, 455 blocks of 2026-11-05). FIRST = the
            # row's action is in the first group. Without pa (old tables) each row is judged on its own tif, as before.
            FIRST = (pl.col("pa") == 0) if HAS_PA else (pl.col("tif") == "Alo")
            ev_first, ev_last = orders_events(lf.filter(FIRST.fill_null(False))), orders_events(lf.filter(~FIRST.fill_null(False)))
        else:
            ev_ = cancels_events(lf)
        if src == 0:
            key_fits(ev_last, f"stream {src} chunk {n_files[src]}"); key_fits(ev_first, f"stream 4 chunk {n_files[src]}")
            # collect + the canonical write_ipc (sim/detio.py), not sink_ipc: the streaming writer cuts record batches by
            # thread count, so equal streams differed in bytes; a chunk is at most CHUNK_ROWS rows, memory stays bounded
            ev_last.with_columns(KEY(2)).collect().write_ipc(f"{OUT}/events_0_{n_files[src]:03d}.arrow", compression="lz4")
            ev_first.with_columns(KEY(0)).collect().write_ipc(f"{OUT}/events_4_{n_files[src]:03d}.arrow", compression="lz4")
        else:
            key_fits(ev_, f"stream {src} chunk {n_files[src]}")
            ev_.with_columns(KEY(1)).collect().write_ipc(f"{OUT}/events_{src}_{n_files[src]:03d}.arrow", compression="lz4")
        n_files[src] += 1
    mem(f"after events stream {src} ({n_files[src]} files)")
for _n, _d in ((2, sev), (3, rev)): key_fits(_d, f"stream {_n}")
lfs = [None, None] + [d.with_columns(KEY(2)) for d in (sev, rev)]
# one pre-sorted stream per source; the engine merges them on `key` while reading (bounded memory end to end)
for n in (2, 3):
    lfs[n].collect().write_ipc(f"{OUT}/events_{n}_000.arrow", compression="lz4")
import shutil; shutil.rmtree(TMPD)
if os.path.exists(f"{OUT}/events.arrow"):
    os.remove(f"{OUT}/events.arrow")
mem("after events sort+sink")
print("events", pl.scan_ipc(sorted(glob.glob(f"{OUT}/events_*.arrow"))).group_by("k").len().sort("k").collect().to_dicts())

# ---------------------------------------------------------------- trades: real fills of user takers, engine-taker injections, seeds
mk = fills.filter(~pl.col("crossed")).select("trade_id", "ms", pl.col("price").alias("px"), pl.col("size").alias("sz"), pl.col("oid").alias("m_oid"),
                                              pl.col("address").alias("m_u"), pl.col("side").alias("m_side"))
tk = fills.filter(pl.col("crossed")).select("trade_id", pl.col("oid").alias("t_oid"), "liquidation_method", pl.col("address").alias("t_u"), pl.col("side").alias("t_side"))
VAULT = "0x4000000000000000000000000000000000000001"
tr = (mk.join(tk, on="trade_id").filter(pl.col("liquidation_method").fill_null("") != "backstop")
      .with_columns(pl.col("ms").replace_strict(h_of_ms, default=None).alias("h")).filter(pl.col("h").is_not_null()))
real = tr.filter(pl.col("t_oid").is_in(sim_taker.implode())).sort("trade_id", maintain_order=True)
real.select("t_oid", "m_oid", q("sz").alias("sz"), "h", "ms", q("px").alias("px"), U("m_u").alias("m_u"), U("t_u").alias("t_u"),
            (pl.col("t_side") == "buy").alias("t_buy")).write_ipc(f"{OUT}/real_fills.arrow")
# real taker fills of trigger orders: the engine walks them when it fires the trigger itself (TRIGGERS=simulate)
tr.filter(pl.col("t_oid").is_in(trig.implode())).sort("trade_id", maintain_order=True).select(
    "t_oid", "m_oid", q("sz").alias("sz"), "h", "ms", q("px").alias("px"), U("m_u").alias("m_u"), U("t_u").alias("t_u"),
    (pl.col("t_side") == "buy").alias("t_buy")).write_ipc(f"{OUT}/trig_fills.arrow")
# per-user fee rates (fee / notional, taker and maker separately) for fills the simulator generates itself
fr = fills.with_columns((pl.col("price").cast(float) * pl.col("size").cast(float)).alias("ntl"), pl.col("fee").cast(float))
rates = fsum_by(fr, ["address", "crossed"], ["fee", "ntl"]).select("address", "crossed", (pl.col("fee") / pl.col("ntl")).alias("rate"))
tr_ = rates.filter(pl.col("crossed")).select("address", pl.col("rate").alias("taker"))
mr_ = rates.filter(~pl.col("crossed")).select("address", pl.col("rate").alias("maker"))
g_t = ssum(fr.filter(pl.col("crossed"))["fee"]) / ssum(fr.filter(pl.col("crossed"))["ntl"])
g_m = ssum(fr.filter(~pl.col("crossed"))["fee"]) / ssum(fr.filter(~pl.col("crossed"))["ntl"])
pl.DataFrame({"address": all_users}).join(tr_, on="address", how="left").join(mr_, on="address", how="left").select(
    U("address").alias("u"), pl.col("taker").fill_null(g_t), pl.col("maker").fill_null(g_m)).write_ipc(f"{OUT}/fees.arrow")
# per-user liquidation fee rate (the account's base taker rate, from every xyz coin that day): fees.arrow `liq`
import subprocess
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fees_liq.py"), OUT, FILLS], check=True)
print(f"fee rates: global taker {g_t*1e4:.2f}bp maker {g_m*1e4:.2f}bp")
inj = tr.filter(~pl.col("t_oid").is_in(sim_taker.implode())).sort("h", "trade_id", maintain_order=True)
inj.select("h", "m_oid", q("sz").alias("sz"), pl.col("m_oid").is_in(trig.implode()).alias("m_is_trig"), q("px").alias("px"),
           pl.when(pl.col("t_u") == VAULT).then(2).when(pl.col("liquidation_method") == "market").then(1).otherwise(0).cast(pl.UInt8).alias("t_kind"),
           U("t_u").alias("t_u"), (pl.col("t_side") == "buy").alias("t_buy"), U("m_u").alias("m_u"),
           pl.col("t_oid").is_in(trig.implode()).alias("t_is_trig")).write_ipc(f"{OUT}/inject.arrow")
print("injected kind-0 fills whose taker is a trigger order:", inj.filter(pl.col("t_oid").is_in(trig.implode())).height, "of", inj.height)
print("injected by taker kind (0 other, 1 liquidation round, 2 vault):", inj.with_columns(pl.when(pl.col("t_u") == VAULT).then(2).when(pl.col("liquidation_method") == "market").then(1).otherwise(0).alias("kk")).group_by("kk").agg(pl.len(), (pl.col("px").cast(float)*pl.col("sz").cast(float)).sum().round(0)).sort("kk").to_dicts())
# per-coin fallback liquidation fee rate (the engine uses each account's own rate, fees.arrow `liq`): the liquidated
# side only, net of builder fees (both sides averaged gave 0.43-0.56 bp instead of HL's 0.86-0.9)
lq = fills.filter(pl.col("liquidation_method") == "market", pl.col("is_liquidation").fill_null(False)).with_columns(
    fee=pl.col("fee").cast(float) - pl.col("builder_fee").cast(float).fill_null(0.0))
# quiet days may have no market liquidation: fall back to LIQ_FEE_RATE (default 5e-5, the earnings days' 4.3-5.6 bp)
_lq_ntl = ssum(lq["price"].cast(float) * lq["size"].cast(float)) if lq.height else 0.0
LIQ_FEE = ssum(lq["fee"].cast(float)) / _lq_ntl if _lq_ntl > 0 else float(os.environ.get("LIQ_FEE_RATE", "5e-5"))
print("liquidation fee rate (bp of notional):", round(LIQ_FEE * 1e4, 4), "" if _lq_ntl > 0 else "(fallback: no market liquidation)")
mem("after trades")
pre = (tr.filter(pl.col("m_oid") < first_oid).group_by("m_oid", maintain_order=True)
       .agg(pl.col("m_u").first(), pl.col("m_side").first(), pl.col("px").first(), pl.col("sz").sum()))
pre.select("m_oid", U("m_u").alias("u"), (pl.col("m_side") == "buy").alias("buy"), q("px").alias("px"), q("sz").alias("sz")).sort("m_oid").write_ipc(f"{OUT}/seeds.arrow")
pl.DataFrame({"t": trig}).write_ipc(f"{OUT}/trigger_oids.arrow")
print("real user-taker fills", real.height, "| engine-taker injections", inj.height, "| seeds", pre.height)

# ---------------------------------------------------------------- validation: 1-min L2 (top 5), real liquidation marks
ob = pl.read_parquet(OB1M)
rows = []
for h, bids, asks in ob.select("block_number", "bids", "asks").iter_rows():
    for side, lv in ((1, bids), (0, asks)):
        for k, x in enumerate(lv[:5]):
            rows.append((int(h), side, k, round(float(x["px"]) * SC), round(float(x["sz"]) * SC)))
pl.DataFrame(rows, schema={"h": pl.Int64, "buy": pl.UInt8, "lvl": pl.UInt8, "px": pl.Int64, "sz": pl.Int64}, orient="row").write_ipc(f"{OUT}/l2.arrow")
L = pl.read_parquet(LIQ).filter(pl.col("coin") == COIN).with_columns(pl.col("timestamp").cast(pl.Int64).replace_strict(h_of_ms, default=None).alias("h"))
L.drop_nulls("h").group_by("h").agg(q("liquidation_mark_px").first().alias("mk")).sort("h").write_ipc(f"{OUT}/liqmarks.arrow")

# ---------------------------------------------------------------- clearinghouse inputs (Phase 2a)
snap_block = int(sorted(glob.glob(SNAP))[0].split("/")[-1].split("_")[0])
# cross accounts holding at most this one xyz position (snapshot) and trading no other xyz coin during the tape: their
# account value is collateral + this position's PnL, so they can be margined like an isolated account with
# cm = account_value - (mark0 - e) * q (cross semantics on reduce: realized PnL stays, nothing is released)
_dex = COIN.split(":")[0] + ":"
_allsnap = (pl.scan_parquet(SNAP).filter(pl.col("market").str.starts_with(_dex)).group_by("user")
            .agg((pl.col("size") != 0).sum().alias("npos"), pl.col("account_value").first().alias("av")).collect())
_other = set(pl.concat([pl.scan_parquet(f).filter(pl.col("coin").str.starts_with(_dex), pl.col("coin") != COIN,
                                                   pl.col("timestamp").cast(pl.Int64) <= _tape_end).select("address")
                        for f in [FILLS] + ([_FN] if _FN else [])]).unique().collect()["address"].to_list())
_ai = snap.join(_allsnap, on="user", how="left").with_columns(
    pl.when((pl.col("leverage_type") != "isolated") & (pl.col("npos") <= 1) & ~pl.col("user").is_in(list(_other)) & (pl.col("size") != 0)
            & (pl.col("account_mode") != "portfolio_margin"))
    .then(pl.col("av") - (pl.col("notional") / pl.col("size").abs() - pl.col("entry_price")) * pl.col("size")).otherwise(float("nan")).alias("cm"))
print("cross single-position accounts with collateral:", _ai.filter(pl.col("cm").is_not_nan()).height, "of", _ai.filter(pl.col("leverage_type") != "isolated").height, "cross")
_ai.select(U("user").alias("u"), pl.col("size").cast(pl.Float64).alias("q"), pl.col("entry_price").cast(pl.Float64).alias("e"),
           pl.col("liquidation_price").cast(pl.Float64).fill_null(float("nan")).alias("lp"),
           (pl.col("leverage_type") == "isolated").alias("iso"), pl.col("leverage").cast(pl.Float64).alias("lev"),
           pl.col("cm").cast(pl.Float64)).write_ipc(f"{OUT}/acc_init.arrow")
sa = pl.scan_parquet(f"{T}/state.parquet").filter(pl.col("asset") == ASSET, pl.col("ok"), pl.col("h") > snap_block).collect()
sa = sa.select("h", "b", "i", U("u").alias("u"),
               pl.when(pl.col("type") == "updateLeverage").then(1).otherwise(2).cast(pl.UInt8).alias("k"),
               pl.col("fields").str.json_path_match("$.leverage").cast(pl.Float64).fill_null(0.0).alias("lev"),
               (pl.col("fields").str.json_path_match("$.isCross") == "true").fill_null(False).alias("cross"),
               (pl.col("fields").str.json_path_match("$.ntli").cast(pl.Float64).fill_null(0.0) / 1e6).alias("amt"))
fl = fills.with_columns(pl.col("ms").replace_strict(h_of_ms, default=None).alias("h")).filter(pl.col("h") > snap_block).sort("h", "trade_id", maintain_order=True)
fl = fl.select("h", pl.lit(0, pl.Int64).alias("b"), pl.lit(0, pl.Int64).alias("i"), U("address").alias("u"),
               pl.when(pl.col("liquidation_method").is_not_null()).then(4).otherwise(3).cast(pl.UInt8).alias("k"),
               (pl.col("side") == "buy").alias("cross"),                          # reused: buy flag
               pl.col("price").cast(pl.Float64).alias("lev"),                      # reused: fill px
               pl.col("size").cast(pl.Float64).alias("amt"),                       # reused: fill sz
               pl.col("fee").cast(pl.Float64).alias("fee"),
               (pl.col("liquidation_method") == "backstop").fill_null(False).alias("bstop"),
               pl.col("direction").str.contains("Isolated").fill_null(False).alias("dir_iso"),
               pl.col("direction").str.starts_with("Liquidated").fill_null(False).alias("dir_liq"),
               pl.col("liquidation_mark_px").cast(pl.Float64).fill_null(float("nan")).alias("lmark"),
               pl.col("is_liquidation").fill_null(False).alias("liq_side"))      # the liquidated account's side (sim/prep/liqside.py)
fu = pl.read_parquet(ledger_file("funding")).filter(pl.col("h") > snap_block).select(
    "h", pl.lit(0, pl.Int64).alias("b"), pl.lit(0, pl.Int64).alias("i"), U("user").alias("u"), pl.lit(5, pl.UInt8).alias("k"),
    pl.lit(False).alias("cross"), pl.lit(0.0).alias("lev"), pl.col("amount").alias("amt"))
ext = dict(fee=pl.lit(0.0), bstop=pl.lit(False), dir_iso=pl.lit(False), dir_liq=pl.lit(False), lmark=pl.lit(float("nan")), liq_side=pl.lit(False))
acc_cols = ["h", "b", "i", "u", "k", "cross", "lev", "amt", "fee", "bstop", "dir_iso", "dir_liq", "lmark", "liq_side"]
acc = pl.concat([sa.with_columns(**ext).select(acc_cols), fl.select(acc_cols), fu.with_columns(**ext).select(acc_cols)], how="vertical_relaxed")
acc = acc.with_columns(pl.col("k").replace_strict({1: 0, 2: 0, 3: 1, 4: 2, 5: 3}, return_dtype=pl.UInt8).alias("phase")).sort("h", "phase", "b", "i", maintain_order=True)
acc.write_ipc(f"{OUT}/acc_events.arrow")
pl.read_parquet(ledger_file("liq_ledger")).select("h", U("user").alias("u"), "account_value", "szi", (pl.col("leverage_type") == "Isolated").alias("iso")).write_ipc(f"{OUT}/ledger.arrow")
if SNAP_NEXT:
    sn = pl.scan_parquet(SNAP_NEXT).filter(pl.col("market") == COIN, pl.col("user").is_in(list(uid.keys()))).collect()
    # the next snapshot is taken a few minutes after midnight: roll it back to the end of this fills tape
    FILLS_NEXT = sys.argv[10] if len(sys.argv) > 10 else None
    adj = pl.DataFrame({"user": [], "dq": []}, schema={"user": pl.String, "dq": pl.Float64})
    if FILLS_NEXT:
        t_end = fills["ms"].max()
        snap_ms = int(sorted(glob.glob(SNAP_NEXT))[0].split("_")[-1].split(".")[0])
        fn = (pl.scan_parquet(FILLS_NEXT).filter(pl.col("coin") == COIN).with_columns(pl.col("timestamp").cast(pl.Int64).alias("ms"))
              .filter(pl.col("ms") > t_end, pl.col("ms") <= snap_ms).collect())
        adj = fsum_by(fn.with_columns(pl.when(pl.col("side") == "buy").then(pl.col("size").cast(float)).otherwise(-pl.col("size").cast(float)).alias("dq")), ["address"], ["dq"]).rename({"address": "user"})
        print("fills between end of tape and next snapshot:", fn.height)
    sn = sn.join(adj, on="user", how="left").with_columns((pl.col("size").cast(pl.Float64) - pl.col("dq").fill_null(0.0)).alias("q"))
    sn.select(U("user").alias("u"), "q").write_ipc(f"{OUT}/acc_next.arrow")
    print("next-day snapshot positions", sn.height)
print("acc_init", snap.height, "acc_events", acc.height, "snap_block", snap_block)
with open(f"{OUT}/meta.json", "w") as fh:
    vf = fills.filter(pl.col("address") == VAULT, pl.col("liquidation_method").is_null())
    vault_fee_rate = ssum(vf["fee"].cast(float)) / max(ssum(vf["price"].cast(float) * vf["size"].cast(float)), 1.0)
    if vault_fee_rate == 0.0:   # no vault fill that day: the earnings days' 0.9 bp
        vault_fee_rate = 9e-5
    szd = 3
    if META_JSON:
        szd = {u["name"]: u["szDecimals"] for u in json.load(open(META_JSON))[0]["universe"]}.get(COIN, 3)
    json.dump({"sz_decimals": szd, "vault_uid": uid.get(VAULT, -1), "vault_fee_rate": vault_fee_rate, "liq_fee_rate": LIQ_FEE, "coin": COIN, "asset": ASSET, "snap_block": snap_block, "first_oid": int(first_oid), "w0_ms": W0_MS, "w1_ms": W1_MS}, fh)
