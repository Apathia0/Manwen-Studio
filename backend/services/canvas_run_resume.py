"""服务启动时自动恢复被重启打断的画布生成运行。

任务管理器在启动时会把“进行中”的后台任务统一标记为中断并结算积分（因为执行它们的进程已经不在了）。
画布运行的上游视频任务 ID 在提交时就已持久化，所以这里在标记中断之后，对这些运行走与用户点击
“恢复执行”完全相同的流程：保留已完成节点，已提交的视频只查询原上游任务，不会重复提交、重复收费。

只恢复：重启前仍在排队 / 运行、且创建不超过 24 小时的运行；用户已请求取消的不恢复。
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request

from database import SessionLocal
from models import User, VideoCanvas, VideoCanvasRun

logger = logging.getLogger(__name__)

RESUMABLE_STATUSES = ("queued", "running")
MAX_RESUME_AGE = datetime.timedelta(hours=24)


def collect_resumable_runs(db) -> list[dict[str, int]]:
    """必须在任务管理器标记中断之前调用：此时运行状态仍是 queued / running。"""
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - MAX_RESUME_AGE
    rows = (
        db.query(VideoCanvasRun, VideoCanvas)
        .join(VideoCanvas, VideoCanvas.id == VideoCanvasRun.canvas_id)
        .filter(VideoCanvasRun.status.in_(RESUMABLE_STATUSES))
        .order_by(VideoCanvasRun.id.asc())
        .all()
    )
    refs: list[dict[str, int]] = []
    for run, canvas in rows:
        created = run.created_at.replace(tzinfo=None) if run.created_at else None
        if created is not None and created < cutoff:
            continue
        refs.append({"canvas_id": canvas.id, "run_id": run.id, "owner_user_id": canvas.owner_user_id})
    return refs


async def _resume_one(ref: dict[str, int]) -> bool:
    from routers import video_canvas as api
    from schemas import VideoCanvasRunConfirmRequest

    db = SessionLocal()
    try:
        owner = db.get(User, ref["owner_user_id"])
        run = db.get(VideoCanvasRun, ref["run_id"])
        if owner is None or run is None:
            return False
        # 中断标记已把它置为 failed；不是这个状态说明已被处理（或用户已取消），不再动它
        if run.status != "failed":
            return False
        request = Request({"type": "http", "method": "POST", "path": "/internal/canvas-run-resume", "headers": []})
        request.state.current_user = owner if hasattr(owner, "id") else SimpleNamespace(id=ref["owner_user_id"])
        request.state.db = db
        request.state.trusted_agent_dispatch = True
        await api.confirm_video_canvas_run(ref["canvas_id"], ref["run_id"], VideoCanvasRunConfirmRequest(confirmed=True), request, db)
        return True
    except Exception:  # noqa: BLE001 - 单个运行恢复失败不影响其他运行，用户仍可手动点「恢复执行」
        logger.warning("自动恢复画布运行失败 canvas=%s run=%s", ref.get("canvas_id"), ref.get("run_id"), exc_info=True)
        return False
    finally:
        db.close()


async def resume_interrupted_canvas_runs(refs: list[dict[str, int]], *, delay_seconds: float = 3.0) -> int:
    """等应用就绪后逐个恢复；返回成功恢复的数量。"""
    if not refs:
        return 0
    await asyncio.sleep(delay_seconds)
    resumed = 0
    for ref in refs:
        if await _resume_one(ref):
            resumed += 1
            logger.info("已自动恢复画布运行 canvas=%s run=%s", ref["canvas_id"], ref["run_id"])
    return resumed
