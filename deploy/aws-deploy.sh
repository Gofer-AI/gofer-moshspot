#!/usr/bin/env bash
# Deploy MoshSpot (worker on COOL + sim bridge + HTTPS) to one Graviton instance for a fixed number of days.
#
#   aws login                                   # or any AWS CLI v2 credentials
#   DOMAIN=moshspot.example.com AMI_ID=ami-... RUN=demo-s7-20261025220245 deploy/aws-deploy.sh
#
# Required:
#   DOMAIN          hostname judges will open (Caddy gets a Let's Encrypt cert for it; needs an A record)
#   AMI_ID          the COOL Graviton AMI id from your AWS Marketplace subscription (arm64)
#   RUN             a recorded run in runs/ (its gt.json is the camera calibration; replay mode also uses its frames)
# Optional:
#   AWS_REGION      default: the CLI's configured region, else us-east-1
#   HOSTED_ZONE_ID  Route 53 zone for DOMAIN: the script creates the A record and schedules its deletion.
#                   Without it (e.g. DNS on Vercel, like goferai.space) the script prints the record to add.
#   INSTANCE_TYPE   default c8g.large (2 vCPU / 4 GB). c8g.xlarge if the worker can't keep up (see DEPLOY.md)
#   WORKER_FPS      frames per second per camera the worker analyses (default 1)
#   MODE            live (judges' browsers drive the sim; default) | replay (loop RUN, no browser needed)
#   DAYS            lifetime before automatic termination (default 20)
#   BUDGET_USD + BUDGET_EMAIL   optional AWS Budgets alert at 80% of BUDGET_USD
#   NAME            resource name prefix (default moshspot)
#
# Security: no SSH (no key pair, port 22 closed; use Session Manager), IMDSv2 only, encrypted disk, least-privilege
# instance role, token in SSM SecureString (never in user-data or argv), private encrypted bucket that expires.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${DOMAIN:?set DOMAIN}" "${AMI_ID:?set AMI_ID}" "${RUN:?set RUN}"
NAME="${NAME:-moshspot}"
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"; REGION="${REGION:-us-east-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c8g.large}"
WORKER_FPS="${WORKER_FPS:-1}"
MODE="${MODE:-live}"
DAYS="${DAYS:-20}"
STATE="deploy/.state-$NAME.env"
export AWS_REGION="$REGION" AWS_PAGER=""

say() { printf '\n== %s\n' "$*"; }
die() { printf '!! %s\n' "$*" >&2; exit 1; }

[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "DOMAIN looks wrong: $DOMAIN"
[[ "$RUN" =~ ^[A-Za-z0-9_.-]+$ && "$RUN" != "." && "$RUN" != ".." ]] || die "RUN must be a folder name in runs/"
[[ "$MODE" == live || "$MODE" == replay ]] || die "MODE must be live or replay"
[[ "$DAYS" =~ ^[0-9]+$ && "$DAYS" -ge 1 && "$DAYS" -le 60 ]] || die "DAYS must be 1..60"
[ -f "$STATE" ] && die "$STATE exists: a deployment named $NAME is already up. Run deploy/aws-teardown.sh first, or set NAME."

say "preflight"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text) || die "AWS CLI not signed in (run: aws login)"
ARCH=$(aws ec2 describe-images --image-ids "$AMI_ID" --query 'Images[0].Architecture' --output text 2>/dev/null) \
  || die "AMI $AMI_ID not found in $REGION (subscribe to COOL in AWS Marketplace and use its AMI id for this region)"
[ "$ARCH" = "arm64" ] || die "AMI $AMI_ID is $ARCH; COOL on Graviton needs arm64"
ROOT_DEV=$(aws ec2 describe-images --image-ids "$AMI_ID" --query 'Images[0].RootDeviceName' --output text)
# the root disk can't be smaller than the AMI's snapshot (the COOL AMI's is 50 GB)
AMI_GB=$(aws ec2 describe-images --image-ids "$AMI_ID" --output text \
  --query "Images[0].BlockDeviceMappings[?DeviceName=='$ROOT_DEV'].Ebs.VolumeSize | [0]")
