import fixture from './quant-fixture.generated.json';
import type { QuantWorkspaceSnapshot } from '../../quant-domain';

// Generated from the same server-owned projection used by browser E2E. Keeping
// one completed snapshot here provides an offline adapter without a second,
// hand-maintained set of bars, metrics, verdicts, or report copy.
export const quantFixtureSnapshot = fixture as unknown as QuantWorkspaceSnapshot;
