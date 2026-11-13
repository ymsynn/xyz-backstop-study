#!/bin/zsh
# A real crash while xyz's whole book stands still: from the onset of the Alphabet crash (October 28) every recorded
# order, modify and cancel is dropped for five minutes (engine switch ATTACK_FREEZE), so resting orders stay where they
# were and only the engine's own liquidations and fired triggers trade against them. The external price falls as
# recorded. This is the case the three-vote mark is weakest in: two of its three votes stay behind.
# Output FINAL_OUT/bookstill/still (default data/scen/final); the same replay without the freeze is data/scen/final/crash.
# Scored in docs/results/book_still.md.
cd "${0:A:h}/../.."; export PY=${PY:-python3}; K=${FINAL_OUT:-$PWD/data/scen/final}/bookstill; mkdir -p $K/still
source $PWD/sim/times.zsh      # the moments of the replayed market-days
export ATTACK_FREEZE="$((GOOGL_CLOSE + GOOGL_ONSET_MS - 5000));300"
EV="GOOGL/1028/20" S=$K/still DES="${DES:-today lead3q1800}" zsh sim/runs/liqbook_runs.sh > $K/still.log 2>&1
echo BOOK STILL DONE
