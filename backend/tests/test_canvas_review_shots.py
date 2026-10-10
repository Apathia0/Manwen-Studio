"""分镜质检：镜头数按真实分场统计；时长提示给出合理范围、偏长镜头与可合并的相邻短镜头。"""

from services.canvas_quality_review import _review_storyboard, audit_plan_durations

SCENE_NODE = "scene-1"


def _beat(action: str = "他推门而入。") -> dict:
    return {"beat_id": 1, "type": "action", "action": action, "dialogue": []}


def _unit(seq: int, seconds: float, scene_id: int = 1) -> dict:
    return {
        "unit_id": f"U{seq}", "sequence": seq, "title": f"镜头{seq}", "duration_seconds": seconds, "scene_ids": [scene_id],
        "source_beats": [{"source_id": f"{scene_id}.{seq}", "beat": _beat()}],
    }


def _graph(units, *, scene_ids_per_unit=None, policy=None):
    scene = {"id": SCENE_NODE, "type": "scene", "data": {"label": "剧本场景", "config": {
        "approved": True, "scenes": [],
        "director_plan": {"units": units, "production_policy": policy or {"duration_options": list(range(4, 16)), "shot_duration_mode": "flexible"}},
    }}}
    videos = []
    for index, unit in enumerate(units):
        scene_ids = (scene_ids_per_unit[index] if scene_ids_per_unit else unit["scene_ids"])
        videos.append({"id": f"video-{index}", "type": "video", "data": {"label": f"视频{index}", "config": {
            "unit_id": unit["unit_id"], "prompt": "p", "source_scene_node": SCENE_NODE, "source_scene_ids": scene_ids,
            "duration_seconds": unit["duration_seconds"],
        }}})
    return [scene, *videos], []


def _codes(issues, code):
    return [i for i in issues if i["code"] == code]


def test_shots_are_counted_per_real_scene_not_per_scene_node():
    # 30 个镜头分在 8 个分场里（每个不超过 6 个）：不能报“一个场景被拆成 30 个镜头”
    units = [_unit(i + 1, 6, scene_id=i % 8 + 1) for i in range(30)]
    nodes, edges = _graph(units)

    assert _codes(_review_storyboard(nodes, edges), "too_many_shots") == []


def test_a_real_scene_with_too_many_shots_is_flagged_with_its_number_and_shot_nodes():
    units = [_unit(i + 1, 6, scene_id=3) for i in range(13)] + [_unit(14 + i, 6, scene_id=4) for i in range(3)]
    nodes, edges = _graph(units)

    issues = _codes(_review_storyboard(nodes, edges), "too_many_shots")

    assert len(issues) == 1
    assert "分场 3" in issues[0]["message"] and "13 个镜头" in issues[0]["message"]
    assert issues[0]["node_ids"][0] == "video-0", "定位到该分场的镜头节点，而不是整个场景节点"


def test_duration_hint_has_range_over_allocated_shots_and_merge_pairs():
    units = [_unit(i + 1, 8) for i in range(8)]            # 每个镜头内容只需 3 秒，却给了 8 秒
    units[2]["duration_seconds"] = 14                        # 个别镜头更夸张
    nodes, edges = _graph(units)

    issues = _codes(_review_storyboard(nodes, edges), "duration_inflated")

    assert len(issues) == 1
    message = issues[0]["message"]
    assert "合理范围约" in message and "偏长约" in message
    assert "第 3 镜「镜头3」14 秒（内容约 3 秒）" in message      # 偏长最多的排最前
    assert "可合并的相邻短镜头：" in message and "1+2" in message
    assert issues[0]["redo_stage"] == "director"


def test_reasonable_pacing_is_not_flagged():
    units = [_unit(i + 1, 5) for i in range(8)]              # 内容下限 3 秒，给 5 秒（×1.67）在合理范围内
    nodes, edges = _graph(units)

    assert _codes(_review_storyboard(nodes, edges), "duration_inflated") == []


def test_fixed_15_mode_is_expected_to_be_long():
    units = [_unit(i + 1, 15) for i in range(6)]
    nodes, edges = _graph(units, policy={"duration_options": [15], "shot_duration_mode": "fixed15"})

    assert _codes(_review_storyboard(nodes, edges), "duration_inflated") == []


def test_single_duration_model_names_the_cause():
    units = [_unit(i + 1, 15) for i in range(6)]
    nodes, edges = _graph(units, policy={"duration_options": [15], "shot_duration_mode": "flexible"})

    issues = _codes(_review_storyboard(nodes, edges), "duration_inflated")

    assert len(issues) == 1 and "只有 15 秒一档" in issues[0]["message"]


def test_legacy_plans_without_beats_keep_the_overall_ratio_check():
    units = [{"unit_id": f"U{i}", "sequence": i, "title": f"镜头{i}", "duration_seconds": 15, "scene_ids": [1]} for i in range(1, 7)]
    nodes, edges = _graph(units)
    nodes[0]["data"]["config"]["scenes"] = [{"scene_id": 1, "beats": [_beat() for _ in range(6)]}]

    issues = _codes(_review_storyboard(nodes, edges), "duration_inflated")

    assert len(issues) == 1 and "比内容本身需要的约" in issues[0]["message"]


def test_audit_returns_none_when_units_have_no_beat_info():
    assert audit_plan_durations([{"sequence": 1, "duration_seconds": 8}], [4, 15]) is None
    assert audit_plan_durations([], [4, 15]) is None
