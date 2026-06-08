import asyncio
import contextvars
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx

from database import SessionLocal
from models import Chapter, Story
from sqlalchemy.orm import Session
from services.deepseek import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    _deepseek_auth_headers,
    _build_story_snapshot_tiered,
    adjust_framework_with_chat,
    adjust_chapter_content,
)
from services.framework_utils import (
    _build_current_snapshot_data,
    _build_outline_compact,
    _enforce_framework_snapshot_limit,
    _extract_outline_chapters,
    _merge_framework_outline,
    _normalize_characters_payload,
    _normalize_framework_outline,
    _save_framework_snapshot,
    apply_framework_operations,
)


# ── 待确认修改追踪 ──────────────────────────────────────


@dataclass
class PendingChange:
    """单次修改的快照记录，用于确认或撤回。"""
    type: str  # "chapter" | "story" | "scenes_file"
    record_id: int
    display_name: str  # 用户可读的名称，如"第1章"
    field: str  # 修改的字段名，如"novel_content"
    old_value: Any
    new_value: Any

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "record_id": self.record_id,
            "display_name": self.display_name,
            "field": self.field,
        }


class PendingChangesTracker:
    """追踪 Agent 运行期间的所有修改，支持一键撤回。"""

    def __init__(self):
        self._changes: list[PendingChange] = []
        self._seen: set[tuple[str, int, str]] = set()  # 去重：(type, record_id, field)

    def record(self, change: PendingChange) -> None:
        key = (change.type, change.record_id, change.field)
        if key not in self._seen:
            self._seen.add(key)
            self._changes.append(change)

    def record_chapter_field(self, chapter: Chapter, field: str) -> None:
        """记录章节某个字段修改前的值（仅首次记录生效）。"""
        old = getattr(chapter, field, None)
        display = f"第{chapter.chapter_number}章" + (f" · {chapter.title}" if chapter.title else "")
        self.record(PendingChange(
            type="chapter",
            record_id=chapter.id,
            display_name=display,
            field=field,
            old_value=old,
            new_value=None,  # 工具执行后会自动填充
        ))

    def record_story_field(self, story: Story, field: str) -> None:
        """记录故事某个字段修改前的值。"""
        old = getattr(story, field, None)
        self.record(PendingChange(
            type="story",
            record_id=story.id,
            display_name=story.title,
            field=field,
            old_value=old,
            new_value=None,
        ))

    def update_new_value(self, change_type: str, record_id: int, field: str, new_value: Any) -> None:
        """工具执行后更新 new_value。"""
        for c in self._changes:
            if c.type == change_type and c.record_id == record_id and c.field == field:
                c.new_value = new_value
                break

    def has_changes(self) -> bool:
        return len(self._changes) > 0

    def get_summary(self) -> list[dict]:
        """返回给前端的摘要（不含实际数据，仅描述）。"""
        return [c.to_dict() for c in self._changes if c.new_value is not None]

    def get_full_data(self) -> list[dict]:
        """返回完整的变更数据（含 old_value 和 new_value），供前端展示差异对比。"""
        return [
            {
                "type": c.type,
                "record_id": c.record_id,
                "display_name": c.display_name,
                "field": c.field,
                "old_value": _serialize_for_diff(c.old_value),
                "new_value": _serialize_for_diff(c.new_value),
            }
            for c in self._changes
            if c.new_value is not None
        ]

    def rollback(self, db: Session) -> list[dict]:
        """撤回所有修改，恢复旧值。返回操作结果列表。"""
        results = []
        for change in reversed(self._changes):
            try:
                if change.type == "chapter":
                    obj = db.get(Chapter, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "chapter", "id": change.record_id, "field": change.field})
                elif change.type == "story":
                    obj = db.get(Story, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "story", "id": change.record_id, "field": change.field})
                elif change.type == "scenes_file":
                    scenes_path = _scenes_path(change.record_id)
                    if change.old_value:
                        scenes_path.parent.mkdir(parents=True, exist_ok=True)
                        scenes_path.write_text(change.old_value, encoding="utf-8")
                    elif scenes_path.exists():
                        scenes_path.unlink()
                    results.append({"ok": True, "type": "scenes_file", "id": change.record_id})
            except Exception as e:
                results.append({"ok": False, "error": str(e)})
        if any(r.get("ok") for r in results):
            db.commit()
        self.clear()
        return results

    def clear(self) -> None:
        self._changes.clear()
        self._seen.clear()


AgentMode = str
AGENT_MODES: set[AgentMode] = {"chat", "analyze", "execute"}
READ_ONLY_AGENT_MODES: set[AgentMode] = {"chat", "analyze"}


@dataclass(frozen=True)
class AgentPendingChangeKey:
    user_id: int
    story_id: int
    conversation_id: int


@dataclass
class AgentRunContext:
    story_id: int
    api_key: str | None
    mode: AgentMode
    pending_changes: PendingChangesTracker
    pending_change_key: AgentPendingChangeKey | None = None


class AgentPendingChangeStore:
    """In-memory pending change store scoped to one user/story/conversation."""

    def __init__(self):
        self._items: dict[AgentPendingChangeKey, PendingChangesTracker] = {}
        self._lock = threading.RLock()

    def set(self, key: AgentPendingChangeKey, tracker: PendingChangesTracker) -> None:
        with self._lock:
            if tracker.has_changes():
                self._items[key] = tracker
            else:
                self._items.pop(key, None)

    def get(self, key: AgentPendingChangeKey) -> PendingChangesTracker | None:
        with self._lock:
            return self._items.get(key)

    def clear(self, key: AgentPendingChangeKey) -> None:
        with self._lock:
            self._items.pop(key, None)


_AGENT_RUN_CONTEXT: contextvars.ContextVar[AgentRunContext | None] = contextvars.ContextVar(
    "agent_run_context",
    default=None,
)
agent_pending_change_store = AgentPendingChangeStore()


def normalize_agent_mode(mode: str | None) -> AgentMode:
    normalized = str(mode or "execute").strip().lower()
    if normalized not in AGENT_MODES:
        return "execute"
    return normalized


def _current_run_context() -> AgentRunContext | None:
    return _AGENT_RUN_CONTEXT.get()


def _current_story_id() -> int | None:
    context = _current_run_context()
    return context.story_id if context else None


def _current_api_key() -> str | None:
    context = _current_run_context()
    return context.api_key if context else None


def _current_pending_changes() -> PendingChangesTracker | None:
    context = _current_run_context()
    return context.pending_changes if context else None


