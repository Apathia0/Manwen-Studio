import hashlib
import json
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, update
from sqlalchemy.orm import Session, attributes

from models import (
    AgentContextReceipt,
    Chapter,
    Story,
    StoryKnowledgeCategory,
    StoryKnowledgeEntity,
    StoryKnowledgeFact,
    StoryKnowledgeResource,
    StoryPlotThread,
)
from services.story_state import build_story_bible_compact, build_story_memory_compact, has_active_writing_reference


CONTEXT_PROFILES: dict[str, tuple[str, ...]] = {
    "general": ("story_core", "story_bible", "characters", "story_memory", "book_outline"),
    "framework_designer": ("story_core", "story_bible", "characters", "book_outline", "entities", "facts", "open_threads"),
    "chapter_planner": ("story_core", "chapter_plan", "story_memory", "previous_chapter", "recent_chapters", "entities", "facts", "open_threads"),
    "chapter_writer": ("chapter_plan", "story_memory", "previous_chapter", "recent_chapters", "user_instruction", "entities", "facts", "open_threads", "style_profile"),
    "quality_reviewer": ("chapter_plan", "story_memory", "recent_chapters", "characters", "entities", "facts", "open_threads"),
}

_INTERNAL_CHAPTER_CONTEXT_INSTRUCTIONS = {"生成本章正文创作包"}

_CHAPTER_WRITER_GUIDANCE_EXCLUDED_KEYS = {
    "开书策略",
    "章节密度策略",
    "中段驱动力",
    "后期方向",
    "推荐情节模式",
    "opening_strategy",
    "chapter_density_strategy",
    "middle_stage_driver",
    "late_stage_direction",
    "recommended_plot_patterns",
}

KNOWLEDGE_KIND_MODELS = {
    "resource": StoryKnowledgeResource,
    "entity": StoryKnowledgeEntity,
    "fact": StoryKnowledgeFact,
    "plot_thread": StoryPlotThread,
}

KNOWLEDGE_KIND_FIELDS = {
    "resource": {
        "resource_type", "resource_key", "title", "summary", "content_json", "content_text",
        "importance", "valid_from_chapter", "valid_to_chapter", "status",
    },
    "entity": {
        "entity_key", "entity_type", "canonical_name", "aliases_json", "profile_json",
        "first_chapter", "last_chapter", "importance", "status",
    },
    "fact": {
        "category_id", "subject_key", "predicate", "object_key", "value_json", "value_text",
        "valid_from_chapter", "valid_to_chapter", "confidence", "status",
    },
    "plot_thread": {
        "category_id", "thread_key", "thread_type", "title", "description", "setup_chapter",
        "expected_payoff_from", "expected_payoff_to", "actual_payoff_chapter",
        "related_entity_keys", "priority", "status",
    },
}

KNOWLEDGE_KIND_REQUIRED = {
    "resource": ("title",),
    "entity": ("canonical_name",),
    "fact": (),
    "plot_thread": ("title",),
}

KNOWLEDGE_KIND_DEFAULTS = {
    "resource": {"resource_type": "manual_note", "importance": 50, "status": "active", "source_type": "manual"},
    "entity": {"entity_type": "note", "importance": 50, "status": "active", "source_type": "manual"},
    "fact": {"confidence": Decimal("1.0"), "status": "active", "source_type": "manual"},
    "plot_thread": {"thread_type": "foreshadow", "priority": 50, "status": "open", "source_type": "manual"},
}

DEFAULT_KNOWLEDGE_CATEGORIES: dict[str, tuple[dict[str, Any], ...]] = {
    "fact": (
        {"name": "基础事实", "color": "#2563eb", "sort_order": 10},
        {"name": "人物关系", "color": "#16a34a", "sort_order": 20},
        {"name": "世界规则", "color": "#7c3aed", "sort_order": 30},
    ),
    "plot_thread": (
        {"name": "主要伏笔", "color": "#dc2626", "sort_order": 10},
        {"name": "情感线索", "color": "#db2777", "sort_order": 20},
        {"name": "世界谜团", "color": "#ca8a04", "sort_order": 30},
    ),
}


class StoryKnowledgeConflictError(ValueError):
    """知识条目已被其他请求修改。"""


def _advance_story_revision_in_transaction(db: Session, story: Story) -> int:
    revision = db.execute(
        update(Story)
        .where(Story.id == story.id)
        .values(knowledge_revision=Story.knowledge_revision + 1)
        .returning(Story.knowledge_revision)
    ).scalar_one()
    attributes.set_committed_value(story, "knowledge_revision", int(revision))
    return int(revision)


def normalize_context_profile(value: str | None) -> str:
    profile = str(value or "general").strip().lower()
    return profile if profile in CONTEXT_PROFILES else "general"


def normalize_knowledge_kind(value: str) -> str:
    aliases = {
        "resources": "resource",
        "entities": "entity",
        "facts": "fact",
        "threads": "plot_thread",
        "plot_threads": "plot_thread",
    }
    normalized = str(value or "").strip().lower()
    normalized = aliases.get(normalized, normalized)
    if normalized not in KNOWLEDGE_KIND_MODELS:
        raise ValueError("不支持的知识类型")
    return normalized


def _normalize_category_kind(value: str) -> str:
    normalized = normalize_knowledge_kind(value)
    if normalized not in DEFAULT_KNOWLEDGE_CATEGORIES:
        raise ValueError("该知识类型不支持分类")
    return normalized


def _serialize_category(category: StoryKnowledgeCategory) -> dict[str, Any]:
    return {
        "id": category.id,
        "story_id": category.story_id,
        "knowledge_kind": category.knowledge_kind,
        "name": category.name,
        "color": category.color,
        "sort_order": category.sort_order,
        "version": category.version,
        "created_at": category.created_at.isoformat() if category.created_at else None,
        "updated_at": category.updated_at.isoformat() if category.updated_at else None,
    }


def ensure_story_knowledge_categories(db: Session, *, story: Story, commit: bool = True) -> dict[str, list[StoryKnowledgeCategory]]:
    existing = (
        db.query(StoryKnowledgeCategory)
        .filter(StoryKnowledgeCategory.story_id == story.id)
        .order_by(StoryKnowledgeCategory.knowledge_kind, StoryKnowledgeCategory.sort_order, StoryKnowledgeCategory.id)
        .all()
    )
    by_kind: dict[str, list[StoryKnowledgeCategory]] = {"fact": [], "plot_thread": []}
    existing_names = {(item.knowledge_kind, item.name) for item in existing}
    for item in existing:
        if item.knowledge_kind in by_kind:
            by_kind[item.knowledge_kind].append(item)
    changed = False
    for kind, defaults in DEFAULT_KNOWLEDGE_CATEGORIES.items():
        if by_kind[kind]:
            continue
        for default in defaults:
            key = (kind, default["name"])
            if key in existing_names:
                continue
            category = StoryKnowledgeCategory(
                story_id=story.id,
                knowledge_kind=kind,
                name=default["name"],
                color=default["color"],
                sort_order=default["sort_order"],
            )
            db.add(category)
            by_kind[kind].append(category)
            existing_names.add(key)
            changed = True
    if changed:
        if commit:
            db.commit()
            db.refresh(story)
    for kind in by_kind:
        by_kind[kind].sort(key=lambda item: (item.sort_order or 0, item.id or 0))
    return by_kind


def _category_lookup(db: Session, *, story: Story) -> dict[int, StoryKnowledgeCategory]:
    categories = ensure_story_knowledge_categories(db, story=story)
    return {item.id: item for rows in categories.values() for item in rows if item.id is not None}


def _default_category_id(db: Session, *, story: Story, kind: str) -> int | None:
    categories = ensure_story_knowledge_categories(db, story=story)
    rows = categories.get(kind) or []
    return rows[0].id if rows else None


def serialize_story_knowledge_item(kind: str, item: Any) -> dict[str, Any]:
    normalized = normalize_knowledge_kind(kind)
    fields = KNOWLEDGE_KIND_FIELDS[normalized]
    result = {
        "id": item.id,
        "story_id": item.story_id,
        "kind": normalized,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if getattr(item, "updated_at", None) else None,
    }
    for field in fields:
        value = getattr(item, field, None)
        result[field] = float(value) if isinstance(value, Decimal) else value
    result["source_type"] = getattr(item, "source_type", None)
    result["source_id"] = getattr(item, "source_id", None)
    result["version"] = getattr(item, "version", None)
    category_id = getattr(item, "category_id", None)
    if category_id is not None:
        result["category_id"] = category_id
        result["category_name"] = getattr(item, "_category_name", None)
    return result


