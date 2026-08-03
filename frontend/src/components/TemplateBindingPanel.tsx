import { useEffect, useState } from 'react';
import {
  getStoryTemplate,
  bindStoryTemplate,
  unbindStoryTemplate,
  listMyTemplates,
  listPublicTemplates,
  type PromptTemplateItem,
} from '../api';
import { toast } from '../lib/toast';

interface Props {
  storyId: number;
}

export default function TemplateBindingPanel({ storyId }: Props) {
  const [currentTemplate, setCurrentTemplate] = useState<PromptTemplateItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPicker, setShowPicker] = useState(false);
  const [myTemplates, setMyTemplates] = useState<PromptTemplateItem[]>([]);
  const [marketTemplates, setMarketTemplates] = useState<PromptTemplateItem[]>([]);

  async function loadCurrent() {
    setLoading(true);
    try {
      const res = await getStoryTemplate(storyId);
      setCurrentTemplate(res.template);
    } catch {
      // 忽略加载失败
    } finally {
      setLoading(false);
    }
  }

  async function loadTemplates() {
    try {
      const [my, market] = await Promise.all([
        listMyTemplates({ page_size: 100 }),
        listPublicTemplates({ page_size: 100, sort: 'popular' }),
      ]);
      setMyTemplates(my.templates);
      setMarketTemplates(market.templates);
    } catch {
      // 忽略
    }
  }

  useEffect(() => { loadCurrent(); }, [storyId]);

  async function handleSelect(tpl: PromptTemplateItem) {
    try {
      await bindStoryTemplate(storyId, tpl.id);
      setCurrentTemplate(tpl);
      setShowPicker(false);
    } catch (e: any) {
      toast.error(e.message || '绑定失败');
    }
  }

  async function handleUnbind() {
    try {
      await unbindStoryTemplate(storyId);
      setCurrentTemplate(null);
    } catch (e: any) {
      toast.error(e.message || '解绑失败');
    }
  }

  if (loading) return <span className="text-xs text-slate-400">加载中...</span>;

  return (
    <div className="relative min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-400">提示词模板：</span>
        {currentTemplate ? (
          <>
            <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
              {currentTemplate.name}
            </span>
            <button onClick={handleUnbind} className="text-xs text-rose-500 hover:underline">解绑</button>
          </>
        ) : (
          <span className="text-xs text-slate-400">系统默认</span>
        )}
        <button
          onClick={() => { setShowPicker(!showPicker); if (!showPicker) loadTemplates(); }}
          className="rounded-lg border border-[#d7e3f4] px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
        >
          {showPicker ? '关闭' : '选择模板'}
        </button>
      </div>

      {showPicker && (
        <div className="absolute right-0 top-8 z-50 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-[#e8edf2] bg-white p-4 shadow-xl">
          <h4 className="mb-3 text-sm font-medium text-slate-800">选择提示词模板</h4>
          <div className="mb-2 text-xs font-medium text-slate-500">我的模板</div>
          <div className="mb-3 max-h-40 space-y-1 overflow-y-auto">
            {myTemplates.map(tpl => (
              <button
                key={tpl.id}
                onClick={() => handleSelect(tpl)}
                className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-blue-50"
              >
                {tpl.name}
                {tpl.category && <span className="ml-2 text-slate-400">({tpl.category})</span>}
              </button>
            ))}
            {myTemplates.length === 0 && <p className="text-xs text-slate-400">暂无</p>}
          </div>
          <div className="mb-2 text-xs font-medium text-slate-500">公开模板</div>
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {marketTemplates.map(tpl => (
              <button
                key={tpl.id}
                onClick={() => handleSelect(tpl)}
                className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-blue-50"
              >
                {tpl.name}
                <span className="ml-1 text-slate-400">@{tpl.author?.username || '未知'}</span>
                {tpl.visibility === 'official' && <span className="ml-1 text-blue-500">[官方]</span>}
              </button>
            ))}
            {marketTemplates.length === 0 && <p className="text-xs text-slate-400">暂无</p>}
          </div>
        </div>
      )}
    </div>
  );
}
