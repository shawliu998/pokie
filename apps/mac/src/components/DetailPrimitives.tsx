import type React from 'react';
import { Badge } from '@glint/ui';

export function DetailHeader({ title, status }: { title: string; status: React.ReactNode }) { return <header className="detail-header"><h2>{title}</h2><div>{status}</div></header>; }
export function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="section"><h3>{title}</h3>{children}</section>; }
export function ContentBlock({ type, title, children }: { type: string; title: string; children: React.ReactNode }) { return <section className="content-block"><Badge tone={type === 'Fact' ? 'neutral' : type === 'PM judgment' ? 'info' : 'warning'}>{type}</Badge><h3>{title}</h3>{children}</section>; }

export function CollaborationSummary({ activity, responsibility, statusReason, reviewed = false }: { activity: string; responsibility: string; statusReason: string; reviewed?: boolean }) {
  return <details className="progressive-disclosure"><summary>Collaboration</summary><dl className="collaboration-grid"><dt>Owner</dt><dd>Workspace owner</dd><dt>Reviewer</dt><dd>{reviewed ? 'Review recorded; identity unavailable in this view' : 'Not assigned'}</dd><dt>Last reviewed by</dt><dd>{reviewed ? 'Identity not exposed in this projection' : 'No completed review'}</dd><dt>Review timestamp</dt><dd>{reviewed ? 'Not exposed in this projection' : 'Not reviewed'}</dd><dt>Status reason</dt><dd>{statusReason}</dd><dt>Activity summary</dt><dd>{activity}</dd><dt>Decision responsibility</dt><dd>{responsibility}</dd></dl></details>;
}
