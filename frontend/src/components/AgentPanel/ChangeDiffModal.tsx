import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Loader2, Check, Undo2, FileText, Tags, Users, BookOpen, Film, ChevronRight, ChevronsUpDown } from 'lucide-react';
import { lineDiff, type DiffLine } from '../../utils/diff';
import { apiHeaders } from '../../api';
import { toast } from '../../lib/toast';

export interface FullChangeData {
  type: string;
  record_id: number;
  display_name: string;
  field: string;
  old_value: string;
  new_value: string;
}

interface Props {
  storyId: number;
  conversationId?: number | null;
  runId?: string | null;
  onConfirm: () => void;
  onRollback: () => void;
  onClose: () => void;
}

const 字段图标: Record<string, React.ReactNode> = {
  novel_content: <FileText size={14} />,
  title: <FileText size={14} />,
  description: <FileText size={14} />,
  tags: <Tags size={14} />,
  characters: <Users size={14} />,
  outline: <BookOpen size={14} />,
  scenes_file: <Film size={14} />,
  screenplay_text: <FileText size={14} />,
  screenplay_json: <FileText size={14} />,
  storyboard_prompt: <Film size={14} />,
  video_prompt: <Film size={14} />,
  scene_prompt: <Film size={14} />,
  character_prompts_json: <Users size={14} />,
  prop_prompts_json: <Tags size={14} />,
  camera_plan: <Film size={14} />,
  motion_plan: <Film size={14} />,
  emotion_plan: <Film size={14} />,
  story_summary: <FileText size={14} />,
  scene_location: <FileText size={14} />,
  character_reference_ids: <Users size={14} />,
  creative_brief: <BookOpen size={14} />,
  writing_guidance: <FileText size={14} />,
};

const 字段中文: Record<string, string> = {
  novel_content: '正文内容',
  title: '标题',
  description: '描述',
  tags: '标签',
  characters: '角色设定',
  outline: '大纲',
  scenes_file: '分镜',
  screenplay_text: '剧本文本',
  screenplay_json: '剧本结构',
  storyboard_prompt: '故事版提示词',
  video_prompt: '视频提示词',
  scene_prompt: '场景提示词',
  character_prompts_json: '角色提示词',
  prop_prompts_json: '道具提示词',
  camera_plan: '镜头规划',
  motion_plan: '动作规划',
  emotion_plan: '情绪规划',
  story_summary: '剧情摘要',
  scene_location: '场景地点',
  time_of_day: '时间',
  character_reference_ids: '角色引用',
  scene_reference_ids: '场景引用',
  prop_reference_ids: '道具引用',
  creative_brief: '创意简报',
  writing_guidance: '写作指导',
};

const 类型色: Record<string, string> = {
  chapter: 'border-l-blue-400',
  story: 'border-l-emerald-400',
  scenes_file: 'border-l-amber-400',
  story_bible: 'border-l-purple-400',
  video_shot: 'border-l-violet-400',
  video_workflow: 'border-l-indigo-400',
};

function DiffBlock({ lines }: { lines: DiffLine[] }) {
  const added = lines.filter((l) => l.type === 'add').length;
  const removed = lines.filter((l) => l.type === 'remove').length;
  const hasDiff = added > 0 || removed > 0;

  if (!hasDiff) {
    return <div className="text-xs text-gray-400 italic py-4 text-center">无差异</div>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 text-xs font-mono leading-5">
      <div>
        {lines.map((line, i) => (
          <div
            key={i}
            className={
              line.type === 'add'
                ? 'bg-emerald-50 text-emerald-700 px-3'
                : line.type === 'remove'
                ? 'bg-red-50 text-red-600 px-3'
                : 'bg-transparent text-gray-500 px-3'
            }
          >
            <span className="inline-block w-4 shrink-0 select-none opacity-50">
              {line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}
            </span>
            <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">{line.text || ' '}</span>
          </div>
        ))}
      </div>
      <div className="px-3 py-1 text-xs border-t border-gray-200 text-gray-400 bg-gray-50 shrink-0">
        <span className="text-emerald-600">+{added}</span>
        {' '}
        <span className="text-red-500">−{removed}</span>
        {' 行变动'}
      </div>
    </div>
  );
}

