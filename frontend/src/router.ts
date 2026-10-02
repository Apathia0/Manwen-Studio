export type RouteKey =
  | 'install'
  | 'landing'
  | 'login'
  | 'register'
  | 'pricing'
  | 'stories'
  | 'manga-drama'
  | 'manga-drama-workspace'
  | 'creation-studio'
  | 'model-catalog'
  | 'onboarding'
  | 'import-guidance'
  | 'workspace'
  | 'account'
  | 'templates'
  | 'template-review'
  | 'forgot-password'
  | 'plan-config'
  | 'quota-rules'
  | 'entitlements'
  | 'orders'
  | 'revenue'
  | 'audit-logs'
  | 'announcement'
  | 'system-update'
  | 'system-prompts'
  | 'style-presets'
  | 'deconstruction-library'
  | 'points-ai-admin'
  | 'tasks';

/** RouteKey → URL path 映射（react-router 正式路由） */
export const ROUTE_PATHS: Record<RouteKey, string> = {
  install: '/install',
  landing: '/',
  login: '/login',
  register: '/register',
  pricing: '/pricing',
  stories: '/stories',
  'manga-drama': '/manga-drama',
  'manga-drama-workspace': '/manga-drama/workspace',
  'creation-studio': '/creation-studio',
  'model-catalog': '/model-catalog',
  onboarding: '/onboarding',
  'import-guidance': '/import-guidance',
  workspace: '/workspace',
  account: '/account',
  templates: '/templates',
  'template-review': '/template-review',
  'forgot-password': '/forgot-password',
  'plan-config': '/admin/plan-config',
  'quota-rules': '/admin/quota-rules',
  entitlements: '/admin/entitlements',
  orders: '/admin/orders',
  revenue: '/admin/revenue',
  'audit-logs': '/admin/audit-logs',
  announcement: '/admin/announcement',
  'system-update': '/admin/system-update',
  'system-prompts': '/admin/system-prompts',
  'style-presets': '/admin/style-presets',
  'deconstruction-library': '/deconstruction',
  'points-ai-admin': '/admin/points-ai-admin',
  tasks: '/tasks',
};

const PATH_TO_ROUTE: Record<string, RouteKey> = Object.fromEntries(
  (Object.entries(ROUTE_PATHS) as [RouteKey, string][]).map(([key, path]) => [path, key]),
);

/** URL path → RouteKey（未知路径回退到 landing；支持 /deconstruction/:id、/deconstruction/new、/workspace/:storyId 动态段） */
export function pathToRouteKey(pathname: string): RouteKey {
  if (/^\/deconstruction\/(\d+|new)$/.test(pathname)) return 'deconstruction-library';
  if (/^\/workspace\/\d+$/.test(pathname)) return 'workspace';
  if (/^\/manga-drama\/workspace\/\d+$/.test(pathname)) return 'manga-drama-workspace';
  return PATH_TO_ROUTE[pathname] ?? 'landing';
}

/** 从 /manga-drama/workspace/:storyId 解析漫剧项目 ID（无匹配返回 null） */
export function parseMangaDramaStoryId(pathname: string): number | null {
  const match = pathname.match(/^\/manga-drama\/workspace\/(\d+)$/);
  return match ? Number(match[1]) : null;
}

/** 从 /deconstruction/:id 解析拆书工作 ID；/deconstruction/new 返回 -1（新建模式）；无匹配返回 0 = 列表页 */
export function parseDeconstructionWorkId(pathname: string): number {
  if (pathname === '/deconstruction/new') return -1;
  const match = pathname.match(/^\/deconstruction\/(\d+)$/);
  return match ? Number(match[1]) : 0;
}

/** 从 /workspace/:storyId 解析作品 ID（无匹配返回 null） */
export function parseWorkspaceStoryId(pathname: string): number | null {
  const match = pathname.match(/^\/workspace\/(\d+)$/);
  return match ? Number(match[1]) : null;
}

/** RouteKey → URL path */
export function routeToPath(key: RouteKey): string {
  return ROUTE_PATHS[key] ?? '/';
}

/** 公开路由（未登录可访问）：安装/落地/登录/注册/找回密码/公开定价 */
export const PUBLIC_ROUTES: RouteKey[] = ['install', 'landing', 'login', 'register', 'forgot-password', 'pricing'];

/** 管理员专属路由 */
export const ADMIN_ROUTES: RouteKey[] = [
  'plan-config',
  'quota-rules',
  'entitlements',
  'orders',
  'revenue',
  'audit-logs',
  'announcement',
  'system-update',
  'system-prompts',
  'style-presets',
  'template-review',
  'points-ai-admin',
];
