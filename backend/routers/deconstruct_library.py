"""
独立拆书库 API 路由：搜书 → 爬取 → 拆书 → 结果查阅 → 引用到作品
所有端点不再依赖 story_id，拆书数据完全独立。
"""

import datetime
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import (
    BackgroundTask, DeconstructionWork, DeconstructionChapter,
    StoryDeconstructionRef, Story,
)
from services.novel_crawler import search_novels, crawl_novel_raw
from services.deconstruction import run_deconstruction_pipeline
from services.deconstruction_v2 import run_deconstruction_pipeline_v2
from services.task_manager import task_manager

router = APIRouter(tags=["deconstruction-library"])

REMOTE_CRAWL_SUPPORTED_PLATFORMS = {"qidian"}
TEXT_FILE_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "gbk",
    "gb2312",
    "big5",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
)
PLATFORM_LABELS = {
    "qidian": "起点",
    "fanqie": "番茄小说",
    "qimao": "七猫",
    "zongheng": "纵横",
}


def is_remote_crawl_supported(platform: str) -> bool:
    return platform in REMOTE_CRAWL_SUPPORTED_PLATFORMS


def get_upload_required_message(platform: str) -> str:
    label = PLATFORM_LABELS.get(platform) or "该平台"
    return f"{label}暂不支持稳定自动爬取正文，请上传原文文件或粘贴原文后再拆书。"


def decode_uploaded_text_file(raw_bytes: bytes) -> str:
    if not raw_bytes:
        raise HTTPException(400, "上传的 txt 文件为空")

    for encoding in TEXT_FILE_ENCODINGS:
        try:
            text = raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

        normalized = text.replace("\ufeff", "").strip()
        if normalized:
            return normalized

    raise HTTPException(
        400,
        "文件编码无法自动识别，请尽量保存为 UTF-8、GB18030、GBK 或 UTF-16 编码后重试",
    )


