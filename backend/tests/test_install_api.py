import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from database import Base
import main


def test_health_check_requires_completed_startup(monkeypatch):
    monkeypatch.setattr(main, "_refresh_install_status", lambda: {
        "installed": True,
        "requires_restart": False,
        "database_reachable": True,
    })
    monkeypatch.setattr(main, "SYSTEM_READY", False)

    result = main.health_check()

    assert result.status_code == 503
    assert b'"system_ready":false' in result.body


def test_health_check_rejects_uninstalled_unreachable_database(monkeypatch):
    monkeypatch.setattr(main, "_refresh_install_status", lambda: {
        "installed": False,
        "requires_restart": False,
        "database_reachable": False,
    })

    result = main.health_check()

    assert result.status_code == 503
    assert b'"database_reachable":false' in result.body


def test_health_check_reports_ready_after_completed_startup(monkeypatch):
    monkeypatch.setattr(main, "_refresh_install_status", lambda: {
        "installed": True,
        "requires_restart": False,
        "database_reachable": True,
    })
    monkeypatch.setattr(main, "SYSTEM_READY", True)

    result = main.health_check()

    assert result["ok"] is True
    assert result["ready"] is True
    assert result["system_ready"] is True


def test_init_db_direct_import_registers_all_models():
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)
    command = (
        "from sqlalchemy import create_engine, inspect; "
        "from database import init_db; "
        "engine = create_engine('sqlite:///:memory:'); "
        "init_db(bind_engine=engine, run_migrations=False, raise_errors=True); "
        "assert 'points_products' in inspect(engine).get_table_names()"
    )

    subprocess.run(
        [sys.executable, "-c", command],
        cwd=backend_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_run_migrations_script_propagates_failures(monkeypatch):
    import database

    calls = []

    def fake_init_db(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(database, "init_db", fake_init_db)
    script_path = Path(__file__).resolve().parents[1] / "run_migrations.py"

    runpy.run_path(str(script_path), run_name="__main__")

    assert calls == [{"run_migrations": True, "raise_errors": True}]


def test_manual_migrate_uses_complete_migration_chain(monkeypatch):
    import database

    calls = []

    def fake_init_db(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(database, "init_db", fake_init_db)
    script_path = Path(__file__).resolve().parents[1] / "manual_migrate.py"

    runpy.run_path(str(script_path), run_name="__main__")

    assert calls == [{"run_migrations": True, "raise_errors": True}]


def _sqlite_install_engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'install.db'}")


def _patch_successful_install_dependencies(monkeypatch, engine):
    monkeypatch.setattr(main, "INSTALL_REQUIRES_RESTART", False)
    monkeypatch.setattr(main, "SYSTEM_READY", False)
    monkeypatch.setattr(main, "INSTALL_STATUS", {
        "installed": False,
        "source": "test",
        "database_reachable": True,
    })
    monkeypatch.setattr(main, "_ensure_not_installed_for_install_api", lambda: None)
    monkeypatch.setattr(main, "build_database_url", lambda config: "sqlite:///:memory:")
    monkeypatch.setattr(main, "build_redis_url", lambda config: "redis://localhost:6379/0")
    monkeypatch.setattr(main, "test_database_url", lambda url: {"ok": True})
    monkeypatch.setattr(main, "test_redis_url", lambda url: {"ok": True})
    monkeypatch.setattr(main, "create_install_engine", lambda url: engine)
    monkeypatch.setattr(
        main,
        "init_db",
        lambda *, bind_engine, run_migrations, raise_errors: Base.metadata.create_all(bind=bind_engine),
    )
    monkeypatch.setattr(
        main,
        "write_env_updates",
        lambda updates: {"env_path": "/tmp/.env", "backup_path": None, "updates": updates},
    )


def _valid_install_payload():
    return {
        "database": {
            "host": "localhost",
            "port": 5432,
            "database": "manga_novel",
            "username": "postgres",
            "password": "secret",
            "sslmode": "prefer",
        },
        "redis": {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "username": "",
            "password": "secret",
            "tls": False,
        },
        "admin": {
            "name": "Admin",
            "email": "Admin@Example.COM",
            "password": "password123",
            "confirmPassword": "password123",
        },
    }


def test_install_complete_rejects_invalid_admin_email_before_database_work(monkeypatch):
    called: list[str] = []

    monkeypatch.setattr(main, "_ensure_not_installed_for_install_api", lambda: None)

    def fail_if_called(name):
        def _inner(*args, **kwargs):
            called.append(name)
            raise AssertionError(f"{name} should not be called before admin validation")
        return _inner

    monkeypatch.setattr(main, "build_database_url", fail_if_called("build_database_url"))
    monkeypatch.setattr(main, "build_redis_url", fail_if_called("build_redis_url"))
    monkeypatch.setattr(main, "test_database_url", fail_if_called("test_database_url"))
    monkeypatch.setattr(main, "test_redis_url", fail_if_called("test_redis_url"))
    monkeypatch.setattr(main, "create_install_engine", fail_if_called("create_install_engine"))
    monkeypatch.setattr(main, "init_db", fail_if_called("init_db"))
    monkeypatch.setattr(main, "write_env_updates", fail_if_called("write_env_updates"))

    with pytest.raises(HTTPException) as exc_info:
        main.install_complete({
            "database": {
                "host": "localhost",
                "port": 5432,
                "database": "manga_novel",
                "username": "postgres",
                "password": "secret",
                "sslmode": "prefer",
            },
            "redis": {
                "host": "localhost",
                "port": 6379,
                "db": 0,
                "username": "",
                "password": "secret",
                "tls": False,
            },
            "admin": {
                "name": "Admin",
                "email": "not-an-email",
                "password": "password123",
                "confirmPassword": "password123",
            },
        })

    assert exc_info.value.status_code == 400
    assert "邮箱格式" in str(exc_info.value.detail)
    assert called == []


def test_install_complete_accepts_matching_admin_passwords(monkeypatch, tmp_path):
    engine = _sqlite_install_engine(tmp_path)
    _patch_successful_install_dependencies(monkeypatch, engine)

    result = main.install_complete(_valid_install_payload())

    assert result["ok"] is True
    assert result["admin"]["email"] == "admin@example.com"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM platform_settings")).scalar() > 0
        assert conn.execute(text("SELECT COUNT(*) FROM user_subscriptions")).scalar() == 0


def test_install_complete_rolls_back_seed_data_when_admin_creation_fails(monkeypatch, tmp_path):
    engine = _sqlite_install_engine(tmp_path)
    _patch_successful_install_dependencies(monkeypatch, engine)

    def fail_admin_creation(admin_config, db):
        raise HTTPException(400, "admin creation failed")

    monkeypatch.setattr(main, "_create_install_admin_user", fail_admin_creation)

    with pytest.raises(HTTPException) as exc_info:
        main.install_complete(_valid_install_payload())

    assert exc_info.value.status_code == 400
    assert main.database_has_install_markers(engine) is False
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM platform_settings")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM plans")).scalar() == 0
