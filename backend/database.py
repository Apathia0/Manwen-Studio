import os
import logging
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/manga_novel")
BASE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger("database")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=20,
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 60,
        "keepalives_interval": 10,
        "keepalives_count": 6,
        "connect_timeout": 10,
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db(request: Request):
    request_db = getattr(getattr(request, "state", None), "db", None)
    if request_db is not None:
        yield request_db
        return

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(*, run_migrations: bool | None = None):
    if run_migrations is None:
        run_migrations = _env_flag("RUN_STARTUP_MIGRATIONS", False)
    try:
        Base.metadata.create_all(bind=engine)
        if run_migrations:
            _migrate()
        else:
            logger.info("Skipping startup database migrations; set RUN_STARTUP_MIGRATIONS=true to enable.")
            # Keep lightweight data normalization even when migrations are disabled.
            _normalize_video_style_names()
    except Exception as exc:
        logger.warning("数据库初始化失败（将在下次启动时重试）: %s", exc)


def _prepare_migration_conn(conn) -> None:
    from sqlalchemy import text

    try:
        conn.execute(text("SET lock_timeout = '5s'"))
        conn.execute(text("SET statement_timeout = '120s'"))
    except Exception as exc:
        logger.warning("Failed to configure migration timeouts: %s", exc)


def _migrate():
    """Add missing columns to existing tables (poor-man's migration)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if "stories" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("stories")}
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "owner_user_id" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN owner_user_id INTEGER"))
            if "description" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN description TEXT DEFAULT ''"))
            if "cover_image" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN cover_image VARCHAR(500)"))
            if "character_profiles" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN character_profiles TEXT DEFAULT ''"))
            if "tags" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN tags JSON"))
            if "outline" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN outline JSON"))
            if "characters" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN characters JSON"))
            if "story_bible" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN story_bible JSON"))
            if "story_memory" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN story_memory JSON"))
            if "onboarding_completed" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN onboarding_completed BOOLEAN DEFAULT FALSE"))
                conn.execute(text("UPDATE stories SET onboarding_completed = FALSE WHERE onboarding_completed IS NULL"))
            if "source_type" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN source_type VARCHAR(20) DEFAULT 'manual'"))
                conn.execute(text("UPDATE stories SET source_type = 'manual' WHERE source_type IS NULL"))
            if "import_context_completed" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN import_context_completed BOOLEAN DEFAULT TRUE"))
                conn.execute(text("UPDATE stories SET import_context_completed = TRUE WHERE import_context_completed IS NULL"))
    if "chapters" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chapters")}
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "title" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN title VARCHAR(255)"))
            if "screenplay_text" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN screenplay_text TEXT"))
            if "content_source" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN content_source VARCHAR(20)"))
            if "act" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN act VARCHAR(20)"))
            if "key_events" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN key_events JSON"))
            if "quality_score" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN quality_score JSON"))
            if "memory_summary" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN memory_summary JSON"))
            if "status" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"))
            if "word_count" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN word_count INTEGER"))
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                UPDATE chapters
                SET content_source = CASE
                    WHEN novel_content IS NOT NULL AND btrim(novel_content) <> ''
                         AND (
                            SELECT COUNT(*) FROM chat_messages
                            WHERE chat_messages.chapter_id = chapters.id
                         ) = 1
                         AND EXISTS (
                            SELECT 1 FROM chat_messages
                            WHERE chat_messages.chapter_id = chapters.id
                              AND chat_messages.role = 'user'
                              AND chat_messages.content = chapters.novel_content
                         )
                    THEN 'import'
                    WHEN EXISTS (
                        SELECT 1 FROM chat_messages
                        WHERE chat_messages.chapter_id = chapters.id
                    )
                    THEN 'chat'
                    ELSE NULL
                END
                WHERE content_source IS NULL
            """))
    if "billing_orders" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("billing_orders")}
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "source" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN source VARCHAR(32) DEFAULT 'system'"))
            if "billing_cycle" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN billing_cycle VARCHAR(20) DEFAULT 'monthly'"))
            if "payment_provider" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN payment_provider VARCHAR(32) DEFAULT 'mock'"))
            if "payment_method" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN payment_method VARCHAR(32) DEFAULT 'mock_qr'"))
            if "operator_user_id" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN operator_user_id INTEGER"))
            if "note" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN note TEXT"))
            if "extra_json" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN extra_json JSON"))
            if "paid_at" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN paid_at TIMESTAMP"))
            if "expired_at" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN expired_at TIMESTAMP"))
    if "user_subscriptions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("user_subscriptions")}
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "billing_cycle" not in cols:
                conn.execute(text("ALTER TABLE user_subscriptions ADD COLUMN billing_cycle VARCHAR(20) DEFAULT 'monthly'"))
                conn.execute(text("UPDATE user_subscriptions SET billing_cycle = 'monthly' WHERE billing_cycle IS NULL"))
            if "current_period_start" not in cols:
                conn.execute(text("ALTER TABLE user_subscriptions ADD COLUMN current_period_start TIMESTAMP"))
            if "current_period_end" not in cols:
                conn.execute(text("ALTER TABLE user_subscriptions ADD COLUMN current_period_end TIMESTAMP"))
            if "expires_at" not in cols:
                conn.execute(text("ALTER TABLE user_subscriptions ADD COLUMN expires_at TIMESTAMP"))
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "email_verified" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT TRUE"))
                conn.execute(text("UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL"))
            if "allow_api_key_override" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN allow_api_key_override BOOLEAN DEFAULT FALSE"))
            if "allow_api_url_override" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN allow_api_url_override BOOLEAN DEFAULT FALSE"))
    _migrate_video_tables()
    _seed_video_style_presets()
    _normalize_video_style_names()
    _migrate_money_columns()
    _cleanup_duplicate_chapters()
    _cleanup_duplicate_manga_images()
    _add_unique_constraints()


