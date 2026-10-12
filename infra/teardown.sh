#!/usr/bin/env bash
# Career Coach teardown: deletes your career-coach CloudFormation stack, then checks that nothing
# billable is left behind (the server, the NAT gateway and its address, the HTTPS link, the memory,
# the sign-in).
#
# Run it in AWS CloudShell (the >_ icon in the AWS console), or anywhere the AWS CLI is signed in.
# It uses the credentials the AWS CLI already has. It never asks for, prints or stores keys.
#
#   bash teardown.sh                                   # stack "career-coach" in CloudShell's region
#   bash teardown.sh --stack my-coach --region us-west-2
#   bash teardown.sh --check                           # only look for leftovers; delete nothing
#   bash teardown.sh --yes                             # skip the "type the stack name" prompt
#
# Exit codes: 0 everything is gone, 1 nothing was deleted (bad input, not signed in, wrong stack,
# you said no), 2 the delete failed, 3 the stack is gone but something billable is still there,
# 4 still deleting when the wait ran out.
set -euo pipefail

STACK="career-coach"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
ASSUME_YES=0
CHECK_ONLY=0
POLL_SECONDS="${TEARDOWN_POLL_SECONDS:-15}"
MAX_WAIT_SECONDS="${TEARDOWN_MAX_WAIT_SECONDS:-3600}"
# The stack's template description starts with this, which is how a Career Coach stack is recognized.
STACK_MARKER="Career Coach workshop"

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
}

say() { printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --stack) STACK="${2:-}"; shift 2 ;;
    --region) REGION="${2:-}"; shift 2 ;;
    --yes | -y) ASSUME_YES=1; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) say "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Both values end up in AWS CLI arguments and queries, so only plain names are accepted.
if ! [[ "$STACK" =~ ^[A-Za-z][A-Za-z0-9-]{0,127}$ ]]; then
  say "That stack name isn't valid: use letters, numbers and hyphens, starting with a letter." >&2
  exit 1
fi
if ! [[ "$REGION" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]]; then
  say "That region isn't valid: use a region code such as us-east-1." >&2
  exit 1
fi

ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

cfn() { aws cloudformation --region "$REGION" "$@"; }

if ! command -v aws > /dev/null 2>&1; then
  say "The AWS CLI isn't installed here. Open AWS CloudShell from the AWS console and run this there." >&2
  exit 1
fi
if ! ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2> "$ERR_FILE")"; then
  say "The AWS CLI isn't signed in. Open AWS CloudShell from the AWS console and run this there." >&2
  sed 's/^/  /' "$ERR_FILE" >&2
  exit 1
fi
say "Account: $ACCOUNT   Region: $REGION   Stack: $STACK"

# Prints the stack's status, or GONE when no such stack exists. Any other error stops the script.
stack_status() {
  local out
  if out="$(cfn describe-stacks --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text 2> "$ERR_FILE")"; then
    printf '%s\n' "$out"
    return 0
  fi
  if grep -q 'does not exist' "$ERR_FILE"; then
    printf 'GONE\n'
    return 0
  fi
  say "Couldn't read the stack:" >&2
  sed 's/^/  /' "$ERR_FILE" >&2
  return 1
}

# The physical id of one resource in the stack, or nothing.
physical_id() {
  cfn list-stack-resources --stack-name "$STACK" \
    --query "StackResourceSummaries[?LogicalResourceId=='$1'].PhysicalResourceId | [0]" \
    --output text 2> /dev/null | grep -v '^None$' || true
}

MEMORY_ID=""
LEFTOVERS=0

# One leftover check: a label, then the AWS CLI arguments. Text output, one id per word.
check() {
  local label="$1" out
  shift
  if ! out="$(aws "$@" --output text 2> "$ERR_FILE")"; then
    say "  ?  $label: couldn't check ($(head -n 1 "$ERR_FILE"))"
    return 0
  fi
  out="$(printf '%s' "$out" | tr '\t' ' ' | sed 's/None//g' | xargs || true)"
  if [ -n "$out" ]; then
    say "  !  $label still exists: $out"
    LEFTOVERS=$((LEFTOVERS + 1))
  else
    say "  ok $label: gone"
  fi
}

check_leftovers() {
  local tag="Name=tag:aws:cloudformation:stack-name,Values=$STACK"
  say ""
  say "Checking for anything billable left from \"$STACK\" in $REGION:"
  check "Server (EC2 instance)" ec2 describe-instances --region "$REGION" \
    --filters "$tag" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId'
  check "NAT gateway" ec2 describe-nat-gateways --region "$REGION" \
    --filter "$tag" "Name=state,Values=pending,available,failed" \
    --query 'NatGateways[].NatGatewayId'
  check "Elastic IP address" ec2 describe-addresses --region "$REGION" \
    --filters "$tag" --query 'Addresses[].AllocationId'
  check "HTTPS link (CloudFront distribution)" cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='Career Coach ($STACK)'].Id"
  check "Sign-in (Cognito user pool)" cognito-idp list-user-pools --region "$REGION" --max-results 60 \
    --query "UserPools[?Name=='$STACK-users'].Id"
  if [ -n "$MEMORY_ID" ]; then
    # get-memory answers ResourceNotFoundException once the memory is deleted.
    local out
    if out="$(aws bedrock-agentcore-control get-memory --region "$REGION" --memory-id "$MEMORY_ID" \
      --query 'memory.status' --output text 2> "$ERR_FILE")"; then
      if [ "$out" = "DELETING" ]; then
        say "  ok Memory (AgentCore): deleting"
      else
        say "  !  Memory (AgentCore) still exists: $MEMORY_ID ($out)"
        LEFTOVERS=$((LEFTOVERS + 1))
      fi
    elif grep -q 'ResourceNotFound' "$ERR_FILE"; then
      say "  ok Memory (AgentCore): gone"
    else
      say "  ?  Memory (AgentCore): couldn't check ($(head -n 1 "$ERR_FILE"))"
    fi
  else
    # Without the stack we can't know its memory id; the template names every memory CareerCoachStack.
    check "Memory (AgentCore) named CareerCoachStack" bedrock-agentcore-control list-memories --region "$REGION" \
      --query "memories[?starts_with(id, 'CareerCoachStack-') && status!='DELETING'].id"
  fi
  if [ "$LEFTOVERS" -gt 0 ]; then
    say ""
    say "$LEFTOVERS thing(s) above are still there and may keep billing. Delete them in the console,"
    say "or follow skills/teardown/SKILL.md in the workshop repository."
    return 3
  fi
  return 0
}

