import contextlib
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from sqlalchemy import create_engine, inspect, text


BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND_DIR / ".env"
ALLOWED_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def validate_install_admin_config(config: dict[str, Any]) -> dict[str, str]:
    email = str(config.get("email") or "").strip().lower()
    name = str(config.get("name") or "").strip() or "系统管理员"
    password = str(config.get("password") or "")
    confirm_password = str(config.get("confirmPassword") or config.get("confirm_password") or "")

    if not EMAIL_RE.match(email):
        raise ValueError("管理员邮箱格式不正确")
    if len(password) < 8:
        raise ValueError("管理员密码至少 8 位")
    if password != confirm_password:
        raise ValueError("管理员两次输入的密码不一致")
    return {"email": email, "name": name, "password": password}


def build_database_url(config: dict[str, Any]) -> str:
    host = str(config.get("host") or "").strip()
    port = int(config.get("port") or 5432)
    database = str(config.get("database") or "").strip()
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    sslmode = str(config.get("sslmode") or "prefer").strip().lower()

    if not host or not database or not username:
        raise ValueError("数据库 host、database、username 必填")
    if port <= 0 or port > 65535:
        raise ValueError("数据库端口必须在 1-65535 之间")
    if sslmode not in ALLOWED_SSLMODES:
        raise ValueError(f"sslmode 必须是 {', '.join(sorted(ALLOWED_SSLMODES))} 之一")

    auth = quote(username, safe="")
    if password:
        auth = f"{auth}:{quote(password, safe='')}"
    query = f"?sslmode={quote(sslmode, safe='')}" if sslmode else ""
    return f"postgresql://{auth}@{host}:{port}/{quote(database, safe='')}{query}"


def build_redis_url(config: dict[str, Any]) -> str:
    host = str(config.get("host") or "").strip()
    port = int(config.get("port") or 6379)
    db = int(config.get("db") or 0)
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    scheme = "rediss" if bool(config.get("tls")) else "redis"

    if not host:
        raise ValueError("Redis host 必填")
    if port <= 0 or port > 65535:
        raise ValueError("Redis 端口必须在 1-65535 之间")
    if db < 0:
        raise ValueError("Redis db 不能小于 0")

    auth = ""
    if username or password:
        if username:
            auth = quote(username, safe="")
            if password:
                auth = f"{auth}:{quote(password, safe='')}"
        else:
            auth = f":{quote(password, safe='')}"
        auth = f"{auth}@"
    return f"{scheme}://{auth}{host}:{port}/{db}"


def create_install_engine(database_url: str):
    return create_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=2,
        max_overflow=2,
        connect_args={
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 10,
            "keepalives_count": 6,
            "connect_timeout": 10,
        },
    )


def test_database_url(database_url: str) -> dict[str, Any]:
    engine = create_install_engine(database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "database_url": redact_url(database_url)}
    finally:
        engine.dispose()


def _redis_command(*parts: str) -> bytes:
    chunks = [f"*{len(parts)}\r\n".encode("utf-8")]
    for part in parts:
        data = str(part).encode("utf-8")
        chunks.append(f"${len(data)}\r\n".encode("utf-8"))
        chunks.append(data + b"\r\n")
    return b"".join(chunks)


def _read_redis_response(stream) -> str:
    line = stream.readline()
    if not line:
        raise ConnectionError("Redis 未返回响应")
    prefix = line[:1]
    payload = line[1:].rstrip(b"\r\n")
    if prefix == b"-":
        raise ConnectionError(payload.decode("utf-8", errors="replace"))
    if prefix in {b"+", b":"}:
        return payload.decode("utf-8", errors="replace")
    if prefix == b"$":
        length = int(payload)
        if length < 0:
            return ""
        data = stream.read(length)
        stream.read(2)
        return data.decode("utf-8", errors="replace")
    return line.decode("utf-8", errors="replace").strip()


def test_redis_url(redis_url: str, timeout: float = 5.0) -> dict[str, Any]:
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("Redis URL 仅支持 redis:// 或 rediss://")
    host = parsed.hostname
    if not host:
        raise ValueError("Redis host 必填")
    port = parsed.port or 6379
    db = int((parsed.path or "/0").lstrip("/") or "0")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    raw_sock = socket.create_connection((host, port), timeout=timeout)
    try:
        raw_sock.settimeout(timeout)
        sock = raw_sock
        if parsed.scheme == "rediss":
            sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
        with sock:
            stream = sock.makefile("rb")
            if username or password:
                if username:
                    sock.sendall(_redis_command("AUTH", username, password))
                else:
                    sock.sendall(_redis_command("AUTH", password))
                _read_redis_response(stream)
            if db:
                sock.sendall(_redis_command("SELECT", str(db)))
                _read_redis_response(stream)
            sock.sendall(_redis_command("PING"))
            response = _read_redis_response(stream)
            if response.upper() != "PONG":
                raise ConnectionError(f"Redis PING 返回异常: {response}")
        return {"ok": True, "redis_url": redact_url(redis_url)}
    finally:
        with contextlib.suppress(Exception):
            raw_sock.close()


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        return url
    username = parsed.username or ""
    password = parsed.password
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = ""
    if username:
        auth = quote(unquote(username), safe="")
        if password is not None:
            auth = f"{auth}:***"
        auth = f"{auth}@"
    elif password is not None:
        auth = ":***@"
    return parsed._replace(netloc=f"{auth}{host}{port}").geturl()


