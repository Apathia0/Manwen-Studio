"""Opening Service — 开篇规划增强服务。

为已完成框架生成的小说生成精细化开篇方案，重点关注：
- 平台调性匹配的开篇钩子
- 前 20 章的关键节奏节点设计
- 读者留存率最大化
"""

import json
from typing import Any

from .novel_autopilot import (
    _build_system_prompt,
    _build_story_snapshot,
    _call_deepseek,
    _extract_json_object,
)


def _build_opening_system_prompt(creative_profile: dict | None = None) -> str:
    """构建开篇规划的系统提示。

    Args:
        creative_profile: 创作画像。

    Returns:
        开篇规划系统提示字符串。
    """
    base = _build_system_prompt("opening", creative_profile)
    profile = creative_profile or {}
    platform = (profile.get("platform_mode") or "通用").strip()
    pace_mode = (profile.get("pace_mode") or "适中").strip()

    # 根据平台和节奏模式调整开篇策略
    platform_opening_tips: dict[str, str] = {
        "起点读书": (
            "起点读者习惯较长篇的沉浸式阅读，开篇需要建立世界观的独特性，"
            "但不意味着慢热——前 3 章必须有金手指/核心设定的亮相，第 5 章前建立核心冲突。"
        ),
        "番茄小说": (
            "番茄读者决策成本极低，前 1000 字必须抓住注意力。"
            "建议第一章开头 500 字内抛出最大矛盾或最高概念，"
            "每章结尾必须有强悬念钩子。前 3 章定生死。"
        ),
        "晋江文学城": (
            "晋江读者注重情绪共鸣和人物魅力，开篇需要有辨识度的人物出场和情感锚点。"
            "可以不是强冲突开篇，但必须有让人记住的角色瞬间。"
        ),
        "飞卢小说网": (
            "飞卢读者追求新鲜感和快节奏，开篇必须展示题材的独特切入点。"
            "第一章就要让读者看到「这个文和别人不一样」的核心卖点。"
        ),
    }
    tip = platform_opening_tips.get(platform, (
        "开篇需要平衡吸引力和信息量，让读者快速建立对故事的期待。"
    ))

    pace_opening = ""
    if pace_mode in ("极快", "较快"):
        pace_opening = (
            "由于采用快节奏模式，开篇更要极端重视前 3 章的钩子密度。"
            "每一章的结尾都必须有让读者忍不住点下一章的冲动。"
        )
    elif pace_mode in ("较慢", "史诗级"):
        pace_opening = (
            "开篇可以适当展开世界观和人物背景，但要确保每章都有至少一个"
            "「值得记住」的情节节点或情感瞬间，避免开局过于平淡。"
        )

    return f"""{base}

## 开篇规划专项要求

### 平台开篇策略
{tip}

### 节奏适配
{pace_opening}

## 输出 JSON 结构
输出的 JSON 必须包含以下字段：
- `book_hook`: 整本书的核心卖点提炼（一句话），用于吸引读者点进书籍页
- `chapter_1_hook`: 第一章的核心钩子设计，说明第一章结尾如何让读者想看第二章
- `chapter_3_hook`: 前三章完成后，读者为什么已经「入坑」了——前 3 章的累积钩子
- `chapter_10_payoff`: 第 10 章左右的第一次重要回报/悬念回收设计
- `chapter_20_climax`: 第 20 章左右的阶段性高潮/转折设计
- `opening_notes`: 开篇创作注意事项数组，每条一个字符串（3-6 条）

注意：所有钩子和回报设计必须紧密结合故事的实际内容和人物设定，不能泛泛而谈。
"""


def _build_opening_user_prompt(story_data: dict) -> str:
    """构建开篇规划的用户提示。"""
    snapshot = _build_story_snapshot(story_data)
    return f"""请根据以下故事的完整框架信息，设计一个精细化的开篇规划方案。

{snapshot}

请特别注意：
1. 所有钩子必须基于故事中实际存在的设定、人物和冲突，不能凭空编造。
2. `book_hook` 要像书籍详情页的简介一样吸引人。
3. 钩子之间要有递进关系：第 1 章 → 第 3 章 → 第 10 章 → 第 20 章，读者的阅读体验逐步深化。
4. `opening_notes` 要给出对作者有实际指导意义的创作建议。

只输出 JSON，不要输出额外文字。
"""


async def generate_opening_plan(
    story_data: dict,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """生成精细化开篇规划方案。

    Args:
        story_data: 故事数据字典，应包含 description、tags、characters、outline、chapters 等。
        creative_profile: 创作画像。
        api_key: DeepSeek API Key。

    Returns:
        包含 book_hook、chapter_1_hook、chapter_3_hook、chapter_10_payoff、
        chapter_20_climax、opening_notes 的字典。
        调用失败时返回包含 error 的字典。
    """
    try:
        system_prompt = _build_opening_system_prompt(creative_profile)
        user_prompt = _build_opening_user_prompt(story_data)

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

        # 确保所有字段存在
        result.setdefault("book_hook", "")
        result.setdefault("chapter_1_hook", "")
        result.setdefault("chapter_3_hook", "")
        result.setdefault("chapter_10_payoff", "")
        result.setdefault("chapter_20_climax", "")
        result.setdefault("opening_notes", [])

        return result

    except Exception as e:
        return {
            "error": f"开篇规划生成失败: {e}",
            "book_hook": "",
            "chapter_1_hook": "",
            "chapter_3_hook": "",
            "chapter_10_payoff": "",
            "chapter_20_climax": "",
            "opening_notes": [f"开篇规划生成失败，请重试或检查配置。错误：{e}"],
        }
