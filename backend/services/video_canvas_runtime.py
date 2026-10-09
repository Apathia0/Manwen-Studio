"""视频无限画布的运行时执行器。"""

from __future__ import annotations

import os
import hashlib
import time
import logging
import asyncio
import datetime
import math
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from database import SessionLocal
from models import AiChannel, AiModel, AiUsageEvent, ChapterVideoShot, ChapterVideoWorkflow, VideoAsset, VideoCanvas, VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion
from services import image2 as image2_service
from services import video_api as video_api_service
from services.ai.resolver import begin_ai_call, complete_ai_call_by_usage_event
from services.canvas_run_reuse import (
    IMAGE_OUTPUT_NODE_TYPES,
    REUSABLE_OUTPUT_NODE_TYPES,
    clear_invalid_reuse_markers,
    definition_hash,
    find_reusable_outputs,
    resolve_rerun_node_ids,
    scope_node_ids,
)
from services.media_locator import ensure_local_media_path
from services.task_manager import task_manager
from services.video_compiler import compile_project
from services.video_duration import _duration_options, normalize_video_duration
from services.video_generation import fetch_job_result, query_job_status, submit_video_job


logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
MANGA_OUTPUTS = BACKEND_DIR / "manga_outputs"
VIDEO_OUTPUTS = BACKEND_DIR / "video_outputs"
# 角色资产出图的版式要求：干净的身份参考，避免把档案表格、色板、服装拆解都塞进一张图，
# 后续分镜才能稳定提取脸型、发型和服装。放在提示词末尾，优先于前文任何版式描述。
CHARACTER_IDENTITY_SHEET_DIRECTIVE = (
    "\n\n【版式要求，优先于前文任何版式描述】只画这一个角色的身份参考图：纯净浅色背景，横向 16:9 构图；"
    "左侧一张正面全身站姿，中间侧面全身与背面全身，右侧一张正面头部特写。"
    "同一角色在所有视图中脸型、发型、服装、配饰、体型严格一致；"
    "图中不要自己画任何文字（名称标注由系统在图片下方统一加上）、不要档案表格、不要色板、不要服装拆解、不要多余表情格和背景场景。"
)
_SLIM_DROP_LINE = re.compile(r"^\s*(?:生日|体重|职业|MBTI|Big Five|关键词|角色弧光|性格|表情系统)\s*[:：]")
_SLIM_DROP_PARAGRAPH = re.compile(r"^\s*(?:LEFT PANEL|RIGHT PANEL|Professional character design sheet|Accurate anatomy)", re.I)


def slim_character_prompt(prompt: str) -> str:
    """旧版角色提示词（来自漫画 / 视频工作流的整页设定板模板）精简成只剩外貌的内容。

    那种模板里有大段“设定板、信息栏、表情格、服装分解图、masterpiece、8k professional rendering”之类的版式和画质黑话，
    会把模型推向插画风的设定稿，压过风格参考图，还和后面“只画干净的三视图”的版式要求互相矛盾。
    只去掉明确无关的段落和行（版式面板、画质套话、性格 / MBTI 等非外貌条目），外貌和服装描述原样保留。"""
    text = str(prompt or "")
    if "FINAL IMAGE PROMPT" not in text and "LEFT PANEL" not in text:
        return text
    kept: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        if _SLIM_DROP_PARAGRAPH.match(paragraph.strip()):
            continue
        lines = [line for line in paragraph.split("\n") if not _SLIM_DROP_LINE.match(line)]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            kept.append(cleaned)
    return "\n\n".join(kept)


# 场景 / 道具资产图的版式：画面干净、主体明确，后面会被当作参考图使用；名称标注同样由系统统一加在图片下方
SCENE_ASSET_DIRECTIVE = (
    "\n\n【版式要求，优先于前文任何版式描述】这是一张场景参考图：横向 16:9 的空镜，画面里没有任何人物，"
    "完整展示这个地点的空间布局、建筑与陈设、材质、光线和氛围，视角稳定，便于后续镜头保持同一个场景。"
    "图中不要自己画任何文字、数字、标签或水印（名称标注由系统在图片下方统一加上）。"
)
PROP_ASSET_DIRECTIVE = (
    "\n\n【版式要求，优先于前文任何版式描述】这是一张道具参考图：只画这一件物品，居中放置、完整入画，"
    "纯净浅色背景，光线均匀，展示它的形状、材质、颜色、大小比例和关键细节，不要出现人物或其他物品。"
    "图中不要自己画任何文字、数字、标签或水印（名称标注由系统在图片下方统一加上）。"
)
# 画风锚点（风格预设图 / 用户上传的风格图）：图生图控制画风，比提示词里的画风文字可靠得多
STYLE_ANCHOR_DIRECTIVE = (
    "\n\n【画风统一·最高优先级】本次附带的“画风参考”图是全片统一画风的锚点。首先是渲染媒介必须与参考图一致："
    "参考图是真实摄影 / 电影画面时，人物必须是真人质感（真实的皮肤纹理、自然的光影和比例），不要画成插画、概念设定图、3D 渲染、动漫或游戏立绘；"
    "参考图是插画 / 动漫 / 3D 时同理保持同一种媒介。然后是线条与描边、上色或渲染方式、色调与饱和度、"
    "光影质感、人物与物体的风格化程度（头身比、五官简化程度）必须与它保持一致，像同一部作品里的画面。"
    "它只决定画风，不决定内容：不要复制其中的人物、服装、物体或构图。提示词里关于画风的文字与参考图冲突时，以参考图为准。"
)


def is_style_anchor(item: Any) -> bool:
    return isinstance(item, dict) and bool(item.get("style_anchor"))


def style_anchors_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """图片生成：画风锚点排在所有参考图最前面（稳定排序，其余顺序不变）。"""
    return sorted(items, key=lambda item: 0 if is_style_anchor(item) else 1)


