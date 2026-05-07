/**
 * InkAI storyline generation knowledge base.
 * Extracted from InkAI-main/inkai/agents/storyline_generator.py
 *
 * Three-act structure (25/50/25%), conflict types, foreshadowing, pacing.
 */

// ── Types ──────────────────────────────────────────────────────────────

export interface ActStructure {
  '占比': string;
  '功能': string;
  '关键要素': string[];
}

export type ThreeActKey = '第一幕' | '第二幕' | '第三幕';

export type ThreeActStructure = Record<ThreeActKey, ActStructure>;

export interface PlotCurve {
  name: string;
  phases: string[];
}

export type ConflictType =
  | '人与自我'
  | '人与人'
  | '人与社会'
  | '人与自然'
  | '人与命运'
  | '人与技术';

export type PacingSpeed = '快' | '变化' | '慢';

export interface ActPacing {
  speed: PacingSpeed;
  description: string;
  key_moments?: string[];
  tension_points?: string[];
  climax_moments?: string[];
}

export interface ForeshadowItem {
  type: string;
  content: string;
  placement: string;
  payoff: string;
}

// ── Data ───────────────────────────────────────────────────────────────

export const THREE_ACT_STRUCTURE: ThreeActStructure = {
  '第一幕': {
    '占比': '25%',
    '功能': '建立世界、介绍人物、设置冲突',
    '关键要素': ['开场钩子', '人物介绍', '世界观建立', '冲突引入', '第一转折点'],
  },
  '第二幕': {
    '占比': '50%',
    '功能': '发展冲突、人物成长、情节推进',
    '关键要素': ['冲突升级', '人物考验', '次要情节', '中点转折', '危机时刻'],
  },
  '第三幕': {
    '占比': '25%',
    '功能': '高潮对决、冲突解决、故事收尾',
    '关键要素': ['最终对决', '冲突解决', '人物成长体现', '伏笔回收', '结局'],
  },
};

export const PLOT_CURVES: PlotCurve[] = [
  {
    name: '英雄之旅',
    phases: [
      '平凡世界', '冒险召唤', '拒绝召唤', '导师出现', '跨越门槛',
      '考验盟友敌人', '接近洞穴', '磨难', '奖赏', '回归之路', '复活', '回归',
    ],
  },
  {
    name: '三幕结构',
    phases: ['建立', '对抗', '解决'],
  },
  {
    name: '五幕结构',
    phases: ['开端', '发展', '高潮', '回落', '结局'],
  },
];

export const CONFLICT_TYPES: Record<ConflictType, string> = {
  '人与自我': '内心冲突、道德选择、自我认知',
  '人与人': '人际关系、竞争、背叛、误解',
  '人与社会': '社会制度、文化冲突、群体压力',
  '人与自然': '生存挑战、自然灾害、环境威胁',
  '人与命运': '宿命对抗、时间限制、不可抗力',
  '人与技术': '科技威胁、AI冲突、技术失控',
};

export const FORESHADOW_TYPES = ['预言式', '象征式', '对话暗示', '物品伏笔', '事件预兆'] as const;

export const STRUCTURE_ANALYSIS = {
  narrative_arc: {
    exposition: '故事背景和人物介绍',
    rising_action: '冲突发展和情节推进',
    climax: '故事高潮和关键转折',
    falling_action: '冲突解决过程',
    resolution: '故事结局和人物命运',
  },
  plot_points: {
    inciting_incident: '引发事件',
    first_plot_point: '第一情节点',
    midpoint: '中点转折',
    second_plot_point: '第二情节点',
    climax: '故事高潮',
  },
};

export const ACT_PACING: Record<ThreeActKey, ActPacing> = {
  '第一幕': {
    speed: '快',
    description: '快速建立世界和人物，保持读者兴趣',
    key_moments: ['开场钩子', '人物登场', '冲突引入'],
  },
  '第二幕': {
    speed: '变化',
    description: '快慢结合，有张有弛',
    tension_points: ['冲突升级', '人物考验', '危机时刻'],
  },
  '第三幕': {
    speed: '快',
    description: '快速推进到高潮和结局',
    climax_moments: ['最终对决', '冲突解决', '故事收尾'],
  },
};

// ── Helpers ────────────────────────────────────────────────────────────

/** Analyze story type from genre and theme tags. */
export function analyzeStoryType(typeTags: string[], themeTags: string[]): string {
  if (typeTags.includes('都市')) {
    if (themeTags.includes('系统')) return '都市系统流爽文';
    if (typeTags.includes('商战')) return '都市商战文';
    return '都市现实文';
  }
  if (typeTags.includes('玄幻') || typeTags.includes('修仙')) return '玄幻修仙文';
  if (typeTags.includes('历史')) return '历史架空文';
  if (typeTags.includes('科幻')) return '科幻未来文';
  if (typeTags.includes('悬疑')) return '悬疑推理文';
  return '综合类型文';
}

