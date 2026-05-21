from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, model_validator


# --- Story ---
class StoryCreate(BaseModel):
    title: str = "未命名故事"
    description: str = ""


class StoryUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[dict[str, Any]] = None
    outline: Optional[dict[str, Any]] = None
    characters: Optional[list[dict[str, Any]]] = None


class OutlineChapterPlanPayload(BaseModel):
    title: str
    summary: Optional[str] = None
    key_events: Optional[list[str]] = None
    act: Optional[str] = None
    goal: Optional[str] = None
    conflict: Optional[str] = None
    hook: Optional[str] = None
    payoff: Optional[str] = None
    highlight: Optional[str] = None


class OutlineChapterPlanUpdate(BaseModel):
    mode: str
    target_chapter_number: Optional[int] = None
    after_chapter_number: Optional[int] = None
    chapter: OutlineChapterPlanPayload


class StoryOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = ""
    cover_image: Optional[str] = None
    tags: Optional[dict[str, Any]] = None
    outline: Optional[dict[str, Any]] = None
    characters: Optional[list[dict[str, Any]]] = None
    story_bible: Optional[dict[str, Any]] = None
    story_memory: Optional[dict[str, Any]] = None
    onboarding_completed: bool = False
    source_type: str = "manual"
    import_context_completed: bool = True
    has_character_profiles: bool = False
    has_ref_image: bool = False
    created_at: datetime.datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='before')
    @classmethod
    def _extract_computed_flags(cls, data):
        if hasattr(data, 'character_profiles'):
            cp = getattr(data, 'character_profiles', '') or ''
            d = dict(data.__dict__) if hasattr(data, '__dict__') else dict(data)
            d['has_character_profiles'] = bool(cp.strip())
            # Check for story-level ref image on disk
            story_id = getattr(data, 'id', None)
            if story_id:
                story_dir = Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}"
                ref_dir = story_dir / "ref_images"
                has_multi_ref = ref_dir.exists() and any(
                    p.is_file() and p.suffix.lower() == ".png"
                    for p in ref_dir.iterdir()
                )
                d['has_ref_image'] = has_multi_ref or (story_dir / "ref_image.png").exists()
            return d
        return data


# --- Chapter ---
class ChapterOut(BaseModel):
    id: int
    story_id: int
    chapter_number: int
    title: Optional[str] = None
    novel_content: Optional[str] = None
    content_source: Optional[str] = None
    act: Optional[str] = None
    key_events: Optional[list[Any]] = None
    quality_score: Optional[dict[str, Any]] = None
    memory_summary: Optional[dict[str, Any]] = None
    status: str = "pending"
    word_count: Optional[int] = None
    created_at: datetime.datetime
    messages: list[ChatMessageOut] = []
    images: list[MangaImageOut] = []

    model_config = {"from_attributes": True}


# --- Chat ---
class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: int
    chapter_id: int
    role: str
    content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AgentConversationCreateIn(BaseModel):
    title: Optional[str] = None
    chapter_id: Optional[int] = None


class AgentConversationMessageCreateIn(BaseModel):
    conversation_id: int
    content: str
    chapter_id: Optional[int] = None


class AgentConversationMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AgentConversationSummaryOut(BaseModel):
    id: int
    story_id: int
    chapter_id: Optional[int] = None
    title: str
    last_message_preview: str = ""
    message_count: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AgentConversationOut(BaseModel):
    id: int
    story_id: int
    chapter_id: Optional[int] = None
    title: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    messages: list[AgentConversationMessageOut] = []

    model_config = {"from_attributes": True}


# --- Manga ---
class MangaImageOut(BaseModel):
    id: int
    chapter_id: int
    image_number: int
    image_path: str
    prompt: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class GenerateNovelRequest(BaseModel):
    pass


class GenerateMangaRequest(BaseModel):
    pass


