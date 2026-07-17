import { expect, test } from '@playwright/test';

declare const process: { env: Record<string, string | undefined>; cwd(): string };

const state = process.env.GLINT_E2E_AGENT_STATE;
const stateCopy = {
  'agent-ready': { status: 'Ready to start', current: 'Approved scope is ready', screenshot: 'glint-agent-ready.png' },
  'agent-running': { status: 'Running', current: 'Glint is analyzing evidence', screenshot: 'glint-agent-running.png' },
  'agent-waiting-review': { status: 'Waiting for review', current: '1 evidence proposal needs your review', screenshot: 'glint-agent-review.png' },
  'agent-completed': { status: 'Completed', current: 'This Investigation is complete', screenshot: 'glint-agent-complete.png' },
} as const;

test.describe('Agent Workspace fixture states', () => {
  test.skip(!state || !(state in stateCopy), 'Run with an explicit GLINT_E2E_AGENT_STATE fixture.');

  test('shows a truthful Agent session and captures its application state', async ({ page }) => {
    const expected = stateCopy[state as keyof typeof stateCopy];
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.goto('/');
    await page.getByRole('button', { name: 'Investigations' }).click();

    await expect(page.getByRole('heading', { level: 2, name: 'Should we prioritize permission preview for enterprise teams?' })).toBeVisible();
    await expect(page.getByText('Imported Demo Fixture', { exact: true })).toBeVisible();
    await expect(page.locator('.agent-header .status').filter({ hasText: expected.status })).toBeVisible();
    await expect(page.getByRole('heading', { name: expected.current }).first()).toBeVisible();
    await expect(page.getByText('3 approved sources', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('12 immutable content versions', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Deterministic research', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('No model egress', { exact: true })).toBeVisible();
    if (state !== 'agent-ready') await expect(page.getByText('Budget limit: $4.0000 · 15 min', { exact: true }).first()).toBeVisible();

    if (state === 'agent-ready') await expect(page.getByRole('region', { name: 'Agent action center' }).getByRole('button', { name: 'Start investigation' })).toBeEnabled();
    if (state === 'agent-running') {
      await expect(page.getByRole('button', { name: 'Cancel' })).toBeEnabled();
      await expect(page.getByRole('button', { name: 'Review evidence' })).toHaveCount(0);
    }
    if (state === 'agent-waiting-review') {
      await expect(page.getByRole('region', { name: 'Agent action center' }).getByRole('button', { name: 'Review evidence' })).toBeEnabled();
      await expect(page.getByRole('region', { name: 'Agent action center' }).locator('.status').filter({ hasText: 'Human gate' })).toBeVisible();
      await expect(page.getByText('Evidence Proposal', { exact: true }).first()).toBeVisible();
    }
    if (state === 'agent-completed') {
      await expect(page.getByRole('button', { name: 'Open Decision Brief' }).first()).toBeEnabled();
      await expect(page.getByText('Synthesis Draft', { exact: true })).toBeVisible();
      await expect(page.getByText('Decision Brief', { exact: true }).first()).toBeVisible();
    }

    await page.screenshot({ path: `${process.cwd()}/../../docs/assets/agent/${expected.screenshot}`, fullPage: false });

    await page.setViewportSize({ width: 900, height: 760 });
    await page.getByLabel('Investigations list').getByRole('button', { name: /Should we prioritize permission preview/ }).click();
    const segments = page.getByRole('navigation', { name: 'Agent workspace sections' });
    await expect(segments).toBeVisible();
    for (const label of ['Plan', 'Activity', 'Review', 'Result']) await expect(segments.getByRole('button', { name: label })).toBeVisible();
    await segments.getByRole('button', { name: 'Plan' }).click();
    await expect(page.getByRole('complementary', { name: 'Agent plan' })).toBeVisible();
    await segments.getByRole('button', { name: 'Review' }).click();
    await expect(page.getByRole('region', { name: 'Agent artifacts' })).toBeVisible();

    if (state === 'agent-ready') {
      const started = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/research-runs'));
      await page.keyboard.press('r');
      expect((await started).status()).toBe(202);
    }
  });
});
