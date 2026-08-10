import type { ReactNode } from 'react';
import { BookOpen, Sparkles, ListTodo, Compass, UserCircle2, LogOut, ShieldCheck } from 'lucide-react';
import { MobileBottomNav, type BottomNavItem } from '../mobile/MobileBottomNav';
import { MobileTopBar } from '../mobile/MobileTopBar';

/** 默认底部导航 5 项（作品/创作/任务/发现/我的），对应改造方案移动信息架构 */
export const DEFAULT_BOTTOM_NAV: BottomNavItem[] = [
  { key: 'stories', label: '作品', icon: BookOpen },
  { key: 'workspace', label: '创作', icon: Sparkles },
  { key: 'tasks', label: '任务', icon: ListTodo },
  { key: 'model-catalog', label: '发现', icon: Compass },
  { key: 'account', label: '我的', icon: UserCircle2 },
];

type MobileAppShellProps = {
  platform: { icon_url?: string; site_name?: string };
  session: { name: string; role: string } | null;
  activeKey: string;
  onNavigate: (key: string) => void;
  onLogout: () => void;
  onLogoClick: () => void;
  bottomNavItems?: BottomNavItem[];
  children: ReactNode;
};

/**
 * 移动端 App Shell（<768px）：MobileTopBar + 内容区 + MobileBottomNav。
 * 内容区底部预留导航高度 + safe-area。
 */
export function MobileAppShell({
  platform,
  session,
  activeKey,
  onNavigate,
  onLogout,
  onLogoClick,
  bottomNavItems = DEFAULT_BOTTOM_NAV,
  children,
}: MobileAppShellProps) {
  const isWorkspace = activeKey === 'workspace';
  return (
    <div className="flex h-full flex-col">
      <MobileTopBar
        title={isWorkspace ? '创作' : (platform.site_name || 'StoryCanvas')}
        subtitle={session ? (session.role === 'admin' ? '管理员' : session.name) : undefined}
        onBack={isWorkspace ? () => onNavigate('stories') : undefined}
        left={
          !isWorkspace ? (
            <button type="button" onClick={onLogoClick} className="-ml-1 rounded-lg p-1.5 transition hover:bg-slate-100" aria-label="首页">
              <img
                src={platform.icon_url || '/brand-mark.svg'}
                alt="logo"
                className="h-8 w-8 rounded-xl shadow-[0_10px_24px_rgba(59,130,246,0.14)]"
              />
            </button>
          ) : undefined
        }
        right={
          <div className="flex items-center gap-1">
            {/* 管理员：移动端管理入口（直达用户管理，保留核心运维能力） */}
            {session?.role === 'admin' && activeKey !== 'entitlements' && (
              <button
                type="button"
                onClick={() => onNavigate('entitlements')}
                className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"
                aria-label="管理后台"
              >
                <ShieldCheck size={20} />
              </button>
            )}
            <button
              type="button"
              onClick={onLogout}
              className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"
              aria-label="退出登录"
            >
              <LogOut size={20} />
            </button>
          </div>
        }
      />
      <main
        className={`min-h-0 flex-1 ${isWorkspace ? 'overflow-hidden' : 'overflow-y-auto'}`}
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 64px)' }}
      >
        {children}
      </main>
      <MobileBottomNav items={bottomNavItems} activeKey={activeKey} onNavigate={onNavigate} />
    </div>
  );
}
