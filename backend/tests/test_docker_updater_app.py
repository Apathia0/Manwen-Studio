import importlib.util
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_update_script_resolves_image_by_service_name():
    script_path = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "update-lorevista.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "compose config --format json" in script
    assert '["services"][sys.argv[1]]["image"]' in script
    assert 'config --images "$service"' not in script


def test_update_script_prunes_only_old_project_images():
    script_path = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "update-lorevista.sh"
    script = script_path.read_text(encoding="utf-8")

    assert 'IMAGE_RETENTION_COUNT="${IMAGE_RETENTION_COUNT:-3}"' in script
    assert "prune_project_images" in script
    assert 'docker image ls "$repository"' in script
    assert 'docker image rm "$tagged_ref"' in script
    assert "is_managed_image_tag" in script
    assert "running_image_ids" in script
    assert 'grep -Fxq "$image_id"' in script
    assert "docker image prune" not in script


def test_update_script_does_not_restart_updater_before_terminal_state_is_written():
    script_path = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "update-lorevista.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "lorevista-updater-replacer" not in script
    assert "restarting updater with new image" not in script
    assert 'curl -fs "$url" >/dev/null 2>&1' in script


def test_project_image_cleanup_protects_container_and_rollback_images(tmp_path):
    bash = shutil.which("bash")
    if sys.platform == "win32":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            bash = str(git_bash)
    if not bash:
        pytest.skip("未找到可用的 Bash")

    script_path = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "update-lorevista.sh"
    script = script_path.read_text(encoding="utf-8")
    functions = script[script.index("image_repository_for() {"):script.index("wait_for_health() {")]
    removed_path = tmp_path / "removed.txt"
    harness_path = tmp_path / "cleanup-test.sh"
    harness_path.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail
