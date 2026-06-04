import os

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from services.install import (
    build_database_url,
    build_redis_url,
    database_has_install_markers,
    detect_install_status,
    redact_url,
    write_env_updates,
)


def test_build_database_url_quotes_credentials_and_sslmode():
    url = build_database_url({
        "host": "localhost",
        "port": 5432,
        "database": "manga_novel",
        "username": "postgres",
        "password": "p@ ss",
        "sslmode": "require",
    })

    assert url == "postgresql://postgres:p%40%20ss@localhost:5432/manga_novel?sslmode=require"


def test_build_redis_url_quotes_credentials_and_tls():
    url = build_redis_url({
        "host": "127.0.0.1",
        "port": 6380,
        "db": 2,
        "username": "default",
        "password": "r@ ss",
        "tls": True,
    })

    assert url == "rediss://default:r%40%20ss@127.0.0.1:6380/2"


def test_redact_url_masks_password():
    assert redact_url("postgresql://user:secret@localhost:5432/db?sslmode=prefer") == (
        "postgresql://user:***@localhost:5432/db?sslmode=prefer"
    )
    assert redact_url("redis://:secret@localhost:6379/0") == "redis://:***@localhost:6379/0"


def test_write_env_updates_preserves_existing_values_and_creates_backup(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=keep\nDATABASE_URL=old\n", encoding="utf-8")

    result = write_env_updates({
        "DATABASE_URL": "new",
        "SYSTEM_INSTALLED": "true",
    }, env_path=env_path)

    content = env_path.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=keep" in content
    assert "DATABASE_URL=new" in content
    assert "SYSTEM_INSTALLED=true" in content
    assert result["backup_path"]
    assert os.path.exists(result["backup_path"])


def test_database_has_install_markers_for_existing_users():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("email", String),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(users.insert().values(id=1, email="admin@example.com"))

    assert database_has_install_markers(engine) is True
    assert detect_install_status(engine)["installed"] is True


def test_database_has_install_markers_for_existing_platform_settings():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    settings = Table(
        "platform_settings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("setting_key", String),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(settings.insert().values(id=1, setting_key="platform.site_name"))

    assert database_has_install_markers(engine) is True


def test_detect_install_status_handles_unreachable_database(monkeypatch):
    monkeypatch.setenv("SYSTEM_INSTALLED", "false")
    engine = create_engine("postgresql://missing:missing@127.0.0.1:1/missing")

    status = detect_install_status(engine)

    assert status["installed"] is False
    assert status["database_reachable"] is False
    assert status["database_error"]
