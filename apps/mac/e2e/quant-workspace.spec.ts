import { expect, test, type Page } from './fixture-test';

declare const process: { env: Record<string, string | undefined> };
declare const Buffer: { from(input: string, encoding?: string): unknown };

const fixtureState = process.env.POKIEQUANT_E2E_RUN_STATE ?? 'quant-completed';
const quantFailure = process.env.POKIEQUANT_E2E_FAILURE ?? null;
const expectedRunState: Record<string, string> = {
  'quant-ready': 'Draft',
  'quant-plan-approval': 'Plan review',
  'quant-loading-data': 'Verifying dataset',
  'quant-generating-candidates': 'Preparing candidates',
  'quant-running': 'Running experiments',
  'quant-repairing': 'Repairing candidate',
  'quant-validating': 'Validating evidence',
  'quant-generating-report': 'Building report',
  'quant-waiting-review': 'Review required',
  'quant-completed': 'Completed',
  'quant-paper-pass': 'Completed',
  'quant-no-viable-candidate': 'Completed',
  'quant-failed-safe': 'Failed',
  'quant-cancelled': 'Cancelled',
};
const expectedSidebarStatus: Record<string, string> = {
  ...expectedRunState,
  'quant-ready': 'Ready',
  'quant-completed': 'Experiments complete — validation pending',
  'quant-paper-pass': 'Research complete',
};
const fixtureStatus = expectedRunState[fixtureState] ?? 'Completed';
const sidebarStatus = expectedSidebarStatus[fixtureState] ?? fixtureStatus;
const activeResearchStates = [
  'quant-loading-data',
  'quant-generating-candidates',
  'quant-running',
  'quant-repairing',
  'quant-validating',
  'quant-generating-report',
];
const expectedLiveDecision: Record<string, {
  currentTitle: string;
  currentDetail: string;
  observationTitle: string;
  observationDetail: string;
  nextTitle: string;
  nextDetail: string;
}> = {
  'quant-loading-data': {
    currentTitle: 'Loading research data',
    currentDetail: 'Load market dataset · 1 of 10 plan steps complete.',
    observationTitle: 'Dataset verification in progress',
    observationDetail: 'No experiment evidence is available until the pinned dataset passes its checks.',
    nextTitle: 'Wait for the next retained decision',
    nextDetail: 'Generate candidate specifications after the dataset is ready.',
  },
  'quant-generating-candidates': {
    currentTitle: 'Initial hypothesis A · SMA 20/100',
    currentDetail: 'fast=20 · slow=100 · Queued',
    observationTitle: 'Candidate specifications in progress',
    observationDetail: 'No training result is available until the first bounded candidate completes.',
    nextTitle: 'Complete the initial A/B hypotheses',
    nextDetail: 'Run the first prepared candidate against the training range.',
  },
  'quant-running': {
    currentTitle: 'Initial hypothesis B · SMA 50/200',
    currentDetail: 'fast=50 · slow=200 · Running',
    observationTitle: 'SMA 20/100 completed training',
    observationDetail: '+20.6% annual return · 5.78 Sharpe · -8.8% drawdown.',
    nextTitle: 'Compare the initial A/B hypotheses',
    nextDetail: 'Continue the candidate queue, then compare completed results.',
  },
  'quant-repairing': {
    currentTitle: 'Initial hypothesis B · SMA 50/200',
    currentDetail: 'fast=50 · slow=200 · Repairing',
    observationTitle: 'SMA 20/100 completed training',
    observationDetail: '+20.6% annual return · 5.78 Sharpe · -8.8% drawdown.',
    nextTitle: 'Compare the initial A/B hypotheses',
    nextDetail: 'Backtest the revised candidate when its parameters are ready.',
  },
  'quant-validating': {
    currentTitle: 'Validating results',
    currentDetail: 'Validate robustness · 6 of 10 plan steps complete.',
    observationTitle: '200-day breakout completed training',
    observationDetail: '+16.3% annual return · 4.46 Sharpe · -15.5% drawdown.',
    nextTitle: 'Candidate C is retained · 200-day breakout',
    nextDetail: 'Apply walk-forward checks and the sealed holdout review.',
  },
  'quant-generating-report': {
    currentTitle: 'Building report',
    currentDetail: 'Generate report · 8 of 10 plan steps complete.',
    observationTitle: '200-day breakout completed training',
    observationDetail: '+16.3% annual return · 4.46 Sharpe · -15.5% drawdown.',
    nextTitle: 'Candidate C is retained · 200-day breakout',
    nextDetail: 'Publish the comparison and limitations for review.',
  },
};

async function expectLiveAgentDecision(page: Page, state = fixtureState) {
  const expected = expectedLiveDecision[state];
  if (!expected) throw new Error(`No Qurio research decision expectation is registered for ${state}.`);
  const surface = page.locator('[aria-labelledby="pq-agent-decision-chain-heading"]');
  await expect(surface).toBeVisible();
  await expect(surface.getByRole('heading', { name: 'Agent decision' })).toBeVisible();
  const sections = surface.locator(':scope > div > section');
  const observation = sections.nth(0);
  const why = sections.nth(1);
  const next = sections.nth(2);
  await expect(sections).toHaveCount(3);
  await expect(observation.locator(':scope > span')).toHaveText('Observation');
  await expect(why.locator(':scope > span')).toHaveText('Why Qurio changed');
  await expect(next.locator(':scope > span')).toHaveText('Next action');
  await expect(next.locator(':scope > strong')).not.toBeEmpty();
  await expect(observation.locator(':scope > strong')).toHaveText(expected.observationTitle);
  await expect(observation).toContainText(expected.observationDetail);
  return surface;
}

async function expectWorkspaceTabsInsideHeader(page: Page) {
  const headerBox = await page.locator('.pq-workbench-header').boundingBox();
  if (!headerBox) throw new Error('Workspace header is not measurable.');
  for (const name of ['Overview', 'Experiments', 'Analysis', 'Decision']) {
    const tabBox = await page.getByRole('tab', { name, exact: true }).boundingBox();
    if (!tabBox) throw new Error(`${name} tab is not measurable.`);
    expect(tabBox.x).toBeGreaterThanOrEqual(headerBox.x);
    expect(tabBox.y).toBeGreaterThanOrEqual(headerBox.y);
    expect(tabBox.x + tabBox.width).toBeLessThanOrEqual(headerBox.x + headerBox.width);
    expect(tabBox.y + tabBox.height).toBeLessThanOrEqual(headerBox.y + headerBox.height);
  }
}

async function expectLiveDecisionBeforeCandidateProgress(page: Page) {
  const decisionBox = await page.locator('[aria-labelledby="pq-agent-decision-chain-heading"]').boundingBox();
  const candidateBox = await page.getByRole('heading', { name: 'Candidate experiments' }).boundingBox();
  if (!decisionBox || !candidateBox) throw new Error('Live decision and candidate progress must both be measurable.');
  expect(decisionBox.y).toBeLessThan(candidateBox.y);
}

async function rewriteWorkspaceSnapshot(page: Page, mutate: (snapshot: Record<string, unknown>) => void, routePattern = '**/v1/quant/workspace-snapshot') {
  await page.route(routePattern, async (route) => {
    const response = await route.fetch();
    const snapshot = await response.json() as Record<string, unknown>;
    mutate(snapshot);
    await route.fulfill({ response, json: snapshot });
  });
}

function buildBtcusdt4hCsv(count = 548) {
  const start = Date.parse('2024-01-01T00:00:00Z');
  const rows = ['timestamp,open,high,low,close,volume'];
  for (let index = 0; index < count; index += 1) {
    const timestamp = new Date(start + index * 14_400_000).toISOString().replace('.000Z', 'Z');
    const base = 16_500 + index * 12;
    const open = base + (index % 5);
    const close = base + 6 + (index % 7);
    const high = Math.max(open, close) + 9;
    const low = Math.min(open, close) - 8;
    const volume = 1_000 + index * 3;
    rows.push(`${timestamp},${open.toFixed(2)},${high.toFixed(2)},${low.toFixed(2)},${close.toFixed(2)},${volume.toFixed(2)}`);
  }
  return rows.join('\n');
}

function csvUpload(name: string, content: string) {
  return { name, mimeType: 'text/csv', buffer: Buffer.from(content, 'utf8') as never };
}

function setSeedability(snapshot: Record<string, unknown>, canSeedResearch: boolean, candidateId = 'candidate-b') {
  const candidates = snapshot.candidates as Array<Record<string, unknown>> | undefined;
  if (candidates) {
    for (const candidate of candidates) {
      candidate.canSeedResearch = candidate.id === candidateId ? canSeedResearch : false;
    }
  }
}

function terminalGeneralizationSplit(snapshot: Record<string, unknown>) {
  const dataset = snapshot.dataset as Record<string, unknown>;
  const scope = snapshot.scope as Record<string, unknown>;
  const range = scope.dateRange as Record<string, unknown>;
  const bars = snapshot.bars as Array<Record<string, unknown>> | undefined;
  const barCount = typeof dataset.barCount === 'number' ? dataset.barCount : bars?.length ?? 2;
  const trainBarCount = Math.max(1, Math.min(Math.floor(barCount * 80 / 100), barCount - 1));
  const holdoutBarCount = barCount - trainBarCount;
  const cutoffDate = typeof bars?.[trainBarCount]?.date === 'string'
    ? bars[trainBarCount].date
    : String(range.start);
  const datasetId = typeof dataset.id === 'string' ? dataset.id : '';
  const datasetDigest = typeof dataset.digest === 'string' ? dataset.digest : '';
  const isMarketV2 = dataset.schemaVersion === 'quant-market-bars-v2';
  const split = {
    method: 'chronological',
    ruleVersion: 'chronological-80-20-v1',
    trainBarCount,
    holdoutBarCount,
    cutoffDate,
    datasetId,
    datasetDigest,
    ...(isMarketV2 && typeof dataset.interval === 'string' ? { interval: dataset.interval } : {}),
    ...(isMarketV2 && typeof dataset.periodsPerYear === 'number' ? { periodsPerYear: dataset.periodsPerYear } : {}),
    ...(isMarketV2 && typeof range.start === 'string' ? { rangeStartUtc: range.start } : {}),
    ...(isMarketV2 && typeof range.end === 'string' ? { rangeEndUtc: range.end } : {}),
  };
  if (trainBarCount < 1 || holdoutBarCount < 1 || !split.datasetId || !split.datasetDigest || !split.cutoffDate) {
    throw new Error('Terminal e2e fixture requires a complete chronological generalization split.');
  }
  return split;
}

function setTerminalFailure(snapshot: Record<string, unknown>) {
  const report = snapshot.report as Record<string, unknown>;
  const selectedCandidateId = 'candidate-b';
  report.selectionDecision = { basis: 'approved_objective_rank', selectedCandidateId };
  report.generalization = {
    status: 'fail',
    reason: 'The retained sealed holdout did not support the final choice.',
    selectedCandidateId,
    split: terminalGeneralizationSplit(snapshot),
  };
}

function setContinuationStress(snapshot: Record<string, unknown>) {
  snapshot.project = { ...(snapshot.project as Record<string, unknown>), goal: 'RefineThisContinuationWithALongNoSpaceResearchQuestionToStressTheLayout' };
  const candidates = snapshot.candidates as Array<Record<string, unknown>> | undefined;
  if (candidates) {
    for (const candidate of candidates) {
      candidate.canSeedResearch = candidate.id === 'candidate-b';
      if (candidate.id === 'candidate-b') candidate.name = 'Candidate B · ContinuationLayoutStressTestWithoutSpaces';
    }
  }
}

