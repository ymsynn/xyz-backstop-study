"""Recover HL's silent cancels (margin / reduce-only / ... cancels the command stream never shows) from a PM_DIAG run.

Usage: python silent.py PREP_DIR TABLES_DIR ASSET PM_DIAG_CSV [PREV_SILENT] [VETOES_CSV]
VETOES (m_oid, veto_h) are L2-snapshot vetoes from the engine (VETO_OUT): the order was still resting at block veto_h,
so its silent cancel can only be revealed by a taker after that block.
A maker that pure price-time matching would take for a user taker, that the real taker did not touch, and that is
never referenced again afterwards (no fill, no successful cancel, no modify), or whose next cancel fails ("never placed,
already canceled, or filled"), was already gone: HL had cancelled it. It is removed right before that taker
(PREP_DIR/silent_cancels.arrow: t_oid, m_oid). Run iteratively: each pass removes phantoms the previous book still had.
Makers that are skipped but still live (filled later, cancelled successfully later) are left alone and reported.
"""
import sys, os
import polars as pl
# reproducible outputs (sim/detio.py): canonical write_ipc, exact float sums; loaded by path because of python -I
import importlib.util as _ilu0, os as _os0
_sp0 = _ilu0.spec_from_file_location("detio", _os0.path.join(_os0.path.dirname(_os0.path.dirname(_os0.path.abspath(__file__))), "detio.py"))
detio = _ilu0.module_from_spec(_sp0); _sp0.loader.exec_module(detio)

PREP, T, ASSET, DIAG = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
PREV = sys.argv[5] if len(sys.argv) > 5 else None
VETO = sys.argv[6] if len(sys.argv) > 6 else None
veto = (pl.read_csv(VETO, schema={"m_oid": pl.Int64, "veto_h": pl.Int64}).group_by("m_oid").agg(pl.col("veto_h").max()) if VETO and os.path.exists(VETO)
        else pl.DataFrame(schema={"m_oid": pl.Int64, "veto_h": pl.Int64}))
# seq: the engine's processing order (row order of the diag), the tie-break between takers of one block
d = pl.read_csv(DIAG).with_row_index("seq")
cand = d.filter((pl.col("m") >= 0) & (pl.col("sim_sz") > 0) & (pl.col("real_sz") == 0) & pl.col("inbook")).select(
    pl.col("oid").alias("t_oid"), "h", pl.col("m").alias("m_oid"), "seq")
oids = cand["m_oid"].unique().implode()
# later references to the maker, by block
fl = pl.read_ipc(f"{PREP}/real_fills.arrow").select("m_oid", pl.col("h").alias("rh"))
inj = pl.read_ipc(f"{PREP}/inject.arrow").select("m_oid", pl.col("h").alias("rh"))
tf = pl.read_ipc(f"{PREP}/trig_fills.arrow").select("m_oid", pl.col("h").alias("rh")) if os.path.exists(f"{PREP}/trig_fills.arrow") else inj.head(0)
fills = pl.concat([fl, inj, tf]).filter(pl.col("m_oid").is_in(oids))
c = (pl.scan_parquet(f"{T}/cancels.parquet").filter(pl.col("a") == ASSET)
     .select(pl.col("h").alias("rh"), pl.col("oid").cast(pl.Int64, strict=False).alias("m_oid"), "status").filter(pl.col("m_oid").is_in(oids)).collect())
mods = (pl.scan_parquet(f"{T}/orders.parquet").filter(pl.col("a") == ASSET)
        .select(pl.col("h").alias("rh"), pl.col("oid_in").cast(pl.Int64, strict=False).alias("m_oid")).filter(pl.col("m_oid").is_in(oids)).collect())
refs = pl.concat([
    fills.with_columns(pl.lit("fill").alias("what")),
    c.filter(pl.col("status") == '"success"').select("m_oid", "rh", pl.lit("cancel_ok").alias("what")),
    c.filter(pl.col("status").str.contains("never placed", literal=True)).select("m_oid", "rh", pl.lit("cancel_failed").alias("what")),
    mods.select("m_oid", "rh", pl.lit("modify").alias("what")),
])
# the maker's next reference. Several in one block (the tables carry no order inside a block for fills): evidence that it
# was live comes first, since a fill or a successful cancel followed by a failed cancel is the only consistent order
# (after a failed cancel the order is gone and can neither fill nor be cancelled). Every choice below is a total order:
# no result depends on the row order polars happens to return.
PRI = {"fill": 0, "cancel_ok": 1, "modify": 2, "cancel_failed": 3}
nxt = (cand.join(refs, on="m_oid", how="left").filter(pl.col("rh").is_null() | (pl.col("rh") >= pl.col("h")))
       .with_columns(pl.col("what").replace_strict(PRI, default=None, return_dtype=pl.Int8).alias("pri"))
       .sort("t_oid", "m_oid", "rh", "pri", nulls_last=True)
       .group_by("t_oid", "m_oid", maintain_order=True).agg(pl.col("what").first(), pl.col("h").min(), pl.col("seq").min()))
nxt = nxt.with_columns(pl.col("what").fill_null("nothing"))
print("skipped makers by later fate:", nxt.group_by("what").len().sort("len", descending=True).to_dicts())
# first taker that reveals each silent cancel
nxt = nxt.join(veto, on="m_oid", how="left").filter(pl.col("veto_h").is_null() | (pl.col("h") > pl.col("veto_h"))).drop("veto_h")
sil = (nxt.filter(pl.col("what").is_in(["nothing", "cancel_failed"])).sort("m_oid", "h", "seq")
       .group_by("m_oid", maintain_order=True).agg(pl.col("t_oid").first(), pl.col("h").first()))
out = sil.select("t_oid", "m_oid", "h")
if PREV and os.path.exists(PREV):
    prev = pl.read_ipc(PREV).select("t_oid", "m_oid", *(["h"] if "h" in pl.read_ipc(PREV).columns else []))
    if "h" in prev.columns:   # drop earlier cancels that an L2 snapshot contradicted
        prev = prev.join(veto, on="m_oid", how="left").filter(pl.col("veto_h").is_null() | (pl.col("h") > pl.col("veto_h"))).drop("veto_h")
    out = pl.concat([prev, sil.select("t_oid", "m_oid", "h")], how="diagonal").unique("m_oid", keep="first", maintain_order=True)
out = out.sort("m_oid")   # one row per maker: a fixed row order
out.write_ipc(f"{PREP}/silent_cancels.arrow")
print("silent cancels:", out.height, f"(+{sil.height} this pass)")
