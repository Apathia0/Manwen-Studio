import { BarChart3, FilePlus2, FileText, Loader2, Pencil } from 'lucide-react';
import { useMemo, useState } from 'react';
import { assessQuality, expandChapter, type Chapter } from '../../api';
import type { FrameworkChapter } from './types';
import { STATUS_COLORS, STATUS_LABELS } from './types';

interface Props {
  chapters: FrameworkChapter[] | null;
  actualChapters: Chapter[];
  storyId: number;
  onChapterSelect: (chapterNumber: number) => void;
  onUpdate: () => void | Promise<void>;
  onGenerateChapters: () => Promise<void>;
  onSaveChapterPlan: (
    mode: 'append' | 'insert_after' | 'update',
    chapter: { title: string; summary?: string; key_events?: string[]; act?: string },
    targetChapterNumber?: number,
  ) => Promise<void>;
}

interface PlanEditorState {
  mode: 'append' | 'insert_after' | 'update';
  targetChapterNumber?: number;
  draft: {
    title: string;
    summary: string;
    keyEventsText: string;
    act?: string;
  };
}

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const colorClass = STATUS_COLORS[status] || 'bg-gray-600 text-gray-200';
  const label = STATUS_LABELS[status] || status;
  return <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${colorClass}`}>{label}</span>;
}

function hasGeneratedChapterContent(chapter: Chapter | undefined): boolean {
  if (!chapter) return false;
  return Boolean(
    (chapter.novel_content && chapter.novel_content.trim()) ||
    (Array.isArray(chapter.messages) && chapter.messages.length > 0),
  );
}

function buildEditorDraft(chapter?: FrameworkChapter): PlanEditorState['draft'] {
  return {
    title: chapter?.title ?? '',
    summary: chapter?.summary ?? '',
    keyEventsText: Array.isArray(chapter?.key_events) ? chapter.key_events.join('\n') : '',
    act: chapter?.act,
  };
}

function parseKeyEvents(raw: string): string[] | undefined {
  const items = raw.split(/\r?\n|[;；]/).map((item) => item.trim()).filter(Boolean);
  return items.length > 0 ? items : undefined;
}

function PlanEditorCard({
  title,
  draft,
  saving,
  onChange,
  onCancel,
  onSave,
}: {
  title: string;
  draft: PlanEditorState['draft'];
  saving: boolean;
  onChange: (next: PlanEditorState['draft']) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div className="mt-2 rounded-lg border border-violet-700/40 bg-violet-950/20 p-3 space-y-2">
      <div className="text-[11px] font-medium text-violet-200">{title}</div>
      <input
        value={draft.title}
        onChange={(e) => onChange({ ...draft, title: e.target.value })}
        placeholder="章节标题"
        className="w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 outline-none focus:border-violet-500"
      />
      <textarea
        value={draft.summary}
        onChange={(e) => onChange({ ...draft, summary: e.target.value })}
        placeholder="章节简介"
        rows={3}
        className="w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-200 outline-none resize-y focus:border-violet-500"
      />
      <textarea
        value={draft.keyEventsText}
        onChange={(e) => onChange({ ...draft, keyEventsText: e.target.value })}
        placeholder="关键剧情点，一行一条"
        rows={4}
        className="w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-200 outline-none resize-y focus:border-violet-500"
      />
      <div className="flex items-center justify-end gap-2">
        <button onClick={onCancel} disabled={saving} className="rounded-md border border-gray-700 px-3 py-1.5 text-[11px] text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors disabled:opacity-40">
          取消
        </button>
        <button
          onClick={onSave}
          disabled={saving || !draft.title.trim()}
          className="inline-flex items-center gap-1 rounded-md border border-violet-700/40 bg-violet-600/20 px-3 py-1.5 text-[11px] font-medium text-violet-200 hover:bg-violet-600/30 transition-colors disabled:opacity-40"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <FilePlus2 size={12} />}
          保存章节规划
        </button>
      </div>
    </div>
  );
}

export default function ChapterListSection({
  chapters,
  actualChapters,
  storyId,
  onChapterSelect,
  onUpdate,
  onGenerateChapters,
  onSaveChapterPlan,
}: Props) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<'expand' | 'assess' | null>(null);
  const [editorState, setEditorState] = useState<PlanEditorState | null>(null);
  const [savingPlan, setSavingPlan] = useState(false);
  const [generatingChapters, setGeneratingChapters] = useState(false);
  const [error, setError] = useState('');

  const hasContent = chapters && chapters.length > 0;
  const actualChapterNumbers = useMemo(() => new Set(actualChapters.map((chapter) => chapter.chapter_number)), [actualChapters]);
  const actualChapterMap = useMemo(() => new Map(actualChapters.map((chapter) => [chapter.chapter_number, chapter])), [actualChapters]);

  const handleExpand = async (chapter: FrameworkChapter) => {
    if (busyId !== null) return;
    setBusyId(chapter.chapter_number);
    setBusyAction('expand');
    setError('');
    try {
      await expandChapter(storyId, {
        act: chapter.act,
        chapter_number: chapter.chapter_number,
        chapter_title: chapter.title,
        key_events: chapter.key_events,
      });
      await onUpdate();
      onChapterSelect(chapter.chapter_number);
    } catch (err: any) {
      setError(err.message || '扩写失败');
    } finally {
      setBusyId(null);
      setBusyAction(null);
    }
  };

  const handleAssess = async (chapter: FrameworkChapter) => {
    if (!chapter.id || busyId !== null) return;
    setBusyId(chapter.chapter_number);
    setBusyAction('assess');
    setError('');
    try {
      await assessQuality(chapter.id);
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '评估失败');
    } finally {
      setBusyId(null);
      setBusyAction(null);
    }
  };

  const openEditor = (mode: PlanEditorState['mode'], chapter?: FrameworkChapter, targetChapterNumber?: number) => {
    setError('');
    setEditorState({ mode, targetChapterNumber, draft: buildEditorDraft(chapter) });
  };

  const handleSavePlan = async () => {
    if (!editorState) return;
    setSavingPlan(true);
    setError('');
    try {
      await onSaveChapterPlan(
        editorState.mode,
        {
          title: editorState.draft.title.trim(),
          summary: editorState.draft.summary.trim() || undefined,
          key_events: parseKeyEvents(editorState.draft.keyEventsText),
          act: editorState.draft.act,
        },
        editorState.targetChapterNumber,
      );
      setEditorState(null);
    } catch (err: any) {
      setError(err.message || '保存章节规划失败');
    } finally {
      setSavingPlan(false);
    }
  };

  const handleGenerateChapters = async () => {
    setGeneratingChapters(true);
    setError('');
    try {
      await onGenerateChapters();
    } catch (err: any) {
      setError(err.message || '生成章节失败');
    } finally {
      setGeneratingChapters(false);
    }
  };

  if (!hasContent) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-gray-600">先生成故事框架，章节规划会在这里展示。</p>
        <button onClick={() => void handleGenerateChapters()} disabled={generatingChapters} className="inline-flex items-center gap-1 rounded-md border border-violet-700/40 bg-violet-600/15 px-2.5 py-1.5 text-[11px] font-medium text-violet-200 hover:bg-violet-600/25 transition-colors disabled:opacity-40">
          {generatingChapters ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
          AI 生成章节
        </button>
        <button onClick={() => openEditor('append')} className="inline-flex items-center gap-1 rounded-md border border-violet-700/40 bg-violet-600/15 px-2.5 py-1.5 text-[11px] font-medium text-violet-200 hover:bg-violet-600/25 transition-colors">
          <FilePlus2 size={12} />
          末尾新增章节
        </button>
        {editorState?.mode === 'append' && (
          <PlanEditorCard title="新增章节规划" draft={editorState.draft} saving={savingPlan} onChange={(draft) => setEditorState({ ...editorState, draft })} onCancel={() => setEditorState(null)} onSave={() => void handleSavePlan()} />
        )}
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    );
  }

  const actColors: Record<string, string> = {
    '1': 'border-l-violet-500/50',
    '2': 'border-l-amber-500/50',
    '3': 'border-l-emerald-500/50',
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">{chapters!.length} 话规划</span>
        <button onClick={() => void handleGenerateChapters()} disabled={generatingChapters || savingPlan} className="inline-flex items-center gap-1 rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1 text-[11px] font-medium text-gray-300 hover:bg-gray-700 disabled:opacity-40">
          {generatingChapters ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
          AI 生成章节
        </button>
      </div>

      {chapters!.map((chapter) => {
        const actBorder = actColors[String(chapter.act)] || 'border-l-gray-700/50';
        const actual = actualChapterMap.get(chapter.chapter_number);
        const canOpen = hasGeneratedChapterContent(actual);
        const isBusy = busyId === chapter.chapter_number;
        const isEditing = editorState?.mode === 'update' && editorState.targetChapterNumber === chapter.chapter_number;
        const isInserting = editorState?.mode === 'insert_after' && editorState.targetChapterNumber === chapter.chapter_number;
        const insertWillShiftGenerated = actualChapterNumbers.has(chapter.chapter_number + 1);

        return (
          <div key={chapter.chapter_number} className={`rounded-lg border-l-2 ${actBorder} bg-gray-900/30 px-3 py-2`}>
            <div className={`flex items-center gap-2 ${canOpen ? 'cursor-pointer' : ''}`} onClick={() => canOpen && onChapterSelect(chapter.chapter_number)}>
              <span className="w-12 shrink-0 text-xs font-mono text-gray-600">第{chapter.chapter_number}话</span>
              <span className="min-w-0 flex-1 truncate text-xs text-gray-300">{chapter.title}</span>
              <StatusBadge status={chapter.status} />
            </div>

            {(chapter.summary || (chapter.key_events && chapter.key_events.length > 0)) && (
              <p className="mt-2 text-[11px] leading-relaxed text-gray-500">{chapter.summary || chapter.key_events?.join('；')}</p>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                onClick={() => (canOpen ? onChapterSelect(chapter.chapter_number) : void handleExpand(chapter))}
                disabled={busyId !== null}
                className="inline-flex items-center gap-1 rounded-md border border-violet-700/40 bg-violet-600/15 px-2.5 py-1 text-[11px] font-medium text-violet-300 hover:bg-violet-600/25 disabled:opacity-40"
              >
                {isBusy && busyAction === 'expand' ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
                {canOpen ? '打开正文' : '生成正文'}
              </button>

              {chapter.id && (
                <button onClick={() => void handleAssess(chapter)} disabled={busyId !== null} className="inline-flex items-center gap-1 rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1 text-[11px] font-medium text-gray-400 hover:bg-gray-700 hover:text-gray-200 disabled:opacity-40">
                  {isBusy && busyAction === 'assess' ? <Loader2 size={12} className="animate-spin" /> : <BarChart3 size={12} />}
                  质量评估
                </button>
              )}

              <button onClick={() => openEditor('update', chapter, chapter.chapter_number)} disabled={savingPlan} className="inline-flex items-center gap-1 rounded-md border border-amber-700/40 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-200 hover:bg-amber-500/20 disabled:opacity-40">
                <Pencil size={12} />
                编辑规划
              </button>

              <button
                onClick={() => openEditor('insert_after', { ...chapter, title: '', summary: '', key_events: [] }, chapter.chapter_number)}
                disabled={savingPlan}
                className="inline-flex items-center gap-1 rounded-md border border-emerald-700/40 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
              >
                <FilePlus2 size={12} />
                在后面插入
              </button>
            </div>

            {isEditing && editorState && (
              <PlanEditorCard title={`编辑第 ${chapter.chapter_number} 话规划`} draft={editorState.draft} saving={savingPlan} onChange={(draft) => setEditorState({ ...editorState, draft })} onCancel={() => setEditorState(null)} onSave={() => void handleSavePlan()} />
            )}

            {isInserting && editorState && (
              <div>
                <PlanEditorCard title={`在第 ${chapter.chapter_number} 话后插入新章节`} draft={editorState.draft} saving={savingPlan} onChange={(draft) => setEditorState({ ...editorState, draft })} onCancel={() => setEditorState(null)} onSave={() => void handleSavePlan()} />
                {insertWillShiftGenerated && <p className="mt-2 text-[11px] text-amber-300/80">保存后，后续已生成正文的章节编号会自动顺延，避免大纲和正文对不上。</p>}
              </div>
            )}
          </div>
        );
      })}

      <div className="rounded-lg border border-dashed border-violet-700/40 bg-violet-950/10 p-3">
        <button onClick={() => openEditor('append')} disabled={savingPlan} className="inline-flex items-center gap-1 rounded-md border border-violet-700/40 bg-violet-600/15 px-2.5 py-1.5 text-[11px] font-medium text-violet-200 hover:bg-violet-600/25 disabled:opacity-40">
          <FilePlus2 size={12} />
          末尾新增章节
        </button>
        {editorState?.mode === 'append' && (
          <PlanEditorCard title="在章节列表尾部新增章节" draft={editorState.draft} saving={savingPlan} onChange={(draft) => setEditorState({ ...editorState, draft })} onCancel={() => setEditorState(null)} onSave={() => void handleSavePlan()} />
        )}
      </div>

      {error && <p className="px-1 pt-1 text-xs text-red-400">{error}</p>}
    </div>
  );
}
