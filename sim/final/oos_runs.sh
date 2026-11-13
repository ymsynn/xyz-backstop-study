#!/bin/zsh
# Replays of one held-out market-day under today's rules and the proposal, at real parameters otherwise.
# Usage: [PKS="today pkgm3q1800"] zsh sim/final/oos_runs.sh DAY COIN MAXLEV  -> data/scen/oos/{tk,rd,log,orc}_{COIN}_{DAY}_{pk}.csv, run_{COIN}_{DAY}[_{pk}].log
cd "${0:A:h}/../.."
source $PWD/sim/pkgm_env.zsh   # the proposal's settings: pkgm3<k|q|r><seconds>
DAY=$1; C=$2; L=$3; D=data/prep_${C}_$DAY; O=${FINAL_OUT:-$PWD/data/scen/final}/oos; mkdir -p $O
PKS=(${=PKS:-today pkgm3q1800}); LOG=$O/run_${C}_${DAY}_${PKS// /_}.log
for pk in $PKS; do
  X=(); A=()
  [[ $pk == today || $pk == pkgm3* ]] || { print -u2 "oos_runs: unknown rule set $pk"; continue; }
  [[ $pk == pkgm3* ]] && { X=(${=$(pkgm_extra $pk)}); A=(liq_restore=2 restore_big=1); }
  n=${C}_${DAY}_$pk
  env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $X \
      SIM_TK_OUT=$O/tk_$n.csv ROUNDS_OUT=$O/rd_$n.csv VAULT_LOG=$O/log_$n.csv ORC_OUT=$O/orc_$n.csv TRIG_FIRED_OUT=$O/trig_$n.csv \
      tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|takeover|market rounds|mark reproduced|BAD DEBT|band held|memguard: peak" | sed "s/^/$n: /"
done | tee $LOG