def list_story_knowledge(db: Session, *, story: Story) -> dict[str, Any]:
    sync_story_knowledge_from_legacy(db, story=story)
    categories = ensure_story_knowledge_categories(db, story=story)
    category_by_id = {item.id: item for rows in categories.values() for item in rows if item.id is not None}
    collections: dict[str, list[dict[str, Any]]] = {}
    for kind, model in KNOWLEDGE_KIND_MODELS.items():
        rows = db.query(model).filter(model.story_id == story.id).order_by(model.id.desc()).limit(1000).all()
        for row in rows:
            category = category_by_id.get(getattr(row, "category_id", None))
            if category is not None:
                setattr(row, "_category_name", category.name)
        collections[f"{kind}s" if kind != "entity" else "entities"] = [
            serialize_story_knowledge_item(kind, row) for row in rows
        ]
    collections["plot_threads"] = collections.pop("plot_threads", [])
    counts = {
        "resource": len(collections.get("resources", [])),
        "entity": len(collections.get("entities", [])),
        "fact": len(collections.get("facts", [])),
        "plot_thread": len(collections.get("plot_threads", [])),
    }
    return {
        "story_id": story.id,
        "knowledge_revision": int(story.knowledge_revision or 1),
        "story_bible": story.story_bible if isinstance(story.story_bible, dict) else {},
        "categories": [
            _serialize_category(item)
            for rows in categories.values()
            for item in rows
        ],
        "counts": counts,
        **collections,
    }


