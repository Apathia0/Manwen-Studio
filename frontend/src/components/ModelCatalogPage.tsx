import { useCallback, useEffect, useMemo, useState, type ComponentType } from 'react';
import { CircleDollarSign, FileImage, RefreshCw, Sparkles, Type, Video } from 'lucide-react';
import {
  getAiModels,
  getPublicAiModels,
  type PublicAiModelItem as AiModelItem,
} from '../api';
import { toast } from '../lib/toast';
import { Button } from './ui';

type ModelModality = 'text' | 'image' | 'video';

type ModalityConfig = {
  key: ModelModality;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
};

const MODALITIES: ModalityConfig[] = [
  { key: 'text', label: '文本模型', icon: Type },
  { key: 'image', label: '图片模型', icon: FileImage },
  { key: 'video', label: '视频模型', icon: Video },
];

const NUMBER_FORMATTER = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 });

function formatNumber(value: unknown): string | null {
  return typeof value === 'number' && Number.isFinite(value) ? NUMBER_FORMATTER.format(value) : null;
}

function getPriceLines(model: AiModelItem): string[] {
  const price = model.price;
  if (!price) return ['平台积分价待配置'];
  const config = price.price_config;
  if (price.billing_type === 'per_1m_tokens') {
    const legacy = formatNumber(config.points_per_1m_tokens);
    const input = formatNumber(config.input_points_per_1m) || legacy;
    const output = formatNumber(config.output_points_per_1m) || legacy;
    return [
      input ? `输入 ${input} 积分 / 百万 Token` : '按输入 Token 计费',
      output ? `输出 ${output} 积分 / 百万 Token` : '按输出 Token 计费',
    ];
  }
  if (price.billing_type === 'per_image') {
    const points = formatNumber(config.points_per_image);
    return [points ? `${points} 积分 / 张` : '按图片张数计费'];
  }
  if (price.billing_type === 'per_second') {
    const points = formatNumber(config.points_per_second);
    const estimated = formatNumber(model.estimated_points);
    return [
      points ? `${points} 积分 / 秒` : '按视频时长计费',
      estimated ? `默认参数预计 ${estimated} 积分` : '',
    ].filter(Boolean);
  }
  const estimated = formatNumber(model.estimated_points);
  if (price.billing_type === 'per_call' && model.modality === 'video') {
    const points = formatNumber(config.points_per_call) || estimated;
    const allowed = model.video_capabilities?.limits?.duration_seconds?.allowed;
    const fixedSeconds = allowed?.length === 1 ? `（固定 ${allowed[0]} 秒）` : '';
    return [points ? `${points} 积分 / 次${fixedSeconds}` : '按次计费', '不论时长，每个视频按次收费'];
  }
  return [estimated ? `预计 ${estimated} 积分 / 次` : '按实际用量计费'];
}

function getCapabilityItems(model: AiModelItem): string[] {
  if (model.modality === 'text') return ['小说创作', '剧本生成', 'AI 对话'];
  if (model.modality === 'image') {
    const qualities = model.image_capabilities?.limits?.qualities || [];
    const defaultQuality = model.image_capabilities?.defaults?.quality;
    const result = qualities.length ? [`质量：${qualities.join(' / ')}`] : ['图片生成'];
    if (defaultQuality) result.push(`默认质量：${defaultQuality}`);
    return result;
  }
  const capabilities = model.video_capabilities;
  const result: string[] = [];
  const modeLabels: Record<string, string> = { text_to_video: '文生视频', image_to_video: '图生视频' };
  const inputModes = capabilities?.input_modes?.map((item) => modeLabels[item] || item) || [];
  if (inputModes.length) result.push(inputModes.join(' / '));
  if (capabilities?.limits?.resolutions?.length) result.push(`分辨率：${capabilities.limits.resolutions.join(' / ')}`);
  if (capabilities?.limits?.aspect_ratios?.length) result.push(`画幅：${capabilities.limits.aspect_ratios.join(' / ')}`);
  const duration = capabilities?.limits?.duration_seconds;
  if (duration?.allowed?.length) result.push(`时长：${duration.allowed.join(' / ')} 秒`);
  else if (duration?.min != null || duration?.max != null) result.push(`时长：${duration.min ?? 1}-${duration.max ?? '不限'} 秒`);
  if (capabilities?.limits?.max_reference_images != null) result.push(`参考图：最多 ${capabilities.limits.max_reference_images} 张`);
  return result.length ? result : ['视频生成'];
}

