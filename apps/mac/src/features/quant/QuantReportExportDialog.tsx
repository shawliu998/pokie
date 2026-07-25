import { useEffect, useRef, useState } from 'react';
import type { QuantApi, QuantStrategyReportExport, QuantStrategyReportExportType } from '../../quant-api';

type Props = {
  api: QuantApi;
  runId: string;
  candidateId: string;
  finalCandidateId?: string;
  onClose: () => void;
};

const message = (reason: unknown) => reason instanceof Error ? reason.message : 'Report preview failed.';

export function QuantReportExportDialog({ api, runId, candidateId, finalCandidateId, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const requestGeneration = useRef(0);
  const mounted = useRef(true);
  const [exportType, setExportType] = useState<QuantStrategyReportExportType>('strategy_report_markdown');
  const [preview, setPreview] = useState<QuantStrategyReportExport>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionStatus, setActionStatus] = useState('');
  const canExportJson = finalCandidateId === candidateId;
  const isJsonExport = exportType === 'strategy_evidence_bundle_json';
  const exportFormatLabel = isJsonExport ? 'Evidence bundle (.json)' : 'Report (.md)';
  const previewLabel = isJsonExport ? 'Rendered Strategy Evidence Bundle JSON' : 'Rendered Strategy Report Markdown';
  const exportTitle = isJsonExport ? 'Strategy Evidence Bundle preview' : 'Strategy Report preview';

  const load = async (requestedExportType: QuantStrategyReportExportType = exportType) => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setError('');
    setActionStatus('');
    try {
      const next = await api.previewStrategyReportExport(runId, candidateId, requestedExportType);
      if (!mounted.current || generation !== requestGeneration.current) return;
      if (next.runId !== runId || next.candidateId !== candidateId || next.exportType !== requestedExportType) {
        throw new Error('The server returned a report for a different run, candidate, or export format.');
      }
      setPreview(next);
    } catch (reason) {
      if (!mounted.current || generation !== requestGeneration.current) return;
      setPreview(undefined);
      setError(message(reason));
    } finally {
      if (mounted.current && generation === requestGeneration.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    closeRef.current?.focus();
  }, [runId, candidateId, exportType]);

  useEffect(() => () => {
    mounted.current = false;
    requestGeneration.current += 1;
  }, []);

  const chooseExportType = (nextExportType: QuantStrategyReportExportType) => {
    if (nextExportType === 'strategy_evidence_bundle_json' && !canExportJson) return;
    setPreview(undefined);
    setError('');
    setActionStatus('');
    setLoading(true);
    setExportType(nextExportType);
  };

  const copy = async () => {
    if (!preview) return;
    setActionStatus('');
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable.');
      await navigator.clipboard.writeText(preview.renderedContent);
      setActionStatus(isJsonExport ? 'JSON copied.' : 'Markdown copied.');
    } catch (reason) {
      setActionStatus(`Copy failed: ${message(reason)}`);
    }
  };

  const download = () => {
    if (!preview) return;
    setActionStatus('');
    try {
      if (!URL.createObjectURL) throw new Error('Downloads are unavailable in this browser.');
      const url = URL.createObjectURL(new Blob([preview.renderedContent], { type: preview.mediaType }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = preview.filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setActionStatus(`Downloaded ${preview.filename}.`);
    } catch (reason) {
      setActionStatus(`Download failed: ${message(reason)}`);
    }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal quant-report-export" role="dialog" aria-modal="true" aria-labelledby="quant-report-export-title" onKeyDown={(event) => { if (event.key === 'Escape') onClose(); }}>
      <header><div><span className="quant-report-context">{exportFormatLabel}</span><h2 id="quant-report-export-title">{exportTitle}</h2></div>{preview && <span className="quant-report-export-file">{preview.filename}</span>}</header>
      <label><span>Export format</span><select aria-label="Export format" value={exportType} onChange={(event) => chooseExportType(event.target.value as QuantStrategyReportExportType)}><option value="strategy_report_markdown">Report (.md)</option><option value="strategy_evidence_bundle_json" disabled={!canExportJson}>Evidence bundle (.json)</option></select></label>
      {!canExportJson && <p className="hint">Evidence bundle is available for the final selected strategy only.</p>}
      {loading && <div className="quant-report-export-state"><strong>{isJsonExport ? 'Rendering evidence bundle…' : 'Rendering report…'}</strong><p>Loading the persisted run and selected candidate from the server.</p></div>}
      {!loading && error && <div className="quant-report-export-state" role="alert"><strong>Preview unavailable</strong><p>{error}</p><button className="button" onClick={() => void load()}>Retry preview</button></div>}
      {preview && <pre aria-label={previewLabel}>{preview.renderedContent}</pre>}
      {preview && <p className="hint">Server-rendered from run {preview.runId.slice(0, 8)} · {preview.contentDigest.slice(0, 19)}…</p>}
      {actionStatus && <p className="quant-report-export-status">{actionStatus}</p>}
      <div className="modal-actions"><button ref={closeRef} className="button" onClick={onClose}>Close</button><button className="button" disabled={!preview || loading} onClick={() => void copy()}>{isJsonExport ? 'Copy JSON' : 'Copy Markdown'}</button><button className="button primary" disabled={!preview || loading} onClick={download}>{isJsonExport ? 'Download .json' : 'Download .md'}</button></div>
    </section>
  </div>;
}
