import { Folder, FolderOpen, ChevronDown, ChevronRight, UserRound, MapPin, Box } from 'lucide-react';
import { useState, type ReactNode } from 'react';

export interface ContainerNodeConfig {
  node_role?: string;
  node_label: string;
  tabs: Array<{ title: string; color: string; nodes: string[] }>;
  matrix_layout?: boolean;
}

interface Props {
  config: ContainerNodeConfig;
  onToggleCollapsed?: () => void;
  collapsed?: boolean;
}

export default function ContainerNodeView({ config, onToggleCollapsed, collapsed = false }: Props): ReactNode {
  if (!config.tabs || config.tabs.length === 0) {
    return <div className="flex h-full w-full items-center justify-center text-xs text-[#78818f]">暂无资产</div>;
  }

  const tabs = config.tabs;
  const [activeTab, setActiveTab] = useState<string>(tabs[0].title);

  // Tab bar
  const tabBar = (
    <div className="flex shrink-0 items-center gap-1 border-b border-[#35393f] bg-[#1a1c20] px-2.5 py-1.5">
      {tabs.map((tab, idx) => (
        <button
          key={idx}
          type="button"
          onClick={() => setActiveTab(tab.title)}
          className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] transition-colors ${
            activeTab === tab.title ? 'bg-white/10 text-white' : 'text-[#78818f] hover:text-white/80'
          }`}
          style={{
            borderTop: `2px solid ${tab.color}`,
          }}
        >
          {tab.color === '#73a7ff' && <UserRound size={10} />}
          {tab.color === '#34d399' && <MapPin size={10} />}
          {tab.color === '#f59e0b' && <Box size={10} />}
          <span>{tab.title}</span>
          <span className="rounded-full bg-[#25282e] px-1.5 py-0.5 text-[9px]">{tab.nodes.length}</span>
        </button>
      ))}
    </div>
  );

  // Matrix grid
  const matrixGrid = (
    <div className="overflow-y-auto p-2">
      <div className="grid grid-cols-3 gap-[18px]" style={{ width: 'max-content' }}>
        {(() => {
          const activeNodes = tabs.find(t => t.title === activeTab)?.nodes || [];
          const roleLabels: Record<string, string> = { character: '角色', scene: '场景', prop: '道具', other: '其他' };
          const nodeRows = [];
          for (let i = 0; i < activeNodes.length; i++) {
            const rowIdx = Math.floor(i / 3);
            const colIdx = i % 3;
            nodeRows.push(
              <div
                key={activeNodes[i]}
                className="relative h-16 min-w-[150px] rounded-md border border-[#2d3138] bg-[#202226] px-2 py-1.5 text-left text-[10px] text-[#aeb3be]"
                style={{ gridColumnStart: colIdx + 1, gridRowStart: rowIdx + 1 }}
              >
                <div className="truncate flex items-center gap-1">
                  <Folder size={10} className="shrink-0 text-[#6b7280]" />
                  <span className="truncate">{activeNodes[i]}</span>
                </div>
              </div>
            );
          }
          return nodeRows;
        })()}
      </div>
    </div>
  );

  return (
    <div className="flex h-full w-full flex-col overflow-hidden rounded-xl border border-[#35393f] bg-[#1e2025] shadow-[0_8px_24px_rgba(0,0,0,.15)]">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#35393f] bg-[#1a1c20] px-3 py-2">
        <div className="flex items-center gap-2">
          {collapsed ? <FolderOpen size={14} className="text-[#78818f]" /> : <Folder size={14} className="text-[#78818f]" />}
          <span className="truncate text-xs font-medium text-[#e8ebf0]">{config.node_label || '资产容器'}</span>
          <span className="rounded-full bg-[#2a2e33] px-2 py-0.5 text-[10px] text-[#8b93a1]">
            {tabs.reduce((sum, t) => sum + t.nodes.length, 0)} 个资产
          </span>
        </div>
        {onToggleCollapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="rounded-lg p-1.5 text-[#78818f] hover:bg-white/5 hover:text-white"
            title={collapsed ? "展开容器" : "收起容器"}
          >
            {collapsed ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        )}
      </div>

      {!collapsed && (
        <>
          {tabBar}
          {matrixGrid}
        </>
      )}
    </div>
  );
}
