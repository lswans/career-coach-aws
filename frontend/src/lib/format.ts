// A bare date like "2026-10-05" means that calendar day. new Date("2026-10-05") would
// read it as UTC midnight, which shows as Oct 4 anywhere west of London.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function parse(iso: string): Date {
  const m = DATE_ONLY.exec(iso);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
}

export function formatDate(iso: string): string {
  const d = parse(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatShortDate(iso: string): string {
  const d = parse(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function trimmedLength(s: string): number {
  return s.trim().length;
}
