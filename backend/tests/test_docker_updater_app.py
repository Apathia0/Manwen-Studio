import importlib.util
import sys
from pathlib import Path

from fastapi import HTTPException


def test_update_script_resolves_image_by_service_name():
    script_path = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "update-lorevista.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "compose config --format json" in script
    assert '["services"][sys.argv[1]]["image"]' in script
    assert 'config --images "$service"' not in script


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


def test_successful_update_does_not_replace_remote_manifest(tmp_path, monkeypatch):
    updater_app = _load_updater_app()
    env_path = tmp_path / ".env"
    manifest_url = "https://updates.example.org/manifest.json"
    env_path.write_text(f"UPDATE_MANIFEST_URL={manifest_url}\n", encoding="utf-8")
    monkeypatch.setattr(updater_app, "ENV_FILE", env_path)
    monkeypatch.setattr(updater_app, "APP_DIR", tmp_path)
    monkeypatch.setattr(updater_app, "UPDATE_COMMAND", "ignored")
    monkeypatch.setattr(updater_app, "_set_state", lambda **kwargs: kwargs)
    monkeypatch.setattr(updater_app, "_read_state", lambda: {})
    monkeypatch.setattr(updater_app, "_write_state", lambda state: None)

    class SuccessfulProcess:
        stdout = []

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(updater_app.subprocess, "Popen", lambda *args, **kwargs: SuccessfulProcess())

    updater_app._run_update(None)

    assert env_path.read_text(encoding="utf-8") == f"UPDATE_MANIFEST_URL={manifest_url}\n"


def test_manifest_redirect_strips_credentials_across_origins():
    updater_app = _load_updater_app()
    handler = updater_app._ManifestRedirectHandler()
    request = updater_app.urllib.request.Request(
        "https://updates.example.org/manifest.json",
        headers={
            "Authorization": "Bearer secret",
            "X-Updater-Token": "local-secret",
        },
    )

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://cdn.example.net/manifest.json",
    )

    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("X-updater-token") is None


def test_manifest_redirect_keeps_credentials_for_same_origin():
    updater_app = _load_updater_app()
    handler = updater_app._ManifestRedirectHandler()
    request = updater_app.urllib.request.Request(
        "https://updates.example.org/manifest.json",
        headers={"Authorization": "Bearer secret"},
    )

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://updates.example.org/releases/manifest.json",
    )

    assert redirected.get_header("Authorization") == "Bearer secret"
