"""
拆书分析专用 Prompt 模板。
参考 oh-story-claudecode story-long-analyze 的 Stage 0-6 方法论。
"""

# ── Stage 0: 概要提取 ──────────────────────────────────

STAGE_0_SUMMARY_SYSTEM = """你是小说结构分析师。你的任务是从小说文本中提取基本信息。

**输出要求**：严格返回 JSON 格式，不要包含任何其他文字。

{
  "title": "从文本中识别的小说标题",
  "genre": "题材类型（玄幻/都市/言情/悬疑/科幻/历史/武侠/仙侠/游戏/军事/其他）",
  "estimated_total_chapters": 从章节分隔符估算的总章数,
  "estimated_total_words": 从章节字数估算的总字数（万为单位，如 45.2）,
  "chapter_index": [
    {"chapter_number": 1, "title": "第1章标题", "word_count": 字数},
    ...
  ],
  "thin_summary": "200字以内，基于章节标题+抽样内容归纳的核心驱动+主角名+大致设定"
}
"""

STAGE_0_SUMMARY_USER = """请分析以下小说文本，提取基本信息和章节结构。

{chapter_text}

仅返回 JSON，不要包含任何解释。"""

# ── Stage 1: 黄金三章深度拆解 ──────────────────────────

STAGE_1_GOLDEN_CHAPTERS_SYSTEM = """你是网络小说深度分析专家。你的任务是对小说的前三章进行深度拆解。

**输出要求**：严格返回 JSON 格式。

{
  "chapters": {
    "chapter_1": {
      "word_count": "字数",
      "core_event": "一句话概括核心事件",
      "opening_hook": {
        "type": "悬念/冲突/反差/信息差/代入感",
        "technique": "手法描述",
        "effect": "强/中/弱",
        "reason": "原因"
      },
      "character_intro": [
        {"name": "角色名", "impression": "第一印象", "method": "直接描写/对话/行为/他人评价"}
      ],
      "worldbuilding": {
        "revealed": ["已透露的信息"],
        "hidden": ["被隐藏的信息"],
        "method": "对话/旁白/事件"
      },
      "structure": [
        {"segment": "段落范围", "function": "铺垫/冲突/爽点/收尾", "word_count": "字数"}
      ],
      "pleasure_points": {
        "type": "装逼打脸/逆袭反转/获得机缘/信息差碾压/情感满足",
        "buildup_words": "铺垫字数",
        "release_words": "释放字数",
        "ratio": "铺放比",
        "emotion_curve": "情绪曲线描述"
      },
      "chapter_end_hook": {
        "type": "悬念/冲突/期待",
        "content": "章尾钩子内容",
        "effect": "强/中/弱"
      },
      "learnable_elements": ["可借鉴要素1", "可借鉴要素2"]
    },
    "chapter_2": "同上结构",
    "chapter_3": "同上结构"
  },
  "golden_three_rating": {
    "opening_hook": {"score": "1-5", "comment": "说明"},
    "protagonist_building": {"score": "1-5", "comment": "说明"},
    "pleasure_design": {"score": "1-5", "comment": "说明"},
    "worldbuilding": {"score": "1-5", "comment": "说明"},
    "chapter_end_hooks": {"score": "1-5", "comment": "说明"}
  },
  "early_learnable": ["黄金三章可借鉴要素汇总，3-5条"]
}
"""

STAGE_1_GOLDEN_CHAPTERS_USER = """请对以下小说的前三章进行深度拆解。

{chapter_text}

仅返回 JSON，不要包含任何解释。"""



# --- Stage 0.5: 故事框架识别 ---

