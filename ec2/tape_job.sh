#!/bin/bash
# Tape scan (user-data of ec2/tape_launch.sh): for every xyz day in hydromancer, read the fills tape and the morning
# snapshot in ap-northeast-1 and score backstop / ADL / vault capital with sim/study/tape_backstop.py; upload the small outputs
# to s3://$BUCKET/backstop/tape/. Raw files never leave AWS; every exit terminates the instance.
# Env: BUCKET REGION [DAYS="2026-11-05 ..."] (default: all days listed) [PAR=3]
set -uxo pipefail
exec > >(tee -a /var/log/tape.log) 2>&1
S3=s3://$BUCKET/backstop/tape; H=s3://hydromancer-reservoir/by_dex/xyz; RP=(--request-payer requester --region $REGION --only-show-errors); LS=(--request-payer requester --region $REGION)
IID=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 600" | xargs -I{} curl -s -H "X-aws-ec2-metadata-token: {}" http://169.254.169.254/latest/meta-data/instance-id)
finish() { aws s3 cp /var/log/tape.log $S3/tape_$IID.log --region $REGION --only-show-errors; aws ec2 terminate-instances --region $REGION --instance-ids $IID >/dev/null 2>&1 || shutdown -h now; }
trap finish EXIT
beat() { echo "$(date -u) $IID $*" | aws s3 cp - $S3/HEARTBEAT.txt --region $REGION --only-show-errors; }
beat starting
dnf install -y python3.12 python3.12-pip >/dev/null
python3.12 -m venv /root/venv && /root/venv/bin/pip install -q polars==1.41.1 numpy==2.4.6
W=/root/w; mkdir -p $W && cd $W
aws s3 cp $S3/code.tgz - --region $REGION | tar xz
[ -n "${DAYS:-}" ] || DAYS=$(aws s3 ls $H/fills/perp/all/ "${LS[@]}" | awk '{print $2}' | sed 's/date=//;s/\///')
mkdir -p out
one() {
  d=$1; k=${d//-/}
  aws s3 ls $S3/out/t${k}_summary.json --region $REGION >/dev/null 2>&1 && return 0
  mkdir -p in_$k
  aws s3 cp $H/fills/perp/all/date=$d/fills.parquet in_$k/f.parquet "${RP[@]}" || { echo "no fills $d"; rm -rf in_$k; return 0; }
  sn=$(aws s3 ls $H/snapshots/perp/date=$d/ "${LS[@]}" | awk '{print $4}' | grep parquet | sort | head -1)
  [ -n "$sn" ] && aws s3 cp $H/snapshots/perp/date=$d/$sn in_$k/s.parquet "${RP[@]}"
  /root/venv/bin/python sim/study/tape_backstop.py out/t$k in_$k/f.parquet $([ -s in_$k/s.parquet ] && echo in_$k/s.parquet) > out/t$k.log 2>&1 || echo "FAIL $d" >> out/fails.txt
  aws s3 cp out/ $S3/out/ --recursive --exclude "*" --include "t${k}*" --region $REGION --only-show-errors
  rm -rf in_$k
}
export -f one; export S3 H REGION; export RP_S="${RP[*]}"
# wait on the day jobs' PIDs only: a bare `wait` also waits for the log's tee process substitution and never returns
n=0; P=()
for d in $DAYS; do
  one $d & P+=($!)
  n=$((n+1)); if [ ${#P[@]} -ge ${PAR:-3} ]; then wait "${P[@]}"; P=(); beat "done $n days (last $d)"; fi
done
[ ${#P[@]} -gt 0 ] && wait "${P[@]}"
[ -f out/fails.txt ] && aws s3 cp out/fails.txt $S3/out/ --region $REGION --only-show-errors
[ "$n" -gt 0 ] || { beat "no days listed"; exit 1; }
beat "TAPE DONE $n days"
