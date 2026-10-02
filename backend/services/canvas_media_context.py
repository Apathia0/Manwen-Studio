"""为画布对话定向附带当前生成产物，供模型观察和审查。"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import tempfile
from typing import Any

from models import VideoAsset, VideoCanvas, VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}


def _local_media_path(value: str) -> Path | None:
    """仅解析项目自己的媒体目录，绝不按模型给出的 URL 下载文件。"""
    base = Path(__file__).resolve().parent.parent
    roots = [base / "manga_outputs", base / "video_outputs"]
    raw = value.replace("\\", "/")
    if raw.startswith("/static/manga/"):
        candidates = [roots[0] / raw[len("/static/manga/"):]]
    elif raw.startswith("/static/video/"):
        candidates = [roots[1] / raw[len("/static/video/"):]]
    elif raw.startswith(("manga_outputs/", "video_outputs/")):
        candidates = [base / raw]
    elif Path(value).is_absolute():
        candidates = [Path(value)]
    else:
        candidates = [root / value for root in roots]
    for path in candidates:
        resolved = path.resolve()
        if any(resolved.is_relative_to(root.resolve()) for root in roots) and resolved.is_file():
            return resolved
    return None


def _latest_graph(db, canvas: VideoCanvas) -> dict[str, Any]:
    version = (
        db.query(VideoCanvasVersion)
        .filter(VideoCanvasVersion.canvas_id == canvas.id)
        .order_by(VideoCanvasVersion.version_no.desc())
        .first()
    )
    return version.graph_json if version and isinstance(version.graph_json, dict) else {"nodes": [], "edges": []}


def _node_definition_hash(graph: dict[str, Any], node_id: str) -> str:
    """延迟导入画布阶段网关，避免服务模块顶层循环依赖。"""
    try:
        from services.canvas_stage_gateway import _definition_hash

        return _definition_hash(graph, node_id)
    except Exception:
        node = next((item for item in graph.get("nodes", []) if str(item.get("id")) == node_id), None)
        payload = {"node_id": node_id, "node": node or {}}
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def _public_output(output: dict[str, Any]) -> dict[str, Any]:
    return {
        key: output.get(key)
        for key in ("asset_id", "url", "file_path", "duration_seconds", "clip_count", "has_audio")
        if key in output
    }


def _configured_asset_id(graph: dict[str, Any], node_id: str) -> int | None:
    node = next((item for item in graph.get("nodes", []) if str(item.get("id")) == node_id), None)
    config = (node.get("data") or {}).get("config") if isinstance(node, dict) else None
    asset_id = config.get("asset_id") if isinstance(config, dict) else None
    return asset_id if isinstance(asset_id, int) else None


def _asset_for_output(db, canvas: VideoCanvas, output: dict[str, Any]) -> VideoAsset | None:
    asset_id = output.get("asset_id")
    if not isinstance(asset_id, int):
        return None
    asset = db.get(VideoAsset, asset_id)
    if not asset or asset.story_id != canvas.story_id or asset.status != "active" or not asset.file_path:
        return None
    return asset


def _media_label(*, node_id: str, run_id: int | None, version_id: int | None, asset_id: int | None) -> str:
    parts = [f"node={node_id}"]
    if run_id is not None:
        parts.append(f"run={run_id}")
    if version_id is not None:
        parts.append(f"version={version_id}")
    if asset_id is not None:
        parts.append(f"asset={asset_id}")
    return "画布媒体观察[" + " ".join(parts) + "]"


def _latest_attempts_by_node(db, canvas_id: int, node_ids: list[str]) -> dict[str, tuple[VideoCanvasRun, VideoCanvasRunNode]]:
    runs = (
        db.query(VideoCanvasRun)
        .filter(VideoCanvasRun.canvas_id == canvas_id)
        .order_by(VideoCanvasRun.id.desc())
        .limit(30)
        .all()
    )
    result: dict[str, tuple[VideoCanvasRun, VideoCanvasRunNode]] = {}
    wanted = set(node_ids)
    for run in runs:
        rows = (
            db.query(VideoCanvasRunNode)
            .filter(VideoCanvasRunNode.run_id == run.id, VideoCanvasRunNode.node_id.in_(wanted))
            .order_by(VideoCanvasRunNode.attempt.desc(), VideoCanvasRunNode.id.desc())
            .all()
        )
        for row in rows:
            if row.node_id not in result:
                result[row.node_id] = (run, row)
        if set(result) >= wanted:
            break
    return result


async def inspect_media(
    db,
    canvas_id: int,
    node_ids: list[str],
    expected_revision: int | None,
) -> dict[str, Any]:
    """定向读取画布媒体节点的当前产物，并返回模型可观察附件与审查回执。"""
    canvas = db.get(VideoCanvas, canvas_id)
    if not canvas:
        return {"ok": False, "error": "画布不存在", "attachments": [], "temporary_paths": [], "receipts": []}
    normalized_ids = [str(item).strip() for item in node_ids if str(item).strip()]
    normalized_ids = list(dict.fromkeys(normalized_ids))
    if not normalized_ids:
        return {"ok": False, "error": "node_ids 不能为空", "attachments": [], "temporary_paths": [], "receipts": []}
    current_graph = _latest_graph(db, canvas)
    current_hashes = {node_id: _node_definition_hash(current_graph, node_id) for node_id in normalized_ids}
    revision_matches = expected_revision is None or int(expected_revision) == int(canvas.definition_revision or 0)
    if not revision_matches:
        return {
            "ok": False,
            "error": "画布定义已更新，请重新调用 get_canvas_graph 获取最新 definition_revision 后重试",
            "conflict": True,
            "canvas_id": canvas_id,
            "definition_revision": canvas.definition_revision,
            "expected_definition_revision": expected_revision,
            "nodes": [],
            "receipts": [],
            "attachments": [],
            "temporary_paths": [],
            "summary": "画布定义版本不一致，未附带任何媒体。",
        }
    latest = _latest_attempts_by_node(db, canvas_id, normalized_ids)

    attachments: list[dict[str, Any]] = []
    temporary_paths: list[str] = []
    receipts: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    from services.agent_media import _extract_video_frames, _probe_video

    for node_id in normalized_ids:
        pair = latest.get(node_id)
        if not pair:
            nodes.append({
                "node_id": node_id,
                "current": False,
                "state": "missing",
                "reason": "未找到该节点的生成尝试",
                "definition_hash": current_hashes.get(node_id),
            })
            continue
        run, run_node = pair
        run_version = db.get(VideoCanvasVersion, run.canvas_version_id)
        run_graph = run_version.graph_json if run_version and isinstance(run_version.graph_json, dict) else {"nodes": [], "edges": []}
        run_hash = _node_definition_hash(run_graph, node_id)
        hash_matches = run_hash == current_hashes.get(node_id)
        output = run_node.output_snapshot_json if isinstance(run_node.output_snapshot_json, dict) else {}
        asset = _asset_for_output(db, canvas, output)
        output_asset_id = output.get("asset_id") if isinstance(output.get("asset_id"), int) else None
        configured_asset_id = _configured_asset_id(current_graph, node_id)
        raw_path_value = "" if output_asset_id is not None and asset is None else output.get("url") or output.get("file_path") or ""
        path = _local_media_path(str(asset.file_path if asset else raw_path_value))
        asset_id = asset.id if asset else output.get("asset_id") if isinstance(output.get("asset_id"), int) else None
        label = _media_label(node_id=node_id, run_id=run.id, version_id=run.canvas_version_id, asset_id=asset_id)
        receipt = {
            "receipt_id": hashlib.sha256(f"{canvas_id}:{node_id}:{run_node.id}:{run_hash}:{asset_id}".encode("utf-8")).hexdigest()[:24],
            "canvas_id": canvas_id,
            "node_id": node_id,
            "run_id": run.id,
            "run_node_id": run_node.id,
            "canvas_version_id": run.canvas_version_id,
            "asset_id": asset_id,
            "definition_hash": run_hash,
            "expected_definition_hash": current_hashes.get(node_id),
            "definition_revision": canvas.definition_revision,
            "expected_definition_revision": expected_revision,
            "current": False,
            "delivered": False,
            "media_kind": None,
            "label": label,
        }
        node_result = {
            "node_id": node_id,
            "run_id": run.id,
            "run_node_id": run_node.id,
            "canvas_version_id": run.canvas_version_id,
            "asset_id": asset_id,
            "status": run_node.status,
            "current": False,
            "state": "stale",
            "definition_hash": run_hash,
            "expected_definition_hash": current_hashes.get(node_id),
            "output": _public_output(output),
        }
        if run_node.status != "succeeded":
            node_result["reason"] = run_node.error_message or f"最新尝试状态为 {run_node.status}"
        elif not hash_matches:
            node_result["reason"] = "节点定义或画布版本已变化，旧产物不能冒充当前图"
        elif output_asset_id is not None and asset is None:
            node_result["reason"] = "最新产物资产不存在、不属于当前画布或已失效"
        elif configured_asset_id is not None and configured_asset_id != asset_id:
            node_result["reason"] = "节点当前绑定资产与最新输出不一致，不能作为当前图"
        elif not path:
            node_result["reason"] = "最新产物缺少可读取的本地媒体文件"
        else:
            suffix = path.suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                attachments.append({"filename": label, "media_kind": "image", "content_type": "image/*", "path": str(path)})
                receipt.update({"current": True, "media_kind": "image", "path": str(path)})
                node_result.update({"current": True, "state": "current", "media_kind": "image", "receipt_id": receipt["receipt_id"], "label": label})
            elif suffix in VIDEO_SUFFIXES:
                try:
                    info = await asyncio.to_thread(_probe_video, path)
                    directory = tempfile.mkdtemp(prefix="canvas-review-")
                    temporary_paths.append(directory)
                    frames = await asyncio.to_thread(_extract_video_frames, path, Path(directory), info["duration"])
                    for index, frame in enumerate(frames, start=1):
                        attachments.append({"filename": f"{label} frame={index}/{len(frames)}", "media_kind": "image", "content_type": "image/jpeg", "path": frame})
                    receipt.update({"current": True, "media_kind": "video_frames", "path": str(path), "frame_paths": frames})
                    node_result.update({"current": True, "state": "current", "media_kind": "video_frames", "receipt_id": receipt["receipt_id"], "label": label, "duration_seconds": info.get("duration")})
                    node_result["observation_limit"] = "关键帧不能证明对白、声线、音频节奏或完整动作连续性。"
                except Exception as exc:
                    node_result.update({"state": "unreadable", "reason": f"无法提取视频关键帧：{exc}"})
            else:
                node_result.update({"state": "unsupported", "reason": "该产物不是可观察的图片或视频"})
        if receipt["current"]:
            receipts.append(receipt)
        nodes.append(node_result)

    summary_lines = []
    for item in nodes:
        if item.get("current"):
            line = f"{item['node_id']}：已附 {item.get('media_kind')}，请只依据实际画面观察。"
            if item.get("observation_limit"):
                line += str(item["observation_limit"])
            summary_lines.append(line)
        else:
            summary_lines.append(f"{item['node_id']}：{item.get('state')}，{item.get('reason') or '不能作为当前画面'}。")
    return {
        "ok": True,
        "canvas_id": canvas_id,
        "definition_revision": canvas.definition_revision,
        "expected_definition_revision": expected_revision,
        "revision_matches": revision_matches,
        "nodes": nodes,
        "receipts": receipts,
        "attachments": attachments,
        "temporary_paths": temporary_paths,
        "summary": "\n".join(summary_lines),
    }


async def build_canvas_media_context(db, canvas_id: int) -> dict:
    """兼容旧调用方：自动挑选当前图像/视频节点，附带少量最新产物。"""
    canvas = db.get(VideoCanvas, canvas_id)
    if not canvas:
        return {"attachments": [], "temporary_paths": [], "summary": "画布不存在"}
    graph = _latest_graph(db, canvas)
    node_ids = [
        str(node.get("id"))
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("type") in {"image", "video", "image_generation", "storyboard", "video_generation"}
    ][:6]
    if node_ids:
        result = await inspect_media(db, canvas_id, node_ids, canvas.definition_revision)
        return {
            "attachments": result["attachments"],
            "temporary_paths": result["temporary_paths"],
            "summary": result["summary"],
        }
    return {"attachments": [], "temporary_paths": [], "summary": "未找到可观察的画布媒体节点"}
