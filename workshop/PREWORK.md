# Before the workshop: 20 minutes, a day or two early

In the workshop you deploy a career coach into your own AWS account from one CloudFormation file, then use it from
your browser. You don't install anything on your laptop. What you do need is an AWS account that can use Claude, and
a brand-new account sometimes needs a day before it can, so please do this a day or two before the session. If you
finish the checklist at the bottom, you are ready.

A few terms up front:

- **CloudFormation**: the AWS service that reads one file describing a set of resources and creates all of them
  for you. Deleting the "stack" it creates deletes them again.
- **Model**: the AI that reads your documents and writes your coaching. Ours is Claude Haiku 5.5, made by
  Anthropic.
- **Amazon Bedrock**: the AWS service that runs Claude for you. You pay only for what you use, a few cents for the
  whole workshop.

## 1. Create your AWS account

1. Create an AWS account at [aws.amazon.com](https://aws.amazon.com) if you don't have one. When sign-up asks you to
   pick a plan, choose the **paid plan**. Claude is sold through AWS Marketplace, and the free plan leaves out
   Marketplace products that cost money. New accounts get the same sign-up credits on either plan, and the budget
   alert in step 3 warns you long before you spend anything real.
   - Already have an account on the free plan? Upgrade it from the console's
     [Upgrade plan](https://console.aws.amazon.com/billing/home?#/freetier/upgrade) page. Your remaining credits
     carry over.
   - Use an account you created yourself. Accounts handed out through an AWS partner reseller often can't use
     Claude.
2. Create a user for daily work instead of using the root user (the email you signed up with). The AWS guide
   [Getting started with IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/getting-started.html)
   walks you through it, and
   [root user best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/root-user-best-practices.html)
   explains why. Give the user administrator access: the stack creates a server role and a network, which needs it.
3. Set a budget alert, for example $5, so nothing surprises you:
   [create a budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html).

## 2. Switch on Claude

Anthropic asks every AWS account a few questions before its first use of Claude. You do this once, in the browser.

1. Sign in to the [AWS console](https://console.aws.amazon.com) as the user from step 1. In the top-right corner,
   set the region to **US East (N. Virginia)**. The workshop uses this region throughout.
2. Search for **Bedrock** and open **Amazon Bedrock**. In the left menu, choose **Model catalog**, then choose
   **Claude Haiku 5.5**.
3. If the page asks for use-case details, fill in the short form and submit it. If you don't have a company
   website, your GitHub profile or a portfolio link is fine. For the use case, a sentence like "Learning to build AI
   agents at a workshop" works.
4. Open the model in the playground, type `hi` and run it. A short reply means your account can use Claude.

If you get an error instead of a reply:

| Message mentions | What to do |
|---|---|
| use case details | Submit the form from step 3. |
| payment instrument or payment method | Add a payment method in the Billing console under **Payment preferences**, wait a few minutes, and try again. |
| AWS Marketplace actions | Sign in as a user with administrator access and try again. |
| access denied, right after you sent the form | The form can take a while to go through. AWS emails you when it's done; try again after that. |
| Operation not allowed, or account verification is in progress | AWS is still checking your new account. This can take a few days and only AWS can finish it, so open a case in the [AWS Support Center](https://support.console.aws.amazon.com/support/home). |
| channel program accounts | The account came from an AWS partner. Use an account you created yourself. |

### If Claude Haiku 5.5 still won't answer

A new account can sometimes use one Claude model before another. If Haiku 5.5 still returns an error after you've worked through the table, try a different Claude model:

1. Go back to **Model catalog**, choose **Claude Sonnet 4.6**, open it in the playground and run `hi`.
2. If it answers, look up its model id. Open AWS CloudShell (the `>_` icon at the top of the console) and run:

   ```bash
   aws bedrock list-inference-profiles --region us-east-1 --query "inferenceProfileSummaries[?starts_with(inferenceProfileId, 'us.anthropic')].[inferenceProfileName, inferenceProfileId]" --output table
   ```

3. Find the row whose name matches the model that answered and copy the id in the second column. It starts with `us.anthropic.`, for example `us.anthropic.claude-sonnet-4-6`.
4. Save the id where you can find it on the day. When you create the stack in the workshop, you paste it into the **Bedrock model** box.

If no Claude model answers, the account isn't ready yet. Open a case in the [AWS Support Center](https://support.console.aws.amazon.com/support/home), and plan to pair with someone on the day.

## 3. Check your email

The stack sends your coach's temporary password to an email address you type during the workshop. Pick one you can
open on the day, on your laptop or phone.

## What it costs

- **Claude Haiku 5.5** is paid per use: building a profile costs a fraction of a cent, and so does each chat reply
  ([Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)).
- **Claude Sonnet 4.6**, if you use it instead, costs more per token than Haiku 5.5 ([Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)). The stack's daily limits of 10 profile builds and 100 chat messages per person still cap what you can spend.
- **AgentCore Memory** is pay-per-use, and a workshop's worth of chatting costs well under one cent
  ([pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)).
- **The server, its network and the HTTPS link** are billed by the hour while the stack exists: a small EC2
  instance, a NAT gateway and CloudFront ([EC2](https://aws.amazon.com/ec2/pricing/),
  [VPC](https://aws.amazon.com/vpc/pricing/), [CloudFront](https://aws.amazon.com/cloudfront/pricing/)). The guide
  ends by deleting the stack, which stops all of it. Delete it the same day.

## You are ready if

- [ ] You can sign in to the AWS console as a user with administrator access (not the root user)
- [ ] A budget alert is set
- [ ] Claude Haiku 5.5 replied to `hi` in the Bedrock playground, in US East (N. Virginia)
- [ ] You know which email address you'll use for your coach

See you at the session.
