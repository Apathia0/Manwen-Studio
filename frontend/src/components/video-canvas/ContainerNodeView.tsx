import { Group as GroupIcon, Ungroup } from 'lucide-react';
import { useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';

export interface ContainerNodeConfig {
  node_role?: string;
  node_label: string;
  member_ids?: string[];
  /** 旧文件夹式容器的分组数据，仅用于兼容读取成员数 */
  tabs?: Array<{ title: string; color: string; nodes: string[] }>;
  matrix_layout?: boolean;
}

interface Props {
  config: ContainerNodeConfig;
  /** 实际成员数（由画布解析传入；缺省时回退 config 统计） */
  memberCount?: number;
  onRename?: (name: string) => void;
  onUngroup?: () => void;
}

/**
 * 节点组标题栏。组框外观（边框/底色/层级）由 CanvasNodeView 绘制，
 * 本组件只渲染顶部标题条：
 * - 拖动标题条 = 拖动整个组（pointerdown 冒泡到节点根）；
 * - 双击名称内联改名；
 * - 右侧「解散」按钮移除组框（子节点保留）。
 * 根元素 pointer-events-auto：在 pointer-events-none 的组框根内重新可交互。
 */
export default function ContainerNodeView({ config, memberCount, onRename, onUngroup }: Props): ReactNode {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const fallbackCount = (config.member_ids?.length ?? 0) || (config.tabs?.reduce((sum, tab) => sum + tab.nodes.length, 0) ?? 0);
  const count = memberCount ?? fallbackCount;
  const label = config.node_label || '节点组';

  const startEdit = (event: { stopPropagation(): void }) => {
    if (!onRename) return;
    event.stopPropagation();
    setDraft(label);
    setEditing(true);
  };  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== label) onRename?.(next);
  };

  const cancel = () => setEditing(false);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    event.stopPropagation();
    if (event.key === 'Enter') commit();
    if (event.key === 'Escape') cancel();
  };

  return (
    <div
      className="pointer-events-auto flex h-9 w-full cursor-move items-center gap-2 rounded-t-2xl border-b border-[#2f80ff]/25 bg-[#1a2233]/90 px-3 backdrop-blur"
    >
      <GroupIcon className="h-3.5 w-3.5 shrink-0 text-[#73a7ff]" />
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={handleKeyDown}
          onPointerDown={(event) => event.stopPropagation()}
          maxLength={64}
          aria-label="节点组名称"
          className="min-w-0 flex-1 rounded border border-[#2f80ff]/50 bg-[#10141c] px-1.5 py-0.5 text-xs text-white outline-none"
        />
      ) : (
        <span
          className="min-w-0 flex-1 truncate text-xs font-semibold text-[#dbe7ff]"
          onDoubleClick={(event) => { event.stopPropagation(); startEdit(event); }}
        >
          {label}
        </span>
      )}
      <span className="shrink-0 rounded-full bg-[#2f80ff]/20 px-2 py-0.5 text-[10px] text-[#9ec5ff]">
        {count} 个成员
      </span>
      {onUngroup && (
        <button
          type="button"
          title="解散节点组（保留子节点）"
          aria-label="解散节点组"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); onUngroup(); }}
          className="grid size-6 shrink-0 place-items-center rounded text-[#8aa7d6] transition hover:bg-white/10 hover:text-white"
        >
          <Ungroup className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
