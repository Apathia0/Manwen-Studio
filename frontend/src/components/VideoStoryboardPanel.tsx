import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, Film, CheckSquare, Square, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Sparkles, X, RefreshCw, Play, Check } from 'lucide-react';
import type { VideoShot, VideoAsset, ShotFramesResponse } from '../api';
import {
  deleteVideoAsset,
  getShotFrames,
  regenerateShotFrame,
  toPublicVideoAssetUrl,
  type ImageRedrawMode,
  type ShotAssetPromptDraft,
} from '../api';
import { ImageRedrawModal } from './shared/ImageRedrawModal';
import ImageZoomView from './shared/ImageZoomView';
import MediaImage from './shared/MediaImage';
import AssetReferenceSelector from './AssetReferenceSelector';
import { toast } from '../lib/toast';
import { readResponseError } from '../lib/errors';

// ── 类型定义 ──────────────────────────────────────────────

/** 增强的分镜数据，包含前端运行时状态 */
export interface EnrichedShot extends VideoShot {
  /** AI 分析出的资产提示词 (undefined=未分析) */
  promptDraft?: ShotAssetPromptDraft;
  /** 首尾帧数据 (undefined=未生成) */
  frames?: ShotFramesResponse;
  /** 前端操作状态 */
  _analyzing?: boolean;
  _generatingFrame?: boolean;
  _generatingVideo?: boolean;
  _generatingCharacterAsset?: string | null;  // 正在生成的角色名
  _generatingStoryboard?: boolean;
  _deletingAssetId?: number | null;
  _generatedClip?: { id: number; video_path: string; thumbnail_path?: string; duration_seconds?: number } | null;
}

interface VideoStoryboardPanelProps {
  shots: EnrichedShot[];
  shotsLoading: boolean;
  generatingStoryboard: boolean;
  checkedShotIds: Set<number>;
  page: number;
  perPage: number;
  totalShots: number;
  entitlements?: Record<string, any> | null;
  /** 本章节可用资产（用于 AssetReferenceSelector） */
  chapterAssets: VideoAsset[];
  onCheckToggle: (shotId: number) => void;
  onCheckAll: (checked: boolean) => void;
  onPageChange: (page: number) => void;
  onGenerateStoryboard: () => void;
  /** 批量分析提示词（仅勾选） */
  onBatchAnalyzePrompts: (shotIds: number[]) => Promise<void>;
  /** 批量生成首尾帧（仅勾选） */
  onBatchGenerateFrames: (shotIds: number[]) => Promise<void>;
  /** 单镜操作 */
  onShotsChange: (shots: EnrichedShot[]) => void;
  /** 生成视频 */
  onGenerateVideo: (shotId: number, referenceAssetIds: number[]) => Promise<void>;
  /** 单镜分析提示词 */
  onAnalyzeSingleShot: (shotId: number) => Promise<void>;
  /** 单镜生成角色资产 */
  onGenerateCharacterAsset: (shotId: number, characterName: string, prompt: string) => Promise<void>;
  /** 单镜生成场景参考图 */
  onGenerateSceneAsset?: (shotId: number, prompt: string) => Promise<void>;
  /** 单镜生成道具参考图 */
  onGeneratePropAsset?: (shotId: number, propName: string, prompt: string) => Promise<void>;
  /** 单镜生成分镜图 */
  onGenerateShotStoryboard: (shotId: number, referenceAssetIds?: number[]) => Promise<void>;
  /** 资产变更后通知父级刷新 */
  onAssetsChanged?: () => Promise<void>;
  stylePresets: Array<{id: number; name: string; category: string}>;
  selectedStyle: string;
  onStyleChange: (style: string) => void;
}

/** 获取资产文件的展示 URL */
function toAssetUrl(filePath?: string | null): string {
  return toPublicVideoAssetUrl(filePath) || '';
}

function paginate<T>(items: T[], page: number, perPage: number): T[] {
  const start = (page - 1) * perPage;
  return items.slice(start, start + perPage);
}

function normalizeCharName(raw: string): string {
  let n = raw.trim();
  for (const prefix of ['Character - ', 'Character-', '角色 - ', '角色-']) {
    if (n.startsWith(prefix)) n = n.slice(prefix.length);
  }
  return n.trim();
}

function matchCharName(assetName: string, promptName: string): boolean {
  return normalizeCharName(assetName) === normalizeCharName(promptName);
}

// ── 资产缩略卡片子组件 ────────────────────────────────────

// ── 资产分类卡片 (3列布局) ─────────────────────────────────

interface AssetPlaceholder {
  key: string;
  label: string;
  prompt: string;
  hasAsset: boolean;
  isGenerating: boolean;
  onGenerate?: (editedPrompt: string) => Promise<void>;
}

