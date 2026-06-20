import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { Image, Bot } from 'lucide-react';
import { type Story, type Chapter, type EntitlementResponse } from '../api';
import { RouteLoadingFallback } from './ui/RouteLoadingFallback';
import StoryBibleSummaryCard from './StoryBibleSummaryCard';

const FrameworkPanel = lazy(() => import('./FrameworkPanel'));
const EditorPanel = lazy(() => import('./EditorPanel'));
const MangaPanel = lazy(() => import('./MangaPanel'));
const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));

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
  const [rightPanelTab, setRightPanelTab] = useState<'manga' | 'agent'>(() => {
    const saved = localStorage.getItem('rightPanelTab');
    return (saved === 'manga' || saved === 'agent') ? saved : 'agent';
  });
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
      {story.story_bible && Object.keys(story.story_bible).length > 0 && (
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
          <Suspense fallback={<RouteLoadingFallback />}>
            <FrameworkPanel
              story={story}
              chapters={chapters}
              onChapterSelect={handleChapterSelect}
              onFrameworkUpdate={onContentUpdated}
            />
          </Suspense>
        </div>
        )}

        {!mangaPreviewMode && (
        <div className="flex-1 min-w-0 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
          <Suspense fallback={<RouteLoadingFallback />}>
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
          </Suspense>
        </div>
        )}

        <div className={`${mangaPreviewMode ? 'flex-1' : 'w-[400px] shrink-0'} min-w-0 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl`}>
          <div className="flex flex-col h-full">
            <div className="shrink-0 flex border-b border-[#d7e3f4] px-3">
              <button
                onClick={() => { setRightPanelTab('manga'); localStorage.setItem('rightPanelTab', 'manga'); }}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors relative ${
                  rightPanelTab === 'manga'
                    ? 'text-blue-600'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Image size={16} /> 漫画操作区
                {rightPanelTab === 'manga' && (
                  <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
                )}
              </button>
              <button
                onClick={() => { setRightPanelTab('agent'); localStorage.setItem('rightPanelTab', 'agent'); }}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors relative ${
                  rightPanelTab === 'agent'
                    ? 'text-blue-600'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Bot size={16} /> AI 助手
                {rightPanelTab === 'agent' && (
                  <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
                )}
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <Suspense fallback={<RouteLoadingFallback />}>
              {rightPanelTab === 'manga' ? (
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
              ) : (
                <AgentPanel
                  storyId={story.id}
                  chapterId={resolvedChapter?.id}
                  chapterNumber={resolvedChapter?.chapter_number}
                  storyTitle={story.title}
                  chapterTitle={resolvedChapter?.title || undefined}
                  onContentUpdated={onContentUpdated}
                />
              )}
              </Suspense>
            </div>
          </div>
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
