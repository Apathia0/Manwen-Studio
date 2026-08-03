import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { Image, Bot } from 'lucide-react';
import { type Story, type Chapter } from '../api';
import { RouteLoadingFallback } from './ui/RouteLoadingFallback';

const FrameworkPanel = lazy(() => import('./FrameworkPanel'));
const EditorPanel = lazy(() => import('./EditorPanel'));
const MangaPanel = lazy(() => import('./MangaPanel'));
const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: Record<string, any> | null;
  workspaceDomain: 'novel' | 'manga';
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

export default function WorkspaceLayout({
  story,
  chapters,
  currentChapter,
  entitlements,
  workspaceDomain,
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
  }, [resolvedChapter?.id, workspaceDomain]);

  const handleChapterSelect = useCallback(
    (chapterNumber: number) => {
      const chapter = chapters.find((c) => c.chapter_number === chapterNumber);
      if (chapter) onChapterChange(chapter);
    },
    [chapters, onChapterChange],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_100%)] p-4">
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
            <div className="shrink-0 flex items-center gap-2 border-b border-[#d7e3f4] px-4 py-2.5 text-sm font-semibold text-slate-800">
              {workspaceDomain === 'manga' ? <Image size={16} className="text-blue-600" aria-hidden="true" /> : <Bot size={16} className="text-blue-600" aria-hidden="true" />}
              <span>{workspaceDomain === 'manga' ? '漫画生成' : 'AI 写作助手'}</span>
              <span className="ml-auto text-xs font-normal text-slate-400">
                {workspaceDomain === 'manga' ? '基于当前章节生成画面' : '围绕当前章节协助创作'}
              </span>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <Suspense fallback={<RouteLoadingFallback />}>
              {workspaceDomain === 'manga' ? (
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
