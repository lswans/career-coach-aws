#!/usr/bin/env bash
# Tests for infra/teardown.sh. They put a fake `aws` command first on PATH, so no AWS account is
# touched and no credentials are needed. Run: bash infra/tests/test_teardown.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../teardown.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0
FAIL=0

# ---------- the fake AWS CLI ----------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/aws" << 'FAKE'
#!/usr/bin/env bash
# Answers only the calls teardown.sh makes. State lives in $FAKE_DIR.
echo "$*" >> "$FAKE_DIR/calls.log"
args="$*"
next_status() {
  # Each describe-stacks status read consumes one line; the last line repeats.
  local n; n=$(wc -l < "$FAKE_DIR/statuses")
  if [ "$n" -gt 1 ]; then head -n 1 "$FAKE_DIR/statuses"; sed -i '1d' "$FAKE_DIR/statuses"; else cat "$FAKE_DIR/statuses"; fi
}
case "$args" in
  "sts get-caller-identity"*)
    if [ -n "${FAKE_NOAUTH:-}" ]; then echo "Unable to locate credentials." >&2; exit 253; fi
    echo "111122223333" ;;
  *"cloudformation"*"describe-stacks"*"StackStatus"*)
    s="$(next_status)"
    if [ "$s" = "GONE" ]; then echo "An error occurred (ValidationError): Stack with id x does not exist" >&2; exit 254; fi
    echo "$s" ;;
  *"cloudformation"*"describe-stacks"*"Description"*) echo "${FAKE_DESC:-Career Coach workshop: one stack...}" ;;
  *"cloudformation"*"describe-stacks"*"Outputs"*) echo "https://d111111abcdef8.cloudfront.net" ;;
  *"cloudformation"*"list-stack-resources"*"CoachMemory"*) echo "CareerCoachStack-abc123XYZ" ;;
  *"cloudformation"*"list-stack-resources"*"DELETE_FAILED"*) printf 'CoachDistribution\tAWS::CloudFront::Distribution\tStill disabling\n' ;;
  *"cloudformation"*"list-stack-resources"*"ResourceType"*) printf 'AWS::EC2::VPC\tAWS::EC2::Instance\tAWS::EC2::NatGateway\n' ;;
  *"cloudformation"*"describe-stack-events"*) printf 'CoachDistribution\tDELETE_IN_PROGRESS\n' ;;
  *"cloudformation"*"delete-stack"*) : ;;
  *"ec2 describe-instances"*) echo "${FAKE_LEFT_INSTANCE:-}" ;;
  *"ec2 describe-nat-gateways"*) echo "${FAKE_LEFT_NAT:-}" ;;
  *"ec2 describe-addresses"*) echo "${FAKE_LEFT_EIP:-}" ;;
  *"cloudfront list-distributions"*) echo "${FAKE_LEFT_CF:-}" ;;
  *"cognito-idp list-user-pools"*) echo "${FAKE_LEFT_POOL:-}" ;;
  *"bedrock-agentcore-control get-memory"*)
    if [ -n "${FAKE_LEFT_MEMORY:-}" ]; then echo "ACTIVE"; else
      echo "An error occurred (ResourceNotFoundException) when calling GetMemory" >&2; exit 254; fi ;;
  *"bedrock-agentcore-control list-memories"*) echo "${FAKE_LEFT_MEMORY:-}" ;;
  *) echo "fake aws: unexpected call: $args" >&2; exit 99 ;;
esac
FAKE
chmod +x "$WORK/bin/aws"

# run <name> <expected exit> <stdin> <statuses, space separated> [teardown args...]; extra env via ENV_EXTRA
run() {
  local name="$1" want="$2" input="$3" statuses="$4"
  shift 4
  export FAKE_DIR="$WORK/$name"
  mkdir -p "$FAKE_DIR"
  : > "$FAKE_DIR/calls.log"
  tr ' ' '\n' <<< "$statuses" > "$FAKE_DIR/statuses"
  local -a extra=()
  if [ -n "${ENV_EXTRA:-}" ]; then extra=("$ENV_EXTRA"); fi
  printf '%s\n' "$input" | env PATH="$WORK/bin:$PATH" TEARDOWN_POLL_SECONDS=0 AWS_REGION=us-east-1 \
    "${extra[@]}" bash "$SCRIPT" "$@" > "$FAKE_DIR/out.txt" 2>&1
  GOT=$?
  OUT="$(cat "$FAKE_DIR/out.txt")"
  DELETES=$(grep -c 'delete-stack' "$FAKE_DIR/calls.log" || true)
  if [ "$GOT" = "$want" ]; then CASE_OK=1; else CASE_OK=0; fi
}