def database_has_install_markers(db_engine) -> bool:
    try:
        insp = inspect(db_engine)
        tables = set(insp.get_table_names())
        if "users" in tables:
            with db_engine.connect() as conn:
                if int(conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0) > 0:
                    return True
        if "platform_settings" in tables:
            with db_engine.connect() as conn:
                if int(conn.execute(text("SELECT COUNT(*) FROM platform_settings")).scalar() or 0) > 0:
                    return True
    except Exception:
        raise
    return False


def detect_install_status(db_engine=None) -> dict[str, Any]:
    env_installed = is_truthy(os.getenv("SYSTEM_INSTALLED"))
    if env_installed:
        return {"installed": True, "source": "env", "database_reachable": None}
    if db_engine is None:
        return {"installed": False, "source": "env", "database_reachable": None}
    try:
        if database_has_install_markers(db_engine):
            return {"installed": True, "source": "database", "database_reachable": True}
        return {"installed": False, "source": "database", "database_reachable": True}
    except Exception as exc:
        return {
            "installed": False,
            "source": "database",
            "database_reachable": False,
            "database_error": str(exc),
        }


def write_env_updates(updates: dict[str, str], env_path: Path = ENV_PATH) -> dict[str, str | None]:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
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

    backup_path: Path | None = None
    if env_path.exists():
        backup_path = env_path.with_suffix(f".env.bak.{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(env_path, backup_path)

    fd, tmp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=str(env_path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output).rstrip() + "\n")
        os.replace(tmp_path, env_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    for key, value in updates.items():
        os.environ[key] = value

    return {
        "env_path": str(env_path),
        "backup_path": str(backup_path) if backup_path else None,
    }


def _detached_popen(command: str | list[str], *, shell: bool = False, env: dict[str, str] | None = None):
    kwargs: dict[str, Any] = {
        "cwd": str(BACKEND_DIR),
        "env": env or os.environ.copy(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": shell,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _pm2_restart_command() -> list[str] | None:
    configured_name = os.getenv("INSTALL_PM2_PROCESS_NAME", "").strip()
    pm2_managed = any(os.getenv(key) for key in ("PM2_HOME", "pm_id", "NODE_APP_INSTANCE"))
    process_name = configured_name or (os.getenv("name", "").strip() if pm2_managed else "")
    if pm2_managed and not process_name:
        process_name = "canvas-backend"
    if not process_name:
        return None

    pm2_bin = shutil.which("pm2") or shutil.which("pm2.cmd")
    if not pm2_bin:
        raise RuntimeError("检测到 PM2 重启配置，但当前 PATH 找不到 pm2；请设置 INSTALL_RESTART_COMMAND")
    return [pm2_bin, "reload", process_name, "--update-env"]


def _spawn_development_restart() -> None:
    env = os.environ.copy()
    env["RELOAD"] = "false"
    env["INSTALL_RESTART_CWD"] = str(BACKEND_DIR)
    env["INSTALL_RESTART_DELAY"] = env.get("INSTALL_RESTART_DELAY", "1.2")
    backend_args = [sys.executable, str(BACKEND_DIR / "main.py")]
    launcher_code = (
        "import os, subprocess, sys, time; "
        "time.sleep(float(os.environ.get('INSTALL_RESTART_DELAY', '1.2'))); "
        "kwargs={'cwd': os.environ.get('INSTALL_RESTART_CWD') or None, "
        "'env': os.environ.copy(), 'stdin': subprocess.DEVNULL, "
        "'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}; "
        "kwargs.update({'creationflags': getattr(subprocess, 'DETACHED_PROCESS', 0) | "
        "getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)} if os.name == 'nt' "
        "else {'start_new_session': True}); "
        "subprocess.Popen(sys.argv[1:], **kwargs)"
    )
    _detached_popen([sys.executable, "-c", launcher_code, *backend_args], env=env)
    timer = threading.Timer(0.8, lambda: os._exit(0))
    timer.daemon = True
    timer.start()


def request_backend_restart() -> dict[str, str]:
    command = os.getenv("INSTALL_RESTART_COMMAND", "").strip()
    if command:
        _detached_popen(command, shell=True)
        return {
            "mode": "command",
            "message": "已提交 INSTALL_RESTART_COMMAND，等待后端进程重启。",
        }

    pm2_command = _pm2_restart_command()
    if pm2_command:
        _detached_popen(pm2_command)
        return {
            "mode": "pm2",
            "message": "已提交 PM2 reload --update-env，等待后端进程重启。",
        }

    if os.name != "nt" and not is_truthy(os.getenv("INSTALL_ALLOW_DEV_RESTART")):
        raise RuntimeError(
            "Linux 部署请配置 INSTALL_RESTART_COMMAND 或 INSTALL_PM2_PROCESS_NAME；"
            "如确认为本机开发环境，可设置 INSTALL_ALLOW_DEV_RESTART=true"
        )

    _spawn_development_restart()
    return {
        "mode": "development",
        "message": "已启动本地开发模式自动重启，等待后端重新监听端口。",
    }
