import { useEffect, useMemo, useState } from 'react';
import QRCode from 'qrcode';
import {
  Brush,
  CreditCard,
  Gauge,
  Home,
  Library,
  LogOut,
  MessageSquareQuote,
  ScrollText,
  Settings2,
  ShieldCheck,
  UserCircle2,
  X,
} from 'lucide-react';
import PublicLanding from './components/PublicLanding';
import StoryLibraryPage from './components/StoryLibraryPage';
import ImportGuidancePage from './components/ImportGuidancePage';
import OnboardingPage from './components/OnboardingPage';
import WorkspaceLayout from './components/WorkspaceLayout';
import VideoWorkspaceLayout from './components/VideoWorkspaceLayout';
import TemplateManagePage from './components/TemplateManagePage';
import TemplateBindingPanel from './components/TemplateBindingPanel';
import AdminTemplateReview from './components/AdminTemplateReview';
import {
  AdminAnnouncementPage,
  AdminAuditLogsPage,
  AdminOrdersPage,
  AdminPlanManagementPage,
  AdminPlatformSettingsPage,
  AdminUserManagementPage,
} from './components/admin/AdminPages';
import {
  adminGrantUserQuota,
  adminUpdateUserSubscription,
  cancelMyOrder,
  clearAuthToken,
  clearApiKeySettings,
  confirmMyOrderMock,
  createStory,
  getApiKeySettings,
  getAdminOrders,
  getAdminPlanFeatures,
  getAdminPlans,
  getAdminQuotaRules,
  getAdminUserEntitlements,
  getMyEntitlements,
  getMyOrders,
  getPublicAnnouncement,
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
  changePassword as changePasswordApi,
  sendResetEmailCode,
  resetPassword as resetPasswordApi,
  saveApiKeySettings,
  saveAdminPlanFeatures,
  saveAdminQuotaRules,
  setAuthToken,
  subscribePlan,
  syncMyOrder,
  updateStory,
  deleteStory,
  type BillingCheckout,
  type AdminFeatureItem,
  type AdminOrderItem,
  type AdminPlan,
  type AdminQuotaRule,
  type AuthUser,
  type Chapter,
  type EntitlementResponse,
  type MySubscriptionResponse,
  type PlatformAnnouncement,
  type PublicPlatformSettings,
  type PublicPlan,
  type Story,
  type UsageResponse,
} from './api';

type RouteKey =
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
  | 'audit-logs'
  | 'announcement';

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
  { key: 'orders', label: '订单订阅', icon: ScrollText },
  { key: 'audit-logs', label: '操作审计', icon: MessageSquareQuote },
  { key: 'announcement', label: '公告管理', icon: MessageSquareQuote },
  { key: 'template-review', label: '模板审核', icon: Library },
];

ADMIN_NAV[0].label = '套餐管理';
ADMIN_NAV[1].label = '平台配置';
ADMIN_NAV[2].label = '用户管理';
ADMIN_NAV[3].label = '订单中心';
ADMIN_NAV[4].label = '操作审计';
ADMIN_NAV[5].label = '公告管理';
ADMIN_NAV[6].label = '模板审核';

