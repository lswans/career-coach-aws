import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { sse, streamResponse } from '../test/fixtures';
import { CoachPanel } from './CoachPanel';

const NOTE = { kind: 'certification', text: 'Passed the AWS Cloud Practitioner exam', skill: 'AWS', created_at: '2026-10-06T22:00:00Z' };

function savedChat() {
  return JSON.parse(localStorage.getItem('career-coach:chat:jordan-ab12') ?? 'null') as {
    sessionId: string;
    messages: { role: string; text: string }[];
  };
}

describe('CoachPanel', () => {
  it('streams the reply, shows the progress chip and refreshes insights', async () => {
    const user = userEvent.setup();
    const raw = sse({ type: 'memory', note: NOTE }) + sse({ type: 'delta', text: 'Congrats! ' })
      + sse({ type: 'delta', text: 'Next, deploy your classifier.' })
      + sse({ type: 'done', text: 'Congrats! Next, deploy your classifier.', tools: [], recorded: NOTE });
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => streamResponse([raw.slice(0, 40), raw.slice(40)]));
    vi.stubGlobal('fetch', fetchMock);
    const onMemorySaved = vi.fn();
    render(<CoachPanel userId="jordan-ab12" onMemorySaved={onMemorySaved} />);

    await user.type(screen.getByLabelText('Message the coach'), 'I passed my AWS Cloud Practitioner exam!{Enter}');

    expect(await screen.findByText('Saved to your progress log: Passed the AWS Cloud Practitioner exam')).toBeInTheDocument();
    expect(screen.getByText('Congrats! Next, deploy your classifier.')).toBeInTheDocument();
    expect(onMemorySaved).toHaveBeenCalledTimes(1);

    const sent = JSON.parse(fetchMock.mock.calls[0]![1]!.body as string);
    expect(sent.message).toBe('I passed my AWS Cloud Practitioner exam!');
    expect(sent.session_id).toBe(savedChat().sessionId);
    expect(savedChat().messages.map((m) => m.role)).toEqual(['user', 'coach']);
  });

  it('lists the web sources a reply cites, as safe new-tab links', async () => {
    const user = userEvent.setup();
    const items = [
      { title: 'AWS Certified AI Practitioner', url: 'https://aws.amazon.com/certification/certified-ai-practitioner/' },
      { title: 'Sneaky', url: 'javascript:alert(1)' },
    ];
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse([
      sse({ type: 'sources', items }) + sse({ type: 'done', text: 'Try the AI Practitioner [1].', tools: [], recorded: null }),
    ])));
    render(<CoachPanel userId="jordan-ab12" onMemorySaved={() => undefined} />);
    await user.type(screen.getByLabelText('Message the coach'), 'Which AWS certification is next?{Enter}');

    const link = await screen.findByRole('link', { name: /AWS Certified AI Practitioner/ });
    expect(link).toHaveAttribute('href', items[0]!.url);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('Sneaky').closest('a')).toBeNull(); // not http(s), so not a link
    expect(JSON.parse(localStorage.getItem('career-coach:chat:jordan-ab12')!).messages[1].sources).toEqual(items);
  });

  it('warns under a reply that names something no web result backs up', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse([
      sse({ type: 'delta', text: 'Take the AWS Certified Quantum Wizard exam.' })
        + sse({ type: 'check', unverified: ['AWS Certified Quantum Wizard exam'] })
        + sse({ type: 'done', text: 'Take the AWS Certified Quantum Wizard exam.', tools: [], recorded: null }),
    ])));
    render(<CoachPanel userId="jordan-ab12" onMemorySaved={() => undefined} />);
    await user.type(screen.getByLabelText('Message the coach'), 'What next?{Enter}');

    expect(await screen.findByText(/No web result names “AWS Certified Quantum Wizard exam”/)).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('career-coach:chat:jordan-ab12')!).messages[1].unverified)
      .toEqual(['AWS Certified Quantum Wizard exam']);
  });

  it('New session empties the chat and uses a fresh session id', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse([sse({ type: 'done', text: 'Hi Jordan.', tools: [], recorded: null })])));
    render(<CoachPanel userId="jordan-ab12" onMemorySaved={() => undefined} />);
    await user.click(screen.getByRole('button', { name: 'What should I focus on this week?' }));
    expect(await screen.findByText('Hi Jordan.')).toBeInTheDocument();
    const before = savedChat().sessionId;

    await user.click(screen.getByRole('button', { name: 'New session' }));

    expect(screen.queryByText('Hi Jordan.')).not.toBeInTheDocument();
    expect(savedChat().messages).toEqual([]);
    expect(savedChat().sessionId).not.toBe(before);
  });

  it('Retry resends the failed message without adding it twice', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(streamResponse([sse({ type: 'done', text: 'Back online.', tools: [], recorded: null })]));
    vi.stubGlobal('fetch', fetchMock);
    render(<CoachPanel userId="jordan-ab12" onMemorySaved={() => undefined} />);

    await user.type(screen.getByLabelText('Message the coach'), 'Help me plan my week{Enter}');
    expect(await screen.findByText(/Could not reach the API/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Back online.')).toBeInTheDocument();
    expect(screen.getAllByText('Help me plan my week')).toHaveLength(1);
    expect(savedChat().messages.map((m) => m.text)).toEqual(['Help me plan my week', 'Back online.']);
  });
});
