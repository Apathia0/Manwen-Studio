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
  const activeWorkspaceTab = WORKSPACE_TABS.find((tab) => tab.key === workspaceMode) || WORKSPACE_TABS[0];
  const ActiveWorkspaceIcon = activeWorkspaceTab.icon;

  return (
    <div className="flex h-[calc(100vh-120px)] flex-col overflow-hidden rounded-md border border-[#d9dfd7] bg-white">
      <div className="border-b border-[#e8edf2] bg-[#fbfdff] px-4 py-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="grid w-full grid-cols-3 gap-2 xl:max-w-2xl" role="group" aria-label="作品工作台">
            {WORKSPACE_TABS.map((tab) => {
              const Icon = tab.icon;
              const selected = workspaceMode === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onWorkspaceModeChange(tab.key)}
                  className={`flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                    selected
                      ? 'border-blue-300 bg-[#eaf3ff] text-[#1558b0] shadow-sm'
                      : 'border-transparent bg-white text-slate-600 hover:border-[#cdddf2] hover:bg-[#f4f8ff]'
                  }`}
                >
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${selected ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500'}`}>
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{tab.label}</span>
                    <span className="hidden truncate text-xs text-slate-500 sm:block">{tab.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2 xl:justify-end">
            <button
              type="button"
              onClick={() => setKnowledgeOpen(true)}
              className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1 text-xs text-slate-600 transition hover:bg-[#eef5ff] hover:text-[#1d4ed8]"
            >
              <Database size={13} />
              作品设定中心
            </button>
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 border-b border-[#dce8f8] bg-[#f4f8ff] px-4 py-2 text-xs text-slate-600">
        <ActiveWorkspaceIcon size={15} className="shrink-0 text-[#2563eb]" aria-hidden="true" />
        <span className="font-semibold text-slate-800">当前在{activeWorkspaceTab.label}</span>
        <span className="hidden text-slate-400 sm:inline">|</span>
        <span className="hidden sm:inline">{activeWorkspaceTab.description}</span>
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