[[ "$AMI_GB" =~ ^[0-9]+$ ]] || AMI_GB=20
VOLUME_GB=$(( AMI_GB > 20 ? AMI_GB : 20 ))
# Dry-run the exact launch before creating anything: catches a missing Marketplace subscription, an instance type
# the listing doesn't allow, and disk-size problems up front instead of halfway through.
DRY=$(aws ec2 run-instances --dry-run --image-id "$AMI_ID" --instance-type "$INSTANCE_TYPE" --count 1 \
  --block-device-mappings "DeviceName=$ROOT_DEV,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,Encrypted=true}" 2>&1 || true)
case "$DRY" in
  *DryRunOperation*) ;;
  *OptInRequired*) die "not subscribed to this COOL AMI yet: accept the terms at the URL below, wait until AWS Marketplace shows the subscription as active, then rerun.
$DRY" ;;
  *) die "a test launch of $INSTANCE_TYPE from $AMI_ID failed: $DRY" ;;
esac
for m in yolo26n.onnx yolo26n-pose-dynamic.onnx; do [ -f "models/$m" ] || die "models/$m missing (run: bash tools/export_models.sh)"; done
[ -f "runs/$RUN/gt.json" ] || die "runs/$RUN/gt.json missing"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "commit your changes first: the instance clones the exact pushed commit"
REPO_SHA=$(git rev-parse HEAD)
git branch -r --contains "$REPO_SHA" | grep -q . || die "commit $REPO_SHA is not on GitHub yet (git push)"
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
[ "$VPC" != "None" ] || die "no default VPC in $REGION"
EXPIRES_ISO=$(python3 -c "import datetime as d;print((d.datetime.now(d.timezone.utc)+d.timedelta(days=$DAYS)).strftime('%Y-%m-%dT%H:%M:%S'))")
EXPIRES_SYSTEMD="$(echo "$EXPIRES_ISO" | tr T ' ') UTC"
BUCKET="$NAME-deploy-$ACCOUNT-$REGION"
PARAM="/$NAME/bridge-token"
echo "account …${ACCOUNT: -4}  region $REGION  type $INSTANCE_TYPE  disk ${VOLUME_GB}GB  mode $MODE  fps $WORKER_FPS  expires ${EXPIRES_ISO}Z  commit ${REPO_SHA:0:7}"

: > "$STATE"; chmod 600 "$STATE"
save() { printf '%s=%q\n' "$1" "$2" >> "$STATE"; }
save NAME "$NAME"; save REGION "$REGION"; save DOMAIN "$DOMAIN"; save HOSTED_ZONE_ID "${HOSTED_ZONE_ID:-}"
save BUCKET "$BUCKET"; save PARAM "$PARAM"

say "private bucket for models + calibration (encrypted, no public access, objects expire)"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = us-east-1 ]; then aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  else aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null; fi
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
  "{\"Rules\":[{\"ID\":\"expire\",\"Status\":\"Enabled\",\"Filter\":{\"Prefix\":\"\"},\"Expiration\":{\"Days\":$((DAYS + 2))}}]}" >/dev/null
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging "{\"TagSet\":[{\"Key\":\"Project\",\"Value\":\"$NAME\"}]}"
aws s3 cp --quiet models/yolo26n.onnx "s3://$BUCKET/models/yolo26n.onnx"
aws s3 cp --quiet models/yolo26n-pose-dynamic.onnx "s3://$BUCKET/models/yolo26n-pose-dynamic.onnx"
if [ "$MODE" = replay ]; then
  aws s3 sync --quiet "runs/$RUN" "s3://$BUCKET/runs/$RUN" --exclude "perception/*"
else
  aws s3 cp --quiet "runs/$RUN/gt.json" "s3://$BUCKET/runs/$RUN/gt.json"
fi

say "bridge token -> SSM SecureString (generated here, never printed to the terminal or put in user-data)"
TMP=$(mktemp); chmod 600 "$TMP"; trap 'rm -f "$TMP"' EXIT
TOKEN=$(openssl rand -hex 24)
python3 - "$TMP" "$PARAM" "$TOKEN" <<'PY'
import json, sys
json.dump({"Name": sys.argv[2], "Type": "SecureString", "Value": sys.argv[3], "Overwrite": True}, open(sys.argv[1], "w"))
PY
aws ssm put-parameter --cli-input-json "file://$TMP" >/dev/null
rm -f "$TMP"

