import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { streamChat, isNormalizedError } from '../api/client';
import type { WebSource } from '../api/types';
import { richText, SourceLink } from '../lib/richText';
import {
  loadChat,
  saveChat,
  newSessionId,
  randomMsgId,
  type ChatMessage,
} from '../lib/storage';

/** Web results the coach was given, numbered to match its [1]-style citations. */
function Sources({ items }: { items: WebSource[] }) {
  if (items.length === 0) return null;
  return (
    <div className="sources">
      <span className="muted">Web sources:</span>
      <ol>
        {items.map((s) => (
          <li key={s.url}>
            <SourceLink url={s.url}>{s.title}</SourceLink>
          </li>
        ))}
      </ol>
    </div>
  );
}

const SUGGESTIONS = [
  'What should I focus on this week?',
  "I just finished a project I'm proud of",
  'Help me prepare for technical interviews',
];

export function CoachPanel({
  userId,
  onMemorySaved,
}: {
  userId: string;
  onMemorySaved: () => void;
}) {
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [liveText, setLiveText] = useState('');
  const [liveSources, setLiveSources] = useState<WebSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Restore this user's last chat session, or start one.
  useEffect(() => {
    const stored = loadChat(userId);
    if (stored) {
      setSessionId(stored.sessionId);
      setMessages(stored.messages);
    } else {
      const sid = newSessionId();
      setSessionId(sid);
      setMessages([]);
      saveChat(userId, { sessionId: sid, messages: [] });
    }
  }, [userId]);

  function persist(sid: string, msgs: ChatMessage[]) {
    saveChat(userId, { sessionId: sid, messages: msgs });
  }

  function newSession() {
    const sid = newSessionId();
    setSessionId(sid);
    setMessages([]);
    setLiveText('');
    setLiveSources([]);
    setError(null);
    persist(sid, []);
  }

  /** Send `text`. `history` is the transcript to append to (a retry passes it without the failed message). */
  async function send(text: string, history: ChatMessage[] = messages) {
    const message = text.trim();
    if (!message || streaming || !sessionId) return;
    setError(null);

    const userMsg: ChatMessage = { id: randomMsgId(), role: 'user', text: message };
    const base = [...history, userMsg];
    setMessages(base);
    persist(sessionId, base);
    setInput('');
    setStreaming(true);
    setLiveText('');

    const controller = new AbortController();
    abortRef.current = controller;

    let acc = '';
    let memoryNote: string | undefined;
    let sources: WebSource[] = [];
    let unverified: string[] = [];
    const tools: string[] = [];
    let finalText = '';

    try {
      await streamChat(
        userId,
        { message, session_id: sessionId },
        (evt) => {
          switch (evt.type) {
            case 'memory':
              memoryNote = evt.note.text;
              onMemorySaved();
              break;
            case 'sources':
              sources = evt.items;
              setLiveSources(evt.items);
              break;
            case 'check':
              unverified = evt.unverified;
              break;
            case 'delta':
              acc += evt.text;
              setLiveText(acc);
              break;
            case 'tool':
              if (!tools.includes(evt.name)) tools.push(evt.name);
              break;
            case 'done':
              finalText = evt.text;
              if (evt.recorded && !memoryNote) {
                memoryNote = evt.recorded.text;
                onMemorySaved();
              }
              break;
            case 'error':
              setError(evt.message);
              break;
          }
        },
        controller.signal,
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(isNormalizedError(e) ? e.message : 'The chat request failed.');
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }

    const replyText = finalText || acc;
    if (replyText || memoryNote) {
      const coachMsg: ChatMessage = {
        id: randomMsgId(),
        role: 'coach',
        text: replyText,
        ...(memoryNote ? { memoryNote } : {}),
        ...(tools.length ? { tools } : {}),
        ...(sources.length ? { sources } : {}),
        ...(unverified.length ? { unverified } : {}),
      };
      const withReply = [...base, coachMsg];
      setMessages(withReply);
      persist(sessionId, withReply);
    }
    setLiveText('');
    setLiveSources([]);
  }

  const last = messages[messages.length - 1];
  const canRetry = Boolean(error && !streaming && last?.role === 'user');

  function retry() {
    if (!last || last.role !== 'user') return;
    void send(last.text, messages.slice(0, -1));
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  return (
    <div className="card">
      <div className="spread">
        <h2>Coach</h2>
        <button className="btn btn-sm" onClick={newSession} disabled={streaming}>
          New session
        </button>
      </div>
      <p className="muted">
        New session clears this chat. Long-term memory carries over.
      </p>

      {messages.length === 0 && !streaming && (
        <div className="suggestions" aria-label="Suggested messages">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => void send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="transcript">
        {messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}`}>
            <span className="visually-hidden">{m.role === 'user' ? 'You said: ' : 'Coach said: '}</span>
            {m.role === 'coach' ? richText(m.text) : m.text}
            {m.unverified && m.unverified.length > 0 && (
              <div className="check">
                <span className="chip chip-err">Couldn’t verify</span>{' '}
                <span className="muted">
                  No web result names {m.unverified.map((n) => `“${n}”`).join(', ')}. Check it exists before you act on it.
                </span>
              </div>
            )}
            {m.sources && <Sources items={m.sources} />}
            {m.memoryNote && (
              <div className="chip chip-ok">Saved to your progress log: {m.memoryNote}</div>
            )}
            {m.tools && m.tools.length > 0 && <div className="chip">Looked up your profile</div>}
          </div>
        ))}
        {streaming && (
          <div className="bubble coach" aria-live="polite">
            {liveText ? richText(liveText) : 'Thinking...'}
            <Sources items={liveSources} />
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="row">
          <p className="missing">{error}</p>
          {canRetry && (
            <button className="btn btn-sm" onClick={retry}>
              Retry
            </button>
          )}
        </div>
      )}

      <div className="chat-input">
        <label htmlFor="chat-box" className="visually-hidden">
          Message the coach
        </label>
        <textarea
          id="chat-box"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Enter sends · Shift+Enter for a new line"
          disabled={streaming}
        />
        <button
          className="btn btn-primary"
          onClick={() => void send(input)}
          disabled={streaming || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
