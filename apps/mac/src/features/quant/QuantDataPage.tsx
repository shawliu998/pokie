import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@glint/ui';
import { quantIdempotencyKey, type QuantApi, type QuantConnectorInterval, type QuantMarketDataConnector } from '../../quant-api';
import type { DatasetSnapshot, QuantBarInterval, QuantDatasetPreview, QuantWorkspaceSnapshot } from '../../quant-domain';
import { defaultMarketFetchLimit, marketResearchRequirementLabel } from '../../quant-research-eligibility';
import { presentQuantProblem, QuantInlineProblem, type QuantProblem } from './quant-errors';
import { QuantMarketChart } from './QuantMarketWorkspace';

const MAX_CSV_BYTES = 10_000_000;
type DataDirectoryTab = 'datasets' | 'connections';
type ImportSource = 'binance' | 'kraken' | 'nasdaq' | 'csv';
type CsvMarketCalendar = '24x7' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
const MARKET_INTERVALS: readonly QuantBarInterval[] = ['1h', '4h', '1D'];
const CSV_MARKET_CALENDARS: ReadonlyArray<{ value: CsvMarketCalendar; label: string }> = [
  { value: '24x7', label: '24×7 continuous' },
  { value: 'XNYS', label: 'NYSE (XNYS)' },
  { value: 'XNAS', label: 'Nasdaq (XNAS)' },
  { value: 'XSHG', label: 'Shanghai (XSHG)' },
  { value: 'XSHE', label: 'Shenzhen (XSHE)' },
];

function intervalLabel(value: QuantBarInterval): string {
  return value === '1h' ? '1 hour' : value === '4h' ? '4 hour' : '1 day';
}

function fileStem(fileName: string): string {
  return fileName.replace(/\.csv$/i, '').trim() || 'Imported OHLCV dataset';
}

function uniqueDatasets(snapshotDataset: DatasetSnapshot, datasets: DatasetSnapshot[]): DatasetSnapshot[] {
  const byId = new Map<string, DatasetSnapshot>();
  byId.set(snapshotDataset.id, snapshotDataset);
  for (const dataset of datasets) byId.set(dataset.id, dataset);
  return [...byId.values()];
}

function qualityLabel(dataset: DatasetSnapshot): string {
  if (!dataset.quality) return 'Not checked';
  if (dataset.quality.status === 'blocked') return 'Blocked';
  if (dataset.contract === 'legacy-daily-v1' && dataset.quality.status === 'warning') return 'Attention';
  return 'Verified';
}

function qualityTone(dataset: DatasetSnapshot): 'blocked' | 'warning' | 'verified' | 'unchecked' {
  if (!dataset.quality) return 'unchecked';
  if (dataset.quality.status === 'blocked') return 'blocked';
  if (dataset.contract === 'legacy-daily-v1' && dataset.quality.status === 'warning') return 'warning';
  return 'verified';
}

