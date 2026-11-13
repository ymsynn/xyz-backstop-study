#!/bin/zsh
# The final scorecard: today's rules and the proposal (formula frozen 2026-11-11) on ONE engine build,
# every test of the scorecard plus the attack tests on four markets. Engine defaults: ONE_SIDED=quote, unrounded internal oracle.
#   today      today / today          proposal   pkgm3q1800 / lead3q1800       (mark-run tag / liquidation-replay tag)
# Usage: [FINAL_OUT=dir] zsh sim/final/run_final.sh   -> FINAL_OUT (default data/scen/final), one folder per test, logs beside.
# The proposal without its correction step (docs/results/correction_step.md):
#   FINAL_OUT=$PWD/data/scen/final_k M=pkgm3k1800 D=lead3k1800 LIQ_DES="lead3k1800s20 lead3k1800" zsh sim/final/run_final.sh
cd "${0:A:h}/../.."; export FINAL_OUT=${FINAL_OUT:-$PWD/data/scen/final}; K=$FINAL_OUT; mkdir -p $K
source $PWD/sim/times.zsh      # the moments of the replayed market-days
export PY=${PY:-python3}; F=sim/final
M=${M:-today pkgm3q1800}; D=${D:-today lead3q1800}   # rule sets: mark-run ids, liquidation-replay ids
LIQ_DES=${LIQ_DES:-today rim lead3q1800s20 lead3q1800}   # the liquidation study: mark x sizing
git rev-parse HEAD > $K/BUILD.txt 2>/dev/null; md5 -q engine/target/release/engine >> $K/BUILD.txt 2>/dev/null || md5sum engine/target/release/engine >> $K/BUILD.txt
date -u >> $K/BUILD.txt
# ---- 1. liquidation replays: three crashes, SKHX, five isolated-only markets, six quiet days
mkdir -p $K/crash $K/skhx $K/iso $K/quiet
for ev in GOOGL/1028/20 INTC/1029/10 AMZN/1029/20; do ( EV="$ev" S=$K/crash DES="$D" zsh sim/runs/liqbook_runs.sh > $K/crash/log_${ev%%/*}.txt 2>&1 ) & done
( RELAYER_WARMUP_S=43200 EV="SKHX/0727/10" S=$K/skhx DES="$D" zsh sim/runs/liqbook_runs.sh > $K/skhx.log 2>&1 ) &
( EV="GOOGL/1020/20 INTC/1020/10 AMZN/1020/20 GOOGL/1021/20 INTC/1021/10 AMZN/1021/20" S=$K/quiet DES="$D" zsh sim/runs/liqbook_runs.sh > $K/quiet.log 2>&1 ) &
for ev in NOW/1028/10 LITE/1028/10 MRVL/1028/10; do ( EV="$ev" S=$K/iso DES="$D" zsh sim/runs/liqbook_runs.sh > $K/iso/log_$(echo $ev | tr '/' '_').txt 2>&1 ) & done
wait
for ev in RDDT/1029/10 NET/1105/10; do ( EV="$ev" S=$K/iso DES="$D" zsh sim/runs/liqbook_runs.sh > $K/iso/log_$(echo $ev | tr '/' '_').txt 2>&1 ) & done
# ---- 2. feed tests: walks by day (both ways) and overnight, bad print, stuck feed, normal sessions
( MARKS="$M" S=$K/r_dn zsh sim/runs/ramp_runs.sh > $K/r_dn.log 2>&1 ) &
( MARKS="$M" FRAC=+0.10 S=$K/r_up zsh sim/runs/ramp_runs.sh > $K/r_up.log 2>&1 ) &
( MARKS="$M" S=$K/spike zsh sim/runs/spike_runs.sh > $K/spike.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 MARKS="$M" COINS=GOOGL RAMP_AT=${GOOGL_NIGHT} TAGS="w30 w300" S=$K/onw zsh sim/runs/ramp_runs.sh > $K/onw.log 2>&1 ) &
( FREEZE_S=120 MARKS="$M" zsh $F/stuck_feed_runs.sh > $K/stuck_f120.log 2>&1 ) &
( FREEZE_S=0 MARKS="$M" zsh $F/stuck_feed_runs.sh > $K/stuck_f0.log 2>&1 ) &
wait
( MARKS="$M" S=$K/normal zsh sim/runs/normal_runs.sh > $K/normal.log 2>&1 ) &
# ---- 3. out of sample (7 market-days)
for x in "1022 GOOGL 20" "1022 META 20" "1030 SPCX 20" "1022 SILVER 25" "1030 GOLD 25" "0910 BRENTOIL 20" "0910 CL 20"; do ( PKS="$M" zsh $F/oos_runs.sh ${=x} > /dev/null 2>&1 ) & done
wait
# ---- 4. book pushes: in the crash, in closed sessions, on a quiet feed (up and down)
P=$F/book_push_runs.sh
( MARKS="$M" CAPS="1e6 5e6" DS="60 300" S=$K/push zsh $P > $K/push.log 2>&1 ) &
( S=$K/closed_CL PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=${CL_CLOSED} MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh $P > $K/closed_CL.log 2>&1 ) &
( S=$K/closed_GOLD PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=${GOLD_EVE} MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh $P > $K/closed_GOLD.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 MARKS="$M" PROP_T=${GOOGL_PREV_EVE} EXT_FREEZE="${GOOGL_NIGHT};10800" PROP_AT=${GOOGL_NIGHT_10M} CAPS="5e6" DS="300 3600 9000" F=0.06 S=$K/quiet_up zsh $P > $K/quiet_up.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 MARKS="$M" PROP_T=${GOOGL_PREV_EVE} EXT_FREEZE="${GOOGL_NIGHT};10800" PROP_AT=${GOOGL_NIGHT_10M} CAPS="5e6" DS="300 3600 9000" F=-0.06 S=$K/quiet_dn zsh $P > $K/quiet_dn.log 2>&1 ) &
wait
# ---- 5. adaptive attack (feed walked 10% over 30 s and held 120 s, then a book push the same way) on four markets
#         coin prep maxlev day0(00:10 UTC, own mark from) night(walk) day(walk)
adapt() { # coin prep L t0 walk tag frac cap ds warm
  ( [[ -n ${10} ]] && export RELAYER_WARMUP_S=${10}
    PROP_C=$1 PROP_D=$2 PROP_L=$3 PROP_T=$4 EXT_RAMP="$5;30;$7;120" PROP_AT=$(($5 + 30000)) F=$7 CAPS="$8" DS="$9" MARKS="$M" S=$K/adapt/$1_$6 zsh $P > $K/adapt/$1_$6.log 2>&1 ) &
}
mkdir -p $K/adapt
for sgn in dn up; do f=$([[ $sgn == dn ]] && echo -0.10 || echo +0.10)
  adapt GOOGL data/prep_GOOGL_1028 20 ${GOOGL_PREV_EVE} ${GOOGL_NIGHT} night_$sgn $f 1e6 "15 60" 57600
  adapt GOOGL data/prep_GOOGL_1028 20 ${GOOGL_CLOSE} ${GOOGL_EVE} day_$sgn $f 5e6 "15 60" ""
  adapt AMZN data/prep_AMZN_1029 20 ${AMZN_PREV_EVE} ${AMZN_NIGHT} night_$sgn $f 1e6 "15 60" 57600
  adapt AMZN data/prep_AMZN_1029 20 ${AMZN_CLOSE} ${AMZN_EVE} day_$sgn $f 5e6 "15 60" ""
  wait
  adapt INTC data/prep_INTC_1029 10 ${AMZN_PREV_EVE} ${AMZN_NIGHT} night_$sgn $f 1e6 "15 60" 57600
  adapt INTC data/prep_INTC_1029 10 ${AMZN_CLOSE} ${AMZN_EVE} day_$sgn $f 5e6 "15 60" ""
  # SK Hynix: the relayer is simulated from the start of the day (86400); with 43200 it replays the tape at 03:00 UTC
  adapt SKHX data/prep_SKHX_0727 10 ${SKHX_OPEN} ${SKHX_NOON} day2_$sgn $f 1e6 "15 60" 86400
  wait
done
# ---- 6. liquidation study (the cut-back page and the table of combinations): mark x sizing on the three crashes, and the
#         mark and the cut-back each alone on the five isolated-only markets
mkdir -p $K/liqstudy
for ev in GOOGL/1028/20 INTC/1029/10 AMZN/1029/20; do ( EV="$ev" S=$K/liqstudy DES="$LIQ_DES" zsh sim/runs/liqbook_runs.sh > $K/liqstudy/log_${ev%%/*}.txt 2>&1 ) & done
wait
for ev in NOW/1028/10 LITE/1028/10 MRVL/1028/10 RDDT/1029/10 NET/1105/10; do ( EV="$ev" S=$K/liqstudy DES="$LIQ_DES" zsh sim/runs/liqbook_runs.sh > $K/liqstudy/log_$(echo $ev | tr '/' '_').txt 2>&1 ) & done
wait
LIQBOOK_DIR=$K/liqstudy $PY sim/score/liqbook_eval.py > $K/liqstudy/eval.txt 2>&1
echo FINAL DONE; grep -l 'exit 101' $K/*.log $K/*/*.txt $K/*/*.log $K/oos/*.log 2>/dev/null; df -h / | tail -1 | awk '{print "free:", $4}'
