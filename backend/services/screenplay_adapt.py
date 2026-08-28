"""小说章节正文 → 漫剧剧本改写服务。

只读原作品：路由层负责校验章节所有权并传入内容，本层不做 IO 之外的数据库操作，
也绝不回写任何章节。产出画布剧本节点的初始剧本文本与来源溯源信息。
"""

from __future__ import annotations

import hashlib
import logging
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
