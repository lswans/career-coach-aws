import type { Health, Insights, ProfileResponse } from '../api/types';

/** A fetch Response stand-in with just what the client reads. */
export function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
}

/** A 200 response whose body arrives in the given text chunks, like a real SSE stream. */
export function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  let i = 0;
  const body = {
    getReader: () => ({
      read: async () =>
        i < chunks.length ? { done: false, value: encoder.encode(chunks[i++]) } : { done: true, value: undefined },
      releaseLock: () => undefined,
    }),
  };
  return { ok: true, status: 200, body } as unknown as Response;
}

export const sse = (event: object) => `data: ${JSON.stringify(event)}\n\n`;

export const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  provider: 'bedrock',
  model: 'Claude Haiku 5.5',
  model_id: 'us.anthropic.claude-haiku-5-5',
  model_status: { reachable: true, model_ready: true, detail: 'ok' },
  memory_backend: 'local',
  web_search: 'ddgs',
  rules: { min_goal_chars: 200, min_doc_chars: 50, max_files: 10, max_file_mb: 5, allowed_extensions: ['.pdf', '.docx', '.txt', '.md'] },
};

const INSIGHTS: Insights = {
  stats: {
    goal_alignment: 42,
    readiness_pct: 50,
    skills_total: 2,
    avg_level: 3.5,
    focus_area: 'Model deployment on AWS',
  },
  graph: {
    nodes: [
      { id: 'you', label: 'You', type: 'you' },
      { id: 'cat:technical', label: 'Technical', type: 'category' },
      { id: 'skill:python', label: 'Python', type: 'skill', level: 4, relevance: 'high' },
      { id: 'skill:sql', label: 'SQL', type: 'skill', level: 3, relevance: 'medium' },
      { id: 'gap:0', label: 'Model deployment on AWS', type: 'gap', severity: 'high' },
      { id: 'opp:0', label: 'Deploy the review classifier', type: 'opportunity', timeframe: 'this month' },
      { id: 'target:aws', label: 'AWS', type: 'target' },
    ],
    edges: [
      { source: 'you', target: 'cat:technical', type: 'has' },
      { source: 'cat:technical', target: 'skill:python', type: 'includes' },
      { source: 'cat:technical', target: 'skill:sql', type: 'includes' },
      { source: 'you', target: 'gap:0', type: 'gap' },
      { source: 'opp:0', target: 'skill:python', type: 'builds' },
      { source: 'opp:0', target: 'target:aws', type: 'builds' },
    ],
  },
  trends: {
    snapshots: [{ version: 1, created_at: '2026-10-06T12:00:00Z', goal_alignment: 42, readiness_pct: 50, skills_total: 2, avg_level: 3.5 }],
    alignment_delta: null,
    skill_changes: [],
    new_skills: [],
    notes_by_week: [{ week_start: '2026-10-05', total: 0, win: 0, learning: 0, certification: 0, project: 0, setback: 0 }],
    momentum_14d: 0,
    themes: [],
    recent_notes: [],
  },
};

export const PROFILE_RESPONSE: ProfileResponse = {
  profile: {
    user_id: 'jordan-ab12',
    version: 1,
    created_at: '2026-10-06T12:00:00Z',
    headline: 'CS student who ships data pipelines',
    summary: 'You build Python data tools and want to move into ML engineering.',
    target_role: 'Machine Learning Engineer',
    goal_alignment: 42,
    goals: 'I want to become a machine learning engineer working on cloud-based AI products.',
    model: 'us.anthropic.claude-haiku-5-5',
    skills: [
      { name: 'Python', category: 'technical', level: 4, relevance: 'high', evidence: ['Built a Python ETL job'] },
      { name: 'SQL', category: 'technical', level: 3, relevance: 'medium', evidence: ['PostgreSQL'] },
    ],
    weaknesses: [{ area: 'Model deployment on AWS', why_it_matters: 'Core to ML engineering', severity: 'high' }],
    opportunities: [
      { title: 'Deploy the review classifier', action: 'Serve it behind an API on AWS', timeframe: 'this month', related_skills: ['Python', 'AWS'] },
    ],
    sources: [{ name: 'jordan-resume.md', kind: 'file', chars: 1200, truncated: false }],
  },
  insights: INSIGHTS,
};
