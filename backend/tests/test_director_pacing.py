"""导演收口（灵活剪切模式）：合并碎镜头 + 按内容收紧时长，故事必须完整、不灌水。"""

import asyncio
import json
from copy import deepcopy

from services import canvas_director_quality as q
from services import video_canvas_director as director
from services.canvas_creative_guide import DIRECTOR_PLANNING_GUIDE, DIRECTOR_SHOT_GUIDE, craft_warnings

OPTIONS = list(range(4, 16))
POLICY = {"version": 3, "model_id": None, "duration_options": OPTIONS, "shot_duration_mode": "flexible", "reference_mode": "clean_single_frame"}


def beat(i, action="", dialogue=None, importance="medium"):
    return {"beat_id": i, "type": "action", "importance": importance, "action": action, "dialogue": dialogue or []}


def unit(seq, ids, seconds, **extra):
    return {"unit_id": f"u{seq}", "sequence": seq, "beat_ids": ids, "duration_seconds": seconds, "title": f"镜头{seq}",
            "story_summary": f"摘要{seq}", "narrative_purpose": f"推进{seq}", "continuity": {"from_previous": "", "to_next": f"留给{seq + 1}", "anchor": ""},
            "transition_out": f"出{seq}", "closing_shot_scale": "近景", **extra}


def scenes_fixture():
    return [
        {"scene_id": 1, "beats": [beat(1, "他推门。"), beat(2, "她抬头。"), beat(3, "他坐下。"), beat(4, "她倒茶。")]},
        {"scene_id": 2, "beats": [beat(1, "走廊安静。")]},
    ]


def test_content_seconds_is_never_tighter_than_the_validator_and_counts_comma_joined_actions():
    two_actions = [beat(1, "破镜映出他蓬头垢面，他猛将镜子踢碎。")]
    assert q.minimum_seconds(two_actions) == 3        # 校验口径把逗号连着的两个动作算成一个
    assert q._content_seconds(two_actions) == 5        # 收口估算多留一个动作分句的时间
    talky = [beat(1, "", ["甲：" + "你" * 35])]
    assert q._content_seconds(talky) == q.minimum_seconds(talky) == 10
    for beats in ([beat(1, "他推门。")], two_actions, talky):
        assert q._content_seconds(beats) >= q.minimum_seconds(beats)


def test_merge_combines_adjacent_short_units_in_the_same_scene_only():
    scenes = scenes_fixture()
    plan = {"units": [unit(1, ["1.1"], 8), unit(2, ["1.2"], 8), unit(3, ["1.3"], 8), unit(4, ["1.4"], 8), unit(5, ["2.1"], 8)]}

    removed = q.merge_short_units(plan, scenes, OPTIONS)

    groups = [u["beat_ids"] for u in plan["units"]]
    assert removed >= 1
    assert [k for group in groups for k in group] == ["1.1", "1.2", "1.3", "1.4", "2.1"], "节拍顺序不变、一个不少"
    assert ["2.1"] in groups, "不同分场绝不合并"
    assert [u["sequence"] for u in plan["units"]] == list(range(1, len(plan["units"]) + 1))
    merged = plan["units"][0]
    assert len(merged["beat_ids"]) >= 2 and "摘要1" in merged["story_summary"] and "摘要2" in merged["story_summary"]
    assert merged["transition_out"] == f"出{len(merged['beat_ids'])}", "收尾衔接取最后一个被合并镜头的"
    beats = [b for b in scenes[0]["beats"] if f"1.{b['beat_id']}" in merged["beat_ids"]]
    assert merged["duration_seconds"] >= q.minimum_seconds(beats)


def test_merge_never_swallows_climax_beats_or_hard_cuts():
    scenes = [{"scene_id": 1, "beats": [beat(1, "他推门。"), beat(2, "她转身。", importance="high"), beat(3, "他后退。"), beat(4, "她追上。")]}]
    plan = {"units": [unit(1, ["1.1"], 8), unit(2, ["1.2"], 8), unit(3, ["1.3"], 8, transition_technique="遮挡转场"), unit(4, ["1.4"], 8)]}

    removed = q.merge_short_units(plan, scenes, OPTIONS)

    # 1.2 是高潮节拍不合并；1.3 用了刻意的硬切，不并入上一镜；1.3 与 1.4 之间没有硬切，可以合并
    assert [u["beat_ids"] for u in plan["units"]] == [["1.1"], ["1.2"], ["1.3", "1.4"]] and removed == 1


