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
from services.errors import UpstreamServiceError
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
    VideoCanvasPlan,
    VideoCanvasRun,
    VideoCanvasRunNode,
    VideoCanvasSyncRecord,
    VideoCanvasVersion,
)
from schemas import (
    CreateVideoAssetRequest,
    MangaDramaProjectCreate,
    VideoCanvasCompileScenesRequest,
    VideoCanvasCreate,
    VideoCanvasDirectorPlanRequest,
    VideoCanvasAssetAnalysisRequest,
    VideoCanvasGraphSave,
    VideoCanvasImportRequest,
    VideoCanvasLayoutSave,
    VideoCanvasPlanConfirmRequest,
    VideoCanvasPlanCreate,
    VideoCanvasPlanApplyRequest,
    VideoCanvasPlanWorkflowSyncRequest,
    VideoCanvasScreenplayImportRequest,
    VideoCanvasScreenplaySplitRequest,
    VideoCanvasPlanUpdate,
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

# 用户画布协议只暴露的媒体语义节点。旧注册表仅用于读取已经保存的历史图，
# 防止升级后旧画布无法校验；新建和导入的图不会再生成这些技术节点。
NODE_CATALOG: dict[str, dict[str, Any]] = {
    "text": {
        "label": "文本", "category": "内容", "icon": "Type",
        "inputs": [{"key": "source", "type": "any", "multiple": True, "required": False}],
        "outputs": [{"key": "text", "type": "any"}],
    },
    "screenplay": {
        "label": "剧本", "category": "内容", "icon": "FileText",
        "inputs": [{"key": "source", "type": "any", "multiple": True, "required": False}],
        "outputs": [{"key": "screenplay", "type": "any"}],
    },
    "scene": {
        "label": "场景", "category": "内容", "icon": "Clapperboard",
        "inputs": [{"key": "screenplay", "type": "any", "multiple": True, "required": False}],
        "outputs": [{"key": "shot", "type": "any"}],
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


def _canvas_deepseek_api_key(request: Request, db: Session) -> str | None:
    """画布文本 AI 调用前的运行时注入（AGENTS.md 陷阱 15：必须先 configure 再调用）。"""
    from routers.video import _user_deepseek_api_key
    return _user_deepseek_api_key(request, db)


def _translate_upstream_error(exc: "UpstreamServiceError") -> HTTPException:
    """把上游 AI 错误转成带友好信息的 HTTP 状态码，避免漏成裸 500。"""
    status = int(exc.status_code or 502)
    if status < 400:
        status = 502
    payload = exc.to_payload()
    return HTTPException(status, {"message": str(exc), **payload})


def _screenplay_node_from_graph(graph: dict[str, Any], node_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """从画布图中定位剧本节点，返回 (node, config)。"""
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("id") or "") != node_id:
            continue
        if str(node.get("type") or "") != "screenplay":
            return None, None
        return node, dict((node.get("data") or {}).get("config") or {})
    return None, None


def _require_canvas(canvas_id: int, user: User, db: Session) -> VideoCanvas:
    canvas = db.get(VideoCanvas, canvas_id)
    if not canvas:
        raise HTTPException(404, "画布不存在")
    if canvas.owner_user_id != user.id:
        raise HTTPException(403, "无权访问此画布")
    return canvas


def _lock_canvas(canvas_id: int, user: User, db: Session) -> VideoCanvas:
    """锁定画布定义行，保证版本比较与写入在同一事务内完成。"""
    canvas = (
        db.query(VideoCanvas)
        .filter(VideoCanvas.id == canvas_id, VideoCanvas.owner_user_id == user.id)
        .with_for_update()
        .first()
    )
    if not canvas:
        raise HTTPException(404, "画布不存在")
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


def _run_target_chapter_id(canvas: VideoCanvas, version: VideoCanvasVersion, db: Session) -> int | None:
    """从已应用计划的冻结图解析运行章节，手工画布回退到默认章节。"""
    metadata = (version.graph_json or {}).get("metadata") or {}
    plan_id = metadata.get("compiled_from_plan_id") if isinstance(metadata, dict) else None
    if not isinstance(plan_id, int):
        return canvas.default_chapter_id
    plan = db.get(VideoCanvasPlan, plan_id)
    if not plan or plan.canvas_id != canvas.id or plan.story_id != canvas.story_id:
        return canvas.default_chapter_id
    return plan.chapter_id if plan.chapter_id is not None else canvas.default_chapter_id


def _serialize_plan(plan: VideoCanvasPlan) -> dict[str, Any]:
    """序列化可审阅的画布创作计划，不泄露其他用户或画布数据。"""
    return {
        "id": plan.id,
        "canvas_id": plan.canvas_id,
        "story_id": plan.story_id,
        "chapter_id": plan.chapter_id,
        "status": plan.status,
        "revision": plan.revision,
        "source_snapshot": plan.source_snapshot_json or {},
        "screenplay": plan.screenplay_json or {},
        "shots": plan.shot_json or {},
        "assets": plan.asset_json or {},
        "canvas": plan.canvas_json or {},
        "execution": plan.execution_json or {},
        "workflow_id": plan.workflow_id,
        "applied_canvas_revision": plan.applied_canvas_revision,
        "workflow_sync_revision": plan.workflow_sync_revision,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _plan_ready_errors(plan: VideoCanvasPlan) -> list[str]:
    """确认前检查计划是否具备完整的可审阅内容。"""
    required = {
        "来源快照": plan.source_snapshot_json,
        "剧本计划": plan.screenplay_json,
        "镜头计划": plan.shot_json,
        "资产计划": plan.asset_json,
        "画布计划": plan.canvas_json,
        "执行计划": plan.execution_json,
    }
    errors = [f"缺少{name}" for name, value in required.items() if not value]
    source = plan.source_snapshot_json or {}
    if source and str(source.get("source_type") or "") not in {"chapter", "chat", "text_node"}:
        errors.append("来源快照的 source_type 必须为 chapter、chat 或 text_node")
    if source and not str(source.get("source_hash") or "").strip():
        errors.append("来源快照缺少 source_hash")
    screenplay = plan.screenplay_json or {}
    if screenplay and not isinstance(screenplay.get("scenes"), list):
        errors.append("剧本计划缺少 scenes 数组")
    shots = plan.shot_json or {}
    if shots and (not isinstance(shots.get("shots"), list) or not shots["shots"]):
        errors.append("镜头计划缺少非空 shots 数组")
    canvas = plan.canvas_json or {}
    graph = canvas.get("graph") if isinstance(canvas, dict) else None
    if graph is not None and not isinstance(graph, dict):
        errors.append("画布计划的 graph 必须是对象")
    elif isinstance(graph, dict):
        validation = _validate_graph(graph)
        errors.extend(f"画布图：{item['message']}" for item in validation["errors"])
    execution = plan.execution_json or {}
    if execution and not isinstance(execution.get("batches"), list):
        errors.append("执行计划缺少 batches 数组")
    return errors


def _plan_graph(plan: VideoCanvasPlan, db: Session) -> dict[str, Any]:
    """从已审阅镜头与资产计划确定性编译可执行画布图。"""
    return _compile_plan_graph(plan, _plan_shots(plan, db))


_PLAN_SHOT_FIELDS = {
    "shot_index", "source_text_span", "scene_location", "time_of_day", "characters",
    "story_summary", "dialogue_or_narration", "camera_plan", "motion_plan", "emotion_plan",
    "continuity_notes", "screenplay_scene_id", "screenplay_beat_id", "narrative_purpose",
    "beat_density", "transition_to_next", "continuity_json", "storyboard_prompt", "video_prompt",
    "character_prompts_json", "scene_prompt", "prop_prompts_json", "key_props_json",
    "scene_asset_candidates_json", "character_reference_ids", "scene_reference_ids",
    "prop_reference_ids", "storyboard_json", "duration_seconds",
}


def _is_image_reference_asset(asset: VideoAsset) -> bool:
    """判断计划引用是否可作为故事板和视频节点的图片参考。"""
    asset_type = str(asset.asset_type or "").lower()
    suffix = str(asset.file_path or "").rsplit(".", 1)[-1].lower() if "." in str(asset.file_path or "") else ""
    return asset_type in {"storyboard_frame", "character_reference", "scene_reference", "prop_reference", "style_reference", "image"} or suffix in {"png", "jpg", "jpeg", "webp", "gif"}


def _plan_shots(plan: VideoCanvasPlan, db: Session) -> list[dict[str, Any]]:
    """解析并校验计划镜头，拒绝未知字段和不属于当前章节的资产引用。"""
    section = plan.shot_json or {}
    raw_shots = section.get("shots") if isinstance(section, dict) else None
    if not isinstance(raw_shots, list) or not raw_shots:
        raise HTTPException(422, "计划缺少 shots.shots，无法同步到视频工作流")
    if len(raw_shots) > 200:
        raise HTTPException(422, "单个计划最多同步 200 个镜头")
    asset_ids: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_shots, start=1):
        if not isinstance(item, dict):
            raise HTTPException(422, f"第 {index} 个镜头格式无效")
        unknown = set(item) - _PLAN_SHOT_FIELDS
        if unknown:
            raise HTTPException(422, f"第 {index} 个镜头含不支持字段：{', '.join(sorted(unknown))}")
        shot = {key: value for key, value in item.items() if key in _PLAN_SHOT_FIELDS}
        shot_index = shot.get("shot_index")
        if not isinstance(shot_index, int) or isinstance(shot_index, bool) or shot_index <= 0:
            raise HTTPException(422, f"第 {index} 个镜头的 shot_index 必须为正整数")
        shot.setdefault("source_text_span", f"（第 {shot_index} 镜）")
        shot.setdefault("story_summary", f"镜头 {shot_index}")
        duration_seconds = shot.get("duration_seconds", 15)
        if not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool) or not 1 <= duration_seconds <= 60:
            raise HTTPException(422, f"第 {index} 个镜头的 duration_seconds 必须是 1 到 60 的整数")
        shot["duration_seconds"] = duration_seconds
        for field in ("character_reference_ids", "scene_reference_ids", "prop_reference_ids"):
            values = shot.get(field)
            if values is None:
                continue
            if not isinstance(values, list) or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
                raise HTTPException(422, f"第 {index} 个镜头的 {field} 必须是正整数数组")
            asset_ids.update(values)
        normalized.append(shot)
    if len({item["shot_index"] for item in normalized}) != len(normalized):
        raise HTTPException(422, "镜头 shot_index 不能重复")
    if asset_ids:
        assets = db.query(VideoAsset).filter(
                VideoAsset.id.in_(asset_ids),
                VideoAsset.story_id == plan.story_id,
                VideoAsset.chapter_id == plan.chapter_id,
            ).all()
        valid_ids = {asset.id for asset in assets if _is_image_reference_asset(asset)}
        missing = asset_ids - valid_ids
        if missing:
            raise HTTPException(422, f"计划引用了无效、非图片或不属于当前章节的资产：{', '.join(map(str, sorted(missing)))}")
    return sorted(normalized, key=lambda item: item["shot_index"])


def _plan_node_id(prefix: str, value: Any) -> str:
    """将计划中的任意稳定标识转换为画布允许的 ASCII 节点 ID。"""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _plan_text(value: Any, fallback: str = "") -> str:
    """收敛计划文本，避免缺失字段导致无法生成可审阅节点。"""
    text = str(value or "").strip()
    return text or fallback


def _plan_asset_items(plan: VideoCanvasPlan) -> list[dict[str, Any]]:
    """兼容资产计划的列表写法，只接纳对象项用于确定性画布编译。"""
    section = plan.asset_json or {}
    items = section.get("assets") if isinstance(section, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _compile_plan_graph(plan: VideoCanvasPlan, normalized_shots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把已审阅的来源、剧本、镜头与资产计划编译为固定拓扑的画布图。"""
    shots = normalized_shots if normalized_shots is not None else (plan.shot_json or {}).get("shots") or []
    graph = _empty_graph()
    graph["metadata"] = {"compiled_from_plan_id": plan.id, "compiler": "video_canvas_plan_v1"}
    source = plan.source_snapshot_json or {}
    screenplay = plan.screenplay_json or {}
    source_id = "source"
    screenplay_id = "screenplay"
    source_content = _plan_text(source.get("content") or source.get("text"), "待补充创作来源")
    graph["nodes"].append({
        "id": source_id, "type": "text", "position": {"x": 80, "y": 120},
        "data": {"label": "创作来源", "config": {"content": source_content, "source_type": source.get("source_type"), "source_hash": source.get("source_hash")}},
    })
    screenplay_content = _plan_text(screenplay.get("text") or screenplay.get("screenplay_text"), "结构化剧本")
    graph["nodes"].append({
        "id": screenplay_id, "type": "text", "position": {"x": 380, "y": 120},
        "data": {"label": "视频剧本", "config": {"content": screenplay_content, "scenes": screenplay.get("scenes") or []}},
    })
    graph["edges"].append({"id": "edge-source-screenplay", "source": source_id, "sourceHandle": "text", "target": screenplay_id, "targetHandle": "source"})

    asset_nodes: dict[int, str] = {}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        for field in ("character_reference_ids", "scene_reference_ids", "prop_reference_ids"):
            for asset_id in shot.get(field) or []:
                if not isinstance(asset_id, int) or asset_id in asset_nodes:
                    continue
                node_id = _plan_node_id("asset", asset_id)
                asset_nodes[asset_id] = node_id
                graph["nodes"].append({
                    "id": node_id, "type": "image", "position": {"x": 80, "y": 350 + len(asset_nodes) * 180},
                    "data": {"label": f"已有关联资产 {asset_id}", "config": {"asset_id": asset_id, "reference_asset_ids": [asset_id]}},
                })

    planned_assets: list[tuple[str, dict[str, Any]]] = []
    for index, asset in enumerate(_plan_asset_items(plan), start=1):
        asset_id = asset.get("asset_id")
        if isinstance(asset_id, int) and asset_id in asset_nodes:
            continue
        identity = asset_id if isinstance(asset_id, int) else asset.get("asset_key") or asset.get("key") or asset.get("name") or index
        node_id = _plan_node_id("planned-asset", identity)
        config = {"prompt": _plan_text(asset.get("prompt") or asset.get("description") or asset.get("name"), f"计划资产 {index}"), "asset_role": asset.get("role") or asset.get("asset_type")}
        if isinstance(asset_id, int):
            config = {"asset_id": asset_id, "reference_asset_ids": [asset_id], "asset_role": config["asset_role"]}
        graph["nodes"].append({
            "id": node_id, "type": "image", "position": {"x": 80, "y": 350 + (len(asset_nodes) + index) * 180},
            "data": {"label": _plan_text(asset.get("name"), f"计划资产 {index}"), "config": config},
        })
        planned_assets.append((node_id, asset))

    for order, shot in enumerate(sorted((item for item in shots if isinstance(item, dict)), key=lambda item: item.get("shot_index", 0)), start=1):
        shot_index = shot.get("shot_index") if isinstance(shot.get("shot_index"), int) else order
        shot_id = f"shot-{shot_index}"
        board_id = f"board-{shot_index}"
        video_id = f"video-{shot_index}"
        x = 720 + (order - 1) * 400
        shot_config = {key: value for key, value in shot.items() if key in _PLAN_SHOT_FIELDS}
        graph["nodes"].append({"id": shot_id, "type": "text", "position": {"x": x, "y": 120}, "data": {"label": f"分镜 {shot_index}", "config": {"content": _plan_text(shot.get("story_summary")), **shot_config}}})
        graph["nodes"].append({"id": board_id, "type": "image", "position": {"x": x, "y": 390}, "data": {"label": f"分镜 {shot_index} 故事板", "config": {"prompt": _plan_text(shot.get("storyboard_prompt") or shot.get("scene_prompt"), _plan_text(shot.get("story_summary"))), "reference_asset_ids": [asset_id for field in ("character_reference_ids", "scene_reference_ids", "prop_reference_ids") for asset_id in shot.get(field) or [] if isinstance(asset_id, int)]}}})
        graph["nodes"].append({"id": video_id, "type": "video", "position": {"x": x, "y": 680}, "data": {"label": f"分镜 {shot_index} 视频", "config": {"prompt": _plan_text(shot.get("video_prompt"), _plan_text(shot.get("story_summary"))), "duration_seconds": shot.get("duration_seconds", 15)}}})
        graph["edges"].extend([
            {"id": f"edge-screenplay-shot-{shot_index}", "source": screenplay_id, "sourceHandle": "text", "target": shot_id, "targetHandle": "source"},
            {"id": f"edge-shot-board-{shot_index}", "source": shot_id, "sourceHandle": "text", "target": board_id, "targetHandle": "prompt"},
            {"id": f"edge-shot-video-{shot_index}", "source": shot_id, "sourceHandle": "text", "target": video_id, "targetHandle": "prompt"},
            {"id": f"edge-board-video-{shot_index}", "source": board_id, "sourceHandle": "image", "target": video_id, "targetHandle": "image"},
        ])
        referenced_ids = {asset_id for field in ("character_reference_ids", "scene_reference_ids", "prop_reference_ids") for asset_id in shot.get(field) or [] if isinstance(asset_id, int)}
        for asset_id in referenced_ids:
            node_id = asset_nodes.get(asset_id)
            if node_id:
                graph["edges"].extend([
                    {"id": f"edge-asset-board-{asset_id}-{shot_index}", "source": node_id, "sourceHandle": "image", "target": board_id, "targetHandle": "references"},
                    {"id": f"edge-asset-video-{asset_id}-{shot_index}", "source": node_id, "sourceHandle": "image", "target": video_id, "targetHandle": "image"},
                ])
        for node_id, asset in planned_assets:
            indexes = asset.get("used_by_shot_indexes") or asset.get("shot_indexes") or []
            if isinstance(indexes, list) and shot_index in indexes:
                graph["edges"].extend([
                    {"id": f"edge-planned-board-{node_id}-{shot_index}", "source": node_id, "sourceHandle": "image", "target": board_id, "targetHandle": "references"},
                    {"id": f"edge-planned-video-{node_id}-{shot_index}", "source": node_id, "sourceHandle": "image", "target": video_id, "targetHandle": "image"},
                ])
    return graph


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


def _canvas_source_hash(source_type: str, source_id: Any, content: str) -> str:
    """与 Agent 来源冻结协议一致地计算可追溯内容哈希。"""
    return _source_hash({"source_type": source_type, "source_id": source_id, "content": content})


def _resolve_plan_source_snapshot(
    canvas: VideoCanvas,
    source_snapshot: dict[str, Any] | None,
    db: Session,
) -> dict[str, Any] | None:
    """为 REST 计划入口重读可验证来源，拒绝客户端伪造正文。"""
    if source_snapshot is None:
        return None
    source_type = str(source_snapshot.get("source_type") or "").strip()
    source_id = source_snapshot.get("source_id")
    if source_type == "chapter":
        chapter = db.get(Chapter, source_id) if isinstance(source_id, int) else None
        if not chapter or chapter.story_id != canvas.story_id:
            raise HTTPException(422, "计划来源章节不存在或不属于当前作品")
        content = str(chapter.novel_content or "").strip()
        if not content:
            raise HTTPException(422, "计划来源章节正文为空")
        return {
            "source_type": "chapter",
            "source_id": chapter.id,
            "chapter_id": chapter.id,
            "title": chapter.title or "未命名章节",
            "content": content,
            "source_hash": _canvas_source_hash("chapter", chapter.id, content),
        }
    if source_type == "text_node":
        node_id = str(source_id or "").strip()
        graph = _latest_version(canvas.id, db).graph_json or {}
        node = next((item for item in graph.get("nodes") or [] if isinstance(item, dict) and str(item.get("id") or "") == node_id), None)
        if not node or node.get("type") != "text":
            raise HTTPException(422, "计划来源文本节点不存在或类型不正确")
        config = (node.get("data") or {}).get("config") or {}
        content = str(config.get("content") or config.get("text") or "").strip()
        if not content:
            raise HTTPException(422, "计划来源文本节点为空")
        return {
            "source_type": "text_node",
            "source_id": node_id,
            "node_label": str((node.get("data") or {}).get("label") or node_id),
            "content": content,
            "source_hash": _canvas_source_hash("text_node", node_id, content),
        }
    if source_type == "chat":
        raise HTTPException(422, "聊天剧本必须通过画布 Agent 创建计划")
    raise HTTPException(422, "source_type 仅支持 chapter 或 text_node")


def _plan_source_stale_error(plan: VideoCanvasPlan, db: Session) -> str | None:
    """确认前检测章节或文本节点来源是否已变更，避免旧草案覆盖新创作。"""
    source = plan.source_snapshot_json or {}
    source_type = str(source.get("source_type") or "")
    source_id = source.get("source_id")
    expected_hash = str(source.get("source_hash") or "")
    if source_type == "chapter" and isinstance(source_id, int):
        chapter = db.get(Chapter, source_id)
        if not chapter or chapter.story_id != plan.story_id:
            return "计划来源章节已不存在或不再属于当前作品"
        actual_hash = _canvas_source_hash("chapter", chapter.id, str(chapter.novel_content or "").strip())
        return "章节正文已更新，请重新生成创作计划" if actual_hash != expected_hash else None
    if source_type == "text_node" and source_id:
        graph = _latest_version(plan.canvas_id, db).graph_json or {}
        node = next((item for item in graph.get("nodes") or [] if isinstance(item, dict) and str(item.get("id") or "") == str(source_id)), None)
        if not node or node.get("type") != "text":
            return "计划来源文本节点已不存在或已变更类型"
        config = (node.get("data") or {}).get("config") or {}
        actual_hash = _canvas_source_hash("text_node", str(source_id), str(config.get("content") or config.get("text") or "").strip())
        return "文本节点内容已更新，请重新生成创作计划" if actual_hash != expected_hash else None
    return None


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
        board_config = {"shot_id": shot.id, "prompt": shot.storyboard_prompt or "", "storyboard": shot.storyboard_json or {}, "trusted_import_media_url": shot.storyboard_image_url or ""}
        graph["nodes"].append({"id": board_id, "type": "image", "position": {"x": x, "y": 390}, "data": {"label": f"分镜 {shot.shot_index} 画面", "config": board_config, "origin": _origin("chapter_video_shot_storyboard", shot.id, workflow.id, board_config)}})
        shot_image_nodes.append(board_id)
        video_id = _node_id("video")
        video_config = {"shot_id": shot.id, "prompt": shot.video_prompt or "", "duration_seconds": shot.duration_seconds or 15, "trusted_import_media_url": shot.video_url or ""}
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
        if isinstance(edge.get("data"), dict) and edge["data"].get("disabled"):
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


@router.get("/api/manga-drama/projects")
async def list_manga_drama_projects(request: Request, db: Session = Depends(get_db)):
    """漫剧创作项目列表：当前用户 story_type='video' 的作品及其画布。"""
    user = _require_user(request, db)
    stories = (
        db.query(Story)
        .filter(Story.owner_user_id == user.id, Story.story_type == "video")
        .order_by(Story.created_at.desc())
        .all()
    )
    items: list[dict[str, Any]] = []
    for story in stories:
        canvases = (
            db.query(VideoCanvas)
            .filter(VideoCanvas.owner_user_id == user.id, VideoCanvas.story_id == story.id)
            .order_by(VideoCanvas.id.desc())
            .all()
        )
        items.append(
            {
                "story_id": story.id,
                "title": story.title,
                "description": story.description,
                "cover_image": story.cover_image,
                "created_at": story.created_at.isoformat() if story.created_at else None,
                "canvases": [_serialize_canvas(c, db) for c in canvases],
            }
        )
    return {"projects": items}


@router.post("/api/manga-drama/projects", status_code=201)
async def create_manga_drama_project(body: MangaDramaProjectCreate, request: Request, db: Session = Depends(get_db)):
    """新建漫剧项目：创建 story_type='video' 的作品 + 初始空白画布，一次完成。"""
    user = _require_user(request, db)
    if body.idempotency_key:
        existing_canvas = db.query(VideoCanvas).filter(
            VideoCanvas.owner_user_id == user.id,
            VideoCanvas.creation_idempotency_key == body.idempotency_key,
        ).first()
        if existing_canvas:
            story = db.get(Story, existing_canvas.story_id)
            return {"story_id": existing_canvas.story_id, "canvas": _serialize_canvas(existing_canvas, db), "story_title": story.title if story else body.title}

    story = Story(
        owner_user_id=user.id,
        title=body.title.strip(),
        description=body.description,
        story_type="video",
    )
    db.add(story)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(422, "漫剧项目创建失败，请重试")

    canvas = VideoCanvas(
        owner_user_id=user.id,
        story_id=story.id,
        name=body.canvas_name.strip(),
        description=body.description,
        creation_idempotency_key=body.idempotency_key,
    )
    db.add(canvas)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(422, "漫剧画布创建失败，请重试")
    db.add(VideoCanvasVersion(canvas_id=canvas.id, version_no=1, graph_json=_empty_graph(), source="manual", created_by_user_id=user.id, change_summary="创建漫剧项目空白画布"))
    db.add(VideoCanvasLayout(canvas_id=canvas.id, layout_json={"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}}, revision=1))
    db.commit()
    db.refresh(canvas)
    db.refresh(story)
    return {"story_id": story.id, "story_title": story.title, "canvas": _serialize_canvas(canvas, db)}


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


@router.delete("/api/video-canvas/canvases/{canvas_id}")
async def delete_video_canvas(canvas_id: int, request: Request, db: Session = Depends(get_db)):
    """归档画布，保留历史版本、运行记录和用户生成媒体。"""
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    canvas.status = "archived"
    db.commit()
    return {"ok": True, "canvas_id": canvas_id}


@router.get("/api/video-canvas/canvases/{canvas_id}/plans")
async def list_video_canvas_plans(canvas_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    plans = (
        db.query(VideoCanvasPlan)
        .filter(VideoCanvasPlan.canvas_id == canvas.id, VideoCanvasPlan.owner_user_id == user.id)
        .order_by(VideoCanvasPlan.updated_at.desc(), VideoCanvasPlan.id.desc())
        .limit(30)
        .all()
    )
    return {"plans": [_serialize_plan(plan) for plan in plans]}


@router.post("/api/video-canvas/canvases/{canvas_id}/plans")
async def create_video_canvas_plan(
    canvas_id: int,
    body: VideoCanvasPlanCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """保存 Agent 或用户提出的创作草案，草案本身不会修改画布或触发生成。"""
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    source_snapshot = _resolve_plan_source_snapshot(canvas, body.source_snapshot_json, db)
    source_chapter_id = source_snapshot.get("chapter_id") if isinstance(source_snapshot, dict) else None
    chapter_id = body.chapter_id if body.chapter_id is not None else source_chapter_id if isinstance(source_chapter_id, int) else canvas.default_chapter_id
    if chapter_id is not None:
        chapter = db.get(Chapter, chapter_id)
        if not chapter or chapter.story_id != canvas.story_id:
            raise HTTPException(422, "计划章节不属于当前画布作品")
    plan = VideoCanvasPlan(
        owner_user_id=user.id,
        canvas_id=canvas.id,
        story_id=canvas.story_id,
        chapter_id=chapter_id,
        source_snapshot_json=source_snapshot,
        screenplay_json=body.screenplay_json,
        shot_json=body.shot_json,
        asset_json=body.asset_json,
        canvas_json=body.canvas_json,
        execution_json=body.execution_json,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.get("/api/video-canvas/canvases/{canvas_id}/plans/{plan_id}")
async def get_video_canvas_plan(canvas_id: int, plan_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    plan = db.get(VideoCanvasPlan, plan_id)
    if not plan or plan.canvas_id != canvas_id or plan.owner_user_id != user.id:
        raise HTTPException(404, "画布计划不存在")
    return _serialize_plan(plan)


@router.put("/api/video-canvas/canvases/{canvas_id}/plans/{plan_id}")
async def update_video_canvas_plan(
    canvas_id: int,
    plan_id: int,
    body: VideoCanvasPlanUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    plan = db.query(VideoCanvasPlan).filter(
        VideoCanvasPlan.id == plan_id,
        VideoCanvasPlan.canvas_id == canvas.id,
        VideoCanvasPlan.owner_user_id == user.id,
    ).with_for_update().first()
    if not plan or plan.canvas_id != canvas_id or plan.owner_user_id != user.id:
        raise HTTPException(404, "画布计划不存在")
    if plan.status not in {"draft", "ready"}:
        raise HTTPException(409, "已确认的计划不能再编辑，请创建新草案")
    if plan.revision != body.expected_revision:
        raise HTTPException(409, {"message": "计划已更新，请刷新后再保存", "revision": plan.revision})
    updates = body.model_dump(exclude_unset=True, exclude={"expected_revision", "source_snapshot_json"})
    for field, value in updates.items():
        setattr(plan, field, value)
    if body.source_snapshot_json is not None:
        plan.source_snapshot_json = _resolve_plan_source_snapshot(canvas, body.source_snapshot_json, db)
        source_chapter_id = plan.source_snapshot_json.get("chapter_id") if isinstance(plan.source_snapshot_json, dict) else None
        if isinstance(source_chapter_id, int):
            plan.chapter_id = source_chapter_id
    if body.status == "ready":
        errors = _plan_ready_errors(plan)
        if errors:
            raise HTTPException(422, "；".join(errors))
    plan.revision += 1
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.post("/api/video-canvas/canvases/{canvas_id}/plans/{plan_id}/confirm")
async def confirm_video_canvas_plan(
    canvas_id: int,
    plan_id: int,
    body: VideoCanvasPlanConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """确认计划内容；生成和画布应用仍需走各自的独立确认步骤。"""
    user = _require_user(request, db)
    _require_canvas(canvas_id, user, db)
    plan = db.get(VideoCanvasPlan, plan_id)
    if not plan or plan.canvas_id != canvas_id or plan.owner_user_id != user.id:
        raise HTTPException(404, "画布计划不存在")
    if plan.revision != body.expected_revision:
        raise HTTPException(409, {"message": "计划已更新，请刷新后再确认", "revision": plan.revision})
    if plan.status != "ready":
        raise HTTPException(422, "只有已就绪的计划可以确认")
    if stale_error := _plan_source_stale_error(plan, db):
        raise HTTPException(409, stale_error)
    plan.status = "approved"
    plan.revision += 1
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.post("/api/video-canvas/canvases/{canvas_id}/plans/{plan_id}/apply")
async def apply_video_canvas_plan(
    canvas_id: int,
    plan_id: int,
    body: VideoCanvasPlanApplyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """将已确认计划的图定义原子写入画布，生成执行仍需另行确认。"""
    user = _require_user(request, db)
    canvas = _lock_canvas(canvas_id, user, db)
    plan = db.query(VideoCanvasPlan).filter(
        VideoCanvasPlan.id == plan_id,
        VideoCanvasPlan.canvas_id == canvas.id,
        VideoCanvasPlan.owner_user_id == user.id,
    ).with_for_update().first()
    if not plan or plan.canvas_id != canvas.id or plan.owner_user_id != user.id:
        raise HTTPException(404, "画布计划不存在")
    if plan.status != "approved":
        raise HTTPException(422, "请先确认创作计划")
    if stale_error := _plan_source_stale_error(plan, db):
        raise HTTPException(409, stale_error)
    if plan.revision != body.expected_plan_revision:
        raise HTTPException(409, {"message": "计划已更新，请刷新后再应用", "revision": plan.revision})
    if canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请刷新后再应用", "definition_revision": canvas.definition_revision})
    graph = _plan_graph(plan, db)
    validation = _validate_graph(graph)
    if validation["errors"]:
        raise HTTPException(422, {"message": "计划画布校验失败", **validation})
    next_revision = canvas.definition_revision + 1
    db.add(VideoCanvasVersion(
        canvas_id=canvas.id,
        version_no=next_revision,
        graph_json=graph,
        source="agent",
        change_summary=f"应用创作计划 {plan.id}",
        created_by_user_id=user.id,
    ))
    canvas.definition_revision = next_revision
    plan.status = "applied"
    plan.applied_canvas_revision = next_revision
    plan.revision += 1
    db.commit()
    db.refresh(canvas)
    db.refresh(plan)
    return {"canvas": _serialize_canvas(canvas, db), "plan": _serialize_plan(plan), "validation": validation}


@router.post("/api/video-canvas/canvases/{canvas_id}/plans/{plan_id}/sync-workflow")
async def sync_video_canvas_plan_to_workflow(
    canvas_id: int,
    plan_id: int,
    body: VideoCanvasPlanWorkflowSyncRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """把已确认计划写入新章节视频工作流，作为后续分镜、故事板和视频的事实源。"""
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    plan = db.query(VideoCanvasPlan).filter(
        VideoCanvasPlan.id == plan_id,
        VideoCanvasPlan.canvas_id == canvas.id,
        VideoCanvasPlan.owner_user_id == user.id,
    ).with_for_update().first()
    if not plan or plan.canvas_id != canvas.id or plan.owner_user_id != user.id:
        raise HTTPException(404, "画布计划不存在")
    if plan.status not in {"approved", "applied"}:
        raise HTTPException(422, "请先确认创作计划")
    if stale_error := _plan_source_stale_error(plan, db):
        raise HTTPException(409, stale_error)
    if plan.revision != body.expected_plan_revision:
        raise HTTPException(409, {"message": "计划已更新，请刷新后再同步", "revision": plan.revision})
    if plan.chapter_id is None:
        raise HTTPException(422, "画布计划未绑定章节，不能同步章节视频工作流")
    chapter = db.get(Chapter, plan.chapter_id)
    if not chapter or chapter.story_id != canvas.story_id:
        raise HTTPException(422, "计划章节不属于当前作品")
    if plan.workflow_id is not None:
        raise HTTPException(409, "此计划已同步到章节视频工作流，请创建新计划以避免覆盖既有镜头")
    shots = _plan_shots(plan, db)
    screenplay = plan.screenplay_json or {}
    screenplay_text = str(screenplay.get("text") or screenplay.get("screenplay_text") or "").strip()
    screenplay_json = screenplay.get("json") if isinstance(screenplay.get("json"), dict) else screenplay
    if not screenplay_text and not screenplay_json:
        raise HTTPException(422, "计划缺少可同步剧本")
    source = plan.source_snapshot_json or {}
    source_text = str(source.get("content") or source.get("text") or chapter.novel_content or "")
    workflow = ChapterVideoWorkflow(
        chapter_id=chapter.id,
        story_id=canvas.story_id,
        source_text=source_text,
        workflow_status="shots_ready",
        video_style=str((plan.execution_json or {}).get("video_style") or "") or None,
        duration_per_shot=15,
        screenplay_text=screenplay_text or json.dumps(screenplay_json, ensure_ascii=False),
        screenplay_json=screenplay_json,
        screenplay_status="approved",
        screenplay_updated_at=datetime.datetime.now(datetime.timezone.utc),
        screenplay_approved_at=datetime.datetime.now(datetime.timezone.utc),
        screenplay_version=1,
        total_shots=len(shots),
    )
    db.add(workflow)
    db.flush()
    for shot_data in shots:
        db.add(ChapterVideoShot(
            workflow_id=workflow.id,
            shot_index=shot_data["shot_index"],
            source_text_span=shot_data.get("source_text_span"),
            scene_location=shot_data.get("scene_location"),
            time_of_day=shot_data.get("time_of_day"),
            characters=shot_data.get("characters"),
            story_summary=shot_data.get("story_summary"),
            dialogue_or_narration=shot_data.get("dialogue_or_narration"),
            camera_plan=shot_data.get("camera_plan"),
            motion_plan=shot_data.get("motion_plan"),
            emotion_plan=shot_data.get("emotion_plan"),
            continuity_notes=shot_data.get("continuity_notes"),
            screenplay_scene_id=shot_data.get("screenplay_scene_id"),
            screenplay_beat_id=shot_data.get("screenplay_beat_id"),
            narrative_purpose=shot_data.get("narrative_purpose"),
            beat_density=shot_data.get("beat_density"),
            transition_to_next=shot_data.get("transition_to_next"),
            continuity_json=shot_data.get("continuity_json"),
            storyboard_prompt=shot_data.get("storyboard_prompt") or "",
            video_prompt=shot_data.get("video_prompt") or "",
            character_prompts_json=shot_data.get("character_prompts_json"),
            scene_prompt=shot_data.get("scene_prompt"),
            prop_prompts_json=shot_data.get("prop_prompts_json"),
            key_props_json=shot_data.get("key_props_json"),
            scene_asset_candidates_json=shot_data.get("scene_asset_candidates_json"),
            character_reference_ids=shot_data.get("character_reference_ids") or [],
            scene_reference_ids=shot_data.get("scene_reference_ids") or [],
            prop_reference_ids=shot_data.get("prop_reference_ids") or [],
            storyboard_json=shot_data.get("storyboard_json"),
            duration_seconds=shot_data.get("duration_seconds") or 15,
            status="pending",
        ))
    plan.workflow_id = workflow.id
    plan.workflow_sync_revision = plan.revision + 1
    plan.revision += 1
    db.commit()
    db.refresh(plan)
    return {"plan": _serialize_plan(plan), "workflow_id": workflow.id, "shot_count": len(shots)}


SCREENPLAY_SPLIT_MAX_UNITS = 30


def _merge_beats_to_video_prompt(config: dict[str, Any]) -> str:
    """把场景节点的节拍列表合并成三段式视频 prompt 主体。"""
    beats = config.get("beats")
    parts: list[str] = []
    if isinstance(beats, list):
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            action = str(beat.get("action") or "").strip()
            if action:
                parts.append(action)
            dialogue = beat.get("dialogue")
            if isinstance(dialogue, list) and dialogue:
                lines = []
                for item in dialogue:
                    if isinstance(item, dict):
                        lines.append(f"{item.get('character', '')}：{item.get('line', '')}".strip("："))
                    elif isinstance(item, str) and item.strip():
                        lines.append(item.strip())
                if lines:
                    parts.append("对白：" + "；".join(lines))
            elif isinstance(dialogue, str) and dialogue.strip():
                parts.append(f"对白：{dialogue.strip()}")
    if not parts:
        parts.append(str(config.get("scene_purpose") or config.get("title") or ""))
    return "\n".join(parts)


def _scene_node_from_graph(graph: dict[str, Any], node_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """从画布图中定位场景聚合节点，返回 (node, config)。"""
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("id") or "") != node_id:
            continue
        if str(node.get("type") or "") != "scene":
            return None, {}
        return node, dict((node.get("data") or {}).get("config") or {})
    return None, {}


def _scene_config_revision(config: dict[str, Any]) -> str:
    """场景内容指纹：编辑场景/节拍后变化，用于导演方案失效判定。"""
    return _source_hash({"scenes": config.get("scenes") or [], "approved": bool(config.get("approved"))})


def _scene_source_screenplay(graph: dict[str, Any], config: dict[str, Any], scene_node_id: str) -> tuple[str, str]:
    """读取场景聚合节点绑定的剧本全文，返回 (screenplay_node_id, content)。"""
    screenplay_node_id = str(config.get("source_screenplay_node") or "").strip()
    nodes_by_id = {str(node.get("id") or ""): node for node in graph.get("nodes") or [] if isinstance(node, dict)}
    if screenplay_node_id:
        node = nodes_by_id.get(screenplay_node_id)
        if node and str(node.get("type") or "") == "screenplay":
            node_config = dict((node.get("data") or {}).get("config") or {})
            content = str(node_config.get("content") or node_config.get("screenplay") or "").strip()
            if content:
                return screenplay_node_id, content
    # 兜底：取画布中第一个剧本节点（老图未回写绑定字段）
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and str(node.get("type") or "") == "screenplay":
            node_config = dict((node.get("data") or {}).get("config") or {})
            content = str(node_config.get("content") or node_config.get("screenplay") or "").strip()
            if content:
                return str(node.get("id") or ""), content
    raise HTTPException(422, f"场景节点 {scene_node_id} 未绑定可用的剧本节点，请先从剧本节点拆分")


def _scene_screenplay_hashes(graph: dict[str, Any], config: dict[str, Any], scene_node_id: str) -> tuple[str, str, str]:
    """返回 (screenplay_node_id, screenplay_hash, scene_revision)。"""
    screenplay_node_id, content = _scene_source_screenplay(graph, config, scene_node_id)
    return (
        screenplay_node_id,
        _canvas_source_hash("screenplay_node", screenplay_node_id, content),
        _scene_config_revision(config),
    )


@router.post("/api/video-canvas/canvases/{canvas_id}/director-plan")
async def create_director_plan(canvas_id: int, body: VideoCanvasDirectorPlanRequest, request: Request, db: Session = Depends(get_db)):
    """AI 导演编排预览：把已批准场景动态编排为视频单元方案（不写图、不触发生成）。

    方案 hash 绑定当前剧本 hash、场景内容 hash 与画布 revision；任一变更后自动失效。
    """
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if body.expected_definition_revision is not None and canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请刷新后再编排", "definition_revision": canvas.definition_revision})
    graph = _latest_version(canvas.id, db).graph_json or {}
    node, config = _scene_node_from_graph(graph, body.scene_node_id)
    if node is None:
        raise HTTPException(422, "场景节点不存在或类型不正确")
    if not config.get("approved"):
        raise HTTPException(422, "场景尚未批准，请先完成剧本审核")
    scene_items = config.get("scenes")
    scenes = [item for item in scene_items if isinstance(item, dict)] if isinstance(scene_items, list) else []
    if not scenes:
        raise HTTPException(422, "场景节点没有可编排的场景数据")

    _, screenplay_hash, scene_revision = _scene_screenplay_hashes(graph, config, body.scene_node_id)

    from services.video_canvas_director import orchestrate_scene_video_units

    api_key = _canvas_deepseek_api_key(request, db)
    try:
        plan = await orchestrate_scene_video_units(
            scenes=scenes,
            source_screenplay_hash=screenplay_hash,
            source_scene_node_id=body.scene_node_id,
            source_scene_revision=scene_revision,
            api_key=api_key,
            user_constraints=body.user_constraints,
        )
    except UpstreamServiceError as exc:
        raise _translate_upstream_error(exc)

    units = plan.get("units") or []
    plan_hash = _source_hash(plan)
    return {
        "ok": True,
        "plan": plan,
        "plan_hash": plan_hash,
        "unit_count": len(units),
        "total_duration_seconds": sum(int(unit.get("duration_seconds") or 0) for unit in units if isinstance(unit, dict)),
        "source_screenplay_hash": screenplay_hash,
        "source_scene_node_id": body.scene_node_id,
        "source_scene_revision": scene_revision,
        "definition_revision": canvas.definition_revision,
    }


def _compile_scene_items_legacy(scene_items: list[dict[str, Any]], config: dict[str, Any], scene_node_id: str) -> list[dict[str, Any]]:
    """旧图兼容：无导演方案的聚合节点按场景顺序直出（仅历史画布读取用）。"""
    from services.video_duration import normalize_video_duration

    compiled: list[dict[str, Any]] = []
    for scene_index, scene in enumerate(scene_items, start=1):
        if not isinstance(scene, dict):
            continue
        requested = scene.get("duration_seconds")
        if not isinstance(requested, (int, float)):
            requested = config.get("duration_seconds")
        model_name = str(scene.get("model_id") or config.get("model_id") or "")
        normalized = normalize_video_duration(
            requested if isinstance(requested, (int, float)) else None,
            model=model_name,
            default_seconds=5,
        )
        prompt_body = _merge_beats_to_video_prompt(scene if scene is not config else config)
        video_prompt = str(scene.get("video_prompt") or "").strip()
        if not video_prompt:
            location = str(scene.get("location") or "").strip()
            time_of_day = str(scene.get("time_of_day") or "").strip()
            header_parts = []
            if location:
                header_parts.append(f"场景：{location}")
            if time_of_day:
                header_parts.append(f"时间：{time_of_day}")
            if header_parts:
                video_prompt = "；".join(header_parts) + "\n" + prompt_body
            else:
                video_prompt = prompt_body
        compiled.append(
            {
                "scene_node_id": f"{scene_node_id}#{scene_index}",
                "title": str(scene.get("title") or f"场景 {scene_index}"),
                "video_prompt": video_prompt,
                "duration_seconds": normalized,
                "duration_requested": requested if isinstance(requested, (int, float)) else None,
                "characters": scene.get("characters") or [],
            }
        )
    return compiled


STORY_ASSET_TYPES = frozenset({"character_reference", "scene_reference", "prop_reference", "style_reference", "image"})


def _serialize_canvas_asset(asset: VideoAsset) -> dict[str, Any]:
    """序列化故事级视频资产（画布/资产管理共用）。"""
    from routers.video import _serialize_datetime, _to_video_url

    return {
        "id": asset.id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "scene_id": asset.scene_id,
        "shot_id": asset.shot_id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "file_path": _to_video_url(asset.file_path),
        "provider": asset.provider,
        "prompt": asset.prompt or "",
        "meta": asset.meta_json or {},
        "created_at": _serialize_datetime(asset.created_at),
    }


@router.get("/api/stories/{story_id}/video-assets")
async def list_story_video_assets(
    story_id: int,
    request: Request,
    asset_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """故事级视频资产列表（漫剧项目无章节时复用资产分析管理）。"""
    user = _require_user(request, db)
    _require_story(story_id, user, db)
    query = db.query(VideoAsset).filter(VideoAsset.story_id == story_id, VideoAsset.status == "active")
    if asset_type:
        query = query.filter(VideoAsset.asset_type == asset_type)
    assets = query.order_by(VideoAsset.created_at.desc()).all()
    return {"story_id": story_id, "assets": [_serialize_canvas_asset(asset) for asset in assets]}


@router.post("/api/stories/{story_id}/video-assets", status_code=201)
async def create_story_video_asset(story_id: int, body: CreateVideoAssetRequest, request: Request, db: Session = Depends(get_db)):
    """创建故事级资产（chapter_id 为空），上传文件走既有 /video-assets/{id}/replace。"""
    user = _require_user(request, db)
    _require_story(story_id, user, db)
    if body.asset_type not in STORY_ASSET_TYPES:
        raise HTTPException(422, f"资产类型仅支持：{'、'.join(sorted(STORY_ASSET_TYPES))}")

    from routers.video import _validate_video_asset_storage_path

    asset = VideoAsset(
        story_id=story_id,
        chapter_id=None,
        scene_id=None,
        shot_id=None,
        asset_type=body.asset_type,
        name=body.name,
        file_path=_validate_video_asset_storage_path(body.file_path),
        provider=body.provider or "",
        prompt=body.prompt or "",
        style_preset=body.style_preset or None,
        meta_json=body.meta or {},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_canvas_asset(asset)


@router.post("/api/video-canvas/canvases/{canvas_id}/asset-analysis")
async def analyze_canvas_assets(canvas_id: int, body: VideoCanvasAssetAnalysisRequest, request: Request, db: Session = Depends(get_db)):
    """资产分析导演：剧本 → 角色/场景/道具资产清单与绘图提示词（复用生产美术/角色总监服务）。

    返回的资产由前端渲染为画布资产节点：先出参考图，再绑定到分镜/视频节点保证一致性。
    """
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if body.expected_definition_revision is not None and canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请刷新后再分析", "definition_revision": canvas.definition_revision})
    graph = _latest_version(canvas.id, db).graph_json or {}
    node, config = _scene_node_from_graph(graph, body.scene_node_id)
    if node is None:
        raise HTTPException(422, "场景节点不存在或类型不正确")
    if not config.get("approved"):
        raise HTTPException(422, "场景尚未批准，请先完成剧本审核")
    scene_items = config.get("scenes")
    scenes = [item for item in scene_items if isinstance(item, dict)] if isinstance(scene_items, list) else []
    if not scenes:
        raise HTTPException(422, "场景节点没有可分析的场景数据")

    _, _, _ = _scene_screenplay_hashes(graph, config, body.scene_node_id)
    screenplay_node_id, content = _scene_source_screenplay(graph, config, body.scene_node_id)

    from services.video_canvas_director import analyze_scene_assets

    result = await analyze_scene_assets(
        scenes=scenes,
        screenplay_text=content,
        api_key=_canvas_deepseek_api_key(request, db),
    )
    return {
        "ok": True,
        "scene_node_id": body.scene_node_id,
        "screenplay_node_id": screenplay_node_id,
        **result,
        "definition_revision": canvas.definition_revision,
    }


def _compile_scene_items_from_director_plan(
    *,
    plan: dict[str, Any],
    plan_hash: str,
    scene_node_id: str,
    scene_config: dict[str, Any],
    db: Session,
) -> list[dict[str, Any]]:
    """按导演方案编译视频单元 spec：sequence 顺序 + 模型能力时长归一 + 完整元数据。"""
    from services.video_duration import normalize_video_duration

    # 场景节点绑定的视频模型能力（可选）：归一化只发生在提交边界
    capabilities = None
    model_id = scene_config.get("model_id")
    if isinstance(model_id, int):
        from models import AiModel

        model = db.get(AiModel, model_id)
        raw = model.capabilities_json if model else None
        if isinstance(raw, dict) and isinstance(raw.get("video"), dict):
            capabilities = raw["video"]

    compiled: list[dict[str, Any]] = []
    for unit in plan.get("units") or []:
        if not isinstance(unit, dict):
            continue
        requested = unit.get("duration_seconds")
        requested_int = requested if isinstance(requested, int) and not isinstance(requested, bool) else None
        normalized = normalize_video_duration(
            requested_int,
            capabilities=capabilities if isinstance(capabilities, dict) else None,
            default_seconds=requested_int or 6,
        )
        compiled.append(
            {
                "scene_node_id": scene_node_id,
                "unit_id": str(unit.get("unit_id") or ""),
                "sequence": int(unit.get("sequence") or 0),
                "title": str(unit.get("title") or ""),
                "video_prompt": str(unit.get("video_prompt") or ""),
                "storyboard_prompt": str(unit.get("storyboard_prompt") or ""),
                "storyboard_json": unit.get("storyboard_json") if isinstance(unit.get("storyboard_json"), dict) else None,
                "duration_seconds": normalized,
                "duration_requested": unit.get("duration_requested") if isinstance(unit.get("duration_requested"), (int, float)) else requested_int,
                "duration_reason": str(unit.get("duration_reason") or ""),
                "duration_policy": "director_dynamic",
                "characters": unit.get("characters") or [],
                "visual_anchors": unit.get("visual_anchors") or [],
                "transition_in": str(unit.get("transition_in") or ""),
                "transition_out": str(unit.get("transition_out") or ""),
                "continuity": unit.get("continuity") if isinstance(unit.get("continuity"), dict) else {},
                "source_scene_ids": unit.get("scene_ids") or [],
                "source_beat_ids": unit.get("beat_ids") or [],
                "director_plan_hash": plan_hash,
            }
        )
    return compiled


@router.post("/api/video-canvas/canvases/{canvas_id}/compile-scenes")
async def compile_scenes(canvas_id: int, body: VideoCanvasCompileScenesRequest, request: Request, db: Session = Depends(get_db)):
    """把已批准的场景节点编译为视频节点组（pending 形态返回，前端确认后保存画布）。

    新路径：必须携带 AI 导演方案；编译前重校验批准状态、剧本/场景 hash、方案 hash 与
    beat 覆盖，按 sequence 输出完整单元元数据，时长经模型能力归一化。
    旧图兼容：未携带方案且节点本身是旧单场景形态时走 legacy 直出。
    """
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if body.expected_definition_revision is not None and canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新，请刷新后再编译", "definition_revision": canvas.definition_revision})
    graph = _latest_version(canvas.id, db).graph_json or {}
    node_map = {str(node.get("id") or ""): node for node in graph.get("nodes") or [] if isinstance(node, dict)}

    compiled: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_scene_ids: set[str] = set()
    for scene_node_id in body.scene_node_ids:
        node = node_map.get(scene_node_id)
        if not node or str(node.get("type") or "") != "scene":
            skipped.append({"node_id": scene_node_id, "reason": "场景节点不存在或类型不正确"})
            continue
        if scene_node_id in seen_scene_ids:
            skipped.append({"node_id": scene_node_id, "reason": "重复提交"})
            continue
        seen_scene_ids.add(scene_node_id)
        config = dict((node.get("data") or {}).get("config") or {})
        if not config.get("approved"):
            skipped.append({"node_id": scene_node_id, "reason": "场景未批准"})
            continue
        raw_scenes = config.get("scenes")
        scene_items = [item for item in raw_scenes if isinstance(item, dict)] if isinstance(raw_scenes, list) else []

        if body.director_plan is None:
            # 兼容旧图：仅当节点是旧单场景形态（无 scenes 聚合数组）时允许直出
            if not scene_items and (config.get("beats") or config.get("title")):
                compiled.extend(_compile_scene_items_legacy([config], config, scene_node_id))
                continue
            raise HTTPException(422, "请先执行 AI 导演编排，再编译视频节点组")

        if not scene_items:
            raise HTTPException(422, "场景节点没有可编译的场景数据")

        # 方案绑定校验：剧本/场景内容变更后旧方案自动失效
        _, screenplay_hash, scene_revision = _scene_screenplay_hashes(graph, config, scene_node_id)
        meta = body.director_plan.get("meta") if isinstance(body.director_plan.get("meta"), dict) else {}
        if str(meta.get("source_screenplay_hash") or "") != screenplay_hash:
            raise HTTPException(422, "剧本内容已变更，请重新执行 AI 导演编排")
        if str(meta.get("source_scene_revision") or "") != scene_revision:
            raise HTTPException(422, "场景内容已变更，请重新执行 AI 导演编排")
        if str(meta.get("source_scene_node_id") or "") != scene_node_id:
            raise HTTPException(422, "导演方案与场景节点不匹配")
        if body.director_plan_hash and body.director_plan_hash != _source_hash(body.director_plan):
            raise HTTPException(422, "导演方案校验失败，请重新编排")

        from services.video_canvas_director import normalize_and_validate_director_plan

        normalized_plan, errors = normalize_and_validate_director_plan(
            body.director_plan,
            scene_items,
            source_screenplay_hash=screenplay_hash,
            source_scene_node_id=scene_node_id,
            source_scene_revision=scene_revision,
        )
        if normalized_plan is None:
            issues = errors[:10]
            raise HTTPException(422, {"message": "导演方案不可用（" + "；".join(issues[:5]) + "）", "issues": issues})

        compiled.extend(
            _compile_scene_items_from_director_plan(
                plan=normalized_plan,
                plan_hash=body.director_plan_hash or _source_hash(body.director_plan),
                scene_node_id=scene_node_id,
                scene_config=config,
                db=db,
            )
        )
    if not compiled:
        raise HTTPException(422, {"message": "没有可编译的场景：所选场景均未批准或不存在", "skipped": skipped})
    return {"ok": True, "compiled_count": len(compiled), "skipped": skipped, "compiled": compiled}


@router.post("/api/video-canvas/canvases/{canvas_id}/screenplay-split")
async def screenplay_split(canvas_id: int, body: VideoCanvasScreenplaySplitRequest, request: Request, db: Session = Depends(get_db)):
    """剧本节点 AI 拆分：读取节点当前内容，复用现有轻量拆镜模块输出视频单元列表。

    不直接写图；前端把单元列表组装成节点组后走 pending-change/图保存确认流。
    """
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    graph = _latest_version(canvas.id, db).graph_json or {}
    node, config = _screenplay_node_from_graph(graph, body.node_id)
    if node is None:
        raise HTTPException(422, "剧本节点不存在或类型不正确")
    content = str(config.get("content") or config.get("screenplay") or "").strip()
    if not content:
        raise HTTPException(422, "剧本节点内容为空，无法拆分")

    content_hash = _canvas_source_hash("screenplay_node", body.node_id, content)
    previous_hash = str(config.get("content_hash") or "").strip()
    stale_detected = bool(previous_hash) and previous_hash != content_hash

    from services.screenplay_adapt import generate_structured_screenplay

    api_key = _canvas_deepseek_api_key(request, db)
    try:
        structured = await generate_structured_screenplay(content=content, api_key=api_key, max_scenes=SCREENPLAY_SPLIT_MAX_UNITS)
    except UpstreamServiceError as exc:
        raise _translate_upstream_error(exc)
    scenes = structured["scenes"]

    units: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes, start=1):
        units.append(
            {
                "unit_index": index,
                "scene_id": scene["scene_id"],
                "title": scene["title"],
                "location": scene["location"],
                "time_of_day": scene["time_of_day"],
                "characters": scene["characters"],
                "scene_purpose": scene["scene_purpose"],
                "visual_anchors": scene["visual_anchors"],
                "beats": scene["beats"],
                "transition_to_next_scene": scene["transition_to_next_scene"],
                "duration_seconds": int(scene["duration_seconds"]),
                "duration_reason": scene["duration_reason"],
            }
        )
    if not units:
        raise HTTPException(502, "拆分未返回可用场景，请稍后重试或更换文本模型")

    return {
        "ok": True,
        "node_id": body.node_id,
        "content_hash": content_hash,
        "stale_detected": stale_detected,
        "unit_count": len(units),
        "truncated": bool(structured.get("truncated")),
        "units": units,
    }


@router.get("/api/manga-drama/importable-stories")
async def list_importable_novel_stories(request: Request, db: Session = Depends(get_db)):
    """用户名下可作为剧本素材的小说作品（story_type='novel'）及其章节摘要。"""
    user = _require_user(request, db)
    stories = (
        db.query(Story)
        .filter(Story.owner_user_id == user.id, Story.story_type == "novel")
        .order_by(Story.created_at.desc())
        .all()
    )
    items: list[dict[str, Any]] = []
    for story in stories:
        chapters = (
            db.query(Chapter)
            .filter(Chapter.story_id == story.id)
            .order_by(Chapter.chapter_number.asc())
            .all()
        )
        items.append(
            {
                "story_id": story.id,
                "title": story.title,
                "chapter_count": len(chapters),
                "chapters": [
                    {
                        "chapter_id": chapter.id,
                        "chapter_number": chapter.chapter_number,
                        "title": chapter.title,
                        "content_chars": len((chapter.novel_content or "").strip()),
                        "has_content": bool((chapter.novel_content or "").strip()),
                    }
                    for chapter in chapters
                ],
            }
        )
    return {"stories": items}


@router.post("/api/video-canvas/canvases/{canvas_id}/import-screenplay")
async def import_screenplay(canvas_id: int, body: VideoCanvasScreenplayImportRequest, request: Request, db: Session = Depends(get_db)):
    """导入小说章节 → AI 改写为漫剧剧本草稿。

    只读原作品：此处重新校验章节所有权并重读正文（不信任客户端内容），
    返回 pending-change 形态的剧本文本草稿，由前端走画布保存确认流。
    """
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)

    resolved: list[dict[str, Any]] = []
    seen_chapter_ids: set[int] = set()
    for source in body.sources:
        chapter = db.get(Chapter, source.chapter_id)
        if not chapter or chapter.story_id != source.story_id:
            raise HTTPException(422, f"章节 {source.chapter_id} 不存在或不属于指定作品")
        story = db.get(Story, source.story_id)
        if not story or story.owner_user_id != user.id:
            raise HTTPException(403, f"作品 {source.story_id} 不属于当前用户")
        content = (chapter.novel_content or "").strip()
        if not content:
            raise HTTPException(422, f"章节「{chapter.title or source.chapter_id}」正文为空，无法导入")
        if chapter.id in seen_chapter_ids:
            raise HTTPException(422, f"章节「{chapter.title or chapter.id}」重复选择")
        seen_chapter_ids.add(chapter.id)
        resolved.append(
            {
                "story_id": chapter.story_id,
                "chapter_id": chapter.id,
                "title": chapter.title or f"第{chapter.chapter_number}章",
                "content": content,
            }
        )

    from services.screenplay_adapt import adapt_novel_to_screenplay

    api_key = _canvas_deepseek_api_key(request, db)
    try:
        result = await adapt_novel_to_screenplay(chapters=resolved, api_key=api_key)
    except UpstreamServiceError as exc:
        raise _translate_upstream_error(exc)
    return {
        "ok": True,
        "screenplay_text": result["screenplay_text"],
        "source_refs": result["source_refs"],
        "batch_count": result["batch_count"],
        "content_chars": len(result["screenplay_text"]),
    }


@router.put("/api/video-canvas/canvases/{canvas_id}/graph")
async def save_video_canvas_graph(canvas_id: int, body: VideoCanvasGraphSave, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    canvas = _lock_canvas(canvas_id, user, db)
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
    canvas = _lock_canvas(canvas_id, user, db)
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
    target_chapter_id = _run_target_chapter_id(canvas, version, db)
    if target_chapter_id is not None:
        chapter = db.get(Chapter, target_chapter_id)
        if not chapter or chapter.story_id != canvas.story_id:
            raise HTTPException(422, "画布运行章节不属于当前作品")
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
        plan_json={"topological_order": ordered_node_ids, "warnings": validation["warnings"], "chapter_id": target_chapter_id},
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
    canvas = _require_canvas(canvas_id, user, db)
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
                chapter_id=(run.plan_json or {}).get("chapter_id") if isinstance((run.plan_json or {}).get("chapter_id"), int) else canvas.default_chapter_id,
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
