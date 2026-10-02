"""
小说自动创作 v2 提示词模板模块。

本模块提供面向长篇网文平台的提示词模板构建函数，
按 prompt-architecture.md 定义的生成链路拆分提示词。
每个函数返回可直接用于 LLM 调用的格式化工带字符串。
"""

from __future__ import annotations

import json
from typing import Any


# ─── 系统提示词常量 ────────────────────────────────────────

SYSTEM_FRAMEWORK_V2 = """你是一位服务网文平台创作的小说策划编辑。
你的任务不是生成短篇故事，而是帮助用户规划可持续创作的长篇连载小说。

## 核心规则

1. 阶段结构不固定，不必强制三幕。请根据题材和故事体量自由
   决定分成几个主要阶段。
2. 核心矛盾不得在前几十章全部结束。主线冲突、角色成长、世
   界观揭秘都必须分阶段兑现。
3. 前期负责立局，中期负责升级扩盘，后期负责回收和终局。
4. 允许后半程章节规划更概括，但整体主线必须完整。

## 长篇节奏规则

1. 每卷都应包含冲突、回报和结尾钩子。
2. 不要把所有高潮集中在开头几十章，也不要把所有谜底一次性
   揭穿。
3. 角色成长、势力格局、感情线都需要留出持续发展的空间。
4. 如果题材天然适合多阶段多篇章展开，优先给出灵活的阶段结
   构而非固定模板。

## 平台导向规则

1. 开篇必须有事件而不只是设定。用情节而不是说明文来展示世
   界观。
2. 三章内要让读者明确主线牵引。读者必须知道主角要干什么、
   为什么干、有什么阻碍。
3. 十章内要有初步回报。主角需要获得第一次实质性成长、收获
   或阶段性胜利。
4. 免费期要持续提供追读动力。每章结尾留有悬念或期待点。

## 输出格式

- 必须输出合法的 JSON 对象。
- 不要输出 markdown 代码块包裹（不要 ```json）。
- 不要包含任何解释、说明或额外文字。
- 如果需要对某个字段做说明，使用字段内的注释字段。"""

SYSTEM_OPENING_PLAN = """你是一位网文开书策划专家。你的任务是分析已规划好的
故事框架，制定最有利于吸引读者的开篇方案。

## 核心原则

1. 平台感优先。你规划的每一个开篇细节都要符合所选平台的读
   者口味和追读习惯。
2. 抓人优先。网文的竞争从第一章第一段开始。读者没有耐心等
   到第五章才觉得好看。
3. 不要只有设定没有事件。设定应当通过角色的行动和冲突自然
   展现，而不是靠大段说明。
4. 免费章节（通常是前 20-30 章）必须有持续的追读动力，不能
   让读者在免费期弃书。

## 你必须规划的内容

1. 全书开篇爆点：第一章的第一个高潮事件是什么。
2. 前三章的钩子序列：每一章结尾用什么悬念拉住读者。
3. 前十章的追读节奏：介绍期的信息释放节奏、小高潮位置、
   初步回报时机。
4. 前二十章的大回报：免费期结束前最重要的剧情高潮或阶段性
   收获。

## 输出要求

- 必须输出合法的 JSON 对象。
- 不要输出 markdown 代码块包裹。
- 不要包含任何额外文字。"""

SYSTEM_VOLUME_PLANNER = """你是一位网文长篇节奏设计师。你的任务是规划整部小说
的卷结构，确保节奏合理、衔接自然、高潮迭起。

## 核心原则

1. 长篇节奏优先。每一卷都应当是整体故事的一个有机组成部分，
   而不是独立短篇的拼凑。
2. 卷与卷之间必须有衔接。前一卷的尾钩要能自然引出下一卷
   的核心冲突。
3. 高潮安排要有层次。不能每卷都写世界级决战，也不能连续多
   卷平淡如水。大高潮和小高潮交替出现。
4. 每卷都必须包含：核心冲突 -> 过程展开 -> 阶段性回报 ->
   结尾钩子。
5. 卷的长度不要求均匀。关键卷可以更长，过渡卷可以更短。

## 输出要求

- 必须输出合法的 JSON 对象。
- 不要输出 markdown 代码块包裹。
- 不要包含任何额外文字。"""

