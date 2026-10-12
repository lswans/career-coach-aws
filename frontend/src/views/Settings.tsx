import { useState } from 'react';
import { getApiBase, setApiBase, DEFAULT_API_BASE } from '../api/config';
import { getHealth } from '../api/client';

type TestState =
  | { kind: 'idle' }
  | { kind: 'testing' }
  | { kind: 'ok'; model: string }
  | { kind: 'err'; message: string };

/** `onClose(true)` means the saved API address changed, so the app should check it again. */
export function Settings({ onClose }: { onClose: (changed: boolean) => void }) {
  const [url, setUrl] = useState(getApiBase());
  const [testState, setTestState] = useState<TestState>({ kind: 'idle' });

  function save() {
    const before = getApiBase();
    setApiBase(url || DEFAULT_API_BASE);
    onClose(getApiBase() !== before);
  }

  async function test() {
    setTestState({ kind: 'testing' });
    // The client reads the saved address, so save it briefly, then put the old one back.
    const previous = getApiBase();
    setApiBase(url || DEFAULT_API_BASE);
    try {
      const h = await getHealth();
      setTestState({ kind: 'ok', model: h.model });
    } catch (e) {
      const message =
        typeof e === 'object' && e !== null && 'message' in e
          ? String((e as { message: unknown }).message)
          : 'Could not reach the API.';
      setTestState({ kind: 'err', message });
    } finally {
      setApiBase(previous);
    }
  }

  return (
    <main className="app">
      <section className="card" aria-labelledby="settings-title">
        <div className="spread">
          <h2 id="settings-title">Settings</h2>
          <button className="btn btn-sm" onClick={() => onClose(false)}>
            Close
          </button>
        </div>
        <div className="field">
          <label htmlFor="api-base">API base URL</label>
          <input
            id="api-base"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={DEFAULT_API_BASE}
            autoFocus
          />
          <p className="counter">
            The hosted site talks to the API on your own laptop. Chrome may ask permission to
            access local network devices: click <strong>Allow</strong>.
          </p>
        </div>
        <div className="row">
          <button className="btn btn-primary" onClick={save}>
            Save
          </button>
          <button className="btn" onClick={test} disabled={testState.kind === 'testing'}>
            {testState.kind === 'testing' ? 'Testing...' : 'Test'}
          </button>
          <span role="status">
            {testState.kind === 'ok' && (
              <span className="chip chip-ok">Reached. Model: {testState.model}</span>
            )}
            {testState.kind === 'err' && <span className="chip chip-err">{testState.message}</span>}
          </span>
        </div>
      </section>
    </main>
  );
}
