import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
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
    manga_asset_analysis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    manga_storyboard_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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
    active_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    active_run_started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
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


class AgentAttachment(Base):
    __tablename__ = "agent_attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agent_conversations.id"), nullable=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class AgentPendingChange(Base):
    __tablename__ = "agent_pending_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_conversations.id"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    field: Mapped[str] = mapped_column(String(120), nullable=False)
    old_value: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


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
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class MangaAsset(Base):
    __tablename__ = "manga_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class MangaAssetBinding(Base):
    __tablename__ = "manga_asset_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("manga_assets.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True, index=True)
    binding_role: Mapped[str] = mapped_column(String(20), nullable=False, default="character")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class Plan(Base):
    """历史套餐定义，仅用于兼容旧订单与旧数据。"""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    yearly_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="CNY")
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    features: Mapped[list["PlanFeature"]] = relationship("PlanFeature", back_populates="plan", cascade="all, delete-orphan")
    quota_rules: Mapped[list["PlanQuotaRule"]] = relationship("PlanQuotaRule", back_populates="plan", cascade="all, delete-orphan")


class PlanFeature(Base):
    """历史套餐能力，仅用于读取旧数据。"""

    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped["Plan"] = relationship("Plan", back_populates="features")


class PlanQuotaRule(Base):
    """历史套餐次数规则，仅用于读取旧数据。"""

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
    """历史订阅记录，不再作为当前权益来源。"""

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
    """历史次数用量，不再作为积分扣费来源。"""

    __tablename__ = "user_usage_monthly"
    __table_args__ = (UniqueConstraint("user_id", "feature_key", "period_key", name="uq_user_usage_monthly"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    used_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UserQuotaGrantMonthly(Base):
    """历史次数补发，不再作为积分余额来源。"""

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
    plan_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("plans.id"), nullable=True)
    points_product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("points_products.id"), nullable=True, index=True)
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


# ── 章节视频工作流（新流水线） ──────────────────────────


class ChapterVideoWorkflow(Base):
    """章节视频工作流 — 管理从章节正文到视频的完整流水线

    职责：编排章节正文 → 15s 分镜拆分 → 故事版生成 → 图生视频
    """
    __tablename__ = "chapter_video_workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_status: Mapped[str] = mapped_column(String(32), default="pending")

    # 配置
    character_reference_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    video_style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    style_reference_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_per_shot: Mapped[int] = mapped_column(Integer, default=15)

    # 进度
    total_shots: Mapped[int] = mapped_column(Integer, default=0)
    completed_shots: Mapped[int] = mapped_column(Integer, default=0)
    failed_shots: Mapped[int] = mapped_column(Integer, default=0)

    # 结果
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 短剧剧本
    screenplay_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenplay_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    screenplay_status: Mapped[str] = mapped_column(String(32), default="missing")
    screenplay_updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    screenplay_approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    screenplay_version: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    chapter: Mapped["Chapter"] = relationship("Chapter")
    story: Mapped["Story"] = relationship("Story")
    shots: Mapped[list["ChapterVideoShot"]] = relationship(
        "ChapterVideoShot",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ChapterVideoShot.shot_index",
    )


