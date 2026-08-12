import {
  AlertCircle,
  Bot,
  Check,
  ChevronDown,
  Clipboard,
  Clock3,
  Download,
  Film,
  Image as ImageIcon,
  Images,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
  Video,
  X,
} from 'lucide-react';
import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  apiHeaders,
  analyzeCreationStudioAssets,
  cancelCreationStudioJob,
  createCreationStudioJobs,
  deleteCreationStudioAsset,
  deleteCreationStudioJob,
  estimateAiPoints,
  getAiModels,
  getAiPreferences,
  listCreationStudioAssets,
  listCreationStudioJobs,
  retryCreationStudioJob,
  uploadCreationStudioAsset,
  type AiModelItem,
  type CreationStudioAsset,
  type CreationStudioJob,
  type CreationStudioMediaKind,
} from '../api';
import { toast } from '../lib/toast';
import { normalizeErrorMessage } from '../lib/errors';
import ImageZoomView from './shared/ImageZoomView';
import MediaImage from './shared/MediaImage';

const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));

interface CreationStudioPageProps {
  /** 作品上下文仅用于助手增强，不参与创作台生成与记录归属。 */
  storyId?: number;
  chapterId?: number;
  storyTitle?: string;
  chapterTitle?: string;
}

const ACTIVE_STATUSES = new Set(['queued', 'running', 'cancel_requested']);
const IMAGE_RATIOS = [
  { label: '1:1', width: 1024, height: 1024 },
  { label: '4:3', width: 1024, height: 768 },
  { label: '3:4', width: 768, height: 1024 },
  { label: '3:2', width: 1536, height: 1024 },
  { label: '2:3', width: 1024, height: 1536 },
  { label: '16:9', width: 1344, height: 768 },
  { label: '9:16', width: 768, height: 1344 },
] as const;
const VIDEO_RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4'] as const;
const VIDEO_RESOLUTIONS = ['480P', '720P', '1080P', '1K', '2K', '4K'] as const;
const IMAGE_QUALITIES = ['auto', 'high', 'medium', 'low'] as const;

type MobilePane = 'create' | 'result' | 'history';

interface CreationDraft {
  prompt: string;
  negativePrompt: string;
  selectedAssetIds: number[];
  modelId: number | null;
  quality: 'auto' | 'high' | 'medium' | 'low';
  referenceMode: 'character' | 'style';
  width: number;
  height: number;
  count: number;
  aspectRatio: '16:9' | '9:16' | '1:1' | '4:3' | '3:4';
  resolution: '480P' | '720P' | '1080P' | '1K' | '2K' | '4K';
  durationSeconds: number;
}

const DEFAULT_DRAFT: CreationDraft = {
  prompt: '',
  negativePrompt: '',
  selectedAssetIds: [],
  modelId: null,
  quality: 'auto',
  referenceMode: 'character',
  width: 1024,
  height: 1024,
  count: 1,
  aspectRatio: '16:9',
  resolution: '720P',
  durationSeconds: 5,
};

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function statusLabel(job: CreationStudioJob): string {
  if (job.status === 'succeeded') return '已完成';
  if (job.status === 'failed') return '失败';
  if (job.status === 'cancelled') return '已取消';
  if (job.status === 'cancel_requested') return '取消中';
  if (job.status === 'queued') return '排队中';
  return job.stage === 'materializing' ? '正在保存' : '生成中';
}

function mediaUrl(url: string): string {
  return url.replace(/\\/g, '/');
}

function useAssetMediaUrl(publicUrl: string, mediaType: CreationStudioMediaKind): [string, () => void, boolean, boolean] {
  const protectedAsset = publicUrl.startsWith('/api/creation-studio/');
  const [reloadKey, setReloadKey] = useState(0);
  const [resolved, setResolved] = useState({ sourceKey: '', url: '' });
  const [failedSourceKey, setFailedSourceKey] = useState('');
  const sourceKey = `${mediaType}:${publicUrl}:${reloadKey}`;
  const reload = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    if (!protectedAsset || !publicUrl) return;
    let active = true;
    let objectUrl = '';
    setFailedSourceKey('');
    if (mediaType === 'video') {
      const accessUrl = publicUrl.replace(/\/content(?:\?.*)?$/, '/access-url');
      void fetch(accessUrl, { headers: apiHeaders() })
        .then((response) => {
          if (!response.ok) throw new Error('视频访问链接获取失败');
          return response.json() as Promise<{ url: string }>;
        })
        .then((result) => {
          if (active) setResolved({ sourceKey, url: result.url });
        })
        .catch(() => {
          if (active) {
            setFailedSourceKey(sourceKey);
          }
        });
      return () => {
        active = false;
      };
    }
    void fetch(publicUrl, { headers: apiHeaders() })
      .then((response) => {
        if (!response.ok) throw new Error('素材加载失败');
        return response.blob();
      })
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setResolved({ sourceKey, url: objectUrl });
      })
      .catch(() => {
        if (active) {
          setFailedSourceKey(sourceKey);
        }
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [mediaType, protectedAsset, publicUrl, sourceKey]);

  const url = protectedAsset
    ? (resolved.sourceKey === sourceKey ? resolved.url : '')
    : mediaUrl(publicUrl);
  const loadFailed = failedSourceKey === sourceKey;
  const loading = protectedAsset && Boolean(publicUrl) && !url && !loadFailed;
  return [url, reload, loadFailed, loading];
}

function AssetThumbnail({ asset }: { asset: CreationStudioAsset }) {
  const [src] = useAssetMediaUrl(asset.public_url, 'image');
  return src
    ? <MediaImage src={src} alt={asset.original_name || '参考图片'} className="h-full w-full object-cover" />
    : <span className="grid h-full w-full place-items-center text-slate-300"><Loader2 size={14} className="animate-spin" /></span>;
}

const EmptyResult = memo(function EmptyResult({ mediaKind }: { mediaKind: CreationStudioMediaKind }) {
  const Icon = mediaKind === 'image' ? ImageIcon : Video;
  return (
    <div className="flex h-[clamp(360px,62vh,640px)] max-h-[640px] min-h-[360px] flex-col items-center justify-center text-slate-400">
      <div className="mb-4 grid h-16 w-16 place-items-center rounded-lg border border-[#d7e3f4] bg-white/80 shadow-[0_12px_28px_rgba(59,130,246,0.08)]">
        <Icon size={28} strokeWidth={1.6} />
      </div>
      <div className="text-sm font-medium text-slate-500">还没有生成{mediaKind === 'image' ? '图片' : '视频'}</div>
    </div>
  );
});

interface HistoryPanelProps {
  jobs: CreationStudioJob[];
  selectedJobId: number | null;
  onSelect: (jobId: number) => void;
  onNew: () => void;
  onDelete: (job: CreationStudioJob) => void;
}

