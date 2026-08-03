import type { StoryBible } from '../api';

export type BibleFormState = {
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
  open_story_notes: string;
  opening_strategy: string;
  chapter_density_strategy: string;
  midgame_engine: string;
  late_game_direction: string;
  forbidden_patterns: string;
  preferred_plot_patterns: string;
  raw_idea: string;
  raw_length_goal: string;
  raw_must_keep: string;
  raw_notes: string;
  raw_hidden_setting: string;
  import_material_type: string;
  import_must_keep: string;
  author_goal: string;
  adjustment_scope: string;
  longline_plan: string;
  tone_guardrails: string;
  story_state_text: string;
  continuity_facts: string;
  open_loops: string;
};

export type WorldSettingRow = { id: string; key: string; value: string; originalValue?: unknown };

const SECTION_LABELS: Record<string, string> = {
  raw_input: '原始输入', creative_brief: '创意摘要', writing_guidance: '写作指导', world_setting: '世界观设定',
  import_guidance: '导入指导', story_state: '故事状态', reference_author_profile: '参考作者画像',
  reference_author_report: '参考作者分析报告', reference_style_samples: '参考风格样本', learned_techniques: '已学习写作技法',
  reference_plots: '参考剧情结构', reference_rhythm: '参考节奏模型', reference_emotion_modules: '参考情绪模块',
};

const FIELD_LABELS: Record<string, string> = {
  project_positioning: '作品定位', genre: '题材', audience: '受众', tone: '风格基调', core_hook: '核心卖点',
  one_line_premise: '一句话梗概', protagonist_core: '主角核心', main_conflict: '主线矛盾', longline_mystery: '长线悬念',
  serial_length_target: '目标篇幅', must_keep_rules: '必保留设定', reveal_strategy: '揭秘策略', pacing_strategy: '节奏策略',
  world_setting: '世界观设定', open_story_notes: '开放故事笔记', opening_strategy: '开书策略',
  chapter_density_strategy: '章节密度策略', midgame_engine: '中段驱动力', late_game_direction: '后期方向',
  forbidden_patterns: '避免的模式', preferred_plot_patterns: '推荐情节模式', raw_idea: '原始创意', raw_length_goal: '篇幅目标',
  raw_must_keep: '必保留要素', raw_notes: '原始笔记', raw_hidden_setting: '隐藏设定', import_material_type: '导入素材类型',
  must_keep: '必须保留', author_goal: '作者目标', adjustment_scope: '调整范围', longline_plan: '长线预案',
  tone_guardrails: '风格护栏', continuity_facts: '连续性事实', open_loops: '未闭合线索', resolved_loops: '已解决线索',
  sampled_chapters: '分析章节', style_profile: '文风画像', rhythm_profile: '节奏画像', routine_cards: '写作套路卡',
  writing_guide: '写作指南', confidence: '分析可信度', source_policy: '来源处理', source_label: '来源标识',
};

const KNOWN_SECTIONS = new Set(['raw_input', 'creative_brief', 'writing_guidance', 'import_guidance', 'story_state']);

const REFERENCE_MATERIAL_KEYS = new Set([
  'reference_author_profile',
  'reference_author_report',
  'reference_report',
  'reference_style_samples',
  'learned_techniques',
  'reference_plots',
  'reference_rhythm',
  'reference_emotion_modules',
]);

export function isReferenceMaterialKey(key: string): boolean {
  return REFERENCE_MATERIAL_KEYS.has(key) || key.startsWith('deconstruction_');
}

export function collectBibleSections(storyBible: StoryBible): Array<{ key: string; title: string; value: unknown }> {
  const brief = asBibleRecord(storyBible.creative_brief);
  const world = readBibleField(brief, 'world_setting', '世界观设定');
  const briefWithoutWorld = Object.fromEntries(Object.entries(brief).filter(([key]) => key !== 'world_setting' && key !== '世界观设定'));
  const primarySections = [
    { key: 'raw_input', value: storyBible.raw_input }, { key: 'creative_brief', value: briefWithoutWorld },
    { key: 'writing_guidance', value: storyBible.writing_guidance }, { key: 'world_setting', value: world },
    { key: 'import_guidance', value: storyBible.import_guidance }, { key: 'story_state', value: storyBible.story_state },
  ];
  const extraSections = Object.entries(storyBible)
    .filter(([key, value]) => !KNOWN_SECTIONS.has(key) && !isReferenceMaterialKey(key) && hasBibleValue(value))
    .map(([key, value]) => ({ key, value }));
  return [...primarySections, ...extraSections]
    .filter((section) => hasBibleValue(section.value))
    .map((section) => ({ ...section, title: storyBibleSectionLabel(section.key) }));
}