def order_video_references(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """视频参考图：画风锚点紧跟第一张（分镜首帧 / 分镜板）之后，降级时不会最先被丢；超过上限时先丢画风锚点，而不是让整条视频任务报错。"""
    anchors = [item for item in items if is_style_anchor(item)]
    others = [item for item in items if not is_style_anchor(item)]
    if not anchors:
        return list(items)
    if len(items) > limit:
        return others
    return [*others[:1], *anchors, *others[1:]]


# 分镜出图时的身份绑定：参考图只提供人物长相，不提供版式。
STORYBOARD_IDENTITY_DIRECTIVE = (
    "\n\n【人物一致性】画面中出现的人物（{names}）必须严格使用各自对应参考图里的人物："
    "脸型、五官、发型、发色、服装、配饰、体型都与参考图一致，不得重新设计。"
    "多个人物各自对应各自的参考图，不得混用、互换或合并。"
    "参考图是人物设定图，只提取人物外貌，不要复制其版式、文字、多视图或色板。"
)
# 视频轮询：初期 5 秒一次，等得越久间隔越长（最长 20 秒）；连续查询失败超过该次数才暂停
VIDEO_POLL_INTERVAL_SECONDS = 5
VIDEO_POLL_MAX_CONSECUTIVE_ERRORS = 30


def reference_fallback_tiers(count: int) -> list[int]:
    """上游确定性拒绝参考图时依次尝试的参考图张数：全部 → 一半 → 只留 1 张（分镜首帧）。"""
    if count <= 1:
        return [max(count, 0)]
    tiers: list[int] = []
    for value in (count, (count + 1) // 2, 1):
        if value not in tiers:
            tiers.append(value)
    return tiers


async def submit_with_reference_fallback(submit_once, reference_images: list[str], entries: list[tuple[str, str]], base_prompt: str, token_format: str = "图片{n}", sheet_panels: list[dict[str, Any]] | None = None):
    """提交视频；若上游对这批参考图返回确定性失败（不是网络抖动），按档位减少参考图重试。

    参考图顺序是 分镜首帧 → 角色 → 场景，所以减少时先丢场景、靠后的角色，分镜首帧始终保留。
    每一档都会重新生成「参考图对应关系」说明，序号与实际传给上游的图一一对应。失败的提交在上游
    素材准备阶段就被拒绝（十几秒），没有进入生成，不会产生视频费用。
    返回 (提交结果, 实际使用的参考图, 实际使用的提示词)。
    """
    from services.errors import UpstreamServiceError

    tiers = reference_fallback_tiers(len(reference_images))
    for position, keep in enumerate(tiers):
        images = reference_images[:keep]
        final_prompt = base_prompt + build_video_identity_directive(entries[:keep], token_format, sheet_panels) if images else base_prompt
        try:
            submission = await submit_once(images, final_prompt, "image_to_video" if images else "text_to_video")
        except UpstreamServiceError as exc:
            deterministic = getattr(exc, "retryable", True) is False and int(getattr(exc, "status_code", 0) or 0) >= 500
            if position == len(tiers) - 1 or not deterministic:
                raise
            logger.warning("上游拒绝了 %s 张参考图，自动减少到 %s 张重试：%s", keep, tiers[position + 1], str(exc)[:160])
            continue
        return submission, images, final_prompt
    raise RuntimeError("视频提交没有可用的参考图档位")


def _video_poll_interval(waited_seconds: float) -> float:
    """已等待时间 → 下一次查询前的间隔秒数。"""
    if waited_seconds < 300:
        return VIDEO_POLL_INTERVAL_SECONDS
    if waited_seconds < 1800:
        return 10
    return 20


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


async def _canvas_clip_path(item: dict[str, Any], canvas: VideoCanvas, db) -> str | None:
    """把受控视频输出解析为合片可读的本地文件。

    远程地址只接受已通过资产归属校验或可信列表工作流导入后写入运行输出的值；
    下载仍由 media_locator 执行 URL 安全校验和大小限制。
    """
    local_path = _canvas_video_path(item.get("file_path"))
    if local_path:
        return local_path
    asset_id = item.get("asset_id")
    if isinstance(asset_id, int):
        asset = _require_canvas_asset(db, canvas, asset_id, "video")
        candidate = await asyncio.to_thread(ensure_local_media_path, asset.file_path, "video")
        return candidate if candidate and Path(candidate).is_file() else None
    trusted_url = str(item.get("_media_url") or "").strip()
    if not trusted_url.startswith(("http://", "https://", "/static/video/")):
        return None
    candidate = await asyncio.to_thread(ensure_local_media_path, trusted_url, "video")
    return candidate if candidate and Path(candidate).is_file() else None


_RUNTIME_PORTS: dict[str, dict[str, dict[str, Any]]] = {
    "container": {"inputs": {"items": {"type": "any", "multiple": True}}, "outputs": {"assets": {"type": "any"}}},
    "text": {"inputs": {"source": {"type": "any", "multiple": True}}, "outputs": {"text": {"type": "any"}}},
    "screenplay": {"inputs": {"source": {"type": "any", "multiple": True}}, "outputs": {"screenplay": {"type": "any"}}},
    "scene": {"inputs": {"screenplay": {"type": "any", "multiple": True}}, "outputs": {"shot": {"type": "any"}}},
    "shot": {"inputs": {"screenplay": {"type": "any", "multiple": True}, "references": {"type": "image", "multiple": True}}, "outputs": {"shot": {"type": "any"}}},
    "style": {"inputs": {}, "outputs": {"style": {"type": "style"}}},
    "image": {"inputs": {"prompt": {"type": "any", "multiple": True}, "references": {"type": "image", "multiple": True}}, "outputs": {"image": {"type": "any"}}},
    "image_generation": {"inputs": {"prompt": {"type": "any", "multiple": True}, "references": {"type": "image", "multiple": True}, "style": {"type": "style"}}, "outputs": {"image": {"type": "image"}}},
    "storyboard": {"inputs": {"shot": {"type": "any", "multiple": True}, "references": {"type": "image", "multiple": True}, "style": {"type": "style"}}, "outputs": {"image": {"type": "image"}}},
    "video": {"inputs": {"prompt": {"type": "any", "multiple": True}, "image": {"type": "image", "multiple": True}, "audio": {"type": "audio", "multiple": True}, "style": {"type": "style"}}, "outputs": {"video": {"type": "video"}}},
    "audio": {"inputs": {}, "outputs": {"audio": {"type": "audio"}}},
    "video_generation": {"inputs": {"prompt": {"type": "any", "multiple": True}, "image": {"type": "image", "multiple": True}, "style": {"type": "style"}}, "outputs": {"video": {"type": "video"}}},
    "concat": {"inputs": {"videos": {"type": "video", "multiple": True}}, "outputs": {"video": {"type": "video"}}},
    "asset": {"inputs": {}, "outputs": {"asset": {"type": "image"}}},
    "video_asset": {"inputs": {}, "outputs": {"video": {"type": "video"}}},
}


def _runtime_port(node: dict[str, Any], handle: Any, side: str) -> dict[str, Any] | None:
    node_type = str(node.get("type") or "")
    ports = _RUNTIME_PORTS.get(node_type, {}).get(f"{side}s", {})
    requested = str(handle or "")
    if requested:
        return ports.get(requested)
    # Early canvas versions omitted handles for single-port edges. Preserve
    # those frozen graphs by inferring the only declared port; explicit bad
    # handles remain errors and are never silently coerced.
    if len(ports) == 1:
        return next(iter(ports.values()))
    return None


def resolve_node_inputs(
    graph: dict[str, Any], node_id: str, outputs: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Resolve active incoming edges by target port, rejecting missing upstream output."""
    node_map = {str(node.get("id") or ""): node for node in graph.get("nodes") or [] if isinstance(node, dict)}
    target = node_map.get(node_id)
    if not target:
        raise RuntimeError(f"目标节点 {node_id} 不存在")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("target") != node_id or (isinstance(edge.get("data"), dict) and edge["data"].get("disabled")):
            continue
        source_id = str(edge.get("source") or "")
        source = node_map.get(source_id)
        source_handle = str(edge.get("sourceHandle") or "")
        target_handle = str(edge.get("targetHandle") or "")
        if not source:
            raise RuntimeError(f"连线来源节点 {source_id} 不存在（目标 {node_id}）")
        source_port = _runtime_port(source, source_handle, "output")
        target_port = _runtime_port(target, target_handle, "input")
        if not source_port or not target_port:
            raise RuntimeError(f"节点 {source_id} 的端口 {source_handle} 无法连接到节点 {node_id} 的端口 {target_handle}")
        source_type = source_port.get("type")
        target_type = target_port.get("type")
        if source_type != target_type and "any" not in {source_type, target_type}:
            raise RuntimeError(f"节点 {source_id}.{source_handle} 类型 {source_type} 与 {node_id}.{target_handle} 类型 {target_type} 不兼容")
        value = outputs.get(source_id)
        if not isinstance(value, dict):
            raise RuntimeError(f"节点 {node_id} 的上游 {source_id} 没有可用输出")
        source_type_name = str(source.get("type") or "")
        values = value.get("items", []) if source_type_name == "container" else [value]
        if source_type_name == "container" and not isinstance(values, list):
            raise RuntimeError(f"节点 {source_id} 的容器输出无效，无法提供给 {node_id}")
        edge_sequence = edge.get("data", {}).get("sequence") if isinstance(edge.get("data"), dict) else None
        target_key = target_handle or next(
            key for key, value_spec in _RUNTIME_PORTS.get(str(target.get("type") or ""), {}).get("inputs", {}).items()
            if value_spec is target_port
        )
        bucket = grouped.setdefault(target_key, [])
        for item in values:
            if not isinstance(item, dict):
                continue
            if isinstance(edge_sequence, int) and not isinstance(edge_sequence, bool):
                item = {**item, "sequence": item.get("sequence", edge_sequence)}
            bucket.append(item)
    if str(target.get("type") or "") == "concat":
        grouped["videos"] = sorted(grouped.get("videos", []), key=lambda item: (0, item["sequence"]) if isinstance(item.get("sequence"), int) and not isinstance(item.get("sequence"), bool) else (1, 0))
    return grouped


def _node_inputs(graph: dict[str, Any], node_id: str, outputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible flattened view; execution uses resolve_node_inputs for port isolation."""
    # Older unit callers supplied only edges. Keep that narrow helper contract
    # while the frozen runtime graph always goes through the strict resolver.
    if not any(isinstance(node, dict) and str(node.get("id") or "") == node_id for node in graph.get("nodes") or []):
        entries: list[dict[str, Any]] = []
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict) or edge.get("target") != node_id:
                continue
            value = outputs.get(str(edge.get("source") or ""))
            if isinstance(value, dict):
                entries.append(value)
        return entries
    grouped = resolve_node_inputs(graph, node_id, outputs)
    return [item for values in grouped.values() for item in values]


def _validate_runtime_graph(graph: dict[str, Any]) -> None:
    """Re-check frozen graph ports immediately before executing any node."""
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise RuntimeError("画布运行快照的节点或连线格式无效")
    node_map = {str(node.get("id") or ""): node for node in graph["nodes"] if isinstance(node, dict)}
    for node_id, node in node_map.items():
        node_type = str(node.get("type") or "")
        if node_type in {"note", "output"}:
            continue
        if node_type not in _RUNTIME_PORTS:
            raise RuntimeError(f"节点 {node_id} 的类型 {node_type} 无运行时协议")
        if not _RUNTIME_PORTS[node_type].get("outputs"):
            raise RuntimeError(f"节点 {node_id} 没有可用输出端口")
    for edge in graph["edges"]:
        if not isinstance(edge, dict) or (isinstance(edge.get("data"), dict) and edge["data"].get("disabled")):
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        source = node_map.get(source_id)
        target = node_map.get(target_id)
        if not source or not target:
            raise RuntimeError(f"活动连线引用了不存在的节点：{source_id} → {target_id}")
        source_port = _runtime_port(source, edge.get("sourceHandle"), "output")
        target_port = _runtime_port(target, edge.get("targetHandle"), "input")
        if not source_port or not target_port:
            raise RuntimeError(f"活动连线端口无效：{source_id}.{edge.get('sourceHandle')} → {target_id}.{edge.get('targetHandle')}")
        if source_port.get("type") != target_port.get("type") and "any" not in {source_port.get("type"), target_port.get("type")}:
            raise RuntimeError(f"活动连线端口类型不兼容：{source_id} → {target_id}")


def _validate_runtime_output_contract(graph: dict[str, Any], node_id: str, output: dict[str, Any]) -> None:
    """Reject missing output payloads before downstream nodes can continue silently."""
    node_map = {str(node.get("id") or ""): node for node in graph.get("nodes") or [] if isinstance(node, dict)}
    node = node_map.get(node_id)
    node_type = str((node or {}).get("type") or "")
    if node_type == "container" and not isinstance(output.get("items"), list):
        raise RuntimeError(f"节点 {node_id} 的容器没有有效输出")
    if node_type == "concat" and not (output.get("file_path") or output.get("url")):
        raise RuntimeError(f"节点 {node_id} 未生成成片输出")
    if node_type in {"image", "image_generation", "storyboard", "asset"} and not (output.get("asset_id") or output.get("url") or output.get("file_path")):
        raise RuntimeError(f"节点 {node_id} 未生成图片输出")
    if node_type == "audio" and not (output.get("asset_id") and (output.get("url") or output.get("file_path"))):
        raise RuntimeError(f"节点 {node_id} 未选择有效音频")
    if node_type in {"video", "video_generation", "video_asset"} and not (output.get("asset_id") or output.get("url") or output.get("file_path")):
        raise RuntimeError(f"节点 {node_id} 未生成视频输出")


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


def _restore_usage_runtime(db, usage_event_id: int | None, modality: str) -> tuple[str | None, str | None, str | None]:
    """Restore model/channel context for a resumed reserved usage event."""
    if not isinstance(usage_event_id, int):
        return None, None, None
    event = db.get(AiUsageEvent, usage_event_id)
    if not event or getattr(event, "status", None) in {"failed", "refunded"}:
        return None, None, None
    model_id = getattr(event, "model_id", None)
    if not isinstance(model_id, int):
        return None, None, None
    model = db.get(AiModel, model_id)
    if not model or getattr(model, "modality", None) != modality or not getattr(model, "enabled", True):
        return None, None, None
    channel = db.get(AiChannel, getattr(model, "channel_id", None))
    if not channel or not getattr(channel, "enabled", True) or not getattr(channel, "base_url", None):
        return None, None, None
    from services.ai.channels import load_platform_key
    from services.ai.credentials import load_user_api_key_plain
    api_key = (
        load_user_api_key_plain(db, getattr(event, "user_id", 0), modality)
        if str(getattr(event, "credential_mode", "platform") or "platform") == "user_key"
        else load_platform_key(channel)
    )
    return model.model_key, channel.base_url.rstrip("/"), api_key


def _image_model_capabilities(config: dict[str, Any], db) -> dict[str, Any] | None:
    """读取画布图片节点所选模型的受控能力配置。"""
    model_id = config.get("model_id")
    if not isinstance(model_id, int):
        return None
    model = db.get(AiModel, model_id)
    raw_capabilities = model.capabilities_json if model else None
    image_capabilities = raw_capabilities.get("image") if isinstance(raw_capabilities, dict) else None
    return dict(image_capabilities) if isinstance(image_capabilities, dict) else None


def _resolved_image_model(config: dict[str, Any], db, fallback_model: str) -> str:
    """从受控模型目录解析图片模型，避免 UI 选择只停留在配置层。"""
    model_id = config.get("model_id")
    if not isinstance(model_id, int):
        return fallback_model
    model = db.get(AiModel, model_id)
    if not model or model.modality != "image" or not model.enabled:
        raise RuntimeError("图片节点选择的模型不可用")
    return model.model_key


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


def asset_reference_role(asset: Any) -> str:
    """资产作为视频参考图时的用途：frame 分镜首帧 / character 角色 / scene 场景 / prop 道具 / other。"""
    if asset is None:
        return "other"
    role = str((getattr(asset, "meta_json", None) or {}).get("asset_role") or "")
    if role in {"character", "scene", "prop"}:
        return role
    if (getattr(asset, "meta_json", None) or {}).get("storyboard_sheet"):
        return "sheet"
    return {"character_reference": "character", "scene_reference": "scene", "prop_reference": "prop", "storyboard_frame": "frame"}.get(getattr(asset, "asset_type", ""), "other")


def video_reference_entries(inputs: list[dict[str, Any]], db) -> list[tuple[str, str]]:
    """视频节点每张参考图的 (用途, 名称)：frame 分镜首帧 / character 角色 / scene 场景 / prop 道具 / other。"""
    entries: list[tuple[str, str]] = []
    for item in inputs:
        asset = db.get(VideoAsset, item.get("asset_id")) if isinstance(item.get("asset_id"), int) else None
        if is_style_anchor(item):
            entries.append(("style", ""))
            continue
        entries.append((asset_reference_role(asset), str(asset.name or "") if asset else ""))
    return entries


def reference_label_text(role: str, name: str) -> str:
    """压在参考图上的文字：这张图是什么。例如「角色：萧炎」「场景：广场」「分镜首帧」。"""
    kinds = {"character": "角色", "scene": "场景", "prop": "道具"}
    name = (name or "").strip()
    # 画布生成的资产名形如“画布 xxx - image-abc123”，不是给人 / 模型看的名字，不标
    if role in kinds and name:
        return f"{kinds[role]}：{name}"
    if role == "frame":
        return "分镜首帧（构图参考）"
    if role == "sheet":
        return "分镜板（按格序对应各时间段）"
    return ""


def build_video_identity_directive(entries: list[tuple[str, str]], token_format: str = "图片{n}", sheet_panels: list[dict[str, Any]] | None = None) -> str:
    """提交视频时追加的一致性约束：先说明每张参考图是什么，再按出现的类别写人物 / 道具 / 场景的一致性要求。"""
    if not entries:
        return ""
    from services.canvas_storyboard_sheet import video_sheet_description

    kind_label = {"frame": "分镜首帧", "sheet": "分镜板", "character": "角色", "scene": "场景", "prop": "道具", "style": "画风参考", "other": "参考"}

    def describe(index: int, role: str, name: str) -> str:
        base = f"{token_format.format(n=index)}：{kind_label[role]}"
        if role == "style":
            return f"{base}（画风、色调、光影、渲染质感以这张图为准）"
        if role == "sheet" and sheet_panels:
            return f"{base}（{video_sheet_description(sheet_panels)}）"
        return base + (f"「{name}」" if name and role not in {"frame", "sheet"} else "")

    mapping = "；".join(describe(index, role, name) for index, (role, name) in enumerate(entries, start=1))
    present = {role for role, _ in entries}
    rules: list[str] = []
    if "sheet" in present:
        rules.append("分镜板是这个镜头的分格预览：请按各格的画面、人物站位、景别和先后顺序，在对应的时间段里依次展开成连续的视频，每个时间段的内容都要出现；板上的格线、序号、时间标注只是给你对照用的，不要画进视频里")
    if "frame" in present:
        rules.append("画面起点与构图承接分镜首帧，人物站位、镜头景别和光线保持一致，不要另起一个新场面")
    if "character" in present:
        rules.append("出场人物的脸型、五官、发型发色、服装配饰、体型必须与对应角色参考图完全一致，全程保持同一张脸和同一套服装，不要重新设计，多个人物各自对应各自的参考图，不要混淆")
    if "prop" in present:
        rules.append("道具的形状、颜色、材质、大小和细节必须与道具参考图一致，不得变形或替换")
    if "scene" in present:
        rules.append("场景的空间布局、建筑与陈设、材质、光线和氛围必须与场景参考图一致，镜头内不得出现与之矛盾的背景")
    if "style" in present:
        style_rule = "本视频的画风、色彩、光影以风格参考图为准，保持画面风格稳定统一"
        if present & {"frame", "sheet"}:
            style_rule += "；分镜仅提供构图和动作参考，视频色彩、光影、渲染质感不受分镜影响，完全以风格参考图为准"
        rules.append(style_rule + "（只取画风，不复制风格参考图里的人物、场景或构图）")
    rules.append(("角色、场景、道具参考图" if "sheet" in present else "参考图") + "仅用于锁定外观，不要复制其中的版式、文字、标注或多视图排布")
    return "\n\n【参考图对应关系】" + mapping + "。\n【一致性约束】" + "；".join(rules) + "。"



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
        item = {"asset_id": asset.id, "file_path": asset.file_path, "url": asset.file_path, "media_kind": media_kind}
        if raw_id == style_reference_id:
            item["style_anchor"] = True  # 用户上传的自定义风格图
        inputs.append(item)
    style_snapshot = config.get("style_snapshot")
    style_image_url = style_snapshot.get("image_url") if isinstance(style_snapshot, dict) else None
    if isinstance(style_image_url, str) and style_image_url.strip():
        normalized_url = style_image_url.strip()
        if not any(str(item.get("url") or "") == normalized_url for item in inputs):
            inputs.append({"url": normalized_url, "media_kind": "image", "style_snapshot": style_snapshot, "style_anchor": True})
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


from services.canvas_style import apply_canvas_style, canvas_style, strip_style_text  # noqa: E402


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
    if isinstance(config.get("style_reference_asset_id"), int) or any(isinstance(item, dict) and item.get("style_anchor") for item in inputs):
        # 有风格参考图：画风只由图控制（图生图），不再附加风格文字，避免文字与参考图冲突
        style_fragments = ["画风、色彩、光影与线条质感以画风参考图为准"]
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


_VIDEO_REFERENCE_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".flv")


def _is_video_media_url(url: str) -> bool:
    """已知视频扩展名的 URL 不能当作图片参考传给上游（组内视频成员会被上游边带进来）。"""
    path = str(url or "").split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(_VIDEO_REFERENCE_SUFFIXES)


_LABEL_FONT_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
    # Linux（Docker 镜像里安装 fonts-wqy-microhei；也兼容 Noto CJK）
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc", "/Library/Fonts/Arial Unicode.ttf",
)
_label_font_warned = False