const HistoryPanel = memo(function HistoryPanel({ jobs, selectedJobId, onSelect, onNew, onDelete }: HistoryPanelProps) {
  return (
    <section className="flex h-full min-h-0 flex-col border border-[#d7e3f4] bg-[rgba(255,255,255,0.78)] shadow-[0_16px_36px_rgba(59,130,246,0.09)] backdrop-blur-xl xl:rounded-lg">
      <div className="flex items-center justify-between border-b border-[#d7e3f4] px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">生成记录</h2>
          <div className="mt-0.5 text-[11px] text-slate-400">{jobs.length} 条</div>
        </div>
        <button
          type="button"
          onClick={onNew}
          title="新建创作"
          className="grid h-8 w-8 max-md:h-11 max-md:w-11 place-items-center rounded-lg border border-[#c8d8ef] bg-white text-slate-600 transition hover:border-[#8fb2e8] hover:text-[#1d4ed8]"
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {jobs.length === 0 ? (
          <div className="grid h-40 place-items-center rounded-lg border border-dashed border-[#c8d8ef] text-xs text-slate-400">
            暂无生成记录
          </div>
        ) : (
          <div className="space-y-1.5">
            {jobs.map((job) => {
              const selected = job.id === selectedJobId;
              const active = ACTIVE_STATUSES.has(job.status);
              return (
                <div
                  key={job.id}
                  className={`group relative rounded-lg border transition ${
                    selected
                      ? 'border-[#8fb2e8] bg-[#edf5ff] shadow-[0_8px_18px_rgba(59,130,246,0.1)]'
                      : 'border-transparent hover:border-[#d7e3f4] hover:bg-white/85'
                  }`}
                >
                  <button type="button" onClick={() => onSelect(job.id)} className="block w-full px-3 py-2.5 text-left">
                    <div className="flex items-start gap-2.5">
                    <div className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg ${job.media_kind === 'image' ? 'bg-[#e7f0ff] text-[#2563eb]' : 'bg-[#fff4df] text-[#b45309]'}`}>
                      {job.media_kind === 'image' ? <ImageIcon size={15} /> : <Film size={15} />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-2 text-xs font-medium leading-5 text-slate-700">{job.prompt}</div>
                      <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-slate-400">
                        <span className={`inline-flex items-center gap-1 ${job.status === 'failed' ? 'text-red-500' : job.status === 'succeeded' ? 'text-emerald-600' : ''}`}>
                          {active ? <Loader2 size={10} className="animate-spin" /> : job.status === 'succeeded' ? <Check size={10} /> : <Clock3 size={10} />}
                          {statusLabel(job)}
                        </span>
                        <span>{formatTime(job.created_at)}</span>
                      </div>
                      {active ? (
                        <div className="mt-2 h-1 overflow-hidden rounded-full bg-[#dbe8f8]">
                          <div className="h-full rounded-full bg-[#3b82f6] transition-[width]" style={{ width: `${Math.max(4, job.progress)}%` }} />
                        </div>
                      ) : null}
                    </div>
                    </div>
                  </button>
                  {!active ? (
                    <button
                      type="button"
                      title="删除记录"
                      onClick={() => onDelete(job)}
                      className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-lg text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 focus:opacity-100 max-md:h-9 max-md:w-9 max-md:opacity-100 max-md:text-slate-400"
                    >
                      <Trash2 size={13} />
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
});

interface ResultPanelProps {
  mediaKind: CreationStudioMediaKind;
  job: CreationStudioJob | null;
  onCancel: (job: CreationStudioJob) => void;
  onRetry: (job: CreationStudioJob) => void;
  onRedraw: (job: CreationStudioJob) => void;
}

const ResultPanel = memo(function ResultPanel({ mediaKind, job, onCancel, onRetry, onRedraw }: ResultPanelProps) {
  const active = job ? ACTIVE_STATUSES.has(job.status) : false;
  const [outputUrl, reloadOutput, outputLoadFailed, outputLoading] = useAssetMediaUrl(job?.output?.public_url || '', job?.media_kind || mediaKind);
  const retriedVideoOutputRef = useRef('');
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoPlaying, setVideoPlaying] = useState(false);
  const [imageDecodeFailedUrl, setImageDecodeFailedUrl] = useState('');
  const imageDecodeFailed = job?.media_kind === 'image' && imageDecodeFailedUrl === outputUrl;

  useEffect(() => {
    setVideoPlaying(false);
    retriedVideoOutputRef.current = '';
    setImageDecodeFailedUrl('');
  }, [job?.id]);

  const toggleVideoPlayback = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    try {
      if (video.paused) await video.play();
      else video.pause();
    } catch {
      toast.error('视频无法播放，请重新加载后重试');
    }
  }, []);

  const handleVideoError = useCallback(() => {
    const outputKey = job?.output?.public_url || '';
    if (!outputKey || retriedVideoOutputRef.current === outputKey) return;
    retriedVideoOutputRef.current = outputKey;
    reloadOutput();
  }, [job?.output?.public_url, reloadOutput]);
  const handleImageError = useCallback(() => {
    setImageDecodeFailedUrl(outputUrl);
  }, [outputUrl]);
  const handleReloadOutput = useCallback(() => {
    setImageDecodeFailedUrl('');
    reloadOutput();
  }, [reloadOutput]);
  return (
    <section className="flex h-full min-h-0 flex-col border border-[#d7e3f4] bg-[rgba(255,255,255,0.78)] shadow-[0_16px_36px_rgba(59,130,246,0.09)] backdrop-blur-xl xl:rounded-lg">
      <div className="flex h-[57px] items-center justify-between border-b border-[#d7e3f4] px-4 max-md:h-auto max-md:flex-col max-md:items-stretch max-md:gap-2 max-md:py-2.5">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">生成结果</h2>
          {job ? <div className="mt-0.5 text-[11px] text-slate-400">任务 #{job.id} · {job.model_display_name || job.model_key || '自动模型'}</div> : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 max-md:justify-start">
          {active && job ? (
            <button type="button" onClick={() => onCancel(job)} className="rounded-lg border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs text-slate-600 transition hover:border-red-200 hover:text-red-500 max-md:min-h-11">
              取消
            </button>
          ) : null}
          {job && ['failed', 'cancelled'].includes(job.status) ? (
            <button type="button" onClick={() => onRetry(job)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#bfd2ec] bg-white px-3 py-1.5 text-xs text-[#1d4ed8] transition hover:bg-[#edf5ff] max-md:min-h-11">
              <RefreshCw size={12} /> 重试
            </button>
          ) : null}
          {job?.status === 'succeeded' && job.media_kind === 'image' && job.output ? (
            <button type="button" onClick={() => onRedraw(job)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#bfd2ec] bg-white px-3 py-1.5 text-xs font-medium text-[#1d4ed8] transition hover:bg-[#edf5ff] max-md:min-h-11">
              <RefreshCw size={12} /> 以此图重绘
            </button>
          ) : null}
          {job?.status === 'succeeded' && job.media_kind === 'video' && outputUrl ? (
            <button type="button" onClick={() => void toggleVideoPlayback()} className="inline-flex items-center gap-1.5 rounded-lg border border-[#bfd2ec] bg-white px-3 py-1.5 text-xs font-medium text-[#1d4ed8] transition hover:bg-[#edf5ff] max-md:min-h-11">
              {videoPlaying ? <Pause size={12} /> : <Play size={12} />} {videoPlaying ? '暂停' : '播放'}
            </button>
          ) : null}
          {outputUrl ? (
            <a href={outputUrl} download target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white transition hover:bg-[#1e40af] max-md:min-h-11">
              <Download size={12} /> 下载
            </a>
          ) : null}
        </div>
      </div>
      <div className="min-h-0 flex-1 p-3">
        {!job ? <EmptyResult mediaKind={mediaKind} /> : active ? (
          <div className="flex h-[clamp(360px,62vh,640px)] max-h-[640px] min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-[#c8d8ef] bg-[linear-gradient(180deg,rgba(248,251,255,0.72),rgba(238,245,255,0.72))]">
            <Loader2 size={28} className="animate-spin text-[#3b82f6]" />
            <div className="mt-4 text-sm font-medium text-slate-600">{statusLabel(job)}</div>
            <div className="mt-2 text-xs text-slate-400">{job.progress}%</div>
            <div className="mt-4 h-1.5 w-48 overflow-hidden rounded-full bg-[#dbe8f8]">
              <div className="h-full rounded-full bg-[#3b82f6] transition-[width]" style={{ width: `${Math.max(4, job.progress)}%` }} />
            </div>
          </div>
        ) : job.status === 'failed' || job.status === 'cancelled' ? (
          <div className="flex h-[clamp(360px,62vh,640px)] max-h-[640px] min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-red-200 bg-red-50/40 px-8 text-center">
            <AlertCircle size={28} className="text-red-400" />
            <div className="mt-4 text-sm font-medium text-slate-700">{job.status === 'cancelled' ? '任务已取消' : '生成失败'}</div>
            <div className="mt-2 max-w-lg text-xs leading-5 text-slate-500">{normalizeErrorMessage(job.error_message, '可以调整参数后重试')}</div>
          </div>
        ) : outputLoadFailed || imageDecodeFailed ? (
          <div className="flex h-[clamp(360px,62vh,640px)] max-h-[640px] min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-amber-200 bg-amber-50/50 px-8 text-center">
            <AlertCircle size={28} className="text-amber-500" />
            <div className="mt-4 text-sm font-medium text-slate-700">{job.media_kind === 'video' ? '视频预览加载失败' : '图片预览加载失败'}</div>
            <button type="button" onClick={handleReloadOutput} className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 transition hover:bg-amber-50 max-md:min-h-11">
              <RefreshCw size={12} /> 重新加载
            </button>
          </div>
        ) : outputLoading ? (
          <div className="flex h-[clamp(360px,62vh,640px)] max-h-[640px] min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-[#c8d8ef] bg-[linear-gradient(180deg,rgba(248,251,255,0.72),rgba(238,245,255,0.72))]">
            <Loader2 size={28} className="animate-spin text-[#3b82f6]" />
            <div className="mt-4 text-sm font-medium text-slate-600">正在加载{job.media_kind === 'video' ? '视频' : '图片'}预览</div>
          </div>
        ) : outputUrl ? (
          <div className="relative flex h-[clamp(360px,62vh,640px)] max-h-[640px] min-h-[360px] items-center justify-center overflow-hidden rounded-lg bg-[#101725]">
            {job.media_kind === 'image' ? (
              <ImageZoomView src={outputUrl} alt={job.prompt} className="h-full w-full" fallback={<Loader2 size={24} className="animate-spin text-white/60" />} onLoadError={handleImageError} />
            ) : (
              <video ref={videoRef} src={outputUrl} controls playsInline preload="metadata" onError={handleVideoError} onPlay={() => setVideoPlaying(true)} onPause={() => setVideoPlaying(false)} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()} className="relative z-10 h-full w-full pointer-events-auto object-contain" />
            )}
          </div>
        ) : <EmptyResult mediaKind={mediaKind} />}
      </div>
      {job ? (
        <div className="border-t border-[#d7e3f4] px-4 py-3">
          <div className="line-clamp-2 text-xs leading-5 text-slate-500">{job.prompt}</div>
        </div>
      ) : null}
    </section>
  );
});

export function CreationStudioPage({ storyId, chapterId, storyTitle, chapterTitle }: CreationStudioPageProps) {
  const [mediaKind, setMediaKind] = useState<CreationStudioMediaKind>('image');
  const [mobilePane, setMobilePane] = useState<MobilePane>('create');
  const [jobs, setJobs] = useState<CreationStudioJob[]>([]);
  const [assets, setAssets] = useState<CreationStudioAsset[]>([]);
  const [imageModels, setImageModels] = useState<AiModelItem[]>([]);
  const [videoModels, setVideoModels] = useState<AiModelItem[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [selectedAssetIds, setSelectedAssetIds] = useState<number[]>([]);
  const [modelId, setModelId] = useState<number | null>(null);
  const [quality, setQuality] = useState<'auto' | 'high' | 'medium' | 'low'>('auto');
  const [referenceMode, setReferenceMode] = useState<'character' | 'style'>('character');
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [count, setCount] = useState(1);
  const [aspectRatio, setAspectRatio] = useState<'16:9' | '9:16' | '1:1' | '4:3' | '3:4'>('16:9');
  const [resolution, setResolution] = useState<'480P' | '720P' | '1080P' | '1K' | '2K' | '4K'>('720P');
  const [durationSeconds, setDurationSeconds] = useState(5);
  const [estimate, setEstimate] = useState<{ points: number; sufficient: boolean } | null>(null);
  const estimateRequestRef = useRef(0);
  const [credentialMode, setCredentialMode] = useState<'platform' | 'user_key'>('platform');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzingAssets, setAnalyzingAssets] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const refreshFailureCountRef = useRef(0);
  const draftsRef = useRef<Record<CreationStudioMediaKind, CreationDraft>>({
    image: { ...DEFAULT_DRAFT, selectedAssetIds: [] },
    video: { ...DEFAULT_DRAFT, selectedAssetIds: [] },
  });

  const applyDraft = useCallback((draft: CreationDraft) => {
    setPrompt(draft.prompt);
    setNegativePrompt(draft.negativePrompt);
    setSelectedAssetIds(draft.selectedAssetIds);
    setModelId(draft.modelId);
    setQuality(draft.quality);
    setReferenceMode(draft.referenceMode);
    setWidth(draft.width);
    setHeight(draft.height);
    setCount(draft.count);
    setAspectRatio(draft.aspectRatio);
    setResolution(draft.resolution);
    setDurationSeconds(draft.durationSeconds);
  }, []);

  const currentDraft = useCallback((): CreationDraft => ({
    prompt,
    negativePrompt,
    selectedAssetIds,
    modelId,
    quality,
    referenceMode,
    width,
    height,
    count,
    aspectRatio,
    resolution,
    durationSeconds,
  }), [aspectRatio, count, durationSeconds, height, modelId, negativePrompt, prompt, quality, referenceMode, resolution, selectedAssetIds, width]);

  const currentModels = mediaKind === 'image' ? imageModels : videoModels;
  const effectiveModelId = currentModels.some((model) => model.id === modelId)
    ? modelId
    : currentModels[0]?.id ?? null;
  const selectedVideoModel = videoModels.find((model) => model.id === effectiveModelId);
  const selectedImageModel = imageModels.find((model) => model.id === effectiveModelId);
  const imageCapabilities = selectedImageModel?.image_capabilities;
  const imageQualities = useMemo(() => (imageCapabilities?.limits?.qualities || IMAGE_QUALITIES)
    .filter((item): item is (typeof IMAGE_QUALITIES)[number] => IMAGE_QUALITIES.includes(item)), [imageCapabilities?.limits?.qualities]);
  const videoCapabilities = selectedVideoModel?.video_capabilities;
  const videoLimits = videoCapabilities?.limits;
  const videoRatios = useMemo(() => (videoLimits?.aspect_ratios || [])
    .filter((item): item is typeof VIDEO_RATIOS[number] => VIDEO_RATIOS.includes(item as typeof VIDEO_RATIOS[number])), [videoLimits?.aspect_ratios]);
  const videoResolutions = useMemo(() => (videoLimits?.resolutions || [])
    .filter((item): item is typeof VIDEO_RESOLUTIONS[number] => VIDEO_RESOLUTIONS.includes(item as typeof VIDEO_RESOLUTIONS[number])), [videoLimits?.resolutions]);
  const videoDurations = useMemo(() => {
    const rule = videoLimits?.duration_seconds;
    const allowed = rule?.allowed?.filter((item): item is number => Number.isInteger(item) && item > 0) || [];
    if (allowed.length) return allowed;
    const minimum = rule?.min;
    const maximum = rule?.max;
    if (typeof minimum !== 'number' || typeof maximum !== 'number' || !Number.isInteger(minimum) || !Number.isInteger(maximum) || minimum > maximum) return [];
    return Array.from({ length: maximum - minimum + 1 }, (_, index) => minimum + index);
  }, [videoLimits?.duration_seconds]);
  const videoParametersConfigured = Boolean(
    selectedVideoModel
    && videoRatios.length
    && videoResolutions.length
    && videoDurations.length,
  );

  const visibleJobs = useMemo(() => jobs.filter((job) => job.media_kind === mediaKind), [jobs, mediaKind]);
  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) || null,
    [jobs, selectedJobId],
  );
  const selectedAssets = useMemo(
    () => selectedAssetIds.map((id) => assets.find((asset) => asset.id === id)).filter((asset): asset is CreationStudioAsset => Boolean(asset)),
    [assets, selectedAssetIds],
  );

  const refreshData = useCallback(async (silent = false) => {
    try {
      const [jobResult, assetResult] = await Promise.all([
        listCreationStudioJobs(),
        listCreationStudioAssets(),
      ]);
      setJobs(jobResult.jobs);
      setAssets(assetResult.assets);
      refreshFailureCountRef.current = 0;
    } catch (error) {
      if (!silent) {
        toast.error(normalizeErrorMessage(error, '加载创作台失败，请稍后重试'));
      } else {
        refreshFailureCountRef.current += 1;
        if (refreshFailureCountRef.current === 3) {
          toast.error(normalizeErrorMessage(error, '暂时无法获取创作任务状态，系统将继续重试'));
        }
      }
    }
  }, []);

  useEffect(() => {
    let alive = true;
    void Promise.all([getAiModels('image'), getAiModels('video'), getAiPreferences(), listCreationStudioJobs(), listCreationStudioAssets()])
      .then(([imagesResult, videosResult, preferencesResult, jobsResult, assetsResult]) => {
        if (!alive) return;
        setImageModels(imagesResult.models);
        setVideoModels(videosResult.models);
        setCredentialMode(preferencesResult.credential_mode);
        setJobs(jobsResult.jobs);
        setAssets(assetsResult.assets);
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : '加载创作台失败'))
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!jobs.some((job) => ACTIVE_STATUSES.has(job.status))) return;
    const timer = window.setInterval(() => void refreshData(true), 3000);
    return () => window.clearInterval(timer);
  }, [jobs, refreshData]);

  useEffect(() => {
    const requestId = ++estimateRequestRef.current;
    if (credentialMode === 'user_key' || !effectiveModelId || (mediaKind === 'video' && !videoParametersConfigured)) {
      setEstimate(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void estimateAiPoints({
        model_id: effectiveModelId,
        image_count: mediaKind === 'image' ? count : 1,
        video_seconds: mediaKind === 'video' ? durationSeconds : 0,
      })
        .then((result) => {
          if (requestId === estimateRequestRef.current) {
            setEstimate({ points: result.estimated_points, sufficient: result.sufficient });
          }
        })
        .catch(() => {
          if (requestId === estimateRequestRef.current) setEstimate(null);
        });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [count, credentialMode, durationSeconds, effectiveModelId, mediaKind, videoParametersConfigured]);

  useEffect(() => {
    if (mediaKind !== 'video' || !videoParametersConfigured) return;
    const defaults = videoCapabilities?.defaults;
    setAspectRatio((current) => videoRatios.includes(current) ? current : (defaults?.aspect_ratio && videoRatios.includes(defaults.aspect_ratio as typeof VIDEO_RATIOS[number]) ? defaults.aspect_ratio as typeof VIDEO_RATIOS[number] : videoRatios[0] || '16:9'));
    setResolution((current) => videoResolutions.includes(current) ? current : (defaults?.resolution && videoResolutions.includes(defaults.resolution as typeof VIDEO_RESOLUTIONS[number]) ? defaults.resolution as typeof VIDEO_RESOLUTIONS[number] : videoResolutions[0] || '720P'));
    setDurationSeconds((current) => videoDurations.includes(current) ? current : (defaults?.duration_seconds && videoDurations.includes(defaults.duration_seconds) ? defaults.duration_seconds : videoDurations[0]));
    const maxReferences = videoLimits?.max_reference_images;
    const supportsReferences = videoCapabilities?.input_modes?.includes('image_to_video') ?? true;
    if (!supportsReferences || maxReferences === 0) setSelectedAssetIds([]);
    else if (maxReferences) setSelectedAssetIds((current) => current.slice(0, maxReferences));
  }, [mediaKind, videoCapabilities, videoDurations, videoLimits?.max_reference_images, videoParametersConfigured, videoRatios, videoResolutions]);

  useEffect(() => {
    if (mediaKind !== 'image') return;
    const defaultQuality = imageCapabilities?.defaults?.quality;
    setQuality((current) => {
      if (defaultQuality && imageQualities.includes(defaultQuality) && current === 'auto') return defaultQuality;
      return imageQualities.includes(current) ? current : imageQualities[0] || 'auto';
    });
  }, [imageCapabilities?.defaults?.quality, imageQualities, mediaKind]);

  useEffect(() => {
    if (!storyId) setAssistantOpen(false);
  }, [storyId]);

  const switchMediaKind = (next: CreationStudioMediaKind) => {
    if (next === mediaKind) return;
    draftsRef.current[mediaKind] = currentDraft();
    setMediaKind(next);
    setSelectedJobId(null);
    setEstimate(null);
    applyDraft(draftsRef.current[next]);
  };

  const handleFiles = useCallback(async (files: File[]) => {
    if (uploading) return;
    if (mediaKind === 'video' && !videoParametersConfigured) {
      toast.error('当前视频模型尚未配置可用时长、清晰度和比例，无法添加参考图');
      return;
    }
    const maxReferences = mediaKind === 'video' ? (videoLimits?.max_reference_images ?? 9) : 9;
    const available = Math.max(0, maxReferences - selectedAssetIds.length);
    const accepted = files.filter((file) => file.type.startsWith('image/')).slice(0, available);
    if (!accepted.length) {
      toast.error(available === 0 ? '最多选择 9 张参考图片' : '请选择有效图片');
      return;
    }
    setUploading(true);
    try {
      const results = await Promise.all(accepted.map((file) => uploadCreationStudioAsset(file)));
      const uploadedIds = results.map((result) => result.asset.id);
      setAssets((previous) => {
        const map = new Map(previous.map((asset) => [asset.id, asset]));
        results.forEach((result) => map.set(result.asset.id, result.asset));
        return Array.from(map.values()).sort((a, b) => b.id - a.id);
      });
      setSelectedAssetIds((previous) => Array.from(new Set([...previous, ...uploadedIds])).slice(0, maxReferences));
      toast.success(results.some((result) => result.deduplicated) ? '参考图片已加入，重复素材已自动复用' : '参考图片已上传');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '上传参考图片失败');
    } finally {
      setUploading(false);
    }
  }, [mediaKind, selectedAssetIds.length, uploading, videoLimits?.max_reference_images, videoParametersConfigured]);

  const handleClipboard = async () => {
    if (uploading) return;
    try {
      const items = await navigator.clipboard.read();
      const files: File[] = [];
      for (const item of items) {
        const type = item.types.find((candidate) => candidate.startsWith('image/'));
        if (!type) continue;
        const blob = await item.getType(type);
        files.push(new File([blob], `clipboard-${Date.now()}.png`, { type }));
      }
      await handleFiles(files);
    } catch {
      toast.error('无法读取剪贴板，请使用上传按钮');
    }
  };

  const handleAnalyzeAssets = useCallback(async () => {
    if (!selectedAssetIds.length || analyzingAssets) return;
    setAnalyzingAssets(true);
    try {
      const result = await analyzeCreationStudioAssets(selectedAssetIds);
      type PromptAnalysis = { prompt?: string; negative_prompt?: string };
      let parsed: PromptAnalysis | null = null;
      try {
        const normalized = result.analysis.replace(/^```json\s*/i, '').replace(/```$/i, '').trim();
        const value = JSON.parse(normalized) as unknown;
        if (value && typeof value === 'object') parsed = value as PromptAnalysis;
      } catch {
        // 模型返回普通文本时仍然保留完整分析结果，避免丢失有用内容。
      }
      setPrompt(parsed?.prompt?.trim() || result.analysis);
      if (parsed?.negative_prompt) setNegativePrompt(parsed.negative_prompt.trim());
      toast.success('参考素材分析完成，已回填提示词');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '参考素材分析失败');
    } finally {
      setAnalyzingAssets(false);
    }
  }, [analyzingAssets, selectedAssetIds]);

  const handleSubmit = async () => {
    if (!prompt.trim()) {
      toast.error('请输入提示词');
      return;
    }
    if (!effectiveModelId) {
      toast.error(`暂无可用的${mediaKind === 'image' ? '图片' : '视频'}模型`);
      return;
    }
    if (mediaKind === 'video' && !videoParametersConfigured) {
      toast.error('当前视频模型尚未配置明确的时长、清晰度和比例，请联系管理员完成模型参数配置');
      return;
    }
    if (credentialMode === 'platform' && estimate && !estimate.sufficient) {
      toast.error('积分不足，请先充值或切换到自有 API Key');
      return;
    }
    setSubmitting(true);
    try {
      const result = await createCreationStudioJobs({
        media_kind: mediaKind,
        prompt: prompt.trim(),
        negative_prompt: negativePrompt.trim(),
        model_id: effectiveModelId,
        asset_ids: selectedAssetIds,
        count: mediaKind === 'image' ? count : 1,
        width,
        height,
        quality,
        reference_mode: referenceMode,
        aspect_ratio: aspectRatio,
        resolution,
        duration_seconds: durationSeconds,
      });
      setJobs((previous) => [...result.jobs, ...previous]);
      setSelectedJobId(result.jobs[0]?.id ?? null);
      setMobilePane('result');
      toast.success(result.jobs.length > 1 ? `已提交 ${result.jobs.length} 个生成任务` : '生成任务已提交');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '提交生成任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = useCallback(async (job: CreationStudioJob) => {
    try {
      const result = await cancelCreationStudioJob(job.id);
      setJobs((previous) => previous.map((item) => item.id === job.id ? result.job : item));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '取消任务失败');
    }
  }, []);

  const handleRetry = useCallback(async (job: CreationStudioJob) => {
    try {
      const result = await retryCreationStudioJob(job.id);
      setJobs((previous) => [result.job, ...previous]);
      setSelectedJobId(result.job.id);
      toast.success('已重新提交任务');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重试任务失败');
    }
  }, []);

  const handleRedraw = useCallback((job: CreationStudioJob) => {
    if (!job.output) return;
    setAssets((previous) => previous.some((asset) => asset.id === job.output!.id) ? previous : [job.output!, ...previous]);
    applyDraft({
      ...DEFAULT_DRAFT,
      prompt: job.prompt,
      negativePrompt: job.negative_prompt || '',
      modelId: job.model_id,
      selectedAssetIds: [job.output.id],
      width: typeof job.parameters.width === 'number' ? job.parameters.width : DEFAULT_DRAFT.width,
      height: typeof job.parameters.height === 'number' ? job.parameters.height : DEFAULT_DRAFT.height,
      quality: job.parameters.quality === 'high' || job.parameters.quality === 'medium' || job.parameters.quality === 'low' ? job.parameters.quality : 'auto',
      referenceMode: job.parameters.reference_mode === 'style' ? 'style' : 'character',
    });
    draftsRef.current.image = {
      ...DEFAULT_DRAFT,
      prompt: job.prompt,
      negativePrompt: job.negative_prompt || '',
      modelId: job.model_id,
      selectedAssetIds: [job.output.id],
    };
    setMediaKind('image');
    setMobilePane('create');
    toast.success('已将当前图片带入创作参数，可调整后重绘');
  }, [applyDraft]);

  const applyJobToDraft = useCallback((job: CreationStudioJob) => {
    const parameters = job.parameters;
    const imageDraft: CreationDraft = {
      ...DEFAULT_DRAFT,
      prompt: job.prompt,
      negativePrompt: job.negative_prompt || '',
      modelId: job.model_id,
      selectedAssetIds: job.inputs.map((asset) => asset.id),
      width: typeof parameters.width === 'number' ? parameters.width : DEFAULT_DRAFT.width,
      height: typeof parameters.height === 'number' ? parameters.height : DEFAULT_DRAFT.height,
      count: typeof parameters.count === 'number' ? parameters.count : DEFAULT_DRAFT.count,
      quality: parameters.quality === 'high' || parameters.quality === 'medium' || parameters.quality === 'low' ? parameters.quality : 'auto',
      referenceMode: parameters.reference_mode === 'style' ? 'style' : 'character',
    };
    const videoDraft: CreationDraft = {
      ...imageDraft,
      aspectRatio: parameters.aspect_ratio === '9:16' || parameters.aspect_ratio === '1:1' || parameters.aspect_ratio === '4:3' || parameters.aspect_ratio === '3:4' ? parameters.aspect_ratio : '16:9',
      resolution: parameters.resolution === '480P' || parameters.resolution === '1080P' || parameters.resolution === '1K' || parameters.resolution === '2K' || parameters.resolution === '4K' ? parameters.resolution : '720P',
      durationSeconds: typeof parameters.duration_seconds === 'number' ? parameters.duration_seconds : DEFAULT_DRAFT.durationSeconds,
      count: 1,
    };
    const draft = job.media_kind === 'image' ? imageDraft : videoDraft;
    draftsRef.current[job.media_kind] = draft;
    setAssets((previous) => {
      const assetsById = new Map(previous.map((asset) => [asset.id, asset]));
      job.inputs.forEach((asset) => assetsById.set(asset.id, asset));
      return Array.from(assetsById.values()).sort((a, b) => b.id - a.id);
    });
    setMediaKind(job.media_kind);
    setSelectedJobId(job.id);
    setEstimate(null);
    applyDraft(draft);
    setMobilePane('result');
  }, [applyDraft]);

  const handleDeleteJob = useCallback(async (job: CreationStudioJob) => {
    try {
      await deleteCreationStudioJob(job.id);
      setJobs((previous) => previous.filter((item) => item.id !== job.id));
      setSelectedJobId((current) => current === job.id ? null : current);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除记录失败');
    }
  }, []);

  const handleDeleteAsset = async (asset: CreationStudioAsset) => {
    try {
      await deleteCreationStudioAsset(asset.id);
      setAssets((previous) => previous.filter((item) => item.id !== asset.id));
      setSelectedAssetIds((previous) => previous.filter((id) => id !== asset.id));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除参考图片失败');
    }
  };

  const resetDraft = useCallback(() => {
    const draft = { ...DEFAULT_DRAFT, selectedAssetIds: [] };
    draftsRef.current[mediaKind] = draft;
    applyDraft(draft);
    setSelectedJobId(null);
    setMobilePane('create');
  }, [applyDraft, mediaKind]);

  if (loading) {
    return <div className="grid h-full place-items-center"><Loader2 className="animate-spin text-[#3b82f6]" /></div>;
  }

  return (
    <div className="relative flex h-full min-h-[520px] flex-col overflow-hidden rounded-lg border border-[#d7e3f4] bg-[rgba(245,249,255,0.72)] shadow-[0_18px_42px_rgba(59,130,246,0.08)] backdrop-blur-xl xl:min-h-[620px]">
      <div className="flex min-h-14 items-center justify-between gap-3 border-b border-[#d7e3f4] bg-white/72 px-3 sm:px-4 max-md:flex-wrap max-md:gap-y-2">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-[linear-gradient(145deg,#1d4ed8,#3b82f6)] text-white shadow-[0_8px_18px_rgba(37,99,235,0.24)]">
            <Sparkles size={17} />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-slate-900">创作台</h1>
            <div className="text-[11px] text-slate-400">独立图片与视频生成</div>
          </div>
        </div>
        <div className="flex h-9 items-center rounded-lg border border-[#c8d8ef] bg-[#edf4ff] p-1">
          <button type="button" onClick={() => switchMediaKind('image')} className={`inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#2563eb] ${mediaKind === 'image' ? 'bg-white text-[#1d4ed8] shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>
            <ImageIcon size={14} /> 图片
          </button>
          <button type="button" onClick={() => switchMediaKind('video')} className={`inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#2563eb] ${mediaKind === 'video' ? 'bg-white text-[#b45309] shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>
            <Video size={14} /> 视频
          </button>
        </div>
        <button type="button" disabled={!storyId} onClick={() => setAssistantOpen((value) => !value)} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition max-md:min-h-11 ${assistantOpen ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-[#c8d8ef] bg-white text-slate-600 hover:border-blue-300 hover:text-blue-700'} disabled:cursor-not-allowed disabled:opacity-50`} title={storyId ? '打开创作台 AI 助手' : '独立创作无需绑定作品'}>
          <Bot size={14} /> AI 助手
        </button>
      </div>

      <div className="grid grid-cols-3 border-b border-[#d7e3f4] bg-white/80 xl:hidden">
        {([
          ['create', '创作'],
          ['result', '结果'],
          ['history', '记录'],
        ] as const).map(([key, label]) => (
          <button key={key} type="button" onClick={() => setMobilePane(key)} className={`h-10 max-md:min-h-11 text-xs font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#2563eb] ${mobilePane === key ? 'border-b-2 border-[#2563eb] text-[#1d4ed8]' : 'text-slate-500'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 xl:grid xl:grid-cols-[248px_420px_minmax(0,1fr)] xl:gap-2 xl:p-2">
        <div className={`${mobilePane === 'history' ? 'block' : 'hidden'} h-full xl:block`}>
          <HistoryPanel
            jobs={visibleJobs}
            selectedJobId={selectedJob?.id ?? null}
            onSelect={(id) => {
              const job = jobs.find((item) => item.id === id);
              if (job) applyJobToDraft(job);
            }}
            onNew={resetDraft}
            onDelete={handleDeleteJob}
          />
        </div>

        <section className={`${mobilePane === 'create' ? 'flex' : 'hidden'} h-full min-h-0 flex-col border border-[#d7e3f4] bg-[rgba(255,255,255,0.82)] shadow-[0_16px_36px_rgba(59,130,246,0.09)] backdrop-blur-xl xl:flex xl:rounded-lg`}>
          <div className="border-b border-[#d7e3f4] px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-900">{mediaKind === 'image' ? '图片创作' : '视频创作'}</h2>
          </div>
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
            <div>
              <label htmlFor="creation-studio-prompt" className="mb-2 block text-xs font-semibold text-slate-700">提示词</label>
              <textarea id="creation-studio-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={12000} placeholder={mediaKind === 'image' ? '描述主体、场景、构图、光线和画面风格' : '描述镜头运动、主体动作、场景氛围和画面风格'} className="h-32 w-full resize-none rounded-lg border border-[#c8d8ef] bg-white/90 px-3 py-2.5 text-sm leading-6 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-[#6c9ee6] focus:ring-2 focus:ring-[#dcecff]" />
              <div className="mt-1 text-right text-[10px] text-slate-400">{prompt.length}/12000</div>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-700">参考图片 <span className="font-normal text-slate-400">{selectedAssetIds.length}/{mediaKind === 'video' ? (videoParametersConfigured ? (videoLimits?.max_reference_images ?? 0) : 0) : 9}</span></label>
                <div className="flex gap-1.5">
                  <button type="button" disabled={uploading || (mediaKind === 'video' && !videoParametersConfigured)} title="从剪贴板读取图片" onClick={() => void handleClipboard()} className="grid h-7 w-7 max-md:h-11 max-md:w-11 place-items-center rounded-lg border border-[#c8d8ef] bg-white text-slate-500 transition hover:text-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-50"><Clipboard size={13} /></button>
                  <button type="button" disabled={uploading || (mediaKind === 'video' && !videoParametersConfigured)} title="上传参考图片" onClick={() => fileInputRef.current?.click()} className="grid h-7 w-7 max-md:h-11 max-md:w-11 place-items-center rounded-lg border border-[#c8d8ef] bg-white text-slate-500 transition hover:text-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-50"><Upload size={13} /></button>
                </div>
              </div>
              <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple className="hidden" onChange={(event) => { void handleFiles(Array.from(event.target.files || [])); event.currentTarget.value = ''; }} />
              <button type="button" disabled={uploading || (mediaKind === 'video' && (!videoParametersConfigured || videoCapabilities?.input_modes?.includes('image_to_video') === false))} onClick={() => fileInputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void handleFiles(Array.from(event.dataTransfer.files)); }} className="flex min-h-20 w-full items-center justify-center rounded-lg border border-dashed border-[#b8cce8] bg-[#f7faff] text-xs text-slate-400 transition hover:border-[#6c9ee6] hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50">
                {uploading ? <><Loader2 size={15} className="mr-2 animate-spin" /> 上传中...</> : <><Images size={16} className="mr-2" /> 添加或拖入参考图片</>}
              </button>
              {selectedAssets.length ? (
                <div className="mt-2 grid grid-cols-5 gap-2 max-md:grid-cols-4">
                  {selectedAssets.map((asset) => {
                    const selected = true;
                    return (
                      <div key={asset.id} className="group relative aspect-square overflow-hidden rounded-lg border border-[#d7e3f4] bg-white">
                        <button type="button" onClick={() => setSelectedAssetIds((previous) => selected ? previous.filter((id) => id !== asset.id) : previous.length < (mediaKind === 'video' ? (videoLimits?.max_reference_images ?? 9) : 9) ? [...previous, asset.id] : previous)} className="h-full w-full">
                          <AssetThumbnail asset={asset} />
                          <span className={`absolute inset-0 border-2 transition ${selected ? 'border-[#2563eb] bg-[#2563eb]/10' : 'border-transparent'}`} />
                          {selected ? <span className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full bg-[#2563eb] text-white"><Check size={10} /></span> : null}
                        </button>
                        {asset.role === 'upload' ? <button type="button" title="删除素材" onClick={() => void handleDeleteAsset(asset)} className="absolute right-1 top-1 hidden h-5 w-5 place-items-center rounded-md bg-black/60 text-white group-hover:grid"><X size={11} /></button> : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {mediaKind === 'image' && selectedAssetIds.length ? (
                <button type="button" disabled={analyzingAssets} onClick={() => void handleAnalyzeAssets()} className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50 max-md:w-full max-md:justify-center max-md:min-h-11">
                  {analyzingAssets ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  {analyzingAssets ? '正在分析参考图...' : 'AI 反推提示词'}
                </button>
              ) : null}
              {mediaKind === 'image' && selectedAssetIds.length ? (
                <div className="mt-2 flex gap-2">
                  {(['character', 'style'] as const).map((mode) => <button key={mode} type="button" onClick={() => setReferenceMode(mode)} className={`flex-1 rounded-lg border px-2 py-1.5 text-xs max-md:min-h-11 ${referenceMode === mode ? 'border-[#8fb2e8] bg-[#edf5ff] text-[#1d4ed8]' : 'border-[#d7e3f4] bg-white text-slate-500'}`}>{mode === 'character' ? '角色一致性' : '风格参考'}</button>)}
                </div>
              ) : null}
            </div>

            <div>
              <label htmlFor="creation-studio-model" className="mb-2 block text-xs font-semibold text-slate-700">模型</label>
              <div className="relative">
                <select id="creation-studio-model" value={effectiveModelId ?? ''} onChange={(event) => setModelId(Number(event.target.value) || null)} className="h-10 w-full appearance-none rounded-lg border border-[#c8d8ef] bg-white px-3 pr-9 text-xs text-slate-700 outline-none focus:border-[#6c9ee6]">
                  {currentModels.length === 0 ? <option value="">暂无可用模型</option> : currentModels.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}
                </select>
                <ChevronDown size={14} className="pointer-events-none absolute right-3 top-3 text-slate-400" />
              </div>
            </div>

            {mediaKind === 'image' ? (
              <>
                <div>
                  <div className="mb-2 text-xs font-semibold text-slate-700">质量</div>
                  <div className="grid grid-cols-4 gap-2">
                    {imageQualities.map((item) => <button key={item} type="button" onClick={() => setQuality(item)} className={`rounded-lg border py-2 text-xs max-md:min-h-11 ${quality === item ? 'border-[#6c9ee6] bg-[#edf5ff] font-medium text-[#1d4ed8]' : 'border-[#d7e3f4] bg-white text-slate-500'}`}>{({ auto: '自动', high: '高', medium: '中', low: '低' })[item]}</button>)}
                  </div>
                </div>
                <div>
                  <label htmlFor="creation-studio-image-ratio" className="mb-2 block text-xs font-semibold text-slate-700">图片比例</label>
                  <div className="relative">
                    <select
                      id="creation-studio-image-ratio"
                      value={`${width}x${height}`}
                      onChange={(event) => {
                        const ratio = IMAGE_RATIOS.find((item) => `${item.width}x${item.height}` === event.target.value);
                        if (ratio) {
                          setWidth(ratio.width);
                          setHeight(ratio.height);
                        }
                      }}
                      className="h-10 w-full appearance-none rounded-lg border border-[#c8d8ef] bg-white px-3 pr-9 text-xs text-slate-700 outline-none focus:border-[#6c9ee6]"
                    >
                      {IMAGE_RATIOS.map((ratio) => <option key={ratio.label} value={`${ratio.width}x${ratio.height}`}>{ratio.label}</option>)}
                    </select>
                    <ChevronDown size={14} className="pointer-events-none absolute right-3 top-3 text-slate-400" />
                  </div>
                </div>
                <div>
                  <label htmlFor="creation-studio-count" className="mb-2 block text-xs font-semibold text-slate-700">生成数量</label>
                  <input id="creation-studio-count" type="range" min={1} max={4} step={1} value={count} onChange={(event) => setCount(Number(event.target.value))} className="w-full accent-[#2563eb]" />
                  <div className="mt-1 flex justify-between text-[10px] text-slate-400"><span>1</span><span className="font-medium text-[#1d4ed8]">{count} 张</span><span>4</span></div>
                </div>
              </>
            ) : !videoParametersConfigured ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-800">
                当前视频模型尚未配置可用的时长、清晰度和画面比例。请管理员在“积分与 AI 渠道”的模型参数中完成视频能力配置。
              </div>
            ) : (
              <>
                <div>
                  <div className="mb-2 text-xs font-semibold text-slate-700">画面比例</div>
                  <div className="grid grid-cols-5 gap-2 max-md:grid-cols-3">{videoRatios.map((ratio) => <button key={ratio} type="button" onClick={() => setAspectRatio(ratio)} className={`rounded-lg border py-2 text-[11px] max-md:min-h-11 ${aspectRatio === ratio ? 'border-[#e5b967] bg-[#fff7e8] text-[#9a5a06]' : 'border-[#d7e3f4] bg-white text-slate-500'}`}>{ratio}</button>)}</div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="creation-studio-resolution" className="mb-2 block text-xs font-semibold text-slate-700">清晰度{videoResolutions.length === 1 ? '（固定）' : ''}</label>
                    <select id="creation-studio-resolution" disabled={videoResolutions.length === 1} value={resolution} onChange={(event) => setResolution(event.target.value as typeof resolution)} className="h-10 w-full rounded-lg border border-[#c8d8ef] bg-white px-3 text-xs text-slate-700 outline-none disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500">{videoResolutions.map((item) => <option key={item}>{item}</option>)}</select>
                  </div>
                  <div>
                    <label htmlFor="creation-studio-duration" className="mb-2 block text-xs font-semibold text-slate-700">时长{videoDurations.length === 1 ? '（固定）' : ''}</label>
                    <select id="creation-studio-duration" disabled={videoDurations.length === 1} value={durationSeconds} onChange={(event) => setDurationSeconds(Number(event.target.value))} className="h-10 w-full rounded-lg border border-[#c8d8ef] bg-white px-3 text-xs text-slate-700 outline-none disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500">{videoDurations.map((item) => <option key={item} value={item}>{item} 秒</option>)}</select>
                  </div>
                </div>
              </>
            )}

            <div>
              <label htmlFor="creation-studio-negative" className="mb-2 block text-xs font-semibold text-slate-700">排除内容</label>
              <textarea id="creation-studio-negative" value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} maxLength={4000} placeholder="模糊、低质量、水印、文字..." className="h-20 w-full resize-none rounded-lg border border-[#c8d8ef] bg-white/90 px-3 py-2 text-xs leading-5 text-slate-700 outline-none placeholder:text-slate-400 focus:border-[#6c9ee6]" />
            </div>
          </div>
          <div className="border-t border-[#d7e3f4] bg-white/92 p-3">
            <button type="button" disabled={submitting || !effectiveModelId} onClick={() => void handleSubmit()} className={`flex h-11 w-full items-center justify-center gap-2 rounded-lg text-sm font-semibold text-white shadow-[0_10px_22px_rgba(37,99,235,0.2)] transition disabled:cursor-not-allowed disabled:opacity-50 ${mediaKind === 'image' ? 'bg-[#1d4ed8] hover:bg-[#1e40af]' : 'bg-[#b45309] hover:bg-[#92400e]'}`}>
              {submitting ? <Loader2 size={16} className="animate-spin" /> : mediaKind === 'image' ? <ImageIcon size={16} /> : <Video size={16} />}
              {submitting ? '正在提交...' : `生成${mediaKind === 'image' ? '图片' : '视频'}`}
            </button>
            <div className={`mt-2 text-center text-[10px] ${estimate && !estimate.sufficient ? 'text-red-500' : 'text-slate-400'}`}>
              {credentialMode === 'user_key'
                ? '使用自有 API Key，不扣平台积分'
                : estimate
                  ? `预计消耗 ${estimate.points} 积分${estimate.sufficient ? '' : ' · 积分不足'}`
                  : '实际消耗以模型返回为准'}
            </div>
          </div>
        </section>

        <div className={`${mobilePane === 'result' ? 'block' : 'hidden'} h-full xl:block`}>
          <ResultPanel mediaKind={mediaKind} job={selectedJob} onCancel={handleCancel} onRetry={handleRetry} onRedraw={handleRedraw} />
        </div>
      </div>
      {assistantOpen ? (
        <aside className="absolute inset-y-14 right-2 z-30 flex w-[380px] min-h-0 flex-col overflow-hidden rounded-xl border border-[#d7e3f4] bg-white/95 shadow-[0_18px_42px_rgba(15,23,42,0.2)] backdrop-blur-xl max-sm:inset-x-2 max-sm:w-auto">
          <header className="flex shrink-0 items-center justify-between border-b border-[#d7e3f4] px-4 py-3 text-sm font-semibold text-slate-800">
            <span className="flex items-center gap-2"><Bot size={16} className="text-blue-600" />创作台 AI 助手</span>
            <button type="button" onClick={() => setAssistantOpen(false)} className="rounded-md px-2 py-1 text-xs text-slate-400 hover:bg-slate-100 hover:text-slate-700">关闭</button>
          </header>
          <div className="min-h-0 flex-1">
            {storyId ? (
              <Suspense fallback={<div className="p-4 text-sm text-slate-500">正在加载 AI 助手...</div>}>
                <AgentPanel
                  storyId={storyId}
                  chapterId={chapterId}
                  storyTitle={storyTitle}
                  chapterTitle={chapterTitle}
                />
              </Suspense>
            ) : (
              <div className="flex h-full items-center justify-center px-6 text-center text-sm leading-6 text-slate-500">请先在作品工作台选择一部作品，再使用创作台 AI 助手。</div>
            )}
          </div>
        </aside>
      ) : null}
    </div>
  );
}
