import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, ChevronUp, Download, Edit3, Image as ImageIcon, Loader2, MapPin, Package, Palette, Pin, Save, Sparkles, Trash2, Upload, User, X } from 'lucide-react';
import {
  analyzeChapterMangaAssets,
  deleteMangaAsset,
  generateMangaAsset,
  generateMangaAssetsBatch,
  getMangaAssetAnalysis,
  listMangaAssetBindings,
  listMangaAssets,
  redrawMangaAsset,
  saveMangaAssetBindings,
  saveMangaAssetAnalysis,
  toPublicMangaAssetUrl,
  updateMangaAsset,
  uploadMangaAsset,
  type MangaAsset,
  type MangaAssetAnalysisSuggestion,
  type MangaAssetBinding,
  type MangaAssetType,
  type ImageRedrawMode,
  type BackgroundTaskStatus,
} from '../api';
import { confirm } from '../lib/confirm';
import { toast } from '../lib/toast';
import { normalizeErrorMessage } from '../lib/errors';
import { downloadImagesAsZip, sanitizeFilename } from '../lib/zipDownload';
import { getTrackedMangaAssetBatch, subscribeMangaAssetBatch, trackMangaAssetBatch } from '../mangaAssetBatchMonitor';
import { ImageRedrawModal } from './shared/ImageRedrawModal';

interface Props {
  storyId: number;
  chapterId: number;
  onClose: () => void;
  onAssetsChanged?: () => void;
}

type AssetTab = 'all' | MangaAssetType;

const tabs: Array<{ key: AssetTab; label: string; icon: typeof ImageIcon }> = [
  { key: 'all', label: '全部', icon: ImageIcon },
  { key: 'character_reference', label: '角色', icon: User },
  { key: 'scene_reference', label: '场景', icon: MapPin },
  { key: 'prop_reference', label: '道具', icon: Package },
  { key: 'style_reference', label: '风格', icon: Palette },
];

const assetTypeLabel: Record<MangaAssetType, string> = {
  character_reference: '角色',
  scene_reference: '场景',
  prop_reference: '道具',
  style_reference: '风格',
};

function bindingRole(type: MangaAssetType): string {
  return type.replace('_reference', '');
}

function suggestionKey(suggestion: MangaAssetAnalysisSuggestion, index: number): string {
  return `${suggestion.asset_type}-${suggestion.name}-${index}`;
}

function assetPrompt(asset: MangaAsset): string {
  const prompt = asset.metadata?.prompt;
  if (typeof prompt === 'string' && prompt.trim()) return prompt;
  return `保持“${asset.name}”的核心造型、材质、配色和画面风格一致，按我的要求重新绘制。`;
}

function assetImageUrl(asset: MangaAsset): string {
  const url = toPublicMangaAssetUrl(asset.storage_path);
  const revision = asset.metadata?.revision;
  if (!url || (typeof revision !== 'number' && typeof revision !== 'string')) return url || '';
  return `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(String(revision))}`;
}

function assetFileExtension(storagePath: string): string {
  const match = /\.([a-zA-Z0-9]+)(?:\?|$)/.exec(storagePath || '');
  const ext = match ? match[1].toLowerCase() : '';
  return ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(ext) ? ext : 'png';
}

const terminalTaskStatuses = new Set(['succeeded', 'failed', 'cancelled', 'canceled']);

