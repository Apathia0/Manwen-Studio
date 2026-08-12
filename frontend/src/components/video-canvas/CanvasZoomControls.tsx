import { useState } from 'react';
import { Compass, Focus, HelpCircle, X } from 'lucide-react';

/**
 * 画布缩放控制 dock（底部左侧）。
 * 纯展示组件：小地图开关 + 重置视图 + 缩放滑杆 + 百分比 + 快捷键帮助弹窗。
 * 所有交互通过回调上抛，不持有任何全局 store。
 */
export interface CanvasZoomControlsProps {
  /** 当前缩放比例（1 = 100%） */
  scale: number;
  /** 缩放变化回调（传入新的比例，如 0.5 / 1.5） */
  onScaleChange: (scale: number) => void;
  /** 重置视图回调 */
  onReset: () => void;
  /** 小地图是否打开 */
  isMiniMapOpen: boolean;
  /** 切换小地图开关回调 */
  onToggleMiniMap: () => void;
}

/** 快捷键帮助弹窗中的一行：左侧快捷键，右侧功能说明 */
function ShortcutRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm font-medium text-[#ded7d0]">{label}</span>
      <span className="text-xs text-[#938b84]">{value}</span>
    </div>
  );
}

/** dock 内的图标按钮：默认灰、hover 提亮、激活态高亮 */
function DockIconButton({
  title,
  active = false,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded transition-colors ${
        active ? 'bg-white/10 text-white' : 'text-[#a49b94] hover:bg-white/10 hover:text-white'
      }`}
    >
      {children}
    </button>
  );
}

export default function CanvasZoomControls({
  scale,
  onScaleChange,
  onReset,
  isMiniMapOpen,
  onToggleMiniMap,
}: CanvasZoomControlsProps) {
  // 快捷键帮助弹窗开关
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  return (
    <div
      className="absolute bottom-5 right-5 z-50"
      // 阻止事件冒泡到画布，避免触发画布框选 / 平移
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="flex h-14 items-center gap-1 rounded-xl border border-[#393633] bg-[#211f1d]/95 px-2 shadow-xl backdrop-blur">
        <DockIconButton title={isMiniMapOpen ? '关闭小地图' : '打开小地图'} active={isMiniMapOpen} onClick={onToggleMiniMap}>
          <Compass className="h-4 w-4" />
        </DockIconButton>
        <DockIconButton title="重置视图" onClick={onReset}>
          <Focus className="h-4 w-4" />
        </DockIconButton>
        <input
          type="range"
          min="5"
          max="500"
          step="1"
          value={Math.round(scale * 100)}
          aria-label="缩放"
          className="w-24 accent-[#60a5fa]"
          onChange={(event) => onScaleChange(Number(event.target.value) / 100)}
        />
        <span className="w-10 text-right text-xs tabular-nums text-[#938b84]">{Math.round(scale * 100)}%</span>
        <DockIconButton title="快捷键" active={shortcutsOpen} onClick={() => setShortcutsOpen(true)}>
          <HelpCircle className="h-4 w-4" />
        </DockIconButton>
      </div>

      {/* 快捷键帮助弹窗（自绘 Modal 风格） */}
      {shortcutsOpen ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50"
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => setShortcutsOpen(false)}
        >
          <div
            className="w-[420px] max-w-[calc(100vw-32px)] rounded-2xl border border-[#393633] bg-[#211f1d] p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <span className="text-base font-semibold text-[#ded7d0]">快捷键</span>
              <button
                type="button"
                aria-label="关闭"
                onClick={() => setShortcutsOpen(false)}
                className="grid h-7 w-7 place-items-center rounded-lg text-[#938b84] transition hover:bg-white/10 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 border-t border-[#393633] pt-4">
              <ShortcutRow label="Ctrl / Space + 拖拽" value="切换工具" />
              <ShortcutRow label="滚轮" value="缩放" />
              <ShortcutRow label="拖拽" value="框选" />
              <ShortcutRow label="Shift / Cmd + 点击" value="追加选择" />
              <ShortcutRow label="Ctrl / Cmd + C / V" value="复制粘贴" />
              <ShortcutRow label="Delete / Backspace" value="删除" />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}