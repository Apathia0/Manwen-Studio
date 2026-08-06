import base64
import json
import contextlib
import hmac
import os
import re
import subprocess
import threading
import time
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


def _updater_token_configured() -> bool:
    return len(UPDATER_TOKEN) >= 32 and not UPDATER_TOKEN.lower().startswith("change-this")


class UpdateRequest(BaseModel):
    target_version: str | None = None


class EnvUpdateRequest(BaseModel):
    updates: dict[str, str]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _state_age_seconds(state: dict[str, Any]) -> float:
    value = state.get("heartbeat_at") or state.get("started_at") or state.get("queued_at")
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


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme.lower(), (parts.hostname or "").lower(), parts.port


class _ManifestRedirectHandler(urllib.request.HTTPRedirectHandler):
    """跨源重定向时移除更新清单认证头。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and _url_origin(req.full_url) != _url_origin(newurl):
            sensitive_headers = {"authorization", "x-updater-token"}
            for name, _value in list(redirected.header_items()):
                if name.lower() in sensitive_headers:
                    redirected.remove_header(name)
        return redirected


def _fetch_update_manifest() -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    manifest_host = (urllib.parse.urlsplit(UPDATE_MANIFEST_URL).hostname or "").lower()
    if manifest_host in {"updater", "localhost", "127.0.0.1", "::1"} and UPDATER_TOKEN:
        headers["X-Updater-Token"] = UPDATER_TOKEN
    if UPDATE_MANIFEST_TOKEN:
        headers["Authorization"] = f"Bearer {UPDATE_MANIFEST_TOKEN}"
    request = urllib.request.Request(UPDATE_MANIFEST_URL, headers=headers)
    try:
        opener = urllib.request.build_opener(_ManifestRedirectHandler())
        with opener.open(request, timeout=UPDATE_MANIFEST_TIMEOUT_SECONDS) as response:
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


def _tag_exists_in_registry(tag: str) -> bool | None:
    """查询 ghcr.io API 检查指定 tag 是否存在。

    ghcr.io 使用 token 认证流程：
    1. 用 docker config 中的 basic auth 凭证换取 Bearer token
    2. 用 Bearer token 分页查询 tag 列表
    返回 True/False，API 不可用时返回 None。
    """
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

    # ghcr.io 需要先用 basic auth 换取 Bearer token，不能直接用 basic auth 查询
    repo = "dream619/manwen-studio/backend"
    basic_encoded = base64.b64encode(auth_value.encode("utf-8")).decode("ascii")
    token_url = f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io"
    try:
        token_req = urllib.request.Request(token_url)
        token_req.add_header("Authorization", f"Basic {basic_encoded}")
        with urllib.request.urlopen(token_req, timeout=UPDATE_MANIFEST_TIMEOUT_SECONDS) as resp:
            token_data = json.loads(resp.read(512 * 1024).decode())
        bearer_token = token_data.get("token", "")
        if not bearer_token:
            return None
    except Exception:
        return None

    # 分页查询 tag 列表（ghcr.io 默认每页 100 条，Link 头返回相对 URL）
    link_re = re.compile(r'<([^>]+)>;\s*rel="?next"?(?:;|$)')
    base_url = f"https://ghcr.io/v2/{repo}/tags/list"
    page_url: str | None = f"{base_url}?n=100"
    try:
        while page_url:
            req = urllib.request.Request(page_url)
            req.add_header("Authorization", f"Bearer {bearer_token}")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=UPDATE_MANIFEST_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read(512 * 1024).decode())
            tags = data.get("tags") or []
            if tag in tags:
                return True
            link_header = resp.headers.get("Link", "")
            match = link_re.search(link_header)
            page_url = urllib.parse.urljoin(base_url, match.group(1)) if match else None
    except Exception:
        return None
    return False


def _get_image_ref(service: str, target_version: str) -> str:
    """根据 REGISTRY_IMAGE_PREFIX 构造服务镜像引用。

    直接从 .env 读取 REGISTRY_IMAGE_PREFIX 并拼接服务名和版本号，
    不再依赖 docker compose config --images（该命令会返回所有依赖镜像，
    不只目标服务的，导致取到错误的镜像引用）。
    """
    prefix = _read_env_value("REGISTRY_IMAGE_PREFIX") or "ghcr.io/dream619/manwen-studio"
    return f"{prefix}/{service}:{target_version}"


def _validate_version_tags(target_version: str) -> None:
    """验证目标版本在 ghcr.io 中存在。优先查 API tag 列表，失败时回退到 docker buildx inspect。"""
    exists = _tag_exists_in_registry(target_version)
    if exists is True:
        return
    if exists is False:
        raise HTTPException(400, f"版本 {target_version} 在 ghcr.io 中不存在")

    # API 不可用，回退到 docker buildx imagetools inspect 逐镜像验证
    missing: list[str] = []
    for service in ["backend", "web", "updater"]:
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
    if not _updater_token_configured():
        raise HTTPException(503, "Updater token is not configured")
    if not hmac.compare_digest(str(x_updater_token or ""), UPDATER_TOKEN):
        raise HTTPException(401, "Invalid updater token")


def _update_env_version(version: str) -> None:
    if not VERSION_RE.match(version):
        raise HTTPException(400, "Invalid target version. Please use a valid version like v1.2.3.")
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
    state["heartbeat_at"] = _now()


def _schedule_updater_restart(target_version: str | None) -> tuple[bool, str]:
    """在成功状态落盘后，通过独立 helper 容器替换 updater。"""
    version = (target_version or _read_env_value("APP_VERSION") or "").strip()
    if not version:
        return False, "APP_VERSION is not configured; updater restart was skipped."

    updater_image = _get_image_ref("updater", version)
    helper_name = f"lorevista-updater-replacer-{int(time.time())}-{os.getpid()}"
    command = [
        "docker", "run", "--rm", "-d",
        "--name", helper_name,
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{APP_DIR}:{APP_DIR}",
        "-e", f"ENV_FILE={ENV_FILE}",
        "-e", f"COMPOSE_FILE={COMPOSE_FILE}",
        "--entrypoint", "bash",
        updater_image,
        "-lc",
        'sleep 2; docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" '
        'up -d --no-deps updater >/dev/null 2>&1',
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except Exception as exc:
        return False, f"Unable to schedule updater restart: {exc}"
    if result.returncode != 0:
        detail = _redact_line((result.stderr or result.stdout or "unknown error").strip())
        return False, f"Unable to schedule updater restart: {detail}"
    return True, "Updater restart scheduled."


def _run_update(target_version: str | None) -> None:
    global _process
    env_existed = ENV_FILE.exists()
    previous_env_content = ENV_FILE.read_text(encoding="utf-8") if env_existed else None
    state = _set_state(
        status="running",
        message="Update started.",
        target_version=target_version,
        started_at=_now(),
        heartbeat_at=_now(),
        finished_at=None,
        exit_code=None,
        updater_restart=None,
        updater_restart_message=None,
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
        if exit_code == 0:
            _set_state(status="succeeded", message="Update completed.", finished_at=_now(), exit_code=exit_code)
            _process = None
            restart_scheduled, restart_message = _schedule_updater_restart(target_version)
            if not restart_scheduled:
                _set_state(
                    updater_restart="failed",
                    updater_restart_message=restart_message,
                    message="Update completed, but the updater restart could not be scheduled.",
                )
        else:
            if target_version:
                _restore_env(previous_env_content, env_existed)
            _set_state(status="failed", message=f"Update failed with exit code {exit_code}.", finished_at=_now(), exit_code=exit_code)
            _process = None
    except Exception as exc:
        if target_version:
            with contextlib.suppress(Exception):
                _restore_env(previous_env_content, env_existed)
        _set_state(status="failed", message=f"Update failed: {exc}", finished_at=_now(), exit_code=None)
        _process = None


@app.get("/health")
def health():
    if not _updater_token_configured():
        raise HTTPException(503, "Updater token is not configured")
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
        state = {
            **state,
            "status": "interrupted",
            "message": "Updater process is not running. The previous update may have been interrupted.",
            "finished_at": state.get("finished_at") or _now(),
        }
    state["running"] = _process is not None
    return state


@app.get("/check")
def check_update(_: None = Depends(_auth)):
    current_version = _read_env_value("APP_VERSION") or "dev"

    if not UPDATE_MANIFEST_URL:
        return {
            "configured": False,
            "source": None,
            "current_version": current_version,
            "latest_version": None,
            "update_available": False,
            "release_notes": "",
            "published_at": None,
            "min_supported_version": None,
            "channel": None,
            "manifest_url": "",
            "message": "UPDATE_MANIFEST_URL is not configured.",
        }

    manifest = _fetch_update_manifest()
    latest_version = _string_field(manifest, "latest_version") or _string_field(manifest, "version")
    if not latest_version or not VERSION_RE.match(latest_version):
        return {
            "configured": False,
            "source": None,
            "current_version": current_version,
            "latest_version": latest_version or None,
            "update_available": False,
            "release_notes": "",
            "published_at": None,
            "min_supported_version": None,
            "channel": None,
            "manifest_url": _redact_manifest_url(UPDATE_MANIFEST_URL),
            "message": "更新清单不可用。如果仓库是私有的，需要在 .env 中配置 UPDATE_MANIFEST_URL。",
        }

    update_available = _is_newer_version(latest_version, current_version)
    return {
        "configured": True,
        "source": "manifest",
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "release_notes": _string_field(manifest, "release_notes"),
        "published_at": _string_field(manifest, "published_at") or None,
        "min_supported_version": _string_field(manifest, "min_supported_version") or None,
        "channel": _string_field(manifest, "channel") or None,
        "manifest_url": _redact_manifest_url(UPDATE_MANIFEST_URL),
        "message": "A new version is available." if update_available else "Already on the latest version.",
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