def _migrate_money_columns():
    """Migrate price/amount columns to fixed-point decimals for billing accuracy."""
    from sqlalchemy import text

    if engine.dialect.name != "postgresql":
        logger.warning("Skipping money column migration for non-PostgreSQL database: %s", engine.dialect.name)
        return

    with engine.begin() as conn:
        _prepare_migration_conn(conn)
        conn.execute(text("""
            ALTER TABLE plans
            ALTER COLUMN monthly_price TYPE NUMERIC(10,2)
            USING ROUND(COALESCE(monthly_price, 0)::numeric, 2)
        """))
        conn.execute(text("""
            ALTER TABLE plans
            ALTER COLUMN yearly_price TYPE NUMERIC(10,2)
            USING CASE
                WHEN yearly_price IS NULL THEN NULL
                ELSE ROUND(yearly_price::numeric, 2)
            END
        """))
        conn.execute(text("""
            ALTER TABLE billing_orders
            ALTER COLUMN amount TYPE NUMERIC(10,2)
            USING ROUND(COALESCE(amount, 0)::numeric, 2)
        """))


def _migrate_video_tables():
    """Add missing columns to video-related tables (Phase 1 assets-driven workflow)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    video_shots_cols = {c["name"] for c in insp.get_columns("video_shots")} if "video_shots" in insp.get_table_names() else set()
    if video_shots_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "style_preset" not in video_shots_cols:
                conn.execute(text("ALTER TABLE video_shots ADD COLUMN style_preset VARCHAR(50)"))
            if "storyboard_asset_id" not in video_shots_cols:
                conn.execute(text("ALTER TABLE video_shots ADD COLUMN storyboard_asset_id INTEGER REFERENCES video_assets(id)"))
            if "storyboard_locked" not in video_shots_cols:
                conn.execute(text("ALTER TABLE video_shots ADD COLUMN storyboard_locked BOOLEAN DEFAULT FALSE"))
            if "first_frame_prompt" not in video_shots_cols:
                conn.execute(text("ALTER TABLE video_shots ADD COLUMN first_frame_prompt TEXT"))
            if "last_frame_prompt" not in video_shots_cols:
                conn.execute(text("ALTER TABLE video_shots ADD COLUMN last_frame_prompt TEXT"))
            if "character_prompts_json" not in video_shots_cols:
                conn.execute(text("ALTER TABLE video_shots ADD COLUMN character_prompts_json JSON"))

    video_assets_cols = {c["name"] for c in insp.get_columns("video_assets")} if "video_assets" in insp.get_table_names() else set()
    if video_assets_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "asset_subtype" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN asset_subtype VARCHAR(50)"))
            if "source_asset_ids_json" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN source_asset_ids_json JSON"))
            if "style_preset" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN style_preset VARCHAR(50)"))
            if "locked" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN locked BOOLEAN DEFAULT FALSE"))
            if "revision" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN revision INTEGER DEFAULT 1"))
                conn.execute(text("UPDATE video_assets SET revision = 1 WHERE revision IS NULL"))
            if "is_master" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN is_master BOOLEAN DEFAULT FALSE"))
            if "status" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN status VARCHAR(20) DEFAULT 'active'"))
                conn.execute(text("UPDATE video_assets SET status = 'active' WHERE status IS NULL"))
            if "hash_key" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN hash_key VARCHAR(64)"))

    # Usage scope fields for video_assets
    if video_assets_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "usage_scope" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN usage_scope VARCHAR(20) DEFAULT 'shot_only'"))
                conn.execute(text("UPDATE video_assets SET usage_scope = 'shot_only' WHERE usage_scope IS NULL"))
            if "inherit_to_next_shot" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN inherit_to_next_shot BOOLEAN DEFAULT FALSE"))
            if "source_type" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN source_type VARCHAR(20) DEFAULT 'ai_generated'"))
                conn.execute(text("UPDATE video_assets SET source_type = 'ai_generated' WHERE source_type IS NULL"))
            if "story_level_default" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN story_level_default BOOLEAN DEFAULT FALSE"))
            if "chapter_level_default" not in video_assets_cols:
                conn.execute(text("ALTER TABLE video_assets ADD COLUMN chapter_level_default BOOLEAN DEFAULT FALSE"))

    video_jobs_cols = {c["name"] for c in insp.get_columns("video_generation_jobs")} if "video_generation_jobs" in insp.get_table_names() else set()
    if video_jobs_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "input_mode" not in video_jobs_cols:
                conn.execute(text("ALTER TABLE video_generation_jobs ADD COLUMN input_mode VARCHAR(20)"))
            if "source_storyboard_asset_id" not in video_jobs_cols:
                conn.execute(text("ALTER TABLE video_generation_jobs ADD COLUMN source_storyboard_asset_id INTEGER REFERENCES video_assets(id)"))
            if "reference_asset_ids_json" not in video_jobs_cols:
                conn.execute(text("ALTER TABLE video_generation_jobs ADD COLUMN reference_asset_ids_json JSON"))
            if "provider_payload_json" not in video_jobs_cols:
                conn.execute(text("ALTER TABLE video_generation_jobs ADD COLUMN provider_payload_json JSON"))
            if "provider_result_json" not in video_jobs_cols:
                conn.execute(text("ALTER TABLE video_generation_jobs ADD COLUMN provider_result_json JSON"))
            if "retry_of_job_id" not in video_jobs_cols:
                conn.execute(text("ALTER TABLE video_generation_jobs ADD COLUMN retry_of_job_id INTEGER REFERENCES video_generation_jobs(id)"))

    rendered_clips_cols = {c["name"] for c in insp.get_columns("rendered_clips")} if "rendered_clips" in insp.get_table_names() else set()
    if rendered_clips_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "source_storyboard_asset_id" not in rendered_clips_cols:
                conn.execute(text("ALTER TABLE rendered_clips ADD COLUMN source_storyboard_asset_id INTEGER REFERENCES video_assets(id)"))
            if "style_preset" not in rendered_clips_cols:
                conn.execute(text("ALTER TABLE rendered_clips ADD COLUMN style_preset VARCHAR(50)"))
            if "continuity_score" not in rendered_clips_cols:
                conn.execute(text("ALTER TABLE rendered_clips ADD COLUMN continuity_score INTEGER"))
            if "quality_score" not in rendered_clips_cols:
                conn.execute(text("ALTER TABLE rendered_clips ADD COLUMN quality_score INTEGER"))
            if "review_status" not in rendered_clips_cols:
                conn.execute(text("ALTER TABLE rendered_clips ADD COLUMN review_status VARCHAR(20) DEFAULT 'pending'"))
                conn.execute(text("UPDATE rendered_clips SET review_status = 'pending' WHERE review_status IS NULL"))

    if "video_style_presets" not in insp.get_table_names():
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE video_style_presets (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    prompt_template TEXT,
                    image_style_params JSONB,
                    video_style_params JSONB,
                    sort_order INTEGER DEFAULT 0
                )
            """))

    chapters_cols = {c["name"] for c in insp.get_columns("chapters")} if "chapters" in insp.get_table_names() else set()
    if "video_style_preset_id" not in chapters_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE chapters ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))

    stories_cols = {c["name"] for c in insp.get_columns("stories")} if "stories" in insp.get_table_names() else set()
    if "video_style_preset_id" not in stories_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE stories ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))

    script_scenes_cols = {c["name"] for c in insp.get_columns("script_scenes")} if "script_scenes" in insp.get_table_names() else set()
    if "concept_art_asset_id" not in script_scenes_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE script_scenes ADD COLUMN concept_art_asset_id INTEGER REFERENCES video_assets(id)"))

    if "shot_asset_bindings" not in insp.get_table_names():
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE shot_asset_bindings (
                    id SERIAL PRIMARY KEY,
                    shot_id INTEGER NOT NULL REFERENCES video_shots(id),
                    asset_id INTEGER NOT NULL REFERENCES video_assets(id),
                    role VARCHAR(30) NOT NULL,
                    is_selected BOOLEAN DEFAULT FALSE,
                    selection_source VARCHAR(30) DEFAULT 'auto_recommended',
                    inherit_source_asset_id INTEGER REFERENCES video_assets(id),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_shot_asset_bindings_shot_id ON shot_asset_bindings(shot_id)"))

    if "character_involvement" not in video_shots_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN character_involvement TEXT"))
    if "scene_mood" not in video_shots_cols:
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN scene_mood VARCHAR(50)"))


def _seed_video_style_presets():
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        if "video_style_presets" not in insp.get_table_names():
            return

        with engine.begin() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM video_style_presets")).scalar()
            if count and count > 0:
                return

            presets = [
                {"name": "写实电影感", "category": "realistic", "prompt_template": "Realistic cinematic style, movie-grade lighting, natural colors, high detail, film grain", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "cinematic"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 1},
                {"name": "日式动漫风", "category": "anime", "prompt_template": "Japanese anime style, cel-shaded, vibrant colors, expressive eyes, clean line art, Studio Ghibli inspired", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "anime"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 2},
                {"name": "3A游戏渲染", "category": "game", "prompt_template": "AAA game cinematic render, Unreal Engine 5 quality, photorealistic textures, ray traced lighting, high polygon count", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "photorealistic"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 3},
                {"name": "水墨国风", "category": "artistic", "prompt_template": "Chinese ink wash painting style, brush stroke textures, minimalist composition, monochrome with subtle color accents, poetic atmosphere", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "ink-wash"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 4},
                {"name": "水彩手绘风", "category": "artistic", "prompt_template": "Watercolor illustration style, soft edges, paper texture visible, light and airy, hand-painted feel, gentle color palette", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "watercolor"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 5},
                {"name": "暗黑哥特风", "category": "artistic", "prompt_template": "Dark gothic style, dramatic shadows, muted color palette, high contrast, mysterious atmosphere, ornate details", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "dark"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 6},
                {"name": "复古胶片感", "category": "realistic", "prompt_template": "Vintage film look, 1970s cinema aesthetic, warm color grading, film grain, soft focus, retro lens flares", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "vintage"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 7},
                {"name": "科技赛博风", "category": "game", "prompt_template": "Cyberpunk sci-fi style, neon lights, dark urban environment, holographic displays, rain-slicked streets, futuristic technology", "image_style_params": {"model": "sd3.5", "size": "1920x1080", "style": "cyberpunk"}, "video_style_params": {"aspect_ratio": "16:9"}, "sort_order": 8},
            ]

            for preset in presets:
                conn.execute(
                    text("""INSERT INTO video_style_presets (name, category, prompt_template, image_style_params, video_style_params, sort_order)
                            VALUES (:name, :category, :prompt_template, :image_style_params::jsonb, :video_style_params::jsonb, :sort_order)"""),
                    preset,
                )

            logger.info("Seeded %d default video style presets", len(presets))
    except Exception as exc:
        logger.warning("Failed to seed video style presets: %s", exc)


def _normalize_video_style_names():
    """Normalize known legacy/typo style names across video workflow tables."""
    from sqlalchemy import inspect, text

    aliases = {
        "3A游戏渲析": "3A游戏渲染",
        "3A游戏滚析": "3A游戏渲染",
        "3D游戏渲染": "3A游戏渲染",
        "日式动漏风": "日式动漫风",
        "水壁国风": "水墨国风",
        "水彩手画风": "水彩手绘风",
        "科技赛模风": "科技赛博风",
    }
    canonical_by_sort_order = {
        1: "写实电影感",
        2: "日式动漫风",
        3: "3A游戏渲染",
        4: "水墨国风",
        5: "水彩手绘风",
        6: "暗黑哥特风",
        7: "复古胶片感",
        8: "科技赛博风",
    }

    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "video_style_presets" in tables:
                for sort_order, canonical_name in canonical_by_sort_order.items():
                    conn.execute(
                        text("UPDATE video_style_presets SET name = :name WHERE sort_order = :sort_order"),
                        {"sort_order": sort_order, "name": canonical_name},
                    )
            for old_name, new_name in aliases.items():
                if "video_style_presets" in tables:
                    conn.execute(
                        text("UPDATE video_style_presets SET name = :new_name WHERE name = :old_name"),
                        {"old_name": old_name, "new_name": new_name},
                    )
                if "video_shots" in tables:
                    conn.execute(
                        text("UPDATE video_shots SET style_preset = :new_name WHERE style_preset = :old_name"),
                        {"old_name": old_name, "new_name": new_name},
                    )
                if "video_assets" in tables:
                    conn.execute(
                        text("UPDATE video_assets SET style_preset = :new_name WHERE style_preset = :old_name"),
                        {"old_name": old_name, "new_name": new_name},
                    )
                if "rendered_clips" in tables:
                    conn.execute(
                        text("UPDATE rendered_clips SET style_preset = :new_name WHERE style_preset = :old_name"),
                        {"old_name": old_name, "new_name": new_name},
                    )
        logger.info("Normalized legacy video style names")
    except Exception as exc:
        logger.warning("Failed to normalize video style names: %s", exc)


def _safe_unlink(path: Path):
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete duplicate image file %s: %s", path, exc)


def _safe_rmtree(path: Path):
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError as exc:
        logger.warning("Failed to delete duplicate chapter directory %s: %s", path, exc)


def _cleanup_duplicate_manga_images():
    """Keep the newest image record per chapter/image number and remove older duplicates."""
    from sqlalchemy import text

    with engine.begin() as conn:
        groups = conn.execute(text("""
            SELECT chapter_id, image_number
            FROM manga_images
            GROUP BY chapter_id, image_number
            HAVING COUNT(*) > 1
        """)).mappings().all()

        for group in groups:
            rows = conn.execute(text("""
                SELECT id, image_path, created_at
                FROM manga_images
                WHERE chapter_id = :chapter_id AND image_number = :image_number
                ORDER BY created_at DESC NULLS LAST, id DESC
            """), dict(group)).mappings().all()
            for row in rows[1:]:
                _safe_unlink(BASE_DIR / row["image_path"])
                conn.execute(text("DELETE FROM manga_images WHERE id = :id"), {"id": row["id"]})
                logger.warning(
                    "Deleted duplicate manga image id=%s chapter_id=%s image_number=%s",
                    row["id"],
                    group["chapter_id"],
                    group["image_number"],
                )


def _chapter_score(chapter: dict, has_dir: bool) -> tuple[int, int, int, int]:
    novel_score = 1 if chapter["novel_content"] else 0
    return (
        novel_score,
        int(chapter["message_count"] or 0),
        int(chapter["image_count"] or 0),
        1 if has_dir else 0,
    )


def _cleanup_duplicate_chapters():
    """Keep the most content-rich chapter per story/chapter number and remove duplicates."""
    from sqlalchemy import text

    with engine.begin() as conn:
        groups = conn.execute(text("""
            SELECT story_id, chapter_number
            FROM chapters
            GROUP BY story_id, chapter_number
            HAVING COUNT(*) > 1
        """)).mappings().all()

        for group in groups:
            chapters = conn.execute(text("""
                SELECT
                    c.id,
                    c.novel_content,
                    c.created_at,
                    COUNT(DISTINCT cm.id) AS message_count,
                    COUNT(DISTINCT mi.id) AS image_count
                FROM chapters c
                LEFT JOIN chat_messages cm ON cm.chapter_id = c.id
                LEFT JOIN manga_images mi ON mi.chapter_id = c.id
                WHERE c.story_id = :story_id AND c.chapter_number = :chapter_number
                GROUP BY c.id
                ORDER BY c.created_at DESC NULLS LAST, c.id DESC
            """), dict(group)).mappings().all()

            def sort_key(chapter):
                has_dir = (BASE_DIR / "manga_outputs" / f"chapter_{chapter['id']}").exists()
                return (*_chapter_score(chapter, has_dir), chapter["created_at"], chapter["id"])

            keep = max(chapters, key=sort_key)
            for chapter in chapters:
                if chapter["id"] == keep["id"]:
                    continue
                images = conn.execute(text("""
                    SELECT image_path
                    FROM manga_images
                    WHERE chapter_id = :chapter_id
                """), {"chapter_id": chapter["id"]}).mappings().all()
                for image in images:
                    _safe_unlink(BASE_DIR / image["image_path"])
                _safe_rmtree(BASE_DIR / "manga_outputs" / f"chapter_{chapter['id']}")
                conn.execute(text("DELETE FROM chat_messages WHERE chapter_id = :chapter_id"), {"chapter_id": chapter["id"]})
                conn.execute(text("DELETE FROM manga_images WHERE chapter_id = :chapter_id"), {"chapter_id": chapter["id"]})
                conn.execute(text("DELETE FROM chapters WHERE id = :chapter_id"), {"chapter_id": chapter["id"]})
                logger.warning(
                    "Deleted duplicate chapter id=%s story_id=%s chapter_number=%s; kept id=%s",
                    chapter["id"],
                    group["story_id"],
                    group["chapter_number"],
                    keep["id"],
                )


def _add_unique_constraints():
    """Apply model unique constraints to existing PostgreSQL tables."""
    from sqlalchemy import inspect, text

    if engine.dialect.name != "postgresql":
        logger.warning("Skipping unique constraint migration for non-PostgreSQL database: %s", engine.dialect.name)
        return

    insp = inspect(engine)
    table_names = set(insp.get_table_names())
    if not {"chapters", "manga_images"}.issubset(table_names):
        return

    existing = {
        constraint["name"]
        for table in ("chapters", "manga_images")
        for constraint in insp.get_unique_constraints(table)
    }

    with engine.begin() as conn:
        if "uq_chapters_story_number" not in existing:
            conn.execute(text("""
                ALTER TABLE chapters
                ADD CONSTRAINT uq_chapters_story_number
                UNIQUE (story_id, chapter_number)
            """))
        if "uq_manga_images_chapter_number" not in existing:
            conn.execute(text("""
                ALTER TABLE manga_images
                ADD CONSTRAINT uq_manga_images_chapter_number
                UNIQUE (chapter_id, image_number)
            """))
