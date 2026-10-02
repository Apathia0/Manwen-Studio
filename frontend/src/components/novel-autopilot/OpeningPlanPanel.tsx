import { Loader2, Sparkles } from 'lucide-react';
import type { OpeningPlanResponse } from '../../api';

interface Props {
  openingPlan: OpeningPlanResponse | null;
  onGenerate: () => Promise<void>;
  loading: boolean;
}

const 钩子颜色: Record<string, string> = {
  book_hook: 'border-l-[#2563eb]',
  chapter_1_hook: 'border-l-[#7c3aed]',
  chapter_3_hook: 'border-l-[#0891b2]',
  chapter_10_payoff: 'border-l-[#059669]',
  chapter_20_climax: 'border-l-[#dc2626]',
};

const 钩子标签: Record<string, string> = {
  book_hook: '全书总钩子',
  chapter_1_hook: '第一章爆点',
  chapter_3_hook: '前三章钩子',
  chapter_10_payoff: '前十章追读回报',
  chapter_20_climax: '前二十章大高潮',
};

export default function OpeningPlanPanel({ openingPlan, onGenerate, loading }: Props) {
  return (
    <div className="flex flex-col h-full bg-[#fcfcfa]">
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#d7e3f4] shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-[#2563eb]" />
          <h2 className="text-sm font-semibold text-slate-900 tracking-wide">开书强化方案</h2>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {!openingPlan ? (
          <div className="flex flex-col items-center justify-center h-full px-5 text-center">
            <Sparkles size={36} className="text-[#93c5fd] mb-3" />
            <p className="text-sm text-slate-600 mb-4 leading-relaxed">
              生成开书强化方案，规划全书钩子、章节爆点和前二十章的高潮节奏，让作品开篇就有强力吸引力。
            </p>
            <button
              onClick={() => void onGenerate()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-5 py-2.5 text-sm font-medium rounded-xl
                         bg-[#2563eb] hover:bg-[#1d4ed8] text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)]
                         disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {loading ? '正在生成...' : '生成开书方案'}
            </button>
          </div>
        ) : (
          <div className="px-5 py-4 space-y-3">
            {(
              [
                ['book_hook', openingPlan.book_hook],
                ['chapter_1_hook', openingPlan.chapter_1_hook],
                ['chapter_3_hook', openingPlan.chapter_3_hook],
                ['chapter_10_payoff', openingPlan.chapter_10_payoff],
                ['chapter_20_climax', openingPlan.chapter_20_climax],
              ] as const
            ).map(([key, content]) => (
              <div
                key={key}
                className={`rounded-xl border border-[#d7e3f4] bg-white pl-4 pr-4 py-3 border-l-4 ${钩子颜色[key] ?? 'border-l-[#2563eb]'}`}
              >
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  {钩子标签[key]}
                </div>
                <div className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{content}</div>
              </div>
            ))}

            {openingPlan.opening_notes.length > 0 && (
              <div className="rounded-xl border border-[#d7e3f4] bg-white px-4 py-3">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-2">开书备忘</div>
                <div className="flex flex-wrap gap-1.5">
                  {openingPlan.opening_notes.map((note, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium
                                 bg-blue-50 text-blue-700 border border-blue-200"
                    >
                      {note}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="pt-2">
              <button
                onClick={() => void onGenerate()}
                disabled={loading}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg
                           bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100
                           disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                {loading ? '重新生成中...' : '重新生成'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
