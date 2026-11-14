"""画布资产分析：只提取高度出现、有重要性的场景/道具，其余作为可选候选。"""

import asyncio

import pytest

from services import canvas_asset_analysis as analysis
from services import deepseek as deepseek_service
from services import video_canvas_director as director
from services.errors import UpstreamServiceError

SCRIPT = "宴会厅里，顾沉捡起工牌。陈磊把工牌摔在地上。顾沉握紧工牌。主管的咖啡杯被打翻。走廊尽头有一台自动售货机。宴会厅的灯亮起。"


def scene(scene_id, location, characters, text="", time="夜"):
    return {"scene_id": scene_id, "title": location, "location": location, "time_of_day": time, "characters": characters, "beats": [{"source_text": text}]}


SCENES = [scene("1", "宴会厅", ["顾沉", "陈磊"], "顾沉捡起工牌"), scene("2", "走廊", ["顾沉"], "自动售货机"), scene("3", "宴会厅", ["顾沉", "陈磊"], "陈磊摔工牌")]


def triage_payload(**overrides):
    payload = {
        "style": {"art_style": "都市写实", "palette": "冷暖对比"},
        "characters": [{"name": "顾沉", "profile": "二十三岁实习生"}, {"name": "陈磊", "profile": "主管"}],
        "scenes": [{"name": "宴会厅（夜）", "scene_ids": ["1", "3"], "prompt": "金色宴会大厅"}, {"name": "走廊", "scene_ids": ["2"], "prompt": "冷色走廊"}],
        "props": [{"name": "工牌", "scene_ids": ["1", "3"], "prompt": "蓝色工牌"}, {"name": "咖啡杯", "scene_ids": ["2"], "prompt": "咖啡杯"}, {"name": "自动售货机", "scene_ids": ["2"], "prompt": "售货机"}, {"name": "虚构物", "scene_ids": ["1", "3"], "prompt": "不存在"}],
        "optional": [{"role": "prop", "name": "自动售货机", "scene_ids": ["2"], "desc": "走廊里的售货机"}],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def stubs(monkeypatch):
    calls = {"triage": 0, "character": 0}
    state = {"triage": triage_payload(), "character_error": None}

    async def fake_json(**kwargs):
        calls["triage"] += 1
        if isinstance(state["triage"], Exception):
            raise state["triage"]
        return state["triage"]

    async def fake_character(shot_data, character_profiles="", api_key=None):
        calls["character"] += 1
        state["character_args"] = (shot_data, character_profiles)
        if state["character_error"]:
            raise state["character_error"]
        return [{"name": name, "prompt": f"{name}三视图"} for name in shot_data["characters"]]

    monkeypatch.setattr(director, "_call_deepseek_json", fake_json)
    monkeypatch.setattr(analysis, "generate_character_prompts", fake_character)
    return SimpleState(calls, state)


class SimpleState:
    def __init__(self, calls, state):
        self.calls, self.state = calls, state


def run():
    return asyncio.run(analysis.analyze_scene_assets(scenes=SCENES, screenplay_text=SCRIPT))


def test_only_two_model_calls_regardless_of_scene_count(stubs):
    run()
    assert stubs.calls == {"triage": 1, "character": 1}


def test_recurring_scene_and_prop_are_extracted_others_become_candidates(stubs):
    result = run()
    by_role = {}
    for asset in result["assets"]:
        by_role.setdefault(asset["role"], []).append(asset["name"])
    assert by_role["character"] == ["陈磊", "顾沉"] or sorted(by_role["character"]) == ["陈磊", "顾沉"]
    # 剧本拆分出的每个地点都建场景资产（走廊只出现一次，也要有），不再要求“出现 2 次”
    assert sorted(by_role["scene"]) == sorted(["宴会厅（夜）", "走廊"])
    assert by_role["prop"] == ["工牌"]
    candidate_names = {c["name"] for c in result["candidates"]}
    assert {"咖啡杯", "自动售货机"} <= candidate_names
    assert "走廊" not in candidate_names and "虚构物" not in candidate_names


def test_prop_repeated_in_text_without_scene_overlap_is_kept(stubs):
    stubs.state["triage"] = triage_payload(props=[{"name": "工牌", "scene_ids": ["1"], "prompt": "蓝色工牌"}], scenes=[])
    result = run()
    assert [a["name"] for a in result["assets"] if a["role"] == "prop"] == ["工牌"]


def test_model_cannot_exceed_caps(stubs):
    many = [{"name": f"宴会厅{i}", "scene_ids": ["1", "3"], "prompt": "p"} for i in range(9)]
    text = SCRIPT + "".join(f"宴会厅{i}" for i in range(9))
    stubs.state["triage"] = triage_payload(scenes=many, props=[])
    result = asyncio.run(analysis.analyze_scene_assets(scenes=SCENES, screenplay_text=text))
    assert len([a for a in result["assets"] if a["role"] == "scene"]) == analysis.MAX_SCENE_ASSETS


def test_character_assets_carry_profile_and_no_style_text(stubs):
    result = run()
    hero = next(a for a in result["assets"] if a["name"] == "顾沉")
    # 画风只由风格参考图（图生图）控制：资产提示词里不再带任何风格行
    assert hero["profile"] == "二十三岁实习生" and "统一视觉风格" not in hero["prompt"]
    assert all("统一视觉风格" not in a["prompt"] for a in result["assets"])
    assert "二十三岁实习生" in stubs.state["character_args"][1]
    assert hero["scene_ids"] == ["1", "2", "3"]


def test_triage_failure_falls_back_to_characters_only(stubs):
    stubs.state["triage"] = RuntimeError("boom")
    result = run()
    # 模型筛选失败时，角色和“剧本拆分出的地点”仍然保证有资产；道具交给分镜提示词
    assert {a["role"] for a in result["assets"]} == {"character", "scene"}
    assert sorted(a["name"] for a in result["assets"] if a["role"] == "scene") == ["宴会厅", "走廊"]
    assert result["candidates"] == [] and any("资产筛选失败" in w for w in result["warnings"])
    assert result["failed_calls"] == 0


def test_character_failure_is_counted_but_scene_and_prop_remain(stubs):
    stubs.state["character_error"] = RuntimeError("boom")
    result = run()
    assert result["failed_calls"] == 1
    assert {a["role"] for a in result["assets"]} == {"scene", "prop"}


def test_nothing_extracted_raises(stubs):
    stubs.state["triage"] = RuntimeError("boom")
    stubs.state["character_error"] = RuntimeError("boom")
    # 有拆分出的地点时场景资产兜底可用，不会整体失败；既没角色也没地点才算“什么都没提取到”
    with pytest.raises(UpstreamServiceError):
        asyncio.run(analysis.analyze_scene_assets(scenes=[scene("1", "", [])], screenplay_text=""))


def test_every_split_location_becomes_a_scene_asset_and_similar_names_merge(stubs):
    """拆分出 7 个场景：古道、周府东院、珍宝阁、周府书房外、东院、周府门外、山中茅舍——东院与周府东院是同一处，其余各一个。"""
    scenes = [
        scene("1", "古道", ["周万贯"], "周万贯下车"), scene("2", "周府东院", ["周万贯", "周氏"], "东院夜话"),
        scene("3", "珍宝阁", ["周万贯"], "挑选珍宝"), scene("4", "周府书房外", ["周氏"], "书房外偷听"),
        scene("5", "东院", ["周氏"], "回到东院"), scene("6", "周府门外", ["周万贯"], "门外送客"), scene("7", "山中茅舍", ["周万贯"], "茅舍避雨"),
    ]
    stubs.state["triage"] = triage_payload(scenes=[{"name": "周府东院", "scene_ids": ["2", "5"], "prompt": "东院夜景"}], props=[], optional=[])
    result = asyncio.run(analysis.analyze_scene_assets(scenes=scenes, screenplay_text="周万贯：走。\n周氏：慢着。"))

    names = sorted(a["name"] for a in result["assets"] if a["role"] == "scene")
    assert names == sorted(["古道", "周府东院", "珍宝阁", "周府书房外", "周府门外", "山中茅舍"])
    east = next(a for a in result["assets"] if a["name"] == "周府东院")
    assert east["scene_ids"] == ["2", "5"] and east["prompt"] == "东院夜景"
    # 模型没写的地点用拆分信息兜底出提示词
    ancient = next(a for a in result["assets"] if a["name"] == "古道")
    assert "古道" in ancient["prompt"] and "周万贯下车" in ancient["prompt"] and ancient["scene_ids"] == ["1"]
    assert not [c for c in result["candidates"] if c["role"] == "scene"]


def test_scene_assets_are_capped_and_overflow_is_not_silently_lost(stubs):
    scenes = [scene(str(i), f"地点{chr(0x4e00 + i)}{chr(0x4e10 + i)}", ["顾沉"], f"第{i}场") for i in range(analysis.MAX_SCENE_ASSETS + 3)]
    stubs.state["triage"] = triage_payload(scenes=[], props=[], optional=[])
    result = asyncio.run(analysis.analyze_scene_assets(scenes=scenes, screenplay_text="顾沉：走。"))
    assert len([a for a in result["assets"] if a["role"] == "scene"]) == analysis.MAX_SCENE_ASSETS


CHAPTER_TEXT = "周万贯：小娘子，天色将晚。\n周氏：你个杀千刀的！\n账房：老爷息怒。\n周万贯摔账册。周氏赶来，哭喊着。\n周万贯：滚！\n"


def test_action_suffixed_names_are_merged_into_the_real_character():
    from services.screenplay_adapt import clean_character_names

    cleaned = clean_character_names(["周万贯", "周万贯摔账册", "周氏", "周氏赶来", "账房"], CHAPTER_TEXT)
    assert cleaned == ["周万贯", "周氏", "账房"]
    # 角色表里没有本名、只有“人名+动作”时，用剧本里单独出现过的前缀还原
    assert clean_character_names(["周氏赶来", "周万贯摔账册"], CHAPTER_TEXT) == ["周氏", "周万贯"]
    # 真正的不同角色不受影响
    assert clean_character_names(["萧炎", "萧薰儿", "测验员（漠然）", "测验员"], "") == ["萧炎", "萧薰儿", "测验员"]
    assert clean_character_names(["周", "周管事"], "周：来人。\n周管事：老爷。\n") == ["周管事"] or "周管事" in clean_character_names(["周管事", "周氏"], "周管事：老爷。\n周氏：嗯。\n")


def test_analysis_does_not_create_assets_for_action_suffixed_names(stubs):
    scenes = [
        scene("1", "古道", ["周万贯", "周万贯摔账册"], "周万贯摔账册"),
        scene("2", "周府东院", ["周氏", "周氏赶来", "账房"], "周氏赶来"),
    ]
    stubs.state["triage"] = triage_payload(characters=[], scenes=[], props=[], optional=[])
    result = asyncio.run(analysis.analyze_scene_assets(scenes=scenes, screenplay_text=CHAPTER_TEXT))

    names = sorted(a["name"] for a in result["assets"] if a["role"] == "character")
    assert names == sorted(["周万贯", "周氏", "账房"])
    assert not [a for a in result["assets"] if "摔" in a["name"] or "赶来" in a["name"]]


def test_scene_titles_always_carry_the_location_but_named_titles_are_kept():
    from services.screenplay_adapt import normalize_scene_titles

    scenes = normalize_scene_titles([
        {"scene_id": 1, "title": "场景1", "location": "古道"},
        {"scene_id": 2, "title": "", "location": "周府东院"},
        {"scene_id": 3, "title": "场次 3", "location": "珍宝阁"},
        {"scene_id": 4, "title": "场景4: 周府书房", "location": "周府书房"},
        {"scene_id": 5, "title": "夜袭", "location": "山间茅舍"},
        {"scene_id": 6, "title": "场景6", "location": ""},
    ])
    assert [s["title"] for s in scenes] == ["场景1: 古道", "场景 2: 周府东院", "场次 3: 珍宝阁", "场景4: 周府书房", "夜袭", "场景6"]
