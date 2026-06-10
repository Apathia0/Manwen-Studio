import { useMemo, useState } from 'react';
import {
  CheckCircle2,
  Clapperboard,
  Film,
  Image as ImageIcon,
  Loader2,
  RefreshCcw,
  Sparkles,
  UserRound,
  Wand2,
  SquarePen,
  StepForward,
  PanelBottomOpen,
  SkipForward,
} from 'lucide-react';
import type { ChapterVideoWorkflow, StoryVideoCharacter, VideoAsset } from '../api';
import { saveChapterShotPrompts } from '../api';
import AssetReferenceSelector from './AssetReferenceSelector';

import VideoCardWorkbench from './VideoCardWorkbench';
import { buildCharacterWorkbenchResources } from './videoWorkbenchUtils';

interface ChapterVideoWorkflowPanelProps {
  workflow: ChapterVideoWorkflow | null;
  workflowLoading: boolean;
  workflowRunning: boolean;
  chapterAssets: VideoAsset[];
  selectedReferenceIds: number[];
  selectedStyle: string;
  stylePresets: Array<{ id: number; name: string; category: string }>;
  concatVideoUrl: string | null;
  selectedShotIds: Set<number>;
  skippedShotIds: Set<number>;
  onSelectReferenceIds: (ids: number[]) => void;
  onRefreshWorkflow: () => Promise<void> | void;
  onConcatWorkflow: () => Promise<void> | void;
  onRegenerateStoryboard: (shotId: number, refAssetIds?: number[]) => Promise<void> | void;
  onRegenerateVideo: (shotId: number, refAssetIds?: number[]) => Promise<void> | void;
  onStyleChange: (style: string) => void;
  onParseShots: () => Promise<void> | void;
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
  parsing?: boolean;
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
  if (!filePath) return '';
  if (filePath.startsWith('http') || filePath.startsWith('/static/')) return filePath;
  return `/static/video/${filePath.replace(/\\/g, '/')}`;
}

