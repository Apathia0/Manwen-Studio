import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  BookOpen,
  Brush,
  CreditCard,
  Home,
  Library,
  LogOut,
  MessageSquareQuote,
  Cpu,
  Sparkles,
  Settings2,
  ShieldCheck,
  UserCircle2,
  X,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { toast } from './lib/toast';
import { confirm } from './lib/confirm';
import {
  AI_MODEL_SELECTION_REQUIRED_EVENT,
  type AiModelSelectionRequiredDetail,
} from './lib/errors';
import { LoadingOverlay } from './components/ui/LoadingOverlay';
import { RouteLoadingFallback } from './components/ui/RouteLoadingFallback';
import PublicLanding from './components/PublicLanding';
import StoryLibraryPage from './components/StoryLibraryPage';
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

type RouteKey =
  | 'install'
  | 'landing'
  | 'login'
  | 'register'
  | 'pricing'
  | 'stories'
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
  | 'points-ai-admin';

type NavItem = {
  key: RouteKey;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
};

const DEFAULT_SITE_NAME = 'StoryCanvas';
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台';
const DEFAULT_ICON_URL = '/brand-mark.svg';
const LS_WORKSPACE_MODE = 'storycanvas.workspaceMode';
const LS_NAV_COLLAPSED = 'storycanvas.navCollapsed';

const USER_NAV: NavItem[] = [
  { key: 'stories', label: '作品', icon: Home },
  { key: 'creation-studio', label: '创作台', icon: Sparkles },
  { key: 'model-catalog', label: '模型广场', icon: Cpu },
  { key: 'workspace', label: '作品工作台', icon: Brush },
  { key: 'deconstruction-library', label: '拆书库', icon: BookOpen },
  { key: 'account', label: '账户与积分', icon: UserCircle2 },
  { key: 'pricing', label: '积分套餐', icon: CreditCard },
];