export function createStoryBibleFormState(storyBible: StoryBible): BibleFormState {
  const brief = asBibleRecord(storyBible.creative_brief);
  const guidance = asBibleRecord(storyBible.writing_guidance);
  const raw = asBibleRecord(storyBible.raw_input);
  const imported = asBibleRecord(storyBible.import_guidance);
  const state = asBibleRecord(storyBible.story_state);
  return {
    project_positioning: stringify(readBibleField(brief, 'project_positioning', '作品定位')),
    genre: stringify(readBibleField(brief, 'genre', '题材')), audience: stringify(readBibleField(brief, 'audience', '受众')),
    tone: stringify(readBibleField(brief, 'tone', '风格基调')), core_hook: stringify(readBibleField(brief, 'core_hook', '核心卖点')),
    one_line_premise: stringify(readBibleField(brief, 'one_line_premise', '一句话梗概')),
    protagonist_core: stringify(readBibleField(brief, 'protagonist_core', '主角核心')),
    main_conflict: stringify(readBibleField(brief, 'main_conflict', '主线矛盾', '主线冲突')),
    longline_mystery: stringify(readBibleField(brief, 'longline_mystery', '长线悬念')),
    serial_length_target: stringify(readBibleField(brief, 'serial_length_target', '目标篇幅')),
    must_keep_rules: toLines(readBibleField(brief, 'must_keep_rules', '必保留设定')),
    reveal_strategy: stringify(readBibleField(brief, 'reveal_strategy', '揭秘策略')),
    pacing_strategy: stringify(readBibleField(brief, 'pacing_strategy', '节奏策略')),
    open_story_notes: stringify(readBibleField(brief, 'open_story_notes', '开放故事笔记')),
    opening_strategy: stringify(readBibleField(guidance, 'opening_strategy', '开书策略', '开篇策略')),
    chapter_density_strategy: stringify(readBibleField(guidance, 'chapter_density_strategy', '章节密度策略', '章节密度')),
    midgame_engine: stringify(readBibleField(guidance, 'midgame_engine', '中段驱动力', '中段驱动')),
    late_game_direction: stringify(readBibleField(guidance, 'late_game_direction', '后期方向')),
    forbidden_patterns: toLines(readBibleField(guidance, 'forbidden_patterns', '避免的模式', '避免模式')),
    preferred_plot_patterns: toLines(readBibleField(guidance, 'preferred_plot_patterns', '推荐情节模式')),
    raw_idea: stringify(readBibleField(raw, 'raw_idea', '原始创意')), raw_length_goal: stringify(readBibleField(raw, 'raw_length_goal', '篇幅目标')),
    raw_must_keep: stringify(readBibleField(raw, 'raw_must_keep', '必保留要素')), raw_notes: stringify(readBibleField(raw, 'raw_notes', '原始笔记')),
    raw_hidden_setting: stringify(readBibleField(raw, 'raw_hidden_setting', '隐藏设定')),
    import_material_type: stringify(readBibleField(imported, 'import_material_type', '导入素材类型')),
    import_must_keep: stringify(readBibleField(imported, 'must_keep', '必须保留')), author_goal: stringify(readBibleField(imported, 'author_goal', '作者目标')),
    adjustment_scope: stringify(readBibleField(imported, 'adjustment_scope', '调整范围')), longline_plan: stringify(readBibleField(imported, 'longline_plan', '长线预案')),
    tone_guardrails: stringify(readBibleField(imported, 'tone_guardrails', '风格护栏')),
    story_state_text: stringify(readBibleField(state, 'story_state', '故事状态')),
    continuity_facts: toLines(readBibleField(state, 'continuity_facts', '连续性事实')),
    open_loops: toLines(readBibleField(state, 'open_loops', '未闭合线索')),
  };
}