STAGE_0_5_FRAMEWORK_SYSTEM = """你是网络小说结构分析师。你的任务是从章节标题和概要中识别小说的故事框架类型。

框架类型定义：
- 升级流：等级体系清晰，按境界阶段分段，每个境界有对应的冲突和目标
- 复仇线：核心矛盾是复仇，目标明确，按仇家/复仇阶段推进
- 日常单元：每卷独立故事，弱连续性，按卷/单元划分
- 多线交织：多视角/多时间线，按线索划分，交叉点单独标记
- 蜕变成长：主角内在变化为主线，按成长阶段划分

输出要求：严格返回 JSON 格式。
{
  "framework_type": "升级流/复仇线/日常单元/多线交织/蜕变成长",
  "confidence": 0.0-1.0,
  "reasoning": "识别依据（100字内）",
  "stage_boundaries": [
    {"stage": "阶段名称", "chapters": "第1-15章", "description": "阶段描述"}
  ],
  "suggested_chunk_size": "建议的分块章节数（默认60，长篇幅可适当增大）"
}
"""

STAGE_0_5_FRAMEWORK_USER = """请分析以下小说的章节信息，识别故事框架类型。

章节概要：{thin_summary}

章节列表（前80章+后40章）：
{chapter_titles}

仅返回 JSON，不要包含任何解释。"""



# --- Stage 1: 快速预览报告 ---

STAGE_1_PREVIEW_REPORT_SYSTEM = """你是小说分析报告撰写专家。基于黄金三章深度拆解数据，撰写一份快速预览报告。

输出要求：返回 Markdown 格式的快速预览报告，不要包含 JSON 包装。

报告结构：
# 快速预览：{书名}

## 基本信息
- 书名 | 题材 | 预估总章节 | 预估总字数

## 框架识别
- 故事框架类型 | 置信度 | 识别依据

## 黄金三章评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 开篇钩子 | X/5 | ... |
| 主角塑造 | X/5 | ... |
| 爽点设计 | X/5 | ... |
| 世界观铺设 | X/5 | ... |
| 章尾悬念 | X/5 | ... |

## 可借鉴要素
（3-5条，从黄金三章中提取的写作技巧）

## 预估耗时
全量拆解（Stage 2-6）预计耗时：{estimated_time}
"""

# ── Stage 2: 逐章摘要 ──────────────────────────────────

STAGE_2_CHAPTER_SUMMARY_SYSTEM = """你是小说章节分析专家。你需要对单章小说内容进行结构化摘要提取。

**输出要求**：严格返回 JSON 格式。

{
  "chapter_number": "章号",
  "one_liner": "100-300字因果链叙事概括",
  "key_events": [
    {"order": 1, "description": "事件描述", "type": "转折点/信息揭示/冲突/解决/铺垫/行动/对话/状态变化"}
  ],
  "characters_appeared": [
    {"name": "全名", "level": "major/supporting/minor", "function": "本章功能", "aliases": ["别名"]}
  ],
  "theme_tags": ["爱情", "权力"],
  "tone": "紧张/轻松/悲伤/热血/爽/甜/温馨/恐怖/压抑/其他",
  "plot_progress": "大转折/日常过渡/铺垫伏笔",
  "plot_points": [
    {
      "id": "P1",
      "type": "转折点/信息揭示/冲突/解决/铺垫/行动/对话/状态变化",
      "description": "客观白描，只记录发生了什么",
      "quote": "原文引用（≤400字）",
      "characters": ["全名"],
      "location": "地点",
      "key_items": ["关键物品"],
      "time_marker": "相对时间（次日、半月后、同时）",
      "tone": "紧张"
    }
  ],
  "key_info_and_techniques": [
    {
      "key_info": "本章必须传递的剧情信息",
      "how_expanded": "作者如何扩写成场景",
      "technique": "铺垫后置/反应层放大/信息差/对比锚点/延迟揭示/身体反应/小目标嵌套/其他",
      "emotion_effect": "对读者情绪的作用",
      "reusable_reminder": "可复用提醒（只抽象逻辑，不照搬具体桥段）"
    }
  ]
}
"""

STAGE_2_CHAPTER_SUMMARY_USER = """请分析以下小说章节，提取结构化摘要。

章节编号：第{chapter_number}章 {chapter_title}
章节字数：{word_count}

{chapter_text}

仅返回 JSON，不要包含任何解释。"""



