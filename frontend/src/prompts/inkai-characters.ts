/**
 * InkAI character creation knowledge base.
 * Extracted from InkAI-main/inkai/agents/character_creator.py
 *
 * Big Five personality model, profession archetypes, relationship types,
 * character arc templates.
 */

// ── Types ──────────────────────────────────────────────────────────────

export type BigFiveTrait =
  | '开放性'
  | '尽责性'
  | '外向性'
  | '宜人性'
  | '神经质';

export type TraitLevel = '高' | '低';

export interface BigFiveTraits {
  开放性: { '高': string[]; '低': string[] };
  尽责性: { '高': string[]; '低': string[] };
  外向性: { '高': string[]; '低': string[] };
  宜人性: { '高': string[]; '低': string[] };
  神经质: { '高': string[]; '低': string[] };
}

export interface ProfessionInfo {
  skills: string[];
  personalityTendencies: string[];
  commonMotivations: string[];
  typicalFears: string[];
}

export type ProfessionName =
  | '程序员'
  | '医生'
  | '教师'
  | '企业家'
  | '修行者'
  | '学生'
  | '白领'
  | '普通人';

export interface BigFiveScores {
  openness: number;
  conscientiousness: number;
  extraversion: number;
  agreeableness: number;
  neuroticism: number;
}

export interface CharacterArchetype {
  name: string;
  description: string;
}

export interface RelationshipNetwork {
  family: {
    parents: string;
    siblings: string;
    other_family: string;
  };
  social: {
    best_friend: string;
    mentor: string;
    rival: string;
    colleagues: string;
  };
  romantic: {
    current_status: string;
    past_relationships: string;
    ideal_partner: string;
  };
  special: {
    enemy: string;
    protector: string;
    mysterious_connection: string;
  };
}

export interface CharacterArc {
  starting_point: {
    emotional_state: string;
    skill_level: string;
    worldview: string;
    relationships_status: string;
  };
  growth_path: {
    key_challenges: string[];
    learning_moments: string[];
    skill_development: string;
    emotional_growth: string;
  };
  transformation: {
    internal_change: string;
    external_change: string;
    new_abilities: string;
    resolved_conflicts: string;
  };
  end_point: {
    achieved_goals: string;
    new_understanding: string;
    changed_relationships: string;
    future_potential: string;
  };
  arc_type?: string;
  focus?: string;
}

// ── Data ───────────────────────────────────────────────────────────────

export const BIG_FIVE_TRAITS: BigFiveTraits = {
  '开放性': {
    '高': ['富有想象力', '好奇心强', '喜欢新体验', '创造性', '思维开放'],
    '低': ['传统保守', '实用主义', '谨慎', '循规蹈矩', '现实主义'],
  },
  '尽责性': {
    '高': ['有组织', '负责任', '自律', '目标导向', '勤奋'],
    '低': ['随性', '灵活', '自发', '适应性强', '不拘小节'],
  },
  '外向性': {
    '高': ['健谈', '活力充沛', '社交', '乐观', '主动'],
    '低': ['内向', '安静', '独立', '深思熟虑', '谨慎'],
  },
  '宜人性': {
    '高': ['合作', '信任他人', '慷慨', '同情心', '友善'],
    '低': ['竞争性', '怀疑', '直率', '独立', '批判性'],
  },
  '神经质': {
    '高': ['情绪敏感', '焦虑', '情绪波动', '紧张', '易受压力影响'],
    '低': ['情绪稳定', '平静', '自信', '放松', '抗压能力强'],
  },
};

