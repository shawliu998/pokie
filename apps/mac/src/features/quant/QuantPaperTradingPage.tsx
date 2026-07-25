import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '@glint/ui';
import {
  quantIdempotencyKey,
  type PaperOrder,
  type PaperSnapshot,
  type QuantApi,
} from '../../quant-api';
import type { QuantWorkspaceSnapshot } from '../../quant-domain';
import { projectPaperTradingEligibility } from './quant-presentation';

function money(value: string): string {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(number)
    : '—';
}

function number(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString('en-US', { maximumFractionDigits: 8 }) : '—';
}

export function QuantPaperTradingPage({
  api,
  research,
  onOpenDecision,
}: {
  api: QuantApi;
  research: QuantWorkspaceSnapshot;
  onOpenDecision?: () => void;
}) {
  const [paper, setPaper] = useState<PaperSnapshot | null>(null);
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [quantity, setQuantity] = useState('1');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eligibility = projectPaperTradingEligibility(research);
  const selectedCandidateId = eligibility.candidateId;
  const selectedCandidate = useMemo(
    () => research.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? null,
    [research.candidates, selectedCandidateId],
  );
  const eligible = eligibility.eligible && selectedCandidate !== null;

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setPaper(await api.getPaperSnapshot());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Paper account could not be loaded.');
    }
  }, [api]);

  useEffect(() => { void refresh(); }, [refresh]);

  const mutate = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Paper action failed.');
    } finally {
      setBusy(false);
    }
  };

  const createDraft = () => {
    if (!paper || !selectedCandidateId) return;
    void mutate(() => api.createPaperDraft({
      sourceRunId: research.run.id,
      sourceCandidateId: selectedCandidateId,
      side,
      quantity,
      orderType: 'market',
      timeInForce: 'day',
      expectedAccountRowVersion: paper.account.rowVersion,
      idempotencyKey: quantIdempotencyKey(),
    }));
  };

  const submit = (order: PaperOrder) => {
    if (!paper) return;
    void mutate(() => api.submitPaperOrder(
      order.orderId,
      order.rowVersion,
      paper.account.rowVersion,
      quantIdempotencyKey(),
    ));
  };

  const cancel = (order: PaperOrder) => {
    void mutate(() => api.cancelPaperOrder(order.orderId, order.rowVersion, quantIdempotencyKey()));
  };

  return <div className="quant-paper-page">
    <header className="quant-paper-heading">
      <div>
        <p className="quant-paper-label">Simulation only</p>
        <h1>Paper Trading</h1>
        <p>Move a retained research candidate into an isolated account, review the order, then observe simulated execution.</p>
      </div>
      <div className="quant-paper-boundary"><strong>Local simulator</strong><span>No live-trading route or live credentials</span></div>
    </header>

    {error && <div className="quant-paper-error" role="alert">{error}</div>}

    {paper ? <>
      <section className="quant-paper-account" aria-label="Paper account">
        <div><span>Equity</span><strong>{money(paper.account.equity)}</strong></div>
        <div><span>Cash</span><strong>{money(paper.account.cash)}</strong></div>
        <div><span>Buying power</span><strong>{money(paper.account.buyingPower)}</strong></div>
        <Button disabled={busy} onClick={() => void mutate(() => api.reconcilePaperAccount(paper.account.rowVersion, quantIdempotencyKey()))}>Reconcile</Button>
      </section>

      <div className="quant-paper-grid">
        <section className="quant-paper-ticket" aria-labelledby="paper-ticket-title">
          <header><div><p className="quant-paper-label">Research handoff</p><h2 id="paper-ticket-title">Create order draft</h2></div><span>{research.scope.symbol}</span></header>
          <dl>
            <div><dt>Run</dt><dd>{research.project.title}</dd></div>
            <div><dt>Candidate</dt><dd>{selectedCandidate?.name ?? 'No retained final candidate'}</dd></div>
            <div><dt>Evidence</dt><dd>{eligibility.reason}</dd></div>
          </dl>
          <div className="quant-paper-fields">
            <label>Side<select value={side} onChange={(event) => setSide(event.target.value as 'buy' | 'sell')}><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
            <label>Quantity<input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
            <label>Order type<input value="Market · Day" readOnly /></label>
          </div>
          <Button disabled={!eligible || busy || Number(quantity) <= 0} onClick={createDraft}>Review draft</Button>
          {!eligible && eligibility.canOpenDecision && onOpenDecision && <Button className="quant-paper-open-decision" onClick={onOpenDecision}>Open decision</Button>}
        </section>

        <section className="quant-paper-orders" aria-labelledby="paper-orders-title">
          <header><h2 id="paper-orders-title">Orders</h2><span>{paper.orders.length}</span></header>
          {paper.orders.length === 0 ? <p className="quant-paper-empty">No orders yet. Create a draft from the retained research result.</p> : <div className="quant-paper-table-wrap"><table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Est. value</th><th>Status</th><th aria-label="Actions" /></tr></thead><tbody>{paper.orders.map((order) => <tr key={order.orderId}><td>{order.symbol}</td><td>{order.side}</td><td>{number(order.quantity)}</td><td>{money(order.estimatedNotional)}</td><td>{order.state.replace('_', ' ')}</td><td>{order.state === 'draft' && <div className="quant-paper-row-actions"><button disabled={busy} onClick={() => submit(order)}>Submit</button><button disabled={busy} onClick={() => cancel(order)}>Cancel</button></div>}</td></tr>)}</tbody></table></div>}
        </section>
      </div>

      <section className="quant-paper-ledger" aria-labelledby="paper-positions-title">
        <header><h2 id="paper-positions-title">Positions</h2><span>{paper.positions.length} open</span></header>
        {paper.positions.length === 0 ? <p className="quant-paper-empty">No open positions.</p> : <div className="quant-paper-table-wrap"><table><thead><tr><th>Symbol</th><th>Quantity</th><th>Avg. entry</th><th>Market value</th><th>Unrealized P/L</th></tr></thead><tbody>{paper.positions.map((position) => <tr key={position.symbol}><td>{position.symbol}</td><td>{number(position.quantity)}</td><td>{money(position.averageEntryPrice)}</td><td>{money(position.marketValue)}</td><td>{money(position.unrealizedPl)}</td></tr>)}</tbody></table></div>}
      </section>
    </> : <div className="quant-paper-loading" role="status" aria-label="Loading isolated Paper account"><span /><span /><span /></div>}
  </div>;
}
