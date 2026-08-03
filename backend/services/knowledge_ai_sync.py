from __future__ import annotations

import asyncio
import ast
import hashlib
import json
import os
import re
from typing import Any

import httpx

from database import SessionLocal
from models import BackgroundTask, Chapter, Story, StoryKnowledgeEntity, StoryKnowledgeFact, StoryKnowledgeResource, StoryPlotThread
from services.deepseek import _deepseek_auth_headers, _extract_json_object, _response_json, runtime_base_url, runtime_model
from services.task_manager import task_manager


SYNC_CONCURRENCY = max(1, min(12, int(os.getenv("KNOWLEDGE_AI_SYNC_CONCURRENCY", "6") or "6")))
SOURCE_CHUNK_SIZE = 8000
SYNC_EXTRACTION_ATTEMPTS = 2
SYNC_COLLECTION_TIMEOUT = max(60, min(840, int(os.getenv("KNOWLEDGE_AI_SYNC_COLLECTION_TIMEOUT", "840") or "840")))
SYNC_SCHEMA_VERSION = 3
SYNC_SCOPES = {"all", "entities", "facts", "plot_threads"}


class KnowledgeSyncInputChangedError(RuntimeError):
    """同步分析期间作品内容发生变化，需要基于新快照重试。"""

    retryable = True


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content or "")


def _parse_sync_json(content: Any) -> dict[str, Any]:
    raw = _message_content_text(content).strip()
    if not raw:
        raise ValueError("模型返回了空内容")
    try:
        return _extract_json_object(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as first_error:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
        decoder = json.JSONDecoder(strict=False)
        for index, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        without_trailing_commas = re.sub(r",\s*([}\]])", r"\1", cleaned)
        candidates = [without_trailing_commas]
        object_match = re.search(r"\{[\s\S]*\}", without_trailing_commas)
        if object_match and object_match.group(0) != without_trailing_commas:
            candidates.append(object_match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate, strict=False)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            try:
                parsed = ast.literal_eval(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (SyntaxError, ValueError):
                pass
        raise ValueError("模型返回的同步结果不是有效 JSON") from first_error


def _result_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value, strict=False)
        except json.JSONDecodeError as exc:
            raise ValueError("同步结果数组不是有效 JSON") from exc
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("同步结果字段必须是数组")
    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            items.append(item)
        elif isinstance(item, str):
            try:
                parsed = json.loads(item, strict=False)
            except json.JSONDecodeError as exc:
                raise ValueError("同步结果包含无法解析的数组条目") from exc
            if not isinstance(parsed, dict):
                raise ValueError("同步结果数组条目必须是对象")
            items.append(parsed)
        else:
            raise ValueError("同步结果数组条目必须是对象")
    return items


def _normalize_sync_result(value: dict[str, Any]) -> dict[str, Any]:
    required_keys = ("entities", "facts")
    missing = [key for key in required_keys if key not in value]
    if "plot_threads" not in value and "plotThreads" not in value:
        missing.append("plot_threads")
    if missing:
        raise ValueError(f"同步结果缺少字段：{', '.join(missing)}")
    plot_threads = value["plot_threads"] if "plot_threads" in value else value["plotThreads"]
    result = {
        "entities": _result_items(value.get("entities")),
        "facts": _result_items(value.get("facts")),
        "plot_threads": _result_items(plot_threads),
    }
    requirements = {
        "entities": ("canonical_name",),
        "facts": ("subject_key", "predicate"),
        "plot_threads": ("title",),
    }
    for kind, required_fields in requirements.items():
        for item in result[kind]:
            if any(not isinstance(item.get(field), str) or not item[field].strip() for field in required_fields):
                raise ValueError(f"同步结果中的 {kind} 条目缺少必填字段")
    return result


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text, strict=False)
            value = parsed if isinstance(parsed, list) else [text]
        except json.JSONDecodeError:
            value = [item.strip() for item in re.split(r"[,，;；\n]+", text) if item.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:item_limit] for item in value if str(item).strip()][:limit]


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_key(value: Any, prefix: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff:_-]+", "-", str(value or "").strip()).strip("-")
    if text:
        return text[:140]
    return f"{prefix}:{hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:20]}"


