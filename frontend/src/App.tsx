import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { configureAuth, signOut } from './api/auth';
import { getInsights, getMe, getProfile, isNormalizedError } from './api/client';
import type { Health, ProfileResponse } from './api/types';
import { Header } from './components/Header';
import { clearUser, loadUser, saveUser, type StoredUser } from './lib/storage';
import { Dashboard } from './views/Dashboard';
import { Settings } from './views/Settings';
import { SetupWizard } from './views/SetupWizard';
import { SignIn } from './views/SignIn';
import { Welcome } from './views/Welcome';

// The app is a small state machine. Each view is one screen.
type View =
  | { name: 'welcome' }
  | { name: 'loading' }
  | { name: 'error'; message: string }
  | { name: 'setup'; updating: boolean }
  | { name: 'dashboard' };

export function App() {
  const [user, setUser] = useState<StoredUser | null>(loadUser);
  const [view, setView] = useState<View>(() => (loadUser() ? { name: 'loading' } : { name: 'welcome' }));
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  // The first health answer (or failure) says whether this coach has sign-in, so wait for it.
  const [healthSeen, setHealthSeen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [healthKey, setHealthKey] = useState(0);
  const hosted = health?.auth?.mode === 'cognito';

  const onHealth = useCallback((h: Health | null) => {
    if (h?.auth?.mode === 'cognito' && h.auth.region && h.auth.client_id) {
      configureAuth({ region: h.auth.region, clientId: h.auth.client_id });
    }
    setHealth(h);
    setHealthSeen(true);
  }, []);

  // A returning user: load their latest profile. Found -> dashboard, 404 -> setup wizard.
  useEffect(() => {
    if (!user || view.name !== 'loading' || !healthSeen) return;
    const controller = new AbortController();
    getProfile(user.userId, controller.signal)
      .then((res) => {
        setData(res);
        setView({ name: 'dashboard' });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        if (isNormalizedError(e) && e.status === 401) {
          // Hosted coach and the sign-in has lapsed (or this is a new tab): sign in again.
          signOut();
          clearUser();
          setUser(null);
          setView({ name: 'welcome' });
        } else if (isNormalizedError(e) && e.status === 404) setView({ name: 'setup', updating: false });
        else setView({ name: 'error', message: isNormalizedError(e) ? e.message : 'Could not load your profile.' });
      });
    return () => controller.abort();
  }, [user, view.name, healthSeen]);

  async function signedIn(email: string) {
    try {
      const me = await getMe();
      const u = { userId: me.user_id, name: email };
      saveUser(u);
      setUser(u);
      setView({ name: 'loading' });
    } catch (e) {
      setView({ name: 'error', message: isNormalizedError(e) ? e.message : 'Could not open your coach.' });
    }
  }

  // After the coach saves a progress note, fetch fresh insights so the trends update. The answer is
  // kept only if it describes the profile on screen: a refresh that finished first already brought
  // newer insights, and these must not overwrite them.
  const refreshInsights = useCallback(() => {
    if (!user) return;
    getInsights(user.userId)
      .then((insights) =>
        setData((d) => (d && insights.trends.snapshots.at(-1)?.version === d.profile.version ? { ...d, insights } : d)),
      )
      .catch(() => undefined); // the next profile load will catch up
  }, [user]);

  // The coach rebuilt the profile: replace everything the dashboard shows with the new version.
  const profileUpdated = useCallback((res: ProfileResponse) => {
    setData((d) => (d && d.profile.version > res.profile.version ? d : res));
  }, []);

  function startOver() {
    signOut();
    clearUser();
    setUser(null);
    setData(null);
    setView({ name: 'welcome' });
  }

  function closeSettings(changed: boolean) {
    setShowSettings(false);
    if (!changed) return;
    setHealthKey((k) => k + 1); // re-check the new API address now
    if (user && view.name === 'error') setView({ name: 'loading' });
  }

  let content: ReactNode = null;
  if (view.name === 'welcome' && !healthSeen) {
    content = (
      <main className="app">
        <p className="muted" role="status">
          Connecting to your coach...
        </p>
      </main>
    );
  } else if (view.name === 'welcome' && hosted) {
    content = <SignIn onSignedIn={(email) => void signedIn(email)} />;
  } else if (view.name === 'welcome') {
    content = (
      <Welcome
        onReady={(u) => {
          saveUser(u);
          setUser(u);
          setView({ name: 'loading' }); // the same name may already have a coach on this backend
        }}
      />
    );
  } else if (view.name === 'loading') {
    content = (
      <main className="app">
        <p className="muted" role="status">
          Loading your coach...
        </p>
      </main>
    );
  } else if (view.name === 'error') {
    content = (
      <main className="app">
        <section className="card" role="alert">
          <h2>Can't load your coach</h2>
          <p className="missing">{view.message}</p>
          <div className="row">
            <button className="btn btn-primary" onClick={() => setView({ name: 'loading' })}>
              Try again
            </button>
            <button className="btn" onClick={startOver}>
              Start over as someone else
            </button>
          </div>
        </section>
      </main>
    );
  } else if (view.name === 'setup' && user) {
    content = (
      <SetupWizard
        key={`setup-${data?.profile.version ?? 0}`}
        userId={user.userId}
        health={health}
        initialGoals={view.updating ? data?.profile.goals : undefined}
        onDone={(res) => {
          setData(res);
          setView({ name: 'dashboard' });
        }}
        onCancel={view.updating ? () => setView({ name: 'dashboard' }) : undefined}
      />
    );
  } else if (view.name === 'dashboard' && user && data) {
    content = (
      <Dashboard
        user={user}
        data={data}
        onUpdateProfile={() => setView({ name: 'setup', updating: true })}
        onStartOver={startOver}
        onMemorySaved={refreshInsights}
        onProfileUpdated={profileUpdated}
      />
    );
  }

  return (
    <>
      <Header onOpenSettings={() => setShowSettings(true)} onHealth={onHealth} refreshKey={healthKey} />
      {/* Settings opens on top; the current screen stays mounted underneath. */}
      {showSettings && <Settings onClose={closeSettings} />}
      <div hidden={showSettings}>{content}</div>
    </>
  );
}
