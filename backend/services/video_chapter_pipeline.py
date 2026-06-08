"""章节视频工作流编排服务。

职责：管理从章节正文到 10s 视频的完整流水线编排。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from database import SessionLocal
from models import ChapterVideoWorkflow, ChapterVideoShot, BackgroundTask
from sqlalchemy.orm import selectinload
from services import deepseek as deepseek_service
from services import image2 as image_service
from services import video_generation as video_gen_service
from services.task_manager import task_manager

logger = logging.getLogger(__name__)

# 默认视频生成配置
DEFAULT_VIDEO_PROVIDER = "sora"
DEFAULT_VIDEO_MODEL = "kling"
DEFAULT_VIDEO_ASPECT_RATIO = "16:9"


# ── 工作流 CRUD ──────────────────────────────────────────


def create_workflow(
    chapter_id: int,
    story_id: int,
    source_text: str,
    character_reference_ids: list[int] | None = None,
    video_style: str | None = None,
) -> ChapterVideoWorkflow:
    """创建新的章节视频工作流。"""
    db = SessionLocal()
    try:
        workflow = ChapterVideoWorkflow(
            chapter_id=chapter_id,
            story_id=story_id,
            source_text=source_text,
            workflow_status="pending",
            character_reference_ids=character_reference_ids or [],
            video_style=video_style,
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        return workflow
    finally:
        db.close()


def get_workflow(workflow_id: int) -> ChapterVideoWorkflow | None:
    """获取工作流及其所有 shot。"""
    db = SessionLocal()
    try:
        return db.query(ChapterVideoWorkflow).options(
            selectinload(ChapterVideoWorkflow.shots)
        ).filter(
            ChapterVideoWorkflow.id == workflow_id
        ).first()
    finally:
        db.close()


def get_workflows_for_chapter(chapter_id: int) -> list[ChapterVideoWorkflow]:
    """获取章节的所有工作流。"""
    db = SessionLocal()
    try:
        return db.query(ChapterVideoWorkflow).options(
            selectinload(ChapterVideoWorkflow.shots)
        ).filter(
            ChapterVideoWorkflow.chapter_id == chapter_id
        ).order_by(ChapterVideoWorkflow.created_at.desc()).all()
    finally:
        db.close()


def update_workflow_status(workflow_id: int, status: str, error: str | None = None) -> None:
    """更新工作流状态。"""
    db = SessionLocal()
    try:
        wf = db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.id == workflow_id).first()
        if wf:
            wf.workflow_status = status
            if error:
                wf.error_message = error
            db.commit()
    finally:
        db.close()


# ── Shot 管理 ────────────────────────────────────────────


def save_shots_from_parse(workflow_id: int, shots_data: list[dict[str, Any]]) -> list[ChapterVideoShot]:
    """将解析出的 shots 保存到数据库。"""
    db = SessionLocal()
    try:
        created = []
        workflow = db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.id == workflow_id).first()
        default_reference_ids = list(workflow.character_reference_ids or []) if workflow else []
        for shot_data in shots_data:
            shot = ChapterVideoShot(
                workflow_id=workflow_id,
                shot_index=shot_data.get("shot_index", 0),
                source_text_span=shot_data.get("source_text_span"),
                scene_location=shot_data.get("scene_location"),
                time_of_day=shot_data.get("time_of_day"),
                characters=shot_data.get("characters"),
                story_summary=shot_data.get("story_summary"),
                dialogue_or_narration=shot_data.get("dialogue_or_narration"),
                camera_plan=shot_data.get("camera_plan"),
                motion_plan=shot_data.get("motion_plan"),
                emotion_plan=shot_data.get("emotion_plan"),
                continuity_notes=shot_data.get("continuity_notes"),
                character_reference_ids=shot_data.get("character_reference_ids") or default_reference_ids,
                storyboard_json=shot_data.get("storyboard_json"),
                status="pending",
            )
            db.add(shot)
            created.append(shot)

        db.commit()
        for shot in created:
            db.refresh(shot)

        # 更新工作流统计
        if workflow:
            workflow.total_shots = len(created)
            db.commit()

        return created
    finally:
        db.close()


def get_shot(shot_id: int) -> ChapterVideoShot | None:
    """获取单个 shot。"""
    db = SessionLocal()
    try:
        return db.query(ChapterVideoShot).filter(ChapterVideoShot.id == shot_id).first()
    finally:
        db.close()


def update_shot(shot_id: int, **kwargs) -> ChapterVideoShot | None:
    """更新 shot 字段。"""
    db = SessionLocal()
    try:
        shot = db.query(ChapterVideoShot).filter(ChapterVideoShot.id == shot_id).first()
        if shot:
            for key, value in kwargs.items():
                if hasattr(shot, key):
                    setattr(shot, key, value)
            db.commit()
            db.refresh(shot)
        return shot
    finally:
        db.close()


def get_pending_shots(workflow_id: int) -> list[ChapterVideoShot]:
    """获取工作流中待处理的 shots。"""
    db = SessionLocal()
    try:
        return db.query(ChapterVideoShot).filter(
            ChapterVideoShot.workflow_id == workflow_id,
            ChapterVideoShot.status == "pending",
        ).order_by(ChapterVideoShot.shot_index).all()
    finally:
        db.close()


# ── 阶段函数（独立可调用）─────────────────────────────────


async def parse_chapter_shots(
    workflow_id: int,
    chapter_id: int,
    story_id: int,
    source_text: str,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """阶段1：将章节正文解析为 10s 镜头列表，停在工作流状态 shots_ready。"""
    logger.info("阶段1-拆镜 workflow=%s chapter=%s", workflow_id, chapter_id)

    update_workflow_status(workflow_id, "parsing_shots")

    if task_id and task_manager.is_cancellation_requested(task_id):
        update_workflow_status(workflow_id, "failed", "用户取消")
        return {"workflow_status": "failed", "error": "用户取消"}

    character_profiles = _load_character_profiles(story_id)
    shots_data = await deepseek_service.parse_chapter_to_shots(
        chapter_text=source_text,
        character_profiles=character_profiles,
        api_key=deepseek_api_key,
    )

    saved_shots = save_shots_from_parse(workflow_id, shots_data)
    logger.info("章节 %s 解析出 %d 个镜头", chapter_id, len(saved_shots))

    update_workflow_status(workflow_id, "shots_ready")

    return {
        "workflow_status": "shots_ready",
        "shot_count": len(saved_shots),
        "total_shots": len(saved_shots),
    }


async def generate_storyboards_for_shots(
    workflow_id: int,
    story_id: int,
    shot_ids: list[int] | None = None,
    image_api_key: str | None = None,
    deepseek_api_key: str | None = None,
    character_reference_ids: list[int] | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """阶段2：为指定 shots（或全部 pending shots）生成故事版图片。"""
    logger.info("阶段2-故事版 workflow=%s", workflow_id)

    update_workflow_status(workflow_id, "generating_storyboards")

    ref_image_paths = _resolve_ref_image_paths(story_id, character_reference_ids) if character_reference_ids else None

    # 确定目标 shots
    if shot_ids:
        db = SessionLocal()
        try:
            target_shots = (
                db.query(ChapterVideoShot)
                .filter(
                    ChapterVideoShot.workflow_id == workflow_id,
                    ChapterVideoShot.id.in_(shot_ids),
                )
                .order_by(ChapterVideoShot.shot_index)
                .all()
            )
        finally:
            db.close()
    else:
        target_shots = get_pending_shots(workflow_id)

    if not target_shots:
        update_workflow_status(workflow_id, "storyboards_ready")
        return {"workflow_status": "storyboards_ready", "shot_count": 0, "failed_shot_ids": []}

    wf = get_workflow(workflow_id)
    chapter_id = wf.chapter_id if wf else 0

    failed_ids: list[int] = []
    for shot in target_shots:
        if task_id and task_manager.is_cancellation_requested(task_id):
            update_workflow_status(workflow_id, "failed", "用户取消")
            return {"workflow_status": "failed", "error": "用户取消"}

        try:
            await regenerate_shot_storyboard(
                shot_id=shot.id,
                api_key=image_api_key,
            )
        except Exception:
            failed_ids.append(shot.id)

        _update_workflow_progress(workflow_id)

    if failed_ids:
        update_workflow_status(workflow_id, "generating_storyboards", f"{len(failed_ids)} 个镜头失败，等待人工处理")
        return {
            "workflow_status": "generating_storyboards",
            "shot_count": len(target_shots) - len(failed_ids),
            "failed_shot_ids": failed_ids,
        }

    update_workflow_status(workflow_id, "storyboards_ready")
    return {
        "workflow_status": "storyboards_ready",
        "shot_count": len(target_shots),
        "failed_shot_ids": [],
    }


async def generate_videos_for_shots(
    workflow_id: int,
    shot_ids: list[int] | None = None,
    image_api_key: str | None = None,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """阶段3：为指定 shots（或全部 storyboard_ready shots）生成视频。"""
    logger.info("阶段3-视频 workflow=%s", workflow_id)

    update_workflow_status(workflow_id, "generating_videos")

    # 确定目标 shots
    if shot_ids:
        db = SessionLocal()
        try:
            target_shots = (
                db.query(ChapterVideoShot)
                .filter(
                    ChapterVideoShot.workflow_id == workflow_id,
                    ChapterVideoShot.id.in_(shot_ids),
                    ChapterVideoShot.status.in_(["storyboard_ready", "video_generating", "pending"]),
                )
                .order_by(ChapterVideoShot.shot_index)
                .all()
            )
        finally:
            db.close()
    else:
        target_shots = _get_storyboard_ready_shots(workflow_id)

    if not target_shots:
        update_workflow_status(workflow_id, "videos_ready")
        return {"workflow_status": "videos_ready", "shot_count": 0, "failed_shot_ids": []}

    failed_ids: list[int] = []
    for shot in target_shots:
        if task_id and task_manager.is_cancellation_requested(task_id):
            update_workflow_status(workflow_id, "failed", "用户取消")
            return {"workflow_status": "failed", "error": "用户取消"}

        try:
            await regenerate_shot_video(
                shot_id=shot.id,
                api_key=image_api_key,
            )
        except Exception:
            failed_ids.append(shot.id)

        _update_workflow_progress(workflow_id)

    if failed_ids:
        update_workflow_status(workflow_id, "generating_videos", f"{len(failed_ids)} 个镜头失败，等待人工处理")
        return {
            "workflow_status": "generating_videos",
            "shot_count": len(target_shots) - len(failed_ids),
            "failed_shot_ids": failed_ids,
        }

    update_workflow_status(workflow_id, "videos_ready")
    return {
        "workflow_status": "videos_ready",
        "shot_count": len(target_shots),
        "failed_shot_ids": [],
    }


# ── run-all 包装 ──────────────────────────────────────────


async def run_all_stages(
    workflow_id: int,
    chapter_id: int,
    story_id: int,
    source_text: str,
    character_reference_ids: list[int] | None = None,
    deepseek_api_key: str | None = None,
    image_api_key: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """一键全自动：依次执行拆镜→故事版→视频三个阶段。

    根据工作流当前状态智能跳过已完成阶段。
    每个阶段独立调用，但统一汇报最终状态。
    """
    logger.info("一键全自动 workflow=%s", workflow_id)

    # 检查当前工作流状态，跳过已完成阶段
    current_wf = get_workflow(workflow_id)
    current_status = current_wf.workflow_status if current_wf else "pending"

    if current_status in ("storyboards_ready", "generating_videos", "videos_ready"):
        # 拆镜和故事版已完成，直接从视频阶段继续
        logger.info("工作流状态 %s，跳过拆镜和故事版阶段", current_status)
        video_result = await generate_videos_for_shots(
            workflow_id=workflow_id,
            shot_ids=None,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            task_id=task_id,
        )
        if video_result.get("workflow_status") in ("failed", "generating_videos"):
            return video_result
        wf = get_workflow(workflow_id)
        if wf and wf.failed_shots == wf.total_shots:
            update_workflow_status(workflow_id, "failed", "所有镜头均失败")
            return {"workflow_status": "failed", "error": "所有镜头均失败"}
        elif wf and wf.completed_shots > 0:
            update_workflow_status(workflow_id, "completed")
            return {"workflow_status": "completed", "workflow_id": workflow_id}
        else:
            update_workflow_status(workflow_id, "failed", "无成功镜头")
            return {"workflow_status": "failed", "error": "无成功镜头"}

    if current_status in ("shots_ready", "generating_storyboards"):
        # 拆镜已完成，跳过拆镜阶段，从故事版继续
        logger.info("工作流状态 %s，跳过拆镜阶段", current_status)
        storyboard_result = await generate_storyboards_for_shots(
            workflow_id=workflow_id,
            story_id=story_id,
            shot_ids=None,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            character_reference_ids=character_reference_ids,
            task_id=task_id,
        )
        if storyboard_result.get("workflow_status") in ("failed", "generating_storyboards"):
            return storyboard_result
    else:
        # pending/parsing_shots：阶段1：拆镜
        parse_result = await parse_chapter_shots(
            workflow_id=workflow_id,
            chapter_id=chapter_id,
            story_id=story_id,
            source_text=source_text,
            deepseek_api_key=deepseek_api_key,
            task_id=task_id,
        )
        if parse_result.get("workflow_status") == "failed":
            return parse_result

        # 阶段2：故事版
        storyboard_result = await generate_storyboards_for_shots(
            workflow_id=workflow_id,
            story_id=story_id,
            shot_ids=None,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            character_reference_ids=character_reference_ids,
            task_id=task_id,
        )
        if storyboard_result.get("workflow_status") in ("failed", "generating_storyboards"):
            return storyboard_result

    # 阶段3：视频（两个路径都汇合到这里）
    video_result = await generate_videos_for_shots(
        workflow_id=workflow_id,
        shot_ids=None,
        image_api_key=image_api_key,
        deepseek_api_key=deepseek_api_key,
        task_id=task_id,
    )
    if video_result.get("workflow_status") in ("failed", "generating_videos"):
        return video_result

    # 最终状态检查
    wf = get_workflow(workflow_id)
    if wf and wf.failed_shots == wf.total_shots:
        update_workflow_status(workflow_id, "failed", "所有镜头均失败")
        return {"workflow_status": "failed", "error": "所有镜头均失败"}
    elif wf and wf.completed_shots > 0:
        update_workflow_status(workflow_id, "completed")
        return {"workflow_status": "completed", "workflow_id": workflow_id}
    else:
        update_workflow_status(workflow_id, "failed", "无成功镜头")
        return {"workflow_status": "failed", "error": "无成功镜头"}


# ── 核心编排逻辑 ──────────────────────────────────────────


async def run_chapter_video_workflow(
    workflow_id: int,
    chapter_id: int,
    story_id: int,
    source_text: str,
    character_reference_ids: list[int] | None = None,
    video_style: str | None = None,
    api_key: str | None = None,
    task_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """执行完整的章节视频工作流（一键全自动模式）。

    内部使用 run_all_stages。image_api_key 和 deepseek_api_key 由调用方分别传递。
    """
    deepseek_api_key = api_key
    image_api_key = kwargs.get("image_api_key")

    logger.info("开始章节视频工作流（一键） workflow=%s chapter=%s", workflow_id, chapter_id)

    try:
        result = await run_all_stages(
            workflow_id=workflow_id,
            chapter_id=chapter_id,
            story_id=story_id,
            source_text=source_text,
            character_reference_ids=character_reference_ids,
            deepseek_api_key=deepseek_api_key,
            image_api_key=image_api_key,
            task_id=task_id,
        )

        ws = result.get("workflow_status", "failed")
        if ws == "completed":
            logger.info("章节视频工作流完成 workflow=%s", workflow_id)
            return {"status": "completed", "workflow_id": workflow_id}
        else:
            logger.warning("章节视频工作流未全部完成 workflow=%s status=%s", workflow_id, ws)
            return {"status": ws, "workflow_id": workflow_id}

    except Exception as exc:
        logger.error("章节视频工作流失败 workflow=%s: %s", workflow_id, exc)
        update_workflow_status(workflow_id, "failed", str(exc))
        raise


# ── 辅助工具 ──────────────────────────────────────────────


def _load_character_profiles(story_id: int) -> str:
    """从数据库加载故事的角色外貌设定。"""
    from models import Story
    db = SessionLocal()
    try:
        story = db.query(Story).filter(Story.id == story_id).first()
        return story.character_profiles or "" if story else ""
    finally:
        db.close()


def _resolve_ref_image_paths(story_id: int, ref_ids: list[int]) -> list[str] | None:
    """将 reference asset IDs 解析为文件路径。"""
    if not ref_ids:
        return None
    from models import VideoAsset
    db = SessionLocal()
    try:
        assets = db.query(VideoAsset).filter(
            VideoAsset.id.in_(ref_ids),
            VideoAsset.status == "active",
        ).all()
        paths = [a.file_path for a in assets if a.file_path]
        return paths if paths else None
    finally:
        db.close()


def _resolve_storyboard_local_path(storyboard_url: str | None) -> str | None:
    """将故事版 URL 解析为本地文件路径。"""
    if not storyboard_url:
        return None
    if storyboard_url.startswith("/static/manga/"):
        rel = storyboard_url[len("/static/manga/"):]
        local = Path(__file__).resolve().parent.parent / "manga_outputs" / rel
        return str(local) if local.exists() else None
    return None


def _update_workflow_progress(workflow_id: int) -> None:
    """更新工作流的进度计数。"""
    db = SessionLocal()
    try:
        wf = db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.id == workflow_id).first()
        if wf:
            shots = db.query(ChapterVideoShot).filter(
                ChapterVideoShot.workflow_id == workflow_id
            ).all()
            wf.completed_shots = sum(
                1 for s in shots if s.status in ("storyboard_ready", "video_ready")
            )
            wf.failed_shots = sum(1 for s in shots if s.status == "failed")
            db.commit()
    finally:
        db.close()


def _get_storyboard_ready_shots(workflow_id: int) -> list[ChapterVideoShot]:
    """获取故事版已就绪的 shots。"""
    db = SessionLocal()
    try:
        return db.query(ChapterVideoShot).filter(
            ChapterVideoShot.workflow_id == workflow_id,
            ChapterVideoShot.status == "storyboard_ready",
        ).order_by(ChapterVideoShot.shot_index).all()
    finally:
        db.close()


async def _poll_video_job(
    provider: str,
    provider_job_id: str,
    api_key: str | None = None,
    max_poll_seconds: int = 300,
    poll_interval: float = 5.0,
) -> str | None:
    """轮询视频任务直到完成，返回视频 URL。"""
    import asyncio

    start = datetime.now(timezone.utc)
    while (datetime.now(timezone.utc) - start).total_seconds() < max_poll_seconds:
        status = await video_gen_service.query_job_status(
            provider=provider,
            provider_job_id=provider_job_id,
            api_key=api_key,
        )
        if status.get("status") == "succeeded":
            # 获取最终结果
            result = await video_gen_service.fetch_job_result(
                provider=provider,
                provider_job_id=provider_job_id,
                shot_id=0,
                api_key=api_key,
            )
            video_path = result.get("video_path", "")
            if video_path:
                if video_path.startswith("/static/video/"):
                    return video_path
                return f"/static/video/{Path(video_path).name}"
            return status.get("video_url", "")
        elif status.get("status") == "failed":
            raise Exception(f"视频任务失败: {status.get('error', '未知错误')}")
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"视频任务超时（{max_poll_seconds}s）")


# ── 后台任务启动 ──────────────────────────────────────────


async def start_workflow_background(
    workflow_id: int,
    api_key: str | None = None,
    image_api_key: str | None = None,
) -> str:
    """在后台启动章节视频工作流。"""
    wf = get_workflow(workflow_id)
    if not wf:
        raise ValueError(f"工作流不存在: {workflow_id}")

    task_id = f"chapter_video_{workflow_id}_{uuid.uuid4().hex[:8]}"

    await task_manager.submit_task(
        task_id=task_id,
        task_type="chapter_video_workflow",
        coro_func=run_chapter_video_workflow,
        workflow_id=workflow_id,
        chapter_id=wf.chapter_id,
        story_id=wf.story_id,
        source_text=wf.source_text or "",
        character_reference_ids=wf.character_reference_ids,
        video_style=wf.video_style,
        api_key=api_key,
        image_api_key=image_api_key,
        timeout=1800.0,  # 30 分钟超时
        max_retries=1,
        story_id_extra=wf.story_id,
        chapter_id_extra=wf.chapter_id,
    )

    return task_id


# ── 单镜头重新生成 ────────────────────────────────────────


async def regenerate_shot_storyboard(
    shot_id: int,
    api_key: str | None = None,
    prompt_override: str | None = None,
) -> ChapterVideoShot | None:
    """重新生成单镜头的故事版图片。"""
    shot = get_shot(shot_id)
    if not shot:
        return None

    storyboard_prompt = prompt_override or shot.storyboard_prompt
    if not storyboard_prompt:
        storyboard_prompt = await deepseek_service.generate_shot_storyboard_prompt({
            "shot_index": shot.shot_index,
            "scene_location": shot.scene_location,
            "time_of_day": shot.time_of_day,
            "characters": shot.characters,
            "story_summary": shot.story_summary,
            "dialogue_or_narration": shot.dialogue_or_narration,
            "camera_plan": shot.camera_plan,
            "motion_plan": shot.motion_plan,
            "emotion_plan": shot.emotion_plan,
        })

    workflow = get_workflow(shot.workflow_id)
    chapter_id = workflow.chapter_id if workflow else 0

    try:
        update_shot(shot_id, status="storyboard_generating", storyboard_prompt=storyboard_prompt, error_message=None)

        image_result = await image_service.generate_manga_image(
            prompt=storyboard_prompt,
            chapter_id=chapter_id,
            image_number=1000 + shot.shot_index,
            api_key=api_key,
            color_mode="color",
        )

        storyboard_url = f"/static/manga/{image_result.image_path}" if image_result.image_path else ""
        update_shot(shot_id, status="storyboard_ready", storyboard_image_url=storyboard_url)
    except Exception as exc:
        update_shot(shot_id, status="failed", error_message=str(exc))
        raise

    return get_shot(shot_id)


async def regenerate_shot_video(
    shot_id: int,
    api_key: str | None = None,
    prompt_override: str | None = None,
) -> ChapterVideoShot | None:
    """重新生成单镜头的视频。"""
    shot = get_shot(shot_id)
    if not shot:
        return None

    video_prompt = prompt_override or shot.video_prompt
    if not video_prompt:
        video_prompt = await deepseek_service.generate_shot_video_prompt({
            "camera_plan": shot.camera_plan,
            "motion_plan": shot.motion_plan,
            "emotion_plan": shot.emotion_plan,
            "continuity_notes": shot.continuity_notes,
        })

    try:
        update_shot(shot_id, status="video_generating", video_prompt=video_prompt, error_message=None)

        storyboard_local_path = _resolve_storyboard_local_path(shot.storyboard_image_url)
        reference_images = [storyboard_local_path] if storyboard_local_path else None

        result = await video_gen_service.submit_video_job(
            shot_id=shot.id,
            provider=DEFAULT_VIDEO_PROVIDER,
            model=DEFAULT_VIDEO_MODEL,
            prompt=video_prompt,
            negative_prompt="",
            duration_seconds=10,
            aspect_ratio=DEFAULT_VIDEO_ASPECT_RATIO,
            reference_images=reference_images,
            input_mode="image_to_video",
            api_key=api_key,
        )

        provider_job_id = result.get("provider_job_id", "")
        if provider_job_id:
            video_url = await _poll_video_job(
                provider=DEFAULT_VIDEO_PROVIDER,
                provider_job_id=provider_job_id,
                api_key=api_key,
            )
            update_shot(shot_id, status="video_ready", video_url=video_url or "")
        else:
            raise Exception(f"视频任务提交失败: {result.get('error', '未知错误')}")
    except Exception as exc:
        update_shot(shot_id, status="failed", error_message=str(exc))
        raise

    return get_shot(shot_id)


# ── 第四阶段：质量优化 ──────────────────────────────────


def _is_transient_error(exc: Exception) -> bool:
    """判断异常是否为瞬态错误（可重试）。"""
    msg = str(exc).lower()
    return any(t in msg for t in ("timeout", "rate_limit", "503", "502", "service unavailable", "too many requests", "temporary", "try again"))


async def async_retry(
    coro_factory: Callable[[], Awaitable[Any]],
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> Any:
    """带指数退避的异步重试包装器，仅对瞬态错误重试。"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and _is_transient_error(exc):
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning("瞬态错误 (尝试 %d/%d): %s，%.1fs 后重试", attempt + 1, max_retries + 1, exc, delay)
                await asyncio.sleep(delay)
            else:
                raise
    if last_exc is None:
        raise RuntimeError("async_retry reached unexpected empty error state")
    raise last_exc


