import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  type Story,
  type Chapter,
  type ChapterVideoWorkflow,
  type ChapterVideoShotCreate,
  type StoryVideoCharacter,
  type VideoAsset,
  apiHeaders,
  concatChapterVideoWorkflow,
  createChapterVideoWorkflow,
  createChapterWorkflowShot,
  getChapterVideoWorkflow,
  getChapterVideoWorkflowStatus,
  listChapterVideoWorkflows,
  listVideoAssets,
  parseChapterWorkflowShots,
  generateChapterWorkflowShotDetails,
  generateChapterWorkflowStoryboards,
  generateChapterWorkflowVideos,
  generateWorkflowScreenplay,
  generateStoryVideoCharacters,
  listStoryVideoCharacters,
  reanalyzeChapterShotPrompts,
  reanalyzeChapterWorkflowStoryboardPrompt,
  saveChapterShotPrompts,
  regenerateChapterWorkflowStoryboard,
  regenerateChapterWorkflowVideo,
  deleteVideoAsset,
  clearShotStoryboard,
  clearShotVideo,
  resetChapterWorkflow,
  type VideoStylePreset,
} from '../api';
import { findCharacterPromptByName } from './videoWorkbenchUtils';
import { isChapterWorkflowActive } from './chapterWorkflowUtils';
import ChapterListPanel from './ChapterListPanel';
import ChapterVideoWorkflowPanel from './ChapterVideoWorkflowPanel';
import StyleSelectorModal from './StyleSelectorModal';
import AssetManagementModal from './AssetManagementModal';
import VideoCanvasPanel from './VideoCanvasPanel';
import { toast } from '../lib/toast';
import { normalizeErrorMessage, readResponseError } from '../lib/errors';
import { confirm } from '../lib/confirm';
import { videoGenStore } from '../videoGenStore';

const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: Record<string, any> | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated?: () => void | Promise<void>;
}