# --- Framework (InkAI) ---
class TagsSchema(BaseModel):
    type: Optional[str] = None
    theme: Optional[str] = None
    style: Optional[str] = None
    audience: Optional[str] = None


class CharacterSchema(BaseModel):
    name: str = ""
    role: str = ""
    big_five: Optional[dict[str, Any]] = None
    arc: Optional[dict[str, Any]] = None
    relationships: Optional[list[dict[str, Any]]] = None


class OutlineSchema(BaseModel):
    three_acts: Optional[list[dict[str, Any]]] = None
    themes: Optional[list[str]] = None
    foreshadowing: Optional[list[str]] = None


class QualityScoreSchema(BaseModel):
    content: Optional[int] = None
    writing: Optional[int] = None
    character: Optional[int] = None
    plot: Optional[int] = None
    overall: Optional[int] = None


class FrameworkGenerateResponse(BaseModel):
    tags: Optional[dict[str, Any]] = None
    characters: Optional[list[dict[str, Any]]] = None
    outline: Optional[dict[str, Any]] = None
    chapters: Optional[list[dict[str, Any]]] = None


class RewriteSelectionRequest(BaseModel):
    selected_text: str
    chapter_context: Optional[str] = None
    instruction: Optional[str] = None


class ChapterContentUpdate(BaseModel):
    content: str


class QualityAssessResponse(BaseModel):
    scores: Optional[QualityScoreSchema] = None
    suggestions: Optional[list[str]] = None
    overall_comment: Optional[str] = None


class ScenesFromSelectionRequest(BaseModel):
    selected_text: str
    chapter_context: Optional[str] = None
    character_profiles: Optional[str] = None
    page_count: int = 4


class ScenesFromSelectionResponse(BaseModel):
    scenes: list[dict[str, Any]] = []


# --- Import/Export ---
class ImportParseResponse(BaseModel):
    detected_title: str = ""
    chapters: list[ImportChapterInfo] = []
    total_word_count: int = 0


class ImportChapterInfo(BaseModel):
    chapter_number: int
    title: str = ""
    content: str = ""
    detection_method: str = "regex"  # "regex" | "ai"


class ImportCreateRequest(BaseModel):
    title: str
    description: str = ""
    chapters: list[ImportChapterCreate] = []
    analyze_framework: bool = True


class ImportChapterCreate(BaseModel):
    chapter_number: int
    title: str = ""
    content: str = ""
    act: str | None = None
    key_events: list[str] = []


class FrameworkAnalyzeResponse(BaseModel):
    tags: dict | None = None
    characters: list[dict] | None = None
    outline: dict | None = None


# ─── Onboarding / Story Bible ────────────────────────────────


class OnboardingMessageIn(BaseModel):
    """用户发送的引导对话消息"""
    messages: list[dict[str, str]]  # [{role, content}, ...]


class OnboardingConfirmIn(BaseModel):
    """确认引导结果"""
    messages: list[dict[str, str]]


class OnboardingMessageOut(BaseModel):
    """AI 引导回复"""
    reply: str
    collected_info: dict[str, Any] = {}
    step: int = 1
    total_steps: int = 5
    is_complete: bool = False
    creative_brief: dict[str, Any] | None = None


class CreativeBriefOut(BaseModel):
    """创意理解卡（用户确认前预览）"""
    project_positioning: str = ""
    genre: str = ""
    audience: str = ""
    tone: str = ""
    core_hook: str = ""
    one_line_premise: str = ""
    protagonist_core: str = ""
    main_conflict: str = ""
    longline_mystery: str = ""
    serial_length_target: str = ""
    must_keep_rules: list[str] = []
    reveal_strategy: str = ""
    pacing_strategy: str = ""


class StoryBibleSchema(BaseModel):
    """完整的 Story Bible 数据结构"""
    story_bible: dict[str, Any] = {}


class StoryBibleUpdate(BaseModel):
    """更新 Story Bible"""
    story_bible: dict[str, Any]


# Resolve forward references
ChapterOut.model_rebuild()
