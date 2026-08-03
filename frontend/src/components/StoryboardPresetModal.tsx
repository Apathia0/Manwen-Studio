import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, Eye, FileText, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react';
import {
  createStoryboardPreset,
  deleteStoryboardPreset,
  duplicateStoryboardPreset,
  getStoryStoryboardPreset,
  listStoryboardPresets,
  setStoryStoryboardPreset,
  updateStoryboardPreset,
  type StoryboardPromptPreset,
} from '../api';
import { confirm } from '../lib/confirm';
import { toast } from '../lib/toast';

interface StoryboardPresetModalProps {
  isOpen: boolean;
  onClose: () => void;
  storyId: number;
  currentPresetId: number | null;
  onPresetApplied: (presetId: number | null, presetName: string) => void;
}

type ActiveTab = 'system' | 'custom';

type PresetForm = {
  name: string;
  description: string;
  promptTemplate: string;
  systemPrompt: string;
};

const EMPTY_FORM: PresetForm = {
  name: '',
  description: '',
  promptTemplate: '',
  systemPrompt: '',
};

function toForm(preset: StoryboardPromptPreset): PresetForm {
  return {
    name: preset.name,
    description: preset.description ?? '',
    promptTemplate: preset.prompt_template,
    systemPrompt: preset.system_prompt ?? '',
  };
}

