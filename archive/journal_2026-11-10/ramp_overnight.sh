#!/bin/zsh
# Walking external feed: E drifts linearly to FRAC (default -10%) over the ramp, stays there HOLD_S (default 120 s), then
# snaps back, at 18:30 ET on GOOGL 10-28 and AMZN 10-29 (the bad-print time of sim/spike_runs.sh). A slow manipulation of
# the external market never makes a single-update jump, so package_k's feed-failure test does not see it.
# Marks: today | pkgm (core package: package_k without the fair sweep) | pkgmd500 / pkgmd250: pkgm + a hold that may also
# start when xyz's trades and book both disagree with E by more than 5% (d at 20x) / 2.5% (the MM rate at 20x);
# suffixes (sim/pkgm_env.zsh): c|s step only while xyz has no trade, v only while its volume is below average, n never. FRAC=+0.10 walks up.
# Usage: [MARKS=...] [TAGS="w15 w30 w60 w300"] zsh sim/ramp_runs.sh  -> data/scen/ramp/{orc,tk,rd,trig}_{COIN}_{MARK}_{TAG}.csv
cd ${REPO:-$PWD}
source $PWD/sim/pkgm_env.zsh   # core-package variant names (pkgm, pkgm100, pkgmd250v, ...)
S=${S:-$PWD/data/scen/ramp}; mkdir -p $S
run() { # coin mark tag ramp
  local c=$1 mk=$2 n=$1_$2_$3 D L T
  if [[ $c == GOOGL ]]; then D=data/prep_GOOGL_1028; L=20; T=1793146200000; else D=data/prep_AMZN_1029; L=20; T=1793232600000; fi
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           ORC_OUT=$S/orc_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv TRIG_FIRED_OUT=$S/trig_$n.csv)
  local A=()
  if [[ $mk == pkgm* ]]; then
    X+=(MARK=own_et OWN_FROM_MS=$T OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=${IMPACT_N:-6000} OWN_HOLD_S=150 OWN_HOLD_STEP=1
        OWN_HOLD_TRIG=2 OWN_ONLY_HOLD=1 CLAMP_O_BPS=100000 M2_REF=ext OWN_FROZEN_UPD=2 OWN_FROZEN_GAP=0.005 OWN_JUMP_GAP=0.005
        OWN_CLOSED="$(${PY:-python3} sim/closed_windows.py --prep $D)")
    A=(liq_restore=2 restore_big=1)
    X+=(${=$(pkgm_extra $mk)})
  fi
  [[ -n $4 ]] && X+=(EXT_RAMP=$4)
  # DUST=ntl: an attacker's dust trade of ntl at every relayer update for the whole walk (keeps a trade-count freshness alive)
  [[ -n $4 && -n $DUST ]] && X+=(WASH="$Q;$(( ${3#w} + ${HOLD_S:-120} ));0;$DUST")
  env "${X[@]}" tools/memguard.sh 6000 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|OWN MARK|memguard: peak" | sed -E "s/OWN MARK.*divergence holds/divergence holds/; s/^/$n: /"
}
for c in ${=COINS:-GOOGL AMZN}; do
  if [[ $c == GOOGL ]]; then Q=${RAMP_AT:-1793226600000}; else Q=${RAMP_AT:-1793313000000}; fi
  for mk in ${=MARKS:-today pkgm pkgmd500 pkgmd250}; do
    [[ -f $S/tk_${c}_${mk}_base.csv ]] || run $c $mk base
    for tag in ${=TAGS:-w15 w30 w60 w300}; do run $c $mk $tag "$Q;${tag#w};${FRAC:--0.10};${HOLD_S:-120}"; done
  done
done
echo RAMP DONE
