"""原文保真拆分的完整覆盖、来源验证及有限重试测试。"""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from services import deepseek
from services import screenplay_adapt as service
from services.errors import UpstreamServiceError


def beat(text, **fields):
    return {"source_text": text, "action": text, **fields}


def structured(*beats):
    return {"scenes": [{"beats": list(beats)}]}


def response(value, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {
        "content": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
    }}]}


@pytest.fixture
def upstream(monkeypatch):
    state = SimpleNamespace(calls=[], responses=[])

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            state.calls.append(deepcopy(kwargs["json"]))
            index = min(len(state.calls) - 1, len(state.responses) - 1)
            payload = state.responses[index]
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(deepseek, "runtime_model", lambda: "test-model")
    monkeypatch.setattr(deepseek, "runtime_base_url", lambda: "https://example.invalid/v1")
    monkeypatch.setattr(deepseek, "_deepseek_auth_headers", lambda *args: {})
    return state


def generate(content, **kwargs):
    return asyncio.run(service.generate_structured_screenplay(content=content, preserve_source=True, **kwargs))


def test_preserve_exact_original_and_explicit_unicode_offsets(upstream):
    text = " \n甲🙂推门。\n甲：别走！\n "
    first, second = "甲🙂推门。", "甲：别走！"
    start1, start2 = text.index(first), text.index(second)
    upstream.responses = [response(structured(
        beat(first, source_start=start1, source_end=start1 + len(first)),
        beat(second, source_start=start2, source_end=start2 + len(second), type="dialogue", action="", dialogue=[second]),
    ))]
    result = generate(text)
    beats = result["scenes"][0]["beats"]
    assert result["screenplay_text"] == text
    assert result["truncated"] is False
    assert result["source_span"] == {"start": 0, "end": len(text), "text": text}
    for item in beats:
        assert text[item["source_start"]:item["source_end"]] == item["source_text"]
        assert item["source_span"]["text"] == item["source_text"]
    assert beats[1]["dialogue"] == [second]
    assert len(upstream.calls) == 1
    assert "禁止改写对白" in upstream.calls[0]["messages"][0]["content"]


def test_missing_offsets_locates_repeated_text_in_order(upstream):
    upstream.responses = [response(structured(beat("停。"), beat("停。")))]
    result = generate("停。\n\n停。")
    assert [(item["source_start"], item["source_end"]) for item in result["scenes"][0]["beats"]] == [(0, 2), (4, 6)]


def test_invalid_first_result_gets_one_error_guided_full_retry(upstream):
    upstream.responses = [
        response(structured(beat("乙。"), beat("甲。"))),
        response(structured(beat("甲。"), beat("乙。"))),
    ]
    result = generate("甲。乙。")
    assert len(result["scenes"][0]["beats"]) == 2
    assert len(upstream.calls) == 2
    retry = upstream.calls[1]["messages"][-1]["content"]
    assert "不精确匹配" in retry or "乱序" in retry
    assert "不能删减原文" in retry


def test_malformed_offsets_are_relocated_from_cursor(upstream):
    text = "甲。乙。"
    for fields in (
        {"source_start": 1, "source_end": 5},
        {"source_start": True, "source_end": 4},
        {"source_start": 0},
        {"source_start": 2, "source_end": 4},
    ):
        upstream.responses = [response(structured(beat(text, **fields)))]
        result = generate(text)
        item = result["scenes"][0]["beats"][0]
        assert (item["source_start"], item["source_end"]) == (0, 4)
        assert item["source_text"] == text


def test_offsets_claiming_wrong_slice_are_relocated_when_text_still_found(upstream):
    text = "甲。乙。"
    upstream.responses = [response(structured(
        beat("甲。", source_start=2, source_end=4),
        beat("乙。", source_start=0, source_end=2),
    ))]
    result = generate(text)
    assert [(b["source_start"], b["source_end"]) for b in result["scenes"][0]["beats"]] == [(0, 2), (2, 4)]


@pytest.mark.parametrize("payload", [
    structured(beat("乙。"), beat("甲。")),
    structured(beat("甲。", source_start=0, source_end=2), beat("甲。", source_start=0, source_end=2)),
    structured(beat("不存在的片段")),
    {"scenes": []},
])
def test_invalid_or_unfaithful_result_is_rejected_after_only_two_calls(upstream, payload):
    upstream.responses = [response(payload)]
    with pytest.raises(UpstreamServiceError) as failure:
        generate("甲。乙。")
    assert failure.value.code == "screenplay_preserve_validation_failed"
    assert failure.value.retryable is False
    assert len(upstream.calls) == 2