export default function MangaAssetManagementModal({ storyId, chapterId, onClose, onAssetsChanged }: Props) {
  const [assets, setAssets] = useState<MangaAsset[]>([]);
  const [bindings, setBindings] = useState<MangaAssetBinding[]>([]);
  const [activeTab, setActiveTab] = useState<AssetTab>('all');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState('');
  const [editingLabel, setEditingLabel] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadType, setUploadType] = useState<MangaAssetType>('character_reference');
  const [uploadLabel, setUploadLabel] = useState('');
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [suggestions, setSuggestions] = useState<MangaAssetAnalysisSuggestion[]>([]);
  const [suggestionsCollapsed, setSuggestionsCollapsed] = useState(false);
  const [suggestionsDirty, setSuggestionsDirty] = useState(false);
  const [savingSuggestions, setSavingSuggestions] = useState(false);
  const [generatingSuggestion, setGeneratingSuggestion] = useState<string | null>(null);
  const [selectedSuggestionKeys, setSelectedSuggestionKeys] = useState<Set<string>>(() => new Set());
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchTask, setBatchTask] = useState<BackgroundTaskStatus | null>(() => getTrackedMangaAssetBatch(chapterId));
  const [bindingBusy, setBindingBusy] = useState(false);
  const [workbenchAsset, setWorkbenchAsset] = useState<MangaAsset | null>(null);
  const [redrawingAssetId, setRedrawingAssetId] = useState<number | null>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [downloadStatus, setDownloadStatus] = useState('');
  const exportAbortRef = useRef<AbortController | null>(null);
  const bindingsRef = useRef<MangaAssetBinding[]>([]);
  const bindingBusyRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadAssets = useCallback(async (includeAnalysis = false) => {
    setLoading(true);
    try {
      const [assetResult, bindingResult, analysisResult] = await Promise.all([
        listMangaAssets(storyId),
        listMangaAssetBindings(chapterId),
        includeAnalysis ? getMangaAssetAnalysis(chapterId) : Promise.resolve(null),
      ]);
      setAssets(assetResult.assets);
      setBindings(bindingResult.bindings);
      bindingsRef.current = bindingResult.bindings;
      if (analysisResult) {
        setSuggestions(analysisResult.suggestions);
        setSuggestionsDirty(false);
        setSelectedSuggestionKeys(new Set(analysisResult.suggestions.map((suggestion, index) => suggestionKey(suggestion, index))));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '加载漫画资产失败');
    } finally {
      setLoading(false);
    }
  }, [chapterId, storyId]);

  useEffect(() => { void loadAssets(true); }, [loadAssets]);

  useEffect(() => {
    setBatchTask(getTrackedMangaAssetBatch(chapterId));
    return subscribeMangaAssetBatch((update) => {
      if (update.chapterId !== chapterId) return;
      setBatchTask(update.task);
      if (terminalTaskStatuses.has(update.task.status)) {
        void loadAssets().then(() => onAssetsChanged?.());
      }
    });
  }, [chapterId, loadAssets, onAssetsChanged]);

  const filteredAssets = useMemo(
    () => activeTab === 'all' ? assets : assets.filter((asset) => asset.asset_type === activeTab),
    [activeTab, assets],
  );

  const getBinding = (assetId: number) => bindings.find((binding) => binding.asset_id === assetId);

  const saveBindings = async (nextBindings: MangaAssetBinding[]) => {
    const result = await saveMangaAssetBindings(chapterId, nextBindings.map((binding) => ({
      asset_id: binding.asset_id,
      binding_role: binding.binding_role,
      label: binding.label ?? null,
      priority: binding.priority,
      is_required: binding.is_required,
    })));
    setBindings(result.bindings);
    bindingsRef.current = result.bindings;
    onAssetsChanged?.();
  };

  const beginBindingWrite = () => {
    if (bindingBusyRef.current) return false;
    bindingBusyRef.current = true;
    setBindingBusy(true);
    return true;
  };

  const finishBindingWrite = () => {
    bindingBusyRef.current = false;
    setBindingBusy(false);
  };

  const toggleBinding = async (asset: MangaAsset) => {
    if (!beginBindingWrite()) return;
    setSaving(asset.id);
    try {
      const currentBindings = bindingsRef.current;
      const current = currentBindings.find((binding) => binding.asset_id === asset.id);
      const next = current
        ? currentBindings.filter((binding) => binding.asset_id !== asset.id)
        : [...currentBindings, {
          id: 0,
          asset_id: asset.id,
          binding_role: bindingRole(asset.asset_type),
          label: asset.name,
          priority: 0,
          is_required: false,
        }];
      await saveBindings(next);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存章节资产绑定失败');
    } finally {
      setSaving(null);
      finishBindingWrite();
    }
  };

  const toggleRequiredBinding = async (asset: MangaAsset) => {
    if (!beginBindingWrite()) return;
    setSaving(asset.id);
    try {
      const currentBindings = bindingsRef.current;
      const current = currentBindings.find((binding) => binding.asset_id === asset.id);
      if (!current) return;
      await saveBindings(currentBindings.map((binding) => binding.asset_id === asset.id
        ? { ...binding, is_required: !binding.is_required }
        : binding));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新全章固定状态失败');
    } finally {
      setSaving(null);
      finishBindingWrite();
    }
  };

  const bindSuggestion = async (suggestion: MangaAssetAnalysisSuggestion, asset: Pick<MangaAsset, 'id' | 'name' | 'asset_type'>) => {
    if (!beginBindingWrite()) return;
    setSaving(asset.id);
    try {
      const currentBindings = bindingsRef.current;
      const current = currentBindings.find((binding) => binding.asset_id === asset.id);
      const next = current
        ? currentBindings.map((binding) => binding.asset_id === asset.id ? { ...binding, label: suggestion.name, binding_role: bindingRole(suggestion.asset_type) } : binding)
        : [...currentBindings, {
          id: 0,
          asset_id: asset.id,
          binding_role: bindingRole(suggestion.asset_type),
          label: suggestion.name,
          priority: 0,
          is_required: false,
        }];
      await saveBindings(next);
      toast.success(`已将“${asset.name}”绑定为${suggestion.name}参考`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '绑定分析建议失败');
    } finally {
      setSaving(null);
      finishBindingWrite();
    }
  };

  const analyzeCurrentChapter = async () => {
    setAnalyzing(true);
    try {
      const result = await analyzeChapterMangaAssets(chapterId);
      setSuggestions(result.suggestions);
      setSuggestionsCollapsed(false);
      setSuggestionsDirty(false);
      setSelectedSuggestionKeys(new Set(result.suggestions.map((suggestion, index) => suggestionKey(suggestion, index))));
      if (result.suggestions.length === 0) toast.info('未发现需要建立视觉参考的关键资产');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '分析当前章节资产失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const openUploadForSuggestion = (suggestion: MangaAssetAnalysisSuggestion) => {
    setUploadType(suggestion.asset_type);
    setUploadName(suggestion.name);
    setUploadLabel(suggestion.name);
    setUploadOpen(true);
  };

  const updateSuggestionPrompt = (index: number, prompt: string) => {
    setSuggestions((current) => current.map((suggestion, suggestionIndex) => (
      suggestionIndex === index ? { ...suggestion, prompt } : suggestion
    )));
    setSuggestionsDirty(true);
  };

  const persistSuggestions = async (showSuccess = true) => {
    setSavingSuggestions(true);
    try {
      const result = await saveMangaAssetAnalysis(chapterId, suggestions);
      setSuggestions(result.suggestions);
      setSuggestionsDirty(false);
      if (showSuccess) toast.success('资产提示词已保存');
      return result.suggestions;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存漫画资产提示词失败');
      return null;
    } finally {
      setSavingSuggestions(false);
    }
  };

  const toggleSuggestionSelection = (key: string) => {
    setSelectedSuggestionKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const allSuggestionsSelected = suggestions.length > 0 && suggestions.every(
    (suggestion, index) => selectedSuggestionKeys.has(suggestionKey(suggestion, index)),
  );

  const toggleAllSuggestions = () => {
    setSelectedSuggestionKeys(allSuggestionsSelected
      ? new Set()
      : new Set(suggestions.map((suggestion, index) => suggestionKey(suggestion, index))));
  };

  const selectedSuggestionCount = suggestions.reduce(
    (count, suggestion, index) => count + (selectedSuggestionKeys.has(suggestionKey(suggestion, index)) ? 1 : 0),
    0,
  );
  const batchTaskActive = Boolean(batchTask && !terminalTaskStatuses.has(batchTask.status));
  const batchCompleted = Number(batchTask?.result_json?.completed ?? batchTask?.metadata_json?.completed ?? 0);
  const batchFailed = Number(batchTask?.result_json?.failed ?? batchTask?.metadata_json?.failed ?? 0);
  const batchTotal = Number(batchTask?.result_json?.total ?? batchTask?.metadata_json?.total ?? 0);

  const generateSelectedSuggestions = async () => {
    const selected = suggestions.filter((suggestion, index) => (
      selectedSuggestionKeys.has(suggestionKey(suggestion, index))
    ));
    if (selected.length === 0) {
      toast.info('请先勾选需要出图的资产');
      return;
    }
    const emptyPrompt = selected.find((suggestion) => !suggestion.prompt.trim());
    if (emptyPrompt) {
      toast.error(`请先填写“${emptyPrompt.name}”的资产设定图提示词`);
      return;
    }

    setBatchSubmitting(true);
    try {
      if (suggestionsDirty) {
        const saved = await persistSuggestions(false);
        if (!saved) return;
      }
      const result = await generateMangaAssetsBatch(chapterId, selected.map((suggestion) => ({
        asset_type: suggestion.asset_type,
        name: suggestion.name,
        prompt: suggestion.prompt.trim(),
      })));
      setBatchTask({
        task_id: result.task_id,
        task_type: 'manga_asset_batch_generation',
        status: result.status,
        message: result.message,
        metadata_json: { total: result.total, completed: 0, failed: 0 },
      });
      trackMangaAssetBatch(chapterId, result.task_id);
      toast.info('批量出图已转入后台，可关闭弹窗或网页');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '提交漫画资产批量出图失败');
    } finally {
      setBatchSubmitting(false);
    }
  };

  const generateSuggestionAsset = async (suggestion: MangaAssetAnalysisSuggestion, index: number) => {
    const prompt = suggestion.prompt.trim();
    if (!prompt) {
      toast.error('请先填写资产设定图提示词');
      return;
    }
    const itemKey = suggestionKey(suggestion, index);
    setGeneratingSuggestion(itemKey);
    try {
      if (suggestionsDirty) {
        const saved = await persistSuggestions(false);
        if (!saved) return;
      }
      await generateMangaAsset(chapterId, {
        asset_type: suggestion.asset_type,
        name: suggestion.name,
        prompt,
      });
      await loadAssets();
      onAssetsChanged?.();
      toast.success(`“${suggestion.name}”资产图已生成并绑定到本章`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '生成漫画资产失败');
    } finally {
      setGeneratingSuggestion(null);
    }
  };

  const saveAssetEdit = async (asset: MangaAsset) => {
    const name = editingName.trim();
    if (!name) return;
    if (!beginBindingWrite()) return;
    setSaving(asset.id);
    try {
      const updated = await updateMangaAsset(asset.id, { name });
      setAssets((current) => current.map((item) => item.id === asset.id ? updated : item));
      const currentBindings = bindingsRef.current;
      const binding = currentBindings.find((item) => item.asset_id === asset.id);
      // 编辑未绑定资产只更新资产本身，不隐式改变本章绑定范围。
      if (binding) {
        await saveBindings(currentBindings.map((item) => item.asset_id === asset.id
          ? { ...item, label: editingLabel.trim() || name }
          : item));
      }
      setEditingId(null);
      onAssetsChanged?.();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新漫画资产失败');
    } finally {
      setSaving(null);
      finishBindingWrite();
    }
  };

  const removeAsset = async (asset: MangaAsset) => {
    const accepted = await confirm({ title: '删除漫画资产', message: `确定删除“${asset.name}”吗？已绑定到本章的引用会一并解除。`, confirmText: '删除', danger: true });
    if (!accepted) return;
    setDeleting(asset.id);
    try {
      await deleteMangaAsset(asset.id);
      setAssets((current) => current.filter((item) => item.id !== asset.id));
      setBindings((current) => current.filter((item) => item.asset_id !== asset.id));
      onAssetsChanged?.();
      toast.success('漫画资产已删除');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除漫画资产失败');
    } finally {
      setDeleting(null);
    }
  };

  const resetUpload = () => {
    setUploadOpen(false);
    setUploadFile(null);
    setUploadName('');
    setUploadLabel('');
    setUploadPreview(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadName.trim()) return;
    setUploading(true);
    try {
      await uploadMangaAsset(storyId, {
        file: uploadFile,
        asset_type: uploadType,
        name: uploadName.trim(),
        chapter_id: chapterId,
        bind_to_chapter: true,
        binding_label: uploadLabel.trim() || uploadName.trim(),
      });
      resetUpload();
      await loadAssets();
      toast.success('漫画资产已上传并绑定到本章');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '上传漫画资产失败');
    } finally {
      setUploading(false);
    }
  };

  const handleAssetRedraw = async (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => {
    if (!workbenchAsset) return;
    setRedrawingAssetId(workbenchAsset.id);
    try {
      const updated = await redrawMangaAsset(workbenchAsset.id, payload);
      setAssets((current) => current.map((asset) => asset.id === updated.id ? updated : asset));
      setWorkbenchAsset(null);
      onAssetsChanged?.();
      toast.success('漫画资产重绘完成');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重绘漫画资产失败');
    } finally {
      setRedrawingAssetId(null);
    }
  };

  // 复用公共下载工具，将当前筛选的资产图片打包为 ZIP 导出。
  const handleDownloadAll = async () => {
    const items = filteredAssets
      .map((asset) => ({ asset, url: assetImageUrl(asset) }))
      .filter((entry): entry is { asset: MangaAsset; url: string } => Boolean(entry.url))
      .map(({ asset, url }) => ({
        filename: `${assetTypeLabel[asset.asset_type]}_${sanitizeFilename(asset.name)}.${assetFileExtension(asset.storage_path)}`,
        url,
      }));
    if (items.length === 0) {
      toast.error('当前没有可下载的资产图片');
      return;
    }
    if (downloadingAll) return;
    exportAbortRef.current?.abort();
    const abortController = new AbortController();
    exportAbortRef.current = abortController;
    const isCurrentExport = () => (
      exportAbortRef.current === abortController && !abortController.signal.aborted
    );
    setDownloadingAll(true);
    setDownloadStatus('正在准备导出');
    try {
      const dateStr = new Date().toISOString().slice(0, 10);
      await downloadImagesAsZip(items, {
        zipName: `漫画资产_${dateStr}.zip`,
        signal: abortController.signal,
        onStage: (stage) => {
          if (!isCurrentExport()) return;
          if (stage === 'preparing') setDownloadStatus('正在准备导出');
          if (stage === 'downloading') setDownloadStatus(`下载 0/${items.length}`);
          if (stage === 'archiving') setDownloadStatus('正在生成压缩包');
        },
        onProgress: (completed, total) => {
          if (isCurrentExport()) setDownloadStatus(`下载 ${completed}/${total}`);
        },
      });
      if (!isCurrentExport()) return;
      toast.success(`已下载 ${items.length} 张资产图片`);
    } catch (err) {
      if (exportAbortRef.current !== abortController) return;
      if (abortController.signal.aborted) return;
      toast.error(normalizeErrorMessage(err, '资产打包下载失败，请重试'));
    } finally {
      if (exportAbortRef.current === abortController) {
        exportAbortRef.current = null;
        setDownloadingAll(false);
        setDownloadStatus('');
      }
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <section className="flex h-[85vh] w-[min(1100px,95vw)] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()} aria-modal="true" role="dialog" aria-label="漫画资产管理">
        <header className="flex flex-col gap-3 border-b border-slate-200 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">漫画资产管理</h2>
            <p className="mt-0.5 text-xs text-slate-500">角色、场景、道具和风格资产独立管理，勾选后用于当前章节的漫画生成。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => void analyzeCurrentChapter()} disabled={analyzing} className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100 disabled:opacity-50">
              {analyzing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}分析当前章节
            </button>
            <button type="button" onClick={() => setUploadOpen(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700">
              <Upload size={15} />上传资产
            </button>
            <button type="button" onClick={() => void handleDownloadAll()} disabled={downloadingAll || filteredAssets.length === 0} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">
              {downloadingAll ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
              {downloadingAll ? downloadStatus : '下载导出'}
            </button>
            <button type="button" onClick={onClose} className="rounded-full p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800" title="关闭">
              <X size={18} />
            </button>
          </div>
        </header>

        <nav className="flex gap-1 overflow-x-auto bg-slate-50 px-6 pt-4" aria-label="资产分类">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const count = tab.key === 'all' ? assets.length : assets.filter((asset) => asset.asset_type === tab.key).length;
            return <button key={tab.key} type="button" onClick={() => setActiveTab(tab.key)} className={`inline-flex shrink-0 items-center gap-1.5 rounded-t-lg px-4 py-2 text-sm font-medium transition ${activeTab === tab.key ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500 hover:bg-white/70 hover:text-slate-700'}`}>
              <Icon size={14} />{tab.label}<span className="text-xs text-slate-400">({count})</span>
            </button>;
          })}
        </nav>

        <div className="flex-1 overflow-y-auto p-6">
          {suggestions.length > 0 && <section className="mb-6 border-b border-slate-200 pb-6">
            <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between"><div><h3 className="text-sm font-semibold text-slate-800">章节资产分析建议</h3><p className="mt-0.5 text-xs text-slate-500">分析结果会按章节保存；修改提示词后请点击保存。</p></div><div className="flex flex-wrap items-center gap-2">{!suggestionsCollapsed && <><label className={`inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 ${batchTaskActive || batchSubmitting ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-slate-50'}`}><input type="checkbox" checked={allSuggestionsSelected} onChange={toggleAllSuggestions} disabled={batchTaskActive || batchSubmitting} className="h-3.5 w-3.5 accent-indigo-600" />{allSuggestionsSelected ? '取消全选' : '全选'}</label><button type="button" onClick={() => void generateSelectedSuggestions()} disabled={selectedSuggestionCount === 0 || batchTaskActive || batchSubmitting || generatingSuggestion !== null} className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">{batchSubmitting || batchTaskActive ? <Loader2 size={13} className="animate-spin" /> : <ImageIcon size={13} />}{batchSubmitting ? '提交中...' : batchTaskActive ? `后台生成中 ${batchCompleted + batchFailed}/${batchTotal || selectedSuggestionCount}` : `一键出图（${selectedSuggestionCount}）`}</button></>}<button type="button" onClick={() => void persistSuggestions()} disabled={!suggestionsDirty || savingSuggestions} className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-white px-2.5 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50">{savingSuggestions ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}{savingSuggestions ? '保存中...' : '保存提示词'}</button><button type="button" onClick={() => setSuggestionsCollapsed((value) => !value)} className="inline-flex items-center gap-1 rounded-md px-2 py-2 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-800">{suggestionsCollapsed ? <ChevronDown size={13} /> : <ChevronUp size={13} />}{suggestionsCollapsed ? '展开' : '收起'}</button></div></div>
            {!suggestionsCollapsed && batchTask && <div className={`mb-3 rounded-lg border px-3 py-2.5 ${batchTaskActive ? 'border-indigo-200 bg-indigo-50' : batchTask.status === 'succeeded' ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'}`}><div className="flex items-center justify-between gap-3 text-xs"><span className="font-medium text-slate-700">{batchTask.message || (batchTaskActive ? '后台正在并行生成资产图' : '批量任务已结束')}</span><span className="shrink-0 text-slate-500">成功 {batchCompleted} · 失败 {batchFailed} · 共 {batchTotal}</span></div>{batchTotal > 0 && <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/80"><div className={`h-full rounded-full transition-all ${batchTaskActive ? 'bg-indigo-500' : 'bg-emerald-500'}`} style={{ width: `${Math.min(100, ((batchCompleted + batchFailed) / batchTotal) * 100)}%` }} /></div>}</div>}
            {!suggestionsCollapsed && <div className="grid gap-3 lg:grid-cols-2">
              {suggestions.map((suggestion, index) => { const itemKey = suggestionKey(suggestion, index); const isGenerating = generatingSuggestion === itemKey; const isSelected = selectedSuggestionKeys.has(itemKey); return <article key={`${suggestion.asset_type}-${suggestion.name}-${index}`} className={`rounded-lg border p-3 transition ${isSelected ? 'border-indigo-300 bg-indigo-50/50 ring-1 ring-indigo-100' : 'border-slate-200 bg-slate-50'}`}>
                <div className="flex items-start gap-3"><input type="checkbox" checked={isSelected} onChange={() => toggleSuggestionSelection(itemKey)} disabled={batchTaskActive || batchSubmitting} aria-label={`选择${suggestion.name}`} className="mt-0.5 h-4 w-4 shrink-0 accent-indigo-600 disabled:opacity-50" /><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-sm font-semibold text-slate-800">{suggestion.name}</p><p className="mt-1 text-xs leading-5 text-slate-600">{suggestion.description || '暂无细节描述'}</p></div><span className="shrink-0 rounded bg-white px-2 py-1 text-[11px] text-slate-500">{assetTypeLabel[suggestion.asset_type]}</span></div>
                {suggestion.evidence && <p className="mt-2 border-l-2 border-indigo-200 pl-2 text-xs leading-5 text-slate-500">依据：{suggestion.evidence}</p>}
                <label className="mt-3 block text-xs font-medium text-slate-700">设定图提示词<span className="ml-1 font-normal text-slate-400">可直接编辑</span><textarea value={suggestion.prompt} onChange={(event) => updateSuggestionPrompt(index, event.target.value)} className="mt-1 min-h-36 w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 font-normal leading-5 text-slate-700 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" placeholder="填写用于生成角色、场景或道具设定图的完整提示词" /></label>
                <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => void generateSuggestionAsset(suggestion, index)} disabled={!suggestion.prompt.trim() || generatingSuggestion !== null || batchTaskActive || batchSubmitting} className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">{isGenerating ? <Loader2 size={12} className="animate-spin" /> : <ImageIcon size={12} />}{isGenerating ? '生成中...' : '生成资产图'}</button>{suggestion.candidates.map((candidate) => <button key={candidate.id} type="button" onClick={() => void bindSuggestion(suggestion, candidate)} disabled={bindingBusy || generatingSuggestion !== null || batchTaskActive} title={candidate.match_reason} className="inline-flex max-w-full items-center gap-1 rounded-md border border-indigo-200 bg-white px-2 py-1 text-xs text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"><Check size={12} /><span className="truncate">绑定“{candidate.name}”</span></button>)}<button type="button" onClick={() => openUploadForSuggestion(suggestion)} disabled={generatingSuggestion !== null || batchTaskActive} className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-50"><Upload size={12} />上传设定图</button></div></div></div>
              </article>; })}
            </div>}
          </section>}
          {loading ? <div className="flex justify-center py-16"><Loader2 className="animate-spin text-slate-400" size={26} /></div> : filteredAssets.length === 0 ? (
            <div className="flex min-h-72 flex-col items-center justify-center text-center text-slate-400">
              <ImageIcon size={48} className="mb-4 opacity-50" />
              <p className="font-medium text-slate-500">暂无{activeTab === 'all' ? '' : tabs.find((tab) => tab.key === activeTab)?.label}资产</p>
              <p className="mt-1 text-sm">上传角色、场景、道具或风格图片，建立漫画的一致性参考。</p>
            </div>
          ) : <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {filteredAssets.map((asset) => {
              const binding = getBinding(asset.id);
              const imageUrl = assetImageUrl(asset);
              const isEditing = editingId === asset.id;
              return <article key={asset.id} className={`group relative overflow-hidden rounded-xl border bg-white transition-shadow hover:shadow-md ${binding ? 'border-indigo-300 ring-1 ring-indigo-100' : 'border-slate-200'}`}>
                <div className="relative aspect-square bg-slate-100">
                  {imageUrl ? <button type="button" onClick={() => setWorkbenchAsset(asset)} className="block h-full w-full cursor-zoom-in" aria-label={`打开${asset.name}图片工作台`} title="查看与重绘"><img src={imageUrl} alt={asset.name} className="h-full w-full object-cover" loading="lazy" /></button> : <div className="flex h-full items-center justify-center text-slate-300"><ImageIcon size={32} /></div>}
                  <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 bg-black/0 opacity-0 transition group-hover:bg-black/40 group-hover:opacity-100">
                    <button type="button" onClick={() => { setEditingId(asset.id); setEditingName(asset.name); setEditingLabel(binding?.label ?? asset.name); }} className="pointer-events-auto rounded-full bg-white p-2 text-slate-700 shadow-lg hover:bg-slate-100" title="编辑"><Edit3 size={14} /></button>
                    <button type="button" onClick={() => void removeAsset(asset)} disabled={deleting === asset.id} className="pointer-events-auto rounded-full bg-white p-2 text-red-600 shadow-lg hover:bg-red-50 disabled:opacity-50" title="删除">{deleting === asset.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}</button>
                  </div>
                  {binding && <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-indigo-600 px-2 py-1 text-[11px] font-medium text-white"><Check size={12} />本章已绑定</span>}
                </div>
                <div className="p-3">
                  {isEditing ? <div className="space-y-2"><input value={editingName} onChange={(event) => setEditingName(event.target.value)} className="w-full rounded border border-slate-300 px-2 py-1 text-sm outline-none focus:border-indigo-500" placeholder="资产名称" autoFocus /><input value={editingLabel} onChange={(event) => setEditingLabel(event.target.value)} className="w-full rounded border border-slate-300 px-2 py-1 text-xs outline-none focus:border-indigo-500" placeholder="分镜匹配名称，例如角色名" /><div className="flex justify-end gap-1"><button type="button" onClick={() => setEditingId(null)} className="rounded p-1 text-xs text-slate-500 hover:bg-slate-100">取消</button><button type="button" onClick={() => void saveAssetEdit(asset)} disabled={bindingBusy} className="rounded p-1 text-indigo-600 hover:bg-indigo-50 disabled:opacity-50"><Save size={15} /></button></div></div> : <><p className="truncate text-sm font-medium text-slate-800">{asset.name}</p><p className="mt-1 truncate text-xs text-slate-400">{assetTypeLabel[asset.asset_type]}{binding?.label ? ` · ${binding.label}` : ''}</p><button type="button" onClick={() => void toggleBinding(asset)} disabled={bindingBusy} className={`mt-3 flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium transition ${binding ? 'bg-indigo-50 text-indigo-700 hover:bg-indigo-100' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'} disabled:opacity-50`}>{saving === asset.id ? <Loader2 size={13} className="animate-spin" /> : binding ? <Check size={13} /> : null}{binding ? '已绑定到本章' : '绑定到本章'}</button>{binding && <button type="button" onClick={() => void toggleRequiredBinding(asset)} disabled={bindingBusy} className={`mt-2 flex w-full items-center justify-center gap-1 rounded-md border px-2 py-1.5 text-xs font-medium transition ${binding.is_required ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'} disabled:opacity-50`} title="固定后每个分镜都会携带该参考图"><Pin size={12} />{binding.is_required ? '已全章固定' : '全章固定'}</button>}</>}
                </div>
              </article>;
            })}
          </div>}
        </div>
      </section>

      {uploadOpen && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4" onClick={resetUpload}>
        <section className="w-[min(500px,95vw)] rounded-2xl bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-label="上传漫画资产">
          <div className="mb-4 flex items-center justify-between"><h3 className="text-lg font-semibold text-slate-900">上传漫画资产</h3><button type="button" onClick={resetUpload} className="rounded-full p-1.5 text-slate-500 hover:bg-slate-100"><X size={17} /></button></div>
          <button type="button" onClick={() => fileInputRef.current?.click()} className="flex min-h-44 w-full items-center justify-center overflow-hidden rounded-xl border-2 border-dashed border-slate-300 p-4 transition hover:border-indigo-400">
            {uploadPreview ? <img src={uploadPreview} alt="上传预览" className="max-h-44 rounded-lg object-contain" /> : <span className="text-center text-sm text-slate-500"><Upload size={38} className="mx-auto mb-2 text-slate-300" />点击选择 JPG、PNG 或 WebP 图片</span>}
          </button>
          <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; setUploadFile(file); if (!uploadName.trim()) setUploadName(file.name.replace(/\.[^/.]+$/, '')); const reader = new FileReader(); reader.onload = () => setUploadPreview(String(reader.result)); reader.readAsDataURL(file); }} />
          <label className="mt-4 block text-sm font-medium text-slate-700">资产名称<input value={uploadName} onChange={(event) => setUploadName(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal outline-none focus:border-indigo-500" placeholder="例如：林晚秋正面设定" /></label>
          <label className="mt-4 block text-sm font-medium text-slate-700">资产类型<select value={uploadType} onChange={(event) => setUploadType(event.target.value as MangaAssetType)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal outline-none focus:border-indigo-500"><option value="character_reference">角色参考</option><option value="scene_reference">场景参考</option><option value="prop_reference">道具参考</option><option value="style_reference">风格参考</option></select></label>
          <label className="mt-4 block text-sm font-medium text-slate-700">分镜匹配名称<span className="ml-1 font-normal text-slate-400">可选</span><input value={uploadLabel} onChange={(event) => setUploadLabel(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal outline-none focus:border-indigo-500" placeholder="例如：林晚秋、旧城区咖啡馆、银色怀表" /></label>
          <div className="mt-6 flex justify-end gap-3"><button type="button" onClick={resetUpload} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100">取消</button><button type="button" onClick={() => void handleUpload()} disabled={!uploadFile || !uploadName.trim() || uploading} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">{uploading && <Loader2 size={14} className="animate-spin" />}{uploading ? '上传中' : '上传并绑定'}</button></div>
        </section>
      </div>}
      {workbenchAsset && <ImageRedrawModal
        imageSrc={assetImageUrl(workbenchAsset)}
        title={`${workbenchAsset.name} · 图片工作台`}
        prompt={assetPrompt(workbenchAsset)}
        busy={redrawingAssetId === workbenchAsset.id}
        onClose={() => setWorkbenchAsset(null)}
        onSubmit={handleAssetRedraw}
        zIndexClassName="z-[90]"
      />}
    </div>,
    document.body,
  );
}
