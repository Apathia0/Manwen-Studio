import type { Story, Chapter, EntitlementResponse } from '../api';
import WorkspaceLayout from './WorkspaceLayout';
import VideoStoryboardLayout from './VideoStoryboardLayout';
import TemplateBindingPanel from './TemplateBindingPanel';

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
  entitlements: EntitlementResponse | null;
  workspaceMode: 'manga' | 'video';
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => Promise<void>;
  onWorkspaceModeChange?: (mode: 'manga' | 'video') => void;
}) {
  if (!story) {
    return (
      <div className="rounded-md border border-[#d9dfd7] bg-white p-6 text-sm text-slate-600">
        请先在「作品」页面选择一个项目再进入工作台。
      </div>
    );
  }
  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto rounded-md border border-[#d9dfd7] bg-white">
      <div className="flex items-center justify-between border-b border-[#e8edf2] px-4 py-2">
        <div className="flex items-center gap-1 rounded-xl bg-slate-100 p-0.5">
          <button
            onClick={() => onWorkspaceModeChange?.('manga')}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              workspaceMode === 'manga'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            小说/漫画
          </button>
          <button
            onClick={() => onWorkspaceModeChange?.('video')}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              workspaceMode === 'video'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            视频创作
          </button>
        </div>
        <TemplateBindingPanel storyId={story.id} />
      </div>
      {workspaceMode === 'manga' ? (
        <WorkspaceLayout
          story={story}
          chapters={chapters}
          currentChapter={currentChapter}
          entitlements={entitlements}
          onChapterChange={onChapterChange}
          onContentUpdated={onContentUpdated}
        />
      ) : (
        <VideoStoryboardLayout
          story={story}
          chapters={chapters}
          currentChapter={currentChapter}
          entitlements={entitlements}
          onChapterChange={onChapterChange}
          onContentUpdated={onContentUpdated}
        />
      )}
    </div>
  );
}
