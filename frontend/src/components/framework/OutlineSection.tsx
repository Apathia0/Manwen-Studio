import { useMemo, useState } from 'react';
import { BookOpen, ChevronDown, ChevronRight, FileText, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { expandChapter, regenerateOutline, type Chapter, type Outline } from '../../api';

interface Props {
  outline: Outline | null;
  chapters: Chapter[];
  storyId: number;
  onChapterSelect: (chapterNumber: number) => void;
  onUpdate: () => void | Promise<void>;
}

interface PlannedChapter {
  chapter_number: number;
  title: string;
  summary?: string;
  key_events?: string[];
}

interface ActNode {
  act: string;
  name: string;
  summary?: string;
  chapters: PlannedChapter[];
}

function flattenActs(outline: Outline | null): ActNode[] {
  if (!outline?.three_acts || !Array.isArray(outline.three_acts)) return [];
  return outline.three_acts.map((act: any, index: number): ActNode => ({
    act: String(act?.act ?? index + 1),
    name: String(act?.title || act?.name || `第${index + 1}幕`),
    summary: typeof act?.summary === 'string' ? act.summary : undefined,
    chapters: Array.isArray(act?.chapters)
      ? act.chapters
          .map((chapter: any, chapterIndex: number): PlannedChapter => ({
            chapter_number: Number(chapter?.chapter_number ?? chapterIndex + 1),
            title: String(chapter?.title || `第${chapterIndex + 1}话`),
            summary: typeof chapter?.summary === 'string' ? chapter.summary : undefined,
            key_events: Array.isArray(chapter?.key_events)
              ? chapter.key_events.map((item: unknown) => String(item)).filter(Boolean)
              : undefined,
          }))
          .filter((chapter: PlannedChapter) => Number.isInteger(chapter.chapter_number) && chapter.chapter_number > 0)
      : [],
  }));
}

const ACT_COLORS: Record<string, string> = {
  '1': 'border-l-violet-500',
  '2': 'border-l-amber-500',
  '3': 'border-l-emerald-500',
};

const ACT_BADGE_COLORS: Record<string, string> = {
  '1': 'bg-violet-600/20 text-violet-300 border-violet-700/40',
  '2': 'bg-amber-600/20 text-amber-300 border-amber-700/40',
  '3': 'bg-emerald-600/20 text-emerald-300 border-emerald-700/40',
};

function ActCard({
  act,
  index,
  chapterMap,
  storyId,
  onChapterSelect,
  onUpdate,
  defaultExpanded,
}: {
  act: ActNode;
  index: number;
  chapterMap: Map<number, Chapter>;
  storyId: number;
  onChapterSelect: (n: number) => void;
  onUpdate: () => void | Promise<void>;
  defaultExpanded: boolean;
}) {
  const actKey = String(index + 1);
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [busyChapter, setBusyChapter] = useState<number | null>(null);
  const [error, setError] = useState('');
  const actPercentage = index === 0 ? '25%' : index === 1 ? '50%' : '25%';

  const handleExpand = async (chapter: PlannedChapter) => {
    if (busyChapter !== null) return;
    setBusyChapter(chapter.chapter_number);
    setError('');
    try {
      await expandChapter(storyId, {
        act: act.act,
        chapter_number: chapter.chapter_number,
        chapter_title: chapter.title,
        key_events: chapter.key_events,
      });
      await onUpdate();
      onChapterSelect(chapter.chapter_number);
    } catch (err: any) {
      setError(err.message || '生成正文失败');
    } finally {
      setBusyChapter(null);
    }
  };

  return (
    <div className={`border-l-2 pl-3 ${ACT_COLORS[actKey] || 'border-l-gray-700'}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between gap-2 py-1.5 text-left group"
      >
        <div className="flex items-center gap-2 min-w-0">
          <BookOpen size={13} className="text-gray-500 shrink-0" />
          <span className="text-sm font-medium text-gray-200 truncate group-hover:text-white transition-colors">
            {act.name}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${ACT_BADGE_COLORS[actKey] || 'bg-gray-700/30 text-gray-400 border-gray-700'}`}>
            {actPercentage}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] text-gray-600">{act.chapters.length} 章</span>
          {expanded ? <ChevronDown size={13} className="text-gray-500" /> : <ChevronRight size={13} className="text-gray-500" />}
        </div>
      </button>

      {expanded && act.summary && (
        <p className="text-[11px] text-gray-500 leading-relaxed ml-6 mb-1.5 line-clamp-2">{act.summary}</p>
      )}

      {expanded && act.chapters.length > 0 && (
        <div className="ml-5 space-y-1 mb-1">
          {act.chapters.map((chapter) => {
            const existing = chapterMap.get(chapter.chapter_number);
            const isBusy = busyChapter === chapter.chapter_number;
            return (
              <div key={chapter.chapter_number} className="rounded-md hover:bg-gray-800/40 transition-colors">
                <div className="flex items-center gap-2 px-2.5 py-1.5">
                  <button
                    onClick={() => existing && onChapterSelect(chapter.chapter_number)}
                    className={`flex flex-1 items-center gap-2 min-w-0 text-left ${existing ? 'cursor-pointer' : 'cursor-default'}`}
                  >
                    <span className="text-[10px] text-gray-600 font-mono shrink-0">
                      #{String(chapter.chapter_number).padStart(2, '0')}
                    </span>
                    <span className="truncate text-xs text-gray-300">{chapter.title}</span>
                  </button>
                  <button
                    onClick={() => (existing ? onChapterSelect(chapter.chapter_number) : void handleExpand(chapter))}
                    disabled={busyChapter !== null}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium
                               bg-violet-600/15 text-violet-300 border border-violet-700/40 hover:bg-violet-600/25
                               disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                  >
                    {isBusy ? <Loader2 size={11} className="animate-spin" /> : <FileText size={11} />}
                    {existing ? '打开' : '生成正文'}
                  </button>
                </div>
                {chapter.summary && (
                  <p className="px-2.5 pb-1.5 pl-8 text-[10px] text-gray-600 leading-relaxed line-clamp-2">
                    {chapter.summary}
                  </p>
                )}
              </div>
            );
          })}
          {error && <p className="text-xs text-red-400 px-2.5 pt-1">{error}</p>}
        </div>
      )}

      {expanded && act.chapters.length === 0 && (
        <p className="text-[11px] text-gray-600 italic ml-6 mb-1">暂无章节</p>
      )}
    </div>
  );
}

