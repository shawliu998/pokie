import { expect, test } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

const fixtureState = process.env.POKIEQUANT_E2E_RUN_STATE ?? 'quant-completed';
const expectedStatus: Record<string, string> = {
  'quant-ready': 'Ready',
  'quant-plan-approval': 'Waiting for plan approval',
  'quant-running': 'Running experiments',
  'quant-repairing': 'Repairing',
  'quant-validating': 'Validating',
  'quant-waiting-review': 'Waiting for review',
  'quant-completed': 'Completed',
  'quant-no-viable-candidate': 'Completed',
  'quant-failed-safe': 'Failed safely',
  'quant-cancelled': 'Cancelled',
};
const fixtureStatus = expectedStatus[fixtureState] ?? 'Completed';

test('renders the server-owned Quant fixture without active Glint product copy', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Quant screenshots use the deterministic loopback fixture API.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');

  await expect(page.getByRole('complementary', { name: 'PokieQuant navigation' })).toBeVisible();
  await expect(page.getByText('Synthetic Demo Fixture').first()).toBeVisible();
  await expect(page.locator('.quant-project-header')).toContainText(fixtureStatus);
  await expect(page.getByRole('button', { name: 'Inbox' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Signals' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Decisions' })).toHaveCount(0);
  await expect(page.getByText('Start Paper Trading')).toHaveCount(0);

  if (fixtureState === 'quant-repairing') {
    await expect(page.getByText(/candidate-scoped failure/i).first()).toBeVisible();
    await expect(page.locator('.quant-project-header')).not.toContainText('Failed safely');
  }
  if (fixtureState === 'quant-no-viable-candidate') {
    await expect(page.getByText(/No candidate passed validation/).first()).toBeVisible();
    await expect(page.locator('.quant-project-header')).not.toContainText('Failed safely');
  }

  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByText('No live or historical provider retrieval')).toBeVisible();
  await expect(page.getByText('No code execution in this shell')).toBeVisible();
  await expect(page.getByText('No broker connection or order action')).toBeVisible();
});

test('ready fixture advances through an API-owned plan command and refresh', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-ready', 'Command flow starts from quant-ready.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByRole('button', { name: 'New Research' }).click();
  await page.getByRole('button', { name: 'Generate plan' }).click();
  await page.getByRole('button', { name: 'Projects' }).click();
  await expect(page.locator('.quant-project-header')).toContainText('Waiting for plan approval');
  await page.reload();
  await expect(page.locator('.quant-project-header')).toContainText('Waiting for plan approval');
});

test('captures a real workbench screenshot when explicitly enabled', async ({ page }) => {
  test.skip(process.env.POKIEQUANT_CAPTURE_SCREENSHOTS !== '1', 'Screenshot capture is an explicit reviewed workflow.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await expect(page.getByText('Synthetic Demo Fixture').first()).toBeVisible();
  await page.screenshot({
    path: `../../docs/assets/pokiequant/${fixtureState}.png`,
    fullPage: false,
    animations: 'disabled',
  });
});
