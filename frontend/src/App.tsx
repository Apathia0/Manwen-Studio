import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  Brush,
  CreditCard,
  Gauge,
  Home,
  Library,
  LogOut,
  MessageSquareQuote,
  Settings2,
  ShieldCheck,
  UserCircle2,
  X,
} from 'lucide-react';
import { toast } from './lib/toast';
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
  AdminPlanManagementPage,
  AdminPlatformSettingsPage,
  AdminRevenueDashboardPage,
  AdminSystemUpdatePage,
  AdminSystemPromptsPage,
  AdminUserManagementPage,
} from './components/admin/AdminPages';
import { LoginPage } from './components/LoginPage';
import { ForgotPasswordPage } from './components/ForgotPasswordPage';
import { RegisterPage } from './components/RegisterPage';
import { InstallWizardPage } from './components/InstallWizardPage';
import { PricingPublicPage } from './components/PricingPublicPage';
import { WorkspacePage } from './components/WorkspacePage';
import { PaymentCheckoutDialog } from './components/PaymentCheckoutDialog';
import { UserPricingPage } from './components/UserPricingPage';
import { UserAccountUsagePage } from './components/UserAccountUsagePage';
import {
  cancelMyOrder,
  clearAuthToken,
  confirmMyOrderMock,
  createStory,
  getMyEntitlements,
  getMyOrders,
  getPublicAnnouncement,
  getPaymentConfig,
  getPublicPlatformSettings,
  getMySubscription,
  getMyUsage,
  getPublicPlans,
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
  subscribePlan,
  syncMyOrder,
  updateStory,
  deleteStory,
  getInstallStatus,
  type AdminOrderItem,
  type AuthUser,
  type BillingCheckout,
  type Chapter,
  type EntitlementResponse,
  type MySubscriptionResponse,
  type PaymentMethodOption,
  type PlatformAnnouncement,
  type PublicPlatformSettings,
  type PublicPlan,
  type Story,
  type UsageResponse,
} from './api';

type RouteKey =
  | 'install'
  | 'landing'
  | 'login'
  | 'register'
  | 'pricing'
  | 'stories'
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
  | 'system-prompts';

type NavItem = {
  key: RouteKey;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
};

const DEFAULT_SITE_NAME = 'StoryCanvas';
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台';
const DEFAULT_ICON_URL = '/brand-mark.svg';

const USER_NAV: NavItem[] = [
  { key: 'stories', label: '作品', icon: Home },
  { key: 'workspace', label: '创作工作台', icon: Brush },
  { key: 'account', label: '账户与用量', icon: UserCircle2 },
  { key: 'templates', label: '提示词模板', icon: Library },
  { key: 'pricing', label: '套餐订阅', icon: CreditCard },
];

const ADMIN_NAV: NavItem[] = [
  { key: 'plan-config', label: '套餐配置', icon: Settings2 },
  { key: 'quota-rules', label: '配额规则', icon: Gauge },
  { key: 'entitlements', label: '用户权益', icon: ShieldCheck },
  { key: 'revenue', label: '收入看板', icon: BarChart3 },
  { key: 'audit-logs', label: '操作审计', icon: MessageSquareQuote },
  { key: 'announcement', label: '公告管理', icon: MessageSquareQuote },
  { key: 'template-review', label: '模板审核', icon: Library },
  { key: 'system-prompts', label: '系统提示词', icon: MessageSquareQuote },
  { key: 'system-update', label: '系统更新', icon: Settings2 },
];