SYSTEM_CHAPTER_GOAL = """你是一位网文章节规划师。你的任务是为单章制定精确的
写作目标，确保每一章都在整体故事中发挥明确作用。

## 核心原则

1. 每一章都必须有明确的章节目标，知道这章要达成什么效果。
2. 每一章都必须推进主线。即使是日常或过渡章节，也要在角色
   关系、伏笔埋设或氛围营造上有所推进。
3. 角色关系变化是网文的核心驱动力之一。每一章都要体现至少
   一段关系的变化或进展。
4. 爽点是网文的生命线。每一章至少要有一个让读者感到"爽"
   的瞬间——不论是战力提升、智商碾压、情感进展还是解密
   时刻。
5. 悬念是追读的动力。每一章结尾都要留下让读者想点下一章的
   钩子。
6. 收尾钩子可以是剧情悬念，也可以是情感悬念或对话未完成。

## 你需要生成的字段

- goal: 本章要达成的一个核心目标
- plot_progress: 本章对主线的具体推进（列表）
- relationship_change: 本章发生的角色关系变化（列表）
- hook: 本章结尾的钩子，吸引读者追更
- payoff: 本章给读者的回报/爽点
- scene_suggestions: 建议本章包含的场景片段（列表）

## 输出要求

- 必须输出合法的 JSON 对象。
- 不要输出 markdown 代码块包裹。
- 不要包含任何额外文字。"""

SYSTEM_PUBLISHING = """你是一位网文出版策划专家。你的任务是根据已完成的故事
框架和内容，生成一整套投稿出版所需的多媒体。

## 核心原则

1. 书名必须吸引目标平台的读者群体。好的网文书名应该让读者
   一眼就知道这本书的类型和卖点。
2. 简介必须在 200 字内说清楚核心卖点。不要剧透太多，但要
   制造足够的阅读欲望。
3. 标签要精准匹配平台分类体系，帮助算法推荐到正确的读者
   群体。
4. 卖点文案要突出故事的独特性——和同类作品比，这本书有
   什么不可替代的吸引力。
5. 投稿摘要要简明扼要地说明故事规模、预计字数、更新频率和
   读者定位，帮助编辑快速判断作品价值。

## 输出要求

- 必须输出合法的 JSON 对象。
- 不要输出 markdown 代码块包裹。
- 不要包含任何额外文字。"""


# ─── 创作参数格式化辅助函数 ───────────────────────────────

_PLATFORM_MODE_MAP: dict[str, str] = {
    "qidian": "起点中文网",
    "zhulang": "逐浪小说",
    "qq": "QQ阅读",
    "zongheng": "纵横中文网",
    "chuangshi": "创世中文网",
    "ciweimao": "刺猬猫",
    "other": "其他平台",
}

# 读者群体映射表
_AUDIENCE_MODE_MAP: dict[str, str] = {
    "male": "男频",
    "female": "女频",
    "lightnovel": "轻小说",
    "all": "全年龄",
}

# 节奏模式映射表
_PACE_MODE_MAP: dict[str, str] = {
    "strong_hook": "强钩子快节奏",
    "steady": "稳健节奏",
    "warm": "慢热细腻",
}

# 目标长度映射表
_TARGET_LENGTH_MAP: dict[str, str] = {
    "short": "短篇（20-50万字）",
    "medium": "中篇（50-150万字）",
    "long": "长篇（150万字以上）",
}

# 创作目标映射表
_CREATION_GOAL_MAP: dict[str, str] = {
    "publish": "平台投稿出版",
    "practice": "练习练笔",
    "series": "系列作品（同一世界观多部）",
}


