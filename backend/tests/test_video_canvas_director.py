"""画布 AI 导演服务：动态编排协议与确定性自动修复测试。

质量门语义：修复优先于拒绝——节拍漏覆盖自动补单元、时长越界自动钳制、
提示词为空自动兜底、对白原文缺失自动回填、分段时间轴断裂丢弃可选脚本。
只有结构级失败（非 JSON / 无有效单元）才返回 errors。
"""

import asyncio

import pytest

from services.errors import UpstreamServiceError
from services.video_canvas_director import (
    DIRECTOR_PLAN_SYSTEM_PROMPT,
    DIRECTOR_PROMPT_SYSTEM_PROMPT,
    build_director_plan_user_prompt,
    build_director_prompt_user_prompt,
    normalize_and_validate_director_plan,
    orchestrate_scene_video_units,
)


def _make_scenes() -> list[dict]:
    return [
        {
            "scene_id": 1,
            "title": "深夜的未接来电",
            "location": "出租屋",
            "time_of_day": "夜",
            "characters": ["林晚"],
            "scene_purpose": "建立悬念",
            "visual_anchors": [{"type": "set_dressing", "description": "桌上堆着外卖盒"}],
            "beats": [
                {"beat_id": "1.1", "type": "action", "importance": "high", "action": "林晚从床上坐起，盯着手机屏幕", "dialogue": []},
                {"beat_id": "1.2", "type": "dialogue", "importance": "high", "action": "林晚回拨电话", "dialogue": [{"character": "林晚", "line": "妈，这么晚打给我干嘛？"}]},
            ],
        },
        {
            "scene_id": 2,
            "title": "医院的走廊",
            "location": "医院走廊",
            "time_of_day": "夜",
            "characters": ["林晚", "陈默"],
            "scene_purpose": "揭示病情",
            "visual_anchors": [],
            "beats": [
                {"beat_id": "2.1", "type": "narration", "importance": "medium", "action": "走廊尽头的灯忽明忽暗", "dialogue": "走廊里只剩下消毒水的味道。"},
                {"beat_id": "2.2", "type": "dialogue", "importance": "high", "action": "陈默告知病情", "dialogue": [{"character": "陈默", "line": "医生说，最多还有三个月。"}]},
            ],
        },
    ]


_META = {
    "source_screenplay_hash": "hash-screenplay",
    "source_scene_node_id": "scene-node-1",
    "source_scene_revision": "rev-1",
}


def _make_raw_plan() -> dict:
    return {
        "pacing_strategy": "先悬念后揭示",
        "units": [
            {
                "unit_id": "u-001", "sequence": 1, "scene_ids": [1], "beat_ids": ["1.1", "1.2"],
                "title": "深夜来电", "narrative_purpose": "建立钩子",
                "duration_seconds": 6, "duration_reason": "一个动作加一句台词",
                "story_summary": "林晚深夜接到母亲来电",
                "dialogue_or_narration": "林晚：妈，这么晚打给我干嘛？",
                "transition_in": "开场", "transition_out": "悬念收尾，接到消息后冲出家门",
                "continuity": {"from_previous": "", "to_next": "林晚抓起外套冲出门", "anchor": "出租屋夜灯"},
                "video_prompt": "深夜出租屋内，林晚从床上坐起盯着手机屏幕，回拨电话急切询问，画面在她的表情特写中收束",
            },
            {
                "unit_id": "u-002", "sequence": 2, "scene_ids": [2], "beat_ids": ["2.1"],
                "title": "走廊", "narrative_purpose": "过渡",
                "duration_seconds": 4, "duration_reason": "一段旁白",
                "story_summary": "医院走廊过渡",
                "dialogue_or_narration": "走廊里只剩下消毒水的味道。",
                "transition_in": "承接林晚冲出家门", "transition_out": "镜头推向走廊尽头的陈默",
                "continuity": {"from_previous": "林晚赶往医院", "to_next": "陈默开口", "anchor": "医院走廊夜灯"},
                "video_prompt": "医院走廊夜色中灯光忽明忽暗，空镜推进渲染不安气氛",
            },
            {
                "unit_id": "u-003", "sequence": 3, "scene_ids": [2], "beat_ids": ["2.2"],
                "title": "病情揭示", "narrative_purpose": "信息揭示",
                "duration_seconds": 12, "duration_reason": "情绪转折需要完整反应",
                "story_summary": "陈默告知病情",
                "dialogue_or_narration": "陈默：医生说，最多还有三个月。",
                "transition_in": "承接走廊镜头", "transition_out": "收束于林晚的震惊表情",
                "continuity": {"from_previous": "陈默站在走廊尽头", "to_next": "", "anchor": "两人站位"},
                "video_prompt": "医院走廊里陈默低声告知病情，林晚的表情从疑惑转为崩溃，长镜头推进捕捉情绪转折",
            },
        ],
    }


