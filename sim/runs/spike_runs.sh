#!/bin/zsh
# A wrong external price for a short time: the feed prints FRAC off for the length of each tag, then returns.
# Usage: [COINS=GOOGL] [TAGS="q30s q120s"] [FRAC=-0.05] [MARKS="today pkgm3q1800"] [S=dir] zsh sim/runs/spike_runs.sh
#   -> $S (default data/scen/spike): {tk,rd,orc,log}_<COIN>_<mark>_<tag>.csv, and _base for the same day with no wrong price.
cd "${0:A:h}/../.."
source $PWD/sim/times.zsh      # the moments of the replayed market-days
source $PWD/sim/pkgm_env.zsh   # the proposal's settings: pkgm3<k|q|r><seconds>
S=${S:-$PWD/data/scen/spike}   # after the cd above, as in every other runner
mkdir -p $S
run() { # coin mark tag spike
  local c=$1 mk=$2 n=$1_$2_$3 SZ=$2
  # a mark name ending in s20 keeps today's 20% slices; todayc = today's mark with the cut-back (the rule explorer's mixes)
  mk=${mk%s20}; [[ $mk == todayc ]] && mk=today
  local D L
  if [[ $c == GOOGL ]]; then D=data/prep_GOOGL_1028; L=20; T=${GOOGL_CLOSE}; else D=data/prep_AMZN_1029; L=20; T=${AMZN_CLOSE}; fi
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           ORC_OUT=$S/orc_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv TRIG_FIRED_OUT=$S/trig_$n.csv)
  local A=()
  [[ $mk == pkgm3* ]] && { X+=(${=$(pkgm_extra $mk)}); A=(liq_restore=2 restore_big=1); }
  [[ -n $4 ]] && X+=(EXT_SPIKE=$4)
  [[ $SZ == *s20 ]] && A=(); [[ $SZ == todayc ]] && A=(liq_restore=2 restore_big=1)
  env "${X[@]}" tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|memguard: peak" | sed "s/^/$n: /"
}
for c in ${=COINS:-GOOGL AMZN}; do
  if [[ $c == GOOGL ]]; then A=${GOOGL_CLOSE_10M}; Q=${GOOGL_EVE}; else A=${AMZN_CLOSE_10M}; Q=${AMZN_EVE}; fi
  for mk in ${=MARKS:-today noclamp et}; do
    run $c $mk base
    for tag in ${=TAGS:-a3s a30s q30s}; do
      local at=$A; [[ $tag == q* ]] && at=$Q
      run $c $mk $tag "$at;${${tag#?}%s};${FRAC:--0.05}"
    done
  done
done
