import importlib
import logging
import os
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
        # 确保从迁移脚本直接调用 init_db 时，所有 ORM 表都已注册到元数据。
        importlib.import_module("models")
        if target_engine.dialect.name == "postgresql":
            _migrate(
                target_engine,
                create_schema=True,
                run_changes=run_migrations,
            )
            if not run_migrations:
                logger.info("跳过启动时数据库迁移（RUN_STARTUP_MIGRATIONS=false）")
        else:
            Base.metadata.create_all(bind=target_engine)
            if run_migrations:
                _migrate(target_engine)
            else:
                logger.info("跳过启动时数据库迁移（RUN_STARTUP_MIGRATIONS=false）")
        _assert_model_schema_present(target_engine)
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
    if isinstance(column_type, Text):
        return
    if isinstance(column_type, String) and not _varchar_length_is_below(column, length):
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


def _varchar_length_is_below(column: Mapping[str, Any] | None, minimum_length: int) -> bool:
    if not column:
        return False
    length = getattr(column.get("type"), "length", None)
    return isinstance(length, int) and length < minimum_length


def _assert_model_schema_present(target_engine=None) -> None:
    """确保数据库具备当前 ORM 模型声明的全部表和列。"""
    from sqlalchemy import inspect

    db_engine = target_engine or engine
    inspector = inspect(db_engine)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    missing_tables = sorted(expected_tables - actual_tables)
    missing_columns: list[str] = []

    for table_name in sorted(expected_tables & actual_tables):
        expected_columns = set(Base.metadata.tables[table_name].columns.keys())
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns.extend(
            f"{table_name}.{column_name}"
            for column_name in sorted(expected_columns - actual_columns)
        )

    if missing_tables or missing_columns:
        details = []
        if missing_tables:
            details.append("缺失表: " + ", ".join(missing_tables))
        if missing_columns:
            details.append("缺失列: " + ", ".join(missing_columns))
        raise RuntimeError("数据库结构未达到当前版本要求；" + "；".join(details))


