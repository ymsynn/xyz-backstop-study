#!/bin/zsh
# The tests added after the final run, on Alphabet, October 28, into FINAL_OUT (default data/scen/final):
#   longprint/  the external price fed 20% low from 18:30 ET for 2, 5 and 15 minutes (docs/results/long_wrong_price.md)
#   worstcase/  the same 15-minute wrong price, plus from 15 s in a margined attacker pushing xyz's book 10% down for 45 s,
#               with $1M and $5M of capital (docs/results/worst_case_wrong_price_and_push.md)
#   bookstill/  xyz's whole book standing still for five minutes from the crash onset (sim/final/book_still.sh)
# M / D: the rule sets, as in run_final.sh (mark-run ids / liquidation-replay ids). The run without the correction step:
#   FINAL_OUT=$PWD/data/scen/final_k M=pkgm3k1800 D=lead3k1800 zsh sim/final/side_runs.sh
# Usage: [FINAL_OUT=dir] [M="today pkgm3q1800"] [D="today lead3q1800"] zsh sim/final/side_runs.sh
cd "${0:A:h}/../.."; export PY=${PY:-python3}
source $PWD/sim/times.zsh      # the moments of the replayed market-days
K=${FINAL_OUT:-$PWD/data/scen/final}; M=${M:-today pkgm3q1800}; D=${D:-today lead3q1800}; mkdir -p $K/longprint $K/worstcase
Q=${GOOGL_EVE}
( COINS=GOOGL TAGS="q120s q300s q900s" FRAC=-0.20 MARKS="$M" S=$K/longprint zsh sim/runs/spike_runs.sh > $K/longprint.log 2>&1 ) &
( EXT_SPIKE="$Q;900;-0.20" PROP_C=GOOGL PROP_D=data/prep_GOOGL_1028 PROP_L=20 PROP_T=0 PROP_AT=$((Q + 15000)) F=-0.10 \
    CAPS="1e6 5e6" DS="45" MARKS="$M" S=$K/worstcase zsh sim/final/book_push_runs.sh > $K/worstcase.log 2>&1 ) &
( FINAL_OUT=$K DES="$D" zsh sim/final/book_still.sh > /dev/null 2>&1 ) &
wait
echo SIDE RUNS DONE
