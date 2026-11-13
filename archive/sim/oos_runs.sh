#!/bin/zsh
# Out-of-sample runs for one coin-day: today's rules and package_v, unchanged, at real parameters otherwise.
# Usage: [PKS="today pkgv pkgk"] zsh sim/oos_runs.sh DAY COIN MAXLEV  -> data/scen/oos/{tk,rd,log,orc}_{COIN}_{DAY}_{pk}.csv, run_{COIN}_{DAY}[_{pk}].log
# pkgk = package_v + the venue's scheduled closures (OWN_CLOSED from sim/closed_windows.py): no frozen-feed hold while the venue is shut.
cd ${REPO:-$PWD}
source $PWD/sim/pkgm_env.zsh   # core-package variant names (pkgm, pkgm100, pkgmd250v, ...)
DAY=$1; C=$2; L=$3; D=data/prep_${C}_$DAY; O=data/scen/oos; mkdir -p $O
PKGV=(MARK=own_et OWN_FROM_MS=0 OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=6000 OWN_HOLD_S=150 OWN_HOLD_STEP=1 VAULT_FAIR=1
      OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005)
PKS=(${=PKS:-today pkgv}); LOG=$O/run_${C}_$DAY.log; [[ "$PKS" == "today pkgv" ]] || LOG=$O/run_${C}_${DAY}_${PKS// /_}.log
for pk in $PKS; do
  if [[ $pk == today ]]; then X=(); A=(); else X=($PKGV); A=(liq_restore=2 restore_big=1); fi
  [[ $pk == pkgk ]] && X+=(OWN_CLOSED=$(${PY:-python3} sim/closed_windows.py $C 2026-${DAY:0:2}-${DAY:2:2} 2))
  # pkgm = the core package: package_k without the fair sweep (vault unwind is appendix only); pkgm050/100/200 = + the
  # internal oracle's book input capped at 0.5 / 1 / 2 % of the oracle in every closure (INTERNAL_CAP)
  if [[ $pk == pkgm* ]]; then X=(${PKGV:#VAULT_FAIR=1} OWN_CLOSED=$(${PY:-python3} sim/closed_windows.py --prep $D)); X+=(${=$(pkgm_extra $pk)}); fi
  # pkgb = package_k + daily breaks hold the last external price (internal oracle only on weekends)
  [[ $pk == pkgb ]] && X+=(OWN_CLOSED=$(${PY:-python3} sim/closed_windows.py --prep $D) RELAYER_INTERNAL="$(${PY:-python3} sim/closed_windows.py --internal --weekend-only --prep $D)")
  n=${C}_${DAY}_$pk
  env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $X \
      SIM_TK_OUT=$O/tk_$n.csv ROUNDS_OUT=$O/rd_$n.csv VAULT_LOG=$O/log_$n.csv ORC_OUT=$O/orc_$n.csv TRIG_FIRED_OUT=$O/trig_$n.csv \
      tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|takeover|market rounds|mark reproduced|BAD DEBT|band held|memguard: peak" | sed "s/^/$n: /"
done | tee $LOG
