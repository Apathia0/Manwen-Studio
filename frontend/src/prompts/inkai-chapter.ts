/**
 * InkAI chapter writing knowledge base.
 * Extracted from InkAI-main/inkai/agents/chapter_writer.py
 *
 * Writing technique library (5 categories), 4 style templates,
 * word count guidelines.
 */

// ── Types ──────────────────────────────────────────────────────────────

export type TechniqueCategory =
  | '开头技巧'
  | '情节推进'
  | '人物塑造'
  | '环境描写'
  | '结尾技巧';

export type WritingStyleName =
  | '轻松愉快'
  | '严肃深刻'
  | '热血激昂'
  | '温馨治愈';

export type ChapterType = '标准' | '对话' | '动作' | '情感' | '短章节' | '长章节';

export interface WritingStyle {
  features: string;
  techniques: string[];
}

export interface WordRange {
  min: number;
  max: number;
  ideal: number;
}

// ── Data ───────────────────────────────────────────────────────────────

export const WRITING_TECHNIQUES: Record<TechniqueCategory, string[]> = {
  '开头技巧': [
    '动作开头', '对话开头', '场景描写开头', '内心独白开头', '悬念开头',
  ],
  '情节推进': [
    '冲突升级', '转折点设置', '伏笔埋设', '悬念营造', '节奏控制',
  ],
  '人物塑造': [
    '对话展现性格', '行为体现内心', '细节描写', '对比手法', '成长轨迹',
  ],
  '环境描写': [
    '氛围营造', '感官描写', '象征手法', '对比烘托', '动态描写',
  ],
  '结尾技巧': [
    '悬念结尾', '情感高潮', '转折结尾', '呼应开头', '开放式结尾',
  ],
};

export const WRITING_STYLES: Record<WritingStyleName, WritingStyle> = {
  '轻松愉快': {
    features: '语言幽默、节奏明快、对话生动',
    techniques: ['幽默对话', '轻松氛围', '明快节奏', '生动描写'],
  },
  '严肃深刻': {
    features: '语言庄重、思想深刻、描写细腻',
    techniques: ['深度思考', '细腻描写', '庄重语言', '哲学思辨'],
  },
  '热血激昂': {
    features: '情感强烈、节奏紧凑、气势磅礴',
    techniques: ['情感渲染', '节奏紧凑', '气势描写', '激情对话'],
  },
  '温馨治愈': {
    features: '语言温暖、情感细腻、氛围温馨',
    techniques: ['温暖描写', '细腻情感', '温馨氛围', '治愈元素'],
  },
};

export const WORD_COUNT_GUIDELINES: Record<string, WordRange> = {
  '短章节': { min: 1500, max: 2500, ideal: 2000 },
  '标准章节': { min: 2500, max: 4000, ideal: 3000 },
  '长章节': { min: 4000, max: 6000, ideal: 5000 },
};

export const EMOTIONAL_WORDS: Record<string, string[]> = {
  '高': ['愤怒', '狂喜', '绝望', '兴奋', '恐惧'],
  '中': ['高兴', '难过', '紧张', '担心', '期待'],
  '低': ['平静', '淡然', '轻松', '舒适', '满足'],
};

// ── Helpers ────────────────────────────────────────────────────────────

/** Analyze which writing style to use based on the story tone description. */
export function analyzeWritingStyle(tone: string): WritingStyleName {
  if (tone.includes('轻松') || tone.includes('愉快')) return '轻松愉快';
  if (tone.includes('严肃') || tone.includes('深刻')) return '严肃深刻';
  if (tone.includes('热血') || tone.includes('激昂')) return '热血激昂';
  if (tone.includes('温馨') || tone.includes('治愈')) return '温馨治愈';
  return '轻松愉快';
}

/** Get word count requirements for a chapter type. */
export function getWordRequirements(chapterType: ChapterType): WordRange {
  if (chapterType === '短章节') return WORD_COUNT_GUIDELINES['短章节'];
  if (chapterType === '长章节') return WORD_COUNT_GUIDELINES['长章节'];
  return WORD_COUNT_GUIDELINES['标准章节'];
}

/** Recommend writing techniques based on chapter type. */
export function recommendTechniques(chapterType: ChapterType): string[] {
  switch (chapterType) {
    case '对话':
      return ['对话展现性格', '对话推进情节'];
    case '动作':
      return ['动作描写', '节奏控制'];
    case '情感':
      return ['情感渲染', '内心独白'];
    default:
      return ['情节推进', '人物塑造'];
  }
}

/** Calculate dialogue ratio in content (percentage). */
export function calculateDialogueRatio(content: string): number {
  if (!content) return 0;
  const dialogueMatches = content.match(/[""][^""]*[""]|„[^„]*“/g);
  if (!dialogueMatches) return 0;
  const dialogueLength = dialogueMatches.reduce((sum, m) => sum + m.length, 0);
  return (dialogueLength / content.length) * 100;
}

/** Assess emotional intensity of content. */
export function assessEmotionalIntensity(content: string): string {
  if (!content) return '低';

  const scores: Record<string, number> = { '高': 0, '中': 0, '低': 0 };
  for (const [intensity, words] of Object.entries(EMOTIONAL_WORDS)) {
    for (const word of words) {
      scores[intensity] += content.split(word).length - 1;
    }
  }

  const maxIntensity = Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
  return scores[maxIntensity] > 0 ? maxIntensity : '低';
}

/** Analyze pacing based on punctuation distribution. */
export function analyzePacing(content: string): '快节奏' | '慢节奏' | '中等节奏' {
  if (!content) return '中等节奏';

  const fastPunc = ['！', '？'];
  const slowPunc = ['。', '，', '；'];

  const fastCount = fastPunc.reduce((sum, p) => sum + content.split(p).length - 1, 0);
  const slowCount = slowPunc.reduce((sum, p) => sum + content.split(p).length - 1, 0);

  if (fastCount > slowCount * 0.3) return '快节奏';
  if (slowCount > fastCount * 2) return '慢节奏';
  return '中等节奏';
}

// ── Builder ────────────────────────────────────────────────────────────

/**
 * Build the chapter writing section of a system prompt.
 * Injects writing techniques, style templates, and word count guidelines.
 */
export function buildChapterPromptSegment(): string {
  let segment = '【章节写作】\n\n';

  segment += '写作技巧库（5大类25种技巧）：\n';
  for (const [category, techniques] of Object.entries(WRITING_TECHNIQUES)) {
    segment += `  【${category}】${techniques.join('、')}\n`;
  }

  segment += '\n文风模板（4种）：\n';
  for (const [name, style] of Object.entries(WRITING_STYLES)) {
    segment += `  【${name}】${style.features}\n`;
    segment += `    技巧：${style.techniques.join('、')}\n`;
  }

  segment += '\n字数规范：\n';
  for (const [label, range] of Object.entries(WORD_COUNT_GUIDELINES)) {
    segment += `  ${label}：${range.min}-${range.max}字（理想${range.ideal}字）\n`;
  }

  segment += '\n章节写作要求：\n';
  segment += '1. 保持人物性格一致性\n';
  segment += '2. 推进故事情节发展\n';
  segment += '3. 运用适当的写作技巧\n';
  segment += '4. 控制章节节奏和字数\n';
  segment += '5. 设置适当的悬念和伏笔\n';
  segment += '6. 保持文风的一致性\n';
  segment += '7. 对话比例建议控制在20%-60%之间\n';
  segment += '8. 避免句式单一，注意长短句结合\n';

  return segment;
}