def _migrate_legacy_video_channel_adapters(target_engine=None) -> None:
    """将历史视频渠道协议幂等迁移到 Lingdong，不改写其他渠道或未知值。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    inspector = inspect(db_engine)
    if "ai_channels" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ai_channels")}
    if not {"modality", "adapter_type"}.issubset(columns):
        return
    with db_engine.begin() as conn:
        _prepare_migration_conn(conn)
        conn.execute(text("""
            UPDATE ai_channels
            SET adapter_type = 'lingdong_video'
            WHERE modality = 'video'
              AND (
                  adapter_type IS NULL
                  OR trim(adapter_type) = ''
                  OR adapter_type = 'openai_compatible'
              )
        """))


def _migrate(
    target_engine=None,
    *,
    create_schema: bool = False,
    run_changes: bool = True,
):
    """串行执行增量迁移，避免多进程同时执行 inspect-then-alter。"""
    from sqlalchemy import text

    db_engine = target_engine or engine
    if db_engine.dialect.name != "postgresql":
        if create_schema:
            Base.metadata.create_all(bind=db_engine)
        if run_changes:
            return _migrate_unlocked(db_engine)
        return None
    with db_engine.connect() as lock_conn:
        lock_conn.execute(text("SET lock_timeout = '30s'"))
        lock_conn.execute(text("SET statement_timeout = '30s'"))
        lock_conn.execute(text("SELECT pg_advisory_lock(731945280164)"))
        try:
            if create_schema:
                Base.metadata.create_all(bind=db_engine)
            if run_changes:
                return _migrate_unlocked(db_engine)
            return None
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(731945280164)"))


def _migrate_unlocked(target_engine=None):
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
    _ensure_story_owner_integrity(db_engine)

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
            if "creation_pack_content" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN creation_pack_content TEXT"))
            if "creation_pack_version" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN creation_pack_version INTEGER DEFAULT 1"))
                conn.execute(text("UPDATE chapters SET creation_pack_version = 1 WHERE creation_pack_version IS NULL"))
            if "creation_pack_source_hash" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN creation_pack_source_hash VARCHAR(64)"))
            if "creation_pack_is_manual" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN creation_pack_is_manual BOOLEAN DEFAULT FALSE"))
                conn.execute(text("UPDATE chapters SET creation_pack_is_manual = FALSE WHERE creation_pack_is_manual IS NULL"))
            if "creation_pack_ai_generated" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN creation_pack_ai_generated BOOLEAN DEFAULT FALSE"))
                conn.execute(text("UPDATE chapters SET creation_pack_ai_generated = FALSE WHERE creation_pack_ai_generated IS NULL"))
            if "creation_pack_updated_at" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN creation_pack_updated_at TIMESTAMP"))
            if "manga_asset_analysis_json" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN manga_asset_analysis_json JSON"))
            if "manga_storyboard_json" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN manga_storyboard_json JSON"))
            if "manga_aspect_ratio" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN manga_aspect_ratio VARCHAR(10) DEFAULT '9:16'"))
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
            if "points_product_id" not in cols:
                conn.execute(text("ALTER TABLE billing_orders ADD COLUMN points_product_id INTEGER"))
            if db_engine.dialect.name == "postgresql":
                current_tables = set(inspect(db_engine).get_table_names())
                if "points_products" not in current_tables:
                    raise RuntimeError("积分商品表 points_products 未创建，拒绝添加 billing_orders 外键")
                conn.execute(text("ALTER TABLE billing_orders ALTER COLUMN plan_id DROP NOT NULL"))
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'billing_orders_points_product_id_fkey'
                              AND conrelid = 'billing_orders'::regclass
                        ) THEN
                            ALTER TABLE billing_orders
                            ADD CONSTRAINT billing_orders_points_product_id_fkey
                            FOREIGN KEY (points_product_id) REFERENCES points_products(id);
                        END IF;
                    END $$;
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_billing_orders_points_product_id ON billing_orders(points_product_id)"))
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
    if "email_verification_codes" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("email_verification_codes")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "attempt_count" not in cols:
                conn.execute(text("ALTER TABLE email_verification_codes ADD COLUMN attempt_count INTEGER DEFAULT 0 NOT NULL"))
    if "points_products" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("points_products")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "description" not in cols:
                conn.execute(text("ALTER TABLE points_products ADD COLUMN description TEXT"))
            if "is_recommended" not in cols:
                conn.execute(text("ALTER TABLE points_products ADD COLUMN is_recommended BOOLEAN DEFAULT FALSE"))
            if "updated_at" not in cols:
                conn.execute(text("ALTER TABLE points_products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
    if "ai_models" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("ai_models")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "intro_tag" not in cols:
                conn.execute(text("ALTER TABLE ai_models ADD COLUMN intro_tag VARCHAR(80) DEFAULT '' NOT NULL"))
    if "user_ai_credentials" in insp.get_table_names() and "user_ai_modality_credentials" in inspect(db_engine).get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            insert_prefix = "INSERT OR IGNORE" if db_engine.dialect.name == "sqlite" else "INSERT"
            conflict_suffix = "" if db_engine.dialect.name == "sqlite" else " ON CONFLICT (user_id, modality) DO NOTHING"
            conn.execute(text(f"""
                {insert_prefix} INTO user_ai_modality_credentials
                    (user_id, modality, secret_ciphertext, key_version, last_four, status, last_validated_at, updated_at)
                SELECT legacy.user_id, modalities.modality, legacy.secret_ciphertext, legacy.key_version,
                       legacy.last_four, legacy.status, legacy.last_validated_at, legacy.updated_at
                FROM user_ai_credentials AS legacy
                CROSS JOIN (
                    SELECT 'text' AS modality UNION ALL SELECT 'image' UNION ALL SELECT 'video'
                ) AS modalities
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM user_ai_modality_credentials AS existing
                    WHERE existing.user_id = legacy.user_id
                )
                {conflict_suffix}
            """))
    if "points_accounts" in insp.get_table_names() and db_engine.dialect.name == "postgresql":
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            invalid_accounts = conn.execute(text("""
                SELECT COUNT(*) FROM points_accounts
                WHERE available_points < 0 OR reserved_points < 0
            """)).scalar() or 0
            if invalid_accounts:
                raise RuntimeError(
                    f"发现 {invalid_accounts} 个历史负积分账户，请先完成账本对账和修正流水后再迁移"
                )
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_points_accounts_available_nonnegative'
                          AND conrelid = 'points_accounts'::regclass
                    ) THEN
                        ALTER TABLE points_accounts
                        ADD CONSTRAINT ck_points_accounts_available_nonnegative
                        CHECK (available_points >= 0);
                    END IF;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_points_accounts_reserved_nonnegative'
                          AND conrelid = 'points_accounts'::regclass
                    ) THEN
                        ALTER TABLE points_accounts
                        ADD CONSTRAINT ck_points_accounts_reserved_nonnegative
                        CHECK (reserved_points >= 0);
                    END IF;
                END $$;
            """))
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
            if "quota_period_key" not in cols:
                conn.execute(text("ALTER TABLE background_tasks ADD COLUMN quota_period_key VARCHAR(32)"))
            # 同章节只能有一个活动漫画任务。先终结历史重复记录，再建立部分唯一索引。
            conn.execute(text("""
                UPDATE background_tasks
                SET status = 'failed',
                    error_message = '检测到重复活动任务，系统已自动终结',
                    completed_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY chapter_id
                                   ORDER BY created_at DESC, id DESC
                               ) AS duplicate_rank
                        FROM background_tasks
                        WHERE task_type = 'manga_generation'
                          AND chapter_id IS NOT NULL
                          AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
                    ) ranked_tasks
                    WHERE duplicate_rank > 1
                )
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_background_tasks_active_manga_chapter
                ON background_tasks (chapter_id)
                WHERE task_type = 'manga_generation'
                  AND chapter_id IS NOT NULL
                  AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
            """))
            conn.execute(text("""
                UPDATE background_tasks
                SET status = 'failed',
                    error_message = '检测到重复章节生成任务，系统已自动终结',
                    completed_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY chapter_id
                                   ORDER BY created_at DESC, id DESC
                               ) AS duplicate_rank
                        FROM background_tasks
                        WHERE task_type = 'chapter_generation'
                          AND chapter_id IS NOT NULL
                          AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
                    ) ranked_tasks
                    WHERE duplicate_rank > 1
                )
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_background_tasks_active_chapter_generation
                ON background_tasks (chapter_id)
                WHERE task_type = 'chapter_generation'
                  AND chapter_id IS NOT NULL
                  AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
            """))
            # 知识同步和创作包刷新也必须在数据库层跨进程去重。
            # 先结束历史重复任务，再建立部分唯一索引，避免迁移因脏数据失败。
            conn.execute(text("""
                UPDATE background_tasks
                SET status = 'failed',
                    error_message = '检测到重复知识同步任务，系统已自动终结',
                    completed_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY story_id
                                   ORDER BY created_at DESC, id DESC
                               ) AS duplicate_rank
                        FROM background_tasks
                        WHERE task_type = 'knowledge_ai_sync'
                          AND story_id IS NOT NULL
                          AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
                    ) ranked_tasks
                    WHERE duplicate_rank > 1
                )
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_background_tasks_active_knowledge_sync
                ON background_tasks (story_id)
                WHERE task_type = 'knowledge_ai_sync'
                  AND story_id IS NOT NULL
                  AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
            """))
            conn.execute(text("""
                UPDATE background_tasks
                SET status = 'failed',
                    error_message = '检测到重复创作包更新任务，系统已自动终结',
                    completed_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY story_id
                                   ORDER BY created_at DESC, id DESC
                               ) AS duplicate_rank
                        FROM background_tasks
                        WHERE task_type = 'chapter_creation_pack_refresh'
                          AND story_id IS NOT NULL
                          AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
                    ) ranked_tasks
                    WHERE duplicate_rank > 1
                )
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_background_tasks_active_creation_pack_refresh
                ON background_tasks (story_id)
                WHERE task_type = 'chapter_creation_pack_refresh'
                  AND story_id IS NOT NULL
                  AND status IN ('pending', 'running', 'retrying', 'cancel_requested')
            """))
    _migrate_legacy_video_channel_adapters(db_engine)
    _migrate_video_tables(db_engine)
    _migrate_video_character_tables(db_engine)
    _seed_video_style_presets(db_engine)
    _migrate_storyboard_presets(db_engine)
    _normalize_video_style_names(db_engine)
    _migrate_money_columns(db_engine)
    _assert_no_duplicate_content(db_engine)
    _add_unique_constraints(db_engine)
    _migrate_prompt_templates(db_engine)
    _migrate_agent_pending_changes(db_engine)
    _migrate_story_knowledge_tables(db_engine)
    if "deconstruction_results" in insp.get_table_names():
        res_cols = {c["name"] for c in insp.get_columns("deconstruction_results")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "framework_type" not in res_cols:
                conn.execute(text("ALTER TABLE deconstruction_results ADD COLUMN framework_type VARCHAR(50)"))
            if "decon_range" not in res_cols:
                conn.execute(text("ALTER TABLE deconstruction_results ADD COLUMN decon_range INTEGER"))
            # 扩大 status 字段以容纳 paused_after_partial:N 格式
            res_status_col = next((c for c in insp.get_columns("deconstruction_results") if c["name"] == "status"), None)
            if db_engine.dialect.name == "postgresql" and _varchar_length_is_below(res_status_col, 30):
                conn.execute(text("ALTER TABLE deconstruction_results ALTER COLUMN status TYPE VARCHAR(30)"))

    if "deconstruction_works" in insp.get_table_names():
        works_cols = {c["name"] for c in insp.get_columns("deconstruction_works")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "framework_type" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN framework_type VARCHAR(50)"))
            if "decon_range" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN decon_range INTEGER"))
            # 扩大 status 字段
            works_status_col = next((c for c in insp.get_columns("deconstruction_works") if c["name"] == "decon_status"), None)
            if db_engine.dialect.name == "postgresql" and _varchar_length_is_below(works_status_col, 30):
                conn.execute(text("ALTER TABLE deconstruction_works ALTER COLUMN decon_status TYPE VARCHAR(30)"))

    _migrate_deconstruction_tables(db_engine)
    _migrate_deconstruction_library_tables(db_engine)
    _ensure_deconstruction_status_lengths(db_engine)


def _migrate_agent_pending_changes(target_engine=None):
    """迁移 Agent 待确认修改和对话运行占用字段。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)

    if "agent_conversations" in insp.get_table_names():
        conversation_cols = {column["name"] for column in insp.get_columns("agent_conversations")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "active_run_id" not in conversation_cols:
                conn.execute(text("ALTER TABLE agent_conversations ADD COLUMN active_run_id VARCHAR(64)"))
            if "active_run_started_at" not in conversation_cols:
                conn.execute(text("ALTER TABLE agent_conversations ADD COLUMN active_run_started_at TIMESTAMP"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS agent_conversations_active_run_id_idx "
                "ON agent_conversations (active_run_id)"
            ))

    if "agent_pending_changes" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE agent_pending_changes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    story_id INTEGER NOT NULL REFERENCES stories(id),
                    conversation_id INTEGER NOT NULL REFERENCES agent_conversations(id),
                    run_id VARCHAR(64),
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
            conn.execute(text("CREATE INDEX IF NOT EXISTS agent_pending_changes_run_id_idx ON agent_pending_changes (run_id)"))
        return

    pending_cols = {column["name"] for column in insp.get_columns("agent_pending_changes")}
    with db_engine.begin() as conn:
        _prepare_migration_conn(conn)
        if "run_id" not in pending_cols:
            conn.execute(text("ALTER TABLE agent_pending_changes ADD COLUMN run_id VARCHAR(64)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS agent_pending_changes_run_id_idx "
            "ON agent_pending_changes (run_id)"
        ))


def _migrate_story_knowledge_tables(target_engine=None) -> None:
    """创建数据库化作品知识表，并为作品补充知识版本号。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    inspector = inspect(db_engine)
    if "stories" in inspector.get_table_names():
        story_columns = {column["name"] for column in inspector.get_columns("stories")}
        if "knowledge_revision" not in story_columns:
            with db_engine.begin() as conn:
                _prepare_migration_conn(conn)
                conn.execute(text(
                    "ALTER TABLE stories ADD COLUMN knowledge_revision INTEGER DEFAULT 1 NOT NULL"
                ))

    for table_name in (
        "story_knowledge_categories",
        "story_knowledge_resources",
        "story_knowledge_entities",
        "story_knowledge_facts",
        "story_plot_threads",
        "agent_context_receipts",
    ):
        table = Base.metadata.tables.get(table_name)
        if table is not None:
            table.create(bind=db_engine, checkfirst=True)

    knowledge_columns = {
        "story_knowledge_entities": ("source_type", "source_id", "version"),
        "story_knowledge_facts": ("source_id", "version", "category_id"),
        "story_plot_threads": ("source_type", "source_id", "version", "category_id"),
    }
    for table_name, expected_columns in knowledge_columns.items():
        inspector = inspect(db_engine)
        if table_name not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "source_type" in expected_columns and "source_type" not in existing:
                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN source_type VARCHAR(30) DEFAULT 'system' NOT NULL"
                ))
            if "source_id" in expected_columns and "source_id" not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN source_id VARCHAR(120)"))
            if "version" in expected_columns and "version" not in existing:
                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN version INTEGER DEFAULT 1 NOT NULL"
                ))
            if "category_id" in expected_columns and "category_id" not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN category_id INTEGER"))

    if db_engine.dialect.name == "postgresql":
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_story_knowledge_resource_active_rank "
                "ON story_knowledge_resources (story_id, status, importance, updated_at)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_story_knowledge_entity_active_rank "
                "ON story_knowledge_entities (story_id, status, importance, id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_story_knowledge_fact_active_recent "
                "ON story_knowledge_facts (story_id, status, id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_story_plot_thread_active_payoff "
                "ON story_plot_threads (story_id, status, expected_payoff_from, expected_payoff_to)"
            ))
            try:
                with conn.begin_nested():
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            except Exception as exc:
                logger.warning("数据库无权启用 pg_trgm，作品知识检索将继续使用普通索引: %s", exc)
            has_pg_trgm = conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
            )).scalar()
            if has_pg_trgm:
                # gin_trgm_ops 操作符类可能位于非默认 schema（如扩展安装在 public 而当前
                # search_path 仅指向私有 schema），动态解析其实际 schema 并用限定名创建索引，
                # 避免 "operator class gin_trgm_ops does not exist" 的解析错误。
                trgm_opclass_schema = conn.execute(text(
                    "SELECT n.nspname FROM pg_opclass oc "
                    "JOIN pg_namespace n ON n.oid = oc.opcnamespace "
                    "WHERE oc.opcname = 'gin_trgm_ops' "
                    "ORDER BY (n.nspname = 'public') DESC, n.nspname "
                    "LIMIT 1"
                )).scalar()
                if not trgm_opclass_schema:
                    logger.warning("pg_trgm 已启用但找不到 gin_trgm_ops 操作符类，跳过模糊检索索引")
                else:
                    quoted_ops = f'"{trgm_opclass_schema}".gin_trgm_ops'
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_knowledge_entity_search_trgm "
                        f"ON story_knowledge_entities USING gin (canonical_name {quoted_ops})"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_knowledge_fact_search_trgm "
                        f"ON story_knowledge_facts USING gin (value_text {quoted_ops})"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_plot_thread_search_trgm "
                        f"ON story_plot_threads USING gin (title {quoted_ops})"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_plot_thread_description_trgm "
                        f"ON story_plot_threads USING gin (description {quoted_ops})"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_knowledge_resource_search_trgm "
                        f"ON story_knowledge_resources USING gin (title {quoted_ops})"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_knowledge_resource_summary_trgm "
                        f"ON story_knowledge_resources USING gin (summary {quoted_ops})"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_story_knowledge_resource_content_trgm "
                        f"ON story_knowledge_resources USING gin (content_text {quoted_ops})"
                    ))


