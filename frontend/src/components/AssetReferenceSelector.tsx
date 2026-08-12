import { useState } from 'react';
import { X } from 'lucide-react';
import { toPublicVideoAssetUrl, type VideoAsset } from '../api';

function toAssetUrl(filePath?: string | null): string {
  return toPublicVideoAssetUrl(filePath) || '';
}

interface AssetReferenceSelectorProps {
  /** 可用资产列表 (本章节+跨章角色库) */
  availableAssets: VideoAsset[];
  /** 当前已选资产 ID 集合 */
  selectedIds: number[];
  /** 确认回调 */
  onConfirm: (selectedIds: number[]) => void;
  /** 关闭回调 */
  onClose: () => void;
  /** 额外的故事版图片（来自 shot 的 storyboard_image_url） */
  shotStoryboards?: Array<{ id: number; file_path: string; name: string }>;
  /** 系统推荐优先引用的资产 */
  recommendedIds?: number[];
}

type PresetKey = 'storyboard_and_chars' | 'chars_only' | 'all' | 'custom';

const PRESETS: { key: PresetKey; label: string; description: string }[] = [
  { key: 'storyboard_and_chars', label: '故事版+人物', description: '故事版分镜图 + 所有出场人物图' },
  { key: 'chars_only', label: '仅人物', description: '仅使用角色参考图' },
  { key: 'all', label: '全部资产', description: '使用本章所有已生成资产' },
  { key: 'custom', label: '自定义', description: '手动勾选需要的资产' },
];

/**
 * 参考资产选择弹窗
 *
 * 提供 4 种预设模板快速勾选 + 手动微调。
 * 用于分镜生成视频前指定哪些已生成资产作为参考。
 */
