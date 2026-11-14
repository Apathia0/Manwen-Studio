import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import PlatformSetting
from services import agent_model_capabilities as capabilities
from services.agent_service import (
    _agent_upstream_http_error,
    _flatten_completed_tool_exchanges,
    _skill_routing_text,
    infer_agent_skills,
    tool_registry,
)
from services.token_utils import emergency_compact_messages


def test_dynamic_budget_uses_optimistic_unknown_and_learned_window():
    assert capabilities.dynamic_prompt_budget({}, reserved_output_tokens=4096) == 82_304
    learned = {"observed_context_limit": 64_000, "observed_output_limit": 8_192}
    assert capabilities.dynamic_output_limit(learned) == 8_192
    assert capabilities.dynamic_prompt_budget(learned, reserved_output_tokens=8_192) == 49_408


def test_capability_observation_is_persisted_by_endpoint_and_model(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(capabilities, "SessionLocal", session_factory)

    saved = capabilities.persist_model_capability_observation(
        "https://gateway.example/v1",
        "reasoning-model",
        prompt_tokens=23_000,
        completion_tokens=3_000,
        requested_output_tokens=4_096,
        finish_reason="stop",
    )
    learned = capabilities.persist_model_capability_observation(
        "https://gateway.example/v1",
        "reasoning-model",
        context_error="maximum context length is 65536 tokens",
        output_error="maximum 8192 tokens are allowed for output",
    )

    assert saved["largest_successful_prompt"] == 23_000
    assert learned["observed_context_limit"] == 65_536
    assert learned["observed_output_limit"] == 8_192
    db = session_factory()
    try:
        assert db.query(PlatformSetting).count() == 1
    finally:
        db.close()


def test_agent_automatically_routes_planning_tools():
    skills = infer_agent_skills(
        "请续写十章大纲并保存完整任务卡",
        workflow_type=None,
        explicit_skills=None,
    )
    assert skills == ["framework_designer"]
    names = {
        spec["function"]["name"]
        for spec in tool_registry.get_tool_specs(enabled_skills=skills)
    }
    assert "bulk_add_chapter_plans" in names
    assert "resolve_story_context" in names
    assert "update_chapter_content" not in names


def test_agent_followup_execution_inherits_previous_framework_topic():
    messages = [
        {"role": "assistant", "content": "当前三幕结构需要压缩第三卷，并补充第四卷章节规划。"},
        {"role": "user", "content": "根据你的建议执行优化"},
    ]

    skills = infer_agent_skills(
        _skill_routing_text(messages),
        workflow_type="novel",
        explicit_skills=None,
    )

    assert skills == ["framework_designer"]


def test_agent_402_is_reported_as_payment_error():
    error = _agent_upstream_http_error(402)

    assert error is not None
    assert error.code == "agent_upstream_payment_required"
    assert error.retryable is False
    assert "额度不足" in str(error)

    server_error = _agent_upstream_http_error(505)
    assert server_error is not None
    assert server_error.code == "agent_upstream_server_error"
    assert server_error.retryable is True


def test_agent_followup_with_new_topic_does_not_inherit_old_framework_topic():
    messages = [
        {"role": "assistant", "content": "当前三幕大纲需要压缩第三卷。"},
        {"role": "user", "content": "根据下面要求重写正文：强化战斗细节"},
    ]

    skills = infer_agent_skills(
        _skill_routing_text(messages),
        workflow_type="novel",
        explicit_skills=None,
    )

    assert skills == ["chapter_writer"]


def test_completed_tool_history_is_aggregated_without_full_payloads():
    messages = []
    for index in range(9):
        call_id = f"call-{index}"
        messages.extend([
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "bulk_add_chapter_plans",
                        "arguments": json.dumps({
                            "story_id": 12,
                            "chapters": [{"chapter_number": index + 1, "summary": "正文" * 2000}],
                        }, ensure_ascii=False),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": call_id, "content": '{"ok":true,"results":[{"ok":true}]}'},
        ])

    compacted = _flatten_completed_tool_exchanges(messages, "nonce-test")

    assert len(compacted) == 1
    assert "bulk_add_chapter_plans" in compacted[0]["content"]
    assert '"chapters_count":1' in compacted[0]["content"]
    assert "正文正文正文" not in compacted[0]["content"]


def test_emergency_compaction_removes_reasoning_and_large_tool_arguments():
    arguments = json.dumps({"chapters": [{"summary": "长" * 3000}]}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": "规则"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "推理" * 3000,
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "bulk_add_chapter_plans", "arguments": arguments},
            }],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "结果" * 2000},
    ]

    compacted = emergency_compact_messages(messages, tool_max_chars=300)
    assistant = next(message for message in compacted if message.get("role") == "assistant")
    assert "reasoning_content" not in assistant
    compacted_arguments = assistant["tool_calls"][0]["function"]["arguments"]
    assert json.loads(compacted_arguments)["_compacted"] is True
    assert len(compacted_arguments) < 300


def test_bulk_chapter_tool_schema_enforces_small_batches():
    spec = next(
        item for item in tool_registry.get_tool_specs()
        if item["function"]["name"] == "bulk_add_chapter_plans"
    )
    assert spec["function"]["parameters"]["properties"]["chapters"]["maxItems"] == 3
