"""
拆书功能 API 路由：搜书 → 爬取 → 拆书 → 结果 → 注入 Bible
"""

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import get_db
from models import DeconstructionResult, NovelSource, Chapter
from services.novel_crawler import search_novels, crawl_qidian_novel
from services.deconstruction import run_deconstruction_pipeline
from services.task_manager import task_manager

router = APIRouter(tags=["deconstruction"])


# ── 辅助函数（从 main.py 引用）────────────────────────

def _require_user(request: Request, db: Session):
    """从 main.py 引用用户认证"""
    from main import _require_user as _ru
    return _ru(request, db)


def _require_story_for_user(story_id: int, user, db: Session):
    """从 main.py 引用故事权限检查"""
    from main import _require_story_for_user as _rsfu
    return _rsfu(story_id, user, db)


# ── 1. 搜书 ─────────────────────────────────────────

@router.get("/api/novels/search")
async def search_novels_endpoint(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    platform: str = Query("qidian", description="平台 (qidian)"),
    limit: int = Query(10, ge=1, le=20),
):
    """搜索网络小说"""
    results = await search_novels(keyword, platform, limit)
    return {"results": results, "total": len(results)}


# ── 2. 爬取小说 ─────────────────────────────────────

@router.post("/api/stories/{story_id}/crawl")
async def crawl_novel_endpoint(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """爬取小说章节内容"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    body = await request.json()

    platform = body.get("platform", "qidian")
    book_id = body.get("book_id")
    max_chapters = body.get("max_chapters", 100)

    if not book_id:
        raise HTTPException(400, "缺少 book_id 参数")

    # 创建或更新 NovelSource 记录
    source = db.query(NovelSource).filter(
        NovelSource.story_id == story_id,
        NovelSource.platform == platform,
        NovelSource.source_book_id == str(book_id),
    ).first()

    if not source:
        source = NovelSource(
            story_id=story_id,
            platform=platform,
            source_url=f"https://m.qidian.com/book/{book_id}/",
            source_book_id=str(book_id),
            crawl_status="crawling",
        )
        db.add(source)
        db.commit()

    task_id_str = f"crawl_{story_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"

    await task_manager.submit_task(
        task_id_str,
        "novel_crawl",
        crawl_qidian_novel,
        book_id,
        story_id=story_id,
        max_chapters=max_chapters,
        timeout=3600,
        max_retries=0,
    )

    return {
        "task_id": task_id_str,
        "message": f"开始爬取小说 (最多 {max_chapters} 章)",
    }


@router.get("/api/stories/{story_id}/crawl/status")
async def get_crawl_status(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """获取爬取进度"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    source = db.query(NovelSource).filter(
        NovelSource.story_id == story_id,
    ).order_by(NovelSource.created_at.desc()).first()

    if not source:
        return {"status": "not_started"}

    chapter_count = db.query(Chapter).filter(
        Chapter.story_id == story_id,
    ).count()

    return {
        "status": source.crawl_status,
        "platform": source.platform,
        "total_chapters": source.total_chapters,
        "crawled_chapters": source.crawled_chapters or chapter_count,
        "word_count": source.word_count,
        "source_url": source.source_url,
    }


# ── 3. 拆书 ─────────────────────────────────────────

@router.post("/api/stories/{story_id}/deconstruct/start")
async def start_deconstruction(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """启动拆书分析"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    chapter_count = db.query(Chapter).filter(
        Chapter.story_id == story_id,
        Chapter.novel_content.isnot(None),
        Chapter.novel_content != "",
    ).count()

    if chapter_count < 3:
        raise HTTPException(400, f"至少需要 3 章有内容的章节才能拆书（当前 {chapter_count} 章）")

    existing = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
        DeconstructionResult.status.in_(["pending", "running"]),
    ).first()

    if existing:
        raise HTTPException(400, "已有进行中的拆书任务")

    from main import _user_deepseek_api_key
    api_key = _user_deepseek_api_key(request)

    task_id_str = f"deconstruct_{story_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"

    await task_manager.submit_task(
        task_id=task_id_str,
        task_type="deconstruction",
        coro_func=run_deconstruction_pipeline,
        story_id=story_id,
        api_key=api_key,
        timeout=7200,
        max_retries=0,
    )

    return {
        "task_id": task_id_str,
        "message": "拆书任务已启动",
    }


@router.get("/api/stories/{story_id}/deconstruct/status")
async def get_deconstruction_status(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """获取拆书状态"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    result = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
    ).order_by(DeconstructionResult.created_at.desc()).first()

    if not result:
        return {"status": "not_started"}

    return {
        "status": result.status,
        "current_stage": result.current_stage,
        "stages_completed": result.stages_completed or [],
        "progress": result.progress_markdown,
        "result_id": result.id,
    }


@router.get("/api/stories/{story_id}/deconstruct/result")
async def get_deconstruction_result(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """获取拆书结果"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    result = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
        DeconstructionResult.status == "completed",
    ).order_by(DeconstructionResult.created_at.desc()).first()

    if not result:
        raise HTTPException(404, "该作品尚未完成拆书分析")

    return {
        "id": result.id,
        "status": result.status,
        "summary": result.summary,
        "golden_chapters": result.golden_chapters,
        "chapter_summaries": result.chapter_summaries,
        "characters": result.characters,
        "character_relations": result.character_relations,
        "plot_lines": result.plot_lines,
        "rhythm": result.rhythm,
        "emotion_modules": result.emotion_modules,
        "worldbuilding": result.worldbuilding,
        "report_markdown": result.report_markdown,
        "writing_style": result.writing_style,
        "writing_techniques": result.writing_techniques,
        "created_at": str(result.created_at) if result.created_at else None,
        "updated_at": str(result.updated_at) if result.updated_at else None,
    }


@router.post("/api/stories/{story_id}/deconstruct/cancel")
async def cancel_deconstruction(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """取消拆书"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    result = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
        DeconstructionResult.status.in_(["pending", "running"]),
    ).first()

    if not result:
        raise HTTPException(404, "没有进行中的拆书任务")

    if result.task_id:
        task_manager.request_cancellation(result.task_id)

    result.status = "failed"
    result.progress_markdown = (result.progress_markdown or "") + "\n- 用户取消"
    db.commit()

    return {"message": "已取消拆书任务"}


# ── 4. 拆书结果注入 story_bible ──────────────────────

@router.post("/api/stories/{story_id}/deconstruct/apply-to-bible")
async def apply_deconstruction_to_bible(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """将拆书结果注入作品的 story_bible，供 Agent 参考"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    result = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
        DeconstructionResult.status == "completed",
    ).order_by(DeconstructionResult.created_at.desc()).first()

    if not result:
        raise HTTPException(404, "该作品尚未完成拆书分析")

    decon_bible = {
        "deconstruction": {
            "source": result.summary,
            "applied_at": str(datetime.datetime.now(datetime.timezone.utc)),
        },
        "learned_techniques": result.writing_techniques or [],
        "reference_plots": result.plot_lines or [],
        "reference_rhythm": result.rhythm,
        "reference_emotion_modules": result.emotion_modules,
    }

    current_bible = story.story_bible or {}
    current_bible.update(decon_bible)
    story.story_bible = current_bible
    db.commit()

    return {"message": "拆书结果已注入作品圣经，Agent 可在写作中参考"}