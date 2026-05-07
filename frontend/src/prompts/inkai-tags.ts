/**
 * InkAI tag taxonomy knowledge base.
 * Extracted from InkAI-main/inkai/agents/tag_selector.py
 *
 * 70+ tags across 4 categories, compatibility matrix, popular combinations.
 */

// ── Types ──────────────────────────────────────────────────────────────

export type TagCategoryName = '类型标签' | '主题标签' | '风格标签' | '受众标签';

export interface TagCategories {
  '类型标签': Record<string, string[]>;
  '主题标签': Record<string, string[]>;
  '风格标签': Record<string, string[]>;
  '受众标签': Record<string, string[]>;
}

export interface TagWeights {
  '类型标签': number;
  '主题标签': number;
  '风格标签': number;
  '受众标签': number;
}

export type CompatibilityMatrix = Record<string, Record<string, number>>;

export interface PopularCombination {
  name: string;
  tags: string[];
  popularity: number;
  success_rate: number;
}

export interface TagScores {
  type_tags: string[];
  theme_tags: string[];
  style_tags: string[];
  audience_tags: string[];
}

// ── Data ───────────────────────────────────────────────────────────────

export const TAG_CATEGORIES: TagCategories = {
  '类型标签': {
    '现代': ['都市', '校园', '职场', '娱乐圈', '商战', '医疗', '律政'],
    '古代': ['历史', '宫廷', '武侠', '仙侠', '古言', '架空', '种田'],
    '奇幻': ['玄幻', '奇幻', '魔幻', '异世界', '穿越', '重生', '修仙'],
    '科幻': ['科幻', '未来', '星际', '机甲', '末世', '赛博朋克', '太空'],
    '悬疑': ['悬疑', '推理', '犯罪', '恐怖', '灵异', '惊悚', '探案'],
    '其他': ['军事', '体育', '游戏', '美食', '旅游', '音乐', '艺术'],
  },
  '主题标签': {
    '成长': ['成长', '励志', '逆袭', '奋斗', '蜕变', '自我实现'],
    '情感': ['爱情', '友情', '亲情', '师生情', '兄弟情', '暗恋', '失恋'],
    '冒险': ['冒险', '探险', '寻宝', '旅行', '挑战', '求生', '探索'],
    '权谋': ['权谋', '政治', '商战', '宫斗', '智斗', '阴谋', '策略'],
    '治愈': ['治愈', '温馨', '日常', '生活', '家庭', '美食', '田园'],
    '特殊': ['复仇', '重生', '系统', '金手指', '快穿', '无限流', '穿书'],
  },
  '风格标签': {
    '轻松': ['轻松愉快', '幽默诙谐', '搞笑', '沙雕', '甜宠', '治愈'],
    '严肃': ['严肃深刻', '文艺抒情', '哲学思辨', '现实主义', '批判'],
    '热血': ['热血激昂', '燃', '激情', '战斗', '竞技', '冒险'],
    '温馨': ['温馨治愈', '小清新', '治愈系', '温暖', '日常'],
    '黑暗': ['黑暗压抑', '虐心', '悲剧', '沉重', '现实', '残酷'],
  },
  '受众标签': {
    '年龄': ['儿童向', '青少年', '成年人', '全年龄'],
    '性别': ['女性向', '男性向', '中性向'],
    '偏好': ['小白文', '老白文', '深度文', '爽文', '文青文', '快节奏', '慢节奏'],
  },
} as const;

export const TAG_WEIGHTS: TagWeights = {
  '类型标签': 0.4,
  '主题标签': 0.3,
  '风格标签': 0.2,
  '受众标签': 0.1,
} as const;

export const TAG_COMPATIBILITY_MATRIX: CompatibilityMatrix = {
  '都市': {
    '职场': 0.9, '校园': 0.8, '娱乐圈': 0.7, '商战': 0.8,
    '成长': 0.8, '爱情': 0.9, '励志': 0.8, '现实主义': 0.7,
  },
  '玄幻': {
    '修仙': 0.9, '异世界': 0.8, '系统': 0.7, '重生': 0.6,
    '冒险': 0.9, '热血': 0.8, '成长': 0.7, '爽文': 0.8,
  },
  '悬疑': {
    '推理': 0.9, '犯罪': 0.8, '恐怖': 0.7, '灵异': 0.6,
    '智斗': 0.8, '严肃': 0.7, '成年人': 0.8,
  },
  '言情': {
    '甜宠': 0.9, '虐恋': 0.7, '校园': 0.8, '职场': 0.6,
    '爱情': 0.9, '治愈': 0.7, '女性向': 0.9,
  },
  '历史': {
    '宫廷': 0.9, '武侠': 0.7, '架空': 0.8,
    '权谋': 0.8, '严肃': 0.7, '文艺': 0.6,
  },
  '科幻': {
    '未来': 0.9, '星际': 0.8, '机甲': 0.7,
    '探索': 0.8, '哲学': 0.6, '严肃': 0.7,
  },
};

