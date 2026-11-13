#!/bin/zsh
# 2026-11-11: anchor band (the mark never further than a band from the plain 30 min average of the feed's vote), a test that
# reopens the frozen formula. Variants: pkgm3u (no ratchet, band 1/maxLev), pkgm3v (book-aware ratchet, band 1/maxLev),
# pkgm3s (book-aware, half band); champion pkgm3q beside them. Tests: the three crashes and SK Hynix (the cost of a slower
# mark), the walk and the combined attack (what the band buys), the crash push, the bad print.
cd ${REPO:-$PWD}; export FINAL_OUT=$PWD/data/scen/band; K=$FINAL_OUT; mkdir -p $K/crash $K/adapt
export PY=${PY:-python3}; F=sim/final; P=$F/prop_runs_log.sh
M="pkgm3q1800 pkgm3u1800 pkgm3v1800 pkgm3s1800"; D="lead3q1800 lead3u1800 lead3v1800 lead3s1800"
for ev in GOOGL/1028/20 INTC/1029/10 AMZN/1029/20; do ( EV="$ev" S=$K/crash DES="$D" zsh sim/liqbook_runs.sh > $K/crash/log_${ev%%/*}.txt 2>&1 ) & done
( RELAYER_WARMUP_S=43200 EV="SKHX/0727/10" S=$K/skhx DES="$D" zsh sim/liqbook_runs.sh > $K/skhx.log 2>&1 ) &
( MARKS="$M" S=$K/r_dn zsh sim/ramp_runs.sh > $K/r_dn.log 2>&1 ) &
( MARKS="$M" S=$K/spike zsh sim/spike_runs.sh > $K/spike.log 2>&1 ) &
( MARKS="$M" CAPS="5e6" DS="60 300" S=$K/push zsh $P > $K/push.log 2>&1 ) &
wait
adapt() { ( [[ -n ${10} ]] && export RELAYER_WARMUP_S=${10}
    PROP_C=$1 PROP_D=$2 PROP_L=$3 PROP_T=$4 EXT_RAMP="$5;30;$7;120" PROP_AT=$(($5 + 30000)) F=$7 CAPS="$8" DS="$9" MARKS="$M" S=$K/adapt/$1_$6 zsh $P > $K/adapt/$1_$6.log 2>&1 ) & }
adapt GOOGL data/prep_GOOGL_1028 20 1793146200000 1793163600000 night_dn -0.10 1e6 "15 60" 57600
adapt GOOGL data/prep_GOOGL_1028 20 1793217600000 1793226600000 day_dn -0.10 5e6 "15 60" ""
adapt GOOGL data/prep_GOOGL_1028 20 1793146200000 1793163600000 night_up +0.10 1e6 "60" 57600
adapt INTC data/prep_INTC_1029 10 1793304000000 1793313000000 day_dn -0.10 5e6 "60" ""
adapt SKHX data/prep_SKHX_0727 10 1785111000000 1785121200000 day2_dn -0.10 5e6 "60" 86400
( RELAYER_WARMUP_S=57600 MARKS="$M" COINS=GOOGL RAMP_AT=1793163600000 TAGS="w30 w300" S=$K/onw zsh $F/ramp_overnight.sh > $K/onw.log 2>&1 ) &
wait
echo BAND DONE; grep -l 'exit 101' $K/*.log $K/*/*.txt $K/*/*.log 2>/dev/null; df -h / | tail -1 | awk '{print "free:", $4}'