# --- Stage 2: 增强版逐章摘要（含关键信息与扩写技法）---

STAGE_2_ENHANCED_SUMMARY_SYSTEM = """你是网络小说章节深度分析专家。对每一章进行三层提取：

1. 章节摘要（100-200字因果链）
2. 情节点提取（按字数密度：150-200字/个情节点，每章10-40个）
3. 关键信息与扩写技法

输出要求：严格返回 JSON 格式。
{
  "chapter_number": "章号",
  "summary": "100-200字因果链摘要",
  "key_events": ["事件1", "事件2", "事件3"],
  "characters_appeared": ["角色名"],
  "theme_tags": ["标签"],
  "chapter_tone": "基调",
  "plot_progression": "大转折/日常过渡/铺垫伏笔",
  "key_info": [
    {
      "info": "关键信息/剧情走向",
      "expansion": "原文如何扩写",
      "technique": "铺垫后置/反应层放大/信息差/对比锚点/延迟揭示/身体反应/小目标嵌套/其他",
      "emotion_effect": "好奇/期待/压抑/爽/心疼/紧张/甜/热血"
    }
  ],
  "characters_detail": [
    {
      "name": "角色名",
      "importance": "major/supporting/minor",
      "new_info": "本章新信息",
      "aliases": ["别名"]
    }
  ]
}
"""

STAGE_2_ENHANCED_SUMMARY_USER = """分析以下章节：

第{chapter_number}章 {chapter_title}（{word_count}字）

{chapter_text}

仅返回 JSON，不要包含任何解释。"""

# ── Stage 3: 聚合分析 ──────────────────────────────────

STAGE_3_AGGREGATION_SYSTEM = """你是小说结构聚合分析师。你需要基于全部章节摘要进行跨章节聚合分析。

**输出要求**：严格返回 JSON 格式。

{
  "story_framework": {
    "type": "升级流/复仇线/日常单元/多线交织/蜕变成长",
    "description": "框架识别说明"
  },
  "plot_lines": [
    {
      "title": "剧情线标题（15字内）",
      "summary": "150-300字因果链",
      "core_goal": "具体、可衡量的戏剧目标",
      "core_conflict": "冲突对象+冲突事件",
      "type": "主线/爱情/成长/复仇/寻宝/悬疑/战斗/权谋/修炼/危机/谜团/日常/其他",
      "themes": ["主题1", "主题2"],
      "chapter_range": "第1-15章",
      "bridge_tags": ["桥段标签1"]
    }
  ],
  "story_line_summary": "故事线整体摘要",
  "rhythm": {
    "key_info_progression": [
      {"chapter": 1, "info_released": "释放的关键信息", "how_accumulated": "如何累积"}
    ],
    "emotion_peaks": [
      {"chapter": 5, "type": "爽点/虐点/期待点", "buildup": "铺垫方式", "release": "释放方式", "aftermath": "余波"}
    ],
    "rhythm_cycles": [
      {"cycle": 1, "pattern": "铺垫→释放→衔接", "chapters": "1-3", "description": "描述"}
    ]
  },
  "emotion_modules": {
    "reader_demands": [
      {"demand": "读者需求", "how_fulfilled": "如何满足"}
    ],
    "emotion_engines": [
      {"engine": "情绪引擎", "mechanism": "运作机制"}
    ],
    "reusable_modules": [
      {"module": "可复现模块", "condition": "使用条件", "risk": "风险边界"}
    ]
  },
  "merged_characters": {
    "protagonist": {"name": "主角名", "aliases": ["别名"], "chapters_appeared": [1,2,3]},
    "antagonist": {"name": "反派名", "aliases": [], "chapters_appeared": [1,2]},
    "core_supporting": [{"name": "配角名", "chapters_appeared": [1,2]}],
    "functional": [{"name": "功能角色", "chapters_appeared": [1]}]
  },
  "orphan_plots": [
    {"content": "散落情节", "related_chapters": [1], "disposition": "归类建议"}
  ]
}
"""

