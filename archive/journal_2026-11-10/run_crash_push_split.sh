#!/bin/zsh
# 2026-11-11: crash book push (GOOGL 10-28, a margined account bids 6% above xyz's mid from 5 s before the crash), all five
# designs on the fixed engine (unrounded internal oracle, ONE_SIDED=quote), $1M and $5M, 60 s and 300 s.
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; P=python3; export ONE_SIDED=quote
for m in today pkgmint pkgm3k1800 pkgm3r1800 pkgm3q1800; do
  ( PY=$P MARKS="$m" CAPS="1e6 5e6" DS="60 300" S=$T/fl/push5 zsh $T/push/prop_runs_log.sh > $T/fl/push5/log_$m.txt 2>&1 ) &
done
wait; echo PUSH5 DONE; grep -l 'exit 101' $T/fl/push5/log_*.txt; df -h / | tail -1 | awk '{print "free:", $4}'
