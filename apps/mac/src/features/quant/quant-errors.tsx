import type { ReactNode } from 'react';

export type QuantProblemKind = 'offline' | 'timeout' | 'rate_limit' | 'session' | 'conflict' | 'validation' | 'unknown';

export interface QuantProblem {
  kind: QuantProblemKind;
  title: string;
  detail: string;
  retryable: boolean;
}

function errorMessage(reason: unknown): string {
  if (reason instanceof Error && reason.message.trim()) return reason.message.trim();
  if (typeof reason === 'string' && reason.trim()) return reason.trim();
  return 'No additional diagnostics were returned.';
}

export function presentQuantProblem(reason: unknown, operation = 'The request'): QuantProblem {
  const detail = errorMessage(reason);
  const normalized = detail.toLowerCase();
  if (/failed to fetch|networkerror|network error|offline|connection refused|econnrefused/.test(normalized)) {
    return { kind: 'offline', title: 'Local runtime is unavailable', detail: 'No changes were made. Check the API process and connection, then retry.', retryable: true };
  }
  if (/timed?\s*out|timeout|deadline exceeded/.test(normalized)) {
    return { kind: 'timeout', title: 'The provider did not respond in time', detail: 'The run remains unchanged. Retry once the provider is responsive.', retryable: true };
  }
  if (/429|rate.?limit|too many requests|quota/.test(normalized)) {
    return { kind: 'rate_limit', title: 'Provider rate limit reached', detail: 'The request was not applied. Wait briefly before retrying.', retryable: true };
  }
  if (/401|unauthori[sz]ed|session expired|access token/.test(normalized)) {
    return { kind: 'session', title: 'Session needs attention', detail: 'Reconnect the authenticated API session before continuing.', retryable: false };
  }
  if (/409|conflict|row.?version|version mismatch|stale/.test(normalized)) {
    return { kind: 'conflict', title: 'The run changed on the server', detail: 'Refresh the authoritative snapshot before trying this action again.', retryable: true };
  }
  if (/400|422|validation|invalid|required|must |cannot |blocked/.test(normalized)) {
    return { kind: 'validation', title: `${operation} was not accepted`, detail, retryable: false };
  }
  return { kind: 'unknown', title: `${operation} could not be completed`, detail, retryable: true };
}

export function QuantInlineProblem({ problem, action }: { problem: QuantProblem; action?: ReactNode }) {
  return <div className={`quant-problem is-${problem.kind}`} role="alert">
    <div><strong>{problem.title}</strong><span>{problem.detail}</span></div>
    {action}
  </div>;
}
