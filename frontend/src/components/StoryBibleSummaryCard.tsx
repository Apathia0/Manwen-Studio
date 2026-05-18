import { BookOpen, ChevronDown, ChevronUp, Loader2, Pencil, Save, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { updateStoryBible, type StoryBible } from '../api';

interface Props {
  storyId: number;
  storyBible: StoryBible;
  onUpdated?: () => void | Promise<void>;
}

type StoryBibleFormState = {
  project_positioning: string;
  genre: string;
  audience: string;
  tone: string;
  core_hook: string;
  one_line_premise: string;
  protagonist_core: string;
  main_conflict: string;
  longline_mystery: string;
  serial_length_target: string;
  must_keep_rules: string;
  reveal_strategy: string;
  pacing_strategy: string;
  opening_strategy: string;
  chapter_density_strategy: string;
  midgame_engine: string;
  late_game_direction: string;
  forbidden_patterns: string;
  preferred_plot_patterns: string;
};

export default function StoryBibleSummaryCard({ storyId, storyBible, onUpdated }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const formInitialState = useMemo(() => createFormState(storyBible), [storyBible]);
  const [form, setForm] = useState<StoryBibleFormState>(formInitialState);

  useEffect(() => {
    setForm(formInitialState);
  }, [formInitialState]);

  const brief = storyBible.creative_brief;
  const guidance = storyBible.writing_guidance;
  const mustKeepRules = Array.isArray(brief?.must_keep_rules) ? brief.must_keep_rules : [];
  const forbiddenPatterns = Array.isArray(guidance?.forbidden_patterns) ? guidance.forbidden_patterns : [];
  const preferredPlotPatterns = Array.isArray(guidance?.preferred_plot_patterns) ? guidance.preferred_plot_patterns : [];

  if (!brief) return null;

  const handleChange = (key: keyof StoryBibleFormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await updateStoryBible(storyId, buildStoryBiblePayload(form, storyBible));
      setEditOpen(false);
      await onUpdated?.();
    } catch (err: any) {
      setError(err?.message || '更新作品圣经失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-[linear-gradient(135deg,_#f8fbff_0%,_#eff6ff_100%)] p-4 shadow-[0_8px_20px_rgba(59,130,246,0.06)]">
      <div className="flex items-start justify-between gap-3">
        <button
          onClick={() => setExpanded((prev) => !prev)}
          className="flex min-w-0 flex-1 items-center justify-between gap-3"
        >
          <div className="flex min-w-0 items-center gap-2">
            <BookOpen size={16} className="shrink-0 text-[#2563eb]" />
            <span className="text-sm font-semibold text-slate-900">作品圣经摘要</span>
            {brief.one_line_premise ? (
              <span className="hidden max-w-[420px] truncate text-sm text-slate-500 md:inline-block">
                {brief.one_line_premise}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">
              {brief.genre} / {brief.audience} / {brief.serial_length_target}
            </span>
            {expanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
          </div>
        </button>

        <button
          onClick={() => {
            setError('');
            setForm(createFormState(storyBible));
            setEditOpen(true);
          }}
          className="inline-flex shrink-0 items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-[#f8fbff]"
        >
          <Pencil size={13} />
          调整
        </button>
      </div>

      {expanded ? (
        <div className="mt-3 border-t border-[#d7e3f4] pt-3">
          <div className="max-h-[min(65vh,720px)] overflow-y-auto pr-1">
            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              <InfoItem label="作品定位" value={brief.project_positioning} />
              <InfoItem label="题材" value={brief.genre} />
              <InfoItem label="受众" value={brief.audience} />
              <InfoItem label="风格基调" value={brief.tone} />
              <InfoItem label="核心卖点" value={brief.core_hook} />
              <InfoItem label="一句话梗概" value={brief.one_line_premise} />
              <InfoItem label="主角核心" value={brief.protagonist_core} />
              <InfoItem label="主线矛盾" value={brief.main_conflict} />
              <InfoItem label="长线悬念" value={brief.longline_mystery} />
              <InfoItem label="目标篇幅" value={brief.serial_length_target} />
              <InfoItem label="揭秘策略" value={brief.reveal_strategy} />
              <InfoItem label="节奏策略" value={brief.pacing_strategy} />
              {mustKeepRules.length > 0 ? (
                <ListItem label="必保留设定" items={mustKeepRules} tone="blue" />
              ) : null}
              {guidance ? (
                <>
                  <InfoItem label="开书策略" value={guidance.opening_strategy} />
                  <InfoItem label="章节密度策略" value={guidance.chapter_density_strategy} />
                  <InfoItem label="中段驱动力" value={guidance.midgame_engine} />
                  <InfoItem label="后期方向" value={guidance.late_game_direction} />
                  {forbiddenPatterns.length > 0 ? (
                    <ListItem label="避免的模式" items={forbiddenPatterns} tone="red" />
                  ) : null}
                  {preferredPlotPatterns.length > 0 ? (
                    <ListItem label="推荐情节模式" items={preferredPlotPatterns} tone="green" />
                  ) : null}
                </>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {editOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
          <div className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] border border-[#d7e3f4] bg-white shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
            <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
              <div>
                <div className="text-base font-semibold text-slate-900">调整作品圣经</div>
                <div className="mt-1 text-xs text-slate-500">
                  生成完成后可以继续修改摘要和写作指导，保存后会刷新当前工作台。
                </div>
              </div>
              <button
                onClick={() => !saving && setEditOpen(false)}
                disabled={saving}
                className="rounded-full border border-[#d7e3f4] bg-white p-1.5 text-slate-400 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <X size={16} />
              </button>
            </div>

            <div className="grid min-h-0 flex-1 lg:grid-cols-2">
              <div className="min-h-0 overflow-y-auto border-b border-[#e5edf8] px-6 py-5 lg:border-b-0 lg:border-r">
                <div className="mb-4 text-sm font-semibold text-slate-900">创意摘要</div>
                <div className="space-y-3">
                  <Field label="作品定位" value={form.project_positioning} onChange={(value) => handleChange('project_positioning', value)} multiline />
                  <Field label="题材" value={form.genre} onChange={(value) => handleChange('genre', value)} />
                  <Field label="受众" value={form.audience} onChange={(value) => handleChange('audience', value)} />
                  <Field label="风格基调" value={form.tone} onChange={(value) => handleChange('tone', value)} multiline />
                  <Field label="核心卖点" value={form.core_hook} onChange={(value) => handleChange('core_hook', value)} multiline />
                  <Field label="一句话梗概" value={form.one_line_premise} onChange={(value) => handleChange('one_line_premise', value)} multiline />
                  <Field label="主角核心" value={form.protagonist_core} onChange={(value) => handleChange('protagonist_core', value)} multiline />
                  <Field label="主线矛盾" value={form.main_conflict} onChange={(value) => handleChange('main_conflict', value)} multiline />
                  <Field label="长线悬念" value={form.longline_mystery} onChange={(value) => handleChange('longline_mystery', value)} multiline />
                  <Field label="目标篇幅" value={form.serial_length_target} onChange={(value) => handleChange('serial_length_target', value)} />
                  <Field label="揭秘策略" value={form.reveal_strategy} onChange={(value) => handleChange('reveal_strategy', value)} multiline />
                  <Field label="节奏策略" value={form.pacing_strategy} onChange={(value) => handleChange('pacing_strategy', value)} multiline />
                  <Field
                    label="必保留设定"
                    hint="每行一条"
                    value={form.must_keep_rules}
                    onChange={(value) => handleChange('must_keep_rules', value)}
                    multiline
                    rows={5}
                  />
                </div>
              </div>

              <div className="min-h-0 overflow-y-auto px-6 py-5">
                <div className="mb-4 text-sm font-semibold text-slate-900">写作指导</div>
                <div className="space-y-3">
                  <Field label="开书策略" value={form.opening_strategy} onChange={(value) => handleChange('opening_strategy', value)} multiline />
                  <Field
                    label="章节密度策略"
                    value={form.chapter_density_strategy}
                    onChange={(value) => handleChange('chapter_density_strategy', value)}
                    multiline
                  />
                  <Field label="中段驱动力" value={form.midgame_engine} onChange={(value) => handleChange('midgame_engine', value)} multiline />
                  <Field label="后期方向" value={form.late_game_direction} onChange={(value) => handleChange('late_game_direction', value)} multiline />
                  <Field
                    label="避免的模式"
                    hint="每行一条"
                    value={form.forbidden_patterns}
                    onChange={(value) => handleChange('forbidden_patterns', value)}
                    multiline
                    rows={6}
                  />
                  <Field
                    label="推荐情节模式"
                    hint="每行一条"
                    value={form.preferred_plot_patterns}
                    onChange={(value) => handleChange('preferred_plot_patterns', value)}
                    multiline
                    rows={6}
                  />
                </div>
              </div>
            </div>

            <div className="border-t border-[#e5edf8] px-6 py-4">
              {error ? <div className="mb-3 text-xs text-rose-600">{error}</div> : null}
              <div className="flex flex-wrap items-center justify-end gap-3">
                <button
                  onClick={() => setEditOpen(false)}
                  disabled={saving}
                  className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  取消
                </button>
                <button
                  onClick={() => void handleSave()}
                  disabled={saving}
                  className="inline-flex items-center gap-1.5 rounded-2xl bg-[#2563eb] px-5 py-2.5 text-sm font-medium text-white shadow-[0_10px_24px_rgba(37,99,235,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {saving ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      保存中...
                    </>
                  ) : (
                    <>
                      <Save size={14} />
                      保存调整
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="rounded-xl border border-[#d7e3f4] bg-white/90 p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">{label}</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{value}</div>
    </div>
  );
}

function ListItem({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: 'blue' | 'red' | 'green';
}) {
  if (items.length === 0) return null;
  const toneClass =
    tone === 'red' ? 'text-red-500' : tone === 'green' ? 'text-emerald-600' : 'text-[#2563eb]';
  return (
    <div className="rounded-xl border border-[#d7e3f4] bg-white/90 p-3">
      <div className={`text-[11px] font-medium ${toneClass}`}>{label}</div>
      <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs leading-5 text-slate-600">
        {items.map((item, idx) => (
          <li key={idx}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  multiline = false,
  rows = 3,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  rows?: number;
  hint?: string;
}) {
  const className =
    'w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]';

  return (
    <label className="block">
      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs font-medium text-[#2563eb]">
        <span>{label}</span>
        {hint ? <span className="font-normal text-slate-400">{hint}</span> : null}
      </div>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={rows}
          className={`${className} resize-y leading-6`}
        />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} className={className} />
      )}
    </label>
  );
}

function createFormState(storyBible: StoryBible): StoryBibleFormState {
  const brief = storyBible.creative_brief;
  const guidance = storyBible.writing_guidance;

  return {
    project_positioning: brief?.project_positioning ?? '',
    genre: brief?.genre ?? '',
    audience: brief?.audience ?? '',
    tone: brief?.tone ?? '',
    core_hook: brief?.core_hook ?? '',
    one_line_premise: brief?.one_line_premise ?? '',
    protagonist_core: brief?.protagonist_core ?? '',
    main_conflict: brief?.main_conflict ?? '',
    longline_mystery: brief?.longline_mystery ?? '',
    serial_length_target: brief?.serial_length_target ?? '',
    must_keep_rules: (brief?.must_keep_rules ?? []).join('\n'),
    reveal_strategy: brief?.reveal_strategy ?? '',
    pacing_strategy: brief?.pacing_strategy ?? '',
    opening_strategy: guidance?.opening_strategy ?? '',
    chapter_density_strategy: guidance?.chapter_density_strategy ?? '',
    midgame_engine: guidance?.midgame_engine ?? '',
    late_game_direction: guidance?.late_game_direction ?? '',
    forbidden_patterns: (guidance?.forbidden_patterns ?? []).join('\n'),
    preferred_plot_patterns: (guidance?.preferred_plot_patterns ?? []).join('\n'),
  };
}

function buildStoryBiblePayload(form: StoryBibleFormState, storyBible: StoryBible): Partial<StoryBible> {
  return {
    ...storyBible,
    creative_brief: {
      project_positioning: form.project_positioning.trim(),
      genre: form.genre.trim(),
      audience: form.audience.trim(),
      tone: form.tone.trim(),
      core_hook: form.core_hook.trim(),
      one_line_premise: form.one_line_premise.trim(),
      protagonist_core: form.protagonist_core.trim(),
      main_conflict: form.main_conflict.trim(),
      longline_mystery: form.longline_mystery.trim(),
      serial_length_target: form.serial_length_target.trim(),
      must_keep_rules: toLineList(form.must_keep_rules),
      reveal_strategy: form.reveal_strategy.trim(),
      pacing_strategy: form.pacing_strategy.trim(),
    },
    writing_guidance: {
      opening_strategy: form.opening_strategy.trim(),
      chapter_density_strategy: form.chapter_density_strategy.trim(),
      midgame_engine: form.midgame_engine.trim(),
      late_game_direction: form.late_game_direction.trim(),
      forbidden_patterns: toLineList(form.forbidden_patterns),
      preferred_plot_patterns: toLineList(form.preferred_plot_patterns),
    },
  };
}

function toLineList(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}
