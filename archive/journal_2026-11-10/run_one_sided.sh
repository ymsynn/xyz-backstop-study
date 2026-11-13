#!/bin/zsh
# 2026-11-10 night: one-sided book conventions (ONE_SIDED=last | drop; unset = mark unchanged, the runs of tests_1110h / i) on
# the downward adaptive attack, where the attacker empties the bid side. Overnight $1M, day $5M.
cd ${REPO:-$PWD}; T=${REPO:-$PWD}/data/scen/tests_1110j; F=${REPO:-$PWD}/data/scen/tests_1110f; P=python3
M="today pkgmint pkgm3k1800 pkgm3r1800 pkgm3q1800"
for o in last drop; do
  ( export ONE_SIDED=$o; RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;-0.10;120" PROP_AT=1793163630000 F=-0.10 CAPS="1e6" DS="15 60" S=$T/night_$o zsh $F/push/prop_runs_log.sh > $T/night_$o.log 2>&1 ) &
  ( export ONE_SIDED=$o; PY=$P MARKS="$M" EXT_RAMP="1793226600000;30;-0.10;120" PROP_AT=1793226630000 F=-0.10 CAPS="5e6" DS="60" S=$T/day_$o zsh $F/push/prop_runs_log.sh > $T/day_$o.log 2>&1 ) &
done
wait
echo ONESIDED DONE; grep -c 'exit 101' $T/*.log | grep -v ':0'; df -h / | tail -1 | awk '{print "free:", $4}'
