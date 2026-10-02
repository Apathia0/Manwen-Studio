"""Volume Service — 卷/篇章规划服务。

基于框架生成的阶段（phases）和章节规划（chapters），将故事细化为多个
彼此关联又各自独立的卷/篇章。每一卷都有完整的起承转合：
- 独立的叙事弧线
- 明确的核心冲突
- 结尾处设置悬念/钩子，驱动读者进入下一卷
"""

import json
from typing import Any

from .novel_autopilot import (
    _build_system_prompt,
    _build_story_snapshot,
    _call_deepseek,
    _extract_json_object,
    _extract_json_array,
)


def _build_volume_system_prompt(creative_profile: dict | None = None) -> str:
    """构建卷规划的系统提示。

    Args:
        creative_profile: 创作画像。

    Returns:
        卷规划系统提示字符串。
    """
    base = _build_system_prompt("volume", creative_profile)
    return f"""{base}

## 卷/篇章规划规则

1. 每一卷必须是一个「可独立阅读的故事单元」——有自己的起承转合，同时推进整体主线。
2. 卷内章节数量一般 8-25 章，根据节奏模式和故事需要灵活调整。
3. 第一卷必须承载故事的世界观引入、主角登场和核心冲突的种子。
4. 最后一卷承载终局高潮和主线回收。
5. 中间各卷要有明确的差异化——每卷换地图、换阶段、换矛盾类型，避免读者审美疲劳。
6. 每卷结尾必须设计「卷末钩子」——一个让读者不得不继续追更的悬念或期待。
7. 卷与卷之间要有连贯性，前卷的伏笔在后卷回收，后卷的危机在前卷埋设。

## 输出格式
输出一个 JSON 对象，包含一个 `volumes` 数组。每个卷对象包含：
- `id`: 卷标识，如 "vol_1"、"vol_2"（字符串）
- `title`: 卷标题（字符串）
- `summary`: 卷内容概要（字符串，200-500 字）
- `goal`: 本卷要达成的叙事目标（字符串）
- `core_conflict`: 本卷的核心冲突（字符串）
- `climax`: 本卷高潮情节描述（字符串）
- `ending_hook`: 卷末悬念/钩子设计（字符串）
- `chapter_start`: 起始章节编号（数字）
- `chapter_end`: 结束章节编号（数字）
- `linked_phase`: 关联的阶段标识（字符串，与 framework.phases 中的阶段对应）
"""


def _build_volume_user_prompt(framework: dict, chapters_plan: list | None = None) -> str:
    """构建卷规划的用户提示。"""
    parts: list[str] = []

    # 框架信息摘要
    snapshot_parts: list[str] = []
    if framework.get("description"):
        snapshot_parts.append(f"故事描述: {framework['description']}")
    if framework.get("tags"):
        snapshot_parts.append(f"标签: {json.dumps(framework['tags'], ensure_ascii=False)}")
    if framework.get("characters"):
        character_names = [c.get("name", "") for c in framework["characters"]]
        snapshot_parts.append(f"核心角色: {', '.join(character_names)}")
    if framework.get("outline"):
        phases = framework["outline"].get("phases", framework["outline"].get("three_acts", []))
        phase_summaries = []
        for p in phases:
            title = p.get("title", p.get("act", ""))
            summary = p.get("summary", "")[:100]
            phase_summaries.append(f"  - {title}: {summary}")
        if phase_summaries:
            snapshot_parts.append("阶段/幕信息:\n" + "\n".join(phase_summaries))
        themes = framework["outline"].get("themes", [])
        if themes:
            snapshot_parts.append(f"主题线索: {', '.join(themes)}")
    parts.append("当前故事框架信息：")
    parts.append("\n\n".join(snapshot_parts))

    # 章节规划信息
    chapters = chapters_plan or framework.get("chapters", [])
    if chapters:
        chapter_lines = []
        for c in chapters:
            ch_num = c.get("chapter_number", "?")
            ch_title = c.get("title", "")
            ch_phase = c.get("act", c.get("phase", ""))
            chapter_lines.append(f"  第{ch_num}章：{ch_title}（{ch_phase}）")
        parts.append(f"\n当前章节规划（{len(chapters)} 章）：\n" + "\n".join(chapter_lines))

    if framework.get("volumes"):
        parts.append(
            f"\n简要卷规划参考：\n"
            + "\n".join(
                f"  {v.get('id', '?')}: {v.get('title', '')}（第{v.get('chapter_start', '?')}-{v.get('chapter_end', '?')}章）"
                for v in framework["volumes"]
            )
        )

    parts.append("""
请根据以上框架信息和章节规划，生成详细的大纲级别的卷规划。

要求：
1. 每卷是一个独立叙事单元，有完整的起承转合。
2. 卷的数量根据故事规模自由决定，建议 2-6 卷。
3. 必须确保所有章节都被覆盖到某个卷中。
4. 每卷的 chapter_start 和 chapter_end 必须严格对应实际章节编号。
5. 如果已有简要卷规划（volumes），请在此基础上细化和调整。
6. `linked_phase` 字段关联 framework.outline.phases 中的对应阶段。

只输出 JSON，格式：{"volumes": [...]}
""")

    return "\n".join(parts)


