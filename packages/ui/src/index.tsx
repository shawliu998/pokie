import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from 'react';

export function Badge({ children, tone = 'neutral' }: PropsWithChildren<{ tone?: 'neutral' | 'info' | 'warning' | 'positive' }>) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Status({ children, tone = 'neutral' }: PropsWithChildren<{ tone?: 'neutral' | 'info' | 'warning' | 'positive' | 'danger' }>) {
  return <span className={`status status-${tone}`}><span aria-hidden="true">●</span>{children}</span>;
}

export function Button({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`button ${className}`} {...props}>{children}</button>;
}

export function EmptyState({ title, body, action }: { title: string; body: string; action: ReactNode }) {
  return <div className="empty-state"><h2>{title}</h2><p>{body}</p>{action}</div>;
}
