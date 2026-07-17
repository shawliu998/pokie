import { useEffect, useMemo, useState } from 'react';
import { Badge, Button } from '@glint/ui';
import { quantIdempotencyKey, type QuantApi } from '../../quant-api';
import { quantAuthenticityLabel, type DatasetSnapshot, type QuantWorkspaceSnapshot } from '../../quant-domain';

const MAX_CSV_BYTES = 10_000_000;
const MIN_AUTONOMOUS_RESEARCH_BARS = 252;

function fileStem(fileName: string): string {
  return fileName.replace(/\.csv$/i, '').trim() || 'Imported OHLCV dataset';
}

function uniqueDatasets(snapshotDataset: DatasetSnapshot, datasets: DatasetSnapshot[]): DatasetSnapshot[] {
  const byId = new Map<string, DatasetSnapshot>();
  byId.set(snapshotDataset.id, snapshotDataset);
  for (const dataset of datasets) byId.set(dataset.id, dataset);
  return [...byId.values()];
}

export function QuantDataPage({ api, snapshot, selectedDataset, onSelect, onInspect }: {
  api: QuantApi;
  snapshot: QuantWorkspaceSnapshot;
  selectedDataset: DatasetSnapshot;
  onSelect: (dataset: DatasetSnapshot) => void;
  onInspect: () => void;
}) {
  const [datasets, setDatasets] = useState<DatasetSnapshot[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [symbol, setSymbol] = useState('');
  const [sourceName, setSourceName] = useState('');
  const [sourceReference, setSourceReference] = useState('');
  const [priceAdjustment, setPriceAdjustment] = useState<'unknown' | 'unadjusted' | 'split_adjusted' | 'total_return_adjusted'>('unknown');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setDatasets(await api.listDatasets());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load immutable datasets.');
    }
  };

  useEffect(() => { void refresh(); }, [api]);

  const allDatasets = useMemo(
    () => uniqueDatasets(snapshot.dataset, datasets),
    [datasets, snapshot.dataset],
  );
  const eligible = selectedDataset.barCount >= MIN_AUTONOMOUS_RESEARCH_BARS;

  const chooseFile = (nextFile: File | null) => {
    setFile(nextFile);
    setError(null);
    setNotice(null);
    if (!nextFile) return;
    if (nextFile.size > MAX_CSV_BYTES) {
      setError('CSV files must be 10 MB or smaller.');
      return;
    }
    setName((current) => current || fileStem(nextFile.name));
  };

  const importCsv = async () => {
    if (!file || busy) return;
    if (file.size > MAX_CSV_BYTES) {
      setError('CSV files must be 10 MB or smaller.');
      return;
    }
    if (!name.trim() || !symbol.trim()) {
      setError('Provide a dataset name and symbol before importing.');
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const dataset = await api.importDatasetCsv({
        name: name.trim(),
        symbol: symbol.trim(),
        csvText: await file.text(),
        fileName: file.name,
        sourceName: sourceName.trim() || 'User-provided CSV',
        sourceReference: sourceReference.trim() || undefined,
        priceAdjustment,
        idempotencyKey: quantIdempotencyKey(),
      });
      setDatasets((current) => uniqueDatasets(dataset, current));
      onSelect(dataset);
      setFile(null);
      setName('');
      setSymbol('');
      setSourceName('');
      setSourceReference('');
      setPriceAdjustment('unknown');
      setNotice(`${dataset.name} was imported as an immutable dataset.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The OHLCV CSV could not be imported.');
    } finally {
      setBusy(false);
    }
  };

  return <div className="quant-page quant-data-page">
    <div className="quant-page-title"><p className="quant-eyebrow">Data</p><h1>Immutable datasets</h1><p>Import daily OHLCV CSV files, then select the version that a new research run must pin.</p></div>
    <section className="quant-data-import" aria-labelledby="quant-data-import-title">
      <div><p className="quant-eyebrow">Import CSV</p><h2 id="quant-data-import-title">Daily OHLCV</h2><p>Accepted files are parsed by the server and stored as immutable, digest-addressed dataset versions.</p></div>
      <div className="quant-data-import-fields">
        <label><span>CSV file</span><input aria-label="OHLCV CSV file" type="file" accept=".csv,text/csv" disabled={busy} onChange={(event) => chooseFile(event.target.files?.[0] ?? null)} /></label>
        <label><span>Dataset name</span><input aria-label="Dataset name" value={name} disabled={busy} onChange={(event) => setName(event.target.value)} /></label>
        <label><span>Symbol</span><input aria-label="Dataset symbol" value={symbol} disabled={busy} placeholder="SPY" onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label>
        <label><span>Source/provider</span><input aria-label="Dataset source provider" value={sourceName} disabled={busy} placeholder="Exchange, vendor, or research source" onChange={(event) => setSourceName(event.target.value)} /></label>
        <label><span>Source reference</span><input aria-label="Dataset source reference" value={sourceReference} disabled={busy} placeholder="URL, export ID, or internal reference" onChange={(event) => setSourceReference(event.target.value)} /></label>
        <label><span>Price adjustment</span><select aria-label="Dataset price adjustment" value={priceAdjustment} disabled={busy} onChange={(event) => setPriceAdjustment(event.target.value as typeof priceAdjustment)}><option value="unknown">Unknown</option><option value="unadjusted">Unadjusted</option><option value="split_adjusted">Split adjusted</option><option value="total_return_adjusted">Total return adjusted</option></select></label>
        <Button className="primary" disabled={!file || busy} onClick={() => void importCsv()}>{busy ? 'Importing…' : 'Import immutable dataset'}</Button>
      </div>
      <small>Maximum 10 MB. The selected file is sent only when you import it.</small>
      {error && <p className="quant-inline-note" role="alert">{error}</p>}
      {notice && <p className="quant-inline-note" role="status">{notice}</p>}
    </section>
    <section className="quant-dataset-list" aria-labelledby="quant-dataset-list-title">
      <header><div><p className="quant-eyebrow">Available versions</p><h2 id="quant-dataset-list-title">Select a dataset</h2></div><span>{allDatasets.length} version{allDatasets.length === 1 ? '' : 's'}</span></header>
      {allDatasets.map((dataset) => {
        const isSelected = dataset.id === selectedDataset.id;
        const canResearch = dataset.barCount >= MIN_AUTONOMOUS_RESEARCH_BARS;
        return <article className={`quant-dataset-card${isSelected ? ' is-selected' : ''}`} key={dataset.id}>
          <header><div><p className="quant-eyebrow">{dataset.symbol} · {dataset.interval}</p><h3>{dataset.name}</h3></div><Badge tone={dataset.authenticity === 'synthetic_fixture' ? 'warning' : 'info'}>{quantAuthenticityLabel(dataset.authenticity)}</Badge></header>
          <dl><div><dt>Date range</dt><dd>{dataset.dateRange.start} – {dataset.dateRange.end}</dd></div><div><dt>Bars</dt><dd>{dataset.barCount.toLocaleString()}</dd></div>{dataset.source && <><div><dt>Source</dt><dd>{dataset.source.sourceName}</dd></div><div><dt>Adjustment</dt><dd>{dataset.source.priceAdjustment.replaceAll('_', ' ')}</dd></div></>}<div><dt>Research eligibility</dt><dd>{canResearch ? 'Ready for Auto Research' : `Needs ${MIN_AUTONOMOUS_RESEARCH_BARS - dataset.barCount} more daily bars`}</dd></div></dl>
          <footer><code title={dataset.digest}>{dataset.digest.slice(0, 19)}…</code><div>{isSelected ? <span className="quant-dataset-selected">Selected</span> : <Button onClick={() => onSelect(dataset)}>Select dataset</Button>}{isSelected && <Button onClick={onInspect}>Inspect provenance</Button>}</div></footer>
        </article>;
      })}
    </section>
    {!eligible && <p className="quant-inline-note" role="status">The selected dataset can be inspected, but Auto Research needs at least {MIN_AUTONOMOUS_RESEARCH_BARS} daily bars.</p>}
  </div>;
}
