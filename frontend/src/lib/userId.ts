// User ids must match ^[a-z0-9][a-z0-9-]{1,62}$ (2-63 characters), the server's rule.

export const USER_ID_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;

/**
 * Slugify a display name into the id-safe body: lowercase, strip accents, keep
 * only [a-z0-9-], collapse and trim hyphens. May be empty for exotic input.
 */
export function slugName(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '') // strip combining diacritics
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** A short, stable base-36 hash (FNV-1a), so names with no Latin letters still get their own id. */
function shortHash(text: string): string {
  let hash = 0x811c9dc5;
  for (const ch of text) {
    hash ^= ch.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36).padStart(4, '0').slice(-4);
}

/**
 * Turn a first name into the coach's user id. The same name always gives the same id,
 * so typing your name again (on the hosted site, or after clearing the browser) finds
 * your coach. Each attendee runs their own backend, so ids only need to be unique on
 * one laptop.
 */
export function makeUserId(name: string): string {
  const base = slugName(name).slice(0, 63).replace(/-+$/g, '');
  if (base.length >= 2) return base;
  return `${base || 'user'}-${shortHash(name.trim().toLowerCase())}`;
}
