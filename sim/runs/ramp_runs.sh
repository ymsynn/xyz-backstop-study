#!/bin/zsh
# Walking external feed: E drifts linearly to FRAC (default -10%) over the ramp, stays there HOLD_S (default 120 s), then
# snaps back, on GOOGL 10-28 and AMZN 10-29. A slow manipulation of the external market never makes a single-update jump.
# The walk starts at 18:30 ET (the bad-print time of sim/runs/spike_runs.sh) unless RAMP_AT says otherwise; the overnight
# runs of the paper set RAMP_AT to a closed-venue time and widen the relayer's warm-up (see sim/final/run_final.sh).
# Usage: [MARKS=...] [TAGS="w15 w30 w60 w300"] [RAMP_AT=ms] zsh sim/runs/ramp_runs.sh
#     -> data/scen/ramp/{orc,tk,rd,trig}_{COIN}_{MARK}_{TAG}.csv
cd "${0:A:h}/../.."
source $PWD/sim/times.zsh      # the moments of the replayed market-days
source $PWD/sim/pkgm_env.zsh   # the proposal's settings: pkgm3<k|q|r><seconds>
S=${S:-$PWD/data/scen/ramp}; mkdir -p $S
run() { # coin mark tag ramp
  local c=$1 mk=$2 n=$1_$2_$3 D L SZ=$2
  # a mark name ending in s20 keeps today's 20% slices; todayc = today's mark with the cut-back (the rule explorer's mixes)
  mk=${mk%s20}; [[ $mk == todayc ]] && mk=today
  if [[ $c == GOOGL ]]; then D=data/prep_GOOGL_1028; L=20; else D=data/prep_AMZN_1029; L=20; fi
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           ORC_OUT=$S/orc_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv TRIG_FIRED_OUT=$S/trig_$n.csv)
  local A=()
  [[ $mk == pkgm3* ]] && { X+=(${=$(pkgm_extra $mk)}); A=(liq_restore=2 restore_big=1); }
  [[ $SZ == *s20 ]] && A=(); [[ $SZ == todayc ]] && A=(liq_restore=2 restore_big=1)
  [[ -n $4 ]] && X+=(EXT_RAMP=$4)
  # DUST=ntl: an attacker's dust trade of ntl at every relayer update for the whole walk (keeps a trade-count freshness alive)
  [[ -n $4 && -n $DUST ]] && X+=(WASH="$Q;$(( ${3#w} + ${HOLD_S:-120} ));0;$DUST")
  env "${X[@]}" tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|OWN MARK|memguard: peak" | sed -E "s/OWN MARK.*divergence holds/divergence holds/; s/^/$n: /"
}
for c in ${=COINS:-GOOGL AMZN}; do
  if [[ $c == GOOGL ]]; then Q=${RAMP_AT:-${GOOGL_EVE}}; else Q=${RAMP_AT:-${AMZN_EVE}}; fi
  for mk in ${=MARKS:-today pkgm3q1800}; do
    [[ -f $S/tk_${c}_${mk}_base.csv ]] || run $c $mk base
    for tag in ${=TAGS:-w15 w30 w60 w300}; do run $c $mk $tag "$Q;${tag#w};${FRAC:--0.10};${HOLD_S:-120}"; done
  done
done
echo RAMP DONE
