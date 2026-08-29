import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import VideoCanvasPanel from './VideoCanvasPanel';
import AssetManagementModal from './AssetManagementModal';
import { getStory, listStylePresets, listStoryVideoAssets, type Story, type VideoAsset, type VideoStylePreset } from '../api';
import { confirm } from '../lib/confirm';
import { LoadingOverlay } from './ui/LoadingOverlay';

interface MangaDramaWorkspacePageProps {
  storyId: number;
  onBack: () => void;
}

/**
 * 漫剧创作画布工作台：全屏画布模式，不加载小说章节列表与分镜列表工作流。
 * 复用 VideoCanvasPanel（chapterId 不传 → 画布绑定到项目级）；
 * 资产分析管理走故事级资产接口，保证角色/场景/道具跨单元一致性。
 */
export default function MangaDramaWorkspacePage({ storyId, onBack }: MangaDramaWorkspacePageProps) {
  const [story, setStory] = useState<Story | null>(null);
  const [stylePresets, setStylePresets] = useState<VideoStylePreset[]>([]);
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [assetManagementOpen, setAssetManagementOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);

  const loadAssets = useCallback(async () => {
    try {
      const data = await listStoryVideoAssets(storyId);
      setAssets(data.assets || []);
    } catch {
      setAssets([]);
    }
  }, [storyId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [storyRes, presetsRes] = await Promise.all([
          getStory(storyId),
          listStylePresets().catch(() => ({ presets: [] as VideoStylePreset[] })),
        ]);
        if (cancelled) return;
        setStory(storyRes as unknown as Story);
        setStylePresets(presetsRes.presets || []);
      } catch {
        if (!cancelled) setStory(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    void loadAssets();
    return () => { cancelled = true; };
  }, [storyId, loadAssets]);

  const handleDirtyChange = useCallback((next: boolean) => {
    dirtyRef.current = next;
    setDirty(next);
  }, []);

  const handleBack = useCallback(async () => {
    if (dirtyRef.current) {
      const discard = await confirm({
        title: '未保存的画布修改',
        message: '返回项目列表将放弃当前未保存的节点、连线和配置修改。',
        confirmText: '放弃修改',
        danger: true,
      });
      if (!discard) return;
    }
    onBack();
  }, [onBack]);

  const canvasKey = useMemo(() => `manga-drama-canvas-${storyId}`, [storyId]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#f5f7fb]">
      {loading && <LoadingOverlay visible message="正在打开漫剧画布…" />}
      {/* 顶部栏 */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-[#d7e3f4] bg-white px-3">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={() => void handleBack()}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50"
          >
            <ArrowLeft size={13} />
            返回项目
          </button>
          <span className="truncate text-sm font-medium text-slate-900">{story?.title || '漫剧创作'}</span>
          <span className="hidden rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-600 sm:inline-flex">画布模式</span>
        </div>
        {dirty && <span className="text-[11px] text-amber-500">有未保存修改</span>}
      </div>
      {/* 画布区：storyId 绑定项目，不传 chapterId */}
      <div className="min-h-0 flex-1">
        <VideoCanvasPanel
          key={canvasKey}
          storyId={storyId}
          assets={assets}
          stylePresets={stylePresets}
          onDirtyChange={handleDirtyChange}
          onOpenAssetManagement={() => setAssetManagementOpen(true)}
        />
      </div>
      {assetManagementOpen && (
        <AssetManagementModal
          storyId={storyId}
          onClose={() => setAssetManagementOpen(false)}
          onAssetsChanged={() => void loadAssets()}
        />
      )}
    </div>
  );
}
