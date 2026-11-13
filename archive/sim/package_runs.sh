#!/bin/zsh
# The full package on every event, each layer added in turn:
#   today      HL mark (HyperCore 1% cap, default), today's liquidation, 0.5% clip unwind
#   p4d        + P4d mark
#   p4d_rb2    + restore-to-IM liquidation (liq_restore=2 restore_big=1)
#   pkg        + fair-sweep vault unwind (VAULT_FAIR=1)
# Crashes -> data/scen/runs/tk_{COIN}_pk_{pkg}.csv (takeover_score.py pk_*), rd_*, data/scen/pkg/log_*.csv (vault log)
# Quiet days (DAYS="1020 1021") -> data/scen/pkg/{tk,rd,log}_{COIN}_{DAY}_{pkg}.csv
cd "${0:A:h}/.."
source $PWD/sim/pkgm_env.zsh   # core-package variant names (pkgm, pkgm100, pkgmd250v, ...)
R=data/scen/runs; Q=data/scen/pkg; mkdir -p $R $Q
run() { # coin prep maxlev T outprefix pkg
  local c=$1 D=$2 L=$3 T=$4 o=$5 pk=$6 X A
  P4D=(MARK=own_et OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=6000 OWN_HOLD_S=150 OWN_HOLD_STEP=1 OWN_FROM_MS=$T)
  case $pk in
    today) X=(); A=();;
    p4d) X=($P4D); A=();;
    p4d_rb2) X=($P4D); A=(liq_restore=2 restore_big=1);;
    pkg) X=($P4D VAULT_FAIR=1); A=(liq_restore=2 restore_big=1);;
    pkgc) X=($P4D VAULT_FAIR=1 OWN_HOLD_CAP=1); A=(liq_restore=2 restore_big=1);;
    pkgt) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=1); A=(liq_restore=2 restore_big=1);;
    pkgs) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2); A=(liq_restore=2 restore_big=1);;
    pkge) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=1 OWN_P_EMA_S=150); A=(liq_restore=2 restore_big=1);;
    pkgv) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005); A=(liq_restore=2 restore_big=1);;
    pkgk) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(python3 sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1);;
    # pkgm: core package; pkgmd500 / pkgmd250: + divergence-triggered holds
    pkgm*) X=($P4D OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005 OWN_CLOSED=$(python3 sim/closed_windows.py --prep $D)); A=(liq_restore=2 restore_big=1); X+=(${=$(pkgm_extra $pk)});;;
    pkgw) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005); A=(liq_restore=2 restore_big=1);;
    pkgy) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=oracle OWN_FROZEN_UPD=2); A=(liq_restore=2 restore_big=1);;
    pkgz) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000); A=(liq_restore=2 restore_big=1);;
    pkgx) X=($P4D VAULT_FAIR=1 OWN_HOLD_TRIG=2 OWN_P_EMA_S=150 OWN_P_EMA_HOLD_RAW=1); A=(liq_restore=2 restore_big=1);;
  esac
  env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $X \
      SIM_TK_OUT=${o/XX/tk}_$pk.csv ROUNDS_OUT=${o/XX/rd}_$pk.csv VAULT_LOG=${o/XX/log}_$pk.csv ORC_OUT=$Q/orc_$c${7:+_$7}_$pk.csv \
      tools/memguard.sh 6000 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|fair sweep|takeover notional|BAD DEBT|memguard: peak" | sed "s/^/$c ${7:-crash} $pk: /"
}
PKS=(${=PKS:-today p4d p4d_rb2 pkg})
if [[ -z $DAYS ]]; then
  for spec in "GOOGL data/prep_GOOGL_1028 20 1793217600000" "INTC data/prep_INTC_1029 10 1793304000000" "AMZN data/prep_AMZN_1029 20 1793304000000"; do
    a=(${=spec}); for pk in $PKS; do run $a[1] $a[2] $a[3] $a[4] XX_$a[1]_pk $pk; done
  done
  # crash outputs: tk/rd to runs/ (takeover_score), vault log to pkg/
  for c in GOOGL INTC AMZN; do for pk in $PKS; do
    [[ -f tk_${c}_pk_$pk.csv ]] && mv tk_${c}_pk_$pk.csv rd_${c}_pk_$pk.csv $R/ ; [[ -f log_${c}_pk_$pk.csv ]] && mv log_${c}_pk_$pk.csv $Q/
  done; done
else
  for day in ${=DAYS}; do T=$([[ $day == 1020 ]] && echo 1792526400000 || echo 1792612800000)
    for c in GOOGL INTC AMZN; do L=$([[ $c == INTC ]] && echo 10 || echo 20)
      for pk in $PKS; do run $c data/prep_${c}_$day $L $T $Q/XX_${c}_$day $pk $day; done
    done
  done
fi
echo PKG DONE