def _serialize_for_diff(value: Any) -> str:
    """将各种类型的值序列化为适合对比展示的字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


logger = logging.getLogger("agent_service")

# ── 文件系统辅助 ──────────────────────────────────────────

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 批量操作的并发限制
BATCH_CONCURRENCY_LIMIT = 3


def _chapter_dir(chapter_id: int) -> Path:
    return BACKEND_DIR / "manga_outputs" / f"chapter_{chapter_id}"


def _scenes_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "scenes.txt"


def _characters_file_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "characters.txt"


def _parse_scenes_text(raw: str) -> list[str]:
    import re
    parts = [p.strip() for p in re.split(r"(?m)^=== .*? ===\n", raw) if p.strip()]
    return parts


# ── 小工具注册器 ──────────────────────────────────────────


class ToolRegistry:
    """管理 Agent 可见的工具列表，支持装饰器注册模式。"""

    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}
        self._write_tool_names: set[str] = set()

    def register(self, name: str, description: str, parameters: dict, is_write: bool = False):
        """装饰器：注册一个工具处理函数。"""
        def decorator(func):
            self._tools[name] = {
                "handler": func,
                "spec": {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                },
            }
            if is_write:
                self._write_tool_names.add(name)
            return func
        return decorator

    def is_write_tool(self, name: str) -> bool:
        return name in self._write_tool_names

    def get_tool_specs(self, mode: AgentMode = "execute") -> list[dict]:
        """返回 DeepSeek/OpenAI function calling 格式的工具清单。"""
        if normalize_agent_mode(mode) in READ_ONLY_AGENT_MODES:
            return [
                info["spec"]
                for name, info in self._tools.items()
                if name not in self._write_tool_names
            ]
        return [info["spec"] for info in self._tools.values()]

    async def execute(self, name: str, args: dict) -> str:
        """按名称执行工具，返回 JSON 字符串。"""
        info = self._tools.get(name)
        if not info:
            raise ValueError(f"未知工具: {name}")
        context = _current_run_context()
        if name in self._write_tool_names and (context is None or context.mode != "execute"):
            return json.dumps(
                {
                    "error": "当前 Agent 模式不允许写入。请切换到执行模式后再保存修改。",
                    "write_denied": True,
                    "mode": context.mode if context else None,
                },
                ensure_ascii=False,
            )
        result = await info["handler"](**args)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)


# ── 所有权校验辅助 ──────────────────────────────────────────

def _validate_chapter_ownership(db: Session, chapter_id: int, expected_story_id: int | None) -> Chapter | None:
    """校验章节是否属于指定故事。返回章节对象，失败返回 None。"""
    if expected_story_id is None:
        return None
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        return None
    if chapter.story_id != expected_story_id:
        return None
    return chapter


def _validate_story_ownership(db: Session, story_id: int, expected_story_id: int | None) -> Story | None:
    """校验故事 ID 是否与当前上下文一致。返回故事对象，失败返回 None。"""
    if expected_story_id is None:
        return None
    story = db.get(Story, story_id)
    if not story:
        return None
    if story.id != expected_story_id:
        return None
    return story


# ── 全局注册器 ──────────────────────────────────────────

tool_registry = ToolRegistry()


# ────────────────────────────────────────────────────────────
# 读取工具（6 个）
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="get_chapter_full",
    description="读取指定章节的完整正文内容，包括标题、正文、关键事件、质量评分等。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_chapter_full(chapter_id: int) -> dict:
    """读取完整的章节信息。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        return {
            "id": chapter.id,
            "story_id": chapter.story_id,
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or "",
            "act": chapter.act or "",
            "content": chapter.novel_content or "",
            "key_events": chapter.key_events or [],
            "quality_score": chapter.quality_score or {},
            "status": chapter.status,
            "word_count": chapter.word_count or 0,
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_all_chapters_summary",
    description="获取故事所有章节的摘要列表，包含章节号、标题、字数、状态。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
        },
        "required": ["story_id"],
    },
)
async def get_all_chapters_summary(story_id: int) -> dict:
    """列出故事下所有章节的基本信息。"""
    db = SessionLocal()
    try:
        if story_id != _current_story_id():
            return {"error": "故事 ID 与当前上下文不匹配"}
        chapters = (
            db.query(Chapter)
            .filter(Chapter.story_id == story_id)
            .order_by(Chapter.chapter_number)
            .all()
        )
        return {
            "chapters": [
                {
                    "id": ch.id,
                    "chapter_number": ch.chapter_number,
                    "title": ch.title or "",
                    "word_count": ch.word_count or 0,
                    "status": ch.status,
                    "act": ch.act or "",
                }
                for ch in chapters
            ]
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_framework_detail",
    description="获取故事框架详情：标签、角色设定、故事大纲。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
        },
        "required": ["story_id"],
    },
)
async def get_framework_detail(story_id: int) -> dict:
    """获取故事标签、角色和大纲。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        return {
            "tags": story.tags or {},
            "characters": story.characters or [],
            "outline": story.outline or {},
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_story_bible",
    description="获取作品圣经：创意简报和写作指导。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
        },
        "required": ["story_id"],
    },
)
async def get_story_bible(story_id: int) -> dict:
    """获取故事圣经中的 creative_brief 和 writing_guidance。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        bible = story.story_bible if isinstance(story.story_bible, dict) else {}
        return {
            "creative_brief": bible.get("creative_brief", {}),
            "writing_guidance": bible.get("writing_guidance", {}),
            "import_guidance": bible.get("import_guidance", {}),
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_scenes",
    description="获取指定章节的分镜列表。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_scenes(chapter_id: int) -> dict:
    """从文件读取章节分镜列表。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
    finally:
        db.close()
    scenes_file = _scenes_path(chapter_id)
    if not scenes_file.exists():
        return {"scenes": []}
    try:
        raw = scenes_file.read_text(encoding="utf-8")
        scenes = _parse_scenes_text(raw)
        return {"scenes": scenes}
    except Exception as exc:
        logger.warning("读取分镜文件失败 chapter_id=%s: %s", chapter_id, exc)
        return {"scenes": [], "error": str(exc)}


@tool_registry.register(
    name="get_character_profiles",
    description="获取章节的角色外貌设定。优先读取章节独立设定，没有则返回故事级设定。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_character_profiles(chapter_id: int) -> dict:
    """获取角色外貌设定。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        cfile = _characters_file_path(chapter_id)
        if cfile.exists():
            text = cfile.read_text(encoding="utf-8").strip()
            if text:
                return {"source": "chapter", "content": text}
        if chapter.story and chapter.story.character_profiles:
            text = chapter.story.character_profiles.strip()
            if text:
                return {"source": "story", "content": text}
        return {"source": "none", "content": ""}
    finally:
        db.close()


# ────────────────────────────────────────────────────────────
# 写入工具（8 个）
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="update_chapter_content",
    description="直接保存/更新章节的正文内容。用户给出改写建议后，必须用此工具保存修改。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "content": {"type": "string", "description": "新的章节正文内容"},
        },
        "required": ["chapter_id", "content"],
    },
)
async def update_chapter_content(chapter_id: int, content: str) -> dict:
    """直接更新章节正文。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")
        chapter.novel_content = content
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", content)
        db.commit()
        return {"ok": True, "chapter_id": chapter_id}
    finally:
        db.close()


@tool_registry.register(
    name="batch_update_chapters",
    description="批量更新多个章节的正文内容。适用于用户给出多个章节的具体改写内容时，一次保存多章。比分别调用 update_chapter_content 更高效。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "description": "要更新的章节列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer", "description": "章节 ID"},
                        "content": {"type": "string", "description": "新的章节正文内容"},
                    },
                    "required": ["chapter_id", "content"],
                },
            },
        },
        "required": ["chapters"],
    },
)
async def batch_update_chapters(chapters: list[dict]) -> dict:
    """批量更新多个章节正文。"""
    MAX_BATCH_SIZE = 10
    if not isinstance(chapters, list):
        return {"error": "chapters 必须是一个数组"}
    if len(chapters) > MAX_BATCH_SIZE:
        return {"error": f"一次最多更新 {MAX_BATCH_SIZE} 个章节"}

    async def _update_one(item: dict) -> dict:
        chapter_id = item.get("chapter_id")
        content = item.get("content")
        if not chapter_id or content is None:
            return {"chapter_id": chapter_id, "error": "缺少 chapter_id 或 content"}
        db = SessionLocal()
        try:
            chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
            if not chapter:
                return {"chapter_id": chapter_id, "error": "章节不存在或无权访问"}
            if _current_pending_changes():
                _current_pending_changes().record_chapter_field(chapter, "novel_content")
            chapter.novel_content = content
            if _current_pending_changes():
                _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", content)
            db.commit()
            return {"chapter_id": chapter_id, "ok": True}
        except Exception as e:
            return {"chapter_id": chapter_id, "error": str(e)}
        finally:
            db.close()

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)

    async def _update_one_with_limit(item: dict) -> dict:
        async with semaphore:
            return await _update_one(item)

    results = await asyncio.gather(*[_update_one_with_limit(item) for item in chapters])
    return {"ok": True, "results": results}


@tool_registry.register(
    name="adjust_chapter_by_instruction",
    description="根据用户指令让 AI 重写整章正文。适用于用户要求调整风格、补充内容等场景。消耗文本配额。如果用户已给出具体改写文本，用 update_chapter_content 更直接。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "要调整的章节 ID"},
            "instruction": {"type": "string", "description": "用户的修改指令"},
        },
        "required": ["chapter_id", "instruction"],
    },
)
async def adjust_chapter_by_instruction(chapter_id: int, instruction: str) -> dict:
    """调用 DeepSeek 根据指令重写整章。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        story_obj = db.get(Story, chapter.story_id)
        if not story_obj:
            return {"error": "所属故事不存在"}

        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")

        story_context = _build_story_context_dict(story_obj)
        chapter_info = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or f"第{chapter.chapter_number}章",
            "act": chapter.act or "",
            "key_events": chapter.key_events or [],
        }
        chapter_content = chapter.novel_content or ""

        api_key = _current_api_key()
        if not api_key:
            return {"error": "DeepSeek API Key 未配置"}

        new_content = await adjust_chapter_content(
            story_context=story_context,
            chapter_info=chapter_info,
            chapter_content=chapter_content,
            instruction=instruction,
            api_key=api_key,
        )
        if not new_content or not new_content.strip():
            return {"error": "AI 返回内容为空"}

        chapter.novel_content = new_content
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", new_content)
        db.commit()
        return {"ok": True, "chapter_id": chapter_id, "content_length": len(new_content)}
    finally:
        db.close()


