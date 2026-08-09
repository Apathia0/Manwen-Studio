import { Images, Maximize2, MessageSquareText, Send, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toPublicVideoAssetUrl, type AiModelItem, type VideoAsset, type VideoStylePreset } from '../../api';
import type { CanvasSceneNode } from './CanvasEditorSurface';

interface Props {
  node: CanvasSceneNode;
  assets: VideoAsset[];
  stylePresets: VideoStylePreset[];
  models: AiModelItem[];
  left: number;
  top: number;
  onChange: (key: string, value: unknown) => void;
  onAssetChange: (assetId: number | null) => void;
  onOpenAssetSelector?: () => void;
  onStyleChange: (styleId: number | null) => void;
  onTemplateSave?: () => void;
  onGenerate: () => void;
}

const IMAGE_RATIOS = ['1:1', '4:3', '3:4', '16:9', '9:16'];

function isVideoNode(type: string): boolean { return type === 'video' || type === 'video_generation' || type === 'video_asset'; }
function isAssetNode(type: string): boolean { return type === 'asset' || type === 'video_asset'; }
function isMediaNode(type: string): boolean { return ['image', 'video', 'image_generation', 'storyboard', 'video_generation', 'asset', 'video_asset'].includes(type); }
function supportsReferenceAsset(type: string): boolean { return isMediaNode(type) || type === 'shot'; }

