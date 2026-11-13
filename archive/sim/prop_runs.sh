#!/bin/zsh
# Book prop beyond the band: a fresh attacker account keeps a buy limit at P0 = mid x (1 + F) during the GOOGL 10-28 crash,
# re-placed every block (lifts all asks <= P0, rests the rest). Usage: MARKS="today et p4 p4b" NS="2e5 1e6" DS="60 300" F=0.06 zsh sim/prop_runs.sh
cd "${0:A:h}/.."
source $PWD/sim/pkgm_env.zsh   # core-package variant names (pkgm, pkgm100, pkgmd250v, ...)
S=${S:-$PWD/data/scen/wash}; mkdir -p $S
# PROP_C / PROP_D / PROP_L / PROP_T: another coin's prep, max leverage and own-mark start (default the GOOGL 10-28 crash)
C=${PROP_C:-GOOGL}; D=${PROP_D:-data/prep_GOOGL_1028}; L=${PROP_L:-20}; T=${PROP_T:-1793217600000}
A=${PROP_AT:-$((1793217718800 - 5000))}   # PROP_AT: start (ms), e.g. inside a venue closure
run() {
  local n=${C}_$1_$2
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
  [[ $1 == pkgk ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(${PY:-python3} sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); }
  # pkgm: core package (no fair sweep); pkgm050/100/200: + internal-oracle input cap 0.5 / 1 / 2 %
  [[ $1 == pkgm* ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(${PY:-python3} sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); X+=(${=$(pkgm_extra $1)}); }
  [[ $1 == pkgb ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(${PY:-python3} sim/closed_windows.py --prep $D) RELAYER_INTERNAL="$(${PY:-python3} sim/closed_windows.py --internal --weekend-only --prep $D)"); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgx ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_P_EMA_S=150 OWN_P_EMA_HOLD_RAW=1); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkge ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_P_EMA_S=150); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgs ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=2); A=(liq_restore=2 restore_big=1); }
  [[ $1 == pkgtc ]] && { X+=($O OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=${HOLD_S:-150} OWN_HOLD_STEP=1 VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_HOLD_CAP=1); A=(liq_restore=2 restore_big=1); }
  [[ -n $3 ]] && X+=(ATTACK_PROP=$3)
  env "${X[@]}" tools/memguard.sh 6000 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "PROP:|PROP ACCOUNT|band held|takeover notional|memguard: peak" | sed -E "s/OWN MARK.*band held/band held/; s/^/$n: /"
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