say "IAM: least-privilege instance role (read this bucket + this parameter; Session Manager)"
ROLE="$NAME-ec2"; PROFILE="$NAME-ec2"
aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --tags Key=Project,Value="$NAME" >/dev/null
save ROLE "$ROLE"
aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name "$ROLE" --policy-name "$NAME-read" --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
   {\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\"},
   {\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::$BUCKET\"},
   {\"Effect\":\"Allow\",\"Action\":\"ssm:GetParameter\",\"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT:parameter$PARAM\"}]}"
aws iam create-instance-profile --instance-profile-name "$PROFILE" >/dev/null
save PROFILE "$PROFILE"
aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE" --role-name "$ROLE"
aws iam wait instance-profile-exists --instance-profile-name "$PROFILE"
sleep 10  # IAM propagation before EC2 can use the profile

say "security group: 443 + 80 only (80 = Let's Encrypt challenge + redirect). No 22."
SG=$(aws ec2 create-security-group --group-name "$NAME-web" --description "MoshSpot HTTPS only" --vpc-id "$VPC" \
  --tag-specifications "ResourceType=security-group,Tags=[{Key=Project,Value=$NAME}]" --query GroupId --output text)
save SG "$SG"
aws ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions \
  'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]' \
  'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]' >/dev/null

say "instance"
UD=$(mktemp)
sed -e "s|__REGION__|$REGION|g" -e "s|__BUCKET__|$BUCKET|g" -e "s|__PARAM__|$PARAM|g" -e "s|__DOMAIN__|$DOMAIN|g" \
    -e "s|__REPO_SHA__|$REPO_SHA|g" -e "s|__RUN__|$RUN|g" -e "s|__MODE__|$MODE|g" -e "s|__WORKER_FPS__|$WORKER_FPS|g" \
    -e "s|__EXPIRES_SYSTEMD__|$EXPIRES_SYSTEMD|g" deploy/user-data.sh > "$UD"
grep -q "__[A-Z_]*__" "$UD" && die "user-data has unrendered placeholders"
IID=$(aws ec2 run-instances --image-id "$AMI_ID" --instance-type "$INSTANCE_TYPE" \
  --iam-instance-profile Name="$PROFILE" --security-group-ids "$SG" \
  --metadata-options HttpTokens=required,HttpPutResponseHopLimit=1,HttpEndpoint=enabled \
  --block-device-mappings "DeviceName=$ROOT_DEV,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
  --instance-initiated-shutdown-behavior terminate \
  --user-data "file://$UD" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=$NAME},{Key=ExpiresAt,Value=${EXPIRES_ISO}Z}]" \
                       "ResourceType=volume,Tags=[{Key=Project,Value=$NAME}]" \
  --query 'Instances[0].InstanceId' --output text)
rm -f "$UD"
save IID "$IID"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "instance $IID  public IP $IP"

if [ -n "${HOSTED_ZONE_ID:-}" ]; then
  say "DNS: $DOMAIN -> $IP (Route 53)"
  aws route53 change-resource-record-sets --hosted-zone-id "$HOSTED_ZONE_ID" --change-batch \
    "{\"Changes\":[{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$DOMAIN\",\"Type\":\"A\",\"TTL\":60,\"ResourceRecords\":[{\"Value\":\"$IP\"}]}}]}" >/dev/null
  save IP "$IP"
fi

say "auto-expiry: EventBridge Scheduler terminates the instance (and deletes the DNS record) at ${EXPIRES_ISO}Z"
SROLE="$NAME-expiry"
aws iam create-role --role-name "$SROLE" --assume-role-policy-document \
  "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"scheduler.amazonaws.com\"},\"Action\":\"sts:AssumeRole\",\"Condition\":{\"StringEquals\":{\"aws:SourceAccount\":\"$ACCOUNT\"}}}]}" \
  --tags Key=Project,Value="$NAME" >/dev/null
save SROLE "$SROLE"
SPOL="{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ec2:TerminateInstances\",\"Resource\":\"arn:aws:ec2:$REGION:$ACCOUNT:instance/$IID\"}"
[ -n "${HOSTED_ZONE_ID:-}" ] && SPOL="$SPOL,{\"Effect\":\"Allow\",\"Action\":\"route53:ChangeResourceRecordSets\",\"Resource\":\"arn:aws:route53:::hostedzone/$HOSTED_ZONE_ID\"}"
aws iam put-role-policy --role-name "$SROLE" --policy-name "$NAME-expiry" --policy-document "$SPOL]}"
sleep 10
SROLE_ARN="arn:aws:iam::$ACCOUNT:role/$SROLE"
aws scheduler create-schedule --name "$NAME-terminate" --schedule-expression "at($EXPIRES_ISO)" \
  --schedule-expression-timezone UTC --flexible-time-window Mode=OFF --action-after-completion DELETE \
  --target "{\"Arn\":\"arn:aws:scheduler:::aws-sdk:ec2:terminateInstances\",\"RoleArn\":\"$SROLE_ARN\",\"Input\":\"{\\\"InstanceIds\\\":[\\\"$IID\\\"]}\"}" >/dev/null
save SCHEDULES "$NAME-terminate"
if [ -n "${HOSTED_ZONE_ID:-}" ]; then
  DEL="{\"HostedZoneId\":\"$HOSTED_ZONE_ID\",\"ChangeBatch\":{\"Changes\":[{\"Action\":\"DELETE\",\"ResourceRecordSet\":{\"Name\":\"$DOMAIN\",\"Type\":\"A\",\"TTL\":60,\"ResourceRecords\":[{\"Value\":\"$IP\"}]}}]}}"
  aws scheduler create-schedule --name "$NAME-dns" --schedule-expression "at($EXPIRES_ISO)" \
    --schedule-expression-timezone UTC --flexible-time-window Mode=OFF --action-after-completion DELETE \
    --target "{\"Arn\":\"arn:aws:scheduler:::aws-sdk:route53:changeResourceRecordSets\",\"RoleArn\":\"$SROLE_ARN\",\"Input\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$DEL")}" >/dev/null
  save SCHEDULES "$NAME-terminate $NAME-dns"
