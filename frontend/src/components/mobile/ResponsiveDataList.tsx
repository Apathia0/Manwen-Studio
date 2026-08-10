import type { ReactNode } from 'react';

type ResponsiveDataListProps<T> = {
  /** 数据数组 */
  items: T[];
  /** 唯一 key 提取器 */
  getKey: (item: T) => string | number;
  /** 桌面端渲染（≥768px）：通常为表格行 */
  renderDesktopRow: (item: T) => ReactNode;
  /** 移动端渲染（<768px）：通常为卡片 */
  renderMobileRow: (item: T) => ReactNode;
  /** 桌面端表格头部（≥768px 显示） */
  desktopHeader?: ReactNode;
  /** 空状态 */
  empty?: ReactNode;
  /** 移动端分组标题（可选，渲染在列表顶部） */
  mobileHeader?: ReactNode;
};

/**
 * 响应式数据列表：同一份数据在桌面渲染为表格、移动端渲染为卡片列表。
 * 用于"表格在手机端转换为列表，不直接横向压缩"的改造要求。
 */
export function ResponsiveDataList<T>({
  items,
  getKey,
  renderDesktopRow,
  renderMobileRow,
  desktopHeader,
  empty,
  mobileHeader,
}: ResponsiveDataListProps<T>) {
  if (items.length === 0) {
    return <>{empty}</>;
  }
  return (
    <>
      {/* 桌面端表格（≥768px） */}
      <div className="hidden md:block">
        <div className="overflow-x-auto rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_6px_18px_rgba(59,130,246,0.06)]">
          {desktopHeader && (
            <div className="border-b border-[#eef2f7] bg-[#f8fbff] px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {desktopHeader}
            </div>
          )}
          <div className="divide-y divide-[#eef2f7]">
            {items.map((item) => (
              <div key={getKey(item)}>{renderDesktopRow(item)}</div>
            ))}
          </div>
        </div>
      </div>

      {/* 移动端卡片列表（<768px） */}
      <div className="space-y-3 md:hidden">
        {mobileHeader && <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{mobileHeader}</div>}
        {items.map((item) => (
          <div key={getKey(item)}>{renderMobileRow(item)}</div>
        ))}
      </div>
    </>
  );
}
