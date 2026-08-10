import type { LucideIcon } from 'lucide-react';

export type BottomNavItem = {
  key: string;
  label: string;
  icon: LucideIcon;
  activeIcon?: LucideIcon;
  badge?: number;
};

type MobileBottomNavProps = {
  items: BottomNavItem[];
  activeKey: string;
  onNavigate: (key: string) => void;
};

/**
 * 移动端底部导航（6 项：作品/创作/任务/发现/我的/资产）。
 * 仅在移动端渲染（<768px），桌面/平板使用侧栏。
 * 含 safe-area 底部内边距。
 */
export function MobileBottomNav({ items, activeKey, onNavigate }: MobileBottomNavProps) {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-[110] border-t border-[#d7e3f4] bg-white/95 backdrop-blur-xl md:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      aria-label="底部导航"
    >
      <div className="grid grid-cols-6">
        {items.map((item) => {
          const Icon = item.icon;
          const ActiveIcon = item.activeIcon;
          const active = activeKey === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onNavigate(item.key)}
              aria-label={item.label}
              aria-current={active ? 'page' : undefined}
              className={`relative flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[11px] transition ${
                active ? 'text-[#1d4ed8]' : 'text-slate-500 active:text-slate-700'
              }`}
            >
              {active && ActiveIcon ? <ActiveIcon size={22} /> : <Icon size={22} />}
              <span className="leading-tight">{item.label}</span>
              {item.badge != null && item.badge > 0 && (
                <span className="absolute right-[calc(50%-20px)] top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
                  {item.badge > 99 ? '99+' : item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
