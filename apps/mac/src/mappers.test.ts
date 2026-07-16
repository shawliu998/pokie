import { describe, expect, it } from 'vitest';
import { mapBrief, mapEvidence, mapSignal, mapSource } from './mappers';

const timestamps = { created_at: '2026-07-15T05:00:00Z', updated_at: '2026-07-15T05:01:00Z' };

describe('strict REST DTO mappers', () => {
  it('fails closed on unknown authenticity and keeps nullable freshness safe', () => {
    const source = {
      id: 'source-rss', workspace_id: 'workspace-1', name: 'Release feeds', source_kind: 'cloud', runtime: 'cloud', connector_type: 'rss', connector_version: 'rss-v1', status: 'healthy',
      source_config: { connector_type: 'rss', feeds: [{ name: 'Releases', feed_url: 'https://example.com/releases.xml' }] }, cadence: 'daily', timezone: 'Asia/Shanghai', last_run_at: null, last_success_at: null,
      health: { state: 'unknown', checked_at: null, last_error_code: null }, freshness: { state: 'never', last_success_at: null }, capabilities: ['fetch', 'health'], data_scope: 'public', current_import_manifest: null, row_version: 1, data_authenticity: 'collected', ...timestamps,
    };
    expect(mapSource(source).freshness.lastSuccessAt).toBeNull();
    expect(mapSource(source).sourceConfig).toMatchObject({ connectorType: 'rss' });
    expect(() => mapSource({ ...source, data_authenticity: 'synthetic-ish' })).toThrow(/unknown data_authenticity/);
  });

  it('maps real Signal trigger rules, counts, limitations, and per-source freshness', () => {
    const signal = mapSignal({ id: 'signal-1', workspace_id: 'workspace-1', watchlist_id: 'watchlist-1', title: 'Release churn', status: 'new', detector_version: 'detector-v1', trigger_rules: ['release_count_delta > 2'], limitations: ['RSS dates may be absent.'], total_source_count: 2, independent_source_count: 2, cross_source_confirmation: true, per_source_freshness: [{ source_connection_id: 'source-rss', state: 'current', last_success_at: '2026-07-15T05:00:00Z' }], window: { current_start: '2026-07-08T00:00:00Z', current_end: '2026-07-15T00:00:00Z', baseline_start: '2026-06-10T00:00:00Z', baseline_end: '2026-07-08T00:00:00Z' }, metrics: { current_count: 4, baseline_count: 1, mention_count: 4, independent_source_count: 2, platform_count: 1, growth_ratio: 4, robust_z: 2.5 }, dimensions: { detection_confidence: { level: 'high', calibration_status: 'calibrated', explanation: 'Two independent feeds changed.' }, business_impact: { suggested_level: null, suggested_explanation: null, suggestion_origin: 'none', suggestion_version: null, confirmed_level: null, confirmed_by: null, confirmed_at: null, version: 0 }, urgency: { suggested_level: null, suggested_explanation: null, suggestion_origin: 'none', suggestion_version: null, confirmed_level: null, confirmed_by: null, confirmed_at: null, version: 0 }, priority: { level: null, status: 'insufficient_input', policy_version: 'priority-v1', explanation: 'Needs input.' } }, disposition: null, row_version: 1, data_authenticity: 'collected', ...timestamps });
    expect(signal.triggerRules).toEqual(['release_count_delta > 2']);
    expect(signal.limitations).toEqual(['RSS dates may be absent.']);
    expect(signal.totalSourceCount).toBe(2);
    expect(signal.perSourceFreshness[0]?.sourceConnectionId).toBe('source-rss');
  });

  it('maps nested DecisionBrief current_version and exact block_document', () => {
    const brief = mapBrief({ id: 'brief-1', workspace_id: 'workspace-1', investigation_id: 'investigation-1', current_version: { id: 'brief-version-1', decision_brief_id: 'brief-1', investigation_id: 'investigation-1', version_number: 2, synthesis_version_id: 'synthesis-version-1', synthesis_review_id: 'synthesis-review-1', block_document: { schema_version: 'decision-brief-blocks-v1', blocks: [{ id: 'fact-1', type: 'fact', body: 'A verified fact.', claim_version_ids: ['claim-version-1'], evidence_ids: ['evidence-1'], content_version_ids: ['content-version-1'] }, { id: 'judgment-1', type: 'pm_judgment', body: 'Proceed.', actor_id: 'owner-1' }, { id: 'recommendation-1', type: 'recommendation', body: 'Ship it.', recommendation_status: 'accepted' }], no_counter_evidence_search: null }, reference_snapshot_json: { synthesis_version_id: 'synthesis-version-1', synthesis_review_id: 'synthesis-review-1', claim_version_ids: ['claim-version-1'], claim_review_ids: ['claim-review-1'], claim_evidence_ids: ['evidence-review-1'], evidence_review_ids: ['evidence-review-1'], evidence_ids: ['evidence-1'], content_version_ids: ['content-version-1'] }, template_version: 'brief-v1', human_edit_digest: `sha256:${'a'.repeat(64)}`, readiness: 'draft', freshness: 'current', created_by: 'owner-1', created_at: timestamps.created_at, data_authenticity: 'human_authored' }, status: 'draft', owner_id: 'owner-1', decision_outcome: null, next_checkpoint_at: null, row_version: 2, data_authenticity: 'human_authored', ...timestamps }, 'Should we ship?');
    expect(brief.versionId).toBe('brief-version-1');
    expect(brief.blockDocument.blocks.map((block) => block.type)).toEqual(['fact', 'pm_judgment', 'recommendation']);
    expect(brief.referenceSnapshot.evidenceReviewIds).toEqual(['evidence-review-1']);
  });

  it('maps the durable latest EvidenceReview projection after a reload', () => {
    const evidence = mapEvidence({ id: 'evidence-1', workspace_id: 'workspace-1', investigation_id: 'investigation-1', research_run_id: 'run-1', content_version_id: 'content-1', quote_start: 0, quote_end: 10, quote_text: 'Exact quote', quote_text_digest: `sha256:${'a'.repeat(64)}`, stance: 'supports', status: 'valid', latest_review: { id: 'evidence-review-1', decision: 'valid', policy_version: 'evidence-review-v1', reviewed_at: timestamps.updated_at }, relevance: 1, reliability: 1, independence: 1, recency: 1, specificity: 1, provenance: { research_run_id: 'run-1', extraction_method: 'deterministic-v1' }, data_authenticity: 'collected', ...timestamps });
    expect(evidence.latestReviewId).toBe('evidence-review-1');
  });
});
