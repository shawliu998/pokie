import { expect, test } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

test('desktop resize state and explicit compact navigation remain deterministic', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Layout interaction coverage uses the deterministic fixture workspace.');
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1180, height: 760 });
  await page.goto('/');

  const group = page.getByTestId('glint-workbench');
  const sidebarSeparator = page.getByRole('separator', { name: 'Resize sidebar and list' });
  const listSeparator = page.getByRole('separator', { name: 'Resize list and detail' });
  await expect(group).toBeVisible();
  await expect(sidebarSeparator).toBeVisible();
  await expect(listSeparator).toBeVisible();

  const hideSidebar = page.getByRole('button', { name: 'Hide sidebar' });
  await hideSidebar.click();
  await expect(page.getByRole('button', { name: 'Show sidebar' })).toBeVisible();
  await page.getByRole('button', { name: 'Show sidebar' }).click();
  await expect(hideSidebar).toBeVisible();

  await listSeparator.focus();
  await listSeparator.press('ArrowRight');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('glint:workbench-layout:v1'))).not.toBeNull();
  const storedLayout = await page.evaluate(() => JSON.parse(localStorage.getItem('glint:workbench-layout:v1') ?? '{}')) as { version?: number; layout?: Record<string, number> };
  expect(storedLayout.version).toBe(1);
  expect(Object.keys(storedLayout.layout ?? {}).sort()).toEqual(['detail', 'list', 'sidebar']);

  if (await page.locator('button.signal-row').count() === 0) {
    await page.getByRole('button', { name: 'Monitoring' }).click();
    await page.getByLabel('Destination source').selectOption({ label: 'Customer feedback CSV' });
    await page.getByLabel('CSV file').setInputFiles('e2e/fixtures/feedback.csv');
    await page.getByRole('button', { name: 'Review upload scope' }).click();
    await page.getByRole('button', { name: 'Create metadata session' }).click();
    await page.getByRole('button', { name: 'Preview consent scope' }).click();
    await page.getByRole('button', { name: 'Confirm scoped upload grant' }).click();
    await expect(page.locator('.import-progress')).toContainText('scope changed');
    await page.getByRole('button', { name: 'Preview consent scope' }).click();
    await page.getByRole('button', { name: 'Confirm scoped upload grant' }).click();
    await page.getByRole('button', { name: 'Confirm upload bytes' }).click();
    await expect(page.getByText(/Finalized ImportManifest/)).toBeVisible();
    await page.getByRole('button', { name: 'Inbox' }).click();
  }

  await page.setViewportSize({ width: 900, height: 760 });
  const compact = page.locator('[data-layout="compact"]');
  await expect(compact).toBeVisible();
  await expect(sidebarSeparator).toHaveCount(0);
  await expect(page.getByLabel('Search Inbox')).toBeVisible();

  await page.locator('button.signal-row').first().click();
  const back = page.getByRole('button', { name: 'Back to list' });
  await expect(back).toBeVisible();
  await page.locator('header.toolbar').getByRole('button').last().click();
  await expect(page.getByRole('dialog', { name: 'Data status' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Data status' })).toHaveCount(0);
  await expect(back).toBeVisible();
  await page.getByRole('button', { name: 'Investigations' }).click();
  await expect(page.getByLabel('Search Investigations')).toBeVisible();
  await page.getByRole('button', { name: /^Inbox/ }).click();
  await page.locator('button.signal-row').first().click();
  await expect(back).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByLabel('Search Inbox')).toBeVisible();
  await page.getByRole('button', { name: 'Decisions' }).click();
  await expect(page.getByLabel('Search Decisions')).toBeVisible();

  await page.setViewportSize({ width: 1180, height: 760 });
  await expect(group).toBeVisible();
  await expect(sidebarSeparator).toBeVisible();
  await expect(page.getByLabel('Search Decisions')).toBeVisible();
});
