#!/bin/zsh
# Full scorecard on the book-aware ratchet (pkgm3q1800 / lead3q1800), 2026-11-10 night. Same commands as folder r/.
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; K=$T/q; G=$PWD/data/scen/tests_1110g; P=python3
M=pkgm3q1800; D=lead3q1800
( PY=$P MARKS="$M" S=$K/r_dn zsh sim/ramp_runs.sh > $K/r_dn.log 2>&1 ) &
( PY=$P MARKS="$M" FRAC=+0.10 S=$K/r_up zsh sim/ramp_runs.sh > $K/r_up.log 2>&1 ) &
( PY=$P MARKS="$M" S=$K/spike zsh sim/spike_runs.sh > $K/spike.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" COINS=GOOGL RAMP_AT=1793163600000 TAGS="w30 w300" S=$K/onw zsh $T/ramp_overnight.sh > $K/onw.log 2>&1 ) &
for ev in GOOGL/1028/20 INTC/1029/10 AMZN/1029/20; do ( PY=$P EV="$ev" S=$K/crash DES="$D" zsh sim/liqbook_runs.sh > $K/crash/log_${ev%%/*}.txt 2>&1 ) & done
wait
( RELAYER_WARMUP_S=43200 PY=$P EV="SKHX/0727/10" S=$K/skhx DES="$D" zsh sim/liqbook_runs.sh > $K/skhx.log 2>&1 ) &
for ev in NOW/1028/10 LITE/1028/10 MRVL/1028/10 RDDT/1029/10 NET/1105/10; do ( PY=$P EV="$ev" S=$K/iso DES="$D" zsh sim/liqbook_runs.sh > $K/iso/log_$(echo $ev | tr '/' '_').txt 2>&1 ) & done
( PY=$P EV="GOOGL/1020/20 INTC/1020/10 AMZN/1020/20 GOOGL/1021/20 INTC/1021/10 AMZN/1021/20" S=$K/quiet DES="$D" zsh sim/liqbook_runs.sh > $K/quiet.log 2>&1 ) &
wait
( PY=$P MARKS="$M" zsh $K/freeze_runs.sh > $K/freeze.log 2>&1 ) &
( PY=$P FREEZE_S=120 MARKS="$M" zsh $T/stuck/freeze_f120.sh > $T/stuck/f120_q.log 2>&1 ) &
( PY=$P FREEZE_S=0 MARKS="$M" zsh $T/stuck/freeze_f0.sh > $T/stuck/f0_q.log 2>&1 ) &
( S=$T/closed_CL PY=$P PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=1789074600000 MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $T/closed_CL_q.log 2>&1 ) &
( S=$T/closed_GOLD PY=$P PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=1793397600000 MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $T/closed_GOLD_q.log 2>&1 ) &
wait
for x in "1022 GOOGL 20" "1022 META 20" "1030 SPCX 20"; do ( PY=$P PKS=$M zsh $K/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
for x in "1022 SILVER 25" "1030 GOLD 25" "0910 BRENTOIL 20" "0910 CL 20"; do ( PY=$P PKS=$M zsh $K/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
( PY=$P MARKS="$M" S=$G/normal zsh sim/normal_runs.sh > $G/normal_q.log 2>&1 ) &
wait
echo SCORECARD DONE; grep -l 'exit 101' $K/*.log $K/*/*.txt $K/oos/*.log $T/*_q.log $T/stuck/*_q.log 2>/dev/null; df -h / | tail -1 | awk '{print "free:", $4}'