export function buildStoryBiblePayload(form: BibleFormState, storyBible: StoryBible, worldSetting: Record<string, unknown>): Partial<StoryBible> {
  const section = (value: unknown, fields: Array<[string[], unknown]>) => mergeFields(asBibleRecord(value), fields);
  return {
    creative_brief: section(storyBible.creative_brief, [
      [['project_positioning', '作品定位'], form.project_positioning.trim()], [['genre', '题材'], form.genre.trim()],
      [['audience', '受众'], form.audience.trim()], [['tone', '风格基调'], form.tone.trim()], [['core_hook', '核心卖点'], form.core_hook.trim()],
      [['one_line_premise', '一句话梗概'], form.one_line_premise.trim()], [['protagonist_core', '主角核心'], form.protagonist_core.trim()],
      [['main_conflict', '主线矛盾', '主线冲突'], form.main_conflict.trim()], [['longline_mystery', '长线悬念'], form.longline_mystery.trim()],
      [['serial_length_target', '目标篇幅'], form.serial_length_target.trim()], [['must_keep_rules', '必保留设定'], lineList(form.must_keep_rules)],
      [['reveal_strategy', '揭秘策略'], form.reveal_strategy.trim()], [['pacing_strategy', '节奏策略'], form.pacing_strategy.trim()],
      [['open_story_notes', '开放故事笔记'], form.open_story_notes.trim()], [['world_setting', '世界观设定'], worldSetting],
    ]) as StoryBible['creative_brief'],
    writing_guidance: section(storyBible.writing_guidance, [
      [['opening_strategy', '开书策略', '开篇策略'], form.opening_strategy.trim()],
      [['chapter_density_strategy', '章节密度策略', '章节密度'], form.chapter_density_strategy.trim()],
      [['midgame_engine', '中段驱动力', '中段驱动'], form.midgame_engine.trim()], [['late_game_direction', '后期方向'], form.late_game_direction.trim()],
      [['forbidden_patterns', '避免的模式', '避免模式'], lineList(form.forbidden_patterns)],
      [['preferred_plot_patterns', '推荐情节模式'], lineList(form.preferred_plot_patterns)],
    ]),
    raw_input: section(storyBible.raw_input, [
      [['raw_idea', '原始创意'], form.raw_idea.trim()], [['raw_length_goal', '篇幅目标'], form.raw_length_goal.trim()],
      [['raw_must_keep', '必保留要素'], form.raw_must_keep.trim()], [['raw_notes', '原始笔记'], form.raw_notes.trim()],
      [['raw_hidden_setting', '隐藏设定'], form.raw_hidden_setting.trim()],
    ]),
    import_guidance: section(storyBible.import_guidance, [
      [['import_material_type', '导入素材类型'], form.import_material_type.trim()], [['must_keep', '必须保留'], form.import_must_keep.trim()],
      [['author_goal', '作者目标'], form.author_goal.trim()], [['adjustment_scope', '调整范围'], form.adjustment_scope.trim()],
      [['longline_plan', '长线预案'], form.longline_plan.trim()], [['tone_guardrails', '风格护栏'], form.tone_guardrails.trim()],
    ]),
    story_state: section(storyBible.story_state, [
      [['story_state', '故事状态'], form.story_state_text.trim()], [['continuity_facts', '连续性事实'], lineList(form.continuity_facts)],
      [['open_loops', '未闭合线索'], lineList(form.open_loops)],
    ]),
  };
}

export function asBibleRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function readBibleField(record: Record<string, unknown>, ...aliases: string[]): unknown {
  const key = aliases.find((alias) => Object.prototype.hasOwnProperty.call(record, alias));
  return key ? record[key] : undefined;
}

export function storyBibleFieldLabel(key: string): string {
  return FIELD_LABELS[key] || key.replace(/_/g, ' ');
}

export function hasBibleValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.some(hasBibleValue);
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).some(hasBibleValue);
  return true;
}

export function worldSettingToRows(value: unknown, idFactory: () => string): WorldSettingRow[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => ({
    id: idFactory(),
    key,
    value: stringify(item),
    originalValue: item,
  }));
}

export function worldSettingRowsToObject(rows: WorldSettingRow[]): Record<string, unknown> {
  return rows.reduce<Record<string, unknown>>((result, row) => {
    const key = row.key.trim();
    if (!key) return result;
    const value = row.value.trim();
    result[key] = row.originalValue !== undefined && value === stringify(row.originalValue)
      ? row.originalValue
      : value;
    return result;
  }, {});
}

function storyBibleSectionLabel(key: string): string {
  if (SECTION_LABELS[key]) return SECTION_LABELS[key];
  if (key.startsWith('deconstruction_')) return `拆书分析 · ${key.slice('deconstruction_'.length).replace(/_/g, ' ')}`;
  return key.replace(/_/g, ' ');
}

function mergeFields(record: Record<string, unknown>, fields: Array<[string[], unknown]>): Record<string, unknown> {
  const result = { ...record };
  for (const [aliases, value] of fields) {
    const existingKey = aliases.find((alias) => Object.prototype.hasOwnProperty.call(result, alias));
    result[existingKey || aliases[0]] = value;
  }
  return result;
}

function stringify(value: unknown): string {
  if (value == null) return '';
  if (Array.isArray(value)) return value.map(stringify).join('\n');
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}：${stringify(item)}`).join('\n');
  return String(value);
}

function toLines(value: unknown): string {
  return Array.isArray(value) ? value.map(stringify).join('\n') : stringify(value);
}

function lineList(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}
