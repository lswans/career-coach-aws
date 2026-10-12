import type { NotesByWeek, Snapshot } from '../api/types';
import { formatShortDate } from '../lib/format';

// Charts are drawn at this size and shrink on narrow screens (CSS max-width: 100%).
const W = 560;
const H = 220;
const PAD = 36;

function scaleX(i: number, n: number): number {
  if (n <= 1) return PAD + (W - 2 * PAD) / 2;
  return PAD + (i / (n - 1)) * (W - 2 * PAD);
}
function scaleY(v: number, max: number): number {
  const safeMax = max <= 0 ? 1 : max;
  return H - PAD - (v / safeMax) * (H - 2 * PAD);
}

export function TrendLineChart({ snapshots }: { snapshots: Snapshot[] }) {
  if (snapshots.length <= 1) {
    return <p className="muted">Update your profile to start a trend.</p>;
  }
  const n = snapshots.length;
  const max = 100;

  function path(key: 'goal_alignment' | 'readiness_pct'): string {
    return snapshots
      .map((s, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i, n)} ${scaleY(s[key], max)}`)
      .join(' ');
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      role="img"
      aria-label={`Goal alignment and readiness across ${n} profile versions`}
    >
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" />
      <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="var(--border)" />
      <path d={path('goal_alignment')} fill="none" stroke="#1b4fd6" strokeWidth={2} />
      <path d={path('readiness_pct')} fill="none" stroke="#137a3f" strokeWidth={2} strokeDasharray="5 3" />
      {snapshots.map((s, i) => (
        <g key={s.version}>
          <circle cx={scaleX(i, n)} cy={scaleY(s.goal_alignment, max)} r={3} fill="#1b4fd6">
            <title>v{s.version}: alignment {s.goal_alignment}</title>
          </circle>
          <circle cx={scaleX(i, n)} cy={scaleY(s.readiness_pct, max)} r={3} fill="#137a3f">
            <title>v{s.version}: readiness {s.readiness_pct}%</title>
          </circle>
          <text x={scaleX(i, n)} y={H - PAD + 14} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
            v{s.version}
          </text>
        </g>
      ))}
      <text x={PAD} y={PAD - 8} fontSize={10} fill="#1b4fd6">
        ── Goal alignment
      </text>
      <text x={PAD + 120} y={PAD - 8} fontSize={10} fill="#137a3f">
        - - Readiness %
      </text>
    </svg>
  );
}

export function NotesBarChart({ weeks }: { weeks: NotesByWeek[] }) {
  if (weeks.length === 0) return <p className="muted">No notes yet.</p>;
  const max = Math.max(1, ...weeks.map((w) => w.total));
  const n = weeks.length;
  const bw = ((W - 2 * PAD) / n) * 0.6;
  const total = weeks.reduce((sum, w) => sum + w.total, 0);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      role="img"
      aria-label={`Progress notes per week for the last ${n} weeks: ${total} in total`}
    >
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" />
      {weeks.map((w, i) => {
        const x = scaleX(i, n) - bw / 2;
        const y = scaleY(w.total, max);
        return (
          <g key={w.week_start}>
            <rect x={x} y={y} width={bw} height={H - PAD - y} fill="#0c8599">
              <title>
                Week of {formatShortDate(w.week_start)}: {w.total} note{w.total === 1 ? '' : 's'}
              </title>
            </rect>
            {w.total > 0 && (
              <text x={scaleX(i, n)} y={y - 5} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--text)">
                {w.total}
              </text>
            )}
            <text x={scaleX(i, n)} y={H - PAD + 14} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
              {formatShortDate(w.week_start)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
