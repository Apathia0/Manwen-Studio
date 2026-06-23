import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Braces,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clapperboard,
  Clock,
  Eye,
  Film,
  Home,
  Image as ImageIcon,
  Loader2,
  MapPin,
  MessageSquare,
  Package,
  Palette,
  Sun,
  RefreshCcw,
  Sparkles,
  Trash2,
  UserRound,
  Wand2,
  SquarePen,
  StepForward,
  PanelBottomOpen,
  SkipForward,
  FileText,
  Save,
  Send,
  Tag,
  ThumbsUp,
  Zap,
} from 'lucide-react';
import type { ChapterVideoWorkflow, StoryVideoCharacter, VideoAsset } from '../api';
import { saveChapterShotPrompts, replaceVideoAsset, regenerateVideoAsset, uploadShotStoryboard, uploadShotVideo, createVideoAsset, toPublicVideoAssetUrl, generateWorkflowScreenplay, saveWorkflowScreenplay, approveWorkflowScreenplay, regenerateWorkflowScreenplay } from '../api';
import { canStartChapterWorkflowParse } from './chapterWorkflowUtils';
import { toast } from '../lib/toast';

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
  chapterNovelContent?: string | null;
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
  onCreateAndGenerateScreenplay: () => Promise<void> | void;
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
  renderAiAssistantButton?: React.ReactNode;
  parsing?: boolean;
  videoAspectRatio?: '16:9' | '9:16';
  onVideoAspectRatioChange?: (value: '16:9' | '9:16') => void;
onOpenAssetManagement?: () => void;
  onAgentShotChange?: (shotId: number | undefined) => void;
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

interface ScreenplayBeat {
  beat_id: string;
  type: string;
  importance: string;
  action: string;
  dialogue: any; // 运行时可能是 string | string[] | {character,line}[]
  emotion_shift: string;
  transition_to_next: string;
}

interface ScreenplayScene {
  scene_id: string;
  title: string;
  location: string;
  time_of_day: string;
  characters: string[];
  scene_purpose: string;
  visual_anchors: string;
  beats: ScreenplayBeat[];
  transition_to_next_scene: string;
}

