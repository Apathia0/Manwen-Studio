import { Image as ImageIcon, Images, Loader2, Maximize2, Send, SlidersHorizontal, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toPublicVideoAssetUrl, type AiModelItem, type VideoAsset } from '../../api';
import type { CanvasSceneNode } from './CanvasEditorSurface';
import MediaImage from '../shared/MediaImage';

interface Props {
  node: CanvasSceneNode;
  assets: VideoAsset[];
  models: AiModelItem[];
  left: number;
  top: number;
  onChange: (key: string, value: unknown) => void;
  onAssetChange: (assetId: number | null) => void;
  onOpenAssetSelector?: () => void;
  onOpenStyleSelector?: () => void;
  onGenerate: () => void;
  isGenerating?: boolean;
  isUploading?: boolean;
  onUploadReference?: (kind: 'image') => void;
}

type ReferenceKind = 'image';
type ReferencePreview = { assetId: number; url: string; kind: ReferenceKind };

const IMAGE_RATIOS = ['1:1', '4:3', '3:4', '16:9', '9:16'];

function isVideoNode(type: string): boolean { return type === 'video' || type === 'video_generation' || type === 'video_asset'; }
function isAssetNode(type: string): boolean { return type === 'asset' || type === 'video_asset'; }
function isMediaNode(type: string): boolean { return ['image', 'video', 'image_generation', 'storyboard', 'video_generation', 'asset', 'video_asset'].includes(type); }
function supportsReferenceAsset(type: string): boolean { return isMediaNode(type) || type === 'shot'; }

function HighlightedPrompt({ value }: { value: string }) {
  return <>{value.split(/(@(?:图片|视频|音频)\d+)/g).map((part, index) => /^@(?:图片|视频|音频)\d+$/.test(part)
    ? <span key={`${part}-${index}`} className="text-[#4d97ff]">{part}</span>
    : <span key={index}>{part}</span>)}</>;
}

