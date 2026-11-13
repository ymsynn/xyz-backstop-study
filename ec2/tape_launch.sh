#!/bin/bash
# Launch ec2/tape_job.sh on one instance in ap-northeast-1 (where the hydromancer tape is). Usage:
#   [ONDEMAND=1] [INSTANCE_TYPE=c6i.2xlarge] [DAYS="2026-11-05 ..."] bash ec2/tape_launch.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
REGION=${REGION:-ap-northeast-1}
[ -f "$HERE/config.env" ] && . "$HERE/config.env"
BUCKET=${BUCKET:?set BUCKET, an S3 bucket of yours in ap-northeast-1 (see config.example.env)}
PROFILE=${INSTANCE_PROFILE:?set INSTANCE_PROFILE, an EC2 instance profile that may read the two archives and write to BUCKET}
HERE=$(cd "$(dirname "$0")/.." && pwd); S3=s3://$BUCKET/backstop/tape; T=$(mktemp -d)
COPYFILE_DISABLE=1 tar czf $T/code.tgz -C "$HERE" sim/study/tape_backstop.py data/xyzmeta.json
aws s3 cp $T/code.tgz $S3/code.tgz --region $REGION --only-show-errors
AMI=$(aws ssm get-parameter --region $REGION --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
{ echo '#!/bin/bash'; echo "export BUCKET=$BUCKET REGION=$REGION DAYS=\"${DAYS:-}\" PAR=${PAR:-3} HOME=/root"; cat "$HERE/ec2/tape_job.sh"; } > $T/u.sh
MKT=(); [ "${ONDEMAND:-0}" = 1 ] || MKT=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
aws ec2 run-instances --region $REGION --image-id "$AMI" --instance-type "${INSTANCE_TYPE:-c6i.2xlarge}" --iam-instance-profile Name=$PROFILE \
  ${MKT[@]+"${MKT[@]}"} --user-data file://$T/u.sh --instance-initiated-shutdown-behavior terminate \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=40,VolumeType=gp3,DeleteOnTermination=true}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=xyz-tape}]" --query 'Instances[0].InstanceId' --output text
