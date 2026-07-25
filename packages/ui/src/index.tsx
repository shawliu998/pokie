import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  LabelHTMLAttributes,
  PropsWithChildren,
  ReactNode,
} from 'react';

type BadgeSize = 'xs' | 'sm' | 'md';

export function Badge({ children, tone = 'neutral', size = 'sm' }: PropsWithChildren<{ tone?: 'neutral' | 'info' | 'warning' | 'positive'; size?: BadgeSize }>) {
  return <span data-slot="badge" data-tone={tone} data-size={size} className={`badge badge-${tone}`}>{children}</span>;
}

export function Status({ children, tone = 'neutral', size = 'sm' }: PropsWithChildren<{ tone?: 'neutral' | 'info' | 'warning' | 'positive' | 'danger'; size?: BadgeSize }>) {
  return <span data-slot="status" data-tone={tone} data-size={size} className={`status status-${tone}`}><span aria-hidden="true">●</span>{children}</span>;
}

type ButtonVariant = 'primary' | 'outline' | 'soft' | 'ghost' | 'destructive';
type ButtonSize = 'sm' | 'md' | 'lg';

export function Button({
  children,
  className = '',
  variant,
  size = 'sm',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  const resolvedVariant = variant ?? (className.split(/\s+/).includes('primary') ? 'primary' : 'outline');
  return <button
    data-slot="button"
    data-variant={resolvedVariant}
    data-size={size}
    type={type}
    className={`button ${className}`}
    {...props}
  >{children}</button>;
}

export function Field({ children, className = '', ...props }: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return <div data-slot="field" className={`field ${className}`} {...props}>{children}</div>;
}

export function FieldLabel({ children, className = '', ...props }: PropsWithChildren<LabelHTMLAttributes<HTMLLabelElement>>) {
  return <label data-slot="field-label" className={`field-label ${className}`} {...props}>{children}</label>;
}

export function FieldDescription({ children, className = '', ...props }: PropsWithChildren<HTMLAttributes<HTMLParagraphElement>>) {
  return <p data-slot="field-description" className={`field-description ${className}`} {...props}>{children}</p>;
}

export function FieldError({ children, className = '', ...props }: PropsWithChildren<HTMLAttributes<HTMLParagraphElement>>) {
  return <p data-slot="field-error" className={`field-error ${className}`} role="alert" {...props}>{children}</p>;
}

export function Kbd({ children, className = '', ...props }: PropsWithChildren<HTMLAttributes<HTMLElement>>) {
  return <kbd data-slot="kbd" className={`kbd ${className}`} {...props}>{children}</kbd>;
}

export function Skeleton({ className = '', effect = 'shimmer', ...props }: HTMLAttributes<HTMLDivElement> & { effect?: 'shimmer' | 'pulse' | 'none' }) {
  return <div data-slot="skeleton" data-effect={effect} aria-hidden="true" className={`skeleton ${className}`} {...props} />;
}

export function EmptyState({ title, body, action }: { title: string; body: string; action: ReactNode }) {
  return <div data-slot="empty-state" className="empty-state"><h2>{title}</h2><p>{body}</p>{action}</div>;
}