export const PROFESSION_TRAITS: Record<ProfessionName, ProfessionInfo> = {
  '程序员': {
    skills: ['编程', '逻辑思维', '问题解决', '系统设计'],
    personalityTendencies: ['内向', '专注', '细致', '理性'],
    commonMotivations: ['技术追求', '创新欲望', '完美主义'],
    typicalFears: ['技术落后', '项目失败', '沟通困难'],
  },
  '医生': {
    skills: ['医学知识', '诊断能力', '决策能力', '沟通技巧'],
    personalityTendencies: ['负责任', '细心', '冷静', '同情心'],
    commonMotivations: ['救死扶伤', '知识追求', '社会认可'],
    typicalFears: ['误诊', '失去病人', '医疗事故'],
  },
  '教师': {
    skills: ['教学能力', '沟通技巧', '知识传授', '课堂管理'],
    personalityTendencies: ['耐心', '友善', '负责', '开放'],
    commonMotivations: ['教育理想', '知识传播', '学生成长'],
    typicalFears: ['教学失败', '学生不理解', '知识过时'],
  },
  '企业家': {
    skills: ['商业洞察', '领导能力', '风险评估', '资源整合'],
    personalityTendencies: ['外向', '冒险', '自信', '进取'],
    commonMotivations: ['成功欲望', '财富积累', '影响力'],
    typicalFears: ['失败', '破产', '失去控制'],
  },
  '修行者': {
    skills: ['修炼', '战斗技巧', '冥想', '炼丹炼器'],
    personalityTendencies: ['坚毅', '专注', '超然', '执着'],
    commonMotivations: ['长生', '变强', '守护', '飞升'],
    typicalFears: ['心魔', '修为停滞', '天人五衰'],
  },
  '学生': {
    skills: ['学习', '考试', '社交', '信息收集'],
    personalityTendencies: ['好奇心强', '适应力好', '热情', '可塑性强'],
    commonMotivations: ['成长', '认可', '探索', '证明自己'],
    typicalFears: ['失败', '被轻视', '落后于人'],
  },
  '白领': {
    skills: ['办公技能', '沟通协调', '时间管理', '数据分析'],
    personalityTendencies: ['谨慎', '有条理', '温和', '务实'],
    commonMotivations: ['升职加薪', '稳定', '平衡生活'],
    typicalFears: ['失业', '能力不足', '职场政治'],
  },
  '普通人': {
    skills: ['生活技能', '人际交往', '适应能力'],
    personalityTendencies: ['普通', '真实', '接地气', '可塑性强'],
    commonMotivations: ['幸福生活', '家人安全', '自我实现'],
    typicalFears: ['失去', '未知', '变化'],
  },
};

export const CHARACTER_ARCHETYPES: CharacterArchetype[] = [
  { name: '英雄', description: '勇敢、正义、有使命感，通常是故事的核心' },
  { name: '导师', description: '智慧、经验丰富，为主角提供指导' },
  { name: '盟友', description: '忠诚、支持主角，共同面对挑战' },
  { name: '守门人', description: '设置障碍，考验主角的决心和能力' },
  { name: '变形者', description: '多变、难以预测，增加故事复杂性' },
  { name: '阴影', description: '主角的对立面，代表内心黑暗或外在威胁' },
  { name: '小丑', description: '幽默、轻松，缓解紧张气氛' },
  { name: '无辜者', description: '纯真、需要保护，激发主角的保护欲' },
];

export const RELATIONSHIP_FUNCTIONS: Record<string, string> = {
  '导师': '提供指导和智慧，帮助主角成长',
  '朋友': '提供支持和陪伴，共同面对挑战',
  '敌人': '制造冲突和障碍，推动情节发展',
  '恋人': '提供情感支持，增加情感线索',
  '竞争对手': '激发主角潜力，提供成长动力',
  '家人': '提供背景和动机，影响主角决策',
};

// ── Helpers ────────────────────────────────────────────────────────────

/**
 * Analyze Big Five personality scores (1-5) and get trait descriptions.
 */