def _map_value(value: str | None, mapping: dict[str, str]) -> str:
    """将英文配置值映射为中文可读文本。"""
    if not value:
        return "未指定"
    return mapping.get(value.strip().lower(), value)


def build_consistent_profile_section(
    creative_profile: dict[str, Any] | None,
) -> str:
    """将创作参数（creative profile）格式化为提示词文本段。

    输出中文描述段落，包含平台模式、读者群体、节奏偏好、
    目标长度和创作目标等维度。
    """
    if not creative_profile:
        return "创作参数：未设置"

    platform = _map_value(
        creative_profile.get("platform_mode"), _PLATFORM_MODE_MAP
    )
    audience = _map_value(
        creative_profile.get("audience_mode"), _AUDIENCE_MODE_MAP
    )
    pace = _map_value(
        creative_profile.get("pace_mode"), _PACE_MODE_MAP
    )
    target_len = _map_value(
        creative_profile.get("target_length"), _TARGET_LENGTH_MAP
    )
    goal = _map_value(
        creative_profile.get("creation_goal"), _CREATION_GOAL_MAP
    )

    lines = ["## 创作参数配置"]
    lines.append(f"- 目标平台：{platform}")
    lines.append(f"- 读者群体：{audience}")
    lines.append(f"- 节奏偏好：{pace}")
    lines.append(f"- 目标长度：{target_len}")
    lines.append(f"- 创作目标：{goal}")

    # 可选的流派和附加说明
    genre = creative_profile.get("custom_genre") or creative_profile.get("genre")
    if genre:
        lines.append(f"- 流派：{genre}")

    return "\n".join(lines)


# ─── 框架生成 v2 提示词 ────────────────────────────────────

def build_framework_v2_prompt(
    description: str,
    creative_profile: dict[str, Any] | None,
) -> str:
    profile_section = build_consistent_profile_section(creative_profile)

    output_schema = """## JSON 输出结构

{
  "description": "故事描述文本",
  "tags": {
    "type": "小说类型（奇幻/科幻/悬疑/言情/武侠等）",
    "theme": "核心主题（成长/复仇/救赎等）",
    "style": "写作风格（细腻温情/磅礴大气等）",
    "audience": "目标读者（青少年/成人/全年龄等）"
  },
  "characters": [
    {
      "name": "角色名",
      "role": "主角/反派/导师/伙伴/恋爱对象",
      "big_five": {
        "openness": 1-10,
        "conscientiousness": 1-10,
        "extraversion": 1-10,
        "agreeableness": 1-10,
        "neuroticism": 1-10
      },
      "arc": {
        "start": "初始状态描述",
        "middle": "转折状态描述",
        "end": "最终状态描述"
      },
      "relationships": [
        {"to": "角色名", "type": "关系类型", "description": "描述"}
      ]
    }
  ],
  "outline": {
    "stages": [
      {
        "stage": 1,
        "title": "阶段标题",
        "summary": "阶段概茫",
        "key_events": ["关键事件1"],
        "chapters": [
          {"chapter_number": 1, "title": "章节标题",
           "key_events": ["事件"]}
        ]
      }
    ],
    "themes": ["主题线索1"],
    "foreshadowing": ["伏笔1"]
  },
  "chapters": [
    {
      "chapter_number": 1,
      "title": "章节标题",
      "act": "所属阶段标识",
      "key_events": ["关键事件"]
    }
  ],
  "volumes": [
    {
      "volume_number": 1,
      "title": "卷标题",
      "summary": "卷概要",
      "climax": "卷高潮描述",
      "hook": "卷尾钩子"
    }
  ]
}

注意：
- stages（阶段）数量不固定，请根据题材决定，不必三幕。
- chapters 须覆盖完整主线，前半段可更具体。
- volumes 可选，用于辅助长篇卷结构规划。"""

    return (
        f"## 故事描述\n\n{description}\n\n"
        f"{profile_section}\n\n"
        f"{output_schema}"
    )


# ─── 开书方案提示词 ────────────────────────────────────────

