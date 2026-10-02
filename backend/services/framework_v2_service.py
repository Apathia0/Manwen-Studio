"""Framework V2 Service — 平台导向的长篇网文框架生成。

与 V1 的关键区别：
- 不强制三幕结构，支持 2+ 个阶段/篇章
- 以 creative_profile 中的 platform_mode、pace_mode 等参数驱动系统提示
- 强调长篇可持续创作节奏
- 输出中包含 volumes 字段，供后续 volume_service 细化
"""

import json
from typing import Any

from .novel_autopilot import (
    _build_system_prompt,
    _build_story_snapshot,
    _call_deepseek,
    _extract_json_object,
)

# ─── 系统提示 ─────────────────────────────────────────────────────────────────


def _effective_genre(profile: dict | None) -> str:
    profile = profile or {}
    return (profile.get("custom_genre") or profile.get("genre") or "").strip()


def generate_system_prompt(creative_profile: dict | None = None) -> str:
    """生成长篇网文框架生成的系统提示。

    Args:
        creative_profile: 创作画像字典。

    Returns:
        针对平台和长篇节奏优化的系统提示字符串。
    """
    profile = creative_profile or {}
    genre = _effective_genre(profile)
    pace_mode = (profile.get("pace_mode") or "适中").strip()
    audience_mode = (profile.get("audience_mode") or "大众向").strip()

    base = _build_system_prompt("framework", creative_profile)

    genre_guidance = ""
    if genre:
        genre_guidance = f"""
## 题材专项指导（{genre}）
- 请充分体现 {genre} 题材的核心魅力和读者期待
- 世界观设定要有层次感，随着剧情推进逐步展开
- 核心冲突和力量体系要有清晰的递进逻辑
"""

    return f"""{base}

{genre_guidance}
## 长篇框架结构规则
1. 不要强制使用三幕结构。根据题材和节奏自由决定阶段数量（2 个及以上阶段/篇章）。
2. 每个阶段/篇章要有独立的起承转合，同时服务于整体主线。
3. 核心矛盾、角色成长、关系变化、世界观揭秘都必须分阶段兑现，不要过早回收。
4. 真正的终局高潮应位于整体规划后段，而不是前 20-40 章内。
5. 前半段章节可以更具体，后半段章节可以更偏里程碑式推进，但仍要覆盖完整主线。
6. 章节规划要体现「铺垫 → 升级 → 扩盘 → 反转 → 决战 → 余波」的长篇节奏。
7. 不要把角色一夜成长完成，不要把世界观谜底一次性揭穿，不要把感情线过早定局。

## 节奏适配（{pace_mode}）
- 根据节奏模式调整章节密度和冲突频率
- 确保整体推进速度与节奏模式一致
- 在关键节点（每卷结尾、每阶段过渡）设置足够的悬念和期待

## 目标受众（{audience_mode}）
- 所有内容面向 {audience_mode} 读者
- 确保故事设定、人物关系、情感线符合目标受众的阅读偏好

## JSON 输出结构要求
输出的 JSON 必须包含以下顶层字段：
- `description`: 故事描述（字符串）
- `tags`: 标签对象，包含 `type`、`theme`、`style`、`audience`
- `characters`: 角色数组，3-8 个核心角色，每个角色包含 `name`、`role`、`arc`（包含 start/middle/end）、`relationships`（数组）
- `outline`: 大纲对象，包含 `phases`（阶段数组，每个阶段包含 title、summary、key_events、chapters）、`themes`（主题线索数组）、`foreshadowing`（伏笔数组）
- `chapters`: 完整章节规划数组，每章包含 `chapter_number`、`title`、`summary`、`key_events`、`phase`（所属阶段标识）
- `volumes`: 卷/篇章规划数组（简要版），每卷包含 `id`、`title`、`summary`、`chapter_start`、`chapter_end`、`linked_phase`

注意：`outline.phases` 是阶段数组，数量根据题材自由决定，至少 2 个阶段。
"""


def _build_user_prompt(description: str, creative_profile: dict | None = None) -> str:
    """构建框架生成的用户提示。"""
    profile = creative_profile or {}
    target_length = (profile.get("target_length") or "").strip()
    goal = (profile.get("creation_goal") or "").strip()
    genre = _effective_genre(profile)

    extra = ""
    if target_length:
        extra += f"\n- 目标篇幅：{target_length}"
    if goal:
        extra += f"\n- 创作目标：{goal}"

    return f"""请根据以下故事描述，生成一版适合{profile.get('platform_mode', '网文平台')}连载的长篇小说完整框架。

故事描述：
{description}

## 输出要求
1. `outline.phases` 为阶段数组，数量根据题材自由决定（至少 2 个），不要为了形式硬套三幕。
2. 每个阶段要有明确的核心冲突、剧情推进方向和预期篇幅。
3. `chapters` 要提供一版完整的章节规划，章节编号从 1 连续递增。
4. 前半段章节可以更具体，后半段章节可以更偏里程碑式概括，但仍需覆盖完整主线。
5. `volumes` 为简要的卷规划，后续可以单独细化每卷内容。
6. 如果题材天然适合长篇连载，优先规划成更有延展性的长篇，而不是短篇速通。{extra}
7. 只输出 JSON，不要输出额外文字。JSON 顶层字段：description、tags、characters、outline、chapters、volumes。
"""


# ─── 核心生成函数 ─────────────────────────────────────────────────────────────


async def generate_framework_v2(
    description: str,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """平台导向的长篇网文框架生成（V2）。

    与 V1 的 generate_framework 不同：
    - 不强制三幕结构，outline.phases 支持 2+ 阶段
    - 根据 creative_profile 的平台、受众、节奏等信息定制系统提示
    - 输出包含 volumes 简要规划

    Args:
        description: 故事描述文本。
        creative_profile: 创作画像（包含 platform_mode、audience_mode、genre、pace_mode 等）。
        api_key: DeepSeek API Key。

    Returns:
        包含 description、tags、characters、outline、chapters、volumes 的字典。
        调用失败时返回包含 error 字段的字典。
    """
    try:
        system_prompt = generate_system_prompt(creative_profile)
        user_prompt = _build_user_prompt(description, creative_profile)

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

        # 确保顶层字段存在
        result.setdefault("description", description)
        result.setdefault("tags", {})
        result.setdefault("characters", [])
        result.setdefault("outline", {})
        result.setdefault("chapters", [])
        result.setdefault("volumes", [])

        return result

    except Exception as e:
        return {
            "error": f"框架生成失败: {e}",
            "description": description,
            "tags": {},
            "characters": [],
            "outline": {},
            "chapters": [],
            "volumes": [],
        }
