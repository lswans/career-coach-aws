import { authHeaders } from './auth';
import { getApiBase } from './config';
import { SseParser } from './sse';
import type {
  BuildEvent,
  ChatEvent,
  Health,
  Insights,
  NormalizedError,
  ProfileResponse,
} from './types';

type RawErrorBody = {
  error?: { code?: string; message?: string; fields?: Record<string, string> };
};

/** Normalize any failed response/exception into a NormalizedError. */
async function normalizeError(res: Response): Promise<NormalizedError> {
  let body: RawErrorBody | null = null;
  try {
    body = (await res.json()) as RawErrorBody;
  } catch {
    body = null;
  }
  const err = body?.error;
  return {
    status: res.status,
    code: err?.code ?? 'HTTP_ERROR',
    message: err?.message ?? `Request failed with status ${res.status}.`,
    ...(err?.fields ? { fields: err.fields } : {}),
  };
}

function networkError(e: unknown): NormalizedError {
  return {
    status: 0,
    code: 'NETWORK_ERROR',
    message:
      e instanceof Error && e.name === 'AbortError'
        ? 'The request was cancelled.'
        : 'Could not reach the API. Is the backend running?',
  };
}

export function isNormalizedError(e: unknown): e is NormalizedError {
  return (
    typeof e === 'object' &&
    e !== null &&
    'status' in e &&
    'code' in e &&
    'message' in e
  );
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${getApiBase()}${path}`, { signal, headers: await authHeaders() });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await normalizeError(res);
  return (await res.json()) as T;
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  return getJson<Health>('/api/health', signal);
}

/** Hosted mode: the signed-in person's user id. */
export async function getMe(signal?: AbortSignal): Promise<{ user_id: string }> {
  return getJson<{ user_id: string }>('/api/me', signal);
}

export async function getProfile(
  userId: string,
  signal?: AbortSignal,
): Promise<ProfileResponse> {
  return getJson<ProfileResponse>(
    `/api/users/${encodeURIComponent(userId)}/profile`,
    signal,
  );
}

export async function getInsights(
  userId: string,
  signal?: AbortSignal,
): Promise<Insights> {
  return getJson<Insights>(
    `/api/users/${encodeURIComponent(userId)}/insights`,
    signal,
  );
}

export type BuildProfileInput = {
  files: File[];
  entries: { label: string; text: string }[];
  goals: string;
};

/** Read an SSE body to the end, handing each parsed event to `onEvent`. */
async function readEvents<T extends { type: string }>(res: Response, onEvent: (evt: T) => void): Promise<void> {
  if (!res.body) throw { status: 0, code: 'NETWORK_ERROR', message: 'No response body.' } satisfies NormalizedError;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser<T>();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const evt of parser.push(decoder.decode(value, { stream: true }))) onEvent(evt);
    }
    for (const evt of parser.flush()) onEvent(evt);
  } finally {
    reader.releaseLock();
  }
}

/**
 * Build the profile, streaming real progress (stages, what the model has written so far)
 * to `onEvent`. Resolves with the saved profile. Intake problems come back as a 422
 * NormalizedError with `fields`; a failure after the build started has status 0.
 */
export async function buildProfile(
  userId: string,
  input: BuildProfileInput,
  onEvent: (evt: BuildEvent) => void,
  signal?: AbortSignal,
): Promise<ProfileResponse> {
  const form = new FormData();
  for (const file of input.files) form.append('files', file);
  form.append('entries', JSON.stringify(input.entries));
  form.append('goals', input.goals);

  let res: Response;
  try {
    res = await fetch(`${getApiBase()}/api/users/${encodeURIComponent(userId)}/profile`, {
      method: 'POST',
      headers: { Accept: 'text/event-stream', ...(await authHeaders()) },
      body: form,
      signal,
    });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await normalizeError(res);

  // Set from inside the callback, so keep them on an object (TS does not track closure writes to lets).
  const out: { result?: ProfileResponse; failure?: NormalizedError } = {};
  try {
    await readEvents<BuildEvent>(res, (evt) => {
      if (evt.type === 'done') out.result = { profile: evt.profile, insights: evt.insights };
      else if (evt.type === 'error') out.failure = { status: 0, code: evt.code, message: evt.message };
      else onEvent(evt);
    });
  } catch (e) {
    throw isNormalizedError(e) ? e : networkError(e);
  }
  if (out.failure) throw out.failure;
  if (!out.result) throw { status: 0, code: 'NETWORK_ERROR', message: 'The build stopped before it finished.' } satisfies NormalizedError;
  return out.result;
}

/**
 * POST the chat message and read the SSE stream, invoking `onEvent` for each
 * parsed event. Resolves when the stream ends. Throws a NormalizedError on a
 * non-2xx response or network failure.
 */
export async function streamChat(
  userId: string,
  body: { message: string; session_id: string; request_id?: string },
  onEvent: (evt: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(
      `${getApiBase()}/api/users/${encodeURIComponent(userId)}/chat`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
        body: JSON.stringify(body),
        signal,
      },
    );
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await normalizeError(res);
  await readEvents<ChatEvent>(res, onEvent);
}
