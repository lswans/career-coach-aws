import { useState, type FormEvent } from 'react';
import { setNewPassword, signIn } from '../api/auth';

// Hosted coach only. The CloudFormation stack creates one account for the email the attendee
// entered, and AWS emails them a temporary password; the first sign-in asks for a new one.
export function SignIn({ onSignedIn }: { onSignedIn: (email: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [session, setSession] = useState<string | null>(null);
  const [fresh, setFresh] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (session) {
        await setNewPassword(email.trim(), session, fresh);
        onSignedIn(email.trim());
        return;
      }
      const result = await signIn(email.trim(), password);
      if (result.kind === 'new-password') setSession(result.session);
      else onSignedIn(email.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app">
      <section className="card" aria-labelledby="signin-title">
        <h2 id="signin-title">{session ? 'Choose a new password' : 'Sign in to your coach'}</h2>
        <p className="muted">
          {session
            ? 'This is your first sign-in. Pick a password of at least 8 characters with a number, an uppercase letter and a lowercase letter.'
            : 'Use the email you entered when you deployed the stack. AWS emailed you a temporary password.'}
        </p>
        <form onSubmit={submit}>
          {!session ? (
            <>
              <div className="field">
                <label htmlFor="signin-email">Email</label>
                <input id="signin-email" type="email" value={email} autoComplete="username"
                  onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="signin-password">Password</label>
                <input id="signin-password" type="password" value={password} autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)} />
              </div>
            </>
          ) : (
            <div className="field">
              <label htmlFor="signin-new-password">New password</label>
              <input id="signin-new-password" type="password" value={fresh} autoComplete="new-password"
                onChange={(e) => setFresh(e.target.value)} />
            </div>
          )}
          {error && (
            <p className="missing" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-primary" type="submit"
            disabled={busy || (session ? fresh.length < 8 : !email.trim() || !password)}>
            {busy ? 'Signing in...' : session ? 'Set password and continue' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  );
}
