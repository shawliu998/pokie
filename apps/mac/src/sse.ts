import type { Authenticity } from './domain';
import { asNumber, asObject, asString, mapAuthenticity } from './mappers';
import { SessionExpiredError } from './session';

export interface RunStreamEvent {
  eventId: string;
  runId: string;
  sequence: number;
  eventType: string;
  payload: Record<string, unknown>;
  timestamp: string;
  authenticity: Authenticity;
}

export interface StreamReset { snapshotUrl: string; latestSequence: number; authenticity: Authenticity }

export interface RunStreamOptions {
  baseUrl: string;
  workspaceId: string;
  accessToken: string;
  runId: string;
  lastEventId?: string;
  signal?: AbortSignal;
  onEvent: (event: RunStreamEvent) => void;
  onReset: (reset: StreamReset) => Promise<void> | void;
}

function parseFrame(frame: string): { id?: string; event?: string; data?: string } {
  const output: { id?: string; event?: string; data?: string } = {};
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const key = colon < 0 ? line : line.slice(0, colon);
    const raw = colon < 0 ? '' : line.slice(colon + 1);
    const value = raw.startsWith(' ') ? raw.slice(1) : raw;
    if (key === 'id') output.id = value;
    if (key === 'event') output.event = value;
    if (key === 'data') output.data = output.data === undefined ? value : `${output.data}\n${value}`;
  }
  return output;
}

function parseData(frame: { id?: string; event?: string; data?: string }): RunStreamEvent | StreamReset | null {
  if (!frame.event || frame.data === undefined) return null;
  const data = asObject(JSON.parse(frame.data), `SSE ${frame.event}`);
  if (frame.event === 'stream.reset') return { snapshotUrl: asString(data.snapshot_url, 'StreamReset.snapshot_url'), latestSequence: asNumber(data.latest_sequence, 'StreamReset.latest_sequence'), authenticity: mapAuthenticity(data.data_authenticity, 'StreamReset.data_authenticity') };
  const eventType = asString(data.event_type, 'RunEvent.event_type');
  const eventId = asString(data.event_id, 'RunEvent.event_id');
  if (eventType !== frame.event || (frame.id !== undefined && frame.id !== eventId)) throw new Error('SSE frame metadata differs from the RunEvent payload.');
  return {
    eventId,
    runId: asString(data.run_id, 'RunEvent.run_id'),
    sequence: asNumber(data.sequence, 'RunEvent.sequence'),
    eventType,
    payload: asObject(data.payload, 'RunEvent.payload'),
    timestamp: asString(data.timestamp, 'RunEvent.timestamp'),
    authenticity: mapAuthenticity(data.data_authenticity, 'RunEvent.data_authenticity'),
  };
}

export async function subscribeRunEvents(options: RunStreamOptions): Promise<void> {
  const response = await fetch(`${options.baseUrl}/v1/research-runs/${options.runId}/events`, { headers: { Accept: 'text/event-stream', Authorization: `Bearer ${options.accessToken}`, 'X-Workspace-ID': options.workspaceId, ...(options.lastEventId ? { 'Last-Event-ID': options.lastEventId } : {}) }, signal: options.signal });
  if (response.status === 401) throw new SessionExpiredError();
  if (!response.ok || !response.body) throw new Error(`SSE subscription failed (${response.status}).`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = '';
  while (true) {
    const read = await reader.read();
    buffered += decoder.decode(read.value, { stream: !read.done }).replaceAll('\r\n', '\n');
    let boundary = buffered.indexOf('\n\n');
    while (boundary >= 0) {
      const parsed = parseData(parseFrame(buffered.slice(0, boundary)));
      buffered = buffered.slice(boundary + 2);
      boundary = buffered.indexOf('\n\n');
      if (!parsed) continue;
      if ('snapshotUrl' in parsed) {
        await options.onReset(parsed);
        await reader.cancel();
        return;
      } else {
        if (parsed.runId !== options.runId) throw new Error('RunEvent escaped the subscribed ResearchRun.');
        options.onEvent(parsed);
      }
    }
    if (read.done) {
      if (buffered.trim() && !buffered.trimStart().startsWith(':')) throw new Error('SSE stream ended with an incomplete frame.');
      return;
    }
  }
}
