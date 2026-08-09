"""视频无限画布的运行时执行器。"""

from __future__ import annotations

import asyncio
import datetime
import re
from pathlib import Path
from typing import Any

from database import SessionLocal
from models import VideoAsset, VideoCanvas, VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion
from services import image2 as image2_service
from services.ai.resolver import begin_ai_call, complete_ai_call
from services.task_manager import task_manager
from services.video_compiler import compile_project
from services.video_generation import fetch_job_result, query_job_status, submit_video_job


BACKEND_DIR = Path(__file__).resolve().parent.parent
MANGA_OUTPUTS = BACKEND_DIR / "manga_outputs"
VIDEO_OUTPUTS = BACKEND_DIR / "video_outputs"
GENERATION_TYPES = {"image", "video", "image_generation", "storyboard", "video_generation", "concat"}
IMAGE_ASSET_TYPES = {"storyboard_frame", "character_reference", "scene_reference", "prop_reference", "style_reference", "image"}
VIDEO_ASSET_TYPES = {"video_clip", "video", "compiled_video", "final_video"}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _relative_path(path: str, root: Path) -> str:
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _static_url(path: str, root: Path, prefix: str) -> str:
    if path.startswith(("http://", "https://", "/static/")):
        return path
    relative = _relative_path(path, root)
    return f"{prefix}/{relative}" if not relative.startswith(("http://", "https://")) else relative


