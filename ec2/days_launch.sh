#!/bin/bash
# Launch the out-of-sample job (ec2/days_job.sh) on one small spot instance. Packs the code (no data), uploads it, starts
# the instance with the job as user-data; results land in s3://$BUCKET/backstop/oos/ (results/, logs/, preps/, done/).
# Relaunching resumes from the done-markers. Usage: bash ec2/days_launch.sh   (env: INSTANCE_TYPE DAYS DAYS_DES EXTRA_ENV, see REPRODUCE.md)
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
REGION=${REGION:-ap-northeast-1}
[ -f "$HERE/config.env" ] && . "$HERE/config.env"
BUCKET=${BUCKET:?set BUCKET, an S3 bucket of yours in ap-northeast-1 (see config.example.env)}
PROFILE=${INSTANCE_PROFILE:?set INSTANCE_PROFILE, an EC2 instance profile that may read the two archives and write to BUCKET}
INSTANCE_TYPE=${INSTANCE_TYPE:-c6i.2xlarge}
DAYS=${DAYS:-"0910@0911@2026-09-05T09:29:18Z@1141870000@CL/110029/20,BRENTOIL/110049/20 1022@1023@2026-10-10T08:17:54Z@1192510000@META/110008/20,GOOGL/110012/20,SILVER/110026/25 1030@1031@2026-10-25T09:33:07Z@1202130000@GOLD/110003/25,SPCX/110076/20"}
HERE=$(cd "$(dirname "$0")/.." && pwd); S3=s3://$BUCKET/backstop/oos
T=$(mktemp -d); COPYFILE_DISABLE=1 tar czf $T/code.tgz -C "$HERE" --exclude engine/target engine sim tools ec2 data/xyzmeta.json data/venue_hours.json
aws s3 cp $T/code.tgz $S3/code/code.tgz --region $REGION --only-show-errors
AMI=$(aws ssm get-parameter --region $REGION --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
U=$T/userdata.sh
# ONDEMAND=1: no spot (e.g. the account spot quota is full); the job still terminates itself
MKT=(); [ "${ONDEMAND:-0}" = 1 ] || MKT=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
# EXTRA_ENV="K=V K2=V2": engine settings exported for the whole job (e.g. RELAYER_WARMUP_S)
{ echo '#!/bin/bash'; [ -n "${EXTRA_ENV:-}" ] && echo "export ${EXTRA_ENV}"; echo "export BUCKET=$BUCKET REGION=$REGION DAYS=\"$DAYS\" VARIANTS=\"${VARIANTS:-}\" CLOSED_SPEC=\"${CLOSED_SPEC:-}\" REVAL=\"${REVAL:-}\" REVAL_ATTACK=\"${REVAL_ATTACK:-}\" REVAL_PKS=\"${REVAL_PKS:-}\" REVAL_MARKS=\"${REVAL_MARKS:-}\" REVAL_LIQBOOK=\"${REVAL_LIQBOOK:-}\" REVAL_DES=\"${REVAL_DES:-}\" ADL=\"${ADL:-}\" DAYS_DES=\"${DAYS_DES:-}\" X_COINS=\"${X_COINS:-}\" CONTAGION=\"${CONTAGION:-}\" PAR=\"${PAR:-1}\" DETCHECK=\"${DETCHECK:-}\" ONLY=\"${ONLY:-}\" KNOWN_GAPS=\"${KNOWN_GAPS:-}\" FILL_HOLES=\"${FILL_HOLES:-}\" HOME=/root"; echo 'cd /root'; cat "$HERE/ec2/days_job.sh"; } > $U
gzip -9c $U > $U.gz   # user data is capped at 16 KB; cloud-init unpacks gzip
IID=$(aws ec2 run-instances --region $REGION --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --iam-instance-profile Name=$PROFILE \
  ${MKT[@]+"${MKT[@]}"} \
  --user-data fileb://$U.gz --instance-initiated-shutdown-behavior terminate \
  --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=${VOLUME_GB:-150},VolumeType=gp3,DeleteOnTermination=true}" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=xyz-oos}]" --query 'Instances[0].InstanceId' --output text)
echo "launched $IID ($INSTANCE_TYPE $([ "${ONDEMAND:-0}" = 1 ] && echo on-demand || echo spot))"; echo "monitor: aws s3 cp $S3/HEARTBEAT.txt - --region $REGION"
