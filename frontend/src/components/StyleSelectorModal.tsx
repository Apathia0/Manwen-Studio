import { useState, useRef } from 'react';
import { X, Upload, Check, Loader2, Film } from 'lucide-react';
import type { VideoStylePreset } from '../api';
import { uploadStyleReferenceImage } from '../api';

interface StyleSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  presets: VideoStylePreset[];
  selectedStyleName: string;
  styleReferenceImageUrl: string | null;
  workflowId: number | null;
  onStyleSelect: (styleName: string, referenceImageUrl: string | null) => void;
}

function toStyleImageUrl(filePath?: string | null): string {
  if (!filePath) return '';
  if (filePath.startsWith('http') || filePath.startsWith('/static/')) return filePath;
  // 对路径中的中文字符进行 URL 编码
  const parts = filePath.replace(/\\/g, '/').split('/');
  const encodedParts = parts.map(p => encodeURIComponent(p));
  return `/static/manga/${encodedParts.join('/')}`;
}

const STYLE_CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: 'realistic', label: '写实' },
  { key: 'anime', label: '动漫' },
  { key: 'artistic', label: '艺术' },
  { key: 'cinematic', label: '电影' },
];

export default function StyleSelectorModal({
  isOpen,
  onClose,
  presets,
  selectedStyleName,
  styleReferenceImageUrl,
  workflowId,
  onStyleSelect,
}: StyleSelectorModalProps) {
  const [activeCategory, setActiveCategory] = useState('all');
  const [uploading, setUploading] = useState(false);
  const [localSelectedStyle, setLocalSelectedStyle] = useState(selectedStyleName);
  const [localReferenceUrl, setLocalReferenceUrl] = useState(styleReferenceImageUrl);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const prevOpenRef = useRef(isOpen);

  // 每次弹窗打开时，将本地状态与父组件 prop 同步
  if (isOpen && !prevOpenRef.current) {
    prevOpenRef.current = true;
    setLocalSelectedStyle(selectedStyleName);
    setLocalReferenceUrl(styleReferenceImageUrl);
  }
  if (!isOpen) {
    prevOpenRef.current = false;
  }

  if (!isOpen) return null;

  const filteredPresets = activeCategory === 'all'
    ? presets
    : presets.filter((p) => p.category === activeCategory);

  const handlePresetClick = (preset: VideoStylePreset) => {
    setLocalSelectedStyle(preset.name);
    setLocalReferenceUrl(null); // 使用内置预设时清除自定义参考图
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!workflowId) {
      // 如果没有工作流，先提示用户
      alert('请先创建工作流后再上传风格参考图');
      return;
    }

    setUploading(true);
    try {
      const result = await uploadStyleReferenceImage(workflowId, file);
      setLocalReferenceUrl(result.style_reference_image_url);
      setLocalSelectedStyle(''); // 使用自定义参考图时清除内置风格
    } catch (err) {
      console.error('上传风格参考图失败:', err);
    } finally {
      setUploading(false);
    }
  };

  const handleConfirm = () => {
    onStyleSelect(localSelectedStyle, localReferenceUrl);
    onClose();
  };

  const handleCancel = () => {
    setLocalSelectedStyle(selectedStyleName);
    setLocalReferenceUrl(styleReferenceImageUrl);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm"
      onClick={handleCancel}
    >
      <div
        className="flex h-[80vh] w-[min(900px,90vw)] flex-col overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">选择画面风格</div>
            <div className="mt-1 text-sm text-slate-500">
              选择内置风格预设或上传自定义风格参考图，确保所有镜头风格一致
            </div>
          </div>
          <button
            onClick={handleCancel}
            className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200"
          >
            <X size={18} />
          </button>
        </div>

        {/* 分类标签 */}
        <div className="flex gap-2 border-b border-[#e5edf8] px-6 py-3">
          {STYLE_CATEGORIES.map((cat) => (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                activeCategory === cat.key
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* 自定义风格参考图上传 */}
          <div className="mb-6">
            <div className="mb-3 text-sm font-medium text-slate-700">自定义风格参考图</div>
            <div
              className={`relative cursor-pointer rounded-xl border-2 border-dashed p-4 transition ${
                localReferenceUrl
                  ? 'border-blue-400 bg-blue-50'
                  : 'border-[#d7e3f4] bg-slate-50 hover:border-blue-300 hover:bg-blue-50/50'
              }`}
              onClick={() => fileInputRef.current?.click()}
            >
              {localReferenceUrl ? (
                <div className="flex items-center gap-4">
                  <img
                    src={toStyleImageUrl(localReferenceUrl)}
                    alt="风格参考"
                    className="h-24 w-24 rounded-lg object-cover"
                  />
                  <div>
                    <div className="text-sm font-medium text-blue-700">已上传自定义风格参考图</div>
                    <div className="mt-1 text-xs text-slate-500">点击更换</div>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 py-4">
                  {uploading ? (
                    <Loader2 size={24} className="animate-spin text-blue-500" />
                  ) : (
                    <Upload size={24} className="text-slate-400" />
                  )}
                  <div className="text-sm text-slate-600">
                    {uploading ? '上传中...' : '点击或拖拽上传风格参考图'}
                  </div>
                  <div className="text-xs text-slate-400">
                    上传一张图片作为所有镜头的风格参考，确保画面风格一致
                  </div>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleFileUpload}
                className="hidden"
              />
            </div>
          </div>

          {/* 内置风格预设 */}
          <div>
            <div className="mb-3 text-sm font-medium text-slate-700">内置风格预设</div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
              {filteredPresets.map((preset) => {
                const isSelected = localSelectedStyle === preset.name && !localReferenceUrl;
                return (
                  <button
                    key={preset.id}
                    onClick={() => handlePresetClick(preset)}
                    className={`relative overflow-hidden rounded-xl border-2 text-left transition ${
                      isSelected
                        ? 'border-blue-500 ring-2 ring-blue-200'
                        : 'border-[#e5edf8] hover:border-blue-300'
                    }`}
                  >
                    {/* 预览图 */}
                    <div className="aspect-[4/3] overflow-hidden bg-slate-100">
                      {preset.image_url ? (
                        <img
                          src={toStyleImageUrl(preset.image_url)}
                          alt={preset.name}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-slate-400">
                          <div className="text-center">
                            <Film size={28} className="mx-auto text-slate-300" />
                            <div className="mt-1 text-xs">{preset.name}</div>
                          </div>
                        </div>
                      )}
                    </div>
                    {/* 名称 */}
                    <div className="px-3 py-2">
                      <div className="text-sm font-medium text-slate-800">{preset.name}</div>
                      <div className="mt-0.5 text-[11px] text-slate-500">{preset.category}</div>
                    </div>
                    {/* 选中标记 */}
                    {isSelected && (
                      <div className="absolute right-2 top-2 rounded-full bg-blue-500 p-1">
                        <Check size={12} className="text-white" />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-between border-t border-[#e5edf8] px-6 py-4">
          <div className="text-sm text-slate-500">
            {localReferenceUrl
              ? '<Check size={12} className="inline-block" /> 已选择自定义风格参考图'
              : localSelectedStyle
                ? `<Check size={12} className="inline-block" /> 已选择: ${localSelectedStyle}`
                : '未选择风格'}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCancel}
              className="rounded-lg border border-[#d7e3f4] px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              onClick={handleConfirm}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
            >
              确认选择
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
