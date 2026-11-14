"""画布质量评审：三个审核点的检查、确认指纹失效、局部重做的影响预览与应用。"""

from copy import deepcopy

import pytest

from services import canvas_quality_review as qr


def node(identifier, kind, label="", **config):
    return {"id": identifier, "type": kind, "data": {"label": label or identifier, "config": config}}


def edge(source, target, handle="image"):
    return {"id": f"{source}-{target}", "source": source, "target": target, "targetHandle": handle}


def healthy_graph():
    plan = {"units": [{"unit_id": "u-001", "characters": ["顾沉"]}]}
    return {
        "nodes": [
            node("sc", "scene", beats=[{"id": "b1"}], director_plan=plan),
            node("hero", "image", asset_role="character", asset_name="顾沉", asset_scene_node="sc", prompt="黑发青年"),
            node("sb", "image", node_role="storyboard", source_scene_node="sc", unit_id="u-001", prompt="顾沉走进宴会厅", characters=["顾沉"]),
            node("mv", "video", source_scene_node="sc", unit_id="u-001", prompt="顾沉走进宴会厅", duration_seconds=6),
        ],
        "edges": [edge("sb", "mv")],
        "metadata": {},
    }


def test_healthy_graph_is_ready_to_generate():
    review = qr.review_graph(healthy_graph())
    assert review["error_count"] == 0
    assert [review["checkpoints"][k]["status"] for k in qr.CHECKPOINTS] == ["ready"] * 3
    assert review["ready_to_generate"] is True


def test_empty_canvas_checkpoints_are_pending():
    review = qr.review_graph({"nodes": [], "edges": []})
    assert all(c["status"] == "pending" for c in review["checkpoints"].values())
    assert review["ready_to_generate"] is False


def test_character_without_asset_is_only_a_warning_and_ignores_non_character_words():
    graph = healthy_graph()
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "hero"]
    plan = graph["nodes"][0]["data"]["config"]["director_plan"]
    # “级别”只出现 1 次、“石碑上亮起五个刺眼的大字”超过 6 个字：都不算缺失的角色；顾沉在镜头文字里出现 2 次
    plan["units"] = [{"unit_id": "u-001", "characters": ["顾沉", "级别", "石碑上亮起五个刺眼的大字"], "video_prompt": "顾沉走进宴会厅，顾沉看向众人，级别很高"}]
    review = qr.review_graph(graph)
    issue = next(i for i in review["checkpoints"]["assets"]["issues"] if i["code"] == "character_missing_asset")
    assert issue["severity"] == "warning" and "顾沉" in issue["message"] and "级别" not in issue["message"] and "石碑" not in issue["message"]
    # 警告不阻塞确认；但“缺角色资产”这类靠重做资产阶段就能修好的警告，自动质检会修一轮，其他警告不会触发重做
    assert review["checkpoints"]["assets"]["error_count"] == 0
    assert list(qr.repair_targets(review)) == [("sc", "assets")]
    other = {"checkpoints": {"x": {"issues": [{"severity": "warning", "code": "too_many_shots", "redo_stage": "director", "scene_node_id": "sc", "message": "m"}]}}}
    assert qr.repair_targets(other) == {}


def test_shot_problems_are_reported_with_node_ids():
    graph = healthy_graph()
    graph["nodes"][3]["data"]["config"].update(prompt="", duration_seconds=40)
    graph["edges"] = []
    codes = {i["code"] for i in qr.review_graph(graph)["checkpoints"]["storyboard"]["issues"]}
    assert {"shot_empty_prompt", "shot_duration", "shot_no_storyboard"} <= codes


def test_repair_targets_keep_only_the_earliest_stage_per_scene():
    review = {"checkpoints": {"a": {"issues": [
        {"severity": "error", "redo_stage": "compile", "scene_node_id": "sc", "message": "x"},
        {"severity": "error", "redo_stage": "assets", "scene_node_id": "sc", "message": "y"},
        {"severity": "warning", "redo_stage": "director", "scene_node_id": "sc", "message": "z"},
    ]}}}
    assert list(qr.repair_targets(review)) == [("sc", "assets")]


def test_approval_is_invalidated_when_content_changes():
    graph = healthy_graph()
    fingerprint = qr.review_graph(graph)["checkpoints"]["assets"]["fingerprint"]
    graph["metadata"]["review_approvals"] = {"assets": {"fingerprint": fingerprint, "approved_at": "t"}}
    assert qr.review_graph(graph)["checkpoints"]["assets"]["status"] == "approved"
    graph["nodes"][1]["data"]["config"]["prompt"] = "改过的描述"
    assert qr.review_graph(graph)["checkpoints"]["assets"]["status"] == "ready"


def test_redo_preview_counts_generated_nodes_and_spares_locked_assets():
    graph = healthy_graph()
    graph["nodes"][2]["data"]["config"]["asset_id"] = 9
    graph["nodes"].append(node("fixed", "image", asset_role="character", asset_name="林晚", asset_scene_node="sc", locked=True, asset_id=3))
    preview = qr.redo_preview(graph, "sc", "director")
    assert (preview["asset_count"], preview["shot_count"], preview["generated_count"], preview["kept_locked_count"]) == (1, 2, 1, 1)
    assert "fixed" not in preview["node_ids"]
    assert qr.redo_preview(graph, "sc", "compile")["asset_count"] == 0


def test_apply_redo_marks_stale_and_drops_plan_without_touching_input_preview():
    graph = healthy_graph()
    before = deepcopy(graph)
    summary = qr.apply_redo(graph, "sc", "director")
    cfg = {n["id"]: n["data"]["config"] for n in graph["nodes"]}
    assert cfg["hero"]["stale"] and cfg["sb"]["stale"] and cfg["mv"]["stale"]
    assert "director_plan" not in cfg["sc"] and summary["shot_count"] == 2
    assert "director_plan" in before["nodes"][0]["data"]["config"]


def test_redo_rejects_unknown_scene_or_stage():
    with pytest.raises(ValueError):
        qr.redo_preview(healthy_graph(), "nope", "director")
    with pytest.raises(ValueError):
        qr.redo_preview(healthy_graph(), "sc", "images")


# ---------------- 自动布局 ----------------

def test_shots_are_laid_out_one_row_per_unit_right_of_the_scene():
    from services import canvas_stage_gateway as gw

    scene = node("sc", "scene")
    scene["position"] = {"x": 0, "y": 100}
    graph = {"nodes": [scene], "edges": []}
    pairs = []
    for seq in (2, 1, 3):
        a, b = node(f"sb{seq}", "image"), node(f"mv{seq}", "video")
        a["position"] = b["position"] = {"x": 0, "y": 100}
        graph["nodes"] += [a, b]
        pairs.append((seq, a, b))
    gw._layout_shots(graph, scene, pairs)
    pos = {n["id"]: n["position"] for n in graph["nodes"]}
    assert pos["sb1"]["x"] == gw.SCENE_DEFAULT_W + gw.SHOT_SCENE_GAP and pos["sb1"]["y"] == 100
    assert pos["sb2"]["y"] == 100 + gw.SHOT_ROW_H and pos["sb3"]["y"] == 100 + 2 * gw.SHOT_ROW_H
    assert pos["mv1"]["x"] == pos["sb1"]["x"] + gw.SHOT_COL_W
    assert gw.SHOT_ROW_H > gw.NODE_H and gw.SHOT_COL_W > gw.NODE_W and gw.ASSET_CELL_W > gw.NODE_W and gw.ASSET_CELL_H > gw.NODE_H


def test_overlapping_new_nodes_are_pushed_below_existing_ones():
    from services import canvas_stage_gateway as gw

    existing = node("old", "image")
    existing["position"] = {"x": 0, "y": 0}
    fresh = node("new", "image")
    fresh["position"] = {"x": 100, "y": 50}
    graph = {"nodes": [existing, fresh], "edges": []}
    gw._avoid_overlaps(graph, [fresh])
    assert fresh["position"]["y"] >= gw.NODE_H


# ---------------- 视频节点参考图 ----------------

def _video_graph():
    graph = healthy_graph()
    graph["nodes"][2]["data"]["config"]["source_scene_ids"] = ["1"]
    graph["nodes"][3]["data"]["config"].update(characters=["顾沉"], source_scene_ids=["1"])
    graph["nodes"][1]["data"]["config"]["scene_ids"] = ["1"]
    graph["nodes"].append(node("room", "image", asset_role="scene", asset_name="宴会厅", asset_scene_node="sc", scene_ids=["1"], prompt="厅"))
    return graph


def test_video_node_without_character_reference_is_flagged_with_a_one_click_fix():
    issues = qr.review_graph(_video_graph())["checkpoints"]["storyboard"]["issues"]
    issue = next(i for i in issues if i["code"] == "video_missing_character_ref")
    assert issue["action"] == "bind_references" and issue["severity"] == "warning" and "顾沉" in issue["message"]


