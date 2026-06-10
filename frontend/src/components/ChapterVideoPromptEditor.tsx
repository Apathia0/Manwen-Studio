import { useState } from 'react';
import { ChevronDown, ChevronUp, PenLine, Sparkles } from 'lucide-react';

interface ChapterVideoPromptEditorProps {
  value: string;
  onChange: (value: string) => void;
  onReanalyze?: () => void;
  disabled?: boolean;
}

export default function ChapterVideoPromptEditor({
  value,
  onChange,
  onReanalyze,
  disabled = false,
}: ChapterVideoPromptEditorProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl border border-[#e5edf8] bg-white">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-slate-600 hover:text-slate-800"
      >
        <span className="inline-flex items-center gap-1.5">
          <PenLine size={12} />
          故事版提示词
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {open && (
        <div className="border-t border-[#e5edf8] px-3 py-2">
          <textarea
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            rows={4}
            className="w-full resize-none rounded-lg border border-[#d7e3f4] bg-slate-50 p-2 text-xs text-slate-700 outline-none transition-colors focus:border-blue-400 focus:bg-white focus:ring-1 focus:ring-blue-200 disabled:opacity-50"
            placeholder="输入故事版提示词，或点击下方按钮由 AI 重新生成..."
          />
          {onReanalyze && (
            <button
              type="button"
              onClick={onReanalyze}
              disabled={disabled}
              className="mt-2 inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              <Sparkles size={11} />
              重新分析提示词
            </button>
          )}
        </div>
      )}
    </div>
  );
}