expect() {  # expect <name> <condition description> <test result 0/1>
  if [ "$CASE_OK" = 1 ] && [ "$3" = 0 ]; then
    PASS=$((PASS + 1)); echo "ok   $1"
  else
    FAIL=$((FAIL + 1)); echo "FAIL $1 (exit $GOT, $2)"; sed 's/^/       /' "$FAKE_DIR/out.txt"
  fi
}

run happy 0 "career-coach" "CREATE_COMPLETE DELETE_IN_PROGRESS DELETE_IN_PROGRESS GONE"
if [ "$DELETES" = 1 ] && grep -q "Stack deleted" <<< "$OUT" && grep -q "Memory (AgentCore): gone" <<< "$OUT"; then c=0; else c=1; fi
expect "deletes after the name is typed, waits, finds no leftovers" "deletes=$DELETES" "$c"

run wrong-answer 1 "yes" "CREATE_COMPLETE"
if [ "$DELETES" = 0 ] && grep -q "Nothing was deleted" <<< "$OUT"; then c=0; else c=1; fi
expect "anything but the stack name deletes nothing" "deletes=$DELETES" "$c"

run no-input 1 "" "CREATE_COMPLETE"
if [ "$DELETES" = 0 ]; then c=0; else c=1; fi
expect "an empty answer deletes nothing" "deletes=$DELETES" "$c"

run assume-yes 0 "" "UPDATE_COMPLETE GONE" --yes
if [ "$DELETES" = 1 ]; then c=0; else c=1; fi
expect "--yes skips the prompt" "deletes=$DELETES" "$c"

ENV_EXTRA="FAKE_DESC=Some other team's production stack" run not-coach 1 "career-coach" "CREATE_COMPLETE"
if [ "$DELETES" = 0 ] && grep -q "isn't a Career Coach stack" <<< "$OUT"; then c=0; else c=1; fi
expect "refuses a stack that isn't a Career Coach stack" "deletes=$DELETES" "$c"

run retry-ok 0 "career-coach" "ROLLBACK_COMPLETE DELETE_IN_PROGRESS DELETE_FAILED DELETE_IN_PROGRESS GONE"
if [ "$DELETES" = 2 ] && grep -q "CoachDistribution" <<< "$OUT"; then c=0; else c=1; fi
expect "retries once after DELETE_FAILED and shows what failed" "deletes=$DELETES" "$c"

run retry-fails 2 "career-coach" "CREATE_COMPLETE DELETE_FAILED DELETE_FAILED"
if [ "$DELETES" = 2 ] && grep -q "failed again" <<< "$OUT"; then c=0; else c=1; fi
expect "gives up with exit 2 after the retry fails" "deletes=$DELETES" "$c"

ENV_EXTRA="FAKE_LEFT_NAT=nat-0abc123" run gone-leftover 3 "" "GONE"
if [ "$DELETES" = 0 ] && grep -q "NAT gateway still exists: nat-0abc123" <<< "$OUT"; then c=0; else c=1; fi
expect "no stack, but a leftover NAT gateway, exits 3" "deletes=$DELETES" "$c"

run gone-clean 0 "" "GONE"
if [ "$DELETES" = 0 ] && grep -q "nothing to delete" <<< "$OUT"; then c=0; else c=1; fi
expect "no stack and no leftovers exits 0" "deletes=$DELETES" "$c"

run check-only 1 "" "CREATE_COMPLETE" --check
if [ "$DELETES" = 0 ]; then c=0; else c=1; fi
expect "--check never deletes" "deletes=$DELETES" "$c"

run busy 1 "career-coach" "UPDATE_IN_PROGRESS"
if [ "$DELETES" = 0 ] && grep -q "busy" <<< "$OUT"; then c=0; else c=1; fi
expect "a busy stack is left alone" "deletes=$DELETES" "$c"

ENV_EXTRA="FAKE_NOAUTH=1" run no-auth 1 "" "CREATE_COMPLETE"
if [ "$DELETES" = 0 ] && grep -q "isn't signed in" <<< "$OUT"; then c=0; else c=1; fi
expect "not signed in stops before any AWS change" "deletes=$DELETES" "$c"

run bad-name 1 "" "CREATE_COMPLETE" --stack "x';rm -rf ."
if [ ! -s "$FAKE_DIR/calls.log" ]; then c=0; else c=1; fi
expect "an unsafe stack name is rejected before any AWS call" "calls=$(wc -l < "$FAKE_DIR/calls.log")" "$c"

ENV_EXTRA="FAKE_LEFT_MEMORY=1" run memory-left 3 "career-coach" "CREATE_COMPLETE GONE"
if grep -q "Memory (AgentCore) still exists: CareerCoachStack-abc123XYZ" <<< "$OUT"; then c=0; else c=1; fi
expect "reports a memory the delete left behind, by its id" "deletes=$DELETES" "$c"

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
