#!/bin/zsh
# 2026-11-11: the rest of the candidate's scorecard with both engine fixes (unrounded internal oracle, ONE_SIDED=quote).
# run.sh in this folder did SKHX, the three crashes, closed sessions, the quiet-feed push and the overnight tests.
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; K=$T/fl; P=python3
M=pkgm3q1800; D=lead3q1800; export ONE_SIDED=quote
( PY=$P MARKS="today $M" S=$K/normal zsh sim/normal_runs.sh > $K/normal.log 2>&1 ) &
( PY=$P MARKS="$M" S=$K/r_dn zsh sim/ramp_runs.sh > $K/r_dn.log 2>&1 ) &
( PY=$P MARKS="$M" FRAC=+0.10 S=$K/r_up zsh sim/ramp_runs.sh > $K/r_up.log 2>&1 ) &
( PY=$P MARKS="$M" S=$K/spike zsh sim/spike_runs.sh > $K/spike.log 2>&1 ) &
( PY=$P MARKS="$M" CAPS="5e6" DS="60 300" S=$K/push zsh $T/push/prop_runs_log.sh > $K/push.log 2>&1 ) &
wait
for ev in NOW/1028/10 LITE/1028/10 MRVL/1028/10 RDDT/1029/10 NET/1105/10; do ( PY=$P EV="$ev" S=$K/iso DES="$D" zsh sim/liqbook_runs.sh > $K/iso/log_$(echo $ev | tr '/' '_').txt 2>&1 ) & done
( PY=$P EV="GOOGL/1020/20 INTC/1020/10 AMZN/1020/20 GOOGL/1021/20 INTC/1021/10 AMZN/1021/20" S=$K/quiet DES="$D" zsh sim/liqbook_runs.sh > $K/quiet.log 2>&1 ) &
wait
( PY=$P MARKS="$M" zsh $K/freeze_runs.sh > $K/freeze.log 2>&1 ) &
( PY=$P FREEZE_S=120 MARKS="$M" zsh $K/freeze_f120.sh > $K/stuck_f120.log 2>&1 ) &
( PY=$P FREEZE_S=0 MARKS="$M" zsh $K/freeze_f0.sh > $K/stuck_f0.log 2>&1 ) &
for x in "1022 GOOGL 20" "1022 META 20" "1030 SPCX 20"; do ( PY=$P PKS=$M zsh $K/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
wait
for x in "1022 SILVER 25" "1030 GOLD 25" "0910 BRENTOIL 20" "0910 CL 20"; do ( PY=$P PKS=$M zsh $K/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
wait
echo REST DONE; grep -l 'exit 101' $K/*.log $K/*/*.txt $K/oos/*.log 2>/dev/null; df -h / | tail -1 | awk '{print "free:", $4}'
