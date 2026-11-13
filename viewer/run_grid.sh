#!/bin/zsh
# Replays for the rule explorer beyond today's rules and the proposal: the three-vote mark with each averaging time and each
# anchor rule, under both liquidation sizings, on the crash market-days. Each replay is one run of the engine through
# sim/runs/liqbook_runs.sh; the combinations already in the paper's run (data/scen/final) are not repeated.
#   lead3<k|q|r><seconds>[s20]   k = the average is never brought back to the mark, q = unless the book alone decided the
#                                last mark (the proposal), r = always; s20 = today's 20% slices instead of the cut-back
# Usage: [EVENTS="GOOGL/1028/20 INTC/1029/10 AMZN/1029/20"] [TAUS="300 1800 7200"] [PAR=4] zsh viewer/run_grid.sh
#        -> data/scen/explorer/crash, then: python viewer/build_data.py
cd "${0:A:h}/.."
S=$PWD/data/scen/explorer/crash; mkdir -p $S
des=()
for tau in ${=TAUS:-300 1800 7200}; do for x in k q r; do for z in "" s20; do
  [[ $x$tau == q1800 ]] && continue                       # the proposal's mark: both sizings are in the paper's run
  des+=(lead3$x$tau$z)
done; done; done
PAR=${PAR:-4}
for ev in ${=EVENTS:-GOOGL/1028/20 INTC/1029/10 AMZN/1029/20}; do
  for i in {1..$PAR}; do
    mine=(); for j in {1..$#des}; do (( (j - 1) % PAR == i - 1 )) && [[ ! -s $S/orc_${ev%%/*}_${${ev#*/}%%/*}_$des[j].csv ]] && mine+=($des[j]); done
    (( $#mine )) && ( EV="$ev" S=$S DES="$mine" zsh sim/runs/liqbook_runs.sh > $S/log_${ev%%/*}_$i.txt 2>&1 ) &
  done
  wait
done
echo GRID DONE
