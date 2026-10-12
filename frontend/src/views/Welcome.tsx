import { useState, type FormEvent } from 'react';
import { makeUserId } from '../lib/userId';
import type { StoredUser } from '../lib/storage';

export function Welcome({ onReady }: { onReady: (user: StoredUser) => void }) {
  const [name, setName] = useState('');
  const trimmed = name.trim();

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!trimmed) return;
    onReady({ userId: makeUserId(trimmed), name: trimmed });
  }

  return (
    <main className="app">
      <section className="card" aria-labelledby="welcome-title">
        <h2 id="welcome-title">Welcome</h2>
        <p className="muted">
          Build a personal career coach from your own documents and goals. First, what should we
          call you?
        </p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="first-name">Your first name</label>
            <input
              id="first-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="given-name"
              placeholder="e.g. Jordan"
              aria-describedby="name-hint"
            />
            <p id="name-hint" className="counter">
              Use the same name next time, on any device or site: it's how your coach finds you
              again.
            </p>
          </div>
          <button className="btn btn-primary" type="submit" disabled={!trimmed}>
            Continue
          </button>
        </form>
      </section>
    </main>
  );
}
