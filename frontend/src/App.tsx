import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  BookOpen,
  Brush,
  Clapperboard,
  CreditCard,
  Home,
  Library,
  MessageSquareQuote,
  Cpu,
  Sparkles,
  Settings2,
  ShieldCheck,
  UserCircle2,
  X,
} from 'lucide-react';
import { useLocation, useNavigate, Navigate } from 'react-router-dom';
import { toast } from './lib/toast';
import { confirm } from './lib/confirm';
import {
  AI_MODEL_SELECTION_REQUIRED_EVENT,
  type AiModelSelectionRequiredDetail,
} from './lib/errors';
import { useDeviceMode } from './lib/useMediaQuery';
import {
  ADMIN_ROUTES,
  PUBLIC_ROUTES,
  parseDeconstructionWorkId,
  parseMangaDramaStoryId,
  parseWorkspaceStoryId,
  pathToRouteKey,
  routeToPath,
  type RouteKey,
} from './router';
import { WorkspaceProvider } from './context/WorkspaceContext';
import { LoadingOverlay } from './components/ui/LoadingOverlay';
import { RouteLoadingFallback } from './components/ui/RouteLoadingFallback';
import PublicLanding from './components/PublicLanding';
import StoryLibraryPage from './components/StoryLibraryPage';
import MangaDramaListPage from './components/MangaDramaListPage';
import MangaDramaWorkspacePage from './components/MangaDramaWorkspacePage';
import ImportGuidancePage from './components/ImportGuidancePage';
import OnboardingPage from './components/OnboardingPage';
import TemplateManagePage from './components/TemplateManagePage';
import AdminTemplateReview from './components/AdminTemplateReview';
import {
  AdminAnnouncementPage,
  AdminAuditLogsPage,
  AdminPlatformSettingsPage,
  AdminRevenueDashboardPage,
  AdminSystemUpdatePage,
  AdminSystemPromptsPage,
  AdminUserManagementPage,
} from './components/admin/AdminPages';
import StylePresetManager from './components/admin/StylePresetManager';
import { LoginPage } from './components/LoginPage';
import { ForgotPasswordPage } from './components/ForgotPasswordPage';
import { RegisterPage } from './components/RegisterPage';
import { InstallWizardPage } from './components/InstallWizardPage';
import { PricingPublicPage } from './components/PricingPublicPage';
import { WorkspacePage } from './components/WorkspacePage';
import DeconstructionLibraryPage from './components/DeconstructionLibraryPage';
import DeconstructionWorkPage from './components/DeconstructionWorkPage';
import { PaymentCheckoutDialog } from './components/PaymentCheckoutDialog';
import { UserPricingPage } from './components/UserPricingPage';
import { UserAccountUsagePage } from './components/UserAccountUsagePage';
import { PointsAiAdminPage } from './components/admin/PointsAiAdminPage';
import { CreationStudioPage } from './components/CreationStudioPage';
import { ModelCatalogPage } from './components/ModelCatalogPage';
import { TasksPage } from './components/TasksPage';
import { DesktopAppShell, type ShellNavItem } from './components/shell/DesktopAppShell';
import { TabletAppShell } from './components/shell/TabletAppShell';
import { MobileAppShell, DEFAULT_BOTTOM_NAV } from './components/shell/MobileAppShell';
import type { BottomNavItem } from './components/mobile/MobileBottomNav';
import {
  cancelMyOrder,
  clearAuthToken,
  confirmMyOrderMock,
  createStory,
  getMyOrders,
  getPublicAnnouncement,
  getPublicPlatformSettings,
  getStory,
  listChapters,
  listStories,
  login,
  logout as logoutApi,
  me,
  register,
  sendEmailVerificationCode,
  sendResetEmailCode,
  resetPassword as resetPasswordApi,
  setAuthToken,
  syncMyOrder,
  updateStory,
  deleteStory,
  getInstallStatus,
  checkHealth,
  type AdminOrderItem,
  type AuthUser,
  type BillingCheckout,
  type Chapter,
  type PlatformAnnouncement,
  type PublicPlatformSettings,
  type Story,
} from './api';

const DEFAULT_SITE_NAME = 'StoryCanvas';
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台';
const DEFAULT_ICON_URL = '/brand-mark.svg';
const LS_WORKSPACE_MODE = 'storycanvas.workspaceMode';
const LS_NAV_COLLAPSED = 'storycanvas.navCollapsed';

