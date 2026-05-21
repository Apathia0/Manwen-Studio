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
from models import AgentConversation, AgentConversationMessage, Chapter
from schemas import AgentConversationCreateIn, AgentConversationOut, AgentConversationSummaryOut

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
        raise HTTPException(404, "Conversation not found")
    return conversation


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
            raise HTTPException(400, "Invalid chapter_id")

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
    body: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)

    conversation_id = int(body.get("conversation_id") or 0)
    content = str(body.get("content") or "").strip()
    if not conversation_id:
        raise HTTPException(400, "conversation_id is required")
    if not content:
        raise HTTPException(400, "content is required")

    conversation = _require_conversation(
        db,
        conversation_id=conversation_id,
        story_id=story_id,
        user_id=user.id,
    )
    persisted_conversation_id = conversation.id
    persisted_user_id = user.id

    current_chapter = None
    current_chapter_id = body.get("chapter_id")
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

    history = [{"role": item.role, "content": item.content} for item in conversation.messages]
    deepseek_api_key = _user_deepseek_api_key(request)
    _release_db_transaction(db)

    async def event_generator():
        from services.agent_service import agent_service, tool_registry

        tool_registry.current_story_id = story_id
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
            finally:
                write_db.close()

        try:
            async for event in agent_service.run_stream(
                messages=history,
                story_context=story_context,
                api_key=deepseek_api_key,
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
            if not assistant_saved:
                persist_assistant_message(f"错误: {exc}")
            yield {"event": "error", "data": json.dumps({"error": str(exc)}, ensure_ascii=False)}
        finally:
            tool_registry.current_story_id = None

    return EventSourceResponse(event_generator())


@router.post("/confirm")
def confirm_changes(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from services.agent_service import tool_registry

    _require_user(request, db)
    if tool_registry.pending_changes:
        tool_registry.pending_changes.clear()
    return {"ok": True, "message": "修改已确认"}


@router.post("/rollback")
def rollback_changes(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from services.agent_service import tool_registry

    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    if not tool_registry.pending_changes or not tool_registry.pending_changes.has_changes():
        return {"ok": True, "message": "没有待撤回的修改"}

    results = tool_registry.pending_changes.rollback(db)
    return {"ok": True, "results": results}


@router.get("/pending-changes")
def get_pending_changes(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from services.agent_service import tool_registry

    _require_user(request, db)
    if not tool_registry.pending_changes:
        return {"changes": []}
    return {"changes": tool_registry.pending_changes.get_full_data()}
