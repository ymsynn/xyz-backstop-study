#!/bin/zsh
# Replays for the rule explorer on the attack tests, for every combination beyond today's rules and the proposal: the
# three-vote mark with each averaging time and anchor rule, under both liquidation sizings, and today's mark with the
# cut-back. Each job is one attacked replay and its reference without the attack, run by the paper's own runners.
#   pkgm3<k|q|r><seconds>[s20]   as in viewer/run_grid.sh;  todayc = today's mark with the cut-back
# Usage: [PAR=3] zsh viewer/run_attacks.sh   -> data/scen/explorer/{spike,onw,closed_CL,closed_GOLD,quiet_up}
#        then: python viewer/build_data.py
cd "${0:A:h}/.."
K=$PWD/data/scen/explorer; P=sim/final/book_push_runs.sh; PAR=${PAR:-3}
mkdir -p $K/spike $K/onw $K/closed_CL $K/closed_GOLD $K/quiet_up
marks=(todayc)
for tau in ${=TAUS:-300 1800 7200}; do for x in k q r; do
  [[ $x$tau == q1800 ]] || marks+=(pkgm3$x$tau)           # the proposal itself is in the paper's run
  marks+=(pkgm3$x${tau}s20)
done; done
job() { # test mark
  case $1 in
    spike)       [[ -s $K/spike/orc_GOOGL_$2_q30s.csv ]] || COINS=GOOGL TAGS=q30s MARKS=$2 S=$K/spike zsh sim/runs/spike_runs.sh;;
    onw)         [[ -s $K/onw/orc_GOOGL_$2_w30.csv ]] || RELAYER_WARMUP_S=57600 MARKS=$2 COINS=GOOGL RAMP_AT=${GOOGL_NIGHT} TAGS=w30 S=$K/onw zsh sim/runs/ramp_runs.sh;;
    closed_CL)   [[ -s $K/closed_CL/orc_CL_$2_c5e6_f0.06_d900.csv ]] || S=$K/closed_CL PROP_C=CL PROP_D=data/prep_CL_0910 PROP_L=20 PROP_T=0 PROP_AT=${CL_CLOSED} MARKS=$2 CAPS=5e6 DS=900 F=0.06 zsh $P;;
    closed_GOLD) [[ -s $K/closed_GOLD/orc_GOLD_$2_c5e6_f0.06_d900.csv ]] || S=$K/closed_GOLD PROP_C=GOLD PROP_D=data/prep_GOLD_1030 PROP_L=25 PROP_T=0 PROP_AT=${GOLD_EVE} MARKS=$2 CAPS=5e6 DS=900 F=0.06 zsh $P;;
    quiet_up)    [[ -s $K/quiet_up/orc_GOOGL_$2_c5e6_f0.06_d9000.csv ]] || RELAYER_WARMUP_S=57600 MARKS=$2 PROP_T=${GOOGL_PREV_EVE} EXT_FREEZE="${GOOGL_NIGHT};10800" PROP_AT=${GOOGL_NIGHT_10M} CAPS=5e6 DS=9000 F=0.06 S=$K/quiet_up zsh $P;;
  esac
}
# one job per line through xargs, which starts at most PAR at a time (a count of background jobs taken inside $(...) is
# always zero in zsh, so a loop throttled that way starts everything at once)
if [[ $1 == --job ]]; then
  [[ -n $DRY ]] && { echo "start $2 $3"; sleep 2; exit 0; }
  job $2 $3 > $K/$2/run_$3.log 2>&1; exit 0
fi
for t in ${=TESTS:-spike onw closed_CL closed_GOLD quiet_up}; do for m in $marks; do print -r -- "$t $m"; done; done \
  | xargs -P $PAR -L 1 zsh ${0:A} --job
echo ATTACKS DONE
