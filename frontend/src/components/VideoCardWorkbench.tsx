import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { RotateCcw, Upload, Trash2, Wand2, X, Loader2, CheckSquare } from 'lucide-react';
import { ImageRedrawModal } from './shared/ImageRedrawModal';
import AssetReferenceSelector from './AssetReferenceSelector';
import type { VideoAsset } from '../api';

interface VideoCardWorkbenchProps {
  type: 'character' | 'storyboard' | 'video' | 'scene';
  shotId: number;
  assetId?: number;
  displayShotIndex?: number;
  resources: Array<{
    id: number;
    assetId?: number;
    url: string;
    prompt?: string;
    label?: string;
    characterName?: string;
    hasAsset?: boolean;
  }>;
  onRegenerate: (resourceId: number, aspectRatio?: '16:9' | '9:16') => Promise<void>;
  onUploadReplace: (resourceId: number, file: File) => Promise<void>;
  onDelete: (resourceId: number) => Promise<void>;
  onRedraw: (resourceId: number, prompt: string, mask?: string) => Promise<void>;
  onPromptSave?: (resourceId: number, prompt: string) => Promise<void>;
  onReanalyzePrompt?: (resourceId: number) => Promise<void>;
  onClose: () => void;
  storyboardRefAssets?: Array<{ id: number; file_path: string; name: string; prompt?: string | null }>;
  selectedRefAssetIds?: number[];
  onSelectedRefAssetsChange?: (ids: number[]) => void;
  /** 视频类型：无视频时显示的故事版参考图 URL */
  storyboardImageUrl?: string;
  /** 当前章节所有资产（用于选择引用资产弹窗） */
  chapterAssets?: VideoAsset[];
  /** 镜头故事版图片（来自 shot 的 storyboard_image_url） */
  shotStoryboards?: Array<{ id: number; file_path: string; name: string }>;
  videoAspectRatio?: '16:9' | '9:16';
  onVideoAspectRatioChange?: (value: '16:9' | '9:16') => void;
  recommendedSceneAssets?: string[];
  recommendedKeyProps?: string[];
  recommendedReferenceAssetIds?: number[];
  externalBusy?: string | null;
}

interface WorkbenchState {
  currentIndex: number;
  zoomLevel: 1 | 1.35 | 1.7;
  isRedrawModalOpen: boolean;
  editingPrompt: string;
  busy: string | null;
}