function AssetCard3({
  title,
  assets,
  placeholders,
  onViewAsset: _onViewAsset,
  onRedrawAsset: _onRedrawAsset,
  onDeleteAsset: _onDeleteAsset,
  onReplaceAsset: _onReplaceAsset,
  onOpenWorkbench,
  _refAssets,
  _refIds,
  _onRefChange,
  _shotId,
  /** 允许在缩略图上直接删除资产 */
  onDirectDeleteAsset,
  /** 删除确认中的资产 ID */
  deletingAssetId,
}: {
  title: string;
  assets: VideoAsset[];
  placeholders: AssetPlaceholder[];
  onViewAsset: (asset: VideoAsset) => void;
  onRedrawAsset: (asset: VideoAsset) => void;
  onDeleteAsset: (assetId: number) => void;
  onReplaceAsset: (assetId: number) => void;
  onOpenWorkbench?: (items: WorkbenchItem[], title: string, refAssets?: VideoAsset[], refIds?: number[], onRefChange?: (ids: number[]) => void, shotId?: number) => void;
  _refAssets?: VideoAsset[];
  _refIds?: number[];
  _onRefChange?: (ids: number[]) => void;
  _shotId?: number;
  onDirectDeleteAsset?: (assetId: number) => void;
  deletingAssetId?: number | null;
}) {
  const refAssets = _refAssets;
  const refIds = _refIds;
  const onRefChange = _onRefChange;
  const hasContent = assets.length > 0 || placeholders.length > 0;
  if (!hasContent) return null;

  const totalItems = assets.length + placeholders.filter(p => !p.hasAsset).length;

  const handleOpenWorkbench = () => {
    if (!onOpenWorkbench) return;
    // 从 placeholders 提取最新分析的角色提示词（原名匹配）
    const latestStoryboardPrompt = placeholders.find(p => p.key === 'storyboard')?.prompt || '';
    const findCharPrompt = (assetName: string): string => {
      const an = normalizeCharName(assetName);
      for (const p of placeholders) {
        if (p.key !== 'storyboard' && normalizeCharName(p.label) === an && p.prompt) {
          return p.prompt;
        }
      }
      return '';
    };

    const items: WorkbenchItem[] = [
      ...assets.map(a => ({
        key: String(a.id),
        label: a.name,
        imageSrc: toAssetUrl(a.file_path),
        // 优先使用最新 promptDraft 而非资产创建时的旧 prompt
        prompt: a.name?.includes('Storyboard') ? (latestStoryboardPrompt || a.prompt || '')
             : (findCharPrompt(a.name) || a.prompt || ''),
        isAsset: true,
        isGenerating: false,
      })),
      ...placeholders.filter(p => !p.hasAsset).map(p => ({
        key: p.key,
        label: p.label,
        prompt: p.prompt,
        isAsset: false,
        isGenerating: p.isGenerating,
        onGenerate: p.onGenerate,
      })),
    ];
    if (items.length > 0) onOpenWorkbench(items, title, refAssets, refIds, onRefChange, _shotId);
  };

  return (
    <div
      onClick={handleOpenWorkbench}
      className="rounded-xl border border-[#e5edf8] bg-white overflow-hidden cursor-pointer transition-all hover:shadow-md hover:border-blue-200"
    >
      <div className="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-[#e5edf8]">
        <span className="text-xs font-semibold text-slate-700">{title}</span>
        <span className="text-[10px] text-slate-400">{totalItems} 个</span>
      </div>
      <div className="p-2">
        <div className="flex flex-wrap gap-1.5">
          {assets.map(a => (
            <div
              key={a.id}
              className="relative group w-10 h-10 rounded-lg overflow-hidden border border-slate-200 bg-slate-100 shrink-0"
              title={a.name}
            >
              <MediaImage src={toAssetUrl(a.file_path)} alt={a.name} className="w-full h-full object-cover" />
              {a.is_master && <span className="absolute top-0 left-0 px-0.5 rounded-br bg-blue-500 text-[6px] text-white">主</span>}
              {onDirectDeleteAsset && (
                <button
                  onClick={(e) => { e.stopPropagation(); onDirectDeleteAsset(a.id); }}
                  disabled={deletingAssetId === a.id}
                  className="absolute top-0 right-0 w-4 h-4 flex items-center justify-center bg-red-500/80 hover:bg-red-600 text-white rounded-bl-md opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  {deletingAssetId === a.id ? (
                    <Loader2 size={8} className="animate-spin" />
                  ) : (
                    <X size={8} />
                  )}
                </button>
              )}
            </div>
          ))}
          {placeholders.filter(p => !p.hasAsset).map(p => (
            <div
              key={p.key}
              className={`w-10 h-10 rounded-lg border border-dashed flex items-center justify-center shrink-0 ${
                p.onGenerate ? 'border-violet-300 bg-violet-50' : 'border-[#d7e3f4] bg-slate-50'
              }`}
              title={p.label}
            >
              {p.isGenerating ? (
                <Loader2 size={12} className="animate-spin text-violet-500" />
              ) : p.onGenerate ? (
                <Sparkles size={12} className="text-violet-400" />
              ) : (
                <span className="text-[8px] text-slate-400">待</span>
              )}
            </div>
          ))}
        </div>
        {assets.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {assets.map(a => (
              <span key={a.id} className="text-[9px] text-slate-500 truncate max-w-[60px]">{a.name}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 多资源列表工作台 (左侧列表 + 右侧操作) ────────────────

interface WorkbenchItem {
  key: string;
  label: string;
  imageSrc?: string;
  prompt: string;
  isAsset: boolean;
  isGenerating: boolean;
  onGenerate?: (editedPrompt: string) => Promise<void>;
}

function MultiAssetWorkbench({
  title,
  items,
  onClose,
  onRedraw: _onRedraw,
  onDelete,
  onReplace,
  busy,
  generatingKey,
  refAssets,
  refSelectedIds,
  onRefSelect,
  onReanalyze,
  onRegenerate,
}: {
  title: string;
  items: WorkbenchItem[];
  onClose: () => void;
  onRedraw?: (item: WorkbenchItem) => void;
  onDelete?: (item: WorkbenchItem) => void;
  onReplace?: (item: WorkbenchItem) => void;
  busy: boolean;
  generatingKey?: string | null;
  refAssets?: VideoAsset[];
  refSelectedIds?: number[];
  onRefSelect?: (ids: number[]) => void;
  onReanalyze?: () => void;
  onRegenerate?: (prompt: string, mode: string) => void;
}) {
  const [refSelectorOpen, setRefSelectorOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState(items[0]?.key || '');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'full' | 'partial'>('full');
  const selected = items.find(i => i.key === selectedKey) || items[0];

  useEffect(() => {
    if (selected) setPrompt(selected.prompt);
  }, [selectedKey, selected?.prompt]);

  const isGenerating = generatingKey === selectedKey;

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">{title}</div>
            <div className="mt-1 text-sm text-slate-500">左侧选择资源，中间查看预览，右侧编辑操作</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 hover:bg-slate-200"><X size={18} /></button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div className="w-[180px] shrink-0 overflow-y-auto border-r border-[#e5edf8] bg-slate-50 py-2">
            {items.map(item => {
              const itemGenerating = generatingKey === item.key;
              return (
                <button
                  key={item.key}
                  onClick={() => setSelectedKey(item.key)}
                  className={`w-full text-left px-3 py-2.5 text-xs transition border-r-2 flex items-center gap-2 ${
                    selectedKey === item.key
                      ? 'bg-white border-blue-500 text-slate-900 font-medium'
                      : 'border-transparent text-slate-600 hover:bg-white/50'
                  }`}
                >
                  {item.isAsset && item.imageSrc ? (
                    <MediaImage src={item.imageSrc} alt="" className="w-7 h-7 rounded object-cover shrink-0" />
                  ) : (
                    <Sparkles size={14} className="text-violet-400 shrink-0" />
                  )}
                  <span className="truncate">{item.label}</span>
                  {itemGenerating && <Loader2 size={10} className="animate-spin text-violet-500 shrink-0 ml-auto" />}
                </button>
              );
            })}
          </div>

          <div className="flex-1 overflow-hidden bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-4 flex items-center justify-center">
            {isGenerating ? (
              <div className="text-white/60 text-center">
                <Loader2 size={48} className="animate-spin text-violet-400 mx-auto mb-3" />
                <div className="text-sm font-medium">正在生成中...</div>
                <div className="text-xs mt-1 opacity-60">{selected?.label}</div>
                <div className="text-xs mt-2 opacity-40">请稍候，生成完成后将自动更新</div>
              </div>
            ) : selected?.isAsset && selected?.imageSrc ? (
              <ImageZoomView
                src={selected.imageSrc}
                alt={selected.label}
                className="h-full w-full rounded-2xl"
              />
            ) : (
              <div className="text-white/60 text-center">
                <Sparkles size={32} className="mx-auto mb-2 opacity-40" />
                <div className="text-sm">待生成</div>
                <div className="text-xs mt-1 opacity-60">{selected?.label}</div>
              </div>
            )}
          </div>

          <div className="w-[380px] shrink-0 overflow-y-auto border-l border-[#e5edf8] bg-[#f8fbff] p-5">
            {selected?.isAsset && selected?.imageSrc ? (
              <div className="space-y-5">
                {onReanalyze && (
                  <button
                    disabled={busy}
                    onClick={() => onReanalyze()}
                    className="w-full rounded-xl border border-[#d7e3f4] bg-white px-3 py-2 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {busy ? '分析中...' : <><RefreshCw size={12} className="inline-block" /> 重新分析提示词</>}
                  </button>
                )}
                {/* 参考资产区（已有图时也可重新选择并重新生成） */}
                <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-700">引用资产</span>
                    <span className="text-[10px] text-slate-400">{(refSelectedIds || []).length} 个已选</span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); setRefSelectorOpen(true); }}
                    className="w-full rounded-xl border border-dashed border-[#d7e3f4] px-3 py-2 text-xs text-slate-500 hover:border-violet-300 hover:text-violet-600 transition"
                  >
                    {(refSelectedIds || []).length > 0
                      ? `已选 ${refSelectedIds!.length} 个参考资产，点击修改后重新生成`
                      : '点击选择角色参考图后重新生成'}
                  </button>
                  {refSelectorOpen && refAssets && refAssets.length > 0 && (
                    <AssetReferenceSelector
                      availableAssets={refAssets}
                      selectedIds={refSelectedIds || []}
                      onConfirm={(ids) => { onRefSelect?.(ids); setRefSelectorOpen(false); }}
                      onClose={() => setRefSelectorOpen(false)}
                    />
                  )}
                </div>
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">重绘方式</div>
                  <div className="flex gap-2">
                    <button onClick={() => setMode('full')} className={`rounded-2xl px-3 py-2 text-sm transition ${mode === 'full' ? 'bg-[#1d4ed8] text-white' : 'bg-white text-slate-700 border border-[#d7e3f4]'}`}>整图重绘</button>
                    <button onClick={() => setMode('partial')} className={`rounded-2xl px-3 py-2 text-sm transition ${mode === 'partial' ? 'bg-[#1d4ed8] text-white' : 'bg-white text-slate-700 border border-[#d7e3f4]'}`}>局部重绘</button>
                  </div>
                </div>
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">修改提示</div>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={12}
                    className="w-full rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
                    placeholder="描述你想调整的效果…"
                  />
                </div>
                <div className="flex gap-3">
                  <button
                    disabled={busy || !prompt.trim()}
                    onClick={() => onRegenerate?.(prompt.trim(), mode)}
                    className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                  >
                    {busy ? '处理中...' : '开始重绘'}
                  </button>
                  {onReplace && (
                    <button
                      disabled={busy}
                      onClick={() => onReplace(selected)}
                      className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-40"
                    >
                      上传替换
                    </button>
                  )}
                  {onDelete && (
                    <button
                      disabled={busy}
                      onClick={() => onDelete(selected)}
                      className="rounded-2xl border border-rose-200 bg-white px-4 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-40"
                    >
                      删除
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-5">
                <div className="flex items-center justify-between rounded-xl border border-[#d7e3f4] bg-white px-3 py-2">
                  <span className="text-xs text-slate-500">提示词不理想？</span>
                  <button
                    disabled={busy}
                    onClick={() => onReanalyze?.()}
                    className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {busy ? '分析中...' : <><RefreshCw size={12} className="inline-block" /> 重新分析提示词</>}
                  </button>
                </div>
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">提示词编辑</div>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={14}
                    className="w-full rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
                    placeholder="输入或修改生成提示词…"
                  />
                </div>
                {/* 参考资产选择 */}
                <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-700">参考资产</span>
                    <span className="text-[10px] text-slate-400">{(refSelectedIds || []).length} 个已选</span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); setRefSelectorOpen(true); }}
                    className="w-full rounded-xl border border-dashed border-[#d7e3f4] px-3 py-2 text-xs text-slate-500 hover:border-violet-300 hover:text-violet-600 transition"
                  >
                    {(refSelectedIds || []).length > 0
                      ? `已选 ${refSelectedIds!.length} 个参考资产，点击修改`
                      : (refAssets && refAssets.length > 0
                        ? '点击选择角色参考图作为视觉引用'
                        : '暂无可用参考资产，请先生成角色图')}
                  </button>
                  {refSelectorOpen && refAssets && refAssets.length > 0 && (
                    <AssetReferenceSelector
                      availableAssets={refAssets}
                      selectedIds={refSelectedIds || []}
                      onConfirm={(ids) => { onRefSelect?.(ids); setRefSelectorOpen(false); }}
                      onClose={() => setRefSelectorOpen(false)}
                    />
                  )}
                </div>

                <div className="flex gap-3">
                  {selected?.onGenerate && (
                    <button
                      disabled={busy || !prompt.trim()}
                      onClick={() => selected.onGenerate?.(prompt.trim())}
                      className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:opacity-40 flex items-center gap-1"
                    >
                      {busy ? <><Loader2 size={14} className="animate-spin" /> 生成中</> : <>开始生成</>}
                    </button>
                  )}
                  <button onClick={onClose} className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700">取消</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function VideoWorkbench({
  shot,
  chapterAssets,
  selectedRefIds,
  onGenerateVideo,
  onSelectRefIds,
  onClose,
  onReanalyze,
}: {
  shot: EnrichedShot;
  chapterAssets: VideoAsset[];
  selectedRefIds: number[];
  onGenerateVideo: (shotId: number, referenceAssetIds: number[]) => void;
  onSelectRefIds: (ids: number[]) => void;
  onClose: () => void;
  onReanalyze?: () => void;
}) {
  const [refSelectorOpen, setRefSelectorOpen] = useState(false);
  const shotId = shot.id;

  const [prompt, setPrompt] = useState(shot.promptDraft?.video_prompt || '');

  // 重新分析后自动刷新提示词
  useEffect(() => {
    setPrompt(shot.promptDraft?.video_prompt || '');
  }, [shot.promptDraft?.video_prompt]);

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="flex items-center gap-2 text-lg font-semibold text-slate-900"><Film size={20} /> 视频工作台</div>
            <div className="mt-1 text-sm text-slate-500">左侧预览视频，右侧编辑提示词和操作</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 hover:bg-slate-200">
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 bg-slate-900 flex items-center justify-center">
            {shot._generatedClip?.video_path ? (
              <video src={toAssetUrl(shot._generatedClip.video_path)} controls className="w-full h-full object-contain" />
            ) : shot._generatingVideo ? (
              <div className="text-center">
                <Loader2 size={48} className="animate-spin text-blue-400 mx-auto mb-3" />
                <div className="text-sm text-slate-400">视频生成中...</div>
                <div className="text-xs mt-1 text-slate-500">请稍候，生成完成后将自动更新</div>
              </div>
            ) : (
              <div className="text-center px-8">
                <Film size={40} className="text-slate-600 mx-auto mb-3" />
                <span className="text-sm text-slate-500">暂无视频</span>
              </div>
            )}
          </div>

          <div className="w-[380px] shrink-0 overflow-y-auto border-l border-[#e5edf8] bg-[#f8fbff] p-5">
            <div className="space-y-5">
              {onReanalyze && (
                <button
                  onClick={onReanalyze}
                  disabled={shot._analyzing}
                  className="w-full rounded-xl border border-[#d7e3f4] bg-white px-3 py-2 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  {shot._analyzing ? '分析中...' : <><RefreshCw size={12} className="inline-block" /> 重新分析视频提示词</>}
                </button>
              )}
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">视频提示词</div>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={12}
                  className="w-full rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
                  placeholder="输入或修改视频生成提示词..."
                />
              </div>

              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  引用资产 <span className="text-slate-400 font-normal">({selectedRefIds.length} 已选)</span>
                </div>
                <button
                  onClick={() => setRefSelectorOpen(true)}
                  className="w-full text-left text-xs text-slate-600 bg-white hover:bg-slate-50 rounded-2xl px-3 py-2.5 border border-[#d7e3f4] transition-colors"
                >
                  点击选择参考资产...
                </button>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => onGenerateVideo(shotId, selectedRefIds)}
                  disabled={shot._generatingVideo || !prompt}
                  className="flex-1 rounded-2xl bg-[#1d4ed8] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-blue-700 transition-colors flex items-center justify-center gap-2"
                >
                  {shot._generatingVideo ? (
                    <><Loader2 size={14} className="animate-spin" /> 生成中...</>
                  ) : (
                    <><Film size={14} /> 生成视频</>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {refSelectorOpen && (
        <AssetReferenceSelector
          availableAssets={chapterAssets}
          selectedIds={selectedRefIds}
          onConfirm={(ids) => {
            onSelectRefIds(ids);
            setRefSelectorOpen(false);
          }}
          onClose={() => setRefSelectorOpen(false)}
        />
      )}
    </div>,
    document.body
  );
}

// ── 单个分镜行 ────────────────────────────────────────────

/** 单行分镜（可展开查看提示词和操作） */
function ShotRow({
  shot,
  checked,
  chapterAssets,
  onCheckToggle,
  onViewAsset,
  onRedrawAsset,
  onDeleteAsset,
  onReplaceAsset,
  onGenerateVideo,
  onAnalyzeSingleShot,
  onGenerateCharacterAsset,
  onGenerateShotStoryboard,
  onGenerateSceneAsset,
  onGeneratePropAsset,
  onOpenAssetWorkbench,
  onDirectDeleteAsset,
  deletingAssetId,
}: {
  shot: EnrichedShot;
  checked: boolean;
  chapterAssets: VideoAsset[];
  onCheckToggle: (id: number) => void;
  onViewAsset: (asset: VideoAsset) => void;
  onRedrawAsset: (asset: VideoAsset) => void;
  onDeleteAsset: (shotId: number, assetId: number) => void;
  onReplaceAsset: (shotId: number, assetId: number) => void;
  onGenerateVideo: (shotId: number, referenceAssetIds: number[]) => void;
  onAnalyzeSingleShot: (shotId: number) => void;
  onGenerateCharacterAsset: (shotId: number, characterName: string, prompt: string) => Promise<void>;
  onGenerateShotStoryboard: (shotId: number, referenceAssetIds?: number[]) => Promise<void>;
  onGenerateSceneAsset?: (shotId: number, prompt: string) => Promise<void>;
  onGeneratePropAsset?: (shotId: number, propName: string, prompt: string) => Promise<void>;
  onOpenAssetWorkbench?: (items: WorkbenchItem[], title: string, refAssets?: VideoAsset[], refIds?: number[], onRefChange?: (ids: number[]) => void, shotId?: number) => void;
  onDirectDeleteAsset?: (shotId: number, assetId: number) => void;
  deletingAssetId?: number | null;
}) {
  const shotId = shot.id;
  const [expanded, setExpanded] = useState(false);
  const [refSelectorOpen, setRefSelectorOpen] = useState(false);
  const [selectedRefIds, setSelectedRefIds] = useState<number[]>([]);
  const [videoWorkbenchOpen, setVideoWorkbenchOpen] = useState(false);

  const characterNames = useMemo(() => {
    if (shot.promptDraft?.character_prompts) return shot.promptDraft.character_prompts.map(c => c.name);
    if (shot.character_involvement) {
      try { return JSON.parse(shot.character_involvement) as string[]; } catch { return [shot.character_involvement]; }
    }
    return [];
  }, [shot]);

  const charAssets = useMemo(() => {
    const isCharacterAsset = (a: any) => a.asset_type === 'character_reference' || a.asset_type === 'character';
    const currentShotChars = chapterAssets.filter(a => a.shot_id === shotId && isCharacterAsset(a));
    const normalizedNames = new Set([
      ...currentShotChars.map(a => normalizeCharName(a.name)),
      ...characterNames.map(n => normalizeCharName(n)),
    ]);
    const inheritedChars = chapterAssets.filter(a =>
      a.shot_id !== shotId && isCharacterAsset(a) && normalizedNames.has(normalizeCharName(a.name))
    );
    return [...currentShotChars, ...inheritedChars];
  }, [chapterAssets, shotId, characterNames]);

  // 场景资产（当前 shot + 同 scene 继承）
  const sceneAssets = useMemo(() => {
    const isSceneAsset = (a: any) => a.asset_type === 'scene_reference';
    const currentShotScenes = chapterAssets.filter(a => a.shot_id === shotId && isSceneAsset(a));
    const sceneId = shot.scene_id;
    const inheritedScenes = sceneId
      ? chapterAssets.filter(a => a.shot_id !== shotId && a.scene_id === sceneId && isSceneAsset(a))
      : [];
    const seen = new Set(currentShotScenes.map(a => a.id));
    const result = [...currentShotScenes];
    for (const a of inheritedScenes) {
      if (!seen.has(a.id)) {
        result.push(a);
        seen.add(a.id);
      }
    }
    return result;
  }, [chapterAssets, shotId, shot.scene_id]);

  // 道具资产（当前 shot + 同名继承）
  const propAssets = useMemo(() => {
    const isPropAsset = (a: any) => a.asset_type === 'prop_reference';
    const currentShotProps = chapterAssets.filter(a => a.shot_id === shotId && isPropAsset(a));
    const propNames = (shot.promptDraft?.prop_prompts || []).map(p => p.name);
    if (propNames.length === 0) return currentShotProps;
    const normalizedNames = new Set(propNames.map(n => n.trim().toLowerCase()));
    const inheritedProps = chapterAssets.filter(a =>
      a.shot_id !== shotId && isPropAsset(a) &&
      normalizedNames.has((a.name || '').replace(/^Prop\s*-\s*/i, '').trim().toLowerCase())
    );
    const seen = new Set(currentShotProps.map(a => a.id));
    const result = [...currentShotProps];
    for (const a of inheritedProps) {
      if (!seen.has(a.id)) {
        result.push(a);
        seen.add(a.id);
      }
    }
    return result;
  }, [chapterAssets, shotId, shot.promptDraft?.prop_prompts]);

  const hasPromptDraft = !!shot.promptDraft;

  return (
    <div className={`rounded-xl border bg-white ${checked ? 'border-blue-300 ring-1 ring-blue-100' : 'border-[#d7e3f4]'}`}>
      {/* ── 顶部主行（始终可见） ──────────────────────── */}
      <div
        className="flex items-center gap-3 p-3 cursor-pointer"
        onClick={() => setExpanded(v => !v)}
      >
        {/* 复选框 */}
        <button onClick={(e) => { e.stopPropagation(); onCheckToggle(shotId); }} className="shrink-0 text-slate-400 hover:text-blue-600">
          {checked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}
        </button>

        {/* 展开/收起 */}
        <button className="shrink-0 text-slate-400">
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {/* 分镜信息 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-900 whitespace-nowrap">分镜 {shot.shot_number}</span>
            <span className="text-sm text-slate-700 truncate">{shot.title}</span>
            <span className="hidden sm:inline text-xs text-slate-400">{shot.shot_type || 'medium'}</span>
            {hasPromptDraft && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">提示词<Check size={10} /></span>
            )}
            {shot._generatedClip && (
              <span className="text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded cursor-pointer"
                onClick={(e) => { e.stopPropagation(); window.open(toAssetUrl(shot._generatedClip!.video_path), '_blank'); }}
                title="点击查看视频"><Play size={10} className="inline-block fill-current mr-0.5" /> 视频已生成</span>
            )}
            {shot.status === 'completed' && !shot._generatedClip && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">视频<Check size={10} /></span>
            )}
            {shot._analyzing && <Loader2 size={12} className="animate-spin text-violet-500" />}
            {shot._generatingFrame && <Loader2 size={12} className="animate-spin text-blue-500" />}
          </div>
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{shot.action_description || '暂无描述'}</p>
        </div>

        {/* 操作区（阻止点击冒泡） */}
        <div className="shrink-0 flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => setRefSelectorOpen(true)}
            className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white"
          >
            参考资产
          </button>
          <button
            onClick={() => onGenerateVideo(shotId, selectedRefIds)}
            disabled={shot._generatingVideo}
            className="rounded-lg bg-[#2563eb] px-3 py-1 text-xs text-white disabled:opacity-60 flex items-center gap-1"
          >
            {shot._generatingVideo ? (
              <><Loader2 size={12} className="animate-spin" /> 生成中</>
            ) : (
              '生成视频'
            )}
          </button>
        </div>
      </div>

      {/* ── 展开区：3 列资产卡片 ────────────────── */}
      {expanded && (
        <div className="border-t border-[#e5edf8] bg-slate-50 px-4 py-4" onClick={(e) => e.stopPropagation()}>
          {/* 提示词操作条 */}
          {!hasPromptDraft && (
            <div className="mb-3 flex items-center justify-between rounded-xl border border-dashed border-[#d7e3f4] bg-white px-4 py-3">
              <div>
                <span className="text-xs font-medium text-slate-600">尚未分析提示词</span>
                <p className="text-[10px] text-slate-400 mt-0.5">AI 将分析此镜头的角色、构图和故事版提示词</p>
              </div>
              <button
                onClick={() => onAnalyzeSingleShot(shotId)}
                disabled={shot._analyzing}
                className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs text-white disabled:opacity-50 flex items-center gap-1"
              >
                {shot._analyzing ? <><Loader2 size={12} className="animate-spin" /> 分析中</> : <><Sparkles size={12} /> 分析提示词</>}
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* ① 角色资产 */}
            <AssetCard3
              title="角色资产"
              assets={charAssets}
              placeholders={
                hasPromptDraft && shot.promptDraft?.character_prompts
                  ? shot.promptDraft.character_prompts.map(cp => ({
                      key: cp.name,
                      label: cp.name,
                      prompt: cp.prompt,
                      hasAsset: charAssets.some(a => matchCharName(a.name, cp.name)),
                      isGenerating: shot._generatingCharacterAsset === cp.name,
                      onGenerate: async (p: string) => { await onGenerateCharacterAsset(shotId, cp.name, p); },
                    }))
                  : characterNames.length > 0
                    ? characterNames.map(n => ({ key: n, label: n, prompt: '', hasAsset: false, isGenerating: false }))
                    : [{ key: 'no_chars', label: '待分析角色', prompt: '', hasAsset: false, isGenerating: false }]
              }
              onViewAsset={onViewAsset}
              onRedrawAsset={onRedrawAsset}
              onDeleteAsset={(aid: number) => onDeleteAsset(shotId, aid)}
              onReplaceAsset={(aid: number) => onReplaceAsset(shotId, aid)}
              onOpenWorkbench={onOpenAssetWorkbench}
              _refAssets={chapterAssets}
              _refIds={selectedRefIds}
              _onRefChange={setSelectedRefIds}
              _shotId={shotId}
              onDirectDeleteAsset={onDirectDeleteAsset ? (aid: number) => onDirectDeleteAsset(shotId, aid) : undefined}
              deletingAssetId={deletingAssetId}
            />

            {/* ② 故事版分镜 */}
            <AssetCard3
              title={`故事版${selectedRefIds.length > 0 ? ` · ${selectedRefIds.length}个参考` : ''}`}
              assets={chapterAssets.filter(a => (a.asset_type === 'storyboard_frame' || a.asset_type === 'storyboard') && a.shot_id === shotId)}
              placeholders={[{
                key: 'storyboard',
                label: '分镜故事版',
                prompt: [
                  shot.promptDraft?.storyboard_prompt,
                  shot.title ? `Shot: ${shot.title}` : '',
                  shot.shot_type ? `Type: ${shot.shot_type}` : '',
                  shot.camera_angle ? `Angle: ${shot.camera_angle}` : '',
                  shot.camera_movement ? `Movement: ${shot.camera_movement}` : '',
                  shot.action_description ? `Action: ${shot.action_description}` : '',
                  shot.dialogue ? `Dialogue: ${shot.dialogue}` : '',
                ].filter(Boolean).join('\n'),
                hasAsset: chapterAssets.some(a => (a.asset_type === 'storyboard_frame' || a.asset_type === 'storyboard') && a.shot_id === shotId),
                isGenerating: !!shot._generatingStoryboard,
                onGenerate: hasPromptDraft
                  ? async (_p: string) => { await onGenerateShotStoryboard(shotId, selectedRefIds); }
                  : undefined,
              }].filter(p => p.prompt || p.hasAsset)}
              onViewAsset={onViewAsset}
              onRedrawAsset={onRedrawAsset}
              onDeleteAsset={(aid: number) => onDeleteAsset(shotId, aid)}
              onReplaceAsset={(aid: number) => onReplaceAsset(shotId, aid)}
              onOpenWorkbench={onOpenAssetWorkbench}
              _refAssets={chapterAssets}
              _refIds={selectedRefIds}
              _onRefChange={setSelectedRefIds}
              _shotId={shotId}
              onDirectDeleteAsset={onDirectDeleteAsset ? (aid: number) => onDirectDeleteAsset(shotId, aid) : undefined}
              deletingAssetId={deletingAssetId}
            />

            {/* ③ 场景 & 道具资产 */}
            <AssetCard3
              title="场景 & 道具"
              assets={[...sceneAssets, ...propAssets]}
              placeholders={[
                ...(hasPromptDraft && shot.promptDraft?.scene_prompt
                  ? [{
                      key: 'scene',
                      label: '场景环境',
                      prompt: shot.promptDraft.scene_prompt,
                      hasAsset: sceneAssets.some(a => a.asset_type === 'scene_reference'),
                      isGenerating: false,
                      onGenerate: onGenerateSceneAsset
                        ? async (p: string) => { await onGenerateSceneAsset(shotId, p); }
                        : undefined,
                    }]
                  : []),
                ...(hasPromptDraft && shot.promptDraft?.prop_prompts && shot.promptDraft.prop_prompts.length > 0
                  ? shot.promptDraft.prop_prompts.map(pp => ({
                      key: `prop_${pp.name}`,
                      label: pp.name,
                      prompt: pp.prompt,
                      hasAsset: propAssets.some(a => {
                        const assetPropName = (a.name || '').replace(/^Prop\s*-\s*/i, '').trim().toLowerCase();
                        return assetPropName === pp.name.trim().toLowerCase();
                      }),
                      isGenerating: false,
                      onGenerate: onGeneratePropAsset
                        ? async (p: string) => { await onGeneratePropAsset(shotId, pp.name, p); }
                        : undefined,
                    }))
                  : []),
                ...(!hasPromptDraft ? [{ key: 'no_data', label: '待分析', prompt: '', hasAsset: false, isGenerating: false }] : []),
              ]}
              onViewAsset={onViewAsset}
              onRedrawAsset={onRedrawAsset}
              onDeleteAsset={(aid: number) => onDeleteAsset(shotId, aid)}
              onReplaceAsset={(aid: number) => onReplaceAsset(shotId, aid)}
              onOpenWorkbench={onOpenAssetWorkbench}
              _refAssets={chapterAssets}
              _refIds={selectedRefIds}
              _onRefChange={setSelectedRefIds}
              _shotId={shotId}
              onDirectDeleteAsset={onDirectDeleteAsset ? (aid: number) => onDirectDeleteAsset(shotId, aid) : undefined}
              deletingAssetId={deletingAssetId}
            />

            {hasPromptDraft && (
              <div
                onClick={() => setVideoWorkbenchOpen(true)}
                className="rounded-xl border border-[#e5edf8] bg-white overflow-hidden cursor-pointer transition-all hover:shadow-md hover:border-blue-200"
              >
                <div className="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-[#e5edf8]">
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-700"><Film size={14} /> 视频</span>
                  <span className="text-[10px] text-slate-400">{shot._generatingVideo ? '生成中' : shot.promptDraft?.video_prompt ? '已就绪' : '待生成'}</span>
                </div>
                <div className="p-2">
                  <div className="flex flex-wrap gap-1.5">
                    {shot.promptDraft?.video_prompt && (
                      <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-100 to-blue-50 flex items-center justify-center shrink-0">
                        <Film size={16} className="text-blue-500" />
                      </div>
                    )}
                    {shot.promptDraft?.video_prompt && (
                      <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-green-100 to-green-50 flex items-center justify-center shrink-0">
                        <span className="text-[8px] text-green-600 font-medium">P</span>
                      </div>
                    )}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {shot.promptDraft?.video_prompt && (
                      <span className="text-[9px] text-slate-500 truncate max-w-[60px]">提示词</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 参考资产选择弹窗 */}
      {refSelectorOpen && (
        <AssetReferenceSelector
          availableAssets={chapterAssets}
          selectedIds={selectedRefIds}
          onConfirm={(ids) => {
            setSelectedRefIds(ids);
            setRefSelectorOpen(false);
          }}
          onClose={() => setRefSelectorOpen(false)}
        />
      )}

      {/* 视频工作台弹窗 */}
      {videoWorkbenchOpen && (
        <VideoWorkbench
          shot={shot}
          chapterAssets={chapterAssets}
          selectedRefIds={selectedRefIds}
          onGenerateVideo={onGenerateVideo}
          onSelectRefIds={setSelectedRefIds}
          onClose={() => setVideoWorkbenchOpen(false)}
          onReanalyze={() => onAnalyzeSingleShot(shotId)}
        />
      )}
    </div>
  );
}

// ── 主面板组件 ────────────────────────────────────────────

/** 视频分镜面板 — 工具栏 + 分页列表 + 图片重绘 */
export default function VideoStoryboardPanel({
  shots,
  shotsLoading,
  generatingStoryboard,
  checkedShotIds,
  page,
  perPage,
  totalShots,
  chapterAssets,
  onCheckToggle,
  onCheckAll,
  onPageChange,
  onGenerateStoryboard,
  onBatchAnalyzePrompts,
  onBatchGenerateFrames,
  onShotsChange,
  onGenerateVideo,
  onAnalyzeSingleShot,
  onGenerateCharacterAsset,
  onGenerateSceneAsset,
  onGeneratePropAsset,
  onGenerateShotStoryboard,
  onAssetsChanged,
  stylePresets,
  selectedStyle,
  onStyleChange,
}: VideoStoryboardPanelProps) {
  const [redrawTarget, setRedrawTarget] = useState<{ asset: VideoAsset; shotId: number } | null>(null);
  const [redrawBusy, setRedrawBusy] = useState(false);
  const [viewImage, setViewImage] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [workbenchItems, setWorkbenchItems] = useState<WorkbenchItem[] | null>(null);
  const [workbenchTitle, setWorkbenchTitle] = useState('');
  const [workbenchBusy, setWorkbenchBusy] = useState(false);
  const [workbenchGeneratingKey, setWorkbenchGeneratingKey] = useState<string | null>(null);
  const [workbenchRefAssets, setWorkbenchRefAssets] = useState<VideoAsset[]>([]);
  const [workbenchRefIds, setWorkbenchRefIds] = useState<number[]>([]);
  const [workbenchShotId, setWorkbenchShotId] = useState<number | null>(null);
  const workbenchOnRefChange = useRef<((ids: number[]) => void) | null>(null);

  const handleOpenWorkbench = useCallback(
    (items: WorkbenchItem[], title: string, refAssets?: VideoAsset[], refIds?: number[], onRefChange?: (ids: number[]) => void, shotId?: number) => {
      setWorkbenchItems(items);
      setWorkbenchTitle(title);
      setWorkbenchRefAssets(refAssets || []);
      setWorkbenchRefIds(refIds || []);
      setWorkbenchShotId(shotId || null);
      workbenchOnRefChange.current = onRefChange || null;
    },
    [],
  );


  const handleCloseWorkbench = useCallback(() => {
    setWorkbenchItems(null);
    setWorkbenchBusy(false);
    setWorkbenchGeneratingKey(null);
  }, []);

  const totalPages = Math.max(1, Math.ceil(totalShots / perPage));
  const pageShots = paginate(shots, page, perPage);
  const allChecked = pageShots.length > 0 && pageShots.every(s => checkedShotIds.has(s.id));

  // ── 资产操作 ──────────────────────────────────────

  const handleViewAsset = useCallback((asset: VideoAsset) => {
    setViewImage(toAssetUrl(asset.file_path));
  }, []);

  const handleRedrawAsset = useCallback((asset: VideoAsset) => {
    setRedrawTarget({ asset, shotId: asset.shot_id || 0 });
  }, []);

  const handleDeleteAsset = useCallback(async (shotId: number, assetId: number) => {
    if (deleteConfirmId === assetId) {
      try {
        await deleteVideoAsset(assetId);
        toast.success('资产已删除');
        onShotsChange(shots.map(s => {
          if (s.id === shotId) {
            const newFrames = s.frames ? {
              ...s.frames,
              first_frames: s.frames.first_frames.filter(f => f.id !== assetId),
              last_frames: s.frames.last_frames.filter(f => f.id !== assetId),
            } : undefined;
            return { ...s, frames: newFrames };
          }
          return s;
        }));
        setDeleteConfirmId(null);
        // 通知父级刷新 chapterAssets
        await onAssetsChanged?.();
      } catch (err: any) {
        toast.error(`删除失败: ${err.message}`);
      }
    } else {
      setDeleteConfirmId(assetId);
      setTimeout(() => setDeleteConfirmId(prev => prev === assetId ? null : prev), 3000);
    }
  }, [deleteConfirmId, shots, onShotsChange, onAssetsChanged]);

  const handleDirectDeleteAsset = useCallback(async (shotId: number, assetId: number) => {
    try {
      await deleteVideoAsset(assetId);
      toast.success('资产已删除');
      onShotsChange(shots.map(s => {
        if (s.id === shotId) {
          const newFrames = s.frames ? {
            ...s.frames,
            first_frames: s.frames.first_frames.filter(f => f.id !== assetId),
            last_frames: s.frames.last_frames.filter(f => f.id !== assetId),
          } : undefined;
          return { ...s, frames: newFrames };
        }
        return s;
      }));
      await onAssetsChanged?.();
    } catch (err: any) {
      toast.error(`删除失败: ${err.message}`);
    }
  }, [shots, onShotsChange, onAssetsChanged]);

  const handleReplaceAsset = useCallback(async (shotId: number, assetId: number) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    const cleanup = () => { input.remove(); };
    input.addEventListener('cancel', cleanup, { once: true });
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) { cleanup(); return; }
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch(`/api/video-assets/${assetId}/replace`, {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) throw new Error(await readResponseError(res, '替换资产图失败，请稍后重试'));
        toast.success('资产图已替换');
        await onAssetsChanged?.();
        if (shotId) {
          const frames = await getShotFrames(shotId);
          onShotsChange(shots.map(s => s.id === shotId ? { ...s, frames } : s));
        }
      } catch (err: any) {
        toast.error(`替换失败: ${err.message}`);
      } finally {
        cleanup();
      }
    };
    input.click();
  }, [shots, onShotsChange, onAssetsChanged]);

  const handleRedrawSubmit = useCallback(async (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => {
    if (!redrawTarget) return;
    setRedrawBusy(true);
    try {
      await regenerateShotFrame(redrawTarget.shotId, {
        asset_id: redrawTarget.asset.id,
        prompt: payload.prompt,
        mode: payload.mode,
        mask: payload.mask || null,
      });
      toast.success('重绘完成');
      if (redrawTarget.shotId) {
        const frames = await getShotFrames(redrawTarget.shotId);
        onShotsChange(shots.map(s => s.id === redrawTarget.shotId ? { ...s, frames } : s));
      }
      setRedrawTarget(null);
    } catch (err: any) {
      toast.error(`重绘失败: ${err.message}`);
    } finally {
      setRedrawBusy(false);
    }
  }, [redrawTarget, shots, onShotsChange]);

  // ── 渲染 ──────────────────────────────────────────

  if (!shotsLoading && shots.length === 0 && !generatingStoryboard) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#d7e3f4]">
          <span className="text-sm font-medium text-slate-900">分镜列表</span>
          <button
            onClick={onGenerateStoryboard}
            className="rounded-xl bg-[#2563eb] px-4 py-2 text-sm text-white hover:bg-blue-700 transition"
          >
            一键分镜
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-400">
            <Film size={48} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">点击顶部「一键分镜」将本章拆分为分镜</p>
            <p className="text-xs mt-1">AI 将自动分析每镜出场人物、场景和镜头类型</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#d7e3f4] bg-white/80 backdrop-blur">
        <div className="flex items-center gap-3">
          <button onClick={() => onCheckAll(!allChecked)} className="text-slate-400 hover:text-blue-600" title="全选/取消">
            {allChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}
          </button>
          <span className="text-sm font-medium text-slate-900">
            分镜列表
            {checkedShotIds.size > 0 && (
              <span className="ml-1 text-xs text-blue-600">(已选 {checkedShotIds.size} 镜)</span>
            )}
          </span>
          {/* 风格选择 */}
          {stylePresets.length > 0 && (
            <select
              value={selectedStyle}
              onChange={(e) => onStyleChange(e.target.value)}
              className="ml-3 rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 bg-white outline-none"
            >
              {stylePresets.map(sp => (
                <option key={sp.id} value={sp.name}>{sp.name}</option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onGenerateStoryboard}
            disabled={generatingStoryboard}
            className="rounded-lg border border-[#d7e3f4] px-3 py-1.5 text-xs text-slate-600 hover:bg-white disabled:opacity-60"
          >
            {generatingStoryboard ? (
              <span className="flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> 拆分中</span>
            ) : shots.length > 0 ? '重新分镜' : '一键分镜'}
          </button>
          <button
            onClick={() => onBatchAnalyzePrompts(Array.from(checkedShotIds))}
            disabled={checkedShotIds.size === 0}
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs text-white disabled:opacity-40"
          >
            批量分析提示词
          </button>
          <button
            onClick={() => onBatchGenerateFrames(Array.from(checkedShotIds))}
            disabled={checkedShotIds.size === 0}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs text-white disabled:opacity-40"
          >
            批量生成首尾帧
          </button>
        </div>
      </div>

      {shotsLoading && (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={24} className="animate-spin text-slate-400" />
        </div>
      )}

      {!shotsLoading && (
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {pageShots.map((shot) => (
            <ShotRow
              key={shot.id}
              shot={shot}
              checked={checkedShotIds.has(shot.id)}
              chapterAssets={chapterAssets}
              onCheckToggle={onCheckToggle}
              onViewAsset={handleViewAsset}
              onRedrawAsset={handleRedrawAsset}
              onDeleteAsset={handleDeleteAsset}
              onReplaceAsset={handleReplaceAsset}
              onGenerateVideo={onGenerateVideo}
              onAnalyzeSingleShot={onAnalyzeSingleShot}
              onGenerateCharacterAsset={onGenerateCharacterAsset}
              onGenerateSceneAsset={onGenerateSceneAsset}
              onGeneratePropAsset={onGeneratePropAsset}
              onGenerateShotStoryboard={onGenerateShotStoryboard}
              onOpenAssetWorkbench={handleOpenWorkbench}
              onDirectDeleteAsset={handleDirectDeleteAsset}
              deletingAssetId={deleteConfirmId}
            />
          ))}
        </div>
      )}

      {!shotsLoading && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 px-4 py-3 border-t border-[#d7e3f4]">
          <button onClick={() => onPageChange(page - 1)} disabled={page <= 1} className="p-1 rounded text-slate-400 hover:text-slate-700 disabled:opacity-30"><ChevronLeft size={16} /></button>
          <span className="text-xs text-slate-600">{page} / {totalPages}</span>
          <input type="number" min={1} max={totalPages} value={page} onChange={(e) => { const v = Number(e.target.value); if (v >= 1 && v <= totalPages) onPageChange(v); }} className="w-12 text-center rounded border border-[#d7e3f4] text-xs py-1" />
          <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages} className="p-1 rounded text-slate-400 hover:text-slate-700 disabled:opacity-30"><ChevronRight size={16} /></button>
        </div>
      )}

      {viewImage && (
        <div className="fixed inset-0 z-[65] bg-black/80 flex items-center justify-center cursor-zoom-out" onClick={() => setViewImage(null)}>
          <MediaImage src={viewImage} alt="预览" className="max-h-[90vh] max-w-[90vw] object-contain rounded-xl shadow-2xl" />
        </div>
      )}

      {redrawTarget && (
        <ImageRedrawModal
          imageSrc={toAssetUrl(redrawTarget.asset.file_path)}
          title={`${redrawTarget.asset.name} 重绘`}
          prompt={(redrawTarget.shotId
            ? shots.find(s => s.id === redrawTarget.shotId)?.promptDraft?.storyboard_prompt
            : '') || redrawTarget.asset.prompt || ''}
          busy={redrawBusy}
          onClose={() => setRedrawTarget(null)}
          onSubmit={handleRedrawSubmit}
        />
      )}

      {/* 多资源列表工作台 */}
      {workbenchItems && workbenchItems.length > 0 && (
        <MultiAssetWorkbench
          title={workbenchTitle}
          items={workbenchItems.map(item => ({
            ...item,
            onGenerate: item.onGenerate
              ? async (editedPrompt: string) => {
                  setWorkbenchBusy(true);
                  setWorkbenchGeneratingKey(item.key);
                  try {
                    await item.onGenerate?.(editedPrompt);
                    if (onShotsChange) {
                      onShotsChange(shots);
                    }
                    const updatedItems = workbenchItems.map(i =>
                      i.key === item.key ? { ...i, isGenerating: false } : i
                    );
                    setWorkbenchItems(updatedItems);
                  } finally {
                    setWorkbenchBusy(false);
                    setWorkbenchGeneratingKey(null);
                  }
                }
              : undefined,
          }))}
          onClose={handleCloseWorkbench}
          refAssets={workbenchRefAssets}
          refSelectedIds={workbenchRefIds}
          onRefSelect={(ids) => { setWorkbenchRefIds(ids); workbenchOnRefChange.current?.(ids); }}
          onReanalyze={workbenchShotId && workbenchItems ? (async () => {
            setWorkbenchBusy(true);
            try {
              await onAnalyzeSingleShot(workbenchShotId);
              setWorkbenchItems(null);
              toast.success('提示词已重新分析，请重新打开工作台查看');
            } catch (e: any) {
              toast.error(`重新分析失败: ${e.message}`);
            } finally {
              setWorkbenchBusy(false);
            }
          }) : undefined}
          onRegenerate={workbenchShotId && workbenchItems ? (async (prompt: string, mode: string) => {
            const assetKey = workbenchItems.find(i => i.isAsset)?.key;
            if (!assetKey) return;
            const assetId = parseInt(assetKey);
            if (!assetId) return;
            setWorkbenchBusy(true);
            try {
              await regenerateShotFrame(workbenchShotId, {
                asset_id: assetId,
                prompt,
                mode: mode as ImageRedrawMode,
              });
              toast.success('重绘完成');
              const frames = await getShotFrames(workbenchShotId);
              onShotsChange(shots.map(s => s.id === workbenchShotId ? { ...s, frames } : s));
            } catch (e: any) {
              toast.error('重绘失败: ' + (e.message || ''));
            } finally {
              setWorkbenchBusy(false);
            }
          }) : undefined}
          onDelete={(item: WorkbenchItem) => {
            const asset = chapterAssets.find(a => String(a.id) === item.key);
            if (asset) handleDeleteAsset(asset.shot_id || 0, asset.id);
          }}
          onReplace={(item: WorkbenchItem) => {
            const asset = chapterAssets.find(a => String(a.id) === item.key);
            if (asset) handleReplaceAsset(asset.shot_id || 0, asset.id);
          }}
          busy={workbenchBusy}
          generatingKey={workbenchGeneratingKey}
        />
      )}
    </div>
  );
}