def split_imported_novel_text(text: str) -> list[dict[str, str | int]]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chapter_pattern = re.compile(r"(?m)^\s*#{0,6}\s*(第[0-9一二三四五六七八九十百千万两]+[章节回卷集](?:[ 　\t].*)?)\s*$")
    matches = list(chapter_pattern.finditer(normalized))
    if not matches:
        return [{"chapter_number": 1, "title": "第1章", "content": normalized}]

    chapters: list[dict[str, str | int]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = normalized[start:end].strip()
        if not content:
            continue
        chapters.append({
            "chapter_number": len(chapters) + 1,
            "title": match.group(1).strip(),
            "content": content,
        })
    return chapters


def _require_user(request: Request, db: Session):
    from main import _require_user as _ru
    return _ru(request, db)


def _require_story_for_user(story_id: int, user, db: Session):
    from main import _require_story_for_user as _rsfu
    return _rsfu(story_id, user, db)


# ── 1. 搜书 ─────────────────────────────────────────

@router.get("/api/deconstruct/search")
async def search_novels_endpoint(
    keyword: str = Query(..., min_length=1),
    platform: str = Query("all"),
    limit: int = Query(10, ge=1, le=20),
):
    results = await search_novels(keyword, platform, limit)
    return {"results": results, "total": len(results)}


# ── 2. 拆书库列表 ───────────────────────────────────

@router.get("/api/deconstruct/works")
async def list_deconstruction_works(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    works = db.query(DeconstructionWork).filter(
        DeconstructionWork.owner_user_id == user.id,
    ).order_by(DeconstructionWork.updated_at.desc()).all()

    return [
        {
            "id": w.id,
            "title": w.title,
            "author": w.author,
            "platform": w.platform,
            "genre": w.genre,
            "status_label": w.status_label,
            "crawl_status": w.crawl_status,
            "decon_status": w.decon_status,
            "total_chapters": w.total_chapters,
            "crawled_chapters": w.crawled_chapters,
            "word_count": w.word_count,
            "task_id": w.task_id,
            "created_at": str(w.created_at) if w.created_at else None,
            "updated_at": str(w.updated_at) if w.updated_at else None,
        }
        for w in works
    ]


# ── 3. 创建拆书工作 + 爬取 ───────────────────────────

@router.post("/api/deconstruct/works")
async def create_and_crawl_work(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    body = await request.json()

    title = body.get("title", "").strip()
    platform = body.get("platform", "qidian")
    book_id = body.get("book_id")
    max_chapters = body.get("max_chapters", 100)

    if not title or not book_id:
        raise HTTPException(400, "缺少 title 或 book_id 参数")

    if not is_remote_crawl_supported(platform):
        raise HTTPException(400, get_upload_required_message(platform))

    if platform == "fanqie":
        source_url = f"https://fanqienovel.com/page/{book_id}"
    elif platform == "qimao":
        source_url = f"https://www.qimao.com/shuku/{book_id}/"
    elif platform == "zongheng":
        source_url = f"http://book.zongheng.com/book/{book_id}.html"
    else:
        source_url = f"https://m.qidian.com/book/{book_id}/"

    work = DeconstructionWork(
        owner_user_id=user.id,
        title=title,
        author=body.get("author"),
        platform=platform,
        source_url=source_url,
        source_book_id=str(book_id),
        genre=body.get("genre"),
        status_label=body.get("status_label"),
        crawl_status="crawling",
    )
    db.add(work)
    db.commit()
    db.refresh(work)

    task_id_str = f"deconlib_{work.id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

    await task_manager.submit_task(
        task_id_str,
        "deconlib_crawl",
        _crawl_to_deconstruction_work,
        book_id,
        work_id=work.id,
        max_chapters=max_chapters,
        timeout=3600,
        max_retries=0,
    )

    return {
        "work_id": work.id,
        "task_id": task_id_str,
        "message": f"开始爬取《{title}》(最多 {max_chapters} 章)",
    }


@router.post("/api/deconstruct/works/import-text")
async def import_text_work(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    body = await request.json()

    title = (body.get("title") or "").strip()
    raw_text = body.get("text") or ""
    author = body.get("author")
    platform = body.get("platform") or "manual"
    chapters = split_imported_novel_text(raw_text)

    if not title:
        raise HTTPException(400, "缺少 title 参数")
    if len(chapters) < 3:
        raise HTTPException(400, f"至少需要 3 章原文才能拆书（当前识别 {len(chapters)} 章）")

    work = _create_work_from_chapters(db, user.id, title, author, platform, body.get("genre"), chapters)
    return {
        "work_id": work.id,
        "message": f"已导入《{title}》{len(chapters)} 章原文，可开始拆书",
    }


@router.post("/api/deconstruct/works/import-file")
async def import_file_work(
    file: UploadFile = File(...),
    title: str = Form(""),
    author: str = Form(""),
    genre: str = Form(""),
    request: Request = None,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)

    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(400, "仅支持 .txt 文件")

    raw_bytes = await file.read()
    raw_text = decode_uploaded_text_file(raw_bytes)

    if not title.strip():
        title = re.sub(r"\.[^.]+$", "", file.filename)

    chapters = split_imported_novel_text(raw_text)
    if len(chapters) < 3:
        raise HTTPException(400, f"至少需要 3 章原文才能拆书（当前识别 {len(chapters)} 章）")

    work = _create_work_from_chapters(db, user.id, title.strip(), author or None, "manual", genre or None, chapters)

    # 自动触发后台拆书管线
    try:
        from main import _check_and_consume_feature_quota, _refund_quota, _user_deepseek_api_key
        deepseek_api_key = _user_deepseek_api_key(request)

        task_id_str = f"deconlib_{work.id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"
        quota_result = _check_and_consume_feature_quota(
            request,
            user.id,
            "deconstruction.run.monthly_limit",
            1,
            db,
            deduct=True,
            provider_kind="text",
        )
        quota_period_key = quota_result.get("period_key")
        quota_amount = 0 if quota_result.get("skipped") else 1
        work.decon_status = "running"
        work.current_stage = 0
        work.task_id = task_id_str
        db.commit()

        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="deconlib_deconstruct",
            coro_func=_run_deconstruction_for_work,
            work_id=work.id,
            api_key=deepseek_api_key,
            timeout=7200,
            max_retries=0,
            quota_user_id=user.id,
            quota_feature_key="deconstruction.run.monthly_limit",
            quota_amount=quota_amount,
            quota_period_key=quota_period_key,
        )
        return {
            "work_id": work.id,
            "task_id": task_id_str,
            "message": f"已导入《{title.strip()}》{len(chapters)} 章原文，后台拆书已启动",
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        if "quota_amount" in locals() and quota_amount > 0:
            _refund_quota(user.id, "deconstruction.run.monthly_limit", quota_amount, db, locals().get("quota_period_key"))
        work.decon_status = "not_started"
        work.current_stage = None
        work.task_id = None
        db.commit()
        raise HTTPException(500, f"拆书启动失败: {e}")


def _create_work_from_chapters(
    db: Session,
    user_id: int,
    title: str,
    author: str | None,
    platform: str,
    genre: str | None,
    chapters: list[dict],
) -> DeconstructionWork:
    word_count = sum(len(str(ch["content"]).replace("\n", "").replace(" ", "")) for ch in chapters)
    work = DeconstructionWork(
        owner_user_id=user_id,
        title=title,
        author=author,
        platform=platform,
        source_url="manual_upload",
        source_book_id=None,
        genre=genre,
        status_label="手动导入",
        crawl_status="completed",
        decon_status="not_started",
        total_chapters=len(chapters),
        crawled_chapters=len(chapters),
        word_count=word_count,
    )
    db.add(work)
    db.commit()
    db.refresh(work)

    for ch in chapters:
        content = str(ch["content"])
        db.add(DeconstructionChapter(
            work_id=work.id,
            chapter_number=int(ch["chapter_number"]),
            title=str(ch["title"]),
            content=content,
            word_count=len(content.replace("\n", "").replace(" ", "")),
            source_url="manual_upload",
        ))
    db.commit()

    return work


async def _crawl_to_deconstruction_work(book_id: str, work_id: int, max_chapters: int, task_id: str | None = None, **kwargs):
    """爬取章节到 DeconstructionChapter 表（使用平台分发器）"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        work = db.query(DeconstructionWork).filter(DeconstructionWork.id == work_id).first()
        if not work:
            return

        platform = work.platform or "qidian"
        chapters_data = await crawl_novel_raw(platform, book_id, max_chapters=max_chapters, task_id=task_id)

        # 将爬取结果写入 DeconstructionChapter
        for ch_data in chapters_data:
            ch = DeconstructionChapter(
                work_id=work_id,
                chapter_number=ch_data.get("chapter_number", 0),
                title=ch_data.get("title"),
                content=ch_data.get("content"),
                word_count=ch_data.get("word_count", 0),
                source_url=ch_data.get("source_url"),
            )
            db.add(ch)

        work.crawl_status = "completed"
        work.crawled_chapters = len(chapters_data)
        work.total_chapters = len(chapters_data)
        total_words = sum(ch.get("word_count", 0) for ch in chapters_data)
        work.word_count = total_words
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"爬取失败 work_id={work_id}: {e}")
        if work:
            work.crawl_status = "failed"
            db.commit()
        raise
    finally:
        db.close()


# ── 4. 爬取状态 ─────────────────────────────────────

@router.get("/api/deconstruct/works/{work_id}/crawl/status")
async def get_crawl_status(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    chapter_count = db.query(DeconstructionChapter).filter(
        DeconstructionChapter.work_id == work_id,
    ).count()

    return {
        "status": work.crawl_status,
        "total_chapters": work.total_chapters,
        "crawled_chapters": work.crawled_chapters or chapter_count,
        "word_count": work.word_count,
        "source_url": work.source_url,
    }


# ── 5. 启动拆书 ─────────────────────────────────────

@router.post("/api/deconstruct/works/{work_id}/resume")
async def resume_deconstruction_work(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """续跑拆书分析。mode: "full" = 全量续跑, "partial" = 试读模式"""
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    body = await request.json()
    mode = body.get("mode", "full")

    if mode == "partial":
        valid = ["paused_after_stage1"]
    elif mode == "quick_report":
        valid = ["paused_after_stage1"]
    else:
        valid = ["paused_after_stage1"]

    if work.decon_status not in valid:
        raise HTTPException(400, "当前状态不支持续跑（需要已完成黄金三章拆解并停靠）")

    work.decon_status = "running"
    db.commit()

    from main import _user_deepseek_api_key
    api_key = _user_deepseek_api_key(request)

    task_id_str = f"decon_work_{work_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

    if mode == "quick_report":
        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="deconstruction",
            coro_func=_run_deconstruction_for_work,
            work_id=work_id,
            api_key=api_key,
            start_stage=5,
            pause_after_stage1=False,
            quick_report_mode=True,
            timeout=600,
            max_retries=0,
        )
        return {
            "task_id": task_id_str,
            "message": "快速报告生成已启动（基于黄金三章数据）",
        }

    is_partial = mode == "partial"
    await task_manager.submit_task(
        task_id=task_id_str,
        task_type="deconstruction",
        coro_func=_run_deconstruction_for_work,
        work_id=work_id,
        api_key=api_key,
        start_stage=2,
        pause_after_stage1=False,
        partial_mode=is_partial,
        timeout=7200,
        max_retries=0,
    )

    msg = "试读模式已启动（Stage 2'-5'）" if is_partial else "拆书续跑任务已启动（Stage 2-6）"
    return {
        "task_id": task_id_str,
        "message": msg,
    }


@router.post("/api/deconstruct/works/{work_id}/start")
async def start_deconstruction(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    if work.decon_status in ("pending", "running"):
        raise HTTPException(400, "已有进行中的拆书任务")

    body = await request.json()
    max_chapters = body.get("max_chapters")

    chapter_count = db.query(DeconstructionChapter).filter(
        DeconstructionChapter.work_id == work_id,
        DeconstructionChapter.content.isnot(None),
        DeconstructionChapter.content != "",
    ).count()

    if chapter_count < 3:
        raise HTTPException(400, f"至少需要 3 章有内容的章节才能拆书（当前 {chapter_count} 章）")

    # 清理旧失败 BackgroundTask
    db.query(BackgroundTask).filter(
        BackgroundTask.task_id.like(f"deconlib_{work_id}_%"),
        BackgroundTask.status == "failed",
    ).delete()
    db.commit()

    from main import _check_and_consume_feature_quota, _refund_quota, _user_deepseek_api_key
    api_key = _user_deepseek_api_key(request)

    task_id_str = f"deconlib_{work_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

    quota_result = _check_and_consume_feature_quota(
        request,
        user.id,
        "deconstruction.run.monthly_limit",
        1,
        db,
        deduct=True,
        provider_kind="text",
    )
    quota_period_key = quota_result.get("period_key")
    quota_amount = 0 if quota_result.get("skipped") else 1

    try:
        work.decon_status = "running"
        work.current_stage = 0
        work.task_id = task_id_str
        if max_chapters:
            work.decon_range = max_chapters
        db.commit()

        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="deconlib_deconstruct",
            coro_func=_run_deconstruction_for_work,
            work_id=work_id,
            api_key=api_key,
            timeout=7200,
            max_retries=0,
            quota_user_id=user.id,
            quota_feature_key="deconstruction.run.monthly_limit",
            quota_amount=quota_amount,
            quota_period_key=quota_period_key,
            max_chapters_for_partial=max_chapters,
            pause_after_stage1=True,
        )
    except Exception:
        db.rollback()
        if quota_amount > 0:
            _refund_quota(user.id, "deconstruction.run.monthly_limit", quota_amount, db, quota_period_key)
        work.decon_status = "not_started"
        work.current_stage = None
        work.task_id = None
        db.commit()
        raise

    return {
        "task_id": task_id_str,
        "message": "拆书任务已启动",
    }


async def _run_deconstruction_for_work(work_id: int, api_key: str, task_id: str | None = None, **kwargs):
    """为 DeconstructionWork 运行拆书管道"""
    max_chapters_for_partial = kwargs.get("max_chapters_for_partial")
    partial_mode = kwargs.get("partial_mode", False)
    quick_report_mode = kwargs.get("quick_report_mode", False)
    from database import SessionLocal
    from services.deconstruction import (
        _configure_deepseek_from_db,
        _get_api_key_from_db,
        _call_deepseek_json,
        _call_deepseek_text,
        _count_words,
        _truncate_title_list,
        FatalModelProviderError,
        _run_stage3_aggregation,
        _truncate_json_for_context,
        STAGE2_CHAPTER_CONCURRENCY,
        should_flush_stage2_progress,
    )
    import json, logging, asyncio
    from prompts.deconstruction import (
        STAGE_0_SUMMARY_SYSTEM, STAGE_0_SUMMARY_USER,
        STAGE_0_5_FRAMEWORK_SYSTEM, STAGE_0_5_FRAMEWORK_USER,
        STAGE_1_GOLDEN_CHAPTERS_SYSTEM, STAGE_1_GOLDEN_CHAPTERS_USER,
        STAGE_2_CHAPTER_SUMMARY_SYSTEM, STAGE_2_CHAPTER_SUMMARY_USER,
        STAGE_4_SETTINGS_SYSTEM, STAGE_4_SETTINGS_USER,
        STAGE_5_REPORT_SYSTEM, STAGE_5_REPORT_USER,
        STAGE_6_STYLE_SYSTEM, STAGE_6_STYLE_USER,
    )

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        _configure_deepseek_from_db(db)
        if not api_key:
            api_key = _get_api_key_from_db(db)

        work = db.query(DeconstructionWork).filter(DeconstructionWork.id == work_id).first()
        if not work:
            raise ValueError(f"拆书工作 {work_id} 不存在")

        chapters = db.query(DeconstructionChapter).filter(
            DeconstructionChapter.work_id == work_id,
            DeconstructionChapter.content.isnot(None),
            DeconstructionChapter.content != "",
        ).order_by(DeconstructionChapter.chapter_number).all()

        if len(chapters) < 3:
            raise ValueError("至少需要 3 章有内容的章节才能拆书")

        if max_chapters_for_partial and max_chapters_for_partial < len(chapters):
            chapters = chapters[:max_chapters_for_partial]

        if quick_report_mode and work.current_stage <= 5:
            _update_work_progress(work, db, "quick_report: 基于黄金三章数据生成报告...")
            summary = work.summary or {}
            response = await _call_deepseek_text(
                STAGE_5_REPORT_SYSTEM,
                STAGE_5_REPORT_USER.format(
                    title=summary.get("title", "未知"),
                    genre=summary.get("genre", "未知"),
                    total_chapters=summary.get("estimated_total_chapters", 0),
                    total_words=summary.get("estimated_total_words", 0),
                    golden_chapters=_truncate_json_for_context(work.golden_chapters, 8000),
                    chapter_summaries=_truncate_json_for_context(None, 1000),
                    characters=_truncate_json_for_context(None, 1000),
                    character_relations=_truncate_json_for_context(None, 1000),
                    plot_lines=_truncate_json_for_context(None, 1000),
                    rhythm=_truncate_json_for_context(None, 1000),
                    emotion_modules=_truncate_json_for_context(None, 1000),
                    worldbuilding=_truncate_json_for_context(None, 1000),
                ),
                api_key,
            )
            work.report_markdown = response
            work.decon_status = "paused_after_stage1"
            db.commit()
            _update_work_progress(work, db, "quick_report: 报告已生成")
            return {"status": "paused_after_stage1", "work_id": work.id}

        # Stage 0: 概要提取
        if work.current_stage <= 0:
            _update_work_progress(work, db, "Stage 0: 概要提取中...")
            sample_text = ""
            for ch in chapters[:5]:
                sample_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.content or '')[:2000]}"
            title_lines = [f"第{ch.chapter_number}章 {ch.title or ''} ({ch.word_count}字)" for ch in chapters]
            all_titles = _truncate_title_list(title_lines)
            response = await _call_deepseek_json(
                STAGE_0_SUMMARY_SYSTEM,
                STAGE_0_SUMMARY_USER.format(chapter_text=f"章节列表：\n{all_titles}\n\n样本内容：\n{sample_text}"),
                api_key,
            )
            work.summary = response
            work.current_stage = 1
            db.commit()

        # Stage 0.5: 故事框架识别
        if work.current_stage <= 1:
            _update_work_progress(work, db, "Stage 0.5: 故事框架识别中...")
            summary = work.summary or {}
            thin = summary.get("thin_summary", "")
            title_lines = [f"第{ch.chapter_number}章 {ch.title or ''}" for ch in chapters]
            titles_text = _truncate_title_list(title_lines)
            try:
                fw_response = await _call_deepseek_json(
                    STAGE_0_5_FRAMEWORK_SYSTEM,
                    STAGE_0_5_FRAMEWORK_USER.format(thin_summary=thin, chapter_titles=titles_text),
                    api_key,
                )
                work.framework_type = fw_response.get("framework_type", "")
                _update_work_progress(work, db, f"Stage 0.5: 框架识别完成 - {fw_response.get('framework_type', '未知')}")
            except Exception as e:
                logger.warning(f"框架识别失败（非致命）: {e}")
                _update_work_progress(work, db, f"Stage 0.5: 框架识别失败 - {e}")
            work.current_stage = 1
            db.commit()

        # Stage 1: 黄金三章
        if work.current_stage <= 1:
            _update_work_progress(work, db, "Stage 1: 黄金三章深度拆解中...")
            golden_text = ""
            for ch in chapters[:3]:
                golden_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.content or '')}"
            response = await _call_deepseek_json(
                STAGE_1_GOLDEN_CHAPTERS_SYSTEM,
                STAGE_1_GOLDEN_CHAPTERS_USER.format(chapter_text=golden_text),
                api_key,
            )
            work.golden_chapters = response
            work.current_stage = 2
            work.stages_completed = [0, 0.5, 1] if isinstance(work.stages_completed, list) else [0, 0.5, 1]
            db.commit()

            # Stage 1 停靠点
            if kwargs.get("pause_after_stage1", True):
                preview = f"# 快速预览：{work.title}\n\n## 框架识别\n- 故事框架类型：{work.framework_type or '未识别'}\n\n## 黄金三章拆解完成\n可选「继续全量拆解」或「试读前 N 章」。"
                work.progress_markdown = (work.progress_markdown or "") + "\n\n" + preview
                if max_chapters_for_partial:
                    work.decon_status = f"paused_after_partial:{max_chapters_for_partial}"
                    work.decon_range = max_chapters_for_partial
                    db.commit()
                    return {"status": f"paused_after_partial:{max_chapters_for_partial}", "work_id": work.id}
                work.decon_status = "paused_after_stage1"
                db.commit()
                return {"status": "paused_after_stage1", "work_id": work.id}

        # Stage 2: 逐章摘要（并发）
        if work.current_stage <= 2:
            semaphore = asyncio.Semaphore(STAGE2_CHAPTER_CONCURRENCY)
            db_lock = asyncio.Lock()
            completed = [0]
            total = len(chapters)
            fatal_error_seen = asyncio.Event()

            async def _summarize_one(ch, index: int):
                async with semaphore:
                    if fatal_error_seen.is_set():
                        raise FatalModelProviderError("文本模型上游已返回致命错误，已停止继续提交逐章摘要请求。任务失败后，本次拆书次数会自动返还。")
                    try:
                        response = await _call_deepseek_json(
                            STAGE_2_CHAPTER_SUMMARY_SYSTEM,
                            STAGE_2_CHAPTER_SUMMARY_USER.format(
                                chapter_number=ch.chapter_number,
                                chapter_title=ch.title or "",
                                word_count=ch.word_count,
                                chapter_text=ch.content or "",
                            ),
                            api_key,
                        )
                        async with db_lock:
                            completed[0] += 1
                            if should_flush_stage2_progress(completed[0], total):
                                _update_work_progress(work, db, f"Stage 2: 逐章摘要 ({completed[0]}/{total})...")
                        return (index, response)
                    except FatalModelProviderError:
                        fatal_error_seen.set()
                        raise
                    except Exception as e:
                        logger.error(f"第{ch.chapter_number}章摘要失败: {e}")
                        async with db_lock:
                            completed[0] += 1
                            if should_flush_stage2_progress(completed[0], total):
                                _update_work_progress(work, db, f"Stage 2: 逐章摘要 ({completed[0]}/{total}) - 第{ch.chapter_number}章失败")
                        return (index, {"chapter_number": ch.chapter_number, "error": str(e)})

            results = await asyncio.gather(*[_summarize_one(ch, i) for i, ch in enumerate(chapters)])
            results.sort(key=lambda x: x[0])
            work.chapter_summaries = [r[1] for r in results]
            work.current_stage = 3
            db.commit()

        if partial_mode:
            decon_range = work.decon_range or len(chapters)
            summaries_text = _truncate_json_for_context(work.chapter_summaries, 20000)

            _update_work_progress(work, db, "Stage 3': 轻量聚合中（试读模式）...")
            stage3_partial = await _run_stage3_aggregation(
                work.chapter_summaries, api_key,
                lambda message: _update_work_progress(work, db, message),
            )
            work.plot_lines = stage3_partial.get("plot_lines")
            work.rhythm = stage3_partial.get("rhythm")
            work.emotion_modules = stage3_partial.get("emotion_modules")
            merged = stage3_partial.get("merged_characters", {})
            work.progress_markdown = (work.progress_markdown or "") + "\n## STAGE3_MERGED\n" + json.dumps(merged, ensure_ascii=False)

            _update_work_progress(work, db, "Stage 4': 设定+关系提取中（试读模式）...")
            try:
                stage4_partial = await _call_deepseek_json(
                    STAGE_4_SETTINGS_SYSTEM,
                    STAGE_4_SETTINGS_USER.format(chapter_summaries=summaries_text, merged_characters=json.dumps(merged, ensure_ascii=False)),
                    api_key,
                )
                work.worldbuilding = stage4_partial.get("worldbuilding")
                work.characters = stage4_partial.get("character_profiles")
                work.character_relations = stage4_partial.get("character_relations")
            except Exception as e:
                logger.warning(f"Stage 4' 设定提取失败（非致命）: {e}")

            _update_work_progress(work, db, "Stage 5': 试读报告生成中...")
            summary = work.summary or {}
            response = await _call_deepseek_text(
                STAGE_5_REPORT_SYSTEM,
                STAGE_5_REPORT_USER.format(
                    title=f"{summary.get('title', '未知')}（前{decon_range}章）",
                    genre=summary.get("genre", "未知"),
                    total_chapters=decon_range,
                    total_words=summary.get("estimated_total_words", 0),
                    golden_chapters=_truncate_json_for_context(work.golden_chapters, 8000),
                    chapter_summaries=_truncate_json_for_context(work.chapter_summaries, 15000),
                    characters=_truncate_json_for_context(work.characters, 8000),
                    character_relations=_truncate_json_for_context(work.character_relations, 5000),
                    plot_lines=_truncate_json_for_context(work.plot_lines, 5000),
                    rhythm=_truncate_json_for_context(work.rhythm, 3000),
                    emotion_modules=_truncate_json_for_context(work.emotion_modules, 3000),
                    worldbuilding=_truncate_json_for_context(work.worldbuilding, 5000),
                ),
                api_key,
            )
            work.report_markdown = response
            work.decon_status = f"paused_after_partial:{decon_range}"
            work.current_stage = 5
            work.stages_completed = [0, 0.5, 1, 2, 3, 4, 5]
            db.commit()
            _update_work_progress(work, db, f"试读模式完成：前 {decon_range} 章分析完毕")
            return {"status": f"paused_after_partial:{decon_range}", "work_id": work.id}

        # Stage 3-6 与原管道相同，保存到 work 而非 result
        # Stage 3: 聚合分析
        if work.current_stage <= 3:
            _update_work_progress(work, db, "Stage 3: 聚合分析中...")
            response = await _run_stage3_aggregation(
                work.chapter_summaries,
                api_key,
                lambda message: _update_work_progress(work, db, message),
            )
            work.plot_lines = response.get("plot_lines")
            work.rhythm = response.get("rhythm")
            work.emotion_modules = response.get("emotion_modules")
            merged = response.get("merged_characters", {})
            work.progress_markdown = (work.progress_markdown or "") + "\n## STAGE3_MERGED\n" + json.dumps(merged, ensure_ascii=False)
            work.current_stage = 4
            db.commit()

        # Stage 4: 设定+关系
        if work.current_stage <= 4:
            _update_work_progress(work, db, "Stage 4: 设定+关系提取中...")
            summaries_text = _truncate_json_for_context(work.chapter_summaries, 15000)
            merged = "{}"
            if work.progress_markdown and "## STAGE3_MERGED" in work.progress_markdown:
                merged = work.progress_markdown.split("## STAGE3_MERGED\n", 1)[1].split("\n## ")[0]
            response = await _call_deepseek_json(
                STAGE_4_SETTINGS_SYSTEM,
                STAGE_4_SETTINGS_USER.format(chapter_summaries=summaries_text, merged_characters=merged),
                api_key,
            )
            work.worldbuilding = response.get("worldbuilding")
            work.characters = response.get("character_profiles")
            work.character_relations = response.get("character_relations")
            work.current_stage = 5
            db.commit()

        # Stage 5: 汇总报告
        if work.current_stage <= 5:
            _update_work_progress(work, db, "Stage 5: 汇总报告中...")
            summary = work.summary or {}
            response = await _call_deepseek_text(
                STAGE_5_REPORT_SYSTEM,
                STAGE_5_REPORT_USER.format(
                    title=summary.get("title", "未知"),
                    genre=summary.get("genre", "未知"),
                    total_chapters=summary.get("estimated_total_chapters", 0),
                    total_words=summary.get("estimated_total_words", 0),
                    golden_chapters=_truncate_json_for_context(work.golden_chapters, 8000),
                    chapter_summaries=_truncate_json_for_context(work.chapter_summaries, 15000),
                    characters=_truncate_json_for_context(work.characters, 8000),
                    character_relations=_truncate_json_for_context(work.character_relations, 5000),
                    plot_lines=_truncate_json_for_context(work.plot_lines, 5000),
                    rhythm=_truncate_json_for_context(work.rhythm, 3000),
                    emotion_modules=_truncate_json_for_context(work.emotion_modules, 3000),
                    worldbuilding=_truncate_json_for_context(work.worldbuilding, 5000),
                ),
                api_key,
            )
            work.report_markdown = response
            work.current_stage = 6
            db.commit()

        # Stage 6: 文风分析
        if work.current_stage <= 6:
            _update_work_progress(work, db, "Stage 6: 文风分析中...")
            samples = []
            for i, ch in enumerate(chapters):
                if i < 3 or i % 10 == 0:
                    samples.append(f"## 第{ch.chapter_number}章\n\n{(ch.content or '')[:3000]}")
            golden_text = json.dumps(work.golden_chapters, ensure_ascii=False, indent=2)[:5000]
            summaries_text = json.dumps(work.chapter_summaries, ensure_ascii=False, indent=2)[:5000]
            response = await _call_deepseek_json(
                STAGE_6_STYLE_SYSTEM,
                STAGE_6_STYLE_USER.format(
                    chapter_summaries=summaries_text,
                    golden_chapters_text=golden_text,
                    original_text_samples="\n\n".join(samples),
                ),
                api_key,
            )
            work.writing_style = response
            work.writing_techniques = response.get("techniques", [])
            work.current_stage = 7
            db.commit()

        work.decon_status = "completed"
        work.stages_completed = [0, 1, 2, 3, 4, 5, 6]
        db.commit()

    except Exception as e:
        logger.error(f"拆书管道 work_id={work_id} Stage {work.current_stage if work else '?'} 失败: {e}")
        work.decon_status = "failed"
        work.progress_markdown = (work.progress_markdown or "") + f"\n\n## Stage {work.current_stage} 失败\n{str(e)}"
        db.commit()
        raise
    finally:
        db.close()


def _update_work_progress(work: DeconstructionWork, db: Session, message: str):
    work.progress_markdown = (work.progress_markdown or "") + f"\n- {message}"
    db.commit()


# ── 6. 拆书状态 ─────────────────────────────────────

@router.get("/api/deconstruct/works/{work_id}/status")
async def get_deconstruction_status(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    return {
        "status": work.decon_status,
        "current_stage": work.current_stage,
        "stages_completed": work.stages_completed or [],
        "progress": work.progress_markdown,
        "work_id": work.id,
    }


# ── 7. 拆书结果 ─────────────────────────────────────

@router.get("/api/deconstruct/works/{work_id}/result")
async def get_deconstruction_result(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")
    # 允许 completed 和 paused_after_partial:* 两种状态返回结果
    if work.decon_status != "completed" and not (work.decon_status or "").startswith("paused_after_partial"):
        raise HTTPException(400, "拆书尚未完成")

    return {
        "id": work.id,
        "title": work.title,
        "author": work.author,
        "status": work.decon_status,
        "summary": work.summary,
        "golden_chapters": work.golden_chapters,
        "chapter_summaries": work.chapter_summaries,
        "characters": work.characters,
        "character_relations": work.character_relations,
        "plot_lines": work.plot_lines,
        "rhythm": work.rhythm,
        "emotion_modules": work.emotion_modules,
        "worldbuilding": work.worldbuilding,
        "report_markdown": work.report_markdown,
        "writing_style": work.writing_style,
        "writing_techniques": work.writing_techniques,
        "created_at": str(work.created_at) if work.created_at else None,
        "updated_at": str(work.updated_at) if work.updated_at else None,
    }


# ── 8. 取消拆书 ─────────────────────────────────────

@router.post("/api/deconstruct/works/{work_id}/cancel")
async def cancel_deconstruction(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    if work.decon_status not in ("pending", "running"):
        raise HTTPException(400, "没有进行中的拆书任务")

    if work.task_id:
        task_manager.request_cancellation(work.task_id)

    work.decon_status = "failed"
    work.progress_markdown = (work.progress_markdown or "") + "\n- 用户取消"
    db.commit()

    return {"message": "已取消拆书任务"}


# ── 9. 删除拆书工作 ─────────────────────────────────

@router.delete("/api/deconstruct/works/{work_id}")
async def delete_deconstruction_work(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    if work.decon_status in ("pending", "running"):
        if work.task_id:
            task_manager.request_cancellation(work.task_id)
            task_manager.cancel_task(work.task_id)

    db.delete(work)
    db.commit()

    return {"message": "已删除"}


# ── 10. 引用拆书结果到作品 ───────────────────────────

@router.post("/api/stories/{story_id}/deconstruct/refs")
async def add_deconstruction_ref(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """将拆书结果引用到作品，创作时 Agent 可参考"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    work_id = body.get("work_id")

    if not work_id:
        raise HTTPException(400, "缺少 work_id 参数")

    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")
    if work.decon_status != "completed" and not (work.decon_status or "").startswith("paused_after_partial") and work.decon_status != "paused_after_stage1":
        raise HTTPException(400, "拆书尚未完成")

    existing = db.query(StoryDeconstructionRef).filter(
        StoryDeconstructionRef.story_id == story_id,
        StoryDeconstructionRef.work_id == work_id,
    ).first()
    if existing:
        raise HTTPException(400, "已引用过该拆书结果")

    ref = StoryDeconstructionRef(story_id=story_id, work_id=work_id)
    db.add(ref)

    # 注入拆书结果到 story_bible
    decon_bible = {
        f"deconstruction_{work_id}": {
            "title": work.title,
            "author": work.author,
            "genre": work.genre,
            "summary": work.summary,
            "applied_at": str(datetime.datetime.now(datetime.timezone.utc)),
        },
        "learned_techniques": work.writing_techniques or [],
        "reference_plots": work.plot_lines or [],
        "reference_rhythm": work.rhythm,
        "reference_emotion_modules": work.emotion_modules,
        "reference_report": work.report_markdown,
    }
    current_bible = story.story_bible or {}
    current_bible.update(decon_bible)
    story.story_bible = current_bible
    db.commit()

    return {"message": f"已引用《{work.title}》的拆书报告到作品"}


@router.get("/api/stories/{story_id}/deconstruct/refs")
async def list_deconstruction_refs(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """查看作品引用的拆书结果列表"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    refs = db.query(StoryDeconstructionRef).filter(
        StoryDeconstructionRef.story_id == story_id,
    ).order_by(StoryDeconstructionRef.applied_at.desc()).all()

    return [
        {
            "id": r.id,
            "work_id": r.work_id,
            "title": r.work.title,
            "author": r.work.author,
            "genre": r.work.genre,
            "applied_at": str(r.applied_at) if r.applied_at else None,
        }
        for r in refs
    ]


@router.delete("/api/stories/{story_id}/deconstruct/refs/{ref_id}")
async def remove_deconstruction_ref(
    story_id: int,
    ref_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """取消引用拆书结果"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    ref = db.query(StoryDeconstructionRef).filter(
        StoryDeconstructionRef.id == ref_id,
        StoryDeconstructionRef.story_id == story_id,
    ).first()
    if not ref:
        raise HTTPException(404, "引用不存在")

    db.delete(ref)
    db.commit()

    return {"message": "已取消引用"}
