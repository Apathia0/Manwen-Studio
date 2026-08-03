import type { StoryBible } from '../api';

export type ReferenceSummaryItem = {
  key: string;
  label: string;
  text: string;
};

export type ReferenceRoutine = {
  name: string;
  category: string;
  structure: string;
  emotionCurve: string;
  evidence: string;
};

export type ReferenceStyleSample = {
  label: string;
  snippet: string;
};

export type ReferenceMaterialForm = {
  sentence: string;
  dialogue: string;
  description: string;
  emotionExpression: string;
  povAndNarration: string;
  openingHook: string;
  chapterEndHooks: string;
  emotionCycle: string;
  infoReleasePattern: string;
  mustDo: string;
  avoid: string;
  promptNotes: string;
  routines: ReferenceRoutine[];
  report: string;
};

export type ReferenceMaterialSummary = {
  hasContent: boolean;
  sourceLabel: string;
  sampledChapterCount: number;
  confidencePercent: number | null;
  positioning: string;
  expressionPlan: ReferenceSummaryItem[];
  rhythmPlan: ReferenceSummaryItem[];
  mustDo: string[];
  avoid: string[];
  promptNotes: string[];
  routines: ReferenceRoutine[];
  report: string;
  samples: ReferenceStyleSample[];
  learnedTechniques: unknown[];
  referencePlots: unknown[];
  referenceRhythm: unknown;
  emotionModules: unknown;
};

const EXPRESSION_FIELDS = [
  ['sentence', '句式节奏'],
  ['dialogue', '对话组织'],
  ['description', '描写方式'],
  ['emotion_expression', '情绪表达'],
  ['pov_and_narration', '叙事视角'],
] as const;

const RHYTHM_FIELDS = [
  ['opening_hook', '开篇抓力'],
  ['chapter_end_hooks', '章尾钩子'],
  ['emotion_cycle', '情绪循环'],
  ['info_release_pattern', '信息释放'],
] as const;

export function buildReferenceMaterialSummary(storyBible: StoryBible): ReferenceMaterialSummary {
  const isActive = hasActiveReferenceMaterial(storyBible);
  const profile = isActive ? asRecord(storyBible.reference_author_profile) : {};
  const styleProfile = asRecord(profile.style_profile);
  const rhythmProfile = asRecord(profile.rhythm_profile);
  const writingGuide = asRecord(profile.writing_guide);
  const sampledChapters = asArray(profile.sampled_chapters);
  const routines = asArray(profile.routine_cards)
    .map((item) => asRecord(item))
    .map((item, index) => ({
      name: textValue(item.name) || `写作模式 ${index + 1}`,
      category: textValue(item.category),
      structure: textValue(item.structure),
      emotionCurve: textValue(item.emotion_curve),
      evidence: textValue(item.evidence_summary),
    }))
    .filter((item) => item.name || item.structure || item.evidence);
  const expressionPlan = EXPRESSION_FIELDS
    .map(([key, label]) => ({ key, label, text: generalText(styleProfile[key]) }))
    .filter((item) => item.text);
  const rhythmPlan = RHYTHM_FIELDS
    .map(([key, label]) => ({ key, label, text: generalText(rhythmProfile[key]) }))
    .filter((item) => item.text);
  const mustDo = stringList(writingGuide.do);
  const avoid = stringList(writingGuide.avoid);
  const promptNotes = stringList(writingGuide.prompt_notes);
  const report = isActive ? textValue(storyBible.reference_author_report ?? storyBible.reference_report) : '';
  const samples = (isActive ? asArray(storyBible.reference_style_samples) : [])
    .map((item, index) => {
      const sample = asRecord(item);
      return {
        label: `风格样本 ${index + 1}`,
        snippet: textValue(sample.snippet ?? sample.excerpt ?? sample.content ?? item),
      };
    })
    .filter((sample) => sample.snippet);
  const learnedTechniques = isActive ? asArray(storyBible.learned_techniques) : [];
  const referencePlots = isActive ? asArray(storyBible.reference_plots) : [];
  const referenceRhythm = isActive ? storyBible.reference_rhythm : undefined;
  const emotionModules = isActive ? storyBible.reference_emotion_modules : undefined;
  const sourceLabel = textValue(profile.source_label) || '匿名参考样本';
  const confidence = Number(profile.confidence);
  const confidencePercent = Number.isFinite(confidence) ? Math.round(confidence <= 1 ? confidence * 100 : confidence) : null;
  const positioning = [expressionPlan[0]?.text, rhythmPlan[0]?.text].filter(Boolean).join('；');
  const hasContent = Boolean(
    expressionPlan.length || rhythmPlan.length || mustDo.length || avoid.length || promptNotes.length || routines.length || report || samples.length
    || learnedTechniques.length || referencePlots.length || hasValue(referenceRhythm) || hasValue(emotionModules),
  );
  return {
    hasContent,
    sourceLabel,
    sampledChapterCount: sampledChapters.length,
    confidencePercent,
    positioning,
    expressionPlan,
    rhythmPlan,
    mustDo,
    avoid,
    promptNotes,
    routines,
    report,
    samples,
    learnedTechniques,
    referencePlots,
    referenceRhythm,
    emotionModules,
  };
}

export function referenceMaterialGroupCount(summary: ReferenceMaterialSummary): number {
  if (!summary.hasContent) return 0;
  return [
    summary.expressionPlan.length > 0,
    summary.rhythmPlan.length > 0,
    summary.mustDo.length > 0 || summary.avoid.length > 0,
    summary.routines.length > 0,
    Boolean(summary.report),
    summary.samples.length > 0,
    summary.learnedTechniques.length > 0,
    summary.referencePlots.length > 0,
    hasValue(summary.referenceRhythm),
    hasValue(summary.emotionModules),
  ].filter(Boolean).length;
}

