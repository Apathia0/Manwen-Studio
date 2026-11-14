"""历史摘要持久化、提前压缩、参考素材分析与图片 token 估算的回归测试。"""

import json

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentAttachment
from services import agent_reference_analysis as reference
from services import agent_service as agent_service_module
from services.agent_media import multimodal_content
from services.token_utils import (
    EMERGENCY_MAX_USER_IMAGES,
    IMAGE_TOKEN_ESTIMATE,
    emergency_compact_messages,
    estimate_messages_tokens,
)
from tests.test_agent_media import _agent_sse_response, _install_agent_stream_client


# ── 图片 token 估算与紧急压缩 ─────────────────────────────

def test_images_are_counted_in_token_estimate():
    text_only = [{"role": "user", "content": [{"type": "text", "text": "看图"}]}]
    with_images = [{"role": "user", "content": [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,y"}},
    ]}]
    assert estimate_messages_tokens(with_images) - estimate_messages_tokens(text_only) == 2 * IMAGE_TOKEN_ESTIMATE


def test_emergency_compaction_keeps_user_uploaded_references_beyond_generic_limit():
    content = [{"type": "text", "text": "按参考图风格优化"}]
    for index in range(5):
        content.append({"type": "text", "text": f"[用户上传的参考素材《ref{index}.png》]"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,user-{index}"}})
    content.append({"type": "text", "text": "[画布已生成的产物（不是用户提供的参考）《canvas.png》]"})
    for index in range(4):
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,canvas-{index}"}})
    compacted = emergency_compact_messages([{"role": "user", "content": content}])
    urls = [item["image_url"]["url"] for item in compacted[0]["content"] if item.get("type") == "image_url"]
    assert [url for url in urls if "user-" in url] == [f"data:image/jpeg;base64,user-{i}" for i in range(EMERGENCY_MAX_USER_IMAGES)]
    assert len([url for url in urls if "canvas-" in url]) == 2


def test_multimodal_content_labels_user_references_and_canvas_media(tmp_path):
    image_path = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), "red").save(image_path)
    content = multimodal_content("请参考", [
        {"media_kind": "image", "filename": "ref.png", "content_type": "image/png", "path": str(image_path), "source": "user_upload"},
        {"media_kind": "image", "filename": "node.png", "content_type": "image/png", "path": str(image_path), "source": "canvas_media"},
    ])
    texts = [item["text"] for item in content if item["type"] == "text"]
    assert any("用户上传的参考素材《ref.png》" in text for text in texts)
    assert any("画布已生成的产物" in text and "node.png" in text for text in texts)


# ── 参考素材分析持久化 ───────────────────────────────────

@pytest.fixture
def attachment_db():
    engine = create_engine("sqlite:///:memory:")
    AgentAttachment.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        for attachment_id, conversation_id in (("a1", 7), ("a2", 7), ("a3", 8)):
            db.add(AgentAttachment(
                id=attachment_id, owner_user_id=1, story_id=2, conversation_id=conversation_id,
                original_name=f"{attachment_id}.png", content_type="image/png", file_size=1,
                storage_path="x", metadata_json={"media_kind": "image"},
            ))
        db.commit()
    with factory() as db:
        yield db
    engine.dispose()


def test_reference_analysis_is_persisted_and_reloaded_per_conversation(attachment_db):
    db = attachment_db
    reference.persist_reference_analysis(db, ["a1", "a2"], "【风格关键词】赛璐璐，高饱和")
    reference.persist_reference_analysis(db, ["a3"], "另一会话的分析")
    loaded = reference.load_conversation_reference_analyses(db, owner_user_id=1, story_id=2, conversation_id=7)
    assert len(loaded) == 1, "同一次分析写入多张附件时按文本去重"
    assert loaded[0]["analysis"].startswith("【风格关键词】")
    excluded = reference.load_conversation_reference_analyses(db, owner_user_id=1, story_id=2, conversation_id=7, exclude_ids=["a1", "a2"])
    assert excluded == []
    other_owner = reference.load_conversation_reference_analyses(db, owner_user_id=9, story_id=2, conversation_id=7)
    assert other_owner == []
    assert "参考素材分析" in reference.format_reference_context(loaded, title="参考素材分析（本会话此前上传）")
    assert reference.format_reference_context([], title="x") == ""


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    @property
    def is_error(self):
        return self.status_code >= 400

    def json(self):
        return self._body


