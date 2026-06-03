import { Loader2 } from 'lucide-react';

/** 路由切换时的加载占位组件 */
export function RouteLoadingFallback() {
  return (
    <div className="flex h-[60vh] items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <Loader2 size={28} className="animate-spin text-[#1d4ed8]" />
        <p className="text-sm text-slate-500">加载中...</p>
      </div>
    </div>
  );
}
