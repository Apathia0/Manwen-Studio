import base64
import json
import contextlib
import os
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel


APP_DIR = Path(os.getenv("APP_DIR", "/opt/lorevista"))
ENV_FILE = Path(os.getenv("ENV_FILE", str(APP_DIR / ".env")))
COMPOSE_FILE = Path(os.getenv("COMPOSE_FILE", str(APP_DIR / "docker-compose.yml")))
STATE_FILE = Path(os.getenv("UPDATER_STATE_FILE", str(APP_DIR / "deploy/docker/update-state.json")))
UPDATE_COMMAND = os.getenv("UPDATER_COMMAND", "/usr/bin/env bash /updater/update-lorevista.sh")
UPDATER_TOKEN = os.getenv("UPDATER_TOKEN", "").strip()
DEFAULT_MANIFEST_URL = os.getenv("DEFAULT_MANIFEST_URL", "").strip()
UPDATE_MANIFEST_URL = os.getenv("UPDATE_MANIFEST_URL", "").strip() or DEFAULT_MANIFEST_URL or ""
UPDATE_MANIFEST_TOKEN = os.getenv("UPDATE_MANIFEST_TOKEN", "").strip()
UPDATE_MANIFEST_TIMEOUT_SECONDS = float(os.getenv("UPDATE_MANIFEST_TIMEOUT_SECONDS", "10"))
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_API_TIMEOUT_SECONDS = float(os.getenv("GITHUB_API_TIMEOUT_SECONDS", "10"))
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SEMVER_RE = re.compile(r"^v?(\d+)(?:\.(\d+)(?:\.(\d+))?)?")
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|KEY)[A-Z0-9_]*)=([^\s]+)")
URL_WITH_PASSWORD_RE = re.compile(r"(?i)\b((?:postgresql|postgres|redis|rediss)://[^:\s/@]+:)([^@\s]+)(@[^ \t\r\n]+)")
STALE_STATE_SECONDS = int(os.getenv("UPDATER_STALE_STATE_SECONDS", "60"))

app = FastAPI(title="LoreVista Updater")
_lock = threading.Lock()
_process: subprocess.Popen[str] | None = None


class UpdateRequest(BaseModel):
    target_version: str | None = None


class EnvUpdateRequest(BaseModel):
    updates: dict[str, str]


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


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_env_value(key: str) -> str | None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() == key:
                return _strip_env_quotes(value.strip())
    value = os.getenv(key, "").strip()
    return value or None


def _redact_manifest_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
        netloc = parts.netloc
        if parts.password:
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            netloc = f"{parts.username}:***@{host}" if parts.username else host
        query = "..." if parts.query else ""
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, query, ""))
    except Exception:
        return _redact_line(url)


def _string_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _fetch_update_manifest() -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if UPDATE_MANIFEST_TOKEN:
        headers["Authorization"] = f"Bearer {UPDATE_MANIFEST_TOKEN}"
    request = urllib.request.Request(UPDATE_MANIFEST_URL, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=UPDATE_MANIFEST_TIMEOUT_SECONDS) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise HTTPException(502, "Update manifest is too large")
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError:
        return {}
    except urllib.error.URLError:
        return {}
    except TimeoutError:
        return {}
    try:
        data = json.loads(body.decode(charset))
    except Exception as exc:
        raise HTTPException(502, "Update manifest returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(502, "Update manifest must be a JSON object")
    return data


def _fetch_latest_tag_from_github() -> str | None:
    if not GITHUB_REPOSITORY:
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/tags?per_page=10"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "StoryCanvas-Updater",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_API_TIMEOUT_SECONDS) as resp:
            tags = json.loads(resp.read(1024 * 128).decode())
    except Exception:
        return None
    if not isinstance(tags, list):
        return None
    for tag in tags:
        tag_name = tag.get("name", "")
        if VERSION_RE.match(tag_name) and tag_name.startswith("v"):
            return tag_name
    return None


def _fetch_latest_tag_from_registry() -> str | None:
    """从 ghcr.io 列出可用标签，找到最新版本。"""
    docker_config = Path("/root/.docker/config.json")
    auth_value: str | None = None
    if docker_config.exists():
        try:
            cfg = json.loads(docker_config.read_text())
            for registry_key in cfg.get("auths", {}):
                if "ghcr.io" in registry_key:
                    entry = cfg["auths"][registry_key]
                    raw = entry.get("auth", "").strip()
                    if raw:
                        decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
                        auth_value = decoded
                    break
        except Exception:
            pass
    if not auth_value:
        return None
    registry_url = "https://ghcr.io/v2/dream619/manwen-studio/backend/tags/list"
    encoded = base64.b64encode(auth_value.encode("utf-8")).decode("ascii")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {encoded}",
    }
    try:
        req = urllib.request.Request(registry_url, headers=headers)
        with urllib.request.urlopen(req, timeout=UPDATE_MANIFEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read(512 * 1024).decode())
    except Exception:
        return None
    tags = data.get("tags") or []
    version_tags = sorted(
        [t for t in tags if SEMVER_RE.match(t)],
        key=lambda t: _parse_semver(t),
        reverse=True,
    )
    return version_tags[0] if version_tags else None


def _get_image_ref(service: str, target_version: str) -> str:
    """从 docker compose config 获取服务镜像名，替换 tag 为目标版本。"""
    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE),
             "config", "--images", service],
            capture_output=True, text=True, timeout=15, cwd=str(APP_DIR),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(503, f"无法获取 {service} 的镜像配置：命令超时") from exc
    except Exception as exc:
        raise HTTPException(502, f"无法获取 {service} 的镜像配置：{exc}") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise HTTPException(502, f"无法获取 {service} 的镜像配置：{result.stderr.strip()}")
    current_ref = result.stdout.strip().splitlines()[0]
    if ":" in current_ref:
        repo = current_ref.rsplit(":", 1)[0]
        return f"{repo}:{target_version}"
    return f"{current_ref}:{target_version}"


