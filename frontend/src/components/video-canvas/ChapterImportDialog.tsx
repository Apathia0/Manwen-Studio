import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, CheckSquare, Loader2, Square, X } from 'lucide-react';
import {
  importScreenplay,
  listImportableNovelStories,
  type ImportableNovelStory,
} from '../../api';
import { normalizeErrorMessage } from '../../lib/errors';
import { toast } from '../../lib/toast';

interface ChapterImportDialogProps {
  canvasId: number;
  onClose: () => void;
  onImported: (screenplayText: string, sourceRefs: { story_id: number; chapter_id: number; title: string; content_hash: string }[]) => void;
}

/** 小说章节选择器：从用户名下 novel 作品导入章节正文，AI 改写为剧本草稿。 */
export default function ChapterImportDialog({ canvasId, onClose, onImported }: ChapterImportDialogProps) {
  const [stories, setStories] = useState<ImportableNovelStory[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeStoryId, setActiveStoryId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Map<number, { story_id: number; chapter_id: number; title: string }>>(new Map());
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listImportableNovelStories();
        if (cancelled) return;
        setStories(res.stories);
        if (res.stories.length > 0) setActiveStoryId(res.stories[0].story_id);
      } catch (err) {
        if (!cancelled) toast.error(normalizeErrorMessage(err, '加载小说作品失败'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const activeStory = useMemo(
    () => stories.find((story) => story.story_id === activeStoryId) || null,
    [stories, activeStoryId],
  );

  const toggleChapter = useCallback((storyId: number, chapterId: number, title: string) => {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(chapterId)) next.delete(chapterId);
      else next.set(chapterId, { story_id: storyId, chapter_id: chapterId, title });
      return next;
    });
  }, []);

  const handleImport = useCallback(async () => {
    if (selected.size === 0) return;
    setImporting(true);
    try {
      const result = await importScreenplay(canvasId, Array.from(selected.values()));
      toast.success(`剧本草稿已生成（${result.batch_count} 批改写，共 ${result.content_chars} 字）`);
      onImported(result.screenplay_text, result.source_refs);
    } catch (err) {
      toast.error(normalizeErrorMessage(err, '章节导入失败'));
    } finally {
      setImporting(false);
    }
  }, [canvasId, selected, onImported]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onPointerDown={(e) => { if (e.target === e.currentTarget && !importing) onClose(); }}>
      <div className="flex h-[560px] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-2xl">
        {/* 头部 */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#d7e3f4] px-4 py-3">
          <div className="flex items-center gap-2">
            <BookOpen size={16} className="text-slate-500" />
            <span className="text-sm font-medium text-slate-900">导入小说章节为剧本</span>
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-600">AI 将把小说正文改写为剧本草稿</span>
          </div>
          <button type="button" onClick={onClose} disabled={importing} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-40">
            <X size={16} />
          </button>
        </div>

        {loading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-slate-400">
            <Loader2 size={16} className="animate-spin" /> 正在加载小说作品…
          </div>
        ) : stories.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-slate-400">
            <BookOpen size={22} className="text-slate-300" />
            <p>名下还没有小说作品</p>
            <p className="text-xs text-slate-400">先在「作品」中创建小说并生成章节正文，再回到这里导入</p>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1">
            {/* 左栏：作品列表 */}
            <div className="w-48 shrink-0 overflow-y-auto border-r border-[#d7e3f4] bg-slate-50/60">
              {stories.map((story) => (
                <button
                  key={story.story_id}
                  type="button"
                  onClick={() => setActiveStoryId(story.story_id)}
                  className={`block w-full px-3 py-2.5 text-left text-xs transition-colors ${story.story_id === activeStoryId ? 'bg-white font-medium text-blue-700 shadow-sm' : 'text-slate-600 hover:bg-white/60'}`}
                >
                  <span className="block truncate">{story.title}</span>
                  <span className="mt-0.5 block text-[10px] text-slate-400">{story.chapter_count} 章</span>
                </button>
              ))}
            </div>
            {/* 右栏：章节多选 */}
            <div className="min-w-0 flex-1 overflow-y-auto p-2">
              {activeStory?.chapters.length === 0 && <p className="p-4 text-xs text-slate-400">该作品暂无章节</p>}
              {activeStory?.chapters.map((chapter: ImportableNovelStory['chapters'][number]) => {
                const isSelected = selected.has(chapter.chapter_id);
                return (
                  <button
                    key={chapter.chapter_id}
                    type="button"
                    disabled={!chapter.has_content}
                    onClick={() => toggleChapter(activeStory.story_id, chapter.chapter_id, chapter.title || `第${chapter.chapter_number}章`)}
                    className={`mb-1 flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${isSelected ? 'border-blue-300 bg-blue-50/60 text-blue-800' : 'border-transparent hover:bg-slate-50 text-slate-700'}`}
                  >
                    {isSelected ? <CheckSquare size={14} className="shrink-0 text-blue-600" /> : <Square size={14} className="shrink-0 text-slate-300" />}
                    <span className="min-w-0 flex-1 truncate">{chapter.title || `第${chapter.chapter_number}章`}</span>
                    <span className="shrink-0 text-[10px] text-slate-400">{chapter.has_content ? `${chapter.content_chars} 字` : '正文为空'}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 底部操作栏 */}
        <div className="flex shrink-0 items-center justify-between border-t border-[#d7e3f4] px-4 py-3">
          <span className="text-xs text-slate-500">已选 {selected.size} 章（最多 10 章）</span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} disabled={importing} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40">
              取消
            </button>
            <button
              type="button"
              onClick={() => void handleImport()}
              disabled={importing || selected.size === 0}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              {importing && <Loader2 size={13} className="animate-spin" />}
              {importing ? 'AI 改写中，可能需要一到几分钟…' : '导入并改写为剧本'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
