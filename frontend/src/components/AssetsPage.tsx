import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Images, Inbox, Play, X } from 'lucide-react';
import { listAssets, type CrossStoryAsset } from '../api';
import { toast } from '../lib/toast';
import { Button } from './ui';
import MediaImage from './shared/MediaImage';

/** 每页加载条数 */
const PAGE_SIZE = 24;

/** 资产类型 Tab 配置：空字符串代表「全部」 */
const KIND_TABS: { key: string; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'manga_image', label: '漫画图片' },
  { key: 'manga_asset', label: '漫画素材' },
  { key: 'video_asset', label: '视频素材' },
  { key: 'video_storyboard', label: '视频分镜' },
  { key: 'video_shot', label: '视频成片' },
];

/** kind → 中文标签（卡片角标使用） */
const KIND_LABELS: Record<string, string> = {
  manga_image: '漫画图片',
  manga_asset: '漫画素材',
  video_asset: '视频素材',
  video_storyboard: '视频分镜',
  video_shot: '视频成片',
};

/** 格式化创建时间（非法输入原样返回） */
function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

/** 单张资产卡片：图片缩略图 / 视频预览 + 名称 + 创建时间 */
function AssetCard({ asset, onOpen }: { asset: CrossStoryAsset; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`预览 ${asset.name}`}
      className="group flex min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white text-left shadow-[0_2px_8px_rgba(15,23,42,0.04)] transition hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-[0_10px_28px_rgba(59,130,246,0.12)]"
    >
      <div className="relative w-full overflow-hidden bg-slate-100">
        {asset.media_type === 'video' ? (
          <>
            <video
              src={asset.url}
              muted
              playsInline
              preload="metadata"
              className="aspect-video w-full object-cover transition duration-300 group-hover:scale-105"
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm transition group-hover:bg-blue-600/80">
                <Play size={18} className="ml-0.5" fill="currentColor" aria-hidden="true" />
              </span>
            </div>
          </>
        ) : (
          <MediaImage
            src={asset.url}
            alt={asset.name}
            className="aspect-square w-full object-cover transition duration-300 group-hover:scale-105"
          />
        )}
        {asset.kind ? (
          <span className="absolute left-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
            {KIND_LABELS[asset.kind] ?? asset.kind}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-1 px-3 py-2.5">
        <div className="truncate text-sm font-medium text-slate-800">{asset.name}</div>
        <div className="text-xs text-slate-400">{formatDate(asset.created_at)}</div>
      </div>
    </button>
  );
}

/** 加载骨架卡片 */
function AssetCardSkeleton() {
  return (
    <div className="animate-pulse overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="aspect-square w-full bg-slate-100" />
      <div className="space-y-2 px-3 py-2.5">
        <div className="h-3.5 w-3/4 rounded bg-slate-100" />
        <div className="h-3 w-1/2 rounded bg-slate-100" />
      </div>
    </div>
  );
}

type PreviewModalProps = {
  asset: CrossStoryAsset;
  canNavigate: boolean;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
};

/**
 * 大图 / 大视频预览弹层：
 * 移动端全屏展示，桌面端居中限宽（md:max-w-4xl）；
 * 支持 ESC 关闭、左右方向键切换上一个/下一个资产。
 */
function PreviewModal({ asset, canNavigate, onClose, onPrev, onNext }: PreviewModalProps) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (canNavigate && event.key === 'ArrowLeft') onPrev();
      if (canNavigate && event.key === 'ArrowRight') onNext();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [canNavigate, onClose, onPrev, onNext]);

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/85 md:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={asset.name}
    >
      {/* 关闭按钮 */}
      <button
        type="button"
        onClick={onClose}
        aria-label="关闭预览"
        className="absolute right-3 top-3 z-10 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/25 md:right-5 md:top-5"
      >
        <X size={22} />
      </button>

      {canNavigate && (
        <>
          {/* 上一个 */}
          <button
            type="button"
            onClick={onPrev}
            aria-label="上一个资产"
            className="absolute left-2 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/25 md:left-6 md:h-12 md:w-12"
          >
            <ChevronLeft size={26} />
          </button>
          {/* 下一个 */}
          <button
            type="button"
            onClick={onNext}
            aria-label="下一个资产"
            className="absolute right-2 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/25 md:right-6 md:h-12 md:w-12"
          >
            <ChevronRight size={26} />
          </button>
        </>
      )}

      <div className="flex max-h-full w-full flex-col items-center md:max-w-4xl">
        {asset.media_type === 'video' ? (
          <video src={asset.url} controls autoPlay playsInline className="max-h-[72vh] w-full bg-black object-contain md:rounded-lg" />
        ) : (
          <MediaImage src={asset.url} alt={asset.name} className="max-h-[72vh] w-auto max-w-full object-contain md:rounded-lg" />
        )}
        <div className="mt-3 px-4 text-center text-white">
          <div className="text-sm font-medium">{asset.name}</div>
          <div className="mt-1 text-xs text-white/60">{formatDate(asset.created_at)}</div>
        </div>
      </div>
    </div>
  );
}

/**
 * 跨作品资产中心页面：集中浏览所有作品生成的漫画图片、漫画素材与视频素材。
 * 支持按作品 / 类型筛选、分页加载（加载更多）、大图 / 视频预览。
 */
