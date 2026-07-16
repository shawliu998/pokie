import { defineConfig, devices } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

const fixtureApiUrl = 'http://127.0.0.1:4174';
const requestedMode = process.env.GLINT_E2E_API_MODE;
if (!requestedMode || !['fixture', 'external', '1'].includes(requestedMode)) throw new Error('GLINT_E2E_API_MODE is required and must be "fixture" or "external" (legacy verify value "1" means external).');
const useFixture = requestedMode === 'fixture';
const apiUrl = useFixture ? fixtureApiUrl : process.env.GLINT_E2E_API_URL ?? process.env.VITE_GLINT_API_URL;
const accessToken = useFixture ? process.env.GLINT_E2E_ACCESS_TOKEN ?? 'fixture-access-token' : process.env.GLINT_E2E_ACCESS_TOKEN ?? process.env.VITE_GLINT_ACCESS_TOKEN;
const workspaceId = useFixture ? process.env.GLINT_E2E_WORKSPACE_ID ?? '00000000-0000-4000-8000-000000000001' : process.env.GLINT_E2E_WORKSPACE_ID ?? process.env.VITE_GLINT_WORKSPACE_ID;
const principalId = useFixture ? process.env.GLINT_E2E_PRINCIPAL_ID ?? '00000000-0000-4000-8000-000000000002' : process.env.GLINT_E2E_PRINCIPAL_ID ?? process.env.VITE_GLINT_PRINCIPAL_ID;
if (!apiUrl || !accessToken?.trim() || !workspaceId) throw new Error('External API E2E requires GLINT_E2E_API_URL/WORKSPACE_ID/ACCESS_TOKEN or the matching VITE_GLINT_* values; fixture fallback is forbidden.');
const appUrl = useFixture ? 'http://127.0.0.1:5173' : 'http://localhost:3000';

const appServer = {
  command: useFixture ? 'pnpm dev --host 127.0.0.1 --port 5173' : 'pnpm dev --host localhost --port 3000',
  url: appUrl,
  reuseExistingServer: false,
  env: { ...process.env, VITE_GLINT_DATA_MODE: 'api', VITE_GLINT_API_URL: apiUrl, VITE_GLINT_WORKSPACE_ID: workspaceId, VITE_GLINT_PRINCIPAL_ID: principalId ?? '', VITE_GLINT_ACCESS_TOKEN: accessToken },
};

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  metadata: { apiMode: useFixture ? 'fixture' : 'external', apiUrl },
  use: { ...devices['Desktop Chrome'], baseURL: appUrl },
  webServer: useFixture ? [
    { command: 'node e2e/api-fixture.mjs', url: `${fixtureApiUrl}/healthz`, reuseExistingServer: false, env: { ...process.env, GLINT_FIXTURE_ACCESS_TOKEN: accessToken } },
    appServer,
  ] : appServer,
});
