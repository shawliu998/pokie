import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { presentQuantProblem, QuantInlineProblem } from './quant-errors';

describe('Quant error presentation', () => {
  it.each([
    ['Failed to fetch', 'offline', 'Local runtime is unavailable', true],
    ['DeepSeek request timed out', 'timeout', 'The provider did not respond in time', true],
    ['429 Too Many Requests', 'rate_limit', 'Provider rate limit reached', true],
    ['401 Unauthorized', 'session', 'Session needs attention', false],
    ['row version conflict', 'conflict', 'The run changed on the server', true],
    ['Validation failed: symbol is required', 'validation', 'CSV import was not accepted', false],
  ] as const)('maps %s to a stable recovery state', (message, kind, title, retryable) => {
    const problem = presentQuantProblem(new Error(message), 'CSV import');
    expect(problem).toMatchObject({ kind, title, retryable });
  });

  it('renders one compact alert without decorative status glyphs', () => {
    const problem = presentQuantProblem(new Error('DeepSeek request timed out'), 'Agent command');
    const markup = renderToStaticMarkup(<QuantInlineProblem problem={problem} action={<button>Retry</button>} />);
    expect(markup).toContain('role="alert"');
    expect(markup).toContain('The provider did not respond in time');
    expect(markup).toContain('Retry');
    expect(markup).not.toContain('<svg');
  });
});
