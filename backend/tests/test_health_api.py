from types import SimpleNamespace

import main


class _Response:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Connection:
    def __init__(self, raises=False):
        self.raises = raises

    def __enter__(self):
        if self.raises:
            raise RuntimeError("database unavailable")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _statement):
        return _Response(1)


def test_health_check_allows_uninstalled_startup(monkeypatch):
    monkeypatch.setattr(main, "_refresh_install_status", lambda: {
        "installed": False,
        "requires_restart": False,
        "database_reachable": None,
    })

    result = main.health_check()

    assert result["ok"] is True
    assert result["ready"] is False
    assert result["installed"] is False


def test_health_check_reports_ready_for_installed_database(monkeypatch):
    monkeypatch.setattr(main, "_refresh_install_status", lambda: {
        "installed": True,
        "requires_restart": False,
        "database_reachable": None,
    })
    monkeypatch.setattr(main, "database_engine", SimpleNamespace(connect=lambda: _Connection()))

    result = main.health_check()

    assert result["ok"] is True
    assert result["ready"] is True
    assert result["database_reachable"] is True


def test_health_check_returns_503_for_installed_unreachable_database(monkeypatch):
    monkeypatch.setattr(main, "_refresh_install_status", lambda: {
        "installed": True,
        "requires_restart": False,
        "database_reachable": None,
    })
    monkeypatch.setattr(main, "database_engine", SimpleNamespace(connect=lambda: _Connection(raises=True)))

    result = main.health_check()

    assert result.status_code == 503
    assert b"database unavailable" in result.body
