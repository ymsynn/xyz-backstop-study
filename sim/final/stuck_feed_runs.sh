#!/bin/zsh
# Stuck feed: the external price freezes 5 s before each crash onset for FREEZE_S (default 120 s) while xyz trades on.
# Writes FINAL_OUT/stuck_f<FREEZE_S>/{tk,orc,log,rd}_{COIN}_freeze_{MARK}.csv (default data/scen/final/stuck_f120), scored
# by sim/final/score_final.py, or on their own: TK_DIR=data/scen/final/stuck_f120 python sim/score/takeover_score.py freeze_today
cd "${0:A:h}/../.."
source $PWD/sim/times.zsh      # the moments of the replayed market-days
source $PWD/sim/pkgm_env.zsh   # the proposal's settings: pkgm3<k|q|r><seconds>
R=${FINAL_OUT:-$PWD/data/scen/final}/stuck_f${FREEZE_S:-120}; mkdir -p $R
run() { # coin mark
  local c=$1 mk=$2 D L T O
  case $c in
    GOOGL) D=data/prep_GOOGL_1028; L=20; T=${GOOGL_CLOSE}; O=${GOOGL_ONSET_MS};;
    INTC)  D=data/prep_INTC_1029;  L=10; T=${AMZN_CLOSE}; O=${INTC_ONSET_MS};;
    AMZN)  D=data/prep_AMZN_1029;  L=20; T=${AMZN_CLOSE}; O=${AMZN_ONSET_MS};;
  esac
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           SIM_TK_OUT=$R/tk_${c}_freeze_$mk.csv ORC_OUT=$R/orc_${c}_freeze_$mk.csv VAULT_LOG=$R/log_${c}_freeze_$mk.csv ROUNDS_OUT=$R/rd_${c}_freeze_$mk.csv EXT_FREEZE="$((T + O - 5000));${FREEZE_S:-120}")
  local A=()
  [[ $mk == pkgm3* ]] && { X+=(${=$(pkgm_extra $mk)}); A=(liq_restore=2 restore_big=1); }
  env "${X[@]}" tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "OWN MARK|memguard: peak" | sed "s/^/$c $mk: /"
}
for c in GOOGL INTC AMZN; do for mk in ${=MARKS:-today et p3 p4}; do run $c $mk; done; done