def test_dynamic_duration_rules_in_prompt():
    text = DIRECTOR_PLAN_SYSTEM_PROMPT + DIRECTOR_PROMPT_SYSTEM_PROMPT
    assert "禁止所有单元等长" in text
    assert "15 秒" not in text.replace("15 秒或 10 秒", "")
    assert "每秒 3-4 字" in text
    assert "禁止为凑时长添加空镜" in text


def test_valid_plan_passes_without_repair():
    plan, errors = normalize_and_validate_director_plan(_make_raw_plan(), _make_scenes(), **_META)
    assert errors == []
    assert plan is not None
    durations = [unit["duration_seconds"] for unit in plan["units"]]
    assert durations == [6, 4, 12]
    assert plan["units"][0]["unit_id"] == "u-001"
    assert plan["units"][0]["sequence"] == 1
    # 节拍引用已归一为 "场景ID.节拍ID" 规范键
    assert plan["units"][0]["beat_ids"] == ["1.1.1", "1.1.2"]


def test_missing_beat_auto_generates_remedial_unit():
    raw = _make_raw_plan()
    raw["units"][2]["beat_ids"] = []
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    assert plan is not None
    assert len(plan["units"]) == 4
    remedial = plan["units"][-1]
    assert remedial["unit_id"] == "u-r004"
    assert remedial["beat_ids"] == ["2.2.2"]
    assert remedial["duration_seconds"] >= 3
    assert remedial["video_prompt"]
    assert "医生说，最多还有三个月" in remedial["dialogue_or_narration"]
    assert any("补充单元" in warning for warning in plan["warnings"])


def test_unknown_beat_dropped_and_covered_by_remedial_unit():
    raw = _make_raw_plan()
    raw["units"][0]["beat_ids"] = ["9.9"]
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    assert plan is not None
    assert plan["units"][0]["beat_ids"] == []
    assert any("不存在的节拍" in warning for warning in plan["warnings"])
    # 场景 1 的两个节拍由补充单元兜底
    remedial = plan["units"][-1]
    assert remedial["beat_ids"] == ["1.1.1", "1.1.2"]
    assert "妈，这么晚打给我干嘛" in remedial["dialogue_or_narration"]


def test_duplicate_beat_coverage_keeps_first_unit():
    raw = _make_raw_plan()
    raw["units"][1]["beat_ids"] = ["2.1", "2.2"]
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    assert plan is not None
    # 首个覆盖单元保留，后到的 u-003 被裁剪为空引用
    assert plan["units"][1]["beat_ids"] == ["2.2.1", "2.2.2"]
    assert plan["units"][2]["beat_ids"] == []
    assert any("重复" in warning for warning in plan["warnings"])


def test_duplicate_sequence_renumbered():
    raw = _make_raw_plan()
    raw["units"][1]["sequence"] = 1
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    assert [unit["sequence"] for unit in plan["units"]] == [1, 2, 3]
    assert any("修正" in warning for warning in plan["warnings"])


def test_out_of_range_duration_clamped_with_requested_preserved():
    raw = _make_raw_plan()
    raw["units"][0]["duration_seconds"] = 120
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    unit = plan["units"][0]
    assert unit["duration_seconds"] == 60
    assert unit["duration_requested"] == 120
    assert any("钳制" in warning for warning in plan["warnings"])


def test_missing_duration_estimated_from_beats():
    raw = _make_raw_plan()
    raw["units"][0]["duration_seconds"] = None
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    unit = plan["units"][0]
    assert isinstance(unit["duration_seconds"], int) and 3 <= unit["duration_seconds"] <= 60
    assert any("自动估算" in warning for warning in plan["warnings"])


def test_empty_video_prompt_fallback_filled():
    raw = _make_raw_plan()
    raw["units"][0]["video_prompt"] = ""
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    unit = plan["units"][0]
    assert len(unit["video_prompt"]) >= 12
    assert "林晚深夜接到母亲来电" in unit["video_prompt"]
    assert any("基础提示词" in warning for warning in plan["warnings"])


def test_broken_segment_timeline_dropped():
    raw = _make_raw_plan()
    raw["units"][0]["storyboard_json"] = {"segments": [
        {"start_second": 0, "end_second": 2.0},
        {"start_second": 4.0, "end_second": 6.0},
    ]}
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    assert plan["units"][0]["storyboard_json"] is None
    assert any("时间轴" in warning for warning in plan["warnings"])


