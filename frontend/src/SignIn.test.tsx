import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { configureAuth, signIn, signOut } from './api/auth';
import { HEALTH, jsonResponse, PROFILE_RESPONSE } from './test/fixtures';

const HOSTED = { ...HEALTH, auth: { mode: 'cognito', region: 'us-east-1', client_id: 'client-123' } };
const USER_ID = 'u-6f1c2d3e-0000-4abc-8def-123456789abc';
const TOKENS = { AccessToken: 'access-1', RefreshToken: 'refresh-1', ExpiresIn: 3600 };

type Call = { url: string; init?: RequestInit };

/** A hosted backend plus the Cognito endpoint. `cognito` answers each Cognito call in turn. */
function stubHosted(cognito: Array<[number, object]>, profileStatus: 200 | 404 = 200) {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.startsWith('https://cognito-idp.')) {
      const [status, body] = cognito.shift() ?? [500, {}];
      return jsonResponse(status, body);
    }
    if (url.endsWith('/api/health')) return jsonResponse(200, HOSTED);
    const headers = new Headers(init?.headers);
    if (headers.get('X-Coach-Auth') !== 'Bearer access-1') {
      return jsonResponse(401, { error: { code: 'UNAUTHORIZED', message: 'Sign in to use your coach.' } });
    }
    if (url.endsWith('/api/me')) return jsonResponse(200, { user_id: USER_ID });
    if (url.endsWith('/profile')) {
      return profileStatus === 200
        ? jsonResponse(200, PROFILE_RESPONSE)
        : jsonResponse(404, { error: { code: 'PROFILE_NOT_FOUND', message: 'No profile yet.' } });
    }
    return jsonResponse(404, {});
  }));
  return calls;
}

describe('hosted coach sign-in', () => {
  beforeEach(() => {
    sessionStorage.clear();
    configureAuth(null);
  });
  it('signs in for the first time, sets a new password and opens the setup wizard', async () => {
    const user = userEvent.setup();
    const calls = stubHosted([[200, { ChallengeName: 'NEW_PASSWORD_REQUIRED', Session: 'sess-1' }],
                              [200, { AuthenticationResult: TOKENS }]], 404);
    render(<App />);

    await user.type(await screen.findByLabelText('Email'), 'jordan@example.com');
    await user.type(screen.getByLabelText('Password'), 'Temp#Pass1');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    await user.type(await screen.findByLabelText('New password'), 'MyNewPass1');
    await user.click(screen.getByRole('button', { name: 'Set password and continue' }));

    expect(await screen.findByRole('heading', { name: 'Dump your docs' })).toBeInTheDocument();
    const cognito = calls.filter((c) => c.url.startsWith('https://cognito-idp.us-east-1'));
    expect(JSON.parse(String(cognito[0]!.init!.body))).toMatchObject({
      ClientId: 'client-123', AuthFlow: 'USER_PASSWORD_AUTH',
      AuthParameters: { USERNAME: 'jordan@example.com', PASSWORD: 'Temp#Pass1' },
    });
    expect(JSON.parse(String(cognito[1]!.init!.body))).toMatchObject({
      ChallengeName: 'NEW_PASSWORD_REQUIRED', Session: 'sess-1',
      ChallengeResponses: { USERNAME: 'jordan@example.com', NEW_PASSWORD: 'MyNewPass1' },
    });
    expect(JSON.parse(localStorage.getItem('career-coach:user')!)).toEqual({ userId: USER_ID, name: 'jordan@example.com' });
  });

  it('a returning user whose sign-in lapsed sees the sign-in screen, not an error', async () => {
    localStorage.setItem('career-coach:user', JSON.stringify({ userId: USER_ID, name: 'jordan@example.com' }));
    stubHosted([]);
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Sign in to your coach' })).toBeInTheDocument();
    expect(localStorage.getItem('career-coach:user')).toBeNull();
  });

  it('shows a plain message for a wrong password', async () => {
    const user = userEvent.setup();
    stubHosted([[400, { __type: 'NotAuthorizedException', message: 'Incorrect username or password.' }]]);
    render(<App />);
    await user.type(await screen.findByLabelText('Email'), 'jordan@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/don.t match/);
  });

  it('sends the token on API calls after sign-in', async () => {
    const calls = stubHosted([[200, { AuthenticationResult: TOKENS }]]);
    configureAuth({ region: 'us-east-1', clientId: 'client-123' });
    expect(await signIn('jordan@example.com', 'Pass1word')).toEqual({ kind: 'signed-in' });
    const { getProfile } = await import('./api/client');
    await getProfile(USER_ID);
    const profileCall = calls.find((c) => c.url.endsWith('/profile'))!;
    expect(new Headers(profileCall.init?.headers).get('X-Coach-Auth')).toBe('Bearer access-1');
    signOut();
    configureAuth(null);
  });
});
