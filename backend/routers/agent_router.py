import asyncio
import datetime
import json
import logging
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask as ResponseBackgroundTask

from database import SessionLocal, get_db
from models import AgentConversation, AgentConversationMessage, AgentPendingChange, Chapter, ChapterVideoShot, ChapterVideoWorkflow, MangaImage, Story
from schemas import AgentChatIn, AgentConversationCreateIn, AgentConversationOut, AgentConversationSummaryOut
from services.agent_service import (
    AgentPendingChangeKey,
    _chapter_storyboard_text,
    _parse_scenes_text,
    _scenes_file_lock,
    _scenes_path,
    _set_chapter_storyboard_scenes,
    _write_scenes_text_atomic,
    agent_pending_change_store,
    agent_service,
    normalize_agent_mode,
)
from services.agent_media import _extract_video_frames, _probe_video
from services.errors import public_error_message
from services.redaction import redact_sensitive_text
from services.agent_media import multimodal_content, resolve_attachments, save_attachment
from services.media_locator import ensure_local_media_path

logger = logging.getLogger("agent_router")

router = APIRouter(prefix="/api/stories/{story_id}/agent")

_main = sys.modules.get("main") or sys.modules.get("__main__")
if _main is None:
    raise RuntimeError("Unable to locate main module; ensure the app starts from main.py")

_require_user = _main._require_user
_require_story_for_user = _main._require_story_for_user
_user_deepseek_api_key = _main._user_deepseek_api_key
_release_db_transaction = _main._release_db_transaction
_check_and_consume_advanced_text_quota = _main._check_and_consume_advanced_text_quota
_detach_pending_platform_points = _main._detach_pending_platform_points
_finish_streaming_platform_points = _main._finish_streaming_platform_points
_build_framework_context = _main._build_framework_context