def _install_fake_httpx(monkeypatch, responses):
    payloads = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            payloads.append({"url": url, "json": json})
            return responses.pop(0)

    monkeypatch.setattr(reference.httpx, "AsyncClient", FakeClient)
    return payloads


def _image_attachment(tmp_path):
    path = tmp_path / "ref.png"
    Image.new("RGB", (16, 16), "blue").save(path)
    return {"id": "a1", "media_kind": "image", "filename": "ref.png", "content_type": "image/png", "path": str(path), "source": "user_upload"}


def _ok(text, finish="stop"):
    return _FakeResponse(200, {"choices": [{"message": {"content": text}, "finish_reason": finish}]})


async def _analyze(attachment):
    return await reference.analyze_reference_media(
        [attachment], user_text="参考这张", api_key="k", base_url="https://main.test/v1", model="main", headers_factory=lambda key: {"Authorization": key},
    )


@pytest.mark.asyncio
async def test_analysis_enables_thinking_and_returns_text(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_VISION_BASE_URL", raising=False)
    payloads = _install_fake_httpx(monkeypatch, [_ok("【内容概述】少女")])
    result = await _analyze(_image_attachment(tmp_path))
    assert result and result["analysis"] == "【内容概述】少女" and result["used_vision_model"] is False
    assert payloads[0]["json"]["thinking"] == {"type": "enabled"}
    assert payloads[0]["url"].startswith("https://main.test/v1")


@pytest.mark.asyncio
async def test_analysis_retries_without_thinking_when_upstream_rejects_field(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_VISION_BASE_URL", raising=False)
    payloads = _install_fake_httpx(monkeypatch, [_FakeResponse(400, {}), _ok("分析结果")])
    result = await _analyze(_image_attachment(tmp_path))
    assert result and result["thinking"] is False
    assert "thinking" not in payloads[1]["json"]


@pytest.mark.asyncio
async def test_analysis_doubles_budget_when_reasoning_consumes_output(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_VISION_BASE_URL", raising=False)
    payloads = _install_fake_httpx(monkeypatch, [_ok("", "length"), _ok("终于有正文")])
    result = await _analyze(_image_attachment(tmp_path))
    assert result and result["analysis"] == "终于有正文"
    assert payloads[1]["json"]["max_tokens"] == 2 * payloads[0]["json"]["max_tokens"]


@pytest.mark.asyncio
async def test_analysis_uses_dedicated_vision_model_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_VISION_BASE_URL", "https://vision.test/v1/")
    monkeypatch.setenv("AGENT_VISION_MODEL", "vision-x")
    monkeypatch.setenv("AGENT_VISION_API_KEY", "vk")
    payloads = _install_fake_httpx(monkeypatch, [_ok("视觉分析")])
    result = await _analyze(_image_attachment(tmp_path))
    assert result and result["used_vision_model"] is True
    assert payloads[0]["url"] == "https://vision.test/v1/chat/completions"
    assert payloads[0]["json"]["model"] == "vision-x"


@pytest.mark.asyncio
async def test_analysis_failure_returns_none_instead_of_raising(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_VISION_BASE_URL", raising=False)
    _install_fake_httpx(monkeypatch, [_FakeResponse(400, {}), _FakeResponse(400, {})])
    assert await _analyze(_image_attachment(tmp_path)) is None
    assert await reference.analyze_reference_media([], user_text="", api_key="k", base_url="b", model="m", headers_factory=lambda key: {}) is None


# ── 历史摘要持久化与提前压缩 ──────────────────────────────

def _long_history(count, *, with_prefix=False):
    messages = []
    if with_prefix:
        messages.append({"role": "user", "_agent_synthetic_context": "history", "content": "## 对话历史摘要\n\n旧摘要"})
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"第{index}条消息：" + "画布节点提示词内容" * 110})
    return messages


def _patch_budget(monkeypatch, service, summary_result):
    monkeypatch.setattr(service, "_build_system_prompt", lambda *_a, **_k: "系统提示")
    monkeypatch.setattr(agent_service_module, "load_model_capability", lambda *_a, **_k: {"observed_context_limit": 40000, "observed_output_limit": 2048})
    monkeypatch.setattr(agent_service_module, "persist_model_capability_observation", lambda *_a, **_k: {})
    calls = []

    async def fake_summary(old_messages, api_key):
        calls.append(len(old_messages))
        if isinstance(summary_result, Exception):
            raise summary_result
        return summary_result

    monkeypatch.setattr(service, "_compress_history_with_ai", fake_summary)
    return calls


async def _run(service, messages, ids, callback):
    return [
        event
        async for event in service.run_stream(
            messages=messages,
            story_context="测试上下文",
            api_key="test-key",
            history_message_ids=ids,
            on_history_compressed=callback,
            db=object(),
        )
    ]


@pytest.mark.asyncio
async def test_soft_threshold_compresses_early_and_persists_summary(monkeypatch):
    payloads = _install_agent_stream_client(monkeypatch, [_agent_sse_response("好的", "stop")])
    service = agent_service_module.AgentService()
    calls = _patch_budget(monkeypatch, service, "新的结构化摘要")
    persisted = []
    messages = _long_history(14)
    ids = list(range(101, 115))

    estimated = agent_service_module.estimate_messages_tokens if hasattr(agent_service_module, "estimate_messages_tokens") else None
    del estimated  # 仅确认预算场景：14 条长消息使输入落在 70%~100% 预算之间
    await _run(service, messages, ids, lambda summary, upto: persisted.append((summary, upto)))

    assert calls == [6], "keep_recent=8，14 条消息中最早 6 条被折叠"
    assert persisted == [("新的结构化摘要", 106)]
    sent = json.dumps(payloads[0]["messages"], ensure_ascii=False)
    assert "新的结构化摘要" in sent and "第13条消息" in sent and "第0条消息" not in sent


@pytest.mark.asyncio
async def test_existing_summary_prefix_is_not_counted_as_database_message(monkeypatch):
    _install_agent_stream_client(monkeypatch, [_agent_sse_response("好的", "stop")])
    service = agent_service_module.AgentService()
    _patch_budget(monkeypatch, service, "合并后的摘要")
    persisted = []
    messages = _long_history(13, with_prefix=True)  # 1 条旧摘要 + 13 条数据库消息
    ids = list(range(201, 214))
    await _run(service, messages, ids, lambda summary, upto: persisted.append((summary, upto)))
    # 14 条里最早 6 条被折叠：1 条旧摘要 + 5 条数据库消息 → 覆盖到第 5 条的 id
    assert persisted == [("合并后的摘要", 205)]


@pytest.mark.asyncio
async def test_failed_summary_never_persists_and_falls_back(monkeypatch):
    _install_agent_stream_client(monkeypatch, [_agent_sse_response("好的", "stop")])
    service = agent_service_module.AgentService()
    _patch_budget(monkeypatch, service, ValueError("历史摘要为空"))
    persisted = []
    events = await _run(service, _long_history(14), list(range(1, 15)), lambda summary, upto: persisted.append((summary, upto)))
    assert persisted == []
    assert any(event["event"] == "done" for event in events)


# ── 画布助手英文过程说明过滤 ─────────────────────────────

def _feed_all(chunks):
    narration = agent_service_module.EnglishNarrationFilter()
    out = "".join(narration.feed(chunk) for chunk in chunks) + narration.finish()
    return out, narration.dropped


def test_filter_drops_english_preamble_and_keeps_chinese_from_first_cjk():
    text = "I'll start by reading the current canvas state and status, then create the screenplay.I found the canvas is empty.剧本已写入画布，剩余编排已在后台自动进行。"
    chunks = [text[i:i + 7] for i in range(0, len(text), 7)]  # 模拟流式小块
    out, dropped = _feed_all(chunks)
    assert out == "剧本已写入画布，剩余编排已在后台自动进行。" and dropped is True


def test_filter_passes_chinese_replies_with_english_identifiers_untouched():
    text = "好的，我会调用 canvas_stage 提交 screenplay 阶段，节点 ID 是 screenplay-abc123。"
    out, dropped = _feed_all([text[i:i + 5] for i in range(0, len(text), 5)])
    assert out == text and dropped is False


def test_filter_flushes_short_undecided_reply_and_drops_pure_english_tool_narration():
    assert _feed_all(["OK"]) == ("OK", False)
    out, dropped = _feed_all(["Now let me create the screenplay and write it to the canvas now."])
    assert out == "" and dropped is True


@pytest.mark.asyncio
async def test_canvas_agent_discards_english_narration_and_asks_for_chinese_reply(monkeypatch):
    payloads = _install_agent_stream_client(monkeypatch, [
        _agent_sse_response("I'll start by reading the current canvas state and status, then create it.", "stop"),
        _agent_sse_response("已读取画布，正在处理。", "stop"),
    ])
    service = agent_service_module.AgentService()
    monkeypatch.setattr(service, "_build_system_prompt", lambda *_a, **_k: "系统提示")
    events = [
        event
        async for event in service.run_stream(
            messages=[{"role": "user", "content": "写个剧本"}],
            story_context="测试上下文",
            api_key="test-key",
            workflow_type="video_canvas",
            workflow_id=1,
        )
    ]
    tokens = "".join(json.loads(event["data"])["content"] for event in events if event["event"] == "token")
    assert tokens == "已读取画布，正在处理。"
    assert len(payloads) == 2 and "上一条回复使用了英文" in json.dumps(payloads[1]["messages"], ensure_ascii=False)


# ── 助手主动看图：数量不设上限 ─────────────────────────────

def _noise_image(path, size=900):
    import random

    image = Image.new("RGB", (size, size))
    image.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(size * size)])
    image.save(path, format="PNG")


