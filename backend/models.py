import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled Story")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    character_profiles: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    video_character_profiles: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outline: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    characters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    story_bible: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    story_memory: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    import_context_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    video_style_preset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_style_presets.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    chapters: Mapped[list["Chapter"]] = relationship("Chapter", back_populates="story", order_by="Chapter.chapter_number", cascade="all, delete-orphan")
    agent_conversations: Mapped[list["AgentConversation"]] = relationship(
        "AgentConversation",
        back_populates="story",
        order_by="AgentConversation.updated_at.desc()",
        cascade="all, delete-orphan",
    )
    framework_snapshots: Mapped[list["FrameworkSnapshot"]] = relationship(
        "FrameworkSnapshot",
        back_populates="story",
        order_by="FrameworkSnapshot.created_at.desc()",
        cascade="all, delete-orphan",
    )

    @property
    def has_character_profiles(self) -> bool:
        return bool((self.character_profiles or "").strip())


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("story_id", "chapter_number", name="uq_chapters_story_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    novel_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenplay_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    act: Mapped[str | None] = mapped_column(String(20), nullable=True)
    key_events: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    quality_score: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    memory_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    video_style_preset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_style_presets.id"), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    story: Mapped["Story"] = relationship("Story", back_populates="chapters")
    video_style_preset: Mapped["VideoStylePreset | None"] = relationship("VideoStylePreset", foreign_keys=[video_style_preset_id])
    messages: Mapped[list["ChatMessage"]] = relationship("ChatMessage", back_populates="chapter", order_by="ChatMessage.created_at", cascade="all, delete-orphan")
    images: Mapped[list["MangaImage"]] = relationship("MangaImage", back_populates="chapter", order_by="MangaImage.image_number", cascade="all, delete-orphan")
    script_scenes: Mapped[list["ScriptScene"]] = relationship("ScriptScene", back_populates="chapter", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="messages")


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    story: Mapped["Story"] = relationship("Story", back_populates="agent_conversations")
    owner: Mapped["User"] = relationship("User", back_populates="agent_conversations")
    messages: Mapped[list["AgentConversationMessage"]] = relationship(
        "AgentConversationMessage",
        back_populates="conversation",
        order_by="AgentConversationMessage.created_at",
        cascade="all, delete-orphan",
    )


class StoryCharacterVersion(Base):
    __tablename__ = "story_character_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True)
    character_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version_label: Mapped[str] = mapped_column(String(50), nullable=False, default="v1-默认")
    appearance_card: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    ref_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("story_id", "character_name", "version_label"),
    )

    story: Mapped["Story"] = relationship("Story")


class AgentConversationMessage(Base):
    __tablename__ = "agent_conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["AgentConversation"] = relationship("AgentConversation", back_populates="messages")


class MangaImage(Base):
    __tablename__ = "manga_images"
    __table_args__ = (UniqueConstraint("chapter_id", "image_number", name="uq_manga_images_chapter_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False)
    image_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="images")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="User")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_api_key_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_api_url_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    agent_conversations: Mapped[list["AgentConversation"]] = relationship(
        "AgentConversation",
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    yearly_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="CNY")
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    features: Mapped[list["PlanFeature"]] = relationship("PlanFeature", back_populates="plan", cascade="all, delete-orphan")
    quota_rules: Mapped[list["PlanQuotaRule"]] = relationship("PlanQuotaRule", back_populates="plan", cascade="all, delete-orphan")


class PlanFeature(Base):
    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped["Plan"] = relationship("Plan", back_populates="features")


