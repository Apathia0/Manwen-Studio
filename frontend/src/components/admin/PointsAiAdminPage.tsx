import { useCallback, useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react';
import {
  Bot,
  Coins,
  DatabaseZap,
  Eye,
  EyeOff,
  Package,
  Pencil,
  Plus,
  RadioTower,
  RefreshCw,
  Save,
  Square,
  SquareCheckBig,
  Tags,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react';
import {
  type AiChannelAdmin,
  type AiModelAdmin,
  type AiPriceSyncPreview,
  type VideoAdapterType,
  type UpstreamAiModelCandidate,
  type PointsProduct,
  type PointsSettings,
  addAdminAiChannelModels,
  createAdminAiChannel,
  createAdminAiModel,
  createAdminPointsProduct,
  deleteAdminPointsProduct,
  deleteAdminAiChannel,
  deleteAdminAiModel,
  discoverAdminAiChannelModels,
  getAdminAiChannels,
  getAdminAiModels,
  getAdminPointsProducts,
  getAdminPointsSettings,
  previewAdminAiChannelPrices,
  saveAdminPointsSettings,
  setAdminAiModelPrice,
  syncAdminAiChannelPrices,
  updateAdminAiChannel,
  updateAdminAiModel,
  updateAdminPointsProduct,
} from '../../api';
import { confirm } from '../../lib/confirm';
import { toast } from '../../lib/toast';
import { applyVideoAdapterPreset, applyVideoModelCapabilitiesPreset, createVideoAdapterDraftState, getVideoAdapterLabel, getVideoModelCapabilitiesAdapter, isVideoAdapterType, VIDEO_ADAPTER_PRESETS } from '../../lib/videoAdapterPresets';
import { Button, Input, Select, TextArea } from '../ui';

type TabKey = 'settings' | 'products' | 'channels' | 'models';
type ModelModalityFilter = 'all' | 'text' | 'image' | 'video';

interface TabItem {
  key: TabKey;
  label: string;
  icon: LucideIcon;
}

const TABS: TabItem[] = [
  { key: 'settings', label: '积分规则', icon: Coins },
  { key: 'products', label: '积分套餐', icon: Package },
  { key: 'channels', label: 'AI 渠道', icon: RadioTower },
  { key: 'models', label: '模型目录', icon: Bot },
];

const MODEL_MODALITY_FILTERS: Array<{ value: ModelModalityFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'text', label: '文本' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
];

const EMPTY_PRODUCT_FORM = {
  code: '',
  name: '',
  description: '',
  price_cny: 10,
  points: 100,
  bonus_points: 0,
  is_visible: true,
  is_recommended: false,
  sort_order: 0,
};

const EMPTY_CHANNEL_FORM = {
  code: '',
  name: '',
  base_url: '',
  modality: 'text',
  adapter_type: 'lingdong_video',
  platform_api_key: '',
  extra_config_json: '{}',
};

const IMAGE_QUALITY_OPTIONS = ['auto', 'low', 'medium', 'high'] as const;
const DEFAULT_IMAGE_CAPABILITIES = {
  schema_version: 1,
  image: {
    defaults: { quality: 'high' },
    limits: { qualities: [...IMAGE_QUALITY_OPTIONS] },
  },
};
const DEFAULT_TEXT_POINTS_PER_1M_TOKENS = 2000;
const PRICE_NUMBER_FORMATTER = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 4,
});

function defaultPointsForModality(modality: string) {
  if (modality === 'video') return 3;
  if (modality === 'image') return 5;
  return DEFAULT_TEXT_POINTS_PER_1M_TOKENS;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block min-w-0 text-sm font-medium text-slate-700">
      <span className="flex items-center justify-between gap-2">
        {label}
        {hint ? <span className="text-xs font-normal text-slate-400">{hint}</span> : null}
      </span>
      <span className="mt-1.5 block">{children}</span>
    </label>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-28 items-center justify-center border-y border-dashed border-slate-200 px-4 text-center text-sm text-slate-400">
      {children}
    </div>
  );
}

function StatusLabel({ active, activeText, inactiveText }: { active: boolean; activeText: string; inactiveText: string }) {
  return (
    <span className={active ? 'text-emerald-700' : 'text-slate-400'}>
      {active ? activeText : inactiveText}
    </span>
  );
}

function readPrice(config: Record<string, unknown> | undefined, key: string, fallback: number) {
  const value = Number(config?.[key]);
  return Number.isFinite(value) ? value : fallback;
}

function formatPriceNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? PRICE_NUMBER_FORMATTER.format(parsed) : '-';
}

function formatModelPrice(price: { billing_type: string; price_config_json: Record<string, unknown> } | null) {
  if (!price) return '未定价';
  const config = price.price_config_json;
  if (price.billing_type === 'per_1m_tokens') {
    const legacy = config.points_per_1m_tokens;
    return `输入 ${formatPriceNumber(config.input_points_per_1m ?? legacy)} / 输出 ${formatPriceNumber(config.output_points_per_1m ?? legacy)} 积分/百万 Token`;
  }
  if (price.billing_type === 'per_image') return `${formatPriceNumber(config.points_per_image)} 积分/张`;
  if (price.billing_type === 'per_second') return `${formatPriceNumber(config.points_per_second)} 积分/秒`;
  if (price.billing_type === 'per_call') return `${formatPriceNumber(config.points_per_call)} 积分/次`;
  return price.billing_type;
}

function formatUpstreamPrice(price: Record<string, unknown> | null, modality: string) {
  if (!price) return '-';
  if (price.input_cny_per_1m != null || price.output_cny_per_1m != null) {
    return `输入 ¥${formatPriceNumber(price.input_cny_per_1m)} / 输出 ¥${formatPriceNumber(price.output_cny_per_1m)} 每百万 Token`;
  }
  const fixed = price.fixed_cny ?? price.cny_per_call ?? price.cny_per_image;
  return fixed == null ? '-' : `¥${formatPriceNumber(fixed)} / ${modality === 'image' ? '张' : '次'}`;
}

function readTextPrices(model: AiModelAdmin) {
  const price = model.active_price;
  const config = price?.price_config_json;
  if (price?.billing_type === 'per_1m_tokens') {
    const legacyRate = readPrice(config, 'points_per_1m_tokens', DEFAULT_TEXT_POINTS_PER_1M_TOKENS);
    return {
      input: readPrice(config, 'input_points_per_1m', legacyRate),
      output: readPrice(config, 'output_points_per_1m', legacyRate),
    };
  }
  if (price?.billing_type === 'per_call') {
    const totalTokens = 20000 + 8192;
    const rate = totalTokens > 0 ? (readPrice(config, 'points_per_call', 2) * 1000000) / totalTokens : DEFAULT_TEXT_POINTS_PER_1M_TOKENS;
    return { input: rate, output: rate };
  }
  if (price?.billing_type === 'per_1k_tokens') {
    return {
      input: readPrice(config, 'input_points_per_1k', 0) * 1000,
      output: readPrice(config, 'output_points_per_1k', 0) * 1000,
    };
  }
  return { input: DEFAULT_TEXT_POINTS_PER_1M_TOKENS, output: DEFAULT_TEXT_POINTS_PER_1M_TOKENS };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && !Array.isArray(value) && typeof value === 'object';
}

function getImageCapabilitiesDraft(capabilities: Record<string, unknown> | null | undefined) {
  return capabilities?.image ? capabilities : DEFAULT_IMAGE_CAPABILITIES;
}

function getImageQualityDraft(raw: string) {
  try {
    const value: unknown = JSON.parse(raw);
    const quality = isRecord(value) && isRecord(value.image) && isRecord(value.image.defaults)
      ? value.image.defaults.quality
      : undefined;
    return typeof quality === 'string' && IMAGE_QUALITY_OPTIONS.includes(quality as (typeof IMAGE_QUALITY_OPTIONS)[number])
      ? quality
      : 'high';
  } catch {
    return 'high';
  }
}

function setImageQualityDraft(raw: string, quality: string) {
  let value: Record<string, unknown> = DEFAULT_IMAGE_CAPABILITIES;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (isRecord(parsed)) value = getImageCapabilitiesDraft(parsed);
  } catch {
    // JSON 草稿尚未完成时，以受控默认配置继续编辑。
  }
  const image = isRecord(value.image) ? value.image : {};
  const defaults = isRecord(image.defaults) ? image.defaults : {};
  return JSON.stringify({
    ...value,
    schema_version: 1,
    image: { ...image, defaults: { ...defaults, quality } },
  }, null, 2);
}

