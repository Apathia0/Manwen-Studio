import { useCallback, useEffect, useState } from 'react';
import { type Story, type Chapter } from '../api';
import FrameworkPanel from './FrameworkPanel';
import EditorPanel from './EditorPanel';
import MangaPanel from './MangaPanel';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

export default function WorkspaceLayout({
  story,
  chapters,
  currentChapter,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [selectedText, setSelectedText] = useState('');
  const [chapterContext, setChapterContext] = useState<object | undefined>(undefined);
  const resolvedChapter = currentChapter ? mergeChapterWithFramework(story, currentChapter) : null;

  useEffect(() => {
    setSelectedText('');
    setChapterContext(undefined);
  }, [resolvedChapter?.id]);

  const handleChapterSelect = useCallback(
    (chapterNumber: number) => {
      const chapter = chapters.find((c) => c.chapter_number === chapterNumber);
      if (chapter) onChapterChange(chapter);
    },
    [chapters, onChapterChange],
  );

  return (
    <div className="flex flex-1 min-h-0">
      <div className="w-[280px] shrink-0 border-r border-gray-800 overflow-y-auto">
        <FrameworkPanel
          story={story}
          chapters={chapters}
          onChapterSelect={handleChapterSelect}
          onFrameworkUpdate={onContentUpdated}
        />
      </div>

      <div className="flex-1 min-w-0 overflow-hidden">
        <EditorPanel
          story={story}
          chapters={chapters}
          currentChapter={resolvedChapter}
          onChapterChange={onChapterChange}
          onContentUpdated={onContentUpdated}
          onTextSelected={(text, context) => {
            setSelectedText(text);
            setChapterContext(context);
          }}
        />
      </div>

      <div className="w-[380px] shrink-0 border-l border-gray-800 overflow-y-auto">
        <MangaPanel
          chapter={resolvedChapter}
          onChapterRefresh={onContentUpdated}
          selectedText={selectedText}
          chapterContext={chapterContext as { characters?: any[] } | undefined}
          onClearSelection={() => {
            setSelectedText('');
            setChapterContext(undefined);
          }}
        />
      </div>
    </div>
  );
}

function mergeChapterWithFramework(story: Story, chapter: Chapter): Chapter {
  const plan = findPlannedChapter(story, chapter.chapter_number);
  if (!plan) return chapter;
  return {
    ...chapter,
    title: chapter.title || plan.title || chapter.title,
    act: chapter.act || plan.act || chapter.act,
    key_events: Array.isArray(chapter.key_events) && chapter.key_events.length > 0
      ? chapter.key_events
      : (plan.key_events ?? chapter.key_events),
  };
}

function findPlannedChapter(story: Story, chapterNumber: number): { title?: string; act?: string; key_events?: any[] } | null {
  const acts = story.outline?.three_acts;
  if (!Array.isArray(acts)) return null;
  for (let index = 0; index < acts.length; index += 1) {
    const act = acts[index] as any;
    const chapters = Array.isArray(act?.chapters) ? act.chapters : [];
    const match = chapters.find((item: any) => Number(item?.chapter_number) === chapterNumber);
    if (match) {
      return {
        title: typeof match?.title === 'string' ? match.title : undefined,
        act: String(act?.act ?? index + 1),
        key_events: Array.isArray(match?.key_events) ? match.key_events : undefined,
      };
    }
  }
  return null;
}
