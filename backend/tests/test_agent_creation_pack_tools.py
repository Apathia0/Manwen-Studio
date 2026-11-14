"""Agent 助手读写章节创作包 + 用户指令注入创作包 hard_requirements。"""

import asyncio
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import Chapter, Story
from services import agent_service


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _story(db, *, with_pack: bool = True) -> Story:
    story = Story(
        title="测试长篇",
        description="描述",
        tags={"type": "玄幻"},
        characters=[{"name": "陈玄", "role": "主角"}],
        story_bible={},
        story_memory={},
        outline={"summary": "大纲", "three_acts": []},
    )
    db.add(story)
    db.flush()
    db.add(Chapter(
        story_id=story.id,
        chapter_number=1,
        title="残卷",
        novel_content="陈玄收起残卷。" * 100,
        memory_summary={"summary": "测试"},
        creation_pack_content=(
            "# 第1章创作包\n\n"
            "> 正文 Agent 实际接收的完整创作包。\n\n"
            "## 核心冲突\n- 陈玄必须取得残卷。\n\n"
            "## 硬性要求\n- 不写后续章节内容。"
        ) if with_pack else None,
        creation_pack_version=1,
        creation_pack_is_manual=False,
        creation_pack_source_hash="hash-abc" if with_pack else None,
    ))
    db.commit()
    return story


def _chapter(db, story_id: int) -> Chapter:
    return db.query(Chapter).filter_by(story_id=story_id).one()


def _context(**overrides):
    values = {
        "story_id": 1,
        "api_key": None,
        "pending_changes": agent_service.PendingChangesTracker(),
        "workflow_type": None,
        "workflow_id": None,
        "chapter_id": None,
        "enabled_skills": None,
        "run_id": "run-test",
    }
    values.update(overrides)
    return agent_service.AgentRunContext(**values)


def _set_context(monkeypatch, db, *, story_id: int = 1) -> None:
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    # 工具 finally 会 close 自己的 SessionLocal；真实环境返回独立 session，测试共用同一 session 需屏蔽 close
    monkeypatch.setattr(db, "close", lambda: None)
    # 写入前记录（new_value=None）不触发持久化；update_new_value 会触发，测试中静默
    monkeypatch.setattr(agent_service, "_persist_tracker_write_ahead", lambda tracker: None)
    token = agent_service._AGENT_RUN_CONTEXT.set(_context(story_id=story_id))
    return token


# ── 读工具 get_chapter_creation_pack ──────────────────────────


def test_get_chapter_creation_pack_returns_content_version_and_manual_flag(monkeypatch):
    db = _session()
    story = _story(db)
    token = _set_context(monkeypatch, db, story_id=story.id)
    try:
        result = asyncio.run(agent_service.get_chapter_creation_pack(_chapter(db, story.id).id))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert "第1章创作包" in result["creation_pack_content"]
    assert result["creation_pack_version"] == 1
    assert result["is_manual"] is False
    assert result["source_hash"] == "hash-abc"
    assert result["has_creation_pack"] is True


def test_get_chapter_creation_pack_empty_when_no_pack(monkeypatch):
    db = _session()
    story = _story(db, with_pack=False)
    token = _set_context(monkeypatch, db, story_id=story.id)
    try:
        result = asyncio.run(agent_service.get_chapter_creation_pack(_chapter(db, story.id).id))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert result["has_creation_pack"] is False
    assert result["creation_pack_content"] == ""


def test_get_chapter_creation_pack_denies_foreign_chapter(monkeypatch):
    db = _session()
    story = _story(db)
    token = _set_context(monkeypatch, db, story_id=999)  # 上下文故事与章节归属不符
    try:
        result = asyncio.run(agent_service.get_chapter_creation_pack(_chapter(db, story.id).id))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["error"]


# ── 写工具 update_chapter_creation_pack ───────────────────────


def test_update_chapter_creation_pack_sets_manual_and_increments_version(monkeypatch):
    db = _session()
    story = _story(db)
    chapter = _chapter(db, story.id)
    token = _set_context(monkeypatch, db, story_id=story.id)
    try:
        result = asyncio.run(agent_service.update_chapter_creation_pack(
            chapter.id,
            "全新创作包内容：陈玄发现残卷是钥匙。",
        ))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert result["creation_pack_version"] == 2
    assert result["is_manual"] is True
    db.refresh(chapter)
    assert chapter.creation_pack_content == "全新创作包内容：陈玄发现残卷是钥匙。"
    assert chapter.creation_pack_is_manual is True
    assert chapter.creation_pack_version == 2