STAGE_3_AGGREGATION_USER = """请基于以下全部章节摘要进行聚合分析。

{all_chapter_summaries}

仅返回 JSON，不要包含任何解释。"""

# ── Stage 4: 设定+关系 ──────────────────────────────────

STAGE_4_SETTINGS_SYSTEM = """你是小说世界观与角色关系分析师。你需要提取世界观设定和角色关系。

**输出要求**：严格返回 JSON 格式。

{
  "worldbuilding": {
    "world_rules": [
      {"rule": "核心规则", "source_chapters": [1, 3], "description": "详细描述"}
    ],
    "power_system": {
      "name": "力量体系名称",
      "levels": ["等级1", "等级2"],
      "description": "体系描述",
      "source_chapters": [1, 2]
    },
    "geography": {
      "locations": [
        {"name": "地点名", "description": "描述", "source_chapters": [1]}
      ]
    },
    "cheat_ability": {
      "name": "金手指名称",
      "type": "系统/重生/穿越/天赋/血脉/传承/其他",
      "description": "描述",
      "source_chapters": [1, 2]
    },
    "factions": [
      {"name": "势力名", "type": "宗门/家族/国家/组织", "description": "描述", "source_chapters": [1, 2]}
    ],
    "special_settings": [
      {"setting": "特殊设定", "description": "描述", "source_chapters": [1]}
    ]
  },
  "character_profiles": [
    {
      "name": "角色名",
      "level": "protagonist/antagonist/core_supporting/functional",
      "identity": "身份",
      "core_traits": ["核心特质"],
      "abilities": "当前能力",
      "motivation": "核心动机",
      "weakness": "弱点/缺陷",
      "appearance_records": [
        {"chapter": 1, "event": "关键事件", "state_change": "状态变化"}
      ]
    }
  ],
  "character_relations": [
    {
      "pair": ["角色A", "角色B"],
      "essence": "关系本质",
      "evolution": [
        {"chapter": 1, "state": "状态A"},
        {"chapter": 5, "state": "状态B", "trigger": "触发事件"}
      ],
      "final_state": "最终状态",
      "implicit_inference": "隐含推断"
    }
  ]
}
"""

STAGE_4_SETTINGS_USER = """请基于以下章节摘要和角色数据，提取世界观设定和角色关系。

章节摘要：
{chapter_summaries}

角色数据：
{merged_characters}

仅返回 JSON，不要包含任何解释。"""

# ── Stage 5: 汇总报告 ──────────────────────────────────

STAGE_5_REPORT_SYSTEM = """你是小说分析报告撰写专家。你需要基于所有拆书数据撰写综合拆文报告。

**输出要求**：返回 Markdown 格式的完整拆文报告，不要包含 JSON 包装。

报告结构如下：

# 拆文报告：{书名}

## 基本信息
- 书名 | 题材 | 总章数 | 总字数 | 目标平台

## 读者需求与情绪引擎
（从情绪模块数据中提取，分析读者为什么被吸引、什么情绪推动了追读）

## 关键信息与扩写技法总览
（从章节摘要的关键信息与扩写技法中汇总，列出最有效的技法及其使用频率）

## 节奏与情绪触动点
（从节奏分析数据中提取，包含爽点清单、虐点清单、期待点清单，以及它们的铺垫→释放→余波模式）

## 可复现模块
（从情绪模块中提取，每个模块含使用条件、核心机制和风险边界）

## 黄金三章评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 开篇钩子 | X/5 | ... |
| 主角塑造 | X/5 | ... |
| 爽点设计 | X/5 | ... |
| 世界观铺设 | X/5 | ... |
| 章尾悬念 | X/5 | ... |

## 写作技巧清单
（汇总所有章节摘要中的技法，分类：一笔两用/延迟揭示/视角欺骗/对比锚点/行为循环/身体反应替代心理描写/跨章回扣）

## 写作手法清单（供 Agent 学习）
请额外提取一份 JSON 格式的写作手法清单，放在报告的「写作手法清单」章节中：

[
  {
    "technique": "手法名称",
    "category": "开篇钩子/角色塑造/爽点设计/章节结尾/对话手法/信息控制/节奏控制/反转设计/伏笔/情绪操控",
    "description": "手法描述",
    "examples": [
      {"chapter": 1, "context": "使用场景", "effect": "效果"}
    ],
    "reusable": true,
    "reuse_condition": "可复用的条件",
    "reuse_risk": "复用风险"
  }
]

## 全书概要
（500-1000字，情节感知型概要，覆盖全书核心冲突和主要转折）
"""

