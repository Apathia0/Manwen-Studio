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
    name: String(act?.title || act?.name || `第 ${index + 1} 幕`),
    summary: typeof act?.summary === 'string' ? act.summary : undefined,
    chapters: Array.isArray(act?.chapters)
      ? act.chapters
          .map((chapter: any, chapterIndex: number): PlannedChapter => ({
            chapter_number: Number(chapter?.chapter_number ?? chapterIndex + 1),
            title: String(chapter?.title || `第 ${chapterIndex + 1} 话`),
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
  '1': 'border-l-blue-400',
  '2': 'border-l-sky-400',
  '3': 'border-l-emerald-400',
};

const ACT_BADGE_COLORS: Record<string, string> = {
  '1': 'bg-blue-50 text-blue-700 border-blue-200',
  '2': 'bg-sky-50 text-sky-700 border-sky-200',
  '3': 'bg-emerald-50 text-emerald-700 border-emerald-200',
};

function hasGeneratedChapterContent(chapter: Chapter | undefined): boolean {
  if (!chapter) return false;
  return Boolean(
    (chapter.novel_content && chapter.novel_content.trim()) ||
    (Array.isArray(chapter.messages) && chapter.messages.length > 0),
  );
}

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
    <div className={`border-l-2 pl-3 ${ACT_COLORS[actKey] || 'border-l-slate-300'}`}>
      <button onClick={() => setExpanded(!expanded)} className="w-full flex items-center justify-between gap-2 py-1.5 text-left group">
        <div className="flex items-center gap-2 min-w-0">
          <BookOpen size={13} className="text-slate-400 shrink-0" />
          <span className="text-sm font-medium text-slate-800 truncate group-hover:text-slate-900 transition-colors">{act.name}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${ACT_BADGE_COLORS[actKey] || 'bg-slate-100 text-slate-600 border-slate-200'}`}>
            {actPercentage}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] text-slate-500">{act.chapters.length} 章</span>
          {expanded ? <ChevronDown size={13} className="text-slate-400" /> : <ChevronRight size={13} className="text-slate-400" />}
        </div>
      </button>

      {expanded && act.summary && <p className="text-[11px] text-slate-500 leading-relaxed ml-6 mb-1.5 line-clamp-2">{act.summary}</p>}

      {expanded && act.chapters.length > 0 && (
        <div className="ml-5 space-y-1 mb-1">
          {act.chapters.map((chapter) => {
            const existing = chapterMap.get(chapter.chapter_number);
            const canOpen = hasGeneratedChapterContent(existing);
            const isBusy = busyChapter === chapter.chapter_number;

            return (
              <div key={chapter.chapter_number} className="rounded-md hover:bg-slate-50 transition-colors">
                <div className="flex items-center gap-2 px-2.5 py-1.5">
                  <button
                    onClick={() => canOpen && onChapterSelect(chapter.chapter_number)}
                    className={`flex flex-1 items-center gap-2 min-w-0 text-left ${canOpen ? 'cursor-pointer' : 'cursor-default'}`}
                  >
                    <span className="text-[10px] text-slate-500 font-mono shrink-0">#{String(chapter.chapter_number).padStart(2, '0')}</span>
                    <span className="truncate text-xs text-slate-700">{chapter.title}</span>
                  </button>
                  <button
                    onClick={() => (canOpen ? onChapterSelect(chapter.chapter_number) : void handleExpand(chapter))}
                    disabled={busyChapter !== null}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed transition-colors shrink-0"
                  >
                    {isBusy ? <Loader2 size={11} className="animate-spin" /> : <FileText size={11} />}
                    {canOpen ? '打开' : '生成正文'}
                  </button>
                </div>
                {chapter.summary && <p className="px-2.5 pb-1.5 pl-8 text-[10px] text-slate-500 leading-relaxed line-clamp-2">{chapter.summary}</p>}
              </div>
            );
          })}
          {error && <p className="text-xs text-red-500 px-2.5 pt-1">{error}</p>}
        </div>
      )}

      {expanded && act.chapters.length === 0 && <p className="text-[11px] text-slate-500 italic ml-6 mb-1">暂无章节</p>}
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
      setError(err.message || '生成大纲失败');
    } finally {
      setLoading(false);
    }
  };

  if (!hasContent && !loading) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-slate-600">点击下方按钮，AI 会自动生成故事的三幕式大纲结构。</p>
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <RefreshCw size={13} className="animate-spin" /> : <Sparkles size={13} />}
          AI 生成大纲
        </button>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    );
  }

  const totalChapters = acts.reduce((sum, act) => sum + act.chapters.length, 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        {acts.length > 0 && <span className="text-xs text-slate-500">{acts.length} 幕 · {totalChapters} 章</span>}
        <div className="flex items-center gap-2">
          <button onClick={() => setExpandedAll(!expandedAll)} className="text-[11px] text-slate-500 hover:text-slate-700 transition-colors">
            {expandedAll ? '全部收起' : '全部展开'}
          </button>
          <button
            onClick={handleRegenerate}
            disabled={loading}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed transition-colors"
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

      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
