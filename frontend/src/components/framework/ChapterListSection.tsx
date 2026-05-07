import { BarChart3, FileText, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { assessQuality, expandChapter } from '../../api';
import type { FrameworkChapter } from './types';
import { STATUS_COLORS, STATUS_LABELS } from './types';

interface Props {
  chapters: FrameworkChapter[] | null;
  storyId: number;
  onChapterSelect: (chapterNumber: number) => void;
  onUpdate: () => void | Promise<void>;
}

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const colorClass = STATUS_COLORS[status] || 'bg-gray-600 text-gray-200';
  const label = STATUS_LABELS[status] || status;
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${colorClass}`}>
      {label}
    </span>
  );
}

export default function ChapterListSection({ chapters, storyId, onChapterSelect, onUpdate }: Props) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<'expand' | 'assess' | null>(null);
  const [error, setError] = useState('');

  const hasContent = chapters && chapters.length > 0;

  const handleExpand = async (chapter: FrameworkChapter) => {
    if (busyId !== null) return;
    setBusyId(chapter.chapter_number);
    setBusyAction('expand');
    setError('');
    try {
      await expandChapter(storyId, {
        act: chapter.act,
        chapter_number: chapter.chapter_number,
        chapter_title: chapter.title,
        key_events: chapter.key_events,
      });
      await onUpdate();
      onChapterSelect(chapter.chapter_number);
    } catch (err: any) {
      setError(err.message || '扩写失败');
    } finally {
      setBusyId(null);
      setBusyAction(null);
    }
  };

  const handleAssess = async (chapter: FrameworkChapter) => {
    if (!chapter.id || busyId !== null) return;
    setBusyId(chapter.chapter_number);
    setBusyAction('assess');
    setError('');
    try {
      await assessQuality(chapter.id);
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '评估失败');
    } finally {
      setBusyId(null);
      setBusyAction(null);
    }
  };

  if (!hasContent) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-gray-600">先生成故事框架，章节规划会在这里展示。</p>
      </div>
    );
  }

  const actColors: Record<string, string> = {
    '1': 'border-l-violet-500/50',
    '2': 'border-l-amber-500/50',
    '3': 'border-l-emerald-500/50',
  };

  return (
    <div className="space-y-1.5">
      {chapters!.map((chapter) => {
        const actBorder = actColors[String(chapter.act)] || 'border-l-gray-700/50';
        const hasDraft = typeof chapter.id === 'number';
        const isBusy = busyId === chapter.chapter_number;
        return (
          <div
            key={chapter.chapter_number}
            className={`group px-3 py-2 rounded-lg border-l-2 ${actBorder} bg-gray-900/30 hover:bg-gray-800/50 transition-colors`}
          >
            <div
              className={`flex items-center gap-2 ${hasDraft ? 'cursor-pointer' : ''}`}
              onClick={() => hasDraft && onChapterSelect(chapter.chapter_number)}
            >
              <span className="text-xs font-mono text-gray-600 shrink-0 w-12">
                第{chapter.chapter_number}话
              </span>
              <span className="flex-1 text-xs text-gray-300 truncate min-w-0">
                {chapter.title}
              </span>
              <StatusBadge status={chapter.status} />
            </div>

            {chapter.key_events && chapter.key_events.length > 0 && (
              <p className="mt-2 text-[11px] text-gray-500 leading-relaxed line-clamp-2">
                {chapter.key_events.join('、')}
              </p>
            )}

            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={() => void handleExpand(chapter)}
                disabled={busyId !== null}
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium
                           bg-violet-600/15 text-violet-300 border border-violet-700/40 hover:bg-violet-600/25
                           disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {isBusy && busyAction === 'expand' ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <FileText size={12} />
                )}
                {hasDraft ? '重新扩写正文' : '生成正文'}
              </button>

              {chapter.id && (
                <button
                  onClick={() => void handleAssess(chapter)}
                  disabled={busyId !== null}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium
                             bg-gray-800 text-gray-400 border border-gray-700 hover:bg-gray-700 hover:text-gray-200
                             disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isBusy && busyAction === 'assess' ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <BarChart3 size={12} />
                  )}
                  质量评估
                </button>
              )}
            </div>
          </div>
        );
      })}

      {error && <p className="text-xs text-red-400 px-1 pt-1">{error}</p>}
    </div>
  );
}
