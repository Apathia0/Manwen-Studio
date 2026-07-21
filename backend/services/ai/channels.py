from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import AiChannel
from services.ai.crypto_secrets import decrypt_secret, encrypt_secret, last_four


def validate_base_url(base_url: str, *, allow_http: bool = False) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise HTTPException(400, "Base URL 不能为空")
    parsed = urlparse(url)
    if parsed.scheme not in (("http", "https") if allow_http else ("https",)):
        if allow_http and parsed.scheme == "http":
            pass
        elif parsed.scheme != "https":
            raise HTTPException(400, "生产环境仅允许 HTTPS Base URL")
    host = (parsed.hostname or "").lower()
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(400, "Base URL 格式不合法")
    blocked = {"localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"}
    if host in blocked or host.startswith("169.254.") or host.endswith(".local"):
        raise HTTPException(400, f"不允许的上游地址: {host}")
    _validate_public_host(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    return url


def _validate_public_host(hostname: str, port: int) -> None:
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise HTTPException(400, f"不允许的上游地址: {host}")

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise HTTPException(400, "自定义上游域名无法解析") from exc
        addresses = []
        for item in resolved:
            try:
                addresses.append(ipaddress.ip_address(item[4][0]))
            except ValueError:
                continue
        if not addresses:
            raise HTTPException(400, "自定义上游域名未解析到有效地址")

    if any(not address.is_global for address in addresses):
        raise HTTPException(400, f"不允许访问内网或保留地址: {host}")


def validate_user_base_url(base_url: str) -> str:
    """校验用户自定义上游地址，阻止凭据被发送到内网或不安全端点。"""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise HTTPException(400, "自定义 Base URL 不能为空")
    if len(url) > 2048:
        raise HTTPException(400, "自定义 Base URL 过长")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(400, "自定义上游仅允许 HTTPS 地址")
    if not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, "自定义上游地址格式不合法")
    if parsed.query or parsed.fragment:
        raise HTTPException(400, "自定义上游地址不能包含查询参数或片段")
    if (os.getenv("APP_ENV") or "").strip().lower() in {"production", "prod"}:
        allowed_hosts = {
            item.strip().rstrip(".").lower()
            for item in (os.getenv("USER_UPSTREAM_HOST_ALLOWLIST") or "").split(",")
            if item.strip()
        }
        if not allowed_hosts:
            raise HTTPException(503, "生产环境尚未配置用户自定义上游域名白名单")
        if parsed.hostname.rstrip(".").lower() not in allowed_hosts:
            raise HTTPException(403, "该自定义上游域名不在管理员允许的白名单中")
    _validate_public_host(parsed.hostname, parsed.port or 443)
    return url


def validate_remote_media_url(media_url: str) -> str:
    """校验上游返回的远程媒体地址，查询参数可用于签名但禁止内网目标。"""
    url = (media_url or "").strip()
    if not url or len(url) > 4096:
        raise HTTPException(400, "上游返回的媒体 URL 不合法")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(400, "远程媒体仅允许 HTTPS 地址")
    if not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, "远程媒体 URL 格式不合法")
    _validate_public_host(parsed.hostname, parsed.port or 443)
    return urlunparse(parsed._replace(fragment=""))


def get_channel(db: Session, channel_id: int) -> AiChannel:
    ch = db.get(AiChannel, channel_id)
    if not ch or not ch.enabled:
        raise HTTPException(404, "渠道不存在或已停用")
    return ch


def get_channel_by_code(db: Session, code: str) -> AiChannel | None:
    return db.query(AiChannel).filter(AiChannel.code == code).first()


def list_channels(db: Session) -> list[AiChannel]:
    return db.query(AiChannel).order_by(AiChannel.id.asc()).all()


def serialize_channel(ch: AiChannel, *, include_secret_meta: bool = True) -> dict[str, Any]:
    data = {
        "id": ch.id,
        "code": ch.code,
        "name": ch.name,
        "adapter_type": ch.adapter_type,
        "base_url": ch.base_url,
        "modality": ch.modality,
        "enabled": ch.enabled,
        "timeout_seconds": ch.timeout_seconds,
        "extra_config_json": ch.extra_config_json or {},
    }
    if include_secret_meta:
        data["has_platform_key"] = bool(ch.platform_secret_ciphertext)
        data["last_four"] = ch.last_four
    return data


def set_platform_key(ch: AiChannel, api_key: str | None) -> None:
    if api_key is None:
        return
    plain = api_key.strip()
    if plain == "":
        return
    ch.platform_secret_ciphertext = encrypt_secret(plain)
    ch.last_four = last_four(plain)


def load_platform_key(ch: AiChannel) -> str | None:
    if not ch.platform_secret_ciphertext:
        return None
    try:
        return decrypt_secret(ch.platform_secret_ciphertext)
    except Exception:
        return None