export default function AssetReferenceSelector({
  availableAssets,
  selectedIds,
  onConfirm,
  onClose,
  shotStoryboards,
  recommendedIds,
}: AssetReferenceSelectorProps) {
  const [currentPreset, setCurrentPreset] = useState<PresetKey>(
    selectedIds.length === 0 ? 'storyboard_and_chars' : 'custom'
  );
  const [checked, setChecked] = useState<Set<number>>(new Set(selectedIds));
  const [failedImages, setFailedImages] = useState<Set<number>>(new Set());

  const applyPreset = (key: PresetKey) => {
    setCurrentPreset(key);
    const allStoryboardIds = [...availableAssets.filter(a => a.asset_type === 'storyboard_frame' || a.asset_type === 'storyboard'), ...shotStoryboardAssets].map(a => a.id);
    if (key === 'storyboard_and_chars') {
      const ids = [...allStoryboardIds, ...availableAssets.filter(a => a.asset_type === 'character_reference' || a.asset_type === 'character').map(a => a.id)];
      setChecked(new Set(ids));
    } else if (key === 'chars_only') {
      const ids = availableAssets.filter(a =>
        a.asset_type === 'character_reference' || a.asset_type === 'character'
      ).map(a => a.id);
      setChecked(new Set(ids));
    } else if (key === 'all') {
      setChecked(new Set([...availableAssets.map(a => a.id), ...allStoryboardIds]));
    }
    // 'custom' 保持当前勾选不变
  };

  const getThumbLabel = (a: VideoAsset): string => {
    if (a.asset_type === 'storyboard_frame' || a.asset_type === 'storyboard') {
      const m = a.name.match(/分镜\s*(\d+)/);
      return m ? `分镜${m[1]}的故事版` : a.name || '故事版';
    }
    if (a.asset_type === 'character_reference' || a.asset_type === 'character') return a.name || '角色';
    if (a.asset_type === 'scene_reference' || a.asset_type === 'scene' || a.asset_type === 'background') return a.name || '场景';
    if (a.asset_type === 'prop_reference') return a.name || '道具';
    return a.name;
  };

  const toggle = (id: number) => {
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
    setCurrentPreset('custom');
  };

  const shotStoryboardAssets: VideoAsset[] = (shotStoryboards || []).map(s => ({
    id: s.id,
    story_id: 0,
    chapter_id: 0,
    scene_id: null,
    shot_id: 0,
    asset_type: 'storyboard_frame',
    name: s.name,
    file_path: s.file_path,
    provider: null,
    prompt: null,
    meta: {},
    created_at: '',
  } as unknown as VideoAsset));

  const categorized = {
    storyboard: [...availableAssets.filter(a => a.asset_type === 'storyboard_frame' || a.asset_type === 'storyboard'), ...shotStoryboardAssets],
    characters: availableAssets.filter(a => (a.asset_type === 'character_reference' || a.asset_type === 'character')),
    scene: availableAssets.filter(a => (a.asset_type === 'scene_reference' || a.asset_type === 'scene' || a.asset_type === 'background')),
    props: availableAssets.filter(a => a.asset_type === 'prop_reference'),
    frames: availableAssets.filter(a => a.asset_type === 'first_frame' || a.asset_type === 'last_frame'),
    uploads: availableAssets.filter(a => ['image', 'video', 'audio'].includes(a.asset_type)),
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[rgba(15,23,42,0.5)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-[85vh] w-[min(1200px,90vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#e5edf8]">
          <div>
            <div className="text-base font-semibold text-slate-900">选择参考资产</div>
            <div className="text-xs text-slate-500">已选 {checked.size} 个资产</div>
          </div>
          <button onClick={onClose} className="rounded-full p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100">
            <X size={16} />
          </button>
        </div>

        {/* 预设模板 */}
        <div className="px-5 py-3 border-b border-[#e5edf8]">
          <div className="text-xs font-medium text-slate-500 mb-2">快速选择</div>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map(p => (
              <button
                key={p.key}
                onClick={() => applyPreset(p.key)}
                className={`px-3 py-1.5 rounded-lg text-xs transition ${
                  currentPreset === p.key
                    ? 'bg-[#2563eb] text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
                title={p.description}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* 资产列表 */}
        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-4">
          {([
            ['分镜图 (故事版)', categorized.storyboard],
            ['人物图 (角色参考)', categorized.characters],
            ['场景图', categorized.scene],
            ['道具图', categorized.props],
            ['本地上传媒体', categorized.uploads],
          ] as const).map(([label, items]) => {
            const visible = items.filter(a => !failedImages.has(a.id) && toAssetUrl(a.file_path));
            if (visible.length === 0) {
              return (
                <div key={label}>
                  <div className="text-xs font-medium text-slate-400 mb-1.5">{label} <span className="text-slate-300">- 暂无</span></div>
                </div>
              );
            }
            return (
              <div key={label}>
                <div className="text-xs font-medium text-slate-500 mb-1.5">{label}</div>
                <div className="flex flex-wrap gap-2">
                  {visible.map(a => (
                      <div
                        key={a.id}
                        onClick={() => toggle(a.id)}
                        className={`relative group cursor-pointer rounded-xl overflow-hidden border-2 transition-all ${
                          checked.has(a.id) ? 'border-[#2563eb] ring-2 ring-blue-200' : 'border-transparent hover:border-slate-300'
                        }`}
                    >
                      <div className="w-24 h-24 relative">
                        {a.asset_type === 'audio'
                          ? <div className="flex h-full items-center justify-center bg-slate-800 text-xs font-medium text-white">音频</div>
                          : a.asset_type === 'video'
                            ? <video src={toAssetUrl(a.file_path)} className="w-full h-full object-cover" muted preload="metadata" onError={() => setFailedImages(prev => new Set(prev).add(a.id))} />
                            : <img src={toAssetUrl(a.file_path)} alt={a.name} className="w-full h-full object-cover" onError={() => setFailedImages(prev => new Set(prev).add(a.id))} />}
                        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
                      </div>
                      {checked.has(a.id) && (
                        <div className="absolute top-1 right-1 w-4 h-4 bg-[#2563eb] rounded-full flex items-center justify-center">
                          <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                      )}
                      {(recommendedIds || []).includes(a.id) && (
                        <div className="absolute top-1 left-1 rounded bg-amber-500 px-1.5 py-0.5 text-[9px] font-medium text-white">
                          推荐
                        </div>
                      )}
                      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 via-black/40 to-transparent p-1.5 pt-4">
                        <div className="text-[10px] text-white truncate leading-tight">{getThumbLabel(a)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          {availableAssets.length === 0 || availableAssets.every(a => failedImages.has(a.id) || !toAssetUrl(a.file_path)) ? (
            <div className="py-8 text-center text-xs text-slate-400">暂无可用资产，请先生成首尾帧或人物图</div>
          ) : null}
        </div>

        {/* 底部按钮 */}
        <div className="flex justify-end gap-3 px-5 py-3 border-t border-[#e5edf8]">
          <button
            onClick={onClose}
            className="rounded-xl border border-[#d7e3f4] px-4 py-2 text-xs text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            onClick={() => onConfirm(Array.from(checked))}
            className="rounded-xl bg-[#2563eb] px-4 py-2 text-xs text-white hover:bg-blue-700"
          >
            确认选择 ({checked.size})
          </button>
        </div>
      </div>
    </div>
  );
}
