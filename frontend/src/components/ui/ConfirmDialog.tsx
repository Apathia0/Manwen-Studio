import { useEffect, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle } from 'lucide-react';
import {
  _confirmSubscribe,
  _confirmGetSnapshot,
  _confirmResolve,
  _confirmCancel,
} from '../../lib/confirm';

/** 全局确认对话框，通过 Portal 渲染 */
export function ConfirmDialog() {
  const req = useSyncExternalStore(
    _confirmSubscribe,
    _confirmGetSnapshot,
    _confirmGetSnapshot,
  );

  // ESC 键关闭
  useEffect(() => {
    if (!req) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') _confirmCancel();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [req]);

  if (!req) return null;

  const isDanger = req.danger !== false; // 默认为危险操作（红色确认按钮）

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40"
      onClick={_confirmCancel}
    >
      <div
        className="mx-4 w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className={`shrink-0 rounded-full p-2 ${isDanger ? 'bg-red-100' : 'bg-amber-100'}`}>
            <AlertTriangle size={20} className={isDanger ? 'text-red-600' : 'text-amber-600'} />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-semibold text-slate-900">
              {req.title || '确认操作'}
            </h3>
            <p className="mt-2 text-sm text-slate-600 leading-relaxed">
              {req.message}
            </p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={_confirmCancel}
            className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-[#eff6ff]"
          >
            {req.cancelText || '取消'}
          </button>
          <button
            onClick={_confirmResolve}
            className={`rounded-2xl px-4 py-2 text-sm font-medium text-white transition ${
              isDanger
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-[#1d4ed8] hover:bg-[#1e40af]'
            }`}
          >
            {req.confirmText || '确认'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
