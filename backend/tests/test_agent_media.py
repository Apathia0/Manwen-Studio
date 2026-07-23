"""Agent 多模态附件服务的回归测试。"""

import base64
import copy
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentAttachment
from services import agent_service as agent_service_module
from services.agent_media import _extract_document_text, _extract_document_text_safely, multimodal_content, resolve_attachments
from services.token_utils import emergency_compact_messages, split_messages_for_compression
from services.token_utils import should_compress_messages


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_multimodal_image_uses_data_url(tmp_path: Path):
    image_path = tmp_path / "image.png"
    image = Image.new("RGB", (2, 2), "red")
    image.save(image_path, format="PNG")
    payload = multimodal_content(
        "请反推提示词",
        [{"media_kind": "image", "path": str(image_path), "content_type": "image/png", "filename": "image.png"}],
    )
    assert payload[1]["type"] == "image_url"
    assert payload[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(payload[1]["image_url"]["url"].split(",", 1)[1]).startswith(b"\xff\xd8")


def test_multimodal_video_preserves_frame_order(tmp_path: Path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    for path, color in ((first, "red"), (second, "blue")):
        image = Image.new("RGB", (2, 2), color)
        image.save(path, format="JPEG")
    payload = multimodal_content(
        "请生成分镜",
        [{
            "media_kind": "video",
            "filename": "clip.mp4",
            "frame_paths": [str(first), str(second)],
        }],
    )
    frame_payloads = [item["image_url"]["url"] for item in payload if item["type"] == "image_url"]
    assert all(base64.b64decode(item.split(",", 1)[1]).startswith(b"\xff\xd8") for item in frame_payloads)


def test_pdf_attachment_extracts_text(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "script.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, text: str):
            self.text = text

        def extract_text(self):
            return self.text

    fake_reader = SimpleNamespace(pages=[FakePage("第一幕"), FakePage("第二幕")])
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _path, **_kwargs: fake_reader))

    assert _extract_document_text(pdf_path, ".pdf") == "第一幕\n第二幕"


def test_pdf_attachment_rejects_excessive_page_count(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "long.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_reader = SimpleNamespace(pages=[SimpleNamespace() for _ in range(101)])
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _path, **_kwargs: fake_reader))

    with pytest.raises(HTTPException) as error:
        _extract_document_text(pdf_path, ".pdf")

    assert error.value.status_code == 400
    assert "100" in error.value.detail


