#!/bin/zsh
# Change 2 on its own: today's mark formula and today's liquidation sizing, with only the proposal's rule for a feed that
# is not live (the internal price steps toward the book by at most 1% of itself, and the same rule applies when the
# external price has repeated a value twice). The tests are those of run_final.sh that this rule bears on: the pushes of
# xyz's book in a closed session and on a quiet feed, and the crashes, to see what it changes when nothing is attacked.
# Usage: [FINAL_OUT=dir] zsh sim/final/change2_alone.sh  -> FINAL_OUT/change2/ (default data/scen/final), {closed_CL,closed_GOLD,quiet_up,crash,skhx}
cd "${0:A:h}/../.."; export PY=${PY:-python3}; K=${FINAL_OUT:-$PWD/data/scen/final}/change2; mkdir -p $K
source $PWD/sim/times.zsh      # the moments of the replayed market-days
export INTERNAL_CAP=0.01 RELAYER_STALE_INTERNAL=2
P=sim/final/book_push_runs.sh
( S=$K/closed_CL PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=${CL_CLOSED} MARKS=today CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh $P > $K/closed_CL.log 2>&1 ) &
( S=$K/closed_GOLD PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=${GOLD_EVE} MARKS=today CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh $P > $K/closed_GOLD.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 MARKS=today PROP_T=${GOOGL_PREV_EVE} EXT_FREEZE="${GOOGL_NIGHT};10800" PROP_AT=${GOOGL_NIGHT_10M} CAPS="5e6" DS="300 3600 9000" F=0.06 S=$K/quiet_up zsh $P > $K/quiet_up.log 2>&1 ) &
wait
( EV="GOOGL/1028/20 INTC/1029/10" S=$K/crash DES=today zsh sim/runs/liqbook_runs.sh > $K/crash_a.log 2>&1 ) &
( EV="AMZN/1029/20" S=$K/crash DES=today zsh sim/runs/liqbook_runs.sh > $K/crash_b.log 2>&1 ) &
( RELAYER_WARMUP_S=43200 EV="SKHX/0727/10" S=$K/skhx DES=today zsh sim/runs/liqbook_runs.sh > $K/skhx.log 2>&1 ) &
wait
echo CHANGE2 DONE