def _migrate_money_columns(target_engine=None):
    """Migrate price/amount columns to fixed-point decimals for billing accuracy."""
    from sqlalchemy import text

    db_engine = target_engine or engine
    if db_engine.dialect.name != "postgresql":
        logger.warning("Skipping money column migration for non-PostgreSQL database: %s", db_engine.dialect.name)
        return

    from sqlalchemy import inspect

    table_names = set(inspect(db_engine).get_table_names())
    with db_engine.begin() as conn:
        _prepare_migration_conn(conn)
        if "plans" in table_names:
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
        if "billing_orders" in table_names:
            conn.execute(text("""
                ALTER TABLE billing_orders
                ALTER COLUMN amount TYPE NUMERIC(10,2)
                USING ROUND(COALESCE(amount, 0)::numeric, 2)
            """))


def _ensure_story_owner_integrity(target_engine=None) -> None:
    """为历史 stories.owner_user_id 补齐索引和外键约束。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    if not {"stories", "users"}.issubset(tables):
        return
    story_columns = {column["name"] for column in inspector.get_columns("stories")}
    if "owner_user_id" not in story_columns:
        return

    with db_engine.begin() as conn:
        _prepare_migration_conn(conn)
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_stories_owner_user_id "
            "ON stories(owner_user_id)"
        ))

        if db_engine.dialect.name != "postgresql":
            return

        foreign_keys = inspector.get_foreign_keys("stories")
        has_owner_foreign_key = any(
            foreign_key.get("constrained_columns") == ["owner_user_id"]
            and foreign_key.get("referred_table") == "users"
            for foreign_key in foreign_keys
        )
        if has_owner_foreign_key:
            return

        orphan_count = int(conn.execute(text("""
            SELECT COUNT(*)
            FROM stories AS s
            LEFT JOIN users AS u ON u.id = s.owner_user_id
            WHERE s.owner_user_id IS NOT NULL AND u.id IS NULL
        """)).scalar() or 0)
        conn.execute(text("""
            ALTER TABLE stories
            ADD CONSTRAINT stories_owner_user_id_fkey
            FOREIGN KEY (owner_user_id) REFERENCES users(id) NOT VALID
        """))
        if orphan_count == 0:
            conn.execute(text("""
                ALTER TABLE stories
                VALIDATE CONSTRAINT stories_owner_user_id_fkey
            """))
        else:
            logger.warning(
                "stories.owner_user_id 存在 %s 条孤儿引用；已约束新写入，历史数据需人工对账后再验证约束",
                orphan_count,
            )

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


def _assert_no_duplicate_content(target_engine=None) -> None:
    """阻止自动迁移删除重复内容，要求先完成可恢复的人工对账。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    table_names = set(inspect(db_engine).get_table_names())
    checks = []
    if "chapters" in table_names:
        checks.append(("章节", "SELECT COUNT(*) FROM (SELECT 1 FROM chapters GROUP BY story_id, chapter_number HAVING COUNT(*) > 1) AS duplicates"))
    if "manga_images" in table_names:
        checks.append(("漫画图片", "SELECT COUNT(*) FROM (SELECT 1 FROM manga_images GROUP BY chapter_id, image_number HAVING COUNT(*) > 1) AS duplicates"))
    if not checks:
        return
    with db_engine.connect() as conn:
        conflicts = [(label, int(conn.execute(text(sql)).scalar() or 0)) for label, sql in checks]
    found = [f"{label} {count} 组" for label, count in conflicts if count > 0]
    if found:
        raise RuntimeError(
            "检测到重复内容（" + "，".join(found) + "）；自动迁移禁止删除用户数据，请先备份并人工对账"
        )


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
    table_names = set(insp.get_table_names())
    video_shots_cols = {c["name"] for c in insp.get_columns("video_shots")} if "video_shots" in table_names else set()
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

    video_assets_cols = {c["name"] for c in insp.get_columns("video_assets")} if "video_assets" in table_names else set()
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

    video_jobs_cols = {c["name"] for c in insp.get_columns("video_generation_jobs")} if "video_generation_jobs" in table_names else set()
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

    rendered_clips_cols = {c["name"] for c in insp.get_columns("rendered_clips")} if "rendered_clips" in table_names else set()
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

    if "video_style_presets" not in table_names:
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
                    sort_order INTEGER DEFAULT 0,
                    image_url VARCHAR(500)
                )
            """))

    insp = inspect(db_engine)
    table_names = set(insp.get_table_names())
    chapters_cols = {c["name"] for c in insp.get_columns("chapters")} if "chapters" in table_names else set()
    if chapters_cols and "video_style_preset_id" not in chapters_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE chapters ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))

    stories_cols = {c["name"] for c in insp.get_columns("stories")} if "stories" in table_names else set()
    if stories_cols and "video_style_preset_id" not in stories_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE stories ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))

    # 风格参考图字段迁移
    video_style_presets_cols = {c["name"] for c in insp.get_columns("video_style_presets")} if "video_style_presets" in table_names else set()
    if video_style_presets_cols and "image_url" not in video_style_presets_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_style_presets ADD COLUMN image_url VARCHAR(500)"))

    chapter_video_workflows_cols = {c["name"] for c in insp.get_columns("chapter_video_workflows")} if "chapter_video_workflows" in table_names else set()
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

    script_scenes_cols = {c["name"] for c in insp.get_columns("script_scenes")} if "script_scenes" in table_names else set()
    if script_scenes_cols and "concept_art_asset_id" not in script_scenes_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE script_scenes ADD COLUMN concept_art_asset_id INTEGER REFERENCES video_assets(id)"))

    if {"video_shots", "video_assets"}.issubset(table_names) and "shot_asset_bindings" not in table_names:
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

    if video_shots_cols and "character_involvement" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN character_involvement TEXT"))
    if video_shots_cols and "scene_mood" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN scene_mood VARCHAR(50)"))
    if video_shots_cols and "scene_prompt" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN scene_prompt TEXT"))
    if video_shots_cols and "prop_prompts_json" not in video_shots_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("ALTER TABLE video_shots ADD COLUMN prop_prompts_json JSON"))

    # chapter_video_shots 表迁移
    chapter_video_shots_columns = insp.get_columns("chapter_video_shots") if "chapter_video_shots" in table_names else []
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
            if "duration_seconds" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN duration_seconds INTEGER DEFAULT 15"))
            conn.execute(text("UPDATE chapter_video_shots SET duration_seconds = 15 WHERE duration_seconds IS NULL"))
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
            if "storyboard_prompt_stale" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN storyboard_prompt_stale BOOLEAN DEFAULT FALSE"))
            if "storyboard_generation_token" not in chapter_video_shots_cols:
                conn.execute(text("ALTER TABLE chapter_video_shots ADD COLUMN storyboard_generation_token VARCHAR(64)"))
            conn.execute(text("UPDATE chapter_video_shots SET storyboard_prompt_stale = FALSE WHERE storyboard_prompt_stale IS NULL"))


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
        raise


def _migrate_storyboard_presets(target_engine=None):
    """创建漫画分镜提示词预设表并补充作品绑定字段。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)
    table_names = set(insp.get_table_names())
    if "storyboard_prompt_presets" not in table_names:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE storyboard_prompt_presets (
                    id SERIAL PRIMARY KEY,
                    preset_key VARCHAR(64),
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    prompt_template TEXT NOT NULL,
                    system_prompt TEXT,
                    is_system BOOLEAN DEFAULT FALSE,
                    story_id INTEGER REFERENCES stories(id),
                    author_user_id INTEGER REFERENCES users(id),
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    insp = inspect(db_engine)
    table_names = set(insp.get_table_names())
    preset_cols = {
        column["name"]
        for column in insp.get_columns("storyboard_prompt_presets")
    } if "storyboard_prompt_presets" in table_names else set()
    if "storyboard_prompt_presets" in table_names:
        missing_preset_columns = {
            "preset_key": "VARCHAR(64)",
            "author_user_id": "INTEGER REFERENCES users(id)",
            "story_id": "INTEGER REFERENCES stories(id)",
            "sort_order": "INTEGER DEFAULT 0",
        }
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            for column_name, column_sql in missing_preset_columns.items():
                if column_name not in preset_cols:
                    conn.execute(text(
                        f"ALTER TABLE storyboard_prompt_presets "
                        f"ADD COLUMN {column_name} {column_sql}"
                    ))

        insp = inspect(db_engine)
        preset_cols = {
            column["name"]
            for column in insp.get_columns("storyboard_prompt_presets")
        }
    stories_cols = {
        column["name"] for column in insp.get_columns("stories")
    } if "stories" in table_names else set()
    if stories_cols and "storyboard_preset_id" not in stories_cols:
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text(
                "ALTER TABLE stories ADD COLUMN storyboard_preset_id "
                "INTEGER REFERENCES storyboard_prompt_presets(id)"
            ))

    # 将旧版作品级模板升级为用户级模板；无法确认作品所有者的数据继续保留旧归属。
    if (
        "storyboard_prompt_presets" in table_names
        and "stories" in table_names
        and "owner_user_id" in stories_cols
    ):
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                UPDATE storyboard_prompt_presets
                SET author_user_id = (
                    SELECT stories.owner_user_id
                    FROM stories
                    WHERE stories.id = storyboard_prompt_presets.story_id
                )
                WHERE is_system = FALSE
                  AND story_id IS NOT NULL
                  AND (
                      SELECT stories.owner_user_id
                      FROM stories
                      WHERE stories.id = storyboard_prompt_presets.story_id
                  ) IS NOT NULL
            """))
            conn.execute(text("""
                UPDATE storyboard_prompt_presets
                SET story_id = NULL
                WHERE is_system = FALSE
                  AND author_user_id IS NOT NULL
                  AND story_id IS NOT NULL
                  AND author_user_id = (
                      SELECT stories.owner_user_id
                      FROM stories
                      WHERE stories.id = storyboard_prompt_presets.story_id
                  )
            """))

    with db_engine.begin() as conn:
        _prepare_migration_conn(conn)
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_storyboard_prompt_presets_author_user_id "
            "ON storyboard_prompt_presets (author_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_storyboard_prompt_presets_user_order "
            "ON storyboard_prompt_presets (author_user_id, sort_order, id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_storyboard_prompt_presets_preset_key "
            "ON storyboard_prompt_presets (preset_key)"
        ))
        if "stories" in table_names:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_stories_storyboard_preset_id "
                "ON stories (storyboard_preset_id)"
            ))

    _seed_storyboard_presets(db_engine)


def _seed_storyboard_presets(target_engine=None):
    """从安装种子数据幂等写入系统分镜模板，运行时以数据库内容为准。"""
    import json

    from sqlalchemy import inspect, text

    seed_path = BASE_DIR / "seed_data" / "storyboard_presets.json"
    try:
        system_presets = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取分镜模板数据库种子: {seed_path}") from exc
    if not isinstance(system_presets, list):
        raise RuntimeError("分镜模板数据库种子必须是数组")

    db_engine = target_engine or engine
    insp = inspect(db_engine)
    if "storyboard_prompt_presets" not in insp.get_table_names():
        return

    with db_engine.begin() as conn:
        for preset in system_presets:
            if not isinstance(preset, dict):
                raise RuntimeError("分镜模板数据库种子包含无效记录")
            required_fields = ("preset_key", "name", "prompt_template", "system_prompt", "sort_order")
            if any(not preset.get(field) for field in required_fields):
                raise RuntimeError(f"分镜模板数据库种子字段不完整: {preset.get('preset_key') or 'unknown'}")
            preset_exists = conn.execute(
                text("""
                    SELECT 1
                    FROM storyboard_prompt_presets
                    WHERE is_system = TRUE AND preset_key = :preset_key
                    LIMIT 1
                """),
                {"preset_key": preset["preset_key"]},
            ).scalar()
            if preset_exists is not None:
                continue
            legacy_exists = conn.execute(
                text("""
                    SELECT 1
                    FROM storyboard_prompt_presets
                    WHERE is_system = TRUE
                      AND preset_key IS NULL
                      AND name = :name
                    LIMIT 1
                """),
                {"name": preset["name"]},
            ).scalar()
            if legacy_exists is not None:
                conn.execute(
                    text("""
                        UPDATE storyboard_prompt_presets
                        SET preset_key = :preset_key
                        WHERE is_system = TRUE
                          AND preset_key IS NULL
                          AND name = :name
                    """),
                    {"preset_key": preset["preset_key"], "name": preset["name"]},
                )
                continue
            conn.execute(
                text("""
                    INSERT INTO storyboard_prompt_presets (
                        preset_key, name, description, prompt_template,
                        system_prompt, is_system, sort_order
                    ) VALUES (
                        :preset_key, :name, :description, :prompt_template,
                        :system_prompt, TRUE, :sort_order
                    )
                """),
                preset,
            )
            logger.info("Seeded system storyboard prompt preset: %s", preset["preset_key"])


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
        raise


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


def _ensure_deconstruction_status_lengths(target_engine=None) -> None:
    """确保拆书状态字段可以容纳 paused_after_partial:N。"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    if db_engine.dialect.name != "postgresql":
        return

    inspector = inspect(db_engine)
    table_columns = (
        ("deconstruction_results", "status"),
        ("deconstruction_works", "decon_status"),
    )
    tables = set(inspector.get_table_names())
    with db_engine.begin() as conn:
        _prepare_migration_conn(conn)
        for table_name, column_name in table_columns:
            if table_name not in tables:
                continue
            column = next(
                (item for item in inspector.get_columns(table_name) if item["name"] == column_name),
                None,
            )
            if _varchar_length_is_below(column, 30):
                conn.execute(text(
                    f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE VARCHAR(30)"
                ))


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
                    status VARCHAR(30) DEFAULT 'pending',
                    current_stage INTEGER,
                    framework_type VARCHAR(50),
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