def test_pdf_safe_parser_isolates_invalid_file(tmp_path: Path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not-a-pdf")

    with pytest.raises(HTTPException) as error:
        _extract_document_text_safely(pdf_path, ".pdf")

    assert error.value.status_code == 400


def test_attachment_cannot_cross_user_or_story(db_session, tmp_path: Path):
    path = tmp_path / "owned.png"
    path.write_bytes(b"owned")
    attachment = AgentAttachment(
        id="attachment-1",
        owner_user_id=10,
        story_id=20,
        original_name="owned.png",
        content_type="image/png",
        file_size=5,
        storage_path=str(path),
        metadata_json={"media_kind": "image"},
    )
    db_session.add(attachment)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        resolve_attachments(["attachment-1"], db=db_session, owner_user_id=11, story_id=20, conversation_id=30)
    assert error.value.status_code == 404


class _FakeAgentStreamResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.is_error = False
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAgentContextErrorResponse(_FakeAgentStreamResponse):
    def __init__(self):
        super().__init__([])
        self.is_error = True
        self.status_code = 400

    async def aread(self):
        return b'{"error":{"code":"context_length_exceeded","message":"maximum context length exceeded"}}'

    def raise_for_status(self):
        raise AssertionError("上下文超限响应应在 raise_for_status 前处理")


class _FakeAgentPayloadTooLargeResponse(_FakeAgentContextErrorResponse):
    async def aread(self):
        return b""

    def __init__(self):
        super().__init__()
        self.status_code = 413


class _FakeAgentInputLengthErrorResponse(_FakeAgentContextErrorResponse):
    async def aread(self):
        return b'{"error":{"type":"invalid_request_error","message":"Input length exceeds the model context length"}}'


class _FakeAgentOutputLimitErrorResponse(_FakeAgentContextErrorResponse):
    async def aread(self):
        return b'{"error":{"type":"invalid_request_error","message":"Maximum completion tokens must be between 1 and 2048"}}'


class _FakeAgentUnsupportedMaxTokensResponse(_FakeAgentContextErrorResponse):
    async def aread(self):
        return b'{"error":{"type":"invalid_request_error","message":"Unsupported parameter max_tokens; use max_completion_tokens instead"}}'


def _agent_sse_response(content: str, finish_reason: str, tool_calls: list[dict] | None = None) -> list[str]:
    delta: dict = {}
    if content:
        delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = tool_calls
    data = {"choices": [{"delta": delta, "finish_reason": finish_reason}]}
    return [f"data: {json.dumps(data, ensure_ascii=False)}", "data: [DONE]"]


def _install_agent_stream_client(monkeypatch, responses: list) -> list[dict]:
    payloads: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, *, json, headers):
            payloads.append(copy.deepcopy(json))
            response = responses[len(payloads) - 1]
            return response if isinstance(response, _FakeAgentStreamResponse) else _FakeAgentStreamResponse(response)

    monkeypatch.setattr(agent_service_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent_service_module, "_deepseek_auth_headers", lambda api_key: {"Authorization": "Bearer test"})
    monkeypatch.setattr(agent_service_module._deepseek_service, "runtime_base_url", lambda: "https://example.test/v1")
    monkeypatch.setattr(agent_service_module._deepseek_service, "runtime_model", lambda: "test-model")
    return payloads


def test_emergency_compaction_keeps_latest_request_and_limits_images():
    user_images = [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,user-1"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,user-2"}},
    ]
    context_images = [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,context-1"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,context-2"}},
    ]
    messages = [
        {"role": "system", "content": "规则" * 30000},
        {"role": "user", "content": "早期要求" * 3000},
        {"role": "assistant", "content": "早期回答" * 3000},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请优化当前漫画和视频分镜"},
                *user_images,
                *context_images,
            ],
        },
    ]

    compacted = emergency_compact_messages(messages)

    assert len(str(compacted)) < len(str(messages))
    assert "当前会话历史紧急摘要" in compacted[1]["content"]
    latest_content = compacted[-1]["content"]
    assert any(item.get("text") == "请优化当前漫画和视频分镜" for item in latest_content)
    assert sum(1 for item in latest_content if item.get("type") == "image_url") == 2
    assert [
        item["image_url"]["url"]
        for item in latest_content
        if item.get("type") == "image_url"
    ] == ["data:image/jpeg;base64,user-1", "data:image/jpeg;base64,user-2"]


def test_agent_compression_threshold_includes_exact_128k(monkeypatch):
    monkeypatch.setattr(
        "services.token_utils.estimate_messages_tokens",
        lambda _messages: 128_000,
    )

    assert should_compress_messages([{"role": "user", "content": "测试"}]) is True


@pytest.mark.asyncio
async def test_agent_compacts_short_oversized_history_before_request(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [_agent_sse_response("压缩后完成", "stop")],
    )
    oversized = "旧内容" * 50_000

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[
                {"role": "user", "content": oversized},
                {"role": "assistant", "content": oversized},
                {"role": "user", "content": "请继续处理"},
            ],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 1
    assert len(json.dumps(payloads[0]["messages"], ensure_ascii=False)) < len(oversized) * 2
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "压缩后完成"


