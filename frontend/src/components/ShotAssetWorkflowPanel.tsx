import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  apiHeaders,
  approveShotStoryboard,
  deleteVideoAsset,
  generateShotCharacterAsset,
  generateShotFrames,
  getShotFrames,
  getShotStoryboards,
  getVideoJob,
  listVideoAssets,
  parseShotAssetPrompts,
  regenerateVideoAsset,
  rejectShotStoryboard,
  renderShotVideo,
  renderStoryboardFrame,
  type RenderedClip,
  type ShotAssetPromptDraft,
  type ShotFramesResponse,
  type VideoAsset,
  type VideoGenerationJob,
  type VideoShot,
  type EntitlementResponse,
  toPublicVideoAssetUrl,
} from '../api';
import ShotFrameRegenerationModal from './ShotFrameRegenerationModal';
import { confirm } from '../lib/confirm';

function entitlementNumber(entitlements: EntitlementResponse | null | undefined, key: string, fallback: number): number {
  const raw = entitlements?.entitlements?.[key];
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string') {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export interface ShotAssetWorkflowPanelProps {
  shot: VideoShot | null;
  jobs: VideoGenerationJob[];
  clips: RenderedClip[];
  onJobsChange: React.Dispatch<React.SetStateAction<VideoGenerationJob[]>>;
  onClipsChange: React.Dispatch<React.SetStateAction<RenderedClip[]>>;
  chapter: any;
  stylePresets: any[];
  chapterStylePreset: any;
  storyStylePreset: any;
  entitlements?: EntitlementResponse | null;
  onShotStylePresetChange?: (preset: string | null) => void;
  loading: boolean;
}

type SectionKey = 'style' | 'characters' | 'scenes' | 'storyboard' | 'frames' | 'bundle' | 'result';
const SECTION_LABELS: Record<SectionKey, string> = {
  style: '风格',
  characters: '角色',
  scenes: '场景',
  storyboard: '分镜',
  frames: '首尾帧',
  bundle: '资产包',
  result: '结果',
};

function toAssetUrl(filePath?: string | null) {
  return toPublicVideoAssetUrl(filePath) || '';
}

function formatStyleName(name?: string | null) {
  if (!name) return '';
  const trimmed = name.trim();
  const nameMap: Record<string, string> = {
    '3A游戏滚析': '3A游戏渲染',
    '3A游戏滾析': '3A游戏渲染',
    '3A游戏渲染': '3D游戏渲染',
    '日式动漫风': '日式动漫风',
    '水墨国风': '水墨国风',
    '水彩手画风': '水彩手绘风',
    '科技赛模风': '科技赛博风',
  };
  return nameMap[trimmed] || trimmed;
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    pending: '等待中',
    queued: '排队中',
    running: '生成中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };
  return map[status] || status;
}

function statusColor(status: string) {
  const map: Record<string, string> = {
    pending: 'text-slate-500',
    queued: 'text-amber-500',
    running: 'text-blue-500',
    succeeded: 'text-emerald-600',
    failed: 'text-rose-500',
    cancelled: 'text-slate-400',
  };
  return map[status] || 'text-slate-500';
}