def test_merge_respects_capacity_long_narration_and_single_option_models():
    long_line = "旁白：" + "字" * 55
    scenes = [{"scene_id": 1, "beats": [beat(1, "他看着窗外。"), beat(2, "", [long_line]), beat(3, "他叹气。")]}]
    plan = {"units": [unit(1, ["1.1"], 6), unit(2, ["1.2"], 15), unit(3, ["1.3"], 6)]}

    assert q.merge_short_units(plan, scenes, OPTIONS) == 0
    assert q.merge_short_units({"units": [unit(1, ["1.1"], 8)]}, scenes, [15]) == 0


def test_tighten_only_shortens_padded_units_and_never_goes_below_content():
    scenes = [{"scene_id": 1, "beats": [beat(1, "他推门。"), beat(2, "", ["甲：" + "你" * 35]), beat(3, "他笑了。")]}]
    plan = {"units": [unit(1, ["1.1"], 10), unit(2, ["1.2"], 15), unit(3, ["1.3"], 4)]}

    result = q.tighten_durations(plan, scenes, OPTIONS)

    durations = [u["duration_seconds"] for u in plan["units"]]
    assert durations[0] == 4                         # 内容 3 秒 → 4 秒
    assert 10 <= durations[1] <= 13                  # 35 字对白需 10 秒，留约 30% 呼吸，不能压到 10 秒以下
    assert durations[2] == 4                         # 原本就合适，不改
    assert result["count"] == 2 and result["saved"] == (10 - 4) + (15 - durations[1])
    assert "已收紧" in plan["units"][0]["duration_reason"]
    for u in plan["units"]:
        beats = [b for b in scenes[0]["beats"] if f"1.{b['beat_id']}" in u["beat_ids"]]
        assert u["duration_seconds"] >= q.minimum_seconds(beats)


def test_tighten_never_lengthens_and_skips_single_option_models():
    scenes = scenes_fixture()
    plan = {"units": [unit(1, ["1.1"], 15)]}
    assert q.tighten_durations(plan, scenes, [15]) == {"count": 0, "saved": 0}
    assert plan["units"][0]["duration_seconds"] == 15
    short = {"units": [unit(1, ["1.1"], 4)]}
    q.tighten_durations(short, scenes, OPTIONS)
    assert short["units"][0]["duration_seconds"] == 4


def _fake_model(padding):
    async def fake(*, system, user, api_key=None, max_tokens=None):
        data = json.loads(user)
        if "本次只输出这些unit_id" in data:
            ids = data["本次只输出这些unit_id"]
            out = []
            for u in data["完整导演交接"]["units"]:
                if u["unit_id"] in ids:
                    out.append({"unit_id": u["unit_id"], "storyboard_prompt": "干净单帧构图：人物站位朝向清晰，光线柔和，动作即将开始。",
                                "storyboard_json": {"segments": [{"start_second": 0, "end_second": u["duration_seconds"], "visual_action": "动作推进", "camera_direction": "中景固定",
                                                                   "start_state": "起", "end_state": "止", "dialogue_or_narration": u["dialogue_or_narration"]}]}})
            return {"units": out}
        units, n = [], 0
        for scene in data["完整源场景"]:
            for b in scene["beats"]:
                n += 1
                units.append({"unit_id": f"u{n}", "sequence": n, "beat_ids": [f"{scene['scene_id']}.{b['beat_id']}"], "scene_ids": [scene["scene_id"]], "title": f"镜头{n}",
                              "narrative_purpose": "推进", "story_summary": f"摘要{n}", "duration_seconds": padding, "duration_reason": "含特效与反应",
                              "transition_in": "开场" if n == 1 else "承接", "transition_out": "交给下一镜", "transition_technique": "" if n == 1 else "景别递进",
                              "opening_shot_scale": "中景", "closing_shot_scale": "近景", "continuity": {"from_previous": "承", "to_next": "接", "anchor": "锚"}})
        return {"pacing_strategy": "测试", "units": units}
    return fake


