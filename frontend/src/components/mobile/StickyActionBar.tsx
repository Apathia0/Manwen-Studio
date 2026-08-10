import type { ReactNode } from 'react';

type StickyActionBarProps = {
  children: ReactNode;
  className?: string;
};

/**
 * 粘性操作栏：固定在视口底部（safe-area 自动处理）。
 * 用于移动端保存/提交按钮在软键盘弹出时保持可见。
 */
export function StickyActionBar({ children, className = '' }: StickyActionBarProps) {
  return (
    <div
      className={`sticky bottom-0 z-20 shrink-0 border-t border-[#d7e3f4] bg-white/90 px-4 py-3 backdrop-blur-xl ${className}`}
      style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 12px)' }}
    >
      {children}
    </div>
  );
}
