import os

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from services.install import (
    build_database_url,
    build_redis_url,
    database_has_install_markers,
    detect_install_status,
    redact_url,
    request_backend_restart,
    validate_install_admin_config,
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


def test_validate_install_admin_config_normalizes_email_and_name():
    result = validate_install_admin_config({
        "name": "",
        "email": " Admin@Example.COM ",
        "password": "password123",
        "confirmPassword": "password123",
    })

    assert result == {
        "name": "系统管理员",
        "email": "admin@example.com",
        "password": "password123",
    }


def test_validate_install_admin_config_rejects_invalid_email_before_install_writes():
    try:
        validate_install_admin_config({
            "name": "Admin",
            "email": "not-an-email",
            "password": "password123",
            "confirmPassword": "password123",
        })
    except ValueError as exc:
        assert "邮箱格式" in str(exc)
    else:
        raise AssertionError("invalid email should be rejected")


def test_validate_install_admin_config_rejects_short_or_mismatched_password():
    for payload, message in [
        ({"email": "admin@example.com", "password": "short", "confirmPassword": "short"}, "至少"),
        ({"email": "admin@example.com", "password": "password123", "confirmPassword": "password456"}, "不一致"),
    ]:
        try:
            validate_install_admin_config(payload)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid admin payload should be rejected")


def test_request_backend_restart_uses_explicit_command(monkeypatch):
    calls = []
    monkeypatch.setenv("INSTALL_RESTART_COMMAND", "pm2 reload canvas-backend --update-env")
    monkeypatch.setattr("services.install._detached_popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("services.install._running_in_docker", lambda: True)

    result = request_backend_restart()

    assert result["mode"] == "command"
    assert calls[0][0] == ("pm2 reload canvas-backend --update-env",)
    assert calls[0][1]["shell"] is True


def test_request_backend_restart_uses_docker_container_exit(monkeypatch):
    calls = []
    monkeypatch.delenv("INSTALL_RESTART_COMMAND", raising=False)
    monkeypatch.delenv("INSTALL_PM2_PROCESS_NAME", raising=False)
    monkeypatch.setattr("services.install._pm2_restart_command", lambda: None)
    monkeypatch.setattr("services.install._running_in_docker", lambda: True)
    monkeypatch.setattr("services.install._exit_for_container_restart", lambda: calls.append("exit"))

    result = request_backend_restart()

    assert result["mode"] == "docker"
    assert calls == ["exit"]


def test_request_backend_restart_rejects_unmanaged_linux(monkeypatch):
    monkeypatch.delenv("INSTALL_RESTART_COMMAND", raising=False)
    monkeypatch.delenv("INSTALL_PM2_PROCESS_NAME", raising=False)
    monkeypatch.delenv("INSTALL_ALLOW_DEV_RESTART", raising=False)
    monkeypatch.setattr("services.install.os.name", "posix")
    monkeypatch.setattr("services.install._pm2_restart_command", lambda: None)
    monkeypatch.setattr("services.install._running_in_docker", lambda: False)

    try:
        request_backend_restart()
    except RuntimeError as exc:
        assert "Linux 部署" in str(exc)
    else:
        raise AssertionError("unmanaged Linux restart should require explicit configuration")


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


def test_write_env_updates_uses_updater_writer_in_docker(monkeypatch):
    calls = []
    monkeypatch.delenv("INSTALL_ENV_PATH", raising=False)
    monkeypatch.setattr("services.install._running_in_docker", lambda: True)
    monkeypatch.setenv("UPDATER_URL", "http://updater:8090")
    monkeypatch.setattr(
        "services.install._write_env_updates_via_updater",
        lambda updates: calls.append(updates) or {
            "env_path": "/opt/lorevista/.env",
            "backup_path": None,
            "env_writer": "updater",
        },
    )

    result = write_env_updates({"SYSTEM_INSTALLED": "true"})

    assert result["env_writer"] == "updater"
    assert result["env_path"] == "/opt/lorevista/.env"
    assert calls == [{"SYSTEM_INSTALLED": "true"}]
    assert os.environ["SYSTEM_INSTALLED"] == "true"


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