def build_opening_plan_prompt(
    framework: dict[str, Any],
    characters: list[dict[str, Any]],
    creative_profile: dict[str, Any] | None,
) -> str:
    profile_section = build_consistent_profile_section(creative_profile)

    framework_summary_parts = []
    if framework.get("description"):
        framework_summary_parts.append(
            f"故事描述：{framework['description']}"
        )
    if framework.get("tags"):
        framework_summary_parts.append(
            f"标签：{json.dumps(framework['tags'], ensure_ascii=False)}"
        )
    if framework.get("outline"):
        outline = framework["outline"]
        stages = outline.get("stages") or outline.get("three_acts")
        if stages:
            stage_summaries = []
            for s in stages:
                title = s.get("title", "")
                summary = s.get("summary", "")
                stage_summaries.append(f"{title}：{summary}")
            framework_summary_parts.append(
                "阶段概要：\n" + "\n".join(stage_summaries)
            )

    framework_text = "\n\n".join(framework_summary_parts)

    character_lines = []
    for ch in characters[:6]:
        name = ch.get("name", "未命名")
        role = ch.get("role", "")
        character_lines.append(f"- {name}（{role}）")
    character_text = "\n".join(character_lines) if character_lines else "无"

    output_schema = """## JSON 输出结构

{
  "book_hook": "全书最核心的卖点/爆点概括",
  "chapter_1_hook": "第一章的爆点事件描述",
  "chapter_3_hook": "前三章的悬念链条和追读动力",
  "chapter_10_payoff": "前十章的初步回报和阶段性胜利",
  "chapter_20_climax": "前二十章的大高潮/免费期收尾高潮",
  "opening_notes": [
    "开篇注意事项1",
    "开篇注意事项2"
  ]
}"""

    return (
        f"## 故事框架\n\n{framework_text}\n\n"
        f"## 核心角色\n\n{character_text}\n\n"
        f"{profile_section}\n\n"
        f"{output_schema}"
    )


# ─── 卷规划提示词 ──────────────────────────────────────────

def build_volume_prompt(
    framework: dict[str, Any],
    chapters: list[dict[str, Any]],
    creative_profile: dict[str, Any] | None,
) -> str:
    profile_section = build_consistent_profile_section(creative_profile)

    parts = []
    if framework.get("description"):
        parts.append(f"故事描述：{framework['description']}")
    if framework.get("outline"):
        outline = framework["outline"]
        themes = outline.get("themes", [])
        if themes:
            parts.append(f"主题线索：{'、'.join(themes)}")
        foreshadowing = outline.get("foreshadowing", [])
        if foreshadowing:
            parts.append(f"伏笔列表：{json.dumps(foreshadowing, ensure_ascii=False)}")

    framework_text = "\n".join(parts)

    chapter_text_parts = []
    for ch in chapters:
        cn = ch.get("chapter_number", "?")
        title = ch.get("title", "未命名")
        events = ch.get("key_events", [])
        events_str = "；".join(events) if events else ""
        chapter_text_parts.append(f"第{cn}章 {title}：{events_str}")
    chapter_text = "\n".join(chapter_text_parts)

    output_schema = """## JSON 输出结构

{
  "volumes": [
    {
      "volume_number": 1,
      "title": "卷标题",
      "summary": "卷概要",
      "start_chapter": 1,
      "end_chapter": 20,
      "core_conflict": "本卷核心矛盾",
      "climax": "卷高潮事件",
      "payoff": "阶段性回报",
      "hook": "卷尾钩子（引出下一卷）",
      "key_themes": ["本卷涉及的主题"]
    }
  ]
}"""

    return (
        f"## 故事框架摘要\n\n{framework_text}\n\n"
        f"## 章节规划\n\n{chapter_text}\n\n"
        f"{profile_section}\n\n"
        f"{output_schema}"
    )


# ─── 章节目标卡提示词 ─────────────────────────────────────