@pytest.mark.asyncio
async def test_agent_context_limit_compresses_and_retries_once(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _FakeAgentContextErrorResponse(),
            _agent_sse_response("压缩后成功", "stop"),
        ],
    )
    messages = [
        {"role": "user", "content": "旧要求" * 8000},
        {"role": "assistant", "content": "旧回答" * 8000},
        {"role": "user", "content": "请继续优化当前漫画和视频"},
    ]

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=messages,
            story_context="故事上下文" * 10000,
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 2
    assert len(json.dumps(payloads[1], ensure_ascii=False)) < len(json.dumps(payloads[0], ensure_ascii=False))
    assert "当前会话历史紧急摘要" in json.dumps(payloads[1]["messages"], ensure_ascii=False)
    done = next(event for event in events if event["event"] == "done")
    assert json.loads(done["data"])["content"] == "压缩后成功"


@pytest.mark.asyncio
async def test_agent_empty_413_compresses_and_retries_once(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _FakeAgentPayloadTooLargeResponse(),
            _agent_sse_response("压缩后成功", "stop"),
        ],
    )

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[
                {"role": "user", "content": "旧要求" * 8000},
                {"role": "assistant", "content": "旧回答" * 8000},
                {"role": "user", "content": "请继续处理"},
            ],
            story_context="故事上下文" * 10000,
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 2
    assert len(json.dumps(payloads[1], ensure_ascii=False)) < len(json.dumps(payloads[0], ensure_ascii=False))
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "压缩后成功"


@pytest.mark.asyncio
async def test_agent_context_limit_fails_after_single_retry(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [_FakeAgentContextErrorResponse(), _FakeAgentContextErrorResponse()],
    )

    with pytest.raises(agent_service_module.AgentContextLimitError) as exc_info:
        async for _ in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "继续处理"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        ):
            pass

    assert len(payloads) == 2
    assert exc_info.value.code == "agent_context_limit_exceeded"