fi

if [ -n "${BUDGET_USD:-}" ] && [ -n "${BUDGET_EMAIL:-}" ]; then
  say "budget alert at 80% of \$$BUDGET_USD -> $BUDGET_EMAIL"
  aws budgets create-budget --account-id "$ACCOUNT" \
    --budget "{\"BudgetName\":\"$NAME\",\"BudgetLimit\":{\"Amount\":\"$BUDGET_USD\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
    --notifications-with-subscribers "[{\"Notification\":{\"NotificationType\":\"ACTUAL\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":80},\"Subscribers\":[{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$BUDGET_EMAIL\"}]}]"
  save BUDGET "$NAME"
fi

LINK="deploy/judge-link-$NAME.txt"
( umask 077; printf 'https://%s/#token=%s\n' "$DOMAIN" "$TOKEN" > "$LINK" )
command -v qrencode >/dev/null && qrencode -o "deploy/judge-qr-$NAME.png" "$(cat "$LINK")" && chmod 600 "deploy/judge-qr-$NAME.png"
unset TOKEN

say "done"
cat <<EOF
URL         https://$DOMAIN   (HTTPS comes up once DNS points at $IP; bootstrap takes ~5-10 min)
judge link  in $LINK (and deploy/judge-qr-$NAME.png if qrencode is installed). Share it privately with judges only.
expires     ${EXPIRES_ISO}Z (instance terminated by EventBridge Scheduler; bucket objects expire 2 days later)
DNS         $( [ -n "${HOSTED_ZONE_ID:-}" ] && echo "created in Route 53 (deleted automatically at expiry)" || echo "ADD IT NOW (see below)" )
logs        aws ssm start-session --target $IID   then: sudo tail -f /var/log/moshspot-bootstrap.log; journalctl -u moshspot-worker -f
check       curl -s https://$DOMAIN/status
remove all  deploy/aws-teardown.sh
EOF
if [ -z "${HOSTED_ZONE_ID:-}" ]; then
  APEX=$(echo "$DOMAIN" | awk -F. '{print $(NF-1)"."$NF}'); SUB="${DOMAIN%."$APEX"}"
  save DNS_MANUAL "$APEX $SUB"
  cat <<EOF

DNS is not in Route 53, so add this record yourself (Caddy keeps retrying the certificate until it resolves):
  type A   name $SUB   value $IP   TTL 60      (on $APEX)
  Vercel dashboard: Domains -> $APEX -> DNS Records -> Add
  or Vercel CLI:    vercel login && vercel dns add $APEX $SUB A $IP
!! Delete this record when the demo ends (${EXPIRES_ISO}Z) or when you tear down: a record left pointing at a
   released AWS IP can be taken over by whoever gets that IP next.
EOF
fi