IMAGE_RETENTION_COUNT=2
BACKEND_SERVICE=backend
WEB_SERVICE=web
BACKEND_PREVIOUS_IMAGE_ID=sha256:rollback
WEB_PREVIOUS_IMAGE_ID=
UPDATER_PREVIOUS_IMAGE_ID=
REMOVED_FILE={removed_path.as_posix()!r}
log() {{ :; }}
image_ref_for() {{ printf 'registry.example/storycanvas/%s:v4\\n' "$1"; }}
docker() {{
  if [[ "$1 $2" == "ps -aq" ]]; then
    printf 'running-container\\nstopped-container\\n'
  elif [[ "$1" == "inspect" ]]; then
    [[ "$4" == "running-container" ]] && printf 'sha256:active\\n' || printf 'sha256:stopped\\n'
  elif [[ "$1 $2" == "image ls" ]]; then
    local name="${{3##*/}}"
    printf 'registry.example/storycanvas/%s|v4.0.0\\n' "$name"
    printf 'registry.example/storycanvas/%s|v3.0.0\\n' "$name"
    printf 'registry.example/storycanvas/%s|dev-branch\\n' "$name"
    printf 'registry.example/storycanvas/%s|v1.2.3.backup\\n' "$name"
    if [[ "$name" == "backend" ]]; then
      printf 'registry.example/storycanvas/backend|v2.0.0\\n'
      printf 'registry.example/storycanvas/backend|v1.0.0\\n'
      printf 'registry.example/storycanvas/backend|v0.9.0\\n'
    fi
  elif [[ "$1 $2" == "image inspect" ]]; then
    case "$5" in
      *:v4.0.0) printf '2026-04-01T00:00:00Z|sha256:active\\n' ;;
      *:v3.0.0) printf '2026-03-01T00:00:00Z|sha256:previous-%s\\n' "${{5##*/}}" ;;
      *:v2.0.0) printf '2026-02-01T00:00:00Z|sha256:old\\n' ;;
      *:v1.0.0) printf '2026-01-01T00:00:00Z|sha256:rollback\\n' ;;
      *:v0.9.0) printf '2025-12-01T00:00:00Z|sha256:stopped\\n' ;;
    esac
  elif [[ "$1 $2" == "image rm" ]]; then
    printf '%s\\n' "$3" >>"$REMOVED_FILE"
  fi
}}
{functions}
prune_project_images
""",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run([bash, str(harness_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    removed = removed_path.read_text(encoding="utf-8").splitlines()
    assert removed == ["registry.example/storycanvas/backend:v2.0.0"]


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
    monkeypatch.setattr(updater_app, "_schedule_updater_restart", lambda target: (True, "scheduled"))

    class SuccessfulProcess:
        stdout = []

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(updater_app.subprocess, "Popen", lambda *args, **kwargs: SuccessfulProcess())

    updater_app._run_update(None)

    assert env_path.read_text(encoding="utf-8") == f"UPDATE_MANIFEST_URL={manifest_url}\n"


def test_successful_update_persists_terminal_state_before_scheduling_restart(tmp_path, monkeypatch):
    updater_app = _load_updater_app()
    monkeypatch.setattr(updater_app, "APP_DIR", tmp_path)
    monkeypatch.setattr(updater_app, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(updater_app, "UPDATE_COMMAND", "ignored")
    monkeypatch.setattr(updater_app, "_read_state", lambda: {})
    monkeypatch.setattr(updater_app, "_write_state", lambda state: None)
    events: list[str] = []

    def record_state(**updates):
        if updates.get("status") == "succeeded":
            events.append("succeeded")
        return updates

    monkeypatch.setattr(updater_app, "_set_state", record_state)
    def schedule_restart(target):
        events.append("restart")
        return True, "scheduled"

    monkeypatch.setattr(updater_app, "_schedule_updater_restart", schedule_restart)

    class SuccessfulProcess:
        stdout = []

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(updater_app.subprocess, "Popen", lambda *args, **kwargs: SuccessfulProcess())

    updater_app._run_update("v9.9.9")

    assert events == ["succeeded", "restart"]


def test_status_reports_stale_run_without_mutating_state(monkeypatch):
    updater_app = _load_updater_app()
    persisted = {
        "status": "running",
        "message": "Update started.",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    monkeypatch.setattr(updater_app, "_read_state", lambda: dict(persisted))
    monkeypatch.setattr(updater_app, "_state_is_stale", lambda state: True)
    monkeypatch.setattr(
        updater_app,
        "_write_state",
        lambda state: pytest.fail("GET /status 不应写入状态文件"),
    )

    result = updater_app.status(None)

    assert result["status"] == "interrupted"
    assert result["running"] is False
    assert persisted["status"] == "running"


def test_stale_detection_uses_recent_heartbeat_instead_of_start_time(monkeypatch):
    updater_app = _load_updater_app()
    monkeypatch.setattr(updater_app, "_process", None)
    state = {
        "status": "running",
        "started_at": "2020-01-01T00:00:00+00:00",
        "heartbeat_at": datetime.now(UTC).isoformat(),
    }

    assert updater_app._state_is_stale(state) is False


def test_updater_restart_is_scheduled_with_target_image(tmp_path, monkeypatch):
    updater_app = _load_updater_app()
    env_path = tmp_path / ".env"
    compose_path = tmp_path / "docker-compose.yml"
    monkeypatch.setattr(updater_app, "APP_DIR", tmp_path)
    monkeypatch.setattr(updater_app, "ENV_FILE", env_path)
    monkeypatch.setattr(updater_app, "COMPOSE_FILE", compose_path)
    captured = {}

    class Result:
        returncode = 0
        stdout = "helper-id"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(updater_app.subprocess, "run", fake_run)

    scheduled, message = updater_app._schedule_updater_restart("v9.9.9")

    assert scheduled is True
    assert message == "Updater restart scheduled."
    command = captured["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "ghcr.io/dream619/manwen-studio/updater:v9.9.9" in command
    assert f"ENV_FILE={env_path}" in command
    assert f"COMPOSE_FILE={compose_path}" in command
    assert captured["kwargs"]["timeout"] == 30


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
