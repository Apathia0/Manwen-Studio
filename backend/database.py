import os
import logging
import shutil
from pathlib import Path
from typing import Any, Mapping

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


def init_db(*, run_migrations: bool | None = None, bind_engine=None, raise_errors: bool = False):
    target_engine = bind_engine or engine
    if run_migrations is None:
        run_migrations = _env_flag("RUN_STARTUP_MIGRATIONS", True)
    try:
        Base.metadata.create_all(bind=target_engine)
        if run_migrations:
            _migrate(target_engine)
        else:
            logger.info("跳过启动时数据库迁移（RUN_STARTUP_MIGRATIONS=false）")
    except Exception as exc:
        logger.warning("数据库初始化失败（将在下次启动时重试）: %s", exc)
        if raise_errors:
            raise


def _prepare_migration_conn(conn) -> None:
    from sqlalchemy import text

    try:
        conn.execute(text("SET lock_timeout = '5s'"))
        conn.execute(text("SET statement_timeout = '120s'"))
    except Exception as exc:
        logger.warning("Failed to configure migration timeouts: %s", exc)


def _ensure_varchar_column(
    conn: Any,
    table_name: str,
    column_name: str,
    cols_by_name: Mapping[str, Mapping[str, Any]],
    length: int = 64,
) -> None:
    """确保历史库中的列类型为 VARCHAR，兼容多 ID 字符串。"""
    from sqlalchemy import String, Text, text

    column = cols_by_name.get(column_name)
    if not column:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR({length})"))
        return

    column_type = column.get("type")
    if isinstance(column_type, (String, Text)):
        return

    if getattr(conn.dialect, "name", "") == "postgresql":
        alter_sql = (
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
            + f"TYPE VARCHAR({length}) USING {column_name}::text"
        )
        conn.execute(text(alter_sql))
    else:
        logger.warning(
            "跳过 %s.%s 类型迁移：当前数据库方言 %s 不支持自动 ALTER TYPE",
            table_name,
            column_name,
            getattr(conn.dialect, "name", "unknown"),
        )


def _migrate(target_engine=None):
    """Add missing columns to existing tables (poor-man's migration)."""
    from sqlalchemy import inspect, text
    db_engine = target_engine or engine
    insp = inspect(db_engine)
    if "stories" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("stories")}
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "title" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN title VARCHAR(255)"))
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
            if "screenplay_text" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN screenplay_text TEXT"))
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "email_verified" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT TRUE"))
                conn.execute(text("UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL"))
            if "allow_api_key_override" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN allow_api_key_override BOOLEAN DEFAULT FALSE"))
            if "allow_api_url_override" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN allow_api_url_override BOOLEAN DEFAULT FALSE"))
    if "background_tasks" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("background_tasks")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "quota_user_id" not in cols:
                conn.execute(text("ALTER TABLE background_tasks ADD COLUMN quota_user_id INTEGER"))
            if "quota_feature_key" not in cols:
                conn.execute(text("ALTER TABLE background_tasks ADD COLUMN quota_feature_key VARCHAR(128)"))
            if "quota_amount" not in cols:
                conn.execute(text("ALTER TABLE background_tasks ADD COLUMN quota_amount INTEGER DEFAULT 0"))
    _migrate_video_tables(db_engine)
    _migrate_video_character_tables(db_engine)
    _seed_video_style_presets(db_engine)
    _normalize_video_style_names(db_engine)
    _migrate_money_columns(db_engine)
    _cleanup_duplicate_chapters(db_engine)
    _cleanup_duplicate_manga_images(db_engine)
    _add_unique_constraints(db_engine)
    _migrate_prompt_templates(db_engine)
    _migrate_agent_pending_changes(db_engine)
    _migrate_deconstruction_tables(db_engine)


