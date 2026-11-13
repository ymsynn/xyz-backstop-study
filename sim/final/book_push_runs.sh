#!/bin/zsh
# Book prop beyond the band: a fresh attacker account keeps a buy limit at P0 = mid x (1 + F) during the GOOGL 10-28 crash,
# re-placed every block (lifts all asks <= P0, rests the rest). Usage: MARKS="today et p4 p4b" NS="2e5 1e6" DS="60 300" F=0.06 zsh sim/final/book_push_runs.sh
cd "${0:A:h}/../.."
source $PWD/sim/times.zsh      # the moments of the replayed market-days
source $PWD/sim/pkgm_env.zsh   # the proposal's settings: pkgm3<k|q|r><seconds>
S=${S:-$PWD/data/scen/book_push}; mkdir -p $S   # every runner of the paper passes S; this is the bare-run default
# PROP_C / PROP_D / PROP_L / PROP_T: another coin's prep, max leverage and own-mark start (default the GOOGL 10-28 crash)
C=${PROP_C:-GOOGL}; D=${PROP_D:-data/prep_GOOGL_1028}; L=${PROP_L:-20}; T=${PROP_T:-${GOOGL_CLOSE}}
A=${PROP_AT:-$((GOOGL_CLOSE + GOOGL_ONSET_MS - 5000))}   # PROP_AT: start (ms), e.g. inside a venue closure
run() {
  local n=${C}_$1_$2 SZ=$1 MK=${1%s20}
  # a mark name ending in s20 keeps today's 20% slices; todayc = today's mark with the cut-back (the rule explorer's mixes)
  [[ $MK == todayc ]] && MK=today; set -- $MK "${@:2}"
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           ORC_OUT=$S/orc_$n.csv VAULT_LOG=$S/log_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv TRIG_FIRED_OUT=$S/trig_$n.csv)
  local A=()
  [[ $1 == pkgm3* ]] && { X+=(${=$(pkgm_extra $1)}); A=(liq_restore=2 restore_big=1); }
  [[ $SZ == *s20 ]] && A=(); [[ $SZ == todayc ]] && A=(liq_restore=2 restore_big=1)
  [[ -n $3 ]] && X+=(ATTACK_PROP=$3)
  env "${X[@]}" tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "PROP:|PROP ACCOUNT|band held|takeover notional|memguard: peak" | sed -E "s/OWN MARK.*band held/band held/; s/^/$n: /"
}
for mk in ${=MARKS:-today et p4 p4b}; do
  [[ -f $S/tk_${C}_${mk}_base.csv ]] || run $mk base
  if [[ -n $CAPS ]]; then   # faithful attacker: a margined clearing account with this capital, bidding up to $5M per block
    for c in ${=CAPS}; do for d in ${=DS:-60 300}; do run $mk c${c}_f${F:-0.06}_d$d "$A;$d;${F:-0.06};5e6;$c"; done; done
  else
    for w in ${=NS:-2e5 1e6}; do for d in ${=DS:-60 300}; do run $mk p${w}_f${F:-0.06}_d$d "$A;$d;${F:-0.06};$w"; done; done
  fi
done
echo PROP DONE
