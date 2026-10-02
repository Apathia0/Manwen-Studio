"""画布 Agent 的持久阶段授权，所有模式均在服务端执行相同的归属与版本校验。"""

import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request

from fastapi import HTTPException

from database import SessionLocal
from models import CanvasAgentAction, VideoCanvas, VideoCanvasRun, VideoCanvasVersion


from services.canvas_ops_preview import build_ops_preview, node_fingerprint, operations_digest, operations_overwrite_existing

# 这些来源的版本是用户/前端自己的保存（如发送消息前的 flush），不代表画布被他人或其他阶段改写。
_BENIGN_VERSION_SOURCES = {"manual"}

ACTION_TOOLS = {"apply_canvas_ops", "canvas_stage"}
# 全自动模式下，这些阶段之后的编排交给后台运行器（services/canvas_pipeline_runner.py）
PIPELINE_HANDOFF_STAGES = {"split", "director", "assets", "compile"}
_CONTINUATION_STAGES = {"images": "videos", "videos": "concat"}


def _proposal_scope_key(args: dict[str, Any]) -> tuple[str, str]:
    """提案幂等键：stage（或首个操作的 op 类型）+ 目标 node_id。

    同阶段同目标的 pending 提案复用已有记录，不因 summary 微差重复创建；
    screenplay 尚未落节点（无 node_id）时用正文摘要充当目标，防止不同正文互相复用。
    """
    stage = str(args.get("stage") or "").strip()
    raw_parameters = args.get("parameters")
    parameters: dict[str, Any] = raw_parameters if isinstance(raw_parameters, dict) else {}
    if stage:
        target = str(
            parameters.get("node_id")
            or parameters.get("scene_node_id")
            or parameters.get("screenplay_node_id")
            or ""
        )
        if not target:
            node_ids = parameters.get("node_ids") or parameters.get("target_node_ids")
            if isinstance(node_ids, list) and node_ids:
                target = ",".join(str(item) for item in node_ids)
        if not target and stage == "screenplay":
            content = str(parameters.get("content") or parameters.get("screenplay_text") or "")
            if content:
                target = "content:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return stage, target
    # apply_canvas_ops 没有 stage：用首个操作类型 + 目标节点作为幂等键。
    operations = args.get("operations")
    first = next((op for op in operations if isinstance(op, dict)), None) if isinstance(operations, list) else None
    if not first:
        return "node_edit", ""
    raw_node = first.get("node")
    node_spec: dict[str, Any] = raw_node if isinstance(raw_node, dict) else {}
    return str(first.get("op") or "node_edit"), str(first.get("node_id") or node_spec.get("id") or "")


_NON_SEMANTIC_ARG_KEYS = {"summary", "expected_definition_revision", "agent_action_id", "auto_approve_scenes"}


def _canonical_args(arguments: Any) -> str:
    """去掉摘要、版本号等不影响实际效果的字段后的稳定序列化，用于识别重复提交。"""
    args = dict(arguments or {})
    for key in _NON_SEMANTIC_ARG_KEYS:
        args.pop(key, None)
    if isinstance(args.get("parameters"), dict):
        args["parameters"] = {k: v for k, v in args["parameters"].items() if k not in _NON_SEMANTIC_ARG_KEYS}
    return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)


def _already_applied_action(db, canvas, conversation_id: int, name: str, args: dict[str, Any]):
    """本会话最近已完成、参数完全相同、且之后画布没有再变化的动作：再次提交就是重复执行。"""
    parameters = args.get("parameters") if isinstance(args.get("parameters"), dict) else {}
    if parameters.get("regenerate"):
        return None
    signature = _canonical_args(args)
    recent = (
        db.query(CanvasAgentAction)
        .filter(
            CanvasAgentAction.canvas_id == canvas.id,
            CanvasAgentAction.conversation_id == conversation_id,
            CanvasAgentAction.tool_name == name,
            CanvasAgentAction.status == "completed",
        )
        .order_by(CanvasAgentAction.id.desc())
        .limit(10)
        .all()
    )
    for item in recent:
        result = item.result_json if isinstance(item.result_json, dict) else {}
        if result.get("definition_revision") == canvas.definition_revision and _canonical_args(item.arguments_json) == signature:
            return item
    return None


def operation_digest_of(arguments: Any) -> str:
    """提案参数中操作列表的摘要，用于判断两次 apply_canvas_ops 提案是否等价。"""
    return operations_digest((arguments or {}).get("operations"))


