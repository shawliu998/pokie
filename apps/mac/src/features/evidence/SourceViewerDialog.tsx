import { Badge, Button, Status } from '@glint/ui';
import type { SourceViewer } from '../../api';
import { authenticityLabel } from '../../domain';
import { displayTime } from '../../lib/formatting';

export function SourceViewerDialog({ viewer, onClose }: { viewer: SourceViewer; onClose: () => void }) {
  return <div className="modal-backdrop"><section className="modal source-viewer" role="dialog" aria-modal="true" aria-label="Source Viewer"><h2>{viewer.title}</h2><p><Status tone={viewer.availability === 'captured' ? 'positive' : 'danger'}>{viewer.availability}</Status> <Badge tone="info">{authenticityLabel(viewer.authenticity)}</Badge></p><dl><dt>Source</dt><dd>{viewer.source.name} · {viewer.source.kind}</dd><dt>Author</dt><dd>{viewer.author ?? 'Not supplied'}</dd><dt>Captured</dt><dd>{displayTime(viewer.capturedAt)}</dd><dt>Published</dt><dd>{displayTime(viewer.publishedAt)}</dd><dt>Independence group</dt><dd>{viewer.independenceGroupId ?? 'Not assigned'}</dd><dt>ContentVersion</dt><dd><code>{viewer.contentVersionId}</code></dd>{viewer.canonicalUrl && <><dt>Canonical URL</dt><dd>{viewer.canonicalUrl}</dd></>}</dl><h3>Immutable captured body</h3><pre>{viewer.beforeQuote}<mark>{viewer.highlightedQuote}</mark>{viewer.afterQuote}</pre><div className="modal-actions"><Button onClick={onClose}>Close Source Viewer</Button></div></section></div>;
}
