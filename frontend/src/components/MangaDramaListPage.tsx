import { useCallback, useEffect, useState } from 'react';
import { Clapperboard, Plus, RefreshCcw, ArrowRight, Pencil, Trash2, X } from 'lucide-react';
import { createMangaDramaProject, deleteMangaDramaProject, listMangaDramaProjects, updateMangaDramaProject, type MangaDramaProject } from '../api';
import { confirm } from '../lib/confirm';
import { toast } from '../lib/toast';

interface MangaDramaListPageProps {
  onOpenProject: (storyId: number) => void;
}

function formatDate(value?: string | null): string {
  if (!value) return '';
  try {
    return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/** 编辑项目名称与简介的小弹窗 */
function EditProjectDialog({ project, onClose, onSaved }: { project: MangaDramaProject; onClose: () => void; onSaved: (next: { title: string; description: string }) => void }) {
  const [title, setTitle] = useState(project.title);
  const [description, setDescription] = useState(project.description || '');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const nextTitle = title.trim();
    if (!nextTitle) { toast.error('项目名称不能为空'); return; }
    setSaving(true);
    try {
      const saved = await updateMangaDramaProject(project.story_id, { title: nextTitle, description: description.trim() });
      onSaved({ title: saved.title, description: saved.description || '' });
      toast.success('项目信息已保存');
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存项目信息失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="编辑漫剧项目" className="w-full max-w-md rounded-2xl border border-[#d7e3f4] bg-white p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">编辑项目</h2>
          <button type="button" aria-label="关闭" onClick={onClose} className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"><X size={16} /></button>
        </div>
        <label className="mb-1.5 block text-xs font-medium text-slate-600">项目名称</label>
        <input
          autoFocus
          value={title}
          maxLength={120}
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') void save(); if (event.key === 'Escape') onClose(); }}
          className="w-full rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-400"
        />
        <label className="mb-1.5 mt-4 block text-xs font-medium text-slate-600">简介（可选）</label>
        <textarea
          value={description}
          maxLength={500}
          rows={3}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="一句话说明这部漫剧讲什么"
          className="w-full resize-none rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-400"
        />
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-xs text-slate-600 hover:bg-slate-50">取消</button>
          <button type="button" onClick={() => void save()} disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50">{saving ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </div>
  );
}

export default function MangaDramaListPage({ onOpenProject }: MangaDramaListPageProps) {
  const [projects, setProjects] = useState<MangaDramaProject[]>([]);
  const [editing, setEditing] = useState<MangaDramaProject | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listMangaDramaProjects();
      setProjects(res.projects);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '加载漫剧项目失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = useCallback(async () => {
    const title = newTitle.trim() || '未命名漫剧';
    setCreating(true);
    try {
      const idempotencyKey = `md-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const res = await createMangaDramaProject({ title, idempotency_key: idempotencyKey });
      toast.success(`漫剧项目「${res.story_title}」已创建`);
      onOpenProject(res.story_id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '创建漫剧项目失败');
    } finally {
      setCreating(false);
    }
  }, [newTitle, onOpenProject]);

  const handleDelete = useCallback(async (project: MangaDramaProject) => {
    const ok = await confirm({
      title: '删除漫剧项目',
      message: `确定删除「${project.title}」吗？项目里的 ${project.canvases.length} 个画布、版本记录、资产和助手对话都会一并删除，且无法恢复。`,
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    setDeletingId(project.story_id);
    try {
      await deleteMangaDramaProject(project.story_id);
      setProjects((current) => current.filter((item) => item.story_id !== project.story_id));
      toast.success(`已删除「${project.title}」`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除项目失败');
    } finally {
      setDeletingId(null);
    }
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 max-md:px-3 max-md:py-4">
      {editing && (
        <EditProjectDialog
          project={editing}
          onClose={() => setEditing(null)}
          onSaved={(next) => setProjects((current) => current.map((item) => (item.story_id === editing.story_id ? { ...item, ...next } : item)))}
        />
      )}
      {/* 顶部标题栏 */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <Clapperboard size={18} />
          </span>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">无限画布</h1>
            <p className="text-xs text-slate-500">从画布编排剧本、分镜与视频，独立于小说与漫画工作台</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCcw size={13} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Plus size={14} />
            新建漫剧项目
          </button>
        </div>
      </div>

      {/* 新建面板 */}
      {showCreate && (
        <div className="rounded-xl border border-[#d7e3f4] bg-white p-4 shadow-sm">
          <label className="mb-1.5 block text-xs font-medium text-slate-600">项目名称</label>
          <div className="flex gap-2">
            <input
              autoFocus
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate(); }}
              placeholder="给漫剧起个名字，留空则使用默认名称"
              className="flex-1 rounded-lg border border-[#d7e3f4] px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-400"
            />
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Plus size={13} />
              {creating ? '创建中…' : '创建并进入画布'}
            </button>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">创建后将直接进入空白画布，可导入小说章节、与 AI 对话创作剧本，或手动编写。</p>
        </div>
      )}

      {/* 项目列表 */}
      {loading ? (
        <div className="flex items-center justify-center rounded-xl border border-slate-100 bg-white py-16 text-sm text-slate-400">
          正在加载漫剧项目…
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-slate-200 bg-white py-16">
          <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-500">
            <Clapperboard size={22} />
          </span>
          <p className="text-sm text-slate-500">还没有漫剧项目</p>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700"
          >
            <Plus size={13} />
            创建第一个漫剧项目
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <div
              key={project.story_id}
              role="button"
              tabIndex={0}
              aria-busy={deletingId === project.story_id}
              onClick={() => { if (deletingId !== project.story_id) onOpenProject(project.story_id); }}
              onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onOpenProject(project.story_id); } }}
              className={`group flex cursor-pointer flex-col gap-2.5 rounded-xl border border-[#d7e3f4] bg-white p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 ${deletingId === project.story_id ? 'pointer-events-none opacity-50' : ''}`}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <Clapperboard size={16} />
                </span>
                <div className="flex items-center gap-0.5">
                  <button
                    type="button"
                    title="编辑名称与简介"
                    aria-label={`编辑项目 ${project.title}`}
                    onClick={(event) => { event.stopPropagation(); setEditing(project); }}
                    className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-600 md:opacity-60 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    title="删除项目"
                    aria-label={`删除项目 ${project.title}`}
                    onClick={(event) => { event.stopPropagation(); void handleDelete(project); }}
                    className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600 md:opacity-60 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                  >
                    <Trash2 size={14} />
                  </button>
                  <ArrowRight size={15} className="ml-1 text-slate-300 transition-colors group-hover:text-blue-500" />
                </div>
              </div>
              <div>
                <h3 className="truncate text-sm font-medium text-slate-900">{project.title}</h3>
                <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{project.description || '暂无简介'}</p>
              </div>
              <div className="mt-auto flex items-center justify-between border-t border-slate-50 pt-2 text-[11px] text-slate-400">
                <span>{project.canvases.length} 个画布</span>
                <span>{formatDate(project.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
