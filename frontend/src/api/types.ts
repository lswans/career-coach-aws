// Types mirroring docs/API.md. Source of truth for request/response shapes.

export type Rating = 'high' | 'medium' | 'low';
export type SkillCategory = 'technical' | 'tool' | 'domain' | 'soft';
export type Timeframe = 'this week' | 'this month' | 'this quarter' | 'this year';
export type NoteKind = 'win' | 'learning' | 'certification' | 'project' | 'setback';

export type ApiErrorCode =
  | 'VALIDATION_ERROR'
  | 'BAD_USER_ID'
  | 'PROFILE_NOT_FOUND'
  | 'PROFILE_REQUIRED'
  | 'SYNTHESIS_FAILED'
  | 'MODEL_UNAVAILABLE'
  | 'MEMORY_UNAVAILABLE'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'DAILY_LIMIT'
  | 'HTTP_ERROR'
  | 'NETWORK_ERROR';

// Normalized client-side error shape.
export type NormalizedError = {
  status: number;
  code: ApiErrorCode | string;
  message: string;
  fields?: Record<string, string>;
};

export type HealthRules = {
  min_goal_chars: number;
  min_doc_chars: number;
  max_files: number;
  max_file_mb: number;
  allowed_extensions: string[];
};

export type Health = {
  status: string;
  version: string;
  provider: 'bedrock' | 'ollama';
  model: string; // display name, e.g. "Claude Haiku 5.5" or "qwen3:1.7b"
  model_id: string; // what the backend calls, e.g. "us.anthropic.claude-haiku-5-5"
  model_status: { reachable: boolean; model_ready: boolean; detail: string };
  // "none" on a laptop; "cognito" when the CloudFormation stack runs the coach
  auth?: { mode: 'none' | 'cognito'; region?: string; client_id?: string };
  memory_backend: 'local' | 'agentcore';
  web_search: string; // 'ddgs' | 'tavily' | 'off'
  rules: HealthRules;
};

export type Skill = {
  name: string;
  category: SkillCategory;
  level: number; // 1-5
  relevance: Rating;
  evidence: string[];
};

export type Weakness = {
  area: string;
  why_it_matters: string;
  severity: Rating;
};

// How the web check judged a suggested next step (absent on profiles saved before the check existed).
export type Verification = 'verified' | 'corrected' | 'unverified' | 'general' | 'unchecked';

export type Opportunity = {
  title: string;
  action: string;
  timeframe: Timeframe;
  related_skills: string[];
  verification?: Verification;
  source_title?: string;
  source_url?: string;
  original_title?: string;
};

export type Source = {
  name: string;
  kind: 'file' | 'text';
  chars: number;
  truncated: boolean;
};

export type CareerProfile = {
  user_id: string;
  version: number;
  created_at: string; // ISO UTC, ends with Z
  headline: string;
  summary: string;
  target_role: string;
  goal_alignment: number; // 0-100
  goals: string;
  model: string;
  skills: Skill[];
  weaknesses: Weakness[];
  opportunities: Opportunity[];
  sources: Source[];
  // How this version was made (absent on profiles saved before chat refreshes existed).
  origin?: 'intake' | 'refresh';
  request_id?: string;
  notes_used?: number;
};

export type GraphNodeType =
  | 'you'
  | 'category'
  | 'skill'
  | 'target'
  | 'gap'
  | 'opportunity';

export type GraphNode = {
  id: string;
  label: string;
  type: GraphNodeType;
  level?: number;
  relevance?: Rating;
  severity?: Rating;
  timeframe?: string;
};

export type GraphEdge = {
  source: string;
  target: string;
  type: 'has' | 'includes' | 'gap' | 'builds';
};

export type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type ProgressNote = {
  kind: NoteKind;
  text: string;
  skill: string;
  created_at: string;
  request_id?: string;
};

export type Snapshot = {
  version: number;
  created_at: string;
  goal_alignment: number;
  readiness_pct: number;
  skills_total: number;
  avg_level: number;
};

export type NotesByWeek = {
  week_start: string;
  total: number;
  win: number;
  learning: number;
  certification: number;
  project: number;
  setback: number;
};

export type InsightsStats = {
  goal_alignment: number;
  readiness_pct: number;
  skills_total: number;
  avg_level: number;
  focus_area: string | null;
};

export type Trends = {
  snapshots: Snapshot[]; // oldest first
  alignment_delta: number | null;
  skill_changes: { skill: string; from: number; to: number; delta: number }[];
  new_skills: string[];
  notes_by_week: NotesByWeek[]; // last 8 weeks
  momentum_14d: number;
  themes: { skill: string; count: number }[];
  recent_notes: ProgressNote[]; // newest first, max 10
};

export type Insights = {
  stats: InsightsStats;
  graph: Graph;
  trends: Trends;
};

export type ProfileResponse = { profile: CareerProfile; insights: Insights };

// Profile build SSE events (POST /profile with Accept: text/event-stream).
export type BuildStageId = 'read' | 'model' | 'verify' | 'save';
export type BuildStageState = 'pending' | 'active' | 'done' | 'skipped';
export type BuildProgress = {
  section: string;
  chars: number;
  skills: string[];
  weaknesses: string[];
  opportunities: string[];
};
export type BuildEvent =
  | { type: 'stage'; stage: BuildStageId; state: Exclude<BuildStageState, 'pending'>; detail: string }
  | ({ type: 'progress' } & BuildProgress)
  | { type: 'done'; profile: CareerProfile; insights: Insights }
  | { type: 'error'; code: string; message: string };

export type WebSource = { title: string; url: string };

// Chat SSE events. A reported milestone (or "refresh my profile") adds the profile_* events before
// the reply: profile_refresh while it builds, then profile_updated or profile_refresh_failed.
export type ChatEvent =
  | { type: 'memory'; note: ProgressNote }
  | { type: 'profile_refresh'; state: string; stage?: string; detail: string }
  | ({ type: 'profile_updated' } & ProfileResponse)
  | { type: 'profile_refresh_failed'; code: string; message: string; note_saved: boolean; retryable: boolean }
  | { type: 'sources'; items: WebSource[] }
  | { type: 'delta'; text: string }
  | { type: 'tool'; name: string }
  | { type: 'check'; unverified: string[] }
  | { type: 'done'; text: string; tools: string[]; recorded: ProgressNote | null; profile_version?: number | null }
  | { type: 'error'; message: string };
