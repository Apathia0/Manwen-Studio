"""剧本头部信息（标题、一句话梗概）不再被当成对白，也不参与导演编排。"""

import asyncio
from copy import deepcopy

import pytest

from services import screenplay_adapt
from services import video_canvas_director as old
from services.canvas_director_quality import direct, validate_plan
from services.screenplay_meta import is_meta_label, is_meta_line, is_meta_text, strip_meta_beats

LOGLINE = "一句话梗概：被当众踩进泥里的实习生，在签约宴上亮出真实身份，一纸签字让羞辱他的人当场失业。"
POLICY = {"duration_options": [5, 10, 15], "reference_mode": "clean_single_frame"}


def beat(beat_id, text, dialogue=None, kind="action"):
    return {"beat_id": beat_id, "source_text": text, "action": "" if dialogue else text, "dialogue": dialogue or [], "type": kind}


def scene_with_meta():
    return [{
        "scene_id": 1, "location": "宴会厅", "characters": ["顾沉"],
        "beats": [beat(1, "《定位》"), beat(2, LOGLINE, [LOGLINE], "dialogue"), beat(3, "顾沉捡起工牌。")],
    }]


@pytest.mark.parametrize("name", ["一句话梗概", "故事简介", "片名", "题材", "画幅", "Logline", "备注"])
def test_metadata_labels_are_recognized(name):
    assert is_meta_label(name)


@pytest.mark.parametrize("name", ["顾沉", "陈磊", "旁白", "主管"])
def test_character_names_are_not_metadata(name):
    assert not is_meta_label(name)


def test_title_and_logline_lines_are_metadata_but_dialogue_is_not():
    assert is_meta_line("《定位》") and is_meta_line(LOGLINE)
    assert not is_meta_line("顾沉：我进来就行。") and not is_meta_line("旁白：雨很大。")
    assert is_meta_text("《定位》\n\n" + LOGLINE)
    assert not is_meta_text(LOGLINE + "\n顾沉：走。")


def test_strip_meta_beats_keeps_real_beats_and_does_not_mutate_input():
    original = scene_with_meta()
    snapshot = deepcopy(original)
    cleaned = strip_meta_beats(original)
    assert [b["beat_id"] for b in cleaned[0]["beats"]] == [3]
    assert original == snapshot


def test_scene_with_only_metadata_is_dropped():
    scenes = [{"scene_id": 1, "beats": [beat(1, "《定位》")]}, {"scene_id": 2, "beats": [beat(1, "顾沉走进大厅。")]}]
    assert [s["scene_id"] for s in strip_meta_beats(scenes)] == [2]


def test_logline_is_no_longer_treated_as_a_speaker_line():
    assert screenplay_adapt._real_speaker_matches(LOGLINE) == []
    beats = screenplay_adapt._fallback_line_beats(LOGLINE, 0)
    assert beats[0]["type"] == "action" and beats[0]["dialogue"] == []
    assert screenplay_adapt._real_speaker_matches("顾沉：我进来就行。") != []


def timeline_plan():
    return {"units": [{
        "unit_id": "u1", "sequence": 1, "beat_ids": ["1.3"], "duration_seconds": 5, "narrative_purpose": "顾沉捡起工牌确立处境",
        "storyboard_prompt": "宴会厅地面，顾沉蹲下伸手去捡工牌，暖光从头顶洒下，构图偏低",
        "storyboard_json": {"segments": [{"start_second": 0, "end_second": 5, "visual_action": "捡起工牌", "camera_direction": "固定近景", "start_state": "工牌在地", "end_state": "工牌在手", "dialogue_or_narration": ""}]},
    }]}


def test_validation_fails_when_metadata_beats_are_kept_but_passes_after_stripping():
    """回归：梗概被当成 50 字对白，5 秒内不可能完成，且要求时间轴逐字包含它。"""
    scenes = scene_with_meta()
    plan = timeline_plan()
    plan["units"][0]["beat_ids"] = ["1.1", "1.2", "1.3"]
    assert validate_plan(plan, scenes, POLICY, require_shots=True)
    assert validate_plan(timeline_plan(), strip_meta_beats(scenes), POLICY, require_shots=True) == []


@pytest.mark.asyncio
async def test_director_plans_only_real_beats(monkeypatch):
    async def call(**kwargs):
        return timeline_plan()

    monkeypatch.setattr(old, "_call_deepseek_json", call)
    result = await direct(scene_with_meta(), POLICY, source_screenplay_hash="s", source_scene_node_id="n", source_scene_revision="r")
    assert [item["source_id"] for item in result["units"][0]["source_beats"]] == ["1.3"]