export default function ShotAssetWorkflowPanel({
  shot,
  jobs,
  clips,
  onJobsChange,
  onClipsChange,
  chapter,
  stylePresets,
  chapterStylePreset,
  storyStylePreset,
  entitlements,
  onShotStylePresetChange,
}: ShotAssetWorkflowPanelProps) {
  const [activeSection, setActiveSection] = useState<SectionKey>('style');
  const [error, setError] = useState<string | null>(null);

  const videoSecondsLimit = entitlementNumber(entitlements, 'video.generate.seconds.monthly_limit', 0);

  const [characterAssets, setCharacterAssets] = useState<VideoAsset[]>([]);
  const [sceneAssets, setSceneAssets] = useState<VideoAsset[]>([]);

  const [storyboardLoading, setStoryboardLoading] = useState(false);
  const [storyboardSubmitting, setStoryboardSubmitting] = useState(false);
  const [storyboardLocking, setStoryboardLocking] = useState(false);
  const [storyboardData, setStoryboardData] = useState<{ assets: VideoAsset[]; active_storyboard_asset_id?: number | null; storyboard_locked: boolean } | null>(null);

  const [framesLoading, setFramesLoading] = useState(false);
  const [framesSubmitting, setFramesSubmitting] = useState(false);
  const [framesData, setFramesData] = useState<ShotFramesResponse | null>(null);

  const [generatingCharacters, setGeneratingCharacters] = useState(false);
  const [generatingScene, setGeneratingScene] = useState(false);
  const [submittingVideo, setSubmittingVideo] = useState(false);

  const [promptDrafts, setPromptDrafts] = useState<ShotAssetPromptDraft | null>(null);
  const [parsingPrompts, setParsingPrompts] = useState(false);
  const [selectedCharacterName, setSelectedCharacterName] = useState('');
  const [selectedCharacterPrompt, setSelectedCharacterPrompt] = useState('');
  const [storyboardPromptDraft, setStoryboardPromptDraft] = useState('');
  const [firstFramePromptDraft, setFirstFramePromptDraft] = useState('');
  const [lastFramePromptDraft, setLastFramePromptDraft] = useState('');
  const [videoPromptDraft, setVideoPromptDraft] = useState('');

  const [previewAsset, setPreviewAsset] = useState<VideoAsset | null>(null);
  const [previewTitle, setPreviewTitle] = useState('');
  const [previewBusy, setPreviewBusy] = useState(false);
  const [deletingAssetId, setDeletingAssetId] = useState<number | null>(null);

  const [selectedReferenceAssetIds, setSelectedReferenceAssetIds] = useState<number[]>([]);

  const currentStyleName =
    formatStyleName(shot?.style_preset) ||
    formatStyleName(chapterStylePreset?.style_preset?.name) ||
    formatStyleName(storyStylePreset?.style_preset?.name) ||
    '';

  const loadAssets = useCallback(async () => {
    if (!chapter?.id) return;
    try {
      const [characters, scenes] = await Promise.all([
        listVideoAssets(chapter.id, 'character_reference'),
        listVideoAssets(chapter.id, 'scene_reference'),
      ]);
      setCharacterAssets(characters.assets || []);
      setSceneAssets(scenes.assets || []);
    } catch (err: any) {
      setError(err.message || '加载资产失败');
    }
  }, [chapter?.id]);

  const loadStoryboards = useCallback(async () => {
    if (!shot?.id) return;
    setStoryboardLoading(true);
    try {
      const result = await getShotStoryboards(shot.id);
      setStoryboardData(result);
    } catch (err: any) {
      setStoryboardData(null);
      setError(err.message || '加载分镜失败');
    } finally {
      setStoryboardLoading(false);
    }
  }, [shot?.id]);

  const loadFrames = useCallback(async () => {
    if (!shot?.id) return;
    setFramesLoading(true);
    try {
      const result = await getShotFrames(shot.id);
      setFramesData(result);
    } catch (err: any) {
      setFramesData(null);
      setError(err.message || '加载首尾帧失败');
    } finally {
      setFramesLoading(false);
    }
  }, [shot?.id]);

  // 回读 shot 上已保存的解析结果，避免重复 AI 解析
  const loadSavedPrompts = useCallback(() => {
    if (!shot) return;
    const charPrompts = shot.character_prompts_json;
    const hasSaved = charPrompts && charPrompts.length > 0;
    if (hasSaved) {
      const draft: ShotAssetPromptDraft = {
        shot_id: shot.id,
        style_preset: shot.style_preset || '',
        character_prompts: charPrompts,
        scene_prompt: shot.scene_prompt || '',
        prop_prompts: shot.prop_prompts_json || [],
        storyboard_prompt: shot.storyboard_prompt || '',
        first_frame_prompt: shot.first_frame_prompt || '',
        last_frame_prompt: shot.last_frame_prompt || '',
        video_prompt: shot.video_prompt || '',
      };
      setPromptDrafts(draft);
      setStoryboardPromptDraft(draft.storyboard_prompt || '');
      setFirstFramePromptDraft(draft.first_frame_prompt || '');
      setLastFramePromptDraft(draft.last_frame_prompt || '');
      setVideoPromptDraft(draft.video_prompt || '');
      const first = charPrompts[0];
      setSelectedCharacterName(first?.name || '');
      setSelectedCharacterPrompt(first?.prompt || '');
    }
  }, [shot]);

  useEffect(() => {
    setError(null);
    setPromptDrafts(null);
    setStoryboardPromptDraft('');
    setFirstFramePromptDraft('');
    setLastFramePromptDraft('');
    setVideoPromptDraft('');
    setSelectedCharacterName('');
    setSelectedCharacterPrompt('');
    if (!shot || !chapter) return;
    void loadSavedPrompts();
    void loadAssets();
    void loadStoryboards();
    void loadFrames();
  }, [shot?.id, chapter?.id, loadSavedPrompts, loadAssets, loadStoryboards, loadFrames]);

  const activeStoryboard = useMemo(() => {
    if (!storyboardData?.assets?.length) return null;
    return storyboardData.assets.find((a) => a.id === storyboardData.active_storyboard_asset_id) || storyboardData.assets[0];
  }, [storyboardData]);

  const firstFrame = framesData?.first_frames?.[0] || null;
  const lastFrame = framesData?.last_frames?.[0] || null;
  const activeClip = clips.find((clip) => clip.is_active) || null;

  const candidateReferenceAssets = useMemo(() => {
    const all: VideoAsset[] = [];
    all.push(...characterAssets, ...sceneAssets, ...(storyboardData?.assets || []));
    all.push(...((framesData?.first_frames || []) as unknown as VideoAsset[]));
    all.push(...((framesData?.last_frames || []) as unknown as VideoAsset[]));
    const seen = new Set<number>();
    return all.filter((a) => {
      if (!a?.id || seen.has(a.id)) return false;
      seen.add(a.id);
      return true;
    });
  }, [characterAssets, sceneAssets, storyboardData?.assets, framesData?.first_frames, framesData?.last_frames]);

  useEffect(() => {
    setSelectedReferenceAssetIds((prev) => {
      const allowed = new Set(candidateReferenceAssets.map((a) => a.id));
      const keep = prev.filter((id) => allowed.has(id));
      if (keep.length) return keep;
      return candidateReferenceAssets.map((a) => a.id);
    });
  }, [candidateReferenceAssets]);

  const parseAssetPrompts = useCallback(async () => {
    if (!shot?.id) return;
    setParsingPrompts(true);
    setError(null);
    try {
      const draft = await parseShotAssetPrompts(shot.id, { style_preset: currentStyleName || undefined });
      setPromptDrafts(draft);
      setStoryboardPromptDraft(draft.storyboard_prompt || '');
      setFirstFramePromptDraft(draft.first_frame_prompt || '');
      setLastFramePromptDraft(draft.last_frame_prompt || '');
      setVideoPromptDraft(draft.video_prompt || '');
      const first = draft.character_prompts?.[0];
      setSelectedCharacterName(first?.name || '');
      setSelectedCharacterPrompt(first?.prompt || '');
    } catch (err: any) {
      setError(err.message || '解析提示词失败');
    } finally {
      setParsingPrompts(false);
    }
  }, [shot?.id, currentStyleName]);

  const generateCharacterAssets = async () => {
    if (!shot?.id || !selectedCharacterPrompt.trim()) return;
    setGeneratingCharacters(true);
    setError(null);
    try {
      await generateShotCharacterAsset(shot.id, {
        character_name: selectedCharacterName || '角色',
        prompt: selectedCharacterPrompt.trim(),
        style_preset: currentStyleName || undefined,
        source_asset_ids: selectedReferenceAssetIds,
      });
      await loadAssets();
    } catch (err: any) {
      setError(err.message || '角色图生成失败');
    } finally {
      setGeneratingCharacters(false);
    }
  };

  const generateSceneAsset = async () => {
    if (!shot?.scene_id) return;
    setGeneratingScene(true);
    setError(null);
    try {
      const res = await fetch(`/api/scenes/${shot.scene_id}/concept-art/generate`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({
          style_preset: currentStyleName || '写实电影感',
          overwrite: true,
          reference_asset_ids: selectedReferenceAssetIds,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadAssets();
    } catch (err: any) {
      setError(err.message || '场景图生成失败');
    } finally {
      setGeneratingScene(false);
    }
  };

  const generateStoryboard = async () => {
    if (!shot?.id) return;
    setStoryboardSubmitting(true);
    setError(null);
    try {
      await renderStoryboardFrame(shot.id, {
        provider: 'image2',
        style_preset: currentStyleName || '写实电影感',
        prompt: storyboardPromptDraft.trim() || undefined,
        reference_asset_ids: selectedReferenceAssetIds,
      });
      await loadStoryboards();
    } catch (err: any) {
      setError(err.message || '分镜图生成失败');
    } finally {
      setStoryboardSubmitting(false);
    }
  };

  const toggleStoryboardLock = async () => {
    if (!shot?.id) return;
    setStoryboardLocking(true);
    setError(null);
    try {
      if (storyboardData?.storyboard_locked) await rejectShotStoryboard(shot.id);
      else await approveShotStoryboard(shot.id);
      await loadStoryboards();
    } catch (err: any) {
      setError(err.message || '分镜锁定更新失败');
    } finally {
      setStoryboardLocking(false);
    }
  };

  const generateFrames = async (frameType: 'both' | 'first_frame' | 'last_frame' = 'both') => {
    if (!shot?.id) return;
    setFramesSubmitting(true);
    setError(null);
    try {
      const run = async (type: 'first_frame' | 'last_frame', prompt: string) => {
        await generateShotFrames(shot.id!, {
          frame_type: type,
          prompt: prompt.trim() || undefined,
          overwrite: false,
          style_preset: currentStyleName || undefined,
          reference_asset_ids: selectedReferenceAssetIds,
        });
      };
      if (frameType === 'both') {
        await run('first_frame', firstFramePromptDraft);
        await run('last_frame', lastFramePromptDraft);
      } else {
        await run(frameType, frameType === 'first_frame' ? firstFramePromptDraft : lastFramePromptDraft);
      }
      await loadFrames();
    } catch (err: any) {
      setError(err.message || '首尾帧生成失败');
    } finally {
      setFramesSubmitting(false);
    }
  };

  const handleDeleteAsset = async (asset: VideoAsset) => {
    if (!asset?.id) return;
    if (!(await confirm({ message: `确认删除资产「${asset.name}」吗？` }))) return;
    setDeletingAssetId(asset.id);
    try {
      await deleteVideoAsset(asset.id);
      await Promise.all([loadAssets(), loadStoryboards(), loadFrames()]);
    } catch (err: any) {
      setError(err.message || '删除资产失败');
    } finally {
      setDeletingAssetId(null);
    }
  };

  const openAssetWorkbench = (asset: VideoAsset, title?: string) => {
    setPreviewAsset(asset);
    setPreviewTitle(title || asset.name || '资产重绘');
  };

  const handleRedrawAsset = async (payload: { prompt: string; mode: 'full' | 'partial'; mask?: string }) => {
    if (!previewAsset?.id) return;
    setPreviewBusy(true);
    setError(null);
    try {
      await regenerateVideoAsset(previewAsset.id, payload.prompt, payload.mask);
      await Promise.all([loadAssets(), loadStoryboards(), loadFrames()]);
      setPreviewAsset(null);
    } catch (err: any) {
      setError(err.message || '重绘失败');
    } finally {
      setPreviewBusy(false);
    }
  };

  const pollJob = useCallback((jobId: number) => {
    const tick = async () => {
      try {
        const nextJob = await getVideoJob(jobId);
        onJobsChange((prev) => prev.map((j) => (j.id === jobId ? nextJob : j)));
        if (nextJob.clip) onClipsChange((prev) => (prev.some((c) => c.id === nextJob.clip!.id) ? prev : [...prev, nextJob.clip!]));
        if (['succeeded', 'failed', 'cancelled'].includes(nextJob.status)) return;
        setTimeout(tick, 3000);
      } catch {
        setTimeout(tick, 5000);
      }
    };
    setTimeout(tick, 3000);
  }, [onJobsChange, onClipsChange]);

  const submitVideo = async () => {
    if (!shot?.id) return;
    setSubmittingVideo(true);
    setError(null);
    try {
      const result = await renderShotVideo(shot.id, {
        provider: '',
        duration_seconds: shot.duration_seconds || 5,
        aspect_ratio: '16:9',
        fps: 24,
        reference_asset_ids: selectedReferenceAssetIds,
        input_mode: selectedReferenceAssetIds.length > 0 ? 'image_to_video' : 'text_to_video',
        prompt: videoPromptDraft || undefined,
      });
      onJobsChange((prev) => [result.job, ...prev]);
      pollJob(result.job.id);
      setActiveSection('result');
    } catch (err: any) {
      setError(err.message || '视频任务提交失败');
    } finally {
      setSubmittingVideo(false);
    }
  };

  if (!shot) {
    return <aside className="w-[360px] shrink-0 rounded-[20px] border border-[#d7e3f4] bg-white p-6 text-sm text-slate-500">请选择镜头后管理资产</aside>;
  }

  const styleSource = shot?.style_preset ? '镜头' : chapterStylePreset?.style_preset?.name ? '章节' : storyStylePreset?.style_preset?.name ? '故事' : '默认';
  const activeJobs = jobs.slice(0, 5);

  return (
    <aside className="w-[360px] shrink-0 overflow-hidden rounded-[20px] border border-[#d7e3f4] bg-white xl:w-[380px]">
      <div className="border-b border-[#d7e3f4] p-3">
        <div className="text-sm font-semibold text-slate-800">镜头 {shot.shot_number}: {shot.title}</div>
        <div className="mt-1 text-xs text-slate-500">{shot.duration_seconds || 5}s · {shot.shot_type || 'medium'} · {currentStyleName || '默认风格'}</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {(['style', 'characters', 'scenes', 'storyboard', 'frames', 'bundle', 'result'] as SectionKey[]).map((k) => (
            <button key={k} className={`rounded-full border px-2.5 py-1 text-xs ${activeSection === k ? 'border-[#2563eb] bg-[#2563eb] text-white' : 'border-[#d7e3f4] bg-white text-slate-600 hover:border-[#93c5fd] hover:text-[#1d4ed8]'}`} onClick={() => setActiveSection(k)}>
              {SECTION_LABELS[k]}
            </button>
          ))}
        </div>
      </div>

      <div className="h-[calc(100%-118px)] overflow-y-auto p-3 space-y-3">
        {error ? <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}

        {activeSection === 'style' ? (
          <div className="space-y-3">
            <div className="text-xs text-slate-500">风格来源：{styleSource}</div>
            <select
              value={shot.style_preset ? stylePresets.find((s: any) => s.name === shot.style_preset)?.id ?? '' : chapterStylePreset?.style_preset_id ?? ''}
              onChange={(e) => {
                if (!e.target.value) return;
                const preset = stylePresets.find((s: any) => s.id === Number(e.target.value));
                onShotStylePresetChange?.(preset?.name || null);
              }}
              className="w-full rounded-lg border border-[#d7e3f4] px-2 py-2 text-sm"
            >
              <option value="">选择风格预设</option>
              {stylePresets.map((preset: any) => <option key={preset.id} value={preset.id}>{formatStyleName(preset.name)}</option>)}
            </select>
            <button onClick={parseAssetPrompts} disabled={parsingPrompts} className="w-full rounded-lg border border-[#2563eb] px-3 py-2 text-xs text-[#1d4ed8]">{parsingPrompts ? '解析中...' : 'AI 解析资产提示词'}</button>
          </div>
        ) : null}

        {activeSection === 'characters' ? (
          <div className="space-y-3">
            <button onClick={generateCharacterAssets} disabled={generatingCharacters || !selectedCharacterPrompt.trim()} className="rounded-lg bg-[#2563eb] px-3 py-2 text-xs text-white hover:bg-[#1d4ed8]">{generatingCharacters ? '生成中...' : '生成角色图'}</button>
            <select value={selectedCharacterName} onChange={(e)=>{ const n=e.target.value; setSelectedCharacterName(n); const hit=promptDrafts?.character_prompts?.find((p)=>p.name===n); setSelectedCharacterPrompt(hit?.prompt||''); }} className="w-full rounded-lg border border-[#d7e3f4] px-2 py-2 text-xs">
              <option value="">选择角色</option>
              {(promptDrafts?.character_prompts || []).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
            <textarea value={selectedCharacterPrompt} onChange={(e)=>setSelectedCharacterPrompt(e.target.value)} className="h-24 w-full rounded-lg border border-[#d7e3f4] p-2 text-xs" placeholder="角色设定板提示词" />
            <div className="grid grid-cols-2 gap-2 max-h-52 overflow-y-auto">
              {characterAssets.map((a) => (
                <div key={a.id} className="rounded-lg border border-[#d7e3f4] p-1.5">
                  <img src={toAssetUrl(a.file_path)} alt={a.name} className="aspect-[3/4] w-full cursor-zoom-in rounded object-cover" loading="lazy" decoding="async" onClick={() => openAssetWorkbench(a, `${a.name}（角色参考）`)} />
                  <div className="mt-1 flex items-center justify-between text-[11px]"><span className="truncate">{a.name}</span><button onClick={() => handleDeleteAsset(a)} disabled={deletingAssetId===a.id} className="text-rose-500">删除</button></div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {activeSection === 'scenes' ? (
          <div className="space-y-3">
            <button onClick={generateSceneAsset} disabled={generatingScene} className="rounded-lg bg-[#2563eb] px-3 py-2 text-xs text-white hover:bg-[#1d4ed8]">{generatingScene ? '生成中...' : '生成场景图'}</button>
            <div className="space-y-2">
              {sceneAssets.map((a) => (
                <div key={a.id} className="flex gap-2 rounded-lg border border-[#d7e3f4] p-2">
                  <img src={toAssetUrl(a.file_path)} alt={a.name} className="h-16 w-24 cursor-zoom-in rounded object-cover" loading="lazy" decoding="async" onClick={() => openAssetWorkbench(a, `${a.name}（场景参考）`)} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-xs">{a.name}</div>
                      <button onClick={() => handleDeleteAsset(a)} disabled={deletingAssetId === a.id} className="shrink-0 text-[11px] text-rose-500 hover:text-rose-600 disabled:opacity-50">删除</button>
                    </div>
                    <div className="text-[11px] text-slate-400">{a.style_preset || '默认风格'}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {activeSection === 'storyboard' ? (
          <div className="space-y-3">
            <div className="flex gap-2">
              <button onClick={generateStoryboard} disabled={storyboardSubmitting} className="rounded-lg bg-[#2563eb] px-3 py-2 text-xs text-white hover:bg-[#1d4ed8]">{storyboardSubmitting ? '生成中...' : '生成分镜图'}</button>
              <button onClick={toggleStoryboardLock} disabled={storyboardLocking} className="rounded-lg border border-[#d7e3f4] px-3 py-2 text-xs">{storyboardData?.storyboard_locked ? '解锁' : '锁定'}</button>
              {activeStoryboard ? (
                <button onClick={() => handleDeleteAsset(activeStoryboard)} disabled={deletingAssetId === activeStoryboard.id} className="rounded-lg border border-rose-200 px-3 py-2 text-xs text-rose-500 hover:bg-rose-50 disabled:opacity-50">删除</button>
              ) : null}
            </div>
            <textarea value={storyboardPromptDraft} onChange={(e)=>setStoryboardPromptDraft(e.target.value)} className="h-24 w-full rounded-lg border border-[#d7e3f4] p-2 text-xs" placeholder="分镜提示词" />
            {storyboardLoading ? <div className="text-xs text-slate-500">加载中...</div> : activeStoryboard ? <img src={toAssetUrl(activeStoryboard.file_path)} alt="storyboard" className="w-full cursor-zoom-in rounded-lg border border-[#d7e3f4]" loading="lazy" decoding="async" onClick={() => openAssetWorkbench(activeStoryboard, '主分镜图重绘')} /> : <div className="text-xs text-slate-500">暂无分镜图</div>}
          </div>
        ) : null}

        {activeSection === 'frames' ? (
          <div className="space-y-3">
            <div className="flex gap-2">
              <button onClick={() => generateFrames('first_frame')} disabled={framesSubmitting} className="rounded-lg bg-[#2563eb] px-3 py-2 text-xs text-white hover:bg-[#1d4ed8]">首帧</button>
              <button onClick={() => generateFrames('last_frame')} disabled={framesSubmitting} className="rounded-lg bg-[#2563eb] px-3 py-2 text-xs text-white hover:bg-[#1d4ed8]">尾帧</button>
              <button onClick={() => generateFrames('both')} disabled={framesSubmitting} className="rounded-lg bg-[#2563eb] px-3 py-2 text-xs text-white hover:bg-[#1d4ed8]">全生成</button>
            </div>
            <textarea value={firstFramePromptDraft} onChange={(e)=>setFirstFramePromptDraft(e.target.value)} className="h-20 w-full rounded-lg border border-[#d7e3f4] p-2 text-xs" placeholder="首帧提示词" />
            <textarea value={lastFramePromptDraft} onChange={(e)=>setLastFramePromptDraft(e.target.value)} className="h-20 w-full rounded-lg border border-[#d7e3f4] p-2 text-xs" placeholder="尾帧提示词" />
            <div className="grid grid-cols-2 gap-2">
              <div>
                {framesLoading ? <div className="text-xs">加载中...</div> : firstFrame ? (
                  <div className="space-y-1">
                    <img src={toAssetUrl(firstFrame.file_path)} alt="first" className="cursor-zoom-in rounded-lg border border-[#d7e3f4]" loading="lazy" decoding="async" onClick={() => openAssetWorkbench(firstFrame as unknown as VideoAsset, '首帧重绘')} />
                    <button onClick={() => handleDeleteAsset(firstFrame as unknown as VideoAsset)} disabled={deletingAssetId === (firstFrame as any).id} className="text-[11px] text-rose-500 hover:text-rose-600 disabled:opacity-50">删除</button>
                  </div>
                ) : <div className="text-xs text-slate-500">暂无首帧</div>}
              </div>
              <div>
                {framesLoading ? <div className="text-xs">加载中...</div> : lastFrame ? (
                  <div className="space-y-1">
                    <img src={toAssetUrl(lastFrame.file_path)} alt="last" className="cursor-zoom-in rounded-lg border border-[#d7e3f4]" loading="lazy" decoding="async" onClick={() => openAssetWorkbench(lastFrame as unknown as VideoAsset, '尾帧重绘')} />
                    <button onClick={() => handleDeleteAsset(lastFrame as unknown as VideoAsset)} disabled={deletingAssetId === (lastFrame as any).id} className="text-[11px] text-rose-500 hover:text-rose-600 disabled:opacity-50">删除</button>
                  </div>
                ) : <div className="text-xs text-slate-500">暂无尾帧</div>}
              </div>
            </div>
          </div>
        ) : null}

        {activeSection === 'bundle' ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-[#d7e3f4] p-3">
              <div className="mb-2 text-xs font-semibold">本次引用资产</div>
              <div className="max-h-40 overflow-y-auto space-y-1 text-xs">
                {candidateReferenceAssets.map((asset) => (
                  <label key={asset.id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selectedReferenceAssetIds.includes(asset.id)}
                      onChange={(e) => {
                        setSelectedReferenceAssetIds((prev) => {
                          if (e.target.checked) return Array.from(new Set([...prev, asset.id]));
                          return prev.filter((id) => id !== asset.id);
                        });
                      }}
                    />
                    <span className="truncate">{asset.name}</span>
                    <span className="text-slate-400">{asset.asset_type}</span>
                  </label>
                ))}
              </div>
            </div>
            <textarea value={videoPromptDraft} onChange={e => setVideoPromptDraft(e.target.value)} className="h-28 w-full rounded-lg border border-[#d7e3f4] p-2 text-xs resize-y" placeholder="视频生成提示词（AI 解析或手动编辑）" />
            <div className="flex items-center justify-between gap-3">
              {videoSecondsLimit > 0 && (
                <span className="text-xs text-slate-400">本月视频时长配额 {videoSecondsLimit}s</span>
              )}
              <button onClick={submitVideo} disabled={submittingVideo} className="flex-1 rounded-lg bg-gradient-to-r from-[#1d4ed8] to-[#1e40af] px-4 py-2 text-xs font-semibold text-white">
                {submittingVideo ? '提交中...' : '生成视频'}
              </button>
            </div>
          </div>
        ) : null}

        {activeSection === 'result' ? (
          <div className="space-y-3">
            {activeClip ? <video src={activeClip.video_path} controls className="aspect-video w-full rounded-lg border border-[#d7e3f4]" /> : <div className="text-xs text-slate-500">暂无视频</div>}
            <div className="space-y-1">{activeJobs.map((job) => <div key={job.id} className="flex items-center justify-between rounded border border-[#d7e3f4] px-2 py-1 text-xs"><span className={statusColor(job.status)}>{statusLabel(job.status)}</span><span className="text-slate-400">{job.progress}%</span></div>)}</div>
          </div>
        ) : null}
      </div>

      {previewAsset ? (
        <ShotFrameRegenerationModal
          imageSrc={toAssetUrl(previewAsset.file_path)}
          title={previewTitle || previewAsset.name || '资产'}
          prompt={previewAsset.prompt || ''}
          busy={previewBusy}
          onClose={() => !previewBusy && setPreviewAsset(null)}
          onSubmit={handleRedrawAsset}
        />
      ) : null}
    </aside>
  );
}
