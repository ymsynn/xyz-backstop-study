#!/bin/bash
# xyz market-simulator inputs from the HL command stream (replica_cmds) for one day: blocks, the book
# actions of ASSETS, xyz margin-state actions and every xyz relayer setOracle (see extract.py).
# Reads hl-mainnet-node-data IN-REGION (requester-pays GETs only), runs extract.py on every 10k-block
# file of the day folder, uploads one part per file to
#   s3://$BUCKET/backstop/xyz_extract/<DAY>/parts/<file>.jsonl.gz  (+ <DAY>.done, HEARTBEAT.txt)
# Same infra / role / bucket as quant_share/ec2/launch.sh. ~205 GB of stream per day, c6i.8xlarge
# ~20-40 min -> ~$1-2. Self-terminates.
# Usage: AWS_PROFILE=<your-profile> bash backstop/ec2/launch.sh   (env: DAY SNAP MIN_H ASSETS INSTANCE_TYPE)
set -euo pipefail
REGION=ap-northeast-1; BUCKET=${BUCKET:?set BUCKET to your S3 bucket}; PROFILE=${INSTANCE_PROFILE:?set INSTANCE_PROFILE to your instance profile}
INSTANCE_TYPE=${INSTANCE_TYPE:-c6i.8xlarge}
DAY=${DAY:-20261028}; SNAP=${SNAP:-2026-10-25T09:33:07Z}
MIN_H=${MIN_H:-1199710000}            # hydromancer xyz snapshot block of that day (00:02:09)
ASSETS=${ASSETS:-110012}              # xyz:GOOGL
P=backstop/xyz_extract
HERE=$(cd "$(dirname "$0")" && pwd)
aws s3 cp "$HERE/extract.py" "s3://$BUCKET/$P/code/extract.py" --region $REGION
AMI=$(aws ssm get-parameter --region $REGION --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)

USERDATA_FILE=$(mktemp)
cat > "$USERDATA_FILE" <<USERDATA
#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/userdata.log) 2>&1
OUT=$BUCKET; REGION=$REGION; P=$P; DAY=$DAY
dnf install -y python3 python3-pip lz4 awscli >/dev/null
pip3 install -q orjson
mkdir -p /opt/work && cd /opt/work
aws s3 cp s3://\$OUT/\$P/code/extract.py extract.py --region \$REGION
TOKEN=\$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
IID=\$(curl -sH "X-aws-ec2-metadata-token: \$TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
echo "started \$(date -u) \$IID" > S.txt; aws s3 cp S.txt s3://\$OUT/\$P/\$DAY/STARTED.txt --region \$REGION
aws s3 ls "s3://hl-mainnet-node-data/replica_cmds/$SNAP/\$DAY/" --request-payer requester --region \$REGION \
  | awk '{print \$4}' | grep lz4 > keys.txt
mkdir -p parts
cat keys.txt | xargs -P \$(nproc) -I '{}' bash -c 'f="{}"; aws s3 cp "s3://hl-mainnet-node-data/replica_cmds/$SNAP/$DAY/\$f" - \
    --request-payer requester --region ap-northeast-1 2>/dev/null | lz4 -dc 2>/dev/null \
    | python3 /opt/work/extract.py $MIN_H "parts/\${f%.lz4}.jsonl.gz" $ASSETS \
    && aws s3 cp "parts/\${f%.lz4}.jsonl.gz" "s3://$BUCKET/$P/$DAY/parts/" --region ap-northeast-1 --only-show-errors \
    || echo "FAIL \$f" >> fails.txt'
echo "\$(date -u) day=\$DAY files=\$(wc -l < keys.txt) parts=\$(ls parts | wc -l) fails=\$(cat fails.txt 2>/dev/null | wc -l)" | tee d.done
aws s3 cp d.done "s3://\$OUT/\$P/\$DAY.done" --region \$REGION
aws s3 cp d.done "s3://\$OUT/\$P/HEARTBEAT.txt" --region \$REGION
[ -f fails.txt ] && aws s3 cp fails.txt "s3://\$OUT/\$P/\$DAY/fails.txt" --region \$REGION || true
aws s3 cp /var/log/userdata.log "s3://\$OUT/\$P/\$DAY/userdata.log" --region \$REGION
aws ec2 terminate-instances --region \$REGION --instance-ids \$IID || true
shutdown -h now
USERDATA
IID=$(aws ec2 run-instances --region $REGION --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --iam-instance-profile Name=$PROFILE \
  --user-data file://$USERDATA_FILE --instance-initiated-shutdown-behavior terminate \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=40,VolumeType=gp3,DeleteOnTermination=true}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=xyz-extract}]" --query 'Instances[0].InstanceId' --output text)
echo "launched $IID ($INSTANCE_TYPE)"; echo "monitor: aws s3 cp s3://$BUCKET/$P/HEARTBEAT.txt -   (done marker: $P/$DAY.done)"
