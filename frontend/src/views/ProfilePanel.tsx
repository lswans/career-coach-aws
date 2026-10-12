import type { CareerProfile, Opportunity, Timeframe } from '../api/types';
import { LevelDots, Meter, RatingChip, SeverityChip } from '../components/ui';
import { formatDate } from '../lib/format';
import { SourceLink } from '../lib/richText';

const TIMEFRAME_ORDER: Timeframe[] = ['this week', 'this month', 'this quarter', 'this year'];

/** What the web check found for one next step. General advice and older profiles show nothing. */
function CheckNote({ o }: { o: Opportunity }) {
  switch (o.verification) {
    case 'verified':
      return (
        <div className="check">
          <span className="chip chip-ok">Verified online</span>{' '}
          <SourceLink url={o.source_url}>{o.source_title}</SourceLink>
        </div>
      );
    case 'corrected':
      return (
        <div className="check">
          <span className="chip chip-warn">Corrected</span>{' '}
          <span className="muted">
            The model suggested “{o.original_title}”, which no search result names. Closest real match:
          </span>{' '}
          <SourceLink url={o.source_url}>{o.source_title}</SourceLink>
        </div>
      );
    case 'unverified':
      return (
        <div className="check">
          <span className="chip chip-err">Couldn’t verify</span>{' '}
          <span className="muted">No search result names this. Check that it exists before you act on it.</span>
        </div>
      );
    case 'unchecked':
      return (
        <div className="check">
          <span className="chip">Not checked</span>{' '}
          <span className="muted">Web search was off, unreachable or returned nothing when this profile was built.</span>
        </div>
      );
    default:
      return null;
  }
}

export function ProfilePanel({ profile }: { profile: CareerProfile }) {
  return (
    <div>
      <section className="card">
        <h2>{profile.headline}</h2>
        <p className="muted">Target role: {profile.target_role}</p>
        <p>{profile.summary}</p>
        <Meter value={profile.goal_alignment} label="Goal alignment" />
      </section>

      <section className="card" aria-labelledby="skills-title">
        <h3 id="skills-title">Skills</h3>
        <div className="table-wrap">
          {/* Explicit roles keep this a table for screen readers when phones restyle it as cards. */}
          <table className="stack-table" role="table">
            <thead role="rowgroup">
              <tr role="row">
                <th scope="col" role="columnheader">Skill</th>
                <th scope="col" role="columnheader">Category</th>
                <th scope="col" role="columnheader">Level</th>
                <th scope="col" role="columnheader">Relevance to your goals</th>
                <th scope="col" role="columnheader">Evidence</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {profile.skills.map((s) => (
                <tr key={s.name} role="row">
                  <td role="cell" data-label="Skill">
                    {s.name}
                  </td>
                  <td role="cell" data-label="Category">
                    {s.category}
                  </td>
                  <td role="cell" data-label="Level">
                    <LevelDots level={s.level} />
                  </td>
                  <td role="cell" data-label="Relevance">
                    <RatingChip rating={s.relevance} />
                  </td>
                  <td role="cell" data-label="Evidence">
                    <ul className="tight">
                      {s.evidence.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" aria-labelledby="gaps-title">
        <h3 id="gaps-title">Weaknesses</h3>
        {profile.weaknesses.length === 0 && <p className="muted">None identified.</p>}
        <ul>
          {profile.weaknesses.map((w) => (
            <li key={w.area}>
              <strong>{w.area}</strong> <SeverityChip severity={w.severity} />
              <div className="muted">{w.why_it_matters}</div>
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="opps-title">
        <h3 id="opps-title">Opportunities</h3>
        {TIMEFRAME_ORDER.map((tf) => {
          const items = profile.opportunities.filter((o) => o.timeframe === tf);
          if (items.length === 0) return null;
          return (
            <div key={tf}>
              <h4 className="timeframe">{tf}</h4>
              <ul>
                {items.map((o) => (
                  <li key={o.title}>
                    <strong>{o.title}:</strong> {o.action}
                    <CheckNote o={o} />
                    <div>
                      {o.related_skills.map((rs) => (
                        <span className="chip" key={rs}>
                          {rs}
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </section>

      <section className="card" aria-labelledby="sources-title">
        <h3 id="sources-title">Sources</h3>
        <ul>
          {profile.sources.map((src, i) => (
            <li key={`${src.name}-${i}`}>
              {src.name}{' '}
              <span className="muted">
                ({src.kind}, {src.chars.toLocaleString()} characters)
              </span>
              {src.truncated && <span className="chip chip-warn">trimmed</span>}
            </li>
          ))}
        </ul>
      </section>

      <p className="muted">
        Version {profile.version} · created {formatDate(profile.created_at)} · model {profile.model}
      </p>
    </div>
  );
}
