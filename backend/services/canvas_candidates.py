"""画布节点的历史生成结果（候选）：来自各次成功运行的节点输出，用户可挑选其一固定为当前结果。"""

from __future__ import annotations

from typing import Any

from models import VideoAsset, VideoCanvasRun, VideoCanvasRunNode

MAX_CANDIDATES = 20


def list_node_candidates(db, *, canvas, node_id: str, current_asset_id: int | None) -> list[dict[str, Any]]:
    """按时间倒序返回该节点成功生成过的不同素材；素材必须仍存在且属于本作品。"""
    rows = (
        db.query(VideoCanvasRunNode, VideoCanvasRun)
        .join(VideoCanvasRun, VideoCanvasRun.id == VideoCanvasRunNode.run_id)
        .filter(
            VideoCanvasRun.canvas_id == canvas.id,
            VideoCanvasRunNode.node_id == node_id,
            VideoCanvasRunNode.status == "succeeded",
        )
        .order_by(VideoCanvasRunNode.id.desc())
        .limit(MAX_CANDIDATES * 3)
        .all()
    )
    seen: set[int] = set()
    candidates: list[dict[str, Any]] = []
    for run_node, run in rows:
        output = run_node.output_snapshot_json if isinstance(run_node.output_snapshot_json, dict) else {}
        asset_id = output.get("asset_id")
        url = output.get("url")
        if not isinstance(asset_id, int) or isinstance(asset_id, bool) or not url or asset_id in seen:
            continue
        asset = db.get(VideoAsset, asset_id)
        if not asset or asset.story_id != canvas.story_id:
            continue
        seen.add(asset_id)
        candidates.append({
            "asset_id": asset_id,
            "url": str(url),
            "run_id": run.id,
            "created_at": (run_node.completed_at or run.created_at).isoformat() if (run_node.completed_at or run.created_at) else None,
            "duration_seconds": output.get("duration_seconds"),
        })
        if len(candidates) >= MAX_CANDIDATES:
            break
    # 未固定时最新一次即为当前结果。
    active = current_asset_id if current_asset_id in seen else (candidates[0]["asset_id"] if candidates else None)
    for item in candidates:
        item["is_current"] = item["asset_id"] == active
    return candidates
