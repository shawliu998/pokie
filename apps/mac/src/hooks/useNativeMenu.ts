import { useEffect, useRef } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';

export function useNativeMenu(onCommand: (command: string) => void): void {
  const callback = useRef(onCommand);
  callback.current = onCommand;
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    let unlisten: UnlistenFn | undefined;
    void listen<string>('glint-menu', (event) => callback.current(event.payload)).then((next) => {
      if (disposed) next();
      else unlisten = next;
    });
    return () => { disposed = true; unlisten?.(); };
  }, []);
}
