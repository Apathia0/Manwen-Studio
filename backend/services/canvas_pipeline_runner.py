"""画布自动编排运行器：在服务端后台按固定顺序跑完 拆分 → 导演 → 资产 → 分镜编排。

与"助手在对话里一步步调用工具"相比：
- 不受对话轮次和 token 预算限制，关掉页面也会继续；
- 每一步读取数据库里的最新画布，只有一份权威状态；
- 可恢复的失败自动重试（导演阶段第二次会带上"细分镜头、控制对白量"的约束），
  只有积分、权限、缺少剧本这类无法自行解决的问题才停下，并给出明确原因。

运行器只做编排，不提交出图、视频、合片等付费生成任务。
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

from database import SessionLocal
from models import VideoCanvas
from services.errors import UpstreamServiceError

logger = logging.getLogger(__name__)

PIPELINE_TASK_TYPE = "video_canvas_pipeline"
STAGE_LABELS = {"split": "拆分剧本", "director": "导演编排", "assets": "资产分析", "compile": "分镜编排"}
MAX_STAGE_ATTEMPTS = 2
# 上游模型服务暂时不可用（5xx、超时）时，多等几次再重试，而不是第二次失败就整体停下
MAX_TRANSIENT_ATTEMPTS = 4
TRANSIENT_BACKOFF_SECONDS = (5, 15, 30)
MAX_STEPS = 40
RETRY_HINT = "每个镜头只承担一个动作或一轮对话，对白量小、时长可控；按人物焦点细分镜头，避免把整段戏塞进一个镜头。"
# 这些状态码说明问题出在账户、权限或资源本身，重试没有意义
_UNRECOVERABLE_STATUS = {401, 402, 403, 404}


class PipelineStopped(RuntimeError):
    """需要用户处理才能继续的情况（缺剧本、积分不足、没有权限等）。"""


def _config(node: dict[str, Any]) -> dict[str, Any]:
    return (node.get("data") or {}).get("config") or {}


def _live(nodes: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [n for n in nodes if isinstance(n, dict) and n.get("type") == kind and not _config(n).get("stale")]


def next_pipeline_step(graph: dict[str, Any], scene_ids: set[str] | None = None) -> tuple[str, dict[str, Any]] | None:
    """根据画布当前内容推断下一步要做什么；全部完成返回 None。只读，不修改入参。

    scene_ids 不为空时只处理这些场景（局部重做），不会再拆分剧本，也不会碰其他场景。"""
    nodes = [n for n in (graph or {}).get("nodes") or [] if isinstance(n, dict)]
    screenplays = [n for n in _live(nodes, "screenplay") if str(_config(n).get("content") or _config(n).get("screenplay") or "").strip()]
    if not screenplays:
        raise PipelineStopped("画布上还没有剧本：请先让助手写剧本，或导入小说章节后再自动编排")
    scenes = _live(nodes, "scene")
    for screenplay in screenplays if not scene_ids else []:
        own = [s for s in scenes if _config(s).get("source_screenplay_node") == screenplay["id"]]
        # 手动拆分的场景节点可能没有写来源字段：只有一个剧本时，画布上的场景都算它的
        if not own and len(screenplays) == 1:
            own = scenes
        if not own:
            return "split", {"node_id": screenplay["id"]}
    for scene in scenes:
        scene_id = scene["id"]
        if scene_ids and scene_id not in scene_ids:
            continue
        config = _config(scene)
        if not config.get("director_plan"):
            return "director", {"scene_node_id": scene_id}
        has_assets = any(
            _config(n).get("asset_role") in {"character", "scene", "prop"}
            and scene_id in {_config(n).get("asset_scene_node"), _config(n).get("source_scene_node")}
            for n in nodes if not _config(n).get("stale")
        )
        if not has_assets:
            return "assets", {"scene_node_id": scene_id}
        compiled = any(_config(n).get("source_scene_node") == scene_id and _config(n).get("unit_id") for n in nodes if not _config(n).get("stale"))
        if not compiled:
            return "compile", {"scene_node_id": scene_id}
    return None


def _error_text(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    if isinstance(detail, str) and detail.strip():
        return detail
    return str(exc) or type(exc).__name__


def _is_transient(exc: BaseException) -> bool:
    """上游暂时不可用（值得等一会儿再试，且不需要改任何提示词）。质量校验没通过不算。"""
    if isinstance(exc, UpstreamServiceError):
        return bool(getattr(exc, "retryable", False)) and getattr(exc, "code", "") != "canvas_director_quality_failed"
    if isinstance(exc, HTTPException):
        return int(getattr(exc, "status_code", 0) or 0) in {502, 503, 504}
    return False


def _recoverable(exc: BaseException) -> bool:
    if isinstance(exc, PipelineStopped):
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(exc, HTTPException):
        return status not in _UNRECOVERABLE_STATUS
    if isinstance(exc, UpstreamServiceError):
        return bool(getattr(exc, "retryable", False)) or getattr(exc, "code", "") == "canvas_director_quality_failed" or status not in _UNRECOVERABLE_STATUS
    return True


def _latest_graph(canvas_id: int) -> tuple[dict[str, Any], int, int]:
    from routers import video_canvas as api

    with SessionLocal() as db:
        canvas = db.get(VideoCanvas, canvas_id)
        if not canvas:
            raise PipelineStopped("画布不存在或已被删除")
        return deepcopy(api._latest_version(canvas.id, db).graph_json or {}), canvas.definition_revision, canvas.owner_user_id


async def _execute_stage(canvas_id: int, owner_user_id: int, stage: str, params: dict[str, Any], action_id: str) -> dict[str, Any]:
    """以画布所有者身份、走与助手相同的服务端阶段网关执行一步（全自动：场景由网关代为批准）。"""
    from services.canvas_stage_gateway import execute_agent_canvas_stage

    db = SessionLocal()
    try:
        canvas = db.get(VideoCanvas, canvas_id)
        if not canvas or canvas.owner_user_id != owner_user_id:
            raise PipelineStopped("画布不存在或无权访问")
        request = Request({"type": "http", "method": "POST", "path": "/internal/canvas-pipeline", "headers": []})
        request.state.current_user = SimpleNamespace(id=owner_user_id)
        request.state.db = db
        request.state.trusted_agent_dispatch = True
        parameters = {
            **params,
            "agent_action_id": action_id,
            "expected_definition_revision": canvas.definition_revision,
            "auto_approve_scenes": True,
        }
        return await execute_agent_canvas_stage(canvas.id, stage, parameters, request, db)
    finally:
        db.close()


def _apply_repair(canvas_id: int, owner_user_id: int, scene_id: str, stage: str) -> None:
    """质量循环用：把该场景从 stage 起的产物标记失效，下一轮由运行器重新生成。"""
    from routers import video_canvas as api
    from services.canvas_quality_review import apply_redo
    from services.canvas_stage_gateway import _save

    with SessionLocal() as db:
        canvas = db.get(VideoCanvas, canvas_id)
        if not canvas:
            raise PipelineStopped("画布不存在或已被删除")
        graph = deepcopy(api._latest_version(canvas.id, db).graph_json or {})
        apply_redo(graph, scene_id, stage)
        _save(graph, canvas, SimpleNamespace(id=owner_user_id), db, canvas.definition_revision, "自动质检：重做未通过的阶段")


async def run_canvas_pipeline(canvas_id: int, owner_user_id: int, *, user_constraints: str | None = None, task_id: str | None = None, scene_node_ids: list[str] | None = None, **_: Any) -> dict[str, Any]:
    """后台任务入口：循环"读最新画布 → 推断下一步 → 执行（失败自动重试）"，直到全部完成或遇到需要用户处理的问题。

    全部完成后做一次自动质检：能靠重做某阶段修复的错误，每个场景最多自动修复一轮。"""
    from services.canvas_quality_review import repair_targets, review_graph
    from services.task_manager import task_manager

    only_scenes = set(scene_node_ids or []) or None
    repaired: set[tuple[str, str]] = set()

    steps: list[dict[str, Any]] = []
    auto_fixes: list[str] = []
    seen: dict[tuple[str, str], int] = {}

    def publish(message: str, stage: str) -> None:
        task_manager.update_task_metadata(task_id, stage=stage, message=message, steps=steps, auto_fixes=auto_fixes, canvas_id=canvas_id)

    for step_no in range(1, MAX_STEPS + 1):
        if task_manager.is_cancellation_requested(task_id):
            publish("已取消自动编排", "cancelled")
            return {"status": "cancelled", "steps": steps, "auto_fixes": auto_fixes}
        graph, _, _ = _latest_graph(canvas_id)
        step = next_pipeline_step(graph, only_scenes)
        if step is None:
            review = review_graph(graph)
            fixable = [(key, notes) for key, notes in repair_targets(review).items() if key not in repaired and (not only_scenes or key[0] in only_scenes)]
            if fixable:
                for (scene_id, stage), notes in fixable:
                    repaired.add((scene_id, stage))
                    _apply_repair(canvas_id, owner_user_id, scene_id, stage)
                    auto_fixes.append(f"自动质检发现问题并重做了{STAGE_LABELS[stage]}：{notes[0]}")
                seen.clear()
                publish("自动质检发现可修复的问题，正在重做", "review")
                continue
            publish("自动编排完成：可以在画布上检查节点，然后提交出图和视频生成", "completed")
            return {"status": "succeeded", "steps": steps, "auto_fixes": auto_fixes, "review_error_count": review["error_count"]}
        stage, params = step
        target = str(params.get("scene_node_id") or params.get("node_id") or "")
        seen[(stage, target)] = seen.get((stage, target), 0) + 1
        if seen[(stage, target)] > 2:
            # 同一步执行成功却没有产生应有的结果：停下来，避免无限循环重复扣费
            raise PipelineStopped(f"{STAGE_LABELS[stage]}已完成但画布上没有出现对应结果，请检查该场景节点后重试")
        record = {"stage": stage, "label": STAGE_LABELS[stage], "target": target, "status": "running", "attempts": 0, "error": None}
        steps.append(record)
        last_error: BaseException | None = None
        attempt = 0
        limit = MAX_STAGE_ATTEMPTS
        quality_retry = False
        while attempt < limit:
            attempt += 1
            record["attempts"] = attempt
            publish(f"正在{record['label']}" + (f"（第 {attempt} 次尝试）" if attempt > 1 else ""), stage)
            stage_params = dict(params)
            # 用户自己的约束照常传；“细分镜头”的重试提示只在这一次调用里临时生效，不能写进画布设置，
            # 否则之后每次导演都会带着它，把镜头越拆越细（固定 15 秒档位的模型下还会被填充成更长的片子）。
            if user_constraints and stage == "director":
                stage_params["user_constraints"] = user_constraints
            if quality_retry and stage in {"director", "split"}:
                stage_params["retry_hint"] = RETRY_HINT
            try:
                result = await _execute_stage(canvas_id, owner_user_id, stage, stage_params, f"pipeline:{task_id}:{step_no}:{attempt}")
            except Exception as exc:  # noqa: BLE001 - 分类后决定重试或停止
                last_error = exc
                logger.warning("[canvas_pipeline] canvas=%s stage=%s attempt=%s 失败：%s", canvas_id, stage, attempt, _error_text(exc))
                if not _recoverable(exc):
                    break
                if _is_transient(exc):
                    limit = max(limit, MAX_TRANSIENT_ATTEMPTS)
                    if attempt < limit:
                        delay = TRANSIENT_BACKOFF_SECONDS[min(attempt - 1, len(TRANSIENT_BACKOFF_SECONDS) - 1)]
                        publish(f"上游服务暂时不可用，{delay} 秒后自动重试（第 {attempt + 1} 次）", stage)
                        await asyncio.sleep(delay)
                    continue
                quality_retry = True
                continue
            record["status"] = "succeeded"
            record["error"] = None
            if attempt > 1:
                auto_fixes.append(f"{record['label']}第一次未通过，已自动调整后重试成功")
            for warning in (result or {}).get("warnings") or []:
                if isinstance(warning, str) and ("自动" in warning or "保守" in warning):
                    auto_fixes.append(warning)
            last_error = None
            break
        if last_error is not None:
            record["status"] = "failed"
            record["error"] = _error_text(last_error)
            publish(f"{record['label']}失败：{record['error']}", "failed")
            raise PipelineStopped(f"{record['label']}失败：{record['error']}")
        publish(f"{record['label']}完成", stage)
    raise PipelineStopped("自动编排步骤过多，已停止以免重复消耗，请检查画布节点后重试")


def active_pipeline_task(db, canvas: VideoCanvas) -> Any:
    """当前画布正在进行中的自动编排任务（没有返回 None）。"""
    from models import BackgroundTask

    rows = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.task_type == PIPELINE_TASK_TYPE, BackgroundTask.story_id == canvas.story_id)
        .order_by(BackgroundTask.id.desc())
        .limit(30)
        .all()
    )
    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if metadata.get("canvas_id") == canvas.id and row.status in {"pending", "running", "retrying", "cancel_requested"}:
            return row
    return None


def latest_pipeline_task(db, canvas: VideoCanvas) -> Any:
    from models import BackgroundTask

    rows = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.task_type == PIPELINE_TASK_TYPE, BackgroundTask.story_id == canvas.story_id)
        .order_by(BackgroundTask.id.desc())
        .limit(30)
        .all()
    )
    return next((row for row in rows if (row.metadata_json or {}).get("canvas_id") == canvas.id), None)


async def start_canvas_pipeline(db, canvas: VideoCanvas, owner_user_id: int, user_constraints: str | None = None, scene_node_ids: list[str] | None = None) -> dict[str, Any]:
    """启动（或返回已在进行的）自动编排任务。"""
    import uuid

    from services.task_manager import task_manager

    existing = active_pipeline_task(db, canvas)
    if existing:
        return {"task_id": existing.task_id, "already_running": True}
    task_id = f"canvas-pipeline-{canvas.id}-{uuid.uuid4().hex[:10]}"
    await task_manager.submit_task(
        task_id,
        PIPELINE_TASK_TYPE,
        run_canvas_pipeline,
        canvas.id,
        owner_user_id,
        user_constraints=user_constraints,
        scene_node_ids=scene_node_ids,
        timeout=3600,
        max_retries=0,
        story_id=canvas.story_id,
        metadata={"canvas_id": canvas.id, "steps": [], "auto_fixes": [], "running_stage": "running", "running_message": "自动编排已开始"},
    )
    return {"task_id": task_id, "already_running": False}
