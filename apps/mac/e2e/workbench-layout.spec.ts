import { expect, test } from './fixture-test';

declare const process: { env: Record<string, string | undefined> };

test('PokieQuant keeps the workbench contiguous and stacks evidence at compact width', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Layout coverage uses the deterministic PokieQuant fixture.');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  const overview = page.locator('.pq-overview-main');
  const copilot = page.getByRole('complementary', { name: 'Research Copilot' });
  await expect(overview).toBeVisible();
  await expect(copilot).toBeVisible();
  await expect(copilot.getByText('Current', { exact: true })).toBeVisible();
  await expect(copilot.getByText('Observation', { exact: true })).toBeVisible();
  await expect(copilot.getByText('Next', { exact: true })).toBeVisible();
  await expect(copilot.getByText('Run details', { exact: true })).toBeVisible();
  const [overviewBox, copilotBox] = await Promise.all([overview.boundingBox(), copilot.boundingBox()]);
  expect(overviewBox).not.toBeNull();
  expect(copilotBox).not.toBeNull();
  expect(Math.abs((overviewBox?.x ?? 0) + (overviewBox?.width ?? 0) - (copilotBox?.x ?? 0))).toBeLessThanOrEqual(1);
  for (const selector of ['.quant-decision-gate.is-overview', '.pq-results-performance', '.pq-validation-summary']) {
    await expect(page.locator(selector)).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  }
  await expect(page.getByRole('heading', { name: 'Strategy vs benchmark' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Candidate snapshot' })).toBeVisible();

  await page.setViewportSize({ width: 1280, height: 720 });
  const clippedCandidateFacts = await page.locator('.pq-key-comparison dt,.pq-key-comparison dd,.pq-validation-summary dt,.pq-validation-summary dd').evaluateAll((elements) => elements.filter((element) => element.scrollWidth > element.clientWidth).map((element) => element.textContent));
  expect(clippedCandidateFacts).toEqual([]);

  await page.setViewportSize({ width: 1024, height: 960 });
  await expect(copilot).toHaveCount(0);
  const compactCopilot = page.locator('.pq-copilot-content.is-compact');
  await expect(compactCopilot).toBeVisible();
  await expect(compactCopilot.getByText('Current', { exact: true })).toBeVisible();
  await expect(compactCopilot.getByText('Observation', { exact: true })).toBeVisible();
  await expect(compactCopilot.getByText('Next', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  await expect(page.locator('.pq-strategy-lab')).toHaveCSS('background-color', 'rgb(26, 26, 31)');
  for (const control of await page.locator('.quant-chart-controls button,.quant-market-events button').all()) {
    expect((await control.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(28);
  }

  await page.setViewportSize({ width: 980, height: 800 });
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await expect(page.locator('.quant-compact-stack')).toBeVisible();
  await expect(page.locator('.quant-run-monitor')).toBeVisible();
});

test('utility pages use intentional width classes without split-column gaps', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Layout coverage uses the deterministic PokieQuant fixture.');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  await page.getByRole('button', { name: 'Runs', exact: true }).click();
  const runsFrame = page.locator('.pq-utility-frame.is-runs');
  const runsCenter = runsFrame.locator('.pq-utility-center');
  await expect(runsFrame).toBeVisible();
  await expect(runsFrame.getByRole('complementary')).toHaveCount(0);
  const [runsGridBox, runsCenterBox] = await Promise.all([
    runsFrame.locator('.pq-utility-grid').boundingBox(),
    runsCenter.boundingBox(),
  ]);
  expect(runsGridBox).not.toBeNull();
  expect(runsCenterBox).not.toBeNull();
  expect(Math.abs((runsGridBox?.width ?? 0) - (runsCenterBox?.width ?? 0))).toBeLessThanOrEqual(1);
  const runList = runsFrame.locator('.quant-run-list');
  const [runListBox, runTitleBox, runCountBox] = await Promise.all([
    runList.boundingBox(),
    runList.locator('.quant-run-question').first().boundingBox(),
    runList.locator(':scope > header strong').boundingBox(),
  ]);
  expect(runListBox).not.toBeNull();
  expect((runTitleBox?.x ?? 0) - (runListBox?.x ?? 0)).toBeGreaterThanOrEqual(12);
  expect((runCountBox?.x ?? 0) - (runListBox?.x ?? 0)).toBeGreaterThanOrEqual(8);
  await expect(runsFrame.locator('.quant-runs-table tbody tr.is-current')).toHaveCSS('background-color', 'rgb(29, 29, 34)');
  for (const selector of ['.quant-run-summary>.quant-decision-gate', '.quant-run-summary>.pq-evaluation-path']) {
    await expect(runsFrame.locator(selector)).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  }

  await page.getByRole('button', { name: 'Data', exact: true }).click();
  for (const selector of ['.quant-data-directory-table', '.quant-data-directory-table tbody tr', '.pq-utility-card']) {
    await expect(page.locator(selector).first()).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  }
  await expect(page.locator('.pq-utility-card').first()).toHaveCSS('border-left-width', '0px');

  await page.getByRole('button', { name: 'Runtime & policy', exact: true }).click();
  const settingsGrid = page.locator('.pq-utility-frame.is-settings .pq-utility-grid');
  const settingsContent = page.locator('.quant-settings-content');
  const [settingsGridBox, settingsContentBox] = await Promise.all([
    settingsGrid.boundingBox(),
    settingsContent.boundingBox(),
  ]);
  expect(settingsGridBox).not.toBeNull();
  expect(settingsContentBox).not.toBeNull();
  expect(settingsContentBox?.width ?? 0).toBeLessThanOrEqual(900);
  expect(Math.abs(
    (settingsGridBox?.x ?? 0) + (settingsGridBox?.width ?? 0) / 2
      - ((settingsContentBox?.x ?? 0) + (settingsContentBox?.width ?? 0) / 2),
  )).toBeLessThanOrEqual(1);
});
