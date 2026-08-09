"""视频无限画布的独立工作流路由。"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from services.task_manager import task_manager
from services.video_canvas_runtime import execute_canvas_run
from models import (
    Chapter,
    ChapterVideoShot,
    ChapterVideoWorkflow,
    Story,
    User,
    VideoAsset,
    VideoCanvas,
    VideoCanvasLayout,
    VideoCanvasRun,
    VideoCanvasRunNode,
    VideoCanvasSyncRecord,
    VideoCanvasVersion,
)
from schemas import (
    VideoCanvasCreate,
    VideoCanvasGraphSave,
    VideoCanvasImportRequest,
    VideoCanvasLayoutSave,
    VideoCanvasRunRequest,
    VideoCanvasRunConfirmRequest,
    VideoCanvasUpdate,
)


router = APIRouter()


_LEGACY_NODE_CATALOG: dict[str, dict[str, Any]] = {
    "text": {
        "label": "文本", "category": "输入", "icon": "Type",
        "inputs": [], "outputs": [{"key": "text", "type": "text"}],
    },
    "screenplay": {
        "label": "剧本", "category": "创作", "icon": "FileText",
        "inputs": [{"key": "source", "type": "text", "required": False}],
        "outputs": [{"key": "screenplay", "type": "screenplay"}],
    },
    "shot": {
        "label": "镜头", "category": "创作", "icon": "Clapperboard",
        "inputs": [
            {"key": "screenplay", "type": "screenplay", "required": False},
            {"key": "references", "type": "image", "multiple": True, "required": False},
        ],
        "outputs": [{"key": "shot", "type": "shot"}],
    },
    "asset": {
        "label": "资产", "category": "资产", "icon": "Image",
        "inputs": [], "outputs": [{"key": "asset", "type": "image"}],
    },
    "video_asset": {
        "label": "视频资产", "category": "资产", "icon": "Video",
        "inputs": [], "outputs": [{"key": "video", "type": "video"}],
    },
    "style": {
        "label": "风格", "category": "风格", "icon": "Palette",
        "inputs": [], "outputs": [{"key": "style", "type": "style"}],
    },
    "image_generation": {
        "label": "图像生成", "category": "生成", "icon": "Wand2",
        "inputs": [
            {"key": "prompt", "type": "text", "required": True},
            {"key": "references", "type": "image", "multiple": True, "required": False},
            {"key": "style", "type": "style", "required": False},
        ],
        "outputs": [{"key": "image", "type": "image"}],
    },
    "storyboard": {
        "label": "故事版", "category": "画面", "icon": "PanelsTopLeft",
        "inputs": [
            {"key": "shot", "type": "shot", "required": False},
            {"key": "references", "type": "image", "multiple": True, "required": False},
            {"key": "style", "type": "style", "required": False},
        ],
        "outputs": [{"key": "image", "type": "image"}],
    },
    "video_generation": {
        "label": "视频生成", "category": "生成", "icon": "Film",
        "inputs": [
            {"key": "prompt", "type": "text", "required": False},
            {"key": "image", "type": "image", "multiple": True, "required": False},
            {"key": "style", "type": "style", "required": False},
        ],
        "outputs": [{"key": "video", "type": "video"}],
    },
    "concat": {
        "label": "视频拼接", "category": "后处理", "icon": "Combine",
        "inputs": [{"key": "videos", "type": "video", "multiple": True, "required": True}],
        "outputs": [{"key": "video", "type": "video"}],
    },
    "output": {
        "label": "输出", "category": "输出", "icon": "Download",
        "inputs": [{"key": "input", "type": "video", "required": False}],
        "outputs": [],
    },
    "note": {
        "label": "便签", "category": "辅助", "icon": "StickyNote",
        "inputs": [], "outputs": [], "executable": False,
    },
}

# 用户画布协议只暴露三种媒体语义节点。旧注册表仅用于读取已经保存的历史图，
# 防止升级后旧画布无法校验；新建和导入的图不会再生成这些技术节点。
NODE_CATALOG: dict[str, dict[str, Any]] = {
    "text": {
        "label": "文本", "category": "内容", "icon": "Type",
        "inputs": [{"key": "source", "type": "any", "multiple": True, "required": False}],
        "outputs": [{"key": "text", "type": "any"}],
    },
    "image": {
        "label": "图片", "category": "媒体", "icon": "Image",
        "inputs": [
            {"key": "prompt", "type": "any", "multiple": True, "required": False},
            {"key": "references", "type": "any", "multiple": True, "required": False},
        ],
        "outputs": [{"key": "image", "type": "any"}],
    },
    "video": {
        "label": "视频", "category": "媒体", "icon": "Video",
        "inputs": [
            {"key": "prompt", "type": "any", "multiple": True, "required": False},
            {"key": "image", "type": "any", "multiple": True, "required": False},
        ],
        "outputs": [{"key": "video", "type": "any"}],
    },
}


def _node_spec(node_type: str) -> dict[str, Any] | None:
    """返回公开节点定义，或历史图仍在使用的内部兼容定义。"""
    return NODE_CATALOG.get(node_type) or _LEGACY_NODE_CATALOG.get(node_type)


def _require_user(request: Request, db: Session) -> User:
    import main as main_mod
    return main_mod._require_user(request, db)


def _require_canvas(canvas_id: int, user: User, db: Session) -> VideoCanvas:
    canvas = db.get(VideoCanvas, canvas_id)
    if not canvas:
        raise HTTPException(404, "画布不存在")
    if canvas.owner_user_id != user.id:
        raise HTTPException(403, "无权访问此画布")
    return canvas


def _require_story(story_id: int, user: User, db: Session) -> Story:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问此作品")
    return story


def _empty_graph() -> dict[str, Any]:
    return {"schema_version": 1, "nodes": [], "edges": [], "groups": [], "metadata": {}}


def _latest_version(canvas_id: int, db: Session) -> VideoCanvasVersion:
    version = (
        db.query(VideoCanvasVersion)
        .filter(VideoCanvasVersion.canvas_id == canvas_id)
        .order_by(VideoCanvasVersion.version_no.desc())
        .first()
    )
    if not version:
        raise HTTPException(500, "画布缺少定义版本")
    return version


def _matches_creation_scope(canvas: VideoCanvas, story_id: int, default_chapter_id: int | None) -> bool:
    """判断同一创建幂等键是否仍指向同一作品和章节作用域。"""
    return canvas.story_id == story_id and canvas.default_chapter_id == default_chapter_id


def _serialize_canvas(canvas: VideoCanvas, db: Session, include_runs: bool = False) -> dict[str, Any]:
    version = _latest_version(canvas.id, db)
    layout = db.query(VideoCanvasLayout).filter(VideoCanvasLayout.canvas_id == canvas.id).first()
    payload: dict[str, Any] = {
        "id": canvas.id,
        "story_id": canvas.story_id,
        "default_chapter_id": canvas.default_chapter_id,
        "name": canvas.name,
        "description": canvas.description,
        "status": canvas.status,
        "definition_revision": canvas.definition_revision,
        "layout_revision": canvas.layout_revision,
        "created_at": canvas.created_at,
        "updated_at": canvas.updated_at,
        "version": {"id": version.id, "version_no": version.version_no, "graph": version.graph_json, "source": version.source},
        "layout": layout.layout_json if layout else {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
    }
    if include_runs:
        runs = (
            db.query(VideoCanvasRun)
            .filter(VideoCanvasRun.canvas_id == canvas.id)
            .order_by(VideoCanvasRun.created_at.desc())
            .limit(20)
            .all()
        )
        payload["runs"] = [_serialize_run(run, db) for run in runs]
    return payload


def _serialize_run(run: VideoCanvasRun, db: Session) -> dict[str, Any]:
    nodes = (
        db.query(VideoCanvasRunNode)
        .filter(VideoCanvasRunNode.run_id == run.id)
        .order_by(VideoCanvasRunNode.id.asc())
        .all()
    )
    return {
        "id": run.id,
        "canvas_id": run.canvas_id,
        "canvas_version_id": run.canvas_version_id,
        "status": run.status,
        "scope": run.scope_json or {},
        "plan": run.plan_json or {},
        "error_message": run.error_message,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "nodes": [
            {
                "id": node.id, "node_id": node.node_id, "node_type": node.node_type,
                "attempt": node.attempt, "status": node.status,
                "input_snapshot": node.input_snapshot_json, "output_snapshot": node.output_snapshot_json,
                "error_message": node.error_message,
            }
            for node in nodes
        ],
    }


def _port_map(spec: dict[str, Any], key: str, direction: str) -> dict[str, Any] | None:
    collection = spec["outputs"] if direction == "source" else spec["inputs"]
    return next((item for item in collection if item["key"] == key), None)


def _validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return {"valid": False, "errors": [{"code": "graph_format", "message": "nodes 和 edges 必须是数组"}], "warnings": []}

    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            errors.append({"code": "node_format", "message": "节点格式无效"})
            continue
        node_id = str(node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if not node_id:
            errors.append({"code": "node_id", "message": "节点缺少 id"})
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
            errors.append({"code": "node_id", "message": "节点 id 只能包含字母、数字、下划线和连字符"})
            continue
        if node_id in node_map:
            errors.append({"code": "node_duplicate", "message": f"节点 {node_id} 重复"})
            continue
        if _node_spec(node_type) is None:
            errors.append({"code": "node_type", "message": f"节点 {node_id} 的类型不受支持"})
            continue
        node_map[node_id] = node

    incoming: dict[tuple[str, str], int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in node_map}
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append({"code": "edge_format", "message": "连线格式无效"})
            continue
        if isinstance(edge.get("data"), dict) and edge["data"].get("disabled"):
            warnings.append({"code": "edge_disabled", "message": "连线来源已失效，已跳过执行"})
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        source_handle = str(edge.get("sourceHandle") or "")
        target_handle = str(edge.get("targetHandle") or "")
        if source_id not in node_map or target_id not in node_map:
            errors.append({"code": "edge_node", "message": "连线引用了不存在的节点"})
            continue
        source_spec = _node_spec(node_map[source_id]["type"])
        target_spec = _node_spec(node_map[target_id]["type"])
        source_port = _port_map(source_spec, source_handle, "source") if source_spec else None
        target_port = _port_map(target_spec, target_handle, "target") if target_spec else None
        if not source_port or not target_port:
            errors.append({"code": "edge_port", "message": "连线端口不存在"})
            continue
        if source_port["type"] != target_port["type"]:
            errors.append({"code": "edge_type", "message": f"{source_port['type']} 不能连接到 {target_port['type']}"})
        key = (target_id, target_handle)
        incoming[key] += 1
        if incoming[key] > 1 and not target_port.get("multiple"):
            errors.append({"code": "edge_cardinality", "message": "单值输入端口只能连接一条线"})
        adjacency[source_id].append(target_id)
        indegree[target_id] += 1

    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    order: list[str] = []
    while queue:
        current = queue.popleft()
        visited += 1
        order.append(current)
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if node_map and visited != len(node_map):
        errors.append({"code": "cycle", "message": "可执行连线不能形成循环"})

    for node_id, node in node_map.items():
        spec = _node_spec(node["type"])
        if spec is None:
            continue
        if spec.get("executable", True) is False:
            continue
        config = (node.get("data") or {}).get("config") or {}
        for port in spec["inputs"]:
            if not port.get("required"):
                continue
            has_edge = incoming[(node_id, port["key"])] > 0
            has_value = bool(config.get(port["key"]))
            if not has_edge and not has_value:
                warnings.append({"code": "missing_input", "node_id": node_id, "message": f"缺少必填输入：{port['key']}"})
    return {"valid": not errors, "errors": errors, "warnings": warnings, "topological_order": order}


def _node_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _source_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _origin(source_type: str, source_id: int, workflow_id: int, config: dict[str, Any]) -> dict[str, Any]:
    """构造可用于显式同步的来源快照，不保存用户本地布局。"""
    return {
        "source_type": source_type,
        "source_id": source_id,
        "source_workflow_id": workflow_id,
        "source_hash": _source_hash(config),
        "baseline_config": config,
        "source_missing": False,
    }


def _origin_key(node: dict[str, Any]) -> tuple[str, str, str] | None:
    """返回来源节点的稳定键；手动节点不会参与同步。"""
    origin = (node.get("data") or {}).get("origin") or {}
    source_type = str(origin.get("source_type") or "")
    source_id = str(origin.get("source_id") or "")
    workflow_id = str(origin.get("source_workflow_id") or "")
    if not source_type or not source_id or not workflow_id:
        return None
    return source_type, workflow_id, source_id


def _import_graph(workflow: ChapterVideoWorkflow, db: Session) -> dict[str, Any]:
    """将列表工作流投影为用户可见的文本、图片和视频节点。

    节点配置保留来源实体的完整快照，便于画布编辑和后续显式同步；节点类型
    不再泄漏列表工作流的内部阶段（剧本、镜头、故事版生成等）。
    """
    graph = _empty_graph()
    screenplay_config = {
        "content": workflow.screenplay_text or "",
        "structure": workflow.screenplay_json or {},
        "source_text": workflow.source_text or "",
        "screenplay_status": workflow.screenplay_status,
        "screenplay_version": workflow.screenplay_version,
    }
    screenplay_id = _node_id("text")
    graph["nodes"].append({
        "id": screenplay_id, "type": "text", "position": {"x": 80, "y": 120},
        "data": {
            "label": "剧本文本", "config": screenplay_config,
            "origin": _origin("chapter_video_workflow", workflow.id, workflow.id, screenplay_config),
        },
    })
    shots = (
        db.query(ChapterVideoShot)
        .filter(ChapterVideoShot.workflow_id == workflow.id)
        .order_by(ChapterVideoShot.shot_index.asc())
        .all()
    )
    asset_roles: dict[int, set[str]] = defaultdict(set)
    asset_shots: dict[int, set[int]] = defaultdict(set)
    for shot in shots:
        for role, refs in (
            ("character", shot.character_reference_ids),
            ("scene", shot.scene_reference_ids),
            ("prop", shot.prop_reference_ids),
        ):
            for asset_id in refs or []:
                if isinstance(asset_id, int):
                    asset_roles[asset_id].add(role)
                    asset_shots[asset_id].add(shot.id)
    asset_ids = set(asset_roles)
    assets = {asset.id: asset for asset in db.query(VideoAsset).filter(VideoAsset.id.in_(asset_ids)).all()} if asset_ids else {}
    asset_nodes: dict[int, str] = {}
    for index, asset in enumerate(assets.values()):
        asset_node_id = _node_id("image")
        asset_nodes[asset.id] = asset_node_id
        asset_config = {
            "asset_id": asset.id,
            "asset_revision": asset.revision,
            "asset_type": asset.asset_type,
            "file_path": asset.file_path,
            "roles": sorted(asset_roles.get(asset.id, set())),
            "source_shot_ids": sorted(asset_shots.get(asset.id, set())),
            "existing_url": asset.file_path,
        }
        graph["nodes"].append({
            "id": asset_node_id, "type": "image", "position": {"x": 80, "y": 360 + index * 150},
            "data": {
                "label": asset.name, "config": asset_config,
                "origin": _origin("video_asset", asset.id, workflow.id, asset_config),
            },
        })
    for index, shot in enumerate(shots):
        x = 480 + index * 340
        shot_config = {
            "shot_id": shot.id,
            "shot_index": shot.shot_index,
            "source_text_span": shot.source_text_span or "",
            "scene_location": shot.scene_location or "",
            "time_of_day": shot.time_of_day or "",
            "characters": shot.characters or [],
            "story_summary": shot.story_summary or "", "dialogue": shot.dialogue_or_narration or "",
            "camera_plan": shot.camera_plan or "", "motion_plan": shot.motion_plan or "",
            "emotion_plan": shot.emotion_plan or "", "continuity_notes": shot.continuity_notes or "",
            "screenplay_scene_id": shot.screenplay_scene_id, "screenplay_beat_id": shot.screenplay_beat_id,
            "narrative_purpose": shot.narrative_purpose, "beat_density": shot.beat_density,
            "transition_to_next": shot.transition_to_next, "continuity": shot.continuity_json or {},
            "video_prompt": shot.video_prompt or "", "storyboard_prompt": shot.storyboard_prompt or "",
            "character_prompts": shot.character_prompts_json or {}, "scene_prompt": shot.scene_prompt or "",
            "prop_prompts": shot.prop_prompts_json or {}, "key_props": shot.key_props_json or [],
            "scene_asset_candidates": shot.scene_asset_candidates_json or [],
            "negative_prompt": getattr(shot, "negative_prompt", None) or "",
            "duration_seconds": shot.duration_seconds or 15, "source_order": shot.shot_index,
        }
        shot_id = _node_id("text")
        graph["nodes"].append({
            "id": shot_id, "type": "text", "position": {"x": x, "y": 120},
            "data": {
                "label": f"分镜 {shot.shot_index}",
                "config": shot_config,
                "origin": _origin("chapter_video_shot", shot.id, workflow.id, shot_config),
            },
        })
        graph["edges"].append({"id": _node_id("edge"), "source": screenplay_id, "sourceHandle": "text", "target": shot_id, "targetHandle": "source"})
        shot_image_nodes: list[str] = []
        for asset_ref in [*(shot.character_reference_ids or []), *(shot.scene_reference_ids or []), *(shot.prop_reference_ids or [])]:
            if isinstance(asset_ref, int) and asset_ref in asset_nodes:
                shot_image_nodes.append(asset_nodes[asset_ref])
        board_id: str | None = None
        # 即使故事版或视频尚未生成，也创建占位媒体节点，保证列表详情同步后能继续在画布中创作。
        board_id = _node_id("image")
        board_config = {"shot_id": shot.id, "prompt": shot.storyboard_prompt or "", "existing_url": shot.storyboard_image_url or "", "storyboard": shot.storyboard_json or {}}
        graph["nodes"].append({"id": board_id, "type": "image", "position": {"x": x, "y": 390}, "data": {"label": f"分镜 {shot.shot_index} 画面", "config": board_config, "origin": _origin("chapter_video_shot_storyboard", shot.id, workflow.id, board_config)}})
        shot_image_nodes.append(board_id)
        video_id = _node_id("video")
        video_config = {"shot_id": shot.id, "prompt": shot.video_prompt or "", "existing_url": shot.video_url or "", "duration_seconds": shot.duration_seconds or 15}
        graph["nodes"].append({"id": video_id, "type": "video", "position": {"x": x, "y": 650}, "data": {"label": f"分镜 {shot.shot_index} 视频", "config": video_config, "origin": _origin("chapter_video_shot_video", shot.id, workflow.id, video_config)}})
        graph["edges"].append({"id": _node_id("edge"), "source": shot_id, "sourceHandle": "text", "target": video_id, "targetHandle": "prompt"})
        for image_id in dict.fromkeys(shot_image_nodes):
            graph["edges"].append({"id": _node_id("edge"), "source": image_id, "sourceHandle": "image", "target": video_id, "targetHandle": "image", "data": {"reference_only": True}})
    return graph


def _merge_import_graph(
    current: dict[str, Any],
    source: dict[str, Any],
    workflow_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """将列表快照单向合并到画布，保留本地修改并报告字段冲突。"""
    current_nodes = list(current.get("nodes") or [])
    current_edges = list(current.get("edges") or [])
    current_by_origin = {
        key: node for node in current_nodes
        if (key := _origin_key(node)) is not None
    }
    source_keys: set[tuple[str, str, str]] = set()
    remapped_node_ids: dict[str, str] = {}
    added_nodes: list[dict[str, Any]] = []
    updated_node_ids: list[str] = []
    conflicts: list[dict[str, Any]] = []
    migrated_node_ids: set[str] = set()

    for source_node in source.get("nodes") or []:
        key = _origin_key(source_node)
        if key is None:
            added_nodes.append(source_node)
            remapped_node_ids[source_node["id"]] = source_node["id"]
            continue
        source_keys.add(key)
        existing = current_by_origin.get(key)
        if existing is None:
            added_nodes.append(source_node)
            remapped_node_ids[source_node["id"]] = source_node["id"]
            continue

        remapped_node_ids[source_node["id"]] = existing["id"]
        # 同步时把历史技术节点升级为当前公开语义节点，避免旧类型继续出现在用户画布。
        if existing.get("type") != source_node.get("type"):
            existing["type"] = source_node.get("type") or existing.get("type")
            migrated_node_ids.add(existing["id"])
        existing_data = existing.setdefault("data", {})
        source_data = source_node.get("data") or {}
        current_config = dict(existing_data.get("config") or {})
        source_config = dict(source_data.get("config") or {})
        old_origin = existing_data.get("origin") or {}
        baseline = dict(old_origin.get("baseline_config") or {})
        changed = False

        for field, source_value in source_config.items():
            old_value = baseline.get(field)
            local_value = current_config.get(field)
            source_changed = source_value != old_value
            local_changed = local_value != old_value
            if source_changed and local_changed and source_value != local_value:
                conflicts.append({
                    "node_id": existing["id"], "field": field,
                    "source_value": source_value, "local_value": local_value,
                })
                continue
            if source_changed and source_value != local_value:
                current_config[field] = source_value
                changed = True

        for field in set(baseline) - set(source_config):
            local_value = current_config.get(field)
            old_value = baseline[field]
            if local_value != old_value:
                conflicts.append({
                    "node_id": existing["id"], "field": field,
                    "source_value": None, "local_value": local_value,
                })
            elif field in current_config:
                current_config.pop(field)
                changed = True

        existing_data["config"] = current_config
        existing_data["origin"] = {
            **source_data.get("origin", {}),
            "source_missing": False,
        }
        if source_data.get("label") and not existing_data.get("label"):
            existing_data["label"] = source_data["label"]
        if changed:
            updated_node_ids.append(existing["id"])

    if migrated_node_ids:
        current_edges = [
            edge for edge in current_edges
            if edge.get("source") not in migrated_node_ids and edge.get("target") not in migrated_node_ids
        ]

    existing_edge_keys = {
        (edge.get("source"), edge.get("sourceHandle"), edge.get("target"), edge.get("targetHandle"))
        for edge in current_edges
    }
    added_edges: list[dict[str, Any]] = []
    for edge in source.get("edges") or []:
        remapped = {
            **edge,
            "source": remapped_node_ids.get(edge.get("source"), edge.get("source")),
            "target": remapped_node_ids.get(edge.get("target"), edge.get("target")),
        }
        edge_key = (remapped.get("source"), remapped.get("sourceHandle"), remapped.get("target"), remapped.get("targetHandle"))
        if edge_key not in existing_edge_keys:
            remapped["id"] = _node_id("edge")
            added_edges.append(remapped)
            existing_edge_keys.add(edge_key)

    source_orphaned: list[str] = []
    for node in current_nodes:
        key = _origin_key(node)
        if key is None or key[1] != str(workflow_id) or key in source_keys:
            continue
        origin = (node.get("data") or {}).get("origin") or {}
        if not origin.get("source_missing"):
            origin["source_missing"] = True
            node.setdefault("data", {})["origin"] = origin
            source_orphaned.append(node["id"])

    orphaned_ids = set(source_orphaned)
    merged_edges = [
        ({**edge, "data": {**(edge.get("data") or {}), "disabled": True, "disabled_reason": "source_missing"}} if edge.get("source") in orphaned_ids or edge.get("target") in orphaned_ids else edge)
        for edge in [*current_edges, *added_edges]
    ]
    merged = {
        **current,
        "nodes": [*current_nodes, *added_nodes],
        "edges": merged_edges,
    }
    result = {
        "added_node_count": len(added_nodes),
        "added_edge_count": len(added_edges),
        "updated_node_ids": updated_node_ids,
        "migrated_node_ids": sorted(migrated_node_ids),
        "source_orphaned_node_ids": source_orphaned,
        "conflicts": conflicts,
        "source_workflow_id": workflow_id,
    }
    return merged, result


def _run_scope_node_ids(graph: dict[str, Any], target_node_ids: set[str]) -> set[str]:
    """返回目标节点及其全部上游依赖，确保运行快照可独立复现。"""
    parents: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            parents[target].add(source)
    included = set(target_node_ids)
    pending = deque(target_node_ids)
    while pending:
        node_id = pending.popleft()
        for parent_id in parents.get(node_id, set()):
            if parent_id not in included:
                included.add(parent_id)
                pending.append(parent_id)
    return included


@router.get("/api/video-canvas/node-catalog")
async def get_video_canvas_node_catalog(request: Request, db: Session = Depends(get_db)):
    _require_user(request, db)
    return {"node_types": [{"type": key, **value} for key, value in NODE_CATALOG.items()]}


@router.post("/api/video-canvas/canvases")
async def create_video_canvas(body: VideoCanvasCreate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_story(body.story_id, user, db)
    if body.idempotency_key:
        existing = db.query(VideoCanvas).filter(
            VideoCanvas.owner_user_id == user.id,
            VideoCanvas.creation_idempotency_key == body.idempotency_key,
        ).first()
        if existing:
            if not _matches_creation_scope(existing, body.story_id, body.default_chapter_id):
                raise HTTPException(409, "创建幂等键已用于其他作品或章节")
            return _serialize_canvas(existing, db)
    if body.default_chapter_id:
        chapter = db.get(Chapter, body.default_chapter_id)
        if not chapter or chapter.story_id != body.story_id:
            raise HTTPException(422, "默认章节不属于当前作品")
    canvas = VideoCanvas(owner_user_id=user.id, story_id=body.story_id, default_chapter_id=body.default_chapter_id, name=body.name.strip(), description=body.description, creation_idempotency_key=body.idempotency_key)
    db.add(canvas)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(VideoCanvas).filter(
            VideoCanvas.owner_user_id == user.id,
            VideoCanvas.creation_idempotency_key == body.idempotency_key,
        ).first()
        if existing:
            if not _matches_creation_scope(existing, body.story_id, body.default_chapter_id):
                raise HTTPException(409, "创建幂等键已用于其他作品或章节")
            return _serialize_canvas(existing, db)
        raise
    db.add(VideoCanvasVersion(canvas_id=canvas.id, version_no=1, graph_json=_empty_graph(), source="manual", created_by_user_id=user.id, change_summary="创建空白画布"))
    db.add(VideoCanvasLayout(canvas_id=canvas.id, layout_json={"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}}, revision=1))
    db.commit()
    db.refresh(canvas)
    return _serialize_canvas(canvas, db)


@router.get("/api/video-canvas/stories/{story_id}/canvases")
async def list_video_canvases(story_id: int, request: Request, chapter_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_story(story_id, user, db)
    query = db.query(VideoCanvas).filter(VideoCanvas.story_id == story_id, VideoCanvas.owner_user_id == user.id, VideoCanvas.status != "archived")
    if chapter_id is not None:
        query = query.filter(VideoCanvas.default_chapter_id == chapter_id)
    canvases = query.order_by(VideoCanvas.updated_at.desc(), VideoCanvas.id.desc()).all()
    return {"canvases": [_serialize_canvas(canvas, db) for canvas in canvases]}


@router.get("/api/video-canvas/stories/{story_id}/list-workflows")
async def list_importable_video_workflows(story_id: int, request: Request, db: Session = Depends(get_db)):
    """返回当前作品可显式导入的列表分镜工作流摘要。"""
    user = _require_user(request, db)
    _require_story(story_id, user, db)
    workflows = (
        db.query(ChapterVideoWorkflow)
        .filter(ChapterVideoWorkflow.story_id == story_id)
        .order_by(ChapterVideoWorkflow.updated_at.desc(), ChapterVideoWorkflow.id.desc())
        .all()
    )
    chapter_ids = {workflow.chapter_id for workflow in workflows if workflow.chapter_id}
    chapters = {
        chapter.id: chapter
        for chapter in db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()
    } if chapter_ids else {}
    return {
        "workflows": [
            {
                "id": workflow.id,
                "chapter_id": workflow.chapter_id,
                "chapter_title": chapters.get(workflow.chapter_id).title if workflow.chapter_id in chapters else None,
                "status": workflow.workflow_status,
                "updated_at": workflow.updated_at,
                "shot_count": db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id == workflow.id).count(),
            }
            for workflow in workflows
        ]
    }


@router.get("/api/video-canvas/canvases/{canvas_id}")
async def get_video_canvas(canvas_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    return _serialize_canvas(_require_canvas(canvas_id, user, db), db, include_runs=True)


@router.patch("/api/video-canvas/canvases/{canvas_id}")
async def update_video_canvas(canvas_id: int, body: VideoCanvasUpdate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(canvas, field, value.strip() if field == "name" and value else value)
    db.commit()
    db.refresh(canvas)
    return _serialize_canvas(canvas, db)


@router.put("/api/video-canvas/canvases/{canvas_id}/graph")
async def save_video_canvas_graph(canvas_id: int, body: VideoCanvasGraphSave, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请刷新后再保存", "definition_revision": canvas.definition_revision})
    validation = _validate_graph(body.graph)
    if validation["errors"]:
        raise HTTPException(422, {"message": "画布校验失败", **validation})
    next_revision = canvas.definition_revision + 1
    db.add(VideoCanvasVersion(canvas_id=canvas.id, version_no=next_revision, graph_json=body.graph, source=body.source, change_summary=body.change_summary, created_by_user_id=user.id))
    canvas.definition_revision = next_revision
    db.commit()
    db.refresh(canvas)
    return {**_serialize_canvas(canvas, db), "validation": validation}


@router.put("/api/video-canvas/canvases/{canvas_id}/layout")
async def save_video_canvas_layout(canvas_id: int, body: VideoCanvasLayoutSave, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if canvas.layout_revision != body.expected_layout_revision:
        raise HTTPException(409, {"message": "画布布局已更新，请刷新后再保存", "layout_revision": canvas.layout_revision})
    layout = db.query(VideoCanvasLayout).filter(VideoCanvasLayout.canvas_id == canvas.id).first()
    if not layout:
        layout = VideoCanvasLayout(canvas_id=canvas.id, layout_json=body.layout, revision=1)
        db.add(layout)
    else:
        layout.layout_json = body.layout
        layout.revision += 1
    canvas.layout_revision += 1
    db.commit()
    return {"layout": body.layout, "layout_revision": canvas.layout_revision}


@router.post("/api/video-canvas/canvases/{canvas_id}/validate")
async def validate_video_canvas(canvas_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    return _validate_graph(_latest_version(canvas.id, db).graph_json)


@router.post("/api/video-canvas/canvases/{canvas_id}/imports/list-workflow")
async def import_list_workflow(canvas_id: int, body: VideoCanvasImportRequest, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    workflow = db.get(ChapterVideoWorkflow, body.source_workflow_id)
    if not workflow or workflow.story_id != canvas.story_id or (canvas.default_chapter_id is not None and workflow.chapter_id != canvas.default_chapter_id):
        raise HTTPException(404, "未找到可导入的列表工作流")
    source_graph = _import_graph(workflow, db)
    if body.mode == "preview":
        return {"mode": "preview", "source_workflow_id": workflow.id, "graph": source_graph, "node_count": len(source_graph["nodes"]), "edge_count": len(source_graph["edges"])}
    if body.expected_definition_revision is not None and canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请刷新后再导入", "definition_revision": canvas.definition_revision})
    if body.idempotency_key:
        existing = db.query(VideoCanvasSyncRecord).filter(
            VideoCanvasSyncRecord.canvas_id == canvas.id,
            VideoCanvasSyncRecord.source_workflow_id == workflow.id,
            VideoCanvasSyncRecord.idempotency_key == body.idempotency_key,
        ).first()
        if existing:
            return {"idempotent": True, "result": existing.result_json or {}, "canvas": _serialize_canvas(canvas, db)}
    current = _latest_version(canvas.id, db).graph_json
    merged, result = _merge_import_graph(current, source_graph, workflow.id)
    validation = _validate_graph(merged)
    if validation["errors"]:
        raise HTTPException(422, {"message": "导入结果校验失败", **validation})
    next_revision = canvas.definition_revision + 1
    db.add(VideoCanvasVersion(canvas_id=canvas.id, version_no=next_revision, graph_json=merged, source="import", change_summary=f"导入列表工作流 {workflow.id}", created_by_user_id=user.id))
    canvas.definition_revision = next_revision
    db.add(VideoCanvasSyncRecord(canvas_id=canvas.id, source_workflow_id=workflow.id, action="import", idempotency_key=body.idempotency_key, before_json=current, after_json=merged, result_json=result, created_by_user_id=user.id))
    db.commit()
    db.refresh(canvas)
    return {"idempotent": False, "result": result, "canvas": _serialize_canvas(canvas, db), "validation": validation}


@router.post("/api/video-canvas/canvases/{canvas_id}/runs")
async def create_video_canvas_run(canvas_id: int, body: VideoCanvasRunRequest, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请重新预检", "definition_revision": canvas.definition_revision})
    version = _latest_version(canvas.id, db)
    validation = _validate_graph(version.graph_json)
    if validation["errors"]:
        raise HTTPException(422, {"message": "画布校验失败", **validation})
    selected = set(body.target_node_ids)
    all_nodes = {node["id"]: node for node in version.graph_json.get("nodes", [])}
    unknown = selected - set(all_nodes)
    if unknown:
        raise HTTPException(422, f"目标节点不存在：{', '.join(sorted(unknown))}")
    if body.idempotency_key:
        existing_run = (
            db.query(VideoCanvasRun)
            .filter(
                VideoCanvasRun.canvas_id == canvas.id,
                VideoCanvasRun.idempotency_key == body.idempotency_key,
            )
            .first()
        )
        if existing_run:
            return {"idempotent": True, "run": _serialize_run(existing_run, db), "validation": validation}
    node_ids = _run_scope_node_ids(version.graph_json, selected) if selected else set(validation["topological_order"])
    ordered_node_ids = [node_id for node_id in validation["topological_order"] if node_id in node_ids]
    run = VideoCanvasRun(
        canvas_id=canvas.id,
        canvas_version_id=version.id,
        idempotency_key=body.idempotency_key,
        status="queued",
        scope_json={"target_node_ids": sorted(selected), "resolved_node_ids": ordered_node_ids},
        plan_json={"topological_order": ordered_node_ids, "warnings": validation["warnings"]},
        requested_by_user_id=user.id,
    )
    db.add(run)
    db.flush()
    pending_approval = False
    for node_id in run.plan_json["topological_order"]:
        node = all_nodes[node_id]
        node_type = node["type"]
        is_generation = node_type in {"image", "video", "image_generation", "storyboard", "video_generation", "concat"}
        status = "awaiting_approval" if is_generation else "succeeded"
        if is_generation:
            pending_approval = True
        config = (node.get("data") or {}).get("config") or {}
        db.add(VideoCanvasRunNode(run_id=run.id, node_id=node_id, node_type=node_type, status=status, input_snapshot_json=config, output_snapshot_json=None if is_generation else {"config": config}, completed_at=None if is_generation else datetime.datetime.now(datetime.timezone.utc)))
    run.status = "awaiting_approval" if pending_approval else "succeeded"
    if run.status == "succeeded":
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(run)
    return {"run": _serialize_run(run, db), "validation": validation}


@router.post("/api/video-canvas/canvases/{canvas_id}/runs/{run_id}/confirm")
async def confirm_video_canvas_run(
    canvas_id: int,
    run_id: int,
    body: VideoCanvasRunConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """确认包含生成节点的运行计划，作为执行器派发的唯一入口。"""
    user = _require_user(request, db)
    _require_canvas(canvas_id, user, db)
    run = db.query(VideoCanvasRun).filter(
        VideoCanvasRun.id == run_id,
        VideoCanvasRun.canvas_id == canvas_id,
    ).with_for_update().first()
    if not run or run.canvas_id != canvas_id:
        raise HTTPException(404, "画布运行不存在")
    if run.status == "awaiting_approval":
        import main as main_mod
        from routers.video import _user_video_api_key

        request.state.db = db
        image_api_key = main_mod._user_image_api_key(request)
        video_api_key, video_base_url, video_model = _user_video_api_key(request)
        generation_nodes = db.query(VideoCanvasRunNode).filter(
            VideoCanvasRunNode.run_id == run.id,
            VideoCanvasRunNode.status == "awaiting_approval",
        ).all()
        if any(node.node_type in {"image", "image_generation", "storyboard"} for node in generation_nodes) and not image_api_key:
            raise HTTPException(400, "请先配置 Image API Key")
        if any(node.node_type in {"video", "video_generation"} for node in generation_nodes) and not video_api_key:
            raise HTTPException(400, "请先配置 Video API Key")
        task_id = f"video_canvas_{canvas_id}_run_{run.id}_{uuid.uuid4().hex[:10]}"
        run.status = "queued"
        for node in db.query(VideoCanvasRunNode).filter(
            VideoCanvasRunNode.run_id == run.id,
            VideoCanvasRunNode.status == "awaiting_approval",
        ):
            node.status = "queued"
            node.task_id = task_id
        run.plan_json = {
            **(run.plan_json or {}),
            "approved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "approval_confirmed": body.confirmed,
        }
        db.commit()
        try:
            await task_manager.submit_task(
                task_id=task_id,
                task_type="video_canvas_run",
                coro_func=execute_canvas_run,
                run_id=run.id,
                image_api_key=image_api_key,
                video_api_key=video_api_key,
                video_base_url=video_base_url,
                video_model=video_model,
                timeout=1800.0,
                max_retries=0,
                story_id=canvas.story_id,
                chapter_id=canvas.default_chapter_id,
                metadata={"canvas_id": canvas.id, "run_id": run.id, "message": "视频画布正在执行..."},
            )
        except Exception:
            # 派发失败不应吞掉用户已经确认的计划，恢复到可重新确认的状态。
            db.rollback()
            retry_run = db.query(VideoCanvasRun).filter(
                VideoCanvasRun.id == run.id,
                VideoCanvasRun.canvas_id == canvas_id,
            ).with_for_update().first()
            if retry_run and retry_run.status == "queued":
                retry_run.status = "awaiting_approval"
                for retry_node in db.query(VideoCanvasRunNode).filter(
                    VideoCanvasRunNode.run_id == retry_run.id,
                    VideoCanvasRunNode.task_id == task_id,
                    VideoCanvasRunNode.status == "queued",
                ):
                    retry_node.status = "awaiting_approval"
                    retry_node.task_id = None
                db.commit()
            raise
        db.refresh(run)
    return {"run": _serialize_run(run, db)}


@router.post("/api/video-canvas/canvases/{canvas_id}/runs/{run_id}/cancel")
async def cancel_video_canvas_run(canvas_id: int, run_id: int, request: Request, db: Session = Depends(get_db)):
    """请求取消当前画布运行，不影响其他独立画布和列表工作流。"""
    user = _require_user(request, db)
    _require_canvas(canvas_id, user, db)
    run = db.query(VideoCanvasRun).filter(
        VideoCanvasRun.id == run_id,
        VideoCanvasRun.canvas_id == canvas_id,
    ).with_for_update().first()
    if not run or run.canvas_id != canvas_id:
        raise HTTPException(404, "画布运行不存在")
    task_ids = [node.task_id for node in db.query(VideoCanvasRunNode).filter(VideoCanvasRunNode.run_id == run.id).all() if node.task_id]
    if run.status not in {"succeeded", "failed", "cancelled"}:
        unstarted = run.status == "awaiting_approval" and not task_ids
        run.status = "cancelled" if unstarted else "cancel_requested"
        for node in db.query(VideoCanvasRunNode).filter(
            VideoCanvasRunNode.run_id == run.id,
            VideoCanvasRunNode.status.in_(["queued", "awaiting_approval"]),
        ):
            node.status = "cancelled"
            node.completed_at = datetime.datetime.now(datetime.timezone.utc)
        if unstarted:
            run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
    for task_id in set(task_ids):
        task_manager.request_cancellation(task_id)
    return {"run": _serialize_run(run, db)}


@router.get("/api/video-canvas/canvases/{canvas_id}/runs/{run_id}")
async def get_video_canvas_run(canvas_id: int, run_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_canvas(canvas_id, user, db)
    run = db.get(VideoCanvasRun, run_id)
    if not run or run.canvas_id != canvas_id:
        raise HTTPException(404, "画布运行不存在")
    return {"run": _serialize_run(run, db)}
