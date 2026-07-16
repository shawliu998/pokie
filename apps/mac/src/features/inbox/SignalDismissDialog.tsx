import { useState } from 'react';
import { Button } from '@glint/ui';
import type { SignalDismissReason } from '../../api';
import type { Signal } from '../../domain';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';

const reasons: Array<[SignalDismissReason, string]> = [
  ['duplicate', 'Duplicate'], ['single_author_spike', 'Single-author spike'], ['irrelevant', 'Irrelevant'], ['known_issue', 'Known issue'], ['bad_data', 'Bad data'], ['other', 'Other'],
];

export function SignalDismissDialog({ signal, disabled, onClose, onConfirm }: { signal: Signal; disabled: boolean; onClose: () => void; onConfirm: (reason: SignalDismissReason, note: string) => void }) {
  const [reason, setReason] = useState<SignalDismissReason | ''>('');
  const [note, setNote] = useState('');
  useEscapeToClose(onClose);
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Dismiss Signal"><h2>Dismiss Signal</h2><p><strong>{signal.title}</strong></p><p>Dismissal is an audited disposition. It does not delete the Signal or its source evidence.</p><label>Reason<select aria-label="Dismiss reason" value={reason} onChange={(event) => setReason(event.target.value as SignalDismissReason)}><option value="">Select a reason</option>{reasons.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label>Decision note<textarea aria-label="Dismiss note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Explain why this Signal should leave the active Inbox." /></label><div className="modal-actions"><Button onClick={onClose}>Cancel</Button><Button className="primary" disabled={disabled || !reason || !note.trim()} onClick={() => { if (reason) onConfirm(reason, note.trim()); }}>Dismiss Signal</Button></div></section></div>;
}