def serialize_action(action: CanvasAgentAction) -> dict[str, Any]:
    return {
        "id": action.id, "canvas_id": action.canvas_id, "stage": action.stage,
        "summary": action.summary, "parameters": action.arguments_json,
        "permission_mode": action.permission_mode,
        "expected_definition_revision": action.expected_definition_revision,
        "status": action.status, "result": action.result_json,
        "preview": (action.result_json or {}).get("preview") if isinstance(action.result_json, dict) else None,
    }


def serialize_waiting_tasks(actions: list[CanvasAgentAction]) -> list[dict[str, Any]]:
    """Return every recoverable backend task while preserving legacy payload shape."""
    waiting: list[dict[str, Any]] = []
    for action in actions:
        if action.status != "waiting":
            continue
        pending_task = (action.result_json or {}).get("pending_task")
        if not isinstance(pending_task, dict):
            continue
        waiting.append({
            **pending_task,
            "action_id": action.id,
            "stage": action.stage,
            "permission_mode": action.permission_mode,
        })
    return waiting


def _owned_canvas(db, context):
    key = context.pending_change_key
    canvas = db.get(VideoCanvas, context.workflow_id)
    if not key or not canvas or canvas.owner_user_id != key.user_id or canvas.story_id != context.story_id:
        raise HTTPException(403, "画布不存在或不属于当前用户")
    return canvas


def _owned_action(db, context, action_id):
    action = db.query(CanvasAgentAction).filter(CanvasAgentAction.id == action_id).with_for_update().first()
    key = context.pending_change_key
    if not key or not action or action.owner_user_id != key.user_id or action.conversation_id != key.conversation_id or action.canvas_id != context.workflow_id:
        raise HTTPException(404, "阶段提案不存在或不属于当前会话")
    return action


def _revision_drift_is_benign(db, canvas, action) -> bool:
    """提案后画布版本号上涨，但变化与提案无关时允许继续（点“同意”前前端会先保存本地草稿，版本号因此 +1）。

    - canvas_stage：只要期间的版本全是用户自己的保存，阶段本来就基于最新图执行，放行；
    - apply_canvas_ops：被改/删的目标节点内容指纹未变才放行，否则预览已过期，必须重新提案。
    """
    expected = action.expected_definition_revision
    current = canvas.definition_revision
    if expected is None or expected >= current:
        return False
    rows = (
        db.query(VideoCanvasVersion)
        .filter(VideoCanvasVersion.canvas_id == canvas.id, VideoCanvasVersion.version_no > expected, VideoCanvasVersion.version_no <= current)
        .order_by(VideoCanvasVersion.version_no)
        .all()
    )
    if len(rows) != current - expected or any(row.source not in _BENIGN_VERSION_SOURCES for row in rows):
        return False
    if action.tool_name != "apply_canvas_ops":
        return True
    base = (
        db.query(VideoCanvasVersion)
        .filter(VideoCanvasVersion.canvas_id == canvas.id, VideoCanvasVersion.version_no == expected)
        .first()
    )
    if base is None:
        return False
    before = {str(node.get("id")): node for node in (base.graph_json or {}).get("nodes", []) if isinstance(node, dict)}
    after = {str(node.get("id")): node for node in (rows[-1].graph_json or {}).get("nodes", []) if isinstance(node, dict)}
    for op in (action.arguments_json or {}).get("operations") or []:
        if not isinstance(op, dict) or op.get("op") not in {"update_node", "delete_node"}:
            continue
        node_id = str(op.get("node_id") or "")
        if node_id not in before or node_id not in after or node_fingerprint(before[node_id]) != node_fingerprint(after[node_id]):
            return False
    return True


def claim_approval(context, action_id: int) -> tuple[str, dict[str, Any]]:
    """审批只从受认证请求进入，原子消费待确认动作，绝不解析自然语言授权。"""
    with SessionLocal() as db:
        canvas = _owned_canvas(db, context)
        action = _owned_action(db, context, action_id)
        if action.status != "pending":
            raise HTTPException(409, "该提案已处理，请刷新阶段状态")
        if action.permission_mode != context.canvas_permission_mode:
            raise HTTPException(409, "权限模式已变化，请在当前模式重新提出阶段计划")
        if action.expected_definition_revision != canvas.definition_revision:
            try:
                benign = _revision_drift_is_benign(db, canvas, action)
            except Exception:
                db.rollback()
                benign = False
            if not benign:
                # 旧提案作废，避免残留成永远无法确认的待审批项。
                action.status = "superseded"
                db.commit()
                raise HTTPException(409, "画布内容在提案之后被修改，旧提案不可执行，请让助手基于最新画布重新提案")
            # 变化与提案无关：把提案锚点前移到当前版本，后续阶段的版本校验按新锚点进行。
            action.expected_definition_revision = canvas.definition_revision
        action.status = "executing"
        db.commit()
        return action.tool_name, copy.deepcopy(action.arguments_json)


