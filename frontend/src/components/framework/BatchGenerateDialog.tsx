import { useState } from 'react';
import { Loader2, X, CheckSquare, Square, FileText } from 'lucide-react';
import type { FrameworkChapter } from './types';
import type { Chapter as ActualChapter, ChapterBatchProgress } from '../../api';

interface Props {
  isOpen: boolean;
  chapters: FrameworkChapter[];
  actualChapters: ActualChapter[];
  onClose: () => void;
  onSubmit: (chapterNumbers: number[]) => Promise<void>;
  batchRunning: boolean;
  batchProgress: ChapterBatchProgress | null;
}

function hasGeneratedChapterContent(chapter?: ActualChapter): boolean {
  if (!chapter) return false;
  return Boolean(
    (chapter.novel_content && chapter.novel_content.trim()) ||
    (Array.isArray(chapter.messages) && chapter.messages.length > 0),
  );
}

export default function BatchGenerateDialog({
  isOpen,
  chapters,
  actualChapters,
  onClose,
  onSubmit,
  batchRunning,
  batchProgress,
}: Props) {
  const [selected, setSelected] = useState<Set<number>>(new Set());

  if (!isOpen) return null;

  const actualChapterMap = new Map(actualChapters.map((ch) => [ch.chapter_number, ch]));

  const availableChapters = chapters.filter((ch) => {
    const actual = actualChapterMap.get(ch.chapter_number);
    return !hasGeneratedChapterContent(actual);
  });

  const toggleChapter = (chapterNumber: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(chapterNumber)) {
        next.delete(chapterNumber);
      } else {
        next.add(chapterNumber);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === availableChapters.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(availableChapters.map((ch) => ch.chapter_number)));
    }
  };

  const handleSubmit = async () => {
    if (selected.size === 0) return;
    await onSubmit(Array.from(selected).sort((a, b) => a - b));
  };

  const selectedCount = selected.size;
  const maxAllowed = 10;
  const canSubmit = selectedCount > 0 && selectedCount <= maxAllowed && !batchRunning;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="relative w-full max-w-2xl max-h-[80vh] bg-white rounded-lg shadow-xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">批量生成章节正文</h2>
          <button
            onClick={onClose}
            disabled={batchRunning}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {availableChapters.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">所有章节已生成正文，无可生成章节</p>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <button
                  onClick={toggleAll}
                  disabled={batchRunning}
                  className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 disabled:opacity-40"
                >
                  {selected.size === availableChapters.length ? (
                    <>
                      <CheckSquare size={14} />
                      取消全选
                    </>
                  ) : (
                    <>
                      <Square size={14} />
                      全选
                    </>
                  )}
                </button>
                <span className="text-xs text-slate-500">
                  已选 {selectedCount} / {availableChapters.length} 话（最多 {maxAllowed} 话）
                </span>
              </div>

              <div className="space-y-2">
                {availableChapters.map((chapter) => {
                  const isSelected = selected.has(chapter.chapter_number);
                  const actColors: Record<string, string> = {
                    '1': 'border-l-blue-400',
                    '2': 'border-l-sky-400',
                    '3': 'border-l-emerald-400',
                  };
                  const actBorder = actColors[String(chapter.act)] || 'border-l-slate-300';

                  return (
                    <button
                      key={chapter.chapter_number}
                      onClick={() => toggleChapter(chapter.chapter_number)}
                      disabled={batchRunning}
                      className={`w-full text-left rounded-xl border border-l-4 ${actBorder} px-3 py-2.5 transition-all disabled:opacity-40 ${
                        isSelected ? 'bg-blue-50 border-blue-200' : 'bg-slate-50 border-slate-200 hover:bg-slate-100'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {isSelected ? (
                          <CheckSquare size={16} className="shrink-0 text-blue-600" />
                        ) : (
                          <Square size={16} className="shrink-0 text-slate-400" />
                        )}
                        <span className="w-14 shrink-0 text-xs font-mono text-slate-500">第{chapter.chapter_number}话</span>
                        <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-700">{chapter.title}</span>
                      </div>
                      {(chapter.summary || (chapter.key_events && chapter.key_events.length > 0)) && (
                        <p className="mt-1.5 ml-6 text-[11px] leading-relaxed text-slate-500 line-clamp-2">
                          {chapter.summary || chapter.key_events?.join('；')}
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* Progress Display */}
          {batchRunning && batchProgress && (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-amber-800">生成进度</span>
                <span className="text-xs text-amber-600">
                  {batchProgress.batch_completed.length + batchProgress.batch_failed.length} / {batchProgress.batch_total}
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-amber-100">
                <div
                  className="h-full bg-amber-500 transition-all duration-300"
                  style={{ width: `${Math.round(((batchProgress.batch_completed.length + batchProgress.batch_failed.length) / batchProgress.batch_total) * 100)}%` }}
                />
              </div>
              {batchProgress.message && (
                <p className="text-[11px] text-amber-700">
                  {batchProgress.message}
                </p>
              )}
              {batchProgress.batch_failed.length > 0 && (
                <p className="text-[11px] text-red-600">
                  {batchProgress.batch_failed.length} 章失败
                </p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 bg-slate-50">
          <div className="text-xs text-slate-500">
            {selectedCount > maxAllowed && (
              <span className="text-red-600">超出最大限制 {maxAllowed} 话</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              disabled={batchRunning}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40"
            >
              {batchRunning ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  生成中...
                </>
              ) : (
                <>
                  <FileText size={14} />
                  开始生成 ({selectedCount})
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