@tool_registry.register(
    name="rewrite_text_segment",
    description='在章节正文中精确查找并替换指定段落。适用于用户给出「把某段改成XX」的明确指令。注意：original 必须与正文完全匹配。',
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "original": {"type": "string", "description": "需要被替换的原文（必须完全匹配）"},
            "rewritten": {"type": "string", "description": "改写后的新文本"},
        },
        "required": ["chapter_id", "original", "rewritten"],
    },
)
async def rewrite_text_segment(chapter_id: int, original: str, rewritten: str) -> dict:
    """在章节正文中执行精确查找替换。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        current = chapter.novel_content or ""
        if original not in current:
            return {"error": "未在正文中找到完全匹配的原文，请确认文本是否一致", "found": False}
        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")
        new_content = current.replace(original, rewritten, 1)
        chapter.novel_content = new_content
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", new_content)
        db.commit()
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "replaced": True,
            "new_content_length": len(new_content),
        }
    finally:
        db.close()


@tool_registry.register(
    name="update_story_info",
    description="更新故事的基本信息（标题、描述、标签）。只更新提供的字段。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "title": {"type": "string", "description": "新标题（可选）"},
            "description": {"type": "string", "description": "新描述（可选）"},
            "tags": {
                "type": "object",
                "description": "新标签对象，例如 {\"type\": \"奇幻\", \"theme\": \"冒险\"}（可选）",
                "additionalProperties": True,
            },
        },
        "required": ["story_id"],
    },
)
async def update_story_info(story_id: int, title: str | None = None, description: str | None = None, tags: dict | None = None) -> dict:
    """更新故事基本信息。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if _current_pending_changes():
            if title is not None:
                _current_pending_changes().record_story_field(story, "title")
            if description is not None:
                _current_pending_changes().record_story_field(story, "description")
            if tags is not None:
                _current_pending_changes().record_story_field(story, "tags")
        updated_fields = []
        if title is not None:
            story.title = title
            updated_fields.append("title")
        if description is not None:
            story.description = description
            updated_fields.append("description")
        if tags is not None:
            story.tags = tags
            updated_fields.append("tags")
        if _current_pending_changes():
            for f in updated_fields:
                _current_pending_changes().update_new_value("story", story.id, f, getattr(story, f))
        db.commit()
        return {"ok": True, "updated_fields": updated_fields}
    finally:
        db.close()


@tool_registry.register(
    name="update_characters",
    description="替换故事的角色设定列表。用户要求修改角色时，必须用此工具保存更改。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "characters": {
                "type": "array",
                "description": "角色列表，每个角色包含 name、role、description 等字段",
                "items": {"type": "object"},
            },
        },
        "required": ["story_id", "characters"],
    },
)
async def update_characters(story_id: int, characters: list[dict]) -> dict:
    """替换整个角色设定列表。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "characters")
        story.characters = characters
        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "characters", characters)
        db.commit()
        return {"ok": True, "count": len(characters)}
    finally:
        db.close()


@tool_registry.register(
    name="adjust_framework",
    description="通过自然语言指令调整故事框架（标签、角色、大纲、章节规划）。调用 AI 理解指令并生成精准的框架编辑操作。此操作会消耗高级文本配额。\n\n⚠️ 批量使用：请将所有要修改的内容汇总到一条 instruction 中（例如：'把主角改成更勇敢，新增一个反派角色，把大纲基调改为悬疑风格，把第 3 章标题改成XXX'），全部放进一条 instruction，不要分多次调用。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "instruction": {"type": "string", "description": "调整指令，描述要做的修改"},
        },
        "required": ["story_id", "instruction"],
    },
)
async def adjust_framework(story_id: int, instruction: str) -> dict:
    """根据自然语言指令调整故事框架。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "description")
            _current_pending_changes().record_story_field(story, "tags")
            _current_pending_changes().record_story_field(story, "characters")
            _current_pending_changes().record_story_field(story, "outline")

        api_key = _current_api_key()
        if not api_key:
            return {"error": "DeepSeek API Key 未配置"}

        existing_framework = {
            "description": story.description or "",
            "tags": story.tags or {},
            "characters": story.characters or [],
            "outline": story.outline or {},
        }

        story_context = _build_story_context_dict(story, user_instruction=instruction)

        messages = [{"role": "user", "content": instruction}]

        # 推断篇幅类型，让框架调整遵循正确的篇幅规则
        from .deepseek import _infer_story_length
        story_length = _infer_story_length(story_context, description=instruction, messages=messages)

        try:
            plan = await adjust_framework_with_chat(
                story_context=story_context,
                messages=messages,
                api_key=api_key,
                existing_framework=existing_framework,
                story_length=story_length,
            )
        except ValueError as exc:
            return {"error": f"AI 返回格式无效: {exc}"}

        apply_result = apply_framework_operations(
            existing_framework=existing_framework,
            operations=plan.get("operations"),
            patches=plan.get("patches"),
        )

        if apply_result.get("errors"):
            return {"error": "；".join(apply_result["errors"])}

        framework = apply_result["framework"]

        # ★ 自动快照：保存调整前的当前状态（用于回退）
        _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=_build_current_snapshot_data(story),
            source="agent_adjust",
            reply_summary=(plan.get("reply") or "")[:255] if plan.get("reply") else None,
            db=db,
        )
        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

        story.description = str(framework.get("description") or existing_framework["description"] or "").strip()
        story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
        story.characters = _normalize_characters_payload(framework.get("characters"))
        story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]

        if _current_pending_changes():
            for f in ("description", "tags", "characters", "outline"):
                _current_pending_changes().update_new_value("story", story.id, f, getattr(story, f))

        db.commit()

        warnings = [*plan.get("warnings", []), *apply_result.get("warnings", [])]
        return {
            "ok": True,
            "reply": plan.get("reply", ""),
            "applied_operations": apply_result.get("applied_operations", []),
            "warnings": warnings,
            "_generated_operations": plan.get("operations", []),
        }
    finally:
        db.close()


