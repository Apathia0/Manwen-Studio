import json
import contextlib
import os
import re
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel


APP_DIR = Path(os.getenv("APP_DIR", "/opt/lorevista"))
ENV_FILE = Path(os.getenv("ENV_FILE", str(APP_DIR / ".env")))
STATE_FILE = Path(os.getenv("UPDATER_STATE_FILE", str(APP_DIR / "deploy/docker/update-state.json")))
UPDATE_COMMAND = os.getenv("UPDATER_COMMAND", "/usr/bin/env bash /updater/update-lorevista.sh")
UPDATER_TOKEN = os.getenv("UPDATER_TOKEN", "").strip()
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|KEY)[A-Z0-9_]*)=([^\s]+)")
URL_WITH_PASSWORD_RE = re.compile(r"(?i)\b((?:postgresql|postgres|redis|rediss)://[^:\s/@]+:)([^@\s]+)(@[^ \t\r\n]+)")
STALE_STATE_SECONDS = int(os.getenv("UPDATER_STALE_STATE_SECONDS", "60"))

app = FastAPI(title="LoreVista Updater")
_lock = threading.Lock()
_process: subprocess.Popen[str] | None = None


class UpdateRequest(BaseModel):
    target_version: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _state_age_seconds(state: dict[str, Any]) -> float:
    value = state.get("started_at") or state.get("queued_at")
    if not value:
        return 0
    try:
        started = datetime.fromisoformat(str(value))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - started).total_seconds())
    except Exception:
        return STALE_STATE_SECONDS + 1


def _state_is_stale(state: dict[str, Any]) -> bool:
    return state.get("status") in {"queued", "running"} and _process is None and _state_age_seconds(state) > STALE_STATE_SECONDS


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "status": "idle",
            "message": "No update has been run yet.",
            "log_tail": [],
        }
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "unknown",
            "message": "State file is not readable.",
            "log_tail": [],
        }


def _write_state(next_state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(next_state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, STATE_FILE)


def _redact_line(line: str) -> str:
    text = URL_WITH_PASSWORD_RE.sub(r"\1***\3", line)
    return SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=***", text)


def _set_state(**updates: Any) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        state.update(updates)
        _write_state(state)
        return state


def _auth(x_updater_token: str | None = Header(default=None)) -> None:
    if not UPDATER_TOKEN:
        return
    if x_updater_token != UPDATER_TOKEN:
        raise HTTPException(401, "Invalid updater token")


def _update_env_version(version: str) -> None:
    if not VERSION_RE.match(version):
        raise HTTPException(400, "Invalid target version. Use a Docker tag such as v1.2.3 or sha-abcdef123456.")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = existing.splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith("APP_VERSION="):
            output.append(f"APP_VERSION={version}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(f"APP_VERSION={version}")
    if ENV_FILE.exists():
        backup = ENV_FILE.with_suffix(f".env.bak.{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
        backup.write_text(existing, encoding="utf-8")
    tmp_path = ENV_FILE.with_suffix(".tmp")
    tmp_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp_path, ENV_FILE)


def _restore_env(previous_content: str | None, existed: bool) -> None:
    if not existed:
        if ENV_FILE.exists():
            ENV_FILE.unlink()
        return
    tmp_path = ENV_FILE.with_suffix(".tmp")
    tmp_path.write_text(previous_content or "", encoding="utf-8")
    os.replace(tmp_path, ENV_FILE)


def _append_log(state: dict[str, Any], line: str) -> None:
    tail = list(state.get("log_tail") or [])
    tail.append(_redact_line(line.rstrip()))
    state["log_tail"] = tail[-200:]


def _run_update(target_version: str | None) -> None:
    global _process
    env_existed = ENV_FILE.exists()
    previous_env_content = ENV_FILE.read_text(encoding="utf-8") if env_existed else None
    state = _set_state(
        status="running",
        message="Update started.",
        target_version=target_version,
        started_at=_now(),
        finished_at=None,
        exit_code=None,
        log_tail=[],
    )
    try:
        if target_version:
            _update_env_version(target_version)
            _append_log(state, f"APP_VERSION set to {target_version}")
            _write_state(state)

        env = os.environ.copy()
        env.setdefault("APP_DIR", str(APP_DIR))
        env.setdefault("ENV_FILE", str(ENV_FILE))
        proc = subprocess.Popen(
            UPDATE_COMMAND,
            cwd=str(APP_DIR),
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _process = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            with _lock:
                state = _read_state()
                _append_log(state, line)
                _write_state(state)
        exit_code = proc.wait()
        _process = None
        if exit_code == 0:
            _set_state(status="succeeded", message="Update completed.", finished_at=_now(), exit_code=exit_code)
        else:
            if target_version:
                _restore_env(previous_env_content, env_existed)
            _set_state(status="failed", message=f"Update failed with exit code {exit_code}.", finished_at=_now(), exit_code=exit_code)
    except Exception as exc:
        _process = None
        if target_version:
            with contextlib.suppress(Exception):
                _restore_env(previous_env_content, env_existed)
        _set_state(status="failed", message=f"Update failed: {exc}", finished_at=_now(), exit_code=None)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status")
def status(_: None = Depends(_auth)):
    state = _read_state()
    if _state_is_stale(state):
        state["status"] = "failed"
        state["message"] = "Updater process is not running. The previous update may have been interrupted."
        state["finished_at"] = state.get("finished_at") or _now()
        _write_state(state)
    state["running"] = _process is not None
    return state


@app.post("/update")
def start_update(payload: UpdateRequest, _: None = Depends(_auth)):
    global _process
    with _lock:
        if _process is not None:
            raise HTTPException(409, "Update is already running")
        current = _read_state()
        if current.get("status") in {"queued", "running"}:
            if _process is not None or not _state_is_stale(current):
                raise HTTPException(409, "Update is already running")
            current = {
                **current,
                "status": "failed",
                "message": "Updater process is not running. The previous update may have been interrupted.",
                "finished_at": current.get("finished_at") or _now(),
            }
        if payload.target_version and not VERSION_RE.match(payload.target_version):
            raise HTTPException(400, "Invalid target version")
        _write_state({
            **current,
            "status": "queued",
            "message": "Update queued.",
            "target_version": payload.target_version,
            "queued_at": _now(),
        })
    thread = threading.Thread(target=_run_update, args=(payload.target_version,), daemon=True)
    thread.start()
    return _read_state()