def revise_proposal(context, action_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        _owned_canvas(db, context)
        action = _owned_action(db, context, action_id)
        if action.status != "pending":
            raise HTTPException(409, "仅待确认提案可以修改")
        action.status = "superseded"
        db.commit()
        return serialize_action(action)


def _continuation_parameters(next_stage: str, result: dict[str, Any]) -> dict[str, Any]:
    """从已完成阶段的结构化回执生成下一阶段的最小参数集。"""
    if next_stage in {"split"}:
        node_id = result.get("node_id")
        return {"node_id": node_id} if node_id else {}
    if next_stage in {"director", "assets", "compile"}:
        node_id = result.get("scene_node_id")
        return {"scene_node_id": node_id} if node_id else {}
    if next_stage in {"images", "videos", "concat"}:
        node_ids = result.get("node_ids")
        return {"node_ids": list(node_ids)} if isinstance(node_ids, list) else {}
    return {}


def continue_canvas_stage_after_run(task_id: str, result: Any) -> dict[str, Any] | None:
    """持久化画布 Agent 的下一阶段；重复任务回调只产生一条 continuation。

    该函数刻意只做数据库状态转换，不在后台任务回调里重新提交上游生成请求。
    下一阶段以 queued/pending/waiting 动作落库，进程重启或后续结构化审批可以安全接续。
    """
    if not isinstance(result, dict) or str(result.get("status") or "").lower() != "succeeded":
        return None
    db = SessionLocal()
    try:
        from models import BackgroundTask
        task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
        if not task or task.task_type != "video_canvas_run":
            return None
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        run_id = int(metadata.get("run_id") or result.get("run_id") or 0)
        canvas_id = int(metadata.get("canvas_id") or 0)
        action_id = int(metadata.get("agent_action_id") or 0)
        if not run_id or not canvas_id:
            return None
        run = db.query(VideoCanvasRun).filter(VideoCanvasRun.id == run_id, VideoCanvasRun.canvas_id == canvas_id).with_for_update().first()
        if not run or run.status != "succeeded":
            return None
        action_query = db.query(CanvasAgentAction).filter(CanvasAgentAction.canvas_id == canvas_id)
        if action_id:
            action_query = action_query.filter(CanvasAgentAction.id == action_id)
        else:
            action_query = action_query.filter(CanvasAgentAction.status == "waiting")
        actions = action_query.with_for_update().all()
        action = next(
            (
                candidate
                for candidate in actions
                if int(((candidate.result_json or {}).get("pending_task") or {}).get("run_id") or 0) == run_id
            ),
            None,
        )
        if not action:
            # A second callback sees the source action after the first callback
            # committed it as completed; return the durable continuation instead
            # of creating another action.
            for candidate in actions:
                continuation_id = (candidate.result_json or {}).get("continuation_id")
                if continuation_id:
                    return {"action_id": int(continuation_id), "idempotent": True}
            return None
        pending = (action.result_json or {}).get("pending_task") or {}
        action_result = dict(action.result_json or {})
        if int(pending.get("run_id") or 0) != run_id:
            return None
        next_stage = str(action_result.get("next_stage") or "").strip()
        if next_stage not in {"split", "director", "assets", "compile", "images", "videos", "concat"}:
            next_stage = str(action.arguments_json.get("next_stage") or "").strip()
        if not next_stage:
            action.status = "completed"
            action_result["resumed"] = True
            action.result_json = action_result
            db.commit()
            return None
        marker = {"source_action_id": action.id, "run_id": run_id, "next_stage": next_stage}
        existing = db.query(CanvasAgentAction).filter(
            CanvasAgentAction.canvas_id == canvas_id,
            CanvasAgentAction.conversation_id == action.conversation_id,
            CanvasAgentAction.owner_user_id == action.owner_user_id,
        ).all()
        for candidate in existing:
            continuation = (candidate.result_json or {}).get("continuation")
            if continuation == marker:
                action.status = "completed"
                action.result_json = {**action_result, "continuation_id": candidate.id, "resumed": True}
                db.commit()
                return {"action_id": candidate.id, "idempotent": True}
        canvas = db.get(VideoCanvas, canvas_id)
        if not canvas or canvas.owner_user_id != action.owner_user_id:
            return None
        result_revision = action_result.get("definition_revision")
        if isinstance(result_revision, int) and canvas.definition_revision != result_revision:
            action.status = "blocked"
            action.result_json = {
                **action_result,
                "continuation_blocked": True,
                "error": "画布定义已变化，请重新审阅后继续下一阶段",
            }
            db.commit()
            return {"blocked": True, "reason": "definition_revision_conflict"}
        mode = action.permission_mode
        next_parameters = _continuation_parameters(next_stage, action_result)
        next_args = {
            "canvas_id": canvas_id,
            "stage": next_stage,
            "summary": f"继续{next_stage}阶段",
            "parameters": next_parameters,
        }
        status = "queued" if mode == "auto" else "pending"
        continuation_result = {"continuation": marker, "source_run_id": run_id, "waiting_for_approval": status == "pending"}
        next_action = CanvasAgentAction(
            canvas_id=canvas_id,
            owner_user_id=action.owner_user_id,
            conversation_id=action.conversation_id,
            permission_mode=mode,
            stage=next_stage,
            tool_name=action.tool_name,
            summary=next_args["summary"],
            arguments_json=next_args,
            expected_definition_revision=canvas.definition_revision,
            status=status,
            result_json=continuation_result,
        )
        db.add(next_action)
        db.flush()
        action.status = "completed"
        action.result_json = {**action_result, "continuation_id": next_action.id, "resumed": True}
        db.commit()
        return {"action_id": next_action.id, "status": status, "next_stage": next_stage, "idempotent": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _persist_next_action(action_id: int, result: dict[str, Any], *, source_run_id: int | None = None) -> dict[str, Any] | None:
    """Create the next action for a synchronous stage result, idempotently."""
    next_stage = str(result.get("next_stage") or "").strip()
    if next_stage not in {"split", "director", "assets", "compile", "images", "videos", "concat"}:
        return None
    with SessionLocal() as db:
        source = db.query(CanvasAgentAction).filter(CanvasAgentAction.id == action_id).with_for_update().first()
        if not source:
            return None
        if source.permission_mode == "auto" and next_stage in {"images", "videos", "concat"}:
            # 全自动链路在节点编排完成（compile）后终止，生成任务留给用户提交。
            source.status = "completed"
            db.commit()
            return None
        canvas = db.get(VideoCanvas, source.canvas_id)
        if not canvas or canvas.owner_user_id != source.owner_user_id:
            source.status = "failed"
            source.result_json = {**(source.result_json or {}), "error": "画布不存在或无权访问"}
            db.commit()
            return {"action_id": action_id, "status": "failed"}
        marker = {"source_action_id": source.id, "run_id": int(source_run_id or 0), "next_stage": next_stage}
        for candidate in db.query(CanvasAgentAction).filter(
            CanvasAgentAction.canvas_id == source.canvas_id,
            CanvasAgentAction.conversation_id == source.conversation_id,
            CanvasAgentAction.owner_user_id == source.owner_user_id,
        ).all():
            if (candidate.result_json or {}).get("continuation") == marker:
                source.status = "completed"
                source.result_json = {**(source.result_json or {}), "continuation_id": candidate.id}
                db.commit()
                return {"action_id": candidate.id, "status": candidate.status, "idempotent": True}
        args = {
            "canvas_id": source.canvas_id,
            "stage": next_stage,
            "summary": f"继续{next_stage}阶段",
            "parameters": _continuation_parameters(next_stage, result),
        }
        next_action = CanvasAgentAction(
            canvas_id=source.canvas_id,
            owner_user_id=source.owner_user_id,
            conversation_id=source.conversation_id,
            permission_mode=source.permission_mode,
            stage=next_stage,
            tool_name=source.tool_name,
            summary=args["summary"],
            arguments_json=args,
            expected_definition_revision=canvas.definition_revision,
            status="queued" if source.permission_mode == "auto" else "pending",
            result_json={"continuation": marker, "source_run_id": source_run_id},
        )
        db.add(next_action)
        db.flush()
        source.status = "completed"
        source.result_json = {**(source.result_json or {}), "continuation_id": next_action.id}
        db.commit()
        return {"action_id": next_action.id, "status": next_action.status, "idempotent": False}


async def dispatch_queued_canvas_action(action_id: int) -> dict[str, Any] | None:
    """Consume one auto continuation and execute it through the trusted gateway.

    Claiming is a short transaction (queued -> executing). Gateway work happens
    outside that transaction, so duplicate callback tasks cannot execute it twice.
    A retry after a process crash sees ``executing`` and deliberately does not
    replay an unknown side effect; startup recovery can surface it for repair.
    """
    db = SessionLocal()
    try:
        action = db.query(CanvasAgentAction).filter(
            CanvasAgentAction.id == action_id,
            CanvasAgentAction.permission_mode == "auto",
        ).with_for_update().first()
        if not action:
            return None
        if action.status != "queued":
            return {
                "action_id": action.id,
                "status": action.status,
                "idempotent": True,
                "result": action.result_json,
            }
        canvas = db.get(VideoCanvas, action.canvas_id)
        if not canvas or canvas.owner_user_id != action.owner_user_id:
            action.status = "failed"
            action.result_json = {**(action.result_json or {}), "error": "画布不存在或无权访问"}
            db.commit()
            return {"action_id": action_id, "status": "failed"}
        if canvas.definition_revision != action.expected_definition_revision:
            action.status = "blocked"
            action.result_json = {**(action.result_json or {}), "error": "画布定义已变化，请重新提出阶段"}
            db.commit()
            return {"action_id": action_id, "status": "blocked"}
        action.status = "executing"
        db.commit()
        # The action is already scoped to an owner and the gateway only needs
        # the authenticated identity for ownership checks. Avoid requiring a
        # live HTTP session/token in this in-process path.
        owner = SimpleNamespace(id=action.owner_user_id)
        request = Request({"type": "http", "method": "POST", "path": "/internal/agent/canvas-stage", "headers": []})
        request.state.current_user = owner
        request.state.db = db
        request.state.trusted_agent_dispatch = True
        args = copy.deepcopy(action.arguments_json or {})
        parameters = dict(args.get("parameters") or {})
        parameters["agent_action_id"] = action.id
        parameters["expected_definition_revision"] = action.expected_definition_revision
        parameters["auto_approve_scenes"] = True  # 仅 auto 模式动作会走到这里（上方已按 permission_mode 过滤）
        from services.canvas_stage_gateway import execute_agent_canvas_stage
        result = await execute_agent_canvas_stage(
            canvas.id,
            str(args.get("stage") or action.stage),
            parameters,
            request,
            db,
        )
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            result = {"result": result}
        with SessionLocal() as write_db:
            saved = write_db.query(CanvasAgentAction).filter(CanvasAgentAction.id == action_id).with_for_update().first()
            if not saved:
                return None
            saved.result_json = {**(saved.result_json or {}), **result}
            if result.get("pending_task"):
                saved.status = "waiting"
            elif result.get("error") or result.get("ok") is False:
                saved.status = "failed"
            else:
                saved.status = "completed"
            write_db.commit()
        if result.get("pending_task"):
            return {"action_id": action_id, "status": "waiting", **result}
        if result.get("error") or result.get("ok") is False:
            return {"action_id": action_id, "status": "failed", **result}
        next_action = _persist_next_action(action_id, result)
        dispatched = None
        if isinstance(next_action, dict) and next_action.get("status") == "queued":
            # Synchronous stages must not leave auto mode parked in queued.
            # Continue within the same bounded stage chain; generation stages
            # return pending_task and stop here until the run callback resumes it.
            dispatched = await dispatch_queued_canvas_action(int(next_action["action_id"]))
        return {
            "action_id": action_id,
            "status": "completed",
            "next_action": next_action,
            "dispatched": dispatched,
            **result,
        }
    except Exception as exc:
        db.rollback()
        with SessionLocal() as fail_db:
            saved = fail_db.query(CanvasAgentAction).filter(CanvasAgentAction.id == action_id, CanvasAgentAction.status == "executing").with_for_update().first()
            if saved:
                saved.status = "failed"
                saved.result_json = {**(saved.result_json or {}), "error": str(exc)}
                fail_db.commit()
        return {"action_id": action_id, "status": "failed", "error": str(exc)}
    finally:
        db.close()


def consume_resume(context, run_id: int) -> dict[str, Any]:
    """只有已完成且未续接过的本会话后台任务才可自动唤起下一阶段。"""
    with SessionLocal() as db:
        _owned_canvas(db, context)
        key = context.pending_change_key
        actions = db.query(CanvasAgentAction).filter(
            CanvasAgentAction.canvas_id == context.workflow_id,
            CanvasAgentAction.conversation_id == key.conversation_id,
            CanvasAgentAction.owner_user_id == key.user_id,
            CanvasAgentAction.status.in_(["waiting", "completed"]),
        ).with_for_update().all()
        action = next((item for item in actions if ((item.result_json or {}).get("pending_task") or {}).get("run_id") == run_id), None)
        run = db.get(VideoCanvasRun, run_id)
        if not action or not run or run.canvas_id != context.workflow_id:
            raise HTTPException(409, "后台任务已续接或不属于当前会话")
        if action.status == "completed":
            continuation_id = (action.result_json or {}).get("continuation_id")
            if continuation_id:
                return {"run_id": run_id, "stage": action.stage, "status": run.status, "continuation_id": continuation_id, "idempotent": True}
            raise HTTPException(409, "后台任务已续接或不属于当前会话")
        if run.status != "succeeded":
            raise HTTPException(409, "后台任务尚未成功完成，不能自动进入下一阶段")
        if action.permission_mode != context.canvas_permission_mode:
            raise HTTPException(409, "权限模式已变化，请手动查看结果并决定后续阶段")
        action.status = "completed"
        action.result_json = {**(action.result_json or {}), "resumed": True}
        db.commit()
        return {"run_id": run_id, "stage": action.stage, "status": run.status}


async def execute_action(context, name: str, args: dict[str, Any], call):
    """计划/询问模式保存精确提案；自动模式或结构化审批才执行实际操作。"""
    with SessionLocal() as db:
        canvas = _owned_canvas(db, context)
        if args.get("canvas_id") != canvas.id:
            raise HTTPException(403, "工具画布 ID 与当前会话不一致")
        approved_id = context.canvas_executing_action_id
        if approved_id:
            action = _owned_action(db, context, approved_id)
            # claim 后按幂等键（stage/op 类型 + 目标节点）核对实际动作，而非全参数精确匹配。
            if action.status != "executing" or action.tool_name != name or _proposal_scope_key(action.arguments_json or {}) != _proposal_scope_key(args):
                raise HTTPException(409, "实际动作与已批准提案不一致")
        else:
            mode = context.canvas_permission_mode
            if mode not in {"plan", "ask", "auto"}:
                raise HTTPException(403, "画布权限模式无效")
            pending = db.query(CanvasAgentAction).filter(
                CanvasAgentAction.canvas_id == canvas.id,
                CanvasAgentAction.conversation_id == context.pending_change_key.conversation_id,
                CanvasAgentAction.status == "pending",
            ).all()
            # 幂等键从全参数 arguments_json 精确匹配放宽为 stage/op+目标节点：同阶段同目标复用，不因 summary 微差重复创建。
            duplicate = _already_applied_action(db, canvas, context.pending_change_key.conversation_id, name, args)
            if duplicate is not None:
                # 用户批准后已经执行过同一改动、画布之后也没变：直接告知模型，避免再弹一次确认卡片形成循环。
                return {
                    "ok": True,
                    "already_applied": True,
                    "action_id": duplicate.id,
                    "message": "相同的改动已在用户批准后执行完成，不要重复提交；请继续用户请求中尚未完成的其它步骤，或直接向用户汇报结果。",
                }
            scope = _proposal_scope_key(args)
            action = next((
                item for item in pending
                if item.tool_name == name
                and item.permission_mode == mode
                and item.expected_definition_revision == canvas.definition_revision
                and _proposal_scope_key(item.arguments_json or {}) == scope
            ), None)
            if action is not None and name == "apply_canvas_ops" and operation_digest_of(action.arguments_json) != operation_digest_of(args):
                # 同目标但操作内容已变（用户追加了新要求）：旧提案作废，按新内容重新提案，不能复用旧方案。
                action.status = "superseded"
                db.commit()
                action = None
            # 覆盖/删除已有节点内容必须先预览确认，自动模式也不例外。
            force_review = name == "apply_canvas_ops" and operations_overwrite_existing(args.get("operations"))
            if action is None:
                preview = None
                if name == "apply_canvas_ops":
                    from routers.video_canvas import _latest_version
                    snapshot = context.canvas_graph_snapshot
                    if isinstance(snapshot, dict) and isinstance(snapshot.get("nodes"), list) and not context.canvas_snapshot_consumed:
                        base_graph = snapshot
                    else:
                        base_graph = _latest_version(canvas.id, db).graph_json or {"nodes": [], "edges": []}
                    preview = build_ops_preview(base_graph, args.get("operations") or [])
                    if preview.get("errors"):
                        return {"error": "；".join(preview["errors"]), "preview_errors": preview["errors"]}
                    if not preview.get("nodes") and not preview.get("edges"):
                        # 改动已经在画布上（通常是批准执行后又提交了一遍）：没有可确认的变化，不再弹卡片。
                        return {"ok": True, "no_change": True, "message": "这些改动已经在画布上，无需重复提交；请继续其它未完成的步骤，或向用户汇报结果。"}
                action = CanvasAgentAction(
                    canvas_id=canvas.id, owner_user_id=canvas.owner_user_id,
                    conversation_id=context.pending_change_key.conversation_id,
                    permission_mode=mode, stage=str(args.get("stage") or "node_edit"), tool_name=name,
                    summary=str(args.get("summary") or f"执行{args.get('stage') or '画布节点编辑'}阶段"),
                    arguments_json=copy.deepcopy(args), expected_definition_revision=canvas.definition_revision,
                    status="executing" if (mode == "auto" and not force_review) else "pending",
                    result_json={"preview": preview} if preview else None,
                )
                db.add(action)
                db.commit()
            if mode != "auto" or force_review:
                return {"awaiting_approval": True, "approval": serialize_action(action), "message": "阶段方案已保存，等待用户审阅；实际操作尚未执行。"}
        action_id = action.id
        expected_revision = action.expected_definition_revision
        if expected_revision != canvas.definition_revision:
            raise HTTPException(409, "画布已变化，执行前必须重新审阅阶段提案")
    context.canvas_executing_action_id = action_id
    context.canvas_expected_definition_revision = expected_revision
    try:
        result = await call()
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            result = {"result": result}
        with SessionLocal() as db:
            action = _owned_action(db, context, action_id)
            action.result_json = result
            action.status = "failed" if result.get("error") or result.get("ok") is False else "waiting" if result.get("pending_task") else "completed"
            mode = action.permission_mode
            db.commit()
        # In auto mode, synchronous stages must immediately consume their
        # durable next action. Generation stages return pending_task and stop;
        # their VideoCanvasRun callback will create/dispatch the next action.
        if mode == "auto" and not result.get("pending_task") and not result.get("error") and result.get("ok") is not False \
                and str(result.get("next_stage") or "") in PIPELINE_HANDOFF_STAGES:
            # 剩余的编排阶段交给服务端后台运行器：不受对话轮次与预算限制，失败自动重试，
            # 助手只需告诉用户进度在画布底部查看。
            from services.canvas_pipeline_runner import start_canvas_pipeline

            with SessionLocal() as db:
                canvas = db.get(VideoCanvas, context.workflow_id)
                started = await start_canvas_pipeline(db, canvas, canvas.owner_user_id) if canvas else None
                saved = db.query(CanvasAgentAction).filter(CanvasAgentAction.id == action_id).first()
                if saved and started:
                    saved.result_json = {**(saved.result_json or {}), "pipeline_task_id": started["task_id"]}
                    db.commit()
            if started:
                result["pipeline"] = {
                    "task_id": started["task_id"],
                    "message": "剩余的拆分、导演编排、资产分析、分镜编排已在后台自动进行，进度显示在画布底部；本轮对话到此结束，不要再逐阶段调用 canvas_stage。",
                }
            return result
        if mode == "auto" and not result.get("pending_task") and not result.get("error") and result.get("ok") is not False:
            next_action = _persist_next_action(action_id, result)
            if isinstance(next_action, dict) and next_action.get("status") == "queued":
                result["next_action"] = await dispatch_queued_canvas_action(int(next_action["action_id"]))
            elif next_action is not None:
                result["next_action"] = next_action
        return result
    except BaseException as exc:
        with SessionLocal() as db:
            action = _owned_action(db, context, action_id)
            action.status = "interrupted"
            action.result_json = {"error": "阶段执行中断，请查询画布与运行状态；不会自动重放未知结果的操作。"}
            db.commit()
        raise
    finally:
        context.canvas_executing_action_id = None
