import { useEffect, useState } from 'react';
import { Badge, Button } from '@glint/ui';
import type { BriefExport, ExportPreview } from '../../api';
import type { DecisionBrief } from '../../domain';
import { authenticityLabel } from '../../domain';
import { completeLocalExport, TerminalAuditError } from '../../export-flow';

interface ExportDialogProps {
  brief: DecisionBrief;
  disabled: boolean;
  onClose: () => void;
  onPreview: () => Promise<ExportPreview>;
  onExecute: (preview: ExportPreview, destination: BriefExport['destination'], idempotencyKey: string) => Promise<BriefExport>;
  onDone: (message: string) => void;
}

export function ExportDialog({ brief, disabled, onClose, onPreview, onExecute, onDone }: ExportDialogProps) {
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [pendingAudit, setPendingAudit] = useState<{ destination: BriefExport['destination']; idempotencyKey: string } | null>(null);
  useEffect(() => { void onPreview().then(setPreview).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to render export preview.')).finally(() => setBusy(false)); }, [onPreview]);
  const finishTerminal = (terminal: BriefExport, destination: BriefExport['destination']) => {
    setPendingAudit(null);
    onDone(`${destination === 'copy_markdown' ? 'Copied' : 'Exported'} PRD Research Input · terminal BriefExport ${terminal.id} · ${authenticityLabel(terminal.authenticity)}.`);
  };
  const retryTerminal = async (destination: BriefExport['destination'], idempotencyKey: string) => {
    if (!preview) return;
    try {
      const terminal = await onExecute(preview, destination, idempotencyKey);
      finishTerminal(terminal, destination);
    } catch (reason) {
      setPendingAudit({ destination, idempotencyKey });
      setError(`Local output completed, but the terminal export audit record failed: ${reason instanceof Error ? reason.message : 'unknown audit error'}. Retry audit recording with the same idempotency key.`);
    }
  };
  const execute = async (action: 'copy' | 'download') => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    const destination = action === 'copy' ? 'copy_markdown' : 'local_download';
    const idempotencyKey = crypto.randomUUID();
    try {
      const terminal = await completeLocalExport(async () => {
        if (action === 'copy') await navigator.clipboard.writeText(preview.renderedContent);
        else { const url = URL.createObjectURL(new Blob([preview.renderedContent], { type: 'text/markdown' })); const link = document.createElement('a'); link.href = url; link.download = `glint-prd-research-input-v${brief.version}.md`; link.click(); URL.revokeObjectURL(url); }
      }, () => onExecute(preview, destination, idempotencyKey));
      finishTerminal(terminal, destination);
    } catch (reason) {
      if (reason instanceof TerminalAuditError) {
        setPendingAudit({ destination, idempotencyKey });
        setError(`Local output completed, but the terminal export audit record failed: ${reason.message}. Retry audit recording with the same idempotency key.`);
      } else {
        setError(`Local ${action} failed; no BriefExport audit record was created. ${reason instanceof Error ? reason.message : ''}`);
      }
      setBusy(false);
      return;
    }
    setBusy(false);
  };
  const retryAudit = async () => { if (!pendingAudit) return; setBusy(true); setError(null); await retryTerminal(pendingAudit.destination, pendingAudit.idempotencyKey); setBusy(false); };
  return <div className="modal-backdrop"><section className="modal export" role="dialog" aria-modal="true" aria-label="PRD Research Input Preview"><h2>PRD Research Input</h2><p>From Decision Brief v{brief.version} · readiness-reviewed · {brief.freshness}</p>{preview && <p className="authenticity-callout"><Badge tone={preview.authenticity === 'seed' ? 'warning' : 'info'}>Data authenticity: {authenticityLabel(preview.authenticity)}</Badge> The canonical server-rendered Markdown below carries the same marker.</p>}{busy && !preview ? <p>Rendering exact-version preview…</p> : preview && <pre>{preview.renderedContent}</pre>}{error && <p role="alert">{error}</p>}<p className="hint">Export type: prd_research_input_markdown. Synthesis and unaccepted recommendations are excluded by policy.</p><div className="modal-actions"><Button onClick={onClose}>Close</Button>{pendingAudit ? <Button className="primary" disabled={disabled || busy} onClick={() => void retryAudit()}>Retry audit record</Button> : <><Button disabled={disabled || busy || !preview} onClick={() => void execute('copy')}>Copy Markdown</Button><Button className="primary" disabled={disabled || busy || !preview} onClick={() => void execute('download')}>Export .md</Button></>}</div></section></div>;
}