export default function OutlineSection({ outline, chapters, storyId, onChapterSelect, onUpdate }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedAll, setExpandedAll] = useState(true);

  const acts = useMemo(() => flattenActs(outline), [outline]);
  const chapterMap = useMemo(() => new Map(chapters.map((chapter) => [chapter.chapter_number, chapter])), [chapters]);
  const hasContent = acts.length > 0;

  const handleRegenerate = async () => {
    setLoading(true);
    setError('');
    try {
      await regenerateOutline(storyId);
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '生成失败');
    } finally {
      setLoading(false);
    }
  };

  if (!hasContent && !loading) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-gray-600">点击下方按钮，AI 会自动生成故事的三幕式大纲结构。</p>
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 border border-violet-700/40
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <RefreshCw size={13} className="animate-spin" />
          ) : (
            <Sparkles size={13} />
          )}
          AI 生成大纲
        </button>
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    );
  }

  const totalChapters = acts.reduce((sum, act) => sum + act.chapters.length, 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        {acts.length > 0 && (
          <span className="text-xs text-gray-500">{acts.length} 幕 · {totalChapters} 章</span>
        )}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpandedAll(!expandedAll)}
            className="text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
          >
            {expandedAll ? '全部收起' : '全部展开'}
          </button>
          <button
            onClick={handleRegenerate}
            disabled={loading}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg
                       bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 border border-gray-700
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
            优化大纲
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        {acts.map((act, i) => (
          <ActCard
            key={`${act.act}-${i}`}
            act={act}
            index={i}
            chapterMap={chapterMap}
            storyId={storyId}
            onChapterSelect={onChapterSelect}
            onUpdate={onUpdate}
            defaultExpanded={expandedAll}
          />
        ))}
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