@router.post("/attachments")
async def upload_agent_attachments(
    story_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    if len(files) > 5:
        raise HTTPException(400, "一次最多上传 5 个附件")
    attachments = []
    for item in files:
        attachments.append(await save_attachment(item, db=db, owner_user_id=user.id, story_id=story_id))
    return {"attachments": attachments}


def _conversation_preview(content: str, limit: int = 72) -> str:
    normalized = " ".join((content or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def _conversation_title_from_text(content: str) -> str:
    normalized = " ".join((content or "").split()).strip()
    if not normalized:
        return "新对话"
    return normalized[:30]


def _settle_agent_response_content(
    streamed_parts: list[str],
    final_content: str = "",
    suffix: str = "",
) -> str:
    """以完整流式内容为准，避免最终事件只含最后一轮文本时截断回复。"""
    streamed_content = "".join(streamed_parts).strip()
    settled = streamed_content or str(final_content or "").strip()
    normalized_suffix = str(suffix or "").strip()
    if normalized_suffix:
        return f"{settled}\n\n{normalized_suffix}".strip()
    return settled


def _require_conversation(
    db: Session,
    *,
    conversation_id: int,
    story_id: int,
    user_id: int,
) -> AgentConversation:
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation or conversation.story_id != story_id or conversation.owner_user_id != user_id:
        raise HTTPException(404, "对话未找到")
    return conversation


def _pending_change_key_from_request(
    *,
    request: Request,
    db: Session,
    story_id: int,
    user_id: int,
    body: dict[str, Any] | None = None,
) -> AgentPendingChangeKey | None:
    raw_conversation_id = None
    if body is not None:
        raw_conversation_id = body.get("conversation_id")
    if raw_conversation_id in (None, ""):
        raw_conversation_id = request.query_params.get("conversation_id")
    try:
        conversation_id = int(raw_conversation_id or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "无效的对话 ID")
    if not conversation_id:
        return None
    _require_conversation(db, conversation_id=conversation_id, story_id=story_id, user_id=user_id)
    return AgentPendingChangeKey(user_id=user_id, story_id=story_id, conversation_id=conversation_id)


_AGENT_RUN_STALE_AFTER = datetime.timedelta(minutes=15)


def _require_conversation_idle(conversation: AgentConversation) -> None:
    """运行中的对话禁止确认、撤回或删除，避免与工具写入交错。"""
    if not conversation.active_run_id:
        return
    started_at = conversation.active_run_started_at
    if started_at and started_at < datetime.datetime.utcnow() - _AGENT_RUN_STALE_AFTER:
        return
    raise HTTPException(409, "当前对话仍在执行，请等待完成后再操作")


def _claim_agent_run(db: Session, conversation: AgentConversation) -> tuple[str, list[dict[str, Any]]]:
    """原子占用对话，防止多个进程同时覆盖同一份撤回快照。"""
    run_id = uuid.uuid4().hex
    stale_before = datetime.datetime.utcnow() - _AGENT_RUN_STALE_AFTER
    updated = (
        db.query(AgentConversation)
        .filter(
            AgentConversation.id == conversation.id,
            AgentConversation.owner_user_id == conversation.owner_user_id,
            or_(
                AgentConversation.active_run_id.is_(None),
                AgentConversation.active_run_started_at < stale_before,
            ),
        )
        .update(
            {
                AgentConversation.active_run_id: run_id,
                AgentConversation.active_run_started_at: datetime.datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(409, "当前对话已有请求正在执行，请等待完成后再试")

    prior_records = (
        db.query(AgentPendingChange)
        .filter(
            AgentPendingChange.user_id == conversation.owner_user_id,
            AgentPendingChange.story_id == conversation.story_id,
            AgentPendingChange.conversation_id == conversation.id,
        )
        .all()
    )
    prior_snapshot: list[dict[str, Any]] = []
    legacy_run_id = f"legacy-{run_id}"
    for record in prior_records:
        if not record.run_id:
            record.run_id = legacy_run_id
        prior_snapshot.append({
            "run_id": record.run_id,
            "change_type": record.change_type,
            "record_id": record.record_id,
            "display_name": record.display_name,
            "field": record.field,
            "old_value": record.old_value,
            "new_value": record.new_value,
        })
    db.commit()
    return run_id, prior_snapshot


def _release_agent_run(conversation_id: int, run_id: str) -> None:
    release_db = SessionLocal()
    try:
        release_db.query(AgentConversation).filter(
            AgentConversation.id == conversation_id,
            AgentConversation.active_run_id == run_id,
        ).update(
            {
                AgentConversation.active_run_id: None,
                AgentConversation.active_run_started_at: None,
            },
            synchronize_session=False,
        )
        release_db.commit()
    except Exception:
        release_db.rollback()
        logger.exception("释放 Agent 对话运行占用失败 conversation_id=%s", conversation_id)
    finally:
        release_db.close()


def _heartbeat_agent_run(conversation_id: int, run_id: str) -> None:
    """刷新运行租约，避免正常长任务被误判为过期。"""
    heartbeat_db = SessionLocal()
    try:
        heartbeat_db.query(AgentConversation).filter(
            AgentConversation.id == conversation_id,
            AgentConversation.active_run_id == run_id,
        ).update(
            {AgentConversation.active_run_started_at: datetime.datetime.utcnow()},
            synchronize_session=False,
        )
        heartbeat_db.commit()
    except Exception:
        heartbeat_db.rollback()
        logger.exception("刷新 Agent 对话运行租约失败 conversation_id=%s", conversation_id)
    finally:
        heartbeat_db.close()


def _finalize_pending_run(
    key: AgentPendingChangeKey,
    run_id: str,
    prior_snapshot: list[dict[str, Any]],
) -> None:
    """合并连续未确认修改，使撤回始终回到首个修改前的值。"""
    write_db = SessionLocal()
    try:
        records = (
            write_db.query(AgentPendingChange)
            .filter(
                AgentPendingChange.user_id == key.user_id,
                AgentPendingChange.story_id == key.story_id,
                AgentPendingChange.conversation_id == key.conversation_id,
            )
            .all()
        )
        current_records = [record for record in records if record.run_id == run_id]
        if not current_records:
            if not records and prior_snapshot:
                for item in prior_snapshot:
                    write_db.add(AgentPendingChange(
                        user_id=key.user_id,
                        story_id=key.story_id,
                        conversation_id=key.conversation_id,
                        **item,
                    ))
                write_db.commit()
            return

        prior_by_field = {
            (item["change_type"], item["record_id"], item["field"]): item
            for item in prior_snapshot
        }
        current_keys: set[tuple[str, int, str]] = set()
        for record in current_records:
            record_key = (record.change_type, record.record_id, record.field)
            current_keys.add(record_key)
            prior = prior_by_field.get(record_key)
            if prior is not None:
                record.old_value = prior["old_value"]
        for record in records:
            if record.run_id == run_id:
                continue
            record_key = (record.change_type, record.record_id, record.field)
            if record_key in current_keys:
                write_db.delete(record)

        remaining_keys = {
            (record.change_type, record.record_id, record.field)
            for record in records
            if record.run_id != run_id and (record.change_type, record.record_id, record.field) not in current_keys
        }
        for record_key, item in prior_by_field.items():
            if record_key in current_keys or record_key in remaining_keys:
                continue
            write_db.add(AgentPendingChange(
                user_id=key.user_id,
                story_id=key.story_id,
                conversation_id=key.conversation_id,
                **item,
            ))
        write_db.commit()
    except Exception:
        write_db.rollback()
        logger.exception("合并 Agent pending changes 失败 run_id=%s", run_id)
    finally:
        write_db.close()


def _load_owned_pending_target(
    db: Session,
    change_type: str,
    record_id: int,
    story_id: int,
    *,
    with_for_update: bool = False,
) -> Any | None:
    """读取并复核待撤回记录真实归属，不能只信任 pending 表。"""
    get_options = {"with_for_update": True} if with_for_update else {}
    if change_type in {"chapter", "chapter_created", "scenes_file"}:
        chapter = db.get(Chapter, record_id, **get_options)
        return chapter if chapter and chapter.story_id == story_id else None
    if change_type in {"story", "story_bible"}:
        story = db.get(Story, record_id, **get_options)
        return story if story and story.id == story_id else None
    if change_type == "video_workflow":
        workflow = db.get(ChapterVideoWorkflow, record_id, **get_options)
        return workflow if workflow and workflow.story_id == story_id else None
    if change_type == "video_shot":
        shot = db.get(ChapterVideoShot, record_id, **get_options)
        if not shot:
            return None
        workflow_id = getattr(shot, "workflow_id", None)
        if workflow_id is None and not isinstance(shot, ChapterVideoShot):
            return shot
        workflow = db.get(ChapterVideoWorkflow, workflow_id)
        if workflow and not isinstance(workflow, ChapterVideoWorkflow) and not hasattr(workflow, "story_id"):
            return shot
        return shot if workflow and getattr(workflow, "story_id", None) == story_id else None
    return None


def _created_chapter_conflict(db: Session, chapter: Chapter, snapshot: Any) -> str | None:
    """确认新建章节仍是空壳，避免撤回时级联删除后续创作结果。"""
    expected = snapshot if isinstance(snapshot, dict) else {}
    for field in (
        "story_id",
        "chapter_number",
        "title",
        "status",
        "novel_content",
        "act",
        "video_style_preset_id",
    ):
        if field in expected and getattr(chapter, field, None) != expected[field]:
            return "新建章节已被继续修改，为避免丢失内容，本次未删除"
    if str(chapter.novel_content or "").strip():
        return "新建章节已写入正文，为避免丢失内容，本次未删除"
    meaningful_fields = (
        "screenplay_text",
        "content_source",
        "key_events",
        "quality_score",
        "memory_summary",
        "manga_asset_analysis_json",
        "word_count",
    )
    if any(getattr(chapter, field, None) not in (None, "", [], {}) for field in meaningful_fields):
        return "新建章节已有后续生成数据，为避免丢失内容，本次未删除"
    if any((chapter.messages, chapter.images, chapter.script_scenes)):
        return "新建章节已有聊天、漫画或分镜数据，为避免丢失内容，本次未删除"
    if db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.chapter_id == chapter.id).first():
        return "新建章节已有视频工作流，为避免丢失内容，本次未删除"
    if db.query(AgentConversation).filter(AgentConversation.chapter_id == chapter.id).first():
        return "新建章节仍被 Agent 对话引用，为避免破坏对话，本次未删除"
    return None


def _safe_short_text(value: str | None, max_len: int = 5000) -> str:
    """安全截断文本（默认 5000 字符，适配 DeepSeek V4 100 万 tokens 上下文）。"""
    if not value:
        return "（无）"
    text = " ".join(str(value).split())
    return text[:max_len] + "…" if len(text) > max_len else text


def _build_video_agent_context(
    workflow: Any,
    shots: list[Any],
    current_shot_id: int | None = None,
) -> str:
    """构建视频工作流的 Agent 上下文字符串（完整版，充分利用 DeepSeek V4 大上下文）。"""
    lines = [
        "\n\n## 视频工作流上下文",
        "",
        "### 工作流概览",
        f"- 工作流 ID: {workflow.id}",
        f"- 状态: {workflow.workflow_status or '未知'}",
        f"- 视频风格: {workflow.video_style or '未指定'}",
        f"- 每镜头时长: {workflow.duration_per_shot}s",
        f"- 总镜头数: {workflow.total_shots}",
        f"- 已完成镜头: {workflow.completed_shots}",
        f"- 失败镜头: {workflow.failed_shots}",
    ]

    # 剧本全文（不再截断，5000字上限已足够）
    if workflow.screenplay_text:
        lines.append("")
        lines.append("### 剧本全文")
        lines.append(f"```\n{_safe_short_text(workflow.screenplay_text, 5000)}\n```")

    if shots:
        lines.append("")
        lines.append("### 镜头列表（完整信息）")
        for shot in shots:
            marker = " ← 当前镜头" if current_shot_id and shot.id == current_shot_id else ""
            lines.append(f"\n#### 镜头 {shot.shot_index} [{shot.status or 'pending'}]{marker}")
            lines.append(f"- 场景: {shot.scene_location or '未指定'} / {shot.time_of_day or '未指定'}")
            chars = shot.characters
            if isinstance(chars, list):
                lines.append(f"- 角色: {', '.join(str(c) for c in chars)}")
            lines.append(f"- 故事概要: {shot.story_summary or '无'}")
            if shot.dialogue_or_narration:
                lines.append(f"- 对话/旁白: {_safe_short_text(shot.dialogue_or_narration, 500)}")
            lines.append(f"- 镜头计划: {shot.camera_plan or '无'}")
            lines.append(f"- 运动计划: {shot.motion_plan or '无'}")
            lines.append(f"- 情绪计划: {shot.emotion_plan or '无'}")
            if shot.narrative_purpose:
                lines.append(f"- 叙事目的: {shot.narrative_purpose}")
            if shot.beat_density:
                lines.append(f"- 节拍密度: {shot.beat_density}")
            if shot.transition_to_next:
                lines.append(f"- 过渡到下一镜: {shot.transition_to_next}")
            if shot.continuity_notes:
                lines.append(f"- 连续性: {shot.continuity_notes}")
            if shot.storyboard_prompt:
                lines.append(f"- 故事版提示词: {_safe_short_text(shot.storyboard_prompt, 2000)}")
            if shot.video_prompt:
                lines.append(f"- 视频提示词: {_safe_short_text(shot.video_prompt, 2000)}")
            if shot.scene_prompt:
                lines.append(f"- 场景提示词: {_safe_short_text(shot.scene_prompt, 1000)}")
            if shot.character_prompts_json:
                lines.append(f"- 角色提示词: {_safe_short_text(str(shot.character_prompts_json), 1000)}")
            if shot.prop_prompts_json:
                lines.append(f"- 道具提示词: {_safe_short_text(str(shot.prop_prompts_json), 1000)}")
            if shot.character_reference_ids:
                lines.append(f"- 角色引用 ID: {shot.character_reference_ids}")
            if shot.scene_reference_ids:
                lines.append(f"- 场景引用 ID: {shot.scene_reference_ids}")
            if shot.prop_reference_ids:
                lines.append(f"- 道具引用 ID: {shot.prop_reference_ids}")
            if shot.storyboard_image_url:
                lines.append(f"- 故事版图片: {shot.storyboard_image_url}")
            if shot.video_url:
                lines.append(f"- 视频 URL: {shot.video_url}")

    return "\n".join(lines)


def _build_conversation_summary(conversation: AgentConversation) -> AgentConversationSummaryOut:
    ordered_messages = list(conversation.messages or [])
    last_message = ordered_messages[-1].content if ordered_messages else ""
    return AgentConversationSummaryOut(
        id=conversation.id,
        story_id=conversation.story_id,
        chapter_id=conversation.chapter_id,
        title=conversation.title or "新对话",
        last_message_preview=_conversation_preview(last_message),
        message_count=len(ordered_messages),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("/conversations", response_model=list[AgentConversationSummaryOut])
def list_conversations(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    conversations = (
        db.query(AgentConversation)
        .filter(
            AgentConversation.story_id == story_id,
            AgentConversation.owner_user_id == user.id,
        )
        .order_by(AgentConversation.updated_at.desc(), AgentConversation.id.desc())
        .all()
    )
    return [_build_conversation_summary(item) for item in conversations]


@router.post("/conversations", response_model=AgentConversationOut)
def create_conversation(
    story_id: int,
    body: AgentConversationCreateIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    chapter_id = body.chapter_id
    if chapter_id is not None:
        chapter = db.get(Chapter, chapter_id)
        if not chapter or chapter.story_id != story_id:
            raise HTTPException(422, "章节不存在或不属于当前作品")
    if body.workflow_type == "video":
        workflow = db.get(ChapterVideoWorkflow, body.workflow_id)
        if not workflow or workflow.story_id != story_id:
            raise HTTPException(422, "视频工作流不存在或不属于当前作品")

    conversation = AgentConversation(
        story_id=story_id,
        owner_user_id=user.id,
        chapter_id=chapter_id,
        title=(body.title or "").strip() or "新对话",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return AgentConversationOut.model_validate(conversation)


@router.get("/conversations/{conversation_id}", response_model=AgentConversationOut)
def get_conversation(
    story_id: int,
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    conversation = _require_conversation(db, conversation_id=conversation_id, story_id=story_id, user_id=user.id)
    return AgentConversationOut.model_validate(conversation)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    story_id: int,
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    conversation = _require_conversation(db, conversation_id=conversation_id, story_id=story_id, user_id=user.id)
    _require_conversation_idle(conversation)
    db.delete(conversation)
    db.commit()
    return {"ok": True}


@router.post("/chat")
async def agent_chat(
    story_id: int,
    body: AgentChatIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    conversation_id = int(body.conversation_id or 0)
    content = str(body.message or "").strip()
    agent_mode = normalize_agent_mode(body.mode)
    if not conversation_id:
        raise HTTPException(400, "对话 ID 必填")
    if not content and not body.attachment_ids:
        raise HTTPException(400, "内容必填")
    if not content:
        content = "请分析我上传的附件，并给出可直接用于创作的结构化建议。"

    conversation = _require_conversation(
        db,
        conversation_id=conversation_id,
        story_id=story_id,
        user_id=user.id,
    )
    persisted_conversation_id = conversation.id
    persisted_user_id = user.id
    pending_change_key = AgentPendingChangeKey(
        user_id=persisted_user_id,
        story_id=story_id,
        conversation_id=persisted_conversation_id,
    )
    attachments = resolve_attachments(
        body.attachment_ids,
        db=db,
        owner_user_id=user.id,
        story_id=story_id,
        conversation_id=persisted_conversation_id,
    )

    current_chapter = None
    current_chapter_id = body.chapter_id
    if current_chapter_id:
        current_chapter = db.get(Chapter, int(current_chapter_id))
        if not current_chapter or current_chapter.story_id != story_id:
            raise HTTPException(422, "章节不存在或不属于当前作品")
    if current_chapter:
        conversation.chapter_id = current_chapter.id

    story_context = _build_framework_context(story, current_chapter)
    if current_chapter:
        story_context += (
            "\n\n## 当前用户正在查看的章节\n"
            f"章节 ID: {current_chapter.id}\n"
            f"章节号: {current_chapter.chapter_number}\n"
            f"章节标题: {current_chapter.title or '未命名'}\n"
            f"所属幕: {current_chapter.act or '未分配'}\n"
            f"状态: {current_chapter.status or 'draft'}\n"
            f"字数: {current_chapter.word_count or 0}\n"
            f"注意：如需读取本章正文内容，请调用 get_chapter_full(chapter_id={current_chapter.id}) 工具。"
        )

    workflow_type = body.workflow_type
    workflow_id = body.workflow_id
    shot_id = body.shot_id

    # 漫画工作流自动附带当前章节的已生成图片，用户无需重复上传即可让视觉模型检查画面。
    context_image_attachments: list[dict[str, Any]] = []
    temporary_context_paths: list[Path] = []
    if workflow_type == "manga" and current_chapter:
        backend_root = Path(__file__).resolve().parent.parent
        manga_images = (
            db.query(MangaImage)
            .filter(MangaImage.chapter_id == current_chapter.id)
            .order_by(MangaImage.image_number)
            .limit(6)
            .all()
        )
        for image in manga_images:
            raw_path = str(image.image_path or "")
            if raw_path.startswith(("http://", "https://")):
                continue
            local_path = (backend_root / raw_path).resolve()
            if not local_path.is_file() or not local_path.is_relative_to(backend_root):
                continue
            context_image_attachments.append({
                "filename": f"第{image.image_number}张漫画图",
                "content_type": "image/*",
                "media_kind": "image",
                "path": str(local_path),
            })
        if context_image_attachments:
            story_context += (
                "\n\n## 当前章节视觉上下文\n"
                f"已自动附带当前章节 {len(context_image_attachments)} 张漫画图。"
                "请直接查看这些图片后再回答，不要要求用户重复上传；如图片不可见，再明确说明原因。"
            )

    if workflow_type == "video" and workflow_id:
        video_workflow = db.get(ChapterVideoWorkflow, workflow_id)
        if (
            video_workflow
            and video_workflow.story_id == story_id
            and current_chapter
            and video_workflow.chapter_id == current_chapter.id
        ):
            video_shots = (
                db.query(ChapterVideoShot)
                .filter(ChapterVideoShot.workflow_id == workflow_id)
                .order_by(ChapterVideoShot.shot_index)
                .all()
            )
            story_context += _build_video_agent_context(video_workflow, video_shots, current_shot_id=shot_id)
            context_media_count = 0
            storyboard_count = 0
            video_count = 0
            for shot in video_shots:
                if storyboard_count < 8 and shot.storyboard_image_url:
                    storyboard_path = await asyncio.to_thread(ensure_local_media_path, shot.storyboard_image_url, "manga")
                    if storyboard_path and Path(storyboard_path).is_file():
                        context_image_attachments.append({
                            "filename": f"分镜{shot.shot_index}故事版",
                            "content_type": "image/jpeg",
                            "media_kind": "image",
                            "path": storyboard_path,
                        })
                        storyboard_count += 1
                        context_media_count += 1
                if video_count < 4 and shot.video_url:
                    video_path = await asyncio.to_thread(ensure_local_media_path, shot.video_url, "video")
                    if video_path and Path(video_path).is_file():
                        frame_dir = Path(tempfile.mkdtemp(prefix=f"agent_video_{shot.id}_"))
                        temporary_context_paths.append(frame_dir)
                        try:
                            probe = await asyncio.to_thread(_probe_video, Path(video_path))
                            frame_paths = await asyncio.to_thread(_extract_video_frames, Path(video_path), frame_dir, probe["duration"])
                        except Exception:
                            frame_paths = []
                        if frame_paths:
                            context_image_attachments.append({
                                "filename": f"分镜{shot.shot_index}视频关键帧",
                                "content_type": "video/mp4",
                                "media_kind": "video",
                                "path": video_path,
                                "frame_paths": frame_paths,
                            })
                            video_count += 1
                            context_media_count += 1
            if context_media_count:
                story_context += (
                    "\n\n## 视频工作流视觉上下文\n"
                    f"已自动附带分镜列表中的 {storyboard_count} 张故事版图片和 {video_count} 个视频的关键帧。"
                    "请直接查看这些视觉资料后回答，不要要求用户重复上传；视频按时间顺序提供关键帧。"
                )
        else:
            raise HTTPException(422, "视频工作流不存在或不属于当前作品")

    # 紧急压缩优先保留数组前部图片，因此用户本次显式附件必须排在自动视觉上下文之前。
    attachments = [*attachments, *context_image_attachments]

    quota_result = _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)

    if len(conversation.messages) == 0 or (conversation.title or "").strip() in {"", "新对话"}:
        conversation.title = _conversation_title_from_text(content)

    attachment_note = ""
    if attachments:
        attachment_note = "\n\n" + "\n".join(
            f"[附件] {item['filename']}（{item['media_kind']}）" for item in attachments
        )
    user_message = AgentConversationMessage(
        conversation_id=persisted_conversation_id,
        role="user",
        content=content + attachment_note,
    )
    run_id, prior_pending_snapshot = _claim_agent_run(db, conversation)
    conversation.updated_at = datetime.datetime.utcnow()
    db.add(user_message)
    try:
        db.commit()
    except Exception:
        db.rollback()
        _release_agent_run(persisted_conversation_id, run_id)
        raise

    history_records = (
        db.query(AgentConversationMessage)
        .filter(AgentConversationMessage.conversation_id == persisted_conversation_id)
        .order_by(AgentConversationMessage.created_at.asc(), AgentConversationMessage.id.asc())
        .all()
    )
    history = [{"role": item.role, "content": item.content} for item in history_records]
    if attachments and history:
        # 数据库存储纯文本，发送给模型时为最后一条用户消息附加多模态结构。
        history[-1]["content"] = multimodal_content(content, attachments)
    deepseek_api_key = _user_deepseek_api_key(request)
    streaming_billing_ctx = _detach_pending_platform_points(
        request,
        quota_result.get("usage_event_id"),
    )
    _release_db_transaction(db)
    billing_state = {"finished": False}
    run_cleanup_state = {"pending_finalized": False, "released": False}

    def finalize_pending_once() -> None:
        if run_cleanup_state["pending_finalized"]:
            return
        run_cleanup_state["pending_finalized"] = True
        _finalize_pending_run(pending_change_key, run_id, prior_pending_snapshot)

    def release_run_once() -> None:
        if run_cleanup_state["released"]:
            return
        run_cleanup_state["released"] = True
        _release_agent_run(persisted_conversation_id, run_id)

    async def event_generator():
        collected: list[str] = []
        assistant_saved = False
        stream_failed = False
        stream_token_count = 0

        async def heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(60)
                await asyncio.to_thread(_heartbeat_agent_run, persisted_conversation_id, run_id)

        heartbeat_task = asyncio.create_task(heartbeat_loop())

        def settle_billing(*, success: bool, error_code: str | None = None) -> None:
            if billing_state["finished"]:
                return
            _finish_streaming_platform_points(
                streaming_billing_ctx,
                success=success,
                input_text=json.dumps(history, ensure_ascii=False),
                output_text="".join(collected),
                error_code=error_code,
            )
            billing_state["finished"] = True

        def persist_assistant_message(content_text: str) -> None:
            nonlocal assistant_saved
            normalized = redact_sensitive_text(content_text).strip()
            if not normalized or assistant_saved:
                return
            write_db = SessionLocal()
            try:
                persisted_conversation = _require_conversation(
                    write_db,
                    conversation_id=persisted_conversation_id,
                    story_id=story_id,
                    user_id=persisted_user_id,
                )
                persisted_conversation.updated_at = datetime.datetime.utcnow()
                write_db.add(
                    AgentConversationMessage(
                        conversation_id=persisted_conversation_id,
                        role="assistant",
                        content=normalized,
                    )
                )
                write_db.commit()
                assistant_saved = True
            except Exception as e:
                logger.warning("persist_assistant_message 写入失败（DB异常或对话未找到）: %s", e)
            finally:
                write_db.close()

        try:
            async for event in agent_service.run_stream(
                messages=history,
                story_context=story_context,
                api_key=deepseek_api_key,
                story_id=story_id,
                mode=agent_mode,
                pending_change_key=pending_change_key,
                workflow_type=workflow_type,
                workflow_id=workflow_id,
                shot_id=shot_id,
                chapter_id=body.chapter_id,
                enabled_skills=body.enabled_skills,
                run_id=run_id,
                db=db,
            ):
                event_type = str(event.get("event") or "")
                if event_type == "token":
                    try:
                        payload = json.loads(event.get("data", "{}"))
                        token = str(payload.get("content") or "")
                        if token:
                            collected.append(token)
                            stream_token_count += 1
                            if stream_token_count % 16 == 0:
                                from services.ai.resolver import charge_streaming_tokens
                                from services.token_utils import estimate_tokens

                                billing_db = SessionLocal()
                                try:
                                    charge_streaming_tokens(
                                        billing_db,
                                        streaming_billing_ctx,
                                        input_tokens=estimate_tokens(
                                            json.dumps(history, ensure_ascii=False) + story_context
                                        ),
                                        output_tokens=estimate_tokens("".join(collected)),
                                    )
                                finally:
                                    billing_db.close()
                    except Exception:
                        pass
                elif event_type == "done":
                    try:
                        payload = json.loads(event.get("data", "{}"))
                        final_content = str(payload.get("content") or "").strip()
                        settled_content = _settle_agent_response_content(collected, final_content)
                        payload["content"] = settled_content
                        payload["run_id"] = run_id
                        event = {**event, "data": json.dumps(payload, ensure_ascii=False)}
                    except Exception:
                        final_content = ""
                        settled_content = _settle_agent_response_content(collected)
                    finalize_pending_once()
                    if settled_content and not collected:
                        collected.append(settled_content)
                    settle_billing(success=True)
                    persist_assistant_message(settled_content)
                    release_run_once()
                elif event_type == "error":
                    stream_failed = True
                    try:
                        payload = json.loads(event.get("data", "{}"))
                        error_text = str(payload.get("error") or "").strip()
                    except Exception:
                        error_text = ""
                    if error_text:
                        persist_assistant_message(
                            _settle_agent_response_content(collected, suffix=f"错误: {error_text}")
                        )
                # SSE 也做一层清洗，避免上游工具结果或异常文本直接暴露给浏览器。
                if event_type in {"token", "done", "error", "tool"}:
                    try:
                        event_payload = json.loads(event.get("data", "{}"))
                        for key in ("content", "error", "result", "message"):
                            if isinstance(event_payload.get(key), str):
                                event_payload[key] = redact_sensitive_text(event_payload[key])
                        event = {**event, "data": json.dumps(event_payload, ensure_ascii=False)}
                    except HTTPException:
                        raise
                    except Exception:
                        pass
                yield event

            if not assistant_saved:
                persist_assistant_message(_settle_agent_response_content(collected))
            if not stream_failed:
                settle_billing(success=True)
            elif not billing_state["finished"]:
                settle_billing(success=bool(collected), error_code=None if collected else "stream_failed")
        except asyncio.CancelledError:
            settle_billing(success=bool(collected), error_code=None if collected else "stream_cancelled")
            if not assistant_saved:
                persist_assistant_message("".join(collected) + "\n\n[已中止]")
            raise
        except Exception as exc:
            logger.exception("Agent stream failed")
            public_message = public_error_message(exc, "AI 助手执行失败，请稍后重试")
            error_code = str(getattr(exc, "code", "agent_stream_failed") or "agent_stream_failed")
            settle_billing(success=bool(collected), error_code=None if collected else "stream_failed")
            if not assistant_saved:
                persist_assistant_message(
                    _settle_agent_response_content(collected, suffix=f"执行失败：{public_message}")
                )
            yield {"event": "error", "data": json.dumps({"error": public_message, "code": error_code}, ensure_ascii=False)}
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            finalize_pending_once()
            release_run_once()

    def release_unfinished_billing() -> None:
        finalize_pending_once()
        release_run_once()
        for temporary_path in temporary_context_paths:
            shutil.rmtree(temporary_path, ignore_errors=True)
        if billing_state["finished"]:
            return
        try:
            _finish_streaming_platform_points(
                streaming_billing_ctx,
                success=False,
                error_code="stream_not_started_or_unfinished",
            )
            billing_state["finished"] = True
        except Exception:
            logger.exception(
                "Agent 流清理预留积分失败 conversation_id=%s",
                persisted_conversation_id,
            )

    return EventSourceResponse(
        event_generator(),
        background=ResponseBackgroundTask(release_unfinished_billing),
    )


@router.post("/confirm")
async def confirm_changes(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    try:
        body = await request.json()
    except Exception:
        body = None
    key = _pending_change_key_from_request(
        request=request,
        db=db,
        story_id=story_id,
        user_id=user.id,
        body=body if isinstance(body, dict) else None,
    )
    if key is not None:
        conversation = _require_conversation(
            db,
            conversation_id=key.conversation_id,
            story_id=story_id,
            user_id=user.id,
        )
        _require_conversation_idle(conversation)
        pending_query = db.query(AgentPendingChange).filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
        )
        requested_run_id = str(body.get("run_id") or "").strip() if isinstance(body, dict) else ""
        if requested_run_id:
            pending_query = pending_query.filter(AgentPendingChange.run_id == requested_run_id)
        pending_query.delete()
        db.commit()
        agent_pending_change_store.clear(key)
    return {"ok": True, "message": "修改已确认"}


@router.post("/rollback")
async def rollback_changes(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    try:
        body = await request.json()
    except Exception:
        body = None
    key = _pending_change_key_from_request(
        request=request,
        db=db,
        story_id=story_id,
        user_id=user.id,
        body=body if isinstance(body, dict) else None,
    )
    if key is None:
        return {"ok": True, "message": "没有待撤回的修改"}

    conversation = _require_conversation(
        db,
        conversation_id=key.conversation_id,
        story_id=story_id,
        user_id=user.id,
    )
    _require_conversation_idle(conversation)

    pending_query = db.query(AgentPendingChange).filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
    )
    requested_run_id = str(body.get("run_id") or "").strip() if isinstance(body, dict) else ""
    if requested_run_id:
        pending_query = pending_query.filter(AgentPendingChange.run_id == requested_run_id)
    db_records = pending_query.all()
    if db_records:
        results = []
        conflicted_video_shots: set[int] = set()
        conflicted_video_workflows: set[int] = set()
        conflicted_changes: set[tuple[str, int, str]] = set()
        for record in db_records:
            obj = _load_owned_pending_target(
                db,
                record.change_type,
                record.record_id,
                story_id,
                with_for_update=True,
            )
            if obj is None:
                conflicted_changes.add((record.change_type, record.record_id, record.field))
                results.append({
                    "ok": False,
                    "conflict": True,
                    "type": record.change_type,
                    "id": record.record_id,
                    "field": record.field,
                    "error": "待撤回对象不存在或已不属于当前作品",
                })
                continue
            if record.change_type == "scenes_file":
                continue
            if record.change_type == "chapter_created":
                conflict_error = _created_chapter_conflict(db, obj, record.new_value)
                if conflict_error:
                    conflicted_changes.add((record.change_type, record.record_id, record.field))
                    results.append({
                        "ok": False,
                        "conflict": True,
                        "type": record.change_type,
                        "id": record.record_id,
                        "field": record.field,
                        "error": conflict_error,
                    })
                continue

            if getattr(obj, record.field, None) == record.new_value:
                continue
            if record.change_type == "video_shot" and record.field == "storyboard_prompt_stale":
                conflicted_video_shots.add(record.record_id)
                workflow_id = getattr(obj, "workflow_id", None)
                if workflow_id is not None:
                    conflicted_video_workflows.add(workflow_id)
                results.append({
                    "ok": False,
                    "conflict": True,
                    "type": "video_shot",
                    "id": record.record_id,
                    "field": record.field,
                    "error": "故事板已重新生成，为避免覆盖新结果，未撤回该镜头的修改",
                })
            else:
                conflicted_changes.add((record.change_type, record.record_id, record.field))
                results.append({
                    "ok": False,
                    "conflict": True,
                    "type": record.change_type,
                    "id": record.record_id,
                    "field": record.field,
                    "error": "内容已被再次修改，为避免覆盖新结果，本次未撤回",
                })
        for record in reversed(db_records):
            try:
                if (record.change_type, record.record_id, record.field) in conflicted_changes:
                    continue
                if record.change_type == "chapter_created":
                    obj = _load_owned_pending_target(db, "chapter_created", record.record_id, story_id)
                    if obj:
                        db.delete(obj)
                        results.append({"ok": True, "type": "chapter_created", "id": record.record_id, "field": record.field})
                elif record.change_type == "chapter":
                    obj = _load_owned_pending_target(db, "chapter", record.record_id, story_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": "chapter", "id": record.record_id, "field": record.field})
                elif record.change_type in ("story", "story_bible"):
                    obj = _load_owned_pending_target(db, record.change_type, record.record_id, story_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": record.change_type, "id": record.record_id, "field": record.field})
                elif record.change_type == "video_shot":
                    obj = _load_owned_pending_target(db, "video_shot", record.record_id, story_id)
                    if obj and (
                        record.record_id in conflicted_video_shots
                        or getattr(obj, "workflow_id", None) in conflicted_video_workflows
                    ):
                        continue
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": "video_shot", "id": record.record_id, "field": record.field})
                elif record.change_type == "video_workflow":
                    if record.record_id in conflicted_video_workflows:
                        continue
                    obj = _load_owned_pending_target(db, "video_workflow", record.record_id, story_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": "video_workflow", "id": record.record_id, "field": record.field})
                elif record.change_type == "scenes_file":
                    with _scenes_file_lock(record.record_id):
                        chapter = db.get(Chapter, record.record_id)
                        scenes_path = _scenes_path(record.record_id)
                        current_value = (
                            _chapter_storyboard_text(chapter)
                            if chapter
                            else (scenes_path.read_text(encoding="utf-8") if scenes_path.exists() else None)
                        )
                        if current_value != record.new_value:
                            results.append({
                                "ok": False,
                                "conflict": True,
                                "type": "scenes_file",
                                "id": record.record_id,
                                "field": record.field,
                                "error": "分镜已被再次修改，为避免覆盖新结果，本次未撤回",
                            })
                            continue
                        if chapter:
                            restored_scenes = _parse_scenes_text(str(record.old_value or ""))
                            _set_chapter_storyboard_scenes(chapter, restored_scenes)
                            db.commit()
                        try:
                            if record.old_value:
                                _write_scenes_text_atomic(record.record_id, str(record.old_value))
                            elif scenes_path.exists():
                                scenes_path.unlink()
                        except OSError:
                            logger.exception("撤回后写入分镜兼容文件失败 chapter_id=%s", record.record_id)
                        results.append({"ok": True, "type": "scenes_file", "id": record.record_id, "field": record.field})
            except Exception as e:
                results.append({"ok": False, "error": public_error_message(e, "撤回修改失败，请稍后重试")})
        if any(r.get("ok") for r in results):
            db.commit()
        has_failures = any(not result.get("ok") for result in results)
        if not has_failures:
            delete_query = db.query(AgentPendingChange).filter(
                AgentPendingChange.user_id == key.user_id,
                AgentPendingChange.story_id == key.story_id,
                AgentPendingChange.conversation_id == key.conversation_id,
            )
            if requested_run_id:
                delete_query = delete_query.filter(AgentPendingChange.run_id == requested_run_id)
            delete_query.delete()
            db.commit()
        agent_pending_change_store.clear(key)
        return {"ok": True, "results": results, "pending_retained": has_failures}

    tracker = agent_pending_change_store.get(key)
    if not tracker or not tracker.has_changes():
        return {"ok": True, "message": "没有待撤回的修改"}

    memory_changes = list(getattr(tracker, "_changes", []))
    ownership_conflicts = []
    for change in memory_changes:
        target = _load_owned_pending_target(
            db,
            change.type,
            change.record_id,
            story_id,
            with_for_update=True,
        )
        if target is None:
            ownership_conflicts.append({
                "ok": False,
                "conflict": True,
                "type": change.type,
                "id": change.record_id,
                "field": change.field,
                "error": "待撤回对象不存在或已不属于当前作品",
            })
        elif change.type == "chapter_created":
            conflict_error = _created_chapter_conflict(db, target, change.new_value)
            if conflict_error:
                ownership_conflicts.append({
                    "ok": False,
                    "conflict": True,
                    "type": change.type,
                    "id": change.record_id,
                    "field": change.field,
                    "error": conflict_error,
                })
    if ownership_conflicts:
        return {"ok": True, "results": ownership_conflicts, "pending_retained": True}

    created_changes = [change for change in memory_changes if change.type == "chapter_created"]
    for change in created_changes:
        chapter = _load_owned_pending_target(db, change.type, change.record_id, story_id)
        if chapter:
            db.delete(chapter)
    if created_changes:
        tracker._changes = [change for change in memory_changes if change.type != "chapter_created"]
    results = tracker.rollback(db)
    if created_changes:
        db.commit()
        results.extend({
            "ok": True,
            "type": "chapter_created",
            "id": change.record_id,
            "field": change.field,
        } for change in created_changes)
    agent_pending_change_store.clear(key)
    return {"ok": True, "results": results}


@router.get("/pending-changes")
def get_pending_changes(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    key = _pending_change_key_from_request(
        request=request,
        db=db,
        story_id=story_id,
        user_id=user.id,
    )
    if key is None:
        return {"changes": []}

    pending_query = db.query(AgentPendingChange).filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
    )
    requested_run_id = str(request.query_params.get("run_id") or "").strip()
    if requested_run_id:
        pending_query = pending_query.filter(AgentPendingChange.run_id == requested_run_id)
    db_records = pending_query.all()
    if db_records:
        return {
            "changes": [
                {
                    "type": r.change_type,
                    "record_id": r.record_id,
                    "display_name": r.display_name,
                    "field": r.field,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                    "run_id": r.run_id,
                    "source": "db",
                }
                for r in db_records
            ]
        }

    tracker = agent_pending_change_store.get(key)
    if not tracker:
        return {"changes": []}
    return {"changes": tracker.get_full_data(), "source": "memory"}