def _label_font(size: int):
    """找一个能显示中文的字体；环境变量 VIDEO_REF_LABEL_FONT 可指定路径。找不到返回 None（此时不加标注）。"""
    global _label_font_warned
    from PIL import ImageFont

    candidates = [os.environ.get("VIDEO_REF_LABEL_FONT", "").strip(), *_LABEL_FONT_CANDIDATES]
    for path in candidates:
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001 - 字体损坏就试下一个
                continue
    if not _label_font_warned:
        _label_font_warned = True
        logger.warning("没有找到可显示中文的字体，视频参考图将不加文字标注（可设置环境变量 VIDEO_REF_LABEL_FONT）")
    return None


def _add_label_bar(image, label: str):
    """在图片下方接一条标注栏（不遮挡画面内容）：深色底、白字、居中，字号随图宽自适应。"""
    from PIL import Image, ImageDraw

    width, height = image.size
    bar = max(48, round(width * 0.06))
    size = int(bar * 0.6)
    font = _label_font(size)
    if font is None:
        return image
    draw_probe = ImageDraw.Draw(image)
    while size > 14 and draw_probe.textlength(label, font=font) > width - 24:
        size -= 2
        font = _label_font(size)
        if font is None:
            return image
    canvas = Image.new("RGB", (width, height + bar), (22, 22, 22))
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    text_width = draw.textlength(label, font=font)
    draw.text(((width - text_width) / 2, height + (bar - size) / 2 - 2), label, font=font, fill=(255, 255, 255))
    return canvas


