#!/bin/zsh
# xyz push beyond the band: an attacker prints wash trades at the pre-crash price during the GOOGL 10-28 crash, so that P (the
# xyz trade median) disagrees with the falling feed by more than the band and P4's centre holds. Book untouched.
# Runs: mark x {base, W$ per relayer update for D s from onset - 5 s}. Usage: MARKS="today et p4 p4b" WS="1e6" DS="60 300 900" zsh sim/wash_runs.sh
cd ${REPO:-$PWD}
source $PWD/sim/pkgm_env.zsh   # core-package variant names (pkgm, pkgm100, pkgmd250v, ...)
S=${S:-$PWD/data/scen/wash}; mkdir -p $S
D=data/prep_GOOGL_1028; L=20; T=1793217600000; A=${WASH_AT:-$((1793217718800 - 5000))}   # WASH_AT: start (ms)
run() { # mark tag [wash]
  local n=GOOGL_$1_$2
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           ORC_OUT=$S/orc_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv TRIG_FIRED_OUT=$S/trig_$n.csv)
  local O=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30)
  [[ $1 == et ]] && X+=($O)
  [[ $1 == p4 ]] && X+=($O OWN_GATE=1)
  [[ $1 == p4b ]] && X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000})
  [[ $1 == p4c ]] && X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150})
  [[ $1 == p4d ]] && X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1)
  local A=()
  [[ $1 == pkg ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgc ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_CAP=1); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgt ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgz ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgy ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=oracle OWN_FROZEN_UPD=2); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgw ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgv ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgk ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(python3 sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); }
  # pkgm family: core package and its variants (sim/pkgm_env.zsh)
  [[ $1 == pkgm* ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(python3 sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); X+=(${=$(pkgm_extra $1)}); }
  [[ $1 == pkgx ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_P_EMA_S=150 OWN_P_EMA_HOLD_RAW=1); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkge ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_P_EMA_S=150); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgs ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgtc ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_HOLD_CAP=1); A=(liq_restore=2 restore_big=1); }
  [[ -n $3 ]] && X+=(WASH=$3)
  [[ -n $3 && -n $CAP ]] && X+=(ATTACK_CAP=$CAP)   # faithful: two margined attacker accounts trade on the book
  env "${X[@]}" tools/memguard.sh 6000 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|OWN MARK|takeovers|ATTACKER|WASH FAITHFUL|memguard: peak" | sed "s/^/$n: /"
}
for mk in ${=MARKS:-today et p4 p4b}; do
  [[ -f $S/tk_GOOGL_${mk}_base.csv ]] || run $mk base
  for w in ${=WS:-1e6}; do for d in ${=DS:-60 300 900}; do run $mk w${w}_f${F:-0}_d$d "$A;$d;${F:-0};$w"; done; done
done
echo WASH DONE
