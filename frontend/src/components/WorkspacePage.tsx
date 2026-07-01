import { useState, useEffect } from 'react';
import type { Story, Chapter, EntitlementResponse } from '../api';
import { listDeconstructionWorks, listDeconstructionRefs, addDeconstructionRef, removeDeconstructionRef } from '../api';
import type { DeconstructionWorkItem, DeconstructionRefItem } from '../api';
import WorkspaceLayout from './WorkspaceLayout';
import VideoStoryboardLayout from './VideoStoryboardLayout';
import TemplateBindingPanel from './TemplateBindingPanel';
import { BookOpen, Plus, X, CheckCircle2 } from 'lucide-react';

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
  const [showRefPicker, setShowRefPicker] = useState(false);
  const [availableWorks, setAvailableWorks] = useState<DeconstructionWorkItem[]>([]);
  const [activeRefs, setActiveRefs] = useState<DeconstructionRefItem[]>([]);
  const [refLoading, setRefLoading] = useState(false);

  useEffect(() => {
    if (story && showRefPicker) {
      loadRefData();
    }
  }, [story, showRefPicker]);

  async function loadRefData() {
    if (!story) return;
    setRefLoading(true);
    try {
      const [works, refs] = await Promise.all([
        listDeconstructionWorks(),
        listDeconstructionRefs(story.id),
      ]);
      setAvailableWorks(works.filter(w => w.decon_status === 'completed'));
      setActiveRefs(refs);
    } catch {}
    setRefLoading(false);
  }

  async function handleAddRef(workId: number) {
    if (!story) return;
    try {
      await addDeconstructionRef(story.id, workId);
      await loadRefData();
    } catch (e: any) {
      alert(e.message || '引用失败');
    }
  }

  async function handleRemoveRef(refId: number) {
    if (!story) return;
    try {
      await removeDeconstructionRef(story.id, refId);
      await loadRefData();
    } catch (e: any) {
      alert(e.message || '取消引用失败');
    }
  }

  if (!story) {
    return (
      <div className="rounded-md border border-[#d9dfd7] bg-white p-6 text-sm text-slate-600">
        请先在「作品」页面选择一个项目再进入工作台。
      </div>
    );
  }
  return (
    <div className="flex h-[calc(100vh-120px)] flex-col overflow-hidden rounded-md border border-[#d9dfd7] bg-white">
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
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setShowRefPicker(!showRefPicker); if (!showRefPicker) loadRefData(); }}
            className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] px-2.5 py-1 text-xs text-slate-600 transition hover:bg-[#eef5ff]"
          >
            <BookOpen size={13} />
            引用拆书报告
            {activeRefs.length > 0 && (
              <span className="ml-1 rounded-full bg-[#1d4ed8] px-1.5 py-0.5 text-[10px] text-white">{activeRefs.length}</span>
            )}
          </button>
          <TemplateBindingPanel storyId={story.id} />
        </div>
      </div>

      {showRefPicker && (
        <div className="border-b border-[#e8edf2] bg-[#f8fbff] px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-slate-600">已引用的拆书报告</span>
            <button onClick={() => setShowRefPicker(false)} className="text-slate-400 hover:text-slate-600">
              <X size={14} />
            </button>
          </div>
          {activeRefs.length === 0 ? (
            <p className="text-xs text-slate-400">暂未引用任何拆书报告，Agent 将使用默认写作风格</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {activeRefs.map(ref => (
                <span key={ref.id} className="inline-flex items-center gap-1 rounded-full bg-[#e8f1ff] px-2.5 py-1 text-xs text-[#1d4ed8]">
                  <CheckCircle2 size={12} />
                  {ref.title}
                  <button onClick={() => handleRemoveRef(ref.id)} className="ml-1 text-slate-400 hover:text-red-500">
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="mt-3">
            <span className="text-xs font-medium text-slate-600">可引用的拆书报告</span>
            {refLoading ? (
              <p className="mt-1 text-xs text-slate-400">加载中...</p>
            ) : availableWorks.length === 0 ? (
              <p className="mt-1 text-xs text-slate-400">暂无可引用的拆书报告，请先去「拆书库」完成拆书</p>
            ) : (
              <div className="mt-1 flex flex-wrap gap-2">
                {availableWorks.filter(w => !activeRefs.some(r => r.work_id === w.id)).map(work => (
                  <button
                    key={work.id}
                    onClick={() => handleAddRef(work.id)}
                    className="inline-flex items-center gap-1 rounded-full border border-[#d7e3f4] bg-white px-2.5 py-1 text-xs text-slate-600 transition hover:bg-[#eef5ff] hover:text-[#1d4ed8]"
                  >
                    <Plus size={12} />
                    {work.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

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