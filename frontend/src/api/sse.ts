/**
 * Incremental Server-Sent-Events parser for the chat and profile-build POST streams.
 *
 * Events are `data: <json>` lines separated by a blank line. Chunks from the
 * network can split anywhere (mid-line, mid-event), so we buffer and only emit
 * complete events. Non-`data:` lines (comments, other fields) are ignored.
 */
export class SseParser<T extends { type: string }> {
  private buffer = '';

  /** Feed a raw chunk; returns any complete events it completed. */
  push(chunk: string): T[] {
    this.buffer += chunk;
    const events: T[] = [];

    // An event is terminated by a blank line. Normalize CRLF first.
    const normalized = this.buffer.replace(/\r\n/g, '\n');
    const parts = normalized.split('\n\n');
    // The last part may be an incomplete event: keep it buffered.
    this.buffer = parts.pop() ?? '';

    for (const part of parts) {
      const evt = this.parseEvent(part);
      if (evt) events.push(evt);
    }
    return events;
  }

  /** Flush a trailing event that was not terminated by a blank line. */
  flush(): T[] {
    const remaining = this.buffer.trim();
    this.buffer = '';
    if (!remaining) return [];
    const evt = this.parseEvent(remaining);
    return evt ? [evt] : [];
  }

  private parseEvent(block: string): T | null {
    // Join all `data:` lines in the block (SSE allows multi-line data).
    const dataLines: string[] = [];
    for (const rawLine of block.split('\n')) {
      const line = rawLine.replace(/\r$/, '');
      if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).replace(/^ /, ''));
      }
      // Ignore everything else (comments `:`, event:, id:, blank).
    }
    if (dataLines.length === 0) return null;

    const payload = dataLines.join('\n').trim();
    if (!payload) return null;

    try {
      const parsed = JSON.parse(payload) as T;
      if (parsed && typeof parsed.type === 'string') return parsed;
      return null;
    } catch {
      return null;
    }
  }
}
