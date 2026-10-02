import { useState } from 'react';
import { Check, ImageIcon, MoreHorizontal, Pencil, Plus, ScrollText, Trash2, Upload, X } from 'lucide-react';
import { coverImageUrl, listChapters, type Story } from '../api';
import { exportStoryAsZip } from '../lib/exportStory';
import { confirm } from '../lib/confirm';
import { showActionSheet } from './mobile/MobileActionSheet';
import NovelCoverEditModal from './NovelCoverEditModal';
import ImportDialog from './ImportDialog';
import MediaImage from './shared/MediaImage';

interface Props {
  stories: Story[];
  loading: boolean;
  onRefresh: () => Promise<void>;
  onCreate: () => Promise<void>;
  onCreateDraft: (title: string, description: string) => Promise<Story>;
  onUpdateStory: (storyId: number, payload: { title?: string; description?: string }) => Promise<Story>;
  onDeleteStory: (story: Story) => Promise<void>;
  onOpen: (story: Story) => Promise<void>;
  /** 作品导入完成回调（storyId 为新建作品 ID） */
  onImportComplete: (storyId: number) => void;
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
  onImportComplete,
  loadingWorkspace,
}: Props) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showImportDialog, setShowImportDialog] = useState(false);
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

  const openStoryActions = (story: Story) => {
    const isBusy = savingId !== null || deletingId !== null;
    showActionSheet({
      title: story.title,
      actions: [
        {
          key: 'export',
          label: '导出作品',
          icon: ScrollText,
          disabled: isBusy || exportingStoryId === story.id,
          onClick: () => void handleExport(story),
        },
        {
          key: 'cover',
          label: '封面编辑',
          icon: ImageIcon,
          disabled: isBusy,
          onClick: () => setCoverEditorStoryId(story.id),
        },
        {
          key: 'edit',
          label: '编辑信息',
          icon: Pencil,
          disabled: isBusy,
          onClick: () => startEdit(story),
        },
        {
          key: 'delete',
          label: '删除作品',
          icon: Trash2,
          danger: true,
          disabled: isBusy,
          onClick: () => void handleDelete(story),
        },
      ],
    });
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">小说作品</h2>
          <p className="text-sm text-slate-600">管理你的小说项目，并从这里进入创作工作台。</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void onRefresh()}
            className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm"
          >
            刷新
          </button>
          <button
            onClick={() => setShowImportDialog(true)}
            className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm text-slate-700"
          >
            <Upload size={14} />
            导入
          </button>
          <button
            onClick={() => {
              setShowCreateForm((prev) => !prev);
              if (showCreateForm) resetCreateForm();
            }}
            className="inline-flex items-center gap-1 rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white"
          >
            <Plus size={14} />
            新建作品
          </button>
        </div>
      </div>

      {showCreateForm && (
        <div className="mb-4 rounded-md border border-[#d9dfd7] bg-white p-4">
          <div className="text-sm font-semibold text-slate-800">创建作品</div>
          <div className="mt-3 grid gap-3">
            <input
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              placeholder="输入作品名称"
              className="rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58]"
            />
            <textarea
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              rows={3}
              placeholder="输入作品简介，可留空"
              className="rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58] resize-y"
            />
            <div className="flex flex-wrap justify-end gap-2">
              <button
                onClick={() => void onCreate()}
                disabled={savingId !== null}
                className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                快速创建并进入
              </button>
              <button
                onClick={resetCreateForm}
                disabled={savingId !== null}
                className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                取消
              </button>
              <button
                onClick={() => void handleCreateDraft()}
                disabled={savingId !== null}
                className="rounded-md bg-[#1f5f58] px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
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
                  <div className="space-y-3 rounded-lg border border-[#d9dfd7] bg-white p-3">
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="w-full rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58]"
                    />
                    <textarea
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={3}
                      className="w-full rounded-md border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 outline-none focus:border-[#1f5f58] resize-y"
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
                          className="rounded-md border border-[#d9dfd7] bg-white px-2 py-1 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <X size={12} />
                        </button>
                        <button
                          onClick={() => void handleSaveEdit()}
                          disabled={isSaving}
                          className="rounded-md bg-[#1f5f58] px-2 py-1 text-xs text-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Check size={12} />
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="relative">
                      <div
                        onClick={() => void onOpen(story)}
                        className="group/book relative block w-full cursor-pointer overflow-hidden rounded-lg border border-[#e2e8f0] bg-gradient-to-br from-slate-50 to-slate-100 shadow-sm transition-all hover:shadow-md"
                      >
                        {story.cover_image ? (
                          <div className="relative aspect-[2/3] w-full overflow-hidden bg-slate-100">
                            <MediaImage
                              src={coverImageUrl(story.cover_image) || ''}
                              alt={story.title}
                              className="h-full w-full object-cover"
                              priority
                            />
                          </div>
                        ) : (
                          <div className="flex aspect-[2/3] w-full items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-50 p-4">
                            <span className="text-4xl font-bold text-blue-200/80 select-none">
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
                      </div>
                      {/* 移动端显式"更多"按钮：触摸设备无 hover，必须提供明确操作入口 */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          openStoryActions(story);
                        }}
                        className="absolute right-1.5 top-1.5 flex h-8 w-8 items-center justify-center rounded-full bg-black/35 text-white backdrop-blur-sm transition active:bg-black/55 md:hidden"
                        aria-label={`${story.title} 更多操作`}
                      >
                        <MoreHorizontal size={16} />
                      </button>
                    </div>

                    <div className="mt-2 px-0.5">
                      <div className="truncate text-sm font-medium text-slate-800" title={story.title}>
                        {story.title}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-400">
                        {new Date(story.created_at).toLocaleDateString('zh-CN')}
                      </div>
                    </div>
                  </>
                )}
              </div>
            );
          })}
          {stories.length === 0 && (
            <div className="col-span-full flex aspect-[2/3] w-full max-w-[200px] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 text-center text-sm text-slate-500">
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

      <ImportDialog
        open={showImportDialog}
        onClose={() => setShowImportDialog(false)}
        onImportComplete={(storyId) => {
          setShowImportDialog(false);
          onImportComplete(storyId);
        }}
      />
    </div>
  );
}
