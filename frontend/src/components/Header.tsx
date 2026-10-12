import { useEffect, useRef, useState } from 'react';
import { getHealth } from '../api/client';
import type { Health } from '../api/types';

type Status = 'loading' | 'ok' | 'warn' | 'err';

const POLL_MS = 20_000;

export function Header({
  onOpenSettings,
  onHealth,
  refreshKey = 0,
}: {
  onOpenSettings: () => void;
  onHealth?: (h: Health | null) => void;
  /** Change this number to re-check the API right away (for example after Settings changes). */
  refreshKey?: number;
}) {
  const [status, setStatus] = useState<Status>('loading');
  const [health, setHealth] = useState<Health | null>(null);

  // Keep the latest callback in a ref so a new function from the parent
  // does not restart the polling loop on every render.
  const onHealthRef = useRef(onHealth);
  useEffect(() => {
    onHealthRef.current = onHealth;
  }, [onHealth]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    async function poll() {
      try {
        const h = await getHealth(controller.signal);
        if (!active) return;
        setHealth(h);
        setStatus(h.model_status.model_ready ? 'ok' : 'warn');
        onHealthRef.current?.(h);
      } catch {
        if (!active) return;
        setHealth(null);
        setStatus('err');
        onHealthRef.current?.(null);
      } finally {
        if (active) timer = setTimeout(poll, POLL_MS);
      }
    }

    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [refreshKey]);

  return (
    <header className="header">
      <div className="header-inner">
        <h1 className="header-title">Career Coach</h1>
        <HealthPill status={status} health={health} />
        <button className="btn btn-sm" onClick={onOpenSettings}>
          Settings
        </button>
      </div>
    </header>
  );
}

function HealthPill({ status, health }: { status: Status; health: Health | null }) {
  if (status === 'loading') {
    return (
      <span className="pill pill-warn" role="status">
        <span className="dot" /> Checking API...
      </span>
    );
  }
  if (status === 'err') {
    return (
      <span className="pill pill-err" role="status">
        <span className="dot" /> API offline. Run: uv run python -m coach
      </span>
    );
  }
  const backend = health?.memory_backend === 'agentcore' ? 'AgentCore Memory' : 'Local memory';
  const model = health?.model ?? 'model';
  if (status === 'warn') {
    return (
      <span className="pill pill-warn" role="status">
        <span className="dot" />
        {model} · {backend} · {health?.model_status.detail ?? 'model not ready'}
      </span>
    );
  }
  return (
    <span className="pill pill-ok" role="status">
      <span className="dot" />
      {model} · {backend} · ready
    </span>
  );
}