@pytest.mark.parametrize("payload,expected_beats", [
    (structured(beat("乙。")), 2),
    (structured(beat("甲。")), 2),
    (structured(beat("甲。乙。", action="新剧情")), 1),
    (structured(beat("甲。乙。", dialogue=["改写的对白"])), 1),
    (structured(beat("甲。乙。", dialogue=[{"character": "新角色", "line": "甲。"}])), 1),
    (structured(beat("甲。乙。", action="", dialogue=[])), 1),
    (structured(beat("甲。"), beat("乙。", action="甲。")), 2),
    ({"scenes": [{"beats": [beat("甲。乙。")], "location": "不存在的场景"}]}, 1),
    ({"scenes": [{"beats": [beat("甲。乙。")], "characters": ["新增角色"]}]}, 1),
    ({"scenes": [{"beats": [beat("甲。乙。")], "scene_purpose": "新增剧情目的"}]}, 1),
    ({"scenes": [{"beats": [beat("甲。乙。")], "visual_anchors": [{"type": "prop", "description": "新增道具"}]}]}, 1),
])
def test_imperfect_but_locatable_model_output_is_repaired(upstream, payload, expected_beats):
    upstream.responses = [response(payload)]
    result = generate("甲。乙。")
    assert len(upstream.calls) == 1
    beats = result["scenes"][0]["beats"]
    assert len(beats) == expected_beats
    assert result["screenplay_text"] == "甲。乙。"
    text = "甲。乙。"
    for item in beats:
        assert text[item["source_start"]:item["source_end"]] == item["source_text"]


def test_missing_prefix_gap_is_filled_without_retrying(upstream):
    text = "《最后一班地铁》\n\n场景1：地铁车厢 / 夜晚 / 内景\n\n甲说：你好。"
    quoted = "甲说：你好。"
    start = text.index(quoted)
    upstream.responses = [response(structured(
        beat(quoted, source_start=start, source_end=start + len(quoted), type="dialogue", action="", dialogue=[quoted]),
    ))]
    result = generate(text)
    assert len(upstream.calls) == 1
    beats = result["scenes"][0]["beats"]
    assert beats[0]["source_start"] == 0
    assert beats[-1]["source_text"] == quoted
    joined = "".join(item["source_text"] for item in beats)
    assert "《最后一班地铁》" in joined
    assert "场景1：地铁车厢" in joined


@pytest.mark.parametrize("finish,raw", [
    ("length", structured(beat("甲。"))),
    ("stop", '{"scenes":[{"beats":[{"source_text":"甲。","action":"甲。"}]'),
    ("stop", '```json\n{"scenes":[]}\n```'),
    ("stop", {"truncated": True, "scenes": [{"beats": [beat("甲。")]}]}),
])
def test_truncation_or_repairable_json_is_never_accepted(upstream, monkeypatch, finish, raw):
    def forbidden(*args):
        pytest.fail("保真模式不能调用宽松 JSON 修复")

    monkeypatch.setattr(deepseek, "_loads_json_lenient", forbidden)
    monkeypatch.setattr(deepseek, "_repair_truncated_json", forbidden)
    upstream.responses = [response(raw, finish)]
    with pytest.raises(UpstreamServiceError):
        generate("甲。")
    assert len(upstream.calls) == 2


def test_max_scenes_never_silently_drops_tail(upstream):
    upstream.responses = [response({"scenes": [{"beats": [beat("甲。")]}, {"beats": [beat("乙。")]}]})]
    with pytest.raises(UpstreamServiceError, match="场景数超过"):
        generate("甲。乙。", max_scenes=1)
    assert len(upstream.calls) == 2


def test_dialogue_dictionary_preserves_literal_character_and_line(upstream):
    text = "甲：别走。"
    upstream.responses = [response(structured(beat(text, action="", type="dialogue", dialogue=[{"character": "甲", "line": "别走。"}])))]
    result = generate(text)
    assert result["scenes"][0]["beats"][0]["dialogue"] == [{"character": "甲", "line": "别走。"}]


@pytest.mark.parametrize("source,action,dialogue,kind", [
    ("甲推门后取出信。", "甲", [], "action"),
    ("甲：别走。", "甲：别走。", [], "action"),
    ("甲：别走。乙：站住。", "", ["甲：别走。乙：站住。"], "dialogue"),
    ("甲：别走。还有证据。", "", ["甲：别走。"], "dialogue"),
])
def test_source_quote_cannot_hide_omitted_or_misclassified_production_content(source, action, dialogue, kind):
    with pytest.raises(ValueError):
        service._validate_atomic_preserved_content(source, action, dialogue, kind, "节拍1")


def test_scene_header_is_not_misclassified_as_speech():
    service._validate_atomic_preserved_content("地点：客厅", "地点：客厅", [], "action", "节拍1")


def test_default_mode_keeps_existing_rewrite_behavior(upstream):
    upstream.responses = [response({"screenplay": "旧模式允许改写", "scenes": [{"title": "新标题", "beats": [{"action": "改写后的动作"}]}]})]
    result = asyncio.run(service.generate_structured_screenplay(content="小说原文"))
    assert result["screenplay_text"] == "旧模式允许改写"
    assert result["scenes"][0]["beats"][0]["action"] == "改写后的动作"
    assert len(upstream.calls) == 1


