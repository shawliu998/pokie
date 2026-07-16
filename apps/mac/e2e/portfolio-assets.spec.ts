import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

const captureEnabled = process.env.GLINT_CAPTURE_PORTFOLIO === '1';
const assetDir = '../../docs/assets';

async function capture(page: Page, name: string) {
  await page.screenshot({
    path: `${assetDir}/${name}`,
    fullPage: false,
    animations: 'disabled',
  });
}

test('captures the reviewed pilot portfolio views from the external demo runtime', async ({ page }) => {
  test.skip(!captureEnabled, 'Portfolio capture is an explicit external-demo workflow.');
  test.setTimeout(120_000);

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await expect(page.getByText('Glint / Glint Demo')).toBeVisible();
  await expect(page.getByText('Imported Demo Fixture').first()).toBeVisible();
  await expect(page.getByLabel('Inbox list')).toBeVisible();
  await capture(page, 'glint-inbox.png');

  const firstSignal = page.locator('.signal-row').first();
  await firstSignal.click();
  await expect(page.getByRole('heading', { name: 'What changed' })).toBeVisible();
  await page.getByText('Detection details', { exact: true }).click();
  await page.getByLabel('Detail panel').evaluate((element) => { element.scrollTop = 0; });
  await capture(page, 'glint-signal-detail.png');

  await page.getByRole('button', { name: 'Investigations' }).click();
  await expect(page.getByLabel('Investigations list')).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Overview' })).toBeVisible();
  await capture(page, 'glint-investigation.png');

  await page.getByRole('button', { name: 'Decisions' }).click();
  await expect(page.getByLabel('Decisions list')).toBeVisible();
  await expect(page.getByText('Decision-ready').first()).toBeVisible();
  await capture(page, 'glint-decision-brief.png');

  await page.getByRole('button', { name: 'Monitoring' }).click();
  await expect(page.getByRole('heading', { name: 'Monitoring' }).last()).toBeVisible();
  await expect(page.getByText('Imported Demo Fixture').first()).toBeVisible();
  await capture(page, 'glint-monitoring.png');
});
