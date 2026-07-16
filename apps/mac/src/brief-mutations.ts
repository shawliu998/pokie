export interface SerialMutationQueue {
  run(task: () => Promise<void>): Promise<void>;
  dispose(): void;
}

export function createSerialMutationQueue(onBusyChange: (busy: boolean) => void): SerialMutationQueue {
  let tail: Promise<void> = Promise.resolve();
  let pendingCount = 0;
  let busyListener: ((busy: boolean) => void) | undefined = onBusyChange;

  return {
    run(task) {
      pendingCount += 1;
      if (pendingCount === 1) busyListener?.(true);

      const result = tail.then(task);
      tail = result.then(
        () => undefined,
        () => undefined,
      );

      return result.finally(() => {
        pendingCount -= 1;
        if (pendingCount === 0) busyListener?.(false);
      });
    },
    dispose() {
      busyListener = undefined;
    },
  };
}