def test_whitespace_only_source_is_rejected_without_request(upstream):
    with pytest.raises(ValueError):
        generate(" \r\n\t ")
    assert upstream.calls == []


def test_screenplay_layout_repairs_partial_model_output_on_first_call(upstream):
    text = "场景1：萧家广场 / 日 / 外景\n广场上人头攒动。\n萧炎：这是哪里？"
    upstream.responses = [response(structured(beat("广场上人头攒动。")))]
    result = generate(text)

    assert result["screenplay_text"] == text
    assert result["preserve_source"] is True
    assert len(upstream.calls) == 1
    beats = result["scenes"][0]["beats"]
    assert [item["type"] for item in beats] == ["action", "action", "dialogue"]
    assert beats[-1]["dialogue"] == ["萧炎：这是哪里？"]


def test_screenplay_layout_uses_line_fallback_after_two_hard_failures(upstream):
    text = "场景1：萧家广场 / 日 / 外景\n广场上人头攒动。\n萧炎：这是哪里？"
    upstream.responses = [response(structured(beat("不存在的片段")))]
    result = generate(text)
    assert len(upstream.calls) == 2
    assert result["preserve_source"] is True
    beats = result["scenes"][0]["beats"]
    assert [item["type"] for item in beats] == ["action", "action", "dialogue"]
    assert beats[-1]["dialogue"] == ["萧炎：这是哪里？"]


def test_plain_text_does_not_silently_fallback(upstream):
    upstream.responses = [response(structured(beat("不存在的片段")))]
    with pytest.raises(UpstreamServiceError):
        generate("甲。乙。")


def test_fallback_classifies_mid_line_speaker_as_dialogue(upstream):
    text = "场景1：客厅 / 日 / 内景\n他转过头，说：你来了。\n小明：来吧，小红：好的。"
    upstream.responses = [response(structured(beat("不存在的片段")))]
    result = generate(text)
    assert len(upstream.calls) == 2
    beats = result["scenes"][0]["beats"]
    assert [item["type"] for item in beats] == ["action", "dialogue", "dialogue", "dialogue"]
    assert beats[1]["dialogue"] == ["他转过头，说：你来了。"]
    assert beats[2]["source_text"] == "小明：来吧，"
    assert beats[3]["source_text"] == "小红：好的。"
    assert result["scenes"][0]["characters"] == ["小明", "小红"]  # “说”不是角色，清洗时去掉
    assert result["screenplay_text"] == text


def test_fallback_keeps_header_prefixed_speaker_line_as_dialogue(upstream):
    text = "场景2：书房 / 傍晚 / 内景\n时间：傍晚，小明：你来了。"
    upstream.responses = [response(structured(beat("不存在的片段")))]
    result = generate(text)
    assert len(upstream.calls) == 2
    beats = result["scenes"][0]["beats"]
    assert [item["type"] for item in beats] == ["action", "dialogue"]
    assert beats[1]["dialogue"] == ["时间：傍晚，小明：你来了。"]
    assert "小明" in result["scenes"][0]["characters"]


def test_fallback_merges_preheader_title_into_first_scene(upstream):
    text = "《最后一班地铁》\n\n场景1：地铁车厢 / 夜晚 / 内景\n甲：走吧。"
    upstream.responses = [response(structured(beat("不存在的片段")))]
    result = generate(text)
    assert len(upstream.calls) == 2
    assert len(result["scenes"]) == 1
    scene = result["scenes"][0]
    assert scene["title"].startswith("场景1")
    assert scene["beats"][0]["source_text"] == "《最后一班地铁》"
    assert any(item["dialogue"] == ["甲：走吧。"] for item in scene["beats"])


def test_model_packing_all_headers_into_one_scene_is_split(upstream):
    text = (
        "《最后一班地铁》\n\n"
        "场景1：地铁车厢 / 夜晚 / 内景\n\n甲上车。\n\n甲：你好。\n\n"
        "场景2：地铁站台 / 夜晚 / 内景\n\n乙等待。\n\n乙：走吧。\n\n"
        "场景3：地铁站台 / 夜晚 / 内景\n\n列车开走。"
    )
    upstream.responses = [response(structured(
        beat(text, source_start=0, source_end=len(text)),
    ))]
    result = generate(text)
    assert len(upstream.calls) == 1
    assert len(result["scenes"]) == 3
    titles = [scene["title"] for scene in result["scenes"]]
    assert titles[0].startswith("场景1")
    assert titles[1].startswith("场景2")
    assert titles[2].startswith("场景3")
    covered = sum(len(scene["beats"]) for scene in result["scenes"])
    assert covered >= 6