@tool_registry.register(
    name="apply_framework_ops",
    description="直接执行框架编辑操作。接收结构化的 operations 数组，立即应用到故事数据库。不调用 AI，适合你已经明确知道要做什么修改的场景（如'把主角改名为李明'、'添加一个反派角色'、'修改第三幕概要'）。复杂创作需求（如'帮我重新设计第二幕'）请用 adjust_framework。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "operations": {
                "type": "array",
                "description": "编辑操作列表，每项格式: {\"op\": \"操作名\", \"target\": {...}, \"changes\": {...}}",
                "items": {"type": "object"},
            },
            "patches": {
                "type": "array",
                "description": "JSON Patch 列表（可选）",
                "items": {"type": "object"},
            },
            "dry_run": {
                "type": "boolean",
                "description": "为 true 时只校验不执行，返回预览结果而不写入数据库（默认 false）",
            },
        },
        "required": ["story_id", "operations"],
    },
)
async def apply_framework_ops(story_id: int, operations: list, patches: list | None = None, dry_run: bool = False) -> dict:
    """直接应用框架编辑操作，不调用 AI。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        existing_framework = {
            "description": story.description or "",
            "tags": story.tags or {},
            "characters": story.characters or [],
            "outline": story.outline or {},
        }

        apply_result = apply_framework_operations(
            existing_framework=existing_framework,
            operations=operations,
            patches=patches or [],
        )

        if apply_result["errors"]:
            return {"error": "；".join(apply_result["errors"])}

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "preview_framework": apply_result["framework"],
                "applied_operations": apply_result["applied_operations"],
                "warnings": apply_result.get("warnings", []),
            }

        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "description")
            _current_pending_changes().record_story_field(story, "tags")
            _current_pending_changes().record_story_field(story, "characters")
            _current_pending_changes().record_story_field(story, "outline")

        framework = apply_result["framework"]
        story.description = str(framework.get("description") or "").strip()
        story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
        story.characters = _normalize_characters_payload(framework.get("characters"))
        story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]

        _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=_build_current_snapshot_data(story),
            source="agent_direct_ops",
            reply_summary=None,
            db=db,
        )
        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)
        db.commit()

        return {
            "ok": True,
            "applied_operations": apply_result["applied_operations"],
            "warnings": apply_result.get("warnings", []),
        }
    finally:
        db.close()


@tool_registry.register(
    name="batch_adjust_chapters",
    description="批量调整多个章节的正文内容。适用于用户要求统一调整多章风格、同时优化多个章节等场景。每次调用可调整多章，比分别调用 adjust_chapter_by_instruction 更高效。消耗高级文本配额。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "description": "要调整的章节列表，每项包含 chapter_id 和 instruction",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer", "description": "章节 ID"},
                        "instruction": {"type": "string", "description": "该章节的调整指令"},
                    },
                    "required": ["chapter_id", "instruction"],
                },
            },
        },
        "required": ["chapters"],
    },
)
async def batch_adjust_chapters(chapters: list[dict]) -> dict:
    """批量调整多个章节正文。"""
    MAX_BATCH_SIZE = 10
    if not isinstance(chapters, list):
        return {"error": "chapters 必须是一个数组"}
    if len(chapters) > MAX_BATCH_SIZE:
        return {"error": f"一次最多调整 {MAX_BATCH_SIZE} 个章节"}
    api_key = _current_api_key()
    if not api_key:
        return {"error": "DeepSeek API Key 未配置"}

    async def _adjust_one(item: dict) -> dict:
        chapter_id = item.get("chapter_id")
        instruction = str(item.get("instruction") or "").strip()
        if not chapter_id or not instruction:
            return {"chapter_id": chapter_id, "error": "缺少 chapter_id 或 instruction"}
        db = SessionLocal()
        try:
            chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
            if not chapter:
                return {"chapter_id": chapter_id, "error": "章节不存在或无权访问"}
            story_obj = db.get(Story, chapter.story_id)
            if not story_obj:
                return {"chapter_id": chapter_id, "error": "所属故事不存在"}
            if _current_pending_changes():
                _current_pending_changes().record_chapter_field(chapter, "novel_content")
            story_context = _build_story_context_dict(story_obj)
            chapter_info = {
                "chapter_number": chapter.chapter_number,
                "title": chapter.title or f"第{chapter.chapter_number}章",
                "act": chapter.act or "",
                "key_events": chapter.key_events or [],
            }
            chapter_content = chapter.novel_content or ""
            new_content = await adjust_chapter_content(
                story_context=story_context,
                chapter_info=chapter_info,
                chapter_content=chapter_content,
                instruction=instruction,
                api_key=api_key,
            )
            if not new_content or not new_content.strip():
                return {"chapter_id": chapter_id, "error": "AI 返回内容为空"}
            chapter.novel_content = new_content
            if _current_pending_changes():
                _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", new_content)
            db.commit()
            return {"chapter_id": chapter_id, "ok": True}
        except Exception as e:
            return {"chapter_id": chapter_id, "error": str(e)}
        finally:
            db.close()

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)

    async def _adjust_one_with_limit(item: dict) -> dict:
        async with semaphore:
            return await _adjust_one(item)

    results = await asyncio.gather(*[_adjust_one_with_limit(item) for item in chapters])
    return {"ok": True, "results": results}


@tool_registry.register(
    name="add_chapter_plan",
    description="在故事大纲中添加一个新的章节计划。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "chapter": {
                "type": "object",
                "description": "章节计划对象，包含 chapter_number、title、summary、act 等",
                "properties": {
                    "chapter_number": {"type": "integer", "description": "章节号"},
                    "title": {"type": "string", "description": "章节标题"},
                    "summary": {"type": "string", "description": "章节概要"},
                    "act": {"type": "string", "description": "所属幕/阶段标识"},
                    "key_events": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键事件列表",
                    },
                },
                "required": ["chapter_number", "title"],
            },
        },
        "required": ["story_id", "chapter"],
    },
)
async def add_chapter_plan(story_id: int, chapter: dict) -> dict:
    """在故事大纲中添加章节计划。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "outline")

        outline = story.outline if isinstance(story.outline, dict) else {}
        three_acts = outline.get("three_acts")
        if not isinstance(three_acts, list):
            three_acts = []
            outline["three_acts"] = three_acts

        act_label = chapter.get("act", "")
        # 找到或创建对应的 act
        target_act = None
        for act in three_acts:
            if isinstance(act, dict) and act.get("act") == act_label:
                target_act = act
                break
        if not target_act:
            target_act = {
                "act": act_label or f"act_{len(three_acts) + 1}",
                "title": act_label or f"第{len(three_acts) + 1}幕",
                "summary": "",
                "key_events": [],
                "chapters": [],
            }
            three_acts.append(target_act)

        act_chapters = target_act.get("chapters")
        if not isinstance(act_chapters, list):
            act_chapters = []
            target_act["chapters"] = act_chapters

        # 检查是否已存在同号章节
        chapter_number = chapter.get("chapter_number")
        for existing in act_chapters:
            if isinstance(existing, dict) and existing.get("chapter_number") == chapter_number:
                # 更新已有章节
                existing.update(chapter)
                story.outline = outline
                if _current_pending_changes():
                    _current_pending_changes().update_new_value("story", story.id, "outline", outline)
                db.commit()
                return {"ok": True, "action": "updated", "chapter_number": chapter_number}

        # 新增章节
        new_chapter = {
            "chapter_number": chapter_number,
            "title": chapter.get("title", ""),
            "summary": chapter.get("summary", ""),
            "act": act_label,
            "key_events": chapter.get("key_events", []),
            "goal": chapter.get("goal", ""),
            "conflict": chapter.get("conflict", ""),
            "hook": chapter.get("hook", ""),
            "payoff": chapter.get("payoff", ""),
            "highlight": chapter.get("highlight", ""),
        }
        # 去除空值
        new_chapter = {k: v for k, v in new_chapter.items() if v not in (None, "", [], {})}
        new_chapter["chapter_number"] = chapter_number
        new_chapter["title"] = chapter.get("title", "")

        act_chapters.append(new_chapter)

        # 按章节号排序
        act_chapters.sort(key=lambda x: x.get("chapter_number", 0) if isinstance(x, dict) else 0)

        story.outline = outline
        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "outline", outline)
        db.commit()
        return {"ok": True, "action": "added", "chapter_number": chapter_number}
    finally:
        db.close()


