import { useEffect, useState } from 'react';
import { Download, Wifi, WifiOff } from 'lucide-react';
import { onInstallableChange, promptInstall, subscribeOnline } from '../pwa';

/**
 * PWA 安装提示 + 离线状态条
 * - 可安装时：显示"安装到设备"按钮（调用 beforeinstallprompt）
 * - iOS Safari 无提示事件：显示"添加到主屏幕"引导文字
 * - 网络离线/恢复时：在页面顶部显示轻量状态条
 */
export default function PwaInstallPrompt() {
  const [installable, setInstallable] = useState(false);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const offInstall = onInstallableChange(setInstallable);
    const offOnline = subscribeOnline(setOnline);
    // iOS 无法捕获 to install 事件，通过 UA 检测兜底显示引导
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent) && !(window as unknown as { MSStream?: unknown }).MSStream;
    if (isIos) setInstallable(true);
    return () => {
      offInstall();
      offOnline();
    };
  }, []);

  // 离线横幅或安装按钮仅在「离线」或「可安装」条件下渲染
  if (!installable && online) return null;

  return (
    <div className="fixed bottom-20 left-0 right-0 z-[90] mx-auto flex max-w-md flex-col gap-2 px-4 md:bottom-6">
      {!online && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-300/40 bg-amber-50 px-3 py-2 text-xs text-amber-800 shadow-lg">
          <WifiOff className="h-4 w-4 shrink-0" />
          当前离线，草稿已保存在本地，联网后自动同步。
        </div>
      )}
      {online && installable && (
        <button
          type="button"
          onClick={() => void promptInstall()}
          className="flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-lg active:scale-[0.98]"
        >
          <Download className="h-4 w-4" />
          安装 StoryCanvas 到设备
        </button>
      )}
      {online && installable && /iphone|ipad|ipod/i.test(navigator.userAgent) && (
        <div className="flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 shadow-lg">
          <Wifi className="h-4 w-4 shrink-0" />
          Safari 浏览器：点分享按钮 → 添加到主屏幕。
        </div>
      )}
    </div>
  );
}