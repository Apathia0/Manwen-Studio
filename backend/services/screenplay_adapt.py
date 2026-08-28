"""小说章节正文 → 漫剧剧本改写服务。

只读原作品：路由层负责校验章节所有权并传入内容，本层不做 IO 之外的数据库操作，
也绝不回写任何章节。产出画布剧本节点的初始剧本文本与来源溯源信息。
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import httpx

from services.errors import UpstreamServiceError

logger = logging.getLogger(__name__)

ADAPT_TIMEOUT_SECONDS = 600


def chapter_content_hash(content: str) -> str:
    """章节内容指纹：相同内容稳定，用于来源溯源展示。"""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:32]


def _split_content_chunks(content: str, max_chars: int) -> list[str]:
    """按段落边界切分长正文，保证每段不超过 max_chars。"""
    text = (content or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        # 优先在段落边界（双换行）切，其次单换行，最后硬切
        cut = window.rfind("\n\n")
        if cut < max_chars // 2:
            cut = window.rfind("\n")
        if cut < max_chars // 2:
            cut = max_chars
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


async def _adapt_single_call(
    *,
    chapter_title: str,
    chapter_content: str,
    previous_digest: str,
    api_key: str | None,
) -> str:
    """单批改写调用，返回该批剧本文本。"""
    from services import deepseek as deepseek_service
    from services.video_chapter_prompts import (
        SCREENPLAY_ADAPT_SYSTEM_PROMPT,
        SCREENPLAY_ADAPT_USER_TEMPLATE,
    )

    payload: dict[str, Any] = {
        "model": deepseek_service.runtime_model(),
        "messages": [
            {"role": "system", "content": SCREENPLAY_ADAPT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": SCREENPLAY_ADAPT_USER_TEMPLATE.format(
                    chapter_title=chapter_title,
                    previous_digest=previous_digest or "（无，本批为剧本开头）",
                    chapter_content=chapter_content,
                ),
            },
        ],
        "stream": False,
        "max_tokens": 16384,
        "thinking": {"type": "disabled"},
    }
    try:
        async with httpx.AsyncClient(timeout=ADAPT_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
        resp.raise_for_status()
        data = deepseek_service._response_json(resp, context="DeepSeek")
    except httpx.TimeoutException as exc:
        raise UpstreamServiceError(
            "剧本改写响应超时，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=504,
            code="screenplay_adapt_timeout",
        ) from exc
    except httpx.HTTPStatusError as exc:
        status_code = int(exc.response.status_code)
        raise UpstreamServiceError(
            "剧本改写服务暂时不可用，请稍后重试",
            retryable=status_code in {408, 409, 425, 429, 500, 502, 503, 504},
            provider="DeepSeek",
            status_code=status_code,
            code="screenplay_adapt_failed",
            diagnostics={"upstream_status_code": status_code},
        ) from exc
    except httpx.RequestError as exc:
        raise UpstreamServiceError(
            "剧本改写网络连接失败，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_adapt_network_error",
        ) from exc
    except ValueError as exc:
        raise UpstreamServiceError(
            "剧本改写响应格式异常，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_adapt_invalid_response",
        ) from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise UpstreamServiceError(
            "剧本改写未返回可用内容，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_adapt_empty_response",
        )
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise UpstreamServiceError(
            "剧本改写未返回可用内容，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_adapt_empty_response",
        )
    return content.strip()


async def adapt_novel_to_screenplay(
    *,
    chapters: list[dict[str, Any]],
    api_key: str | None = None,
    max_chars_per_call: int = 8000,
) -> dict[str, Any]:
    """逐章把小说正文改写为剧本并拼接。

    chapters 由路由层校验所有权后传入：[{story_id, chapter_id, title, content}]。
    只读原作品，本函数不产生任何对原作品的写入。
    """
    if not chapters:
        raise ValueError("至少需要一章正文才能改写剧本")

    screenplay_parts: list[str] = []
    source_refs: list[dict[str, Any]] = []
    batch_count = 0

    for chapter in chapters:
        title = str(chapter.get("title") or "未命名章节")
        content = str(chapter.get("content") or "").strip()
        if not content:
            continue
        chunks = _split_content_chunks(content, max_chars_per_call)
        chapter_parts: list[str] = []
        previous_digest = ""
        for index, chunk in enumerate(chunks, start=1):
            logger.info(
                "screenplay_adapt.batch_start chapter=%s batch=%s/%s chars=%s",
                chapter.get("chapter_id"),
                index,
                len(chunks),
                len(chunk),
            )
            part = await _adapt_single_call(
                chapter_title=f"{title}（{index}/{len(chunks)}）" if len(chunks) > 1 else title,
                chapter_content=chunk,
                previous_digest=previous_digest,
                api_key=api_key,
            )
            chapter_parts.append(part)
            batch_count += 1
            # 摘要取该批结尾的有限字符，供下一批衔接
            previous_digest = part[-600:]
            logger.info(
                "screenplay_adapt.batch_done chapter=%s batch=%s/%s out_chars=%s",
                chapter.get("chapter_id"),
                index,
                len(chunks),
                len(part),
            )
        if chapter_parts:
            screenplay_parts.append("\n\n".join(chapter_parts))
            source_refs.append(
                {
                    "story_id": chapter.get("story_id"),
                    "chapter_id": chapter.get("chapter_id"),
                    "title": title,
                    "content_hash": chapter_content_hash(content),
                }
            )

    if not screenplay_parts:
        raise ValueError("所选章节正文均为空，无法改写剧本")

    screenplay_text = "\n\n".join(screenplay_parts)
    logger.info(
        "screenplay_adapt.done chapters=%s batches=%s out_chars=%s",
        len(source_refs),
        batch_count,
        len(screenplay_text),
    )
    return {
        "screenplay_text": screenplay_text,
        "source_refs": source_refs,
        "batch_count": batch_count,
    }


def _normalize_visual_anchors(value: Any) -> list[dict[str, str]]:
    """视觉锚点归一为 [{type, description}] 列表。

    兼容：list[dict] / list[str] / Python 字典字符串 / JSON 字符串 / 纯文本行。
    """
    items: list[dict[str, str]] = []

    def push(type_value: Any, description_value: Any) -> None:
        desc = str(description_value or "").strip().strip("\"'")
        if not desc:
            return
        items.append({"type": str(type_value or "细节").strip() or "细节", "description": desc})

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                push(item.get("type"), item.get("description"))
            elif str(item or "").strip():
                push("细节", item)
        return items

    text = str(value or "").strip()
    if not text:
        return items
    parsed: Any = None
    import json as _json
    try:
        parsed = _json.loads(text)
    except Exception:
        try:
            parsed = _json.loads(text.replace("'", '"'))
        except Exception:
            parsed = None
    if isinstance(parsed, list):
        return _normalize_visual_anchors(parsed)
    for line in text.splitlines():
        line = line.strip().strip(",")
        if not line:
            continue
        match = re.match(r"^['\"]?type['\"]?\s*[:：]\s*['\"]?([\w-]+)['\"]?[,，]\s*['\"]?description['\"]?\s*[:：]\s*['\"]?(.+?)['\"]?\s*$", line)
        if match:
            push(match.group(1), match.group(2))
            continue
        colon = re.match(r"^([\w一-龥-]+)\s*[:：]\s*(.+)$", line)
        if colon:
            push(colon.group(1), colon.group(2))
        else:
            push("细节", line)
    return items


async def generate_structured_screenplay(
    *,
    content: str,
    api_key: str | None = None,
    max_scenes: int = 30,
) -> dict[str, Any]:
    """把剧本/正文文本转换为带多节拍的结构化剧本（与生产环境剧本审核同构）。

    复用 NOVEL_TO_SHORT_DRAMA_SCREENPLAY prompt 与宽松 JSON 修复链路；
    返回 {"screenplay_text", "scenes": [{scene_id,title,location,time_of_day,
    characters,scene_purpose,visual_anchors,beats[],transition_to_next_scene,
    duration_seconds,duration_reason}]}。
    """
    from services import deepseek as deepseek_service
    from services.video_chapter_prompts import (
        NOVEL_TO_SHORT_DRAMA_SCREENPLAY_SYSTEM_PROMPT,
        NOVEL_TO_SHORT_DRAMA_SCREENPLAY_USER_PROMPT_HEADER,
    )

    text = (content or "").strip()
    if not text:
        raise ValueError("内容为空，无法生成结构化剧本")

    payload: dict[str, Any] = {
        "model": deepseek_service.runtime_model(),
        "messages": [
            {"role": "system", "content": NOVEL_TO_SHORT_DRAMA_SCREENPLAY_SYSTEM_PROMPT},
            {"role": "user", "content": NOVEL_TO_SHORT_DRAMA_SCREENPLAY_USER_PROMPT_HEADER + "\n\n" + text},
        ],
        "stream": False,
        "max_tokens": 32768,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    try:
        async with httpx.AsyncClient(timeout=ADAPT_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
        resp.raise_for_status()
        data = deepseek_service._response_json(resp, context="DeepSeek")
    except httpx.TimeoutException as exc:
        raise UpstreamServiceError(
            "剧本结构化响应超时，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=504,
            code="screenplay_structure_timeout",
        ) from exc
    except httpx.HTTPStatusError as exc:
        status_code = int(exc.response.status_code)
        raise UpstreamServiceError(
            "剧本结构化服务暂时不可用，请稍后重试",
            retryable=status_code in {408, 409, 425, 429, 500, 502, 503, 504},
            provider="DeepSeek",
            status_code=status_code,
            code="screenplay_structure_failed",
            diagnostics={"upstream_status_code": status_code},
        ) from exc
    except httpx.RequestError as exc:
        raise UpstreamServiceError(
            "剧本结构化网络连接失败，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_structure_network_error",
        ) from exc

    raw_content = ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        raw_content = message.get("content") if isinstance(message.get("content"), str) else ""
    if not raw_content.strip():
        raise UpstreamServiceError(
            "剧本结构化未返回可用内容，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_structure_empty",
        )

    # 复用轻量拆镜同一套宽松 JSON 修复链路（AGENTS.md 陷阱 17）
    screenplay_json: Any = None
    try:
        screenplay_json = deepseek_service._loads_json_lenient(raw_content)
        if not isinstance(screenplay_json, dict):
            raise ValueError(f"非 JSON 对象: {type(screenplay_json).__name__}")
    except Exception:
        from services.deepseek import _extract_json_object, _repair_broken_json_fields, _repair_truncated_json
        try:
            screenplay_json = _extract_json_object(raw_content)
        except ValueError:
            repaired = _repair_broken_json_fields(raw_content)
            if repaired != raw_content:
                try:
                    screenplay_json = _extract_json_object(repaired)
                except ValueError as exc:
                    raise UpstreamServiceError(
                        f"剧本 JSON 修复失败: {exc}",
                        retryable=True,
                        provider="DeepSeek",
                        status_code=502,
                        code="screenplay_structure_parse_failed",
                    ) from exc
            else:
                truncated = _repair_truncated_json(raw_content)
                if truncated != raw_content:
                    try:
                        screenplay_json = _extract_json_object(truncated)
                    except ValueError as exc:
                        raise UpstreamServiceError(
                            f"剧本 JSON 截断修复后仍无法解析: {exc}",
                            retryable=True,
                            provider="DeepSeek",
                            status_code=502,
                            code="screenplay_structure_parse_failed",
                        ) from exc
                else:
                    raise UpstreamServiceError(
                        "剧本 JSON 解析错误，且未发现可修复的损坏字段",
                        retryable=True,
                        provider="DeepSeek",
                        status_code=502,
                        code="screenplay_structure_parse_failed",
                    )

    raw_scenes = screenplay_json.get("scenes") if isinstance(screenplay_json, dict) else None
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise UpstreamServiceError(
            "剧本结构化结果缺少 scenes 数组，请重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_structure_no_scenes",
        )

    scenes: list[dict[str, Any]] = []
    for index, raw_scene in enumerate(raw_scenes, start=1):
        if not isinstance(raw_scene, dict):
            continue
        raw_beats = raw_scene.get("beats")
        beats: list[dict[str, Any]] = []
        if isinstance(raw_beats, list):
            for beat_index, raw_beat in enumerate(raw_beats, start=1):
                if not isinstance(raw_beat, dict):
                    continue
                beats.append(
                    {
                        "beat_id": int(raw_beat.get("beat_id") or beat_index),
                        "type": str(raw_beat.get("type") or "action"),
                        "importance": str(raw_beat.get("importance") or "medium"),
                        "emotion_shift": str(raw_beat.get("emotion_shift") or ""),
                        "action": str(raw_beat.get("action") or ""),
                        "dialogue": raw_beat.get("dialogue") if raw_beat.get("dialogue") is not None else [],
                        "transition_to_next": str(raw_beat.get("transition_to_next") or ""),
                    }
                )
        anchors = _normalize_visual_anchors(raw_scene.get("visual_anchors"))
        beat_count = max(1, len(beats))
        # 动态时长：按节拍数估算，上限 15 秒（归一化在视频提交前再做）
        duration = min(15, max(3, beat_count * 4))
        scenes.append(
            {
                "scene_id": int(raw_scene.get("scene_id") or index),
                "title": str(raw_scene.get("title") or f"场景 {index}"),
                "location": str(raw_scene.get("location") or ""),
                "time_of_day": str(raw_scene.get("time_of_day") or ""),
                "characters": [str(c) for c in (raw_scene.get("characters") or []) if str(c).strip()],
                "scene_purpose": str(raw_scene.get("scene_purpose") or ""),
                "visual_anchors": anchors,
                "beats": beats,
                "transition_to_next_scene": str(raw_scene.get("transition_to_next_scene") or ""),
                "duration_seconds": duration,
                "duration_reason": f"按 {beat_count} 个节拍估算",
            }
        )
        if len(scenes) >= max_scenes:
            break

    if not scenes:
        raise UpstreamServiceError(
            "剧本结构化结果为空，请重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="screenplay_structure_no_scenes",
        )

    logger.info(
        "screenplay_structure.done scenes=%s beats_total=%s",
        len(scenes),
        sum(len(s["beats"]) for s in scenes),
    )
    return {
        "screenplay_text": str(screenplay_json.get("screenplay") or "") if isinstance(screenplay_json, dict) else "",
        "scenes": scenes,
        "truncated": len(raw_scenes) > max_scenes,
    }