function App() {
  const [session, setSession] = useState<AuthUser | null>(null);
  const [route, setRoute] = useState<RouteKey>('landing');
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
  const [adminPlans, setAdminPlans] = useState<AdminPlan[]>([]);
  const [adminPlanId, setAdminPlanId] = useState<number | null>(null);
  const [adminFeatures, setAdminFeatures] = useState<AdminFeatureItem[]>([]);
  const [adminRules, setAdminRules] = useState<AdminQuotaRule[]>([]);
  const [adminOrders, setAdminOrders] = useState<AdminOrderItem[]>([]);
  const [entitlementLookupUserId, setEntitlementLookupUserId] = useState('1');
  const [entitlementPreview, setEntitlementPreview] = useState<any>(null);
  const [grantFeatureKey, setGrantFeatureKey] = useState('manga.image.monthly_limit');
  const [grantAmount, setGrantAmount] = useState('10');
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [globalSuccess, setGlobalSuccess] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<PlatformAnnouncement | null>(null);
  const [announcementDismissed, setAnnouncementDismissed] = useState(false);
  // const [workspaceMode, setWorkspaceMode] = useState<'manga' | 'video'>('manga'); // 视频工作流暂时屏蔽
  void adminPlans;
  void adminOrders;
  void entitlementPreview;
  void setEntitlementLookupUserId;
  void setGrantFeatureKey;
  void setGrantAmount;

  const activeChapter = useMemo(
    () => chapters.find((chapter) => chapter.id === activeChapterId) ?? null,
    [chapters, activeChapterId],
  );
  const isWorkspaceRoute = route === 'workspace';

  useEffect(() => {
    void bootstrapSession();
    void refreshPlans();
    void refreshPlatformSettings();
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
    if (session.role === 'admin') {
      void refreshAdminData();
    }
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
        if (currentOrder.status !== 'pending') {
          await Promise.all([refreshSubscriptionData(), refreshUsage(), refreshAdminDataIfNeeded()]);
          if (!cancelled) {
            setActiveCheckout(null);
            setRoute('account');
            setGlobalError(null);
            setGlobalSuccess(`支付成功，${syncResult.subscription.plan.name} 已生效。`);
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
      setGlobalError(error.message || '加载作品失败');
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
      setGlobalError(error.message || '进入工作台失败');
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

  async function createNewStory() {
    try {
      const next = await createStory(`新故事 ${stories.length + 1}`, '从这里开始你的下一段创作旅程');
      setStories((prev) => [next, ...prev]);
      setOnboardingStory(next);
      setRoute('onboarding');
    } catch (error: any) {
      setGlobalError(error.message || '新建作品失败');
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
    setGlobalError(null);
    return next;
  }

  async function updateStoryDraft(storyId: number, payload: { title?: string; description?: string }) {
    const updated = await updateStory(storyId, payload);
    setStories((prev) => prev.map((story) => (story.id === updated.id ? updated : story)));
    setActiveStory((prev) => (prev?.id === updated.id ? updated : prev));
    setGlobalError(null);
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
    setGlobalError(null);
  }

  async function doLogin(email: string, password: string, verificationCode?: string) {
    try {
      const result = await login({ email, password, verification_code: verificationCode });
      setAuthToken(result.token);
      setSession(result.user);
      setRoute('stories');
      setGlobalError(null);
      void fetchAnnouncement();
    } catch (error: any) {
      clearAuthToken();
      setSession(null);
      setGlobalError(error.message || '登录失败');
    }
  }

  async function doRegister(name: string, email: string, password: string, verificationCode?: string) {
    try {
      const result = await register({ name, email, password, verification_code: verificationCode });
      setAuthToken(result.token);
      setSession(result.user);
      setRoute('stories');
      setGlobalError(null);
      void fetchAnnouncement();
    } catch (error: any) {
      clearAuthToken();
      setSession(null);
      setGlobalError(error.message || '注册失败');
    }
  }

  async function doSendAuthCode(email: string, purpose: 'register' | 'login') {
    try {
      const result = await sendEmailVerificationCode({ email, purpose });
      const minutes = Math.max(1, Math.round((result.expires_in_seconds || 600) / 60));
      setGlobalError(null);
      setGlobalSuccess(`验证码已发送，请在 ${minutes} 分钟内完成${purpose === 'register' ? '注册' : '登录'}。`);
    } catch (error: any) {
      setGlobalSuccess(null);
      setGlobalError(error.message || '验证码发送失败');
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
    setGlobalSuccess(`验证码已发送至 ${email}，请在 ${minutes} 分钟内完成重置。`);
    return result;
  }

  async function doResetPassword(email: string, verificationCode: string) {
    const result = await resetPasswordApi(email, verificationCode);
    setGlobalSuccess(result.message || `新密码已发送至 ${email}，请查收邮件。`);
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
    setSubscribingPlanId(planId);
    try {
      const result = await subscribePlan(planId, billingCycle);
      await Promise.all([refreshSubscriptionData(), refreshUsage(), refreshAdminDataIfNeeded()]);
      setGlobalError(null);
      setGlobalSuccess(null);
      if (result.status === 'pending') {
        setActiveCheckout({ ...result.checkout, orderNo: result.order.order_no });
        setRoute('account');
      } else {
        setActiveCheckout(null);
        setRoute('account');
        setGlobalSuccess(`支付成功，${result.subscription.plan.name} 已生效。`);
      }
    } catch (error: any) {
      setGlobalError(error.message || '订阅套餐失败');
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
      await Promise.all([refreshSubscriptionData(), refreshUsage(), refreshAdminDataIfNeeded()]);
      setActiveCheckout((prev) => (prev?.orderNo === orderNo ? null : prev));
      setGlobalError(null);
      setGlobalSuccess('支付成功，套餐已生效。');
      setRoute('account');
    } catch (error: any) {
      setGlobalError(error.message || '确认支付失败');
    } finally {
      setActioningOrderNo(null);
    }
  }

  async function cancelPendingOrder(orderNo: string) {
    setActioningOrderNo(orderNo);
    try {
      await cancelMyOrder(orderNo);
      await Promise.all([refreshSubscriptionData(), refreshAdminDataIfNeeded()]);
      setActiveCheckout((prev) => (prev?.orderNo === orderNo ? null : prev));
      setGlobalError(null);
      setGlobalSuccess(null);
    } catch (error: any) {
      setGlobalError(error.message || '取消订单失败');
    } finally {
      setActioningOrderNo(null);
    }
  }

  async function refreshAdminDataIfNeeded() {
    if (session?.role === 'admin') {
      await refreshAdminData();
    }
  }

  async function refreshAdminData() {
    try {
      const data = await getAdminPlans();
      setAdminPlans(data);
      const firstPlan = data[0];
      if (firstPlan) {
        setAdminPlanId(firstPlan.id);
        const [features, rules, orders] = await Promise.all([
          getAdminPlanFeatures(firstPlan.id),
          getAdminQuotaRules(firstPlan.id),
          getAdminOrders(),
        ]);
        setAdminFeatures(features);
        setAdminRules(rules);
        setAdminOrders(orders);
      }
    } catch (error: any) {
      setGlobalError(error.message || '加载管理员配置失败');
    }
  }

  async function switchAdminPlan(planId: number) {
    setAdminPlanId(planId);
    const [features, rules] = await Promise.all([getAdminPlanFeatures(planId), getAdminQuotaRules(planId)]);
    setAdminFeatures(features);
    setAdminRules(rules);
  }

  async function saveAdminFeatures() {
    if (!adminPlanId) return;
    await saveAdminPlanFeatures(adminPlanId, adminFeatures);
    await refreshAdminData();
  }

  async function saveAdminRules() {
    if (!adminPlanId) return;
    await saveAdminQuotaRules(adminPlanId, adminRules);
    await refreshAdminData();
  }

  async function lookupEntitlement() {
    const userId = Number(entitlementLookupUserId);
    if (!Number.isFinite(userId) || userId < 1) return;
    try {
      const data = await getAdminUserEntitlements(userId);
      setEntitlementPreview(data);
    } catch (error: any) {
      setGlobalError(error.message || '查询用户权益失败');
      setEntitlementPreview(null);
    }
  }

  async function applyAdminPlanToUser() {
    const userId = Number(entitlementLookupUserId);
    if (!Number.isFinite(userId) || userId < 1 || !adminPlanId) return;
    try {
      await adminUpdateUserSubscription(userId, adminPlanId);
      await Promise.all([lookupEntitlement(), refreshAdminData()]);
      setGlobalError(null);
    } catch (error: any) {
      setGlobalError(error.message || '更新用户套餐失败');
    }
  }

  async function grantQuotaToUser() {
    const userId = Number(entitlementLookupUserId);
    const amount = Number(grantAmount);
    if (!Number.isFinite(userId) || userId < 1 || !grantFeatureKey.trim() || !Number.isFinite(amount) || amount <= 0) return;
    try {
      await adminGrantUserQuota(userId, grantFeatureKey.trim(), amount);
      await lookupEntitlement();
      setGlobalError(null);
    } catch (error: any) {
      setGlobalError(error.message || '补发额度失败');
    }
  }

  void switchAdminPlan;
  void saveAdminFeatures;
  void saveAdminRules;
  void applyAdminPlanToUser;
  void grantQuotaToUser;

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
          error={globalError}
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
        error={globalError}
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
          error={globalError}
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
      <header className="sticky top-0 z-20 border-b border-[#d7e3f4] bg-[rgba(248,251,255,0.82)] backdrop-blur-xl">
        <div className="flex h-14 items-center justify-between px-5 lg:px-8">
          <button
            type="button"
            onClick={() => setRoute('stories')}
            className="flex items-center gap-3 text-left transition hover:opacity-90"
          >
            <img
              src="/brand-mark.svg"
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
          {globalError && (

            <div className="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {globalError}
            </div>
          )}
          {globalSuccess && (
            <div className="mb-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {globalSuccess}
            </div>
          )}

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
              onChapterChange={(chapter) => setActiveChapterId(chapter.id)}
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
            <AdminPlanManagementPage onError={(message) => setGlobalError(message)} />
          )}
          {route === 'quota-rules' && session.role === 'admin' && (
            <AdminPlatformSettingsPage
              onError={(message) => setGlobalError(message)}
              onSaved={() => {
                void refreshPlatformSettings();
              }}
            />
          )}
          {route === 'entitlements' && session.role === 'admin' && (
            <AdminUserManagementPage onError={(message) => setGlobalError(message)} />
          )}
          {route === 'orders' && session.role === 'admin' && <AdminOrdersPage onError={(message) => setGlobalError(message)} />}
          {route === 'audit-logs' && session.role === 'admin' && (
            <AdminAuditLogsPage onError={(message: string) => setGlobalError(message)} />
          )}
          {route === 'announcement' && session.role === 'admin' && (
            <AdminAnnouncementPage onError={(message) => setGlobalError(message)} />
          )}
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
        onClose={() => setActiveCheckout(null)}
        onSuccess={(message) => {
          setActiveCheckout(null);
          setRoute('account');
          setGlobalError(null);
          setGlobalSuccess(message);
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

function AuthLayout({
  brandName,
  brandSlogan,
  title,
  subtitle,
  children,
  onBack,
}: {
  brandName: string;
  brandSlogan: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
  onBack: () => void;
}) {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.18),_transparent_24%),linear-gradient(180deg,_#eef4ff_0%,_#f5f9ff_45%,_#f8fbff_100%)]">
      <div className="mx-auto max-w-md px-4 py-16">
        <button
          onClick={onBack}
          className="mb-6 inline-flex items-center rounded-full border border-[#d7e3f4] bg-white/88 px-4 py-2 text-sm text-slate-600 shadow-[0_10px_24px_rgba(59,130,246,0.08)] transition hover:bg-white hover:text-[#2563eb]"
        >
          返回首页
        </button>
        <div className="rounded-[28px] border border-[#d7e3f4] bg-white/96 p-7 shadow-[0_24px_60px_rgba(59,130,246,0.12)] backdrop-blur">
          <img src="/brand-mark.svg" alt={`${brandName} logo`} className="mb-5 h-11 w-11 rounded-2xl shadow-[0_12px_28px_rgba(59,130,246,0.14)]" />
          <div className="mb-3">
            <div className="text-[17px] font-semibold tracking-tight text-slate-950">{brandName}</div>
            <div className="mt-1 text-xs text-slate-500">{brandSlogan}</div>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{title}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  );
}

function LoginPage({
  title,
  subtitle,
  onBack,
  onLogin,
  onSendCode,
  requireEmailCode,
  codeExpireMinutes,
  toRegister,
  toForgotPassword,
  error,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
  onLogin: (email: string, password: string, verificationCode?: string) => Promise<void>;
  onSendCode: (email: string, purpose: 'register' | 'login') => Promise<void>;
  requireEmailCode: boolean;
  codeExpireMinutes: number;
  toRegister: () => void;
  toForgotPassword: () => void;
  error: string | null;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const brandName = title || DEFAULT_SITE_NAME;
  const brandSlogan = subtitle || DEFAULT_SITE_SLOGAN;

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setTimeout(() => setCodeCooldown((prev) => Math.max(0, prev - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [codeCooldown]);

  return (
    <AuthLayout
      brandName={brandName}
      brandSlogan={brandSlogan}
      title="登录"
      subtitle={`登录后进入 ${brandName}，按角色展示可用菜单。`}
      onBack={onBack}
    >
      <div className="space-y-3">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="邮箱"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="密码"
          type="password"
        />
        {requireEmailCode ? (
          <div className="flex gap-2">
            <input
              value={verificationCode}
              onChange={(e) => setVerificationCode(e.target.value)}
              className="min-w-0 flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
              placeholder={`邮箱验证码（${codeExpireMinutes}分钟内有效）`}
            />
            <button
              onClick={() =>
                void (async () => {
                  setSendingCode(true);
                  try {
                    await onSendCode(email, 'login');
                    setCodeCooldown(60);
                  } finally {
                    setSendingCode(false);
                  }
                })()
              }
              className="shrink-0 rounded-2xl border border-[#bfdbfe] bg-white px-4 py-3 text-sm font-medium text-[#2563eb] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={sendingCode || codeCooldown > 0}
            >
              {sendingCode ? '发送中...' : codeCooldown > 0 ? `${codeCooldown}s 后重发` : '发送验证码'}
            </button>
          </div>
        ) : null}
        <button
          onClick={() => void onLogin(email, password, verificationCode)}
          className="w-full rounded-2xl bg-[#2563eb] py-3 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]"
        >
          登录
        </button>
        {error && <div className="text-xs text-rose-600">{error}</div>}
      </div>
      <div className="mt-5 flex items-center justify-between">
        <button onClick={toForgotPassword} className="text-xs font-medium text-slate-500 transition hover:text-[#2563eb]">忘记密码？</button>
        <button onClick={toRegister} className="text-xs font-medium text-slate-600 transition hover:text-[#2563eb]">没有账号？去注册</button>
      </div>
    </AuthLayout>
  );
}

function ForgotPasswordPage({
  title,
  subtitle,
  onBack,
  onSendCode,
  onResetPassword,
  error,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
  onSendCode: (email: string) => Promise<{ ok: boolean; expires_in_seconds: number }>;
  onResetPassword: (email: string, verificationCode: string) => Promise<void>;
  error: string | null;
}) {
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [resetting, setResetting] = useState(false);
  const brandName = title || DEFAULT_SITE_NAME;
  const brandSlogan = subtitle || DEFAULT_SITE_SLOGAN;

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setTimeout(() => setCodeCooldown((prev) => Math.max(0, prev - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [codeCooldown]);

  return (
    <AuthLayout
      brandName={brandName}
      brandSlogan={brandSlogan}
      title="找回密码"
      subtitle={`验证邮箱后，新密码将发送到您的邮箱。`}
      onBack={onBack}
    >
      <div className="space-y-3">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="邮箱"
        />
        <div className="flex gap-2">
          <input
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value)}
            className="min-w-0 flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
            placeholder="邮箱验证码"
          />
          <button
            onClick={() =>
              void (async () => {
                setSendingCode(true);
                try {
                  await onSendCode(email);
                  setCodeCooldown(60);
                } finally {
                  setSendingCode(false);
                }
              })()
            }
            className="shrink-0 rounded-2xl border border-[#bfdbfe] bg-white px-4 py-3 text-sm font-medium text-[#2563eb] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={sendingCode || codeCooldown > 0 || !email}
          >
            {sendingCode ? '发送中...' : codeCooldown > 0 ? `${codeCooldown}s 后重发` : '发送验证码'}
          </button>
        </div>
        <button
          onClick={() =>
            void (async () => {
              setResetting(true);
              try {
                await onResetPassword(email, verificationCode);
              } finally {
                setResetting(false);
              }
            })()
          }
          disabled={resetting || !email || !verificationCode}
          className="w-full rounded-2xl bg-[#2563eb] py-3 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {resetting ? '处理中...' : '重置密码'}
        </button>
        {error && <div className="text-xs text-rose-600">{error}</div>}
      </div>
    </AuthLayout>
  );
}

function RegisterPage({
  title,
  subtitle,
  onBack,
  onRegister,
  onSendCode,
  requireEmailCode,
  codeExpireMinutes,
  toLogin,
  error,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
  onRegister: (name: string, email: string, password: string, verificationCode?: string) => Promise<void>;
  onSendCode: (email: string, purpose: 'register' | 'login') => Promise<void>;
  requireEmailCode: boolean;
  codeExpireMinutes: number;
  toLogin: () => void;
  error: string | null;
}) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const brandName = title || DEFAULT_SITE_NAME;
  const brandSlogan = subtitle || DEFAULT_SITE_SLOGAN;

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setTimeout(() => setCodeCooldown((prev) => Math.max(0, prev - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [codeCooldown]);

  return (
    <AuthLayout
      brandName={brandName}
      brandSlogan={brandSlogan}
      title="注册"
      subtitle={`创建账号后即可开始 ${brandName} 的小说与漫画创作。`}
      onBack={onBack}
    >
      <div className="space-y-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="昵称"
        />
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="邮箱"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="设置密码"
          type="password"
        />
        {requireEmailCode ? (
          <div className="flex gap-2">
            <input
              value={verificationCode}
              onChange={(e) => setVerificationCode(e.target.value)}
              className="min-w-0 flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
              placeholder={`邮箱验证码（${codeExpireMinutes}分钟内有效）`}
            />
            <button
              onClick={() =>
                void (async () => {
                  setSendingCode(true);
                  try {
                    await onSendCode(email, 'register');
                    setCodeCooldown(60);
                  } finally {
                    setSendingCode(false);
                  }
                })()
              }
              className="shrink-0 rounded-2xl border border-[#bfdbfe] bg-white px-4 py-3 text-sm font-medium text-[#2563eb] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={sendingCode || codeCooldown > 0}
            >
              {sendingCode ? '发送中...' : codeCooldown > 0 ? `${codeCooldown}s 后重发` : '发送验证码'}
            </button>
          </div>
        ) : null}
        <button
          onClick={() => void onRegister(name, email, password, verificationCode)}
          className="w-full rounded-2xl bg-[#2563eb] py-3 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]"
        >
          注册并进入
        </button>
        {error && <div className="text-xs text-rose-600">{error}</div>}
      </div>
      <button onClick={toLogin} className="mt-5 text-xs font-medium text-slate-600 transition hover:text-[#2563eb]">已有账号？去登录</button>
    </AuthLayout>
  );
}

function PricingPublicPage({
  onBack,
  plans,
  onRegister,
}: {
  onBack: () => void;
  plans: PublicPlan[];
  onRegister: () => void;
}) {
  return (
    <div className="min-h-screen bg-[#f7f8f5] px-4 py-10">
      <div className="mx-auto max-w-6xl">
        <button onClick={onBack} className="mb-6 text-sm text-slate-600 hover:text-slate-900">返回首页</button>
        <UserPricingPage plans={plans} onPrimary={onRegister} />
      </div>
    </div>
  );
}

function PricingPage({
  plans,
  onPrimary,
  subscription,
  onSubscribe,
  subscribingPlanId,
}: {
  plans: PublicPlan[];
  onPrimary?: () => void;
  subscription?: MySubscriptionResponse | null;
  onSubscribe?: (planId: number, billingCycle: 'monthly' | 'yearly') => void;
  subscribingPlanId?: number | null;
}) {
  const fallback = [
    {
      id: 0,
      name: 'Free',
      monthly_price: 0,
      description: '适合体验',
      features: {
        'framework.generate.monthly_limit': 5,
        'chapter.expand.monthly_limit': 20,
        'scene.generate.monthly_limit': 15,
        'manga.image.monthly_limit': 80,
        'manga.regenerate.monthly_limit': 20,
        'ai.text.advanced_calls.monthly_limit': 20,
        'manga.max_image_count_per_chapter': 6,
        'manga.allow_color_mode': false,
      },
    },
    {
      id: 1,
      name: 'Pro',
      monthly_price: 59,
      description: '适合稳定创作',
      features: {
        'framework.generate.monthly_limit': 50,
        'chapter.expand.monthly_limit': 200,
        'scene.generate.monthly_limit': 120,
        'manga.image.monthly_limit': 800,
        'manga.regenerate.monthly_limit': 300,
        'ai.text.advanced_calls.monthly_limit': 180,
        'manga.max_image_count_per_chapter': 12,
        'manga.allow_color_mode': true,
      },
    },
    {
      id: 2,
      name: 'Premium',
      monthly_price: 199,
      description: '适合高频创作',
      features: {
        'framework.generate.monthly_limit': 200,
        'chapter.expand.monthly_limit': 1000,
        'scene.generate.monthly_limit': 500,
        'manga.image.monthly_limit': 4000,
        'manga.regenerate.monthly_limit': 1500,
        'ai.text.advanced_calls.monthly_limit': 600,
        'manga.max_image_count_per_chapter': 20,
        'manga.allow_color_mode': true,
      },
    },
  ];
  const data = plans.length > 0 ? plans : (fallback as any[]);

  return (
    <div>
      <h2 className="text-xl font-semibold">套餐订阅</h2>
      <p className="mt-1 text-sm text-slate-600">套餐能力、小说框架额度、漫画生成额度都由后台套餐配置中心统一驱动。</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {data.map((plan: any) => {
          const isCurrent = subscription?.subscription.plan.id === plan.id;
          const featureEntries = getPlanFeatureEntries(plan.features);
          return (
            <div key={plan.id ?? plan.name} className="flex h-full flex-col rounded-md border border-[#d9dfd7] bg-white p-4">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">{plan.name}</div>
                {isCurrent && <span className="rounded-md bg-[#f6ede2] px-2 py-1 text-xs text-[#8b5a21]">当前套餐</span>}
              </div>
              <div className="mt-2 text-2xl font-semibold">
                ¥{formatMoney(plan.monthly_price)}
                <span className="text-sm font-normal text-slate-500">/月</span>
              </div>
              <div className="mt-1 text-xs text-slate-500">{plan.description || ''}</div>
              <div className="mt-3 space-y-2">
                {featureEntries.map(({ key, value }) => (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-3 rounded-md border border-[#edf1ea] bg-[#f8faf7] px-3 py-2 text-xs"
                    title={featureDescription(key)}
                  >
                    <span className="text-slate-600">{featureLabel(key)}</span>
                    <span className="shrink-0 font-medium text-[#1f5f58]">{formatFeatureValue(key, value)}</span>
                  </div>
                ))}
              </div>
              {onSubscribe ? (
                <button
                  onClick={() => onSubscribe(plan.id, 'monthly')}
                  disabled={isCurrent || subscribingPlanId === plan.id}
                  className="mt-4 w-full rounded-md bg-[#1f5f58] py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCurrent ? '已生效' : subscribingPlanId === plan.id ? '处理中...' : '立即订阅'}
                </button>
              ) : null}
              {!onSubscribe && onPrimary ? (
                <button onClick={onPrimary} className="mt-4 w-full rounded-md bg-[#1f5f58] py-2 text-sm text-white">开始使用</button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/*
function StoriesPage({
  stories,
  loading,
  onRefresh,
  onCreate,
  onCreateDraft,
  onImportComplete,
  onUpdateStory,
  onDeleteStory,
  onOpen,
  loadingWorkspace,
}: {
  stories: Story[];
  loading: boolean;
  onRefresh: () => Promise<void>;
  onCreate: () => Promise<void>;
  onCreateDraft: (title: string, description: string) => Promise<Story>;
  onImportComplete: (storyId: number) => Promise<void>;
  onUpdateStory: (storyId: number, payload: { title?: string; description?: string }) => Promise<Story>;
  onDeleteStory: (story: Story) => Promise<void>;
  onOpen: (story: Story) => Promise<void>;
  loadingWorkspace: boolean;
}) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftDescription, setDraftDescription] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [exportingStoryId, setExportingStoryId] = useState<number | null>(null);

  const resetCreateForm = () => {
    setDraftTitle('');
    setDraftDescription('');
    setShowCreateForm(false);
  };

  const startEdit = (story: Story) => {
    setEditingId(story.id);
    setEditTitle(story.title);
    setEditDescription(story.description || '');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditTitle('');
    setEditDescription('');
  };

  const handleCreateDraft = async () => {
    const title = draftTitle.trim() || `新故事 ${stories.length + 1}`;
    const description = draftDescription.trim();
    setSavingId(-1);
    try {
      await onCreateDraft(title, description);
      resetCreateForm();
    } finally {
      setSavingId(null);
    }
  };

  const handleSaveEdit = async () => {
    if (editingId === null) return;
    setSavingId(editingId);
    try {
      await onUpdateStory(editingId, {
        title: editTitle.trim() || '未命名故事',
        description: editDescription.trim(),
      });
      cancelEdit();
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async (story: Story) => {
    const confirmed = window.confirm(`确定删除《${story.title}》吗？作品下的章节、对话和漫画资源也会一起删除。`);
    if (!confirmed) return;
    setDeletingId(story.id);
    try {
      await onDeleteStory(story);
      if (editingId === story.id) cancelEdit();
    } finally {
      setDeletingId(null);
    }
  };

  const handleExport = async (story: Story) => {
    setExportingStoryId(story.id);
    try {
      const chapters = await listChapters(story.id);
      await exportStoryAsZip({ story, chapters });
    } finally {
      setExportingStoryId(null);
    }
  };

  const handleImportDone = async (storyId: number) => {
    setShowImportDialog(false);
    await onImportComplete(storyId);
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">作品首页</h2>
          <p className="text-sm text-slate-600">管理你的小说项目并进入创作工作台。</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => void onRefresh()} className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm">刷新</button>
          <button
            onClick={() => {
              setShowCreateForm((prev) => !prev);
              if (showCreateForm) {
                resetCreateForm();
              }
            }}
            className="inline-flex items-center gap-1 rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white"
          >
            <Plus size={14} />
            新建作品
          </button>
        </div>
      </div>
      {showCreateForm && (
        <div className="mb-4 rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-sm font-semibold text-slate-800">创建作品</div>
          <div className="mt-3 grid gap-3">
            <input
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              placeholder="输入作品名称"
              className="rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58]"
            />
            <textarea
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              rows={3}
              placeholder="输入作品简介，可留空"
              className="rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58] resize-y"
            />
            <div className="flex flex-wrap justify-end gap-2">
              <button
                onClick={() => void onCreate()}
                disabled={savingId !== null}
                className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                快速创建并进入
              </button>
              <button
                onClick={resetCreateForm}
                disabled={savingId !== null}
                className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                取消
              </button>
              <button
                onClick={() => void handleCreateDraft()}
                disabled={savingId !== null}
                className="rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {savingId === -1 ? '创建中...' : '保存作品'}
              </button>
            </div>
          </div>
        </div>
      )}
      {loading ? (
        <div className="rounded-md border border-[#d9dfd7] bg-white p-5 text-sm text-slate-600">加载中...</div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {stories.map((story) => {
            const isEditing = editingId === story.id;
            const isSaving = savingId === story.id;
            const isDeleting = deletingId === story.id;
            return (
              <div
                key={story.id}
                className="rounded-md border border-[#d9dfd7] bg-white p-4 transition-colors hover:border-[#9fb3ad]"
              >
                {isEditing ? (
                  <div className="space-y-3">
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="w-full rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58]"
                    />
                    <textarea
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={3}
                      className="w-full rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58] resize-y"
                      placeholder="输入作品简介，可留空"
                    />
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs text-slate-500">创建于 {new Date(story.created_at).toLocaleDateString('zh-CN')}</div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={cancelEdit}
                          disabled={isSaving}
                          className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-white px-2 py-1.5 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <X size={12} />
                          取消
                        </button>
                        <button
                          onClick={() => void handleSaveEdit()}
                          disabled={isSaving}
                          className="inline-flex items-center gap-1 rounded-md bg-[#1f5f58] px-2 py-1.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Check size={12} />
                          {isSaving ? '保存中...' : '保存'}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <button onClick={() => void onOpen(story)} className="w-full text-left">
                      <div className="text-sm font-semibold">{story.title}</div>
                      <div className="mt-1 min-h-[40px] line-clamp-2 text-xs leading-5 text-slate-600">
                        {story.description || '尚未填写简介，点击进入开始创作。'}
                      </div>
                    </button>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <div className="text-xs text-slate-500">创建于 {new Date(story.created_at).toLocaleDateString('zh-CN')}</div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => startEdit(story)}
                          disabled={savingId !== null || deletingId !== null}
                          className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-white px-2 py-1.5 text-xs text-slate-700 hover:bg-[#f7f8f5] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Pencil size={12} />
                          编辑
                        </button>
                        <button
                          onClick={() => void handleDelete(story)}
                          disabled={savingId !== null || deletingId !== null}
                          className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-xs text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Trash2 size={12} />
                          {isDeleting ? '删除中...' : '删除'}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            );
          })}
          {stories.length === 0 && (
            <div className="rounded-md border border-dashed border-[#c8d0c8] bg-white p-5 text-sm text-slate-500">
              还没有作品，点击右上角新建作品开始创建，或用快速创建直接进入工作台。
            </div>
          )}
        </div>
      )}
      {loadingWorkspace && <div className="mt-4 text-sm text-slate-600">正在进入工作台...</div>}
    </div>
  );
}

*/
function WorkspacePage({
  story,
  chapters,
  currentChapter,
  entitlements,
  workspaceMode,
  onChapterChange,
  onContentUpdated,
}: {
  story: Story | null;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements: EntitlementResponse | null;
  workspaceMode: 'manga' | 'video';
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => Promise<void>;
}) {
  if (!story) {
    return (
      <div className="rounded-md border border-[#d9dfd7] bg-white p-6 text-sm text-slate-600">
        请先在「作品」页面选择一个项目再进入工作台。
      </div>
    );
  }
  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto rounded-md border border-[#d9dfd7] bg-white">
      <div className="flex items-center justify-end border-b border-[#e8edf2] px-4 py-2">
        <TemplateBindingPanel storyId={story.id} />
      </div>
      {workspaceMode === 'manga' ? (
        <WorkspaceLayout
          story={story}
          chapters={chapters}
          currentChapter={currentChapter}
          entitlements={entitlements}
          onChapterChange={onChapterChange}
          onContentUpdated={onContentUpdated}
        />
      ) : (
        <VideoWorkspaceLayout
          story={story}
          chapters={chapters}
          currentChapter={currentChapter}
          onChapterChange={onChapterChange}
          onContentUpdated={onContentUpdated}
        />
      )}
    </div>
  );
}

function PaymentCheckoutDialog({
  checkout,
  onClose,
  onSuccess,
}: {
  checkout: (BillingCheckout & { orderNo: string }) | null;
  onClose: () => void;
  onSuccess: (message: string) => void;
}) {
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [checkingPayment, setCheckingPayment] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function renderQr() {
      if (!checkout?.qr_code_text) {
        setQrDataUrl('');
        return;
      }
      try {
        const url = await QRCode.toDataURL(checkout.qr_code_text, {
          width: 280,
          margin: 1,
          color: {
            dark: '#0f172a',
            light: '#ffffff',
          },
        });
        if (!cancelled) setQrDataUrl(url);
      } catch {
        if (!cancelled) setQrDataUrl('');
      }
    }
    void renderQr();
    return () => {
      cancelled = true;
    };
  }, [checkout]);

  async function confirmAlipayPaid() {
    if (!checkout?.orderNo || checkingPayment) return;
    setCheckingPayment(true);
    try {
      const result = await syncMyOrder(checkout.orderNo);
      if (result.status === 'paid') {
        onSuccess(`支付成功，${result.subscription.plan.name} 已生效。`);
      }
    } finally {
      setCheckingPayment(false);
    }
  }

  if (!checkout) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.48)] px-4">
      <div className="w-full max-w-4xl rounded-[28px] border border-[#d7e3f4] bg-white p-6 shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">支付订单</div>
            <div className="mt-1 text-sm text-slate-500">
              订单号 {checkout.orderNo}，请使用{paymentMethodLabel(checkout.method)}完成支付。
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-[#d7e3f4] bg-white p-2 text-slate-500 transition hover:bg-[#f8fbff] hover:text-slate-900"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <div className="rounded-3xl border border-[#d7e3f4] bg-[#f8fbff] p-5">
            <div className="rounded-3xl bg-white p-4 shadow-[0_10px_24px_rgba(59,130,246,0.08)]">
              {qrDataUrl ? (
                <img src={qrDataUrl} alt="支付二维码" className="mx-auto h-[280px] w-[280px] rounded-2xl" />
              ) : (
                <div className="flex h-[280px] items-center justify-center rounded-2xl bg-[#f8fbff] text-sm text-slate-500">
                  正在生成二维码...
                </div>
              )}
            </div>
            <div className="mt-4 text-center text-sm text-slate-600">
              {checkout.provider === 'alipay' ? '打开支付宝扫一扫完成付款' : '请使用对应支付 App 扫码完成付款'}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-3xl border border-[#d7e3f4] bg-white p-5">
              <div className="text-sm font-semibold text-slate-900">订单信息</div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">套餐</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{checkout.plan_name}</div>
                </div>
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">金额</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{checkout.currency} {formatMoney(checkout.amount)}</div>
                </div>
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">计费周期</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{checkout.billing_cycle === 'yearly' ? '年付' : '月付'}</div>
                </div>
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">失效时间</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{formatDateTime(checkout.expires_at)}</div>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-[#d7e3f4] bg-white p-5">
              <div className="text-sm font-semibold text-slate-900">支付说明</div>
              <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-600">
                {checkout.instructions || '请在二维码失效前完成支付，支付成功后系统会通过官方回调自动更新订单状态。'}
              </div>
              {checkout.payment_url ? (
                <a
                  href={checkout.payment_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-4 inline-flex rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#1e40af]"
                >
                  在新窗口打开支付链接
                </a>
              ) : null}
              {checkout.method === 'alipay_qr' ? (
                <button
                  onClick={() => void confirmAlipayPaid()}
                  disabled={checkingPayment}
                  className="mt-4 ml-3 inline-flex rounded-2xl border border-[#bfdbfe] bg-white px-4 py-2 text-sm font-medium text-[#1d4ed8] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {checkingPayment ? '正在确认支付...' : '我已完成支付'}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountUsagePage({
  usage,
  subscription,
  entitlements,
  orders,
}: {
  usage: UsageResponse | null;
  subscription: MySubscriptionResponse | null;
  entitlements: EntitlementResponse | null;
  orders: AdminOrderItem[];
}) {
  return (
    <div>
      <h2 className="text-xl font-semibold">账户与用量</h2>
      <p className="mt-1 text-sm text-slate-600">查看当前套餐状态、本月核心用量，以及当前订单和权益明细。</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-xs text-slate-500">当前套餐</div>
          <div className="mt-2 text-lg font-semibold">{subscription?.subscription.plan.name || '-'}</div>
          <div className="mt-1 text-sm text-slate-600">状态：{subscription?.subscription.status || '-'}</div>
        </div>
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-xs text-slate-500">月费</div>
          <div className="mt-2 text-lg font-semibold">{subscription ? `¥${formatMoney(subscription.subscription.plan.monthly_price)}` : '-'}</div>
          <div className="mt-1 text-sm text-slate-600">{subscription?.subscription.plan.currency || '-'}</div>
        </div>
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-xs text-slate-500">最近订单</div>
          <div className="mt-2 text-sm font-medium">{subscription?.latest_order?.order_no || '-'}</div>
          <div className="mt-1 text-sm text-slate-600">{subscription?.latest_order?.status || '暂无订单'}</div>
        </div>
      </div>
      <div className="mt-4 overflow-hidden rounded-md border border-[#d9dfd7] bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-[#f2f4ef] text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-semibold">能力键</th>
              <th className="px-3 py-2 font-semibold">总量</th>
              <th className="px-3 py-2 font-semibold">已用</th>
              <th className="px-3 py-2 font-semibold">剩余</th>
            </tr>
          </thead>
          <tbody>
            {(usage?.items || []).map((item) => (
              <tr key={item.feature_key} className="border-t border-[#eef1ec]">
                <td className="px-3 py-2">{item.feature_key}</td>
                <td className="px-3 py-2">{item.limit}</td>
                <td className="px-3 py-2">{item.used}</td>
                <td className="px-3 py-2">{item.remaining}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-[1.3fr_1fr]">
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-sm font-semibold">当前权益</div>
          <pre className="mt-3 overflow-x-auto rounded-md bg-[#f5f7f3] p-3 text-xs text-slate-700">
            {JSON.stringify(entitlements?.entitlements || {}, null, 2)}
          </pre>
        </div>
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-sm font-semibold">我的订单</div>
          <div className="mt-3 space-y-2">
            {orders.slice(0, 5).map((order) => (
              <div key={order.order_no} className="rounded-md border border-[#eef1ec] px-3 py-2 text-sm">
                <div className="font-medium">{order.order_no}</div>
                <div className="mt-1 text-slate-600">¥{formatMoney(order.amount)} · {order.status}</div>
              </div>
            ))}
            {orders.length === 0 && <div className="text-sm text-slate-500">暂无订单记录</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

function UserPricingPage({
  plans,
  onPrimary,
  subscription,
  onSubscribe,
  subscribingPlanId,
}: {
  plans: PublicPlan[];
  onPrimary?: () => void;
  subscription?: MySubscriptionResponse | null;
  onSubscribe?: (planId: number, billingCycle: 'monthly' | 'yearly') => void;
  subscribingPlanId?: number | null;
}) {
  const fallback = [
    { id: 0, name: 'Free', monthly_price: 0, description: '适合体验和轻量创作', features: { 'manga.image.monthly_limit': 80, 'framework.generate.monthly_limit': 5, 'scene.generate.monthly_limit': 15, 'ai.text.advanced_calls.monthly_limit': 20, 'manga.max_image_count_per_chapter': 6, 'manga.allow_color_mode': false } },
    { id: 1, name: 'Pro', monthly_price: 59, description: '适合稳定更新的个人创作者', features: { 'manga.image.monthly_limit': 800, 'framework.generate.monthly_limit': 50, 'scene.generate.monthly_limit': 120, 'ai.text.advanced_calls.monthly_limit': 180, 'manga.max_image_count_per_chapter': 12, 'manga.allow_color_mode': true } },
    { id: 2, name: 'Premium', monthly_price: 199, description: '适合高频产出的团队和工作室', features: { 'manga.image.monthly_limit': 4000, 'framework.generate.monthly_limit': 200, 'scene.generate.monthly_limit': 500, 'ai.text.advanced_calls.monthly_limit': 600, 'manga.max_image_count_per_chapter': 20, 'manga.allow_color_mode': true } },
  ];
  const data = plans.length > 0 ? plans : (fallback as any[]);

  return (
    <div>
      <h2 className="text-xl font-semibold">套餐订阅</h2>
      <p className="mt-1 text-sm text-slate-600">所有小说创作、分镜生成和漫画出图能力都由平台套餐统一控制。你可以在这里直观看到不同套餐的额度差异和适用场景。</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {data.map((plan: any) => {
          const isCurrent = subscription?.subscription.plan.id === plan.id;
          const highlights = [
            ['framework.generate.monthly_limit', plan.features?.['framework.generate.monthly_limit'] ?? 0],
            ['scene.generate.monthly_limit', plan.features?.['scene.generate.monthly_limit'] ?? 0],
            ['manga.image.monthly_limit', plan.features?.['manga.image.monthly_limit'] ?? 0],
          ] as const;

          return (
            <div key={plan.id ?? plan.name} className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
              <div className="flex items-center justify-between">
                <div className="text-base font-semibold text-slate-900">{plan.name}</div>
                {isCurrent ? <span className="rounded-full bg-[#eff6ff] px-3 py-1 text-xs text-[#1d4ed8]">当前套餐</span> : null}
              </div>
              <div className="mt-3 text-3xl font-semibold text-slate-900">
                ¥{formatMoney(plan.monthly_price)}
                <span className="ml-1 text-sm font-normal text-slate-500">/月</span>
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-500">{plan.description || '暂无套餐说明'}</div>
              <div className="mt-4 space-y-2 rounded-2xl bg-[#f8fbff] p-3">
                {highlights.map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between text-sm">
                    <span className="text-slate-600">{featureLabel(key)}</span>
                    <span className="font-medium text-slate-900">{formatFeatureValue(key, value)}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 rounded-2xl border border-dashed border-[#d7e3f4] px-3 py-3 text-xs leading-6 text-slate-500">
                {plan.features?.['manga.allow_color_mode'] ? '支持彩漫模式' : '支持黑白漫画模式'}
                ，单章节最多生成 {plan.features?.['manga.max_image_count_per_chapter'] ?? 0} 张图片。
              </div>
              {onSubscribe ? (
                <button
                  onClick={() => onSubscribe(plan.id, 'monthly')}
                  disabled={isCurrent || subscribingPlanId === plan.id}
                  className="mt-5 w-full rounded-2xl bg-[#1d4ed8] py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCurrent ? '已生效' : subscribingPlanId === plan.id ? '处理中...' : '立即订阅'}
                </button>
              ) : null}
              {!onSubscribe && onPrimary ? (
                <button onClick={onPrimary} className="mt-5 w-full rounded-2xl bg-[#1d4ed8] py-2.5 text-sm font-medium text-white">开始使用</button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function UserAccountUsagePage({
  session,
  platform,
  usage,
  subscription,
  entitlements,
  orders,
  actioningOrderNo,
  onConfirmMockPayment,
  onCancelOrder,
}: {
  session: AuthUser | null;
  platform: PublicPlatformSettings;
  usage: UsageResponse | null;
  subscription: MySubscriptionResponse | null;
  entitlements: EntitlementResponse | null;
  orders: AdminOrderItem[];
  actioningOrderNo: string | null;
  onConfirmMockPayment: (orderNo: string) => void;
  onCancelOrder: (orderNo: string) => void;
}) {
  const [apiSettings, setApiSettings] = useState(() => getApiKeySettings());
  const entitlementEntries = Object.entries(entitlements?.entitlements || {});
  const pendingOrder = orders.find((order) => order.status === 'pending') || null;
  const canOverrideApiKey = Boolean(session?.can_override_api_key);
  const canOverrideApiUrl = Boolean(session?.can_override_api_url);

  return (
    <div>
      <h2 className="text-xl font-semibold">账户与用量</h2>
      <p className="mt-1 text-sm text-slate-600">查看当前套餐状态、本月核心能力剩余额度，以及当前套餐已经为你开放的能力项，方便判断是否需要升级套餐。</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-xs font-medium text-slate-500">当前套餐</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900">{subscription?.subscription.plan.name || '-'}</div>
          <div className="mt-2 text-sm text-slate-600">状态：{statusLabel(subscription?.subscription.status)}</div>
          <div className="mt-2 text-sm text-slate-600">
            到期时间：{subscription?.subscription.expires_at ? formatDateTime(subscription.subscription.expires_at) : '长期有效'}
          </div>
          <div className="mt-1 text-sm text-slate-600">
            当前账期：{formatSubscriptionPeriod(subscription?.subscription.current_period_start, subscription?.subscription.current_period_end)}
          </div>
        </div>
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-xs font-medium text-slate-500">当前月费</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900">{subscription ? `¥${formatMoney(subscription.subscription.plan.monthly_price)}` : '-'}</div>
          <div className="mt-2 text-sm text-slate-600">{subscription?.subscription.plan.currency || '-'}</div>
        </div>
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-xs font-medium text-slate-500">最近订单</div>
          <div className="mt-2 text-sm font-semibold text-slate-900">{subscription?.latest_order?.order_no || '-'}</div>
          <div className="mt-2 text-sm text-slate-600">{statusLabel(subscription?.latest_order?.status) || '暂无订单'}</div>
          {pendingOrder ? (
            <div className="mt-3 rounded-2xl bg-[#f8fbff] px-3 py-3 text-xs leading-6 text-slate-600">
              <div>待支付金额：{pendingOrder.currency} {formatMoney(pendingOrder.amount)}</div>
              <div>支付方式：{paymentMethodLabel(pendingOrder.payment_method)}</div>
              <div>失效时间：{formatDateTime(pendingOrder.expired_at)}</div>
              {pendingOrder.extra?.alipay_qr_code ? <div className="break-all">支付宝付款码：{pendingOrder.extra.alipay_qr_code}</div> : null}
            </div>
          ) : null}
        </div>
      </div>

      {pendingOrder ? (
        <div className="mt-4 rounded-3xl border border-[#bfdbfe] bg-[#eff6ff] p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold text-slate-900">有一笔待支付订单</div>
              <div className="mt-1 text-sm text-slate-600">
                订单号 {pendingOrder.order_no}，金额 {pendingOrder.currency} {formatMoney(pendingOrder.amount)}，方式 {paymentMethodLabel(pendingOrder.payment_method)}。
              </div>
              {pendingOrder.extra?.alipay_payment_url ? (
                <a className="mt-2 inline-block text-sm text-[#1d4ed8] underline" href={pendingOrder.extra.alipay_payment_url} target="_blank" rel="noreferrer">
                  打开支付宝收银二维码
                </a>
              ) : null}
              <div className="mt-1 text-xs text-slate-500">当前先支持模拟支付确认，后续接真实网关时这里可以继续扩展为二维码跳转或回调状态轮询。</div>
            </div>
            <div className="flex flex-wrap gap-3">
              {pendingOrder.payment_method === 'mock_qr' ? (
                <button
                  onClick={() => onConfirmMockPayment(pendingOrder.order_no)}
                  disabled={actioningOrderNo === pendingOrder.order_no}
                  className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {actioningOrderNo === pendingOrder.order_no ? '处理中...' : '确认模拟支付'}
                </button>
              ) : null}
              <button
                onClick={() => onCancelOrder(pendingOrder.order_no)}
                disabled={actioningOrderNo === pendingOrder.order_no}
                className="rounded-2xl border border-[#bfdbfe] bg-white px-4 py-2 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                取消订单
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {canOverrideApiKey || canOverrideApiUrl ? (
        <div className="mt-4 rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-sm font-semibold text-slate-900">自定义模型对接</div>
          <div className="mt-1 text-xs text-slate-500">
            这里的配置只对当前浏览器生效。没有权限的字段即使填写，服务端也会继续使用管理员配置。
          </div>
          <div className="mt-2 text-xs text-[#1d4ed8]">
            启用自定义中转地址后，对应请求将不再扣减平台套餐配额。
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">文本模型</div>
              <div className="mb-3 rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-xs text-slate-600">
                <div>平台地址：{platform.api?.deepseek_base_url || '-'}</div>
                <div className="mt-1">平台模型：{platform.api?.deepseek_model || '-'}</div>
              </div>
              <div className="space-y-3">
                <input
                  value={apiSettings.deepseekBaseUrl}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, deepseekBaseUrl: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.deepseek_base_url || '自定义 DeepSeek Base URL'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.deepseekModel}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, deepseekModel: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.deepseek_model || '自定义 DeepSeek 模型名'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.deepseekApiKey}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, deepseekApiKey: e.target.value }))}
                  disabled={!canOverrideApiKey}
                  type="password"
                  placeholder="自定义 DeepSeek API Key"
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
              </div>
            </div>
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">图片模型</div>
              <div className="mb-3 rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-xs text-slate-600">
                <div>平台地址：{platform.api?.image_base_url || '-'}</div>
                <div className="mt-1">平台模型：{platform.api?.image_model || '-'}</div>
              </div>
              <div className="space-y-3">
                <input
                  value={apiSettings.imageBaseUrl}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, imageBaseUrl: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.image_base_url || '自定义图片服务 Base URL'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.imageModel}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, imageModel: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.image_model || '自定义图片模型名'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.imageApiKey}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, imageApiKey: e.target.value }))}
                  disabled={!canOverrideApiKey}
                  type="password"
                  placeholder="自定义图片 API Key"
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
              </div>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              onClick={() => saveApiKeySettings(apiSettings)}
              className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white"
            >
              保存本地对接配置
            </button>
            <button
              onClick={() => {
                clearApiKeySettings();
                setApiSettings(getApiKeySettings());
              }}
              className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700"
            >
              清空本地配置
            </button>
          </div>
        </div>
      ) : null}

      <div className="mt-4 rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
        <div className="text-sm font-semibold text-slate-900">密码修改</div>
        <PasswordChangeForm onChangePassword={changePasswordApi} />
      </div>

      <div className="mt-4 overflow-hidden rounded-3xl border border-[#d7e3f4] bg-white/95 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
        <div className="border-b border-[#e5edf8] px-4 py-3">
          <div className="text-sm font-semibold text-slate-900">本月核心额度</div>
          <div className="mt-1 text-xs text-slate-500">这里展示会直接影响创作效率的主要可消耗能力。</div>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="bg-[#f8fbff] text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">能力项</th>
              <th className="px-4 py-3 font-medium">总量</th>
              <th className="px-4 py-3 font-medium">已用</th>
              <th className="px-4 py-3 font-medium">剩余</th>
            </tr>
          </thead>
          <tbody>
            {(usage?.items || []).map((item) => {
              const percent = item.limit > 0 ? Math.max(0, Math.min(100, Math.round((item.remaining / item.limit) * 100))) : 0;
              return (
                <tr key={item.feature_key} className="border-t border-[#e5edf8] align-top">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{featureLabel(item.feature_key)}</div>
                    <div className="mt-1 text-xs text-slate-500">{featureDescription(item.feature_key)}</div>
                  </td>
                  <td className="px-4 py-3">{item.limit}</td>
                  <td className="px-4 py-3">{item.used}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{item.remaining}</div>
                    <div className="mt-2 h-2.5 rounded-full bg-[#e5edf8]">
                      <div className="h-2.5 rounded-full bg-[#3b82f6]" style={{ width: `${percent}%` }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-sm font-semibold text-slate-900">当前权益说明</div>
          <div className="mt-1 text-xs text-slate-500">这里展示你的套餐已经开通的能力项和对应额度，不再显示难理解的内部系统键名。</div>
          <div className="mt-4 space-y-3">
            {entitlementEntries.map(([key, value]) => (
              <div key={key} className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-medium text-slate-900">{featureLabel(key)}</div>
                    <div className="mt-1 text-xs text-slate-500">{featureDescription(key)}</div>
                  </div>
                  <div className="text-sm font-semibold text-slate-900">{formatFeatureValue(key, value)}</div>
                </div>
              </div>
            ))}
            {entitlementEntries.length === 0 ? <div className="text-sm text-slate-500">暂无权益信息</div> : null}
          </div>
        </div>

        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-sm font-semibold text-slate-900">我的订单</div>
          <div className="mt-1 text-xs text-slate-500">最近 5 条订单或后台调整记录。</div>
          <div className="mt-4 space-y-3">
            {orders.slice(0, 5).map((order) => (
              <div key={order.order_no} className="rounded-2xl border border-[#e5edf8] px-4 py-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="font-medium text-slate-900">{order.order_no}</div>
                  <span className="rounded-full bg-[#eff6ff] px-2 py-1 text-xs text-[#1d4ed8]">
                    {orderSourceLabel(order.source)}
                  </span>
                </div>
                <div className="mt-2 grid gap-1 text-slate-600">
                  <div>金额：{order.currency} {formatMoney(order.amount)}</div>
                  <div>状态：{statusLabel(order.status)}</div>
                  <div>方式：{paymentMethodLabel(order.payment_method)}</div>
                  <div>套餐：{order.plan_name || `#${order.plan_id}`}</div>
                  <div>时间：{formatDateTime(order.paid_at || order.created_at)}</div>
                  {order.operator?.name ? <div>操作人：{order.operator.name}</div> : null}
                  {order.note ? <div>说明：{order.note}</div> : null}
                  {order.extra?.feature_name || order.extra?.feature_key ? (
                    <div>
                      补发内容：{order.extra?.feature_name || featureLabel(String(order.extra?.feature_key || ''))}
                      {order.extra?.amount ? ` +${order.extra.amount}` : ''}
                    </div>
                  ) : null}
                </div>
                {order.status === 'pending' ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {order.payment_method === 'mock_qr' ? (
                      <button
                        onClick={() => onConfirmMockPayment(order.order_no)}
                        disabled={actioningOrderNo === order.order_no}
                        className="rounded-xl bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actioningOrderNo === order.order_no ? '处理中...' : '确认支付'}
                      </button>
                    ) : null}
                    <button
                      onClick={() => onCancelOrder(order.order_no)}
                      disabled={actioningOrderNo === order.order_no}
                      className="rounded-xl border border-[#d7e3f4] px-3 py-1.5 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      取消
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
            {orders.length === 0 ? <div className="text-sm text-slate-500">暂无订单记录</div> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function PasswordChangeForm({
  onChangePassword,
}: {
  onChangePassword: (oldPassword: string, newPassword: string) => Promise<void>;
}) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [localSuccess, setLocalSuccess] = useState<string | null>(null);

  async function handleSubmit() {
    setLocalError(null);
    setLocalSuccess(null);
    if (!oldPassword || !newPassword || !confirmPassword) {
      setLocalError('请填写所有密码字段');
      return;
    }
    if (newPassword.length < 6) {
      setLocalError('新密码长度不能少于 6 位');
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError('两次输入的新密码不一致');
      return;
    }
    if (newPassword === oldPassword) {
      setLocalError('新密码不能与旧密码相同');
      return;
    }
    setSaving(true);
    try {
      await onChangePassword(oldPassword, newPassword);
      setLocalSuccess('密码修改成功');
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      setLocalError(err.message || '密码修改失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-3">
      <input
        value={oldPassword}
        onChange={(e) => setOldPassword(e.target.value)}
        type="password"
        placeholder="当前密码"
        className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
      />
      <input
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        type="password"
        placeholder="新密码（不少于 6 位）"
        className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
      />
      <input
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        type="password"
        placeholder="确认新密码"
        className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
      />
      <button
        onClick={() => void handleSubmit()}
        disabled={saving}
        className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {saving ? '修改中...' : '修改密码'}
      </button>
      {localError && <div className="text-xs text-rose-600">{localError}</div>}
      {localSuccess && <div className="text-xs text-emerald-600">{localSuccess}</div>}
    </div>
  );
}

function PlanConfigPage({
  plans,
  selectedPlanId,
  features,
  onSelectPlan,
  onFeaturesChange,
  onSave,
}: {
  plans: AdminPlan[];
  selectedPlanId: number | null;
  features: AdminFeatureItem[];
  onSelectPlan: (planId: number) => void;
  onFeaturesChange: (items: AdminFeatureItem[]) => void;
  onSave: () => void;
}) {
  return (
    <div>
      <h2 className="text-xl font-semibold">套餐配置</h2>
      <div className="mt-3 flex flex-wrap gap-2">
        {plans.map((plan) => (
          <button
            key={plan.id}
            onClick={() => onSelectPlan(plan.id)}
            className={`rounded-md border px-3 py-1.5 text-sm ${
              selectedPlanId === plan.id ? 'border-[#1f5f58] bg-[#e7efea]' : 'border-[#d9dfd7] bg-white'
            }`}
          >
            {plan.name}
          </button>
        ))}
      </div>
      <div className="mt-4 overflow-hidden rounded-md border border-[#d9dfd7] bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-[#f2f4ef] text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-semibold">权益键</th>
              <th className="px-3 py-2 font-semibold">值</th>
            </tr>
          </thead>
          <tbody>
            {features.map((item, idx) => (
              <tr key={item.feature_key} className="border-t border-[#eef1ec]">
                <td className="px-3 py-2">{item.feature_key}</td>
                <td className="px-3 py-2">
                  <input
                    value={String(item.value ?? '')}
                    onChange={(e) => {
                      const next = [...features];
                      next[idx] = { ...item, value: e.target.value };
                      onFeaturesChange(next);
                    }}
                    className="w-full rounded-md border border-[#d9dfd7] px-2 py-1 text-sm"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={onSave} className="mt-3 rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white">保存权益</button>
    </div>
  );
}

function QuotaRulesPage({
  rules,
  onRulesChange,
  onSave,
}: {
  rules: AdminQuotaRule[];
  onRulesChange: (items: AdminQuotaRule[]) => void;
  onSave: () => void;
}) {
  return (
    <div>
      <h2 className="text-xl font-semibold">配额规则</h2>
      <div className="mt-4 overflow-hidden rounded-md border border-[#d9dfd7] bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-[#f2f4ef] text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-semibold">权益键</th>
              <th className="px-3 py-2 font-semibold">重置周期</th>
              <th className="px-3 py-2 font-semibold">扣减模式</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((item, idx) => (
              <tr key={item.feature_key} className="border-t border-[#eef1ec]">
                <td className="px-3 py-2">{item.feature_key}</td>
                <td className="px-3 py-2">
                  <input
                    value={item.reset_period}
                    onChange={(e) => {
                      const next = [...rules];
                      next[idx] = { ...item, reset_period: e.target.value };
                      onRulesChange(next);
                    }}
                    className="w-full rounded-md border border-[#d9dfd7] px-2 py-1 text-sm"
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    value={item.deduct_mode}
                    onChange={(e) => {
                      const next = [...rules];
                      next[idx] = { ...item, deduct_mode: e.target.value };
                      onRulesChange(next);
                    }}
                    className="w-full rounded-md border border-[#d9dfd7] px-2 py-1 text-sm"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={onSave} className="mt-3 rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white">保存规则</button>
    </div>
  );
}

function EntitlementPage({
  lookupId,
  onLookupIdChange,
  onLookup,
  preview,
  plans,
  selectedPlanId,
  onApplyPlan,
  grantFeatureKey,
  onGrantFeatureKeyChange,
  grantAmount,
  onGrantAmountChange,
  onGrantQuota,
}: {
  lookupId: string;
  onLookupIdChange: (value: string) => void;
  onLookup: () => void;
  preview: any;
  plans: AdminPlan[];
  selectedPlanId: number | null;
  onApplyPlan: () => void;
  grantFeatureKey: string;
  onGrantFeatureKeyChange: (value: string) => void;
  grantAmount: string;
  onGrantAmountChange: (value: string) => void;
  onGrantQuota: () => void;
}) {
  return (
    <div>
      <h2 className="text-xl font-semibold">用户权益</h2>
      <div className="mt-3 flex items-center gap-2">
        <input
          value={lookupId}
          onChange={(e) => onLookupIdChange(e.target.value)}
          className="w-40 rounded-md border border-[#d9dfd7] px-3 py-2 text-sm"
          placeholder="用户ID"
        />
        <button onClick={onLookup} className="rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white">查询</button>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-sm font-semibold">切换用户套餐</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {plans.map((plan) => (
              <span
                key={plan.id}
                className={`rounded-md border px-3 py-1.5 text-sm ${
                  selectedPlanId === plan.id ? 'border-[#1f5f58] bg-[#e7efea]' : 'border-[#d9dfd7] bg-[#f8faf7]'
                }`}
              >
                {plan.name}
              </span>
            ))}
          </div>
          <button onClick={onApplyPlan} className="mt-3 rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white">
            套用当前选中套餐
          </button>
        </div>
        <div className="rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-sm font-semibold">补发额度</div>
          <div className="mt-3 grid gap-2 md:grid-cols-[1fr_120px_auto]">
            <input
              value={grantFeatureKey}
              onChange={(e) => onGrantFeatureKeyChange(e.target.value)}
              className="rounded-md border border-[#d9dfd7] px-3 py-2 text-sm"
              placeholder="feature_key"
            />
            <input
              value={grantAmount}
              onChange={(e) => onGrantAmountChange(e.target.value)}
              className="rounded-md border border-[#d9dfd7] px-3 py-2 text-sm"
              placeholder="amount"
            />
            <button onClick={onGrantQuota} className="rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white">
              发放
            </button>
          </div>
          <div className="mt-2 text-xs text-slate-500">补发逻辑为冲减本月已用量，用户会立即获得更多剩余额度。</div>
        </div>
      </div>
      {preview && (
        <pre className="mt-3 overflow-x-auto rounded-md border border-[#d9dfd7] bg-white p-3 text-xs">
          {JSON.stringify(preview, null, 2)}
        </pre>
      )}
    </div>
  );
}

function OrdersPage({ orders }: { orders: AdminOrderItem[] }) {
  return (
    <div>
      <h2 className="text-xl font-semibold">订单订阅</h2>
      <div className="mt-4 overflow-hidden rounded-md border border-[#d9dfd7] bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-[#f2f4ef] text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-semibold">订单号</th>
              <th className="px-3 py-2 font-semibold">用户ID</th>
              <th className="px-3 py-2 font-semibold">金额</th>
              <th className="px-3 py-2 font-semibold">状态</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.order_no} className="border-t border-[#eef1ec]">
                <td className="px-3 py-2">{order.order_no}</td>
                <td className="px-3 py-2">{order.user_id}</td>
                <td className="px-3 py-2">¥{formatMoney(order.amount)}</td>
                <td className="px-3 py-2">{order.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const USER_FEATURE_META: Record<string, { label: string; description: string; unit: string; kind?: 'boolean' | 'number' }> = {
  'framework.generate.monthly_limit': {
    label: '小说框架生成',
    description: '用于生成世界观、角色设定和故事大纲。',
    unit: '次/月',
  },
  'chapter.expand.monthly_limit': {
    label: '章节扩写',
    description: '将章节规划一键扩写为完整正文。',
    unit: '次/月',
  },
  'scene.generate.monthly_limit': {
    label: '漫画分镜生成',
    description: '将小说正文转换成分镜脚本。',
    unit: '次/月',
  },
  'manga.image.monthly_limit': {
    label: '漫画图片生成',
    description: '每月可生成的漫画图片总张数。',
    unit: '张/月',
  },
  'manga.regenerate.monthly_limit': {
    label: '漫画重绘',
    description: '对单张漫画图重新生成和修正。',
    unit: '次/月',
  },
  'ai.text.advanced_calls.monthly_limit': {
    label: '高级文本 AI',
    description: '用于框架调整、继续扩展、文本改写、正文调整、质量评估与单项重生成。',
    unit: '次/月',
  },
  'manga.max_image_count_per_chapter': {
    label: '单章节最大出图',
    description: '单个章节允许生成的最大图片数量。',
    unit: '张/章',
  },
  'manga.allow_color_mode': {
    label: '彩漫模式',
    description: '是否支持彩色漫画生成。',
    unit: '',
    kind: 'boolean',
  },
  'video.generate.seconds.monthly_limit': {
    label: '视频生成时长',
    description: '每月可生成的视频总时长。',
    unit: '秒/月',
  },
  'screenplay.generate.monthly_limit': {
    label: '剧本生成',
    description: '每月可生成影视剧本的次数。',
    unit: '次/月',
  },
  'shot.generate.monthly_limit': {
    label: '分镜任务生成',
    description: '每月可生成分镜任务卡的次数。',
    unit: '次/月',
  },
};

function featureLabel(key: string): string {
  return USER_FEATURE_META[key]?.label || key;
}

function featureDescription(key: string): string {
  return USER_FEATURE_META[key]?.description || '';
}

function featureUnit(key: string): string {
  return USER_FEATURE_META[key]?.unit || '';
}

function formatFeatureValue(key: string, value: any): string {
  const meta = USER_FEATURE_META[key];
  if (meta?.kind === 'boolean') {
    return value ? '已开启' : '未开启';
  }
  const unit = featureUnit(key);
  return unit ? `${value}${unit}` : String(value ?? '-');
}

function getPlanFeatureEntries(features: Record<string, any> | null | undefined) {
  const source = features || {};
  const knownKeys = Object.keys(USER_FEATURE_META).filter((key) => key in source);
  const extraKeys = Object.keys(source).filter((key) => !(key in USER_FEATURE_META)).sort();
  return [...knownKeys, ...extraKeys].map((key) => ({ key, value: source[key] }));
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN');
}

function formatSubscriptionPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return '-';
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return `${start || '-'} ~ ${end || '-'}`;
  }
  return `${startDate.toLocaleDateString('zh-CN')} ~ ${endDate.toLocaleDateString('zh-CN')}`;
}

function formatMoney(value: number | string | null | undefined): string {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount)) return '-';
  return amount.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

function paymentMethodLabel(method: string | null | undefined): string {
  if (!method) return '-';
  if (method === 'mock_qr') return '模拟支付';
  if (method === 'wechat_qr') return '微信扫码';
  if (method === 'alipay_qr') return '支付宝扫码';
  if (method === 'manual_adjustment') return '后台人工调整';
  return method;
}

function orderSourceLabel(source: string | null | undefined): string {
  if (!source) return '-';
  if (source === 'admin_adjustment') return '后台套餐调整';
  if (source === 'quota_grant') return '额度补发';
  if (source === 'mock_checkout') return '模拟支付下单';
  return source;
}

const SUBSCRIPTION_STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  pending: '待支付',
  paid: '已支付',
  admin_adjusted: '后台调整',
  inactive: '未生效',
  cancelled: '已取消',
  expired: '已过期',
};

function statusLabel(status: string | null | undefined): string {
  if (!status) return '-';
  return SUBSCRIPTION_STATUS_LABELS[status] || status;
}

void PlanConfigPage;
void QuotaRulesPage;
void EntitlementPage;
void OrdersPage;
void PricingPage;
void AccountUsagePage;

export default App;
