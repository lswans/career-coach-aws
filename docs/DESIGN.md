# Career Coach: design

A career coach agent that uses Claude Haiku 5.5 on Amazon Bedrock in your own AWS account (or a free open-source
model on your laptop through Ollama), keeps its memory in Amazon Bedrock AgentCore Memory (or local files), and
serves a React site. Workshop attendees deploy all of it from one CloudFormation template
(`infra/career-coach.yaml`, see "The hosted stack" below). Developers can still run it on a laptop.

```
 Browser (React, Vite)  ── localhost or https://main.<id>.amplifyapp.com
        │  fetch + SSE
        ▼
 FastAPI on 127.0.0.1:8000 (backend/coach)
   ├─ synthesis.py   one structured-output call, streamed -> CareerProfile (no agent loop)
   ├─ llm.py         model per purpose: Bedrock (default) or Ollama; streamed structured output
   ├─ bedrock.py     Claude on Bedrock: access check, fix-it error messages
   ├─ verify.py      web check of suggested next steps and of chat replies
   ├─ search.py      web search: ddgs (no key) or Tavily; COACH_WEB_SEARCH=off disables
   ├─ coach_agent.py Strands Agent: chat, get_profile_section tool, routed progress capture
   ├─ insights.py    stats, skill graph, trends (pure Python)
   └─ memory/        local JSONL  |  AgentCore Memory
        │                               │
        ▼                               ▼
 Amazon Bedrock (us-east-1)        AgentCore Memory (us-east-1)
 Claude Haiku 5.5                  events + long-term records
 (or Ollama on 127.0.0.1:11434,
  qwen3, the offline fallback)
```

## The three parts

**1. The Coach: Strands Agents + Claude Haiku 5.5 on Amazon Bedrock.** With `COACH_PROVIDER=bedrock` (the
default), `strands.models.bedrock.BedrockModel` calls Claude Haiku 5.5 through the US cross-region inference
profile `us.anthropic.claude-haiku-5-5`, from `AWS_REGION` (default `us-east-1`), with the standard AWS
credential chain (`aws login`, IAM Identity Center or access keys). `COACH_BEDROCK_MODEL` picks another model.
Checked live on 2026-10-07:

- The bare model id `anthropic.claude-haiku-5-5` fails ("on-demand throughput isn't supported"), and a `us.` id
  called from an EU region fails as an invalid model identifier. The `global.anthropic.claude-haiku-5-5` profile
  also works from us-east-1. It can route a request to any commercial region; the coach defaults to the US
  profile so documents stay in US regions.
- Haiku 5.5 rejects `temperature` ("deprecated for this model"), so Bedrock calls never send it.
- Haiku 5.5 reasons before it answers, and those hidden tokens count against `max_tokens`: a 700-token chat limit
  ran out on a 170-word reply. The Bedrock budgets in `llm.BUDGETS` are roomy (8,192 tokens for a profile, 4,096
  for chat, 2,048 for extraction and checks), and you pay only for tokens the model writes.
- Reasoning effort stays at the model's default (`medium`). With the coach's real system prompt, Claude started
  writing after 0.7 to 1.1 s at the default, at `low`, and with thinking turned off, so a lower setting would buy
  nothing.

A brand-new AWS account needs a few one-time things before Claude answers: Anthropic's use-case form (once per
account or organization, and it can sit pending for a while), a payment method on the paid account plan (Claude is
sold through AWS Marketplace, which the free plan leaves out), `aws-marketplace:Subscribe` for the account's first
call, and `bedrock:InvokeModel` plus `bedrock:InvokeModelWithResponseStream`. Some new accounts are also held
for a few days while AWS verifies them ("Operation not allowed"). `bedrock.explain()` turns each of these errors,
and the usual credential, throttling and network ones, into one sentence that names the fix. It checks the message
text before the error code, because Bedrock reports a missing use-case form as `ResourceNotFoundException` and a
missing payment method as `AccessDeniedException`. The health check makes one real call of about 20 tokens,
cached for 10 minutes when it works and 20 seconds when it fails, because only a real call proves that the
credentials, permissions, form and subscription all line up. `scripts/set_model.py bedrock` runs the same check
from the terminal.

