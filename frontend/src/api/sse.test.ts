import { describe, expect, it } from 'vitest';
import { sse } from '../test/fixtures';
import { SseParser } from './sse';

const delta = { type: 'delta', text: 'Hello world' };
const done = { type: 'done', text: 'Hello world', tools: [], recorded: null };

describe('SseParser', () => {
  it('waits for the rest of an event that was split across chunks', () => {
    const parser = new SseParser();
    const raw = sse(delta);
    expect(parser.push(raw.slice(0, 15))).toEqual([]);
    expect(parser.push(raw.slice(15))).toEqual([delta]);
  });

  it('gives the same events wherever the network splits the stream', () => {
    const raw = sse(delta) + sse(done);
    for (let cut = 1; cut < raw.length; cut++) {
      const parser = new SseParser();
      const events = [...parser.push(raw.slice(0, cut)), ...parser.push(raw.slice(cut)), ...parser.flush()];
      expect(events).toEqual([delta, done]);
    }
  });

  it('returns several events from one chunk, in order', () => {
    const tool = { type: 'tool', name: 'get_profile_section' };
    expect(new SseParser().push(sse(tool) + sse(delta) + sse(done))).toEqual([tool, delta, done]);
  });

  it('ignores comments, other fields and lines that are not JSON', () => {
    const chunk = ': keep-alive\n\nevent: ping\nid: 7\n\ndata: not json\n\n' + sse(delta);
    expect(new SseParser().push(chunk)).toEqual([delta]);
  });

  it('accepts Windows line endings', () => {
    expect(new SseParser().push(`data: ${JSON.stringify(delta)}\r\n\r\n`)).toEqual([delta]);
  });

  it('flush returns a last event that had no blank line after it', () => {
    const parser = new SseParser();
    expect(parser.push(`data: ${JSON.stringify(done)}`)).toEqual([]);
    expect(parser.flush()).toEqual([done]);
    expect(parser.flush()).toEqual([]);
  });
});