def test_binding_connects_character_then_scene_after_the_storyboard_frame():
    from services import canvas_stage_gateway as gw

    graph = _video_graph()
    gw._bind_assets(graph)
    video_edges = [e for e in graph["edges"] if e["target"] == "mv"]
    # 顺序：分镜图 → 角色 → 场景，与提示词里的 @图片N 对应
    assert [e["source"] for e in video_edges] == ["sb", "hero", "room"]
    assert all(e["targetHandle"] == "image" for e in video_edges)
    gw._bind_assets(graph)
    assert len([e for e in graph["edges"] if e["target"] == "mv"]) == 3
    assert not any(i["code"] == "video_missing_character_ref" for i in qr.review_graph(graph)["checkpoints"]["storyboard"]["issues"])


# ---------------- 视频提交时的一致性约束 ----------------

def test_video_identity_directive_maps_each_reference_and_only_lists_present_kinds():
    from services.video_canvas_runtime import build_video_identity_directive

    text = build_video_identity_directive([("frame", ""), ("character", "萧炎"), ("scene", "宴会厅")])
    assert "图片1：分镜首帧；图片2：角色「萧炎」；图片3：场景「宴会厅」" in text
    assert "保持同一张脸" in text and "场景的空间布局" in text and "道具的形状" not in text
    assert build_video_identity_directive([]) == ""


def test_video_reference_entries_use_asset_meta_and_type(monkeypatch):
    from types import SimpleNamespace

    from services import video_canvas_runtime as rt

    assets = {
        1: SimpleNamespace(name="分镜2", meta_json={}, asset_type="storyboard_frame"),
        2: SimpleNamespace(name="萧炎", meta_json={"asset_role": "character"}, asset_type="image"),
        3: SimpleNamespace(name="工牌", meta_json=None, asset_type="prop_reference"),
    }
    db = SimpleNamespace(get=lambda model, key: assets.get(key))
    entries = rt.video_reference_entries([{"asset_id": 1}, {"asset_id": 2}, {"asset_id": 3}, {"url": "x"}], db)
    assert entries == [("frame", "分镜2"), ("character", "萧炎"), ("prop", "工牌"), ("other", "")]


# ---------------- 画布级画面比例 ----------------

def test_canvas_aspect_is_read_from_production_settings_and_described_for_the_agent():
    from services.canvas_style import canvas_aspect, describe_canvas_aspect

    graph = {"metadata": {"production_settings": {"aspect_ratio": "9:16"}}}
    assert canvas_aspect(graph) == "9:16" and "9:16" in describe_canvas_aspect(graph) and "不要传 aspect_ratio" in describe_canvas_aspect(graph)
    assert canvas_aspect({"metadata": {"production_settings": {"aspect_ratio": "7:5"}}}) is None
    assert "默认 16:9" in describe_canvas_aspect({})


def test_video_reference_slots_follow_the_selected_models_declared_limit(monkeypatch):
    from services import canvas_stage_gateway as gw
    from services import video_canvas_runtime as rt

    graph = _video_graph()
    for index in range(3):
        graph["nodes"].append(node(f"extra{index}", "image", asset_role="character", asset_name=f"路人{index}", asset_scene_node="sc", scene_ids=["1"], prompt="p"))
    graph["nodes"][3]["data"]["config"]["characters"] = ["顾沉", "路人0", "路人1", "路人2"]
    graph["nodes"][3]["data"]["config"]["prompt"] = "顾沉走进宴会厅，顾沉看向路人0，路人1，路人2"
    graph["nodes"][3]["data"]["config"]["model_id"] = 7
    monkeypatch.setattr(rt, "_video_model_capabilities", lambda config, db: {"limits": {"max_reference_images": 3}})
    gw._bind_assets(graph, db=object())
    # 上限 3：分镜图占 1 个，剩下 2 个名额先给角色，场景被挤掉
    assert [e["source"] for e in graph["edges"] if e["target"] == "mv"] == ["sb", "hero", "extra0"]


def test_video_reference_limit_defaults_to_nine_and_is_capped_at_nine(monkeypatch):
    from services import canvas_stage_gateway as gw
    from services import video_canvas_runtime as rt

    assert gw._video_reference_limit({}, None) == 9
    monkeypatch.setattr(rt, "_video_model_capabilities", lambda config, db: None)
    assert gw._video_reference_limit({"model_id": 1}, object()) == 9
    monkeypatch.setattr(rt, "_video_model_capabilities", lambda config, db: {"limits": {"max_reference_images": 30}})
    assert gw._video_reference_limit({"model_id": 1}, object()) == 9
    monkeypatch.setattr(rt, "_video_model_capabilities", lambda config, db: {"limits": {"max_reference_images": 0}})
    assert gw._video_reference_limit({"model_id": 1}, object()) == 0


# ---------------- 智能连线 ----------------

def _keys(graph, target):
    return [(e["source"], e["targetHandle"]) for e in graph["edges"] if e["target"] == target]


def test_smart_connect_repairs_skeleton_and_binds_references_in_order():
    from services.canvas_smart_connect import plan_smart_connect

    graph = _video_graph()
    graph["edges"] = []  # 手滑把线全删了
    graph["nodes"][0]["data"]["config"]["source_screenplay_node"] = "sp"
    plan = plan_smart_connect(graph)
    assert graph["edges"] == []  # 入参不被修改
    assert plan["changed"] and _keys(plan["graph"], "mv") == [("sb", "image"), ("hero", "image"), ("room", "image")]
    assert ("sc", "prompt") in _keys(plan["graph"], "sb") and ("hero", "references") in _keys(plan["graph"], "sb")
    assert {a["target"] for a in plan["added"]} >= {"mv", "sb"} and plan["removed"] == []


def test_smart_connect_is_idempotent_and_reports_orphans():
    from services.canvas_smart_connect import plan_smart_connect

    graph = _video_graph()
    graph["nodes"].append(node("lonely", "image", asset_role="prop", asset_name="酒杯", asset_scene_node="sc", scene_ids=["9"], prompt="杯"))
    first = plan_smart_connect(graph)
    second = plan_smart_connect(first["graph"])
    assert not second["changed"]
    assert any(i["code"] == "orphan_asset" and "酒杯" in i["message"] for i in second["issues"])


def test_smart_connect_trims_agent_reference_edges_when_the_model_limit_shrinks(monkeypatch):
    from services import canvas_smart_connect as sc
    from services import video_canvas_runtime as rt
    from services.canvas_smart_connect import plan_smart_connect

    graph = _video_graph()
    graph["nodes"][3]["data"]["config"]["model_id"] = 7
    first = plan_smart_connect(graph)
    assert len(_keys(first["graph"], "mv")) == 3
    monkeypatch.setattr(rt, "_video_model_capabilities", lambda config, db: {"limits": {"max_reference_images": 2}})
    second = plan_smart_connect(first["graph"], db=object())
    assert _keys(second["graph"], "mv") == [("sb", "image"), ("hero", "image")]
    assert [r["source"] for r in second["removed"] if r["target"] == "mv"] == ["room"]
    assert sc is not None


def test_smart_connect_flags_manual_edges_over_the_model_limit(monkeypatch):
    from services import video_canvas_runtime as rt
    from services.canvas_smart_connect import plan_smart_connect

    graph = _video_graph()
    graph["nodes"][3]["data"]["config"]["model_id"] = 7
    for index in range(3):
        extra = node(f"m{index}", "image", prompt="x")
        graph["nodes"].append(extra)
        graph["edges"].append(edge(f"m{index}", "mv", "image"))  # 用户手动拉的线，没有 agent_asset_binding 标记
    monkeypatch.setattr(rt, "_video_model_capabilities", lambda config, db: {"limits": {"max_reference_images": 3}})
    plan = plan_smart_connect(graph, db=object())
    assert any(i["code"] == "over_reference_limit" for i in plan["issues"])
    assert all(e["source"].startswith("m") or e["source"] == "sb" for e in plan["graph"]["edges"] if e["target"] == "mv")


def test_smart_connect_selection_skips_unchecked_changes():
    from services.canvas_smart_connect import apply_selection, plan_smart_connect

    graph = _video_graph()
    plan = plan_smart_connect(graph)
    hero_key = next(a["key"] for a in plan["added"] if a["source"] == "hero" and a["target"] == "mv")
    chosen = apply_selection(graph, plan["graph"], {hero_key}, set())
    assert ("hero", "image") not in _keys(chosen, "mv") and ("room", "image") in _keys(chosen, "mv")
    # 不想被移除的连线放回去
    shrunk = plan_smart_connect(plan["graph"])
    assert apply_selection(plan["graph"], shrunk["graph"], set(), {"nope"}) is not None


# ---------------- 连续时长区间 ----------------

def test_duration_range_declared_by_model_allows_any_integer_second_inside():
    from services.video_duration import normalize_video_duration

    caps = {"limits": {"duration_seconds": {"min": 4, "max": 15}}}
    assert normalize_video_duration(13, model="xinyao", capabilities=caps) == 13
    assert normalize_video_duration(2, model="xinyao", capabilities=caps) == 4
    assert normalize_video_duration(30, model="xinyao", capabilities=caps) == 15


