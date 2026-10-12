# Career Coach API contract

Base URL: `http://127.0.0.1:8000` (local only, no auth). All bodies are JSON unless noted.
The implementation is in `backend/coach/api.py`. `backend/tests/test_api.py` locks this contract in.

## Errors

Every non-2xx response has this shape:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Human readable.", "fields": { "goals": "..." } } }
```

`fields` appears only on validation errors. Codes: `VALIDATION_ERROR` (422), `BAD_USER_ID` (400),
`PROFILE_NOT_FOUND` (404), `PROFILE_REQUIRED` (409), `SYNTHESIS_FAILED` (502), `MODEL_UNAVAILABLE` (503, the model
can't be used; `message` names the fix, the same sentence as `detail` in `/api/health`),
`MEMORY_UNAVAILABLE` (503, AgentCore Memory unreachable; `message` says how to fix it, for example `aws login`).
Hosted mode only: `UNAUTHORIZED` (401, no or invalid sign-in), `FORBIDDEN` (403, another user's id),
`DAILY_LIMIT` (429, the per-user daily cap on builds or chats).

## Sign-in (hosted mode)

With `COACH_AUTH=cognito` (set by `infra/career-coach.yaml`), every `/api/users/{user_id}/...` route needs a Cognito
access token in `X-Coach-Auth: Bearer <token>` (or `Authorization`), and `user_id` must be the caller's own:
`u-` plus the token's `sub`. `GET /api/me` returns `{ "user_id": "u-..." }`. `/api/health` stays open and reports
`"auth": { "mode": "cognito", "region": "us-east-1", "client_id": "..." }`, which the website uses to sign in. In
local mode `auth` is `{ "mode": "none" }`, `/api/me` is 404 and nothing else changes.

## `user_id`

The client picks it: `^[a-z0-9][a-z0-9-]{1,62}$`, for example `jordan-rivera-x7k2`.

## GET /api/health

```json
{
  "status": "ok", "version": "0.1.0",
  "provider": "bedrock", "model": "Claude Haiku 5.5", "model_id": "us.anthropic.claude-haiku-5-5",
  "model_status": { "reachable": true, "model_ready": true, "detail": "ok" },
  "memory_backend": "local",
  "web_search": "ddgs",
  "rules": { "min_goal_chars": 200, "min_doc_chars": 50, "max_files": 10, "max_file_mb": 5,
             "allowed_extensions": [".pdf", ".docx", ".txt", ".md"] }
}
```

`provider` is `"bedrock"` (the default, Claude on Amazon Bedrock) or `"ollama"` (the local fallback,
`COACH_PROVIDER=ollama`). `model_id` is the model the coach calls: the Bedrock model or inference-profile id
(`COACH_BEDROCK_MODEL`, default `us.anthropic.claude-haiku-5-5`), or the Ollama tag (with `COACH_MODEL=auto`, the
first pulled of `qwen3:4b-instruct`, `qwen3:1.7b`). `model` is the same thing for display: Claude ids become names
like `Claude Haiku 5.5`, and other ids lose only their region prefix.

`model_status.model_ready` is true when the model really answers. On Bedrock that takes one call of about 20
tokens, cached for 10 minutes after it works and 20 seconds after it fails, so a fixed account turns green
quickly. `reachable` is false when the check got no answer from Bedrock or Ollama at all (no credentials, no
network, or Ollama not running). When `model_ready` is false,
`detail` is one sentence that names the fix, for example Anthropic's use-case form, a payment method or
`aws login` on Bedrock, or the `ollama pull` command to run.

`memory_backend` is `"local"` or `"agentcore"`. `web_search` is `"ddgs"` (default, no key), `"tavily"`
(`TAVILY_API_KEY` set) or `"off"` (`COACH_WEB_SEARCH=off`). The UI must read its validation limits from `rules`;
don't hard-code them.

## POST /api/users/{user_id}/profile  (multipart/form-data)

Builds a new profile version: reads the documents, runs one model call, checks the suggested next steps on
the web, then saves. It takes about 15 seconds on Claude Haiku 5.5, or 1-2 minutes on a laptop CPU with Ollama.

- With `Accept: text/event-stream` (what the UI sends) the answer is `200 text/event-stream`: progress
  events as they happen, then `done`. Read it like the chat stream below.
- Without it the answer is one `201` JSON response at the end (handy for curl and tests).
- Intake problems are a `422` JSON error either way, before any streaming starts.

| Field | Type | Notes |
|---|---|---|
| `files` | file, repeatable | 0-10 files, .pdf .docx .txt .md, 5 MB each |
| `entries` | string | JSON list: `[{"label": "Achievements", "text": "..."}]` from the paste boxes |
| `goals` | string | Required, at least 200 characters after trimming |

Rule: documents (files plus entries) must total at least 50 characters AND goals must be at least
200 characters. Otherwise 422 with any of `fields.documents`, `fields.goals`, `fields.files`
(per-file problems such as wrong type, too large or no text). Progress notes from chat are added to
the model's prompt (not to `sources`), so a rebuild knows what the person has done since.

Stream events (each one only when the step really happens; nothing is paced by a timer):

| `type` | Payload | Meaning |
|---|---|---|
| `stage` | `stage`: `read`, `model`, `verify` or `save`; `state`: `active`, `done` or `skipped`; `detail` | A step started, finished or was skipped. `detail` is display text |
| `progress` | `section`, `chars`, `skills`, `weaknesses`, `opportunities` (names so far) | What the model has written so far, read off its streaming JSON (about every 0.4 s) |
| `done` | `profile`, `insights` | The saved result |
| `error` | `code`, `message` | The build failed after streaming started (same codes as above) |

JSON response (and the `done` payload): `{ "profile": CareerProfile, "insights": Insights }`

```ts
type Rating = "high" | "medium" | "low";
type CareerProfile = {
  user_id: string; version: number; created_at: string /* ISO UTC, ends with Z */;
  headline: string; summary: string; target_role: string;
  goal_alignment: number;                       // 0-100
  goals: string; model: string;
  skills: { name: string; category: "technical" | "tool" | "domain" | "soft";
            level: number /* 1-5 */; relevance: Rating; evidence: string[] }[];
  weaknesses: { area: string; why_it_matters: string; severity: Rating }[];
  opportunities: { title: string; action: string;
                   timeframe: "this week" | "this month" | "this quarter" | "this year";
                   related_skills: string[];
                   // The web check (absent on profiles saved before it existed):
                   verification?: "verified" | "corrected" | "unverified" | "general" | "unchecked";
                   source_title?: string; source_url?: string;
                   original_title?: string /* the model's wording, when corrected */ }[];
  sources: { name: string; kind: "file" | "text"; chars: number; truncated: boolean }[];
};
```

`verification`: `verified` = a search result names the offering (`source_*` link to it); `corrected` = it
doesn't, but a close real one does, so the step was renamed to it; `unverified` = nothing matching was found;
`general` = general advice that names no course or certification; `unchecked` = search was off, failed or
returned nothing.

## GET /api/users/{user_id}/profile -> 200 | 404

`{ "profile": CareerProfile, "insights": Insights }` for the latest version. 404 `PROFILE_NOT_FOUND` means
"show the setup wizard".

## GET /api/users/{user_id}/insights -> 200 | 404

```ts
type Insights = {
  stats: {
    goal_alignment: number; readiness_pct: number; skills_total: number; avg_level: number;
    focus_area: string | null;                                       // the most severe gap
  };
  graph: {
    nodes: { id: string; label: string;
             type: "you" | "category" | "skill" | "target" | "gap" | "opportunity";
             level?: number; relevance?: Rating; severity?: Rating; timeframe?: string }[];
    edges: { source: string; target: string; type: "has" | "includes" | "gap" | "builds" }[];
  };
  trends: {
    snapshots: { version: number; created_at: string; goal_alignment: number; readiness_pct: number;
                 skills_total: number; avg_level: number }[];       // oldest first
    alignment_delta: number | null;                                  // latest minus previous
    skill_changes: { skill: string; from: number; to: number; delta: number }[];
    new_skills: string[];
    notes_by_week: { week_start: string; total: number; win: number; learning: number;
                     certification: number; project: number; setback: number }[];  // last 8 weeks
    momentum_14d: number;
    themes: { skill: string; count: number }[];
    recent_notes: ProgressNote[];                                     // newest first, max 10
  };
};
type ProgressNote = { kind: "win" | "learning" | "certification" | "project" | "setback";
                      text: string; skill: string; created_at: string };
