#!/bin/zsh
# Hydromancer + node misc inputs for the quiet days (Oct 20, 21; next-day snapshots Oct 21, 22). Requester-pays.
export AWS_PROFILE=${AWS_PROFILE:?set AWS_PROFILE to your AWS profile}
cd ${REPO:-$PWD}/data
R=(--request-payer requester --region ap-northeast-1 --only-show-errors)
H=s3://hydromancer-reservoir/by_dex/xyz; G=s3://hydromancer-reservoir/global
for d in 20 21 22; do
  aws s3 cp $H/fills/perp/all/date=2026-10-$d/fills.parquet xyzdata/all10$d.parquet $R
  aws s3 sync $H/snapshots/perp/date=2026-10-$d/ xyzdata/snap10$d/ $R
  aws s3 sync $G/snapshots/account_values/date=2026-10-$d/ global10$d/account_values/ $R
  aws s3 sync $G/snapshots/perp/all/date=2026-10-$d/ global10$d/perp_all/ $R
  aws s3 sync $G/snapshots/spot/date=2026-10-$d/ global10$d/spot/ $R
done
for d in 20 21; do
  aws s3 sync $H/fills/perp/liquidations/date=2026-10-$d/ xyzdata/liquidations/date=2026-10-$d/ $R
  for C in GOOGL INTC AMZN; do aws s3 cp $H/orderbook/1m/perps/date=2026-10-$d/$C.parquet xyzdata/ob1m_${C}_10$d.parquet $R; done
  aws s3 sync s3://hl-mainnet-node-data/misc_events_by_block/hourly/202610$d/ nodedata/misc10$d/ --request-payer requester --only-show-errors
  mkdir -p global10$d/fills_raw; aws s3 sync $G/fills/raw/date=2026-10-$d/ global10$d/fills_raw/ $R
done
du -sh xyzdata global10* nodedata; echo PULL DONE
