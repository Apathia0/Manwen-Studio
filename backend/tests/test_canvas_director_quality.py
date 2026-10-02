"""严格导演前置校验，不调用真实模型。"""

from copy import deepcopy
import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

from services.canvas_director_quality import validate_plan, direct, resolve_policy


POLICY = {"duration_options": [5, 10, 15], "reference_mode": "clean_single_frame"}
SCENES = [{"scene_id": 1, "location": "书房", "visual_anchors": [{"description": "左手有伤"}], "characters": ["甲"], "beats": [{"beat_id": 1, "action": "左手递信", "dialogue": "甲：快走"}]}]


def plan():
    return {"units": [{"unit_id": "u1", "sequence": 1, "scene_ids": [1], "beat_ids": ["1.1"], "duration_seconds": 5, "narrative_purpose": "交出证据改变人物选择", "storyboard_prompt": "书房近景，甲左手握着信件尚未递出，目光朝向门口，侧光照亮面部与手部", "storyboard_json": {"segments": [{"start_second": 0, "end_second": 5, "visual_action": "递出信件", "camera_direction": "固定近景", "start_state": "手握信", "end_state": "信已交出", "dialogue_or_narration": "甲：快走"}]}}]}


def test_valid_continuous_shot_passes():
    assert validate_plan(plan(), SCENES, POLICY, require_shots=True) == []


def test_long_dialogue_cannot_fit_five_seconds():
    scenes = deepcopy(SCENES)
    scenes[0]["beats"][0]["dialogue"] = "甲：" + "我还有重要的话要告诉你" * 5
    assert any("不能塞进" in e for e in validate_plan(plan(), scenes, POLICY))


@pytest.mark.parametrize("refs", [[], ["1.1", "1.1"], ["1.2"]])
def test_invalid_beat_coverage_is_rejected(refs):
    value = plan()
    value["units"][0]["beat_ids"] = refs
    assert validate_plan(value, SCENES, POLICY)


@pytest.mark.parametrize("start", [1, float("nan"), float("inf")])
def test_broken_timeline_is_rejected_not_discarded(start):
    value = plan()
    value["units"][0]["storyboard_json"]["segments"][0]["start_second"] = start
    assert validate_plan(value, SCENES, POLICY, require_shots=True)
    assert value["units"][0]["storyboard_json"] is not None


def test_model_change_revalidates_duration():
    value = plan()
    value["units"][0]["duration_seconds"] = 15
    assert validate_plan(value, SCENES, {"duration_options": [5, 10]})


def test_shot_reverse_shot_between_segments_is_allowed():
    value = plan()
    value["units"][0]["storyboard_json"]["segments"][0]["camera_direction"] = "过肩正反打，先近景后特写"
    assert validate_plan(value, SCENES, POLICY, require_shots=True) == []


def test_cross_space_montage_is_still_rejected():
    value = plan()
    value["units"][0]["storyboard_json"]["segments"][0]["camera_direction"] = "蒙太奇转场到另一地点"
    assert validate_plan(value, SCENES, POLICY, require_shots=True)


def test_craft_warnings_flag_flat_rhythm_and_repeated_camera():
    from services.canvas_creative_guide import craft_warnings
    segment = {"camera_direction": "固定中景"}
    units = [{"duration_seconds": 5, "transition_technique": "动作剪辑", "storyboard_json": {"segments": [dict(segment), dict(segment)]}} for _ in range(3)]
    warnings = craft_warnings({"units": units})
    assert len(warnings) == 2


def test_grid_is_not_a_production_frame():
    value = plan()
    value["units"][0]["storyboard_prompt"] = "一张多格分镜展示板，顶部时间标注，下方对白，横向四格清晰展示动作"
    assert validate_plan(value, SCENES, POLICY, require_shots=True)


@pytest.mark.asyncio
async def test_shot_director_receives_complete_source_and_compiles_timeline(monkeypatch):
    from services import video_canvas_director as old
    calls = []
    async def call(**kwargs):
        calls.append(kwargs)
        return plan()
    monkeypatch.setattr(old, "_call_deepseek_json", call)
    result = await direct(SCENES, POLICY, source_screenplay_hash="s", source_scene_node_id="n", source_scene_revision="r")
    assert "左手递信" in calls[1]["user"] and "左手有伤" in calls[1]["user"] and "书房" in calls[1]["user"]
    assert "0-5秒" in result["units"][0]["video_prompt"]
    assert result["units"][0]["reference_mode"] == "clean_single_frame"