def _migrate_agent_pending_changes(target_engine=None):
    """agent_pending_changes 持久化待确认修改表"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)

    if "agent_pending_changes" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE agent_pending_changes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    story_id INTEGER NOT NULL REFERENCES stories(id),
                    conversation_id INTEGER NOT NULL REFERENCES agent_conversations(id),
                    change_type VARCHAR(40) NOT NULL,
                    record_id INTEGER NOT NULL,
                    display_name VARCHAR(255) NOT NULL DEFAULT '',
                    field VARCHAR(120) NOT NULL,
                    old_value JSON,
                    new_value JSON,
                    created_at TIMESTAMP NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS agent_pending_changes_user_id_idx ON agent_pending_changes (user_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS agent_pending_changes_story_id_idx ON agent_pending_changes (story_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS agent_pending_changes_conversation_id_idx ON agent_pending_changes (conversation_id)"))


def _migrate_money_columns(target_engine=None):
    """Migrate price/amount columns to fixed-point decimals for billing accuracy."""
    from sqlalchemy import text

    db_engine = target_engine or engine
    if db_engine.dialect.name != "postgresql":
        logger.warning("Skipping money column migration for non-PostgreSQL database: %s", db_engine.dialect.name)
        return

    with db_engine.begin() as conn:
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


def _cleanup_duplicate_manga_images(target_engine=None):
    """Keep the newest image record per chapter/image number and remove older duplicates."""
    from sqlalchemy import text

    db_engine = target_engine or engine
    with db_engine.begin() as conn:
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


def _chapter_score(chapter: Mapping[str, Any], has_dir: bool) -> tuple[int, int, int, int]:
    novel_score = 1 if chapter["novel_content"] else 0
    return (
        novel_score,
        int(chapter["message_count"] or 0),
        int(chapter["image_count"] or 0),
        1 if has_dir else 0,
    )


def _cleanup_duplicate_chapters(target_engine=None):
    """Keep the most content-rich chapter per story/chapter number and remove duplicates."""
    from sqlalchemy import text

    db_engine = target_engine or engine
    with db_engine.begin() as conn:
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


def _add_unique_constraints(target_engine=None):
    """Apply model unique constraints to existing PostgreSQL tables."""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    if db_engine.dialect.name != "postgresql":
        logger.warning("Skipping unique constraint migration for non-PostgreSQL database: %s", db_engine.dialect.name)
        return

    insp = inspect(db_engine)
    table_names = set(insp.get_table_names())
    if not {"chapters", "manga_images"}.issubset(table_names):
        return

    existing = {
        constraint["name"]
        for table in ("chapters", "manga_images")
        for constraint in insp.get_unique_constraints(table)
    }

    with db_engine.begin() as conn:
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


def _migrate_video_tables(target_engine=None):
    """Add missing columns to video-related tables (Phase 1 assets-driven workflow)."""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)
    video_shots_cols = {c["name"] for c in insp.get_columns("video_shots")} if "video_shots" in insp.get_table_names() else set()
    if video_shots_cols:
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE chapters ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))

    stories_cols = {c["name"] for c in insp.get_columns("stories")} if "stories" in insp.get_table_names() else set()
    if "video_style_preset_id" not in stories_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE stories ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))

    # 风格参考图字段迁移
    video_style_presets_cols = {c["name"] for c in insp.get_columns("video_style_presets")} if "video_style_presets" in insp.get_table_names() else set()
    if video_style_presets_cols and "image_url" not in video_style_presets_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_style_presets ADD COLUMN image_url VARCHAR(500)"))

    chapter_video_workflows_cols = {c["name"] for c in insp.get_columns("chapter_video_workflows")} if "chapter_video_workflows" in insp.get_table_names() else set()
    if chapter_video_workflows_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "style_reference_image_url" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN style_reference_image_url VARCHAR(500)"))
            if "screenplay_text" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN screenplay_text TEXT"))
            if "screenplay_json" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN screenplay_json JSON"))
            if "screenplay_status" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN screenplay_status VARCHAR(32) DEFAULT 'missing'"))
            if "screenplay_updated_at" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN screenplay_updated_at TIMESTAMP"))
            if "screenplay_approved_at" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN screenplay_approved_at TIMESTAMP"))
            if "screenplay_version" not in chapter_video_workflows_cols:
                conn.execute(text("ALTER TABLE chapter_video_workflows ADD COLUMN screenplay_version INTEGER DEFAULT 0"))

    script_scenes_cols = {c["name"] for c in insp.get_columns("script_scenes")} if "script_scenes" in insp.get_table_names() else set()
    if "concept_art_asset_id" not in script_scenes_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE script_scenes ADD COLUMN concept_art_asset_id INTEGER REFERENCES video_assets(id)"))

    if "shot_asset_bindings" not in insp.get_table_names():
        with db_engine.begin() as conn:
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
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN character_involvement TEXT"))
    if "scene_mood" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN scene_mood VARCHAR(50)"))
    if "scene_prompt" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN scene_prompt TEXT"))
    if "prop_prompts_json" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN prop_prompts_json JSON"))

    # chapter_video_shots 表迁移
    chapter_video_shots_columns = insp.get_columns("chapter_video_shots") if "chapter_video_shots" in insp.get_table_names() else []
    chapter_video_shots_cols_by_name = {c["name"]: c for c in chapter_video_shots_columns}
    chapter_video_shots_cols = set(chapter_video_shots_cols_by_name)
    if chapter_video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "scene_prompt" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN scene_prompt TEXT"))
            if "prop_prompts_json" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN prop_prompts_json JSON"))
            if "key_props_json" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN key_props_json JSON"))
            if "scene_asset_candidates_json" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN scene_asset_candidates_json JSON"))
            if "scene_reference_ids" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN scene_reference_ids JSON"))
            if "prop_reference_ids" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN prop_reference_ids JSON"))
            _ensure_varchar_column(conn, "chapter_video_shots", "screenplay_scene_id", chapter_video_shots_cols_by_name)
            _ensure_varchar_column(conn, "chapter_video_shots", "screenplay_beat_id", chapter_video_shots_cols_by_name)
            if "narrative_purpose" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN narrative_purpose VARCHAR(64)"))
            if "beat_density" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN beat_density VARCHAR(16)"))
            if "transition_to_next" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN transition_to_next VARCHAR(32)"))
            if "continuity_json" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN continuity_json JSON"))


def _seed_video_style_presets(target_engine=None):
    import json
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    try:
        insp = inspect(db_engine)
        if "video_style_presets" not in insp.get_table_names():
            return

        with db_engine.begin() as conn:
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
                            VALUES (:name, :category, :prompt_template, CAST(:image_style_params AS JSONB), CAST(:video_style_params AS JSONB), :sort_order)"""),
                    {k: json.dumps(v) if isinstance(v, dict) else v for k, v in preset.items()},
                )

            logger.info("Seeded %d default video style presets", len(presets))
    except Exception as exc:
        logger.warning("Failed to seed video style presets: %s", exc)