export default function ChapterVideoWorkflowPanel({
  workflow,
  workflowLoading,
  workflowRunning,
  chapterAssets,
  selectedReferenceIds,
  selectedStyle,
  stylePresets,
  concatVideoUrl,
  selectedShotIds,
  skippedShotIds,
  onSelectReferenceIds,
  onRefreshWorkflow,
  onConcatWorkflow,
  onRegenerateStoryboard,
  onRegenerateVideo,
  onStyleChange,
  onParseShots,
  onGenerateStoryboards,
  onGenerateVideos,
  onToggleShotSelection,
  onSelectAllShots,
  onSkipShot,
  onReanalyzePrompt,
  onReanalyzeCurrentCharacter,
  onStoryboardPromptChange,
  onDeleteChapterAsset,
  onDeleteStoryboard,
  onDeleteVideo,
  parsing,
}: ChapterVideoWorkflowPanelProps) {
  const [selectorOpen, setSelectorOpen] = useState(false);

  const [videoWorkbench, setVideoWorkbench] = useState<{
    shotId: number;
    type: 'character' | 'storyboard' | 'video';
    assetId?: number;
  } | null>(null);

  const [workbenchRefAssetIds, setWorkbenchRefAssetIds] = useState<number[]>([]);

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

  if (workflowLoading && !videoWorkbench) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500">
        <Loader2 size={22} className="animate-spin" />
      </div>
    );
  }

  const status = workflow?.workflow_status ?? '';

  const canParse = (!workflow || ['pending', 'failed'].includes(status)) && !workflowRunning;
  const canStoryboard = ['shots_ready', 'generating_storyboards', 'failed'].includes(status) && !workflowRunning;
  const canVideo = ['storyboards_ready', 'generating_videos', 'failed'].includes(status) && !workflowRunning;
  const canConcat = ['completed', 'videos_ready'].includes(status) && !workflowRunning;

  const storyboardReadyShots = workflow?.shots?.filter((shot) => shot.status === 'storyboard_ready') ?? [];
  const videoReadyShots = workflow?.shots?.filter((shot) => shot.status === 'video_ready') ?? [];

  const getCharacterThumbnails = (names: string[] | null | undefined): Array<{ name: string; thumbnailUrl: string | null }> => {
    if (!names?.length) return [];
    return names.map((name) => {
      const trimmed = name.trim();
      const normalizedName = trimmed.toLowerCase();
      const asset = characterAssets.find((a) => {
        const haystacks = [a.name, a.prompt].filter((v): v is string => Boolean(v?.trim()));
        return haystacks.some((v) => v.toLowerCase().includes(normalizedName));
      });
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
          {stylePresets.length > 0 && (
            <select
              value={selectedStyle}
              onChange={(e) => onStyleChange(e.target.value)}
              className="rounded-lg border border-[#d7e3f4] bg-white px-2 py-1 text-xs text-slate-600 outline-none"
            >
              {stylePresets.map((preset) => (
                <option key={preset.id} value={preset.name}>{preset.name}</option>
              ))}
            </select>
          )}
          <button
            onClick={() => setSelectorOpen(true)}
            className="rounded-lg border border-[#d7e3f4] bg-white px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            角色参考图 {selectedReferenceIds.length > 0 ? `(${selectedReferenceIds.length})` : ''}
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
          {workflow && (
            <>
              <button
                onClick={() => void onGenerateStoryboards(activeShotIds)}
                disabled={!canStoryboard || activeShotIds.length === 0}
                title="阶段2：为选中的镜头生成故事版图片"
                className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ImageIcon size={12} />
                故事版
              </button>
              <button
                onClick={() => void onGenerateVideos(activeShotIds)}
                disabled={!canVideo || activeShotIds.length === 0}
                title="阶段3：为选中的镜头生成视频"
                className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Film size={12} />
                视频
              </button>
              <button
                onClick={() => void onConcatWorkflow()}
                disabled={!canConcat}
                title="阶段4：拼接已完成视频为整章成片"
                className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <PanelBottomOpen size={12} />
                拼接
              </button>
            </>
          )}
          <button
            onClick={() => void onRefreshWorkflow()}
            disabled={workflowRunning}
            className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-white disabled:opacity-50"
          >
            <RefreshCcw size={12} />
            刷新
          </button>
        </div>
      </div>

      {/* ── 空状态 ── */}
      {!workflow && (
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
                  <span className="text-sm font-medium text-slate-600">正在拆镜...</span>
                </div>
              </div>
            )}
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
                                    : 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {shotStatusLabel(shot.status)}
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
                      <div className="grid shrink-0 grid-cols-1 gap-3 sm:grid-cols-3 xl:w-[640px]">
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
                          onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'storyboard' })}
                          className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <ImageIcon size={12} /> 故事版
                          </div>
                          {hasStoryboard ? (
                            <img
                              src={toAssetUrl(shot.storyboard_image_url)}
                              alt={`镜头 ${shot.shot_index} 故事版`}
                              className="h-32 w-full rounded-lg object-cover"
                            />
                          ) : (
                            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                              暂无故事版
                            </div>
                          )}
                        </button>

                        <button
                          type="button"
                          onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'video' })}
                          className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <Film size={12} /> 视频
                          </div>
                          {hasVideo ? (
                            <video
                              src={toAssetUrl(shot.video_url)}
                              controls
                              className="h-32 w-full rounded-lg bg-slate-950 object-contain"
                            />
                          ) : (
                            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                              暂无视频
                            </div>
                          )}
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
                         <Sparkles size={12} /> 重新分析提示词
                       </button>
                       {isFailed && (
                         <>
                           <button
                             onClick={() => void onRegenerateStoryboard(shot.id)}
                             className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-3 py-1.5 text-xs text-rose-600 hover:bg-rose-50"
                          >
                            <RefreshCcw size={12} /> 重试故事版
                          </button>
                          <button
                            onClick={() => void onRegenerateVideo(shot.id)}
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-3 py-1.5 text-xs text-rose-600 hover:bg-rose-50"
                          >
                            <RefreshCcw size={12} /> 重试视频
                          </button>
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
                            onClick={() => void onRegenerateVideo(shot.id)}
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

            {/* ── 紧凑版整章成片卡片 ── */}
            {sortedShots.length > 0 && (
              <div className="hidden shrink-0 xl:block xl:w-[280px]">
                <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold text-slate-900">整章成片</div>
                      <div className="mt-0.5 text-xs text-slate-500">
                        {storyboardReadyShots.length} 镜故事版 · {videoReadyShots.length} 镜视频
                      </div>
                    </div>
                    <button
                      onClick={() => void onConcatWorkflow()}
                      disabled={!canConcat}
                      className="rounded-lg bg-slate-900 px-2.5 py-1 text-xs text-white disabled:opacity-40"
                    >
                      拼接
                    </button>
                  </div>
                  {concatVideoUrl ? (
                    <video src={toAssetUrl(concatVideoUrl)} controls className="mt-3 h-28 w-full rounded-xl bg-slate-950 object-contain" />
                  ) : (
                    <div className="mt-3 flex h-28 items-center justify-center rounded-xl border border-dashed border-[#d7e3f4] bg-slate-50 text-xs text-slate-400">
                      暂无
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {selectorOpen && (
        <AssetReferenceSelector
          availableAssets={characterAssets}
          selectedIds={selectedReferenceIds}
          onConfirm={(ids) => {
            onSelectReferenceIds(ids);
            setSelectorOpen(false);
          }}
          onClose={() => setSelectorOpen(false)}
        />
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

        let resources: Array<{ id: number; assetId?: number; url: string; prompt?: string; label?: string; characterName?: string; hasAsset?: boolean }>;
        let onRegenerate: (resourceId: number) => Promise<void>;
        let onUploadReplace: (resourceId: number, file: File) => Promise<void>;
        let onDelete: (resourceId: number) => Promise<void>;
        let onRedraw: (resourceId: number, prompt: string, mask?: string) => Promise<void>;
        let onPromptSave: ((resourceId: number, prompt: string) => Promise<void>) | undefined;
        let onWorkbenchReanalyze: ((resourceId: number) => Promise<void>) | undefined;

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
          onRegenerate = async () => {};
          onUploadReplace = async () => {};
          onDelete = async (resourceId: number) => {
            if (resourceId > 0 && onDeleteChapterAsset) await onDeleteChapterAsset(resourceId);
          };
          onRedraw = async () => {};
          onPromptSave = undefined;
          onWorkbenchReanalyze = onReanalyzeCurrentCharacter
            ? async (_resourceId: number) => {
                const currentIdx = resources.findIndex(r => r.id === _resourceId);
                const charName = resources[currentIdx >= 0 ? currentIdx : 0]?.characterName;
                if (charName && workbenchShot) {
                  await onReanalyzeCurrentCharacter(workbenchShot.id, charName);
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
            await onRegenerateStoryboard(resourceId, workbenchRefAssetIds);
          };
          onUploadReplace = async () => {};
          onDelete = async (resourceId: number) => {
            if (onDeleteStoryboard) await onDeleteStoryboard(resourceId);
          };
          onRedraw = async () => {};
          onPromptSave = async (resourceId: number, prompt: string) => {
            await saveChapterShotPrompts(resourceId, { storyboard_prompt: prompt });
            if (onRefreshWorkflow) await onRefreshWorkflow();
          };
          onWorkbenchReanalyze = async (resourceId: number) => {
            await onReanalyzePrompt([resourceId]);
            if (onRefreshWorkflow) await onRefreshWorkflow();
          };
        } else if (videoWorkbench.type === 'video') {
          resources = [{
            id: workbenchShot.id,
            url: toAssetUrl(workbenchShot.video_url),
            prompt: workbenchShot.video_prompt ?? '',
          }];
          onRegenerate = async (resourceId: number) => { await onRegenerateVideo(resourceId, workbenchRefAssetIds); };
          onUploadReplace = async () => {};
          onDelete = async (resourceId: number) => {
            if (onDeleteVideo) await onDeleteVideo(resourceId);
          };
          onRedraw = async () => {};
          onPromptSave = async (resourceId: number, prompt: string) => {
            await saveChapterShotPrompts(resourceId, { video_prompt: prompt });
            if (onRefreshWorkflow) await onRefreshWorkflow();
          };
          onWorkbenchReanalyze = async (resourceId: number) => {
            await onReanalyzePrompt([resourceId]);
            if (onRefreshWorkflow) await onRefreshWorkflow();
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

        return (
          <VideoCardWorkbench
            key={JSON.stringify(resources)}
            type={videoWorkbench.type}
            shotId={videoWorkbench.shotId}
            assetId={videoWorkbench.assetId}
            resources={resources}
            onRegenerate={onRegenerate}
            onUploadReplace={onUploadReplace}
            onDelete={onDelete}
            onRedraw={onRedraw}
            onPromptSave={onPromptSave}
            onReanalyzePrompt={onWorkbenchReanalyze}
            onClose={() => setVideoWorkbench(null)}
          storyboardRefAssets={(videoWorkbench.type === 'storyboard' || videoWorkbench.type === 'video') ? workbenchStoryboardAssets : undefined}
          selectedRefAssetIds={workbenchRefAssetIds}
          onSelectedRefAssetsChange={setWorkbenchRefAssetIds}
          displayShotIndex={workbenchShot.shot_index}
          storyboardImageUrl={toAssetUrl(workbenchShot.storyboard_image_url)}
        />
        );
      })()}
    </div>
  );
}
