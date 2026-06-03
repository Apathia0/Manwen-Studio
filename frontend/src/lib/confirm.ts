type ConfirmOptions = {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
};

type ConfirmRequest = ConfirmOptions & {
  resolve: (value: boolean) => void;
};

let currentRequest: ConfirmRequest | null = null;
const listeners = new Set<(req: ConfirmRequest | null) => void>();

function notify() {
  listeners.forEach((fn) => fn(currentRequest));
}

/** 显示确认对话框，返回 Promise<boolean> */
export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    currentRequest = { ...options, resolve };
    notify();
  });
}

/** 内部：确认操作 */
export function _confirmResolve() {
  currentRequest?.resolve(true);
  currentRequest = null;
  notify();
}

/** 内部：取消操作 */
export function _confirmCancel() {
  currentRequest?.resolve(false);
  currentRequest = null;
  notify();
}

/** 内部：订阅确认请求变化 */
export function _confirmSubscribe(fn: (req: ConfirmRequest | null) => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** 内部：获取当前请求快照 */
export function _confirmGetSnapshot(): ConfirmRequest | null {
  return currentRequest;
}
