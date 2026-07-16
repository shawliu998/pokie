import { describe, expect, it, vi } from 'vitest';
import { createSerialMutationQueue } from './brief-mutations';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((complete) => { resolve = complete; });
  return { promise, resolve };
}

describe('Decision Brief mutation queue', () => {
  it('runs mutations in order and keeps the UI busy until the queue drains', async () => {
    const first = deferred();
    const busyChanges: boolean[] = [];
    const order: string[] = [];
    const queue = createSerialMutationQueue((busy) => busyChanges.push(busy));

    const firstMutation = queue.run(async () => {
      order.push('save-started');
      await first.promise;
      order.push('save-finished');
    });
    const secondMutation = queue.run(async () => {
      order.push('ready-started');
    });

    await Promise.resolve();
    expect(order).toEqual(['save-started']);
    expect(busyChanges).toEqual([true]);

    first.resolve();
    await Promise.all([firstMutation, secondMutation]);

    expect(order).toEqual(['save-started', 'save-finished', 'ready-started']);
    expect(busyChanges).toEqual([true, false]);
  });

  it('continues with the next mutation after a rejected operation', async () => {
    const onBusyChange = vi.fn();
    const queue = createSerialMutationQueue(onBusyChange);
    const nextMutation = vi.fn(async () => undefined);

    const failed = queue.run(async () => { throw new Error('save failed'); });
    const next = queue.run(nextMutation);

    await expect(failed).rejects.toThrow('save failed');
    await next;

    expect(nextMutation).toHaveBeenCalledOnce();
    expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
  });
});