export const POPULAR_TAG_COMBINATIONS: PopularCombination[] = [
  {
    name: '都市系统爽文',
    tags: ['都市', '系统', '逆袭', '爽文'],
    popularity: 0.9,
    success_rate: 0.85,
  },
  {
    name: '玄幻修仙',
    tags: ['玄幻', '修仙', '热血', '冒险'],
    popularity: 0.95,
    success_rate: 0.9,
  },
  {
    name: '校园甜宠',
    tags: ['校园', '甜宠', '爱情', '治愈'],
    popularity: 0.8,
    success_rate: 0.8,
  },
];

// ── Helpers ────────────────────────────────────────────────────────────

/** Collect all tags from all categories into a flat set. */
export function getAllTags(): string[] {
  const tags = new Set<string>();
  for (const category of Object.values(TAG_CATEGORIES)) {
    const subTagList: string[][] = Object.values(category);
    for (const subTags of subTagList) {
      for (const tag of subTags) {
        tags.add(tag);
      }
    }
  }
  return [...tags];
}

/** Get all tags for a specific category. */
export function getTagsByCategory(category: TagCategoryName): string[] {
  const cat = TAG_CATEGORIES[category];
  const result: string[] = [];
  for (const subTags of Object.values(cat)) {
    result.push(...subTags);
  }
  return result;
}

/**
 * Calculate the compatibility score between a type/genre tag and a set of other tags.
 * Returns a value between 0 and 1.
 */
export function calculateTagCompatibility(
  typeTag: string,
  otherTags: string[],
): number {
  const compat = TAG_COMPATIBILITY_MATRIX[typeTag];
  if (!compat) return 0.5;

  if (otherTags.length === 0) return 0.5;

  let total = 0;
  let count = 0;
  for (const tag of otherTags) {
    if (tag in compat) {
      total += compat[tag];
      count++;
    }
  }
  return count > 0 ? total / count : 0.5;
}

/** Calculate an overall compatibility score for a set of tag scores. */
export function calculateOverallTagCompatibility(scores: TagScores): number {
  if (scores.type_tags.length === 0) return 0.5;

  const allOther = [
    ...scores.theme_tags,
    ...scores.style_tags,
    ...scores.audience_tags,
  ];

  let total = 0;
  for (const typeTag of scores.type_tags) {
    total += calculateTagCompatibility(typeTag, allOther);
  }
  return total / scores.type_tags.length;
}

// ── Builder ────────────────────────────────────────────────────────────

/**
 * Build the tag taxonomy section of a system prompt.
 * Injects the full tag categories, weights, and recommendations guidance.
 */
export function buildTagPromptSegment(options?: {
  includeCompatibility?: boolean;
  includePopular?: boolean;
}): string {
  const opt = { includeCompatibility: true, includePopular: true, ...options };

  let segment = '【标签体系】\n\n';
  segment += '可选的标签分类及子类：\n';

  for (const [category, subcategories] of Object.entries(TAG_CATEGORIES)) {
    segment += `\n【${category}】（权重 ${TAG_WEIGHTS[category as TagCategoryName]}）\n`;
    const subcatEntries: [string, string[]][] = Object.entries(subcategories);
    for (const [subcat, tags] of subcatEntries) {
      segment += `  ${subcat}：${tags.join('、')}\n`;
    }
  }

  segment += '\n推荐原则：\n';
  segment += '1. 根据用户需求精准匹配标签\n';
  segment += '2. 考虑标签兼容性和组合效果\n';
  segment += '3. 每个分类推荐2-4个最合适的标签\n';
  segment += '4. 确保标签组合能形成完整的故事框架\n';
  segment += '5. 考虑目标受众的喜好和市场趋势\n';

  if (opt.includeCompatibility) {
    segment += '\n标签兼容性参考（主要类型与其他标签的兼容度，0-1）：\n';
    for (const [typeTag, compatMap] of Object.entries(TAG_COMPATIBILITY_MATRIX)) {
      const pairs = Object.entries(compatMap)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([tag, score]) => `${tag}(${score})`)
        .join(' ');
      segment += `  ${typeTag}：${pairs}\n`;
    }
  }

  if (opt.includePopular) {
    segment += '\n热门标签组合参考：\n';
    for (const combo of POPULAR_TAG_COMBINATIONS) {
      segment += `  【${combo.name}】${combo.tags.join('、')}（热度${combo.popularity}，成功率${combo.success_rate}）\n`;
    }
  }

  return segment;
}
