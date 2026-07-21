"""媒体地址的安全日志格式化工具。"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def safe_media_url_for_log(value: object) -> str:
    """仅保留媒体 URL 的协议、主机和路径，移除凭据与签名参数。"""
    text = str(value or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return text
    parsed = urlsplit(text)
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), host, parsed.path, "", ""))