def test_missing_dialogue_auto_backfilled_from_source_beat():
    raw = _make_raw_plan()
    raw["units"][2]["dialogue_or_narration"] = ""
    raw["units"][2]["story_summary"] = "陈默说了一些话"
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    unit = plan["units"][2]
    assert "陈默：医生说，最多还有三个月。" in unit["dialogue_or_narration"]
    assert any("回填" in warning for warning in plan["warnings"])


def test_duplicate_unit_id_renamed():
    raw = _make_raw_plan()
    raw["units"][1]["unit_id"] = "u-001"
    plan, errors = normalize_and_validate_director_plan(raw, _make_scenes(), **_META)
    assert errors == []
    ids = [unit["unit_id"] for unit in plan["units"]]
    assert len(set(ids)) == len(ids)


def test_non_dict_plan_rejected():
    plan, errors = normalize_and_validate_director_plan(["not", "a", "dict"], _make_scenes(), **_META)
    assert plan is None
    assert errors


def test_empty_units_rejected():
    plan, errors = normalize_and_validate_director_plan({"units": []}, _make_scenes(), **_META)
    assert plan is None
    assert errors


def test_user_prompt_embeds_scenes_json():
    prompt = build_director_plan_user_prompt(_make_scenes(), "节奏快一点")
    assert "节奏快一点" in prompt
    assert "深夜的未接来电" in prompt
    assert "1.1" in prompt


def test_prompt_user_prompt_embeds_units():
    plan, _errors = normalize_and_validate_director_plan(_make_raw_plan(), _make_scenes(), **_META)
    assert plan is not None
    prompt = build_director_prompt_user_prompt(plan)
    assert "u-001" in prompt
    assert "先悬念后揭示" in prompt


def test_orchestrate_repairs_structural_failure_then_succeeds(monkeypatch):
    calls: list[str] = []

    async def fake_call(*, system, user, api_key, max_tokens=32768):
        if system == DIRECTOR_PROMPT_SYSTEM_PROMPT:
            calls.append("prompt")
            return {"units": []}
        calls.append("plan")
        if len([c for c in calls if c == "plan"]) == 1:
            return {"units": []}  # 结构性失败 → 触发一次修复调用
        return _make_raw_plan()

    import services.video_canvas_director as director

    monkeypatch.setattr(director, "_call_deepseek_json", fake_call)

    plan = asyncio.run(orchestrate_scene_video_units(
        scenes=_make_scenes(),
        source_screenplay_hash="hash-screenplay",
        source_scene_node_id="scene-node-1",
        source_scene_revision="rev-1",
    ))
    assert calls.count("plan") == 2
    assert calls.count("prompt") == 1
    assert len(plan["units"]) == 3
    assert all(unit["video_prompt"] for unit in plan["units"])
    assert any("基础提示词" in warning for warning in plan["warnings"])


def test_orchestrate_quality_issues_auto_repaired_without_second_plan_call(monkeypatch):
    calls: list[str] = []

    async def fake_call(*, system, user, api_key, max_tokens=32768):
        if system == DIRECTOR_PROMPT_SYSTEM_PROMPT:
            calls.append("prompt")
            return {"units": []}
        calls.append("plan")
        raw = _make_raw_plan()
        raw["units"][2]["beat_ids"] = []  # 可修复问题 → 不再触发第二次规划调用
        return raw

    import services.video_canvas_director as director

    monkeypatch.setattr(director, "_call_deepseek_json", fake_call)

    plan = asyncio.run(orchestrate_scene_video_units(
        scenes=_make_scenes(),
        source_screenplay_hash="hash-screenplay",
        source_scene_node_id="scene-node-1",
        source_scene_revision="rev-1",
    ))
    assert calls.count("plan") == 1
    assert len(plan["units"]) == 4  # 补充单元兜底


def test_orchestrate_fails_after_second_structural_rejection(monkeypatch):
    import services.video_canvas_director as director

    async def fake_call(*, system, user, api_key, max_tokens=32768):
        return {"units": []}

    monkeypatch.setattr(director, "_call_deepseek_json", fake_call)

    with pytest.raises(UpstreamServiceError) as exc_info:
        asyncio.run(orchestrate_scene_video_units(
            scenes=_make_scenes(),
            source_screenplay_hash="hash-screenplay",
            source_scene_node_id="scene-node-1",
            source_scene_revision="rev-1",
        ))
    assert exc_info.value.code == "director_plan_quality_failed"
    assert "仍未生成有效方案" in str(exc_info.value)