```

Graph meaning: `you` connects to each `category`, categories to `skill`s (have it), opportunities
`builds` existing skills or `target` skills (wanted, not yet held), and `you` connects to each `gap`.

## POST /api/users/{user_id}/chat -> 200 text/event-stream | 409

Body: `{ "message": "1-4000 chars", "session_id": "^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$" }`

Chat history persists per `session_id`. Long-term memory (profile, progress notes and, with AgentCore,
extracted facts and preferences) carries across sessions. The response is a POST stream, so read it
with `fetch` and a stream reader, not `EventSource`. Each event is one line `data: <json>`
followed by a blank line:

| `type` | Payload | Meaning |
|---|---|---|
| `memory` | `note: ProgressNote` | Sent first, only when the message reported progress and it was saved |
| `sources` | `items: {title, url}[]` | Web results the coach was given, numbered to match its `[1]` citations. Only for questions about certifications, courses, jobs or events |
| `delta` | `text` | Next chunk of the reply; append it |
| `tool` | `name` | The coach looked something up (`get_profile_section`) |
| `check` | `unverified: string[]` | Certification names in the reply that no web result backs up (sent before `done`) |
| `done` | `text`, `tools: string[]`, `recorded: ProgressNote \| null` | Final reply text |
| `error` | `message` | The model failed mid-stream |

After a `memory` event, re-fetch insights so the trends update.
