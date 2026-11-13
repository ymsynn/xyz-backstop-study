#!/bin/bash
# Run one of the ec2/*.py screens on a small spot instance in ap-northeast-1, where the archives live (reading them from
# anywhere else costs egress, and the raw data never leaves AWS). The instance terminates itself: on every exit path, and
# on a wall-clock cap if that fails. Replaces three near-identical launchers.
#
# Usage: SCRIPT=ec2/<name>.py PREFIX=<s3 prefix under backstop/> [TAG=<instance name>] [INSTANCE_TYPE=c6i.large]
#        [MAX_MIN=45] [ONDEMAND=1] bash ec2/py_job_launch.sh
#
# The three screens behind the paper:
#   SCRIPT=ec2/onesided_screen.py  PREFIX=onesided TAG=xyz-onesided         INSTANCE_TYPE=c6i.xlarge MAX_MIN=90
#     -> s3://$BUCKET/backstop/onesided/{summary.txt,hits.csv,onesided_days.csv}  (what the mark does with one side empty)
#   SCRIPT=ec2/onesided_confirm.py PREFIX=onesided TAG=xyz-onesided-confirm INSTANCE_TYPE=c6i.large  MAX_MIN=45
#     -> s3://$BUCKET/backstop/onesided/confirm_*                                 (the same events, read from the fills)
#   SCRIPT=ec2/market_index.py     PREFIX=random   TAG=xyz-market-index     INSTANCE_TYPE=c6i.large  MAX_MIN=20
#     -> s3://$BUCKET/backstop/random/market_index.csv                             (the frame the random sample is drawn from)
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
REGION=${REGION:-ap-northeast-1}
[ -f "$HERE/config.env" ] && . "$HERE/config.env"
BUCKET=${BUCKET:?set BUCKET, an S3 bucket of yours in ap-northeast-1 (see config.example.env)}
PROFILE=${INSTANCE_PROFILE:?set INSTANCE_PROFILE, an EC2 instance profile that may read the two archives and write to BUCKET}
SCRIPT=${SCRIPT:?set SCRIPT, the ec2/*.py to run (see the header)}
PREFIX=${PREFIX:?set PREFIX, the folder under s3://$BUCKET/backstop/}
[ -f "$HERE/$SCRIPT" ] || { echo "no such script: $SCRIPT"; exit 1; }
NAME=$(basename "$SCRIPT")
TAG=${TAG:-xyz-${NAME%.py}}
S3=s3://$BUCKET/backstop/$PREFIX; T=$(mktemp -d)
aws s3 cp "$HERE/$SCRIPT" "$S3/code/$NAME" --region "$REGION" --only-show-errors
AMI=$(aws ssm get-parameter --region "$REGION" --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
cat > $T/u.sh <<U
#!/bin/bash
export BUCKET=$BUCKET REGION=$REGION HOME=/root
shutdown -h +${MAX_MIN:-45}
exec > /var/log/$TAG.log 2>&1
trap 'aws s3 cp /var/log/$TAG.log $S3/${NAME%.py}.log --region $REGION || true; shutdown -h now' EXIT
dnf install -y python3.12 python3.12-pip >/dev/null
python3.12 -m venv /root/v && /root/v/bin/pip install -q polars==1.41.1 boto3
aws s3 cp $S3/code/$NAME /root/s.py --region $REGION
/root/v/bin/python /root/s.py
U
MKT=(); [ "${ONDEMAND:-0}" = 1 ] || MKT=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
IID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "${INSTANCE_TYPE:-c6i.large}" --iam-instance-profile Name=$PROFILE \
  ${MKT[@]+"${MKT[@]}"} --user-data file://$T/u.sh --instance-initiated-shutdown-behavior terminate \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,DeleteOnTermination=true}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$TAG}]" --query 'Instances[0].InstanceId' --output text)
echo "launched $IID ($NAME -> $S3, cap ${MAX_MIN:-45} min); log $S3/${NAME%.py}.log"