def test_direct_pipeline_compacts_a_padded_plan_without_losing_story(monkeypatch):
    scenes = [
        {"scene_id": 1, "beats": [beat(1, "他推门。"), beat(2, "她抬头。"), beat(3, "他坐下。"), beat(4, "她倒茶。"), beat(5, "他喝茶。"), beat(6, "她微笑。")]},
        {"scene_id": 2, "beats": [beat(1, "", ["甲：" + "你" * 30]), beat(2, "他点头。")]},
    ]
    monkeypatch.setattr(director, "_call_deepseek_json", _fake_model(10))

    plan = asyncio.run(q.direct(deepcopy(scenes), POLICY, api_key=None))

    assert plan["total_duration_seconds"] < 80 * 0.7
    assert len(plan["units"]) < 8
    covered = [k for u in plan["units"] for k in u["beat_ids"]]
    assert covered == [f"1.{i}" for i in range(1, 7)] + ["2.1", "2.2"], "节拍顺序不变、一个不少"
    assert q.validate_plan(plan, scenes, POLICY, require_shots=True) == []
    index = q.source_index(scenes, 15)
    for u in plan["units"]:
        need = q.minimum_seconds([index[k][1] for k in u["beat_ids"]])
        assert u["duration_seconds"] >= need
        assert len({index[k][0]["scene_id"] for k in u["beat_ids"]}) == 1
    notes = " ".join(plan["warnings"])
    assert "合并" in notes and "收紧" in notes
    assert "甲：" + "你" * 30 in "\n".join(u["dialogue_or_narration"] for u in plan["units"]), "对白原文完整保留"


def test_direct_keeps_the_models_plan_when_pacing_pass_would_break_validation(monkeypatch):
    scenes = [{"scene_id": 1, "beats": [beat(1, "他推门。"), beat(2, "她抬头。")]}]
    monkeypatch.setattr(director, "_call_deepseek_json", _fake_model(8))
    original_validate = q.validate_plan
    original_tighten = q.tighten_durations
    state = {"armed": False}

    def arming_tighten(plan, scenes_, options):
        state["armed"] = True
        return original_tighten(plan, scenes_, options)

    def flaky_validate(raw, scenes_, policy, **kwargs):
        # 收口之后的那一次整体校验模拟失败，应当回退到模型原方案
        if state["armed"] and not kwargs.get("require_shots") and not kwargs.get("partial"):
            state["armed"] = False
            return ["模拟失败"]
        return original_validate(raw, scenes_, policy, **kwargs)

    monkeypatch.setattr(q, "validate_plan", flaky_validate)
    monkeypatch.setattr(q, "tighten_durations", arming_tighten)

    plan = asyncio.run(q.direct(deepcopy(scenes), POLICY, api_key=None))

    assert [u["duration_seconds"] for u in plan["units"]] == [8, 8], "收口失败就保留模型原方案"
    assert not any("已按内容节奏收紧" in w for w in plan["warnings"])


def test_guides_align_with_the_code_rules_and_no_longer_encourage_padding():
    assert "时长必须有差异" not in DIRECTOR_PLANNING_GUIDE
    for phrase in ("不要把动作秒数和对白秒数相加", "多留约30%", "不得为它们额外加时长", "故事完整优先"):
        assert phrase in DIRECTOR_PLANNING_GUIDE
    assert "不额外延长单元时长" in DIRECTOR_SHOT_GUIDE and "不超过6秒" in DIRECTOR_SHOT_GUIDE