export default function VideoStoryboardLayout({
  story,
  chapters,
  currentChapter,
  entitlements: _entitlements,
  onChapterChange,
  onContentUpdated: _onContentUpdated,
}: Props) {
  const [leftCollapsed, setLeftCollapsed] = useState(false);

  /** 切换 Agent 面板：打开时自动折叠左侧章节列表 */
  function handleToggleAgentPanel() {
    setVideoAgentOpen((prev) => {
      const next = !prev;
      if (next) setLeftCollapsed(true);
      return next;
    });
  }

  function handleCloseAgentPanel() {
    setVideoAgentOpen(false);
    setLeftCollapsed(false);
  }
  const [chapterAssets, setChapterAssets] = useState<VideoAsset[]>([]);
  const [workflow, setWorkflow] = useState<ChapterVideoWorkflow | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [concatVideoUrl, setConcatVideoUrl] = useState<string | null>(null);
  const [selectedReferenceIds, setSelectedReferenceIds] = useState<number[]>([]);
  const [stylePresets, setStylePresets] = useState<VideoStylePreset[]>([]);
  const [selectedStyle, setSelectedStyle] = useState('写实电影感');
  const [styleReferenceImageUrl, setStyleReferenceImageUrl] = useState<string | null>(null);
  const [styleSelectorOpen, setStyleSelectorOpen] = useState(false);
  const [videoAspectRatio, setVideoAspectRatio] = useState<'16:9' | '9:16'>('16:9');
  const [selectedShotIds, setSelectedShotIds] = useState<Set<number>>(new Set());
  const [skippedShotIds, setSkippedShotIds] = useState<Set<number>>(new Set());
  const [videoCharacters, setVideoCharacters] = useState<StoryVideoCharacter[]>([]);
  const [characterLoading, setCharacterLoading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [screenplayGenerating, setScreenplayGenerating] = useState(false);
  const [assetManagementOpen, setAssetManagementOpen] = useState(false);
  const [videoAgentOpen, setVideoAgentOpen] = useState(false);
  // 分镜列表已由画布模式取代；VITE_ENABLE_SHOT_LIST=true 可临时恢复（默认下线）
  const shotListEnabled = import.meta.env.VITE_ENABLE_SHOT_LIST === 'true';
  const [viewMode, setViewMode] = useState<'list' | 'canvas'>(shotListEnabled ? 'list' : 'canvas');
  const [canvasDirty, setCanvasDirty] = useState(false);
  const [agentShotId, setAgentShotId] = useState<number | undefined>(undefined);
  const pollTimerRef = useRef<number | null>(null);
  const pollGenerationRef = useRef(0);
  const pollAbortRef = useRef<AbortController | null>(null);
  const workflowStyleChapterIdRef = useRef<number | null>(null);

  const resolvedChapter = currentChapter;

  const handleChapterSelect = useCallback(async (chapter: Chapter) => {
    if (chapter.id === currentChapter?.id) return;
    if (viewMode === 'canvas' && canvasDirty) {
      const discard = await confirm({
        title: '未保存的画布修改',
        message: '切换章节将放弃当前未保存的节点、连线和配置修改。',
        confirmText: '放弃修改',
        danger: true,
      });
      if (!discard) return;
    }
    setCanvasDirty(false);
    onChapterChange(chapter);
    setWorkflow(null);
    setWorkflowRunning(false);
    setParsing(false);
    setConcatVideoUrl(null);
  }, [canvasDirty, currentChapter?.id, onChapterChange, viewMode]);

  const handleViewModeChange = useCallback(async (nextMode: 'list' | 'canvas') => {
    if (nextMode === viewMode) return;
    if (viewMode === 'canvas' && canvasDirty) {
      const discard = await confirm({
        title: '未保存的画布修改',
        message: '切换到列表模式将放弃当前未保存的节点、连线和配置修改。',
        confirmText: '放弃修改',
        danger: true,
      });
      if (!discard) return;
    }
    setCanvasDirty(false);
    setViewMode(nextMode);
  }, [canvasDirty, viewMode]);

  const restoreWorkflowStyle = useCallback((nextWorkflow: ChapterVideoWorkflow | null) => {
    if (!nextWorkflow) {
      workflowStyleChapterIdRef.current = null;
      setStyleReferenceImageUrl(null);
      return;
    }
    workflowStyleChapterIdRef.current = nextWorkflow.chapter_id;
    setSelectedStyle(nextWorkflow.video_style ?? '');
    setStyleReferenceImageUrl(nextWorkflow.style_reference_image_url ?? null);
  }, []);

  const stopPolling = useCallback(() => {
    pollGenerationRef.current += 1;
    pollAbortRef.current?.abort();
    pollAbortRef.current = null;
    if (pollTimerRef.current) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const loadChapterAssets = useCallback(async (chapterId: number, signal?: AbortSignal) => {
    try {
      const res = await listVideoAssets(chapterId);
      if (signal?.aborted) return;
      setChapterAssets(res.assets || []);
    } catch {
      if (!signal?.aborted) setChapterAssets([]);
    }
  }, []);

  const loadWorkflowDetail = useCallback(async (workflowId: number, signal?: AbortSignal) => {
    const detail = await getChapterVideoWorkflow(workflowId);
    if (signal?.aborted) return null;
    setWorkflow(detail);
    restoreWorkflowStyle(detail);
    return detail;
  }, [restoreWorkflowStyle]);

  const loadVideoCharacters = useCallback(async (storyId: number, signal?: AbortSignal) => {
    try {
      setCharacterLoading(true);
      const data = await listStoryVideoCharacters(storyId);
      if (signal?.aborted) return;
      setVideoCharacters(data.characters || []);
    } catch {
      if (!signal?.aborted) setVideoCharacters([]);
    } finally {
      if (!signal?.aborted) setCharacterLoading(false);
    }
  }, []);

  const pollWorkflowUntilSettled = useCallback(async (workflowId: number) => {
    stopPolling();
    const pollGeneration = pollGenerationRef.current;
    const pollAborter = new AbortController();
    pollAbortRef.current = pollAborter;

    const tick = async () => {
      if (pollGenerationRef.current !== pollGeneration) return;
      try {
        const status = await getChapterVideoWorkflowStatus(workflowId);
        if (pollGenerationRef.current !== pollGeneration) return;
        const detail = await getChapterVideoWorkflow(workflowId);
        if (pollGenerationRef.current !== pollGeneration) return;
        setWorkflow({ ...detail, ...status });
        restoreWorkflowStyle(detail);

        const running = isChapterWorkflowActive(status.workflow_status);
        setWorkflowRunning(running);

        if (running) {
          if (pollGenerationRef.current !== pollGeneration) return;
          pollTimerRef.current = window.setTimeout(() => {
            void tick();
          }, 4000);
          return;
        }

        detail.shots.forEach(shot => {
          if (shot.status === 'storyboard_ready') {
            videoGenStore.markSucceeded(shot.id, 'storyboard');
          }
          if (shot.status === 'video_ready') {
            videoGenStore.markSucceeded(shot.id);
          }
          if (shot.status === 'failed') {
            // 仅清除或标记仍在 active 的故事版状态
            const sbState = videoGenStore.get(shot.id, 'storyboard');
            if (sbState?.active) {
              videoGenStore.markFailed(shot.id, normalizeErrorMessage(shot.error_message, '故事版生成失败，请重试'), 'storyboard');
            }
            videoGenStore.markFailed(shot.id, normalizeErrorMessage(shot.error_message, '视频生成失败，请重试'));
          }
        });

        // 解析完成，清除 parsing 状态
        setParsing(false);
        if (status.workflow_status === 'failed') {
          toast.error(normalizeErrorMessage(status.error_message || status.message, '拆镜失败，请重试'));
        }
        await loadChapterAssets(status.chapter_id, pollAborter.signal);
      } catch (error: any) {
        if (pollGenerationRef.current !== pollGeneration) return;
        // 网络抖动不代表后端任务结束，保持运行态并继续查询，直到后端返回终态。
        setWorkflowRunning(true);
        console.error(`刷新视频工作流失败，稍后重试: ${error.message || '未知错误'}`);
        pollTimerRef.current = window.setTimeout(() => {
          void tick();
        }, 8000);
      }
    };

    void tick();
  }, [loadChapterAssets, restoreWorkflowStyle, stopPolling]);

  const loadLatestWorkflow = useCallback(async (chapterId: number, signal?: AbortSignal) => {
    setWorkflowLoading(true);
    setSelectedShotIds(new Set());
    setSkippedShotIds(new Set());
    try {
      const data = await listChapterVideoWorkflows(chapterId);
      if (signal?.aborted) return;
      const latest = data.workflows?.[0] ?? null;
      setWorkflow(latest);
      restoreWorkflowStyle(latest);
      setConcatVideoUrl(null);

      if (latest) {
        setSelectedReferenceIds(latest.character_reference_ids || []);
        const isActive = isChapterWorkflowActive(latest.workflow_status);
        if (isActive) {
          // 立即设置运行状态，防止按钮在轮询启动前可点击
          setWorkflowRunning(true);
          // 恢复拆镜遮罩（用户切走章节时会被清除，切回时若任务仍进行中则恢复）
          if (latest.workflow_status === 'parsing_shots') {
            setParsing(true);
          }
          void pollWorkflowUntilSettled(latest.id);
        } else {
          // 已结束或待机状态：加载完整详情
          const detail = await loadWorkflowDetail(latest.id, signal);
          setWorkflowRunning(false);
          setParsing(false);

          // 清除可能残留的 storyboard/video 状态（用户切走时轮询被 stopPolling 终止导致状态未清除）
          if (detail && !signal?.aborted) {
            detail.shots.forEach(shot => {
              if (shot.status === 'storyboard_ready') {
                videoGenStore.markSucceeded(shot.id, 'storyboard');
              }
              if (shot.status === 'video_ready') {
                videoGenStore.markSucceeded(shot.id);
              }
              if (shot.status === 'failed') {
                const sbState = videoGenStore.get(shot.id, 'storyboard');
                if (sbState?.active) {
                  videoGenStore.markFailed(shot.id, normalizeErrorMessage(shot.error_message, '故事版生成失败，请重试'), 'storyboard');
                }
                videoGenStore.markFailed(shot.id, normalizeErrorMessage(shot.error_message, '视频生成失败，请重试'));
              }
            });
          }
        }
      } else {
        setWorkflowRunning(false);
      }
    } catch (err: any) {
      if (!signal?.aborted) {
        setWorkflow(null);
        setWorkflowRunning(false);
        console.error('加载工作流失败 chapter=%s', chapterId, err);
      }
    } finally {
      if (!signal?.aborted) setWorkflowLoading(false);
    }
  }, [loadWorkflowDetail, pollWorkflowUntilSettled, restoreWorkflowStyle]);

  useEffect(() => {
    fetch('/api/video-style-presets', { headers: apiHeaders() })
      .then((response) => response.json())
      .then((data) => {
        setStylePresets(data.presets || []);
        if (resolvedChapter?.id) {
          const lsKey = `video_style_preset_${resolvedChapter.id}`;
          const savedStyle = localStorage.getItem(lsKey);
          if (savedStyle) {
            setSelectedStyle(savedStyle);
            // 不 return，继续从 API 同步，确保与后端一致
          }
          fetch(`/api/chapters/${resolvedChapter.id}/video-style-preset`, { headers: apiHeaders() })
            .then((response) => response.json())
            .then((payload) => {
              if (payload?.style_preset?.name && workflowStyleChapterIdRef.current !== resolvedChapter.id) {
                setSelectedStyle(payload.style_preset.name);
              }
            })
            .catch((error) => {
              toast.error(normalizeErrorMessage(error, '加载视频风格配置失败，请稍后重试'));
            });
        }
      })
      .catch((error) => {
        toast.error(normalizeErrorMessage(error, '加载视频工作流失败，请稍后重试'));
      });
  }, [resolvedChapter?.id]);

  useEffect(() => {
    if (!resolvedChapter?.id) return;
    const aborter = new AbortController();
    setWorkflow(null);
    setWorkflowRunning(false);
    setParsing(false);
    setConcatVideoUrl(null);
    stopPolling();
    void loadChapterAssets(resolvedChapter.id, aborter.signal);
    void loadVideoCharacters(story.id, aborter.signal);
    void loadLatestWorkflow(resolvedChapter.id, aborter.signal);

    return () => {
      aborter.abort();
      stopPolling();
    };
  }, [resolvedChapter?.id, loadChapterAssets, loadVideoCharacters, loadLatestWorkflow, stopPolling, story.id]);

  const chapterInfos = useMemo(() => chapters.map((chapter) => ({
    chapter,
    shotCount: chapter.id === resolvedChapter?.id ? (workflow?.shots?.length ?? workflow?.total_shots ?? 0) : 0,
    hasFrames: chapter.id === resolvedChapter?.id ? Boolean(workflow?.shots?.some((shot) => shot.storyboard_image_url)) : false,
  })), [chapters, resolvedChapter?.id, workflow]);

  const handleParseShots = useCallback(async () => {
    if (!resolvedChapter?.id) return;
    if (parsing || workflowRunning) return;
    if (workflow && workflow.screenplay_status !== 'approved') {
      toast.error('请先生成并批准剧本后再拆镜');
      return;
    }
    try {
      setWorkflowRunning(true);
      setParsing(true);
      setConcatVideoUrl(null);

      let wf = workflow;
      if (!wf) {
        wf = await createChapterVideoWorkflow({
          chapter_id: resolvedChapter.id,
          character_reference_ids: selectedReferenceIds,
          video_style: selectedStyle,
          style_reference_image_url: styleReferenceImageUrl,
        });
        setWorkflow(wf);
      }

      const status = await parseChapterWorkflowShots(wf.id);
      setWorkflow((prev) => (prev && prev.id === wf!.id ? { ...prev, ...(status as Partial<ChapterVideoWorkflow>) } : prev));
      toast.success('拆镜任务已提交');
      void pollWorkflowUntilSettled(wf.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      setParsing(false);
      toast.error(`拆镜失败: ${error.message || '未知错误'}`);
    }
  }, [parsing, pollWorkflowUntilSettled, workflow, workflowRunning, resolvedChapter?.id, selectedReferenceIds, selectedStyle, styleReferenceImageUrl]);

  const handleCreateAndGenerateScreenplay = useCallback(async () => {
    if (!resolvedChapter?.id) return;
    if (workflowRunning || screenplayGenerating) return;
    try {
      setWorkflowRunning(true);
      setScreenplayGenerating(true);
      let wf = workflow;
      if (!wf) {
        wf = await createChapterVideoWorkflow({
          chapter_id: resolvedChapter.id,
          character_reference_ids: selectedReferenceIds,
          video_style: selectedStyle,
          style_reference_image_url: styleReferenceImageUrl,
        });
        setWorkflow(wf);
      }
      await generateWorkflowScreenplay(wf.id);
      const refreshedWorkflow = await getChapterVideoWorkflow(wf.id);
      setWorkflow(refreshedWorkflow);
      restoreWorkflowStyle(refreshedWorkflow);
      toast.success('剧本生成完成');
    } catch (error: any) {
      toast.error(`剧本生成失败: ${error.message || '未知错误'}`);
    } finally {
      setScreenplayGenerating(false);
      setWorkflowRunning(false);
    }
  }, [workflowRunning, screenplayGenerating, workflow, resolvedChapter?.id, selectedReferenceIds, selectedStyle, styleReferenceImageUrl, restoreWorkflowStyle]);

  const handleGenerateShotDetails = useCallback(async (shotIds: number[]) => {
    if (!workflow || shotIds.length === 0) return;
    if (shotIds.length > 5) {
      toast.error('最多支持 5 个镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      const status = await generateChapterWorkflowShotDetails(workflow.id, { shot_ids: shotIds });
      setWorkflow((prev) => (prev && prev.id === workflow.id ? { ...prev, ...(status as Partial<ChapterVideoWorkflow>) } : prev));
      toast.success('镜头详情生成任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`生成详情失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);

  const handleRefreshWorkflow = useCallback(async () => {
    if (!resolvedChapter?.id) return;
    await Promise.all([
      loadLatestWorkflow(resolvedChapter.id),
      loadChapterAssets(resolvedChapter.id),
    ]);
    // 确保强制加载工作流完整详情（含 shots 的 prompts），
    // loadLatestWorkflow 在非终态时不会加载详情
    if (workflow?.id) {
      await loadWorkflowDetail(workflow.id);
    }
  }, [loadLatestWorkflow, loadChapterAssets, resolvedChapter?.id, workflow?.id, loadWorkflowDetail]);

  const handleCreateShot = useCallback(async (payload: ChapterVideoShotCreate) => {
    if (!workflow) return;
    const shot = await createChapterWorkflowShot(workflow.id, payload);
    setWorkflow((current) => current?.id === workflow.id
      ? { ...current, shots: [...current.shots, shot], total_shots: current.shots.length + 1, workflow_status: 'shots_ready' }
      : current);
    setSelectedShotIds((current) => new Set(current).add(shot.id));
    toast.success(`镜头 ${shot.shot_index} 已添加`);
  }, [workflow]);
  const handleConcatWorkflow = useCallback(async () => {
    if (!workflow) return;
    try {
      const result = await concatChapterVideoWorkflow(workflow.id);
      setConcatVideoUrl(result.video_url || null);
      toast.success(result.message || '整章视频拼接完成');
    } catch (error: any) {
      toast.error(`拼接失败: ${error.message || '未知错误'}`);
    }
  }, [workflow]);

  const handleRegenerateStoryboard = useCallback(async (shotId: number, refAssetIds?: number[]) => {
    if (!workflow) return;
    try {
      videoGenStore.startJob(shotId, 0, 'storyboard');
      await regenerateChapterWorkflowStoryboard(shotId, undefined, refAssetIds);
      toast.success('故事版已重新生成');
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
      await loadChapterAssets(detail.chapter_id);
      videoGenStore.markSucceeded(shotId, 'storyboard');
    } catch (error: any) {
      videoGenStore.markFailed(shotId, error.message || '故事版重生成失败', 'storyboard');
      toast.error(`故事版重生成失败: ${error.message || '未知错误'}`);
    }
  }, [loadChapterAssets, workflow]);

  const handleRegenerateVideo = useCallback(async (shotId: number, refAssetIds?: number[], aspectRatio: '16:9' | '9:16' = '16:9', promptOverride?: string) => {
    if (!workflow) return;
    try {
      // 为该镜头创建初始 loading 状态
      videoGenStore.startJob(shotId, 0);

      await regenerateChapterWorkflowVideo(shotId, promptOverride, refAssetIds, aspectRatio);
      toast.success('视频已重新生成');
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      // 清理占位状态，防止状态残留
      videoGenStore.clear(shotId);
      toast.error(`视频重生成失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);

  const handleDeleteStoryboard = useCallback(async (shotId: number) => {
    if (!workflow) return;
    try {
      await clearShotStoryboard(shotId);
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
      toast.success('故事版图片已删除');
    } catch (error: any) {
      toast.error(`删除故事版图片失败: ${error.message || '未知错误'}`);
    }
  }, [workflow]);

  const handleDeleteVideo = useCallback(async (shotId: number) => {
    if (!workflow) return;
    try {
      await clearShotVideo(shotId);
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
      toast.success('视频已删除');
    } catch (error: any) {
      toast.error(`删除视频失败: ${error.message || '未知错误'}`);
    }
  }, [workflow]);

  const handleDeleteChapterAsset = useCallback(async (assetId: number) => {
    try {
      await deleteVideoAsset(assetId);
      toast.success('角色资产已删除');
      if (resolvedChapter?.id) {
        await loadChapterAssets(resolvedChapter.id);
      }
    } catch (error: any) {
      toast.error(`删除角色资产失败: ${error.message || '未知错误'}`);
    }
  }, [resolvedChapter?.id, loadChapterAssets]);

  const handleStyleChange = useCallback(async (styleName: string, referenceImageUrl: string | null = null) => {
    setSelectedStyle(styleName);
    setStyleReferenceImageUrl(referenceImageUrl);
    if (resolvedChapter?.id) {
      localStorage.setItem(`video_style_preset_${resolvedChapter.id}`, styleName);
    }
    const preset = stylePresets.find((item) => item.name === styleName);
    if (preset && resolvedChapter?.id) {
      try {
        const response = await fetch(`/api/chapters/${resolvedChapter.id}/video-style-preset`, {
          method: 'PUT',
          headers: apiHeaders(true),
          body: JSON.stringify({ style_preset_id: preset.id }),
        });
        if (!response.ok) throw new Error(await readResponseError(response, '保存视频风格失败'));
      } catch (error: any) {
        toast.error(`保存视频风格失败: ${error.message || '未知错误'}`);
        // 静默失败，不阻断主流程
      }
    }
    // 如果工作流已存在，更新其风格参考图
    if (workflow?.id) {
      try {
        const response = await fetch(`/api/video/chapter-workflows/${workflow.id}/style-reference-url`, {
          method: 'PUT',
          headers: apiHeaders(true),
          body: JSON.stringify({
            video_style: styleName || null,
            style_reference_image_url: referenceImageUrl,
          }),
        });
        if (!response.ok) throw new Error(await readResponseError(response, '保存风格参考图失败'));
        setWorkflow((current) => (
          current?.id === workflow.id
            ? { ...current, style_reference_image_url: referenceImageUrl }
            : current
        ));
      } catch (error: any) {
        toast.error(`保存风格参考图失败: ${error.message || '未知错误'}`);
        // 静默失败，不阻断主流程
      }
    }
  }, [resolvedChapter?.id, stylePresets, workflow?.id]);

  const handleGenerateStoryboards = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) {
      toast.error('请先勾选需要生成故事版的镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      // 为每个选中镜头创建故事版 loading 状态
      shotIds.forEach(shotId => {
        videoGenStore.startJob(shotId, 0, 'storyboard');
      });
      const status = await generateChapterWorkflowStoryboards(workflow.id, { shot_ids: shotIds });
      setWorkflow((prev) => (prev && prev.id === workflow.id ? { ...prev, ...(status as Partial<ChapterVideoWorkflow>) } : prev));
      toast.success('故事版生成任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      // 清除占位状态
      shotIds.forEach(shotId => videoGenStore.clear(shotId, 'storyboard'));
      toast.error(`故事版生成失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);

  const handleGenerateVideos = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) {
      toast.error('请先勾选需要生成视频的镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      
      // 为每个选中的镜头创建初始状态
      shotIds.forEach(shotId => {
        videoGenStore.startJob(shotId, 0);
      });
      
      const status = await generateChapterWorkflowVideos(workflow.id, { shot_ids: shotIds });
      setWorkflow((prev) => (prev && prev.id === workflow.id ? { ...prev, ...(status as Partial<ChapterVideoWorkflow>) } : prev));
      toast.success('视频生成任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      // 清理占位状态，防止状态残留
      shotIds.forEach(shotId => videoGenStore.clear(shotId));
      toast.error(`视频生成失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);

  const handleResetWorkflow = useCallback(async () => {
    if (!workflow) return;
    try {
      await resetChapterWorkflow(workflow.id);
      toast.success('工作流已重置');
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
    } catch (error: any) {
      toast.error(`重置失败: ${error.message || '未知错误'}`);
    }
  }, [workflow]);

  const handleToggleShotSelection = useCallback((shotId: number) => {
    setSelectedShotIds((prev) => {
      const next = new Set(prev);
      if (next.has(shotId)) {
        next.delete(shotId);
      } else {
        next.add(shotId);
      }
      return next;
    });
  }, []);

  const handleSelectAllShots = useCallback(() => {
    if (!workflow?.shots) return;
    setSelectedShotIds((prev) => {
      if (prev.size === workflow.shots.length) {
        return new Set();
      }
      return new Set(workflow.shots.map((shot) => shot.id));
    });
  }, [workflow]);

  const handleSkipShot = useCallback((shotId: number) => {
    setSkippedShotIds((prev) => {
      const next = new Set(prev);
      if (next.has(shotId)) {
        next.delete(shotId);
      } else {
        next.add(shotId);
      }
      return next;
    });
    setSelectedShotIds((prev) => {
      const next = new Set(prev);
      next.delete(shotId);
      return next;
    });
  }, []);

  const handleReanalyzePrompt = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) return;
    try {
      setWorkflowRunning(true);
      const status = await reanalyzeChapterWorkflowStoryboardPrompt(workflow.id, { shot_ids: shotIds });
      setWorkflow((prev) => (prev && prev.id === workflow.id ? { ...prev, ...(status as Partial<ChapterVideoWorkflow>) } : prev));
      toast.success('提示词重新分析任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`重新分析失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);

  const handleReanalyzeCurrentCharacter = useCallback(async (shotId: number, characterName: string) => {
    try {
      const result = await reanalyzeChapterShotPrompts(shotId);
      const matched = findCharacterPromptByName(result.character_prompts, characterName);
      if (matched) {
        toast.success(`角色「${characterName}」提示词已重新分析`);
      } else {
        toast.info(`角色「${characterName}」提示词已重新分析（名称未完全匹配，已更新全局提示词）`);
      }
      // 始终刷新工作流，确保所有提示词（角色/场景/道具/故事版/视频）同步更新
      await handleRefreshWorkflow();
    } catch (error: any) {
      toast.error(`重新分析失败: ${error.message || '未知错误'}`);
    }
  }, [handleRefreshWorkflow]);

  const handleStoryboardPromptChange = useCallback(async (shotId: number, value: string) => {
    try {
      await saveChapterShotPrompts(shotId, { storyboard_prompt: value });
      await handleRefreshWorkflow();
    } catch (err) {
      console.error('保存故事版提示词失败', err);
    }
  }, [handleRefreshWorkflow]);

  const handleGenerateCharacters = useCallback(async () => {
    try {
      setCharacterLoading(true);
      const data = await generateStoryVideoCharacters(story.id);
      setVideoCharacters(data.characters || []);
      toast.success('角色资产分析生成完成');
    } catch (error: any) {
      toast.error(`角色资产生成失败: ${error.message || '未知错误'}`);
    } finally {
      setCharacterLoading(false);
    }
  }, [story.id]);

  /* TODO: 以下两个函数将在后续 PR 中接入 UI 按钮时启用
  const handleGenerateSceneAsset = useCallback(async (shotId: number, prompt: string) => {
    try {
      await generateShotSceneAsset(shotId, { prompt });
      toast.success('场景参考图已生成');
      if (resolvedChapter?.id) {
        await loadChapterAssets(resolvedChapter.id);
      }
    } catch (err: any) {
      toast.error(`场景图生成失败: ${err.message}`);
    }
  }, [resolvedChapter?.id, loadChapterAssets]);

  const handleGeneratePropAsset = useCallback(async (shotId: number, propName: string, prompt: string) => {
    try {
      await generateShotPropAsset(shotId, { prop_name: propName, prompt });
      toast.success(`道具「${propName}」参考图已生成`);
      if (resolvedChapter?.id) {
        await loadChapterAssets(resolvedChapter.id);
      }
    } catch (err: any) {
      toast.error(`道具图生成失败: ${err.message}`);
    }
  }, [resolvedChapter?.id, loadChapterAssets]);
  */

  if (!story) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <p className="text-sm">请先在「作品」页面选择一个项目再进入工作台。</p>
      </div>
    );
  }

  return (
    <>
    <div className="relative flex h-full min-h-0 flex-col bg-white sm:flex-row">
      <ChapterListPanel
        chapters={chapterInfos}
        selectedChapterId={resolvedChapter?.id ?? null}
        collapsed={leftCollapsed}
        className="max-sm:h-[132px] max-sm:w-full"
        onSelect={(chapter) => { void handleChapterSelect(chapter); }}
        onToggleCollapse={() => setLeftCollapsed((value) => !value)}
      />

      <div className="flex min-w-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-white">
          <div className="flex h-11 shrink-0 items-center justify-between border-b border-[#d7e3f4] px-3">
            {shotListEnabled ? (
              <div className="inline-flex border border-slate-200 bg-slate-50 p-0.5">
                <button type="button" onClick={() => void handleViewModeChange('list')} className={`px-3 py-1 text-xs font-medium ${viewMode === 'list' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>列表</button>
                <button type="button" onClick={() => void handleViewModeChange('canvas')} className={`px-3 py-1 text-xs font-medium ${viewMode === 'canvas' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>无限画布</button>
              </div>
            ) : (
              <span className="text-xs font-medium text-slate-700">无限画布</span>
            )}
            {viewMode === 'canvas' && shotListEnabled && <span className="text-xs text-slate-500">画布与列表工作流可相互配合</span>}
          </div>
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          {viewMode === 'canvas' ? (
            <VideoCanvasPanel
              key={`video-canvas-${story.id}-${resolvedChapter?.id ?? 'story'}`}
              storyId={story.id}
              chapterId={resolvedChapter?.id}
              workflow={workflow}
              assets={chapterAssets}
              stylePresets={stylePresets}
              onDirtyChange={setCanvasDirty}
              onAssetsChanged={() => resolvedChapter ? void loadChapterAssets(resolvedChapter.id) : undefined}
              onOpenAssetManagement={() => setAssetManagementOpen(true)}
            />
          ) : (
          <ChapterVideoWorkflowPanel
          workflow={workflow}
          workflowLoading={workflowLoading}
          workflowRunning={workflowRunning}
          screenplayGenerating={screenplayGenerating}
          chapterNovelContent={resolvedChapter?.novel_content ?? undefined}
          chapterAssets={chapterAssets}
          selectedReferenceIds={selectedReferenceIds}
          selectedStyle={selectedStyle}
          styleReferenceImageUrl={styleReferenceImageUrl}
          stylePresets={stylePresets}
          concatVideoUrl={concatVideoUrl}
          selectedShotIds={selectedShotIds}
          skippedShotIds={skippedShotIds}
          onRefreshWorkflow={handleRefreshWorkflow}
          onCreateShot={handleCreateShot}
          onConcatWorkflow={handleConcatWorkflow}
          onRegenerateStoryboard={handleRegenerateStoryboard}
          onRegenerateVideo={handleRegenerateVideo}
          onStyleChange={handleStyleChange}
          onOpenStyleSelector={() => setStyleSelectorOpen(true)}
          onParseShots={handleParseShots}
          onCreateAndGenerateScreenplay={handleCreateAndGenerateScreenplay}
          parsing={parsing}
          onGenerateShotDetails={handleGenerateShotDetails}
          onGenerateStoryboards={handleGenerateStoryboards}
          onGenerateVideos={handleGenerateVideos}
          onToggleShotSelection={handleToggleShotSelection}
          onSelectAllShots={handleSelectAllShots}
          onSkipShot={handleSkipShot}
          onReanalyzePrompt={handleReanalyzePrompt}
          onReanalyzeCurrentCharacter={handleReanalyzeCurrentCharacter}
          onStoryboardPromptChange={handleStoryboardPromptChange}
          onDeleteChapterAsset={handleDeleteChapterAsset}
          onDeleteStoryboard={handleDeleteStoryboard}
          onDeleteVideo={handleDeleteVideo}
          videoCharacters={videoCharacters}
          characterLoading={characterLoading}
          onGenerateCharacters={handleGenerateCharacters}
          onResetWorkflow={handleResetWorkflow}
          videoAspectRatio={videoAspectRatio}
          onVideoAspectRatioChange={setVideoAspectRatio}
          onOpenAssetManagement={() => setAssetManagementOpen(true)}
          onAgentShotChange={setAgentShotId}
          renderAiAssistantButton={
            <button
              type="button"
              onClick={handleToggleAgentPanel}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100 transition-colors"
            >
              {videoAgentOpen ? '关闭 AI 助手' : 'AI 助手'}
            </button>
          }
        />
          )}
          </div>
        </div>
      </div>

      {/* AI 视频工作流助手 — 桌面内嵌右栏，移动端全屏抽屉 */}
      {videoAgentOpen && workflow && (
        <div className="flex w-[400px] shrink-0 flex-col overflow-hidden border-l border-[#d7e3f4] bg-white max-sm:fixed max-sm:inset-0 max-sm:z-40 max-sm:w-full max-sm:border-l-0">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#d7e3f4] shrink-0" style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 12px)' }}>
            <span className="text-sm font-semibold text-slate-700">AI 视频工作流助手</span>
            <button onClick={handleCloseAgentPanel} className="text-slate-400 hover:text-slate-600 text-lg leading-none">&times;</button>
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">
            <Suspense fallback={<div className="p-4 text-sm text-slate-500">正在加载 AI 助手...</div>}>
              <AgentPanel
                storyId={story.id}
                chapterId={resolvedChapter?.id}
                storyTitle={story.title}
                chapterTitle={resolvedChapter?.title || undefined}
                workflowType="video"
                workflowId={workflow.id}
                shotId={agentShotId}
                onContentUpdated={handleRefreshWorkflow}
              />
            </Suspense>
          </div>
        </div>
      )}
    </div>

    {resolvedChapter?.id && assetManagementOpen && (
      <AssetManagementModal
        chapterId={resolvedChapter.id}
        onClose={() => setAssetManagementOpen(false)}
        onAssetsChanged={() => void loadChapterAssets(resolvedChapter.id)}
      />
    )}

    {/* 风格选择弹窗 */}
    <StyleSelectorModal
      isOpen={styleSelectorOpen}
      onClose={() => setStyleSelectorOpen(false)}
      presets={stylePresets}
      selectedStyleName={selectedStyle}
      styleReferenceImageUrl={styleReferenceImageUrl}
      workflowId={workflow?.id ?? null}
      onStyleSelect={(styleName, refUrl) => {
        handleStyleChange(styleName, refUrl);
      }}
    />
    </>
  );
}
