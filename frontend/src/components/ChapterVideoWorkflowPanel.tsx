import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Clapperboard,
  Film,
  Home,
  Image as ImageIcon,
  Loader2,
  Palette,
  RefreshCcw,
  Sparkles,
  Trash2,
  UserRound,
  Wand2,
  SquarePen,
  StepForward,
  PanelBottomOpen,
  SkipForward,
} from 'lucide-react';
import type { ChapterVideoWorkflow, StoryVideoCharacter, VideoAsset } from '../api';
import { saveChapterShotPrompts, replaceVideoAsset, regenerateVideoAsset, uploadShotStoryboard, uploadShotVideo, createVideoAsset, toPublicVideoAssetUrl } from '../api';
import { canStartChapterWorkflowParse } from './chapterWorkflowUtils';

import VideoCardWorkbench from './VideoCardWorkbench';
import { videoGenStore } from '../videoGenStore';
import {
  buildCharacterWorkbenchResources,
  buildWorkbenchBusyKey,
  findCharacterAssetByName,
  findBusyWorkbenchResourceId,
  isWorkbenchResourceBusy,
  uploadCharacterWorkbenchAsset,
  uploadWorkbenchAsset,
} from './videoWorkbenchUtils';

interface ChapterVideoWorkflowPanelProps {
  workflow: ChapterVideoWorkflow | null;
  workflowLoading: boolean;
  workflowRunning: boolean;
  chapterAssets: VideoAsset[];
  selectedReferenceIds: number[];
  selectedStyle: string;
  styleReferenceImageUrl?: string | null;
  stylePresets: Array<{ id: number; name: string; category: string }>;
  concatVideoUrl: string | null;
  selectedShotIds: Set<number>;
  skippedShotIds: Set<number>;
  onRefreshWorkflow: () => Promise<void> | void;
  onConcatWorkflow: () => Promise<void> | void;
  onRegenerateStoryboard: (shotId: number, refAssetIds?: number[]) => Promise<void> | void;
  onRegenerateVideo: (shotId: number, refAssetIds?: number[], aspectRatio?: '16:9' | '9:16', promptOverride?: string) => Promise<void> | void;
  onStyleChange: (style: string, referenceImageUrl?: string | null) => void;
  onOpenStyleSelector?: () => void;
  onParseShots: () => Promise<void> | void;
  onGenerateShotDetails: (shotIds: number[]) => Promise<void> | void;
  onGenerateStoryboards: (shotIds: number[]) => Promise<void> | void;
  onGenerateVideos: (shotIds: number[]) => Promise<void> | void;
  onToggleShotSelection: (shotId: number) => void;
  onSelectAllShots: () => void;
  onSkipShot: (shotId: number) => void;
  onReanalyzePrompt: (shotIds: number[]) => Promise<void> | void;
  onReanalyzeCurrentCharacter?: (shotId: number, characterName: string) => Promise<void>;
  onStoryboardPromptChange: (shotId: number, value: string) => void;
  onDeleteChapterAsset?: (assetId: number) => Promise<void>;
  onDeleteStoryboard?: (shotId: number) => Promise<void>;
  onDeleteVideo?: (shotId: number) => Promise<void>;
  videoCharacters: StoryVideoCharacter[];
  characterLoading: boolean;
  onGenerateCharacters: () => Promise<void> | void;
  onResetWorkflow?: () => Promise<void> | void;
  parsing?: boolean;
  videoAspectRatio?: '16:9' | '9:16';
  onVideoAspectRatioChange?: (value: '16:9' | '9:16') => void;
}

function shotStatusLabel(status: string): string {
  switch (status) {
    case 'pending':
      return '待处理';
    case 'storyboard_generating':
      return '故事版生成中';
    case 'storyboard_ready':
      return '故事版已完成';
    case 'video_generating':
      return '视频生成中';
    case 'video_ready':
      return '视频已完成';
    case 'failed':
      return '失败';
    default:
      return status;
  }
}

function toAssetUrl(filePath?: string | null): string {
  return toPublicVideoAssetUrl(filePath) || '';
}