const USER_NAV: ShellNavItem[] = [
  { key: 'stories', label: '小说作品', icon: Home },
  { key: 'manga-drama', label: '无限画布', icon: Clapperboard },
  { key: 'workspace', label: '作品工作台', icon: Brush },
  { key: 'creation-studio', label: '创作台', icon: Sparkles },
  { key: 'model-catalog', label: '模型广场', icon: Cpu },
  { key: 'deconstruction-library', label: '拆书库', icon: BookOpen },
  { key: 'account', label: '账户与积分', icon: UserCircle2 },
  { key: 'pricing', label: '积分套餐', icon: CreditCard },
];

const MOBILE_NAV_ITEMS: BottomNavItem[] = DEFAULT_BOTTOM_NAV;

const ADMIN_NAV: ShellNavItem[] = [
  { key: 'points-ai-admin', label: '积分与 AI 渠道', icon: CreditCard },
  { key: 'quota-rules', label: '平台配置', icon: Settings2 },
  { key: 'entitlements', label: '用户管理', icon: ShieldCheck },
  { key: 'revenue', label: '收入与订单', icon: BarChart3 },
  { key: 'audit-logs', label: '操作审计', icon: MessageSquareQuote },
  { key: 'announcement', label: '公告管理', icon: MessageSquareQuote },
  { key: 'style-presets', label: '风格预设', icon: Brush },
  { key: 'template-review', label: '模板审核', icon: Library },
  { key: 'system-prompts', label: '系统提示词', icon: MessageSquareQuote },
  { key: 'system-update', label: '系统更新', icon: Settings2 },
];

/** 已登录用户访问这些公开路由时重定向到作品库 */
const LOGGED_IN_REDIRECT_ROUTES: RouteKey[] = ['landing', 'login', 'register', 'forgot-password'];

// 记住最近一次打开的工作台地址（小说工作台或画布创作台），侧栏「作品工作台」直接回到它
const LAST_WORKSPACE_PATH_KEY = 'storycanvas:last-workspace-path';
const WORKSPACE_PATH_RE = /^\/(?:workspace|manga-drama\/workspace)\/\d+\/?$/;
function readLastWorkspacePath(): string | null {
  try {
    const value = window.localStorage.getItem(LAST_WORKSPACE_PATH_KEY);
    return value && WORKSPACE_PATH_RE.test(value) ? value : null;
  } catch { return null; }
}
function writeLastWorkspacePath(path: string) {
  try { window.localStorage.setItem(LAST_WORKSPACE_PATH_KEY, path); } catch { /* 存储不可用时只是少了记忆，不影响使用 */ }
}

