#!/bin/zsh
# 2026-11-11: ONE_SIDED=quote (the rule the tape shows: with one side of the book empty, the remaining best quote stands for
# the book price) on the tests that decide the ratchet: overnight and day adaptive attack (down), crash book push.
cd ${REPO:-$PWD}; T=${REPO:-$PWD}/data/scen/tests_1110k; F=${REPO:-$PWD}/data/scen/tests_1110f; P=python3
M="today pkgmint pkgm3k1800 pkgm3r1800 pkgm3q1800"; export ONE_SIDED=quote
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;-0.10;120" PROP_AT=1793163630000 F=-0.10 CAPS="1e6" DS="15 60" S=$T/night zsh $F/push/prop_runs_log.sh > $T/night.log 2>&1 ) &
( PY=$P MARKS="$M" EXT_RAMP="1793226600000;30;-0.10;120" PROP_AT=1793226630000 F=-0.10 CAPS="5e6" DS="60" S=$T/day zsh $F/push/prop_runs_log.sh > $T/day.log 2>&1 ) &
( PY=$P MARKS="$M" CAPS="5e6" DS="60 300" S=$T/push zsh $F/push/prop_runs_log.sh > $T/push.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;+0.10;120" PROP_AT=1793163630000 F=0.10 CAPS="1e6" DS="60" S=$T/night_up zsh $F/push/prop_runs_log.sh > $T/night_up.log 2>&1 ) &
wait
echo QUOTE DONE; grep -c 'exit 101' $T/*.log | grep -v ':0'; df -h / | tail -1 | awk '{print "free:", $4}'
