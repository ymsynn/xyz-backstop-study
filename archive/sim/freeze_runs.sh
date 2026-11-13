#!/bin/zsh
# Stuck feed: the external price freezes 5 s before each crash onset for FREEZE_S (default 120 s) while xyz trades on.
# Writes data/scen/runs/tk_{COIN}_freeze_{MARK}.csv for takeover_score.py.
cd ${REPO:-$PWD}
source $PWD/sim/pkgm_env.zsh   # core-package variant names (pkgm, pkgm100, pkgmd250v, ...)
R=data/scen/runs
run() { # coin mark
  local c=$1 mk=$2 D L T O
  case $c in
    GOOGL) D=data/prep_GOOGL_1028; L=20; T=1793217600000; O=118800;;
    INTC)  D=data/prep_INTC_1029;  L=10; T=1793304000000; O=66800;;
    AMZN)  D=data/prep_AMZN_1029;  L=20; T=1793304000000; O=63900;;
  esac
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           SIM_TK_OUT=$R/tk_${c}_freeze_$mk.csv EXT_FREEZE="$((T + O - 5000));${FREEZE_S:-120}")
  [[ $mk == today ]] && :
  [[ $mk == et ]] && X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30)
  [[ $mk == p4 ]] && X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=1)
  [[ $mk == p3 ]] && X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_ANCHOR_N=20)
  [[ $mk == p4b ]] && X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000})
  [[ $mk == p4c ]] && X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150})
  [[ $mk == p4d ]] && X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1)
  local A=()
  [[ $mk == pkg ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgc ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_CAP=1); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgt ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgz ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgy ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=oracle OWN_FROZEN_UPD=2); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgw ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgv ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgk ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(python3 sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); }
  # pkgm: core package; pkgmd250 / pkgmd250s: + divergence holds at 2.5% / + step only while xyz's price is stale
  [[ $mk == pkgm* ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(python3 sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); X+=(${=$(pkgm_extra $mk)}); }
  [[ $mk == pkgx ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_P_EMA_S=150 OWN_P_EMA_HOLD_RAW=1); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkge ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_P_EMA_S=150); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgs ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2); A=(liq_restore=2 restore_big=1); }
  [[ $mk == pkgtc ]] && { X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_HOLD_CAP=1); A=(liq_restore=2 restore_big=1); }
  env "${X[@]}" tools/memguard.sh 6000 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "OWN MARK|memguard: peak" | sed "s/^/$c $mk: /"
}
for c in GOOGL INTC AMZN; do for mk in ${=MARKS:-today et p3 p4}; do run $c $mk; done; done
