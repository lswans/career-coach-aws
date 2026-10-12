import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { HEALTH, jsonResponse, PROFILE_RESPONSE } from './test/fixtures';

/** Answer /api/health with HEALTH and /profile with the given status. */
function stubApi(profileStatus: 200 | 404) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/api/health')) return jsonResponse(200, HEALTH);
      if (url.endsWith('/profile')) {
        return profileStatus === 200
          ? jsonResponse(200, PROFILE_RESPONSE)
          : jsonResponse(404, { error: { code: 'PROFILE_NOT_FOUND', message: 'No profile yet. Complete setup first.' } });
      }
      return jsonResponse(404, {});
    }),
  );
}

const rememberJordan = () =>
  localStorage.setItem('career-coach:user', JSON.stringify({ userId: 'jordan-ab12', name: 'Jordan' }));

describe('App', () => {
  it('takes a new visitor from Welcome to the setup wizard', async () => {
    const user = userEvent.setup();
    stubApi(404);
    render(<App />);

    await user.type(await screen.findByLabelText('Your first name'), 'Jordan');
    await user.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByRole('heading', { name: 'Dump your docs' })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('career-coach:user')!)).toEqual({ userId: 'jordan', name: 'Jordan' });
  });

  it('opens an existing coach when the same name is typed on a new site', async () => {
    const user = userEvent.setup();
    stubApi(200); // this backend already has a profile for "jordan"; the browser storage is empty
    render(<App />);

    await user.type(await screen.findByLabelText('Your first name'), 'Jordan');
    await user.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByRole('tab', { name: 'Profile' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'CS student who ships data pipelines' })).toBeInTheDocument();
  });

  it('shows the health pill with the model and memory backend', async () => {
    stubApi(404);
    render(<App />);
    expect(await screen.findByText(/Claude Haiku 5\.5 · Local memory · ready/)).toBeInTheDocument();
  });

  it('says how to fix a model the AWS account cannot use yet', async () => {
    const detail = 'Anthropic asks for a one-time use-case form before an AWS account can use Claude Haiku 5.5.';
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      url.endsWith('/api/health')
        ? jsonResponse(200, { ...HEALTH, model_status: { reachable: true, model_ready: false, detail } })
        : jsonResponse(404, {}),
    ));
    render(<App />);
    expect(await screen.findByText(new RegExp(`Claude Haiku 5\\.5 · Local memory · ${detail.slice(0, 40)}`))).toBeInTheDocument();
  });

  it('opens a returning user on the dashboard; arrow keys move between tabs', async () => {
    const user = userEvent.setup();
    rememberJordan();
    stubApi(200);
    render(<App />);

    const profileTab = await screen.findByRole('tab', { name: 'Profile' });
    expect(profileTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'CS student who ships data pipelines' })).toBeInTheDocument();

    profileTab.focus();
    await user.keyboard('{ArrowRight}');
    const coachTab = screen.getByRole('tab', { name: 'Coach' });
    expect(coachTab).toHaveAttribute('aria-selected', 'true');
    expect(coachTab).toHaveFocus();
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'panel-coach');

    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Insights' })).toHaveFocus();
    expect(screen.getByRole('heading', { name: 'Skill knowledge graph' })).toBeInTheDocument();

    await user.keyboard('{ArrowRight}'); // wraps around
    expect(screen.getByRole('tab', { name: 'Profile' })).toHaveFocus();
  });

  it('sends a returning user without a profile to the wizard', async () => {
    rememberJordan();
    stubApi(404);
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dump your docs' })).toBeInTheDocument();
  });

  it('Update my profile reopens the wizard with the old goals filled in', async () => {
    const user = userEvent.setup();
    rememberJordan();
    stubApi(200);
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Update my profile' }));
    expect(screen.getByText(/Add your documents again/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next: goals' }));
    expect(screen.getByLabelText('Career goals')).toHaveValue(PROFILE_RESPONSE.profile.goals);
  });

  it('says the API is offline when the backend does not answer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    render(<App />);
    expect(await screen.findByText(/API offline/)).toBeInTheDocument();
  });
});
