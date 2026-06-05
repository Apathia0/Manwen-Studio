import pytest
from fastapi import HTTPException

import main


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
