---
name: career-coach-teardown
description: Delete a Career Coach workshop stack from your own AWS account and confirm nothing billable is left. Use when someone says "tear down", "clean up", "delete my coach" or "stop the billing", when infra/teardown.sh can't run, or when a stack delete ends in DELETE_FAILED.
---

# Career Coach teardown

The workshop stack (`infra/career-coach.yaml`) creates a server and a NAT gateway that are billed by the hour,
so it should be deleted when the workshop is over. Deleting the stack removes everything it created, including
the coach's memory and everything stored in it. That can't be undone.

The quick way is the script: open AWS CloudShell (the `>_` icon at the top of the AWS console), make sure the
region in the top-right corner is the one you deployed to, and run:

```bash
curl -fsSLO https://raw.githubusercontent.com/lswans/career-coach-aws/main/infra/teardown.sh
bash teardown.sh
```

It asks you to type the stack name, deletes the stack, retries once if the delete fails, and then checks for
leftovers. Use this skill when the script can't run or stops with an error.

## Rules (for a person or an AI agent following this skill)

- Only delete a stack whose description starts with "Career Coach workshop". Check it in the stack's **Stack
  info** tab before deleting anything.
- Work in the account and region the stack is in. Check both in the console's top-right corner (or with
  `aws sts get-caller-identity` and `aws configure get region`).
- Only delete resources the stack created. They carry the tag `aws:cloudformation:stack-name` with the stack's
  name, or they're listed in the stack's **Resources** tab. Never delete anything else, even if it looks related.
- Use the credentials you already have: a console sign-in or CloudShell. Never create access keys for this, and
  never paste keys, passwords or tokens into a chat, a file or a command line.
- An agent must show the stack name, account and region and get a clear "yes" before deleting.

## Steps in the console

1. Open **CloudFormation** and select the stack, `career-coach` unless you chose another name.
2. Choose **Delete**, then confirm. The status becomes `DELETE_IN_PROGRESS`.
3. Wait, choosing the refresh button now and then. The CloudFront distribution takes the longest, often 10 minutes
   or more. When the stack is gone from the list (or shows `DELETE_COMPLETE` with the **Deleted** filter), it's done.
4. If the status turns to `DELETE_FAILED`, open the **Events** tab, find the resources marked `DELETE_FAILED`,
   and check the table below. Then choose **Retry delete**.
5. Check for leftovers (next section) even when the delete succeeded.

## When the delete fails

| Resource that failed | Usual reason | What to do |
|---|---|---|
| `CoachDistribution` (CloudFront) | CloudFront was still disabling or deploying the distribution | Wait 15 minutes, then **Retry delete** |
| `CoachVpcOrigin` (CloudFront VPC origin) | The distribution that used it wasn't gone yet | Retry after the distribution is deleted |
| `Vpc`, `PrivateSubnet`, `CoachSecurityGroup` with `DependencyViolation` | A network interface CloudFront made for the VPC origin is still being removed | Wait 10 to 20 minutes, then **Retry delete** |
| `InternetGateway` or `GatewayAttachment` | The NAT gateway's address was still attached | Retry after `NatGateway` and `NatAddress` are deleted |
| `CoachMemory` (AgentCore Memory) | The memory was still deleting | Wait a few minutes, then **Retry delete** |
| `UserPool` (Cognito) | Someone turned on deletion protection | In Cognito, open the pool, turn deletion protection off, then **Retry delete** |
| Anything with `AccessDenied` | The signed-in user can't delete that resource | Sign in as the administrator user from the prework and retry |

If a retry fails twice on the same resource, **Retry delete** offers to retain that resource and delete the
rest. Choose that only as a last step, then delete the retained resource by hand in its own console page, using
the physical ID from the stack's **Resources** tab.

## Check for leftovers

These are the parts that cost money if they survive. Each should be gone after the stack is deleted.

| What | Where to look in the console | Read-only CLI check |
|---|---|---|
| Server | EC2 > Instances, filter by the tag `aws:cloudformation:stack-name` | `aws ec2 describe-instances --filters Name=tag:aws:cloudformation:stack-name,Values=career-coach Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId'` |
| NAT gateway | VPC > NAT gateways | `aws ec2 describe-nat-gateways --filter Name=tag:aws:cloudformation:stack-name,Values=career-coach Name=state,Values=pending,available,failed --query 'NatGateways[].NatGatewayId'` |
| Elastic IP address | EC2 > Elastic IPs | `aws ec2 describe-addresses --filters Name=tag:aws:cloudformation:stack-name,Values=career-coach --query 'Addresses[].AllocationId'` |
| HTTPS link | CloudFront > Distributions, comment "Career Coach (career-coach)" | `aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='Career Coach (career-coach)'].Id"` |
| Memory | Amazon Bedrock AgentCore > Memory, a memory named `CareerCoachStack` | `aws bedrock-agentcore-control list-memories --query "memories[?starts_with(id, 'CareerCoachStack-')]"` |
| Sign-in | Cognito > User pools, `career-coach-users` | `aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='career-coach-users'].Id"` |

Replace `career-coach` with your stack name if you chose another. Every command above only reads. Empty output
(`[]`) means the thing is gone. `bash teardown.sh --check` runs all of these checks at once.

## Maintainers only: the image publishing stack

The `infra/publish-image.yaml` stack holds the public image every attendee's server downloads. Delete it only
when no workshop needs the image any more, because attendee stacks can't start without it.

1. Delete the images first. CloudFormation can't delete an ECR Public repository that still has images:
   in the console open **Amazon ECR > Public repositories > career-coach**, select all images and delete them.
2. Delete the publishing stack in CloudFormation (region us-east-1). This also removes the push role and, if the
   stack created it, the GitHub identity provider.
3. Remove the `PUBLISH_ROLE_ARN` variable from the GitHub repository's Actions settings.