async function expectTradesToFitInitialViewport(page: Page) {
  const analysisView = page.locator('.pq-analysis-view');
  await expect(analysisView.locator('thead th', { hasText: 'Entry' })).toBeVisible();
  await expect(analysisView.locator('thead th', { hasText: 'Exit' })).toBeVisible();
  await expect(analysisView.locator('thead th', { hasText: 'Holding' })).toBeVisible();
  const layout = await page.evaluate(() => {
    const workspace = document.querySelector<HTMLElement>('.pq-strategy-workspace');
    const analysis = document.querySelector<HTMLElement>('.pq-strategy-lab');
    const monitor = workspace?.querySelector<HTMLElement>(':scope > .quant-widget-frame');
    const view = document.querySelector<HTMLElement>('.pq-analysis-view');
    const heading = document.querySelector<HTMLElement>('.pq-strategy-analysis > header h2');
    const entry = [...document.querySelectorAll<HTMLElement>('.pq-analysis-view th')].find((item) => item.textContent?.trim() === 'Entry');
    const holding = [...document.querySelectorAll<HTMLElement>('.pq-analysis-view th')].find((item) => item.textContent?.trim() === 'Holding');
    const viewBounds = view?.getBoundingClientRect();
    return {
      documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      viewFits: Boolean(view && view.scrollWidth <= view.clientWidth + 1 && view.scrollLeft === 0),
      railStacked: Boolean(analysis && monitor && monitor.getBoundingClientRect().top >= analysis.getBoundingClientRect().bottom - 1),
      headingWidth: heading?.getBoundingClientRect().width ?? 0,
      entryVisible: Boolean(entry && viewBounds && entry.getBoundingClientRect().left >= viewBounds.left - 1),
      holdingVisible: Boolean(holding && viewBounds && holding.getBoundingClientRect().right <= viewBounds.right + 1),
    };
  });
  expect(layout).toMatchObject({ documentFits: true, viewFits: true, railStacked: true, entryVisible: true, holdingVisible: true });
  expect(layout.headingWidth).toBeGreaterThan(240);
}

