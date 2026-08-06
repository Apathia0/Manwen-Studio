import { lazy, Suspense, useState, useEffect } from 'react';
import type { Story, Chapter } from '../api';
import WorkspaceLayout from './WorkspaceLayout';
import MangaWorkspaceLayout from './MangaWorkspaceLayout';
import VideoStoryboardLayout from './VideoStoryboardLayout';
import { Clapperboard, Database, Image, PenLine } from 'lucide-react';

type WorkspaceMode = 'novel' | 'manga' | 'video';

const StoryKnowledgeWorkbench = lazy(() => import('./StoryKnowledgeWorkbench'));

const WORKSPACE_TABS: Array<{
  key: WorkspaceMode;
  label: string;
  description: string;
  icon: typeof PenLine;
}> = [
  { key: 'novel', label: '小说创作', description: '框架、章节与 AI 写作', icon: PenLine },
  { key: 'manga', label: '漫画创作', description: '将当前章节转为漫画', icon: Image },
  { key: 'video', label: '视频创作', description: '剧本、分镜与视频成片', icon: Clapperboard },
];

/** 创作工作台页面 */
export function WorkspacePage({
  story,
  chapters,
  currentChapter,
  entitlements,
  workspaceMode,
  onChapterChange,
  onContentUpdated,
  onWorkspaceModeChange,
}: {
  story: Story | null;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements: Record<string, any> | null;
  workspaceMode: WorkspaceMode;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => Promise<void>;
  onWorkspaceModeChange: (mode: WorkspaceMode) => void;
}) {
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [visitedWorkspaceModes, setVisitedWorkspaceModes] = useState<Set<WorkspaceMode>>(
    () => new Set([workspaceMode]),
  );

  useEffect(() => {
    setVisitedWorkspaceModes((previous) => {
      if (previous.has(workspaceMode)) return previous;
      const next = new Set(previous);
      next.add(workspaceMode);
      return next;
    });
  }, [workspaceMode]);

  if (!story) {
    return (
      <div className="rounded-md border border-[#d9dfd7] bg-white p-6 text-sm text-slate-600">
        请先在「作品」页面选择一个项目再进入工作台。
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <div className="shrink-0 border-b border-[#dce8f8] bg-[#fbfdff] px-3 py-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="grid w-full grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1 sm:max-w-[520px]" role="group" aria-label="作品工作台">
            {WORKSPACE_TABS.map((tab) => {
              const Icon = tab.icon;
              const selected = workspaceMode === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onWorkspaceModeChange(tab.key)}
                  className={`flex h-9 min-w-0 items-center justify-center gap-2 rounded-md px-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                    selected
                      ? 'bg-white text-[#1558b0] shadow-sm'
                      : 'text-slate-600 hover:bg-white/70'
                  }`}
                >
                  <Icon size={15} className={selected ? 'text-blue-600' : 'text-slate-400'} aria-hidden="true" />
                  <span className="truncate text-sm font-semibold">{tab.label}</span>
                </button>
              );
            })}
          </div>
          <div className={`flex min-w-0 flex-wrap items-center gap-2 ${workspaceMode === 'novel' ? 'xl:hidden' : ''}`}>
            <button
              type="button"
              onClick={() => setKnowledgeOpen(true)}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[#d7e3f4] bg-white px-3 text-xs font-medium text-slate-600 transition hover:bg-[#eef5ff] hover:text-[#1d4ed8]"
            >
              <Database size={13} />
              作品设定中心
            </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {(workspaceMode === 'novel' || visitedWorkspaceModes.has('novel')) ? (
          <div className={workspaceMode === 'novel' ? 'h-full' : 'hidden'}>
            <WorkspaceLayout
              story={story}
              chapters={chapters}
              currentChapter={currentChapter}
              entitlements={entitlements}
              workspaceDomain="novel"
              onChapterChange={onChapterChange}
              onContentUpdated={onContentUpdated}
              onOpenKnowledge={() => setKnowledgeOpen(true)}
            />
          </div>
        ) : null}
        {(workspaceMode === 'manga' || visitedWorkspaceModes.has('manga')) ? (
          <div className={workspaceMode === 'manga' ? 'h-full' : 'hidden'}>
            <MangaWorkspaceLayout
              story={story}
              chapters={chapters}
              currentChapter={currentChapter}
              entitlements={entitlements}
              onChapterChange={onChapterChange}
              onContentUpdated={onContentUpdated}
            />
          </div>
        ) : null}
        {(workspaceMode === 'video' || visitedWorkspaceModes.has('video')) ? (
          <div className={workspaceMode === 'video' ? 'h-full' : 'hidden'}>
            <VideoStoryboardLayout
              story={story}
              chapters={chapters}
              currentChapter={currentChapter}
              entitlements={entitlements}
              onChapterChange={onChapterChange}
              onContentUpdated={onContentUpdated}
            />
          </div>
        ) : null}
      </div>
      {knowledgeOpen ? (
        <Suspense fallback={null}>
          <StoryKnowledgeWorkbench
            storyId={story.id}
            storyTitle={story.title}
            onContentUpdated={onContentUpdated}
            onClose={() => setKnowledgeOpen(false)}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