# ── 视频拼接 ──────────────────────────────────────────────


def get_video_output_dir() -> Path:
    """获取视频输出目录。"""
    return Path(__file__).resolve().parent.parent / "video_outputs"


def concat_chapter_videos(
    workflow_id: int,
    output_filename: str | None = None,
) -> dict[str, Any]:
    """将工作流中所有 video_ready 的镜头视频拼接为完整的章节视频。

    使用 ffmpeg concat demuxer 进行无损拼接。

    Returns:
        { "video_url": str, "shot_count": int, "duration_seconds": float }
    """
    db = SessionLocal()
    try:
        workflow = db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"工作流不存在: {workflow_id}")
        if workflow.workflow_status != "completed":
            raise ValueError(f"工作流未完成（当前状态: {workflow.workflow_status}），请等待所有镜头生成完毕")

        ready_shots = (
            db.query(ChapterVideoShot)
            .filter(
                ChapterVideoShot.workflow_id == workflow_id,
                ChapterVideoShot.status == "video_ready",
                ChapterVideoShot.video_url.isnot(None),
                ChapterVideoShot.video_url != "",
            )
            .order_by(ChapterVideoShot.shot_index.asc())
            .all()
        )

        if len(ready_shots) < 2:
            return {
                "video_url": ready_shots[0].video_url if ready_shots else "",
                "shot_count": len(ready_shots),
                "duration_seconds": 10,
                "message": "不足 2 个镜头，无需拼接",
            }

        output_dir = get_video_output_dir()
        concat_dir = output_dir / "chapter_concat" / str(workflow_id)
        concat_dir.mkdir(parents=True, exist_ok=True)

        filelist_path = concat_dir / "filelist.txt"
        video_paths: list[str] = []
        with open(filelist_path, "w", encoding="utf-8") as f:
            for shot in ready_shots:
                video_path = _resolve_video_local_path(shot.video_url)
                if video_path and os.path.isfile(video_path):
                    f.write(f"file '{video_path}'\n")
                    video_paths.append(video_path)
                else:
                    logger.warning("镜头 %s 视频文件不可用: %s", shot.shot_index, shot.video_url)

        if not video_paths:
            raise ValueError("没有可用的视频文件进行拼接")

        if len(video_paths) < 2:
            shot = ready_shots[0]
            return {
                "video_url": shot.video_url,
                "shot_count": 1,
                "duration_seconds": 10,
                "message": "可用视频不足 2 个，返回单个镜头视频",
            }

        chapter_id = workflow.chapter_id
        if not output_filename:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_filename = f"chapter_{chapter_id}_full_{timestamp}.mp4"

        output_path = output_dir / output_filename

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(filelist_path),
            "-c", "copy",
            str(output_path),
        ]

        logger.info("执行视频拼接: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error("ffmpeg 拼接失败 (code=%d): %s", result.returncode, result.stderr[:500])
            raise RuntimeError(f"视频拼接失败: {result.stderr[:200]}")

        duration = _get_video_duration(str(output_path))
        video_url = f"/static/video/{output_filename}"

        logger.info("章节视频拼接完成: %s (%d 个镜头, %.1fs)", output_filename, len(video_paths), duration)

        try:
            filelist_path.unlink(missing_ok=True)
        except Exception:
            pass

        return {
            "video_url": video_url,
            "shot_count": len(video_paths),
            "duration_seconds": duration,
        }
    finally:
        db.close()


def _resolve_video_local_path(video_url: str | None) -> str | None:
    """将 video_url 转换为本地文件路径。"""
    if not video_url:
        return None
    if video_url.startswith("/static/video/"):
        rel = video_url[len("/static/video/"):]
        return str(get_video_output_dir() / rel)
    if video_url.startswith("http"):
        return None
    return video_url


def _get_video_duration(file_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒）。"""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as exc:
        logger.warning("获取视频时长失败: %s", exc)
    return 0.0


# ── 角色一致性验证 ────────────────────────────────────────


def validate_character_consistency(workflow_id: int) -> dict[str, Any]:
    """验证工作流中各镜头的角色一致性。"""
    db = SessionLocal()
    try:
        shots = (
            db.query(ChapterVideoShot)
            .filter(ChapterVideoShot.workflow_id == workflow_id)
            .order_by(ChapterVideoShot.shot_index.asc())
            .all()
        )

        issues: list[dict[str, Any]] = []
        all_chars: set[str] = set()

        for shot in shots:
            chars = shot.characters or []
            ref_ids = shot.character_reference_ids or []
            shot_chars = set(c.lower().strip() if isinstance(c, str) else str(c) for c in chars)
            all_chars.update(shot_chars)

            if shot.status in ("storyboard_ready", "video_ready", "video_generating") and not ref_ids:
                issues.append({
                    "shot_index": shot.shot_index,
                    "severity": "warning",
                    "message": f"镜头 {shot.shot_index} 缺少角色参考图，角色一致性可能受影响",
                })

        return {
            "workflow_id": workflow_id,
            "total_shots": len(shots),
            "unique_characters": list(all_chars),
            "issues": issues,
            "issue_count": len(issues),
            "consistent": len(issues) == 0,
        }
    finally:
        db.close()
