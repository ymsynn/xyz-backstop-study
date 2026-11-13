#!/bin/zsh
# Real-parameter parity runs (ENDO=0, simulated relayer + residual) with per-account round dumps, for the
# liquidation over-fill study. TAG names the variant; extra engine args after it. -> data/scen/liqfit/{rd,miss}_{COIN}_{TAG}.csv
cd ${REPO:-$PWD}
O=data/scen/liqfit; TAG=${1:-base}; shift
for spec in "GOOGL data/prep_GOOGL_1028 20" "INTC data/prep_INTC_1029 10" "AMZN data/prep_AMZN_1029 20"; do
  a=(${=spec}); c=$a[1]; D=$a[2]; L=$a[3]
  env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0.txt \
      ROUNDS_OUT=$O/rd_${c}_$TAG.csv RDETAIL_OUT=$O/det_${c}_$TAG.csv STOP_DUMP=$O/stop_${c}_$TAG.csv SIM_TK_OUT=$O/simtk_${c}_$TAG.csv \
      tools/memguard.sh 6000 engine/target/release/engine sim $D $L "$@" 2>&1 | grep -E "^VAULT|takeover|market rounds|mark reproduced|memguard: peak" | sed "s/^/$c $TAG: /"
done
echo LIQFIT DONE
