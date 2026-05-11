import { useCallback, useRef } from 'react';
import { Loader2 } from 'lucide-react';

export interface TextSelection {
  text: string;
  start: number;
  end: number;
}

interface Props {
  content: string | null;
  draftContent?: string;
  editing?: boolean;
  loading?: boolean;
  saving?: boolean;
  onDraftChange?: (value: string) => void;
  onTextSelect: (selection: TextSelection | null) => void;
}

export default function TextEditor({
  content,
  draftContent = '',
  editing = false,
  loading = false,
  saving = false,
  onDraftChange,
  onTextSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseUp = useCallback(() => {
    if (editing) {
      onTextSelect(null);
      return;
    }
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || !containerRef.current) {
      onTextSelect(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (range.collapsed || !containerRef.current.contains(range.commonAncestorContainer)) {
      onTextSelect(null);
      return;
    }
    const text = selection.toString();
    if (!text.trim()) {
      onTextSelect(null);
      return;
    }

    const preRange = range.cloneRange();
    preRange.selectNodeContents(containerRef.current);
    preRange.setEnd(range.startContainer, range.startOffset);
    const start = preRange.toString().length;
    const end = start + text.length;
    onTextSelect({ text, start, end });
  }, [editing, onTextSelect]);

  if (loading) {
    return (
      <div className="flex-1 flex flex-col min-h-0 bg-[#fbfcf8]">
        <div className="flex-1 p-6 space-y-4">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="flex gap-4">
              <div
                className="h-4 bg-[#edf1ec] rounded animate-pulse"
                style={{ width: `${60 + Math.random() * 40}%` }}
              />
            </div>
          ))}
        </div>
        <div className="absolute inset-0 flex items-center justify-center bg-[#fcfcfa]/20">
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-white/95 border border-[#d9dfd7] shadow-lg">
            <Loader2 size={18} className="animate-spin text-blue-500" />
            <span className="text-sm text-slate-700 font-medium">内容生成中...</span>
          </div>
        </div>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="flex-1 min-h-0 bg-[#fbfcf8] relative">
        <textarea
          value={draftContent}
          onChange={(e) => onDraftChange?.(e.target.value)}
          className="w-full h-full resize-none bg-transparent px-6 md:px-10 py-8 text-base leading-8 text-slate-800
                     whitespace-pre-wrap font-['Lora',Georgia,serif] outline-none"
          placeholder="输入或编辑正文内容..."
        />
        {saving && (
          <div className="absolute top-4 right-4 inline-flex items-center gap-2 rounded-full bg-white/95 border border-[#d9dfd7] px-3 py-1.5 text-xs text-blue-600">
            <Loader2 size={13} className="animate-spin" />
            保存中...
          </div>
        )}
      </div>
    );
  }

  if (!content) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#fbfcf8]">
        <div className="flex flex-col items-center gap-3 text-center max-w-sm px-6">
          <div className="w-14 h-14 rounded-2xl bg-[#edf1ec] flex items-center justify-center border border-[#d9dfd7]">
            <svg
              className="w-7 h-7 text-slate-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
              />
            </svg>
          </div>
          <div>
            <p className="text-sm text-slate-500 font-medium">尚无小说内容</p>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              点击左侧大纲节点或章节生成内容
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto bg-[#fbfcf8] select-text"
      onMouseUp={handleMouseUp}
    >
      <div
        className="max-w-3xl mx-auto px-6 md:px-10 py-8 text-base leading-8 text-slate-800 whitespace-pre-wrap font-['Lora',Georgia,serif] selection:bg-blue-200"
        style={{ fontVariantLigatures: 'common' }}
      >
        {content}
      </div>
    </div>
  );
}
