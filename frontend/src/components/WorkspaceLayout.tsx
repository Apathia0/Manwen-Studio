import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { Bot, ChevronLeft, Image, ListTree, PanelRightClose, PanelRightOpen, X } from 'lucide-react';
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
  onOpenKnowledge: () => void;
}

export default function WorkspaceLayout({
  story,
  chapters,
  currentChapter,
  entitlements,
  workspaceDomain,
  onChapterChange,
  onContentUpdated,
  onOpenKnowledge,
}: Props) {
  const [selectedText, setSelectedText] = useState('');
  const [chapterContext, setChapterContext] = useState<object | undefined>(undefined);
  const [mangaPreviewMode, setMangaPreviewMode] = useState(false);
  const [agentCollapsed, setAgentCollapsed] = useState(false);
  const [mobileChapterOpen, setMobileChapterOpen] = useState(false);
  const [mobileAgentOpen, setMobileAgentOpen] = useState(false);
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
    <div className="flex h-full min-h-0 flex-col bg-white">
      {/* 移动端工具条：章节列表与 AI 助手入口（桌面端隐藏） */}
      <div className="flex shrink-0 items-center gap-2 border-b border-[#d7e3f4] bg-white px-3 py-2 md:hidden">
        {!mangaPreviewMode && (
          <button
            type="button"
            onClick={() => setMobileChapterOpen(true)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#d7e3f4] bg-white px-3 text-xs font-medium text-slate-700 transition hover:bg-slate-50 active:bg-slate-100"
          >
            <ListTree size={15} className="text-blue-600" aria-hidden="true" />
            章节
          </button>
        )}
        <button
          type="button"
          onClick={() => setMobileAgentOpen(true)}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#d7e3f4] bg-white px-3 text-xs font-medium text-slate-700 transition hover:bg-slate-50 active:bg-slate-100"
        >
          {workspaceDomain === 'manga' ? <Image size={15} className="text-blue-600" aria-hidden="true" /> : <Bot size={15} className="text-blue-600" aria-hidden="true" />}
          {workspaceDomain === 'manga' ? '漫画生成' : 'AI 助手'}
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {!mangaPreviewMode && (
        <div className="hidden w-[300px] shrink-0 overflow-y-auto border-r border-[#d7e3f4] bg-white xl:block">
          <Suspense fallback={<RouteLoadingFallback />}>
            <FrameworkPanel
              story={story}
              chapters={chapters}
              onChapterSelect={handleChapterSelect}
              onFrameworkUpdate={onContentUpdated}
              onOpenKnowledge={onOpenKnowledge}
            />
          </Suspense>
        </div>
        )}

        {!mangaPreviewMode && (
        <div className="min-h-0 min-w-0 flex-1 overflow-hidden border-b border-[#d7e3f4] bg-white md:border-b-0 md:border-r">
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

        {/* 桌面端 AI 助手右栏（移动端隐藏，见下方抽屉） */}
        <div className={`${mangaPreviewMode ? 'flex-1' : agentCollapsed ? 'h-11 w-full shrink-0 md:h-auto md:w-[48px]' : 'h-[45%] w-full shrink-0 md:h-auto md:w-[390px]'} hidden min-h-0 min-w-0 max-w-full overflow-hidden bg-white transition-[width,height] duration-200 md:flex`}>
          <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col">
            <div className={`shrink-0 flex h-11 items-center border-b border-[#d7e3f4] text-sm font-semibold text-slate-800 ${agentCollapsed ? 'justify-center px-1' : 'gap-2 px-3'}`}>
              {workspaceDomain === 'manga' ? <Image size={16} className="text-blue-600" aria-hidden="true" /> : <Bot size={16} className="text-blue-600" aria-hidden="true" />}
              {!agentCollapsed ? <span>{workspaceDomain === 'manga' ? '漫画生成' : 'AI 写作助手'}</span> : null}
              {!mangaPreviewMode ? (
                <button
                  type="button"
                  onClick={() => setAgentCollapsed((value) => !value)}
                  className={`${agentCollapsed ? '' : 'ml-auto'} rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700`}
                  title={agentCollapsed ? '展开 AI 写作助手' : '收起 AI 写作助手'}
                  aria-label={agentCollapsed ? '展开 AI 写作助手' : '收起 AI 写作助手'}
                >
                  {agentCollapsed ? <PanelRightOpen size={16} /> : <PanelRightClose size={16} />}
                </button>
              ) : null}
            </div>
            <div className={`min-h-0 min-w-0 flex-1 overflow-hidden ${agentCollapsed ? 'hidden' : ''}`}>
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

      {/* 移动端章节列表抽屉 */}
      {mobileChapterOpen && !mangaPreviewMode ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="absolute inset-0 bg-slate-950/40" onClick={() => setMobileChapterOpen(false)} aria-hidden="true" />
          <div className="relative flex h-full w-[86%] max-w-[340px] flex-col overflow-hidden bg-white shadow-2xl">
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-[#d7e3f4] bg-white px-3">
              <button
                type="button"
                onClick={() => setMobileChapterOpen(false)}
                className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"
                aria-label="关闭章节列表"
              >
                <ChevronLeft size={20} />
              </button>
              <span className="text-sm font-semibold text-slate-800">章节与框架</span>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <Suspense fallback={<RouteLoadingFallback />}>
                <FrameworkPanel
                  story={story}
                  chapters={chapters}
                  onChapterSelect={(chapterNumber) => {
                    handleChapterSelect(chapterNumber);
                    setMobileChapterOpen(false);
                  }}
                  onFrameworkUpdate={onContentUpdated}
                  onOpenKnowledge={() => {
                    setMobileChapterOpen(false);
                    onOpenKnowledge();
                  }}
                />
              </Suspense>
            </div>
          </div>
        </div>
      ) : null}

      {/* 移动端 AI 助手全屏抽屉 */}
      {mobileAgentOpen ? (
        <div className="fixed inset-0 z-40 flex flex-col bg-white md:hidden">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b border-[#d7e3f4] bg-white px-3" style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
            <button
              type="button"
              onClick={() => setMobileAgentOpen(false)}
              className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"
              aria-label="关闭助手"
            >
              <ChevronLeft size={20} />
            </button>
            <span className="text-sm font-semibold text-slate-800">
              {workspaceDomain === 'manga' ? '漫画生成' : 'AI 写作助手'}
            </span>
            <button
              type="button"
              onClick={() => setMobileAgentOpen(false)}
              className="ml-auto rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100"
              aria-label="关闭助手"
            >
              <X size={18} />
            </button>
          </header>
          <div className="min-h-0 flex-1">
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
      ) : null}
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