@tool_registry.register(
    name="bulk_add_chapter_plans",
    description="批量添加多个章节计划到故事大纲中。如果用户给出了明确的章节列表，用此工具一次添加多章。如果用户只说帮我规划后续章节，用 adjust_framework 更合适。比分别调用 add_chapter_plan 更高效。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "chapters": {
                "type": "array",
                "description": "章节计划列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_number": {"type": "integer", "description": "章节号"},
                        "title": {"type": "string", "description": "章节标题"},
                        "summary": {"type": "string", "description": "章节概要"},
                        "act": {"type": "string", "description": "所属幕（如 1, 2, 3）"},
                    },
                    "required": ["chapter_number", "title"],
                },
            },
        },
        "required": ["story_id", "chapters"],
    },
)
async def bulk_add_chapter_plans(story_id: int, chapters: list[dict]) -> dict:
    """批量添加章节计划到故事大纲。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "outline")
        outline = story.outline if isinstance(story.outline, dict) else {}
        three_acts = outline.get("three_acts")
        if not isinstance(three_acts, list):
            three_acts = []
            outline["three_acts"] = three_acts

        results = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                results.append({"chapter_number": None, "ok": False, "error": "无效的章节数据"})
                continue
            chapter_number = chapter.get("chapter_number")
            act_label = str(chapter.get("act") or "").strip() or "1"
            target_act = None
            for act in three_acts:
                if isinstance(act, dict) and act.get("act") == act_label:
                    target_act = act
                    break
            if not target_act:
                target_act = {
                    "act": act_label,
                    "title": f"阶段 {act_label}",
                    "summary": "",
                    "chapters": [],
                }
                three_acts.append(target_act)
            act_chapters = target_act.get("chapters")
            if not isinstance(act_chapters, list):
                act_chapters = []
                target_act["chapters"] = act_chapters
            existing = None
            for item in act_chapters:
                if isinstance(item, dict) and item.get("chapter_number") == chapter_number:
                    existing = item
                    break
            entry = {
                "chapter_number": chapter_number,
                "title": chapter.get("title", ""),
                "summary": chapter.get("summary", ""),
                "act": act_label,
            }
            entry = {k: v for k, v in entry.items() if v not in (None, "", [], {})}
            if chapter_number is not None:
                entry["chapter_number"] = chapter_number
                entry["title"] = chapter.get("title", "")
            if existing is not None:
                existing.update(entry)
                results.append({"chapter_number": chapter_number, "ok": True, "action": "updated"})
            else:
                act_chapters.append(entry)
                results.append({"chapter_number": chapter_number, "ok": True, "action": "added"})
            act_chapters.sort(key=lambda x: x.get("chapter_number", 0) if isinstance(x, dict) else 0)
        story.outline = outline
        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "outline", outline)
        db.commit()
        return {"ok": True, "results": results}
    finally:
        db.close()


@tool_registry.register(
    name="update_scenes",
    description="更新/替换指定章节的分镜列表。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "scenes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分镜描述字符串列表",
            },
        },
        "required": ["chapter_id", "scenes"],
    },
)
async def update_scenes(chapter_id: int, scenes: list[str]) -> dict:
    """写入章节分镜文件。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        # 记录旧分镜内容用于撤回
        if _current_pending_changes():
            old_scenes_text = _scenes_path(chapter_id).read_text("utf-8") if _scenes_path(chapter_id).exists() else ""
            _current_pending_changes().record(PendingChange(
                type="scenes_file",
                record_id=chapter_id,
                display_name=f"第{chapter.chapter_number}章分镜",
                field="scenes_file",
                old_value=old_scenes_text,
                new_value=None,
            ))
    finally:
        db.close()
    prompts_dir = _chapter_dir(chapter_id)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompts_file = prompts_dir / "scenes.txt"
    new_text = ""
    try:
        for idx, scene in enumerate(scenes, start=1):
            new_text += f"=== 第{idx}格 ===\n{scene.strip()}\n\n"
        with open(prompts_file, "w", encoding="utf-8") as f:
            f.write(new_text)
        if _current_pending_changes():
            _current_pending_changes().update_new_value("scenes_file", chapter_id, "scenes_file", new_text)
        return {"ok": True, "chapter_id": chapter_id, "scene_count": len(scenes)}
    except OSError as exc:
        logger.warning("写入分镜文件失败 chapter_id=%s: %s", chapter_id, exc)
        return {"error": f"写入分镜文件失败: {exc}"}


# ── 内部辅助 ──────────────────────────────────────────────