async def generate_volumes(
    framework: dict,
    chapters_plan: list | None = None,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """生成详细的卷/篇章规划。

    基于已有框架信息和章节规划，生成每卷的完整定义。

    Args:
        framework: 框架信息字典（应包含 description、tags、characters、outline、chapters、volumes 等）。
        chapters_plan: 可选，章节规划列表。不传则使用 framework 中的 chapters。
        creative_profile: 创作画像。
        api_key: DeepSeek API Key。

    Returns:
        卷对象列表，每卷包含 id、title、summary、goal、core_conflict、climax、
        ending_hook、chapter_start、chapter_end、linked_phase。
        调用失败时返回空列表。
    """
    try:
        system_prompt = _build_volume_system_prompt(creative_profile)
        user_prompt = _build_volume_user_prompt(framework, chapters_plan)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        content = await _call_deepseek(
            messages=messages,
            api_key=api_key,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        result = _extract_json_object(content)
        volumes = result.get("volumes", [])

        if not isinstance(volumes, list):
            # 尝试直接解析为数组
            try:
                volumes = _extract_json_array(content)
            except Exception:
                volumes = []

        # 验证每卷的必要字段
        validated = []
        required_fields = ["id", "title", "summary", "goal", "core_conflict", "climax", "ending_hook"]
        for v in volumes:
            if isinstance(v, dict):
                v.setdefault("chapter_start", 1)
                v.setdefault("chapter_end", 1)
                v.setdefault("linked_phase", "")
                # 确保必要字段存在
                for field in required_fields:
                    v.setdefault(field, "")
                validated.append(v)

        return validated

    except Exception as e:
        return []


async def generate_single_volume_detail(
    volume_id: str,
    volume_title: str,
    chapter_range: tuple[int, int],
    framework: dict,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """在卷列表生成完成后，对单卷进行更细致的描述深化。

    Args:
        volume_id: 卷标识。
        volume_title: 卷标题。
        chapter_range: (起始章节, 结束章节) 元组。
        framework: 框架信息字典。
        creative_profile: 创作画像。
        api_key: DeepSeek API Key。

        Returns:
            深化后的卷对象字典，包含更详细的 chapter_breakdown、key_scenes 等。
            调用失败时返回包含 error 的字典。
    """
    try:
        chapter_start, chapter_end = chapter_range
        snapshot = _build_story_snapshot(framework)

        system_prompt = f"""{_build_system_prompt("volume", creative_profile)}

## 单卷深化任务
你正在对一卷故事进行深度细化。请基于整体框架，为这一卷生成更详细的情节分解。
"""
        user_prompt = f"""请为以下卷进行细化：

卷标识：{volume_id}
卷标题：{volume_title}
覆盖章节：第{chapter_start}章 - 第{chapter_end}章

整体故事框架：
{snapshot}

请输出包含以下字段的 JSON：
- `id`: 卷标识
- `title`: 卷标题
- `summary`: 卷概要（300-500 字）
- `goal`: 本卷叙事目标
- `core_conflict`: 核心冲突
- `climax`: 高潮情节
- `ending_hook`: 卷末钩子
- `chapter_start`: 起始章节
- `chapter_end`: 结束章节
- `linked_phase`: 关联阶段
- `chapter_breakdown`: 章节明细数组，每项包含 chapter_number、title、core_event（核心事件）
- `key_scenes`: 本卷关键场景数组，每个场景包含 scene_name、description、emotional_beat（情感节奏）

只输出 JSON。
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        content = await _call_deepseek(
            messages=messages,
            api_key=api_key,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        result = _extract_json_object(content)
        result.setdefault("id", volume_id)
        result.setdefault("title", volume_title)
        result.setdefault("chapter_start", chapter_start)
        result.setdefault("chapter_end", chapter_end)
        result.setdefault("chapter_breakdown", [])
        result.setdefault("key_scenes", [])

        return result

    except Exception as e:
        return {
            "error": f"单卷细化失败: {e}",
            "id": volume_id,
            "title": volume_title,
            "chapter_start": chapter_range[0],
            "chapter_end": chapter_range[1],
            "chapter_breakdown": [],
            "key_scenes": [],
        }
