import { useEffect, useState } from 'react';
import { listPendingTemplates, approveTemplate, rejectTemplate, type PromptTemplateItem } from '../api';

export default function AdminTemplateReview() {
  const [templates, setTemplates] = useState<PromptTemplateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});

  async function loadPending() {
    setLoading(true);
    setError(null);
    try {
      const data = await listPendingTemplates(1, 50);
      setTemplates(data.templates);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadPending(); }, []);

  function setNote(templateId: number, value: string) {
    setNotes(prev => ({ ...prev, [templateId]: value }));
  }

  async function handleApprove(templateId: number, visibility: 'public' | 'official') {
    try {
      await approveTemplate(templateId, visibility, notes[templateId] || '');
      setNotes(prev => ({ ...prev, [templateId]: '' }));
      loadPending();
    } catch (e: any) {
      alert(e.message || '操作失败');
    }
  }

  async function handleReject(templateId: number) {
    const note = notes[templateId] || '';
    if (!note.trim()) { alert('请填写拒绝原因'); return; }
    try {
      await rejectTemplate(templateId, note);
      setNotes(prev => ({ ...prev, [templateId]: '' }));
      loadPending();
    } catch (e: any) {
      alert(e.message || '操作失败');
    }
  }

  if (loading) return <div className="px-6 py-8 text-center text-sm text-slate-400">加载中...</div>;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="mb-2 text-2xl font-bold text-slate-900">模板审核管理</h1>
      <p className="mb-6 text-sm text-slate-500">审核用户提交的公开模板申请，共 {templates.length} 个待审核</p>

      {error && <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

      {templates.length === 0 ? (
        <div className="rounded-2xl border border-[#e8edf2] bg-white py-16 text-center text-sm text-slate-400">暂无待审核的模板</div>
      ) : (
        <div className="space-y-4">
          {templates.map(tpl => (
            <div key={tpl.id} className="rounded-2xl border border-[#e8edf2] bg-white p-5">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-medium text-slate-900">{tpl.name}</h3>
                  <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-700">待审核</span>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  作者：{tpl.author?.username || '未知'} | 分类：{tpl.category || '无'} | 提交：{tpl.submitted_at?.slice(0, 16).replace('T', ' ') || '未知'}
                </p>
                <p className="mt-1 text-xs text-slate-500">{tpl.description || '无描述'}</p>

                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-600">查看提示词内容</summary>
                  <div className="mt-2 space-y-2 text-xs">
                    {['framework_prompt','chapter_prompt','character_prompt','manga_style_prompt'].map(key => {
                      const val = (tpl as any)[key];
                      if (!val) return null;
                      const labels: Record<string,string> = {framework_prompt:'框架生成',chapter_prompt:'正文扩写',character_prompt:'角色生成',manga_style_prompt:'漫画风格'};
                      return (
                        <div key={key}>
                          <span className="font-medium text-slate-600">{labels[key]}：</span>
                          <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-2 text-slate-500">{val}</pre>
                        </div>
                      );
                    })}
                  </div>
                </details>
              </div>

              <div className="mt-4 border-t border-[#f0f3f7] pt-3">
                <input
                  value={notes[tpl.id] || ''}
                  onChange={e => setNote(tpl.id, e.target.value)}
                  className="mb-2 w-full rounded-xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-1.5 text-xs outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
                  placeholder="审核备注（拒绝时必填）"
                />
                <div className="flex items-center gap-2">
                  <button onClick={() => handleApprove(tpl.id, 'public')} className="rounded-xl bg-green-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-green-700">通过</button>
                  <button onClick={() => handleApprove(tpl.id, 'official')} className="rounded-xl bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700">通过并推荐</button>
                  <button onClick={() => handleReject(tpl.id)} className="rounded-xl border border-rose-200 bg-white px-4 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50">拒绝</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