export default function ChapterVideoWorkflowPanel({
  workflow,
  workflowLoading,
  workflowRunning,
  chapterAssets,
  selectedReferenceIds,
  selectedStyle,
  styleReferenceImageUrl,
  concatVideoUrl,
  selectedShotIds,
  skippedShotIds,
  onRefreshWorkflow,
  onConcatWorkflow,
  onRegenerateStoryboard,
  onRegenerateVideo,
  onOpenStyleSelector,
  onParseShots,
  onGenerateStoryboards,
  onGenerateVideos,
  onToggleShotSelection,
  onSelectAllShots,
  onSkipShot,
  onReanalyzePrompt,
  onReanalyzeCurrentCharacter,
  onDeleteChapterAsset,
  onDeleteStoryboard,
  onDeleteVideo,
  onResetWorkflow,
  parsing,
  videoAspectRatio = '16:9',
  onVideoAspectRatioChange,
  characterLoading,
}: ChapterVideoWorkflowPanelProps) {
  const [concatModalOpen, setConcatModalOpen] = useState(false);

  const [videoWorkbench, setVideoWorkbench] = useState<{
    shotId: number;
    type: 'character' | 'storyboard' | 'video' | 'scene';
    assetId?: number;
  } | null>(null);
  const [workbenchBusyMap, setWorkbenchBusyMap] = useState<Record<string, string>>({});

  const [workbenchRefAssetIds, setWorkbenchRefAssetIds] = useState<number[]>([]);

  // 订阅 videoGenStore 以响应式更新视频卡片 loading 状态
  const [, setVideoGenTick] = useState(0);
  useEffect(() => videoGenStore.subscribe(() => setVideoGenTick((t) => t + 1)), []);

  const normalizeAssetText = (value?: string | null) => (value || '').trim().toLowerCase();

  const collectRecommendedAssetIds = (shot: ChapterVideoWorkflow['shots'][number]): number[] => {
    const ids = new Set<number>(selectedReferenceIds);
    const sceneCandidates = (shot.scene_asset_candidates || []).map(normalizeAssetText).filter(Boolean);
    const propCandidates = (shot.key_props || []).map(normalizeAssetText).filter(Boolean);

    chapterAssets.forEach((asset) => {
      const name = normalizeAssetText(asset.name);
      const prompt = normalizeAssetText(asset.prompt);
      const isSceneAsset = asset.asset_type === 'scene_reference' || asset.asset_type === 'scene' || asset.asset_type === 'background';
      const isPropAsset = asset.asset_type === 'prop_reference';

      if (isSceneAsset && sceneCandidates.some((candidate) => name.includes(candidate) || prompt.includes(candidate) || candidate.includes(name))) {
        ids.add(asset.id);
      }
      if (isPropAsset && propCandidates.some((candidate) => name.includes(candidate) || prompt.includes(candidate) || candidate.includes(name))) {
        ids.add(asset.id);
      }
    });

    return Array.from(ids);
  };

  const characterAssets = useMemo(
    () => chapterAssets.filter((asset) => asset.asset_type === 'character_reference' || asset.asset_type === 'character'),
    [chapterAssets],
  );

  const activeShotIds = useMemo(
    () => [...selectedShotIds].filter((id) => !skippedShotIds.has(id)),
    [selectedShotIds, skippedShotIds],
  );
  const sortedShots = useMemo(
    () => [...(workflow?.shots ?? [])].sort((a, b) => a.shot_index - b.shot_index),
    [workflow?.shots],
  );

  useEffect(() => {
    if (!videoWorkbench || (videoWorkbench.type !== 'storyboard' && videoWorkbench.type !== 'video')) return;
    const shot = sortedShots.find((item) => item.id === videoWorkbench.shotId);
    if (!shot) return;
    setWorkbenchRefAssetIds(collectRecommendedAssetIds(shot));
  }, [videoWorkbench, sortedShots, chapterAssets, selectedReferenceIds]);

  const runWithWorkbenchBusy = useCallback(async (busyKey: string, busyKind: string, action: () => Promise<void>) => {
    setWorkbenchBusyMap((prev) => ({ ...prev, [busyKey]: busyKind }));
    try {
      await action();
    } finally {
      setWorkbenchBusyMap((prev) => {
        const next = { ...prev };
        delete next[busyKey];
        return next;
      });
    }
  }, []);



  if (workflowLoading && !videoWorkbench) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500">
        <Loader2 size={22} className="animate-spin" />
      </div>
    );
  }

  const status = workflow?.workflow_status ?? '';
  const retryHint = workflow && (workflow.retry_count ?? 0) > 0
    ? `自动重试 ${workflow.retry_count}/${workflow.max_retries ?? 0}`
    : '';

  const canParse = canStartChapterWorkflowParse({
    workflowExists: Boolean(workflow),
    status,
    hasShots: Boolean(workflow?.shots?.length),
    parsing: Boolean(parsing),
    workflowRunning,
  });
  const canStoryboard = ['shots_ready', 'generating_storyboards', 'failed'].includes(status) && !workflowRunning;
  const canVideo = ['storyboards_ready', 'generating_videos', 'failed'].includes(status) && !workflowRunning;
  const canConcat = ['completed', 'videos_ready', 'storyboards_ready', 'generating_videos', 'shots_ready'].includes(status) && !workflowRunning;

  const storyboardReadyShots = workflow?.shots?.filter((shot) => shot.status === 'storyboard_ready') ?? [];
  const videoReadyShots = workflow?.shots?.filter((shot) => shot.status === 'video_ready') ?? [];

  const getCharacterThumbnails = (names: string[] | null | undefined): Array<{ name: string; thumbnailUrl: string | null }> => {
    if (!names?.length) return [];
    return names.map((name) => {
      const trimmed = name.trim();
      const asset = findCharacterAssetByName(characterAssets, trimmed);
      const thumbnailUrl = asset?.file_path || null;
      return { name: trimmed, thumbnailUrl };
    });
  };
  return (
    <div className="flex h-full flex-col">
      {/* ── 顶部：阶段操作工具栏 ── */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#d7e3f4] bg-white/80 px-4 py-2.5 backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="mr-1 text-sm font-medium text-slate-900">电影分镜流水线</span>
          <button
            onClick={() => onOpenStyleSelector?.()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#d7e3f4] bg-white px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            <Palette size={14} /> {selectedStyle || '选择风格'}
            {styleReferenceImageUrl && <span className="text-blue-500">(自定义)</span>}
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => void onParseShots()}
            disabled={!canParse}
            title="阶段1：将章节正文拆解为镜头列表"
            className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {parsing ? <Loader2 size={12} className="animate-spin" /> : <StepForward size={12} />}
            {parsing ? '拆镜中...' : '拆镜'}
          </button>
          <button
            onClick={() => setConcatModalOpen(true)}
            disabled={!canConcat}
            title="阶段4：拼接已完成视频为整章成片"
            className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <PanelBottomOpen size={12} />
            拼接
          </button>
          <button
            onClick={() => void onRefreshWorkflow()}
            disabled={workflowRunning}
            className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-white disabled:opacity-50"
          >
            <RefreshCcw size={12} />
            刷新
          </button>
          {onResetWorkflow && workflow && (
            <button
              onClick={() => {
                if (window.confirm('确定要重置工作流吗？将清除所有镜头和生成数据，此操作不可撤销。')) {
                  void onResetWorkflow();
                }
              }}
              className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-2.5 py-1.5 text-xs text-rose-600 hover:bg-rose-50"
            >
              <Trash2 size={12} />
              重置
            </button>
          )}
        </div>
      </div>

      {/* ── 空状态 ── */}
      {(!workflow || (!parsing && sortedShots.length === 0)) && (
        <div className="flex flex-1 items-center justify-center">
          <div className="max-w-md px-8 text-center text-slate-400">
            <Clapperboard size={46} className="mx-auto mb-3 opacity-40" />
            <p className="text-sm text-slate-500">
              选择视频风格和角色参考图后，点击顶部「拆镜」按钮将本章内容拆分为镜头列表。
            </p>
          </div>
        </div>
      )}

      {/* ── 工作流内容 ── */}
      {workflow && (
        <>
          <div className="relative flex flex-1 min-h-0 gap-4 overflow-hidden px-4 py-4">
            {/* 拆镜加载遮罩 */}
            {parsing && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 backdrop-blur-sm">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 size={32} className="animate-spin text-blue-500" />
                  <span className="text-sm font-medium text-slate-600">{workflow?.message || '正在拆镜...'}</span>
                  {retryHint && <span className="text-xs text-amber-600">{retryHint}</span>}
                </div>
              </div>
            )}
            {/* 后台任务执行中：不使用全屏遮罩，通过各按钮 disabled 状态和状态标签提示用户 */}
            {/* ── 镜头列表 ── */}
            <div className="flex-1 min-w-0 overflow-y-auto">
            {/* 镜头操作栏 */}
              {sortedShots.length > 0 && (
                <div className="mb-3 flex items-center justify-between">
                <button
                  onClick={onSelectAllShots}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  <SquarePen size={11} />
                  {selectedShotIds.size === workflow.shots.length ? '取消全选' : '全选镜头'}
                </button>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  已选 {selectedShotIds.size} / {sortedShots.length} 镜
                  {skippedShotIds.size > 0 && (
                    <span className="text-amber-500">（跳过 {skippedShotIds.size}）</span>
                  )}
                  {activeShotIds.length > 0 && canStoryboard && (
                    <button
                      onClick={() => void onGenerateStoryboards(activeShotIds)}
                      className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs text-white hover:bg-blue-700"
                    >
                      为选中生成故事版
                    </button>
                  )}
                  {activeShotIds.length > 0 && canVideo && (
                    <button
                      onClick={() => void onGenerateVideos(activeShotIds)}
                      className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs text-white hover:bg-blue-700"
                    >
                      为选中生成视频
                    </button>
                  )}
                </div>
              </div>
            )}

            <div className="space-y-3">
              {sortedShots.map((shot) => {
                const isSelected = selectedShotIds.has(shot.id);
                const isFailed = shot.status === 'failed';
                const hasStoryboard = !!shot.storyboard_image_url;
                const hasVideo = !!shot.video_url;

                return (
                  <div
                    key={shot.id}
                    className={`rounded-2xl border bg-white p-4 shadow-sm transition-colors ${
                      isSelected ? 'border-blue-400 ring-1 ring-blue-200' : 'border-[#d7e3f4]'
                    }`}
                  >
                    <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                      {/* 左侧：镜头信息 + 勾选 */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => onToggleShotSelection(shot.id)}
                            className="h-4 w-4 rounded border-[#d7e3f4] text-blue-600 focus:ring-blue-300"
                          />
                          <span className="text-sm font-semibold text-slate-900">镜头 {shot.shot_index}</span>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[11px] ${
                              isFailed
                                ? 'bg-rose-100 text-rose-600'
                                : hasVideo
                                  ? 'bg-emerald-50 text-emerald-600'
                                  : hasStoryboard
                                    ? 'bg-violet-50 text-violet-600'
                                    : !shot.camera_plan
                                      ? 'bg-amber-50 text-amber-600'
                                      : 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {isFailed
                              ? shotStatusLabel(shot.status)
                              : hasVideo
                                ? shotStatusLabel(shot.status)
                                : hasStoryboard
                                  ? shotStatusLabel(shot.status)
                                  : !shot.camera_plan
                                    ? '待生成详情'
                                    : shotStatusLabel(shot.status)
                            }
                          </span>
                          {shot.characters && shot.characters.length > 0 && (
                            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-600">
                              <span className="inline-flex items-center gap-1"><UserRound size={10} /> {shot.characters.join('、')}</span>
                            </span>
                          )}
                        </div>
                        <p className="mt-2 text-sm text-slate-700">{shot.story_summary || '暂无情节摘要'}</p>
                        <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-slate-500 md:grid-cols-2">
                          <div>场景：{shot.scene_location || '未明确'} / {shot.time_of_day || '未明确'}</div>
                          <div>运镜：{shot.camera_plan || '未明确'}</div>
                          <div>动作：{shot.motion_plan || '未明确'}</div>
                          <div>情绪：{shot.emotion_plan || '未明确'}</div>
                        </div>
                        {shot.continuity_notes && (
                          <div className="mt-2 text-xs text-slate-500">连续性：{shot.continuity_notes}</div>
                        )}

                        {/* 失败错误信息 */}
                        {shot.error_message && (
                          <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
                            {shot.error_message}
                          </div>
                        )}

                        </div>

                      {/* 右侧：故事版/视频预览 */}
                      <div className="grid shrink-0 grid-cols-2 gap-3 sm:grid-cols-4 xl:w-[880px]">
                        <button
                          type="button"
                          onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'character', assetId: undefined })}
                          className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <UserRound size={12} /> 角色资产
                          </div>
                          <div className="flex h-32 flex-col items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                            {(() => {
                              if (characterLoading && shot.characters?.length) {
                                return (
                                  <div className="flex h-full w-full flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
                                    <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                                    <span className="mt-2 text-sm text-blue-600">角色资产生成中...</span>
                                  </div>
                                );
                              }
                              const thumbnails = getCharacterThumbnails(shot.characters);
                              if (thumbnails.length === 0) {
                                return <div>暂无角色</div>;
                              }
                              return (
                                <div className="flex flex-wrap gap-1 p-1">
                                  {thumbnails.slice(0, 4).map((thumb) => (
                                    <div key={thumb.name} className="flex flex-col items-center">
                                      {thumb.thumbnailUrl ? (
                                        <img
                                          src={toAssetUrl(thumb.thumbnailUrl)}
                                          alt={thumb.name}
                                          className="h-12 w-12 rounded-lg object-cover"
                                        />
                                      ) : (
                                        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100 text-[10px] text-slate-400">
                                          <UserRound size={16} />
                                        </div>
                                      )}
                                      <span className="mt-0.5 max-w-[48px] truncate text-[10px] text-slate-500">{thumb.name}</span>
                                    </div>
                                  ))}
                                  {thumbnails.length > 4 && (
                                    <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100 text-[10px] text-slate-400">
                                      +{thumbnails.length - 4}
                                    </div>
                                  )}
                                </div>
                              );
                            })()}
                          </div>
                        </button>

                        <button
                          type="button"
                          onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'scene' })}
                          className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <Home size={14} /> 场景 & 道具
                          </div>
                          {(() => {
                            const sceneState = videoGenStore.get(shot.id, 'scene');
                            if (sceneState?.active) {
                              return (
                                <div className="flex h-32 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
                                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                                  <span className="mt-2 text-sm text-blue-600">场景生成中...</span>
                                  {sceneState.statusMsg && (
                                    <span className="mt-1 text-xs text-blue-500">{sceneState.statusMsg}</span>
                                  )}
                                </div>
                              );
                            }
                            return (
                              <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                                待生成
                              </div>
                            );
                          })()}
                        </button>

                        <button
                          type="button"
                          onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'storyboard' })}
                          className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <ImageIcon size={12} /> 故事版
                          </div>
                          {(() => {
                            const sbState = videoGenStore.get(shot.id, 'storyboard');
                            if (sbState?.active) {
                              return (
                                <div className="flex h-32 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
                                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                                  <span className="mt-2 text-sm text-blue-600">故事版生成中...</span>
                                  {sbState.statusMsg && (
                                    <span className="mt-1 text-xs text-blue-500">{sbState.statusMsg}</span>
                                  )}
                                </div>
                              );
                            }
                            if (hasStoryboard) {
                              return (
                                <img
                                  src={toAssetUrl(shot.storyboard_image_url)}
                                  alt={`镜头 ${shot.shot_index} 故事版`}
                                  className="h-32 w-full rounded-lg object-cover"
                                />
                              );
                            }
                            return (
                              <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                                暂无故事版
                              </div>
                            );
                          })()}
                        </button>

                        <button
                          type="button"
                          onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'video' })}
                          className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <Film size={12} /> 视频
                          </div>
                          {(() => {
                            const videoState = videoGenStore.get(shot.id);
                            const isGenerating = videoState?.active;

                            if (hasVideo) {
                              return (
                                <video
                                  src={toAssetUrl(shot.video_url)}
                                  controls
                                  className="h-32 w-full rounded-lg bg-slate-950 object-contain"
                                />
                              );
                            } else if (isGenerating) {
                              return (
                                <div className="flex h-32 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
                                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                                  <span className="mt-2 text-sm text-blue-600">视频生成中...</span>
                                  {videoState.statusMsg && (
                                    <span className="mt-1 text-xs text-blue-500">{videoState.statusMsg}</span>
                                  )}
                                </div>
                              );
                            } else {
                              return (
                                <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                                  暂无视频
                                </div>
                              );
                            }
                          })()}
                        </button>
                      </div>
                    </div>

                    {/* 底部操作按钮 */}
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                       <button
                         onClick={() => void onReanalyzePrompt([shot.id])}
                         disabled={workflowRunning}
                         className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-3 py-1.5 text-xs text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                       >
                         <Sparkles size={12} /> {shot.storyboard_prompt ? '重新分析提示词' : '分析提示词'}
                       </button>
                       {isFailed && (
                          <>
                           {!skippedShotIds.has(shot.id) && (
                            <button
                              onClick={() => void onSkipShot(shot.id)}
                              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-50"
                            >
                              <SkipForward size={12} /> 跳过此镜头
                            </button>
                          )}
                          {skippedShotIds.has(shot.id) && (
                            <span className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-600">
                              已跳过
                            </span>
                          )}
                        </>
                      )}
                      {hasStoryboard && !hasVideo && (
                        <button
                          onClick={() => void onRegenerateStoryboard(shot.id)}
                          className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                        >
                          <Sparkles size={12} /> 重生故事版
                        </button>
                      )}
                      {hasVideo && (
                        <>
                          <button
                            onClick={() => void onRegenerateVideo(shot.id, undefined, videoAspectRatio)}
                            className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                          >
                            <Wand2 size={12} /> 重生视频
                          </button>
                          <a
                            href={toAssetUrl(shot.video_url)}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs text-white hover:bg-emerald-700"
                          >
                            <CheckCircle2 size={12} /> 打开视频
                          </a>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            </div>
          </div>
        </>
      )}

      {concatModalOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setConcatModalOpen(false)}>
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">整章成片</h3>
              <button onClick={() => setConcatModalOpen(false)} className="rounded-full bg-slate-100 p-1.5 text-slate-500 hover:bg-slate-200">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M12 4L4 12M4 4l8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
              </button>
            </div>
            <div className="text-sm text-slate-500">
              {storyboardReadyShots.length} 镜故事版 · {videoReadyShots.length} 镜视频
            </div>
            {concatVideoUrl ? (
              <video src={toAssetUrl(concatVideoUrl)} controls className="mt-4 h-48 w-full rounded-xl bg-slate-950 object-contain" />
            ) : (
              <div className="mt-4 flex h-48 items-center justify-center rounded-xl border border-dashed border-[#d7e3f4] bg-slate-50 text-sm text-slate-400">
                暂无成片
              </div>
            )}
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => { void onConcatWorkflow(); }}
                disabled={!canConcat}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-40"
              >
                拼接
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 二级工作台 */}
      {videoWorkbench && (() => {
        const workbenchShot = sortedShots.find(s => s.id === videoWorkbench.shotId);
        if (!workbenchShot) return null;

        const shotCharacterNames = (workbenchShot.characters || []) as string[];
        const workbenchStoryboardAssets = characterAssets.filter((a) =>
          shotCharacterNames.length === 0 || shotCharacterNames.some((name) =>
            (a.name || '').includes(name) || (a.prompt || '').includes(name)
          )
        );
        const shotStoryboardAssets = sortedShots
          .filter((s) => s.storyboard_image_url)
          .map((s) => ({
            id: -(s.id + 300000),
            file_path: s.storyboard_image_url || '',
            name: `镜头${s.shot_index} 故事版`,
            prompt: s.storyboard_prompt || null,
          }));

        let resources: Array<{ id: number; assetId?: number; url: string; prompt?: string; label?: string; characterName?: string; hasAsset?: boolean }>;
        let onRegenerate: (resourceId: number) => Promise<void>;
        let onUploadReplace: (resourceId: number, file: File) => Promise<void>;
        let onDelete: (resourceId: number) => Promise<void>;
        let onRedraw: (resourceId: number, prompt: string, mask?: string) => Promise<void>;
        let onPromptSave: ((resourceId: number, prompt: string) => Promise<void>) | undefined;
        let onWorkbenchReanalyze: ((resourceId: number) => Promise<void>) | undefined;
        const getBusyType = (resource: { characterName?: string; label?: string; id: number }) => {
          if (videoWorkbench.type === 'character') return 'character' as const;
          if (videoWorkbench.type === 'storyboard') return 'storyboard' as const;
          if (videoWorkbench.type === 'video') return 'video' as const;
          return resource.characterName === '__scene__' ? 'scene' as const : 'prop' as const;
        };
        const runForResource = async (
          resource: { characterName?: string; label?: string; id: number },
          busyKind: string,
          action: () => Promise<void>,
        ) => {
          const busyKey = buildWorkbenchBusyKey(getBusyType(resource), workbenchShot.id, resource);
          await runWithWorkbenchBusy(busyKey, busyKind, action);
        };

        if (videoWorkbench.type === 'character') {
          resources = buildCharacterWorkbenchResources(
            workbenchShot.characters,
            characterAssets,
            workbenchShot.character_prompts ?? null,
          ).map((resource) => ({
            id: resource.id,
            assetId: resource.assetId,
            url: resource.url,
            prompt: resource.prompt,
            label: resource.label,
            characterName: resource.characterName,
            hasAsset: resource.hasAsset,
          }));
          onRegenerate = async (resourceId: number) => {
            const resource = resources.find(r => r.id === resourceId);
            if (!resource) return;
            let assetId = resource?.assetId;
            await runForResource(resource, 'regenerate', async () => {
              if (!assetId && workflow) {
                const created = await createVideoAsset(workflow.chapter_id, {
                  asset_type: 'character_reference',
                  name: resource?.characterName || resource?.label || '角色资产',
                  file_path: '',
                  prompt: resource?.prompt || '',
                });
                assetId = created.id;
              }
              if (assetId) {
                await regenerateVideoAsset(assetId, resource?.prompt);
                if (onRefreshWorkflow) await onRefreshWorkflow();
              }
            });
          };
          onUploadReplace = async (resourceId: number, file: File) => {
            const asset = resources.find(r => r.id === resourceId);
            if (!asset || !workflow) return;
            await runForResource(asset, 'upload', async () => {
              await uploadCharacterWorkbenchAsset({ ...asset, prompt: asset.prompt || '', label: asset.label || '' }, workflow.chapter_id, file, createVideoAsset, replaceVideoAsset, onRefreshWorkflow);
            });
          };
          onDelete = async (resourceId: number) => {
            const resource = resources.find(r => r.id === resourceId);
            if (!resource || resourceId <= 0 || !onDeleteChapterAsset) return;
            await runForResource(resource, 'delete', async () => {
              await onDeleteChapterAsset(resourceId);
            });
          };
          onRedraw = async () => {};
          onPromptSave = undefined;
          onWorkbenchReanalyze = onReanalyzeCurrentCharacter
            ? async (_resourceId: number) => {
              const currentIdx = resources.findIndex(r => r.id === _resourceId);
              const charName = resources[currentIdx >= 0 ? currentIdx : 0]?.characterName;
              if (charName && workbenchShot) {
                  const resource = resources[currentIdx >= 0 ? currentIdx : 0];
                  if (!resource) return;
                  await runForResource(resource, 'reanalyze', async () => {
                    await onReanalyzeCurrentCharacter(workbenchShot.id, charName);
                  });
                }
              }
            : undefined;
        } else if (videoWorkbench.type === 'storyboard') {
          resources = [{
            id: workbenchShot.id,
            url: toAssetUrl(workbenchShot.storyboard_image_url),
            prompt: workbenchShot.storyboard_prompt ?? '',
          }];
          onRegenerate = async (resourceId: number) => {
            const resource = resources[0];
            await runForResource(resource, 'regenerate', async () => {
              await onRegenerateStoryboard(resourceId, workbenchRefAssetIds);
            });
          };
          onUploadReplace = async (resourceId: number, file: File) => {
            const resource = resources[0];
            await runForResource(resource, 'upload', async () => {
              await uploadShotStoryboard(resourceId, file);
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
          onDelete = async (resourceId: number) => {
            const resource = resources[0];
            if (!onDeleteStoryboard) return;
            await runForResource(resource, 'delete', async () => {
              await onDeleteStoryboard(resourceId);
            });
          };
          onRedraw = async (resourceId: number, _prompt: string) => {
            const resource = resources[0];
            await runForResource(resource, 'redraw', async () => {
              await onRegenerateStoryboard(resourceId, workbenchRefAssetIds);
            });
          };
          onPromptSave = async (resourceId: number, prompt: string) => {
            const resource = resources[0];
            await runForResource(resource, 'savePrompt', async () => {
              await saveChapterShotPrompts(resourceId, { storyboard_prompt: prompt });
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
          onWorkbenchReanalyze = async (resourceId: number) => {
            const resource = resources[0];
            await runForResource(resource, 'reanalyze', async () => {
              await onReanalyzePrompt([resourceId]);
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
        } else if (videoWorkbench.type === 'video') {
          resources = [{
            id: workbenchShot.id,
            url: toAssetUrl(workbenchShot.video_url),
            prompt: workbenchShot.video_prompt ?? '',
          }];
          onRegenerate = async (resourceId: number, aspectRatio?: '16:9' | '9:16', promptOverride?: string) => {
            const resource = resources[0];
            await runForResource(resource, 'regenerate', async () => {
              await onRegenerateVideo(resourceId, workbenchRefAssetIds, aspectRatio ?? videoAspectRatio, promptOverride);
            });
          };
          onUploadReplace = async (resourceId: number, file: File) => {
            const resource = resources[0];
            await runForResource(resource, 'upload', async () => {
              await uploadShotVideo(resourceId, file);
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
          onDelete = async (resourceId: number) => {
            const resource = resources[0];
            if (!onDeleteVideo) return;
            await runForResource(resource, 'delete', async () => {
              await onDeleteVideo(resourceId);
            });
          };
          onRedraw = async (resourceId: number, _prompt: string) => {
            const resource = resources[0];
            await runForResource(resource, 'redraw', async () => {
              await onRegenerateVideo(resourceId, workbenchRefAssetIds, videoAspectRatio);
            });
          };
          onPromptSave = async (resourceId: number, prompt: string) => {
            const resource = resources[0];
            await runForResource(resource, 'savePrompt', async () => {
              await saveChapterShotPrompts(resourceId, { video_prompt: prompt });
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
          onWorkbenchReanalyze = async (resourceId: number) => {
            const resource = resources[0];
            await runForResource(resource, 'reanalyze', async () => {
              await onReanalyzePrompt([resourceId]);
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
        } else if (videoWorkbench.type === 'scene') {
          const extractSceneName = (prompt?: string | null): string => {
            if (!prompt) return '';
            const lines = prompt.split('\n').map(l => l.replace(/【[^】]*】/g, '').trim()).filter(Boolean);
            for (const line of lines) {
              if (line.startsWith('Part') || line.startsWith('ENVIRONMENT')) continue;
              const cleaned = line.replace(/^[：:]\s*/, '');
              if (cleaned.length >= 2) return cleaned.slice(0, 20);
            }
            return '';
          };
          // 场景资产匹配：ID → 归一化名称（去掉 Scene - 前缀，双向包含）→ 提示词 → 任意有图的场景
          const existingSceneAsset = (workbenchShot.scene_reference_ids || [])
            .map((assetId) => chapterAssets.find((asset) => asset.id === assetId))
            .find(Boolean)
            || (() => {
              if (!workbenchShot.scene_location) return null;
              const targetLoc = workbenchShot.scene_location.trim().toLowerCase();
              return chapterAssets.find((asset) => {
                if (asset.asset_type !== 'scene_reference') return false;
                const normalizedName = (asset.name || '').replace(/^Scene\s*-\s*/i, '').trim().toLowerCase();
                return normalizedName.includes(targetLoc) || targetLoc.includes(normalizedName);
              });
            })()
            || chapterAssets.find((asset) => asset.asset_type === 'scene_reference' && asset.prompt === workbenchShot.scene_prompt)
            || chapterAssets.find((asset) => asset.asset_type === 'scene_reference' && asset.file_path);
          const sceneRes = workbenchShot.scene_prompt
            ? [{ id: workbenchShot.id + 100000, assetId: existingSceneAsset?.id, url: existingSceneAsset?.file_path || '', prompt: workbenchShot.scene_prompt, label: existingSceneAsset?.name || workbenchShot.scene_location || extractSceneName(workbenchShot.scene_prompt) || '场景', characterName: '__scene__' }]
            : [];
          // 道具资产匹配：ID → 归一化名称（去掉 Prop - 前缀，忽略大小写）→ 提示词
          const propRes = (workbenchShot.prop_prompts ?? []).map((p, i) => {
            const targetName = (p.name || `道具${i + 1}`).trim().toLowerCase();
            const findPropAsset = () => chapterAssets.find((asset) => {
              if (asset.asset_type !== 'prop_reference') return false;
              const normalizedName = (asset.name || '').replace(/^Prop\s*-\s*/i, '').trim().toLowerCase();
              return normalizedName === targetName || (asset.prompt || '').trim() === p.prompt;
            });
            const matchedAsset = workbenchShot.prop_reference_ids?.[i]
              ? chapterAssets.find((asset) => asset.id === workbenchShot.prop_reference_ids![i])
              : null;
            const existingPropAsset = matchedAsset || findPropAsset();
            return {
              assetId: existingPropAsset?.id,
              id: workbenchShot.id + 200000 + i,
              url: existingPropAsset?.file_path || '',
              prompt: p.prompt,
              label: p.name || `道具${i + 1}`,
              characterName: p.name || `道具${i + 1}`,
            };
          });
          resources = [...sceneRes, ...propRes];
          onRegenerate = async (resourceId: number) => {
            const r = resources.find(res => res.id === resourceId);
            if (!r || !workflow) return;
            await runForResource(r, 'regenerate', async () => {
              let assetId = r.assetId;
              if (!assetId) {
                const created = await createVideoAsset(workflow.chapter_id, {
                  asset_type: r.characterName === '__scene__' ? 'scene_reference' : 'prop_reference',
                  name: r.label || (r.characterName === '__scene__' ? '场景' : '道具资产'),
                  file_path: '',
                  prompt: r.prompt || '',
                });
                assetId = created.id;
              }
              if (assetId) {
                await regenerateVideoAsset(assetId, r.prompt);
              }
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
          onUploadReplace = async (resourceId: number, file: File) => {
            const resource = resources.find((res) => res.id === resourceId);
            if (!resource || !workflow) return;
            await runForResource(resource, 'upload', async () => {
              await uploadWorkbenchAsset(
                {
                  assetId: resource.assetId,
                  assetType: resource.characterName === '__scene__' ? 'scene_reference' : 'prop_reference',
                  label: resource.label || (resource.characterName === '__scene__' ? '场景' : '道具资产'),
                  prompt: resource.prompt || '',
                },
                workflow.chapter_id,
                file,
                createVideoAsset,
                replaceVideoAsset,
                onRefreshWorkflow,
              );
            });
          };
          onDelete = async () => {};
          onRedraw = async () => {};
          onPromptSave = async (resourceId: number, prompt: string) => {
            const resource = resources.find((res) => res.id === resourceId);
            if (!resource) return;
            await runForResource(resource, 'savePrompt', async () => {
              if (resource.characterName === '__scene__') {
                await saveChapterShotPrompts(workbenchShot.id, { scene_prompt: prompt });
              } else {
                const propPrompts = [...(workbenchShot.prop_prompts ?? [])];
                const propIndex = resources.findIndex((res) => res.id === resourceId) - sceneRes.length;
                if (propIndex >= 0 && propPrompts[propIndex]) {
                  propPrompts[propIndex] = { ...propPrompts[propIndex], prompt };
                  await saveChapterShotPrompts(workbenchShot.id, { prop_prompts: propPrompts });
                }
              }
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
          onWorkbenchReanalyze = async (resourceId: number) => {
            const resource = resources.find((res) => res.id === resourceId);
            if (!resource) return;
            await runForResource(resource, 'reanalyze', async () => {
              await onReanalyzePrompt([workbenchShot.id]);
              if (onRefreshWorkflow) await onRefreshWorkflow();
            });
          };
        } else {
          // fallback（无匹配类型）
          resources = [];
          onRegenerate = async () => {};
          onUploadReplace = async () => {};
          onDelete = async () => {};
          onRedraw = async () => {};
          onPromptSave = undefined;
          onWorkbenchReanalyze = undefined;
        }

        const busyType = videoWorkbench.type === 'scene'
          ? undefined
          : videoWorkbench.type;
        const busyResourceId = videoWorkbench.type === 'scene'
          ? resources.find((resource) => {
              const resourceType = resource.characterName === '__scene__' ? 'scene' : 'prop';
              return isWorkbenchResourceBusy(resourceType, workbenchShot.id, resource, new Set(Object.keys(workbenchBusyMap)));
            })?.id
          : busyType
            ? findBusyWorkbenchResourceId(busyType, workbenchShot.id, resources, new Set(Object.keys(workbenchBusyMap)))
            : undefined;
        const currentBusyResource = resources.find((resource) => resource.id === (busyResourceId ?? videoWorkbench.assetId ?? resources[0]?.id));
        const externalBusy = currentBusyResource
          ? workbenchBusyMap[buildWorkbenchBusyKey(getBusyType(currentBusyResource), workbenchShot.id, currentBusyResource)] || null
          : null;

        return (
          <VideoCardWorkbench
            key={JSON.stringify(resources)}
            type={videoWorkbench.type}
            shotId={videoWorkbench.shotId}
            assetId={busyResourceId ?? videoWorkbench.assetId}
            resources={resources}
            onRegenerate={onRegenerate}
            onUploadReplace={onUploadReplace}
            onDelete={onDelete}
            onRedraw={onRedraw}
            onPromptSave={onPromptSave}
            onReanalyzePrompt={onWorkbenchReanalyze}
            onClose={() => setVideoWorkbench(null)}
          storyboardRefAssets={(videoWorkbench.type === 'storyboard' || videoWorkbench.type === 'video') ? [...workbenchStoryboardAssets, ...shotStoryboardAssets] : undefined}
          selectedRefAssetIds={workbenchRefAssetIds}
          onSelectedRefAssetsChange={setWorkbenchRefAssetIds}
          displayShotIndex={workbenchShot.shot_index}
          storyboardImageUrl={toAssetUrl(workbenchShot.storyboard_image_url)}
            chapterAssets={chapterAssets}
            shotStoryboards={sortedShots.filter(s => s.storyboard_image_url).map(s => ({
              id: s.id,
              file_path: s.storyboard_image_url || '',
              name: `镜头${s.shot_index} 故事版`,
            }))}
            videoAspectRatio={videoAspectRatio}
            onVideoAspectRatioChange={onVideoAspectRatioChange}
            recommendedSceneAssets={videoWorkbench.type === 'scene' ? (workbenchShot.scene_asset_candidates || []) : undefined}
            recommendedKeyProps={videoWorkbench.type === 'scene' ? (workbenchShot.key_props || []) : undefined}
            recommendedReferenceAssetIds={(videoWorkbench.type === 'storyboard' || videoWorkbench.type === 'video') ? workbenchRefAssetIds : undefined}
            externalBusy={externalBusy}
        />
        );
      })()}
    </div>
  );
}
