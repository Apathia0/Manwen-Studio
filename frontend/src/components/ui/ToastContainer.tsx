import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react';
import { toast, type Toast } from '../../lib/toast';

const iconMap = {
  success: <CheckCircle size={16} className="text-emerald-500 shrink-0" />,
  error: <AlertCircle size={16} className="text-red-500 shrink-0" />,
  warning: <AlertTriangle size={16} className="text-amber-500 shrink-0" />,
  info: <Info size={16} className="text-blue-500 shrink-0" />,
};

const borderMap = {
  success: 'border-l-emerald-500',
  error: 'border-l-red-500',
  warning: 'border-l-amber-500',
  info: 'border-l-blue-500',
};

function ToastItem({ t }: { t: Toast }) {
  return (
    <div
      className={`flex items-start gap-2.5 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-lg border-l-4 ${borderMap[t.type]} animate-[slideIn_0.2s_ease-out]`}
      style={{ animation: 'slideIn 0.2s ease-out' }}
    >
      {iconMap[t.type]}
      <span className="flex-1 break-words">{t.message}</span>
      <button
        onClick={() => toast.dismiss(t.id)}
        className="shrink-0 text-slate-400 hover:text-slate-600 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
}

/** 全局 Toast 容器，通过 Portal 渲染在 body 右上角 */
export function ToastContainer() {
  const toasts = useSyncExternalStore(
    toast.subscribe,
    toast.getSnapshot,
    toast.getSnapshot,
  );

  if (toasts.length === 0) return null;

  return createPortal(
    <>
      <style>{`
        @keyframes slideIn {
          from { opacity: 0; transform: translateX(24px); }
          to { opacity: 1; transform: translateX(0); }
        }
      `}</style>
      <div className="fixed top-4 right-4 z-[200] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]">
        {toasts.map((t) => (
          <ToastItem key={t.id} t={t} />
        ))}
      </div>
    </>,
    document.body,
  );
}
