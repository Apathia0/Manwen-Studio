import { normalizeErrorMessage } from './errors';

type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration: number;
}

type Listener = (toasts: Toast[]) => void;

let toasts: Toast[] = [];
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((fn) => fn([...toasts]));
}

function add(type: ToastType, message: string, duration: number) {
  const id = crypto.randomUUID();
  // 最多保留 5 条，超出则移除最早的
  toasts = [...toasts.slice(-4), { id, type, message, duration }];
  notify();
  if (duration > 0) {
    setTimeout(() => toast.dismiss(id), duration);
  }
}

export const toast = {
  /** 成功提示（绿色，4 秒自动消失） */
  success: (message: string, duration = 4000) => add('success', message, duration),
  /** 错误提示（红色，6 秒自动消失） */
  error: (message: string, duration = 6000) => add('error', normalizeErrorMessage(message), duration),
  /** 警告提示（琥珀色，4 秒自动消失） */
  warning: (message: string, duration = 4000) => add('warning', message, duration),
  /** 信息提示（蓝色，4 秒自动消失） */
  info: (message: string, duration = 4000) => add('info', message, duration),
  /** 手动关闭指定 toast */
  dismiss: (id: string) => {
    toasts = toasts.filter((t) => t.id !== id);
    notify();
  },
  /** 订阅 toast 变化，返回取消订阅函数 */
  subscribe: (fn: Listener) => {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  /** 获取当前所有 toast（快照） */
  getSnapshot: () => toasts,
};
