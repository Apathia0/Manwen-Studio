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
            className="rounded-md border border-[#d9dfd7] bg-white px-3 py-2 text-sm"
          >
            刷新
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
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {stories.map((story) => {
            const isEditing = editingId === story.id;
            const isSaving = savingId === story.id;
            const isDeleting = deletingId === story.id;
            const isExporting = exportingStoryId === story.id;
            return (
              <div
                key={story.id}
                className="rounded-md border border-[#d9dfd7] bg-white p-4 transition-colors hover:border-[#9fb3ad]"
              >
                {isEditing ? (
                  <div className="space-y-3">
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
                        创建于 {new Date(story.created_at).toLocaleDateString('zh-CN')}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={cancelEdit}
                          disabled={isSaving}
                          className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-white px-2 py-1.5 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <X size={12} />
                          取消
                        </button>
                        <button
                          onClick={() => void handleSaveEdit()}
                          disabled={isSaving}
                          className="inline-flex items-center gap-1 rounded-md bg-[#1f5f58] px-2 py-1.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Check size={12} />
                          {isSaving ? '保存中...' : '保存'}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    {story.cover_image ? (
                      <div className="mb-3 overflow-hidden rounded-md border border-[#d9dfd7] bg-[#f7f8f5]">
                        <img
                          src={coverImageUrl(story.cover_image) || ''}
                          alt={`${story.title} 封面`}
                          className="h-36 w-full object-cover"
                          loading="lazy"
                          decoding="async"
                        />
                      </div>
                    ) : null}
                    <button onClick={() => void onOpen(story)} className="w-full text-left">
                      <div className="text-sm font-semibold">{story.title}</div>
                      <div className="mt-1 min-h-[40px] line-clamp-2 text-xs leading-5 text-slate-600">
                        {story.description || '尚未填写简介，点击进入开始创作。'}
                      </div>
                    </button>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <div className="text-xs text-slate-500">
                        创建于 {new Date(story.created_at).toLocaleDateString('zh-CN')}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => void handleExport(story)}
                          disabled={isExporting || savingId !== null || deletingId !== null}
                          className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-white px-2 py-1.5 text-xs text-slate-700 hover:bg-[#f7f8f5] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <ScrollText size={12} />
                          {isExporting ? '导出中...' : '导出'}
                        </button>
                        <button
                          onClick={() => setCoverEditorStoryId(story.id)}
                          disabled={savingId !== null || deletingId !== null}
                          className="inline-flex items-center gap-1 rounded-md border border-[#bfdbfe] bg-[#eff6ff] px-2 py-1.5 text-xs text-[#1d4ed8] hover:bg-[#dbeafe] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <ImageIcon size={12} />
                          小说封面编辑
                        </button>
                        <button
                          onClick={() => startEdit(story)}
                          disabled={savingId !== null || deletingId !== null}
                          className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-white px-2 py-1.5 text-xs text-slate-700 hover:bg-[#f7f8f5] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Pencil size={12} />
                          编辑
                        </button>
                        <button
                          onClick={() => void handleDelete(story)}
                          disabled={savingId !== null || deletingId !== null}
                          className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-xs text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Trash2 size={12} />
                          {isDeleting ? '删除中...' : '删除'}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            );
          })}
          {stories.length === 0 && (
            <div className="rounded-md border border-dashed border-[#c8d0c8] bg-white p-5 text-sm text-slate-500">
              还没有作品。你可以先新建作品，也可以直接导入已有章节文稿。
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
