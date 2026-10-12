import { useRef, useState, type KeyboardEvent } from 'react';
import type { ProfileResponse } from '../api/types';
import type { StoredUser } from '../lib/storage';
import { CoachPanel } from './CoachPanel';
import { InsightsPanel } from './InsightsPanel';
import { ProfilePanel } from './ProfilePanel';

const TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'coach', label: 'Coach' },
  { id: 'insights', label: 'Insights' },
] as const;
type TabId = (typeof TABS)[number]['id'];

export function Dashboard({
  user,
  data,
  onUpdateProfile,
  onStartOver,
  onMemorySaved,
}: {
  user: StoredUser;
  data: ProfileResponse;
  onUpdateProfile: () => void;
  onStartOver: () => void;
  onMemorySaved: () => void;
}) {
  const [active, setActive] = useState<TabId>('profile');
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});

  // Arrow keys, Home and End move between tabs (the WAI-ARIA tabs pattern).
  function onTabKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = TABS.length - 1;
    const next =
      e.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : e.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : e.key === 'Home' ? 0
      : e.key === 'End' ? last
      : null;
    if (next === null) return;
    e.preventDefault();
    const id = TABS[next]!.id;
    setActive(id);
    tabRefs.current[id]?.focus();
  }

  return (
    <main className="app">
      <div className="spread toolbar">
        <p className="muted">
          Coaching <strong>{user.name}</strong>
        </p>
        <div className="row">
          <button className="btn btn-sm" onClick={onUpdateProfile}>
            Update my profile
          </button>
          <button className="btn btn-sm" onClick={onStartOver}>
            Start over as someone else
          </button>
        </div>
      </div>

      <div role="tablist" aria-label="Your coach" className="tabs">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[t.id] = el;
            }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={active === t.id ? 0 : -1}
            className="tab"
            onClick={() => setActive(t.id)}
            onKeyDown={(e) => onTabKeyDown(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Panels stay mounted and are only hidden, so a chat reply keeps streaming
          while you look at another tab. */}
      <div role="tabpanel" id="panel-profile" aria-labelledby="tab-profile" hidden={active !== 'profile'}>
        <ProfilePanel profile={data.profile} />
      </div>
      <div role="tabpanel" id="panel-coach" aria-labelledby="tab-coach" hidden={active !== 'coach'}>
        <CoachPanel userId={user.userId} onMemorySaved={onMemorySaved} />
      </div>
      <div role="tabpanel" id="panel-insights" aria-labelledby="tab-insights" hidden={active !== 'insights'}>
        <InsightsPanel insights={data.insights} />
      </div>
    </main>
  );
}
