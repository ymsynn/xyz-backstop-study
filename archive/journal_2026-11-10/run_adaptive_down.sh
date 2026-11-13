#!/bin/zsh
# Check of 2026-11-10 (night), downward adaptive attack: feed walked -10% over 30 s and held 120 s; once the walk is complete
# a margined attacker ($1M / $5M) offers 10% below xyz's mid for 15 s / 60 s, so xyz's book confirms the walked feed.
# Needs the sell-side ATTACK_PROP (frac < 0). Base of each mark = the walk alone. Outputs in data/scen/tests_1110h.
cd ${REPO:-$PWD}; T=${REPO:-$PWD}/data/scen/tests_1110h; F=${REPO:-$PWD}/data/scen/tests_1110f; P=python3
M4="today pkgmint pkgm3k1800 pkgm3r1800"
( PY=$P MARKS="$M4" EXT_RAMP="1793226600000;30;-0.10;120" PROP_AT=1793226630000 F=-0.10 CAPS="1e6 5e6" DS="15 60" S=$T/adapt_day zsh $F/push/prop_runs_log.sh > $T/adapt_day.log 2>&1 ) &
( RELAYER_WARMUP_S=57600 PY=$P MARKS="$M4" PROP_T=1793146200000 EXT_RAMP="1793163600000;30;-0.10;120" PROP_AT=1793163630000 F=-0.10 CAPS="1e6 5e6" DS="15 60" S=$T/adapt_night zsh $F/push/prop_runs_log.sh > $T/adapt_night.log 2>&1 ) &
wait
echo DOWN DONE; grep -c 'exit 101' $T/*.log | grep -v ':0'; df -h / | tail -1 | awk '{print "free:", $4}'