STAGE_5_REPORT_USER = """请基于以下拆书数据撰写综合拆文报告。

书名：{title}
题材：{genre}
总章数：{total_chapters}
总字数：{total_words}万

黄金三章数据：
{golden_chapters}

章节摘要数据：
{chapter_summaries}

角色数据：
{characters}

角色关系数据：
{character_relations}

剧情线数据：
{plot_lines}

节奏数据：
{rhythm}

情绪模块数据：
{emotion_modules}

世界观数据：
{worldbuilding}

仅返回 Markdown 格式报告。"""

# ── Stage 6: 文风分析 ──────────────────────────────────

STAGE_6_STYLE_SYSTEM = """你是小说文风分析专家。你需要分析小说的写作风格特征。

**输出要求**：严格返回 JSON 格式。

{
  "sentence_length": {
    "average": "平均句长（字）",
    "distribution": {"short": "短句占比", "medium": "中句占比", "long": "长句占比"},
    "pattern": "句长变化模式描述"
  },
  "punctuation": {
    "habits": ["标点使用习惯"],
    "dialogue_format": "对话格式描述"
  },
  "dialogue_subtext": {
    "pattern": "对话潜台词模式",
    "techniques": ["使用的技巧"]
  },
  "emotion_cycle": {
    "pattern": "情绪交替周期描述",
    "cycle_length": "平均周期长度（章）"
  },
  "exemplary_passages": [
    {
      "chapter": "章号",
      "purpose": "范例用途",
      "quote": "原文范例片段（≤500字）",
      "analysis": "文风分析"
    }
  ],
  "techniques": [
    {
      "technique": "手法名称",
      "category": "开篇钩子/角色塑造/爽点设计/章节结尾/对话手法/信息控制/节奏控制/反转设计/伏笔/情绪操控",
      "description": "手法描述",
      "examples": [
        {"chapter": 1, "context": "使用场景", "effect": "效果"}
      ],
      "reusable": true,
      "reuse_condition": "可复用的条件",
      "reuse_risk": "复用风险"
    }
  ],
  "generation_note": "生成记录"
}
"""

STAGE_6_STYLE_USER = """请分析以下小说的写作风格。

章节摘要数据：
{chapter_summaries}

黄金三章数据：
{golden_chapters_text}

原文采样：
{original_text_samples}

仅返回 JSON，不要包含任何解释。"""

# ── 快速预览报告模板 ──────────────────────────────────

QUICK_PREVIEW_TEMPLATE = """# 快速预览：{title}

> 基于黄金三章 + 全书概要的早期判断。
> 状态：已完成 Stage 0-1

## 基本信息
{title} | {genre} | {total_chapters}章 | {total_words}万字

## 黄金三章评分

| 维度 | 评分 | 说明 |
|------|------|------|
{ratings_table}

## 开篇判断
- 开篇钩子类型与效果：{opening_hook}
- 主角立人设手法：{protagonist_method}
- 世界观铺设方式：{worldbuilding_method}
- 黄金三章节奏：{rhythm_summary}

## 早期可借鉴点
{learnable_elements}

## 是否值得全量拆解 — 建议
{recommendation}
"""