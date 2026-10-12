import { useMemo, useState } from 'react';
import type { Graph, GraphNode, GraphNodeType } from '../api/types';
import { layoutGraph, shortLabel } from '../lib/layoutGraph';

const NODE_COLOR: Record<GraphNodeType, string> = {
  you: '#1b4fd6',
  category: '#6a4bd6',
  skill: '#137a3f',
  target: '#b36b00',
  gap: '#b31a1a',
  opportunity: '#0c8599',
};

const LEGEND: { type: GraphNodeType; label: string }[] = [
  { type: 'you', label: 'You' },
  { type: 'category', label: 'Category' },
  { type: 'skill', label: 'Skill you have' },
  { type: 'target', label: 'Skill to build' },
  { type: 'opportunity', label: 'Opportunity' },
  { type: 'gap', label: 'Gap' },
];

const WIDTH = 640;
const HEIGHT = 480;

export function KnowledgeGraph({ graph }: { graph: Graph }) {
  const [asList, setAsList] = useState(false);
  const layout = useMemo(() => layoutGraph(graph, WIDTH, HEIGHT), [graph]);

  return (
    <section className="card" aria-labelledby="graph-title">
      <div className="spread">
        <h3 id="graph-title">Skill knowledge graph</h3>
        <button className="btn btn-sm" onClick={() => setAsList((v) => !v)} aria-pressed={asList}>
          {asList ? 'Show as graph' : 'Show as list'}
        </button>
      </div>

      {asList ? (
        <GraphList graph={graph} />
      ) : (
        <>
          <div className="legend" aria-hidden="true">
            {LEGEND.map((l) => (
              <span key={l.type}>
                <span className="sw" style={{ background: NODE_COLOR[l.type] }} /> {l.label}
              </span>
            ))}
          </div>
          <div className="graph-wrap">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label="Skill knowledge graph. Use the Show as list button for a text version."
            >
              {layout.edges.map((e, i) => (
                <line
                  key={i}
                  x1={e.x1}
                  y1={e.y1}
                  x2={e.x2}
                  y2={e.y2}
                  stroke="var(--border)"
                  strokeWidth={e.type === 'builds' ? 1.5 : 1}
                  strokeDasharray={e.type === 'builds' ? '4 3' : undefined}
                />
              ))}
              {layout.nodes.map((n) => (
                <g key={n.id}>
                  <circle cx={n.x} cy={n.y} r={n.r} fill={NODE_COLOR[n.type]}>
                    <title>
                      {n.label} ({n.type}
                      {typeof n.level === 'number' ? `, level ${n.level}` : ''})
                    </title>
                  </circle>
                  <text
                    x={n.x}
                    y={n.y + n.r + 11}
                    textAnchor="middle"
                    fontSize={10}
                    fill="var(--text)"
                  >
                    {shortLabel(n)}
                  </text>
                </g>
              ))}
            </svg>
          </div>
        </>
      )}
    </section>
  );
}

function GraphList({ graph }: { graph: Graph }) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const you = graph.nodes.find((n) => n.type === 'you');
  const categories = graph.nodes.filter((n) => n.type === 'category');
  const opportunities = graph.nodes.filter((n) => n.type === 'opportunity');

  function childrenOf(id: string, edgeType: string): GraphNode[] {
    return graph.edges
      .filter((e) => e.source === id && e.type === edgeType)
      .map((e) => byId.get(e.target))
      .filter((n): n is GraphNode => Boolean(n));
  }

  const gaps = you ? childrenOf(you.id, 'gap') : [];

  return (
    <ul>
      <li>
        <strong>{you?.label ?? 'You'}</strong>
        <ul>
          {categories.map((c) => (
            <li key={c.id}>
              {c.label}
              <ul>
                {childrenOf(c.id, 'includes').map((s) => (
                  <li key={s.id}>
                    {s.label}
                    {typeof s.level === 'number' ? ` (level ${s.level} of 5)` : ''}
                  </li>
                ))}
              </ul>
            </li>
          ))}
          {gaps.map((g) => (
            <li key={g.id}>Gap: {g.label}</li>
          ))}
          {opportunities.map((o) => (
            <li key={o.id}>
              Opportunity: {o.label}
              <ul>
                {childrenOf(o.id, 'builds').map((s) => (
                  <li key={s.id}>
                    Builds {s.label}
                    {s.type === 'target' ? ' (a skill you do not have yet)' : ''}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </li>
    </ul>
  );
}