def test_craft_warnings_flag_very_long_single_segments():
    long_unit = {"sequence": 7, "duration_seconds": 12, "storyboard_json": {"segments": [{"start_second": 0, "end_second": 2, "camera_direction": "a"}, {"start_second": 2, "end_second": 12, "camera_direction": "b"}]}}
    assert any("镜头 7 的第 2 段长达 10 秒" in w for w in craft_warnings({"units": [long_unit]}))
    ok = {"sequence": 1, "duration_seconds": 6, "storyboard_json": {"segments": [{"start_second": 0, "end_second": 3}, {"start_second": 3, "end_second": 6}]}}
    assert not any("长达" in w for w in craft_warnings({"units": [ok]}))
    # 台词本身就很长（约 9 秒语速）的单段不算“慢推凑时长”
    talky = {"sequence": 2, "duration_seconds": 12, "storyboard_json": {"segments": [{"start_second": 0, "end_second": 12, "dialogue_or_narration": "甲：" + "你" * 38}]}}
    assert not any("长达" in w for w in craft_warnings({"units": [talky]}))


# ── 超容量拆分：每个部分要有自己的摘要与衔接；时间轴只保留本镜台词；台词顺序必须与原文一致 ─────────────

def _talky_scene():
    a = "甲：" + "你" * 50
    b = "乙：" + "我" * 50
    return [{"scene_id": 1, "beats": [beat(1, "", [a]), beat(2, "", [b])]}], a, b


def test_split_parts_get_their_own_summary_title_and_transitions():
    scenes, a, b = _talky_scene()
    plan = {"units": [{**unit(1, ["1.1", "1.2"], 15), "title": "对峙", "story_summary": "甲乙争执的全部内容",
                       "transition_in": "开场", "transition_out": "收束", "continuity": {"from_previous": "原承接", "to_next": "原留给下一镜", "anchor": ""}}]}

    q.repair_units(plan, scenes, OPTIONS)

    first, second = plan["units"]
    assert (first["unit_id"], second["unit_id"]) == ("u1", "u1_2")
    assert first["title"] == "对峙（1/2）" and second["title"] == "对峙（2/2）"
    assert a.split("：", 1)[1][:10] in first["story_summary"] and b.split("：", 1)[1][:10] not in first["story_summary"]
    assert b.split("：", 1)[1][:10] in second["story_summary"] and a.split("：", 1)[1][:10] not in second["story_summary"]
    assert first["transition_in"] == "开场" and "同一场戏连续进行" in second["transition_in"]
    assert "同一场戏继续" in first["transition_out"] and second["transition_out"] == "收束"
    assert first["continuity"]["from_previous"] == "原承接" and second["continuity"]["to_next"] == "原留给下一镜"
    assert first["duration_reason"] == second["duration_reason"] == "按本镜自己的节拍内容量取档位"
    assert second["transition_technique"], "拆出的后半段也要有转场手法，避免被提示缺少转场"


def test_unsplit_units_keep_their_original_metadata():
    scenes = scenes_fixture()
    plan = {"units": [{**unit(1, ["1.1", "1.2", "1.3", "1.4"], 12), "title": "原标题", "story_summary": "原摘要"}, unit(2, ["2.1"], 4)]}

    q.repair_units(plan, scenes, OPTIONS)

    assert [u["unit_id"] for u in plan["units"]] == ["u1", "u2"]
    assert plan["units"][0]["title"] == "原标题" and plan["units"][0]["story_summary"] == "原摘要"


def _segment(start, end, dialogue=""):
    return {"start_second": start, "end_second": end, "visual_action": "动作", "camera_direction": "中景固定", "start_state": "起", "end_state": "止", "dialogue_or_narration": dialogue}


def test_timeline_repair_strips_dialogue_that_belongs_to_other_units():
    scenes, a, b = _talky_scene()
    plan = {"units": [{**unit(1, ["1.1"], 15), "storyboard_json": {"segments": [_segment(0, 8, a), _segment(8, 15, b)]}},
                      {**unit(2, ["1.2"], 15), "storyboard_json": {"segments": [_segment(0, 15, b)]}}]}

    q.repair_shot_timelines(plan, scenes, OPTIONS)

    first_text = "\n".join(s["dialogue_or_narration"] for s in plan["units"][0]["storyboard_json"]["segments"])
    assert a in first_text and b not in first_text, "本镜时间轴里不能出现下一镜的台词"
    assert b in plan["units"][1]["storyboard_json"]["segments"][0]["dialogue_or_narration"]


