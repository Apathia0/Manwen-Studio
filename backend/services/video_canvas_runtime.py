"""视频无限画布的运行时执行器。"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from database import SessionLocal
from models import AiModel, ChapterVideoShot, ChapterVideoWorkflow, VideoAsset, VideoCanvas, VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion
from services import image2 as image2_service
from services import video_api as video_api_service
from services.ai.resolver import begin_ai_call, complete_ai_call
from services.media_locator import ensure_local_media_path
from services.task_manager import task_manager
from services.video_compiler import compile_project
from services.video_duration import normalize_video_duration
from services.video_generation import fetch_job_result, query_job_status, submit_video_job


BACKEND_DIR = Path(__file__).resolve().parent.parent
MANGA_OUTPUTS = BACKEND_DIR / "manga_outputs"
VIDEO_OUTPUTS = BACKEND_DIR / "video_outputs"
GENERATION_TYPES = {"image", "video", "image_generation", "storyboard", "video_generation", "concat"}
IMAGE_ASSET_TYPES = {"storyboard_frame", "character_reference", "scene_reference", "prop_reference", "style_reference", "image"}
VIDEO_ASSET_TYPES = {"video_clip", "video", "compiled_video", "final_video"}
AUDIO_ASSET_TYPES = {"audio"}


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


def _asset_static_url(path: str) -> str:
    """根据实际存储目录生成资产的静态地址，兼容画布生成和手动上传。"""
    raw_value = str(path or "").strip().replace("\\", "/")
    if raw_value.startswith(("http://", "https://", "/static/")):
        return raw_value
    backend_root = MANGA_OUTPUTS.parent
    if raw_value.startswith("manga_outputs/"):
        relative = raw_value[len("manga_outputs/"):]
        try:
            if (backend_root / raw_value).resolve().is_file():
                return _static_url(relative, MANGA_OUTPUTS, "/static/manga")
        except OSError:
            pass
    if raw_value.startswith("video_outputs/"):
        relative = raw_value[len("video_outputs/"):]
        try:
            if (backend_root / raw_value).resolve().is_file():
                return _static_url(relative, VIDEO_OUTPUTS, "/static/video")
        except OSError:
            pass
    for root, prefix, relative in (
        (MANGA_OUTPUTS, "/static/manga", raw_value),
        (VIDEO_OUTPUTS, "/static/video", raw_value),
    ):
        try:
            if (root / relative).resolve().is_file():
                return _static_url(relative, root, prefix)
        except OSError:
            continue
    return _static_url(raw_value, VIDEO_OUTPUTS, "/static/video")


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
    node_map = {str(node.get("id") or ""): node for node in graph.get("nodes") or [] if isinstance(node, dict)}
    is_concat = str((node_map.get(node_id) or {}).get("type") or "") == "concat"
    entries: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for edge in graph.get("edges") or []:
        if not (isinstance(edge, dict) and edge.get("target") == node_id and not (isinstance(edge.get("data"), dict) and edge["data"].get("disabled"))):
            continue
        value = outputs.get(str(edge.get("source") or ""))
        if not value:
            continue
        edge_sequence = edge.get("data", {}).get("sequence") if isinstance(edge.get("data"), dict) else None
        if is_concat:
            # 合片按显式 sequence 排序（导演编排顺序）：edge.data.sequence 优先，其次上游输出 sequence
            seq = edge_sequence if isinstance(edge_sequence, int) and not isinstance(edge_sequence, bool) else value.get("sequence")
            order = (0, seq) if isinstance(seq, int) and not isinstance(seq, bool) else (1, 0)
            entries.append((order, value))
        else:
            entries.append(((1, 0), value))
    entries.sort(key=lambda item: item[0])
    return [value for _order, value in entries]


def _asset_media_kind(asset: VideoAsset) -> str | None:
    """根据资产类型和受控文件扩展名判定其可连接的媒体端口。"""
    asset_type = str(asset.asset_type or "").lower()
    suffix = Path(str(asset.file_path or "")).suffix.lower()
    if asset_type in VIDEO_ASSET_TYPES or suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    if asset_type in AUDIO_ASSET_TYPES or suffix in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
        return "audio"
    if asset_type in IMAGE_ASSET_TYPES or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    return None


def _video_model_capabilities(config: dict[str, Any], db) -> dict[str, Any] | None:
    """读取画布节点选中模型的受控视频提交能力配置。"""
    model_id = config.get("model_id")
    if not isinstance(model_id, int):
        return None
    model = db.get(AiModel, model_id)
    raw_capabilities = model.capabilities_json if model else None
    video_capabilities = raw_capabilities.get("video") if isinstance(raw_capabilities, dict) else None
    return dict(video_capabilities) if isinstance(video_capabilities, dict) else None


def _resolved_video_model(config: dict[str, Any], db, fallback_model: str) -> str:
    """从受控模型目录解析提交模型，防止模型名与计费模型脱钩。"""
    model_id = config.get("model_id")
    if not isinstance(model_id, int):
        return fallback_model
    model = db.get(AiModel, model_id)
    if not model or model.modality != "video" or not model.enabled:
        raise RuntimeError("视频节点选择的模型不可用")
    return model.model_key


def _require_canvas_asset(db, canvas: VideoCanvas, asset_id: int, media_kind: str) -> VideoAsset:
    """校验资产归属、活动状态和端口媒体类型。"""
    asset = db.get(VideoAsset, asset_id)
    if not asset or asset.story_id != canvas.story_id or asset.status != "active" or not asset.file_path:
        raise RuntimeError("资产不存在或不属于当前作品")
    if _asset_media_kind(asset) != media_kind:
        raise RuntimeError(f"资产不是可用于{media_kind}端口的有效媒体")
    return asset


def _reusable_image_asset(config: dict[str, Any], canvas: VideoCanvas, db) -> VideoAsset | None:
    """解析图片节点可直接复用的资产，并兼容早期仅保存参考资产的配置。"""
    asset_id = config.get("asset_id")
    if isinstance(asset_id, int):
        return _require_canvas_asset(db, canvas, asset_id, "image")

    prompt = str(config.get("prompt") or config.get("storyboard_prompt") or "").strip()
    raw_ids = config.get("reference_asset_ids")
    if prompt or not isinstance(raw_ids, list):
        return None
    asset_ids = [asset_id for asset_id in raw_ids if isinstance(asset_id, int)]
    if len(asset_ids) != 1:
        return None
    return _require_canvas_asset(db, canvas, asset_ids[0], "image")


def _trusted_import_media(node: dict[str, Any], canvas: VideoCanvas, db, media_kind: str) -> str | None:
    """只复用由章节工作流导入且仍与来源记录完全匹配的媒体。"""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    origin = data.get("origin") if isinstance(data.get("origin"), dict) else {}
    expected_type = "chapter_video_shot_storyboard" if media_kind == "image" else "chapter_video_shot_video"
    if origin.get("source_type") != expected_type:
        return None
    shot_id = origin.get("source_id")
    workflow_id = origin.get("source_workflow_id")
    source_url = config.get("trusted_import_media_url")
    if not isinstance(shot_id, int) or not isinstance(workflow_id, int) or not isinstance(source_url, str) or not source_url.strip():
        return None
    workflow = db.get(ChapterVideoWorkflow, workflow_id)
    shot = db.get(ChapterVideoShot, shot_id)
    if not workflow or not shot or shot.workflow_id != workflow.id or workflow.story_id != canvas.story_id:
        return None
    actual_url = shot.storyboard_image_url if media_kind == "image" else shot.video_url
    return actual_url if isinstance(actual_url, str) and actual_url == source_url else None


def _configured_reference_inputs(config: dict[str, Any], canvas: VideoCanvas, db) -> list[dict[str, Any]]:
    """将节点编辑器显式选择的资产转换为受作品归属约束的运行输入。"""
    raw_ids = config.get("reference_asset_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    style_reference_id = config.get("style_reference_asset_id")
    if isinstance(style_reference_id, int) and style_reference_id not in raw_ids:
        raw_ids = [*raw_ids, style_reference_id]
    inputs: list[dict[str, Any]] = []
    for raw_id in raw_ids:
        if not isinstance(raw_id, int):
            continue
        asset = db.get(VideoAsset, raw_id)
        if not asset or asset.story_id != canvas.story_id or asset.status != "active" or not asset.file_path:
            raise RuntimeError("参考资产不存在或不属于当前作品")
        media_kind = _asset_media_kind(asset)
        if media_kind != "image":
            raise RuntimeError("当前视频生成服务仅支持图片参考素材")
        inputs.append({"asset_id": asset.id, "file_path": asset.file_path, "url": asset.file_path, "media_kind": media_kind})
    style_snapshot = config.get("style_snapshot")
    style_image_url = style_snapshot.get("image_url") if isinstance(style_snapshot, dict) else None
    if isinstance(style_image_url, str) and style_image_url.strip():
        normalized_url = style_image_url.strip()
        if not any(str(item.get("url") or "") == normalized_url for item in inputs):
            inputs.append({"url": normalized_url, "media_kind": "image", "style_snapshot": style_snapshot})
    return inputs


def _append_director_continuity(prompt: str, config: dict[str, Any]) -> str:
    """导演动态节点：把连续性/转场锚点以受控格式追加到提示词，保证前后衔接意图不丢失。"""
    extras: list[str] = []
    continuity = config.get("continuity")
    if isinstance(continuity, dict):
        from_previous = str(continuity.get("from_previous") or "").strip()
        to_next = str(continuity.get("to_next") or "").strip()
        anchor = str(continuity.get("anchor") or "").strip()
        if from_previous:
            extras.append(f"开头承接上一段：{from_previous}")
        if to_next:
            extras.append(f"结尾过渡到下一段：{to_next}")
        if anchor:
            extras.append(f"连续性锚点（必须保持）：{anchor}")
    transition_in = str(config.get("transition_in") or "").strip()
    transition_out = str(config.get("transition_out") or "").strip()
    if transition_in and not any(item.startswith("开头承接") for item in extras):
        extras.append(f"进入方式：{transition_in}")
    if transition_out and not any(item.startswith("结尾过渡") for item in extras):
        extras.append(f"离开方式：{transition_out}")
    if not extras:
        return prompt
    return prompt + "\n" + "\n".join(extras)


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
    """将图片参考资产转换为可由视频提交层上传 OSS 的受控路径。"""
    urls: list[str] = []
    for value in inputs:
        asset_id = value.get("asset_id")
        if isinstance(asset_id, int):
            asset = db.get(VideoAsset, asset_id)
            if asset and asset.story_id == canvas.story_id and asset.status == "active" and _asset_media_kind(asset) == "image":
                urls.append(_asset_static_url(asset.file_path))
        reused_url = str(value.get("_media_url") or "").strip()
        if reused_url:
            urls.append(reused_url)
        configured_url = str(value.get("url") or "").strip()
        if configured_url.startswith("/static/"):
            configured_url = _asset_static_url(configured_url)
        if configured_url and configured_url.lower().startswith(("http://", "https://")):
            urls.append(configured_url)
    return list(dict.fromkeys(urls))


async def _external_video_reference_urls(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    """将画布视频参考图统一转换为上游可访问的 OSS 外链。"""
    urls = _reference_urls(inputs, canvas, db)
    external_urls = await video_api_service.prepare_video_reference_urls(urls)
    if any(not url.lower().startswith(("http://", "https://")) for url in external_urls):
        raise RuntimeError("视频参考素材未能转换为 OSS 公网地址")
    return external_urls


def _local_reference_paths(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    """将图片参考资源本地化，供 Image2 以 multipart 方式读取。"""
    paths: list[str] = []
    for value in inputs:
        asset_id = value.get("asset_id")
        asset = db.get(VideoAsset, asset_id) if isinstance(asset_id, int) else None
        configured_url = str(value.get("url") or "").strip()
        if asset is None and configured_url.lower().startswith(("http://", "https://")):
            local_path = ensure_local_media_path(configured_url, "manga")
            if local_path:
                paths.append(local_path)
                continue
            raise RuntimeError("风格参考图 OSS 外链下载失败，无法提交图片生成任务")
        if not asset or asset.story_id != canvas.story_id or asset.status != "active" or _asset_media_kind(asset) != "image":
            continue
        raw_value = str(asset.file_path or "").strip().replace("\\", "/")
        if not raw_value:
            continue
        if raw_value.lower().startswith(("http://", "https://")):
            local_path = ensure_local_media_path(raw_value, "manga")
            if local_path:
                paths.append(local_path)
            else:
                raise RuntimeError("参考图片 OSS 外链下载失败，无法提交图片生成任务")
            continue
        raw_path = Path(raw_value)
        backend_root = MANGA_OUTPUTS.parent
        candidates = [raw_path] if raw_path.is_absolute() else [
            MANGA_OUTPUTS / raw_path,
            VIDEO_OUTPUTS / raw_path,
            backend_root / raw_path,
        ]
        if raw_value.startswith("/static/manga/"):
            candidates.insert(0, MANGA_OUTPUTS / raw_value[len("/static/manga/"):])
        elif raw_value.startswith("/static/video/"):
            candidates.insert(0, VIDEO_OUTPUTS / raw_value[len("/static/video/"):])
        elif raw_value.startswith("manga_outputs/"):
            candidates.insert(0, backend_root / raw_value)
        elif raw_value.startswith("video_outputs/"):
            candidates.insert(0, backend_root / raw_value)
        try:
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved.is_file() and (resolved.is_relative_to(MANGA_OUTPUTS.resolve()) or resolved.is_relative_to(VIDEO_OUTPUTS.resolve())):
                    paths.append(str(resolved))
                    break
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
        run_chapter_id = (run.plan_json or {}).get("chapter_id")
        if not isinstance(run_chapter_id, int):
            run_chapter_id = canvas.default_chapter_id
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
                trusted_import_url = (
                    _trusted_import_media(node, canvas, db, "video" if node_type in {"video", "video_generation"} else "image")
                    if node_type in {"image", "video", "image_generation", "storyboard", "video_generation"}
                    else None
                )
                is_reused = bool(trusted_import_url) or (
                    node_type in {"image", "video", "image_generation", "storyboard", "video_generation"}
                    and isinstance(config.get("asset_id"), int)
                )
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
                        chapter_id=run_chapter_id,
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
                    if trusted_import_url:
                        output = {"url": trusted_import_url, "_media_url": trusted_import_url, "reused": True}
                    elif asset := _reusable_image_asset(config, canvas, db):
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
                            prefer_local=True,
                        )
                        stored_path = _relative_path(str(saved_path), MANGA_OUTPUTS)
                        asset = VideoAsset(story_id=canvas.story_id, chapter_id=run_chapter_id, asset_type="storyboard_frame", name=f"画布 {canvas.name} - {node_id}", file_path=stored_path, provider="image2", prompt=prompt, meta_json={"canvas_id": canvas.id, "run_id": run.id, "node_id": node_id}, usage_scope="story_shared")
                        db.add(asset)
                        db.flush()
                        output = {"asset_id": asset.id, "file_path": stored_path, "url": _static_url(stored_path, MANGA_OUTPUTS, "/static/manga")}
                elif node_type in {"video", "video_generation"}:
                    if trusted_import_url:
                        output = {"url": trusted_import_url, "_media_url": trusted_import_url, "reused": True, "duration_seconds": config.get("duration_seconds")}
                    elif isinstance(config.get("asset_id"), int):
                        asset = _require_canvas_asset(db, canvas, config["asset_id"], "video")
                        output = {"asset_id": asset.id, "file_path": asset.file_path, "url": _static_url(asset.file_path, VIDEO_OUTPUTS, "/static/video"), "reused": True}
                    else:
                        resolved_video_model = _resolved_video_model(config, db, video_model)
                        prompt = str(config.get("prompt") or "").strip() or _first_input_text(inputs, ("video_prompt", "text", "content", "storyboard_prompt", "prompt", "screenplay"))
                        prompt = _apply_style_prompt(prompt, config, inputs)
                        if not prompt or not video_api_key:
                            raise RuntimeError("视频节点缺少提示词或 Video API Key")
                        # 导演动态时长：提交前按模型能力归一；旧节点保持 15s 兼容默认
                        duration_policy = str(config.get("duration_policy") or "")
                        raw_duration = config.get("duration_seconds")
                        if duration_policy == "director_dynamic":
                            effective_duration = normalize_video_duration(
                                raw_duration if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool) else None,
                                model=resolved_video_model,
                                capabilities=_video_model_capabilities(config, db),
                                default_seconds=6,
                            )
                            prompt = _append_director_continuity(prompt, config)
                        else:
                            effective_duration = int(config.get("duration_seconds") or 15)
                        submission = await submit_video_job(
                            shot_id=run_node.id,
                            provider="canvas",
                            model=resolved_video_model,
                            prompt=prompt,
                            negative_prompt=str(config.get("negative_prompt") or ""),
                            duration_seconds=effective_duration,
                            aspect_ratio=str(config.get("aspect_ratio") or "16:9"),
                            size=str(config.get("size") or "720P"),
                            reference_images=await _external_video_reference_urls(inputs, canvas, db),
                            api_key=video_api_key,
                            base_url=video_base_url,
                            video_capabilities=_video_model_capabilities(config, db),
                        )
                        provider_job_id = submission["provider_job_id"]
                        for _ in range(120):
                            if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                                raise asyncio.CancelledError()
                            status = await query_job_status("canvas", provider_job_id, api_key=video_api_key, base_url=video_base_url, model=resolved_video_model)
                            if status["status"] == "succeeded":
                                break
                            if status["status"] in {"failed", "cancelled"}:
                                raise RuntimeError(str(status.get("error") or "视频生成失败"))
                            await asyncio.sleep(5)
                        else:
                            raise RuntimeError("视频生成超时")
                        result = await fetch_job_result("canvas", provider_job_id, run_node.id, api_key=video_api_key, base_url=video_base_url, model=resolved_video_model)
                        video_path = str(result.get("video_path") or "")
                        if not video_path:
                            raise RuntimeError("视频服务未返回可用文件")
                        stored_path = _relative_path(video_path, VIDEO_OUTPUTS)
                        asset = VideoAsset(story_id=canvas.story_id, chapter_id=run_chapter_id, asset_type="video_clip", name=f"画布 {canvas.name} - {node_id}", file_path=stored_path, provider="canvas", prompt=prompt, meta_json={
                            "canvas_id": canvas.id, "run_id": run.id, "node_id": node_id, "provider_job_id": provider_job_id,
                            **({"duration_requested": config.get("duration_requested"), "duration_reason": config.get("duration_reason"), "sequence": config.get("sequence"), "unit_id": config.get("unit_id"), "director_plan_hash": config.get("director_plan_hash")} if duration_policy == "director_dynamic" else {}),
                        }, usage_scope="story_shared")
                        db.add(asset)
                        db.flush()
                        output = {"asset_id": asset.id, "file_path": stored_path, "url": _static_url(stored_path, VIDEO_OUTPUTS, "/static/video"), "duration_seconds": result.get("duration_seconds") or effective_duration}
                        if duration_policy == "director_dynamic":
                            output.update({
                                "duration_requested": config.get("duration_requested"),
                                "duration_effective": effective_duration,
                                "duration_reason": config.get("duration_reason"),
                                "sequence": config.get("sequence"),
                                "unit_id": config.get("unit_id"),
                                "director_plan_hash": config.get("director_plan_hash"),
                            })
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
                if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                    raise asyncio.CancelledError()
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
        if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
            run.status = "cancelled"
        else:
            run.status = "succeeded"
        run.completed_at = _now()
        db.commit()
        return {"run_id": run.id, "status": run.status}
    finally:
        if task_id:
            task_manager.clear_cancellation_flag(task_id)
        db.close()
