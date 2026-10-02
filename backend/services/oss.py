"""云存储服务（OSS/S3 兼容）。

支持阿里云 OSS 及 S3 兼容存储。
配置通过 PlatformSetting 管理，与 deepseek/image2 等服务模式一致。

使用方式：
  1. 管理员在后台配置 OSS（Access Key / Secret / Endpoint / Bucket）
  2. 各模块在生成文件后调用 upload_file() 上传
  3. 返回的 URL 直接用于前端展示
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .ai.channels import validate_remote_media_url
from .media_logging import safe_media_url_for_log

logger = logging.getLogger("oss_service")
# oss2 把“对象不存在”（上传前的存在性查询）也按 info 记成 Exception，日志里像报错但其实正常
logging.getLogger("oss2.api").setLevel(logging.WARNING)

# 运行时配置
_runtime_enabled: bool = False
_runtime_access_key_id: str | None = None
_runtime_access_key_secret: str | None = None
_runtime_endpoint: str | None = None
_runtime_bucket: str | None = None
_runtime_public_url_base: str | None = None  # CDN / 自定义域名
MAX_REMOTE_MEDIA_BYTES = max(1, int(os.getenv("MAX_REMOTE_MEDIA_BYTES", str(2 * 1024 * 1024 * 1024))))


def configure(
    *,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
    endpoint: str | None = None,
    bucket: str | None = None,
    public_url_base: str | None = None,
    enabled: bool = False,
):
    """运行时注入 OSS 配置（优先于环境变量）。"""
    global _runtime_enabled, _runtime_access_key_id, _runtime_access_key_secret
    global _runtime_endpoint, _runtime_bucket, _runtime_public_url_base
    _runtime_enabled = enabled
    if access_key_id:
        _runtime_access_key_id = access_key_id
    if access_key_secret:
        _runtime_access_key_secret = access_key_secret
    if endpoint:
        _runtime_endpoint = endpoint
    if bucket:
        _runtime_bucket = bucket
    if public_url_base:
        _runtime_public_url_base = public_url_base.rstrip("/")


def is_enabled() -> bool:
    """OSS 是否已启用并配置。"""
    return (
        _runtime_enabled
        and bool(_runtime_access_key_id)
        and bool(_runtime_access_key_secret)
        and bool(_runtime_endpoint)
        and bool(_runtime_bucket)
    )


# 同一配置只创建一次客户端并确认一次 Bucket：之前每次上传 / 查询都会多发一次 create_bucket 请求
_client_cache: dict[tuple[str, str, str], Any] = {}
# 本进程内已确认在云端的文件：(对象键, 大小, 修改时间) → 公网链接。同一个文件再次引用时连查询都省掉。
_uploaded_urls: dict[tuple[str, int, int], str] = {}
_UPLOADED_URLS_MAX = 5000


def _get_client():
    """懒加载并缓存 oss2 客户端。"""
    import oss2

    cache_key = (_runtime_endpoint, _runtime_bucket, _runtime_access_key_id)
    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached
    auth = oss2.Auth(_runtime_access_key_id, _runtime_access_key_secret)
    bucket = oss2.Bucket(auth, _runtime_endpoint, _runtime_bucket)
    bucket.create_bucket()  # 如果 Bucket 不存在则创建（幂等）
    _client_cache[cache_key] = bucket
    return bucket


def upload_file(
    local_path: str | Path,
    remote_key: str | None = None,
    content_type: str | None = None,
    reuse_existing: bool = True,
) -> str | None:
    """上传本地文件到 OSS，返回公网可访问 URL。

    reuse_existing=True 时先查对象是否已在云端且大小一致：是就直接返回已有链接，不重复上传。
    对象键默认由文件相对路径生成（生成图的路径带运行 ID 和随机名，同一路径就是同一张图）。

    Args:
        local_path: 本地文件路径
        remote_key: OSS 对象键（默认使用 local_path 相对于项目目录的路径）
        content_type: 强制 Content-Type（如 image/png, video/mp4）

    Returns:
        文件的公网 URL，上传失败返回 None
    """
    if not is_enabled():
        logger.debug("OSS 未启用，跳过上传: %s", local_path)
        return None
    local_path = Path(local_path)
    if not local_path.exists():
        logger.warning("OSS 上传失败，文件不存在: %s", local_path)
        return None

    if not remote_key:
        remote_key = _default_remote_key(local_path)

    stat = local_path.stat()
    fingerprint = (remote_key, stat.st_size, stat.st_mtime_ns)
    if reuse_existing and fingerprint in _uploaded_urls:
        return _uploaded_urls[fingerprint]

    def remember(url: str) -> str:
        if len(_uploaded_urls) >= _UPLOADED_URLS_MAX:
            _uploaded_urls.pop(next(iter(_uploaded_urls)))
        _uploaded_urls[fingerprint] = url
        return url

    try:
        bucket = _get_client()
        if reuse_existing:
            try:
                existing_size = int(bucket.get_object_meta(remote_key).headers.get("Content-Length") or -1)
            except Exception:  # noqa: BLE001 - 对象不存在或查询失败都按“需要上传”处理
                existing_size = -1
            if existing_size == local_path.stat().st_size:
                url = _build_public_url(remote_key)
                logger.info("OSS 已存在同名同大小对象，直接复用: %s -> %s", local_path.name, url)
                return remember(url)
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        elif local_path.suffix.lower() in (".png",):
            headers["Content-Type"] = "image/png"
        elif local_path.suffix.lower() in (".jpg", ".jpeg"):
            headers["Content-Type"] = "image/jpeg"
        elif local_path.suffix.lower() in (".mp4",):
            headers["Content-Type"] = "video/mp4"
        elif local_path.suffix.lower() in (".webm",):
            headers["Content-Type"] = "video/webm"

        bucket.put_object_from_file(remote_key, str(local_path), headers=headers)
        url = _build_public_url(remote_key)
        logger.info("OSS 上传成功: %s -> %s", local_path.name, url)
        return remember(url)
    except Exception as exc:
        logger.error("OSS 上传失败 %s: %s", local_path, exc)
        return None


def create_browser_upload_signature(
    object_key: str,
    *,
    expires_seconds: int = 900,
) -> dict[str, Any] | None:
    """为浏览器生成一次受限的 OSS PUT 上传地址。"""
    if not is_enabled() or not _is_safe_object_key(object_key):
        return None
    try:
        expires_seconds = max(60, min(int(expires_seconds), 3600))
        upload_url = _get_client().sign_url("PUT", object_key, expires_seconds, slash_safe=True)
        return {
            "object_key": object_key,
            "upload_url": upload_url,
            "public_url": _build_public_url(object_key),
            "expires_at": int(time.time()) + expires_seconds,
        }
    except Exception as exc:
        logger.warning("生成浏览器直传签名失败: %s", type(exc).__name__)
        return None


def get_object_metadata(object_key: str) -> dict[str, Any] | None:
    """读取已直传对象的受控元数据，供业务接口在落库前确认。"""
    if not is_enabled() or not _is_safe_object_key(object_key):
        return None
    try:
        response = _get_client().get_object_meta(object_key)
        headers = response.headers
        return {
            "content_length": int(headers.get("Content-Length") or 0),
            "content_type": str(headers.get("Content-Type") or ""),
            "etag": str(headers.get("ETag") or "").strip('"'),
            "public_url": _build_public_url(object_key),
        }
    except Exception as exc:
        logger.warning("读取直传对象元数据失败: %s", type(exc).__name__)
        return None


def upload_dir(
    local_dir: str | Path,
    remote_prefix: str = "",
    extensions: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".mp4", ".webm"),
) -> list[dict[str, str]]:
    """上传目录下所有匹配文件到 OSS。

    Returns:
        [{"local": str, "remote_key": str, "url": str}, ...]
    """
    results: list[dict[str, str]] = []
    local_dir = Path(local_dir)
    if not local_dir.is_dir():
        return results
    for f in sorted(local_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in extensions:
            remote = f"{remote_prefix}/{f.relative_to(local_dir).as_posix()}" if remote_prefix else str(f.relative_to(local_dir.parent)).replace("\\", "/")
            url = upload_file(f, remote_key=remote)
            if url:
                results.append({"local": str(f), "remote_key": remote, "url": url})
    return results


def delete_file(remote_key: str) -> bool:
    """从 OSS 删除文件。"""
    if not is_enabled():
        return False
    try:
        bucket = _get_client()
        bucket.delete_object(remote_key)
        logger.info("OSS 删除成功: %s", remote_key)
        return True
    except Exception as exc:
        logger.error("OSS 删除失败 %s: %s", remote_key, exc)
        return False


def delete_by_url(url: str | None) -> bool:
    """从 OSS URL 中提取 key 并删除文件。

    支持格式：
      - https://<bucket>.<endpoint>/<key>
      - https://<custom-domain>/<key>
    """
    if not url or not is_enabled():
        return False
    key = _extract_key_from_url(url)
    if not key:
        return False
    return delete_file(key)


def _extract_key_from_url(url: str) -> str | None:
    """从 OSS URL 中提取对象 key。"""
    if not url:
        return None
    # 优先匹配 public_url_base
    if _runtime_public_url_base:
        prefix = _runtime_public_url_base.rstrip("/") + "/"
        if url.startswith(prefix):
            return url[len(prefix):]
    # 匹配 endpoint URL
    if _runtime_endpoint:
        ep = _runtime_endpoint.rstrip("/")
        if not ep.startswith("http"):
            ep = f"https://{ep}"
        prefix = ep + "/"
        if url.startswith(prefix):
            return url[len(prefix):]
    # 尝试匹配 bucket.endpoint 模式
    if _runtime_endpoint and _runtime_bucket:
        patterns = [
            f"https://{_runtime_bucket}.{_runtime_endpoint.lstrip('https://').lstrip('http://')}/",
            f"http://{_runtime_bucket}.{_runtime_endpoint.lstrip('https://').lstrip('http://')}/",
        ]
        for p in patterns:
            if url.startswith(p):
                return url[len(p):]
    return None


def _default_remote_key(local_path: Path) -> str:
    """根据本地路径生成默认的 OSS 对象键。

    保留 backend/manga_outputs/xxx 或 backend/video_outputs/xxx 的目录结构。
    """
    backend_root = Path(__file__).resolve().parent.parent
    try:
        rel = local_path.resolve().relative_to(backend_root.resolve())
        return rel.as_posix()
    except ValueError:
        return local_path.name


def _is_safe_object_key(object_key: str) -> bool:
    """拒绝路径穿越和绝对路径，避免签名被用于范围外对象。"""
    key = str(object_key or "").replace("\\", "/")
    return bool(key and not key.startswith("/") and ".." not in key.split("/"))


def _build_public_url(remote_key: str) -> str:
    """构建公网可访问 URL。

    优先使用自定义域名（public_url_base），否则使用 OSS 默认域名。
    """
    if _runtime_public_url_base:
        return f"{_runtime_public_url_base}/{remote_key}"
    # 标准 OSS URL: https://<bucket>.<endpoint>/<key>
    endpoint = _runtime_endpoint or ""
    if endpoint.startswith("http"):
        base = endpoint.rstrip("/")
    else:
        base = f"https://{endpoint}"
    return f"{base}/{remote_key}"


def auto_configure_from_db() -> bool:
    """从数据库自动加载 OSS 配置。

    可用于任何需要上传文件但尚未配置 OSS 的场景。
    首次调用后会缓存配置，重复调用幂等。

    Returns:
        是否成功启用 OSS
    """
    if is_enabled():
        return True
    try:
        from database import SessionLocal
        from models import PlatformSetting
        from services.ai.crypto_secrets import read_platform_setting_payload

        db = SessionLocal()
        try:
            def _get(key: str, default=None):
                s = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
                return read_platform_setting_payload(s.value_json, default) if s else default

            enabled = bool(_get("oss.enabled", False))
            if not enabled:
                return False

            configure(
                enabled=True,
                access_key_id=str(_get("oss.access_key_id", "") or "").strip(),
                access_key_secret=str(_get("oss.access_key_secret", "") or "").strip(),
                endpoint=str(_get("oss.endpoint", "") or "").strip(),
                bucket=str(_get("oss.bucket", "") or "").strip(),
                public_url_base=str(_get("oss.public_url_base", "") or "").strip(),
            )
            logger.info("OSS 已自动从数据库加载配置")
            return True
        finally:
            db.close()
    except Exception as exc:
        logger.warning("OSS 自动配置加载失败: %s", exc)
        return False


def upload_from_url(
    source_url: str,
    remote_key: str,
    content_type: str | None = None,
) -> str | None:
    """从 URL 直接上传到 OSS，跳过本地存储。

    适用于上游 API 返回图片 URL 的场景，避免先下载到本地再上传的耗时操作。

    Args:
        source_url: 源文件 URL（如上游 CDN 地址）
        remote_key: OSS 对象键
        content_type: 强制 Content-Type

    Returns:
        OSS 公网 URL，失败返回 None
    """
    if not is_enabled():
        return None
    try:
        source_url = validate_remote_media_url(source_url)
        bucket = _get_client()
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type

        # 使用 httpx 流式下载并同时上传到 OSS
        import httpx
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=30, read=600, write=30, pool=30), follow_redirects=False) as client:
            with client.stream("GET", source_url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_REMOTE_MEDIA_BYTES:
                    raise RuntimeError("远程媒体超过允许的最大大小")
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as data:
                    total_bytes = 0
                    for chunk in response.iter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > MAX_REMOTE_MEDIA_BYTES:
                            raise RuntimeError("远程媒体超过允许的最大大小")
                        data.write(chunk)
                    data.seek(0)
                    bucket.put_object(remote_key, data, headers=headers)
        url = _build_public_url(remote_key)
        logger.info(
            "OSS 从 URL 直传成功: %s -> %s",
            safe_media_url_for_log(source_url),
            safe_media_url_for_log(url),
        )
        return url
    except Exception as exc:
        logger.warning(
            "OSS 从 URL 直传失败 %s (%s)",
            safe_media_url_for_log(source_url),
            type(exc).__name__,
        )
        return None


def upload_and_cleanup(local_path: str | Path) -> str | None:
    """上传文件到 OSS（自动配置），成功后删除本地文件。

    Args:
        local_path: 本地文件路径

    Returns:
        OSS 公网 URL，失败或未配置返回 None
    """
    auto_configure_from_db()
    if not is_enabled():
        return None
    url = upload_file(local_path)
    if url:
        try:
            Path(local_path).unlink(missing_ok=True)
            logger.info("OSS 上传成功，已删除本地文件: %s", local_path)
        except Exception:
            pass
    return url