def test_validate_plan_rejects_dialogue_out_of_source_order():
    scenes = [{"scene_id": 1, "beats": [beat(1, "", ["甲：先说这句话。"]), beat(2, "", ["乙：再说这句话。"])]}]
    shots = {"storyboard_prompt": "干净单帧构图：人物站位朝向清晰，光线柔和，动作即将开始。"}

    def plan_with(first, second):
        return {"units": [{**unit(1, ["1.1", "1.2"], 6), **shots, "storyboard_json": {"segments": [_segment(0, 3, first), _segment(3, 6, second)]}}]}

    ok = q.validate_plan(plan_with("甲：先说这句话。", "乙：再说这句话。"), scenes, POLICY, require_shots=True)
    bad = q.validate_plan(plan_with("乙：再说这句话。", "甲：先说这句话。"), scenes, POLICY, require_shots=True)

    assert ok == []
    assert any("台词顺序与原文不一致" in e for e in bad)


def test_descriptive_long_sentence_is_not_counted_as_a_chain_of_actions():
    reveal = [beat(1, "镜丝低头，铜镜发亮，镜中映出明亮屋子，两碗热粥，桌边坐着苏砚和她自己。")]
    assert q._content_seconds(reveal) == 5, "多分句只多留 2 秒，不逐句累加"
    assert q._content_seconds([beat(1, "他推门。")]) == 3


def test_scene_split_does_not_cut_through_a_question_and_its_answer():
    from services.screenplay_adapt import _cut_points, _cuts_dialogue_thread

    # 30 个节拍：动作 / 问 / 答 交替；中心附近 (14~16) 是一问一答，其两侧是动作
    lines, beats, position = [], [], 0
    for i in range(1, 31):
        if i in (14, 15):
            text, dialogue = ("镜丝：你为何给我？" if i == 14 else "苏砚：因为你是客。"), [("镜丝：你为何给我？" if i == 14 else "苏砚：因为你是客。")]
        else:
            text, dialogue = f"他做了第{i}个动作。", []
        beats.append({"beat_id": i, "action": "" if dialogue else text, "dialogue": dialogue, "source_start": position, "source_end": position + len(text)})
        lines.append(text)
        position += len(text) + 1
    content = "\n".join(lines)

    cuts = _cut_points(beats, content)

    assert cuts and all(not _cuts_dialogue_thread(beats, i) for i in cuts)
    assert 15 not in cuts, "不能切在“你为何给我？”和“因为你是客。”之间"


# ── 固定 15 秒：超容量拆分时按内容均衡，不留一两句台词的尾巴镜头 ─────────────────────────

def _lines_scene():
    # 对白时长（3.5 字/秒）：8.6、1.1、3.7、4.0 秒 + 开头 3 秒动作
    return [{"scene_id": 1, "beats": [beat(1, "账房跪地捧账册。"), beat(2, "", ["账：" + "字" * 30]), beat(3, "", ["夺：" + "字" * 4]), beat(4, "", ["周：" + "字" * 13]), beat(5, "", ["挥：" + "字" * 14])]}]


def test_balanced_partition_beats_greedy_for_overflowing_scene():
    scenes = _lines_scene()
    index = q.source_index(scenes, 15)
    keys = list(index)

    parts = q._balanced_partition(keys, index, 2, q.FIXED_FILL_CAP)

    seconds = [q.minimum_seconds([index[k][1] for k in p]) for p in parts]
    assert [k for p in parts for k in p] == keys, "节拍顺序不变、不丢不重"
    assert max(seconds) <= q.FIXED_FILL_CAP and min(seconds) >= 8, "两段都有戏，没有只剩一句台词的尾巴"
    assert q._balanced_partition(keys, index, 1, 13) is None and q._balanced_partition(keys, index, 6, 13) is None


def test_balanced_partition_prefers_not_to_cut_inside_a_dialogue_thread():
    scenes = [{"scene_id": 1, "beats": [beat(1, "他进门。"), beat(2, "", ["甲：" + "字" * 14]), beat(3, "", ["乙：" + "字" * 14]), beat(4, "他转身。"), beat(5, "", ["甲：" + "字" * 14]), beat(6, "", ["乙：" + "字" * 14])]}]
    index = q.source_index(scenes, 15)
    keys = list(index)

    parts = q._balanced_partition(keys, index, 2, 13)

    # 唯一不劈开问答的切点是第 3 / 4 个节拍之间（动作处）
    assert parts == [["1.1", "1.2", "1.3"], ["1.4", "1.5", "1.6"]]


