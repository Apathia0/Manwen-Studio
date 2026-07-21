from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=4)
def _fernet(secret: str):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("需要安装 cryptography 以加密 API Key") from exc
    return Fernet(_derive_fernet_key(secret))


def get_secret_key_material() -> str:
    app_env = (os.getenv("APP_ENV") or "").strip().lower()
    if app_env in {"production", "prod"}:
        value = (os.getenv("AI_CREDENTIAL_SECRET") or "").strip()
        if len(value) < 32 or value.lower().startswith("change-this"):
            raise RuntimeError("生产环境必须配置至少 32 字符的 AI_CREDENTIAL_SECRET")
        return value
    for name in ("AI_CREDENTIAL_SECRET", "SECRET_KEY", "JWT_SECRET", "API_TOKEN"):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return "storycanvas-dev-only-secret-change-me"


def encrypt_secret(plain: str, *, secret: str | None = None) -> str:
    text = (plain or "").strip()
    if not text:
        return ""
    f = _fernet(secret or get_secret_key_material())
    return f.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str, *, secret: str | None = None) -> str:
    raw = (ciphertext or "").strip()
    if not raw:
        return ""
    f = _fernet(secret or get_secret_key_material())
    return f.decrypt(raw.encode("utf-8")).decode("utf-8")


def read_platform_setting_payload(payload, default=None):
    """读取平台设置值，并透明解密敏感字段。"""
    if not isinstance(payload, dict):
        return default
    ciphertext = str(payload.get("ciphertext") or "").strip()
    if ciphertext:
        return decrypt_secret(ciphertext)
    return payload.get("value", default)


def mask_secret(plain: str) -> str:
    text = (plain or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * max(4, len(text) - 4)}{text[-4:]}"


def last_four(plain: str) -> str:
    text = (plain or "").strip()
    return text[-4:] if text else ""
