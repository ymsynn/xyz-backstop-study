#!/bin/zsh
# xyz's resting book depth every minute, by distance from the mid (10 bp to 20%), on every local market-day: the real book,
# rebuilt from the tape (engine replay, no simulated design). Output data/scen/depth/depth_{COIN}_{DAY}.csv (h, ms, mid, side, dbps, ntl).
cd "${0:A:h}/../.."; O=$PWD/data/scen/depth; mkdir -p $O; k=0
for d in data/prep_*_[0-9][0-9][0-9][0-9]; do
  n=${${d:t}#prep_}
  ( TRIGGERS=simulate SILENT=1 DEPTH_OUT=$O/depth_$n.csv tools/memguard.sh 12 engine/target/release/engine replay $d tape_walk > $O/log_$n.txt 2>&1 ) &
  k=$((k+1)); (( k % 6 == 0 )) && wait
done
wait; echo DEPTH DONE; ls $O/depth_*.csv | wc -l
