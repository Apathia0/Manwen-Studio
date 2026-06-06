"""
授权验证服务 — 授权站地址硬编码，无任何本地配置可篡改。

安全逻辑：
  - 授权站 URL 硬编码在代码中，不从 .env 读取
  - 没有 ENABLED 开关，无法通过改配置跳过
  - 没有 SERVER_URL 可配置，无法自建伪授权站
  - 用户必须修改 Python 源码才能绕过
  - localhost/127.0.0.1 自动跳过（开发环境）
"""

import logging
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

logger = logging.getLogger("license_checker")

# ============================================================
# 授权站地址 — 硬编码，不能被 .env 或配置文件覆盖
# 修改为你的 PHP 授权站实际部署地址
# ============================================================
_AUTH_SERVER_URL = "https://auth.aifusion6.cn"

_cache: dict[str, tuple[bool, datetime]] = {}
CACHE_TTL_SECONDS = 300

_DEV_DOMAINS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_dev_domain(hostname: str) -> bool:
    return hostname in _DEV_DOMAINS


def get_auth_page_url() -> str:
    return f"{_AUTH_SERVER_URL.rstrip('/')}/authorize.php"


def _do_check(domain: str) -> bool:
    """调用授权站 API 检查域名是否已授权。"""
    for attempt in range(2):
        try:
            api_url = f"{_AUTH_SERVER_URL.rstrip('/')}/api/check_license.php?domain={quote(domain, safe='')}"
            with httpx.Client(timeout=20) as client:
                resp = client.get(api_url)
                resp.raise_for_status()
                data = resp.json()
                authorized = data.get("success", False) and data.get("authorized", False)
                if authorized:
                    logger.info("域名 %s 授权通过", domain)
                else:
                    logger.warning("域名 %s 未授权", domain)
                return authorized
        except httpx.RequestError as e:
            if attempt == 0:
                logger.warning("授权站不可达，1秒后重试（%s）: %s", _AUTH_SERVER_URL, e)
                time.sleep(1)
            else:
                logger.error("授权站不可达（%s）: %s", _AUTH_SERVER_URL, e)
                return False
        except (ValueError, KeyError) as e:
            logger.error("授权站返回数据异常: %s", e)
            return False
    return False


def check_domain(domain: str) -> bool:
    """检查域名是否已授权（带 5 分钟缓存）。"""
    if domain in _cache:
        result, expiry = _cache[domain]
        if datetime.now() < expiry:
            return result

    result = _do_check(domain)
    _cache[domain] = (result, datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS))
    return result


def clear_cache():
    _cache.clear()
