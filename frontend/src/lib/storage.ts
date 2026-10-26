import { LS } from '../api/config';
import type { WebSource } from '../api/types';

export type StoredUser = { userId: string; name: string };

export type ChatRole = 'user' | 'coach';
// What happened to the profile during a turn. Only 'updated' may say the profile changed.
export type ProfileStatus =
  | { state: 'updated'; version: number }
  | { state: 'failed'; message: string; retryable: boolean };
export type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
  requestId?: string; // user messages: sent with the request and reused on retry, so the server dedupes
  // inline annotations shown with the message
  memoryNote?: string;
  tools?: string[];
  sources?: WebSource[];
  unverified?: string[]; // offering names in the reply that no web result backs up
  profileStatus?: ProfileStatus;
};
export type StoredChat = { sessionId: string; messages: ChatMessage[] };

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function loadUser(): StoredUser | null {
  const u = readJson<StoredUser>(LS.user);
  if (u && typeof u.userId === 'string' && typeof u.name === 'string') return u;
  return null;
}

export function saveUser(user: StoredUser): void {
  localStorage.setItem(LS.user, JSON.stringify(user));
}

export function clearUser(): void {
  localStorage.removeItem(LS.user);
}

export function loadChat(userId: string): StoredChat | null {
  return readJson<StoredChat>(LS.chat(userId));
}

export function saveChat(userId: string, chat: StoredChat): void {
  localStorage.setItem(LS.chat(userId), JSON.stringify(chat));
}

export function newSessionId(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `s-${rand}`;
}

export function randomMsgId(): string {
  return `m-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

/** An id for one chat request (matches the API's request_id pattern). */
export function newRequestId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return `r-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}
