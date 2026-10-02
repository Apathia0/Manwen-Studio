"""Chapter Goal Service — 章节目标卡片生成服务。

为每个章节生成结构化的「目标卡片」，帮助创作者在落笔之前明确：
- 本章要推进什么
- 人物关系有什么变化
- 读者应该有什么情感预期
- 结尾留什么钩子
"""

import json
from typing import Any

from .novel_autopilot import (
    _build_system_prompt,
    _build_story_snapshot,
    _call_deepseek,
    _extract_json_object,
)


def _build_chapter_goal_system_prompt(creative_profile: dict | None = None) -> str:
    """构建章节目标卡片的系统提示。

    Args:
        creative_profile: 创作画像。

    Returns:
        章节目标卡片系统提示字符串。
    """
    base = _build_system_prompt("chapter_goal", creative_profile)
    return f"""{base}

## 章节目标卡片设计规则

1. 每一张目标卡片应该是一章的「写作蓝图」——在动笔前明确本章要完成的任务。
2. `goal` 是本章的核心目标，用一句话说清本章要「完成什么」。
3. `plot_progress` 是本章对主线剧情的推进点列丼，每条一个具体的推进动作。
4. `relationship_change` 是本章中人物关系发生的具体变化，即使只是微小的情感偏移也要记录。
5. `hook` 是本章结尾的悬念/钩子设计——让读者忍不住点下一章。
6. `payoff` 是本章回收的伏笔或兑现的情感承诺（如果有）。
7. `scene_suggestions` 是本章建议包含的场景列表，每个场景一条简要描述。

核心原则：
- 每一章都必须推动故事前进（plot_progress 至少 2 条）
- 每一章都必须有情感/关系变化（relationship_change 至少 1 条）
- 每一章结尾必须有钩子（hook 不能为空）
- 不是每章都有 payoff，但重要节点章必须有
"""


def _build_chapter_goal_user_prompt(
    story_data: dict,
    chapter_number: int,
    chapter_title: str,
    volume_info: dict | None = None,
) -> str:
    """构建章节目标卡片的用户提示。"""
    snapshot = _build_story_snapshot(story_data)

    volume_context = ""
    if volume_info:
        volume_context = f"""
## 所属卷信息
- 卷标题：{volume_info.get('title', '')}
- 卷概要：{volume_info.get('summary', '')}
- 卷目标：{volume_info.get('goal', '')}
- 本卷核心冲突：{volume_info.get('core_conflict', '')}
- 本卷高潮：{volume_info.get('climax', '')}
- 卷末钩子：{volume_info.get('ending_hook', '')}
"""

    # 查找前后章节信息
    chapters = story_data.get("chapters", [])
    current_chapter_info = None
    prev_chapter_info = None
    next_chapter_info = None
    for c in chapters:
        n = c.get("chapter_number")
        if n == chapter_number:
            current_chapter_info = c
        if n == chapter_number - 1:
            prev_chapter_info = c
        if n == chapter_number + 1:
            next_chapter_info = c

    context_lines = []
    if prev_chapter_info:
        context_lines.append(f"上一章（第{chapter_number-1}章）：{prev_chapter_info.get('title', '')}")
    if current_chapter_info:
        context_lines.append(
            f"本章框架定义：{json.dumps(current_chapter_info, ensure_ascii=False)}"
        )
    if next_chapter_info:
        context_lines.append(f"下一章（第{chapter_number+1}章）：{next_chapter_info.get('title', '')}")

    chapter_context = ""
    if context_lines:
        chapter_context = "## 章节上下文\n" + "\n".join(context_lines)

    return f"""请为第 {chapter_number} 章「{chapter_title}」生成一张详细的章节目标卡片。

## 当前故事框架
{snapshot}
{volume_context}
{chapter_context}

## 生成要求
1. 目标卡片必须紧密结合故事实际设定和当前进展，不能泛泛而谈。
2. `goal` 要具体到本章实际要达成的叙事目标。
3. `plot_progress` 至少 2 条，每条描述一个具体的剧情推进动作。
4. `relationship_change` 至少 1 条，描述人物关系的具体变化。
5. `hook` 必须设计为让读者想立即看下一章的悬念。
6. `scene_suggestions` 建议 2-5 个场景。

## 输出 JSON 格式
```json
{{
  "chapter_number": {chapter_number},
  "goal": "本章核心目标",
  "plot_progress": ["推进点1", "推进点2"],
  "relationship_change": ["关系变化1"],
  "hook": "章末钩子",
  "payoff": "本章回报（如有）",
  "scene_suggestions": ["场景1：简要描述", "场景2：简要描述"]
}}
```

只输出 JSON，不要输出额外文字。确保 chapter_number 为 {chapter_number}。
"""


async def generate_chapter_goal_card(
    story_data: dict,
    chapter_number: int,
    chapter_title: str,
    volume_info: dict | None = None,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """生成单个章节的目标卡片。

    Args:
        story_data: 故事数据字典。
        chapter_number: 章节编号。
        chapter_title: 章节标题。
        volume_info: 可选，所属卷的信息字典。
        creative_profile: 创作画像。
        api_key: DeepSeek API Key。

    Returns:
        章节目标卡片字典，包含 chapter_number、goal、plot_progress、
        relationship_change、hook、payoff、scene_suggestions。
        调用失败时返回包含 error 的字典。
    """
    try:
        system_prompt = _build_chapter_goal_system_prompt(creative_profile)
        user_prompt = _build_chapter_goal_user_prompt(
            story_data, chapter_number, chapter_title, volume_info,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        content = await _call_deepseek(
            messages=messages,
            api_key=api_key,
            temperature=0.8,
            response_format={"type": "json_object"},
        )

        result = _extract_json_object(content)

        # 确保字段存在
        result.setdefault("chapter_number", chapter_number)
        result.setdefault("goal", "")
        result.setdefault("plot_progress", [])
        result.setdefault("relationship_change", [])
        result.setdefault("hook", "")
        result.setdefault("payoff", "")
        result.setdefault("scene_suggestions", [])

        return result

    except Exception as e:
        return {
            "error": f"第 {chapter_number} 章目标卡片生成失败: {e}",
            "chapter_number": chapter_number,
            "goal": "",
            "plot_progress": [],
            "relationship_change": [],
            "hook": "",
            "payoff": "",
            "scene_suggestions": [],
        }


async def generate_chapter_goal_cards_batch(
    story_data: dict,
    chapter_list: list[dict],
    volume_info: dict | None = None,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """批量生成多个章节的目标卡片。

    适合在卷规划完成后，为一卷内的所有章节一次生成目标卡片。

    Args:
        story_data: 故事数据字典。
        chapter_list: 章节信息列表，每项包含 chapter_number 和 title。
        volume_info: 可选，所属卷的信息字典。
        creative_profile: 创作画像。
        api_key: DeepSeek API Key。

    Returns:
        章节目标卡片字典列表。
    """
    # 分批生成以避免超长 prompt（每批最多 3 章）
    batch_size = 3
    all_cards: list[dict] = []

    for i in range(0, len(chapter_list), batch_size):
        batch = chapter_list[i:i + batch_size]
        batch_cards = []

        # 并行生成同批内的卡片
        for chapter_info in batch:
            card = await generate_chapter_goal_card(
                story_data=story_data,
                chapter_number=chapter_info.get("chapter_number", 0),
                chapter_title=chapter_info.get("title", ""),
                volume_info=volume_info,
                creative_profile=creative_profile,
                api_key=api_key,
            )
            batch_cards.append(card)

        all_cards.extend(batch_cards)

    return all_cards
