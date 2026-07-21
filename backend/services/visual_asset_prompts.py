"""角色、场景与道具视觉资产提示词的共享分析工具。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from services import deepseek as deepseek_service
from services.video_chapter_prompts import SHOT_CHARACTER_SYSTEM_PROMPT, SHOT_SCENE_PROP_SYSTEM_PROMPT


_CHARACTER_RULES = SHOT_CHARACTER_SYSTEM_PROMPT.split("# JSON 输出格式", 1)[0].strip()
_SCENE_PROP_RULES = SHOT_SCENE_PROP_SYSTEM_PROMPT.split("# 输出格式", 1)[0].strip()
_SCENE_RULES = (
    "# 场景资产规范"
    + _SCENE_PROP_RULES.split("# 场景资产规范", 1)[1].split("# 道具资产规范", 1)[0]
).strip()
_PROP_RULES = (
    "# 道具资产规范"
    + _SCENE_PROP_RULES.split("# 道具资产规范", 1)[1].split("# 第三阶段", 1)[0]
).strip()

_VISUAL_ASSET_GROUPS = ("characters", "scenes", "props")


def _normalize_visual_asset_groups(asset_groups: object = None) -> tuple[str, ...]:
    """规范化需要分析的资产分组；未指定时保持全量分析。"""
    if asset_groups is None:
        return _VISUAL_ASSET_GROUPS
    if not isinstance(asset_groups, (set, list, tuple)):
        raise ValueError("asset_groups 必须是数组或集合")
    selected = {str(group or "").strip().lower() for group in asset_groups}
    unknown = selected.difference(_VISUAL_ASSET_GROUPS)
    if unknown:
        raise ValueError(f"不支持的视觉资产分组: {', '.join(sorted(unknown))}")
    return tuple(group for group in _VISUAL_ASSET_GROUPS if group in selected)


def _build_visual_asset_analysis_system_prompt(asset_groups: object = None, max_items: int = 6) -> str:
    """按所选分组构造分析提示词，避免模型分析未勾选资产。"""
    groups = _normalize_visual_asset_groups(asset_groups)
    if not groups:
        raise ValueError("至少选择一种视觉资产分组")
    sections: list[str] = []
    if "characters" in groups:
        sections.append(f"## 角色资产规范\n{_CHARACTER_RULES}")
    if "scenes" in groups and "props" in groups:
        sections.append(f"## 场景与道具资产规范\n{_SCENE_PROP_RULES}")
    elif "scenes" in groups:
        sections.append(f"## 场景资产规范\n{_SCENE_RULES}")
    elif "props" in groups:
        sections.append(f"## 道具资产规范\n{_PROP_RULES}")
    schema_rows = {
        "characters": '"characters": [{"name":"角色名", "description":"完整视觉摘要", "evidence":"原文依据", "prompt":"完整中文 CHARACTER PROFILE + 不少于500英文单词的 FINAL IMAGE PROMPT"}]',
        "scenes": '"scenes": [{"name":"场景名", "description":"完整空间与视觉摘要", "evidence":"原文依据", "prompt":"完整中文 ENVIRONMENT PROFILE + 不少于300英文单词的 FINAL IMAGE PROMPT"}]',
        "props": '"props": [{"name":"道具名", "description":"完整外观与功能摘要", "evidence":"原文依据", "prompt":"完整中文 PROP PROFILE + 不少于100英文单词的 FINAL IMAGE PROMPT"}]',
    }
    output_schema = ",\n  ".join(schema_rows[group] for group in groups)
    selected_labels = "、".join({"characters": "角色", "scenes": "场景", "props": "道具"}[group] for group in groups)
    return f"""你是统一视觉资产分析工具。本次只分析以下资产类型：{selected_labels}。不得识别、描述或输出未选择的资产类型。请从作品文本中识别值得建立一致性参考的所选资产，再严格按照下列视频制作规范，为每项资产生成可直接用于图片模型的专业设定板提示词。

{chr(10).join(sections)}

## 统一输出格式
只返回有效 JSON，不要输出 Markdown 或解释；只包含以下键：
{{
  {output_schema}
}}

