#!/bin/zsh
# 2026-11-10 night: ratchet variants (pkgm3q book-aware, pkgm3x / pkgm3y the mark must have held 30 s / 150 s) on the two tests
# that pull in opposite directions: the crash book push (wants the ratchet) and the adaptive attack (hurt by it), both ways.
cd ${REPO:-$PWD}; T=${REPO:-$PWD}/data/scen/tests_1110i; F=${REPO:-$PWD}/data/scen/tests_1110f; P=python3
M="pkgm3q1800 pkgm3x1800 pkgm3y1800"
( PY=$P MARKS="$M" CAPS="5e6" DS="60 300" S=$T/push zsh $F/push/prop_runs_log.sh > $T/push.log 2>&1 ) &
( PY=$P MARKS="$M" EXT_RAMP="1793226600000;30;-0.10;120" PROP_AT=1793226630000 F=-0.10 CAPS="5e6" DS="15 60" S=$T/down_day zsh $F/push/prop_runs_log.sh > $T/down_day.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;-0.10;120" PROP_AT=1793163630000 F=-0.10 CAPS="1e6" DS="15 60" S=$T/down_night zsh $F/push/prop_runs_log.sh > $T/down_night.log 2>&1 ) &
wait
( PY=$P MARKS="$M" EXT_RAMP="1793226600000;30;+0.10;120" PROP_AT=1793226630000 F=0.10 CAPS="5e6" DS="15 60" S=$T/up_day zsh $F/push/prop_runs_log.sh > $T/up_day.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;+0.10;120" PROP_AT=1793163630000 F=0.10 CAPS="1e6" DS="15 60" S=$T/up_night zsh $F/push/prop_runs_log.sh > $T/up_night.log 2>&1 ) &
wait
echo VARIANTS DONE; grep -c 'exit 101' $T/*.log | grep -v ':0'; df -h / | tail -1 | awk '{print "free:", $4}'