def _source_key(kind: str, source_id: str, stable_key: str) -> str:
    scope = _source_scope(source_id)
    digest = hashlib.sha256(f"{scope}:{stable_key}".encode("utf-8")).hexdigest()[:24]
    scope_token = f"c{scope.split(':', 1)[1]}" if scope.startswith("chapter:") else f"s{scope.split(':')[1]}"
    return f"ai_sync:v{SYNC_SCHEMA_VERSION}:{kind}:{scope_token}:{digest}"


def _source_scope(source_id: str) -> str:
    parts = str(source_id or "").split(":")
    if len(parts) >= 2 and parts[0] == "chapter":
        return f"chapter:{parts[1]}"
    if len(parts) >= 2 and parts[0] == "story":
        return f"story:{parts[1]}:static"
    return str(source_id or "story")


def _source_chapter_id(source_id: str) -> int | None:
    scope = _source_scope(source_id)
    if not scope.startswith("chapter:"):
        return None
    try:
        return int(scope.split(":", 1)[1])
    except (TypeError, ValueError):
        return None


def _fact_row_scope(row: StoryKnowledgeFact, story_id: int) -> str:
    source_id = str(row.source_id or "")
    match = re.match(r"^ai_sync:v3:fact:([cs])(\d+):", source_id)
    if match:
        return f"chapter:{match.group(2)}" if match.group(1) == "c" else f"story:{match.group(2)}:static"
    if row.source_chapter_id:
        return f"chapter:{row.source_chapter_id}"
    return f"story:{story_id}:static"


def _entity_row_scope(row: StoryKnowledgeEntity, story_id: int) -> str:
    """根据 AI 记录来源还原实体所属的静态资料或章节范围。"""
    source_id = str(row.source_id or "")
    match = re.match(r"^ai_sync:v3:entity:([cs])(\d+):", source_id)
    if match:
        return f"chapter:{match.group(2)}" if match.group(1) == "c" else f"story:{match.group(2)}:static"
    return f"story:{story_id}:static"


def _thread_row_scope(row: StoryPlotThread, story_id: int) -> str:
    source_id = str(row.source_id or "")
    match = re.match(r"^ai_sync:v3:thread:([cs])(\d+):", source_id)
    if match:
        return f"chapter:{match.group(2)}" if match.group(1) == "c" else f"story:{match.group(2)}:static"
    return f"story:{story_id}:static"


def _existing_ai_scopes(db, story_id: int, included: set[str]) -> set[str]:
    """收集当前作品已有 AI 记录的来源范围，用于全量同步清理孤立来源。"""
    scopes: set[str] = set()
    if "entities" in included:
        rows = db.query(StoryKnowledgeEntity).filter(
            StoryKnowledgeEntity.story_id == story_id,
            StoryKnowledgeEntity.source_type == "agent",
        ).all()
        scopes.update(_entity_row_scope(row, story_id) for row in rows if row.source_id)
    if "facts" in included:
        rows = db.query(StoryKnowledgeFact).filter(
            StoryKnowledgeFact.story_id == story_id,
            StoryKnowledgeFact.source_type == "agent",
        ).all()
        scopes.update(_fact_row_scope(row, story_id) for row in rows if row.source_id)
    if "plot_threads" in included:
        rows = db.query(StoryPlotThread).filter(
            StoryPlotThread.story_id == story_id,
            StoryPlotThread.source_type == "agent",
        ).all()
        scopes.update(_thread_row_scope(row, story_id) for row in rows if row.source_id)
    return scopes


def _chapter_fingerprint(chapter: Chapter) -> str:
    return _hash_json({
        "id": chapter.id,
        "chapter_number": chapter.chapter_number,
        "created_at": chapter.created_at,
        "title": chapter.title,
        "key_events": chapter.key_events,
        "memory_summary": chapter.memory_summary,
        "content": chapter.novel_content,
    })


