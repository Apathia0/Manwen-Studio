import importlib.util
import sys
from pathlib import Path

from fastapi import HTTPException


def _load_updater_app():
    module_name = "lorevista_docker_updater_app"
    module_path = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "updater" / "app.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_updater_env_writer_preserves_values_and_creates_backup(tmp_path, monkeypatch):
    updater_app = _load_updater_app()
    env_path = tmp_path / ".env"
    env_path.write_text("APP_VERSION=v1.0.0\nDATABASE_URL=old\nCUSTOM_VALUE=keep\n", encoding="utf-8")
    monkeypatch.setattr(updater_app, "ENV_FILE", env_path)

    result = updater_app._write_env_updates({
        "DATABASE_URL": "new",
        "SYSTEM_INSTALLED": "true",
    })

    content = env_path.read_text(encoding="utf-8")
    assert "APP_VERSION=v1.0.0" in content
    assert "CUSTOM_VALUE=keep" in content
    assert "DATABASE_URL=new" in content
    assert "SYSTEM_INSTALLED=true" in content
    assert result["env_path"] == str(env_path)
    assert result["backup_path"]
    assert Path(result["backup_path"]).exists()


def test_updater_env_writer_rejects_unknown_keys(tmp_path, monkeypatch):
    updater_app = _load_updater_app()
    env_path = tmp_path / ".env"
    env_path.write_text("APP_VERSION=v1.0.0\n", encoding="utf-8")
    monkeypatch.setattr(updater_app, "ENV_FILE", env_path)

    try:
        updater_app._write_env_updates({"UNSUPPORTED_SECRET": "value"})
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Unsupported env keys" in str(exc.detail)
    else:
        raise AssertionError("unknown env keys should be rejected")

    assert env_path.read_text(encoding="utf-8") == "APP_VERSION=v1.0.0\n"