def _build_story_context_dict(story: Story, user_instruction: str = "") -> dict:
    """构建 story_context 字典，与 main._build_framework_ai_context 对齐。"""
    outline = story.outline if isinstance(story.outline, dict) else {}
    chapters = _extract_outline_chapters(outline)
    chapter_numbers = [item["chapter_number"] for item in chapters if isinstance(item.get("chapter_number"), int)]
    return {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": outline,
        "story_bible": story.story_bible,
        "story_bible_compact": _build_bible_compact(story.story_bible),
        "story_memory": story.story_memory,
        "story_memory_compact": _build_memory_compact(story.story_memory),
        "outline_compact": _build_outline_compact(outline),
        "framework_stats": {
            "mode": "agent",
            "stage_count": len(outline.get("three_acts") or []) if isinstance(outline.get("three_acts"), list) else 0,
            "chapter_count": len(chapters),
            "last_chapter_number": max(chapter_numbers) if chapter_numbers else 0,
        },
        "user_instruction": user_instruction.strip(),
    }


def _build_bible_compact(story_bible: dict | None) -> dict[str, Any]:
    """精简版作品圣经，与 main._build_story_bible_compact 对齐。"""
    if not isinstance(story_bible, dict):
        return {}
    creative_brief = story_bible.get("creative_brief") if isinstance(story_bible.get("creative_brief"), dict) else {}
    writing_guidance = story_bible.get("writing_guidance") if isinstance(story_bible.get("writing_guidance"), dict) else {}
    import_guidance = story_bible.get("import_guidance") if isinstance(story_bible.get("import_guidance"), dict) else {}

    compact: dict[str, Any] = {}
    for key in (
        "project_positioning", "one_line_premise", "core_hook",
        "protagonist_core", "main_conflict", "longline_mystery",
        "serial_length_target", "reveal_strategy", "pacing_strategy",
    ):
        value = str(creative_brief.get(key) or "").strip()
        if value:
            compact[key] = value

    must_keep = creative_brief.get("must_keep_rules")
    if isinstance(must_keep, list):
        cleaned = [str(item).strip() for item in must_keep if str(item).strip()]
        if cleaned:
            compact["must_keep_rules"] = cleaned[:8]

    for key in ("opening_strategy", "chapter_density_strategy", "midgame_engine", "late_game_direction"):
        value = str(writing_guidance.get(key) or "").strip()
        if value:
            compact[key] = value

    for key in ("forbidden_patterns", "preferred_plot_patterns"):
        raw = writing_guidance.get(key)
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            if cleaned:
                compact[key] = cleaned[:8]

    for key in ("import_material_type", "must_keep", "author_goal", "adjustment_scope", "longline_plan", "tone_guardrails"):
        value = str(import_guidance.get(key) or "").strip()
        if value:
            compact[f"import_{key}"] = value

    return compact