function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const deviceMode = useDeviceMode();

  const route: RouteKey = useMemo(() => pathToRouteKey(location.pathname), [location.pathname]);
  const deconWorkId = useMemo(() => parseDeconstructionWorkId(location.pathname), [location.pathname]);
  const workspaceStoryId = useMemo(() => parseWorkspaceStoryId(location.pathname), [location.pathname]);
  const mangaDramaStoryId = useMemo(() => parseMangaDramaStoryId(location.pathname), [location.pathname]);

  const setRoute = useCallback((key: RouteKey) => {
    navigate(routeToPath(key));
  }, [navigate]);

  const setDeconWorkId = useCallback((workId: number) => {
    navigate(workId === -1 ? '/deconstruction/new' : workId > 0 ? `/deconstruction/${workId}` : '/deconstruction');
  }, [navigate]);

  const [session, setSession] = useState<AuthUser | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [stories, setStories] = useState<Story[]>([]);
  const [activeStory, setActiveStory] = useState<Story | null>(null);
  const [onboardingStory, setOnboardingStory] = useState<Story | null>(null);
  const [importGuidanceStory, setImportGuidanceStory] = useState<Story | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [activeChapterId, setActiveChapterId] = useState<number | null>(null);
  const [loadingStories, setLoadingStories] = useState(false);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [platform, setPlatform] = useState<PublicPlatformSettings>({
    site_name: DEFAULT_SITE_NAME,
    site_slogan: DEFAULT_SITE_SLOGAN,
    support_email: '',
    icp: '',
    copyright: '',
    notice: '',
    icon_url: DEFAULT_ICON_URL,
    auth: {
      require_email_code_for_register: false,
      require_email_code_for_login: false,
      email_code_expire_minutes: 10,
    },
  });
  const [myOrders, setMyOrders] = useState<AdminOrderItem[]>([]);
  const [actioningOrderNo, setActioningOrderNo] = useState<string | null>(null);
  const [activeCheckout, setActiveCheckout] = useState<(BillingCheckout & { orderNo: string }) | null>(null);
  const [announcement, setAnnouncement] = useState<PlatformAnnouncement | null>(null);
  const [announcementDismissed, setAnnouncementDismissed] = useState(false);
  const [installRequired, setInstallRequired] = useState(false);
  const [workspaceMode, setWorkspaceMode] = useState<'novel' | 'manga' | 'video'>(() => {
    const savedMode = localStorage.getItem(LS_WORKSPACE_MODE);
    if (savedMode === 'novel' || savedMode === 'manga' || savedMode === 'video') return savedMode;
    return localStorage.getItem('rightPanelTab') === 'manga' ? 'manga' : 'novel';
  });
  const [navCollapsed, setNavCollapsed] = useState(() => localStorage.getItem(LS_NAV_COLLAPSED) === 'true');
  const [modelConfigRequest, setModelConfigRequest] = useState<{
    modality: AiModelSelectionRequiredDetail['modality'];
    requestId: number;
  } | null>(null);

  const activeChapter = useMemo(
    () => chapters.find((chapter) => chapter.id === activeChapterId) ?? null,
    [chapters, activeChapterId],
  );

  const workspaceContextValue = useMemo(
    () => ({
      activeStory,
      chapters,
      activeChapterId,
      activeChapter,
      workspaceMode,
      setActiveStory,
      setChapters,
      setActiveChapterId,
      setWorkspaceMode,
    }),
    [activeStory, chapters, activeChapterId, activeChapter, workspaceMode],
  );

  // 漫剧画布工作台与小说工作台一样需要全高内容区（否则画布 h-full 链断裂收成 0 高度）
  const isWorkspaceRoute = route === 'workspace' || route === 'manga-drama-workspace';

  const handleModelConfigRequestHandled = useCallback((requestId: number) => {
    setModelConfigRequest((current) => current?.requestId === requestId ? null : current);
  }, []);

  /** 统一导航入口：移动底部导航 / 桌面侧栏 / 页面内跳转共用 */
  const handleNavigate = useCallback((key: string) => {
    const routeKey = key as RouteKey;
    if (routeKey === 'workspace') {
      // 回到最近用过的工作台：可能是小说工作台，也可能是画布创作台；从没打开过才让用户去选
      const lastPath = readLastWorkspacePath();
      if (lastPath) {
        navigate(lastPath);
        return;
      }
      if (!activeStory) {
        toast.info('请先在「小说作品」或「无限画布」里打开一个作品');
        navigate('/stories');
        return;
      }
    }
    if (routeKey === 'deconstruction-library') {
      navigate('/deconstruction');
      return;
    }
    if (routeKey === 'tasks') {
      navigate('/tasks');
      return;
    }
    navigate(routeToPath(routeKey));
  }, [activeStory, navigate]);

  useEffect(() => {
    let promptOpen = false;
    const handleModelSelectionRequired = (event: Event) => {
      if (promptOpen) return;
      const detail = (event as CustomEvent<AiModelSelectionRequiredDetail>).detail;
      if (!detail) return;
      promptOpen = true;
      const firstConfiguration = detail.reason === 'missing';
      void confirm({
        title: firstConfiguration ? '首次使用前请配置模型' : '需要重新配置模型',
        message: firstConfiguration ? `使用 AI 功能前，${detail.message}。` : detail.message,
        confirmText: '去配置模型',
        cancelText: firstConfiguration ? '稍后配置' : '暂不配置',
        danger: false,
      }).then((accepted) => {
        if (!accepted) return;
        setModelConfigRequest({ modality: detail.modality, requestId: Date.now() });
        setRoute('account');
      }).finally(() => {
        promptOpen = false;
      });
    };
    window.addEventListener(AI_MODEL_SELECTION_REQUIRED_EVENT, handleModelSelectionRequired);
    return () => window.removeEventListener(AI_MODEL_SELECTION_REQUIRED_EVENT, handleModelSelectionRequired);
  }, [setRoute]);

  useEffect(() => {
    localStorage.setItem(LS_WORKSPACE_MODE, workspaceMode);
  }, [workspaceMode]);

  useEffect(() => {
    localStorage.setItem(LS_NAV_COLLAPSED, String(navCollapsed));
  }, [navCollapsed]);

  useEffect(() => {
    void bootstrapApp();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const siteName = platform.site_name?.trim() || DEFAULT_SITE_NAME;
    const siteSlogan = platform.site_slogan?.trim();
    document.title = siteSlogan ? `${siteName} - ${siteSlogan}` : siteName;
  }, [platform]);

  useEffect(() => {
    const iconHref = platform.icon_url?.trim() || DEFAULT_ICON_URL;
    let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.type = iconHref.endsWith('.svg') ? 'image/svg+xml' : 'image/png';
    link.href = iconHref;
  }, [platform.icon_url]);

  useEffect(() => {
    if (!session) return;
    void refreshStories();
    void refreshOrders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  // 进入任一工作台就记下地址，侧栏「作品工作台」回到它
  useEffect(() => {
    if (WORKSPACE_PATH_RE.test(location.pathname)) writeLastWorkspacePath(location.pathname);
  }, [location.pathname]);

  /** 深链支持：/workspace/:storyId 直接定位作品工作台 */
  useEffect(() => {
    if (!session) return;
    if (workspaceStoryId == null) return;
    if (activeStory?.id === workspaceStoryId) return;
    setLoadingWorkspace(true);
    void (async () => {
      try {
        const [detail, chapterList] = await Promise.all([getStory(workspaceStoryId), listChapters(workspaceStoryId)]);
        if (needsImportGuidance(detail)) {
          setImportGuidanceStory(detail);
          navigate('/import-guidance');
          return;
        }
        if (!detail.onboarding_completed) {
          setOnboardingStory(detail);
          navigate('/onboarding');
          return;
        }
        setActiveStory(detail);
        setChapters(chapterList);
        setActiveChapterId(chapterList[0]?.id ?? null);
      } catch (error: any) {
        toast.error(error.message || '加载作品失败');
        navigate('/stories');
      } finally {
        setLoadingWorkspace(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceStoryId, session]);

  async function bootstrapApp() {
    try {
      const status = await getInstallStatus();
      if (!status.installed || status.requires_restart) {
        clearAuthToken();
        setSession(null);
        setInstallRequired(true);
        navigate('/install');
        return;
      }
      setInstallRequired(false);
      void refreshPlatformSettings();
      await bootstrapSession();
    } catch {
      clearAuthToken();
      setSession(null);
      navigate('/');
      const health = await checkHealth();
      if (health === null) {
        toast.error('无法连接到后端服务，请确认后端已启动后刷新页面');
      } else if (!health.ready) {
        toast.error('后端服务正在初始化或数据库未就绪，请稍后刷新页面');
      }
    } finally {
      setBootstrapping(false);
    }
  }

  async function bootstrapSession() {
    try {
      const user = await me();
      setSession(user);
      if (PUBLIC_ROUTES.includes(route)) {
        navigate('/stories');
      }
      void fetchAnnouncement();
    } catch {
      clearAuthToken();
      setSession(null);
      if (route !== 'install') navigate('/');
    }
  }

  async function refreshStories() {
    setLoadingStories(true);
    try {
      const data = await listStories();
      setStories(data);
    } catch (error: any) {
      toast.error(error.message || '加载作品失败');
    } finally {
      setLoadingStories(false);
    }
  }

  async function openWorkspace(story: Story) {
    setLoadingWorkspace(true);
    try {
      const [detail, chapterList] = await Promise.all([getStory(story.id), listChapters(story.id)]);
      if (needsImportGuidance(detail)) {
        setImportGuidanceStory(detail);
        navigate('/import-guidance');
        return;
      }
      if (!detail.onboarding_completed) {
        setOnboardingStory(detail);
        navigate('/onboarding');
        return;
      }
      setActiveStory(detail);
      setChapters(chapterList);
      setActiveChapterId(chapterList[0]?.id ?? null);
      navigate(`/workspace/${detail.id}`);
    } catch (error: any) {
      toast.error(error.message || '进入工作台失败');
    } finally {
      setLoadingWorkspace(false);
    }
  }

  async function refreshWorkspaceData() {
    if (!activeStory) return;
    const [detail, chapterList] = await Promise.all([getStory(activeStory.id), listChapters(activeStory.id)]);
    setActiveStory(detail);
    setChapters(chapterList);
    if (!chapterList.find((chapter) => chapter.id === activeChapterId)) {
      setActiveChapterId(chapterList[0]?.id ?? null);
    }
  }

  const handleChapterChange = useCallback(
    (chapter: Chapter) => setActiveChapterId(chapter.id),
    [],
  );

  async function createNewStory() {
    try {
      const next = await createStory(`新故事 ${stories.length + 1}`, '从这里开始你的下一段创作旅程');
      setStories((prev) => [next, ...prev]);
      setOnboardingStory(next);
      navigate('/onboarding');
    } catch (error: any) {
      toast.error(error.message || '新建作品失败');
    }
  }

  async function handleOnboardingComplete(storyId: number) {
    setOnboardingStory(null);
    const story = await getStory(storyId);
    setStories((prev) => prev.map((item) => (item.id === story.id ? story : item)));
    await openWorkspace(story);
  }

  async function handleImportGuidanceComplete(storyId: number) {
    setImportGuidanceStory(null);
    const story = await getStory(storyId);
    setStories((prev) => prev.map((item) => (item.id === story.id ? story : item)));
    await openWorkspace(story);
  }

  async function createStoryDraft(title: string, description: string) {
    const next = await createStory(title, description);
    setStories((prev) => [next, ...prev]);
    toast.success('草稿创建成功');
    return next;
  }

  async function updateStoryDraft(storyId: number, payload: { title?: string; description?: string }) {
    const updated = await updateStory(storyId, payload);
    setStories((prev) => prev.map((story) => (story.id === updated.id ? updated : story)));
    setActiveStory((prev) => (prev?.id === updated.id ? updated : prev));
    toast.success('保存成功');
    return updated;
  }

  async function deleteStoryDraft(story: Story) {
    await deleteStory(story.id);
    setStories((prev) => prev.filter((item) => item.id !== story.id));
    setActiveStory((prev) => (prev?.id === story.id ? null : prev));
    if (activeStory?.id === story.id) {
      setChapters([]);
      setActiveChapterId(null);
      navigate('/stories');
    }
    toast.success('作品已删除');
  }

  async function doLogin(email: string, password: string, verificationCode?: string) {
    try {
      const result = await login({ email, password, verification_code: verificationCode });
      setAuthToken(result.token);
      setSession(result.user);
      navigate('/stories');
      void fetchAnnouncement();
    } catch (error: any) {
      clearAuthToken();
      setSession(null);
      toast.error(error.message || '登录失败');
    }
  }

  async function doRegister(name: string, email: string, password: string, verificationCode?: string) {
    try {
      const result = await register({ name, email, password, verification_code: verificationCode });
      setAuthToken(result.token);
      setSession(result.user);
      navigate('/stories');
      void fetchAnnouncement();
    } catch (error: any) {
      clearAuthToken();
      setSession(null);
      toast.error(error.message || '注册失败');
    }
  }

  async function doSendAuthCode(email: string, purpose: 'register' | 'login') {
    try {
      const result = await sendEmailVerificationCode({ email, purpose });
      const minutes = Math.max(1, Math.round((result.expires_in_seconds || 600) / 60));
      toast.success(`验证码已发送，请在 ${minutes} 分钟内完成${purpose === 'register' ? '注册' : '登录'}。`);
    } catch (error: any) {
      toast.error(error.message || '验证码发送失败');
      throw error;
    }
  }

  async function doLogout() {
    try {
      await logoutApi();
    } catch {
      // ignore network errors
    } finally {
      clearAuthToken();
      setSession(null);
      setStories([]);
      setActiveStory(null);
      setChapters([]);
      setActiveChapterId(null);
      navigate('/');
    }
  }

  async function doSendResetEmailCode(email: string) {
    const result = await sendResetEmailCode(email);
    const minutes = Math.max(1, Math.round((result.expires_in_seconds || 600) / 60));
    toast.success(`验证码已发送至 ${email}，请在 ${minutes} 分钟内完成重置。`);
    return result;
  }

  async function doResetPassword(email: string, verificationCode: string, newPassword: string) {
    const result = await resetPasswordApi(email, verificationCode, newPassword);
    toast.success(result.message || '密码已重置，请使用新密码登录。');
    navigate('/login');
  }

  async function refreshOrders() {
    try {
      const orders = await getMyOrders();
      setMyOrders(orders);
    } catch {
      setMyOrders([]);
    }
  }

  async function refreshPlatformSettings() {
    try {
      const data = await getPublicPlatformSettings();
      setPlatform(data);
    } catch {
      setPlatform((prev) => prev);
    }
  }

  async function fetchAnnouncement() {
    try {
      const data = await getPublicAnnouncement();
      setAnnouncement(data.enabled && data.content ? data : null);
      setAnnouncementDismissed(false);
    } catch {
      setAnnouncement(null);
    }
  }

  async function confirmPendingOrder(orderNo: string) {
    setActioningOrderNo(orderNo);
    try {
      await confirmMyOrderMock(orderNo);
      await refreshOrders();
      setActiveCheckout((prev) => (prev?.orderNo === orderNo ? null : prev));
      toast.success('支付成功，积分已到账。');
      navigate('/account');
    } catch (error: any) {
      toast.error(error.message || '确认支付失败');
    } finally {
      setActioningOrderNo(null);
    }
  }

  async function cancelPendingOrder(orderNo: string) {
    setActioningOrderNo(orderNo);
    try {
      await cancelMyOrder(orderNo);
      await refreshOrders();
      setActiveCheckout((prev) => (prev?.orderNo === orderNo ? null : prev));
    } catch (error: any) {
      toast.error(error.message || '取消订单失败');
    } finally {
      setActioningOrderNo(null);
    }
  }

  if (installRequired || route === 'install') {
    return (
      <>
        <LoadingOverlay visible={bootstrapping} message="正在检查安装状态..." />
        <InstallWizardPage
          onInstalled={() => {
            setBootstrapping(true);
            void bootstrapApp();
          }}
        />
      </>
    );
  }

  if (!session && route === 'login') {
    return (
        <LoginPage
          title={platform.site_name}
          subtitle={platform.site_slogan}
          onBack={() => navigate('/')}
          onLogin={doLogin}
          onSendCode={doSendAuthCode}
          requireEmailCode={Boolean(platform.auth?.require_email_code_for_login)}
          codeExpireMinutes={platform.auth?.email_code_expire_minutes || 10}
          toRegister={() => navigate('/register')}
          toForgotPassword={() => navigate('/forgot-password')}
          error={null}
        />
    );
  }
  if (!session && route === 'forgot-password') {
    return (
      <ForgotPasswordPage
        title={platform.site_name}
        subtitle={platform.site_slogan}
        onBack={() => navigate('/login')}
        onSendCode={doSendResetEmailCode}
        onResetPassword={doResetPassword}
        error={null}
      />
    );
  }
  if (!session && route === 'register') {
    return (
        <RegisterPage
          title={platform.site_name}
          subtitle={platform.site_slogan}
          onBack={() => navigate('/')}
          onRegister={doRegister}
          onSendCode={doSendAuthCode}
          requireEmailCode={Boolean(platform.auth?.require_email_code_for_register)}
          codeExpireMinutes={platform.auth?.email_code_expire_minutes || 10}
          toLogin={() => navigate('/login')}
          error={null}
        />
    );
  }
    if (!session && route === 'pricing') {
      return <PricingPublicPage onBack={() => navigate('/')} onRegister={() => navigate('/register')} />;
    }
  if (!session) {
    if (PUBLIC_ROUTES.includes(route)) {
      return (
        <PublicSite
          platform={platform}
          onLogin={() => navigate('/login')}
          onRegister={() => navigate('/register')}
          onPricing={() => navigate('/pricing')}
        />
      );
    }
    return <Navigate to="/" replace />;
  }

  if (LOGGED_IN_REDIRECT_ROUTES.includes(route)) {
    return <Navigate to="/stories" replace />;
  }
  if (route === 'workspace' && !activeStory && workspaceStoryId == null) {
    return <Navigate to="/stories" replace />;
  }
  if ((route === 'onboarding' || route === 'import-guidance') && !onboardingStory && !importGuidanceStory) {
    return <Navigate to="/stories" replace />;
  }

  const renderContent = () => (
    <Suspense fallback={<RouteLoadingFallback />}>
      {route === 'stories' && (
        <StoryLibraryPage
          stories={stories}
          loading={loadingStories}
          onRefresh={refreshStories}
          onCreate={createNewStory}
          onCreateDraft={createStoryDraft}
          onUpdateStory={updateStoryDraft}
          onDeleteStory={deleteStoryDraft}
          onOpen={openWorkspace}
          onImportComplete={(storyId) => {
            void refreshStories();
            navigate(`/workspace/${storyId}`);
          }}
          loadingWorkspace={loadingWorkspace}
        />
      )}
      {route === 'manga-drama' && (
        <MangaDramaListPage onOpenProject={(storyId) => navigate(`/manga-drama/workspace/${storyId}`)} />
      )}
      {route === 'manga-drama-workspace' && mangaDramaStoryId && (
        <MangaDramaWorkspacePage storyId={mangaDramaStoryId} onBack={() => navigate('/manga-drama')} />
      )}
      {route === 'deconstruction-library' && deconWorkId !== 0 ? (
        <DeconstructionWorkPage
          workId={deconWorkId}
          onBack={() => setDeconWorkId(0)}
        />
      ) : route === 'deconstruction-library' ? (
        <DeconstructionLibraryPage
          onNavigate={(r, workId) => {
            if (r === 'deconstruction-work' && workId) {
              setDeconWorkId(workId);
            } else if (r === 'deconstruction-work' && !workId) {
              setDeconWorkId(-1);
            } else if (r === 'stories') {
              navigate('/stories');
              setDeconWorkId(0);
            }
          }}
        />
      ) : null}
      {route === 'onboarding' && onboardingStory && (
        <OnboardingPage
          story={onboardingStory}
          onComplete={handleOnboardingComplete}
          onBack={() => {
            setOnboardingStory(null);
            navigate('/stories');
          }}
        />
      )}
      {route === 'import-guidance' && importGuidanceStory && (
        <ImportGuidancePage
          story={importGuidanceStory}
          onComplete={handleImportGuidanceComplete}
          onBack={() => {
            setImportGuidanceStory(null);
            navigate('/stories');
          }}
        />
      )}
      {route === 'workspace' && activeStory && (
        <WorkspacePage
          story={activeStory}
          chapters={chapters}
          currentChapter={activeChapter}
          entitlements={null}
          workspaceMode={workspaceMode}
          onChapterChange={handleChapterChange}
          onContentUpdated={refreshWorkspaceData}
          onWorkspaceModeChange={setWorkspaceMode}
        />
      )}
      {route === 'tasks' && (
        <TasksPage
          onOpenWorkspace={(mode) => {
            setWorkspaceMode(mode);
            if (activeStory) navigate(`/workspace/${activeStory.id}`);
            else navigate('/stories');
          }}
        />
      )}
      {route === 'template-review' && (
        <AdminTemplateReview />
      )}
      {route === 'templates' && (
        <TemplateManagePage />
      )}
      {route === 'account' && (
        <UserAccountUsagePage
          session={session}
          platform={platform}
          orders={myOrders}
          actioningOrderNo={actioningOrderNo}
          onConfirmMockPayment={confirmPendingOrder}
          onCancelOrder={cancelPendingOrder}
          onRefreshOrders={refreshOrders}
          modelConfigRequest={modelConfigRequest}
          onModelConfigRequestHandled={handleModelConfigRequestHandled}
        />
      )}
      {route === 'points-ai-admin' && session.role === 'admin' && (
        <PointsAiAdminPage />
      )}
      {route === 'pricing' && (
        <UserPricingPage
          onCheckout={(checkout) => {
            setActiveCheckout(checkout);
            void refreshOrders();
          }}
        />
      )}
      {route === 'creation-studio' && (
        <CreationStudioPage
          storyId={activeStory?.id}
          chapterId={activeChapter?.id}
          storyTitle={activeStory?.title}
          chapterTitle={activeChapter?.title || undefined}
        />
      )}
      {route === 'model-catalog' && <ModelCatalogPage />}
      {route === 'quota-rules' && session.role === 'admin' && (
        <AdminPlatformSettingsPage
          onError={(message) => toast.error(message)}
          onSaved={() => {
            void refreshPlatformSettings();
          }}
        />
      )}
      {route === 'entitlements' && session.role === 'admin' && (
        <AdminUserManagementPage onError={(message) => toast.error(message)} />
      )}
      {route === 'revenue' && session.role === 'admin' && <AdminRevenueDashboardPage onError={(message) => toast.error(message)} />}
      {route === 'audit-logs' && session.role === 'admin' && (
        <AdminAuditLogsPage onError={(message: string) => toast.error(message)} />
      )}
      {route === 'announcement' && session.role === 'admin' && (
        <AdminAnnouncementPage onError={(message) => toast.error(message)} />
      )}
      {route === 'style-presets' && session.role === 'admin' && <StylePresetManager />}
      {route === 'system-prompts' && session.role === 'admin' && (
        <AdminSystemPromptsPage onError={(message: string) => toast.error(message)} />
      )}
      {route === 'system-update' && session.role === 'admin' && (
        <AdminSystemUpdatePage onError={(message: string) => toast.error(message)} />
      )}
      {ADMIN_ROUTES.includes(route) && session.role !== 'admin' && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <ShieldCheck size={36} className="mb-3 text-slate-300" />
          <div className="text-sm font-medium text-slate-600">该页面仅管理员可访问</div>
        </div>
      )}
    </Suspense>
  );

  const shellProps = {
    platform,
    session,
    isAdmin: session.role === 'admin',
    navItems: USER_NAV,
    adminNavItems: ADMIN_NAV,
    activeKey: route,
    onNavigate: handleNavigate,
    onLogout: () => void doLogout(),
    onLogoClick: () => navigate('/stories'),
    onDeconstructionClick: () => setDeconWorkId(0),
  };

  const shell =
    deviceMode === 'mobile' ? (
      <MobileAppShell {...shellProps} bottomNavItems={MOBILE_NAV_ITEMS} onLogoClick={() => navigate('/stories')}>
        <div className={isWorkspaceRoute ? 'h-full min-h-0 overflow-hidden' : 'p-4 lg:p-7'}>{renderContent()}</div>
      </MobileAppShell>
    ) : deviceMode === 'tablet' ? (
      <TabletAppShell {...shellProps}>
        <div className={isWorkspaceRoute ? 'h-full min-h-0 overflow-hidden' : 'p-4 lg:p-7'}>{renderContent()}</div>
      </TabletAppShell>
    ) : (
      <DesktopAppShell {...shellProps} navCollapsed={navCollapsed} onToggleNav={() => setNavCollapsed((value) => !value)}>
        <div className={isWorkspaceRoute ? 'h-full min-h-0 overflow-hidden' : 'p-5 lg:p-7'}>{renderContent()}</div>
      </DesktopAppShell>
    );

  return (
    <WorkspaceProvider value={workspaceContextValue}>
      <div className="h-dvh overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.18),_transparent_22%),linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_46%,_#f8fbff_100%)] text-slate-900">
        <LoadingOverlay visible={bootstrapping} message="正在加载..." />
        {shell}
      </div>
      {announcement && !announcementDismissed && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4">
          <div className="relative max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl">
            <button
              onClick={() => setAnnouncementDismissed(true)}
              className="absolute right-4 top-4 rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            >
              <X size={20} />
            </button>
            {announcement.title && (
              <h2 className="pr-8 text-lg font-bold text-slate-900">{announcement.title}</h2>
            )}
            <div
              className="mt-4 text-sm text-slate-700 leading-relaxed"
              dangerouslySetInnerHTML={{ __html: announcement.content }}
            />
            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setAnnouncementDismissed(true)}
                className="rounded-2xl bg-[#2563eb] px-5 py-2 text-sm font-medium text-white transition hover:bg-[#1d4ed8]"
              >
                我知道了
              </button>
            </div>
          </div>
        </div>
      )}
      <PaymentCheckoutDialog
        checkout={activeCheckout}
        onClose={async () => {
          const orderNo = activeCheckout?.orderNo;
          setActiveCheckout(null);
          if (orderNo) {
            try {
              await syncMyOrder(orderNo);
              const orders = await getMyOrders();
              setMyOrders(orders);
              const currentOrder = orders.find((o) => o.order_no === orderNo);
              if (currentOrder && currentOrder.status === 'paid') {
                await refreshOrders();
                navigate('/account');
                toast.success('支付成功，积分已到账。');
              }
            } catch {
              void 0;
            }
          }
        }}
        onSuccess={(message) => {
          setActiveCheckout(null);
          navigate('/account');
          void refreshOrders();
          toast.success(message);
        }}
      />
    </WorkspaceProvider>
  );
}

function needsImportGuidance(story: Story | null | undefined): boolean {
  if (!story || story.source_type !== 'import') return false;
  if (story.import_context_completed) return false;
  const creativeBrief = story.story_bible?.creative_brief;
  const hasSummary = Boolean(
    creativeBrief?.one_line_premise ||
    creativeBrief?.project_positioning ||
    creativeBrief?.main_conflict,
  );
  return !hasSummary || !story.story_bible?.import_guidance;
}

function PublicSite({
  platform,
  onLogin,
  onRegister,
  onPricing,
}: {
  platform: PublicPlatformSettings;
  onLogin: () => void;
  onRegister: () => void;
  onPricing: () => void;
}) {
  return <PublicLanding platform={platform} onLogin={onLogin} onRegister={onRegister} onPricing={onPricing} />;
}

export default App;
