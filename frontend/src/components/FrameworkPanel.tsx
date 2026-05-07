import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, Loader2, Sparkles } from 'lucide-react';
import { generateFramework, type Chapter, type Story } from '../api';
import type { FrameworkChapter } from './framework/types';
import ChapterListSection from './framework/ChapterListSection';
import CharacterSection from './framework/CharacterSection';
import OutlineSection from './framework/OutlineSection';
import TagSection from './framework/TagSection';

interface Props {
  story: Story;
  chapters: Chapter[];
  onChapterSelect: (chapterNumber: number) => void;
  onFrameworkUpdate: () => void | Promise<void>;
}

type SectionKey = 'tags' | 'characters' | 'outline' | 'chapters';

const SECTION_LABELS: Record<SectionKey, string> = {
  tags: '标签设定',
  characters: '角色设定',
  outline: '故事大纲',
  chapters: '章节列表',
};

export default function FrameworkPanel({ story, chapters, onChapterSelect, onFrameworkUpdate }: Props) {
  const [description, setDescription] = useState(story.description || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    tags: true,
    characters: true,
    outline: true,
    chapters: true,
  });

  useEffect(() => {
    if (story.description !== undefined) {
      setDescription(story.description);
    }
  }, [story.id, story.description]);

  const frameworkChapters = useMemo(() => buildFrameworkChapters(story, chapters), [story, chapters]);

  const handleGenerate = async () => {
    if (!description.trim()) return;
    setLoading(true);
    setError('');
    try {
      await generateFramework(story.id, description);
      onFrameworkUpdate();
    } catch (err: any) {
      setError(err.message || '生成框架失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  };

  const toggleSection = (key: SectionKey) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const allExpanded = Object.values(expanded).every(Boolean);
  const toggleAll = () => {
    const next = !allExpanded;
    setExpanded({ tags: next, characters: next, outline: next, chapters: next });
  };

  return (
    <div className="flex flex-col h-full bg-gray-950">
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-violet-400" />
          <h2 className="text-sm font-semibold text-gray-100 tracking-wide">故事框架</h2>
        </div>
        <button
          onClick={toggleAll}
          className="text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
        >
          {allExpanded ? '全部收起' : '全部展开'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-5 py-4 space-y-3">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="输入故事描述，AI 会基于此生成标签、角色、大纲与章节规划。"
            rows={3}
            className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 text-sm text-gray-200
                       placeholder-gray-600 resize-none outline-none focus:border-violet-500 transition-colors
                       leading-relaxed"
          />
          <button
            onClick={handleGenerate}
            disabled={loading || !description.trim()}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium
                       rounded-lg bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-900/30
                       disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {loading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                生成中…
              </>
            ) : (
              <>
                <Sparkles size={16} />
                AI 生成框架
              </>
            )}
          </button>
          {error && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-900/20 border border-red-800/40">
              <span className="text-xs text-red-400 leading-relaxed">{error}</span>
            </div>
          )}
        </div>

        <div className="border-t border-gray-800">
          <SectionShell
            sectionKey="tags"
            expanded={expanded}
            toggleSection={toggleSection}
            generated={!!(story.tags && Object.values(story.tags).some(Boolean))}
          >
            <TagSection tags={story.tags ?? null} storyId={story.id} onUpdate={onFrameworkUpdate} />
          </SectionShell>

          <SectionShell
            sectionKey="characters"
            expanded={expanded}
            toggleSection={toggleSection}
            generated={!!(story.characters && story.characters.length > 0)}
          >
            <CharacterSection
              characters={story.characters ?? null}
              storyId={story.id}
              onUpdate={onFrameworkUpdate}
            />
          </SectionShell>

          <SectionShell
            sectionKey="outline"
            expanded={expanded}
            toggleSection={toggleSection}
            generated={!!story.outline?.three_acts?.length}
          >
            <OutlineSection
              outline={story.outline ?? null}
              chapters={chapters}
              storyId={story.id}
              onChapterSelect={onChapterSelect}
              onUpdate={onFrameworkUpdate}
            />
          </SectionShell>

          <SectionShell
            sectionKey="chapters"
            expanded={expanded}
            toggleSection={toggleSection}
            count={frameworkChapters.length}
          >
            <ChapterListSection
              chapters={frameworkChapters}
              storyId={story.id}
              onChapterSelect={onChapterSelect}
              onUpdate={onFrameworkUpdate}
            />
          </SectionShell>
        </div>

        <div className="h-4" />
      </div>
    </div>
  );
}

function SectionShell({
  sectionKey,
  expanded,
  toggleSection,
  children,
  generated,
  count,
}: {
  sectionKey: SectionKey;
  expanded: Record<SectionKey, boolean>;
  toggleSection: (key: SectionKey) => void;
  children: ReactNode;
  generated?: boolean;
  count?: number;
}) {
  return (
    <div className="border-b border-gray-800">
      <button
        onClick={() => toggleSection(sectionKey)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-900/30 transition-colors"
      >
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          {SECTION_LABELS[sectionKey]}
        </span>
        <div className="flex items-center gap-2">
          {generated && (
            <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full">已生成</span>
          )}
          {!generated && typeof count === 'number' && count > 0 && (
            <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full">{count} 话</span>
          )}
          <ChevronDown
            size={14}
            className={`text-gray-600 transition-transform duration-200 ${expanded[sectionKey] ? '' : '-rotate-90'}`}
          />
        </div>
      </button>
      {expanded[sectionKey] && <div className="px-5 pb-4">{children}</div>}
    </div>
  );
}

function buildFrameworkChapters(story: Story, chapters: Chapter[]): FrameworkChapter[] {
  const actualByNumber = new Map(chapters.map((chapter) => [chapter.chapter_number, chapter]));
  const planned: FrameworkChapter[] = [];
  const acts = story.outline?.three_acts;

  if (Array.isArray(acts)) {
    acts.forEach((act, actIndex) => {
      const actLabel = String((act as any)?.act ?? actIndex + 1);
      const actChapters = Array.isArray((act as any)?.chapters) ? (act as any).chapters : [];
      actChapters.forEach((chapter: any) => {
        const chapterNumber = Number(chapter?.chapter_number);
        if (!Number.isInteger(chapterNumber) || chapterNumber < 1) return;
        const actual = actualByNumber.get(chapterNumber);
        const title = String(chapter?.title || actual?.title || `第${chapterNumber}话`).trim();
        const rawEvents = Array.isArray(chapter?.key_events) ? chapter.key_events : actual?.key_events;
        const keyEvents = Array.isArray(rawEvents)
          ? rawEvents.map((item) => String(item)).filter(Boolean)
          : undefined;
        planned.push({
          id: actual?.id,
          act: actLabel,
          chapter_number: chapterNumber,
          title,
          status: actual?.status ?? (actual?.novel_content ? 'completed' : 'pending'),
          key_events: keyEvents,
        });
      });
    });
  }

  const knownNumbers = new Set(planned.map((item) => item.chapter_number));
  chapters.forEach((chapter) => {
    if (knownNumbers.has(chapter.chapter_number)) return;
    planned.push({
      id: chapter.id,
      act: chapter.act || '',
      chapter_number: chapter.chapter_number,
      title: chapter.title || `第${chapter.chapter_number}话`,
      status: chapter.status ?? (chapter.novel_content ? 'completed' : 'pending'),
      key_events: Array.isArray(chapter.key_events) ? chapter.key_events.map((item) => String(item)) : undefined,
    });
  });

  return planned.sort((a, b) => a.chapter_number - b.chapter_number);
}
