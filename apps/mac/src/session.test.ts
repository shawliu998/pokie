import { describe, expect, it, vi } from 'vitest';
import { clearAccessToken, resolveAccessToken, storeAccessToken, type NativeSessionBoundary, type SessionEnvironment } from './session';

const boundary = (tauri: boolean, implementation: (command: string, args?: { accessToken: string }) => Promise<unknown>) => ({
  isTauri: () => tauri,
  invoke: vi.fn(implementation) as NativeSessionBoundary['invoke'],
});

describe('secure session boundary', () => {
  it('always reads Tauri sessions from Keychain and never falls back to VITE credentials', async () => {
    let browserCredentialReads = 0;
    const environment: SessionEnvironment = {
      dev: true,
      get browserAccessToken() {
        browserCredentialReads += 1;
        return 'compiled-secret-must-not-win';
      },
    };
    const native = boundary(true, async () => 'keychain-token');
    await expect(resolveAccessToken(native, environment)).resolves.toBe('keychain-token');
    expect(native.invoke).toHaveBeenCalledOnce();
    expect(native.invoke).toHaveBeenCalledWith('get_access_token');
    expect(browserCredentialReads).toBe(0);

    const missingKeychain = boundary(true, async () => null);
    await expect(resolveAccessToken(missingKeychain, environment)).rejects.toMatchObject({ kind: 'missing' });
    expect(missingKeychain.invoke).toHaveBeenCalledOnce();
    expect(missingKeychain.invoke).toHaveBeenCalledWith('get_access_token');
    expect(browserCredentialReads).toBe(0);
  });

  it('allows VITE access tokens only in browser development and E2E processes', async () => {
    const browser = boundary(false, async () => { throw new Error('native invoke must not run'); });
    await expect(resolveAccessToken(browser, { dev: true, browserAccessToken: 'browser-e2e-token' })).resolves.toBe('browser-e2e-token');
    await expect(resolveAccessToken(browser, { dev: false, browserAccessToken: 'must-not-compile' })).rejects.toMatchObject({ kind: 'unavailable' });
    expect(browser.invoke).not.toHaveBeenCalled();
  });

  it('stores and clears only through the three-command native boundary', async () => {
    const native = boundary(true, async () => undefined);
    await storeAccessToken('  opaque-token  ', native);
    await clearAccessToken(native);
    expect(native.invoke).toHaveBeenNthCalledWith(1, 'store_access_token', { accessToken: 'opaque-token' });
    expect(native.invoke).toHaveBeenNthCalledWith(2, 'clear_access_token');
    expect(localStorage.length).toBe(0);
  });

  it('rejects empty, control-character, and oversized tokens before native IPC', async () => {
    const native = boundary(true, async () => undefined);
    await expect(storeAccessToken('line\nbreak', native)).rejects.toMatchObject({ kind: 'unavailable' });
    await expect(storeAccessToken(' ', native)).rejects.toMatchObject({ kind: 'missing' });
    expect(native.invoke).not.toHaveBeenCalled();
  });
});
