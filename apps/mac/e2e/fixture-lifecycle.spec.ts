import { expect, test } from './fixture-test';

declare const process: { env: Record<string, string | undefined> };

const workspaceId = process.env.GLINT_E2E_WORKSPACE_ID ?? '00000000-0000-4000-8000-000000000001';
const accessToken = process.env.GLINT_E2E_ACCESS_TOKEN ?? 'fixture-access-token';
const apiUrl = `http://127.0.0.1:${process.env.GLINT_FIXTURE_PORT ?? '4174'}/v1`;
const headers = (key?: string) => ({
  Authorization: `Bearer ${accessToken}`,
  'X-Workspace-ID': workspaceId,
  ...(key ? { 'Idempotency-Key': key } : {}),
});

const expectedQuantRunState = {
  'quant-cancelled': 'cancelled',
  'quant-completed': 'completed',
  'quant-failed-safe': 'failed',
  'quant-generating-candidates': 'generating_candidates',
  'quant-generating-report': 'generating_report',
  'quant-loading-data': 'loading_data',
  'quant-no-viable-candidate': 'completed',
  'quant-plan-approval': 'waiting_plan_approval',
  'quant-ready': 'draft',
  'quant-repairing': 'repairing',
  'quant-running': 'running_experiments',
  'quant-validating': 'validating',
  'quant-waiting-review': 'waiting_for_review',
} as const;

const fixtureGoal = 'Evaluate bounded SPY trend hypotheses with synthetic evidence.';

test('fixture reset restores the exact configured Quant startup baseline', async ({ request }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'Fixture lifecycle assertions require the deterministic API fixture.');
  const variant = process.env.POKIEQUANT_E2E_RUN_STATE ?? 'quant-completed';
  if (!(variant in expectedQuantRunState)) throw new Error(`No Quant fixture baseline is defined for ${variant}.`);

  const polluted = await request.post(`${apiUrl}/fixture-control`, {
    headers: headers('fixture-lifecycle-pollute'),
    data: { api_offline: true },
  });
  expect(polluted.ok()).toBe(true);
  const reset = await request.post(`${apiUrl}/fixture-reset`, {
    headers: headers('fixture-lifecycle-reset'),
  });
  expect(reset.ok()).toBe(true);
  const response = await request.get(`${apiUrl}/fixture-state`, { headers: headers() });
  expect(response.ok()).toBe(true);
  expect(await response.json()).toMatchObject({
    quant_fixture_state: variant,
    quant_run_state: expectedQuantRunState[variant as keyof typeof expectedQuantRunState],
    quant_run_mode: 'auto_research',
    quant_goal: fixtureGoal,
    quant_row_version: 8,
    quant_project_row_version: 1,
    active_market_run_id: null,
    api_offline: false,
    mutation_request_count: 0,
    investigation_status: 'none',
    investigation_row_version: 1,
    run_state: 'none',
    run_row_version: 1,
    latest_sequence: 0,
    evidence_status: 'proposed',
    claim_status: 'needs_review',
    synthesis_status: 'none',
    brief_status: 'none',
  });
});