def test_repair_units_with_balance_cap_avoids_the_thin_tail_unit():
    scenes = _lines_scene()
    plan = {"units": [{**unit(1, ["1.1", "1.2", "1.3", "1.4", "1.5"], 15), "title": "书房争执"}]}
    greedy = deepcopy(plan)

    q.repair_units(greedy, scenes, [15])
    q.repair_units(plan, scenes, [15], balance_cap=q.FIXED_FILL_CAP)

    index = q.source_index(scenes, 15)
    contents = lambda p: [q.minimum_seconds([index[k][1] for k in u["beat_ids"]]) for u in p["units"]]
    assert min(contents(greedy)) < 5, "贪心拆分会留下约 4 秒的尾巴"
    assert len(plan["units"]) == 2 and min(contents(plan)) >= 8
    assert [u["title"] for u in plan["units"]] == ["书房争执（1/2）", "书房争执（2/2）"]


def test_tidy_after_pacing_drops_orphan_split_suffix_and_stale_counts():
    plan = {"pacing_strategy": "节奏紧凑，转折即切。全剧共33个单元，总时长约294秒。", "units": [
        {"title": "荒郊立约（2/2）"}, {"title": "破镜踢碎（1/2）"}, {"title": "破镜踢碎（2/2）"}, {"title": "普通标题"}]}

    q.tidy_after_pacing(plan)

    assert [u["title"] for u in plan["units"]] == ["荒郊立约", "破镜踢碎（1/2）", "破镜踢碎（2/2）", "普通标题"]
    assert "33个单元" not in plan["pacing_strategy"] and plan["pacing_strategy"].startswith("节奏紧凑，转折即切")
    untouched = {"pacing_strategy": "场景1拆为2个单元。", "units": []}
    q.tidy_after_pacing(untouched)
    assert untouched["pacing_strategy"] == "场景1拆为2个单元。"


# ── 塞得过满的镜头要均衡拆开；拆分后标题统一重新编号 ──────────────────────────────────

def _dense_scene(n=9):
    return [{"scene_id": 1, "beats": [beat(i, f"他做了第{i}个动作。") if i % 2 else beat(i, "", [f"甲：{'字' * 10}"]) for i in range(1, n + 1)]}]


def test_overstuffed_unit_is_split_into_balanced_non_thin_parts():
    scenes = _dense_scene(9)
    keys = [f"1.{i}" for i in range(1, 10)]
    plan = {"units": [{**unit(1, keys, 15), "title": "整场戏", "story_summary": "整场的摘要"}]}

    extra = q.split_overstuffed_units(plan, scenes, OPTIONS)

    index = q.source_index(scenes, 15)
    assert extra >= 1 and len(plan["units"]) == extra + 1
    assert [k for u in plan["units"] for k in u["beat_ids"]] == keys, "节拍顺序不变、一个不少"
    for u in plan["units"]:
        beats = [index[k][1] for k in u["beat_ids"]]
        assert len(u["beat_ids"]) <= q.OVERSTUFF_MAX_BEATS
        assert q._content_seconds(beats) <= 15 * q.OVERSTUFF_FILL + 1e-6
        assert q.minimum_seconds(beats) >= q.THIN_UNIT_SECONDS, "不留过薄的镜头"
        assert u["duration_seconds"] >= q.minimum_seconds(beats)
        assert u["story_summary"] != "整场的摘要", "每个部分写自己的摘要"
    assert len({u["unit_id"] for u in plan["units"]}) == len(plan["units"])
    assert [u["sequence"] for u in plan["units"]] == list(range(1, len(plan["units"]) + 1))


def test_reasonably_sized_units_are_left_alone_by_the_overstuff_guard():
    scenes = scenes_fixture()
    plan = {"units": [unit(1, ["1.1", "1.2", "1.3", "1.4"], 12), unit(2, ["2.1"], 4)]}
    before = deepcopy(plan)

    assert q.split_overstuffed_units(plan, scenes, OPTIONS) == 0
    assert plan == before
    assert q.split_overstuffed_units({"units": [unit(1, [f"1.{i}" for i in range(1, 5)], 15)]}, scenes, [15]) == 0, "单一档位的模型不处理"


