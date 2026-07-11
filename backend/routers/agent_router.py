import asyncio
import datetime
import json
import logging
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal, get_db
from models import AgentConversation, AgentConversationMessage, AgentPendingChange, Chapter, ChapterVideoShot, ChapterVideoWorkflow, Story
from schemas import AgentChatIn, AgentConversationCreateIn, AgentConversationOut, AgentConversationSummaryOut
from services.agent_service import (
    AgentPendingChangeKey,
    _scenes_path,
    agent_pending_change_store,
    agent_service,
    normalize_agent_mode,
)

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
_refund_quota = _main._refund_quota
_build_framework_context = _main._build_framework_context


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
            raise HTTPException(400, "无效的章节 ID")

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
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)

    conversation_id = int(body.conversation_id or 0)
    content = str(body.message or "").strip()
    agent_mode = normalize_agent_mode(body.mode)
    if not conversation_id:
        raise HTTPException(400, "对话 ID 必填")
    if not content:
        raise HTTPException(400, "内容必填")

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

    current_chapter = None
    current_chapter_id = body.chapter_id
    if current_chapter_id:
        current_chapter = db.get(Chapter, int(current_chapter_id))
        if current_chapter and current_chapter.story_id != story_id:
            current_chapter = None
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

    if workflow_type == "video" and workflow_id:
        video_workflow = db.get(ChapterVideoWorkflow, workflow_id)
        if video_workflow and video_workflow.story_id == story_id:
            video_shots = (
                db.query(ChapterVideoShot)
                .filter(ChapterVideoShot.workflow_id == workflow_id)
                .order_by(ChapterVideoShot.shot_index)
                .all()
            )
            story_context += _build_video_agent_context(video_workflow, video_shots, current_shot_id=shot_id)
        else:
            raise HTTPException(403, "视频工作流不属于当前故事")

    if len(conversation.messages) == 0 or (conversation.title or "").strip() in {"", "新对话"}:
        conversation.title = _conversation_title_from_text(content)

    user_message = AgentConversationMessage(
        conversation_id=persisted_conversation_id,
        role="user",
        content=content,
    )
    conversation.updated_at = datetime.datetime.utcnow()
    db.add(user_message)
    db.commit()

    db.refresh(conversation, ["messages"])
    history = [{"role": item.role, "content": item.content} for item in conversation.messages]
    deepseek_api_key = _user_deepseek_api_key(request)
    _release_db_transaction(db)

    async def event_generator():
        collected: list[str] = []
        assistant_saved = False

        def persist_assistant_message(content_text: str) -> None:
            nonlocal assistant_saved
            normalized = (content_text or "").strip()
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
                enabled_skills=body.enabled_skills,
                db=db,
            ):
                event_type = str(event.get("event") or "")
                if event_type == "token":
                    try:
                        payload = json.loads(event.get("data", "{}"))
                        token = str(payload.get("content") or "")
                        if token:
                            collected.append(token)
                    except Exception:
                        pass
                elif event_type == "done":
                    try:
                        payload = json.loads(event.get("data", "{}"))
                        final_content = str(payload.get("content") or "").strip()
                    except Exception:
                        final_content = ""
                    persist_assistant_message(final_content or "".join(collected))
                elif event_type == "error":
                    try:
                        payload = json.loads(event.get("data", "{}"))
                        error_text = str(payload.get("error") or "").strip()
                    except Exception:
                        error_text = ""
                    if error_text:
                        persist_assistant_message(f"错误: {error_text}")
                yield event

            if not assistant_saved:
                persist_assistant_message("".join(collected))
        except asyncio.CancelledError:
            if not assistant_saved:
                persist_assistant_message("".join(collected) + "\n\n[已中止]")
            raise
        except Exception as exc:
            logger.exception("Agent stream failed")
            _refund_quota(persisted_user_id, "ai.text.advanced_calls.monthly_limit", 1, db)
            if not assistant_saved:
                persist_assistant_message(f"错误: {exc}")
            yield {"event": "error", "data": json.dumps({"error": str(exc)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


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
        db.query(AgentPendingChange).filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
        ).delete()
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

    db_records = (
        db.query(AgentPendingChange)
        .filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
        )
        .all()
    )
    if db_records:
        results = []
        for record in reversed(db_records):
            try:
                if record.change_type == "chapter":
                    obj = db.get(Chapter, record.record_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": "chapter", "id": record.record_id, "field": record.field})
                elif record.change_type in ("story", "story_bible"):
                    obj = db.get(Story, record.record_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": record.change_type, "id": record.record_id, "field": record.field})
                elif record.change_type == "video_shot":
                    obj = db.get(ChapterVideoShot, record.record_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": "video_shot", "id": record.record_id, "field": record.field})
                elif record.change_type == "video_workflow":
                    obj = db.get(ChapterVideoWorkflow, record.record_id)
                    if obj:
                        setattr(obj, record.field, record.old_value)
                        results.append({"ok": True, "type": "video_workflow", "id": record.record_id, "field": record.field})
                elif record.change_type == "scenes_file":
                    scenes_path = _scenes_path(record.record_id)
                    if record.old_value:
                        scenes_path.parent.mkdir(parents=True, exist_ok=True)
                        scenes_path.write_text(str(record.old_value), encoding="utf-8")
                    elif scenes_path.exists():
                        scenes_path.unlink()
                    results.append({"ok": True, "type": "scenes_file", "id": record.record_id, "field": record.field})
            except Exception as e:
                results.append({"ok": False, "error": str(e)})
        if any(r.get("ok") for r in results):
            db.commit()
        db.query(AgentPendingChange).filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
        ).delete()
        db.commit()
        agent_pending_change_store.clear(key)
        return {"ok": True, "results": results}

    tracker = agent_pending_change_store.get(key)
    if not tracker or not tracker.has_changes():
        return {"ok": True, "message": "没有待撤回的修改"}

    results = tracker.rollback(db)
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

    db_records = (
        db.query(AgentPendingChange)
        .filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
        )
        .all()
    )
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
                    "source": "db",
                }
                for r in db_records
            ]
        }

    tracker = agent_pending_change_store.get(key)
    if not tracker:
        return {"changes": []}
    return {"changes": tracker.get_full_data(), "source": "memory"}
