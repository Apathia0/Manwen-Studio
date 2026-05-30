class ShotAssetBinding(Base):
    __tablename__ = "shot_asset_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shot_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_shots.id"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_assets.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)  # character_reference, scene_reference, storyboard, first_frame, last_frame, style_reference
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_source: Mapped[str] = mapped_column(String(30), default="auto_recommended")  # auto_recommended, user_selected, inherited, global_default, story_default, chapter_default
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
    # 阶段1 新增字段：分镜图优先改造
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
    # 阶段1 新增字段
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
    # 阶段1 新增字段
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
    # 阶段1 新增字段
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

