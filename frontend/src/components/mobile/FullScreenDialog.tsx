import type { ReactNode } from 'react';
import { X, ChevronLeft } from 'lucide-react';

type FullScreenDialogProps = {
  open: boolean;
  title?: ReactNode;
  /** 左侧返回按钮回调；不传则不显示返回按钮 */
  onBack?: () => void;
  /** 右侧关闭按钮回调；不传则隐藏关闭按钮 */
  onClose?: () => void;
  /** 顶部右侧自定义操作 */
  headerRight?: ReactNode;
  children: ReactNode;
  /** 底部固定操作区（safe-area 自动处理） */
  footer?: ReactNode;
};

/**
 * 全屏对话框：移动端渲染为全屏页面（含安全区），桌面端渲染为居中模态框。
 * 用于移动端把 Dialog / 编辑器切换为全屏页。
 */
export function FullScreenDialog({ open, title, onBack, onClose, headerRight, children, footer }: FullScreenDialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[120] flex flex-col bg-white md:items-center md:justify-center md:bg-black/45 md:p-6">
      <div className="flex h-full w-full flex-col bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_46%,_#f8fbff_100%)] md:max-h-[90vh] md:rounded-3xl md:shadow-2xl">
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center justify-between border-b border-[#d7e3f4] bg-white/90 px-4 backdrop-blur-xl" style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {onBack && (
              <button type="button" onClick={onBack} className="rounded-lg p-1.5 text-slate-600 transition hover:bg-slate-100" aria-label="返回">
                <ChevronLeft size={22} />
              </button>
            )}
            <div className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">{title}</div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {headerRight}
            {onClose && (
              <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100" aria-label="关闭">
                <X size={20} />
              </button>
            )}
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {footer && (
          <div
            className="shrink-0 border-t border-[#d7e3f4] bg-white/90 px-4 py-3 backdrop-blur-xl"
            style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 12px)' }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
