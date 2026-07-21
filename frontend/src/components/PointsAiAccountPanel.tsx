import { type KeyboardEvent, useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2,
  Coins,
  ExternalLink,
  FileImage,
  FlaskConical,
  Gauge,
  KeyRound,
  ListRestart,
  Save,
  Settings2,
  ShieldCheck,
  Trash2,
  Type,
  Video,
} from 'lucide-react';
import {
  type ApiKeySettings,
  type AiCredentialStatus,
  type AiModelItem,
  type AiPreferences,
  type CredentialMode,
  type PointsAccount,
  type PointsLedgerItem,
  type PublicPlatformSettings,
  deleteAiCredential,
  getApiKeySettings,
  getAiCredential,
  getAiModels,
  getAiPreferences,
  getLocalCredentialMode,
  getPointsAccount,
  getPointsLedger,
  saveAiCredential,
  saveApiKeySettings,
  saveAiPreferences,
  setLocalCredentialMode,
  testAiCredential,
} from '../api';
import { toast } from '../lib/toast';
import { Button, Input, Select } from './ui';

type AccountTab = 'overview' | 'credential' | 'models' | 'ledger';
type ModelModality = 'text' | 'image' | 'video';
type PlatformApiSettings = NonNullable<PublicPlatformSettings['api']>;

const ACCOUNT_TABS = [
  { key: 'overview', label: '账户概览', icon: Gauge },
  { key: 'credential', label: 'API 凭据', icon: KeyRound },
  { key: 'models', label: '模型配置', icon: Settings2 },
  { key: 'ledger', label: '积分流水', icon: ListRestart },
] as const;

const MODEL_TABS = [
  {
    key: 'text',
    label: '文本模型',
    icon: Type,
    preferenceKey: 'default_text_model_id',
    description: '用于小说创作、剧本生成与 AI 对话。',
  },
  {
    key: 'image',
    label: '图片模型',
    icon: FileImage,
    preferenceKey: 'default_image_model_id',
    description: '用于封面、角色图与漫画图片生成。',
  },
  {
    key: 'video',
    label: '视频模型',
    icon: Video,
    preferenceKey: 'default_video_model_id',
    description: '用于分镜视频与成片生成。',
  },
] as const;

const UPSTREAM_FIELDS = {
  text: {
    modelKey: 'deepseekModel',
    platformBaseUrlKey: 'deepseek_base_url',
    platformModelKey: 'deepseek_model',
  },
  image: {
    modelKey: 'imageModel',
    platformBaseUrlKey: 'image_base_url',
    platformModelKey: 'image_model',
  },
  video: {
    modelKey: 'videoModel',
    platformBaseUrlKey: 'video_base_url',
    platformModelKey: 'video_model',
  },
} as const satisfies Record<ModelModality, {
  modelKey: keyof ApiKeySettings;
  platformBaseUrlKey: keyof PlatformApiSettings;
  platformModelKey: keyof PlatformApiSettings;
}>;

