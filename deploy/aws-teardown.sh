#!/usr/bin/env bash
# Remove everything aws-deploy.sh created (reads deploy/.state-$NAME.env). Safe to re-run.
#   deploy/aws-teardown.sh            # asks before deleting the bucket's contents
#   YES=1 deploy/aws-teardown.sh      # no prompt
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
NAME="${NAME:-moshspot}"
STATE="deploy/.state-$NAME.env"
[ -f "$STATE" ] || { echo "no $STATE: nothing recorded to tear down"; exit 1; }
# shellcheck disable=SC1090
source "$STATE"
export AWS_REGION="$REGION" AWS_PAGER=""
step() { printf '== %s\n' "$*"; }

if [ -z "${YES:-}" ]; then
  read -r -p "Tear down '$NAME' in $REGION, including deleting s3://$BUCKET and its contents? Type DELETE: " ans
  [ "$ans" = DELETE ] || { echo "aborted"; exit 1; }
fi

for s in ${SCHEDULES:-}; do step "schedule $s"; aws scheduler delete-schedule --name "$s" 2>/dev/null; done
if [ -n "${IID:-}" ]; then
  step "terminate $IID"; aws ec2 terminate-instances --instance-ids "$IID" >/dev/null 2>&1
  aws ec2 wait instance-terminated --instance-ids "$IID" 2>/dev/null
fi
if [ -n "${HOSTED_ZONE_ID:-}" ] && [ -n "${IP:-}" ]; then
  step "DNS $DOMAIN"
  aws route53 change-resource-record-sets --hosted-zone-id "$HOSTED_ZONE_ID" --change-batch \
    "{\"Changes\":[{\"Action\":\"DELETE\",\"ResourceRecordSet\":{\"Name\":\"$DOMAIN\",\"Type\":\"A\",\"TTL\":60,\"ResourceRecords\":[{\"Value\":\"$IP\"}]}}]}" >/dev/null 2>&1
fi
[ -n "${SG:-}" ] && { step "security group $SG"; aws ec2 delete-security-group --group-id "$SG" 2>/dev/null; }
if [ -n "${PROFILE:-}" ]; then
  step "instance profile + role"
  aws iam remove-role-from-instance-profile --instance-profile-name "$PROFILE" --role-name "$ROLE" 2>/dev/null
  aws iam delete-instance-profile --instance-profile-name "$PROFILE" 2>/dev/null
fi
if [ -n "${ROLE:-}" ]; then
  aws iam detach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore 2>/dev/null
  aws iam delete-role-policy --role-name "$ROLE" --policy-name "$NAME-read" 2>/dev/null
  aws iam delete-role --role-name "$ROLE" 2>/dev/null
fi
if [ -n "${SROLE:-}" ]; then
  aws iam delete-role-policy --role-name "$SROLE" --policy-name "$NAME-expiry" 2>/dev/null
  aws iam delete-role --role-name "$SROLE" 2>/dev/null
fi
[ -n "${PARAM:-}" ] && { step "parameter $PARAM"; aws ssm delete-parameter --name "$PARAM" 2>/dev/null; }
if [ -n "${BUDGET:-}" ]; then
  ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
  step "budget"; aws budgets delete-budget --account-id "$ACCOUNT" --budget-name "$BUDGET" 2>/dev/null
fi
if [ -n "${BUCKET:-}" ]; then
  step "bucket $BUCKET"; aws s3 rm --quiet --recursive "s3://$BUCKET" 2>/dev/null; aws s3api delete-bucket --bucket "$BUCKET" 2>/dev/null
fi
if [ -n "${DNS_MANUAL:-}" ]; then
  read -r APEX SUB <<< "$DNS_MANUAL"
  echo "!! Now delete the DNS record you added: $SUB.$APEX (A). Vercel: Domains -> $APEX -> DNS Records,"
  echo "   or: vercel dns ls $APEX  then  vercel dns rm <record id>"
fi
rm -f "$STATE" "deploy/judge-link-$NAME.txt" "deploy/judge-qr-$NAME.png"
step "done"
