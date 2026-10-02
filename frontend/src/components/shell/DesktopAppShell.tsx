import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { PanelLeftClose, PanelLeftOpen, LogOut } from 'lucide-react';

export type ShellNavItem = {
  key: string;
  label: string;
  icon: LucideIcon;
};

type SharedShellHeaderProps = {
  platform: { icon_url?: string; site_name?: string; site_slogan?: string };
  session: { name: string; role: string } | null;
  onLogout: () => void;
  onLogoClick: () => void;
};

/** 桌面/平板共用顶部栏：Logo + 站点名 + 角色徽标 + 用户名 + 退出 */
export function SharedShellHeader({ platform, session, onLogout, onLogoClick }: SharedShellHeaderProps) {
  return (
    <header className="sticky top-0 z-20 border-b border-[#d7e3f4] bg-[rgba(248,251,255,0.82)] backdrop-blur-xl">
      <div className="flex h-14 items-center justify-between px-5 lg:px-8">
        <button type="button" onClick={onLogoClick} className="flex items-center gap-3 text-left transition hover:opacity-90">
          <img
            src={platform.icon_url || '/brand-mark.svg'}
            alt={`${platform.site_name || 'StoryCanvas'} logo`}
            className="h-9 w-9 rounded-2xl shadow-[0_10px_24px_rgba(59,130,246,0.14)]"
          />
          <div>
            <div className="text-sm font-semibold tracking-wide">{platform.site_name || 'StoryCanvas'}</div>
            <div className="text-[11px] text-slate-500">{platform.site_slogan || 'AI 小说与漫画创作平台'}</div>
          </div>
        </button>
        <div className="flex items-center gap-3 text-sm">
          <span className="rounded-full border border-[#d7e3f4] bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 shadow-[0_6px_18px_rgba(59,130,246,0.08)]">
            {session?.role === 'admin' ? '管理员' : '用户'}
          </span>
          <span className="hidden sm:inline">{session?.name}</span>
          <button
            type="button"
            onClick={onLogout}
            className="inline-flex items-center gap-1 rounded-full border border-[#d7e3f4] bg-white/90 px-3 py-1.5 text-xs text-slate-700 shadow-[0_6px_18px_rgba(59,130,246,0.08)] transition hover:bg-[#eef5ff]"
          >
            <LogOut size={14} />
            退出
          </button>
        </div>
      </div>
    </header>
  );
}

type SideNavProps = {
  items: ShellNavItem[];
  activeKey: string;
  onNavigate: (key: string) => void;
  collapsed: boolean;
  sectionLabel?: string;
  onDeconstructionClick?: () => void;
};

/** 侧边导航列表（支持收起为图标栏） */
export function SideNav({ items, activeKey, onNavigate, collapsed, sectionLabel, onDeconstructionClick }: SideNavProps) {
  return (
    <nav className="space-y-1.5">
      {sectionLabel && !collapsed && (
        <div className="mb-2 hidden text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 lg:block">
          {sectionLabel}
        </div>
      )}
      {items.map((item) => {
        const Icon = item.icon;
        const active = activeKey === item.key;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => {
              if (onDeconstructionClick && item.key === 'deconstruction-library') onDeconstructionClick();
              onNavigate(item.key);
            }}
            title={collapsed ? item.label : undefined}
            aria-label={item.label}
            className={`flex w-full items-center justify-center rounded-xl px-2 py-2.5 text-left text-sm transition ${collapsed ? '' : 'lg:justify-start lg:gap-2 lg:px-3'} ${
              active
                ? 'bg-[linear-gradient(180deg,_#fafdff_0%,_#e8f1ff_100%)] text-[#1d4ed8] shadow-[0_10px_24px_rgba(59,130,246,0.14)]'
                : 'text-slate-700 hover:bg-white/80'
            }`}
          >
            <Icon size={16} />
            <span className={collapsed ? 'hidden' : 'hidden lg:inline'}>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

type DesktopAppShellProps = {
  platform: { icon_url?: string; site_name?: string; site_slogan?: string };
  session: { name: string; role: string } | null;
  isAdmin: boolean;
  navItems: ShellNavItem[];
  adminNavItems: ShellNavItem[];
  activeKey: string;
  onNavigate: (key: string) => void;
  onLogout: () => void;
  onLogoClick: () => void;
  onDeconstructionClick?: () => void;
  navCollapsed: boolean;
  onToggleNav: () => void;
  children: ReactNode;
};

/**
 * 桌面端 App Shell（≥1200px）：完整侧栏（220px 可收起）+ 顶部栏。
 */
export function DesktopAppShell({
  platform,
  session,
  isAdmin,
  navItems,
  adminNavItems,
  activeKey,
  onNavigate,
  onLogout,
  onLogoClick,
  onDeconstructionClick,
  navCollapsed,
  onToggleNav,
  children,
}: DesktopAppShellProps) {
  return (
    <div className="flex h-full flex-col">
      <SharedShellHeader platform={platform} session={session} onLogout={onLogout} onLogoClick={onLogoClick} />
      <div className={`grid min-h-0 flex-1 grid-cols-[68px_minmax(0,1fr)] ${navCollapsed ? 'lg:grid-cols-[68px_minmax(0,1fr)]' : 'lg:grid-cols-[220px_minmax(0,1fr)]'}`}>
        <aside className="overflow-y-auto border-r border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(248,251,255,0.94)_0%,_rgba(238,244,255,0.92)_100%)] px-2 py-4 backdrop-blur-xl">
          <div className={`mb-4 flex items-center justify-center ${navCollapsed ? '' : 'lg:justify-between lg:px-2'}`}>
            {!navCollapsed ? <div className="hidden text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 lg:block">应用菜单</div> : null}
            <button
              type="button"
              onClick={onToggleNav}
              className="rounded-lg p-2 text-slate-400 transition hover:bg-white/80 hover:text-slate-700"
              title={navCollapsed ? '展开菜单' : '收起菜单'}
              aria-label={navCollapsed ? '展开菜单' : '收起菜单'}
            >
              {navCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            </button>
          </div>
          <SideNav
            items={navItems}
            activeKey={activeKey}
            onNavigate={onNavigate}
            collapsed={navCollapsed}
            onDeconstructionClick={onDeconstructionClick}
          />
          {isAdmin && (
            <div className="mt-6 border-t border-[#d7e3f4] pt-3">
              <SideNav
                items={adminNavItems}
                activeKey={activeKey}
                onNavigate={onNavigate}
                collapsed={navCollapsed}
                sectionLabel="运营配置"
              />
            </div>
          )}
        </aside>
        <main className="min-h-0 overflow-y-auto bg-transparent">{children}</main>
      </div>
    </div>
  );
}
