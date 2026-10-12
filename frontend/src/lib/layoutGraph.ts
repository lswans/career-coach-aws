import type { Graph, GraphNode } from '../api/types';

export type LaidOutNode = GraphNode & {
  x: number;
  y: number;
  r: number;
};

export type LaidOutEdge = {
  source: string;
  target: string;
  type: 'has' | 'includes' | 'gap' | 'builds';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type GraphLayout = {
  width: number;
  height: number;
  nodes: LaidOutNode[];
  edges: LaidOutEdge[];
};

type Point = { x: number; y: number };
type Box = { left: number; right: number; top: number; bottom: number };

// Each ring is an ellipse: a fraction of the usable half-width and half-height.
// Ellipses use the wide canvas, because labels are wide.
const RING = { category: 0.34, skill: 0.64, skillInner: 0.52, outer: 1, outerInner: 0.84 } as const;
// Space kept free at the edges for a centred label and the text under a node.
const EDGE_X = 56;
const EDGE_Y = 28;
// Label geometry, matching KnowledgeGraph: 10px text drawn just under the circle.
const CHAR_W = 6;
const LABEL_TOP = 2;
const LABEL_H = 12;
const TURNS = 72; // rotations of the outer ring to try

export const MAX_LABEL = 18;

/** The text drawn under a node: long names are cut short (the full name is in its tooltip). */
export function shortLabel(node: GraphNode): string {
  if (node.type === 'you' || node.type === 'category' || node.label.length <= MAX_LABEL) return node.label;
  return `${node.label.slice(0, MAX_LABEL - 1)}…`;
}

function radiusFor(node: GraphNode): number {
  if (node.type === 'you') return 22;
  if (node.type === 'category') return 14;
  if (node.type === 'skill') {
    const level = typeof node.level === 'number' ? node.level : 1;
    return 7 + (Math.max(1, Math.min(5, level)) - 1) * 2; // level 1..5 -> radius 7..15
  }
  return 11; // target / opportunity / gap
}

/** The circle and the label of a node drawn at `p`, as rectangles. */
function boxesOf(node: GraphNode, p: Point): [Box, Box] {
  const r = radiusFor(node);
  const w = shortLabel(node).length * CHAR_W;
  return [
    { left: p.x - r, right: p.x + r, top: p.y - r, bottom: p.y + r },
    { left: p.x - w / 2, right: p.x + w / 2, top: p.y + r + LABEL_TOP, bottom: p.y + r + LABEL_TOP + LABEL_H },
  ];
}

function overlap(a: Box, b: Box): number {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 0 && h > 0 ? w * h : 0;
}

/**
 * Deterministic radial layout. Pure: the same graph always gives the same picture.
 * `you` sits in the centre, categories on an inner ring, skills on a middle ring next to
 * their category, and targets, opportunities and gaps on the outer ring. Rings are placed
 * one at a time; for each we try a few arrangements and keep the one whose circles and
 * labels overlap what is already drawn the least. Every coordinate is finite and inside
 * the [0,width] x [0,height] box.
 */
export function layoutGraph(graph: Graph, width: number, height: number): GraphLayout {
  const cx = width / 2;
  const cy = height / 2;
  const rx = Math.max(0, width / 2 - EDGE_X);
  const ry = Math.max(0, height / 2 - EDGE_Y);
  const point = (angle: number, ring: number): Point => ({
    x: cx + Math.cos(angle) * rx * ring,
    y: cy + Math.sin(angle) * ry * ring,
  });

  const pos = new Map<string, Point>();
  const drawn: Box[] = []; // circles and labels placed so far

  function put(node: GraphNode, p: Point) {
    pos.set(node.id, p);
    drawn.push(...boxesOf(node, p));
  }

  /** Try each arrangement of `group` and keep the first one with the least overlap. */
  function putBest(group: GraphNode[], arrangements: ((i: number) => Point)[]) {
    if (group.length === 0) return;
    let best: Point[] = [];
    let bestScore = Number.POSITIVE_INFINITY;
    for (const at of arrangements) {
      const points = group.map((_, i) => at(i));
      const boxes = group.map((n, i) => boxesOf(n, points[i]!));
      let score = 0;
      boxes.forEach((mine, i) => {
        for (const box of mine) {
          for (const other of drawn) score += overlap(box, other);
          for (let j = i + 1; j < boxes.length; j++) for (const theirs of boxes[j]!) score += overlap(box, theirs);
        }
      });
      if (score < bestScore) {
        bestScore = score;
        best = points;
        if (score === 0) break;
      }
    }
    group.forEach((n, i) => put(n, best[i]!));
  }

  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const categories = graph.nodes.filter((n) => n.type === 'category');
  const outer = graph.nodes
    .filter((n) => n.type === 'target' || n.type === 'opportunity' || n.type === 'gap')
    .sort((a, b) => a.id.localeCompare(b.id));

  // 1. You in the centre, categories evenly spaced from the top.
  for (const n of graph.nodes) if (n.type === 'you') put(n, { x: cx, y: cy });
  const catCount = Math.max(1, categories.length);
  const catAngle = new Map<string, number>();
  categories.forEach((c, i) => {
    const a = -Math.PI / 2 + (i / catCount) * Math.PI * 2;
    catAngle.set(c.id, a);
    put(c, point(a, RING.category));
  });

  // 2. Skills fan out around their category's direction, from the "includes" edges.
  const skillCategory = new Map<string, string>();
  for (const e of graph.edges) {
    if (e.type === 'includes' && byId.get(e.source)?.type === 'category' && byId.get(e.target)?.type === 'skill') {
      skillCategory.set(e.target, e.source);
    }
  }
  const skillsByCat = new Map<string, GraphNode[]>();
  for (const s of graph.nodes.filter((n) => n.type === 'skill')) {
    const cat = skillCategory.get(s.id) ?? '__none__';
    skillsByCat.set(cat, [...(skillsByCat.get(cat) ?? []), s]);
  }
  const wedge = (Math.PI * 2) / catCount;
  for (const [cat, group] of skillsByCat) {
    group.sort((a, b) => a.id.localeCompare(b.id));
    const base = catAngle.get(cat) ?? -Math.PI / 2;
    const angle = (i: number) => base + (group.length === 1 ? 0 : (i / (group.length - 1) - 0.5) * wedge * 0.8);
    putBest(group, [
      (i) => point(angle(i), RING.skill),
      (i) => point(angle(i), i % 2 ? RING.skillInner : RING.skill), // every other skill a little closer in
    ]);
  }

  // 3. Targets, opportunities and gaps round the outside, evenly spaced. Try small turns of
  //    the whole ring, then the same with every other node pulled in a little.
  const step = (Math.PI * 2) / Math.max(1, outer.length);
  const arrangements: ((i: number) => Point)[] = [];
  for (const staggered of [false, true]) {
    for (let k = 0; k < TURNS; k++) {
      const turn = (k / TURNS) * step;
      arrangements.push((i) => point(-Math.PI / 2 + i * step + turn, staggered && i % 2 ? RING.outerInner : RING.outer));
    }
  }
  putBest(outer, arrangements);

  // Anything left over (there should be nothing) goes in the centre so output stays finite.
  const laidNodes: LaidOutNode[] = graph.nodes.map((n) => {
    const p = pos.get(n.id) ?? { x: cx, y: cy };
    return { ...n, x: clamp(p.x, 0, width), y: clamp(p.y, 0, height), r: radiusFor(n) };
  });

  const nodePos = new Map(laidNodes.map((n) => [n.id, n]));
  const laidEdges: LaidOutEdge[] = graph.edges
    .map((e) => {
      const a = nodePos.get(e.source);
      const b = nodePos.get(e.target);
      if (!a || !b) return null;
      return { source: e.source, target: e.target, type: e.type, x1: a.x, y1: a.y, x2: b.x, y2: b.y };
    })
    .filter((e): e is LaidOutEdge => e !== null);

  return { width, height, nodes: laidNodes, edges: laidEdges };
}

function clamp(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return (lo + hi) / 2;
  return Math.max(lo, Math.min(hi, v));
}
