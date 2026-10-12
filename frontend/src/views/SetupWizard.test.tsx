import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { jsonResponse, PROFILE_RESPONSE, sse } from '../test/fixtures';
import { SetupWizard } from './SetupWizard';

function renderWizard() {
  const onDone = vi.fn();
  const view = render(<SetupWizard userId="jordan-ab12" health={null} onDone={onDone} />);
  const fileInput = view.container.querySelector('input[type="file"]') as HTMLInputElement;
  return { onDone, fileInput };
}

const pasteAchievements = (text = 'Won 2nd place at the Fall Hackathon and made the Dean’s List.') =>
  fireEvent.change(screen.getByLabelText('Achievements'), { target: { value: text } });
const goToGoals = () => fireEvent.click(screen.getByRole('button', { name: 'Next: goals' }));
const typeGoals = (text: string) => fireEvent.change(screen.getByLabelText('Career goals'), { target: { value: text } });
const buildButton = () => screen.getByRole('button', { name: 'Build my coach' });

describe('SetupWizard gating', () => {
  it('stays disabled with goals but no documents, and says why', () => {
    renderWizard();
    goToGoals();
    typeGoals('g'.repeat(250));
    expect(buildButton()).toBeDisabled();
    expect(screen.getByText(/Add at least one file, or paste at least 50 characters/)).toBeInTheDocument();
  });

  it('stays disabled with documents but no goals', () => {
    renderWizard();
    pasteAchievements();
    goToGoals();
    expect(screen.getByText('0 / 200 characters minimum')).toBeInTheDocument();
    expect(buildButton()).toBeDisabled();
  });

  it('enables at exactly 200 trimmed goal characters, not 199', () => {
    renderWizard();
    pasteAchievements();
    goToGoals();

    typeGoals(`   ${'g'.repeat(199)}   `); // padding does not count
    expect(screen.getByText('199 / 200 characters minimum')).toBeInTheDocument();
    expect(screen.getByText('Write 1 more character of goals')).toBeInTheDocument();
    expect(buildButton()).toBeDisabled();

    typeGoals('g'.repeat(200));
    expect(screen.getByText('200 / 200 characters minimum')).toBeInTheDocument();
    expect(buildButton()).toBeEnabled();
  });

  it('does not count less than 50 pasted characters as a document', () => {
    renderWizard();
    pasteAchievements('short');
    goToGoals();
    typeGoals('g'.repeat(200));
    expect(buildButton()).toBeDisabled();
  });

  it('counts one uploaded resume as a document', async () => {
    const user = userEvent.setup();
    const { fileInput } = renderWizard();
    await user.upload(fileInput, new File(['# Resume\nPython, SQL'], 'resume.md', { type: 'text/markdown' }));
    expect(screen.getByText('resume.md')).toBeInTheDocument();
    goToGoals();
    typeGoals('g'.repeat(200));
    expect(buildButton()).toBeEnabled();
  });

  it('blocks building while an unsupported file is attached', () => {
    const { fileInput } = renderWizard();
    fireEvent.change(fileInput, { target: { files: [new File(['x'], 'selfie.png', { type: 'image/png' })] } });
    expect(screen.getByText(/Unsupported type/)).toBeInTheDocument();
    pasteAchievements();
    goToGoals();
    typeGoals('g'.repeat(200));
    expect(buildButton()).toBeDisabled();
    expect(screen.getByText(/Remove the files marked unsupported/)).toBeInTheDocument();
  });
});

/** A response whose SSE events the test sends one at a time, to check the UI between them. */
function controlledStream() {
  const encoder = new TextEncoder();
  const queue: (string | null)[] = [];
  let wake: () => void = () => undefined;
  const body = {
    getReader: () => ({
      read: async () => {
        while (queue.length === 0) await new Promise<void>((resolve) => (wake = resolve));
        const next = queue.shift()!;
        return next === null ? { done: true, value: undefined } : { done: false, value: encoder.encode(next) };
      },
      releaseLock: () => undefined,
    }),
  };
  return {
    response: { ok: true, status: 200, body } as unknown as Response,
    send: (event: object) => (queue.push(sse(event)), wake()),
    end: () => (queue.push(null), wake()),
  };
}

const row = (label: string) => screen.getByText(label).closest('li')!;

describe('SetupWizard building', () => {
  it('shows each real build step as the server reports it, then hands back the result', async () => {
    const stream = controlledStream();
    const fetchMock = vi.fn(async () => stream.response);
    vi.stubGlobal('fetch', fetchMock);
    const { onDone } = renderWizard();
    pasteAchievements();
    goToGoals();
    typeGoals('g'.repeat(200));
    fireEvent.click(buildButton());

    expect(screen.getByRole('heading', { name: 'Building your coach' })).toBeInTheDocument();
    expect(row('Read your documents')).toHaveAttribute('aria-current', 'step');
    expect(row('Analyze them with the AI model')).toHaveAttribute('data-state', 'pending');

    stream.send({ type: 'stage', stage: 'read', state: 'done', detail: '1 document · 61 characters' });
    stream.send({ type: 'stage', stage: 'model', state: 'active', detail: 'Claude Haiku 5.5 is reading them on Amazon Bedrock' });
    expect(await screen.findByText('Claude Haiku 5.5 is reading them on Amazon Bedrock')).toBeInTheDocument();
    expect(row('Read your documents')).toHaveAttribute('data-state', 'done');

    stream.send({ type: 'progress', section: 'skills', chars: 1204, skills: ['Python', 'AWS'], weaknesses: [], opportunities: [] });
    expect(await screen.findByText('Writing skills · 1,204 characters so far')).toBeInTheDocument();
    expect(screen.getByText('AWS')).toHaveClass('chip');

    stream.send({ type: 'stage', stage: 'model', state: 'done', detail: '6 skills · 3 gaps · 4 next steps' });
    stream.send({ type: 'stage', stage: 'verify', state: 'active', detail: 'Checking 1 of 2: AWS Certified Cloud Practitioner' });
    expect(await screen.findByText('Checking 1 of 2: AWS Certified Cloud Practitioner')).toBeInTheDocument();
    expect(screen.getByText('6 skills · 3 gaps · 4 next steps')).toBeInTheDocument();
    expect(screen.queryByText(/characters so far/)).not.toBeInTheDocument(); // live counter only while the model writes
    expect(screen.getByRole('status')).toHaveTextContent('Check suggested next steps on the web. Checking 1 of 2');

    stream.send({ type: 'done', ...PROFILE_RESPONSE });
    stream.end();
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith(PROFILE_RESPONSE));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('shows a server field error on the step that owns it', async () => {
    const body = { error: { code: 'VALIDATION_ERROR', message: 'Not ready', fields: { goals: 'Describe your career goals in more detail' } } };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(422, body)));
    renderWizard();
    pasteAchievements();
    goToGoals();
    typeGoals('g'.repeat(200));
    fireEvent.click(buildButton());

    expect(await screen.findByText('Describe your career goals in more detail')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Your career goals' })).toBeInTheDocument();
  });

  it('offers Retry when the model is unavailable', async () => {
    const body = { error: { code: 'MODEL_UNAVAILABLE', message: "Can't reach Ollama. Start it, then try again." } };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(503, body)));
    renderWizard();
    pasteAchievements();
    goToGoals();
    typeGoals('g'.repeat(200));
    fireEvent.click(buildButton());

    expect(await screen.findByText("Can't reach Ollama. Start it, then try again.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