export function PointsAiAdminPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('settings');
  const [channels, setChannels] = useState<AiChannelAdmin[]>([]);
  const [models, setModels] = useState<AiModelAdmin[]>([]);
  const [modelModalityFilter, setModelModalityFilter] = useState<ModelModalityFilter>('all');
  const [products, setProducts] = useState<PointsProduct[]>([]);
  const [settings, setSettings] = useState<PointsSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingProductId, setEditingProductId] = useState<number | null>(null);
  const [productForm, setProductForm] = useState({ ...EMPTY_PRODUCT_FORM });
  const [editingChannelId, setEditingChannelId] = useState<number | null>(null);
  const [channelForm, setChannelForm] = useState({ ...EMPTY_CHANNEL_FORM });
  const [pricingModelId, setPricingModelId] = useState<number | null>(null);
  const [editingModelId, setEditingModelId] = useState<number | null>(null);
  const [upstreamModalOpen, setUpstreamModalOpen] = useState(false);
  const [upstreamChannelId, setUpstreamChannelId] = useState<number>(0);
  const [upstreamCandidates, setUpstreamCandidates] = useState<UpstreamAiModelCandidate[]>([]);
  const [selectedUpstreamKeys, setSelectedUpstreamKeys] = useState<string[]>([]);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [addingModels, setAddingModels] = useState(false);
  const [priceSyncModalOpen, setPriceSyncModalOpen] = useState(false);
  const [priceSyncChannelId, setPriceSyncChannelId] = useState(0);
  const [priceSyncPreview, setPriceSyncPreview] = useState<AiPriceSyncPreview | null>(null);
  const [selectedPriceSyncModelIds, setSelectedPriceSyncModelIds] = useState<number[]>([]);
  const [previewingPrices, setPreviewingPrices] = useState(false);
  const [applyingPrices, setApplyingPrices] = useState(false);
  const [capabilitiesModelId, setCapabilitiesModelId] = useState<number | null>(null);
  const [capabilitiesDraft, setCapabilitiesDraft] = useState('');
  const [selectedVideoPreset, setSelectedVideoPreset] = useState<VideoAdapterType | 'custom' | ''>('');
  const [priceForm, setPriceForm] = useState({
    billing_type: 'per_1m_tokens',
    points: DEFAULT_TEXT_POINTS_PER_1M_TOKENS,
    output_points: DEFAULT_TEXT_POINTS_PER_1M_TOKENS,
    estimate_default_seconds: 15,
  });
  const [modelForm, setModelForm] = useState({
    channel_id: 0,
    model_key: '',
    display_name: '',
    intro_tag: '',
    modality: 'text',
    initial_points: DEFAULT_TEXT_POINTS_PER_1M_TOKENS,
    initial_output_points: DEFAULT_TEXT_POINTS_PER_1M_TOKENS,
    video_billing_type: 'per_second',
    sort_order: 0,
    user_visible: true,
    capabilities_json: '{}',
  });

  const reload = useCallback(async () => {
    const [channelResult, modelResult, settingsResult, productResult] = await Promise.all([
      getAdminAiChannels(),
      getAdminAiModels(),
      getAdminPointsSettings(),
      getAdminPointsProducts(),
    ]);
    const nextChannels = channelResult.channels || [];
    setChannels(nextChannels);
    setModels(modelResult.models || []);
    setSettings(settingsResult);
    setProducts(productResult.products || []);
    setModelForm((prev) => {
      if (nextChannels.some((channel) => channel.id === prev.channel_id)) return prev;
      const fallbackChannel = nextChannels[0];
      return fallbackChannel
        ? {
            ...prev,
            channel_id: fallbackChannel.id,
            modality: fallbackChannel.modality,
            initial_points: defaultPointsForModality(fallbackChannel.modality),
            initial_output_points: defaultPointsForModality(fallbackChannel.modality),
          }
        : { ...prev, channel_id: 0 };
    });
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload().catch((error) =>
        toast.error(error instanceof Error ? error.message : '加载失败'),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [reload]);

  const modelModalityCounts = useMemo(() => {
    const counts: Record<ModelModalityFilter, number> = { all: models.length, text: 0, image: 0, video: 0 };
    for (const model of models) {
      if (model.modality === 'text' || model.modality === 'image' || model.modality === 'video') {
        counts[model.modality] += 1;
      }
    }
    return counts;
  }, [models]);

  const filteredModels = useMemo(
    () => modelModalityFilter === 'all'
      ? models
      : models.filter((model) => model.modality === modelModalityFilter),
    [modelModalityFilter, models],
  );

  const resetProductForm = () => {
    setEditingProductId(null);
    setProductForm({ ...EMPTY_PRODUCT_FORM });
  };

  const resetChannelForm = () => {
    setEditingChannelId(null);
    setChannelForm({ ...EMPTY_CHANNEL_FORM });
  };

  const startProductEdit = (product: PointsProduct) => {
    setEditingProductId(product.id);
    setProductForm({
      code: product.code,
      name: product.name,
      description: product.description,
      price_cny: product.price_cny,
      points: product.points,
      bonus_points: product.bonus_points,
      is_visible: product.is_visible,
      is_recommended: product.is_recommended,
      sort_order: product.sort_order,
    });
  };

  const startChannelEdit = (channel: AiChannelAdmin) => {
    const adapterDraft = createVideoAdapterDraftState(channel.adapter_type);
    setEditingChannelId(channel.id);
    setChannelForm({
      code: channel.code,
      name: channel.name,
      base_url: channel.base_url || '',
      modality: channel.modality,
      adapter_type: adapterDraft.adapterType,
      platform_api_key: '',
      extra_config_json: JSON.stringify(channel.extra_config_json || {}, null, 2),
    });
  };

  const startPriceEdit = (model: AiModelAdmin) => {
    const config = model.active_price?.price_config_json;
    const textPrices = readTextPrices(model);
    setPricingModelId(model.id);
    setPriceForm({
      billing_type: model.active_price?.billing_type || (model.modality === 'text' ? 'per_1m_tokens' : model.modality === 'video' ? 'per_second' : 'per_image'),
      points: model.modality === 'text'
        ? textPrices.input
        : readPrice(
            config,
            model.active_price?.billing_type === 'per_call'
              ? 'points_per_call'
              : model.modality === 'video' ? 'points_per_second' : 'points_per_image',
            defaultPointsForModality(model.modality),
          ),
      output_points: textPrices.output,
      estimate_default_seconds: readPrice(config, 'estimate_default_seconds', 15),
    });
  };

  const resetModelForm = () => {
    setEditingModelId(null);
    setSelectedVideoPreset('');
    setModelForm((previous) => ({
      channel_id: previous.channel_id || channels[0]?.id || 0,
      model_key: '',
      display_name: '',
      intro_tag: '',
      modality: 'text',
      initial_points: DEFAULT_TEXT_POINTS_PER_1M_TOKENS,
      initial_output_points: DEFAULT_TEXT_POINTS_PER_1M_TOKENS,
      video_billing_type: 'per_second',
      sort_order: 0,
      user_visible: true,
      capabilities_json: '{}',
    }));
  };

  const startModelEdit = (model: AiModelAdmin) => {
    setPricingModelId(null);
    setCapabilitiesModelId(null);
    setEditingModelId(model.id);
    const channel = channels.find((item) => item.id === model.channel_id);
    setSelectedVideoPreset(getVideoModelCapabilitiesAdapter(model.modality, channel?.adapter_type) || '');
    const textPrices = readTextPrices(model);
    setModelForm({
      channel_id: model.channel_id,
      model_key: model.model_key,
      display_name: model.display_name,
      intro_tag: model.intro_tag || '',
      modality: model.modality,
      initial_points: model.modality === 'text'
        ? textPrices.input
        : readPrice(
            model.active_price?.price_config_json,
            model.modality === 'video'
              ? model.active_price?.billing_type === 'per_call' ? 'points_per_call' : 'points_per_second'
              : 'points_per_image',
            defaultPointsForModality(model.modality),
          ),
      initial_output_points: textPrices.output,
      video_billing_type: model.active_price?.billing_type === 'per_call' ? 'per_call' : 'per_second',
      sort_order: model.sort_order,
      user_visible: model.user_visible,
      capabilities_json: JSON.stringify(
        model.modality === 'image'
          ? getImageCapabilitiesDraft(model.capabilities_json)
          : model.capabilities_json || {},
        null,
        2,
      ),
    });
  };

  const startCapabilitiesEdit = (model: AiModelAdmin) => {
    setPricingModelId(null);
    setCapabilitiesModelId(model.id);
    const draft = model.modality === 'image'
      ? getImageCapabilitiesDraft(model.capabilities_json)
      : model.capabilities_json || {
          schema_version: 1,
          video: {
            payload_profile: 'legacy_lingdong',
            defaults: { aspect_ratio: '16:9', resolution: '720P', duration_seconds: 15 },
            input_modes: ['text_to_video'],
            limits: { aspect_ratios: ['16:9', '9:16'], resolutions: ['720P'], duration_seconds: { allowed: [15] }, max_reference_images: 9 },
          },
        };
    setCapabilitiesDraft(JSON.stringify(draft, null, 2));
  };

  const saveCapabilities = async (model: AiModelAdmin) => {
    try {
      const value: unknown = JSON.parse(capabilitiesDraft);
      if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('配置必须是 JSON 对象');
      setBusy(true);
      await updateAdminAiModel(model.id, { capabilities_json: value });
      setCapabilitiesModelId(null);
      await reload();
      toast.success(`${model.modality === 'image' ? '图片质量' : '视频'}参数配置已保存`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '参数配置格式无效');
    } finally {
      setBusy(false);
    }
  };

  const saveProduct = async () => {
    setBusy(true);
    try {
      if (editingProductId) {
        await updateAdminPointsProduct(editingProductId, productForm);
        toast.success('积分套餐已更新');
      } else {
        await createAdminPointsProduct(productForm);
        toast.success('积分套餐已创建');
      }
      resetProductForm();
      await reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const saveChannel = async () => {
    setBusy(true);
    try {
      const extraConfig: unknown = JSON.parse(channelForm.extra_config_json || '{}');
      if (!isRecord(extraConfig)) throw new Error('渠道高级配置必须是 JSON 对象');
      const videoAdapterType = channelForm.modality === 'video' ? channelForm.adapter_type : undefined;
      if (channelForm.modality === 'video' && !isVideoAdapterType(videoAdapterType)) {
        throw new Error('请选择受支持的视频适配器后再保存');
      }
      const payload = {
        name: channelForm.name,
        base_url: channelForm.base_url,
        modality: channelForm.modality,
        ...(isVideoAdapterType(videoAdapterType) ? { adapter_type: videoAdapterType } : {}),
        extra_config_json: extraConfig,
        ...(channelForm.platform_api_key.trim()
          ? { platform_api_key: channelForm.platform_api_key.trim() }
          : {}),
      };
      if (editingChannelId) {
        await updateAdminAiChannel(editingChannelId, payload);
        toast.success('渠道已更新');
      } else {
        await createAdminAiChannel({ ...payload, code: channelForm.code });
        toast.success('渠道已创建');
      }
      resetChannelForm();
      await reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const deleteChannel = async (channel: AiChannelAdmin) => {
    const accepted = await confirm({
      title: '删除 AI 渠道',
      message: `确定删除渠道“${channel.name}”吗？未被业务引用的所属模型和价格也会一并删除。`,
      confirmText: '删除渠道',
      danger: true,
    });
    if (!accepted) return;
    setBusy(true);
    try {
      await deleteAdminAiChannel(channel.id);
      if (editingChannelId === channel.id) resetChannelForm();
      await reload();
      toast.success('渠道已删除');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除渠道失败');
    } finally {
      setBusy(false);
    }
  };

  const saveModelPrice = async (model: AiModelAdmin) => {
    setBusy(true);
    try {
      const billingType =
        model.modality === 'video'
          ? priceForm.billing_type === 'per_call' ? 'per_call' : 'per_second'
          : model.modality === 'image'
            ? 'per_image'
            : 'per_1m_tokens';
      const priceConfig =
        model.modality === 'video'
          ? billingType === 'per_call'
            ? { points_per_call: priceForm.points }
            : {
              points_per_second: priceForm.points,
              estimate_default_seconds: priceForm.estimate_default_seconds,
            }
          : model.modality === 'image'
            ? { points_per_image: priceForm.points }
            : {
                input_points_per_1m: priceForm.points,
                output_points_per_1m: priceForm.output_points,
              };
      await setAdminAiModelPrice(model.id, {
        billing_type: billingType,
        price_config_json: priceConfig,
      });
      setPricingModelId(null);
      await reload();
      toast.success(model.modality === 'video' ? (billingType === 'per_call' ? '视频按次价格已更新' : '视频按秒价格已更新') : '模型价格已更新');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '定价失败');
    } finally {
      setBusy(false);
    }
  };

  const openUpstreamModels = () => {
    setUpstreamChannelId((current) => current || channels[0]?.id || 0);
    setUpstreamCandidates([]);
    setSelectedUpstreamKeys([]);
    setUpstreamModalOpen(true);
  };

  const discoverUpstreamModels = async () => {
    if (!upstreamChannelId) return;
    setDiscoveringModels(true);
    try {
      const result = await discoverAdminAiChannelModels(upstreamChannelId);
      setUpstreamCandidates(result.candidates);
      setSelectedUpstreamKeys(result.candidates.map((item) => item.key));
      toast.success(`已获取 ${result.upstream_count} 个上游模型`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '获取上游模型失败');
    } finally {
      setDiscoveringModels(false);
    }
  };

  const addSelectedUpstreamModels = async () => {
    const selected = upstreamCandidates.filter((item) => selectedUpstreamKeys.includes(item.key));
    if (!upstreamChannelId || !selected.length) return;
    setAddingModels(true);
    try {
      const result = await addAdminAiChannelModels(upstreamChannelId, selected);
      await reload();
      setUpstreamModalOpen(false);
      toast.success(`已添加 ${result.added.length} 个模型${result.existing.length ? `，跳过 ${result.existing.length} 个已有模型` : ''}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '添加模型失败');
    } finally {
      setAddingModels(false);
    }
  };

  const openPriceSync = () => {
    const preferredChannel = channels.find((channel) => (
      modelModalityFilter === 'all' || channel.modality === modelModalityFilter
    )) || channels[0];
    setPriceSyncChannelId(preferredChannel?.id || 0);
    setPriceSyncPreview(null);
    setSelectedPriceSyncModelIds([]);
    setPriceSyncModalOpen(true);
  };

  const previewPriceSync = async () => {
    if (!priceSyncChannelId) return;
    setPreviewingPrices(true);
    try {
      const result = await previewAdminAiChannelPrices(priceSyncChannelId);
      setPriceSyncPreview(result);
      setSelectedPriceSyncModelIds(
        result.items.filter((item) => item.status === 'ready').map((item) => item.model_id),
      );
    } catch (error) {
      setPriceSyncPreview(null);
      setSelectedPriceSyncModelIds([]);
      toast.error(error instanceof Error ? error.message : '获取上游定价失败');
    } finally {
      setPreviewingPrices(false);
    }
  };

  const applyPriceSync = async () => {
    if (!priceSyncPreview || !selectedPriceSyncModelIds.length) return;
    const accepted = await confirm({
      title: '同步模型定价',
      message: `将按 1 元 = ${formatPriceNumber(priceSyncPreview.yuan_to_points)} 积分，为 ${selectedPriceSyncModelIds.length} 个已有模型创建新价格版本。确认继续吗？`,
      confirmText: '确认同步',
    });
    if (!accepted) return;
    setApplyingPrices(true);
    try {
      const result = await syncAdminAiChannelPrices(priceSyncPreview.channel.id, {
        model_ids: selectedPriceSyncModelIds,
        expected_price_ids: Object.fromEntries(
          priceSyncPreview.items
            .filter((item) => selectedPriceSyncModelIds.includes(item.model_id))
            .map((item) => [String(item.model_id), item.current_price?.id ?? null]),
        ),
        expected_pricing_version: priceSyncPreview.upstream.pricing_version,
        expected_yuan_to_points: priceSyncPreview.yuan_to_points,
      });
      await reload();
      setPriceSyncModalOpen(false);
      toast.success(`已更新 ${result.updated.length} 个模型定价${result.unchanged.length ? `，${result.unchanged.length} 个无需变更` : ''}`);
    } catch (error) {
      setPriceSyncPreview(null);
      setSelectedPriceSyncModelIds([]);
      toast.error(error instanceof Error ? error.message : '同步模型定价失败');
    } finally {
      setApplyingPrices(false);
    }
  };

  const allUpstreamModelsSelected = upstreamCandidates.length > 0
    && selectedUpstreamKeys.length === upstreamCandidates.length;

  const toggleAllUpstreamModels = () => {
    setSelectedUpstreamKeys(
      allUpstreamModelsSelected ? [] : upstreamCandidates.map((candidate) => candidate.key),
    );
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (index + 1) % TABS.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (index - 1 + TABS.length) % TABS.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = TABS.length - 1;
    }
    if (nextIndex == null) return;
    event.preventDefault();
    const nextTab = TABS[nextIndex];
    setActiveTab(nextTab.key);
    window.requestAnimationFrame(() => {
      document.getElementById(`points-ai-tab-${nextTab.key}`)?.focus();
    });
  };

  const settingsInvalid =
    !settings ||
    !Number.isFinite(settings.yuan_to_points) ||
    settings.yuan_to_points <= 0 ||
    settings.yuan_to_points > 1_000_000_000 ||
    !Number.isFinite(settings.register_grant_amount) ||
    settings.register_grant_amount < 0;
  const selectedModelChannel = channels.find((channel) => channel.id === modelForm.channel_id);
  const selectedModelAdapter = getVideoModelCapabilitiesAdapter(
    modelForm.modality,
    selectedModelChannel?.adapter_type,
  );

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-5 p-2 sm:p-4">
      <header>
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-slate-950">积分与 AI 配置</h1>
          <p className="mt-1 text-sm text-slate-500">统一管理积分规则、充值套餐、上游渠道与模型计价。</p>
        </div>
      </header>

      <main className="overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_12px_30px_rgba(59,130,246,0.07)]">
        <div
          className="grid grid-cols-2 border-b border-[#d7e3f4] bg-slate-50/70 sm:grid-cols-4"
          role="tablist"
          aria-label="积分与 AI 配置分类"
        >
          {TABS.map((tab, index) => {
            const Icon = tab.icon;
            const selected = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                id={`points-ai-tab-${tab.key}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`points-ai-panel-${tab.key}`}
                tabIndex={selected ? 0 : -1}
                className={`relative flex min-h-12 items-center justify-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${
                  selected
                    ? 'border-blue-600 bg-white text-blue-700'
                    : 'border-transparent text-slate-500 hover:bg-white/70 hover:text-slate-800'
                }`}
                onClick={() => setActiveTab(tab.key)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {activeTab === 'settings' ? (
          <section
            id="points-ai-panel-settings"
            role="tabpanel"
            aria-labelledby="points-ai-tab-settings"
            className="p-4 sm:p-6"
          >
            <div className="mb-5">
              <h2 className="text-base font-semibold text-slate-900">积分规则</h2>
              <p className="mt-1 text-sm text-slate-500">设置人民币兑换比例和新用户注册赠送策略。</p>
            </div>
            {settings ? (
              <div className="max-w-4xl">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="1 元兑换积分" hint="积分 / 元">
                    <Input
                      type="number"
                      min="0.0001"
                      max="1000000000"
                      step="0.0001"
                      value={settings.yuan_to_points}
                      onChange={(event) =>
                        setSettings({ ...settings, yuan_to_points: Number(event.target.value) })
                      }
                    />
                  </Field>
                  <Field label="注册赠送数量" hint="积分">
                    <Input
                      type="number"
                      min="0"
                      step="0.0001"
                      value={settings.register_grant_amount}
                      onChange={(event) =>
                        setSettings({ ...settings, register_grant_amount: Number(event.target.value) })
                      }
                    />
                  </Field>
                </div>
                <div className="mt-5 divide-y divide-slate-100 border-y border-slate-200">
                  <label className="flex cursor-pointer items-center justify-between gap-4 py-3 text-sm">
                    <span>
                      <span className="block font-medium text-slate-800">开启注册赠送</span>
                      <span className="mt-0.5 block text-xs text-slate-500">新用户注册后自动发放上方积分。</span>
                    </span>
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-blue-600"
                      checked={settings.register_grant_enabled}
                      onChange={(event) =>
                        setSettings({ ...settings, register_grant_enabled: event.target.checked })
                      }
                    />
                  </label>
                  <label className="flex cursor-pointer items-center justify-between gap-4 py-3 text-sm">
                    <span>
                      <span className="block font-medium text-slate-800">启用积分双轨</span>
                      <span className="mt-0.5 block text-xs text-slate-500">同时支持平台积分与用户自备密钥。</span>
                    </span>
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-blue-600"
                      checked={settings.dual_track_enabled}
                      onChange={(event) =>
                        setSettings({ ...settings, dual_track_enabled: event.target.checked })
                      }
                    />
                  </label>
                  <label className="flex cursor-pointer items-center justify-between gap-4 py-3 text-sm">
                    <span>
                      <span className="block font-medium text-slate-800">允许所有用户填写 API Key</span>
                      <span className="mt-0.5 block text-xs text-slate-500">
                        开启后无需逐个授权；关闭后仅已单独授权的用户可使用自己的 Key。
                      </span>
                    </span>
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-blue-600"
                      checked={settings.allow_all_users_api_key_override}
                      onChange={(event) =>
                        setSettings({
                          ...settings,
                          allow_all_users_api_key_override: event.target.checked,
                        })
                      }
                    />
                  </label>
                </div>
                <Button
                  type="button"
                  className="mt-5 w-full sm:w-auto"
                  loading={busy}
                  icon={<Save size={15} />}
                  disabled={settingsInvalid}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const nextSettings = await saveAdminPointsSettings(settings);
                      setSettings(nextSettings);
                      toast.success('积分设置已保存');
                    } catch (error) {
                      toast.error(error instanceof Error ? error.message : '保存失败');
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  保存设置
                </Button>
              </div>
            ) : (
              <EmptyState>积分规则加载中</EmptyState>
            )}
          </section>
        ) : null}

        {activeTab === 'products' ? (
          <section
            id="points-ai-panel-products"
            role="tabpanel"
            aria-labelledby="points-ai-tab-products"
            className="grid min-w-0 lg:grid-cols-[minmax(0,1fr)_360px]"
          >
            <div className="min-w-0 p-4 sm:p-6">
              <div className="mb-4 flex items-end justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">套餐列表</h2>
                  <p className="mt-1 text-sm text-slate-500">已有订单的套餐删除时会自动转为下架。</p>
                </div>
                <span className="shrink-0 text-xs text-slate-400">共 {products.length} 项</span>
              </div>
              {products.length ? (
                <div className="divide-y divide-slate-100 border-y border-slate-200">
                  {products.map((product) => (
                    <div key={product.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="font-medium text-slate-900">{product.name}</span>
                          <span className="font-mono text-xs text-slate-400">{product.code}</span>
                          {product.is_recommended ? (
                            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">推荐</span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          ¥{product.price_cny} · {product.points} 积分
                          {product.bonus_points > 0 ? ` + 赠送 ${product.bonus_points}` : ''} ·{' '}
                          <StatusLabel active={product.is_visible} activeText="已上架" inactiveText="已下架" />
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<Pencil size={13} />} onClick={() => startProductEdit(product)}>
                          编辑
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          disabled={busy}
                          icon={product.is_visible ? <EyeOff size={13} /> : <Eye size={13} />}
                          onClick={async () => {
                            setBusy(true);
                            try {
                              await updateAdminPointsProduct(product.id, { is_visible: !product.is_visible });
                              await reload();
                            } catch (error) {
                              toast.error(error instanceof Error ? error.message : '更新失败');
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          {product.is_visible ? '下架' : '上架'}
                        </Button>
                        <Button
                          type="button"
                          variant="danger"
                          size="sm"
                          disabled={busy}
                          icon={<Trash2 size={13} />}
                          onClick={async () => {
                            const confirmed = await confirm({
                              title: '删除积分套餐',
                              message: `确定删除积分套餐“${product.name}”吗？`,
                              confirmText: '删除',
                              danger: true,
                            });
                            if (!confirmed) return;
                            setBusy(true);
                            try {
                              const result = await deleteAdminPointsProduct(product.id);
                              await reload();
                              toast.success(result.archived ? '套餐已有历史订单，已改为下架' : '积分套餐已删除');
                            } catch (error) {
                              toast.error(error instanceof Error ? error.message : '删除失败');
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          删除
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState>暂无积分套餐，请在右侧创建。</EmptyState>
              )}
            </div>

            <aside className="min-w-0 border-t border-[#d7e3f4] bg-slate-50/50 p-4 sm:p-6 lg:border-l lg:border-t-0">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-900">{editingProductId ? '编辑套餐' : '新增套餐'}</h3>
                {editingProductId ? (
                  <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<X size={13} />} onClick={resetProductForm}>
                    取消
                  </Button>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <Field label="套餐代码">
                  <Input value={productForm.code} placeholder="例如 starter_100" onChange={(event) => setProductForm({ ...productForm, code: event.target.value })} />
                </Field>
                <Field label="套餐名称">
                  <Input value={productForm.name} placeholder="例如 入门积分包" onChange={(event) => setProductForm({ ...productForm, name: event.target.value })} />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="售价" hint="元">
                    <Input type="number" min="0.01" step="0.01" value={productForm.price_cny} onChange={(event) => setProductForm({ ...productForm, price_cny: Number(event.target.value) })} />
                  </Field>
                  <Field label="基础积分">
                    <Input type="number" min="0.0001" step="0.0001" value={productForm.points} onChange={(event) => setProductForm({ ...productForm, points: Number(event.target.value) })} />
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="赠送积分">
                    <Input type="number" min="0" step="0.0001" value={productForm.bonus_points} onChange={(event) => setProductForm({ ...productForm, bonus_points: Number(event.target.value) })} />
                  </Field>
                  <Field label="排序">
                    <Input type="number" value={productForm.sort_order} onChange={(event) => setProductForm({ ...productForm, sort_order: Number(event.target.value) })} />
                  </Field>
                </div>
                <Field label="套餐说明">
                  <TextArea rows={3} value={productForm.description} placeholder="面向用户展示的套餐说明" onChange={(event) => setProductForm({ ...productForm, description: event.target.value })} />
                </Field>
                <div className="flex flex-wrap gap-x-5 gap-y-2 border-y border-slate-200 py-3 text-sm text-slate-700">
                  <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-blue-600" checked={productForm.is_visible} onChange={(event) => setProductForm({ ...productForm, is_visible: event.target.checked })} />上架</label>
                  <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-blue-600" checked={productForm.is_recommended} onChange={(event) => setProductForm({ ...productForm, is_recommended: event.target.checked })} />推荐</label>
                </div>
              </div>
              <Button
                type="button"
                className="mt-4 w-full"
                loading={busy}
                icon={editingProductId ? <Save size={15} /> : <Plus size={15} />}
                disabled={!productForm.code.trim() || !productForm.name.trim() || productForm.price_cny <= 0 || productForm.points <= 0}
                onClick={() => void saveProduct()}
              >
                {editingProductId ? '保存套餐' : '新增套餐'}
              </Button>
            </aside>
          </section>
        ) : null}

        {activeTab === 'channels' ? (
          <section
            id="points-ai-panel-channels"
            role="tabpanel"
            aria-labelledby="points-ai-tab-channels"
            className="grid min-w-0 lg:grid-cols-[minmax(0,1fr)_380px]"
          >
            <div className="min-w-0 p-4 sm:p-6">
              <div className="mb-4 flex items-end justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">渠道列表</h2>
                  <p className="mt-1 text-sm text-slate-500">管理平台统一使用的 AI 服务接入地址与密钥。</p>
                </div>
                <span className="shrink-0 text-xs text-slate-400">共 {channels.length} 项</span>
              </div>
              {channels.length ? (
                <div className="divide-y divide-slate-100 border-y border-slate-200">
                  {channels.map((channel) => (
                    <div key={channel.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="font-medium text-slate-900">{channel.name}</span>
                          <span className="font-mono text-xs text-slate-400">{channel.code}</span>
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{channel.modality}</span>
                          {channel.modality === 'video' ? (
                            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
                              {getVideoAdapterLabel(channel.adapter_type)}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 break-all text-xs text-slate-500">
                          {channel.base_url || '未设置 Base URL'} · Key {channel.has_platform_key ? `···${channel.last_four || ''}` : '未配置'}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<Pencil size={13} />} onClick={() => startChannelEdit(channel)}>
                          编辑
                        </Button>
                        <Button type="button" variant="danger" size="sm" disabled={busy} icon={<Trash2 size={13} />} onClick={() => void deleteChannel(channel)}>
                          删除
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState>暂无 AI 渠道，请在右侧创建。</EmptyState>
              )}
            </div>

            <aside className="min-w-0 border-t border-[#d7e3f4] bg-slate-50/50 p-4 sm:p-6 lg:border-l lg:border-t-0">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-900">{editingChannelId ? '编辑渠道' : '新增渠道'}</h3>
                {editingChannelId ? (
                  <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<X size={13} />} onClick={resetChannelForm}>
                    取消
                  </Button>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <Field label="渠道代码" hint={editingChannelId ? '创建后不可修改' : undefined}>
                  <Input disabled={Boolean(editingChannelId)} className="disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500" value={channelForm.code} placeholder="例如 deepseek" onChange={(event) => setChannelForm({ ...channelForm, code: event.target.value })} />
                </Field>
                <Field label="渠道名称">
                  <Input value={channelForm.name} placeholder="例如 DeepSeek" onChange={(event) => setChannelForm({ ...channelForm, name: event.target.value })} />
                </Field>
                <Field label="Base URL">
                  <Input value={channelForm.base_url} placeholder="https://.../v1" onChange={(event) => setChannelForm({ ...channelForm, base_url: event.target.value })} />
                </Field>
                <Field label="能力类型">
                  <Select value={channelForm.modality} onChange={(event) => setChannelForm({ ...channelForm, modality: event.target.value })}>
                    <option value="text">文本</option>
                    <option value="image">图片</option>
                    <option value="video">视频</option>
                  </Select>
                </Field>
                {channelForm.modality === 'video' ? (
                  <Field label="视频适配器预设" hint="仅填充草稿，可继续修改">
                    <Select
                      value={channelForm.adapter_type}
                      aria-label="视频适配器预设"
                      onChange={(event) => {
                        const adapterType = event.target.value;
                        if (!isVideoAdapterType(adapterType)) return;
                        const draft = applyVideoAdapterPreset(
                          {
                            adapterType: isVideoAdapterType(channelForm.adapter_type)
                              ? channelForm.adapter_type
                              : 'lingdong_video',
                            baseUrl: channelForm.base_url,
                            modelKey: '',
                            capabilities: {},
                          },
                          adapterType,
                        );
                        setChannelForm({
                          ...channelForm,
                          adapter_type: draft.adapterType,
                          base_url: draft.baseUrl,
                        });
                      }}
                    >
                      {!isVideoAdapterType(channelForm.adapter_type) ? (
                        <option value={channelForm.adapter_type} disabled>{getVideoAdapterLabel(channelForm.adapter_type)}</option>
                      ) : null}
                      {VIDEO_ADAPTER_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
                    </Select>
                  </Field>
                ) : null}
                <Field label="平台 API Key" hint={editingChannelId ? '留空则不修改' : undefined}>
                  <Input type="password" autoComplete="new-password" value={channelForm.platform_api_key} placeholder={editingChannelId ? '留空保留现有密钥' : '输入平台 API Key'} onChange={(event) => setChannelForm({ ...channelForm, platform_api_key: event.target.value })} />
                </Field>
                <Field label="渠道高级配置" hint="JSON">
                  <TextArea rows={5} value={channelForm.extra_config_json} className="font-mono text-xs" onChange={(event) => setChannelForm({ ...channelForm, extra_config_json: event.target.value })} />
                </Field>
              </div>
              <Button
                type="button"
                className="mt-4 w-full"
                loading={busy}
                icon={editingChannelId ? <Save size={15} /> : <Plus size={15} />}
                disabled={
                  !channelForm.code.trim() ||
                  !channelForm.name.trim() ||
                  (channelForm.modality === 'video' && !isVideoAdapterType(channelForm.adapter_type))
                }
                onClick={() => void saveChannel()}
              >
                {editingChannelId ? '保存渠道' : '新增渠道'}
              </Button>
            </aside>
          </section>
        ) : null}

        {activeTab === 'models' ? (
          <section
            id="points-ai-panel-models"
            role="tabpanel"
            aria-labelledby="points-ai-tab-models"
            className="grid min-w-0 lg:grid-cols-[minmax(0,1fr)_380px]"
          >
            <div className="min-w-0 p-4 sm:p-6">
              <div className="mb-4 flex flex-col items-start gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">模型目录</h2>
                  <p className="mt-1 text-sm text-slate-500">控制模型可见性，并按 Token、图片或视频秒数设置积分价。</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-slate-400">
                    {modelModalityFilter === 'all' ? `共 ${models.length} 项` : `${filteredModels.length} / ${models.length} 项`}
                  </span>
                  <Button type="button" variant="secondary" size="sm" disabled={busy || channels.length === 0} icon={<RefreshCw size={13} />} onClick={openPriceSync}>同步模型定价</Button>
                  <Button type="button" variant="secondary" size="sm" disabled={busy || channels.length === 0} icon={<DatabaseZap size={13} />} onClick={openUpstreamModels}>从上游获取模型</Button>
                </div>
              </div>
              <div className="mb-4 flex flex-wrap items-center gap-1 rounded-lg bg-slate-100 p-1" role="group" aria-label="按能力类型筛选模型">
                {MODEL_MODALITY_FILTERS.map((item) => {
                  const active = modelModalityFilter === item.value;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setModelModalityFilter(item.value)}
                      className={`inline-flex min-h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors ${active ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:bg-white/60 hover:text-slate-800'}`}
                    >
                      {item.label}
                      <span className={active ? 'text-blue-500' : 'text-slate-400'}>{modelModalityCounts[item.value]}</span>
                    </button>
                  );
                })}
              </div>
              {filteredModels.length ? (
                <div className="divide-y divide-slate-100 border-y border-slate-200">
                  {filteredModels.map((model) => (
                    <div key={model.id} className="py-3">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="font-medium text-slate-900">{model.display_name}</span>
                            {model.intro_tag ? <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">{model.intro_tag}</span> : null}
                            <span className="break-all font-mono text-xs text-slate-400">{model.model_key}</span>
                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{model.modality}</span>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">
                            <StatusLabel active={model.user_visible} activeText="用户可见" inactiveText="已隐藏" /> ·{' '}
                            {model.active_price ? formatModelPrice(model.active_price) : '未定价'}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={busy}
                            icon={model.user_visible ? <EyeOff size={13} /> : <Eye size={13} />}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                await updateAdminAiModel(model.id, { user_visible: !model.user_visible });
                                await reload();
                              } catch (error) {
                                toast.error(error instanceof Error ? error.message : '更新失败');
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            {model.user_visible ? '隐藏' : '上架'}
                          </Button>
                          <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<Tags size={13} />} onClick={() => startPriceEdit(model)}>
                            定价
                          </Button>
                          <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<Pencil size={13} />} onClick={() => startModelEdit(model)}>
                            编辑
                          </Button>
                          {model.modality === 'video' || model.modality === 'image' ? (
                            <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<Pencil size={13} />} onClick={() => startCapabilitiesEdit(model)}>
                              {model.modality === 'image' ? '质量' : '参数'}
                            </Button>
                          ) : null}
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={busy}
                            icon={<Trash2 size={13} />}
                            onClick={async () => {
                              const accepted = await confirm({
                                title: '删除模型',
                                message: `确认删除模型“${model.display_name}”吗？若它仍被默认配置或任务引用，系统会阻止删除。`,
                                confirmText: '删除',
                                danger: true,
                              });
                              if (!accepted) return;
                              setBusy(true);
                              try {
                                await deleteAdminAiModel(model.id);
                                if (editingModelId === model.id) resetModelForm();
                                await reload();
                                toast.success('模型已删除');
                              } catch (error) {
                                toast.error(error instanceof Error ? error.message : '删除模型失败');
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            删除
                          </Button>
                        </div>
                      </div>

                      {pricingModelId === model.id ? (
                        <div className="mt-3 flex flex-col gap-3 border-l-2 border-blue-500 bg-blue-50/60 p-3 sm:flex-row sm:items-end">
                          <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
                            {model.modality === 'video' ? (
                              <Field label="计价方式" hint="固定时长、整条按次收费的模型选「按次」">
                                <Select value={priceForm.billing_type === 'per_call' ? 'per_call' : 'per_second'} onChange={(event) => setPriceForm({ ...priceForm, billing_type: event.target.value })}>
                                  <option value="per_second">按秒计价（时长 × 单价）</option>
                                  <option value="per_call">按次计价（每个视频固定价）</option>
                                </Select>
                              </Field>
                            ) : null}
                            <Field label={model.modality === 'video' ? priceForm.billing_type === 'per_call' ? '每次积分价' : '每秒积分价' : model.modality === 'image' ? '每张积分价' : '每百万输入 Token 积分价'}>
                              <Input type="number" min="0" step="0.0001" value={priceForm.points} onChange={(event) => setPriceForm({ ...priceForm, points: Number(event.target.value) })} />
                            </Field>
                            {model.modality === 'text' ? (
                              <Field label="每百万输出 Token 积分价">
                                <Input type="number" min="0" step="0.0001" value={priceForm.output_points} onChange={(event) => setPriceForm({ ...priceForm, output_points: Number(event.target.value) })} />
                              </Field>
                            ) : null}
                            {model.modality === 'video' && priceForm.billing_type !== 'per_call' ? (
                              <Field label="默认估算时长" hint="秒">
                                <Input type="number" min="1" step="1" value={priceForm.estimate_default_seconds} onChange={(event) => setPriceForm({ ...priceForm, estimate_default_seconds: Number(event.target.value) })} />
                              </Field>
                            ) : null}
                          </div>
                          <div className="flex shrink-0 gap-2">
                            <Button
                              type="button"
                              size="sm"
                              loading={busy}
                              icon={<Save size={13} />}
                              disabled={
                                !Number.isFinite(priceForm.points) ||
                                priceForm.points < 0 ||
                                (model.modality === 'text' &&
                                  (!Number.isFinite(priceForm.output_points) || priceForm.output_points < 0)) ||
                                (model.modality === 'video' && priceForm.billing_type !== 'per_call' &&
                                  (!Number.isFinite(priceForm.estimate_default_seconds) ||
                                    priceForm.estimate_default_seconds < 1))
                              }
                              onClick={() => void saveModelPrice(model)}
                            >
                              保存价格
                            </Button>
                            <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<X size={13} />} onClick={() => setPricingModelId(null)}>
                              取消
                            </Button>
                          </div>
                        </div>
                      ) : null}
                      {capabilitiesModelId === model.id ? (
                        <div className="mt-3 border-l-2 border-violet-500 bg-violet-50/60 p-3">
                          <Field label={model.modality === 'image' ? '图片质量配置' : '视频参数配置'} hint={model.modality === 'image' ? '仅允许默认质量与可选质量' : '仅允许受支持 profile 和能力字段'}>
                            <TextArea rows={16} value={capabilitiesDraft} className="font-mono text-xs" onChange={(event) => setCapabilitiesDraft(event.target.value)} />
                          </Field>
                          {model.modality === 'image' ? (
                            <div className="mt-3 grid max-w-xl gap-3 sm:grid-cols-2">
                              <Field label="默认质量">
                                <Select value={getImageQualityDraft(capabilitiesDraft)} onChange={(event) => setCapabilitiesDraft(setImageQualityDraft(capabilitiesDraft, event.target.value))}>
                                  {IMAGE_QUALITY_OPTIONS.map((quality) => <option key={quality} value={quality}>{quality}</option>)}
                                </Select>
                              </Field>
                            </div>
                          ) : null}
                          <div className="mt-3 flex gap-2">
                            <Button type="button" size="sm" loading={busy} icon={<Save size={13} />} onClick={() => void saveCapabilities(model)}>保存参数</Button>
                            <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<X size={13} />} onClick={() => setCapabilitiesModelId(null)}>取消</Button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState>
                  {models.length ? `暂无${MODEL_MODALITY_FILTERS.find((item) => item.value === modelModalityFilter)?.label || ''}模型` : '暂无模型，请先创建 AI 渠道。'}
                </EmptyState>
              )}
            </div>

            <aside className="min-w-0 border-t border-[#d7e3f4] bg-slate-50/50 p-4 sm:p-6 lg:border-l lg:border-t-0">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-900">{editingModelId ? '编辑模型' : '新增模型'}</h3>
                {editingModelId ? <Button type="button" variant="secondary" size="sm" disabled={busy} icon={<X size={13} />} onClick={resetModelForm}>取消</Button> : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <Field label="所属渠道">
                  <Select disabled={Boolean(editingModelId)} value={modelForm.channel_id} onChange={(event) => {
                    const channelId = Number(event.target.value);
                    const channel = channels.find((item) => item.id === channelId);
                    setSelectedVideoPreset('');
                    const modality = channel?.modality || modelForm.modality;
                    setModelForm({
                      ...modelForm,
                      channel_id: channelId,
                      modality,
                      initial_points: defaultPointsForModality(modality),
                      initial_output_points: defaultPointsForModality(modality),
                      capabilities_json: modality === 'image' ? JSON.stringify(DEFAULT_IMAGE_CAPABILITIES, null, 2) : modelForm.capabilities_json,
                    });
                  }}>
                    {!channels.length ? <option value={0}>暂无可用渠道</option> : null}
                    {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
                  </Select>
                </Field>
                {modelForm.modality === 'video' && selectedModelAdapter ? (
                  <Field label="应用视频参数预设" hint="仅填充参数草稿，可继续修改">
                    <Select
                      value={selectedVideoPreset}
                      aria-label="应用视频参数预设"
                      onChange={(event) => {
                        if (event.target.value === 'custom') {
                          setSelectedVideoPreset('custom');
                          return;
                        }
                        if (!isVideoAdapterType(event.target.value)) return;
                        setSelectedVideoPreset(event.target.value);
                        const draft = applyVideoModelCapabilitiesPreset(
                          {
                            channelId: modelForm.channel_id,
                            channelBaseUrl: selectedModelChannel?.base_url || '',
                            modelKey: modelForm.model_key,
                            capabilities: {},
                          },
                          event.target.value,
                        );
                        setModelForm({
                          ...modelForm,
                          capabilities_json: JSON.stringify(draft.capabilities, null, 2),
                        });
                      }}
                    >
                      <option value="">请选择视频参数预设</option>
                      <option value="custom">自定义参数配置</option>
                      {VIDEO_ADAPTER_PRESETS.map((preset) => (
                        <option key={preset.id} value={preset.id}>{preset.label}</option>
                      ))}
                    </Select>
                  </Field>
                ) : null}
                <Field label="模型标识">
                  <Input disabled={Boolean(editingModelId)} value={modelForm.model_key} placeholder="例如 deepseek-chat" onChange={(event) => setModelForm({ ...modelForm, model_key: event.target.value })} />
                </Field>
                <Field label="显示名称" hint="留空使用模型标识">
                  <Input value={modelForm.display_name} placeholder="面向用户展示的名称" onChange={(event) => setModelForm({ ...modelForm, display_name: event.target.value })} />
                </Field>
                <Field label="介绍标签" hint={`${modelForm.intro_tag.length}/80`}>
                  <Input maxLength={80} value={modelForm.intro_tag} placeholder="例如：高性价比、长视频、细节出色" onChange={(event) => setModelForm({ ...modelForm, intro_tag: event.target.value })} />
                </Field>
                <Field label="能力类型">
                  <Select disabled={Boolean(editingModelId)} value={modelForm.modality} onChange={(event) => {
                    setSelectedVideoPreset('');
                    setModelForm({
                      ...modelForm,
                      modality: event.target.value,
                      initial_points: defaultPointsForModality(event.target.value),
                      initial_output_points: defaultPointsForModality(event.target.value),
                    });
                  }}>
                    <option value="text">文本</option>
                    <option value="image">图片</option>
                    <option value="video">视频</option>
                  </Select>
                </Field>
                {modelForm.modality === 'image' ? (
                  <>
                    <Field label="默认质量" hint="将优先覆盖平台默认质量">
                      <Select value={getImageQualityDraft(modelForm.capabilities_json)} onChange={(event) => setModelForm({ ...modelForm, capabilities_json: setImageQualityDraft(modelForm.capabilities_json, event.target.value) })}>
                        {IMAGE_QUALITY_OPTIONS.map((quality) => <option key={quality} value={quality}>{quality}</option>)}
                      </Select>
                    </Field>
                    <Field label="图片质量配置" hint="JSON，可继续调整可选质量">
                      <TextArea rows={12} value={modelForm.capabilities_json} className="font-mono text-xs" onChange={(event) => setModelForm({ ...modelForm, capabilities_json: event.target.value })} />
                    </Field>
                  </>
                ) : modelForm.modality === 'video' ? (
                  <Field label="视频参数配置" hint="JSON，可在预设后继续修改">
                    <TextArea
                      rows={12}
                      value={modelForm.capabilities_json}
                      className="font-mono text-xs"
                      onChange={(event) => setModelForm({ ...modelForm, capabilities_json: event.target.value })}
                    />
                  </Field>
                ) : null}
                {!editingModelId ? (
                  <>
                    {modelForm.modality === 'video' ? (
                      <Field label="计价方式" hint="固定时长、整条按次收费的模型选「按次」">
                        <Select value={modelForm.video_billing_type} onChange={(event) => setModelForm({ ...modelForm, video_billing_type: event.target.value })}>
                          <option value="per_second">按秒计价（时长 × 单价）</option>
                          <option value="per_call">按次计价（每个视频固定价）</option>
                        </Select>
                      </Field>
                    ) : null}
                    <Field
                      label={modelForm.modality === 'text' ? '初始输入积分价' : '初始积分价'}
                      hint={modelForm.modality === 'video' ? (modelForm.video_billing_type === 'per_call' ? '积分 / 次' : '积分 / 秒') : modelForm.modality === 'image' ? '积分 / 张' : '积分 / 百万输入 Token'}
                    >
                      <Input type="number" min="0" step="0.0001" value={modelForm.initial_points} onChange={(event) => setModelForm({ ...modelForm, initial_points: Number(event.target.value) })} />
                    </Field>
                    {modelForm.modality === 'text' ? (
                      <Field label="初始输出积分价" hint="积分 / 百万输出 Token">
                        <Input type="number" min="0" step="0.0001" value={modelForm.initial_output_points} onChange={(event) => setModelForm({ ...modelForm, initial_output_points: Number(event.target.value) })} />
                      </Field>
                    ) : null}
                  </>
                ) : null}
                <Field label="排序">
                  <Input type="number" value={modelForm.sort_order} onChange={(event) => setModelForm({ ...modelForm, sort_order: Number(event.target.value) })} />
                </Field>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="h-4 w-4 accent-blue-600" checked={modelForm.user_visible} onChange={(event) => setModelForm({ ...modelForm, user_visible: event.target.checked })} />用户可见</label>
              </div>
              <Button
                type="button"
                className="mt-4 w-full"
                loading={busy}
                icon={editingModelId ? <Save size={15} /> : <Plus size={15} />}
                disabled={
                  !modelForm.channel_id ||
                  !modelForm.model_key.trim() ||
                  !Number.isFinite(modelForm.initial_points) ||
                  modelForm.initial_points < 0 ||
                  (modelForm.modality === 'text' &&
                    (!Number.isFinite(modelForm.initial_output_points) || modelForm.initial_output_points < 0))
                }
                onClick={async () => {
                  setBusy(true);
                  try {
                    if (editingModelId) {
                      const capabilities = modelForm.modality === 'video' || modelForm.modality === 'image'
                        ? (() => {
                            const value: unknown = JSON.parse(modelForm.capabilities_json);
                            if (!isRecord(value)) {
                              throw new Error(`${modelForm.modality === 'image' ? '图片质量' : '视频'}参数配置必须是 JSON 对象`);
                            }
                            return value;
                          })()
                        : undefined;
                      await updateAdminAiModel(editingModelId, {
                        display_name: modelForm.display_name || modelForm.model_key,
                        intro_tag: modelForm.intro_tag,
                        sort_order: modelForm.sort_order,
                        user_visible: modelForm.user_visible,
                        ...(capabilities ? { capabilities_json: capabilities } : {}),
                      });
                      resetModelForm();
                      await reload();
                      toast.success('模型已更新');
                      return;
                    }
                    const initialModality = modelForm.modality;
                    const initialPoints = modelForm.initial_points;
                    const initialOutputPoints = modelForm.initial_output_points;
                    const initialUserVisible = modelForm.user_visible;
                    const initialCapabilities = initialModality === 'video' || initialModality === 'image'
                      ? (() => {
                          const value: unknown = JSON.parse(modelForm.capabilities_json);
                          if (!isRecord(value)) {
                            throw new Error(`${initialModality === 'image' ? '图片质量' : '视频'}参数配置必须是 JSON 对象`);
                          }
                          return value;
                        })()
                      : undefined;
                    const model = await createAdminAiModel({
                      channel_id: modelForm.channel_id,
                      model_key: modelForm.model_key,
                      display_name: modelForm.display_name || modelForm.model_key,
                      intro_tag: modelForm.intro_tag,
                      modality: initialModality,
                      enabled: true,
                      user_visible: false,
                      ...(initialCapabilities ? { capabilities_json: initialCapabilities } : {}),
                    });
                    const billingType =
                      initialModality === 'video'
                        ? modelForm.video_billing_type === 'per_call' ? 'per_call' : 'per_second'
                        : initialModality === 'image'
                          ? 'per_image'
                          : 'per_1m_tokens';
                    const priceConfig =
                      initialModality === 'video'
                        ? billingType === 'per_call'
                          ? { points_per_call: initialPoints }
                          : {
                              points_per_second: initialPoints,
                              estimate_default_seconds: 15,
                            }
                        : initialModality === 'image'
                          ? { points_per_image: initialPoints }
                          : {
                              input_points_per_1m: initialPoints,
                              output_points_per_1m: initialOutputPoints,
                            };
                    try {
                      await setAdminAiModelPrice(model.id, {
                        billing_type: billingType,
                        price_config_json: priceConfig,
                      });
                    } catch (priceError) {
                      await reload().catch(() => undefined);
                      setPricingModelId(model.id);
                      setPriceForm({
                        billing_type: billingType,
                        points: initialPoints,
                        output_points: initialOutputPoints,
                        estimate_default_seconds: 15,
                      });
                      toast.error(
                        priceError instanceof Error
                          ? `模型已创建，但初始定价失败：${priceError.message}`
                          : '模型已创建，但初始定价失败，请在列表中补充价格',
                      );
                      return;
                    }
                    await updateAdminAiModel(model.id, { user_visible: initialUserVisible });
                    resetModelForm();
                    await reload();
                    toast.success('模型已创建');
                  } catch (error) {
                    toast.error(error instanceof Error ? error.message : '创建失败');
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {editingModelId ? '保存模型' : '新增模型'}
              </Button>
            </aside>
          </section>
        ) : null}

        {upstreamModalOpen ? (
          <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm" onMouseDown={() => { if (!discoveringModels && !addingModels) setUpstreamModalOpen(false); }}>
            <section role="dialog" aria-modal="true" aria-label="从上游获取模型" className="flex max-h-[min(720px,calc(100vh-2rem))] w-full max-w-2xl flex-col overflow-hidden rounded-lg bg-white shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
              <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">从上游获取模型</h2>
                  <p className="mt-1 text-xs text-slate-500">获取后勾选需要添加到本地模型目录的项目。</p>
                </div>
                <Button type="button" variant="secondary" size="sm" disabled={discoveringModels || addingModels} icon={<X size={13} />} onClick={() => setUpstreamModalOpen(false)}>关闭</Button>
              </div>
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                  <div className="min-w-0 flex-1">
                    <Field label="上游渠道">
                      <Select value={upstreamChannelId} onChange={(event) => { setUpstreamChannelId(Number(event.target.value)); setUpstreamCandidates([]); setSelectedUpstreamKeys([]); }}>
                        {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name} · {channel.modality}</option>)}
                      </Select>
                    </Field>
                  </div>
                  <Button type="button" loading={discoveringModels} disabled={!upstreamChannelId || addingModels} icon={<DatabaseZap size={14} />} onClick={() => void discoverUpstreamModels()}>获取列表</Button>
                </div>
                {upstreamCandidates.length ? (
                  <div className="divide-y divide-slate-100 border-y border-slate-200">
                    {upstreamCandidates.map((candidate) => {
                      const checked = selectedUpstreamKeys.includes(candidate.key);
                      return <label key={candidate.key} className="flex cursor-pointer items-center gap-3 px-1 py-3 text-sm text-slate-700">
                        <input type="checkbox" className="h-4 w-4 accent-blue-600" checked={checked} onChange={() => setSelectedUpstreamKeys((previous) => checked ? previous.filter((key) => key !== candidate.key) : [...previous, candidate.key])} />
                        <span className="min-w-0 flex-1"><span className="block font-medium text-slate-900">{candidate.display_name}</span><span className="block break-all font-mono text-xs text-slate-400">{candidate.key}</span></span>
                      </label>;
                    })}
                  </div>
                ) : (
                  <div className="border-y border-dashed border-slate-200 py-12 text-center text-sm text-slate-400">选择渠道后获取上游模型列表</div>
                )}
              </div>
              <div className="flex items-center justify-between border-t border-slate-200 px-5 py-4">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500">已选择 {selectedUpstreamKeys.length} 项</span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    disabled={!upstreamCandidates.length || discoveringModels || addingModels}
                    icon={allUpstreamModelsSelected ? <Square size={13} /> : <SquareCheckBig size={13} />}
                    onClick={toggleAllUpstreamModels}
                  >
                    {allUpstreamModelsSelected ? '取消全选' : '全选'}
                  </Button>
                </div>
                <div className="flex gap-2">
                  <Button type="button" variant="secondary" size="sm" disabled={discoveringModels || addingModels} onClick={() => setUpstreamModalOpen(false)}>取消</Button>
                  <Button type="button" size="sm" loading={addingModels} disabled={!selectedUpstreamKeys.length || discoveringModels} icon={<Plus size={13} />} onClick={() => void addSelectedUpstreamModels()}>添加选中模型</Button>
                </div>
              </div>
            </section>
          </div>
        ) : null}

        {priceSyncModalOpen ? (
          <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm" onMouseDown={() => { if (!previewingPrices && !applyingPrices) setPriceSyncModalOpen(false); }}>
            <section role="dialog" aria-modal="true" aria-label="同步模型定价" className="flex max-h-[min(760px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
              <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">同步模型定价</h2>
                  <p className="mt-1 text-xs text-slate-500">只同步当前渠道已加入模型目录的项目；文本缓存价格不会参与换算。</p>
                </div>
                <Button type="button" variant="secondary" size="sm" disabled={previewingPrices || applyingPrices} icon={<X size={13} />} onClick={() => setPriceSyncModalOpen(false)}>关闭</Button>
              </div>
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                  <div className="min-w-0 flex-1">
                    <Field label="上游渠道">
                      <Select value={priceSyncChannelId} onChange={(event) => { setPriceSyncChannelId(Number(event.target.value)); setPriceSyncPreview(null); setSelectedPriceSyncModelIds([]); }}>
                        {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name} · {channel.modality}</option>)}
                      </Select>
                    </Field>
                  </div>
                  <Button type="button" loading={previewingPrices} disabled={!priceSyncChannelId || applyingPrices} icon={<RefreshCw size={14} />} onClick={() => void previewPriceSync()}>获取定价预览</Button>
                </div>

                {priceSyncPreview ? (
                  <>
                    <div className="grid gap-3 border-y border-blue-100 bg-blue-50/60 px-3 py-3 text-sm sm:grid-cols-3">
                      <div><span className="block text-xs text-slate-500">当前积分兑换</span><span className="font-semibold text-slate-900">1 元 = {formatPriceNumber(priceSyncPreview.yuan_to_points)} 积分</span></div>
                      <div><span className="block text-xs text-slate-500">积分人民币价值</span><span className="font-semibold text-slate-900">1 积分 = ¥{formatPriceNumber(priceSyncPreview.yuan_per_point)}</span></div>
                      <div><span className="block text-xs text-slate-500">上游计价组</span><span className="font-semibold text-slate-900">{priceSyncPreview.upstream.group} × {formatPriceNumber(priceSyncPreview.upstream.group_ratio)}</span></div>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
                      <span>已有模型 {priceSyncPreview.summary.total}</span>
                      <span className="text-blue-700">可更新 {priceSyncPreview.summary.ready}</span>
                      <span className="text-emerald-700">无需变更 {priceSyncPreview.summary.unchanged}</span>
                      <span>跳过 {priceSyncPreview.summary.skipped}</span>
                    </div>
                    <div className="divide-y divide-slate-100 border-y border-slate-200">
                      {priceSyncPreview.items.map((item) => {
                        const selectable = item.status === 'ready';
                        const checked = selectedPriceSyncModelIds.includes(item.model_id);
                        return (
                          <label key={item.model_id} className={`flex gap-3 px-1 py-3 text-sm ${selectable ? 'cursor-pointer' : 'cursor-default'}`}>
                            <input
                              type="checkbox"
                              className="mt-0.5 h-4 w-4 shrink-0 accent-blue-600"
                              disabled={!selectable || applyingPrices}
                              checked={checked}
                              onChange={() => setSelectedPriceSyncModelIds((previous) => checked ? previous.filter((id) => id !== item.model_id) : [...previous, item.model_id])}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <span className="font-medium text-slate-900">{item.display_name}</span>
                                <span className="font-mono text-xs text-slate-400">{item.model_key}</span>
                                <span className={`text-xs ${item.status === 'ready' ? 'text-blue-700' : item.status === 'unchanged' ? 'text-emerald-700' : 'text-slate-400'}`}>
                                  {item.status === 'ready' ? '可更新' : item.status === 'unchanged' ? '无需变更' : '已跳过'}
                                </span>
                              </span>
                              {item.proposed_price ? (
                                <span className="mt-1 grid gap-1 text-xs text-slate-500 sm:grid-cols-2">
                                  <span>当前：{formatModelPrice(item.current_price)}</span>
                                  <span>建议：{formatModelPrice(item.proposed_price)}</span>
                                  <span className="sm:col-span-2">上游：{formatUpstreamPrice(item.upstream_price, item.modality)}{item.cache_ignored ? ' · 已忽略缓存价' : ''}</span>
                                </span>
                              ) : (
                                <span className="mt-1 block text-xs text-slate-400">{item.reason || '上游价格类型与当前模型计费方式不兼容'}</span>
                              )}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </>
                ) : (
                  <div className="border-y border-dashed border-slate-200 py-12 text-center text-sm text-slate-400">选择渠道后获取定价预览</div>
                )}
              </div>
              <div className="flex flex-col gap-3 border-t border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-xs text-slate-500">已选择 {selectedPriceSyncModelIds.length} 个待更新模型</span>
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="secondary" size="sm" disabled={previewingPrices || applyingPrices} onClick={() => setPriceSyncModalOpen(false)}>取消</Button>
                  <Button type="button" size="sm" loading={applyingPrices} disabled={!priceSyncPreview || !selectedPriceSyncModelIds.length || previewingPrices} icon={<Save size={13} />} onClick={() => void applyPriceSync()}>应用选中定价</Button>
                </div>
              </div>
            </section>
          </div>
        ) : null}
      </main>
    </div>
  );
}
