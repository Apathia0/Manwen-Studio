import { useState } from 'react';
import { Check, ImageIcon, Pencil, Plus, ScrollText, Trash2, X } from 'lucide-react';
import { coverImageUrl, listChapters, type Story } from '../api';
import { exportStoryAsZip } from '../lib/exportStory';
import { confirm } from '../lib/confirm';
import NovelCoverEditModal from './NovelCoverEditModal';

interface Props {
  stories: Story[];
  loading: boolean;
  onRefresh: () => Promise<void>;
  onCreate: () => Promise<void>;
  onCreateDraft: (title: string, description: string) => Promise<Story>;
  onUpdateStory: (storyId: number, payload: { title?: string; description?: string }) => Promise<Story>;
  onDeleteStory: (story: Story) => Promise<void>;
  onOpen: (story: Story) => Promise<void>;
  loadingWorkspace: boolean;
}

export default function StoryLibraryPage({
  stories,
  loading,
  onRefresh,
  onCreate,
  onCreateDraft,
  onUpdateStory,
  onDeleteStory,
  onOpen,
  loadingWorkspace,
}: Props) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftDescription, setDraftDescription] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [exportingStoryId, setExportingStoryId] = useState<number | null>(null);
  const [coverEditorStoryId, setCoverEditorStoryId] = useState<number | null>(null);

  const resetCreateForm = () => {
    setDraftTitle('');
    setDraftDescription('');
    setShowCreateForm(false);
  };

  const startEdit = (story: Story) => {
    setEditingId(story.id);
    setEditTitle(story.title);
    setEditDescription(story.description || '');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditTitle('');
    setEditDescription('');
  };

  const handleCreateDraft = async () => {
    const title = draftTitle.trim() || `新故事 ${stories.length + 1}`;
    const description = draftDescription.trim();
    setSavingId(-1);
    try {
      await onCreateDraft(title, description);
      resetCreateForm();
    } finally {
      setSavingId(null);
    }
  };

  const handleSaveEdit = async () => {
    if (editingId === null) return;
    setSavingId(editingId);
    try {
      await onUpdateStory(editingId, {
        title: editTitle.trim() || '未命名故事',
        description: editDescription.trim(),
      });
      cancelEdit();
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async (story: Story) => {
    const confirmed = await confirm({
      title: '删除作品',
      message: `确定删除《${story.title}》吗？作品下的章节、对话和漫画资源也会一起删除。`,
    });
    if (!confirmed) return;
    setDeletingId(story.id);
    try {
      await onDeleteStory(story);
      if (editingId === story.id) cancelEdit();
    } finally {
      setDeletingId(null);
    }
  };

  const handleExport = async (story: Story) => {
    setExportingStoryId(story.id);
    try {
      const chapters = await listChapters(story.id);
      await exportStoryAsZip({ story, chapters });
    } finally {
      setExportingStoryId(null);
    }
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">作品首页</h2>
          <p className="text-sm text-slate-600">管理你的小说项目，并从这里进入创作工作台。</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void onRefresh()}
            className="sc-button-secondary rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm"
          >
            刷新
          </button>
          <button
            onClick={() => {
              setShowCreateForm((prev) => !prev);
              if (showCreateForm) resetCreateForm();
            }}
            className="sc-button-primary inline-flex items-center gap-1 rounded-[var(--sc-radius-sm)] px-3 py-2 text-sm"
          >
            <Plus size={14} />
            新建作品
          </button>
        </div>
      </div>

      {showCreateForm && (
        <div className="sc-card mb-4 rounded-[var(--sc-radius-sm)] border p-4">
          <div className="text-sm font-semibold text-slate-800">创建作品</div>
          <div className="mt-3 grid gap-3">
            <input
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              placeholder="输入作品名称"
              className="sc-input rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm outline-none"
            />
            <textarea
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              rows={3}
              placeholder="输入作品简介，可留空"
              className="sc-input resize-y rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm outline-none"
            />
            <div className="flex flex-wrap justify-end gap-2">
              <button
                onClick={() => void onCreate()}
                disabled={savingId !== null}
                className="sc-button-secondary rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              >
                快速创建并进入
              </button>
              <button
                onClick={resetCreateForm}
                disabled={savingId !== null}
                className="sc-button-secondary rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              >
                取消
              </button>
              <button
                onClick={() => void handleCreateDraft()}
                disabled={savingId !== null}
                className="sc-button-primary rounded-[var(--sc-radius-sm)] px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              >
                {savingId === -1 ? '创建中...' : '保存作品'}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="rounded-md border border-[#d9dfd7] bg-white p-5 text-sm text-slate-600">加载中...</div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {stories.map((story) => {
            const isEditing = editingId === story.id;
            const isSaving = savingId === story.id;
            const isExporting = exportingStoryId === story.id;
            return (
              <div
                key={story.id}
                className="group relative flex flex-col"
              >
                {isEditing ? (
                  <div className="sc-card space-y-3 rounded-[var(--sc-radius-md)] border p-3">
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="sc-input w-full rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm outline-none"
                    />
                    <textarea
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={3}
                      className="sc-input w-full resize-y rounded-[var(--sc-radius-sm)] border px-3 py-2 text-sm outline-none"
                      placeholder="输入作品简介，可留空"
                    />
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs text-slate-500">
                        {new Date(story.created_at).toLocaleDateString('zh-CN')}
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={cancelEdit}
                          disabled={isSaving}
                          className="sc-button-secondary rounded-[var(--sc-radius-sm)] border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <X size={12} />
                        </button>
                        <button
                          onClick={() => void handleSaveEdit()}
                          disabled={isSaving}
                          className="sc-button-primary rounded-[var(--sc-radius-sm)] px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Check size={12} />
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <button
                      onClick={() => void onOpen(story)}
                      className="group/book relative block w-full overflow-hidden rounded-[var(--sc-radius-md)] border border-[var(--sc-border-soft)] bg-[var(--sc-panel-muted)] shadow-sm transition-all hover:shadow-md"
                    >
                      {story.cover_image ? (
                        <div className="aspect-[2/3] w-full">
                          <img
                            src={coverImageUrl(story.cover_image) || ''}
                            alt={story.title}
                            className="h-full w-full object-cover"
                            loading="lazy"
                            decoding="async"
                          />
                        </div>
                      ) : (
                        <div className="flex aspect-[2/3] w-full items-center justify-center bg-[var(--sc-accent-soft)] p-4">
                          <span className="sc-book-initial select-none text-4xl font-bold">
                            {story.title.charAt(0)}
                          </span>
                        </div>
                      )}
                      
                      <div className="absolute inset-0 flex items-end justify-center bg-gradient-to-t from-black/60 via-transparent to-transparent p-3 opacity-0 transition-opacity group-hover/book:opacity-100">
                        <div className="flex gap-1.5">
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              if (isExporting || savingId !== null || deletingId !== null) return;
                              void handleExport(story);
                            }}
                            className={`rounded-md px-2 py-1.5 text-xs font-medium backdrop-blur-sm transition hover:bg-white ${isExporting || savingId !== null || deletingId !== null ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'} bg-white/90 text-slate-700`}
                            title="导出"
                          >
                            <ScrollText size={14} />
                          </span>
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              if (savingId !== null || deletingId !== null) return;
                              setCoverEditorStoryId(story.id);
                            }}
                            className={`rounded-md px-2 py-1.5 text-xs font-medium backdrop-blur-sm transition hover:bg-white ${savingId !== null || deletingId !== null ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'} bg-white/90 text-[#1d4ed8]`}
                            title="封面编辑"
                          >
                            <ImageIcon size={14} />
                          </span>
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              if (savingId !== null || deletingId !== null) return;
                              startEdit(story);
                            }}
                            className={`rounded-md px-2 py-1.5 text-xs font-medium backdrop-blur-sm transition hover:bg-white ${savingId !== null || deletingId !== null ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'} bg-white/90 text-slate-700`}
                            title="编辑"
                          >
                            <Pencil size={14} />
                          </span>
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              if (savingId !== null || deletingId !== null) return;
                              void handleDelete(story);
                            }}
                            className={`rounded-md px-2 py-1.5 text-xs font-medium backdrop-blur-sm transition hover:bg-white ${savingId !== null || deletingId !== null ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'} bg-white/90 text-rose-600`}
                            title="删除"
                          >
                            <Trash2 size={14} />
                          </span>
                        </div>
                      </div>
                    </button>
                    
                    <div className="mt-2 px-0.5">
                      <div className="truncate text-sm font-medium text-[var(--sc-text)]" title={story.title}>
                        {story.title}
                      </div>
                      <div className="sc-text-subtle mt-0.5 text-xs">
                        {new Date(story.created_at).toLocaleDateString('zh-CN')}
                      </div>
                    </div>
                  </>
                )}
              </div>
            );
          })}
          {stories.length === 0 && (
            <div className="sc-muted-surface sc-text-muted col-span-full flex aspect-[2/3] w-full max-w-[200px] items-center justify-center rounded-[var(--sc-radius-md)] border border-dashed border-[var(--sc-border)] p-5 text-center text-sm">
              还没有作品。点击「新建作品」开始创作。
            </div>
          )}
        </div>
      )}

      {loadingWorkspace && <div className="mt-4 text-sm text-slate-600">正在进入工作台...</div>}

      {coverEditorStoryId !== null && (
        <NovelCoverEditModal
          story={stories.find((story) => story.id === coverEditorStoryId)!}
          onClose={() => setCoverEditorStoryId(null)}
          onUpdated={onRefresh}
        />
      )}
    </div>
  );
}
