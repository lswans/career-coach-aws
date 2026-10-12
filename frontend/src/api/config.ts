// Configuration: API base URL resolution and localStorage keys.

export const DEFAULT_API_BASE = 'http://127.0.0.1:8000';

export const LS = {
  apiBase: 'career-coach:apiBase',
  user: 'career-coach:user',
  chat: (userId: string) => `career-coach:chat:${userId}`,
} as const;

export function getApiBase(): string {
  try {
    const saved = localStorage.getItem(LS.apiBase);
    if (saved && saved.trim()) return saved.trim().replace(/\/+$/, '');
  } catch {
    // ignore storage errors
  }
  const env = import.meta.env.VITE_API_BASE_URL;
  // "same-origin": the CloudFormation stack serves this site and the API from one CloudFront URL.
  if (env && env.trim() === 'same-origin') return '';
  return (env && env.trim() ? env.trim() : DEFAULT_API_BASE).replace(/\/+$/, '');
}

export function setApiBase(url: string): void {
  localStorage.setItem(LS.apiBase, url.trim().replace(/\/+$/, ''));
}
