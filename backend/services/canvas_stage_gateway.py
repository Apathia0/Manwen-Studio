"""画布 Agent 阶段执行入口：复用业务校验，并把阶段产物落到同一张图。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import uuid
from typing import Any

from fastapi import HTTPException

from models import VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion


STAGES = ("screenplay", "split", "director", "assets", "compile", "images", "videos", "concat")


def _config(node: dict) -> dict:
    return node.setdefault("data", {}).setdefault("config", {})


def _node(graph: dict, kind: str, node_id: Any = None) -> dict:
    candidates = [n for n in graph.get("nodes", []) if n.get("type") == kind and (not node_id or n.get("id") == node_id)]
    if len(candidates) != 1:
        hint = "（画布上可能有尚未保存的节点，请先保存画布后再继续）" if not candidates else ""
        raise HTTPException(422, f"请明确选择一个{kind}节点，目前匹配到 {len(candidates)} 个{hint}")
    return candidates[0]


def _new_node(graph: dict, kind: str, label: str, config: dict, *, x: float | None = None, y: float = 100) -> dict:
    if x is None:
        x = max((float((n.get("position") or {}).get("x") or 0) for n in graph["nodes"]), default=-400) + 450
    data: dict = {"label": label, "config": config}
    if kind == "scene":
        data["ui"] = {"width": SCENE_DEFAULT_W, "height": SCENE_DEFAULT_H}
    node = {"id": f"{kind}-{uuid.uuid4().hex[:16]}", "type": kind, "position": {"x": x, "y": y}, "data": data}
    graph["nodes"].append(node)
    return node


def _connect(graph: dict, source: dict, target: dict, output: str, input_key: str, sequence: int = 0) -> None:
    graph.setdefault("edges", []).append({
        "id": f"edge-{uuid.uuid4().hex[:16]}", "source": source["id"], "target": target["id"],
        "sourceHandle": output, "targetHandle": input_key, "data": {"sequence": sequence},
    })


def _save(graph: dict, canvas, user, db, expected: int, summary: str) -> int:
    from routers import video_canvas as api

    locked = api._lock_canvas(canvas.id, user, db)
    if locked.definition_revision != expected:
        raise HTTPException(409, "画布已被修改，本次阶段结果未覆盖新内容，请重新审阅后继续")
    validation = api._validate_graph(graph)
    if not validation["valid"]:
        raise HTTPException(422, {"message": "阶段产物的画布连线无效", **validation})
    revision = expected + 1
    db.add(VideoCanvasVersion(canvas_id=canvas.id, version_no=revision, graph_json=deepcopy(graph), source="agent", change_summary=summary, created_by_user_id=user.id))
    locked.definition_revision = revision
    db.commit()
    return revision


def _definition_hash(graph: dict, node_id: str) -> str:
    """共享画布运行复用的定义指纹。"""
    from services.canvas_run_reuse import definition_hash

    return definition_hash(graph, node_id)


def _reusable_outputs(graph: dict, canvas_id: int, db, rerun_ids: set[str]) -> None:
    """仅复用定义仍相同的成功产物，防止进入下一阶段时重新付费生成上游。"""
    from services.canvas_run_reuse import _reusable_outputs as shared_reusable_outputs

    shared_reusable_outputs(graph, canvas_id, db, rerun_ids)


def api_scope(graph: dict, node_id: str) -> set[str]:
    from routers.video_canvas import _run_scope_node_ids
    return _run_scope_node_ids(graph, {node_id})


# 媒体节点默认 420x236（前端 nodeSize），单元格必须比节点大，否则相邻节点会互相压住
NODE_W = 420
NODE_H = 236
ASSET_CELL_W = 460
ASSET_CELL_H = 290
# 资产块只占两列：角色 / 场景 / 道具三类按顺序纵向分段堆叠（不再三类并排占三列），把横向空间留给分镜和视频
# 资产三栏：角色一列、道具一列、场景一列，放在场景审核节点右侧、分镜区左侧（自左向右：剧本 → 场景审核 → 资产 → 分镜 → 视频）
ASSET_SCENE_GAP = 160
# 分镜：每个镜头一行，分镜图在左、视频在右，整体在场景节点右侧自上而下排列
SHOT_ROW_H = 300
SHOT_COL_W = 500
SHOT_SCENE_GAP = 200
# 分镜区与资产块之间至少留的横向间距：分镜永远排在资产块右边，不与它重叠
SHOT_ASSET_GAP = 160
# 剧本审核节点要并排放“小说原文 | 改写剧本 | 场景审核”三栏，默认就要足够大，不让用户自己手动拉大
SCENE_DEFAULT_W = 1280
SCENE_DEFAULT_H = 800
_ASSET_ORDER = ("character", "scene", "prop")
_ASSET_COLUMN_ORDER = ("character", "prop", "scene")


def _rect(node: dict) -> tuple[float, float, float, float]:
    ui = (node.get("data") or {}).get("ui") or {}
    p = node.get("position") or {}
    x, y = float(p.get("x") or 0), float(p.get("y") or 0)
    w, h = float(ui.get("width") or NODE_W), float(ui.get("height") or NODE_H)
    return x, y, x + w, y + h


def _avoid_overlaps(graph: dict, moved: list[dict]) -> None:
    """把刚布局的节点依次向下推，直到不与任何其他节点重叠（已有节点位置保持不动）。"""
    moved_ids = {n["id"] for n in moved}
    placed = [n for n in graph["nodes"] if n["id"] not in moved_ids and n.get("type") != "container"]
    for node in moved:
        for _ in range(200):
            left, top, right, bottom = _rect(node)
            hit = next((o for o in placed if (r := _rect(o)) and left < r[2] - 1 and right > r[0] + 1 and top < r[3] - 1 and bottom > r[1] + 1), None)
            if hit is None:
                break
            node["position"]["y"] = _rect(hit)[3] + 40
        placed.append(node)


def _layout_shots(graph: dict, scene_node: dict, pairs: list[tuple[int, dict, dict]]) -> None:
    """新建的 分镜图 + 视频 按镜头序号一行一个，放在场景节点右侧自上而下排列，便于逐镜头编排。"""
    if not pairs:
        return
    scene_rect = _rect(scene_node)
    ui = (scene_node.get("data") or {}).get("ui") or {}
    width = float(ui.get("width") or SCENE_DEFAULT_W)
    origin_x = scene_rect[0] + width + SHOT_SCENE_GAP
    asset_rights = [_rect(n)[2] for n in graph["nodes"] if _config(n).get("asset_role") in _ASSET_ORDER and _rect(n)[0] >= scene_rect[0] - 1]
    if asset_rights:
        # 已有资产节点：分镜区从资产块右边缘再往右，避免被资产挤住后只能往下硬推
        origin_x = max(origin_x, max(asset_rights) + SHOT_ASSET_GAP)
    origin_y = scene_rect[1]
    ordered = sorted(pairs, key=lambda item: item[0])
    for row, (_, storyboard, movie) in enumerate(ordered):
        storyboard["position"] = {"x": origin_x, "y": origin_y + row * SHOT_ROW_H}
        movie["position"] = {"x": origin_x + SHOT_COL_W, "y": origin_y + row * SHOT_ROW_H}
    _avoid_overlaps(graph, [n for _, a, b in ordered for n in (a, b)])


def _layout_assets_by_kind(graph: dict, scene_node: dict, asset_nodes: list[dict]) -> None:
    """资产按类型分三栏：角色一列、道具一列、场景一列，自上而下排，放在场景审核节点右侧。

    分镜 / 视频区排在资产三栏的右边（见 _layout_shots），整体自左向右：剧本 → 场景审核 → 资产 → 分镜 → 视频。
    只重排本次资产分析涉及的节点；用户之后手动拖动的位置不会被再次覆盖（只在分析时布局一次）。
    """
    position = scene_node.get("position") or {}
    width = float(((scene_node.get("data") or {}).get("ui") or {}).get("width") or SCENE_DEFAULT_W)
    top = float(position.get("y") or 0)
    cursor_x = float(position.get("x") or 0) + width + ASSET_SCENE_GAP
    for kind in _ASSET_COLUMN_ORDER:
        group = [n for n in asset_nodes if _config(n).get("asset_role") == kind]
        if not group:
            continue
        for row, node in enumerate(group):
            node["position"] = {"x": cursor_x, "y": top + row * ASSET_CELL_H}
        cursor_x += ASSET_CELL_W
    _avoid_overlaps(graph, asset_nodes)


def _shot_text(config: dict) -> str:
    """一个镜头的全部文字：提示词、标题、摘要、对白 / 动作节拍。资产是否出现在这个镜头里，只看这些文字里有没有提到它。"""
    parts = [str(config.get(key) or "") for key in ("prompt", "storyboard_prompt", "video_prompt", "title", "story_summary")]
    beats = config.get("source_beats")
    if beats:
        parts.append(json.dumps(beats, ensure_ascii=False, default=str))
    return " ".join(parts)


def _mention_count(text: str, asset: dict) -> int:
    name = str(_config(asset).get("asset_name") or "").strip()
    return text.count(name) if name else 0


def select_shot_assets(config: dict, assets: list[dict]) -> dict[str, list[dict]]:
    """判断哪些资产真的出现在这个镜头里：只在镜头文字里被提到的角色 / 道具才连线（按提到次数从多到少），
    场景资产最多连 1 个（被提到的优先，否则取该分场景的第一个场景图）。
    导演记录的“出场角色”列表常常是整个场景的所有人，甚至混进非角色的词，不能作为依据。"""
    text = _shot_text(config)
    scene_ids = {str(v) for v in config.get("source_scene_ids", [])}

    def mentioned(role: str) -> list[dict]:
        found = [a for a in assets if _config(a).get("asset_role") == role and _mention_count(text, a) > 0]
        return sorted(found, key=lambda a: -_mention_count(text, a))

    scene_candidates = [a for a in assets if _config(a).get("asset_role") == "scene" and scene_ids & {str(v) for v in _config(a).get("scene_ids", [])}]
    scenes = sorted(scene_candidates, key=lambda a: -_mention_count(text, a))[:1]
    return {"character": mentioned("character"), "prop": mentioned("prop"), "scene": scenes}


# 分镜图出图时最多带的参考图：角色、道具各设上限，避免一个镜头塞满不相干的图
STORYBOARD_REF_MAX_CHARACTERS = 6
STORYBOARD_REF_MAX_PROPS = 2


def _bind_assets(graph: dict, db=None) -> None:
    """把统一资产连到真正用到它们的分镜 / 视频节点：镜头文字里提到的角色、道具，加上所属分场景的场景图。"""
    graph["edges"] = [e for e in graph.get("edges", []) if not (e.get("data") or {}).get("agent_asset_binding")]
    assets = [n for n in graph["nodes"] if n.get("type") == "image" and not _config(n).get("stale") and _config(n).get("asset_role") in {"character", "scene", "prop"}]
    for shot in graph["nodes"]:
        config = _config(shot)
        if shot.get("type") != "image" or config.get("node_role") != "storyboard":
            continue
        picked = select_shot_assets(config, assets)
        chosen = [*picked["character"][:STORYBOARD_REF_MAX_CHARACTERS], *picked["prop"][:STORYBOARD_REF_MAX_PROPS], *picked["scene"]]
        for asset in chosen:
            if any(e.get("source") == asset["id"] and e.get("target") == shot["id"] and e.get("targetHandle") == "references" for e in graph.get("edges", [])):
                continue
            _connect(graph, asset, shot, "image", "references")
            graph["edges"][-1]["id"] = "asset-ref-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{asset['id']}:{shot['id']}:image:references").hex[:20]
            graph["edges"][-1]["data"]["agent_asset_binding"] = True
    _bind_video_references(graph, assets, db)


# 视频参考图的默认上限；具体以所选视频模型声明的 limits.max_reference_images 为准（最大 9）
VIDEO_REF_DEFAULT_LIMIT = 9


def _video_reference_limit(config: dict, db) -> int:
    """该视频节点最多能带几张参考图：取所选模型声明的上限，没有声明或没选模型就按 9。"""
    if db is None:
        return VIDEO_REF_DEFAULT_LIMIT
    from services.video_canvas_runtime import _video_model_capabilities

    capabilities = _video_model_capabilities(config, db)
    limits = capabilities.get("limits") if isinstance(capabilities, dict) else None
    declared = limits.get("max_reference_images") if isinstance(limits, dict) else None
    if isinstance(declared, int) and not isinstance(declared, bool) and declared >= 0:
        return min(VIDEO_REF_DEFAULT_LIMIT, declared)
    return VIDEO_REF_DEFAULT_LIMIT


def _bind_video_references(graph: dict, assets: list[dict], db=None) -> None:
    """视频节点除了分镜图，还要连上真正出现在这个镜头里的角色、场景、道具参考图。

    连线追加在分镜图连线之后，输入顺序即 分镜图 → 角色 → 场景 → 道具，与提示词里的 @图片N 一致。
    数量按所选视频模型声明的参考图上限分配（最大 9）：已有连线先占名额，剩下的按上面的优先级分，名额不够先丢道具。
    """
    for shot in graph["nodes"]:
        config = _config(shot)
        if shot.get("type") != "video" or not config.get("unit_id") or config.get("stale"):
            continue
        picked = select_shot_assets(config, assets)
        used = sum(1 for e in graph.get("edges", []) if e.get("target") == shot["id"] and e.get("targetHandle") == "image")
        slots = max(0, _video_reference_limit(config, db) - used)
        for asset in [*picked["character"], *picked["scene"], *picked["prop"]][:slots]:
            if any(e.get("source") == asset["id"] and e.get("target") == shot["id"] and e.get("targetHandle") == "image" for e in graph.get("edges", [])):
                continue
            _connect(graph, asset, shot, "image", "image")
            graph["edges"][-1]["id"] = "asset-ref-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{asset['id']}:{shot['id']}:image:image").hex[:20]
            graph["edges"][-1]["data"]["agent_asset_binding"] = True


async def execute_agent_canvas_stage(canvas_id: int, stage: str, parameters: dict, request, db, graph_snapshot: dict[str, Any] | None = None) -> dict:
    """仅由通过服务端权限门禁的 Agent 动作调用；不信任模型提供的用户或版本。

    graph_snapshot 可选：浏览器实时图快照，传入且有效时优先于数据库最新版本作为基图
    （与 get_canvas_graph 的快照优先逻辑一致）；不传时保持原有读库行为，向后兼容。
    校验仍走 _validate_graph 与 definition_revision 乐观锁。
    """
    from routers import video_canvas as api
    from schemas import (VideoCanvasScreenplayImportRequest, VideoCanvasScreenplaySplitRequest,
                         VideoCanvasDirectorPlanRequest, VideoCanvasAssetAnalysisRequest,
                         VideoCanvasCompileScenesRequest, VideoCanvasRunRequest, VideoCanvasRunConfirmRequest)

    if stage not in STAGES:
        raise HTTPException(422, "不支持的制作阶段")
    user = api._require_user(request, db)
    canvas = api._require_canvas(canvas_id, user, db)
    revision = canvas.definition_revision
    # 浏览器实时快照优先作为基图（含用户未保存的本地修改）；写合约仍锚定数据库 revision。
    if isinstance(graph_snapshot, dict) and isinstance(graph_snapshot.get("nodes"), list):
        graph = deepcopy(graph_snapshot)
        # 快照只负责节点/连线；画布级设置（画风、比例、生产设置、分组）缺失时以数据库最新版本补齐，避免写库时抹掉。
        persisted_graph = api._latest_version(canvas_id, db).graph_json or {}
        for key in ("metadata", "groups", "schema_version"):
            if key not in graph and key in persisted_graph:
                graph[key] = deepcopy(persisted_graph[key])
    else:
        graph = deepcopy(api._latest_version(canvas_id, db).graph_json)
    p = dict(parameters or {})
    for left, right in (("node_id", "screenplay_node_id"), ("node_ids", "target_node_ids")):
        if left in p and right in p and p[left] != p[right]:
            raise HTTPException(422, "阶段目标参数冲突，请明确唯一操作范围")
    action_id = p.get("agent_action_id")
    if not action_id:
        raise HTTPException(403, "制作阶段必须通过 Agent 权限门禁")
    action_key = str(action_id)
    existing_run = db.query(VideoCanvasRun).filter(VideoCanvasRun.canvas_id == canvas_id, VideoCanvasRun.idempotency_key == f"canvas-agent-action:{action_key}").first()
    if existing_run:
        if existing_run.status == "awaiting_approval":
            await api.confirm_video_canvas_run(canvas_id, existing_run.id, VideoCanvasRunConfirmRequest(), request, db)
        return {"ok": True, "canvas_id": canvas_id, "stage": stage, "idempotent": True, "pending_task": {"canvas_id": canvas_id, "run_id": existing_run.id, "status": existing_run.status}}
    metadata = graph.setdefault("metadata", {})
    completed = metadata.setdefault("agent_stage_actions", {})
    if action_key in completed:
        previous_result = completed[action_key]
        if previous_result.get("pending_task"):
            run = db.get(VideoCanvasRun, previous_result["pending_task"]["run_id"])
            return {**previous_result, "pending_task": {**previous_result["pending_task"], "status": run.status if run else "missing"}, "idempotent": True}
        return {**previous_result, "idempotent": True}
    if p.get("expected_definition_revision") != revision:
        raise HTTPException(409, "画布已在本次授权后发生变化，请重新审阅制作阶段")
    # 仅可信入口（全自动模式）会注入该标记；模型传入的同名参数在入口处已被覆盖。
    auto_approve = p.get("auto_approve_scenes") is True
    if auto_approve and stage in {"images", "videos", "concat"}:
        # 全自动只负责把节点编排完整；付费生成任务必须由用户在画布上亲自提交。
        raise HTTPException(409, "全自动模式只编排画布节点，出图、视频和合片任务请由用户在画布上提交")
    if graph_snapshot is not None and stage in {"split", "director", "assets", "compile"}:
        # 这些阶段会调用只读数据库图的业务接口；浏览器快照（含未保存的批准/编辑）
        # 必须先落库，否则网关与业务接口看到的是两份不同的图。
        db_graph = api._latest_version(canvas_id, db).graph_json or {}
        if (db_graph.get("nodes"), db_graph.get("edges")) != (graph.get("nodes"), graph.get("edges")):
            revision = _save(graph, canvas, user, db, revision, "同步浏览器画布快照")
    result: dict[str, Any] = {"ok": True, "canvas_id": canvas_id, "stage": stage}
    settings = metadata.setdefault("production_settings", {})
    for key in ("aspect_ratio", "image_model_id", "video_model_id", "format", "user_constraints"):
        # 画面比例是画布级设置（开局选定、界面里调整）：助手传来的比例不覆盖已选定的值，保证整部作品一致
        if key in p and not (key == "aspect_ratio" and settings.get("aspect_ratio") in {"9:16", "16:9", "1:1", "4:3", "3:4"}):
            settings[key] = p[key]
    aspect = str(settings.get("aspect_ratio") or "16:9")
    if aspect not in {"9:16", "16:9", "1:1", "4:3", "3:4"}:
        raise HTTPException(422, "请明确支持的画幅比例")

    if stage == "screenplay":
        content = str(p.get("content") or p.get("screenplay_text") or "").strip()
        source_refs = []
        if p.get("sources"):
            adapted = await api.import_screenplay(canvas_id, VideoCanvasScreenplayImportRequest(sources=p["sources"]), request, db)
            content, source_refs = adapted["screenplay_text"], adapted["source_refs"]
        if not content:
            raise HTTPException(422, "请先交流并完成剧本正文，或明确要改编的小说章节")
        # 用户给了目标总时长时，剧本篇幅必须与之匹配：导演阶段只会保证对白动作放得下，不会替用户删剧情，
        # 篇幅超标的剧本拆出来的镜头总时长会成倍超出（60 秒的要求拍出 150 秒）。
        from services.video_duration import estimate_screenplay_seconds, parse_target_duration_seconds, screenplay_char_budget, target_duration_ceiling

        target_seconds = parse_target_duration_seconds(str(p.get("user_constraints") or settings.get("user_constraints") or ""))
        if target_seconds:
            settings["target_duration_seconds"] = target_seconds
            estimated = estimate_screenplay_seconds(content)
            ceiling = target_duration_ceiling(target_seconds)
            if estimated > ceiling:
                budget = screenplay_char_budget(ceiling)
                raise HTTPException(
                    422,
                    f"剧本篇幅约需 {estimated:.0f} 秒，超出了短视频的合理时长上限 {ceiling} 秒（参考时长是 {target_seconds} 秒，短剧单集不宜超出太多）。"
                    f"请精简到约 {budget} 字以内：删减次要对白和重复动作，保留因果交代、钩子、反转与结尾金句。",
                )
        # 逻辑审稿：规则查不出“主角凭什么赢”“反转有没有铺垫”，交给文本模型按清单审。
        # 审稿不通过时服务端自己按意见改写重审（最多两轮），不把问题抛给用户或助手；
        # 从小说章节改编来的剧本是原文，不改写；取不到文本模型凭证或服务出错时直接放行。
        if not p.get("sources"):
            from services.canvas_script_review import format_issues, improve_screenplay

            try:
                review_key = api._canvas_deepseek_api_key(request, db)
            except Exception:  # noqa: BLE001
                review_key = None
            else:
                ceiling_seconds = target_duration_ceiling(target_seconds) if target_seconds else 180
                content, issues, revised_rounds = await improve_screenplay(
                    content, str(p.get("user_constraints") or settings.get("user_constraints") or ""), screenplay_char_budget(ceiling_seconds), review_key,
                )
                if revised_rounds:
                    result["script_auto_revised"] = revised_rounds
                if issues:
                    result["script_review_warnings"] = format_issues(issues)
        # 短镜头剧本不能用字符数判定质量；保真拆分与导演容量校验负责后续可拍性。
        if p.get("node_id"):
            target = _node(graph, "screenplay", p["node_id"])
        else:
            # 未指定节点时复用图中已有的有效剧本节点，避免重复创建同类节点（对齐 split 分支的 existing 检测）。
            existing = [n for n in graph["nodes"] if n.get("type") == "screenplay" and not _config(n).get("stale")]
            if len(existing) > 1:
                raise HTTPException(422, "同一画布存在多个有效剧本节点，请先明确保留哪一版")
            target = existing[0] if existing else _new_node(graph, "screenplay", str(p.get("title") or "剧本"), {})
        _config(target).update({"content": content, "source_refs": source_refs})
        result.update(node_id=target["id"], content_chars=len(content), next_stage="split")
    elif stage == "split":
        screenplay = _node(graph, "screenplay", p.get("node_id") or p.get("screenplay_node_id"))
        split = await api.screenplay_split(canvas_id, VideoCanvasScreenplaySplitRequest(node_id=screenplay["id"]), request, db)
        if split.get("truncated"):
            raise HTTPException(422, "拆分结果被截断，请把剧本划分为较小段落后重新拆分；未发布不完整场景")
        scenes = [{**u, "approved": False} for u in split["units"]]
        existing = [n for n in graph["nodes"] if n.get("type") == "scene" and _config(n).get("source_screenplay_node") == screenplay["id"]]
        if len(existing) > 1:
            raise HTTPException(422, "同一剧本存在多个场景节点，请先明确保留哪一版")
        target = existing[0] if existing else _new_node(graph, "scene", "剧本场景", {})
        _config(target).update({"scenes": scenes, "approved": False, "scene_count": len(scenes), "source_screenplay_node": screenplay["id"], "source_content": _config(screenplay)["content"],
                                  # 小说改写来的剧本：带上来源章节引用，审核节点据此取回小说原文与剧本对照
                                  "source_refs": list(_config(screenplay).get("source_refs") or [])})
        _config(target).pop("director_plan", None)
        _config(target).pop("director_plan_hash", None)
        for old in graph["nodes"]:
            if _config(old).get("source_scene_node") == target["id"]:
                _config(old)["stale"] = True
        # 旧剧本留下的孤儿资产：所属场景节点已经不存在、又还没生成过图 / 没锁定的，收起来，免得占位、混进待生成数量、让进度看起来乱序
        live_scene_ids = {n["id"] for n in graph["nodes"] if n.get("type") == "scene"}
        for old in graph["nodes"]:
            old_config = _config(old)
            owner = old_config.get("asset_scene_node") or old_config.get("source_scene_node")
            if old_config.get("asset_role") in _ASSET_ORDER and owner and owner not in live_scene_ids \
                    and not old_config.get("locked") and not isinstance(old_config.get("asset_id"), int) and not (old.get("data") or {}).get("result"):
                old_config["stale"] = True
        _config(screenplay)["content_hash"] = split["content_hash"]
        if not existing:
            _connect(graph, screenplay, target, "screenplay", "screenplay")
        result.update(scene_node_id=target["id"], scene_count=len(scenes), next_stage="director")
    elif stage in {"director", "assets", "compile"}:
        target = _node(graph, "scene", p.get("scene_node_id"))
        config = _config(target)
        if not config.get("approved"):
            # 场景内容审批与后续阶段授权是两个独立门禁；手动/询问模式不能因调用
            # director/assets/compile 而隐式接受未审阅的拆分结果。
            # 全自动模式下用户已授权整条流水线，网关代为批准并落库，标记来源以便追溯。
            if not auto_approve:
                raise HTTPException(409, "场景尚未批准，请先审阅并批准当前场景版本")
            config.update(approved=True, approved_by="agent_auto")
            revision = _save(graph, canvas, user, db, revision, "全自动模式批准场景")
        if stage == "director":
            # 历史画布的设置里可能残留早期版本误存的“细分镜头”重试提示，导演前先清掉
            from services.canvas_pipeline_runner import RETRY_HINT

            stored = str(settings.get("user_constraints") or "")
            if RETRY_HINT in stored:
                settings["user_constraints"] = stored.replace(RETRY_HINT, "").strip(" ；;")
            base_constraints = str(p.get("user_constraints") or settings.get("user_constraints") or "").strip()
            # retry_hint 只本次调用有效，不写入画布设置
            constraints = "；".join(part for part in (base_constraints, str(p.get("retry_hint") or "").strip()) if part)
            directed = await api.create_director_plan(canvas_id, VideoCanvasDirectorPlanRequest(scene_node_id=target["id"], video_model_id=settings.get("video_model_id"), user_constraints=constraints or None, expected_definition_revision=revision), request, db)
            config.update(director_plan=directed["plan"], director_plan_hash=directed["plan_hash"])
            selected_model = (directed["plan"].get("production_policy") or {}).get("model_id")
            if selected_model is not None:
                settings["video_model_id"] = selected_model
            result.update(scene_node_id=target["id"], unit_count=directed["unit_count"], warnings=directed["plan"].get("warnings", []), next_stage="assets")
        elif stage == "assets":
            analyzed = await api.analyze_canvas_assets(canvas_id, VideoCanvasAssetAnalysisRequest(scene_node_id=target["id"], expected_definition_revision=revision), request, db)
            if analyzed.get("failed_calls"):
                raise HTTPException(422, {"message": "资产分析不完整，请修正失败原因后重试", "warnings": analyzed.get("warnings", [])})
            ids = []
            created_asset_ids: set[str] = set()
            for old in graph["nodes"]:
                if _config(old).get("asset_scene_node") == target["id"]:
                    _config(old)["stale"] = True
            for asset in analyzed["assets"]:
                matched = next((n for n in graph["nodes"] if n.get("type") == "image" and _config(n).get("asset_scene_node") == target["id"] and _config(n).get("asset_role") == asset["role"] and _config(n).get("asset_name") == asset["name"]), None)
                asset_node = matched or _new_node(graph, "image", asset["name"], {})
                if not matched:
                    created_asset_ids.add(asset_node["id"])
                locked = bool(_config(asset_node).get("locked"))
                # 用户已锁定的形象保持素材与提示词不变：角色一致性优先于重新分析的结果。
                if matched and not locked and _config(matched).get("prompt") != asset["prompt"]:
                    _config(matched).pop("asset_id", None)
                update = {"asset_role": asset["role"], "asset_name": asset["name"], "asset_scene_node": target["id"], "stale": False, "scene_ids": asset.get("scene_ids", []), "aspect_ratio": aspect, "model_id": settings.get("image_model_id")}
                if not locked:
                    update["prompt"] = asset["prompt"]
                if asset.get("profile") and not _config(asset_node).get("profile_edited"):
                    update["profile"] = asset["profile"]
                _config(asset_node).update(update)
                ids.append(asset_node["id"])
            # 这次分析里已经没有的旧资产：没生成过图、没锁定的直接移除（连同连线），不在画布上留空壳；生成过图的保留，已标记过期。
            leftover = [
                n for n in graph["nodes"]
                if _config(n).get("asset_scene_node") == target["id"] and _config(n).get("asset_role") in _ASSET_ORDER and n["id"] not in ids
                and not _config(n).get("locked") and not _config(n).get("manual_added")
                and not isinstance(_config(n).get("asset_id"), int) and not (n.get("data") or {}).get("result")
            ]
            if leftover:
                gone = {n["id"] for n in leftover}
                graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in gone]
                graph["edges"] = [e for e in graph.get("edges", []) if e.get("source") not in gone and e.get("target") not in gone]
            # 新建的资产节点按类别分栏；已存在的（含用户挪动过的）保持原位置。
            fresh = [n for n in graph["nodes"] if n["id"] in ids and n["id"] in created_asset_ids]
            _layout_assets_by_kind(graph, target, fresh)
            # 未入选的场景/道具作为"可选资产"保存在场景节点上，用户在资产面板自行决定是否生成。
            config["asset_candidates"] = analyzed.get("candidates", [])
            _bind_assets(graph, db)
            result.update(node_ids=ids, warnings=analyzed.get("warnings", []), next_stage="compile", candidate_count=len(config["asset_candidates"]))
        else:
            if not config.get("director_plan"):
                raise HTTPException(422, "请先完成导演编排，再编译分镜与视频节点")
            compiled = await api.compile_scenes(canvas_id, VideoCanvasCompileScenesRequest(scene_node_ids=[target["id"]], video_model_id=settings.get("video_model_id"), director_plan=config["director_plan"], director_plan_hash=config.get("director_plan_hash"), expected_definition_revision=revision), request, db)
            created = []
            new_pairs: list[tuple[int, dict, dict]] = []
            unit_ids = {u["unit_id"] for u in compiled["compiled"]}
            for old in graph["nodes"]:
                if _config(old).get("source_scene_node") == target["id"] and _config(old).get("unit_id") not in unit_ids:
                    _config(old)["stale"] = True
            for unit in compiled["compiled"]:
                common = {k: v for k, v in unit.items() if k not in {"video_prompt", "storyboard_prompt"}}
                common.update(aspect_ratio=aspect, source_scene_node=target["id"])
                # 分镜节点出一张 16:9 的分镜板：导演拆了几个时间段就分几格；没有时间轴的单元仍出单帧
                from services.canvas_storyboard_sheet import REFERENCE_MODE as SHEET_MODE, SHEET_ASPECT_RATIO, build_sheet_prompt, panel_summary, sheet_panels

                panels = sheet_panels(unit)
                board_extra = {"reference_mode": SHEET_MODE, "sheet_panels": panel_summary(panels), "single_frame_prompt": unit["storyboard_prompt"], "aspect_ratio": SHEET_ASPECT_RATIO} if panels else {}
                video_extra = {"reference_mode": SHEET_MODE, "sheet_panels": panel_summary(panels)} if panels else {}
                board_prompt = build_sheet_prompt(unit, panels) if panels else (unit["storyboard_prompt"] or unit["video_prompt"])
                storyboard = next((n for n in graph["nodes"] if n.get("type") == "image" and _config(n).get("source_scene_node") == target["id"] and _config(n).get("unit_id") == unit["unit_id"]), None)
                movie = next((n for n in graph["nodes"] if n.get("type") == "video" and _config(n).get("source_scene_node") == target["id"] and _config(n).get("unit_id") == unit["unit_id"]), None)
                is_new = storyboard is None or movie is None
                storyboard = storyboard or _new_node(graph, "image", f"分镜 {unit['sequence']}：{unit['title']}", {})
                movie = movie or _new_node(graph, "video", f"镜头 {unit['sequence']}：{unit['title']}", {})
                if is_new:
                    new_pairs.append((int(unit.get('sequence') or 0), storyboard, movie))
                storyboard["data"]["config"] = {**common, "node_role": "storyboard", "prompt": board_prompt, "model_id": settings.get("image_model_id"), **board_extra}
                movie["data"]["config"] = {**common, "node_role": "video", "prompt": unit["video_prompt"], "model_id": None, "model_auto": True, **video_extra}
                if not any(e.get("source") == target["id"] and e.get("target") == storyboard["id"] for e in graph["edges"]):
                    _connect(graph, target, storyboard, "shot", "prompt")
                if not any(e.get("source") == storyboard["id"] and e.get("target") == movie["id"] for e in graph["edges"]):
                    _connect(graph, storyboard, movie, "image", "image")
                created.extend([storyboard["id"], movie["id"]])
            _layout_shots(graph, target, new_pairs)
            _bind_assets(graph, db)
            # 每个视频节点按自己的时长自动推荐视频模型（用户之后手动选过的不会被覆盖）
            from services.canvas_video_model import apply_auto_video_models

            apply_auto_video_models(graph, db, user.id)
            result.update(node_ids=created, next_stage="images")
    else:
        kind = "image" if stage == "images" else "video"
        requested_ids = set(p.get("node_ids") or p.get("target_node_ids") or [])
        targets = [n for n in graph["nodes"] if n.get("type") == kind and not _config(n).get("stale") and (not requested_ids or n["id"] in requested_ids)]
        if not targets or requested_ids - {n["id"] for n in targets}:
            raise HTTPException(422, "请明确当前阶段要生成的节点")
        if stage in {"images", "videos"}:
            model_key = "image_model_id" if stage == "images" else "video_model_id"
            for target_node in targets:
                if model_key in p:
                    if _config(target_node).get("model_id") != p[model_key]:
                        _config(target_node).pop("asset_id", None)
                    _config(target_node)["model_id"] = p[model_key]
                if "aspect_ratio" in p:
                    if _config(target_node).get("aspect_ratio") != aspect:
                        _config(target_node).pop("asset_id", None)
                    _config(target_node)["aspect_ratio"] = aspect
        by_id = {n["id"]: n for n in graph["nodes"]}
        for target_node in targets:
            scene = by_id.get(_config(target_node).get("source_scene_node"))
            if not scene:
                if _config(target_node).get("source_scene_node"):
                    raise HTTPException(409, "镜头来源场景已删除，请重新建立场景与镜头关联")
                continue
            scene_config = _config(scene)
            screenplay = by_id.get(scene_config.get("source_screenplay_node"))
            if screenplay and _config(screenplay).get("content") != scene_config.get("source_content"):
                raise HTTPException(409, "剧本已修改，请重新拆分和编排后生成，避免沿用旧版镜头")
            if _config(target_node).get("director_plan_hash") != scene_config.get("director_plan_hash"):
                raise HTTPException(409, "导演方案已修改，请重新编译镜头后生成")
            plan = scene_config.get("director_plan") or {}
            meta = plan.get("meta") or {}
            _, screenplay_hash, scene_hash = api._scene_screenplay_hashes(graph, scene_config, scene["id"])
            if meta.get("source_screenplay_hash") != screenplay_hash or meta.get("source_scene_revision") != scene_hash:
                raise HTTPException(409, "场景内容或导演来源已过期，请重新编排和编译后生成")
            if stage in {"images", "videos"} and plan.get("plan_version") != 2:
                raise HTTPException(422, "这是旧版展示板方案，请重新执行严格导演编排和分镜编译后制作")
        # 锁定的角色形象不参与显式返工，避免一键重来时角色换脸。
        rerun = {n["id"] for n in targets if not _config(n).get("locked")} if p.get("regenerate") else set()
        for node in graph["nodes"]:
            if node["id"] in rerun:
                _config(node).pop("asset_id", None)
        _reusable_outputs(graph, canvas_id, db, rerun)
        if stage in {"videos", "concat"}:
            dependencies = set().union(*(api_scope(graph, n["id"]) for n in targets))
            if any(n["id"] in dependencies and n.get("type") == "image" and not _config(n).get("asset_id") for n in graph["nodes"]):
                raise HTTPException(422, "视频依赖的图片尚未生成或已经过期，请先完成出图阶段")
        if stage == "concat":
            ordered = sorted(targets, key=lambda n: (int(_config(n).get("sequence") or 0), n["id"]))
            if any(not _config(n).get("asset_id") for n in ordered):
                raise HTTPException(422, "还有未完成或已过期的视频镜头，请先生成完成后再合片")
            sizes = {"9:16": "720x1280", "16:9": "1280x720", "1:1": "1024x1024", "4:3": "1024x768", "3:4": "768x1024"}
            final = _new_node(graph, "concat", str(p.get("title") or "完整成片"), {"resolution": sizes[aspect], "fps": 24})
            for index, node in enumerate(ordered):
                _connect(graph, node, final, "video", "videos", index)
            targets = [final]
        _save(graph, canvas, user, db, revision, f"准备 {stage} 阶段")
        revision += 1
        run_key = f"canvas-agent-action:{action_key}"
        planned = await api.create_video_canvas_run(
            canvas_id,
            VideoCanvasRunRequest(
                target_node_ids=[n["id"] for n in targets],
                expected_definition_revision=revision,
                idempotency_key=run_key,
                rerun_node_ids=sorted(rerun),
            ),
            request,
            db,
        )
        run = planned["run"]
        if run["status"] == "awaiting_approval":
            confirmed = await api.confirm_video_canvas_run(canvas_id, run["id"], VideoCanvasRunConfirmRequest(), request, db)
            run = confirmed["run"]
        result.update(pending_task={"canvas_id": canvas_id, "run_id": run["id"], "status": run["status"]}, node_ids=[n["id"] for n in targets], next_stage={"images": "videos", "videos": "concat", "concat": "review"}[stage])
        return {**result, "definition_revision": revision}
    completed[action_key] = {**result, "definition_revision": revision + 1}
    # 仅保留最近动作回执；真正的审批与恢复记录由动作表持久保存。
    if len(completed) > 100:
        for key in list(completed)[:-100]:
            completed.pop(key)
    revision = _save(graph, canvas, user, db, revision, f"Agent 完成 {stage} 阶段")
    return {**result, "definition_revision": revision}
