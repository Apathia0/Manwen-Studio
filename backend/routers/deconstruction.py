"""
拆书功能 API 路由：搜书 → 爬取 → 拆书 → 结果 → 注入 Bible
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from database import get_db
from models import BackgroundTask, DeconstructionResult, NovelSource, Chapter
from services.novel_crawler import search_novels, crawl_qidian_novel
from services.deconstruction_v2 import run_deconstruction_pipeline_v2
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

    task_id_str = f"crawl_{story_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

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
    """启动拆书分析。可选 max_chapters 参数控制试读范围（如 100 = 仅前100章）。"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    body = await request.json()
    max_chapters = body.get("max_chapters")  # 试读模式：仅拆前 N 章，None = 全量

    chapter_count = db.query(Chapter).filter(
        Chapter.story_id == story_id,
        Chapter.novel_content.isnot(None),
        Chapter.novel_content != "",
        Chapter.content_source.in_(["crawled", None]),
    ).count()

    if chapter_count < 3:
        raise HTTPException(400, f"至少需要 3 章有内容的章节才能拆书（当前 {chapter_count} 章）")

    existing = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
        DeconstructionResult.status.in_(["pending", "running"]),
    ).first()

    if existing:
        raise HTTPException(400, "已有进行中的拆书任务")

    # 清理同 story 的旧失败 BackgroundTask 记录，避免 task_id 冲突
    db.query(BackgroundTask).filter(
        BackgroundTask.task_id.like(f"deconstruct_{story_id}_%"),
        BackgroundTask.status == "failed",
    ).delete()
    db.commit()

    from main import _check_and_consume_feature_quota, _refund_quota, _user_deepseek_api_key
    api_key = _user_deepseek_api_key(request)

    task_id_str = f"deconstruct_{story_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

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
        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="deconstruction",
            coro_func=run_deconstruction_pipeline_v2,
            story_id=story_id,
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
        if quota_amount > 0:
            _refund_quota(user.id, "deconstruction.run.monthly_limit", quota_amount, db, quota_period_key)
        raise

    return {
        "task_id": task_id_str,
        "message": "拆书任务已启动",
    }




@router.post("/api/stories/{story_id}/deconstruct/resume")
async def resume_deconstruction(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """续跑拆书分析。
    
    mode: "full" = 全量续跑 Stage 2-6（停靠后）；"partial" = 试读模式仅续跑前 N 章 Stage 2'-5'；"quick_report" = 基于前三章数据直接生成报告
    """
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)

    body = await request.json()
    mode = body.get("mode", "full")

    valid_statuses = ["paused_after_stage1"]
    if mode in ("partial", "quick_report"):
        # 试读/快速报告模式：从 paused_after_stage1 或 paused_after_partial:N 状态均可续跑
        valid_statuses = ["paused_after_stage1"]

    status_filter = DeconstructionResult.status.in_(valid_statuses)
    if mode in ("partial", "quick_report"):
        status_filter = or_(
            status_filter,
            DeconstructionResult.status.like("paused_after_partial:%"),
        )
    existing = db.query(DeconstructionResult).filter(
        DeconstructionResult.story_id == story_id,
        status_filter,
    ).order_by(DeconstructionResult.created_at.desc()).first()

    if not existing:
        if mode == "partial":
            raise HTTPException(400, "没有可续跑的拆书任务（需要先完成黄金三章拆解并停靠，再选择试读模式）")
        raise HTTPException(400, "没有可续跑的拆书任务（需要先完成黄金三章拆解并停靠）")

    existing.status = "running"
    db.commit()

    from main import _user_deepseek_api_key
    api_key = _user_deepseek_api_key(request)

    task_id_str = f"deconstruct_{story_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

    if mode == "partial":
        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="deconstruction",
            coro_func=run_deconstruction_pipeline_v2,
            story_id=story_id,
            api_key=api_key,
            start_stage=2,
            pause_after_stage1=False,
            partial_mode=True,
            timeout=7200,
            max_retries=0,
        )
        return {
            "task_id": task_id_str,
            "message": "试读模式已启动（Stage 2'-5'：逐章摘要 + 聚合 + 角色 + 试读报告）",
        }

    if mode == "quick_report":
        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="deconstruction",
            coro_func=run_deconstruction_pipeline_v2,
            story_id=story_id,
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

    # 全量续跑不变
    await task_manager.submit_task(
        task_id=task_id_str,
        task_type="deconstruction",
        coro_func=run_deconstruction_pipeline_v2,
        story_id=story_id,
        api_key=api_key,
        start_stage=2,
        pause_after_stage1=False,
        timeout=7200,
        max_retries=0,
    )

    return {
        "task_id": task_id_str,
        "message": "拆书续跑任务已启动（Stage 2-6）",
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
        DeconstructionResult.status.in_(["completed"]),
    ).order_by(DeconstructionResult.created_at.desc()).first()

    # 如果 completed 结果不存在，按优先级回退：paused_after_partial → paused_after_stage1
    if not result:
        result = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status.like("paused_after_partial:%"),
        ).order_by(DeconstructionResult.created_at.desc()).first()
    if not result:
        result = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status == "paused_after_stage1",
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
        "reference_report": result.report_markdown,
    }

    current_bible = story.story_bible or {}
    current_bible.update(decon_bible)
    story.story_bible = current_bible
    db.commit()

    return {"message": "拆书结果已注入作品圣经，Agent 可在写作中参考"}
