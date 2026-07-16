import { describe, expect, it } from 'vitest';
import { authenticityLabel, derivePriority, priorityLabel, selectCloudScheduleWatchlist } from './domain';

describe('Phase 1 signal triage', () => {
  it('derives priority only from confirmed rankable dimensions', () => { expect(derivePriority('high', 'now')).toBe('P0'); expect(derivePriority('unknown', 'now')).toBeNull(); expect(priorityLabel({ impact: 'unknown', urgency: 'now', priority: null })).toBe('Unranked · insufficient input'); });
  it('renders all closed authenticity values without assuming Seed', () => { expect(authenticityLabel('human_authored')).toBe('human authored'); expect(authenticityLabel('collected')).toBe('collected'); });
});

describe('cloud schedule Watchlist selection', () => {
  it('prefers an active cloud-bound Watchlist over an imported-data Watchlist', () => {
    const imported = {
      id: 'watchlist-imported',
      status: 'active',
      sourceConnectionIds: ['source-csv'],
    };
    const cloud = {
      id: 'watchlist-cloud',
      status: 'active',
      sourceConnectionIds: ['source-github', 'source-rss'],
    };
    const sources = [
      { id: 'source-csv', sourceKind: 'imported_dataset' },
      { id: 'source-github', sourceKind: 'cloud' },
      { id: 'source-rss', sourceKind: 'cloud' },
    ];

    expect(
      selectCloudScheduleWatchlist(
        [imported, cloud] as Parameters<typeof selectCloudScheduleWatchlist>[0],
        sources as Parameters<typeof selectCloudScheduleWatchlist>[1],
      )?.id,
    ).toBe('watchlist-cloud');
  });

  it('does not silently bind a cloud schedule to an imported-data Watchlist', () => {
    const imported = {
      id: 'watchlist-imported',
      status: 'active',
      sourceConnectionIds: ['source-csv'],
    };
    const sources = [
      { id: 'source-csv', sourceKind: 'imported_dataset' },
      { id: 'source-github', sourceKind: 'cloud' },
    ];

    expect(
      selectCloudScheduleWatchlist(
        [imported] as Parameters<typeof selectCloudScheduleWatchlist>[0],
        sources as Parameters<typeof selectCloudScheduleWatchlist>[1],
      ),
    ).toBeUndefined();
  });
});
