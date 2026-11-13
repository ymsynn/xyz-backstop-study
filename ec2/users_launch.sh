#!/bin/bash
# Wallet addresses behind the per-market account numbers. Each rebuilt market-day numbers its accounts from 0
# (users.arrow: uid, user), so counting distinct traders over several markets needs the addresses. This job reads the
# archives of the market-days in S3, where they live, keeps only users.arrow from each, and writes them together to
# s3://$BUCKET/backstop/oos/users/users_<TAG>.tgz (a few MB). One small spot instance; it terminates itself.
# Usage: TAG=1105 MATCH="_1105" bash ec2/users_launch.sh      (MATCH: grep pattern on the archive names in preps_final/)
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
REGION=${REGION:-ap-northeast-1}
[ -f "$HERE/config.env" ] && . "$HERE/config.env"
BUCKET=${BUCKET:?set BUCKET (see config.example.env)}
PROFILE=${INSTANCE_PROFILE:?set INSTANCE_PROFILE (see config.example.env)}
TAG=${TAG:?set TAG, the name of the output}; MATCH=${MATCH:?set MATCH, a grep pattern on archive names}
S3=s3://$BUCKET/backstop/oos
KEYS=$(aws s3 ls $S3/preps_final/ --region $REGION | awk '{print $4}' | grep -E "$MATCH" | tr '\n' ' ')
[ -n "$KEYS" ] || { echo "no archive matches $MATCH"; exit 1; }
AMI=$(aws ssm get-parameter --region $REGION --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
U=$(mktemp)
cat > $U <<EOF
#!/bin/bash
set -euo pipefail
exec > /var/log/users_job.log 2>&1
trap 'aws s3 cp /var/log/users_job.log $S3/users/users_$TAG.log --region $REGION --only-show-errors || true; shutdown -h now' EXIT
shutdown -h +\${MAX_MIN:-40}
mkdir -p /tmp/u; cd /tmp
for k in $KEYS; do
  n=\${k%.tgz}; n=\${n#prep_}
  aws s3 cp $S3/preps_final/\$k - --region $REGION | tar xzf - -O --wildcards '*users.arrow' > u/users_\$n.arrow
  [ -s u/users_\$n.arrow ] || { echo "no users.arrow in \$k"; exit 1; }
  echo "\$n \$(stat -c %s u/users_\$n.arrow) bytes"
done
tar czf users_$TAG.tgz -C u .
aws s3 cp users_$TAG.tgz $S3/users/users_$TAG.tgz --region $REGION --only-show-errors
EOF
gzip -9c $U > $U.gz   # user data is capped at 16 KB; cloud-init unpacks gzip
IID=$(aws ec2 run-instances --region $REGION --image-id "$AMI" --instance-type "${INSTANCE_TYPE:-c6i.large}" --iam-instance-profile Name=$PROFILE \
  --instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}' \
  --user-data fileb://$U.gz --instance-initiated-shutdown-behavior terminate \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=xyz-users}]" --query 'Instances[0].InstanceId' --output text)
echo "launched $IID for $(echo $KEYS | wc -w | tr -d ' ') archives; output $S3/users/users_$TAG.tgz"