const ADMIN_NAV: NavItem[] = [
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

function App() {
  const [session, setSession] = useState<AuthUser | null>(null);
  const [route, setRoute] = useState<RouteKey>('landing');
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
  const [deconWorkId, setDeconWorkId] = useState<number>(0);
  const [modelConfigRequest, setModelConfigRequest] = useState<{
    modality: AiModelSelectionRequiredDetail['modality'];
    requestId: number;
  } | null>(null);

  const activeChapter = useMemo(
    () => chapters.find((chapter) => chapter.id === activeChapterId) ?? null,
    [chapters, activeChapterId],
  );

  const handleModelConfigRequestHandled = useCallback((requestId: number) => {
    setModelConfigRequest((current) => current?.requestId === requestId ? null : current);
  }, []);

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
  }, []);

  useEffect(() => {
    localStorage.setItem(LS_WORKSPACE_MODE, workspaceMode);
  }, [workspaceMode]);

  useEffect(() => {
    localStorage.setItem(LS_NAV_COLLAPSED, String(navCollapsed));
  }, [navCollapsed]);
  const isWorkspaceRoute = route === 'workspace';

  useEffect(() => {
    void bootstrapApp();
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
  }, [session]);

  async function bootstrapApp() {
    try {
      const status = await getInstallStatus();
      if (!status.installed || status.requires_restart) {
        clearAuthToken();
        setSession(null);
        setInstallRequired(true);
        setRoute('install');
        return;
      }
      setInstallRequired(false);
      void refreshPlatformSettings();
      await bootstrapSession();
    } catch {
      // getInstallStatus 失败：探测后端健康状态，给用户明确的故障归属提示。
      clearAuthToken();
      setSession(null);
      setRoute('landing');
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
      setRoute('stories');
      void fetchAnnouncement();
    } catch {
      clearAuthToken();
      setSession(null);
      setRoute('landing');
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
        setRoute('import-guidance');
        return;
      }
      if (!detail.onboarding_completed) {
        setOnboardingStory(detail);
        setRoute('onboarding');
        return;
      }
      setActiveStory(detail);
      setChapters(chapterList);
      setActiveChapterId(chapterList[0]?.id ?? null);
      setRoute('workspace');
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
      setRoute('onboarding');
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
      setRoute('stories');
    }
    toast.success('作品已删除');
  }

  async function doLogin(email: string, password: string, verificationCode?: string) {
    try {
      const result = await login({ email, password, verification_code: verificationCode });
      setAuthToken(result.token);
      setSession(result.user);
      setRoute('stories');
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
      setRoute('stories');
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
      setRoute('landing');
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
    setRoute('login');
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
      setRoute('account');
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
          onBack={() => setRoute('landing')}
          onLogin={doLogin}
          onSendCode={doSendAuthCode}
          requireEmailCode={Boolean(platform.auth?.require_email_code_for_login)}
          codeExpireMinutes={platform.auth?.email_code_expire_minutes || 10}
          toRegister={() => setRoute('register')}
          toForgotPassword={() => setRoute('forgot-password')}
          error={null}
        />
    );
  }
  if (!session && route === 'forgot-password') {
    return (
      <ForgotPasswordPage
        title={platform.site_name}
        subtitle={platform.site_slogan}
        onBack={() => setRoute('login')}
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
          onBack={() => setRoute('landing')}
          onRegister={doRegister}
          onSendCode={doSendAuthCode}
          requireEmailCode={Boolean(platform.auth?.require_email_code_for_register)}
          codeExpireMinutes={platform.auth?.email_code_expire_minutes || 10}
          toLogin={() => setRoute('login')}
          error={null}
        />
    );
  }
    if (!session && route === 'pricing') {
      return <PricingPublicPage onBack={() => setRoute('landing')} onRegister={() => setRoute('register')} />;
    }
  if (!session) {
    return (
      <PublicSite
        platform={platform}
        onLogin={() => setRoute('login')}
        onRegister={() => setRoute('register')}
        onPricing={() => setRoute('pricing')}
      />
    );
  }

  return (
    <div className="h-screen overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.18),_transparent_22%),linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_46%,_#f8fbff_100%)] text-slate-900">
      <LoadingOverlay visible={bootstrapping} message="正在加载..." />
      <header className="sticky top-0 z-20 border-b border-[#d7e3f4] bg-[rgba(248,251,255,0.82)] backdrop-blur-xl">
        <div className="flex h-14 items-center justify-between px-5 lg:px-8">
          <button
            type="button"
            onClick={() => setRoute('stories')}
            className="flex items-center gap-3 text-left transition hover:opacity-90"
          >
            <img
              src={platform.icon_url || DEFAULT_ICON_URL}
              alt={`${platform.site_name || DEFAULT_SITE_NAME} logo`}
              className="h-9 w-9 rounded-2xl shadow-[0_10px_24px_rgba(59,130,246,0.14)]"
            />
            <div>
              <div className="text-sm font-semibold tracking-wide">{platform.site_name || DEFAULT_SITE_NAME}</div>
              <div className="text-[11px] text-slate-500">{platform.site_slogan || 'AI 小说与漫画创作平台'}</div>
            </div>
          </button>
          <div className="flex items-center gap-3 text-sm">
            <span className="rounded-full border border-[#d7e3f4] bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 shadow-[0_6px_18px_rgba(59,130,246,0.08)]">
              {session.role === 'admin' ? '管理员' : '用户'}
            </span>
            <span>{session.name}</span>
            <button
              onClick={() => void doLogout()}
              className="inline-flex items-center gap-1 rounded-full border border-[#d7e3f4] bg-white/90 px-3 py-1.5 text-xs text-slate-700 shadow-[0_6px_18px_rgba(59,130,246,0.08)] transition hover:bg-[#eef5ff]"
            >
              <LogOut size={14} />
              退出
            </button>
          </div>
        </div>
      </header>

      <div className={`grid h-[calc(100vh-56px)] overflow-hidden grid-cols-[68px_minmax(0,1fr)] ${navCollapsed ? 'lg:grid-cols-[68px_minmax(0,1fr)]' : 'lg:grid-cols-[220px_minmax(0,1fr)]'}`}>
        <aside className={`overflow-y-auto border-r border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(248,251,255,0.94)_0%,_rgba(238,244,255,0.92)_100%)] px-2 py-4 backdrop-blur-xl ${navCollapsed ? '' : 'lg:px-4'}`}>
          <div className={`mb-4 flex items-center justify-center ${navCollapsed ? '' : 'lg:justify-between lg:px-2'}`}>
            {!navCollapsed ? <div className="hidden text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 lg:block">应用菜单</div> : null}
            <button
              type="button"
              onClick={() => setNavCollapsed((value) => !value)}
              className="rounded-lg p-2 text-slate-400 transition hover:bg-white/80 hover:text-slate-700"
              title={navCollapsed ? '展开菜单' : '收起菜单'}
              aria-label={navCollapsed ? '展开菜单' : '收起菜单'}
            >
              {navCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            </button>
          </div>
          <nav className="space-y-1.5">
            {USER_NAV.map((item) => {
              const Icon = item.icon;
              const active = route === item.key;
              return (
                <button
                  key={item.key}
                  onClick={() => {
                    if (item.key === 'deconstruction-library') setDeconWorkId(0);
                    setRoute(item.key);
                  }}
                  title={navCollapsed ? item.label : undefined}
                  aria-label={item.label}
                  className={`flex w-full items-center justify-center rounded-xl px-2 py-2.5 text-left text-sm transition ${navCollapsed ? '' : 'lg:justify-start lg:gap-2 lg:px-3'} ${
                    active
                      ? 'bg-[linear-gradient(180deg,_#fafdff_0%,_#e8f1ff_100%)] text-[#1d4ed8] shadow-[0_10px_24px_rgba(59,130,246,0.14)]'
                      : 'text-slate-700 hover:bg-white/80'
                  }`}
                >
                  <Icon size={16} />
                  <span className={navCollapsed ? 'hidden' : 'hidden lg:inline'}>{item.label}</span>
                </button>
              );
            })}
          </nav>

          {session.role === 'admin' && (
            <>
              <div className={`mb-3 mt-6 border-t border-[#d7e3f4] ${navCollapsed ? '' : 'lg:border-t-0 lg:px-2 lg:text-xs lg:font-semibold lg:uppercase lg:tracking-[0.18em] lg:text-slate-400'}`}>
                {!navCollapsed ? <span className="hidden lg:inline">运营配置</span> : null}
              </div>
              <nav className="space-y-1.5">
                {ADMIN_NAV.map((item) => {
                  const Icon = item.icon;
                  const active = route === item.key;
                  return (
                    <button
                      key={item.key}
                      onClick={() => setRoute(item.key)}
                      title={navCollapsed ? item.label : undefined}
                      aria-label={item.label}
                      className={`flex w-full items-center justify-center rounded-xl px-2 py-2.5 text-left text-sm transition ${navCollapsed ? '' : 'lg:justify-start lg:gap-2 lg:px-3'} ${
                        active
                          ? 'bg-[linear-gradient(180deg,_#fafdff_0%,_#e8f1ff_100%)] text-[#1d4ed8] shadow-[0_10px_24px_rgba(59,130,246,0.14)]'
                          : 'text-slate-700 hover:bg-white/80'
                      }`}
                    >
                      <Icon size={16} />
                      <span className={navCollapsed ? 'hidden' : 'hidden lg:inline'}>{item.label}</span>
                    </button>
                  );
                })}
              </nav>
            </>
          )}
        </aside>

        <main className={`min-h-0 overflow-y-auto bg-transparent ${isWorkspaceRoute ? 'p-0' : 'p-5 lg:p-7'}`}>
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
              loadingWorkspace={loadingWorkspace}
            />
          )}
          {route === 'deconstruction-library' && deconWorkId !== 0 ? (
            <DeconstructionWorkPage
              workId={deconWorkId}
              onBack={() => { setDeconWorkId(0); }}
            />
          ) : route === 'deconstruction-library' ? (
            <DeconstructionLibraryPage
              onNavigate={(r, workId) => {
                if (r === 'deconstruction-work' && workId) {
                  setDeconWorkId(workId);
                } else if (r === 'deconstruction-work' && !workId) {
                  setDeconWorkId(-1);
                } else if (r === 'stories') {
                  setRoute('stories');
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
                setRoute('stories');
              }}
            />
          )}
          {route === 'import-guidance' && importGuidanceStory && (
            <ImportGuidancePage
              story={importGuidanceStory}
              onComplete={handleImportGuidanceComplete}
              onBack={() => {
                setImportGuidanceStory(null);
                setRoute('stories');
              }}
            />
          )}
          {route === 'workspace' && (
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
          </Suspense>
        </main>
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
                setRoute('account');
                toast.success('支付成功，积分已到账。');
              }
            } catch {
              void 0;
            }
          }
        }}
        onSuccess={(message) => {
          setActiveCheckout(null);
          setRoute('account');
          void refreshOrders();
          toast.success(message);
        }}
      />
    </div>
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
