"""Publishing Service — 发布包生成服务。

为已完成创作的小说生成面向各平台投稿的发布包，包含：
- 多版本书名方案
- 平台优化的简介
- 核心卖点提炼
- 平台标签推荐
- 投稿建议
"""

import json
from typing import Any

from .novel_autopilot import (
    _build_system_prompt,
    _build_story_snapshot,
    _call_deepseek,
    _extract_json_object,
)


def _build_publishing_system_prompt(creative_profile: dict | None = None) -> str:
    """构建发布包生成的系统提示。

    Args:
        creative_profile: 创作画像。

    Returns:
        发布包生成系统提示字符串。
    """
    base = _build_system_prompt("publishing", creative_profile)
    profile = creative_profile or {}
    platform = (profile.get("platform_mode") or "通用").strip()
    audience = (profile.get("audience_mode") or "大众向").strip()

    platform_tag_guidance: dict[str, str] = {
        "起点读书": "推荐标签类型：玄幻、奇幻、仙侠、武侠、都市、科幻、历史、游戏、体育、轻小说",
        "番茄小说": "推荐标签类型：玄幻、言情、都市、穿越、重生、系统、马甲、脑洞、甜宠、爽文",
        "晋江文学城": "推荐标签类型：言情、纯爱、百合、奇幻、科幻、悬疑推理、游戏、衍生、轻小说",
        "纵横中文网": "推荐标签类型：玄幻、奇幻、仙侠、武侠、都市、历史、军事、科幻、竞技",
        "飞卢小说网": "推荐标签类型：同人、影视、动漫、游戏、穿越、系统、变身、无敌",
        "豆瓣阅读": "推荐标签类型：小说、悬疑、科幻、爱情、历史、社会派",
    }
    tag_ref = platform_tag_guidance.get(platform, "推荐标签类型：根据题材自定")

    return f"""{base}

## 发布包生成规则

### 书名要求
1. 生成 5-8 个备选书名。
2. 书名必须符合 "{platform}" 平台的风格偏好。
3. 书名要突出核心卖点，让目标读者一看就感兴趣。
4. 建议包含一个最推荐的主打书名（放在第一顺位）。

### 简介要求
1. 简介要像书籍详情页的文案一样吸引人。
2. 控制在 200-500 字。
3. 突出故事的核心冲突和独特卖点。
4. 针对 {audience} 读者群体优化语言风格。

### 卖点要求
1. 提炼 3-6 个核心卖点。
2. 每个卖点一句话，直击读者痛点/爽点。

### 标签要求
1. 推荐 5-10 个平台标签。
2. 参考 {platform} 平台的标签体系。
{tag_ref}

### 投稿建议
1. 写明在 {platform} 平台投稿的注意事项。
2. 建议首发字数、更新频率、黄金更新时间等。
3. 针对 {audience} 读者群体的运营建议。

## 输出 JSON 格式
```json
{{
  "titles": ["主打书名", "备选书名2", "备选书名3", ...],
  "summary": "作品简介（200-500字）",
  "selling_points": ["卖点1", "卖点2", "卖点3"],
  "platform_tags": ["标签1", "标签2", "标签3"],
  "submission_notes": "投稿建议和注意事项"
}}
```

只输出 JSON，不要输出额外文字。
"""


def _build_publishing_user_prompt(story_data: dict, creative_profile: dict | None = None) -> str:
    """构建发布包生成的用户提示。"""
    snapshot = _build_story_snapshot(story_data)
    profile = creative_profile or {}
    platform = (profile.get("platform_mode") or "通用").strip()

    # 检查是否有已生成的开篇规划，可以提供更多素材
    opening_extra = ""
    opening_plan = story_data.get("opening_plan")
    if opening_plan and isinstance(opening_plan, dict):
        if opening_plan.get("book_hook"):
            opening_extra = f"""
## 已有的开篇卖点参考
- 书籍核心钩子：{opening_plan.get('book_hook', '')}
"""

    return f"""请根据以下故事的完整信息，生成面向 {platform} 平台的发布包。

{snapshot}
{opening_extra}

## 要求
1. 所有内容必须使用中文。
2. 书名要符合 {platform} 读者口味。
3. 简介要有足够吸引力，同时准确反映故事内容。
4. 卖点要直击目标读者群体的核心需求。
5. 投稿建议要具体可行。

只输出 JSON，不要输出额外文字。
"""


async def generate_publishing_package(
    story_data: dict,
    creative_profile: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """生成面向平台的发布包。

    Args:
        story_data: 故事数据字典，应包含 description、tags、characters、outline、
                    chapters、opening_plan 等字段。
        creative_profile: 创作画像。
        api_key: DeepSeek API Key。

    Returns:
        包含 titles、summary、selling_points、platform_tags、submission_notes 的字典。
        调用失败时返回包含 error 的字典。
    """
    try:
        system_prompt = _build_publishing_system_prompt(creative_profile)
        user_prompt = _build_publishing_user_prompt(story_data, creative_profile)

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
        result.setdefault("titles", [])
        result.setdefault("summary", "")
        result.setdefault("selling_points", [])
        result.setdefault("platform_tags", [])
        result.setdefault("submission_notes", "")

        # 如果 titles 为空或无推荐书名，补充一个基于描述的默认书名
        if not result.get("titles") and story_data.get("description"):
            desc = story_data["description"]
            short_desc = desc[:30] if len(desc) > 30 else desc
            result["titles"] = [f"未命名：{short_desc}"]

        return result

    except Exception as e:
        return {
            "error": f"发布包生成失败: {e}",
            "titles": [],
            "summary": "",
            "selling_points": [],
            "platform_tags": [],
            "submission_notes": "",
        }