const UPSTREAM_GUIDE_MODALITIES = [
  { key: 'text', label: '文本' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
] as const;

type UpstreamGuideItem = {
  url: string;
  openUrl: string;
  status: 'available' | 'missing' | 'unsafe';
  services: Array<{ label: string; source: '自定义' | '平台' }>;
};

function normalizeUpstreamUrl(rawUrl: string) {
  const trimmed = rawUrl.trim();
  if (!trimmed) return { status: 'missing' as const, url: '', openUrl: '', groupKey: '__missing__' };

  try {
    const parsed = new URL(trimmed);
    if (
      !['http:', 'https:'].includes(parsed.protocol)
      || parsed.username
      || parsed.password
      || parsed.search
      || parsed.hash
    ) {
      return { status: 'unsafe' as const, url: '', openUrl: '', groupKey: '__unsafe__' };
    }
    const pathname = parsed.pathname.replace(/\/+$/, '');
    const normalizedUrl = `${parsed.protocol}//${parsed.host}${pathname}`;
    const openUrl = pathname.toLowerCase().endsWith('/v1') ? `${parsed.origin}/` : normalizedUrl;
    return {
      status: 'available' as const,
      url: normalizedUrl,
      openUrl,
      groupKey: normalizedUrl,
    };
  } catch {
    return { status: 'unsafe' as const, url: '', openUrl: '', groupKey: '__unsafe__' };
  }
}

function buildUpstreamGuideItems(
  apiSettings: ApiKeySettings,
  platformApi: PlatformApiSettings | undefined,
  canOverrideApiUrl: boolean,
  mode: CredentialMode,
): UpstreamGuideItem[] {
  const grouped = new Map<string, UpstreamGuideItem>();

  for (const modality of UPSTREAM_GUIDE_MODALITIES) {
    const fields = UPSTREAM_FIELDS[modality.key];
    const customUrl = apiSettings.upstreamBaseUrl.trim();
    const platformUrl = String(platformApi?.[fields.platformBaseUrlKey] || '').trim();
    const useCustomUrl = mode === 'user_key' && canOverrideApiUrl && customUrl.length > 0;
    const normalized = normalizeUpstreamUrl(useCustomUrl ? customUrl : platformUrl);
    const item = grouped.get(normalized.groupKey) || {
      url: normalized.url,
      openUrl: normalized.openUrl,
      status: normalized.status,
      services: [],
    };
    item.services.push({
      label: modality.label,
      source: useCustomUrl ? '自定义' : '平台',
    });
    grouped.set(normalized.groupKey, item);
  }

  return [...grouped.values()];
}

function focusTab(id: string) {
  window.requestAnimationFrame(() => document.getElementById(id)?.focus());
}

function getNextTabIndex(
  event: KeyboardEvent<HTMLButtonElement>,
  index: number,
  tabCount: number,
) {
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') return (index + 1) % tabCount;
  if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') return (index - 1 + tabCount) % tabCount;
  if (event.key === 'Home') return 0;
  if (event.key === 'End') return tabCount - 1;
  return null;
}

function getPriceSummary(model: AiModelItem, mode: CredentialMode) {
  if (!model.price) {
    return mode === 'platform' ? '未配置积分价格，平台账户不可用' : '使用我的 Key，不扣积分';
  }
  const estimatedPoints = model.estimated_points;
  const billingType = model.price?.billing_type;
  if (billingType === 'per_second') {
    const pointsPerSecond = model.price?.price_config.points_per_second;
    if (typeof pointsPerSecond === 'number') {
      return estimatedPoints == null
        ? `${pointsPerSecond} 积分/秒`
        : `${pointsPerSecond} 积分/秒 · 默认时长约 ${estimatedPoints} 积分`;
    }
    return estimatedPoints == null ? '按视频时长计费' : `默认时长约 ${estimatedPoints} 积分`;
  }
  if (estimatedPoints == null) return '按实际用量计费';
  if (billingType === 'per_image') return `预计 ${estimatedPoints} 积分/张`;
  if (billingType === 'per_1k_tokens') return `参考 ${estimatedPoints} 积分/次 · 按 Token 结算`;
  return `预计 ${estimatedPoints} 积分/次`;
}

export function PointsAiAccountPanel({
  canOverrideApiKey = false,
  canOverrideApiUrl = false,
  platformApi,
}: {
  canOverrideApiKey?: boolean;
  canOverrideApiUrl?: boolean;
  platformApi?: PlatformApiSettings;
}) {
  const canUseOwnKey = canOverrideApiKey || canOverrideApiUrl;
  const [activeTab, setActiveTab] = useState<AccountTab>('overview');
  const [activeModality, setActiveModality] = useState<ModelModality>('text');
  const [account, setAccount] = useState<PointsAccount | null>(null);
  const [ledger, setLedger] = useState<PointsLedgerItem[]>([]);
  const [credential, setCredential] = useState<AiCredentialStatus | null>(null);
  const [prefs, setPrefs] = useState<AiPreferences | null>(null);
  const [models, setModels] = useState<AiModelItem[]>([]);
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [apiSettings, setApiSettings] = useState<ApiKeySettings>(() => getApiKeySettings());
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<CredentialMode>(getLocalCredentialMode());

  const reload = useCallback(async () => {
    const [a, l, c, pr, m] = await Promise.all([
      getPointsAccount(),
      getPointsLedger(30),
      getAiCredential(),
      getAiPreferences(),
      getAiModels(),
    ]);
    setAccount(a);
    setLedger(l.items || []);
    setCredential(c);
    setModels(m.models || []);
    let nextPreferences = pr;
    if (pr.credential_mode === 'user_key' && (!c.configured || !canUseOwnKey)) {
      try {
        nextPreferences = await saveAiPreferences({ credential_mode: 'platform' });
        toast.info(canUseOwnKey ? '未检测到可用 API Key，已自动切换为平台账户' : '当前账号未获自定义上游权限，已切换为平台账户');
      } catch {
        nextPreferences = { ...pr, credential_mode: 'platform' };
        toast.error('未检测到可用 API Key，已在当前设备回退为平台账户');
      }
    }
    setPrefs(nextPreferences);
    if (nextPreferences.credential_mode) {
      setMode(nextPreferences.credential_mode);
      setLocalCredentialMode(nextPreferences.credential_mode);
    }
  }, [canUseOwnKey]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload().catch((error) =>
        toast.error(error instanceof Error ? error.message : '加载失败'),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [reload]);

  const onSaveKey = async () => {
    setBusy(true);
    try {
      const c = await saveAiCredential(apiKeyInput.trim());
      setCredential(c);
      setApiKeyInput('');
      toast.success('API Key 已保存');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const onTestKey = async () => {
    const draftKey = apiKeyInput.trim();
    const testingDraft = Boolean(draftKey);
    setBusy(true);
    try {
      await testAiCredential(draftKey || undefined);
      toast.success(testingDraft ? '当前输入的 Key 测试通过' : 'Key 测试通过');
      if (!testingDraft) await reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '测试失败');
    } finally {
      setBusy(false);
    }
  };

  const onClearKey = async () => {
    setBusy(true);
    try {
      if (mode === 'user_key') {
        const nextPrefs = await saveAiPreferences({ credential_mode: 'platform' });
        setPrefs(nextPrefs);
        setMode(nextPrefs.credential_mode);
        setLocalCredentialMode(nextPrefs.credential_mode);
      }
      await deleteAiCredential();
      toast.success('已清除 API Key');
      await reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '清除失败');
    } finally {
      setBusy(false);
    }
  };

  const onModeChange = async (next: CredentialMode) => {
    if (next === mode) return;
    if (next === 'user_key' && !canUseOwnKey) {
      toast.error('管理员未授权当前账号使用自定义 API Key 或上游');
      return;
    }
    setBusy(true);
    try {
      const pr = await saveAiPreferences({ credential_mode: next });
      setPrefs(pr);
      setMode(pr.credential_mode);
      setLocalCredentialMode(pr.credential_mode);
      toast.success(next === 'platform' ? '已切换为平台账户（扣积分）' : '已切换为我的 Key（不扣积分）');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '切换失败');
    } finally {
      setBusy(false);
    }
  };

  const onDefaultModel = async (modality: ModelModality, modelId: number) => {
    const config = MODEL_TABS.find((item) => item.key === modality);
    if (!config) return;
    setBusy(true);
    try {
      const pr = await saveAiPreferences({ [config.preferenceKey]: modelId });
      setPrefs(pr);
      toast.success(`默认${config.label}已更新`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const onSaveUpstream = () => {
    const baseUrl = apiSettings.upstreamBaseUrl.trim();
    if (baseUrl) {
      try {
        const parsed = new URL(baseUrl);
        if (parsed.protocol !== 'https:') {
          toast.error('自定义上游仅允许 HTTPS 地址');
          return;
        }
        if (parsed.username || parsed.password || parsed.search || parsed.hash) {
          toast.error('自定义上游地址不能包含认证信息、查询参数或片段');
          return;
        }
      } catch {
        toast.error('请输入有效的自定义 Base URL');
        return;
      }
    }
    const nextSettings = { ...apiSettings, upstreamBaseUrl: baseUrl };
    setApiSettings(nextSettings);
    saveApiKeySettings(nextSettings);
    toast.success('统一上游配置已保存');
  };

  const onClearUpstream = () => {
    const fields = UPSTREAM_FIELDS[activeModality];
    setApiSettings((previous) => {
      const next = {
        ...previous,
        upstreamBaseUrl: '',
        deepseekBaseUrl: '',
        imageBaseUrl: '',
        videoBaseUrl: '',
        [fields.modelKey]: '',
      };
      saveApiKeySettings(next);
      return next;
    });
    toast.info(`已恢复使用管理员配置的${modelConfig.label}上游`);
  };

  const handleAccountTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const nextIndex = getNextTabIndex(event, index, ACCOUNT_TABS.length);
    if (nextIndex == null) return;
    event.preventDefault();
    const nextTab = ACCOUNT_TABS[nextIndex];
    setActiveTab(nextTab.key);
    focusTab(`account-tab-${nextTab.key}`);
  };

  const handleModelTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const nextIndex = getNextTabIndex(event, index, MODEL_TABS.length);
    if (nextIndex == null) return;
    event.preventDefault();
    const nextTab = MODEL_TABS[nextIndex];
    setActiveModality(nextTab.key);
    focusTab(`model-tab-${nextTab.key}`);
  };

  const modelConfig = MODEL_TABS.find((item) => item.key === activeModality) || MODEL_TABS[0];
  const ModelIcon = modelConfig.icon;
  const upstreamFields = UPSTREAM_FIELDS[activeModality];
  const customBaseUrl = apiSettings.upstreamBaseUrl;
  const customModel = apiSettings[upstreamFields.modelKey];
  const platformModel = platformApi?.[upstreamFields.platformModelKey] || '-';
  const availableModels = models.filter((item) => item.modality === activeModality);
  const selectableModels = availableModels.filter((item) => mode === 'user_key' || item.price);
  const selectedModelId = prefs?.[modelConfig.preferenceKey] ?? null;
  const selectedModel = availableModels.find((item) => item.id === selectedModelId) || null;
  const upstreamGuideItems = buildUpstreamGuideItems(apiSettings, platformApi, canOverrideApiUrl, mode);

  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_12px_30px_rgba(37,99,235,0.06)]">
      <div className="flex items-start gap-3 px-5 py-5 sm:px-6">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#eff6ff] text-[#2563eb]">
          <Coins size={20} aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-slate-900">积分与 AI 配置</h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            管理账户计费、API 凭据和各类默认模型。
          </p>
        </div>
      </div>

      <div
        className="grid grid-cols-2 border-y border-[#d7e3f4] bg-slate-50/70 sm:grid-cols-4"
        role="tablist"
        aria-label="积分与 AI 配置分类"
      >
        {ACCOUNT_TABS.map((tab, index) => {
          const Icon = tab.icon;
          const selected = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              id={`account-tab-${tab.key}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`account-panel-${tab.key}`}
              tabIndex={selected ? 0 : -1}
              className={`relative flex min-h-12 items-center justify-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${
                selected
                  ? 'border-blue-600 bg-white text-blue-700'
                  : 'border-transparent text-slate-500 hover:bg-white/70 hover:text-slate-800'
              }`}
              onClick={() => setActiveTab(tab.key)}
              onKeyDown={(event) => handleAccountTabKeyDown(event, index)}
            >
              <Icon size={16} aria-hidden="true" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {activeTab === 'overview' ? (
        <div
          id="account-panel-overview"
          role="tabpanel"
          aria-labelledby="account-tab-overview"
          className="p-5 sm:p-6"
        >
          <div className="grid overflow-hidden rounded-xl border border-[#e5edf8] bg-[#f8fbff] md:grid-cols-3 md:divide-x md:divide-[#e5edf8]">
            <div className="flex min-h-28 items-center gap-3 px-4 py-5 sm:px-5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white text-[#2563eb] shadow-sm">
                <Coins size={19} aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-500">可用积分</div>
                <div className="mt-0.5 text-2xl font-semibold text-slate-900">
                  {account ? account.available_points : '-'}
                </div>
                <div className="text-xs text-slate-500">预扣中 {account?.reserved_points ?? 0}</div>
              </div>
            </div>

            <div className="min-h-28 border-t border-[#e5edf8] px-4 py-5 sm:px-5 md:border-t-0">
              <div className="text-xs font-medium text-slate-500">当前计费模式</div>
              <div className="mt-2 inline-flex max-w-full rounded-xl border border-[#d7e3f4] bg-white p-1" role="group" aria-label="AI 计费模式">
                <button
                  type="button"
                  disabled={busy}
                  aria-pressed={mode === 'platform'}
                  onClick={() => onModeChange('platform')}
                  className={`min-w-0 flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition sm:min-w-24 ${mode === 'platform' ? 'bg-[#2563eb] text-white shadow-sm' : 'text-slate-600 hover:bg-slate-50'}`}
                >
                  平台账户
                </button>
                <button
                  type="button"
                  disabled={busy || !canUseOwnKey || !credential?.configured}
                  aria-pressed={mode === 'user_key'}
                  title={!canUseOwnKey ? '管理员尚未授权' : credential?.configured ? undefined : '请先保存 API Key'}
                  onClick={() => onModeChange('user_key')}
                  className={`min-w-0 flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition sm:min-w-24 ${mode === 'user_key' ? 'bg-[#2563eb] text-white shadow-sm' : 'text-slate-600 hover:bg-slate-50'}`}
                >
                  我的 Key
                </button>
              </div>
            </div>

            <div className="flex min-h-28 items-center gap-3 border-t border-[#e5edf8] px-4 py-5 sm:px-5 md:border-t-0">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white shadow-sm ${credential?.configured ? 'text-emerald-600' : 'text-slate-400'}`}>
                {credential?.configured ? <ShieldCheck size={19} aria-hidden="true" /> : <KeyRound size={19} aria-hidden="true" />}
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-500">API Key 状态</div>
                <div className="mt-0.5 truncate text-sm font-semibold text-slate-900">
                  {!canUseOwnKey ? '未授权' : credential?.configured ? `已配置 ···${credential.last_four || ''}` : '未配置'}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {!canUseOwnKey ? '请联系管理员开放权限' : credential?.configured ? `验证状态：${credential.status || '待验证'}` : '使用平台账户无需填写'}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-2 border-t border-[#e5edf8] pt-4 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between">
            <span>{mode === 'platform' ? '平台账户：使用已上架模型并按规则扣除积分。' : '我的 Key：使用你的上游额度，平台不扣积分。'}</span>
            <button
              type="button"
              className="shrink-0 font-medium text-[#1d4ed8] hover:underline"
              onClick={() => {
                setActiveTab('credential');
                focusTab('account-tab-credential');
              }}
            >
              管理 API 凭据
            </button>
          </div>
        </div>
      ) : null}

      {activeTab === 'credential' ? (
        <div
          id="account-panel-credential"
          role="tabpanel"
          aria-labelledby="account-tab-credential"
          className="p-5 sm:p-6"
        >
          <div className="max-w-3xl">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#f8fbff] text-[#2563eb]">
                <KeyRound size={18} aria-hidden="true" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-900">配置我的 API Key</h4>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  {!canUseOwnKey ? '当前账号未获自定义 API Key 或上游权限。' : canOverrideApiUrl ? 'Key 会加密保存；已授权的自定义地址在「模型配置」中管理。' : 'Key 会加密保存，上游服务地址由管理员统一维护。'}
                </p>
              </div>
            </div>

            <div className="mt-5 border-y border-[#e5edf8] bg-slate-50/70 py-4">
              <div className="px-3">
                <h5 className="text-xs font-semibold text-slate-800">当前 API 服务地址</h5>
                <p className="mt-1 text-xs leading-5 text-slate-500">可打开服务地址确认上游；API Key 请按服务商控制台或页面指引获取。</p>
              </div>
              <div className="mt-3 divide-y divide-[#e5edf8]">
                {upstreamGuideItems.map((item, index) => (
                  <div
                    key={item.url || `missing-${index}`}
                    className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap gap-1.5">
                        {item.services.map((service) => (
                          <span
                            key={`${service.label}-${service.source}`}
                            className="rounded-md border border-[#d7e3f4] bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600"
                          >
                            {service.label} · {service.source}
                          </span>
                        ))}
                      </div>
                      <div className="mt-1.5 break-all text-xs text-slate-700">
                        {item.status === 'unsafe'
                          ? '地址格式不安全，请联系管理员更新'
                          : item.url || '管理员暂未配置'}
                      </div>
                    </div>
                    {item.status === 'available' ? (
                      <a
                        href={item.openUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex shrink-0 items-center gap-1.5 self-start text-xs font-medium text-[#2563eb] hover:text-[#1d4ed8] sm:self-center"
                      >
                        访问上游网站
                        <ExternalLink size={14} aria-hidden="true" />
                      </a>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>

            <label className="mt-5 block text-xs font-medium text-slate-600" htmlFor="user-ai-api-key">
              API Key
            </label>
            <Input
              id="user-ai-api-key"
              type="password"
              disabled={!canUseOwnKey}
              value={apiKeyInput}
              onChange={(event) => setApiKeyInput(event.target.value)}
              placeholder={credential?.configured ? `已配置 ···${credential.last_four || ''}` : 'sk-...'}
              className="mt-1 rounded-xl"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={busy || !canUseOwnKey || !apiKeyInput.trim()}
                onClick={onSaveKey}
                size="sm"
                icon={<Save size={14} />}
              >
                保存
              </Button>
              <Button
                type="button"
                disabled={busy || !canUseOwnKey || (!apiKeyInput.trim() && !credential?.configured)}
                onClick={onTestKey}
                size="sm"
                variant="secondary"
                icon={<FlaskConical size={14} />}
              >
                {apiKeyInput.trim() ? '测试当前 Key' : '测试已保存 Key'}
              </Button>
              <Button
                type="button"
                disabled={busy || !canUseOwnKey || !credential?.configured}
                onClick={onClearKey}
                size="sm"
                variant="danger"
                icon={<Trash2 size={14} />}
              >
                清除
              </Button>
            </div>

            <div className="mt-5 flex items-center gap-3 border-t border-[#e5edf8] pt-4 text-xs text-slate-500">
              {credential?.configured ? (
                <CheckCircle2 size={16} className="shrink-0 text-emerald-600" aria-hidden="true" />
              ) : (
                <ShieldCheck size={16} className="shrink-0 text-slate-400" aria-hidden="true" />
              )}
              <span>
                {credential?.configured
                  ? `当前凭据已保存，验证状态：${credential.status || '待验证'}。`
                  : '保存并通过测试后，即可在账户概览中切换为「我的 Key」。'}
              </span>
            </div>
          </div>
        </div>
      ) : null}

      {activeTab === 'models' ? (
        <div
          id="account-panel-models"
          role="tabpanel"
          aria-labelledby="account-tab-models"
          className="p-5 sm:p-6"
        >
          <div className="max-w-4xl">
            <div>
              <h4 className="text-sm font-semibold text-slate-900">默认模型</h4>
              <p className="mt-1 text-xs leading-5 text-slate-500">从管理员已上架的模型中选择，各类任务会优先使用对应的默认配置。</p>
            </div>

            {canOverrideApiUrl ? (
              <div className="mt-5 border-y border-[#e5edf8] py-4">
                <label className="block text-xs font-medium text-slate-600" htmlFor="custom-upstream-base-url">自定义上游 Base URL</label>
                <Input
                  id="custom-upstream-base-url"
                  type="url"
                  value={customBaseUrl}
                  onChange={(event) => setApiSettings((previous) => ({ ...previous, upstreamBaseUrl: event.target.value }))}
                  placeholder="https://api.example.com/v1"
                  className="mt-1 rounded-xl"
                />
                <p className="mt-1 text-xs leading-5 text-slate-400">文本、图片和视频将统一使用此地址；模型名称仍可分别设置。</p>
              </div>
            ) : null}

            <div
              className="mt-5 inline-grid w-full grid-cols-3 rounded-xl border border-[#d7e3f4] bg-[#f8fbff] p-1 sm:w-auto"
              role="tablist"
              aria-label="默认模型类型"
            >
              {MODEL_TABS.map((tab, index) => {
                const Icon = tab.icon;
                const selected = activeModality === tab.key;
                return (
                  <button
                    key={tab.key}
                    id={`model-tab-${tab.key}`}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    aria-controls="model-config-panel"
                    tabIndex={selected ? 0 : -1}
                    onClick={() => setActiveModality(tab.key)}
                    onKeyDown={(event) => handleModelTabKeyDown(event, index)}
                    className={`flex min-h-10 min-w-0 items-center justify-center gap-1.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                      selected ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Icon size={15} className="shrink-0" aria-hidden="true" />
                    <span className="truncate">{tab.label}</span>
                  </button>
                );
              })}
            </div>

            <div
              id="model-config-panel"
              role="tabpanel"
              aria-labelledby={`model-tab-${activeModality}`}
              className="mt-5 border-t border-[#e5edf8] pt-5"
            >
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#eff6ff] text-[#2563eb]">
                  <ModelIcon size={18} aria-hidden="true" />
                </div>
                <div>
                  <h5 className="text-sm font-semibold text-slate-900">{modelConfig.label}</h5>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{modelConfig.description}</p>
                </div>
              </div>

              <label className="mt-4 block text-xs font-medium text-slate-600" htmlFor={`default-${activeModality}-model`}>
                默认模型
              </label>
              <Select
                id={`default-${activeModality}-model`}
                value={selectedModel?.id ?? ''}
                disabled={busy || selectableModels.length === 0}
                onChange={(event) => {
                  const modelId = Number(event.target.value);
                  if (modelId) void onDefaultModel(activeModality, modelId);
                }}
                className="mt-1 rounded-xl bg-white"
              >
                <option value="">
                  {availableModels.length === 0
                    ? `暂无可用${modelConfig.label}`
                    : selectableModels.length === 0
                      ? '当前计费模式下暂无可选模型'
                      : '请选择默认模型'}
                </option>
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id} disabled={mode === 'platform' && !model.price}>
                    {model.display_name}
                    {model.price
                      ? model.estimated_points != null
                        ? ` · 约 ${model.estimated_points} 积分`
                        : ''
                      : ' · 未定价'}
                  </option>
                ))}
              </Select>

              <div className="mt-3 min-h-10 border-t border-[#e5edf8] pt-3 text-xs text-slate-500">
                {selectedModel ? (
                  <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
                    <span className="break-all">模型标识：{selectedModel.model_key}</span>
                    <span className={`shrink-0 font-medium ${mode === 'platform' && !selectedModel.price ? 'text-rose-600' : 'text-[#1d4ed8]'}`}>
                      {getPriceSummary(selectedModel, mode)}
                    </span>
                  </div>
                ) : selectedModelId ? (
                  <span className="text-amber-600">原默认模型已下架，请重新选择可用模型。</span>
                ) : (
                  <span>选择后将作为{modelConfig.label}任务的默认模型。</span>
                )}
              </div>

              {canOverrideApiUrl ? (
                <div className="mt-5 border-t border-[#e5edf8] pt-5">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-slate-900">自定义上游</div>
                      <p className="mt-1 text-xs leading-5 text-slate-500">
                        管理员已授权当前账号使用统一上游地址，并为不同任务配置模型；配置仅保存在当前浏览器。
                      </p>
                    </div>
                    <span className="w-fit shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                      已授权
                    </span>
                  </div>

                  {mode !== 'user_key' ? (
                    <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                      自定义上游仅在「我的 Key」模式生效，请先在账户概览中切换计费模式。
                    </div>
                  ) : null}

                  <div className="mt-4">
                    <div>
                      <label className="block text-xs font-medium text-slate-600" htmlFor={`custom-${activeModality}-model`}>
                        自定义模型名称
                      </label>
                      <Input
                        id={`custom-${activeModality}-model`}
                        value={customModel}
                        onChange={(event) => setApiSettings((previous) => ({
                          ...previous,
                          [upstreamFields.modelKey]: event.target.value,
                        }))}
                        placeholder={platformModel === '-' ? '输入上游模型名称' : platformModel}
                        className="mt-1 rounded-xl"
                      />
                      <div className="mt-1 truncate text-xs text-slate-400" title={platformModel}>平台配置：{platformModel}</div>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button type="button" size="sm" icon={<Save size={14} />} onClick={onSaveUpstream}>
                      保存上游配置
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      disabled={!customBaseUrl && !customModel}
                      onClick={onClearUpstream}
                    >
                      恢复平台配置
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {activeTab === 'ledger' ? (
        <div
          id="account-panel-ledger"
          role="tabpanel"
          aria-labelledby="account-tab-ledger"
          className="p-5 sm:p-6"
        >
          <div className="mb-3">
            <h4 className="text-sm font-semibold text-slate-900">积分流水</h4>
            <p className="mt-1 text-xs text-slate-500">最近 30 条积分收入与消费记录。</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th className="py-3 pr-4 font-medium">时间</th>
                  <th className="py-3 pr-4 font-medium">类型</th>
                  <th className="py-3 pr-4 font-medium">变动</th>
                  <th className="py-3 font-medium">余额</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((row) => (
                  <tr key={row.id} className="border-t border-slate-100">
                    <td className="whitespace-nowrap py-2.5 pr-4 text-slate-600">{row.created_at || '-'}</td>
                    <td className="whitespace-nowrap py-2.5 pr-4">{row.entry_type}</td>
                    <td className={`whitespace-nowrap py-2.5 pr-4 ${row.amount >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                      {row.amount}
                    </td>
                    <td className="whitespace-nowrap py-2.5">{row.balance_after ?? '-'}</td>
                  </tr>
                ))}
                {ledger.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-10 text-center text-slate-500">
                      暂无流水
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}
