import asyncio
import contextlib
import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import smtplib
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from sqlalchemy import func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal, get_db, init_db
from models import (
    AuditLog,
    BillingOrder,
    Chapter,
    EmailVerificationCode,
    ChatMessage,
    MangaImage,
    Plan,
    PlanFeature,
    PlanQuotaRule,
    PlatformSetting,
    Story,
    User,
    UserQuotaGrantMonthly,
    UserSession,
    UserSubscription,
    UserUsageMonthly,
)
from schemas import (
    ChapterContentUpdate,
    ChapterOut,
    ChatMessageIn,
    ChatMessageOut,
    MangaImageOut,
    OutlineChapterPlanUpdate,
    StoryCreate,
    StoryOut,
    StoryUpdate,
)
from services.deepseek import (
    adjust_chapter_content,
    adjust_framework_with_chat,
    chat_stream,
    continue_framework,
    expand_chapter_to_content,
    generate_character_profiles_from_framework,
    generate_framework,
    generate_novel,
    quality_assess,
    regenerate_characters,
    regenerate_outline,
    regenerate_tags,
    rewrite_selection,
    scenes_from_selection,
    split_scenes,
)
from services.errors import MangaImageGenerationError, MissingApiKeyError
from services.image2 import edit_existing_image, generate_manga_image, generate_reference_image
from services.scene_safety import sanitize_scene_list
from services import deepseek as deepseek_service
from services import image2 as image_service
from services import alipay_f2f

load_dotenv()

logger = logging.getLogger("main")
ACTIVE_MANGA_GENERATIONS: set[int] = set()
MONEY_QUANT = Decimal("0.01")

FEATURE_CATALOG: list[dict] = [
    {
        "key": "framework.generate.monthly_limit",
        "name": "\u5c0f\u8bf4\u6846\u67b6\u751f\u6210\u6b21\u6570",
        "description": "\u7528\u6237\u6bcf\u6708\u53ef\u751f\u6210\u4e16\u754c\u89c2\u3001\u89d2\u8272\u4e0e\u5927\u7eb2\u7684\u6b21\u6570\u3002",
        "category": "\u5c0f\u8bf4\u521b\u4f5c",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "chapter.expand.monthly_limit",
        "name": "\u7ae0\u8282\u6269\u5199\u6b21\u6570",
        "description": "\u7528\u6237\u6bcf\u6708\u53ef\u5c06\u7ae0\u8282\u8ba1\u5212\u6269\u5199\u6210\u6b63\u6587\u7684\u6b21\u6570\u3002",
        "category": "\u5c0f\u8bf4\u521b\u4f5c",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "scene.generate.monthly_limit",
        "name": "\u5206\u955c\u751f\u6210\u6b21\u6570",
        "description": "\u7528\u6237\u6bcf\u6708\u53ef\u5c06\u6587\u672c\u62c6\u5206\u4e3a\u6f2b\u753b\u5206\u955c\u7684\u6b21\u6570\u3002",
        "category": "\u6f2b\u753b\u751f\u6210",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "manga.image.monthly_limit",
        "name": "\u6f2b\u753b\u56fe\u7247\u751f\u6210\u5f20\u6570",
        "description": "\u7528\u6237\u6bcf\u6708\u53ef\u751f\u6210\u7684\u6f2b\u753b\u56fe\u7247\u603b\u5f20\u6570\u3002",
        "category": "\u6f2b\u753b\u751f\u6210",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "manga.regenerate.monthly_limit",
        "name": "\u6f2b\u753b\u91cd\u7ed8\u6b21\u6570",
        "description": "\u7528\u6237\u6bcf\u6708\u53ef\u91cd\u65b0\u751f\u6210\u5355\u5f20\u6f2b\u753b\u56fe\u7247\u7684\u6b21\u6570\u3002",
        "category": "\u6f2b\u753b\u751f\u6210",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "ai.text.advanced_calls.monthly_limit",
        "name": "\u9ad8\u7ea7\u6587\u672c AI \u8c03\u7528\u6b21\u6570",
        "description": "\u7528\u4e8e\u6846\u67b6\u8c03\u6574\u3001\u7ee7\u7eed\u6269\u5c55\u3001\u6587\u672c\u6539\u5199\u3001\u6b63\u6587\u8c03\u6574\u3001\u8d28\u91cf\u8bc4\u4f30\u4e0e\u5355\u9879\u91cd\u751f\u6210\u7b49\u9ad8\u7ea7\u6587\u672c\u80fd\u529b\u3002",
        "category": "\u9ad8\u7ea7\u6587\u672c\u80fd\u529b",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "manga.max_image_count_per_chapter",
        "name": "\u5355\u7ae0\u8282\u6700\u5927\u51fa\u56fe\u6570",
        "description": "\u5355\u4e2a\u7ae0\u8282\u5141\u8bb8\u751f\u6210\u7684\u6700\u5927\u6f2b\u753b\u9875\u6570\u3002",
        "category": "\u6f2b\u753b\u751f\u6210",
        "value_type": "number",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
    {
        "key": "manga.allow_color_mode",
        "name": "\u5141\u8bb8\u5f69\u6f2b\u6a21\u5f0f",
        "description": "\u63a7\u5236\u8be5\u5957\u9910\u7528\u6237\u662f\u5426\u53ef\u5207\u6362\u5f69\u8272\u6f2b\u753b\u8f93\u51fa\u3002",
        "category": "\u6f2b\u753b\u751f\u6210",
        "value_type": "boolean",
        "default_rule": {"reset_period": "monthly", "deduct_mode": "on_success"},
    },
]

FEATURE_CATALOG_MAP = {item["key"]: item for item in FEATURE_CATALOG}

app = FastAPI(title="Novel & Manga Generator")

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
MAX_CHARACTER_PROFILE_CHARS = int(os.getenv("MAX_CHARACTER_PROFILE_CHARS", "20000"))
API_TOKEN = os.getenv("API_TOKEN", "").strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingApiKeyError)
async def _missing_api_key_handler(request: Request, exc: MissingApiKeyError):
    return JSONResponse(status_code=400, content={"detail": str(exc), "provider": exc.provider})

# Serve generated manga images as static files
manga_dir = Path(__file__).resolve().parent / "manga_outputs"
manga_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/manga", StaticFiles(directory=str(manga_dir)), name="manga")


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if API_TOKEN and request.url.path.startswith("/api") and request.method != "OPTIONS":
        supplied = request.headers.get("x-api-token", "").strip()
        if not supplied:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                bearer = auth[7:].strip()
                if bearer == API_TOKEN:
                    supplied = bearer
        if supplied != API_TOKEN:
            return JSONResponse({"detail": "Invalid or missing API token"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def bind_request_db(request: Request, call_next):
    db = SessionLocal()
    request.state.db = db
    try:
        return await call_next(request)
    finally:
        db.close()


def _require_chapter(chapter_id: int, db: Session) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    return chapter


def _get_platform_setting(key: str, db: Session, default=None):
    setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if not setting:
        return default
    payload = setting.value_json or {}
    return payload.get("value", default)


def _set_platform_setting(key: str, value, db: Session) -> None:
    setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if setting:
        setting.value_json = {"value": value}
    else:
        db.add(PlatformSetting(setting_key=key, value_json={"value": value}))


def _platform_settings_snapshot(db: Session) -> dict:
    return {
        "basic": {
            "site_name": _get_platform_setting("platform.site_name", db, "StoryCanvas"),
            "site_slogan": _get_platform_setting("platform.site_slogan", db, "AI 小说漫画创作平台"),
            "support_email": _get_platform_setting("platform.support_email", db, ""),
            "icp": _get_platform_setting("platform.icp", db, ""),
            "copyright": _get_platform_setting("platform.copyright", db, ""),
            "notice": _get_platform_setting("platform.notice", db, ""),
            "icon_url": _platform_icon_url(db),
        },
        "api": {
            "deepseek_base_url": _get_platform_setting("api.deepseek.base_url", db, "https://api.deepseek.com"),
            "deepseek_model": _get_platform_setting("api.deepseek.model", db, "deepseek-chat"),
            "deepseek_api_key": _get_platform_setting("api.deepseek.api_key", db, ""),
            "image_base_url": _get_platform_setting("api.image.base_url", db, "https://api.xbyjs.top/v1"),
            "image_model": _get_platform_setting("api.image.model", db, "default"),
            "image_api_key": _get_platform_setting("api.image.api_key", db, ""),
            "enable_user_override": bool(_get_platform_setting("api.enable_user_override", db, True)),
            "enable_user_url_override": bool(_get_platform_setting("api.enable_user_url_override", db, False)),
        },
        "auth": {
            "require_email_code_for_register": bool(_get_platform_setting("auth.require_email_code_for_register", db, False)),
            "require_email_code_for_login": bool(_get_platform_setting("auth.require_email_code_for_login", db, False)),
            "email_code_expire_minutes": int(_get_platform_setting("auth.email_code_expire_minutes", db, 10) or 10),
            "email_code_length": int(_get_platform_setting("auth.email_code_length", db, 6) or 6),
        },
        "email": {
            "smtp_enabled": bool(_get_platform_setting("email.smtp_enabled", db, False)),
            "smtp_host": str(_get_platform_setting("email.smtp_host", db, "") or ""),
            "smtp_port": int(_get_platform_setting("email.smtp_port", db, 587) or 587),
            "smtp_username": str(_get_platform_setting("email.smtp_username", db, "") or ""),
            "smtp_password": str(_get_platform_setting("email.smtp_password", db, "") or ""),
            "smtp_from_email": str(_get_platform_setting("email.smtp_from_email", db, "") or ""),
            "smtp_from_name": str(_get_platform_setting("email.smtp_from_name", db, "StoryCanvas") or "StoryCanvas"),
            "smtp_use_tls": bool(_get_platform_setting("email.smtp_use_tls", db, True)),
            "smtp_use_ssl": bool(_get_platform_setting("email.smtp_use_ssl", db, False)),
        },
        "announcement": {
            "enabled": bool(_get_platform_setting("platform.announcement.enabled", db, False)),
            "title": str(_get_platform_setting("platform.announcement.title", db, "") or ""),
            "content": str(_get_platform_setting("platform.announcement.content", db, "") or ""),
        },
        "payment": {
            "enabled": bool(_get_platform_setting("payment.enabled", db, True)),
            "mode": str(_get_platform_setting("payment.mode", db, "mock")),
            "default_method": str(_get_platform_setting("payment.default_method", db, "mock_qr")),
            "order_expire_minutes": int(_get_platform_setting("payment.order_expire_minutes", db, 30) or 30),
            "auto_activate_free_plan": bool(_get_platform_setting("payment.auto_activate_free_plan", db, True)),
            "instructions": str(_get_platform_setting("payment.instructions", db, "测试环境可使用模拟支付；正式上线时请切换到真实支付网关。") or ""),
            "mock_enabled": bool(_get_platform_setting("payment.mock_enabled", db, True)),
            "wechat_enabled": bool(_get_platform_setting("payment.wechat_enabled", db, False)),
            "wechat_app_id": str(_get_platform_setting("payment.wechat_app_id", db, "") or ""),
            "wechat_mch_id": str(_get_platform_setting("payment.wechat_mch_id", db, "") or ""),
            "wechat_notify_url": str(_get_platform_setting("payment.wechat_notify_url", db, "") or ""),
            "alipay_enabled": bool(_get_platform_setting("payment.alipay_enabled", db, False)),
            "alipay_app_id": str(_get_platform_setting("payment.alipay_app_id", db, "") or ""),
            "alipay_pid": str(_get_platform_setting("payment.alipay_pid", db, "") or ""),
            "alipay_gateway": str(_get_platform_setting("payment.alipay_gateway", db, "https://openapi.alipay.com/gateway.do") or ""),
            "alipay_sign_type": str(_get_platform_setting("payment.alipay_sign_type", db, "RSA2") or "RSA2"),
            "alipay_app_private_key": str(_get_platform_setting("payment.alipay_app_private_key", db, "") or ""),
            "alipay_public_key": str(_get_platform_setting("payment.alipay_public_key", db, "") or ""),
            "alipay_notify_url": str(_get_platform_setting("payment.alipay_notify_url", db, "") or ""),
        },
    }


def _payment_settings_snapshot(db: Session) -> dict:
    return _platform_settings_snapshot(db)["payment"]


def _auth_settings_snapshot(db: Session) -> dict:
    return _platform_settings_snapshot(db)["auth"]


def _email_settings_snapshot(db: Session) -> dict:
    return _platform_settings_snapshot(db)["email"]


def _platform_icon_url(db: Session) -> str:
    icon_data = _get_platform_setting("platform.icon_data", db, "")
    if not icon_data:
        return "/brand-mark.svg"
    version = _get_platform_setting("platform.icon_updated_at", db, "") or "1"
    return f"/api/platform/icon?v={version}"


def _public_platform_settings_snapshot(db: Session) -> dict:
    snapshot = _platform_settings_snapshot(db)
    basic = snapshot["basic"]
    api = snapshot["api"]
    auth = snapshot["auth"]
    return {
        "site_name": basic.get("site_name") or "StoryCanvas",
        "site_slogan": basic.get("site_slogan") or "",
        "support_email": basic.get("support_email") or "",
        "icp": basic.get("icp") or "",
        "copyright": basic.get("copyright") or "",
        "notice": basic.get("notice") or "",
        "icon_url": _platform_icon_url(db),
        "api": {
            "deepseek_base_url": api.get("deepseek_base_url") or "",
            "deepseek_model": api.get("deepseek_model") or "",
            "image_base_url": api.get("image_base_url") or "",
            "image_model": api.get("image_model") or "",
        },
        "auth": {
            "require_email_code_for_register": bool(auth.get("require_email_code_for_register")),
            "require_email_code_for_login": bool(auth.get("require_email_code_for_login")),
            "email_code_expire_minutes": int(auth.get("email_code_expire_minutes") or 10),
        },
        "announcement": {
            "enabled": bool(_get_platform_setting("platform.announcement.enabled", db, False)),
            "title": str(_get_platform_setting("platform.announcement.title", db, "") or ""),
            "content": str(_get_platform_setting("platform.announcement.content", db, "") or ""),
        },
    }


def _payment_method_options(db: Session) -> list[dict]:
    payment = _payment_settings_snapshot(db)
    methods = [
        {"key": "mock_qr", "label": "模拟支付", "enabled": bool(payment.get("mock_enabled")), "provider": "mock"},
        {"key": "wechat_qr", "label": "微信扫码", "enabled": bool(payment.get("wechat_enabled")), "provider": "wechat"},
        {"key": "alipay_qr", "label": "支付宝扫码", "enabled": bool(payment.get("alipay_enabled")), "provider": "alipay"},
    ]
    return [item for item in methods if item["enabled"]]


def _public_payment_config(db: Session) -> dict:
    payment = _payment_settings_snapshot(db)
    return {
        "enabled": bool(payment.get("enabled")),
        "mode": str(payment.get("mode") or "mock"),
        "default_method": str(payment.get("default_method") or "mock_qr"),
        "order_expire_minutes": int(payment.get("order_expire_minutes") or 30),
        "instructions": str(payment.get("instructions") or ""),
        "methods": _payment_method_options(db),
    }


def _user_api_override_capabilities(user: User | None, db: Session) -> dict[str, bool]:
    key_global = bool(_get_platform_setting("api.enable_user_override", db, True))
    url_global = bool(_get_platform_setting("api.enable_user_url_override", db, False))
    return {
        "can_override_api_key": key_global and bool(user and user.allow_api_key_override),
        "can_override_api_url": url_global and bool(user and user.allow_api_url_override),
    }


def _serialize_auth_user(user: User, db: Session) -> dict:
    capabilities = _user_api_override_capabilities(user, db)
    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "email": user.email,
        "can_override_api_key": capabilities["can_override_api_key"],
        "can_override_api_url": capabilities["can_override_api_url"],
    }


def _custom_text_provider_active(request: Request) -> bool:
    db = getattr(request.state, "db", None)
    if db is None:
        return False
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    if not capabilities["can_override_api_url"]:
        return False
    return bool((request.headers.get("x-deepseek-base-url") or "").strip())


def _custom_image_provider_active(request: Request) -> bool:
    db = getattr(request.state, "db", None)
    if db is None:
        return False
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    if not capabilities["can_override_api_url"]:
        return False
    return bool((request.headers.get("x-image-base-url") or "").strip())


def _check_and_consume_feature_quota(
    request: Request,
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    *,
    deduct: bool,
    provider_kind: str | None = None,
) -> dict:
    if provider_kind == "text" and _custom_text_provider_active(request):
        return {"skipped": True, "reason": "custom_text_provider", "feature_key": feature_key}
    if provider_kind == "image" and _custom_image_provider_active(request):
        return {"skipped": True, "reason": "custom_image_provider", "feature_key": feature_key}
    return _check_and_consume_quota(user_id, feature_key, amount, db, deduct=deduct)


def _user_deepseek_api_key(request: Request) -> str | None:
    override = request.headers.get("x-deepseek-api-key") or None
    override_base_url = request.headers.get("x-deepseek-base-url") or None
    override_model = request.headers.get("x-deepseek-model") or None
    db = getattr(request.state, "db", None)
    if db is None:
        return override
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.deepseek.base_url", db, deepseek_service.DEEPSEEK_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.deepseek.model", db, deepseek_service.DEEPSEEK_MODEL)).strip()
    resolved_base_url = override_base_url.strip() if capabilities["can_override_api_url"] and override_base_url and override_base_url.strip() else admin_base_url
    resolved_model = override_model.strip() if capabilities["can_override_api_url"] and override_model and override_model.strip() else admin_model
    deepseek_service.DEEPSEEK_BASE_URL = resolved_base_url.rstrip("/") or deepseek_service.DEEPSEEK_BASE_URL
    deepseek_service.DEEPSEEK_MODEL = resolved_model or deepseek_service.DEEPSEEK_MODEL
    if capabilities["can_override_api_key"] and override:
        return override
    return _get_platform_setting("api.deepseek.api_key", db, "") or None


def _user_image_api_key(request: Request) -> str | None:
    override = request.headers.get("x-image-api-key") or None
    override_base_url = request.headers.get("x-image-base-url") or None
    override_model = request.headers.get("x-image-model") or None
    db = getattr(request.state, "db", None)
    if db is None:
        return override
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.image.base_url", db, image_service.IMAGE_API_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.image.model", db, image_service.IMAGE_MODEL)).strip()
    resolved_base_url = override_base_url.strip() if capabilities["can_override_api_url"] and override_base_url and override_base_url.strip() else admin_base_url
    resolved_model = override_model.strip() if capabilities["can_override_api_url"] and override_model and override_model.strip() else admin_model
    image_service.IMAGE_API_BASE_URL = resolved_base_url.rstrip("/") or image_service.IMAGE_API_BASE_URL
    image_service.IMAGE_MODEL = resolved_model or image_service.IMAGE_MODEL
    if capabilities["can_override_api_key"] and override:
        return override
    return _get_platform_setting("api.image.api_key", db, "") or None


def _password_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_session_token() -> str:
    return f"lv_{secrets.token_urlsafe(32)}"


def _current_period_key(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.utcnow()
    return now.strftime("%Y%m")


def _parse_auth_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _normalize_email(raw: object) -> str:
    return str(raw or "").strip().lower()


def _validate_email_format(email: str) -> None:
    if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "邮箱格式不正确")