def test_update_chapter_creation_pack_expected_version_mismatch(monkeypatch):
    db = _session()
    story = _story(db)
    chapter = _chapter(db, story.id)
    token = _set_context(monkeypatch, db, story_id=story.id)
    try:
        result = asyncio.run(agent_service.update_chapter_creation_pack(
            chapter.id,
            "会被拒绝的内容",
            expected_version=5,
        ))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["version_conflict"] is True
    assert result["current_version"] == 1
    db.refresh(chapter)
    assert chapter.creation_pack_content.startswith("# 第1章创作包")  # 内容未变
    assert chapter.creation_pack_version == 1


def test_update_chapter_creation_pack_optional_expected_version(monkeypatch):
    db = _session()
    story = _story(db)
    chapter = _chapter(db, story.id)
    token = _set_context(monkeypatch, db, story_id=story.id)
    try:
        result = asyncio.run(agent_service.update_chapter_creation_pack(
            chapter.id,
            "强制保存的内容",
            expected_version=1,
        ))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert result["creation_pack_version"] == 2


def test_update_chapter_creation_pack_tracks_pending_changes(monkeypatch):
    db = _session()
    story = _story(db)
    chapter = _chapter(db, story.id)
    tracker = agent_service.PendingChangesTracker()
    token = _set_context(monkeypatch, db, story_id=story.id)
    try:
        ctx = agent_service._current_run_context()
        # 替换 tracker 为可观察实例
        ctx.pending_changes = tracker
        asyncio.run(agent_service.update_chapter_creation_pack(chapter.id, "新内容"))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    fields = {c.field for c in tracker._changes}
    assert "creation_pack_content" in fields


# ── 凭证门与注册断言 ──────────────────────────────────────────


def test_write_tool_registered_in_mutation_guard():
    assert "update_chapter_creation_pack" in agent_service._STORY_KNOWLEDGE_MUTATION_TOOLS
    assert agent_service._STORY_KNOWLEDGE_CONTEXT_PROFILES["update_chapter_creation_pack"] == ("chapter_writer",)


def test_read_and_write_tools_in_chapter_writer_skill():
    chapter_writer = next(
        skill for skill in agent_service.skill_registry._skills.values()
        if skill.name == "chapter_writer"
    )
    assert "get_chapter_creation_pack" in chapter_writer.tool_names
    assert "update_chapter_creation_pack" in chapter_writer.tool_names


def test_tools_visible_in_novel_workflow_specs():
    names = {
        spec["function"]["name"]
        for spec in agent_service.tool_registry.get_tool_specs(workflow_type="novel", enabled_skills=["chapter_writer"])
    }
    assert "get_chapter_creation_pack" in names
    assert "update_chapter_creation_pack" in names


# ── 用户指令注入创作包 ────────────────────────────────────────


def test_inject_user_instruction_into_pack_adds_section_and_task_field():
    pack = {
        "schema_version": 2,
        "canonical_content": "# 第1章创作包\n\n## 核心冲突\n- 陈玄必须取得残卷。",
        "chapter_task": {"chapter_number": 1},
    }
    injected = agent_service._inject_user_instruction_into_pack(pack, "加重悬疑氛围，章尾留钩子")

    assert "## 用户要求" in injected["canonical_content"]
    assert "加重悬疑氛围，章尾留钩子" in injected["canonical_content"]
    assert injected["chapter_task"]["user_instruction"] == "加重悬疑氛围，章尾留钩子"
    # 原有创作包内容保留
    assert "核心冲突" in injected["canonical_content"]
    assert "陈玄必须取得残卷" in injected["canonical_content"]


def test_inject_user_instruction_into_pack_does_not_mutate_input():
    pack = {
        "schema_version": 2,
        "canonical_content": "# 第1章创作包\n\n## 核心冲突\n- 陈玄必须取得残卷。",
        "chapter_task": {"chapter_number": 1},
    }
    original = copy.deepcopy(pack)
    agent_service._inject_user_instruction_into_pack(pack, "新要求")

    assert pack == original  # 输入对象未被原地修改


def test_inject_user_instruction_into_pack_empty_instruction_returns_unchanged():
    pack = {
        "schema_version": 2,
        "canonical_content": "# 第1章创作包",
        "chapter_task": {},
    }
    result = agent_service._inject_user_instruction_into_pack(pack, "   ")

    assert result == pack
    assert "## 用户要求" not in result["canonical_content"]


