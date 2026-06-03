import { Loader2 } from 'lucide-react';

interface LoadingOverlayProps {
  visible: boolean;
  message?: string;
}

/** 全屏 Loading 遮罩，用于应用初始化等场景 */
export function LoadingOverlay({ visible, message = '加载中...' }: LoadingOverlayProps) {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[150] flex flex-col items-center justify-center bg-white/80 backdrop-blur-sm">
      <Loader2 size={32} className="animate-spin text-[#1d4ed8]" />
      <p className="mt-3 text-sm text-slate-600">{message}</p>
    </div>
  );
}
