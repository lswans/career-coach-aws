import { describe, expect, it, vi } from 'vitest';
import { jsonResponse, PROFILE_RESPONSE, sse, streamResponse } from '../test/fixtures';
import type { BuildEvent, ChatEvent } from './types';
import { buildProfile, getHealth, getProfile, streamChat } from './client';

const INPUT = { files: [], entries: [], goals: 'x' };

describe('API client', () => {
  it('maps a 422 error body to status, code, message and fields', async () => {
    const body = {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Your intake is not ready for synthesis yet.',
        fields: { goals: 'Describe your career goals in at least 200 characters', documents: 'Add at least one document' },
      },
    };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(422, body)));
    await expect(buildProfile('jordan-ab12', INPUT, () => undefined)).rejects.toEqual({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Your intake is not ready for synthesis yet.',
      fields: body.error.fields,
    });
  });

  it('asks for a stream, sends the form, passes progress on and resolves with the profile', async () => {
    const stage = { type: 'stage', stage: 'read', state: 'done', detail: '1 document · 8 characters' } as const;
    const progress = { type: 'progress', section: 'skills', chars: 120, skills: ['Python'], weaknesses: [], opportunities: [] } as const;
    const raw = sse(stage) + sse(progress) + sse({ type: 'done', ...PROFILE_RESPONSE });
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => streamResponse([raw.slice(0, 30), raw.slice(30)]));
    vi.stubGlobal('fetch', fetchMock);
    const resume = new File(['# Resume'], 'resume.md', { type: 'text/markdown' });
    const events: BuildEvent[] = [];

    const result = await buildProfile(
      'jordan-ab12',
      { files: [resume], entries: [{ label: 'Achievements', text: 'Hackathon 2nd place' }], goals: 'Become an ML engineer' },
      (e) => events.push(e),
    );

    expect(result).toEqual(PROFILE_RESPONSE);
    expect(events).toEqual([stage, progress]);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/api/users/jordan-ab12/profile');
    expect(init?.method).toBe('POST');
    expect(init?.headers).toEqual({ Accept: 'text/event-stream' });
    const form = init?.body as FormData;
    expect((form.getAll('files') as File[]).map((f) => f.name)).toEqual(['resume.md']);
    expect(JSON.parse(form.get('entries') as string)).toEqual([{ label: 'Achievements', text: 'Hackathon 2nd place' }]);
    expect(form.get('goals')).toBe('Become an ML engineer');
  });

  it('rejects with the in-band error when the build fails mid-stream', async () => {
    const raw = sse({ type: 'error', code: 'MODEL_UNAVAILABLE', message: "Can't reach Ollama. Start it, then try again." });
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse([raw])));
    await expect(buildProfile('jordan-ab12', INPUT, () => undefined)).rejects.toEqual({
      status: 0,
      code: 'MODEL_UNAVAILABLE',
      message: "Can't reach Ollama. Start it, then try again.",
    });
  });

  it('reports a network failure as NETWORK_ERROR', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    await expect(getHealth()).rejects.toMatchObject({ status: 0, code: 'NETWORK_ERROR' });
  });

  it('copes with an error body that is not JSON', async () => {
    const res = { ok: false, status: 500, json: async () => Promise.reject(new SyntaxError('bad json')) };
    vi.stubGlobal('fetch', vi.fn(async () => res as unknown as Response));
    await expect(getProfile('jordan-ab12')).rejects.toEqual({
      status: 500,
      code: 'HTTP_ERROR',
      message: 'Request failed with status 500.',
    });
  });

  it('uses the API address saved in Settings', async () => {
    localStorage.setItem('career-coach:apiBase', 'http://localhost:9000/');
    const fetchMock = vi.fn(async (_url: string) => jsonResponse(200, {}));
    vi.stubGlobal('fetch', fetchMock);
    await getHealth();
    expect(fetchMock.mock.calls[0]![0]).toBe('http://localhost:9000/api/health');
  });

  it('streams chat events from a body that arrives in uneven chunks', async () => {
    const note = { kind: 'win', text: 'Shipped my API', skill: 'AWS', created_at: '2026-10-06T22:00:00Z' };
    const raw = sse({ type: 'memory', note }) + sse({ type: 'delta', text: 'Nice ' }) + sse({ type: 'delta', text: 'work!' })
      + sse({ type: 'done', text: 'Nice work!', tools: [], recorded: note });
    const chunks = [raw.slice(0, 7), raw.slice(7, 80), raw.slice(80, 81), raw.slice(81)];
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => streamResponse(chunks));
    vi.stubGlobal('fetch', fetchMock);

    const events: ChatEvent[] = [];
    await streamChat('jordan-ab12', { message: 'I shipped my API', session_id: 's-1' }, (e) => events.push(e));

    expect(events.map((e) => e.type)).toEqual(['memory', 'delta', 'delta', 'done']);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/api/users/jordan-ab12/chat');
    expect(JSON.parse(init?.body as string)).toEqual({ message: 'I shipped my API', session_id: 's-1' });
  });
});
