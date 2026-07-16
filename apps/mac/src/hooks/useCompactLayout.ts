import { useEffect, useState } from 'react';
import { isCompactWorkbenchWidth } from '../lib/layout-state';

export function useCompactLayout(): boolean {
  const [compact, setCompact] = useState(() => isCompactWorkbenchWidth(window.innerWidth));

  useEffect(() => {
    const update = () => setCompact(isCompactWorkbenchWidth(window.innerWidth));
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  return compact;
}