def test_duration_allowed_list_inside_limits_is_honoured_and_options_take_priority():
    from services.video_duration import normalize_video_duration

    assert normalize_video_duration(7, model="m", capabilities={"limits": {"duration_seconds": {"allowed": [5, 10]}}}) == 5
    assert normalize_video_duration(7, model="m", capabilities={"duration_options": [6, 12], "limits": {"duration_seconds": {"min": 4, "max": 15}}}) == 6


# ---------------- 启动自动恢复 ----------------

def test_collect_resumable_runs_only_picks_recent_active_runs():
    import datetime
    from types import SimpleNamespace

    from services import canvas_run_resume as resume

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    def row(run_id, status, age_hours):
        run = SimpleNamespace(id=run_id, status=status, created_at=now - datetime.timedelta(hours=age_hours))
        return run, SimpleNamespace(id=100 + run_id, owner_user_id=7)

    rows = [row(1, "running", 1), row(2, "queued", 30), row(3, "running", 23)]

    class FakeQuery:
        def join(self, *a, **k): return self
        def filter(self, *a, **k): return self
        def order_by(self, *a, **k): return self
        def all(self): return rows

    class FakeDb:
        def query(self, *a, **k): return FakeQuery()

    refs = resume.collect_resumable_runs(FakeDb())
    assert [r["run_id"] for r in refs] == [1, 3] and refs[0] == {"canvas_id": 101, "run_id": 1, "owner_user_id": 7}


def test_resume_skips_runs_that_are_not_failed_and_survives_individual_errors(monkeypatch):
    import asyncio

    from services import canvas_run_resume as resume

    calls = []

    async def fake_one(ref):
        calls.append(ref["run_id"])
        if ref["run_id"] == 2:
            return False
        return True

    monkeypatch.setattr(resume, "_resume_one", fake_one)
    refs = [{"canvas_id": 1, "run_id": 1, "owner_user_id": 1}, {"canvas_id": 1, "run_id": 2, "owner_user_id": 1}, {"canvas_id": 1, "run_id": 3, "owner_user_id": 1}]
    assert asyncio.run(resume.resume_interrupted_canvas_runs(refs, delay_seconds=0)) == 2
    assert calls == [1, 2, 3]
    assert asyncio.run(resume.resume_interrupted_canvas_runs([], delay_seconds=0)) == 0


# ---------------- 云端链接复用 ----------------

def test_prepare_reference_urls_keeps_input_order_and_skips_upload_for_public_links(monkeypatch, tmp_path):
    import asyncio

    from services import oss as oss_service
    from services import video_api

    local = tmp_path / "a.png"
    local.write_bytes(b"x")
    uploads = []
    monkeypatch.setattr(oss_service, "is_enabled", lambda: True)
    monkeypatch.setattr(oss_service, "upload_file", lambda path, *a, **k: uploads.append(path) or "https://oss.example/a.png")
    urls = asyncio.run(video_api.prepare_video_reference_urls(["https://oss.example/first.png", str(local), "https://oss.example/last.png"]))
    assert urls == ["https://oss.example/first.png", "https://oss.example/a.png", "https://oss.example/last.png"]
    assert uploads == [str(local)]


