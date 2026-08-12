import { useEffect } from 'react';
import { Plus, Trash2 } from 'lucide-react';

/**
 * 画布右键菜单状态（节点菜单 / 连线菜单）。
 * 由 useCanvasInteractions 或集成方持有，本组件只负责渲染与回调。
 */
export type ContextMenuState =
  | { type: 'node'; x: number; y: number; nodeId: string }
  | { type: 'connection'; x: number; y: number; connectionId: string }
  | null;

export interface CanvasContextMenuProps {
  /** 当前菜单状态；null 时不渲染 */
  menu: ContextMenuState;
  /** 关闭菜单回调（点击外部 / 执行操作后调用） */
  onClose: () => void;
  /** 复制节点回调（仅节点菜单） */
  onDuplicateNode: (nodeId: string) => void;
  /** 删除节点回调（仅节点菜单） */
  onDeleteNode: (nodeId: string) => void;
  /** 删除连线回调（仅连线菜单） */
  onDeleteConnection: (connectionId: string) => void;
}

/** 菜单项按钮：普通色 / 危险色，hover 提亮 */
function MenuButton({
  icon,
  label,
  danger = false,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-white/10 ${
        danger ? 'text-[#f87171]' : 'text-[#ded7d0]'
      }`}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export default function CanvasContextMenu({ menu, onClose, onDuplicateNode, onDeleteNode, onDeleteConnection }: CanvasContextMenuProps) {
  // 点击菜单外部任意位置时关闭菜单
  useEffect(() => {
    if (!menu) return;
    const close = () => onClose();
    window.addEventListener('pointerdown', close);
    return () => window.removeEventListener('pointerdown', close);
  }, [menu, onClose]);

  if (!menu) return null;

  const isNode = menu.type === 'node';

  return (
    <div
      className="fixed z-[80] min-w-44 overflow-hidden rounded-xl border border-[#393633] bg-[#211f1d] py-1 shadow-2xl"
      style={{ left: menu.x, top: menu.y }}
      // 阻止事件冒泡到画布，避免触发画布框选 / 平移
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {isNode ? (
        <MenuButton icon={<Plus className="h-4 w-4" />} label="复制" onClick={() => onDuplicateNode(menu.nodeId)} />
      ) : null}
      {isNode ? (
        <MenuButton icon={<Trash2 className="h-4 w-4" />} label="删除" danger onClick={() => onDeleteNode(menu.nodeId)} />
      ) : (
        <MenuButton icon={<Trash2 className="h-4 w-4" />} label="删除连线" danger onClick={() => onDeleteConnection(menu.connectionId)} />
      )}
    </div>
  );
}