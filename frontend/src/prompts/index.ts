/**
 * InkAI knowledge base barrel export.
 * Unified entry point for all prompt knowledge segments.
 */

import {
  buildTagPromptSegment as _buildTag,
} from './inkai-tags';
import {
  buildCharacterPromptSegment as _buildChar,
} from './inkai-characters';
import {
  buildStorylinePromptSegment as _buildStory,
} from './inkai-storyline';
import {
  buildChapterPromptSegment as _buildChapter,
} from './inkai-chapter';
import {
  buildQualityPromptSegment as _buildQuality,
} from './inkai-quality';

// Re-export all types and values from each knowledge module
export type {
  TagCategoryName,
  TagCategories,
  TagWeights,
  CompatibilityMatrix,
  PopularCombination,
  TagScores,
} from './inkai-tags';

export {
  TAG_CATEGORIES,
  TAG_WEIGHTS,
  TAG_COMPATIBILITY_MATRIX,
  POPULAR_TAG_COMBINATIONS,
  getAllTags,
  getTagsByCategory,
  calculateTagCompatibility,
  calculateOverallTagCompatibility,
  buildTagPromptSegment,
} from './inkai-tags';

export type {
  BigFiveTrait,
  TraitLevel,
  BigFiveTraits,
  ProfessionInfo,
  ProfessionName,
  BigFiveScores,
  CharacterArchetype,
  RelationshipNetwork,
  CharacterArc,
} from './inkai-characters';

export {
  BIG_FIVE_TRAITS,
  PROFESSION_TRAITS,
  CHARACTER_ARCHETYPES,
  RELATIONSHIP_FUNCTIONS,
  analyzeBigFive,
  recommendProfession,
  recommendPersonalityTraits,
  buildCharacterPromptSegment,
} from './inkai-characters';

export type {
  ActStructure,
  ThreeActKey,
  ThreeActStructure,
  PlotCurve,
  ConflictType,
  PacingSpeed,
  ActPacing,
  ForeshadowItem,
} from './inkai-storyline';

export {
  THREE_ACT_STRUCTURE,
  PLOT_CURVES,
  CONFLICT_TYPES,
  FORESHADOW_TYPES,
  STRUCTURE_ANALYSIS,
  ACT_PACING,
  analyzeStoryType,
  recommendConflicts,
  recommendStructure,
  estimateStoryLength,
  estimateChapterCount,
  buildStorylinePromptSegment,
} from './inkai-storyline';

export type {
  TechniqueCategory,
  WritingStyleName,
  ChapterType,
  WritingStyle,
  WordRange,
} from './inkai-chapter';

export {
  WRITING_TECHNIQUES,
  WRITING_STYLES,
  WORD_COUNT_GUIDELINES,
  EMOTIONAL_WORDS,
  analyzeWritingStyle,
  getWordRequirements,
  recommendTechniques,
  calculateDialogueRatio,
  assessEmotionalIntensity,
  analyzePacing,
  buildChapterPromptSegment,
} from './inkai-chapter';

export type {
  DimensionName,
  QualityLevel,
  DimensionInfo,
  ScoringCriteria,
  DimensionScores,
  ImprovementSuggestion,
  QualityReport,
} from './inkai-quality';

export {
  ASSESSMENT_DIMENSIONS,
  QUALITY_LEVELS,
  getQualityLevel,
  calculateOverallScore,
  generateImprovementSuggestions,
  basicQualityCheck,
  buildQualityPromptSegment,
} from './inkai-quality';

// ── Unified Builder ────────────────────────────────────────────────────

export interface BuildFrameworkPromptOptions {
  includeTags?: boolean;
  includeCharacters?: boolean;
  includeStoryline?: boolean;
  includeChapter?: boolean;
  includeQuality?: boolean;
}

const DEFAULT_OPTIONS: BuildFrameworkPromptOptions = {
  includeTags: true,
  includeCharacters: true,
  includeStoryline: true,
  includeChapter: true,
  includeQuality: true,
};

/**
 * Build a complete framework system prompt by combining all knowledge segments.
 *
 * @param description - User's story description to include in the prompt
 * @param options - Optional flags to include/exclude specific knowledge segments
 * @returns A complete system prompt string suitable for LLM injection
 */
export function buildFrameworkPrompt(
  description: string,
  options?: BuildFrameworkPromptOptions,
): string {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  const parts: string[] = [];

  parts.push('你是一个专业的小说创作辅助系统。请根据用户的故事描述，结合以下知识体系，提供专业的小说创作建议。');
  parts.push('');
  parts.push(`用户故事描述：${description}`);
  parts.push('');

  if (opts.includeTags) {
    parts.push(_buildTag());
    parts.push('');
  }

  if (opts.includeCharacters) {
    parts.push(_buildChar());
    parts.push('');
  }

  if (opts.includeStoryline) {
    parts.push(_buildStory());
    parts.push('');
  }

  if (opts.includeChapter) {
    parts.push(_buildChapter());
    parts.push('');
  }

  if (opts.includeQuality) {
    parts.push(_buildQuality());
    parts.push('');
  }

  parts.push('请基于以上知识体系，结合用户描述，返回结构化的JSON响应。');

  return parts.join('\n');
}