def test_inject_user_instruction_into_pack_replaces_previous_section():
    pack = {
        "schema_version": 2,
        "canonical_content": "# 第1章创作包\n\n## 核心冲突\n- A。\n\n## 用户要求\n旧要求",
        "chapter_task": {"user_instruction": "旧要求"},
    }
    result = agent_service._inject_user_instruction_into_pack(pack, "新要求")

    assert result["canonical_content"].count("## 用户要求") == 1
    assert "新要求" in result["canonical_content"]
    assert "旧要求" not in result["canonical_content"]
    assert "核心冲突" in result["canonical_content"]


# ── adjust_chapter_by_instruction 端到端注入 ───────────────────


def test_adjust_chapter_by_instruction_injects_instruction_into_creation_pack(monkeypatch):
    db = _session()
    story = _story(db)
    chapter = _chapter(db, story.id)
    chapter.creation_pack_is_manual = True
    db.commit()

    captured: dict = {}

    async def fake_pipeline(**kwargs):
        captured["creation_pack"] = kwargs.get("creation_pack")
        captured["chapter_info"] = kwargs.get("chapter_info")
        captured["initial_content"] = kwargs.get("initial_content")
        return {"ok": True, "content": "新版正文", "review": {}}

    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)  # 工具 finally 会 close 共享 session，测试中屏蔽
    monkeypatch.setattr(agent_service, "_current_api_key", lambda: "test-key")
    monkeypatch.setattr(
        agent_service,
        "get_effective_prompt",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        agent_service,
        "build_agent_chapter_system_prompt",
        lambda *a, **k: "系统提示",
    )
    monkeypatch.setattr(
        "services.chapter_agents.run_chapter_creation_pipeline",
        fake_pipeline,
    )
    monkeypatch.setattr(agent_service, "_schedule_agent_memory_refresh", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "_persist_tracker_write_ahead", lambda tracker: None)

    token = agent_service._AGENT_RUN_CONTEXT.set(_context(story_id=story.id))
    try:
        result = asyncio.run(agent_service.adjust_chapter_by_instruction(chapter.id, "加重悬疑，章尾留钩子"))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    pack = captured["creation_pack"]
    assert pack is not None
    assert "## 用户要求" in str(pack.get("canonical_content") or "")
    assert "加重悬疑，章尾留钩子" in str(pack.get("canonical_content") or "")
    assert captured["chapter_info"].get("user_instruction") == "加重悬疑，章尾留钩子"
    # 注入发生在内存，不落库：持久化创作包不含「## 用户要求」
    db.refresh(chapter)
    assert "## 用户要求" not in (chapter.creation_pack_content or "")


def test_adjust_chapter_by_instruction_passes_previous_chapter_summary(monkeypatch):
    """Agent 调整正文时必须把上一章衔接摘要传给 pipeline（复用包场景）。"""
    db = _session()
    story = _story(db)
    chapter2 = Chapter(
        story_id=story.id,
        chapter_number=2,
        title="第二章",
        novel_content="第二章正文。" * 100,
        creation_pack_is_manual=True,
        creation_pack_version=1,
    )
    db.add(chapter2)
    db.commit()

    captured: dict = {}

    async def fake_pipeline(**kwargs):
        captured["previous_chapter_summary"] = kwargs.get("previous_chapter_summary")
        return {"ok": True, "content": "新版正文", "review": {}}

    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(agent_service, "_current_api_key", lambda: "test-key")
    monkeypatch.setattr(agent_service, "get_effective_prompt", lambda *a, **k: "")
    monkeypatch.setattr(agent_service, "build_agent_chapter_system_prompt", lambda *a, **k: "系统提示")
    monkeypatch.setattr("services.chapter_agents.run_chapter_creation_pipeline", fake_pipeline)
    monkeypatch.setattr(agent_service, "_schedule_agent_memory_refresh", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "_persist_tracker_write_ahead", lambda tracker: None)

    token = agent_service._AGENT_RUN_CONTEXT.set(_context(story_id=story.id))
    try:
        result = asyncio.run(agent_service.adjust_chapter_by_instruction(chapter2.id, "加重悬疑"))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert captured["previous_chapter_summary"]
    assert "第1章" in captured["previous_chapter_summary"]
