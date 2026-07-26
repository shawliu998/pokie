import { expect, test, type Page } from './fixture-test';

declare const process: { env: Record<string, string | undefined> };

const captureEnabled = process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1';
const asset = (name: string) => `../../docs/assets/pokiequant/${name}`;

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

async function capture(page: Page, name: string) {
  if (!captureEnabled) return;
  await page.screenshot({ path: asset(name), fullPage: false, animations: 'disabled' });
}

test.describe.configure({ timeout: 120_000 });

test('P1-C golden visual proof: deterministic BTCUSDT 4h data to approved plan, evidence, and historical reopen', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'P1-C is a deterministic public market-v2 fixture proof, never a live-provider claim.');
  test.slow();

  const question = 'Assess interpretable BTCUSDT 4h strategies with drawdown control before retaining a final choice.';
  const noUnexpectedBrowserErrors: string[] = [];
  page.on('pageerror', (error) => noUnexpectedBrowserErrors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') noUnexpectedBrowserErrors.push(message.text()); });

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  const importer = page.getByRole('tabpanel', { name: 'Binance Spot' });
  await importer.getByLabel('Binance Spot interval').selectOption('4h');
  await importer.getByLabel('Binance Spot bar limit').fill('4386');
  const datasetRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/datasets/v2/fetch-binance') && request.method() === 'POST');
  await importer.getByRole('button', { name: 'Fetch and validate' }).click();
  expect((await datasetRequest).postDataJSON()).toMatchObject({ name: 'BTCUSDT Binance Spot 4 hour', symbol: 'BTCUSDT', interval: '4h', limit: 4386 });

  const catalog = page.getByRole('table', { name: 'Available research datasets' });
  const datasetRow = catalog.getByRole('row', { name: /BTCUSDT Binance Spot 4 hour/ });
  await expect(datasetRow).toContainText('4h');
  await expect(datasetRow).toContainText('Verified');
  await datasetRow.getByRole('button', { name: 'Preview' }).click();
  const preview = page.locator('.quant-dataset-preview');
  await expect(preview.getByRole('heading', { name: 'BTCUSDT · 4h', level: 2 })).toBeVisible();
  await expect(preview).toContainText('Coverage');
  await expect(preview).toContainText('Bars');
  await expect(preview).toContainText('4,386');
  await expect(preview).toContainText('Verified');
  await expect(preview).toContainText('Research ready');
  await expect(preview).toContainText('Binance Spot deterministic API fixture');
  await expect(preview.getByRole('img', { name: 'BTCUSDT 4h price and volume chart' })).toBeVisible();
  await expect(preview.getByRole('button', { name: 'Use for research' })).toBeVisible();
  await noHorizontalOverflow(page);
  await capture(page, 'p1c-01-data-1440x960.png');

  await preview.getByRole('button', { name: 'Use for research' }).click();
  await expect(page.getByRole('heading', { name: 'New research' })).toBeVisible();
  await expect(page.getByLabel('Research dataset')).toHaveValue('66666666-6666-4666-8666-666666666604');
  await expect(page.getByText('2,190 periods/year', { exact: true })).toBeVisible();
  await page.getByLabel('Research start UTC').fill('2024-03-01T00:00');
  await page.getByRole('group', { name: 'Research mode' }).getByRole('button', { name: /Plan first/i }).click();
  await page.getByLabel('Research goal').fill(question);
  const createRun = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate plan' }).click();
  const created = await createRun;
  expect(created.ok()).toBe(true);
  expect(created.request().postDataJSON()).toMatchObject({
    dataset_id: '66666666-6666-4666-8666-666666666604',
    mode: 'plan',
    research_start_utc: '2024-03-01T00:00:00Z',
    research_end_utc: '2025-12-31T20:00:00+00:00',
  });
  const planSurface = page.locator('.pq-overview-main').getByLabel('Research plan awaiting approval');
  await expect(planSurface.getByText(question, { exact: true })).toBeVisible();
  await expect(planSurface).toContainText('Plan for approval');
  await expect(planSurface).toContainText('Moving-average trend');
  await expect(planSurface).toContainText('Price breakout');
  await expect(planSurface).toContainText('Drawdown control');
  await expect(planSurface).toContainText('Backtest all approved candidates and retain one final training comparison.');
  await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).not.toContainText('Plan for approval');
  const approvePlan = page.getByRole('button', { name: 'Approve & run' });
  await expect(approvePlan).toBeVisible();
  await noHorizontalOverflow(page);
  await capture(page, 'p1c-02-plan-approval-1440x960.png');

  const approveResponse = page.waitForResponse((response) => /\/v1\/quant\/market-runs\/[^/]+\/approve-plan$/.test(response.url()) && response.request().method() === 'POST');
  await approvePlan.click();
  expect((await approveResponse).ok()).toBe(true);
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  const runContext = page.locator('[aria-label="Run context"]');
  await expect(runContext).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Candidate experiments' })).toBeVisible();
  await expect(page.locator('.quant-run-monitor h3')).not.toHaveText('Research concluded');
  const decisionPath = page.locator('[aria-labelledby="pq-agent-decision-chain-heading"]');
  await expect(decisionPath.locator(':scope > div > section > span')).toHaveText(['Observation', 'Why Qurio changed', 'Next action']);
  await expect(decisionPath).toContainText('Initial hypothesis B · SMA 50/200');
  await expect(decisionPath).toContainText('SMA 20/100 completed training');
  await expect(decisionPath).toContainText('SMA 50/200');
  await noHorizontalOverflow(page);
  await capture(page, 'p1c-03-live-ab-1440x960.png');

  await expect.poll(async () => page.locator('.quant-run-monitor h3').textContent(), { timeout: 12_000 }).toContain('Research concluded');
  const ledger = page.locator('.pq-agent-decision-chain.is-completed');
  await expect(ledger).toContainText('Observation → Why Qurio changed → Next action');
  await expect(ledger).toContainText('Widen the breakout window after the initial training comparison.');
  await expect(ledger).toContainText(/Final training choice[\s\S]*SMA 50\/200[\s\S]*Approved comparison objective/);
  await noHorizontalOverflow(page);
  await capture(page, 'p1c-04-observation-to-c-1440x960.png');

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const analysis = page.locator('.pq-strategy-analysis');
  await expect(analysis.getByRole('heading', { name: 'SMA 50/200', exact: true })).toBeVisible();
  await expect(analysis.getByRole('img', { name: 'SMA 50/200 equity compared with benchmark' })).toBeVisible();
  await expect(analysis.getByLabel('Performance inspection')).toContainText('Difference');
  await expect(analysis.locator('.pq-strategy-chart figcaption time').first()).toHaveAttribute('datetime', '2024-03-01T00:00:00+00:00');
  await analysis.getByRole('tab', { name: 'Drawdown', exact: true }).click();
  await expect(analysis.getByRole('img', { name: 'SMA 50/200 drawdown compared with benchmark' })).toBeVisible();
  await analysis.getByRole('tab', { name: 'Trades', exact: true }).click();
  const retainedTrades = analysis.getByRole('table', { name: 'SMA 50/200 trades' });
  await expect(retainedTrades).toBeVisible();
  await expect(retainedTrades.locator('tbody tr')).not.toHaveCount(0);
  await expect(retainedTrades.getByText('2 bars · 8h').first()).toBeVisible();
  await noHorizontalOverflow(page);

  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  const terminal = page.locator('.quant-terminal-decision');
  await expect(terminal).toContainText('Qurio decision');
  await expect(terminal).toContainText('Final choice');
  await expect(terminal).toContainText('Training selection');
  await expect(terminal).toContainText('Sealed holdout');
  await expect(terminal).toContainText('SMA 50/200');
  await expect(terminal).toContainText('Failed');
  await expect(terminal).toContainText('Proposed change');
  await expect(terminal).toContainText('Evidence basis');
  await expect(terminal).toContainText('Success / stop condition');
  await terminal.getByRole('button', { name: 'Export evidence' }).click();
  const exportDialog = page.locator('.quant-report-export');
  await expect(exportDialog).toBeVisible();
  await expect(exportDialog.getByRole('heading', { name: 'Strategy Report preview' })).toBeVisible();
  await exportDialog.getByLabel('Export format').selectOption('strategy_evidence_bundle_json');
  await expect(exportDialog.getByRole('heading', { name: 'Strategy Evidence Bundle preview' })).toBeVisible();
  const json = exportDialog.getByLabel('Rendered Strategy Evidence Bundle JSON');
  await expect(json).toContainText('"selected_result"');
  await expect(json).toContainText('"selected_candidate_id": "candidate-b"');
  await expect(exportDialog.getByRole('button', { name: 'Download .json' })).toBeEnabled();
  await noHorizontalOverflow(page);
  await capture(page, 'p1c-05-report-json-1440x960.png');

  await page.setViewportSize({ width: 1024, height: 960 });
  await noHorizontalOverflow(page);
  await expect(exportDialog.getByRole('button', { name: 'Close' })).toBeEnabled();
  await expect(exportDialog.getByRole('button', { name: 'Download .json' })).toBeEnabled();
  await capture(page, 'p1c-05-report-json-1024x960.png');
  await page.setViewportSize({ width: 1440, height: 960 });
  await exportDialog.getByRole('button', { name: 'Close' }).click();

  const childQuestion = 'Refine the retained BTCUSDT 4h final choice with one bounded drawdown change.';
  const refinementReason = 'Retain the authoritative SMA 50/200 final choice and test one bounded drawdown refinement.';
  await terminal.getByRole('button', { name: 'Refine version' }).click();
  await expect(page.getByRole('heading', { name: 'Refine research' })).toBeVisible();
  await expect(page.getByLabel('Research dataset')).toBeDisabled();
  await page.getByLabel('Research goal').fill(childQuestion);
  await page.getByLabel('Refinement reason').fill(refinementReason);
  const createChild = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate next plan' }).click();
  const child = await createChild;
  expect(child.ok()).toBe(true);
  expect(child.request().postDataJSON()).toMatchObject({
    parent_run_id: '77777777-7777-4777-8777-777777777704',
    seed_candidate_id: 'candidate-b',
    refinement_reason: refinementReason,
  });
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  const runRow = history.getByRole('row').filter({ hasText: question }).filter({ hasText: 'Root version' });
  await expect(runRow).toContainText('BTCUSDT · 4h');
  await runRow.getByRole('button', { name: 'Open run' }).click();
  await expect(page.getByRole('heading', { name: 'BTCUSDT 4h Research' })).toBeVisible();
  await expect(page.getByText('Historical run', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve & run' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open decision', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Decision', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.quant-terminal-decision')).toContainText('SMA 50/200');
  await expect(page.locator('.quant-terminal-decision')).toContainText('Failed');
  await noHorizontalOverflow(page);
  await capture(page, 'p1c-06-history-reopen-1440x960.png');

  expect(noUnexpectedBrowserErrors).toEqual([]);
});
