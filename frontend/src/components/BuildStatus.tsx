import type { BuildProgress, BuildStageId, BuildStageState } from '../api/types';

export type StageView = { state: BuildStageState; detail: string };
export type StageMap = Record<BuildStageId, StageView>;

const STAGES: { id: BuildStageId; label: string }[] = [
  { id: 'read', label: 'Read your documents' },
  { id: 'model', label: 'Analyze them with the AI model' },
  { id: 'verify', label: 'Check suggested next steps on the web' },
  { id: 'save', label: 'Save your profile' },
];

const STATE_TEXT: Record<BuildStageState, string> = {
  pending: 'not started',
  active: 'in progress',
  done: 'done',
  skipped: 'skipped',
};

const SECTION_LABEL: Record<string, string> = {
  headline: 'your summary',
  summary: 'your summary',
  target_role: 'your target role',
  goal_alignment: 'your goal-alignment score',
  skills: 'skills',
  weaknesses: 'gaps',
  opportunities: 'next steps',
};

export function initialStages(): StageMap {
  return {
    read: { state: 'active', detail: 'Sending your documents to the coach' },
    model: { state: 'pending', detail: '' },
    verify: { state: 'pending', detail: '' },
    save: { state: 'pending', detail: '' },
  };
}

/** Names the model has written so far in the list it is working on, e.g. the skills it rated. */
function liveItems(progress: BuildProgress): string[] {
  const { section } = progress;
  return section === 'skills' || section === 'weaknesses' || section === 'opportunities' ? progress[section] : [];
}

/**
 * The build checklist. Every row changes only when the backend reports a real step,
 * and the model row shows what the model has actually written so far.
 */
export function BuildStatus({ stages, progress }: { stages: StageMap; progress: BuildProgress | null }) {
  const active = [...STAGES].reverse().find((s) => stages[s.id].state === 'active');
  return (
    <>
      <ol className="build-steps" aria-label="Build progress">
        {STAGES.map(({ id, label }) => {
          const { state, detail } = stages[id];
          const live = id === 'model' && state === 'active' ? progress : null;
          const items = live ? liveItems(live).slice(-8) : [];
          return (
            <li key={id} data-state={state} aria-current={state === 'active' ? 'step' : undefined}>
              <span className="step-icon" aria-hidden="true" />
              <div>
                <div className="step-label">
                  {label}
                  <span className="visually-hidden"> ({STATE_TEXT[state]})</span>
                </div>
                {detail && <div className="step-detail">{detail}</div>}
                {live && (
                  <div className="step-detail">
                    Writing {SECTION_LABEL[live.section] ?? 'your profile'} · {live.chars.toLocaleString()} characters so far
                  </div>
                )}
                {items.length > 0 && (
                  <div className="live-items">
                    {items.map((name, i) => (
                      <span className="chip" key={`${i}-${name}`}>
                        {name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {/* Announce stage changes, not every character the model writes. */}
      <p className="visually-hidden" role="status">
        {active ? `${active.label}. ${stages[active.id].detail}` : ''}
      </p>
    </>
  );
}
