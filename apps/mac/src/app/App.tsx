import { SessionBoundary } from '../features/session/SessionBoundary';
import { Workbench } from '../features/workbench/Workbench';

export function App() {
  return <SessionBoundary>{(api) => <Workbench api={api} />}</SessionBoundary>;
}
