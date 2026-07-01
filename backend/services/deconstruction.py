"""
拆书服务：编排长篇拆文 Stage 0-6 管道。
参考 oh-story-claudecode story-long-analyze 方法论。
"""

import asyncio
import json
import logging

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from models import DeconstructionResult, PlatformSetting, Story, Chapter
from services.deepseek import _deepseek_auth_headers, _loads_json_lenient, configure_runtime
import services.deepseek as _deepseek
from prompts.deconstruction import (
    STAGE_0_SUMMARY_SYSTEM, STAGE_0_SUMMARY_USER,
    STAGE_1_GOLDEN_CHAPTERS_SYSTEM, STAGE_1_GOLDEN_CHAPTERS_USER,
    STAGE_2_CHAPTER_SUMMARY_SYSTEM, STAGE_2_CHAPTER_SUMMARY_USER,
    STAGE_3_AGGREGATION_SYSTEM, STAGE_3_AGGREGATION_USER,
    STAGE_4_SETTINGS_SYSTEM, STAGE_4_SETTINGS_USER,
    STAGE_5_REPORT_SYSTEM, STAGE_5_REPORT_USER,
    STAGE_6_STYLE_SYSTEM, STAGE_6_STYLE_USER,
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
            if exc.response.status_code == 524 and attempt < 2:
                logger.warning(f"DeepSeek 524 timeout, retry {attempt + 1}/3 after 8s")
                await asyncio.sleep(8)
                last_exc = exc
                continue
            _raise_model_provider_error(exc)
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            if attempt < 2:
                logger.warning(f"DeepSeek client timeout, retry {attempt + 1}/3 after 8s")
                await asyncio.sleep(8)
                last_exc = exc
                continue
            raise RuntimeError("text model timeout 3 times") from exc
    raise RuntimeError("text model 524 timeout 3 retries failed") from last_exc


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
            if exc.response.status_code == 524 and attempt < 2:
                logger.warning(f"DeepSeek 524 timeout, retry {attempt + 1}/3 after 8s")
                await asyncio.sleep(8)
                last_exc = exc
                continue
            _raise_model_provider_error(exc)
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            if attempt < 2:
                logger.warning(f"DeepSeek client timeout, retry {attempt + 1}/3 after 8s")
                await asyncio.sleep(8)
                last_exc = exc
                continue
            raise RuntimeError("text model timeout 3 times") from exc
    raise RuntimeError("text model 524 timeout 3 retries failed") from last_exc


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


async def run_deconstruction_pipeline(
    story_id: int,
    api_key: str,
    task_id: str | None = None,
    start_stage: int = 0,
    **kwargs,
) -> dict:
    """运行完整拆书管道 Stage 0-6。

    Args:
        story_id: 故事 ID
        api_key: DeepSeek API Key
        task_id: 后台任务 ID（用于进度更新和取消检测）
        start_stage: 起始阶段（续跑时使用）

    Returns:
        {"status": "completed", "result_id": int}
    """
    db = SessionLocal()
    try:
        _configure_deepseek_from_db(db)

        if not api_key:
            api_key = _get_api_key_from_db(db)

        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            raise ValueError(f"故事 {story_id} 不存在")

        chapters = db.query(Chapter).filter(
            Chapter.story_id == story_id,
            Chapter.novel_content.isnot(None),
            Chapter.novel_content != "",
            Chapter.content_source.in_(["crawled", None]),
        ).order_by(Chapter.chapter_number).all()

        if len(chapters) < 3:
            raise ValueError("至少需要 3 章有内容的章节才能拆书")

        # 创建或恢复 DeconstructionResult
        result = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status.in_(["pending", "running"]),
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not result:
            result = DeconstructionResult(
                story_id=story_id,
                status="running",
                current_stage=start_stage,
                stages_completed=[],
                task_id=task_id,
            )
            db.add(result)
            db.commit()
            db.refresh(result)
        else:
            result.current_stage = start_stage
            result.status = "running"
            db.commit()

        try:
            # Stage 0: 概要提取
            if result.current_stage <= 0:
                _update_progress(result, db, "Stage 0: 概要提取中...")
                sample_text = ""
                for ch in chapters[:5]:
                    sample_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.novel_content or '')[:2000]}"
                title_lines = [f"第{ch.chapter_number}章 {ch.title or ''} ({_count_words(ch.novel_content)}字)" for ch in chapters]
                all_titles = _truncate_title_list(title_lines)
                response = await _call_deepseek_json(
                    STAGE_0_SUMMARY_SYSTEM,
                    STAGE_0_SUMMARY_USER.format(chapter_text=f"章节列表：\n{all_titles}\n\n样本内容：\n{sample_text}"),
                    api_key,
                )
                result.summary = response
                result.current_stage = 1
                db.commit()

            # Stage 1: 黄金三章深度拆解
            if result.current_stage <= 1:
                _update_progress(result, db, "Stage 1: 黄金三章深度拆解中...")
                golden_text = ""
                for ch in chapters[:3]:
                    golden_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.novel_content or '')}"
                response = await _call_deepseek_json(
                    STAGE_1_GOLDEN_CHAPTERS_SYSTEM,
                    STAGE_1_GOLDEN_CHAPTERS_USER.format(chapter_text=golden_text),
                    api_key,
                )
                result.golden_chapters = response
                result.current_stage = 2
                db.commit()

            # Stage 2: 逐章摘要（并发控制）
            if result.current_stage <= 2:
                semaphore = asyncio.Semaphore(STAGE2_CHAPTER_CONCURRENCY)
                db_lock = asyncio.Lock()
                completed = [0]
                total = len(chapters)
                fatal_error_seen = asyncio.Event()

                async def _summarize_one(ch, index: int):
                    async with semaphore:
                        if fatal_error_seen.is_set():
                            raise FatalModelProviderError("文本模型上游已返回致命错误，已停止继续提交逐章摘要请求。任务失败后，本次拆书次数会自动返还。")
                        try:
                            response = await _call_deepseek_json(
                                STAGE_2_CHAPTER_SUMMARY_SYSTEM,
                                STAGE_2_CHAPTER_SUMMARY_USER.format(
                                    chapter_number=ch.chapter_number,
                                    chapter_title=ch.title or "",
                                    word_count=_count_words(ch.novel_content),
                                    chapter_text=ch.novel_content or "",
                                ),
                                api_key,
                            )
                            async with db_lock:
                                completed[0] += 1
                                if should_flush_stage2_progress(completed[0], total):
                                    _update_progress(result, db, f"Stage 2: 逐章摘要 ({completed[0]}/{total})...")
                            return (index, response)
                        except FatalModelProviderError:
                            fatal_error_seen.set()
                            raise
                        except Exception as e:
                            logger.error(f"第{ch.chapter_number}章摘要失败: {e}")
                            async with db_lock:
                                completed[0] += 1
                                if should_flush_stage2_progress(completed[0], total):
                                    _update_progress(result, db, f"Stage 2: 逐章摘要 ({completed[0]}/{total}) - 第{ch.chapter_number}章失败")
                            return (index, {"chapter_number": ch.chapter_number, "error": str(e)})

                results = await asyncio.gather(
                    *[_summarize_one(ch, i) for i, ch in enumerate(chapters)]
                )
                # 按原始序号排序，保证顺序一致性
                results.sort(key=lambda x: x[0])
                result.chapter_summaries = [r[1] for r in results]
                result.current_stage = 3
                db.commit()

            # Stage 3: 聚合分析
            if result.current_stage <= 3:
                _update_progress(result, db, "Stage 3: 聚合分析中...")
                response = await _run_stage3_aggregation(
                    result.chapter_summaries,
                    api_key,
                    lambda message: _update_progress(result, db, message),
                )
                result.plot_lines = response.get("plot_lines")
                result.rhythm = response.get("rhythm")
                result.emotion_modules = response.get("emotion_modules")
                # 暂存合并角色数据
                merged = response.get("merged_characters", {})
                result.progress_markdown = (result.progress_markdown or "") + "\n## STAGE3_MERGED\n" + json.dumps(merged, ensure_ascii=False)
                result.current_stage = 4
                db.commit()

            # Stage 4: 设定+关系
            if result.current_stage <= 4:
                _update_progress(result, db, "Stage 4: 设定+关系提取中...")
                summaries_text = _truncate_json_for_context(result.chapter_summaries, 15000)
                merged = "{}"
                if result.progress_markdown and "## STAGE3_MERGED" in result.progress_markdown:
                    merged = result.progress_markdown.split("## STAGE3_MERGED\n", 1)[1].split("\n## ")[0]
                response = await _call_deepseek_json(
                    STAGE_4_SETTINGS_SYSTEM,
                    STAGE_4_SETTINGS_USER.format(chapter_summaries=summaries_text, merged_characters=merged),
                    api_key,
                )
                result.worldbuilding = response.get("worldbuilding")
                result.characters = response.get("character_profiles")
                result.character_relations = response.get("character_relations")
                result.current_stage = 5
                db.commit()

            # Stage 5: 汇总报告（截断大字段防止超出上下文限制）
            if result.current_stage <= 5:
                _update_progress(result, db, "Stage 5: 汇总报告中...")
                summary = result.summary or {}
                response = await _call_deepseek_text(
                    STAGE_5_REPORT_SYSTEM,
                    STAGE_5_REPORT_USER.format(
                        title=summary.get("title", "未知"),
                        genre=summary.get("genre", "未知"),
                        total_chapters=summary.get("estimated_total_chapters", 0),
                        total_words=summary.get("estimated_total_words", 0),
                        golden_chapters=_truncate_json_for_context(result.golden_chapters, 8000),
                        chapter_summaries=_truncate_json_for_context(result.chapter_summaries, 15000),
                        characters=_truncate_json_for_context(result.characters, 8000),
                        character_relations=_truncate_json_for_context(result.character_relations, 5000),
                        plot_lines=_truncate_json_for_context(result.plot_lines, 5000),
                        rhythm=_truncate_json_for_context(result.rhythm, 3000),
                        emotion_modules=_truncate_json_for_context(result.emotion_modules, 3000),
                        worldbuilding=_truncate_json_for_context(result.worldbuilding, 5000),
                    ),
                    api_key,
                )
                result.report_markdown = response
                result.current_stage = 6
                db.commit()

            # Stage 6: 文风分析
            if result.current_stage <= 6:
                _update_progress(result, db, "Stage 6: 文风分析中...")
                samples = []
                for i, ch in enumerate(chapters):
                    if i < 3 or i % 10 == 0:
                        samples.append(f"## 第{ch.chapter_number}章\n\n{(ch.novel_content or '')[:3000]}")
                golden_text = json.dumps(result.golden_chapters, ensure_ascii=False, indent=2)[:5000]
                summaries_text = json.dumps(result.chapter_summaries, ensure_ascii=False, indent=2)[:5000]
                response = await _call_deepseek_json(
                    STAGE_6_STYLE_SYSTEM,
                    STAGE_6_STYLE_USER.format(
                        chapter_summaries=summaries_text,
                        golden_chapters_text=golden_text,
                        original_text_samples="\n\n".join(samples),
                    ),
                    api_key,
                )
                result.writing_style = response
                result.writing_techniques = response.get("techniques", [])
                result.current_stage = 7
                db.commit()

            result.status = "completed"
            result.stages_completed = [0, 1, 2, 3, 4, 5, 6]
            db.commit()

            return {"status": "completed", "result_id": result.id}

        except Exception as e:
            logger.error(f"拆书管道 Stage {result.current_stage} 失败: {e}")
            result.status = "failed"
            result.progress_markdown = (result.progress_markdown or "") + f"\n\n## Stage {result.current_stage} 失败\n{str(e)}"
            db.commit()
            raise

    finally:
        db.close()