@pytest.mark.asyncio
async def test_agent_context_limit_after_read_tool_compresses_and_retries(monkeypatch):
    tool_call = [{
        "index": 0,
        "id": "call-read",
        "function": {"name": "get_story_overview", "arguments": "{}"},
    }]
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("", "tool_calls", tool_calls=tool_call),
            _FakeAgentInputLengthErrorResponse(),
            _agent_sse_response("压缩后完成", "stop"),
        ],
    )
    service = agent_service_module.AgentService()

    async def fake_execute(_name, _args):
        return '{"title":"测试作品"}'

    monkeypatch.setattr(service.tool_registry, "execute", fake_execute)

    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "分析当前故事"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 3
    retry_messages = payloads[2]["messages"]
    assistant_index = next(
        index for index, message in enumerate(retry_messages)
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    assert retry_messages[assistant_index + 1]["role"] == "tool"
    assert retry_messages[assistant_index + 1]["tool_call_id"] == "call-read"
    assert retry_messages[assistant_index]["content"] == ""
    assert json.loads(retry_messages[assistant_index]["tool_calls"][0]["function"]["arguments"]) == {}
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "压缩后完成"


@pytest.mark.asyncio
async def test_agent_context_limit_after_uncertain_write_tool_does_not_retry(monkeypatch):
    tool_call = [{
        "index": 0,
        "id": "call-write",
        "function": {"name": "update_chapter_content", "arguments": "{}"},
    }]
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("", "tool_calls", tool_calls=tool_call),
            _FakeAgentContextErrorResponse(),
        ],
    )
    service = agent_service_module.AgentService()

    async def fake_execute(_name, _args):
        raise RuntimeError("写入结果未知")

    monkeypatch.setattr(service.tool_registry, "execute", fake_execute)
    monkeypatch.setattr(service.tool_registry, "is_write_tool", lambda name: name == "update_chapter_content")

    with pytest.raises(agent_service_module.AgentContextLimitError):
        async for _ in service.run_stream(
            messages=[{"role": "user", "content": "更新章节正文"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="execute",
        ):
            pass

    assert len(payloads) == 2


def test_context_length_error_recognizes_common_input_length_message():
    assert agent_service_module._is_context_length_exceeded_response(
        400,
        '{"error":{"type":"invalid_request_error","message":"Input length exceeds the model context length"}}',
    )


def test_context_length_error_recognizes_generic_token_limit_message():
    assert agent_service_module._is_context_length_exceeded_response(
        400,
        '{"error":{"message":"Request has 200000 tokens, exceeds the 131072 token limit"}}',
    )


@pytest.mark.parametrize(
    "message",
    [
        "Maximum completion tokens must be between 1 and 8192",
        "Invalid max_tokens: maximum 8192 tokens are allowed for output",
        "The output token limit exceeds the model's allowed maximum",
        "Invalid max_tokens: requested output token limit is 9000",
        "Completion token limit must not exceed 8192",
    ],
)
def test_context_length_error_rejects_output_token_parameter_errors(message):
    assert not agent_service_module._is_context_length_exceeded_response(400, message)


def test_safe_upstream_error_details_only_returns_controlled_metadata():
    code, error_type, message_hash, message_chars = agent_service_module._safe_upstream_error_details(
        '{"error":{"code":"invalid_request","type":"payload_error",'
        '"message":"Authorization: Bearer sk-secret-value payload invalid"}}'
    )

    assert code == "invalid_request"
    assert error_type == "payload_error"
    assert len(message_hash) == 16
    assert message_chars > 0
    assert "sk-secret-value" not in "".join((code, error_type, message_hash))


def test_history_compression_keeps_tool_exchange_atomic():
    messages = [
        {"role": "user", "content": f"旧消息 {index}"}
        for index in range(20)
    ] + [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-atomic",
                "type": "function",
                "function": {"name": "get_story_overview", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call-atomic", "content": "{}"},
    ]

    old_messages, recent_messages = split_messages_for_compression(messages, keep_recent=1)

    assert old_messages[-1]["role"] == "user"
    assert recent_messages[0]["role"] == "assistant"
    assert recent_messages[1]["role"] == "tool"


@pytest.mark.asyncio
async def test_agent_normalizes_missing_tool_id_and_invalid_arguments(monkeypatch):
    tool_call = [{
        "index": 0,
        "id": "",
        "function": {"name": "get_story_overview", "arguments": "[invalid"},
    }]
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("", "tool_calls", tool_calls=tool_call),
            _agent_sse_response("已恢复", "stop"),
        ],
    )
    service = agent_service_module.AgentService()

    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "分析故事"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assistant_message = next(
        message for message in payloads[1]["messages"]
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    normalized_call = assistant_message["tool_calls"][0]
    tool_message = next(message for message in payloads[1]["messages"] if message.get("role") == "tool")
    assert normalized_call["id"]
    assert normalized_call["function"]["arguments"] == "{}"
    assert tool_message["tool_call_id"] == normalized_call["id"]
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "已恢复"


@pytest.mark.asyncio
async def test_agent_skips_duplicate_tool_call_id(monkeypatch):
    tool_calls = [
        {
            "index": 0,
            "id": "call-duplicate",
            "function": {"name": "get_story_overview", "arguments": "{}"},
        },
        {
            "index": 1,
            "id": "call-duplicate",
            "function": {"name": "get_story_overview", "arguments": "{}"},
        },
    ]
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("", "tool_calls", tool_calls=tool_calls),
            _agent_sse_response("结果如下", "stop"),
        ],
    )
    service = agent_service_module.AgentService()
    execute_count = 0

    async def fake_execute(_name, _args):
        nonlocal execute_count
        execute_count += 1
        return '{"ok":true}'

    monkeypatch.setattr(service.tool_registry, "execute", fake_execute)

    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "分析故事"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assistant_message = next(
        message for message in payloads[1]["messages"]
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    assert execute_count == 1
    assert len(assistant_message["tool_calls"]) == 1
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "结果如下"


@pytest.mark.asyncio
async def test_agent_skips_repeated_write_tool_id_across_iterations(monkeypatch):
    first_call = [{
        "index": 0,
        "id": "call-write-once",
        "function": {"name": "update_chapter_content", "arguments": '{"chapter_id":1,"content":"正文"}'},
    }]
    reordered_call = [{
        "index": 0,
        "id": "call-write-once",
        "function": {"name": "update_chapter_content", "arguments": '{"content":"正文","chapter_id":1}'},
    }]
    _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("", "tool_calls", tool_calls=first_call),
            _agent_sse_response("", "tool_calls", tool_calls=reordered_call),
            _agent_sse_response("写入完成", "stop"),
        ],
    )
    service = agent_service_module.AgentService()
    execute_count = 0

    async def fake_execute(_name, _args):
        nonlocal execute_count
        execute_count += 1
        return '{"ok":true}'

    monkeypatch.setattr(service.tool_registry, "execute", fake_execute)
    monkeypatch.setattr(service.tool_registry, "is_write_tool", lambda name: name == "update_chapter_content")

    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "更新章节正文"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="execute",
        )
    ]

    assert execute_count == 1
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "写入完成"


