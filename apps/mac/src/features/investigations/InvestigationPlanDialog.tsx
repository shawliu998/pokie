import { useState } from 'react';
import { Button } from '@glint/ui';
import { eligibleResearchSources } from '../../api';
import type { Signal, SourceHealth } from '../../domain';
import { authenticityLabel } from '../../domain';
import { displayTime } from '../../lib/formatting';

export function InvestigationPlanDialog({ signal, sources, disabled, onClose, onRun }: { signal: Signal; sources: SourceHealth[]; disabled: boolean; onClose: () => void; onRun: (question: string) => void }) {
  const [question, setQuestion] = useState(`What decision should we make in response to “${signal.title}”?`);
  const eligible = eligibleResearchSources(signal, sources);
  return <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label="Investigation plan"><h2>Plan Investigation</h2><p>This creates a bounded deterministic run only from Signal-linked, versioned source content. No model egress is authorized.</p><label>Decision Question<textarea value={question} onChange={(event) => setQuestion(event.target.value)} /></label><dl><dt>Time window</dt><dd>{displayTime(signal.window.currentStart)} → {displayTime(signal.window.currentEnd)}</dd><dt>Source content</dt><dd>{eligible.map((item) => item.sourceKind === 'imported_dataset' ? `${item.name} · Imported terminal manifest ${item.currentImportManifestId}` : `${item.name} · Cloud ${item.connectorType} collection · ${item.freshness.state} since ${displayTime(item.freshness.lastSuccessAt)}`).join('\n') || 'No Signal-linked source has eligible versioned content'}</dd><dt>Budget</dt><dd>Up to $4.00 / 15 minutes</dd><dt>Authenticity</dt><dd>{authenticityLabel(signal.authenticity)}</dd></dl><div className="modal-actions"><Button onClick={onClose}>Back to Signal</Button><Button className="primary" disabled={disabled || !question.trim() || eligible.length === 0} onClick={() => onRun(question)}>Run Investigation</Button></div></section></div>;
}
