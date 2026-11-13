#!/bin/zsh
# One coin-day from extract tables + hydromancer / node inputs to a validated engine prep, the same chain as the
# earnings days (2026-11-03/04): ledger, oidbind, prep, silent cancels with L2 vetoes (5 passes) + margin, prio,
# liqside, accav, crossacc, relayer residual, then a real-parameter validation run.
# Usage: zsh sim/pipe_day.sh DAY NEXT COIN ASSET MAXLEV      e.g. zsh sim/pipe_day.sh 1020 1021 GOOGL 110012 20
# Inputs: data/extract$DAY/tables, data/xyzdata/{all,snap}$DAY/$NEXT, liquidations/date=2026-10-DD, ob1m_${C}_$DAY,
#         data/nodedata/misc$DAY, data/global$DAY, data/global$NEXT. One heavy step at a time (memguard).
set -e
setopt pipefail   # every heavy step ends in a display filter: without this a Python traceback never fails the day
cd "${0:A:h}/.."
DAY=$1; NX=$2; C=$3; A=$4; L=$5
PY=${PY:-python3}; G=tools/memguard.sh
# E_DIR: this coin's own tables (sim/prep/split_tables.py), PREP_DIR / WORK_DIR: other output dirs; VALIDATE=0 skips the
# final real-parameter validation run (a check only: nothing downstream reads it)
# step NAME: prints the header and, for the step that just ended, its wall time ([time] lines: where a run's minutes go)
TS=$(date +%s); T00=$TS; STEP=""
step() { local now=$(date +%s); [[ -n $STEP ]] && echo "   [time] $STEP: $((now - TS)) s"; STEP="$*"; TS=$now; if [[ -n $STEP ]]; then echo "== $*"; fi; }
D=${PREP_DIR:-data/prep_${C}_$DAY}; E=${E_DIR:-data/extract$DAY/tables}; X=data/xyzdata; W=${WORK_DIR:-data/scen/pipe_${C}_$DAY}; mkdir -p $W
step "ledger";   $G 6000 $PY -I sim/prep/ledger.py data/nodedata/misc$DAY xyz:$C $E 2>&1 | tail -2
step "oidbind";  $G 6000 $PY -I sim/prep/oidbind.py $E $X/all$DAY.parquet xyz:$C $A $E/oid_bind_$C.parquet 2>&1 | { grep -E "bound|memguard|Error" || true; } | tail -3
step "prep";     XYZ_META=data/xyzmeta.json $G 6000 $PY -I sim/prep/prep.py $E $X/all$DAY.parquet $X/ob1m_${C}_$DAY.parquet "$X/liquidations/date=2026-${DAY:0:2}-${DAY:2:2}" "$X/snap$DAY/*.parquet" xyz:$C $A $D "$X/snap$NX/*.parquet" $X/all$NX.parquet 2>&1 | { grep -E "events|acc_init|memguard|Error|error" || true; } | tail -4
step "leverage of accounts opening during the day"; $PY -I sim/prep/acc_lev.py $D "$X/snap$NX/*.parquet" xyz:$C 2>&1 | tail -1
step "silent cancels"; echo "m_oid,veto_h" > $D/silent_vetoes.csv
TR=0; TP=0
for it in 1 2 3 4 5; do
  t1=$(date +%s)
  TRIGGERS=simulate SILENT=1 PM_DIAG=$W/pm.csv VETO_OUT=$W/veto.csv $G 6000 engine/target/release/engine replay $D tape_walk 2>&1 | { grep -E "L2 snap" || true; } | tr '\n' ' '; echo
  t2=$(date +%s); TR=$((TR + t2 - t1))
  [[ -f $W/veto.csv ]] && tail -n +2 $W/veto.csv >> $D/silent_vetoes.csv
  [[ $it -lt 5 ]] && $PY -I sim/prep/silent.py $D $E $A $W/pm.csv $D/silent_cancels.arrow $D/silent_vetoes.csv 2>&1 | tail -1
  TP=$((TP + $(date +%s) - t2))
done
echo "   [time] silent cancels, of which: 5 book replays $TR s, 4 inference passes $TP s"
step "margin";   $PY -I sim/prep/margin.py $D $E $A $X/all$DAY.parquet $W/pm.csv 2>&1 | tail -2
step "prio";     $G 6000 $PY -I sim/prep/prio.py $D $E $A 2>&1 | tail -1
step "liqside";  $PY -I sim/prep/liqside.py $D xyz:$C $X/all$DAY.parquet $X/all$NX.parquet 2>&1 | tail -1
step "accav";    $PY -I sim/prep/accav.py $D data/global$DAY data/global$NX 2>&1 | tail -1
step "crossacc"; $G 6000 $PY -I sim/prep/crossacc.py $D data/global$DAY data/nodedata/misc$DAY data/xyzmeta.json xyz:$C data/global$NX $E/oracle.parquet 2>&1 | { grep -E "validated|acc_x |peak|rror" || true; } | tail -3
# isolated-only (noCross / strictIsolated) market: every position is isolated and a backstop is ADL (engine backstop=adl,
# which implies iso_only); the leverage of accounts that leave no evidence is fitted on the real marks (sim/prep/lev_fit.py)
NOX=(); if $PY -c "import json,sys; u={x['name']:x.get('marginMode') for x in json.load(open('data/xyzmeta.json'))[0]['universe']}; sys.exit(0 if u.get('xyz:$C') in ('noCross','strictIsolated') else 1)"; then NOX=(backstop=adl); fi
if [[ -n $NOX ]]; then step "leverage fit (isolated-only market)"; $PY -I sim/prep/lev_fit.py $D $L $NOX 2>&1 | tail -1; fi
step "internal-session windows"; $PY -I sim/prep/closed_windows.py --internal --prep $D > $D/internal_windows.txt; echo "$(cat $D/internal_windows.txt | tr , "\n" | grep -c .) windows"
step "relayer residual"
env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_OUT=$D/relayer_resid_endo0_policy.txt $G 6000 engine/target/release/engine sim $D $L $NOX 2>&1 | { grep -E "relayer|takeovers|=> PnL|memguard" || true; } | tail -5
if [[ ${VALIDATE:-1} != 0 ]]; then
step "validation (real parameters, residual in)"
env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $G 6000 engine/target/release/engine sim $D $L $NOX 2>&1 | { grep -E "relayer|mark|takeovers|liquidat|positions|exact|=> PnL|memguard" || true; } | tail -14
fi
step ""; echo "   [time] total: $(( $(date +%s) - T00 )) s"
echo "PIPE DONE $C $DAY"