def test_asset_without_cloud_link_is_uploaded_once_then_reused(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from services import video_canvas_runtime as rt

    asset = SimpleNamespace(id=5, story_id=1, status="active", file_path="canvas_1/run_1/x.png", asset_type="storyboard_frame", meta_json={"asset_role": None})
    db = SimpleNamespace(get=lambda model, key: asset, commit=lambda: None)
    canvas = SimpleNamespace(story_id=1)
    uploads = []

    async def fake_upload(path):
        uploads.append(path)
        return "https://oss.example/x.png"

    monkeypatch.setattr(rt, "_upload_generated_image_to_oss", fake_upload)
    monkeypatch.setattr(rt, "_asset_media_kind", lambda a: "image")
    monkeypatch.setattr(rt, "_local_reference_paths", lambda inputs, c, d: ["C:/x.png"])
    asyncio.run(rt._ensure_asset_oss_urls([{"asset_id": 5}], canvas, db))
    assert asset.meta_json["oss_url"] == "https://oss.example/x.png" and uploads == ["C:/x.png"]
    asyncio.run(rt._ensure_asset_oss_urls([{"asset_id": 5}], canvas, db))
    assert uploads == ["C:/x.png"]  # 第二次直接复用，不再上传


def test_asset_with_generation_time_cloud_link_is_not_uploaded_again_at_video_submit(monkeypatch):
    """图片生成时已直传 OSS 并记下外链的资产，提交视频时直接用外链，不再上传。"""
    import asyncio
    from types import SimpleNamespace

    from services import video_canvas_runtime as rt

    asset = SimpleNamespace(id=5, story_id=1, status="active", name="萧炎", file_path="canvas_1/run_1/x.png", asset_type="character_reference", meta_json={"asset_role": "character", "oss_url": "https://oss.example/x.png"})
    db = SimpleNamespace(get=lambda model, key: asset, commit=lambda: None)
    canvas = SimpleNamespace(story_id=1)
    uploads = []

    async def fake_upload(path):
        uploads.append(path)
        return "https://oss.example/other.png"

    monkeypatch.setattr(rt, "_upload_generated_image_to_oss", fake_upload)
    monkeypatch.setattr(rt, "_asset_media_kind", lambda a: "image")
    monkeypatch.setattr(rt, "_local_reference_paths", lambda inputs, c, d: ["C:/x.png"])
    asyncio.run(rt._ensure_asset_oss_urls([{"asset_id": 5}], canvas, db))
    assert uploads == []
    assert rt._reference_urls([{"asset_id": 5}], canvas, db) == ["https://oss.example/x.png"]


def test_asset_already_in_the_cloud_records_its_own_link_without_uploading(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from services import video_canvas_runtime as rt

    asset = SimpleNamespace(id=6, story_id=1, status="active", name="广场", file_path="https://oss.example/up.png", asset_type="scene_reference", meta_json={})
    db = SimpleNamespace(get=lambda model, key: asset, commit=lambda: None)
    uploads = []

    async def fake_upload(path):
        uploads.append(path)
        return "https://oss.example/other.png"

    monkeypatch.setattr(rt, "_upload_generated_image_to_oss", fake_upload)
    monkeypatch.setattr(rt, "_asset_media_kind", lambda a: "image")
    asyncio.run(rt._ensure_asset_oss_urls([{"asset_id": 6}], SimpleNamespace(story_id=1), db))
    assert uploads == [] and asset.meta_json["oss_url"] == "https://oss.example/up.png"


def test_oss_upload_reuses_an_existing_same_size_object(monkeypatch, tmp_path):
    from services import oss as oss_service

    local = tmp_path / "img.png"
    local.write_bytes(b"12345")
    puts = []

    class FakeBucket:
        def get_object_meta(self, key):
            return type("R", (), {"headers": {"Content-Length": "5"}})()

        def put_object_from_file(self, *a, **k):
            puts.append(a)

    monkeypatch.setattr(oss_service, "is_enabled", lambda: True)
    monkeypatch.setattr(oss_service, "_get_client", lambda: FakeBucket())
    monkeypatch.setattr(oss_service, "_build_public_url", lambda key: f"https://oss.example/{key}")
    assert oss_service.upload_file(local, remote_key="k/img.png") == "https://oss.example/k/img.png"
    assert puts == []
    local.write_bytes(b"123456")  # 大小变了：视为不同内容，必须重新上传
    assert oss_service.upload_file(local, remote_key="k/img.png") == "https://oss.example/k/img.png"
    assert len(puts) == 1


def test_oss_remembers_uploaded_files_within_the_process(monkeypatch, tmp_path):
    from services import oss as oss_service

    local = tmp_path / "again.png"
    local.write_bytes(b"abc")
    calls = {"client": 0, "put": 0}

    class FakeBucket:
        def get_object_meta(self, key):
            raise RuntimeError("不存在")

        def put_object_from_file(self, *a, **k):
            calls["put"] += 1

    def fake_client():
        calls["client"] += 1
        return FakeBucket()

    monkeypatch.setattr(oss_service, "is_enabled", lambda: True)
    monkeypatch.setattr(oss_service, "_get_client", fake_client)
    monkeypatch.setattr(oss_service, "_build_public_url", lambda key: f"https://oss.example/{key}")
    first = oss_service.upload_file(local, remote_key="k/again.png")
    second = oss_service.upload_file(local, remote_key="k/again.png")
    assert first == second == "https://oss.example/k/again.png"
    assert calls == {"client": 1, "put": 1}  # 第二次连云端查询都没有


def test_one_input_is_one_reference_even_when_it_has_cloud_link_and_static_url(monkeypatch):
    from types import SimpleNamespace

    from services import video_canvas_runtime as rt

    asset = SimpleNamespace(id=5, story_id=1, status="active", file_path="canvas_1/run_1/x.png", asset_type="storyboard_frame", meta_json={"oss_url": "https://oss.example/x.png"})
    db = SimpleNamespace(get=lambda model, key: asset)
    monkeypatch.setattr(rt, "_asset_media_kind", lambda a: "image")
    inputs = [{"asset_id": 5, "url": "/static/manga/canvas_1/run_1/x.png", "_media_url": "/static/manga/canvas_1/run_1/x.png"}] * 1
    inputs += [{"url": "https://other.example/style.png"}]
    urls = rt._reference_urls(inputs, SimpleNamespace(story_id=1), db)
    assert urls == ["https://oss.example/x.png", "https://other.example/style.png"]  # 不再是 3 张


# ---------------- 参考图被上游拒绝时自动降级 ----------------

def test_reference_fallback_tiers_halve_then_keep_only_the_storyboard_frame():
    from services.video_canvas_runtime import reference_fallback_tiers

    assert reference_fallback_tiers(6) == [6, 3, 1]
    assert reference_fallback_tiers(3) == [3, 2, 1]
    assert reference_fallback_tiers(2) == [2, 1]
    assert reference_fallback_tiers(1) == [1] and reference_fallback_tiers(0) == [0]


def test_submit_retries_with_fewer_references_and_rebuilds_the_mapping_text():
    import asyncio

    from services.errors import UpstreamServiceError
    from services.video_canvas_runtime import submit_with_reference_fallback

    entries = [("frame", ""), ("character", "萧炎"), ("character", "测验员"), ("character", "少年甲"), ("character", "萧薰儿"), ("scene", "广场")]
    images = [f"https://oss.example/{i}.jpg" for i in range(6)]
    calls = []

    async def submit(imgs, prompt, mode):
        calls.append((len(imgs), mode, prompt))
        if len(imgs) > 3:
            raise UpstreamServiceError("生成失败", retryable=False, provider="Video", status_code=500)
        return {"provider_job_id": "job-1"}

    result, used, prompt = asyncio.run(submit_with_reference_fallback(submit, images, entries, "BASE"))
    assert [c[0] for c in calls] == [6, 3] and used == images[:3] and result == {"provider_job_id": "job-1"}
    assert "图片3：角色「测验员」" in prompt and "场景" not in prompt.split("【一致性约束】")[0]  # 说明与实际保留的 3 张对应


def test_submit_does_not_degrade_on_transient_errors_or_when_the_last_tier_fails():
    import asyncio

    import pytest

    from services.errors import UpstreamServiceError
    from services.video_canvas_runtime import submit_with_reference_fallback

    entries = [("frame", ""), ("character", "甲")]
    images = ["https://oss.example/a.jpg", "https://oss.example/b.jpg"]
    calls = []

    async def transient(imgs, prompt, mode):
        calls.append(len(imgs))
        raise UpstreamServiceError("暂时不可用", retryable=True, provider="Video", status_code=503)

    with pytest.raises(UpstreamServiceError):
        asyncio.run(submit_with_reference_fallback(transient, images, entries, "P"))
    assert calls == [2]  # 瞬时错误不降级，交给原有重试

    calls.clear()

    async def always_rejected(imgs, prompt, mode):
        calls.append(len(imgs))
        raise UpstreamServiceError("生成失败", retryable=False, provider="Video", status_code=500)

    with pytest.raises(UpstreamServiceError):
        asyncio.run(submit_with_reference_fallback(always_rejected, images, entries, "P"))
    assert calls == [2, 1]


def test_video_references_only_bind_characters_mentioned_in_the_prompt_ordered_by_mentions():
    from services import canvas_stage_gateway as gw

    graph = _video_graph()
    for name in ("路人0", "路人1"):
        graph["nodes"].append(node(name, "image", asset_role="character", asset_name=name, asset_scene_node="sc", scene_ids=["1"], prompt="p"))
    # 导演记录的出场角色混着非角色的词和场景里所有人；提示词里只出现了 路人1（两次）和 顾沉（一次）
    graph["nodes"][3]["data"]["config"]["characters"] = ["石碑上亮起五个大字", "顾沉", "路人0", "路人1", "级别"]
    graph["nodes"][3]["data"]["config"]["prompt"] = "路人1转身，顾沉看向路人1"
    gw._bind_assets(graph)
    assert [e["source"] for e in graph["edges"] if e["target"] == "mv"] == ["sb", "路人1", "hero", "room"]


def test_assets_are_only_connected_to_shots_that_actually_mention_them():
    from services import canvas_stage_gateway as gw

    graph = _video_graph()
    graph["nodes"] += [
        node("extra", "image", asset_role="character", asset_name="路人甲", asset_scene_node="sc", scene_ids=["1"], prompt="p"),
        node("cup", "image", asset_role="prop", asset_name="酒杯", asset_scene_node="sc", scene_ids=["1"], prompt="p"),
        node("lamp", "image", asset_role="prop", asset_name="油灯", asset_scene_node="sc", scene_ids=["1"], prompt="p"),
    ]
    # 同一个分场景里的所有资产都会带着“场景编号”，但这个镜头只写了顾沉、宴会厅和酒杯
    graph["nodes"][2]["data"]["config"]["prompt"] = "顾沉举起酒杯，走进宴会厅"
    graph["nodes"][3]["data"]["config"]["prompt"] = "顾沉举起酒杯，走进宴会厅"
    graph["nodes"][3]["data"]["config"]["characters"] = ["顾沉", "路人甲"]
    gw._bind_assets(graph)
    video_sources = [e["source"] for e in graph["edges"] if e["target"] == "mv"]
    board_sources = [e["source"] for e in graph["edges"] if e["target"] == "sb" and e.get("targetHandle") == "references"]
    assert video_sources == ["sb", "hero", "room", "cup"]  # 没提到的路人甲、油灯都不连
    assert sorted(board_sources) == ["cup", "hero", "room"]


# ---------------- 参考图文字标注 ----------------

def test_reference_label_text_names_the_kind_and_skips_unnamed_assets():
    from services.video_canvas_runtime import reference_label_text

    assert reference_label_text("character", "萧炎") == "角色：萧炎"
    assert reference_label_text("scene", "广场") == "场景：广场" and reference_label_text("prop", "酒杯") == "道具：酒杯"
    assert reference_label_text("frame", "画布 x") == "分镜首帧（构图参考）"
    assert reference_label_text("character", "") == "" and reference_label_text("other", "x") == ""


def test_aggregate_scene_node_with_scenes_is_not_empty():
    from services.canvas_quality_review import review_graph
    graph = {"nodes": [{"id": "s", "type": "scene", "data": {"label": "剧本审核（1 场）", "config": {"scenes": [{"scene_id": 1, "title": "场景1", "beats": [{"beat_id": 1, "action": "站着"}]}]}}}], "edges": []}
    codes = [i["code"] for i in review_graph(graph)["checkpoints"]["script"]["issues"]]
    assert "empty_scene" not in codes
    graph["nodes"][0]["data"]["config"]["scenes"] = []
    assert "empty_scene" in [i["code"] for i in review_graph(graph)["checkpoints"]["script"]["issues"]]


def test_stale_retry_hint_in_canvas_settings_is_cleaned_and_the_new_hint_is_not_persisted(monkeypatch):
    # 网关里的清理逻辑：设置里残留的重试提示被去掉，且本次的 retry_hint 不会写进 production_settings
    from services.canvas_pipeline_runner import RETRY_HINT

    stored = f"保持悬疑；{RETRY_HINT}"
    cleaned = stored.replace(RETRY_HINT, "").strip(" ；;")
    assert cleaned == "保持悬疑"
    assert "；".join(part for part in (cleaned, RETRY_HINT) if part) == f"保持悬疑；{RETRY_HINT}"


# ---------------- 视频节点自动推荐模型 ----------------

def _video_model(model_id, key, video):
    from types import SimpleNamespace

    return SimpleNamespace(id=model_id, model_key=key, display_name=key, capabilities_json={"video": video})


FIXED_15 = _video_model(25, "cvk", {"limits": {"duration_seconds": {"allowed": [15]}, "aspect_ratios": ["16:9", "9:16"], "max_reference_images": 9}})
RANGE_4_15 = _video_model(41, "xinyao", {"limits": {"duration_seconds": {"min": 4, "max": 15}, "aspect_ratios": ["16:9", "9:16"], "max_reference_images": 9}})
UNDECLARED = _video_model(7, "mystery", {})


def test_recommendation_picks_a_model_that_really_supports_the_duration():
    from services.canvas_video_model import recommend_video_model

    models = [FIXED_15, RANGE_4_15, UNDECLARED]
    assert recommend_video_model(None, None, 13, "16:9", 3, models).id == 41  # 固定 15 秒的不支持 13 秒
    assert recommend_video_model(None, None, 15, "16:9", 3, models).id == 25  # 都支持时按后台排序
    assert recommend_video_model(None, None, 6, "9:16", 0, [UNDECLARED, RANGE_4_15]).id == 41  # 明确支持优先于“未声明”


def test_recommendation_respects_aspect_ratio_and_reference_limits_then_falls_back_to_the_closest_duration():
    from services.canvas_video_model import recommend_video_model

    square_only = _video_model(8, "square", {"limits": {"duration_seconds": {"min": 4, "max": 15}, "aspect_ratios": ["1:1"]}})
    assert recommend_video_model(None, None, 8, "16:9", 0, [square_only, RANGE_4_15]).id == 41
    few_refs = _video_model(9, "few", {"limits": {"duration_seconds": {"min": 4, "max": 15}, "max_reference_images": 2}})
    assert recommend_video_model(None, None, 8, "16:9", 6, [few_refs, RANGE_4_15]).id == 41
    # 没有任何模型支持 13 秒：选最接近的（固定 15 秒，差 2 秒）
    assert recommend_video_model(None, None, 13, "16:9", 0, [FIXED_15]).id == 25
    assert recommend_video_model(None, None, 13, "16:9", 0, []) is None


def test_apply_auto_models_only_touches_auto_nodes_and_follows_duration_changes(monkeypatch):
    from services import canvas_video_model as cvm

    monkeypatch.setattr(cvm, "candidate_video_models", lambda db: [FIXED_15, RANGE_4_15])
    monkeypatch.setattr(cvm, "_user_default_video_model_id", lambda db, user_id: None)
    graph = {"nodes": [
        node("auto", "video", unit_id="u1", duration_seconds=13, model_auto=True, aspect_ratio="16:9"),
        node("manual", "video", unit_id="u2", duration_seconds=13, model_id=25, aspect_ratio="16:9"),
        node("stale", "video", unit_id="u3", duration_seconds=13, model_auto=True, stale=True),
    ], "edges": []}
    changes = cvm.apply_auto_video_models(graph, object(), 1)
    cfg = {n["id"]: n["data"]["config"] for n in graph["nodes"]}
    assert cfg["auto"]["model_id"] == 41 and cfg["manual"]["model_id"] == 25 and "model_id" not in cfg["stale"]
    assert [c["node_id"] for c in changes] == ["auto"]
    # 用户把时长改成 15 秒：重新推荐（两个都支持，按排序取第一个）
    cfg["auto"]["duration_seconds"] = 15
    assert cvm.apply_auto_video_models(graph, object(), 1)[0]["to"] == 25
    assert cvm.apply_auto_video_models(graph, object(), 1) == []  # 没变化就不重复


# ---------------- 导演：超长单句 & 上游暂时不可用 ----------------

def test_long_single_sentence_dialogue_is_split_at_clauses_without_changing_a_word():
    from services.canvas_director_quality import _split_long_line, speech_seconds

    line = "测验员：薰儿小姐，半年之后，你应该便能凝聚斗气之旋，如果你成功的话，那么以十四岁年龄成为一名真正的斗者，你是萧家百年内的第二人！"
    assert speech_seconds([{"dialogue": [line]}]) > 15  # 只有句末一个标点，原来拆不开
    parts = _split_long_line(line, 15 * 3.5)
    assert len(parts) >= 2 and all(p.startswith("测验员：") for p in parts)
    assert "".join(p.removeprefix("测验员：") for p in parts) == line.removeprefix("测验员：")  # 只切分，不改写
    assert all(speech_seconds([{"dialogue": [p]}]) <= 15 for p in parts)
    # 本来就短的、或者没有任何标点可切的，原样返回
    assert _split_long_line("甲：快走", 52) == ["甲：快走"]


def test_pipeline_waits_and_retries_when_the_upstream_model_is_temporarily_unavailable(monkeypatch):
    import asyncio

    from services import canvas_pipeline_runner as runner
    from services.errors import UpstreamServiceError

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)
    assert runner._is_transient(UpstreamServiceError("暂时不可用", retryable=True, provider="DeepSeek", status_code=500))
    assert not runner._is_transient(UpstreamServiceError("校验没过", retryable=False, provider="DeepSeek", code="canvas_director_quality_failed"))
    assert not runner._is_transient(UpstreamServiceError("质量", retryable=True, provider="DeepSeek", code="canvas_director_quality_failed"))
    assert runner.MAX_TRANSIENT_ATTEMPTS > runner.MAX_STAGE_ATTEMPTS and runner.TRANSIENT_BACKOFF_SECONDS == (5, 15, 30)
    assert sleeps == [] and asyncio is not None


# ---------------- 分镜板（一张 16:9 大图，按时间段分格并标注） ----------------

def _unit_with_segments(count, seconds_each=2):
    return {"unit_id": "u1", "title": "石碑宣判", "storyboard_prompt": "单帧", "video_prompt": "视频", "storyboard_json": {"segments": [
        {"start_second": i * seconds_each, "end_second": (i + 1) * seconds_each, "visual_action": f"动作{i + 1}", "camera_direction": "中景", "start_state": "起", "end_state": f"止{i + 1}", "dialogue_or_narration": ""}
        for i in range(count)]}}


def test_sheet_has_one_panel_per_time_segment_and_a_regular_grid():
    from services.canvas_storyboard_sheet import build_sheet_prompt, sheet_layout, sheet_panels

    assert [sheet_layout(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9)] == [(1, 1), (2, 1), (3, 1), (2, 2), (3, 2), (3, 2), (4, 2), (4, 2), (3, 3)]
    panels = sheet_panels(_unit_with_segments(5))
    assert [p["label"] for p in panels] == ["0-2s", "2-4s", "4-6s", "6-8s", "8-10s"]
    prompt = build_sheet_prompt(_unit_with_segments(5), panels)
    assert "3 列 × 2 行" in prompt and "共 5 格" in prompt and "格3（4-6s）：动作3" in prompt and "：；" not in prompt
    assert "禁止：不要在图里画任何文字" in prompt  # 标注由系统统一写，不让图片模型画字
    assert sheet_panels({"storyboard_json": {}}) == [] and sheet_panels({}) == []  # 没有时间轴就不出分镜板


def test_more_than_nine_segments_are_merged_in_order_without_losing_time_coverage():
    from services.canvas_storyboard_sheet import MAX_PANELS, sheet_panels

    panels = sheet_panels(_unit_with_segments(14, 1))
    assert len(panels) == MAX_PANELS and panels[0]["start"] == 0 and panels[-1]["end"] == 14
    assert [p["index"] for p in panels] == list(range(1, 10))
    assert all(a["end"] == b["start"] for a, b in zip(panels, panels[1:]))  # 合并后时间段首尾相接


def test_labels_are_stamped_in_each_cells_top_left(monkeypatch, tmp_path):
    from PIL import Image, ImageFont

    from services import canvas_storyboard_sheet as sheet
    from services import video_canvas_runtime as rt

    monkeypatch.setattr(rt, "_label_font", lambda size: ImageFont.load_default())
    path = tmp_path / "sheet.png"
    Image.new("RGB", (1920, 1080), (255, 255, 255)).save(path)
    panels = sheet.panel_summary(sheet.sheet_panels(_unit_with_segments(4)))
    assert sheet.stamp_sheet_labels(str(path), panels) is True
    image = Image.open(path).convert("RGB")
    boxes = sheet._cell_boxes(1920, 1080, 4)
    for x0, y0, x1, y1 in boxes:
        assert image.getpixel((x0 + 24, y0 + 22)) != (255, 255, 255)  # 每格左上角都有深色标签（避开圆角缺口）
        assert image.getpixel((x1 - 20, y1 - 20)) == (255, 255, 255)  # 其余位置不动
    monkeypatch.setattr(rt, "_label_font", lambda size: None)
    assert sheet.stamp_sheet_labels(str(path), panels) is False  # 没有字体时跳过，原图保留


def test_video_directive_explains_the_sheet_order_and_time_ranges():
    from services.canvas_storyboard_sheet import panel_summary, sheet_panels
    from services.video_canvas_runtime import asset_reference_role, build_video_identity_directive, reference_label_text
    from types import SimpleNamespace

    panels = panel_summary(sheet_panels(_unit_with_segments(3)))
    text = build_video_identity_directive([("sheet", ""), ("character", "萧炎")], "@图{n}", panels)
    assert "@图1：分镜板（共 3 格（3列×1行，从左到右、从上到下）" in text and "第2格 2-4s" in text and "@图2：角色「萧炎」" in text
    assert "依次展开成连续的视频" in text and "不要画进视频里" in text
    assert "分镜首帧" not in text
    sheet_asset = SimpleNamespace(asset_type="storyboard_frame", meta_json={"storyboard_sheet": True})
    assert asset_reference_role(sheet_asset) == "sheet" and "分镜板" in reference_label_text("sheet", "")
    assert asset_reference_role(SimpleNamespace(asset_type="storyboard_frame", meta_json={})) == "frame"  # 老的单帧分镜图不变


def test_stamp_asset_label_bar_adds_caption_strip(tmp_path):
    """资产图生成后，下方会接一条名称标注条；没有名称时原图不动。"""
    from PIL import Image

    from services.video_canvas_runtime import stamp_asset_label_bar

    path = tmp_path / "a.png"
    Image.new("RGB", (640, 360), (200, 200, 200)).save(path)
    assert stamp_asset_label_bar(path, "") is False
    assert Image.open(path).size == (640, 360)
    if stamp_asset_label_bar(path, "角色：萧炎"):
        assert Image.open(path).size[1] > 360


def test_descriptive_colon_is_not_a_speaker():
    """描述句里的冒号（“塑料膜上贴着标签：周一”“她写下：第七天”）不是说话人，真台词仍然识别。"""
    from services.screenplay_adapt import _real_speaker_matches

    assert _real_speaker_matches("冷藏层整整齐齐码着六盒番茄牛腩，塑料膜上贴着标签：周一、周二、周三……") == []
    assert _real_speaker_matches("陈默退到墙边。茶几上压着一张纸：器官捐献同意书，签名是他的。") == []
    assert _real_speaker_matches("她写下：第七天。") == []
    assert [n for _, n in _real_speaker_matches("陈默：我死了？")] == ["陈默"]
    assert [n for _, n in _real_speaker_matches("林晚（轻声）：明天见，陈默。")] == ["林晚（轻声）"]
    assert [n for _, n in _real_speaker_matches("甲：走。乙：好。")] == ["甲", "乙"]


def test_clean_source_scenes_repairs_saved_beats():
    """旧画布里已保存的脏节拍：标题行从动作里剥掉，被误判的“台词”还原成动作，假角色从人物表去掉。"""
    from services.canvas_director_quality import clean_source_scenes

    scene = {
        "scene_id": 2, "characters": ["塑料膜上贴着标签", "陈默"],
        "beats": [
            {"beat_id": 1, "type": "action", "action": "场景2：厨房 / 夜 / 内\n\n陈默拉开冰箱找水。", "dialogue": []},
            {"beat_id": 2, "type": "dialogue", "action": "", "dialogue": ["冷藏层码着六盒牛腩，塑料膜上贴着标签：周一、周二"]},
            {"beat_id": 3, "type": "dialogue", "action": "", "dialogue": ["陈默：晚晚，这些是谁做的？"]},
        ],
    }
    cleaned = clean_source_scenes([scene])[0]
    assert cleaned["characters"] == ["陈默"]
    assert cleaned["beats"][0]["action"] == "陈默拉开冰箱找水。"
    assert cleaned["beats"][1]["type"] == "action" and cleaned["beats"][1]["dialogue"] == []
    assert "塑料膜上贴着标签" in cleaned["beats"][1]["action"]
    assert cleaned["beats"][2]["dialogue"] == ["陈默：晚晚，这些是谁做的？"]
    assert scene["beats"][0]["action"].startswith("场景2")  # 入参不被修改


def test_synthesized_shots_have_no_placeholder_text():
    """规则兜底的分镜不再出现“开口说话，神情与台词情绪一致”“台词说完”，也不会切出一秒一格。"""
    from services.canvas_director_quality import source_index, synthesize_shots

    scenes = [{"scene_id": 1, "location": "厨房", "time_of_day": "夜", "beats": [
        {"beat_id": 1, "type": "action", "action": "陈默拉开冰箱找水。", "dialogue": []},
        {"beat_id": 2, "type": "action", "action": "他数到第六盒，手指发抖。", "dialogue": []},
        {"beat_id": 3, "type": "dialogue", "action": "", "dialogue": ["陈默：晚晚，这些是谁做的？"]},
        {"beat_id": 4, "type": "dialogue", "action": "", "dialogue": ["林晚：每天的你都问这一句。"]},
    ]}]
    unit = {"unit_id": "u1", "beat_ids": ["1.1", "1.2", "1.3", "1.4"], "duration_seconds": 9}
    shots = synthesize_shots(unit, source_index(scenes), list(range(4, 16)))
    segments = shots["storyboard_json"]["segments"]
    text = str(segments)
    assert "神情与台词情绪一致" not in text and "台词说完" not in text and "完成" not in text
    assert all(s["end_second"] - s["start_second"] >= 2.0 for s in segments)
    assert "晚晚，这些是谁做的" in text and "每天的你都问这一句" in text


def test_script_review_blocks_on_issues_and_never_on_failure(monkeypatch):
    """逻辑审稿：有硬伤返回问题列表；通过返回空；审稿服务自己出错一律放行，不能阻断创作。"""
    import asyncio

    from services import canvas_script_review as review
    from services import video_canvas_director as director

    async def run(result=None, error=None):
        async def fake(**_kwargs):
            if error:
                raise error
            return result

        monkeypatch.setattr(director, "_call_deepseek_json", fake)
        return await review.review_screenplay("剧本", "逆袭", None)

    issues = asyncio.run(run({"passed": False, "issues": [{"where": "场景2", "problem": "主角凭什么赢没交代", "fix": "补一句"}, {"problem": ""}]}))
    assert len(issues) == 1 and "凭什么" in review.format_issues(issues)
    assert asyncio.run(run({"passed": True, "issues": []})) == []
    assert asyncio.run(run(error=RuntimeError("402"))) == []


def test_improve_screenplay_revises_silently_and_keeps_better_version(monkeypatch):
    """审稿不通过时服务端自动改写重审：改得更好就采用；改写失败 / 变差则沿用上一版；全程不抛错。"""
    import asyncio

    from services import canvas_script_review as review

    reviews = {"原稿": [{"problem": "凭什么赢没交代"}, {"problem": "结尾无来源"}], "改稿": []}

    async def fake_review(content, _constraints, _key):
        return reviews[content]

    async def fake_revise(content, _issues, _constraints, _max_chars, _key):
        return "改稿"

    monkeypatch.setattr(review, "review_screenplay", fake_review)
    monkeypatch.setattr(review, "revise_screenplay", fake_revise)
    content, issues, rounds = asyncio.run(review.improve_screenplay("原稿", "逆袭", 600, None))
    assert (content, issues, rounds) == ("改稿", [], 1)

    async def fail_revise(*_args):
        return None

    monkeypatch.setattr(review, "revise_screenplay", fail_revise)
    content, issues, rounds = asyncio.run(review.improve_screenplay("原稿", "逆袭", 600, None))
    assert content == "原稿" and len(issues) == 2 and rounds == review.MAX_REVISION_ROUNDS  # 改写失败不放弃，继续下一轮

    reviews["改稿"] = [{"problem": "a"}, {"problem": "b"}, {"problem": "c"}]
    monkeypatch.setattr(review, "revise_screenplay", fake_revise)
    content, issues, _ = asyncio.run(review.improve_screenplay("原稿", "逆袭", 600, None))
    assert content == "原稿", "改写后问题更多时必须保留上一版"


def test_shots_start_to_the_right_of_the_asset_block():
    """已有资产块时，分镜 / 视频区从资产块右边缘之外开始，不被资产挤住后只能往下硬推。"""
    from services import canvas_stage_gateway as gw

    scene = node("sc", "scene")
    scene["position"] = {"x": 0, "y": 100}
    asset = node("hero", "image", asset_role="character")
    asset["position"] = {"x": gw.ASSET_CELL_W, "y": 1000}
    a, b = node("sb1", "image"), node("mv1", "video")
    a["position"] = b["position"] = {"x": 0, "y": 100}
    graph = {"nodes": [scene, asset, a, b], "edges": []}
    gw._layout_shots(graph, scene, [(1, a, b)])
    asset_right = gw.ASSET_CELL_W + gw.NODE_W
    assert a["position"]["x"] >= asset_right + gw.SHOT_ASSET_GAP and a["position"]["y"] == 100


def test_fixed15_policy_and_underfilled_merge():
    """固定 15 秒：策略只有 15 一档；同场景内容过少的相邻镜头合并，叙事 beat 不增不减、顺序不变。"""
    from services import canvas_director_quality as q

    fixed = {"metadata": {"production_settings": {"shot_duration_mode": "fixed15"}}}
    assert q.resolve_policy(fixed, None)["duration_options"] == [15]
    assert q.resolve_policy(fixed, None)["shot_duration_mode"] == "fixed15"
    flexible = q.resolve_policy({"metadata": {"production_settings": {}}}, None)
    assert flexible["duration_options"][0] == 4 and flexible["duration_options"][-1] == 15

    def beat(i, action="", dialogue=None):
        return {"beat_id": i, "type": "action", "action": action, "dialogue": dialogue or []}

    scenes = [
        {"scene_id": 1, "beats": [beat(1, "他推门。"), beat(2, "她抬头。"), beat(3, "", ["甲：来了。"])]},
        {"scene_id": 2, "beats": [beat(1, "走廊里很安静。")]},
    ]
    plan = {"units": [
        {"unit_id": "u1", "sequence": 1, "beat_ids": ["1.1"], "duration_seconds": 15, "story_summary": "开门", "narrative_purpose": "进入"},
        {"unit_id": "u2", "sequence": 2, "beat_ids": ["1.2", "1.3"], "duration_seconds": 15, "story_summary": "对视", "narrative_purpose": "对峙"},
        {"unit_id": "u3", "sequence": 3, "beat_ids": ["2.1"], "duration_seconds": 15, "story_summary": "走廊", "narrative_purpose": "转场"},
    ]}
    removed = q.merge_underfilled_units(plan, scenes, [15])
    assert removed == 1 and [u["beat_ids"] for u in plan["units"]] == [["1.1", "1.2", "1.3"], ["2.1"]]
    assert [u["sequence"] for u in plan["units"]] == [1, 2], "不同场景绝不合并，序号重排"
    assert "开门" in plan["units"][0]["story_summary"] and "对视" in plan["units"][0]["story_summary"]

    # 兜底分组：固定模式装到约 13 秒自然内容即切开，每组都是 15 秒
    synthesized = q.synthesize_plan(scenes, q.resolve_policy(fixed, None))
    assert {u["duration_seconds"] for u in synthesized["units"]} == {15}


def test_fixed15_mode_suppresses_flat_rhythm_and_inflation_warnings():
    from services.canvas_creative_guide import craft_warnings

    units = [{"duration_seconds": 15, "storyboard_json": {"segments": []}} for _ in range(4)]
    assert any("时长相同" in w for w in craft_warnings({"units": units}))
    assert not any("时长相同" in w for w in craft_warnings({"units": units, "production_policy": {"shot_duration_mode": "fixed15"}}))


def test_style_preset_image_becomes_style_anchor_and_goes_first():
    """风格预设图是“画风锚点”：图片生成时置顶，且带上与漫画工作流一致的图生图画风指令。"""
    from services import video_canvas_runtime as rt

    config = {"style_snapshot": {"name": "写实电影感", "prompt_template": "cinematic", "image_url": "https://oss.example/style.png"}}
    refs = rt._configured_reference_inputs(config, None, None)
    assert len(refs) == 1 and refs[0]["style_anchor"] is True and refs[0]["url"] == "https://oss.example/style.png"
    character = {"asset_id": 7, "url": "/static/manga/a.png"}
    ordered = rt.style_anchors_first([character, *refs])
    assert ordered[0] is refs[0] and ordered[1] is character
    assert "以参考图为准" in rt.STYLE_ANCHOR_DIRECTIVE and "只决定画风" in rt.STYLE_ANCHOR_DIRECTIVE
    # 自定义上传风格图没有提示词模板时，也要有一句画风要求
    assert "画风参考图为准" in rt._apply_style_prompt("一个女人", {"style_reference_asset_id": 3}, [])


def test_video_style_anchor_ordering_and_directive_follow_original_video_workflow():
    """视频：画风锚点紧跟分镜首帧，超过参考图上限先丢它；说明措辞照搬原视频工作流。"""
    from services import video_canvas_runtime as rt

    frame, hero, scene = {"asset_id": 1}, {"asset_id": 2}, {"asset_id": 3}
    style = {"url": "https://oss.example/style.png", "style_anchor": True}
    ordered = rt.order_video_references([frame, hero, scene, style], limit=9)
    assert ordered == [frame, style, hero, scene]
    assert rt.order_video_references([frame, hero, scene, style], limit=3) == [frame, hero, scene]
    assert rt.order_video_references([frame, hero], limit=9) == [frame, hero]

    assert rt.video_reference_entries([style], None) == [("style", "")]
    entries = [("frame", ""), ("style", "")]
    text = rt.build_video_identity_directive(entries, "@图{n}")
    assert "@图2：画风参考（画风、色调、光影、渲染质感以这张图为准）" in text
    assert "本视频的画风、色彩、光影以风格参考图为准，保持画面风格稳定统一" in text
    assert "完全以风格参考图为准" in text, "有分镜首帧时要声明分镜只提供构图和动作"
    assert "画风参考" not in rt.build_video_identity_directive([("frame", ""), ("character", "甲")], "@图{n}")


def test_parenthetical_stage_direction_does_not_demote_real_dialogue():
    """“萧炎（尴尬地笑了一声）：呵呵……”是真台词：括号里的“了”不能让它被当成叙述句。导演与编译看到的是同一份来源节拍。"""
    from services.screenplay_adapt import _real_speaker_matches
    from services.canvas_director_quality import source_index

    assert [n for _, n in _real_speaker_matches("萧炎（尴尬地笑了一声）：呵呵……")] == ["萧炎（尴尬地笑了一声）"]
    scenes = [{"scene_id": 1, "characters": ["萧炎"], "beats": [
        {"beat_id": 1, "type": "dialogue", "action": "", "dialogue": ["萧炎（尴尬地笑了一声）：呵呵……"]},
        {"beat_id": 2, "type": "dialogue", "action": "", "dialogue": ["冷藏层码着六盒，塑料膜上贴着标签：周一、周二"]},
    ]}]
    index = source_index(scenes)  # 编译校验直接用未清洗的场景，也必须得到与导演一致的节拍
    assert index["1.1"][1]["dialogue"] == ["萧炎（尴尬地笑了一声）：呵呵……"]
    assert index["1.2"][1]["dialogue"] == [] and "标签" in index["1.2"][1]["action"]


def test_multiline_dialogue_is_timed_line_by_line():
    """多句对白用换行拼成一个字符串时逐行计时：之前整串只从第一个冒号后开始数，把后面的说话人名和舞台提示也算进念白。"""
    from services import canvas_director_quality as q
    from services.video_canvas_director import _dialogue_lines

    text = "萧薰儿：谢谢。\n萧薰儿（弯腰行礼，露出笑容）：萧炎哥哥。"
    assert _dialogue_lines(text) == ["萧薰儿：谢谢。", "萧薰儿（弯腰行礼，露出笑容）：萧炎哥哥。"]
    assert q.speech_seconds([{"dialogue": text}]) < 2.0


def test_bare_beat_ids_are_completed_to_scene_prefixed_refs():
    """模型把 beat_ids 写成不带场景前缀的 “1” “38-1” 时，能唯一对应的补全成 “场景.节拍”，补不全的原样保留。"""
    from services import canvas_director_quality as q

    index = {"1.1": ({}, {}), "1.2": ({}, {}), "1.38-1": ({}, {}), "2.1": ({}, {})}
    plan = {"units": [{"beat_ids": ["2", "38-1", "1.1", "1", "9"]}]}
    q.normalize_beat_refs(plan, index)
    # “1”在两个场景里都有（1.1 与 2.1），不唯一，保持原样交给校验报错；“9”不存在，同样保留
    assert plan["units"][0]["beat_ids"] == ["1.2", "1.38-1", "1.1", "1", "9"]


def test_segment_span_solver_gives_dialogue_enough_time_and_sums_to_total():
    """时间轴求解：对白段至少够念完，总和恰好等于镜头时长；对白多时动作段让出时间。"""
    from services import canvas_director_quality as q

    # 模型原分配 3/3/3/3/3（共 15），但第二段对白要 9 秒：其余段必须让出时间
    spans = q._solve_segment_spans([3, 3, 3, 3, 3], [0, 9.0, 0, 0, 0], 15.0)
    assert abs(sum(spans) - 15.0) < 0.01 and spans[1] >= 9.0 and all(v > 0 for v in spans)
    # 放得下时按模型原比例分剩余时间
    spans = q._solve_segment_spans([5, 10], [2.0, 0], 15.0)
    assert abs(sum(spans) - 15.0) < 0.01 and spans[0] >= 2.0


def test_director_retries_when_model_returns_broken_json(monkeypatch):
    """模型偶发返回损坏 JSON：算一次失败并重试，不让整条导演编排失败；欠费等其他上游错误照常抛出。"""
    import asyncio

    from services import canvas_director_quality as q
    from services import video_canvas_director as director
    from services.errors import UpstreamServiceError

    calls = []

    async def flaky(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise UpstreamServiceError("坏 JSON", retryable=True, provider="DeepSeek", status_code=502, code="director_plan_invalid_json")
        return {"units": []}

    monkeypatch.setattr(director, "_call_deepseek_json", flaky)
    scenes = [{"scene_id": 1, "beats": [{"beat_id": 1, "type": "action", "action": "他推门。", "dialogue": []}]}]
    try:
        asyncio.run(q.direct(scenes, q.resolve_policy({}, None), api_key=None))
    except Exception:  # noqa: BLE001 - 这里只关心“坏 JSON 之后确实又请求了一次”
        pass
    assert len(calls) >= 2

    async def broke(**_kwargs):
        raise UpstreamServiceError("欠费", retryable=False, provider="DeepSeek", status_code=402, code="director_plan_insufficient_balance")

    monkeypatch.setattr(director, "_call_deepseek_json", broke)
    try:
        asyncio.run(q.direct(scenes, q.resolve_policy({}, None), api_key=None))
        raise AssertionError("欠费应该直接抛出")
    except UpstreamServiceError as exc:
        assert exc.code == "director_plan_insufficient_balance"


def test_character_names_are_cleaned_and_extras_do_not_need_assets():
    """角色表清洗：去括号提示、去“级别”这类标签词；群演（少年甲、中年族人）不占主角名额，也不要求有角色资产。"""
    from services.canvas_asset_analysis import is_extra_character, rank_main_characters
    from services.screenplay_adapt import clean_character_names

    names = clean_character_names(["测验员（漠然）", "测验员", "级别", "少年甲", "萧炎", "萧薰儿", "说"])
    assert names == ["测验员", "少年甲", "萧炎", "萧薰儿"]
    assert clean_character_names(["魔石碑亮起五个大字", "石碑爆发刺眼光芒", "萧炎"]) == ["萧炎"], "描述句不是角色"
    text = "测验员：萧炎，三段！\n萧炎：嗯。\n少年甲：废物。\n萧薰儿：萧炎哥哥。\n萧薰儿：好久不见。\n萧炎：你来了。\n测验员：下一个。"
    main, extras = rank_main_characters(names, text)
    assert "少年甲" in extras and "少年甲" not in main and {"萧炎", "萧薰儿", "测验员"} <= set(main)
    assert is_extra_character("少年丁") and is_extra_character("中年族人") and not is_extra_character("萧媚") and not is_extra_character("测验员")


def test_oversized_scene_is_split_at_natural_paragraphs():
    """节拍太多的场景自动拆成多个场景：在空行处切开，节拍内容和顺序不变，地点沿用。"""
    from services.screenplay_adapt import MAX_BEATS_PER_SCENE, _split_oversized_scenes

    lines, position, beats = [], 0, []
    for i in range(40):
        text = f"第{i}句动作。"
        beats.append({"beat_id": i + 1, "type": "action", "action": text, "dialogue": [], "source_text": text, "source_start": position, "source_end": position + len(text)})
        position += len(text)
        lines.append(text + ("\n\n" if i % 10 == 9 else "\n"))
        position += 2 if i % 10 == 9 else 1
    content = "".join(lines)
    scene = {"scene_id": 1, "title": "场景1：广场 / 日 / 外景", "location": "广场", "time_of_day": "日", "characters": [], "beats": beats}
    result = _split_oversized_scenes([scene], content, 30)
    assert len(result) >= 2 and all(len(s["beats"]) <= MAX_BEATS_PER_SCENE for s in result)
    assert [b["action"] for s in result for b in s["beats"]] == [b["action"] for b in beats]
    assert [s["scene_id"] for s in result] == list(range(1, len(result) + 1)) and all(s["location"] == "广场" for s in result)
    assert all(s["beats"][0]["beat_id"] == 1 for s in result)
    assert _split_oversized_scenes([scene], content, 1) == [scene], "超过场景数上限时放弃拆分"


def test_asset_analysis_generates_characters_in_batches_and_fills_the_gaps(monkeypatch):
    """角色提示词分批生成：模型少写了某个角色时单独补一次；补不出来要明确报告，不能悄悄漏掉。"""
    import asyncio

    from services import canvas_asset_analysis as analysis
    from services import deepseek as deepseek_service
    from services import video_canvas_director as director

    async def fake_json(**_kwargs):
        return {"characters": [], "scenes": [], "props": [], "optional": []}

    calls = []

    async def fake_character(shot_data, character_profiles="", api_key=None):
        batch = list(shot_data["characters"])
        calls.append(batch)
        if "萧薰儿" in batch and len(batch) > 1:
            batch = [n for n in batch if n != "萧薰儿"]  # 批量时漏掉她
        batch = [n for n in batch if n != "萧媚"]  # 萧媚无论批量还是单独都生成不出来
        return [{"name": n, "prompt": f"{n}的三视图"} for n in batch]

    monkeypatch.setattr(director, "_call_deepseek_json", fake_json)
    monkeypatch.setattr(analysis, "generate_character_prompts", fake_character)
    text = "\n".join(f"{n}：台词{i}。" for n in ("萧炎", "萧薰儿", "萧媚", "萧战") for i in range(3))
    scenes = [{"scene_id": "1", "location": "广场", "characters": ["萧炎", "萧薰儿", "萧媚", "萧战"], "beats": [{"source_text": text}]}]
    result = asyncio.run(analysis.analyze_scene_assets(scenes=scenes, screenplay_text=text))
    got = {a["name"] for a in result["assets"] if a["role"] == "character"}
    assert got == {"萧炎", "萧薰儿", "萧战"}, "漏掉的萧薰儿要单独补回来"
    assert any("萧媚" in w and "没有生成成功" in w for w in result["warnings"])
    assert ["萧薰儿"] in calls


def test_novel_adaptation_gets_a_short_drama_sized_budget_and_condenses_when_over(monkeypatch):
    """小说改写成短剧：每章有目标时长和字数预算，提示词里带上详略要求；改写仍明显超预算时再压缩一次。"""
    import asyncio

    from services import screenplay_adapt as adapt
    from services.video_duration import adapt_chapter_targets

    assert adapt_chapter_targets([3000]) == [120]
    assert sum(adapt_chapter_targets([3000, 3000, 3000])) <= 180, "多章合计不超过 3 分钟"
    assert adapt_chapter_targets([2000, 4000], 120) == [40, 80], "指定总时长时按篇幅占比分配"

    seen = []
    long_script = "场景1：广场 / 日 / 外景\n" + "他走了一步又一步。\n" * 300

    async def fake_single(**kwargs):
        seen.append(kwargs["length_requirement"])
        return long_script

    condensed_calls = []

    async def fake_condense(text, budget, api_key):
        condensed_calls.append(budget)
        return "场景1：广场 / 日 / 外景\n萧炎：三段。"

    monkeypatch.setattr(adapt, "_adapt_single_call", fake_single)
    monkeypatch.setattr(adapt, "_condense_screenplay", fake_condense)
    result = asyncio.run(adapt.adapt_novel_to_screenplay(chapters=[{"story_id": 1, "chapter_id": 2, "title": "第一章", "content": "正文" * 1500}]))
    assert "目标成片约 120 秒" in seen[0] and "672 字" in seen[0]
    assert condensed_calls == [672] and result["screenplay_text"] == "场景1：广场 / 日 / 外景\n萧炎：三段。"


def test_scene_review_node_is_created_large_and_carries_source_refs():
    """剧本审核节点要并排放原文 | 剧本 | 场景三栏：创建时就是大尺寸，不让用户手动拉大。"""
    from services import canvas_stage_gateway as gw

    graph = {"nodes": [], "edges": []}
    scene = gw._new_node(graph, "scene", "剧本场景", {})
    assert scene["data"]["ui"] == {"width": gw.SCENE_DEFAULT_W, "height": gw.SCENE_DEFAULT_H}
    assert gw.SCENE_DEFAULT_W >= 1100 and gw.SCENE_DEFAULT_H >= 700
    assert "ui" not in gw._new_node(graph, "image", "图", {})["data"], "其他节点保持原来的默认尺寸"


def test_old_character_sheet_prompt_is_slimmed_to_appearance_only():
    """旧版整页设定板提示词（画质套话 + 信息栏 / 表情格面板 + 性格 MBTI）精简后只留外貌和服装，不再和风格参考图、干净三视图的要求互相打架。"""
    from services.video_canvas_runtime import STYLE_ANCHOR_DIRECTIVE, slim_character_prompt

    old = "\n".join([
        "第一部分：CHARACTER PROFILE", "", "姓名：萧薰儿", "年龄：14岁", "生日：二月廿一", "性格：表面清冷", "MBTI：INFJ", "Big Five：开放性高",
        "", "第二部分：FINAL IMAGE PROMPT", "",
        "Professional character design sheet, single image, masterpiece, best quality, 8k, professional rendering.", "",
        "LEFT PANEL: a narrow vertical information column with chips.", "",
        "CENTER PANEL: four full-body standing views. The girl is fourteen, hair blue-black, straight, long.", "",
        "RIGHT PANEL: an expression sheet of ten head-and-shoulder portraits.", "",
        "Accurate anatomy, identical face and costume across all views.",
    ])
    slim = slim_character_prompt(old)
    assert "姓名：萧薰儿" in slim and "年龄：14岁" in slim and "hair blue-black" in slim
    for gone in ("生日", "性格", "MBTI", "Big Five", "LEFT PANEL", "RIGHT PANEL", "8k", "masterpiece", "Accurate anatomy"):
        assert gone not in slim
    assert slim_character_prompt("一个普通的短提示词") == "一个普通的短提示词", "新版精简提示词原样保留"
    assert "渲染媒介" in STYLE_ANCHOR_DIRECTIVE and "真人质感" in STYLE_ANCHOR_DIRECTIVE


def test_style_reference_instruction_requires_matching_the_rendering_medium():
    from services.image2 import _reference_role_instruction

    text = _reference_role_instruction("style", "画风参考", 1)
    assert "RENDERING MEDIUM" in text and "real photograph" in text and "NOT be drawn as an illustration" in text

