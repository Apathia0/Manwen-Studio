/**
 * InkAI quality assessment knowledge base.
 * Extracted from InkAI-main/inkai/agents/quality_assessor.py
 *
 * 5-dimension scoring rubrics with weights, quality levels, improvement suggestions.
 */

// ── Types ──────────────────────────────────────────────────────────────

export type DimensionName =
  | '内容质量'
  | '文笔质量'
  | '结构质量'
  | '人物质量'
  | '读者体验';

export type QualityLevel = '优秀' | '良好' | '一般' | '较差' | '不合格';

export interface DimensionInfo {
  weight: number;
  subDimensions: string[];
}

export interface ScoringCriteria {
  scoreRange: [number, number];
  description: string;
}

export interface DimensionScores {
  '内容质量': number;
  '文笔质量': number;
  '结构质量': number;
  '人物质量': number;
  '读者体验': number;
}

export interface ImprovementSuggestion {
  type: string;
  priority: string;
  suggestion: string;
  implementation: string;
}

export interface QualityReport {
  overallScore: number;
  qualityLevel: QualityLevel;
  dimensionScores: DimensionScores;
  improvementSuggestions: ImprovementSuggestion[];
}

// ── Data ───────────────────────────────────────────────────────────────

export const ASSESSMENT_DIMENSIONS: Record<DimensionName, DimensionInfo> = {
  '内容质量': {
    weight: 0.3,
    subDimensions: ['逻辑性', '创新性', '深度', '完整性'],
  },
  '文笔质量': {
    weight: 0.25,
    subDimensions: ['语言流畅度', '文采', '表达准确性', '风格一致性'],
  },
  '结构质量': {
    weight: 0.2,
    subDimensions: ['章节结构', '情节安排', '节奏控制', '伏笔设置'],
  },
  '人物质量': {
    weight: 0.15,
    subDimensions: ['人物立体性', '性格一致性', '成长弧线', '关系网络'],
  },
  '读者体验': {
    weight: 0.1,
    subDimensions: ['可读性', '吸引力', '情感共鸣', '记忆点'],
  },
};

export const QUALITY_LEVELS: Record<QualityLevel, ScoringCriteria> = {
  '优秀': { scoreRange: [90, 100], description: '达到出版标准，具有商业价值' },
  '良好': { scoreRange: [80, 89], description: '质量较高，有改进空间' },
  '一般': { scoreRange: [70, 79], description: '基本合格，需要改进' },
  '较差': { scoreRange: [60, 69], description: '存在明显问题，需要大幅改进' },
  '不合格': { scoreRange: [0, 59], description: '质量不达标，需要重新创作' },
};

// ── Helpers ────────────────────────────────────────────────────────────

/** Determine quality level from a numeric score. */
export function getQualityLevel(score: number): QualityLevel {
  for (const [level, criteria] of Object.entries(QUALITY_LEVELS)) {
    const [min, max] = criteria.scoreRange;
    if (score >= min && score <= max) {
      return level as QualityLevel;
    }
  }
  return '不合格';
}

/**
 * Calculate the overall weighted score from individual dimension scores.
 * Uses InkAI weights: 内容质量30%, 文笔质量25%, 结构质量20%, 人物质量15%, 读者体验10%.
 */
export function calculateOverallScore(dimensions: DimensionScores): number {
  let total = 0;
  for (const [name, score] of Object.entries(dimensions)) {
    const dim = ASSESSMENT_DIMENSIONS[name as DimensionName];
    if (dim) {
      total += score * dim.weight;
    }
  }
  return Math.round(total * 100) / 100;
}

