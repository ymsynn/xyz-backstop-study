#!/bin/zsh
# Normal-market comparison: today's formula against a suggested mark, replayed over the WHOLE tape (the mark a market
# would really run on is the same all day). sim/score/normal_eval.py then scores only the out-of-hours sessions
# (overnight, pre-market, post-market) and leaves out regular hours [13:30, 20:00) UTC and the crash window.
cd "${0:A:h}/../.."
source $PWD/sim/pkgm_env.zsh   # the proposal's settings: pkgm3<k|q|r><seconds>
S=${S:-$PWD/data/scen/normal}; mkdir -p $S
run() { # coin mark
  local c=$1 mk=$2 D L
  local DY=${DAY:-}
  case $c in
    GOOGL) D=data/prep_GOOGL_${DY:-1028}; L=20;;
    INTC)  D=data/prep_INTC_${DY:-1029};  L=10;;
    AMZN)  D=data/prep_AMZN_${DY:-1029};  L=20;;
  esac
  local n=${c}_$mk
  local X=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt
           ORC_OUT=$S/orc_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv TRIG_FIRED_OUT=$S/trig_$n.csv)
  local A=()
  [[ $mk == pkgm3* ]] && { X+=(${=$(pkgm_extra $mk)}); A=(liq_restore=2 restore_big=1); }
  env "${X[@]}" tools/memguard.sh 12 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|OWN MARK|memguard: peak" | sed "s/^/$n: /"
}
for c in GOOGL INTC AMZN; do for mk in ${=MARKS:-today p2 p4}; do run $c $mk; done; done
echo DONE
