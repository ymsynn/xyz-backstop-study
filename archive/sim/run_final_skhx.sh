#!/bin/zsh
# The adaptive attack on SK Hynix (thin market), 03:00 UTC on 07-27, rerun: in run_final.sh the simulated relayer only starts
# 12 h before the day's cascade (RELAYER_WARMUP_S=43200), so at 03:00 it replayed the tape and the walked feed had no effect
# (folders adapt/SKHX_day_*: NOT VALID). Here it is simulated from the start of the day (86400).
cd ${REPO:-$PWD}; export FINAL_OUT=${FINAL_OUT:-$PWD/data/scen/final}; K=$FINAL_OUT
export PY=${PY:-python3}; M="today pkgmint pkgm3q1800"
for sgn in dn up; do f=$([[ $sgn == dn ]] && echo -0.10 || echo +0.10)
  ( export RELAYER_WARMUP_S=86400; PROP_C=SKHX PROP_D=data/prep_SKHX_0727 PROP_L=10 PROP_T=1785111000000 EXT_RAMP="1785121200000;30;$f;120" PROP_AT=1785121230000 F=$f CAPS="1e6" DS="15 60" MARKS="$M" S=$K/adapt/SKHX_day2_$sgn zsh sim/final/prop_runs_log.sh > $K/adapt/SKHX_day2_$sgn.log 2>&1 ) &
done
wait; echo SKHX DONE
