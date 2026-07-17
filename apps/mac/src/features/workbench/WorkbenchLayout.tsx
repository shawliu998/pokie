import { useState, type ReactNode, type RefObject } from 'react';
import { Group, Panel, Separator, type PanelImperativeHandle } from 'react-resizable-panels';
import type { CompactPane } from '../../lib/workbench-state';
import { loadWorkbenchLayout, saveWorkbenchLayout } from '../../lib/layout-state';

interface WorkbenchLayoutProps {
  compact: boolean;
  compactPane: CompactPane;
  sidebar: ReactNode;
  list: ReactNode;
  detail: ReactNode;
  sidebarPanelRef: RefObject<PanelImperativeHandle | null>;
  onSidebarCollapsedChange: (collapsed: boolean) => void;
  onBack: () => void;
}

export function WorkbenchLayout({ compact, compactPane, sidebar, list, detail, sidebarPanelRef, onSidebarCollapsedChange, onBack }: WorkbenchLayoutProps) {
  const [latestLayout, setLatestLayout] = useState(() => loadWorkbenchLayout());

  if (compact) return <div className="compact-workbench" data-layout="compact">
    <div className="compact-sidebar">{sidebar}</div>
    <div className="compact-main">
      {compactPane === 'list' ? list : <><div className="compact-pane-toolbar"><button className="text-button" onClick={onBack} aria-label="Back to list">← Back</button></div>{detail}</>}
    </div>
  </div>;

  return <Group
    id="glint-workbench"
    className="three-column"
    orientation="horizontal"
    defaultLayout={latestLayout}
    onLayoutChanged={(layout) => {
      setLatestLayout(layout);
      saveWorkbenchLayout(layout);
    }}
    resizeTargetMinimumSize={{ coarse: 24, fine: 10 }}
  >
    <Panel id="sidebar" panelRef={sidebarPanelRef} defaultSize={200} minSize={160} maxSize={300} collapsible collapsedSize={0} groupResizeBehavior="preserve-pixel-size" onResize={(size) => onSidebarCollapsedChange(size.inPixels < 1)}>{sidebar}</Panel>
    <Separator id="sidebar-list-separator" className="resize-separator" aria-label="Resize sidebar and list" />
    <Panel id="list" defaultSize={310} minSize={260} maxSize={500} groupResizeBehavior="preserve-pixel-size">{list}</Panel>
    <Separator id="list-detail-separator" className="resize-separator" aria-label="Resize list and detail" />
    <Panel id="detail" minSize={520}>{detail}</Panel>
  </Group>;
}