function coverageLabel(dataset: DatasetSnapshot): string {
  const format = (value: string) => {
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return value;
    const includesIntradayTime = value.includes('T') && !/T00:00(?::00)?(?:Z|[+-]00:00)?$/.test(value);
    return new Intl.DateTimeFormat('en', {
      timeZone: 'UTC',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      ...(includesIntradayTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
    }).format(parsed);
  };
  return `${format(dataset.dateRange.start)} – ${format(dataset.dateRange.end)} UTC`;
}

function focusAfterPaint(target: () => HTMLElement | null | undefined) {
  requestAnimationFrame(() => requestAnimationFrame(() => target()?.focus()));
}

function QuantDatasetPreviewPanel({ dataset, preview, loading, problem, selected, onRetry, onClose, onSelect }: {
  dataset: DatasetSnapshot;
  preview: QuantDatasetPreview | null;
  loading: boolean;
  problem: QuantProblem | null;
  selected: boolean;
  onRetry: () => void;
  onClose: () => void;
  onSelect: () => void;
}) {
  const canResearch = dataset.researchEligible;
  const source = dataset.source?.sourceName ?? (dataset.authenticity === 'synthetic_fixture' ? 'Synthetic fixture' : 'Imported dataset');
  const tone = qualityTone(dataset);
  return <aside className="quant-dataset-preview" aria-labelledby="quant-dataset-preview-title" aria-busy={loading}>
    <header><div><span>Dataset preview</span><h2 id="quant-dataset-preview-title">{dataset.symbol} · {dataset.interval}</h2><p>{dataset.name}</p><div className="quant-dataset-preview-status"><strong className={tone === 'blocked' ? 'is-danger' : tone === 'warning' ? 'is-warning' : 'is-positive'}>{qualityLabel(dataset)}</strong><span>{canResearch ? 'Research ready' : 'Preview only'}</span></div></div><Button onClick={onClose}>Back to catalog</Button></header>
    <dl className="quant-dataset-preview-facts"><div><dt>Coverage</dt><dd>{coverageLabel(dataset)}</dd></div><div><dt>Bars</dt><dd>{dataset.barCount.toLocaleString()}</dd></div><div><dt>Source</dt><dd>{source}</dd></div>{dataset.contract === 'market-v2' && <div><dt>Annualization</dt><dd>{dataset.periodsPerYear ? `${dataset.periodsPerYear.toLocaleString()} periods/year` : 'Unavailable'}</dd></div>}</dl>
    {dataset.quality?.status === 'blocked' && <p className="quant-preview-blocked"><strong>Research use is blocked.</strong> Review the quality findings before selecting this dataset.</p>}
    {loading && <div className="quant-preview-loading"><strong>Loading stored OHLCV…</strong><span>The preview is read from this dataset, not the current run.</span></div>}
    {problem && <QuantInlineProblem problem={problem} action={problem.retryable ? <Button onClick={onRetry}>Retry preview</Button> : undefined} />}
    {!loading && !problem && preview && <>
      <QuantMarketChart bars={preview.bars} symbol={preview.symbol} interval={preview.interval} dateRange={{ start: preview.bars[0]?.date ?? preview.coveredStart, end: preview.bars.at(-1)?.date ?? preview.coveredEnd }} title={`${preview.returnedBarCount} latest contiguous bars`} description={`${preview.symbol} stored OHLCV preview; ${preview.returnedBarCount} of ${preview.totalBarCount} bars returned using the latest contiguous rule.`} />
      <footer><span>{preview.returnedBarCount.toLocaleString()} of {preview.totalBarCount.toLocaleString()} stored bars shown · latest contiguous</span>{selected ? <strong>Current research dataset</strong> : <Button className="primary" disabled={!canResearch} title={canResearch ? undefined : 'Stored and previewable, but this dataset is not eligible for research.'} onClick={onSelect}>Use for research</Button>}</footer>
    </>}
  </aside>;
}

export function QuantDataPage({ api, snapshot, selectedDataset, onSelect, onUseForResearch, onImportViewChange, onPreviewViewChange, initialView = 'directory', initialSource = 'binance' }: {
  api: QuantApi;
  snapshot: QuantWorkspaceSnapshot;
  selectedDataset: DatasetSnapshot;
  onSelect: (dataset: DatasetSnapshot) => void;
  onUseForResearch?: (dataset: DatasetSnapshot) => void;
  onImportViewChange?: (importing: boolean) => void;
  onPreviewViewChange?: (previewing: boolean) => void;
  initialView?: 'directory' | 'import';
  initialSource?: ImportSource;
}) {
  const [datasets, setDatasets] = useState<DatasetSnapshot[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [symbol, setSymbol] = useState('');
  const [sourceName, setSourceName] = useState('');
  const [sourceReference, setSourceReference] = useState('');
  const [csvInterval, setCsvInterval] = useState<QuantBarInterval>('1D');
  const [csvMarketCalendar, setCsvMarketCalendar] =
    useState<CsvMarketCalendar>('24x7');
  const [binanceSymbol, setBinanceSymbol] = useState('BTCUSDT');
  const [binanceInterval, setBinanceInterval] = useState<QuantBarInterval>('1D');
  const [binanceLimit, setBinanceLimit] = useState(defaultMarketFetchLimit('1D'));
  const [connectors, setConnectors] = useState<QuantMarketDataConnector[]>([]);
  const [krakenSymbol, setKrakenSymbol] = useState('BTCUSD');
  const [krakenInterval, setKrakenInterval] = useState<QuantConnectorInterval>('4h');
  const [krakenLimit, setKrakenLimit] = useState(548);
  const [nasdaqSymbol, setNasdaqSymbol] = useState('AAPL');
  const [nasdaqLookbackDays, setNasdaqLookbackDays] = useState(730);
  const [showImporter, setShowImporter] = useState(initialView === 'import');
  const [importSource, setImportSource] = useState<ImportSource>(initialSource);
  const [directoryTab, setDirectoryTab] = useState<DataDirectoryTab>('datasets');
  const [directoryQuery, setDirectoryQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'all' | 'provider' | 'local'>('all');
  const [integrityFilter, setIntegrityFilter] = useState<'all' | 'verified' | 'attention'>('all');
  const [busy, setBusy] = useState(false);
  const operationLock = useRef(false);
  const hasMounted = useRef(false);
  const wasShowingImporter = useRef(showImporter);
  const [listError, setListError] = useState<QuantProblem | null>(null);
  const [connectorError, setConnectorError] = useState<QuantProblem | null>(null);
  const [importError, setImportError] = useState<QuantProblem | null>(null);
  const [binanceError, setBinanceError] = useState<QuantProblem | null>(null);
  const [krakenError, setKrakenError] = useState<QuantProblem | null>(null);
  const [nasdaqError, setNasdaqError] = useState<QuantProblem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewDataset, setPreviewDataset] = useState<DatasetSnapshot | null>(null);
  const [preview, setPreview] = useState<QuantDatasetPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewProblem, setPreviewProblem] = useState<QuantProblem | null>(null);
  const showImportView = (importing: boolean) => {
    if (operationLock.current) return;
    if (importing && previewDataset) {
      setPreviewDataset(null);
      setPreview(null);
      setPreviewProblem(null);
      onPreviewViewChange?.(false);
    }
    setShowImporter(importing);
    onImportViewChange?.(importing);
  };

  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true;
      wasShowingImporter.current = showImporter;
      if (showImporter) focusAfterPaint(() => document.getElementById(`quant-data-source-${importSource}`));
      return;
    }
    if (wasShowingImporter.current === showImporter) return;
    wasShowingImporter.current = showImporter;
    if (showImporter) {
      focusAfterPaint(() => document.getElementById(`quant-data-source-${importSource}`));
      return;
    }
    focusAfterPaint(() => document.querySelector<HTMLButtonElement>('.quant-data-directory-nav .button.primary'));
  }, [importSource, showImporter]);

  const refresh = async () => {
    const [legacy, market, connectorDirectory] = await Promise.allSettled([api.listDatasets(), api.listMarketDatasets(), api.listConnectors()]);
    const loaded = [legacy, market].flatMap((result) => result.status === 'fulfilled' ? result.value : []);
    setDatasets(loaded);
    const failures = [legacy, market].filter((result) => result.status === 'rejected');
    setListError(failures.length ? presentQuantProblem(failures[0]!.reason, failures.length === 2 ? 'Dataset list' : 'Part of the dataset list') : null);
    if (connectorDirectory.status === 'fulfilled') {
      setConnectors(connectorDirectory.value);
      setConnectorError(null);
    } else {
      setConnectorError(presentQuantProblem(connectorDirectory.reason, 'Connector directory'));
    }
  };

  const loadPreview = async (dataset: DatasetSnapshot) => {
    setPreviewDataset(dataset);
    onPreviewViewChange?.(true);
    setPreview(null);
    setPreviewProblem(null);
    setPreviewLoading(true);
    try {
      setPreview(await (dataset.contract === 'market-v2' ? api.getMarketDatasetPreview(dataset.id) : api.getDatasetPreview(dataset.id)));
    } catch (reason) {
      setPreviewProblem(presentQuantProblem(reason, 'Dataset preview'));
    } finally {
      setPreviewLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, [api]);
  useEffect(() => {
    setBinanceLimit(defaultMarketFetchLimit(binanceInterval));
  }, [binanceInterval]);
  useEffect(() => {
    if (csvInterval !== '1D') setCsvMarketCalendar('24x7');
  }, [csvInterval]);
  const krakenConnector = useMemo(
    () => connectors.find((connector) => connector.provider === 'kraken_spot') ?? null,
    [connectors],
  );
  useEffect(() => {
    if (!krakenConnector) return;
    setKrakenSymbol((current) => krakenConnector.supportedSymbols.includes(current) ? current : krakenConnector.supportedSymbols[0]!);
    setKrakenInterval((current) => krakenConnector.supportedIntervals.includes(current) ? current : krakenConnector.supportedIntervals[0]!);
  }, [krakenConnector]);
  useEffect(() => {
    if (!krakenConnector) return;
    setKrakenLimit(krakenConnector.minimumRecentBars[krakenInterval]);
  }, [krakenConnector, krakenInterval]);
  const sourceTabs = useMemo<ImportSource[]>(
    () => krakenConnector ? ['binance', 'kraken', 'nasdaq', 'csv'] : ['binance', 'nasdaq', 'csv'],
    [krakenConnector],
  );

  const allDatasets = useMemo(
    () => uniqueDatasets(snapshot.dataset, datasets),
    [datasets, snapshot.dataset],
  );
  const visibleDatasets = useMemo(() => allDatasets.filter((dataset) => {
    const query = directoryQuery.trim().toLowerCase();
    const sourceKind = dataset.source?.kind === 'provider_fetch' ? 'provider' : 'local';
    const tone = qualityTone(dataset);
    const integrity = tone === 'unchecked' || tone === 'blocked' || tone === 'warning' ? 'attention' : 'verified';
    return (!query || `${dataset.symbol} ${dataset.name} ${dataset.source?.sourceName ?? ''}`.toLowerCase().includes(query))
      && (sourceFilter === 'all' || sourceFilter === sourceKind)
      && (integrityFilter === 'all' || integrityFilter === integrity);
  }), [allDatasets, directoryQuery, integrityFilter, sourceFilter]);
  const onDirectoryTabKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const tabs: DataDirectoryTab[] = ['datasets', 'connections'];
    const current = tabs.indexOf(directoryTab);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = tabs[next] ?? directoryTab;
    setDirectoryTab(nextTab);
    requestAnimationFrame(() => document.getElementById(`quant-data-tab-${nextTab}`)?.focus());
  };

  const onSourceTabKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const current = sourceTabs.indexOf(importSource);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % sourceTabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + sourceTabs.length) % sourceTabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = sourceTabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = sourceTabs[next] ?? importSource;
    setImportSource(nextTab);
    requestAnimationFrame(() => document.getElementById(`quant-data-source-${nextTab}`)?.focus());
  };

  const focusAlert = (id: string) => {
    focusAfterPaint(() => {
      const node = document.getElementById(id);
      if (!node) return null;
      return node.querySelector<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')
        ?? node;
    });
  };

  const focusField = (selector: string) => {
    focusAfterPaint(() => document.querySelector<HTMLElement>(selector));
  };

  const chooseFile = (nextFile: File | null) => {
    setFile(nextFile);
    setImportError(null);
    setNotice(null);
    if (!nextFile) return;
    if (nextFile.size > MAX_CSV_BYTES) {
      setImportError(presentQuantProblem('CSV files must be 10 MB or smaller.', 'CSV import'));
      focusField('[aria-label="OHLCV CSV file"]');
      return;
    }
    setName((current) => current || fileStem(nextFile.name));
  };

  const importCsv = async () => {
    if (!file || operationLock.current) return;
    if (file.size > MAX_CSV_BYTES) {
      setImportError(presentQuantProblem('CSV files must be 10 MB or smaller.', 'CSV import'));
      focusField('[aria-label="OHLCV CSV file"]');
      return;
    }
    if (!name.trim() || !symbol.trim()) {
      setImportError(presentQuantProblem('A dataset name and symbol are required.', 'CSV import'));
      focusField(!name.trim() ? '[aria-label="Dataset name"]' : '[aria-label="Dataset symbol"]');
      return;
    }
    operationLock.current = true;
    setBusy(true);
    setImportError(null);
    setNotice(null);
    try {
      const dataset = await api.importMarketDatasetCsv({
        name: name.trim(),
        symbol: symbol.trim(),
        interval: csvInterval,
        marketCalendar: csvMarketCalendar,
        csvText: await file.text(),
        fileName: file.name,
        sourceName: sourceName.trim() || 'User-provided CSV',
        sourceReference: sourceReference.trim() || undefined,
        idempotencyKey: quantIdempotencyKey(),
      });
      setDatasets((current) => uniqueDatasets(dataset, current));
      setFile(null);
      setName('');
      setSymbol('');
      setSourceName('');
      setSourceReference('');
      setCsvInterval('1D');
      setCsvMarketCalendar('24x7');
      setNotice(`${dataset.name} was imported as an immutable dataset.`);
      await refresh();
      setShowImporter(false);
      onImportViewChange?.(false);
    } catch (reason) {
      setImportError(presentQuantProblem(reason, 'CSV import'));
      focusAlert('quant-import-error');
    } finally {
      operationLock.current = false;
      setBusy(false);
    }
  };

  const fetchBinanceSpot = async () => {
    if (operationLock.current) return;
    operationLock.current = true;
    setBusy(true);
    setBinanceError(null);
    setNotice(null);
    try {
      const dataset = await api.fetchMarketBinanceDataset({
        name: `${binanceSymbol.trim().toUpperCase() || 'BTCUSDT'} Binance Spot ${intervalLabel(binanceInterval)}`,
        symbol: binanceSymbol.trim().toUpperCase() || 'BTCUSDT',
        interval: binanceInterval,
        limit: Math.max(1, Math.min(5000, binanceLimit || defaultMarketFetchLimit(binanceInterval))),
        idempotencyKey: quantIdempotencyKey(),
      });
      setDatasets((current) => uniqueDatasets(dataset, current));
      setNotice(`${dataset.name} was fetched and stored as an immutable dataset.`);
      await refresh();
      setShowImporter(false);
      onImportViewChange?.(false);
    } catch (reason) {
      setBinanceError(presentQuantProblem(reason, 'Binance data fetch'));
      focusAlert('quant-binance-error');
    } finally {
      operationLock.current = false;
      setBusy(false);
    }
  };

  const fetchKrakenSpot = async () => {
    if (!krakenConnector || operationLock.current) return;
    operationLock.current = true;
    setBusy(true);
    setKrakenError(null);
    setNotice(null);
    try {
      const dataset = await api.fetchConnectorDataset({
        connectorId: krakenConnector.id,
        name: `${krakenSymbol} Kraken Spot ${intervalLabel(krakenInterval)}`,
        symbol: krakenSymbol,
        interval: krakenInterval,
        limit: Math.max(
          krakenConnector.minimumRecentBars[krakenInterval],
          Math.min(krakenConnector.maximumRecentBars, krakenLimit || krakenConnector.minimumRecentBars[krakenInterval]),
        ),
        idempotencyKey: quantIdempotencyKey(),
      });
      setDatasets((current) => uniqueDatasets(dataset, current));
      setNotice(`${dataset.name} was fetched and stored as an immutable dataset.`);
      await refresh();
      setDirectoryTab('datasets');
      setShowImporter(false);
      onImportViewChange?.(false);
    } catch (reason) {
      setKrakenError(presentQuantProblem(reason, 'Kraken data fetch'));
      focusAlert('quant-kraken-error');
    } finally {
      operationLock.current = false;
      setBusy(false);
    }
  };

  const fetchNasdaqEquity = async () => {
    if (operationLock.current) return;
    operationLock.current = true;
    setBusy(true);
    setNasdaqError(null);
    setNotice(null);
    try {
      const dataset = await api.fetchNasdaqEquityDataset({
        symbol: nasdaqSymbol.trim().toUpperCase() || 'AAPL',
        lookbackDays: Math.max(370, Math.min(3650, nasdaqLookbackDays || 730)),
        idempotencyKey: quantIdempotencyKey(),
      });
      setDatasets((current) => uniqueDatasets(dataset, current));
      onSelect(dataset);
      setNotice(`${dataset.name} was fetched and stored as an immutable dataset.`);
      await refresh();
      setShowImporter(false);
      onImportViewChange?.(false);
    } catch (reason) {
      setNasdaqError(presentQuantProblem(reason, 'Nasdaq data fetch'));
      focusAlert('quant-nasdaq-error');
    } finally {
      operationLock.current = false;
      setBusy(false);
    }
  };

  if (!showImporter) return <div className="quant-data-directory">
    <h1 className="quant-visually-hidden">Data directory</h1>
    <div className="quant-data-directory-nav"><div className="quant-data-directory-tabs" role="tablist" aria-label="Data directory views" onKeyDown={onDirectoryTabKeyDown}>{(['datasets', 'connections'] as const).map((tab) => <button key={tab} id={`quant-data-tab-${tab}`} role="tab" aria-controls={`quant-data-panel-${tab}`} aria-selected={directoryTab === tab} tabIndex={directoryTab === tab ? 0 : -1} className={directoryTab === tab ? 'active' : undefined} onClick={() => setDirectoryTab(tab)}>{tab === 'datasets' ? 'Catalog' : 'Connections'}</button>)}</div><span className="quant-data-directory-count">{allDatasets.length} dataset{allDatasets.length === 1 ? '' : 's'}</span><Button className="primary" onClick={() => showImportView(true)}>Add data</Button></div>
    {notice && <p className="quant-data-notice" role="status">{notice}</p>}
    {directoryTab === 'datasets' && <section className={`quant-data-catalog-layout${previewDataset ? ' has-preview' : ''}`} id="quant-data-panel-datasets" role="tabpanel" aria-labelledby="quant-data-tab-datasets">
      <div className="quant-data-directory-table quant-data-catalog-list">
        <div className="quant-data-directory-tools"><input aria-label="Search datasets" placeholder="Search by symbol, name, or source" value={directoryQuery} onChange={(event) => setDirectoryQuery(event.target.value)} /><select aria-label="Dataset source filter" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as typeof sourceFilter)}><option value="all">All sources</option><option value="provider">Providers</option><option value="local">Local/imported</option></select><select aria-label="Dataset quality filter" value={integrityFilter} onChange={(event) => setIntegrityFilter(event.target.value as typeof integrityFilter)}><option value="all">All quality states</option><option value="verified">Quality verified</option><option value="attention">Needs review</option></select></div>
        {listError && <QuantInlineProblem problem={listError} action={listError.retryable ? <Button onClick={() => void refresh()}>Retry dataset list</Button> : undefined} />}
        <table className="quant-research-table">
        <caption className="quant-visually-hidden">Available research datasets</caption>
        <thead><tr><th>Dataset</th><th>Coverage</th><th>Quality</th><th className="is-action">Action</th></tr></thead>
        <tbody>{visibleDatasets.map((dataset) => {
          const isSelected = dataset.id === selectedDataset.id;
          const canResearch = dataset.researchEligible;
          const tone = qualityTone(dataset);
          const source = dataset.source?.sourceName ?? (dataset.authenticity === 'synthetic_fixture' ? 'Synthetic fixture' : 'Imported');
          return <tr key={dataset.id} className={isSelected ? 'is-selected' : undefined}><td><strong>{dataset.symbol}</strong><small>{dataset.name} · {dataset.interval}</small><small className="quant-dataset-source">{source}</small></td><td>{coverageLabel(dataset)}</td><td><span className={tone === 'blocked' ? 'is-danger' : tone === 'warning' ? 'is-warning' : tone === 'verified' ? 'is-positive' : undefined}>{qualityLabel(dataset)}</span><small className="quant-dataset-bars">{dataset.barCount.toLocaleString()} bars</small></td><td className="is-action"><div className="quant-dataset-actions"><Button onClick={() => void loadPreview(dataset)}>Preview</Button>{isSelected ? <span className="quant-dataset-selected">Current</span> : <Button disabled={!canResearch} title={canResearch ? undefined : 'Stored and previewable, but not research eligible'} onClick={() => (onUseForResearch ?? onSelect)(dataset)}>Use</Button>}</div></td></tr>;
        })}</tbody>
      </table>
      {visibleDatasets.length === 0 && <div className="quant-data-empty"><strong>No matching datasets</strong><span>Clear the search or broaden the source and integrity filters.</span><button onClick={() => { setDirectoryQuery(''); setSourceFilter('all'); setIntegrityFilter('all'); }}>Clear filters</button></div>}
      </div>
      {previewDataset && <QuantDatasetPreviewPanel dataset={previewDataset} preview={preview} loading={previewLoading} problem={previewProblem} selected={previewDataset.id === selectedDataset.id} onRetry={() => void loadPreview(previewDataset)} onClose={() => { setPreviewDataset(null); setPreview(null); setPreviewProblem(null); onPreviewViewChange?.(false); }} onSelect={() => (onUseForResearch ?? onSelect)(previewDataset)} />}
    </section>}
    {directoryTab === 'connections' && <section className="quant-data-directory-panel" id="quant-data-panel-connections" role="tabpanel" aria-labelledby="quant-data-tab-connections"><header><strong>Available sources</strong></header>{connectorError && <QuantInlineProblem problem={connectorError} action={connectorError.retryable ? <Button onClick={() => void refresh()}>Retry connector directory</Button> : undefined} />}<dl><div><dt>Binance Spot<small>Supported `1h`, `4h`, and `1D` public OHLCV with retained provider batch evidence</small></dt><dd className="is-positive">Available · public API</dd></div>{connectors.map((connector) => <div key={connector.id}><dt>{connector.displayName}<small>{connector.supportedIntervals.join(' and ')} · {connector.supportedSymbols.join(', ')}</small></dt><dd><Button onClick={() => { setImportSource('kraken'); showImportView(true); }}>Fetch data</Button></dd></div>)}<div><dt>Nasdaq Equity<small>Daily equity OHLCV with corporate-action coverage</small></dt><dd className="is-positive">Available · public API</dd></div><div><dt>CSV upload<small>Explicit local upload for supported `1h`, `4h`, and `1D` market-bar datasets</small></dt><dd className="is-positive">Available</dd></div><div><dt>Wind<small>User-owned Wind Client API or Server API entitlement required; a Kimi membership or Kimi Work plugin does not grant Qurio backend access.</small></dt><dd>Not installed · licensed API required</dd></div></dl></section>}
  </div>;

  return <div className="quant-page quant-data-page" aria-busy={busy}>
    <div className="quant-page-title"><div><h1>Add market data</h1><p>Choose a source, define the market window, then fetch and validate it for the research catalog.</p></div><Button disabled={busy} onClick={() => showImportView(false)}>Back</Button></div>
    <div className="quant-data-source-tabs" role="tablist" aria-label="Data source" onKeyDown={onSourceTabKeyDown}>{sourceTabs.map((source) => <button key={source} disabled={busy} id={`quant-data-source-${source}`} role="tab" aria-controls={`quant-data-source-panel-${source}`} aria-selected={importSource === source} tabIndex={importSource === source ? 0 : -1} onClick={() => setImportSource(source)}>{source === 'binance' ? 'Binance Spot' : source === 'kraken' ? krakenConnector?.displayName ?? 'Kraken Spot' : source === 'nasdaq' ? 'Nasdaq Equity' : 'CSV upload'}</button>)}</div>
    {importSource === 'binance' && <section id="quant-data-source-panel-binance" role="tabpanel" aria-labelledby="quant-data-source-binance" className="quant-data-import" aria-busy={busy}><header><h2>Spot OHLCV</h2><p>Fetch supported `1h`, `4h`, or `1D` completed bars. Provider batch evidence and the normalized digest are retained.</p></header><div className="quant-data-provider-fields"><label><span>Spot symbol</span><input aria-label="Binance Spot symbol" value={binanceSymbol} disabled={busy} aria-invalid={Boolean(binanceError)} aria-describedby={binanceError ? 'quant-binance-error' : undefined} onChange={(event) => setBinanceSymbol(event.target.value.toUpperCase())} /></label><label><span>Interval</span><select aria-label="Binance Spot interval" value={binanceInterval} disabled={busy} aria-invalid={Boolean(binanceError)} aria-describedby={binanceError ? 'quant-binance-error' : undefined} onChange={(event) => setBinanceInterval(event.target.value as QuantBarInterval)}>{MARKET_INTERVALS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label><span>Bar limit</span><input aria-label="Binance Spot bar limit" type="number" min="1" max="5000" value={binanceLimit} disabled={busy} aria-invalid={Boolean(binanceError)} aria-describedby={binanceError ? 'quant-binance-error quant-binance-limit-help' : 'quant-binance-limit-help'} onChange={(event) => setBinanceLimit(Number(event.target.value))} /></label></div><footer><span id="quant-binance-limit-help">{busy ? 'Validating provider response and storing an immutable version…' : `Suggested for ${binanceInterval}: ${marketResearchRequirementLabel(binanceInterval, null)}; shorter retained datasets stay previewable.`}</span><Button className="primary" disabled={busy} onClick={() => void fetchBinanceSpot()}>{busy ? 'Fetching and validating…' : 'Fetch and validate'}</Button></footer>{binanceError && <div id="quant-binance-error" tabIndex={-1}><QuantInlineProblem problem={binanceError} action={binanceError.retryable ? <Button onClick={() => void fetchBinanceSpot()}>Retry fetch</Button> : undefined} /></div>}</section>}
    {importSource === 'kraken' && krakenConnector && <section id="quant-data-source-panel-kraken" role="tabpanel" aria-labelledby="quant-data-source-kraken" className="quant-data-import" aria-busy={busy}><header><h2>Kraken Spot OHLCV</h2><p>Fetch a recent public `4h` or `1D` window through the installed connector. Qurio validates and stores the result in the same research catalog.</p></header><div className="quant-data-provider-fields"><label><span>Spot symbol</span><select aria-label="Kraken Spot symbol" value={krakenSymbol} disabled={busy} aria-invalid={Boolean(krakenError)} aria-describedby={krakenError ? 'quant-kraken-error' : undefined} onChange={(event) => setKrakenSymbol(event.target.value)}>{krakenConnector.supportedSymbols.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label><span>Interval</span><select aria-label="Kraken Spot interval" value={krakenInterval} disabled={busy} aria-invalid={Boolean(krakenError)} aria-describedby={krakenError ? 'quant-kraken-error' : undefined} onChange={(event) => setKrakenInterval(event.target.value as QuantConnectorInterval)}>{krakenConnector.supportedIntervals.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label><span>Recent bars</span><input aria-label="Kraken Spot bar limit" type="number" min={krakenConnector.minimumRecentBars[krakenInterval]} max={krakenConnector.maximumRecentBars} value={krakenLimit} disabled={busy} aria-invalid={Boolean(krakenError)} aria-describedby={krakenError ? 'quant-kraken-error quant-kraken-limit-help' : 'quant-kraken-limit-help'} onChange={(event) => setKrakenLimit(Number(event.target.value))} /></label></div><footer><span id="quant-kraken-limit-help">{busy ? 'Validating connector response and storing an immutable version…' : `${krakenConnector.minimumRecentBars[krakenInterval]}–${krakenConnector.maximumRecentBars} recent completed bars · public market data`}</span><Button className="primary" disabled={busy} onClick={() => void fetchKrakenSpot()}>{busy ? 'Fetching and validating…' : 'Fetch and validate'}</Button></footer>{krakenError && <div id="quant-kraken-error" tabIndex={-1}><QuantInlineProblem problem={krakenError} action={krakenError.retryable ? <Button onClick={() => void fetchKrakenSpot()}>Retry fetch</Button> : undefined} /></div>}</section>}
    {importSource === 'nasdaq' && <section id="quant-data-source-panel-nasdaq" role="tabpanel" aria-labelledby="quant-data-source-nasdaq" className="quant-data-import"><header><h2>Daily equity OHLCV</h2><p>Fetch server-normalized prices with retained provider and corporate-action evidence.</p></header><div className="quant-data-provider-fields"><label><span>Equity symbol</span><input aria-label="Nasdaq Equity symbol" value={nasdaqSymbol} disabled={busy} aria-invalid={Boolean(nasdaqError)} aria-describedby={nasdaqError ? 'quant-nasdaq-error' : undefined} onChange={(event) => setNasdaqSymbol(event.target.value.toUpperCase())} /></label><label><span>Lookback days</span><input aria-label="Nasdaq Equity lookback days" type="number" min="370" max="3650" value={nasdaqLookbackDays} disabled={busy} aria-invalid={Boolean(nasdaqError)} aria-describedby={nasdaqError ? 'quant-nasdaq-error' : undefined} onChange={(event) => setNasdaqLookbackDays(Number(event.target.value))} /></label></div><footer><Button className="primary" disabled={busy} onClick={() => void fetchNasdaqEquity()}>{busy ? 'Fetching and validating…' : 'Fetch and validate'}</Button></footer>{nasdaqError && <div id="quant-nasdaq-error" tabIndex={-1}><QuantInlineProblem problem={nasdaqError} action={nasdaqError.retryable ? <Button onClick={() => void fetchNasdaqEquity()}>Retry fetch</Button> : undefined} /></div>}</section>}
    {importSource === 'csv' && <section id="quant-data-source-panel-csv" role="tabpanel" aria-labelledby="quant-data-source-csv" className="quant-data-import">
      <header>
        <h2>Market OHLCV CSV</h2>
        <p>
          Upload a supported `1h`, `4h`, or `1D` market-bar CSV. Continuous
          markets use an RFC3339 `timestamp`; exchange daily bars use an ISO
          `date` session label. Qurio does not infer holiday completeness.
        </p>
      </header>
      <div className="quant-data-csv-fields">
        <label><span>CSV file</span><input aria-label="OHLCV CSV file" type="file" accept=".csv,text/csv" disabled={busy} aria-invalid={Boolean(importError)} aria-describedby={importError ? 'quant-import-error' : undefined} onChange={(event) => chooseFile(event.target.files?.[0] ?? null)} /></label>
        <label><span>Dataset interval</span><select aria-label="Dataset interval" value={csvInterval} disabled={busy} aria-invalid={Boolean(importError)} aria-describedby={importError ? 'quant-import-error' : undefined} onChange={(event) => setCsvInterval(event.target.value as QuantBarInterval)}>{MARKET_INTERVALS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label>
          <span>Market calendar</span>
          <select
            aria-label="Market calendar"
            value={csvMarketCalendar}
            disabled={busy || csvInterval !== '1D'}
            onChange={(event) => setCsvMarketCalendar(event.target.value as CsvMarketCalendar)}
          >
            {CSV_MARKET_CALENDARS.map((calendar) => <option key={calendar.value} value={calendar.value}>{calendar.label}</option>)}
          </select>
        </label>
        <label><span>Dataset name</span><input aria-label="Dataset name" value={name} disabled={busy} aria-invalid={Boolean(importError && !name.trim())} aria-describedby={importError ? 'quant-import-error' : undefined} onChange={(event) => setName(event.target.value)} /></label>
        <label><span>Symbol</span><input aria-label="Dataset symbol" value={symbol} disabled={busy} aria-invalid={Boolean(importError && !symbol.trim())} aria-describedby={importError ? 'quant-import-error' : undefined} placeholder="BTCUSDT" onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label>
      </div>
      <details className="quant-data-import-advanced"><summary>Source metadata</summary><div><label><span>Source/provider</span><input aria-label="Dataset source provider" value={sourceName} disabled={busy} placeholder="Exchange, vendor, or research source" onChange={(event) => setSourceName(event.target.value)} /></label><label><span>Source reference</span><input aria-label="Dataset source reference" value={sourceReference} disabled={busy} placeholder="URL, export ID, or internal reference" onChange={(event) => setSourceReference(event.target.value)} /></label></div></details>
      <footer><span>CSV only · 10 MB maximum</span><Button className="primary" disabled={!file || busy} onClick={() => void importCsv()}>{busy ? 'Importing and validating…' : 'Import and validate'}</Button></footer>
      {importError && <div id="quant-import-error" tabIndex={-1}><QuantInlineProblem problem={importError} action={importError.retryable && file ? <Button onClick={() => void importCsv()}>Retry import</Button> : undefined} /></div>}
    </section>}
  </div>;
}