**The offline fallback: Ollama.** `scripts/set_model.py ollama [tag]` sets `COACH_PROVIDER=ollama`, and
`strands.models.ollama.OllamaModel` talks to a local Ollama server. `COACH_MODEL=auto` (the default) uses
`qwen3:4b-instruct` (Qwen3-4B-Instruct-2507, Apache-2.0, 2.5 GB, 256K context) if it's pulled, otherwise
`qwen3:1.7b` (1.4 GB, for laptops with 8 GB of RAM or less). qwen3:1.7b is a hybrid thinking model, and `llm.py`
turns its thinking off automatically by reading the model's capabilities from Ollama. Ollama pulls the weights
from its own registry, or from Hugging Face directly with `ollama pull hf.co/<org>/<repo>-GGUF`. Documents are
capped at 40,000 characters on Bedrock and 12,000 on Ollama (`COACH_MAX_DOC_CHARS`), since a small local context
fills up fast.

**2. The Brain: AgentCore Memory.** AgentCore is model-agnostic (its FAQ: "any foundation model in or outside of
Amazon Bedrock"), so the same memory code works with Claude and with the local model. The coach uses it in three
ways:

| Data | Stored as | Why |
|---|---|---|
| Profile snapshots | blob events in session `profile-snapshots` | exact, ordered history for trends |
| Progress notes | blob events in `progress-notes`, plus a long-term record in `/career/{actorId}/progress/` | exact list for charts, plus search by meaning for the coach |
| Chat turns | `AgentCoreMemorySessionManager` (short-term memory) | built-in strategies extract facts, preferences and summaries; relevant ones come back into context every turn |

Built-in extraction runs on AWS-managed models inside the service, not on the coach's model. New memories keep
events for 365 days.

Verified against a real memory on 2026-10-07 (`tests/test_live_agentcore.py`, plus the browser runs below):

- Profile snapshots and notes round-trip through blob events. **Send blobs as JSON strings.** A dict sent
  as a blob comes back from `ListEvents` as `{key=value, ...}` text that can't be parsed; the SDK's own
  session manager also `json.dumps` its blobs.
- A note written with `BatchCreateMemoryRecords` was found by semantic search 6 s later.
- Chat turns restored into a new `Agent` for the same session (3 messages).
- The built-in strategies extracted "The user wants a remote internship in summer 2027" (facts) and
  "Favorite programming language is Rust" (preferences) about 2 minutes after the chat. In the UI, a
  **New session** asked "What do you remember about me?" got an answer naming the exam from the earlier chat,
  on the local model and again on Claude.
- Errors from AWS (expired sign-in, missing memory, no permission) surface as `MEMORY_UNAVAILABLE` with a
  fix-it message instead of a model error.

Switching brains mid-workshop keeps your work: on the first start with `COACH_MEMORY=agentcore`, the backend
copies each local user's profile versions and notes into AgentCore (`coach/memory/migrate.py`). It only copies
users AgentCore doesn't have yet, so restarts never duplicate anything. User ids come from the first name alone
(`jordan`), so typing the same name on the hosted site opens the same coach.

`COACH_MEMORY=local` swaps in a JSON-lines store plus Strands `FileSessionManager`, with no AWS account.

**3. The Interface: React on Amplify Hosting.** It's a static site. `backend/scripts/deploy_amplify.py`
deploys `frontend/dist` with Amplify's manual-deploy API (no Git needed) and adds the site's origin to the
backend's CORS list. The hosted page calls the attendee's own `http://127.0.0.1:8000`. Browsers treat
loopback as a secure context, and Chrome's Local Network Access may ask the user before a public site can
reach this machine. The backend answers the private-network preflight (`allow_private_network=True`).
Tested 2026-10-07 from `https://main.<id>.amplifyapp.com` in Edge 154 (headless): the full flow worked
(profile, streamed chat, insights), first on the local model and again on Claude. A probe with no permission
granted also reached the API, but only because the test laptop's managed-browser policy turns Local Network
Access restrictions off (`LocalNetworkAccessRestrictionsTemporaryOptOut=1`). On an attendee's own laptop, expect
Chrome or Edge to ask, so the guide says to click Allow. Unknown origins get `400` on preflight.

**Bonus: Insights.** These are deterministic: stats, a skill knowledge graph (you -> categories -> skills;
opportunities -> skills you have and "target" skills you don't; gaps), and trends across profile versions and
progress notes. Nothing here calls the model, so it is instant and free. Trends match skills by name, so a skill
the model words differently in version 2 counts as new. Claude did this in testing ("scikit-learn / classical ML"
became "scikit-learn and ML modeling").

## The hosted stack (what workshop attendees deploy)

`infra/career-coach.yaml` creates everything in the attendee's own account, in us-east-1 or us-west-2:

```
 Browser ──HTTPS──► CloudFront ──VPC origin (private, HTTP 8000)──► EC2 t4g.small, private subnet, no public IP
    │                                                                  uvicorn: FastAPI API + the built website
    └──► Cognito (sign-in, USER_PASSWORD_AUTH)                         │ via NAT gateway, HTTPS only
                                                                       ├─► Bedrock (Claude Haiku 5.5)
                                                                       ├─► AgentCore Memory (created by the stack)
                                                                       └─► Cognito JWKS, web search
```

- **One origin.** The instance serves the built website and the API (`COACH_STATIC_DIR`), and the site calls the API
  on the same CloudFront URL (`VITE_API_BASE_URL=same-origin`). No CORS, no Amplify, and no localhost prompt.
- **Sign-in without redirects.** The site talks to Cognito's `InitiateAuth` with plain `fetch` (no SDK), handles the
  first-sign-in `NEW_PASSWORD_REQUIRED` challenge, and keeps tokens in `sessionStorage`. A hosted-UI redirect would
  need the CloudFront domain as a callback URL, and the CloudFront distribution depends on the instance, which needs
  the app client: a dependency cycle. Learning the pool settings from `/api/health` at runtime also means the site
  needs no build-time Cognito settings.
- **The token travels in `X-Coach-Auth`.** CloudFront doesn't pass the `Authorization` header to the origin on GET
  requests unless it is in the cache key, and the API is never cached. The backend accepts either header.
- **Identity comes from the token.** With `COACH_AUTH=cognito`, every user route verifies the access token (signature
  against the pool's JWKS, issuer, expiry, `token_use=access`, `client_id`) and only serves the caller's own id,
  `u-` plus the Cognito `sub`. `/api/me` tells the site that id. Local mode is unchanged.
- **Daily caps.** 10 profile builds and 100 chat messages per user per day (`COACH_DAILY_BUILDS`,
  `COACH_DAILY_CHATS`), counted in memory, so a leaked link can't run up the attendee's bill.
- **The coach ships as one container image.** The `Dockerfile` builds the website in a Node stage, installs the
  backend's locked packages with uv in a second stage, and copies both into a slim Python image that runs as a
  non-root user. Base images are pinned by digest. `.github/workflows/publish-image.yml` runs the backend and
  frontend tests, builds natively on an arm64 runner and pushes to Amazon ECR Public whenever a `v*` tag is pushed.
  It signs in to AWS through GitHub's OIDC provider, using a role from `infra/publish-image.yaml` that only that
  repository's tag builds can assume and that can push only to that one repository. It refuses to overwrite a tag
  that already exists, because attendees' stacks pin one.
- **The stack waits for a working coach.** The instance's start-up script installs Docker and writes the coach's
  settings, then sends `cfn-signal`. A Systems Manager State Manager association (`CoachDeploy`,
  `AWS-RunShellScript`) then pulls the image named by `ImageUri` (public, so no credentials), runs it under
  systemd with `--network host`, so the container reaches the instance role through IMDSv2 with a hop limit of 1,
  and waits for `/api/health`. The stack waits for the association (`WaitForSuccessTimeoutSeconds`), and the
  CloudFront origin depends on it, so `CREATE_COMPLETE` still means the health check answered. Nothing is
  compiled in the attendee's account.
- **Updating a running stack swaps the image, never the server.** CloudFront rejects any change to a VPC origin
  while a distribution uses it (HTTP 409, "disassociate the VPC origin from all distributions"), so a new server
  can't take over the link inside one stack update. Found the hard way on 2026-10-26: an update that only changed
  `ImageUri` also picked up a newer Amazon Linux AMI from the public SSM parameter, replaced the instance, and
  rolled back at `CoachVpcOrigin`. Two template rules prevent this. The image lives in the association, not in
  user data (user data runs on first boot only, and changing it stops and starts the server), and changing
  `ImageUri` updates the association, which State Manager runs at once. The script pulls the new image, restarts
  the service, checks that the health endpoint answers from the new image, and puts the previous image back and
  fails (so the stack rolls back) if it doesn't. And `ServerAmiId` pins the AMI: empty on create (newest AL2023),
  then the `ServerAmi` output on every update.
- **Least privilege.** The instance role can invoke the chosen inference profile (and the foundation models it
  routes to), subscribe through Bedrock on first use, and use this stack's memory only. Session Manager replaces
  SSH. IMDSv2 only, encrypted gp3 root volume.
- **Cost shape.** Per use: Bedrock tokens and AgentCore Memory. Per hour while the stack exists: the instance, the
  NAT gateway and its address. Deleting the stack removes everything, including the memory and its data.

Not yet verified: a real deployment. Both templates pass `cfn-lint` and CloudFormation's `validate-template`, the
Dockerfile passes hadolint, the workflow passes actionlint, and the hosted mode passed a local browser check (served
site, sign-in screen, 401 without a token). The image has never been built: the first `v*` tag on the public
repository is its first build.

## Decisions worth explaining in the talk

- **Synthesis is not an agent loop.** It's one structured-output call. On Bedrock, Strands' `structured_output`
  turns the `CareerProfile` schema into a tool that Claude has to call, and pydantic validates what comes back.
  On Ollama, the JSON-schema `format` constrains decoding, so even a 1.7B model returns valid JSON in our shape.
  Schema bounds (1-5 levels, list sizes) ride along, and Python clamps anything the model misses. A tool-calling
  loop would add round trips, and small models fail at tool calls more often than at filling a schema.
- **Progress capture is routed in code, not left to the model.** In live tests a 1.7B model never chose to call
  a `record_progress` tool, even with explicit instructions. A regex gate catches messages that might report
  progress. Only those get a short constrained extraction call, so questions cost no extra calls. The same
  routing runs on Claude, which keeps the two providers interchangeable.
- **Context discipline.** The system prompt carries a compact profile summary. The agent fetches details
  with `get_profile_section`, recall returns only the top 5 memories, and a sliding window keeps 20 messages.
- **Chat updates the profile, but the model never writes it.** The coach's only tool reads profile sections.
  When the extractor accepts a progress report, or the message asks to "refresh my profile", the API runs the
  same synthesis pipeline as setup and saves version N+1 before the coach replies, so the reply comes from the
  new profile. Raw uploads are never kept, so a refresh can't reread the resume. Instead
  `progress.baseline_document` turns the previous profile (headline, summary, skills with levels and evidence,
  gaps, next steps) into one synthetic document that says plainly it is the coach's earlier assessment, clipped
  to `COACH_MAX_DOC_CHARS`. The goal text is copied from the baseline unchanged; only the setup form, which
  validates it, can replace it. Two checks run in code after the model (`coach/progress.py`), because a small
  model often repeats a finished step:
  - a next step is dropped when a completion note (win, learning, certification or project; finished, not
    started or planned) contains the step title's distinctive words, adjacent and in order, after removing
    generic words like "AWS" and "certification". One word is only enough for a credential: "Learned Python"
    must not remove "Advanced Python course", and an Associate certification must not remove the Professional one;
  - a milestone reported since the baseline is added as evidence on the skill its note names, if that skill
    exists and the model didn't cite it. Code never invents a skill or a level.
- **Progress log budget for a refresh.** The model sees the newest notes, oldest first, up to 40 notes and
  6,000 characters, each clipped to 300 characters, and the stage detail says how many older notes were left
  out. The completed-step check reads the whole log, so an old completion still keeps its step off the list.
- **Refreshes are serialized and idempotent.** Each user has one in-process lock (the service runs one uvicorn
  worker) held for the whole build, setup builds included, and the version is one past the highest saved
  version, so concurrent requests can't save the same number. The browser sends a `request_id` per message and
  reuses it on retry: the note is stored once (checked again under a short lock after extraction), and a
  request that already produced a version replays it without a new build or a new charge against the daily
  build cap. If the build fails, the note stays, the stream says `profile_refresh_failed`, and the coach's
  prompt tells it not to claim an update.
- **Intake gate.** Documents (50+ characters) and goals (200+ characters) are both required, enforced on the
  server and mirrored in the UI from `/api/health` `rules`.
- **Live build progress, with no fake timers.** The build is an async generator of events streamed over SSE:
  read, model, verify, save. On Bedrock, Strands' `structured_output` already streams, and `llm.py` reads the
  tool-input JSON as Claude writes it (`contentBlockDelta.delta.toolUse.input`). Strands' `OllamaModel` sends
  `stream=False` for structured output, so for Ollama `llm.py` reuses Strands' `format_request` and streams the
  same constrained request. Either way the UI shows which part of the profile the model is writing and the skill
  names as they appear. Cancel stops generation: Ollama when the stream closes (tested live), and Bedrock through
  Strands' `cancel_signal` (unit-tested).
- **Models invent names, so code checks them.** In playtesting, qwen3:1.7b suggested an "AWS AI Advocate"
  certification, which does not exist. Every next step that names a certification, course or program is
  searched; the model says which offering the step names and which real one the results show, and code decides:
  the name's distinctive words must appear, in order, in the title of a result that looks like an offering page.
  Forums can't vouch, and neither can a racehorse (Wikipedia's "Cloud Computing (horse)" once matched a generic
  "Cloud Computing Course"). Outcomes are verified, corrected (renamed to the real one, with the original kept),
  unverified, general or unchecked. Empty results count as unchecked, never as invented: a rate-limited search
  engine often answers with nothing. Names that come from the person's own documents or goals count as general:
  Claude names projects from the resume ("Deploy your Course Review Classifier on AWS"), and the course detector
  used to flag the student's own project.
- **Chat gets web results too.** Messages about certifications, courses, jobs or events are searched while
  progress is extracted, the top 4 results go into the prompt as numbered sources, and the reply cites
  them. After the reply, certification names it mentions are checked the same way and flagged if nothing
  backs them up (in testing the local model recommended an "AWS Certified Advanced Networking and Security exam",
  which does not exist). Names from the person's own goals and evidence aren't re-checked. Questions about the
  conversation itself ("Which exam did I just tell you I passed?") skip the search: in testing, an unrelated
  search there made Claude take back the correct citations in its earlier reply. The prompt also says that
  citation numbers in earlier replies belong to earlier searches.
- **What leaves the laptop.** Documents, goals and chat go to Claude on Amazon Bedrock in the attendee's own
  account. Bedrock runs models in AWS-owned accounts that model providers can't reach, so Anthropic has no access
  to these prompts or replies
  ([Bedrock data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html)). With
  AgentCore Memory on, profiles, notes and chat turns are stored in the attendee's memory. The search provider
  sees only search text: a next step's title, or a chat question plus the target role, never documents. On the
  Ollama fallback with `COACH_WEB_SEARCH=off` and local memory, nothing leaves the laptop. The default search,
  ddgs, needs no key but reads public search engines, so treat it as a workshop tool; 50 attendees on one
  conference IP can get rate-limited, which is why `TAVILY_API_KEY` switches to Tavily's API (free tier, no card).

## What it costs

Pricing checked 2026-10-06 on the [AgentCore pricing page](https://aws.amazon.com/bedrock/agentcore/pricing/):
short-term ingestion $1.00/GB (12 KB minimum per event), storage $0.10/GB-month, retrieval $0.20/GB;
long-term records $0.75 per 1,000 per month (built-in strategies); long-term retrieval $0.50 per 1,000.
A workshop session (about 50 events, 30 records, 50 retrievals per attendee) costs well under one cent per
attendee.

Claude Haiku 5.5 launched on Bedrock on 2026-10-07 and wasn't in the AWS Price List that day. Anthropic lists it
at $0.10 per million input tokens and $0.50 per million output tokens (prompts up to 100K tokens), and the
[Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) is the reference once it appears there. For newer
models, Bedrock's pages show a regional (US) profile costing about 10% more than the global one. Measured usage: a
profile build is about 2,500 to 3,000 input and 2,000 output tokens, and a chat turn about 1,800 input and 1,000
output, so at list price a build costs about 0.2 cents, a chat turn about 0.1 cents, and a whole workshop about 2
cents per attendee.

## Measured (this laptop: Ryzen 5 PRO 8540U, CPU only, about 1-2.5 GB of RAM free)

On Claude Haiku 5.5 (Bedrock, us-east-1, 2026-10-07):

| Step | Time |
|---|---|
| Profile build through the browser UI, including the web check of next steps (3 runs) | 14-16 s; profile written after about 10 s |
| Version 2 rebuild through the browser UI | 12-13 s |
| Chat reply with progress extraction and a web search (4 sources), 3 runs | 12-14 s total; first words after 10-12 s |
| The model alone on the coach's system prompt, no tools or memory | first words after 0.7-1.1 s; about 2 s total |
| New-session recall reply on AgentCore Memory | 8 s |
| Live tests (`tests/test_live_model.py`): synthesis / next-step check / chat turn | about 13 s / 6 s / 6-8 s |

Claude starts writing about a second after it gets the prompt, so most of the wait before the first chat words
is the coach's own work before the reply (progress extraction, the web search, memory recall). Profiling those
steps is open work.

On the Ollama fallback (qwen3:1.7b on this laptop's CPU):

| Step | Time |
|---|---|
| Profile synthesis (sample persona, 3 docs, API test) | 32-51 s |
| Profile synthesis through the browser UI (resume upload + pasted achievements) | 45-98 s |
| Same, including the web check of next steps (3 runs) | 65-81 s; first model text after about 13 s |
| Checking 3 next steps alone (real ddgs + qwen3:1.7b) | 14-17 s |
| Chat reply including progress extraction | 9-24 s total; first streamed words after 12-18 s |
| Chat reply with a web search (4 sources) | 28-33 s total; first words after 22-25 s |

`qwen3:4b-instruct` was not measured here (not enough free disk or RAM). Expect it to be about 2x slower
on CPU and much faster on Apple Silicon.

AWS setup steps:

| Step | Time |
|---|---|
| Create the AgentCore Memory (`create_agentcore_memory.py`) | 160 s |
| Long-term facts and preferences searchable after a chat | about 2 min |
| Deploy to Amplify (`deploy_amplify.py`) | 11-16 s |
| Delete the Amplify app / the AgentCore Memory | 4 s / 158 s |

## Open-source alternatives to AgentCore Memory

| Option | What it is | Trade-off for this workshop |
|---|---|---|
| Local JSONL + `FileSessionManager` (built in) | Files on disk | No setup, no semantic search, no extraction |
| [Mem0](https://github.com/mem0ai/mem0) (Apache-2.0) | Extraction + vector memory library; can use Ollama for LLM and embeddings | Closest feature match; adds a vector store and more dependencies |
| [Letta](https://github.com/letta-ai/letta) (Apache-2.0) | Stateful agent server (MemGPT lineage) | Replaces the agent runtime, not just memory |
| [Graphiti](https://github.com/getzep/graphiti) (Apache-2.0) | Temporal knowledge graph memory | Great for "skills over time"; needs Neo4j or FalkorDB |
| [Cognee](https://github.com/topoteretes/cognee) (Apache-2.0) | Documents to knowledge graph + vectors | Strong for the doc-dump step; heavier setup |
| [LangMem](https://github.com/langchain-ai/langmem) (MIT) | Memory extraction primitives | Tied to the LangGraph ecosystem |

## Security

No authentication: the API binds to 127.0.0.1 and allows only the configured CORS origins. Don't expose it
on a network interface. Uploaded files are parsed in memory and never written to disk. Profiles, notes and
chat history live in `backend/data/` (git-ignored) or in your AgentCore Memory. Model calls go to Amazon Bedrock
with your own AWS credentials, and web searches send only the search text to the search provider. Links from
search results are rendered only if they are `http(s)` and open in a new tab with `rel="noopener noreferrer"`.
