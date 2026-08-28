import { useCallback, useEffect, useState } from 'react';
import { Clapperboard, Plus, RefreshCcw, ArrowRight } from 'lucide-react';
import { createMangaDramaProject, listMangaDramaProjects, type MangaDramaProject } from '../api';
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

export default function MangaDramaListPage({ onOpenProject }: MangaDramaListPageProps) {
  const [projects, setProjects] = useState<MangaDramaProject[]>([]);
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

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 max-md:px-3 max-md:py-4">
      {/* 顶部标题栏 */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <Clapperboard size={18} />
          </span>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">漫剧创作</h1>
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
            <button
              key={project.story_id}
              type="button"
              onClick={() => onOpenProject(project.story_id)}
              className="group flex flex-col gap-2.5 rounded-xl border border-[#d7e3f4] bg-white p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <Clapperboard size={16} />
                </span>
                <ArrowRight size={15} className="mt-1.5 text-slate-300 transition-colors group-hover:text-blue-500" />
              </div>
              <div>
                <h3 className="truncate text-sm font-medium text-slate-900">{project.title}</h3>
                <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{project.description || '暂无简介'}</p>
              </div>
              <div className="mt-auto flex items-center justify-between border-t border-slate-50 pt-2 text-[11px] text-slate-400">
                <span>{project.canvases.length} 个画布</span>
                <span>{formatDate(project.created_at)}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