def _verification_code_hash(email: str, purpose: str, code: str) -> str:
    payload = f"{email}|{purpose}|{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _generate_verification_code(length: int) -> str:
    digits = max(4, min(int(length or 6), 8))
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def _send_platform_email(to_email: str, subject: str, text_body: str, db: Session) -> None:
    settings = _email_settings_snapshot(db)
    if not settings.get("smtp_enabled"):
        raise HTTPException(503, "邮箱发信服务未启用")
    host = str(settings.get("smtp_host") or "").strip()
    username = str(settings.get("smtp_username") or "").strip()
    password = str(settings.get("smtp_password") or "")
    from_email = str(settings.get("smtp_from_email") or username or "").strip()
    if not host or not from_email:
        raise HTTPException(503, "邮箱发信配置不完整，请先填写 SMTP 主机和发件邮箱")
    port = int(settings.get("smtp_port") or 587)
    use_ssl = bool(settings.get("smtp_use_ssl"))
    use_tls = bool(settings.get("smtp_use_tls"))
    msg = EmailMessage()
    from_name = str(settings.get("smtp_from_name") or "StoryCanvas").strip() or "StoryCanvas"
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                if username:
                    server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if use_tls:
                    server.starttls()
                    server.ehlo()
                if username:
                    server.login(username, password)
                server.send_message(msg)
    except Exception as exc:
        logger.exception("Failed to send verification email to %s", to_email)
        raise HTTPException(502, f"邮件发送失败：{exc}")


def _issue_email_verification_code(email: str, purpose: str, db: Session) -> dict:
    _validate_email_format(email)
    auth = _auth_settings_snapshot(db)
    code_length = int(auth.get("email_code_length") or 6)
    expire_minutes = int(auth.get("email_code_expire_minutes") or 10)
    now = datetime.datetime.utcnow()
    latest = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
        )
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    if latest and latest.created_at and (now - latest.created_at).total_seconds() < 60:
        raise HTTPException(429, "验证码发送过于频繁，请稍后再试")
    code = _generate_verification_code(code_length)
    expires_at = now + datetime.timedelta(minutes=max(1, expire_minutes))
    (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .update({"consumed_at": now}, synchronize_session=False)
    )
    db.add(
        EmailVerificationCode(
            email=email,
            purpose=purpose,
            code_hash=_verification_code_hash(email, purpose, code),
            expires_at=expires_at,
        )
    )
    subject_action = "注册" if purpose == "register" else "登录"
    subject = f"{_get_platform_setting('platform.site_name', db, 'StoryCanvas')} {subject_action}验证码"
    body = (
        f"您好，\n\n"
        f"您本次用于{subject_action}的验证码是：{code}\n"
        f"验证码将在 {expire_minutes} 分钟后失效。\n"
        f"如果这不是您的操作，请忽略这封邮件。\n"
    )
    _send_platform_email(email, subject, body, db)
    db.commit()
    return {"ok": True, "expires_in_seconds": expire_minutes * 60}


def _consume_email_verification_code(email: str, purpose: str, code: str, db: Session) -> None:
    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise HTTPException(400, "请输入邮箱验证码")
    now = datetime.datetime.utcnow()
    record = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(400, "未找到可用验证码，请先发送验证码")
    if record.expires_at < now:
        record.consumed_at = now
        db.commit()
        raise HTTPException(400, "验证码已过期，请重新发送")
    if record.code_hash != _verification_code_hash(email, purpose, normalized_code):
        raise HTTPException(400, "邮箱验证码不正确")
    record.consumed_at = now
    db.commit()


def _ensure_platform_seed(db: Session) -> None:
    admin = db.query(User).filter(User.email == "admin@lorevista.ai").first()
    if not admin:
        db.add(User(
            email="admin@lorevista.ai",
            password_hash=_password_hash("admin123"),
            name="运营管理员",
            role="admin",
            status="active",
        ))
        db.commit()

    if db.query(Plan).count() > 0:
        _ensure_plan_feature_seed(db)
        if not db.query(PlatformSetting).first():
            _seed_platform_settings(db)
            db.commit()
        return

    free = Plan(
        code="free",
        name="Free",
        description="适合体验",
        monthly_price=0,
        yearly_price=0,
        is_recommended=False,
        is_visible=True,
    )
    pro = Plan(
        code="pro",
        name="Pro",
        description="适合稳定创作",
        monthly_price=59,
        yearly_price=599,
        is_recommended=True,
        is_visible=True,
    )
    premium = Plan(
        code="premium",
        name="Premium",
        description="适合高频创作",
        monthly_price=199,
        yearly_price=1999,
        is_recommended=False,
        is_visible=True,
    )
    db.add_all([free, pro, premium])
    db.flush()

    defaults = {
        "free": {
            "framework.generate.monthly_limit": 5,
            "chapter.expand.monthly_limit": 20,
            "scene.generate.monthly_limit": 15,
            "manga.image.monthly_limit": 80,
            "manga.regenerate.monthly_limit": 20,
            "ai.text.advanced_calls.monthly_limit": 20,
            "manga.max_image_count_per_chapter": 6,
            "manga.allow_color_mode": False,
        },
        "pro": {
            "framework.generate.monthly_limit": 50,
            "chapter.expand.monthly_limit": 200,
            "scene.generate.monthly_limit": 120,
            "manga.image.monthly_limit": 800,
            "manga.regenerate.monthly_limit": 300,
            "ai.text.advanced_calls.monthly_limit": 180,
            "manga.max_image_count_per_chapter": 12,
            "manga.allow_color_mode": True,
        },
        "premium": {
            "framework.generate.monthly_limit": 200,
            "chapter.expand.monthly_limit": 1000,
            "scene.generate.monthly_limit": 500,
            "manga.image.monthly_limit": 4000,
            "manga.regenerate.monthly_limit": 1500,
            "ai.text.advanced_calls.monthly_limit": 600,
            "manga.max_image_count_per_chapter": 20,
            "manga.allow_color_mode": True,
        },
    }
    for plan in [free, pro, premium]:
        for key, value in defaults[plan.code].items():
            db.add(
                PlanFeature(
                    plan_id=plan.id,
                    feature_key=key,
                    value_json={"value": value},
                )
            )
            db.add(
                PlanQuotaRule(
                    plan_id=plan.id,
                    feature_key=key,
                    reset_period="monthly",
                    deduct_mode="on_success",
                    extra_config={"carry_over_enabled": False},
                )
            )

    db.commit()
    _seed_platform_settings(db)
    db.commit()


def _ensure_plan_feature_seed(db: Session) -> None:
    default_limits = {
        "free": {
            "ai.text.advanced_calls.monthly_limit": 20,
        },
        "pro": {
            "ai.text.advanced_calls.monthly_limit": 180,
        },
        "premium": {
            "ai.text.advanced_calls.monthly_limit": 600,
        },
    }
    changed = False
    plans = db.query(Plan).all()
    for plan in plans:
        plan_defaults = default_limits.get(plan.code, {})
        for feature in FEATURE_CATALOG:
            feature_key = str(feature["key"])
            feature_row = db.query(PlanFeature).filter(PlanFeature.plan_id == plan.id, PlanFeature.feature_key == feature_key).first()
            if not feature_row:
                default_value = plan_defaults.get(feature_key, 0)
                db.add(PlanFeature(plan_id=plan.id, feature_key=feature_key, value_json={"value": default_value}))
                changed = True
            rule_row = db.query(PlanQuotaRule).filter(PlanQuotaRule.plan_id == plan.id, PlanQuotaRule.feature_key == feature_key).first()
            if not rule_row:
                default_rule = feature.get("default_rule") if isinstance(feature.get("default_rule"), dict) else {}
                db.add(PlanQuotaRule(
                    plan_id=plan.id,
                    feature_key=feature_key,
                    reset_period=str(default_rule.get("reset_period") or "monthly"),
                    deduct_mode=str(default_rule.get("deduct_mode") or "on_success"),
                    extra_config={"carry_over_enabled": False},
                ))
                changed = True
    if changed:
        db.commit()


def _seed_platform_settings(db: Session) -> None:
    defaults = {
        "platform.site_name": "StoryCanvas",
        "platform.site_slogan": "AI 小说漫画创作平台",
        "platform.support_email": "support@storycanvas.ai",
        "platform.icp": "",
        "platform.copyright": "© StoryCanvas",
        "platform.notice": "欢迎使用企业级 AI 小说漫画创作平台。",
        "api.deepseek.base_url": "https://api.deepseek.com",
        "api.deepseek.model": "deepseek-chat",
        "api.deepseek.api_key": "",
        "api.image.base_url": "https://api.xbyjs.top/v1",
        "api.image.model": "default",
        "api.image.api_key": "",
        "api.enable_user_override": True,
        "api.enable_user_url_override": False,
        "auth.require_email_code_for_register": False,
        "auth.require_email_code_for_login": False,
        "auth.email_code_expire_minutes": 10,
        "auth.email_code_length": 6,
        "platform.announcement.enabled": False,
        "platform.announcement.title": "",
        "platform.announcement.content": "",
        "email.smtp_enabled": False,
        "email.smtp_host": "",
        "email.smtp_port": 587,
        "email.smtp_username": "",
        "email.smtp_password": "",
        "email.smtp_from_email": "",
        "email.smtp_from_name": "StoryCanvas",
        "email.smtp_use_tls": True,
        "email.smtp_use_ssl": False,
        "payment.enabled": True,
        "payment.mode": "mock",
        "payment.default_method": "mock_qr",
        "payment.order_expire_minutes": 30,
        "payment.auto_activate_free_plan": True,
        "payment.instructions": "测试环境可使用模拟支付；正式上线时请切换到真实支付网关。",
        "payment.mock_enabled": True,
        "payment.wechat_enabled": False,
        "payment.wechat_app_id": "",
        "payment.wechat_mch_id": "",
        "payment.wechat_notify_url": "",
        "payment.alipay_enabled": False,
        "payment.alipay_app_id": "",
        "payment.alipay_pid": "",
        "payment.alipay_gateway": "https://openapi.alipay.com/gateway.do",
        "payment.alipay_sign_type": "RSA2",
        "payment.alipay_app_private_key": "",
        "payment.alipay_public_key": "",
        "payment.alipay_notify_url": "",
    }
    for key, value in defaults.items():
        if db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first():
            continue
        db.add(PlatformSetting(setting_key=key, value_json={"value": value}))


def _require_user(request: Request, db: Session) -> User:
    token = _parse_auth_token(request)
    if not token:
        raise HTTPException(401, "Unauthorized")
    session = db.query(UserSession).filter(UserSession.token == token, UserSession.revoked_at.is_(None)).first()
    if not session:
        raise HTTPException(401, "Session expired or invalid token")
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        raise HTTPException(403, "User unavailable")
    request.state.current_user = user
    return user


def _require_admin(request: Request, db: Session) -> User:
    user = _require_user(request, db)
    if user.role != "admin":
        raise HTTPException(403, "Admin permission required")
    return user


def _active_plan_for_user(user_id: int, db: Session) -> Plan:
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
    if sub:
        plan = db.get(Plan, sub.plan_id)
        if plan:
            return plan
    free = db.query(Plan).filter(Plan.code == "free").first()
    if not free:
        raise HTTPException(500, "Seed plan missing")
    return free


def _require_story_for_user(story_id: int, user: User, db: Session) -> Story:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "Story access denied")
    return story


def _require_chapter_for_user(chapter_id: int, user: User, db: Session) -> Chapter:
    chapter = _require_chapter(chapter_id, db)
    story = chapter.story
    if not story:
        raise HTTPException(404, "Story not found")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "Chapter access denied")
    return chapter


def _plan_feature_map(plan_id: int, db: Session) -> dict[str, object]:
    features = db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).all()
    result: dict[str, object] = {}
    for item in features:
        payload = item.value_json or {}
        result[item.feature_key] = payload.get("value")
    return result


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return default


def _coerce_money(value: object, default: str = "0.00") -> Decimal:
    if value is None or value == "":
        return Decimal(default).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    if isinstance(value, Decimal):
        return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _parse_money_input(value: object, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else "0")).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(400, f"{field_name} must be a valid number") from exc
    if amount < 0:
        raise HTTPException(400, f"{field_name} must be greater than or equal to 0")
    return amount


def _money_to_number(value: object) -> float:
    return float(_coerce_money(value))


def _plan_feature_value(user_id: int, feature_key: str, db: Session):
    plan = _active_plan_for_user(user_id, db)
    return _plan_feature_map(plan.id, db).get(feature_key)


def _plan_feature_int(user_id: int, feature_key: str, db: Session, default: int = 0) -> int:
    return _coerce_int(_plan_feature_value(user_id, feature_key, db), default=default)


def _plan_feature_bool(user_id: int, feature_key: str, db: Session, default: bool = False) -> bool:
    return _coerce_bool(_plan_feature_value(user_id, feature_key, db), default=default)


def _check_and_consume_quota(
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    *,
    deduct: bool,
) -> dict:
    if amount <= 0:
        amount = 1
    plan = _active_plan_for_user(user_id, db)
    limits = _plan_feature_map(plan.id, db)
    period_key = _current_period_key()
    base_limit = _coerce_int(limits.get(feature_key), default=0)
    granted = _extra_grant_amount(user_id, feature_key, period_key, db)
    limit = base_limit + granted
    usage = db.query(UserUsageMonthly).filter(
        UserUsageMonthly.user_id == user_id,
        UserUsageMonthly.feature_key == feature_key,
        UserUsageMonthly.period_key == period_key,
    ).first()
    used = _coerce_int(usage.used_amount if usage else 0, default=0)
    if limit <= 0:
        raise HTTPException(403, f"Feature not available in your current plan: {feature_key}")
    if used + amount > limit:
        raise HTTPException(429, f"Quota exceeded for {feature_key} ({used}/{limit})")
    if deduct:
        if usage:
            usage.used_amount = used + amount
        else:
            db.add(UserUsageMonthly(
                user_id=user_id,
                feature_key=feature_key,
                period_key=period_key,
                used_amount=amount,
            ))
        db.commit()
    return {"feature_key": feature_key, "used": used, "base_limit": base_limit, "granted": granted, "limit": limit, "period_key": period_key}


def _serialize_order(order: BillingOrder) -> dict:
    operator = None
    user_name = None
    plan_name = None
    db = getattr(_serialize_order, "_db", None)
    if db is not None:
        if order.operator_user_id:
            op = db.get(User, order.operator_user_id)
            if op:
                operator = {"id": op.id, "name": op.name, "email": op.email}
        user = db.get(User, order.user_id)
        if user:
            user_name = user.name
        plan = db.get(Plan, order.plan_id)
        if plan:
            plan_name = plan.name
    return {
        "order_no": order.order_no,
        "user_id": order.user_id,
        "user_name": user_name,
        "plan_id": order.plan_id,
        "plan_name": plan_name,
        "amount": _money_to_number(order.amount),
        "currency": order.currency,
        "status": order.status,
        "source": order.source or "system",
        "billing_cycle": order.billing_cycle or "monthly",
        "payment_provider": order.payment_provider or "mock",
        "payment_method": order.payment_method or "mock_qr",
        "operator": operator,
        "note": order.note or "",
        "extra": order.extra_json or {},
        "paid_at": order.paid_at,
        "expired_at": order.expired_at,
        "created_at": order.created_at,
    }


def _serialize_order_with_db(order: BillingOrder, db: Session) -> dict:
    setattr(_serialize_order, "_db", db)
    try:
        return _serialize_order(order)
    finally:
        setattr(_serialize_order, "_db", None)


def _write_audit_log(
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | int | None,
    summary: str,
    db: Session,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_name=actor.name if actor else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            summary=summary,
            detail_json=detail or {},
        )
    )


def _extra_grant_amount(user_id: int, feature_key: str, period_key: str, db: Session) -> int:
    grant = db.query(UserQuotaGrantMonthly).filter(
        UserQuotaGrantMonthly.user_id == user_id,
        UserQuotaGrantMonthly.feature_key == feature_key,
        UserQuotaGrantMonthly.period_key == period_key,
    ).first()
    return int(grant.granted_amount if grant else 0)


def _usage_entries_for_user(user_id: int, db: Session) -> list[dict]:
    plan = _active_plan_for_user(user_id, db)
    limits = _plan_feature_map(plan.id, db)
    period = _current_period_key()
    usage_items = db.query(UserUsageMonthly).filter(
        UserUsageMonthly.user_id == user_id,
        UserUsageMonthly.period_key == period,
    ).all()
    used_map = {item.feature_key: item.used_amount for item in usage_items}
    grant_items = db.query(UserQuotaGrantMonthly).filter(
        UserQuotaGrantMonthly.user_id == user_id,
        UserQuotaGrantMonthly.period_key == period,
    ).all()
    grant_map = {item.feature_key: item.granted_amount for item in grant_items}
    tracked = [
        "framework.generate.monthly_limit",
        "chapter.expand.monthly_limit",
        "scene.generate.monthly_limit",
        "manga.image.monthly_limit",
        "manga.regenerate.monthly_limit",
        "ai.text.advanced_calls.monthly_limit",
    ]
    entries = []
    for key in tracked:
        base_limit = int(limits.get(key, 0) or 0)
        granted = int(grant_map.get(key, 0) or 0)
        limit = base_limit + granted
        used = int(used_map.get(key, 0))
        entries.append({
            "feature_key": key,
            "base_limit": base_limit,
            "granted": granted,
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
        })
    return entries


def _check_and_consume_advanced_text_quota(request: Request, user_id: int, db: Session, *, deduct: bool) -> None:
    _check_and_consume_feature_quota(
        request,
        user_id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=deduct,
        provider_kind="text",
    )


def _upsert_user_subscription(user_id: int, plan_id: int, db: Session) -> UserSubscription:
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
    if sub:
        sub.plan_id = plan_id
        sub.status = "active"
        return sub
    sub = UserSubscription(user_id=user_id, plan_id=plan_id, status="active")
    db.add(sub)
    db.flush()
    return sub


def _mark_order_paid(order: BillingOrder, db: Session, *, operator_user_id: int | None = None, note: str = "") -> BillingOrder:
    if order.status != "paid":
        order.status = "paid"
        order.paid_at = datetime.datetime.utcnow()
    if operator_user_id is not None:
        order.operator_user_id = operator_user_id
    if note:
        order.note = note
    _upsert_user_subscription(order.user_id, order.plan_id, db)
    db.flush()
    return order


def _mark_order_cancelled(order: BillingOrder, db: Session, *, operator_user_id: int | None = None, note: str = "") -> BillingOrder:
    if order.status not in {"paid", "cancelled", "expired"}:
        order.status = "cancelled"
    if operator_user_id is not None:
        order.operator_user_id = operator_user_id
    if note:
        order.note = note
    db.flush()
    return order


def _mark_order_expired(order: BillingOrder, db: Session, *, note: str = "") -> BillingOrder:
    if order.status not in {"paid", "cancelled", "expired"}:
        order.status = "expired"
    if note:
        order.note = note
    db.flush()
    return order