def create_story_knowledge_category(
    db: Session,
    *,
    story: Story,
    knowledge_kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    kind = _normalize_category_kind(knowledge_kind)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("分类名称不能为空")
    category = StoryKnowledgeCategory(
        story_id=story.id,
        knowledge_kind=kind,
        name=name,
        color=str(payload.get("color") or "").strip() or None,
        sort_order=int(payload.get("sort_order") or 0),
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return _serialize_category(category)


def update_story_knowledge_category(
    db: Session,
    *,
    story: Story,
    category_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    category = db.get(StoryKnowledgeCategory, category_id)
    if not category or category.story_id != story.id:
        raise LookupError("知识分类未找到")
    expected_version = payload.get("expected_version")
    if expected_version is None:
        raise ValueError("缺少 expected_version")
    if int(category.version or 1) != int(expected_version):
        raise StoryKnowledgeConflictError("知识分类已被其他页面修改，请刷新后重试")
    values: dict[str, Any] = {}
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("分类名称不能为空")
        values["name"] = name
    if "color" in payload:
        values["color"] = str(payload.get("color") or "").strip() or None
    if "sort_order" in payload:
        values["sort_order"] = int(payload.get("sort_order") or 0)
    result = db.execute(
        update(StoryKnowledgeCategory)
        .where(
            StoryKnowledgeCategory.id == category_id,
            StoryKnowledgeCategory.story_id == story.id,
            StoryKnowledgeCategory.version == int(expected_version),
        )
        .values(**values, version=StoryKnowledgeCategory.version + 1)
    )
    if result.rowcount != 1:
        db.rollback()
        raise StoryKnowledgeConflictError("知识分类已被其他页面修改，请刷新后重试")
    _advance_story_revision_in_transaction(db, story)
    db.commit()
    db.refresh(category)
    return _serialize_category(category)


def delete_story_knowledge_category(
    db: Session,
    *,
    story: Story,
    category_id: int,
    expected_version: int,
) -> None:
    category = db.get(StoryKnowledgeCategory, category_id)
    if not category or category.story_id != story.id:
        raise LookupError("知识分类未找到")
    if int(category.version or 1) != int(expected_version):
        raise StoryKnowledgeConflictError("知识分类已被其他页面修改，请刷新后重试")
    same_kind_count = (
        db.query(StoryKnowledgeCategory)
        .filter(
            StoryKnowledgeCategory.story_id == story.id,
            StoryKnowledgeCategory.knowledge_kind == category.knowledge_kind,
        )
        .count()
    )
    if same_kind_count <= 1:
        raise StoryKnowledgeConflictError("不能删除最后一个知识分类")
    model = StoryKnowledgeFact if category.knowledge_kind == "fact" else StoryPlotThread
    referenced = (
        db.query(model.id)
        .filter(model.story_id == story.id, model.category_id == category.id)
        .first()
        is not None
    )
    if referenced:
        raise StoryKnowledgeConflictError("该分类已被知识条目引用，无法删除")
    db.delete(category)
    db.commit()


def _prepare_knowledge_values(kind: str, payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    normalized = normalize_knowledge_kind(kind)
    allowed = KNOWLEDGE_KIND_FIELDS[normalized]
    values = {key: value for key, value in payload.items() if key in allowed}
    for key, value in list(values.items()):
        if isinstance(value, str):
            values[key] = value.strip()
    if creating:
        for default_key in KNOWLEDGE_KIND_DEFAULTS[normalized]:
            if values.get(default_key) is None:
                values.pop(default_key, None)
        values = {**KNOWLEDGE_KIND_DEFAULTS[normalized], **values}
    if normalized in KNOWLEDGE_KIND_MODELS:
        values["source_type"] = "manual"
    if normalized == "fact" and "confidence" in values and values["confidence"] is not None:
        values["confidence"] = Decimal(str(values["confidence"]))
    if creating:
        manual_key = f"manual:{uuid.uuid4().hex}"
        if normalized == "resource" and not values.get("resource_key"):
            values["resource_key"] = manual_key
        elif normalized == "entity" and not values.get("entity_key"):
            values["entity_key"] = manual_key
        elif normalized == "plot_thread" and not values.get("thread_key"):
            values["thread_key"] = manual_key
        elif normalized == "fact":
            if not values.get("subject_key"):
                values["subject_key"] = "story"
            if not values.get("predicate"):
                values["predicate"] = "note"
    if normalized == "resource" and ({"content_json", "content_text"} & values.keys()):
        content = values.get("content_json") if values.get("content_json") is not None else values.get("content_text")
        values["content_hash"] = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    allowed_statuses = (
        {"open", "active", "due", "resolved", "archived", "abandoned"}
        if normalized == "plot_thread"
        else {"active", "archived", "superseded"}
    )
    if values.get("status") is not None and values["status"] not in allowed_statuses:
        raise ValueError("状态值不合法")
    range_pairs = (
        ("valid_from_chapter", "valid_to_chapter"),
        ("first_chapter", "last_chapter"),
        ("expected_payoff_from", "expected_payoff_to"),
    )
    for start_key, end_key in range_pairs:
        start = values.get(start_key)
        end = values.get(end_key)
        if start is not None and end is not None and start > end:
            raise ValueError(f"{start_key} 不能大于 {end_key}")
    return values


def _validate_category_for_item(db: Session, *, story: Story, kind: str, values: dict[str, Any], creating: bool) -> None:
    if kind not in DEFAULT_KNOWLEDGE_CATEGORIES:
        return
    assigned_default = False
    if creating and not values.get("category_id"):
        categories = ensure_story_knowledge_categories(db, story=story, commit=False)
        rows = categories.get(kind) or []
        if rows:
            if rows[0].id is not None:
                values["category_id"] = rows[0].id
            else:
                values["_category_obj"] = rows[0]
        assigned_default = True
    category_id = values.get("category_id")
    if category_id is None:
        return
    if assigned_default:
        return
    category = db.get(StoryKnowledgeCategory, int(category_id))
    if not category or category.story_id != story.id or category.knowledge_kind != kind:
        raise ValueError("知识分类不属于当前作品或类型不匹配")


def create_story_knowledge_item(
    db: Session,
    *,
    story: Story,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_knowledge_kind(kind)
    values = _prepare_knowledge_values(normalized, payload, creating=True)
    _validate_category_for_item(db, story=story, kind=normalized, values=values, creating=True)
    missing = [key for key in KNOWLEDGE_KIND_REQUIRED[normalized] if not values.get(key)]
    if normalized == "fact" and values.get("value_text") in (None, "") and values.get("value_json") is None:
        if not (payload.get("subject_key") and payload.get("predicate")):
            missing.append("value_text")
    if missing:
        raise ValueError(f"缺少必填字段: {', '.join(missing)}")
    category_obj = values.pop("_category_obj", None)
    item = KNOWLEDGE_KIND_MODELS[normalized](story_id=story.id, **values)
    if category_obj is not None:
        item.category = category_obj
    db.add(item)
    db.commit()
    db.refresh(item)
    if getattr(item, "category_id", None):
        category = db.get(StoryKnowledgeCategory, item.category_id)
        if category is not None:
            setattr(item, "_category_name", category.name)
    return serialize_story_knowledge_item(normalized, item)


def update_story_knowledge_item(
    db: Session,
    *,
    story: Story,
    kind: str,
    item_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_knowledge_kind(kind)
    model = KNOWLEDGE_KIND_MODELS[normalized]
    item = db.get(model, item_id)
    if not item or item.story_id != story.id:
        raise LookupError("知识条目未找到")
    expected_version = payload.get("expected_version")
    if expected_version is None:
        raise ValueError("缺少 expected_version")
    if int(item.version or 1) != int(expected_version):
        raise StoryKnowledgeConflictError("知识条目已被其他页面修改，请刷新后重试")
    values = _prepare_knowledge_values(normalized, payload, creating=False)
    _validate_category_for_item(db, story=story, kind=normalized, values=values, creating=False)
    for required in KNOWLEDGE_KIND_REQUIRED[normalized]:
        if not values.get(required, getattr(item, required, None)):
            raise ValueError(f"{required} 不能为空")
    range_pairs = (
        ("valid_from_chapter", "valid_to_chapter"),
        ("first_chapter", "last_chapter"),
        ("expected_payoff_from", "expected_payoff_to"),
    )
    for start_key, end_key in range_pairs:
        start = values.get(start_key, getattr(item, start_key, None))
        end = values.get(end_key, getattr(item, end_key, None))
        if start is not None and end is not None and start > end:
            raise ValueError(f"{start_key} 不能大于 {end_key}")
    result = db.execute(
        update(model)
        .where(
            model.id == item_id,
            model.story_id == story.id,
            model.version == int(expected_version),
        )
        .values(**values, version=model.version + 1)
    )
    if result.rowcount != 1:
        db.rollback()
        raise StoryKnowledgeConflictError("知识条目已被其他页面修改，请刷新后重试")
    _advance_story_revision_in_transaction(db, story)
    db.commit()
    db.refresh(item)
    if getattr(item, "category_id", None):
        category = db.get(StoryKnowledgeCategory, item.category_id)
        if category is not None:
            setattr(item, "_category_name", category.name)
    return serialize_story_knowledge_item(normalized, item)


def delete_story_knowledge_item(
    db: Session,
    *,
    story: Story,
    kind: str,
    item_id: int,
    expected_version: int,
) -> None:
    normalized = normalize_knowledge_kind(kind)
    model = KNOWLEDGE_KIND_MODELS[normalized]
    item = db.get(model, item_id)
    if not item or item.story_id != story.id:
        raise LookupError("知识条目未找到")
    if getattr(item, "source_type", "manual") != "manual":
        raise StoryKnowledgeConflictError("该记录由作品圣经或章节记忆同步，请先编辑为人工维护记录")
    result = db.execute(
        delete(model).where(
            model.id == item_id,
            model.story_id == story.id,
            model.version == int(expected_version),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise StoryKnowledgeConflictError("知识条目已被其他页面修改，请刷新后重试")
    _advance_story_revision_in_transaction(db, story)
    db.commit()


def _legacy_source_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _story_state_list(story: Story, key: str) -> list[Any]:
    bible = story.story_bible if isinstance(story.story_bible, dict) else {}
    state = bible.get("story_state") if isinstance(bible.get("story_state"), dict) else {}
    value = state.get(key)
    return value if isinstance(value, list) else []


def _knowledge_text(value: Any, keys: tuple[str, ...] = ("text", "fact", "description", "title", "summary")) -> str:
    if isinstance(value, dict):
        for key in keys:
            text_value = str(value.get(key) or "").strip()
            if text_value:
                return text_value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value or "").strip()


def sync_story_knowledge_from_legacy(
    db: Session,
    *,
    story: Story,
    source_chapter_id: int | None = None,
    commit: bool = True,
) -> bool:
    """把现有角色和连续性记忆幂等同步到结构化知识表，不额外调用 AI。"""
    changed = False
    characters = story.characters if isinstance(story.characters, list) else []
    memory = story.story_memory if isinstance(story.story_memory, dict) else {}
    chapter_number = None
    # 同步可能在作品 JSON 刚更新、尚未提交时调用，查询阶段禁止 autoflush，确保一次逻辑变更只推进一个知识版本。
    with db.no_autoflush:
        if source_chapter_id:
            source_chapter = db.get(Chapter, source_chapter_id)
            if source_chapter and source_chapter.story_id == story.id:
                chapter_number = source_chapter.chapter_number
        entities_by_key = {
            item.entity_key: item
            for item in db.query(StoryKnowledgeEntity).filter_by(story_id=story.id).all()
        }
        facts_by_source = {
            item.source_id: item
            for item in db.query(StoryKnowledgeFact)
            .filter(StoryKnowledgeFact.story_id == story.id, StoryKnowledgeFact.source_id.is_not(None))
            .all()
        }
        threads_by_key = {
            item.thread_key: item
            for item in db.query(StoryPlotThread).filter_by(story_id=story.id).all()
        }
        pending_before_categories = len(db.new)
        categories = ensure_story_knowledge_categories(db, story=story, commit=False)
    if len(db.new) > pending_before_categories:
        changed = True
    default_fact_category_id = categories["fact"][0].id if categories.get("fact") else None
    default_thread_category_id = categories["plot_thread"][0].id if categories.get("plot_thread") else None
    default_fact_category = categories["fact"][0] if categories.get("fact") else None
    default_thread_category = categories["plot_thread"][0] if categories.get("plot_thread") else None

    current_entity_keys: set[str] = set()
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or character.get("canonical_name") or "").strip()
        if not name:
            continue
        entity_key = _legacy_source_key("legacy:character", name)
        current_entity_keys.add(entity_key)
        entity = entities_by_key.get(entity_key)
        profile = dict(character)
        if entity is None:
            entity = StoryKnowledgeEntity(
                story_id=story.id,
                entity_key=entity_key,
                entity_type="character",
                canonical_name=name,
                aliases_json=[],
                profile_json=profile,
                importance=80 if str(character.get("role") or "").strip() in {"主角", "protagonist"} else 60,
                status="active",
                source_type="legacy_projection",
                source_id=f"story.characters:{name}",
            )
            db.add(entity)
            entities_by_key[entity_key] = entity
            changed = True
        elif entity.source_type != "manual":
            if entity.canonical_name != name or entity.profile_json != profile or entity.status != "active":
                entity.canonical_name = name
                entity.profile_json = profile
                entity.status = "active"
                entity.source_type = "legacy_projection"
                entity.version = int(entity.version or 1) + 1
                changed = True
    for entity_key, entity in entities_by_key.items():
        if entity.source_type == "legacy_projection" and entity_key not in current_entity_keys and entity.status != "archived":
            entity.status = "archived"
            entity.version = int(entity.version or 1) + 1
            changed = True

    continuity_facts = memory.get("continuity_facts") if isinstance(memory.get("continuity_facts"), list) else []
    current_fact_source_ids: set[str] = set()
    for raw_fact in continuity_facts:
        fact_text = str(raw_fact or "").strip()
        if not fact_text:
            continue
        source_id = _legacy_source_key("story_memory:fact", fact_text)
        current_fact_source_ids.add(source_id)
        fact = facts_by_source.get(source_id)
        if fact is None:
            fact = StoryKnowledgeFact(
                story_id=story.id,
                category_id=default_fact_category_id,
                subject_key="story",
                predicate="continuity",
                value_text=fact_text,
                valid_from_chapter=chapter_number,
                source_type="story_memory",
                source_id=source_id,
                source_chapter_id=source_chapter_id,
                status="active",
            )
            if default_fact_category_id is None and default_fact_category is not None:
                fact.category = default_fact_category
            db.add(fact)
            facts_by_source[source_id] = fact
            changed = True
        elif fact.source_type != "manual" and fact.status != "active":
            fact.status = "active"
            fact.version = int(fact.version or 1) + 1
            changed = True
    for source_id, fact in facts_by_source.items():
        if (
            fact.source_type == "story_memory"
            and fact.predicate == "continuity"
            and source_id not in current_fact_source_ids
            and fact.status != "archived"
        ):
            fact.status = "archived"
            fact.version = int(fact.version or 1) + 1
            changed = True

    bible_continuity_facts = _story_state_list(story, "continuity_facts")
    current_bible_fact_source_ids: set[str] = set()
    for raw_fact in bible_continuity_facts:
        fact_text = _knowledge_text(raw_fact)
        if not fact_text:
            continue
        source_id = _legacy_source_key("story_bible:fact", fact_text)
        current_bible_fact_source_ids.add(source_id)
        fact = facts_by_source.get(source_id)
        if fact is None:
            fact = StoryKnowledgeFact(
                story_id=story.id,
                category_id=default_fact_category_id,
                subject_key="story",
                predicate="continuity",
                value_text=fact_text,
                source_type="story_bible",
                source_id=source_id,
                status="active",
            )
            if default_fact_category_id is None and default_fact_category is not None:
                fact.category = default_fact_category
            db.add(fact)
            facts_by_source[source_id] = fact
            changed = True
        elif fact.source_type != "manual" and fact.status != "active":
            fact.status = "active"
            fact.version = int(fact.version or 1) + 1
            changed = True
    for source_id, fact in facts_by_source.items():
        if (
            fact.source_type == "story_bible"
            and fact.predicate == "continuity"
            and source_id not in current_bible_fact_source_ids
            and fact.status != "archived"
        ):
            fact.status = "archived"
            fact.version = int(fact.version or 1) + 1
            changed = True

    open_loops = memory.get("open_loops") if isinstance(memory.get("open_loops"), list) else []
    resolved_loops = memory.get("resolved_loops") if isinstance(memory.get("resolved_loops"), list) else []
    current_thread_keys: set[str] = set()
    for raw_loop in open_loops:
        loop_text = str(raw_loop or "").strip()
        if not loop_text:
            continue
        thread_key = _legacy_source_key("memory:loop", loop_text)
        current_thread_keys.add(thread_key)
        thread = threads_by_key.get(thread_key)
        if thread is None:
            thread = StoryPlotThread(
                story_id=story.id,
                category_id=default_thread_category_id,
                thread_key=thread_key,
                thread_type="foreshadow",
                title=loop_text[:255],
                description=loop_text,
                setup_chapter=chapter_number,
                priority=60,
                status="open",
                source_type="story_memory",
                source_id=thread_key,
            )
            if default_thread_category_id is None and default_thread_category is not None:
                thread.category = default_thread_category
            db.add(thread)
            threads_by_key[thread_key] = thread
            changed = True
        elif thread.source_type != "manual" and thread.status not in {"open", "active", "due"}:
            thread.status = "open"
            thread.actual_payoff_chapter = None
            thread.version = int(thread.version or 1) + 1
            changed = True

    for raw_loop in resolved_loops:
        loop_text = str(raw_loop or "").strip()
        if not loop_text:
            continue
        thread_key = _legacy_source_key("memory:loop", loop_text)
        current_thread_keys.add(thread_key)
        thread = threads_by_key.get(thread_key)
        if thread is None:
            thread = StoryPlotThread(
                story_id=story.id,
                category_id=default_thread_category_id,
                thread_key=thread_key,
                thread_type="foreshadow",
                title=loop_text[:255],
                description=loop_text,
                setup_chapter=chapter_number,
                actual_payoff_chapter=chapter_number,
                priority=60,
                status="resolved",
                source_type="story_memory",
                source_id=thread_key,
            )
            if default_thread_category_id is None and default_thread_category is not None:
                thread.category = default_thread_category
            db.add(thread)
            threads_by_key[thread_key] = thread
            changed = True
        elif thread.source_type != "manual" and thread.status != "resolved":
            thread.status = "resolved"
            thread.actual_payoff_chapter = chapter_number
            thread.version = int(thread.version or 1) + 1
            changed = True
    for thread_key, thread in threads_by_key.items():
        if thread.source_type == "story_memory" and thread_key not in current_thread_keys and thread.status != "archived":
            thread.status = "archived"
            thread.version = int(thread.version or 1) + 1
            changed = True

    bible_open_loops = _story_state_list(story, "open_loops")
    current_bible_thread_keys: set[str] = set()
    for raw_loop in bible_open_loops:
        loop_text = _knowledge_text(raw_loop, ("title", "text", "description", "summary"))
        if not loop_text:
            continue
        thread_key = _legacy_source_key("story_bible:loop", loop_text)
        current_bible_thread_keys.add(thread_key)
        thread = threads_by_key.get(thread_key)
        if thread is None:
            thread = StoryPlotThread(
                story_id=story.id,
                category_id=default_thread_category_id,
                thread_key=thread_key,
                thread_type="foreshadow",
                title=loop_text[:255],
                description=loop_text,
                priority=60,
                status="open",
                source_type="story_bible",
                source_id=thread_key,
            )
            if default_thread_category_id is None and default_thread_category is not None:
                thread.category = default_thread_category
            db.add(thread)
            threads_by_key[thread_key] = thread
            changed = True
        elif thread.source_type != "manual" and thread.status not in {"open", "active", "due"}:
            thread.status = "open"
            thread.actual_payoff_chapter = None
            thread.version = int(thread.version or 1) + 1
            changed = True
    for thread_key, thread in threads_by_key.items():
        if thread.source_type == "story_bible" and thread_key not in current_bible_thread_keys and thread.status != "archived":
            thread.status = "archived"
            thread.version = int(thread.version or 1) + 1
            changed = True

    if changed and commit:
        db.commit()
        db.refresh(story)
    return changed


def bump_story_knowledge_revision(db: Session, story_id: int) -> int:
    """在作品内容变更后推进知识版本，使旧读取凭证可被识别。"""
    revision = db.execute(
        update(Story)
        .where(Story.id == story_id)
        .values(knowledge_revision=Story.knowledge_revision + 1)
        .returning(Story.knowledge_revision)
    ).scalar_one_or_none()
    db.commit()
    return int(revision or 0)


def validate_context_receipt(
    db: Session,
    *,
    story_id: int,
    run_id: str | None,
    owner_user_id: int | None = None,
    task_types: tuple[str, ...] | None = None,
    chapter_number: int | None = None,
) -> tuple[bool, str]:
    """校验当前 Agent run 是否读取过最新作品知识。

    章节维度采用宽松匹配：验证传入具体章节号时，接受"章节号一致"或"未绑定章节号"
    （resolve 时未传 chapter_number）的读取凭证，避免框架/正文任务因章节号语义
    不一致而误判为未读取上下文。task_type 与知识版本仍为精确校验。
    """
    if not run_id:
        return False, "missing_run_id"
    story = db.get(Story, story_id)
    if not story:
        return False, "story_not_found"
    receipt = (
        db.query(AgentContextReceipt)
        .filter(
            AgentContextReceipt.story_id == story_id,
            AgentContextReceipt.run_id == run_id,
            *(
                (AgentContextReceipt.owner_user_id == owner_user_id,)
                if owner_user_id is not None
                else ()
            ),
            *(
                (AgentContextReceipt.task_type.in_(task_types),)
                if task_types
                else ()
            ),
            *(
                (
                    or_(
                        AgentContextReceipt.chapter_number == chapter_number,
                        AgentContextReceipt.chapter_number.is_(None),
                    ),
                )
                if chapter_number is not None
                else ()
            ),
        )
        .order_by(AgentContextReceipt.created_at.desc(), AgentContextReceipt.id.desc())
        .first()
    )
    if not receipt:
        return False, "context_not_resolved"
    if receipt.knowledge_revision != int(story.knowledge_revision or 1):
        return False, "context_stale"
    return True, "ok"


def _outline_chapters(outline: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(outline, dict):
        return []
    result: list[dict[str, Any]] = []
    acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
    for act in acts:
        if not isinstance(act, dict):
            continue
        for item in act.get("chapters") if isinstance(act.get("chapters"), list) else []:
            if isinstance(item, dict):
                result.append(item)
    return result


def _chapter_number(item: dict[str, Any]) -> int | None:
    value = item.get("chapter_number")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _chapter_plan(outline: dict[str, Any] | None, chapter_number: int | None, *, current_only: bool = False) -> dict[str, Any]:
    chapters = _outline_chapters(outline)
    if not chapter_number:
        return {"recent_plans": chapters[-10:]}
    current = next((item for item in chapters if _chapter_number(item) == chapter_number), {})
    if current_only:
        return {"current": current}
    previous = [item for item in chapters if (_chapter_number(item) or 0) < chapter_number][-2:]
    future = [item for item in chapters if (_chapter_number(item) or 0) > chapter_number][:4]
    return {
        "current": current,
        "previous_for_continuity": previous,
        "future_for_boundary_only": future,
    }


def _character_digest(characters: list[dict[str, Any]] | None, limit: int = 16) -> list[dict[str, Any]]:
    if not isinstance(characters, list):
        return []
    keys = ("name", "role", "identity", "personality", "motivation", "goal", "ability", "relationship")
    return [
        {key: item.get(key) for key in keys if item.get(key) not in (None, "", [], {})}
        for item in characters[:limit]
        if isinstance(item, dict)
    ]


def build_agent_story_manifest(story: Story, chapter: Chapter | None = None) -> str:
    chapter_line = "未指定"
    if chapter is not None:
        chapter_line = f"第{chapter.chapter_number}章（chapter_id={chapter.id}，标题={chapter.title or '未命名'}）"
    available = ["story_core", "story_bible", "characters", "book_outline", "story_memory"]
    return (
        "## 当前作品知识清单\n"
        f"作品 ID: {story.id}\n"
        f"作品标题: {story.title or '未命名'}\n"
        f"知识版本: {int(getattr(story, 'knowledge_revision', 1) or 1)}\n"
        f"当前章节: {chapter_line}\n"
        f"基础资源: {', '.join(available)}\n"
        "作品详细设定不再默认注入。执行框架设计、章节规划、正文创作或质量审查前，"
        "先调用 resolve_story_context 获取对应任务的数据库知识上下文；信息不足时再调用 search_story_knowledge。"
    )


def _resource_payload(resource: StoryKnowledgeResource) -> dict[str, Any]:
    return {
        "key": resource.resource_key,
        "type": resource.resource_type,
        "title": resource.title,
        "summary": resource.summary,
        "content": resource.content_json if resource.content_json is not None else resource.content_text,
        "version": resource.version,
        "source_type": resource.source_type,
    }


def _retrieval_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip().casefold()
    return json.dumps(value, ensure_ascii=False, default=str).casefold()


def _search_terms(text: str) -> tuple[str, ...]:
    stopwords = {"如何", "具体", "当前", "本章", "主角", "内容", "说明", "状态", "相关", "问题", "需要", "后续"}
    terms: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9:_-]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.append(token)
            for size in (2, 3, 4):
                terms.extend(token[index:index + size] for index in range(max(0, len(token) - size + 1)))
        else:
            terms.append(token)
    return tuple(dict.fromkeys(
        item
        for item in terms
        if len(item) >= 2 and not any(stopword in item for stopword in stopwords)
    ))


def _retrieval_terms(value: Any) -> tuple[str, tuple[str, ...]]:
    focus = _retrieval_text(value)
    terms = _search_terms(focus)
    return focus, terms[:80]


def _semantic_lookup_terms(terms: tuple[str, ...]) -> list[str]:
    chinese_terms = [term for term in terms if re.fullmatch(r"[\u4e00-\u9fff]{2,}", term)]
    longer = sorted((term for term in chinese_terms if len(term) > 4), key=len, reverse=True)[:8]
    compact = [term for term in chinese_terms if 2 <= len(term) <= 4][:24]
    return list(dict.fromkeys([*longer, *compact]))[:16]


def _append_unique_rows(target: list[Any], rows: list[Any]) -> None:
    seen = {getattr(item, "id", None) for item in target}
    for item in rows:
        item_id = getattr(item, "id", None)
        if item_id in seen:
            continue
        seen.add(item_id)
        target.append(item)


def _text_relevance(focus: str, terms: tuple[str, ...], *values: Any) -> int:
    haystack = " ".join(_retrieval_text(value) for value in values if value not in (None, "", [], {}))
    if not haystack or not focus:
        return 0
    score = 0
    if haystack in focus or focus in haystack:
        score += 80
    score += min(60, sum(12 for term in terms if term in haystack))
    haystack_terms = _search_terms(haystack)
    score += min(140, sum(40 for term in haystack_terms if term in focus))
    return score


def _source_authority(source_type: str | None) -> int:
    normalized = str(source_type or "").strip().lower()
    if normalized == "manual":
        return 30
    if normalized in {"story_bible", "system"}:
        return 24
    if normalized in {"story_memory", "legacy_projection"}:
        return 14
    return 8


def _chapter_number_by_id(db: Session, story_id: int) -> dict[int, int]:
    return {
        int(chapter_id): int(chapter_number)
        for chapter_id, chapter_number in db.query(Chapter.id, Chapter.chapter_number)
        .filter(Chapter.story_id == story_id)
        .all()
        if chapter_id is not None and chapter_number is not None
    }


def _ai_sync_source_chapter_number(source_id: str | None, chapter_numbers: dict[int, int]) -> int | None:
    match = re.search(r"^ai_sync:v\d+:(?:entity|fact|thread):c(\d+):", str(source_id or ""))
    if not match:
        return None
    return chapter_numbers.get(int(match.group(1)))


def _fact_start_chapter(item: StoryKnowledgeFact, chapter_numbers: dict[int, int]) -> int | None:
    candidates: list[int] = []
    if item.valid_from_chapter is not None:
        candidates.append(int(item.valid_from_chapter))
    if item.source_chapter_id is not None:
        source_number = chapter_numbers.get(int(item.source_chapter_id))
        if source_number is not None:
            candidates.append(source_number)
    source_number = _ai_sync_source_chapter_number(item.source_id, chapter_numbers)
    if source_number is not None:
        candidates.append(source_number)
    return max(candidates) if candidates else None


def _entity_start_chapter(item: StoryKnowledgeEntity, chapter_numbers: dict[int, int]) -> int | None:
    if item.first_chapter is not None:
        return int(item.first_chapter)
    return _ai_sync_source_chapter_number(item.source_id, chapter_numbers)


def _thread_setup_chapter(item: StoryPlotThread, chapter_numbers: dict[int, int]) -> int | None:
    if item.setup_chapter is not None:
        return int(item.setup_chapter)
    return _ai_sync_source_chapter_number(item.source_id, chapter_numbers)


def _entity_display_name(entity_key: str | None, entities: dict[str, StoryKnowledgeEntity]) -> str | None:
    if not entity_key:
        return None
    if entity_key in entities:
        return str(entities[entity_key].canonical_name or "").strip() or None
    return {"story": "全书状态", "world_story": "世界设定"}.get(entity_key)


def _replace_entity_references(value: Any, entities: dict[str, StoryKnowledgeEntity]) -> Any:
    if not isinstance(value, str):
        return value
    result = value
    for key, entity in sorted(entities.items(), key=lambda row: len(row[0]), reverse=True):
        name = str(entity.canonical_name or "").strip()
        if key and name:
            result = result.replace(key, name)
    return result


def _chapter_entity_profile(profile: Any, allowed_relation_names: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    allowed = (
        "role", "identity", "occupation", "realm", "faction", "location", "appearance",
        "personality", "motivation", "goal", "ability", "weakness", "current_state",
        "description", "relationships",
    )
    result = {
        key: profile[key]
        for key in allowed
        if profile.get(key) not in (None, "", [], {})
    }
    relationships = result.get("relationships")
    if isinstance(relationships, list) and allowed_relation_names is not None:
        result["relationships"] = [
            item
            for item in relationships
            if isinstance(item, dict)
            and str(item.get("to") or item.get("target") or "").strip() in allowed_relation_names
        ]
        if not result["relationships"]:
            result.pop("relationships")
    return result


def _thread_semantic_key(title: str | None) -> str:
    text = str(title or "").strip().casefold()
    text = re.sub(r"[？?！!。．，,、；;：:\s]+", "", text)
    text = re.sub(r"[（(](?:已解决|已完成|本章已[^）)]*)[）)]", "", text)
    return text


_ENTITY_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "母": ("母亲", "母子", "母女", "娘亲"),
    "父": ("父亲", "父子", "父女", "爹"),
    "兄": ("兄长", "兄弟", "哥哥"),
    "弟": ("兄弟", "弟弟"),
    "姐": ("姐妹", "姐姐"),
    "妹": ("姐妹", "妹妹"),
    "师": ("师父", "师尊", "师傅"),
}


def _entity_has_direct_chapter_evidence(item: StoryKnowledgeEntity, focus_text: str, focus_terms: tuple[str, ...]) -> tuple[bool, int]:
    """只使用身份字段判断人物是否被章节任务直接提及，避免人物关系和成长弧中的泛词误召回。"""
    profile = item.profile_json if isinstance(item.profile_json, dict) else {}
    identity_profile = {
        key: profile.get(key)
        for key in ("role", "identity", "occupation", "realm", "faction", "location", "tags")
        if profile.get(key) not in (None, "", [], {})
    }
    relevance = _text_relevance(
        focus_text,
        focus_terms,
        item.entity_key,
        item.canonical_name,
        item.aliases_json,
        identity_profile,
    )
    if relevance > 0:
        return True, relevance
    name = str(item.canonical_name or "").strip()
    if focus_text and name:
        for suffix, hints in _ENTITY_FAMILY_HINTS.items():
            if name.endswith(suffix) and any(hint in focus_text for hint in hints):
                return True, 60
    return False, 0


def _legacy_sections(
    db: Session,
    story: Story,
    requested: set[str],
    chapter_number: int | None,
    profile: str,
) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    immediate_previous_number: int | None = None
    nonblank_chapter_content = func.length(func.trim(
        func.replace(func.replace(func.replace(Chapter.novel_content, "\n", ""), "\r", ""), "\t", "")
    )) > 0
    if "story_core" in requested:
        sections["story_core"] = {
            "title": story.title or "",
            "description": story.description or "",
            "tags": story.tags or {},
        }
    if "story_bible" in requested:
        sections["story_bible"] = build_story_bible_compact(story.story_bible)
    if "characters" in requested:
        sections["characters"] = _character_digest(story.characters)
    if "book_outline" in requested:
        outline = story.outline if isinstance(story.outline, dict) else {}
        sections["book_outline"] = {
            "summary": outline.get("summary"),
            "three_acts": [
                {key: act.get(key) for key in ("act", "title", "summary") if act.get(key) not in (None, "")}
                for act in outline.get("three_acts", [])
                if isinstance(act, dict)
            ],
            "chapter_count": len(_outline_chapters(outline)),
        }
    if "chapter_plan" in requested:
        sections["chapter_plan"] = _chapter_plan(story.outline, chapter_number, current_only=profile == "chapter_writer")
    if "story_memory" in requested:
        sections["story_memory"] = build_story_memory_compact(story.story_memory)
    if "style_profile" in requested:
        bible = story.story_bible if isinstance(story.story_bible, dict) else {}
        compact_bible = build_story_bible_compact(bible)
        reference_fields = {
            key: compact_bible[key]
            for key in (
                "learned_techniques",
                "reference_plots",
                "reference_rhythm",
                "reference_emotion_modules",
                "reference_author_profile",
                "reference_author_report",
                "reference_style_samples",
                "referenced_deconstruction_works",
            )
            if key in compact_bible
        }
        writing_guidance = bible.get("writing_guidance", {})
        if profile == "chapter_writer" and isinstance(writing_guidance, dict):
            writing_guidance = {
                key: value
                for key, value in writing_guidance.items()
                if str(key).strip() not in _CHAPTER_WRITER_GUIDANCE_EXCLUDED_KEYS
            }
        sections["style_profile"] = {
            "writing_guidance": writing_guidance,
            **reference_fields,
        }
    if "previous_chapter" in requested and chapter_number and chapter_number > 1:
        previous = (
            db.query(Chapter)
            .filter(
                Chapter.story_id == story.id,
                Chapter.chapter_number < chapter_number,
                Chapter.novel_content.isnot(None),
                nonblank_chapter_content,
            )
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        if previous is not None:
            immediate_previous_number = previous.chapter_number
            memory = previous.memory_summary if isinstance(previous.memory_summary, dict) else {}
            chapter_summary = memory.get("chapter_summary") if isinstance(memory.get("chapter_summary"), dict) else {}
            handoff = memory.get("chapter_handoff") if isinstance(memory.get("chapter_handoff"), dict) else {}
            summary = str(chapter_summary.get("summary") or memory.get("summary") or "").strip()
            ending_scene = str(chapter_summary.get("ending_scene") or memory.get("ending_scene") or "").strip()
            ending_excerpt = (previous.novel_content or "")[-1200:].strip()
            sections["previous_chapter"] = {
                key: value
                for key, value in {
                    "chapter_number": previous.chapter_number,
                    "title": previous.title or f"第{previous.chapter_number}章",
                    "summary": summary,
                    "ending_scene": ending_scene,
                    "ending_excerpt": ending_excerpt,
                    "chapter_handoff": handoff,
                }.items()
                if value not in (None, "", [], {})
            }
    if "recent_chapters" in requested:
        query = db.query(Chapter).filter(
            Chapter.story_id == story.id,
            Chapter.novel_content.isnot(None),
            nonblank_chapter_content,
        )
        if chapter_number:
            query = query.filter(Chapter.chapter_number < chapter_number)
        chapters = query.order_by(Chapter.chapter_number.desc()).limit(4).all()
        if immediate_previous_number is not None and len(chapters) > 1:
            chapters = [item for item in chapters if item.chapter_number != immediate_previous_number][:3]
        else:
            chapters = chapters[:3]
        sections["recent_chapters"] = [
            {
                "chapter_number": item.chapter_number,
                "title": item.title or "",
                "memory_summary": item.memory_summary or {},
                "ending_excerpt": (item.novel_content or "")[-800:],
            }
            for item in reversed(chapters)
        ]
    return sections


def resolve_story_context(
    db: Session,
    *,
    story: Story,
    task_type: str,
    chapter_number: int | None = None,
    owner_user_id: int | None = None,
    run_id: str | None = None,
    token_budget: int = 6000,
    retrieval_hints: Any = None,
) -> dict[str, Any]:
    sync_story_knowledge_from_legacy(db, story=story)
    profile = normalize_context_profile(task_type)
    requested = set(CONTEXT_PROFILES[profile])
    sections = _legacy_sections(db, story, requested, chapter_number, profile)
    resource_keys: list[str] = []
    focus_text, focus_terms = _retrieval_terms(retrieval_hints)
    if "user_instruction" in requested and isinstance(retrieval_hints, dict):
        visible_instruction = str(retrieval_hints.get("user_instruction") or "").strip()
        if visible_instruction:
            sections["user_instruction"] = {"content": visible_instruction}
    scored_entities: list[tuple[int, int, StoryKnowledgeEntity]] = []
    entity_candidates_by_key: dict[str, StoryKnowledgeEntity] = {}
    direct_entity_keys: set[str] = set()
    fact_entity_evidence: set[str] = set()
    thread_entity_evidence: set[str] = set()
    chapter_numbers = _chapter_number_by_id(db, story.id) if chapter_number is not None else {}

    resource_query = db.query(StoryKnowledgeResource).filter(
            StoryKnowledgeResource.story_id == story.id,
            StoryKnowledgeResource.status == "active",
            or_(
                StoryKnowledgeResource.resource_type.in_(requested),
                StoryKnowledgeResource.source_type == "manual",
            ),
        )
    if chapter_number is not None:
        resource_query = resource_query.filter(
            or_(StoryKnowledgeResource.valid_from_chapter.is_(None), StoryKnowledgeResource.valid_from_chapter <= chapter_number),
            or_(StoryKnowledgeResource.valid_to_chapter.is_(None), StoryKnowledgeResource.valid_to_chapter >= chapter_number),
        )
    resources: list[StoryKnowledgeResource] = []
    _append_unique_rows(
        resources,
        resource_query.order_by(
            StoryKnowledgeResource.importance.desc(),
            StoryKnowledgeResource.updated_at.desc(),
        ).limit(60).all(),
    )
    semantic_terms = _semantic_lookup_terms(focus_terms)
    if semantic_terms:
        resource_filters = []
        for term in semantic_terms:
            pattern = f"%{term}%"
            resource_filters.extend((
                StoryKnowledgeResource.title.ilike(pattern),
                StoryKnowledgeResource.summary.ilike(pattern),
                StoryKnowledgeResource.content_text.ilike(pattern),
            ))
        _append_unique_rows(
            resources,
            resource_query.filter(or_(*resource_filters)).order_by(
                StoryKnowledgeResource.importance.desc(),
                StoryKnowledgeResource.updated_at.desc(),
            ).limit(100).all(),
        )
    for resource in resources:
        section_key = resource.resource_type if resource.resource_type in requested else "resources"
        sections.setdefault(section_key, [])
        if not isinstance(sections[section_key], list):
            sections[f"database_{section_key}"] = sections.pop(section_key)
            sections[section_key] = []
        sections[section_key].append(_resource_payload(resource))
        sections[section_key][-1]["_receipt_key"] = f"resource:{resource.id}:{resource.version}"

    if "entities" in requested:
        entity_base = db.query(StoryKnowledgeEntity).filter(
            StoryKnowledgeEntity.story_id == story.id,
            StoryKnowledgeEntity.status == "active",
        )
        entity_candidates: list[StoryKnowledgeEntity] = []
        _append_unique_rows(
            entity_candidates,
            entity_base.order_by(StoryKnowledgeEntity.importance.desc(), StoryKnowledgeEntity.id).limit(120).all(),
        )
        _append_unique_rows(
            entity_candidates,
            entity_base.order_by(StoryKnowledgeEntity.id.desc()).limit(120).all(),
        )
        if chapter_number is not None:
            _append_unique_rows(
                entity_candidates,
                entity_base.filter(
                    or_(StoryKnowledgeEntity.first_chapter.is_(None), StoryKnowledgeEntity.first_chapter <= chapter_number),
                    or_(StoryKnowledgeEntity.last_chapter.is_(None), StoryKnowledgeEntity.last_chapter >= chapter_number),
                ).order_by(StoryKnowledgeEntity.importance.desc(), StoryKnowledgeEntity.id).limit(160).all(),
            )
        semantic_terms = _semantic_lookup_terms(focus_terms)
        if semantic_terms:
            entity_filters = []
            for term in semantic_terms:
                pattern = f"%{term}%"
                entity_filters.append(StoryKnowledgeEntity.canonical_name.ilike(pattern))
            _append_unique_rows(
                entity_candidates,
                entity_base.filter(or_(*entity_filters)).order_by(StoryKnowledgeEntity.importance.desc(), StoryKnowledgeEntity.id).limit(200).all(),
            )
        for item in entity_candidates:
            effective_start = _entity_start_chapter(item, chapter_numbers)
            if profile == "chapter_writer" and chapter_number is not None:
                if effective_start is not None and effective_start > chapter_number:
                    continue
                if item.last_chapter is not None and item.last_chapter < chapter_number:
                    continue
                if (
                    effective_start is None
                    and item.source_type in {"agent", "story_memory"}
                ):
                    continue
            if item.entity_key:
                entity_candidates_by_key[item.entity_key] = item
            score = int(item.importance or 0)
            has_direct_evidence, semantic_score = _entity_has_direct_chapter_evidence(item, focus_text, focus_terms)
            score += semantic_score
            item_profile = item.profile_json if isinstance(item.profile_json, dict) else {}
            if str(item_profile.get("role") or "").strip().casefold() in {"主角", "protagonist"}:
                has_direct_evidence = True
            if chapter_number is not None:
                if item.first_chapter is not None and item.first_chapter <= chapter_number:
                    score += 8
                if item.first_chapter == chapter_number:
                    has_direct_evidence = True
                if item.last_chapter is None or item.last_chapter >= chapter_number:
                    score += 8
                if (
                    item.first_chapter is not None
                    and item.last_chapter is not None
                    and item.first_chapter <= chapter_number <= item.last_chapter
                ):
                    has_direct_evidence = True
            if has_direct_evidence and item.entity_key:
                direct_entity_keys.add(item.entity_key)
            scored_entities.append((score, item.id, item))
        scored_entities.sort(key=lambda row: (-row[0], row[1]))
        selected_entity_keys = set(direct_entity_keys) if focus_text else {
            item.entity_key for _, _, item in scored_entities[:20] if item.entity_key
        }
    else:
        selected_entity_keys = set()

    if "facts" in requested:
        fact_query = db.query(StoryKnowledgeFact).filter(
            StoryKnowledgeFact.story_id == story.id,
            StoryKnowledgeFact.status == "active",
        )
        if chapter_number is not None:
            fact_query = fact_query.filter(
                or_(StoryKnowledgeFact.valid_from_chapter.is_(None), StoryKnowledgeFact.valid_from_chapter <= chapter_number),
                or_(StoryKnowledgeFact.valid_to_chapter.is_(None), StoryKnowledgeFact.valid_to_chapter >= chapter_number),
            )
        fact_candidates: list[StoryKnowledgeFact] = []
        _append_unique_rows(
            fact_candidates,
            fact_query.order_by(StoryKnowledgeFact.id.desc()).limit(240).all(),
        )
        _append_unique_rows(
            fact_candidates,
            fact_query.order_by(StoryKnowledgeFact.confidence.desc(), StoryKnowledgeFact.id.desc()).limit(240).all(),
        )
        if selected_entity_keys:
            _append_unique_rows(
                fact_candidates,
                fact_query.filter(
                    or_(
                        StoryKnowledgeFact.subject_key.in_(selected_entity_keys),
                        StoryKnowledgeFact.object_key.in_(selected_entity_keys),
                    )
                ).order_by(StoryKnowledgeFact.id.desc()).limit(300).all(),
            )
        semantic_terms = _semantic_lookup_terms(focus_terms)
        if semantic_terms:
            fact_filters = []
            for term in semantic_terms:
                pattern = f"%{term}%"
                fact_filters.append(StoryKnowledgeFact.value_text.ilike(pattern))
            _append_unique_rows(
                fact_candidates,
                fact_query.filter(or_(*fact_filters)).order_by(StoryKnowledgeFact.id.desc()).limit(300).all(),
            )
        scored_facts = []
        for item in fact_candidates:
            effective_start = _fact_start_chapter(item, chapter_numbers)
            if profile == "chapter_writer" and chapter_number is not None:
                if effective_start is not None and effective_start > chapter_number:
                    continue
                if (
                    effective_start is None
                    and item.source_type in {"agent", "story_memory"}
                ):
                    continue
            semantic_score = _text_relevance(
                focus_text,
                focus_terms,
                item.subject_key,
                item.predicate,
                item.object_key,
                item.value_json,
                item.value_text,
            )
            score = semantic_score
            if item.subject_key in selected_entity_keys:
                score += 60
            if item.object_key in selected_entity_keys:
                score += 45
            score += int(float(item.confidence or 0) * 20)
            score += _source_authority(item.source_type)
            if chapter_number is not None and item.valid_from_chapter is not None:
                score += max(0, 12 - min(12, abs(chapter_number - item.valid_from_chapter)))
            scored_facts.append((score, item.id, semantic_score, effective_start, item))
        scored_facts.sort(key=lambda row: (-row[0], row[1]))
        if focus_text:
            scored_facts = [
                row for row in scored_facts
                if row[2] > 0
                or (
                    row[4].source_type == "manual"
                    and row[4].subject_key in selected_entity_keys
                    and row[4].object_key in selected_entity_keys
                )
            ]
        if profile == "chapter_writer":
            latest_state_facts: dict[tuple[str, str, str], tuple[int, int, int, int | None, StoryKnowledgeFact]] = {}
            independent_facts: list[tuple[int, int, int, int | None, StoryKnowledgeFact]] = []
            for row in scored_facts:
                item = row[4]
                if item.object_key:
                    independent_facts.append(row)
                    continue
                state_key = (item.subject_key, item.predicate, "")
                existing = latest_state_facts.get(state_key)
                row_order = (row[3] or 0, item.version or 1, item.id)
                existing_order = (
                    existing[3] or 0,
                    existing[4].version or 1,
                    existing[4].id,
                ) if existing else None
                if existing is None or row_order > existing_order:
                    latest_state_facts[state_key] = row
            scored_facts = independent_facts + list(latest_state_facts.values())
            scored_facts.sort(key=lambda row: (-row[0], row[1]))
        selected_facts = scored_facts[:40]
        for _, _, semantic_score, effective_start, item in selected_facts:
            starts_now = chapter_number is not None and effective_start == chapter_number
            if semantic_score > 0 or starts_now:
                if item.subject_key in entity_candidates_by_key:
                    fact_entity_evidence.add(item.subject_key)
                if item.object_key in entity_candidates_by_key:
                    fact_entity_evidence.add(item.object_key)
        sections["facts"] = [
            {
                "subject": item.subject_key,
                "subject_name": _entity_display_name(item.subject_key, entity_candidates_by_key),
                "predicate": item.predicate,
                "object": item.object_key,
                "object_name": _entity_display_name(item.object_key, entity_candidates_by_key),
                "value": _replace_entity_references(
                    item.value_json if item.value_json is not None else item.value_text,
                    entity_candidates_by_key,
                ),
                "valid_from": effective_start,
                "valid_to": item.valid_to_chapter,
                "source_chapter_id": item.source_chapter_id,
                "relevance_score": score,
                "_receipt_key": f"fact:{item.id}",
            }
            for score, _, _, effective_start, item in selected_facts
        ]

    if "open_threads" in requested:
        thread_query = db.query(StoryPlotThread).filter(
            StoryPlotThread.story_id == story.id,
            StoryPlotThread.status.in_(("open", "active", "due")),
        )
        thread_candidates: list[StoryPlotThread] = []
        _append_unique_rows(
            thread_candidates,
            thread_query.order_by(StoryPlotThread.priority.desc(), StoryPlotThread.id).limit(160).all(),
        )
        _append_unique_rows(
            thread_candidates,
            thread_query.order_by(StoryPlotThread.id.desc()).limit(160).all(),
        )
        if chapter_number is not None:
            _append_unique_rows(
                thread_candidates,
                thread_query.filter(
                    or_(
                        StoryPlotThread.expected_payoff_to < chapter_number,
                        StoryPlotThread.expected_payoff_from <= chapter_number,
                        StoryPlotThread.expected_payoff_from <= chapter_number + 10,
                    )
                ).order_by(StoryPlotThread.expected_payoff_from, StoryPlotThread.id).limit(360).all(),
            )
        semantic_terms = _semantic_lookup_terms(focus_terms)
        if semantic_terms:
            thread_filters = []
            for term in semantic_terms:
                pattern = f"%{term}%"
                thread_filters.extend((
                    StoryPlotThread.title.ilike(pattern),
                    StoryPlotThread.description.ilike(pattern),
                ))
            _append_unique_rows(
                thread_candidates,
                thread_query.filter(or_(*thread_filters)).order_by(StoryPlotThread.priority.desc(), StoryPlotThread.id).limit(260).all(),
            )
        scored_threads = []
        for item in thread_candidates:
            effective_setup = _thread_setup_chapter(item, chapter_numbers)
            if profile == "chapter_writer" and chapter_number is not None:
                if effective_setup is not None and effective_setup > chapter_number:
                    continue
                if (
                    effective_setup is None
                    and item.source_type in {"agent", "story_memory"}
                ):
                    continue
            score = int(item.priority or 0)
            semantic_score = _text_relevance(
                focus_text,
                focus_terms,
                item.thread_key,
                item.title,
                item.description,
                item.related_entity_keys,
            )
            score += semantic_score
            related_keys = set(item.related_entity_keys or [])
            score += min(80, len(related_keys & selected_entity_keys) * 40)
            urgency = "background"
            if chapter_number is not None:
                payoff_from = item.expected_payoff_from
                payoff_to = item.expected_payoff_to
                if payoff_to is not None and chapter_number > payoff_to:
                    score += 120
                    urgency = "overdue"
                elif payoff_from is not None and chapter_number >= payoff_from and (payoff_to is None or chapter_number <= payoff_to):
                    score += 100
                    urgency = "due"
                elif payoff_from is not None:
                    distance = payoff_from - chapter_number
                    if 0 < distance <= 10:
                        score += 60 - distance * 4
                        urgency = "approaching"
            scored_threads.append((score, item.id, urgency, semantic_score, effective_setup, item))
        scored_threads.sort(key=lambda row: (-row[0], row[1]))
        if focus_text:
            scored_threads = [
                row for row in scored_threads
                if row[3] >= 80 or row[2] in {"due", "overdue", "approaching"}
            ]
        if profile == "chapter_writer":
            deduplicated_threads = []
            seen_thread_keys: set[str] = set()
            for row in scored_threads:
                semantic_key = _thread_semantic_key(row[5].title)
                if not semantic_key or semantic_key in seen_thread_keys:
                    continue
                seen_thread_keys.add(semantic_key)
                deduplicated_threads.append(row)
            scored_threads = deduplicated_threads
        thread_limit = 12 if profile == "chapter_writer" else 30
        if profile == "chapter_writer":
            selected_threads = []
            seen_thread_ids: set[int] = set()
            for row in scored_threads:
                if row[2] not in {"due", "overdue", "approaching"}:
                    continue
                selected_threads.append(row)
                seen_thread_ids.add(row[1])
                if len(selected_threads) >= thread_limit:
                    break
            if len(selected_threads) < thread_limit:
                for row in scored_threads:
                    if row[1] in seen_thread_ids:
                        continue
                    selected_threads.append(row)
                    seen_thread_ids.add(row[1])
                    if len(selected_threads) >= thread_limit:
                        break
        else:
            selected_threads = scored_threads[:thread_limit]
        for _, _, urgency, semantic_score, _, item in selected_threads:
            if semantic_score > 0 or urgency in {"due", "overdue"}:
                thread_entity_evidence.update(
                    key for key in (item.related_entity_keys or []) if key in entity_candidates_by_key
                )
        sections["open_threads"] = [
            {
                "key": item.thread_key,
                "type": item.thread_type,
                "title": item.title,
                "description": item.description,
                "setup_chapter": item.setup_chapter,
                "payoff_window": [item.expected_payoff_from, item.expected_payoff_to],
                "expected_payoff_from": item.expected_payoff_from,
                "expected_payoff_to": item.expected_payoff_to,
                "priority": item.priority,
                "related_entities": item.related_entity_keys or [],
                "related_entity_names": [
                    name
                    for key in (item.related_entity_keys or [])
                    if (name := _entity_display_name(key, entity_candidates_by_key))
                ],
                "urgency": urgency,
                "relevance_score": score,
                "_receipt_key": f"thread:{item.id}:{item.version}",
            }
            for score, _, urgency, _, _, item in selected_threads
        ]

    if "entities" in requested:
        evidence_keys = direct_entity_keys | fact_entity_evidence | thread_entity_evidence
        if not focus_text:
            evidence_keys = selected_entity_keys
        selected_scored_entities = [
            row for row in scored_entities if row[2].entity_key in evidence_keys
        ][:20]
        selected_entity_names = {
            str(item.canonical_name or "").strip()
            for _, _, item in selected_scored_entities
            if str(item.canonical_name or "").strip()
        }
        sections["entities"] = [
            {
                "key": item.entity_key,
                "type": item.entity_type,
                "name": item.canonical_name,
                "aliases": item.aliases_json or [],
                "profile": _chapter_entity_profile(item.profile_json, selected_entity_names) if profile == "chapter_writer" else (item.profile_json or {}),
                "relevance_score": score,
                "_receipt_key": f"entity:{item.id}",
            }
            for score, _, item in selected_scored_entities
        ]
        selected_entity_keys = {item.entity_key for _, _, item in selected_scored_entities if item.entity_key}

    max_chars = max(2000, min(int(token_budget or 6000), 24000) * 3)
    omitted: list[str] = []
    minimum_items = {"recent_chapters": 1, "entities": 5, "facts": 8, "open_threads": 8}
    while len(json.dumps(sections, ensure_ascii=False, default=str)) > max_chars and sections:
        optional_key = next((
            key for key in ("recent_chapters", "entities", "facts", "open_threads")
            if isinstance(sections.get(key), list) and len(sections[key]) > minimum_items[key]
        ), None)
        if optional_key is None:
            previous = sections.get("previous_chapter")
            ending_excerpt = previous.get("ending_excerpt") if isinstance(previous, dict) else None
            if isinstance(ending_excerpt, str) and len(ending_excerpt) > 320:
                current_size = len(json.dumps(sections, ensure_ascii=False, default=str))
                keep = max(320, len(ending_excerpt) - max(1, current_size - max_chars) - 64)
                if keep >= len(ending_excerpt):
                    keep = max(320, len(ending_excerpt) // 2)
                previous["ending_excerpt"] = ending_excerpt[-keep:]
                if "previous_chapter:ending_excerpt_trimmed" not in omitted:
                    omitted.append("previous_chapter:ending_excerpt_trimmed")
                continue
            break
        value = sections.get(optional_key)
        keep = max(minimum_items[optional_key], len(value) // 2)
        sections[optional_key] = value[-keep:] if optional_key == "recent_chapters" else value[:keep]
        omitted.append(f"{optional_key}:trimmed")

    def collect_receipt_keys(value: Any) -> None:
        if isinstance(value, dict):
            receipt_key = value.pop("_receipt_key", None)
            if receipt_key:
                resource_keys.append(str(receipt_key))
            for nested in value.values():
                collect_receipt_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_receipt_keys(nested)

    collect_receipt_keys(sections)

    revision = int(getattr(story, "knowledge_revision", 1) or 1)
    context_json = json.dumps(sections, ensure_ascii=False, sort_keys=True, default=str)
    context_hash = hashlib.sha256(context_json.encode("utf-8")).hexdigest()
    receipt_id = uuid.uuid4().hex
    db.add(AgentContextReceipt(
        receipt_id=receipt_id,
        story_id=story.id,
        owner_user_id=owner_user_id,
        run_id=run_id,
        task_type=profile,
        chapter_number=chapter_number,
        knowledge_revision=revision,
        resource_keys_json=resource_keys,
        context_hash=context_hash,
    ))
    db.commit()
    return {
        "receipt_id": receipt_id,
        "context_hash": context_hash,
        "knowledge_revision": revision,
        "task_type": profile,
        "chapter_number": chapter_number,
        "sections": sections,
        "omitted": omitted,
        "context_chars": len(context_json),
        "retrieval": {
            "query_terms": list(focus_terms),
            "selected_counts": {
                key: len(sections.get(key, []))
                for key in ("entities", "facts", "open_threads", "recent_chapters")
            },
        },
    }


def resolve_chapter_context_pack(
    db: Session,
    *,
    story: Story,
    chapter_info: dict[str, Any],
    user_instruction: str = "",
    owner_user_id: int | None = None,
    run_id: str | None = None,
    token_budget: int = 8000,
) -> dict[str, Any]:
    """解析实际供正文 Writer 使用的章节知识包。"""
    chapter_number = chapter_info.get("chapter_number")
    if not isinstance(chapter_number, int) or chapter_number <= 0:
        raise ValueError("章节创作包缺少有效章节号")
    clean_user_instruction = str(user_instruction or "").strip()
    visible_user_instruction = (
        clean_user_instruction
        if clean_user_instruction and clean_user_instruction not in _INTERNAL_CHAPTER_CONTEXT_INSTRUCTIONS
        else ""
    )
    retrieval_hints = {
        key: chapter_info.get(key)
        for key in ("title", "summary", "goal", "conflict", "hook", "payoff", "highlight", "key_events")
        if chapter_info.get(key) not in (None, "", [], {})
    }
    if visible_user_instruction:
        retrieval_hints["user_instruction"] = visible_user_instruction
    resolved = resolve_story_context(
        db,
        story=story,
        task_type="chapter_writer",
        chapter_number=chapter_number,
        owner_user_id=owner_user_id,
        run_id=run_id,
        token_budget=token_budget,
        retrieval_hints=retrieval_hints,
    )
    return {
        "schema_version": 1,
        "receipt_id": resolved["receipt_id"],
        "story_id": story.id,
        "chapter_number": chapter_number,
        "chapter_title": str(chapter_info.get("title") or "").strip(),
        "knowledge_revision": resolved["knowledge_revision"],
        "context_hash": resolved["context_hash"],
        "sections": resolved["sections"],
        "omitted": resolved["omitted"],
        "context_chars": resolved["context_chars"],
        "retrieval": resolved["retrieval"],
    }


def apply_chapter_context_pack(base_context: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """把结构化章节知识包挂载到旧上下文，保持旧字段兼容。"""
    context = dict(base_context or {})
    sections = pack.get("sections") if isinstance(pack.get("sections"), dict) else {}
    context["chapter_context_pack"] = pack
    context["knowledge_revision"] = pack.get("knowledge_revision")
    context["knowledge_entities"] = sections.get("entities") or []
    context["knowledge_facts"] = sections.get("facts") or []
    context["open_threads"] = sections.get("open_threads") or []
    context["resolved_recent_chapters"] = sections.get("recent_chapters") or []
    if sections.get("chapter_plan"):
        context["chapter_plan"] = sections["chapter_plan"]
    if sections.get("style_profile"):
        context["resolved_style_profile"] = sections["style_profile"]
    return context


def search_story_knowledge(
    db: Session,
    *,
    story_id: int,
    query: str,
    resource_types: list[str] | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {"results": []}
    pattern = f"%{text}%"
    size = max(1, min(int(limit or 12), 30))
    resource_query = db.query(StoryKnowledgeResource).filter(
        StoryKnowledgeResource.story_id == story_id,
        StoryKnowledgeResource.status == "active",
        or_(
            StoryKnowledgeResource.title.ilike(pattern),
            StoryKnowledgeResource.summary.ilike(pattern),
            StoryKnowledgeResource.content_text.ilike(pattern),
        ),
    )
    if resource_types:
        resource_query = resource_query.filter(StoryKnowledgeResource.resource_type.in_(resource_types))
    resources = resource_query.order_by(StoryKnowledgeResource.importance.desc()).limit(size).all()
    entities = (
        db.query(StoryKnowledgeEntity)
        .filter(
            StoryKnowledgeEntity.story_id == story_id,
            StoryKnowledgeEntity.status == "active",
            or_(StoryKnowledgeEntity.canonical_name.ilike(pattern), StoryKnowledgeEntity.entity_key.ilike(pattern)),
        )
        .limit(size)
        .all()
    )
    facts = (
        db.query(StoryKnowledgeFact)
        .filter(
            StoryKnowledgeFact.story_id == story_id,
            StoryKnowledgeFact.status == "active",
            or_(
                StoryKnowledgeFact.subject_key.ilike(pattern),
                StoryKnowledgeFact.predicate.ilike(pattern),
                StoryKnowledgeFact.value_text.ilike(pattern),
            ),
        )
        .limit(size)
        .all()
    )
    threads = (
        db.query(StoryPlotThread)
        .filter(
            StoryPlotThread.story_id == story_id,
            or_(
                StoryPlotThread.title.ilike(pattern),
                StoryPlotThread.description.ilike(pattern),
                StoryPlotThread.thread_key.ilike(pattern),
            ),
        )
        .order_by(StoryPlotThread.priority.desc())
        .limit(size)
        .all()
    )
    results = [
        {"kind": "resource", **_resource_payload(item)} for item in resources
    ] + [
        {"kind": "entity", "key": item.entity_key, "type": item.entity_type, "name": item.canonical_name, "profile": item.profile_json or {}}
        for item in entities
    ] + [
        {"kind": "fact", "subject": item.subject_key, "predicate": item.predicate, "object": item.object_key, "value": item.value_json if item.value_json is not None else item.value_text}
        for item in facts
    ] + [
        {"kind": "plot_thread", "key": item.thread_key, "type": item.thread_type, "title": item.title, "description": item.description, "status": item.status}
        for item in threads
    ]
    return {"query": text, "results": results[:size]}