export function analyzeBigFive(scores: BigFiveScores): {
  summary: string[];
  strengths: string[];
  weaknesses: string[];
} {
  const summary: string[] = [];
  const strengths: string[] = [];
  const weaknesses: string[] = [];

  const entries: [string, number, string][] = [
    ['开放性', scores.openness, 'openness'],
    ['尽责性', scores.conscientiousness, 'conscientiousness'],
    ['外向性', scores.extraversion, 'extraversion'],
    ['宜人性', scores.agreeableness, 'agreeableness'],
    ['神经质', scores.neuroticism, 'neuroticism'],
  ];

  for (const [traitCn, score] of entries) {
    const level: TraitLevel | null = score >= 4 ? '高' : score <= 2 ? '低' : null;
    if (!level) continue;

    const descriptors = BIG_FIVE_TRAITS[traitCn as BigFiveTrait][level] ?? [];
    summary.push(...descriptors.slice(0, 2));

    if (traitCn !== '神经质' && level === '高') {
      strengths.push(...descriptors.slice(0, 1));
    } else if (traitCn === '神经质' && level === '高') {
      weaknesses.push(...descriptors.slice(0, 1));
    }
  }

  return { summary, strengths, weaknesses };
}

/** Recommend a profession based on genre and theme tags. */
export function recommendProfession(
  typeTags: string[],
  themeTags: string[],
): ProfessionName {
  if (typeTags.includes('都市')) {
    if (themeTags.includes('系统') || themeTags.includes('逆袭')) return '程序员';
    if (typeTags.includes('商战')) return '企业家';
    return '白领';
  }
  if (typeTags.includes('医疗')) return '医生';
  if (typeTags.includes('校园')) return '学生';
  if (typeTags.includes('玄幻') || typeTags.includes('修仙')) return '修行者';
  return '普通人';
}

/** Recommend Big Five personality trait levels based on style/theme tags. */
export function recommendPersonalityTraits(
  styleTags: string[],
  themeTags: string[],
): Record<BigFiveTrait, string> {
  const traits: Record<string, string> = {
    '开放性': '中等',
    '尽责性': '中等',
    '外向性': '中等',
    '宜人性': '中等',
    '神经质': '中等',
  };

  if (styleTags.includes('轻松愉快')) {
    traits['外向性'] = '高';
    traits['神经质'] = '低';
  } else if (styleTags.includes('严肃深刻')) {
    traits['开放性'] = '高';
    traits['外向性'] = '低';
  }

  if (themeTags.includes('成长')) {
    traits['开放性'] = '高';
    traits['尽责性'] = '高';
  } else if (themeTags.includes('冒险')) {
    traits['开放性'] = '高';
    traits['外向性'] = '高';
  }

  return traits as Record<BigFiveTrait, string>;
}

// ── Builder ────────────────────────────────────────────────────────────

/**
 * Build the character model section of a system prompt.
 * Injects Big Five personality model, profession traits, archetypes,
 * and character design principles.
 */
export function buildCharacterPromptSegment(): string {
  let segment = '【角色模型】\n\n';
  segment += '使用 Big Five 人格模型（OCEAN）设计角色性格：\n';

  for (const [trait, levels] of Object.entries(BIG_FIVE_TRAITS)) {
    segment += `  ${trait}：高→${levels['高'].join('、')}\n`;
    segment += `          低→${levels['低'].join('、')}\n`;
  }

  segment += '\n职业特征库（包含性格倾向、动机、恐惧）：\n';
  for (const [profession, info] of Object.entries(PROFESSION_TRAITS)) {
    segment += `  【${profession}】\n`;
    segment += `    技能：${info.skills.join('、')}\n`;
    segment += `    性格倾向：${info.personalityTendencies.join('、')}\n`;
    segment += `    常见动机：${info.commonMotivations.join('、')}\n`;
    segment += `    典型恐惧：${info.typicalFears.join('、')}\n`;
  }

  segment += '\n角色原型：\n';
  for (const archetype of CHARACTER_ARCHETYPES) {
    segment += `  ${archetype.name}：${archetype.description}\n`;
  }

  segment += '\n角色设计原则：\n';
  segment += '1. 基于Big Five人格模型设计性格\n';
  segment += '2. 职业特征要与性格相符\n';
  segment += '3. 动机和恐惧要有深层心理依据\n';
  segment += '4. 外貌描述要体现内在性格\n';
  segment += '5. 技能设定要合理可信\n';
  segment += '6. 为后续的成长弧线留下空间\n';
  segment += '7. 角色要有独立的目标和动机\n';
  segment += '8. 配角应与主角形成互补或对比\n';

  return segment;
}