ADMIN_NAV[0].label = '套餐管理';
ADMIN_NAV[1].label = '平台配置';
ADMIN_NAV[2].label = '用户管理';
ADMIN_NAV[3].label = '收入与订单';
ADMIN_NAV[4].label = '操作审计';
ADMIN_NAV[5].label = '公告管理';
ADMIN_NAV[6].label = '模板审核';
ADMIN_NAV[7].label = '系统提示词';
ADMIN_NAV[8].label = '系统更新';

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
  const [plans, setPlans] = useState<PublicPlan[]>([]);
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
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [myEntitlements, setMyEntitlements] = useState<EntitlementResponse | null>(null);
  const [mySubscription, setMySubscription] = useState<MySubscriptionResponse | null>(null);
  const [myOrders, setMyOrders] = useState<AdminOrderItem[]>([]);
  const [subscribingPlanId, setSubscribingPlanId] = useState<number | null>(null);
  const [actioningOrderNo, setActioningOrderNo] = useState<string | null>(null);
  const [activeCheckout, setActiveCheckout] = useState<(BillingCheckout & { orderNo: string }) | null>(null);
  const [announcement, setAnnouncement] = useState<PlatformAnnouncement | null>(null);
  const [announcementDismissed, setAnnouncementDismissed] = useState(false);
  const [installRequired, setInstallRequired] = useState(false);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethodOption[]>([]);
  const [channelPicker, setChannelPicker] = useState<{ planId: number; billingCycle: 'monthly' | 'yearly'; options: PaymentMethodOption[] } | null>(null);
  const [channelLoading, setChannelLoading] = useState<string | null>(null);

  const activeChapter = useMemo(
    () => chapters.find((chapter) => chapter.id === activeChapterId) ?? null,
    [chapters, activeChapterId],
  );
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
    void refreshUsage();
    void refreshSubscriptionData();
  }, [session]);

  useEffect(() => {
    const checkoutOrderNo = activeCheckout?.orderNo;
    if (!session || !checkoutOrderNo) return;

    let cancelled = false;

    async function syncCheckoutStatus() {
      const orderNo = checkoutOrderNo!;
      try {
        const syncResult = await syncMyOrder(orderNo);
        if (cancelled) return;
        const orders = await getMyOrders();
        if (cancelled) return;
        setMyOrders(orders);
        const currentOrder = orders.find((order) => order.order_no === orderNo) || syncResult.order;
        if (!currentOrder) {
          return;
        }
        if (currentOrder.status === 'paid') {
          await Promise.all([refreshSubscriptionData(), refreshUsage()]);
          if (!cancelled) {
            setActiveCheckout(null);
            setRoute('account');
            toast.success(`支付成功，${syncResult.subscription.plan.name} 已生效。`);
          }
        }
      } catch {
        // Ignore transient polling failures and keep the dialog open.
      }
    }

    void syncCheckoutStatus();
    const timer = window.setInterval(() => {
      void syncCheckoutStatus();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session, activeCheckout?.orderNo]);

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
      void refreshPlans();
      void refreshPlatformSettings();
      void fetchPaymentConfig();
      await bootstrapSession();
    } catch {
      clearAuthToken();
      setSession(null);
      setRoute('landing');
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

  async function doResetPassword(email: string, verificationCode: string) {
    const result = await resetPasswordApi(email, verificationCode);
    toast.success(result.message || `新密码已发送至 ${email}，请查收邮件。`);
    setRoute('login');
  }

  async function refreshPlans() {
    try {
      const data = await getPublicPlans();
      setPlans(data);
    } catch {
      setPlans([]);
    }
  }

  async function refreshUsage() {
    try {
      const data = await getMyUsage();
      setUsage(data);
    } catch {
      setUsage(null);
    }
  }

  async function refreshSubscriptionData() {
    try {
      const [subscription, entitlements, orders] = await Promise.all([
        getMySubscription(),
        getMyEntitlements(),
        getMyOrders(),
      ]);
      setMySubscription(subscription);
      setMyEntitlements(entitlements);
      setMyOrders(orders);
    } catch {
      setMySubscription(null);
      setMyEntitlements(null);
      setMyOrders([]);
    }
  }

  async function purchasePlan(planId: number, billingCycle: 'monthly' | 'yearly' = 'monthly') {
    if (paymentMethods.length > 1) {
      setChannelPicker({ planId, billingCycle, options: paymentMethods });
      return;
    }
    await doSubscribe(planId, billingCycle, paymentMethods.length === 1 ? paymentMethods[0].key : undefined);
  }

  /** 执行订阅，返回是否成功 */
  async function doSubscribe(planId: number, billingCycle: 'monthly' | 'yearly', paymentMethod?: string): Promise<boolean> {
    setSubscribingPlanId(planId);
    try {
      const result = await subscribePlan(planId, billingCycle, paymentMethod);
      await Promise.all([refreshSubscriptionData(), refreshUsage()]);
      if (result.status === 'pending') {
        setActiveCheckout({ ...result.checkout, orderNo: result.order.order_no });
        setRoute('account');
      } else {
        setActiveCheckout(null);
        setRoute('account');
        toast.success(`支付成功，${result.subscription.plan.name} 已生效。`);
      }
      return true;
    } catch (error: any) {
      toast.error(error.message || '订阅套餐失败');
      return false;
    } finally {
      setSubscribingPlanId(null);
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

  async function fetchPaymentConfig() {
    try {
      const data = await getPaymentConfig();
      if (data.enabled && data.methods) {
        setPaymentMethods(data.methods);
      } else {
        setPaymentMethods([]);
      }
    } catch {
      setPaymentMethods([]);
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
      await Promise.all([refreshSubscriptionData(), refreshUsage()]);
      setActiveCheckout((prev) => (prev?.orderNo === orderNo ? null : prev));
      toast.success('支付成功，套餐已生效。');
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
      await refreshSubscriptionData();
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
    return <PricingPublicPage onBack={() => setRoute('landing')} plans={plans} onRegister={() => setRoute('register')} />;
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
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.18),_transparent_22%),linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_46%,_#f8fbff_100%)] text-slate-900">
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

      <div className="grid min-h-[calc(100vh-56px)] grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="border-r border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(248,251,255,0.94)_0%,_rgba(238,244,255,0.92)_100%)] px-4 py-5 backdrop-blur-xl">
          <div className="mb-4 px-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">应用菜单</div>
          <nav className="space-y-1.5">
            {USER_NAV.map((item) => {
              const Icon = item.icon;
              const active = route === item.key;
              return (
                <button
                  key={item.key}
                  onClick={() => setRoute(item.key)}
                  className={`flex w-full items-center gap-2 rounded-2xl px-3 py-2.5 text-left text-sm transition ${
                    active
                      ? 'bg-[linear-gradient(180deg,_#fafdff_0%,_#e8f1ff_100%)] text-[#1d4ed8] shadow-[0_10px_24px_rgba(59,130,246,0.14)]'
                      : 'text-slate-700 hover:bg-white/80'
                  }`}
                >
                  <Icon size={16} />
                  {item.label}
                </button>
              );
            })}
          </nav>

          {session.role === 'admin' && (
            <>
              <div className="mb-3 mt-6 px-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">运营配置</div>
              <nav className="space-y-1.5">
                {ADMIN_NAV.map((item) => {
                  const Icon = item.icon;
                  const active = route === item.key;
                  return (
                    <button
                      key={item.key}
                      onClick={() => setRoute(item.key)}
                      className={`flex w-full items-center gap-2 rounded-2xl px-3 py-2.5 text-left text-sm transition ${
                        active
                          ? 'bg-[linear-gradient(180deg,_#fafdff_0%,_#e8f1ff_100%)] text-[#1d4ed8] shadow-[0_10px_24px_rgba(59,130,246,0.14)]'
                          : 'text-slate-700 hover:bg-white/80'
                      }`}
                    >
                      <Icon size={16} />
                      {item.label}
                    </button>
                  );
                })}
              </nav>
            </>
          )}
        </aside>

        <main className={`min-h-[calc(100vh-56px)] bg-transparent ${isWorkspaceRoute ? 'p-2 lg:p-3' : 'p-5 lg:p-7'}`}>
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
              entitlements={myEntitlements}
              workspaceMode="manga"
              onChapterChange={handleChapterChange}
              onContentUpdated={refreshWorkspaceData}
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
              usage={usage}
              subscription={mySubscription}
              entitlements={myEntitlements}
              orders={myOrders}
              actioningOrderNo={actioningOrderNo}
              onConfirmMockPayment={confirmPendingOrder}
              onCancelOrder={cancelPendingOrder}
            />
          )}
          {route === 'pricing' && (
            <UserPricingPage
              plans={plans}
              subscription={mySubscription}
              onSubscribe={(planId: number, billingCycle: 'monthly' | 'yearly') => void purchasePlan(planId, billingCycle)}
              subscribingPlanId={subscribingPlanId}
            />
          )}
          {route === 'plan-config' && session.role === 'admin' && (
            <AdminPlanManagementPage onError={(message) => toast.error(message)} />
          )}
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
          setSubscribingPlanId(null);
          if (orderNo) {
            try {
              await syncMyOrder(orderNo);
              const orders = await getMyOrders();
              setMyOrders(orders);
              const currentOrder = orders.find((o) => o.order_no === orderNo);
              if (currentOrder && currentOrder.status === 'paid') {
                await Promise.all([refreshSubscriptionData(), refreshUsage()]);
                setRoute('account');
                toast.success('支付成功，套餐已生效。');
              }
            } catch {
              // 静默处理，不干扰用户操作
            }
          }
        }}
        onSuccess={(message) => {
          setActiveCheckout(null);
          setSubscribingPlanId(null);
          setRoute('account');
          toast.success(message);
        }}
      />

      {/* 支付方式选择弹窗 */}
      {channelPicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(15,23,42,0.48)] px-4">
          <div className="w-full max-w-sm rounded-[28px] border border-[#d7e3f4] bg-white p-6 shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
            <div className="text-base font-semibold text-slate-900">选择支付方式</div>
            <div className="mt-1 text-sm text-slate-500">请选择要使用的支付方式</div>
            <div className="mt-4 space-y-2">
              {channelPicker.options.map((opt) => {
                const loading = channelLoading === opt.key;
                return (
                  <button
                    key={opt.key}
                    disabled={!!channelLoading}
                    onClick={async () => {
                      setChannelLoading(opt.key);
                      const ok = await doSubscribe(channelPicker.planId, channelPicker.billingCycle, opt.key);
                      if (ok) setChannelPicker(null);
                      setChannelLoading(null);
                    }}
                    className="w-full rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-4 py-3 text-left text-sm font-medium text-slate-900 transition hover:border-[#1d4ed8] hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {loading ? `${opt.label} ...` : opt.label}
                  </button>
                );
              })}
            </div>
            <button
              onClick={() => { setChannelPicker(null); setChannelLoading(null); }}
              className="mt-4 w-full rounded-2xl border border-[#d7e3f4] px-4 py-2 text-sm text-slate-500 transition hover:bg-[#f8fbff]"
            >
              取消
            </button>
          </div>
        </div>
      )}
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