def _build_memory_compact(story_memory: dict | None) -> dict[str, Any]:
    """精简版连续性记忆，与 main._build_story_memory_compact 对齐。"""
    if not isinstance(story_memory, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
        value = str(story_memory.get(key) or "").strip()
        if value:
            compact[key] = value
    for key in ("continuity_facts", "open_loops", "resolved_loops"):
        raw = story_memory.get(key)
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            if cleaned:
                compact[key] = cleaned[:8]
    return compact


# ── Agent 服务 ─────────────────────────────────────────────


class AgentService:
    """Agent 服务：构建故事上下文，调用 DeepSeek function calling，执行工具，流式返回。"""

    def __init__(self):
        self.tool_registry = tool_registry

    def _build_system_prompt(self, story_context: str, story_id: int = 0) -> str:
        """构建包含故事上下文的系统提示。"""
        story_id_line = f"\n当前作品 ID: {story_id}" if story_id else ""
        return f"""你是 Manwen-Studio 的 AI 创作助手，拥有直接读写故事数据库的工具权限。{story_id_line}

**你的工作方式**：每次收到用户输入，先理解用户真正想要什么，再决定怎么做。不是每次都需要调用工具——用户可以只是想聊聊天。

---

## 🧭 第一步：理解用户意图（先思考，再行动）

每次收到用户输入，先在大脑里问自己三个问题：
1. **用户这句话的核心目的是什么？** 是想讨论想法、分析问题、查询信息，还是让我动手改东西？
2. **用户预期我的角色是什么？** 是创作顾问（给建议）、执行者（动手改）、还是信息员（查资料）？
3. **我需要调用工具吗？** 还是直接用我已经知道的上下文就能回答？

完成这个思考后，按以下分类确定行为模式：

| 意图类型 | 典型用户表述 | 你的行为模式 |
|----------|-------------|-------------|
| **💬 聊天探讨 / 创意交流** | "你觉得主角动机够不够"、"我在想下一章该让谁出场"、"这样写会不会太拖"、"我想让故事更悬疑有什么方向"、"你觉得这样设计合理吗"、"我有个想法……" | **不需要调任何工具**。直接基于已有的故事上下文进行创作讨论、提供思路、探讨方向、给出专业见解。你的角色是创作顾问。 |
| **🔍 分析 / 评估** | "分析结构"、"评估节奏"、"检查伏笔"、"提出优化建议"、"有什么问题"、"review这段"、"看看哪里可以改进" | 先调用读取工具获取数据 → 输出系统性分析/评估/建议 → **等待用户确认是否修改**（禁止调用写入工具） |
| **📖 查询 / 了解** | "有哪些章节"、"写了什么"、"帮我查一下"、"告诉我……"、"当前设定是什么" | 调用读取工具获取数据并回答即可 |
| **✏️ 明确修改** | "把这段改成……"（附具体文本）、"改成这样"、"删除"、"替换为" | 先读取确认现状 → 调用写入工具执行修改 → 说明结果 |
| **🎨 模糊创作** | "帮我重写"、"优化一下"、"改得更好"（无具体改动文本） | 先读取数据 → 给出具体修改方案 → **等待用户确认后再执行** |
| **🔄 混合意图** | "先分析再优化"、"看看有什么问题然后调整" | 先分析/评估 → 输出发现和建议 → **等待用户确认后再执行修改** |

> 关键原则：**用户说"你觉得"/"我想"/"我在想"/"这样会不会"等表述时，大概率是在聊天探讨，而不是要你动手改。** 优先用已有的上下文知识和他讨论，不需要每次都要读数据、调工具。

---

## 🔧 第二步：根据意图选择合适的工具

### 读取工具（用于分析 / 查询）
- `get_chapter_full` — 读取某章节的完整正文内容
- `get_all_chapters_summary` — 列出所有章节（编号/标题/字数/状态）
- `get_framework_detail` — 读取标签、角色设定、故事大纲
- `get_story_bible` — 读取作品圣经（创意简报/写作指导）
- `get_scenes` — 读取分镜列表
- `get_character_profiles` — 读取角色外貌设定

### 写入工具（用于执行修改）
- `update_chapter_content` — 直接保存整章正文（用户给出了完整改写内容时用）
- `rewrite_text_segment` — 查找并替换章节中的特定段落（精确匹配替换）
- `adjust_chapter_by_instruction` — 根据用户指令让 AI 重写整章（消耗高级配额）
- `update_story_info` — 修改标题/描述/标签
- `update_characters` — 替换角色设定列表
- `apply_framework_ops` — **直接执行框架编辑操作**，不调用 AI，适合明确的增删改（如"把主角改名"、"加个反派"、"改章节标题"）
- `adjust_framework` — 根据指令调整故事框架/大纲，**适合需要 AI 创作的场景**（如"帮我重新设计第二幕"、"让故事更悬疑"）。消耗高级配额。如果改动明确请优先用 apply_framework_ops
- `add_chapter_plan` — 在大纲中添加新的章节计划
- `bulk_add_chapter_plans` — **批量添加多个章节规划**（用户给出明确章节列表时用，比多次调 add_chapter_plan 更高效）
- `update_scenes` — 更新分镜列表

---

## 📋 第三步：场景 → 行动对照表

| 用户说 | 你应该 |
|--------|--------|
| "你觉得……怎么样"、"我在想……"、"这样会不会……"、"我有个想法" | **直接对话讨论**。基于故事上下文给出见解和思路，不需要调用任何工具 |
| "帮我分析一下故事结构/框架/节奏/伏笔" | 调 `get_framework_detail` + `get_all_chapters_summary`（需要时加 `get_chapter_full`）→ 给出分析 → 等待用户反馈 |
| "帮我检查这一章写得怎么样" | 调 `get_chapter_full` 读取本章 → 给出评价/问题/建议 → 等待用户反馈 |
| "提出优化建议" | 调读取工具获取数据 → 输出具体优化方案列表 → 等用户选定后执行 |
| "把这段改成……"（附具体文本） | 调 `rewrite_text_segment` 或 `update_chapter_content` 直接执行 |
| "帮我重写这一章，改成……风格"（无具体文本） | 先调 `get_chapter_full` 读取本章 → 给出重写方案/方向让用户确认 → 再调 `adjust_chapter_by_instruction` |
| "帮我修改角色设定" | 调 `get_framework_detail` 查看当前角色 → 给出修改方案 → 待确认后调 `update_characters` |
| "帮我调整大纲/结构" | 调 `get_framework_detail` 查看当前大纲 → 给出调整方案 → 待确认后调 `apply_framework_ops`（明确改动）或 `adjust_framework`（需要 AI 创作） |
| "添加一个新章节" | 调 `get_framework_detail` 查看现有章节 → 给出新章节建议位置 → 待确认后调 `add_chapter_plan` |
| "看看这一章写了什么" | 调 `get_chapter_full` → 总结/展示内容 |
| "有哪些章节，进展如何" | 调 `get_all_chapters_summary` → 呈现概览 |

---

## 📌 核心行为准则

1. **不是每次都要调工具**。如果用户在聊天探讨、讨论创作方向、征求意见，直接用已有的故事上下文（你下面的"故事上下文"部分已经包含了作品信息）参与讨论即可。
2. **每次收到新消息，先把历史中最后一条用户消息作为当前要处理的消息**。不要忽略最新消息去回答之前的问题。新消息是独立的请求。
3. **先理解意图，再决定行动**。每收到一条消息，先花一秒想"用户想干嘛"，而不是默认去改东西。
4. **分析/评估永远必须先读取数据**。没有数据支撑的分析等于空谈。
5. **分析/评估模式下，禁止调用任何写入工具**。输出分析建议后等待用户明确指示"好，按这个改"。如果用户接着要求"按你说的改"，再开始执行修改。
6. **明确修改时，必须先读取确认现状**，再进行修改，避免覆盖已有内容。
7. **模糊创作需求（无具体修改文本）**，先读数据 → 出方案 → 等确认 → 再执行。不要跳过确认步骤。
8. **所有修改必须通过工具调用实际写入数据库**。文字回复不能代替工具调用。
9. **不要暴露工具名和参数等内部细节**，用自然的创作语言说明你做了什么。
10. **可以并行调用多个读取工具**（如同时获取框架和章节列表），以提高效率。
11. **工具调用后我会把结果返回给你**，根据返回的数据决定下一步行动。
    12. **⚠️ 工具调用失败时**：如果返回结果中包含 `"error"` 字段，说明工具执行出错。此时你应当：
        - 告知用户工具执行遇到了什么问题（用自然语言，不要暴露细节）
        - 询问用户能否提供正确的参数信息
        - 如果是因为缺少参数（如 `story_id`），当前作品 ID 已在上方注明
        - **不要默默忽略错误去用其他数据回答问题**。如果工具没法用，就想办法用已有的上下文知识给用户提供帮助，但要明确说明你目前能做什么、不能做什么
    13. **⚠️ 强制批处理规则（必须遵守）**：当用户提出的修改涉及多个章节或多个项目时，**必须**将所有项目一次性传入对应的批量工具，禁止逐个调用单章工具。
        - **多章调整/改写**：必须使用 `batch_adjust_chapters`，将所有待调整章节一次传入。禁止多次调用 `adjust_chapter_by_instruction`。
        - **多章正文保存**：必须使用 `batch_update_chapters`，将所有章节内容一次提交。禁止多次调用 `update_chapter_content`。
        - 角色管理：使用 `update_characters` 传入完整列表，不要逐个增删。
        - 分镜调整：使用 `update_scenes` 一次替换完整列表。
        - 章节规划：如果用户给出明确的章节列表，使用 `bulk_add_chapter_plans` 批量添加。
          如果需要 AI 自主生成章节内容（如"帮我规划后续 5 章"），用 `adjust_framework` 更合适。
        - **违反后果**：每次工具调用触发一次完整的 AI 推理循环。如果逐个调用单章工具，每改完一章会话就会结束，你必须等待用户重新发消息才能继续处理下一章，效率极低且体验差。**一次传入全部章节，是确保多个改动一次性完成的唯一方式。**

### 框架修改工具选择决策树

框架修改时，按以下优先级选择工具：

| 场景 | 推荐工具 | 原因 |
|------|---------|------|
| 用户给出明确修改（"把 X 改成 Y"、"删除角色 Z"、"加 5 章"） | `apply_framework_ops` / `bulk_add_chapter_plans` | 一次 LLM 调用，零额外 AI 成本 |
| 用户需要 AI 创作/生成内容（"让故事更悬疑"、"重新设计第二幕"） | `adjust_framework` | 需要 AI 创作能力生成具体方案 |

原则：**能用 `apply_framework_ops` 解决的，不要用 `adjust_framework`**。

### 框架直接编辑（apply_framework_ops 操作格式参考）

`apply_framework_ops` 的 `operations` 参数结构：

```json
[
  {{"op": "操作名", "target": {{...}}, "changes": {{...}}}},
  {{"op": "操作名", "target": {{...}}, "changes": {{...}}}}
]
```

| op | target | changes | 说明 |
|----|--------|---------|------|
| `update_story_description` | — | `{{"description": "..."}}` | 更新故事描述 |
| `update_tags` | — | `{{...}}` | 更新标签（tags.type/theme/style/audience） |
| `add_character` | — | `{{"name": "...", "role": "...", ...}}` | 添加角色 |
| `update_character` | `{{"name": "角色名"}}` | `{{...}}` | 更新指定角色 |
| `remove_character` | `{{"name": "角色名"}}` | — | 删除角色 |
| `update_act_summary` | `{{"act": "幕标识"}}` | `{{"summary": "..."}}` | 更新幕概要 |
| `add_chapter` | `{{"act": "幕标识"}}` | `{{"chapter_number": N, "title": "...", ...}}` | 添加章节规划 |
| `update_chapter` | `{{"chapter_number": N}}` | `{{"title": "...", "summary": "...", ...}}` | 更新章节规划 |
| `insert_chapter_after` | `{{"chapter_number": N}}` | `{{"chapter_number": N+1, "title": "...", ...}}` | 在指定章节后插入 |
| `move_chapter_to_act` | `{{"chapter_number": N, "act": "目标幕"}}` | — | 移动章节到另一幕 |
| `delete_chapter` | `{{"chapter_number": N}}` | — | 删除章节 |

> 💡 `apply_framework_ops` 支持 `dry_run=true` 参数：设为 true 时只校验不写入数据库，返回预览结果。适合需要先看一眼改动效果再确认的场景。

示例：用户说"把主角改名为李明，添加一个反派叫张三，把第 5 章标题改为'真相'"
→ 调用 apply_framework_ops，operations:
```json
[
  {{"op": "update_character", "target": {{"name": "原主角名"}}, "changes": {{"name": "李明"}}}},
  {{"op": "add_character", "changes": {{"name": "张三", "role": "反派"}}}},
  {{"op": "update_chapter", "target": {{"chapter_number": 5}}, "changes": {{"title": "真相"}}}}
]
```

---

## 📖 故事上下文（以下是当前作品的完整信息，供你参与讨论时参考）
{story_context}"""

    async def run_stream(
        self,
        messages: list[dict],
        story_context: str,
        api_key: str,
        story_id: int = 0,
        mode: AgentMode = "execute",
        pending_change_key: AgentPendingChangeKey | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """运行 agent 聊天循环，生成 SSE 事件。"""
        mode = normalize_agent_mode(mode)
        pending_changes = PendingChangesTracker()
        run_context = AgentRunContext(
            story_id=story_id,
            api_key=api_key,
            mode=mode,
            pending_changes=pending_changes,
            pending_change_key=pending_change_key,
        )
        context_token = _AGENT_RUN_CONTEXT.set(run_context)
        pending_changes_stored = False

        try:
            system_prompt = self._build_system_prompt(story_context, story_id=story_id)
            all_messages: list[dict] = [{"role": "system", "content": system_prompt}] + list(messages)

            collected_content = ""
            iteration_count = 0
            SAFETY_MAX_ITERATIONS = 50  # 熔断：防止无限循环
            write_executed = False

            while iteration_count < SAFETY_MAX_ITERATIONS:
                iteration_count += 1

                payload = {
                    "model": DEEPSEEK_MODEL,
                    "messages": all_messages,
                    "stream": True,
                    "tools": self.tool_registry.get_tool_specs(mode=mode),
                    "max_tokens": 32768,
                }

                collected_content = ""
                tool_calls_acc: dict[int, dict[str, Any]] = {}
                finish_reason: str | None = None

                async with httpx.AsyncClient(timeout=600) as client:
                    async with client.stream(
                        "POST",
                        f"{DEEPSEEK_BASE_URL}/chat/completions",
                        json=payload,
                        headers=_deepseek_auth_headers(api_key),
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                finish_reason = choices[0].get("finish_reason")

                                # 文本 token
                                content = delta.get("content", "")
                                if content:
                                    collected_content += content
                                    yield {"event": "token", "data": json.dumps({"content": content}, ensure_ascii=False)}

                                # 工具调用（流式累加）
                                tool_calls = delta.get("tool_calls", [])
                                for tc in tool_calls:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_calls_acc:
                                        tool_calls_acc[idx] = {
                                            "id": "",
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    if tc.get("id"):
                                        tool_calls_acc[idx]["id"] = tc["id"]
                                    func_data = tc.get("function", {})
                                    if func_data.get("name"):
                                        tool_calls_acc[idx]["function"]["name"] = func_data["name"]
                                    if func_data.get("arguments"):
                                        tool_calls_acc[idx]["function"]["arguments"] += func_data["arguments"]
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue

                # 构建 assistant 消息
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if collected_content:
                    assistant_msg["content"] = collected_content
                else:
                    assistant_msg["content"] = None

                if tool_calls_acc:
                    sorted_indices = sorted(tool_calls_acc.keys())
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tool_calls_acc[i]["id"],
                            "type": "function",
                            "function": {
                                "name": tool_calls_acc[i]["function"]["name"],
                                "arguments": tool_calls_acc[i]["function"]["arguments"],
                            },
                        }
                        for i in sorted_indices
                    ]
                all_messages.append(assistant_msg)

                # 处理工具调用
                if finish_reason == "tool_calls" and tool_calls_acc:
                    sorted_indices = sorted(tool_calls_acc.keys())
                    for i in sorted_indices:
                        tc = tool_calls_acc[i]
                        name = tc["function"]["name"]
                        try:
                            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"].strip() else {}
                        except json.JSONDecodeError:
                            args = {}

                        yield {"event": "tool_call", "data": json.dumps({"name": name, "arguments": args}, ensure_ascii=False)}

                        try:
                            result_str = await self.tool_registry.execute(name, args)
                            yield {"event": "tool_result", "data": json.dumps({"name": name, "result": result_str}, ensure_ascii=False)}
                        except Exception as e:
                            error_msg = json.dumps({"error": str(e)}, ensure_ascii=False)
                            yield {"event": "tool_result", "data": json.dumps({"name": name, "result": error_msg}, ensure_ascii=False)}
                            result_str = error_msg

                        all_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_str,
                        })

                    # 检查是否有写工具成功执行（不含 error）
                    any_write_succeeded = False
                    for i in sorted_indices:
                        tc = tool_calls_acc[i]
                        tool_name = tc["function"]["name"]
                        if self.tool_registry.is_write_tool(tool_name):
                            tool_call_id = tc["id"]
                            for msg in all_messages:
                                if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_call_id:
                                    content_str = str(msg.get("content", ""))
                                    if '"error"' not in content_str:
                                        any_write_succeeded = True
                                    break

                    if any_write_succeeded:
                        write_executed = True
                        all_messages.append({
                            "role": "system",
                            "content": "写入操作已完成。请检查是否所有需要修改的章节都已处理完毕。如果还有章节未处理，请继续调用批量工具完成剩余章节。如果全部完成，请回复用户总结操作结果。",
                        })

                    # 继续循环（把工具结果送回 LLM，让 LLM 判断是否还有未完成的章节需要处理）
                    continue

                # 这里说明没有工具调用了，正常结束
                break

            if write_executed:
                logger.info("Agent 写入操作完成，共 %s 次迭代", iteration_count)
            elif iteration_count >= SAFETY_MAX_ITERATIONS:
                logger.warning("Agent 达到安全熔断上限 %s", SAFETY_MAX_ITERATIONS)

            if pending_change_key is not None:
                agent_pending_change_store.set(pending_change_key, pending_changes)
                pending_changes_stored = True

            yield {"event": "done", "data": json.dumps({
                "content": collected_content,
                "pending_changes": pending_changes.get_summary(),
                "agent_mode": mode,
            }, ensure_ascii=False)}

        finally:
            if pending_change_key is not None and not pending_changes_stored:
                agent_pending_change_store.set(pending_change_key, pending_changes)
            _AGENT_RUN_CONTEXT.reset(context_token)


# ── 模块级单例 ──────────────────────────────────────────

agent_service = AgentService()