def _migrate_deconstruction_library_tables(target_engine=None):
    """创建独立拆书库表（deconstruction_works, deconstruction_chapters, story_deconstruction_refs）"""
    from sqlalchemy import inspect, text

    db_engine = target_engine or engine
    insp = inspect(db_engine)

    if "deconstruction_works" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE deconstruction_works (
                    id SERIAL PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL REFERENCES users(id),
                    title VARCHAR(255) NOT NULL,
                    author VARCHAR(100),
                    platform VARCHAR(20) NOT NULL DEFAULT 'qidian',
                    source_url VARCHAR(500),
                    source_book_id VARCHAR(100),
                    genre VARCHAR(100),
                    status_label VARCHAR(20),
                    crawl_status VARCHAR(20) DEFAULT 'pending',
                    total_chapters INTEGER,
                    crawled_chapters INTEGER DEFAULT 0,
                    word_count INTEGER,
                    decon_status VARCHAR(30) DEFAULT 'not_started',
                    current_stage INTEGER,
                    framework_type VARCHAR(50),
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
                    author_style_status VARCHAR(30) DEFAULT 'not_started',
                    author_style_task_id VARCHAR(80),
                    author_style_profile JSON,
                    author_style_report_markdown TEXT,
                    author_style_progress_markdown TEXT,
                    progress_markdown TEXT,
                    task_id VARCHAR(50),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_decon_works_owner ON deconstruction_works(owner_user_id)"))
            conn.execute(text("CREATE INDEX ix_decon_works_task_id ON deconstruction_works(task_id)"))

    if "deconstruction_chapters" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE deconstruction_chapters (
                    id SERIAL PRIMARY KEY,
                    work_id INTEGER NOT NULL REFERENCES deconstruction_works(id) ON DELETE CASCADE,
                    chapter_number INTEGER NOT NULL,
                    title VARCHAR(500),
                    content TEXT,
                    word_count INTEGER DEFAULT 0,
                    source_url VARCHAR(500),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_decon_chapters_work ON deconstruction_chapters(work_id)"))

    if "story_deconstruction_refs" not in insp.get_table_names():
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE story_deconstruction_refs (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    work_id INTEGER NOT NULL REFERENCES deconstruction_works(id) ON DELETE CASCADE,
                    applied_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_story_decon_ref UNIQUE (story_id, work_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_story_decon_refs_story ON story_deconstruction_refs(story_id)"))

    refreshed_insp = inspect(db_engine)
    if "deconstruction_works" in refreshed_insp.get_table_names():
        works_cols = {c["name"] for c in refreshed_insp.get_columns("deconstruction_works")}
        with db_engine.begin() as conn:
            _prepare_migration_conn(conn)
            if "author_style_status" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_status VARCHAR(30) DEFAULT 'not_started'"))
            if "author_style_task_id" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_task_id VARCHAR(80)"))
            if "author_style_profile" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_profile JSON"))
            if "author_style_report_markdown" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_report_markdown TEXT"))
            if "author_style_progress_markdown" not in works_cols:
                conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_progress_markdown TEXT"))