export function referenceValueText(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(referenceValueText).filter(Boolean).join('；');
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return textValue(record.summary ?? record.description ?? record.name ?? record.title ?? record.text)
      || Object.values(record).map(referenceValueText).filter(Boolean).join('；');
  }
  return String(value);
}

export function hasActiveReferenceMaterial(storyBible: StoryBible): boolean {
  const profile = asRecord(storyBible.reference_author_profile);
  if (profile.manual_override === true) return true;
  if (Object.keys(asRecord(storyBible.deconstruction)).length > 0) return true;
  return Object.entries(storyBible).some(([key, value]) => key.startsWith('deconstruction_') && Object.keys(asRecord(value)).length > 0);
}

export function createReferenceMaterialForm(storyBible: StoryBible): ReferenceMaterialForm {
  const isActive = hasActiveReferenceMaterial(storyBible);
  const profile = isActive ? asRecord(storyBible.reference_author_profile) : {};
  const styleProfile = asRecord(profile.style_profile);
  const rhythmProfile = asRecord(profile.rhythm_profile);
  const writingGuide = asRecord(profile.writing_guide);
  const summary = buildReferenceMaterialSummary(storyBible);
  return {
    sentence: generalText(styleProfile.sentence),
    dialogue: generalText(styleProfile.dialogue),
    description: generalText(styleProfile.description),
    emotionExpression: generalText(styleProfile.emotion_expression),
    povAndNarration: generalText(styleProfile.pov_and_narration),
    openingHook: generalText(rhythmProfile.opening_hook),
    chapterEndHooks: listText(rhythmProfile.chapter_end_hooks),
    emotionCycle: generalText(rhythmProfile.emotion_cycle),
    infoReleasePattern: generalText(rhythmProfile.info_release_pattern),
    mustDo: stringList(writingGuide.do).join('\n'),
    avoid: stringList(writingGuide.avoid).join('\n'),
    promptNotes: stringList(writingGuide.prompt_notes).join('\n'),
    routines: summary.routines.map((routine) => ({ ...routine })),
    report: isActive ? summary.report : '',
  };
}

export function buildReferenceMaterialPayload(storyBible: StoryBible, form: ReferenceMaterialForm): Partial<StoryBible> {
  const isActive = hasActiveReferenceMaterial(storyBible);
  const profile = isActive ? asRecord(storyBible.reference_author_profile) : {};
  const styleProfile = asRecord(profile.style_profile);
  const rhythmProfile = asRecord(profile.rhythm_profile);
  const writingGuide = asRecord(profile.writing_guide);
  const routineCards = asArray(profile.routine_cards).map(asRecord);
  const reportKey = Object.prototype.hasOwnProperty.call(storyBible, 'reference_author_report')
    ? 'reference_author_report'
    : Object.prototype.hasOwnProperty.call(storyBible, 'reference_report') ? 'reference_report' : 'reference_author_report';
  return {
    reference_author_profile: {
      ...profile,
      manual_override: true,
      style_profile: {
        ...styleProfile,
        sentence: withGeneral(styleProfile.sentence, form.sentence),
        dialogue: withGeneral(styleProfile.dialogue, form.dialogue),
        description: withGeneral(styleProfile.description, form.description),
        emotion_expression: withGeneral(styleProfile.emotion_expression, form.emotionExpression),
        pov_and_narration: withGeneral(styleProfile.pov_and_narration, form.povAndNarration),
      },
      rhythm_profile: {
        ...rhythmProfile,
        opening_hook: withGeneral(rhythmProfile.opening_hook, form.openingHook),
        chapter_end_hooks: lineList(form.chapterEndHooks),
        emotion_cycle: withGeneral(rhythmProfile.emotion_cycle, form.emotionCycle),
        info_release_pattern: withGeneral(rhythmProfile.info_release_pattern, form.infoReleasePattern),
      },
      writing_guide: {
        ...writingGuide,
        do: lineList(form.mustDo),
        avoid: lineList(form.avoid),
        prompt_notes: lineList(form.promptNotes),
      },
      routine_cards: form.routines.map((routine, index) => ({
        ...routineCards[index],
        name: routine.name.trim(),
        category: routine.category.trim(),
        structure: routine.structure.trim(),
        emotion_curve: routine.emotionCurve.trim(),
        evidence_summary: routine.evidence.trim(),
      })).filter((routine) => routine.name || routine.structure || routine.evidence_summary),
    },
    [reportKey]: form.report.trim(),
    ...(isActive ? {} : {
      reference_style_samples: [],
      learned_techniques: [],
      reference_plots: [],
      reference_rhythm: null,
      reference_emotion_modules: null,
    }),
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function generalText(value: unknown): string {
  if (Array.isArray(value)) return stringList(value).join('；');
  const record = asRecord(value);
  return textValue(record.general) || textValue(record.summary) || textValue(value);
}

function withGeneral(value: unknown, general: string): Record<string, unknown> {
  return { ...asRecord(value), general: general.trim() };
}

function listText(value: unknown): string {
  return Array.isArray(value) ? stringList(value).join('\n') : generalText(value);
}

function lineList(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function stringList(value: unknown): string[] {
  return asArray(value).map(referenceValueText).filter(Boolean);
}

function hasValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.some(hasValue);
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).some(hasValue);
  return true;
}
