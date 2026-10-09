import { Image as ImageIcon, Loader2, Maximize2, Plus, Send, SlidersHorizontal, Sparkles, Square, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { toPublicVideoAssetUrl, type AiModelItem, type VideoAsset } from '../../api';
import type { CanvasSceneNode } from './CanvasEditorSurface';
import MediaImage from '../shared/MediaImage';
import type { CanvasReferenceCandidate } from './canvasReferenceSync';

interface Props {
  node: CanvasSceneNode;
  assets: VideoAsset[];
  models: AiModelItem[];
  left: number;
  top: number;
  /** 传入后改为底部锚定（聚焦模式：输入框固定在画布底部居中，自身增高不遮挡工具栏） */
  bottom?: number;
  onChange: (key: string, value: unknown) => void;
  onAssetChange: (assetId: number | null) => void;
  onOpenStyleSelector?: () => void;
  onGenerate: () => void;
  isGenerating?: boolean;
  /** 发送键左侧的内容（积分预估） */
  costSlot?: ReactNode;
  /** 节点已有结果：发送键的含义是“重新生成”（旧结果保留在候选里），提示文案相应变化 */
  regenerates?: boolean;
  /** 生成中且任务可取消时传入：发送按钮变成停止按钮 */
  onStop?: () => void;
  isUploading?: boolean;
  onUploadReference?: (kind: 'image') => void;
  maxWidth?: number;
  connectedPreviews?: Array<{ key: string; label: string; url: string; nodeId?: string }>;
  /** 画布上已有图片、可一键连成参考图的节点 */
  referenceCandidates?: CanvasReferenceCandidate[];
  onConnectReference?: (nodeId: string) => void;
  onDisconnectReference?: (nodeId: string) => void;
  /** 面板底部操作行之前的扩展区（如候选结果） */
  footer?: ReactNode;
}

type ReferenceKind = 'image';
type ReferencePreview = { assetId: number; url: string; kind: ReferenceKind };

const IMAGE_RATIOS = ['1:1', '4:3', '3:4', '16:9', '9:16'];

function isVideoNode(type: string): boolean { return type === 'video' || type === 'video_generation' || type === 'video_asset'; }
function isAssetNode(type: string): boolean { return type === 'asset' || type === 'video_asset'; }
function isMediaNode(type: string): boolean { return ['image', 'video', 'image_generation', 'storyboard', 'video_generation', 'asset', 'video_asset'].includes(type); }


function HighlightedPrompt({ value }: { value: string }) {
  return <>{value.split(/(@(?:图片|视频|音频)\d+)/g).map((part, index) => /^@(?:图片|视频|音频)\d+$/.test(part)
    ? <span key={`${part}-${index}`} className="text-[#4d97ff]">{part}</span>
    : <span key={index}>{part}</span>)}</>;
}

function computeVideoSettingsStyle(anchor: { left: number; top: number; bottom: number }): CSSProperties {
  const spaceAbove = anchor.top - 16;
  const spaceBelow = window.innerHeight - anchor.bottom - 16;
  const preferAbove = spaceAbove >= 300 || spaceAbove >= spaceBelow;
  const width = Math.min(320, window.innerWidth - 48);
  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8));
  return preferAbove
    ? { position: 'fixed', left, bottom: window.innerHeight - anchor.top + 10 }
    : { position: 'fixed', left, top: anchor.bottom + 10 };
}
export default function CanvasNodePropertyPanel({ node, assets, models, left, top, bottom, maxWidth = 860, connectedPreviews = [], referenceCandidates = [], onConnectReference, onDisconnectReference, footer, onChange, onOpenStyleSelector, onGenerate, regenerates = false, costSlot, onStop, isGenerating = false, isUploading = false, onUploadReference }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  // 提示词文字画在叠层里（用来高亮 @图片1），输入框自己滚动时叠层必须同步，否则拖滚动条内容不动。
  const promptOverlayRef = useRef<HTMLDivElement>(null);
  const [videoSettingsOpen, setVideoSettingsOpen] = useState(false);
  const videoSettingsButtonRef = useRef<HTMLButtonElement>(null);
  const [videoSettingsAnchor, setVideoSettingsAnchor] = useState<{ left: number; top: number; bottom: number } | null>(null);
  useEffect(() => {
    if (!videoSettingsOpen) return;
    const sync = () => {
      const rect = videoSettingsButtonRef.current?.getBoundingClientRect();
      if (rect) setVideoSettingsAnchor({ left: rect.left, top: rect.top, bottom: rect.bottom });
    };
    window.addEventListener('scroll', sync, true);
    window.addEventListener('resize', sync);
    return () => {
      window.removeEventListener('scroll', sync, true);
      window.removeEventListener('resize', sync);
    };
  }, [videoSettingsOpen]);
  const config = node.data.config || {};
  const video = isVideoNode(node.type);
  const media = isMediaNode(node.type);
  const promptKey = node.type === 'shot' ? 'video_prompt' : ['text', 'screenplay', 'note'].includes(node.type) ? 'content' : 'prompt';
  const availableModels = useMemo(() => models.filter((model) => model.modality === (video ? 'video' : 'image')), [models, video]);
  const selectedModel = String(config.model_id || '');
  // 视频节点默认“自动推荐”：运行时按这个镜头的时长 / 画幅 / 参考图数量选合适的视频模型；用户手动选过就固定
  const autoModel = Boolean(config.model_auto);
  const selectedVideoModel = availableModels.find((model) => model.id === Number(config.model_id));
  const videoLimits = selectedVideoModel?.video_capabilities?.limits;
  const videoSize = String(config.size || '720P');
  const videoRatio = String(config.aspect_ratio || '16:9');
  const videoDuration = Number(config.duration_seconds || 6);
  const videoSizes = videoLimits?.resolutions?.length ? videoLimits.resolutions : ['480P', '720P', '1080P'];
  const videoRatios = videoLimits?.aspect_ratios?.length ? videoLimits.aspect_ratios : ['16:9', '9:16', '1:1', '4:3', '3:4'];
  // 模型可以声明离散档位（allowed），也可以只声明连续区间（min / max，如 4 到 15 秒：每个整数秒都能选）。
  const videoDurations = (() => {
    if (autoModel || !selectedVideoModel) return Array.from({ length: 12 }, (_, index) => 4 + index);
    const spec = videoLimits?.duration_seconds;
    if (spec?.allowed?.length) return spec.allowed;
    const low = Number(spec?.min);
    const high = Number(spec?.max);
    if (Number.isFinite(low) && Number.isFinite(high) && low >= 1 && high >= low) {
      return Array.from({ length: Math.min(60, Math.floor(high) - Math.ceil(low) + 1) }, (_, index) => Math.ceil(low) + index);
    }
    return [4, 6, 8, 15];
  })();
  const selectableAssets = assets.filter((asset) => !/video|clip|final|audio/i.test(asset.asset_type || '') && !/\.(mp4|mov|webm|mkv|mp3|wav|m4a|aac|ogg)$/i.test(asset.file_path || ''));
  const selectedAssetIds = isAssetNode(node.type) ? (config.asset_id ? [Number(config.asset_id)] : []) : (Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number).filter(Number.isFinite) : []);
  const selectedAssets = selectedAssetIds.map((id) => selectableAssets.find((asset) => asset.id === id)).filter((asset): asset is VideoAsset => Boolean(asset));
  const referencePreviews = useMemo<ReferencePreview[]>(() => {
    const byId = new Map<number, ReferencePreview>();
    const stored = Array.isArray(config.reference_previews) ? config.reference_previews : [];
    stored.forEach((item) => {
      if (!item || typeof item !== 'object') return;
      const value = item as Record<string, unknown>;
      const assetId = Number(value.asset_id);
      const url = String(value.url || '');
      const kind = value.kind;
      if (Number.isFinite(assetId) && url && kind === 'image') byId.set(assetId, { assetId, url, kind });
    });
    selectedAssets.forEach((asset) => {
      if (byId.has(asset.id)) return;
      const kind: ReferenceKind = 'image';
      const url = toPublicVideoAssetUrl(asset.file_path) || '';
      if (url) byId.set(asset.id, { assetId: asset.id, url, kind });
    });
    return selectedAssetIds.map((id) => byId.get(id)).filter((item): item is ReferencePreview => Boolean(item));
  }, [config.reference_previews, selectedAssetIds, selectedAssets]);
  // 点缩略图在提示词里插入 @图片N：插在光标处（没点过输入框就接在末尾），前后留空格，插完回到输入框并把光标放在引用后面。
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const caretTouchedRef = useRef(false);
  const appendMediaMention = (index: number) => {
    const token = `@图片${index + 1}`;
    const current = String(config[promptKey] || '');
    const textarea = promptRef.current;
    const at = textarea && caretTouchedRef.current ? Math.min(textarea.selectionStart ?? current.length, current.length) : current.length;
    const before = current.slice(0, at);
    const after = current.slice(at);
    const lead = before && !/\s$/.test(before) ? ' ' : '';
    const tail = after && !/^\s/.test(after) ? ' ' : '';
    const next = `${before}${lead}${token}${tail}${after}`;
    onChange(promptKey, next);
    const caret = before.length + lead.length + token.length + (tail ? 1 : 0);
    window.requestAnimationFrame(() => { textarea?.focus(); textarea?.setSelectionRange(caret, caret); caretTouchedRef.current = true; });
  };
  // 退格 / 删除键碰到 @图片N 引用时整体删除（连同一侧多余的空格），不会只吃掉引用的一个字符或前面的文字。
  const handlePromptKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Backspace' && event.key !== 'Delete') return;
    const textarea = event.currentTarget;
    if (textarea.selectionStart !== textarea.selectionEnd) return;
    const value = textarea.value;
    const caret = textarea.selectionStart;
    for (const match of value.matchAll(/@(?:图片|视频|音频)\d+/g)) {
      const start = match.index ?? 0;
      const end = start + match[0].length;
      const hit = event.key === 'Backspace' ? caret > start && caret <= end : caret >= start && caret < end;
      if (!hit) continue;
      event.preventDefault();
      let from = start;
      let to = end;
      if (value[to] === ' ') to += 1;
      else if (from > 0 && value[from - 1] === ' ') from -= 1;
      onChange(promptKey, value.slice(0, from) + value.slice(to));
      window.requestAnimationFrame(() => textarea.setSelectionRange(from, from));
      return;
    }
  };
  const previews = (kind: ReferenceKind) => referencePreviews.filter((item) => item.kind === kind);
  const assetImagePreviews = previews('image');
  const assetUrls = new Set(assetImagePreviews.map((item) => item.url));
  const connectedImages = connectedPreviews.filter((item) => item.url && !assetUrls.has(item.url));
  // 连线参考排在最前：与运行时“先边输入、后配置参考”的输入顺序一致，@图片N 引用才能对上。
  const imageThumbnailList = [
    ...connectedImages.map((item) => ({ key: item.key, url: item.url, title: `${item.label}（点击插入 @ 引用）`, connected: true, nodeId: item.nodeId, assetId: undefined as number | undefined })),
    // 配置里的参考素材和连线是同一张图时（连线会自动同步进配置），缩略图要认出它背后的那条连线：
    // 点 × 删的是连线；只删配置的话，同步逻辑下一次又会按连线把它加回来。
    ...assetImagePreviews.map((item, index) => {
      const viaEdge = connectedPreviews.find((preview) => preview.url === item.url && preview.nodeId);
      return { key: `asset-${item.assetId}`, url: item.url, title: viaEdge ? `${viaEdge.label}（点击插入 @ 引用）` : `引用图片${connectedImages.length + index + 1}`, connected: Boolean(viaEdge), nodeId: viaEdge?.nodeId as string | undefined, assetId: item.assetId as number | undefined };
    }),
  ];
  const panelWidth = expanded ? 860 : 820;
  const removeReference = (preview: { nodeId?: string; assetId?: number }) => {
    if (preview.nodeId) onDisconnectReference?.(preview.nodeId);
    else if (preview.assetId !== undefined) onChange('reference_asset_ids', selectedAssetIds.filter((id) => id !== preview.assetId));
  };
  const candidateGroups = referenceCandidates.reduce<Record<string, CanvasReferenceCandidate[]>>((groups, item) => { (groups[item.group] ||= []).push(item); return groups; }, {});
  const placeholder = node.type === 'text' ? '输入剧本、镜头说明或旁白' : video ? '描述要生成的视频内容' : '描述要生成的图片内容';
  const selectedStyleName = String((config.style_snapshot as Record<string, unknown> | null)?.name || (config.style_reference_asset_id ? '自定义风格参考' : '跟随画布风格'));
  const updateVideoSetting = (key: 'size' | 'aspect_ratio' | 'duration_seconds', value: string | number) => {
    onChange(key, value);
    setVideoSettingsOpen(false);
  };
  const toggleVideoSettings = () => {
    if (videoSettingsOpen) {
      setVideoSettingsOpen(false);
      return;
    }
    const rect = videoSettingsButtonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setVideoSettingsAnchor({ left: rect.left, top: rect.top, bottom: rect.bottom });
    setVideoSettingsOpen(true);
  };

  return <section data-canvas-inspector onPointerDown={(event) => event.stopPropagation()} className="pointer-events-auto absolute z-30 flex max-h-[calc(100%-112px)] flex-col overflow-y-auto rounded-2xl border border-[#49433f] bg-[#242220] p-5 text-[#d2ceca] shadow-[0_18px_45px_rgba(0,0,0,.38)]" style={{ ...(bottom === undefined ? { left, top } : { left: '50%', bottom, transform: 'translateX(-50%)', maxHeight: '52%' }), width: `min(${panelWidth}px, ${maxWidth}px, calc(100% - 32px))` }}>
    {media && onUploadReference && <div className="mb-4 flex items-start gap-3">
      {(['image'] as ReferenceKind[]).map((kind) => <div key={kind} className="flex min-w-0 flex-1 flex-col gap-1.5"><span className="text-[11px] text-[#8f8984]">参考图 · 点缩略图在提示词里 @ 引用</span><div className="flex flex-wrap gap-2">{imageThumbnailList.map((preview, index) => <div key={preview.key} className="group relative"><button type="button" title={preview.title} onClick={() => appendMediaMention(index)} className="relative grid size-14 place-items-center overflow-hidden rounded-xl border border-[#56504b] bg-[#2a2826] transition hover:border-[#c9c1b9] hover:ring-2 hover:ring-white/20"><MediaImage src={preview.url} alt={`图片${index + 1}`} width={240} className="h-full w-full object-cover" />{preview.connected && <span className="absolute bottom-0 right-0 rounded-tl-md bg-black/70 px-1 text-[8px] leading-4 text-[#9ec5ff]">连线</span>}</button><button type="button" title="移除参考" aria-label="移除参考" onClick={() => removeReference(preview)} className="absolute -right-1.5 -top-1.5 hidden size-5 place-items-center rounded-full border border-[#56504b] bg-[#1d1b1a] text-[#d2ceca] hover:border-rose-400 hover:text-rose-300 group-hover:grid"><X className="h-3 w-3" /></button></div>)}<button type="button" title="添加参考图：从画布选择或上传" onClick={() => setPickerOpen((open) => !open)} className={`grid size-14 place-items-center rounded-xl border border-dashed bg-[#2a2826] hover:text-white ${pickerOpen ? 'border-[#73a7ff] text-white' : 'border-[#56504b] text-[#aaa19a] hover:border-[#8a8179]'}`}>{isUploading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Plus className="h-5 w-5" />}</button></div>{pickerOpen && <div className="rounded-xl border border-[#49433f] bg-[#1d1b1a] p-3"><div className="mb-2 flex items-center justify-between gap-2"><span className="text-[11px] text-[#8f8984]">从画布选择（点击即连线为参考）</span><button type="button" disabled={isUploading} onClick={() => onUploadReference(kind)} className="inline-flex h-7 items-center gap-1.5 rounded-full border border-[#4a4541] px-2.5 text-[11px] text-[#ded9d4] hover:border-[#77706a] disabled:opacity-60"><ImageIcon className="h-3.5 w-3.5" />上传图片</button></div>{referenceCandidates.length === 0 ? <p className="py-2 text-[11px] text-[#7d756e]">画布上还没有可用的图片。先生成角色 / 场景资产，或上传图片。</p> : <div className="max-h-44 space-y-2 overflow-y-auto pr-1">{Object.entries(candidateGroups).map(([group, items]) => <div key={group}><p className="mb-1 text-[11px] text-[#7d756e]">{group}</p><div className="flex flex-wrap gap-2">{items.map((item) => <button key={item.nodeId} type="button" title={item.label} onClick={() => onConnectReference?.(item.nodeId)} className="w-16 text-left"><span className="block size-16 overflow-hidden rounded-lg border border-[#56504b] hover:border-[#73a7ff]"><MediaImage src={item.url} alt={item.label} width={240} className="h-full w-full object-cover" /></span><span className="mt-0.5 block truncate text-[10px] text-[#a79f98]">{item.label}</span></button>)}</div></div>)}</div>}</div>}</div>)}
    </div>}
    <div className="relative h-28 w-full"><div ref={promptOverlayRef} aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[15px] leading-6 text-[#e1ddd9] [scrollbar-gutter:stable]"><HighlightedPrompt value={String(config[promptKey] || '')} /></div><textarea ref={promptRef} style={{ fontSize: 15, lineHeight: "24px" }} autoFocus value={String(config[promptKey] || '')} onChange={(event) => onChange(promptKey, event.target.value)} onKeyDown={handlePromptKeyDown} onClick={() => { caretTouchedRef.current = true; }} onKeyUp={() => { caretTouchedRef.current = true; }} placeholder={placeholder} onScroll={(event) => { if (promptOverlayRef.current) promptOverlayRef.current.scrollTop = event.currentTarget.scrollTop; }} className="relative h-full w-full resize-none bg-transparent text-[15px] leading-6 text-transparent caret-[#e1ddd9] outline-none placeholder:text-[#88817b] selection:bg-[#4d97ff]/35 [scrollbar-gutter:stable]" /></div>
    {expanded && <div className="mt-3 grid grid-cols-1 gap-3 border-t sm:grid-cols-2 border-[#3b3734] pt-3">{node.type === 'shot' && <><label className="text-xs text-[#8f8984]">镜头摘要<textarea value={String(config.story_summary || '')} onChange={(event) => onChange('story_summary', event.target.value)} className="mt-1 h-16 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none" /></label><label className="text-xs text-[#8f8984]">故事版提示词<textarea value={String(config.storyboard_prompt || '')} onChange={(event) => onChange('storyboard_prompt', event.target.value)} className="mt-1 h-16 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none" /></label></>}</div>}
    {footer}
    <div className="mt-4 flex items-center gap-2 border-t border-[#3b3734] pt-3"><button type="button" title="展开高级配置" onClick={() => setExpanded((value) => !value)} className={`rounded-lg p-2 hover:bg-white/10 ${expanded ? 'text-white' : 'text-[#9a938d]'}`}><Maximize2 className="h-4 w-4" /></button><div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{media && <select value={video && autoModel ? 'auto' : selectedModel} title={video ? '生成模型：默认自动推荐，会按这个镜头的时长选择合适的视频模型' : '生成模型'} onChange={(event) => { if (video && event.target.value === 'auto') { onChange('model_auto', true); return; } const model = availableModels.find((item) => item.id === Number(event.target.value)); if (video) onChange('model_auto', false); onChange('model_id', model?.id || null); onChange('model', model?.model_key || ''); }} className="h-8 w-36 max-w-full shrink-0 truncate rounded-full border border-[#4a4541] bg-[#2a2826] px-3 text-xs text-[#ded9d4] outline-none hover:border-[#77706a]">{video ? <option value="auto">自动推荐{autoModel && selectedVideoModel ? `（${selectedVideoModel.display_name}）` : ''}</option> : <option value="">默认模型</option>}{availableModels.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}</select>}{media && <button type="button" title="选择系统风格预设或上传风格参考图" onClick={onOpenStyleSelector} className="inline-flex h-8 min-w-0 max-w-[9rem] shrink-0 items-center gap-1.5 rounded-full border border-[#4a4541] bg-[#2a2826] px-3 text-xs text-[#ded9d4] hover:border-[#dfbf88] hover:bg-[#34312f]"><Sparkles className="h-3.5 w-3.5 shrink-0 text-[#dfbf88]" /><span className="truncate">{selectedStyleName}</span></button>}{video ? <div className="relative"><button ref={videoSettingsButtonRef} type="button" title="视频设置" aria-expanded={videoSettingsOpen} onClick={toggleVideoSettings} className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-[#4a4541] bg-[#2a2826] px-3 text-xs text-[#ded9d4] hover:border-[#77706a] hover:bg-[#34312f]"><SlidersHorizontal className="h-3.5 w-3.5 text-[#aaa19a]" />{videoSize} · {videoRatio} · {videoDuration}s</button>{videoSettingsOpen && videoSettingsAnchor && createPortal(<div onPointerDown={(event) => event.stopPropagation()} style={computeVideoSettingsStyle(videoSettingsAnchor)} className="z-50 w-[min(320px,calc(100vw-48px))] max-h-[min(420px,calc(100dvh-140px))] overflow-y-auto rounded-xl border border-[#56504b] bg-[#242220] p-4 shadow-[0_18px_45px_rgba(0,0,0,.45)]"><p className="mb-3 text-sm font-medium text-[#e1ddd9]">视频设置</p><div className="space-y-4"><div><p className="mb-2 text-[11px] text-[#99918b]">清晰度</p><div className="grid grid-cols-3 gap-2">{videoSizes.map((size) => <button key={size} type="button" onClick={() => updateVideoSetting('size', size)} className={`h-9 rounded-full border text-xs transition ${videoSize === size ? 'border-white bg-white/10 text-white' : 'border-[#4a4541] text-[#b6afa9] hover:border-[#77706a] hover:text-white'}`}>{size}</button>)}</div></div><div><p className="mb-2 text-[11px] text-[#99918b]">画面比例</p><div className="grid grid-cols-3 gap-2">{videoRatios.map((ratio) => <button key={ratio} type="button" onClick={() => updateVideoSetting('aspect_ratio', ratio)} className={`h-14 rounded-lg border text-xs transition ${videoRatio === ratio ? 'border-white bg-white/10 text-white' : 'border-[#4a4541] text-[#b6afa9] hover:border-[#77706a] hover:text-white'}`}><span className="block text-sm">{ratio}</span><span className="mt-0.5 block text-[10px] text-[#8f8984]">{ratio === '16:9' ? '横屏' : ratio === '9:16' ? '竖屏' : ratio === '1:1' ? '方形' : '画幅'}</span></button>)}</div></div><div><p className="mb-2 text-[11px] text-[#99918b]">秒数</p><div className="grid grid-cols-3 gap-2">{videoDurations.map((duration) => <button key={duration} type="button" onClick={() => updateVideoSetting('duration_seconds', duration)} className={`h-9 rounded-full border text-xs transition ${videoDuration === duration ? 'border-white bg-white/10 text-white' : 'border-[#4a4541] text-[#b6afa9] hover:border-[#77706a] hover:text-white'}`}>{duration}s</button>)}</div></div></div></div>, document.body)}</div> : <select value={String(config.aspect_ratio || '16:9')} title="画面比例" onChange={(event) => onChange('aspect_ratio', event.target.value)} className="h-8 w-24 shrink-0 rounded-full border border-[#4a4541] bg-[#2a2826] pl-3 pr-2 text-xs text-[#ded9d4] outline-none hover:border-[#77706a]">{IMAGE_RATIOS.map((ratio) => <option key={ratio}>{ratio}</option>)}</select>}</div><div className="flex shrink-0 items-center gap-2">{!isGenerating && costSlot}{isGenerating && onStop
      ? <button type="button" title="停止生成" aria-label="停止生成" onClick={onStop} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#e8e4df] text-[#24211f] hover:bg-white"><Square className="h-3.5 w-3.5 fill-current" /></button>
      : <button type="button" title={isGenerating ? '正在提交生成任务' : regenerates ? '重新生成（旧结果保留在候选里）' : '发送生成'} disabled={isGenerating} onClick={onGenerate} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#73a7ff] text-[#111827] hover:bg-[#8db6ff] disabled:cursor-wait disabled:opacity-60">{isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>}</div></div>
    {Boolean(node.data.config?.style_snapshot) && <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-[#8e8882]"><Sparkles className="h-3 w-3" />已绑定风格快照</div>}
  </section>;
}