failed_resources() {
  cfn list-stack-resources --stack-name "$STACK" \
    --query "StackResourceSummaries[?ResourceStatus=='DELETE_FAILED'].[LogicalResourceId,ResourceType,ResourceStatusReason]" \
    --output text 2> /dev/null | sed 's/^/    /' || true
}

# Waits until the stack is gone. 0 gone, 2 DELETE_FAILED, 4 out of time.
wait_until_gone() {
  local start=$SECONDS status event last=""
  while :; do
    status="$(stack_status)"
    case "$status" in
      GONE | DELETE_COMPLETE) say "  Stack deleted."; return 0 ;;
      DELETE_FAILED) return 2 ;;
    esac
    event="$(cfn describe-stack-events --stack-name "$STACK" --no-paginate \
      --query 'StackEvents[0].[LogicalResourceId,ResourceStatus]' --output text 2> /dev/null | tr '\t' ' ' || true)"
    if [ "$event" != "$last" ]; then
      say "  $(date +%H:%M:%S)  $status  (latest: $event)"
      last="$event"
    fi
    if [ $((SECONDS - start)) -ge "$MAX_WAIT_SECONDS" ]; then
      say "  Still deleting after $((MAX_WAIT_SECONDS / 60)) minutes. Run this script again later to keep waiting."
      return 4
    fi
    sleep "$POLL_SECONDS"
  done
}

STATUS="$(stack_status)"

if [ "$STATUS" = "GONE" ]; then
  say "There's no stack called \"$STACK\" in $REGION, so there's nothing to delete."
  check_leftovers && exit 0 || exit 3
fi

DESCRIPTION="$(cfn describe-stacks --stack-name "$STACK" --query 'Stacks[0].Description' --output text)"
case "$DESCRIPTION" in
  "$STACK_MARKER"*) ;;
  *)
    say "\"$STACK\" isn't a Career Coach stack (its description doesn't start with \"$STACK_MARKER\")."
    say "Nothing was deleted. Pass the right name with --stack."
    exit 1
    ;;
esac

MEMORY_ID="$(physical_id CoachMemory)"
COACH_URL="$(cfn describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CoachUrl'].OutputValue | [0]" --output text 2> /dev/null | grep -v '^None$' || true)"

if [ "$CHECK_ONLY" = 1 ]; then
  say "The stack still exists ($STATUS). --check deletes nothing."
  exit 1
fi

case "$STATUS" in
  DELETE_IN_PROGRESS)
    say "The stack is already being deleted. Waiting for it to finish."
    ;;
  *_COMPLETE | *_FAILED | CREATE_IN_PROGRESS)
    say ""
    say "This deletes the stack and everything it created:"
    cfn list-stack-resources --stack-name "$STACK" --query 'StackResourceSummaries[].ResourceType' --output text \
      | tr '\t' '\n' | sort | uniq -c | sed 's/^/  /'
    [ -n "$COACH_URL" ] && say "  The coach at $COACH_URL stops working, and everything it stored is erased."
    if [ "$ASSUME_YES" != 1 ]; then
      say ""
      printf 'Type the stack name (%s) to delete it, or anything else to stop: ' "$STACK"
      read -r ANSWER || ANSWER=""
      if [ "$ANSWER" != "$STACK" ]; then
        say "Nothing was deleted."
        exit 1
      fi
    fi
    say "Deleting \"$STACK\". CloudFront takes the longest, often 10 minutes or more."
    cfn delete-stack --stack-name "$STACK"
    ;;
  *)
    say "The stack is busy ($STATUS). Wait until it finishes, then run this again."
    exit 1
    ;;
esac

set +e
wait_until_gone
RESULT=$?
if [ "$RESULT" = 2 ]; then
  say "  The delete failed on:"
  failed_resources
  say "  Trying once more (the console calls this Retry delete)."
  cfn delete-stack --stack-name "$STACK"
  wait_until_gone
  RESULT=$?
  if [ "$RESULT" = 2 ]; then
    say "  The delete failed again on:"
    failed_resources
    say "  Fix the resources above in the console, then run this again. skills/teardown/SKILL.md lists the usual causes."
    exit 2
  fi
fi
[ "$RESULT" = 0 ] || exit "$RESULT"
check_leftovers
exit $?
