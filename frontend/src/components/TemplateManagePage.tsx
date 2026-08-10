import { useEffect, useState } from 'react';
import { Heart } from 'lucide-react';
import {
  listMyTemplates,
  listPublicTemplates,
  deletePromptTemplate,
  submitTemplateForReview,
  likeTemplate,
  unlikeTemplate,
  forkPromptTemplate,
  type PromptTemplateItem,
} from '../api';
import TemplateEditor from './TemplateEditor';
import { toast } from '../lib/toast';
import { confirm } from '../lib/confirm';

type TabKey = 'my' | 'market';

export default function TemplateManagePage() {
  const [activeTab, setActiveTab] = useState<TabKey>('my');
  const [myTemplates, setMyTemplates] = useState<PromptTemplateItem[]>([]);
  const [marketTemplates, setMarketTemplates] = useState<PromptTemplateItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplateItem | null>(null);
  const [showEditor, setShowEditor] = useState(false);

  async function loadMyTemplates() {
    setLoading(true);
    setError(null);
    try {
      const res = await listMyTemplates({ page_size: 50 });
      setMyTemplates(res.templates);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }

  async function loadMarketTemplates() {
    setLoading(true);
    setError(null);
    try {
      const res = await listPublicTemplates({ page_size: 50, sort: 'popular' });
      setMarketTemplates(res.templates);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (activeTab === 'my') loadMyTemplates();
    else loadMarketTemplates();
  }, [activeTab]);

  async function handleDelete(templateId: number) {
    if (!(await confirm({ message: '确定删除此模板？' }))) return;
    try {
      await deletePromptTemplate(templateId);
      setMyTemplates(prev => prev.filter(t => t.id !== templateId));
    } catch (e: any) {
      toast.error(e.message || '删除失败');
    }
  }

  async function handleSubmitReview(templateId: number) {
    try {
      await submitTemplateForReview(templateId);
      loadMyTemplates();
    } catch (e: any) {
      toast.error(e.message || '提交失败');
    }
  }

  async function handleLike(tpl: PromptTemplateItem) {
    try {
      if (tpl.is_liked) {
        await unlikeTemplate(tpl.id);
      } else {
        await likeTemplate(tpl.id);
      }
      loadMarketTemplates();
    } catch (e: any) {
      toast.error(e.message || '操作失败');
    }
  }

  async function handleFork(tpl: PromptTemplateItem) {
    try {
      await forkPromptTemplate(tpl.id);
      loadMyTemplates();
      setActiveTab('my');
    } catch (e: any) {
      toast.error(e.message || '复制失败');
    }
  }

  function handleEditorSaved() {
    setShowEditor(false);
    setEditingTemplate(null);
    loadMyTemplates();
  }

  const statusLabels: Record<string, string> = {
    draft: '草稿',
    pending: '审核中',
    approved: '已通过',
    rejected: '已拒绝',
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 md:px-6 md:py-8">
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">提示词模板</h1>
          <p className="mt-1 text-sm text-slate-500">管理你的创作模板，或从社区发现优秀模板</p>
        </div>
        <button
          onClick={() => { setEditingTemplate(null); setShowEditor(true); }}
          className="max-md:min-h-[44px] rounded-xl bg-[#2563eb] px-4 py-2 text-sm font-medium text-white shadow-[0_4px_10px_rgba(37,99,235,0.18)] transition hover:bg-[#1d4ed8]"
        >
          创建模板
        </button>
      </div>

      {/* Tab 切换 */}
      <div className="mb-6 flex gap-1 border-b border-[#e8edf2]">
        <button
          onClick={() => setActiveTab('my')}
          className={`max-md:min-h-[44px] rounded-t-lg px-4 py-2 text-sm font-medium transition ${
            activeTab === 'my' ? 'border-b-2 border-[#2563eb] text-[#2563eb]' : 'text-slate-400 hover:text-slate-600'
          }`}
        >我的模板</button>
        <button
          onClick={() => setActiveTab('market')}
          className={`max-md:min-h-[44px] rounded-t-lg px-4 py-2 text-sm font-medium transition ${
            activeTab === 'market' ? 'border-b-2 border-[#2563eb] text-[#2563eb]' : 'text-slate-400 hover:text-slate-600'
          }`}
        >模板广场</button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-slate-400">加载中...</div>
      ) : showEditor ? (
        <TemplateEditor
          template={editingTemplate}
          onSave={handleEditorSaved}
          onCancel={() => { setShowEditor(false); setEditingTemplate(null); }}
        />
      ) : activeTab === 'my' ? (
        /* 我的模板列表 */
        <div className="space-y-3">
          {myTemplates.length === 0 && (
            <div className="py-12 text-center text-sm text-slate-400">
              还没有模板，点击上方按钮创建第一个
            </div>
          )}
          {myTemplates.map(tpl => (
            <div key={tpl.id} className="rounded-2xl border border-[#e8edf2] bg-white p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium text-slate-900">{tpl.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${
                      tpl.status === 'approved' ? 'bg-green-100 text-green-700' :
                      tpl.status === 'pending' ? 'bg-yellow-100 text-yellow-700' :
                      tpl.status === 'rejected' ? 'bg-red-100 text-red-700' :
                      'bg-slate-100 text-slate-500'
                    }`}>{statusLabels[tpl.status] || tpl.status}</span>
                    {tpl.visibility === 'official' && (
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700">官方推荐</span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{tpl.description || '无描述'}</p>
                  {tpl.category && (
                    <span className="mt-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{tpl.category}</span>
                  )}
                  <p className="mt-1 text-xs text-slate-400">使用 {tpl.usage_count} 次 · {tpl.updated_at.slice(0, 10)}</p>
                </div>
                <div className="flex shrink-0 gap-1 md:ml-4">
                  <button
                    onClick={() => { setEditingTemplate(tpl); setShowEditor(true); }}
                    className="max-md:min-h-[44px] rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
                  >编辑</button>
                  {tpl.status === 'draft' && (
                    <button
                      onClick={() => handleSubmitReview(tpl.id)}
                      className="max-md:min-h-[44px] rounded-lg px-2 py-1 text-xs text-blue-600 hover:bg-blue-50"
                    >申请公开</button>
                  )}
                  <button
                    onClick={() => handleDelete(tpl.id)}
                    className="max-md:min-h-[44px] rounded-lg px-2 py-1 text-xs text-rose-500 hover:bg-rose-50"
                  >删除</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* 模板广场 */
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {marketTemplates.length === 0 && (
            <div className="col-span-full py-12 text-center text-sm text-slate-400">暂无可用的公开模板</div>
          )}
          {marketTemplates.map(tpl => (
            <div key={tpl.id} className="rounded-2xl border border-[#e8edf2] bg-white p-4">
              <div className="flex items-start gap-2">
                {tpl.visibility === 'official' && (
                  <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-700">官方</span>
                )}
                <h3 className="font-medium text-slate-900">{tpl.name}</h3>
              </div>
              <p className="mt-1 text-xs text-slate-400 line-clamp-2">{tpl.description || '无描述'}</p>
              <div className="mt-2 flex items-center gap-2">
                {tpl.category && (
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{tpl.category}</span>
                )}
                <span className="text-xs text-slate-400">
                  {tpl.author?.username || '未知'} · 使用 {tpl.usage_count} 次
                </span>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={() => handleLike(tpl)}
                  className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                    tpl.is_liked ? 'bg-rose-50 text-rose-600' : 'text-slate-400 hover:bg-slate-50'
                  }`}
                >
                  <Heart size={14} className={tpl.is_liked ? 'fill-rose-500 text-rose-500' : 'text-slate-400'} /> {tpl.like_count}
                </button>
                <button
                  onClick={() => handleFork(tpl)}
                  className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-slate-50"
                >复制使用</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
