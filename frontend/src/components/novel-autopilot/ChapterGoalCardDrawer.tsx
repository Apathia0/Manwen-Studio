import { useState } from 'react';
import { Loader2, Plus, Save, Sparkles, Trash2, X } from 'lucide-react';
import type { ChapterGoalCard } from '../../api';

interface Props {
  chapterNumber: number;
  chapterTitle: string;
  goalCard: ChapterGoalCard | null;
  onGenerate: () => Promise<void>;
  onUpdate: (data: Partial<ChapterGoalCard>) => Promise<void>;
  onClose: () => void;
  loading: boolean;
}

export default function ChapterGoalCardDrawer({
  chapterNumber,
  chapterTitle,
  goalCard,
  onGenerate,
  onUpdate,
  onClose,
  loading,
}: Props) {
  const [目标, set目标] = useState(goalCard?.goal ?? '');
  const [主线推进, set主线推进] = useState<string[]>(goalCard?.plot_progress ?? []);
  const [角色关系变化, set角色关系变化] = useState<string[]>(goalCard?.relationship_change ?? []);
  const [悬念钩子, set悬念钩子] = useState(goalCard?.hook ?? '');
  const [爽点回报, set爽点回报] = useState(goalCard?.payoff ?? '');
  const [场景建议, set场景建议] = useState<string[]>(goalCard?.scene_suggestions ?? []);
  const [保存中, set保存中] = useState(false);

  function 收集数据(): Partial<ChapterGoalCard> {
    return {
      goal: 目标,
      plot_progress: 主线推进.filter(Boolean),
      relationship_change: 角色关系变化.filter(Boolean),
      hook: 悬念钩子,
      payoff: 爽点回报,
      scene_suggestions: 场景建议.filter(Boolean),
    };
  }

  async function 处理保存() {
    set保存中(true);
    try {
      await onUpdate(收集数据());
    } finally {
      set保存中(false);
    }
  }

  function 添加条目(list: string[], setter: (list: string[]) => void) {
    setter([...list, '']);
  }

  function 更新条目(list: string[], setter: (list: string[]) => void, index: number, value: string) {
    const 新的 = [...list];
    新的[index] = value;
    setter(新的);
  }

  function 删除条目(list: string[], setter: (list: string[]) => void, index: number) {
    setter(list.filter((_, i) => i !== index));
  }

  function 渲染列表编辑器({
    label,
    列表,
    set列表,
    placeholder,
  }: {
    label: string;
    列表: string[];
    set列表: (v: string[]) => void;
    placeholder: string;
  }) {
    return (
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
          <button
            type="button"
            onClick={() => 添加条目(列表, set列表)}
            className="inline-flex items-center gap-0.5 text-[10px] text-[#2563eb] hover:text-[#1d4ed8] transition-colors"
          >
            <Plus size={11} />
            添加
          </button>
        </div>
        <div className="space-y-1.5">
          {列表.map((item, index) => (
            <div key={index} className="flex items-center gap-1.5">
              <input
                value={item}
                onChange={(e) => 更新条目(列表, set列表, index, e.target.value)}
                placeholder={placeholder}
                className="flex-1 rounded-lg border border-[#d7e3f4] bg-[#fafdff] px-3 py-1.5 text-xs text-slate-800
                           outline-none focus:border-[#93c5fd] focus:bg-white transition-colors"
              />
              <button
                type="button"
                onClick={() => 删除条目(列表, set列表, index)}
                className="p-1 text-slate-400 hover:text-red-500 transition-colors"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          {列表.length === 0 && (
            <button
              type="button"
              onClick={() => 添加条目(列表, set列表)}
              className="w-full rounded-lg border border-dashed border-[#d7e3f4] py-2 text-[11px] text-slate-400 hover:text-[#2563eb] hover:border-[#2563eb] transition-colors"
            >
              <Plus size={12} className="inline mr-1" />
              添加{label}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-lg bg-white shadow-2xl flex flex-col animate-slide-in-right">
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#d7e3f4] shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles size={15} className="text-[#2563eb] shrink-0" />
            <h2 className="text-sm font-semibold text-slate-900 truncate">
              第 {chapterNumber} 章 · {chapterTitle || '未命名章节'}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {!goalCard ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Sparkles size={36} className="text-[#93c5fd] mb-3" />
              <p className="text-sm text-slate-600 mb-4 leading-relaxed">
                生成章节目标卡，为本章设定明确的目标、悬念和爽点，让每一章都有清晰的创作方向。
              </p>
              <button
                onClick={() => void onGenerate()}
                disabled={loading}
                className="inline-flex items-center gap-1.5 px-5 py-2.5 text-sm font-medium rounded-xl
                           bg-[#2563eb] hover:bg-[#1d4ed8] text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)]
                           disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                {loading ? '正在生成...' : '生成目标卡'}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">章节目标</span>
                <textarea
                  value={目标}
                  onChange={(e) => set目标(e.target.value)}
                  rows={3}
                  placeholder="本章要达成什么目标..."
                  className="mt-1 w-full rounded-lg border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-xs text-slate-800
                             outline-none focus:border-[#93c5fd] focus:bg-white transition-colors resize-y"
                />
              </div>

              {渲染列表编辑器({
                label: '主线推进',
                列表: 主线推进,
                set列表: set主线推进,
                placeholder: '主线事件...',
              })}

              {渲染列表编辑器({
                label: '角色关系变化',
                列表: 角色关系变化,
                set列表: set角色关系变化,
                placeholder: '关系变化...',
              })}

              <div>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">悬念/结尾钩子</span>
                <textarea
                  value={悬念钩子}
                  onChange={(e) => set悬念钩子(e.target.value)}
                  rows={2}
                  placeholder="本章结束时的悬念或钩子..."
                  className="mt-1 w-full rounded-lg border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-xs text-slate-800
                             outline-none focus:border-[#93c5fd] focus:bg-white transition-colors resize-y"
                />
              </div>

              <div>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">爽点/回报</span>
                <textarea
                  value={爽点回报}
                  onChange={(e) => set爽点回报(e.target.value)}
                  rows={2}
                  placeholder="本章给读者的爽点或回报..."
                  className="mt-1 w-full rounded-lg border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-xs text-slate-800
                             outline-none focus:border-[#93c5fd] focus:bg-white transition-colors resize-y"
                />
              </div>

              {渲染列表编辑器({
                label: '场景建议',
                列表: 场景建议,
                set列表: set场景建议,
                placeholder: '场景描述...',
              })}
            </div>
          )}
        </div>

        {goalCard && (
          <div className="border-t border-[#d7e3f4] px-5 py-3 shrink-0 space-y-2">
            <button
              onClick={() => void 处理保存()}
              disabled={保存中}
              className="inline-flex items-center justify-center gap-1.5 w-full px-4 py-2.5 text-sm font-medium rounded-xl
                         bg-[#2563eb] hover:bg-[#1d4ed8] text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)]
                         disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {保存中 ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              {保存中 ? '保存中...' : '保存目标卡'}
            </button>
            <button
              onClick={() => void onGenerate()}
              disabled={loading}
              className="inline-flex items-center justify-center gap-1.5 w-full px-4 py-2 text-xs font-medium rounded-xl
                         border border-[#d7e3f4] text-slate-600 hover:bg-slate-50
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {loading ? '重新生成中...' : '重新生成目标卡'}
            </button>
          </div>
        )}
      </div>

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slideInRight 0.25s ease-out;
        }
      `}</style>
    </div>
  );
}