def _sync_order_status(order: BillingOrder, db: Session) -> BillingOrder:
    if order.status == "pending" and order.expired_at and order.expired_at <= datetime.datetime.utcnow():
        _mark_order_expired(order, db, note=order.note or "Order expired before payment confirmation")
        db.commit()
        db.refresh(order)
    return order


def _order_checkout_payload(order: BillingOrder, plan: Plan, db: Session) -> dict:
    payment = _payment_settings_snapshot(db)
    expire_minutes = int(payment.get("order_expire_minutes") or 30)
    expires_at = order.expired_at or (datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes))
    method = order.payment_method or str(payment.get("default_method") or "mock_qr")
    provider = order.payment_provider or "mock"
    extra = order.extra_json or {}
    qr_code_text = f"LOREVISTA:{method}:{order.order_no}:{order.amount}"
    payment_url = f"/mock-pay/{order.order_no}" if method == "mock_qr" else ""
    can_mock_confirm = method == "mock_qr"
    if method == "alipay_qr":
        qr_code_text = str(extra.get("alipay_qr_code") or "")
        payment_url = str(extra.get("alipay_payment_url") or qr_code_text or "")
        can_mock_confirm = False
    return {
        "mode": str(payment.get("mode") or "mock"),
        "method": method,
        "provider": provider,
        "instructions": str(payment.get("instructions") or ""),
        "amount": _money_to_number(order.amount),
        "currency": order.currency,
        "plan_name": plan.name,
        "billing_cycle": order.billing_cycle or "monthly",
        "expires_at": expires_at,
        "qr_code_text": qr_code_text,
        "payment_url": payment_url,
        "can_mock_confirm": can_mock_confirm,
    }


def _alipay_config(payment: dict) -> dict:
    config = {
        "app_id": str(payment.get("alipay_app_id") or "").strip(),
        "seller_id": str(payment.get("alipay_pid") or "").strip(),
        "gateway": str(payment.get("alipay_gateway") or "https://openapi.alipay.com/gateway.do").strip(),
        "sign_type": str(payment.get("alipay_sign_type") or "RSA2").strip() or "RSA2",
        "app_private_key": str(payment.get("alipay_app_private_key") or "").strip(),
        "alipay_public_key": str(payment.get("alipay_public_key") or "").strip(),
        "notify_url": str(payment.get("alipay_notify_url") or "").strip(),
    }
    return config


def _validate_alipay_config(payment: dict) -> dict:
    config = _alipay_config(payment)
    required = {
        "app_id": "payment.alipay_app_id",
        "gateway": "payment.alipay_gateway",
        "app_private_key": "payment.alipay_app_private_key",
        "alipay_public_key": "payment.alipay_public_key",
        "notify_url": "payment.alipay_notify_url",
    }
    missing = [setting_key for field, setting_key in required.items() if not config.get(field)]
    if missing:
        raise HTTPException(400, f"Alipay configuration incomplete: {', '.join(missing)}")
    if config["sign_type"].upper() != "RSA2":
        raise HTTPException(400, "Only RSA2 is supported for Alipay face-to-face payment")
    return config


def _alipay_precreate(order: BillingOrder, plan: Plan, payment: dict) -> dict:
    config = _validate_alipay_config(payment)
    expire_minutes = max(1, int(payment.get("order_expire_minutes") or 30))
    timeout_express = f"{expire_minutes}m"
    expires_at = order.expired_at or (datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes))
    subject = f"{plan.name} {('年付' if (order.billing_cycle or 'monthly') == 'yearly' else '月付')}"
    body = plan.description or f"StoryCanvas subscription for {plan.name}"
    total_amount = f"{float(order.amount or 0):.2f}"
    result = alipay_f2f.precreate(
        gateway=config["gateway"],
        app_id=config["app_id"],
        private_key=config["app_private_key"],
        notify_url=config["notify_url"],
        out_trade_no=order.order_no,
        total_amount=total_amount,
        subject=subject[:256],
        seller_id=config["seller_id"] or None,
        timeout_express=timeout_express,
        body=body[:128],
        store_id="StoryCanvas",
    )
    qr_code = result["result"].get("qr_code") or ""
    payment_url = qr_code
    extra = dict(order.extra_json or {})
    extra.update({
        "payment_method": order.payment_method,
        "billing_cycle": order.billing_cycle,
        "alipay_qr_code": qr_code,
        "alipay_payment_url": payment_url,
        "alipay_precreate_response": result["result"],
    })
    order.extra_json = extra
    return {
        "mode": str(payment.get("mode") or "mock"),
        "provider": "alipay",
        "method": "alipay_qr",
        "instructions": str(payment.get("instructions") or ""),
        "amount": _money_to_number(order.amount),
        "currency": order.currency,
        "plan_name": plan.name,
        "billing_cycle": order.billing_cycle or "monthly",
        "expires_at": expires_at,
        "qr_code_text": qr_code,
        "payment_url": payment_url,
        "can_mock_confirm": False,
        "provider_response": result["result"],
    }


def _sync_alipay_order_status(order: BillingOrder, db: Session) -> BillingOrder:
    if order.payment_method != "alipay_qr" or order.status != "pending":
        return order

    payment = _payment_settings_snapshot(db)
    config = _validate_alipay_config(payment)
    try:
        result = alipay_f2f.trade_query(
            gateway=config["gateway"],
            app_id=config["app_id"],
            private_key=config["app_private_key"],
            out_trade_no=order.order_no,
            seller_id=config["seller_id"] or None,
        )
    except (alipay_f2f.AlipayApiError, alipay_f2f.AlipayConfigError, httpx.HTTPError):
        return order

    query_result = result.get("result", {})
    trade_status = str(query_result.get("trade_status") or "").strip()
    total_amount = str(query_result.get("total_amount") or "").strip()
    trade_no = str(query_result.get("trade_no") or "").strip()

    extra = dict(order.extra_json or {})
    extra.update({
        "alipay_trade_query_result": query_result,
        "alipay_trade_no": trade_no or str(extra.get("alipay_trade_no") or ""),
    })
    order.extra_json = extra

    if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        expected_amount = f"{float(order.amount or 0):.2f}"
        if total_amount and total_amount == expected_amount:
            _mark_order_paid(order, db, note=f"Alipay trade query confirmed trade {trade_no or order.order_no}")
    elif trade_status == "TRADE_CLOSED":
        _mark_order_cancelled(order, db, note=f"Alipay trade query closed trade {trade_no or order.order_no}")

    db.commit()
    db.refresh(order)
    return order


