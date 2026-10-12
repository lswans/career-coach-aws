# Career Coach: attendee guide

Follow these steps in order. Each one is a single action, and each part ends with a "You should see" check so you
know it worked before moving on. Everything happens in your browser: the AWS console and your coach's website.

If you skipped the prework, stop and do it first. It sets up your AWS account and switches on Claude, which takes
about 20 minutes, and a brand-new account can take longer than the session to approve.

A few terms as they come up:

- **Agent**: a program that uses an AI model to decide what to do, including calling tools.
- **Model**: the AI that writes the text. Ours is Claude Haiku 5.5 from Anthropic, on Amazon Bedrock.
- **CloudFormation stack**: a set of AWS resources created together from one template file, and deleted together.
- **Strands**: the open-source toolkit that wires the model into an agent.
- **Memory**: what the coach remembers about you. Short-term memory is the current chat. Long-term memory carries
  facts across chats.

`<REPO_URL>` means the GitHub link in the AWS Builder Center post for this workshop.

---

## Part 0: Check Claude still answers (2 min)

### Step 1. Open the Bedrock playground

Sign in to the [AWS console](https://console.aws.amazon.com) with the user from the prework, set the region in the
top-right corner to **US East (N. Virginia)**, and open **Amazon Bedrock**. Choose **Model catalog**, then
**Claude Haiku 5.5**, and open it in the playground.

### Step 2. Say hi

Type `hi` and run it.

You should see a short reply. If you see an error, the table in step 2 of the prework says what to fix.

---

## Part 1: Deploy your coach with one stack (5 min, then about 15 min of waiting)

### Step 3. Download the template

Open `<REPO_URL>/blob/main/infra/career-coach.yaml`, choose **Download raw file** (the download arrow), and save it.

This one file describes everything the coach needs. You'll see each piece appear in Step 9.

### Step 4. Start a new stack

In the console, search for **CloudFormation** and open it. Check that the region is still **US East
(N. Virginia)**. Choose **Create stack**, then **With new resources (standard)**.

### Step 5. Upload the template

Under **Specify template**, choose **Upload a template file**, choose the file from Step 3, and choose **Next**.

### Step 6. Fill in the parameters

- **Stack name**: `career-coach`
- **Your email**: an address you can open now. AWS sends your temporary password there.
- Leave everything else as it is, including **Coach container image**, and choose **Next**.

### Step 7. Skip the options page

Leave the **Configure stack options** page as it is and choose **Next**.

### Step 8. Create the stack

At the bottom of the review page, tick **I acknowledge that AWS CloudFormation might create IAM resources**, then
choose **Submit**.

The stack creates a role for the coach's server, which is why it asks. The role can call Claude, use this stack's
memory, and nothing else in your account.

You should see the stack with the status `CREATE_IN_PROGRESS`.

### Step 9. Watch it build

Open the **Events** tab and refresh it now and then. In about 15 minutes the stack creates:

- a private network with a NAT gateway, so the server can reach AWS and the internet but nothing can reach it;
- a sign-in for your email (**Amazon Cognito**) and an email with your temporary password;
- the coach's long-term memory (**Amazon Bedrock AgentCore Memory**);
- a small server (**Amazon EC2**) that downloads the coach from the repository, builds it and starts it;
- an HTTPS link (**Amazon CloudFront**) that is the only way in to the server.

Most of the wait is the server installing the coach and CloudFront starting up. The presenter walks through each
piece while you wait.

You should see the stack status turn to `CREATE_COMPLETE`, and an email titled **Your Career Coach sign-in** in your
inbox. If the status turns to `ROLLBACK_IN_PROGRESS` instead, see Troubleshooting at the end.

---

## Part 2: Sign in and build your profile (8 min)

### Step 10. Open your coach

Open the **Outputs** tab of the stack and choose the **CoachUrl** link.

You should see the Career Coach page with **Sign in to your coach**.

### Step 11. Sign in

Type your email and the temporary password from the email, and choose **Sign in**. The first time, the coach asks
for a new password: at least 8 characters, with a number, an uppercase letter and a lowercase letter.

You should see the first setup step, **Dump your docs**, and the header pill reads
`Claude Haiku 5.5 · AgentCore Memory · ready`.

### Step 12. Get the sample files

Download these three files from the repository, the same way as Step 3:

- `<REPO_URL>/blob/main/sample-data/jordan-resume.md`
- `<REPO_URL>/blob/main/sample-data/jordan-achievements.txt`
- `<REPO_URL>/blob/main/sample-data/jordan-goals.txt`

They describe a fictional student named Jordan Rivera. You can use your own resume instead: Claude reads it on
Amazon Bedrock in your own AWS account, and Anthropic has no access to what you send there
([Bedrock data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html)). The sample
keeps your results close to what the presenter shows.

### Step 13. Upload the sample resume

In **Dump your docs**, upload `jordan-resume.md`.

You should see the file listed as uploaded.

### Step 14. Paste the achievements

Open `jordan-achievements.txt`, copy its contents, and paste them into the Achievements box.

### Step 15. Paste the goals

Choose **Next: goals**, open `jordan-goals.txt`, copy it, and paste it into the goals box.

The **Build my coach** button stays disabled until you have at least one document and at least 200 characters of
goals. A counter shows how close you are.

You should see the counter pass 200 and the **Build my coach** button become clickable.

### Step 16. Build the coach

Choose **Build my coach**.

A checklist shows each step as it happens: reading your documents, Claude writing your profile (you can watch the
skills it rates appear), checking the suggested next steps on the web, and saving. This takes about 15 to 30
seconds.

You should see the checklist fill in, then the dashboard appear.

### Step 17. Read your profile

On the dashboard, open the **Profile** tab.

You should see skills rated 1 to 5 with evidence, a list of weaknesses, opportunities grouped by timeframe, and a
goal alignment score from 0 to 100.

AI models sometimes invent certifications that don't exist, so the coach searched the web for every next step that
names a course or certification. Look for the note under each one: **Verified online** links to the real page,
**Corrected** means it was renamed to the closest real one, and **Couldn't verify** means check it yourself. Steps
about your own work, like deploying a project from your resume, need no check and show no note.

---

## Part 3: Chat, and memory across sessions (8 min)

### Step 18. Chat with the coach

Open the **Coach** tab and ask it something, for example "What should I focus on this month?"

You should see the reply stream in word by word. Ask about certifications, courses, jobs or events (for example
"Which AWS certification should I take next?") and the coach searches the web first: the reply cites its
**Web sources** by number.

### Step 19. Report some progress

Type a progress update, for example "I passed my AWS Cloud Practitioner exam!"

The coach saves messages that report progress to your log.

You should see a **Saved to your progress log** chip appear on that message.

### Step 20. Tell it something, then start a new session

Tell the coach something new about yourself, for example "I want a remote internship next summer, and my favorite
programming language is Rust." Then choose **New session** to start a fresh chat.

**New session** clears the current conversation, but long-term memory carries over.

You should see an empty chat.

### Step 21. Test recall

Wait about two minutes, then ask: "What do you remember about me?"

AgentCore Memory extracts facts and preferences from your chat in the background, which took one to two minutes in
testing. After that, the coach recalls things from the earlier session.

You should see the coach mention something you said before the new session, such as your exam or your favorite
language.

---

## Part 4: Bonus, insights and trends (5 min)

### Step 22. Open the Insights tab

On the dashboard, open the **Insights** tab.

You should see stats, a skill knowledge graph (you to categories to skills), and a trends area.

### Step 23. Update your profile

Choose **Update my profile** (above the tabs). The coach doesn't keep copies of your files, so upload
`jordan-resume.md` again, add a new achievement such as "Deployed my Flask API to AWS Lambda", then choose
**Next: goals** and **Build my coach**. Your goals are already filled in.

**Update my profile** creates version 2 of your profile, which is what makes trends appear.

You should see the dashboard rebuild, now at version 2.

### Step 24. See the trends

Go back to the **Insights** tab.

You should see trend lines comparing version 1 and version 2: alignment change, skill level changes, and any new
skills.

---

## Clean up (2 min, then about 10 min of waiting)

Do this before you leave. The server and the NAT gateway are billed by the hour until the stack is gone.

### Step 25. Delete the stack

In CloudFormation, select the `career-coach` stack, choose **Delete**, and confirm.

This removes everything the stack created: the server, the network, the HTTPS link, the sign-in, and the memory
with everything the coach stored in it. CloudFront takes the longest to remove.

You should see the stack disappear from the list (choose the refresh button now and then). If the status turns to
`DELETE_FAILED`, choose **Retry delete**.

---

## Troubleshooting

When something goes wrong with the model, the coach says what to fix: under the header pill and in the error box.
The message starts with the words in the first column.

| Symptom | Fix |
|---|---|
| The stack won't start: "Deploy in US East (N. Virginia) or US West (Oregon)" | Switch the console region in the top-right corner and start again |
| `ROLLBACK_IN_PROGRESS`, and the Events tab says the server "Failed to receive 1 resource signal" | The server couldn't download or start the coach. Check that **Coach container image** was left as it is, then delete the stack and create it again. If it fails a second time, ask the presenter |
| `ROLLBACK_IN_PROGRESS` with an IAM or "not authorized" message | Your user needs administrator access (prework step 1) |
| No email after the stack finished | Check the spam folder. If the email address was mistyped, delete the stack and create it again |
| "That email and password don't match" | Copy the temporary password from the email exactly. It expires after 7 days |
| "Your sign-in has expired" | Sign in again. A sign-in lasts until you close the browser tab, up to 7 days |
| "Anthropic asks for a one-time use-case form" | In the Bedrock console, open **Model catalog**, choose **Claude Haiku 5.5** and submit the form (prework step 2) |
| "Claude models are sold through AWS Marketplace, so your AWS account needs a payment method" | Add one in the Billing console under **Payment preferences**, wait a few minutes, and try again |
| "This AWS account or user can't use Claude Haiku 5.5 yet" | Upgrade a free-plan account to the paid plan. If you just sent the use-case form, wait for AWS's email |
| "Amazon Bedrock is still verifying this new AWS account" | Only AWS can finish this, so open a support case. Pair with a neighbour for today |
| "Amazon Bedrock is busy right now" | Wait a few seconds and try again |
| "You've used today's profile builds" or "chat messages" | The stack caps each person at 10 builds and 100 chat messages a day, to protect your bill |
| Next steps all say "Not checked" | The free web search is rate-limited on busy networks. Wait a minute, or redeploy with a free Tavily key from tavily.com in the **Tavily API key** parameter |
| The page says "API offline" | The server is restarting. Wait a minute and refresh |

---

## Glossary

- **Agent**: a program that uses an AI model to decide what to do next, including which tools to call.
- **Model**: the AI that generates text. Here it is Claude Haiku 5.5 from Anthropic.
- **Amazon Bedrock**: the AWS service that runs AI models such as Claude in your AWS account, paid per use.
- **AWS CloudFormation**: creates and deletes a set of AWS resources from one template file. The set is a stack.
- **Amazon EC2**: virtual servers. Your coach runs on one, in a private subnet with no public address.
- **Amazon CloudFront**: serves websites over HTTPS from locations around the world. Here it is the only way to
  reach your server.
- **Amazon Cognito**: sign-in for your apps. Here it holds one account: yours.
- **Strands**: an open-source toolkit for building agents. It connects the model, the tools, and the chat loop.
- **Memory**: what the coach retains about you.
- **Short-term memory**: the messages in the current chat session.
- **Long-term memory**: facts, preferences and progress that carry across sessions.
- **AgentCore Memory**: an AWS memory service that stores chat events and extracts long-term facts for you.

---

## What to build next

1. **Read the template.** Open `infra/career-coach.yaml` and match each resource to what you saw in Step 9. The
   comments say why each piece is there.
2. **Change the coach.** Clone the repository, edit the prompts in `backend/coach/synthesis.py` or
   `backend/coach/coach_agent.py`, and run it on your laptop as the README describes, or push your change to your
   own fork and deploy the stack from it.
3. **Add your own tool.** Give the coach a tool that looks up open job postings for the target role and compares
   them against the profile's skills.
