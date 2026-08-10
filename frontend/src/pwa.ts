/**
 * Service Worker 注册与 PWA 安装能力
 * - 生产环境注册 /sw.js（本地开发不注册，避免缓存干扰 HMR）
 * - 捕获 `beforeinstallprompt`，暴露可手动触发的安装入口（Android Chrome / Edge）
 * - 监听网络在线状态变化，返回给 React 层使用
 */

/** 模块级变量：保存浏览器原生安装弹窗句柄（仅桌面端可拦截） */
let deferredPrompt: { prompt: () => Promise<void>; userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }> } | null = null;

/** 供 UI 层订阅的「可安装」状态变化回调 */
export type OnInstallableChange = (installable: boolean) => void;
const installableListeners = new Set<OnInstallableChange>();

function emitInstallable(installable: boolean) {
  installableListeners.forEach((fn) => fn(installable));
}

/** 订阅 PWA 可安装状态变化，返回退订函数 */
export function onInstallableChange(fn: OnInstallableChange): () => void {
  installableListeners.add(fn);
  return () => {
    installableListeners.delete(fn);
  };
}

/** 注册 Service Worker（幂等） */
export function registerServiceWorker() {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.warn('[PWA] Service Worker 注册失败（不影响正常使用）:', err);
    });
  });
}

/** 捕获浏览器安装事件（仅支持 beforeinstallprompt 的浏览器生效，iOS Safari 走系统提示） */
export function setupInstallPromptCapture() {
  if (typeof window === 'undefined') return;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e as unknown as typeof deferredPrompt;
    emitInstallable(true);
  });
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    emitInstallable(false);
  });
}

/** 主动触发安装弹窗（必须在用户手势中调用）。返回是否成功弹出 */
export async function promptInstall(): Promise<boolean> {
  if (!deferredPrompt) return false;
  const p = deferredPrompt;
  deferredPrompt = null;
  emitInstallable(false);
  await p.prompt();
  await p.userChoice;
  return true;
}

/** 订阅在线/离线状态（SSR 安全） */
export function subscribeOnline(fn: (online: boolean) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const update = () => fn(navigator.onLine);
  window.addEventListener('online', update);
  window.addEventListener('offline', update);
  update();
  return () => {
    window.removeEventListener('online', update);
    window.removeEventListener('offline', update);
  };
}