import type { ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';

type MobileTopBarProps = {
  title?: ReactNode;
  subtitle?: ReactNode;
  onBack?: () => void;
  right?: ReactNode;
  /** 左侧自定义操作（优先于 onBack） */
  left?: ReactNode;
};

/**
 * 移动端顶部栏：返回按钮 + 标题 + 右侧操作，含 safe-area 顶部内边距。
 * 桌面端自动隐藏（md:hidden）。
 */
export function MobileTopBar({ title, subtitle, onBack, right, left }: MobileTopBarProps) {
  return (
    <header
      className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-[#d7e3f4] bg-[rgba(248,251,255,0.9)] px-4 backdrop-blur-xl md:hidden"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {left ? (
          <div className="flex shrink-0 items-center">{left}</div>
        ) : onBack ? (
          <button type="button" onClick={onBack} className="-ml-1 shrink-0 rounded-lg p-1.5 text-slate-600 transition hover:bg-slate-100" aria-label="返回">
            <ChevronLeft size={22} />
          </button>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-slate-800">{title}</div>
          {subtitle && <div className="truncate text-[11px] text-slate-500">{subtitle}</div>}
        </div>
      </div>
      {right && <div className="ml-2 flex shrink-0 items-center gap-2">{right}</div>}
    </header>
  );
}
