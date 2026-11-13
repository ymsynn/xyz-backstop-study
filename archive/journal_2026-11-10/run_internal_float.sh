#!/bin/zsh
# 2026-11-11: the capped internal oracle with its own unrounded state (engine fix, relayer.rs int_state), ONE_SIDED=quote.
# Tests that lean on the internal oracle: SKHX (feed frozen 12 h), book push on a quiet feed, closed CL / GOLD, the overnight
# walk and walk + push, and the three crashes as a check. Previous candidate (same capped oracle) beside the candidate.
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; K=$T/fl; P=python3
M=pkgm3q1800; D=lead3q1800; export ONE_SIDED=quote
( RELAYER_WARMUP_S=43200 PY=$P EV="SKHX/0727/10" S=$K/skhx DES="lead $D" zsh sim/liqbook_runs.sh > $K/skhx.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="pkgmint $M" PROP_T=1793146200000 EXT_FREEZE="1793163600000;10800" PROP_AT=1793164200000 CAPS="5e6" DS="300 3600 9000" S=$K/frz zsh $T/push/prop_runs_log.sh > $K/frz.log 2>&1 ) &
( S=$K/closed_CL PY=$P PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=1789074600000 MARKS="pkgmint $M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $K/closed_CL.log 2>&1 ) &
( S=$K/closed_GOLD PY=$P PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=1793397600000 MARKS="pkgmint $M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $K/closed_GOLD.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" COINS=GOOGL RAMP_AT=1793163600000 TAGS="w30 w300" S=$K/onw zsh $T/ramp_overnight.sh > $K/onw.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;-0.10;120" PROP_AT=1793163630000 F=-0.10 CAPS="1e6" DS="15 60" S=$K/night zsh $T/push/prop_runs_log.sh > $K/night.log 2>&1 ) &
for ev in GOOGL/1028/20 INTC/1029/10 AMZN/1029/20; do ( PY=$P EV="$ev" S=$K/crash DES="$D" zsh sim/liqbook_runs.sh > $K/crash/log_${ev%%/*}.txt 2>&1 ) & done
wait
echo FLOAT DONE; grep -l 'exit 101' $K/*.log $K/*/*.txt 2>/dev/null; df -h / | tail -1 | awk '{print "free:", $4}'
