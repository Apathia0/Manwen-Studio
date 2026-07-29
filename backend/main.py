import asyncio
import calendar
import contextlib
import datetime
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import smtplib
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from services.writing_utils import build_chapter_generation_prompt
from services.framework_utils import (
    _build_current_snapshot_data,
    _build_outline_compact,
    _coerce_chapter_number,
    _count_framework_chapters,
    _enforce_framework_snapshot_limit,
    _extract_outline_chapters,
    _merge_chapter_plans,
    _merge_framework_outline,
    _normalize_act_token,
    _normalize_big_five_scores,
    _normalize_chapter_plan_meta,
    _normalize_characters_payload,
    _normalize_framework_outline,
    _normalize_key_events,
    _save_framework_snapshot,
    apply_framework_operations,
    restore_framework_snapshot,
    validate_applied_framework_consistency,
    validate_framework_json,
)
from urllib.parse import parse_qsl

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from sqlalchemy import case, func, and_, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask as ResponseBackgroundTask

from database import SessionLocal, get_db, init_db, engine as database_engine
from models import (
    AgentConversation,
    AgentConversationMessage,
    AgentPendingChange,
    AuditLog,
    BackgroundTask,
    BillingOrder,
    Chapter,
    ChapterVideoShot,
    ChapterVideoWorkflow,
    EmailVerificationCode,
    ChatMessage,
    DeconstructionResult,
    FrameworkSnapshot,
    MangaAsset,
    MangaAssetBinding,
    MangaImage,
    NovelSource,
    Plan,
    PlatformSetting,
    PointsAccount,
    PromptTemplate,
    RenderedClip,
    ScriptScene,
    ShotAssetBinding,
    Story,
    StoryCharacterVersion,
    StoryTemplateBinding,
    TemplateLike,
    User,
    UserSession,
    VideoAsset,
    VideoGenerationJob,
    VideoProject,
    VideoShot,
    VideoStylePreset,
)
from schemas import (
    ChapterContentUpdate,
    ChapterOut,
    ChatMessageIn,
    ChatMessageOut,
    CreativeBriefOut,
    FrameworkAnalyzeResponse,
    ImportChapterCreate,
    ImportChapterInfo,
    ImportCreateRequest,
    ImportParseResponse,
    MangaImageOut,
    MangaStoryboardImportCommitIn,
    MangaStoryboardImportPreviewIn,
    OnboardingConfirmIn,
    OnboardingMessageIn,
    OnboardingMessageOut,
    OutlineChapterPlanUpdate,
    StoryBibleUpdate,
    StoryCreate,
    StoryOut,
    StoryUpdate,
)
from services.task_manager import task_manager
from services.blocking import run_blocking
from services.install import (
    build_database_url,
    build_redis_url,
    create_install_engine,
    database_has_install_markers,
    detect_install_status,
    redact_url,
    request_backend_restart,
    test_database_url,
    test_redis_url,
    validate_install_admin_config,
    write_env_updates,
)

from services.deepseek import (
    adjust_chapter_content,
    adjust_framework_with_chat,
    analyze_import_material,
    analyze_content_framework,
    build_import_creative_brief,
    build_story_bible,
    chat_stream,
    continue_framework,
    continue_framework_with_chat,
    ChapterPipelineQualityError,
    expand_chapter_to_content,
    generate_character_profiles_from_framework,
    generate_character_profiles_from_content,
    generate_framework,
    generate_import_guidance_response,
    generate_onboarding_response,
    generate_novel,
    quality_assess,
    regenerate_characters_with_variance,
    regenerate_outline,
    regenerate_tags,
    rewrite_selection,
    scenes_from_selection,
    split_scenes,
    summarize_chapter_memory,
)
from services.errors import MangaImageGenerationError, MissingApiKeyError, public_error_message, sanitize_public_error_detail
from services.prompt_template import get_effective_prompt, get_system_prompt, set_system_prompt, get_template_story_length, SYSTEM_PROMPT_KEYS
from services.chapter_quality import finalize_generated_chapter_content, format_quality_gate_detail
from services.image2 import edit_existing_image, generate_cover_image, generate_manga_image
from services.media_locator import ensure_local_media_path
from services.scene_safety import sanitize_scene_list
from services.manga_storyboard_import import MAX_IMPORT_BYTES, decode_uploaded_file, parse_import_text
from services.manga_storyboard_storage import (
    atomic_write_text,
    canonical_scenes_hash,
    content_revision,
    parse_scenes_text as parse_stored_scenes_text,
    render_scenes_text,
    scenes_file_lock,
    scenes_path,
    write_scenes_text_atomic,
)
from services.visual_asset_generation import (
    generate_visual_asset_image,
    label_matches_visual_context,
    normalize_visual_role,
    select_visual_references,
)
from services.visual_asset_prompts import analyze_visual_assets
from services import deepseek as deepseek_service
from services import image2 as image_service
from services import license_checker
from services.payment import init_gateways, get_gateway, get_gateway_by_provider, get_method_options
from services.story_state import build_story_bible_compact, build_story_memory_compact, extract_author_profile_sections, extract_report_highlights
from routers.video import router as video_router
from routers.deconstruction import router as deconstruction_router
from routers.deconstruct_library import router as deconstruct_library_router

load_dotenv()

logger = logging.getLogger("main")
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("watchfiles.watcher").setLevel(logging.WARNING)
ACTIVE_MANGA_GENERATIONS: set[int] = set()
MONEY_QUANT = Decimal("0.01")
AUTO_MANGA_ASSET_ANALYSIS_VERSION = 2
AUTO_MANGA_ASSET_CONCURRENCY = max(1, min(4, int(os.getenv("AUTO_MANGA_ASSET_CONCURRENCY", "2") or "2")))
AUTO_MANGA_ASSET_START_INTERVAL_SECONDS = max(
    0,
    min(30, int(os.getenv("AUTO_MANGA_ASSET_START_INTERVAL_SECONDS", "3") or "3")),
)


def _default_reload_enabled() -> bool:
    env_value = os.getenv("RELOAD")
    if env_value is not None:
        return env_value.lower() == "true"
    return os.name != "nt"

# 旧套餐配额系统已移除 — 改用积分双轨（platform / user_key）


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 — 替代废弃的 @app.on_event('startup') 语法"""
    global SYSTEM_READY

    # ── 启动：数据库初始化 ──
    status = _refresh_install_status()
    if not status.get("installed"):
        logger.info("System is not installed; startup database initialization is skipped.")
        yield
        return

    if str(os.getenv("APP_ENV") or "").strip().lower() in {"production", "prod"}:
        from services.ai.crypto_secrets import get_secret_key_material

        get_secret_key_material()

    try:
        init_db(raise_errors=True)
    except Exception as exc:
        SYSTEM_READY = False
        logger.warning("Startup database initialization skipped: %s", exc)
        yield
        return

    db = SessionLocal()
    try:
        _hash_legacy_session_tokens(db)
        _encrypt_legacy_platform_secrets(db)
        db.commit()
        # 同步写作 Prompt 到数据库（每次启动自动同步代码中的最新版本）
        _ensure_framework_prompt_synced(db)

        for s in db.query(Story).filter(Story.title.in_(["我的第一个故事", "未命名故事"])).all():
            if s.chapters and any(ch.messages for ch in s.chapters):
                s.title = "转生成为暗恋公主的女仆故事"
                s.description = "百合女仆与公主的奇幻冒险"
        db.commit()
        try:
            from services.creation_studio import fail_interrupted_creation_studio_jobs

            interrupted_count = fail_interrupted_creation_studio_jobs(db)
            if interrupted_count:
                logger.warning("已终止 %s 个因服务重启中断的创作台任务", interrupted_count)
        except Exception as exc:
            logger.warning("创作台中断任务清理失败: %s", exc)
        interrupted_task_count = task_manager.fail_interrupted_tasks()
        if interrupted_task_count:
            logger.warning("已终止 %s 个因服务重启中断的后台任务", interrupted_task_count)
        SYSTEM_READY = True
        try:
            init_gateways()
        except Exception as exc:
            logger.warning("Payment gateway initialization failed: %s", exc)
    except Exception as exc:
        SYSTEM_READY = False
        logger.warning("Startup database maintenance skipped: %s", exc)
    finally:
        db.close()

    # ── 启动：定时清理后台任务 ──
    async def cleanup_loop():
        while True:
            try:
                cleaned = task_manager.cleanup_stale_tasks(max_age_hours=24)
                if cleaned > 0:
                    logger.info("Cleaned up %d stale tasks", cleaned)
            except Exception as e:
                logger.error("Task cleanup failed: %s", e)
            await asyncio.sleep(3600)

    cleanup_task = asyncio.create_task(cleanup_loop())

    yield  # 应用在此运行

    # ── 关闭：取消后台清理任务 ──
    cleanup_task.cancel()


app = FastAPI(title="Novel & Manga Generator", lifespan=lifespan)

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
MAX_CHARACTER_PROFILE_CHARS = int(os.getenv("MAX_CHARACTER_PROFILE_CHARS", "20000"))
API_TOKEN = os.getenv("API_TOKEN", "").strip()
UPDATER_URL = os.getenv("UPDATER_URL", "http://updater:8090").strip().rstrip("/")
UPDATER_TOKEN = os.getenv("UPDATER_TOKEN", "").strip()
UPDATER_TIMEOUT_SECONDS = float(os.getenv("UPDATER_TIMEOUT_SECONDS", "10"))
UPDATER_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|KEY)[A-Z0-9_]*)=([^\s]+)")
URL_WITH_PASSWORD_RE = re.compile(r"(?i)\b((?:postgresql|postgres|redis|rediss)://[^:\s/@]+:)([^@\s]+)(@[^ \t\r\n]+)")
INSTALL_API_PREFIX = "/api/install"
HEALTH_API_PATH = "/api/health"
INSTALL_STATUS: dict[str, Any] = {
    "installed": False,
    "source": "unknown",
    "database_reachable": None,
}
INSTALL_REQUIRES_RESTART = False
SYSTEM_READY = False


def _is_install_api_path(path: str) -> bool:
    return path == INSTALL_API_PREFIX or path.startswith(f"{INSTALL_API_PREFIX}/")


def _is_public_runtime_api_path(path: str) -> bool:
    return _is_install_api_path(path) or path == HEALTH_API_PATH


def _refresh_install_status() -> dict[str, Any]:
    global INSTALL_STATUS
    if INSTALL_REQUIRES_RESTART:
        INSTALL_STATUS = {
            "installed": True,
            "source": "installer",
            "database_reachable": True,
            "requires_restart": True,
        }
        return INSTALL_STATUS
    INSTALL_STATUS = detect_install_status(database_engine)
    return INSTALL_STATUS


def _system_installed() -> bool:
    return bool(INSTALL_STATUS.get("installed")) and not bool(INSTALL_STATUS.get("requires_restart")) and SYSTEM_READY


@app.get("/api/health")
def health_check():
    status = _refresh_install_status()
    installed = bool(status.get("installed"))
    requires_restart = bool(status.get("requires_restart"))
    database_reachable = status.get("database_reachable")
    base_payload = {
        "version": os.getenv("APP_VERSION", "dev"),
        "installed": installed,
        "requires_restart": requires_restart,
        "system_ready": SYSTEM_READY,
    }
    if not installed:
        payload = {
            "ok": database_reachable is not False,
            "ready": False,
            "database_reachable": database_reachable,
            **base_payload,
        }
        if database_reachable is False:
            return JSONResponse(status_code=503, content=payload)
        return payload
    if requires_restart:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "ready": False,
                "database_reachable": database_reachable,
                **base_payload,
            },
        )
    if database_reachable is None:
        try:
            with database_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            database_reachable = True
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                "ok": False,
                    "ready": False,
                "database_reachable": database_reachable,
                "database_error": str(exc),
                    **base_payload,
                },
            )
    ok = database_reachable is not False and SYSTEM_READY
    payload = {
        "ok": ok,
        "ready": ok,
        "database_reachable": database_reachable,
        **base_payload,
    }
    if not ok:
        return JSONResponse(status_code=503, content=payload)
    return {
        **payload,
    }

# 未授权域名时显示的 HTML 页面模板
_UNAUTHORIZED_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>域名未授权 - StoryCanvas</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#fff;border-radius:20px;padding:40px;max-width:520px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.3);text-align:center}}
.icon{{font-size:64px;margin-bottom:20px}}
h1{{font-size:24px;color:#333;margin-bottom:12px}}
p{{color:#666;line-height:1.6;margin-bottom:8px;font-size:14px}}
.domain{{background:#f8f9fa;padding:10px 16px;border-radius:8px;font-family:monospace;font-size:16px;color:#667eea;margin:16px 0;word-break:break-all}}
.btn{{display:inline-block;padding:12px 32px;border-radius:25px;text-decoration:none;font-weight:600;font-size:15px;margin:8px 4px;transition:transform .2s}}
.btn-primary{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff}}
.btn-primary:hover{{transform:translateY(-2px);box-shadow:0 5px 15px rgba(102,126,234,.4)}}
.footer{{margin-top:24px;padding-top:16px;border-top:1px solid #eee;font-size:12px;color:#999}}
</style>
</head>
<body>
<div class="card">
<div class="icon">🔒</div>
<h1>域名未授权</h1>
<p>当前域名 <strong>{hostname}</strong> 尚未获得授权。</p>
<div class="domain">{hostname}</div>
<p>请联系管理员获取授权码，或前往授权页面完成授权。</p>
<p style="font-size:12px;color:#999;margin-top:12px">授权完成后，系统将自动解除限制。</p>
<div style="margin-top:20px">
{{button_html}}
</div>
<div class="footer">StoryCanvas — AI 小说创作平台</div>
</div>
</body>
</html>"""

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def license_check_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith(("/static/",)) or _is_public_runtime_api_path(path) or request.method == "OPTIONS":
        return await call_next(request)

    host_header = request.headers.get("host", "")
    hostname = host_header.split(":")[0].strip().lower()
    if not hostname or license_checker.is_dev_domain(hostname):
        return await call_next(request)

    if not license_checker.check_domain(hostname):
        auth_url = license_checker.get_auth_page_url()
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "域名未授权，请联系管理员",
                    "message": f"当前域名 {hostname} 未获得授权，无法提供服务",
                    "authorized": False,
                    "auth_url": auth_url,
                },
            )
        return HTMLResponse(
            status_code=403,
            content=_UNAUTHORIZED_HTML.format(hostname=hostname, button_html=(
                f'<a class="btn btn-primary" href="{auth_url}" target="_blank">前往授权页面</a>'
            )),
        )

    return await call_next(request)


@app.exception_handler(MissingApiKeyError)
async def _missing_api_key_handler(request: Request, exc: MissingApiKeyError):
    return JSONResponse(
        status_code=400,
        content={"detail": public_error_message(exc, "AI 服务配置缺失，请联系管理员"), "provider": exc.provider},
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    """统一清洗路由错误，避免向前端暴露英文上游异常和内部信息。"""
    detail = exc.detail
    if isinstance(detail, str):
        source = detail if any("\u4e00" <= char <= "\u9fff" for char in detail) else f"HTTP {exc.status_code}: {detail}"
        detail = public_error_message(
            source,
            "请求处理失败，请稍后重试",
        )
    else:
        detail = sanitize_public_error_detail(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=exc.headers,
    )


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError):
    """将业务校验错误统一转换为可读的 400 响应。"""
    detail = public_error_message(exc, "请求参数不合法，请检查后重试")
    return JSONResponse(
        status_code=400,
        content={"detail": detail},
    )


class GeneratedMediaStaticFiles(StaticFiles):
    """公开旧媒体目录，但强制隔离创作台的鉴权素材。"""

    async def get_response(self, path: str, scope):
        normalized = os.path.normpath(f"/{path}").replace("\\", "/").lstrip("/")
        if normalized in {"creative_studio", "agent_attachments"} or normalized.startswith(("creative_studio/", "agent_attachments/")):
            return Response(status_code=404)
        return await super().get_response(path, scope)


# Serve generated manga images as static files
manga_dir = Path(__file__).resolve().parent / "manga_outputs"
manga_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/manga", GeneratedMediaStaticFiles(directory=str(manga_dir)), name="manga")

# Serve downloaded videos as static files
video_dir = Path(__file__).resolve().parent / "video_outputs"
video_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/video", GeneratedMediaStaticFiles(directory=str(video_dir)), name="video")


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    normalized_path = "/" + "/".join(part for part in request.url.path.split("/") if part)
    if normalized_path.startswith(("/static/manga/creative_studio/", "/static/manga/agent_attachments/", "/static/video/creative_studio/")):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if API_TOKEN and request.url.path.startswith("/api") and not _is_public_runtime_api_path(request.url.path) and request.method != "OPTIONS":
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
    if _is_public_runtime_api_path(request.url.path):
        return await call_next(request)
    if request.url.path.startswith("/api") and not _system_installed():
        return JSONResponse({"detail": "System is not installed", "installed": False}, status_code=503)
    db = SessionLocal()
    db.info["request"] = request
    request.state.db = db
    response = None
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            _refund_request_points_charges(request, db, error_code=f"http_{response.status_code}")
        return response
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        _refund_request_points_charges(request, db, error_code="request_failed")
        raise
    finally:
        with contextlib.suppress(Exception):
            db.rollback()
        _release_request_points_reservations(request, db)
        db.info.pop("request", None)
        db.close()


def _require_chapter(chapter_id: int, db: Session) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "章节未找到")
    return chapter


def _get_platform_setting(key: str, db: Session, default=None):
    setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if not setting:
        return default
    payload = setting.value_json or {}
    if key in SENSITIVE_PLATFORM_SETTING_KEYS and payload.get("ciphertext"):
        from services.ai.crypto_secrets import decrypt_secret

        return decrypt_secret(str(payload["ciphertext"]))
    return payload.get("value", default)


SENSITIVE_PLATFORM_SETTING_KEYS = {
    "api.deepseek.api_key",
    "api.image.api_key",
    "api.video.api_key",
    "oss.access_key_id",
    "oss.access_key_secret",
    "email.smtp_password",
    "payment.alipay_app_private_key",
    "payment.epay_key",
    "payment.mapay_key",
}


def _set_platform_setting(key: str, value, db: Session, *, clear_secret: bool = False) -> None:
    setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if key in SENSITIVE_PLATFORM_SETTING_KEYS:
        plain = str(value or "").strip()
        if not plain and setting and not clear_secret:
            return
        if plain:
            from services.ai.crypto_secrets import encrypt_secret, last_four

            payload = {
                "ciphertext": encrypt_secret(plain),
                "encrypted": True,
                "last_four": last_four(plain),
            }
        else:
            payload = {"ciphertext": "", "encrypted": True, "last_four": ""}
        if setting:
            setting.value_json = payload
        else:
            db.add(PlatformSetting(setting_key=key, value_json=payload))
        return
    if setting:
        setting.value_json = {"value": value}
    else:
        db.add(PlatformSetting(setting_key=key, value_json={"value": value}))


def _encrypt_legacy_platform_secrets(db: Session) -> None:
    for key in SENSITIVE_PLATFORM_SETTING_KEYS:
        setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
        if not setting:
            continue
        payload = setting.value_json or {}
        if payload.get("ciphertext"):
            continue
        legacy_value = str(payload.get("value") or "").strip()
        if legacy_value:
            _set_platform_setting(key, legacy_value, db)


def _admin_platform_settings_snapshot(db: Session) -> dict:
    snapshot = _platform_settings_snapshot(db)
    field_map = {
        "api.deepseek.api_key": ("api", "deepseek_api_key"),
        "api.image.api_key": ("api", "image_api_key"),
        "api.video.api_key": ("api", "video_api_key"),
        "oss.access_key_id": ("api", "oss_access_key_id"),
        "oss.access_key_secret": ("api", "oss_access_key_secret"),
        "email.smtp_password": ("email", "smtp_password"),
        "payment.alipay_app_private_key": ("payment", "alipay_app_private_key"),
        "payment.epay_key": ("payment", "epay_key"),
        "payment.mapay_key": ("payment", "mapay_key"),
    }
    for setting_key, (section, field) in field_map.items():
        row = db.query(PlatformSetting).filter(PlatformSetting.setting_key == setting_key).first()
        payload = row.value_json if row and isinstance(row.value_json, dict) else {}
        current = str(snapshot.get(section, {}).get(field) or "")
        snapshot[section][field] = ""
        snapshot[section][f"{field}_configured"] = bool(payload.get("ciphertext") or current)
        snapshot[section][f"{field}_last_four"] = str(payload.get("last_four") or current[-4:] or "")
    return snapshot


def _configure_oss_from_db(db: Session) -> None:
    from services import oss as oss_service
    enabled = bool(_get_platform_setting("oss.enabled", db, False))
    access_key_id = str(_get_platform_setting("oss.access_key_id", db, "") or "").strip()
    access_key_secret = str(_get_platform_setting("oss.access_key_secret", db, "") or "").strip()
    endpoint = str(_get_platform_setting("oss.endpoint", db, "") or "").strip()
    bucket = str(_get_platform_setting("oss.bucket", db, "") or "").strip()
    public_url_base = str(_get_platform_setting("oss.public_url_base", db, "") or "").strip()
    oss_service.configure(
        enabled=enabled,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint=endpoint,
        bucket=bucket,
        public_url_base=public_url_base,
    )


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
            "deepseek_base_url": _get_platform_setting("api.deepseek.base_url", db, deepseek_service.DEEPSEEK_BASE_URL),
            "deepseek_model": _get_platform_setting("api.deepseek.model", db, deepseek_service.DEEPSEEK_MODEL),
            "deepseek_api_key": _get_platform_setting("api.deepseek.api_key", db, ""),
            "image_base_url": _get_platform_setting("api.image.base_url", db, "https://newapi.aifusion6.cn/v1"),
            "image_model": _get_platform_setting("api.image.model", db, "default"),
            "image_api_key": _get_platform_setting("api.image.api_key", db, ""),
            "image_size": _get_platform_setting("api.image.size", db, ""),
            "image_quality": _get_platform_setting("api.image.quality", db, ""),
            "image_background": _get_platform_setting("api.image.background", db, ""),
            "image_moderation": _get_platform_setting("api.image.moderation", db, ""),
            "image_output_format": _get_platform_setting("api.image.output_format", db, ""),
            "image_output_compression": _get_platform_setting("api.image.output_compression", db, ""),
            "image_input_fidelity": _get_platform_setting("api.image.input_fidelity", db, ""),
            "video_base_url": _get_platform_setting("api.video.base_url", db, "https://newapi.aifusion6.cn/v1"),
            "video_model": _get_platform_setting("api.video.model", db, "veo3.1-fast"),
            "video_api_key": _get_platform_setting("api.video.api_key", db, ""),
            "video_provider": _get_platform_setting("api.video.provider", db, ""),
            "enable_user_override": bool(_get_platform_setting("api.enable_user_override", db, True)),
            "allow_all_users_api_key_override": bool(
                _get_platform_setting("api.allow_all_users_api_key_override", db, False)
            ),
            "enable_user_url_override": bool(_get_platform_setting("api.enable_user_url_override", db, False)),
            "oss_enabled": bool(_get_platform_setting("oss.enabled", db, False)),
            "oss_access_key_id": _get_platform_setting("oss.access_key_id", db, ""),
            "oss_access_key_secret": _get_platform_setting("oss.access_key_secret", db, ""),
            "oss_endpoint": _get_platform_setting("oss.endpoint", db, ""),
            "oss_bucket": _get_platform_setting("oss.bucket", db, ""),
            "oss_public_url_base": _get_platform_setting("oss.public_url_base", db, ""),
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
        "pricing": {
            "quota_framework_generate": float(_get_platform_setting("pricing.quota.framework.generate.monthly_limit", db, 1.0) or 1.0),
            "quota_chapter_expand": float(_get_platform_setting("pricing.quota.chapter.expand.monthly_limit", db, 0.5) or 0.5),
            "quota_scene_generate": float(_get_platform_setting("pricing.quota.scene.generate.monthly_limit", db, 0.3) or 0.3),
            "quota_manga_image_generate": float(_get_platform_setting("pricing.quota.manga.image.generate.monthly_limit", db, 0.2) or 0.2),
            "quota_ai_text_advanced": float(_get_platform_setting("pricing.quota.ai.text.advanced_calls.monthly_limit", db, 0.3) or 0.3),
            "quota_deconstruction_run": float(_get_platform_setting("pricing.quota.deconstruction.run.monthly_limit", db, 3.0) or 3.0),
            "quota_video_shot_split": float(_get_platform_setting("pricing.quota.video.shot.split.monthly_limit", db, 1.0) or 1.0),
            "quota_video_generate": float(_get_platform_setting("pricing.quota.video.generate.count.monthly_limit", db, 2.0) or 2.0),
        },
        "payment": {
            "enabled": bool(_get_platform_setting("payment.enabled", db, True)),
            "default_method": str(_get_platform_setting("payment.default_method", db, "mock_qr")),
            "order_expire_minutes": int(_get_platform_setting("payment.order_expire_minutes", db, 30) or 30),
            "auto_activate_free_plan": bool(_get_platform_setting("payment.auto_activate_free_plan", db, True)),
            "instructions": str(_get_platform_setting("payment.instructions", db, "") or ""),
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
            "epay_enabled": bool(_get_platform_setting("payment.epay_enabled", db, False)),
            "epay_gateway": str(_get_platform_setting("payment.epay_gateway", db, "") or ""),
            "epay_pid": str(_get_platform_setting("payment.epay_pid", db, "") or ""),
            "epay_key": str(_get_platform_setting("payment.epay_key", db, "") or ""),
            "epay_type": str(_get_platform_setting("payment.epay_type", db, "alipay") or "alipay"),
            "epay_notify_url": str(_get_platform_setting("payment.epay_notify_url", db, "") or ""),
            "epay_return_url": str(_get_platform_setting("payment.epay_return_url", db, "") or ""),
            "mapay_enabled": bool(_get_platform_setting("payment.mapay_enabled", db, False)),
            "mapay_gateway": str(_get_platform_setting("payment.mapay_gateway", db, "https://pay.21lili.cn") or ""),
            "mapay_pid": str(_get_platform_setting("payment.mapay_pid", db, "") or ""),
            "mapay_key": str(_get_platform_setting("payment.mapay_key", db, "") or ""),
            "mapay_type": str(_get_platform_setting("payment.mapay_type", db, "alipay") or "alipay"),
            "mapay_notify_url": str(_get_platform_setting("payment.mapay_notify_url", db, "") or ""),
            "mapay_return_url": str(_get_platform_setting("payment.mapay_return_url", db, "") or ""),
        },
    }


def _payment_settings_snapshot(db: Session) -> dict:
    return _platform_settings_snapshot(db)["payment"]


def _mock_payments_enabled() -> bool:
    """模拟支付必须由部署环境显式开启。"""
    return str(os.getenv("ALLOW_MOCK_PAYMENTS") or "").strip().lower() in {"1", "true", "yes", "on"}


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
            "video_base_url": api.get("video_base_url") or "https://newapi.aifusion6.cn/v1",
            "video_model": api.get("video_model") or "veo3.1-fast",
            "video_provider": api.get("video_provider") or "",
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
    return get_method_options(payment)


def _public_payment_config(db: Session) -> dict:
    payment = _payment_settings_snapshot(db)
    return {
        "enabled": bool(payment.get("enabled")),
        "default_method": str(payment.get("default_method") or "mock_qr"),
        "order_expire_minutes": int(payment.get("order_expire_minutes") or 30),
        "instructions": str(payment.get("instructions") or ""),
        "methods": _payment_method_options(db),
    }


def _user_api_override_capabilities(user: User | None, db: Session) -> dict[str, bool]:
    key_global = bool(_get_platform_setting("api.enable_user_override", db, True))
    key_allowed_for_all_users = bool(
        _get_platform_setting("api.allow_all_users_api_key_override", db, False)
    )
    url_global = bool(_get_platform_setting("api.enable_user_url_override", db, False))
    return {
        "can_override_api_key": key_global
        and user is not None
        and (key_allowed_for_all_users or bool(user.allow_api_key_override)),
        "can_override_api_url": url_global and bool(user and user.allow_api_url_override),
    }


def _resolve_user_upstream_override(
    request: Request,
    db: Session,
    *,
    user: User,
    modality: str,
    mode: str,
    api_key_override: str | None = None,
) -> dict | None:
    header_names = {
        "text": ("x-deepseek-base-url", "x-deepseek-model"),
        "image": ("x-image-base-url", "x-image-model"),
        "video": ("x-video-base-url", "x-video-model"),
    }
    names = header_names.get(modality)
    if not names:
        return None
    raw_base_url = (request.headers.get(names[0]) or "").strip()
    raw_model = (request.headers.get(names[1]) or "").strip()
    if not raw_base_url and not raw_model:
        return None

    capabilities = _user_api_override_capabilities(user, db)
    if not capabilities["can_override_api_url"]:
        return None
    if mode != "user_key":
        raise HTTPException(400, "自定义 URL/模型仅能在「我的 Key」模式使用")
    if len(raw_model) > 200 or any(char in raw_model for char in "\r\n\0"):
        raise HTTPException(400, "自定义模型名称不合法")

    from services.ai.channels import validate_user_base_url
    from services.ai.credentials import load_user_api_key_plain

    api_key = (api_key_override or "").strip() or load_user_api_key_plain(db, user.id, modality)
    if not api_key:
        raise HTTPException(403, "请先在用户中心配置 API Key，再使用自定义上游")
    return {
        "base_url": validate_user_base_url(raw_base_url) if raw_base_url else None,
        "model_key": raw_model or None,
        "api_key": api_key,
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
    has_custom_key = capabilities["can_override_api_key"] and bool((request.headers.get("x-deepseek-api-key") or "").strip())
    has_custom_url = capabilities["can_override_api_url"] and bool((request.headers.get("x-deepseek-base-url") or "").strip())
    return has_custom_key or has_custom_url


def _custom_image_provider_active(request: Request) -> bool:
    db = getattr(request.state, "db", None)
    if db is None:
        return False
    dual = getattr(request.state, "dual_track_image", None)
    if isinstance(dual, dict):
        return dual.get("mode") == "user_key"
    header_mode = (request.headers.get("x-credential-mode") or "").strip().lower()
    if header_mode == "platform":
        return False
    user = getattr(request.state, "current_user", None)
    if header_mode != "user_key" and user is not None:
        try:
            from models import UserAiPreference

            pref = db.query(UserAiPreference).filter(UserAiPreference.user_id == user.id).first()
            if pref and pref.credential_mode == "platform":
                return False
            if pref and pref.credential_mode == "user_key":
                return True
        except Exception:
            pass
    capabilities = _user_api_override_capabilities(user, db)
    has_custom_key = capabilities["can_override_api_key"] and bool((request.headers.get("x-image-api-key") or "").strip())
    has_custom_url = capabilities["can_override_api_url"] and bool((request.headers.get("x-image-base-url") or "").strip())
    return has_custom_key or has_custom_url


def _points_dual_track_enabled(db: Session) -> bool:
    try:
        return bool(_get_platform_setting("points.dual_track_enabled", db, True))
    except Exception:
        return True


def _request_credential_mode(request: Request, db: Session) -> str:
    header_mode = (request.headers.get("x-credential-mode") or "").strip().lower()
    if header_mode in {"platform", "user_key"}:
        return header_mode
    user = getattr(request.state, "current_user", None)
    if user is not None:
        try:
            from models import UserAiPreference

            pref = db.query(UserAiPreference).filter(UserAiPreference.user_id == user.id).first()
            if pref and pref.credential_mode in {"platform", "user_key"}:
                return pref.credential_mode
        except Exception:
            pass
    if _custom_text_provider_active(request) or _custom_image_provider_active(request):
        return "user_key"
    return "platform"


def _feature_key_to_modality(feature_key: str) -> str:
    key = (feature_key or "").lower()
    if "video" in key:
        return "video"
    if "manga" in key or "image" in key:
        return "image"
    return "text"


def _check_and_consume_feature_quota(
    request: Request,
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    *,
    deduct: bool,
    provider_kind: str | None = None,
    reserve: bool = True,
) -> dict:
    """积分双轨配额检查与扣费 — 旧套餐配额系统已移除"""
    mode = _request_credential_mode(request, db)
    modality = provider_kind if provider_kind in {"text", "image", "video"} else _feature_key_to_modality(feature_key)
    charge = None
    if not deduct and modality == "text":
        from services.deepseek import reset_usage_accumulator

        reset_usage_accumulator()
    if mode == "platform":
        if deduct:
            charge = _settle_pending_platform_points(
                request,
                db,
                user_id=user_id,
                task_type=feature_key,
                modality=modality,
            ) or _charge_platform_points_immediate(
                request,
                db,
                user_id=user_id,
                task_type=feature_key,
                modality=modality,
                units=max(1, int(amount or 1)),
            )
        elif reserve:
            if modality == "text":
                _check_platform_points_available(
                    request,
                    db,
                    user_id=user_id,
                    task_type=feature_key,
                    modality=modality,
                    units=max(1, int(amount or 1)),
                )
            charge = _charge_platform_points_immediate(
                request,
                db,
                user_id=user_id,
                task_type=feature_key,
                modality=modality,
                units=max(1, int(amount or 1)),
                settle=False,
                streaming=modality == "text",
            )
        else:
            _check_platform_points_available(
                request,
                db,
                user_id=user_id,
                task_type=feature_key,
                modality=modality,
                units=max(1, int(amount or 1)),
            )
    return {
        "skipped": True,
        "reason": "points_dual_track",
        "credential_mode": mode,
        "feature_key": feature_key,
        "points_charged": float(charge.get("amount") or 0) if charge else 0,
        "usage_event_id": charge.get("usage_event_id") if charge else None,
        "billing_request_id": charge.get("request_id") if charge else None,
    }


def _resolve_dual_track_runtime(request: Request, db: Session, *, modality: str) -> dict | None:
    if not _points_dual_track_enabled(db):
        return None
    try:
        from services.ai.channels import load_platform_key
        from services.ai.credentials import load_user_api_key_plain
        from services.ai.resolver import resolve_credential_mode, resolve_model
        from models import AiChannel

        user = getattr(request.state, "current_user", None)
        if user is None:
            return None
        mode = resolve_credential_mode(db, user.id, _request_credential_mode(request, db))
        custom_upstream = _resolve_user_upstream_override(
            request,
            db,
            user=user,
            modality=modality,
            mode=mode,
        )
        model_header = None
        if modality == "text":
            model_header = request.headers.get("x-ai-model-id") or request.headers.get("x-deepseek-model-id")
        elif modality == "image":
            model_header = request.headers.get("x-ai-model-id") or request.headers.get("x-image-model-id")
        elif modality == "video":
            model_header = request.headers.get("x-ai-model-id") or request.headers.get("x-video-model-id")
        model_id = int(model_header) if model_header and str(model_header).isdigit() else None
        model = resolve_model(
            db,
            user.id,
            modality=modality,
            model_id=model_id,
            task_type=None,
            selection_policy="interactive_strict",
        )
        channel = db.get(AiChannel, model.channel_id)
        if not channel or not channel.enabled:
            return None
        base_url = ((custom_upstream or {}).get("base_url") or channel.base_url or "").rstrip("/")
        resolved_model_key = (custom_upstream or {}).get("model_key") or model.model_key
        if mode == "user_key":
            capabilities = _user_api_override_capabilities(user, db)
            if not custom_upstream and not capabilities["can_override_api_key"]:
                raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")
            api_key = (custom_upstream or {}).get("api_key") or load_user_api_key_plain(db, user.id, modality)
            if not api_key:
                labels = {"text": "文本", "image": "图片", "video": "视频"}
                raise HTTPException(403, f"请先在账户页配置{labels.get(modality, modality)} API Key，或切换到平台账户模式")
        else:
            api_key = load_platform_key(channel)
            if not api_key:
                raise HTTPException(500, "平台渠道 API Key 未配置，请管理员在「积分与 AI 渠道」中设置")
        return {
            "mode": mode,
            "base_url": base_url,
            "api_key": api_key,
            "model_key": resolved_model_key,
            "model_id": model.id,
            "channel_id": channel.id,
            "user_id": user.id,
            "custom_upstream": bool(custom_upstream),
            # 自定义上游没有目录模型能力，避免把当前模型能力错误套用到用户配置。
            "capabilities_json": None if custom_upstream else model.capabilities_json,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("双轨运行时解析失败 modality=%s", modality)
        return None


def _user_deepseek_api_key(request: Request) -> str | None:
    db = getattr(request.state, "db", None)
    if db is not None:
        dual = _resolve_dual_track_runtime(request, db, modality="text")
        if dual:
            deepseek_service.configure_runtime(
                base_url=dual["base_url"] or deepseek_service.DEEPSEEK_BASE_URL,
                model=dual["model_key"] or deepseek_service.DEEPSEEK_MODEL,
            )
            request.state.dual_track_text = dual
            return dual["api_key"]

    override = request.headers.get("x-deepseek-api-key") or None
    if db is None:
        return override
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.deepseek.base_url", db, deepseek_service.DEEPSEEK_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.deepseek.model", db, deepseek_service.DEEPSEEK_MODEL)).strip()
    requested_mode = _request_credential_mode(request, db)
    custom_upstream = _resolve_user_upstream_override(
        request,
        db,
        user=user,
        modality="text",
        mode=requested_mode,
    )
    resolved_base_url = (custom_upstream or {}).get("base_url") or admin_base_url
    resolved_model = (custom_upstream or {}).get("model_key") or admin_model
    deepseek_service.configure_runtime(
        base_url=resolved_base_url.rstrip("/") or deepseek_service.DEEPSEEK_BASE_URL,
        model=resolved_model or deepseek_service.DEEPSEEK_MODEL,
    )
    if custom_upstream:
        return custom_upstream["api_key"]
    if requested_mode == "user_key" and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")
    if capabilities["can_override_api_key"] and override:
        return override
    return _get_platform_setting("api.deepseek.api_key", db, "") or None


def _user_image_api_key(request: Request) -> str | None:
    db = getattr(request.state, "db", None)
    if db is not None:
        dual = _resolve_dual_track_runtime(request, db, modality="image")
        if dual:
            capabilities = dual.get("capabilities_json")
            image_capabilities = capabilities.get("image") if isinstance(capabilities, dict) else None
            defaults = image_capabilities.get("defaults") if isinstance(image_capabilities, dict) else None
            model_quality = defaults.get("quality") if isinstance(defaults, dict) else ""
            image_service.configure_runtime(
                base_url=dual["base_url"] or image_service.DEFAULT_IMAGE_API_BASE_URL,
                model=dual["model_key"] or image_service.DEFAULT_IMAGE_MODEL,
                size=str(_get_platform_setting("api.image.size", db, "") or ""),
                quality=str(model_quality or _get_platform_setting("api.image.quality", db, "") or ""),
                background=str(_get_platform_setting("api.image.background", db, "") or ""),
                moderation=str(_get_platform_setting("api.image.moderation", db, "") or ""),
                output_format=str(_get_platform_setting("api.image.output_format", db, "") or ""),
                output_compression=_get_platform_setting("api.image.output_compression", db, ""),
                input_fidelity=str(_get_platform_setting("api.image.input_fidelity", db, "") or ""),
            )
            request.state.dual_track_image = dual
            return dual["api_key"]

    override = request.headers.get("x-image-api-key") or None
    if db is None:
        return override
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.image.base_url", db, image_service.DEFAULT_IMAGE_API_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.image.model", db, image_service.DEFAULT_IMAGE_MODEL)).strip()
    requested_mode = _request_credential_mode(request, db)
    custom_upstream = _resolve_user_upstream_override(
        request,
        db,
        user=user,
        modality="image",
        mode=requested_mode,
    )
    resolved_base_url = (custom_upstream or {}).get("base_url") or admin_base_url
    resolved_model = (custom_upstream or {}).get("model_key") or admin_model
    if not resolved_model or resolved_model.strip().lower() in ("default", "none", "null"):
        resolved_model = ""
    if custom_upstream:
        # 用户自定义上游不继承平台专属图片参数或目录模型能力。
        image_service.configure_runtime(
            base_url=resolved_base_url.rstrip("/") or image_service.DEFAULT_IMAGE_API_BASE_URL,
            model=resolved_model or image_service.DEFAULT_IMAGE_MODEL,
        )
        return custom_upstream["api_key"]
    image_service.configure_runtime(
        base_url=resolved_base_url.rstrip("/") or image_service.DEFAULT_IMAGE_API_BASE_URL,
        model=resolved_model or image_service.DEFAULT_IMAGE_MODEL,
        size=str(_get_platform_setting("api.image.size", db, "") or ""),
        quality=str(_get_platform_setting("api.image.quality", db, "") or ""),
        background=str(_get_platform_setting("api.image.background", db, "") or ""),
        moderation=str(_get_platform_setting("api.image.moderation", db, "") or ""),
        output_format=str(_get_platform_setting("api.image.output_format", db, "") or ""),
        output_compression=_get_platform_setting("api.image.output_compression", db, ""),
        input_fidelity=str(_get_platform_setting("api.image.input_fidelity", db, "") or ""),
    )
    if requested_mode == "user_key" and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")
    if capabilities["can_override_api_key"] and override:
        return override
    return _get_platform_setting("api.image.api_key", db, "") or None


def _image_setting_text(api: dict, key: str) -> str:
    value = api.get(key, "")
    if value is None:
        return ""
    cleaned = str(value).strip()
    return "" if cleaned.lower() in ("default", "none", "null") else cleaned


def _image_output_compression_setting(api: dict) -> str:
    value = api.get("image_output_compression", "")
    if value in (None, ""):
        return ""
    try:
        return str(max(0, min(100, int(value))))
    except (TypeError, ValueError):
        return ""


def _release_db_transaction(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        logger.debug("Failed to rollback request transaction before external API call", exc_info=True)


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _password_hash_iterations() -> int:
    return _bounded_env_int("PASSWORD_HASH_ITERATIONS", 600_000, 100_000, 2_000_000)


def _password_hash(raw: str) -> str:
    iterations = _password_hash_iterations()
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _verify_password(raw: str, encoded: str) -> bool:
    value = str(encoded or "")
    if value.startswith("pbkdf2_sha256$"):
        try:
            _, raw_iterations, raw_salt, expected = value.split("$", 3)
            iterations = int(raw_iterations)
            if not 100_000 <= iterations <= 2_000_000:
                return False
            salt = bytes.fromhex(raw_salt)
            if len(salt) != 16 or len(expected) != 64:
                return False
            digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, iterations).hex()
        except (TypeError, ValueError):
            return False
        return secrets.compare_digest(digest, expected)

    # 兼容旧版无盐 SHA-256；用户下次成功登录时会自动升级哈希。
    legacy = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return len(value) == 64 and secrets.compare_digest(legacy, value)


def _password_needs_rehash(encoded: str) -> bool:
    if not str(encoded or "").startswith("pbkdf2_sha256$"):
        return True
    try:
        iterations = int(str(encoded).split("$", 3)[1])
    except (IndexError, ValueError):
        return True
    return iterations < _password_hash_iterations()


def _validate_new_password(raw: str) -> None:
    if len(raw) < 8:
        raise HTTPException(400, "密码长度不能少于 8 位")
    if len(raw) > 128:
        raise HTTPException(400, "密码长度不能超过 128 位")


def _session_is_expired(session: UserSession) -> bool:
    ttl_days = _bounded_env_int("SESSION_TTL_DAYS", 30, 1, 365)
    created_at = session.created_at
    if not created_at:
        return True
    return created_at + datetime.timedelta(days=ttl_days) <= _utcnow()


def _new_session_token() -> str:
    return f"lv_{secrets.token_urlsafe(32)}"


def _session_token_fingerprint(token: str) -> str:
    return f"sha256${hashlib.sha256(token.encode('utf-8')).hexdigest()}"


def _hash_legacy_session_tokens(db: Session) -> int:
    """将历史明文会话令牌迁移为指纹，同时保持客户端令牌有效。"""
    legacy_sessions = db.query(UserSession).filter(~UserSession.token.like("sha256$%")).all()
    for session in legacy_sessions:
        fingerprint = _session_token_fingerprint(session.token)
        duplicate = db.query(UserSession.id).filter(
            UserSession.token == fingerprint,
            UserSession.id != session.id,
        ).first()
        if duplicate:
            db.delete(session)
        else:
            session.token = fingerprint
    db.flush()
    return len(legacy_sessions)


def _find_active_session(token: str, db: Session) -> UserSession | None:
    fingerprint = _session_token_fingerprint(token)
    return db.query(UserSession).filter(
        UserSession.token == fingerprint,
        UserSession.revoked_at.is_(None),
    ).first()


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _add_months(base: datetime.datetime, months: int) -> datetime.datetime:
    month_index = (base.month - 1) + months
    year = base.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day)



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


def _issue_email_verification_code(email: str, purpose: str, db: Session, *, deliver: bool = True) -> dict:
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
    subject_action = {"register": "注册", "login": "登录", "reset": "重置密码"}.get(purpose, purpose)
    subject = f"{_get_platform_setting('platform.site_name', db, 'StoryCanvas')} {subject_action}验证码"
    body = (
        f"您好，\n\n"
        f"您本次用于{subject_action}的验证码是：{code}\n"
        f"验证码将在 {expire_minutes} 分钟后失效。\n"
        f"如果这不是您的操作，请忽略这封邮件。\n"
    )
    if deliver:
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
        .with_for_update()
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(400, "未找到可用验证码，请先发送验证码")
    if record.expires_at < now:
        record.consumed_at = now
        db.commit()
        raise HTTPException(400, "验证码已过期，请重新发送")
    if not secrets.compare_digest(record.code_hash, _verification_code_hash(email, purpose, normalized_code)):
        record.attempt_count = int(record.attempt_count or 0) + 1
        if record.attempt_count >= 5:
            record.consumed_at = now
        db.commit()
        raise HTTPException(400, "邮箱验证码不正确")
    record.consumed_at = now
    db.commit()


def _ensure_platform_seed(
    db: Session,
    *,
    create_default_admin: bool = False,
    commit: bool = True,
) -> None:
    # 旧套餐配额种子已移除，仅保留平台设置种子
    _seed_platform_settings(db, commit=commit)
    if commit:
        db.commit()


def _create_install_admin_user(normalized_admin: dict[str, str], db: Session) -> User:
    email = normalized_admin["email"]
    name = normalized_admin["name"]
    password = normalized_admin["password"]
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(409, "管理员邮箱已存在")

    user = User(
        email=email,
        password_hash=_password_hash(password),
        name=name,
        role="admin",
        status="active",
        email_verified=True,
        allow_api_key_override=True,
        allow_api_url_override=True,
    )
    db.add(user)
    db.flush()
    return user


def _ensure_plan_feature_seed(db: Session, *, commit: bool = True) -> None:
    """旧套餐配额种子函数 — 积分双轨系统已替代，保留为空实现"""
    pass


def _seed_platform_settings(db: Session, *, commit: bool = True) -> None:
    defaults = {
        "platform.site_name": "StoryCanvas",
        "platform.site_slogan": "AI 小说漫画创作平台",
        "platform.support_email": "support@storycanvas.ai",
        "platform.icp": "",
        "platform.copyright": "© StoryCanvas",
        "platform.notice": "欢迎使用企业级 AI 小说漫画创作平台。",
        "api.deepseek.base_url": deepseek_service.DEEPSEEK_BASE_URL,
        "api.deepseek.model": deepseek_service.DEEPSEEK_MODEL,
        "api.deepseek.api_key": "",
        "api.image.base_url": "https://newapi.aifusion6.cn/v1",
        "api.image.model": "",
        "api.image.api_key": "",
        "api.image.size": "",
        "api.image.quality": "",
        "api.image.background": "",
        "api.image.moderation": "",
        "api.image.output_format": "",
        "api.image.output_compression": "",
        "api.image.input_fidelity": "",
        "api.video.base_url": "https://newapi.aifusion6.cn/v1",
        "api.video.model": "veo3.1-fast",
        "api.video.api_key": "",
        "api.video.provider": "",
        "api.enable_user_override": True,
        "api.allow_all_users_api_key_override": False,
        "api.enable_user_url_override": False,
        "oss.enabled": False,
        "oss.access_key_id": "",
        "oss.access_key_secret": "",
        "oss.endpoint": "",
        "oss.bucket": "",
        "oss.public_url_base": "",
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
        "payment.default_method": "mock_qr",
        "payment.order_expire_minutes": 30,
        "payment.auto_activate_free_plan": True,
        "payment.instructions": "",
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
        "payment.epay_enabled": False,
        # 配额购买定价（元/单位）
        "pricing.quota.framework.generate.monthly_limit": "1.0",
        "pricing.quota.chapter.expand.monthly_limit": "0.5",
        "pricing.quota.scene.generate.monthly_limit": "0.3",
        "pricing.quota.manga.image.generate.monthly_limit": "0.2",
        "pricing.quota.ai.text.advanced_calls.monthly_limit": "0.3",
        "pricing.quota.deconstruction.run.monthly_limit": "3.0",
        "pricing.quota.video.shot.split.monthly_limit": "1.0",
        "pricing.quota.video.generate.count.monthly_limit": "2.0",
        "payment.epay_gateway": "",
        "payment.epay_pid": "",
        "payment.epay_key": "",
        "payment.epay_type": "alipay",
        "payment.epay_notify_url": "",
        "payment.epay_return_url": "",
        "payment.mapay_enabled": False,
        "payment.mapay_gateway": "https://pay.21lili.cn",
        "payment.mapay_pid": "",
        "payment.mapay_key": "",
        "payment.mapay_type": "alipay",
        "payment.mapay_notify_url": "",
        "payment.mapay_return_url": "",
    }
    for key, value in defaults.items():
        if db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first():
            continue
        db.add(PlatformSetting(setting_key=key, value_json={"value": value}))

    _seed_system_prompts(db, commit=commit)
    _seed_methodology(db, commit=commit)


# ── 系统提示词种子数据 ──────────────────────────


def _ensure_framework_prompt_synced(db) -> None:
    """启动时同步核心写作提示词到数据库。

    确保 DB 记录与框架、正文扩写、参考章节的源码种子一致。
    修改 Python 源码中的这些常量后，重启即可自动同步到数据库。
    """
    from models import PlatformSetting

    prompt_map = {
        "prompt.framework_generation": FRAMEWORK_PROMPT_SEED,
        "prompt.framework_editing": EDITING_PROMPT_SEED,
        "prompt.framework_continuation": CONTINUATION_PROMPT_SEED,
        "prompt.chapter_generation": NOVEL_PROMPT_SEED,
        "prompt.reference_chapter": REFERENCE_CHAPTER_PROMPT_SEED,
    }
    for key, seed in prompt_map.items():
        setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
        if setting:
            setting.value_json = {"value": seed}
        else:
            db.add(PlatformSetting(setting_key=key, value_json={"value": seed}))
    db.commit()


_BASE_NOVEL_PROMPT = """你是白金级网文作家，作品长期位居各平台畅销榜首。你的小说以逻辑严密、节奏精准、人物鲜活著称。

## 核心创作铁律
1. **逻辑自洽优先**：每一个情节点都必须有因有果。角色做出的每个决定，都必须有足够的情感动机和信息支撑。
   - 不能出现「没有理由就突然改变主意」「明明知道危险还往上冲」这类不合逻辑的行为。
   - 如果角色做出了看似不合理的决定，必须在文中给出足够的情感铺垫或信息揭示。

2. **剧情推进要有因果链**：每个事件都必须是前一个事件的合理结果，不能「跳跃式」推进。
   - 禁止出现「几天后」「过了段时间」「不知不觉中」这类时间跳跃直接推进剧情。
   - 禁止用「突然出现」「突然发生」来制造转折——所有转折都必须有铺垫。
   - 如果需要时间过渡，必须用具体场景或细节来展示这段时间发生了什么。

3. **人物行为要符合其性格和处境**：角色不能做出与其一贯性格相悖的行为，除非有足够的心理铺垫。
   - 内向的角色不能突然变得健谈，除非有特定的情境触发。
   - 聪明的角色不能突然做出愚蠢的决定，除非有情绪干扰或信息不对称。

## 对话写作要求
1. 对话必须符合角色的性格、身份、处境和情绪。
2. 禁止所有角色说话风格雷同——必须有明显的语言差异。
3. 对话要有潜台词，不能直白地表达所有情感。
4. 禁止用对话直接解释剧情——要通过行动和细节来展现。

## 标点规范
1. 【禁止破折号】全文禁止使用破折号（——），用逗号、句号或冒号代替。破折号是 AI 生成的典型痕迹，必须消除。

## 逻辑自检清单（在写完每个场景后检查）
- 这个角色为什么会做出这个决定？有足够的情感铺垫吗？
- 这个事件的发生合理吗？有前因后果吗？
- 这段对话符合角色的性格和处境吗？
- 这个情节能让读者信服吗？有没有逻辑漏洞？
- 如果我是读者，我会觉得这个发展牵强吗？

（关于写作技法、禁用词、节奏控制、去AI味规则，见下方方法论兜底。）"""

# 注入写作方法论（从 references/writing/ 参考文件读取，修改 .md 文件即可同步）
NOVEL_PROMPT_SEED = build_chapter_generation_prompt(_BASE_NOVEL_PROMPT)

REFERENCE_CHAPTER_PROMPT_SEED = """你是出版级网文作家。你写的章节节奏紧凑、人物鲜活，能直接发表到起点/番茄等平台。

## 篇幅与输出格式
1. 标准章节必须控制在 2200-3000 字，理想约 2500 字；低于 2200 字视为展开不足，高于 3000 字视为超出标准。
2. 只输出正文，不要标题、章节号、字数统计、写作说明或总结。
3. 不要把正文写成梗概、剧情提要、分镜说明或创作计划。
4. 首轮优先写到 2300-2700 字，按 9-10 个自然段组织，每段约 200-260 字，不要贴着 3000 字上限写。
5. 篇幅收束靠合并重复场景、删除无效转场和解释性设定完成，禁止硬截断关键情节。
6. 章末必须留有自然钩子，但不能用「他不知道的是」「这一切才刚刚开始」等模板化预告；钩子完成后立刻停笔。

## 核心写作准则
1. 场景即故事：每个场景必须有明确的戏剧功能。
2. 角色驱动：情节由角色的欲望、恐惧、缺陷推动，不是作者在背后操纵。
3. 对话有区分度：不同角色的说话方式必须不同，对话要推进剧情或暴露关系。
4. 克制抒情：用动作、对话、细节来传达情绪，不要直接告诉读者「他很愤怒」。
5. 节奏变化：紧张处用短句、快切；日常处用舒缓长句，但不能水环境描写。
6. 上下文承接：延续前文人物状态、伏笔、因果链，不擅自改设定、不跳过关键结果。

## 严禁的 AI 写作习惯
- 禁止「突然」「忽然」「就在这时」频繁出现
- 禁止「深深地」「无比地」「极其」等程度副词堆砌
- 禁止「他不知道的是……」「而这一切，才刚刚开始……」等模板化悬念
- 禁止所有角色说话风格雷同
- 禁止「心中涌起一股暖流」等空洞套话
- 禁止凑字数的环境描写和无意义细节"""

FRAMEWORK_PROMPT_SEED = """你是资深小说策划编辑，擅长设计能被直接写成畅销网文的故事框架。

你的框架必须满足：拿到框架的写手/AI 不需要额外脑补就能写出逻辑自洽、情节紧凑的章节。

请根据用户描述生成完整小说框架，严格只输出如下 JSON 格式，不要包含任何其他文字。

## 输出 JSON 结构

```json
{
  "description": "（必填）故事概述，一句话概括核心故事",
  "tags": {
    "type": "（必填）小说类型，如奇幻/科幻/悬疑/言情/都市/历史",
    "theme": "（必填）核心主题，如成长/复仇/救赎/守护/抗争",
    "style": "（必填）写作风格，如细腻温情/磅礴大气/轻松搞笑/暗黑深沉",
    "audience": "（必填）目标读者，如男频/女频/全年龄/青少年"
  },
  "characters": [
    {
      "name": "（必填）角色全名",
      "role": "（必填）角色定位，如主角/反派/导师/挚友/红颜",
      "big_five": {
        "openness": "（必填，0-100）开放性——想象力、好奇心",
        "conscientiousness": "（必填，0-100）尽责性——自律、条理",
        "extraversion": "（必填，0-100）外向性——社交、活力",
        "agreeableness": "（必填，0-100）宜人性——合作、同理心",
        "neuroticism": "（必填，0-100）神经质——情绪波动"
      },
      "arc": {
        "start": "角色起始状态",
        "middle": "角色中期变化",
        "end": "角色终局状态"
      },
      "relationships": [
        {"to": "对方角色名", "type": "关系类型", "description": "关系描述"}
      ]
    }
  ],
  "outline": {
    "three_acts": [
      {
        "act": "（必填）幕标识，如 1/2/3 或 第一幕/第二幕/第三幕",
        "title": "（必填）本幕标题",
        "summary": "（必填）本幕故事概要",
        "chapters": [
          {
            "chapter_number": "（必填，正整数）章节号，全书唯一",
            "title": "（必填）章节标题",
            "summary": "（强烈建议）本章内容概要",
            "goal": "（强烈建议）本章叙事目标——推进什么情节",
            "conflict": "（强烈建议）本章核心冲突",
            "hook": "（强烈建议）章节钩子——让读者想继续读的悬念",
            "hook_intensity": "（建议）钩子强度 1-5 分，5=极强悬念/爽点预告，1=平淡过渡",
            "payoff": "（强烈建议）本章回报/高潮",
            "payoff_type": "（建议）爽点类型：打脸/升级/获宝/揭秘/情感/装逼/无",
            "payoff_intensity": "（建议）爽点强度 1-5 分，5=大爽点（每30章1个），3=小爽点（每3-5章1个），1=微爽点",
            "micro_payoffs": "（建议）本章微爽点描述列表，至少 2 个，如 [\"信息碾压打脸配角\", \"金手指小试牛锋\"]",
            "highlight": "（可选）本章最大亮点",
            "key_events": "（可选）关键事件列表，如 [\"主角发现遗物\", \"力量意外觉醒\"]"
          }
        ]
      }
    ],
    "themes": "（可选）主题线索数组，如 [\"成长\", \"牺牲\"]",
    "foreshadowing": "（可选）伏笔数组，每个元素为对象 {id, text, type(short/mid/long), planted_chapter, expected_payoff_chapter, priority(high/medium/low)}，如 [{\"id\":\"fb_001\",\"text\":\"古代遗物隐藏着更大秘密\",\"type\":\"long\",\"planted_chapter\":3,\"expected_payoff_chapter\":50,\"priority\":\"high\"}]",
    "serial_strategy": {
      "positioning": "（必填）作品定位与市场卖点",
      "opening_hook": "（必填）开篇钩子——第一章如何抓住读者",
      "first_3_chapter_hook": "（必填）前三章追读动力设计",
      "chapter_10_climax": "（中篇/长篇必填）第十章小高潮设计",
      "chapter_20_payoff": "（中篇/长篇必填）第二十章阶段性回报",
      "midgame_engine": "（长篇推荐）中段驱动力——什么支撑读者继续追",
      "late_game_direction": "（长篇推荐）后期故事方向与终局布局"
    }
  }
}
```

## 字段完整性要求

1. `description`: 必须存在且非空。
2. `tags`: 必须包含 type/theme/style/audience 四个非空字段。
3. `characters`: 至少 1 个角色，每个必须有 name/role/big_five。big_five 五个维度值必须在 0-100 之间，角色之间的人格要有明显区分度。`arc` 字段为结构化对象 {type(growth/fall/flat), summary, stages:[{chapter, trait, evidence, trigger}], current_stage, next_milestone_chapter}，至少包含起点和终点两个 stage。
4. `outline.three_acts`: 至少 2 幕，每幕必须有 act/title/summary 非空。
5. 每章 `chapter_number`: 从 1 开始的正整数，全书唯一不重复。
6. 每章 `title`: 必须有意义，不能为空。
7. **每章必须填充以下任务卡字段（缺一不可）**：
   - `summary`: 本章内容概要
   - `goal`: 本章叙事目标——推进什么情节、展示什么核心卖点
   - `conflict`: 本章核心冲突——谁和谁在什么层面产生对抗
   - `hook`: 开篇钩子——本章第一段如何抓住读者
   - `payoff`: 本章回报/高潮——读者读完本章能获得什么满足感
   - `highlight`: 本章最大亮点——区别于其他章节的独特记忆点
   这些字段是 AI 生成章节正文时的**唯一叙事指南**，缺了任何一个，AI 都会因为不知道本章要做什么而自由发挥、偏离大纲。
8. 后续扩展阶段的 chapters 不可为空数组——每章都必须有完整任务卡。如果某卷暂不规划详细章节，整个 chapters 数组留空 `[]`，但不能有只填了 title 而缺任务卡的半成品章节。
9. `serial_strategy`: 根据篇幅类型填充对应字段。
10. **爽点节奏规划（必须遵守）**：每章建议标注 `payoff_type`（打脸/升级/获宝/揭秘/情感/装逼/无）、`payoff_intensity`（1-5 分）、`micro_payoffs`（至少 2 个微爽点描述）、`hook_intensity`（1-5 分）。爽点密度硬约束：前 30 章 sum(payoff_intensity)/30 ≥ 1.5；每 3-5 章至少 1 个 intensity ≥ 3 的小爽点；每 10 章至少 1 个 intensity ≥ 4 的中爽点；每 30 章至少 1 个 intensity = 5 的大爽点；禁止连续 5 章 intensity < 2。前 30 章至少覆盖 3 种不同 payoff_type。

## 篇幅适配（根据用户描述的篇幅要求选择应用）

### 短篇（~10-30 章）
1. 全书控制在 10-30 章以内，节奏紧凑，不要拖沓。
2. 聚焦单一核心冲突，不要引入过多支线和副线。
3. 阶段结构 2-3 个即可：建立冲突 → 升级/反转 → 高潮/解决。
4. 高密度情节推进——每一章都必须有明确的叙事功能（推进剧情/揭示真相/制造转折），不能有纯过渡章。
5. 世界观简洁明了，只保留服务核心冲突的必要设定，不要过度展开。
6. 角色精简（3-5 个核心角色），每个角色都要有明确的叙事功能。
7. 第二章前必须进入核心冲突，不要用太多篇幅铺垫。
8. 中段要有一个关键反转或真相揭示，推动故事走向高潮。
9. 结局要紧凑有力，回收所有主要伏笔，不要拖尾。
10. 每章必须标注 goal, conflict, hook, payoff, highlight，确保全书节奏紧凑、每章有明确叙事功能。

### 中篇（~50-100 章）
1. 初始大纲只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和方向，不要求输出每章明细。
2. 核心冲突升级 2-3 次，每次升级改变角色处境和故事格局。
3. 阶段结构 3-5 个，每个阶段标注核心冲突方向和关键里程碑。
4. 阶段间要有明确的转折点，不能平铺直叙地过渡。
5. 角色成长渐进，每个阶段角色至少有一个关键变化。
6. 世界观分 2-3 层揭秘，不要一次性交代完毕。
7. 中段要保留升级空间和悬念递进，不能让故事在中段塌陷。
8. 感情线、友情线、敌对线都要有独立的发展曲线。
9. 每章必须标注 summary, goal, conflict, hook, payoff, highlight，确保开篇有足够抓力、每章有明确叙事功能。
10. 不要强制写出终局结局——用 serial_strategy 标注故事发展方向即可。

### 长篇（100+ 章，默认）
1. 初始大纲只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和关键里程碑，不要求输出每章明细。
2. 默认按长篇节奏规划（100 章以上潜力），不要在前 10 章内写完主要矛盾。
3. 核心冲突至少预留三次升级空间，每次升级改变角色处境和故事格局，但后续升级只需在幕级描述中标明方向。
4. 终局方向可以标注，但不要强制写出结局——保留开放扩展空间，让作者后续逐步完善。
5. 章节规划体现「铺垫→升级→扩盘→反转→决战→余波」节奏，但只在第一个阶段用满章节明细。
6. 角色成长渐进，不要把人物弧光一夜完成。
7. 世界观揭秘分层递进，每次只给读者部分真相。
8. 感情线、友情线、敌对线都要有独立的发展曲线。
9. 每章必须标注 summary, goal, conflict, hook, payoff, highlight，确保开篇有足够抓力、每章有明确叙事功能。
10. 后续阶段不要强制写出终局结局——用 serial_strategy 标注故事发展方向即可。"""

EDITING_PROMPT_SEED = """你是故事框架编辑规划器。你的任务不是输出完整 framework JSON，而是输出结构化编辑计划。

输出 JSON 格式：
{
  "reply": "只描述实际可执行改动",
  "operations": [{"op": "update_character", "target": {"name": "林霁"}, "changes": {}}],
  "patches": [{"path": "outline.themes", "value": []}],
  "warnings": ["无法定位目标时写在这里"]
}

支持的操作 operations：
- update_story_description: 用 target 不填，changes.description 更新故事描述
- update_tags: 用 target 不填，changes 中传 tags.type/theme/style/audience
- add_character: target 不填，changes 包含新角色字段
- update_character: target.name 指定角色名，changes 包含要更新的字段
- remove_character: target.name 指定要删除的角色名
- update_act_summary: target.act 指定幕标识，changes.summary 更新幕概述
- add_chapter: target.act 指定目标幕标识，changes 包含新章节字段
- insert_chapter_after: target.chapter_number 指定插入位置，changes 包含新章节字段
- move_chapter_to_act: target.chapter_number + target.act，将章节移动到目标幕
- update_chapter: target.chapter_number 指定章节号，changes 包含要更新的字段
- delete_chapter: target.chapter_number 指定要删除的章节号

支持的 patch 路径：
- description, tags.type, tags.theme, tags.style, tags.audience
- outline.serial_strategy, outline.themes, outline.foreshadowing
- outline.three_acts（用于整体压缩/重组幕结构，value 为新 three_acts 数组）

## 章节规划数量限制（强制规则）

**绝对禁止一次性输出所有卷的章节规划。** 长篇小说的框架应分阶段构建：

1. **每次规划一卷**：只规划当前卷的章节。每章必须包含 title/summary/goal/conflict/hook/payoff/highlight（缺一不可）。
2. **后续卷**：只规划幕级大纲（act/title/summary），chapters 设为空数组 `[]`。等前卷写完后，再用续写模式逐步生成后续章节。
3. **单次调整上限**：一次 `add_chapter` 操作最多添加 15 章。如果用户要求设计 60 章，先创建幕级大纲，再分批生成每卷的前 10 章。

**为什么不能一次性输出全部章节？**
- 一次性输出 60+ 章会导致 AI 省略任务卡字段，正文质量崩盘
- 后续卷的剧情应该根据前卷实际写作情况动态调整
- 任务卡字段是 AI 生成正文的**唯一叙事指南**，缺少任何一个都会导致正文偏离大纲

要求：
1. operations 优先，只有 description/tags.* / outline.serial_strategy / outline.themes / outline.foreshadowing 允许走 patches。
2. 禁止返回完整 framework。
3. 用户未要求修改的内容不要生成无关操作。
4. 找不到目标或指令有歧义时，把问题写进 warnings。
5. 移动章节到不同幕：用 move_chapter_to_act（target.chapter_number + target.act）。
6. 压缩/合并/重组幕结构：用 patch path="outline.three_acts"，value 为完整的新 three_acts 数组（包含 act/title/summary/chapters），会整体替换现有幕结构。
    关于已有章节的处理：
    - 用户未提及删除/修改章节 → 保留所有已有章节（chapter_number、title、summary 等完整保留），自动划分到新幕归属中。
    - 用户明确要求删除某些章节 → 按用户要求删除，其余保留。
    - 用户明确要求修改某些章节 → 按用户要求修改，其余保留。
     绝对不能在用户未要求的情况下丢失任何已有章节。
     重要：用户明确要求的幕数必须严格遵守。如用户要求压缩/扩展到特定幕数（如 5 幕、7 幕），
     即使某些幕暂时没有章节，也必须创建该数量的幕（空幕设 chapters: []），不能擅自减少或增加幕数。
7. 每个 add_chapter 的 changes **必须**包含 title、summary、goal、conflict、hook、payoff、highlight（缺一不可）。这些字段是后续 AI 生成章节正文时的唯一叙事指南，缺少任何一个都会导致 AI 自由发挥、偏离大纲。key_events 可选。"""

CONTINUATION_PROMPT_SEED = """你是故事框架续写规划器。你的任务是基于现有框架，向后扩展后续阶段和章节规划。

输出 JSON 格式：
{
  "reply": "描述续写的内容",
  "operations": [
    {"op": "add_chapter", "target": {"act": "幕标识"}, "changes": {"chapter_number": N, "title": "...", "summary": "...", ...}},
    {"op": "add_character", "changes": {"name": "...", "role": "...", ...}},
    {"op": "update_act_summary", "target": {"act": "幕标识"}, "changes": {"summary": "..."}},
    {"op": "move_chapter_to_act", "target": {"chapter_number": N, "act": "幕标识"}, "changes": {}},
    {"op": "delete_chapter", "target": {"chapter_number": N}, "changes": {}}
  ],
  "patches": [
    {"path": "outline.three_acts", "value": [...]}
  ],
  "warnings": []
}

要求：
1. 续写操作：只使用 add_chapter、add_character、update_act_summary、move_chapter_to_act、delete_chapter 操作，不要删除或修改已有内容。
2. 大纲重构（重要）：如果用户明确要求压缩/合并/重构幕结构，使用 patch 操作，path 为 "outline.three_acts"，value 为新的完整三幕结构数组。
   每个幕对象格式：{"act": "幕标识", "title": "...", "summary": "...", "chapters": [...]}。
   关于已有章节的处理：
   - 用户未提及删除/修改章节 → 保留所有已有章节（chapter_number、title、summary 等完整保留），自动划分到新幕归属中。
   - 用户明确要求删除某些章节 → 按用户要求删除，其余保留。
   - 用户明确要求修改某些章节 → 按用户要求修改，其余保留。
    绝对不能在用户未要求的情况下丢失任何已有章节。
    重要：用户明确要求的幕数必须严格遵守。如用户要求压缩/扩展到特定幕数（如 5 幕、7 幕），
    即使某些幕暂时没有章节，也必须创建该数量的幕（空幕设 chapters: []），不能擅自减少或增加幕数。
3. 每个 add_chapter 的 changes **必须**包含 title、summary、goal、conflict、hook、payoff、highlight（缺一不可）。这些字段是后续 AI 生成章节正文时的唯一叙事指南，缺少任何一个都会导致 AI 自由发挥、偏离大纲。key_events 可选。
4. 章节编号严格延续现有主线，不要跳跃或重复。
5. 不要把长篇故事压缩成短篇结局，保持后续升级、扩盘、反转空间。
6. reply 只说明实际续写的章节范围，不要说"我会"。"""

ONBOARDING_PROMPT_SEED = """你是小说创意提取专家。任务：从对话中按顺序提取 5 个核心字段，填满即结束。

## 绝对禁止的行为（违反会使整个引导失败）
- 禁止写任何样章、正文片段、场景描写、对白
- 禁止对用户的构思做文学分析、点评、赞赏或评价（如"这个设定有趣"）
- 禁止给任何创作建议、商业化建议、市场分析
- 禁止推荐选项——除非用户明确说"你定"或"推荐"，才给出 2-3 个简洁选项
- 禁止一次问多个问题——每轮只针对当前字段问一个问题

## 5 个字段（严格按顺序填充，每个字段都要提取丰富信息）

字段 1 — concept（故事概念）：用 1-2 句话概括，包含：
- 故事类型（如都市诡异、玄幻、科幻等）
- 主角身份与核心特质
- 开篇核心事件或冲突
- 示例：「都市诡异题材，程序员主角加班后被困在诡异公司，被迫与鬼签订契约才能逃脱」

字段 2 — setting（世界观规则）：引导用户从 5 个维度详细描述世界观，每个维度提取 1-3 句：
- 力量体系核心规则（如何获得力量、等级划分、能力分类、限制条件）
- 社会结构（掌握力量者与普通人的关系、相关组织/势力、管控方式）
- 关键场景地标（故事核心场所及其特点）
- 世界观历史背景（演化脉络、关键事件）
- 隐藏真相（只有主角或部分角色知道的秘密）
每轮聚焦一个维度追问，不要一次性全问。示例值：「契约体系——与鬼签订契约可获得鬼技，以鬼对抗鬼。世界存在表里两层，普通人看不见诡异，只有被选中的人才能进入里世界」

字段 3 — tone（风格标签）：3-5 个标签词，如：都市、诡异、契约、悬疑、写实

字段 4 — goals（创作目标）：用 1-2 句话说明，包含：
- 预期篇幅（短篇/中篇/长篇）
- 目标读者群体
- 示例：「中篇，面向网文读者，节奏紧凑的都市诡异故事」

字段 5 — synthesis（主角设定）：用 2-3 句话描述，包含：
- 主角姓名
- 核心人设（性格、能力、背景）
- 人物弧线方向
- 示例：「林默，做事严谨但不失风趣的程序员，会吐槽，诙谐。被迫涉入诡异世界后，从普通人逐渐成长为能驾驭鬼技的强者，为了求生只能变强」

## 工作流程
每一轮只做一件事：
1. 看当前字段是否已填充
2. 已填充 → 进入下一字段
3. 未填充 → 针对该字段问一个问题
4. 用户回答 → 提取关键信息填入 understanding 对应字段，确保信息完整丰富
5. 回复必须包含 JSON

## 对话示例
第一次消息 → concept 字段为空 → AI：
"作品属于什么类型？主角的身份是什么？"{"reply":"作品属于什么类型？主角的身份是什么？","understanding":{"concept":"","setting":"","tone":"","goals":"","synthesis":""},"understanding_depth":0,"phase":"extracting","has_brief":false,"creative_brief":null}

用户回答"都市诡异，程序员主角" → AI 提取 concept：
"已记录：都市诡异题材，程序员主角。接下来描述世界观：力量体系的核心规则是什么？比如契约、寄生还是道具？"{"reply":"已记录：都市诡异题材，程序员主角。接下来描述世界观：力量体系的核心规则是什么？比如契约、寄生还是道具？","understanding":{"concept":"都市诡异题材，程序员主角","setting":"","tone":"","goals":"","synthesis":""},"understanding_depth":20,"phase":"extracting","has_brief":false,"creative_brief":null}

## 模糊回答处理
用户说"你定/推荐/都可以"时：基于已有信息给出 2 个简洁选项（一行一个），不要展开描述。
用户选择后填入当前字段，继续下一字段。

## 填充完成条件
当 concept 和 goals 都非空 + 至少还有 1 个字段非空 → has_brief=true，reply 写"提取完毕，准备生成。"
此时不再提问，用户点击确认后后端自动构建框架。

## 输出格式（所有回复必须以此格式结尾）
{"reply":"提问或确认（≤150字）","understanding":{"concept":"","setting":"","tone":"","goals":"","synthesis":""},"understanding_depth":0,"phase":"extracting","has_brief":false,"creative_brief":null}"""

IMPORT_CONTEXT_PROMPT_SEED = """你是一位职业网文策划编辑，正在帮助作者补充"导入作品"的创作上下文。

你的目标不是重新立项，而是围绕作者已经导入的大纲/正文，快速补齐后续创作最关键的信息。

请严格遵守：
1. 一次只追问一个最关键的问题，避免长篇分析。
2. 优先确认：导入内容类型、必须保留项、后续创作目标、允许调整范围。
3. 语气专业、简洁，适合熟练作者快速填写。
4. 输出 JSON 对象，字段必须包含："""

_SYSTEM_PROMPT_SEEDS: dict[str, str] = {
    "prompt.chapter_generation": NOVEL_PROMPT_SEED,
    "prompt.framework_generation": FRAMEWORK_PROMPT_SEED,
    "prompt.framework_editing": EDITING_PROMPT_SEED,
    "prompt.framework_continuation": CONTINUATION_PROMPT_SEED,
    "prompt.onboarding": ONBOARDING_PROMPT_SEED,
    "prompt.import_context": IMPORT_CONTEXT_PROMPT_SEED,
    "prompt.tag_generation": "你是小说策划编辑。基于已有的故事框架，从 type（类型）、theme（主题）、style（风格）、audience（受众）四个维度输出标签（tags）的 JSON 对象。",
    "prompt.reference_framework": FRAMEWORK_PROMPT_SEED,
    "prompt.reference_chapter": REFERENCE_CHAPTER_PROMPT_SEED,
    "prompt.reference_character": "你是专业漫画角色设定师，擅长把角色设定转化为具体可视化的外貌卡。\n\n要求：\n1. 每个角色必须有2-3个标志性特征（特定发型、疤痕、配饰等）\n2. 性格映射为外貌——冷静的人克制端正、张扬的人有攻击性视觉符号\n3. 禁止千篇一律的「俊美」「帅气」——具体到可画的特征\n4. 每个角色需包含：角色名、身份、外貌、发型发色、眼型、体型、服装、配饰、标志性表情（常态/高兴/愤怒）、动作习惯、神态气质",
    "prompt.reference_manga_style": "画面风格必须完全以用户上传或选择的风格参考图为准，禁止根据预设名称或文字模板改变画风。\n黑白模式(bw)：仅将参考图的最终色彩输出为黑白或灰度，保留参考图的真实感、材质、光影和构图语言。\n彩色模式(color)：保留参考图的原始色彩和视觉媒介，不额外套用动漫、插画、线稿或其他固定画风。\n\n用户可在增量修改中添加非画风约束，如：\n- 场景使用电影级构图\n- 角色服装符合故事时代背景\n- 画面整体偏暗色调或暖色调",
}


def _seed_system_prompts(db: Session, *, commit: bool = True) -> None:
    """写入系统提示词种子数据。已存在的 key 跳过（onboarding 例外：旧版「灵感捕手」强制覆盖）。"""
    for key, value in _SYSTEM_PROMPT_SEEDS.items():
        setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
        if setting:
            # 检测旧版 onboarding prompt（含「灵感捕手」或「创作灵感」），强制更新
            if key == "prompt.onboarding":
                cur = setting.value_json.get("value", "") if isinstance(setting.value_json, dict) else ""
                if "灵感捕手" in cur or "创作灵感" in cur:
                    setting.value_json = {"value": value}
            elif key == "prompt.reference_manga_style":
                cur = setting.value_json.get("value", "") if isinstance(setting.value_json, dict) else ""
                if "日式动漫风格" in cur or "cel-shaded" in cur or "网点/排线阴影" in cur:
                    setting.value_json = {"value": value}
            continue
        db.add(PlatformSetting(setting_key=key, value_json={"value": value}))
    if commit:
        db.commit()


def _seed_methodology(db: Session, *, commit: bool = True) -> None:
    """将全部四个写作方法论组件种子数据写入 PlatformSetting 表。

    仅在 key 不存在时写入，避免覆盖管理员已编辑的内容。
    """
    from services.writing_utils import (
        _METHODOLOGY_KEYS, _METHODOLOGY_FILE_FALLBACK, save_methodology_to_db,
    )

    for key in _METHODOLOGY_KEYS:
        existing = db.query(PlatformSetting).filter_by(
            setting_key=_METHODOLOGY_KEYS[key]
        ).first()
        if existing:
            continue
        content = _METHODOLOGY_FILE_FALLBACK[key]()
        if content:
            save_methodology_to_db(db, key, content, commit=False)
    if commit:
        db.commit()


def _require_user(request: Request, db: Session) -> User:
    token = _parse_auth_token(request)
    if not token:
        raise HTTPException(401, "未授权")
    session = _find_active_session(token, db)
    if not session:
        raise HTTPException(401, "会话已过期或令牌无效")
    if _session_is_expired(session):
        session.revoked_at = _utcnow()
        db.commit()
        raise HTTPException(401, "会话已过期或令牌无效")
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        raise HTTPException(403, "用户不可用")
    request.state.current_user = user
    return user


def _get_current_user(request: Request, db: Session) -> User | None:
    """获取当前用户（不抛出异常），未登录时返回 None。"""
    token = _parse_auth_token(request)
    if not token:
        return None
    session = _find_active_session(token, db)
    if not session:
        return None
    if _session_is_expired(session):
        session.revoked_at = _utcnow()
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        return None
    request.state.current_user = user
    return user


def _require_admin(request: Request, db: Session) -> User:
    user = _require_user(request, db)
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user



def _require_story_for_user(story_id: int, user: User, db: Session) -> Story:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "作品未找到")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "作品访问被拒绝")
    return story


def _is_import_story(story: Story) -> bool:
    return str(getattr(story, "source_type", "manual") or "manual").strip().lower() == "import"


def _truncate_text(value: str, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _story_cover_output_path(story_id: int) -> Path:
    covers_dir = manga_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    return covers_dir / f"cover_{story_id}_{uuid.uuid4().hex[:8]}.png"


def _replace_story_cover_from_path(story: Story, generated_path: Path) -> str:
    relative = f"manga_outputs/covers/{generated_path.name}"
    if story.cover_image and story.cover_image != relative:
        old = Path(__file__).resolve().parent / story.cover_image
        try:
            _unlink_file(old, "old story cover")
        except HTTPException:
            logger.warning("Old story cover remained after replacement: %s", old)
    story.cover_image = relative
    return relative


def _store_story_cover_result(story: Story, generated_path: Path, stored_path: str) -> str:
    normalized = str(stored_path or "").strip()
    if normalized.startswith(("http://", "https://")):
        story.cover_image = normalized
        return normalized
    return _replace_story_cover_from_path(story, generated_path)


def _build_story_cover_prompt(story: Story, instruction: str = "") -> str:
    story_bible_compact = build_story_bible_compact(story.story_bible)
    outline_compact = _build_outline_compact(story.outline or {}, recent_chapter_limit=3)
    title = str(story.title or "").strip() or "Untitled Story"
    premise = str(
        story_bible_compact.get("one_line_premise")
        or story_bible_compact.get("project_positioning")
        or story.description
        or ""
    ).strip()
    core_hook = str(story_bible_compact.get("core_hook") or "").strip()
    tone = str(story_bible_compact.get("pacing_strategy") or "").strip()
    protagonist = str(story_bible_compact.get("protagonist_core") or "").strip()
    main_conflict = str(story_bible_compact.get("main_conflict") or "").strip()
    must_keep = story_bible_compact.get("must_keep_rules")
    must_keep_text = "、".join(str(item).strip() for item in must_keep if str(item).strip()) if isinstance(must_keep, list) else ""
    user_instruction = str(instruction or "").strip()

    # 构建画面主体描述
    scene_elements = []
    if premise:
        scene_elements.append(f"故事梗概：{premise}")
    if protagonist:
        scene_elements.append(f"主角特征：{protagonist}")
    if main_conflict:
        scene_elements.append(f"核心冲突：{main_conflict}")
    if core_hook:
        scene_elements.append(f"核心卖点：{core_hook}")
    scene_text = "\n".join(scene_elements)

    return (
        "为网络小说《" + title + "》设计一张出版级竖版封面图。\n\n"
        "【核心要求】\n"
        "1. 在封面醒目位置加入书名文字《" + title + "》，字体设计有商业质感，可搭配英文副标题；\n"
        "2. 画面必须紧扣小说主题，有人物/场景/世界观视觉呈现，让读者一眼看出题材类型；\n"
        "3. 竖版构图（宽高比约2:3），上部留位给书名，中部/下部为主视觉画面；\n"
        "4. 色彩氛围与故事基调一致（" + (tone or "根据题材匹配相应情绪") + "）；\n"
        "5. 画面干净、光影有层次、有商业封面质感，适合网络小说平台展示。\n\n"
        "【故事设定】\n" + scene_text + "\n"
        + ("【必须保留的设定】\n" + must_keep_text + "\n" if must_keep_text else "")
        + "【章节概要参考】\n" + json.dumps(outline_compact, ensure_ascii=False) + "\n\n"
        + (user_instruction if user_instruction else "【风格倾向】写实厚涂或半厚涂风格，人物刻画精致，背景有氛围感，整体有畅销小说封面气质。")
    )


def _build_import_guidance_context(story: Story, db: Session) -> dict[str, Any]:
    chapters = (
        db.query(Chapter)
        .filter(Chapter.story_id == story.id)
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    non_empty_chapters = [chapter for chapter in chapters if str(chapter.novel_content or "").strip()]
    content_kind = "chapter_manuscript" if non_empty_chapters else "outline_source"
    chapter_cards: list[dict[str, Any]] = []
    for chapter in chapters[:12]:
        memory_summary = chapter.memory_summary if isinstance(chapter.memory_summary, dict) else {}
        chapter_cards.append(
            {
                "chapter_number": chapter.chapter_number,
                "title": chapter.title or f"第{chapter.chapter_number}章",
                "act": chapter.act or "",
                "summary": memory_summary.get("summary")
                or _truncate_text(chapter.novel_content or "", 180),
                "key_events": chapter.key_events or [],
            }
        )

    creative_brief = {}
    if isinstance(story.story_bible, dict):
        creative_brief = story.story_bible.get("creative_brief") if isinstance(story.story_bible.get("creative_brief"), dict) else {}

    return {
        "story_id": story.id,
        "title": story.title,
        "description": story.description or "",
        "import_material_type_hint": content_kind,
        "chapter_count": len(chapters),
        "has_outline": bool(story.outline),
        "has_characters": isinstance(story.characters, list) and len(story.characters) > 0,
        "tags": story.tags or {},
        "outline_compact": _build_outline_compact(story.outline or {}, recent_chapter_limit=16),
        "characters_compact": [
            {
                "name": str(item.get("name") or "").strip(),
                "role": str(item.get("role") or "").strip(),
            }
            for item in (story.characters or [])[:8]
            if isinstance(item, dict) and (item.get("name") or item.get("role"))
        ],
        "chapter_cards": chapter_cards,
        "existing_creative_brief": creative_brief,
    }


def _compose_import_raw_input(
    import_context: dict[str, Any],
    collected_info: dict[str, Any],
    messages_raw: list[dict[str, Any]],
) -> dict[str, str]:
    all_raw = "\n".join(
        f"{'作者' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in messages_raw
        if isinstance(m, dict)
    )
    return {
        "raw_idea": str(collected_info.get("author_goal") or import_context.get("description") or "").strip(),
        "raw_length_goal": str(collected_info.get("longline_plan") or "").strip(),
        "raw_must_keep": str(collected_info.get("must_keep") or "").strip(),
        "raw_hidden_setting": str(collected_info.get("tone_guardrails") or "").strip(),
        "raw_notes": (
            "【导入作品上下文】\n"
            + json.dumps(import_context, ensure_ascii=False, indent=2)
            + "\n\n【作者补充要求】\n"
            + json.dumps(collected_info, ensure_ascii=False, indent=2)
            + "\n\n【对话记录】\n"
            + all_raw
        ).strip(),
    }


def _build_import_guidance_payload(collected_info: dict[str, Any], import_context: dict[str, Any]) -> dict[str, Any]:
    guidance: dict[str, Any] = {
        "context_source": "import_guidance",
        "import_material_type": str(
            collected_info.get("import_material_type") or import_context.get("import_material_type_hint") or ""
        ).strip(),
        "must_keep": str(collected_info.get("must_keep") or "").strip(),
        "author_goal": str(collected_info.get("author_goal") or "").strip(),
        "adjustment_scope": str(collected_info.get("adjustment_scope") or "").strip(),
        "longline_plan": str(collected_info.get("longline_plan") or "").strip(),
        "tone_guardrails": str(collected_info.get("tone_guardrails") or "").strip(),
    }
    return {key: value for key, value in guidance.items() if value}


async def _build_import_provisional_story_bible(
    story: Story,
    db: Session,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    import_context = _build_import_guidance_context(story, db)
    raw_input = _compose_import_raw_input(import_context, {}, [])
    _release_db_transaction(db)
    creative_brief = await build_import_creative_brief(
        import_context,
        {},
        api_key=api_key,
    )
    story_bible = await build_story_bible(
        creative_brief,
        raw_input,
        api_key=api_key,
    )
    story_bible["import_guidance"] = _build_import_guidance_payload({}, import_context)
    return story_bible


def _require_chapter_for_user(chapter_id: int, user: User, db: Session) -> Chapter:
    chapter = _require_chapter(chapter_id, db)
    story = chapter.story
    if not story:
        raise HTTPException(404, "作品未找到")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "章节访问被拒绝")
    return chapter



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
        raise HTTPException(400, f"{field_name} 必须是有效数字") from exc
    if amount < 0:
        raise HTTPException(400, f"{field_name} 必须大于等于 0")
    return amount


def _money_to_number(value: object) -> float:
    return float(_coerce_money(value))


def _payment_amount_matches(expected: object, reported: object) -> bool:
    if reported is None or str(reported).strip() == "":
        return False
    try:
        expected_amount = Decimal(str(expected)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        reported_amount = Decimal(str(reported)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return False
    return expected_amount == reported_amount



def _check_and_consume_quota(
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    *,
    deduct: bool,
) -> dict:
    """积分双轨配额检查与扣费（无 request 上下文）— 旧套餐配额系统已移除"""
    if amount <= 0:
        amount = 1
    try:
        from models import UserAiPreference
        from decimal import Decimal as _Decimal
        import uuid as _uuid
        from services.ai.resolver import begin_ai_call, complete_ai_call, resolve_model

        pref = db.query(UserAiPreference).filter(UserAiPreference.user_id == user_id).first()
        mode = pref.credential_mode if pref and pref.credential_mode in {"platform", "user_key"} else "platform"
        if not deduct or mode == "user_key":
            return {
                "skipped": True,
                "reason": "points_dual_track",
                "credential_mode": mode,
                "feature_key": feature_key,
                "used": 0,
                "limit": 0,
                "period_key": "",
                "base_limit": 0,
                "granted": 0,
            }
        modality = _feature_key_to_modality(feature_key)
        model = resolve_model(db, user_id, modality=modality, model_id=None, task_type=None)
        units = max(1, int(amount or 1))
        estimate_kwargs = {}
        if modality == "text":
            estimate_kwargs["call_count"] = units
        elif modality == "image":
            estimate_kwargs["image_count"] = units
        elif modality == "video":
            estimate_kwargs["video_seconds"] = units
        ctx = begin_ai_call(
            db,
            user_id=user_id,
            modality=modality,
            task_type=feature_key,
            credential_mode="platform",
            model_id=model.id,
            request_id=str(_uuid.uuid4()),
            estimate_kwargs=estimate_kwargs,
        )
        complete_ai_call(
            db,
            ctx,
            success=True,
            image_count=units if modality == "image" else 0,
            video_seconds=units if modality == "video" else 0,
            usage_source="estimated",
        )
        return {
            "skipped": True,
            "reason": "points_dual_track",
            "credential_mode": mode,
            "feature_key": feature_key,
            "points_charged": float(ctx.estimated_points or ctx.reserved_points or _Decimal("0")),
            "usage_event_id": ctx.usage_event_id,
            "billing_request_id": ctx.request_id,
            "used": 0,
            "limit": 0,
            "period_key": "",
            "base_limit": 0,
            "granted": 0,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("无 request 双轨扣费失败 feature=%s", feature_key)
        raise


def _refund_quota(
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    period_key: str | None = None,
    *,
    usage_event_id: int | None = None,
) -> None:
    """按原始用量事件退款；没有账本事件时拒绝猜测退款金额。"""
    if not usage_event_id:
        logger.warning(
            "忽略缺少用量事件的退款请求 user=%s feature=%s amount=%s",
            user_id,
            feature_key,
            amount,
        )
        return
    try:
        from services.ai.resolver import refund_ai_call

        refund_ai_call(db, usage_event_id, error_code="quota_refund")
    except Exception:
        logger.exception("积分退款失败 feature=%s usage_event_id=%s", feature_key, usage_event_id)


def _serialize_order(order: BillingOrder) -> dict:
    operator = None
    user_name = None
    extra = order.extra_json or {}
    plan_name = str(extra.get("product_name") or "") or None
    db = getattr(_serialize_order, "_db", None)
    if db is not None:
        if order.operator_user_id:
            op = db.get(User, order.operator_user_id)
            if op:
                operator = {"id": op.id, "name": op.name, "email": op.email}
        user = db.get(User, order.user_id)
        if user:
            user_name = user.name
        if not plan_name and order.plan_id:
            historical_plan = db.get(Plan, order.plan_id)
            if historical_plan:
                plan_name = historical_plan.name
    return {
        "order_no": order.order_no,
        "user_id": order.user_id,
        "user_name": user_name,
        "plan_id": order.plan_id,
        "points_product_id": order.points_product_id,
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
        "extra": extra,
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


def _redact_update_line(line: Any) -> str:
    text_value = str(line)
    text_value = URL_WITH_PASSWORD_RE.sub(r"\1***\3", text_value)
    return SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=***", text_value)


def _sanitize_update_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    log_tail = payload.get("log_tail") if isinstance(payload.get("log_tail"), list) else []
    return {
        "status": str(payload.get("status") or "unknown"),
        "message": str(payload.get("message") or ""),
        "running": bool(payload.get("running", False)),
        "target_version": payload.get("target_version") or None,
        "current_version": os.getenv("APP_VERSION", "dev"),
        "started_at": payload.get("started_at") or None,
        "finished_at": payload.get("finished_at") or None,
        "exit_code": payload.get("exit_code") if payload.get("exit_code") is not None else None,
        "log_tail": [_redact_update_line(item) for item in log_tail[-120:]],
    }


def _sanitize_update_check(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    latest_version = str(payload.get("latest_version") or "").strip() or None
    current_version = str(payload.get("current_version") or os.getenv("APP_VERSION", "dev")).strip()
    return {
        "configured": bool(payload.get("configured", False)),
        "current_version": current_version or "dev",
        "latest_version": latest_version,
        "update_available": bool(payload.get("update_available", False) and latest_version),
        "release_notes": str(payload.get("release_notes") or ""),
        "published_at": payload.get("published_at") or None,
        "min_supported_version": payload.get("min_supported_version") or None,
        "channel": payload.get("channel") or None,
        "manifest_url": _redact_update_line(payload.get("manifest_url") or ""),
        "message": str(payload.get("message") or ""),
    }


async def _call_updater(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not UPDATER_URL:
        raise HTTPException(503, "更新服务未配置")
    headers = {"X-Updater-Token": UPDATER_TOKEN} if UPDATER_TOKEN else {}
    url = f"{UPDATER_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=UPDATER_TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise HTTPException(503, "更新服务超时")
    except httpx.RequestError as exc:
        raise HTTPException(503, f"更新服务不可用: {exc}")
    if response.status_code >= 400:
        detail = response.text
        with contextlib.suppress(Exception):
            data = response.json()
            detail = data.get("detail") or data.get("message") or detail
        status_code = 503 if response.status_code == 401 else response.status_code
        raise HTTPException(status_code, f"更新服务拒绝请求: {detail}")
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(503, "更新服务返回无效 JSON")
    if not isinstance(data, dict):
        raise HTTPException(503, "更新服务返回无效负载")
    return data



def _check_platform_points_available(
    request: Request,
    db: Session,
    *,
    user_id: int,
    task_type: str,
    modality: str,
    units: int,
) -> None:
    """为流式逐项计费接口做余额检查，不创建可退款账单。"""
    from services.ai.catalog import get_active_price
    from services.ai.resolver import resolve_model
    from services.points import accounts as points_accounts
    from services.points.pricing import estimate_points, reserve_points_from_estimate

    dual = getattr(request.state, f"dual_track_{modality}", None) or _resolve_dual_track_runtime(
        request, db, modality=modality
    )
    if not dual or dual.get("mode") != "platform":
        return
    model = resolve_model(
        db,
        user_id,
        modality=modality,
        model_id=dual.get("model_id"),
        task_type=task_type,
    )
    price = get_active_price(db, model.id)
    if not price:
        raise HTTPException(400, "该模型尚未配置积分价格")
    estimate_kwargs = {
        "image_count": units if modality == "image" else 1,
        "video_seconds": units if modality == "video" else 0,
    }
    estimated = estimate_points(
        billing_type=price.billing_type,
        price_config=price.price_config_json,
        image_count=estimate_kwargs["image_count"],
        video_seconds=estimate_kwargs["video_seconds"],
        use_estimate_defaults=True,
    )
    required = reserve_points_from_estimate(estimated)
    account = points_accounts.get_account_for_update(db, user_id)
    if account.available_points < required:
        raise HTTPException(402, f"积分不足：可用 {account.available_points}，需要 {required}")


def _charge_platform_points_immediate(
    request: Request,
    db: Session,
    *,
    user_id: int,
    task_type: str,
    modality: str = "text",
    units: int = 1,
    settle: bool = True,
    streaming: bool = False,
) -> dict | None:
    if not _points_dual_track_enabled(db):
        return None
    dual = getattr(request.state, f"dual_track_{modality}", None) or _resolve_dual_track_runtime(
        request, db, modality=modality
    )
    if not dual or dual.get("mode") != "platform":
        return None
    try:
        import uuid as _uuid
        from decimal import Decimal as _Decimal

        from services.ai.resolver import begin_ai_call, complete_ai_call

        units = max(1, int(units or 1))
        rid = (request.headers.get("x-request-id") or "").strip() or str(_uuid.uuid4())
        seq = int(getattr(request.state, "points_charge_seq", 0) or 0) + 1
        request.state.points_charge_seq = seq
        if units > 1 or seq > 1:
            suffix = f":{seq}"
            rid = f"{rid[:64 - len(suffix)]}{suffix}"
        else:
            rid = rid[:64]

        estimate_kwargs = {}
        if modality == "text":
            estimate_kwargs["call_count"] = units
            estimate_kwargs["streaming"] = streaming
        elif modality == "image":
            estimate_kwargs["image_count"] = units
        elif modality == "video":
            estimate_kwargs["video_seconds"] = units

        ctx = begin_ai_call(
            db,
            user_id=user_id,
            modality=modality,
            task_type=task_type,
            credential_mode="platform",
            model_id=dual.get("model_id"),
            request_id=rid,
            estimate_kwargs=estimate_kwargs,
        )
        charged = ctx.estimated_points or ctx.reserved_points or _Decimal("0")
        result = {
            "request_id": rid,
            "usage_event_id": ctx.usage_event_id,
            "user_id": user_id,
            "amount": str(charged),
            "task_type": task_type,
            "modality": modality,
            "units": units,
        }
        if settle:
            usage = {"input_tokens": 0, "output_tokens": 0}
            if modality == "text":
                from services.deepseek import consume_usage_accumulator

                usage = consume_usage_accumulator()
            has_provider_usage = bool(usage["input_tokens"] or usage["output_tokens"])
            complete_ai_call(
                db,
                ctx,
                success=True,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                image_count=units if modality == "image" else 0,
                video_seconds=units if modality == "video" else 0,
                usage_source="provider" if has_provider_usage else "estimated",
            )
            bag = getattr(request.state, "points_charge_ids", None)
            if bag is None:
                bag = []
                request.state.points_charge_ids = bag
            bag.append(result)
        else:
            pending = getattr(request.state, "points_pending_charges", None)
            if pending is None:
                pending = []
                request.state.points_pending_charges = pending
            pending.append({**result, "ctx": ctx})
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("积分扣费失败 task=%s", task_type)
        raise


def _settle_pending_platform_points(
    request: Request,
    db: Session,
    *,
    user_id: int,
    task_type: str,
    modality: str,
) -> dict | None:
    pending = getattr(request.state, "points_pending_charges", None) or []
    for index, item in enumerate(pending):
        if (
            item.get("user_id") == user_id
            and item.get("task_type") == task_type
            and item.get("modality") == modality
        ):
            from services.ai.resolver import complete_ai_call

            ctx = item["ctx"]
            units = max(1, int(item.get("units") or 1))
            usage = {"input_tokens": 0, "output_tokens": 0}
            if modality == "text":
                from services.deepseek import consume_usage_accumulator

                usage = consume_usage_accumulator()
            has_provider_usage = bool(usage["input_tokens"] or usage["output_tokens"])
            complete_ai_call(
                db,
                ctx,
                success=True,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                image_count=units if modality == "image" else 0,
                video_seconds=units if modality == "video" else 0,
                usage_source="provider" if has_provider_usage else "estimated",
            )
            pending.pop(index)
            settled = {key: value for key, value in item.items() if key != "ctx"}
            bag = getattr(request.state, "points_charge_ids", None)
            if bag is None:
                bag = []
                request.state.points_charge_ids = bag
            bag.append(settled)
            return settled
    return None


def _detach_pending_platform_points(request: Request, usage_event_id: int | None):
    """把流式请求的预留账单交给生成器管理，避免响应中间件提前释放。"""
    if not usage_event_id:
        return None
    pending = getattr(request.state, "points_pending_charges", None) or []
    for index, item in enumerate(pending):
        if item.get("usage_event_id") == usage_event_id:
            pending.pop(index)
            return item.get("ctx")
    return None


def _finish_streaming_platform_points(
    ctx,
    *,
    success: bool,
    input_text: str = "",
    output_text: str = "",
    image_count: int = 0,
    video_seconds: int | float = 0,
    error_code: str | None = None,
) -> None:
    """终结脱离请求中间件托管的流式账单。"""
    if ctx is None:
        return
    from services.ai.resolver import complete_ai_call
    from services.deepseek import consume_usage_accumulator

    usage = consume_usage_accumulator()
    usage_source = "provider"
    if (
        success
        and getattr(ctx, "modality", "text") == "text"
        and not (usage["input_tokens"] or usage["output_tokens"])
    ):
        from services.token_utils import estimate_tokens

        usage = {
            "input_tokens": estimate_tokens(input_text),
            "output_tokens": estimate_tokens(output_text),
        }
        usage_source = "estimated"
    billing_db = SessionLocal()
    try:
        complete_ai_call(
            billing_db,
            ctx,
            success=success,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            image_count=max(0, int(image_count or 0)),
            video_seconds=max(0, video_seconds or 0),
            error_code=error_code,
            usage_source=usage_source if getattr(ctx, "modality", "text") == "text" else "provider",
        )
    finally:
        billing_db.close()


def _reserve_background_image_points(
    *,
    user_id: int,
    story_id: int,
    chapter_id: int,
    image_count: int,
    credential_mode: str,
    model_id: int | None,
):
    """后台按实际缺失资产数预留图片积分，不依赖已结束的 HTTP 请求状态。"""
    if credential_mode != "platform" or image_count <= 0:
        return None
    from services.ai.resolver import begin_ai_call

    billing_db = SessionLocal()
    try:
        return begin_ai_call(
            billing_db,
            user_id=user_id,
            modality="image",
            task_type="manga.image.generate.monthly_limit",
            credential_mode=credential_mode,
            model_id=model_id,
            story_id=story_id,
            chapter_id=chapter_id,
            estimate_kwargs={"image_count": image_count},
        )
    finally:
        billing_db.close()


def _refund_request_points_charges(request: Request, db: Session, *, error_code: str) -> None:
    charges = list(getattr(request.state, "points_charge_ids", None) or [])
    if not charges:
        return
    from services.ai.resolver import refund_ai_call

    for item in charges:
        refund_ai_call(db, item.get("usage_event_id"), error_code=error_code)
    request.state.points_charge_ids = []


def _release_request_points_reservations(request: Request, db: Session) -> None:
    pending = list(getattr(request.state, "points_pending_charges", None) or [])
    if pending:
        from services.ai.resolver import refund_ai_call

        for item in pending:
            with contextlib.suppress(Exception):
                refund_ai_call(db, item.get("usage_event_id"), error_code="request_incomplete")
        request.state.points_pending_charges = []
    with contextlib.suppress(Exception):
        from services.deepseek import consume_usage_accumulator

        consume_usage_accumulator()


def _check_and_consume_advanced_text_quota(
    request: Request,
    user_id: int,
    db: Session,
    *,
    deduct: bool,
    reserve: bool = True,
) -> dict:
    return _check_and_consume_feature_quota(
        request,
        user_id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=deduct,
        provider_kind="text",
        reserve=reserve,
    )





def _mark_order_paid(order: BillingOrder, db: Session, *, operator_user_id: int | None = None, note: str = "") -> BillingOrder:
    if order.status != "paid":
        order.status = "paid"
        order.paid_at = _utcnow()
    if operator_user_id is not None:
        order.operator_user_id = operator_user_id
    if note:
        order.note = note

    if order.source == "points_purchase":
        from decimal import Decimal as _Decimal

        from services.points import accounts as points_accounts
        from services.points.pricing import quantize_points

        extra = order.extra_json or {}
        pts = quantize_points(_Decimal(str(extra.get("points") or 0)))
        bonus = quantize_points(_Decimal(str(extra.get("bonus_points") or 0)))
        total = quantize_points(pts + bonus)
        if total > 0:
            points_accounts.credit_points(
                db,
                order.user_id,
                total,
                entry_type="purchase",
                idempotency_key=f"points_purchase:{order.order_no}",
                order_id=order.id,
                metadata={"order_no": order.order_no, "product_id": extra.get("product_id")},
            )
        db.flush()
        return order

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
    if order.status == "pending" and order.expired_at and order.expired_at <= _utcnow():
        _mark_order_expired(order, db, note=order.note or "Order expired before payment confirmation")
        db.commit()
        db.refresh(order)
    return order


def _order_checkout_payload(
    order: BillingOrder,
    plan,
    db: Session,
    payment_override: dict | None = None,
    *,
    raise_gateway_errors: bool = False,
) -> dict:
    payment = payment_override if payment_override is not None else _payment_settings_snapshot(db)
    method = order.payment_method or str(payment.get("default_method") or "mock_qr")
    provider = order.payment_provider or "mock"
    extra = dict(order.extra_json or {})
    item = plan or SimpleNamespace(
        name=str(extra.get("product_name") or order.source or "订单"),
        description=str(extra.get("product_description") or ""),
    )

    if provider in {"alipay", "epay", "mapay"}:
        qr_code_text = str(
            extra.get(f"{provider}_qr_code")
            or extra.get("alipay_qr_code")
            or ""
        )
        payment_url = str(
            extra.get(f"{provider}_payment_url")
            or extra.get("alipay_payment_url")
            or qr_code_text
            or ""
        )
        if qr_code_text or payment_url:
            expire_minutes = int(payment.get("order_expire_minutes") or 30)
            expires_at = order.expired_at or (_utcnow() + datetime.timedelta(minutes=expire_minutes))
            return {
                "mode": "qrcode" if qr_code_text else "redirect",
                "method": method,
                "provider": provider,
                "source": order.source or "",
                "instructions": str(payment.get("instructions") or ""),
                "amount": _money_to_number(order.amount),
                "currency": order.currency,
                "plan_name": item.name,
                "billing_cycle": order.billing_cycle or "monthly",
                "expires_at": expires_at,
                "qr_code_text": qr_code_text,
                "payment_url": payment_url,
                "can_mock_confirm": False,
            }

    gateway = get_gateway(method)
    if gateway is not None:
        try:
            checkout = gateway.create_checkout(order, item, payment)
            if checkout.extra:
                merged = dict(order.extra_json or {})
                merged.update(checkout.extra)
                order.extra_json = merged
            return gateway.build_checkout_response(order, item, payment, checkout)
        except RuntimeError:
            if raise_gateway_errors:
                raise

    expire_minutes = int(payment.get("order_expire_minutes") or 30)
    expires_at = order.expired_at or (_utcnow() + datetime.timedelta(minutes=expire_minutes))
    return {
        "method": method,
        "provider": provider,
        "source": order.source or "",
        "instructions": str(payment.get("instructions") or ""),
        "amount": _money_to_number(order.amount),
        "currency": order.currency,
        "plan_name": item.name,
        "billing_cycle": order.billing_cycle or "monthly",
        "expires_at": expires_at,
        "qr_code_text": "",
        "payment_url": "",
        "can_mock_confirm": False,
    }


def _order_for_user(order_no: str, user_id: int, db: Session) -> BillingOrder:
    order = db.query(BillingOrder).filter(BillingOrder.order_no == order_no, BillingOrder.user_id == user_id).first()
    if not order:
        raise HTTPException(404, "订单未找到")
    return _sync_order_status(order, db)


def _character_profile_text(body: dict) -> str:
    raw = body.get("characters", "")
    if not isinstance(raw, str):
        raise HTTPException(400, "角色必须是字符串")
    text = raw.strip()
    if len(text) > MAX_CHARACTER_PROFILE_CHARS:
        raise HTTPException(413, f"角色简介过长，最大长度为 {MAX_CHARACTER_PROFILE_CHARS} 个字符")
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


def _outline_chapter_scope_for_generation(outline: dict | None, chapter_number: int | None) -> dict[str, Any]:
    """为正文生成提取章节边界，避免聊天生成路径预支后续剧情。"""
    if not isinstance(outline, dict) or not isinstance(chapter_number, int) or chapter_number <= 0:
        return {}
    acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
    chapter_cards: list[dict[str, Any]] = []
    for act_index, act in enumerate(acts, start=1):
        if not isinstance(act, dict):
            continue
        act_label = act.get("act", act_index)
        chapters = act.get("chapters") if isinstance(act.get("chapters"), list) else []
        for item in chapters:
            if not isinstance(item, dict):
                continue
            raw_number = item.get("chapter_number")
            if isinstance(raw_number, bool):
                continue
            if isinstance(raw_number, str) and raw_number.strip().isdigit():
                raw_number = int(raw_number.strip())
            if not isinstance(raw_number, int) or raw_number <= 0:
                continue
            chapter_cards.append({
                "chapter_number": raw_number,
                "title": str(item.get("title") or "").strip(),
                "act": item.get("act", act_label),
                "summary": str(item.get("summary") or "").strip(),
                "goal": str(item.get("goal") or "").strip(),
                "conflict": str(item.get("conflict") or "").strip(),
                "hook": str(item.get("hook") or "").strip(),
                "payoff": str(item.get("payoff") or "").strip(),
                "highlight": str(item.get("highlight") or "").strip(),
            })
    if not chapter_cards:
        return {}
    chapter_cards.sort(key=lambda item: item["chapter_number"])
    current = next((item for item in chapter_cards if item["chapter_number"] == chapter_number), None)
    previous = [
        {
            "chapter_number": item["chapter_number"],
            "title": item.get("title"),
            "summary": item.get("summary"),
        }
        for item in chapter_cards
        if item["chapter_number"] < chapter_number
    ][-2:]
    future = [
        {
            "chapter_number": item["chapter_number"],
            "title": item.get("title"),
            "summary": item.get("summary"),
        }
        for item in chapter_cards
        if item["chapter_number"] > chapter_number
    ][:6]
    return {
        "current_chapter_number": chapter_number,
        "current_chapter_card": current or {},
        "previous_chapters_for_continuity": previous,
        "future_chapters_for_boundary_only": future,
        "boundary_rule": "正文只能完成 current_chapter_card 内的本章事件；future_chapters_for_boundary_only 只用于防止预支后文，禁止提前写完。",
    }


def _build_framework_context(story: Story | None, chapter: Chapter | None = None) -> str:
    """Assemble framework constraints from story tags, characters, outline and chapter metadata."""
    if not story:
        return ""
    parts = []
    story_bible = story.story_bible if isinstance(story.story_bible, dict) else {}
    creative_brief = story_bible.get("creative_brief") if isinstance(story_bible.get("creative_brief"), dict) else {}
    writing_guidance = story_bible.get("writing_guidance") if isinstance(story_bible.get("writing_guidance"), dict) else {}
    import_guidance = story_bible.get("import_guidance") if isinstance(story_bible.get("import_guidance"), dict) else {}
    if creative_brief:
        bible_raw = {
            "作品定位": creative_brief.get("project_positioning"),
            "一句话梗概": creative_brief.get("one_line_premise"),
            "核心卖点": creative_brief.get("core_hook"),
            "主角核心": creative_brief.get("protagonist_core"),
            "主线矛盾": creative_brief.get("main_conflict"),
            "长线悬念": creative_brief.get("longline_mystery"),
            "目标篇幅": creative_brief.get("serial_length_target"),
            "揭秘策略": creative_brief.get("reveal_strategy"),
            "节奏策略": creative_brief.get("pacing_strategy"),
            "必保留设定": creative_brief.get("must_keep_rules"),
            "世界观设定": creative_brief.get("world_setting"),
            "开放故事笔记": creative_brief.get("open_story_notes"),
        }
        bible_summary = {k: v for k, v in bible_raw.items() if v not in (None, "", [], {})}
        if bible_summary:
            parts.append(f"作品圣经摘要: {json.dumps(bible_summary, ensure_ascii=False)}")
    if writing_guidance:
        guidance_summary = {
            "开书策略": writing_guidance.get("opening_strategy"),
            "章节密度策略": writing_guidance.get("chapter_density_strategy"),
            "中段驱动力": writing_guidance.get("midgame_engine"),
            "后期方向": writing_guidance.get("late_game_direction"),
            "避免模式": writing_guidance.get("forbidden_patterns"),
            "推荐情节模式": writing_guidance.get("preferred_plot_patterns"),
        }
        parts.append(f"作品圣经写作指导: {json.dumps(guidance_summary, ensure_ascii=False)}")
    if import_guidance:
        import_summary = {
            "导入材料类型": import_guidance.get("import_material_type"),
            "必须保留": import_guidance.get("must_keep"),
            "后续创作目标": import_guidance.get("author_goal"),
            "允许调整范围": import_guidance.get("adjustment_scope"),
            "长线计划": import_guidance.get("longline_plan"),
            "风格边界": import_guidance.get("tone_guardrails"),
        }
        parts.append(
            "导入作品作者约束: "
            + json.dumps(import_summary, ensure_ascii=False)
            + "。如与自由发挥冲突，优先遵守这些导入作品约束。"
        )
    reference_author_profile = story_bible.get("reference_author_profile")
    if isinstance(reference_author_profile, dict) and reference_author_profile:
        profile_parts = extract_author_profile_sections(reference_author_profile)
        parts.extend(profile_parts)
    reference_author_report = story_bible.get("reference_author_report")
    if isinstance(reference_author_report, str) and reference_author_report.strip():
        highlights = extract_report_highlights(reference_author_report)
        parts.append(f"作者画像参考报告（核心要点）:\n{highlights}")
    reference_style_samples = story_bible.get("reference_style_samples")
    if isinstance(reference_style_samples, list) and reference_style_samples:
        parts.append(f"作者原文风格示例: {json.dumps(reference_style_samples, ensure_ascii=False)}")
    story_memory = story.story_memory if isinstance(story.story_memory, dict) else {}
    if story_memory:
        memory_summary = build_story_memory_compact(story_memory)
        if memory_summary:
            parts.append(f"作品连续性记忆: {json.dumps(memory_summary, ensure_ascii=False)}")
    if story.tags:
        parts.append(f"故事标签: {json.dumps(story.tags, ensure_ascii=False)}")
    if story.characters:
        parts.append(f"角色设定: {json.dumps(story.characters, ensure_ascii=False)}")
    if story.outline:
        chapter_scope = _outline_chapter_scope_for_generation(
            story.outline if isinstance(story.outline, dict) else {},
            getattr(chapter, "chapter_number", None) if chapter else None,
        )
        if chapter_scope:
            parts.append(f"章节大纲边界: {json.dumps(chapter_scope, ensure_ascii=False)}")
        else:
            parts.append(f"故事大纲: {json.dumps(story.outline, ensure_ascii=False)}")
    if chapter:
        if chapter.act:
            parts.append(f"当前章节所属幕: {chapter.act}")
        if chapter.key_events:
            parts.append(f"本章关键事件: {json.dumps(chapter.key_events, ensure_ascii=False)}")
        raw_goal_card = getattr(chapter, "goal_card", None)
        goal_card = raw_goal_card if isinstance(raw_goal_card, dict) else {}
        if goal_card:
            parts.append(f"本章目标卡: {json.dumps(goal_card, ensure_ascii=False)}")

    from services.token_utils import compress_context_parts_if_needed
    full_context = {
        "outline": story.outline if isinstance(story.outline, dict) else {},
        "characters": story.characters if isinstance(story.characters, list) else [],
        "story_bible": story.story_bible if isinstance(story.story_bible, dict) else {},
    }
    current_chapter_number = getattr(chapter, "chapter_number", None) if chapter else None
    parts = compress_context_parts_if_needed(
        parts, full_context=full_context, current_chapter_number=current_chapter_number
    )
    return "\n".join(parts)


def _count_words(text: str | None) -> int | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    return len("".join(stripped.split()))


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
    if not isinstance(acts, list) or len(acts) < 2:
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


def _character_big_five_vector(character: dict | None) -> dict[str, int] | None:
    if not isinstance(character, dict):
        return None
    scores = character.get("big_five")
    if not isinstance(scores, dict) or not _has_complete_big_five(scores):
        return None
    vector: dict[str, int] = {}
    alias_map = {
        "O": ("O", "openness"),
        "C": ("C", "conscientiousness"),
        "E": ("E", "extraversion"),
        "A": ("A", "agreeableness"),
        "N": ("N", "neuroticism"),
    }
    for target, aliases in alias_map.items():
        value = None
        for key in aliases:
            if scores.get(key) not in (None, ""):
                value = scores.get(key)
                break
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 10:
            numeric *= 10
        vector[target] = max(0, min(100, int(round(numeric))))
    return vector


def _characters_big_five_feel_generic(characters) -> bool:
    if not isinstance(characters, list) or len(characters) < 2:
        return False
    vectors: list[dict[str, int]] = []
    for item in characters:
        vector = _character_big_five_vector(item)
        if vector:
            vectors.append(vector)
    if len(vectors) < 2:
        return False

    unique_vectors = {
        tuple(vector[key] for key in ("O", "C", "E", "A", "N"))
        for vector in vectors
    }
    if len(unique_vectors) <= 1:
        return True

    dimensions = ("O", "C", "E", "A", "N")
    spread_by_dimension = {
        key: max(vector[key] for vector in vectors) - min(vector[key] for vector in vectors)
        for key in dimensions
    }
    # If every trait differs only a little across the cast, the result is still too flat.
    return max(spread_by_dimension.values()) < 15


def _has_opening_ready_outline(outline: dict | None, story_length: str | None = None) -> bool:
    if not isinstance(outline, dict):
        return False
    acts = outline.get("three_acts")
    if not isinstance(acts, list) or len(acts) < 2:
        return False
    chapters = _extract_outline_chapters(outline)
    if len(chapters) < 3:
        return False

    # 根据故事篇幅决定验证范围
    length_to_max_check = {"short": 5, "medium": 8}
    max_check = min(len(chapters), length_to_max_check.get(story_length or "", 10))

    strategy = _read_serial_strategy(outline)
    # 短/中篇不要求 chapter_10_climax（没有第10章）
    required_strategy_fields = [
        "positioning",
        "opening_hook",
        "first_3_chapter_hook",
    ]
    if max_check >= 10:
        required_strategy_fields.append("chapter_10_climax")
    if any(not str(strategy.get(field) or "").strip() for field in required_strategy_fields):
        return False

    first_chapter = next((item for item in chapters if item.get("chapter_number") == 1), None)
    if not first_chapter:
        return False
    if not str(first_chapter.get("summary") or "").strip():
        return False
    if not str(first_chapter.get("hook") or "").strip():
        return False

    need_detailed = max(3, max_check - 4)
    if _count_detailed_opening_chapters(chapters, upto=max_check) < need_detailed:
        return False
    return True


def _read_serial_strategy(outline: dict | None) -> dict[str, Any]:
    if not isinstance(outline, dict):
        return {}
    raw = outline.get("serial_strategy")
    return raw if isinstance(raw, dict) else {}


def _count_detailed_opening_chapters(chapters: list[dict], upto: int = 10) -> int:
    count = 0
    for chapter in sorted(chapters, key=lambda item: int(item.get("chapter_number", 0))):
        chapter_number = chapter.get("chapter_number")
        if not isinstance(chapter_number, int) or chapter_number < 1 or chapter_number > upto:
            continue
        has_summary = bool(str(chapter.get("summary") or "").strip())
        has_goal_like = any(
            bool(str(chapter.get(field) or "").strip())
            for field in ("goal", "conflict", "hook", "payoff", "highlight")
        )
        key_events = chapter.get("key_events")
        has_events = isinstance(key_events, list) and any(str(item).strip() for item in key_events)
        if has_summary and (has_goal_like or has_events):
            count += 1
    return count


def _framework_launch_quality_issues(framework: dict | None, expected_min_chapters: int = 10) -> list[str]:
    issues: list[str] = []
    if not isinstance(framework, dict):
        return ["返回结果不是有效框架对象"]

    outline = framework.get("outline")
    if not isinstance(outline, dict):
        issues.append("故事大纲缺失")
        return issues

    acts = outline.get("three_acts") if isinstance(outline, dict) else None
    if not isinstance(acts, list) or len(acts) < 2:
        issues.append("主要阶段不足，至少需要 2 个以上阶段来支撑开书和后续扩写")

    chapters = _extract_outline_chapters(outline)
    min_ch = expected_min_chapters
    if len(chapters) < min_ch:
        issues.append(f"开书规划不足，至少需要覆盖前 {min_ch} 章的章节规划")

    detailed_count = _count_detailed_opening_chapters(chapters, upto=min_ch)
    min_detailed = max(3, min_ch - 4)
    if detailed_count < min_detailed:
        issues.append(f"前 {min_ch} 章不够细，至少应有 {min_detailed} 章具备摘要和目标/冲突/钩子等执行信息")

    strategy = _read_serial_strategy(outline)
    required_strategy_fields = [
        "positioning",
        "opening_hook",
        "first_3_chapter_hook",
        "chapter_10_climax",
    ]
    missing_strategy = [field for field in required_strategy_fields if not str(strategy.get(field) or "").strip()]
    if missing_strategy:
        issues.append("开书策略不完整，缺少：" + "、".join(missing_strategy))

    if chapters:
        first_chapter = next((item for item in chapters if item.get("chapter_number") == 1), None)
        if first_chapter:
            if not str(first_chapter.get("hook") or "").strip():
                issues.append("第 1 章缺少明确开篇钩子")
            if not str(first_chapter.get("goal") or "").strip():
                issues.append("第 1 章缺少明确章节目标")
            if not str(first_chapter.get("summary") or "").strip():
                issues.append("第 1 章缺少明确章节摘要")
            characters = framework.get("characters")
            if isinstance(characters, list):
                protagonist = next(
                    (c for c in characters
                     if isinstance(c, dict) and str(c.get("role") or "") in ("主角", "protagonist", "男主", "女主")),
                    None,
                )
                if protagonist and protagonist.get("name"):
                    proto_name = str(protagonist["name"]).strip()
                    chapter_text = " ".join([
                        str(first_chapter.get("hook") or ""),
                        str(first_chapter.get("goal") or ""),
                        str(first_chapter.get("summary") or ""),
                    ])
                    if proto_name and proto_name not in chapter_text:
                        issues.append(f"第 1 章任务卡未包含主角名「{proto_name}」")

    return issues


def _parse_chapter_count_token(raw: str) -> int | None:
    token = str(raw or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)

    token = token.replace("两", "二")
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}

    total = 0
    current = 0
    for char in token:
        if char in digits:
            current = digits[char]
            continue
        if char in units:
            total += (current or 1) * units[char]
            current = 0
            continue
        return None

    value = total + current
    return value if value > 0 else None


def _extract_requested_min_chapters(messages: list[dict] | None) -> int | None:
    if not isinstance(messages, list):
        return None

    count_token = r"(\d{2,4}|[零一二两三四五六七八九十百千]{2,})"
    unit = r"[章节话回]"
    patterns = [
        re.compile(rf"至少\s*{count_token}\s*{unit}"),
        re.compile(rf"{count_token}\s*{unit}\s*起"),
        re.compile(rf"不低于\s*{count_token}\s*{unit}"),
        re.compile(rf"扩展到\s*{count_token}\s*{unit}"),
        re.compile(rf"扩展至\s*{count_token}\s*{unit}"),
        re.compile(rf"拉到\s*{count_token}\s*{unit}"),
        re.compile(rf"写到\s*{count_token}\s*{unit}"),
    ]

    requested: int | None = None
    for item in messages:
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        for pattern in patterns:
            match = pattern.search(content)
            if not match:
                continue
            value = _parse_chapter_count_token(match.group(1))
            if value is None:
                continue
            if value >= 20:
                requested = max(requested or 0, value)
    return requested


def _extract_requested_min_chapters_from_text(text: str | None) -> int | None:
    content = str(text or "").strip()
    if not content:
        return None
    return _extract_requested_min_chapters([{"role": "user", "content": content}])


def _infer_story_bible_min_chapters(story_bible: dict | None) -> int | None:
    if not isinstance(story_bible, dict):
        return None
    creative_brief = story_bible.get("creative_brief")
    raw_input = story_bible.get("raw_input")
    candidates: list[str] = []
    if isinstance(creative_brief, dict):
        candidates.append(str(creative_brief.get("serial_length_target") or "").strip())
    if isinstance(raw_input, dict):
        candidates.append(str(raw_input.get("raw_length_goal") or "").strip())
    requested = None
    for text in candidates:
        value = _extract_requested_min_chapters_from_text(text)
        if value and value >= 20:
            requested = max(requested or 0, value)
    return requested


def _infer_story_length_from_story(story: Story, description: str = "", messages: list | None = None) -> str | None:
    """从 Story 对象中推断篇幅类型 short/medium/long，返回 None 表示无法推断。

    Args:
        story: Story 数据库对象
        description: 用户输入的故事描述文本，作为篇幅推断的补充来源。
        messages: 对话消息列表，用于从用户聊天中提取篇幅信息。
    """
    from services.deepseek import _infer_story_length
    context = {"story_bible": story.story_bible}
    length = _infer_story_length(context, description=description, messages=messages)
    # 如果推断结果仍为 long（默认值），且没有任何有效数据，返回 None 让调用方使用默认行为
    if length == "long":
        story_bible = story.story_bible if isinstance(story.story_bible, dict) else {}
        creative_brief = story_bible.get("creative_brief") if isinstance(story_bible, dict) else None
        raw_input = story_bible.get("raw_input") if isinstance(story_bible, dict) else None
        has_target = (isinstance(creative_brief, dict) and str(creative_brief.get("serial_length_target") or "").strip()) or \
                     (isinstance(raw_input, dict) and str(raw_input.get("raw_length_goal") or "").strip())
        has_desc_hint = bool(description.strip()) and _infer_story_length({}, description=description) != "long"
        has_msg_hint = bool(messages) and _infer_story_length({}, messages=messages) != "long"
        if not has_target and not has_desc_hint and not has_msg_hint:
            return None
    return length


def _is_generic_framework_instruction(text: str | None) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    if not normalized:
        return True
    generic_tokens = (
        "根据作品圣经生成",
        "根据圣经生成",
        "生成小说框架",
        "生成框架",
        "生成大纲",
        "根据作品圣经构建",
        "根据故事圣经生成",
        "请生成框架",
    )
    return any(token in normalized for token in generic_tokens) and len(normalized) <= 30


def _build_creative_brief_from_understanding(understanding: dict) -> dict:
    """从 understanding 字段自动构建创意分析卡，免去 AI 调用"""
    concept = str(understanding.get("concept", "") or "")
    setting = str(understanding.get("setting", "") or "")
    tone = str(understanding.get("tone", "") or "")
    goals = str(understanding.get("goals", "") or "")
    synthesis = str(understanding.get("synthesis", "") or "")
    return {
        "project_positioning": concept,
        "genre": concept,
        "audience": goals,
        "tone": tone,
        "core_hook": setting,
        "one_line_premise": concept,
        "protagonist_core": synthesis,
        "main_conflict": setting,
        "longline_mystery": "",
        "serial_length_target": goals,
        "must_keep_rules": [],
        "reveal_strategy": "",
        "pacing_strategy": "",
        "world_setting": setting,
        "open_story_notes": "",
    }


def _build_framework_seed_description(story: Story) -> str:
    story_bible = story.story_bible if isinstance(story.story_bible, dict) else {}
    creative_brief = story_bible.get("creative_brief") if isinstance(story_bible.get("creative_brief"), dict) else {}
    raw_input = story_bible.get("raw_input") if isinstance(story_bible.get("raw_input"), dict) else {}

    segments: list[str] = []
    if str(creative_brief.get("project_positioning") or "").strip():
        segments.append(f"作品定位：{str(creative_brief.get('project_positioning')).strip()}")
    if str(creative_brief.get("one_line_premise") or "").strip():
        segments.append(f"一句话梗概：{str(creative_brief.get('one_line_premise')).strip()}")
    if str(creative_brief.get("core_hook") or "").strip():
        segments.append(f"核心卖点：{str(creative_brief.get('core_hook')).strip()}")
    if str(creative_brief.get("main_conflict") or "").strip():
        segments.append(f"主线冲突：{str(creative_brief.get('main_conflict')).strip()}")
    if str(creative_brief.get("longline_mystery") or "").strip():
        segments.append(f"长线悬念：{str(creative_brief.get('longline_mystery')).strip()}")
    if str(creative_brief.get("serial_length_target") or "").strip():
        segments.append(f"目标篇幅：{str(creative_brief.get('serial_length_target')).strip()}")
    must_keep = creative_brief.get("must_keep_rules")
    if isinstance(must_keep, list):
        cleaned = [str(item).strip() for item in must_keep if str(item).strip()]
        if cleaned:
            segments.append("必保留设定：" + "；".join(cleaned))
    raw_idea = str(raw_input.get("raw_idea") or "").strip()
    if raw_idea:
        segments.append(f"作者原始创意：{raw_idea}")
    fallback_description = str(story.description or "").strip()
    if not segments and fallback_description:
        segments.append(fallback_description)
    return "\n".join(segments).strip()


# [已迁移至 services.story_state.build_story_bible_compact，保留此处供 diff 参考]
# def _build_story_bible_compact(story_bible: dict | None) -> dict[str, Any]:
#     if not isinstance(story_bible, dict):
#         return {}
#     creative_brief = story_bible.get("creative_brief") if isinstance(story_bible.get("creative_brief"), dict) else {}
#     raw_input = story_bible.get("raw_input") if isinstance(story_bible.get("raw_input"), dict) else {}
#     writing_guidance = story_bible.get("writing_guidance") if isinstance(story_bible.get("writing_guidance"), dict) else {}
#     import_guidance = story_bible.get("import_guidance") if isinstance(story_bible.get("import_guidance"), dict) else {}
#
#     compact: dict[str, Any] = {}
#     for key in (
#         "project_positioning",
#         "one_line_premise",
#         "core_hook",
#         "protagonist_core",
#         "main_conflict",
#         "longline_mystery",
#         "serial_length_target",
#         "reveal_strategy",
#         "pacing_strategy",
#         "world_setting",
#         "open_story_notes",
#     ):
#         value = str(creative_brief.get(key) or "").strip()
#         if value:
#             compact[key] = value
#
#     must_keep_rules = creative_brief.get("must_keep_rules")
#     if isinstance(must_keep_rules, list):
#         cleaned = [str(item).strip() for item in must_keep_rules if str(item).strip()]
#         if cleaned:
#             compact["must_keep_rules"] = cleaned[:8]
#
#     for key in (
#         "opening_strategy",
#         "chapter_density_strategy",
#         "midgame_engine",
#         "late_game_direction",
#     ):
#         value = str(writing_guidance.get(key) or "").strip()
#         if value:
#             compact[key] = value
#
#     for key in ("forbidden_patterns", "preferred_plot_patterns"):
#         raw = writing_guidance.get(key)
#         if isinstance(raw, list):
#             cleaned = [str(item).strip() for item in raw if str(item).strip()]
#             if cleaned:
#                 compact[key] = cleaned[:8]
#
#     for key in ("raw_idea", "raw_length_goal", "raw_must_keep", "raw_hidden_setting"):
#         value = str(raw_input.get(key) or "").strip()
#         if value:
#             compact[key] = value
#
#     for key in (
#         "import_material_type",
#         "must_keep",
#         "author_goal",
#         "adjustment_scope",
#         "longline_plan",
#         "tone_guardrails",
#     ):
#         value = str(import_guidance.get(key) or "").strip()
#         if value:
#             compact[f"import_{key}"] = value
#
#     return compact


# [已迁移至 services.story_state.build_story_memory_compact，保留此处供 diff 参考]
# def _build_story_memory_compact(story_memory: dict | None) -> dict[str, Any]:
#     if not isinstance(story_memory, dict):
#         return {}
#     compact: dict[str, Any] = {}
#     for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
#         value = str(story_memory.get(key) or "").strip()
#         if value:
#             compact[key] = value
#     for key in ("continuity_facts", "open_loops", "resolved_loops"):
#         raw = story_memory.get(key)
#         if isinstance(raw, list):
#             cleaned = [str(item).strip() for item in raw if str(item).strip()]
#             if cleaned:
#                 compact[key] = cleaned[:12]
#     recent_chapter_summaries = story_memory.get("recent_chapter_summaries")
#     if isinstance(recent_chapter_summaries, list):
#         compact["recent_chapter_summaries"] = [
#             item for item in recent_chapter_summaries[-8:]
#             if isinstance(item, dict)
#         ]
#     return compact


def _build_framework_ai_context(story: Story, mode: str = "general", user_instruction: str = "") -> dict:
    outline = story.outline if isinstance(story.outline, dict) else {}
    chapters = _extract_outline_chapters(outline)
    chapter_numbers = [item["chapter_number"] for item in chapters if isinstance(item.get("chapter_number"), int)]
    return {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": outline,
        "story_bible": story.story_bible,
        "story_bible_compact": build_story_bible_compact(story.story_bible),
        "story_memory": story.story_memory,
        "story_memory_compact": build_story_memory_compact(story.story_memory),
        "outline_compact": _build_outline_compact(outline),
        "framework_stats": {
            "mode": mode,
            "stage_count": len(outline.get("three_acts") or []) if isinstance(outline.get("three_acts"), list) else 0,
            "chapter_count": len(chapters),
            "last_chapter_number": max(chapter_numbers) if chapter_numbers else 0,
        },
        "user_instruction": user_instruction.strip(),
    }


async def _complete_framework_payload(
    framework: dict | None,
    description: str,
    api_key: str | None = None,
    story_bible: dict | None = None,
    require_launch_ready: bool = False,
    allow_partial_outline: bool = False,
    fields_to_check: list[str] | None = None,
    story_length: str | None = None,
) -> dict:
    """Normalize and optionally complete framework fields.

    fields_to_check controls which fields get AI backfill:
    - None or ["all"]: check all fields (tags, characters, outline)
    - ["outline"] or ["outline", "chapters"]: only check outline
    - [] or other combos: check only specified fields

    No longer cascades - each field is checked independently.
    No longer runs rescue generate_framework on failure.
    """
    payload = dict(framework or {})
    if isinstance(story_bible, dict) and story_bible:
        payload["story_bible"] = story_bible
    payload["tags"] = payload.get("tags") if isinstance(payload.get("tags"), dict) else {}
    payload["characters"] = _normalize_characters_payload(payload.get("characters") if isinstance(payload.get("characters"), list) else [])
    payload["outline"] = _merge_framework_outline({}, payload.get("outline"), payload.get("chapters"))
    payload["chapters"] = _extract_outline_chapters(payload["outline"])

    story_context = {
        "description": description,
        "tags": payload["tags"],
        "characters": payload["characters"],
        "outline": payload["outline"],
        "story_bible": payload.get("story_bible"),
    }

    if fields_to_check is None:
        fields_to_check = ["all"]

    check_all = "all" in fields_to_check

    if check_all or "tags" in fields_to_check:
        if not _has_complete_tags(payload["tags"]):
            try:
                payload["tags"] = _merge_tags(payload["tags"], await regenerate_tags(story_context, api_key=api_key))
                story_context["tags"] = payload["tags"]
            except Exception as exc:
                logger.warning("Failed to backfill framework tags: %s", exc)

    if check_all or "characters" in fields_to_check:
        if not _has_complete_characters(payload["characters"]) or _characters_big_five_feel_generic(payload["characters"]):
            try:
                payload["characters"] = _merge_characters_payload(
                    payload["characters"],
                    await regenerate_characters_with_variance(story_context, api_key=api_key),
                )
                story_context["characters"] = payload["characters"]
            except Exception as exc:
                logger.warning("Failed to backfill framework characters: %s", exc)

    if check_all or "outline" in fields_to_check:
        outline_ready = (lambda o: _has_opening_ready_outline(o, story_length=story_length)) if require_launch_ready else _has_complete_outline
        if not outline_ready(payload["outline"]):
            try:
                incoming_outline = await regenerate_outline(story_context, api_key=api_key, story_length=story_length)
                payload["outline"] = _merge_framework_outline(
                    payload["outline"],
                    incoming_outline,
                    _extract_outline_chapters(incoming_outline),
                )
                story_context["outline"] = payload["outline"]
            except Exception as exc:
                logger.warning("Failed to backfill framework outline for story_context outline keys=%s acts=%d: %s",
                    list(payload.get("outline", {}).keys()),
                    len(payload.get("outline", {}).get("three_acts") or []),
                    exc)

        payload["chapters"] = _extract_outline_chapters(payload["outline"])
        if not outline_ready(payload["outline"]):
            if allow_partial_outline:
                logger.info("Allowing partial framework update without full outline readiness")
                return payload
            if require_launch_ready:
                raise ValueError("Framework opening structure is still not launch-ready after backfill")
            raise ValueError("Framework outline is still incomplete after backfill")
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
    act = str(raw.get("act") or fallback_act or "").strip() or fallback_act

    payload = {
        "title": title,
        "act": act,
    }
    payload.update(_normalize_chapter_plan_meta(raw))
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


_MOTHER_FEE_PAID_TERMS = ("已支付", "已付", "暂时支付", "暂时续上", "暂时解决", "付清", "缴清", "交上")
_MOTHER_FEE_UNPAID_TERMS = ("未付", "没着落", "无着落", "付不起", "欠费", "还缺", "还差")


def _memory_text_contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_mother_medical_fee_text(text: str) -> bool:
    return "母亲" in text and any(term in text for term in ("药费", "医药费", "治疗费", "医疗费"))


def _normalize_story_memory_consistency(memory: dict) -> dict:
    """保守修正连续性记忆中的母亲药费状态冲突。"""
    fields = ("story_state", "current_arc_focus", "next_payoff_target")
    list_fields = ("continuity_facts", "open_loops")
    fragments: list[str] = []
    for field in fields:
        value = memory.get(field)
        if isinstance(value, str):
            fragments.append(value)
    for field in list_fields:
        value = memory.get(field)
        if isinstance(value, list):
            fragments.extend(str(item) for item in value if isinstance(item, str))

    combined = "\n".join(fragments)
    if not _is_mother_medical_fee_text(combined):
        return memory
    has_paid = _memory_text_contains_any(combined, _MOTHER_FEE_PAID_TERMS)
    has_unpaid = _memory_text_contains_any(combined, _MOTHER_FEE_UNPAID_TERMS)
    if not (has_paid and has_unpaid):
        return memory

    cash_match = re.search(r"(?:口袋|手头)[^。！？；;，,\n]{0,20}\d+\s*元", combined)
    cash_note = f"{cash_match.group(0)}，" if cash_match else "主角手头现金仍紧张，"
    canonical = f"{cash_note}母亲短期药费已暂时续上，但后续治疗费用和债务压力仍在。"

    def normalize_text(value: str) -> str:
        if not _is_mother_medical_fee_text(value):
            return value
        parts = re.split(r"(?<=[。！？；;])\s*", value)
        kept = [
            part.strip()
            for part in parts
            if part.strip()
            and not (
                _is_mother_medical_fee_text(part)
                and (
                    _memory_text_contains_any(part, _MOTHER_FEE_PAID_TERMS)
                    or _memory_text_contains_any(part, _MOTHER_FEE_UNPAID_TERMS)
                )
            )
        ]
        if canonical not in kept:
            kept.append(canonical)
        return "".join(kept)

    for field in fields:
        value = memory.get(field)
        if isinstance(value, str):
            memory[field] = normalize_text(value)

    for field in list_fields:
        value = memory.get(field)
        if not isinstance(value, list):
            continue
        normalized_items: list[str] = []
        seen: set[str] = set()
        replaced = False
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            if _is_mother_medical_fee_text(text) and (
                _memory_text_contains_any(text, _MOTHER_FEE_PAID_TERMS)
                or _memory_text_contains_any(text, _MOTHER_FEE_UNPAID_TERMS)
            ):
                replaced = True
                continue
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                normalized_items.append(text)
        if replaced and canonical.casefold() not in seen:
            normalized_items.append(canonical)
        memory[field] = normalized_items

    logger.info("已归一化 story_memory 中的母亲药费状态冲突")
    return memory


def _merge_story_memory(existing: dict | None, update: dict | None, chapter: Chapter, chapter_summary: dict | None) -> dict:
    memory = dict(existing or {})
    update = update if isinstance(update, dict) else {}
    chapter_summary = chapter_summary if isinstance(chapter_summary, dict) else {}

    for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
        value = str(update.get(key) or "").strip()
        if value:
            memory[key] = value

    def merge_string_list(field: str, limit: int = 20) -> None:
        current = memory.get(field)
        current_items = [str(item).strip() for item in current] if isinstance(current, list) else []
        incoming = update.get(field)
        incoming_items = [str(item).strip() for item in incoming] if isinstance(incoming, list) else []
        merged: list[str] = []
        seen: set[str] = set()
        for item in current_items + incoming_items:
            if not item:
                continue
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        if merged:
            memory[field] = merged[-limit:]

    merge_string_list("continuity_facts", limit=24)
    merge_string_list("open_loops", limit=24)
    merge_string_list("resolved_loops", limit=24)

    open_loops = memory.get("open_loops")
    resolved_loops = memory.get("resolved_loops")
    if isinstance(open_loops, list) and isinstance(resolved_loops, list):
        resolved_keys = {str(item).strip().casefold() for item in resolved_loops if str(item).strip()}
        if resolved_keys:
            memory["open_loops"] = [
                str(item).strip()
                for item in open_loops
                if str(item).strip() and str(item).strip().casefold() not in resolved_keys
            ]

    recent = memory.get("recent_chapter_summaries")
    recent_entries = [dict(item) for item in recent if isinstance(item, dict)] if isinstance(recent, list) else []
    summary_text = str(chapter_summary.get("summary") or "").strip()
    if summary_text:
        entry = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or f"第{chapter.chapter_number}话",
            "summary": summary_text,
        }
        ending_scene = str(chapter_summary.get("ending_scene") or "").strip()
        if ending_scene:
            entry["ending_scene"] = ending_scene
        chapter_handoff = _extract_chapter_handoff(chapter.memory_summary if isinstance(chapter.memory_summary, dict) else {})
        if chapter_handoff:
            entry["handoff"] = chapter_handoff
        recent_entries = [item for item in recent_entries if item.get("chapter_number") != chapter.chapter_number]
        recent_entries.append(entry)
        recent_entries = sorted(recent_entries, key=lambda item: int(item.get("chapter_number") or 0))[-12:]
        memory["recent_chapter_summaries"] = recent_entries

    memory.setdefault("long_term_foreshadowing", [])
    memory.setdefault("volume_summaries", [])
    memory.setdefault("character_state_snapshots", [])

    return _normalize_story_memory_consistency(memory)


async def _refresh_chapter_memory(chapter: Chapter, request: Request, db: Session) -> None:
    if not chapter.novel_content or not chapter.novel_content.strip():
        return
    chapter_id = chapter.id
    chapter_info = {
        "chapter_number": chapter.chapter_number,
        "title": chapter.title or f"第{chapter.chapter_number}话",
        "act": chapter.act or "",
        "key_events": chapter.key_events or [],
    }
    story_context = _story_framework_context(chapter.story)
    novel_content = chapter.novel_content
    deepseek_api_key = _user_deepseek_api_key(request)
    _release_db_transaction(db)
    try:
        memory_payload = await summarize_chapter_memory(
            story_context,
            chapter_info,
            novel_content,
            api_key=deepseek_api_key,
        )
    except Exception as exc:
        logger.warning("Failed to refresh chapter memory for chapter %s: %s", chapter.id, exc)
        return

    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        return
    chapter_summary = memory_payload.get("chapter_summary") if isinstance(memory_payload.get("chapter_summary"), dict) else {}
    chapter_handoff = memory_payload.get("chapter_handoff") if isinstance(memory_payload.get("chapter_handoff"), dict) else {}
    story_memory_update = memory_payload.get("story_memory_update") if isinstance(memory_payload.get("story_memory_update"), dict) else {}
    chapter.memory_summary = {
        "chapter_summary": chapter_summary,
        "chapter_handoff": chapter_handoff,
        "summary": chapter_summary.get("summary"),
        "ending_scene": chapter_summary.get("ending_scene"),
    } if (chapter_summary or chapter_handoff) else None
    chapter.story.story_memory = _merge_story_memory(chapter.story.story_memory, story_memory_update, chapter, chapter_summary)


async def _background_refresh_chapter_memory(
    chapter_id: int,
    api_key: str,
    billing_ctx=None,
    *,
    task_id: str | None = None,
    story_id: int | None = None,
    shot_id: int | None = None,
) -> None:
    """后台异步刷新章节记忆，不阻塞主请求响应。"""
    del task_id, story_id, shot_id
    from services.deepseek import reset_usage_accumulator

    reset_usage_accumulator()
    db = SessionLocal()
    billing_finished = False
    try:
        chapter = db.get(Chapter, chapter_id)
        if not chapter or not chapter.novel_content or not chapter.novel_content.strip():
            return

        chapter_info = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or f"第{chapter.chapter_number}话",
            "act": chapter.act or "",
            "key_events": chapter.key_events or [],
        }
        story_context = _story_framework_context(chapter.story)
        novel_content = chapter.novel_content

        _release_db_transaction(db)
        try:
            memory_payload = await summarize_chapter_memory(
                story_context,
                chapter_info,
                novel_content,
                api_key=api_key,
            )
        except Exception as exc:
            logger.warning("后台刷新章节记忆失败 chapter=%s: %s", chapter_id, exc)
            return

        chapter = db.get(Chapter, chapter_id)
        if not chapter:
            return
        chapter_summary = memory_payload.get("chapter_summary") if isinstance(memory_payload.get("chapter_summary"), dict) else {}
        chapter_handoff = memory_payload.get("chapter_handoff") if isinstance(memory_payload.get("chapter_handoff"), dict) else {}
        story_memory_update = memory_payload.get("story_memory_update") if isinstance(memory_payload.get("story_memory_update"), dict) else {}
        chapter.memory_summary = {
            "chapter_summary": chapter_summary,
            "chapter_handoff": chapter_handoff,
            "summary": chapter_summary.get("summary"),
            "ending_scene": chapter_summary.get("ending_scene"),
        } if (chapter_summary or chapter_handoff) else None
        chapter.story.story_memory = _merge_story_memory(chapter.story.story_memory, story_memory_update, chapter, chapter_summary)
        db.commit()
        _finish_streaming_platform_points(billing_ctx, success=True)
        billing_finished = True
    except Exception as exc:
        logger.warning("后台刷新章节记忆异常 chapter=%s: %s", chapter_id, exc, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if billing_ctx is not None and not billing_finished:
            _finish_streaming_platform_points(
                billing_ctx,
                success=False,
                error_code="chapter_memory_refresh_failed",
            )
        db.close()


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


def _apply_generated_framework_to_story(
    story,
    framework: dict,
    raw_description: str | None,
    resolved_description: str,
) -> None:
    """将 AI 生成的框架数据写入 story 对象（不包含 DB commit 和快照）。

    这是从 generate_framework_endpoint 抽出的纯函数，方便测试。
    """
    if raw_description and not _is_generic_framework_instruction(raw_description):
        story.description = raw_description
    elif not str(story.description or "").strip():
        story.description = resolved_description
    story.tags = _merge_tags(story.tags, framework.get("tags"))
    story.characters = _normalize_characters_payload(framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))


def _story_framework_context(story: Story) -> dict:
    return _build_framework_ai_context(story)


def _extract_chapter_handoff(memory_summary: dict | None) -> dict[str, Any]:
    if not isinstance(memory_summary, dict):
        return {}
    handoff = memory_summary.get("chapter_handoff")
    return dict(handoff) if isinstance(handoff, dict) else {}


def _compact_chapter_memory(chapter: Chapter) -> dict[str, Any]:
    memory_summary = chapter.memory_summary if isinstance(chapter.memory_summary, dict) else {}
    chapter_summary = memory_summary.get("chapter_summary") if isinstance(memory_summary.get("chapter_summary"), dict) else {}
    handoff = _extract_chapter_handoff(memory_summary)
    summary_text = str(
        chapter_summary.get("summary")
        or memory_summary.get("summary")
        or ""
    ).strip()
    compact: dict[str, Any] = {
        "chapter_number": chapter.chapter_number,
        "title": chapter.title or f"第{chapter.chapter_number}章",
    }
    if summary_text:
        compact["summary"] = summary_text
    ending_scene = str(chapter_summary.get("ending_scene") or memory_summary.get("ending_scene") or "").strip()
    if ending_scene:
        compact["ending_scene"] = ending_scene
    if handoff:
        compact["handoff"] = handoff
    return compact


def _build_previous_chapter_bridge(
    story_id: int,
    target_chapter_number: int | None,
    db: Session,
) -> dict[str, Any]:
    if not isinstance(target_chapter_number, int) or target_chapter_number <= 1:
        return {"summary_text": "", "handoff": {}, "previous_chapter": None}

    prev_chapter = (
        db.query(Chapter)
        .filter(
            Chapter.story_id == story_id,
            Chapter.chapter_number < target_chapter_number,
            Chapter.novel_content.isnot(None),
            Chapter.status.in_(["completed", "draft", "reviewed"]),
        )
        .order_by(Chapter.chapter_number.desc())
        .first()
    )
    if not prev_chapter:
        return {"summary_text": "", "handoff": {}, "previous_chapter": None}

    memory_summary = prev_chapter.memory_summary if isinstance(prev_chapter.memory_summary, dict) else {}
    chapter_summary = memory_summary.get("chapter_summary") if isinstance(memory_summary.get("chapter_summary"), dict) else {}
    handoff = _extract_chapter_handoff(memory_summary)
    ending_scene = str(chapter_summary.get("ending_scene") or memory_summary.get("ending_scene") or "").strip()
    summary_text = str(chapter_summary.get("summary") or memory_summary.get("summary") or "").strip()
    fallback_tail = (prev_chapter.novel_content or "")[-800:].strip()

    parts = [f"上一章《第{prev_chapter.chapter_number}章：{prev_chapter.title or ''}》"]
    if summary_text:
        parts.append(f"章节摘要：{summary_text}")
    if ending_scene:
        parts.append(f"结尾场景：{ending_scene}")
    if fallback_tail and not ending_scene:
        parts.append(f"正文结尾片段：\n{fallback_tail}")
    if handoff.get("opening_must_continue"):
        parts.append(f"下一章必须承接：{handoff['opening_must_continue']}")
    if handoff.get("active_conflict"):
        parts.append(f"即时冲突：{handoff['active_conflict']}")
    return {
        "summary_text": "\n".join(parts)[:2400],
        "handoff": handoff,
        "previous_chapter": prev_chapter,
    }


def _build_chapter_runtime_context(
    story: Story,
    db: Session,
    chapter_info: dict[str, Any],
    *,
    user_instruction: str = "",
) -> dict[str, Any]:
    context = _build_framework_ai_context(story, mode="chapter_runtime", user_instruction=user_instruction)
    target_chapter_number = chapter_info.get("chapter_number")
    previous_bridge = _build_previous_chapter_bridge(story.id, target_chapter_number if isinstance(target_chapter_number, int) else None, db)
    recent_candidates = (
        db.query(Chapter)
        .filter(
            Chapter.story_id == story.id,
            Chapter.chapter_number < (target_chapter_number if isinstance(target_chapter_number, int) else 10**9),
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(3)
        .all()
    )
    recent_memories = [_compact_chapter_memory(item) for item in reversed(recent_candidates) if _compact_chapter_memory(item)]
    current_card = {
        "chapter_number": chapter_info.get("chapter_number"),
        "title": chapter_info.get("title"),
        "act": chapter_info.get("act"),
        "summary": chapter_info.get("summary"),
        "goal": chapter_info.get("goal"),
        "conflict": chapter_info.get("conflict"),
        "hook": chapter_info.get("hook"),
        "payoff": chapter_info.get("payoff"),
        "highlight": chapter_info.get("highlight"),
        "key_events": chapter_info.get("key_events"),
    }
    context["current_chapter"] = {key: value for key, value in current_card.items() if value not in (None, "", [], {})}
    context["previous_chapter_handoff"] = previous_bridge.get("handoff") or {}
    context["recent_chapter_memories"] = recent_memories
    return context


def _build_chapter_continuity_context_text(story_context: dict[str, Any]) -> str:
    parts: list[str] = []
    current_chapter = story_context.get("current_chapter")
    if isinstance(current_chapter, dict) and current_chapter:
        parts.append("当前章节任务卡: " + json.dumps(current_chapter, ensure_ascii=False))
    previous_handoff = story_context.get("previous_chapter_handoff")
    if isinstance(previous_handoff, dict) and previous_handoff:
        parts.append("上一章交接包: " + json.dumps(previous_handoff, ensure_ascii=False))
    recent_memories = story_context.get("recent_chapter_memories")
    if isinstance(recent_memories, list) and recent_memories:
        parts.append("近期章节记忆: " + json.dumps(recent_memories[-3:], ensure_ascii=False))
    return "\n".join(parts)


async def _ensure_generated_chapter_continuity(
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    content: str,
    request: Request,
    system_prompt: str | None = None,
) -> str:
    previous_handoff = story_context.get("previous_chapter_handoff")
    if not isinstance(previous_handoff, dict) or not previous_handoff:
        return content

    opening_sample = (content or "")[:900]
    expected_signals: list[str] = []
    for key in ("ending_location", "active_conflict", "opening_must_continue"):
        value = str(previous_handoff.get(key) or "").strip()
        if value:
            expected_signals.append(value[:24])
    active_characters = previous_handoff.get("active_characters")
    if isinstance(active_characters, list):
        expected_signals.extend(str(item).strip() for item in active_characters[:2] if str(item).strip())
    matched = sum(1 for item in expected_signals if item and item in opening_sample)
    if matched >= 1 or not expected_signals:
        return content

    instruction = (
        "请只修正本章开头的连续性问题，重点是让开头自然承接上一章结尾，"
        "不要重写整章主线，不要改变已成立事件。"
    )
    instruction += "\n上一章交接包：" + json.dumps(previous_handoff, ensure_ascii=False)
    instruction += "\n当前问题：本章开头没有充分体现上一章结尾的地点、在场角色或即时冲突。"
    return await adjust_chapter_content(
        story_context,
        chapter_info,
        content,
        instruction,
        api_key=_user_deepseek_api_key(request),
        system_prompt=system_prompt,
    )


def _unlink_file(path: Path, label: str) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete %s %s: %s", label, path, exc)
        raise HTTPException(409, f"{label} 文件正在使用中，请稍后再试")


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
        raise HTTPException(409, f"{label} 文件正在使用中，请稍后再试")


def _chapter_dir(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"


def _initialize_empty_chapter_workspace(chapter_id: int) -> None:
    chapter_dir = _chapter_dir(chapter_id)
    _rmtree_best_effort(chapter_dir, "stale chapter workspace")


def _scene_meta_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "scenes_meta.json"


def _storyboard_payload(scenes: list[str], sanitized_indices: list[int] | None = None) -> dict:
    normalized_scenes = [str(scene).strip() for scene in scenes if str(scene).strip()]
    normalized_indices = sorted({
        int(index)
        for index in (sanitized_indices or [])
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(normalized_scenes)
    })
    return {
        "schema_version": 1,
        "scenes": normalized_scenes,
        "sanitized_indices": normalized_indices,
    }


def _chapter_storyboard(chapter: Chapter) -> tuple[list[str], list[int]] | None:
    payload = getattr(chapter, "manga_storyboard_json", None)
    if not isinstance(payload, dict):
        return None
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list):
        return None
    scenes = [str(scene).strip() for scene in raw_scenes if isinstance(scene, str) and scene.strip()]
    if len(scenes) != len(raw_scenes) or len(scenes) > MAX_IMAGE_COUNT:
        return None
    raw_indices = payload.get("sanitized_indices")
    sanitized_indices = sorted({
        int(index)
        for index in (raw_indices if isinstance(raw_indices, list) else [])
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(scenes)
    })
    return scenes, sanitized_indices


def _persist_chapter_storyboard(
    chapter_id: int,
    scenes: list[str],
    sanitized_indices: list[int] | None = None,
    *,
    db: Session | None = None,
    chapter: Chapter | None = None,
) -> None:
    owns_session = db is None
    write_db = db or SessionLocal()
    try:
        target = chapter or write_db.get(Chapter, chapter_id)
        if target is None:
            return
        target.manga_storyboard_json = _storyboard_payload(scenes, sanitized_indices)
        write_db.add(target)
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        if owns_session:
            write_db.close()


def _write_scenes_projection(
    chapter_id: int,
    scenes: list[str],
    sanitized_indices: list[int] | None = None,
) -> None:
    backend_dir = Path(__file__).resolve().parent
    with scenes_file_lock(backend_dir, chapter_id):
        _write_scenes_projection_unlocked(chapter_id, scenes, sanitized_indices)


def _write_scenes_projection_unlocked(
    chapter_id: int,
    scenes: list[str],
    sanitized_indices: list[int] | None = None,
) -> None:
    backend_dir = Path(__file__).resolve().parent
    write_scenes_text_atomic(backend_dir, chapter_id, render_scenes_text(scenes))
    meta_path = _scene_meta_path(chapter_id)
    payload = {"sanitized_indices": sorted(set(sanitized_indices or []))}
    atomic_write_text(meta_path, json.dumps(payload, ensure_ascii=False))


def _write_scenes_file(
    chapter_id: int,
    scenes: list[str],
    sanitized_indices: list[int] | None = None,
    *,
    db: Session | None = None,
    chapter: Chapter | None = None,
) -> None:
    backend_dir = Path(__file__).resolve().parent
    with scenes_file_lock(backend_dir, chapter_id):
        _persist_chapter_storyboard(
            chapter_id,
            scenes,
            sanitized_indices,
            db=db,
            chapter=chapter,
        )
        try:
            _write_scenes_projection_unlocked(chapter_id, scenes, sanitized_indices)
        except OSError:
            logger.exception("写入分镜兼容文件失败 chapter_id=%s", chapter_id)


def _parse_scenes_text(raw: str) -> list[str]:
    return parse_stored_scenes_text(raw)


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
        from services.agent_service import _scenes_file_lock

        with _scenes_file_lock(chapter.id):
            scenes_path = chapter_dir / "scenes.txt"
            if scenes_path.exists():
                _unlink_file(scenes_path, "scenes.txt")
        for img in list(chapter.images):
            img_path = Path(__file__).resolve().parent / img.image_path
            if img_path.exists():
                _unlink_file(img_path, "manga image")
            db.delete(img)
    chapter.manga_storyboard_json = _storyboard_payload([])


def _clear_chapter_images_only(chapter: Chapter, db: Session) -> None:
    for img in list(chapter.images):
        img_path = Path(__file__).resolve().parent / img.image_path
        if img_path.exists():
            _unlink_file(img_path, "manga image")
        db.delete(img)


def _decode_png_upload(b64: str) -> bytes:
    if not b64:
        raise HTTPException(400, "未提供图片")
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        import base64
        import binascii
        import io

        from PIL import Image, UnidentifiedImageError

        img_bytes = base64.b64decode(b64, validate=True)
        if len(img_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"图片太大，最大尺寸为 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        with Image.open(io.BytesIO(img_bytes)) as img:
            img.verify()
        with Image.open(io.BytesIO(img_bytes)) as img:
            output = io.BytesIO()
            img.convert("RGBA").save(output, format="PNG", optimize=True)
            png_bytes = output.getvalue()
        if len(png_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"图片处理后太大，最大尺寸为 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        return png_bytes
    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(400, "无效的 base64 图片数据")
    except UnidentifiedImageError:
        raise HTTPException(400, "上传的文件不是有效图片")


def _decode_edit_mask_upload(b64: str, target_size: tuple[int, int]) -> bytes:
    if not b64:
        raise HTTPException(400, "未提供遮罩")
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
            raise HTTPException(413, f"遮罩处理后太大，最大尺寸为 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        return normalized
    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(400, "无效的 base64 遮罩数据")
    except UnidentifiedImageError:
        raise HTTPException(400, "上传的遮罩不是有效图片")


# ── 启动事件已迁移到 lifespan 函数（见文件顶部 app=FastAPI(...) 附近） ──


# ─── Story CRUD ─────────────────────────────────────────────

@app.get("/api/install/status")
def install_status():
    status = _refresh_install_status()
    return {
        "installed": bool(status.get("installed")),
        "source": status.get("source") or "unknown",
        "database_reachable": status.get("database_reachable"),
        "database_error": status.get("database_error"),
        "requires_restart": bool(status.get("requires_restart")),
    }


def _ensure_not_installed_for_install_api() -> None:
    status = _refresh_install_status()
    if status.get("installed"):
        raise HTTPException(409, "系统已安装，不能重复执行安装程序")


@app.post("/api/install/test-database")
def install_test_database(body: dict):
    _ensure_not_installed_for_install_api()
    try:
        database_url = build_database_url(body or {})
        return test_database_url(database_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"数据库连接失败: {exc}") from exc


@app.post("/api/install/test-redis")
def install_test_redis(body: dict):
    _ensure_not_installed_for_install_api()
    try:
        redis_url = build_redis_url(body or {})
        return test_redis_url(redis_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Redis 连接失败: {exc}") from exc


@app.post("/api/install/complete")
def install_complete(body: dict):
    global INSTALL_REQUIRES_RESTART, INSTALL_STATUS, SYSTEM_READY
    _ensure_not_installed_for_install_api()

    database_config = body.get("database") if isinstance(body.get("database"), dict) else {}
    redis_config = body.get("redis") if isinstance(body.get("redis"), dict) else {}
    admin_config = body.get("admin") if isinstance(body.get("admin"), dict) else {}

    try:
        admin_config = validate_install_admin_config(admin_config)
        database_url = build_database_url(database_config)
        redis_url = build_redis_url(redis_config)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        test_database_url(database_url)
        test_redis_url(redis_url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    install_engine = create_install_engine(database_url)
    InstallSession = sessionmaker(bind=install_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    admin_user_payload: dict[str, Any] = {}
    try:
        if database_has_install_markers(install_engine):
            raise HTTPException(409, "目标数据库已有用户或平台配置，不能重复执行安装程序")
        init_db(bind_engine=install_engine, run_migrations=True, raise_errors=True)
        db = InstallSession()
        try:
            _ensure_platform_seed(db, commit=False)
            admin_user = _create_install_admin_user(admin_config, db)
            admin_user_payload = {"id": admin_user.id, "email": admin_user.email, "name": admin_user.name}
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(500, f"初始化管理员失败: {exc}") from exc
        finally:
            db.close()

        env_result = write_env_updates({
            "DATABASE_URL": database_url,
            "REDIS_URL": redis_url,
            "REDIS_ENABLED": "true",
            "SYSTEM_INSTALLED": "true",
        })
        SYSTEM_READY = False
        INSTALL_REQUIRES_RESTART = True
        INSTALL_STATUS = {
            "installed": True,
            "source": "installer",
            "database_reachable": True,
            "requires_restart": True,
        }
        return {
            "ok": True,
            "installed": True,
            "requires_restart": True,
            "message": "安装完成，请重启后端或 PM2 后刷新页面。",
            "database_url": redact_url(database_url),
            "redis_url": redact_url(redis_url),
            "admin": admin_user_payload,
            **env_result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"安装失败: {exc}") from exc
    finally:
        install_engine.dispose()


@app.post("/api/install/restart")
def install_restart():
    status = _refresh_install_status()
    if not status.get("requires_restart"):
        raise HTTPException(409, "系统当前不处于安装后待重启状态")
    try:
        restart_result = request_backend_restart()
        return {"ok": True, **restart_result}
    except Exception as exc:
        raise HTTPException(500, f"自动重启失败: {exc}") from exc


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
    _validate_new_password(password)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "该邮箱已注册")
    if bool(_auth_settings_snapshot(db).get("require_email_code_for_register")):
        _consume_email_verification_code(email, "register", verification_code, db)

    user = User(email=email, password_hash=_password_hash(password), name=name, role="user", status="active", email_verified=True)
    db.add(user)
    db.flush()
    try:
        from decimal import Decimal as _Decimal

        from services.points import accounts as points_accounts
        from services.points.pricing import quantize_points

        if bool(_get_platform_setting("points.register_grant_enabled", db, False)):
            grant_amt = quantize_points(_Decimal(str(_get_platform_setting("points.register_grant_amount", db, 0) or 0)))
            if grant_amt > 0:
                points_accounts.credit_points(
                    db,
                    user.id,
                    grant_amt,
                    entry_type="register_grant",
                    idempotency_key=f"register_grant:{user.id}",
                    metadata={"source": "register"},
                )
    except Exception:
        logger.exception("注册赠送积分失败 user_id=%s", user.id)
    token = _new_session_token()
    db.add(UserSession(user_id=user.id, token=_session_token_fingerprint(token)))
    db.commit()
    return {"token": token, "user": _serialize_auth_user(user, db)}


@app.post("/api/auth/login")
def login(body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    email = _normalize_email(body.get("email"))
    password = str(body.get("password") or "").strip()
    verification_code = str(body.get("verification_code") or "").strip()
    user = db.query(User).filter(User.email == email).first()
    if not user or not _verify_password(password, user.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    if user.status != "active":
        raise HTTPException(403, "账号已被停用")
    if bool(_auth_settings_snapshot(db).get("require_email_code_for_login")):
        _consume_email_verification_code(email, "login", verification_code, db)
    if _password_needs_rehash(user.password_hash):
        user.password_hash = _password_hash(password)
    token = _new_session_token()
    db.add(UserSession(user_id=user.id, token=_session_token_fingerprint(token)))
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
        if not user or user.status != "active":
            return _issue_email_verification_code(email, purpose, db, deliver=False)
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
        sess = _find_active_session(token, db)
        if sess:
            sess.revoked_at = datetime.datetime.utcnow()
            db.commit()
    return {"ok": True}


@app.put("/api/user/password")
def change_password(request: Request, body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    old_password = str(body.get("old_password") or "").strip()
    new_password = str(body.get("new_password") or "").strip()
    if not old_password or not new_password:
        raise HTTPException(400, "请输入旧密码和新密码")
    if not _verify_password(old_password, user.password_hash):
        raise HTTPException(403, "旧密码不正确")
    _validate_new_password(new_password)
    if new_password == old_password:
        raise HTTPException(400, "新密码不能与旧密码相同")
    user.password_hash = _password_hash(new_password)
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": _utcnow()}, synchronize_session=False)
    _write_audit_log(user, "user.change_password", "user", user.id, f"用户 {user.name}({user.email}) 修改了密码", db)
    db.commit()
    return {"ok": True}


@app.post("/api/auth/forgot-password")
def forgot_password(body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    email = _normalize_email(body.get("email"))
    _validate_email_format(email)
    user = db.query(User).filter(User.email == email).first()
    if not user or user.status != "active":
        return _issue_email_verification_code(email, "reset", db, deliver=False)
    return _issue_email_verification_code(email, "reset", db)


@app.post("/api/auth/reset-password")
def reset_password(body: dict, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    email = _normalize_email(body.get("email"))
    verification_code = str(body.get("verification_code") or "").strip()
    new_password = str(body.get("new_password") or "").strip()
    user = db.query(User).filter(User.email == email).first()
    if not user or user.status != "active":
        raise HTTPException(400, "邮箱验证码不正确")
    _validate_new_password(new_password)
    _consume_email_verification_code(email, "reset", verification_code, db)
    user.password_hash = _password_hash(new_password)
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": _utcnow()}, synchronize_session=False)
    _write_audit_log(None, "system.reset_password", "user", user.id, f"用户 {user.name}({user.email}) 通过邮箱验证重置了密码", db)
    db.commit()
    return {"ok": True, "message": "密码已重置，请使用新密码登录"}




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
    payment = _payment_settings_snapshot(db)
    if order.status == "pending":
        gateway = get_gateway(order.payment_method or "")
        if gateway is not None:
            sync_result = gateway.sync_status(order, payment)
            if sync_result and sync_result.status_changed:
                if sync_result.new_status == "paid":
                    _mark_order_paid(order, db, note=f"{gateway.provider} sync confirmed trade {sync_result.trade_no}")
                elif sync_result.new_status == "cancelled":
                    _mark_order_cancelled(order, db, note=f"{gateway.provider} sync closed trade {sync_result.trade_no}")
                db.commit()
                db.refresh(order)
    checkout_payload = None
    if order.status == "pending":
        payment_with_ip = dict(payment)
        payment_with_ip["client_ip"] = request.client.host if request.client else ""
        checkout_payload = _order_checkout_payload(order, None, db, payment_override=payment_with_ip)

    return {
        "ok": True,
        "status": order.status,
        "order": _serialize_order_with_db(order, db),
        "checkout": checkout_payload,
    }


@app.get("/api/billing/payment-config")
def billing_payment_config(db: Session = Depends(get_db)):
    """返回公开支付配置，含可用支付方式选项"""
    _ensure_platform_seed(db)
    return _public_payment_config(db)





@app.post("/api/me/orders/{order_no}/mock-confirm")
def my_order_mock_confirm(order_no: str, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    if not _mock_payments_enabled():
        raise HTTPException(403, "模拟支付仅允许在显式启用的开发环境中使用")
    order = _order_for_user(order_no, user.id, db)
    if order.status != "pending":
        raise HTTPException(400, f"Order cannot be confirmed from status {order.status}")
    if order.payment_method != "mock_qr":
        raise HTTPException(400, "此处只能手动确认模拟支付订单")
    _mark_order_paid(order, db, operator_user_id=user.id, note=f"Mock payment confirmed by {user.name}")
    _write_audit_log(user, "confirm_mock_payment", "billing_order", order.order_no, f"Confirmed mock payment", db, {
        "order_no": order.order_no,
    })
    db.commit()
    db.refresh(order)
    return {
        "ok": True,
        "status": order.status,
        "order": _serialize_order_with_db(order, db),
    }


@app.post("/api/me/orders/{order_no}/cancel")
def my_order_cancel(order_no: str, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    order = _order_for_user(order_no, user.id, db)
    if order.status != "pending":
        raise HTTPException(400, f"Order cannot be cancelled from status {order.status}")
    _mark_order_cancelled(order, db, operator_user_id=user.id, note=f"Cancelled by {user.name}")
    _write_audit_log(user, "cancel_order", "billing_order", order.order_no, "User cancelled checkout", db, {
        "order_no": order.order_no,
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

    gateway = get_gateway("alipay_qr")
    if gateway is None:
        return Response("failure", media_type="text/plain", status_code=500)

    payment = _payment_settings_snapshot(db)
    result = gateway.verify_notify(payload, payment)
    if not result.verified:
        return Response("failure", media_type="text/plain", status_code=400)

    order_no = payload.get("out_trade_no", "").strip()
    trade_status = payload.get("trade_status", "").strip()
    trade_no = payload.get("trade_no", "").strip()
    total_amount = payload.get("total_amount", "").strip()
    order = (
        db.query(BillingOrder)
        .filter(BillingOrder.order_no == order_no)
        .with_for_update()
        .first()
    )
    if not order:
        return Response("failure", media_type="text/plain", status_code=404)
    if order.payment_provider != "alipay":
        return Response("failure", media_type="text/plain", status_code=400)
    extra = dict(order.extra_json or {})
    extra.update({
        "alipay_trade_no": trade_no,
        "alipay_notify_payload": payload,
    })
    order.extra_json = extra
    if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        if not _payment_amount_matches(order.amount, total_amount):
            return Response("failure", media_type="text/plain", status_code=400)
        first_confirmation = order.status != "paid"
        _mark_order_paid(order, db, note=f"Alipay notify confirmed trade {trade_no}")
        if first_confirmation:
            _write_audit_log(None, "alipay_notify_paid", "billing_order", order.order_no, "Alipay async notify marked order paid", db, {
                "order_no": order.order_no,
                "trade_no": trade_no,
            })
    elif trade_status in {"TRADE_CLOSED"}:
        _mark_order_cancelled(order, db, note=f"Alipay notify closed trade {trade_no}")
    db.commit()
    return Response("success", media_type="text/plain")


@app.post("/api/payments/epay/notify")
@app.post("/epay/notify")
async def epay_notify(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    payload = {key: value for key, value in parse_qsl(raw_body, keep_blank_values=True)}

    gateway = get_gateway("epay_qr")
    if gateway is None:
        return Response("failure", media_type="text/plain", status_code=500)
    result = gateway.verify_notify(payload, _payment_settings_snapshot(db))
    if not result.verified:
        return Response("failure", media_type="text/plain", status_code=400)

    order_no = str(payload.get("out_trade_no") or "").strip()
    order = (
        db.query(BillingOrder)
        .filter(BillingOrder.order_no == order_no)
        .with_for_update()
        .first()
    )
    if not order:
        return Response("failure", media_type="text/plain", status_code=404)
    if order.payment_provider != "epay":
        return Response("failure", media_type="text/plain", status_code=400)

    trade_no = str(result.trade_no or "").strip()
    extra = dict(order.extra_json or {})
    extra.update({"epay_trade_no": trade_no, "epay_notify_payload": payload})
    order.extra_json = extra
    if result.trade_status == "paid":
        if not _payment_amount_matches(order.amount, result.amount):
            return Response("failure", media_type="text/plain", status_code=400)
        first_confirmation = order.status != "paid"
        _mark_order_paid(order, db, note=f"Epay notify confirmed trade {trade_no}")
        if first_confirmation:
            _write_audit_log(None, "epay_notify_paid", "billing_order", order.order_no, "Epay async notify marked order paid", db, {
                "order_no": order.order_no,
                "trade_no": trade_no,
            })
    elif result.trade_status == "failed":
        _mark_order_cancelled(order, db, note=f"Epay notify closed trade {trade_no}")
    db.commit()
    return Response("success", media_type="text/plain")


@app.post("/api/payments/mapay/notify")
@app.post("/mapay/notify")
async def mapay_notify(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    payload = {key: value for key, value in parse_qsl(raw_body, keep_blank_values=True)}

    gateway = get_gateway("mapay_qr")
    if gateway is None:
        return Response("failure", media_type="text/plain", status_code=500)

    payment = _payment_settings_snapshot(db)
    result = gateway.verify_notify(payload, payment)
    if not result.verified:
        return Response("failure", media_type="text/plain", status_code=400)

    order_no = payload.get("out_trade_no", "").strip()
    trade_no = payload.get("trade_no", "").strip()
    notify_amount = payload.get("money", "").strip()
    order = (
        db.query(BillingOrder)
        .filter(BillingOrder.order_no == order_no)
        .with_for_update()
        .first()
    )
    if not order:
        return Response("failure", media_type="text/plain", status_code=404)
    if order.payment_provider != "mapay":
        return Response("failure", media_type="text/plain", status_code=400)

    extra = dict(order.extra_json or {})
    extra.update({
        "mapay_trade_no": trade_no,
        "mapay_notify_payload": payload,
    })
    order.extra_json = extra

    if result.trade_status == "paid":
        if not _payment_amount_matches(order.amount, notify_amount):
            return Response("failure", media_type="text/plain", status_code=400)
        first_confirmation = order.status != "paid"
        _mark_order_paid(order, db, note=f"MaPay notify confirmed trade {trade_no}")
        if first_confirmation:
            _write_audit_log(None, "mapay_notify_paid", "billing_order", order.order_no, "MaPay async notify marked order paid", db, {
                "order_no": order.order_no,
                "trade_no": trade_no,
            })
    elif result.trade_status == "failed":
        _mark_order_cancelled(order, db, note=f"MaPay notify closed trade {trade_no}")

    db.commit()
    return Response("success", media_type="text/plain")




@app.get("/api/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    users = db.query(User).order_by(User.created_at.desc()).all()
    user_ids = [user.id for user in users]
    accounts = (
        db.query(PointsAccount)
        .filter(PointsAccount.user_id.in_(user_ids))
        .all()
        if user_ids
        else []
    )
    account_by_user_id = {account.user_id: account for account in accounts}
    result = []
    for user in users:
        account = account_by_user_id.get(user.id)
        result.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "allow_api_key_override": bool(user.allow_api_key_override),
            "allow_api_url_override": bool(user.allow_api_url_override),
            "created_at": user.created_at,
            "points_available": float(account.available_points) if account else 0,
            "points_reserved": float(account.reserved_points) if account else 0,
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
        raise HTTPException(400, "邮箱和密码必填")
    _validate_email_format(email)
    _validate_new_password(password)
    if role not in {"user", "admin"}:
        raise HTTPException(400, "角色必须是 user 或 admin")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "邮箱已存在")
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
        raise HTTPException(404, "用户未找到")
    if body.get("name") is not None:
        user.name = str(body.get("name") or user.name).strip() or user.name
    if body.get("email") is not None:
        email = str(body.get("email") or "").strip().lower()
        _validate_email_format(email)
        existing = db.query(User).filter(User.email == email, User.id != user.id).first()
        if existing:
            raise HTTPException(409, "邮箱已存在")
        if email:
            user.email = email
    if body.get("role") is not None:
        role = str(body.get("role") or "").strip().lower()
        if role not in {"user", "admin"}:
            raise HTTPException(400, "角色必须是 user 或 admin")
        if user.id == admin.id and role != "admin":
            raise HTTPException(400, "不能取消当前管理员自己的管理员权限")
        user.role = role
    if body.get("status") is not None:
        status = str(body.get("status") or "").strip().lower()
        if status not in {"active", "disabled"}:
            raise HTTPException(400, "状态必须是 active 或 disabled")
        if user.id == admin.id and status != "active":
            raise HTTPException(400, "不能停用当前管理员自己的账号")
        user.status = status
    if body.get("allow_api_key_override") is not None:
        user.allow_api_key_override = bool(body.get("allow_api_key_override"))
    if body.get("allow_api_url_override") is not None:
        user.allow_api_url_override = bool(body.get("allow_api_url_override"))
    if body.get("password"):
        new_password = str(body.get("password")).strip()
        _validate_new_password(new_password)
        user.password_hash = _password_hash(new_password)
    if body.get("password") or user.status != "active":
        db.query(UserSession).filter(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        ).update({"revoked_at": _utcnow()}, synchronize_session=False)
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
        raise HTTPException(404, "用户未找到")
    if user.id == admin.id:
        raise HTTPException(400, "不能删除当前管理员")
    user.status = "disabled"
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": _utcnow()}, synchronize_session=False)
    _write_audit_log(admin, "disable_user", "user", user.id, f"停用用户 {user.email}", db, {"email": user.email})
    db.commit()
    return {"ok": True}


@app.get("/api/admin/users/{user_id}/stories")
def admin_user_stories(user_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户未找到")
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
        raise HTTPException(404, "作品未找到")
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


@app.get("/api/admin/platform/settings")
def admin_platform_settings(request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    _require_admin(request, db)
    return _admin_platform_settings_snapshot(db)


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
        raise HTTPException(404, "平台图标未配置")
    try:
        import base64

        icon_bytes = base64.b64decode(icon_data, validate=True)
    except Exception:
        raise HTTPException(500, "存储的平台图标无效")
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
    pricing = body.get("pricing") if isinstance(body.get("pricing"), dict) else {}
    mappings = {
        "platform.site_name": basic.get("site_name", "StoryCanvas"),
        "platform.site_slogan": basic.get("site_slogan", ""),
        "platform.support_email": basic.get("support_email", ""),
        "platform.icp": basic.get("icp", ""),
        "platform.copyright": basic.get("copyright", ""),
        "platform.notice": basic.get("notice", ""),
        "api.deepseek.base_url": api.get("deepseek_base_url", deepseek_service.DEEPSEEK_BASE_URL),
        "api.deepseek.model": api.get("deepseek_model", deepseek_service.DEEPSEEK_MODEL),
        "api.deepseek.api_key": api.get("deepseek_api_key", ""),
        "api.image.base_url": api.get("image_base_url", "https://newapi.aifusion6.cn/v1"),
        "api.image.model": api.get("image_model", ""),
        "api.image.api_key": api.get("image_api_key", ""),
        "api.image.size": _image_setting_text(api, "image_size"),
        "api.image.quality": _image_setting_text(api, "image_quality"),
        "api.image.background": _image_setting_text(api, "image_background"),
        "api.image.moderation": _image_setting_text(api, "image_moderation"),
        "api.image.output_format": _image_setting_text(api, "image_output_format"),
        "api.image.output_compression": _image_output_compression_setting(api),
        "api.image.input_fidelity": _image_setting_text(api, "image_input_fidelity"),
        "api.video.base_url": api.get("video_base_url", "https://newapi.aifusion6.cn/v1"),
        "api.video.model": api.get("video_model", "veo3.1-fast"),
        "api.video.api_key": api.get("video_api_key", ""),
        "api.video.provider": api.get("video_provider", ""),
        "api.enable_user_override": bool(api.get("enable_user_override", True)),
        "api.allow_all_users_api_key_override": bool(
            api.get(
                "allow_all_users_api_key_override",
                _get_platform_setting("api.allow_all_users_api_key_override", db, False),
            )
        ),
        "api.enable_user_url_override": bool(api.get("enable_user_url_override", False)),
        "oss.enabled": bool(api.get("oss_enabled", False)),
        "oss.access_key_id": str(api.get("oss_access_key_id", "") or ""),
        "oss.access_key_secret": str(api.get("oss_access_key_secret", "") or ""),
        "oss.endpoint": str(api.get("oss_endpoint", "") or ""),
        "oss.bucket": str(api.get("oss_bucket", "") or ""),
        "oss.public_url_base": str(api.get("oss_public_url_base", "") or ""),
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
        "payment.default_method": str(payment.get("default_method", "mock_qr") or "mock_qr"),
        "payment.order_expire_minutes": int(payment.get("order_expire_minutes", 30) or 30),
        "payment.auto_activate_free_plan": bool(payment.get("auto_activate_free_plan", True)),
        "payment.instructions": str(payment.get("instructions", "") or ""),
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
        "payment.epay_enabled": bool(payment.get("epay_enabled", False)),
        "payment.epay_gateway": str(payment.get("epay_gateway", "") or ""),
        "payment.epay_pid": str(payment.get("epay_pid", "") or ""),
        "payment.epay_key": str(payment.get("epay_key", "") or ""),
        "payment.epay_type": str(payment.get("epay_type", "alipay") or "alipay"),
        "payment.epay_notify_url": str(payment.get("epay_notify_url", "") or ""),
        "payment.epay_return_url": str(payment.get("epay_return_url", "") or ""),
        "payment.mapay_enabled": bool(payment.get("mapay_enabled", False)),
        "payment.mapay_gateway": str(payment.get("mapay_gateway", "https://pay.21lili.cn") or "https://pay.21lili.cn"),
        "payment.mapay_pid": str(payment.get("mapay_pid", "") or ""),
        "payment.mapay_key": str(payment.get("mapay_key", "") or ""),
        "payment.mapay_type": str(payment.get("mapay_type", "alipay") or "alipay"),
        "payment.mapay_notify_url": str(payment.get("mapay_notify_url", "") or ""),
        "payment.mapay_return_url": str(payment.get("mapay_return_url", "") or ""),
        "platform.announcement.enabled": bool(announcement.get("enabled", False)),
        "platform.announcement.title": announcement.get("title", ""),
        "platform.announcement.content": announcement.get("content", ""),
        "pricing.quota.framework.generate.monthly_limit": pricing.get("quota_framework_generate", 1.0),
        "pricing.quota.chapter.expand.monthly_limit": pricing.get("quota_chapter_expand", 0.5),
        "pricing.quota.scene.generate.monthly_limit": pricing.get("quota_scene_generate", 0.3),
        "pricing.quota.manga.image.generate.monthly_limit": pricing.get("quota_manga_image_generate", 0.2),
        "pricing.quota.ai.text.advanced_calls.monthly_limit": pricing.get("quota_ai_text_advanced", 0.3),
        "pricing.quota.deconstruction.run.monthly_limit": pricing.get("quota_deconstruction_run", 3.0),
        "pricing.quota.video.shot.split.monthly_limit": pricing.get("quota_video_shot_split", 1.0),
        "pricing.quota.video.generate.count.monthly_limit": pricing.get("quota_video_generate", 2.0),
    }
    icon_data = basic.get("icon_data")
    icon_mime = basic.get("icon_mime", "image/png")
    clear_icon = bool(basic.get("clear_icon", False))
    clear_secret_keys = {
        str(item).strip()
        for item in (body.get("clear_secret_keys") or [])
        if str(item).strip() in SENSITIVE_PLATFORM_SETTING_KEYS
    }
    for key, value in mappings.items():
        _set_platform_setting(key, value, db, clear_secret=key in clear_secret_keys)
    if clear_icon:
        _set_platform_setting("platform.icon_data", "", db)
        _set_platform_setting("platform.icon_mime", "", db)
        _set_platform_setting("platform.icon_updated_at", "", db)
    elif isinstance(icon_data, str) and icon_data.strip():
        _set_platform_setting("platform.icon_data", icon_data.strip(), db)
        _set_platform_setting("platform.icon_mime", str(icon_mime or "image/png"), db)
        _set_platform_setting("platform.icon_updated_at", datetime.datetime.utcnow().isoformat(), db)
    db.commit()
    return {"ok": True, "settings": _admin_platform_settings_snapshot(db)}


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


@app.get("/api/admin/system/update/status")
async def admin_system_update_status(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return _sanitize_update_status(await _call_updater("GET", "/status"))


@app.get("/api/admin/system/update/check")
async def admin_system_update_check(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return _sanitize_update_check(await _call_updater("GET", "/check"))


@app.post("/api/admin/system/update")
async def admin_start_system_update(body: dict, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    target_version = str(body.get("target_version") or "").strip() or None
    if target_version and not UPDATER_VERSION_RE.match(target_version):
        raise HTTPException(400, "无效的目标版本格式")
    status = _sanitize_update_status(await _call_updater("POST", "/update", {"target_version": target_version}))
    _write_audit_log(
        admin,
        "system_update_start",
        "system",
        "docker",
        f"Started system update to {target_version or 'configured APP_VERSION'}",
        db,
        {"target_version": target_version},
    )
    db.commit()
    return status


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


@app.get("/api/admin/revenue/summary")
def admin_revenue_summary(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    orders = db.query(BillingOrder).filter(BillingOrder.source == "points_purchase").all()
    monthly_orders = [order for order in orders if order.created_at and order.created_at >= month_start]
    paid_orders = [order for order in orders if order.status == "paid"]
    monthly_paid = [
        order
        for order in paid_orders
        if (order.paid_at or order.created_at) and (order.paid_at or order.created_at) >= month_start
    ]
    monthly_created_paid = [order for order in monthly_orders if order.status == "paid"]
    monthly_paid_users = len({order.user_id for order in monthly_paid})

    return {
        "total_revenue": sum(_money_to_number(order.amount) for order in paid_orders),
        "total_orders": len(orders),
        "paid_orders": len(paid_orders),
        "cancelled_orders": sum(1 for order in orders if order.status == "cancelled"),
        "expired_orders": sum(1 for order in orders if order.status == "expired"),
        "monthly_revenue": sum(_money_to_number(order.amount) for order in monthly_paid),
        "monthly_orders": len(monthly_orders),
        "monthly_paid_orders": len(monthly_paid),
        "conversion_rate": round(len(monthly_created_paid) / len(monthly_orders) * 100, 1) if monthly_orders else 0,
        "monthly_paid_users": monthly_paid_users,
        "monthly_new_users": monthly_paid_users,
    }


@app.get("/api/admin/revenue/monthly")
def admin_revenue_monthly(
    months: int = Query(default=12, ge=1, le=24),
    request: Request = None,
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    now = _utcnow()
    periods: list[str] = []
    year = now.year
    month = now.month
    for offset in range(months - 1, -1, -1):
        absolute_month = year * 12 + month - 1 - offset
        periods.append(f"{absolute_month // 12:04d}-{absolute_month % 12 + 1:02d}")
    first_year, first_month = (int(part) for part in periods[0].split("-"))
    start = datetime.datetime(first_year, first_month, 1)
    rows = (
        db.query(BillingOrder)
        .filter(
            BillingOrder.source == "points_purchase",
            or_(BillingOrder.created_at >= start, BillingOrder.paid_at >= start),
        )
        .all()
    )
    buckets = {
        period: {"period": period, "revenue": 0.0, "orders": 0, "paid": 0, "cancelled": 0, "expired": 0}
        for period in periods
    }
    for order in rows:
        if not order.created_at:
            continue
        created_bucket = buckets.get(order.created_at.strftime("%Y-%m"))
        if created_bucket:
            created_bucket["orders"] += 1
            if order.status == "cancelled":
                created_bucket["cancelled"] += 1
            elif order.status == "expired":
                created_bucket["expired"] += 1
        if order.status == "paid":
            paid_at = order.paid_at or order.created_at
            paid_bucket = buckets.get(paid_at.strftime("%Y-%m")) if paid_at else None
            if paid_bucket:
                paid_bucket["paid"] += 1
                paid_bucket["revenue"] += _money_to_number(order.amount)
    return [buckets[period] for period in periods]


@app.get("/api/admin/orders/search")
def admin_orders_search(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    query = db.query(BillingOrder)
    if status and status.strip():
        query = query.filter(BillingOrder.status == status.strip())
    if start_date:
        try:
            sd = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(BillingOrder.created_at >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            query = query.filter(BillingOrder.created_at < ed)
        except ValueError:
            pass

    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    orders = query.order_by(BillingOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    for order in orders:
        _sync_order_status(order, db)

    return {
        "items": [_serialize_order_with_db(order, db) for order in orders],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@app.post("/api/admin/orders/{order_no}/status")
def admin_update_order_status(order_no: str, body: dict, request: Request, db: Session = Depends(get_db)):
    _ensure_platform_seed(db)
    admin = _require_admin(request, db)
    order = db.query(BillingOrder).filter(BillingOrder.order_no == order_no).first()
    if not order:
        raise HTTPException(404, "订单未找到")
    order = _sync_order_status(order, db)
    next_status = str(body.get("status") or "").strip().lower()
    note = str(body.get("note") or "").strip()
    if next_status == "paid":
        _mark_order_paid(order, db, operator_user_id=admin.id, note=note or f"Marked paid by admin {admin.name}")
    elif next_status == "cancelled":
        _mark_order_cancelled(order, db, operator_user_id=admin.id, note=note or f"Cancelled by admin {admin.name}")
    elif next_status == "expired":
        _mark_order_expired(order, db, note=note or f"Expired by admin {admin.name}")
    else:
        raise HTTPException(400, "状态必须是 paid、cancelled 或 expired")
    _write_audit_log(admin, "admin_update_order_status", "billing_order", order.order_no, f"Updated order to {order.status}", db, {
        "order_no": order.order_no,
        "status": order.status,
        "plan_id": order.plan_id,
    })
    db.commit()
    db.refresh(order)
    return {"ok": True, "order": _serialize_order_with_db(order, db)}



@app.post("/api/stories", response_model=StoryOut)
def create_story(body: StoryCreate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = Story(
        title=body.title,
        description=body.description,
        owner_user_id=user.id,
        source_type="manual",
        import_context_completed=True,
    )
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
    # 删除所有引用 chapters 的非 cascade 子表（必须在删除 chapter 之前）
    chapter_ids = [c.id for c in story.chapters]
    if chapter_ids:
        scene_ids_subq = db.query(ScriptScene.id).filter(
            ScriptScene.chapter_id.in_(chapter_ids)
        ).subquery()
        shot_ids_subq = db.query(VideoShot.id).filter(
            VideoShot.scene_id.in_(scene_ids_subq)
        ).subquery()

        db.query(ShotAssetBinding).filter(
            ShotAssetBinding.shot_id.in_(shot_ids_subq)
        ).delete(synchronize_session=False)
        db.query(RenderedClip).filter(
            RenderedClip.shot_id.in_(shot_ids_subq)
        ).delete(synchronize_session=False)
        db.query(VideoGenerationJob).filter(
            VideoGenerationJob.shot_id.in_(shot_ids_subq)
        ).delete(synchronize_session=False)
        db.query(VideoShot).filter(
            VideoShot.scene_id.in_(scene_ids_subq)
        ).delete(synchronize_session=False)
        db.query(ScriptScene).filter(
            ScriptScene.chapter_id.in_(chapter_ids)
        ).delete(synchronize_session=False)

        db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id.in_(
            db.query(ChapterVideoWorkflow.id).filter(ChapterVideoWorkflow.chapter_id.in_(chapter_ids)).subquery()
        )).delete(synchronize_session=False)
        db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
        db.query(VideoProject).filter(VideoProject.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
        db.query(VideoAsset).filter(VideoAsset.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
    # 删除章节及其 cascade 数据
    for chapter in story.chapters:
        chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter.id}"
        _rmtree_best_effort(chapter_dir, "chapter directory")
    if chapter_ids:
        manga_asset_ids_subq = db.query(MangaAsset.id).filter(
            MangaAsset.chapter_id.in_(chapter_ids)
        ).subquery()
        db.query(MangaAssetBinding).filter(
            or_(
                MangaAssetBinding.chapter_id.in_(chapter_ids),
                MangaAssetBinding.asset_id.in_(manga_asset_ids_subq),
            )
        ).delete(synchronize_session=False)
        db.query(MangaAsset).filter(MangaAsset.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
        db.query(MangaImage).filter(MangaImage.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
        db.query(ChatMessage).filter(ChatMessage.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
    # AgentConversation 及其子表必须在 Chapter 之前删除（chapter_id FK 引用 chapters.id，默认 RESTRICT）
    db.query(AgentPendingChange).filter(AgentPendingChange.story_id == story_id).delete(synchronize_session=False)
    db.query(AgentConversationMessage).filter(AgentConversationMessage.conversation_id.in_(
        db.query(AgentConversation.id).filter(AgentConversation.story_id == story_id)
    )).delete(synchronize_session=False)
    db.query(AgentConversation).filter(AgentConversation.story_id == story_id).delete(synchronize_session=False)
    if chapter_ids:
        db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).delete(synchronize_session=False)
    if story.cover_image:
        cover_path = Path(__file__).resolve().parent / story.cover_image
        try:
            _unlink_file(cover_path, "story cover")
        except HTTPException:
            logger.warning("Story cover remained after story deletion: %s", cover_path)
    story_dir = Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}"
    _rmtree_best_effort(story_dir, "story asset directory")
    # 删除所有引用 stories 的非 cascade 子表（必须在删除 story 之前）
    # StoryCharacterVersion 必须在 VideoAsset 之前删除（ref_asset_id 外键约束，默认 RESTRICT）
    db.query(StoryCharacterVersion).filter(StoryCharacterVersion.story_id == story_id).delete(synchronize_session=False)
    db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.story_id == story_id).delete(synchronize_session=False)
    db.query(VideoProject).filter(VideoProject.story_id == story_id).delete(synchronize_session=False)
    db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).delete(synchronize_session=False)
    db.query(MangaAssetBinding).filter(MangaAssetBinding.story_id == story_id).delete(synchronize_session=False)
    db.query(MangaAsset).filter(MangaAsset.story_id == story_id).delete(synchronize_session=False)
    db.query(VideoAsset).filter(VideoAsset.story_id == story_id).delete(synchronize_session=False)
    db.query(DeconstructionResult).filter(DeconstructionResult.story_id == story_id).delete(synchronize_session=False)
    db.query(FrameworkSnapshot).filter(FrameworkSnapshot.story_id == story_id).delete(synchronize_session=False)
    db.query(NovelSource).filter(NovelSource.story_id == story_id).delete(synchronize_session=False)
    db.query(BackgroundTask).filter(BackgroundTask.story_id == story_id).delete(synchronize_session=False)
    db.delete(story)
    db.commit()
    return {"ok": True}


@app.post("/api/stories/{story_id}/upload-cover")
async def upload_story_cover(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    b64 = body.get("image", "")
    img_bytes = _decode_png_upload(b64)
    output_path = _story_cover_output_path(story_id)
    _write_bytes_or_conflict(output_path, img_bytes, "story cover")
    # OSS 上传（如已配置）
    from services import oss as oss_service
    oss_url = oss_service.upload_file(str(output_path)) if oss_service.is_enabled() else None
    if oss_url:
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass
        story.cover_image = oss_url
    else:
        _replace_story_cover_from_path(story, output_path)
    db.commit()
    db.refresh(story)
    return {"cover_image": story.cover_image}


@app.post("/api/stories/{story_id}/generate-cover")
async def generate_story_cover(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    instruction = str(body.get("instruction") or "").strip()
    prompt = _build_story_cover_prompt(story, instruction)
    logger.info("[cover:%s] 封面 Prompt 长度: %s 字", story_id, len(prompt))
    output_path = _story_cover_output_path(story_id)
    image_api_key = _user_image_api_key(request)

    _check_and_consume_feature_quota(
        request,
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=False,
        provider_kind="image",
    )
    _release_db_transaction(db)
    try:
        generated_cover_path = await asyncio.wait_for(
            generate_cover_image(
                prompt,
                output_path,
                api_key=image_api_key,
            ),
            timeout=300,
        )
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise HTTPException(504, {"error": "封面生成超时，请稍后重试或减少描述内容"}) from exc

    story = _require_story_for_user(story_id, user, db)
    _store_story_cover_result(story, output_path, generated_cover_path)
    _check_and_consume_feature_quota(
        request,
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=True,
        provider_kind="image",
    )
    db.commit()
    db.refresh(story)
    return {"cover_image": story.cover_image, "prompt": prompt}


@app.post("/api/stories/{story_id}/adjust-cover")
async def adjust_story_cover(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if not story.cover_image:
        raise HTTPException(400, "作品没有封面可调整")

    body = await request.json()
    instruction = str(body.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(400, "指令必填")

    source_path_str = ensure_local_media_path(story.cover_image, "manga")
    if not source_path_str:
        raise HTTPException(404, "Existing cover file not found")
    source_path = Path(source_path_str)

    prompt = _build_story_cover_prompt(story, f"在现有封面基础上调整：{instruction}")
    output_path = _story_cover_output_path(story_id)
    image_api_key = _user_image_api_key(request)
    _check_and_consume_feature_quota(
        request,
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=False,
        provider_kind="image",
    )
    _release_db_transaction(db)
    try:
        generated_cover_path = await edit_existing_image(
            prompt,
            source_path,
            output_path,
            api_key=image_api_key,
            size="1024x1792",
        )
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc

    story = _require_story_for_user(story_id, user, db)
    _store_story_cover_result(story, output_path, generated_cover_path)
    _check_and_consume_feature_quota(
        request,
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=True,
        provider_kind="image",
    )
    db.commit()
    db.refresh(story)
    return {"cover_image": story.cover_image, "prompt": prompt}


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
    for asset in db.query(VideoAsset).filter(VideoAsset.chapter_id == chapter.id):
        db.delete(asset)
    manga_asset_ids_subq = db.query(MangaAsset.id).filter(MangaAsset.chapter_id == chapter.id).subquery()
    db.query(MangaAssetBinding).filter(
        or_(
            MangaAssetBinding.chapter_id == chapter.id,
            MangaAssetBinding.asset_id.in_(manga_asset_ids_subq),
        )
    ).delete(synchronize_session=False)
    db.query(MangaAsset).filter(MangaAsset.chapter_id == chapter.id).delete(synchronize_session=False)
    db.delete(chapter)
    db.commit()
    return {"ok": True}


# ─── 漫画资产与章节绑定 ───────────────────────────────────

def _serialize_manga_asset(asset: MangaAsset) -> dict[str, Any]:
    """序列化漫画资产，屏蔽内部 ORM 字段名。"""
    return {
        "id": asset.id,
        "owner_user_id": asset.owner_user_id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "storage_path": asset.storage_path,
        "source_type": asset.source_type,
        "status": asset.status,
        "metadata": asset.metadata_json,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


def _serialize_manga_asset_binding(binding: MangaAssetBinding, asset: MangaAsset | None = None) -> dict[str, Any]:
    """序列化章节资产绑定，并在可用时附带资产信息。"""
    result = {
        "id": binding.id,
        "asset_id": binding.asset_id,
        "story_id": binding.story_id,
        "chapter_id": binding.chapter_id,
        "binding_role": binding.binding_role,
        "label": binding.label,
        "priority": binding.priority,
        "is_required": binding.is_required,
        "created_at": binding.created_at.isoformat() if binding.created_at else None,
    }
    if asset is not None:
        result["asset"] = _serialize_manga_asset(asset)
    return result


def _manga_asset_for_user(asset_id: int, user: User, db: Session) -> MangaAsset:
    """获取当前用户拥有的漫画资产。"""
    asset = db.get(MangaAsset, asset_id)
    if not asset:
        raise HTTPException(404, "漫画资产未找到")
    if asset.owner_user_id != user.id:
        raise HTTPException(403, "漫画资产访问被拒绝")
    return asset


def _validate_manga_asset_chapter(chapter_id: object, story_id: int, user: User, db: Session) -> int | None:
    """校验资产关联章节属于当前用户的指定作品。"""
    if chapter_id is None:
        return None
    if isinstance(chapter_id, bool):
        raise HTTPException(422, "chapter_id 必须是整数或 null")
    try:
        resolved_chapter_id = int(chapter_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "chapter_id 必须是整数或 null") from exc
    chapter = _require_chapter_for_user(resolved_chapter_id, user, db)
    if chapter.story_id != story_id:
        raise HTTPException(400, "章节不属于当前作品")
    return chapter.id


def _required_manga_asset_text(body: dict, key: str, limit: int) -> str:
    """读取并校验创建资产所需的文本字段。"""
    value = str(body.get(key) or "").strip()
    if not value:
        raise HTTPException(422, f"{key} 不能为空")
    if len(value) > limit:
        raise HTTPException(422, f"{key} 长度不能超过 {limit}")
    return value


def _optional_manga_asset_metadata(body: dict) -> dict[str, Any] | None:
    """读取兼容 metadata 与 metadata_json 的资产元数据。"""
    if "metadata" in body:
        metadata = body["metadata"]
    else:
        metadata = body.get("metadata_json")
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(422, "metadata 必须是对象或 null")
    return metadata


@app.get("/api/stories/{story_id}/manga-assets")
def list_manga_assets(story_id: int, request: Request, chapter_id: int | None = None, asset_type: str | None = None, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    query = db.query(MangaAsset).filter(
        MangaAsset.story_id == story_id,
        MangaAsset.owner_user_id == user.id,
    )
    if chapter_id is not None:
        _validate_manga_asset_chapter(chapter_id, story_id, user, db)
        query = query.filter(MangaAsset.chapter_id == chapter_id)
    if asset_type:
        query = query.filter(MangaAsset.asset_type == asset_type.strip())
    assets = query.order_by(MangaAsset.created_at.desc(), MangaAsset.id.desc()).all()
    return {"assets": [_serialize_manga_asset(asset) for asset in assets]}


@app.post("/api/stories/{story_id}/manga-assets", status_code=201)
async def create_manga_asset(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(422, "请求体必须是对象")
    asset = MangaAsset(
        owner_user_id=user.id,
        story_id=story_id,
        chapter_id=_validate_manga_asset_chapter(body.get("chapter_id"), story_id, user, db),
        asset_type=_required_manga_asset_text(body, "asset_type", 32),
        name=_required_manga_asset_text(body, "name", 255),
        storage_path=_required_manga_asset_text(body, "storage_path", 500),
        source_type=str(body.get("source_type") or "upload").strip()[:20] or "upload",
        status=str(body.get("status") or "active").strip()[:20] or "active",
        metadata_json=_optional_manga_asset_metadata(body),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_manga_asset(asset)


@app.patch("/api/manga-assets/{asset_id}")
async def update_manga_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    asset = _manga_asset_for_user(asset_id, user, db)
    _require_story_for_user(asset.story_id, user, db)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(422, "请求体必须是对象")
    for field, limit in (("asset_type", 32), ("name", 255), ("storage_path", 500), ("source_type", 20), ("status", 20)):
        if field in body:
            value = _required_manga_asset_text(body, field, limit)
            setattr(asset, field, value)
    if "chapter_id" in body:
        asset.chapter_id = _validate_manga_asset_chapter(body["chapter_id"], asset.story_id, user, db)
    if "metadata" in body or "metadata_json" in body:
        asset.metadata_json = _optional_manga_asset_metadata(body)
    db.commit()
    db.refresh(asset)
    return _serialize_manga_asset(asset)


@app.delete("/api/manga-assets/{asset_id}")
def delete_manga_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    asset = _manga_asset_for_user(asset_id, user, db)
    db.query(MangaAssetBinding).filter(MangaAssetBinding.asset_id == asset.id).delete(synchronize_session=False)
    db.delete(asset)
    db.commit()
    return {"ok": True}


@app.get("/api/chapters/{chapter_id}/manga-asset-bindings")
def list_chapter_manga_asset_bindings(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    bindings = (
        db.query(MangaAssetBinding)
        .filter(MangaAssetBinding.chapter_id == chapter.id, MangaAssetBinding.story_id == chapter.story_id)
        .order_by(MangaAssetBinding.priority.desc(), MangaAssetBinding.id.asc())
        .all()
    )
    assets = {
        asset.id: asset
        for asset in db.query(MangaAsset).filter(
            MangaAsset.id.in_([binding.asset_id for binding in bindings]),
            MangaAsset.owner_user_id == user.id,
            MangaAsset.story_id == chapter.story_id,
        ).all()
    } if bindings else {}
    return {"bindings": [_serialize_manga_asset_binding(binding, assets.get(binding.asset_id)) for binding in bindings]}


@app.put("/api/chapters/{chapter_id}/manga-asset-bindings")
async def replace_chapter_manga_asset_bindings(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("bindings"), list):
        raise HTTPException(422, "bindings 必须是数组")

    validated_bindings: list[tuple[MangaAsset, dict]] = []
    for item in body["bindings"]:
        if not isinstance(item, dict) or isinstance(item.get("asset_id"), bool):
            raise HTTPException(422, "每个绑定必须包含有效的 asset_id")
        try:
            asset_id = int(item.get("asset_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "每个绑定必须包含有效的 asset_id") from exc
        asset = _manga_asset_for_user(asset_id, user, db)
        if asset.story_id != chapter.story_id:
            raise HTTPException(400, "不能绑定其他作品的漫画资产")
        role = _required_manga_asset_text(item, "binding_role", 20)
        label = item.get("label")
        if label is not None:
            label = str(label).strip()
            if len(label) > 255:
                raise HTTPException(422, "label 长度不能超过 255")
        priority = _coerce_int(item.get("priority"), 0)
        validated_bindings.append((asset, {
            "binding_role": role,
            "label": label or None,
            "priority": priority,
            "is_required": _coerce_bool(item.get("is_required"), False),
        }))

    db.query(MangaAssetBinding).filter(MangaAssetBinding.chapter_id == chapter.id).delete(synchronize_session=False)
    new_bindings: list[MangaAssetBinding] = []
    for asset, values in validated_bindings:
        binding = MangaAssetBinding(
            asset_id=asset.id,
            story_id=chapter.story_id,
            chapter_id=chapter.id,
            **values,
        )
        db.add(binding)
        new_bindings.append(binding)
    db.commit()
    for binding in new_bindings:
        db.refresh(binding)
    return {
        "bindings": [
            _serialize_manga_asset_binding(binding, asset)
            for binding, (asset, _) in zip(new_bindings, validated_bindings)
        ]
    }


# ─── Chat (SSE streaming) ──────────────────────────────────

@app.post("/api/chapters/{chapter_id}/chat")
async def chat(chapter_id: int, body: ChatMessageIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if chapter.content_source == "import":
        raise HTTPException(409, "此章节是从现有小说文本导入的，无法使用 AI 对话")

    # 配额预检
    user_id = user.id
    quota_result = _check_and_consume_advanced_text_quota(request, user_id, db, deduct=False)

    # Save user message
    chapter.content_source = "chat"
    user_msg = ChatMessage(chapter_id=chapter_id, role="user", content=body.content)
    db.add(user_msg)
    db.commit()

    # 读取当前章节的全部消息 + 之前章节最近 50 条消息，确保上下文连贯
    current_messages = [
        {"role": m.role, "content": m.content}
        for m in chapter.messages
    ]

    previous_chapters = (
        db.query(Chapter)
        .filter(
            Chapter.story_id == chapter.story_id,
            Chapter.chapter_number < chapter.chapter_number,
        )
        .order_by(Chapter.chapter_number)
        .all()
    )
    previous_messages: list[dict] = []
    for ch in previous_chapters:
        for m in ch.messages:
            previous_messages.append({"role": m.role, "content": m.content})

    if len(previous_messages) > 50:
        previous_messages = previous_messages[-50:]

    history = previous_messages + current_messages

    framework_context = _build_framework_context(chapter.story, chapter)
    deepseek_api_key = _user_deepseek_api_key(request)
    template_ch_prompt = get_effective_prompt(chapter.story_id, "chapter", db)
    streaming_billing_ctx = _detach_pending_platform_points(
        request,
        quota_result.get("usage_event_id"),
    )
    _release_db_transaction(db)

    collected: list[str] = []
    billing_state = {"finished": False}
    stream_token_checkpoint = {"count": 0}

    def save_interrupted_assistant() -> None:
        full_content = "".join(collected).strip()
        if not full_content:
            return
        write_db = SessionLocal()
        try:
            assistant_msg = ChatMessage(
                chapter_id=chapter_id,
                role="assistant",
                content=f"{full_content}\n\n[已中止]",
            )
            write_db.add(assistant_msg)
            write_db.commit()
        finally:
            write_db.close()

    async def event_generator():
        def finish_billing(*, success: bool, error_code: str | None = None) -> None:
            if billing_state["finished"]:
                return
            full_content = "".join(collected)
            _finish_streaming_platform_points(
                streaming_billing_ctx,
                success=success,
                input_text=json.dumps(history, ensure_ascii=False),
                output_text=full_content,
                error_code=error_code,
            )
            billing_state["finished"] = True

        try:
            async for token in chat_stream(history, api_key=deepseek_api_key, framework_context=framework_context, system_prompt=template_ch_prompt or None):
                collected.append(token)
                stream_token_checkpoint["count"] += 1
                if stream_token_checkpoint["count"] % 16 == 0:
                    from services.ai.resolver import charge_streaming_tokens
                    from services.token_utils import estimate_tokens

                    billing_db = SessionLocal()
                    try:
                        charge_streaming_tokens(
                            billing_db,
                            streaming_billing_ctx,
                            input_tokens=estimate_tokens(
                                json.dumps(history, ensure_ascii=False)
                                + framework_context
                                + (template_ch_prompt or "")
                            ),
                            output_tokens=estimate_tokens("".join(collected)),
                        )
                    finally:
                        billing_db.close()
                yield {"event": "token", "data": json.dumps({"content": token}, ensure_ascii=False)}
            # Save assistant message
            full_content = "".join(collected)
            finish_billing(success=True)
            write_db = SessionLocal()
            try:
                assistant_msg = ChatMessage(chapter_id=chapter_id, role="assistant", content=full_content)
                write_db.add(assistant_msg)
                write_db.commit()
            finally:
                write_db.close()
            yield {"event": "done", "data": json.dumps({"content": full_content}, ensure_ascii=False)}
        except asyncio.CancelledError:
            finish_billing(success=bool(collected), error_code=None if collected else "stream_cancelled")
            save_interrupted_assistant()
            raise
        except Exception as e:
            public_message = public_error_message(e, "对话生成失败，请稍后重试")
            finish_billing(success=bool(collected), error_code=None if collected else "stream_failed")
            write_db = SessionLocal()
            try:
                persisted_user_msg = write_db.get(ChatMessage, user_msg.id)
                if persisted_user_msg:
                    write_db.delete(persisted_user_msg)
                    write_db.commit()
            finally:
                write_db.close()
            logger.exception("章节对话流执行失败 chapter_id=%s", chapter_id)
            yield {"event": "error", "data": json.dumps({"error": public_message, "code": "chat_stream_failed"}, ensure_ascii=False)}

    def release_unfinished_billing() -> None:
        if billing_state["finished"]:
            return
        try:
            _finish_streaming_platform_points(
                streaming_billing_ctx,
                success=False,
                error_code="stream_not_started_or_unfinished",
            )
            billing_state["finished"] = True
        except Exception:
            logger.exception("章节对话流清理预留积分失败 chapter_id=%s", chapter_id)

    return EventSourceResponse(
        event_generator(),
        background=ResponseBackgroundTask(release_unfinished_billing),
    )


# ─── Generate Novel ─────────────────────────────────────────

@app.post("/api/chapters/{chapter_id}/generate-novel", response_model=ChapterOut)
async def generate_novel_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if chapter.content_source == "import":
        raise HTTPException(409, "此章节是从现有小说文本导入的，无法生成 AI 小说文本")

    history = [{"role": m.role, "content": m.content} for m in chapter.messages]
    if not history:
        raise HTTPException(400, "没有对话历史可生成小说")

    # 配额预检
    user_id = user.id
    _check_and_consume_advanced_text_quota(request, user_id, db, deduct=False)

    chapter_info = {
        "chapter_number": chapter.chapter_number,
        "title": chapter.title or f"第{chapter.chapter_number}章",
        "act": chapter.act or "",
        "key_events": chapter.key_events or [],
    }
    chapter_runtime_context = _build_chapter_runtime_context(
        chapter.story,
        db,
        chapter_info,
        user_instruction="根据当前聊天记录生成完整正文",
    )
    framework_context = _build_framework_context(chapter.story, chapter)
    continuity_context = _build_chapter_continuity_context_text(chapter_runtime_context)
    if continuity_context:
        framework_context = framework_context + "\n" + continuity_context if framework_context else continuity_context
    deepseek_api_key = _user_deepseek_api_key(request)
    template_ch_prompt = get_effective_prompt(chapter.story_id, "chapter", db)
    existing_creation_pack = (
        chapter.quality_score.get("creation_pack")
        if isinstance(chapter.quality_score, dict) and isinstance(chapter.quality_score.get("creation_pack"), dict)
        else None
    )
    _release_db_transaction(db)
    novel_content = await generate_novel(
        history,
        api_key=deepseek_api_key,
        framework_context=framework_context,
        system_prompt=template_ch_prompt or None,
    )
    logger.info(
        "generate_novel 跳过生成后连续性二次改写 chapter_id=%s chapter=%s reason=%s",
        chapter_id,
        chapter_info.get("chapter_number"),
        "continuity_in_generation_context",
    )
    quality_gate = await finalize_generated_chapter_content(
        content=novel_content,
        story_context=chapter_runtime_context,
        chapter_info=chapter_info,
        api_key=deepseek_api_key,
        system_prompt=template_ch_prompt or None,
        source="generate_novel",
        existing_creation_pack=existing_creation_pack,
        allow_pipeline_rerun=False,
    )
    if not quality_gate.get("ok"):
        raise HTTPException(status_code=422, detail=format_quality_gate_detail(quality_gate))
    novel_content = quality_gate["content"]
    chapter = _require_chapter(chapter_id, db)
    _apply_chapter_content(chapter, novel_content, status="completed")
    chapter.quality_score = quality_gate.get("report")
    chapter.content_source = "chat"
    await _refresh_chapter_memory(chapter, request, db)

    # Also save as assistant message
    msg = ChatMessage(chapter_id=chapter_id, role="assistant", content=novel_content)
    db.add(msg)
    db.commit()
    # 配额扣减
    _check_and_consume_advanced_text_quota(request, user_id, db, deduct=True)
    response_payload = ChapterOut.model_validate(chapter)
    _release_db_transaction(db)
    return response_payload


MAX_IMPORTED_NOVEL_CHARS = int(os.getenv("MAX_IMPORTED_NOVEL_CHARS", "50000"))


@app.post("/api/chapters/{chapter_id}/import-novel", response_model=ChapterOut)
async def import_novel_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Replace chapter chat history with a single user-imported novel text.

    The imported text is saved both as a single chat message (so the existing
    `generate-scenes` flow works unchanged) and as `chapter.novel_content`.
    """
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    body = await request.json()
    raw = body.get("content", "")
    if not isinstance(raw, str):
        raise HTTPException(400, "内容必须是字符串")
    text = raw.strip()
    if not text:
        raise HTTPException(400, "内容为空")
    if len(text) > MAX_IMPORTED_NOVEL_CHARS:
        raise HTTPException(413, f"小说过长，最大长度为 {MAX_IMPORTED_NOVEL_CHARS} 个字符")
    if chapter.content_source == "chat" or chapter.messages:
        raise HTTPException(409, "此章节已使用 AI 对话，请创建新章节来导入现有小说文本")
    if chapter.images:
        raise HTTPException(409, "此章节已有漫画图片，请创建新章节来导入现有小说文本")

    _clear_chapter_manga_state(chapter, db)
    db.query(ChatMessage).filter(ChatMessage.chapter_id == chapter_id).delete()
    db.add(ChatMessage(chapter_id=chapter_id, role="user", content=text))
    _apply_chapter_content(chapter, text, status="draft")
    chapter.content_source = "import"
    await _refresh_chapter_memory(chapter, request, db)
    db.commit()
    db.refresh(chapter)
    return chapter


@app.put("/api/chapters/{chapter_id}/content", response_model=ChapterOut)
async def update_chapter_content(chapter_id: int, body: ChapterContentUpdate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "内容为空")
    _apply_chapter_content(chapter, text, status="draft")
    if not chapter.messages:
        db.add(ChatMessage(chapter_id=chapter_id, role="user", content=text))
    db.commit()
    db.refresh(chapter)
    await _refresh_chapter_memory(chapter, request, db)
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


async def _load_characters_async(chapter_id: int, request: Request, db: Session) -> str:
    """加载角色数据，当为空时自动从章节内容提取。"""
    # 先尝试从文件和数据库加载
    result = _load_characters(chapter_id, db)
    if result:
        return result

    # 如果为空，尝试从章节内容提取
    chapter = db.get(Chapter, chapter_id)
    if not chapter or not chapter.novel_content or not chapter.novel_content.strip():
        return ""

    # 从章节内容提取角色信息，并作为独立文本调用预扣与结算。
    user = getattr(request.state, "current_user", None) or _require_user(request, db)
    _check_and_consume_feature_quota(
        request,
        user.id,
        "character.extract",
        1,
        db,
        deduct=False,
        provider_kind="text",
    )
    deepseek_api_key = _user_deepseek_api_key(request)
    try:
        generated = await generate_character_profiles_from_content(
            chapter.novel_content,
            api_key=deepseek_api_key,
        )
    except Exception as exc:
        logger.warning("Failed to generate character profiles from content for chapter %s: %s", chapter_id, exc)
        return ""

    _check_and_consume_feature_quota(
        request,
        user.id,
        "character.extract",
        1,
        db,
        deduct=True,
        provider_kind="text",
    )
    if generated:
        # 保存到章节文件
        p = _characters_path(chapter_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(generated, encoding="utf-8")
        return generated

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
    deepseek_api_key = _user_deepseek_api_key(request)

    if isinstance(story.characters, list) and len(story.characters) > 0:
        story_context = _story_framework_context(story)
        template_char_prompt = get_effective_prompt(story_id, "character", db)
        _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
        _release_db_transaction(db)
        generated = await generate_character_profiles_from_framework(
            story_context,
            api_key=deepseek_api_key,
            system_prompt=template_char_prompt or None,
        )
    else:
        all_chapters = db.query(Chapter).filter(
            Chapter.story_id == story_id,
            Chapter.novel_content.isnot(None),
            Chapter.novel_content != "",
        ).order_by(Chapter.chapter_number).all()
        if not all_chapters:
            raise HTTPException(400, "作品没有框架角色或小说内容可生成")
        combined_content = "\n\n".join(
            f"第 {c.chapter_number} 话：{c.novel_content}" for c in all_chapters
        )
        _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
        _release_db_transaction(db)
        generated = await generate_character_profiles_from_content(
            combined_content,
            api_key=deepseek_api_key,
        )

    story = _require_story_for_user(story_id, user, db)
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
    chapter = db.get(Chapter, chapter_id)
    story_refs: list[dict] = []
    if chapter:
        story_dir = _story_ref_dir(chapter.story_id)
        _migrate_legacy_ref(_legacy_story_ref_image(chapter.story_id), story_dir)
        story_refs = _build_ref_entries(story_dir, "story", chapter.story_id)
        bindings = (
            db.query(MangaAssetBinding, MangaAsset)
            .join(MangaAsset, MangaAsset.id == MangaAssetBinding.asset_id)
            .filter(
                MangaAssetBinding.chapter_id == chapter_id,
                MangaAssetBinding.story_id == chapter.story_id,
                MangaAsset.status == "active",
            )
            .order_by(MangaAssetBinding.priority.desc(), MangaAssetBinding.id.asc())
            .all()
        )
        asset_entries: list[dict] = []
        for binding, asset in bindings:
            resolved_path = ensure_local_media_path(asset.storage_path, "manga")
            if not resolved_path:
                logger.warning("漫画资产无法解析为本地参考图，已跳过 asset_id=%s path=%s", asset.id, asset.storage_path)
                continue
            path = Path(resolved_path)
            if not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            asset_entries.append({
                "filename": path.name,
                "path": path,
                "image_path": asset.storage_path,
                "kind": binding.binding_role,
                "label": binding.label or asset.name,
                "priority": binding.priority,
                "is_required": binding.is_required,
            })
        if bindings:
            return asset_entries
        return [*chapter_refs, *story_refs]
    return chapter_refs


def _effective_ref_image_paths(chapter_id: int, db: Session) -> list[Path]:
    """Return the effective ref image list: chapter-level first, else story-level fallback."""
    return [entry["path"] for entry in _effective_ref_entries(chapter_id, db)]


def _label_matches_scene(label: str, scene_text: str) -> bool:
    return label_matches_visual_context(label, scene_text)


def _normalize_manga_ref_role(value: object) -> str:
    role = str(value or "").strip().lower().replace("_reference", "")
    return "style" if role == "style" else normalize_visual_role(role)


def _select_ref_image_paths_for_scene(scene_prompt: str, ref_entries: list[dict]) -> list[tuple[Path, str, str]]:
    """按分镜选择参考图，返回图片路径、匹配标签和资产类型。"""
    all_style_entries = [entry for entry in ref_entries if _normalize_manga_ref_role(entry.get("kind")) == "style"]
    content_entries = [entry for entry in ref_entries if entry not in all_style_entries]
    valid_style_entries = [
        entry
        for entry in all_style_entries
        if isinstance(entry.get("path"), Path) and entry["path"].exists()
    ]
    style_entries = max(
        valid_style_entries,
        key=lambda entry: int(entry.get("priority") or 0),
        default=None,
    )
    selected = select_visual_references(scene_prompt, content_entries, max_items=7 if style_entries else 8)
    # 角色身份一致性优先于环境和道具；同一类别内继续遵守全章固定和手动优先级。
    role_rank = {"character": 0, "scene": 1, "prop": 2}
    selected.sort(key=lambda reference: (
        role_rank.get(reference.role, 3),
        0 if reference.is_required else 1,
        -reference.priority,
    ))
    result: list[tuple[Path, str, str]] = []
    if style_entries:
        result.append((style_entries["path"], str(style_entries.get("label") or "").strip(), "style"))
    result.extend((reference.path, reference.label, reference.role) for reference in selected)
    return result[:8]


def _character_profiles_for_page(
    character_profiles: str,
    scene_prompt: str,
    ref_labels: list[str],
    ref_roles: list[str],
) -> str:
    """仅当当前页涉及的角色都有参考图时省略文本设定。"""
    character_labels = [
        str(label or "").strip()
        for label, role in zip(ref_labels, ref_roles)
        if role == "character" and str(label or "").strip()
    ]
    if not character_labels:
        return character_profiles

    cards = _parse_character_profile_cards(character_profiles)
    character_names = [
        str(card.get("name") or "").strip()
        for card in cards
        if str(card.get("name") or "").strip()
        and not re.fullmatch(r"角色\s*\d+", str(card.get("name") or "").strip())
    ]
    if not character_names:
        return character_profiles

    involved_names = [name for name in character_names if name in scene_prompt]
    names_to_cover = involved_names or (character_names if len(character_names) == 1 else [])
    if not names_to_cover:
        return character_profiles

    def has_reference(name: str) -> bool:
        canonical_name = _canonical_manga_asset_name(name)
        return any(
            canonical_name in _canonical_manga_asset_name(label)
            or _canonical_manga_asset_name(label) in canonical_name
            for label in character_labels
        )

    return "" if all(has_reference(name) for name in names_to_cover) else character_profiles


def _effective_page_ref_entries(ref_entries: list[dict], style_ref_path: str | None) -> list[dict]:
    """已显式选择风格图时移除资产库中的其他风格，避免两种画风同时参与。"""
    if not style_ref_path:
        return ref_entries
    return [
        entry
        for entry in ref_entries
        if _normalize_manga_ref_role(entry.get("kind")) != "style"
    ]


_AUTO_MANGA_ASSET_TYPE_MAP = {
    "characters": "character_reference",
    "scenes": "scene_reference",
    "props": "prop_reference",
}
_AUTO_MANGA_ASSET_TYPE_LABELS = {
    "character_reference": "角色",
    "scene_reference": "场景",
    "prop_reference": "道具",
}


def _canonical_manga_asset_name(value: object) -> str:
    """构造自动资产精确复用键，不做可能误绑角色的模糊匹配。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def _manga_asset_analysis_fingerprint(
    chapter_text: str,
    character_context: str,
    structured_characters: object,
    selected_types: object = None,
) -> str:
    normalized_types = sorted(
        set(selected_types)
        if isinstance(selected_types, (set, list, tuple))
        else set(_AUTO_MANGA_ASSET_TYPE_MAP.values())
    )
    payload = json.dumps(
        {
            "version": AUTO_MANGA_ASSET_ANALYSIS_VERSION,
            "chapter_text": chapter_text,
            "character_context": character_context,
            "structured_characters": structured_characters if isinstance(structured_characters, list) else [],
            "selected_types": normalized_types,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_auto_manga_asset_suggestions(raw_suggestions: object) -> list[dict[str, object]]:
    if not isinstance(raw_suggestions, list):
        return []
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    allowed_types = set(_AUTO_MANGA_ASSET_TYPE_MAP.values())
    for raw in raw_suggestions[:18]:
        if not isinstance(raw, dict):
            continue
        asset_type = str(raw.get("asset_type") or "").strip()
        name = str(raw.get("name") or "").strip()[:255]
        prompt = str(raw.get("prompt") or "").strip()[:24000]
        identity = (asset_type, _canonical_manga_asset_name(name))
        if asset_type not in allowed_types or not identity[1] or not prompt or identity in seen:
            continue
        seen.add(identity)
        normalized.append({
            "asset_type": asset_type,
            "name": name,
            "description": str(raw.get("description") or "").strip()[:4000],
            "evidence": str(raw.get("evidence") or "").strip()[:2000],
            "prompt": prompt,
            "candidates": raw.get("candidates") if isinstance(raw.get("candidates"), list) else [],
        })
    return normalized


def _normalize_auto_manga_asset_options(enabled: object = True, raw_types: object = None) -> tuple[bool, set[str]]:
    """规范化漫画生成的自动资产配置；旧请求默认提取全部三类资产。"""
    if not isinstance(enabled, bool):
        raise HTTPException(422, "auto_asset_extraction.enabled 必须是布尔值")
    enabled_value = enabled
    if raw_types is None:
        selected_types = set(_AUTO_MANGA_ASSET_TYPE_MAP.values())
    elif isinstance(raw_types, list):
        aliases = {
            "character": "character_reference",
            "characters": "character_reference",
            "character_reference": "character_reference",
            "scene": "scene_reference",
            "scenes": "scene_reference",
            "scene_reference": "scene_reference",
            "prop": "prop_reference",
            "props": "prop_reference",
            "prop_reference": "prop_reference",
        }
        normalized_values = [str(value).strip().lower() for value in raw_types]
        unknown_types = sorted({value for value in normalized_values if value not in aliases})
        if unknown_types:
            raise HTTPException(422, f"不支持的自动资产类型: {', '.join(unknown_types)}")
        selected_types = {aliases[value] for value in normalized_values}
    else:
        raise HTTPException(422, "auto_asset_extraction.types 必须是数组")
    return enabled_value and bool(selected_types), selected_types


def _filter_auto_manga_asset_suggestions(
    suggestions: list[dict[str, object]],
    selected_types: set[str],
) -> list[dict[str, object]]:
    """仅保留本次漫画生成选择的资产类型。"""
    return [item for item in suggestions if item.get("asset_type") in selected_types]


def _is_auto_manga_asset_analysis_cached(payload: object, fingerprint: str) -> bool:
    """判断资产分析是否可复用，并兼容早期没有状态字段的非空缓存。"""
    if not isinstance(payload, dict):
        return False
    cached_hash = str(payload.get("input_hash") or "").strip()
    if cached_hash and cached_hash != fingerprint:
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status == "ready":
        return True
    return not status and bool(_normalize_auto_manga_asset_suggestions(payload.get("suggestions")))


def _flatten_auto_manga_asset_analysis(result: object) -> list[dict[str, object]]:
    if not isinstance(result, dict):
        return []
    suggestions: list[dict[str, object]] = []
    for group, asset_type in _AUTO_MANGA_ASSET_TYPE_MAP.items():
        rows = result.get(group)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                suggestions.append({**row, "asset_type": asset_type, "candidates": []})
    return _normalize_auto_manga_asset_suggestions(suggestions)


async def _load_or_analyze_auto_manga_assets(
    *,
    chapter: Chapter,
    chapter_text: str,
    character_context: str,
    structured_characters: object,
    selected_types: set[str],
    request: Request | None,
    user_id: int,
    db: Session,
    analysis_billing_ctx=None,
    text_api_key: str | None = None,
) -> tuple[list[dict[str, object]], str, bool]:
    """读取同内容指纹的分析缓存；不存在时自动执行一次全量章节资产分析。"""
    fingerprint = _manga_asset_analysis_fingerprint(
        chapter_text,
        character_context,
        structured_characters,
        selected_types,
    )
    cached_payload = chapter.manga_asset_analysis_json if isinstance(chapter.manga_asset_analysis_json, dict) else {}
    cached_suggestions = _normalize_auto_manga_asset_suggestions(cached_payload.get("suggestions"))
    if _is_auto_manga_asset_analysis_cached(cached_payload, fingerprint):
        chapter.manga_asset_analysis_json = {
            **cached_payload,
            "version": AUTO_MANGA_ASSET_ANALYSIS_VERSION,
            "input_hash": fingerprint,
            "status": "ready",
            "suggestions": cached_suggestions,
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }
        db.commit()
        return cached_suggestions, fingerprint, True

    if analysis_billing_ctx is None and request is not None:
        _check_and_consume_feature_quota(
            request,
            user_id,
            "ai.text.advanced_calls.monthly_limit",
            1,
            db,
            deduct=False,
            provider_kind="text",
        )
    text_api_key = text_api_key or (_user_deepseek_api_key(request) if request is not None else None)
    if not text_api_key:
        raise HTTPException(400, "文本 AI 服务未配置，无法自动提取章节资产")

    chapter.manga_asset_analysis_json = {
        "version": AUTO_MANGA_ASSET_ANALYSIS_VERSION,
        "input_hash": fingerprint,
        "status": "analyzing",
        "suggestions": cached_suggestions,
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }
    db.commit()
    try:
        analyzed = await analyze_visual_assets(
            chapter_text=chapter_text,
            character_context=character_context,
            structured_characters=structured_characters,
            api_key=text_api_key,
            max_items=6,
            asset_groups={
                group
                for group, asset_type in _AUTO_MANGA_ASSET_TYPE_MAP.items()
                if asset_type in selected_types
            },
        )
        suggestions = _flatten_auto_manga_asset_analysis(analyzed)
    except Exception as exc:
        chapter.manga_asset_analysis_json = {
            "version": AUTO_MANGA_ASSET_ANALYSIS_VERSION,
            "input_hash": fingerprint,
            "status": "failed",
            "suggestions": cached_suggestions,
            "error": public_error_message(exc, "自动章节资产分析失败，请稍后重试"),
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }
        db.commit()
        logger.exception("自动章节资产分析失败 chapter_id=%s", chapter.id)
        _finish_streaming_platform_points(
            analysis_billing_ctx,
            success=False,
            error_code="asset_analysis_failed",
        )
        raise HTTPException(502, public_error_message(exc, "自动章节资产分析失败，请稍后重试")) from exc

    chapter.manga_asset_analysis_json = {
        "version": AUTO_MANGA_ASSET_ANALYSIS_VERSION,
        "input_hash": fingerprint,
        "status": "ready",
        "suggestions": suggestions,
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }
    if analysis_billing_ctx is not None:
        _finish_streaming_platform_points(analysis_billing_ctx, success=True)
    elif request is not None:
        _check_and_consume_feature_quota(
            request,
            user_id,
            "ai.text.advanced_calls.monthly_limit",
            1,
            db,
            deduct=True,
            provider_kind="text",
        )
    db.commit()
    return suggestions, fingerprint, False


def _ensure_auto_manga_asset_binding(
    db: Session,
    *,
    asset: MangaAsset,
    chapter_id: int,
    story_id: int,
    label: str,
) -> None:
    role = asset.asset_type.replace("_reference", "")
    binding = db.query(MangaAssetBinding).filter(
        MangaAssetBinding.asset_id == asset.id,
        MangaAssetBinding.chapter_id == chapter_id,
        MangaAssetBinding.binding_role == role,
    ).first()
    if binding:
        if not binding.label:
            binding.label = label
        return
    db.add(MangaAssetBinding(
        asset_id=asset.id,
        story_id=story_id,
        chapter_id=chapter_id,
        binding_role=role,
        label=label,
        priority=0,
        is_required=False,
    ))


def _find_reusable_auto_manga_asset(
    db: Session,
    *,
    user_id: int,
    story_id: int,
    asset_type: str,
    name: str,
) -> tuple[MangaAsset | None, str | None]:
    identity = _canonical_manga_asset_name(name)
    assets = db.query(MangaAsset).filter(
        MangaAsset.owner_user_id == user_id,
        MangaAsset.story_id == story_id,
        MangaAsset.asset_type == asset_type,
        MangaAsset.status == "active",
    ).order_by(MangaAsset.id.desc()).all()
    for asset in assets:
        if _canonical_manga_asset_name(asset.name) != identity:
            continue
        resolved = ensure_local_media_path(str(asset.storage_path or ""), "manga")
        if resolved and Path(resolved).exists():
            return asset, resolved
    return None, None


def _prepare_auto_manga_asset_plan(
    db: Session,
    *,
    user_id: int,
    story_id: int,
    chapter_id: int,
    suggestions: list[dict[str, object]],
) -> tuple[list[dict[str, str]], int, str | None]:
    """精确复用已有资产并补章节绑定，返回真正需要调用图片模型的缺失项。"""
    missing: list[dict[str, str]] = []
    reused = 0
    anchor_path: str | None = None
    for suggestion in suggestions:
        asset_type = str(suggestion["asset_type"])
        name = str(suggestion["name"])
        asset, resolved = _find_reusable_auto_manga_asset(
            db,
            user_id=user_id,
            story_id=story_id,
            asset_type=asset_type,
            name=name,
        )
        if asset:
            _ensure_auto_manga_asset_binding(
                db,
                asset=asset,
                chapter_id=chapter_id,
                story_id=story_id,
                label=name,
            )
            reused += 1
            anchor_path = anchor_path or resolved
            continue
        missing.append({
            "asset_type": asset_type,
            "name": name,
            "prompt": str(suggestion["prompt"]),
            "description": str(suggestion.get("description") or ""),
            "evidence": str(suggestion.get("evidence") or ""),
        })
    db.commit()
    return missing, reused, anchor_path


async def _generate_auto_manga_asset(
    *,
    chapter_id: int,
    story_id: int,
    user_id: int,
    item: dict[str, str],
    image_api_key: str | None,
    style_anchor_path: str | None,
    generation_task_id: str | None = None,
) -> dict[str, object]:
    """生成单个缺失资产；调用前后都复查，避免任务重试时重复出图。"""
    check_db = SessionLocal()
    try:
        existing, resolved = _find_reusable_auto_manga_asset(
            check_db,
            user_id=user_id,
            story_id=story_id,
            asset_type=item["asset_type"],
            name=item["name"],
        )
        if existing:
            _ensure_auto_manga_asset_binding(
                check_db,
                asset=existing,
                chapter_id=chapter_id,
                story_id=story_id,
                label=item["name"],
            )
            check_db.commit()
            return {"status": "reused", "asset_id": existing.id, "resolved_path": resolved}
    finally:
        check_db.close()

    relative_dir = Path(f"story_{story_id}") / "assets"
    filename = f"asset_auto_{uuid.uuid4().hex}.png"
    output_dir = manga_dir / relative_dir
    output_path = output_dir / filename
    await run_blocking(output_dir.mkdir, parents=True, exist_ok=True)

    reference_paths = [style_anchor_path] if style_anchor_path else None
    try:
        saved_path = await generate_visual_asset_image(
            prompt=item["prompt"],
            output_path=output_path,
            asset_type=item["asset_type"],
            api_key=image_api_key or None,
            size="1920x1080",
            reference_paths=reference_paths,
            reference_labels=["画面风格参考锚点"] if reference_paths else None,
            reference_roles=["style"] if reference_paths else None,
        )
    except Exception:
        if output_path.exists():
            await run_blocking(output_path.unlink)
        raise

    saved_text = str(saved_path or "").strip()
    storage_path = (
        saved_text
        if saved_text.startswith(("http://", "https://"))
        else f"manga_outputs/{relative_dir.as_posix()}/{filename}"
    )
    write_db = SessionLocal()
    try:
        existing, resolved = _find_reusable_auto_manga_asset(
            write_db,
            user_id=user_id,
            story_id=story_id,
            asset_type=item["asset_type"],
            name=item["name"],
        )
        if existing:
            _ensure_auto_manga_asset_binding(
                write_db,
                asset=existing,
                chapter_id=chapter_id,
                story_id=story_id,
                label=item["name"],
            )
            write_db.commit()
            if output_path.exists():
                await run_blocking(output_path.unlink)
            return {"status": "reused", "asset_id": existing.id, "resolved_path": resolved}

        asset = MangaAsset(
            owner_user_id=user_id,
            story_id=story_id,
            chapter_id=chapter_id,
            asset_type=item["asset_type"],
            name=item["name"],
            storage_path=storage_path,
            source_type="generated",
            status="active",
            metadata_json={
                "prompt": item["prompt"],
                "description": item.get("description") or "",
                "evidence": item.get("evidence") or "",
                "provider": "image2",
                "auto_generated": True,
                "generation_task_id": generation_task_id,
            },
        )
        write_db.add(asset)
        write_db.flush()
        _ensure_auto_manga_asset_binding(
            write_db,
            asset=asset,
            chapter_id=chapter_id,
            story_id=story_id,
            label=item["name"],
        )
        write_db.commit()
        write_db.refresh(asset)
        resolved_path = ensure_local_media_path(storage_path, "manga")
        return {"status": "generated", "asset_id": asset.id, "resolved_path": resolved_path}
    except Exception:
        write_db.rollback()
        if output_path.exists():
            await run_blocking(output_path.unlink)
        raise
    finally:
        write_db.close()


async def _ensure_auto_manga_assets(
    *,
    chapter_id: int,
    story_id: int,
    user_id: int,
    items: list[dict[str, str]],
    image_api_key: str | None,
    style_ref_path: str | None,
    fallback_anchor_path: str | None,
    billing_ctx,
    task_id: str | None,
) -> dict[str, object]:
    """在页面生成前补齐缺失资产，部分成功会保留，账单按实际新增数结算。"""
    generated_count = 0
    completed_count = 0
    generated_asset_ids: list[int] = []
    failures: list[tuple[str, Exception]] = []
    anchor_path = style_ref_path or fallback_anchor_path
    remaining = list(items)
    child_tasks: list[asyncio.Task] = []

    def record_result(result: dict[str, object]) -> None:
        nonlocal completed_count, generated_count
        completed_count += 1
        if result.get("status") == "generated":
            generated_count += 1
            generated_asset_ids.append(int(result["asset_id"]))

    def update_progress(message: str, running_names: list[str] | None = None) -> None:
        task_manager.update_task_metadata(
            task_id,
            stage="asset_generating",
            message=message,
            asset_total=len(items),
            asset_completed=completed_count,
            asset_generated=generated_count,
            asset_failed=len(failures),
            asset_running=running_names or [],
        )

    async def generate_one(index: int, item: dict[str, str], reference_anchor: str | None) -> dict[str, object]:
        if index > 0 and AUTO_MANGA_ASSET_START_INTERVAL_SECONDS > 0:
            await asyncio.sleep(index * AUTO_MANGA_ASSET_START_INTERVAL_SECONDS)
        if task_manager.is_cancellation_requested(task_id):
            raise RuntimeError("用户取消了漫画生成任务")
        return await _generate_auto_manga_asset(
            chapter_id=chapter_id,
            story_id=story_id,
            user_id=user_id,
            item=item,
            image_api_key=image_api_key,
            style_anchor_path=reference_anchor,
            generation_task_id=task_id,
        )

    try:
        update_progress(f"正在生成章节一致性资产 0/{len(items)}")
        # 未选择风格图且没有可复用资产时，先生成一张锚点图，再让其余资产复用该视觉语言。
        if remaining and not anchor_path:
            first = remaining.pop(0)
            try:
                result = await generate_one(0, first, None)
                record_result(result)
                anchor_path = str(result.get("resolved_path") or "") or None
            except Exception as exc:
                failures.append((first["name"], exc))

        semaphore = asyncio.Semaphore(AUTO_MANGA_ASSET_CONCURRENCY)

        async def guarded(index: int, item: dict[str, str]) -> tuple[dict[str, str], dict[str, object] | None, Exception | None]:
            async with semaphore:
                update_progress(
                    f"正在生成章节一致性资产 {completed_count}/{len(items)}",
                    [item["name"]],
                )
                try:
                    result = await generate_one(index, item, anchor_path)
                except Exception as exc:
                    failures.append((item["name"], exc))
                    return item, None, exc
                # 结果可能已经落库，必须在任何后续 await 之前完成本地结算记账。
                record_result(result)
                update_progress(f"正在生成章节一致性资产 {completed_count}/{len(items)}")
                return item, result, None

        if remaining and not failures:
            child_tasks = [
                asyncio.create_task(guarded(index, item))
                for index, item in enumerate(remaining)
            ]
            await asyncio.gather(*child_tasks)
    finally:
        for child_task in child_tasks:
            if not child_task.done():
                child_task.cancel()
        if child_tasks:
            await asyncio.gather(*child_tasks, return_exceptions=True)
        _finish_streaming_platform_points(
            billing_ctx,
            success=True,
            image_count=generated_count,
        )
        task_manager.update_task_metadata(
            task_id,
            asset_billing_usage_event_id=0,
            asset_generated_ids=generated_asset_ids,
            asset_generated=generated_count,
            asset_completed=completed_count,
        )

    if failures:
        names = "、".join(name for name, _ in failures[:3])
        first_error = failures[0][1]
        update_progress(f"章节资产生成失败：{names}")
        raise MangaImageGenerationError(
            code="asset_preflight_failed",
            user_message=f"章节资产生成失败（{names}），已生成的资产会保留，重试时只补缺失项。",
            retryable=bool(getattr(first_error, "retryable", False)),
            provider_message=str(first_error),
        ) from first_error

    task_manager.update_task_metadata(
        task_id,
        stage="asset_ready",
        message=f"章节一致性资产已准备完成，共新增 {generated_count} 个，开始生成漫画。",
        asset_total=len(items),
        asset_completed=completed_count,
        asset_generated=generated_count,
        asset_failed=0,
        asset_running=[],
    )
    return {
        "generated": generated_count,
        "completed": completed_count,
        "asset_ids": generated_asset_ids,
    }


def _save_uploaded_ref(ref_dir: Path, img_bytes: bytes, label: str) -> str:
    if len(_list_ref_files(ref_dir)) >= MAX_REF_IMAGES_PER_LEVEL:
        raise HTTPException(409, f"Maximum {MAX_REF_IMAGES_PER_LEVEL} reference images allowed")
    ref_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ref_{uuid.uuid4().hex[:8]}.png"
    filepath = ref_dir / filename
    _write_bytes_or_conflict(filepath, img_bytes, label)
    # OSS 上传（如已配置，保留本地文件供 _serialize_refs 使用）
    from services.oss import auto_configure_from_db, upload_file
    auto_configure_from_db()
    upload_file(str(filepath))
    return filename


def _slugify_ref_label(label: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", (label or "").strip())
    slug = slug.strip("_")
    return slug[:40] or "character"


def _build_character_ref_prompt(story: Story, card: dict) -> str:
    tags = json.dumps(story.tags, ensure_ascii=False) if story.tags else "漫画角色设定"
    return (
        "请生成一张完整的漫画角色设定参考图（Character Design Sheet），用于后续漫画分镜中固定该角色的外貌形象。\n"
        f"题材标签：{tags}\n"
        f"角色名：{card['name']}\n"
        f"以下为该角色的详细外貌设定：\n{card['raw']}\n\n"
        "设定图必须包含以下内容：\n"
        "1. 三视图——正面全身站立图（居中偏大，作为主图）、侧面全身图（左侧）、"
        "背面全身图（右侧）。三个视角比例一致，姿态自然中性站立，双臂自然下垂。\n"
        "2. 表情集——在画面下方或右下角，用3-4个独立的小头像特写展示关键表情："
        "常态（自然表情）、高兴/微笑、愤怒/严肃、悲伤/惊讶。每个表情须有明显差异。\n"
        "3. 服装和配饰——所有服装款式、材质、色彩必须清晰展示。"
        "所有配饰（首饰、武器、道具、装饰品）必须在角色身上明确可见，不可省略或模糊。\n\n"
        "构图与内容要求：\n"
        "- 背景为纯白或浅灰，无场景、无背景元素\n"
        "- 只绘制这一个角色，画面中绝对不出现其他人物\n"
        "- 不要对话框、不要分镜线、不要叙事性文字或标题\n"
        "- 整体呈现为专业角色设定稿的标准排版，不指定具体画风"
    )


# ─── Story-level multi ref images ───────────────────────────

@app.post("/api/stories/{story_id}/character-ref-images/generate")
async def generate_story_character_ref_images(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    cards = _parse_character_profile_cards(story.character_profiles or "")
    if not cards:
        raise HTTPException(400, "作品没有角色外观卡可转换")

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
    image_api_key = _user_image_api_key(request)
    skipped: list[str] = []
    pending_targets: list[dict] = []
    prompt_map: dict[str, str] = {}

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
        prompt_map[card["name"]] = _build_character_ref_prompt(story, card)

    streaming_billing_ctx = None
    if pending_targets:
        quota_result = _check_and_consume_feature_quota(
            request,
            user.id,
            "manga.image.generate.monthly_limit",
            len(pending_targets),
            db,
            deduct=False,
            provider_kind="image",
        )
        streaming_billing_ctx = _detach_pending_platform_points(
            request,
            quota_result.get("usage_event_id"),
        )
    _release_db_transaction(db)
    # 清空 request.state 中的 db/user，避免后面异步 generator 中
    # _check_and_consume_feature_quota → _custom_image_provider_active
    # 访问到已 detached 的 User 实例触发 DetachedInstanceError
    request.state.db = None
    request.state.current_user = None
    billing_state = {"finished": False}

    async def event_generator():
        nonlocal meta
        generated: list[str] = []

        def finish_billing() -> None:
            if billing_state["finished"]:
                return
            _finish_streaming_platform_points(
                streaming_billing_ctx,
                success=bool(generated),
                image_count=len(generated),
                error_code=None if generated else "no_image_generated",
            )
            billing_state["finished"] = True

        _save_ref_meta(ref_dir, meta)
        current_images = _serialize_refs(ref_dir, "story", story_id)
        yield {"event": "snapshot", "data": json.dumps({
            "images": current_images,
            "max": MAX_REF_IMAGES_PER_LEVEL,
            "generated": [],
            "skipped": skipped,
        }, ensure_ascii=False)}

        for card in pending_targets:
            if await request.is_disconnected():
                break

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
                continue

            filename = f"char_{_slugify_ref_label(card['name'])}_{uuid.uuid4().hex[:8]}.png"
            try:
                generated_path = await generate_visual_asset_image(
                    prompt=prompt_map.get(card["name"]) or _build_character_ref_prompt(story, card),
                    output_path=ref_dir / filename,
                    asset_type="character_reference",
                    api_key=image_api_key,
                )
                if str(generated_path).startswith(("http://", "https://")):
                    cached_path = ensure_local_media_path(str(generated_path), "manga")
                    if not cached_path:
                        raise RuntimeError("角色参考图已生成，但无法恢复本地副本")
                    await run_blocking(shutil.copyfile, cached_path, ref_dir / filename)
            except Exception:
                continue

            meta[filename] = {"label": card["name"], "kind": "character_generated"}
            generated.append(card["name"])
            _save_ref_meta(ref_dir, meta)

            yield {"event": "image", "data": json.dumps({
                "images": _serialize_refs(ref_dir, "story", story_id),
                "max": MAX_REF_IMAGES_PER_LEVEL,
                "generated": [card["name"]],
            }, ensure_ascii=False)}

        finish_billing()

        yield {"event": "done", "data": json.dumps({
            "images": _serialize_refs(ref_dir, "story", story_id),
            "max": MAX_REF_IMAGES_PER_LEVEL,
            "generated": generated,
            "skipped": skipped,
        }, ensure_ascii=False)}

    def release_unfinished_billing() -> None:
        if billing_state["finished"]:
            return
        try:
            _finish_streaming_platform_points(
                streaming_billing_ctx,
                success=False,
                error_code="stream_not_started_or_unfinished",
            )
            billing_state["finished"] = True
        except Exception:
            logger.exception("角色参考图流清理预留积分失败 story_id=%s", story_id)

    return EventSourceResponse(
        event_generator(),
        background=ResponseBackgroundTask(release_unfinished_billing),
    )


@app.post("/api/stories/{story_id}/character-ref-images/upload")
async def upload_character_ref_image(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """上传角色专属参考图"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    body = await request.json()
    image_b64 = body.get("image", "")
    character_name = body.get("character_name", "").strip()
    replace_existing = body.get("replace_existing", False)

    if not image_b64:
        raise HTTPException(400, "缺少图片数据")
    if not character_name:
        raise HTTPException(400, "缺少角色名")

    img_bytes = _decode_png_upload(image_b64)

    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    ref_dir.mkdir(parents=True, exist_ok=True)

    meta = _load_ref_meta(ref_dir)

    existing_filename = None
    for fname, info in meta.items():
        if isinstance(info, dict) and info.get("label") == character_name:
            existing_filename = fname
            break

    if existing_filename:
        if replace_existing:
            old_path = ref_dir / existing_filename
            if old_path.exists():
                _unlink_file(old_path, "character ref image")
            meta.pop(existing_filename, None)
            _save_ref_meta(ref_dir, meta)
        else:
            images = _serialize_refs(ref_dir, "story", story_id)
            return {"images": images, "max": MAX_REF_IMAGES_PER_LEVEL}

    filename = _save_uploaded_ref(ref_dir, img_bytes, character_name)

    meta[filename] = {"label": character_name, "kind": "character_uploaded"}
    _save_ref_meta(ref_dir, meta)

    images = _serialize_refs(ref_dir, "story", story_id)
    return {"images": images, "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/stories/{story_id}/character-ref-images/{filename}")
async def delete_character_ref_image(
    story_id: int,
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    ref_dir = _story_ref_dir(story_id)
    if not ref_dir.exists():
        raise HTTPException(404, "参考图目录不存在")

    meta = _load_ref_meta(ref_dir)

    if filename not in meta:
        raise HTTPException(404, "参考图不存在")

    file_path = ref_dir / filename
    if file_path.exists():
        _unlink_file(file_path, "character ref image")

    meta.pop(filename, None)
    _save_ref_meta(ref_dir, meta)

    images = _serialize_refs(ref_dir, "story", story_id)
    return {"images": images}


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
        raise HTTPException(400, "无效的文件名")
    body = await request.json()
    prompt = str(body.get("prompt") or "").strip()
    mode = str(body.get("mode") or "full").strip().lower()
    path = _story_ref_dir(story_id) / filename
    if not path.exists():
        raise HTTPException(404, "参考图片未找到")
    try:
        _check_and_consume_feature_quota(request, user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False, provider_kind="image")
        mask_bytes = None
        if mode == "partial":
            with Image.open(path) as img:
                mask_bytes = _decode_edit_mask_upload(str(body.get("mask") or ""), img.size)
        image_api_key = _user_image_api_key(request)
        _release_db_transaction(db)
        await edit_existing_image(prompt, path, path, mask_bytes=mask_bytes, api_key=image_api_key)
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    _check_and_consume_feature_quota(request, user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True, provider_kind="image")
    return {"images": _serialize_refs(_story_ref_dir(story_id), "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/stories/{story_id}/ref-images/{filename}")
async def delete_story_ref_image(story_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "无效的文件名")
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
        raise HTTPException(400, "无效的文件名")
    body = await request.json()
    prompt = str(body.get("prompt") or "").strip()
    mode = str(body.get("mode") or "full").strip().lower()
    path = _chapter_ref_dir(chapter_id) / filename
    if not path.exists():
        raise HTTPException(404, "参考图片未找到")
    try:
        _check_and_consume_feature_quota(request, user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False, provider_kind="image")
        mask_bytes = None
        if mode == "partial":
            with Image.open(path) as img:
                mask_bytes = _decode_edit_mask_upload(str(body.get("mask") or ""), img.size)
        image_api_key = _user_image_api_key(request)
        _release_db_transaction(db)
        await edit_existing_image(prompt, path, path, mask_bytes=mask_bytes, api_key=image_api_key)
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    _check_and_consume_feature_quota(request, user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True, provider_kind="image")
    return {"images": _serialize_refs(_chapter_ref_dir(chapter_id), "chapter", chapter_id), "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/chapters/{chapter_id}/ref-images/{filename}")
async def delete_chapter_ref_image(chapter_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "无效的文件名")
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
    if stored_mode == "color":
        return "color"
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
        raise HTTPException(400, "颜色模式必须是 'bw' 或 'color'")
    if mode == "color":
        pass  # 积分双轨无需套餐限制
    _save_color_mode(chapter_id, mode)
    return {"ok": True}


# ─── Manga Aspect Ratio ──────────────────────────────────────

DEFAULT_MANGA_ASPECT_RATIO = "9:16"
MANGA_ASPECT_RATIOS = {"9:16", "3:4", "2:3", "1:1", "3:2", "4:3", "16:9"}


def _chapter_manga_aspect_ratio(chapter: Chapter) -> str:
    ratio = getattr(chapter, "manga_aspect_ratio", None)
    return ratio if ratio in MANGA_ASPECT_RATIOS else DEFAULT_MANGA_ASPECT_RATIO


@app.get("/api/chapters/{chapter_id}/manga-aspect-ratio")
async def get_manga_aspect_ratio(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    return {"aspect_ratio": _chapter_manga_aspect_ratio(chapter)}


@app.put("/api/chapters/{chapter_id}/manga-aspect-ratio")
async def set_manga_aspect_ratio(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    ratio = body.get("aspect_ratio")
    if not isinstance(ratio, str) or ratio not in MANGA_ASPECT_RATIOS:
        raise HTTPException(400, "漫画比例不受支持")
    chapter.manga_aspect_ratio = ratio
    db.commit()
    return {"ok": True, "aspect_ratio": ratio}


# ─── Image Count ───────────────────────────────────────────

DEFAULT_IMAGE_COUNT = 10
MIN_IMAGE_COUNT = 1
MAX_IMAGE_COUNT = 20


def _resolve_style_preset_ref(db: Session, style_preset_name: str | None) -> str | None:
    """根据风格预设名称解析出本地图片路径（下载 OSS URL 到缓存），供漫画作为风格参考图。"""
    if not style_preset_name:
        return None
    try:
        preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == style_preset_name.strip()).first()
        if not preset or not preset.image_url:
            return None
        return ensure_local_media_path(preset.image_url, "manga")
    except Exception as exc:
        logger.error("解析风格预设参考图失败: %s", exc)
        return None


def _load_manga_image_concurrency() -> int:
    try:
        configured = int(os.getenv("MANGA_IMAGE_CONCURRENCY", "4"))
    except (TypeError, ValueError):
        configured = 2
    return max(1, min(2, configured))


MANGA_IMAGE_CONCURRENCY = _load_manga_image_concurrency()


def _load_manga_image_start_interval() -> int:
    try:
        configured = int(os.getenv("MANGA_IMAGE_START_INTERVAL_SECONDS", "5"))
    except (TypeError, ValueError):
        configured = 5
    return max(0, min(60, configured))


MANGA_IMAGE_START_INTERVAL_SECONDS = _load_manga_image_start_interval()


def _load_manga_generation_timeout_per_image() -> int:
    try:
        configured = int(os.getenv("MANGA_IMAGE_TIMEOUT_PER_PAGE", "360"))
    except (TypeError, ValueError):
        configured = 360
    return max(180, min(900, configured))


MANGA_IMAGE_TIMEOUT_PER_PAGE = _load_manga_generation_timeout_per_image()


def _manga_image_concurrency(total: int) -> int:
    return max(1, min(total, MANGA_IMAGE_CONCURRENCY))


def _image_count_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "image_count.txt"


def _load_image_count(chapter_id: int) -> int:
    p = _image_count_path(chapter_id)
    if p.exists():
        try:
            v = int(p.read_text(encoding="utf-8").strip())
            if MIN_IMAGE_COUNT <= v <= MAX_IMAGE_COUNT:
                return v
        except (ValueError, OSError):
            pass
    return DEFAULT_IMAGE_COUNT


def _effective_image_count(chapter_id: int, user_id: int, db: Session) -> int:
    chapter = db.get(Chapter, chapter_id)
    if chapter is not None:
        stored_storyboard = _chapter_storyboard(chapter)
        if stored_storyboard and stored_storyboard[0]:
            return len(stored_storyboard[0])
    stored = _load_image_count(chapter_id)
    # 积分双轨无套餐限制，使用系统最大可用值
    return min(stored, MAX_IMAGE_COUNT)


def _chapter_has_scene_file(chapter_id: int) -> bool:
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        return False
    try:
        return bool(prompts_file.read_text(encoding="utf-8").strip())
    except OSError:
        return True


def _chapter_is_blank(chapter: Chapter) -> bool:
    stored_storyboard = _chapter_storyboard(chapter)
    return (
        not chapter.messages
        and not chapter.images
        and not (chapter.novel_content or "").strip()
        and not (stored_storyboard and stored_storyboard[0])
    )


@app.get("/api/chapters/{chapter_id}/image-count")
async def get_image_count(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    image_count = _effective_image_count(chapter_id, user.id, db)
    if image_count != _load_image_count(chapter_id):
        p = _image_count_path(chapter_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(p, str(image_count))
    return {"image_count": image_count}


@app.put("/api/chapters/{chapter_id}/image-count")
async def set_image_count(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    count = body.get("image_count", DEFAULT_IMAGE_COUNT)
    if not isinstance(count, int) or isinstance(count, bool) or not MIN_IMAGE_COUNT <= count <= MAX_IMAGE_COUNT:
        raise HTTPException(400, f"image_count must be between {MIN_IMAGE_COUNT} and {MAX_IMAGE_COUNT}")
    p = _image_count_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, str(count))
    return {"ok": True, "image_count": count}


# ─── Scene generation & management ───────────────────────

@app.post("/api/chapters/{chapter_id}/generate-scenes")
async def generate_scenes_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Generate scene prompts from chat history. Returns them for user review."""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if not chapter.messages and not chapter.novel_content:
        raise HTTPException(400, "暂无聊天消息")

    image_count = _effective_image_count(chapter_id, user.id, db)
    if chapter.messages:
        chat_history = [{"role": m.role, "content": m.content} for m in chapter.messages]
    else:
        chat_history = [{"role": "user", "content": chapter.novel_content}]
    character_profiles = await _load_characters_async(chapter_id, request, db)
    deepseek_api_key = _user_deepseek_api_key(request)
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=False, provider_kind="text")
    _release_db_transaction(db)
    split_task = asyncio.create_task(
        split_scenes(
            chat_history,
            character_profiles=character_profiles,
            page_count=image_count,
            api_key=deepseek_api_key,
        )
    )
    try:
        while not split_task.done():
            if await request.is_disconnected():
                split_task.cancel()
                raise HTTPException(499, "场景生成已取消")
            await asyncio.sleep(0.25)
        scenes = await split_task
        if await request.is_disconnected():
            raise HTTPException(499, "场景生成已取消")
    except ValueError as exc:
        logger.warning("Failed to parse scene split response for chapter %s: %s", chapter_id, exc)
        raise HTTPException(502, "AI 返回无效的场景 JSON，请重试生成场景")
    except asyncio.CancelledError:
        raise HTTPException(499, "场景生成已取消")
    finally:
        if not split_task.done():
            split_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await split_task
    sanitized_scenes, sanitized_indices = sanitize_scene_list(scenes)
    _write_scenes_file(chapter_id, sanitized_scenes, sanitized_indices, db=db, chapter=chapter)
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=True, provider_kind="text")
    return {"scenes": sanitized_scenes, "sanitized_indices": sanitized_indices}


@app.get("/api/chapters/{chapter_id}/scenes")
async def get_scenes_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """从数据库加载分镜，并兼容回填历史文件数据。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    stored_storyboard = _chapter_storyboard(chapter)
    if stored_storyboard is not None:
        stored_scenes, sanitized_indices = stored_storyboard
        if stored_scenes:
            try:
                _write_scenes_projection(chapter_id, stored_scenes, sanitized_indices)
                atomic_write_text(_image_count_path(chapter_id), str(len(stored_scenes)))
            except OSError:
                logger.exception("重建分镜兼容文件失败 chapter_id=%s", chapter_id)
        return {"scenes": stored_scenes, "sanitized_indices": sanitized_indices}
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        return {"scenes": [], "sanitized_indices": []}
    try:
        raw = prompts_file.read_text(encoding="utf-8")
        parts = _parse_scenes_text(raw)
        meta = _load_scene_meta(chapter_id)
        if parts:
            if not MIN_IMAGE_COUNT <= len(parts) <= MAX_IMAGE_COUNT:
                raise HTTPException(500, f"历史分镜数量必须为 {MIN_IMAGE_COUNT}-{MAX_IMAGE_COUNT} 格，请先修正分镜文件")
            _write_scenes_file(
                chapter_id,
                parts,
                meta.get("sanitized_indices", []),
                db=db,
                chapter=chapter,
            )
        return {"scenes": parts, "sanitized_indices": meta.get("sanitized_indices", [])}
    except (OSError, UnicodeError, ValueError) as exc:
        logger.exception("读取章节分镜失败 chapter_id=%s", chapter_id)
        raise HTTPException(500, "分镜读取失败，请联系管理员检查存储状态") from exc


@app.put("/api/chapters/{chapter_id}/scenes")
async def update_scenes_endpoint(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Save user-edited scene prompts."""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    scenes = body.get("scenes", [])
    if not isinstance(scenes, list) or not all(isinstance(s, str) and s.strip() for s in scenes):
        raise HTTPException(400, "无效的场景格式")
    if not MIN_IMAGE_COUNT <= len(scenes) <= MAX_IMAGE_COUNT:
        raise HTTPException(400, f"每章分镜数量必须为 {MIN_IMAGE_COUNT}-{MAX_IMAGE_COUNT} 格")
    if getattr(chapter, "images", None):
        stored_storyboard = _chapter_storyboard(chapter)
        if stored_storyboard is not None:
            old_scenes = stored_storyboard[0]
        else:
            path = scenes_path(Path(__file__).resolve().parent, chapter_id)
            old_scenes = _parse_scenes_text(path.read_text(encoding="utf-8")) if path.exists() else []
        if len(old_scenes) != len(scenes):
            raise HTTPException(409, "当前章节已有漫画图片，改变分镜格数会导致图片错位")

    _write_scenes_file(chapter_id, scenes, [], db=db, chapter=chapter)
    try:
        atomic_write_text(_image_count_path(chapter_id), str(len(scenes)))
    except OSError:
        logger.exception("写入分镜数量兼容文件失败 chapter_id=%s", chapter_id)
    return {"ok": True, "image_count": len(scenes)}


def _storyboard_import_state(chapter_id: int, db: Session) -> tuple[str, list[str], list[int]]:
    chapter = db.get(Chapter, chapter_id)
    if chapter is not None:
        stored_storyboard = _chapter_storyboard(chapter)
        if stored_storyboard is not None:
            current_scenes, _sanitized_indices = stored_storyboard
            raw = render_scenes_text(current_scenes) if current_scenes else ""
            generated_indices = sorted({
                int(row.image_number)
                for row in db.query(MangaImage.image_number).filter(MangaImage.chapter_id == chapter_id).all()
            })
            return raw, current_scenes, generated_indices
    path = scenes_path(Path(__file__).resolve().parent, chapter_id)
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    current_scenes = _parse_scenes_text(raw)
    generated_indices = sorted({
        int(row.image_number)
        for row in db.query(MangaImage.image_number).filter(MangaImage.chapter_id == chapter_id).all()
    })
    return raw, current_scenes, generated_indices


def _storyboard_import_payload(
    chapter_id: int,
    db: Session,
    parsed: dict,
    *,
    revision: str | None = None,
    stale_image_indices: list[int] | None = None,
) -> dict:
    raw, current_scenes, generated_indices = _storyboard_import_state(chapter_id, db)
    scenes = parsed.get("scenes", [])
    errors = list(parsed.get("errors", []))
    structural_conflict_error = "当前章节已有漫画图片，改变分镜格数会导致图片错位；请先处理已有图片"
    if generated_indices and len(current_scenes) != len(scenes):
        if structural_conflict_error not in errors:
            errors.append(structural_conflict_error)
    computed_stale_indices = [
        index
        for index in generated_indices
        if index <= len(current_scenes)
        and index <= len(scenes)
        and current_scenes[index - 1] != scenes[index - 1]
    ]
    canonical_hash = parsed.get("canonical_hash") or canonical_scenes_hash(scenes)
    return {
        "scenes": scenes,
        "scene_count": len(scenes),
        "count": len(scenes),
        "revision": revision or content_revision(raw),
        "canonical_hash": canonical_hash,
        "hash": canonical_hash,
        "warnings": list(parsed.get("warnings", [])),
        "errors": errors,
        "generated_image_indices": generated_indices,
        "stale_image_indices": sorted(set(stale_image_indices or computed_stale_indices)),
        "can_commit": not errors,
    }


@app.post("/api/chapters/{chapter_id}/manga-storyboard/import/preview-file")
async def preview_manga_storyboard_file(
    chapter_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)
    data = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        text_content = decode_uploaded_file(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    parsed = parse_import_text(text_content, require_markers_for_prose=True)
    return _storyboard_import_payload(chapter_id, db, parsed)


@app.post("/api/chapters/{chapter_id}/manga-storyboard/import/preview")
async def preview_manga_storyboard(
    chapter_id: int,
    body: MangaStoryboardImportPreviewIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if body.source_kind == "chapter_content":
        text_content = chapter.novel_content or ""
    else:
        text_content = body.content or ""
    parsed = parse_import_text(text_content, require_markers_for_prose=True)
    return _storyboard_import_payload(chapter_id, db, parsed)


@app.post("/api/chapters/{chapter_id}/manga-storyboard/import/commit")
async def commit_manga_storyboard_import(
    chapter_id: int,
    body: MangaStoryboardImportCommitIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    normalized_scenes = [scene.strip() for scene in body.scenes if isinstance(scene, str)]
    errors: list[str] = []
    if len(normalized_scenes) != len(body.scenes) or any(not scene for scene in normalized_scenes):
        errors.append("分镜脚本必须是非空字符串数组")
    if not MIN_IMAGE_COUNT <= len(normalized_scenes) <= MAX_IMAGE_COUNT:
        errors.append(f"每章分镜数量必须为 {MIN_IMAGE_COUNT}-{MAX_IMAGE_COUNT} 格")
    submitted_hash = canonical_scenes_hash(normalized_scenes)
    if not re.fullmatch(r"[0-9a-f]{64}", body.expected_revision or ""):
        errors.append("expected_revision 必须是 64 位小写 SHA-256")
    if not secrets.compare_digest(submitted_hash, body.canonical_hash or ""):
        errors.append("canonical_hash 与提交的分镜内容不一致，请重新预览")
    active_task = db.query(BackgroundTask.id).filter(
        BackgroundTask.task_type == "manga_generation",
        BackgroundTask.chapter_id == chapter_id,
        BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
    ).first()
    if active_task or chapter_id in ACTIVE_MANGA_GENERATIONS:
        errors.append("当前章节有正在进行的漫画生成任务，请等待任务结束后再导入")
    if errors:
        parsed = {"scenes": normalized_scenes, "warnings": [], "errors": errors, "canonical_hash": submitted_hash}
        return JSONResponse(_storyboard_import_payload(chapter_id, db, parsed), status_code=409)

    backend_dir = Path(__file__).resolve().parent
    with scenes_file_lock(backend_dir, chapter_id):
        raw, old_scenes, generated_indices = _storyboard_import_state(chapter_id, db)
        current_revision = content_revision(raw)
        active_task = db.query(BackgroundTask.id).filter(
            BackgroundTask.task_type == "manga_generation",
            BackgroundTask.chapter_id == chapter_id,
            BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
        ).first()
        if active_task or chapter_id in ACTIVE_MANGA_GENERATIONS:
            parsed = {
                "scenes": normalized_scenes,
                "warnings": [],
                "errors": ["当前章节有正在进行的漫画生成任务，请等待任务结束后再导入"],
                "canonical_hash": submitted_hash,
            }
            return JSONResponse(_storyboard_import_payload(chapter_id, db, parsed), status_code=409)
        if not secrets.compare_digest(current_revision, body.expected_revision):
            parsed = {
                "scenes": normalized_scenes,
                "warnings": [],
                "errors": ["分镜已被其他操作更新，请重新预览后再提交"],
                "canonical_hash": submitted_hash,
            }
            return JSONResponse(_storyboard_import_payload(chapter_id, db, parsed), status_code=409)
        if generated_indices and len(old_scenes) != len(normalized_scenes):
            parsed = {
                "scenes": normalized_scenes,
                "warnings": [],
                "errors": ["当前章节已有漫画图片，改变分镜格数会导致图片错位；请先处理已有图片"],
                "canonical_hash": submitted_hash,
            }
            return JSONResponse(_storyboard_import_payload(chapter_id, db, parsed), status_code=409)

        sanitized_scenes, sanitized_zero_indices = sanitize_scene_list(normalized_scenes)
        stale_indices = [
            index
            for index in generated_indices
            if index <= len(old_scenes) and old_scenes[index - 1] != sanitized_scenes[index - 1]
        ]
        warnings = []
        if sanitized_zero_indices:
            warnings.append("部分分镜包含敏感表达，提交时已自动替换")
        if stale_indices:
            warnings.append("部分已有图片对应的脚本已变化，建议重新生成这些图片")
        new_text = render_scenes_text(sanitized_scenes)
        changed = new_text != raw
        _persist_chapter_storyboard(
            chapter_id,
            sanitized_scenes,
            sanitized_zero_indices,
            db=db,
            chapter=chapter,
        )
        if changed:
            try:
                write_scenes_text_atomic(backend_dir, chapter_id, new_text)
                atomic_write_text(_image_count_path(chapter_id), str(len(sanitized_scenes)))
                atomic_write_text(
                    _scene_meta_path(chapter_id),
                    json.dumps({"sanitized_indices": sanitized_zero_indices}, ensure_ascii=False),
                )
            except OSError:
                logger.exception("导入分镜后写入兼容文件失败 chapter_id=%s", chapter_id)
        new_revision = content_revision(new_text if changed else raw)

    parsed = {
        "scenes": sanitized_scenes,
        "warnings": warnings,
        "errors": [],
        "canonical_hash": canonical_scenes_hash(sanitized_scenes),
    }
    payload = _storyboard_import_payload(
        chapter_id,
        db,
        parsed,
        revision=new_revision,
        stale_image_indices=stale_indices,
    )
    payload.update({"ok": True, "changed": changed})
    return payload


# ─── SSE for manga image generation ─────────────────────


async def _background_manga_generation(
    chapter_id: int,
    scenes: list,
    image_count: int,
    character_profiles: str,
    ref_entries: list,
    color_mode: str,
    image_api_key: str,
    custom_image_provider: bool,
    user_id: int,
    task_id: str | None = None,
    **kwargs,
) -> dict:
    """后台漫画生成任务，由 TaskManager 调度"""
    manga_image_size = kwargs.get("manga_image_size")
    style_ref_path: str | None = kwargs.get("style_ref_path")
    billing_ctx = kwargs.get("billing_ctx")
    initial_existing_numbers = {
        int(value)
        for value in (kwargs.get("initial_existing_numbers") or [])
    }
    logger.info(f"Background manga generation started: chapter={chapter_id}, images={image_count}")
    completed = 0
    total = len(scenes)
    task_manager.update_task_metadata(
        task_id,
        stage="preparing",
        message=f"正在准备生成 {total} 张漫画...",
        current=0,
        total=total,
    )

    # 提前设置 result_json，使 get_manga_generation_status 能获取 total
    init_db = SessionLocal()
    try:
        bg_task = init_db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
        if bg_task:
            bg_task.result_json = {"completed_images": 0, "total_images": total}
            init_db.commit()
    finally:
        init_db.close()

    for i, scene_prompt in enumerate(scenes, start=1):
        task_manager.update_task_metadata(
            task_id,
            stage="generating",
            message=f"正在生成第 {i}/{total} 张漫画...",
            current=completed,
            total=total,
            current_image=i,
        )
        # 检查用户是否请求取消（优雅取消：当前 await 完成后才生效）
        if task_manager.is_cancellation_requested(task_id):
            logger.info(f"Background manga generation cancelled by user at image {i}/{total}")
            break

        # 检查是否已存在（幂等性：断点续传）
        check_db = SessionLocal()
        try:
            existing = check_db.query(MangaImage).filter(
                MangaImage.chapter_id == chapter_id,
                MangaImage.image_number == i,
            ).first()
            if existing:
                completed += 1
                task_manager.update_task_metadata(
                    task_id,
                    stage="generating",
                    message=f"已存在第 {i}/{total} 张漫画，继续后续图片...",
                    current=completed,
                    total=total,
                    current_image=i,
                )
                continue
        finally:
            check_db.close()
        
        # 生成参考图路径
        ref_imgs = _select_ref_image_paths_for_scene(scene_prompt, ref_entries)
        ref_paths = [str(p) for p, _, _ in ref_imgs]
        ref_labels = [label for _, label, _ in ref_imgs]
        ref_roles = [role for _, _, role in ref_imgs]
        
        try:
            image_result = await generate_manga_image(
                scene_prompt,
                chapter_id,
                i,
                all_scenes=scenes,
                character_profiles=character_profiles,
                ref_image_paths=ref_paths if ref_paths else None,
                ref_labels=ref_labels if any(ref_labels) else None,
                ref_roles=ref_roles if ref_roles else None,
                color_mode=color_mode,
                api_key=image_api_key,
                size=manga_image_size,
                style_ref_path=style_ref_path,
            )
            
            # 如果有 sanitized prompt，更新 scenes 文件
            if image_result.prompt_sanitized and image_result.final_prompt != scene_prompt:
                scenes[i - 1] = image_result.final_prompt
                meta = _load_scene_meta(chapter_id)
                sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [i - 1]))
                _write_scenes_file(chapter_id, scenes, sanitized_indices)
                scene_prompt = image_result.final_prompt
        except (MangaImageGenerationError, Exception) as e:
            task_manager.update_task_metadata(
                task_id,
                stage="retrying" if getattr(e, "retryable", False) else "failed",
                message=public_error_message(e, f"第 {i} 张漫画生成失败，请稍后重试"),
                current=completed,
                total=total,
                current_image=i,
                retryable=bool(getattr(e, "retryable", False)),
            )
            logger.error(f"Background manga image {i} failed: {e}")
            raise  # 让 TaskManager 处理重试/失败
        
        task_manager.update_task_metadata(
            task_id,
            stage="saving",
            message=f"第 {i}/{total} 张漫画已生成，正在保存结果...",
            current=completed,
            total=total,
            current_image=i,
        )

        # 保存到数据库
        write_db = SessionLocal()
        try:
            manga = MangaImage(
                chapter_id=chapter_id,
                image_number=i,
                image_path=image_result.image_path,
                prompt=scene_prompt,
            )
            write_db.add(manga)
            if custom_image_provider:
                write_db.commit()
            else:
                _check_and_consume_quota(user_id, "manga.image.generate.monthly_limit", 1, write_db, deduct=True)
            write_db.refresh(manga)
        finally:
            write_db.close()
        
        completed += 1
        task_manager.update_task_metadata(
            task_id,
            stage="generating",
            message=f"已完成 {completed}/{total} 张漫画...",
            current=completed,
            total=total,
        )
    
    # 如果因用户取消而退出循环，在 DB 标记失败（_on_task_complete 不会覆盖已存在的 failed）
    if task_manager.is_cancellation_requested(task_id):
        task_manager.clear_cancellation_flag(task_id)
        _finish_manga_batch_billing(
            billing_ctx,
            chapter_id=chapter_id,
            initial_existing_numbers=initial_existing_numbers,
            task_id=task_id,
        )
        cancel_db = SessionLocal()
        try:
            bg_task = cancel_db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
            if bg_task and bg_task.status != "failed":
                bg_task.status = "failed"
                bg_task.error_message = f"用户手动取消了任务，已完成 {completed}/{total} 张"
                bg_task.completed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                meta = bg_task.metadata_json if isinstance(bg_task.metadata_json, dict) else {}
                bg_task.metadata_json = {
                    **meta,
                    "stage": "cancelled",
                    "message": bg_task.error_message,
                    "current": completed,
                    "total": total,
                    "next_retry_at": None,
                }
                cancel_db.commit()
        finally:
            cancel_db.close()
        logger.info(f"Background manga generation cancelled: chapter={chapter_id}, completed={completed}/{total}")
        return {"status": "cancelled", "completed_images": completed, "total_images": total, "cancelled": True}
    
    task_manager.update_task_metadata(
        task_id,
        stage="succeeded",
        message=f"漫画生成完成，共 {completed}/{total} 张",
        current=completed,
        total=total,
        next_retry_at=None,
    )
    logger.info(f"Background manga generation completed: chapter={chapter_id}, completed={completed}/{total}")
    return {"completed_images": completed, "total_images": total}


async def _background_manga_generation_concurrent(
    chapter_id: int,
    scenes: list,
    image_count: int,
    character_profiles: str,
    ref_entries: list,
    color_mode: str,
    image_api_key: str,
    task_id: str | None = None,
    **kwargs,
) -> dict:
    """Generate chapter manga pages concurrently with a bounded fan-out."""

    manga_image_size = kwargs.get("manga_image_size")
    style_ref_path: str | None = kwargs.get("style_ref_path")
    billing_ctx = kwargs.get("billing_ctx")
    asset_billing_ctx = kwargs.get("asset_billing_ctx")
    auto_asset_items = list(kwargs.get("auto_asset_items") or [])
    auto_asset_preflight = bool(kwargs.get("auto_asset_preflight"))
    auto_asset_chapter_text = str(kwargs.get("auto_asset_chapter_text") or "")
    auto_asset_character_context = str(kwargs.get("auto_asset_character_context") or "")
    auto_asset_structured_characters = kwargs.get("auto_asset_structured_characters")
    auto_asset_types = set(kwargs.get("auto_asset_types") or _AUTO_MANGA_ASSET_TYPE_MAP.values())
    auto_asset_text_api_key = kwargs.get("auto_asset_text_api_key")
    auto_asset_analysis_billing_ctx = kwargs.get("auto_asset_analysis_billing_ctx")
    auto_asset_credential_mode = str(kwargs.get("auto_asset_credential_mode") or "user_key")
    auto_asset_image_model_id = kwargs.get("auto_asset_image_model_id")
    auto_asset_story_id = kwargs.get("auto_asset_story_id")
    auto_asset_user_id = kwargs.get("auto_asset_user_id")
    auto_asset_fallback_anchor = kwargs.get("auto_asset_fallback_anchor")
    initial_existing_numbers = {
        int(value)
        for value in (kwargs.get("initial_existing_numbers") or [])
    }

    total = len(scenes)
    concurrency = _manga_image_concurrency(total)
    completed = 0
    running_images: set[int] = set()
    progress_lock = asyncio.Lock()
    scenes_lock = asyncio.Lock()
    page_semaphore = asyncio.Semaphore(concurrency)
    stop_scheduling = asyncio.Event()

    logger.info(
        "Concurrent manga generation started: chapter=%s, images=%s, concurrency=%s",
        chapter_id,
        total,
        concurrency,
    )

    def _write_result_progress(done: int) -> None:
        db = SessionLocal()
        try:
            bg_task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
            if bg_task:
                bg_task.result_json = {"completed_images": done, "total_images": total}
                db.commit()
        finally:
            db.close()

    def _update_progress(
        *,
        stage: str,
        message: str,
        current_image: int | None = None,
        **extra: Any,
    ) -> None:
        task_manager.update_task_metadata(
            task_id,
            stage=stage,
            message=message,
            current=completed,
            total=total,
            current_image=current_image,
            running_images=sorted(running_images),
            concurrency=concurrency,
            next_retry_at=None,
            **extra,
        )

    task_manager.update_task_metadata(
        task_id,
        stage="preparing",
        message=f"正在准备并发生成 {total} 张漫画，最多同时 {concurrency} 张...",
        current=0,
        total=total,
        concurrency=concurrency,
    )
    _write_result_progress(0)

    if auto_asset_preflight:
        asset_billing_started = False
        try:
            selected_asset_label = "、".join(
                _AUTO_MANGA_ASSET_TYPE_LABELS[asset_type]
                for asset_type in _AUTO_MANGA_ASSET_TYPE_LABELS
                if asset_type in auto_asset_types
            )
            preflight_db = SessionLocal()
            try:
                preflight_chapter = preflight_db.get(Chapter, chapter_id)
                if not preflight_chapter:
                    raise RuntimeError("章节不存在，无法准备一致性资产")
                task_manager.update_task_metadata(
                    task_id,
                    stage="asset_analyzing",
                    message=f"正在准备当前章节的{selected_asset_label}资产...",
                )
                suggestions, analysis_hash, analysis_cached = await _load_or_analyze_auto_manga_assets(
                    chapter=preflight_chapter,
                    chapter_text=auto_asset_chapter_text,
                    character_context=auto_asset_character_context,
                    structured_characters=auto_asset_structured_characters,
                    selected_types=auto_asset_types,
                    request=None,
                    user_id=int(auto_asset_user_id),
                    db=preflight_db,
                    analysis_billing_ctx=auto_asset_analysis_billing_ctx,
                    text_api_key=auto_asset_text_api_key,
                )
                suggestions = _filter_auto_manga_asset_suggestions(suggestions, auto_asset_types)
                task_manager.update_task_metadata(
                    task_id,
                    stage="asset_planning",
                    message="资产分析完成，正在复用已有资产并规划缺失项...",
                    asset_analysis_hash=analysis_hash,
                    asset_analysis_cached=analysis_cached,
                    analysis_billing_usage_event_id=0,
                )
                auto_asset_items, reused_asset_count, auto_asset_fallback_anchor = _prepare_auto_manga_asset_plan(
                    preflight_db,
                    user_id=int(auto_asset_user_id),
                    story_id=int(auto_asset_story_id),
                    chapter_id=chapter_id,
                    suggestions=suggestions,
                )
                task_manager.update_task_metadata(
                    task_id,
                    asset_total=len(auto_asset_items),
                    asset_reused=reused_asset_count,
                    asset_completed=0,
                    asset_generated=0,
                    asset_failed=0,
                )
                if auto_asset_items:
                    asset_billing_ctx = _reserve_background_image_points(
                        user_id=int(auto_asset_user_id),
                        story_id=int(auto_asset_story_id),
                        chapter_id=chapter_id,
                        image_count=len(auto_asset_items),
                        credential_mode=auto_asset_credential_mode,
                        model_id=int(auto_asset_image_model_id) if auto_asset_image_model_id else None,
                    )
                    task_manager.update_task_metadata(
                        task_id,
                        asset_billing_usage_event_id=getattr(asset_billing_ctx, "usage_event_id", 0),
                    )
            finally:
                preflight_db.close()

            if auto_asset_items:
                asset_billing_started = True
                await _ensure_auto_manga_assets(
                    chapter_id=chapter_id,
                    story_id=int(auto_asset_story_id),
                    user_id=int(auto_asset_user_id),
                    items=auto_asset_items,
                    image_api_key=image_api_key,
                    style_ref_path=style_ref_path,
                    fallback_anchor_path=auto_asset_fallback_anchor,
                    billing_ctx=asset_billing_ctx,
                    task_id=task_id,
                )
            ref_db = SessionLocal()
            try:
                ref_entries = _effective_page_ref_entries(
                    _effective_ref_entries(chapter_id, ref_db),
                    style_ref_path,
                )
            finally:
                ref_db.close()
            task_manager.update_task_metadata(
                task_id,
                stage="preparing",
                message=f"章节资产已就绪，正在准备生成 {total} 张漫画。",
                selected_asset_count=len(ref_entries),
            )
        except Exception:
            if asset_billing_ctx is not None and not asset_billing_started:
                _finish_streaming_platform_points(
                    asset_billing_ctx,
                    success=False,
                    error_code="asset_preflight_failed",
                )
                task_manager.update_task_metadata(task_id, asset_billing_usage_event_id=0)
            _finish_manga_batch_billing(
                billing_ctx,
                chapter_id=chapter_id,
                initial_existing_numbers=initial_existing_numbers,
                task_id=task_id,
            )
            raise

    async def _generate_one(image_number: int, scene_prompt: str) -> dict[str, Any]:
        nonlocal completed

        async with page_semaphore:
            if task_manager.is_cancellation_requested(task_id) or stop_scheduling.is_set():
                return {"status": "cancelled", "image_number": image_number}

            async with progress_lock:
                running_images.add(image_number)
                _update_progress(
                    stage="generating",
                    message=(
                        f"正在并发生成漫画 {completed}/{total}，"
                        f"第 {image_number} 张已开始（最多同时 {concurrency} 张）..."
                    ),
                    current_image=image_number,
                )

            final_prompt = scene_prompt
            try:
                check_db = SessionLocal()
                try:
                    existing = check_db.query(MangaImage).filter(
                        MangaImage.chapter_id == chapter_id,
                        MangaImage.image_number == image_number,
                    ).first()
                finally:
                    check_db.close()

                if existing:
                    async with progress_lock:
                        running_images.discard(image_number)
                        completed += 1
                        _write_result_progress(completed)
                        _update_progress(
                            stage="generating",
                            message=(
                                f"第 {image_number}/{total} 张漫画已存在，"
                                f"已完成 {completed}/{total} 张。"
                            ),
                            current_image=image_number,
                        )
                    return {"status": "skipped", "image_number": image_number}

                ref_imgs = _select_ref_image_paths_for_scene(scene_prompt, ref_entries)
                ref_paths = [str(p) for p, _, _ in ref_imgs]
                ref_labels = [label for _, label, _ in ref_imgs]
                ref_roles = [role for _, _, role in ref_imgs]
                page_character_profiles = _character_profiles_for_page(
                    character_profiles,
                    scene_prompt,
                    ref_labels,
                    ref_roles,
                )
                logger.info(
                    "漫画页参考资产 chapter=%s page=%s refs=%s",
                    chapter_id,
                    image_number,
                    [f"{role}:{label}" for label, role in zip(ref_labels, ref_roles)],
                )

                image_result = await generate_manga_image(
                    scene_prompt,
                    chapter_id,
                    image_number,
                    all_scenes=list(scenes),
                    character_profiles=page_character_profiles,
                    ref_image_paths=ref_paths if ref_paths else None,
                    ref_labels=ref_labels if any(ref_labels) else None,
                    ref_roles=ref_roles if ref_roles else None,
                    color_mode=color_mode,
                    api_key=image_api_key,
                    size=manga_image_size,
                    style_ref_path=style_ref_path,
                )

                if image_result.prompt_sanitized and image_result.final_prompt != scene_prompt:
                    async with scenes_lock:
                        scenes[image_number - 1] = image_result.final_prompt
                        meta = _load_scene_meta(chapter_id)
                        sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [image_number - 1]))
                        _write_scenes_file(chapter_id, scenes, sanitized_indices)
                        final_prompt = image_result.final_prompt

                async with progress_lock:
                    _update_progress(
                        stage="saving",
                        message=f"第 {image_number}/{total} 张漫画已生成，正在保存结果...",
                        current_image=image_number,
                    )

                write_db = SessionLocal()
                try:
                    existing = write_db.query(MangaImage).filter(
                        MangaImage.chapter_id == chapter_id,
                        MangaImage.image_number == image_number,
                    ).first()
                    if not existing:
                        manga = MangaImage(
                            chapter_id=chapter_id,
                            image_number=image_number,
                            image_path=image_result.image_path,
                            prompt=final_prompt,
                        )
                        write_db.add(manga)
                        write_db.commit()
                        write_db.refresh(manga)
                finally:
                    write_db.close()

                async with progress_lock:
                    running_images.discard(image_number)
                    completed += 1
                    _write_result_progress(completed)
                    _update_progress(
                        stage="generating" if completed < total else "saving",
                        message=f"已完成 {completed}/{total} 张漫画。",
                        current_image=image_number,
                    )
                return {"status": "completed", "image_number": image_number}

            except Exception as exc:
                stop_scheduling.set()
                async with progress_lock:
                    running_images.discard(image_number)
                    _update_progress(
                        stage="retrying" if getattr(exc, "retryable", False) else "failed",
                        message=f"第 {image_number}/{total} 张漫画生成失败：{exc}",
                        current_image=image_number,
                        failed_image=image_number,
                        retryable=bool(getattr(exc, "retryable", False)),
                    )
                logger.error("Background manga image %s failed: %s", image_number, exc)
                return {"status": "failed", "image_number": image_number, "exception": exc}

    async def _staggered_generate(image_number: int, scene_prompt: str) -> dict[str, Any]:
        if image_number > 1 and MANGA_IMAGE_START_INTERVAL_SECONDS > 0:
            await asyncio.sleep((image_number - 1) * MANGA_IMAGE_START_INTERVAL_SECONDS)
        return await _generate_one(image_number, scene_prompt)

    tasks = [
        asyncio.create_task(_staggered_generate(i, scene_prompt))
        for i, scene_prompt in enumerate(scenes, start=1)
    ]
    results: list[dict[str, Any]] = []
    try:
        for finished in asyncio.as_completed(tasks):
            results.append(await finished)
    finally:
        # 外层任务超时或硬取消时，必须停止所有页面子任务，避免状态已失败但图片仍继续写入。
        pending_tasks = [task for task in tasks if not task.done()]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    if task_manager.is_cancellation_requested(task_id):
        task_manager.clear_cancellation_flag(task_id)
        settled_images = _finish_manga_batch_billing(
            billing_ctx,
            chapter_id=chapter_id,
            initial_existing_numbers=initial_existing_numbers,
            task_id=task_id,
        )
        task_manager.update_task_metadata(
            task_id,
            stage="cancelled",
            message=f"用户手动取消了任务，已完成 {completed}/{total} 张",
            current=completed,
            total=total,
            running_images=[],
            next_retry_at=None,
        )
        logger.info(
            "Concurrent manga generation cancelled: chapter=%s, completed=%s/%s",
            chapter_id,
            completed,
            total,
        )
        return {
            "status": "cancelled",
            "message": f"用户手动取消了任务，已结算 {settled_images} 张",
            "completed_images": completed,
            "total_images": total,
        }

    failures = [result for result in results if result.get("status") == "failed"]
    if failures:
        first_failure = failures[0]
        failed_image = first_failure["image_number"]
        exc = first_failure["exception"]
        async with progress_lock:
            running_images.clear()
            _update_progress(
                stage="retrying" if getattr(exc, "retryable", False) else "failed",
                message=f"第 {failed_image}/{total} 张漫画生成失败，已完成 {completed}/{total} 张：{exc}",
                current_image=failed_image,
                failed_image=failed_image,
                retryable=bool(getattr(exc, "retryable", False)),
            )
        _finish_manga_batch_billing(
            billing_ctx,
            chapter_id=chapter_id,
            initial_existing_numbers=initial_existing_numbers,
            task_id=task_id,
        )
        raise exc

    if completed < total:
        _finish_manga_batch_billing(
            billing_ctx,
            chapter_id=chapter_id,
            initial_existing_numbers=initial_existing_numbers,
            task_id=task_id,
        )
        raise MangaImageGenerationError(
            code="incomplete_generation",
            user_message=f"漫画生成未完整完成，已完成 {completed}/{total} 张，请稍后重试。",
            retryable=True,
        )

    task_manager.update_task_metadata(
        task_id,
        stage="succeeded",
        message=f"漫画生成完成，共 {completed}/{total} 张。",
        current=completed,
        total=total,
        running_images=[],
        concurrency=concurrency,
        next_retry_at=None,
    )
    logger.info(
        "Concurrent manga generation completed: chapter=%s, completed=%s/%s",
        chapter_id,
        completed,
        total,
    )
    _finish_manga_batch_billing(
        billing_ctx,
        chapter_id=chapter_id,
        initial_existing_numbers=initial_existing_numbers,
        task_id=task_id,
    )
    return {"completed_images": completed, "total_images": total}


def _finish_manga_batch_billing(
    billing_ctx,
    *,
    chapter_id: int,
    initial_existing_numbers: set[int],
    task_id: str | None,
) -> int:
    """按本批新增漫画数量结算，并阻止任务失败回调重复退款。"""
    if billing_ctx is None:
        return 0
    billing_db = SessionLocal()
    try:
        generated_numbers = {
            int(row[0])
            for row in billing_db.query(MangaImage.image_number).filter(
                MangaImage.chapter_id == chapter_id,
            ).all()
        }
    finally:
        billing_db.close()
    generated_count = len(generated_numbers - initial_existing_numbers)
    _finish_streaming_platform_points(
        billing_ctx,
        success=True,
        image_count=generated_count,
    )
    if task_id:
        task_manager.update_task_metadata(
            task_id,
            billing_usage_event_id=0,
            billing_settled_images=generated_count,
        )
    return generated_count


@app.delete("/api/chapters/{chapter_id}/manga-images")
async def reset_manga_images(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    active_task = db.query(BackgroundTask.id).filter(
        BackgroundTask.task_type == "manga_generation",
        BackgroundTask.chapter_id == chapter_id,
        BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
    ).first()
    if chapter_id in ACTIVE_MANGA_GENERATIONS or active_task:
        raise HTTPException(409, "此章节的漫画生成已在运行中")
    _clear_chapter_images_only(chapter, db)
    db.commit()
    return {"ok": True}


@app.post("/api/chapters/{chapter_id}/upload-style-reference")
async def upload_manga_style_reference(chapter_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传漫画章节的自定义风格参考图"""
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "请上传图片文件")

    from services.blocking import run_blocking

    upload_dir = Path(__file__).resolve().parent / "manga_outputs" / "style_references"
    upload_dir.mkdir(parents=True, exist_ok=True)

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(file.filename or "ref.png").suffix or ".png"
    filename = f"style_ref_ch{chapter_id}_{timestamp}{ext}"
    file_path = upload_dir / filename

    content = await file.read()
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(400, "无法解析该风格参考图，请上传有效的图片文件") from exc
    await run_blocking(file_path.write_bytes, content)

    relative_path = f"style_references/{filename}"

    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = await run_blocking(oss_service.upload_file, str(file_path))
    if oss_url:
        logger.info("漫画风格参考图已上传到 OSS: %s", oss_url)
        relative_path = oss_url
    else:
        logger.info("漫画风格参考图使用本地路径: %s", relative_path)

    return {"success": True, "style_reference_image_url": relative_path}


@app.post("/api/chapters/{chapter_id}/generate-manga-stream")
async def generate_manga_stream(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # 可选：读取请求体中的尺寸参数和风格预设
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "请求体必须是有效的 JSON 对象") from exc
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(422, "请求体必须是 JSON 对象")
    manga_size: str | None = body.get("size")
    style_preset_name: str | None = body.get("style_preset_name")
    style_ref_url: str | None = body.get("style_ref_url")
    extraction_config = body.get("auto_asset_extraction")
    if extraction_config is None:
        auto_asset_enabled, auto_asset_types = _normalize_auto_manga_asset_options()
    elif isinstance(extraction_config, dict):
        auto_asset_enabled, auto_asset_types = _normalize_auto_manga_asset_options(
            extraction_config.get("enabled", True),
            extraction_config.get("types"),
        )
    else:
        raise HTTPException(422, "auto_asset_extraction 必须是对象")

    # Load scenes from file (must exist - user should generate/confirm scenes first)
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        raise HTTPException(400, "未找到场景提示，请先生成场景")
    image_count = _effective_image_count(chapter_id, user.id, db)

    raw = prompts_file.read_text(encoding="utf-8")
    scenes = _parse_scenes_text(raw)
    if len(scenes) != image_count:
        if len(scenes) > image_count:
            raise HTTPException(403, f"Current plan allows at most {image_count} images per chapter. Please reduce page count or upgrade your plan.")
        raise HTTPException(400, f"Expected {image_count} scenes, found {len(scenes)}")
    if chapter_id in ACTIVE_MANGA_GENERATIONS:
        raise HTTPException(409, "此章节的漫画生成已在运行中")
    # 数据库级别检查：防止服务器重启或 SSE 断开后仍允许重复提交
    existing_task = db.query(BackgroundTask).filter(
        BackgroundTask.task_type == "manga_generation",
        BackgroundTask.chapter_id == chapter_id,
        BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
    ).first()
    if existing_task:
        raise HTTPException(409, "此章节的漫画生成已在运行中")
    character_profiles = await _load_characters_async(chapter_id, request, db)
    color_mode = _effective_color_mode(chapter_id, user.id, db)
    image_api_key = _user_image_api_key(request)
    credential_mode = _request_credential_mode(request, db)
    dual_image_runtime = getattr(request.state, "dual_track_image", None)
    image_model_id = dual_image_runtime.get("model_id") if isinstance(dual_image_runtime, dict) else None
    # 风格预设只允许使用参考图片，名称和文字模板不参与画风控制。
    style_ref_path = None
    if style_ref_url:
        style_ref_path = ensure_local_media_path(style_ref_url, "manga")
        if not style_ref_path:
            raise HTTPException(422, "自定义风格参考图无法读取，请重新上传")
    elif style_preset_name:
        style_ref_path = _resolve_style_preset_ref(db, style_preset_name)
        if not style_ref_path:
            raise HTTPException(422, "该风格预设尚未配置有效参考图，不能用于漫画生成")
    logger.info(
        "漫画风格参考图已解析 chapter_id=%s source=%s path=%s",
        chapter_id,
        "custom" if style_ref_url else ("preset" if style_preset_name else "none"),
        style_ref_path or "",
    )

    story = chapter.story or db.get(Story, chapter.story_id)
    chapter_asset_text = str(chapter.novel_content or "").strip() or "\n".join(scenes)
    structured_characters = getattr(story, "characters", None) if story else None
    asset_analysis_hash = _manga_asset_analysis_fingerprint(
        chapter_asset_text,
        character_profiles,
        structured_characters,
        auto_asset_types,
    )
    cached_analysis = chapter.manga_asset_analysis_json if isinstance(chapter.manga_asset_analysis_json, dict) else {}
    should_prepare_assets = auto_asset_enabled and bool(auto_asset_types)
    analysis_cached = not should_prepare_assets or _is_auto_manga_asset_analysis_cached(
        cached_analysis,
        asset_analysis_hash,
    )
    text_api_key = None if analysis_cached else _user_deepseek_api_key(request)
    ref_entries = _effective_page_ref_entries(_effective_ref_entries(chapter_id, db), style_ref_path)
    initial_existing_numbers = {
        int(row[0])
        for row in db.query(MangaImage.image_number).filter(MangaImage.chapter_id == chapter_id).all()
    }
    try:
        quota_result = _check_and_consume_feature_quota(
            request,
            user.id,
            "manga.image.generate.monthly_limit",
            len(scenes),
            db,
            deduct=False,
            provider_kind="image",
        )
    except Exception:
        raise
    manga_billing_ctx = _detach_pending_platform_points(
        request,
        quota_result.get("usage_event_id"),
    )
    analysis_quota_result: dict[str, object] = {}
    analysis_billing_ctx = None
    if not analysis_cached:
        try:
            analysis_quota_result = _check_and_consume_feature_quota(
                request,
                user.id,
                "ai.text.advanced_calls.monthly_limit",
                1,
                db,
                deduct=False,
                provider_kind="text",
            )
            analysis_billing_ctx = _detach_pending_platform_points(
                request,
                analysis_quota_result.get("usage_event_id"),
            )
        except Exception:
            _finish_streaming_platform_points(
                manga_billing_ctx,
                success=False,
                error_code="analysis_quota_reservation_failed",
            )
            raise
    # 在释放事务前提取 user_id，避免异步 generator 中 user 对象 session 已关闭
    user_id = user.id
    _release_db_transaction(db)

    # 资产分析与缺失资产生成都在后台任务内完成，SSE 可以立即建立连接。
    _manga_gen_timeout = max(
        900,
        min(14400, (len(scenes) + 18) * MANGA_IMAGE_TIMEOUT_PER_PAGE),
    )
    _manga_concurrency = _manga_image_concurrency(len(scenes))
    _manga_start_interval = MANGA_IMAGE_START_INTERVAL_SECONDS
    selected_asset_label = "、".join(
        _AUTO_MANGA_ASSET_TYPE_LABELS[asset_type]
        for asset_type in _AUTO_MANGA_ASSET_TYPE_LABELS
        if asset_type in auto_asset_types
    )

    # 提交后台任务到 TaskManager
    task_id = f"manga_gen_{chapter_id}_{uuid.uuid4().hex[:12]}"
    try:
        # 与分镜导入共享章节锁；在登记生成状态前复核版本，关闭读取后的竞态窗口。
        backend_dir = Path(__file__).resolve().parent
        with scenes_file_lock(backend_dir, chapter_id):
            latest_raw = prompts_file.read_text(encoding="utf-8") if prompts_file.exists() else ""
            if not secrets.compare_digest(content_revision(latest_raw), content_revision(raw)):
                raise HTTPException(409, "分镜已在生成准备期间更新，请重新发起漫画生成")
            if chapter_id in ACTIVE_MANGA_GENERATIONS:
                raise HTTPException(409, "此章节的漫画生成已在运行中")
            latest_task = db.query(BackgroundTask.id).filter(
                BackgroundTask.task_type == "manga_generation",
                BackgroundTask.chapter_id == chapter_id,
                BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
            ).first()
            if latest_task:
                raise HTTPException(409, "此章节的漫画生成已在运行中")
            ACTIVE_MANGA_GENERATIONS.add(chapter_id)
            await task_manager.submit_task(
            task_id=task_id,
            task_type="manga_generation",
            coro_func=_background_manga_generation_concurrent,
            chapter_id=chapter_id,
            scenes=scenes,
            image_count=image_count,
            character_profiles=character_profiles,
            ref_entries=ref_entries,
            color_mode=color_mode,
            image_api_key=image_api_key,
            manga_image_size=manga_size,
            style_ref_path=style_ref_path,
            billing_ctx=manga_billing_ctx,
            asset_billing_ctx=None,
            auto_asset_preflight=should_prepare_assets,
            auto_asset_items=[],
            auto_asset_enabled=auto_asset_enabled,
            auto_asset_types=sorted(auto_asset_types),
            auto_asset_chapter_text=chapter_asset_text,
            auto_asset_character_context=character_profiles,
            auto_asset_structured_characters=structured_characters,
            auto_asset_text_api_key=text_api_key,
            auto_asset_analysis_billing_ctx=analysis_billing_ctx,
            auto_asset_credential_mode=credential_mode,
            auto_asset_image_model_id=image_model_id,
            auto_asset_story_id=chapter.story_id,
            auto_asset_user_id=user_id,
            auto_asset_fallback_anchor=None,
            initial_existing_numbers=sorted(initial_existing_numbers),
            timeout=_manga_gen_timeout,
            max_retries=0,
            quota_user_id=user_id,
            quota_feature_key="manga.image.generate.monthly_limit",
            quota_amount=len(scenes),
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "stage": "queued",
                "message": f"漫画生成任务已排队，共 {len(scenes)} 张，最多同时 {_manga_concurrency} 张...",
                "current": 0,
                "total": len(scenes),
                "concurrency": _manga_concurrency,
                "start_interval_seconds": _manga_start_interval,
                "running_stage": "preparing",
                "running_message": (
                    f"正在准备当前章节的{selected_asset_label}资产..."
                    if should_prepare_assets
                    else f"正在准备错峰漫画生成，最多同时 {_manga_concurrency} 张..."
                ),
                "initial_existing_numbers": sorted(initial_existing_numbers),
                "asset_analysis_hash": asset_analysis_hash,
                "asset_analysis_cached": analysis_cached,
                "auto_asset_extraction_enabled": auto_asset_enabled,
                "auto_asset_extraction_types": sorted(auto_asset_types),
                "analysis_billing_usage_event_id": analysis_quota_result.get("usage_event_id"),
                "asset_total": 0,
                "asset_reused": 0,
                "asset_completed": 0,
                "asset_generated": 0,
                "asset_failed": 0,
                "asset_billing_usage_event_id": 0,
            },
            )
    except Exception as exc:
        ACTIVE_MANGA_GENERATIONS.discard(chapter_id)
        _finish_streaming_platform_points(
            manga_billing_ctx,
            success=False,
            error_code="task_submission_failed",
        )
        _finish_streaming_platform_points(
            analysis_billing_ctx,
            success=False,
            error_code="task_submission_failed",
        )
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, "此章节的漫画生成已在运行中") from exc
        raise

    # 已发送过的图片编号集合，防止重复推送
    _yielded_image_numbers: set[int] = set()

    async def event_generator():
        nonlocal _yielded_image_numbers
        try:
            yield {"event": "scenes", "data": json.dumps({"scenes": scenes}, ensure_ascii=False)}

            poll_count = 0
            max_polls = _manga_gen_timeout // 2  # 与 TaskManager 超时同步，每 2 秒轮询一次。

            while poll_count < max_polls:
                poll_count += 1
                task_status = task_manager.get_task_status(task_id)

                def progress_payload(
                    current: int,
                    prompt: str,
                    *,
                    status_info: dict | None = None,
                ) -> dict:
                    info = status_info or {}
                    message = info.get("message") or prompt
                    return {
                        "current": current,
                        "total": image_count,
                        "prompt": message,
                        "stage": info.get("stage"),
                        "message": message,
                        "retry_count": info.get("retry_count", 0),
                        "max_retries": info.get("max_retries", 0),
                        "next_retry_at": info.get("next_retry_at"),
                        "running_images": info.get("running_images") or [],
                        "current_image": info.get("current_image"),
                        "failed_image": info.get("failed_image"),
                        "concurrency": info.get("concurrency"),
                        "asset_total": info.get("asset_total", 0),
                        "asset_completed": info.get("asset_completed", 0),
                        "asset_generated": info.get("asset_generated", 0),
                        "asset_failed": info.get("asset_failed", 0),
                        "asset_running": info.get("asset_running") or [],
                    }

                if task_status is None:
                    yield {"event": "progress", "data": json.dumps(progress_payload(0, "正在排队..."), ensure_ascii=False)}
                    await asyncio.sleep(2)
                    continue

                status = task_status["status"]

                if status == "succeeded":
                    # 查询数据库中所有已生成的图片并返回
                    result_db = SessionLocal()
                    try:
                        chapter_refresh = result_db.query(Chapter).filter(Chapter.id == chapter_id).first()
                        all_images = sorted(chapter_refresh.images, key=lambda img: img.image_number) if chapter_refresh else []
                        for img in all_images:
                            yield {
                                "event": "image",
                                "data": json.dumps({
                                    "id": img.id,
                                    "image_number": img.image_number,
                                    "image_path": img.image_path,
                                    "prompt": img.prompt or "",
                                }, ensure_ascii=False),
                            }
                    finally:
                        result_db.close()
                    yield {"event": "done", "data": json.dumps({"message": "漫画生成完成！"}, ensure_ascii=False)}
                    return

                elif status == "failed":
                    error_meta = task_status.get("metadata_json") if isinstance(task_status.get("metadata_json"), dict) else {}
                    error_msg = task_status.get("message") or task_status.get("error_message") or "漫画生成失败，请重试"
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "error": error_msg,
                            "code": error_meta.get("error_code") or "manga_generation_failed",
                            "retryable": bool(error_meta.get("retryable")),
                            "suggestion": error_meta.get("suggestion"),
                            "stage": error_meta.get("stage"),
                            "asset_generated": error_meta.get("asset_generated", 0),
                            "asset_failed": error_meta.get("asset_failed", 0),
                        }, ensure_ascii=False),
                    }
                    return

                elif status == "running":
                    # 从数据库中查询已完成的数量和图片
                    check_db2 = SessionLocal()
                    try:
                        existing_imgs = check_db2.query(MangaImage).filter(
                            MangaImage.chapter_id == chapter_id,
                        ).order_by(MangaImage.image_number).all()
                    finally:
                        check_db2.close()

                    completed_count = len(existing_imgs)
                    yield {"event": "progress", "data": json.dumps(progress_payload(
                        completed_count,
                        f"正在生成第 {completed_count + 1}/{image_count} 张漫画",
                        status_info=task_status,
                    ), ensure_ascii=False)}

                    # 仅发送增量图片（防止重复推送）
                    for img_obj in existing_imgs:
                        if img_obj.image_number not in _yielded_image_numbers:
                            _yielded_image_numbers.add(img_obj.image_number)
                            yield {
                                "event": "image",
                                "data": json.dumps({
                                    "id": img_obj.id,
                                    "image_number": img_obj.image_number,
                                    "image_path": img_obj.image_path,
                                    "prompt": img_obj.prompt or "",
                                }, ensure_ascii=False),
                            }

                elif status == "pending":
                    yield {"event": "progress", "data": json.dumps(progress_payload(0, "正在排队...", status_info=task_status), ensure_ascii=False)}

                elif status == "retrying":
                    yield {"event": "progress", "data": json.dumps(progress_payload(
                        int((task_status.get("metadata_json") or {}).get("current") or 0),
                        "上游较慢，正在自动重试...",
                        status_info=task_status,
                    ), ensure_ascii=False)}

                await asyncio.sleep(2)

            # Timeout
            yield {"event": "error", "data": json.dumps({"error": "漫画生成超时"}, ensure_ascii=False)}

        except asyncio.CancelledError:
            # SSE 连接断开，但后台任务继续运行
            logger.info(f"Manga generation SSE cancelled for chapter {chapter_id}, background task continues")
        except Exception as e:
            logger.exception(f"Manga generation SSE error: {e}")
            yield {
                "event": "error",
                "data": json.dumps(
                    {"error": public_error_message(e, "漫画生成连接异常，请稍后重试")},
                    ensure_ascii=False,
                ),
            }
        finally:
            ACTIVE_MANGA_GENERATIONS.discard(chapter_id)

    return EventSourceResponse(event_generator(), ping=10)


@app.post("/api/chapters/{chapter_id}/cancel-manga-generation")
async def cancel_manga_generation(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """取消正在进行的漫画生成任务"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # 查找该章节正在运行的 BackgroundTask
    task = db.query(BackgroundTask).filter(
        BackgroundTask.task_type == "manga_generation",
        BackgroundTask.chapter_id == chapter_id,
        BackgroundTask.status.in_(["pending", "running", "retrying"]),
    ).first()

    if not task:
        raise HTTPException(404, "此章节没有活跃的漫画生成任务")

    # 1) 设置取消标志，不抛 CancelledError——让当前正在 await 的图片正常完成
    task_manager.request_cancellation(task.task_id)

    # 2) 标记取消请求，后台协程会在当前图片结束后按实际产出结算。
    task.status = "cancel_requested"
    task.error_message = "用户已请求取消任务"
    meta = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    task.metadata_json = {
        **meta,
        "stage": "cancel_requested",
        "message": "用户已请求取消任务，正在等待当前图片完成",
        "next_retry_at": None,
    }
    db.commit()

    logger.info(f"Manga generation cancelled by user: chapter={chapter_id}, task={task.task_id}")
    return {"ok": True, "message": "漫画生成取消请求已提交"}


@app.get("/api/chapters/{chapter_id}/manga-generation-status")
async def get_manga_generation_status(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """查询漫画生成后台任务状态"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # 查询最新的漫画生成 BackgroundTask
    task = db.query(BackgroundTask).filter(
        BackgroundTask.task_type == "manga_generation",
        BackgroundTask.chapter_id == chapter_id,
    ).order_by(BackgroundTask.created_at.desc()).first()

    if not task:
        return {
            "status": "none",
            "message": "没有进行中的漫画生成任务",
        }

    # 查询当前已生成的图片数量
    image_count = db.query(MangaImage).filter(
        MangaImage.chapter_id == chapter_id,
    ).count()

    meta = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    friendly_message = meta.get("message") or task.error_message
    if not friendly_message:
        friendly_message = "漫画生成完成" if task.status == "succeeded" else "漫画生成中"

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": image_count,
        "total": task.result_json.get("total_images", image_count) if task.result_json else image_count,
        "error_message": task.error_message,
        "stage": meta.get("stage"),
        "message": friendly_message,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "next_retry_at": meta.get("next_retry_at"),
        "running_images": meta.get("running_images") or [],
        "current_image": meta.get("current_image"),
        "failed_image": meta.get("failed_image"),
        "error_code": meta.get("error_code"),
        "retryable": bool(meta.get("retryable")),
        "suggestion": meta.get("suggestion"),
        "asset_total": meta.get("asset_total", 0),
        "asset_completed": meta.get("asset_completed", 0),
        "asset_generated": meta.get("asset_generated", 0),
        "asset_failed": meta.get("asset_failed", 0),
        "concurrency": meta.get("concurrency"),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


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
        raise HTTPException(400, "提示词必填")
    mode = str(body.get("mode") or "regenerate").strip().lower()
    manga_size: str | None = body.get("size")
    style_preset_name: str | None = body.get("style_preset_name")
    style_ref_url: str | None = body.get("style_ref_url")
    # 风格预设只允许使用参考图片，名称和文字模板不参与画风控制。
    style_ref_path = None
    if style_ref_url:
        style_ref_path = ensure_local_media_path(style_ref_url, "manga")
        if not style_ref_path:
            raise HTTPException(422, "自定义风格参考图无法读取，请重新上传")
    elif style_preset_name:
        style_ref_path = _resolve_style_preset_ref(db, style_preset_name)
        if not style_ref_path:
            raise HTTPException(422, "该风格预设尚未配置有效参考图，不能用于漫画生成")
    logger.info(
        "单格漫画风格参考图已解析 chapter_id=%s image_number=%s source=%s path=%s",
        chapter_id,
        image_number,
        "custom" if style_ref_url else ("preset" if style_preset_name else "none"),
        style_ref_path or "",
    )

    # 以数据库分镜为准，仅对尚未迁移的章节回退到兼容文件。
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    all_scenes = None
    stored_storyboard = _chapter_storyboard(chapter)
    sanitized_indices: list[int] = []
    if stored_storyboard is not None:
        parts, sanitized_indices = stored_storyboard
    elif prompts_file.exists():
        raw = prompts_file.read_text(encoding="utf-8")
        parts = _parse_scenes_text(raw)
        sanitized_indices = _load_scene_meta(chapter_id).get("sanitized_indices", [])
    else:
        parts = []
    if len(parts) == image_count:
        parts[image_number - 1] = prompt
        all_scenes = parts
        _write_scenes_file(
            chapter_id,
            parts,
            sanitized_indices,
            db=db,
            chapter=chapter,
        )

    # Keep old DB/file intact until the new image is generated successfully.
    old_img = db.query(MangaImage).filter(
        MangaImage.chapter_id == chapter_id,
        MangaImage.image_number == image_number,
    ).first()
    old_path = None
    if old_img and old_img.image_path:
        # 支持 OSS URL 和本地路径：ensure_local_media_path 会自动下载 OSS 文件到 .media_cache/
        local = ensure_local_media_path(old_img.image_path, "manga")
        if local:
            old_path = Path(local)
    character_profiles = await _load_characters_async(chapter_id, request, db)
    color_mode = _effective_color_mode(chapter_id, user.id, db)
    image_api_key = _user_image_api_key(request)
    custom_image_provider = _custom_image_provider_active(request)

    # Generate new image
    ref_entries = _effective_ref_entries(chapter_id, db)
    reference_context = "\n".join(
        value for value in ((old_img.prompt if old_img else ""), prompt) if value
    )
    ref_imgs = _select_ref_image_paths_for_scene(reference_context, ref_entries)
    ref_paths = [str(p) for p, _, _ in ref_imgs]
    ref_labels = [label for _, label, _ in ref_imgs]
    ref_roles = [role for _, _, role in ref_imgs]
    try:
        _check_and_consume_feature_quota(request, user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False, provider_kind="image")
        _release_db_transaction(db)
        if mode in {"full", "partial"}:
            if not old_path or not old_path.exists():
                raise HTTPException(404, "源图片未找到")
            mask_bytes = None
            if mode == "partial":
                with Image.open(old_path) as img:
                    mask_bytes = _decode_edit_mask_upload(str(body.get("mask") or ""), img.size)
            chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            filename = f"panel_{image_number:02d}_{uuid.uuid4().hex[:8]}.png"
            output_path = chapter_dir / filename
            saved_path = await edit_existing_image(
                prompt,
                old_path,
                output_path,
                mask_bytes=mask_bytes,
                api_key=image_api_key,
                style_reference_path=Path(style_ref_path) if style_ref_path else None,
                reference_image_paths=[Path(path) for path in ref_paths],
                reference_labels=ref_labels,
                reference_roles=ref_roles,
            )
            # edit_existing_image 可能返回 OSS URL
            saved_path_str = str(saved_path) if saved_path else str(output_path)
            image_result = image_service.ImageGenerationResult(
                image_path=saved_path_str if saved_path_str.startswith("http") else f"manga_outputs/chapter_{chapter_id}/{filename}",
                final_prompt=prompt,
                prompt_sanitized=False,
            )
        else:
            image_result = await generate_manga_image(
                prompt,
                chapter_id,
                image_number,
                all_scenes=all_scenes,
                character_profiles=character_profiles,
                ref_image_paths=ref_paths if ref_paths else None,
                ref_labels=ref_labels if any(ref_labels) else None,
                ref_roles=ref_roles if ref_roles else None,
                color_mode=color_mode,
                api_key=image_api_key,
                size=manga_size,
                style_ref_path=style_ref_path,
            )
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    if image_result.prompt_sanitized and image_result.final_prompt != prompt and all_scenes and len(all_scenes) == image_count:
        all_scenes[image_number - 1] = image_result.final_prompt
        meta = _load_scene_meta(chapter_id)
        sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [image_number - 1]))
        _write_scenes_file(chapter_id, all_scenes, sanitized_indices)
        prompt = image_result.final_prompt

    old_image_path = old_img.image_path if old_img else None
    old_image_id = old_img.id if old_img else None
    chapter = _require_chapter_for_user(chapter_id, user, db)
    if old_image_id:
        manga = (
            db.query(MangaImage)
            .filter(MangaImage.id == old_image_id, MangaImage.chapter_id == chapter_id)
            .first()
        )
        if not manga:
            raise HTTPException(404, "源图片未找到")
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
    if custom_image_provider:
        db.commit()
    else:
        _check_and_consume_feature_quota(request, user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True, provider_kind="image")
    db.commit()
    db.refresh(manga)

    if old_image_path and old_path and old_path.exists() and old_path != Path(__file__).resolve().parent / image_result.image_path:
        # 不删除 .media_cache 中的缓存文件（OSS URL 下载的临时文件）
        if '.media_cache' in str(old_path):
            logger.debug("跳过删除 .media_cache 缓存: %s", old_path)
        else:
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


# ─── Onboarding / Story Bible ───────────────────────────────


@app.post("/api/stories/{story_id}/onboarding/message", response_model=OnboardingMessageOut)
async def onboarding_send_message(story_id: int, request: Request, db: Session = Depends(get_db)):
    """发送引导对话消息，获取 AI 回复"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    messages_raw = body.get("messages", [])
    previous_understanding = body.get("understanding", {})
    if not isinstance(messages_raw, list) or len(messages_raw) == 0:
        raise HTTPException(400, "消息必填")
    if not isinstance(previous_understanding, dict):
        previous_understanding = {}

    safe_messages = [
        {"role": msg["role"], "content": str(msg["content"])}
        for msg in messages_raw
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and str(msg.get("content", "")).strip()
    ]
    if not safe_messages:
        raise HTTPException(400, "没有有效消息")

    # 配额预检
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)

    creative_brief = None
    deepseek_api_key = _user_deepseek_api_key(request)
    onboard_prompt = get_system_prompt("prompt.onboarding", db) or None
    _release_db_transaction(db)
    try:
        result = await generate_onboarding_response(
            safe_messages,
            understanding=previous_understanding,
            api_key=deepseek_api_key,
            system_prompt=onboard_prompt,
        )
        # 构建 creative_brief：AI 输出优先，否则从 understanding 自动构建
        if bool(result.get("has_brief")) and result.get("creative_brief"):
            creative_brief = result["creative_brief"]
        elif bool(result.get("has_brief")):
            ai_understanding = result.get("understanding") or {}
            creative_brief = _build_creative_brief_from_understanding(ai_understanding)
    except Exception as e:
        raise HTTPException(502, f"AI 服务调用失败: {e}")

    # 配额扣减
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)

    # 构建兼容的 collected_info
    understanding = result.get("understanding", {})
    collected_info = {
        "story_concept": understanding.get("concept", ""),
        "genre_audience": understanding.get("setting", ""),
        "core_hook": understanding.get("tone", ""),
        "target_length": understanding.get("goals", ""),
        "must_keep": understanding.get("synthesis", ""),
    }

    return OnboardingMessageOut(
        reply=result.get("reply", ""),
        understanding=understanding,
        understanding_depth=int(result.get("understanding_depth", 0)),
        phase=str(result.get("phase", "exploring")),
        has_brief=bool(result.get("has_brief", False)),
        creative_brief=creative_brief,
        collected_info=collected_info,
        step=1,
        total_steps=5,
        is_complete=bool(result.get("has_brief", False)),
    )


@app.post("/api/stories/{story_id}/onboarding/confirm")
async def onboarding_confirm(story_id: int, request: Request, db: Session = Depends(get_db)):
    """确认引导结果，生成 Story Bible 并保存"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    understanding = body.get("understanding", {})
    creative_brief_input = body.get("creative_brief", {})
    messages_raw = body.get("messages", [])

    # 从 understanding 构建 raw_input
    raw_input = {
        "raw_idea": understanding.get("concept", ""),
        "raw_length_goal": understanding.get("goals", ""),
        "raw_must_keep": understanding.get("synthesis", ""),
        "raw_hidden_setting": "",
        "raw_notes": "",
    }

    # Captura todas as mensagens como texto bruto
    all_raw = "\n".join(
        f"{'作者' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in messages_raw
        if isinstance(m, dict)
    )
    raw_input["raw_notes"] = all_raw

    deepseek_api_key = _user_deepseek_api_key(request)

    # 配额预检
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    _check_and_consume_feature_quota(
        request,
        user.id,
        "framework.generate.monthly_limit",
        2,
        db,
        deduct=False,
        provider_kind="text",
    )

    _release_db_transaction(db)
    try:
        # 优先使用前端传来的 creative_brief，否则从 understanding 自动构建
        if creative_brief_input and isinstance(creative_brief_input, dict) and any(creative_brief_input.values()):
            creative_brief = creative_brief_input
        else:
            creative_brief = _build_creative_brief_from_understanding(understanding)
        story_bible = await build_story_bible(
            creative_brief,
            raw_input,
            api_key=deepseek_api_key,
        )
    except Exception as e:
        raise HTTPException(502, f"Story Bible 生成失败: {e}")

    story = _require_story_for_user(story_id, user, db)
    story.story_bible = story_bible
    story.description = story_bible.get("creative_brief", {}).get("one_line_premise", story.description or "")
    story.onboarding_completed = True
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)

    # --- 新增：自动生成故事框架 ---
    framework_result = None
    try:
        description = _build_framework_seed_description(story)
        if description.strip():
            story_context = _build_framework_ai_context(story, mode="initial_generate")
            template_fw_prompt = get_effective_prompt(story_id, "framework", db)
            # 释放 DB 事务，避免 AI 调用期间长连接占用
            _release_db_transaction(db)

            framework = await generate_framework(
                description.strip(),
                api_key=deepseek_api_key,
                story_bible=story_bible,
                story_context=story_context,
                launch_ready_required=True,
                system_prompt=template_fw_prompt or None,
            )

            story = _require_story_for_user(story_id, user, db)
            story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else story.tags
            story.characters = _normalize_characters_payload(framework.get("characters"))
            story.outline = _merge_framework_outline({}, framework.get("outline"), framework.get("chapters"))
            db.commit()

            _save_framework_snapshot(
                story_id=story.id,
                snapshot_data=_build_current_snapshot_data(story),
                source="initial_generate",
                reply_summary="引导生成初始框架",
                db=db,
            )
            _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)
            db.commit()

            # 配额扣减
            _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 2, db, deduct=True, provider_kind="text")

            framework_result = {
                "tags": story.tags,
                "characters": story.characters,
                "outline": story.outline,
            }
    except Exception as e:
        logger.warning(f"[onboarding] 自动框架生成失败，优雅降级: {e}")
        framework_result = None
    # --- 新增结束 ---

    db.refresh(story)

    return {
        "story_id": story.id,
        "story_bible": story_bible,
        "creative_brief": creative_brief,
        "framework": framework_result,
    }


@app.post("/api/stories/{story_id}/onboarding/skip")
async def onboarding_skip(story_id: int, request: Request, db: Session = Depends(get_db)):
    """跳过引导，直接标记为已完成"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    story.onboarding_completed = True
    db.commit()
    db.refresh(story)
    return {"story_id": story.id, "onboarding_completed": True}


@app.post("/api/stories/{story_id}/import-context/message", response_model=OnboardingMessageOut)
async def import_context_send_message(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if not _is_import_story(story):
        raise HTTPException(400, "仅导入的作品支持导入上下文指导")

    body = await request.json()
    messages_raw = body.get("messages", [])
    previous_collected_info = body.get("collected_info", {})
    current_step = body.get("step")
    if not isinstance(messages_raw, list) or not messages_raw:
        raise HTTPException(400, "消息必填")
    if not isinstance(previous_collected_info, dict):
        previous_collected_info = {}
    if current_step is not None:
        try:
            current_step = int(current_step)
        except (TypeError, ValueError):
            current_step = None

    safe_messages = [
        {"role": msg["role"], "content": str(msg["content"])}
        for msg in messages_raw
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and str(msg.get("content", "")).strip()
    ]
    if not safe_messages:
        raise HTTPException(400, "没有有效消息")

    # 配额预检
    _check_and_consume_feature_quota(
        request,
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        2,
        db,
        deduct=False,
        provider_kind="text",
    )

    import_context = _build_import_guidance_context(story, db)
    creative_brief = None
    deepseek_api_key = _user_deepseek_api_key(request)
    import_prompt = get_system_prompt("prompt.import_context", db) or None
    _release_db_transaction(db)
    try:
        result = await generate_import_guidance_response(
            safe_messages,
            import_context,
            previous_collected_info=previous_collected_info,
            current_step=current_step,
            api_key=deepseek_api_key,
            system_prompt=import_prompt,
        )
        if bool(result.get("is_complete")):
            try:
                creative_brief = await build_import_creative_brief(
                    import_context,
                    result.get("collected_info", {}),
                    api_key=deepseek_api_key,
                )
            except Exception as exc:
                logger.warning("Failed to preview creative brief during import guidance: %s", exc)
    except Exception as exc:
        raise HTTPException(502, f"AI 导入补充调用失败: {exc}")

    # 配额扣减
    _check_and_consume_feature_quota(
        request,
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        2,
        db,
        deduct=True,
        provider_kind="text",
    )

    return OnboardingMessageOut(
        reply=result.get("reply", ""),
        collected_info=result.get("collected_info", {}),
        step=int(result.get("step", 1)),
        total_steps=int(result.get("total_steps", 4)),
        is_complete=bool(result.get("is_complete", False)),
        creative_brief=creative_brief,
    )


@app.post("/api/stories/{story_id}/import-context/confirm")
async def import_context_confirm(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if not _is_import_story(story):
        raise HTTPException(400, "仅导入的作品支持导入上下文指导")

    body = await request.json()
    collected_info = body.get("collected_info", {})
    messages_raw = body.get("messages", [])
    if not isinstance(collected_info, dict):
        collected_info = {}
    if not isinstance(messages_raw, list):
        messages_raw = []

    import_context = _build_import_guidance_context(story, db)
    raw_input = _compose_import_raw_input(import_context, collected_info, messages_raw)
    deepseek_api_key = _user_deepseek_api_key(request)

    # 配额预检
    _check_and_consume_feature_quota(
        request,
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        2,
        db,
        deduct=False,
        provider_kind="text",
    )

    _release_db_transaction(db)
    try:
        creative_brief = await build_import_creative_brief(
            import_context,
            collected_info,
            api_key=deepseek_api_key,
        )
        story_bible = await build_story_bible(
            creative_brief,
            raw_input,
            api_key=deepseek_api_key,
        )
        story_bible["import_guidance"] = _build_import_guidance_payload(collected_info, import_context)
    except Exception as exc:
        raise HTTPException(502, f"导入作品上下文补充失败: {exc}")

    story = _require_story_for_user(story_id, user, db)
    story.story_bible = story_bible
    story.description = story_bible.get("creative_brief", {}).get("one_line_premise", story.description or "")
    story.import_context_completed = True
    db.commit()
    # 配额扣减
    _check_and_consume_feature_quota(
        request,
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        2,
        db,
        deduct=True,
        provider_kind="text",
    )
    db.refresh(story)
    return {
        "story_id": story.id,
        "story_bible": story_bible,
        "creative_brief": creative_brief,
    }


@app.post("/api/stories/{story_id}/import-context/skip")
async def import_context_skip(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    if not _is_import_story(story):
        raise HTTPException(400, "仅导入的作品支持导入上下文指导")
    story.import_context_completed = True
    db.commit()
    return {"ok": True, "story_id": story.id}


@app.get("/api/stories/{story_id}/story-bible")
def get_story_bible(story_id: int, request: Request, db: Session = Depends(get_db)):
    """获取作品圣经"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    return {"story_bible": story.story_bible or {}}


@app.patch("/api/stories/{story_id}/story-bible")
async def update_story_bible(story_id: int, request: Request, db: Session = Depends(get_db)):
    """更新作品圣经"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    bible_update = body.get("story_bible", {})
    from services.story_state import deep_merge_story_bible

    current = deep_merge_story_bible(story.story_bible, bible_update)
    # world_setting 应完全替换而非递归合并，确保删除的字段被移除
    if isinstance(bible_update.get("creative_brief"), dict) and "world_setting" in bible_update["creative_brief"]:
        if isinstance(current.get("creative_brief"), dict):
            current["creative_brief"]["world_setting"] = bible_update["creative_brief"]["world_setting"]
    story.story_bible = current
    creative_brief = current.get("creative_brief") if isinstance(current.get("creative_brief"), dict) else {}
    next_description = str(creative_brief.get("one_line_premise") or "").strip()
    if not next_description:
        next_description = str(creative_brief.get("project_positioning") or "").strip()
    if next_description:
        story.description = next_description
    db.commit()
    db.refresh(story)
    return {"story_bible": story.story_bible}


# ─── Framework (InkAI) ─────────────────────────────────────

async def _background_quality_check(
    story_id: int,
    story_description: str,
    api_key: str | None,
    captured_tags: dict,
    captured_characters: list,
    captured_outline: dict,
    task_id: str | None = None,
):
    """Async background quality gate for framework generate.

    Runs after response is returned. Checks framework quality and,
    if issues found and framework hasn't been modified by the user,
    applies fixes using generate_framework with quality feedback.

    Uses content-based optimistic locking: compares current DB state
    against captured snapshot. If different, skips silently.
    """
    try:
        await asyncio.sleep(2)
        db = SessionLocal()
        try:
            story = db.query(Story).filter(Story.id == story_id).first()
            if not story:
                return

            current_tags = (story.tags or {}) if isinstance(story.tags, dict) else {}
            current_characters = (story.characters or []) if isinstance(story.characters, list) else []
            current_outline = (story.outline or {}) if isinstance(story.outline, dict) else {}

            if current_tags != captured_tags:
                return
            if current_characters != captured_characters:
                return
            if current_outline != captured_outline:
                return

            current_framework = {
                "description": story_description,
                "tags": current_tags,
                "characters": current_characters,
                "outline": current_outline,
            }

            quality_issues = _framework_launch_quality_issues(current_framework)
            if not quality_issues:
                return

            logger.info("Background quality check found %d issues for story %d, fixing...", len(quality_issues), story_id)
            runtime_context = _build_framework_ai_context(story, mode="repair", user_instruction="后台开书质量修复")
            story_bible = story.story_bible
            story_length = _infer_story_length_from_story(story, description=story_description)
            fw_prompt = get_effective_prompt(story_id, "framework", db) or get_system_prompt("prompt.framework_generation", db) or None
            _release_db_transaction(db)
            fixed_framework = await generate_framework(
                story_description,
                api_key=api_key,
                required_min_chapters=20,
                story_bible=story_bible,
                story_context=runtime_context,
                launch_ready_required=True,
                quality_feedback=quality_issues,
                system_prompt=fw_prompt,
                story_length=story_length,
            )
            fixed_framework = await _complete_framework_payload(
                fixed_framework,
                story_description,
                api_key=api_key,
                story_bible=story_bible,
                require_launch_ready=True,
                story_length=story_length,
            )
            remaining = _framework_launch_quality_issues(fixed_framework)
            if remaining:
                logger.warning("Background quality fix for story %d still has %d issues", story_id, len(remaining))
                return

            story = db.query(Story).filter(Story.id == story_id).first()
            if not story:
                return
            recheck_tags = (story.tags or {}) if isinstance(story.tags, dict) else {}
            recheck_chars = (story.characters or []) if isinstance(story.characters, list) else []
            recheck_outline = (story.outline or {}) if isinstance(story.outline, dict) else {}
            if recheck_tags == current_tags and recheck_chars == current_characters and recheck_outline == current_outline:
                story.tags = fixed_framework.get("tags")
                story.characters = _normalize_characters_payload(fixed_framework.get("characters"))
                story.outline = _merge_framework_outline(story.outline, fixed_framework.get("outline"), fixed_framework.get("chapters"))
                db.commit()
                logger.info("Background quality fix applied to story %d", story_id)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Background quality check failed for story %d: %s", story_id, exc)


# ─── 后台任务状态查询 ──────────────────────────────────


def _background_task_belongs_to_user(task: BackgroundTask, user: User, db: Session) -> bool:
    """管理员可查看全部任务，普通用户只能查看自己的任务。"""
    if user.role == "admin":
        return True
    if task.quota_user_id is not None:
        return task.quota_user_id == user.id
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    metadata_owner = metadata.get("owner_user_id") or metadata.get("user_id")
    if metadata_owner is not None:
        try:
            return int(metadata_owner) == user.id
        except (TypeError, ValueError):
            return False
    if task.story_id is not None:
        story = db.query(Story).filter(Story.id == task.story_id).first()
        return bool(story and story.owner_user_id == user.id)
    if task.chapter_id is not None:
        chapter = db.query(Chapter).filter(Chapter.id == task.chapter_id).first()
        return bool(chapter and chapter.story.owner_user_id == user.id)
    if task.shot_id is not None:
        shot = db.query(VideoShot).filter(VideoShot.id == task.shot_id).first()
        return bool(shot and shot.scene and shot.scene.chapter.story.owner_user_id == user.id)
    return False


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request, db: Session = Depends(get_db)):
    """查询后台任务状态"""
    user = _require_user(request, db)
    task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
    if not task or not _background_task_belongs_to_user(task, user, db):
        raise HTTPException(404, "任务未找到")
    status = task_manager.get_task_status(task_id)
    if not status:
        raise HTTPException(404, "任务未找到")
    return status


@app.get("/api/tasks")
async def list_tasks(
    request: Request,
    db: Session = Depends(get_db),
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """列出后台任务"""
    user = _require_user(request, db)
    query = db.query(BackgroundTask)
    if user.role != "admin":
        owned_story_ids = db.query(Story.id).filter(Story.owner_user_id == user.id)
        owned_chapter_ids = db.query(Chapter.id).join(Story).filter(Story.owner_user_id == user.id)
        owned_shot_ids = (
            db.query(VideoShot.id)
            .join(ScriptScene, ScriptScene.id == VideoShot.scene_id)
            .join(Chapter, Chapter.id == ScriptScene.chapter_id)
            .join(Story, Story.id == Chapter.story_id)
            .filter(Story.owner_user_id == user.id)
        )
        query = query.filter(or_(
            BackgroundTask.quota_user_id == user.id,
            and_(
                BackgroundTask.quota_user_id.is_(None),
                or_(
                    BackgroundTask.story_id.in_(owned_story_ids),
                    BackgroundTask.chapter_id.in_(owned_chapter_ids),
                    BackgroundTask.shot_id.in_(owned_shot_ids),
                ),
            ),
        ))
    if status:
        query = query.filter(BackgroundTask.status == status)
    if task_type:
        query = query.filter(BackgroundTask.task_type == task_type)

    total = query.count()
    tasks = query.order_by(BackgroundTask.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "task_type": t.task_type,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/stories/{story_id}/framework/generate")
async def generate_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    raw_description = body.get("description", "")
    if not isinstance(raw_description, str):
        raw_description = ""
    raw_description = raw_description.strip()
    description = raw_description
    if not description or _is_generic_framework_instruction(description):
        description = _build_framework_seed_description(story) or (story.description or "").strip()
    if not description.strip():
        raise HTTPException(400, "描述必填")
    story_context = _build_framework_ai_context(story, mode="initial_generate", user_instruction=raw_description or description)

    requested_min_chapters = _extract_requested_min_chapters([{"role": "user", "content": raw_description or description.strip()}])
    story_bible = story.story_bible
    deepseek_api_key = _user_deepseek_api_key(request)
    # 篇幅推断优先级：模板参数 > story_bible > 用户描述 > 默认 long
    template_story_length = get_template_story_length(story_id, db)
    story_length = template_story_length or _infer_story_length_from_story(story, description=description)

    template_fw_prompt = get_effective_prompt(story_id, "framework", db)
    _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 4, db, deduct=False, provider_kind="text")
    _release_db_transaction(db)
    try:
        framework = await generate_framework(
            description.strip(),
            api_key=deepseek_api_key,
            required_min_chapters=requested_min_chapters,
            story_bible=story_bible,
            story_context=story_context,
            launch_ready_required=True,
            system_prompt=template_fw_prompt or None,
            story_length=story_length,
        )
        framework = await _complete_framework_payload(
            framework,
            description.strip(),
            api_key=deepseek_api_key,
            story_bible=story_bible,
            require_launch_ready=True,
            story_length=story_length,
        )
    except ValueError as exc:
        raise HTTPException(502, f"AI 初始框架生成不完整：{exc}") from exc
    length_defaults = {"short": 5, "medium": 8}
    expected_min = max(requested_min_chapters or 0, length_defaults.get(story_length or "", 10))
    quality_issues = _framework_launch_quality_issues(framework, expected_min_chapters=expected_min)
    if quality_issues:
        try:
            framework = await generate_framework(
                description.strip(),
                api_key=deepseek_api_key,
                required_min_chapters=expected_min,
                story_bible=story_bible,
                story_context=story_context,
                launch_ready_required=True,
                quality_feedback=quality_issues,
                system_prompt=template_fw_prompt or None,
                story_length=story_length,
            )
            framework = await _complete_framework_payload(
                framework,
                description.strip(),
                api_key=deepseek_api_key,
                story_bible=story_bible,
                require_launch_ready=True,
                story_length=story_length,
            )
            quality_issues = _framework_launch_quality_issues(framework, expected_min_chapters=expected_min)
        except ValueError as exc:
            raise HTTPException(502, f"AI 开书框架二次修正失败：{exc}") from exc
    if quality_issues:
        raise HTTPException(502, "AI 首次框架未达到开书可发布标准：" + "；".join(quality_issues))
    if requested_min_chapters and _count_framework_chapters(framework) < requested_min_chapters:
        raise HTTPException(502, f"AI 未能满足至少 {requested_min_chapters} 章的初始框架要求，请换一种更明确的故事描述后重试。")

    story = _require_story_for_user(story_id, user, db)
    _apply_generated_framework_to_story(
        story=story,
        framework=framework,
        raw_description=raw_description,
        resolved_description=description.strip(),
    )
    db.commit()

    # ★ 初始快照：保存首次生成框架后的状态
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data=_build_current_snapshot_data(story),
        source="initial_generate",
        reply_summary="初始框架",
        db=db,
    )
    _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)
    db.commit()

    _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 4, db, deduct=True, provider_kind="text")
    _release_db_transaction(db)

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

    story_context = _story_framework_context(story)
    deepseek_api_key = _user_deepseek_api_key(request)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    tag_system_prompt = get_effective_prompt(story_id, "tag_generation", db)
    _release_db_transaction(db)
    result = await regenerate_tags(story_context, api_key=deepseek_api_key, system_prompt=tag_system_prompt)

    tags = result if isinstance(result, dict) and "type" in result else result
    story = _require_story_for_user(story_id, user, db)
    story.tags = tags
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {"tags": story.tags}


@app.post("/api/stories/{story_id}/framework/characters")
async def regenerate_characters_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    story_context = _story_framework_context(story)
    deepseek_api_key = _user_deepseek_api_key(request)
    template_fw_prompt = get_effective_prompt(story_id, "framework", db)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    _release_db_transaction(db)
    result = await regenerate_characters_with_variance(story_context, api_key=deepseek_api_key, system_prompt=template_fw_prompt or None)

    characters = _normalize_characters_payload(result if isinstance(result, list) else result)
    story = _require_story_for_user(story_id, user, db)
    story.characters = characters
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {"characters": story.characters}


@app.post("/api/stories/{story_id}/framework/outline")
async def regenerate_outline_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    story_context = _story_framework_context(story)
    deepseek_api_key = _user_deepseek_api_key(request)
    template_story_length = get_template_story_length(story_id, db)
    story_length = template_story_length or _infer_story_length_from_story(story)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    template_fw_prompt = get_effective_prompt(story_id, "framework", db)
    _release_db_transaction(db)
    result = await regenerate_outline(story_context, api_key=deepseek_api_key, story_length=story_length, system_prompt=template_fw_prompt or None)

    outline = result if isinstance(result, dict) and "three_acts" in result else result
    story = _require_story_for_user(story_id, user, db)
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
        raise HTTPException(400, "无效的模式")

    chapters = _extract_outline_chapters(story.outline)
    plan_map = {item["chapter_number"]: dict(item) for item in chapters}

    if mode == "update":
        target_number = body.target_chapter_number
        if not isinstance(target_number, int) or target_number < 1:
            raise HTTPException(400, "更新需要目标章节编号")
        existing = plan_map.get(target_number)
        if not existing:
            raise HTTPException(404, "计划章节未找到")
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
                raise HTTPException(400, "插入后需要 after_chapter_number")
            if after_number not in plan_map:
                raise HTTPException(404, "插入锚点章节未找到")

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


def _merge_framework_changes(existing: dict, changes: dict) -> dict:
    """Merge patch-mode changes into existing framework (destructive merge).

    Only fields present in `changes` are updated; all others stay untouched.
    """
    merged = dict(existing)
    if "description" in changes:
        merged["description"] = str(changes["description"]).strip()
    if "tags" in changes and isinstance(changes["tags"], dict):
        merged["tags"] = _merge_tags(merged.get("tags"), changes["tags"])
    if "characters" in changes and isinstance(changes["characters"], list):
        merged["characters"] = _merge_characters_payload(merged.get("characters"), changes["characters"])
    if "outline" in changes or "chapters" in changes:
        merged_outline, merged_chapters = _merge_framework_outline_and_chapters(
            merged.get("outline"),
            changes.get("outline"),
            changes.get("chapters"),
        )
        merged["outline"] = merged_outline
        merged["chapters"] = merged_chapters
    return merged


def _merge_framework_outline_and_chapters(
    existing_outline: dict | None,
    incoming_outline: dict | None,
    incoming_chapters: list | None,
) -> tuple[dict, list]:
    merged = _merge_framework_outline(existing_outline, incoming_outline, incoming_chapters)
    chapters = _extract_outline_chapters(merged)
    return merged, chapters


def _find_outline_act_index(acts: list[dict], act_key) -> int | None:
    normalized_key = _normalize_act_token(act_key)
    if not normalized_key:
        return None
    for index, act in enumerate(acts):
        if not isinstance(act, dict):
            continue
        candidates = {
            act.get("act"),
            act.get("title"),
            act.get("name"),
            index + 1,
        }
        if any(_normalize_act_token(candidate) == normalized_key for candidate in candidates):
            return index
    return None


def _ensure_outline_act(outline: dict, act_key: str, value: dict | None = None) -> list[dict]:
    acts = outline.get("three_acts")
    if not isinstance(acts, list):
        acts = []
    normalized_acts = [dict(act) for act in acts if isinstance(act, dict)]
    outline["three_acts"] = normalized_acts

    index = _find_outline_act_index(normalized_acts, act_key)
    if index is None:
        act_value = dict(value or {})
        act_value["act"] = str(act_value.get("act") or act_key or len(normalized_acts) + 1)
        act_value.setdefault("title", f"阶段 {act_value['act']}")
        act_value.setdefault("summary", "")
        act_value.setdefault("chapters", [])
        normalized_acts.append(act_value)
    return normalized_acts


def _apply_framework_edit_operations(existing: dict, operations: list) -> tuple[dict, list[dict]]:
    framework = {
        "description": str(existing.get("description") or ""),
        "tags": dict(existing.get("tags") or {}),
        "characters": [dict(item) for item in (existing.get("characters") or []) if isinstance(item, dict)],
        "outline": dict(existing.get("outline") or {}),
    }
    framework["outline"]["three_acts"] = [
        dict(act) for act in (framework["outline"].get("three_acts") or []) if isinstance(act, dict)
    ]
    applied: list[dict] = []

    def record(op_name: str, target: str) -> None:
        applied.append({"op": op_name, "target": target})

    for raw_op in operations:
        if not isinstance(raw_op, dict):
            continue
        op_name = str(raw_op.get("op") or "").strip()
        value = raw_op.get("value")

        if op_name == "set_description":
            if isinstance(value, str):
                framework["description"] = value.strip()
                record(op_name, "description")
            continue

        if op_name == "set_tags":
            if isinstance(value, dict):
                framework["tags"] = _merge_tags(framework.get("tags"), value)
                record(op_name, "tags")
            continue

        if op_name == "upsert_character":
            if not isinstance(value, dict):
                continue
            name = str(raw_op.get("name") or value.get("name") or "").strip()
            if not name:
                continue
            value = dict(value)
            value["name"] = str(value.get("name") or name).strip()
            normalized_name = name.casefold()
            characters = framework["characters"]
            for index, character in enumerate(characters):
                if str(character.get("name") or "").strip().casefold() == normalized_name:
                    merged = dict(character)
                    merged.update({k: v for k, v in value.items() if v not in (None, "", [], {})})
                    characters[index] = merged
                    break
            else:
                characters.append(value)
            record(op_name, name)
            continue

        if op_name == "delete_character":
            name = str(raw_op.get("name") or "").strip()
            if not name:
                continue
            normalized_name = name.casefold()
            before = len(framework["characters"])
            framework["characters"] = [
                character for character in framework["characters"]
                if str(character.get("name") or "").strip().casefold() != normalized_name
            ]
            if len(framework["characters"]) != before:
                record(op_name, name)
            continue

        outline = framework["outline"]
        if op_name == "replace_outline_meta":
            if isinstance(value, dict):
                for key in ("themes", "foreshadowing", "serial_strategy"):
                    if key in value:
                        outline[key] = value[key]
                record(op_name, "outline_meta")
            continue

        if op_name == "upsert_act":
            if not isinstance(value, dict):
                value = {}
            act_key = str(raw_op.get("act") or value.get("act") or "").strip()
            if not act_key:
                continue
            acts = _ensure_outline_act(outline, act_key, value)
            index = _find_outline_act_index(acts, act_key)
            if index is not None:
                current = dict(acts[index])
                incoming = {k: v for k, v in dict(value).items() if k != "chapters" and v not in (None, "", [], {})}
                incoming["act"] = incoming.get("act", current.get("act", act_key))
                current.update(incoming)
                current.setdefault("chapters", [])
                acts[index] = current
                record(op_name, act_key)
            continue

        if op_name == "delete_act":
            act_key = str(raw_op.get("act") or "").strip()
            acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
            index = _find_outline_act_index(acts, act_key)
            if index is not None:
                del acts[index]
                outline["three_acts"] = acts
                record(op_name, act_key)
            continue

        if op_name == "upsert_chapter":
            chapter_number = _coerce_chapter_number(raw_op.get("chapter_number"))
            if chapter_number is None:
                continue
            if not isinstance(value, dict):
                value = {}
            existing_chapters = [dict(item) for item in _extract_outline_chapters(outline)]
            previous_chapter = next((item for item in existing_chapters if item.get("chapter_number") == chapter_number), {})
            chapters = [item for item in existing_chapters if item.get("chapter_number") != chapter_number]
            merged_value = dict(previous_chapter)
            merged_value.update({k: v for k, v in dict(value).items() if v not in (None, "", [], {})})
            fallback_act = str(
                raw_op.get("act")
                or merged_value.get("act")
                or _infer_manual_plan_act(existing_chapters, target_chapter_number=chapter_number)
            ).strip() or "1"
            _ensure_outline_act(outline, fallback_act)
            normalized = _normalize_outline_plan_payload(
                merged_value,
                fallback_title=f"Chapter {chapter_number}",
                fallback_act=fallback_act,
            )
            normalized["chapter_number"] = chapter_number
            normalized["act"] = str(normalized.get("act") or fallback_act)
            chapters.append(normalized)
            outline = _normalize_framework_outline(outline, chapters)
            framework["outline"] = outline
            record(op_name, f"chapter:{chapter_number}")
            continue

        if op_name == "delete_chapter":
            chapter_number = _coerce_chapter_number(raw_op.get("chapter_number"))
            if chapter_number is None:
                continue
            chapters = [dict(item) for item in _extract_outline_chapters(outline) if item.get("chapter_number") != chapter_number]
            if len(chapters) != len(_extract_outline_chapters(outline)):
                framework["outline"] = _normalize_framework_outline(outline, chapters)
                record(op_name, f"chapter:{chapter_number}")
            continue

    framework["chapters"] = _extract_outline_chapters(framework["outline"])
    return framework, applied


# ── 框架快照 API ──────────────────────────────────────


@app.get("/api/stories/{story_id}/framework/snapshots")
def list_framework_snapshots(story_id: int, request: Request, db: Session = Depends(get_db)):
    """获取指定故事的框架快照列表（不含 snapshot_data，仅元信息）。"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    snapshots = (
        db.query(FrameworkSnapshot)
        .filter(FrameworkSnapshot.story_id == story.id)
        .order_by(FrameworkSnapshot.created_at.desc())
        .limit(50)
        .all()
    )

    # 旧作品首次查看快照时，自动生成一个当前状态的初始快照作为种子
    if not snapshots:
        _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=_build_current_snapshot_data(story),
            source="initial_generate",
            reply_summary="初始框架（自动生成）",
            db=db,
        )
        db.commit()
        snapshots = (
            db.query(FrameworkSnapshot)
            .filter(FrameworkSnapshot.story_id == story.id)
            .order_by(FrameworkSnapshot.created_at.desc())
            .limit(50)
            .all()
        )

    return {
        "snapshots": [
            {
                "id": s.id,
                "source": s.source,
                "reply_summary": s.reply_summary or "",
                "created_at": s.created_at.isoformat() if s.created_at else "",
            }
            for s in snapshots
        ],
    }


@app.post("/api/stories/{story_id}/framework/snapshots/{snapshot_id}/restore")
def restore_framework_snapshot_endpoint(story_id: int, snapshot_id: int, request: Request, db: Session = Depends(get_db)):
    """将故事框架恢复到指定快照版本。回滚前自动保存当前状态。"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    try:
        new_data = restore_framework_snapshot(story, snapshot_id, db)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    db.commit()
    db.refresh(story)
    return {
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "snapshot_data": new_data,
        "message": "已恢复到所选版本",
    }


@app.post("/api/stories/{story_id}/framework/adjust")
async def adjust_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    body = await request.json()
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "消息必填")
    requested_min_chapters = _extract_requested_min_chapters(messages)

    existing_framework = {
        "description": story.description or "",
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }
    context_story = _build_framework_ai_context(
        story,
        mode="adjust",
        user_instruction=str(messages[-1].get("content") or "") if messages else "",
    )
    deepseek_api_key = _user_deepseek_api_key(request)
    template_story_length = get_template_story_length(story_id, db)
    story_length = template_story_length or _infer_story_length_from_story(story, messages=messages)
    template_edit_prompt = get_effective_prompt(story_id, "framework_editing", db)

    # 检查是否仅分析模式
    is_analyze_only = any(
        "【仅分析模式" in (msg.get("content") or "")
        for msg in messages
    )
    if is_analyze_only:
        _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
        _release_db_transaction(db)
        try:
            plan = await adjust_framework_with_chat(
                context_story,
                messages,
                api_key=deepseek_api_key,
                existing_framework=existing_framework,
                system_prompt=template_edit_prompt or None,
                story_length=story_length,
            )
        except ValueError as exc:
            raise HTTPException(502, f"AI 框架分析返回格式无效：{exc}") from exc
        db = SessionLocal()
        _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
        db.close()
        return {
            "reply": plan.get("reply", ""),
            "story": {
                "description": story.description,
                "tags": story.tags,
                "characters": story.characters,
                "outline": story.outline,
            },
            "chapters": _extract_outline_chapters(story.outline or {}),
            "applied_operations": [],
            "warnings": ["仅分析模式：未写入数据库"],
            "validation_errors": [],
        }

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    _release_db_transaction(db)
    try:
        plan = await adjust_framework_with_chat(
            context_story,
            messages,
            api_key=deepseek_api_key,
            required_min_chapters=requested_min_chapters,
            existing_framework=existing_framework,
            system_prompt=template_edit_prompt or None,
            story_length=story_length,
        )
    except ValueError as exc:
        raise HTTPException(502, f"AI 框架调整返回格式无效：{exc}") from exc

    apply_result = apply_framework_operations(
        existing_framework=existing_framework,
        operations=plan.get("operations"),
        patches=plan.get("patches"),
    )

    if apply_result["errors"]:
        raise HTTPException(502, "；".join(apply_result["errors"]))

    framework = apply_result["framework"]
    validation_errors = validate_applied_framework_consistency(framework)

    if validation_errors:
        raise HTTPException(502, "；".join(validation_errors))

    if requested_min_chapters and _count_framework_chapters(framework) < requested_min_chapters:
        raise HTTPException(
            502,
            f"AI 未能满足至少 {requested_min_chapters} 章的硬性要求，请重试或换一种更明确的扩写指令。",
        )

    story = _require_story_for_user(story_id, user, db)

    # ★ 自动快照：保存调整前的当前状态（用于回退）
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data=_build_current_snapshot_data(story),
        source="panel_adjust",
        reply_summary=(plan.get("reply") or "")[:255] if plan.get("reply") else None,
        db=db,
    )
    _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

    description = str(framework.get("description") or story.description or "").strip()
    story.description = description
    story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
    story.characters = _normalize_characters_payload(framework.get("characters"))
    story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]

    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {
        "reply": plan.get("reply", ""),
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "chapters": _extract_outline_chapters(framework.get("outline", {})),
        "applied_operations": apply_result["applied_operations"],
        "warnings": [*plan.get("warnings", []), *apply_result["warnings"]],
        "validation_errors": validation_errors,
    }


@app.post("/api/stories/{story_id}/framework/continue")
async def continue_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    # ★ 自动快照：保存续写前的当前状态（用于回退）
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data=_build_current_snapshot_data(story),
        source="panel_continue",
        reply_summary="一键续写",
        db=db,
    )

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)

    existing_framework = {
        "description": story.description or "",
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }
    before_chapter_count = len(_extract_outline_chapters(story.outline))
    deepseek_api_key = _user_deepseek_api_key(request)
    template_story_length = get_template_story_length(story_id, db)
    story_length = template_story_length or _infer_story_length_from_story(story, description=str(story.description or ""))
    # 短篇续写目标章节数更少
    if story_length == "short":
        continue_instruction = (
            "一键续写：请基于当前框架继续向后扩展后续阶段和章节规划。"
            "在 framework.outline.three_acts 中至少新增 5 个后续章节任务卡。"
            "不要只在 reply 里描述扩展到了多少章，必须体现在 framework.outline.three_acts 中。"
            "每个新增章节尽量包含 title、summary、goal、conflict、hook、payoff、highlight、key_events。"
            "保留原有主线、角色成长与代价平衡，不要删除现有内容。"
        )
    else:
        continue_instruction = (
            "一键续写：请基于当前框架继续向后扩展后续阶段和真实章节规划。"
            "在 framework.outline.three_acts 中至少新增 10 个后续章节任务卡。"
            "不要只在 reply 里描述扩展到了多少章，必须体现在 framework.outline.three_acts 中。"
            "每个新增章节尽量包含 title、summary、goal、conflict、hook、payoff、highlight、key_events。"
            "保留原有主线、角色成长与代价平衡，不要删除现有内容。"
        )
    context_story = _build_framework_ai_context(story, mode="continue", user_instruction=continue_instruction)

    messages = [
        {
            "role": "user",
            "content": continue_instruction,
        }
    ]

    cont_prompt = get_effective_prompt(story_id, "framework", db) or get_system_prompt("prompt.framework_continuation", db) or None
    _release_db_transaction(db)
    try:
        plan = await continue_framework_with_chat(
            context_story,
            messages,
            api_key=deepseek_api_key,
            story_length=story_length,
            system_prompt=cont_prompt,
        )
    except ValueError as exc:
        raise HTTPException(502, f"AI 续写返回格式无效：{exc}") from exc

    apply_result = apply_framework_operations(
        existing_framework=existing_framework,
        operations=plan.get("operations"),
        patches=plan.get("patches"),
    )

    if apply_result["errors"]:
        raise HTTPException(502, "；".join(apply_result["errors"]))

    framework = apply_result["framework"]
    after_chapter_count = _count_framework_chapters(framework)

    has_new_chapter = any(
        op.startswith("add_chapter") or op.startswith("insert_chapter_after")
        for op in apply_result["applied_operations"]
    )
    if not has_new_chapter or after_chapter_count <= before_chapter_count:
        raise HTTPException(
            502,
            "AI 续写没有写入任何新增章节。请重试，或直接输入“新增第X到第Y章，并列出每章任务卡”。",
        )

    story = _require_story_for_user(story_id, user, db)

    story.description = str(framework.get("description") or story.description or "").strip()
    story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
    story.characters = _normalize_characters_payload(framework.get("characters"))
    story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]

    _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)
    return {
        "reply": plan.get("reply", ""),
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "chapters": _extract_outline_chapters(framework.get("outline", {})),
        "applied_operations": apply_result["applied_operations"],
        "warnings": [*plan.get("warnings", []), *apply_result["warnings"]],
    }


def _build_chapter_pipeline_error_quality_gate(review: Any) -> dict[str, Any]:
    """把章节流水线异常中的结构化门禁报告映射为 API 详情输入。"""
    error_review = review if isinstance(review, dict) else {"reason": str(review)}
    error_deterministic = error_review.get("deterministic") if isinstance(error_review.get("deterministic"), dict) else {}
    return {
        "ok": False,
        "content": "",
        "attempts": error_review.get("attempts", 0),
        "report": {
            "deterministic": error_deterministic,
            "review": error_review,
            "pipeline_quality_error": True,
        },
        "source": "expand_chapter",
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
        raise HTTPException(400, "章节标题必填")

    chapter_info = {
        "title": chapter_title.strip(),
        "act": act if isinstance(act, str) else "",
        "chapter_number": chapter_number_val,
        "summary": str(body.get("summary") or "").strip(),
        "goal": str(body.get("goal") or "").strip(),
        "conflict": str(body.get("conflict") or "").strip(),
        "hook": str(body.get("hook") or "").strip(),
        "payoff": str(body.get("payoff") or "").strip(),
        "highlight": str(body.get("highlight") or "").strip(),
        "key_events": _normalize_key_events(body.get("key_events")),
    }

    _check_and_consume_feature_quota(request, user.id, "chapter.expand.monthly_limit", 1, db, deduct=False, provider_kind="text")
    memory_quota_result = _check_and_consume_feature_quota(
        request,
        user.id,
        "chapter.memory.refresh",
        1,
        db,
        deduct=False,
        provider_kind="text",
    )

    previous_chapter_summary = ""
    chapter_num_for_query = chapter_number_val
    if not isinstance(chapter_num_for_query, int) or chapter_num_for_query <= 0:
        max_num_row = (
            db.query(Chapter.chapter_number)
            .filter(Chapter.story_id == story_id)
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        chapter_num_for_query = (max_num_row[0] + 1) if max_num_row else 1

    if isinstance(chapter_num_for_query, int) and chapter_num_for_query > 1:
        prev_chapter = (
            db.query(Chapter)
            .filter(
                Chapter.story_id == story_id,
                Chapter.chapter_number < chapter_num_for_query,
                Chapter.novel_content.isnot(None),
                Chapter.status.in_(["completed", "draft"]),
            )
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        if prev_chapter and prev_chapter.novel_content:
            ending_text = prev_chapter.novel_content[-800:]
            memory_compact = build_story_memory_compact(
                story.story_memory if isinstance(story.story_memory, dict) else {}
            )
            parts_list = [f"上一章《第{prev_chapter.chapter_number}章：{prev_chapter.title or ''}》结尾：\n{ending_text}"]
            if memory_compact.get("story_state"):
                parts_list.append(f"当前故事状态：{memory_compact['story_state']}")
            if memory_compact.get("current_arc_focus"):
                parts_list.append(f"当前剧情焦点：{memory_compact['current_arc_focus']}")
            if memory_compact.get("open_loops"):
                loops = memory_compact["open_loops"][:5]
                parts_list.append("待回收伏笔：\n- " + "\n- ".join(loops))
            previous_chapter_summary = "\n".join(parts_list)
            if len(previous_chapter_summary) > 2000:
                previous_chapter_summary = previous_chapter_summary[:2000]

    chapter_info["chapter_number"] = chapter_num_for_query
    chapter_runtime_context = _build_chapter_runtime_context(
        story,
        db,
        chapter_info,
        user_instruction="根据章节任务卡扩写正文",
    )
    previous_bridge = _build_previous_chapter_bridge(story_id, chapter_num_for_query, db)
    if previous_bridge.get("summary_text"):
        previous_chapter_summary = str(previous_bridge["summary_text"])
    deepseek_api_key = _user_deepseek_api_key(request)

    _release_db_transaction(db)
    template_ch_prompt = get_effective_prompt(story_id, "chapter", db)
    try:
        novel_content = await expand_chapter_to_content(
            chapter_runtime_context,
            chapter_info,
            api_key=deepseek_api_key,
            previous_chapter_summary=previous_chapter_summary,
            system_prompt=template_ch_prompt or None,
            db=db,
        )
    except ChapterPipelineQualityError as exc:
        quality_gate = _build_chapter_pipeline_error_quality_gate(exc.review)
        raise HTTPException(status_code=422, detail=format_quality_gate_detail(quality_gate)) from exc
    pipeline_result = chapter_runtime_context.get("_last_chapter_pipeline_result") if isinstance(chapter_runtime_context, dict) else {}
    review = pipeline_result.get("review") if isinstance(pipeline_result, dict) else {}
    deterministic_report = review.get("deterministic") if isinstance(review, dict) and isinstance(review.get("deterministic"), dict) else {}
    quality_gate = {
        "ok": True,
        "content": novel_content,
        "report": {
            "deterministic": deterministic_report,
            "review": review if isinstance(review, dict) else {},
            "pipeline_ok": bool(pipeline_result.get("ok")) if isinstance(pipeline_result, dict) else False,
            "pipeline_mode": "two_stage",
            "stages": pipeline_result.get("stages") if isinstance(pipeline_result, dict) else {},
            "editor_review_skipped": bool(pipeline_result.get("editor_review_skipped")) if isinstance(pipeline_result, dict) else True,
        },
    }

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
    chapter.quality_score = quality_gate.get("report")
    if existing is None:
        db.add(chapter)
        db.flush()
        _initialize_empty_chapter_workspace(chapter.id)
    db.add(ChatMessage(chapter_id=chapter.id, role="assistant", content=novel_content))
    db.commit()
    _check_and_consume_feature_quota(request, user.id, "chapter.expand.monthly_limit", 1, db, deduct=True, provider_kind="text")
    db.refresh(chapter)
    memory_billing_ctx = _detach_pending_platform_points(
        request,
        memory_quota_result.get("usage_event_id"),
    )
    memory_task_id = f"chapter_memory_{chapter.id}_{uuid.uuid4().hex[:10]}"
    try:
        await task_manager.submit_task(
            memory_task_id,
            "chapter_memory_refresh",
            _background_refresh_chapter_memory,
            chapter.id,
            deepseek_api_key,
            memory_billing_ctx,
            timeout=300,
            max_retries=1,
            chapter_id=chapter.id,
            quota_user_id=user.id,
            quota_feature_key="chapter.memory.refresh",
            quota_amount=1,
            quota_usage_event_id=memory_quota_result.get("usage_event_id"),
        )
    except Exception:
        _finish_streaming_platform_points(
            memory_billing_ctx,
            success=False,
            error_code="task_submission_failed",
        )
        logger.exception("提交章节记忆刷新任务失败 chapter=%s", chapter.id)
    return chapter


@app.post("/api/chapters/{chapter_id}/rewrite-selection")
async def rewrite_selection_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    selected_text = body.get("selected_text", "")
    chapter_context = body.get("chapter_context", body.get("context", ""))

    if not isinstance(selected_text, str) or not selected_text.strip():
        raise HTTPException(400, "选中文本必填")
    if not isinstance(chapter_context, str):
        chapter_context = ""

    chapter_runtime_context = _build_chapter_runtime_context(
        chapter.story,
        db,
        {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or f"第{chapter.chapter_number}章",
            "act": chapter.act or "",
            "key_events": chapter.key_events or [],
        },
        user_instruction="局部改写正文片段",
    )
    deepseek_api_key = _user_deepseek_api_key(request)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    template_system = get_effective_prompt(chapter.story_id, "chapter", db)
    _release_db_transaction(db)
    rewritten = await rewrite_selection(
        selected_text.strip(),
        chapter_context.strip() or (chapter.novel_content or "")[:4000],
        story_context=chapter_runtime_context,
        api_key=deepseek_api_key,
        system_prompt=template_system or None,
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
        raise HTTPException(400, "指令必填")
    if not chapter.novel_content or not chapter.novel_content.strip():
        raise HTTPException(400, "章节没有小说内容可调整")

    chapter_info = {
        "title": chapter.title or f"第{chapter.chapter_number}话",
        "act": chapter.act or "",
        "chapter_number": chapter.chapter_number,
        "key_events": chapter.key_events or [],
    }
    chapter_runtime_context = _build_chapter_runtime_context(
        chapter.story,
        db,
        chapter_info,
        user_instruction=instruction.strip(),
    )
    deepseek_api_key = _user_deepseek_api_key(request)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    template_system = get_effective_prompt(chapter.story_id, "chapter", db)
    existing_creation_pack = (
        chapter.quality_score.get("creation_pack")
        if isinstance(chapter.quality_score, dict) and isinstance(chapter.quality_score.get("creation_pack"), dict)
        else None
    )
    _release_db_transaction(db)
    updated_content = await adjust_chapter_content(
        chapter_runtime_context,
        chapter_info,
        chapter.novel_content,
        instruction.strip(),
        api_key=deepseek_api_key,
        system_prompt=template_system or None,
    )
    quality_gate = await finalize_generated_chapter_content(
        content=updated_content,
        story_context=chapter_runtime_context,
        chapter_info=chapter_info,
        api_key=deepseek_api_key,
        system_prompt=template_system or None,
        source="adjust_chapter_content",
        existing_creation_pack=existing_creation_pack,
        allow_pipeline_rerun=False,
    )
    if not quality_gate.get("ok"):
        raise HTTPException(status_code=422, detail=format_quality_gate_detail(quality_gate))
    updated_content = quality_gate["content"]
    chapter = _require_chapter_for_user(chapter_id, user, db)
    _apply_chapter_content(chapter, updated_content, status="completed")
    chapter.quality_score = quality_gate.get("report")
    await _refresh_chapter_memory(chapter, request, db)
    db.commit()
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(chapter)
    return chapter


@app.patch("/api/chapters/{chapter_id}/continuity-memory", response_model=ChapterOut)
async def update_continuity_memory(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()

    current = chapter.memory_summary if isinstance(chapter.memory_summary, dict) else {}
    if not isinstance(current, dict):
        current = {}

    summary = body.get("chapter_summary")
    handoff = body.get("chapter_handoff")

    update: dict[str, Any] = {}
    if isinstance(summary, dict):
        update["chapter_summary"] = summary
    if isinstance(handoff, dict):
        update["chapter_handoff"] = handoff

    if isinstance(current.get("chapter_summary"), dict):
        current["chapter_summary"].update(summary) if isinstance(summary, dict) else None
    elif summary:
        current["chapter_summary"] = summary

    if isinstance(current.get("chapter_handoff"), dict):
        current["chapter_handoff"].update(handoff) if isinstance(handoff, dict) else None
    elif handoff:
        current["chapter_handoff"] = handoff

    chapter.memory_summary = current
    db.commit()
    db.refresh(chapter)
    return chapter


@app.post("/api/stories/{story_id}/refresh-all-memories")
async def refresh_all_memories(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    chapters = (
        db.query(Chapter)
        .filter(Chapter.story_id == story.id, Chapter.novel_content.isnot(None), Chapter.novel_content != "")
        .order_by(Chapter.chapter_number)
        .all()
    )
    # 统计需要刷新的章节数并预检配额
    needs_refresh = 0
    for chapter in chapters:
        memory = chapter.memory_summary if isinstance(chapter.memory_summary, dict) else {}
        handoff = memory.get("chapter_handoff") if isinstance(memory.get("chapter_handoff"), dict) else {}
        if not (handoff.get("ending_location") and handoff.get("active_characters")):
            needs_refresh += 1
    if needs_refresh > 0:
        _check_and_consume_feature_quota(
            request, user.id, "ai.text.advanced_calls.monthly_limit",
            needs_refresh, db, deduct=False, provider_kind="text",
        )

    refreshed = 0
    for chapter in chapters:
        memory = chapter.memory_summary if isinstance(chapter.memory_summary, dict) else {}
        handoff = memory.get("chapter_handoff") if isinstance(memory.get("chapter_handoff"), dict) else {}
        if handoff.get("ending_location") and handoff.get("active_characters"):
            continue
        await _refresh_chapter_memory(chapter, request, db)
        refreshed += 1
    db.commit()
    # 配额扣减（按实际刷新数量）
    if refreshed > 0:
        _check_and_consume_feature_quota(
            request, user.id, "ai.text.advanced_calls.monthly_limit",
            refreshed, db, deduct=True, provider_kind="text",
        )
    for chapter in chapters:
        db.refresh(chapter)
    return {"refreshed": refreshed, "total": len(chapters)}


@app.post("/api/chapters/{chapter_id}/quality-assess")
async def quality_assess_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    content = chapter.novel_content or ""
    if not content.strip():
        raise HTTPException(400, "章节没有小说内容可评估")

    deepseek_api_key = _user_deepseek_api_key(request)
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    _release_db_transaction(db)
    assessment = await quality_assess(content, api_key=deepseek_api_key)

    chapter = _require_chapter_for_user(chapter_id, user, db)
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
        raise HTTPException(400, "选中文本必填")
    if not isinstance(character_profiles, str):
        character_profiles = str(character_profiles) if character_profiles else ""
    if not isinstance(page_count, int) or page_count < 1:
        page_count = 4
    if page_count > 20:
        page_count = 20

    deepseek_api_key = _user_deepseek_api_key(request)
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=False, provider_kind="text")
    _release_db_transaction(db)
    scenes = await scenes_from_selection(
        selected_text.strip(),
        character_profiles=character_profiles,
        page_count=page_count,
        api_key=deepseek_api_key,
    )
    _check_and_consume_feature_quota(request, user.id, "scene.generate.monthly_limit", 1, db, deduct=True, provider_kind="text")
    sanitized_scenes, sanitized_indices = sanitize_scene_list(scenes)
    return {"scenes": sanitized_scenes, "page_count": page_count, "sanitized_indices": sanitized_indices}


# ─── Import/Export ────────────────────────────────────────────

MAX_IMPORT_FILE_BYTES = int(os.getenv("MAX_IMPORT_FILE_BYTES", str(10 * 1024 * 1024)))


def _chapter_split_patterns() -> list[tuple[re.Pattern, str]]:
    """Return (regex_pattern, label) for known chapter delimiters, ordered by priority."""
    return [
        (re.compile(r"第[零一二三四五六七八九十百千\d]+[章话节回]"), "chinese_chapter"),
        (re.compile(r"^#{1,3}\s+.+", re.MULTILINE), "markdown_heading"),
        (re.compile(r"^第\s*\d+\s*[章话节回]", re.MULTILINE), "chinese_chapter_space"),
        (re.compile(r"^Chapter\s+\d+", re.IGNORECASE | re.MULTILINE), "english_chapter"),
    ]


def _parse_import_text_into_chapters(text: str) -> list[ImportChapterInfo]:
    """Detect chapter boundaries in raw text and return chapter infos."""
    patterns = _chapter_split_patterns()
    boundaries: list[tuple[int, str, str]] = []  # (position, method, title)

    for pattern, method_name in patterns:
        for match in pattern.finditer(text):
            title = match.group().strip()
            # Strip leading '#' from markdown headings
            if method_name == "markdown_heading":
                title = re.sub(r"^#+\s*", "", title)
            boundaries.append((match.start(), "regex", title))

    if boundaries:
        # Deduplicate: keep the earliest match at each position (±10 char window)
        boundaries.sort(key=lambda x: x[0])
        deduped: list[tuple[int, str, str]] = []
        for pos, method, title in boundaries:
            if not deduped or pos - deduped[-1][0] > 10:
                deduped.append((pos, method, title))
        boundaries = deduped

    chapters: list[ImportChapterInfo] = []
    if len(boundaries) >= 2:
        for i, (pos, method, title) in enumerate(boundaries):
            start = pos
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
            raw_content = text[start:end].strip()
            if not raw_content:
                continue
            chapters.append(ImportChapterInfo(
                chapter_number=i + 1,
                title=title,
                content=raw_content,
                detection_method="regex",
            ))
    elif len(boundaries) == 1:
        # Single boundary: split into chapter + remaining
        pos, method, title = boundaries[0]
        header_content = text[:pos].strip()
        chapter_content = text[pos:].strip()
        if header_content:
            chapters.append(ImportChapterInfo(
                chapter_number=1,
                title="",
                content=header_content,
                detection_method="regex",
            ))
        if chapter_content:
            chapters.append(ImportChapterInfo(
                chapter_number=len(chapters) + 1,
                title=title,
                content=chapter_content,
                detection_method="regex",
            ))

    # If still no structural detection, return as single chapter
    if not chapters:
        chapters.append(ImportChapterInfo(
            chapter_number=1,
            title="",
            content=text.strip(),
            detection_method="regex",
        ))

    return chapters


def _single_import_source(text: str) -> list[ImportChapterInfo]:
    source_text = text.strip()
    return [
        ImportChapterInfo(
            chapter_number=1,
            title="导入原文",
            content=source_text,
            detection_method="raw_text",
        )
    ]


def _normalize_ai_import_chapters(chapters_payload: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(chapters_payload, list):
        return normalized

    for index, item in enumerate(chapters_payload, start=1):
        if not isinstance(item, dict):
            continue
        chapter_number = item.get("chapter_number")
        try:
            chapter_number = int(chapter_number)
        except Exception:
            chapter_number = index
        title = str(item.get("title") or "").strip() or f"第{chapter_number}话"
        act = str(item.get("act") or "").strip() or None
        key_events_raw = item.get("key_events")
        if isinstance(key_events_raw, list):
            key_events = [str(event).strip() for event in key_events_raw if str(event).strip()]
        else:
            key_events = []
        normalized.append(
            {
                "chapter_number": max(1, chapter_number),
                "title": title,
                "act": act,
                "key_events": key_events,
            }
        )

    normalized.sort(key=lambda item: item["chapter_number"])
    for index, item in enumerate(normalized, start=1):
        item["chapter_number"] = index
    return normalized


@app.post("/api/import/parse", response_model=ImportParseResponse)
async def import_parse(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Parse an uploaded novel file (.txt, .md, .docx) and detect chapters."""
    _ensure_platform_seed(db)
    user = _require_user(request, db)

    # Read file content
    contents = await file.read()
    if len(contents) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(413, f"文件过大，最大支持 {MAX_IMPORT_FILE_BYTES // (1024 * 1024)}MB")

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()

    # Extract text based on file type
    text = ""
    if ext == ".docx":
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(contents))
            text = "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            raise HTTPException(400, f"无法解析 .docx 文件: {exc}")
    elif ext in (".txt", ".md", ""):
        text = contents.decode("utf-8", errors="replace")
    else:
        raise HTTPException(400, f"不支持的文件类型: {ext}，仅支持 .txt, .md, .docx")

    text = text.strip()
    if not text:
        raise HTTPException(400, "文件内容为空")

    detected_title = Path(filename).stem or "未命名小说"
    total_word_count_text = "".join(text.split())
    total_word_count = len(total_word_count_text)

    chapters = _single_import_source(text)

    return ImportParseResponse(
        detected_title=detected_title,
        chapters=chapters,
        total_word_count=total_word_count,
    )


@app.post("/api/import/create", response_model=StoryOut)
async def import_create(body: ImportCreateRequest, request: Request, db: Session = Depends(get_db)):
    """Create a story with chapters from parsed import data."""
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    combined = "\n\n".join(
        str(ch_data.content or "").strip()
        for ch_data in body.chapters
        if str(ch_data.content or "").strip()
    ).strip()
    if not combined:
        raise HTTPException(400, "导入内容为空，无法创建作品")

    _check_and_consume_feature_quota(
        request,
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        2,
        db,
        deduct=False,
        provider_kind="text",
    )
    _check_and_consume_feature_quota(
        request,
        user.id,
        "import.story_bible.generate",
        2,
        db,
        deduct=False,
        provider_kind="text",
    )
    api_key = _user_deepseek_api_key(request)
    _release_db_transaction(db)
    try:
        framework = await analyze_import_material(combined, api_key=api_key)
    except Exception as exc:
        logger.error("Import AI analysis failed: %s", exc)
        raise HTTPException(502, f"AI分析导入内容失败: {exc}")

    content_type = str(framework.get("content_type") or "chapter_manuscript").strip().lower()
    tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else {}
    characters = framework.get("characters") if isinstance(framework.get("characters"), list) else []
    outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else {}
    ai_chapters = _normalize_ai_import_chapters(framework.get("chapters"))

    story = Story(
        title=body.title,
        description=body.description or ("导入内容已通过 AI 分析生成框架" if outline else ""),
        owner_user_id=user.id,
        onboarding_completed=True,
        source_type="import",
        import_context_completed=False,
    )
    if tags:
        story.tags = tags
    if characters:
        story.characters = _normalize_characters_payload(characters)
    if outline:
        story.outline = outline
    db.add(story)
    db.flush()

    if content_type == "outline_source":
        for ch_data in ai_chapters:
            chapter = Chapter(
                story_id=story.id,
                chapter_number=ch_data["chapter_number"],
                title=ch_data["title"],
                novel_content="",
                content_source="import",
                status="draft",
                word_count=0,
                act=ch_data.get("act"),
                key_events=ch_data.get("key_events") or None,
            )
            db.add(chapter)
            db.flush()
            _initialize_empty_chapter_workspace(chapter.id)
    else:
        ai_meta_by_number = {item["chapter_number"]: item for item in ai_chapters}
        for index, ch_data in enumerate(body.chapters, start=1):
            ai_meta = ai_meta_by_number.get(index, {})
            chapter = Chapter(
                story_id=story.id,
                chapter_number=index,
                title=ai_meta.get("title") or ch_data.title or f"第{index}话",
                novel_content=ch_data.content,
                content_source="import",
                status="draft",
                word_count=_count_words(ch_data.content),
                act=ai_meta.get("act") or ch_data.act,
                key_events=ai_meta.get("key_events") or ch_data.key_events or None,
            )
            db.add(chapter)
            db.flush()
            _initialize_empty_chapter_workspace(chapter.id)

    db.commit()
    _check_and_consume_feature_quota(
        request,
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        2,
        db,
        deduct=True,
        provider_kind="text",
    )
    story_id = story.id
    db.refresh(story)

    try:
        provisional_story_bible = await _build_import_provisional_story_bible(
            story,
            db,
            api_key=api_key,
        )
        if provisional_story_bible:
            story = _require_story_for_user(story_id, user, db)
            story.story_bible = provisional_story_bible
            creative_brief = provisional_story_bible.get("creative_brief") if isinstance(provisional_story_bible.get("creative_brief"), dict) else {}
            next_description = str(creative_brief.get("one_line_premise") or creative_brief.get("project_positioning") or "").strip()
            if next_description:
                story.description = next_description
            db.commit()
            _check_and_consume_feature_quota(
                request,
                user.id,
                "import.story_bible.generate",
                2,
                db,
                deduct=True,
                provider_kind="text",
            )
            db.refresh(story)
    except Exception as exc:
        logger.warning("Import provisional story bible generation failed for story %s: %s", story.id, exc)
    return story


@app.post("/api/stories/{story_id}/framework/analyze", response_model=FrameworkAnalyzeResponse)
async def framework_analyze_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    """Analyze existing story chapter content to extract tags, characters, and outline."""
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    # Read all chapters, concatenate first 5 chapters' novel_content
    chapters = (
        db.query(Chapter)
        .filter(Chapter.story_id == story_id)
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    content_parts = []
    for ch in chapters[:5]:
        if ch.novel_content:
            content_parts.append(ch.novel_content)
    combined = "\n\n".join(content_parts)
    if not combined.strip():
        raise HTTPException(400, "故事还没有正文内容可分析，请先创作至少一个章节")

    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)
    try:
        api_key = _user_deepseek_api_key(request)
        _release_db_transaction(db)
        framework = await analyze_content_framework(combined, api_key=api_key)

        story = _require_story_for_user(story_id, user, db)
        tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else {}
        characters = framework.get("characters") if isinstance(framework.get("characters"), list) else []
        outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else {}

        if tags:
            story.tags = tags
        if characters:
            story.characters = _normalize_characters_payload(characters)
        if outline:
            story.outline = outline
        db.commit()
        _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
        db.refresh(story)

        return FrameworkAnalyzeResponse(
            tags=story.tags,
            characters=story.characters,
            outline=story.outline,
        )
    except Exception as exc:
        db.rollback()
        logger.error("Framework analysis failed for story %s: %s", story_id, exc)
        raise HTTPException(502, f"AI分析失败: {exc}")


# ─── 提示词模板系统 API ──────────────────────────────────

def _serialize_template(template, current_user_id, db_session) -> dict:
    """将 PromptTemplate 序列化为字典"""
    author = None
    if template.author_user_id:
        u = db_session.query(User).filter(User.id == template.author_user_id).first()
        author = {"id": u.id, "username": u.name} if u else None

    is_liked = False
    if current_user_id:
        like = db_session.query(TemplateLike).filter(
            TemplateLike.template_id == template.id,
            TemplateLike.user_id == current_user_id,
        ).first()
        is_liked = like is not None

    def _json_or_none(val):
        return val if isinstance(val, (dict, list, type(None))) else None

    return {
        "id": template.id,
        "name": template.name,
        "description": template.description or "",
        "author": author,
        "category": template.category,
        "tags": template.tags or [],
        "status": template.status,
        "visibility": template.visibility,
        "is_public": template.is_public,
        "usage_count": template.usage_count,
        "like_count": template.like_count,
        "is_liked": is_liked,
        "framework_prompt": template.framework_prompt,
        "chapter_prompt": template.chapter_prompt,
        "character_prompt": template.character_prompt,
        "manga_style_prompt": template.manga_style_prompt,
        "framework_params": _json_or_none(template.framework_params),
        "chapter_params": _json_or_none(template.chapter_params),
        "character_params": _json_or_none(template.character_params),
        "manga_style_params": _json_or_none(template.manga_style_params),
        "forked_from": template.forked_from,
        "submitted_at": template.submitted_at.isoformat() if template.submitted_at else None,
        "reviewed_at": template.reviewed_at.isoformat() if template.reviewed_at else None,
        "review_note": template.review_note,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


# ── 系统默认 Prompt 参考 ──────────────────────────────

@app.get("/api/prompt-templates/defaults")
def get_system_default_prompts(request: Request, db: Session = Depends(get_db)):
    """返回系统内置的四类提示词，供用户创建模板时参考。"""
    _ensure_platform_seed(db)
    return {
        "framework": get_system_prompt("prompt.framework_generation", db),
        "chapter": get_system_prompt("prompt.chapter_generation", db),
        "character": get_system_prompt("prompt.reference_character", db),
        "manga_style": get_system_prompt("prompt.reference_manga_style", db),
    }


# ── 管理员：系统默认提示词管理 ────────────────────────────


_ADMIN_PROMPT_KEYS = [
    ("framework_generation", "prompt.framework_generation", "框架生成"),
    ("framework_editing", "prompt.framework_editing", "框架编辑"),
    ("framework_continuation", "prompt.framework_continuation", "框架续写"),
    ("chapter_generation", "prompt.chapter_generation", "正文扩写"),
    ("reference_character", "prompt.reference_character", "角色生成"),
    ("reference_manga_style", "prompt.reference_manga_style", "漫画风格"),
]


@app.get("/api/admin/system-prompts")
def admin_list_system_prompts(request: Request, db: Session = Depends(get_db)):
    """管理员查看所有系统默认提示词。"""
    _require_admin(request, db)
    return {
        key: {
            "key": full_key,
            "name": display_name,
            "content": get_system_prompt(full_key, db),
        }
        for key, full_key, display_name in _ADMIN_PROMPT_KEYS
    }


@app.put("/api/admin/system-prompts")
def admin_update_system_prompts(body: dict, request: Request, db: Session = Depends(get_db)):
    """管理员批量更新系统默认提示词。"""
    _require_admin(request, db)
    valid_keys = {full_key for _, full_key, _ in _ADMIN_PROMPT_KEYS}
    updated = {}
    for key, value in body.items():
        if key in valid_keys and isinstance(value, str):
            set_system_prompt(key, value.strip(), db)
            updated[key] = value.strip()
    db.commit()
    return {
        "updated": list(updated.keys()),
        "prompts": {
            key: {
                "key": full_key,
                "name": display_name,
                "content": get_system_prompt(full_key, db),
            }
            for key, full_key, display_name in _ADMIN_PROMPT_KEYS
        },
    }


# ── 写作方法论管理 ──────────────────────────────────────

@app.get("/api/admin/methodology")
def admin_get_methodology(request: Request, db: Session = Depends(get_db)):
    """管理员查看全部四个写作方法论组件。"""
    _require_admin(request, db)
    from services.writing_utils import get_all_methodology_from_db
    methodology = get_all_methodology_from_db(db)
    return {
        key: {"content": methodology.get(key, ""), "length": len(methodology.get(key, ""))}
        for key in ["writing_craft", "anti_ai_writing", "quality_checklist", "banned_words"]
    }


@app.put("/api/admin/methodology")
def admin_update_methodology(body: dict, request: Request, db: Session = Depends(get_db)):
    """管理员更新单个写作方法论组件。"""
    _require_admin(request, db)
    from services.writing_utils import save_methodology_to_db
    key = body.get("key", "")
    content = body.get("content", "")
    if not isinstance(key, str) or key not in ("writing_craft", "anti_ai_writing", "quality_checklist", "banned_words"):
        raise HTTPException(400, f"无效的组件 key: {key}")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(400, "方法论内容不能为空")
    save_methodology_to_db(db, key, content.strip())
    return {"ok": True, "key": key, "length": len(content.strip())}


# ── 模板 CRUD ──────────────────────────────────────────

@app.post("/api/prompt-templates")
def create_prompt_template(body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    template = PromptTemplate(
        name=str(body.get("name", "")).strip()[:100],
        description=str(body.get("description", "")).strip(),
        author_user_id=user.id,
        category=str(body.get("category", "")).strip() or None,
        tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
        framework_prompt=str(body.get("framework_prompt", "")).strip() or None,
        chapter_prompt=str(body.get("chapter_prompt", "")).strip() or None,
        character_prompt=str(body.get("character_prompt", "")).strip() or None,
        manga_style_prompt=str(body.get("manga_style_prompt", "")).strip() or None,
        framework_params=body.get("framework_params"),
        chapter_params=body.get("chapter_params"),
        character_params=body.get("character_params"),
        manga_style_params=body.get("manga_style_params"),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _serialize_template(template, user.id, db)


@app.get("/api/prompt-templates/my")
def list_my_templates(request: Request, page: int = 1, page_size: int = 20, status: str = "", db: Session = Depends(get_db)):
    user = _require_user(request, db)

    query = db.query(PromptTemplate).filter(PromptTemplate.author_user_id == user.id)
    if status:
        query = query.filter(PromptTemplate.status == status)
    query = query.order_by(PromptTemplate.updated_at.desc())

    total = query.count()
    templates = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "templates": [_serialize_template(t, user.id, db) for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/prompt-templates/public")
def list_public_templates(
    request: Request,
    sort: str = "popular",
    category: str = "",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(PromptTemplate).filter(
        PromptTemplate.status == "approved",
        PromptTemplate.visibility.in_(["public", "official"]),
    )
    if category:
        query = query.filter(PromptTemplate.category == category)
    if sort == "official":
        query = query.filter(PromptTemplate.visibility == "official")
        query = query.order_by(PromptTemplate.usage_count.desc())
    elif sort == "latest":
        query = query.order_by(PromptTemplate.reviewed_at.desc().nullslast())
    else:
        query = query.order_by(PromptTemplate.usage_count.desc())

    total = query.count()
    templates = query.offset((page - 1) * page_size).limit(page_size).all()

    user = _get_current_user(request, db)
    return {
        "templates": [_serialize_template(t, user.id if user else None, db) for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/prompt-templates/{template_id}")
def get_prompt_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    user = _get_current_user(request, db)
    if template.visibility == "private":
        if not user or user.id != template.author_user_id:
            raise HTTPException(403, "无权访问此模板")

    return _serialize_template(template, user.id if user else None, db)


@app.put("/api/prompt-templates/{template_id}")
def update_prompt_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.author_user_id != user.id:
        raise HTTPException(403, "只能编辑自己的模板")

    str_fields = ["name", "description", "category", "framework_prompt", "chapter_prompt",
                  "character_prompt", "manga_style_prompt"]
    for key in str_fields:
        if key in body:
            val = body[key]
            setattr(template, key, str(val).strip() if val else None)

    list_fields = ["tags"]
    for key in list_fields:
        if key in body:
            val = body[key]
            setattr(template, key, val if isinstance(val, list) else None)

    param_fields = ["framework_params", "chapter_params", "character_params", "manga_style_params"]
    for key in param_fields:
        if key in body:
            val = body[key]
            setattr(template, key, val if isinstance(val, dict) else None)

    template.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(template)
    return _serialize_template(template, user.id, db)


@app.delete("/api/prompt-templates/{template_id}")
def delete_prompt_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.author_user_id != user.id:
        raise HTTPException(403, "只能删除自己的模板")

    try:
        db.query(PromptTemplate).filter(PromptTemplate.forked_from == template_id).update(
            {"forked_from": None}
        )
        db.query(StoryTemplateBinding).filter(StoryTemplateBinding.template_id == template_id).delete()
        db.query(TemplateLike).filter(TemplateLike.template_id == template_id).delete()
        db.delete(template)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("[delete_template:%s] 删除模板失败: %s", template_id, repr(exc))
        raise HTTPException(500, "删除模板失败，请稍后重试") from exc
    return {"ok": True}


@app.post("/api/prompt-templates/{template_id}/submit-for-review")
def submit_template_for_review(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.author_user_id != user.id:
        raise HTTPException(403, "只能提交自己的模板")
    if template.status not in ("draft", "rejected"):
        raise HTTPException(400, "当前状态不允许提交审核")

    template.status = "pending"
    template.submitted_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return _serialize_template(template, user.id, db)


@app.post("/api/prompt-templates/{template_id}/fork")
def fork_prompt_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    source = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not source:
        raise HTTPException(404, "模板不存在")
    if source.visibility == "private" and source.author_user_id != user.id:
        raise HTTPException(403, "无权复制此模板")

    new_template = PromptTemplate(
        name=f"{source.name}（副本）",
        description=source.description,
        author_user_id=user.id,
        category=source.category,
        tags=source.tags,
        framework_prompt=source.framework_prompt,
        chapter_prompt=source.chapter_prompt,
        character_prompt=source.character_prompt,
        manga_style_prompt=source.manga_style_prompt,
        framework_params=source.framework_params,
        chapter_params=source.chapter_params,
        character_params=source.character_params,
        manga_style_params=source.manga_style_params,
        forked_from=source.id,
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return _serialize_template(new_template, user.id, db)


# ── 作品模板绑定 ──────────────────────────────────────

@app.post("/api/stories/{story_id}/bind-template")
def bind_story_template(story_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "只能修改自己的作品")

    template_id = body.get("template_id")
    if not template_id:
        raise HTTPException(400, "请提供 template_id")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).delete()
    binding = StoryTemplateBinding(story_id=story_id, template_id=template_id)
    db.add(binding)
    template.usage_count = (template.usage_count or 0) + 1
    db.commit()
    db.refresh(binding)
    return {
        "story_id": story_id,
        "template_id": template_id,
        "bound_at": binding.bound_at.isoformat() if binding.bound_at else "",
    }


@app.get("/api/stories/{story_id}/template")
def get_story_template(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "权限不足")

    binding = db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).first()
    if not binding or not binding.template:
        return {"template": None}

    return {"template": _serialize_template(binding.template, user.id, db)}


@app.delete("/api/stories/{story_id}/template")
def unbind_story_template(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "只能修改自己的作品")

    db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).delete()
    db.commit()
    return {"ok": True}


@app.post("/api/prompt-templates/{template_id}/like")
def like_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    existing = db.query(TemplateLike).filter(
        TemplateLike.template_id == template_id,
        TemplateLike.user_id == user.id,
    ).first()

    if not existing:
        db.add(TemplateLike(template_id=template_id, user_id=user.id))
        template.like_count = (template.like_count or 0) + 1
        db.commit()

    return {"like_count": template.like_count, "is_liked": True}


@app.delete("/api/prompt-templates/{template_id}/like")
def unlike_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    existing = db.query(TemplateLike).filter(
        TemplateLike.template_id == template_id,
        TemplateLike.user_id == user.id,
    ).first()
    if existing:
        db.delete(existing)
        template.like_count = max(0, (template.like_count or 0) - 1)
        db.commit()

    return {"like_count": template.like_count, "is_liked": False}


# ── 管理员审核 ─────────────────────────────────────────

@app.get("/api/admin/prompt-templates/pending")
def admin_list_pending_templates(request: Request, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    _require_admin(request, db)

    query = db.query(PromptTemplate).filter(PromptTemplate.status == "pending")
    query = query.order_by(PromptTemplate.submitted_at.asc().nullslast())
    total = query.count()
    templates = query.offset((page - 1) * page_size).limit(page_size).all()

    user = _get_current_user(request, db)
    return {
        "templates": [_serialize_template(t, user.id if user else None, db) for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/api/admin/prompt-templates/{template_id}/approve")
def admin_approve_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.status != "pending":
        raise HTTPException(400, "只能审核待审核状态的模板")

    user = _get_current_user(request, db)
    template.status = "approved"
    template.visibility = body.get("visibility", "public")
    template.is_public = True
    template.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    template.reviewed_by = user.id if user else None
    template.review_note = body.get("note", "")
    db.commit()
    return _serialize_template(template, user.id if user else None, db)


@app.post("/api/admin/prompt-templates/{template_id}/reject")
def admin_reject_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    user = _get_current_user(request, db)
    template.status = "rejected"
    template.is_public = False
    template.visibility = "private"
    template.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    template.reviewed_by = user.id if user else None
    template.review_note = body.get("note", "")
    db.commit()
    return _serialize_template(template, user.id if user else None, db)


@app.post("/api/admin/prompt-templates/{template_id}/archive")
def admin_archive_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    template.visibility = "archived"
    template.is_public = False
    template.review_note = body.get("reason", "管理员下架")
    db.commit()
    return {"ok": True, "id": template_id, "visibility": "archived"}


# ── Agent 路由器 ─────────────────────────────────────
# 注意：import 放在文件末尾，确保辅助函数已全部定义，
# 这样 agent_router.py 可以通过 sys.modules 访问 _require_user 等函数
from routers.agent_router import router as agent_router
from routers.points_ai import router as points_ai_router
from routers.creation_studio import router as creation_studio_router

app.include_router(video_router)
app.include_router(agent_router)
app.include_router(deconstruction_router)
app.include_router(deconstruct_library_router)
app.include_router(points_ai_router)
app.include_router(creation_studio_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=_default_reload_enabled(),
        reload_excludes=[
            "*.log",
            "*.err",
            "*.pyc",
            ".env",
            "__pycache__",
            "__pycache__/*",
            "manga_outputs/*",
            "backend.log",
            "backend.err",
        ],
    )
