import { useState } from 'react';
import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import type { LucideIcon } from 'lucide-react';

export type ActionSheetAction = {
  key: string;
  label: string;
  icon?: LucideIcon;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
};

export type ActionSheetOptions = {
  title?: string;
  actions: ActionSheetAction[];
  cancelText?: string;
};

type SheetState = ActionSheetOptions | null;

let current: SheetState = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function getSnapshot(): SheetState {
  return current;
}

/** 打开底部操作面板（全局单例，用法与 confirm() 一致） */
export function showActionSheet(options: ActionSheetOptions): void {
  current = options;
  emit();
}

/** 关闭底部操作面板 */
export function dismissActionSheet(): void {
  current = null;
  emit();
}

/**
 * 移动端底部操作面板（Action Sheet）。
 * 全局单例，通过 showActionSheet() 命令式打开；
 * 桌面端自动居中显示为 Dialog，移动端贴底滑出。
 */
export function MobileActionSheet() {
  const state = useSyncExternalStore(subscribe, getSnapshot);
  const [closing, setClosing] = useState(false);

  const close = () => {
    if (closing) return;
    setClosing(true);
    setTimeout(() => {
      dismissActionSheet();
      setClosing(false);
    }, 180);
  };

  const open = Boolean(state);

  return (
    <>
      {open &&
        createPortal(
          <div className={`fixed inset-0 z-[140] flex items-end justify-center md:items-center md:p-6 ${closing ? '' : ''}`}>
            <div
              className={`absolute inset-0 bg-black/45 transition-opacity duration-200 ${closing ? 'opacity-0' : 'opacity-100'}`}
              onClick={close}
            />
            <div
              role="dialog"
              aria-modal="true"
              className={`relative w-full overflow-hidden rounded-t-3xl bg-white shadow-2xl transition-transform duration-200 md:max-w-md md:rounded-3xl ${
                closing ? 'translate-y-6 md:scale-95' : 'translate-y-0 md:scale-100'
              }`}
              style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
            >
              {state?.title && (
                <div className="border-b border-[#eef2f7] px-5 py-4 text-center">
                  <div className="text-sm font-semibold text-slate-800">{state.title}</div>
                </div>
              )}
              <div className="max-h-[60vh] overflow-y-auto p-2">
                {state?.actions.map((action) => {
                  const Icon = action.icon;
                  return (
                    <button
                      key={action.key}
                      type="button"
                      disabled={action.disabled}
                      onClick={() => {
                        close();
                        setTimeout(action.onClick, 200);
                      }}
                      className={`flex w-full items-center gap-3 rounded-2xl px-4 py-3.5 text-left text-sm transition active:bg-slate-50 ${
                        action.disabled
                          ? 'cursor-not-allowed text-slate-300'
                          : action.danger
                            ? 'text-red-600 hover:bg-red-50'
                            : 'text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      {Icon && <Icon size={18} className={action.danger ? 'text-red-500' : 'text-slate-400'} />}
                      {action.label}
                    </button>
                  );
                })}
              </div>
              <div className="p-2">
                <button
                  type="button"
                  onClick={close}
                  className="w-full rounded-2xl bg-slate-100 py-3 text-sm font-medium text-slate-600 transition active:bg-slate-200"
                >
                  {state?.cancelText || '取消'}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