/** Generate improvement suggestions based on dimension scores. */
export function generateImprovementSuggestions(
  dimensions: DimensionScores,
  issues: string[],
): ImprovementSuggestion[] {
  const suggestions: ImprovementSuggestion[] = [];

  for (const issue of issues) {
    if (issue.includes('内容过短')) {
      suggestions.push({
        type: '内容扩展',
        priority: '高',
        suggestion: '增加更多细节描述和情节发展',
        implementation: '可以添加环境描写、人物心理活动、对话细节等',
      });
    } else if (issue.includes('语言不够流畅')) {
      suggestions.push({
        type: '文笔改进',
        priority: '高',
        suggestion: '优化语言表达，提高流畅度',
        implementation: '检查句式结构，避免重复用词，增加语言变化',
      });
    } else if (issue.includes('结构需要优化')) {
      suggestions.push({
        type: '结构优化',
        priority: '中',
        suggestion: '重新组织内容结构',
        implementation: '确保逻辑清晰，段落安排合理，过渡自然',
      });
    }
  }

  for (const [name, score] of Object.entries(dimensions)) {
    if (score < 70) {
      suggestions.push({
        type: `${name}提升`,
        priority: '中',
        suggestion: `提升${name}水平`,
        implementation: `针对${name}的具体问题进行改进`,
      });
    }
  }

  return suggestions;
}

/** Run a basic quality check on content length, language, and structure. */
export function basicQualityCheck(
  content: string,
): { issues: string[]; strengths: string[]; contentScore: number; writingScore: number; structureScore: number } {
  const issues: string[] = [];
  const strengths: string[] = [];
  let contentScore = 0;
  let writingScore = 0;
  let structureScore = 0;

  if (content.length > 100) {
    contentScore += 20;
    strengths.push('内容长度适中');
  } else {
    issues.push('内容过短');
  }

  const sentences = content.split(/[。！？]/).filter(Boolean);
  const words = content.split(/\s+/).filter(Boolean);
  if (sentences.length >= 3 && words.length >= 10) {
    writingScore += 25;
    strengths.push('语言流畅');
  } else {
    issues.push('语言不够流畅');
  }

  if (content.length >= 200 && (content.includes('。') || content.includes('\n'))) {
    structureScore += 25;
    strengths.push('结构清晰');
  } else {
    issues.push('结构需要优化');
  }

  return { issues, strengths, contentScore, writingScore, structureScore };
}

// ── Builder ────────────────────────────────────────────────────────────

/**
 * Build the quality assessment section of a system prompt.
 * Injects 5-dimension scoring rubrics, quality levels, and evaluation criteria.
 */
export function buildQualityPromptSegment(): string {
  let segment = '【质量评估】\n\n';

  segment += '5维度评估体系（加权综合评分）：\n';
  for (const [name, info] of Object.entries(ASSESSMENT_DIMENSIONS)) {
    segment += `  【${name}】权重 ${info.weight * 100}%\n`;
    segment += `    子维度：${info.subDimensions.join('、')}\n`;
  }

  segment += '\n质量等级划分：\n';
  for (const [level, criteria] of Object.entries(QUALITY_LEVELS)) {
    const [min, max] = criteria.scoreRange;
    segment += `  【${level}】${min}-${max}分 - ${criteria.description}\n`;
  }

  segment += '\n评估原则：\n';
  segment += '1. 内容质量（30%）：评估逻辑性、创新性、深度、完整性\n';
  segment += '2. 文笔质量（25%）：评估语言流畅度、文采、表达准确性、风格一致性\n';
  segment += '3. 结构质量（20%）：评估章节结构、情节安排、节奏控制、伏笔设置\n';
  segment += '4. 人物质量（15%）：评估人物立体性、性格一致性、成长弧线、关系网络\n';
  segment += '5. 读者体验（10%）：评估可读性、吸引力、情感共鸣、记忆点\n';

  segment += '\n改进建议方向：\n';
  segment += '- 内容不足 → 增加细节描写和情节发展\n';
  segment += '- 语言问题 → 优化句式结构，增加语言变化\n';
  segment += '- 结构问题 → 确保逻辑清晰，段落过渡自然\n';
  segment += '- 单项低于70分 → 针对该维度重点改进\n';

  return segment;
}