test('renders the server-owned Quant fixture without active Glint product copy', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Quant screenshots use the deterministic loopback fixture API.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');

  await expect(page.getByRole('complementary', { name: 'Qurio navigation' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'SPY Research' })).toBeVisible();
  if (fixtureState === 'quant-ready') {
    await expect(page.getByRole('heading', { name: 'Generate the research plan' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Generate plan', exact: true })).toHaveCount(1);
    await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).toHaveCount(0);
  } else if (!activeResearchStates.includes(fixtureState)) {
    await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).toBeVisible();
    await expect(page.locator('.pq-copilot-details')).toContainText(fixtureStatus);
    if (['quant-completed', 'quant-paper-pass', 'quant-no-viable-candidate', 'quant-waiting-review'].includes(fixtureState)) {
      await expect(page.getByRole('heading', { name: 'Strategy vs benchmark' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Candidate snapshot' })).toBeVisible();
    }
    if (['quant-failed-safe', 'quant-cancelled'].includes(fixtureState)) await expect(page.getByText('No strategy result')).toBeVisible();
  }
  const currentResearch = page.getByTestId('quant-sidebar').getByRole('region', { name: 'Current research', exact: true });
  await expect(currentResearch).toContainText(sidebarStatus);
  await expect(currentResearch).not.toContainText('_');
  if (fixtureState === 'quant-ready') {
    await expect(page.getByRole('tab', { name: 'Experiments', exact: true })).toBeDisabled();
    await expect(page.getByRole('tab', { name: 'Analysis', exact: true })).toBeDisabled();
    await expect(page.getByRole('tab', { name: 'Decision', exact: true })).toBeDisabled();
    await expect(page.getByText('No experiment evidence yet')).toHaveCount(0);
    await expect(page.getByText('Decision pending')).toHaveCount(0);
  } else {
    await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
    if (activeResearchStates.includes(fixtureState)) {
      await expectLiveAgentDecision(page);
      await expect(page.getByRole('table', { name: 'Live candidate experiment progress' })).toBeVisible();
    } else if (['quant-failed-safe', 'quant-cancelled'].includes(fixtureState)) {
      await expect(page.getByText('No candidate evidence retained')).toBeVisible();
    } else if (fixtureState === 'quant-plan-approval') {
      await expect(page.getByText('Candidate results pending')).toBeVisible();
    } else {
      await expect(page.getByRole('heading', { name: 'Candidate comparison' })).toBeVisible();
      await expect(page.getByRole('table', { name: 'Candidate strategy comparison' })).toContainText('SMA 50/200');
    }
    if (!activeResearchStates.includes(fixtureState)) {
      await page.getByText(/Activity & artifacts/).click();
      await expect(page.getByText('Synthetic Demo Fixture').first()).toBeVisible();
      if (['quant-waiting-review', 'quant-completed', 'quant-paper-pass', 'quant-no-viable-candidate'].includes(fixtureState)) {
        await expect(page.getByRole('heading', { name: 'Daily-bar kernel verified' })).toBeVisible();
        await expect(page.getByText('1,564 synthetic weekday bars')).toBeVisible();
      } else {
        await expect(page.getByRole('heading', { name: 'Daily-bar kernel ready' })).toBeVisible();
        await expect(page.getByText('Results remain hidden until the API advances the run.')).toBeVisible();
      }
      await expect(page.getByText('No network · no broker · no arbitrary code')).toBeVisible();
    }
    await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
    if (['quant-failed-safe', 'quant-cancelled'].includes(fixtureState)) {
      await expect(page.getByText('No candidate evidence retained')).toBeVisible();
    } else if ((activeResearchStates.includes(fixtureState) && !['quant-validating', 'quant-generating-report'].includes(fixtureState)) || fixtureState === 'quant-plan-approval') {
      await expect(page.getByText('Candidate results pending')).toBeVisible();
    } else {
      await expect(page.getByRole('tablist', { name: 'Strategy analysis views' })).toBeVisible();
      await expect(page.getByRole('img', { name: /equity compared with benchmark/ })).toBeVisible();
    }
    if (fixtureState === 'quant-no-viable-candidate') {
      await page.getByRole('tab', { name: 'Overview', exact: true }).click();
      await expect(page.locator('.quant-decision-gate').getByText(/No candidate passed validation/)).toBeVisible();
    }
  }
  await expect(page.getByRole('button', { name: 'Inbox' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Signals' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Decisions' })).toHaveCount(0);
  await expect(page.getByText('Start Paper Trading')).toHaveCount(0);

  if (fixtureState === 'quant-repairing') {
    await expect(page.getByText(/recoverable experiment/i).first()).toBeVisible();
    await expect(page.locator('.quant-run-monitor')).not.toContainText('Failed safely');
  }
  if (fixtureState === 'quant-no-viable-candidate') {
    await expect(page.locator('.quant-decision-gate').getByText(/No candidate passed validation/)).toBeVisible();
    await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).not.toContainText('Failed safely');
  }

  await page.locator('.quant-sidebar-settings').click();
  await expect(page.getByRole('heading', { name: 'Runtime and policy' })).toBeVisible();
  await expect(page.getByText('Research policy')).toBeVisible();
  await expect(page.getByText('Sealed holdout')).toBeVisible();
  await expect(page.getByText('Disabled')).toBeVisible();
});

test('blocks Paper handoff until the retained candidate passes sealed validation', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Paper Trading uses the completed deterministic fixture.');
  await page.setViewportSize({ width: 1024, height: 760 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Paper Trading', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Paper Trading', exact: true })).toBeVisible();
  await expect(page.getByText('No live-trading route or live credentials')).toBeVisible();
  await expect(page.getByText('$100,000.00').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review draft' })).toBeDisabled();
  await expect(page.getByText('No terminal decision is available.')).toBeVisible();
  await page.getByRole('button', { name: 'Open decision' }).click();
  await expect(page.getByRole('tab', { name: 'Decision', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: 'Final decision unavailable' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('hands a sealed-holdout pass into a reviewed Paper order and position', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-paper-pass', 'Paper Trading pass path uses the deterministic sealed-holdout fixture.');
  await page.setViewportSize({ width: 1024, height: 760 });
  await page.goto('/');
  await expect(page.getByText('Research complete', { exact: true }).first()).toBeVisible();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Paper Trading', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Paper Trading', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review draft' })).toBeEnabled();
  await page.getByRole('button', { name: 'Review draft' }).click();
  const orders = page.getByRole('region', { name: 'Orders' });
  await expect(orders).toContainText('draft');
  await orders.getByRole('button', { name: 'Submit' }).click();
  await expect(orders).toContainText('filled');
  const positions = page.getByRole('region', { name: 'Positions' });
  await expect(positions).toContainText('SPY');
  await expect(positions).toContainText('365.25');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('shares Overview candidate selection with Experiments, Analysis, and Decision', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Shared selection uses the completed deterministic fixture.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  const snapshot = page.getByRole('table', { name: 'Candidate strategy comparison' });
  await snapshot.getByRole('button', { name: 'SMA 20/100' }).click();
  await expect(page.locator('.pq-results-performance')).toContainText('SMA 20/100');
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  await expect(page.getByRole('button', { name: 'SMA 20/100' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(page.locator('.pq-strategy-analysis')).toContainText('SMA 20/100');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.locator('.quant-report')).toContainText('SMA 20/100');
});

test('Continue research stays hidden in the fixture snapshot and on waiting review', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Continuation visibility uses the deterministic loopback fixture API.');
  await page.setViewportSize({ width: 1440, height: 960 });
  let waitingReview = false;
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    if (waitingReview) {
      snapshot.run = { ...(snapshot.run as Record<string, unknown>), state: 'waiting_for_review' };
      setSeedability(snapshot, false);
    }
  });
  await page.goto('/');
  for (const tabName of ['Decision', 'Experiments', 'Analysis'] as const) {
    await page.getByRole('tab', { name: tabName, exact: true }).click();
    await expect(page.getByRole('button', { name: 'Continue research' })).toHaveCount(0);
  }
  waitingReview = true;
  await page.reload();
  for (const tabName of ['Decision', 'Experiments', 'Analysis'] as const) {
    await page.getByRole('tab', { name: tabName, exact: true }).click();
    await expect(page.getByRole('button', { name: 'Continue research' })).toHaveCount(0);
  }
});

test('completed Qurio opens Decision instead of continuing the selected candidate', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Completed Qurio uses the retained decision as its terminal entry point.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    setSeedability(snapshot, true);
    setTerminalFailure(snapshot);
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Continue research' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open decision', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Decision', exact: true })).toHaveAttribute('aria-selected', 'true');
});

test('reopened historical evidence stays read-only and retains its own source context', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Historical identity uses the completed deterministic history fixtures.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await rewriteWorkspaceSnapshot(page, (snapshot) => setSeedability(snapshot, true), '**/v1/quant/runs/*/workspace-snapshot');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  await history.getByRole('row', { name: /Compare slower SPY trend filters/ }).last().getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.locator('.quant-report')).toContainText('Compare slower trend filters while retaining the original SPY research evidence.');
  await expect(page.locator('.quant-report')).toContainText('Establish the SPY trend-filter baseline before a focused continuation.');
  await expect(page.locator('.quant-report')).toContainText('Continued from source version');
  await expect(page.getByRole('button', { name: 'Continue research' })).toHaveCount(0);
  await expect(page.getByText('Historical run', { exact: true })).toBeVisible();
});

test('Review and refine research keeps 1024-width layout dense with long source text', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Terminal refinement layout uses the completed deterministic fixture.');
  await page.setViewportSize({ width: 1024, height: 960 });
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    setContinuationStress(snapshot);
    setTerminalFailure(snapshot);
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.getByRole('button', { name: 'Refine version' }).click();
  await expect(page.getByRole('heading', { name: 'Refine research' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Refine one bounded change' })).toBeVisible();
  const refinementContext = page.locator('.quant-refinement-context');
  await expect(refinementContext.getByText('ContinuationLayoutStressTestWithoutSpaces', { exact: true })).toBeVisible();
  await expect(refinementContext.getByText('RefineThisContinuationWithALongNoSpaceResearchQuestionToStressTheLayout', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel refinement' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate next plan' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('inspects persisted strategy performance by pointer and keyboard across result views', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Chart inspection uses the completed deterministic performance series.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');

  const overviewPlot = page.locator('.pq-results-chart .pq-strategy-plot');
  const overviewReadout = page.locator('.pq-results-chart .pq-strategy-inspection');
  await expect(overviewPlot).toHaveAttribute('aria-label', /Use Left and Right arrows/);
  await expect(overviewReadout.locator('time')).toHaveAttribute('datetime', '2023-12-29');
  await overviewPlot.focus();
  await overviewPlot.press('Home');
  await expect(overviewReadout.locator('time')).toHaveAttribute('datetime', '2018-01-02');
  await overviewPlot.press('ArrowRight');
  await expect(overviewReadout.locator('time')).toHaveAttribute('datetime', '2018-01-16');

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const analysis = page.locator('.pq-strategy-analysis');
  const analysisPlot = analysis.locator('.pq-strategy-plot');
  const analysisReadout = analysis.locator('.pq-strategy-inspection');
  await analysisPlot.hover({ position: { x: 4, y: 120 } });
  await expect(analysisReadout.locator('time')).toHaveAttribute('datetime', '2018-01-02');
  await analysisPlot.click({ position: { x: 310, y: 120 } });
  await page.mouse.move(2, 2);
  const pinnedDate = await analysisReadout.locator('dd').first().textContent();
  await page.mouse.move(1, 1);
  await expect(analysisReadout.locator('dd').first()).toHaveText(pinnedDate ?? '');
  await expect(analysisReadout).toContainText('Difference');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/strategy-inspection-analysis-1440x960.png', animations: 'disabled' });

  await analysis.getByRole('tab', { name: 'Drawdown' }).click();
  await expect(analysis.locator('.pq-strategy-axis-label').filter({ hasText: /^0%$/ })).toBeVisible();
  await page.setViewportSize({ width: 1024, height: 960 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(analysisReadout).toBeVisible();
  await analysis.getByRole('tab', { name: 'Market', exact: true }).click();
  await expect(analysis.locator('.quant-trade-marker')).toHaveCount(4);
  await expect(analysis.locator('.quant-trade-marker.is-highlighted')).toHaveCount(2);
  await expect(analysis.locator('.pq-market-trade-inspection')).toContainText('2018-10-09');
  await analysis.getByRole('button', { name: '2020-08-17', exact: true }).click();
  await expect(analysis.locator('.pq-market-trade-inspection')).toContainText('2020-08-17');
  await expect(analysis.getByText('no performance metric is recalculated here')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await analysis.getByRole('tab', { name: 'Trades', exact: true }).click();
  await expectTradesToFitInitialViewport(page);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/strategy-inspection-analysis-1024x960.png', animations: 'disabled' });

  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  const reportPlot = page.locator('.quant-report-performance .pq-strategy-plot');
  await expect(reportPlot).toHaveAttribute('aria-label', /Inspect .* equity performance/);
  await reportPlot.focus();
  await reportPlot.press('End');
  await expect(page.locator('.quant-report-performance .pq-strategy-inspection time')).toHaveAttribute('datetime', '2023-12-29');
});

test('finds, compares, and reopens server-owned historical research runs', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Run comparison uses the completed deterministic history fixtures.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await rewriteWorkspaceSnapshot(page, (snapshot) => setSeedability(snapshot, true), '**/v1/quant/runs/*/workspace-snapshot');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();

  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  await expect(history.getByRole('row')).toHaveCount(9);
  await expect(page.getByText('8 of 8 runs')).toBeVisible();
  await expect(history).toContainText('BTCUSDT · 4h');
  await expect(history).toContainText('SPY Regime Study');
  await expect(history).toContainText('QQQ Momentum Review');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/runs-list-1440x960.png', animations: 'disabled' });

  await page.getByRole('searchbox', { name: 'Find research', exact: true }).fill('QQQ Momentum Review');
  await expect(history.getByRole('row')).toHaveCount(2);
  await expect(history).toContainText('Evaluate QQQ momentum resilience');
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByLabel('Outcome').selectOption('completed');
  await expect(history.getByRole('row')).toHaveCount(9);
  await page.getByText('Project & sort', { exact: true }).click();
  await page.getByLabel('Sort').selectOption('oldest');
  await expect(history.getByRole('row').nth(1)).toContainText('QQQ momentum resilience');
  await page.getByRole('button', { name: 'Clear filters' }).click();

  await page.getByLabel('Select Compare slower SPY trend filters across the same research range. for comparison').last().check();
  await page.getByLabel('Select Evaluate QQQ momentum resilience after the 2020 regime shift. for comparison').check();
  await page.getByRole('button', { name: 'Compare 2' }).click();
  const comparison = page.getByRole('table', { name: 'Stored strategy results for selected historical research runs' });
  await expect(comparison).toContainText('Comparable context');
  await expect(comparison).toContainText('Differs: dataset, symbol, research range');
  await expect(page.getByText('Comparison context differs.')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/runs-compare-1440x960.png', animations: 'disabled' });

  await page.setViewportSize({ width: 1024, height: 960 });
  await expect(comparison).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/runs-compare-1024x960.png', animations: 'disabled' });

  await page.getByRole('button', { name: 'Back to history' }).click();
  const historicalRow = history.getByRole('row', { name: /Compare slower SPY trend filters/ }).last();
  await historicalRow.getByRole('button', { name: 'Open run' }).click();
  await expect(page.getByRole('heading', { name: 'SPY Regime Study' })).toBeVisible();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  await page.getByRole('button', { name: 'Compare with source' }).click();
  const seriesComparison = page.getByRole('table', { name: 'Stored strategy results for selected historical research runs' });
  await expect(seriesComparison).toContainText('Comparable context');
  await expect(page.getByRole('region', { name: 'Research version change' })).toContainText('Weaker');
  await expect(page.getByRole('region', { name: 'Research version change' })).toContainText('Compare slower trend filters while retaining the original SPY research evidence.');
  await expect(page.getByRole('region', { name: 'Research version change' })).toContainText('Change vs source');
  await expect(page.getByText('2 selected · Metrics are shown from each run’s stored result.')).toBeVisible();
  await page.getByRole('button', { name: 'Refine from this result' }).click();
  await expect(page.getByRole('heading', { name: 'Refine research' })).toBeVisible();
  await expect(page.getByLabel('Research goal')).toHaveValue(/Continue research from SMA 50\/200/);
  await expect(page.getByLabel('Refinement reason')).toHaveValue(/Retain Candidate B · SMA 50\/200.*as the seed/);
});

test('projects legacy and public market research series while reopened evidence stays read-only', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Research Series labels use the completed deterministic history fixtures.');
  const noPageOverflow = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  await expect(history).toContainText('Root version');
  await expect(history).toContainText('Continued version');
  await expect(history).toContainText('Continued version · Retry attempt 2');
  await noPageOverflow();

  const continuedRetry = history.getByRole('row').filter({ hasText: 'Compare slower SPY trend filters' }).filter({ hasText: 'Continued version · Retry attempt 2' });
  await continuedRetry.getByRole('button', { name: 'Open run' }).click();
  await expect(page.getByRole('button', { name: 'Open source version' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open prior attempt' })).toBeVisible();
  await page.getByRole('button', { name: 'Open source version' }).click();
  await expect(history.locator('tr.is-current')).toContainText('Establish the SPY trend-filter baseline');
  await expect(history.locator('tr.is-current')).toContainText('Root version');

  await continuedRetry.getByRole('button', { name: 'Open run' }).click();
  await page.getByRole('button', { name: 'Open prior attempt' }).click();
  await expect(history.locator('tr.is-current')).toContainText('Compare slower SPY trend filters');
  await expect(history.locator('tr.is-current')).toContainText('Continued version');

  await continuedRetry.getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.locator('.quant-report')).toContainText('Continued from source version');
  await expect(page.locator('.quant-report')).toContainText('Retry attempt 2');
  await expect(page.getByRole('button', { name: 'Open source version' })).toBeVisible();
  await page.getByRole('button', { name: 'Open source version' }).click();
  await expect(page.getByText('Historical run', { exact: true })).toBeVisible();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  await expect(history.locator('tr.is-current')).toContainText('Establish the SPY trend-filter baseline');
  await noPageOverflow();

  const marketRetry = history.getByRole('row').filter({ hasText: 'Continued version · Retry attempt 2' }).filter({ hasText: 'BTCUSDT · 4h' });
  await marketRetry.getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open source version' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open prior attempt' })).toBeVisible();
  await page.getByRole('button', { name: 'Open source version' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  await expect(history.locator('tr.is-current')).toContainText('Root version');
  await expect(history.locator('tr.is-current')).toContainText('BTCUSDT · 4h');

  await marketRetry.getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.getByRole('button', { name: 'Open prior attempt' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  await expect(history.locator('tr.is-current')).toContainText('Continued version');
  await expect(history.locator('tr.is-current')).not.toContainText('Retry attempt');

  await marketRetry.getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const historicalCopilot = page.getByRole('complementary', { name: 'Qurio', exact: true });
  await expect(historicalCopilot.getByText('Historical evidence is read-only.', { exact: true })).toBeVisible();
  await expect(historicalCopilot.getByRole('button', { name: 'Return to latest', exact: true })).toBeVisible();
  await expect(historicalCopilot.getByLabel('Ask Qurio about this research')).toBeVisible();
  await expect(historicalCopilot.getByRole('button', { name: /Approve|Cancel|Retry|Continue/ })).toHaveCount(0);
  for (const tabName of ['Decision', 'Experiments', 'Analysis'] as const) {
    await page.getByRole('tab', { name: tabName, exact: true }).click();
    await expect(page.getByRole('button', { name: 'Continue research' })).toHaveCount(0);
  }

  await noPageOverflow();
});

test('slow initial API response preserves the shell and explains the wait', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || Number(process.env.POKIEQUANT_E2E_DELAY_MS ?? 0) < 1_500, 'Slow-loading assertions require an explicit fixture delay.');
  await page.goto('/');
  await expect(page.getByText('Still waiting for the local API')).toBeVisible();
  await expect(page.getByText('No action is required; this view will update when a verified snapshot arrives.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'SPY Research' })).toBeVisible();
});

test('polling failure retains verified data and recovers in place', async ({ page, request }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || process.env.POKIEQUANT_TEST_REFRESH_RECOVERY !== '1', 'Refresh recovery is an explicit fixture-control scenario.');
  const apiPort = process.env.GLINT_FIXTURE_PORT ?? '4174';
  const apiUrl = `http://127.0.0.1:${apiPort}/v1/fixture-control`;
  const headers = { Authorization: 'Bearer fixture-access-token', 'X-Workspace-ID': '00000000-0000-4000-8000-000000000001', 'Idempotency-Key': '00000000-0000-4000-8000-000000000901' };
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'SPY Research' })).toBeVisible();
  expect((await request.post(apiUrl, { headers, data: { api_offline: true } })).ok()).toBe(true);
  const warning = page.getByText('Live updates paused').locator('..');
  await expect(warning).toBeVisible();
  await expect(warning).toContainText('Showing snapshot verified at');
  await expect(page.getByRole('heading', { name: 'SPY Research' })).toBeVisible();
  expect((await request.post(apiUrl, { headers: { ...headers, 'Idempotency-Key': '00000000-0000-4000-8000-000000000902' }, data: { api_offline: false } })).ok()).toBe(true);
  await warning.getByRole('button', { name: 'Refresh now' }).click();
  await expect(warning).toHaveCount(0);
});

test('New Research defaults to a reviewable plan before any experiments run', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Mode selection uses the deterministic loopback fixture API.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'New research', exact: true }).click();
  await expect(page.getByText('What should Qurio investigate?', { exact: true })).toBeVisible();
  const modes = page.getByRole('group', { name: 'Research mode' });
  await expect(modes.getByRole('button', { name: 'Ask' })).toHaveCount(0);
  await expect(page.locator('.quant-mode-switch button[aria-pressed="true"]')).toHaveText('Plan first');
  await expect(modes.getByRole('button', { name: 'Auto Research' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Generate plan' })).toBeDisabled();
});

test('Research Setup switches catalog data and stays dense at desktop widths', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Research Setup uses the deterministic catalog fixture.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  await page.getByRole('tabpanel', { name: 'Binance Spot' }).getByRole('button', { name: 'Fetch and validate' }).click();
  await expect(page.getByRole('row', { name: /BTCUSDT Binance Spot 4 hour/ })).toBeVisible();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'New research', exact: true }).click();
  await page.getByLabel('Research dataset').selectOption('66666666-6666-4666-8666-666666666604');
  await expect(page.getByText('24x7 market', { exact: true })).toBeVisible();
  await expect(page.getByText('Binance Spot deterministic API fixture', { exact: true })).toBeVisible();
  await expect(page.getByText('BTCUSDT · 4h', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Trend & risk' }).click();
  await expect(page.getByLabel('Research goal')).toHaveValue(/BTCUSDT trend strategy/);
  await expect(page.getByLabel('Research start UTC')).toHaveAttribute('min', '2024-01-01T00:00');
  await expect(page.getByLabel('Research end UTC')).toHaveAttribute('max', '2025-12-31T20:00');
  await expect(page.getByRole('button', { name: 'Generate plan' })).toBeEnabled();
  const assertNoOverflow = async () => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  };
  await assertNoOverflow();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/new-research-1440x960.png', animations: 'disabled' });
  await page.setViewportSize({ width: 1024, height: 960 });
  await assertNoOverflow();
  await expect(page.getByRole('heading', { name: 'New research' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate plan' })).toBeVisible();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/new-research-1024x960.png', animations: 'disabled' });
});

test('write operations expose pending state and ignore synchronous duplicate clicks', async ({ page, request }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-ready' || Number(process.env.POKIEQUANT_E2E_MUTATION_DELAY_MS ?? 0) < 300, 'Duplicate-submit assertions require the delayed ready fixture.');
  const apiPort = process.env.GLINT_FIXTURE_PORT ?? '4174';
  const stateUrl = `http://127.0.0.1:${apiPort}/v1/fixture-state`;
  const headers = { Authorization: 'Bearer fixture-access-token', 'X-Workspace-ID': '00000000-0000-4000-8000-000000000001' };
  const mutationCount = async () => Number(((await (await request.get(stateUrl, { headers })).json()) as { mutation_request_count: number }).mutation_request_count);

  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'New research', exact: true }).click();
  await page.getByLabel('Research goal').fill('Test duplicate-safe bounded research creation.');
  const start = page.getByRole('button', { name: 'Generate plan' });
  await start.evaluate((element) => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
  await expect(page.getByRole('button', { name: 'Generating plan…' })).toBeDisabled();
  await expect(page.getByText('Plan created', { exact: true })).toBeVisible();
  await expect.poll(mutationCount).toBe(2);

  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  const fetch = page.getByRole('button', { name: 'Fetch and validate' });
  await fetch.evaluate((element) => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
  await expect(page.getByText('Validating provider response and storing an immutable version…')).toBeVisible();
  await expect(page.getByRole('cell', { name: /BTCUSDT Binance Spot fixture/ })).toBeVisible();
  await expect.poll(mutationCount).toBe(3);

  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const run = page.getByRole('button', { name: 'Advance Offline Run' });
  await run.evaluate((element) => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
  await expect(page.getByText('Submitting command…')).toBeVisible();
  await expect(page.getByText('Offline run advanced', { exact: true })).toBeVisible();
  await expect.poll(mutationCount).toBe(4);
});

test('successful new research returns focus to the project workbench', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-ready', 'Focus assertions require the ready fixture.');
  await page.goto('/');
  await page.getByRole('complementary', { name: 'Qurio navigation' }).getByRole('button', { name: 'New research', exact: true }).click();
  await page.getByLabel('Research goal').fill('Compare a bounded SPY trend hypothesis with synthetic evidence.');
  await page.getByRole('button', { name: 'Generate plan' }).click();
  await expect(page.locator('#pq-workspace-tab-overview')).toBeVisible();
  await expect(page.locator('#pq-workspace-tab-overview')).toBeFocused();
});

test('Research Copilot answers retained-evidence questions without starting another run', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Retained evidence coverage requires the completed fixture.');
  let commandRequests = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/v1/quant/workspace-snapshot/commands')) commandRequests += 1;
  });
  await page.goto('/');
  const copilot = page.getByRole('complementary', { name: 'Qurio', exact: true });
  const question = copilot.getByLabel('Ask Qurio about this research');
  await question.fill('Why was this candidate selected?');
  await copilot.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(copilot.getByLabel('Qurio evidence answer')).toContainText('No authoritative final choice');
  await expect(question).toHaveValue('');
  expect(commandRequests).toBe(0);
  await question.fill('Will SPY go up tomorrow?');
  await copilot.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(copilot.getByLabel('Qurio evidence answer')).toContainText('does not forecast the next price');
});

test('Data lists and fetches deterministic provider datasets without network', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || Boolean(quantFailure), 'Data success routes use the deterministic loopback fixture API without an injected failure.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Catalog' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('Unhandled fixture route')).toHaveCount(0);
  await page.getByRole('button', { name: 'Add data' }).click();
  await expect(page.getByRole('tab', { name: 'Binance Spot' })).toBeFocused();
  const binance = page.getByRole('tabpanel', { name: 'Binance Spot' });
  await binance.getByLabel('Binance Spot interval').selectOption('1D');
  await binance.getByLabel('Binance Spot bar limit').fill('365');
  const fetchRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/datasets/v2/fetch-binance') && request.method() === 'POST');
  await binance.getByRole('button', { name: 'Fetch and validate' }).click();
  expect((await fetchRequest).postDataJSON()).toMatchObject({
    name: 'BTCUSDT Binance Spot 1 day',
    symbol: 'BTCUSDT',
    interval: '1D',
    limit: 365,
  });
  const fetchedRow = page.getByRole('row', { name: /BTCUSDT Binance Spot 1 day/ });
  await expect(fetchedRow).toContainText('365');
  await expect(fetchedRow).toContainText('Binance Spot deterministic API fixture');
  await expect(page.getByRole('tabpanel', { name: 'Catalog' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add data' })).toBeFocused();
});

test('Data Catalog previews the selected dataset bars, retries failure, and switches from SPY to BTCUSDT', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Dataset preview uses deterministic stored OHLCV fixtures.');
  await page.setViewportSize({ width: 1440, height: 960 });
  let failFirstPreview = true;
  await page.route('**/v1/quant/datasets/*/preview?*', async (route) => {
    if (failFirstPreview) {
      failFirstPreview = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'API_OFFLINE', message: 'Dataset preview is temporarily unavailable.', request_id: 'fixture-preview', details: {} } }) });
      return;
    }
    await route.continue();
  });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  const catalog = page.getByRole('table', { name: 'Available research datasets' });
  const spyRow = catalog.getByRole('row', { name: /SPY/ });
  await spyRow.getByRole('button', { name: 'Preview' }).click();
  await expect(page.getByRole('alert')).toContainText('Dataset preview is temporarily unavailable.');
  const spyResponsePromise = page.waitForResponse((response) => response.url().includes('/quant/datasets/') && response.url().includes('/preview') && response.status() === 200);
  await page.getByRole('button', { name: 'Retry preview' }).click();
  const spyResponse = await spyResponsePromise;
  const spyPreview = await spyResponse.json() as { symbol: string; bars: Array<{ close: number }> };
  expect(spyPreview.symbol).toBe('SPY');
  const previewPanel = page.locator('.quant-dataset-preview');
  await expect(previewPanel.getByRole('heading', { name: 'SPY · 1D' }).first()).toBeVisible();
  await expect(previewPanel.getByRole('img', { name: 'SPY 1D price and volume chart' })).toBeVisible();
  await expect(previewPanel.getByRole('button', { name: 'SMA 20' })).toBeVisible();
  await expect(previewPanel.getByRole('button', { name: 'SMA 50' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/data-preview-1440x960.png', animations: 'disabled' });

  await page.getByRole('button', { name: 'Back to catalog' }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  const binance = page.getByRole('tabpanel', { name: 'Binance Spot' });
  await binance.getByLabel('Binance Spot interval').selectOption('1D');
  await binance.getByLabel('Binance Spot bar limit').fill('365');
  const fetchRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/datasets/v2/fetch-binance') && request.method() === 'POST');
  await binance.getByRole('button', { name: 'Fetch and validate' }).click();
  expect((await fetchRequest).postDataJSON()).toMatchObject({
    name: 'BTCUSDT Binance Spot 1 day',
    symbol: 'BTCUSDT',
    interval: '1D',
    limit: 365,
  });
  const btcRow = catalog.getByRole('row', { name: /BTCUSDT Binance Spot 1 day/ });
  const btcResponsePromise = page.waitForResponse((response) => response.url().includes('/quant/datasets/v2/') && response.url().includes('/preview') && response.status() === 200);
  await btcRow.getByRole('button', { name: 'Preview' }).click();
  const btcResponse = await btcResponsePromise;
  const btcPreview = await btcResponse.json() as {
    symbol: string;
    total_bar_count: number;
    data_authenticity: string;
    dataset: { covered_start: string; covered_end: string; bar_count: number; evidence: { requested_bar_count: number; returned_bar_count: number; retained_bar_count: number } };
    bars: Array<{ close: string }>;
  };
  expect(btcPreview.symbol).toBe('BTCUSDT');
  expect(btcPreview.data_authenticity).toBe('synthetic_fixture');
  expect(btcPreview.total_bar_count).toBe(365);
  expect(btcPreview.dataset).toMatchObject({
    covered_start: '2023-01-01T00:00:00+00:00',
    covered_end: '2023-12-31T00:00:00+00:00',
    bar_count: 365,
    evidence: {
      requested_bar_count: 365,
      returned_bar_count: 365,
      retained_bar_count: 365,
    },
  });
  expect(Number(btcPreview.bars[0]?.close)).not.toBe(spyPreview.bars[0]?.close);
  await expect(previewPanel.getByRole('heading', { name: 'BTCUSDT · 1D' }).first()).toBeVisible();
  await expect(previewPanel.getByRole('img', { name: 'BTCUSDT 1D price and volume chart' })).toBeVisible();
  await expect(previewPanel.getByRole('button', { name: 'Use for research' })).toBeVisible();
  await page.setViewportSize({ width: 1024, height: 960 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(page.locator('.quant-data-catalog-list')).toBeHidden();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/data-preview-1024x960.png', animations: 'disabled' });
});

test('provider rate limits preserve the form and expose one retry action', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || quantFailure !== 'rate-limit', 'Rate-limit assertions require the explicit failure fixture.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  const binance = page.getByRole('tabpanel', { name: 'Binance Spot' });
  await binance.getByRole('button', { name: 'Fetch and validate' }).click();
  await expect(binance.getByRole('alert')).toContainText('Provider rate limit reached');
  await expect(binance.getByRole('button', { name: 'Retry fetch' })).toBeFocused();
  await expect(binance.getByLabel('Binance Spot symbol')).toHaveValue('BTCUSDT');
});

test('Nasdaq rate limits preserve the form and keep retry focusable', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || quantFailure !== 'rate-limit', 'Rate-limit assertions require the explicit failure fixture.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  await page.getByRole('tab', { name: 'Nasdaq Equity' }).click();
  const nasdaq = page.getByRole('tabpanel', { name: 'Nasdaq Equity' });
  await nasdaq.getByRole('button', { name: 'Fetch and validate' }).click();
  await expect(nasdaq.getByRole('alert')).toContainText('Provider rate limit reached');
  await expect(nasdaq.getByRole('button', { name: 'Retry fetch' })).toBeFocused();
  await expect(nasdaq.getByLabel('Nasdaq Equity symbol')).toHaveValue('AAPL');
});

test('CSV validation errors surface the parser rejection without leaving the importer', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'CSV validation assertions use the deterministic loopback fixture API.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  await page.getByRole('tab', { name: 'CSV upload' }).click();
  await page.getByLabel('OHLCV CSV file').setInputFiles('e2e/fixtures/feedback.csv');
  await page.getByLabel('Dataset interval').selectOption('1D');
  await page.getByLabel('Dataset name').fill('Broken CSV');
  await page.getByLabel('Dataset symbol').fill('BTCUSDT');
  await page.getByRole('button', { name: 'Import and validate' }).click();
  await expect(page.getByRole('alert')).toContainText('CSV header must exactly match timestamp,open,high,low,close,volume.');
  await expect(page.getByRole('tabpanel', { name: 'CSV upload' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Import and validate' })).toBeEnabled();
});

test('market 4h CSV imports with fewer than 548 bars stay stored but not research-eligible', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Short CSV eligibility assertions use the deterministic loopback fixture API.');
  const csvText = buildBtcusdt4hCsv(547);
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  await page.getByRole('tab', { name: 'CSV upload' }).click();
  await page.getByLabel('OHLCV CSV file').setInputFiles(csvUpload('btcusdt-4h-short.csv', csvText));
  await page.getByLabel('Dataset interval').selectOption('4h');
  await page.getByLabel('Dataset name').fill('BTCUSDT CSV short 4h');
  await page.getByLabel('Dataset symbol').fill('BTCUSDT');
  const importResponsePromise = page.waitForResponse((response) => response.url().endsWith('/v1/quant/datasets/v2/import-csv') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Import and validate' }).click();
  const imported = await importResponsePromise;
  const importedJson = await imported.json() as {
    covered_start: string;
    covered_end: string;
    bar_count: number;
    record_digest: string;
    evidence: { submitted_csv_digest: string };
    research_eligible: boolean;
  };
  expect(importedJson).toMatchObject({
    covered_start: '2024-01-01T00:00:00+00:00',
    covered_end: '2024-04-01T00:00:00+00:00',
    bar_count: 547,
    research_eligible: false,
    evidence: { submitted_csv_digest: expect.stringMatching(/^sha256:[0-9a-f]{64}$/) },
  });
  expect(importedJson.record_digest).toMatch(/^sha256:[0-9a-f]{64}$/);
  const shortRow = page.getByRole('row', { name: /BTCUSDT CSV short 4h/ });
  await expect(shortRow).toContainText('4h');
  await expect(shortRow).toContainText('547');
  await expect(shortRow.getByRole('button', { name: 'Use' })).toBeDisabled();
  const previewResponsePromise = page.waitForResponse((response) => response.url().includes('/v1/quant/datasets/v2/') && response.url().endsWith('/preview?max_points=240') && response.status() === 200);
  await shortRow.getByRole('button', { name: 'Preview' }).click();
  const previewResponse = await previewResponsePromise;
  const previewJson = await previewResponse.json() as { total_bar_count: number; dataset: { bar_count: number; covered_end: string; record_digest: string }; };
  expect(previewJson).toMatchObject({
    total_bar_count: 547,
    dataset: {
      bar_count: 547,
      covered_end: '2024-04-01T00:00:00+00:00',
      record_digest: importedJson.record_digest,
    },
  });
  await expect(page.locator('.quant-dataset-preview').getByRole('button', { name: 'Use for research' })).toBeDisabled();
});

test('provider timeouts keep the research goal and make the failed command recoverable', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || quantFailure !== 'provider-timeout' || fixtureState !== 'quant-completed', 'Timeout assertions require the completed failure fixture.');
  await page.goto('/');
  await page.getByRole('complementary', { name: 'Qurio navigation' }).getByRole('button', { name: 'New research', exact: true }).click();
  const goal = 'Evaluate a bounded SPY trend hypothesis after provider recovery.';
  await page.getByLabel('Research goal').fill(goal);
  await page.getByRole('button', { name: 'Start research' }).click();
  await expect(page.getByRole('alert')).toContainText('The provider did not respond in time');
  await expect(page.getByRole('alert')).toBeFocused();
  await expect(page.getByLabel('Research goal')).toHaveValue(goal);
  await expect(page.getByRole('button', { name: 'Start research' })).toBeEnabled();
});

test('Strategy Report tabs support keyboard navigation', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Report evidence is available in the completed fixture.');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  const summary = page.getByRole('tab', { name: 'summary', exact: true });
  await summary.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'candidates', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('End');
  await expect(page.getByRole('tab', { name: 'audit', exact: true })).toHaveAttribute('aria-selected', 'true');
});

test('Strategy Report summary reuses persisted performance and keeps candidate tabs linked', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Report linkage uses the completed deterministic fixture.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Retained development performance' })).toBeVisible();
  await expect(page.locator('.quant-report-selection-context')).toContainText('Research hypothesis');
  await expect(page.locator('.quant-report-selection-context')).toContainText('Training selection');
  await expect(page.getByRole('img', { name: 'SMA 50/200 equity compared with benchmark' })).toBeVisible();
  await expect(page.locator('.quant-report-key-metrics')).toContainText('Vs benchmark');
  await page.getByRole('tab', { name: 'candidates', exact: true }).click();
  await page.getByRole('button', { name: 'SMA 20/100' }).click();
  await page.getByRole('tab', { name: 'summary', exact: true }).click();
  await expect(page.getByRole('img', { name: 'SMA 20/100 equity compared with benchmark' })).toBeVisible();
  await page.getByRole('button', { name: 'View trades' }).click();
  await expect(page.locator('.quant-report-panel')).toContainText('SMA 20/100');
  await page.getByRole('tab', { name: 'strategy', exact: true }).click();
  await expect(page.locator('.quant-spec')).toBeVisible();
  await expect(page.locator('.quant-report>header select')).toHaveValue('candidate-a');
  await page.getByRole('tab', { name: 'summary', exact: true }).click();
  await page.getByRole('button', { name: 'Open analysis' }).click();
  await expect(page.getByRole('tab', { name: 'Analysis', exact: true })).toHaveAttribute('aria-selected', 'true');
});

test('completed Report keeps one authoritative final decision, export, and history path', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Terminal decision assertions use the completed deterministic fixture.');
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    const report = snapshot.report as Record<string, unknown>;
    const candidates = snapshot.candidates as Array<Record<string, unknown>>;
    for (const candidate of candidates) candidate.canSeedResearch = candidate.id === 'candidate-b';
    report.selectionDecision = { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' };
    report.generalization = {
      status: 'fail',
      reason: 'The retained sealed holdout did not support the final choice.',
      selectedCandidateId: 'candidate-b',
      split: {
        method: 'chronological', ruleVersion: 'chronological-80-20-v1', trainBarCount: 1_251, holdoutBarCount: 313,
        cutoffDate: '2022-10-03', datasetId: (snapshot.dataset as Record<string, unknown>).id, datasetDigest: (snapshot.dataset as Record<string, unknown>).digest,
      },
    };
  });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  const terminal = page.locator('.quant-terminal-decision').filter({ hasText: 'Final decision' });
  await expect(terminal).toContainText('Final choice');
  await expect(terminal).toContainText('SMA 50/200');
  await expect(terminal).toContainText('Sealed holdout');
  await expect(terminal).toContainText('Failed');
  await expect(terminal).toContainText('Proposed change');
  await expect(terminal).toContainText('Evidence basis');
  await expect(terminal).toContainText('Success / stop condition');
  await expect(terminal.getByRole('button', { name: 'Refine version' })).toBeVisible();
  await expect(page.getByText('Recommended next step', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Run one suggested refinement' })).toHaveCount(0);
  await page.locator('.quant-report>header select').selectOption('candidate-a');
  await expect(terminal).toContainText('SMA 50/200');
  await expect(page.locator('.quant-report-selection-context')).toContainText('Alternative candidate · training evidence');
  const exportRequest = page.waitForRequest((request) => request.url().includes('/strategy-report-exports/preview') && request.postData()?.includes('candidate-b') === true);
  await terminal.getByRole('button', { name: 'Export evidence' }).click();
  await exportRequest;
  await expect(page.getByRole('dialog', { name: 'Strategy Report preview' })).toBeVisible();
  await page.getByRole('button', { name: 'Close' }).click();
  await terminal.getByRole('button', { name: 'Research history' }).click();
  await expect(page.getByRole('table', { name: 'Searchable and filterable research run history' })).toBeVisible();
  await page.setViewportSize({ width: 1024, height: 960 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('exports the selected Strategy Report as server-rendered Markdown', async ({ page }, testInfo) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Report export uses the completed fixture.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    setSeedability(snapshot, true);
    setTerminalFailure(snapshot);
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.locator('.quant-report>header select').selectOption('candidate-a');
  await page.getByRole('button', { name: 'Export selected candidate report' }).click();
  const dialog = page.getByRole('dialog', { name: 'Strategy Report preview' });
  await expect(dialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('Candidate A · SMA 20/100');
  await expect(dialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('## Strategy vs Benchmark');
  await expect(dialog.getByLabel('Rendered Strategy Report Markdown')).not.toContainText('trace');
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await dialog.getByRole('button', { name: 'Copy Markdown' }).click();
  await expect(dialog).toContainText('Markdown copied.');
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain('Candidate A · SMA 20/100');
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Download .md' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('spy-strategy-report-55555555.md');
  const stream = await download.createReadStream();
  let downloaded = '';
  if (stream) for await (const chunk of stream) downloaded += chunk.toString();
  expect(downloaded).toContain('# SPY Strategy Report');
  expect(downloaded).toContain('Candidate A · SMA 20/100');
  await page.screenshot({ path: testInfo.outputPath('strategy-report-export-1440x960.png'), fullPage: true });
  await page.setViewportSize({ width: 1024, height: 960 });
  await expect(dialog.getByRole('button', { name: 'Download .md' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('strategy-report-export-1024x960.png'), fullPage: true });
});

test('exports the opened historical run instead of the latest run', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Historical report export uses retained fixture runs.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  const historicalRow = history.getByRole('row', { name: /Compare slower SPY trend filters/ })
    .filter({ hasText: 'Continued version', hasNotText: 'Retry attempt' });
  await historicalRow.getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.getByRole('button', { name: 'Export report' }).click();
  const preview = page.getByLabel('Rendered Strategy Report Markdown');
  await expect(preview).toContainText('Compare slower SPY trend filters across the same research range.');
  await expect(page.getByRole('dialog', { name: 'Strategy Report preview' })).toContainText('55555555');
});

test('exports the selected and historical Strategy Report as server-rendered Markdown', async ({ page, context }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'Report export uses the completed deterministic fixture.');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.setViewportSize({ width: 1440, height: 960 });
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    setSeedability(snapshot, true);
    setTerminalFailure(snapshot);
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.locator('.quant-report>header select').selectOption('candidate-a');
  await page.getByRole('button', { name: 'Export selected candidate report' }).click();
  const dialog = page.getByRole('dialog', { name: 'Strategy Report preview' });
  await expect(dialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('Candidate A · SMA 20/100');
  await expect(dialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('## Strategy Specification');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/strategy-report-export-1440x960.png', animations: 'disabled' });
  await dialog.getByRole('button', { name: 'Copy Markdown' }).click();
  await expect(dialog).toContainText('Markdown copied.');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('Candidate A · SMA 20/100');
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Download .md' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^spy-strategy-report-[A-Za-z0-9-]+\.md$/);
  const stream = await download.createReadStream();
  const decoder = new TextDecoder();
  let downloadedMarkdown = '';
  for await (const chunk of stream) downloadedMarkdown += decoder.decode(chunk, { stream: true });
  downloadedMarkdown += decoder.decode();
  expect(downloadedMarkdown).toContain('Candidate A · SMA 20/100');

  await dialog.getByRole('button', { name: 'Close' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  const historicalRow = history.getByRole('row', { name: /Compare slower SPY trend filters/ })
    .filter({ hasText: 'Continued version', hasNotText: 'Retry attempt' });
  await historicalRow.getByRole('button', { name: 'Open run' }).click();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Workspace', exact: true }).click();
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.getByRole('button', { name: 'Export report' }).click();
  const historicalDialog = page.getByRole('dialog', { name: 'Strategy Report preview' });
  await expect(historicalDialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('Compare slower SPY trend filters');
  await expect(historicalDialog.getByLabel('Rendered Strategy Report Markdown')).not.toContainText('Which trend strategy best improves risk-adjusted returns?');
  await page.setViewportSize({ width: 1024, height: 960 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/strategy-report-export-1024x960.png', animations: 'disabled' });
});

test('ready fixture completes the API-owned synthetic Agent workflow', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-ready', 'Command flow starts from quant-ready.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByRole('complementary', { name: 'Qurio navigation' }).getByRole('button', { name: 'New research', exact: true }).click();
  const goal = 'Compare a bounded SPY trend hypothesis with synthetic evidence.';
  await page.getByRole('group', { name: 'Research mode' }).getByRole('button', { name: 'Plan first' }).click();
  await page.getByLabel('Research goal').fill(goal);
  await page.getByRole('button', { name: 'Generate plan' }).click();
  const currentResearch = page.getByTestId('quant-sidebar').getByRole('region', { name: 'Current research', exact: true });
  await expect(currentResearch).toContainText('Waiting for plan approval');
  await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).toContainText(goal);
  await page.getByRole('tab', { name: 'Analysis' }).click();
  await page.getByRole('button', { name: 'Approve & run' }).click();
  await expect(page.getByRole('button', { name: 'Advance Offline Run' })).toBeVisible();
  await page.getByRole('button', { name: 'Advance Offline Run' }).click();
  await expect(currentResearch).toContainText('Waiting for review');
  await expect(page.locator('.pq-strategy-chart figcaption')).toContainText('2018-01-02');
  await page.getByRole('button', { name: 'Complete Review' }).click();
  await expect(currentResearch).toContainText('Experiments complete — validation pending');
  await page.reload();
  await expect(page.getByTestId('quant-sidebar').getByRole('region', { name: 'Current research', exact: true })).toContainText('Experiments complete — validation pending');
  await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).toContainText(goal);
});

test('Run Monitor distinguishes the manual offline fixture and keeps legal cancel control while running', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-running', 'Running-state assertions use the loopback fixture API.');
  await rewriteWorkspaceSnapshot(page, (snapshot) => {
    const events = snapshot.events as Array<Record<string, unknown>>;
    events.push(
      {
        id: 'visible-agent-decision',
        sequence: 100,
        type: 'agent.action_selected',
        timestamp: '2026-07-26T00:00:00Z',
        actor: 'agent',
        safeSummary: 'Test Candidate B after Candidate A retained positive training evidence.',
        action: 'run_backtest',
        expectedResult: 'Retained training metrics and trades for Candidate B.',
      },
      {
        id: 'visible-agent-tool-started',
        sequence: 101,
        type: 'tool.started',
        timestamp: '2026-07-26T00:00:01Z',
        actor: 'system',
        safeSummary: 'Training backtest started.',
        action: 'run_backtest',
      },
    );
  });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await expect(page.getByRole('tab', { name: 'Experiments', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.quant-run-monitor h3')).toContainText('Running experiments');
  await expect(page.getByRole('heading', { name: /Testing initial hypothesis b/i })).toBeVisible();
  await expectLiveAgentDecision(page, 'quant-running');
  const latestMove = page.locator('dl[aria-label="Latest Agent move"]');
  await expect(latestMove).toContainText('Test Candidate B after Candidate A retained positive training evidence.');
  await expect(latestMove).toContainText('Run training backtest');
  await expect(latestMove).toContainText('Tool observation · Running');
  await expect(latestMove).toContainText('The tool is running. Qurio has not retained an observation yet.');
  await expect(page.getByRole('table', { name: 'Live candidate experiment progress' })).toContainText('Running');
  const monitor = page.locator('.quant-run-monitor');
  await expect(monitor.getByText('Run Monitor')).toBeVisible();
  await expect(monitor.getByText('Offline fixture · manual step')).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Cancel Run' })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Retry' })).toHaveCount(0);
  await expect(monitor.getByText('Immutable')).toHaveCount(0);
  await expect(monitor.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
  await expect(page.getByText(/Activity & artifacts/)).toBeVisible();
  await expect(page.locator('.quant-activity-feed')).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 1024, height: 960 });
  await expectWorkspaceTabsInsideHeader(page);
  await expectLiveAgentDecision(page, 'quant-running');
  await expectLiveDecisionBeforeCandidateProgress(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('review gate exposes only human-review actions without active polling', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-waiting-review', 'Review-state assertions use the waiting-review fixture.');
  await page.goto('/');
  await expect(page.getByRole('complementary', { name: 'Qurio', exact: true })).not.toContainText('Questions become available');
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const monitor = page.locator('.quant-run-monitor');
  await expect(monitor.getByText('Needs your decision', { exact: true })).toBeVisible();
  await expect(monitor.getByText('Live · polling')).toHaveCount(0);
  await expect(monitor.getByRole('button', { name: 'Open Decision Draft' })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Review Validation Findings' })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Complete Review' })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Cancel Run' })).toHaveCount(0);
});

test('repair and validation fixtures explain active work without implying run failure', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || !['quant-repairing', 'quant-validating'].includes(fixtureState), 'Intermediate-state assertions use repair or validation fixtures.');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  const monitor = page.locator('.quant-run-monitor');
  await expect(monitor.getByText('Running automatically')).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Cancel Run' })).toBeVisible();
  await expect(monitor).not.toContainText('Failed safely');
  if (fixtureState === 'quant-repairing') {
    await expect(monitor.getByRole('heading', { name: 'Repairing candidate' })).toBeVisible();
  } else {
    await expect(monitor.getByRole('heading', { name: 'Validating evidence' })).toBeVisible();
  }
});

test('transient phases show domain progress and open the relevant detail view', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || !['quant-loading-data', 'quant-generating-candidates', 'quant-generating-report'].includes(fixtureState), 'Transient-phase assertions use the generated phase fixtures.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  const progress = page.getByRole('region', { name: 'Current run progress' });
  await expect(progress).toBeVisible();
  await expect(progress.getByText('Completed', { exact: true })).toBeVisible();
  await expect(progress.getByText('Current', { exact: true })).toBeVisible();
  await expect(progress.getByText('Next', { exact: true })).toBeVisible();
  const expected = fixtureState === 'quant-loading-data'
    ? { action: 'View data progress', current: 'Dataset verification', tab: 'Analysis' }
    : fixtureState === 'quant-generating-candidates'
      ? { action: 'View candidate progress', current: 'Candidate preparation', tab: 'Experiments' }
      : { action: 'View report progress', current: 'Report assembly', tab: 'Analysis' };
  await expect(progress.getByText(expected.current, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 1024, height: 960 });
  await expect(progress).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole('button', { name: expected.action, exact: true }).click();
  await expect(page.getByRole('tab', { name: expected.tab, exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.quant-run-monitor').getByText('Running automatically')).toBeVisible();
});

test('negative and cancelled terminal outcomes expose only relevant next actions', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || !['quant-no-viable-candidate', 'quant-cancelled'].includes(fixtureState), 'Terminal edge assertions use no-viable or cancelled fixtures.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  const inspectRun = page.getByRole('button', { name: 'Inspect run' });
  await expect(inspectRun).toHaveCount(fixtureState === 'quant-cancelled' ? 1 : 0);
  await expect(page.getByRole('button', { name: 'Review evidence' })).toHaveCount(0);
  if (fixtureState === 'quant-no-viable-candidate') await expect(page.getByRole('button', { name: 'New research', exact: true }).first()).toBeVisible();
  if (fixtureState === 'quant-cancelled') {
    await inspectRun.click();
    await expect(page.getByRole('tab', { name: 'Analysis', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('.quant-run-monitor').getByText('Run details')).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 1024, height: 960 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const monitor = page.locator('.quant-run-monitor');
  await expect(monitor.getByText('Immutable', { exact: true })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Cancel Run' })).toHaveCount(0);
  if (fixtureState === 'quant-no-viable-candidate') {
    await expect(monitor.getByRole('button', { name: 'Open Decision' })).toBeVisible();
    await expect(monitor.getByRole('button', { name: 'Compare Candidates' })).toBeVisible();
    await expect(monitor.getByRole('button', { name: 'Retry as New Attempt' })).toHaveCount(0);
  } else {
    await expect(monitor.getByRole('button', { name: 'Retry as New Attempt' })).toBeVisible();
    await expect(monitor.getByRole('button', { name: 'Open Diagnostics' })).toHaveCount(0);
  }
});

test('Run Monitor marks terminal runs as immutable without polling controls', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || !['quant-completed', 'quant-no-viable-candidate', 'quant-failed-safe', 'quant-cancelled'].includes(fixtureState), 'Terminal-state assertions apply to terminal fixtures.');
  await page.goto('/');
  const monitor = page.locator('.quant-run-monitor');
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(monitor.getByText('Immutable', { exact: true })).toBeVisible();
  await expect(monitor.getByText('Live · polling')).toHaveCount(0);
  await expect(monitor.getByRole('progressbar')).toHaveCount(0);
  await expect(monitor.getByText('Run details')).toBeVisible();
});

test('Run Monitor surfaces retry and diagnostics only when legal for failed runs', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-failed-safe', 'Retry/diagnostics assertions use the failed fixture.');
  await page.goto('/');
  const monitor = page.locator('.quant-run-monitor');
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(monitor.getByRole('button', { name: 'Retry as New Attempt' })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Open Diagnostics' })).toBeVisible();
  await expect(monitor.getByRole('button', { name: 'Cancel Run' })).toHaveCount(0);
});

test('a terminal attempt creates a new API-owned Project and Run', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed' || Boolean(quantFailure), 'New Run creation requires the completed success fixture.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'New research', exact: true }).click();
  const goal = 'Start a fresh API-owned SPY trend research run.';
  await page.getByLabel('Research goal').fill(goal);
  await page.getByRole('button', { name: 'Generate plan' }).click();
  await expect(page.getByTestId('quant-sidebar').getByRole('region', { name: 'Current research', exact: true })).toContainText('Waiting for plan approval');
});

test('captures a real workbench screenshot when explicitly enabled', async ({ page }) => {
  test.skip(process.env.POKIEQUANT_CAPTURE_SCREENSHOTS !== '1', 'Screenshot capture is an explicit reviewed workflow.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'SPY Research' })).toBeVisible();
  await page.screenshot({
    path: `../../docs/assets/pokiequant/${fixtureState}.png`,
    fullPage: false,
    animations: 'disabled',
  });
  if (fixtureState === 'quant-ready') return;
  if (fixtureState === 'quant-completed') {
    await page.setViewportSize({ width: 1024, height: 960 });
    await expect(page.getByRole('heading', { name: 'Strategy vs benchmark' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({
      path: '../../docs/assets/pokiequant/quant-completed-1024x960.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.setViewportSize({ width: 1440, height: 960 });
  }
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  await page.screenshot({
    path: `../../docs/assets/pokiequant/${fixtureState}-experiments.png`,
    fullPage: false,
    animations: 'disabled',
  });
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await page.screenshot({
    path: `../../docs/assets/pokiequant/${fixtureState}-analysis.png`,
    fullPage: false,
    animations: 'disabled',
  });
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await page.screenshot({
    path: `../../docs/assets/pokiequant/${fixtureState}-report.png`,
    fullPage: false,
    animations: 'disabled',
  });
  if (fixtureState === 'quant-completed') {
    await page.screenshot({
      path: '../../docs/assets/pokiequant/quant-completed-report-1440x960.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.setViewportSize({ width: 1024, height: 960 });
    await expect(page.getByRole('heading', { name: 'Retained development performance' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({
      path: '../../docs/assets/pokiequant/quant-completed-report-1024x960.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.setViewportSize({ width: 1440, height: 960 });
  }
  if (fixtureState === 'quant-running') {
    await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
    await page.screenshot({
      path: '../../docs/assets/pokiequant/quant-running-live-1440x960.png',
      fullPage: false,
      animations: 'disabled',
    });
    await page.setViewportSize({ width: 1024, height: 960 });
    await expectWorkspaceTabsInsideHeader(page);
    await expectLiveAgentDecision(page, 'quant-running');
    await expectLiveDecisionBeforeCandidateProgress(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({
      path: '../../docs/assets/pokiequant/quant-running-live-1024x960.png',
      fullPage: false,
      animations: 'disabled',
    });
  }
});

test('public 4h market data completes the existing Data to Research to History workflow', async ({ page, context }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'C4 uses a deterministic public-v2 API fixture; it is not a live-provider claim.');
  test.slow();
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') browserErrors.push(message.text()); });
  const noPageOverflow = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  const importer = page.getByRole('tabpanel', { name: 'Binance Spot' });
  await importer.getByLabel('Binance Spot interval').selectOption('4h');
  await importer.getByLabel('Binance Spot bar limit').fill('4386');
  const fetchRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/datasets/v2/fetch-binance') && request.method() === 'POST');
  await importer.getByRole('button', { name: 'Fetch and validate' }).click();
  expect((await fetchRequest).postDataJSON()).toMatchObject({
    name: 'BTCUSDT Binance Spot 4 hour',
    symbol: 'BTCUSDT',
    interval: '4h',
    limit: 4386,
  });
  const catalog = page.getByRole('table', { name: 'Available research datasets' });
  const marketRow = catalog.getByRole('row', { name: /BTCUSDT Binance Spot 4 hour/ });
  await expect(marketRow).toContainText('4h');
  await expect(marketRow).toContainText('Verified');
  await marketRow.getByRole('button', { name: 'Preview' }).click();
  const preview = page.locator('.quant-dataset-preview');
  await expect(preview.getByRole('heading', { name: 'BTCUSDT · 4h' }).first()).toBeVisible();
  await expect(preview.getByRole('img', { name: 'BTCUSDT 4h price and volume chart' })).toBeVisible();
  await expect(preview).toContainText('4,386');
  await noPageOverflow();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/c4-market-data-preview-1440x960.png', animations: 'disabled' });

  await page.setViewportSize({ width: 1024, height: 960 });
  await noPageOverflow();
  await expect(preview.getByRole('button', { name: 'Use for research' })).toBeVisible();
  await preview.getByRole('button', { name: 'Use for research' }).click();
  await expect(page.getByRole('heading', { name: 'New research' })).toBeVisible();
  await expect(page.getByLabel('Research dataset')).toHaveValue('66666666-6666-4666-8666-666666666604');
  await expect(page.getByLabel('Research start UTC')).toHaveValue('2024-01-01T00:00');
  await expect(page.getByLabel('Research end UTC')).toHaveValue('2025-12-31T20:00');
  await expect(page.getByText('2,190 periods/year', { exact: true })).toBeVisible();
  await noPageOverflow();
  await page.getByLabel('Research start UTC').fill('2024-03-01T00:00');
  await page.setViewportSize({ width: 1440, height: 960 });
  const question = 'Research simple interpretable BTCUSDT 4h strategies that improve drawdown while retaining positive return.';
  await page.getByLabel('Research goal').fill(question);
  const createResponse = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate plan' }).click();
  const created = await createResponse;
  expect(created.ok()).toBe(true);
  const rootPayload = created.request().postDataJSON();
  expect(rootPayload).toMatchObject({ dataset_id: '66666666-6666-4666-8666-666666666604', mode: 'plan', research_start_utc: '2024-03-01T00:00:00Z', research_end_utc: '2025-12-31T20:00:00+00:00' });
  expect(rootPayload.research_loop).toBeUndefined();
  expect(await created.json()).toMatchObject({ id: '77777777-7777-4777-8777-777777777704', parent_run_id: null, seed_candidate_id: null, retry_of_run_id: null });
  const approveResponse = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs/77777777-7777-4777-8777-777777777704/approve-plan') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Approve & Run' }).click();
  expect((await approveResponse).ok()).toBe(true);
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  await expectLiveAgentDecision(page, 'quant-running');
  await expect(page.locator('.pq-live-research')).toContainText(question);
  await expect(page.getByRole('button', { name: 'Advance Offline Run' })).toHaveCount(0);
  await expect.poll(async () => page.locator('.quant-run-monitor h3').textContent(), { timeout: 12_000 }).toContain('Research concluded');

  const rootDecision = page.locator('.pq-agent-decision-chain.is-completed');
  const rootComparison = page.locator('.pq-candidate-comparison.is-full');
  await expect(rootDecision).toContainText('Observation → Why Qurio changed → Next action');
  await expect(rootDecision).toContainText('Widen the breakout window after the initial training comparison.');
  await expect(rootDecision).toContainText(/Final training choice[\s\S]*SMA 50\/200[\s\S]*Approved comparison objective/);
  await rootComparison.getByRole('button', { name: '200-day breakout' }).click();
  await expect(page.getByText('Inspecting strategy · 200-day breakout', { exact: true })).toBeVisible();
  await expect(rootDecision).toContainText(/Final training choice[\s\S]*SMA 50\/200[\s\S]*Approved comparison objective/);
  await rootComparison.getByRole('button', { name: 'SMA 50/200' }).click();

  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const completionNotice = page.getByRole('button', { name: 'Dismiss notification' });
  if (await completionNotice.isVisible()) await completionNotice.click();
  const marketCopilot = page.getByRole('complementary', { name: 'Qurio', exact: true });
  await marketCopilot.getByText('Run details', { exact: true }).click();
  await expect(marketCopilot).toContainText('StateCompleted');
  await expect(marketCopilot).toContainText('Plan10 / 10 complete');
  await expect(marketCopilot).toContainText('DatasetBTCUSDT · 4h');
  await expect(marketCopilot).toContainText('4h · 2,190 PPY');
  await expect(marketCopilot).toContainText('2024-03-01T00:00:00Z');

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(page.getByRole('group', { name: /Inspect .* equity performance/ })).toBeVisible();
  await expect(page.locator('.pq-strategy-inspection time')).toHaveAttribute('datetime', '2025-12-15T04:00:00+00:00');
  await expect(page.locator('.pq-strategy-inspection')).toContainText('15 Dec 2025, 04:00 UTC');
  await expect(page.locator('.pq-strategy-chart figcaption time').first()).toHaveAttribute('datetime', '2024-03-01T00:00:00+00:00');
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  await expect(page.getByText('2 bars · 8h').first()).toBeVisible();
  await noPageOverflow();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/c4-market-analysis-1440x960.png', animations: 'disabled' });
  await page.setViewportSize({ width: 1024, height: 960 });
  await expectTradesToFitInitialViewport(page);
  await expect(page.getByText('2 bars · 8h').first()).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 960 });

  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.getByText(/persisted 4h performance/)).toBeVisible();
  await expect(page.getByText(/4h · 2,190 periods\/year/)).toBeVisible();
  await page.getByRole('button', { name: 'Export evidence' }).click();
  const exportDialog = page.getByRole('dialog', { name: 'Strategy Report preview' });
  await expect(exportDialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('BTCUSDT · 4h');
  await expect(exportDialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('2024-03-01T00:00:00Z');
  await expect(exportDialog.getByLabel('Rendered Strategy Report Markdown')).toContainText('2 bars · 8h');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await exportDialog.getByRole('button', { name: 'Copy Markdown' }).click();
  await expect(exportDialog).toContainText('Markdown copied.');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('BTCUSDT · 4h');
  const downloadPromise = page.waitForEvent('download');
  await exportDialog.getByRole('button', { name: 'Download .md' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('btcusdt-strategy-report-77777777.md');
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/c4-market-report-export-1440x960.png', animations: 'disabled' });
  await exportDialog.getByRole('button', { name: 'Close' }).click();

  const refinementReason = 'Retain candidate-b and test one slower drawdown-controlled follow-up.';
  const childQuestion = 'Continue BTCUSDT 4h research from candidate-b with one slower trend adaptation.';
  await page.getByRole('button', { name: 'Refine version' }).click();
  await expect(page.getByRole('heading', { name: 'Refine research' })).toBeVisible();
  await expect(page.getByLabel('Research dataset')).toBeDisabled();
  await expect(page.getByLabel('Research dataset')).toHaveValue('66666666-6666-4666-8666-666666666604');
  await expect(page.getByLabel('Research start UTC')).toHaveValue('2024-03-01T00:00');
  await expect(page.getByLabel('Research end UTC')).toHaveValue('2025-12-31T20:00');
  await page.getByLabel('Research goal').fill(childQuestion);
  await page.getByLabel('Refinement reason').fill(refinementReason);
  const childResponsePromise = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate next plan' }).click();
  const childResponse = await childResponsePromise;
  expect(childResponse.ok()).toBe(true);
  expect(childResponse.request().postDataJSON()).toMatchObject({
    dataset_id: '66666666-6666-4666-8666-666666666604',
    mode: 'plan',
    research_start_utc: '2024-03-01T00:00:00Z',
    research_end_utc: '2025-12-31T20:00:00+00:00',
    parent_run_id: '77777777-7777-4777-8777-777777777704',
    seed_candidate_id: 'candidate-b',
    refinement_reason: refinementReason,
  });
  expect(await childResponse.json()).toMatchObject({
    id: '77777777-7777-4777-8777-777777777708',
    parent_run_id: '77777777-7777-4777-8777-777777777704',
    seed_candidate_id: 'candidate-b',
    attempt_number: 1,
    retry_of_run_id: null,
  });
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await expect(page.getByLabel('Research plan awaiting approval')).toBeVisible();
  const approveChildResponse = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs/77777777-7777-4777-8777-777777777708/approve-plan') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Approve & Run' }).click();
  expect((await approveChildResponse).ok()).toBe(true);
  await expect.poll(async () => page.locator('.quant-run-monitor h3').textContent(), { timeout: 12_000 }).toContain('Experiments complete — validation pending');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.locator('.quant-report')).toContainText('Continued from source version');
  await expect(page.locator('.quant-report')).toContainText('Source candidate: Candidate B · SMA 50/200');
  await expect(page.locator('.quant-report')).toContainText(`Reason: ${refinementReason}`);
  await expect(page.locator('.quant-report')).toContainText('Sealed-holdout evidence is withheld');

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const retryResponsePromise = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs/77777777-7777-4777-8777-777777777708/retry') && response.request().method() === 'POST');
  await page.locator('.quant-run-monitor').getByRole('button', { name: 'Retry as New Attempt' }).click();
  const retryResponse = await retryResponsePromise;
  expect(retryResponse.ok()).toBe(true);
  expect(await retryResponse.json()).toMatchObject({
    id: '77777777-7777-4777-8777-777777777709',
    parent_run_id: '77777777-7777-4777-8777-777777777704',
    seed_candidate_id: 'candidate-b',
    attempt_number: 2,
    retry_of_run_id: '77777777-7777-4777-8777-777777777708',
  });
  await expect.poll(async () => page.locator('.quant-run-monitor h3').textContent(), { timeout: 12_000 }).toContain('Experiments complete — validation pending');
  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.locator('.quant-report')).toContainText('Continued from source version');
  await expect(page.locator('.quant-report')).toContainText('Retry attempt 2');
  await expect(page.locator('.quant-report')).toContainText('Sealed-holdout evidence is withheld');

  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('table', { name: 'Searchable and filterable research run history' });
  const rootRow = history.getByRole('row').filter({ hasText: question }).filter({ hasText: 'Root version' });
  const childRow = history.getByRole('row').filter({ hasText: childQuestion }).filter({ hasText: 'Continued version', hasNotText: 'Retry attempt' });
  const retryRow = history.getByRole('row').filter({ hasText: childQuestion }).filter({ hasText: 'Continued version · Retry attempt 2' });
  await expect(rootRow).toContainText('BTCUSDT · 4h');
  await expect(childRow).toContainText('BTCUSDT · 4h');
  await expect(retryRow).toContainText('BTCUSDT · 4h');
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/c4-market-runs-1440x960.png', animations: 'disabled' });

  const rootSnapshotRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/runs/77777777-7777-4777-8777-777777777704/workspace-snapshot'));
  await rootRow.getByRole('button', { name: 'Open run' }).click();
  await rootSnapshotRequest;
  await expect(page.getByRole('heading', { name: 'BTCUSDT 4h Research' })).toBeVisible();
  await expect(page.getByText('Historical run', { exact: true })).toBeVisible();
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  await expect(history.locator('tr.is-current')).toContainText('Root version');

  const childSnapshotResponsePromise = page.waitForResponse((response) => response.url().endsWith('/v1/quant/runs/77777777-7777-4777-8777-777777777708/workspace-snapshot'));
  await childRow.getByRole('button', { name: 'Open run' }).click();
  const childSnapshotResponse = await childSnapshotResponsePromise;
  const childSnapshot = await childSnapshotResponse.json();
  const childGeneralization = childSnapshot.report.generalization;
  expect(childGeneralization).toMatchObject({
    status: 'not_evaluated',
    split: {
      ruleVersion: 'chronological-80-20-v1',
      trainBarCount: expect.any(Number),
      holdoutBarCount: expect.any(Number),
    },
  });
  expect(childGeneralization.split.trainBarCount).toBeGreaterThan(0);
  expect(childGeneralization.split.holdoutBarCount).toBeGreaterThan(0);
  expect(childGeneralization.split.trainBarCount + childGeneralization.split.holdoutBarCount).toBe(childSnapshot.dataset.barCount);
  expect(childGeneralization.holdout ?? null).toBeNull();
  await page.getByRole('button', { name: 'Open decision' }).click();
  await expect(page.locator('.quant-report')).toContainText('Continued from source version');
  await expect(page.locator('.quant-report')).not.toContainText('Retry attempt 2');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();

  await retryRow.getByRole('button', { name: 'Open run' }).click();
  await page.getByRole('button', { name: 'Open decision' }).click();
  await expect(page.locator('.quant-report')).toContainText('Continued from source version');
  await expect(page.locator('.quant-report')).toContainText('Retry attempt 2');
  const fixtureApiPort = process.env.GLINT_FIXTURE_PORT ?? '4174';
  const fixtureAppPort = process.env.GLINT_E2E_APP_PORT ?? '5174';
  const retrySnapshotResponse = await page.request.get(`http://127.0.0.1:${fixtureApiPort}/v1/quant/runs/77777777-7777-4777-8777-777777777709/workspace-snapshot`, {
    headers: {
      Authorization: `Bearer ${process.env.GLINT_E2E_ACCESS_TOKEN ?? 'fixture-access-token'}`,
      Origin: `http://127.0.0.1:${fixtureAppPort}`,
      'X-Workspace-ID': '00000000-0000-4000-8000-000000000001',
    },
  });
  expect(retrySnapshotResponse.ok()).toBe(true);
  const retrySnapshot = await retrySnapshotResponse.json();
  expect(retrySnapshot).toMatchObject({
    run: {
      id: '77777777-7777-4777-8777-777777777709',
      attemptNumber: 2,
      retryOfRunId: '77777777-7777-4777-8777-777777777708',
      continuedFrom: {
        parentRunId: '77777777-7777-4777-8777-777777777704',
        seedCandidateId: 'candidate-b',
      },
    },
  });
  const retryGeneralization = retrySnapshot.report.generalization;
  expect(retryGeneralization).toMatchObject({
    status: 'not_evaluated',
    split: {
      ruleVersion: 'chronological-80-20-v1',
      trainBarCount: expect.any(Number),
      holdoutBarCount: expect.any(Number),
    },
  });
  expect(retryGeneralization.split.trainBarCount).toBeGreaterThan(0);
  expect(retryGeneralization.split.holdoutBarCount).toBeGreaterThan(0);
  expect(retryGeneralization.split.trainBarCount + retryGeneralization.split.holdoutBarCount).toBe(retrySnapshot.dataset.barCount);
  expect(retryGeneralization.holdout ?? null).toBeNull();

  await page.setViewportSize({ width: 1024, height: 960 });
  await noPageOverflow();
  await expect(page.getByRole('tab', { name: 'Decision', exact: true })).toBeVisible();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/c4-market-report-1024x960.png', animations: 'disabled' });
  expect(browserErrors).toEqual([]);
});

test('public 1h market data preserves intraday points through Analysis, Report, and History', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'C4 1h evidence uses a deterministic public-v2 API fixture; it is not a live-provider claim.');
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') browserErrors.push(message.text()); });
  const noPageOverflow = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  const hourlyRow = page.getByRole('table', { name: 'Available research datasets' }).getByRole('row', { name: /BTCUSDT Binance Spot 1 hour/ });
  await expect(hourlyRow).toContainText('1h');
  await hourlyRow.getByRole('button', { name: 'Preview' }).click();
  const preview = page.locator('.quant-dataset-preview');
  await expect(preview.getByRole('heading', { name: 'BTCUSDT · 1h' }).first()).toBeVisible();
  await expect(preview).toContainText('5,000');
  await preview.getByRole('button', { name: 'Use for research' }).click();
  await expect(page.getByLabel('Research dataset')).toHaveValue('66666666-6666-4666-8666-666666666601');
  await expect(page.getByLabel('Research start UTC')).toHaveValue('2024-01-01T00:00');
  await expect(page.getByLabel('Research end UTC')).toHaveValue('2024-07-27T07:00');
  await expect(page.getByText('8,760 periods/year', { exact: true })).toBeVisible();

  const question = 'Research interpretable BTCUSDT 1h strategies without collapsing intraday observations.';
  await page.getByLabel('Research goal').fill(question);
  const createResponse = page.waitForResponse((response) => response.url().endsWith('/v1/quant/market-runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate plan' }).click();
  const created = await createResponse;
  expect(created.ok()).toBe(true);
  const createPayload = created.request().postDataJSON();
  expect(createPayload).toMatchObject({
    dataset_id: '66666666-6666-4666-8666-666666666601',
    mode: 'plan',
    research_start_utc: '2024-01-01T00:00:00+00:00',
    research_end_utc: '2024-07-27T07:00:00+00:00',
  });
  expect(createPayload).not.toHaveProperty('interval');
  const createdJson = await created.json() as { id: string };
  const approveResponse = page.waitForResponse((response) => response.url().endsWith(`/v1/quant/market-runs/${createdJson.id}/approve-plan`) && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Approve & Run' }).click();
  expect((await approveResponse).ok()).toBe(true);
  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  await expect.poll(async () => page.locator('.quant-run-monitor h3').textContent(), { timeout: 12_000 }).toContain('Research concluded');

  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  const completionNotice = page.getByRole('button', { name: 'Dismiss notification' });
  if (await completionNotice.isVisible()) await completionNotice.click();
  const hourlyCopilot = page.getByRole('complementary', { name: 'Qurio', exact: true });
  await hourlyCopilot.getByText('Run details', { exact: true }).click();
  await expect(hourlyCopilot).toContainText('1h · 8,760 PPY');
  await expect(hourlyCopilot).toContainText('2024-01-01T00:00:00+00:00');

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const plot = page.locator('.pq-strategy-analysis .pq-strategy-plot');
  const inspection = page.locator('.pq-strategy-analysis .pq-strategy-inspection');
  await plot.focus();
  await plot.press('Home');
  await expect(inspection.locator('time')).toHaveAttribute('datetime', '2024-01-01T00:00:00+00:00');
  await plot.press('ArrowRight');
  await expect(inspection.locator('time')).toHaveAttribute('datetime', '2024-01-01T01:00:00+00:00');
  await expect(page.locator('.pq-strategy-chart figcaption time').first()).toHaveAttribute('datetime', '2024-01-01T00:00:00+00:00');
  await noPageOverflow();
  if (process.env.POKIEQUANT_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '../../docs/assets/pokiequant/c4-market-1h-analysis-1440x960.png', animations: 'disabled' });

  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await expect(page.getByText(/persisted 1h performance/)).toBeVisible();
  await expect(page.getByText(/1h · 8,760 periods\/year/)).toBeVisible();
  await expect(page.getByText(/2024-01-01T00:00:00\+00:00/).first()).toBeVisible();

  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'History', exact: true }).click();
  const activeRow = page.getByRole('row', { name: new RegExp(question) }).filter({ hasText: 'BTCUSDT · 1h' });
  await expect(activeRow).toContainText('BTCUSDT · 1h');
  await activeRow.getByRole('button', { name: 'Open run' }).click();
  await expect(page.getByRole('heading', { name: 'BTCUSDT 1h Research' })).toBeVisible();
  await page.getByRole('button', { name: 'Open decision' }).click();
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Analysis', exact: true })).toHaveAttribute('aria-selected', 'true');

  await page.setViewportSize({ width: 1024, height: 960 });
  await noPageOverflow();
  await expect(page.locator('.pq-strategy-analysis .pq-strategy-inspection time')).toHaveAttribute('datetime', /2024-.*T\d{2}:00:00\+00:00/);
  expect(browserErrors).toEqual([]);
});

test('public 4h market CSV reaches the exact G1 eligibility threshold and can be selected for research', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'G1 threshold coverage uses the deterministic public-v2 fixture API.');
  const csvText = buildBtcusdt4hCsv(548);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'Add data' }).click();
  await page.getByRole('tab', { name: 'CSV upload' }).click();
  await page.getByLabel('OHLCV CSV file').setInputFiles(csvUpload('btcusdt-4h-threshold.csv', csvText));
  await page.getByLabel('Dataset interval').selectOption('4h');
  await page.getByLabel('Dataset name').fill('BTCUSDT CSV 4 hour threshold');
  await page.getByLabel('Dataset symbol').fill('BTCUSDT');
  await page.getByText('Source metadata', { exact: true }).click();
  await page.getByLabel('Dataset source provider').fill('Research CSV');
  await page.getByLabel('Dataset source reference').fill('upload:btc-4h-threshold');
  const importRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/datasets/v2/import-csv') && request.method() === 'POST');
  const importResponse = page.waitForResponse((response) => response.url().endsWith('/v1/quant/datasets/v2/import-csv') && response.request().method() === 'POST' && response.status() === 201);
  await page.getByRole('button', { name: 'Import and validate' }).click();
  expect((await importRequest).postDataJSON()).toEqual({
    name: 'BTCUSDT CSV 4 hour threshold',
    symbol: 'BTCUSDT',
    interval: '4h',
    csv_text: csvText,
    file_name: 'btcusdt-4h-threshold.csv',
    source_name: 'Research CSV',
    source_reference: 'upload:btc-4h-threshold',
  });
  const importedJson = await (await importResponse).json() as { dataset_id: string };
  const importedDatasetId = importedJson.dataset_id;
  const catalog = page.getByRole('table', { name: 'Available research datasets' });
  const thresholdRow = catalog.getByRole('row', { name: /BTCUSDT CSV 4 hour threshold/ });
  await expect(thresholdRow).toContainText('4h');
  await expect(thresholdRow).toContainText('548');
  const previewResponsePromise = page.waitForResponse((response) => response.url().includes(`/quant/datasets/v2/${importedDatasetId}/preview`) && response.status() === 200);
  await thresholdRow.getByRole('button', { name: 'Preview' }).click();
  const previewResponse = await previewResponsePromise;
  const previewJson = await previewResponse.json() as {
    dataset: {
      dataset_id: string;
      covered_start: string;
      covered_end: string;
      bar_count: number;
      record_digest: string;
      evidence: { submitted_csv_digest: string };
    };
    total_bar_count: number;
    bars: Array<{ timestamp: string; close: string }>;
  };
  expect(previewJson.total_bar_count).toBe(548);
  expect(previewJson.dataset).toMatchObject({
    dataset_id: importedDatasetId,
    covered_start: '2024-01-01T00:00:00+00:00',
    covered_end: '2024-04-01T04:00:00+00:00',
    bar_count: 548,
    evidence: { submitted_csv_digest: expect.stringMatching(/^sha256:[0-9a-f]{64}$/) },
  });
  expect(previewJson.bars.at(-1)).toMatchObject({ timestamp: '2024-04-01T04:00:00+00:00', close: '23071' });
  const preview = page.locator('.quant-dataset-preview');
  await expect(preview.getByRole('heading', { name: 'BTCUSDT · 4h' }).first()).toBeVisible();
  await expect(preview).toContainText('2,190 periods/year');
  await preview.getByRole('button', { name: 'Use for research' }).click();
  await expect(page.getByRole('heading', { name: 'New research' })).toBeVisible();
  await expect(page.getByLabel('Research dataset')).toHaveValue(importedDatasetId);
  await expect(page.getByLabel('Research start UTC')).toHaveValue('2024-01-01T00:00');
  await expect(page.getByLabel('Research end UTC')).toHaveValue('2024-04-01T04:00');
  await expect(page.getByText('2,190 periods/year', { exact: true })).toBeVisible();
});

test.skip('distinct BTCUSDT 1D CSV imports keep isolated content-addressed dataset ids', async () => {
  // Immutable identity and evidence-conflict semantics are covered by
  // api_fixture_contract_test.py against the real response models.
});

test('public 4h PLAN mutations use the dedicated Market Run endpoints', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture' || fixtureState !== 'quant-completed', 'C4 PLAN controls use the deterministic public-v2 API fixture.');
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'New research', exact: true }).click();
  await page.getByLabel('Research dataset').selectOption('66666666-6666-4666-8666-666666666604');
  await page.getByRole('group', { name: 'Research mode' }).getByRole('button', { name: 'Plan first' }).click();
  await page.getByLabel('Research goal').fill('Plan a bounded BTCUSDT 4h trend comparison.');
  const create = page.waitForRequest((request) => request.url().endsWith('/v1/quant/market-runs') && request.method() === 'POST');
  await page.getByRole('button', { name: 'Generate plan' }).click();
  expect((await create).postDataJSON()).toMatchObject({ mode: 'plan', dataset_id: '66666666-6666-4666-8666-666666666604' });
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  const monitor = page.locator('.quant-run-monitor');
  await expect(monitor.getByRole('button', { name: 'Request Changes' })).toBeVisible();
  await monitor.getByRole('button', { name: 'Request Changes' }).click();
  await monitor.getByLabel('What should change in the plan?').fill('Focus the revised plan on mean reversion.');
  const change = page.waitForRequest((request) => request.url().includes('/request-plan-changes'));
  await monitor.getByRole('button', { name: 'Generate revised plan' }).click();
  expect((await change).postDataJSON()).toMatchObject({ expected_row_version: expect.any(Number), plan_revision: 1, change_request: 'Focus the revised plan on mean reversion.' });
  const approve = page.waitForRequest((request) => request.url().includes('/approve-plan'));
  await monitor.getByRole('button', { name: 'Approve & Run' }).click();
  expect((await approve).postDataJSON()).toMatchObject({ plan_revision: 2 });
  const cancel = page.waitForRequest((request) => request.url().endsWith('/cancel'));
  await expect(monitor.getByRole('button', { name: 'Cancel Run' })).toBeVisible();
  await monitor.getByRole('button', { name: 'Cancel Run' }).click();
  await cancel;
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Analysis', exact: true })).toHaveAttribute('aria-selected', 'true');
  const retry = page.waitForRequest((request) => request.url().endsWith('/retry'));
  await expect(monitor.getByRole('button', { name: 'Retry as New Attempt' })).toBeVisible();
  await monitor.getByRole('button', { name: 'Retry as New Attempt' }).click();
  const retryRequest = await retry;
  const retryResponse = await retryRequest.response();
  expect(retryResponse?.ok()).toBe(true);
  expect(await retryResponse?.json()).toMatchObject({ attempt_number: 2, retry_of_run_id: expect.any(String) });
  await expect(page.getByText('New attempt created', { exact: true })).toBeVisible();
});
