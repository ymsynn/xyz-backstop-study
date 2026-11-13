#!/bin/zsh
# P4 test batch: bad prints at -5% and -20% (3 s, 30 s, 5 min) for today / ET / P3 N=20 / P4, then combine with earlier runs.
cd ${REPO:-$PWD}
for F in 5 20; do
  S=$PWD/data/scen/spikeP4_$F
  MARKS=p4 TAGS="a3s a30s q30s q300s" FRAC=-0.$( [[ $F == 5 ]] && echo 05 || echo 20 ) S=$S zsh sim/spike_runs.sh
  MARKS="today et" TAGS="q300s" FRAC=-0.$( [[ $F == 5 ]] && echo 05 || echo 20 ) S=$S zsh sim/spike_runs.sh
  MARKS="p3" ANCHOR_N=20 TAGS="q300s" FRAC=-0.$( [[ $F == 5 ]] && echo 05 || echo 20 ) S=$S zsh sim/spike_runs.sh
done
echo DONE