def _order_for_user(order_no: str, user_id: int, db: Session) -> BillingOrder:
    order = db.query(BillingOrder).filter(BillingOrder.order_no == order_no, BillingOrder.user_id == user_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    return _sync_order_status(order, db)


def _character_profile_text(body: dict) -> str:
    raw = body.get("characters", "")
    if not isinstance(raw, str):
        raise HTTPException(400, "characters must be a string")
    text = raw.strip()
    if len(text) > MAX_CHARACTER_PROFILE_CHARS:
        raise HTTPException(413, f"Character profile is too long. Max length is {MAX_CHARACTER_PROFILE_CHARS} characters")
    return text


def _parse_character_profile_cards(text: str) -> list[dict]:
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    blocks = [block.strip() for block in re.split(r"(?=^角色名[:：])", normalized, flags=re.MULTILINE) if block.strip()]
    cards: list[dict] = []
    for index, block in enumerate(blocks, start=1):
        name = f"角色 {index}"
        fields: list[dict[str, str]] = []
        for raw_line in block.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^([^:：]{1,20})[:：]\s*(.+)$", line)
            if match:
                label, value = match.groups()
                label = label.strip()
                value = value.strip()
                if not value:
                    continue
                if label == "角色名":
                    name = value
                fields.append({"label": label, "value": value})
            elif fields:
                fields[-1]["value"] = f"{fields[-1]['value']}\n{line}"
            else:
                fields.append({"label": "描述", "value": line})
        cards.append({"name": name, "raw": block, "fields": fields})
    return cards


def _build_framework_context(story: Story | None, chapter: Chapter | None = None) -> str:
    """Assemble framework constraints from story tags, characters, outline and chapter metadata."""
    if not story:
        return ""
    parts = []
    if story.tags:
        parts.append(f"故事标签: {json.dumps(story.tags, ensure_ascii=False)}")
    if story.characters:
        parts.append(f"角色设定: {json.dumps(story.characters, ensure_ascii=False)}")
    if story.outline:
        parts.append(f"故事大纲: {json.dumps(story.outline, ensure_ascii=False)}")
    if chapter:
        if chapter.act:
            parts.append(f"当前章节所属幕: {chapter.act}")
        if chapter.key_events:
            parts.append(f"本章关键事件: {json.dumps(chapter.key_events, ensure_ascii=False)}")
    return "\n".join(parts)


def _count_words(text: str | None) -> int | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    return len("".join(stripped.split()))


def _normalize_key_events(raw) -> list[str] | None:
    if not raw:
        return None
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return items or None
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else None
    return [str(raw).strip()] if str(raw).strip() else None


def _normalize_framework_outline(outline: dict | None, chapters: list | None) -> dict:
    normalized = dict(outline or {})
    acts = normalized.get("three_acts")
    if not isinstance(acts, list):
        acts = []

    chapter_groups: dict[str, list[dict]] = {}
    if isinstance(chapters, list):
        for item in chapters:
            if not isinstance(item, dict):
                continue
            act_key = str(item.get("act") or "").strip()
            chapter_number = item.get("chapter_number")
            title = str(item.get("title") or "").strip()
            if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                continue
            chapter_entry = {
                "chapter_number": chapter_number,
                "title": title,
            }
            key_events = _normalize_key_events(item.get("key_events"))
            if key_events:
                chapter_entry["key_events"] = key_events
            summary = item.get("summary")
            if isinstance(summary, str) and summary.strip():
                chapter_entry["summary"] = summary.strip()
            chapter_groups.setdefault(act_key, []).append(chapter_entry)

    next_unassigned: list[dict] = chapter_groups.pop("", [])
    merged_acts: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if isinstance(act, dict):
            act_entry = dict(act)
        else:
            act_entry = {"title": str(act)}
        act_label = act_entry.get("act", index)
        act_entry["act"] = act_label
        candidates = chapter_groups.pop(str(act_label), None) or chapter_groups.pop(str(index), None)
        if not candidates and next_unassigned:
            candidates = next_unassigned
            next_unassigned = []
        act_entry["chapters"] = sorted(candidates or [], key=lambda item: item["chapter_number"])
        merged_acts.append(act_entry)

    leftover = []
    for items in chapter_groups.values():
        leftover.extend(items)
    leftover.extend(next_unassigned)
    if leftover:
        merged_acts.append({
            "act": len(merged_acts) + 1,
            "title": "章节规划",
            "summary": "",
            "chapters": sorted(leftover, key=lambda item: item["chapter_number"]),
        })

    normalized["three_acts"] = merged_acts
    return normalized


def _extract_outline_chapters(outline: dict | None) -> list[dict]:
    if not isinstance(outline, dict):
        return []
    acts = outline.get("three_acts")
    if not isinstance(acts, list):
        return []
    extracted: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if not isinstance(act, dict):
            continue
        act_label = act.get("act", index)
        chapters = act.get("chapters")
        if not isinstance(chapters, list):
            continue
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter_number = item.get("chapter_number")
            title = str(item.get("title") or "").strip()
            if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                continue
            chapter_entry = dict(item)
            chapter_entry["chapter_number"] = chapter_number
            chapter_entry["title"] = title
            chapter_entry["act"] = item.get("act", act_label)
            extracted.append(chapter_entry)
    return extracted


def _merge_chapter_plans(existing: list[dict] | None, incoming: list[dict] | None) -> list[dict]:
    merged: dict[int, dict] = {}

    def _ingest(items: list[dict] | None, *, prefer_existing: bool) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            chapter_number = item.get("chapter_number")
            title = str(item.get("title") or "").strip()
            if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                continue
            normalized = dict(item)
            normalized["chapter_number"] = chapter_number
            normalized["title"] = title
            if prefer_existing and chapter_number in merged:
                current = dict(merged[chapter_number])
                current.update({k: v for k, v in normalized.items() if v not in (None, "", [], {})})
                merged[chapter_number] = current
            else:
                current = dict(merged.get(chapter_number, {}))
                current.update(normalized)
                merged[chapter_number] = current

    _ingest(existing, prefer_existing=False)
    _ingest(incoming, prefer_existing=True)
    return [merged[key] for key in sorted(merged)]


def _merge_framework_outline(existing_outline: dict | None, incoming_outline: dict | None, incoming_chapters: list | None) -> dict:
    existing_outline = existing_outline if isinstance(existing_outline, dict) else {}
    incoming_outline = incoming_outline if isinstance(incoming_outline, dict) else {}

    existing_chapters = _extract_outline_chapters(existing_outline)
    incoming_outline_chapters = _extract_outline_chapters(incoming_outline)
    combined_incoming = _merge_chapter_plans(incoming_outline_chapters, incoming_chapters)
    merged_chapters = _merge_chapter_plans(existing_chapters, combined_incoming)

    existing_acts = existing_outline.get("three_acts") if isinstance(existing_outline.get("three_acts"), list) else []
    incoming_acts = incoming_outline.get("three_acts") if isinstance(incoming_outline.get("three_acts"), list) else []

    merged_acts: list[dict] = []
    act_index: dict[str, int] = {}

    def _push_act(raw_act, fallback_index: int, *, prefer_incoming: bool) -> None:
        if isinstance(raw_act, dict):
            act_entry = dict(raw_act)
        else:
            act_entry = {"title": str(raw_act)}
        act_label = str(act_entry.get("act", fallback_index))
        act_entry["act"] = act_entry.get("act", fallback_index)
        act_entry.pop("chapters", None)
        if act_label in act_index:
            idx = act_index[act_label]
            current = dict(merged_acts[idx])
            update_data = {k: v for k, v in act_entry.items() if v not in (None, "", [], {})}
            if prefer_incoming:
                current.update(update_data)
            else:
                for key, value in update_data.items():
                    current.setdefault(key, value)
            merged_acts[idx] = current
            return
        act_index[act_label] = len(merged_acts)
        merged_acts.append(act_entry)

    for idx, act in enumerate(existing_acts, start=1):
        _push_act(act, idx, prefer_incoming=False)
    for idx, act in enumerate(incoming_acts, start=1):
        _push_act(act, idx, prefer_incoming=True)

    base_outline = dict(existing_outline)
    base_outline.update({k: v for k, v in incoming_outline.items() if k != "three_acts"})
    base_outline["three_acts"] = merged_acts
    return _normalize_framework_outline(base_outline, merged_chapters)


def _has_complete_tags(tags: dict | None) -> bool:
    if not isinstance(tags, dict):
        return False
    return all(str(tags.get(key) or "").strip() for key in ("type", "theme", "style", "audience"))


def _has_complete_big_five(scores) -> bool:
    if not isinstance(scores, dict):
        return False
    alias_map = {
        "openness": ("openness", "O"),
        "conscientiousness": ("conscientiousness", "C"),
        "extraversion": ("extraversion", "E"),
        "agreeableness": ("agreeableness", "A"),
        "neuroticism": ("neuroticism", "N"),
    }
    for aliases in alias_map.values():
        value = None
        for key in aliases:
            if scores.get(key) not in (None, ""):
                value = scores.get(key)
                break
        if value in (None, ""):
            return False
    return True


def _has_complete_characters(characters) -> bool:
    if not isinstance(characters, list) or len(characters) == 0:
        return False
    for item in characters:
        if not isinstance(item, dict):
            return False
        if not str(item.get("name") or "").strip():
            return False
        if not str(item.get("role") or "").strip():
            return False
        if not _has_complete_big_five(item.get("big_five")):
            return False
    return True


def _has_complete_outline(outline: dict | None) -> bool:
    if not isinstance(outline, dict):
        return False
    acts = outline.get("three_acts")
    if not isinstance(acts, list) or len(acts) < 3:
        return False
    if not _extract_outline_chapters(outline):
        return False
    for act in acts:
        if not isinstance(act, dict):
            return False
        if not str(act.get("title") or "").strip():
            return False
        if not str(act.get("summary") or "").strip():
            return False
        chapters = act.get("chapters")
        if not isinstance(chapters, list) or len(chapters) == 0:
            return False
    return True


async def _complete_framework_payload(framework: dict | None, description: str, api_key: str | None = None) -> dict:
    payload = dict(framework or {})
    payload["tags"] = payload.get("tags") if isinstance(payload.get("tags"), dict) else {}
    payload["characters"] = _normalize_characters_payload(payload.get("characters") if isinstance(payload.get("characters"), list) else [])
    payload["outline"] = _merge_framework_outline({}, payload.get("outline"), payload.get("chapters"))
    payload["chapters"] = _extract_outline_chapters(payload["outline"])

    story_context = {
        "description": description,
        "tags": payload["tags"],
        "characters": payload["characters"],
        "outline": payload["outline"],
    }

    if not _has_complete_tags(payload["tags"]):
        try:
            payload["tags"] = _merge_tags(payload["tags"], await regenerate_tags(story_context, api_key=api_key))
            story_context["tags"] = payload["tags"]
        except Exception as exc:
            logger.warning("Failed to backfill framework tags: %s", exc)

    if not _has_complete_characters(payload["characters"]):
        try:
            payload["characters"] = _merge_characters_payload(
                payload["characters"],
                await regenerate_characters(story_context, api_key=api_key),
            )
            story_context["characters"] = payload["characters"]
        except Exception as exc:
            logger.warning("Failed to backfill framework characters: %s", exc)

    if not _has_complete_outline(payload["outline"]):
        try:
            incoming_outline = await regenerate_outline(story_context, api_key=api_key)
            payload["outline"] = _merge_framework_outline(
                payload["outline"],
                incoming_outline,
                _extract_outline_chapters(incoming_outline),
            )
            story_context["outline"] = payload["outline"]
        except Exception as exc:
            logger.warning("Failed to backfill framework outline: %s", exc)

    payload["chapters"] = _extract_outline_chapters(payload["outline"])
    return payload


def _sort_story_chapters_for_shift(story: Story, start_number: int, delta: int) -> list[Chapter]:
    if delta == 0:
        return []
    candidates = [chapter for chapter in story.chapters if chapter.chapter_number >= start_number]
    return sorted(candidates, key=lambda chapter: chapter.chapter_number, reverse=delta > 0)


def _shift_story_chapter_numbers(story: Story, start_number: int, delta: int) -> None:
    for chapter in _sort_story_chapters_for_shift(story, start_number, delta):
        chapter.chapter_number += delta


def _normalize_outline_plan_payload(raw: dict | None, *, fallback_title: str, fallback_act: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    title = str(raw.get("title") or "").strip() or fallback_title
    summary = str(raw.get("summary") or "").strip()
    key_events = _normalize_key_events(raw.get("key_events"))
    act = str(raw.get("act") or fallback_act or "").strip() or fallback_act

    payload = {
        "title": title,
        "act": act,
    }
    if summary:
        payload["summary"] = summary
    if key_events:
        payload["key_events"] = key_events
    return payload


def _infer_manual_plan_act(chapters: list[dict], *, after_chapter_number: int | None = None, target_chapter_number: int | None = None) -> str:
    if isinstance(target_chapter_number, int):
        for item in chapters:
            if item.get("chapter_number") == target_chapter_number:
                return str(item.get("act") or "").strip() or "1"

    if isinstance(after_chapter_number, int):
        for item in chapters:
            if item.get("chapter_number") == after_chapter_number:
                return str(item.get("act") or "").strip() or "1"
        for item in chapters:
            if item.get("chapter_number") == after_chapter_number + 1:
                return str(item.get("act") or "").strip() or "1"

    if chapters:
        return str(chapters[-1].get("act") or "").strip() or "1"
    return "1"


def _apply_chapter_content(chapter: Chapter, content: str, *, status: str | None = None) -> None:
    chapter.novel_content = content
    chapter.word_count = _count_words(content)
    if status:
        chapter.status = status


def _normalize_big_five_scores(raw):
    if not isinstance(raw, dict):
        return raw
    key_map = {
        "O": "O",
        "C": "C",
        "E": "E",
        "A": "A",
        "N": "N",
        "openness": "O",
        "conscientiousness": "C",
        "extraversion": "E",
        "agreeableness": "A",
        "neuroticism": "N",
    }
    normalized = {}
    for key, value in raw.items():
        target = key_map.get(str(key))
        if not target:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric <= 10:
            numeric *= 10
        normalized[target] = max(0, min(100, int(round(numeric))))
    return normalized or raw


def _normalize_characters_payload(raw):
    if not isinstance(raw, list):
        return raw
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        character = dict(item)
        if "big_five" in character:
            character["big_five"] = _normalize_big_five_scores(character.get("big_five"))
        normalized.append(character)
    return normalized


def _merge_tags(existing, incoming):
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged or existing or incoming


def _merge_characters_payload(existing, incoming):
    existing_list = _normalize_characters_payload(existing if isinstance(existing, list) else [])
    incoming_list = _normalize_characters_payload(incoming if isinstance(incoming, list) else [])
    merged: list[dict] = []
    index_by_name: dict[str, int] = {}

    for item in existing_list:
        if isinstance(item, dict):
            record = dict(item)
            merged.append(record)
            name = str(record.get("name") or "").strip().lower()
            if name:
                index_by_name[name] = len(merged) - 1
        else:
            merged.append(item)

    for item in incoming_list:
        if not isinstance(item, dict):
            merged.append(item)
            continue
        record = dict(item)
        name = str(record.get("name") or "").strip().lower()
        if name and name in index_by_name:
            idx = index_by_name[name]
            current = dict(merged[idx]) if isinstance(merged[idx], dict) else {}
            current.update({k: v for k, v in record.items() if v not in (None, "", [], {})})
            merged[idx] = current
        else:
            merged.append(record)
            if name:
                index_by_name[name] = len(merged) - 1

    return merged


def _story_framework_context(story: Story) -> dict:
    return {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }


def _unlink_file(path: Path, label: str) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete %s %s: %s", label, path, exc)
        raise HTTPException(409, f"{label} file is currently in use. Try again later")


def _rmtree_best_effort(path: Path, label: str) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.warning("Failed to delete %s %s: %s", label, path, exc)


def _write_bytes_or_conflict(path: Path, data: bytes, label: str) -> None:
    try:
        path.write_bytes(data)
    except OSError as exc:
        logger.warning("Failed to write %s %s: %s", label, path, exc)
        raise HTTPException(409, f"{label} file is currently in use. Try again later")


def _chapter_dir(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"


def _initialize_empty_chapter_workspace(chapter_id: int) -> None:
    chapter_dir = _chapter_dir(chapter_id)
    _rmtree_best_effort(chapter_dir, "stale chapter workspace")


def _scene_meta_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "scenes_meta.json"


def _write_scenes_file(chapter_id: int, scenes: list[str], sanitized_indices: list[int] | None = None) -> None:
    prompts_dir = _chapter_dir(chapter_id)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompts_file = prompts_dir / "scenes.txt"
    with open(prompts_file, "w", encoding="utf-8") as f:
        for idx, scene in enumerate(scenes, start=1):
            f.write(f"=== 第{idx}格 ===\n{scene.strip()}\n\n")
    meta_path = _scene_meta_path(chapter_id)
    payload = {"sanitized_indices": sorted(set(sanitized_indices or []))}
    meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _parse_scenes_text(raw: str) -> list[str]:
    import re

    parts = [p.strip() for p in re.split(r"(?m)^=== .*? ===\n", raw) if p.strip()]
    return parts


def _load_scene_meta(chapter_id: int) -> dict:
    meta_path = _scene_meta_path(chapter_id)
    if not meta_path.exists():
        return {"sanitized_indices": []}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"sanitized_indices": []}


def _clear_chapter_manga_state(chapter: Chapter, db: Session) -> None:
    chapter_dir = _chapter_dir(chapter.id)
    if chapter_dir.exists():
        for filename in ("scenes.txt",):
            path = chapter_dir / filename
            if path.exists():
                _unlink_file(path, filename)
        for img in list(chapter.images):
            img_path = Path(__file__).resolve().parent / img.image_path
            if img_path.exists():
                _unlink_file(img_path, "manga image")
            db.delete(img)


def _clear_chapter_images_only(chapter: Chapter, db: Session) -> None:
    for img in list(chapter.images):
        img_path = Path(__file__).resolve().parent / img.image_path
        if img_path.exists():
            _unlink_file(img_path, "manga image")
        db.delete(img)


def _decode_png_upload(b64: str) -> bytes:
    if not b64:
        raise HTTPException(400, "No image provided")
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        import base64
        import binascii
        import io

        from PIL import Image, UnidentifiedImageError

        img_bytes = base64.b64decode(b64, validate=True)
        if len(img_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Image is too large. Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        with Image.open(io.BytesIO(img_bytes)) as img:
            img.verify()
        with Image.open(io.BytesIO(img_bytes)) as img:
            output = io.BytesIO()
            img.convert("RGBA").save(output, format="PNG", optimize=True)
            png_bytes = output.getvalue()
        if len(png_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Image is too large after processing. Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        return png_bytes
    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Invalid base64 image data")
    except UnidentifiedImageError:
        raise HTTPException(400, "Uploaded file is not a valid image")


def _decode_edit_mask_upload(b64: str, target_size: tuple[int, int]) -> bytes:
    if not b64:
        raise HTTPException(400, "No mask provided")
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        import base64
        import binascii
        import io

        from PIL import Image, UnidentifiedImageError

        mask_bytes = base64.b64decode(b64, validate=True)
        with Image.open(io.BytesIO(mask_bytes)) as img:
            rgba = img.convert("RGBA")
            if rgba.size != target_size:
                rgba = rgba.resize(target_size, Image.NEAREST)
            alpha = rgba.getchannel("A")
            opaque_bg = Image.new("RGBA", target_size, (255, 255, 255, 255))
            pixels = opaque_bg.load()
            alpha_pixels = alpha.load()
            for y in range(target_size[1]):
                for x in range(target_size[0]):
                    if alpha_pixels[x, y] > 10:
                        pixels[x, y] = (255, 255, 255, 0)
            output = io.BytesIO()
            opaque_bg.save(output, format="PNG", optimize=True)
            normalized = output.getvalue()
        if len(normalized) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Mask is too large after processing. Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        return normalized
    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Invalid base64 mask data")
    except UnidentifiedImageError:
        raise HTTPException(400, "Uploaded mask is not a valid image")


@app.on_event("startup")
def on_startup():
    init_db()
    # One-time: rename default stories
    from database import SessionLocal
    db = SessionLocal()
    try:
        for s in db.query(Story).filter(Story.title.in_(["我的第一个故事", "未命名故事"])).all():
            if s.chapters and any(ch.messages for ch in s.chapters):
                s.title = "转生成为暗恋公主的女仆故事"
                s.description = "百合女仆与公主的奇幻冒险"
            # else: leave as-is for empty stories
        db.commit()
    finally:
        db.close()


# ─── Story CRUD ─────────────────────────────────────────────

@app.post("/api/auth/register")
def register(body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    email = _normalize_email(body.get("email"))
    password = str(body.get("password") or "").strip()
    verification_code = str(body.get("verification_code") or "").strip()
    name = str(body.get("name") or "").strip() or "User"
    _validate_email_format(email)
    if not email or not password:
        raise HTTPException(400, "请输入邮箱和密码")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "该邮箱已注册")
    if bool(_auth_settings_snapshot(db).get("require_email_code_for_register")):
        _consume_email_verification_code(email, "register", verification_code, db)

    user = User(email=email, password_hash=_password_hash(password), name=name, role="user", status="active", email_verified=True)
    db.add(user)
    db.flush()
    free_plan = db.query(Plan).filter(Plan.code == "free").first()
    if free_plan:
        db.add(UserSubscription(user_id=user.id, plan_id=free_plan.id, status="active"))
    token = _new_session_token()
    db.add(UserSession(user_id=user.id, token=token))
    db.commit()
    return {"token": token, "user": _serialize_auth_user(user, db)}


@app.post("/api/auth/login")
def login(body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    email = _normalize_email(body.get("email"))
    password = str(body.get("password") or "").strip()
    verification_code = str(body.get("verification_code") or "").strip()
    user = db.query(User).filter(User.email == email).first()
    if not user or user.password_hash != _password_hash(password):
        raise HTTPException(401, "邮箱或密码错误")
    if user.status != "active":
        raise HTTPException(403, "账号已被停用")
    if bool(_auth_settings_snapshot(db).get("require_email_code_for_login")):
        _consume_email_verification_code(email, "login", verification_code, db)
    token = _new_session_token()
    db.add(UserSession(user_id=user.id, token=token))
    db.commit()
    return {"token": token, "user": _serialize_auth_user(user, db)}


@app.post("/api/auth/send-email-code")
def send_email_code(body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    email = _normalize_email(body.get("email"))
    purpose = str(body.get("purpose") or "").strip().lower()
    _validate_email_format(email)
    if purpose not in {"register", "login"}:
        raise HTTPException(400, "验证码用途不正确")
    if purpose == "register":
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(409, "该邮箱已注册")
    else:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(404, "该邮箱尚未注册")
        if user.status != "active":
            raise HTTPException(403, "账号已被停用")
    return _issue_email_verification_code(email, purpose, db)


@app.get("/api/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    return _serialize_auth_user(user, db)


@app.post("/api/auth/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = _parse_auth_token(request)
    if token:
        sess = db.query(UserSession).filter(UserSession.token == token, UserSession.revoked_at.is_(None)).first()
        if sess:
            sess.revoked_at = datetime.datetime.utcnow()
            db.commit()
    return {"ok": True}


@app.get("/api/plans/public")
def plans_public(db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    plans = db.query(Plan).filter(Plan.is_visible.is_(True)).order_by(Plan.monthly_price.asc()).all()
    result = []
    for plan in plans:
        result.append({
            "id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "description": plan.description,
            "monthly_price": _money_to_number(plan.monthly_price),
            "yearly_price": _money_to_number(plan.yearly_price) if plan.yearly_price is not None else None,
            "currency": plan.currency,
            "is_recommended": plan.is_recommended,
            "features": _plan_feature_map(plan.id, db),
        })
    return result


@app.get("/api/me/entitlements")
def my_entitlements(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    plan = _active_plan_for_user(user.id, db)
    return {
        "plan": {"id": plan.id, "code": plan.code, "name": plan.name},
        "entitlements": _plan_feature_map(plan.id, db),
    }


@app.get("/api/me/subscription")
def my_subscription(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    plan = _active_plan_for_user(user.id, db)
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user.id).first()
    latest_order = (
        db.query(BillingOrder)
        .filter(BillingOrder.user_id == user.id)
        .order_by(BillingOrder.created_at.desc())
        .first()
    )
    if latest_order:
        latest_order = _sync_order_status(latest_order, db)
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
        "subscription": {
            "status": sub.status if sub else "active",
            "plan": {
                "id": plan.id,
                "code": plan.code,
                "name": plan.name,
                "monthly_price": _money_to_number(plan.monthly_price),
                "yearly_price": _money_to_number(plan.yearly_price) if plan.yearly_price is not None else None,
                "currency": plan.currency,
            },
        },
        "latest_order": _serialize_order_with_db(latest_order, db) if latest_order else None,
    }


@app.get("/api/me/orders")
def my_orders(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    orders = (
        db.query(BillingOrder)
        .filter(BillingOrder.user_id == user.id)
        .order_by(BillingOrder.created_at.desc())
        .limit(20)
        .all()
    )
    for order in orders:
        _sync_order_status(order, db)
    return [_serialize_order_with_db(order, db) for order in orders]


@app.post("/api/me/orders/{order_no}/sync")
def my_order_sync(order_no: str, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    order = _order_for_user(order_no, user.id, db)
    if order.payment_method == "alipay_qr" and order.status == "pending":
        order = _sync_alipay_order_status(order, db)
    plan = db.get(Plan, order.plan_id)
    current_plan = _active_plan_for_user(user.id, db)
    return {
        "ok": True,
        "status": order.status,
        "order": _serialize_order_with_db(order, db),
        "subscription": {
            "status": "active",
            "plan": {
                "id": current_plan.id,
                "code": current_plan.code,
                "name": current_plan.name,
                "monthly_price": _money_to_number(current_plan.monthly_price),
                "yearly_price": _money_to_number(current_plan.yearly_price) if current_plan.yearly_price is not None else None,
                "currency": current_plan.currency,
            },
        },
        "checkout": _order_checkout_payload(order, plan, db) if plan else None,
    }


@app.post("/api/billing/subscribe")
def subscribe_plan(body: dict, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    payment = _payment_settings_snapshot(db)
    if not bool(payment.get("enabled")):
        raise HTTPException(400, "Payment is currently disabled")
    plan_id = int(body.get("plan_id") or 0)
    billing_cycle = str(body.get("billing_cycle") or "monthly").strip().lower()
    payment_method = str(body.get("payment_method") or payment.get("default_method") or "mock_qr").strip()
    if billing_cycle not in {"monthly", "yearly"}:
        raise HTTPException(400, "billing_cycle must be monthly or yearly")
    plan = db.get(Plan, plan_id)
    if not plan or not plan.is_visible:
        raise HTTPException(404, "Plan not found")
    method_options = _payment_method_options(db)
    selected_method = next((item for item in method_options if item["key"] == payment_method), None)
    if not selected_method:
        raise HTTPException(400, "Payment method unavailable")

    amount = plan.yearly_price if billing_cycle == "yearly" and plan.yearly_price is not None else plan.monthly_price
    expire_minutes = int(payment.get("order_expire_minutes") or 30)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes)
    stale_orders = (
        db.query(BillingOrder)
        .filter(BillingOrder.user_id == user.id, BillingOrder.status == "pending")
        .all()
    )
    for stale_order in stale_orders:
        _mark_order_cancelled(stale_order, db, operator_user_id=user.id, note="Superseded by a newer checkout request")
    order = BillingOrder(
        order_no=f"LV{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.randbelow(10000):04d}",
        user_id=user.id,
        plan_id=plan.id,
        amount=_coerce_money(amount),
        currency=plan.currency,
        status="pending",
        source="user_purchase",
        billing_cycle=billing_cycle,
        payment_provider=str(selected_method["provider"]),
        payment_method=str(selected_method["key"]),
        operator_user_id=user.id,
        note=f"Checkout created for {plan.name}",
        extra_json={"billing_cycle": billing_cycle, "payment_method": payment_method},
        expired_at=expires_at,
    )
    db.add(order)
    checkout_override = None
    if _coerce_money(amount) <= Decimal("0.00") and bool(payment.get("auto_activate_free_plan", True)):
        _mark_order_paid(order, db, operator_user_id=user.id, note=f"Auto-activated free plan {plan.name}")
    elif payment_method == "alipay_qr":
        try:
            checkout_override = _alipay_precreate(order, plan, payment)
        except alipay_f2f.AlipayApiError as exc:
            raise HTTPException(502, f"Alipay precreate failed: {exc}") from exc
        except alipay_f2f.AlipayConfigError as exc:
            raise HTTPException(400, f"Alipay config invalid: {exc}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Alipay gateway request failed: {exc}") from exc
    _write_audit_log(user, "subscribe_plan", "billing_order", order.order_no, f"Created checkout for {plan.name}", db, {
        "plan_id": plan.id,
        "plan_name": plan.name,
        "billing_cycle": billing_cycle,
        "amount": _money_to_number(amount),
        "payment_method": payment_method,
    })
    db.commit()
    db.refresh(order)
    current_plan = _active_plan_for_user(user.id, db)
    return {
        "ok": True,
        "message": "subscription updated" if order.status == "paid" else "checkout created",
        "status": order.status,
        "subscription": {
            "status": "active",
            "plan": {
                "id": current_plan.id,
                "code": current_plan.code,
                "name": current_plan.name,
                "monthly_price": _money_to_number(current_plan.monthly_price),
                "yearly_price": _money_to_number(current_plan.yearly_price) if current_plan.yearly_price is not None else None,
                "currency": current_plan.currency,
            },
        },
        "order": _serialize_order_with_db(order, db),
        "checkout": checkout_override or _order_checkout_payload(order, plan, db),
    }


@app.post("/api/me/orders/{order_no}/mock-confirm")
def my_order_mock_confirm(order_no: str, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    order = _order_for_user(order_no, user.id, db)
    if order.status != "pending":
        raise HTTPException(400, f"Order cannot be confirmed from status {order.status}")
    if order.payment_method != "mock_qr":
        raise HTTPException(400, "Only mock payment orders can be manually confirmed here")
    plan = db.get(Plan, order.plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    _mark_order_paid(order, db, operator_user_id=user.id, note=f"Mock payment confirmed by {user.name}")
    _write_audit_log(user, "confirm_mock_payment", "billing_order", order.order_no, f"Confirmed mock payment for {plan.name}", db, {
        "order_no": order.order_no,
        "plan_id": order.plan_id,
    })
    db.commit()
    db.refresh(order)
    return {
        "ok": True,
        "status": order.status,
        "order": _serialize_order_with_db(order, db),
        "subscription": {
            "status": "active",
            "plan": {
                "id": plan.id,
                "code": plan.code,
                "name": plan.name,
                "monthly_price": _money_to_number(plan.monthly_price),
                "yearly_price": _money_to_number(plan.yearly_price) if plan.yearly_price is not None else None,
                "currency": plan.currency,
            },
        },
    }


@app.post("/api/me/orders/{order_no}/cancel")
def my_order_cancel(order_no: str, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    order = _order_for_user(order_no, user.id, db)
    if order.status != "pending":
        raise HTTPException(400, f"Order cannot be cancelled from status {order.status}")
    plan = db.get(Plan, order.plan_id)
    _mark_order_cancelled(order, db, operator_user_id=user.id, note=f"Cancelled by {user.name}")
    _write_audit_log(user, "cancel_order", "billing_order", order.order_no, "User cancelled checkout", db, {
        "order_no": order.order_no,
        "plan_id": order.plan_id,
        "plan_name": plan.name if plan else "",
    })
    db.commit()
    db.refresh(order)
    return {"ok": True, "status": order.status, "order": _serialize_order_with_db(order, db)}


@app.post("/api/payments/alipay/notify")
@app.post("/alipay/notify")
async def alipay_notify(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    payload = {key: value for key, value in parse_qsl(raw_body, keep_blank_values=True)}
    signature = payload.get("sign", "")
    if not signature:
        return Response("failure", media_type="text/plain", status_code=400)
    params = {key: value for key, value in payload.items() if key not in {"sign", "sign_type"}}
    sign_content = "&".join(
        f"{key}={params[key]}"
        for key in sorted(params.keys())
        if params[key] is not None and params[key] != ""
    )
    payment = _payment_settings_snapshot(db)
    config = _validate_alipay_config(payment)
    try:
        alipay_f2f.rsa2_verify(sign_content, signature, config["alipay_public_key"])
    except Exception:
        return Response("failure", media_type="text/plain", status_code=400)

    order_no = payload.get("out_trade_no", "").strip()
    trade_status = payload.get("trade_status", "").strip()
    trade_no = payload.get("trade_no", "").strip()
    total_amount = payload.get("total_amount", "").strip()
    order = db.query(BillingOrder).filter(BillingOrder.order_no == order_no).first()
    if not order:
        return Response("failure", media_type="text/plain", status_code=404)
    plan = db.get(Plan, order.plan_id)
    extra = dict(order.extra_json or {})
    extra.update({
        "alipay_trade_no": trade_no,
        "alipay_notify_payload": payload,
    })
    order.extra_json = extra
    if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        expected_amount = f"{float(order.amount or 0):.2f}"
        if total_amount and total_amount != expected_amount:
            return Response("failure", media_type="text/plain", status_code=400)
        _mark_order_paid(order, db, note=f"Alipay notify confirmed trade {trade_no}")
        _write_audit_log(None, "alipay_notify_paid", "billing_order", order.order_no, f"Alipay async notify marked order paid", db, {
            "order_no": order.order_no,
            "trade_no": trade_no,
            "plan_name": plan.name if plan else "",
        })
    elif trade_status in {"TRADE_CLOSED"}:
        _mark_order_cancelled(order, db, note=f"Alipay notify closed trade {trade_no}")
    db.commit()
    return Response("success", media_type="text/plain")


@app.get("/api/me/usage")
def my_usage(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    plan = _active_plan_for_user(user.id, db)
    return {"period_key": _current_period_key(), "plan_code": plan.code, "items": _usage_entries_for_user(user.id, db)}


@app.get("/api/admin/plans")
def admin_plans(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    _require_admin(request, db)
    plans = db.query(Plan).order_by(Plan.monthly_price.asc()).all()
    return [{
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description or "",
        "monthly_price": _money_to_number(plan.monthly_price),
        "yearly_price": _money_to_number(plan.yearly_price) if plan.yearly_price is not None else None,
        "currency": plan.currency,
        "is_visible": plan.is_visible,
        "is_recommended": plan.is_recommended,
    } for plan in plans]


@app.get("/api/admin/feature-catalog")
def admin_feature_catalog(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return FEATURE_CATALOG


@app.post("/api/admin/plans")
def admin_create_plan(body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    code = str(body.get("code") or "").strip().lower()
    name = str(body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code and name are required")
    if db.query(Plan).filter(Plan.code == code).first():
        raise HTTPException(409, "Plan code already exists")
    plan = Plan(
        code=code,
        name=name,
        description=str(body.get("description") or ""),
        monthly_price=_parse_money_input(body.get("monthly_price"), "monthly_price"),
        yearly_price=_parse_money_input(body.get("yearly_price"), "yearly_price"),
        currency=str(body.get("currency") or "CNY"),
        is_visible=bool(body.get("is_visible", True)),
        is_recommended=bool(body.get("is_recommended", False)),
    )
    db.add(plan)
    db.flush()
    for feature in FEATURE_CATALOG:
        db.add(PlanFeature(plan_id=plan.id, feature_key=feature["key"], value_json={"value": 0}))
        rule = feature.get("default_rule") or {}
        db.add(
            PlanQuotaRule(
                plan_id=plan.id,
                feature_key=feature["key"],
                reset_period=str(rule.get("reset_period") or "monthly"),
                deduct_mode=str(rule.get("deduct_mode") or "on_success"),
                extra_config={},
            )
        )
    db.commit()
    return {"ok": True, "plan_id": plan.id}


@app.delete("/api/admin/plans/{plan_id}")
def admin_delete_plan(plan_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    subscription_count = db.query(UserSubscription).filter(UserSubscription.plan_id == plan.id).count()
    if subscription_count > 0:
        raise HTTPException(409, f"Plan has {subscription_count} active subscription(s) and cannot be deleted")
    order_count = db.query(BillingOrder).filter(BillingOrder.plan_id == plan.id).count()
    if order_count > 0:
        raise HTTPException(409, f"Plan has {order_count} historical order(s) and cannot be deleted")
    db.delete(plan)
    db.commit()
    return {"ok": True}


@app.put("/api/admin/plans/{plan_id}")
def admin_update_plan(plan_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    plan.name = str(body.get("name") or plan.name)
    plan.description = str(body.get("description") or plan.description or "")
    if body.get("monthly_price") is not None:
        plan.monthly_price = _parse_money_input(body.get("monthly_price"), "monthly_price")
    if body.get("yearly_price") is not None:
        plan.yearly_price = _parse_money_input(body.get("yearly_price"), "yearly_price")
    if body.get("is_visible") is not None:
        plan.is_visible = bool(body.get("is_visible"))
    if body.get("is_recommended") is not None:
        plan.is_recommended = bool(body.get("is_recommended"))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/plans/{plan_id}/features")
def admin_plan_features(plan_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    if not db.get(Plan, plan_id):
        raise HTTPException(404, "Plan not found")
    return [{
        "feature_key": f.feature_key,
        "value": (f.value_json or {}).get("value"),
    } for f in db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).order_by(PlanFeature.feature_key.asc()).all()]


@app.put("/api/admin/plans/{plan_id}/features")
def admin_save_plan_features(plan_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    if not db.get(Plan, plan_id):
        raise HTTPException(404, "Plan not found")
    items = body.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(400, "items must be list")
    for item in items:
        if not isinstance(item, dict):
            continue
        feature_key = str(item.get("feature_key") or "").strip()
        if not feature_key:
            continue
        value = item.get("value")
        current = db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id, PlanFeature.feature_key == feature_key).first()
        if current:
            current.value_json = {"value": value}
        else:
            db.add(PlanFeature(plan_id=plan_id, feature_key=feature_key, value_json={"value": value}))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/plans/{plan_id}/quota-rules")
def admin_quota_rules(plan_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    if not db.get(Plan, plan_id):
        raise HTTPException(404, "Plan not found")
    rules = db.query(PlanQuotaRule).filter(PlanQuotaRule.plan_id == plan_id).order_by(PlanQuotaRule.feature_key.asc()).all()
    return [{
        "feature_key": item.feature_key,
        "reset_period": item.reset_period,
        "deduct_mode": item.deduct_mode,
        "extra_config": item.extra_config or {},
    } for item in rules]


@app.put("/api/admin/plans/{plan_id}/quota-rules")
def admin_save_quota_rules(plan_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    if not db.get(Plan, plan_id):
        raise HTTPException(404, "Plan not found")
    items = body.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(400, "items must be list")
    for item in items:
        if not isinstance(item, dict):
            continue
        feature_key = str(item.get("feature_key") or "").strip()
        if not feature_key:
            continue
        current = db.query(PlanQuotaRule).filter(PlanQuotaRule.plan_id == plan_id, PlanQuotaRule.feature_key == feature_key).first()
        reset_period = str(item.get("reset_period") or "monthly")
        deduct_mode = str(item.get("deduct_mode") or "on_success")
        extra = item.get("extra_config")
        if current:
            current.reset_period = reset_period
            current.deduct_mode = deduct_mode
            current.extra_config = extra if isinstance(extra, dict) else {}
        else:
            db.add(PlanQuotaRule(plan_id=plan_id, feature_key=feature_key, reset_period=reset_period, deduct_mode=deduct_mode, extra_config=extra if isinstance(extra, dict) else {}))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    users = db.query(User).order_by(User.created_at.desc()).all()
    subscription_map = {item.user_id: item.plan_id for item in db.query(UserSubscription).all()}
    plan_map = {plan.id: plan for plan in db.query(Plan).all()}
    result = []
    for user in users:
        plan = plan_map.get(subscription_map.get(user.id))
        result.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "allow_api_key_override": bool(user.allow_api_key_override),
            "allow_api_url_override": bool(user.allow_api_url_override),
            "created_at": user.created_at,
            "plan_name": plan.name if plan else "Free",
        })
    return result


@app.post("/api/admin/users")
def admin_create_user(body: dict, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "").strip()
    name = str(body.get("name") or "").strip() or "新用户"
    role = str(body.get("role") or "user").strip().lower()
    allow_api_key_override = bool(body.get("allow_api_key_override", False))
    allow_api_url_override = bool(body.get("allow_api_url_override", False))
    if not email or not password:
        raise HTTPException(400, "email and password are required")
    if role not in {"user", "admin"}:
        raise HTTPException(400, "role must be user or admin")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already exists")
    user = User(
        email=email,
        password_hash=_password_hash(password),
        name=name,
        role=role,
        status="active",
        email_verified=True,
        allow_api_key_override=allow_api_key_override,
        allow_api_url_override=allow_api_url_override,
    )
    db.add(user)
    _write_audit_log(admin, "create_user", "user", email, f"创建用户 {email}", db, {"email": email, "name": name, "role": role})
    db.commit()
    return {"ok": True, "user_id": user.id}


@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if body.get("name") is not None:
        user.name = str(body.get("name") or user.name).strip() or user.name
    if body.get("email") is not None:
        email = str(body.get("email") or "").strip().lower()
        existing = db.query(User).filter(User.email == email, User.id != user.id).first()
        if existing:
            raise HTTPException(409, "Email already exists")
        if email:
            user.email = email
    if body.get("role") is not None:
        role = str(body.get("role") or "").strip().lower()
        if role not in {"user", "admin"}:
            raise HTTPException(400, "role must be user or admin")
        user.role = role
    if body.get("status") is not None:
        status = str(body.get("status") or "").strip().lower()
        if status not in {"active", "disabled"}:
            raise HTTPException(400, "status must be active or disabled")
        user.status = status
    if body.get("allow_api_key_override") is not None:
        user.allow_api_key_override = bool(body.get("allow_api_key_override"))
    if body.get("allow_api_url_override") is not None:
        user.allow_api_url_override = bool(body.get("allow_api_url_override"))
    if body.get("password"):
        user.password_hash = _password_hash(str(body.get("password")))
    _write_audit_log(admin, "update_user", "user", user.id, f"更新用户 {user.email}", db, {
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "allow_api_key_override": bool(user.allow_api_key_override),
        "allow_api_url_override": bool(user.allow_api_url_override),
        "password_changed": bool(body.get("password")),
    })
    db.commit()
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "Cannot delete current admin")
    user.status = "disabled"
    _write_audit_log(admin, "disable_user", "user", user.id, f"停用用户 {user.email}", db, {"email": user.email})
    db.commit()
    return {"ok": True}


@app.get("/api/admin/users/{user_id}/entitlements")
def admin_user_entitlements(user_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    plan = _active_plan_for_user(user.id, db)
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user.id).first()
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
        "subscription": {"status": sub.status if sub else "active"},
        "plan": {"id": plan.id, "code": plan.code, "name": plan.name},
        "entitlements": _plan_feature_map(plan.id, db),
        "usage": _usage_entries_for_user(user.id, db),
    }


@app.get("/api/admin/users/{user_id}/stories")
def admin_user_stories(user_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    stories = (
        db.query(Story)
        .filter(Story.owner_user_id == user.id)
        .order_by(Story.created_at.desc())
        .all()
    )
    chapter_counts = {
        story_id: count
        for story_id, count in (
            db.query(Chapter.story_id, func.count(Chapter.id))
            .filter(Chapter.story_id.in_([story.id for story in stories] or [0]))
            .group_by(Chapter.story_id)
            .all()
        )
    }
    return [
        {
            "id": story.id,
            "title": story.title,
            "description": story.description or "",
            "cover_image": story.cover_image,
            "created_at": story.created_at,
            "chapter_count": int(chapter_counts.get(story.id, 0)),
        }
        for story in stories
    ]


@app.get("/api/admin/stories/{story_id}/chapters")
def admin_story_chapters(story_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    chapters = (
        db.query(Chapter)
        .filter(Chapter.story_id == story.id)
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    return {
        "story": {
            "id": story.id,
            "title": story.title,
            "description": story.description or "",
            "created_at": story.created_at,
            "owner_user_id": story.owner_user_id,
        },
        "chapters": [
            {
                "id": chapter.id,
                "chapter_number": chapter.chapter_number,
                "title": chapter.title or f"第{chapter.chapter_number}话",
                "status": chapter.status,
                "word_count": chapter.word_count or 0,
                "created_at": chapter.created_at,
                "novel_content": chapter.novel_content or "",
            }
            for chapter in chapters
        ],
    }


@app.post("/api/admin/users/{user_id}/subscription")
def admin_update_user_subscription(user_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    plan_id = int(body.get("plan_id") or 0)
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    _upsert_user_subscription(user.id, plan.id, db)
    order = BillingOrder(
        order_no=f"LVADM{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.randbelow(10000):04d}",
        user_id=user.id,
        plan_id=plan.id,
        amount=_coerce_money(plan.monthly_price),
        currency=plan.currency,
        status="admin_adjusted",
        source="admin_adjustment",
        billing_cycle="monthly",
        operator_user_id=admin.id,
        note=f"管理员 {admin.name} 调整用户套餐为 {plan.name}",
        extra_json={"action": "subscription_adjustment"},
    )
    db.add(order)
    _write_audit_log(admin, "update_user_subscription", "user", user.id, f"将 {user.email} 套餐调整为 {plan.name}", db, {
        "plan_id": plan.id,
        "plan_name": plan.name,
        "order_no": order.order_no,
    })
    db.commit()
    return {
        "ok": True,
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "plan": {"id": plan.id, "code": plan.code, "name": plan.name},
        "order": _serialize_order_with_db(order, db),
    }


@app.post("/api/admin/users/{user_id}/quota-grants")
def admin_grant_user_quota(user_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    feature_key = str(body.get("feature_key") or "").strip()
    amount = int(body.get("amount") or 0)
    if not feature_key:
        raise HTTPException(400, "feature_key is required")
    if amount <= 0:
        raise HTTPException(400, "amount must be greater than 0")
    period_key = _current_period_key()
    grant = db.query(UserQuotaGrantMonthly).filter(
        UserQuotaGrantMonthly.user_id == user.id,
        UserQuotaGrantMonthly.feature_key == feature_key,
        UserQuotaGrantMonthly.period_key == period_key,
    ).first()
    before = int(grant.granted_amount if grant else 0)
    after = before + amount
    if grant:
        grant.granted_amount = after
    else:
        grant = UserQuotaGrantMonthly(
            user_id=user.id,
            feature_key=feature_key,
            period_key=period_key,
            granted_amount=amount,
        )
        db.add(grant)
    order = BillingOrder(
        order_no=f"LVGRT{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.randbelow(10000):04d}",
        user_id=user.id,
        plan_id=_active_plan_for_user(user.id, db).id,
        amount=0,
        currency="CNY",
        status="admin_adjusted",
        source="quota_grant",
        billing_cycle="monthly",
        payment_provider="system",
        payment_method="manual_adjustment",
        operator_user_id=admin.id,
        note=f"管理员 {admin.name} 补发 {feature_key} 额度 {amount}",
        extra_json={
            "action": "quota_grant",
            "feature_key": feature_key,
            "feature_name": FEATURE_CATALOG_MAP.get(feature_key, {}).get("name", feature_key),
            "amount": amount,
            "period_key": period_key,
            "before_granted": before,
            "after_granted": after,
        },
        paid_at=datetime.datetime.utcnow(),
    )
    db.add(order)
    _write_audit_log(admin, "grant_user_quota", "user", user.id, f"为 {user.email} 补发 {feature_key} 额度", db, {
        "feature_key": feature_key,
        "amount": amount,
        "period_key": period_key,
        "before_granted": before,
        "after_granted": after,
    })
    db.commit()
    return {
        "ok": True,
        "feature_key": feature_key,
        "granted_amount": amount,
        "before_granted": before,
        "after_granted": after,
        "usage": _usage_entries_for_user(user.id, db),
    }


@app.get("/api/admin/platform/settings")
def admin_platform_settings(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    _require_admin(request, db)
    return _platform_settings_snapshot(db)


@app.get("/api/platform/settings/public")
def public_platform_settings(db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    return _public_platform_settings_snapshot(db)


@app.get("/api/platform/icon")
def public_platform_icon(db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    icon_data = _get_platform_setting("platform.icon_data", db, "")
    icon_mime = _get_platform_setting("platform.icon_mime", db, "image/png") or "image/png"
    if not icon_data:
        raise HTTPException(404, "Platform icon not configured")
    try:
        import base64

        icon_bytes = base64.b64decode(icon_data, validate=True)
    except Exception:
        raise HTTPException(500, "Stored platform icon is invalid")
    return Response(content=icon_bytes, media_type=str(icon_mime))


@app.put("/api/admin/platform/settings")
def admin_save_platform_settings(body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    basic = body.get("basic") if isinstance(body.get("basic"), dict) else {}
    api = body.get("api") if isinstance(body.get("api"), dict) else {}
    auth = body.get("auth") if isinstance(body.get("auth"), dict) else {}
    email = body.get("email") if isinstance(body.get("email"), dict) else {}
    payment = body.get("payment") if isinstance(body.get("payment"), dict) else {}
    announcement = body.get("announcement") if isinstance(body.get("announcement"), dict) else {}
    mappings = {
        "platform.site_name": basic.get("site_name", "StoryCanvas"),
        "platform.site_slogan": basic.get("site_slogan", ""),
        "platform.support_email": basic.get("support_email", ""),
        "platform.icp": basic.get("icp", ""),
        "platform.copyright": basic.get("copyright", ""),
        "platform.notice": basic.get("notice", ""),
        "api.deepseek.base_url": api.get("deepseek_base_url", "https://api.deepseek.com"),
        "api.deepseek.model": api.get("deepseek_model", "deepseek-chat"),
        "api.deepseek.api_key": api.get("deepseek_api_key", ""),
        "api.image.base_url": api.get("image_base_url", "https://api.xbyjs.top/v1"),
        "api.image.model": api.get("image_model", "default"),
        "api.image.api_key": api.get("image_api_key", ""),
        "api.enable_user_override": bool(api.get("enable_user_override", True)),
        "api.enable_user_url_override": bool(api.get("enable_user_url_override", False)),
        "auth.require_email_code_for_register": bool(auth.get("require_email_code_for_register", False)),
        "auth.require_email_code_for_login": bool(auth.get("require_email_code_for_login", False)),
        "auth.email_code_expire_minutes": int(auth.get("email_code_expire_minutes", 10) or 10),
        "auth.email_code_length": int(auth.get("email_code_length", 6) or 6),
        "email.smtp_enabled": bool(email.get("smtp_enabled", False)),
        "email.smtp_host": str(email.get("smtp_host", "") or ""),
        "email.smtp_port": int(email.get("smtp_port", 587) or 587),
        "email.smtp_username": str(email.get("smtp_username", "") or ""),
        "email.smtp_password": str(email.get("smtp_password", "") or ""),
        "email.smtp_from_email": str(email.get("smtp_from_email", "") or ""),
        "email.smtp_from_name": str(email.get("smtp_from_name", "StoryCanvas") or "StoryCanvas"),
        "email.smtp_use_tls": bool(email.get("smtp_use_tls", True)),
        "email.smtp_use_ssl": bool(email.get("smtp_use_ssl", False)),
        "payment.enabled": bool(payment.get("enabled", True)),
        "payment.mode": str(payment.get("mode", "mock") or "mock"),
        "payment.default_method": str(payment.get("default_method", "mock_qr") or "mock_qr"),
        "payment.order_expire_minutes": int(payment.get("order_expire_minutes", 30) or 30),
        "payment.auto_activate_free_plan": bool(payment.get("auto_activate_free_plan", True)),
        "payment.instructions": str(payment.get("instructions", "") or ""),
        "payment.mock_enabled": bool(payment.get("mock_enabled", True)),
        "payment.wechat_enabled": bool(payment.get("wechat_enabled", False)),
        "payment.wechat_app_id": str(payment.get("wechat_app_id", "") or ""),
        "payment.wechat_mch_id": str(payment.get("wechat_mch_id", "") or ""),
        "payment.wechat_notify_url": str(payment.get("wechat_notify_url", "") or ""),
        "payment.alipay_enabled": bool(payment.get("alipay_enabled", False)),
        "payment.alipay_app_id": str(payment.get("alipay_app_id", "") or ""),
        "payment.alipay_pid": str(payment.get("alipay_pid", "") or ""),
        "payment.alipay_gateway": str(payment.get("alipay_gateway", "https://openapi.alipay.com/gateway.do") or "https://openapi.alipay.com/gateway.do"),
        "payment.alipay_sign_type": str(payment.get("alipay_sign_type", "RSA2") or "RSA2"),
        "payment.alipay_app_private_key": str(payment.get("alipay_app_private_key", "") or ""),
        "payment.alipay_public_key": str(payment.get("alipay_public_key", "") or ""),
        "payment.alipay_notify_url": str(payment.get("alipay_notify_url", "") or ""),
        "platform.announcement.enabled": bool(announcement.get("enabled", False)),
        "platform.announcement.title": announcement.get("title", ""),
        "platform.announcement.content": announcement.get("content", ""),
    }
    icon_data = basic.get("icon_data")
    icon_mime = basic.get("icon_mime", "image/png")
    clear_icon = bool(basic.get("clear_icon", False))
    for key, value in mappings.items():
        _set_platform_setting(key, value, db)
    if clear_icon:
        _set_platform_setting("platform.icon_data", "", db)
        _set_platform_setting("platform.icon_mime", "", db)
        _set_platform_setting("platform.icon_updated_at", "", db)
    elif isinstance(icon_data, str) and icon_data.strip():
        _set_platform_setting("platform.icon_data", icon_data.strip(), db)
        _set_platform_setting("platform.icon_mime", str(icon_mime or "image/png"), db)
        _set_platform_setting("platform.icon_updated_at", datetime.datetime.utcnow().isoformat(), db)
    db.commit()
    return {"ok": True, "settings": _platform_settings_snapshot(db)}


@app.get("/api/admin/platform/announcement")
def admin_get_announcement(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return {
        "enabled": bool(_get_platform_setting("platform.announcement.enabled", db, False)),
        "title": str(_get_platform_setting("platform.announcement.title", db, "") or ""),
        "content": str(_get_platform_setting("platform.announcement.content", db, "") or ""),
    }


@app.put("/api/admin/platform/announcement")
def admin_save_announcement(body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    _set_platform_setting("platform.announcement.enabled", bool(body.get("enabled", False)), db)
    _set_platform_setting("platform.announcement.title", str(body.get("title", "") or ""), db)
    _set_platform_setting("platform.announcement.content", str(body.get("content", "") or ""), db)
    db.commit()
    return {
        "ok": True,
        "announcement": {
            "enabled": bool(_get_platform_setting("platform.announcement.enabled", db, False)),
            "title": str(_get_platform_setting("platform.announcement.title", db, "") or ""),
            "content": str(_get_platform_setting("platform.announcement.content", db, "") or ""),
        },
    }


@app.get("/api/platform/announcement")
def public_announcement(db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    enabled = bool(_get_platform_setting("platform.announcement.enabled", db, False))
    if not enabled:
        return {"enabled": False, "title": "", "content": ""}
    return {
        "enabled": True,
        "title": str(_get_platform_setting("platform.announcement.title", db, "") or ""),
        "content": str(_get_platform_setting("platform.announcement.content", db, "") or ""),
    }


@app.get("/api/admin/audit-logs")
def admin_audit_logs(
    request: Request,
    action: str | None = Query(default=None),
    actor_name: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action.strip())
    if actor_name:
        query = query.filter(AuditLog.actor_name.ilike(f"%{actor_name.strip()}%"))
    if target_type:
        query = query.filter(AuditLog.target_type == target_type.strip())
    if target_id:
        query = query.filter(AuditLog.target_id == target_id.strip())
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{
        "id": item.id,
        "actor_user_id": item.actor_user_id,
        "actor_name": item.actor_name,
        "action": item.action,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "summary": item.summary,
        "detail": item.detail_json or {},
        "created_at": item.created_at,
    } for item in logs]


@app.get("/api/admin/orders")
def admin_orders(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    orders = db.query(BillingOrder).order_by(BillingOrder.created_at.desc()).limit(100).all()
    for order in orders:
        _sync_order_status(order, db)
    return [_serialize_order_with_db(order, db) for order in orders]


@app.post("/api/admin/orders/{order_no}/status")
def admin_update_order_status(order_no: str, body: dict, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    admin = _require_admin(request, db)
    order = db.query(BillingOrder).filter(BillingOrder.order_no == order_no).first()
    if not order:
        raise HTTPException(404, "Order not found")
    order = _sync_order_status(order, db)
    next_status = str(body.get("status") or "").strip().lower()
    note = str(body.get("note") or "").strip()
    plan = db.get(Plan, order.plan_id)
    if next_status == "paid":
        _mark_order_paid(order, db, operator_user_id=admin.id, note=note or f"Marked paid by admin {admin.name}")
    elif next_status == "cancelled":
        _mark_order_cancelled(order, db, operator_user_id=admin.id, note=note or f"Cancelled by admin {admin.name}")
    elif next_status == "expired":
        _mark_order_expired(order, db, note=note or f"Expired by admin {admin.name}")
    else:
        raise HTTPException(400, "status must be paid, cancelled, or expired")
    _write_audit_log(admin, "admin_update_order_status", "billing_order", order.order_no, f"Updated order to {order.status}", db, {
        "order_no": order.order_no,
        "status": order.status,
        "plan_id": order.plan_id,
        "plan_name": plan.name if plan else "",
    })
    db.commit()
    db.refresh(order)
    return {"ok": True, "order": _serialize_order_with_db(order, db)}


@app.post("/api/stories", response_model=StoryOut)
def create_story(body: StoryCreate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = Story(title=body.title, description=body.description, owner_user_id=user.id)
    db.add(story)
    db.flush()
    # Auto-create first chapter
    chapter = Chapter(story_id=story.id, chapter_number=1)
    db.add(chapter)
    db.flush()
    _initialize_empty_chapter_workspace(chapter.id)
    db.commit()
    db.refresh(story)
    return story


@app.get("/api/stories", response_model=list[StoryOut])
def list_stories(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    query = db.query(Story).filter(Story.owner_user_id == user.id)
    return query.order_by(Story.created_at.desc()).all()


@app.get("/api/stories/{story_id}", response_model=StoryOut)
def get_story(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    return story


@app.put("/api/stories/{story_id}", response_model=StoryOut)
def update_story(story_id: int, body: StoryUpdate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if body.title is not None:
        story.title = body.title
    if body.description is not None:
        story.description = body.description
    if body.tags is not None:
        story.tags = body.tags
    if body.outline is not None:
        story.outline = body.outline
    if body.characters is not None:
        story.characters = _normalize_characters_payload(body.characters)
    db.commit()
    db.refresh(story)
    return story


@app.delete("/api/stories/{story_id}")
def delete_story(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    # Delete all chapters and their data
    for chapter in story.chapters:
        chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter.id}"
        _rmtree_best_effort(chapter_dir, "chapter directory")
        for img in chapter.images:
            db.delete(img)
        for msg in chapter.messages:
            db.delete(msg)
        db.delete(chapter)
    if story.cover_image:
        cover_path = Path(__file__).resolve().parent / story.cover_image
        try:
            _unlink_file(cover_path, "story cover")
        except HTTPException:
            logger.warning("Story cover remained after story deletion: %s", cover_path)
    story_dir = Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}"
    _rmtree_best_effort(story_dir, "story asset directory")
    db.delete(story)
    db.commit()
    return {"ok": True}


@app.post("/api/stories/{story_id}/upload-cover")
async def upload_story_cover(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    b64 = body.get("image", "")
    import uuid
    img_bytes = _decode_png_upload(b64)
    covers_dir = manga_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cover_{story_id}_{uuid.uuid4().hex[:8]}.png"
    _write_bytes_or_conflict(covers_dir / filename, img_bytes, "story cover")
    # Delete old cover file if exists
    if story.cover_image:
        old = Path(__file__).resolve().parent / story.cover_image
        try:
            _unlink_file(old, "old story cover")
        except HTTPException:
            logger.warning("Old story cover remained after replacement: %s", old)
    story.cover_image = f"manga_outputs/covers/{filename}"
    db.commit()
    db.refresh(story)
    return {"cover_image": story.cover_image}


# ─── Chapter CRUD ───────────────────────────────────────────

@app.get("/api/stories/{story_id}/chapters", response_model=list[ChapterOut])
def list_chapters(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    return (
        db.query(Chapter)
        .filter(Chapter.story_id == story_id)
        .order_by(Chapter.chapter_number)
        .all()
    )


@app.get("/api/chapters/{chapter_id}", response_model=ChapterOut)
def get_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    return chapter


@app.post("/api/stories/{story_id}/chapters", response_model=ChapterOut)
def create_next_chapter(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    story = db.query(Story).filter(Story.id == story.id).with_for_update().first()
    max_num = (
        db.query(Chapter.chapter_number)
        .filter(Chapter.story_id == story_id)
        .order_by(Chapter.chapter_number.desc())
        .first()
    )
    next_num = (max_num[0] + 1) if max_num else 1
    chapter = Chapter(story_id=story_id, chapter_number=next_num, title=f"第{next_num}话", status="pending")
    db.add(chapter)
    db.flush()
    _initialize_empty_chapter_workspace(chapter.id)
    db.commit()
    db.refresh(chapter)
    return chapter


@app.delete("/api/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # Delete image files from disk
    chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"
    _rmtree_best_effort(chapter_dir, "chapter directory")

    # Delete DB records (messages + images cascade via relationship, or manually)
    for img in chapter.images:
        db.delete(img)
    for msg in chapter.messages:
        db.delete(msg)
    db.delete(chapter)
    db.commit()
    return {"ok": True}


# ─── Chat (SSE streaming) ──────────────────────────────────

@app.post("/api/chapters/{chapter_id}/chat")
async def chat(chapter_id: int, body: ChatMessageIn, request: Request, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    if chapter.content_source == "import":
        raise HTTPException(409, "This chapter was imported from existing novel text and cannot use AI chat")

    # Save user message
    chapter.content_source = "chat"
    user_msg = ChatMessage(chapter_id=chapter_id, role="user", content=body.content)
    db.add(user_msg)
    db.commit()

    # Build message history including all previous chapters in same story
    all_chapters = (
        db.query(Chapter)
        .filter(Chapter.story_id == chapter.story_id, Chapter.chapter_number <= chapter.chapter_number)
        .order_by(Chapter.chapter_number)
        .all()
    )
    history = []
    for ch in all_chapters:
        for m in ch.messages:
            history.append({"role": m.role, "content": m.content})

    framework_context = _build_framework_context(chapter.story, chapter)

    collected: list[str] = []

    def save_interrupted_assistant() -> None:
        full_content = "".join(collected).strip()
        if not full_content:
            return
        assistant_msg = ChatMessage(
            chapter_id=chapter_id,
            role="assistant",
            content=f"{full_content}\n\n[已中止]",
        )
        db.add(assistant_msg)
        db.commit()

    async def event_generator():
        try:
            async for token in chat_stream(history, api_key=_user_deepseek_api_key(request), framework_context=framework_context):
                collected.append(token)
                yield {"event": "token", "data": json.dumps({"content": token}, ensure_ascii=False)}
            # Save assistant message
            full_content = "".join(collected)
            assistant_msg = ChatMessage(chapter_id=chapter_id, role="assistant", content=full_content)
            db.add(assistant_msg)
            db.commit()
            yield {"event": "done", "data": json.dumps({"content": full_content}, ensure_ascii=False)}
        except asyncio.CancelledError:
            db.rollback()
            save_interrupted_assistant()
            raise
        except Exception as e:
            db.rollback()
            persisted_user_msg = db.get(ChatMessage, user_msg.id)
            if persisted_user_msg:
                db.delete(persisted_user_msg)
                db.commit()
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


# ─── Generate Novel ─────────────────────────────────────────

@app.post("/api/chapters/{chapter_id}/generate-novel", response_model=ChapterOut)
async def generate_novel_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    if chapter.content_source == "import":
        raise HTTPException(409, "This chapter was imported from existing novel text and cannot generate AI novel text")

    history = [{"role": m.role, "content": m.content} for m in chapter.messages]
    if not history:
        raise HTTPException(400, "No chat history to generate novel from")

    # Build framework context from story outline, characters, tags and chapter metadata
    framework_context = _build_framework_context(chapter.story, chapter)

    novel_content = await generate_novel(
        history,
        api_key=_user_deepseek_api_key(request),
        framework_context=framework_context,
    )
    _apply_chapter_content(chapter, novel_content, status="completed")
    chapter.content_source = "chat"

    # Also save as assistant message
    msg = ChatMessage(chapter_id=chapter_id, role="assistant", content=novel_content)
    db.add(msg)
    db.commit()
    db.refresh(chapter)
    return chapter


MAX_IMPORTED_NOVEL_CHARS = int(os.getenv("MAX_IMPORTED_NOVEL_CHARS", "50000"))


@app.post("/api/chapters/{chapter_id}/import-novel", response_model=ChapterOut)
async def import_novel_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Replace chapter chat history with a single user-imported novel text.

    The imported text is saved both as a single chat message (so the existing
    `generate-scenes` flow works unchanged) and as `chapter.novel_content`.
    """
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    body = await request.json()
    raw = body.get("content", "")
    if not isinstance(raw, str):
        raise HTTPException(400, "content must be a string")
    text = raw.strip()
    if not text:
        raise HTTPException(400, "content is empty")
    if len(text) > MAX_IMPORTED_NOVEL_CHARS:
        raise HTTPException(413, f"Novel is too long. Max length is {MAX_IMPORTED_NOVEL_CHARS} characters")
    if chapter.content_source == "chat" or chapter.messages:
        raise HTTPException(409, "This chapter already uses AI chat. Create a new chapter to import existing novel text.")
    if chapter.images:
        raise HTTPException(409, "This chapter already has manga images. Create a new chapter to import existing novel text.")

    _clear_chapter_manga_state(chapter, db)
    db.query(ChatMessage).filter(ChatMessage.chapter_id == chapter_id).delete()
    db.add(ChatMessage(chapter_id=chapter_id, role="user", content=text))
    _apply_chapter_content(chapter, text, status="draft")
    chapter.content_source = "import"
    db.commit()
    db.refresh(chapter)
    return chapter


@app.put("/api/chapters/{chapter_id}/content", response_model=ChapterOut)
def update_chapter_content(chapter_id: int, body: ChapterContentUpdate, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "content is empty")
    _apply_chapter_content(chapter, text, status="draft")
    db.commit()
    db.refresh(chapter)
    return chapter


# ─── Character Profiles ───────────────────────────────────

def _characters_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "characters.txt"


def _load_characters(chapter_id: int, db: Session | None = None) -> str:
    """Load character profiles: chapter-level file first, then fallback to story-level."""
    p = _characters_path(chapter_id)
    if p.exists():
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    # Fallback to story-level
    if db:
        chapter = db.get(Chapter, chapter_id)
        if chapter and chapter.story and chapter.story.character_profiles:
            return chapter.story.character_profiles.strip()
    return ""


def _has_chapter_characters(chapter_id: int) -> bool:
    """Check if chapter has its own character file (not inherited)."""
    p = _characters_path(chapter_id)
    return p.exists() and bool(p.read_text(encoding="utf-8").strip())


# Story-level character profiles
@app.get("/api/stories/{story_id}/characters")
async def get_story_characters(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    return {"characters": (story.character_profiles or "").strip()}


@app.put("/api/stories/{story_id}/characters")
async def save_story_characters(story_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    story.character_profiles = _character_profile_text(body)
    db.commit()
    return {"ok": True}


@app.post("/api/stories/{story_id}/characters/generate")
async def generate_story_characters_from_framework(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if not isinstance(story.characters, list) or len(story.characters) == 0:
        raise HTTPException(400, "Story has no framework characters to convert")

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    generated = await generate_character_profiles_from_framework(
        _story_framework_context(story),
        api_key=_user_deepseek_api_key(request),
    )
    story.character_profiles = _character_profile_text({"characters": generated})
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    return {"characters": story.character_profiles.strip()}


# Chapter-level character profiles (with fallback info)
@app.get("/api/chapters/{chapter_id}/characters")
async def get_characters(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    has_own = _has_chapter_characters(chapter_id)
    if has_own:
        text = _characters_path(chapter_id).read_text(encoding="utf-8").strip()
    else:
        text = (chapter.story.character_profiles or "").strip() if chapter.story else ""
    return {"characters": text, "source": "chapter" if has_own else ("story" if text else "none")}


@app.put("/api/chapters/{chapter_id}/characters")
async def save_characters(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    text = _character_profile_text(body)
    p = _characters_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return {"ok": True}


@app.delete("/api/chapters/{chapter_id}/characters")
async def reset_chapter_characters(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete chapter-level override so it falls back to story-level."""
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    p = _characters_path(chapter_id)
    _unlink_file(p, "character profile")
    return {"ok": True}


# ─── Reference Image (垫图，支持多图) ──────────────────────────

MAX_REF_IMAGES_PER_LEVEL = int(os.getenv("MAX_REF_IMAGES_PER_LEVEL", "4"))


def _story_ref_dir(story_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}" / "ref_images"


def _chapter_ref_dir(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "ref_images"


def _ref_meta_path(ref_dir: Path) -> Path:
    return ref_dir / "ref_meta.json"


def _legacy_story_ref_image(story_id: int) -> Path:
    """Old single-file location, kept for backward compat / lazy migration."""
    return Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}" / "ref_image.png"


def _legacy_chapter_ref_image(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "ref_image.png"


def _migrate_legacy_ref(legacy: Path, ref_dir: Path) -> None:
    """Move legacy single ref_image.png into ref_images/ as ref_legacy.png on demand."""
    if not legacy.exists():
        return
    try:
        ref_dir.mkdir(parents=True, exist_ok=True)
        target = ref_dir / "ref_legacy.png"
        if target.exists():
            target = ref_dir / f"ref_legacy_{uuid.uuid4().hex[:8]}.png"
        legacy.rename(target)
        logger.info("Migrated legacy ref image %s -> %s", legacy, target)
    except OSError as exc:
        logger.warning("Failed to migrate legacy ref image %s: %s", legacy, exc)


def _list_ref_files(ref_dir: Path) -> list[Path]:
    if not ref_dir.exists():
        return []
    return sorted([p for p in ref_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"])


def _load_ref_meta(ref_dir: Path) -> dict[str, dict]:
    meta_path = _ref_meta_path(ref_dir)
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_ref_meta(ref_dir: Path, meta: dict[str, dict]) -> None:
    ref_dir.mkdir(parents=True, exist_ok=True)
    _ref_meta_path(ref_dir).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _ref_static_path(ref_dir: Path, filename: str, kind: str, owner_id: int) -> str:
    """Build the static URL-relative path for a ref image."""
    if kind == "story":
        return f"manga_outputs/story_{owner_id}/ref_images/{filename}"
    return f"manga_outputs/chapter_{owner_id}/ref_images/{filename}"


def _serialize_refs(ref_dir: Path, kind: str, owner_id: int) -> list[dict]:
    meta = _load_ref_meta(ref_dir)
    out = []
    for p in _list_ref_files(ref_dir):
        item = {
            "filename": p.name,
            "image_path": _ref_static_path(ref_dir, p.name, kind, owner_id),
            "size_kb": round(p.stat().st_size / 1024),
        }
        extra = meta.get(p.name)
        if isinstance(extra, dict):
            if isinstance(extra.get("label"), str) and extra["label"].strip():
                item["label"] = extra["label"].strip()
            if isinstance(extra.get("kind"), str) and extra["kind"].strip():
                item["kind"] = extra["kind"].strip()
        out.append(item)
    return out


def _build_ref_entries(ref_dir: Path, kind: str, owner_id: int) -> list[dict]:
    meta = _load_ref_meta(ref_dir)
    entries: list[dict] = []
    for p in _list_ref_files(ref_dir):
        item = {
            "filename": p.name,
            "path": p,
            "image_path": _ref_static_path(ref_dir, p.name, kind, owner_id),
            "kind": "",
            "label": "",
        }
        extra = meta.get(p.name)
        if isinstance(extra, dict):
            if isinstance(extra.get("label"), str):
                item["label"] = extra["label"].strip()
            if isinstance(extra.get("kind"), str):
                item["kind"] = extra["kind"].strip()
        entries.append(item)
    return entries


def _effective_ref_entries(chapter_id: int, db: Session) -> list[dict]:
    chapter_dir = _chapter_ref_dir(chapter_id)
    _migrate_legacy_ref(_legacy_chapter_ref_image(chapter_id), chapter_dir)
    chapter_refs = _build_ref_entries(chapter_dir, "chapter", chapter_id)
    if chapter_refs:
        return chapter_refs
    chapter = db.get(Chapter, chapter_id)
    if chapter:
        story_dir = _story_ref_dir(chapter.story_id)
        _migrate_legacy_ref(_legacy_story_ref_image(chapter.story_id), story_dir)
        return _build_ref_entries(story_dir, "story", chapter.story_id)
    return []


def _effective_ref_image_paths(chapter_id: int, db: Session) -> list[Path]:
    """Return the effective ref image list: chapter-level first, else story-level fallback."""
    return [entry["path"] for entry in _effective_ref_entries(chapter_id, db)]


def _select_ref_image_paths_for_scene(scene_prompt: str, ref_entries: list[dict]) -> list[Path]:
    if not ref_entries:
        return []

    scene_text = (scene_prompt or "").strip()
    unlabeled = [entry["path"] for entry in ref_entries if not entry.get("label")]
    labeled_matches = [
        entry["path"]
        for entry in ref_entries
        if entry.get("label") and entry["label"] in scene_text
    ]
    if labeled_matches:
        seen: set[str] = set()
        selected: list[Path] = []
        for path in [*unlabeled, *labeled_matches]:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            selected.append(path)
        return selected
    return unlabeled or [entry["path"] for entry in ref_entries]


def _save_uploaded_ref(ref_dir: Path, img_bytes: bytes, label: str) -> str:
    if len(_list_ref_files(ref_dir)) >= MAX_REF_IMAGES_PER_LEVEL:
        raise HTTPException(409, f"Maximum {MAX_REF_IMAGES_PER_LEVEL} reference images allowed")
    ref_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ref_{uuid.uuid4().hex[:8]}.png"
    _write_bytes_or_conflict(ref_dir / filename, img_bytes, label)
    return filename


def _slugify_ref_label(label: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", (label or "").strip())
    slug = slug.strip("_")
    return slug[:40] or "character"


def _build_character_ref_prompt(story: Story, card: dict) -> str:
    tags = json.dumps(story.tags, ensure_ascii=False) if story.tags else "漫画角色设定"
    return (
        "请生成一张单人漫画角色参考图，用于后续固定角色形象。\n"
        f"题材标签：{tags}\n"
        f"角色名：{card['name']}\n"
        f"角色外貌卡：\n{card['raw']}\n\n"
        "要求：只出现该角色一人；突出稳定五官、发型、服装和体型特征；"
        "采用角色设定图或干净半身立绘构图；背景简洁；不要对话框、不要文字、不要分镜、不要多人物。"
    )


# ─── Story-level multi ref images ───────────────────────────

@app.post("/api/stories/{story_id}/character-ref-images/generate")
async def generate_story_character_ref_images(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    cards = _parse_character_profile_cards(story.character_profiles or "")
    if not cards:
        raise HTTPException(400, "Story has no character appearance cards to convert")

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    target_name = (body.get("character_name") or "").strip() if isinstance(body, dict) else ""
    overwrite = bool(body.get("overwrite")) if isinstance(body, dict) else False

    targets = [card for card in cards if not target_name or card["name"] == target_name]
    if not targets:
        raise HTTPException(404, f"Character '{target_name}' not found in appearance cards")

    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    ref_dir.mkdir(parents=True, exist_ok=True)
    meta = _load_ref_meta(ref_dir)
    generated: list[str] = []
    skipped: list[str] = []
    pending_targets: list[dict] = []

    for card in targets:
        existing = [
            filename
            for filename, item in meta.items()
            if isinstance(item, dict)
            and item.get("kind") == "character_generated"
            and item.get("label") == card["name"]
        ]
        if existing and not overwrite:
            skipped.append(card["name"])
            continue
        pending_targets.append(card)

    if pending_targets:
        _check_and_consume_feature_quota(
            request,
            user.id,
            "manga.image.monthly_limit",
            len(pending_targets),
            db,
            deduct=False,
            provider_kind="image",
        )

    for card in pending_targets:
        existing = [
            filename
            for filename, item in meta.items()
            if isinstance(item, dict)
            and item.get("kind") == "character_generated"
            and item.get("label") == card["name"]
        ]
        for filename in existing:
            path = ref_dir / filename
            if path.exists():
                _unlink_file(path, "story character ref image")
            meta.pop(filename, None)

        if len(_list_ref_files(ref_dir)) >= MAX_REF_IMAGES_PER_LEVEL:
            raise HTTPException(409, f"Maximum {MAX_REF_IMAGES_PER_LEVEL} reference images allowed")

        filename = f"char_{_slugify_ref_label(card['name'])}_{uuid.uuid4().hex[:8]}.png"
        await generate_reference_image(
            _build_character_ref_prompt(story, card),
            ref_dir / filename,
            api_key=_user_image_api_key(request),
        )
        meta[filename] = {"label": card["name"], "kind": "character_generated"}
        generated.append(card["name"])

    _save_ref_meta(ref_dir, meta)
    if generated:
        _check_and_consume_feature_quota(
            request,
            user.id,
            "manga.image.monthly_limit",
            len(generated),
            db,
            deduct=True,
            provider_kind="image",
        )
    return {
        "images": _serialize_refs(ref_dir, "story", story_id),
        "max": MAX_REF_IMAGES_PER_LEVEL,
        "generated": generated,
        "skipped": skipped,
    }


@app.get("/api/stories/{story_id}/ref-images")
async def list_story_ref_images(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    return {"images": _serialize_refs(ref_dir, "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


@app.post("/api/stories/{story_id}/ref-images")
async def add_story_ref_image(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    img_bytes = _decode_png_upload(body.get("image", ""))
    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    _save_uploaded_ref(ref_dir, img_bytes, "story ref image")
    return {"images": _serialize_refs(ref_dir, "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


@app.post("/api/stories/{story_id}/ref-images/{filename}/redraw")
async def redraw_story_ref_image(story_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    body = await request.json()
    prompt = str(body.get("prompt") or "").strip()
    mode = str(body.get("mode") or "full").strip().lower()
    path = _story_ref_dir(story_id) / filename
    if not path.exists():
        raise HTTPException(404, "reference image not found")
    try:
        _check_and_consume_feature_quota(request, user.id, "manga.regenerate.monthly_limit", 1, db, deduct=False, provider_kind="image")
        mask_bytes = None
        if mode == "partial":
            with Image.open(path) as img:
                mask_bytes = _decode_edit_mask_upload(str(body.get("mask") or ""), img.size)
        await edit_existing_image(prompt, path, path, mask_bytes=mask_bytes, api_key=_user_image_api_key(request))
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    _check_and_consume_feature_quota(request, user.id, "manga.regenerate.monthly_limit", 1, db, deduct=True, provider_kind="image")
    return {"images": _serialize_refs(_story_ref_dir(story_id), "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/stories/{story_id}/ref-images/{filename}")
async def delete_story_ref_image(story_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    p = _story_ref_dir(story_id) / filename
    _unlink_file(p, "story ref image")
    meta = _load_ref_meta(_story_ref_dir(story_id))
    if filename in meta:
        meta.pop(filename, None)
        _save_ref_meta(_story_ref_dir(story_id), meta)
    return {"images": _serialize_refs(_story_ref_dir(story_id), "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


# ─── Chapter-level multi ref images (with story fallback) ───

@app.get("/api/chapters/{chapter_id}/ref-images")
async def list_chapter_ref_images(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    ref_dir = _chapter_ref_dir(chapter_id)
    _migrate_legacy_ref(_legacy_chapter_ref_image(chapter_id), ref_dir)
    chapter_refs = _serialize_refs(ref_dir, "chapter", chapter_id)
    if chapter_refs:
        return {"images": chapter_refs, "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}
    story_dir = _story_ref_dir(chapter.story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(chapter.story_id), story_dir)
    story_refs = _serialize_refs(story_dir, "story", chapter.story_id)
    if story_refs:
        return {"images": story_refs, "source": "story", "max": MAX_REF_IMAGES_PER_LEVEL}
    return {"images": [], "source": "none", "max": MAX_REF_IMAGES_PER_LEVEL}


@app.post("/api/chapters/{chapter_id}/ref-images")
async def add_chapter_ref_image(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    img_bytes = _decode_png_upload(body.get("image", ""))
    ref_dir = _chapter_ref_dir(chapter_id)
    _migrate_legacy_ref(_legacy_chapter_ref_image(chapter_id), ref_dir)
    _save_uploaded_ref(ref_dir, img_bytes, "chapter ref image")
    return {"images": _serialize_refs(ref_dir, "chapter", chapter_id), "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}


@app.post("/api/chapters/{chapter_id}/ref-images/{filename}/redraw")
async def redraw_chapter_ref_image(chapter_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    body = await request.json()
    prompt = str(body.get("prompt") or "").strip()
    mode = str(body.get("mode") or "full").strip().lower()
    path = _chapter_ref_dir(chapter_id) / filename
    if not path.exists():
        raise HTTPException(404, "reference image not found")
    try:
        _check_and_consume_feature_quota(request, user.id, "manga.regenerate.monthly_limit", 1, db, deduct=False, provider_kind="image")
        mask_bytes = None
        if mode == "partial":
            with Image.open(path) as img:
                mask_bytes = _decode_edit_mask_upload(str(body.get("mask") or ""), img.size)
        await edit_existing_image(prompt, path, path, mask_bytes=mask_bytes, api_key=_user_image_api_key(request))
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    _check_and_consume_feature_quota(request, user.id, "manga.regenerate.monthly_limit", 1, db, deduct=True, provider_kind="image")
    return {"images": _serialize_refs(_chapter_ref_dir(chapter_id), "chapter", chapter_id), "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/chapters/{chapter_id}/ref-images/{filename}")
async def delete_chapter_ref_image(chapter_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    p = _chapter_ref_dir(chapter_id) / filename
    _unlink_file(p, "chapter ref image")
    meta = _load_ref_meta(_chapter_ref_dir(chapter_id))
    if filename in meta:
        meta.pop(filename, None)
        _save_ref_meta(_chapter_ref_dir(chapter_id), meta)
    return {"images": _serialize_refs(_chapter_ref_dir(chapter_id), "chapter", chapter_id), "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}


# ─── Color Mode ─────────────────────────────────────────────

def _color_mode_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "color_mode.txt"


def _load_color_mode(chapter_id: int) -> str:
    p = _color_mode_path(chapter_id)
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or "bw"
    return "bw"


def _save_color_mode(chapter_id: int, mode: str):
    p = _color_mode_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(mode, encoding="utf-8")


def _effective_color_mode(chapter_id: int, user_id: int, db: Session) -> str:
    stored_mode = _load_color_mode(chapter_id)
    if stored_mode == "color" and not _plan_feature_bool(user_id, "manga.allow_color_mode", db, default=False):
        return "bw"
    return stored_mode if stored_mode in ("bw", "color") else "bw"


@app.get("/api/chapters/{chapter_id}/color-mode")
async def get_color_mode(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    color_mode = _effective_color_mode(chapter_id, user.id, db)
    if color_mode != _load_color_mode(chapter_id):
        _save_color_mode(chapter_id, color_mode)
    return {"color_mode": color_mode}


@app.put("/api/chapters/{chapter_id}/color-mode")
async def set_color_mode(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    mode = body.get("color_mode", "bw")
    if mode not in ("bw", "color"):
        raise HTTPException(400, "color_mode must be 'bw' or 'color'")
    if mode == "color" and not _plan_feature_bool(user.id, "manga.allow_color_mode", db, default=False):
        raise HTTPException(403, "Current plan does not support color manga mode")
    _save_color_mode(chapter_id, mode)
    return {"ok": True}


# ─── Image Count ───────────────────────────────────────────

DEFAULT_IMAGE_COUNT = 10
ALLOWED_IMAGE_COUNTS = [4, 6, 8, 10, 12, 15, 20]


def _image_count_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "image_count.txt"


def _load_image_count(chapter_id: int) -> int:
    p = _image_count_path(chapter_id)
    if p.exists():
        try:
            v = int(p.read_text(encoding="utf-8").strip())
            if v in ALLOWED_IMAGE_COUNTS:
                return v
        except (ValueError, OSError):
            pass
    return DEFAULT_IMAGE_COUNT


def _max_image_count_for_user(user_id: int, db: Session) -> int:
    configured = _plan_feature_int(user_id, "manga.max_image_count_per_chapter", db, default=DEFAULT_IMAGE_COUNT)
    allowed_values = [value for value in ALLOWED_IMAGE_COUNTS if value <= configured]
    if allowed_values:
        return max(allowed_values)
    return min(ALLOWED_IMAGE_COUNTS)


def _effective_image_count(chapter_id: int, user_id: int, db: Session) -> int:
    stored = _load_image_count(chapter_id)
    return min(stored, _max_image_count_for_user(user_id, db))


def _chapter_has_scene_file(chapter_id: int) -> bool:
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        return False
    try:
        return bool(prompts_file.read_text(encoding="utf-8").strip())
    except OSError:
        return True


def _chapter_is_blank(chapter: Chapter) -> bool:
    return not chapter.messages and not chapter.images and not (chapter.novel_content or "").strip()


@app.get("/api/chapters/{chapter_id}/image-count")
async def get_image_count(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    image_count = _effective_image_count(chapter_id, user.id, db)
    if image_count != _load_image_count(chapter_id):
        p = _image_count_path(chapter_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(image_count), encoding="utf-8")
    return {"image_count": image_count}


@app.put("/api/chapters/{chapter_id}/image-count")
async def set_image_count(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if chapter.images or _chapter_has_scene_file(chapter_id):
        raise HTTPException(409, "Cannot change image count after scenes or images have been created")
    count = body.get("image_count", DEFAULT_IMAGE_COUNT)
    if count not in ALLOWED_IMAGE_COUNTS:
        raise HTTPException(400, f"image_count must be one of {ALLOWED_IMAGE_COUNTS}")
    max_allowed = _max_image_count_for_user(user.id, db)
    if count > max_allowed:
        raise HTTPException(403, f"Current plan allows at most {max_allowed} images per chapter")
    p = _image_count_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(count), encoding="utf-8")
    return {"ok": True}


# ─── Scene generation & management ───────────────────────

@app.post("/api/chapters/{chapter_id}/generate-scenes")
async def generate_scenes_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Generate scene prompts from chat history. Returns them for user review."""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if not chapter.messages:
        raise HTTPException(400, "No chat messages yet")

    image_count = _effective_image_count(chapter_id, user.id, db)
    chat_history = [{"role": m.role, "content": m.content} for m in chapter.messages]
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=False, provider_kind="text")
    split_task = asyncio.create_task(
        split_scenes(
            chat_history,
            character_profiles=_load_characters(chapter_id, db),
            page_count=image_count,
            api_key=_user_deepseek_api_key(request),
        )
    )
    try:
        while not split_task.done():
            if await request.is_disconnected():
                split_task.cancel()
                raise HTTPException(499, "Scene generation was cancelled")
            await asyncio.sleep(0.25)
        scenes = await split_task
        if await request.is_disconnected():
            raise HTTPException(499, "Scene generation was cancelled")
    except ValueError as exc:
        logger.warning("Failed to parse scene split response for chapter %s: %s", chapter_id, exc)
        raise HTTPException(502, "AI returned invalid scene JSON. Please retry generating scenes.")
    except asyncio.CancelledError:
        raise HTTPException(499, "Scene generation was cancelled")
    finally:
        if not split_task.done():
            split_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await split_task
    sanitized_scenes, sanitized_indices = sanitize_scene_list(scenes)
    _write_scenes_file(chapter_id, sanitized_scenes, sanitized_indices)
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=True, provider_kind="text")
    return {"scenes": sanitized_scenes, "sanitized_indices": sanitized_indices}


@app.get("/api/chapters/{chapter_id}/scenes")
async def get_scenes_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Load saved scene prompts from file."""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        return {"scenes": [], "sanitized_indices": []}
    if _chapter_is_blank(chapter):
        _rmtree_best_effort(_chapter_dir(chapter_id), "stale blank chapter workspace")
        return {"scenes": [], "sanitized_indices": []}
    try:
        raw = prompts_file.read_text(encoding="utf-8")
        parts = _parse_scenes_text(raw)
        meta = _load_scene_meta(chapter_id)
        if parts:
            _write_scenes_file(chapter_id, parts, meta.get("sanitized_indices", []))
        return {"scenes": parts, "sanitized_indices": meta.get("sanitized_indices", [])}
    except Exception:
        return {"scenes": [], "sanitized_indices": []}


@app.put("/api/chapters/{chapter_id}/scenes")
async def update_scenes_endpoint(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Save user-edited scene prompts."""
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    scenes = body.get("scenes", [])
    image_count = _effective_image_count(chapter_id, user.id, db)
    if not isinstance(scenes, list) or len(scenes) != image_count or not all(isinstance(s, str) and s.strip() for s in scenes):
        raise HTTPException(400, f"Must provide exactly {image_count} scenes")

    _write_scenes_file(chapter_id, scenes, [])
    return {"ok": True}


# ─── SSE for manga image generation ─────────────────────

@app.delete("/api/chapters/{chapter_id}/manga-images")
async def reset_manga_images(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if chapter_id in ACTIVE_MANGA_GENERATIONS:
        raise HTTPException(409, "Manga generation is already running for this chapter")
    _clear_chapter_images_only(chapter, db)
    db.commit()
    return {"ok": True}


@app.post("/api/chapters/{chapter_id}/generate-manga-stream")
async def generate_manga_stream(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # Load scenes from file (must exist - user should generate/confirm scenes first)
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        raise HTTPException(400, "No scene prompts found. Generate scenes first.")
    image_count = _effective_image_count(chapter_id, user.id, db)

    raw = prompts_file.read_text(encoding="utf-8")
    scenes = _parse_scenes_text(raw)
    if len(scenes) != image_count:
        if len(scenes) > image_count:
            raise HTTPException(403, f"Current plan allows at most {image_count} images per chapter. Please reduce page count or upgrade your plan.")
        raise HTTPException(400, f"Expected {image_count} scenes, found {len(scenes)}")
    if chapter_id in ACTIVE_MANGA_GENERATIONS:
        raise HTTPException(409, "Manga generation is already running for this chapter")
    _check_and_consume_feature_quota(request, user.id, "manga.image.monthly_limit", len(scenes), db, deduct=False, provider_kind="image")
    ACTIVE_MANGA_GENERATIONS.add(chapter_id)

    # Check which images already exist
    existing_images = {img.image_number: img for img in chapter.images}

    async def event_generator():
        try:
            yield {"event": "scenes", "data": json.dumps({"scenes": scenes}, ensure_ascii=False)}

            for i, scene_prompt in enumerate(scenes, start=1):
                # Skip already generated images
                if i in existing_images:
                    img = existing_images[i]
                    yield {
                        "event": "image",
                        "data": json.dumps({
                            "id": img.id,
                            "image_number": i,
                            "image_path": img.image_path,
                            "prompt": img.prompt or scene_prompt,
                        }, ensure_ascii=False),
                    }
                    continue

                yield {
                    "event": "progress",
                    "data": json.dumps({"current": i, "total": image_count, "prompt": scene_prompt}, ensure_ascii=False),
                }
                try:
                    ref_entries = _effective_ref_entries(chapter_id, db)
                    ref_imgs = _select_ref_image_paths_for_scene(scene_prompt, ref_entries)
                    image_result = await generate_manga_image(
                        scene_prompt,
                        chapter_id,
                        i,
                        all_scenes=scenes,
                        character_profiles=_load_characters(chapter_id, db),
                        ref_image_paths=[str(p) for p in ref_imgs] if ref_imgs else None,
                        color_mode=_effective_color_mode(chapter_id, user.id, db),
                        api_key=_user_image_api_key(request),
                    )
                    if image_result.prompt_sanitized and image_result.final_prompt != scene_prompt:
                        scenes[i - 1] = image_result.final_prompt
                        meta = _load_scene_meta(chapter_id)
                        sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [i - 1]))
                        _write_scenes_file(chapter_id, scenes, sanitized_indices)
                        scene_prompt = image_result.final_prompt
                except MangaImageGenerationError as img_err:
                    payload = img_err.to_payload()
                    payload["error"] = f"第{i}张生成失败: {payload['error']}"
                    payload["image_number"] = i
                    yield {"event": "error", "data": json.dumps(payload, ensure_ascii=False)}
                    return
                except Exception as img_err:
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": f"第{i}张生成失败: {str(img_err) or repr(img_err)}", "code": "unknown_error", "image_number": i}, ensure_ascii=False),
                    }
                    return

                manga = MangaImage(
                    chapter_id=chapter_id,
                    image_number=i,
                    image_path=image_result.image_path,
                    prompt=scene_prompt,
                )
                db.add(manga)
                db.commit()
                _check_and_consume_feature_quota(request, user.id, "manga.image.monthly_limit", 1, db, deduct=True, provider_kind="image")
                db.refresh(manga)
                yield {
                    "event": "image",
                    "data": json.dumps({
                        "id": manga.id,
                        "image_number": i,
                        "image_path": image_result.image_path,
                        "prompt": scene_prompt,
                    }, ensure_ascii=False),
                }

            yield {"event": "done", "data": json.dumps({"message": "漫画生成完成！"}, ensure_ascii=False)}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}
        finally:
            ACTIVE_MANGA_GENERATIONS.discard(chapter_id)

    return EventSourceResponse(event_generator(), ping=10)


# ─── Regenerate single image ─────────────────────────────

@app.post("/api/chapters/{chapter_id}/regenerate-image/{image_number}")
async def regenerate_single_image(chapter_id: int, image_number: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Regenerate or edit a single panel image."""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    image_count = _effective_image_count(chapter_id, user.id, db)
    if image_number < 1 or image_number > image_count:
        raise HTTPException(400, f"image_number must be 1-{image_count}")

    prompt = body.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    mode = str(body.get("mode") or "regenerate").strip().lower()

    # Load all scenes for context
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    all_scenes = None
    if prompts_file.exists():
        raw = prompts_file.read_text(encoding="utf-8")
        parts = _parse_scenes_text(raw)
        if len(parts) == image_count:
            # Update the scene in file
            parts[image_number - 1] = prompt
            all_scenes = parts
            _write_scenes_file(chapter_id, parts, _load_scene_meta(chapter_id).get("sanitized_indices", []))

    # Keep old DB/file intact until the new image is generated successfully.
    old_img = db.query(MangaImage).filter(
        MangaImage.chapter_id == chapter_id,
        MangaImage.image_number == image_number,
    ).first()
    old_path = Path(__file__).resolve().parent / old_img.image_path if old_img else None

    # Generate new image
    ref_entries = _effective_ref_entries(chapter_id, db)
    ref_imgs = _select_ref_image_paths_for_scene(prompt, ref_entries)
    try:
        _check_and_consume_feature_quota(request, user.id, "manga.regenerate.monthly_limit", 1, db, deduct=False, provider_kind="image")
        if mode in {"full", "partial"}:
            if not old_path or not old_path.exists():
                raise HTTPException(404, "source image not found")
            mask_bytes = None
            if mode == "partial":
                with Image.open(old_path) as img:
                    mask_bytes = _decode_edit_mask_upload(str(body.get("mask") or ""), img.size)
            chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            filename = f"panel_{image_number:02d}_{uuid.uuid4().hex[:8]}.png"
            output_path = chapter_dir / filename
            await edit_existing_image(
                prompt,
                old_path,
                output_path,
                mask_bytes=mask_bytes,
                api_key=_user_image_api_key(request),
            )
            image_result = image_service.ImageGenerationResult(
                image_path=f"manga_outputs/chapter_{chapter_id}/{filename}",
                final_prompt=prompt,
                prompt_sanitized=False,
            )
        else:
            image_result = await generate_manga_image(
                prompt,
                chapter_id,
                image_number,
                all_scenes=all_scenes,
                character_profiles=_load_characters(chapter_id, db),
                ref_image_paths=[str(p) for p in ref_imgs] if ref_imgs else None,
                color_mode=_effective_color_mode(chapter_id, user.id, db),
                api_key=_user_image_api_key(request),
            )
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    if image_result.prompt_sanitized and image_result.final_prompt != prompt and all_scenes and len(all_scenes) == image_count:
        all_scenes[image_number - 1] = image_result.final_prompt
        meta = _load_scene_meta(chapter_id)
        sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [image_number - 1]))
        _write_scenes_file(chapter_id, all_scenes, sanitized_indices)
        prompt = image_result.final_prompt

    if old_img:
        manga = old_img
        manga.image_path = image_result.image_path
        manga.prompt = prompt
    else:
        manga = MangaImage(
            chapter_id=chapter_id,
            image_number=image_number,
            image_path=image_result.image_path,
            prompt=prompt,
        )
        db.add(manga)
    db.commit()
    _check_and_consume_feature_quota(request, user.id, "manga.regenerate.monthly_limit", 1, db, deduct=True, provider_kind="image")
    db.refresh(manga)

    if old_path and old_path.exists() and old_path != Path(__file__).resolve().parent / image_result.image_path:
        try:
            old_path.unlink()
        except OSError as exc:
            logger.warning("Failed to delete old regenerated image %s: %s", old_path, exc)

    return {
        "id": manga.id,
        "image_number": image_number,
                        "image_path": image_result.image_path,
        "prompt": prompt,
    }


# ─── Framework (InkAI) ─────────────────────────────────────

@app.post("/api/stories/{story_id}/framework/generate")
async def generate_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    description = body.get("description", "")
    if not isinstance(description, str) or not description.strip():
        description = story.description or ""
    if not description.strip():
        raise HTTPException(400, "description is required")

    _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 1, db, deduct=False, provider_kind="text")
    framework = await generate_framework(description.strip(), api_key=_user_deepseek_api_key(request))
    framework = await _complete_framework_payload(
        framework,
        description.strip(),
        api_key=_user_deepseek_api_key(request),
    )

    story.description = description.strip()
    story.tags = framework.get("tags")
    story.characters = _normalize_characters_payload(framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
    db.commit()
    _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 1, db, deduct=True, provider_kind="text")
    db.refresh(story)
    return {
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
        "chapters": framework.get("chapters"),
    }


@app.post("/api/stories/{story_id}/framework/tags")
async def regenerate_tags_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    result = await regenerate_tags(story_context, api_key=_user_deepseek_api_key(request))

    tags = result if isinstance(result, dict) and "type" in result else result
    story.tags = tags
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {"tags": story.tags}


@app.post("/api/stories/{story_id}/framework/characters")
async def regenerate_characters_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    result = await regenerate_characters(story_context, api_key=_user_deepseek_api_key(request))

    characters = _normalize_characters_payload(result if isinstance(result, list) else result)
    story.characters = characters
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {"characters": story.characters}


@app.post("/api/stories/{story_id}/framework/outline")
async def regenerate_outline_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    result = await regenerate_outline(story_context, api_key=_user_deepseek_api_key(request))

    outline = result if isinstance(result, dict) and "three_acts" in result else result
    story.outline = _merge_framework_outline(story.outline, outline, _extract_outline_chapters(outline))
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {"outline": story.outline}


@app.post("/api/stories/{story_id}/framework/chapters/manual")
def update_outline_chapter_plan(story_id: int, body: OutlineChapterPlanUpdate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    mode = (body.mode or "").strip().lower()
    if mode not in {"append", "insert_after", "update"}:
        raise HTTPException(400, "Invalid mode")

    chapters = _extract_outline_chapters(story.outline)
    plan_map = {item["chapter_number"]: dict(item) for item in chapters}

    if mode == "update":
        target_number = body.target_chapter_number
        if not isinstance(target_number, int) or target_number < 1:
            raise HTTPException(400, "target_chapter_number is required for update")
        existing = plan_map.get(target_number)
        if not existing:
            raise HTTPException(404, "Planned chapter not found")
        fallback_title = existing.get("title") or f"Chapter {target_number}"
        fallback_act = str(existing.get("act") or _infer_manual_plan_act(chapters, target_chapter_number=target_number))
        normalized = _normalize_outline_plan_payload(body.chapter.model_dump(), fallback_title=fallback_title, fallback_act=fallback_act)
        existing.update(normalized)
        existing["chapter_number"] = target_number
        plan_map[target_number] = existing
        next_plans = [plan_map[key] for key in sorted(plan_map)]
    else:
        if mode == "append":
            after_number = max((item["chapter_number"] for item in chapters), default=0)
        else:
            after_number = body.after_chapter_number
            if not isinstance(after_number, int) or after_number < 1:
                raise HTTPException(400, "after_chapter_number is required for insert_after")
            if after_number not in plan_map:
                raise HTTPException(404, "Insert anchor chapter not found")

        new_number = after_number + 1
        fallback_act = _infer_manual_plan_act(chapters, after_chapter_number=after_number)
        normalized = _normalize_outline_plan_payload(
            body.chapter.model_dump(),
            fallback_title=f"Chapter {new_number}",
            fallback_act=fallback_act,
        )

        shifted_plans: list[dict] = []
        for item in chapters:
            current = dict(item)
            if current["chapter_number"] >= new_number:
                current["chapter_number"] += 1
            shifted_plans.append(current)

        _shift_story_chapter_numbers(story, new_number, 1)

        normalized["chapter_number"] = new_number
        shifted_plans.append(normalized)
        next_plans = sorted(shifted_plans, key=lambda item: item["chapter_number"])

    story.outline = _normalize_framework_outline(story.outline, next_plans)
    db.commit()
    db.refresh(story)
    return {"outline": story.outline}


@app.post("/api/stories/{story_id}/framework/adjust")
async def adjust_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    body = await request.json()
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "messages is required")

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    result = await adjust_framework_with_chat(
        _story_framework_context(story),
        messages,
        api_key=_user_deepseek_api_key(request),
    )

    framework = result.get("framework", {})
    description = str(framework.get("description") or story.description or "").strip()
    story.description = description
    story.tags = _merge_tags(story.tags, framework.get("tags"))
    story.characters = _merge_characters_payload(story.characters, framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {
        "reply": result.get("reply", ""),
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "chapters": framework.get("chapters"),
    }


@app.post("/api/stories/{story_id}/framework/continue")
async def continue_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    result = await continue_framework(
        _story_framework_context(story),
        api_key=_user_deepseek_api_key(request),
    )
    framework = result.get("framework", {})
    story.description = str(framework.get("description") or story.description or "").strip()
    story.tags = _merge_tags(story.tags, framework.get("tags"))
    story.characters = _merge_characters_payload(story.characters, framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {
        "reply": result.get("reply", ""),
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "chapters": framework.get("chapters"),
    }


@app.post("/api/stories/{story_id}/expand-chapter", response_model=ChapterOut)
async def expand_chapter_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    act = body.get("act", "")
    chapter_title = body.get("chapter_title", "")
    chapter_number_val = body.get("chapter_number")

    if not chapter_title or not isinstance(chapter_title, str) or not chapter_title.strip():
        raise HTTPException(400, "chapter_title is required")

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    chapter_info = {
        "title": chapter_title.strip(),
        "act": act if isinstance(act, str) else "",
        "chapter_number": chapter_number_val,
    }

    _check_and_consume_feature_quota(request, user.id, "chapter.expand.monthly_limit", 1, db, deduct=False, provider_kind="text")
    novel_content = await expand_chapter_to_content(
        story_context,
        chapter_info,
        api_key=_user_deepseek_api_key(request),
    )

    # Determine chapter number
    if isinstance(chapter_number_val, int) and chapter_number_val > 0:
        chapter_num = chapter_number_val
    else:
        max_num = (
            db.query(Chapter.chapter_number)
            .filter(Chapter.story_id == story_id)
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        chapter_num = (max_num[0] + 1) if max_num else 1

    existing = (
        db.query(Chapter)
        .filter(Chapter.story_id == story_id, Chapter.chapter_number == chapter_num)
        .first()
    )
    chapter = existing or Chapter(story_id=story_id, chapter_number=chapter_num)
    chapter.title = chapter_title.strip()
    chapter.content_source = "chat"
    chapter.act = act if isinstance(act, str) else None
    chapter.key_events = _normalize_key_events(body.get("key_events"))
    _apply_chapter_content(chapter, novel_content, status="completed")
    if existing is None:
        db.add(chapter)
        db.flush()
        _initialize_empty_chapter_workspace(chapter.id)
    db.add(ChatMessage(chapter_id=chapter.id, role="assistant", content=novel_content))
    db.commit()
    _check_and_consume_feature_quota(request, user.id, "chapter.expand.monthly_limit", 1, db, deduct=True, provider_kind="text")
    db.refresh(chapter)
    return chapter


@app.post("/api/chapters/{chapter_id}/rewrite-selection")
async def rewrite_selection_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    selected_text = body.get("selected_text", "")
    chapter_context = body.get("chapter_context", body.get("context", ""))

    if not isinstance(selected_text, str) or not selected_text.strip():
        raise HTTPException(400, "selected_text is required")
    if not isinstance(chapter_context, str):
        chapter_context = ""

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    rewritten = await rewrite_selection(
        selected_text.strip(),
        chapter_context.strip() or (chapter.novel_content or "")[:4000],
        api_key=_user_deepseek_api_key(request),
    )
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    return {"rewritten_text": rewritten}


@app.post("/api/chapters/{chapter_id}/adjust-content", response_model=ChapterOut)
async def adjust_chapter_content_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    instruction = body.get("instruction", "")

    if not isinstance(instruction, str) or not instruction.strip():
        raise HTTPException(400, "instruction is required")
    if not chapter.novel_content or not chapter.novel_content.strip():
        raise HTTPException(400, "Chapter has no novel content to adjust")

    chapter_info = {
        "title": chapter.title or f"第{chapter.chapter_number}话",
        "act": chapter.act or "",
        "chapter_number": chapter.chapter_number,
        "key_events": chapter.key_events or [],
    }
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    updated_content = await adjust_chapter_content(
        _story_framework_context(chapter.story),
        chapter_info,
        chapter.novel_content,
        instruction.strip(),
        api_key=_user_deepseek_api_key(request),
    )
    _apply_chapter_content(chapter, updated_content, status="completed")
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(chapter)
    return chapter


@app.post("/api/chapters/{chapter_id}/quality-assess")
async def quality_assess_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    content = chapter.novel_content or ""
    if not content.strip():
        raise HTTPException(400, "Chapter has no novel content to assess")

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    assessment = await quality_assess(content, api_key=_user_deepseek_api_key(request))

    chapter.quality_score = assessment.get("scores", assessment)
    if chapter.novel_content and chapter.novel_content.strip():
        chapter.status = "reviewed"
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(chapter)
    return assessment


@app.post("/api/chapters/{chapter_id}/scenes-from-selection")
async def scenes_from_selection_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    selected_text = body.get("selected_text", "")
    character_profiles = body.get("character_profiles", body.get("characters", ""))
    page_count = body.get("page_count", 4)

    if not isinstance(selected_text, str) or not selected_text.strip():
        raise HTTPException(400, "selected_text is required")
    if not isinstance(character_profiles, str):
        character_profiles = str(character_profiles) if character_profiles else ""
    if not isinstance(page_count, int) or page_count < 1:
        page_count = 4
    if page_count > 20:
        page_count = 20

    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=False, provider_kind="text")
    scenes = await scenes_from_selection(
        selected_text.strip(),
        character_profiles=character_profiles,
        page_count=page_count,
        api_key=_user_deepseek_api_key(request),
    )
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=True, provider_kind="text")
    sanitized_scenes, sanitized_indices = sanitize_scene_list(scenes)
    return {"scenes": sanitized_scenes, "page_count": page_count, "sanitized_indices": sanitized_indices}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
    )
