#!/bin/bash
# Bring the rebuilt market-days from your bucket to data/ (about 7 GB for the 22 named market-days), where the scorecard
# reads them. Run after the EC2 jobs of REPRODUCE.md have finished. Usage: bash sim/final/fetch_days.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")/../.." && pwd); [ -f "$HERE/config.env" ] && . "$HERE/config.env"
: "${BUCKET:?set BUCKET in config.env}"; REGION=${REGION:-ap-northeast-1}; mkdir -p "$HERE/data"
for d in CL_0910 BRENTOIL_0910 GOOGL_1020 INTC_1020 AMZN_1020 GOOGL_1021 INTC_1021 AMZN_1021 META_1022 GOOGL_1022 SILVER_1022 \
         GOOGL_1028 LITE_1028 MRVL_1028 NOW_1028 INTC_1029 AMZN_1029 RDDT_1029 GOLD_1030 SPCX_1030 SKHX_0727 NET_1105; do
  [ -s "$HERE/data/prep_$d/relayer_resid_endo0_policy.txt" ] && continue
  aws s3 cp "s3://$BUCKET/backstop/oos/preps_final/prep_$d.tgz" - --region "$REGION" | tar xzf - -C "$HERE/data"
  echo "prep_$d: $(ls "$HERE/data/prep_$d" | wc -l) files"
done