@pytest.mark.parametrize("model_key", ["doubao-seedance-1-0-pro", "seedance-1.5-pro", "cvk-fixed-15"])
def test_director_policy_is_independent_of_the_video_model(model_key):
    # 导演统一按 4~15 秒任意整数秒拆分，不读取视频模型的时长规格（固定 15 秒 / 12 秒上限的模型都一样）
    model = SimpleNamespace(enabled=True, modality="video", model_key=model_key, capabilities_json={"video": {"duration_options": [15]}})
    policy = resolve_policy({"metadata": {"production_settings": {"video_model_id": 3}}}, SimpleNamespace(get=lambda *args: model), model_id=3)
    assert policy["duration_options"] == list(range(4, 16)) and policy["model_id"] is None
    value = plan()
    value["units"][0]["duration_seconds"] = 16
    assert any("档位" in error for error in validate_plan(value, SCENES, policy))


def test_policy_never_queries_the_model_or_the_user_default(monkeypatch):
    from services.ai import resolver

    def boom(*args, **kwargs):
        raise AssertionError("导演策略不应该解析视频模型")

    monkeypatch.setattr(resolver, "resolve_model", boom)
    policy = resolve_policy({}, SimpleNamespace(get=boom), user_id=9)
    assert policy["duration_options"][0] == 4 and policy["duration_options"][-1] == 15


