import { useEffect, useRef } from 'react';
import { FileText, Film, Image, X } from 'lucide-react';

/**
 * 画布创建节点菜单。
 * 在双击空白处或连线松手空白处弹出，列出 text / image / video 三种节点供选择。
 * 纯展示组件，选择结果通过 onSelect 回调上抛。
 */
export interface CanvasCreateMenuProps {
  /** 菜单位置（相对画布容器的坐标） */
  position: { x: number; y: number };
  /** 选择节点类型回调（传入 'text' / 'image' / 'video'） */
  onSelect: (type: string) => void;
  /** 关闭菜单回调 */
  onClose: () => void;
}

/** 可创建的节点类型定义：图标 + 标题 + 描述 */
const NODE_OPTIONS: { type: string; icon: React.ReactNode; title: string; description?: string }[] = [
  { type: 'text', icon: <FileText className="h-5 w-5" />, title: '文本节点', description: '文本内容描述' },
  { type: 'image', icon: <Image className="h-5 w-5" />, title: '图片节点' },
  { type: 'video', icon: <Film className="h-5 w-5" />, title: '视频节点' },
];

/** 单个节点选项：图标 + 标题 + 描述，hover 提亮 */
function CreateOption({
  icon,
  title,
  description,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="flex h-16 w-full cursor-pointer items-center gap-3 rounded-2xl px-3 text-left transition hover:bg-white/5"
      onClick={onClick}
    >
      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/5 text-[#938b84]">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 text-base font-semibold leading-5 text-[#ded7d0]">{title}</span>
        {description ? (
          <span className="mt-1 block truncate text-sm text-[#938b84]">{description}</span>
        ) : null}
      </span>
    </button>
  );
}

export default function CanvasCreateMenu({ position, onSelect, onClose }: CanvasCreateMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  // 点击菜单外部任意位置时关闭菜单
  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener('pointerdown', handlePointerDown, true);
    return () => document.removeEventListener('pointerdown', handlePointerDown, true);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      className="absolute z-[120] w-[300px] rounded-[18px] border border-[#393633] bg-[#211f1d] p-3 shadow-2xl backdrop-blur"
      data-connection-create-menu
      style={{ left: position.x, top: position.y }}
      // 阻止事件冒泡到画布，避免触发画布框选 / 平移
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-sm font-medium text-[#938b84]">选择节点类型</span>
        <button
          type="button"
          aria-label="关闭"
          className="grid size-7 place-items-center rounded-lg text-[#938b84] opacity-55 transition hover:bg-white/10 hover:opacity-100"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid gap-1">
        {NODE_OPTIONS.map((option) => (
          <CreateOption
            key={option.type}
            icon={option.icon}
            title={option.title}
            description={option.description}
            onClick={() => onSelect(option.type)}
          />
        ))}
      </div>
    </div>
  );
}