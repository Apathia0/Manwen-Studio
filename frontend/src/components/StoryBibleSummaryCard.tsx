import { BookOpen, ChevronDown, ChevronUp, Loader2, Pencil, Plus, Save, Trash2, X } from 'lucide-react';
import { useState } from 'react';
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
  raw_idea: string;
  raw_length_goal: string;
  raw_must_keep: string;
  raw_notes: string;
  raw_hidden_setting: string;
  import_material_type: string;
  must_keep: string;
  author_goal: string;
  adjustment_scope: string;
  longline_plan: string;
  tone_guardrails: string;
  story_state_text: string;
  continuity_facts: string;
  open_loops: string;
};

export default function StoryBibleSummaryCard({ storyId, storyBible, onUpdated }: Props) {
  const [workbenchOpen, setWorkbenchOpen] = useState(false);
  const brief = storyBible.creative_brief;

  if (!storyBible || Object.keys(storyBible).length === 0) return null;

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
        </div>
      </div>

      {workbenchOpen ? (
        <StoryBibleWorkbench
          storyId={storyId}
          storyBible={storyBible}
          onUpdated={onUpdated}
          onClose={() => setWorkbenchOpen(false)}
        />
      ) : null}
    </div>
  );
}

const LABEL_MAP: Record<string, string> = {
  // 创意摘要 (creative_brief)
  project_positioning: '作品定位',
  genre: '题材',
  audience: '受众',
  tone: '风格基调',
  core_hook: '核心卖点',
  one_line_premise: '一句话梗概',
  protagonist_core: '主角核心',
  main_conflict: '主线矛盾',
  longline_mystery: '长线悬念',
  serial_length_target: '目标篇幅',
  must_keep_rules: '必保留设定',
  reveal_strategy: '揭秘策略',
  pacing_strategy: '节奏策略',
  open_story_notes: '开放故事笔记',
  target_chapter_count: '目标章节数',
  'target chapter count': '目标章节数',
  character_relationship_map: '角色关系图',
  'character relationship map': '角色关系图',
  hook: '核心卖点',
  premise: '一句话梗概',
  protagonist: '主角核心',
  conflict: '主线冲突',
  longline: '长线悬念',
  pacing: '节奏策略',
  reveal: '揭秘策略',
  positioning: '作品定位',
  strategy: '策略',
  target: '目标',
  rules: '必须保留',
  notes: '开放笔记',

  // 写作指导 (writing_guidance)
  opening_strategy: '开书策略',
  chapter_density_strategy: '章节密度策略',
  midgame_engine: '中段驱动力',
  late_game_direction: '后期方向',
  forbidden_patterns: '避免的模式',
  preferred_plot_patterns: '推荐情节模式',
  forbidden: '禁止模式',
  preferred: '推荐模式',
  opening: '开篇策略',
  density: '章节密度',
  midgame: '中段驱动力',
  late_game: '后期方向',

  // 原始输入 (raw_input)
  raw_idea: '原始创意',
  raw_length_goal: '篇幅目标',
  raw_must_keep: '必保留要素',
  raw_notes: '原始笔记',
  raw_hidden_setting: '隐藏设定',
  idea: '原始创意',
  length_goal: '篇幅目标',
  hidden_setting: '隐藏设定',

  // 导入指导 (import_guidance)
  import_material_type: '导入素材类型',
  must_keep: '必须保留',
  author_goal: '作者目标',
  adjustment_scope: '调整范围',
  longline_plan: '长线预案',
  tone_guardrails: '风格护栏',
  material_type: '素材类型',
  material: '素材',
  goal: '目标',
  scope: '调整范围',
  plan: '长线计划',
  guardrails: '风格护栏',

  // 故事状态 (story_state)
  story_state: '故事状态',
  continuity_facts: '连续性事实',
  open_loops: '未闭合线索',
  resolved_loops: '已解决线索',
  recent_chapter_summaries: '近期章节摘要',
  chapter_number: '章节号',
  title: '标题',
  summary: '摘要',
  ending_scene: '结尾场景',
  handoff: '交接信息',
  chapters_analysis: '章节分析',
  current_arc_focus: '当前剧情焦点',
  current_tone: '当前基调',
  next_payoff_target: '下一伏笔目标',
  continuity: '连续性事实',
  loops: '线索',
  facts: '事实',
  recent: '近期摘要',
  summaries: '章节摘要',
  analysis: '章节分析',
  arc_focus: '当前剧情焦点',
  arc: '剧情弧',
  payoff: '伏笔',
  payoff_target: '伏笔目标',

  // 世界观设定 (world_setting)
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
  // story_bible 顶层通用字段
  tags: '标签',
  characters: '角色',
  outline: '大纲',
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
  storyId,
  storyBible,
  onUpdated,
  onClose,
}: {
  storyId: number;
  storyBible: StoryBible;
  onUpdated?: () => void | Promise<void>;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState('all');
  const [expandVersion, setExpandVersion] = useState(0);
  const [defaultOpen, setDefaultOpen] = useState(true);
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [draftForm, setDraftForm] = useState<StoryBibleFormState>(() => createFormState(storyBible));

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

  const handleFieldChange = (key: keyof StoryBibleFormState, value: string) => {
    setDraftForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    try {
      await updateStoryBible(storyId, buildStoryBiblePayload(draftForm, storyBible));
      setEditMode(false);
      await onUpdated?.();
      toast.success('保存成功');
    } catch (err: any) {
      setSaveError(err?.message || '更新作品圣经失败');
    } finally {
      setSaving(false);
    }
  };

  const handleStartEdit = () => {
    setDraftForm(createFormState(storyBible));
    setEditMode(true);
    setSaveError('');
  };

  const handleCancelEdit = () => {
    setEditMode(false);
    setSaveError('');
  };

  const tabs = [
    { key: 'all', label: '全部' },
    ...(rawInput ? [{ key: 'raw_input', label: '原始输入' }] : []),
    ...(brief ? [{ key: 'creative_brief', label: '创意摘要' }] : []),
    ...(guidance ? [{ key: 'writing_guidance', label: '写作指导' }] : []),
    ...(worldSetting ? [{ key: 'world_setting', label: '世界观' }] : []),
    ...(storyBible.import_guidance ? [{ key: 'import_guidance', label: '导入指导' }] : []),
    ...(storyState ? [{ key: 'story_state', label: '故事状态' }] : []),
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
      <div className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-[28px] border border-[#d7e3f4] bg-white shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div className="text-base font-semibold text-slate-900">作品圣经</div>
          <div className="flex items-center gap-2">
            {editMode ? (
              <>
                {saveError ? <span className="text-xs text-rose-600">{saveError}</span> : null}
                <button
                  onClick={handleCancelEdit}
                  disabled={saving}
                  className="rounded-lg border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-[#f8fbff] disabled:opacity-60"
                >
                  取消
                </button>
                <button
                  onClick={() => void handleSave()}
                  disabled={saving}
                  className="inline-flex items-center gap-1 rounded-lg bg-[#2563eb] px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-[#1d4ed8] disabled:opacity-60"
                >
                  {saving ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Save size={13} />
                  )}
                  {saving ? '保存中...' : '保存'}
                </button>
              </>
            ) : (
              <>
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
                  onClick={handleStartEdit}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-[#f8fbff]"
                >
                  <Pencil size={12} />
                  编辑
                </button>
                <button
                  onClick={onClose}
                  className="rounded-full border border-[#d7e3f4] bg-white p-1.5 text-slate-400 transition hover:bg-[#f8fbff]"
                >
                  <X size={16} />
                </button>
              </>
            )}
          </div>
        </div>

        {editMode ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="grid min-h-full lg:grid-cols-2">
              <div className="border-b border-[#e5edf8] px-6 py-5 lg:border-b-0 lg:border-r">
                <div className="mb-4 text-sm font-semibold text-slate-900">创意摘要</div>
                <div className="space-y-3">
                  <Field label="作品定位" value={draftForm.project_positioning} onChange={(v) => handleFieldChange('project_positioning', v)} multiline />
                  <Field label="题材" value={draftForm.genre} onChange={(v) => handleFieldChange('genre', v)} />
                  <Field label="受众" value={draftForm.audience} onChange={(v) => handleFieldChange('audience', v)} />
                  <Field label="风格基调" value={draftForm.tone} onChange={(v) => handleFieldChange('tone', v)} multiline />
                  <Field label="核心卖点" value={draftForm.core_hook} onChange={(v) => handleFieldChange('core_hook', v)} multiline />
                  <Field label="一句话梗概" value={draftForm.one_line_premise} onChange={(v) => handleFieldChange('one_line_premise', v)} multiline />
                  <Field label="主角核心" value={draftForm.protagonist_core} onChange={(v) => handleFieldChange('protagonist_core', v)} multiline />
                  <Field label="主线矛盾" value={draftForm.main_conflict} onChange={(v) => handleFieldChange('main_conflict', v)} multiline />
                  <Field label="长线悬念" value={draftForm.longline_mystery} onChange={(v) => handleFieldChange('longline_mystery', v)} multiline />
                  <Field label="目标篇幅" value={draftForm.serial_length_target} onChange={(v) => handleFieldChange('serial_length_target', v)} />
                  <Field label="揭秘策略" value={draftForm.reveal_strategy} onChange={(v) => handleFieldChange('reveal_strategy', v)} multiline />
                  <Field label="节奏策略" value={draftForm.pacing_strategy} onChange={(v) => handleFieldChange('pacing_strategy', v)} multiline />
                  <Field label="必保留设定" hint="每行一条" value={draftForm.must_keep_rules} onChange={(v) => handleFieldChange('must_keep_rules', v)} multiline rows={5} />
                  <WorldSettingEditButton value={draftForm.world_setting} onChange={(v) => handleFieldChange('world_setting', v)} />
                  <Field label="开放故事笔记" value={draftForm.open_story_notes} onChange={(v) => handleFieldChange('open_story_notes', v)} multiline rows={4} />
                </div>
              </div>
              <div className="border-b border-[#e5edf8] px-6 py-5 lg:border-b-0">
                <div className="mb-4 text-sm font-semibold text-slate-900">写作指导</div>
                <div className="space-y-3">
                  <Field label="开书策略" value={draftForm.opening_strategy} onChange={(v) => handleFieldChange('opening_strategy', v)} multiline />
                  <Field label="章节密度策略" value={draftForm.chapter_density_strategy} onChange={(v) => handleFieldChange('chapter_density_strategy', v)} multiline />
                  <Field label="中段驱动力" value={draftForm.midgame_engine} onChange={(v) => handleFieldChange('midgame_engine', v)} multiline />
                  <Field label="后期方向" value={draftForm.late_game_direction} onChange={(v) => handleFieldChange('late_game_direction', v)} multiline />
                  <Field label="避免的模式" hint="每行一条" value={draftForm.forbidden_patterns} onChange={(v) => handleFieldChange('forbidden_patterns', v)} multiline rows={6} />
                  <Field label="推荐情节模式" hint="每行一条" value={draftForm.preferred_plot_patterns} onChange={(v) => handleFieldChange('preferred_plot_patterns', v)} multiline rows={6} />
                </div>
              </div>
            </div>
            <div className="border-t border-[#e5edf8] px-6 py-5">
              <div className="mb-4 text-sm font-semibold text-slate-900">原始输入</div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="原始创意" value={draftForm.raw_idea} onChange={(v) => handleFieldChange('raw_idea', v)} multiline />
                <Field label="篇幅目标" value={draftForm.raw_length_goal} onChange={(v) => handleFieldChange('raw_length_goal', v)} />
                <Field label="必保留要素" value={draftForm.raw_must_keep} onChange={(v) => handleFieldChange('raw_must_keep', v)} multiline />
                <Field label="原始笔记" value={draftForm.raw_notes} onChange={(v) => handleFieldChange('raw_notes', v)} multiline />
                <Field label="隐藏设定" value={draftForm.raw_hidden_setting} onChange={(v) => handleFieldChange('raw_hidden_setting', v)} multiline />
              </div>
            </div>
            <div className="border-t border-[#e5edf8] px-6 py-5">
              <div className="mb-4 text-sm font-semibold text-slate-900">导入指导</div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="导入素材类型" value={draftForm.import_material_type} onChange={(v) => handleFieldChange('import_material_type', v)} />
                <Field label="必须保留" value={draftForm.must_keep} onChange={(v) => handleFieldChange('must_keep', v)} multiline />
                <Field label="作者目标" value={draftForm.author_goal} onChange={(v) => handleFieldChange('author_goal', v)} multiline />
                <Field label="调整范围" value={draftForm.adjustment_scope} onChange={(v) => handleFieldChange('adjustment_scope', v)} multiline />
                <Field label="长线预案" value={draftForm.longline_plan} onChange={(v) => handleFieldChange('longline_plan', v)} multiline />
                <Field label="风格护栏" value={draftForm.tone_guardrails} onChange={(v) => handleFieldChange('tone_guardrails', v)} multiline />
              </div>
            </div>
            <div className="border-t border-[#e5edf8] px-6 py-5">
              <div className="mb-4 text-sm font-semibold text-slate-900">故事状态</div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="故事状态" value={draftForm.story_state_text} onChange={(v) => handleFieldChange('story_state_text', v)} multiline />
                <Field label="连续性事实" hint="每行一条" value={draftForm.continuity_facts} onChange={(v) => handleFieldChange('continuity_facts', v)} multiline rows={5} />
                <Field label="未闭合线索" hint="每行一条" value={draftForm.open_loops} onChange={(v) => handleFieldChange('open_loops', v)} multiline rows={5} />
              </div>
            </div>
          </div>
        ) : (
          <>
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
          </>
        )}
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
  if (tab === 'import_guidance') return renderObjectEntries(storyBible.import_guidance);
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

const WORLD_DIMENSIONS: { key: string; label: string }[] = [
  { key: 'power_system', label: '力量体系' },
  { key: 'society_structure', label: '社会结构' },
  { key: 'key_locations', label: '关键地点' },
  { key: 'world_history', label: '世界历史' },
  { key: 'hidden_truths', label: '隐藏真相' },
];

function WorldSettingEditor({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (value: string) => void;
  onClose: () => void;
}) {
  const parseEntryMap = (): Record<string, string> => {
    try {
      const obj = JSON.parse(value || '{}');
      if (obj && typeof obj === 'object') return obj as Record<string, string>;
    } catch {}
    return {};
  };

  const [entries, setEntries] = useState<Record<string, string>>(parseEntryMap);
  const [newKey, setNewKey] = useState('');
  const dimKeys = new Set(WORLD_DIMENSIONS.map((d) => d.key));
  const customKeys = Object.keys(entries).filter((k) => !dimKeys.has(k));

  const setEntry = (key: string, val: string) => {
    setEntries((prev) => ({ ...prev, [key]: val }));
  };

  const addKey = () => {
    const trimmed = newKey.trim();
    if (!trimmed || entries[trimmed] !== undefined) return;
    setEntries((prev) => ({ ...prev, [trimmed]: '' }));
    setNewKey('');
  };

  const removeKey = (key: string) => {
    const next = { ...entries };
    delete next[key];
    setEntries(next);
  };

  const handleSave = () => {
    const cleaned: Record<string, string> = {};
    for (const [k, v] of Object.entries(entries)) {
      if (v.trim()) cleaned[k] = v.trim();
    }
    onChange(Object.keys(cleaned).length > 0 ? JSON.stringify(cleaned, null, 2) : '');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-white shadow-[0_20px_50px_rgba(15,23,42,0.2)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 弹窗头部 */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div className="text-sm font-semibold text-slate-900">编辑世界观设定</div>
          <button onClick={onClose} className="rounded-full p-1.5 text-slate-400 hover:bg-[#f8fbff] hover:text-slate-600 transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* 可滚动内容区 */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="space-y-5">
            {/* 标准维度 */}
            {WORLD_DIMENSIONS.map((dim) => (
              <label key={dim.key} className="block">
                <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-[#2563eb]">
                  <span>{dim.label}</span>
                  <span className="text-[10px] font-normal text-slate-400">({dim.key})</span>
                </div>
                <textarea
                  value={entries[dim.key] ?? ''}
                  onChange={(e) => setEntry(dim.key, e.target.value)}
                  rows={3}
                  className="w-full resize-y rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe] leading-6"
                  placeholder={`输入${dim.label}描述...`}
                />
              </label>
            ))}

            {/* 自定义字段 */}
            {customKeys.length > 0 && (
              <div className="border-t border-[#e5edf8] pt-5">
                <div className="mb-4 text-xs font-semibold text-slate-500">自定义字段</div>
                <div className="space-y-4">
                  {customKeys.map((key) => (
                    <div key={key} className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <label className="block">
                          <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-[#2563eb]">
                            <span>{key}</span>
                          </div>
                          <textarea
                            value={entries[key] ?? ''}
                            onChange={(e) => setEntry(key, e.target.value)}
                            rows={2}
                            className="w-full resize-y rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe] leading-6"
                          />
                        </label>
                      </div>
                      <button
                        onClick={() => removeKey(key)}
                        className="mt-7 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-300 transition hover:bg-red-50 hover:text-red-500"
                        title="删除此字段"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 添加自定义字段 */}
            <div className="border-t border-[#e5edf8] pt-5">
              <div className="mb-3 text-xs font-medium text-slate-500">添加自定义字段</div>
              <div className="flex items-center gap-2">
                <input
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addKey())}
                  placeholder="输入字段名（支持中文）"
                  className="flex-1 rounded-xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
                />
                <button
                  onClick={addKey}
                  disabled={!newKey.trim()}
                  className="inline-flex shrink-0 items-center gap-1 rounded-xl bg-[#2563eb] px-3 py-2 text-xs font-medium text-white transition hover:bg-[#1d4ed8] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus size={14} />
                  添加
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="flex shrink-0 items-center justify-end gap-3 border-t border-[#e5edf8] px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-xl border border-[#d7e3f4] bg-white px-5 py-2 text-xs font-medium text-slate-600 transition hover:bg-[#f8fbff]"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[#2563eb] px-5 py-2 text-xs font-medium text-white shadow-sm transition hover:bg-[#1d4ed8]"
          >
            <Save size={13} />
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

function WorldSettingEditButton({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);

  const count = (() => {
    try {
      const obj = JSON.parse(value || '{}');
      if (obj && typeof obj === 'object') return Object.keys(obj).length;
    } catch {}
    return 0;
  })();

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs font-medium text-[#2563eb]">
        <span>世界观设定</span>
      </div>
      <button
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-600 transition hover:border-[#93c5fd] hover:bg-white"
      >
        {count > 0 ? (
          <>
            <span className="flex-1 text-left text-slate-800">已编辑（{count} 个字段）</span>
            <Pencil size={13} className="shrink-0 text-[#2563eb]" />
          </>
        ) : (
          <span className="flex-1 text-left text-slate-400">点击添加世界观设定（力量体系、社会结构、关键地点等）</span>
        )}
      </button>
      {open ? <WorldSettingEditor value={value} onChange={onChange} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}

function createFormState(storyBible: StoryBible): StoryBibleFormState {
  const brief = storyBible.creative_brief;
  const guidance = storyBible.writing_guidance;
  const raw = storyBible.raw_input;
  const imp = storyBible.import_guidance;
  const state = storyBible.story_state;

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
    raw_idea: raw?.raw_idea ?? '',
    raw_length_goal: raw?.raw_length_goal ?? '',
    raw_must_keep: raw?.raw_must_keep ?? '',
    raw_notes: raw?.raw_notes ?? '',
    raw_hidden_setting: raw?.raw_hidden_setting ?? '',
    import_material_type: imp?.import_material_type ?? '',
    must_keep: imp?.must_keep ?? '',
    author_goal: imp?.author_goal ?? '',
    adjustment_scope: imp?.adjustment_scope ?? '',
    longline_plan: imp?.longline_plan ?? '',
    tone_guardrails: imp?.tone_guardrails ?? '',
    story_state_text: state?.story_state ?? '',
    continuity_facts: (state?.continuity_facts ?? []).join('\n'),
    open_loops: (state?.open_loops ?? []).join('\n'),
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
    raw_input: {
      ...(storyBible.raw_input ?? {}),
      raw_idea: form.raw_idea.trim(),
      raw_length_goal: form.raw_length_goal.trim(),
      raw_must_keep: form.raw_must_keep.trim(),
      raw_notes: form.raw_notes.trim(),
      raw_hidden_setting: form.raw_hidden_setting.trim(),
    },
    import_guidance: {
      ...(storyBible.import_guidance ?? {}),
      import_material_type: form.import_material_type.trim(),
      must_keep: form.must_keep.trim(),
      author_goal: form.author_goal.trim(),
      adjustment_scope: form.adjustment_scope.trim(),
      longline_plan: form.longline_plan.trim(),
      tone_guardrails: form.tone_guardrails.trim(),
    },
    story_state: {
      ...(storyBible.story_state ?? {}),
      story_state: form.story_state_text.trim(),
      continuity_facts: toLineList(form.continuity_facts),
      open_loops: toLineList(form.open_loops),
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
