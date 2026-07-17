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
  if (['quant-validating', 'quant-waiting-review', 'quant-completed', 'quant-no-viable-candidate'].includes(fixtureState)) {
    await expect(page.getByRole('heading', { name: 'Daily-bar kernel verified' })).toBeVisible();
    await expect(page.getByText('1,564 synthetic weekday bars')).toBeVisible();
  } else {
    await expect(page.getByRole('heading', { name: 'Daily-bar kernel ready' })).toBeVisible();
    await expect(page.getByText('Results remain hidden until the API advances the run.')).toBeVisible();
  }
  await expect(page.getByText('No network · no broker · no arbitrary code')).toBeVisible();
  await expect(page.locator('.quant-project-header')).toContainText(fixtureStatus);
  if (fixtureState === 'quant-no-viable-candidate') {
    await expect(page.locator('.quant-project-header')).toContainText('No candidate passed validation · run completed normally');
  }
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

test('ready fixture completes the API-owned synthetic Agent workflow', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-ready', 'Command flow starts from quant-ready.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByRole('button', { name: 'New Research' }).click();
  const goal = 'Compare a bounded SPY trend hypothesis with synthetic evidence.';
  await page.getByLabel('Research goal').fill(goal);
  await page.getByRole('button', { name: 'Generate plan' }).click();
  await expect(page.locator('.quant-project-header')).toContainText('Waiting for plan approval');
  await expect(page.locator('.quant-project-header')).toContainText(goal);
  await page.getByRole('button', { name: 'Approve Plan' }).click();
  await expect(page.getByRole('button', { name: 'Run Synthetic Agent' })).toBeVisible();
  await page.getByRole('button', { name: 'Run Synthetic Agent' }).click();
  await expect(page.locator('.quant-project-header')).toContainText('Waiting for review');
  await expect(page.getByRole('heading', { name: 'Daily-bar kernel verified' })).toBeVisible();
  await page.getByRole('button', { name: 'Complete Review' }).click();
  await expect(page.locator('.quant-project-header')).toContainText('Completed');
  await page.reload();
  await expect(page.locator('.quant-project-header')).toContainText('Completed');
  await expect(page.locator('.quant-project-header')).toContainText(goal);
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