def test_canvas_observation_never_raises_and_defers_overflow_to_next_call(tmp_path, monkeypatch):
    """几十张图也不能像用户附件那样直接报 413 中断；装不下的节点列出来让助手再调一次。"""
    from services import agent_media

    monkeypatch.setattr(agent_media, "MAX_MULTIMODAL_BYTES", 400_000)
    attachments = []
    for index in range(12):
        path = tmp_path / f"n{index}.png"
        _noise_image(path, 500)
        attachments.append({"filename": f"画布媒体观察[node=n{index}]", "media_kind": "image", "content_type": "image/png", "path": str(path), "node_id": f"n{index}"})
    content = agent_media.canvas_observation_content("摘要", attachments)
    images = [item for item in content if item.get("type") == "image_url"]
    assert 0 < len(images) < 12
    note = content[-1]["text"]
    assert "这次没有附图" in note and "n11" in note and "inspect_canvas_media" in note
    # 每张图前都有节点标注，便于对应
    assert any(item.get("text") == "[画布媒体观察[node=n0]]" for item in content)


def test_observation_resolution_scales_down_when_viewing_many_images():
    from services.agent_media import _observation_max_edge

    assert _observation_max_edge(4) == 1600 and _observation_max_edge(12) == 1024 and _observation_max_edge(40) == 768


def test_old_observation_images_rotate_out_of_context_but_text_is_kept():
    from services.agent_service import _evict_consumed_observation_images

    def observation(tag, count):
        return {"role": "user", "_agent_synthetic_context": "canvas_media_observation", "content": [{"type": "text", "text": tag}, *[{"type": "image_url", "image_url": {"url": f"data:{tag}{i}"}} for i in range(count)]]}

    messages = [{"role": "system", "content": "s"}, observation("第一批", 10), {"role": "assistant", "content": "看完了"}, observation("第二批", 10), observation("第三批", 10)]
    removed = _evict_consumed_observation_images(messages)
    assert removed == 10
    first = messages[1]["content"]
    assert first[0]["text"] == "第一批" and not any(item.get("type") == "image_url" for item in first)
    assert "已移出上下文" in first[-1]["text"]
    assert sum(1 for item in messages[3]["content"] if item.get("type") == "image_url") == 10
    assert sum(1 for item in messages[4]["content"] if item.get("type") == "image_url") == 10
    assert _evict_consumed_observation_images(messages) == 0, "幂等"