def _build_sources(db, story: Story, previous_result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    if previous_result.get("sync_schema_version") != SYNC_SCHEMA_VERSION:
        previous_result = {}
    previous_fingerprints = previous_result.get("chapter_fingerprints") if isinstance(previous_result.get("chapter_fingerprints"), dict) else {}
    chapters = db.query(Chapter).filter(Chapter.story_id == story.id).order_by(Chapter.chapter_number.asc()).all()
    chapter_fingerprints = {str(chapter.id): _chapter_fingerprint(chapter) for chapter in chapters}
    resources = db.query(StoryKnowledgeResource).filter(
        StoryKnowledgeResource.story_id == story.id,
        StoryKnowledgeResource.status == "active",
    ).order_by(StoryKnowledgeResource.id.asc()).all()
    static_payload = {
        "title": story.title,
        "description": story.description,
        "tags": story.tags,
        "outline": story.outline,
        "characters": story.characters,
        "story_bible": story.story_bible,
        "story_memory": story.story_memory,
        "resources": [{"title": row.title, "summary": row.summary, "content": row.content_text or row.content_json} for row in resources],
    }
    static_hash = _hash_json(static_payload)
    sources: list[dict[str, Any]] = []
    if static_hash != previous_result.get("static_hash"):
        static_text = json.dumps(static_payload, ensure_ascii=False, default=str)
        for index in range(0, len(static_text), SOURCE_CHUNK_SIZE):
            sources.append({"source_id": f"story:{story.id}:static:{index // SOURCE_CHUNK_SIZE}", "chapter": None, "text": static_text[index:index + SOURCE_CHUNK_SIZE]})
    for chapter in chapters:
        if previous_fingerprints.get(str(chapter.id)) == chapter_fingerprints[str(chapter.id)]:
            continue
        chapter_text = json.dumps({
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "key_events": chapter.key_events,
            "memory_summary": chapter.memory_summary,
            "content": chapter.novel_content or "",
        }, ensure_ascii=False, default=str)
        for index in range(0, len(chapter_text), SOURCE_CHUNK_SIZE):
            sources.append({"source_id": f"chapter:{chapter.id}:{index // SOURCE_CHUNK_SIZE}", "chapter": chapter.chapter_number, "text": chapter_text[index:index + SOURCE_CHUNK_SIZE]})
    return sources, chapter_fingerprints, static_hash


def _existing_manifest(db, story_id: int) -> dict[str, Any]:
    entities = db.query(StoryKnowledgeEntity).filter(StoryKnowledgeEntity.story_id == story_id).all()
    facts = db.query(StoryKnowledgeFact).filter(StoryKnowledgeFact.story_id == story_id, StoryKnowledgeFact.status == "active").all()
    threads = db.query(StoryPlotThread).filter(StoryPlotThread.story_id == story_id, StoryPlotThread.status.in_(["open", "active", "due"])).all()
    return {
        "entities": [{"key": row.entity_key, "name": row.canonical_name, "type": row.entity_type} for row in entities[:300]],
        "facts": [{"subject": row.subject_key, "predicate": row.predicate, "object": row.object_key, "text": row.value_text} for row in facts[:300]],
        "threads": [{"key": row.thread_key, "title": row.title, "status": row.status} for row in threads[:200]],
    }


def _target_manifest(manifest: dict[str, Any], text: str) -> dict[str, Any]:
    normalized = text.casefold()

    def relevant(row: dict[str, Any], fields: tuple[str, ...]) -> bool:
        return any(str(row.get(field) or "").casefold() in normalized for field in fields if len(str(row.get(field) or "").strip()) >= 2)

    entities = [row for row in manifest.get("entities", []) if relevant(row, ("key", "name"))]
    facts = [row for row in manifest.get("facts", []) if relevant(row, ("subject", "object", "text"))]
    threads = [row for row in manifest.get("threads", []) if relevant(row, ("key", "title"))]
    return {
        "entities": (entities or manifest.get("entities", [])[:20])[:80],
        "facts": (facts or manifest.get("facts", [])[:10])[:60],
        "threads": (threads or manifest.get("threads", [])[:10])[:40],
    }


async def _extract_source(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    source: dict[str, Any],
    manifest: dict[str, Any],
    api_key: str | None,
    sync_scope: str = "all",
) -> dict[str, Any]:
    scope_instructions = {
        "all": "完整抽取三类数据。",
        "entities": "本次只同步实体主体，facts 和 plot_threads 必须返回空数组。",
        "facts": "本次只同步事件与连续性事实，entities 和 plot_threads 必须返回空数组。",
        "plot_threads": "本次只同步伏笔与剧情线，entities 和 facts 必须返回空数组。",
    }
    system_prompt = (
        "你是长篇小说连续性编辑。只抽取输入中明确存在的实体、事实、事件和伏笔，不得推测。"
        "返回 JSON 对象，包含 entities、facts、plot_threads 三个数组。"
        "实体字段：entity_key, canonical_name, entity_type, aliases_json, importance, first_chapter, last_chapter。"
        "事实字段：stable_key, subject_key, predicate, object_key, value_text, valid_from_chapter, valid_to_chapter, confidence。"
        "伏笔字段：thread_key, title, description, setup_chapter, expected_payoff_from, expected_payoff_to, actual_payoff_chapter, related_entity_keys, priority, status。"
        "关系两端必须优先使用清单中的 entity_key；无法确认章节则返回 null。stable_key/thread_key 必须稳定、简短。"
        "每次最多返回 40 个实体、80 条事实和 30 条伏笔；没有内容的数组返回 []。只输出一个 JSON 对象，不要 Markdown、注释或解释。"
        + scope_instructions.get(sync_scope, scope_instructions["all"])
    )
    user_payload = {
        "chapter": source.get("chapter"),
        "known": _target_manifest(manifest, str(source.get("text") or "")),
        "source": source.get("text"),
    }
    last_error: Exception | None = None
    for attempt in range(SYNC_EXTRACTION_ATTEMPTS):
        retry_instruction = "" if attempt == 0 else "上次返回无法解析。请减少条目数量并再次只返回完整 JSON 对象。"
        payload = {
            "model": runtime_model(),
            "messages": [
                {"role": "system", "content": system_prompt + retry_instruction},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }
        try:
            async with semaphore:
                response = await client.post(f"{runtime_base_url()}/chat/completions", json=payload, headers=_deepseek_auth_headers(api_key))
                response.raise_for_status()
            response_data = _response_json(response, context="DeepSeek")
            choices = response_data.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("DeepSeek 响应缺少 choices")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("DeepSeek 响应缺少 message")
            result = _normalize_sync_result(_parse_sync_json(message.get("content")))
            result["_source_id"] = source["source_id"]
            result["_source_chapter"] = source.get("chapter")
            return result
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code < 500 and status_code not in {408, 409, 425, 429}:
                raise
            last_error = exc
        except (httpx.TransportError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    raise ValueError(f"来源 {source['source_id']} 的 AI 同步结果连续 {SYNC_EXTRACTION_ATTEMPTS} 次不是有效 JSON") from last_error


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _bounded_int(value: Any, default: int, minimum: int = 0, maximum: int = 100) -> int:
    try:
        return max(minimum, min(maximum, int(float(value))))
    except (TypeError, ValueError):
        return default


def _bounded_float(value: Any, default: float, minimum: float = 0, maximum: float = 1) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def _retry_markers(
    fingerprints: dict[str, str],
    static_hash: str,
    previous_result: dict[str, Any],
    failed_source_ids: set[str],
) -> tuple[dict[str, str], str | None]:
    retry_fingerprints = dict(fingerprints)
    for source_id in failed_source_ids:
        if source_id.startswith("chapter:"):
            retry_fingerprints.pop(source_id.split(":", 2)[1], None)
    retry_static_hash = (
        previous_result.get("static_hash")
        if any(source_id.startswith("story:") for source_id in failed_source_ids)
        else static_hash
    )
    return retry_fingerprints, retry_static_hash


def _result_schema_version(previous_result: dict[str, Any], has_failures: bool) -> int | None:
    if has_failures:
        value = previous_result.get("sync_schema_version")
        return int(value) if isinstance(value, int) else None
    return SYNC_SCHEMA_VERSION


async def _collect_source_results(
    client: httpx.AsyncClient,
    sources: list[dict[str, Any]],
    manifest: dict[str, Any],
    api_key: str | None,
    task_id: str | None,
    semaphore: asyncio.Semaphore,
    sync_scope: str = "all",
) -> tuple[list[dict[str, Any]], list[str], set[str], bool]:
    async def extract_outcome(source_index: int, source: dict[str, Any]) -> tuple[int, str, dict[str, Any] | None, str | None]:
        try:
            result = (
                await _extract_source(client, semaphore, source, manifest, api_key)
                if sync_scope == "all"
                else await _extract_source(client, semaphore, source, manifest, api_key, sync_scope)
            )
            return source_index, source["source_id"], result, None
        except Exception as exc:
            return source_index, source["source_id"], None, str(exc)

    pending = [asyncio.create_task(extract_outcome(index, source)) for index, source in enumerate(sources)]
    task_sources = {task: source for task, source in zip(pending, sources)}
    ordered_results: list[tuple[int, dict[str, Any]]] = []
    failures: list[str] = []
    failed_source_ids: set[str] = set()
    timed_out = False
    try:
        remaining = set(pending)
        deadline = asyncio.get_running_loop().time() + SYNC_COLLECTION_TIMEOUT
        completed = 0
        while remaining:
            remaining_time = max(0, deadline - asyncio.get_running_loop().time())
            done, remaining = await asyncio.wait(
                remaining,
                timeout=remaining_time,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                timed_out = True
                break
            for task in sorted(done, key=lambda item: pending.index(item)):
                source_index, source_id, result, error = await task
                completed += 1
                if result is not None:
                    ordered_results.append((source_index, result))
                elif error:
                    failed_source_ids.add(source_id)
                    failures.append(error)
            task_manager.update_task_metadata(
                task_id,
                stage="extracting",
                message=f"正在并发分析作品更新 {completed}/{len(sources)}",
                completed=completed,
                total=len(sources),
            )
            if task_manager.is_cancellation_requested(task_id):
                raise asyncio.CancelledError
        if timed_out:
            for task in remaining:
                source_id = str(task_sources[task]["source_id"])
                failed_source_ids.add(source_id)
                failures.append(f"来源 {source_id} 超过同步时间预算")
            failures.sort()
            task_manager.update_task_metadata(
                task_id,
                stage="merging",
                message=f"同步时间预算已到，正在保存 {len(ordered_results)} 组有效结果",
                completed=len(ordered_results),
                total=len(sources),
            )
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    results = [result for _, result in sorted(ordered_results, key=lambda item: item[0])]
    return results, failures, failed_source_ids, timed_out


def _merge_results(
    db,
    story: Story,
    results: list[dict[str, Any]],
    *,
    reconcile_scopes: set[str] | None = None,
    deleted_chapter_ids: set[int] | None = None,
    archive_legacy: bool = False,
    include_kinds: set[str] | None = None,
) -> dict[str, int]:
    included = include_kinds or {"entities", "facts", "plot_threads"}
    counts = {
        "entities": 0,
        "facts": 0,
        "plot_threads": 0,
        "archived_facts": 0,
        "archived_plot_threads": 0,
    }
    entities = {row.entity_key: row for row in db.query(StoryKnowledgeEntity).filter_by(story_id=story.id).with_for_update().all()}
    fact_rows = db.query(StoryKnowledgeFact).filter_by(story_id=story.id).with_for_update().all()
    facts = {row.source_id: row for row in fact_rows if row.source_id}
    thread_rows = db.query(StoryPlotThread).filter_by(story_id=story.id).with_for_update().all()
    threads = {row.thread_key: row for row in thread_rows}
    emitted_entity_keys: dict[str, set[str]] = {}
    emitted_fact_sources: dict[str, set[str]] = {}
    emitted_thread_sources: dict[str, set[str]] = {}
    for result in results:
        source_id = str(result.get("_source_id") or "story")
        source_chapter_number = _int_or_none(result.get("_source_chapter"))
        source_scope = _source_scope(source_id)
        emitted_entity_keys.setdefault(source_scope, set())
        emitted_fact_sources.setdefault(source_scope, set())
        emitted_thread_sources.setdefault(source_scope, set())
        for raw in result.get("entities") if "entities" in included and isinstance(result.get("entities"), list) else []:
            if not isinstance(raw, dict) or not raw.get("canonical_name"):
                continue
            key = _stable_key(raw.get("entity_key") or raw.get("canonical_name"), "entity")
            row = entities.get(key)
            if row and row.source_type == "manual":
                continue
            if row is None:
                row = StoryKnowledgeEntity(story_id=story.id, entity_key=key, entity_type=str(raw.get("entity_type") or "other")[:40], canonical_name=str(raw["canonical_name"])[:255], source_type="agent", source_id=_source_key("entity", source_id, key))
                db.add(row)
                entities[key] = row
            else:
                row.version = int(row.version or 1) + 1
                row.entity_type = str(raw.get("entity_type") or row.entity_type or "other")[:40]
                row.canonical_name = str(raw.get("canonical_name") or row.canonical_name)[:255]
            aliases = _string_list(raw.get("aliases_json"), limit=20, item_limit=255)
            row.aliases_json = list(dict.fromkeys([*(row.aliases_json or []), *aliases]))[:20]
            row.importance = max(int(row.importance or 0), _bounded_int(raw.get("importance"), 50))
            first_chapter = _int_or_none(raw.get("first_chapter")) or source_chapter_number
            last_chapter = _int_or_none(raw.get("last_chapter"))
            row.first_chapter = min(value for value in (row.first_chapter, first_chapter) if value is not None) if row.first_chapter or first_chapter else None
            row.last_chapter = max(value for value in (row.last_chapter, last_chapter) if value is not None) if row.last_chapter or last_chapter else None
            row.status = "active"
            emitted_entity_keys[source_scope].add(key)
            counts["entities"] += 1
        for raw in result.get("facts") if "facts" in included and isinstance(result.get("facts"), list) else []:
            if not isinstance(raw, dict) or not raw.get("subject_key") or not raw.get("predicate"):
                continue
            stable = _stable_key(raw.get("stable_key") or f"{raw.get('subject_key')}:{raw.get('predicate')}:{raw.get('object_key') or raw.get('value_text')}", "fact")
            item_source = _source_key("fact", source_id, stable)
            row = facts.get(item_source)
            source_chapter_id = _source_chapter_id(source_id)
            if row is None:
                row = next((
                    candidate
                    for candidate in facts.values()
                    if candidate.source_type == "agent"
                    and candidate.source_id
                    and candidate.source_id.startswith("ai_sync:")
                    and candidate.subject_key == str(raw["subject_key"])[:160]
                    and candidate.predicate == str(raw["predicate"])[:100]
                    and (candidate.object_key or "") == str(raw.get("object_key") or "")[:160]
                    and (candidate.value_text or "") == str(raw.get("value_text") or "").strip()
                    # 章节来源只能复用同一章节的 AI 事实；None 仅代表静态
                    # 作品来源，不能作为跨章节的通配值。
                    and candidate.source_chapter_id == source_chapter_id
                ), None)
            if row and row.source_type == "manual":
                continue
            if row is None:
                row = StoryKnowledgeFact(story_id=story.id, subject_key=str(raw["subject_key"])[:160], predicate=str(raw["predicate"])[:100], source_type="agent", source_id=item_source, source_chapter_id=source_chapter_id)
                db.add(row)
            else:
                row.version = int(row.version or 1) + 1
                row.subject_key = str(raw["subject_key"])[:160]
                row.predicate = str(raw["predicate"])[:100]
                row.source_id = item_source
                row.source_chapter_id = source_chapter_id
            facts[item_source] = row
            emitted_fact_sources[source_scope].add(item_source)
            row.object_key = str(raw.get("object_key") or "")[:160] or None
            row.value_text = str(raw.get("value_text") or "").strip() or None
            valid_from = _int_or_none(raw.get("valid_from_chapter")) or source_chapter_number
            valid_to = _int_or_none(raw.get("valid_to_chapter"))
            row.valid_from_chapter = min(valid_from, valid_to) if valid_from and valid_to else valid_from
            row.valid_to_chapter = max(valid_from, valid_to) if valid_from and valid_to else valid_to
            row.confidence = _bounded_float(raw.get("confidence"), 0.8)
            row.status = "active"
            counts["facts"] += 1
        for raw in result.get("plot_threads") if "plot_threads" in included and isinstance(result.get("plot_threads"), list) else []:
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            key = _stable_key(raw.get("thread_key") or raw.get("title"), "thread")
            item_source = _source_key("thread", source_id, key)
            row = threads.get(key)
            if row and row.source_type == "manual":
                continue
            if row is None:
                row = StoryPlotThread(story_id=story.id, thread_key=key, title=str(raw["title"])[:255], source_type="agent", source_id=item_source)
                db.add(row)
                threads[key] = row
            else:
                row.version = int(row.version or 1) + 1
                row.title = str(raw.get("title") or row.title)[:255]
                row.source_id = item_source
            emitted_thread_sources[source_scope].add(item_source)
            row.description = str(raw.get("description") or "").strip() or None
            setup_chapter = _int_or_none(raw.get("setup_chapter")) or source_chapter_number
            row.setup_chapter = min(value for value in (row.setup_chapter, setup_chapter) if value is not None) if row.setup_chapter or setup_chapter else None
            payoff_from = _int_or_none(raw.get("expected_payoff_from"))
            payoff_to = _int_or_none(raw.get("expected_payoff_to"))
            row.expected_payoff_from = min(payoff_from, payoff_to) if payoff_from and payoff_to else payoff_from
            row.expected_payoff_to = max(payoff_from, payoff_to) if payoff_from and payoff_to else payoff_to
            row.actual_payoff_chapter = _int_or_none(raw.get("actual_payoff_chapter"))
            row.related_entity_keys = _string_list(raw.get("related_entity_keys"), limit=30, item_limit=160)
            row.priority = _bounded_int(raw.get("priority"), 50)
            status = str(raw.get("status") or "open")
            row.status = status if status in {"open", "active", "due", "resolved"} else "open"
            counts["plot_threads"] += 1
    scopes_to_reconcile = reconcile_scopes or set()
    removed_chapters = deleted_chapter_ids or set()
    for row in entities.values() if "entities" in included else []:
        source_id = str(row.source_id or "")
        if row.source_type != "agent" or not source_id.startswith("ai_sync:"):
            continue
        is_current_schema = source_id.startswith(f"ai_sync:v{SYNC_SCHEMA_VERSION}:entity:")
        row_scope = _entity_row_scope(row, story.id)
        row_chapter_id = int(row_scope.split(":", 1)[1]) if row_scope.startswith("chapter:") else None
        should_archive = bool(archive_legacy and not is_current_schema)
        if row_chapter_id in removed_chapters:
            should_archive = True
        if row_scope in scopes_to_reconcile and row.entity_key not in emitted_entity_keys.get(row_scope, set()):
            should_archive = True
        if should_archive and row.status != "archived":
            row.status = "archived"
            row.version = int(row.version or 1) + 1
            counts["archived_entities"] = counts.get("archived_entities", 0) + 1
    for row in fact_rows if "facts" in included else []:
        source_id = str(row.source_id or "")
        if row.source_type != "agent" or not source_id.startswith("ai_sync:"):
            continue
        is_current_schema = source_id.startswith(f"ai_sync:v{SYNC_SCHEMA_VERSION}:fact:")
        row_scope = _fact_row_scope(row, story.id)
        row_chapter_id = int(row_scope.split(":", 1)[1]) if row_scope.startswith("chapter:") else None
        should_archive = bool(archive_legacy and not is_current_schema)
        if row_chapter_id in removed_chapters:
            should_archive = True
        if is_current_schema and row_scope in scopes_to_reconcile and row.source_id not in emitted_fact_sources.get(row_scope, set()):
            should_archive = True
        if should_archive and row.status != "archived":
            row.status = "archived"
            row.version = int(row.version or 1) + 1
            counts["archived_facts"] += 1
    for row in thread_rows if "plot_threads" in included else []:
        source_id = str(row.source_id or "")
        if row.source_type != "agent" or not source_id.startswith("ai_sync:"):
            continue
        is_current_schema = source_id.startswith(f"ai_sync:v{SYNC_SCHEMA_VERSION}:thread:")
        row_scope = _thread_row_scope(row, story.id)
        row_chapter_id = int(row_scope.split(":", 1)[1]) if row_scope.startswith("chapter:") else None
        should_archive = bool(archive_legacy and not is_current_schema)
        if row_chapter_id in removed_chapters:
            should_archive = True
        if is_current_schema and row_scope in scopes_to_reconcile and row.source_id not in emitted_thread_sources.get(row_scope, set()):
            should_archive = True
        if should_archive and row.status != "archived":
            row.status = "archived"
            row.version = int(row.version or 1) + 1
            counts["archived_plot_threads"] += 1
    db.commit()
    return counts


async def sync_story_knowledge_with_ai(
    story_id_value: int,
    api_key: str | None,
    *,
    task_id: str | None = None,
    sync_mode: str = "incremental",
    sync_scope: str = "all",
    **_: Any,
) -> dict[str, Any]:
    if sync_mode not in {"incremental", "full"}:
        raise ValueError("同步模式不受支持")
    if sync_scope not in SYNC_SCOPES:
        raise ValueError("同步范围不受支持")
    include_kinds = {"entities", "facts", "plot_threads"} if sync_scope == "all" else {sync_scope}
    db = SessionLocal()
    try:
        story = db.get(Story, story_id_value)
        if story is None:
            raise ValueError("作品不存在")
        previous_tasks = db.query(BackgroundTask).filter(
            BackgroundTask.story_id == story_id_value,
            BackgroundTask.task_type == "knowledge_ai_sync",
            BackgroundTask.status == "succeeded",
            BackgroundTask.task_id != task_id,
        ).order_by(BackgroundTask.completed_at.desc()).limit(50).all()
        previous_result: dict[str, Any] = {}
        if sync_mode == "incremental":
            for previous_task in previous_tasks:
                candidate = previous_task.result_json if isinstance(previous_task.result_json, dict) else {}
                if str(candidate.get("sync_scope") or "all") == sync_scope:
                    previous_result = candidate
                    break
        sources, fingerprints, static_hash = _build_sources(db, story, previous_result)
        existing_ai_scopes = _existing_ai_scopes(db, story_id_value, include_kinds)
        previous_fingerprints = previous_result.get("chapter_fingerprints") if isinstance(previous_result.get("chapter_fingerprints"), dict) else {}
        deleted_chapter_ids = {
            int(chapter_id)
            for chapter_id in set(previous_fingerprints) - set(fingerprints)
            if str(chapter_id).isdigit()
        }
        if not sources:
            counts = _merge_results(
                db,
                story,
                [],
                reconcile_scopes=existing_ai_scopes if sync_mode == "full" else set(),
                deleted_chapter_ids=deleted_chapter_ids,
                archive_legacy=sync_mode == "full",
                include_kinds=include_kinds,
            ) if deleted_chapter_ids or sync_mode == "full" else {
                "archived_facts": 0,
                "archived_plot_threads": 0,
            }
            message = "已清理删除章节的旧事实" if counts.get("archived_facts") else "作品资料没有变化"
            return {"status": "succeeded", "message": message, "sync_mode": sync_mode, "sync_scope": sync_scope, "changed_sources": 0, "counts": counts, "chapter_fingerprints": fingerprints, "static_hash": static_hash, "sync_schema_version": SYNC_SCHEMA_VERSION}
        manifest = _existing_manifest(db, story_id_value)
        db.rollback()
        task_manager.update_task_metadata(task_id, stage="extracting", message=f"正在并发分析 {len(sources)} 组更新内容", completed=0, total=len(sources))
        semaphore = asyncio.Semaphore(SYNC_CONCURRENCY)

        async with httpx.AsyncClient(timeout=240) as client:
            results, failures, failed_source_ids, timed_out = await _collect_source_results(
                client,
                sources,
                manifest,
                api_key,
                task_id,
                semaphore,
                sync_scope,
            )
        if not results:
            detail = failures[0] if failures else "模型未返回可用数据"
            raise ValueError(f"AI 同步未获得有效 JSON：{detail}")
        task_manager.update_task_metadata(task_id, stage="merging", message="正在合并人物关系、事件与伏笔", completed=len(results), total=len(sources))
        story = db.query(Story).filter(Story.id == story_id_value).with_for_update().one()
        _, current_fingerprints, current_static_hash = _build_sources(db, story, previous_result)
        if current_fingerprints != fingerprints or current_static_hash != static_hash:
            db.rollback()
            raise KnowledgeSyncInputChangedError("同步期间作品内容发生变化，正在基于最新内容重试")
        failed_scopes = {_source_scope(source_id) for source_id in failed_source_ids}
        current_scopes = {_source_scope(source["source_id"]) for source in sources}
        reconcile_scopes = current_scopes - failed_scopes
        if sync_mode == "full":
            # 全量扫描没有上一轮指纹可用于推断删除，因此把已有但已经不在
            # 当前来源集合中的 AI 记录范围也纳入归档；失败的当前范围仍保留。
            reconcile_scopes.update(existing_ai_scopes - current_scopes)
        counts = _merge_results(
            db,
            story,
            results,
            reconcile_scopes=reconcile_scopes,
            deleted_chapter_ids=deleted_chapter_ids,
            archive_legacy=previous_result.get("sync_schema_version") != SYNC_SCHEMA_VERSION and not failures,
            include_kinds=include_kinds,
        )
        if timed_out:
            message = f"已保存本次完成的 {len(results)} 组内容，另有 {len(failures)} 组将在下次同步时继续补充"
        else:
            message = "作品时间轴已同步" if not failures else f"作品时间轴已同步，{len(failures)} 组内容将在下次继续补充"
        retry_fingerprints, retry_static_hash = _retry_markers(
            fingerprints,
            static_hash,
            previous_result,
            failed_source_ids,
        )
        result_schema_version = _result_schema_version(previous_result, bool(failures))
        return {"status": "succeeded", "message": message, "sync_mode": sync_mode, "sync_scope": sync_scope, "changed_sources": len(sources), "successful_sources": len(results), "failed_sources": len(failures), "counts": counts, "chapter_fingerprints": retry_fingerprints, "static_hash": retry_static_hash, "sync_schema_version": result_schema_version}
    finally:
        db.close()