export default function AssetsPage() {
  const [stories, setStories] = useState<{ id: number; title: string }[]>([]);
  const [assets, setAssets] = useState<CrossStoryAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [kind, setKind] = useState('');
  const [storyId, setStoryId] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  /** 请求序号：筛选快速切换时丢弃过期响应 */
  const requestSeqRef = useRef(0);

  /** 按当前筛选条件加载第一页（作品列表 + 资产列表 + 总数） */
  const reload = useCallback(async () => {
    const seq = ++requestSeqRef.current;
    setLoading(true);
    setError(null);
    setPreviewIndex(null);
    try {
      const result = await listAssets({
        kind: kind || undefined,
        story_id: storyId || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      });
      if (seq !== requestSeqRef.current) return;
      setStories(result.stories || []);
      setAssets(result.assets || []);
      setTotal(result.total ?? 0);
    } catch (err) {
      if (seq !== requestSeqRef.current) return;
      setError(err instanceof Error ? err.message : '资产加载失败');
    } finally {
      if (seq === requestSeqRef.current) setLoading(false);
    }
  }, [kind, storyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** 追加加载下一页 */
  const loadMore = useCallback(async () => {
    if (loading || loadingMore) return;
    const seq = ++requestSeqRef.current;
    setLoadingMore(true);
    try {
      const result = await listAssets({
        kind: kind || undefined,
        story_id: storyId || undefined,
        limit: PAGE_SIZE,
        offset: assets.length,
      });
      if (seq !== requestSeqRef.current) return;
      setAssets((prev) => [...prev, ...(result.assets || [])]);
      setTotal(result.total ?? 0);
    } catch (err) {
      if (seq !== requestSeqRef.current) return;
      toast.error(err instanceof Error ? err.message : '加载更多失败');
    } finally {
      if (seq === requestSeqRef.current) setLoadingMore(false);
    }
  }, [assets.length, kind, loading, loadingMore, storyId]);

  /** 当前预览的资产（索引越界时回退 null） */
  const previewAsset = previewIndex != null ? (assets[previewIndex] ?? null) : null;
  const canNavigate = assets.length > 1;

  return (
    <div className="mx-auto w-full max-w-7xl">
      {/* 页头：标题 + 副标题 */}
      <div className="flex flex-col gap-4 border-b border-slate-200 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
            <Images size={16} aria-hidden="true" />
            跨作品资产中心
          </div>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">资产中心</h2>
          <p className="mt-1 text-sm text-slate-500">集中浏览所有作品生成的漫画图片、漫画素材与视频素材。</p>
        </div>
      </div>

      {/* 筛选区：作品下拉 + 类型 Tab */}
      <div className="mt-5 space-y-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <label className="flex w-full flex-col gap-1 md:w-auto md:flex-row md:items-center md:gap-2">
            <span className="text-xs font-medium text-slate-500 md:text-sm">筛选作品</span>
            <select
              value={storyId}
              onChange={(event) => setStoryId(Number(event.target.value))}
              aria-label="按作品筛选"
              className="max-md:min-h-[44px] h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 transition focus:border-blue-400 focus:outline-none md:w-60"
            >
              <option value={0}>全部作品</option>
              {stories.map((story) => (
                <option key={story.id} value={story.id}>
                  {story.title}
                </option>
              ))}
            </select>
          </label>
          <div className="text-sm text-slate-500">共 {total} 项资产</div>
        </div>

        {/* 类型 Tab：移动端横向滚动吸顶，桌面端自动换行 */}
        <div
          role="tablist"
          aria-label="资产类型"
          className="sticky top-0 z-10 -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 max-md:whitespace-nowrap md:mx-0 md:flex-wrap md:px-0"
        >
          {KIND_TABS.map((tab) => {
            const active = tab.key === kind;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setKind(tab.key)}
                className={`max-md:min-h-[44px] inline-flex h-10 shrink-0 items-center rounded-md border px-4 text-sm font-medium transition-colors ${
                  active
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-700'
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 错误态：提示 + 重试 */}
      {error && (
        <div className="mt-5 border-y border-dashed border-slate-300 py-16 text-center">
          <div className="text-sm text-red-600">{error}</div>
          <Button type="button" variant="secondary" className="mt-4" onClick={() => void reload()}>
            重试
          </Button>
        </div>
      )}

      {/* 加载中：骨架屏 */}
      {!error && loading && (
        <div className="mt-5 grid gap-3 md:gap-4 max-md:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <AssetCardSkeleton key={index} />
          ))}
        </div>
      )}

      {/* 资产网格 + 加载更多 */}
      {!error && !loading && assets.length > 0 && (
        <>
          <div className="mt-5 grid gap-3 md:gap-4 max-md:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
            {assets.map((asset, index) => (
              <AssetCard key={asset.id} asset={asset} onOpen={() => setPreviewIndex(index)} />
            ))}
          </div>
          {assets.length < total && (
            <div className="mt-6 flex justify-center">
              <Button
                type="button"
                variant="secondary"
                className="max-md:min-h-[44px]"
                loading={loadingMore}
                onClick={() => void loadMore()}
              >
                加载更多（{assets.length}/{total}）
              </Button>
            </div>
          )}
        </>
      )}

      {/* 空态 */}
      {!error && !loading && assets.length === 0 && (
        <div className="mt-5 flex flex-col items-center gap-2 border-y border-dashed border-slate-300 py-16 text-center">
          <Inbox size={32} className="text-slate-300" aria-hidden="true" />
          <div className="text-sm text-slate-500">暂无资产</div>
        </div>
      )}

      {/* 预览弹层：大图 / 大视频 */}
      {previewAsset && (
        <PreviewModal
          asset={previewAsset}
          canNavigate={canNavigate}
          onClose={() => setPreviewIndex(null)}
          onPrev={() =>
            setPreviewIndex((current) => (current == null ? null : (current - 1 + assets.length) % assets.length))
          }
          onNext={() => setPreviewIndex((current) => (current == null ? null : (current + 1) % assets.length))}
        />
      )}
    </div>
  );
}
