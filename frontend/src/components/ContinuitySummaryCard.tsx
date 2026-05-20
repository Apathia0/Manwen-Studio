import { Check, ChevronDown, ChevronUp, Link2, Pencil, X } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { saveContinuityMemory, type Chapter, type Story } from '../api';

interface Props {
  story: Story;
  chapter: Chapter;
  previousChapter: Chapter | null;
  onSaved?: () => void;
}

export default function ContinuitySummaryCard({ story, chapter, previousChapter, onSaved }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [editSummary, setEditSummary] = useState('');
  const [editLocation, setEditLocation] = useState('');
  const [editConflict, setEditConflict] = useState('');
  const [editCharacters, setEditCharacters] = useState('');
  const [editStates, setEditStates] = useState('');
  const [editLoops, setEditLoops] = useState('');

  const data = useMemo(() => buildContinuityData(story, chapter, previousChapter), [story, chapter, previousChapter]);

  const startEditing = useCallback(() => {
    setEditSummary(data.summary);
    setEditLocation(data.location);
    setEditConflict(data.conflict);
    setEditCharacters(data.activeCharacters.join('\n'));
    setEditStates(data.characterStates.join('\n'));
    setEditLoops(data.immediateLoops.join('\n'));
    setEditing(true);
  }, [data]);

  const cancelEditing = useCallback(() => {
    setEditing(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (!chapter?.id || saving) return;
    setSaving(true);
    try {
      await saveContinuityMemory(chapter.id, {
        chapter_summary: { summary: editSummary.trim() },
        chapter_handoff: {
          ending_location: editLocation.trim(),
          active_conflict: editConflict.trim(),
          active_characters: editCharacters.split('\n').map((s) => s.trim()).filter(Boolean),
          character_states: editStates.split('\n').map((s) => s.trim()).filter(Boolean),
          immediate_open_loops: editLoops.split('\n').map((s) => s.trim()).filter(Boolean),
        },
      });
      setEditing(false);
      onSaved?.();
    } catch {
      // 错误由调用方处理
    } finally {
      setSaving(false);
    }
  }, [chapter?.id, saving, editSummary, editLocation, editConflict, editCharacters, editStates, editLoops, onSaved]);

  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-[linear-gradient(135deg,_#f8fbff_0%,_#eef5ff_100%)] p-4 shadow-[0_8px_20px_rgba(59,130,246,0.06)]">
      <div className="flex items-start justify-between gap-3">
        <button
          onClick={() => setExpanded((prev) => !prev)}
          className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left"
        >
          <div className="flex min-w-0 items-center gap-2">
            <Link2 size={16} className="shrink-0 text-[#2563eb]" />
            <span className="text-sm font-semibold text-slate-900">连续性记忆</span>
          </div>
          <div className="flex items-center gap-2">
            {expanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
          </div>
        </button>

        {editing ? (
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-1 rounded-xl bg-[#2563eb] px-3 py-1.5 text-xs font-medium text-white transition hover:bg-[#1d4ed8] disabled:opacity-60"
            >
              <Check size={13} />
              {saving ? '保存中...' : '保存'}
            </button>
            <button
              onClick={cancelEditing}
              disabled={saving}
              className="inline-flex items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
            >
              <X size={13} />
              取消
            </button>
          </div>
        ) : (
          <button
            onClick={startEditing}
            className="inline-flex shrink-0 items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-[#eef5ff] hover:text-[#2563eb]"
          >
            <Pencil size={13} />
            编辑
          </button>
        )}
      </div>

      {expanded ? (
        <div className="mt-3 border-t border-[#d7e3f4] pt-3 overflow-y-auto max-h-[360px]">
          {editing ? (
            /* ── 编辑模式 ── */
            <div className="space-y-4">
              <FieldEdit label="当前章摘要" value={editSummary} onChange={setEditSummary} multiline />
              <div className="grid gap-3 md:grid-cols-2">
                <FieldEdit label="当前开场位置" value={editLocation} onChange={setEditLocation} />
                <FieldEdit label="即时冲突" value={editConflict} onChange={setEditConflict} />
              </div>
              <FieldEdit label="在场角色（每行一个）" value={editCharacters} onChange={setEditCharacters} multiline />
              <FieldEdit label="角色当前状态（每行一个）" value={editStates} onChange={setEditStates} multiline />
              <FieldEdit label="下一章应继续推进（每行一个）" value={editLoops} onChange={setEditLoops} multiline />
            </div>
          ) : (
            /* ── 只读模式 ── */
            <div className="grid gap-3 xl:grid-cols-[1.05fr_0.95fr]">
              <section className="rounded-2xl border border-[#d9e5fb] bg-white/80 p-3 shadow-[0_8px_24px_rgba(59,130,246,0.08)]">
                <div className="mb-3 text-sm font-semibold text-slate-800">章节衔接</div>
                {data.hasPreviousHandoff ? (
                  <InfoCard label="上一章必须承接" value={data.previousOpeningMustContinue || '（已记录交接信息）'} accent="blue" />
                ) : (
                  <EmptyHint text="上一章还没有生成可复用的交接包。" />
                )}
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <InfoCard label="当前开场位置" value={data.location || '未记录'} />
                  <InfoCard label="即时冲突" value={data.conflict || '未记录'} />
                </div>
                {data.activeCharacters.length > 0 ? <ChipBlock className="mt-3" label="在场角色" items={data.activeCharacters} tone="blue" /> : null}
                {data.characterStates.length > 0 ? <TextBlock className="mt-3" label="角色当前状态" items={data.characterStates} /> : null}
                {data.immediateLoops.length > 0 ? <TextBlock className="mt-3" label="下一章应继续推进" items={data.immediateLoops} /> : null}
              </section>

              <section className="rounded-2xl border border-[#e4e6dc] bg-white/80 p-3 shadow-[0_8px_20px_rgba(15,23,42,0.05)]">
                <div className="mb-3 text-sm font-semibold text-slate-800">全局连续性</div>
                {data.summary ? <InfoCard label="当前章摘要" value={data.summary} accent="green" /> : <EmptyHint text="当前章还没有生成章节摘要。" />}
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <InfoCard label="故事状态" value={data.storyState || '未记录'} />
                  <InfoCard label="当前阶段焦点" value={data.arcFocus || '未记录'} />
                </div>
                {data.continuityFacts.length > 0 ? <TextBlock className="mt-3" label="必须记住的事实" items={data.continuityFacts} /> : null}
                {data.openLoops.length > 0 ? <ChipBlock className="mt-3" label="未回收伏笔" items={data.openLoops} tone="amber" /> : null}
              </section>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** 编辑字段组件 */
function FieldEdit({ label, value, onChange, multiline }: { label: string; value: string; onChange: (v: string) => void; multiline?: boolean }) {
  const cls =
    'w-full rounded-xl border border-[#d7e3f4] bg-white px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-[#93c5fd] focus:ring-4 focus:ring-[#dbeafe]';
  return (
    <div>
      <p className="mb-1 text-[11px] font-medium text-slate-500">{label}</p>
      {multiline ? (
        <textarea className={cls + ' min-h-[60px] resize-y'} value={value} onChange={(e) => onChange(e.target.value)} rows={3} />
      ) : (
        <input className={cls} value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  );
}

function InfoCard({
  label,
  value,
  accent = 'slate',
}: {
  label: string;
  value: string;
  accent?: 'slate' | 'blue' | 'green';
}) {
  const accentClass =
    accent === 'blue'
      ? 'border-blue-100 bg-blue-50/80'
      : accent === 'green'
        ? 'border-emerald-100 bg-emerald-50/70'
        : 'border-[#e7ebf3] bg-[#f8fafc]';
  const labelClass =
    accent === 'blue'
      ? 'text-blue-700'
      : accent === 'green'
        ? 'text-emerald-700'
        : 'text-slate-500';

  return (
    <div className={`rounded-xl border px-3 py-2 ${accentClass}`}>
      <p className={`text-[11px] font-medium ${labelClass}`}>{label}</p>
      <p className="mt-1 text-sm leading-6 text-slate-700">{value}</p>
    </div>
  );
}

function ChipBlock({
  className = '',
  label,
  items,
  tone = 'slate',
}: {
  className?: string;
  label: string;
  items: string[];
  tone?: 'slate' | 'blue' | 'amber';
}) {
  const toneClass =
    tone === 'blue'
      ? 'border-blue-200 bg-blue-50 text-blue-700'
      : tone === 'amber'
        ? 'border-amber-200 bg-amber-50 text-amber-700'
        : 'border-slate-200 bg-slate-50 text-slate-700';
  return (
    <div className={className}>
      <p className="mb-2 text-[11px] font-medium text-slate-500">{label}</p>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span key={item} className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${toneClass}`}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function TextBlock({ className = '', label, items }: { className?: string; label: string; items: string[] }) {
  return (
    <div className={className}>
      <p className="mb-2 text-[11px] font-medium text-slate-500">{label}</p>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item} className="rounded-xl border border-[#e7ebf3] bg-[#f8fafc] px-3 py-2 text-sm leading-6 text-slate-700">
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return <p className="rounded-xl border border-dashed border-[#d7deea] bg-[#f8fafc] px-3 py-2 text-sm text-slate-500">{text}</p>;
}

function buildContinuityData(story: Story, chapter: Chapter, previousChapter: Chapter | null) {
  const storyMemory = isRecord(story.story_memory) ? story.story_memory : {};
  const memorySummary = isRecord(chapter.memory_summary) ? chapter.memory_summary : {};
  const chapterSummary = isRecord(memorySummary.chapter_summary) ? memorySummary.chapter_summary : {};
  const chapterHandoff = isRecord(memorySummary.chapter_handoff) ? memorySummary.chapter_handoff : {};
  const previousMemory = isRecord(previousChapter?.memory_summary) ? previousChapter?.memory_summary : {};
  const previousHandoff = isRecord(previousMemory.chapter_handoff) ? previousMemory.chapter_handoff : {};

  function hasHandoffData(handoff: Record<string, unknown>): boolean {
    return Object.values(handoff).some((v) => {
      if (Array.isArray(v)) return v.length > 0;
      if (typeof v === 'string') return v.trim().length > 0;
      return Boolean(v);
    });
  }

  const data = {
    summary: text(chapterSummary.summary),
    previousOpeningMustContinue: text(previousHandoff.opening_must_continue),
    location: text(chapterHandoff.ending_location) || text(previousHandoff.ending_location),
    conflict: text(chapterHandoff.active_conflict) || text(previousHandoff.active_conflict),
    activeCharacters: toStringList(chapterHandoff.active_characters),
    characterStates: toStringList(chapterHandoff.character_states),
    immediateLoops: toStringList(chapterHandoff.immediate_open_loops),
    storyState: text(storyMemory.story_state),
    arcFocus: text(storyMemory.current_arc_focus),
    continuityFacts: toStringList(storyMemory.continuity_facts).slice(0, 4),
    openLoops: toStringList(storyMemory.open_loops).slice(0, 4),
  };

  return {
    ...data,
    hasPreviousHandoff: hasHandoffData(previousHandoff),
    hasAnyContent:
      Boolean(data.summary) ||
      Boolean(data.previousOpeningMustContinue) ||
      Boolean(data.location) ||
      Boolean(data.conflict) ||
      data.activeCharacters.length > 0 ||
      data.characterStates.length > 0 ||
      data.immediateLoops.length > 0 ||
      data.continuityFacts.length > 0 ||
      data.openLoops.length > 0,
  };
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}

function text(value: unknown): string {
  return String(value || '').trim();
}
