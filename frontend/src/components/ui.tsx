import type { Rating } from '../api/types';

export function LevelDots({ level }: { level: number }) {
  const lvl = Math.max(0, Math.min(5, Math.round(level)));
  return (
    <span className="dots" role="img" aria-label={`Level ${lvl} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`d${i <= lvl ? ' on' : ''}`} aria-hidden="true" />
      ))}
    </span>
  );
}

export function Meter({
  value,
  label,
  max = 100,
}: {
  value: number;
  label: string;
  max?: number;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      role="meter"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
      title={`${label}: ${Math.round(value)} / ${max}`}
    >
      <div className="meter">
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="counter">
        {label}: {Math.round(value)} / {max}
      </div>
    </div>
  );
}

const RATING_CLASS: Record<Rating, string> = {
  high: 'chip-ok',
  medium: 'chip-warn',
  low: 'chip',
};

export function RatingChip({ rating }: { rating: Rating }) {
  return <span className={`chip ${RATING_CLASS[rating]}`}>{rating}</span>;
}

export function SeverityChip({ severity }: { severity: Rating }) {
  // higher severity = more alarming colour
  const cls = severity === 'high' ? 'chip-err' : severity === 'medium' ? 'chip-warn' : 'chip';
  return <span className={`chip ${cls}`}>{severity} severity</span>;
}