export default function VideoCardWorkbench({ type, shotId, assetId, displayShotIndex, resources, onRegenerate, onUploadReplace, onDelete, onRedraw, onPromptSave, onReanalyzePrompt, onClose, selectedRefAssetIds, onSelectedRefAssetsChange, chapterAssets, shotStoryboards, videoAspectRatio = '16:9', onVideoAspectRatioChange, recommendedReferenceAssetIds, externalBusy = null }: VideoCardWorkbenchProps) {
  const [state, setState] = useState<WorkbenchState>(() => {
    const initialIndex = Math.max(0, resources.findIndex(r => r.id === assetId));
    return {
      currentIndex: initialIndex,
      zoomLevel: 1,
      isRedrawModalOpen: false,
      editingPrompt: resources[initialIndex]?.prompt || '',
      busy: null,
    };
  });

  const [isRefSelectorOpen, setIsRefSelectorOpen] = useState(false);

  const { currentIndex } = state;
  const fileInputRef = useRef<HTMLInputElement>(null);

  const currentResource = resources[currentIndex];
  const previewUrl = currentResource?.url;
  const effectiveBusy = state.busy ?? externalBusy;

  // 选择角色/资源
  const handleSelectIndex = (idx: number) => {
    setState(s => ({
      ...s,
      currentIndex: idx,
      editingPrompt: resources[idx]?.prompt || '',
    }));
  };

  const handleRegenerate = async () => {
    if (!currentResource || effectiveBusy) return;
    setState(s => ({ ...s, busy: 'regenerate' }));
    try {
      await onRegenerate(currentResource.id, type === 'video' ? videoAspectRatio : undefined);
    } catch (err) {
      console.error(previewUrl ? '重新生成失败' : '生成失败', err);
    } finally {
      setState(s => ({ ...s, busy: null }));
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !currentResource || effectiveBusy) return;
    setState(s => ({ ...s, busy: 'upload' }));
    try {
      await onUploadReplace(currentResource.id, file);
    } catch (err) {
      console.error('上传替换失败', err);
    } finally {
      setState(s => ({ ...s, busy: null }));
    }
    e.target.value = '';
  };

  const handleDelete = async () => {
    const resourceId = currentResource?.id;
    if (resourceId == null || effectiveBusy) return;
    if (!confirm('确定要删除这个资源吗？')) return;
    setState(s => ({ ...s, busy: 'delete' }));
    try {
      await onDelete(resourceId);
    } catch (err) {
      console.error('删除失败', err);
      setState(s => ({ ...s, busy: null }));
      return;
    }
    setState(s => ({ ...s, busy: null }));
    if (resources.length === 1) {
      onClose();
    } else {
      handleNext();
    }
  };

  const handleReanalyze = async () => {
    const resourceId = currentResource?.id;
    if (resourceId == null || !onReanalyzePrompt || effectiveBusy) return;
    setState(s => ({ ...s, busy: 'reanalyze' }));
    try {
      await onReanalyzePrompt(resourceId);
    } catch (err) {
      console.error('重新分析提示词失败', err);
    } finally {
      setState(s => ({ ...s, busy: null }));
    }
  };

  // 导航函数
  const handlePrev = useCallback(() => {
    setState(s => ({
      ...s,
      currentIndex: s.currentIndex > 0 ? s.currentIndex - 1 : resources.length - 1,
      editingPrompt: resources[s.currentIndex > 0 ? s.currentIndex - 1 : resources.length - 1]?.prompt || '',
    }));
  }, [resources]);

  const handleNext = useCallback(() => {
    setState(s => ({
      ...s,
      currentIndex: s.currentIndex < resources.length - 1 ? s.currentIndex + 1 : 0,
      editingPrompt: resources[s.currentIndex < resources.length - 1 ? s.currentIndex + 1 : 0]?.prompt || '',
    }));
  }, [resources]);

  // 键盘快捷键处理（仅 video 类型支持键盘导航，modal 类型 ESC 关闭即可）
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (type === 'video') {
      switch (e.key) {
        case 'Escape':
          onClose();
          break;
        case 'ArrowLeft':
          handlePrev();
          break;
        case 'ArrowRight':
          handleNext();
          break;
        case '+':
        case '=':
          setState(s => ({ ...s, zoomLevel: s.zoomLevel < 1.7 ? (s.zoomLevel === 1 ? 1.35 : 1.7) : 1 }));
          break;
        case '-':
          setState(s => ({ ...s, zoomLevel: s.zoomLevel > 1 ? (s.zoomLevel === 1.7 ? 1.35 : 1) : 1 }));
          break;
        case 'r':
        case 'R':
          setState(s => ({ ...s, isRedrawModalOpen: true }));
          break;
      }
    } else {
      if (e.key === 'Escape') onClose();
    }
  }, [type, onClose, handlePrev, handleNext]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // 拼装缩放按钮
  const zoomButtons = [1, 1.35, 1.7].map(zoom => (
    <button
      key={zoom}
      type="button"
      onClick={() => setState(s => ({ ...s, zoomLevel: zoom as 1 | 1.35 | 1.7 }))}
      className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
        state.zoomLevel === zoom ? 'bg-white text-slate-900' : 'bg-white/10 text-white hover:bg-white/20'
      }`}
    >
      {Math.round(zoom * 100)}%
    </button>
  ));

  // ────────── 视频类型：居中弹窗布局（与故事版一致）──────────
  if (type === 'video') {
    const modal = (
      <div
        className="fixed inset-0 z-[68] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <div
          className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
          onClick={e => e.stopPropagation()}
        >
          {/* 弹窗头部 */}
          <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
            <div>
              <div className="text-lg font-semibold text-slate-900">视频工作台</div>
              <div className="mt-1 text-sm text-slate-500">
                镜头 {displayShotIndex ?? shotId} · 中间预览视频，右侧查看提示词与操作
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={onClose} className="ml-2 rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
                <X size={18} />
              </button>
            </div>
          </div>

          {/* 弹窗主体：两栏布局 */}
          <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
            {/* 左侧：预览区（深色背景） */}
            <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
              <div className="mb-4 flex items-center justify-between text-white/80">
                <div className="text-sm font-medium">视频预览</div>
                <div className="flex items-center gap-2">{zoomButtons}</div>
              </div>
              <div className="mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
                <div className="rounded-[24px] bg-[#0b1220] p-4 shadow-2xl">
                  {previewUrl ? (
                    <video
                      src={previewUrl}
                      controls
                      className="mx-auto h-auto max-h-[56vh] rounded-xl shadow-2xl"
                      style={{ transform: `scale(${state.zoomLevel})` }}
                    />
                  ) : (
                    <div className="flex min-h-[420px] min-w-[320px] items-center justify-center rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                      暂无内容
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 右侧：提示词 + 操作 */}
            <div className="flex flex-col gap-4 overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
              <div className="flex flex-1 min-h-0 flex-col rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">提示词</div>
                <textarea
                  value={state.editingPrompt}
                  onChange={e => setState(s => ({ ...s, editingPrompt: e.target.value }))}
                  className="mt-3 w-full flex-1 min-h-0 rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-3 text-sm leading-6 text-slate-900 outline-none resize-none focus:border-blue-400"
                  placeholder="输入提示词..."
                />
                {onPromptSave && (
                  <div className="mt-3 flex justify-end shrink-0">
                    <button
                      onClick={async () => {
                        if (!currentResource || effectiveBusy) return;
                        setState(s => ({ ...s, busy: 'savePrompt' }));
                        try {
                          await onPromptSave(currentResource.id, state.editingPrompt);
                        } catch (err) {
                          console.error('保存提示词失败', err);
                        } finally {
                          setState(s => ({ ...s, busy: null }));
                        }
                      }}
                      disabled={state.busy === 'savePrompt' || Boolean(externalBusy)}
                      className="flex items-center gap-1 rounded-2xl bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                    >
                      {(state.busy === 'savePrompt' || effectiveBusy === 'savePrompt') && <Loader2 size={12} className="animate-spin" />} {effectiveBusy === 'savePrompt' ? '保存中...' : '保存提示词'}
                    </button>
                  </div>
                )}
              </div>

              <div className="shrink-0 rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">操作</div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {type === 'video' && onVideoAspectRatioChange && (
                    <div className="flex items-center gap-2 rounded-xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-1.5 text-xs text-slate-700">
                      <span>视频比例</span>
                      <select
                        value={videoAspectRatio}
                        onChange={(e) => onVideoAspectRatioChange(e.target.value as '16:9' | '9:16')}
                        className="rounded-lg border border-[#d7e3f4] bg-white px-2 py-1 text-xs text-slate-700 outline-none"
                      >
                        <option value="16:9">16:9</option>
                        <option value="9:16">9:16</option>
                      </select>
                    </div>
                  )}
                  {chapterAssets && chapterAssets.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setIsRefSelectorOpen(true)}
                      className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      <CheckSquare size={12} />
                      选择引用资产
                      {(selectedRefAssetIds?.length ?? 0) > 0 && (
                        <span className="ml-1 rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-600">
                          {selectedRefAssetIds?.length}
                        </span>
                      )}
                    </button>
                  )}
                  <button onClick={handleRegenerate} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60">
                    {effectiveBusy === 'regenerate' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} {effectiveBusy === 'regenerate' ? '生成中...' : (previewUrl ? '重新生成' : '生成')}
                  </button>
                  <button onClick={handleUploadClick} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
                    {effectiveBusy === 'upload' ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />} {effectiveBusy === 'upload' ? '上传中...' : '上传替换'}
                  </button>
                  <button onClick={handleDelete} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-60">
                    {effectiveBusy === 'delete' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} {effectiveBusy === 'delete' ? '删除中...' : '删除'}
                  </button>
                  {onReanalyzePrompt && (
                    <button onClick={handleReanalyze} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-amber-200 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-60">
                       {effectiveBusy === 'reanalyze' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} {effectiveBusy === 'reanalyze' ? '分析中...' : (currentResource?.prompt ? '重新分析提示词' : '分析提示词')}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* 重绘弹窗 */}
          {state.isRedrawModalOpen && (
            <ImageRedrawModal
              title="重绘视频"
              imageSrc={previewUrl || ''}
              prompt={state.editingPrompt}
              busy={false}
              onClose={() => setState(s => ({ ...s, isRedrawModalOpen: false }))}
              onSubmit={async (payload) => {
                const resourceId = currentResource?.id;
                if (resourceId == null) return;
                setState(s => ({ ...s, isRedrawModalOpen: false }));
                try {
                  await onRedraw(resourceId, payload.prompt, payload.mask);
                } catch (err) {
                  console.error('重绘失败', err);
                }
              }}
            />
          )}

          {/* 选择引用资产弹窗 */}
          {isRefSelectorOpen && chapterAssets && (
            <AssetReferenceSelector
              availableAssets={chapterAssets}
              selectedIds={selectedRefAssetIds || []}
              shotStoryboards={shotStoryboards}
              recommendedIds={recommendedReferenceAssetIds}
              onConfirm={(ids) => {
                onSelectedRefAssetsChange?.(ids);
                setIsRefSelectorOpen(false);
              }}
              onClose={() => setIsRefSelectorOpen(false)}
            />
          )}
          <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileChange} className="hidden" />
        </div>
      </div>
    );

    return createPortal(modal, document.body);
  }

  // ────────── 角色/故事版/场景类型：居中弹窗布局（漫画工作台样式）──────────
  const isCharacter = type === 'character';
  const isScene = type === 'scene';
  const previewClass = state.zoomLevel === 1
    ? 'max-w-[92%] max-h-none'
    : state.zoomLevel === 1.35
      ? 'max-w-none w-[780px]'
      : 'max-w-none w-[940px]';

  const modal = (
    <div
      className="fixed inset-0 z-[68] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={e => e.stopPropagation()}
      >
        {/* 弹窗头部 */}
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">
              {isCharacter ? '角色资产工作台' : isScene ? '场景 & 道具工作台' : '故事版工作台'}
            </div>
            <div className="mt-1 text-sm text-slate-500">
              镜头 {displayShotIndex ?? shotId}
              {isCharacter ? ' · 左侧选择角色，中间预览，右侧查看提示词与操作' : isScene ? ' · 左侧选择场景/道具，中间预览，右侧查看提示词与操作' : ' · 中间预览故事版图片，右侧查看提示词与操作'}
            </div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
            <X size={18} />
          </button>
        </div>

        {/* 弹窗主体 */}
        {(isCharacter || isScene) ? (
          /* ── 角色/场景：左中右三栏 ── */
          <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[1fr_6fr_3fr]">
            {/* 左侧：资产列表 */}
            <div className="overflow-auto border-r border-[#e5edf8] bg-white p-4">
              <div className="mb-3 text-xs font-medium text-slate-500">{isScene ? '场景 & 道具资产' : '角色资产'}</div>
              {resources.length === 0 ? (
                <div className="text-xs text-slate-400">{isScene ? '暂无场景/道具资产' : '暂无角色资产'}</div>
              ) : (
                <div className="space-y-2">
                  {resources.map((res, idx) => (
                    <button
                      key={res.id}
                      type="button"
                      onClick={() => handleSelectIndex(idx)}
                      className={`w-full rounded-xl border p-3 text-left transition ${
                        idx === currentIndex
                          ? 'border-blue-300 bg-blue-50'
                          : 'border-[#e5edf8] bg-[#f8fbff] hover:border-blue-200'
                      }`}
                    >
                       <div className="text-xs font-medium text-slate-800 truncate">{res.label || res.prompt || `资产 #${res.id}`}</div>
                       {res.url ? (
                         <img
                           src={res.url}
                           alt=""
                           className="mt-2 h-16 w-full rounded-lg object-cover"
                         />
                       ) : (
                         <div className="mt-2 flex h-16 w-full items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-[11px] text-slate-400">
                           {isScene ? '暂无场景/道具参考图' : '暂无角色参考图'}
                         </div>
                       )}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* 中间：预览区 */}
            <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
              <div className="mb-4 flex items-center justify-between text-white/80">
                <div className="text-sm font-medium">预览</div>
                <div className="flex items-center gap-2">{zoomButtons}</div>
              </div>
              <div className="mx-auto flex min-h-[55vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
                <div className="rounded-[24px] bg-[#0b1220] p-4 shadow-2xl">
                  {previewUrl ? (
                    <img
                      src={previewUrl}
                      alt="预览"
                      className={`mx-auto h-auto object-contain rounded-xl shadow-2xl ${previewClass}`}
                    />
                  ) : (
                    <div className="flex min-h-[320px] min-w-[280px] items-center justify-center rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                      <Loader2 size={24} className="animate-spin" />
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 右侧：提示词 + 操作 */}
            <div className="flex flex-col gap-4 overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
              <div className="flex flex-1 min-h-0 flex-col rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">提示词</div>
                <textarea
                  value={state.editingPrompt}
                  onChange={e => setState(s => ({ ...s, editingPrompt: e.target.value }))}
                  className="mt-3 w-full flex-1 min-h-0 rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-3 text-sm leading-6 text-slate-900 outline-none resize-none focus:border-blue-400"
                  placeholder="输入提示词..."
                />
                {onPromptSave && (
                  <div className="mt-3 flex justify-end shrink-0">
                    <button
                      onClick={async () => {
                        if (!currentResource || effectiveBusy) return;
                        setState(s => ({ ...s, busy: 'savePrompt' }));
                        try {
                          await onPromptSave(currentResource.id, state.editingPrompt);
                        } catch (err) {
                          console.error('保存提示词失败', err);
                        } finally {
                          setState(s => ({ ...s, busy: null }));
                        }
                      }}
                      disabled={state.busy === 'savePrompt' || Boolean(externalBusy)}
                      className="flex items-center gap-1 rounded-2xl bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                    >
                      {state.busy === 'savePrompt' && <Loader2 size={12} className="animate-spin" />} 保存提示词
                    </button>
                  </div>
                )}
              </div>

              <div className="shrink-0 rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">操作</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button onClick={handleRegenerate} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60">
                    {effectiveBusy === 'regenerate' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} {effectiveBusy === 'regenerate' ? '生成中...' : (previewUrl ? '重新生成' : '生成')}
                  </button>
                  <button onClick={handleUploadClick} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
                    {effectiveBusy === 'upload' ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />} {effectiveBusy === 'upload' ? '上传中...' : '上传替换'}
                  </button>
                  <button onClick={handleDelete} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-60">
                    {effectiveBusy === 'delete' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} {effectiveBusy === 'delete' ? '删除中...' : '删除'}
                  </button>
                  <button onClick={() => setState(s => ({ ...s, isRedrawModalOpen: true }))} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
                    {effectiveBusy === 'redraw' ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />} {effectiveBusy === 'redraw' ? '重绘中...' : '重绘'}
                  </button>
                  {onReanalyzePrompt && (
                    <button onClick={handleReanalyze} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-amber-200 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-60">
                       {effectiveBusy === 'reanalyze' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} {effectiveBusy === 'reanalyze' ? '分析中...' : (currentResource?.prompt ? (isCharacter ? '重新分析当前角色提示词' : '重新分析提示词') : '分析提示词')}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
          ) : (
          /* ── 故事版：两栏布局（左预览右面板，如 RefPreviewModal） ── */
          <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
            {/* 左侧：预览区（深色背景） */}
            <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
              <div className="mb-4 flex items-center justify-between text-white/80">
                <div className="text-sm font-medium">故事版图片</div>
                <div className="flex items-center gap-2">{zoomButtons}</div>
              </div>
              <div className="mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
                <div className="rounded-[24px] bg-[#0b1220] p-4 shadow-2xl">
                  {previewUrl ? (
                    <img
                      src={previewUrl}
                      alt="故事版预览"
                      className={`mx-auto h-auto object-contain rounded-xl shadow-2xl ${previewClass}`}
                    />
                  ) : (
                    <div className="flex min-h-[420px] min-w-[320px] items-center justify-center rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                      <Loader2 size={24} className="animate-spin" />
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 右侧：提示词 + 参考图 + 操作 */}
            <div className="flex flex-col gap-4 overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
              <div className="flex flex-1 min-h-0 flex-col rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">提示词</div>
                <textarea
                  value={state.editingPrompt}
                  onChange={e => setState(s => ({ ...s, editingPrompt: e.target.value }))}
                  className="mt-3 w-full flex-1 min-h-0 rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-3 text-sm leading-6 text-slate-900 outline-none resize-none focus:border-blue-400"
                  placeholder="输入提示词..."
                />
                {onPromptSave && (
                  <div className="mt-3 flex justify-end shrink-0">
                    <button
                      onClick={async () => {
                        if (!currentResource || effectiveBusy) return;
                        setState(s => ({ ...s, busy: 'savePrompt' }));
                        try {
                          await onPromptSave(currentResource.id, state.editingPrompt);
                        } catch (err) {
                          console.error('保存提示词失败', err);
                        } finally {
                          setState(s => ({ ...s, busy: null }));
                        }
                      }}
                      disabled={state.busy === 'savePrompt' || Boolean(externalBusy)}
                      className="flex items-center gap-1 rounded-2xl bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                    >
                      {(state.busy === 'savePrompt' || effectiveBusy === 'savePrompt') && <Loader2 size={12} className="animate-spin" />} {effectiveBusy === 'savePrompt' ? '保存中...' : '保存提示词'}
                    </button>
                  </div>
                )}
              </div>

              <div className="shrink-0 rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">操作</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {chapterAssets && chapterAssets.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setIsRefSelectorOpen(true)}
                      className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      <CheckSquare size={12} />
                      选择引用资产
                      {(selectedRefAssetIds?.length ?? 0) > 0 && (
                        <span className="ml-1 rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-600">
                          {selectedRefAssetIds?.length}
                        </span>
                      )}
                    </button>
                  )}
                  <button onClick={handleRegenerate} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60">
                    {effectiveBusy === 'regenerate' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} {effectiveBusy === 'regenerate' ? '生成中...' : (previewUrl ? '重新生成' : '生成')}
                  </button>
                  <button onClick={handleUploadClick} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
                    {effectiveBusy === 'upload' ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />} {effectiveBusy === 'upload' ? '上传中...' : '上传替换'}
                  </button>
                  <button onClick={handleDelete} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-60">
                    {effectiveBusy === 'delete' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} {effectiveBusy === 'delete' ? '删除中...' : '删除'}
                  </button>
                  <button onClick={() => setState(s => ({ ...s, isRedrawModalOpen: true }))} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
                    {effectiveBusy === 'redraw' ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />} {effectiveBusy === 'redraw' ? '重绘中...' : '重绘'}
                  </button>
                  {onReanalyzePrompt && (
                    <button onClick={handleReanalyze} disabled={Boolean(effectiveBusy)} className="flex items-center gap-1 rounded-xl border border-amber-200 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-60">
                       {effectiveBusy === 'reanalyze' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} {effectiveBusy === 'reanalyze' ? '分析中...' : (currentResource?.prompt ? '重新分析提示词' : '分析提示词')}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 重绘弹窗（角色和故事版共用） */}
        {state.isRedrawModalOpen && (
          <ImageRedrawModal
            title={isCharacter ? '重绘角色资产' : '重绘故事版'}
            imageSrc={previewUrl || ''}
            prompt={state.editingPrompt}
            busy={false}
            onClose={() => setState(s => ({ ...s, isRedrawModalOpen: false }))}
            onSubmit={async (payload) => {
              const resourceId = currentResource?.id;
              if (resourceId == null) return;
              setState(s => ({ ...s, isRedrawModalOpen: false }));
              try {
                await onRedraw(resourceId, payload.prompt, payload.mask);
              } catch (err) {
                console.error('重绘失败', err);
              }
            }}
          />
        )}

        {/* 选择引用资产弹窗 */}
        {isRefSelectorOpen && chapterAssets && (
          <AssetReferenceSelector
            availableAssets={chapterAssets}
            selectedIds={selectedRefAssetIds || []}
            shotStoryboards={shotStoryboards}
            onConfirm={(ids) => {
              onSelectedRefAssetsChange?.(ids);
              setIsRefSelectorOpen(false);
            }}
            onClose={() => setIsRefSelectorOpen(false)}
          />
        )}

        {/* 隐藏的文件上传 input */}
        <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileChange} className="hidden" />
      </div>
    </div>
  );
  return createPortal(modal, document.body);
}
