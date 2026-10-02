import { useCallback, useEffect, useState, useRef } from 'react';
import {
  listStylePresets,
  createStylePreset,
  updateStylePreset,
  deleteStylePreset,
  apiHeaders,
  type VideoStylePreset,
} from '../../api';
import { Film } from 'lucide-react';
import MediaImage from '../shared/MediaImage';
import { toast } from '../../lib/toast';
import { confirm } from '../../lib/confirm';
import { readResponseError } from '../../lib/errors';

function toStyleImageUrl(filePath?: string | null): string {
  if (!filePath) return '';
  if (filePath.startsWith('http') || filePath.startsWith('/static/')) return filePath;
  const parts = filePath.replace(/\\/g, '/').split('/');
  const encodedParts = parts.map(p => encodeURIComponent(p));
  return `/static/manga/${encodedParts.join('/')}`;
}

export default function StylePresetManager() {
  const [presets, setPresets] = useState<VideoStylePreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [editPreset, setEditPreset] = useState<VideoStylePreset | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState({
    name: '',
    category: 'realistic',
    image_url: '',
    prompt_template: '',
    sort_order: 0,
  });

  const loadPresets = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listStylePresets();
      setPresets(data.presets || []);
    } catch (err) {
      toast.error('加载风格预设失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPresets();
  }, [loadPresets]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch('/api/video-style-presets/upload-image', {
        method: 'POST',
        headers: apiHeaders(),
        body: formData,
      });
      if (!res.ok) throw new Error(await readResponseError(res, '上传风格参考图失败'));
      const result = await res.json();
      setFormData(prev => ({ ...prev, image_url: result.url }));
      setPreviewUrl(result.url);
      toast.success('图片上传成功');
    } catch (err: any) {
      toast.error(`上传失败: ${err.message}`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleCreate = async () => {
    if (!formData.name.trim()) {
      toast.error('请输入风格名称');
      return;
    }
    try {
      await createStylePreset({
        name: formData.name,
        category: formData.category,
        image_url: formData.image_url || null,
        prompt_template: formData.prompt_template,
        sort_order: formData.sort_order,
      });
      toast.success('创建成功');
      setIsCreating(false);
      setFormData({ name: '', category: 'realistic', image_url: '', prompt_template: '', sort_order: 0 });
      setPreviewUrl('');
      loadPresets();
    } catch (err: any) {
      toast.error(`创建失败: ${err.message}`);
    }
  };

  const handleUpdate = async () => {
    if (!editPreset) return;
    try {
      await updateStylePreset(editPreset.id, {
        name: formData.name,
        category: formData.category,
        image_url: formData.image_url || null,
        prompt_template: formData.prompt_template,
        sort_order: formData.sort_order,
      });
      toast.success('更新成功');
      setEditPreset(null);
      setPreviewUrl('');
      loadPresets();
    } catch (err: any) {
      toast.error(`更新失败: ${err.message}`);
    }
  };

  const handleDelete = async (preset: VideoStylePreset) => {
    const ok = await confirm({
      title: '删除风格预设',
      message: `确定要删除风格预设「${preset.name}」吗？`,
      confirmText: '删除',
      cancelText: '取消',
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteStylePreset(preset.id);
      toast.success('删除成功');
      loadPresets();
    } catch (err: any) {
      toast.error(`删除失败: ${err.message}`);
    }
  };

  const startEdit = (preset: VideoStylePreset) => {
    setEditPreset(preset);
    setIsCreating(false);
    setFormData({
      name: preset.name,
      category: preset.category,
      image_url: preset.image_url || '',
      prompt_template: preset.prompt_template || '',
      sort_order: preset.sort_order,
    });
    setPreviewUrl(preset.image_url || '');
  };

  const startCreate = () => {
    setEditPreset(null);
    setIsCreating(true);
    setFormData({ name: '', category: 'realistic', image_url: '', prompt_template: '', sort_order: presets.length });
    setPreviewUrl('');
  };

  const cancelForm = () => {
    setEditPreset(null);
    setIsCreating(false);
    setFormData({ name: '', category: 'realistic', image_url: '', prompt_template: '', sort_order: 0 });
    setPreviewUrl('');
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">视频风格预设</h3>
          <p className="mt-1 text-sm text-slate-500">管理内置视频风格预设，用于视频工作流的风格选择</p>
        </div>
        <button
          onClick={startCreate}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          新增风格
        </button>
      </div>

      {/* 新增/编辑表单 */}
      {(isCreating || editPreset) && (
        <div className="rounded-xl border border-[#d7e3f4] bg-white p-4">
          <div className="mb-4 text-sm font-medium text-slate-700">
            {editPreset ? '编辑风格预设' : '新增风格预设'}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs text-slate-500">风格名称 *</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm"
                placeholder="如：写实电影感"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">分类</label>
              <select
                value={formData.category}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                className="w-full rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm"
              >
                <option value="realistic">写实</option>
                <option value="anime">动漫</option>
                <option value="artistic">艺术</option>
                <option value="game">游戏</option>
                <option value="cinematic">电影</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">预览图</label>
              <div className="flex items-center gap-3">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  {uploading ? '上传中...' : '选择图片'}
                </button>
                {(previewUrl || formData.image_url) && (
                  <MediaImage
                    src={toStyleImageUrl(previewUrl || formData.image_url)}
                    alt="预览"
                    className="h-10 w-10 rounded object-cover"
                  />
                )}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">排序</label>
              <input
                type="number"
                value={formData.sort_order}
                onChange={(e) => setFormData({ ...formData, sort_order: parseInt(e.target.value) || 0 })}
                className="w-full rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm"
              />
            </div>
            <div className="col-span-2">
              <label className="mb-1 block text-xs text-slate-500">提示词模板</label>
              <textarea
                value={formData.prompt_template}
                onChange={(e) => setFormData({ ...formData, prompt_template: e.target.value })}
                className="h-20 w-full rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm"
                placeholder="风格描述提示词..."
              />
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              onClick={editPreset ? handleUpdate : handleCreate}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
            >
              {editPreset ? '保存修改' : '创建'}
            </button>
            <button
              onClick={cancelForm}
              className="rounded-lg border border-[#d7e3f4] px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 风格列表 */}
      {loading ? (
        <div className="text-center text-slate-500">加载中...</div>
      ) : presets.length === 0 ? (
        <div className="text-center text-slate-400">暂无风格预设</div>
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          {presets.map((preset) => (
            <div
              key={preset.id}
              className="overflow-hidden rounded-xl border border-[#d7e3f4] bg-white shadow-sm"
            >
              <div className="aspect-[4/3] bg-slate-100">
                {preset.image_url ? (
                  <MediaImage
                    src={toStyleImageUrl(preset.image_url)}
                    alt={preset.name}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-slate-400">
                    <Film size={28} className="mx-auto text-slate-300" />
                  </div>
                )}
              </div>
              <div className="p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-800">{preset.name}</div>
                    <div className="text-[11px] text-slate-500">{preset.category} · 排序: {preset.sort_order}</div>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={() => startEdit(preset)}
                      className="rounded px-2 py-1 text-xs text-blue-600 hover:bg-blue-50"
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => handleDelete(preset)}
                      className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
