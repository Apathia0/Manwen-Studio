"""验证 Agent API 输入约束、pending 版本迁移与撤回安全边界。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

import database
import main  # noqa: F401 - 确保 Agent 路由绑定主模块依赖
from models import AgentConversation
from routers import agent_router
from schemas import AgentChatIn, AgentConversationCreateIn


@pytest.mark.parametrize("mode", ["invalid", "EXECUTE", "", None, 1])
def test_agent_chat_rejects_invalid_mode(mode):
    with pytest.raises(ValidationError):
        AgentChatIn(conversation_id=1, message="测试", mode=mode)


@pytest.mark.parametrize("workflow_type", ["comic", "VIDEO", "", 1])
def test_agent_chat_rejects_invalid_workflow_type(workflow_type):
    with pytest.raises(ValidationError):
        AgentChatIn(conversation_id=1, message="测试", workflow_type=workflow_type)


def test_agent_chat_rejects_unknown_enabled_skill():
    with pytest.raises(ValidationError):
        AgentChatIn(
            conversation_id=1,
            message="测试",
            enabled_skills=["chapter_writer", "unknown_skill"],
        )


def test_agent_chat_defaults_to_read_only_analyze_mode():
    body = AgentChatIn(conversation_id=1, message="请分析当前内容")

    assert body.mode == "analyze"


def test_agent_workflow_context_requires_necessary_ids():
    with pytest.raises(ValidationError, match="workflow_id"):
        AgentChatIn(conversation_id=1, message="测试", workflow_type="video")
    with pytest.raises(ValidationError, match="chapter_id"):
        AgentChatIn(conversation_id=1, message="测试", workflow_type="manga")
    with pytest.raises(ValidationError, match="workflow_id"):
        AgentConversationCreateIn(workflow_type="video")
    with pytest.raises(ValidationError, match="chapter_id"):
        AgentChatIn(
            conversation_id=1,
            message="测试",
            workflow_type="video",
            workflow_id=3,
        )


def test_pending_run_migration_adds_version_and_lease_columns():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE agent_conversations ("
            "id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL, story_id INTEGER NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE agent_pending_changes ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, story_id INTEGER NOT NULL, "
            "conversation_id INTEGER NOT NULL, change_type VARCHAR(40) NOT NULL, "
            "record_id INTEGER NOT NULL, display_name VARCHAR(255) NOT NULL DEFAULT '', "
            "field VARCHAR(120) NOT NULL, old_value JSON, new_value JSON)"
        ))

    database._migrate_agent_pending_changes(engine)

    inspector = inspect(engine)
    conversation_columns = {item["name"] for item in inspector.get_columns("agent_conversations")}
    pending_columns = {item["name"] for item in inspector.get_columns("agent_pending_changes")}
    assert {"active_run_id", "active_run_started_at"}.issubset(conversation_columns)
    assert "run_id" in pending_columns


def test_pending_target_rechecks_video_workflow_story_ownership():
    shot = SimpleNamespace(id=12, workflow_id=7)
    foreign_workflow = SimpleNamespace(id=7, story_id=999)

    class FakeDb:
        def get(self, model, record_id, **_kwargs):
            if model is agent_router.ChapterVideoWorkflow:
                return foreign_workflow
            return shot

    assert agent_router._load_owned_pending_target(FakeDb(), "video_shot", 12, 1) is None


def test_created_chapter_with_downstream_data_cannot_be_deleted():
    chapter = SimpleNamespace(
        id=5,
        story_id=1,
        chapter_number=2,
        title="第二章",
        status="pending",
        novel_content=None,
        screenplay_text=None,
        content_source=None,
        key_events=None,
        quality_score=None,
        memory_summary=None,
        manga_asset_analysis_json=None,
        word_count=None,
        messages=[],
        images=[SimpleNamespace(id=8)],
        script_scenes=[],
    )

    class EmptyQuery:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    db = SimpleNamespace(query=lambda _model: EmptyQuery())
    snapshot = {
        "story_id": 1,
        "chapter_number": 2,
        "title": "第二章",
        "status": "pending",
        "novel_content": None,
    }

    error = agent_router._created_chapter_conflict(db, chapter, snapshot)

    assert error is not None
    assert "已有聊天、漫画或分镜数据" in error


def test_claim_agent_run_rejects_an_active_conversation(monkeypatch):
    class FakeQuery:
        def filter(self, *_args):
            return self

        def update(self, *_args, **_kwargs):
            return 0

    class FakeDb:
        def query(self, model):
            assert model is AgentConversation
            return FakeQuery()

        def rollback(self):
            return None

    conversation = SimpleNamespace(id=3, owner_user_id=2, story_id=1)
    monkeypatch.setattr(agent_router.uuid, "uuid4", lambda: SimpleNamespace(hex="run-1"))

    with pytest.raises(agent_router.HTTPException) as exc_info:
        agent_router._claim_agent_run(FakeDb(), conversation)

    assert exc_info.value.status_code == 409


def test_running_conversation_rejects_destructive_actions():
    conversation = SimpleNamespace(
        active_run_id="run-1",
        active_run_started_at=agent_router.datetime.datetime.utcnow(),
    )

    with pytest.raises(agent_router.HTTPException) as exc_info:
        agent_router._require_conversation_idle(conversation)

    assert exc_info.value.status_code == 409


def test_created_chapter_act_change_blocks_deletion():
    chapter = SimpleNamespace(
        story_id=1,
        chapter_number=2,
        title="第二章",
        status="pending",
        novel_content=None,
        act="第二幕",
        video_style_preset_id=None,
    )
    snapshot = {
        "story_id": 1,
        "chapter_number": 2,
        "title": "第二章",
        "status": "pending",
        "novel_content": None,
        "act": None,
        "video_style_preset_id": None,
    }

    assert agent_router._created_chapter_conflict(SimpleNamespace(), chapter, snapshot) is not None