export default function CanvasNodePropertyPanel({ node, assets, models, left, top, onChange, onOpenAssetSelector, onOpenStyleSelector, onGenerate, isGenerating = false, isUploading = false, onUploadReference }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [videoSettingsOpen, setVideoSettingsOpen] = useState(false);
  const config = node.data.config || {};
  const video = isVideoNode(node.type);
  const media = isMediaNode(node.type);
  const promptKey = node.type === 'shot' ? 'video_prompt' : ['text', 'screenplay', 'note'].includes(node.type) ? 'content' : 'prompt';
  const availableModels = useMemo(() => models.filter((model) => model.modality === (video ? 'video' : 'image')), [models, video]);
  const selectedModel = String(config.model_id || '');
  const selectedVideoModel = availableModels.find((model) => model.id === Number(config.model_id));
  const videoLimits = selectedVideoModel?.video_capabilities?.limits;
  const videoSize = String(config.size || '720P');
  const videoRatio = String(config.aspect_ratio || '16:9');
  const videoDuration = Number(config.duration_seconds || 6);
  const videoSizes = videoLimits?.resolutions?.length ? videoLimits.resolutions : ['480P', '720P', '1080P'];
  const videoRatios = videoLimits?.aspect_ratios?.length ? videoLimits.aspect_ratios : ['16:9', '9:16', '1:1', '4:3', '3:4'];
  const videoDurations = videoLimits?.duration_seconds?.allowed?.length ? videoLimits.duration_seconds.allowed : [4, 6, 8, 15];
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
  const appendMediaMention = (index: number) => {
    const label = '图片';
    const current = String(config[promptKey] || '');
    onChange(promptKey, `${current}${current ? ' ' : ''}@${label}${index + 1}`);
  };
  const previews = (kind: ReferenceKind) => referencePreviews.filter((item) => item.kind === kind);
  const panelWidth = expanded ? 860 : 820;
  const placeholder = node.type === 'text' ? '输入剧本、镜头说明或旁白' : video ? '描述要生成的视频内容' : '描述要生成的图片内容';
  const inputClass = 'rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] outline-none hover:border-[#77706a]';
  const selectedStyleName = String((config.style_snapshot as Record<string, unknown> | null)?.name || (config.style_reference_asset_id ? '自定义风格参考' : '系统默认风格'));
  const updateVideoSetting = (key: 'size' | 'aspect_ratio' | 'duration_seconds', value: string | number) => {
    onChange(key, value);
    setVideoSettingsOpen(false);
  };

  return <section onPointerDown={(event) => event.stopPropagation()} className="pointer-events-auto absolute z-30 rounded-2xl border border-[#49433f] bg-[#242220] p-5 text-[#d2ceca] shadow-[0_18px_45px_rgba(0,0,0,.38)]" style={{ left, top, width: `min(${panelWidth}px, calc(100vw - 32px))` }}>
    {media && onUploadReference && <div className="mb-4 flex items-start gap-3">
      {(['image'] as ReferenceKind[]).map((kind) => <div key={kind} className="flex flex-col gap-1.5"><span className="text-[11px] text-[#8f8984]">参考图</span><div className="flex gap-2">{previews(kind).map((preview, index) => <button key={preview.assetId} type="button" title={`引用图片${index + 1}`} onClick={() => appendMediaMention(index)} className="grid size-14 place-items-center overflow-hidden rounded-xl border border-[#56504b] bg-[#2a2826] transition hover:border-[#c9c1b9] hover:ring-2 hover:ring-white/20"><MediaImage src={preview.url} alt={`图片${index + 1}`} className="h-full w-full object-cover" /></button>)}<button type="button" title={isUploading ? '素材上传中' : '上传参考图'} disabled={isUploading} onClick={() => onUploadReference(kind)} className="grid size-14 place-items-center rounded-xl border border-dashed border-[#56504b] bg-[#2a2826] text-[#aaa19a] hover:border-[#8a8179] hover:text-white disabled:cursor-wait disabled:opacity-60">{isUploading ? <Loader2 className="h-5 w-5 animate-spin" /> : <ImageIcon className="h-5 w-5" />}</button></div></div>)}
    </div>}
    <div className="relative h-28 w-full"><div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[15px] leading-6 text-[#e1ddd9]"><HighlightedPrompt value={String(config[promptKey] || '')} /></div><textarea autoFocus value={String(config[promptKey] || '')} onChange={(event) => onChange(promptKey, event.target.value)} placeholder={placeholder} className="relative h-full w-full resize-none bg-transparent text-[15px] leading-6 text-transparent caret-[#e1ddd9] outline-none placeholder:text-[#88817b] selection:bg-[#4d97ff]/35" /></div>
    {expanded && <div className="mt-3 grid grid-cols-2 gap-3 border-t border-[#3b3734] pt-3">{node.type === 'shot' && <><label className="text-xs text-[#8f8984]">镜头摘要<textarea value={String(config.story_summary || '')} onChange={(event) => onChange('story_summary', event.target.value)} className="mt-1 h-16 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none" /></label><label className="text-xs text-[#8f8984]">故事版提示词<textarea value={String(config.storyboard_prompt || '')} onChange={(event) => onChange('storyboard_prompt', event.target.value)} className="mt-1 h-16 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none" /></label></>}</div>}
    <div className="mt-4 flex items-center gap-2 border-t border-[#3b3734] pt-3"><button type="button" title="展开高级配置" onClick={() => setExpanded((value) => !value)} className={`rounded-lg p-2 hover:bg-white/10 ${expanded ? 'text-white' : 'text-[#9a938d]'}`}><Maximize2 className="h-4 w-4" /></button><div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{media && <select value={selectedModel} onChange={(event) => { const model = availableModels.find((item) => item.id === Number(event.target.value)); onChange('model_id', model?.id || null); onChange('model', model?.model_key || ''); }} className={`${inputClass} min-w-0 max-w-full flex-1 basis-40`}><option value="">使用系统默认模型</option>{availableModels.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}</select>}{media && <button type="button" title="选择系统风格预设或上传风格参考图" onClick={onOpenStyleSelector} className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] hover:border-[#dfbf88] hover:bg-[#34312f]"><Sparkles className="h-3.5 w-3.5 shrink-0 text-[#dfbf88]" /><span className="truncate">{selectedStyleName}</span></button>}{video ? <div className="relative"><button type="button" title="视频设置" aria-expanded={videoSettingsOpen} onClick={() => setVideoSettingsOpen((value) => !value)} className="inline-flex items-center gap-1.5 rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] hover:border-[#77706a] hover:bg-[#34312f]"><SlidersHorizontal className="h-3.5 w-3.5 text-[#aaa19a]" />{videoSize} · {videoRatio} · {videoDuration}s</button>{videoSettingsOpen && <div onPointerDown={(event) => event.stopPropagation()} className="absolute bottom-11 left-0 z-50 w-[320px] rounded-xl border border-[#56504b] bg-[#242220] p-4 shadow-[0_18px_45px_rgba(0,0,0,.45)]"><p className="mb-3 text-sm font-medium text-[#e1ddd9]">视频设置</p><div className="space-y-4"><div><p className="mb-2 text-[11px] text-[#99918b]">清晰度</p><div className="grid grid-cols-3 gap-2">{videoSizes.map((size) => <button key={size} type="button" onClick={() => updateVideoSetting('size', size)} className={`h-9 rounded-full border text-xs transition ${videoSize === size ? 'border-white bg-white/10 text-white' : 'border-[#4a4541] text-[#b6afa9] hover:border-[#77706a] hover:text-white'}`}>{size}</button>)}</div></div><div><p className="mb-2 text-[11px] text-[#99918b]">画面比例</p><div className="grid grid-cols-3 gap-2">{videoRatios.map((ratio) => <button key={ratio} type="button" onClick={() => updateVideoSetting('aspect_ratio', ratio)} className={`h-14 rounded-lg border text-xs transition ${videoRatio === ratio ? 'border-white bg-white/10 text-white' : 'border-[#4a4541] text-[#b6afa9] hover:border-[#77706a] hover:text-white'}`}><span className="block text-sm">{ratio}</span><span className="mt-0.5 block text-[10px] text-[#8f8984]">{ratio === '16:9' ? '横屏' : ratio === '9:16' ? '竖屏' : ratio === '1:1' ? '方形' : '画幅'}</span></button>)}</div></div><div><p className="mb-2 text-[11px] text-[#99918b]">秒数</p><div className="grid grid-cols-3 gap-2">{videoDurations.map((duration) => <button key={duration} type="button" onClick={() => updateVideoSetting('duration_seconds', duration)} className={`h-9 rounded-full border text-xs transition ${videoDuration === duration ? 'border-white bg-white/10 text-white' : 'border-[#4a4541] text-[#b6afa9] hover:border-[#77706a] hover:text-white'}`}>{duration}s</button>)}</div></div></div></div>}</div> : <><select value={String(config.aspect_ratio || '1:1')} onChange={(event) => onChange('aspect_ratio', event.target.value)} className={`${inputClass}`}>{IMAGE_RATIOS.map((ratio) => <option key={ratio}>{ratio}</option>)}</select><select value={String(config.image_count || 1)} onChange={(event) => onChange('image_count', Number(event.target.value))} className={inputClass}><option value="1">1 张</option><option value="2">2 张</option><option value="3">3 张</option><option value="4">4 张</option></select></>}{supportsReferenceAsset(node.type) && <button type="button" title="打开资产管理并选择参考资产" onClick={onOpenAssetSelector} className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] hover:border-[#77706a] hover:bg-[#34312f]"><span className="flex -space-x-1.5">{selectedAssets.slice(0, 3).map((asset) => <MediaImage key={asset.id} src={toPublicVideoAssetUrl(asset.file_path) || ''} alt="" className="h-5 w-5 rounded-full border border-[#2a2826] object-cover" />)}{selectedAssets.length === 0 && <Images className="h-4 w-4 text-[#aaa19a]" />}</span><span className="truncate">{selectedAssets.length ? `${selectedAssets.length} 个参考资产` : '选择参考资产'}</span></button>}</div><button type="button" title={isGenerating ? '正在提交生成任务' : '发送生成'} disabled={isGenerating} onClick={onGenerate} className="flex h-10 w-14 shrink-0 items-center justify-center rounded-full bg-[#3a3835] text-[#9e9892] hover:bg-[#4a4743] hover:text-white disabled:cursor-wait disabled:opacity-60">{isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button></div>
    {Boolean(node.data.config?.style_snapshot) && <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-[#8e8882]"><Sparkles className="h-3 w-3" />已绑定风格快照</div>}
  </section>;
}
