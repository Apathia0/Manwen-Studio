import { useCallback, useEffect, type ReactNode } from 'react';
import { X, ChevronLeft } from 'lucide-react';

type ResponsiveDrawerProps = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  /** 移动端是否显示返回箭头（默认显示） */
  showBack?: boolean;
  /** 移动端宽度比例（默认 85%） */
  widthClass?: string;
  children: ReactNode;
};

/**
 * 响应式抽屉：移动端为从右侧滑出的覆盖式抽屉（可全宽），
 * 桌面端为普通内嵌面板（不遮罩）。
 * 用于章节列表、AI 助手等侧栏在移动端的呈现。
 */
export function ResponsiveDrawer({ open, onClose, title, showBack = true, widthClass = 'w-[85vw] max-w-md', children }: ResponsiveDrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  const stopPropagation = useCallback((event: React.MouseEvent) => event.stopPropagation(), []);

  return (
    <div
      className={`fixed inset-0 z-[130] transition-opacity duration-200 md:hidden ${open ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'}`}
      aria-hidden={!open}
    >
      <div className={`absolute inset-0 bg-black/40 transition-opacity duration-200 ${open ? 'opacity-100' : 'opacity-0'}`} onClick={onClose} />
      <div
        className={`absolute right-0 top-0 flex h-full flex-col bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_46%,_#f8fbff_100%)] shadow-2xl transition-transform duration-200 ${widthClass} ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
        style={{ paddingTop: 'env(safe-area-inset-top, 0px)', paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
        onClick={stopPropagation}
      >
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-[#d7e3f4] bg-white/90 px-4 backdrop-blur-xl">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {showBack && (
              <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-600 transition hover:bg-slate-100" aria-label="关闭">
                <ChevronLeft size={22} />
              </button>
            )}
            <div className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">{title}</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100" aria-label="关闭">
            <X size={20} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
