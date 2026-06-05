import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

import main


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


def test_sanitize_update_status_redacts_secret_log_values(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v1.0.0")

    result = main._sanitize_update_status({
        "status": "running",
        "message": "Update started",
        "running": True,
        "log_tail": [
            "DATABASE_URL=postgresql://user:secret@postgres:5432/db",
            "UPDATER_TOKEN=secret-token",
        ],
    })

    assert result["current_version"] == "v1.0.0"
    assert "secret" not in "\n".join(result["log_tail"])
    assert "DATABASE_URL=postgresql://user:***@postgres:5432/db" in result["log_tail"][0]
    assert result["log_tail"][1] == "UPDATER_TOKEN=***"


def test_admin_start_system_update_rejects_invalid_version(monkeypatch):
    monkeypatch.setattr(main, "_require_admin", lambda request, db: SimpleNamespace(id=1, name="Admin"))

    with pytest.raises(HTTPException) as exc_info:
        _run(main.admin_start_system_update({"target_version": "../bad"}, SimpleNamespace(), _Db()))

    assert exc_info.value.status_code == 400


def test_admin_start_system_update_calls_updater_and_writes_audit(monkeypatch):
    db = _Db()
    calls = []
    audits = []
    admin = SimpleNamespace(id=1, name="Admin")
    monkeypatch.setattr(main, "_require_admin", lambda request, db: admin)

    async def fake_call(method, path, payload=None):
        calls.append((method, path, payload))
        return {
            "status": "queued",
            "message": "Update queued.",
            "running": False,
            "target_version": payload["target_version"],
            "log_tail": [],
        }

    monkeypatch.setattr(main, "_call_updater", fake_call)
    monkeypatch.setattr(main, "_write_audit_log", lambda *args, **kwargs: audits.append(args))

    result = _run(main.admin_start_system_update({"target_version": "v1.2.3"}, SimpleNamespace(), db))

    assert calls == [("POST", "/update", {"target_version": "v1.2.3"})]
    assert result["status"] == "queued"
    assert result["target_version"] == "v1.2.3"
    assert db.committed is True
    assert audits[0][1] == "system_update_start"
