import { Fragment, type ReactNode } from 'react';

/** Only http(s) links from web results become clickable; anything else (javascript:, data:) is dropped. */
export function webUrl(url: string | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

/** A link to a web source that opens in a new tab, and says so to screen readers. */
export function SourceLink({ url, children }: { url: string | undefined; children: ReactNode }) {
  const href = webUrl(url);
  if (!href) return <>{children}</>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  );
}

/**
 * Show **bold** from the model as bold text. Small models add it even when asked not to.
 * Everything else stays plain text, and React escapes it, so model output can't inject HTML.
 */
export function richText(text: string): ReactNode {
  // split() with a capture group returns [plain, bold, plain, bold, ...]
  return text
    .split(/\*\*(.+?)\*\*/g)
    .map((part, i) => (i % 2 === 1 ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>));
}