每类最多 {max_items} 项。只保留具名、重复出现或对视觉连续性重要的资产，不得虚构原文没有的对象。场景提示词不得包含角色，角色与道具提示词不得描述无关人物。"""

VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT = _build_visual_asset_analysis_system_prompt()


def normalize_visual_asset_suggestions(result: object, max_items: int = 6) -> dict[str, list[dict[str, str]]]:
    """将模型输出规范化为稳定的三类视觉资产结构。"""
    normalized: dict[str, list[dict[str, str]]] = {"characters": [], "scenes": [], "props": []}
    if not isinstance(result, dict):
        return normalized

    safe_limit = max(1, min(int(max_items or 6), 12))
    for group in normalized:
        items = result.get(group, [])
        if not isinstance(items, list):
            continue
        seen_names: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:255]
            normalized_name = "".join(name.lower().split())
            if not name or normalized_name in seen_names:
                continue
            prompt = str(item.get("prompt") or "").strip()
            if not prompt:
                continue
            seen_names.add(normalized_name)
            normalized[group].append({
                "name": name,
                "description": str(item.get("description") or "").strip()[:4000],
                "evidence": str(item.get("evidence") or "").strip()[:2000],
                "prompt": prompt[:24000],
            })
            if len(normalized[group]) >= safe_limit:
                break
    return normalized


def _repair_unescaped_json_string_quotes(content: str) -> str:
    """转义模型在长 JSON 字符串内部偶发输出的裸双引号。"""
    def looks_like_object_key(start: int) -> bool:
        if start >= len(content) or content[start] != '"':
            return False
        escaped_key_char = False
        for key_index in range(start + 1, len(content)):
            key_char = content[key_index]
            if escaped_key_char:
                escaped_key_char = False
                continue
            if key_char == "\\":
                escaped_key_char = True
                continue
            if key_char != '"':
                continue
            after_key = key_index + 1
            while after_key < len(content) and content[after_key].isspace():
                after_key += 1
            return after_key < len(content) and content[after_key] == ":"
        return False

    repaired: list[str] = []
    in_string = False
    escaped = False
    length = len(content)
    for index, char in enumerate(content):
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            continue
        if escaped:
            repaired.append(char)
            escaped = False
            continue
        if char == "\\":
            repaired.append(char)
            escaped = True
            continue
        if char != '"':
            repaired.append(char)
            continue

        lookahead = index + 1
        while lookahead < length and content[lookahead].isspace():
            lookahead += 1
        next_char = content[lookahead] if lookahead < length else ""
        closes_string = next_char in {":", "}", "]", ""}
        if next_char == ",":
            after_comma = lookahead + 1
            while after_comma < length and content[after_comma].isspace():
                after_comma += 1
            following = content[after_comma] if after_comma < length else ""
            closes_string = following in {"{", "[", "}", "]", ""} or looks_like_object_key(after_comma)
        if closes_string:
            repaired.append(char)
            in_string = False
        else:
            repaired.append('\\"')
    return "".join(repaired)


def _parse_visual_asset_json(content: str) -> dict:
    """按视频工作流的容错顺序解析视觉资产 JSON。"""
    candidates: list[str] = []

    def add_candidate(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    add_candidate(content)
    add_candidate(deepseek_service._repair_broken_json_fields(content))
    for candidate in tuple(candidates):
        add_candidate(_repair_unescaped_json_string_quotes(candidate))
    for candidate in tuple(candidates):
        add_candidate(deepseek_service._repair_truncated_json(candidate))

    last_error: ValueError | None = None
    for candidate in candidates:
        try:
            return deepseek_service._extract_json_object(candidate)
        except ValueError as exc:
            last_error = exc
    raise ValueError("视觉资产分析响应不是有效 JSON，自动修复失败") from last_error


async def analyze_visual_assets(
    *,
    chapter_text: str,
    character_context: str = "",
    structured_characters: object = None,
    api_key: str,
    max_items: int = 6,
    asset_groups: object = None,
) -> dict[str, list[dict[str, str]]]:
    """使用视频工作流的专业规范统一分析章节视觉资产。"""
    selected_groups = _normalize_visual_asset_groups(asset_groups)
    selected_labels = "、".join(
        {"characters": "角色", "scenes": "场景", "props": "道具"}[group]
        for group in selected_groups
    )
    character_json = json.dumps(
        structured_characters if isinstance(structured_characters, list) else [],
        ensure_ascii=False,
    )
    user_prompt = f"""请分析以下作品资料和当前章节，只为漫画与视频共用的视觉资产库生成{selected_labels}设定板提示词，不要分析其他资产类型。

作品角色设定：
{character_context[:8000]}

结构化角色资料：
{character_json[:8000]}

当前章节正文：
{chapter_text[:30000]}
"""
    payload: dict[str, Any] = {
        "model": deepseek_service.runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": _build_visual_asset_analysis_system_prompt(selected_groups, max_items=max_items),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{deepseek_service.runtime_base_url()}/chat/completions",
            json={**payload, "response_format": {"type": "json_object"}},
            headers=deepseek_service._deepseek_auth_headers(api_key),
        )
        if response.status_code == 400:
            response = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
        response.raise_for_status()
        data = response.json()
        deepseek_service._record_response_usage(data)
        content = str(data["choices"][0]["message"]["content"] or "").strip()

    result = normalize_visual_asset_suggestions(_parse_visual_asset_json(content), max_items=max_items)
    for group in _VISUAL_ASSET_GROUPS:
        if group not in selected_groups:
            result[group] = []
    return result
