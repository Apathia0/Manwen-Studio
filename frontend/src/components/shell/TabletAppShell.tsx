import type { ReactNode } from 'react';
import { SharedShellHeader, SideNav, type ShellNavItem } from './DesktopAppShell';

type TabletAppShellProps = {
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
  children: ReactNode;
};

/**
 * 平板端 App Shell（768–1199px）：固定 68px 图标侧栏 + 顶部栏。
 * 侧栏不提供展开，保持高密度但让出主内容区。
 */
export function TabletAppShell({
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
  children,
}: TabletAppShellProps) {
  return (
    <div className="flex h-full flex-col">
      <SharedShellHeader platform={platform} session={session} onLogout={onLogout} onLogoClick={onLogoClick} />
      <div className="grid min-h-0 flex-1 grid-cols-[68px_minmax(0,1fr)]">
        <aside className="overflow-y-auto border-r border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(248,251,255,0.94)_0%,_rgba(238,244,255,0.92)_100%)] px-2 py-4 backdrop-blur-xl">
          <div className="mb-4 flex items-center justify-center text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
            菜单
          </div>
          <SideNav items={navItems} activeKey={activeKey} onNavigate={onNavigate} collapsed />
          {isAdmin && (
            <>
              <div className="mb-3 mt-6 border-t border-[#d7e3f4]" />
              <SideNav
                items={adminNavItems}
                activeKey={activeKey}
                onNavigate={onNavigate}
                collapsed
                onDeconstructionClick={onDeconstructionClick}
              />
            </>
          )}
        </aside>
        <main className="min-h-0 overflow-y-auto bg-transparent">{children}</main>
      </div>
    </div>
  );
}
