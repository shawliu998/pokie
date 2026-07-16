import { test, expect } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

test('strict API mode covers CSV → Signal → SSE/reviews → Brief → terminal export and P2 health', async ({ page, request }) => {
  test.setTimeout(180_000);
  const fixtureMode = process.env.GLINT_E2E_API_MODE === 'fixture';
  const apiUrl = fixtureMode
    ? process.env.GLINT_E2E_API_URL ?? 'http://127.0.0.1:4174'
    : process.env.GLINT_E2E_API_URL ?? process.env.VITE_GLINT_API_URL;
  const workspaceId = fixtureMode
    ? process.env.GLINT_E2E_WORKSPACE_ID ?? '00000000-0000-4000-8000-000000000001'
    : process.env.GLINT_E2E_WORKSPACE_ID ?? process.env.VITE_GLINT_WORKSPACE_ID;
  const accessToken = fixtureMode
    ? process.env.GLINT_E2E_ACCESS_TOKEN ?? 'fixture-access-token'
    : process.env.GLINT_E2E_ACCESS_TOKEN ?? process.env.VITE_GLINT_ACCESS_TOKEN;
  const captureDir = process.env.GLINT_E2E_CAPTURE_DIR;
  const capture = async (name: string) => {
    if (captureDir) await page.screenshot({ path: `${captureDir}/${name}.png`, fullPage: true });
  };
  if (!apiUrl || !workspaceId || !accessToken) throw new Error('The strict E2E spec requires the configured API base, workspace, and access token; fixture fallback is only allowed in explicit fixture mode.');
  const unauthenticated = await request.get(`${apiUrl}/v1/sync/bootstrap`, { headers: { 'X-Workspace-ID': workspaceId } });
  expect(unauthenticated.ok()).toBe(false);

  if (fixtureMode) await page.addInitScript(() => {
    let copyAttempts = 0;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (markdown: string) => { copyAttempts += 1; if (copyAttempts === 1) throw new Error('Fixture clipboard rejection.'); Reflect.set(globalThis, '__copiedMarkdown', markdown); } } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Monitoring' }).click();

  if (fixtureMode) {
    await expect(page.getByLabel('Glint GitHub GitHub owner')).toHaveValue('openai');
    await expect(page.getByLabel('Glint GitHub GitHub repository')).toHaveValue('glint');
    await expect(page.getByText('PARTIAL_DISCUSSIONS_SCOPE')).toBeVisible();
    await expect(page.getByLabel('Competitor release RSS RSS feed URL')).toHaveValue('https://example.com/releases.xml');
    await expect(page.getByRole('heading', { name: 'Competitor release RSS' }).locator('..')).toContainText('Freshness: never · last success Never');
  } else {
    await expect(page.getByRole('heading', { name: 'P1 Acceptance CSV' })).toBeVisible();
  }
  await capture('01-monitoring');

  await page.getByRole('button', { name: 'Create cloud source' }).click();
  let createdGithub = page.getByRole('article', { name: 'Product feedback GitHub source' });
  await expect(createdGithub).toContainText('draft');
  await createdGithub.getByLabel('Product feedback GitHub configuration name').fill('Configured product feedback GitHub');
  await createdGithub.getByRole('button', { name: 'Save Product feedback GitHub configuration' }).click();
  createdGithub = page.getByRole('article', { name: 'Configured product feedback GitHub source' });
  await expect(createdGithub.getByLabel('Configured product feedback GitHub GitHub repository')).toHaveValue('glint-ui-contracts');
  await createdGithub.getByLabel('Configured product feedback GitHub schedule Watchlist').selectOption({
    label: fixtureMode ? 'Permission friction watchlist' : 'P1 Acceptance Watchlist',
  });
  await createdGithub.getByRole('button', { name: 'Activate Configured product feedback GitHub' }).click();
  await expect(createdGithub).toContainText('validating');
  await expect(createdGithub).toContainText('source will be bound before schedule creation');
  await createdGithub.getByRole('button', { name: 'Schedule Configured product feedback GitHub' }).click();
  await expect(createdGithub.getByText('scheduled')).toBeVisible();
  await createdGithub.getByRole('button', { name: 'Pause Configured product feedback GitHub schedule' }).click();
  await expect(createdGithub.getByText('paused')).toBeVisible();
  await createdGithub.getByRole('button', { name: 'Enable Configured product feedback GitHub schedule' }).click();
  await expect(createdGithub.getByText('scheduled')).toBeVisible();
  await createdGithub.getByRole('button', { name: 'Check Configured product feedback GitHub health' }).click();
  await expect(page.getByText('Configured product feedback GitHub health validation completed.')).toBeVisible();
  await createdGithub.getByRole('button', { name: 'Reconnect Configured product feedback GitHub' }).click();
  await expect(page.getByText('Configured product feedback GitHub reconnect validation completed.')).toBeVisible();
  await createdGithub.getByRole('button', { name: 'Disable Configured product feedback GitHub' }).click();
  await expect(createdGithub).toContainText('disabled');

  await page.getByLabel('Cloud connector').selectOption('rss');
  await page.getByLabel('Cloud source name').fill('Created product RSS');
  await page.getByRole('button', { name: 'Create cloud source' }).click();
  await expect(page.getByRole('article', { name: 'Created product RSS source' }).getByLabel('Created product RSS RSS feed URL')).toHaveValue('https://example.com/product-releases.xml');

  await page.getByLabel('Destination source').selectOption({ label: fixtureMode ? 'Customer feedback CSV' : 'P1 Acceptance CSV' });
  await page.getByLabel('CSV file').setInputFiles('e2e/fixtures/feedback.csv');
  await page.getByRole('button', { name: 'Review upload scope' }).click();
  const review = page.getByRole('region', { name: 'Upload scope review' });
  await expect(review).toBeVisible();
  await expect(review.getByText(workspaceId)).toBeVisible();
  await page.getByRole('button', { name: 'Create metadata session' }).click();
  await expect(page.getByText(/metadata-only ImportSession created/i)).toBeVisible();
  if (fixtureMode) {
    const importState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(importState).toMatchObject({ consent_preview_count: 0, consent_grant_attempts: 0, consent_grant_count: 0, upload_count: 0 });
  }
  await page.getByRole('button', { name: 'Preview consent scope' }).click();
  const consent = page.getByRole('region', { name: 'Exact consent preview' });
  await expect(consent).toContainText(workspaceId);
  await expect(consent).toContainText('imports/');
  await expect(consent).toContainText('text/csv');
  await expect(consent).toContainText('Model egress');
  await expect(consent).toContainText('none · import-transfer-v1');
  if (fixtureMode) {
    let importState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(importState).toMatchObject({ consent_preview_count: 1, consent_grant_attempts: 0, consent_grant_count: 0, upload_count: 0 });
    await page.getByRole('button', { name: 'Confirm scoped upload grant' }).click();
    await expect(page.locator('.import-progress')).toContainText('scope changed');
    importState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(importState).toMatchObject({ consent_preview_count: 1, consent_grant_attempts: 1, consent_grant_count: 0, upload_count: 0 });
    await page.getByRole('button', { name: 'Preview consent scope' }).click();
  }
  await page.getByRole('button', { name: 'Confirm scoped upload grant' }).click();
  await expect(page.getByText(/Append-only consent recorded/i)).toBeVisible();
  if (fixtureMode) {
    const importState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(importState).toMatchObject({ consent_preview_count: 2, consent_grant_attempts: 2, consent_grant_count: 1, upload_count: 0 });
  }
  await page.getByRole('button', { name: 'Confirm upload bytes' }).click();
  await expect(page.getByText(/Finalized ImportManifest/)).toBeVisible({ timeout: 120_000 });
  if (fixtureMode) {
    const importState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(importState.upload_count).toBe(1);
  }

  await page.getByRole('button', { name: 'Inbox' }).click();
  await expect(page.locator('.detail-header h2')).not.toBeEmpty();
  if (fixtureMode) {
    await expect(page.getByRole('heading', { name: 'Permission friction rose in collected GitHub content' })).toBeVisible();
    await expect(page.getByText('github_permission_mentions_delta >= 2', { exact: true })).toBeVisible();
    await expect(page.getByText('GitHub discussions scope is currently partial.')).toBeVisible();
    await expect(page.getByText(/Glint GitHub · last success/)).toBeVisible();
  } else {
    const importedSignal = page.locator('button.signal-row').filter({ hasText: 'static_import_content_count > 0' }).first();
    await expect(importedSignal).toBeVisible({ timeout: 120_000 });
    await importedSignal.click();
    await expect(page.getByText('static_import_content_count > 0', { exact: true })).toBeVisible();
    await expect(page.getByText(/P1 Acceptance CSV · last success/)).toBeVisible();
  }
  await page.keyboard.press('Meta+k');
  let commandPalette = page.getByRole('dialog', { name: 'Command Palette' });
  await expect(commandPalette).toBeVisible();
  await expect(commandPalette.getByText('Go to Investigations')).toBeVisible();
  if (fixtureMode) await expect(commandPalette.getByText('Start Investigation')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Meta+p');
  const globalSearch = page.getByRole('dialog', { name: 'Global Search' });
  await globalSearch.getByRole('combobox', { name: 'Global Search' }).fill(fixtureMode ? 'Glint GitHub' : 'P1 Acceptance CSV');
  await expect(globalSearch.getByText(fixtureMode ? 'Glint GitHub' : 'P1 Acceptance CSV', { exact: true }).first()).toBeVisible();
  if (fixtureMode) {
    await globalSearch.getByRole('combobox', { name: 'Global Search' }).press('Enter');
    await expect(page.getByRole('article', { name: 'Glint GitHub source' })).toBeFocused();
    await page.getByRole('button', { name: 'Inbox' }).click();
  } else await page.keyboard.press('Escape');
  const currentListFilter = page.getByLabel('Search Inbox');
  await currentListFilter.press('r');
  await expect(page.getByRole('dialog', { name: 'Investigation plan' })).toHaveCount(0);
  await currentListFilter.press('Meta+k');
  await expect(page.getByRole('dialog', { name: 'Command Palette' })).toBeVisible();
  await page.keyboard.press('Escape');
  await currentListFilter.fill('');
  await page.getByLabel('Business Impact').selectOption('high');
  await page.getByLabel('Urgency').selectOption('this_week');
  await page.getByRole('button', { name: 'Confirm Impact & Urgency' }).click();
  await expect(page.locator('.triage-grid').getByText('P1', { exact: true })).toBeVisible();
  await capture('02-signal-inbox');

  await page.keyboard.press('Meta+k');
  commandPalette = page.getByRole('dialog', { name: 'Command Palette' });
  await commandPalette.getByRole('combobox', { name: 'Command Palette' }).fill('Show Keyboard Shortcuts');
  await commandPalette.getByRole('combobox', { name: 'Command Palette' }).press('Enter');
  const shortcutHelp = page.getByRole('dialog', { name: 'Keyboard Shortcuts' });
  await expect(shortcutHelp).toContainText('J / ↓');
  await page.keyboard.press('Escape');
  await page.locator('.detail-header h2').click();
  await page.keyboard.press('r');
  await expect(page.getByRole('dialog', { name: 'Investigation plan' })).toBeVisible();
  await page.keyboard.press('Escape');

  await page.getByRole('button', { name: 'Start Investigation' }).click();
  await expect(page.getByRole('dialog', { name: 'Investigation plan' })).toContainText('No model egress is authorized');
  await expect(page.getByRole('dialog', { name: 'Investigation plan' })).toContainText(fixtureMode ? 'Glint GitHub · Cloud github collection' : 'P1 Acceptance CSV');
  await page.getByRole('button', { name: 'Run Investigation' }).click();
  const runsTab = page.getByRole('tab', { name: 'Runs' });
  const investigationError = page.locator('.error-banner');
  const investigationOutcome = await Promise.race([
    runsTab.waitFor({ state: 'visible', timeout: 60_000 }).then(() => 'ready' as const),
    investigationError.waitFor({ state: 'visible', timeout: 60_000 }).then(() => 'error' as const),
  ]);
  if (investigationOutcome === 'error') throw new Error(`Run Investigation failed: ${await investigationError.innerText()}`);
  if (fixtureMode) await expect(page.locator('.detail-header')).toContainText('collected');
  await runsTab.click();
  await expect(page.getByText('Evidence and Claim proposal persisted.')).toBeVisible({ timeout: 120_000 });
  if (fixtureMode) await expect(page.getByText('BROKEN GAP EVENT MUST BE DISCARDED')).toHaveCount(0);
  await expect(page.getByText(/SSE connected/)).toBeVisible();
  await capture('03-investigation-runs');

  await page.getByRole('tab', { name: 'Evidence' }).click();
  const evidenceCards = page.locator('.evidence');
  await expect(evidenceCards.first()).toBeVisible();
  await page.keyboard.press('e');
  await expect(page.getByRole('dialog', { name: 'Source Viewer' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Source Viewer' })).toHaveCount(0);
  const evidenceCount = await evidenceCards.count();
  for (let index = 0; index < evidenceCount; index += 1) {
    const card = evidenceCards.nth(index);
    await expect(card.getByRole('button', { name: 'Valid' })).toBeDisabled();
    await card.getByRole('button', { name: 'Open source' }).click();
    const viewer = page.getByRole('dialog', { name: 'Source Viewer' });
    await expect(viewer).toBeVisible();
    await expect(viewer).toContainText('captured');
    await expect(viewer.locator('mark')).not.toBeEmpty();
    if (fixtureMode && index === 0) {
      await expect(viewer).toContainText('Glint GitHub · cloud');
      await expect(viewer).toContainText('00000000-0000-4000-8000-000000000054');
      await expect(viewer).toContainText('Captured GitHub issue context remains immutable.');
    }
    await viewer.getByRole('button', { name: 'Close Source Viewer' }).click();
    await card.getByRole('button', { name: 'Valid' }).click();
    await expect(card.locator('.status')).toContainText('valid');
  }
  await capture('04-evidence-review');
  if (fixtureMode) {
    await page.reload();
    await page.getByRole('button', { name: 'Investigations' }).click();
    await page.getByRole('tab', { name: 'Runs' }).click();
    await expect(page.locator('.run-event').filter({ hasText: 'Immutable run input accepted.' })).toBeVisible();
    await expect(page.locator('.run-event').filter({ hasText: 'Evidence and Claim proposal persisted.' })).toBeVisible();
  }
  await page.getByRole('tab', { name: 'Claims' }).click();
  await page.getByRole('button', { name: 'Verify' }).first().click();
  await expect(page.locator('.claim .status').filter({ hasText: 'verified' })).toBeVisible();
  await capture('05-claim-review');
  await page.getByRole('tab', { name: 'Synthesis' }).click();
  await page.getByRole('button', { name: 'Create synthesis' }).click();
  await expect(page.getByLabel('Synthesis executive summary')).toHaveValue(fixtureMode ? /Opaque permission execution/ : /Observed source content indicates a product risk/);
  await expect(page.getByRole('button', { name: 'Reject synthesis' })).toBeVisible();
  await page.getByRole('button', { name: 'Verify synthesis' }).click();
  await expect(page.locator('.section .status').filter({ hasText: 'verified' })).toBeVisible();
  await page.getByRole('button', { name: 'Create Decision Brief' }).click();

  await page.getByLabel('PM Judgment').fill('The owner PM recommends enterprise-admin validation.');
  const recommendation = page.getByLabel('Recommendation recommendation-1');
  const acceptRecommendation = page.getByRole('button', { name: /^(Accept|Save accepted)$/ });
  await recommendation.fill('Temporary complete recommendation for guard verification.');
  await expect(acceptRecommendation).toBeEnabled();
  await recommendation.fill('TBD');
  await expect(acceptRecommendation).toBeDisabled();
  await recommendation.fill('Validate a permission execution preview with enterprise administrators.');
  const acceptedBriefResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'PATCH' && /^\/v1\/decision-briefs\/[^/]+$/.test(url.pathname);
  });
  await acceptRecommendation.click();
  const acceptedBrief = await (await acceptedBriefResponse).json() as { current_version: { version_number: number } };
  await expect(page.getByRole('button', { name: 'Save accepted' })).toBeVisible();
  const counterEvidenceSearch = page.getByRole('region', { name: 'Counter-evidence search' });
  await counterEvidenceSearch.getByLabel('Counter-evidence search queries').fill('permission execution preview alternatives and objections');
  await counterEvidenceSearch.getByLabel('Counter-evidence exclusion criteria').fill('Exclude duplicate captures and content outside the pinned Investigation scope.');
  await counterEvidenceSearch.getByLabel('Counter-evidence search limitations').fill('The search was limited to the current confirmed Investigation sources and time range.');
  const savedCounterEvidenceResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'PATCH' && /^\/v1\/decision-briefs\/[^/]+$/.test(url.pathname);
  });
  await counterEvidenceSearch.getByRole('button', { name: 'Save counter-evidence search' }).click();
  const savedCounterEvidence = await savedCounterEvidenceResponse;
  expect(savedCounterEvidence.status()).toBe(200);
  const savedBrief = await savedCounterEvidence.json() as {
    row_version: number;
    current_version: {
      id: string;
      version_number: number;
      block_document: { no_counter_evidence_search: unknown };
    };
  };
  expect(savedBrief.current_version.version_number).toBe(acceptedBrief.current_version.version_number + 1);
  expect(savedBrief.current_version.block_document.no_counter_evidence_search).toMatchObject({
    queries: ['permission execution preview alternatives and objections'],
  });
  await expect(counterEvidenceSearch.locator('.status.status-positive')).toContainText('Recorded');
  await expect(counterEvidenceSearch.locator('.status.status-warning')).toHaveCount(0);
  const markReadyResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'POST' && /\/v1\/decision-briefs\/[^/]+\/mark-decision-ready$/.test(url.pathname);
  });
  await page.getByRole('button', { name: 'Mark Decision-ready' }).click();
  const markedReady = await markReadyResponse;
  expect(markedReady.status()).toBe(201);
  expect(JSON.parse(markedReady.request().postData() ?? '{}')).toMatchObject({
    decision_brief_version_id: savedBrief.current_version.id,
    expected_row_version: savedBrief.row_version,
  });
  await expect(page.locator('.detail-header .status').filter({ hasText: 'Decision-ready' })).toBeVisible();
  await capture('06-decision-brief');
  await page.getByRole('button', { name: 'Export PRD Research Input' }).click();
  const preview = page.getByRole('dialog', { name: 'PRD Research Input Preview' });
  await expect(preview).toContainText('# PRD Research Input');
  await expect(preview).toContainText('prd_research_input_markdown');
  await expect(preview).toContainText(fixtureMode ? 'Data authenticity: Collected' : 'Data authenticity:');
  if (fixtureMode) {
    await expect(preview).toContainText('Decision Brief Version: 3 (00000000-0000-4000-8000-000000000084)');
    await expect(preview).toContainText('Data Authenticity: Collected');
    await expect(preview).toContainText('Source References: source:00000000-0000-4000-8000-000000000011');
    await expect(preview).toContainText('evidence:00000000-0000-4000-8000-000000000050 -> content-version:00000000-0000-4000-8000-000000000052');
    await expect(preview).toContainText('Export Timestamp: 2026-07-15T05:05:00Z');
    await expect(preview).toContainText('Readiness State: decision_ready/current');
  }
  await capture('07-export-preview');
  if (fixtureMode) {
    await page.getByRole('button', { name: 'Copy Markdown' }).click();
    await expect(preview.getByRole('alert')).toContainText('Local copy failed; no BriefExport audit record was created.');
    let fixtureState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(fixtureState).toMatchObject({ export_post_count: 0, export_terminal_count: 0 });
    await page.getByRole('button', { name: 'Copy Markdown' }).click();
    await expect(preview.getByRole('alert')).toContainText('Local output completed, but the terminal export audit record failed');
    const copiedMarkdown = await page.evaluate(() => String(Reflect.get(globalThis, '__copiedMarkdown')));
    expect(copiedMarkdown).toContain('> Data authenticity: Collected');
    expect(copiedMarkdown.match(/Data authenticity: Collected/g)).toHaveLength(1);
    fixtureState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(fixtureState).toMatchObject({ export_post_count: 1, export_terminal_count: 0 });
    await page.getByRole('button', { name: 'Retry audit record' }).click();
    await expect(page.getByText(/terminal BriefExport 00000000-0000-4000-8000-000000000090 · collected/)).toBeVisible();
    fixtureState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId } })).json();
    expect(fixtureState.export_post_count).toBe(2);
    expect(fixtureState.export_terminal_count).toBe(1);
    expect(new Set(fixtureState.export_idempotency_keys).size).toBe(1);
    expect(fixtureState.export_timestamps).toEqual(['2026-07-15T05:05:00Z', '2026-07-15T05:05:00Z']);
  } else {
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export .md' }).click();
    await download;
    await expect(page.getByText(/terminal BriefExport [0-9a-f-]+/)).toBeVisible();
  }

  if (fixtureMode) {
    await page.reload();
    await expect(page.getByRole('button', { name: 'Inbox' })).toBeVisible();
    const fixtureHeaders = { Authorization: `Bearer ${accessToken}`, 'X-Workspace-ID': workspaceId, 'Idempotency-Key': 'fixture-offline-control' };
    const beforeOffline = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: fixtureHeaders })).json();
    await request.post(`${apiUrl}/v1/fixture-control`, { headers: fixtureHeaders, data: { api_offline: true } });
    await page.reload();
    const offlineBanner = page.getByRole('status').filter({ hasText: 'Offline cached read-only' });
    await expect(offlineBanner).toContainText('cached_at');
    await expect(offlineBanner).not.toContainText('Never');
    await page.getByRole('button', { name: 'Inbox' }).click();
    await expect(page.getByRole('heading', { name: 'Permission friction rose in collected GitHub content' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start Investigation' })).toBeDisabled();
    await page.getByRole('button', { name: 'Investigations' }).click();
    await expect(page.getByRole('heading', { name: 'Should permission execution preview enter next-quarter prioritization?' })).toBeVisible();
    await page.getByRole('button', { name: 'Decisions' }).click();
    await expect(page.getByRole('button', { name: 'Export PRD Research Input' })).toBeDisabled();
    await page.getByRole('button', { name: 'Monitoring' }).click();
    await expect(page.getByRole('article', { name: 'Glint GitHub source' }).getByRole('button', { name: 'Reconnect Glint GitHub' })).toBeDisabled();
    const duringOffline = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: fixtureHeaders })).json();
    expect(duringOffline.mutation_request_count).toBe(beforeOffline.mutation_request_count);
    expect(duringOffline.sse_request_count).toBe(beforeOffline.sse_request_count);
    expect(duringOffline).toMatchObject({ offline_mutation_request_count: 0, offline_sse_request_count: 0, offline_export_request_count: 0 });
    await request.post(`${apiUrl}/v1/fixture-control`, { headers: fixtureHeaders, data: { api_offline: false } });
    await offlineBanner.getByRole('button', { name: 'Retry connection' }).click();
    await expect(offlineBanner).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Inbox' })).toBeVisible();
    await page.getByRole('button', { name: 'Inbox' }).click();
    await page.locator('.detail-header h2').click();
    await page.keyboard.press('i');
    const dismissDialog = page.getByRole('dialog', { name: 'Dismiss Signal' });
    await dismissDialog.getByLabel('Dismiss reason').selectOption('known_issue');
    await dismissDialog.getByLabel('Dismiss note').fill('Already tracked by the platform reliability owner.');
    await dismissDialog.getByRole('button', { name: 'Dismiss Signal' }).click();
    await expect(page.getByText('Signal dismissed. The audited disposition remains available in Signal history.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start Investigation' })).toBeDisabled();
    const dispositionState = await (await request.get(`${apiUrl}/v1/fixture-state`, { headers: fixtureHeaders })).json();
    expect(dispositionState).toMatchObject({ signal_transition_count: 1, signal_disposition: { action: 'dismiss', dismiss_reason: 'known_issue', note: 'Already tracked by the platform reliability owner.' } });
  }
});