@pytest.fixture
def compile_state(monkeypatch):
    from routers import video_canvas as api

    scene_config = {"approved": True, "scenes": deepcopy(SCENES), "source_screenplay_node": "screenplay", "source_content": "甲左手递信。甲：快走"}
    graph = {"nodes": [
        {"id": "screenplay", "type": "screenplay", "data": {"config": {"content": scene_config["source_content"]}}},
        {"id": "scene", "type": "scene", "data": {"config": scene_config}},
    ], "edges": []}
    _, source_hash, revision = api._scene_screenplay_hashes(graph, scene_config, "scene")
    value = plan()
    value["meta"] = {"source_screenplay_hash": source_hash, "source_scene_revision": revision, "source_scene_node_id": "scene"}
    state = SimpleNamespace(graph=graph, plan=value, config=scene_config)
    monkeypatch.setattr(api, "_require_user", lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(api, "_require_canvas", lambda *args: SimpleNamespace(id=1, definition_revision=2))
    monkeypatch.setattr(api, "_latest_version", lambda *args: SimpleNamespace(graph_json=state.graph))
    return state


def compile_current(state):
    from routers import video_canvas as api
    from schemas import VideoCanvasCompileScenesRequest

    return asyncio.run(api.compile_scenes(1, VideoCanvasCompileScenesRequest(
        scene_node_ids=["scene"], director_plan=state.plan, expected_definition_revision=2, video_model_id=3,
    ), SimpleNamespace(), SimpleNamespace(get=lambda *args: SimpleNamespace(
        enabled=True, modality="video", model_key="test-model", capabilities_json={"video": {"duration_options": [5, 10, 15]}},
    ))))


def test_compile_rebuilds_video_prompt_from_timeline_not_client_text(compile_state):
    state = compile_state
    state.plan["units"][0]["video_prompt"] = "客户端旧提示词：新增爆炸追逐与另一条剧情"
    state.plan["units"][0]["scene_ids"] = [999]
    result = compile_current(state)
    unit = result["compiled"][0]
    assert "客户端旧提示词" not in unit["video_prompt"]
    assert "递出信件" in unit["video_prompt"] and "甲：快走" in unit["video_prompt"]
    assert "0-5秒" in unit["video_prompt"]
    assert unit["source_scene_ids"] == [1]
    assert unit["reference_mode"] == "clean_single_frame"


def test_compile_rejects_plan_from_other_scene_even_if_content_hashes_match(compile_state):
    compile_state.plan["meta"]["source_scene_node_id"] = "other-scene"
    with pytest.raises(HTTPException) as failure:
        compile_current(compile_state)
    assert failure.value.status_code == 422
    assert "场景节点不匹配" in str(failure.value.detail)


def test_continuous_unit_cannot_cover_beats_from_two_scenes():
    scenes = deepcopy(SCENES)
    scenes.append({"scene_id": 2, "beats": [{"beat_id": 1, "action": "车站等待", "dialogue": []}]})
    value = plan()
    value["units"][0].update(beat_ids=["1.1", "2.1"], duration_seconds=10)
    assert any("不能跨越不同场景" in error for error in validate_plan(value, scenes, POLICY))


def test_compile_rejects_cross_scene_timeline(compile_state):
    from routers import video_canvas as api

    state = compile_state
    state.config["scenes"].append({"scene_id": 2, "beats": [{"beat_id": 1, "action": "走进车站", "dialogue": []}]})
    _, source_hash, revision = api._scene_screenplay_hashes(state.graph, state.config, "scene")
    state.plan["meta"].update(source_screenplay_hash=source_hash, source_scene_revision=revision)
    state.plan["units"][0].update(beat_ids=["1.1", "2.1"], duration_seconds=10)
    state.plan["units"][0]["storyboard_json"]["segments"][0]["end_second"] = 10
    with pytest.raises(HTTPException) as failure:
        compile_current(state)
    assert failure.value.status_code == 422
    assert "不能跨越不同场景" in str(failure.value.detail)


@pytest.mark.asyncio
async def test_director_endpoint_uses_the_model_independent_policy(compile_state, monkeypatch):
    from routers import video_canvas as api
    from schemas import VideoCanvasDirectorPlanRequest
    from services import canvas_director_quality as quality

    calls = []

    async def fake_direct(**kwargs):
        calls.append(kwargs)
        return compile_state.plan

    model = SimpleNamespace(enabled=True, modality="video", model_key="seedance-1-0-pro", capabilities_json={})
    monkeypatch.setattr(quality, "direct", fake_direct)
    monkeypatch.setattr(api, "_canvas_deepseek_api_key", lambda *args: "test-key")
    await api.create_director_plan(1, VideoCanvasDirectorPlanRequest(
        scene_node_id="scene", expected_definition_revision=2, video_model_id=3,
    ), SimpleNamespace(), SimpleNamespace(get=lambda *args: model))
    assert calls[0]["policy"]["duration_options"] == list(range(4, 16))
    assert calls[0]["source_scene_node_id"] == "scene"
    assert calls[0]["scenes"] == SCENES


@pytest.mark.parametrize("has_role_metadata", [False, True])
def test_image_runtime_passes_portrait_size_and_named_reference_roles(monkeypatch, tmp_path, has_role_metadata):
    from services import video_canvas_runtime as runtime
    from tests.test_video_canvas_execution_recovery import _execution_fixture, _run

    image_node = {"id": "shot", "type": "image", "data": {"config": {
        "prompt": "角色甲站在书房门边", "aspect_ratio": "9:16", "reference_mode": "clean_single_frame",
        "reference_asset_ids": [10, 11, 12],
    }}}
    run, records, commits, charges, assets = _execution_fixture(monkeypatch, [image_node])
    for identifier, name, role in [(10, "甲", "character"), (11, "书房", "scene"), (12, "信件", "prop")]:
        path = tmp_path / f"reference-{identifier}.png"
        path.write_bytes(b"reference")
        assets[identifier] = SimpleNamespace(
            id=identifier, name=name, story_id=5, status="active", file_path=str(path),
            asset_type=f"{role}_reference", meta_json={"asset_role": role} if has_role_metadata else {},
        )
    captured = []

    async def generate(**kwargs):
        captured.append(kwargs)
        return str(tmp_path / "result.png")

    monkeypatch.setattr(runtime, "MANGA_OUTPUTS", tmp_path)
    monkeypatch.setattr(runtime.image2_service, "generate_reference_image", generate)
    assert _run()["status"] == "succeeded"
    call = captured[0]
    assert call["size"] == "1080x1920"
    assert call["ref_labels"] == ["甲", "书房", "信件"]
    assert call["ref_roles"] == ["character", "scene", "prop"]
    assert call["ref_image_paths"] == [str(tmp_path / f"reference-{identifier}.png") for identifier in [10, 11, 12]]
    assert call["ref_type"] == "storyboard"
    assert "无字幕、无边框、无文字、无分格" in call["prompt"]
    assert records[0].status == "succeeded"


@pytest.mark.asyncio
async def test_director_self_heals_with_a_conservative_plan_when_the_model_keeps_failing(monkeypatch):
    """模型三次都没通过校验：自动按原文分组，不再失败后让用户选择；并在 warnings 里说明。"""
    from services import video_canvas_director as old

    calls = []

    async def invalid(**kwargs):
        calls.append(kwargs)
        value = plan()
        value["units"][0]["narrative_purpose"] = ""
        return value

    monkeypatch.setattr(old, "_call_deepseek_json", invalid)
    result = await direct(SCENES, POLICY)
    assert len(calls) >= 3 and "必须说明镜头" in calls[1]["user"]
    assert validate_plan(result, SCENES, POLICY, require_shots=True) == []
    assert any("自动分组" in w or "自动生成" in w for w in result["warnings"])
    assert result["units"][0]["beat_ids"] == ["1.1"]


@pytest.mark.asyncio
async def test_director_synthesizes_only_the_failing_shot_timelines(monkeypatch):
    from services import video_canvas_director as old

    async def call(**kwargs):
        value = plan()
        if "镜头导演" in kwargs["system"]:
            value["units"][0]["storyboard_json"] = {"segments": []}  # 时间轴永远无效
        return value

    monkeypatch.setattr(old, "_call_deepseek_json", call)
    result = await direct(SCENES, POLICY)
    unit = result["units"][0]
    assert validate_plan(result, SCENES, POLICY, require_shots=True) == []
    assert "甲：快走" in unit["storyboard_json"]["segments"][0]["dialogue_or_narration"]
    assert any("自动生成" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_director_still_fails_loudly_when_even_the_fallback_is_invalid(monkeypatch):
    from services import canvas_director_quality as quality
    from services import video_canvas_director as old
    from services.errors import UpstreamServiceError

    async def invalid(**kwargs):
        value = plan()
        value["units"][0]["narrative_purpose"] = ""
        return value

    monkeypatch.setattr(old, "_call_deepseek_json", invalid)
    monkeypatch.setattr(quality, "synthesize_plan", lambda scenes, policy: {"units": []})
    with pytest.raises(UpstreamServiceError) as failure:
        await direct(SCENES, POLICY)
    assert failure.value.code == "canvas_director_quality_failed"


def test_synthesized_timeline_fits_dense_dialogue_without_inventing_text():
    from services.canvas_director_quality import source_index, synthesize_plan, synthesize_shots

    lines = [f"少年{n}：这位萧炎同学居然真的能测出这样的结果来真是不可思议啊" for n in range(6)]
    scenes = [{"scene_id": 1, "location": "测验广场", "time_of_day": "日", "characters": ["少年"], "beats": [
        {"beat_id": i + 1, "action": "", "dialogue": [line], "source_text": line} for i, line in enumerate(lines)]}]
    policy = {"duration_options": [5, 10, 15], "reference_mode": "clean_single_frame"}
    value = synthesize_plan(scenes, policy)
    assert len(value["units"]) > 1 and validate_plan(value, scenes, policy) == []
    index = source_index(scenes)
    for unit in value["units"]:
        synthesize_shots(unit, index, policy["duration_options"])
    assert validate_plan(value, scenes, policy, require_shots=True) == []
    spoken = "\n".join(seg["dialogue_or_narration"] for unit in value["units"] for seg in unit["storyboard_json"]["segments"])
    assert all(line in spoken for line in lines)


def test_oversized_beat_is_split_losslessly():
    from services.canvas_director_quality import expand_scenes, source_index
    scenes = [{"scene_id": 1, "beats": [{"beat_id": 1, "action": "开门；走到桌前；拿起信；拆开信；读完信；再将信撕碎；扔进火盆", "dialogue": ["甲：" + "我有很重要的话要说" * 3 + "。再听我说" * 4, "乙：好"]}]}]
    expanded = expand_scenes(scenes, 15)
    assert len(expanded[0]["beats"]) > 1
    assert "".join(b["action"] for b in expanded[0]["beats"]) == scenes[0]["beats"][0]["action"]
    assert len(source_index(scenes, 15)) == len(expanded[0]["beats"])


def test_repair_splits_cross_scene_and_raises_duration():
    from services.canvas_director_quality import repair_units
    scenes = [{"scene_id": 1, "beats": [{"beat_id": 1, "action": "开门；走到桌前；拿起信；拆开信；读完"}]}, {"scene_id": 2, "beats": [{"beat_id": 1, "action": "出门"}]}]
    p = {"units": [{"unit_id": "u1", "sequence": 1, "beat_ids": ["1.1", "2.1"], "duration_seconds": 6}]}
    out = repair_units(p, scenes, [5, 10, 15])["units"]
    assert [u["beat_ids"] for u in out] == [["1.1"], ["2.1"]]
    assert out[0]["duration_seconds"] == 15 and out[1]["duration_seconds"] == 5 and out[1]["sequence"] == 2


def test_repair_fixes_omitted_and_out_of_order_beats():
    from services.canvas_director_quality import repair_units, validate_plan
    scenes = [{"scene_id": 1, "beats": [{"beat_id": i, "action": "动作"} for i in (1, 2, 3, 4)]}]
    p = {"units": [{"unit_id": "a", "sequence": 1, "beat_ids": ["1.3", "1.1"], "duration_seconds": 5, "narrative_purpose": "x"},
                   {"unit_id": "b", "sequence": 2, "beat_ids": ["1.4", "1.4"], "duration_seconds": 5, "narrative_purpose": "x"}]}
    out = repair_units(p, scenes, [5, 10, 15])
    assert validate_plan(out, scenes, {"duration_options": [5, 10, 15]}) == []


def test_craft_warnings_flag_jump_cut_and_missing_technique():
    from services.canvas_creative_guide import craft_warnings
    units = [{"unit_id": "u1", "duration_seconds": 5, "closing_shot_scale": "特写"},
             {"unit_id": "u2", "duration_seconds": 8, "opening_shot_scale": "特写"},
             {"unit_id": "u3", "duration_seconds": 10, "opening_shot_scale": "远景", "transition_technique": "景别递进"}]
    text = "；".join(craft_warnings({"units": units}))
    assert "u2缺少转场手法" in text and "u2与上一镜景别相同" in text


def test_repair_shot_timeline_retimes_dialogue_and_restores_missing_lines():
    from services.canvas_director_quality import repair_shot_timelines
    scenes = [{"scene_id": 1, "beats": [{"beat_id": 1, "action": "转身", "dialogue": ["甲：" + "我有话要说" * 4, "乙：好"]}]}]
    seg = lambda a, b, d: {"start_second": a, "end_second": b, "visual_action": "x", "camera_direction": "中景", "start_state": "s", "end_state": "e", "dialogue_or_narration": d}
    p = {"units": [{"unit_id": "u1", "sequence": 1, "beat_ids": ["1.1"], "duration_seconds": 10, "narrative_purpose": "x", "storyboard_prompt": "一个足够长的单帧构图描述，用于校验通过并且超过二十字",
                    "storyboard_json": {"segments": [seg(0, 2, "甲：" + "我有话要说" * 4), seg(2, 10, "")]}}]}
    out = repair_shot_timelines(p, scenes, [5, 10, 15])
    assert validate_plan(out, scenes, {"duration_options": [5, 10, 15]}, require_shots=True) == []


def test_meta_line_is_not_treated_as_dialogue():
    from services.canvas_director_quality import source_index
    scenes = [{"scene_id": 1, "beats": [{"beat_id": 1, "action": "站着", "dialogue": ["一句话梗概：xxx", "甲：走"]}]}]
    assert source_index(scenes, 15)["1.1"][1]["dialogue"] == ["甲：走"]


def test_polish_continuity_breaks_jump_cuts_and_hands_off_state():
    from services.canvas_director_quality import polish_continuity, compile_video_prompt
    seg = lambda cam, a, b: {"start_second": 0, "end_second": 5, "visual_action": "x", "camera_direction": cam, "start_state": a, "end_state": b, "dialogue_or_narration": ""}
    units = [{"unit_id": "u1", "scene_ids": [1], "storyboard_json": {"segments": [seg("中景，固定机位", "s1", "甲转身")]}},
             {"unit_id": "u2", "scene_ids": [1], "storyboard_json": {"segments": [seg("中景，缓慢推进", "乱的", "e2")]}},
             {"unit_id": "u3", "scene_ids": [2], "storyboard_json": {"segments": [seg("近景", "a", "b")]}}]
    plan = {"units": units}
    assert "调整" in polish_continuity(plan)
    assert units[1]["opening_shot_scale"] != units[0]["closing_shot_scale"]
    assert units[1]["storyboard_json"]["segments"][0]["start_state"] == "甲转身"
    assert units[1]["transition_technique"] == "景别递进" and units[2]["transition_technique"] == "时空跳转"
    assert "承接上一镜结尾（甲转身）" in compile_video_prompt(units[1])


@pytest.mark.asyncio
async def test_director_receives_total_duration_budget_and_warns_when_overrun(monkeypatch):
    from services import video_canvas_director as old
    calls = []

    async def call(**kwargs):
        calls.append(kwargs)
        return plan()

    monkeypatch.setattr(old, "_call_deepseek_json", call)
    result = await direct(SCENES, POLICY, user_constraints="日式动漫风。时长约10秒，16:9。")
    assert "参考时长约10秒" in calls[0]["system"] and '"目标总时长秒数": 10' in calls[0]["user"]
    total = sum(unit["duration_seconds"] for unit in result["units"])
    assert result["total_duration_seconds"] == total and result["target_duration_seconds"] == 10
    if total > 40:  # 参考 10 秒的合理上限是 40 秒
        assert any("合理上限 40 秒" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_director_without_target_has_no_budget_rule(monkeypatch):
    from services import video_canvas_director as old
    calls = []

    async def call(**kwargs):
        calls.append(kwargs)
        return plan()

    monkeypatch.setattr(old, "_call_deepseek_json", call)
    result = await direct(SCENES, POLICY, user_constraints="日式动漫风")
    assert "总时长预算" not in calls[0]["system"] and result["target_duration_seconds"] is None