def test_direct_pipeline_splits_a_model_plan_that_stuffs_a_whole_scene_into_one_shot(monkeypatch):
    scenes = _dense_scene(9)

    async def fake(*, system, user, api_key=None, max_tokens=None):
        data = json.loads(user)
        if "本次只输出这些unit_id" in data:
            ids = data["本次只输出这些unit_id"]
            return {"units": [{"unit_id": u["unit_id"], "storyboard_prompt": "干净单帧构图：人物站位朝向清晰，光线柔和，动作即将开始。",
                               "storyboard_json": {"segments": [{"start_second": 0, "end_second": u["duration_seconds"], "visual_action": "动作推进", "camera_direction": "中景固定",
                                                                  "start_state": "起", "end_state": "止", "dialogue_or_narration": u["dialogue_or_narration"]}]}}
                              for u in data["完整导演交接"]["units"] if u["unit_id"] in ids]}
        beats = [f"1.{i}" for i in range(1, 10)]
        return {"pacing_strategy": "共1个单元，总时长约15秒。把整场戏合并成一个镜头。", "units": [{
            "unit_id": "u1", "sequence": 1, "beat_ids": beats, "scene_ids": [1], "title": "整场戏", "narrative_purpose": "推进", "story_summary": "整场", "duration_seconds": 15,
            "duration_reason": "塞满", "transition_in": "开场", "transition_out": "收束", "transition_technique": "", "opening_shot_scale": "中景", "closing_shot_scale": "近景",
            "continuity": {"from_previous": "", "to_next": "", "anchor": "锚"}}]}

    monkeypatch.setattr(director, "_call_deepseek_json", fake)

    plan = asyncio.run(q.direct(deepcopy(scenes), POLICY, api_key=None))

    assert len(plan["units"]) >= 2
    assert all(len(u["beat_ids"]) <= q.OVERSTUFF_MAX_BEATS for u in plan["units"])
    assert q.validate_plan(plan, scenes, POLICY, require_shots=True) == []
    assert any("塞得过满" in w for w in plan["warnings"])
    assert "共1个单元" not in plan["pacing_strategy"]
    assert [u["title"] for u in plan["units"]] == [f"整场戏（{i}/{len(plan['units'])}）" for i in range(1, len(plan["units"]) + 1)]


def test_tidy_renumbers_stacked_and_orphan_split_suffixes():
    plan = {"units": [
        {"title": "争产（1/2）（1/2）", "scene_ids": [4]}, {"title": "争产（1/2）（2/2）", "scene_ids": [4]}, {"title": "争产（2/2）", "scene_ids": [4]},
        {"title": "离去（2/2）", "scene_ids": [5]}, {"title": "普通", "scene_ids": [5]}]}

    q.tidy_after_pacing(plan)

    assert [u["title"] for u in plan["units"]] == ["争产（1/3）", "争产（2/3）", "争产（3/3）", "离去", "普通"]


def test_stale_duration_reasons_are_rewritten_to_match_the_final_duration():
    scenes = [{"scene_id": 1, "beats": [beat(1, "", ["甲：" + "你" * 35])]}]
    plan = {"units": [
        {**unit(1, ["1.1"], 11), "duration_reason": "对白10秒，取16秒容纳长句"},     # 理由说 16，实际 11
        {**unit(2, ["1.1"], 12), "duration_reason": "内容约10秒，取12秒"},          # 一致，不动
        {**unit(3, ["1.1"], 12), "duration_reason": "没有写具体秒数"},                # 没有数字，不动
    ]}

    refreshed = q.refresh_stale_duration_reasons(plan, scenes, OPTIONS)

    assert refreshed == 1
    assert plan["units"][0]["duration_reason"] == "内容约 10.0 秒，按内容节奏取 11 秒"
    assert plan["units"][1]["duration_reason"] == "内容约10秒，取12秒" and plan["units"][2]["duration_reason"] == "没有写具体秒数"