@pytest.mark.asyncio
async def test_agent_executes_reused_write_tool_id_when_arguments_change(monkeypatch):
    first_call = [{
        "index": 0,
        "id": "call-reused",
        "function": {"name": "update_chapter_content", "arguments": '{"chapter_id":1}'},
    }]
    second_call = [{
        "index": 0,
        "id": "call-reused",
        "function": {"name": "update_chapter_content", "arguments": '{"chapter_id":2}'},
    }]
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("", "tool_calls", tool_calls=first_call),
            _agent_sse_response("", "tool_calls", tool_calls=second_call),
            _agent_sse_response("写入完成", "stop"),
        ],
    )
    service = agent_service_module.AgentService()
    executed_args: list[dict] = []

    async def fake_execute(_name, args):
        executed_args.append(args)
        return '{"ok":true}'

    monkeypatch.setattr(service.tool_registry, "execute", fake_execute)
    monkeypatch.setattr(service.tool_registry, "is_write_tool", lambda name: name == "update_chapter_content")

    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "更新两章正文"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="execute",
        )
    ]

    assert executed_args == [{"chapter_id": 1}, {"chapter_id": 2}]
    replay_calls = [
        message["tool_calls"][0]["id"]
        for message in payloads[-1]["messages"]
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    assert len(replay_calls) == len(set(replay_calls))
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "写入完成"


@pytest.mark.asyncio
async def test_agent_run_stream_sets_token_limit_and_continues_after_length(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response("第一段结尾重复", "length"),
            _agent_sse_response("结尾重复第二段", "stop"),
        ],
    )

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "请分析当前故事"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 2
    assert all(payload["max_tokens"] == 4096 for payload in payloads)
    assert all("max_completion_tokens" not in payload for payload in payloads)
    token_text = "".join(
        json.loads(event["data"])["content"]
        for event in events
        if event["event"] == "token"
    )
    assert token_text == "第一段结尾重复第二段"
    done = next(event for event in events if event["event"] == "done")
    assert json.loads(done["data"])["content"] == token_text
    assert "不要重复" in payloads[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_agent_reduces_output_token_limit_after_upstream_rejection(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [_FakeAgentOutputLimitErrorResponse(), _agent_sse_response("降档成功", "stop")],
    )
    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "继续处理"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert [payload["max_tokens"] for payload in payloads] == [4096, 2048]
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "降档成功"


def test_output_limit_error_recognizes_max_completion_tokens_field():
    assert agent_service_module._is_output_token_limit_response(
        400,
        '{"error":{"type":"invalid_request_error","message":"Invalid max_completion_tokens: value exceeds maximum 2048"}}',
    )


@pytest.mark.asyncio
async def test_agent_switches_output_token_field_when_upstream_requires_it(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [_FakeAgentUnsupportedMaxTokensResponse(), _agent_sse_response("兼容成功", "stop")],
    )

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "继续处理"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert payloads[0]["max_tokens"] == 4096
    assert "max_tokens" not in payloads[1]
    assert payloads[1]["max_completion_tokens"] == 4096
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"] == "兼容成功"


@pytest.mark.asyncio
async def test_agent_length_discards_incomplete_tool_call(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [
            _agent_sse_response(
                "",
                "length",
                tool_calls=[{
                    "index": 0,
                    "id": "call-truncated",
                    "function": {"name": "get_story_overview", "arguments": "{\"story_id\":"},
                }],
            ),
            _agent_sse_response("工具调用已重新规划", "stop"),
        ],
    )

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "查看故事概况"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert not any(event["event"] == "tool_call" for event in events)
    continuation_messages = payloads[1]["messages"]
    assert not any(message.get("tool_calls") for message in continuation_messages)
    assert "从头完整重发整个工具调用" in continuation_messages[-1]["content"]


@pytest.mark.asyncio
async def test_agent_truncation_continuation_limit(monkeypatch):
    payloads = _install_agent_stream_client(
        monkeypatch,
        [_agent_sse_response(f"片段{index}", "length") for index in range(9)],
    )

    with pytest.raises(agent_service_module.AgentTruncationContinuationLimitError) as exc_info:
        async for _ in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "持续分析"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        ):
            pass

    assert len(payloads) == 9
    assert exc_info.value.code == "agent_truncation_continuation_limit"
    assert "8 次安全上限" in str(exc_info.value)


