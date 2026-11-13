#!/bin/zsh
# 2026-11-11: the candidate's full scorecard again with Hyperliquid's one-sided-book rule (ONE_SIDED=quote: the remaining best
# quote stands for the book price), plus today's rules where a test needs its own baseline, and a book push held for hours on
# a feed that does not move (frz). Same commands as folder q/. Outputs in data/scen/tests_1110f/qq.
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; K=$T/qq; P=python3
M=pkgm3q1800; D=lead3q1800; export ONE_SIDED=quote
# feed unchanged for 3 h from 04:30 UTC (GOOGL 10-28), $5M bids 6% above xyz's mid from 04:40 for 5 min / 1 h / 2.5 h
( RELAYER_WARMUP_S=57600 PY=$P MARKS="today pkgmint $M" PROP_T=1793146200000 EXT_FREEZE="1793163600000;10800" PROP_AT=1793164200000 CAPS="5e6" DS="300 3600 9000" S=$K/frz zsh $T/push/prop_runs_log.sh > $K/frz.log 2>&1 ) &
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
( PY=$P FREEZE_S=120 MARKS="$M" zsh $K/freeze_f120.sh > $K/stuck_f120.log 2>&1 ) &
( PY=$P FREEZE_S=0 MARKS="$M" zsh $K/freeze_f0.sh > $K/stuck_f0.log 2>&1 ) &
( S=$K/closed_CL PY=$P PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=1789074600000 MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $K/closed_CL.log 2>&1 ) &
( S=$K/closed_GOLD PY=$P PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=1793397600000 MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $K/closed_GOLD.log 2>&1 ) &
wait
for x in "1022 GOOGL 20" "1022 META 20" "1030 SPCX 20"; do ( PY=$P PKS=$M zsh $K/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
for x in "1022 SILVER 25" "1030 GOLD 25" "0910 BRENTOIL 20" "0910 CL 20"; do ( PY=$P PKS=$M zsh $K/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
( PY=$P MARKS="today $M" S=$K/normal zsh sim/normal_runs.sh > $K/normal.log 2>&1 ) &
wait
echo SCORECARD QUOTE DONE; grep -l 'exit 101' $K/*.log $K/*/*.txt $K/oos/*.log 2>/dev/null; df -h / | tail -1 | awk '{print "free:", $4}'