def build_chapter_goal_prompt(
    chapter_number: int,
    chapter_title: str,
    volume: dict[str, Any] | None,
    framework: dict[str, Any],
    creative_profile: dict[str, Any] | None,
) -> str:
    profile_section = build_consistent_profile_section(creative_profile)

    framework_parts = []
    if framework.get("description"):
        framework_parts.append(f"故事梗概：{framework['description']}")
    if framework.get("outline"):
        outline = framework["outline"]
        stages = outline.get("stages") or outline.get("three_acts")
        if stages:
            current_stage = None
            for s in stages:
                stage_chapters = s.get("chapters", [])
                for sc in stage_chapters:
                    if sc.get("chapter_number") == chapter_number:
                        current_stage = s.get("title", "")
                        break
                if current_stage:
                    break
            if current_stage:
                framework_parts.append(f"当前阶段：{current_stage}")

    characters = framework.get("characters", [])
    char_lines = []
    for ch in characters[:6]:
        name = ch.get("name", "未命名")
        role = ch.get("role", "")
        arc = ch.get("arc", {})
        start = arc.get("start", "")
        char_lines.append(f"- {name}（{role}）：{start}")
    character_text = "\n".join(char_lines) if char_lines else "无"

    volume_text = ""
    if volume:
        volume_text = (
            f"当前卷：{volume.get('title', '')}\n"
            f"卷概要：{volume.get('summary', '')}\n"
            f"卷高潮：{volume.get('climax', '')}\n"
            f"卷尾钩子：{volume.get('hook', '')}"
        )

    output_schema = """## JSON 输出结构

{
  "chapter_number": <章节号>,
  "goal": "本章要达成的一个核心目标",
  "plot_progress": ["主线推进1", "主线推进2"],
  "relationship_change": ["关系变化1", "关系变化2"],
  "hook": "本章结尾的钩子",
  "payoff": "本章给读者的回报/爽点",
  "scene_suggestions": ["建议场景1", "建议场景2"]
}"""

    return (
        f"## 当前章节\n\n第{chapter_number}章：{chapter_title}\n\n"
        f"## 框架上下文\n\n{chr(10).join(framework_parts)}\n"
        f"## 角色状态\n\n{character_text}\n\n"
        f"{profile_section}\n\n"
        f"{volume_text}\n\n"
        f"{output_schema}"
    )


# ─── 投稿出版包提示词 ──────────────────────────────────────

def build_publishing_prompt(
    story_data: dict[str, Any],
    creative_profile: dict[str, Any] | None,
) -> str:
    profile_section = build_consistent_profile_section(creative_profile)

    sections = []

    description = story_data.get("description", "")
    if description:
        sections.append(f"## 故事描述\n\n{description}")

    tags = story_data.get("tags", {})
    if tags:
        sections.append(
            f"## 标签\n\n{json.dumps(tags, ensure_ascii=False)}"
        )

    characters = story_data.get("characters", [])
    char_lines = []
    for ch in characters[:6]:
        name = ch.get("name", "未命名")
        role = ch.get("role", "")
        char_lines.append(f"- {name}（{role}）")
    if char_lines:
        sections.append("## 核心角色\n\n" + "\n".join(char_lines))

    opening_plan = story_data.get("opening_plan")
    if opening_plan:
        hook_text = opening_plan.get("book_hook", "")
        sections.append(f"## 开篇方案\n\n核心卖点：{hook_text}")

    chapters = story_data.get("chapters", [])
    total_chapters = len(chapters)
    sections.append(f"## 作品规模\n\n规划总章节数：{total_chapters}")

    story_text = "\n\n".join(sections)

    output_schema = """## JSON 输出结构

{
  "titles": ["候选书名1", "候选书名2", "候选书名3"],
  "summary": "200字以内的简介，突出核心卖点",
  "selling_points": ["卖点1", "卖点2", "卖点3"],
  "platform_tags": ["推荐标签1", "推荐标签2"],
  "submission_notes": "投稿摘要（故事规模、预计字数、更新频率、定位）"
}"""

    return f"{story_text}\n\n{profile_section}\n\n{output_schema}"
