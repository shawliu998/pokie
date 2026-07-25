import { expect, test as base } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

export { expect };
export type { Page } from '@playwright/test';

export const test = base.extend<{ fixtureLifecycleReset: void }>({
  fixtureLifecycleReset: [async ({ request }, use, testInfo) => {
    if (process.env.GLINT_E2E_API_MODE === 'fixture') {
      const port = process.env.GLINT_FIXTURE_PORT ?? '4174';
      const accessToken = process.env.GLINT_E2E_ACCESS_TOKEN ?? 'fixture-access-token';
      const workspaceId = process.env.GLINT_E2E_WORKSPACE_ID ?? '00000000-0000-4000-8000-000000000001';
      const response = await request.post(`http://127.0.0.1:${port}/v1/fixture-reset`, {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'X-Workspace-ID': workspaceId,
          'Idempotency-Key': `fixture-reset-${testInfo.testId}`,
        },
      });
      if (!response.ok()) throw new Error(`Fixture lifecycle reset failed with HTTP ${response.status()}.`);
    }
    await use();
  }, { auto: true }],
});