export default function CanvasNodePropertyPanel({ node, assets, stylePresets, models, left, top, onChange, onOpenAssetSelector, onStyleChange, onTemplateSave, onGenerate }: Props) {
  const [expanded, setExpanded] = useState(false);
  const config = node.data.config || {};
  const video = isVideoNode(node.type);
  const media = isMediaNode(node.type);
  const promptKey = node.type === 'shot' ? 'video_prompt' : node.type === 'text' || node.type === 'screenplay' || node.type === 'note' ? 'content' : 'prompt';
  const availableModels = useMemo(() => models.filter((model) => model.modality === (video ? 'video' : 'image')), [models, video]);
  const selectedModel = String(config.model_id || '');
  const selectableAssets = isAssetNode(node.type) && video ? assets.filter((asset) => /video|clip|final/i.test(asset.asset_type || '') || /\.(mp4|mov|webm)$/i.test(asset.file_path || '')) : assets.filter((asset) => !/video|clip|final/i.test(asset.asset_type || '') && !/\.(mp4|mov|webm)$/i.test(asset.file_path || ''));
  const selectedAssetIds = isAssetNode(node.type) ? (config.asset_id ? [Number(config.asset_id)] : []) : (Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number).filter(Number.isFinite) : []);
  const selectedAssets = selectedAssetIds.map((id) => selectableAssets.find((asset) => asset.id === id)).filter((asset): asset is VideoAsset => Boolean(asset));
  const panelWidth = expanded ? 700 : 600;
  const placeholder = node.type === 'text' ? '输入剧本、镜头说明或旁白' : node.type === 'video' || video ? '描述要生成的视频内容' : '描述要生成的图片内容';
  return <section onPointerDown={(event) => event.stopPropagation()} className="pointer-events-auto absolute z-30 rounded-2xl border border-[#49433f] bg-[#242220] p-5 text-[#d2ceca] shadow-[0_18px_45px_rgba(0,0,0,.38)]" style={{ left, top, width: `min(${panelWidth}px, calc(100vw - 32px))` }}>
    <textarea autoFocus value={String(config[promptKey] || '')} onChange={(event) => onChange(promptKey, event.target.value)} placeholder={placeholder} className="h-28 w-full resize-none bg-transparent text-[15px] leading-6 text-[#e1ddd9] outline-none placeholder:text-[#88817b]" />
    {expanded && <div className="mt-3 grid grid-cols-2 gap-3 border-t border-[#3b3734] pt-3">
      {node.type === 'shot' && <>
        <label className="text-xs text-[#8f8984]">镜头摘要<textarea value={String(config.story_summary || '')} onChange={(event) => onChange('story_summary', event.target.value)} className="mt-1 h-16 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none" /></label>
        <label className="text-xs text-[#8f8984]">故事版提示词<textarea value={String(config.storyboard_prompt || '')} onChange={(event) => onChange('storyboard_prompt', event.target.value)} className="mt-1 h-16 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none" /></label>
      </>}
      {media && <label className="text-xs text-[#8f8984]">风格预设<select value={String(config.style_preset_id || '')} onChange={(event) => onStyleChange(event.target.value ? Number(event.target.value) : null)} className="mt-1 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none"><option value="">系统默认风格</option>{stylePresets.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}</select></label>}
      {media && <label className="text-xs text-[#8f8984]">模型<select value={selectedModel} onChange={(event) => { const model = availableModels.find((item) => item.id === Number(event.target.value)); onChange('model_id', model?.id || null); onChange('model', model?.model_key || ''); }} className="mt-1 w-full rounded-lg border border-[#4a4541] bg-[#1d1b1a] p-2 text-xs text-[#ded9d4] outline-none"><option value="">使用系统默认模型</option>{availableModels.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}</select></label>}
    </div>}
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <button type="button" title="展开高级配置" onClick={() => setExpanded((value) => !value)} className={`rounded-lg p-2 hover:bg-white/10 ${expanded ? 'text-white' : 'text-[#9a938d]'}`}><Maximize2 className="h-4 w-4" /></button>
      <button type="button" title="保存为提示词模板" onClick={onTemplateSave} className="rounded-lg p-2 text-[#9a938d] hover:bg-white/10 hover:text-white"><MessageSquareText className="h-4 w-4" /></button>
      {media && <select value={selectedModel} onChange={(event) => { const model = availableModels.find((item) => item.id === Number(event.target.value)); onChange('model_id', model?.id || null); onChange('model', model?.model_key || ''); }} className="max-w-[180px] rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] outline-none"><option value="">使用系统默认模型</option>{availableModels.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}</select>}
      {video ? <><select value={String(config.aspect_ratio || '16:9')} onChange={(event) => onChange('aspect_ratio', event.target.value)} className="rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] outline-none"><option>16:9</option><option>9:16</option><option>1:1</option></select><select value={String(config.duration_seconds || 6)} onChange={(event) => onChange('duration_seconds', Number(event.target.value))} className="rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] outline-none"><option value="4">720p · 4s</option><option value="6">720p · 6s</option><option value="8">720p · 8s</option><option value="15">720p · 15s</option></select></> : <><select value={String(config.aspect_ratio || '1:1')} onChange={(event) => onChange('aspect_ratio', event.target.value)} className="rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] outline-none">{IMAGE_RATIOS.map((ratio) => <option key={ratio}>{ratio}</option>)}</select><select value={String(config.image_count || 1)} onChange={(event) => onChange('image_count', Number(event.target.value))} className="rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] outline-none"><option value="1">1 张</option><option value="2">2 张</option><option value="3">3 张</option><option value="4">4 张</option></select></>}
      {supportsReferenceAsset(node.type) && <button type="button" title="打开资产管理并选择参考资产" onClick={onOpenAssetSelector} className="inline-flex min-w-0 max-w-[240px] items-center gap-2 rounded-full border border-[#4a4541] bg-[#2a2826] px-3 py-2 text-xs text-[#ded9d4] hover:border-[#77706a] hover:bg-[#34312f]"><span className="flex -space-x-1.5">{selectedAssets.slice(0, 3).map((asset) => <img key={asset.id} src={toPublicVideoAssetUrl(asset.file_path) || ''} alt="" className="h-5 w-5 rounded-full border border-[#2a2826] object-cover" />)}{selectedAssets.length === 0 && <Images className="h-4 w-4 text-[#aaa19a]" />}</span><span className="truncate">{selectedAssets.length ? `${selectedAssets.length} 个参考资产` : '选择参考资产'}</span></button>}
      <button type="button" title="发送生成" onClick={onGenerate} className="ml-auto flex h-10 w-14 items-center justify-center rounded-full bg-[#3a3835] text-[#9e9892] hover:bg-[#4a4743] hover:text-white"><Send className="h-4 w-4" /></button>
    </div>
    {Boolean(node.data.config?.style_snapshot) && <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-[#8e8882]"><Sparkles className="h-3 w-3" />已绑定风格快照</div>}
  </section>;
}
