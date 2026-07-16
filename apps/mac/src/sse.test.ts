import { describe, expect, it, vi } from 'vitest';
import { subscribeRunEvents } from './sse';

describe('Run SSE recovery', () => {
  it('sends Last-Event-ID and handles replay then reset', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('id: event-10\nevent: run.completed\ndata: {"data_authenticity":"generated","run_id":"run-1","event_id":"event-10","event_type":"run.completed","sequence":10,"payload":{"state":"completed"},"trace_id":"trace-1","timestamp":"2026-07-15T05:03:00Z"}\n\nevent: stream.reset\ndata: {"event_type":"stream.reset","snapshot_url":"/v1/research-runs/run-1","latest_sequence":12,"data_authenticity":"generated"}\n\n', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const received: string[] = []; const reset = vi.fn();
    await subscribeRunEvents({ baseUrl: 'http://127.0.0.1:8000', workspaceId: '00000000-0000-4000-8000-000000000001', accessToken: 'test-access-token', runId: 'run-1', lastEventId: 'event-9', onEvent: (event) => received.push(event.eventId), onReset: reset });
    expect(received).toEqual(['event-10']); expect(reset).toHaveBeenCalledWith({ snapshotUrl: '/v1/research-runs/run-1', latestSequence: 12, authenticity: 'generated' }); expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({ 'Last-Event-ID': 'event-9', Authorization: 'Bearer test-access-token' });
    vi.unstubAllGlobals();
  });
});
