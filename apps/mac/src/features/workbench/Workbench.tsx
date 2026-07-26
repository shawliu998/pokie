import type { GlintApi } from '../../api';
import { createApiQuantApi } from '../../quant-api';
import { QuantWorkspace } from '../quant/QuantWorkspace';

export function Workbench({ api }: { api: GlintApi }) {
  const guidedDemoRunId = (import.meta.env.VITE_QURIO_GUIDED_DEMO_RUN_ID as string | undefined)?.trim();
  const guidedDemoLabel = (import.meta.env.VITE_QURIO_GUIDED_DEMO_LABEL as string | undefined)?.trim();
  return <QuantWorkspace
    api={createApiQuantApi(api)}
    guidedDemo={guidedDemoRunId
      ? {
          runId: guidedDemoRunId,
          label: guidedDemoLabel || 'Retained real-provider research',
        }
      : undefined}
  />;
}
