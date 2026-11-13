#!/bin/zsh
# MM buffer on the P4d mark: base (½), fixed ¾, and speed-triggered (½ -> ¾ as the feed's 150 s move reaches the MM zone).
# Crashes: GOOGL 10-28, INTC/AMZN 10-29 -> data/scen/runs/{tk,rd}_{COIN}_p4d_{base,b75,dyn75}.csv (takeover_score.py)
# Quiet days: DAYS="1020 1021" -> data/scen/buf_q/{tk,rd,trig}_{COIN}_{DAY}_{tag}.csv
cd ${REPO:-$PWD}
R=data/scen/runs; Q=data/scen/buf_q; mkdir -p $R $Q
P4D=(MARK=own_et OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=6000 OWN_HOLD_S=150 OWN_HOLD_STEP=1)
run() { # coin prep maxlev T out_prefix tag args...
  local c=$1 D=$2 L=$3 T=$4 o=$5 tag=$6; shift 6
  env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $P4D OWN_FROM_MS=$T \
      SIM_TK_OUT=${o/XX/tk}_$tag.csv ROUNDS_OUT=${o/XX/rd}_$tag.csv TRIG_FIRED_OUT=${o/XX/trig}_$tag.csv \
      tools/memguard.sh 6000 engine/target/release/engine sim $D $L "$@" 2>&1 | grep -E "MM DYN|takeover notional|memguard: peak" | sed "s/^/$c $tag: /"
}
TAGS=(${=TAGS:-base b75 dyn75})
args_of() { case $1 in base) ;; b75) echo mm_buffer=0.75;; dyn75) echo mm_dyn=0.75;; b75k) echo mm_buffer=0.75 keep_bs=1;; dyn75k) echo mm_dyn=0.75 keep_bs=1;; cd3) echo cooldown_ms=3000;; pf1) echo partial_frac=1;; b75k_cd3) echo mm_buffer=0.75 keep_bs=1 cooldown_ms=3000;; dyn75k_cd3) echo mm_dyn=0.75 keep_bs=1 cooldown_ms=3000;; rs1) echo liq_restore=1;; rs2) echo liq_restore=2;; rs1dyn) echo liq_restore=1 mm_dyn=0.75 keep_bs=1;; rb1) echo liq_restore=1 restore_big=1;; rb2) echo liq_restore=2 restore_big=1;; rb15) echo liq_restore=1.5 restore_big=1;; rb3) echo liq_restore=3 restore_big=1;; rb2dyn) echo liq_restore=2 restore_big=1 mm_dyn=0.75 keep_bs=1;; esac }
if [[ -z $DAYS ]]; then
  for spec in "GOOGL data/prep_GOOGL_1028 20 1793217600000" "INTC data/prep_INTC_1029 10 1793304000000" "AMZN data/prep_AMZN_1029 20 1793304000000"; do
    a=(${=spec}); for t in $TAGS; do run $a[1] $a[2] $a[3] $a[4] $R/XX_$a[1]_p4d $t ${=$(args_of $t)}; done
  done
else
  for day in ${=DAYS}; do T=$([[ $day == 1020 ]] && echo 1792526400000 || echo 1792612800000)
    for c in GOOGL INTC AMZN; do L=$([[ $c == INTC ]] && echo 10 || echo 20)
      for t in $TAGS; do run $c data/prep_${c}_$day $L $T $Q/XX_${c}_${day} $t ${=$(args_of $t)}; done
    done
  done
fi
echo BUF DONE
