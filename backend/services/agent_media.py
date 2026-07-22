"""Agent 附件的安全校验、持久化和多模态消息构建。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from models import AgentAttachment

MEDIA_ROOT = Path(__file__).resolve().parent.parent / "manga_outputs" / "agent_attachments"
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 40_000_000
MAX_VIDEO_DURATION = 300.0
VIDEO_FRAME_COUNT = 6
MAX_MULTIMODAL_BYTES = 10 * 1024 * 1024
_SIGNING_SECRET = (os.getenv("AGENT_ATTACHMENT_SIGNING_SECRET") or os.getenv("JWT_SECRET") or secrets.token_urlsafe(32)).encode("utf-8")
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
ALLOWED_TEXT_SUFFIXES = {".txt", ".md"}
ALLOWED_DOCUMENT_SUFFIXES = {".pdf", ".docx"}


def _run_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, check=True, text=True, timeout=timeout, encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(503, "服务器未安装 FFmpeg，暂时无法解析视频附件") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(400, "视频解析超时，请上传更短或体积更小的视频") from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(400, "上传文件不是可解析的视频") from exc


def _probe_video(path: Path) -> dict[str, Any]:
    result = _run_command(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        timeout=30,
    )
    try:
        payload = json.loads(result.stdout)
        duration = float(payload.get("format", {}).get("duration") or 0)
        video_stream = next(item for item in payload.get("streams", []) if item.get("codec_type") == "video")
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
    except (ValueError, TypeError, StopIteration, json.JSONDecodeError) as exc:
        raise HTTPException(400, "上传文件缺少有效的视频轨道") from exc
    if duration <= 0 or duration > MAX_VIDEO_DURATION:
        raise HTTPException(400, "视频时长必须在 5 分钟以内")
    return {"duration": round(duration, 3), "width": width, "height": height}


def _extract_video_frames(path: Path, output_dir: Path, duration: float) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    positions = [duration * ratio for ratio in (0.03, 0.18, 0.36, 0.55, 0.74, 0.92)]
    frames: list[str] = []
    for index, position in enumerate(positions, start=1):
        target = output_dir / f"frame_{index:02d}.jpg"
        _run_command(
            ["ffmpeg", "-y", "-ss", f"{position:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(target)],
            timeout=45,
        )
        if target.is_file() and target.stat().st_size > 0:
            frames.append(str(target))
    if not frames:
        raise HTTPException(400, "未能从视频中提取有效关键帧")
    return frames


def _inspect_image(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
    except Exception as exc:
        raise HTTPException(400, "上传文件不是有效图片") from exc
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(415, "仅支持 JPG、PNG、WebP 或 GIF 图片")
    if width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE or width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(400, "图片尺寸过大")
    return ALLOWED_IMAGE_FORMATS[image_format], {"width": width, "height": height, "media_kind": "image"}


def _extract_document_text(path: Path, suffix: str) -> str:
    if suffix in ALLOWED_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")[:20_000]
    if suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())[:20_000]
    return ""


async def save_attachment(
    upload: UploadFile,
    *,
    db: Session,
    owner_user_id: int,
    story_id: int,
) -> dict[str, Any]:
    original_name = Path(upload.filename or "附件").name[:255]
    suffix = Path(original_name).suffix.lower()
    allowed_suffixes = set(ALLOWED_IMAGE_FORMATS.values()) | {".jpeg"} | ALLOWED_VIDEO_SUFFIXES | ALLOWED_TEXT_SUFFIXES | ALLOWED_DOCUMENT_SUFFIXES
    if suffix not in allowed_suffixes:
        raise HTTPException(415, "仅支持图片、MP4/WebM/MOV、TXT/Markdown、PDF 或 DOCX 文件")

    attachment_id = secrets.token_urlsafe(24)
    target_dir = MEDIA_ROOT / f"user_{owner_user_id}" / f"story_{story_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(prefix=f"{attachment_id}_", suffix=".tmp", dir=target_dir)
    os.close(file_descriptor)
    temp_path = Path(temp_name)
    total = 0
    try:
        with temp_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_FILE_SIZE:
                    raise HTTPException(413, "附件不能超过 50MB")
                target.write(chunk)
        if total == 0:
            raise HTTPException(400, "附件不能为空")

        metadata: dict[str, Any] = {}
        content_type = (upload.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream").lower()
        final_suffix = suffix
        if suffix in set(ALLOWED_IMAGE_FORMATS.values()) | {".jpeg"}:
            final_suffix, metadata = await asyncio.to_thread(_inspect_image, temp_path)
            content_type = mimetypes.guess_type(f"file{final_suffix}")[0] or content_type
        elif suffix in ALLOWED_VIDEO_SUFFIXES:
            metadata = await asyncio.to_thread(_probe_video, temp_path)
            metadata["media_kind"] = "video"
            frames_dir = target_dir / f"{attachment_id}_frames"
            metadata["frame_paths"] = await asyncio.to_thread(_extract_video_frames, temp_path, frames_dir, metadata["duration"])
        else:
            metadata = {"media_kind": "document", "text_excerpt": await asyncio.to_thread(_extract_document_text, temp_path, suffix)}

        final_path = target_dir / f"{attachment_id}{final_suffix}"
        temp_path.replace(final_path)
        attachment = AgentAttachment(
            id=attachment_id,
            owner_user_id=owner_user_id,
            story_id=story_id,
            original_name=original_name,
            content_type=content_type,
            file_size=total,
            storage_path=str(final_path),
            metadata_json=metadata,
        )
        db.add(attachment)
        db.commit()
        return serialize_attachment(attachment)
    except Exception:
        db.rollback()
        raise
    finally:
        await upload.close()
        temp_path.unlink(missing_ok=True)


def serialize_attachment(attachment: AgentAttachment) -> dict[str, Any]:
    metadata = attachment.metadata_json if isinstance(attachment.metadata_json, dict) else {}
    return {
        "id": attachment.id,
        "filename": attachment.original_name,
        "content_type": attachment.content_type,
        "size": attachment.file_size,
        "media_kind": metadata.get("media_kind", "document"),
        "duration": metadata.get("duration"),
        "frame_count": len(metadata.get("frame_paths") or []),
        "url": None,
    }


def create_access_token(attachment_id: str, frame_index: int = 0, ttl_seconds: int = 1800) -> str:
    expires_at = int(time.time()) + ttl_seconds
    message = f"{attachment_id}:{frame_index}:{expires_at}".encode("utf-8")
    signature = hmac.new(_SIGNING_SECRET, message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def resolve_content_path(
    *,
    db: Session,
    attachment_id: str,
    token: str,
    frame_index: int = 0,
) -> tuple[Path, str]:
    try:
        expires_text, signature = token.split(".", 1)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        raise HTTPException(401, "附件访问凭证无效")
    message = f"{attachment_id}:{frame_index}:{expires_at}".encode("utf-8")
    expected = hmac.new(_SIGNING_SECRET, message, hashlib.sha256).hexdigest()
    if expires_at < int(time.time()) or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "附件访问凭证无效或已过期")
    attachment = db.get(AgentAttachment, attachment_id)
    if not attachment:
        raise HTTPException(404, "附件不存在")
    metadata = attachment.metadata_json if isinstance(attachment.metadata_json, dict) else {}
    if frame_index:
        frame_paths = list(metadata.get("frame_paths") or [])
        if frame_index < 1 or frame_index > len(frame_paths):
            raise HTTPException(404, "视频关键帧不存在")
        path = Path(frame_paths[frame_index - 1]).resolve()
        content_type = "image/jpeg"
    else:
        path = Path(attachment.storage_path).resolve()
        content_type = attachment.content_type
    expected_root = (MEDIA_ROOT / f"user_{attachment.owner_user_id}" / f"story_{attachment.story_id}").resolve()
    if not path.is_relative_to(expected_root) or not path.is_file():
        raise HTTPException(404, "附件文件已失效")
    return path, content_type


def resolve_attachments(
    attachment_ids: list[str] | None,
    *,
    db: Session,
    owner_user_id: int,
    story_id: int,
    conversation_id: int,
) -> list[dict[str, Any]]:
    normalized_ids = list(dict.fromkeys(str(item).strip() for item in attachment_ids or [] if str(item).strip()))
    if len(normalized_ids) > 5:
        raise HTTPException(400, "一次最多使用 5 个附件")
    if not normalized_ids:
        return []
    records = db.query(AgentAttachment).filter(AgentAttachment.id.in_(normalized_ids)).all()
    by_id = {item.id: item for item in records}
    result: list[dict[str, Any]] = []
    for attachment_id in normalized_ids:
        attachment = by_id.get(attachment_id)
        if not attachment or attachment.owner_user_id != owner_user_id or attachment.story_id != story_id:
            raise HTTPException(404, "附件不存在或无权访问")
        if attachment.conversation_id not in (None, conversation_id):
            raise HTTPException(409, "附件已经绑定到其他对话")
        path = Path(attachment.storage_path).resolve()
        expected_root = (MEDIA_ROOT / f"user_{owner_user_id}" / f"story_{story_id}").resolve()
        if not path.is_relative_to(expected_root) or not path.is_file():
            raise HTTPException(404, "附件文件已失效")
        attachment.conversation_id = conversation_id
        metadata = attachment.metadata_json if isinstance(attachment.metadata_json, dict) else {}
        result.append({
            **serialize_attachment(attachment),
            "path": str(path),
            "text_excerpt": metadata.get("text_excerpt", ""),
            "frame_paths": list(metadata.get("frame_paths") or []),
        })
    db.commit()
    return result


def multimodal_content(text: str, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    total_bytes = 0

    def image_data_url(path: str, content_type: str) -> str:
        nonlocal total_bytes
        source = Path(path)
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((1600, 1600))
            output = BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
        encoded_bytes = output.getvalue()
        total_bytes += len(encoded_bytes)
        if total_bytes > MAX_MULTIMODAL_BYTES:
            raise HTTPException(413, "附件视觉输入总量过大，请减少附件数量或压缩图片")
        return f"data:image/jpeg;base64,{base64.b64encode(encoded_bytes).decode('ascii')}"

    for item in attachments:
        media_kind = item.get("media_kind")
        if media_kind == "image":
            content.append({"type": "image_url", "image_url": {"url": image_data_url(item["path"], item["content_type"])}})
        elif media_kind == "video":
            frame_paths = item.get("frame_paths") or []
            content.append({"type": "text", "text": f"以下 {len(frame_paths)} 张图按时间顺序取自视频《{item['filename']}》。请据此反推视频内容、镜头运动、节奏、转场、对白，并输出可编辑的分镜脚本。"})
            for frame_path in frame_paths:
                content.append({"type": "image_url", "image_url": {"url": image_data_url(frame_path, "image/jpeg")}})
        elif item.get("text_excerpt"):
            content.append({"type": "text", "text": f"[文件《{item['filename']}》内容]\n{item['text_excerpt']}"})
        else:
            content.append({"type": "text", "text": f"[文件《{item['filename']}》] 当前模型无法直接读取该格式，请结合用户说明进行处理。"})
    return content
