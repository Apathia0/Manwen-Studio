"""
拆书服务：共享工具模块（DeepSeek 调用、摘要聚合、进度更新等）。
被 deconstruction_v2.py（故事侧 V2 管线）和 deconstruct_library.py（独立拆文库）共用。
"""

import asyncio
import json
import logging

import httpx
from sqlalchemy.orm import Session

from models import DeconstructionResult, PlatformSetting
from services.deepseek import _deepseek_auth_headers, _loads_json_lenient, configure_runtime
import services.deepseek as _deepseek
from prompts.deconstruction import (
    STAGE_3_AGGREGATION_SYSTEM, STAGE_3_AGGREGATION_USER,
)

logger = logging.getLogger(__name__)

STAGE2_CHAPTER_CONCURRENCY = 5
STAGE2_PROGRESS_FLUSH_INTERVAL = 10
STAGE3_DIRECT_SUMMARY_LIMIT = 80
STAGE3_CHUNK_SIZE = 60


def should_flush_stage2_progress(completed: int, total: int) -> bool:
    return completed >= total or completed % STAGE2_PROGRESS_FLUSH_INTERVAL == 0


STAGE0_TITLE_LIST_MAX_CHARS = 15000

def _truncate_title_list(title_lines: list[str]) -> str:
    """截断过长的标题列表，防止 Stage 0 输入超出模型处理能力触发超时。"""
    if not title_lines:
        return ""
    joined = "\n".join(title_lines)
    if len(joined) <= STAGE0_TITLE_LIST_MAX_CHARS:
        return joined
    keep_front = min(80, len(title_lines) // 2)
    keep_back = min(40, len(title_lines) - keep_front)
    front = title_lines[:keep_front]
    back = title_lines[-keep_back:] if keep_back > 0 else []
    skipped = len(title_lines) - keep_front - keep_back
    return "\n".join(front + [f"（中间省略 {skipped} 章）"] + back)

FATAL_MODEL_PROVIDER_STATUS_CODES = {401, 402, 403, 429}


class FatalModelProviderError(RuntimeError):
    """上游文本模型不可继续重试的错误。"""


def _format_model_provider_error(exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    if status_code == 401:
        reason = "文本模型 API Key 无效或未授权"
    elif status_code == 402:
        reason = "文本模型服务余额不足或上游账号欠费"
    elif status_code == 403:
        reason = "文本模型账号没有当前模型或接口权限"
    elif status_code == 429:
        reason = "文本模型请求过于频繁，或已触发上游额度/速率限制"
    elif status_code == 524:
        reason = "文本模型响应超时，可能因为输入内容过长或上游服务繁忙，可尝试减少章节数量后重试"
    elif 500 <= status_code <= 599:
        reason = "文本模型上游服务异常"
    else:
        reason = "文本模型上游请求失败"
    return f"{reason}（HTTP {status_code}），请检查后台 DeepSeek/API 中转配置与账号状态。任务失败后，本次拆书次数会自动返还。"


def _raise_model_provider_error(exc: httpx.HTTPStatusError) -> None:
    message = _format_model_provider_error(exc)
    if exc.response.status_code in FATAL_MODEL_PROVIDER_STATUS_CODES:
        raise FatalModelProviderError(message) from exc
    raise RuntimeError(message) from exc


def _configure_deepseek_from_db(db: Session):
    """从数据库 PlatformSetting 读取 DeepSeek 配置并注入运行时"""
    base_url = db.query(PlatformSetting).filter(PlatformSetting.setting_key == "api.deepseek.base_url").first()
    model = db.query(PlatformSetting).filter(PlatformSetting.setting_key == "api.deepseek.model").first()
    logger.info(f"DeepSeek 配置: base_url={base_url.setting_key if base_url else 'None'}, model={model.setting_key if model else 'None'}")
    if base_url and base_url.value_json:
        base_url_val = (base_url.value_json or {}).get("value")
        model_val = (model.value_json or {}).get("value") if model else None
        logger.info(f"注入 DeepSeek 运行时: base_url={base_url_val}, model={model_val}")
        configure_runtime(base_url=base_url_val, model=model_val)
    else:
        logger.warning(f"DeepSeek 配置缺失: base_url 存在={base_url is not None}, value_json={base_url.value_json if base_url else 'N/A'}")


def _get_api_key_from_db(db: Session) -> str | None:
    """从数据库读取 DeepSeek API Key"""
    row = db.query(PlatformSetting).filter(PlatformSetting.setting_key == "api.deepseek.api_key").first()
    if row and row.value_json:
        return (row.value_json or {}).get("value")
    return None


async def _call_deepseek_json(system: str, user: str, api_key: str | None = None) -> dict:
    """调用 DeepSeek，返回 JSON 解析结果。"""
    if not _deepseek.DEEPSEEK_BASE_URL:
        raise ValueError("DeepSeek API 地址未配置，请先调用 _configure_deepseek_from_db")
    payload = {
        "model": _deepseek.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    last_exc = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{_deepseek.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return _loads_json_lenient(content)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 524) and attempt < 2:
                logger.warning(f"DeepSeek {exc.response.status_code}, retry {attempt + 1}/3 after 15s")
                await asyncio.sleep(15)
                last_exc = exc
                continue
            _raise_model_provider_error(exc)
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            if attempt < 2:
                logger.warning(f"DeepSeek client timeout, retry {attempt + 1}/3 after 15s")
                await asyncio.sleep(15)
                last_exc = exc
                continue
            raise RuntimeError("text model timeout 3 times") from exc
    raise RuntimeError("text model non-200 3 retries failed") from last_exc


async def _call_deepseek_text(system: str, user: str, api_key: str | None = None) -> str:
    """调用 DeepSeek，返回纯文本。"""
    if not _deepseek.DEEPSEEK_BASE_URL:
        raise ValueError("DeepSeek API 地址未配置，请先调用 _configure_deepseek_from_db")
    payload = {
        "model": _deepseek.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    last_exc = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{_deepseek.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 524) and attempt < 2:
                logger.warning(f"DeepSeek {exc.response.status_code}, retry {attempt + 1}/3 after 15s")
                await asyncio.sleep(15)
                last_exc = exc
                continue
            _raise_model_provider_error(exc)
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            if attempt < 2:
                logger.warning(f"DeepSeek client timeout, retry {attempt + 1}/3 after 15s")
                await asyncio.sleep(15)
                last_exc = exc
                continue
            raise RuntimeError("text model timeout 3 times") from exc
    raise RuntimeError("text model non-200 3 retries failed") from last_exc


def _count_words(text: str | None) -> int:
    """统计中文字数"""
    if not text:
        return 0
    return len(text.replace("\n", "").replace(" ", ""))


def _truncate_json_for_context(data: list | dict | None, max_chars: int = 15000) -> str:
    """截断大 JSON 数据，防止超出 DeepSeek 上下文限制。

    对于列表：保留前 N 项 + 最后 3 项，中间插入省略标记。
    对于字典：截断每个值的长度。
    """
    if data is None:
        return "{}" if isinstance(data, dict) else "[]"

    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text

    if isinstance(data, list) and len(data) > 5:
        kept = min(len(data) // 3, 10)
        truncated = data[:kept] + [
            {"_truncated": True, "_skipped": len(data) - kept - min(3, len(data) - kept)}
        ] + data[-min(3, len(data) - kept):]
        text = json.dumps(truncated, ensure_ascii=False, indent=2)
        if len(text) > max_chars:
            text = text[:max_chars - 50] + "\n  ...\n]"
        return text

    return text[:max_chars - 50] + "\n  ...\n}" if isinstance(data, dict) else text[:max_chars - 50] + "\n  ...\n]"


def _chunk_list(items: list, chunk_size: int) -> list[list]:
    """按固定大小切分列表。"""
    if chunk_size <= 0:
        return [items]
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


async def _run_stage3_aggregation(
    chapter_summaries: list | None,
    api_key: str | None,
    progress_callback=None,
) -> dict:
    """对长篇章节摘要进行分块聚合，避免单次请求上下文过大。"""
    summaries = [item for item in (chapter_summaries or []) if isinstance(item, dict)]
    if not summaries:
        return {}

    if len(summaries) <= STAGE3_DIRECT_SUMMARY_LIMIT:
        summaries_text = json.dumps(summaries, ensure_ascii=False, indent=2)
        return await _call_deepseek_json(
            STAGE_3_AGGREGATION_SYSTEM,
            STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=summaries_text),
            api_key,
        )

    chunk_results: list[dict] = []
    chunks = _chunk_list(summaries, STAGE3_CHUNK_SIZE)
    total_chunks = len(chunks)

    for index, chunk in enumerate(chunks, start=1):
        if progress_callback:
            progress_callback(f"Stage 3: 聚合分析分块 {index}/{total_chunks}...")
        chunk_text = _truncate_json_for_context(chunk, 22000)
        response = await _call_deepseek_json(
            STAGE_3_AGGREGATION_SYSTEM,
            STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=chunk_text),
            api_key,
        )
        chunk_results.append({
            "chunk_index": index,
            "chapter_start": chunk[0].get("chapter_number"),
            "chapter_end": chunk[-1].get("chapter_number"),
            "story_framework": response.get("story_framework"),
            "plot_lines": response.get("plot_lines"),
            "story_line_summary": response.get("story_line_summary"),
            "rhythm": response.get("rhythm"),
            "emotion_modules": response.get("emotion_modules"),
            "merged_characters": response.get("merged_characters"),
            "orphan_plots": response.get("orphan_plots"),
        })

    if progress_callback:
        progress_callback("Stage 3: 汇总分块结果中...")
    merged_text = json.dumps(chunk_results, ensure_ascii=False, indent=2)
    return await _call_deepseek_json(
        STAGE_3_AGGREGATION_SYSTEM,
        STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=merged_text),
        api_key,
    )


def _update_progress(result: DeconstructionResult, db: Session, message: str):
    """更新进度信息到数据库"""
    result.progress_markdown = (result.progress_markdown or "") + f"\n- {message}"
    db.commit()



