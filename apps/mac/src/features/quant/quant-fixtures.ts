import fixture from './quant-fixture.generated.json';
import type { QuantWorkspaceSnapshot } from '../../quant-domain';
import { parseQuantWorkspaceSnapshot } from '../../quant-workspace-parser';

// Generated from the same server-owned projection used by browser E2E. Keeping
// one completed snapshot here provides an offline adapter without a second,
// hand-maintained set of bars, metrics, verdicts, or report copy.
const parsedFixture = parseQuantWorkspaceSnapshot(fixture).snapshot;
if (!parsedFixture) throw new Error('The bundled Quant fixture is incompatible with the workspace parser.');
export const quantFixtureSnapshot: QuantWorkspaceSnapshot = parsedFixture;