export function ModelCatalogPage({ publicMode = false }: { publicMode?: boolean }) {
  const [models, setModels] = useState<AiModelItem[]>([]);
  const [activeModality, setActiveModality] = useState<ModelModality>('text');
  const [loading, setLoading] = useState(true);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    try {
      // 未登录访客走公开接口，已登录用户沿用原接口
      const modelResult = publicMode ? await getPublicAiModels() : await getAiModels();
      setModels(modelResult.models || []);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '模型目录加载失败');
    } finally {
      setLoading(false);
    }
  }, [publicMode]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const counts = useMemo(() => {
    const result: Record<ModelModality, number> = { text: 0, image: 0, video: 0 };
    for (const model of models) {
      if (model.modality === 'text' || model.modality === 'image' || model.modality === 'video') result[model.modality] += 1;
    }
    return result;
  }, [models]);

  const visibleModels = useMemo(
    () => models.filter((model) => model.modality === activeModality),
    [activeModality, models],
  );
  const modalityConfig = MODALITIES.find((item) => item.key === activeModality) || MODALITIES[0];

  return (
    <div className="mx-auto w-full max-w-7xl">
      <div className="flex flex-col gap-4 border-b border-slate-200 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
            <Sparkles size={16} aria-hidden="true" />
            AI 模型广场
          </div>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">模型能力与定价</h2>
          <p className="mt-1 text-sm text-slate-500">浏览平台已上架模型的介绍、能力参数与积分价格。</p>
        </div>
        <Button type="button" variant="secondary" className="max-md:min-h-[44px]" icon={<RefreshCw size={14} />} loading={loading} onClick={() => void loadCatalog()}>
          刷新
        </Button>
      </div>

      <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="模型能力类型">
        {MODALITIES.map((item) => {
          const Icon = item.icon;
          const active = item.key === activeModality;
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveModality(item.key)}
              className={`max-md:min-h-[44px] inline-flex h-10 items-center gap-2 rounded-md border px-4 text-sm font-medium transition-colors ${active ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-700'}`}
            >
              <Icon size={16} aria-hidden="true" />
              {item.label}
              <span className={active ? 'text-blue-100' : 'text-slate-400'}>{counts[item.key]}</span>
            </button>
          );
        })}
      </div>

      {loading && !models.length ? (
        <div className="mt-5 border-y border-slate-200 py-16 text-center text-sm text-slate-500">正在加载模型目录...</div>
      ) : visibleModels.length ? (
        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          {visibleModels.map((model) => {
            return (
              <article key={model.id} className="flex min-h-52 flex-col rounded-lg border border-slate-200 bg-white p-5 shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-slate-950">{model.display_name}</h3>
                      {model.intro_tag ? <span className="rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">{model.intro_tag}</span> : null}
                    </div>
                    <div className="mt-1 break-all font-mono text-xs text-slate-400">{model.model_key}</div>
                  </div>
                </div>

                <div className="mt-5 grid flex-1 gap-5 sm:grid-cols-[minmax(0,1fr)_minmax(180px,0.8fr)]">
                  <div>
                    <div className="text-xs font-semibold text-slate-500">能力</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {getCapabilityItems(model).map((item) => (
                        <span key={item} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs leading-5 text-slate-600">{item}</span>
                      ))}
                    </div>
                  </div>
                  <div className="border-t border-slate-100 pt-4 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">
                      <CircleDollarSign size={14} aria-hidden="true" />平台定价
                    </div>
                    <div className="mt-2 space-y-1 text-sm font-medium text-slate-800">
                      {getPriceLines(model).map((line) => <div key={line}>{line}</div>)}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="mt-5 border-y border-dashed border-slate-300 py-16 text-center text-sm text-slate-500">暂无已上架的{modalityConfig.label}</div>
      )}
    </div>
  );
}