/** Recommend conflict types based on genre and theme tags. */
export function recommendConflicts(
  typeTags: string[],
  themeTags: string[],
): ConflictType[] {
  const conflicts = new Set<ConflictType>();

  if (typeTags.includes('都市')) {
    conflicts.add('人与自我');
    conflicts.add('人与人');
    conflicts.add('人与社会');
  } else if (typeTags.includes('玄幻')) {
    conflicts.add('人与自我');
    conflicts.add('人与命运');
    conflicts.add('人与自然');
  } else if (typeTags.includes('科幻')) {
    conflicts.add('人与技术');
    conflicts.add('人与社会');
    conflicts.add('人与自然');
  }

  if (themeTags.includes('成长')) conflicts.add('人与自我');
  if (themeTags.includes('权谋')) {
    conflicts.add('人与人');
    conflicts.add('人与社会');
  }
  if (themeTags.includes('冒险')) {
    conflicts.add('人与自然');
    conflicts.add('人与命运');
  }

  return [...conflicts];
}

/** Recommend story structure based on style and theme tags. */
export function recommendStructure(styleTags: string[], themeTags: string[]): string {
  if (styleTags.includes('轻松愉快')) return '三幕结构（适合轻松节奏）';
  if (styleTags.includes('严肃深刻')) return '五幕结构（适合深度探讨）';
  if (themeTags.includes('冒险')) return '英雄之旅（适合冒险故事）';
  return '三幕结构（经典结构）';
}

/** Estimate story length based on genre tags. */
export function estimateStoryLength(typeTags: string[]): string {
  if (typeTags.includes('都市')) return '中篇（20-50万字）';
  if (typeTags.includes('玄幻') || typeTags.includes('修仙')) return '长篇（50-200万字）';
  if (typeTags.includes('历史')) return '长篇（50-100万字）';
  return '中篇（30-80万字）';
}

/** Estimate chapter count based on genre tags. */
export function estimateChapterCount(typeTags: string[]): { min: number; max: number } {
  if (typeTags.includes('都市')) return { min: 50, max: 150 };
  if (typeTags.includes('玄幻') || typeTags.includes('修仙')) return { min: 200, max: 500 };
  if (typeTags.includes('历史')) return { min: 100, max: 300 };
  return { min: 80, max: 200 };
}

// ── Builder ────────────────────────────────────────────────────────────

/**
 * Build the story structure section of a system prompt.
 * Injects three-act structure, conflict types, foreshadowing, and pacing.
 */
export function buildStorylinePromptSegment(): string {
  let segment = '【故事结构】\n\n';

  segment += '三幕剧结构（经典叙事框架）：\n';
  for (const [act, info] of Object.entries(THREE_ACT_STRUCTURE)) {
    segment += `  ${act}（占比${info['占比']}）\n`;
    segment += `    功能：${info['功能']}\n`;
    segment += `    关键要素：${info['关键要素'].join('、')}\n`;
  }

  segment += '\n冲突类型（6种）：\n';
  for (const [type, desc] of Object.entries(CONFLICT_TYPES)) {
    segment += `  ${type}：${desc}\n`;
  }

  segment += '\n情节结构可选模板：\n';
  for (const curve of PLOT_CURVES) {
    segment += `  ${curve.name}：${curve.phases.join(' → ')}\n`;
  }

  segment += '\n三幕节奏控制：\n';
  for (const [act, pacing] of Object.entries(ACT_PACING)) {
    const moments = pacing.key_moments ?? pacing.tension_points ?? pacing.climax_moments ?? [];
    segment += `  ${act}：${pacing.speed}节奏 - ${pacing.description}\n`;
    segment += `    关键节点：${moments.join('、')}\n`;
  }

  segment += '\n故事设计原则：\n';
  segment += '1. 采用三幕剧结构，确保节奏合理（25%/50%/25%）\n';
  segment += '2. 设置多层次冲突，增加故事张力\n';
  segment += '3. 设计人物成长弧线，体现主题\n';
  segment += '4. 埋下伏笔（预言式、象征式、对话暗示等），增强连贯性\n';
  segment += '5. 构建完整世界观，增强可信度\n';
  segment += '6. 设置转折点，保持读者兴趣\n';

  segment += '\n伏笔管理规范：\n';
  segment += '  第一幕：埋下核心伏笔（预言式/象征式）\n';
  segment += '  第二幕：发展伏笔，增加复杂度\n';
  segment += '  第三幕：回收所有伏笔，完成叙事闭环\n';

  return segment;
}