export default function StoryboardPresetModal({
  isOpen,
  onClose,
  storyId,
  currentPresetId,
  onPresetApplied,
}: StoryboardPresetModalProps) {
  const [presets, setPresets] = useState<StoryboardPromptPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<number | null>(currentPresetId);
  const [boundPresetId, setBoundPresetId] = useState<number | null>(currentPresetId);
  const [activeTab, setActiveTab] = useState<ActiveTab>('system');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [duplicatingId, setDuplicatingId] = useState<number | null>(null);
  const [editingPreset, setEditingPreset] = useState<StoryboardPromptPreset | null | undefined>(undefined);
  const [viewingPreset, setViewingPreset] = useState<StoryboardPromptPreset | null>(null);
  const [form, setForm] = useState<PresetForm>(EMPTY_FORM);
  const loadRequestRef = useRef(0);

  const loadPresets = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    try {
      const [presetResult, bindingResult] = await Promise.all([
        listStoryboardPresets(storyId),
        getStoryStoryboardPreset(storyId),
      ]);
      if (requestId !== loadRequestRef.current) return;
      setPresets(presetResult.presets);
      setSelectedPresetId(bindingResult.preset_id);
      setBoundPresetId(bindingResult.preset_id);
    } catch (err) {
      if (requestId !== loadRequestRef.current) return;
      toast.error(err instanceof Error ? err.message : '加载分镜模板失败');
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, [storyId]);

  useEffect(() => {
    if (!isOpen) {
      loadRequestRef.current += 1;
      return;
    }
    setActiveTab('system');
    setEditingPreset(undefined);
    setViewingPreset(null);
    setSelectedPresetId(currentPresetId);
    setBoundPresetId(currentPresetId);
    void loadPresets();
  }, [currentPresetId, isOpen, loadPresets]);

  if (!isOpen) return null;

  const systemPresets = presets.filter((preset) => preset.is_system);
  const customPresets = presets.filter((preset) => !preset.is_system);
  const isEditing = editingPreset !== undefined;
  const isViewing = viewingPreset !== null;
  const selectedPreset = presets.find((preset) => preset.id === selectedPresetId) ?? null;

  const handleDuplicate = async (preset: StoryboardPromptPreset) => {
    setDuplicatingId(preset.id);
    try {
      const duplicated = await duplicateStoryboardPreset(preset.id, storyId);
      setPresets((items) => [...items, duplicated]);
      setActiveTab('custom');
      setSelectedPresetId(duplicated.id);
      toast.success('已复制为自定义模板');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '复制分镜模板失败');
    } finally {
      setDuplicatingId(null);
    }
  };

  const handleDelete = async (preset: StoryboardPromptPreset) => {
    const confirmed = await confirm({
      title: '删除分镜模板',
      message: `确定删除“${preset.name}”吗？此操作不可恢复。`,
      confirmText: '删除',
      danger: true,
    });
    if (!confirmed) return;

    try {
      await deleteStoryboardPreset(preset.id);
      setPresets((items) => items.filter((item) => item.id !== preset.id));
      if (selectedPresetId === preset.id) setSelectedPresetId(null);
      if (boundPresetId === preset.id) {
        setBoundPresetId(null);
        onPresetApplied(null, '默认分镜模板');
      }
      toast.success('分镜模板已删除');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除分镜模板失败');
    }
  };

  const handleSave = async () => {
    const name = form.name.trim();
    const promptTemplate = form.promptTemplate.trim();
    if (!name || !promptTemplate) {
      toast.error('请填写模板名称和正文模板');
      return;
    }

    setSaving(true);
    try {
      const data = {
        name,
        description: form.description.trim(),
        prompt_template: promptTemplate,
        system_prompt: form.systemPrompt.trim(),
      };
      const saved = editingPreset
        ? await updateStoryboardPreset(editingPreset.id, data)
        : await createStoryboardPreset({ ...data, story_id: storyId });
      setPresets((items) => editingPreset
        ? items.map((item) => item.id === saved.id ? saved : item)
        : [...items, saved]);
      setSelectedPresetId(saved.id);
      try {
        const binding = await setStoryStoryboardPreset(storyId, saved.id);
        setBoundPresetId(binding.preset_id);
        onPresetApplied(binding.preset_id, binding.preset?.name ?? saved.name);
      } catch (applyError) {
        setEditingPreset(undefined);
        setActiveTab('custom');
        toast.error(`模板已保存到个人模板库，但应用失败：${applyError instanceof Error ? applyError.message : '请稍后重试'}`);
        return;
      }
      toast.success(editingPreset ? '分镜模板已保存并应用' : '分镜模板已创建并应用');
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存分镜模板失败');
    } finally {
      setSaving(false);
    }
  };

  const handleApply = async () => {
    setSaving(true);
    try {
      const binding = await setStoryStoryboardPreset(storyId, selectedPresetId);
      setBoundPresetId(binding.preset_id);
      onPresetApplied(binding.preset_id, binding.preset?.name ?? '默认分镜模板');
      toast.success('分镜模板已应用');
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '应用分镜模板失败');
    } finally {
      setSaving(false);
    }
  };

  const openCreateForm = () => {
    setViewingPreset(null);
    setForm(EMPTY_FORM);
    setEditingPreset(null);
  };

  const openEditForm = (preset: StoryboardPromptPreset) => {
    if (preset.is_system) {
      toast.info('系统预设不可编辑，请复制为自定义后编辑');
      return;
    }
    setViewingPreset(null);
    setForm(toForm(preset));
    setEditingPreset(preset);
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[85vh] w-[min(960px,92vw)] flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <FileText size={19} className="text-blue-600" />
              分镜脚本模板
            </div>
            <div className="mt-1 text-sm text-slate-500">自定义模板保存到个人模板库，可在你的所有作品中复用</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200" aria-label="关闭">
            <X size={18} />
          </button>
        </div>

        {isEditing ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-6">
            <div className="mb-5 flex items-center justify-between">
              <div className="text-base font-semibold text-slate-800">{editingPreset ? '编辑自定义模板' : '新建自定义模板'}</div>
              <button onClick={() => setEditingPreset(undefined)} className="text-sm text-slate-500 hover:text-slate-800">返回列表</button>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block text-sm font-medium text-slate-700">
                模板名称
                <input
                  value={form.name}
                  onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
                  className="mt-1.5 w-full rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm outline-none focus:border-blue-500"
                  placeholder="例如：电影感分镜"
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                描述
                <textarea
                  value={form.description}
                  onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
                  className="mt-1.5 h-[74px] w-full resize-none rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm outline-none focus:border-blue-500"
                  placeholder="简要说明模板适用场景"
                />
              </label>
            </div>
            <label className="mt-4 flex min-h-0 flex-1 flex-col text-sm font-medium text-slate-700">
              正文模板
              <textarea
                value={form.promptTemplate}
                onChange={(event) => setForm((value) => ({ ...value, promptTemplate: event.target.value }))}
                className="mt-1.5 min-h-[220px] flex-1 resize-y rounded-lg border border-[#d7e3f4] px-3 py-2 font-mono text-xs leading-6 outline-none focus:border-blue-500"
                placeholder="填写分镜脚本生成提示词"
              />
            </label>
            <div className="mt-2 text-xs text-slate-500">支持 {'{page_count}'} 占位符，生成时自动替换为实际页数</div>
            <label className="mt-4 block text-sm font-medium text-slate-700">
              System Prompt（可选）
              <textarea
                value={form.systemPrompt}
                onChange={(event) => setForm((value) => ({ ...value, systemPrompt: event.target.value }))}
                className="mt-1.5 h-24 w-full resize-y rounded-lg border border-[#d7e3f4] px-3 py-2 font-mono text-xs leading-5 outline-none focus:border-blue-500"
                placeholder="留空使用系统默认"
              />
              <span className="mt-1 block text-xs font-normal text-slate-500">留空使用系统默认</span>
            </label>
          </div>
        ) : isViewing ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-6">
            <div className="mb-5 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-base font-semibold text-slate-800">{viewingPreset.name}</div>
                <div className="mt-1 text-sm text-slate-500">{viewingPreset.description || '暂无描述'}</div>
              </div>
              <button onClick={() => setViewingPreset(null)} className="shrink-0 text-sm text-slate-500 hover:text-slate-800">返回列表</button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-4">
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="text-sm font-medium text-slate-700">正文模板</div>
                <pre className="mt-1.5 min-h-[220px] flex-1 overflow-y-auto rounded-lg border border-[#d7e3f4] bg-slate-50 px-3 py-2 whitespace-pre-wrap break-words font-mono text-xs leading-6 text-slate-700">{viewingPreset.prompt_template}</pre>
                <div className="mt-2 text-xs text-slate-500">支持 {'{page_count}'} 占位符，生成时自动替换为实际页数</div>
              </div>
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="text-sm font-medium text-slate-700">System Prompt</div>
                <pre className="mt-1.5 min-h-[120px] flex-1 overflow-y-auto rounded-lg border border-[#d7e3f4] bg-slate-50 px-3 py-2 whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-700">{viewingPreset.system_prompt || '未设置（使用系统默认）'}</pre>
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-3">
              <div className="flex gap-2">
                {([
                  ['system', '系统模板'],
                  ['custom', '我的模板'],
                ] as const).map(([tab, label]) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition ${activeTab === tab ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {activeTab === 'custom' && (
                <button onClick={openCreateForm} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700">
                  <Plus size={14} />新建模板
                </button>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              {loading ? (
                <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><Loader2 size={18} className="animate-spin text-blue-600" />正在加载模板...</div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {(activeTab === 'system' ? systemPresets : customPresets).map((preset) => {
                    const selected = selectedPresetId === preset.id;
                    return (
                      <div key={preset.id} className={`flex min-h-[164px] flex-col rounded-xl border p-4 transition ${selected ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-200' : 'border-[#e5edf8] bg-white hover:border-blue-300'}`}>
                        <button type="button" onClick={() => setSelectedPresetId(preset.id)} className="text-left">
                          <div className="flex items-start justify-between gap-3">
                            <div className="text-sm font-semibold text-slate-800">{preset.name}</div>
                            {selected && <Check size={16} className="shrink-0 text-blue-600" />}
                          </div>
                          <div className="mt-1 min-h-5 text-xs text-slate-500">{preset.description || '暂无描述'}</div>
                          <div className="mt-3 line-clamp-3 font-mono text-xs leading-5 text-slate-600">{preset.prompt_template.slice(0, 60)}</div>
                        </button>
                        <div className="mt-auto flex justify-end gap-2 pt-3">
                          <button onClick={() => setViewingPreset(preset)} className="inline-flex items-center gap-1 rounded-md border border-[#d7e3f4] px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"><Eye size={13} />查看</button>
                          {preset.is_system || !preset.is_owner ? (
                            <button
                              onClick={() => void handleDuplicate(preset)}
                              disabled={duplicatingId === preset.id}
                              className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-2.5 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                            >
                              {duplicatingId === preset.id ? <Loader2 size={13} className="animate-spin" /> : <Copy size={13} />}
                              {preset.is_system ? '复制为自定义' : '复制到我的模板'}
                            </button>
                          ) : (
                            <>
                              <button onClick={() => openEditForm(preset)} className="inline-flex items-center gap-1 rounded-md border border-[#d7e3f4] px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"><Pencil size={13} />编辑</button>
                              <button onClick={() => void handleDelete(preset)} className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"><Trash2 size={13} />删除</button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {(activeTab === 'system' ? systemPresets : customPresets).length === 0 && (
                    <div className="col-span-full py-14 text-center text-sm text-slate-500">{activeTab === 'system' ? '暂无系统模板' : '尚未创建自定义模板'}</div>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        <div className="flex items-center justify-between border-t border-[#e5edf8] px-6 py-4">
          <div className="text-sm text-slate-500">
            当前绑定：<span className="font-medium text-slate-700">{presets.find((preset) => preset.id === boundPresetId)?.name ?? '默认分镜模板'}</span>
            {selectedPresetId !== boundPresetId && <span className="ml-3 text-blue-600">待应用：{selectedPreset?.name ?? '默认分镜模板'}</span>}
          </div>
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <button onClick={() => setEditingPreset(undefined)} disabled={saving} className="rounded-lg border border-[#d7e3f4] px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50">取消</button>
                <button onClick={() => void handleSave()} disabled={saving} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:cursor-wait disabled:opacity-50">
                  {saving && <Loader2 size={15} className="animate-spin" />}保存并应用
                </button>
              </>
            ) : isViewing ? (
              <button onClick={() => setViewingPreset(null)} className="rounded-lg border border-[#d7e3f4] px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">返回列表</button>
            ) : (
              <>
                <button onClick={onClose} className="rounded-lg border border-[#d7e3f4] px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">取消</button>
                <button onClick={() => void handleApply()} disabled={loading || saving} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
                  {saving && <Loader2 size={15} className="animate-spin" />}应用模板
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
