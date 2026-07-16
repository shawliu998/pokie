import type React from 'react';
import { Badge } from '@glint/ui';

export function DetailHeader({ title, status }: { title: string; status: React.ReactNode }) { return <header className="detail-header"><h2>{title}</h2><div>{status}</div></header>; }
export function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="section"><h3>{title}</h3>{children}</section>; }
export function ContentBlock({ type, title, children }: { type: string; title: string; children: React.ReactNode }) { return <section className="content-block"><Badge tone={type === 'Fact' ? 'neutral' : type === 'PM judgment' ? 'info' : 'warning'}>{type}</Badge><h3>{title}</h3>{children}</section>; }