class PlanQuotaRule(Base):
    __tablename__ = "plan_quota_rules"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key", name="uq_plan_quota_feature_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reset_period: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    deduct_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="on_success")
    extra_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped["Plan"] = relationship("Plan", back_populates="quota_rules")


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_subscription_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    billing_cycle: Mapped[str | None] = mapped_column(String(20), nullable=True, default="monthly")
    current_period_start: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class UserUsageMonthly(Base):
    __tablename__ = "user_usage_monthly"
    __table_args__ = (UniqueConstraint("user_id", "feature_key", "period_key", name="uq_user_usage_monthly"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    used_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UserQuotaGrantMonthly(Base):
    __tablename__ = "user_quota_grants_monthly"
    __table_args__ = (UniqueConstraint("user_id", "feature_key", "period_key", name="uq_user_quota_grants_monthly"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class BillingOrder(Base):
    __tablename__ = "billing_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True, default="system")
    billing_cycle: Mapped[str | None] = mapped_column(String(20), nullable=True, default="monthly")
    payment_provider: Mapped[str | None] = mapped_column(String(32), nullable=True, default="mock")
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True, default="mock_qr")
    operator_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    paid_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


# ── 框架调整快照 ──────────────────────────────────────


class FrameworkSnapshot(Base):
    __tablename__ = "framework_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    snapshot_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="adjust")
    reply_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    story: Mapped["Story"] = relationship("Story", back_populates="framework_snapshots")


# ── 视频工作流模型 ──────────────────────────────────────


class ShotAssetBinding(Base):
    __tablename__ = "shot_asset_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shot_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_shots.id"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_source: Mapped[str] = mapped_column(String(30), default="auto_recommended")
    inherit_source_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class VideoStylePreset(Base):
    __tablename__ = "video_style_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_style_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    video_style_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ScriptScene(Base):
    __tablename__ = "script_scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    time_of_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    characters_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    voiceover: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estimated_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concept_art_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="chapter")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="script_scenes")
    shots: Mapped[list["VideoShot"]] = relationship("VideoShot", back_populates="scene", cascade="all, delete-orphan")


class VideoShot(Base):
    __tablename__ = "video_shots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(Integer, ForeignKey("script_scenes.id"), nullable=False, index=True)
    shot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shot_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    camera_angle: Mapped[str | None] = mapped_column(String(50), nullable=True)
    camera_movement: Mapped[str | None] = mapped_column(String(50), nullable=True)
    composition: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    sound_design: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_involvement: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_mood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    storyboard_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_frame_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_frame_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_prompts_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    continuity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    style_preset: Mapped[str | None] = mapped_column(String(50), nullable=True)
    storyboard_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=True)
    storyboard_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    scene: Mapped["ScriptScene"] = relationship("ScriptScene", back_populates="shots")
    generation_jobs: Mapped[list["VideoGenerationJob"]] = relationship("VideoGenerationJob", back_populates="shot", cascade="all, delete-orphan")
    rendered_clips: Mapped[list["RenderedClip"]] = relationship("RenderedClip", back_populates="shot", cascade="all, delete-orphan")


class VideoAsset(Base):
    __tablename__ = "video_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stories.id"), nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("script_scenes.id"), nullable=True)
    shot_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_shots.id"), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    asset_subtype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_asset_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    style_preset: Mapped[str | None] = mapped_column(String(50), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    hash_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_scope: Mapped[str] = mapped_column(String(20), default="shot_only")
    inherit_to_next_shot: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str] = mapped_column(String(20), default="ai_generated")
    story_level_default: Mapped[bool] = mapped_column(Boolean, default=False)
    chapter_level_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class VideoGenerationJob(Base):
    __tablename__ = "video_generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shot_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_shots.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(10), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_storyboard_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=True)
    reference_asset_ids_json: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    provider_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    retry_of_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_generation_jobs.id"), nullable=True)
    submitted_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    shot: Mapped["VideoShot"] = relationship("VideoShot", back_populates="generation_jobs")


class RenderedClip(Base):
    __tablename__ = "rendered_clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shot_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_shots.id"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_generation_jobs.id"), nullable=True)
    video_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_storyboard_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=True)
    style_preset: Mapped[str | None] = mapped_column(String(50), nullable=True)
    continuity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    shot: Mapped["VideoShot"] = relationship("VideoShot", back_populates="rendered_clips")


class VideoProject(Base):
    __tablename__ = "video_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timeline_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    subtitle_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    bgm_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class BackgroundTask(Base):
    """后台任务状态持久化"""
    __tablename__ = "background_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 关联实体
    story_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 时间戳
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # 元数据
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