def _node_output_path(root: Path, canvas_id: int, run_id: int, node_id: str, suffix: str) -> Path:
    """构造限定在用户媒体目录内的节点输出路径。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
        raise RuntimeError("节点 id 不合法")
    output = (root / f"canvas_{canvas_id}" / f"run_{run_id}" / f"{node_id}{suffix}").resolve()
    if not output.is_relative_to(root.resolve()):
        raise RuntimeError("节点输出路径不合法")
    return output


def _canvas_video_path(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("http://", "https://", "/static/")):
        return None
    candidate = Path(raw) if Path(raw).is_absolute() else VIDEO_OUTPUTS / raw
    try:
        resolved = candidate.resolve()
        return str(resolved) if resolved.is_file() and resolved.is_relative_to(VIDEO_OUTPUTS.resolve()) else None
    except OSError:
        return None


def _node_inputs(graph: dict[str, Any], node_id: str, outputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for edge in graph.get("edges") or []:
        if isinstance(edge, dict) and edge.get("target") == node_id and not (isinstance(edge.get("data"), dict) and edge["data"].get("disabled")):
            value = outputs.get(str(edge.get("source") or ""))
            if value:
                values.append(value)
    return values


def _asset_media_kind(asset: VideoAsset) -> str | None:
    """根据资产类型和受控文件扩展名判定其可连接的媒体端口。"""
    asset_type = str(asset.asset_type or "").lower()
    suffix = Path(str(asset.file_path or "")).suffix.lower()
    if asset_type in VIDEO_ASSET_TYPES or suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    if asset_type in IMAGE_ASSET_TYPES or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    return None


def _require_canvas_asset(db, canvas: VideoCanvas, asset_id: int, media_kind: str) -> VideoAsset:
    """校验资产归属、活动状态和端口媒体类型。"""
    asset = db.get(VideoAsset, asset_id)
    if not asset or asset.story_id != canvas.story_id or asset.status != "active" or not asset.file_path:
        raise RuntimeError("资产不存在或不属于当前作品")
    if _asset_media_kind(asset) != media_kind:
        raise RuntimeError(f"资产不是可用于{media_kind}端口的有效媒体")
    return asset


def _configured_reference_inputs(config: dict[str, Any], canvas: VideoCanvas, db) -> list[dict[str, Any]]:
    """将节点编辑器显式选择的资产转换为受作品归属约束的运行输入。"""
    raw_ids = config.get("reference_asset_ids") or []
    if not isinstance(raw_ids, list):
        return []
    inputs: list[dict[str, Any]] = []
    for raw_id in raw_ids:
        if not isinstance(raw_id, int):
            continue
        asset = _require_canvas_asset(db, canvas, raw_id, "image")
        inputs.append({"asset_id": asset.id, "file_path": asset.file_path, "url": asset.file_path})
    return inputs


def _apply_style_prompt(prompt: str, config: dict[str, Any], inputs: list[dict[str, Any]]) -> str:
    """使用保存时冻结的风格快照，保证同一画布版本可重复执行。"""
    snapshots: list[dict[str, Any]] = []
    own_snapshot = config.get("style_snapshot")
    if isinstance(own_snapshot, dict):
        snapshots.append(own_snapshot)
    for item in inputs:
        snapshot = item.get("style_snapshot")
        if isinstance(snapshot, dict):
            snapshots.append(snapshot)
    style_fragments = [
        str(snapshot.get("prompt_template") or "").strip()
        for snapshot in snapshots
        if str(snapshot.get("prompt_template") or "").strip()
    ]
    if not style_fragments:
        return prompt
    return f"{prompt}\n\n风格要求：{'；'.join(dict.fromkeys(style_fragments))}"


def _first_input_text(inputs: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    """从剧本、镜头或文本节点的白名单字段中提取首个可用提示词。"""
    for item in inputs:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested_shot = item.get("shot")
        if isinstance(nested_shot, dict):
            for key in keys:
                value = nested_shot.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _reference_urls(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    urls: list[str] = []
    for value in inputs:
        asset_id = value.get("asset_id")
        if isinstance(asset_id, int):
            asset = db.get(VideoAsset, asset_id)
            if asset and asset.story_id == canvas.story_id and asset.status == "active" and _asset_media_kind(asset) == "image":
                urls.append(asset.file_path)
        reused_url = str(value.get("_media_url") or "").strip()
        if reused_url:
            urls.append(reused_url)
    return list(dict.fromkeys(urls))


def _local_reference_paths(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    """只把当前作品中可安全访问的本地图片传给 Image2。"""
    paths: list[str] = []
    for value in inputs:
        asset_id = value.get("asset_id")
        asset = db.get(VideoAsset, asset_id) if isinstance(asset_id, int) else None
        if not asset or asset.story_id != canvas.story_id or asset.status != "active" or _asset_media_kind(asset) != "image":
            continue
        raw_path = Path(asset.file_path)
        candidate = raw_path if raw_path.is_absolute() else MANGA_OUTPUTS / raw_path
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(MANGA_OUTPUTS.resolve()):
                paths.append(str(resolved))
        except OSError:
            continue
    return list(dict.fromkeys(paths))


def _mark_remaining_nodes(db, run: VideoCanvasRun, *, status: str, reason: str | None = None) -> None:
    """为终止运行补齐未执行节点的终态，避免前端永久等待。"""
    now = _now()
    pending_nodes = db.query(VideoCanvasRunNode).filter(
        VideoCanvasRunNode.run_id == run.id,
        VideoCanvasRunNode.status.in_(["queued", "awaiting_approval"]),
    ).all()
    for pending_node in pending_nodes:
        pending_node.status = status
        pending_node.error_message = reason
        pending_node.completed_at = now


def _run_cancelled_in_database(db, run: VideoCanvasRun) -> bool:
    """读取持久化取消状态，兼容多进程任务执行与 API 服务。"""
    db.refresh(run)
    return run.status in {"cancel_requested", "cancelled"}


def _finish_cancelled_run(db, run: VideoCanvasRun) -> dict[str, Any]:
    """将运行和未开始节点统一结束为已取消。"""
    run.status = "cancelled"
    run.completed_at = _now()
    _mark_remaining_nodes(db, run, status="cancelled")
    db.commit()
    return {"run_id": run.id, "status": "cancelled"}


async def execute_canvas_run(
    run_id: int,
    *,
    image_api_key: str | None,
    video_api_key: str | None,
    video_base_url: str,
    video_model: str,
    task_id: str | None = None,
    **_task_context: Any,
) -> dict[str, Any]:
    """按冻结版本顺序执行画布；外部生成只在确认后的后台任务中发生。"""
    db = SessionLocal()
    try:
        run = db.get(VideoCanvasRun, run_id)
        if not run:
            raise RuntimeError("画布运行不存在")
        canvas = db.get(VideoCanvas, run.canvas_id)
        version = db.get(VideoCanvasVersion, run.canvas_version_id)
        if not canvas or not version:
            raise RuntimeError("画布运行快照不存在")
        graph = version.graph_json or {}
        node_map = {str(node.get("id")): node for node in graph.get("nodes") or [] if isinstance(node, dict)}
        run_nodes = {item.node_id: item for item in db.query(VideoCanvasRunNode).filter(VideoCanvasRunNode.run_id == run.id).all()}
        order = list((run.plan_json or {}).get("topological_order") or [])
        outputs: dict[str, dict[str, Any]] = {}
        if _run_cancelled_in_database(db, run):
            return _finish_cancelled_run(db, run)
        run.status = "running"
        db.commit()

        for node_id in order:
            if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                return _finish_cancelled_run(db, run)
            node = node_map.get(node_id)
            run_node = run_nodes.get(node_id)
            if not node or not run_node:
                continue
            config = dict((node.get("data") or {}).get("config") or {})
            inputs = [
                *_node_inputs(graph, node_id, outputs),
                *_configured_reference_inputs(config, canvas, db),
            ]
            run_node.status = "running"
            run_node.started_at = _now()
            run_node.input_snapshot_json = {"config": config, "inputs": inputs}
            db.commit()
            billing_ctx = None
            try:
                node_type = str(node.get("type") or "")
                is_reused = node_type in {"image", "video", "image_generation", "storyboard", "video_generation"} and bool(str(config.get("existing_url") or "").strip())
                if node_type in {"image", "video", "image_generation", "storyboard", "video_generation"} and not is_reused:
                    modality = "video" if node_type in {"video", "video_generation"} else "image"
                    estimate = (
                        {"video_seconds": int(config.get("duration_seconds") or 15)}
                        if modality == "video"
                        else {"image_count": 1}
                    )
                    billing_ctx = begin_ai_call(
                        db,
                        user_id=canvas.owner_user_id,
                        modality=modality,
                        task_type=f"video_canvas.{node_type}",
                        model_id=config.get("model_id") if isinstance(config.get("model_id"), int) else None,
                        request_id=f"canvas:{run.id}:node:{run_node.id}:a:{run_node.attempt}",
                        story_id=canvas.story_id,
                        chapter_id=canvas.default_chapter_id,
                        estimate_kwargs=estimate,
                    )
                    run_node.input_snapshot_json = {
                        **(run_node.input_snapshot_json or {}),
                        "billing_usage_event_id": billing_ctx.usage_event_id,
                    }
                    run_node.billing_usage_event_id = billing_ctx.usage_event_id
                    db.commit()
                if node_type not in GENERATION_TYPES:
                    if node_type == "text":
                        text_value = str(config.get("content") or config.get("text") or config.get("story_summary") or "")
                        output = {"text": text_value, "content": text_value}
                        output.update({
                            key: value for key, value in config.items()
                            if key not in {"file_path", "existing_url", "asset_id", "reference_asset_ids"}
                        })
                    elif node_type in {"asset", "video_asset"} and isinstance(config.get("asset_id"), int):
                        expected_kind = "video" if node_type == "video_asset" else "image"
                        asset = _require_canvas_asset(db, canvas, config["asset_id"], expected_kind)
                        output = {"asset_id": asset.id, "file_path": asset.file_path, "url": asset.file_path}
                    elif node_type in {"asset", "video_asset"}:
                        raise RuntimeError("资产节点必须选择有效资产")
                    elif node_type == "style":
                        snapshot = config.get("style_snapshot")
                        output = {"style_snapshot": snapshot} if isinstance(snapshot, dict) else {}
                    else:
                        # 剧本和镜头节点只透传文本/提示词字段，拒绝媒体路径等未验证配置。
                        output = {
                            key: value
                            for key, value in config.items()
                            if key not in {"url", "file_path", "asset_id", "reference_asset_ids"}
                        }
                        if node_type == "screenplay":
                            output["screenplay"] = str(config.get("content") or config.get("screenplay") or "")
                        if node_type == "shot":
                            output["shot"] = dict(output)
                elif node_type in {"image", "image_generation", "storyboard"}:
                    existing_url = str(config.get("existing_url") or "").strip()
                    if existing_url:
                        output = {"url": existing_url, "file_path": existing_url, "_media_url": existing_url, "reused": True}
                    elif isinstance(config.get("asset_id"), int):
                        asset = _require_canvas_asset(db, canvas, config["asset_id"], "image")
                        output = {"asset_id": asset.id, "file_path": asset.file_path, "url": _static_url(asset.file_path, MANGA_OUTPUTS, "/static/manga"), "reused": True}
                    else:
                        prompt = str(config.get("prompt") or config.get("storyboard_prompt") or "").strip()
                        if not prompt:
                            prompt = _first_input_text(inputs, ("text", "content", "storyboard_prompt", "screenplay", "prompt", "shot"))
                        prompt = _apply_style_prompt(prompt, config, inputs)
                        if not prompt or not image_api_key:
                            raise RuntimeError("图像节点缺少提示词或 Image API Key")
                        output_path = _node_output_path(MANGA_OUTPUTS, canvas.id, run.id, node_id, ".png")
                        saved_path = await image2_service.generate_reference_image(
                            prompt=prompt,
                            output_path=output_path,
                            api_key=image_api_key,
                            size=str(config.get("size") or "1920x1080"),
                            ref_image_paths=_local_reference_paths(inputs, canvas, db) or None,
                            ref_type="storyboard" if node_type in {"image", "storyboard"} else "character",
                        )
                        stored_path = _relative_path(str(saved_path), MANGA_OUTPUTS)
                        asset = VideoAsset(story_id=canvas.story_id, chapter_id=canvas.default_chapter_id, asset_type="storyboard_frame", name=f"画布 {canvas.name} - {node_id}", file_path=stored_path, provider="image2", prompt=prompt, meta_json={"canvas_id": canvas.id, "run_id": run.id, "node_id": node_id}, usage_scope="story_shared")
                        db.add(asset)
                        db.flush()
                        output = {"asset_id": asset.id, "file_path": stored_path, "url": _static_url(stored_path, MANGA_OUTPUTS, "/static/manga")}
                elif node_type in {"video", "video_generation"}:
                    existing_url = str(config.get("existing_url") or "").strip()
                    if existing_url:
                        output = {"url": existing_url, "file_path": existing_url, "_media_url": existing_url, "reused": True}
                    else:
                        prompt = str(config.get("prompt") or "").strip() or _first_input_text(inputs, ("video_prompt", "text", "content", "storyboard_prompt", "prompt", "screenplay"))
                        prompt = _apply_style_prompt(prompt, config, inputs)
                        if not prompt or not video_api_key:
                            raise RuntimeError("视频节点缺少提示词或 Video API Key")
                        submission = await submit_video_job(shot_id=run_node.id, provider="canvas", model=str(config.get("model") or video_model), prompt=prompt, negative_prompt=str(config.get("negative_prompt") or ""), duration_seconds=int(config.get("duration_seconds") or 15), aspect_ratio=str(config.get("aspect_ratio") or "16:9"), reference_images=_reference_urls(inputs, canvas, db), api_key=video_api_key, base_url=video_base_url)
                        provider_job_id = submission["provider_job_id"]
                        for _ in range(120):
                            if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                                raise asyncio.CancelledError()
                            status = await query_job_status("canvas", provider_job_id, api_key=video_api_key, base_url=video_base_url, model=str(config.get("model") or video_model))
                            if status["status"] == "succeeded":
                                break
                            if status["status"] in {"failed", "cancelled"}:
                                raise RuntimeError(str(status.get("error") or "视频生成失败"))
                            await asyncio.sleep(5)
                        else:
                            raise RuntimeError("视频生成超时")
                        result = await fetch_job_result("canvas", provider_job_id, run_node.id, api_key=video_api_key, base_url=video_base_url, model=str(config.get("model") or video_model))
                        video_path = str(result.get("video_path") or "")
                        if not video_path:
                            raise RuntimeError("视频服务未返回可用文件")
                        stored_path = _relative_path(video_path, VIDEO_OUTPUTS)
                        asset = VideoAsset(story_id=canvas.story_id, chapter_id=canvas.default_chapter_id, asset_type="video_clip", name=f"画布 {canvas.name} - {node_id}", file_path=stored_path, provider="canvas", prompt=prompt, meta_json={"canvas_id": canvas.id, "run_id": run.id, "node_id": node_id, "provider_job_id": provider_job_id}, usage_scope="story_shared")
                        db.add(asset)
                        db.flush()
                        output = {"asset_id": asset.id, "file_path": stored_path, "url": _static_url(stored_path, VIDEO_OUTPUTS, "/static/video"), "duration_seconds": result.get("duration_seconds") or config.get("duration_seconds")}
                else:
                    clips = [
                        {"video_path": path, "duration_seconds": item.get("duration_seconds") or 0}
                        for item in inputs
                        if (path := _canvas_video_path(item.get("file_path"))) is not None
                    ]
                    output_path = _node_output_path(VIDEO_OUTPUTS, canvas.id, run.id, node_id, ".mp4")
                    result = await compile_project(str(output_path), clips, burn_subtitle=False, strict=True)
                    stored_path = _relative_path(str(result["output_path"]), VIDEO_OUTPUTS)
                    output = {"file_path": stored_path, "url": _static_url(stored_path, VIDEO_OUTPUTS, "/static/video"), "duration_seconds": result.get("duration_seconds")}
                outputs[node_id] = output
                if billing_ctx:
                    complete_ai_call(
                        db,
                        billing_ctx,
                        success=True,
                        image_count=1 if node_type in {"image", "image_generation", "storyboard"} else 0,
                        video_seconds=float(output.get("duration_seconds") or config.get("duration_seconds") or 0) if node_type in {"video", "video_generation"} else 0,
                    )
                    run_node.billing_usage_event_id = None
                run_node.output_snapshot_json = output
                run_node.status = "succeeded"
                run_node.completed_at = _now()
                db.commit()
            except asyncio.CancelledError:
                if billing_ctx:
                    complete_ai_call(db, billing_ctx, success=False, error_code="cancelled")
                    run_node.billing_usage_event_id = None
                run_node.status = "cancelled"
                run_node.completed_at = _now()
                run.status = "cancelled"
                run.completed_at = _now()
                _mark_remaining_nodes(db, run, status="cancelled")
                db.commit()
                raise
            except Exception as exc:
                if billing_ctx:
                    complete_ai_call(db, billing_ctx, success=False, error_code=type(exc).__name__)
                    run_node.billing_usage_event_id = None
                run_node.status = "failed"
                run_node.error_message = str(exc)
                run_node.completed_at = _now()
                run.status = "failed"
                run.error_message = str(exc)
                run.completed_at = _now()
                _mark_remaining_nodes(db, run, status="blocked", reason="上游节点执行失败")
                db.commit()
                raise
        run.status = "succeeded"
        run.completed_at = _now()
        db.commit()
        return {"run_id": run.id, "status": run.status}
    finally:
        if task_id:
            task_manager.clear_cancellation_flag(task_id)
        db.close()
