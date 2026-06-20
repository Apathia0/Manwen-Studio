import { BookOpen, ChevronDown, ChevronUp, Loader2, Pencil, Save, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { updateStoryBible, type StoryBible } from '../api';
import { toast } from '../lib/toast';

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
  world_setting: string;
  open_story_notes: string;
};

export default function StoryBibleSummaryCard({ storyId, storyBible, onUpdated }: Props) {
  const [workbenchOpen, setWorkbenchOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const formInitialState = useMemo(() => createFormState(storyBible), [storyBible]);
  const [form, setForm] = useState<StoryBibleFormState>(formInitialState);

  useEffect(() => {
    setForm(formInitialState);
  }, [formInitialState]);

  const brief = storyBible.creative_brief;

  if (!storyBible || Object.keys(storyBible).length === 0) return null;

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
      toast.success('保存成功');
    } catch (err: any) {
      setError(err?.message || '更新作品圣经失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-[linear-gradient(135deg,_#f8fbff_0%,_#eff6ff_100%)] p-4 shadow-[0_8px_20px_rgba(59,130,246,0.06)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <BookOpen size={16} className="shrink-0 text-[#2563eb]" />
          <span className="text-sm font-semibold text-slate-900">作品圣经摘要</span>
          {brief?.one_line_premise ? (
            <span className="hidden max-w-[420px] truncate text-sm text-slate-500 md:inline-block">
              {brief?.one_line_premise}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-slate-400">
            {brief?.genre} / {brief?.audience} / {brief?.serial_length_target}
          </span>
          <button
            onClick={() => setWorkbenchOpen(true)}
            className="inline-flex shrink-0 items-center gap-1 rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-[#f8fbff]"
          >
            <BookOpen size={13} />
            完整圣经
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
      </div>

      {workbenchOpen ? (
        <StoryBibleWorkbench storyBible={storyBible} onClose={() => setWorkbenchOpen(false)} />
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
                  <Field
                    label="世界观设定"
                    hint="JSON 格式"
                    value={form.world_setting}
                    onChange={(value) => handleChange('world_setting', value)}
                    multiline
                    rows={6}
                  />
                  <Field
                    label="开放故事笔记"
                    value={form.open_story_notes}
                    onChange={(value) => handleChange('open_story_notes', value)}
                    multiline
                    rows={4}
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

const LABEL_MAP: Record<string, string> = {
  // 世界观设定
  power_system: '力量体系',
  society_structure: '社会结构',
  key_locations: '关键地点',
  world_history: '世界历史',
  hidden_truths: '隐藏真相',
  world_rules: '世界规则',
  magic_system: '魔法体系',
  technology_level: '科技水平',
  geography: '地理环境',
  culture: '文化背景',
  religion: '宗教信仰',
  economy: '经济体系',
  politics: '政治格局',
  factions: '势力分布',
  races: '种族设定',
  timeline: '时间线',
  power_levels: '等级划分',
  hierarchy: '等级制度',
  organizations: '组织势力',
  conflicts: '核心冲突',
  natural_laws: '自然法则',
  cosmology: '宇宙观',
  // 完整圣经 sections
  story_state: '故事状态',
  raw_idea: '原始创意',
  raw_length_goal: '篇幅目标',
  raw_must_keep: '必保留要素',
  raw_notes: '原始笔记',
  continuity_facts: '连续性事实',
  open_loops: '未闭合线索',
  recent_chapter_summaries: '近期章节摘要',
  chapter_number: '章节号',
  chapters_analysis: '章节分析',
};

function translateLabel(key: string): string {
  return LABEL_MAP[key] ?? key.replace(/_/g, ' ');
}

function CollapsibleSection({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-xl border border-[#e5edf8] bg-white/80">
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm font-medium text-slate-700 transition hover:bg-[#f8faff]"
      >
        <span>{title}</span>
        {open ? (
          <ChevronUp size={13} className="shrink-0 text-slate-400" />
        ) : (
          <ChevronDown size={13} className="shrink-0 text-slate-400" />
        )}
      </button>
      {open ? (
        <div className="border-t border-[#eef3f9] px-4 pb-3 pt-2">{children}</div>
      ) : null}
    </div>
  );
}

function StoryBibleWorkbench({
  storyBible,
  onClose,
}: {
  storyBible: StoryBible;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState('all');
  const [expandVersion, setExpandVersion] = useState(0);
  const [defaultOpen, setDefaultOpen] = useState(true);

  const brief = storyBible.creative_brief;
  const guidance = storyBible.writing_guidance;
  const rawInput = storyBible.raw_input;
  const storyState = storyBible.story_state;
  const worldSetting =
    typeof brief?.world_setting === 'object' ? brief.world_setting : null;

  const handleExpandAll = () => {
    setDefaultOpen(true);
    setExpandVersion((v) => v + 1);
  };
  const handleCollapseAll = () => {
    setDefaultOpen(false);
    setExpandVersion((v) => v + 1);
  };

  const tabs = [
    { key: 'all', label: '全部' },
    ...(rawInput ? [{ key: 'raw_input', label: '原始输入' }] : []),
    ...(brief ? [{ key: 'creative_brief', label: '创意摘要' }] : []),
    ...(guidance ? [{ key: 'writing_guidance', label: '写作指导' }] : []),
    ...(worldSetting ? [{ key: 'world_setting', label: '世界观' }] : []),
    ...(storyState ? [{ key: 'story_state', label: '故事状态' }] : []),
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
      <div className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-[28px] border border-[#d7e3f4] bg-white shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div className="text-base font-semibold text-slate-900">作品圣经</div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCollapseAll}
              className="rounded-lg border border-[#d7e3f4] bg-white px-2.5 py-1 text-xs font-medium text-slate-500 transition hover:bg-[#f8fbff]"
            >
              <ChevronUp size={12} className="mr-0.5 inline" />
              全部收起
            </button>
            <button
              onClick={handleExpandAll}
              className="rounded-lg border border-[#d7e3f4] bg-white px-2.5 py-1 text-xs font-medium text-slate-500 transition hover:bg-[#f8fbff]"
            >
              <ChevronDown size={12} className="mr-0.5 inline" />
              全部展开
            </button>
            <button
              onClick={onClose}
              className="rounded-full border border-[#d7e3f4] bg-white p-1.5 text-slate-400 transition hover:bg-[#f8fbff]"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Tab 栏 */}
        <div className="flex gap-1 border-b border-[#e5edf8] px-6 pt-3">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-t-lg px-4 py-2 text-xs font-medium transition ${
                activeTab === tab.key
                  ? 'bg-[#eff6ff] text-[#2563eb]'
                  : 'text-slate-500 hover:bg-[#f8fbff] hover:text-slate-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 内容区 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <div key={expandVersion} className="space-y-3">
            {renderTabContent(storyBible, activeTab, defaultOpen)}
          </div>
        </div>
      </div>
    </div>
  );
}

function renderTabContent(
  storyBible: StoryBible,
  tab: string,
  defaultOpen: boolean,
): React.ReactNode {
  const brief = storyBible.creative_brief;
  const guidance = storyBible.writing_guidance;
  const rawInput = storyBible.raw_input;
  const storyState = storyBible.story_state;
  const worldSetting =
    typeof brief?.world_setting === 'object' ? brief.world_setting : null;

  const renderObjectEntries = (data: any) =>
    data ? renderEntries(Object.entries(data), defaultOpen) : null;

  if (tab === 'all') {
    return (
      <>
        {rawInput ? (
          <CollapsibleSection title="原始输入" defaultOpen={defaultOpen}>
            {renderObjectEntries(rawInput)}
          </CollapsibleSection>
        ) : null}
        {brief ? (
          <CollapsibleSection title="创意摘要" defaultOpen={defaultOpen}>
            {renderEntries(
              Object.entries(brief).filter(([k]) => k !== 'world_setting'),
              defaultOpen,
            )}
          </CollapsibleSection>
        ) : null}
        {guidance ? (
          <CollapsibleSection title="写作指导" defaultOpen={defaultOpen}>
            {renderObjectEntries(guidance)}
          </CollapsibleSection>
        ) : null}
        {worldSetting ? (
          <CollapsibleSection title="世界观设定" defaultOpen={defaultOpen}>
            {renderObjectEntries(worldSetting)}
          </CollapsibleSection>
        ) : null}
        {storyBible.import_guidance ? (
          <CollapsibleSection title="导入指导" defaultOpen={defaultOpen}>
            {renderObjectEntries(storyBible.import_guidance)}
          </CollapsibleSection>
        ) : null}
        {storyState ? (
          <CollapsibleSection title="故事状态" defaultOpen={defaultOpen}>
            {renderObjectEntries(storyState)}
          </CollapsibleSection>
        ) : null}
      </>
    );
  }

  if (tab === 'raw_input') return renderObjectEntries(rawInput);
  if (tab === 'creative_brief')
    return brief
      ? renderEntries(
          Object.entries(brief).filter(([k]) => k !== 'world_setting'),
          defaultOpen,
        )
      : null;
  if (tab === 'writing_guidance') return renderObjectEntries(guidance);
  if (tab === 'world_setting') return renderObjectEntries(worldSetting);
  if (tab === 'story_state') return renderObjectEntries(storyState);
  return null;
}

function renderEntries(
  entries: [string, unknown][],
  defaultOpen: boolean,
): React.ReactNode {
  return entries
    .filter(([, value]) => hasRenderableValue(value))
    .map(([key, value]) => (
      <CollapsibleSection key={key} title={translateLabel(key)} defaultOpen={defaultOpen}>
        {renderEntryContent(value, defaultOpen)}
      </CollapsibleSection>
    ));
}

function renderEntryContent(
  value: unknown,
  defaultOpen: boolean,
): React.ReactNode {
  if (value == null) return null;
  if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return null;
    return (
      <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
        {text}
      </div>
    );
  }
  if (Array.isArray(value)) {
    const items = value.filter((v) => v != null);
    if (!items.length) return null;

    if (items.every((v) => typeof v !== 'object')) {
      return (
        <ul className="list-inside list-disc space-y-1 text-sm leading-6 text-slate-700">
          {items.map((item, i) => (
            <li key={i}>{String(item)}</li>
          ))}
        </ul>
      );
    }
    return (
      <div className="space-y-2">
        {items.map((item, i) => {
          if (typeof item !== 'object' || item == null) {
            return (
              <div key={i} className="text-sm leading-6 text-slate-700">
                {String(item)}
              </div>
            );
          }
          return (
            <CollapsibleSection key={i} title={`#${i + 1}`} defaultOpen={defaultOpen}>
              {renderEntryContent(item, defaultOpen)}
            </CollapsibleSection>
          );
        })}
      </div>
    );
  }
  if (typeof value === 'object' && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([, v]) => v != null && String(v).trim(),
    );
    if (!entries.length) return null;
    return renderEntries(entries, defaultOpen);
  }
  return <div className="text-sm text-slate-700">{String(value)}</div>;
}



function hasRenderableValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.some(hasRenderableValue);
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).some(hasRenderableValue);
  return true;
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
    world_setting: formatWorldSettingForForm(brief?.world_setting),
    open_story_notes: brief?.open_story_notes ?? '',
  };
}

function formatWorldSettingForForm(ws: any): string {
  if (ws == null) return '';
  if (typeof ws === 'object') return JSON.stringify(ws, null, 2);
  return String(ws);
}

function buildStoryBiblePayload(form: StoryBibleFormState, storyBible: StoryBible): Partial<StoryBible> {
  return {
    ...storyBible,
    creative_brief: {
      ...(storyBible.creative_brief ?? {}),
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
      world_setting: parseWorldSetting(form.world_setting),
      open_story_notes: form.open_story_notes.trim(),
    },
    writing_guidance: {
      ...(storyBible.writing_guidance ?? {}),
      opening_strategy: form.opening_strategy.trim(),
      chapter_density_strategy: form.chapter_density_strategy.trim(),
      midgame_engine: form.midgame_engine.trim(),
      late_game_direction: form.late_game_direction.trim(),
      forbidden_patterns: toLineList(form.forbidden_patterns),
      preferred_plot_patterns: toLineList(form.preferred_plot_patterns),
    },
  };
}

function parseWorldSetting(value: string): any {
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

function toLineList(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}
