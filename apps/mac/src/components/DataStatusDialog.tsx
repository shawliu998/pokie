import { Badge, Button, Status } from '@glint/ui';
import type { SourceHealth } from '../domain';

export function DataStatusDialog({ sources, onClose }: { sources: SourceHealth[]; onClose: () => void }) {
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Data status"><h2>Data status</h2><p><Badge tone="positive">REST API</Badge></p><p>This client only reads and writes through the configured REST API contract.</p>{sources.map((source) => <p key={source.id}><Status tone={source.health.state === 'healthy' ? 'positive' : 'warning'}>{source.health.state}</Status> {source.name} · freshness {source.freshness.state}</p>)}<Button onClick={onClose}>Close</Button></section></div>;
}
