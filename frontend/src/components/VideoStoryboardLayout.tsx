import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  type Story,
  type Chapter,
  type EntitlementResponse,
  type ChapterVideoWorkflow,
  type StoryVideoCharacter,
  type VideoAsset,
  apiHeaders,
  concatChapterVideoWorkflow,
  createChapterVideoWorkflow,
  getChapterVideoWorkflow,
  getChapterVideoWorkflowStatus,
  listChapterVideoWorkflows,
  listVideoAssets,
  parseChapterWorkflowShots,
  generateChapterWorkflowShotDetails,
  generateChapterWorkflowStoryboards,
  generateChapterWorkflowVideos,
  generateStoryVideoCharacters,
  listStoryVideoCharacters,
  reanalyzeChapterShotPrompts,
  saveChapterShotPrompts,
  regenerateChapterWorkflowStoryboard,
  regenerateChapterWorkflowVideo,
  deleteVideoAsset,
  clearShotStoryboard,
  clearShotVideo,
  generateShotSceneAsset,
  generateShotPropAsset,
  resetChapterWorkflow,
  uploadStyleReferenceImage,
  type VideoStylePreset,
} from '../api';
import { findCharacterPromptByName } from './videoWorkbenchUtils';
import ChapterListPanel from './ChapterListPanel';
import ChapterVideoWorkflowPanel from './ChapterVideoWorkflowPanel';
import StyleSelectorModal from './StyleSelectorModal';
import { toast } from '../lib/toast';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: EntitlementResponse | null;
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
  const pollTimerRef = useRef<number | null>(null);

  const resolvedChapter = currentChapter;

  const stopPolling = useCallback(() => {
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
    return detail;
  }, []);

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

    // 只有后台真正在处理的状态才算 running，等待用户操作的空闲状态不算
    const ACTIVE_STATUSES = new Set(['parsing_shots', 'generating_storyboards', 'generating_videos']);

    const tick = async () => {
      try {
        const status = await getChapterVideoWorkflowStatus(workflowId);
        const detail = await getChapterVideoWorkflow(workflowId);
        setWorkflow(detail);

        const running = ACTIVE_STATUSES.has(status.workflow_status);
        setWorkflowRunning(running);

        if (running) {
          pollTimerRef.current = window.setTimeout(() => {
            void tick();
          }, 4000);
          return;
        }

        // 解析完成，清除 parsing 状态
        setParsing(false);
        await loadChapterAssets(status.chapter_id);
      } catch (error: any) {
        setWorkflowRunning(false);
        toast.error(`刷新视频工作流失败: ${error.message || '未知错误'}`);
      }
    };

    void tick();
  }, [loadChapterAssets, stopPolling]);

  const loadLatestWorkflow = useCallback(async (chapterId: number, signal?: AbortSignal) => {
    setWorkflowLoading(true);
    setSelectedShotIds(new Set());
    setSkippedShotIds(new Set());
    try {
      const data = await listChapterVideoWorkflows(chapterId);
      if (signal?.aborted) return;
      const latest = data.workflows?.[0] ?? null;
      setWorkflow(latest);
      setConcatVideoUrl(null);

      if (latest) {
        setSelectedReferenceIds(latest.character_reference_ids || []);
        if (latest.workflow_status === 'completed' || latest.workflow_status === 'failed' || latest.workflow_status === 'shots_ready' || latest.workflow_status === 'pending') {
          await loadWorkflowDetail(latest.id, signal);
          setWorkflowRunning(false);
        } else {
          void pollWorkflowUntilSettled(latest.id);
        }
      } else {
        setWorkflowRunning(false);
      }
    } catch {
      if (!signal?.aborted) {
        setWorkflow(null);
        setWorkflowRunning(false);
      }
    } finally {
      if (!signal?.aborted) setWorkflowLoading(false);
    }
  }, [loadWorkflowDetail, pollWorkflowUntilSettled]);

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
              if (payload?.style_preset?.name) setSelectedStyle(payload.style_preset.name);
            })
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, [resolvedChapter?.id]);

  useEffect(() => {
    if (!resolvedChapter?.id) return;
    const aborter = new AbortController();
    setWorkflow(null);
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

      await parseChapterWorkflowShots(wf.id);
      toast.success('拆镜完成');
      void pollWorkflowUntilSettled(wf.id);
    } catch (error: any) {
      toast.error(`拆镜失败: ${error.message || '未知错误'}`);
    } finally {
      setWorkflowRunning(false);
      setParsing(false);
    }
  }, [pollWorkflowUntilSettled, workflow, resolvedChapter?.id, selectedReferenceIds, selectedStyle]);

  const handleGenerateShotDetails = useCallback(async (shotIds: number[]) => {
    if (!workflow || shotIds.length === 0) return;
    if (shotIds.length > 5) {
      toast.error('最多支持 5 个镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      const result = await generateChapterWorkflowShotDetails(workflow.id, { shot_ids: shotIds });
      if (result.success) {
        toast.success(`已为 ${result.total} 个镜头生成详情`);
      } else {
        toast.error(result.error || '生成详情失败');
      }
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
    } catch (error: any) {
      toast.error(`生成详情失败: ${error.message || '未知错误'}`);
    } finally {
      setWorkflowRunning(false);
    }
  }, [workflow]);

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
      await regenerateChapterWorkflowStoryboard(shotId, undefined, refAssetIds);
      toast.success('故事版已重新生成');
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
      await loadChapterAssets(detail.chapter_id);
    } catch (error: any) {
      toast.error(`故事版重生成失败: ${error.message || '未知错误'}`);
    }
  }, [loadChapterAssets, workflow]);

  const handleRegenerateVideo = useCallback(async (shotId: number, refAssetIds?: number[], aspectRatio: '16:9' | '9:16' = '16:9') => {
    if (!workflow) return;
    try {
      await regenerateChapterWorkflowVideo(shotId, undefined, refAssetIds, aspectRatio);
      toast.success('视频已重新生成');
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
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
        await fetch(`/api/chapters/${resolvedChapter.id}/video-style-preset`, {
          method: 'PUT',
          headers: apiHeaders(true),
          body: JSON.stringify({ style_preset_id: preset.id }),
        });
      } catch {
        // 静默失败，不阻断主流程
      }
    }
    // 如果工作流已存在，更新其风格参考图
    if (workflow?.id && referenceImageUrl) {
      try {
        await fetch(`/api/video/chapter-workflows/${workflow.id}/style-reference-url`, {
          method: 'PUT',
          headers: apiHeaders(true),
          body: JSON.stringify({ style_reference_image_url: referenceImageUrl }),
        });
      } catch {
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
      await generateChapterWorkflowStoryboards(workflow.id, { shot_ids: shotIds });
      toast.success('故事版生成任务已启动');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
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
      await generateChapterWorkflowVideos(workflow.id, { shot_ids: shotIds });
      toast.success('视频生成任务已启动');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
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
      for (const shotId of shotIds) {
        await reanalyzeChapterShotPrompts(shotId);
      }
      toast.success(`提示词已重新分析（${shotIds.length} 个镜头）`);
      await handleRefreshWorkflow();
    } catch (error: any) {
      toast.error(`重新分析失败: ${error.message || '未知错误'}`);
    } finally {
      setWorkflowRunning(false);
    }
  }, [workflow, handleRefreshWorkflow]);

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

  if (!story) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <p className="text-sm">请先在「作品」页面选择一个项目再进入工作台。</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 gap-4 bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_100%)] p-4">
      <ChapterListPanel
        chapters={chapterInfos}
        selectedChapterId={resolvedChapter?.id ?? null}
        collapsed={leftCollapsed}
        onSelect={(chapter) => {
          onChapterChange(chapter);
          setWorkflow(null);
          setConcatVideoUrl(null);
        }}
        onToggleCollapse={() => setLeftCollapsed((value) => !value)}
      />

      <div className="flex-1 min-w-0 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
        <ChapterVideoWorkflowPanel
          workflow={workflow}
          workflowLoading={workflowLoading}
          workflowRunning={workflowRunning}
          chapterAssets={chapterAssets}
          selectedReferenceIds={selectedReferenceIds}
          selectedStyle={selectedStyle}
          styleReferenceImageUrl={styleReferenceImageUrl}
          stylePresets={stylePresets}
          concatVideoUrl={concatVideoUrl}
          selectedShotIds={selectedShotIds}
          skippedShotIds={skippedShotIds}
          onSelectReferenceIds={setSelectedReferenceIds}
          onRefreshWorkflow={handleRefreshWorkflow}
          onConcatWorkflow={handleConcatWorkflow}
          onRegenerateStoryboard={handleRegenerateStoryboard}
          onRegenerateVideo={handleRegenerateVideo}
          onStyleChange={handleStyleChange}
          onOpenStyleSelector={() => setStyleSelectorOpen(true)}
          onParseShots={handleParseShots}
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
        />
      </div>

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
    </div>
  );
}
