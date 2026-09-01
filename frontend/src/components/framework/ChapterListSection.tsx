import { BarChart3, FilePlus2, FileText, Loader2, Pencil } from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  assessQuality,
  expandChapter,
  expandChaptersBatch,
  waitForChapterBatch,
  cancelBackgroundTask,
  type Chapter,
  type ChapterBatchProgress,
} from '../../api';
import type { FrameworkChapter } from './types';
import { STATUS_COLORS, STATUS_LABELS } from './types';
import BatchGenerateDialog from './BatchGenerateDialog';

interface Props {
  chapters: FrameworkChapter[] | null;
  actualChapters: Chapter[];
  storyId: number;
  onChapterSelect: (chapterNumber: number) => void;
  onUpdate: () => void | Promise<void>;
  onGenerateChapters: () => Promise<void>;
  onSaveChapterPlan: (
    mode: 'append' | 'insert_after' | 'update',
    chapter: {
      title: string;
      summary?: string;
      key_events?: string[];
      act?: string;
      goal?: string;
      conflict?: string;
      hook?: string;
      payoff?: string;
      highlight?: string;
    },
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
    goal: string;
    conflict: string;
    hook: string;
    payoff: string;
    highlight: string;
  };
}

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const colorClass = STATUS_COLORS[status] || 'bg-slate-100 text-slate-600';
  const label = STATUS_LABELS[status] || status;
  return <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${colorClass}`}>{label}</span>;
}

function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-2 py-1">
      <div className="text-[10px] font-medium text-slate-500">{label}</div>
      <div className="mt-0.5 text-[11px] leading-relaxed text-slate-700">{value}</div>
    </div>
  );
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
    goal: chapter?.goal ?? '',
    conflict: chapter?.conflict ?? '',
    hook: chapter?.hook ?? '',
    payoff: chapter?.payoff ?? '',
    highlight: chapter?.highlight ?? '',
  };
}

function parseKeyEvents(raw: string): string[] | undefined {
  const items = raw.split(/\r?\n|[;,，]/).map((item) => item.trim()).filter(Boolean);
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
    <div className="mt-2 rounded-lg border border-blue-200 bg-blue-50/60 p-3 space-y-2">
      <div className="text-[11px] font-medium text-blue-700">{title}</div>
      <input
        value={draft.title}
        onChange={(e) => onChange({ ...draft, title: e.target.value })}
        placeholder="章节标题"
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-400"
      />
      <textarea
        value={draft.summary}
        onChange={(e) => onChange({ ...draft, summary: e.target.value })}
        placeholder="章节简介"
        rows={3}
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none resize-y focus:border-blue-400"
      />
      <textarea
        value={draft.keyEventsText}
        onChange={(e) => onChange({ ...draft, keyEventsText: e.target.value })}
        placeholder="关键剧情点，一行一条"
        rows={4}
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none resize-y focus:border-blue-400"
      />
      <div className="grid gap-2 md:grid-cols-2">
        <input
          value={draft.goal}
          onChange={(e) => onChange({ ...draft, goal: e.target.value })}
          placeholder="本章目标"
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-400"
        />
        <input
          value={draft.conflict}
          onChange={(e) => onChange({ ...draft, conflict: e.target.value })}
          placeholder="本章冲突"
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-400"
        />
        <input
          value={draft.hook}
          onChange={(e) => onChange({ ...draft, hook: e.target.value })}
          placeholder="章末钩子"
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-400"
        />
        <input
          value={draft.payoff}
          onChange={(e) => onChange({ ...draft, payoff: e.target.value })}
          placeholder="本章回报"
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-400"
        />
      </div>
      <input
        value={draft.highlight}
        onChange={(e) => onChange({ ...draft, highlight: e.target.value })}
        placeholder="爽点 / 情绪点 / 记忆点"
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-400"
      />
      <div className="flex items-center justify-end gap-2">
        <button onClick={onCancel} disabled={saving} className="rounded-md border border-slate-200 px-3 py-1.5 text-[11px] text-slate-600 hover:bg-slate-100 transition-colors disabled:opacity-40">
          取消
        </button>
        <button
          onClick={onSave}
          disabled={saving || !draft.title.trim()}
          className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-blue-500 transition-colors disabled:opacity-40"
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
  // 批量生成状态
  const [batchDialogOpen, setBatchDialogOpen] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchTaskId, setBatchTaskId] = useState<string | null>(null);
  const [batchProgress, setBatchProgress] = useState<ChapterBatchProgress | null>(null);

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
        summary: chapter.summary,
        goal: chapter.goal,
        conflict: chapter.conflict,
        hook: chapter.hook,
        payoff: chapter.payoff,
        highlight: chapter.highlight,
      });
      await onUpdate();
      onChapterSelect(chapter.chapter_number);
    } catch (err: any) {
      setError(err.message || '扩写章节失败');
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
      setError(err.message || '质量评估失败');
    } finally {
      setBusyId(null);
      setBusyAction(null);
    }
  };

  // ── 批量章节生成 ──────────────────────────────────────────
  const handleBatchExpand = async (chapterNumbers: number[]) => {
    if (batchRunning || chapterNumbers.length === 0) return;
    if (chapterNumbers.length > 10) {
      setError('单次批量最多 10 章');
      return;
    }
    setError('');
    setBatchRunning(true);
    setBatchProgress({
      stage: 'queued',
      message: `批量生成任务已提交，共 ${chapterNumbers.length} 章，正在排队…`,
      batch_total: chapterNumbers.length,
      batch_completed: [],
      batch_failed: [],
      status: 'pending',
      error_message: null,
    });
    try {
      const submitted = await expandChaptersBatch(storyId, chapterNumbers);
      setBatchTaskId(submitted.task_id);
      // 任务已提交后立即关闭选择窗口，后台轮询与左侧进度展示继续进行。
      setBatchDialogOpen(false);
      let refreshedCompletedCount = 0;
      const finalProgress = await waitForChapterBatch(submitted.task_id, (progress) => {
        setBatchProgress(progress);
        // 每章完成后立即刷新章节列表，让正文状态和“打开正文”按钮及时回显。
        if (progress.batch_completed.length > refreshedCompletedCount) {
          refreshedCompletedCount = progress.batch_completed.length;
          void onUpdate();
        }
      });
      if (finalProgress.status === 'failed' || finalProgress.status === 'cancelled' || finalProgress.stage === 'failed') {
        const firstFailure = finalProgress.batch_failed[0];
        setError(
          `批量生成${finalProgress.status === 'cancelled' ? '已取消' : '中止'}：${
            firstFailure ? `第${firstFailure.chapter_number}章失败（${firstFailure.reason}）` : finalProgress.message
          }`,
        );
      }
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '批量生成失败');
    } finally {
      setBatchRunning(false);
      setBatchTaskId(null);
    }
  };

  const handleCancelBatch = async () => {
    if (!batchTaskId || !batchRunning) return;
    try {
      await cancelBackgroundTask(batchTaskId);
      setBatchProgress((prev) => prev ? { ...prev, stage: 'cancel_requested', status: 'cancel_requested', message: '正在停止批量生成任务…' } : prev);
    } catch (err: any) {
      setError(err.message || '停止批量生成失败');
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
          goal: editorState.draft.goal.trim() || undefined,
          conflict: editorState.draft.conflict.trim() || undefined,
          hook: editorState.draft.hook.trim() || undefined,
          payoff: editorState.draft.payoff.trim() || undefined,
          highlight: editorState.draft.highlight.trim() || undefined,
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
        <p className="text-xs text-slate-600">先生成故事框架，章节规划会在这里展示。</p>
        <button onClick={() => void handleGenerateChapters()} disabled={generatingChapters} className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-[11px] font-medium text-blue-700 hover:bg-blue-100 transition-colors disabled:opacity-40">
          {generatingChapters ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
          AI 生成章节
        </button>
        <button onClick={() => openEditor('append')} className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-slate-700 hover:bg-slate-50 transition-colors">
          <FilePlus2 size={12} />
          末尾新增章节
        </button>
        {editorState?.mode === 'append' && (
          <PlanEditorCard title="新增章节规划" draft={editorState.draft} saving={savingPlan} onChange={(draft) => setEditorState({ ...editorState, draft })} onCancel={() => setEditorState(null)} onSave={() => void handleSavePlan()} />
        )}
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    );
  }

  const actColors: Record<string, string> = {
    '1': 'border-l-blue-400',
    '2': 'border-l-sky-400',
    '3': 'border-l-emerald-400',
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">{chapters!.length} 话规划</span>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setBatchDialogOpen(true)}
            disabled={batchRunning}
            className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-100 transition-colors disabled:opacity-40"
          >
            <FileText size={12} />
            批量生成
          </button>
        </div>
      </div>

      {batchProgress && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <div className="flex items-center gap-2">
            {batchRunning && <Loader2 size={13} className="animate-spin text-amber-600" />}
            <span className="text-xs font-medium text-amber-800">{batchProgress.message || (batchRunning ? '批量生成进行中…' : '批量生成已结束')}</span>
          </div>
          {batchProgress.batch_total > 0 && (
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-amber-100">
              <div
                className="h-full rounded-full bg-amber-500 transition-all"
                style={{ width: `${Math.round(((batchProgress.batch_completed.length + batchProgress.batch_failed.length) / batchProgress.batch_total) * 100)}%` }}
              />
            </div>
          )}
          <p className="mt-1 text-[11px] text-amber-700">可关闭页面,任务会在服务器继续执行；串行生成保证章节上下文连贯。</p>
          {batchRunning && batchTaskId && (
            <button
              onClick={() => void handleCancelBatch()}
              className="mt-2 inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2.5 py-1 text-[11px] font-medium text-red-700 hover:bg-red-50"
            >
              停止生成
            </button>
          )}
        </div>
      )}

      {chapters!.map((chapter) => {
        const actBorder = actColors[String(chapter.act)] || 'border-l-slate-300';
        const actual = actualChapterMap.get(chapter.chapter_number);
        const canOpen = hasGeneratedChapterContent(actual);
        const isBusy = busyId === chapter.chapter_number;
        const isEditing = editorState?.mode === 'update' && editorState.targetChapterNumber === chapter.chapter_number;
        const isInserting = editorState?.mode === 'insert_after' && editorState.targetChapterNumber === chapter.chapter_number;
        const insertWillShiftGenerated = actualChapterNumbers.has(chapter.chapter_number + 1);

        return (
          <div key={chapter.chapter_number} className={`rounded-xl border border-slate-200 border-l-4 ${actBorder} bg-slate-50 px-3 py-2`}>
            <div className={`flex items-center gap-2 ${canOpen ? 'cursor-pointer' : ''}`} onClick={() => canOpen && onChapterSelect(chapter.chapter_number)}>
              <span className="w-14 shrink-0 text-xs font-mono text-slate-500">第{chapter.chapter_number}话</span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-700">{chapter.title}</span>
              <StatusBadge status={chapter.status} />
            </div>

            {(chapter.summary || (chapter.key_events && chapter.key_events.length > 0)) && (
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{chapter.summary || chapter.key_events?.join('；')}</p>
            )}

            {(chapter.goal || chapter.conflict || chapter.hook || chapter.payoff || chapter.highlight) && (
              <div className="mt-2 grid gap-1.5 md:grid-cols-2">
                {chapter.goal && <MetaPill label="目标" value={chapter.goal} />}
                {chapter.conflict && <MetaPill label="冲突" value={chapter.conflict} />}
                {chapter.hook && <MetaPill label="钩子" value={chapter.hook} />}
                {chapter.payoff && <MetaPill label="回报" value={chapter.payoff} />}
                {chapter.highlight && <MetaPill label="亮点" value={chapter.highlight} />}
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                onClick={() => onChapterSelect(chapter.chapter_number)}
                className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-100"
              >
                <FileText size={12} />
                打开正文
              </button>

              {!canOpen && (
                <button
                  onClick={() => void handleExpand(chapter)}
                  disabled={busyId !== null}
                  className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40"
                >
                  {isBusy && busyAction === 'expand' ? (
                    <>
                      <Loader2 size={12} className="animate-spin" />
                      <span>生成中...</span>
                    </>
                  ) : (
                    <>
                      <FileText size={12} />
                      <span>生成正文</span>
                    </>
                  )}
                </button>
              )}

              {chapter.id && (
                <button onClick={() => void handleAssess(chapter)} disabled={busyId !== null} className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-slate-800 disabled:opacity-40">
                  {isBusy && busyAction === 'assess' ? (
                    <>
                      <Loader2 size={12} className="animate-spin" />
                      <span>评估中...</span>
                    </>
                  ) : (
                    <>
                      <BarChart3 size={12} />
                      <span>质量评估</span>
                    </>
                  )}
                </button>
              )}

              <button onClick={() => openEditor('update', chapter, chapter.chapter_number)} disabled={savingPlan} className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-40">
                <Pencil size={12} />
                编辑规划
              </button>

              <button
                onClick={() => openEditor('insert_after', { ...chapter, title: '', summary: '', key_events: [] }, chapter.chapter_number)}
                disabled={savingPlan}
                className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40"
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
                {insertWillShiftGenerated && <p className="mt-2 text-[11px] text-amber-700">保存后，后续已生成正文的章节编号会自动顺延，避免大纲和正文对不上。</p>}
              </div>
            )}
          </div>
        );
      })}

      <BatchGenerateDialog
        isOpen={batchDialogOpen}
        chapters={chapters!}
        actualChapters={actualChapters}
        onClose={() => setBatchDialogOpen(false)}
        onSubmit={handleBatchExpand}
        batchRunning={batchRunning}
        batchProgress={batchProgress}
      />

      {error && <p className="px-1 pt-1 text-xs text-red-500">{error}</p>}
    </div>
  );
}