def stamp_asset_label_bar(image_path: str | Path, label: str) -> bool:
    """给资产图原文件下方加一条名称标注条（深色底白字）。成功返回 True；没有名称 / 没有中文字体 / 出错都返回 False，原图不动。"""
    if not label:
        return False
    from PIL import Image

    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        stamped = _add_label_bar(image, label)
        if stamped is image:
            return False
        stamped.save(image_path, "PNG", optimize=True)
        return True
    except Exception:  # noqa: BLE001 - 标注失败不能让资产生成失败
        logger.warning("资产图名称标注写入失败：%s", image_path, exc_info=True)
        return False


async def _ensure_asset_oss_urls(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> None:
    """提交视频前确保每个图片资产有云端外链：已有外链（生成时直传记下的 oss_url，或资产本身就在云端）直接复用，
    只有旧资产、当时 OSS 未启用或上传失败的才补传一次原图，并把外链记回资产，之后再被引用不会再传。"""
    changed = False
    for value in inputs:
        asset_id = value.get("asset_id")
        asset = db.get(VideoAsset, asset_id) if isinstance(asset_id, int) else None
        if not asset or asset.story_id != canvas.story_id or asset.status != "active" or _asset_media_kind(asset) != "image":
            continue
        meta = dict(getattr(asset, "meta_json", None) or {})
        if str(meta.get("oss_url") or "").lower().startswith(("http://", "https://")):
            continue
        file_path = str(asset.file_path or "").strip()
        if file_path.lower().startswith(("http://", "https://")):
            meta["oss_url"] = file_path
        else:
            local_paths = _local_reference_paths([value], canvas, db)
            if not local_paths:
                continue
            oss_url = await _upload_generated_image_to_oss(local_paths[0])
            if not oss_url:
                continue
            meta["oss_url"] = oss_url
        asset.meta_json = meta
        changed = True
    if changed:
        db.commit()


async def _upload_generated_image_to_oss(local_path: Any) -> str | None:
    """把刚生成的画布图片传到 OSS（已启用才传；失败只记日志，不影响本次生成）。

    本地文件仍是主副本：画布展示、后续图生图参考都继续读本地；OSS 地址记入资产元数据，
    供提交视频时直接作为参考图外链，也为后续切换 CDN 回显留好数据。
    """
    from services import oss as oss_service
    from services.blocking import run_blocking

    try:
        await run_blocking(oss_service.auto_configure_from_db)
        if not oss_service.is_enabled():
            return None
        return await run_blocking(oss_service.upload_file, str(local_path))
    except Exception:  # noqa: BLE001 - 云端备份失败不能让图片生成失败
        logger.warning("画布图片上传 OSS 失败：%s", local_path, exc_info=True)
        return None


def _reference_urls(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    """将图片参考资产转换为可由视频提交层上传 OSS 的受控路径。

    一个输入只对应一张图：资产有效就用资产的地址（优先云端链接），否则才用复用结果 / 配置里的地址。
    同一张图的 云端链接 与 /static 本地地址 形式不同，如果都收进来会被当成两张，参考图数量凭空翻倍。
    """
    urls: list[str] = []
    for value in inputs:
        chosen = ""
        asset_id = value.get("asset_id")
        if isinstance(asset_id, int):
            asset = db.get(VideoAsset, asset_id)
            if asset and asset.story_id == canvas.story_id and asset.status == "active" and _asset_media_kind(asset) == "image":
                # 生成时已上传到 OSS 的图直接用公网地址，提交视频时不必重复上传
                meta = getattr(asset, "meta_json", None) or {}
                oss_url = str(meta.get("oss_url") or "").strip()
                chosen = oss_url if oss_url.lower().startswith(("http://", "https://")) else _asset_static_url(asset.file_path)
        if not chosen:
            reused_url = str(value.get("_media_url") or "").strip()
            if reused_url and not _is_video_media_url(reused_url):
                chosen = reused_url
        if not chosen:
            configured_url = str(value.get("url") or "").strip()
            if configured_url.startswith("/static/"):
                configured_url = _asset_static_url(configured_url)
            if configured_url and not _is_video_media_url(configured_url) and (
                configured_url.lower().startswith(("http://", "https://"))
                or configured_url.startswith(("/static/manga/", "/static/video/"))
            ):
                chosen = configured_url
        if chosen:
            urls.append(chosen)
    return list(dict.fromkeys(urls))


def _require_audio_reference_capability(capabilities: dict[str, Any] | None, count: int) -> None:
    """未声明 limits.max_reference_audios 的模型不接受音频参考，禁止臆测上游协议。"""
    limits = capabilities.get("limits") if isinstance(capabilities, dict) else None
    limit = limits.get("max_reference_audios") if isinstance(limits, dict) else None
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise RuntimeError("所选视频模型未声明音频参考能力，请更换支持音频参考的模型，或断开视频节点上的音频连线")
    if count > limit:
        raise RuntimeError(f"视频节点连接了 {count} 个音频，但当前模型最多支持 {limit} 个")


def _audio_reference_urls(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    """把音频节点输出转换为可上传 OSS 的受控地址；只接受本作品内有效的音频资产。"""
    urls: list[str] = []
    for value in inputs:
        asset_id = value.get("asset_id")
        asset = db.get(VideoAsset, asset_id) if isinstance(asset_id, int) else None
        if not asset or asset.story_id != canvas.story_id or asset.status != "active" or _asset_media_kind(asset) != "audio":
            raise RuntimeError("音频参考已失效或不属于当前作品，请重新选择音频文件")
        urls.append(_asset_static_url(asset.file_path))
    return list(dict.fromkeys(urls))


async def _external_audio_reference_urls(inputs: list[dict[str, Any]], canvas: VideoCanvas, db) -> list[str]:
    """音频参考统一转换为 OSS 公网外链，转换失败即停止提交。"""
    urls = _audio_reference_urls(inputs, canvas, db)
    if not urls:
        return []
    external = await video_api_service.prepare_video_reference_urls(urls)
    if any(not url.lower().startswith(("http://", "https://")) for url in external):
        raise RuntimeError("音频参考未能转换为 OSS 公网地址")
    return external


async def _external_video_reference_urls(
    inputs: list[dict[str, Any]],
    canvas: VideoCanvas,
    db,
    *,
    max_reference_images: int = 9,
) -> list[str]:
    """将画布视频参考图统一转换为 OSS 外链，并按稳定顺序限制上限。"""
    # 只有资产还没有云端链接才兜底上传一次，并把链接记回资产；之后再引用同一张图直接复用，不再上传。
    await _ensure_asset_oss_urls(inputs, canvas, db)
    urls = list(dict.fromkeys(_reference_urls(inputs, canvas, db)))
    if max_reference_images < 0:
        raise RuntimeError("视频参考图上限无效")
    allowed = min(9, max_reference_images)
    if len(urls) > allowed:
        raise RuntimeError(
            f"视频节点需要 {len(urls)} 张参考图，但当前最多允许 {allowed} 张；"
            "请在节点中移除多余参考图后再提交"
        )
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


def _validated_video_duration(config: dict[str, Any], model: str, capabilities: dict[str, Any] | None) -> int:
    """在计费前检查内容时间预算，禁止缩短单元而保留原对白和动作。"""
    requested = config.get("duration_seconds")
    if requested is None:
        requested = 6 if config.get("duration_policy") == "director_dynamic" else 15
    if isinstance(requested, bool) or not isinstance(requested, (int, float)) or not math.isfinite(requested) or requested <= 0:
        raise RuntimeError("视频单元时长无效，请填写大于零的秒数")
    effective = normalize_video_duration(requested, model=model, capabilities=capabilities)
    if effective < requested:
        # 可向上选择档位容纳完整内容；只有超出最大容量时才要求重拆。
        longer_options = [option for option in _duration_options(capabilities) if requested <= option <= 60]
        if longer_options:
            effective = min(longer_options)
    if effective < requested:
        raise RuntimeError(
            f"视频单元需要 {requested:g} 秒，当前模型档位仅能匹配 {effective} 秒。"
            "为避免对白和动作被挤压，请先拆分该单元或选择支持所需时长的模型；原方案已保留。"
        )
    return effective


def _execution_snapshot(run_node: VideoCanvasRunNode) -> dict[str, Any]:
    """仅恢复服务端真正执行过的快照，初始用户配置不能伪造上游任务或计费事件。"""
    snapshot = run_node.input_snapshot_json
    return dict(snapshot) if getattr(run_node, "started_at", None) and isinstance(snapshot, dict) else {}


def _reuse_snapshot_validator(snapshot: dict[str, Any], node: dict[str, Any], canvas: VideoCanvas, db, _source_run: Any, _source_node: Any) -> bool:
    """Validate and normalize a cross-run generated media asset before reuse."""
    asset_id = snapshot.get("asset_id")
    if not isinstance(asset_id, int) or isinstance(asset_id, bool) or asset_id <= 0:
        return False
    node_type = str(node.get("type") or "")
    media_kind = "video" if node_type in {"video", "video_generation"} else "image"
    try:
        asset = _require_canvas_asset(db, canvas, asset_id, media_kind)
    except Exception:
        return False
    root = VIDEO_OUTPUTS if media_kind == "video" else MANGA_OUTPUTS
    prefix = "/static/video" if media_kind == "video" else "/static/manga"
    # Do not trust paths/URLs copied from an old JSON snapshot.  Resolve them
    # from the currently active, story-owned asset row instead.
    snapshot.update({
        "asset_id": asset.id,
        "file_path": asset.file_path,
        "url": _static_url(asset.file_path, root, prefix),
        "reused": True,
    })
    return True


def _prepare_reusable_outputs(
    graph: dict[str, Any],
    run: VideoCanvasRun,
    run_nodes: dict[str, VideoCanvasRunNode],
    canvas: VideoCanvas,
    db,
    rerun_node_ids: Iterable[str] | None,
) -> dict[str, dict[str, Any]]:
    """Resolve prior successful outputs and mark current run nodes succeeded."""
    rerun_ids = set(str(item) for item in (rerun_node_ids or ()) if str(item).strip())

    # A worker-local graph copy may contain markers written by the stage
    # gateway.  Clear invalid markers and every explicitly rerun media output;
    # never mutate the immutable VideoCanvasVersion row.
    invalidated = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        config = (node.get("data") or {}).get("config") if isinstance(node.get("data"), dict) else None
        if not isinstance(config, dict):
            continue
        if node_id in rerun_ids and str(node.get("type") or "") in REUSABLE_OUTPUT_NODE_TYPES:
            config.pop("asset_id", None)
            config.pop("_reused_definition_hash", None)
            invalidated.add(node_id)
    invalidated.update(clear_invalid_reuse_markers(graph, rerun_ids))

    protected: set[str] = set()
    for node_id, run_node in run_nodes.items():
        snapshot = _execution_snapshot(run_node)
        provider_job = snapshot.get("provider_job")
        if (
            isinstance(provider_job, dict) and provider_job.get("provider_job_id")
        ) or snapshot.get("billing_usage_event_id") or getattr(run_node, "billing_usage_event_id", None):
            # A persisted provider task or reservation always wins over a
            # cross-run cache hit; recovery must poll/settle that same task.
            protected.add(node_id)

    reusable = find_reusable_outputs(
        graph,
        canvas.id,
        db,
        rerun_ids,
        current_run_id=run.id,
        protected_node_ids=protected | invalidated,
        output_validator=lambda snapshot, node, source_run, source_node: _reuse_snapshot_validator(
            snapshot, node, canvas, db, source_run, source_node
        ),
    )
    for node_id, snapshot in reusable.items():
        run_node = run_nodes.get(node_id)
        if not run_node or run_node.status == "succeeded":
            continue
        # A late provider snapshot may have appeared after candidate lookup;
        # check again immediately before adopting the cached output.
        if node_id in protected:
            continue
        now = _now()
        run_node.input_snapshot_json = {
            **(_execution_snapshot(run_node) or {}),
            "config": (run_node.input_snapshot_json or {}).get("config", {}),
            "reuse": {"source": "successful_canvas_run", "definition_hash": definition_hash(graph, node_id)},
        }
        run_node.output_snapshot_json = {**snapshot, "reused": True}
        run_node.status = "succeeded"
        run_node.error_message = None
        run_node.started_at = run_node.started_at or now
        run_node.completed_at = now
        run_node.billing_usage_event_id = None
        db.commit()
    return reusable


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
        # JSON columns are mutable; execute against a private copy so reuse
        # marker cleanup can never rewrite the immutable version snapshot.
        graph = deepcopy(version.graph_json or {})
        # 标记为“自动推荐”的视频节点：按当前时长 / 画幅 / 参考图数量重新推荐模型（用户在节点里改过时长也能跟上）
        from services.canvas_video_model import apply_auto_video_models

        apply_auto_video_models(graph, db, canvas.owner_user_id)
        node_map = {str(node.get("id")): node for node in graph.get("nodes") or [] if isinstance(node, dict)}
        _validate_runtime_graph(graph)
        run_nodes = {item.node_id: item for item in db.query(VideoCanvasRunNode).filter(VideoCanvasRunNode.run_id == run.id).order_by(VideoCanvasRunNode.attempt).all()}
        order = list((run.plan_json or {}).get("topological_order") or [])
        run_chapter_id = (run.plan_json or {}).get("chapter_id")
        if not isinstance(run_chapter_id, int):
            run_chapter_id = canvas.default_chapter_id
        image_runtime_default_model = image2_service.runtime_model()
        image_runtime_default_base_url = image2_service.runtime_base_url()
        outputs: dict[str, dict[str, Any]] = {}
        rerun_node_ids = resolve_rerun_node_ids(
            run,
            _task_context.get("rerun_node_ids"),
            _task_context,
        )
        if _run_cancelled_in_database(db, run):
            return _finish_cancelled_run(db, run)
        run.status = "running"
        run.error_message = None
        db.commit()

        # Adopt only outputs whose current graph definition matches a recent
        # successful run.  This happens before video capacity checks so a
        # reused clip cannot trigger a model lookup or a billing reservation.
        _prepare_reusable_outputs(
            graph,
            run,
            run_nodes,
            canvas,
            db,
            rerun_node_ids,
        )
        for node_id, run_node in run_nodes.items():
            if run_node.status == "succeeded" and isinstance(run_node.output_snapshot_json, dict):
                outputs[node_id] = run_node.output_snapshot_json

        # 先检查整次运行的容量，避免已付费生成参考图后才发现视频必须重拆。
        for node_id in order:
            node = node_map.get(node_id) or {}
            run_node = run_nodes.get(node_id)
            if not run_node or run_node.status == "succeeded" or node.get("type") not in {"video", "video_generation"}:
                continue
            config = dict((node.get("data") or {}).get("config") or {})
            if isinstance(config.get("asset_id"), int) or _trusted_import_media(node, canvas, db, "video"):
                continue
            provider_job = _execution_snapshot(run_node).get("provider_job")
            if isinstance(provider_job, dict) and provider_job.get("provider_job_id"):
                continue
            try:
                _validated_video_duration(config, _resolved_video_model(config, db, video_model), _video_model_capabilities(config, db))
            except RuntimeError as exc:
                run_node.status = "failed"
                run_node.error_message = str(exc)
                run_node.completed_at = _now()
                run.status = "failed"
                run.error_message = str(exc)
                run.completed_at = _now()
                _mark_remaining_nodes(db, run, status="blocked", reason="视频时长超过模型容量，请先调整方案")
                db.commit()
                raise

        for node_id in order:
            if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                return _finish_cancelled_run(db, run)
            node = node_map.get(node_id)
            run_node = run_nodes.get(node_id)
            if not node or not run_node:
                continue
            if node.get("type") in GENERATION_TYPES and run_node.status == "succeeded" and isinstance(run_node.output_snapshot_json, dict):
                outputs[node_id] = run_node.output_snapshot_json
                continue
            # 没有自带风格的生成节点使用画布风格，保证整部作品画风统一；节点自带风格优先。
            config = apply_canvas_style(str(node.get("type") or ""), (node.get("data") or {}).get("config") or {}, canvas_style(graph))
            input_groups = resolve_node_inputs(graph, node_id, outputs)
            # Keep the narrow legacy helper as an extension point for older
            # callers/tests that provide edge inputs without port handles.
            legacy_inputs = _node_inputs(graph, node_id, outputs)
            if str(node.get("type") or "") == "container" and legacy_inputs:
                input_groups["items"] = legacy_inputs
            elif not input_groups and legacy_inputs:
                input_groups = {"source": legacy_inputs}
            configured_references = _configured_reference_inputs(config, canvas, db)
            media_reference_inputs = [*input_groups.get("references", []), *input_groups.get("image", []), *configured_references]
            audio_reference_inputs = list(input_groups.get("audio", []))
            prompt_inputs = [
                *input_groups.get("prompt", []),
                *input_groups.get("text", []),
                *input_groups.get("source", []),
                *input_groups.get("screenplay", []),
                *input_groups.get("shot", []),
            ]
            inputs = [
                *prompt_inputs,
                *media_reference_inputs,
                *input_groups.get("videos", []),
                *input_groups.get("items", []),
            ]
            run_node.status = "running"
            run_node.error_message = None
            previous_snapshot = _execution_snapshot(run_node)
            run_node.started_at = _now()
            run_node.input_snapshot_json = {**previous_snapshot, "config": config, "inputs": inputs}
            db.commit()
            billing_ctx = None
            billing_event_id = None
            effective_image_api_key = image_api_key
            effective_video_api_key = video_api_key
            effective_video_base_url = video_base_url
            try:
                node_type = str(node.get("type") or "")
                provider_job = previous_snapshot.get("provider_job")
                provider_job = provider_job if isinstance(provider_job, dict) else {}
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
                    if modality == "video":
                        resolved_video_model = str(provider_job.get("model") or _resolved_video_model(config, db, video_model))
                        effective_duration = (
                            int(provider_job["duration_seconds"])
                            if provider_job.get("provider_job_id") and provider_job.get("duration_seconds")
                            else _validated_video_duration(config, resolved_video_model, _video_model_capabilities(config, db))
                        )
                    if modality == "video" and audio_reference_inputs:
                        # 音频参考能力必须由模型显式声明；计费预留之前就拦截，避免无谓占用积分。
                        _require_audio_reference_capability(_video_model_capabilities(config, db), len(audio_reference_inputs))
                    estimate = (
                        {"video_seconds": effective_duration}
                        if modality == "video"
                        else {"image_count": 1}
                    )
                    previous_event_id = previous_snapshot.get("billing_usage_event_id")
                    previous_event = db.get(AiUsageEvent, previous_event_id) if previous_event_id else None
                    if previous_event and previous_event.status not in {"failed", "refunded"}:
                        # 中断前的预留继续结算，已成功结算的事件不会再次扣款；
                        # 同时恢复当时冻结的模型渠道，避免恢复任务漂移到默认模型。
                        billing_event_id = previous_event.id
                        restored_model, restored_base_url, restored_api_key = _restore_usage_runtime(db, previous_event.id, modality)
                        if modality == "image" and restored_model:
                            image2_service.configure_runtime(base_url=restored_base_url or image_runtime_default_base_url, model=restored_model)
                            effective_image_api_key = restored_api_key or effective_image_api_key
                        elif modality == "video" and restored_model:
                            resolved_video_model = restored_model
                            effective_video_base_url = restored_base_url or effective_video_base_url
                            effective_video_api_key = restored_api_key or effective_video_api_key
                    else:
                        request_id = f"canvas:{run.id}:node:{run_node.id}:a:{run_node.attempt}"
                        if previous_event:
                            request_id += f":resume:{uuid.uuid4().hex}"
                        billing_ctx = begin_ai_call(
                            db,
                            user_id=canvas.owner_user_id,
                            modality=modality,
                            task_type=f"video_canvas.{node_type}",
                            model_id=config.get("model_id") if isinstance(config.get("model_id"), int) else None,
                            request_id=request_id,
                            story_id=canvas.story_id,
                            chapter_id=run_chapter_id,
                            estimate_kwargs=estimate,
                        )
                        billing_event_id = billing_ctx.usage_event_id
                        if modality == "image":
                            effective_image_api_key = getattr(billing_ctx, "api_key", None) or effective_image_api_key
                            image2_service.configure_runtime(base_url=getattr(billing_ctx, "base_url", None) or image_runtime_default_base_url, model=getattr(billing_ctx, "model_key", None) or image_runtime_default_model)
                        else:
                            effective_video_api_key = getattr(billing_ctx, "api_key", None) or effective_video_api_key
                            effective_video_base_url = getattr(billing_ctx, "base_url", None) or effective_video_base_url
                            resolved_video_model = getattr(billing_ctx, "model_key", None) or resolved_video_model
                    run_node.input_snapshot_json = {
                        **(run_node.input_snapshot_json or {}),
                        "billing_usage_event_id": billing_event_id,
                    }
                    run_node.billing_usage_event_id = billing_event_id
                    db.commit()
                if node_type not in GENERATION_TYPES:
                    if node_type == "container":
                        output = {"items": inputs}
                    elif node_type == "text":
                        text_value = str(config.get("content") or config.get("text") or config.get("story_summary") or "")
                        output = {"text": text_value, "content": text_value}
                        output.update({
                            key: value for key, value in config.items()
                            if key not in {"file_path", "existing_url", "asset_id", "reference_asset_ids"}
                        })
                    elif node_type == "audio":
                        if not isinstance(config.get("asset_id"), int):
                            raise RuntimeError("音频节点必须先上传或选择音频文件")
                        asset = _require_canvas_asset(db, canvas, config["asset_id"], "audio")
                        output = {"asset_id": asset.id, "file_path": asset.file_path, "url": _asset_static_url(asset.file_path), "media_kind": "audio"}
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
                        # 节点里可能残留旧的“统一视觉风格”等文字（老画布 / 旧分析结果）：生成前清掉，风格以当前的风格参考图为准
                        if str(config.get("asset_role") or "") == "character":
                            prompt = slim_character_prompt(prompt)
                        prompt = _apply_style_prompt(strip_style_text(prompt), config, inputs)
                        if not prompt:
                            raise RuntimeError("图像节点缺少提示词")
                        output_path = _node_output_path(MANGA_OUTPUTS, canvas.id, run.id, node_id, ".png")
                        reference_paths, reference_labels, reference_roles = [], [], []
                        for reference in style_anchors_first(media_reference_inputs):
                            paths = _local_reference_paths([reference], canvas, db)
                            asset = db.get(VideoAsset, reference.get("asset_id")) if isinstance(reference.get("asset_id"), int) else None
                            role = str((asset.meta_json or {}).get("asset_role") or "") if asset else "style"
                            if role not in {"character", "scene", "prop", "style"}:
                                role = {"character_reference": "character", "scene_reference": "scene", "prop_reference": "prop"}.get(asset.asset_type if asset else "", "style")
                            anchor = is_style_anchor(reference)
                            if anchor:
                                role = "style"
                            reference_paths.extend(paths)
                            reference_labels.extend([("画风参考" if anchor else (asset.name if asset else "画风参考"))] * len(paths))
                            reference_roles.extend([role] * len(paths))
                        if str(config.get("asset_role") or "") == "character":
                            prompt += CHARACTER_IDENTITY_SHEET_DIRECTIVE
                        elif str(config.get("asset_role") or "") == "scene":
                            prompt += SCENE_ASSET_DIRECTIVE
                        elif str(config.get("asset_role") or "") == "prop":
                            prompt += PROP_ASSET_DIRECTIVE
                        elif any(role == "character" for role in reference_roles):
                            names = "、".join(dict.fromkeys(label for label, role in zip(reference_labels, reference_roles) if role == "character" and label))
                            prompt += STORYBOARD_IDENTITY_DIRECTIVE.format(names=names or "各角色")
                        if any(is_style_anchor(reference) for reference in media_reference_inputs) and "style" in reference_roles:
                            prompt += STYLE_ANCHOR_DIRECTIVE
                        image_sizes = {"9:16": "1080x1920", "16:9": "1920x1080", "1:1": "1024x1024", "3:4": "1152x1536", "4:3": "1536x1152"}
                        if config.get("reference_mode") == "clean_single_frame":
                            prompt += "\n只生成一张完整的起始画面，无字幕、无边框、无文字、无分格；动作尚未完成，保留视频推进空间。"
                        # 节点选择的图片模型必须真正注入当前异步任务上下文，不能只停留在 config。
                        selected_image_model = _resolved_image_model(config, db, image_runtime_default_model)
                        image2_service.configure_runtime(base_url=image_runtime_default_base_url, model=selected_image_model)
                        saved_path = await image2_service.generate_reference_image(
                            prompt=prompt,
                            output_path=output_path,
                            api_key=effective_image_api_key,
                            size=str(config.get("size") or image_sizes.get(config.get("aspect_ratio"), "1920x1080")),
                            ref_image_paths=reference_paths or None,
                            ref_labels=reference_labels or None,
                            ref_roles=reference_roles or None,
                            ref_type=str(config.get("asset_role") or "storyboard"),
                            prefer_local=True,
                        )
                        is_storyboard_sheet = config.get("reference_mode") == "storyboard_sheet" and bool(config.get("sheet_panels"))
                        if is_storyboard_sheet:
                            # 每格左上角由程序写上“序号 · 时间段”，视频模型按它对照；图片模型自己画字容易出错
                            from services.blocking import run_blocking
                            from services.canvas_storyboard_sheet import stamp_sheet_labels

                            await run_blocking(stamp_sheet_labels, str(saved_path), list(config.get("sheet_panels") or []))
                        asset_role_value = str(config.get("asset_role") or "")
                        asset_labeled = False
                        if asset_role_value in {"character", "scene", "prop"}:
                            # 资产图下方加一条名称标注（如“角色：萧炎”）：标注是程序写的，图片模型自己画字常出错；
                            # 这样不论是用户翻看、当作参考图，还是被视频模型读取，都能一眼认出这张图属于谁。
                            from services.blocking import run_blocking

                            asset_labeled = await run_blocking(stamp_asset_label_bar, str(saved_path), reference_label_text(asset_role_value, str(config.get("asset_name") or "")))
                        stored_path = _relative_path(str(saved_path), MANGA_OUTPUTS)
                        # 标注/贴字都已写完，先把画布节点用的缩略图生成好：节点拿到结果时缩略图已就绪，首屏不用等转换。
                        from services import media_derivatives

                        await media_derivatives.prewarm(saved_path, (MANGA_OUTPUTS, VIDEO_OUTPUTS))
                        asset_kind = {"character": "character_reference", "scene": "scene_reference", "prop": "prop_reference"}.get(str(config.get("asset_role")), "storyboard_frame")
                        asset = VideoAsset(story_id=canvas.story_id, chapter_id=run_chapter_id, asset_type=asset_kind, name=str(config.get("asset_name") or f"画布 {canvas.name} - {node_id}"), file_path=stored_path, provider="image2", prompt=prompt, meta_json={"canvas_id": canvas.id, "run_id": run.id, "node_id": node_id, "asset_role": config.get("asset_role"), "storyboard_sheet": is_storyboard_sheet, "labeled": asset_labeled}, usage_scope="story_shared")
                        db.add(asset)
                        db.flush()
                        # 生成完成就把原图直传 OSS 并记下外链：之后提交视频、再次被引用都先查这个外链，不会重复上传。
                        # 本地原图仍是主副本（画布展示、图生图参考都读本地）。
                        if oss_url := await _upload_generated_image_to_oss(saved_path):
                            asset.meta_json = {**(asset.meta_json or {}), "oss_url": oss_url}
                        output = {"asset_id": asset.id, "file_path": stored_path, "url": _static_url(stored_path, MANGA_OUTPUTS, "/static/manga")}
                elif node_type in {"video", "video_generation"}:
                    if trusted_import_url:
                        output = {"url": trusted_import_url, "_media_url": trusted_import_url, "reused": True, "duration_seconds": config.get("duration_seconds")}
                    elif isinstance(config.get("asset_id"), int):
                        asset = _require_canvas_asset(db, canvas, config["asset_id"], "video")
                        output = {"asset_id": asset.id, "file_path": asset.file_path, "url": _static_url(asset.file_path, VIDEO_OUTPUTS, "/static/video"), "reused": True}
                    else:
                        prompt = str(config.get("prompt") or "").strip() or _first_input_text(inputs, ("video_prompt", "text", "content", "storyboard_prompt", "prompt", "screenplay"))
                        plain_video_prompt = strip_style_text(prompt)
                        prompt = _apply_style_prompt(plain_video_prompt, config, inputs)
                        if not prompt or not effective_video_api_key:
                            raise RuntimeError("视频节点缺少提示词或 Video API Key")
                        # 时长已在计费前校验；恢复任务使用首次提交时冻结的模型和时长。
                        duration_policy = str(config.get("duration_policy") or "")
                        if duration_policy == "director_dynamic":
                            prompt = _append_director_continuity(prompt, config)
                        provider_job_id = provider_job.get("provider_job_id")
                        job_base_url = str(provider_job.get("base_url") or effective_video_base_url)
                        if not provider_job_id:
                            video_capabilities = _video_model_capabilities(config, db)
                            limits = video_capabilities.get("limits") if isinstance(video_capabilities, dict) else None
                            configured_limit = limits.get("max_reference_images") if isinstance(limits, dict) else None
                            max_reference_images = min(9, configured_limit) if isinstance(configured_limit, int) and configured_limit >= 0 else 9
                            # 画风锚点紧跟分镜首帧之后；参考图超过上限时先丢画风锚点（提示词里仍有画风文字），不让整条视频任务失败
                            video_reference_inputs = order_video_references(media_reference_inputs, max_reference_images)
                            reference_images = await _external_video_reference_urls(
                                video_reference_inputs,
                                canvas,
                                db,
                                max_reference_images=max_reference_images,
                            )
                            reference_audios = await _external_audio_reference_urls(audio_reference_inputs, canvas, db)
                            # 参考图按输入顺序截断到上游上限，图片序号与提示词里的说明一一对应。
                            reference_entries = video_reference_entries(video_reference_inputs, db)[: len(reference_images)]
                            # 与原视频工作流一致：画风由风格参考图控制，提示词里不再重复风格文字；只有没带上风格图时才退回文字
                            base_prompt = plain_video_prompt if any(role == "style" for role, _ in reference_entries) else prompt
                            input_mode = "image_to_video" if reference_images else "text_to_video"
                            requested_seed = config.get("seed")
                            seed = requested_seed if isinstance(requested_seed, int) and not isinstance(requested_seed, bool) else None
                            capability_wire = video_capabilities.get("wire") if isinstance(video_capabilities, dict) else None
                            seed_supported = provider_job.get("seed_supported") if provider_job else None
                            if seed_supported is None:
                                seed_supported = str(config.get("provider") or "").strip().lower() == "comfyui" or (isinstance(capability_wire, dict) and bool(capability_wire.get("seed_field")))
                            run_node.input_snapshot_json = {
                                **(run_node.input_snapshot_json or {}),
                                "video_submission": {
                                    "reference_images": list(reference_images),
                                    "reference_audios": list(reference_audios),
                                    "reference_asset_ids": [item.get("asset_id") for item in inputs if isinstance(item.get("asset_id"), int)],
                                    "input_mode": input_mode,
                                    "seed_requested": seed,
                                    "seed_supported": bool(seed_supported),
                                    "seed_forwarded": bool(seed is not None and seed_supported),
                                    "warning": "当前视频适配器未声明 seed 能力，已保留请求但不会写入上游" if seed is not None and not seed_supported else None,
                                },
                            }
                            db.commit()
                            async def _submit_once(images: list[str], final_prompt: str, mode: str):
                                return await submit_video_job(
                                    shot_id=run_node.id,
                                    provider="canvas",
                                    model=resolved_video_model,
                                    prompt=final_prompt,
                                    negative_prompt=str(config.get("negative_prompt") or ""),
                                    duration_seconds=effective_duration,
                                    aspect_ratio=str(config.get("aspect_ratio") or "16:9"),
                                    size=str(config.get("size") or "720P"),
                                    reference_images=images,
                                    reference_audios=reference_audios or None,
                                    input_mode=mode,
                                    seed=seed,
                                    api_key=effective_video_api_key,
                                    base_url=job_base_url,
                                    video_capabilities=video_capabilities,
                                )

                            submission, reference_images, prompt = await submit_with_reference_fallback(
                                _submit_once, list(reference_images), reference_entries, base_prompt,
                                (video_capabilities.get("wire") or {}).get("reference_token") or "图片{n}" if isinstance(video_capabilities, dict) and isinstance(video_capabilities.get("wire"), dict) else "图片{n}",
                                list(config.get("sheet_panels") or []) if config.get("reference_mode") == "storyboard_sheet" else None,
                            )
                            input_mode = "image_to_video" if reference_images else "text_to_video"
                            if len(reference_images) < len(reference_entries):
                                run_node.input_snapshot_json = {
                                    **(run_node.input_snapshot_json or {}),
                                    "video_submission": {
                                        **((run_node.input_snapshot_json or {}).get("video_submission") or {}),
                                        "reference_images": list(reference_images),
                                        "reference_degraded_from": len(reference_entries),
                                        "warning": f"上游拒绝了全部 {len(reference_entries)} 张参考图，已自动减少到 {len(reference_images)} 张后提交成功（保留分镜图和靠前的角色）",
                                    },
                                }
                            provider_job_id = submission["provider_job_id"]
                            # 一拿到上游 ID 就持久化，轮询失败后恢复同一任务，不重复付费提交。
                            provider_job = {"provider_job_id": provider_job_id, "model": resolved_video_model, "duration_seconds": effective_duration, "base_url": job_base_url, "input_mode": input_mode, "seed": seed, "reference_images": list(reference_images)}
                            run_node.input_snapshot_json = {**(run_node.input_snapshot_json or {}), "provider_job": provider_job}
                            db.commit()
                        # 视频没有总等待上限：一直轮询到上游明确返回成功或失败为止（用户取消 / 服务重启除外）。
                        # 间隔随等待时间拉长，长视频不会给上游造成压力；偶发的查询失败（网络抖动、上游 5xx）只重试，
                        # 连续失败很多次才放弃，且放弃后仍可用「恢复执行」继续查同一个上游任务。
                        poll_started = time.monotonic()
                        consecutive_errors = 0
                        while True:
                            if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                                raise asyncio.CancelledError()
                            try:
                                status = await query_job_status("canvas", provider_job_id, api_key=effective_video_api_key, base_url=job_base_url, model=resolved_video_model)
                                consecutive_errors = 0
                            except asyncio.CancelledError:
                                raise
                            except Exception as poll_exc:  # noqa: BLE001 - 单次查询失败不代表上游任务失败
                                consecutive_errors += 1
                                logger.warning("视频任务状态查询失败（连续 %s 次）job=%s：%s", consecutive_errors, provider_job_id, poll_exc)
                                if consecutive_errors >= VIDEO_POLL_MAX_CONSECUTIVE_ERRORS:
                                    raise RuntimeError(f"连续 {consecutive_errors} 次查询上游视频任务状态失败，已暂停等待；上游任务仍在，可点击「恢复执行」继续查询。最后一次错误：{poll_exc}") from poll_exc
                                await asyncio.sleep(VIDEO_POLL_INTERVAL_SECONDS)
                                continue
                            if status["status"] == "succeeded":
                                break
                            if status["status"] in {"failed", "cancelled"}:
                                raise RuntimeError(
                                    "原上游视频任务已失败或取消，恢复执行不会重复提交。"
                                    "如需重新生成，请新建运行并确认费用。详情："
                                    + str(status.get("error") or status["status"])
                                )
                            await asyncio.sleep(_video_poll_interval(time.monotonic() - poll_started))
                        result = await fetch_job_result("canvas", provider_job_id, run_node.id, api_key=effective_video_api_key, base_url=job_base_url, model=resolved_video_model)
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
                    clips: list[dict[str, Any]] = []
                    for item in input_groups.get("videos", []):
                        path = await _canvas_clip_path(item, canvas, db)
                        if path:
                            clips.append({"video_path": path, "duration_seconds": item.get("duration_seconds") or 0})
                    output_path = _node_output_path(VIDEO_OUTPUTS, canvas.id, run.id, node_id, ".mp4")
                    if len(clips) != len(input_groups.get("videos", [])):
                        raise RuntimeError("合片输入存在缺失或无效的视频，不能跳过镜头交付")
                    result = await compile_project(str(output_path), clips, resolution=str(config.get("resolution") or "1280x720"), fps=int(config.get("fps") or 24), burn_subtitle=bool(config.get("subtitle_data")), subtitle_data=config.get("subtitle_data") or None, strict=True)
                    if result.get("status") != "compiled" or not Path(str(result.get("output_path") or "")).is_file():
                        raise RuntimeError("成片合成未返回有效视频，已停止交付")
                    stored_path = _relative_path(str(result["output_path"]), VIDEO_OUTPUTS)
                    final_asset = VideoAsset(story_id=canvas.story_id, chapter_id=run_chapter_id, asset_type="video_clip", name=f"画布 {canvas.name} - 完整成片", file_path=stored_path, provider="ffmpeg", meta_json={"canvas_id": canvas.id, "run_id": run.id, "node_id": node_id, "role": "final_cut", "clip_count": len(clips), "has_audio": result.get("has_audio")}, usage_scope="story_shared")
                    db.add(final_asset)
                    db.flush()
                    output = {"asset_id": final_asset.id, "file_path": stored_path, "url": _static_url(stored_path, VIDEO_OUTPUTS, "/static/video"), "duration_seconds": result.get("duration_seconds"), "clip_count": len(clips), "has_audio": result.get("has_audio"), "quality_status": "technical_pass_needs_creative_review"}
                _validate_runtime_output_contract(graph, node_id, output)
                if task_manager.is_cancellation_requested(task_id) or _run_cancelled_in_database(db, run):
                    raise asyncio.CancelledError()
                outputs[node_id] = output
                if billing_event_id:
                    complete_ai_call_by_usage_event(
                        db,
                        billing_event_id,
                        success=True,
                        image_count=1 if node_type in {"image", "image_generation", "storyboard"} else 0,
                        video_seconds=float(output.get("duration_seconds") or config.get("duration_seconds") or 0) if node_type in {"video", "video_generation"} else 0,
                        commit=False,
                    )
                    run_node.billing_usage_event_id = None
                run_node.output_snapshot_json = output
                run_node.status = "succeeded"
                run_node.completed_at = _now()
                db.commit()
            except asyncio.CancelledError:
                if billing_event_id:
                    complete_ai_call_by_usage_event(db, billing_event_id, success=False, error_code="cancelled")
                    run_node.billing_usage_event_id = None
                run_node.status = "cancelled"
                run_node.completed_at = _now()
                run.status = "cancelled"
                run.completed_at = _now()
                _mark_remaining_nodes(db, run, status="cancelled")
                db.commit()
                raise
            except Exception as exc:
                if billing_event_id:
                    complete_ai_call_by_usage_event(db, billing_event_id, success=False, error_code=type(exc).__name__)
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
