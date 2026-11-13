#!/bin/zsh
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; PY=python3
while pgrep -f 'ramp_overnight.sh|sim/prop_runs.sh' > /dev/null; do sleep 20; done
( zsh $T/reval_oos.sh GOOGL 1022 20; zsh $T/reval_oos.sh META 1022 20; zsh $T/reval_oos.sh SPCX 1030 20 ) &
( zsh $T/reval_oos.sh SILVER 1022 25; zsh $T/reval_oos.sh GOLD 1030 25 ) &
( zsh $T/reval_oos.sh BRENTOIL 0910 20; zsh $T/reval_oos.sh CL 0910 20 ) &
wait
# closed-session wick attack, as in the earlier runs: CL in its daily close (21:10 UTC), GOLD in the weekend (Fri 22:00 UTC)
M="today pkgmint pkgm3e1800"
( S=$T/closed_CL PY=$PY PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=1789074600000 MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $T/closed_CL.log 2>&1 ) &
( S=$T/closed_GOLD PY=$PY PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=1793397600000 MARKS="$M" CAPS="1e6 5e6" DS="60 240 900" F=0.06 zsh sim/prop_runs.sh > $T/closed_GOLD.log 2>&1 ) &
wait; echo ALL DONE; df -h / | tail -1 | awk '{print "free:", $4}'
