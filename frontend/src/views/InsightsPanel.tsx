import type { Insights } from '../api/types';
import { KnowledgeGraph } from '../components/KnowledgeGraph';
import { NotesBarChart, TrendLineChart } from '../components/Charts';
import { formatShortDate } from '../lib/format';

export function InsightsPanel({ insights }: { insights: Insights }) {
  const { stats, graph, trends } = insights;

  return (
    <div>
      <section className="card">
        <h2>Insights</h2>
        <div className="stat-grid">
          <Stat label="Goal alignment" value={`${Math.round(stats.goal_alignment)}`} />
          <Stat label="Readiness" value={`${Math.round(stats.readiness_pct)}%`} />
          <Stat label="Skills" value={`${stats.skills_total}`} />
          <Stat label="Average level" value={stats.avg_level.toFixed(1)} />
          <Stat label="Notes (14 days)" value={`${trends.momentum_14d}`} />
          <Stat label="Focus area" value={stats.focus_area ?? '—'} text />
        </div>
      </section>

      <KnowledgeGraph graph={graph} />

      <section className="card">
        <h3>Trends</h3>
        <TrendLineChart snapshots={trends.snapshots} />
        {trends.alignment_delta !== null && (
          <p>
            <span className={`chip ${trends.alignment_delta >= 0 ? 'chip-ok' : 'chip-err'}`}>
              Alignment {trends.alignment_delta >= 0 ? '+' : ''}
              {trends.alignment_delta}
            </span>
          </p>
        )}

        {trends.new_skills.length > 0 && (
          <p>
            New skills:{' '}
            {trends.new_skills.map((s) => (
              <span className="chip chip-ok" key={s}>
                {s}
              </span>
            ))}
          </p>
        )}

        {trends.skill_changes.length > 0 && (
          <>
            <h4>Skill changes</h4>
            <ul>
              {trends.skill_changes.map((c) => (
                <li key={c.skill}>
                  {c.skill}: {c.from} → {c.to} ({c.delta >= 0 ? '+' : ''}
                  {c.delta})
                </li>
              ))}
            </ul>
          </>
        )}

        <h4>Notes by week</h4>
        <NotesBarChart weeks={trends.notes_by_week} />

        {trends.themes.length > 0 && (
          <p>
            Themes:{' '}
            {trends.themes.map((t) => (
              <span className="chip" key={t.skill}>
                {t.skill} ({t.count})
              </span>
            ))}
          </p>
        )}

        {trends.recent_notes.length > 0 && (
          <>
            <h4>Recent notes</h4>
            <ul>
              {trends.recent_notes.map((note, i) => (
                <li key={i}>
                  <span className="chip">{note.kind}</span> {note.text}{' '}
                  <span className="muted">
                    ({note.skill ? `${note.skill} · ` : ''}
                    {formatShortDate(note.created_at)})
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, text = false }: { label: string; value: string; text?: boolean }) {
  return (
    <div className="stat">
      <div className={text ? 'val text' : 'val'}>{value}</div>
      <div className="lbl">{label}</div>
    </div>
  );
}