function FieldSection({ change, defaultCollapsed = false }: { change: FullChangeData; defaultCollapsed?: boolean }) {
  const [mode, setMode] = useState<'diff' | 'old' | 'new'>('diff');
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const diff = lineDiff(change.old_value, change.new_value);
  const added = diff.filter((l) => l.type === 'add').length;
  const removed = diff.filter((l) => l.type === 'remove').length;

  return (
    <div className={`border-l-2 ${类型色[change.type] || 'border-l-gray-300'} pl-4 py-1.5`}>
      <button
        type="button"
        aria-expanded={!collapsed}
        className="group -ml-1 flex w-full cursor-pointer select-none items-center gap-2 rounded-lg py-1.5 pl-1 text-left transition-colors hover:bg-gray-50/80"
        onClick={() => setCollapsed(!collapsed)}
      >
        <ChevronRight
          size={14}
          className={`text-gray-400 transition-transform duration-200 shrink-0 ${
            collapsed ? '' : 'rotate-90'
          }`}
        />
        <span className="text-gray-400 shrink-0">{字段图标[change.field] || <FileText size={14} />}</span>
        <span className="text-sm font-medium text-gray-700 truncate">
          {change.display_name}
        </span>
        <span className="text-xs text-gray-300 shrink-0">·</span>
        <span className="text-xs text-gray-500 shrink-0">{字段中文[change.field] || change.field}</span>
        <span className="ml-auto text-xs text-gray-400 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-emerald-600">+{added}</span>
          {' '}
          <span className="text-red-500">−{removed}</span>
        </span>
      </button>

      {!collapsed && (
        <div className="mt-1 transition-all duration-200">
          <div className="flex gap-1 mb-2 ml-1">
            {(['diff', 'old', 'new'] as const).map((m) => (
              <button
                key={m}
                onClick={(e) => { e.stopPropagation(); setMode(m); }}
                className={`px-2 py-0.5 rounded text-xs transition-colors ${
                  mode === m
                    ? 'bg-gray-200 text-gray-700'
                    : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                {m === 'diff' ? '差异对比' : m === 'old' ? '修改前' : '修改后'}
              </button>
            ))}
          </div>

          {mode === 'diff' && <DiffBlock lines={diff} />}
          {mode === 'old' && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs font-mono text-gray-600 leading-5 whitespace-pre-wrap [overflow-wrap:anywhere]">
              {change.old_value || '(空)'}
            </div>
          )}
          {mode === 'new' && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3 text-xs font-mono text-emerald-700 leading-5 whitespace-pre-wrap [overflow-wrap:anywhere]">
              {change.new_value || '(空)'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ChangeDiffModal({ storyId, conversationId, runId, onConfirm, onRollback, onClose }: Props) {
  const [changes, setChanges] = useState<FullChangeData[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'confirming' | 'rolling' | null>(null);
  const [allExpanded, setAllExpanded] = useState(true);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams();
        if (conversationId) params.set('conversation_id', String(conversationId));
        if (runId) params.set('run_id', runId);
        const query = params.size ? `?${params.toString()}` : '';
        const res = await fetch(`/api/stories/${storyId}/agent/pending-changes${query}`, {
          headers: apiHeaders(),
        });
        if (!cancelled) {
          const data = await res.json();
          setChanges(data.changes ?? []);
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [storyId, conversationId, runId]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (busyRef.current === null) onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;

      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (!activeElement || !focusable.includes(activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  const handleClose = () => {
    if (busy === null) onClose();
  };

  const handleConfirm = async () => {
    if (busy !== null) return;
    setBusy('confirming');
    try {
      const { agentConfirmChanges } = await import('../../api');
      await agentConfirmChanges(storyId, conversationId, runId);
      onConfirm();
    } finally {
      setBusy(null);
    }
  };

  const handleRollback = async () => {
    if (busy !== null) return;
    setBusy('rolling');
    try {
      const { agentRollbackChanges } = await import('../../api');
      const result = await agentRollbackChanges(storyId, conversationId, runId);
      if (result.pending_retained) {
        const message = result.results?.find((item) => !item.ok)?.error || '部分修改已发生变化，无法安全撤回';
        toast.error(message, 8000);
        return;
      }
      onRollback();
    } finally {
      setBusy(null);
    }
  };

  return createPortal(
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-3 backdrop-blur-sm sm:p-6"
      onClick={(e) => { if (e.target === overlayRef.current) handleClose(); }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-diff-title"
        className="flex h-[85dvh] min-h-[min(32rem,calc(100dvh-1.5rem))] max-h-[calc(100dvh-1.5rem)] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_18px_42px_rgba(59,130,246,0.15)]"
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#d7e3f4] shrink-0">
          <div className="flex items-center gap-3">
            <h2 id="change-diff-title" className="text-base font-semibold text-gray-800">修改对比</h2>
            {changes && changes.length > 0 && (
              <button
                onClick={() => setAllExpanded(!allExpanded)}
                className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <ChevronsUpDown size={13} />
                {allExpanded ? '全部折叠' : '全部展开'}
              </button>
            )}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={handleClose}
            disabled={busy !== null}
            aria-label="关闭修改对比"
            title="关闭"
            className="p-1 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
          >
            <X size={18} />
          </button>
        </div>

        {/* 内容 */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-3 space-y-1">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-gray-400">
              <Loader2 size={20} className="animate-spin mr-2" />
              加载修改数据…
            </div>
          ) : !changes || changes.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">没有待确认的修改</div>
          ) : (
            changes.map((c, i) => <FieldSection key={`${c.type}-${c.record_id}-${c.field}-${i}-${allExpanded}`} change={c} defaultCollapsed={!allExpanded} />)
          )}
        </div>

        {/* 操作栏 */}
        {changes && changes.length > 0 && (
          <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-[#d7e3f4] shrink-0">
            <button
              onClick={handleRollback}
              disabled={busy !== null}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-100 hover:bg-red-200 disabled:opacity-50 text-red-600 text-sm font-medium transition-colors"
            >
              {busy === 'rolling' ? <Loader2 size={15} className="animate-spin" /> : <Undo2 size={15} />}
              撤回所有修改
            </button>
            <button
              onClick={handleConfirm}
              disabled={busy !== null}
              className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
            >
              {busy === 'confirming' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              确认所有修改
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