class ChapterVideoShot(Base):
    """章节视频工作流的 15 秒分镜 — 独立于传统 ScriptScene/VideoShot

    每个 shot 对应一个固定 15 秒的独立视频片段，直接由正文解析产生。
    """
    __tablename__ = "chapter_video_shots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapter_video_workflows.id"), nullable=False, index=True)
    shot_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # 原文信息
    source_text_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    time_of_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    characters: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    # 镜头内容
    story_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue_or_narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    motion_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    emotion_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    continuity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 短剧剧本关联
    screenplay_scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    screenplay_beat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    narrative_purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    beat_density: Mapped[str | None] = mapped_column(String(16), nullable=True)
    transition_to_next: Mapped[str | None] = mapped_column(String(32), nullable=True)
    continuity_json: Mapped[Any] = mapped_column(JSON, nullable=True)

    # Prompt
    storyboard_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    storyboard_prompt_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    storyboard_generation_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_prompts_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    scene_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    prop_prompts_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    key_props_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    scene_asset_candidates_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    # 引用
    character_reference_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    scene_reference_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    prop_reference_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    # 故事版结构化 JSON
    storyboard_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 图片和视频
    storyboard_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=15, nullable=False)

    # 状态
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    workflow: Mapped["ChapterVideoWorkflow"] = relationship("ChapterVideoWorkflow", back_populates="shots")


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
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    scene_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    prop_prompts_json: Mapped[Any] = mapped_column(JSON, nullable=True)
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
    source_asset_ids_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
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
    __table_args__ = (
        Index(
            "uq_background_tasks_active_manga_chapter",
            "chapter_id",
            unique=True,
            postgresql_where=text(
                "task_type = 'manga_generation' AND chapter_id IS NOT NULL "
                "AND status IN ('pending', 'running', 'retrying', 'cancel_requested')"
            ),
            sqlite_where=text(
                "task_type = 'manga_generation' AND chapter_id IS NOT NULL "
                "AND status IN ('pending', 'running', 'retrying', 'cancel_requested')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 关联实体（带索引）
    story_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    shot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 时间戳
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # 元数据
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 配额回退字段（异步任务失败时自动回退）
    quota_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    quota_feature_key: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    quota_amount: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    quota_period_key: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)


# ── 提示词模板系统 ──────────────────────────────────────


class PromptTemplate(Base):
    """提示词模板主表"""
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # 提示词内容
    framework_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    manga_style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 提示词参数
    framework_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    chapter_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    character_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    manga_style_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 状态与可见性
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")

    # 统计
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 分类
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    # 审核
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fork 来源（自引用外键）
    forked_from: Mapped[int | None] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=True)

    # 时间戳
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    author: Mapped["User"] = relationship("User", foreign_keys=[author_user_id])


class StoryTemplateBinding(Base):
    """作品-模板关联表"""
    __tablename__ = "story_template_bindings"
    __table_args__ = (UniqueConstraint("story_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=False)
    bound_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    # 关系
    story: Mapped["Story"] = relationship("Story")
    template: Mapped["PromptTemplate"] = relationship("PromptTemplate")


class TemplateLike(Base):
    """模板点赞记录表"""
    __tablename__ = "template_likes"
    __table_args__ = (UniqueConstraint("template_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


# ── 小说来源（爬取的小说） ──────────────────────────────

class NovelSource(Base):
    """外部爬取的小说来源"""
    __tablename__ = "novel_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_book_id: Mapped[str] = mapped_column(String(100), nullable=False)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_chapters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawled_chapters: Mapped[int] = mapped_column(Integer, default=0)
    crawl_status: Mapped[str] = mapped_column(String(20), default="pending")
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    story: Mapped["Story"] = relationship("Story")


# ── 拆书分析结果 ──────────────────────────────────────

class DeconstructionResult(Base):
    """拆书分析结果持久化"""
    __tablename__ = "deconstruction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(30), default="pending")
    current_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    framework_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    stages_completed: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    decon_range: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 试读模式下的章节数上限（如 100 = 仅前100章）

    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    golden_chapters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    chapter_summaries: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    characters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    character_relations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    plot_lines: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    rhythm: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    emotion_modules: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    worldbuilding: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    writing_style: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    writing_techniques: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    progress_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    story: Mapped["Story"] = relationship("Story")


# ── 独立拆书库（不绑定作品）──────────────────────────

class DeconstructionWork(Base):
    """独立拆书工作记录，不绑定 Story"""
    __tablename__ = "deconstruction_works"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="qidian")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_book_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_label: Mapped[str | None] = mapped_column(String(20), nullable=True)

    crawl_status: Mapped[str] = mapped_column(String(20), default="pending")
    total_chapters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawled_chapters: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    decon_status: Mapped[str] = mapped_column(String(30), default="not_started")
    current_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    framework_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    stages_completed: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    decon_range: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 试读模式的章节上限

    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    golden_chapters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    chapter_summaries: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    characters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    character_relations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    plot_lines: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    rhythm: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    emotion_modules: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    worldbuilding: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    writing_style: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    writing_techniques: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # 轻量作者风格画像
    author_style_status: Mapped[str] = mapped_column(String(30), default="not_started")
    author_style_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    author_style_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    author_style_report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_style_progress_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    progress_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DeconstructionChapter(Base):
    """拆书库章节内容（独立存储，不污染作品 chapters 表）"""
    __tablename__ = "deconstruction_chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("deconstruction_works.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class StoryDeconstructionRef(Base):
    """作品引用拆书结果（多对多关联）"""
    __tablename__ = "story_deconstruction_refs"
    __table_args__ = (UniqueConstraint("story_id", "work_id", name="uq_story_decon_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("deconstruction_works.id", ondelete="CASCADE"), nullable=False)
    applied_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    work: Mapped["DeconstructionWork"] = relationship("DeconstructionWork")


# ---------------------------------------------------------------------------
# 积分双轨：渠道 / 模型 / 积分账本 / 用户凭据
# ---------------------------------------------------------------------------


class AiChannel(Base):
    """上游 AI 渠道（Base URL + 平台 Key）"""

    __tablename__ = "ai_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    modality: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    platform_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_four: Mapped[str | None] = mapped_column(String(8), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    extra_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    models: Mapped[list["AiModel"]] = relationship("AiModel", back_populates="channel", cascade="all, delete-orphan")


class AiModel(Base):
    """平台模型目录"""

    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("channel_id", "model_key", name="uq_ai_models_channel_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("ai_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    model_key: Mapped[str] = mapped_column(String(191), nullable=False)
    display_name: Mapped[str] = mapped_column(String(191), nullable=False)
    intro_tag: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    modality: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capabilities_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    channel: Mapped["AiChannel"] = relationship("AiChannel", back_populates="models")
    prices: Mapped[list["AiModelPrice"]] = relationship("AiModelPrice", back_populates="model", cascade="all, delete-orphan")


class AiModelPrice(Base):
    """模型积分价格版本"""

    __tablename__ = "ai_model_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True)
    billing_type: Mapped[str] = mapped_column(String(32), nullable=False, default="per_call")
    price_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    valid_from: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    valid_to: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    model: Mapped["AiModel"] = relationship("AiModel", back_populates="prices")


class AiTaskDefault(Base):
    """业务任务默认模型"""

    __tablename__ = "ai_task_defaults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UserAiCredential(Base):
    """用户自有 API Key（加密）"""

    __tablename__ = "user_ai_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_four: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="empty")
    last_validated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UserAiModalityCredential(Base):
    """用户按 AI 模态保存的加密 API Key。"""

    __tablename__ = "user_ai_modality_credentials"
    __table_args__ = (
        CheckConstraint("modality IN ('text', 'image', 'video')", name="ck_user_ai_modality_credentials_modality"),
        UniqueConstraint("user_id", "modality", name="uq_user_ai_modality_credentials_user_modality"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(20), nullable=False)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_four: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="empty")
    last_validated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UserAiPreference(Base):
    """用户默认凭据模式与默认模型"""

    __tablename__ = "user_ai_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    credential_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="platform")
    default_text_model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_models.id"), nullable=True)
    default_image_model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_models.id"), nullable=True)
    default_video_model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_models.id"), nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PointsAccount(Base):
    """用户积分账户"""

    __tablename__ = "points_accounts"
    __table_args__ = (
        CheckConstraint("available_points >= 0", name="ck_points_accounts_available_nonnegative"),
        CheckConstraint("reserved_points >= 0", name="ck_points_accounts_reserved_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    available_points: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    reserved_points: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PointsLedgerEntry(Base):
    """积分流水（不可变追加）"""

    __tablename__ = "points_ledger_entries"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_points_ledger_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("points_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    usage_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class AiUsageEvent(Base):
    """一次逻辑 AI 请求用量事件"""

    __tablename__ = "ai_usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    story_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stories.id"), nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    credential_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="platform")
    model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_models.id"), nullable=True)
    model_key: Mapped[str | None] = mapped_column(String(191), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_channels.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    usage_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estimated_points: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    reserved_points: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    settled_points: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class CreationStudioJob(Base):
    """独立创作台中的一次图片或视频生成任务。"""

    __tablename__ = "creation_studio_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    generation_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="text_to_media")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_models.id"), nullable=True)
    model_key: Mapped[str | None] = mapped_column(String(191), nullable=True)
    parameters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    background_task_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    output_asset_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("creation_studio_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_of_job_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("creation_studio_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class CreationStudioAsset(Base):
    """创作台上传的参考素材或生成结果。"""

    __tablename__ = "creation_studio_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("creation_studio_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="image")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class CreationStudioJobInput(Base):
    """生成任务与参考素材之间的有序关联。"""

    __tablename__ = "creation_studio_job_inputs"
    __table_args__ = (UniqueConstraint("job_id", "asset_id", name="uq_creation_studio_job_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("creation_studio_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("creation_studio_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    input_role: Mapped[str] = mapped_column(String(32), nullable=False, default="reference")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class PointsProduct(Base):
    """可一次性购买的积分套餐。"""

    __tablename__ = "points_products"
    __table_args__ = (
        CheckConstraint("price_cny >= 0", name="ck_points_products_price_nonnegative"),
        CheckConstraint("points > 0", name="ck_points_products_points_positive"),
        CheckConstraint("bonus_points >= 0", name="ck_points_products_bonus_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    points: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    bonus_points: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
