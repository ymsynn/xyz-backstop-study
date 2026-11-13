#!/bin/zsh
# Checks of 2026-11-10 (night): adaptive attack on the ratchet, normal sessions, anchor length. Outputs in data/scen/tests_1110g.
cd ${REPO:-$PWD}; T=${REPO:-$PWD}/data/scen/tests_1110g; F=${REPO:-$PWD}/data/scen/tests_1110f; P=python3
M4="today pkgmint pkgm3k1800 pkgm3r1800"
# 1. feed walked +10% over 30 s and held 120 s; once the walk is complete an attacker ($1M / $5M, margined) bids 10% above
#    xyz's mid for 15 s / 60 s, so xyz's book confirms the walked feed. Base of each mark = the walk alone.
( PY=$P MARKS="$M4" EXT_RAMP="1793226600000;30;+0.10;120" PROP_AT=1793226630000 F=0.10 CAPS="1e6 5e6" DS="15 60" S=$T/adapt_day zsh $F/push/prop_runs_log.sh > $T/adapt_day.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M4" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;+0.10;120" PROP_AT=1793163630000 F=0.10 CAPS="1e6 5e6" DS="15 60" S=$T/adapt_night zsh $F/push/prop_runs_log.sh > $T/adapt_night.log 2>&1 ) &
wait
# 2. normal sessions (out-of-hours, crash windows excluded): mark vs today's
( PY=$P MARKS="today pkgmint pkgm3r1800" S=$T/normal zsh sim/normal_runs.sh > $T/normal.log 2>&1 ) &
# 3. anchor length 15 / 60 min on the tests that depend on it
for tau in 900 3600; do
  M=pkgm3r$tau; D=lead3r$tau; K=$T/tau/$tau; mkdir -p $K/r_dn $K/crash $K/skhx $K/spike $K/onw
  ( PY=$P MARKS="$M" S=$K/r_dn zsh sim/ramp_runs.sh > $K/r_dn.log 2>&1
    RELAYER_WARMUP_S=57600 PY=$P MARKS="$M" COINS=GOOGL RAMP_AT=1793163600000 TAGS="w30 w300" S=$K/onw zsh $F/ramp_overnight.sh > $K/onw.log 2>&1
    PY=$P MARKS="$M" CAPS="5e6" DS="60 300" S=$K/push zsh $F/push/prop_runs_log.sh > $K/push.log 2>&1
    PY=$P MARKS="$M" S=$K/spike zsh sim/spike_runs.sh > $K/spike.log 2>&1 ) &
done
wait
for tau in 900 3600; do D=lead3r$tau; K=$T/tau/$tau
  for ev in GOOGL/1028/20 INTC/1029/10 AMZN/1029/20; do ( PY=$P EV="$ev" S=$K/crash DES="$D" zsh sim/liqbook_runs.sh > $K/crash/log_${ev%%/*}.txt 2>&1 ) & done
  ( RELAYER_WARMUP_S=43200 PY=$P EV="SKHX/0727/10" S=$K/skhx DES="$D" zsh sim/liqbook_runs.sh > $K/skhx.log 2>&1 ) &
  wait
done
echo CHECKS DONE; grep -c 'exit 101' $T/*.log $T/tau/*/*.log | grep -v ':0'; df -h / | tail -1 | awk '{print "free:", $4}'
