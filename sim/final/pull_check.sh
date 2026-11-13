#!/bin/zsh
# A real crash while the largest market makers are gone: at the onset of the Alphabet crash (28 October) the resting orders
# of the 5 or 20 largest makers are cancelled and their new orders dropped for five minutes. Does xyz's book still follow
# the external price, and does the proposal's mark stay with it? Makers ranked by maker volume from 5 minutes before to
# 10 minutes after 20:00 UTC. Output FINAL_OUT/pullcheck/ (default data/scen/final), {none,top5,top20}; scored in docs/results/makers_pulled.md.
cd "${0:A:h}/../.."; export PY=${PY:-python3}; K=${FINAL_OUT:-$PWD/data/scen/final}/pullcheck; mkdir -p $K
read T5 T20 <<< $($PY -c "
[[ -n $T5 && -n $T20 ]] || { print -u2 "pull_check: the maker ranking produced nothing; without it every tag would run as the control"; exit 1 }
import polars as pl
r = pl.read_ipc('data/prep_GOOGL_1028/real_fills.arrow', memory_map=False); T = 1793217600000
g = (r.filter((pl.col('ms') >= T - 300000) & (pl.col('ms') < T + 600000)).with_columns(n=pl.col('sz') / 1e6 * pl.col('px') / 1e6)
      .group_by('m_u').agg(pl.col('n').sum()).sort('n', descending=True))
print(','.join(map(str, g['m_u'][:5].to_list())), ','.join(map(str, g['m_u'][:20].to_list())))")
ON=$((1793217600000 + 118800 - 5000))
for tag in none top5 top20; do
  ( [[ $tag == top5 ]] && export ATTACK_PULL="$T5;$ON;300"; [[ $tag == top20 ]] && export ATTACK_PULL="$T20;$ON;300"
    EV="GOOGL/1028/20" S=$K/$tag DES="today lead3q1800" zsh sim/runs/liqbook_runs.sh > $K/$tag.log 2>&1 ) &
done; wait; echo PULL CHECK DONE