export default function ChapterVideoWorkflowPanel({
  workflow,
  workflowLoading,
  workflowRunning,
  chapterNovelContent,
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
  onCreateAndGenerateScreenplay,
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
renderAiAssistantButton,
  parsing,
  videoAspectRatio = '16:9',
  onVideoAspectRatioChange,
onOpenAssetManagement,
  onAgentShotChange,
  characterLoading,
}: ChapterVideoWorkflowPanelProps) {
  const [concatModalOpen, setConcatModalOpen] = useState(false);
  const [screenplayText, setScreenplayText] = useState('');
  const [screenplayLoading, setScreenplayLoading] = useState(false);

  const [expandedScenes, setExpandedScenes] = useState<Set<string>>(new Set());
  const [showRawJson, setShowRawJson] = useState(false);
  const [rawJsonText, setRawJsonText] = useState('');

  // 可编辑的本地场景数据，从 workflow.screenplay_json 同步初始化
  const [localScenes, setLocalScenes] = useState<ScreenplayScene[]>([]);
  useEffect(() => {
    const json = workflow?.screenplay_json;
    if (!json || typeof json !== 'object') {
      setLocalScenes([]);
      return;
    }
    const scenes = (json as Record<string, unknown>).scenes;
    if (!Array.isArray(scenes)) {
      setLocalScenes([]);
      return;
    }
    setLocalScenes(scenes as ScreenplayScene[]);
  }, [workflow?.screenplay_json]);

  // 内联编辑状态："{scene_id}.{field}" 或 "{scene_id}.{beat_id}.{field}"
  const [editingField, setEditingField] = useState<string | null>(null);

  // 剧本批准后收起场景列表
  const [screenplayCollapsed, setScreenplayCollapsed] = useState(workflow?.screenplay_status === 'approved');
  useEffect(() => {
    if (workflow?.screenplay_status === 'approved') setScreenplayCollapsed(true);
  }, [workflow?.screenplay_status]);

  // 视觉锚点编辑状态（结构化编辑器）
  const [editingAnchors, setEditingAnchors] = useState<Array<{type: string; description: string}>>([]);
  const visualAnchorTypes = [
    { value: 'set_dressing', label: '装饰' },
    { value: 'prop', label: '道具' },
    { value: 'lighting', label: '灯光' },
    { value: 'costume', label: '服装' },
  ];

  // 字段中文映射表
  const beatTypeLabels: Record<string, string> = {
    action: '动作', dialogue: '对话', narration: '旁白', conflict: '冲突', transition: '转场',
  };
  const beatTypeColors: Record<string, string> = {
    action: 'bg-blue-50 text-blue-600',
    dialogue: 'bg-emerald-50 text-emerald-600',
    narration: 'bg-purple-50 text-purple-600',
    conflict: 'bg-red-50 text-red-600',
    transition: 'bg-amber-50 text-amber-600',
  };
  const importanceLabels: Record<string, string> = {
    major: '关键', medium: '一般', minor: '次要',
  };
  const importanceColors: Record<string, string> = {
    major: 'bg-rose-50 text-rose-600',
    medium: 'bg-slate-100 text-slate-500',
    minor: 'bg-amber-50 text-amber-600',
  };
  function parseVisualAnchorsToItems(va: unknown): Array<{type: string; description: string}> {
    if (typeof va === 'string') {
      try { const parsed = JSON.parse(va); if (Array.isArray(parsed)) return parsed; } catch { return [{ type: 'text', description: va }]; }
    }
    if (Array.isArray(va)) return va as Array<{type: string; description: string}>;
    if (typeof va === 'object' && va !== null) return [{ type: 'text', description: JSON.stringify(va) }];
    return [];
  }

  const handleUpdateScene = useCallback((sceneId: string, updates: Partial<ScreenplayScene>) => {
    setLocalScenes((prev) => prev.map((s) => (s.scene_id === sceneId ? { ...s, ...updates } : s)));
    setEditingField(null);
  }, []);

  const handleUpdateBeat = useCallback((sceneId: string, beatId: string, updates: Partial<ScreenplayBeat>) => {
    setLocalScenes((prev) =>
      prev.map((s) => {
        if (s.scene_id !== sceneId) return s;
        return {
          ...s,
          beats: s.beats.map((b) => (b.beat_id === beatId ? { ...b, ...updates } : b)),
        };
      }),
    );
    setEditingField(null);
  }, []);

  const toggleSceneExpand = (sceneId: string) => {
    setExpandedScenes((prev) => {
      const next = new Set(prev);
      if (next.has(sceneId)) {
        next.delete(sceneId);
      } else {
        next.add(sceneId);
      }
      return next;
    });
  };

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
  useEffect(() => {
    setScreenplayText(workflow?.screenplay_text || '');
  }, [workflow?.screenplay_text]);

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

  const screenplayApproved = !!workflow && workflow.screenplay_status === 'approved';
  const canParse = canStartChapterWorkflowParse({
    workflowExists: Boolean(workflow),
    status,
    hasShots: Boolean(workflow?.shots?.length),
    parsing: Boolean(parsing),
    workflowRunning,
  }) && screenplayApproved;
  const canStoryboard = ['shots_ready', 'generating_storyboards', 'failed'].includes(status) && !workflowRunning && screenplayApproved;
  const canVideo = ['storyboards_ready', 'generating_videos', 'failed'].includes(status) && !workflowRunning && screenplayApproved;
  const canConcat = ['completed', 'videos_ready', 'storyboards_ready', 'generating_videos', 'shots_ready'].includes(status) && !workflowRunning;

  const handleGenerateScreenplay = async () => {
    if (!workflow || screenplayLoading) return;
    setScreenplayLoading(true);
    try {
      await generateWorkflowScreenplay(workflow.id);
      if (onRefreshWorkflow) await onRefreshWorkflow();
      toast.success('剧本生成完成');
    } catch (error: any) {
      toast.error(`剧本生成失败: ${error.message || '未知错误'}`);
    } finally {
      setScreenplayLoading(false);
    }
  };

  const handleSaveScreenplay = async () => {
    if (!workflow || screenplayLoading) return;
    setScreenplayLoading(true);
    try {
      await saveWorkflowScreenplay(workflow.id, { screenplay_text: screenplayText, screenplay_json: { scenes: localScenes } } as { screenplay_text: string });
      if (onRefreshWorkflow) await onRefreshWorkflow();
      toast.success('剧本已保存');
    } catch (error: any) {
      toast.error(`剧本保存失败: ${error.message || '未知错误'}`);
    } finally {
      setScreenplayLoading(false);
    }
  };

  const handleApproveScreenplay = async () => {
    if (!workflow || screenplayLoading) return;
    setScreenplayLoading(true);
    try {
      await approveWorkflowScreenplay(workflow.id);
      if (onRefreshWorkflow) await onRefreshWorkflow();
      toast.success('剧本已批准，可以开始拆镜');
    } catch (error: any) {
      toast.error(`剧本批准失败: ${error.message || '未知错误'}`);
    } finally {
      setScreenplayLoading(false);
    }
  };

  const handleRegenerateScreenplay = async () => {
    if (!workflow || screenplayLoading) return;
    setScreenplayLoading(true);
    try {
      await regenerateWorkflowScreenplay(workflow.id);
      if (onRefreshWorkflow) await onRefreshWorkflow();
      toast.success('剧本已重新生成');
    } catch (error: any) {
      toast.error(`剧本重新生成失败: ${error.message || '未知错误'}`);
    } finally {
      setScreenplayLoading(false);
    }
  };

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
          {onOpenAssetManagement && (
            <button
              onClick={onOpenAssetManagement}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
            >
              <Package size={14} /> 资产管理
            </button>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {renderAiAssistantButton}
          {!workflow ? (
            <button
              onClick={() => void onCreateAndGenerateScreenplay()}
              disabled={workflowRunning}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
            >
              <Send size={12} />
              创建并生成剧本
            </button>
          ) : !screenplayApproved ? (
            <button
              onClick={handleGenerateScreenplay}
              disabled={screenplayLoading || workflowRunning}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
            >
              {screenplayLoading ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
              生成剧本
            </button>
          ) : (
            <button
              onClick={() => void onParseShots()}
              disabled={!canParse}
              title="阶段1：从已批准的剧本拆解为镜头列表"
              className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
            >
              {parsing ? <Loader2 size={12} className="animate-spin" /> : <StepForward size={12} />}
              {parsing ? '拆镜中...' : '从剧本拆镜'}
            </button>
          )}
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

      {/* ── 工作流内容 ── */}
      {workflow && (
        <>
          {/* ── 剧本审核区 ── */}
          <div className={!screenplayApproved ? "flex flex-1 min-h-0 overflow-hidden px-4 py-4" : "mx-4 mt-3"}>
            <div className={`flex rounded-2xl border border-[#d7e3f4] bg-white shadow-sm overflow-hidden ${!screenplayApproved ? "flex-1 flex-row" : ""} ${!screenplayApproved || screenplayCollapsed ? '' : 'max-h-[45vh]'}`}>
              {/* ── 左侧：原始小说正文（只读） ── */}
              <div className={`flex flex-col bg-slate-50/60 ${!screenplayApproved ? "w-[40%] min-w-[260px] border-r border-[#d7e3f4]" : "hidden"}`}>
                <div className="flex items-center gap-2 px-3 py-2 border-b border-[#d7e3f4] bg-white/70">
                  <BookOpen size={14} className="text-slate-500" />
                  <span className="text-xs font-medium text-slate-600">章节正文</span>
                </div>
                <div className="flex-1 overflow-y-auto p-3">
                  <div className="text-sm leading-relaxed text-slate-600 whitespace-pre-wrap">
                    {chapterNovelContent || '（暂无章节正文，请从章节管理页导入或生成正文内容）'}
                  </div>
                </div>
              </div>

              {/* ── 右侧：解析后的剧本 ── */}
              <div className="flex-1 flex flex-col min-w-0">
                {/* 顶部操作栏 */}
                <div className="flex items-center justify-between px-3 py-2 border-b border-[#d7e3f4] bg-white/70 shrink-0">
                  <div className="flex items-center gap-2">
                    <FileText size={16} className="text-slate-500" />
                    <span className="text-sm font-medium text-slate-900">剧本审核</span>
                    {workflow.screenplay_status === 'approved' ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-600">
                        <CheckCircle2 size={12} /> 已批准
                      </span>
                    ) : workflow.screenplay_text ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-600">
                        待批准
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500">
                        未生成
                      </span>
                    )}
                    {workflow.screenplay_status === 'approved' && (
                      <button
                        onClick={() => setScreenplayCollapsed(!screenplayCollapsed)}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50 ml-1"
                      >
                        {screenplayCollapsed ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        {screenplayCollapsed ? '展开剧本' : '收起剧本'}
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={handleSaveScreenplay}
                      disabled={screenplayLoading || !screenplayText.trim()}
                      className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Save size={12} />
                      保存
                    </button>
                    <button
                      onClick={handleRegenerateScreenplay}
                      disabled={screenplayLoading || !workflow.screenplay_text || workflowRunning}
                      className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-2.5 py-1.5 text-xs text-amber-700 hover:bg-amber-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <RefreshCcw size={12} />
                      重新生成
                    </button>
                    {workflow.screenplay_text && workflow.screenplay_status !== 'approved' && (
                      <button
                        onClick={handleApproveScreenplay}
                        disabled={screenplayLoading}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs text-white hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <ThumbsUp size={12} />
                        批准剧本
                      </button>
                    )}
                  </div>
                </div>

                {/* 场景卡片列表（批准后可收起） */}
                <div className={`${!screenplayApproved ? "flex-1 overflow-y-auto p-3" : screenplayCollapsed ? "hidden" : "flex-1 overflow-y-auto p-2"}`}>
                  {localScenes.length > 0 ? (
                    <div className="space-y-2.5">
                      {localScenes.map((scene) => {
                        const isExpanded = expandedScenes.has(scene.scene_id);
                        const importanceLabel = scene.beats?.[0]?.importance || '';
                        return (
                          <div key={scene.scene_id} className="rounded-xl border border-[#d7e3f4] bg-white shadow-sm overflow-hidden">
                            {/* 场景卡片头部 */}
                            <div
                              onClick={() => toggleSceneExpand(scene.scene_id)}
                              className="flex items-center justify-between w-full px-3 py-2.5 hover:bg-slate-50/50 transition-colors cursor-pointer"
                            >
                              <div className="flex items-center gap-2 min-w-0 flex-1">
                                <span
                                  className="shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-lg bg-blue-50 text-xs font-semibold text-blue-600"
                                >
                                  {scene.scene_id}
                                </span>
                                {/* 标题：可点击编辑 */}
                                {editingField === `${scene.scene_id}.title` ? (
                                  <input
                                    autoFocus
                                    defaultValue={scene.title}
                                    onBlur={(e) => handleUpdateScene(scene.scene_id, { title: e.target.value })}
                                    onKeyDown={(e) => { if (e.key === 'Enter') handleUpdateScene(scene.scene_id, { title: e.currentTarget.value }); if (e.key === 'Escape') setEditingField(null); }}
                                    className="text-sm font-medium text-slate-800 border border-blue-400 rounded px-1.5 py-0.5 bg-blue-50/50 outline-none min-w-[120px]"
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                ) : (
                                  <span
                                    onClick={(e) => { e.stopPropagation(); setEditingField(`${scene.scene_id}.title`); }}
                                    className="text-sm font-medium text-slate-800 truncate cursor-pointer hover:text-blue-600 hover:bg-blue-50/50 rounded px-1 -mx-1 transition-colors"
                                    title="点击编辑标题"
                                  >
                                    {scene.title || `场景 ${scene.scene_id}`}
                                  </span>
                                )}
                                {/* 地点：可点击编辑 */}
                                {editingField === `${scene.scene_id}.location` ? (
                                  <input
                                    autoFocus
                                    defaultValue={scene.location || ''}
                                    onBlur={(e) => handleUpdateScene(scene.scene_id, { location: e.target.value })}
                                    onKeyDown={(e) => { if (e.key === 'Enter') handleUpdateScene(scene.scene_id, { location: e.currentTarget.value }); if (e.key === 'Escape') setEditingField(null); }}
                                    className="inline-flex items-center gap-0.5 text-[11px] text-slate-600 border border-blue-400 rounded px-1.5 py-0.5 bg-blue-50/50 outline-none min-w-[80px]"
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                ) : (
                                  <span
                                    onClick={(e) => { e.stopPropagation(); setEditingField(`${scene.scene_id}.location`); }}
                                    className="inline-flex items-center gap-0.5 text-[11px] text-slate-400 shrink-0 cursor-pointer hover:text-blue-600 hover:bg-blue-50/50 rounded px-1 -mx-1 transition-colors"
                                    title="点击编辑地点"
                                  >
                                    <MapPin size={10} />
                                    {scene.location || '点击设置地点'}
                                  </span>
                                )}
                                {/* 时间：可点击编辑 */}
                                {editingField === `${scene.scene_id}.time_of_day` ? (
                                  <input
                                    autoFocus
                                    defaultValue={scene.time_of_day || ''}
                                    onBlur={(e) => handleUpdateScene(scene.scene_id, { time_of_day: e.target.value })}
                                    onKeyDown={(e) => { if (e.key === 'Enter') handleUpdateScene(scene.scene_id, { time_of_day: e.currentTarget.value }); if (e.key === 'Escape') setEditingField(null); }}
                                    className="inline-flex items-center gap-0.5 text-[11px] text-slate-600 border border-blue-400 rounded px-1.5 py-0.5 bg-blue-50/50 outline-none min-w-[70px]"
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                ) : (
                                  <span
                                    onClick={(e) => { e.stopPropagation(); setEditingField(`${scene.scene_id}.time_of_day`); }}
                                    className="inline-flex items-center gap-0.5 text-[11px] text-slate-400 shrink-0 cursor-pointer hover:text-blue-600 hover:bg-blue-50/50 rounded px-1 -mx-1 transition-colors"
                                    title="点击编辑时间"
                                  >
                                    <Clock size={10} />
                                    {scene.time_of_day || '点击设置时间'}
                                  </span>
                                )}
                                {importanceLabel && (
                                  <span className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0 ${importanceColors[importanceLabel] || 'bg-slate-100 text-slate-500'}`}>
                                    <Tag size={9} />
                                    {importanceLabels[importanceLabel] || importanceLabel}
                                  </span>
                                )}
                              </div>
                              <span className="shrink-0 ml-2">
                                {isExpanded ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                              </span>
                            </div>

                            {/* 场景卡片展开内容 */}
                            {isExpanded && (
                              <div className="px-3 pb-3 border-t border-[#d7e3f4]">
                                {/* 角色标签 — 可点击编辑 */}
                                <div className="flex flex-wrap items-center gap-1.5 mt-3 mb-2">
                                  <UserRound size={12} className="text-slate-400 shrink-0" />
                                  {editingField === `${scene.scene_id}.characters` ? (
                                    <input
                                      autoFocus
                                      defaultValue={Array.isArray(scene.characters) ? scene.characters.join(', ') : ''}
                                      onBlur={(e) => handleUpdateScene(scene.scene_id, { characters: e.target.value.split(',').map((c) => c.trim()).filter(Boolean) })}
                                      onKeyDown={(e) => { if (e.key === 'Enter') handleUpdateScene(scene.scene_id, { characters: e.currentTarget.value.split(',').map((c) => c.trim()).filter(Boolean) }); if (e.key === 'Escape') setEditingField(null); }}
                                      className="text-[11px] text-slate-600 border border-blue-400 rounded px-1.5 py-0.5 bg-blue-50/50 outline-none min-w-[120px]"
                                      placeholder="角色名, 逗号分隔"
                                    />
                                  ) : (
                                    <>
                                      {Array.isArray(scene.characters) && scene.characters.length > 0 ? (
                                        scene.characters.map((char, i) => (
                                          <span key={i} className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-600">
                                            {typeof char === 'string' ? char : String((char as Record<string, unknown>).name || (char as Record<string, unknown>).character || char)}
                                          </span>
                                        ))
                                      ) : (
                                        <span
                                          onClick={() => setEditingField(`${scene.scene_id}.characters`)}
                                          className="text-[11px] text-slate-400 cursor-pointer hover:text-blue-600 hover:bg-blue-50/50 rounded px-1.5 py-0.5 transition-colors"
                                          title="点击编辑角色"
                                        >
                                          点击添加角色
                                        </span>
                                      )}
                                      {Array.isArray(scene.characters) && scene.characters.length > 0 && (
                                        <button
                                          onClick={() => setEditingField(`${scene.scene_id}.characters`)}
                                          className="text-[10px] text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded px-1 py-0.5 transition-colors"
                                          title="编辑角色列表"
                                        >
                                          <SquarePen size={10} />
                                        </button>
                                      )}
                                    </>
                                  )}
                                </div>

                                {/* 场景目的 — 可点击编辑 */}
                                <div className="mt-2 text-xs text-slate-600 leading-relaxed">
                                  <span className="font-medium text-slate-500 shrink-0">场景目的：</span>
                                  {editingField === `${scene.scene_id}.scene_purpose` ? (
                                    <textarea
                                      autoFocus
                                      defaultValue={typeof scene.scene_purpose === 'string' ? scene.scene_purpose : ''}
                                      onBlur={(e) => handleUpdateScene(scene.scene_id, { scene_purpose: e.target.value })}
                                      onKeyDown={(e) => { if (e.key === 'Escape') { setEditingField(null); e.preventDefault(); } }}
                                      className="w-full mt-1 text-xs text-slate-600 border border-blue-400 rounded px-2 py-1 bg-blue-50/50 outline-none resize-none"
                                      rows={2}
                                      placeholder="场景目的描述..."
                                    />
                                  ) : (
                                    <span
                                      onClick={() => setEditingField(`${scene.scene_id}.scene_purpose`)}
                                      className="cursor-pointer hover:text-blue-600 hover:bg-blue-50/50 rounded px-1 -mx-1 transition-colors"
                                      title="点击编辑场景目的"
                                    >
                                      {scene.scene_purpose ? (typeof scene.scene_purpose === 'string' ? scene.scene_purpose : String(scene.scene_purpose)) : '点击设置场景目的'}
                                    </span>
                                  )}
                                </div>

                                {/* 视觉锚点 — 结构化卡片展示 */}
                                <div className="mt-2">
                                  <div className="flex items-center gap-1 mb-1.5">
                                    <Eye size={12} className="text-slate-400 shrink-0" />
                                    <span className="text-[11px] font-medium text-slate-500">视觉锚点</span>
                                    {editingField === `${scene.scene_id}.visual_anchors` ? (
                                      <span className="flex items-center gap-1 ml-auto">
                                        <button
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleUpdateScene(scene.scene_id, { visual_anchors: JSON.stringify(editingAnchors) });
                                          }}
                                          className="text-[10px] text-blue-600 hover:text-blue-800 font-medium shrink-0"
                                        >
                                          保存
                                        </button>
                                        <button
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            setEditingField(null);
                                          }}
                                          className="text-[10px] text-slate-400 hover:text-slate-600 shrink-0"
                                        >
                                          取消
                                        </button>
                                      </span>
                                    ) : (
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setEditingAnchors(parseVisualAnchorsToItems(scene.visual_anchors));
                                          setEditingField(`${scene.scene_id}.visual_anchors`);
                                        }}
                                        className="ml-auto text-[10px] text-blue-500 hover:text-blue-700 hover:underline shrink-0"
                                      >
                                        编辑
                                      </button>
                                    )}
                                  </div>
                                  {editingField === `${scene.scene_id}.visual_anchors` ? (
                                    <div className="space-y-2">
                                      {editingAnchors.map((item, i) => (
                                        <div key={i} className="bg-white rounded-lg border border-blue-200 p-2">
                                          <div className="flex items-center gap-1.5 mb-1.5">
                                            <select
                                              value={item.type}
                                              onChange={(e) => {
                                                setEditingAnchors((prev) => {
                                                  const next = [...prev];
                                                  next[i] = { ...next[i], type: e.target.value };
                                                  return next;
                                                });
                                              }}
                                              className="text-[11px] font-medium border border-slate-200 rounded px-1.5 py-0.5 outline-none focus:border-blue-400 bg-white"
                                              onClick={(e) => e.stopPropagation()}
                                            >
                                              {visualAnchorTypes.map((t) => (
                                                <option key={t.value} value={t.value}>{t.label}</option>
                                              ))}
                                            </select>
                                            <button
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                setEditingAnchors((prev) => prev.filter((_, idx) => idx !== i));
                                              }}
                                              className="ml-auto text-red-300 hover:text-red-500 transition-colors"
                                              title="删除"
                                            >
                                              <Trash2 size={12} />
                                            </button>
                                          </div>
                                          <input
                                            value={item.description}
                                            onChange={(e) => {
                                              setEditingAnchors((prev) => {
                                                const next = [...prev];
                                                next[i] = { ...next[i], description: e.target.value };
                                                return next;
                                              });
                                            }}
                                            onClick={(e) => e.stopPropagation()}
                                            className="w-full text-xs text-slate-700 border border-slate-200 rounded px-2 py-1 outline-none focus:border-blue-400"
                                            placeholder="描述..."
                                          />
                                        </div>
                                      ))}
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setEditingAnchors((prev) => [...prev, { type: 'set_dressing', description: '' }]);
                                        }}
                                        className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-700 transition-colors"
                                      >
                                        + 添加锚点
                                      </button>
                                    </div>
                                  ) : (
                                    <div className="space-y-1">
                                      {(() => {
                                        const items = parseVisualAnchorsToItems(scene.visual_anchors);
                                        if (items.length === 0) {
                                          return <span className="text-xs text-slate-400">点击编辑添加视觉锚点</span>;
                                        }
const typeConfig: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  set_dressing: { label: '装饰', icon: <Home size={10} />, color: 'bg-teal-50 text-teal-600' },
  prop: { label: '道具', icon: <Package size={10} />, color: 'bg-amber-50 text-amber-600' },
  lighting: { label: '灯光', icon: <Sun size={10} />, color: 'bg-yellow-50 text-yellow-700' },
  costume: { label: '服装', icon: <UserRound size={10} />, color: 'bg-rose-50 text-rose-600' },
};
                                        return items.map((item, i) => {
                                          const cfg = typeConfig[item.type] || { label: item.type, icon: <Eye size={10} />, color: 'bg-slate-100 text-slate-500' };
                                          return (
                                            <div key={i} className="flex items-start gap-1.5 text-xs">
                                              <span className={`shrink-0 inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium ${cfg.color}`}>
                                                {cfg.icon}
                                                {cfg.label}
                                              </span>
                                              <span className="text-slate-600 leading-relaxed">{item.description}</span>
                                            </div>
                                          );
                                        });
                                      })()}
                                    </div>
                                  )}
                                </div>

                                {/* Beats 列表 */}
                                {scene.beats && scene.beats.length > 0 && (
                                  <div className="mt-3 space-y-2">
                                    {scene.beats.map((beat) => (
                                      <div key={beat.beat_id} className="rounded-lg border border-[#e5edf8] bg-slate-50/60 p-2.5">
                                        <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
                                          <span className="text-[11px] font-medium text-slate-600">节拍 {beat.beat_id}</span>
                                          {/* 节拍类型 — 可点击编辑 */}
                                          {editingField === `${scene.scene_id}.${beat.beat_id}.type` ? (
                                            <select
                                              autoFocus
                                              defaultValue={beat.type || 'action'}
                                              onBlur={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { type: e.target.value })}
                                              onChange={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { type: e.target.value })}
                                              className="rounded-full px-1.5 py-0.5 text-[10px] font-medium border border-blue-400 bg-blue-50/50 outline-none text-slate-700"
                                            >
                                              {Object.entries(beatTypeLabels).map(([val, label]) => (
                                                <option key={val} value={val}>{label}</option>
                                              ))}
                                            </select>
                                          ) : (
                                            <span
                                              onClick={() => setEditingField(`${scene.scene_id}.${beat.beat_id}.type`)}
                                              className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium cursor-pointer hover:ring-1 hover:ring-blue-300 transition-all ${beatTypeColors[beat.type] || 'bg-slate-100 text-slate-500'}`}
                                              title="点击编辑类型"
                                            >
                                              <Zap size={9} className="inline mr-0.5" />
                                              {beatTypeLabels[beat.type] || beat.type || '动作'}
                                            </span>
                                          )}
                                          {/* 重要性 — 可点击编辑 */}
                                          {editingField === `${scene.scene_id}.${beat.beat_id}.importance` ? (
                                            <select
                                              autoFocus
                                              defaultValue={beat.importance || 'medium'}
                                              onBlur={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { importance: e.target.value })}
                                              onChange={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { importance: e.target.value })}
                                              className="rounded-full px-1.5 py-0.5 text-[10px] font-medium border border-blue-400 bg-blue-50/50 outline-none text-slate-700"
                                            >
                                              {Object.entries(importanceLabels).map(([val, label]) => (
                                                <option key={val} value={val}>{label}</option>
                                              ))}
                                            </select>
                                          ) : (
                                            <span
                                              onClick={() => setEditingField(`${scene.scene_id}.${beat.beat_id}.importance`)}
                                              className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium cursor-pointer hover:ring-1 hover:ring-blue-300 transition-all ${importanceColors[beat.importance] || 'bg-slate-100 text-slate-500'}`}
                                              title="点击编辑重要性"
                                            >
                                              {importanceLabels[beat.importance] || beat.importance || '一般'}
                                            </span>
                                          )}
                                          {/* 情绪变化 — 可点击编辑 */}
                                          {editingField === `${scene.scene_id}.${beat.beat_id}.emotion_shift` ? (
                                            <input
                                              autoFocus
                                              defaultValue={beat.emotion_shift || ''}
                                              onBlur={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { emotion_shift: e.target.value })}
                                              onKeyDown={(e) => { if (e.key === 'Enter') handleUpdateBeat(scene.scene_id, beat.beat_id, { emotion_shift: e.currentTarget.value }); if (e.key === 'Escape') setEditingField(null); }}
                                              className="rounded-full px-1.5 py-0.5 text-[10px] border border-blue-400 bg-violet-50/50 outline-none text-violet-700 min-w-[60px]"
                                              placeholder="情绪"
                                            />
                                          ) : (
                                            <span
                                              onClick={() => setEditingField(`${scene.scene_id}.${beat.beat_id}.emotion_shift`)}
                                              className="rounded-full bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600 cursor-pointer hover:ring-1 hover:ring-blue-300 transition-all"
                                              title="点击编辑情绪"
                                            >
                                              {beat.emotion_shift || '情绪'}
                                            </span>
                                          )}
                                        </div>

                                        {/* 动作描述 — 可点击编辑 */}
                                        {editingField === `${scene.scene_id}.${beat.beat_id}.action` ? (
                                          <textarea
                                            autoFocus
                                            defaultValue={typeof beat.action === 'string' ? beat.action : ''}
                                            onBlur={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { action: e.target.value })}
                                            onKeyDown={(e) => { if (e.key === 'Escape') { setEditingField(null); e.preventDefault(); } }}
                                            className="w-full text-xs text-slate-700 border border-blue-400 rounded px-2 py-1 bg-blue-50/50 outline-none resize-none mb-1.5"
                                            rows={3}
                                            placeholder="动作描述..."
                                          />
                                        ) : (
                                          <div
                                            onClick={() => setEditingField(`${scene.scene_id}.${beat.beat_id}.action`)}
                                            className="text-xs text-slate-700 leading-relaxed mb-1.5 cursor-pointer hover:text-blue-600 hover:bg-blue-50/30 rounded px-1 -mx-1 transition-colors"
                                            title="点击编辑动作描述"
                                          >
                                            {beat.action ? (typeof beat.action === 'string' ? beat.action : String(beat.action)) : '点击编辑动作描述'}
                                          </div>
                                        )}

                                        {/* 对话 — 可点击编辑 */}
                                        {editingField === `${scene.scene_id}.${beat.beat_id}.dialogue` ? (
                                          <textarea
                                            autoFocus
                                            defaultValue={Array.isArray(beat.dialogue) ? beat.dialogue.join('\n') : ''}
                                            onBlur={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { dialogue: e.target.value.split('\n').filter(Boolean) })}
                                            onKeyDown={(e) => { if (e.key === 'Escape') { setEditingField(null); e.preventDefault(); } }}
                                            className="w-full text-xs text-slate-600 border border-blue-400 rounded px-2 py-1 bg-blue-50/50 outline-none resize-none mb-1.5"
                                            rows={3}
                                            placeholder="每行格式: 角色: 台词"
                                          />
                                        ) : (
                                          <div
                                            onClick={() => setEditingField(`${scene.scene_id}.${beat.beat_id}.dialogue`)}
                                            className="space-y-0.5 mb-1.5 cursor-pointer hover:bg-blue-50/30 rounded px-1 -mx-1 transition-colors"
                                            title="点击编辑对话"
                                          >
                                            {(() => {
                                              // dialogue 可能是字符串、字符串数组、或对象数组
                                              const dialogue = beat.dialogue;
                                              if (typeof dialogue === 'string' && dialogue.trim()) {
                                                return (
                                                  <div className="flex items-start gap-1 text-xs">
                                                    <MessageSquare size={11} className="mt-0.5 text-slate-400 shrink-0" />
                                                    <span className="text-slate-600">{dialogue}</span>
                                                  </div>
                                                );
                                              }
                                              if (Array.isArray(dialogue) && dialogue.length > 0) {
                                                return dialogue.map((line: unknown, i: number) => {
                                                  const lineStr = typeof line === 'string'
                                                    ? line
                                                    : typeof line === 'object' && line !== null
                                                      ? `${(line as Record<string, unknown>).character || ''}: ${(line as Record<string, unknown>).line || ''}`
                                                      : String(line);
                                                  return (
                                                    <div key={i} className="flex items-start gap-1 text-xs">
                                                      <MessageSquare size={11} className="mt-0.5 text-slate-400 shrink-0" />
                                                      <span className="text-slate-600">{lineStr}</span>
                                                    </div>
                                                  );
                                                });
                                              }
                                              return (
                                                <div className="flex items-start gap-1 text-xs text-slate-400">
                                                  <MessageSquare size={11} className="mt-0.5 shrink-0" />
                                                  <span>点击编辑对话</span>
                                                </div>
                                              );
                                            })()}
                                          </div>
                                        )}

                                        {/* 转场 — 可点击编辑 */}
                                        {editingField === `${scene.scene_id}.${beat.beat_id}.transition_to_next` ? (
                                          <input
                                            autoFocus
                                            defaultValue={beat.transition_to_next || ''}
                                            onBlur={(e) => handleUpdateBeat(scene.scene_id, beat.beat_id, { transition_to_next: e.target.value })}
                                            onKeyDown={(e) => { if (e.key === 'Enter') handleUpdateBeat(scene.scene_id, beat.beat_id, { transition_to_next: e.currentTarget.value }); if (e.key === 'Escape') setEditingField(null); }}
                                            className="w-full text-[10px] text-slate-600 border border-blue-400 rounded px-1.5 py-0.5 bg-blue-50/50 outline-none mt-1"
                                            placeholder="转场描述..."
                                          />
                                        ) : (
                                          <div
                                            onClick={() => setEditingField(`${scene.scene_id}.${beat.beat_id}.transition_to_next`)}
                                            className="text-[10px] text-slate-400 italic mt-1 cursor-pointer hover:text-blue-600 hover:bg-blue-50/30 rounded px-1 -mx-1 transition-colors"
                                            title="点击编辑转场"
                                          >
                                            → {beat.transition_to_next || '点击编辑转场'}
                                          </div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}

                                {/* 场次转场 */}
                                {scene.transition_to_next_scene && (
                                  <div className="mt-3 pt-2 border-t border-dashed border-[#d7e3f4] text-[11px] text-slate-400 italic">
                                    → 下一场：{scene.transition_to_next_scene}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : screenplayText ? (
                    <div className="rounded-xl border border-[#d7e3f4] bg-slate-50 p-3">
                      <p className="text-xs text-slate-400 mb-2">（未检测到结构化场景数据，显示纯文本剧本）</p>
                      <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">{screenplayText}</pre>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full text-center text-slate-400">
                      <p className="text-sm">点击「生成剧本」按钮，AI 将根据章节内容自动生成短剧剧本</p>
                    </div>
                  )}

                  {workflow.screenplay_status !== 'approved' && workflow.screenplay_text && (
                    <p className="mt-2 text-xs text-amber-600">
                      请审核并批准剧本后，才能开始拆镜操作
                    </p>
                  )}
                </div>

                {/* JSON 原始数据 toggle */}
                {localScenes.length > 0 && (
                  <div className="border-t border-[#d7e3f4] shrink-0">
                    <button
                      onClick={() => {
                        const nextShow = !showRawJson;
                        setShowRawJson(nextShow);
                        if (nextShow && !rawJsonText && workflow?.screenplay_json) {
                          try {
                            setRawJsonText(JSON.stringify(workflow.screenplay_json, null, 2));
                          } catch {
                            setRawJsonText('');
                          }
                        }
                      }}
                      className="flex items-center gap-1.5 w-full px-3 py-2 text-xs text-slate-500 hover:bg-slate-50 transition-colors"
                    >
                      {showRawJson ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      <Braces size={12} className="text-slate-400" />
                      查看/编辑原始 JSON
                    </button>
                    {showRawJson && (
                      <div className="px-3 pb-3">
                        <textarea
                          value={rawJsonText}
                          onChange={(e) => setRawJsonText(e.target.value)}
                          className="w-full h-40 resize-y rounded-xl border border-[#d7e3f4] bg-slate-50 p-3 text-xs font-mono text-slate-600 focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-200 leading-relaxed"
                          placeholder="原始 JSON 数据..."
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ── 空状态：剧本已批准但无镜头时显示 ── */}
          {screenplayApproved && !parsing && sortedShots.length === 0 && (
            <div className="flex flex-1 items-center justify-center">
              <div className="max-w-md px-8 text-center text-slate-400">
                <Clapperboard size={46} className="mx-auto mb-3 opacity-40" />
                <p className="text-sm text-slate-500">
                  点击顶部「从剧本拆镜」按钮从已批准的剧本拆解为镜头列表。
                </p>
              </div>
            </div>
          )}

          {screenplayApproved && (
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
                      <div className="min-w-0 flex-1 xl:w-[400px]">
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
                        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                          <p className="text-sm text-slate-700">情节：{shot.story_summary || '暂无'}</p>
                          {shot.continuity_notes && (
                            <p className="text-xs text-slate-500">连续性：{shot.continuity_notes}</p>
                          )}
                        </div>

                        {/* 失败错误信息 */}
                        {shot.error_message && (
                          <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
                            {shot.error_message}
                          </div>
                        )}

                        </div>

                      {/* 右侧：故事版/视频预览 */}
                      <div className="grid shrink grid-cols-4 gap-3">
                        <button
                          type="button"
                          onClick={() => { setVideoWorkbench({ shotId: shot.id, type: 'character', assetId: undefined }); onAgentShotChange?.(shot.id); }}
                          className="w-[160px] rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <UserRound size={12} /> 角色资产
                          </div>
                          <div className="flex h-24 flex-col items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
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
                                    {thumbnails.slice(0, 2).map((thumb) => (
                                      <div key={thumb.name} className="flex flex-col items-center">
                                        {thumb.thumbnailUrl ? (
                                          <img
                                            src={toAssetUrl(thumb.thumbnailUrl)}
                                            alt={thumb.name}
                                            className="h-10 w-10 rounded object-cover"
                                          />
                                        ) : (
                                          <div className="flex h-10 w-10 items-center justify-center rounded bg-slate-100 text-[10px] text-slate-400">
                                            <UserRound size={14} />
                                          </div>
                                        )}
                                        <span className="mt-0.5 max-w-[40px] truncate text-[9px] text-slate-500">{thumb.name}</span>
                                      </div>
                                    ))}
                                    {thumbnails.length > 2 && (
                                      <span className="flex h-10 w-10 items-center justify-center text-[11px] text-slate-400">
                                        +{thumbnails.length - 2}
                                      </span>
                                    )}
                                  </div>
                                );
                            })()}
                          </div>
                        </button>

                        <button
                          type="button"
                          onClick={() => { setVideoWorkbench({ shotId: shot.id, type: 'scene' }); onAgentShotChange?.(shot.id); }}
                          className="w-[160px] rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <Home size={14} /> 场景 & 道具
                          </div>
                          {(() => {
                            const sceneState = videoGenStore.get(shot.id, 'scene');
                            if (sceneState?.active) {
                              return (
                                <div className="flex h-24 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
                                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                                  <span className="mt-2 text-sm text-blue-600">场景生成中...</span>
                                  {sceneState.statusMsg && (
                                    <span className="mt-1 text-xs text-blue-500">{sceneState.statusMsg}</span>
                                  )}
                                </div>
                              );
                            }
                            return (
                              <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                                待生成
                              </div>
                            );
                          })()}
                        </button>

                        <button
                          type="button"
                          onClick={() => { setVideoWorkbench({ shotId: shot.id, type: 'storyboard' }); onAgentShotChange?.(shot.id); }}
                          className="w-[160px] rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
                        >
                          <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
                            <ImageIcon size={12} /> 故事版
                          </div>
                          {(() => {
                            const sbState = videoGenStore.get(shot.id, 'storyboard');
                            if (sbState?.active) {
                              return (
                                <div className="flex h-24 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
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
                                  className="h-24 w-full rounded-lg object-cover"
                                />
                              );
                            }
                            return (
                              <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
                                暂无故事版
                              </div>
                            );
                          })()}
                        </button>

                        <button
                          type="button"
                          onClick={() => { setVideoWorkbench({ shotId: shot.id, type: 'video' }); onAgentShotChange?.(shot.id); }}
                          className="w-[160px] rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
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
                                  className="h-24 w-full rounded-lg bg-slate-950 object-contain"
                                />
                              );
                            } else if (isGenerating) {
                              return (
                                <div className="flex h-24 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
                                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                                  <span className="mt-2 text-sm text-blue-600">视频生成中...</span>
                                  {videoState.statusMsg && (
                                    <span className="mt-1 text-xs text-blue-500">{videoState.statusMsg}</span>
                                  )}
                                </div>
                              );
                            } else {
                              return (
                                <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
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
          )}
        </>
      )}

      {!workflow && (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center max-w-sm">
            <Clapperboard size={56} className="mx-auto text-slate-300" />
            <h3 className="mt-4 text-lg font-semibold text-slate-600">开始视频工作流</h3>
            <p className="mt-2 text-sm text-slate-400 leading-relaxed">
              点击上方「创建并生成剧本」按钮，AI 将自动分析章节内容，生成专业影视剧本。
            </p>
            <div className="mt-4 flex flex-col gap-1 text-xs text-slate-400">
              <div className="flex items-center gap-2 justify-center">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-[10px] font-bold text-indigo-600">1</span>
                生成剧本 → 审批
              </div>
              <div className="flex items-center gap-2 justify-center">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-[10px] font-bold text-indigo-600">2</span>
                从剧本拆镜 → 补全提示词
              </div>
              <div className="flex items-center gap-2 justify-center">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-[10px] font-bold text-indigo-600">3</span>
                生成故事版 → 生成视频 → 拼接
              </div>
            </div>
          </div>
        </div>
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
            onClose={() => { onAgentShotChange?.(undefined); setVideoWorkbench(null); }}
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
