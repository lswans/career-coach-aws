// Sign-in for the hosted coach (the CloudFormation stack). On a laptop there is no sign-in and
// none of this runs. Talks to the Cognito user pool's public API directly with fetch, using the
// app client's USER_PASSWORD_AUTH flow, so no AWS SDK is needed in the browser.

export type AuthConfig = { region: string; clientId: string };

type Tokens = { access: string; refresh?: string; expiresAt: number; email: string };

export type SignInResult =
  | { kind: 'signed-in' }
  | { kind: 'new-password'; session: string } // first sign-in with the emailed temporary password

const KEY = 'career-coach:tokens';
let config: AuthConfig | null = null;

export function configureAuth(next: AuthConfig | null): void {
  config = next;
}

export function authEnabled(): boolean {
  return config !== null;
}

function load(): Tokens | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

function store(tokens: Tokens): void {
  sessionStorage.setItem(KEY, JSON.stringify(tokens));
}

export function signOut(): void {
  sessionStorage.removeItem(KEY);
}

export function signedInEmail(): string | null {
  return load()?.email ?? null;
}

type CognitoReply = {
  AuthenticationResult?: { AccessToken: string; RefreshToken?: string; ExpiresIn: number };
  ChallengeName?: string;
  Session?: string;
  __type?: string;
  message?: string;
};

async function call(target: 'InitiateAuth' | 'RespondToAuthChallenge', body: object): Promise<CognitoReply> {
  if (!config) throw new Error('Sign-in is not set up on this coach.');
  const res = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify({ ClientId: config.clientId, ...body }),
  });
  const data = (await res.json()) as CognitoReply;
  if (!res.ok) throw new Error(friendly(data));
  return data;
}

/** Cognito error types to sentences an attendee can act on. */
function friendly(data: CognitoReply): string {
  const type = (data.__type ?? '').split('#').pop();
  if (type === 'NotAuthorizedException') return 'That email and password don\u2019t match. Check the email AWS sent you.';
  if (type === 'UserNotFoundException') return 'No account with that email on this coach.';
  if (type === 'InvalidPasswordException') return data.message ?? 'That password doesn\u2019t meet the rules.';
  if (type === 'PasswordResetRequiredException') return 'Your password needs a reset. Ask the presenter for help.';
  if (type === 'TooManyRequestsException') return 'Too many tries. Wait a minute and try again.';
  return data.message ?? 'Sign-in failed. Try again.';
}

function save(email: string, result: NonNullable<CognitoReply['AuthenticationResult']>, refresh?: string): void {
  store({
    access: result.AccessToken,
    refresh: result.RefreshToken ?? refresh,
    expiresAt: Date.now() + result.ExpiresIn * 1000,
    email,
  });
}

export async function signIn(email: string, password: string): Promise<SignInResult> {
  const data = await call('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  if (data.ChallengeName === 'NEW_PASSWORD_REQUIRED' && data.Session) {
    return { kind: 'new-password', session: data.Session };
  }
  if (!data.AuthenticationResult) throw new Error('Sign-in needs a step this coach does not support.');
  save(email, data.AuthenticationResult);
  return { kind: 'signed-in' };
}

export async function setNewPassword(email: string, session: string, password: string): Promise<void> {
  const data = await call('RespondToAuthChallenge', {
    ChallengeName: 'NEW_PASSWORD_REQUIRED',
    Session: session,
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: password },
  });
  if (!data.AuthenticationResult) throw new Error('Could not set the new password. Try again.');
  save(email, data.AuthenticationResult);
}

/** A valid access token, refreshed when it is within a minute of expiring; null when signed out. */
export async function accessToken(): Promise<string | null> {
  const tokens = load();
  if (!tokens) return null;
  if (tokens.expiresAt - Date.now() > 60_000) return tokens.access;
  if (!tokens.refresh) return null;
  try {
    const data = await call('InitiateAuth', {
      AuthFlow: 'REFRESH_TOKEN_AUTH',
      AuthParameters: { REFRESH_TOKEN: tokens.refresh },
    });
    if (!data.AuthenticationResult) return null;
    save(tokens.email, data.AuthenticationResult, tokens.refresh);
    return data.AuthenticationResult.AccessToken;
  } catch {
    signOut();
    return null;
  }
}

/** Headers for an API call: the token in X-Coach-Auth, which CloudFront passes to the coach. */
export async function authHeaders(): Promise<Record<string, string>> {
  if (!authEnabled()) return {};
  const token = await accessToken();
  return token ? { 'X-Coach-Auth': `Bearer ${token}` } : {};
}
