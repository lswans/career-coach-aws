import { describe, expect, it } from 'vitest';
import type { Graph, GraphNode } from '../api/types';
import { PROFILE_RESPONSE } from '../test/fixtures';
import { layoutGraph, shortLabel } from './layoutGraph';

const graph = PROFILE_RESPONSE.insights.graph;

describe('layoutGraph', () => {
  it('is deterministic: the same graph always gives the same picture', () => {
    expect(layoutGraph(graph, 640, 480)).toEqual(layoutGraph(graph, 640, 480));
  });

  it('puts "you" at the centre', () => {
    const you = layoutGraph(graph, 640, 480).nodes.find((n) => n.type === 'you')!;
    expect([you.x, you.y]).toEqual([320, 240]);
  });

  it('keeps every node finite and inside the viewBox', () => {
    for (const [w, h] of [[640, 480], [375, 600], [120, 90]] as const) {
      const layout = layoutGraph(graph, w, h);
      expect(layout.nodes).toHaveLength(graph.nodes.length);
      for (const n of layout.nodes) {
        expect(Number.isFinite(n.x) && Number.isFinite(n.y) && Number.isFinite(n.r)).toBe(true);
        expect(n.x).toBeGreaterThanOrEqual(0);
        expect(n.x).toBeLessThanOrEqual(w);
        expect(n.y).toBeGreaterThanOrEqual(0);
        expect(n.y).toBeLessThanOrEqual(h);
      }
    }
    // At normal size the whole circle fits, not just its centre.
    for (const n of layoutGraph(graph, 640, 480).nodes) {
      expect(n.x - n.r).toBeGreaterThanOrEqual(0);
      expect(n.x + n.r).toBeLessThanOrEqual(640);
      expect(n.y - n.r).toBeGreaterThanOrEqual(0);
      expect(n.y + n.r).toBeLessThanOrEqual(480);
    }
  });

  it('places skills on a ring further out than their category', () => {
    const layout = layoutGraph(graph, 640, 480);
    const dist = (id: string) => {
      const n = layout.nodes.find((x) => x.id === id)!;
      return Math.hypot(n.x - 320, n.y - 240);
    };
    expect(dist('skill:python')).toBeGreaterThan(dist('cat:technical'));
    expect(dist('target:aws')).toBeGreaterThan(dist('skill:python'));
  });

  it('handles an empty graph and drops edges to unknown nodes', () => {
    expect(layoutGraph({ nodes: [], edges: [] }, 640, 480)).toMatchObject({ nodes: [], edges: [] });
    const dangling: Graph = {
      nodes: [{ id: 'you', label: 'You', type: 'you' }],
      edges: [{ source: 'you', target: 'missing', type: 'gap' }],
    };
    expect(layoutGraph(dangling, 640, 480).edges).toEqual([]);
  });

  it('never stacks two labels on top of each other (graph from a real qwen3:1.7b run)', () => {
    const skill = (name: string, level: number): GraphNode => ({
      id: `skill:${name.toLowerCase().replace(/ /g, '-')}`, label: name, type: 'skill', level, relevance: 'high',
    });
    const skills = [skill('Python', 5), skill('Cloud Computing', 3), skill('Data Pipelines', 4), skill('Machine Learning', 3), skill('Cloud Deployment', 1)];
    const busy: Graph = {
      nodes: [
        { id: 'you', label: 'You', type: 'you' },
        { id: 'cat:technical', label: 'Technical', type: 'category' },
        ...skills,
        { id: 'gap:0', label: 'Cloud Deployment', type: 'gap', severity: 'low' },
        { id: 'gap:1', label: 'Technical Interviews', type: 'gap', severity: 'medium' },
        { id: 'gap:2', label: 'Cloud Experience', type: 'gap', severity: 'medium' },
        { id: 'opp:0', label: 'AWS Cloud Deployment Certification', type: 'opportunity' },
        { id: 'opp:1', label: 'Live Coding Practice', type: 'opportunity' },
        { id: 'opp:2', label: 'Cloud-Based Project', type: 'opportunity' },
        { id: 'target:technical-interviews', label: 'Technical Interviews', type: 'target' },
      ],
      edges: [
        { source: 'you', target: 'cat:technical', type: 'has' },
        ...skills.map((s) => ({ source: 'cat:technical', target: s.id, type: 'includes' as const })),
        { source: 'you', target: 'gap:0', type: 'gap' },
        { source: 'opp:1', target: 'target:technical-interviews', type: 'builds' },
      ],
    };
    // Same geometry KnowledgeGraph draws: 10px text centred 11px below the circle.
    const boxes = layoutGraph(busy, 640, 480).nodes.map((n) => {
      const w = shortLabel(n).length * 6;
      return { id: n.id, left: n.x - w / 2, right: n.x + w / 2, top: n.y + n.r + 2, bottom: n.y + n.r + 14 };
    });
    const clashes: string[] = [];
    boxes.forEach((a, i) =>
      boxes.slice(i + 1).forEach((b) => {
        if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) clashes.push(`${a.id} / ${b.id}`);
      }),
    );
    expect(clashes).toEqual([]);
    expect(Math.max(...boxes.map((b) => b.bottom))).toBeLessThanOrEqual(480); // labels stay on the canvas
  });

  it('keeps labels apart on a crowded graph (4 categories, 10 skills, 10 outer nodes)', () => {
    const cats = ['technical', 'tool', 'domain', 'soft'];
    const names = ['Python', 'Machine Learning', 'Data Pipelines', 'Docker', 'Git', 'Statistics',
      'Healthcare Analytics', 'Public Speaking', 'Mentoring', 'Technical Writing'];
    const outerLabels = ['Model deployment on AWS', 'System design interviews', 'No production ML project', 'Kubernetes',
      'MLOps', 'AWS Certified ML Engineer Associate', 'Build an end-to-end ML app', 'Join an ML reading group',
      'Two mock interviews a week', 'Open-source contribution'];
    const crowded: Graph = {
      nodes: [
        { id: 'you', label: 'You', type: 'you' },
        ...cats.map((c) => ({ id: `cat:${c}`, label: c, type: 'category' as const })),
        ...names.map((n, i) => ({ id: `skill:${i}`, label: n, type: 'skill' as const, level: 1 + (i % 5) })),
        ...outerLabels.map((l, i) => ({
          id: `${i < 3 ? 'gap' : i < 5 ? 'target' : 'opp'}:${i}`,
          label: l,
          type: (i < 3 ? 'gap' : i < 5 ? 'target' : 'opportunity') as GraphNode['type'],
        })),
      ],
      edges: names.map((_, i) => ({ source: `cat:${cats[i % 4]}`, target: `skill:${i}`, type: 'includes' as const })),
    };
    const boxes = layoutGraph(crowded, 640, 480).nodes.map((n) => {
      const w = shortLabel(n).length * 6;
      return { id: n.id, left: n.x - w / 2, right: n.x + w / 2, top: n.y + n.r + 2, bottom: n.y + n.r + 14 };
    });
    const clashes = boxes.flatMap((a, i) =>
      boxes.slice(i + 1).filter((b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom)
        .map((b) => `${a.id} / ${b.id}`),
    );
    expect(clashes).toEqual([]);
    expect(boxes.every((b) => b.left >= 0 && b.right <= 640 && b.bottom <= 480)).toBe(true);
  });

  it('cuts long labels short but keeps "you" and category names whole', () => {
    expect(shortLabel({ id: 'opp:0', label: 'AWS Cloud Deployment Certification', type: 'opportunity' })).toBe('AWS Cloud Deploym…');
    expect(shortLabel({ id: 'cat:x', label: 'A very long category name here', type: 'category' })).toBe('A very long category name here');
  });
});