def _normalize_video_style_names(target_engine=None):
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

    db_engine = target_engine or engine
    try:
        insp = inspect(db_engine)
        tables = set(insp.get_table_names())
        with db_engine.begin() as conn:
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


def _migrate_video_character_tables(target_engine=None):
    """Story-level character library for video workflow (Phase 2)."""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)

    # stories.video_character_profiles
    stories_cols = {c["name"] for c in insp.get_columns("stories")} if "stories" in insp.get_table_names() else set()
    if stories_cols and "video_character_profiles" not in stories_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE stories ADD COLUMN video_character_profiles TEXT"))

    # story_character_versions table
    if "story_character_versions" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE story_character_versions (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    character_name VARCHAR(100) NOT NULL,
                    version_label VARCHAR(50) NOT NULL DEFAULT 'v1-默认',
                    appearance_card TEXT DEFAULT '',
                    ref_asset_id INTEGER REFERENCES video_assets(id),
                    is_default BOOLEAN DEFAULT FALSE,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(story_id, character_name, version_label)
                )
            """))


def _migrate_prompt_templates(target_engine=None):
    """创建提示词模板系统相关表（prompt_templates / story_template_bindings / template_likes）。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)

    # 1. 提示词模板主表
    if "prompt_templates" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE prompt_templates (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    author_user_id INTEGER NOT NULL REFERENCES users(id),
                    framework_prompt TEXT,
                    chapter_prompt TEXT,
                    character_prompt TEXT,
                    manga_style_prompt TEXT,
                    framework_params JSONB,
                    chapter_params JSONB,
                    character_params JSONB,
                    manga_style_params JSONB,
                    is_public BOOLEAN NOT NULL DEFAULT FALSE,
                    status VARCHAR(20) NOT NULL DEFAULT 'draft',
                    visibility VARCHAR(20) NOT NULL DEFAULT 'private',
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    like_count INTEGER NOT NULL DEFAULT 0,
                    category VARCHAR(50),
                    tags JSONB,
                    submitted_at TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by INTEGER REFERENCES users(id),
                    review_note TEXT,
                    forked_from INTEGER REFERENCES prompt_templates(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_templates_author ON prompt_templates(author_user_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_templates_status ON prompt_templates(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_templates_is_public ON prompt_templates(is_public)"))

    # 2. 作品-模板关联表
    if "story_template_bindings" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE story_template_bindings (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id),
                    template_id INTEGER NOT NULL REFERENCES prompt_templates(id),
                    bound_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(story_id)
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_story_template_bindings_story ON story_template_bindings(story_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_story_template_bindings_template ON story_template_bindings(template_id)"))

    # 3. 模板点赞记录表
    if "template_likes" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE template_likes (
                    id SERIAL PRIMARY KEY,
                    template_id INTEGER NOT NULL REFERENCES prompt_templates(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(template_id, user_id)
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_template_likes_template_id ON template_likes(template_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_template_likes_user_id ON template_likes(user_id)"))


def _migrate_deconstruction_tables(target_engine=None):
    """创建拆书相关表（novel_sources, deconstruction_results）"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)

    if "novel_sources" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE novel_sources (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id),
                    platform VARCHAR(20) NOT NULL,
                    source_url VARCHAR(500) NOT NULL,
                    source_book_id VARCHAR(100) NOT NULL,
                    author VARCHAR(100),
                    genre VARCHAR(100),
                    status VARCHAR(20),
                    total_chapters INTEGER,
                    crawled_chapters INTEGER DEFAULT 0,
                    crawl_status VARCHAR(20) DEFAULT 'pending',
                    word_count INTEGER,
                    metadata_json JSON,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_novel_sources_story_id ON novel_sources(story_id)"))
            conn.execute(text("CREATE INDEX ix_novel_sources_platform_book ON novel_sources(platform, source_book_id)"))

    if "deconstruction_results" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE deconstruction_results (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id),
                    status VARCHAR(20) DEFAULT 'pending',
                    current_stage INTEGER,
                    stages_completed JSON,
                    summary JSON,
                    golden_chapters JSON,
                    chapter_summaries JSON,
                    characters JSON,
                    character_relations JSON,
                    plot_lines JSON,
                    rhythm JSON,
                    emotion_modules JSON,
                    worldbuilding JSON,
                    report_markdown TEXT,
                    writing_style JSON,
                    writing_techniques JSON,
                    progress_markdown TEXT,
                    task_id VARCHAR(50),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_deconstruction_story_id ON deconstruction_results(story_id)"))
            conn.execute(text("CREATE INDEX ix_deconstruction_task_id ON deconstruction_results(task_id)"))
