import type { Story, Chapter, EntitlementResponse } from '../api';
import WorkspaceLayout from './WorkspaceLayout';
import VideoWorkspaceLayout from './VideoWorkspaceLayout';
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
}: {
  story: Story | null;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements: EntitlementResponse | null;
  workspaceMode: 'manga' | 'video';
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => Promise<void>;
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
      <div className="flex items-center justify-end border-b border-[#e8edf2] px-4 py-2">
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
        <VideoWorkspaceLayout
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
