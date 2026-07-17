import type { GlintApi } from '../../api';
import { createApiQuantApi } from '../../quant-api';
import { QuantWorkspace } from '../quant/QuantWorkspace';

export function Workbench({ api }: { api: GlintApi }) {
  return <QuantWorkspace api={createApiQuantApi(api)} />;
}