@pytest.mark.asyncio
async def test_agent_truncation_limit_resets_after_successful_tool_response(monkeypatch):
    complete_tool_call = [{
        "index": 0,
        "id": "call-complete",
        "function": {"name": "get_story_overview", "arguments": "{}"},
    }]
    responses = (
        [_agent_sse_response(f"前段{index}", "length") for index in range(8)]
        + [_agent_sse_response("", "tool_calls", tool_calls=complete_tool_call)]
        + [_agent_sse_response(f"后段{index}", "length") for index in range(8)]
        + [_agent_sse_response("完成", "stop")]
    )
    payloads = _install_agent_stream_client(monkeypatch, responses)
    service = agent_service_module.AgentService()

    async def fake_execute(_name, _args):
        return '{"ok": true}'

    monkeypatch.setattr(service.tool_registry, "execute", fake_execute)

    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "执行长流程"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 18
    assert any(event["event"] == "tool_result" for event in events)
    assert json.loads(next(event for event in events if event["event"] == "done")["data"])["content"].endswith("完成")


@pytest.mark.asyncio
async def test_agent_finish_reason_ignores_trailing_null_choice(monkeypatch):
    response = _agent_sse_response("第一段", "length")
    response.insert(-1, f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}')
    payloads = _install_agent_stream_client(
        monkeypatch,
        [response, _agent_sse_response("第二段", "stop")],
    )

    events = [
        event
        async for event in agent_service_module.AgentService().run_stream(
            messages=[{"role": "user", "content": "继续分析"}],
            story_context="测试上下文",
            api_key="test-key",
            mode="analyze",
        )
    ]

    assert len(payloads) == 2
    token_text = "".join(
        json.loads(event["data"])["content"]
        for event in events
        if event["event"] == "token"
    )
    assert token_text == "第一段第二段"


@pytest.mark.asyncio
async def test_agent_history_compression_payload_sets_token_limit(monkeypatch):
    payloads: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "摘要"}}]}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json, headers):
            payloads.append(copy.deepcopy(json))
            return FakeResponse()

    monkeypatch.setattr(agent_service_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent_service_module, "_deepseek_auth_headers", lambda api_key: {"Authorization": "Bearer test"})
    monkeypatch.setattr(agent_service_module._deepseek_service, "runtime_base_url", lambda: "https://example.test/v1")
    monkeypatch.setattr(agent_service_module._deepseek_service, "runtime_model", lambda: "test-model")

    summary = await agent_service_module.AgentService()._compress_history_with_ai(
        [{"role": "user", "content": "旧消息"}],
        "test-key",
    )

    assert summary == "摘要"
    assert payloads[0]["max_tokens"] == 2048
    assert "max_completion_tokens" not in payloads[0]
