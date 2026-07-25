import { expect, test, type Page } from './fixture-test';

declare const process: { env: Record<string, string | undefined> };

const liveUrl = process.env.POKIEQUANT_LIVE_UI_URL ?? 'http://127.0.0.1:3000';
const captureEnabled = process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1';
const asset = (name: string) => `../../docs/assets/pokiequant/${name}`;
const question = [
  'Research simple, interpretable long-or-cash BTCUSD 4h trend and breakout',
  'strategies. Compare risk-adjusted return and drawdown, make one',
  'training-evidence-driven adjustment, then stop with an honest conclusion.',
].join(' ');

const candidateA = 'sma_crossover_20_100';
const candidateB = 'breakout_20';
const candidateBId = 'a7783d43-5789-539f-ad8a-6cea88b8efc6';
const candidateC = 'sma_crossover_50_200';
const candidateCId = '60035abb-8c9f-54d4-b789-f46a13938d39';
const runId = '6ad1c324-b6c5-55af-aa51-411d676b15d8';

async function capture(page: Page, name: string) {
  if (!captureEnabled) return;
  await page.screenshot({
    path: asset(name),
    fullPage: false,
    animations: 'disabled',
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

test.describe.configure({ timeout: 120_000 });

test('V1 live connector evidence: retained Kraken 183209 branch to report and history', async ({
  page,
}) => {
  test.skip(
    process.env.POKIEQUANT_V1_LIVE_PROOF !== '1',
    'V1 requires the retained live Kraken/DeepSeek session.',
  );

  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(liveUrl);
  await expect(page.getByRole('heading', { name: 'BTCUSD Research' })).toBeVisible();

  await page
    .getByTestId('quant-sidebar')
    .getByRole('button', { name: 'Data', exact: true })
    .click();
  const catalog = page.getByRole('table', { name: 'Available research datasets' });
  const datasetRow = catalog.getByRole('row').filter({ hasText: 'BTCUSD Kraken Spot 4 hour' });
  await expect(datasetRow).toContainText('Kraken Spot public OHLC');
  await expect(datasetRow).toContainText('548');
  await expect(datasetRow).toContainText('Verified');
  await datasetRow.getByRole('button', { name: 'Preview' }).click();
  const preview = page.locator('.quant-dataset-preview');
  await expect(preview.getByRole('heading', { name: 'BTCUSD · 4h' })).toBeVisible();
  await expect(preview).toContainText('Kraken Spot public OHLC');
  await expect(preview).toContainText('240 of 548 stored bars shown');
  await expect(preview.getByRole('img', { name: 'BTCUSD 4h price and volume chart' })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, 'v1-final-183209-01-data-1440x960.png');

  await page
    .getByTestId('quant-sidebar')
    .getByRole('button', { name: 'Workspace', exact: true })
    .click();
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  const ledger = page.locator('.pq-candidate-comparison.is-full');
  await expect(ledger).toContainText('Decision ledger');
  await expect(ledger).toContainText('A/B → Observation → Candidate C → Final choice');
  await expect(ledger).toContainText(candidateA);
  await expect(ledger).toContainText(candidateB);
  await expect(ledger).toContainText(candidateC);
  await expect(ledger).toContainText('Final choice');
  await expect(ledger).toContainText('Agent request correction');
  await expect(ledger).toContainText('Refine parameters');
  await expect(ledger).toContainText('Switch approved family');
  await expect(ledger).toContainText('changed only the action');
  await expect(page.locator('.quant-run-monitor-meta')).toContainText('Strategy revisions');
  await ledger.getByRole('button', { name: candidateB }).click();
  await expectNoHorizontalOverflow(page);
  await capture(page, 'v1-final-183209-02-ledger-repair-1440x960.png');

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const analysis = page.locator('.pq-strategy-analysis');
  await expect(analysis).toBeVisible();
  await expect(analysis.getByRole('heading', { name: candidateB })).toBeVisible();
  await expect(
    analysis.getByRole('group', { name: /Inspect .* equity performance/ }),
  ).toBeVisible();
  await expect(
    analysis.getByRole('img', { name: /equity compared with benchmark/ }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, 'v1-final-183209-03-analysis-selection-1440x960.png');

  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'BTCUSD evidence' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Strategy vs benchmark' })).toBeVisible();
  await expect(page.locator('.quant-report>header')).not.toContainText('Relationship unavailable');
  const terminal = page.locator('.quant-terminal-decision');
  await expect(terminal).toContainText('Final choice');
  await expect(terminal).toContainText(candidateB);
  await expect(terminal).toContainText(/minimum trade evidence/i);
  await expect(terminal).toContainText('Retained robustness decision');
  await expect(terminal).toContainText('Sealed holdout');
  await expect(terminal).toContainText('Failed');
  await expect(terminal).toContainText('Refine the final choice');
  await expect(terminal).toContainText('Proposed change');
  await expect(terminal).toContainText('Evidence basis / Why');
  await expect(terminal).toContainText('Success / stop condition');
  await expect(terminal.getByRole('button', { name: 'Review & refine research' })).toBeVisible();
  await expect(page.locator('.quant-report-validation-summary')).toContainText('Holdout annual return');
  await expectNoHorizontalOverflow(page);
  await capture(page, 'v1-final-183209-04-holdout-revise-1440x960.png');

  await terminal.getByRole('button', { name: 'Export final evidence' }).click();
  const exportDialog = page.locator('.quant-report-export');
  await exportDialog
    .getByLabel('Export format')
    .selectOption('strategy_evidence_bundle_json');
  const rendered = exportDialog.getByLabel('Rendered Strategy Evidence Bundle JSON');
  await expect(rendered).toBeVisible();
  const bundle = JSON.parse((await rendered.textContent()) ?? '{}') as {
    schema_version?: string;
    run?: { provider?: string; model?: string; question?: string };
    dataset?: {
      symbol?: string;
      interval?: string;
      periods_per_year?: number;
      source_metadata?: { connector_version?: string; closed_dropped_count?: number };
    };
    candidates?: Array<{
      candidate_id?: string;
      name?: string;
      replan_decision?: { action?: string };
    }>;
    selected_result?: {
      candidate_id?: string;
      replan_decision?: { action?: string };
      research_decision?: {
        decision_basis?: string;
        deviation?: { reason?: string; reference_candidate_id?: string };
      };
      next_step?: string;
    };
    validation?: {
      generalization?: { status?: string; holdout_evidence_state?: string };
    };
  };
  expect(bundle.schema_version).toBe('strategy_evidence_bundle_v1');
  expect(bundle.run).toMatchObject({
    provider: 'deepseek',
    model: 'deepseek-v4-flash',
    question,
  });
  expect(bundle.dataset).toMatchObject({
    symbol: 'BTCUSD',
    interval: '4h',
    periods_per_year: 2190,
    source_metadata: {
      connector_version: 'kraken-spot-ohlc-v1',
      closed_dropped_count: 1,
    },
  });
  expect(bundle.candidates).toHaveLength(3);
  const candidateCEntry = bundle.candidates?.find((c) => c.name === candidateC);
  expect(candidateCEntry).toBeDefined();
  expect(candidateCEntry?.replan_decision?.action).toBe('switch_approved_family');
  expect(bundle.selected_result?.candidate_id).toBe(candidateBId);
  expect(bundle.selected_result?.research_decision?.decision_basis).toBe('robustness_override');
  expect(bundle.selected_result?.research_decision?.deviation?.reason).toBe('minimum_trade_evidence');
  expect(bundle.selected_result?.research_decision?.deviation?.reference_candidate_id).toBe(
    candidateCId,
  );
  expect(bundle.selected_result?.next_step).toBe('revise_research');
  expect(bundle.validation?.generalization?.status).toBe('fail');
  expect(bundle.validation?.generalization?.holdout_evidence_state).toBe('fresh_sealed');
  await expectNoHorizontalOverflow(page);
  await capture(page, 'v1-final-183209-05-e0-export-1440x960.png');
  await exportDialog.getByRole('button', { name: 'Close' }).click();

  await terminal.getByRole('button', { name: 'Research history' }).click();
  const history = page.getByRole('table', {
    name: 'Searchable and filterable research run history',
  });
  const runRow = history.getByRole('row').filter({ hasText: question });
  await expect(runRow).toContainText('BTCUSD · 4h');
  await expect(runRow).toContainText('Completed');
  await expect(runRow).toContainText('Root version');
  await expectNoHorizontalOverflow(page);
  const historicalSnapshot = page.waitForResponse(
    (response) => response.url().endsWith(`/v1/quant/runs/${runId}/workspace-snapshot`),
  );
  await runRow.getByRole('button', { name: 'Open run' }).click();
  expect((await historicalSnapshot).ok()).toBe(true);
  await page.getByRole('button', { name: 'Open decision', exact: true }).click();
  await expect(page.getByText('Historical run', { exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Decision', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(page.locator('.quant-terminal-decision')).toContainText('Failed');
  await expect(page.locator('.quant-terminal-decision')).toContainText(candidateB);
  await expect(page.getByRole('button', { name: 'Review & refine research' })).toHaveCount(0);
  await expect(page.locator('.quant-terminal-decision')).not.toContainText('Proposed change');
  await capture(page, 'v1-final-183209-06-history-reopen-1440x960.png');

  expect(browserErrors).toEqual([]);
});
