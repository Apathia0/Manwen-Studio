import { memo, useMemo, useState } from 'react';
import {
  generateSceneShots,
  generateShotPrompts,
  renderStoryboardFrame,
  approveShotStoryboard,
  rejectShotStoryboard,
  getShotStoryboards,
  updateVideoShot,
  setMasterStoryboard,
  deleteShot,
  createSceneShot,
  reorderSceneShots,
  type ScriptScene,
  type VideoShot,
  type VideoAsset,
  type EntitlementResponse,
} from '../api';
import { toast } from '../lib/toast';
import ShotFrameRegenerationModal from './ShotFrameRegenerationModal';

function entitlementNumber(entitlements: EntitlementResponse | null | undefined, key: string, fallback: number): number {
  const raw = entitlements?.entitlements?.[key];
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string') {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

interface Props {
  scene: ScriptScene | null;
  shots: VideoShot[];
  shotsLoading?: boolean;
  scenesLoading?: boolean;
  entitlements?: EntitlementResponse | null;
  onShotsChange: (shots: VideoShot[]) => void;
  onShotSelect: (shot: VideoShot) => void;
}

export default memo(function StoryboardPanel({
  scene,
  shots,
  shotsLoading,
  scenesLoading,
  entitlements,
  onShotsChange,
  onShotSelect,
}: Props) {
  const shotLimit = entitlementNumber(entitlements, 'shot.generate.monthly_limit', 0);
  const [generating, setGenerating] = useState(false);
  const [generatingPrompts, setGeneratingPrompts] = useState<number | null>(null);
  const [renderingSb, setRenderingSb] = useState<number | null>(null);
  const [approving, setApproving] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expandedShot, setExpandedShot] = useState<number | null>(null);
  const [storyboardAssets, setStoryboardAssets] = useState<Record<number, { assets: VideoAsset[]; locked: boolean }>>({});

  // ─── Inline editing state ──────────────────────────────────
  const [editingShotId, setEditingShotId] = useState<number | null>(null);
  const [editFormData, setEditFormData] = useState<Partial<VideoShot>>({});
  const [savingShotId, setSavingShotId] = useState<number | null>(null);

  // ─── Delete confirmation ──────────────────────────────────
  const [deletingShotId, setDeletingShotId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  // ─── Reorder state ─────────────────────────────────────────
  const [hasOrderChanged, setHasOrderChanged] = useState(false);

  // ─── Rerender modal state ──────────────────────────────────
  const [showRerenderModal, setShowRerenderModal] = useState(false);
  const [rerenderShotId, setRerenderShotId] = useState<number | null>(null);
  const [rerenderPrompt, setRerenderPrompt] = useState('');
  const [rerenderingPrompt, setRerenderingPrompt] = useState(false);
  const [rerenderImageSrc, setRerenderImageSrc] = useState('');

  // ─── Set master loading ────────────────────────────────────
  const [settingMaster, setSettingMaster] = useState<number | null>(null);

  const readyShotCount = useMemo(
    () => shots.filter((shot) => !!shot.video_prompt || shot.status === 'prompt_ready').length,
    [shots],
  );

  const storyboardReadyCount = useMemo(
    () => shots.filter((shot) => shot.status === 'storyboard_ready' || shot.storyboard_asset_id).length,
    [shots],
  );

  async function loadStoryboards(shotId: number) {
    try {
      const result = await getShotStoryboards(shotId);
      setStoryboardAssets((prev) => ({
        ...prev,
        [shotId]: { assets: result.assets, locked: result.storyboard_locked },
      }));
    } catch {}
  }

  async function handleGenerateShots() {
    if (!scene?.id) return;
    setGenerating(true);
    setError(null);
    setNotice('正在根据场次生成镜头拆解...');
    try {
      const result = await generateSceneShots(scene.id, {
        style: 'cinematic',
        shot_count_hint: 4,
        duration_budget_seconds: scene.estimated_duration_seconds || 18,
      });
      onShotsChange(result.shots);
      if (result.shots.length > 0) {
        onShotSelect(result.shots[0]);
        setExpandedShot(result.shots[0].id ?? result.shots[0].shot_number);
      }
      setNotice(`镜头已生成，共 ${result.shots.length} 条。建议先生成分镜图，再到右侧生成视频。`);
    } catch (err: any) {
      setError(err.message || '生成镜头失败');
      setNotice(null);
    } finally {
      setGenerating(false);
    }
  }

  async function handleGeneratePrompts(shot: VideoShot) {
    if (!shot.id) return;
    setGeneratingPrompts(shot.id);
    setError(null);
    setNotice(`正在为镜头 ${shot.shot_number} 生成提示词...`);
    try {
      const result = await generateShotPrompts(shot.id, {
        style: 'cinematic',
        provider: 'sora',
        include_references: true,
      });
      const nextShots = shots.map((item) => (item.id === shot.id ? result.shot : item));
      onShotsChange(nextShots);
      onShotSelect(result.shot);
      setExpandedShot(result.shot.id ?? result.shot.shot_number);
      setNotice(`镜头 ${shot.shot_number} 的提示词已生成，现在可以生成主分镜图或直接生成视频。`);
    } catch (err: any) {
      setError(err.message || '生成提示词失败');
      setNotice(null);
    } finally {
      setGeneratingPrompts(null);
    }
  }

  async function handleRenderStoryboard(shot: VideoShot) {
    if (!shot.id) return;
    setRenderingSb(shot.id);
    setError(null);
    setNotice(`正在为镜头 ${shot.shot_number} 生成主分镜图...`);
    try {
      const result = await renderStoryboardFrame(shot.id, {
        provider: 'image2',
        style_preset: shot.style_preset || 'realistic_cinematic',
      });
      const updatedShot: VideoShot = {
        ...shot,
        status: result.shot_status,
        storyboard_asset_id: result.asset?.id,
        storyboard_locked: result.storyboard_locked ?? false,
      };
      onShotsChange(shots.map((s) => (s.id === shot.id ? updatedShot : s)));
      await loadStoryboards(shot.id);
      setNotice(`镜头 ${shot.shot_number} 的主分镜图已生成，请审核后锁定。`);
    } catch (err: any) {
      setError(err.message || '生成分镜图失败');
      setNotice(null);
    } finally {
      setRenderingSb(null);
    }
  }

  async function handleApprove(shot: VideoShot) {
    if (!shot.id) return;
    setApproving(shot.id);
    setError(null);
    try {
      const result = await approveShotStoryboard(shot.id);
      const updatedShot: VideoShot = {
        ...shot,
        storyboard_locked: result.storyboard_locked,
        storyboard_asset_id: result.storyboard_asset_id ?? shot.storyboard_asset_id,
      };
      onShotsChange(shots.map((s) => (s.id === shot.id ? updatedShot : s)));
      setNotice(`镜头 ${shot.shot_number} 的分镜图已锁定，现在可以生成视频。`);
      await loadStoryboards(shot.id);
    } catch (err: any) {
      setError(err.message || '锁定分镜图失败');
      setNotice(null);
    } finally {
      setApproving(null);
    }
  }

  async function handleReject(shot: VideoShot) {
    if (!shot.id) return;
    setApproving(shot.id);
    setError(null);
    try {
      const result = await rejectShotStoryboard(shot.id);
      const updatedShot: VideoShot = { ...shot, storyboard_locked: result.storyboard_locked, storyboard_asset_id: undefined };
      onShotsChange(shots.map((s) => (s.id === shot.id ? updatedShot : s)));
      setNotice(`镜头 ${shot.shot_number} 的分镜图已拒绝，可以重新生成。`);
    } catch (err: any) {
      setError(err.message || '拒绝分镜图失败');
      setNotice(null);
    } finally {
      setApproving(null);
    }
  }

  // ─── Inline Editing ───────────────────────────────────────

  function handleStartEdit(shot: VideoShot) {
    const shotId = shot.id ?? 0;
    setEditingShotId(shotId);
    setEditFormData({ ...shot });
    setError(null);
  }

  function handleCancelEdit() {
    setEditingShotId(null);
    setEditFormData({});
  }

  async function handleSaveEdit(shot: VideoShot) {
    if (!shot.id) return;
    setSavingShotId(shot.id);
    setError(null);
    try {
      const payload: Record<string, any> = {};
      const editableFields = [
        'title', 'shot_type', 'camera_angle', 'camera_movement',
        'composition', 'action_description', 'dialogue', 'duration_seconds',
      ] as const;
      for (const field of editableFields) {
        if (editFormData[field] !== undefined) {
          payload[field] = editFormData[field];
        }
      }
      const result = await updateVideoShot(shot.id, payload);
      onShotsChange(shots.map((s) => (s.id === shot.id ? result : s)));
      setEditingShotId(null);
      setEditFormData({});
      setNotice(`镜头 ${shot.shot_number} 已更新。`);
      toast.success('已保存');
    } catch (err: any) {
      setError(err.message || '更新镜头失败');
    } finally {
      setSavingShotId(null);
    }
  }

  function handleFieldChange(field: string, value: any) {
    setEditFormData((prev) => ({ ...prev, [field]: value }));
  }

  // ─── Reordering ──────────────────────────────────────────

  function handleMoveUp(index: number) {
    if (index <= 0) return;
    const next = shots.map((s) => ({ ...s }));
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    next.forEach((s, i) => { s.shot_number = i + 1; });
    onShotsChange(next);
    setHasOrderChanged(true);
  }

  function handleMoveDown(index: number) {
    if (index >= shots.length - 1) return;
    const next = shots.map((s) => ({ ...s }));
    [next[index], next[index + 1]] = [next[index + 1], next[index]];
    next.forEach((s, i) => { s.shot_number = i + 1; });
    onShotsChange(next);
    setHasOrderChanged(true);
  }

  async function handleSaveOrder() {
    if (!scene?.id) return;
    setError(null);
    try {
      const shotIds = shots.map((s) => s.id).filter((id): id is number => id !== undefined);
      const result = await reorderSceneShots(scene.id, { shot_ids: shotIds });
      onShotsChange(result.shots);
      setHasOrderChanged(false);
      setNotice('镜头顺序已保存。');
    } catch (err: any) {
      setError(err.message || '保存顺序失败');
    }
  }

  // ─── Add / Delete ────────────────────────────────────────

  async function handleAddShot() {
    if (!scene?.id) return;
    setError(null);
    const nextNumber = shots.length > 0 ? Math.max(...shots.map((s) => s.shot_number)) + 1 : 1;
    try {
      const result = await createSceneShot(scene.id, {
        shot_number: nextNumber,
        title: `新镜头${nextNumber}`,
        action_description: '新镜头',
      });
      onShotsChange([...shots, result]);
      setExpandedShot(result.id ?? result.shot_number);
      setNotice(`已添加镜头 ${nextNumber}。`);
    } catch (err: any) {
      setError(err.message || '添加镜头失败');
    }
  }

  async function handleDeleteShot(shot: VideoShot) {
    if (!shot.id) return;
    setDeletingShotId(shot.id);
    setError(null);
    try {
      await deleteShot(shot.id);
      onShotsChange(shots.filter((s) => s.id !== shot.id));
      if (expandedShot === shot.id) setExpandedShot(null);
      setNotice(`镜头 ${shot.shot_number} 已删除。`);
    } catch (err: any) {
      setError(err.message || '删除镜头失败');
    } finally {
      setDeletingShotId(null);
      setConfirmDeleteId(null);
    }
  }

  // ─── Rerender with prompt editing ─────────────────────────

  function handleOpenRerender(shot: VideoShot) {
    setRerenderShotId(shot.id ?? null);
    setRerenderPrompt(shot.storyboard_prompt || shot.video_prompt || '');
    const sbInfo = shot.id ? storyboardAssets[shot.id] : undefined;
    const masterAsset = sbInfo?.assets?.find((a) => a.is_master);
    setRerenderImageSrc(masterAsset?.file_path || '');
    setShowRerenderModal(true);
  }

  function handleOpenRerenderAsset(shot: VideoShot, asset: VideoAsset) {
    setRerenderShotId(shot.id ?? null);
    setRerenderPrompt(shot.storyboard_prompt || shot.video_prompt || '');
    setRerenderImageSrc(asset.file_path || '');
    setShowRerenderModal(true);
  }

  async function handleConfirmRerender(promptOverride?: string) {
    if (!rerenderShotId) return;
    const finalPrompt = promptOverride ?? rerenderPrompt;
    setRerenderingPrompt(true);
    setError(null);
    try {
      await updateVideoShot(rerenderShotId, { storyboard_prompt: finalPrompt });
      const result = await renderStoryboardFrame(rerenderShotId, {
        provider: 'image2',
        overwrite: true,
        style_preset: 'realistic_cinematic',
      });
      onShotsChange(
        shots.map((s) =>
          s.id === rerenderShotId
            ? { ...s, status: result.shot_status, storyboard_asset_id: result.asset?.id, storyboard_locked: result.storyboard_locked ?? false }
            : s,
        ),
      );
      await loadStoryboards(rerenderShotId);
      setNotice('分镜图已重新生成。');
      setShowRerenderModal(false);
      setRerenderShotId(null);
      setRerenderImageSrc('');
    } catch (err: any) {
      setError(err.message || '重绘分镜图失败');
    } finally {
      setRerenderingPrompt(false);
    }
  }

  // ─── Set Master Storyboard ────────────────────────────────

  async function handleSetMaster(shot: VideoShot, assetId: number) {
    if (!shot.id) return;
    setSettingMaster(shot.id);
    setError(null);
    try {
      await setMasterStoryboard(shot.id, assetId);
      await loadStoryboards(shot.id);
      setNotice(`镜头 ${shot.shot_number} 的主分镜图已更新。`);
    } catch (err: any) {
      setError(err.message || '设置主分镜图失败');
    } finally {
      setSettingMaster(null);
    }
  }

  // ─── Render helpers ──────────────────────────────────────

  function renderEditField(field: string, _label: string, type: 'text' | 'number' | 'textarea' = 'text') {
    const value = (editFormData as any)[field] ?? '';
    if (type === 'textarea') {
      return (
        <textarea
          value={value}
          onChange={(e) => handleFieldChange(field, e.target.value)}
          className="w-full rounded-lg border border-[#d7e3f4] bg-white px-2 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
          rows={2}
          onClick={(e) => e.stopPropagation()}
        />
      );
    }
    if (type === 'number') {
      return (
        <input
          type="number"
          value={value}
          onChange={(e) => handleFieldChange(field, e.target.value === '' ? null : Number(e.target.value))}
          className="w-20 rounded-lg border border-[#d7e3f4] bg-white px-2 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
          onClick={(e) => e.stopPropagation()}
        />
      );
    }
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => handleFieldChange(field, e.target.value)}
        className="w-full rounded-lg border border-[#d7e3f4] bg-white px-2 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      />
    );
  }

  if (!scene) {
    if (scenesLoading) {
      return (
        <div className="flex h-full items-center justify-center text-slate-400">
          <div className="text-center">
            <div className="mx-auto mb-3 h-6 w-6 animate-spin rounded-full border-2 border-[#d7e3f4] border-t-[#2563eb]" />
            <p className="text-sm">正在加载场次数据...</p>
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <p className="text-sm">请先在"影视剧本"里选择一个场次</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* ─── Header ─────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-slate-900">
            场次 {scene.scene_number}: {scene.title}
          </h3>
          <p className="mt-1 text-sm leading-6 text-slate-500">{scene.summary}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {shotLimit > 0 && (
            <span className="text-xs text-slate-400">本月配额 {shotLimit} 次</span>
          )}
          <button
            onClick={handleGenerateShots}
            disabled={generating}
            className="shrink-0 rounded-xl bg-[#2563eb] px-4 py-2 text-sm text-white disabled:opacity-60"
          >
            {generating ? '生成中...' : shots.length > 0 ? '重新生成镜头' : '生成镜头'}
          </button>
        </div>
      </div>

      {/* ─── Scene info bar ─────────────────────────────────── */}
      <div className="rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] p-4 text-sm text-slate-600">
        <div className="flex flex-wrap items-center gap-4">
          <span>地点：{scene.location || '未明确地点'}</span>
          <span>时间：{scene.time_of_day || '白天'}</span>
          <span>预计时长：{scene.estimated_duration_seconds || '?'}s</span>
          <span>提示词：{readyShotCount}/{shots.length}</span>
          <span>分镜图：{storyboardReadyCount}/{shots.length}</span>
        </div>
      </div>

      {/* ─── Notifications ──────────────────────────────────── */}
      {notice && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          {notice}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {shotsLoading && (
        <div className="flex items-center justify-center py-8 text-slate-400">
          <div className="text-center">
            <div className="mx-auto mb-2 h-5 w-5 animate-spin rounded-full border-2 border-[#d7e3f4] border-t-[#2563eb]" />
            <p className="text-xs">正在加载已保存的镜头数据...</p>
          </div>
        </div>
      )}

      {/* ─── Shot list ──────────────────────────────────────── */}
      {!shotsLoading && shots.length > 0 && (
        <div className="space-y-3">
          {shots.map((shot, index) => {
            const shotId = shot.id ?? shot.shot_number;
            const expanded = expandedShot === shotId;
            const isEditing = editingShotId === shot.id;
            const sbInfo = shot.id ? storyboardAssets[shot.id] : undefined;
            const hasSb = !!shot.storyboard_asset_id || (sbInfo?.assets.length ?? 0) > 0;
            const sbLocked = shot.storyboard_locked || sbInfo?.locked || false;
            const isDeleting = deletingShotId === shot.id;

            return (
              <div key={shot.id || shot.shot_number} className="rounded-xl border border-[#d7e3f4] bg-white">
                {/* ── Header row ───────────────────────────── */}

                <div
                  onClick={() => {
                    if (shot.id && !storyboardAssets[shot.id]) loadStoryboards(shot.id);
                    setExpandedShot(expanded ? null : shotId);
                  }}
                  className="flex cursor-pointer items-center justify-between gap-3 p-4"
                >
                  {/* Left: reorder + number + title */}
                  <div className="flex items-center gap-2 min-w-0">
                    {/* Reorder arrows */}
                    <div className="flex shrink-0 flex-col gap-0.5">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleMoveUp(index); }}
                        disabled={index === 0}
                        className="leading-none text-slate-400 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
                        title="上移"
                      >
                        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
                        </svg>
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleMoveDown(index); }}
                        disabled={index === shots.length - 1}
                        className="leading-none text-slate-400 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
                        title="下移"
                      >
                        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                    </div>

                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="whitespace-nowrap text-sm font-medium text-slate-900">
                          镜头 {shot.shot_number}
                        </span>
                        <span className="truncate text-sm text-slate-700">{shot.title}</span>
                        <span className="hidden sm:inline text-xs text-slate-400">
                          {shot.shot_type || 'medium'}
                        </span>
                        {sbLocked && (
                          <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                            已锁定
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">
                        {shot.camera_angle || 'eye_level'} · {shot.camera_movement || 'static'} · {shot.duration_seconds || '?'}s
                      </div>
                    </div>
                  </div>

                  {/* Right: action buttons */}
                  <div className="flex shrink-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => onShotSelect(shot)}
                      className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white"
                    >
                      设为当前
                    </button>

                    {isEditing ? (
                      <>
                        <button
                          onClick={() => handleSaveEdit(shot)}
                          disabled={savingShotId === shot.id}
                          className="rounded-lg bg-emerald-600 px-2 py-1 text-xs text-white disabled:opacity-60"
                        >
                          {savingShotId === shot.id ? '保存中...' : '保存'}
                        </button>
                        <button
                          onClick={handleCancelEdit}
                          className="rounded-lg border border-slate-300 px-2 py-1 text-xs text-slate-600"
                        >
                          取消
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => handleStartEdit(shot)}
                          className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white"
                        >
                          编辑
                        </button>
                        <button
                          onClick={() => {
                            if (confirmDeleteId === shot.id) {
                              handleDeleteShot(shot);
                            } else {
                              setConfirmDeleteId(shot.id ?? null);
                              setTimeout(() => setConfirmDeleteId((prev) => (prev === shot.id ? prev : null)), 3000);
                            }
                          }}
                          disabled={isDeleting}
                          className={`rounded-lg px-2 py-1 text-xs disabled:opacity-60 ${
                            confirmDeleteId === shot.id
                              ? 'bg-rose-600 text-white'
                              : 'border border-rose-200 text-rose-500 hover:border-rose-300'
                          }`}
                        >
                          {isDeleting ? '删除中...' : confirmDeleteId === shot.id ? '确认删除?' : '删除'}
                        </button>
                      </>
                    )}

                    {!isEditing && (
                      <button
                        onClick={() => handleGeneratePrompts(shot)}
                        disabled={generatingPrompts === shot.id}
                        className="rounded-lg bg-[#2563eb] px-2 py-1 text-xs text-white disabled:opacity-60"
                      >
                        {generatingPrompts === shot.id ? '生成中...' : shot.video_prompt ? '重生成' : '生提示词'}
                      </button>
                    )}
                  </div>
                </div>

                {/* ── Expanded / Edit or View ───────────────── */}
                {expanded && (
                  <div className="border-t border-[#d7e3f4] px-4 py-3 text-xs text-slate-600">
                    {isEditing ? (
                      /* ── Edit Mode ─────────────── */
                      <div className="space-y-2.5">
                        <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
                          <div>
                            <label className="mb-0.5 block font-medium text-slate-700">标题</label>
                            {renderEditField('title', '标题')}
                          </div>
                          <div>
                            <label className="mb-0.5 block font-medium text-slate-700">时长（秒）</label>
                            {renderEditField('duration_seconds', '时长', 'number')}
                          </div>
                          <div>
                            <label className="mb-0.5 block font-medium text-slate-700">镜头类型</label>
                            {renderEditField('shot_type', '镜头类型')}
                          </div>
                          <div>
                            <label className="mb-0.5 block font-medium text-slate-700">机位</label>
                            {renderEditField('camera_angle', '机位')}
                          </div>
                          <div>
                            <label className="mb-0.5 block font-medium text-slate-700">运镜</label>
                            {renderEditField('camera_movement', '运镜')}
                          </div>
                        </div>
                        <div>
                          <label className="mb-0.5 block font-medium text-slate-700">构图</label>
                          {renderEditField('composition', '构图', 'textarea')}
                        </div>
                        <div>
                          <label className="mb-0.5 block font-medium text-slate-700">动作描述</label>
                          {renderEditField('action_description', '动作描述', 'textarea')}
                        </div>
                        <div>
                          <label className="mb-0.5 block font-medium text-slate-700">对白</label>
                          {renderEditField('dialogue', '对白', 'textarea')}
                        </div>
                      </div>
                    ) : (
                      /* ── View Mode ─────────────── */
                      <div className="space-y-3">
                        {/* Storyboard assets */}
                        {sbInfo && sbInfo.assets.length > 0 && (
                          <div className="flex flex-wrap gap-2">
                            {sbInfo.assets.slice(0, 5).map((asset) => (
                              <div key={asset.id} className="group relative">
                                <div
                                  onClick={() => handleOpenRerenderAsset(shot, asset)}
                                  className={`relative h-24 w-24 overflow-hidden rounded-lg border bg-slate-100 cursor-pointer transition hover:ring-2 hover:ring-blue-400 ${
                                    asset.is_master ? 'border-2 border-blue-500' : 'border-slate-200'
                                  }`}
                                >
                                  <img
                                    src={asset.file_path}
                                    alt={asset.name}
                                    className="h-full w-full object-cover"
                                    onError={(e) => {
                                      (e.target as HTMLImageElement).style.display = 'none';
                                    }}
                                  />
                                  {asset.is_master && (
                                    <span className="absolute left-1 top-1 rounded bg-blue-500 px-1 py-0.5 text-[8px] text-white">
                                      主图
                                    </span>
                                  )}
                                </div>
                                {/* Version switching */}
                                {!asset.is_master && (
                                  <button
                                    onClick={() => handleSetMaster(shot, asset.id)}
                                    disabled={settingMaster === shot.id}
                                    className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/40 opacity-0 transition-opacity group-hover:opacity-100"
                                  >
                                    <span className="rounded bg-white px-1.5 py-0.5 text-[9px] font-medium text-slate-800">
                                      {settingMaster === shot.id ? '设置中...' : '设为主版本'}
                                    </span>
                                  </button>
                                )}
                              </div>
                            ))}
                            {sbInfo.assets.length > 5 && (
                              <div className="flex h-24 w-24 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-400">
                                +{sbInfo.assets.length - 5}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Field grid */}
                        <div className="grid grid-cols-2 gap-2">
                          <div><span className="font-medium">构图：</span>{shot.composition || '-'}</div>
                          <div><span className="font-medium">动作：</span>{shot.action_description || '-'}</div>
                          <div><span className="font-medium">对白：</span>{shot.dialogue || '-'}</div>
                          <div><span className="font-medium">音效：</span>{shot.sound_design || '-'}</div>
                        </div>

                        {/* Prompts */}
                        {shot.video_prompt && (
                          <div>
                            <span className="font-medium">视频提示词：</span>
                            <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-[#f8fbff] p-2 text-xs">{shot.video_prompt}</pre>
                          </div>
                        )}
                        {shot.storyboard_prompt && (
                          <div>
                            <span className="font-medium">关键帧提示词：</span>
                            <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-[#f8fbff] p-2 text-xs">{shot.storyboard_prompt}</pre>
                          </div>
                        )}

                        {/* Action buttons */}
                        <div className="flex flex-wrap items-center gap-2 border-t border-[#d7e3f4] pt-3">
                          <span className="text-slate-400">状态：{shotStatusLabel(shot.status)}</span>
                          <span className="text-slate-300">|</span>
                          <button
                            onClick={() => handleRenderStoryboard(shot)}
                            disabled={renderingSb === shot.id}
                            className="rounded-lg bg-[#7c3aed] px-2 py-1 text-xs text-white disabled:opacity-60"
                          >
                            {renderingSb === shot.id ? '生成中...' : hasSb ? '重新生成分镜图' : '生成分镜图'}
                          </button>
                          {hasSb && (
                            <button
                              onClick={() => handleOpenRerender(shot)}
                              className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white"
                            >
                              重绘
                            </button>
                          )}
                          {hasSb && !sbLocked && (
                            <>
                              <button
                                onClick={() => handleApprove(shot)}
                                disabled={approving === shot.id}
                                className="rounded-lg bg-emerald-600 px-2 py-1 text-xs text-white disabled:opacity-60"
                              >
                                {approving === shot.id ? '处理中...' : '锁定'}
                              </button>
                              <button
                                onClick={() => handleReject(shot)}
                                disabled={approving === shot.id}
                                className="rounded-lg border border-rose-300 px-2 py-1 text-xs text-rose-600 disabled:opacity-60"
                              >
                                拒绝
                              </button>
                            </>
                          )}
                          {sbLocked && (
                            <span className="rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-600">
                              分镜图已锁定
                            </span>
                          )}
                        </div>

                        {/* Version list for shots with multiple assets */}
                        {sbInfo && sbInfo.assets.length > 1 && (
                          <div className="border-t border-[#d7e3f4] pt-2 text-xs text-slate-500">
                            <span className="font-medium text-slate-600">分镜版本：</span>
                            共 {sbInfo.assets.length} 个版本
                            {sbInfo.assets.filter((a) => !a.is_master).length > 0 && ' · 鼠标悬停在非主图上可设置为主版本'}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* ── Add shot & Save order buttons ─────────────── */}
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={handleAddShot}
              className="rounded-lg border border-dashed border-[#d7e3f4] px-4 py-2 text-xs text-slate-500 hover:border-blue-300 hover:text-blue-600"
            >
              + 添加镜头
            </button>
            {hasOrderChanged && (
              <button
                onClick={handleSaveOrder}
                className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-xs text-white"
              >
                保存顺序
              </button>
            )}
          </div>
        </div>
      )}

      {shots.length === 0 && !generating && !shotsLoading && (
        <div className="py-12 text-center text-slate-400">
          <p className="text-sm">点击"生成镜头"将这个场次拆成可执行镜头。</p>
          <p className="mt-2 text-xs">生成完成后，建议先生成分镜图并锁定，再到右侧生成视频。</p>
        </div>
      )}

      {/* ─── Rerender Prompt Modal ─────────────────────────── */}
      {showRerenderModal && (
        <ShotFrameRegenerationModal
          imageSrc={rerenderImageSrc || ''}
          title={`重绘分镜图 — 镜头 ${rerenderShotId ? shots.find((s) => s.id === rerenderShotId)?.shot_number : ''}`}
          prompt={rerenderPrompt}
          busy={rerenderingPrompt}
          onClose={() => { setShowRerenderModal(false); setRerenderShotId(null); setRerenderImageSrc(''); }}
          onSubmit={async (payload) => {
            setRerenderPrompt(payload.prompt);
            await handleConfirmRerender(payload.prompt);
          }}
        />
      )}
    </div>
  );
})

function shotStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: '草稿',
    prompt_ready: '提示词已就绪',
    storyboard_ready: '分镜图已就绪',
    rendering: '渲染中',
    completed: '已完成',
    failed: '失败',
  };
  return labels[status] || status;
}