def _validate_version_tags(target_version: str) -> None:
    """验证目标版本的所有镜像标签在仓库中存在。"""
    services = ["backend", "web", "updater"]
    missing: list[str] = []
    for service in services:
        image = _get_image_ref(service, target_version)
        try:
            result = subprocess.run(
                ["docker", "buildx", "imagetools", "inspect", image],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(503, f"验证镜像 {image} 超时，仓库可能不可达") from exc
        except FileNotFoundError:
            return
        if result.returncode != 0:
            missing.append(image)
    if missing:
        detail = "以下镜像在仓库中不存在:\n" + "\n".join(f"  - {img}" for img in missing)
        raise HTTPException(400, detail)


def _parse_semver(version: str) -> tuple[int, ...]:
    m = SEMVER_RE.match(version.strip())
    if not m:
        return (0,)
    return tuple(int(p) if p else 0 for p in m.groups())


def _is_newer_version(latest: str, current: str) -> bool:
    return _parse_semver(latest) > _parse_semver(current)


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


def _write_env_updates(updates: dict[str, str]) -> dict[str, str | None]:
    allowed_keys = {
        "DATABASE_URL",
        "REDIS_URL",
        "REDIS_ENABLED",
        "SYSTEM_INSTALLED",
        "RUN_STARTUP_MIGRATIONS",
        "UPDATE_MANIFEST_URL",
    }
    unknown = sorted(set(updates) - allowed_keys)
    if unknown:
        raise HTTPException(400, f"Unsupported env keys: {', '.join(unknown)}")

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = existing.splitlines()
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)

    missing = [key for key in updates if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# System installation")
        output.extend(f"{key}={updates[key]}" for key in missing)

    backup: Path | None = None
    if ENV_FILE.exists():
        backup = ENV_FILE.with_suffix(f".env.bak.{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
        backup.write_text(existing, encoding="utf-8")

    tmp_path = ENV_FILE.with_suffix(".tmp")
    tmp_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp_path, ENV_FILE)
    return {
        "env_path": str(ENV_FILE),
        "backup_path": str(backup) if backup else None,
    }


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
            # 更新成功后，自动配置 UPDATE_MANIFEST_URL 指向本机 /manifest
            current_url = _read_env_value("UPDATE_MANIFEST_URL") or ""
            if not current_url or current_url == DEFAULT_MANIFEST_URL or "example.com" in current_url:
                try:
                    _write_env_updates({"UPDATE_MANIFEST_URL": "http://updater:8090/manifest"})
                    _append_log(state, "UPDATE_MANIFEST_URL 已设置为 http://updater:8090/manifest")
                except Exception as exc:
                    _append_log(state, f"UPDATE_MANIFEST_URL 自动配置失败: {exc}")
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


@app.get("/manifest")
def get_manifest(_: None = Depends(_auth)):
    manifest_path = APP_DIR / "update-manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Manifest file not found")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(502, f"Manifest file is corrupted: {exc}") from exc


@app.post("/internal/env")
def write_env(body: EnvUpdateRequest, _: None = Depends(_auth)):
    result = _write_env_updates({str(key): str(value) for key, value in body.updates.items()})
    return {"ok": True, **result}


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


@app.get("/check")
def check_update(_: None = Depends(_auth)):
    current_version = _read_env_value("APP_VERSION") or "dev"

    # 1) 尝试从 manifest URL 获取最新版本
    manifest_latest: str | None = None
    manifest_data: dict[str, Any] = {}
    manifest_configured = bool(UPDATE_MANIFEST_URL)
    if UPDATE_MANIFEST_URL:
        manifest_data = _fetch_update_manifest()
        ml = _string_field(manifest_data, "latest_version") or _string_field(manifest_data, "version")
        if ml and VERSION_RE.match(ml):
            manifest_latest = ml

    # 2) 尝试从 ghcr.io 远程查询最新 tag（私有仓库使用 Docker 凭证）
    registry_latest: str | None = _fetch_latest_tag_from_registry()

    # 3) 取两个来源中较新的版本
    latest_version = manifest_latest or registry_latest
    source = "registry"
    if manifest_latest and registry_latest:
        latest_version = manifest_latest if _is_newer_version(manifest_latest, registry_latest) else registry_latest
        source = "manifest+registry"
    elif manifest_latest:
        source = "manifest"

    if not latest_version:
        return {
            "configured": manifest_configured,
            "source": None,
            "current_version": current_version,
            "latest_version": None,
            "update_available": False,
            "release_notes": "",
            "published_at": None,
            "min_supported_version": None,
            "channel": None,
            "manifest_url": _redact_manifest_url(UPDATE_MANIFEST_URL),
            "message": "无法检测到最新版本（manifest 不可用且 ghcr.io 查询失败）。",
        }

    update_available = _is_newer_version(latest_version, current_version)
    return {
        "configured": manifest_configured,
        "source": source,
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "release_notes": _string_field(manifest_data, "release_notes"),
        "published_at": _string_field(manifest_data, "published_at") or None,
        "min_supported_version": _string_field(manifest_data, "min_supported_version") or None,
        "channel": _string_field(manifest_data, "channel") or None,
        "manifest_url": _redact_manifest_url(UPDATE_MANIFEST_URL),
        "message": "有新版本可用。" if update_available else "已是最新版本。",
    }


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
        if payload.target_version:
            _validate_version_tags(payload.target_version)
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
