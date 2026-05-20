import { useCallback, useEffect, useState } from 'react';
import { type Story, type Chapter, type EntitlementResponse } from '../api';
import FrameworkPanel from './FrameworkPanel';
import EditorPanel from './EditorPanel';
import MangaPanel from './MangaPanel';
import StoryBibleSummaryCard from './StoryBibleSummaryCard';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: EntitlementResponse | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

export default function WorkspaceLayout({
  story,
  chapters,
  currentChapter,
  entitlements,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [selectedText, setSelectedText] = useState('');
  const [chapterContext, setChapterContext] = useState<object | undefined>(undefined);
  const [mangaPreviewMode, setMangaPreviewMode] = useState(false);
  const resolvedChapter = currentChapter ? mergeChapterWithFramework(story, currentChapter) : null;

  useEffect(() => {
    setSelectedText('');
    setChapterContext(undefined);
    setMangaPreviewMode(false);
  }, [resolvedChapter?.id]);

  const handleChapterSelect = useCallback(
    (chapterNumber: number) => {
      const chapter = chapters.find((c) => c.chapter_number === chapterNumber);
      if (chapter) onChapterChange(chapter);
    },
    [chapters, onChapterChange],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_100%)] p-4">
      {story.story_bible?.creative_brief && (
        <div className="shrink-0">
          <StoryBibleSummaryCard
            storyId={story.id}
            storyBible={story.story_bible}
            onUpdated={onContentUpdated}
          />
        </div>
      )}
      <div className="flex min-h-0 flex-1 gap-4">
        {!mangaPreviewMode && (
        <div className="w-[320px] shrink-0 overflow-y-auto rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
          <FrameworkPanel
            story={story}
            chapters={chapters}
            onChapterSelect={handleChapterSelect}
            onFrameworkUpdate={onContentUpdated}
          />
        </div>
        )}

        {!mangaPreviewMode && (
        <div className="flex-1 min-w-0 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
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
        )}

        <div className={`${mangaPreviewMode ? 'flex-1' : 'w-[400px] shrink-0'} min-w-0 overflow-y-auto rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl`}>
          <MangaPanel
            chapter={resolvedChapter}
            entitlements={entitlements}
            onChapterRefresh={onContentUpdated}
            selectedText={selectedText}
            chapterContext={chapterContext as { characters?: any[] } | undefined}
            isWorkspacePreviewMode={mangaPreviewMode}
            onWorkspacePreviewModeChange={setMangaPreviewMode}
            onClearSelection={() => {
              setSelectedText('');
              setChapterContext(undefined);
            }}
          />
        </div>
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
