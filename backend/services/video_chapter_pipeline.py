"""章节视频工作流编排服务。

职责：管理从章节正文到 15s 分镜视频的完整流水线编排。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from database import SessionLocal
from models import (
    BackgroundTask,
    Chapter,
    ChapterVideoShot,
    ChapterVideoWorkflow,
    ScriptScene,
    Story,
    StoryCharacterVersion,
    VideoAsset,
    VideoShot,
)
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from services import deepseek as deepseek_service
from services import image2 as image_service
from services import video_api as video_api_service
from services import video_chapter_prompts as prompts
from services import video_generation as video_gen_service
from services.blocking import run_blocking
from services.errors import UpstreamServiceError, public_error_message
from services.media_locator import ensure_local_media_path, resolve_reference_input
from services.task_manager import task_manager
from services.visual_asset_generation import select_visual_references

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
    style_reference_image_url: str | None = None,
) -> ChapterVideoWorkflow:
    """创建新的章节视频工作流"""
    db = SessionLocal()
    try:
        workflow = ChapterVideoWorkflow(
            chapter_id=chapter_id,
            story_id=story_id,
            source_text=source_text,
            workflow_status="pending",
            character_reference_ids=character_reference_ids or [],
            video_style=video_style,
            style_reference_image_url=style_reference_image_url,
            duration_per_shot=15,
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
            _validate_shot_skeleton(shot_data)
            shot = ChapterVideoShot(
                workflow_id=workflow_id,
                shot_index=shot_data.get("shot_index", 0),
                source_text_span=shot_data.get("source_text_span"),
                scene_location=shot_data.get("scene_location"),
                time_of_day=shot_data.get("time_of_day"),
                characters=shot_data.get("characters"),
                screenplay_scene_id=shot_data.get("screenplay_scene_id"),
                screenplay_beat_id=shot_data.get("screenplay_beat_id"),
                narrative_purpose=shot_data.get("narrative_purpose"),
                beat_density=shot_data.get("beat_density"),
                transition_to_next=shot_data.get("transition_to_next"),
                story_summary=shot_data.get("story_summary"),
                dialogue_or_narration=shot_data.get("dialogue_or_narration"),
                key_props_json=shot_data.get("key_props"),
                scene_asset_candidates_json=shot_data.get("scene_asset_candidates"),
                camera_plan=shot_data.get("camera_plan"),
                motion_plan=shot_data.get("motion_plan"),
                emotion_plan=shot_data.get("emotion_plan"),
                continuity_notes=shot_data.get("continuity_notes"),
                storyboard_prompt=shot_data.get("storyboard_prompt") or "",  # ← 新增：保存 DeepSeek 生成的简洁提示词
                character_prompts_json=shot_data.get("character_prompts_json"),
                scene_prompt=shot_data.get("scene_prompt"),
                prop_prompts_json=shot_data.get("prop_prompts_json"),
                character_reference_ids=shot_data.get("character_reference_ids") or default_reference_ids,
                scene_reference_ids=shot_data.get("scene_reference_ids"),
                prop_reference_ids=shot_data.get("prop_reference_ids"),
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


def _validate_shot_skeleton(shot_data: dict[str, Any]) -> None:
    """校验拆镜骨架的必填字段，缺失 story_summary/source_text_span 时降级填充而非阻断。"""
    shot_index = int(shot_data.get("shot_index", 0) or 0)
    if shot_index <= 0:
        raise ValueError(f"拆镜骨架 shot_index 无效: {shot_index}")

    source_text_span = str(shot_data.get("source_text_span") or "").strip()
    if not source_text_span:
        logger.warning("镜头 %d 缺少 source_text_span，设为空占位", shot_index)
        shot_data["source_text_span"] = f"（第 {shot_index} 镜）"

    story_summary = str(shot_data.get("story_summary") or "").strip()
    if not story_summary:
        logger.warning("镜头 %d 缺少 story_summary，设为空占位", shot_index)
        shot_data["story_summary"] = f"镜头 {shot_index}"


def _clear_workflow_shots(workflow_id: int) -> None:
    """重新拆镜前清理 workflow 下的旧镜头。"""
    db = SessionLocal()
    try:
        db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id == workflow_id).delete()
        wf = db.query(ChapterVideoWorkflow).filter(ChapterVideoWorkflow.id == workflow_id).first()
        if wf:
            wf.total_shots = 0
            wf.completed_shots = 0
            wf.failed_shots = 0
            wf.error_message = None
        db.commit()
    finally:
        db.close()


def _build_shot_narrative_context(
    workflow: ChapterVideoWorkflow | None,
    current_shot_index: int,
) -> str:
    """构建单个镜头在完整剧情中的上下文衔接信息。

    遍历工作流的所有镜头，找出当前镜头的前一个和后一个镜头，
    提取其场景、时间、情节摘要等信息，格式化为提示词文本块。
    让故事版导演 AI 知道当前镜头在完整剧情序列中的位置。
    """
    if not workflow or not workflow.shots:
        return ""

    sorted_shots = sorted(workflow.shots, key=lambda s: (s.shot_index or 0))
    current_idx = None
    for i, s in enumerate(sorted_shots):
        if s.shot_index == current_shot_index:
            current_idx = i
            break

    if current_idx is None:
        return ""

    current_shot = sorted_shots[current_idx]
    context_parts = []

    # 前一个镜头
    if current_idx > 0:
        prev = sorted_shots[current_idx - 1]
        prev_chars = "、".join(prev.characters or []) if prev.characters else "未明确"
        context_parts.append(
            f"【前一个镜头（镜头{prev.shot_index}）】\n"
            f"场景：{prev.scene_location or '未明确'} | 时间：{prev.time_of_day or '未明确'}\n"
            f"出场角色：{prev_chars}\n"
            f"情节摘要：{prev.story_summary or '无'}\n"
        )

    # 后一个镜头
    if current_idx < len(sorted_shots) - 1:
        nxt = sorted_shots[current_idx + 1]
        nxt_chars = "、".join(nxt.characters or []) if nxt.characters else "未明确"
        context_parts.append(
            f"【后一个镜头（镜头{nxt.shot_index}）】\n"
            f"场景：{nxt.scene_location or '未明确'} | 时间：{nxt.time_of_day or '未明确'}\n"
            f"出场角色：{nxt_chars}\n"
            f"情节摘要：{nxt.story_summary or '无'}\n"
        )

    # 结构化连续性信息（来自 continuity_json）
    continuity_parts = []
    cj = current_shot.continuity_json
    if isinstance(cj, dict):
        from_prev = cj.get("from_previous", {})
        to_next = cj.get("to_next", {})
        visual_anchor = cj.get("visual_anchor")

        if isinstance(from_prev, dict):
            lines = []
            ps = from_prev.get("plot_state")
            cs = from_prev.get("character_state")
            vs = from_prev.get("visual_state")
            if ps:
                lines.append(f"  承接剧情：{ps}")
            if cs:
                lines.append(f"  承接角色状态：{cs}")
            if vs:
                lines.append(f"  承接画面状态：{vs}")
            if lines:
                continuity_parts.append("【承接前镜】\n" + "\n".join(lines))

        if isinstance(to_next, dict):
            lines = []
            ps = to_next.get("plot_setup")
            cs = to_next.get("character_state")
            vs = to_next.get("visual_state")
            if ps:
                lines.append(f"  铺垫剧情：{ps}")
            if cs:
                lines.append(f"  铺垫角色状态：{cs}")
            if vs:
                lines.append(f"  铺垫画面状态：{vs}")
            if lines:
                continuity_parts.append("【铺垫后镜】\n" + "\n".join(lines))

        if visual_anchor:
            continuity_parts.append(f"【画面锚点】{visual_anchor}")

    # 组装输出
    if not context_parts and not continuity_parts:
        return ""

    result = "### 剧情连续性上下文（前后镜头衔接）\n\n"
    if context_parts:
        result += "\n".join(context_parts)
    if continuity_parts:
        if context_parts:
            result += "\n\n"
        result += "### 结构化连续性信息\n\n"
        result += "\n\n".join(continuity_parts)
    result += (
        "\n\n### 连续性要求\n"
        "当前镜头在完整剧情序列中不是孤立出现的，在生成故事版时必须确保：\n"
        "1. 角色情绪必须从前一镜头的终点状态自然发展而来\n"
        "2. 如果时间或场景发生了变化，画面的叙事逻辑必须体现过渡\n"
        "3. 角色行为和状态应与前后镜头形成自然的因果关系链条\n"
        "4. 关键道具（如手机、戒指等）的状态应跨镜头保持一致"
    )
    return result


def _parse_screenplay_id_list(raw_value: object) -> set[str]:
    if raw_value is None:
        return set()
    if isinstance(raw_value, list):
        return {str(item).strip() for item in raw_value if str(item).strip()}
    text = str(raw_value).strip()
    if not text:
        return set()
    normalized = text.replace("，", ",").replace("、", ",").replace(";", ",").replace("；", ",")
    return {part.strip() for part in normalized.split(",") if part.strip()}


def build_screenplay_context_for_shot(workflow: ChapterVideoWorkflow | None, shot: ChapterVideoShot | None) -> str:
    if not workflow or not shot or not isinstance(workflow.screenplay_json, dict):
        return ""
    scenes = workflow.screenplay_json.get("scenes")
    if not isinstance(scenes, list):
        return ""

    target_scene_ids = _parse_screenplay_id_list(shot.screenplay_scene_id)
    target_beat_ids = _parse_screenplay_id_list(shot.screenplay_beat_id)
    normalized_scene_ids = {sid.replace("场景", "").strip() for sid in target_scene_ids}
    lines: list[str] = []

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or scene.get("scene_number") or "").strip()
        if target_scene_ids and scene_id not in target_scene_ids and scene_id not in normalized_scene_ids:
            continue

        title = str(scene.get("title") or "").strip()
        location = str(scene.get("location") or "").strip()
        time_of_day = str(scene.get("time_of_day") or "").strip()
        scene_purpose = str(scene.get("scene_purpose") or "").strip()
        header = f"场景 {scene_id}"
        if title:
            header += f"：{title}"
        if location:
            header += f" [{location}]"
        if time_of_day:
            header += f" ({time_of_day})"
        lines.append(header)

        characters = scene.get("characters")
        if isinstance(characters, list) and characters:
            lines.append(f"出场角色：{'、'.join(str(c) for c in characters if c)}")
        if scene_purpose:
            lines.append(f"场景功能：{scene_purpose}")

        visual_anchors = scene.get("visual_anchors")
        if isinstance(visual_anchors, list):
            for anchor in visual_anchors:
                if not isinstance(anchor, dict):
                    continue
                anchor_type = str(anchor.get("type") or "").strip()
                anchor_desc = str(anchor.get("description") or "").strip()
                if anchor_type and anchor_desc:
                    lines.append(f"视觉锚点[{anchor_type}]：{anchor_desc}")
                elif anchor_desc:
                    lines.append(f"视觉锚点：{anchor_desc}")

        beats = scene.get("beats")
        if isinstance(beats, list):
            for beat in beats:
                if not isinstance(beat, dict):
                    continue
                beat_id = str(beat.get("beat_id") or "").strip()
                if target_beat_ids and beat_id not in target_beat_ids:
                    beat_suffix_match = False
                    for tbid in target_beat_ids:
                        if "-" in tbid and tbid.rsplit("-", 1)[-1] == beat_id:
                            beat_suffix_match = True
                            break
                    if not beat_suffix_match:
                        continue
                beat_type = str(beat.get("type") or "").strip()
                importance = str(beat.get("importance") or "").strip()
                action = str(beat.get("action") or "").strip()
                dialogue = str(beat.get("dialogue") or "").strip()
                emotion = str(beat.get("emotion_shift") or "").strip()
                transition = str(beat.get("transition_to_next") or "").strip()
                beat_header = f"节拍 {beat_id}"
                if beat_type:
                    beat_header += f" [{beat_type}]"
                if importance:
                    beat_header += f" ({importance})"
                lines.append(beat_header)
                if action:
                    lines.append(f"动作：{action}")
                if dialogue:
                    lines.append(f"台词/旁白：{dialogue}")
                if emotion:
                    lines.append(f"情绪变化：{emotion}")
                if transition:
                    lines.append(f"承接：{transition}")

        next_scene = str(scene.get("transition_to_next_scene") or "").strip()
        if next_scene:
            lines.append(f"场次转场：{next_scene}")

    return "\n".join(lines).strip()


def _normalize_prompt_entries(entries: list[dict[str, object]] | list[dict[str, str]] | None) -> list[dict[str, str]]:
    """统一 prompt 条目中的值类型，避免响应校验失败。"""
    normalized: list[dict[str, str]] = []
    for entry in entries or []:
        normalized.append({str(key): "" if value is None else str(value) for key, value in entry.items()})
    return normalized


def _is_placeholder_character_prompt(character_name: str, prompt: str) -> bool:
    normalized_name = str(character_name or "").strip()
    normalized_prompt = str(prompt or "").strip()
    if not normalized_name or not normalized_prompt:
        return True
    compact_prompt = normalized_prompt.replace(" ", "")
    if compact_prompt == normalized_name:
        return True
    if compact_prompt == f"角色设定：{normalized_name}":
        return True
    if compact_prompt == f"角色设定:{normalized_name}":
        return True
    if compact_prompt == f"{normalized_name}角色设定":
        return True
    return False


def _normalize_asset_name(name: str | None, prefix: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    if raw.startswith(prefix):
        return raw[len(prefix):].strip()
    return raw


def _build_story_reuse_cache(story_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        cache: dict[str, Any] = {
            "characters": {},
            "scenes": {},
            "props": {},
        }

        character_versions = db.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.is_default == True,
        ).all()
        scene_assets = db.query(VideoAsset).filter(
            VideoAsset.story_id == story_id,
            VideoAsset.asset_type == "scene_reference",
            VideoAsset.status == "active",
        ).order_by(VideoAsset.created_at.desc()).all()
        prop_assets = db.query(VideoAsset).filter(
            VideoAsset.story_id == story_id,
            VideoAsset.asset_type == "prop_reference",
            VideoAsset.status == "active",
        ).order_by(VideoAsset.created_at.desc()).all()
        character_assets = db.query(VideoAsset).filter(
            VideoAsset.story_id == story_id,
            VideoAsset.asset_type.in_(["story_character_reference", "character_reference"]),
            VideoAsset.status == "active",
        ).order_by(VideoAsset.created_at.desc()).all()
        shots = db.query(ChapterVideoShot).join(ChapterVideoWorkflow).filter(
            ChapterVideoWorkflow.story_id == story_id,
        ).order_by(ChapterVideoShot.updated_at.desc(), ChapterVideoShot.id.desc()).all()

        for version in character_versions:
            name = (version.character_name or "").strip()
            if not name or name in cache["characters"]:
                continue
            asset_ids: list[int] = []
            ref_asset_id = version.ref_asset_id
            if ref_asset_id:
                asset_ids.append(int(ref_asset_id))
            else:
                for asset in character_assets:
                    asset_name = _normalize_asset_name(asset.name, "Character -")
                    if asset_name == name:
                        asset_ids.append(asset.id)
            cache["characters"][name] = {
                "prompt": (version.appearance_card or "").strip(),
                "asset_ids": asset_ids,
            }

        for shot in shots:
            scene_prompt = (shot.scene_prompt or "").strip()
            scene_location = (shot.scene_location or "").strip()
            time_of_day = (shot.time_of_day or "").strip()
            if scene_prompt and scene_location:
                key = (scene_location, time_of_day)
                if key not in cache["scenes"]:
                    asset_ids = list(shot.scene_reference_ids or [])
                    if not asset_ids:
                        asset_ids = [asset.id for asset in scene_assets if (asset.prompt or "").strip() == scene_prompt]
                    cache["scenes"][key] = {
                        "prompt": scene_prompt,
                        "asset_ids": asset_ids,
                    }

            prop_prompts = _normalize_prompt_entries(shot.prop_prompts_json)
            prop_reference_ids = list(shot.prop_reference_ids or [])
            for index, prop in enumerate(prop_prompts):
                prop_name = (prop.get("name") or "").strip()
                prop_prompt = (prop.get("prompt") or "").strip()
                if not prop_name or not prop_prompt or prop_name in cache["props"]:
                    continue
                asset_ids: list[int] = []
                if index < len(prop_reference_ids):
                    try:
                        asset_ids.append(int(prop_reference_ids[index]))
                    except Exception:
                        pass
                if not asset_ids:
                    for asset in prop_assets:
                        asset_name = _normalize_asset_name(asset.name, "Prop -")
                        if asset_name == prop_name or (asset.prompt or "").strip() == prop_prompt:
                            asset_ids.append(asset.id)
                            break
                cache["props"][prop_name] = {
                    "prompt": prop_prompt,
                    "asset_ids": asset_ids,
                }

        return cache
    except Exception as exc:
        logger.warning("构建 story 复用缓存失败 story=%s: %s", story_id, exc)
        return {
            "characters": {},
            "scenes": {},
            "props": {},
        }
    finally:
        db.close()


def _apply_story_reuse_cache_to_shots(shots_data: list[dict[str, Any]], story_cache: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not story_cache:
        return shots_data
    characters_cache = story_cache.get("characters") or {}
    scenes_cache = story_cache.get("scenes") or {}
    props_cache = story_cache.get("props") or {}
    hydrated: list[dict[str, Any]] = []
    for shot_data in shots_data:
        current = dict(shot_data)
        # 仅注入参考图 asset_id，不注入任何提示词
        # 所有提示词（角色/场景/道具）必须由 _expand_single_shot_prompts 重新生成，避免跨工作流缓存污染
        character_reference_ids: list[int] = []
        for raw_name in current.get("characters") or []:
            name = str(raw_name or "").strip()
            entry = characters_cache.get(name)
            if not name or not entry:
                continue
            for asset_id in entry.get("asset_ids") or []:
                if asset_id not in character_reference_ids:
                    character_reference_ids.append(asset_id)
        if character_reference_ids:
            current["character_reference_ids"] = character_reference_ids

        scene_location = str(current.get("scene_location") or "").strip()
        time_of_day = str(current.get("time_of_day") or "").strip()
        scene_entry = scenes_cache.get((scene_location, time_of_day))
        if scene_entry:
            scene_reference_ids = [asset_id for asset_id in (scene_entry.get("asset_ids") or []) if asset_id]
            if scene_reference_ids:
                current["scene_reference_ids"] = scene_reference_ids

        prop_reference_ids: list[int | None] = []
        for raw_name in current.get("key_props") or []:
            prop_name = str(raw_name or "").strip()
            entry = props_cache.get(prop_name)
            if not prop_name or not entry:
                continue
            asset_ids = [asset_id for asset_id in (entry.get("asset_ids") or []) if asset_id]
            prop_reference_ids.append(asset_ids[0] if asset_ids else None)
        if any(asset_id is not None for asset_id in prop_reference_ids):
            current["prop_reference_ids"] = prop_reference_ids
        hydrated.append(current)
    return hydrated


def _positive_reference_ids(values: list[Any] | None) -> list[int]:
    """清理引用 ID，忽略空值、非数字和非正数并保持原始顺序。"""
    result: list[int] = []
    for raw_value in values or []:
        try:
            asset_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if asset_id > 0 and asset_id not in result:
            result.append(asset_id)
    return result


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


def _build_chapter_storyboard_asset(
    *,
    workflow: ChapterVideoWorkflow,
    shot: ChapterVideoShot,
    file_path: str,
    prompt: str | None,
    provider: str,
    source_asset_ids: list[int] | None = None,
    source_type: str = "ai_generated",
) -> VideoAsset:
    return VideoAsset(
        story_id=workflow.story_id,
        chapter_id=workflow.chapter_id,
        shot_id=None,
        asset_type="storyboard_frame",
        name=f"故事版 - 镜头 {shot.shot_index}",
        file_path=file_path,
        provider=provider,
        prompt=prompt or "",
        source_asset_ids_json=source_asset_ids or None,
        style_preset=None,
        source_type=source_type,
        meta_json={
            "chapter_video_workflow_id": workflow.id,
            "chapter_video_shot_id": shot.id,
            "shot_index": shot.shot_index,
        },
    )


def _persist_chapter_storyboard_asset(
    *,
    workflow: ChapterVideoWorkflow,
    shot: ChapterVideoShot,
    file_path: str,
    prompt: str | None,
    provider: str,
    source_asset_ids: list[int] | None = None,
    source_type: str = "ai_generated",
) -> VideoAsset:
    db = SessionLocal()
    try:
        asset = _build_chapter_storyboard_asset(
            workflow=workflow,
            shot=shot,
            file_path=file_path,
            prompt=prompt,
            provider=provider,
            source_asset_ids=source_asset_ids,
            source_type=source_type,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    finally:
        db.close()


def clear_shot_storyboard(shot_id: int) -> ChapterVideoShot | None:
    """清除 shot 的故事版图片 URL，重置状态为 pending。"""
    return update_shot(shot_id, storyboard_image_url=None, status="pending")


def clear_shot_video(shot_id: int) -> ChapterVideoShot | None:
    """清除 shot 的视频 URL，重置状态为 pending。"""
    return update_shot(shot_id, video_url=None, status="pending")


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
    expand_prompts: bool = True,
    shot_id: int | None = None,
    **kwargs,
) -> dict[str, object]:
    """阶段1：将章节正文解析为 15s 分镜列表，停在工作流状态 shots_ready。"""
    logger.info("阶段1-拆镜 workflow=%s chapter=%s", workflow_id, chapter_id)
    billing_ctx = kwargs.get("billing_ctx")
    billing_finished = False

    def _finish_billing(success: bool, error_code: str | None = None) -> None:
        nonlocal billing_finished
        if billing_ctx is None or billing_finished:
            return
        from services.ai.resolver import complete_ai_call

        usage = deepseek_service.consume_usage_accumulator()
        billing_db = SessionLocal()
        try:
            complete_ai_call(
                billing_db,
                billing_ctx,
                success=success,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                error_code=error_code,
                usage_source="provider" if usage["input_tokens"] or usage["output_tokens"] else "estimated",
            )
            billing_finished = True
        finally:
            billing_db.close()

    update_workflow_status(workflow_id, "parsing_shots")

    if task_id and task_manager.is_cancellation_requested(task_id):
        update_workflow_status(workflow_id, "failed", "用户取消")
        _finish_billing(False, "cancelled")
        return {"workflow_status": "failed", "error": "用户取消"}

    _clear_workflow_shots(workflow_id)
    character_profiles = _load_character_profiles(story_id)
    try:
        shots_data = await deepseek_service.parse_chapter_to_shots_lite(
            chapter_text=source_text,
            character_profiles=character_profiles,
            api_key=deepseek_api_key,
        )
    except Exception as exc:
        logger.error("镜头解析失败 workflow=%s: %s", workflow_id, exc)
        error_message = public_error_message(exc, "镜头解析失败，请稍后重试")
        update_workflow_status(workflow_id, "failed", error_message)
        _finish_billing(False, type(exc).__name__)
        return {"workflow_status": "failed", "error": error_message}
    story_cache = _build_story_reuse_cache(story_id)
    shots_data = _apply_story_reuse_cache_to_shots(shots_data, story_cache)

    saved_shots = save_shots_from_parse(workflow_id, shots_data)
    logger.info("章节 %s 解析出 %d 个镜头", chapter_id, len(saved_shots))

    result: dict[str, object] = {
        "workflow_status": "shots_ready",
        "shot_count": len(saved_shots),
        "total_shots": len(saved_shots),
    }

    if expand_prompts:
        expand_result = await expand_shots_with_role_prompts(
            workflow_id=workflow_id,
            story_id=story_id,
            shot_ids=None,
            deepseek_api_key=deepseek_api_key,
            task_id=task_id,
        )
        logger.info(
            "流程完整性 workflow=%s stage=expand result=%s",
            workflow_id,
            expand_result.get("workflow_status"),
        )
        if expand_result.get("workflow_status") == "failed":
            _finish_billing(False, "prompt_expansion_failed")
            return expand_result

        result["expanded_shot_count"] = expand_result.get("expanded_shot_count", 0)
        result["failed_shot_ids"] = expand_result.get("failed_shot_ids", [])

    # 在提示词扩展（Phase 1.5）完成后才标记 shots_ready，
    # 确保前端轮询到 shots_ready 时所有提示词已写入 DB
    update_workflow_status(workflow_id, "shots_ready")
    _finish_billing(True)
    return result


async def expand_shots_with_role_prompts(
    workflow_id: int,
    story_id: int,
    shot_ids: list[int] | None = None,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """为 workflow 中的骨架镜头补全多角色提示词字段。"""
    db = SessionLocal()
    try:
        query = db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id == workflow_id)
        if shot_ids:
            query = query.filter(ChapterVideoShot.id.in_(shot_ids))
        target_shots = query.order_by(ChapterVideoShot.shot_index).all()
    finally:
        db.close()

    logger.info(
        "阶段1.5-提示词补全 workflow=%s total=%s shot_ids=%s",
        workflow_id,
        len(target_shots),
        shot_ids,
    )

    if not target_shots:
        return {"workflow_status": "shots_ready", "expanded_shot_count": 0, "failed_shot_ids": []}

    db = SessionLocal()
    try:
        story = db.query(Story).filter(Story.id == story_id).first()
    finally:
        db.close()

    # 并发展开前预填充角色提示词版本，避免同一角色被多次并发 AI 调用
    # 仅从 story.character_profiles 中提取已知角色的基础描述
    profile_text = (story.character_profiles or '').strip() if story else ''
    all_character_names: set[str] = set()
    for shot in target_shots:
        for name in shot.characters or []:
            normalized = str(name or '').strip()
            if normalized:
                all_character_names.add(normalized)
    for name in all_character_names:
        if not profile_text or name not in profile_text:
            continue
        _ensure_character_version(story_id, name, f"角色设定：{name}；参考角色档案：{profile_text[:280]}")

    semaphore = asyncio.Semaphore(4)
    scene_prop_cache: dict[tuple[object, ...], tuple[str, list[dict[str, str]]]] = {}

    async def _run_for_shot(shot: ChapterVideoShot) -> tuple[int, bool]:
        if task_id and task_manager.is_cancellation_requested(task_id):
            return shot.id, False
        async with semaphore:
            try:
                await _expand_single_shot_prompts(
                    shot.id,
                    deepseek_api_key=deepseek_api_key,
                    story=story,
                    scene_prop_cache=scene_prop_cache,
                )
                return shot.id, True
            except Exception as exc:
                update_shot(
                    shot.id,
                    error_message=public_error_message(exc, "镜头提示词补全失败，请稍后重试"),
                    status="failed",
                )
                logger.error("镜头提示词补全失败 shot=%s: %s", shot.id, exc)
                return shot.id, False

    results = await asyncio.gather(*[_run_for_shot(shot) for shot in target_shots])
    failed_ids = [shot_id for shot_id, ok in results if not ok]

    if task_id and task_manager.is_cancellation_requested(task_id):
        update_workflow_status(workflow_id, "failed", "用户取消")
        return {"workflow_status": "failed", "error": "用户取消"}

    if failed_ids and len(failed_ids) == len(target_shots):
        update_workflow_status(workflow_id, "failed", "所有镜头提示词补全失败")
        return {"workflow_status": "failed", "failed_shot_ids": failed_ids, "error": "所有镜头提示词补全失败"}

    if failed_ids:
        update_workflow_status(workflow_id, "shots_ready", f"{len(failed_ids)} 个镜头提示词补全失败")
    logger.info(
        "提示词补全完成 workflow=%s success=%s failed=%s failed_ids=%s",
        workflow_id,
        len(target_shots) - len(failed_ids),
        len(failed_ids),
        failed_ids,
    )
    return {
        "workflow_status": "shots_ready",
        "expanded_shot_count": len(target_shots) - len(failed_ids),
        "failed_shot_ids": failed_ids,
    }


async def generate_shot_details_batch(
    workflow_id: int,
    shot_ids: list[int],
    chapter_text: str,
    story_id: int,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
    shot_id: int | None = None,
    **kwargs,
) -> dict[str, object]:
    """为选中的镜头批量生成详细信息（运镜/动作/情绪/故事版等）。"""
    logger.info("批量生成详情 workflow=%s shot_ids=%s", workflow_id, shot_ids)

    update_workflow_status(workflow_id, "generating_details")

    if len(shot_ids) > 5:
        return {"success": False, "error": f"最多支持 5 个镜头，当前 {len(shot_ids)} 个"}

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

        if not target_shots:
            return {"success": False, "error": "未找到指定镜头"}

        shots_basic_info = []
        for shot in target_shots:
            shots_basic_info.append({
                "shot_index": shot.shot_index,
                "source_text_span": shot.source_text_span or "",
                "scene_location": shot.scene_location or "",
                "time_of_day": shot.time_of_day or "",
                "characters": shot.characters or [],
                "screenplay_scene_id": shot.screenplay_scene_id or "",
                "screenplay_beat_id": shot.screenplay_beat_id or "",
                "narrative_purpose": shot.narrative_purpose or "",
                "beat_density": shot.beat_density or "",
                "transition_to_next": shot.transition_to_next or "",
                "story_summary": shot.story_summary or "",
                "dialogue_or_narration": shot.dialogue_or_narration or "",
            })

        character_profiles = _load_character_profiles(story_id)

        if task_id and task_manager.is_cancellation_requested(task_id):
            return {"success": False, "error": "用户取消"}

        details_data = await deepseek_service.generate_shot_details(
            chapter_text=chapter_text,
            shots_basic_info=shots_basic_info,
            character_profiles=character_profiles,
            api_key=deepseek_api_key,
        )

        detail_map = {d.get("shot_index"): d for d in details_data}
        updated_ids = []
        failed_ids = []

        for shot in target_shots:
            detail = detail_map.get(shot.shot_index)
            if detail:
                shot.camera_plan = detail.get("camera_plan") or ""
                shot.motion_plan = detail.get("motion_plan") or ""
                shot.emotion_plan = detail.get("emotion_plan") or ""
                shot.continuity_notes = detail.get("continuity_notes") or ""
                shot.storyboard_json = detail.get("storyboard_json")
                shot.storyboard_prompt = _strip_storyboard_style_directives(
                    detail.get("storyboard_prompt") or ""
                )
                shot.scene_prompt = detail.get("scene_prompt") or ""
                shot.prop_prompts_json = detail.get("prop_prompts_json")
                updated_ids.append(shot.id)
            else:
                failed_ids.append(shot.id)

        db.commit()

        update_workflow_status(workflow_id, "shots_ready")

        return {
            "success": True,
            "updated_shot_ids": updated_ids,
            "failed_shot_ids": failed_ids,
            "total": len(shot_ids),
        }

    except Exception as e:
        db.rollback()
        logger.error("批量生成详情失败: %s", e)
        return {"success": False, "error": public_error_message(e, "批量生成镜头详情失败，请稍后重试")}
    finally:
        db.close()


async def generate_storyboards_for_shots(
    workflow_id: int,
    story_id: int,
    shot_ids: list[int] | None = None,
    image_api_key: str | None = None,
    deepseek_api_key: str | None = None,
    character_reference_ids: list[int] | None = None,
    task_id: str | None = None,
    shot_id: int | None = None,
    **kwargs,
) -> dict[str, object]:
    """阶段2：为指定 shots（或全部 pending shots）生成故事版图片。"""
    logger.info("阶段2-故事版 workflow=%s", workflow_id)

    update_workflow_status(workflow_id, "generating_storyboards")

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
            stage_ref_ids = _positive_reference_ids(
                list(character_reference_ids or [])
                + list(getattr(shot, "character_reference_ids", None) or [])
                + list(getattr(shot, "scene_reference_ids", None) or [])
                + list(getattr(shot, "prop_reference_ids", None) or [])
            )
            await regenerate_shot_storyboard(
                shot_id=shot.id,
                api_key=image_api_key,
                ref_asset_ids=stage_ref_ids or None,
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


async def reanalyze_storyboard_prompts(
    workflow_id: int,
    shot_ids: list[int] | None = None,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
    shot_id: int | None = None,
    **kwargs,
) -> dict[str, object]:
    """仅重新分析故事版提示词（DeepSeek 重新生成 prompt），不生成图片。

    遍历指定 shot，重新调用 DeepSeek 生成 storyboard_prompt 并保存，
    不调用 Image API，不影响已有 storyboard_image_url 和 status。
    """
    logger.info("重新分析故事版提示词 workflow=%s shot_ids=%s", workflow_id, shot_ids)

    # 保存旧状态并设置分析中状态
    _wf = get_workflow(workflow_id)
    _prev_status = _wf.workflow_status if _wf else "shots_ready"
    update_workflow_status(workflow_id, "reanalyzing_prompts")

    if not shot_ids:
        update_workflow_status(workflow_id, _prev_status)
        return {"workflow_status": "ok", "updated_shot_ids": [], "prompts": {}}

    db = SessionLocal()
    try:
        target_shots = (
            db.query(ChapterVideoShot)
            .filter(
                ChapterVideoShot.workflow_id == workflow_id,
                ChapterVideoShot.id.in_(shot_ids),
            )
            .all()
        )
    finally:
        db.close()

    if not target_shots:
        update_workflow_status(workflow_id, _prev_status)
        return {"workflow_status": "ok", "updated_shot_ids": [], "prompts": {}}

    updated_ids: list[int] = []
    prompts: dict[int, str] = {}
    wf = get_workflow(workflow_id)
    for shot in target_shots:
        try:
            shot_context = _build_shot_narrative_context(wf, shot.shot_index)
            new_content = await deepseek_service.generate_shot_storyboard_prompt({
                "shot_index": shot.shot_index,
                "scene_location": shot.scene_location,
                "time_of_day": shot.time_of_day,
                "characters": shot.characters,
                "screenplay_scene_id": shot.screenplay_scene_id,
                "screenplay_beat_id": shot.screenplay_beat_id,
                "narrative_purpose": shot.narrative_purpose,
                "beat_density": shot.beat_density,
                "transition_to_next": shot.transition_to_next,
                "story_summary": shot.story_summary,
                "dialogue_or_narration": shot.dialogue_or_narration,
                "source_text_span": shot.source_text_span,
                "camera_plan": shot.camera_plan,
                "motion_plan": shot.motion_plan,
                "emotion_plan": shot.emotion_plan,
                "style_preset": None,
                "shot_context": shot_context,
                "screenplay_context": build_screenplay_context_for_shot(wf, shot),
                "storyboard_json": shot.storyboard_json,
            }, api_key=deepseek_api_key)

            new_content = _strip_storyboard_style_directives(new_content)
            update_shot(shot.id, storyboard_prompt=new_content)
            updated_ids.append(shot.id)
            prompts[shot.id] = new_content
        except Exception as exc:
            logger.error("重新分析 shot %s 提示词失败: %s", shot.id, exc)

    logger.info("重新分析完成: updated=%s", updated_ids)
    update_workflow_status(workflow_id, _prev_status)
    return {
        "workflow_status": "ok",
        "updated_shot_ids": updated_ids,
        "prompts": prompts,
    }


def _append_screenplay_context_to_character_prompt(prompt: str, screenplay_context: str) -> str:
    context = (screenplay_context or "").strip()
    if not context or "剧本视觉锚点约束" in prompt:
        return prompt
    return (
        f"{prompt}\n\n"
        "剧本视觉锚点约束（必须优先遵守）：\n"
        f"{context[:1600]}"
    )


def _enrich_character_prompts_with_screenplay_context(
    prompts: list[dict[str, str]],
    screenplay_context: str,
) -> list[dict[str, str]]:
    if not screenplay_context:
        return prompts
    enriched: list[dict[str, str]] = []
    for entry in prompts:
        enriched.append({
            "name": entry.get("name", ""),
            "prompt": _append_screenplay_context_to_character_prompt(entry.get("prompt", ""), screenplay_context),
        })
    return enriched


def _build_chapter_shot_character_prompts(shot: ChapterVideoShot, story: Story | None, screenplay_context: str = "") -> list[dict[str, str]]:
    prompts: list[dict[str, str]] = []
    db = SessionLocal()
    try:
        version_rows = (
            db.query(StoryCharacterVersion)
            .filter(
                StoryCharacterVersion.story_id == story.id,
                StoryCharacterVersion.is_default == True,
            )
            .all()
            if story else []
        )
    finally:
        db.close()

    version_map = {row.character_name: (row.appearance_card or '').strip() for row in version_rows}
    profile_text = (story.character_profiles or '').strip() if story else ''

    for name in shot.characters or []:
        normalized_name = str(name or '').strip()
        if not normalized_name:
            continue
        version_prompt = version_map.get(normalized_name)
        if version_prompt and not _is_placeholder_character_prompt(normalized_name, version_prompt):
            prompts.append({"name": normalized_name, "prompt": _append_screenplay_context_to_character_prompt(version_prompt, screenplay_context)})
            continue
        fallback_parts = [f"角色设定：{normalized_name}"]
        if profile_text and normalized_name in profile_text:
            fallback_parts.append(f"参考角色档案：{profile_text[:280]}")
            prompt = _append_screenplay_context_to_character_prompt('；'.join(fallback_parts), screenplay_context)
            prompts.append({"name": normalized_name, "prompt": prompt})
    return prompts


async def reanalyze_shot_prompts(
    shot_id: int,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
    **kwargs,
) -> dict[str, object]:
    """重分析单镜头的全部提示词，并返回角色提示词列表。"""
    return await _expand_single_shot_prompts(shot_id, deepseek_api_key=deepseek_api_key)


def _ensure_character_version(story_id: int, name: str, prompt: str) -> None:
    """将 AI 生成的角色提示词持久化到 StoryCharacterVersion，供后续章节复用。

    仅当该角色尚无默认版本时才写入，不会覆盖用户手动创建的版本。
    """
    name = name.strip()
    prompt = prompt.strip()
    if not name or not prompt:
        return
    db = SessionLocal()
    try:
        existing = db.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.character_name == name,
            StoryCharacterVersion.is_default == True,
        ).first()
        if existing:
            return
        max_order = db.query(func.max(StoryCharacterVersion.sort_order)).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.character_name == name,
        ).scalar() or 0
        version = StoryCharacterVersion(
            story_id=story_id,
            character_name=name,
            version_label="",
            appearance_card=prompt,
            sort_order=max_order + 1,
            is_default=True,
        )
        db.add(version)
        db.commit()
    except Exception:
        logger.exception("保存 AI 角色提示词失败 story=%s name=%s", story_id, name)
    finally:
        db.close()


async def _expand_single_shot_prompts(
    shot_id: int,
    deepseek_api_key: str | None = None,
    story: Story | None = None,
    scene_prop_cache: dict[tuple[object, ...], tuple[str, list[dict[str, str]]]] | None = None,
) -> dict[str, object]:
    """补全单镜头的多角色提示词与细节字段。"""
    shot = get_shot(shot_id)
    if not shot:
        raise ValueError(f"镜头不存在: {shot_id}")

    workflow = get_workflow(shot.workflow_id)
    style_preset = None
    if story is None and workflow:
        db = SessionLocal()
        try:
            story = db.query(Story).filter(Story.id == workflow.story_id).first()
        finally:
            db.close()

    chapter_text = (workflow.source_text if workflow else "") or ""
    character_profiles = _load_character_profiles(workflow.story_id) if workflow else ""
    logger.info(
        "镜头提示词补全开始 shot=%s workflow=%s shot_index=%s characters=%s",
        shot_id,
        shot.workflow_id,
        shot.shot_index,
        shot.characters or [],
    )
    shot_basic_info = [{
        "shot_index": shot.shot_index,
        "source_text_span": shot.source_text_span or "",
        "scene_location": shot.scene_location or "",
        "time_of_day": shot.time_of_day or "",
        "characters": shot.characters or [],
        "screenplay_scene_id": shot.screenplay_scene_id or "",
        "screenplay_beat_id": shot.screenplay_beat_id or "",
        "narrative_purpose": shot.narrative_purpose or "",
        "beat_density": shot.beat_density or "",
        "transition_to_next": shot.transition_to_next or "",
        "story_summary": shot.story_summary or "",
        "dialogue_or_narration": shot.dialogue_or_narration or "",
    }]

    try:
        details_list = await deepseek_service.generate_shot_details(
            chapter_text=chapter_text,
            shots_basic_info=shot_basic_info,
            character_profiles=character_profiles,
            api_key=deepseek_api_key,
        )
        detail = details_list[0] if details_list else {}
    except Exception:
        detail = {}

    camera_plan = detail.get("camera_plan", "") or shot.camera_plan or ""
    motion_plan = detail.get("motion_plan", "") or shot.motion_plan or ""
    emotion_plan = detail.get("emotion_plan", "") or shot.emotion_plan or ""
    continuity_notes = detail.get("continuity_notes", "") or shot.continuity_notes or ""
    storyboard_json = detail.get("storyboard_json") or shot.storyboard_json

    storyboard_payload = {
        "shot_index": shot.shot_index,
        "scene_location": shot.scene_location,
        "time_of_day": shot.time_of_day,
        "characters": shot.characters,
        "screenplay_scene_id": shot.screenplay_scene_id,
        "screenplay_beat_id": shot.screenplay_beat_id,
        "narrative_purpose": shot.narrative_purpose,
        "beat_density": shot.beat_density,
        "transition_to_next": shot.transition_to_next,
        "story_summary": shot.story_summary,
        "dialogue_or_narration": shot.dialogue_or_narration,
        "source_text_span": shot.source_text_span,
        "camera_plan": camera_plan,
        "motion_plan": motion_plan,
        "emotion_plan": emotion_plan,
        "style_preset": style_preset,
        "storyboard_json": storyboard_json,
    }
    scene_prop_payload = {
        "shot_index": shot.shot_index,
        "scene_location": shot.scene_location,
        "time_of_day": shot.time_of_day,
        "characters": shot.characters,
        "story_summary": shot.story_summary,
        "dialogue_or_narration": shot.dialogue_or_narration,
        "key_props": shot.key_props_json,
        "scene_asset_candidates": shot.scene_asset_candidates_json,
        "camera_plan": camera_plan,
        "motion_plan": motion_plan,
        "continuity_notes": continuity_notes,
        "style_preset": style_preset,
    }

    shot_context = _build_shot_narrative_context(workflow, shot.shot_index)
    screenplay_context = build_screenplay_context_for_shot(workflow, shot)
    logger.info(
        "screenplay_context shot=%s len=%s has_visual_anchors=%s",
        shot_id,
        len(screenplay_context or ""),
        "视觉锚点" in (screenplay_context or ""),
    )

    character_prompts = _normalize_prompt_entries(shot.character_prompts_json)
    character_prompts = _enrich_character_prompts_with_screenplay_context(character_prompts, screenplay_context)

    # 工作流有剧本时，强制 AI 重生成角色 prompt，确保角色外观与场景一致
    # 用 workflow.screenplay_json（原始数据）而非 screenplay_context（派生文本），
    # 避免因 scene_id 不匹配导致 screenplay_context 为空而漏触发
    workflow_has_screenplay = (
        workflow is not None
        and isinstance(workflow.screenplay_json, dict)
        and bool(workflow.screenplay_json)
    )
    has_screenplay_context = bool((screenplay_context or "").strip())

    # 任一条件满足即触发强制重生成
    should_force_regenerate = (workflow_has_screenplay or has_screenplay_context) and character_prompts
    if should_force_regenerate:
        logger.info(
            "character prompts force ai regenerate shot=%s workflow_screenplay=%s context_len=%s",
            shot_id, workflow_has_screenplay, len(screenplay_context or ""),
        )
        character_prompts = []

    if not character_prompts and not workflow_has_screenplay:
        character_prompts = _normalize_prompt_entries(_build_chapter_shot_character_prompts(shot, story, screenplay_context))
    if character_prompts:
        logger.info("character prompts reused shot=%s count=%s", shot_id, len(character_prompts))
    reused_names = {entry.get("name", "") for entry in character_prompts}

    cache_key = (
        shot.scene_location or "",
        shot.time_of_day or "",
        tuple(str(item) for item in (shot.key_props_json or [])),
        tuple(str(item) for item in (shot.scene_asset_candidates_json or [])),
        style_preset or "",
    )
    if shot.scene_prompt and shot.prop_prompts_json:
        scene_prompt = shot.scene_prompt
        prop_prompts = _normalize_prompt_entries(shot.prop_prompts_json)
        logger.info("scene_prop db reused shot=%s key=%s", shot_id, cache_key)
    elif scene_prop_cache is not None and cache_key in scene_prop_cache:
        logger.info("scene_prop cache hit shot=%s key=%s", shot_id, cache_key)
        scene_prompt, prop_prompts = scene_prop_cache[cache_key]
    else:
        logger.info("scene_prop cache miss shot=%s key=%s", shot_id, cache_key)
        try:
            scene_prompt, prop_prompts = await deepseek_service.generate_shot_scene_prop_prompts(scene_prop_payload, api_key=deepseek_api_key)
            prop_prompts = _normalize_prompt_entries(prop_prompts)
            if scene_prop_cache is not None:
                scene_prop_cache[cache_key] = (scene_prompt, prop_prompts)
        except Exception as exc:
            logger.warning("场景/道具提示词生成失败 shot=%s: %s", shot_id, exc)
            scene_prompt = shot.scene_prompt or ""
            prop_prompts = _normalize_prompt_entries(shot.prop_prompts_json) or []

    storyboard_payload["shot_context"] = shot_context
    storyboard_payload["screenplay_context"] = screenplay_context
    try:
        storyboard_prompt = await deepseek_service.generate_shot_storyboard_prompt(storyboard_payload, api_key=deepseek_api_key)
    except Exception as exc:
        logger.warning("故事版提示词生成失败 shot=%s: %s", shot_id, exc)
        storyboard_prompt = shot.storyboard_prompt or ""

    missing_characters = [str(name) for name in (shot.characters or []) if str(name or '').strip() and str(name) not in reused_names]
    if missing_characters:
        logger.info("character prompts fallback to ai shot=%s names=%s", shot_id, missing_characters)
        try:
            ai_character_prompts_raw = await deepseek_service.generate_shot_character_prompts_ai(
                shot_data={
                    "shot_index": shot.shot_index,
                    "scene_location": shot.scene_location,
                    "time_of_day": shot.time_of_day,
                    "characters": missing_characters,
                    "story_summary": shot.story_summary,
                    "source_text_span": shot.source_text_span or "",
                    "chapter_text": chapter_text or "",
                    "shot_context": shot_context,
                    "screenplay_context": storyboard_payload.get("screenplay_context") or "",
                    "key_props": shot.key_props_json or [],
                    "scene_asset_candidates": shot.scene_asset_candidates_json or [],
                    "dialogue_or_narration": shot.dialogue_or_narration or "",
                    "camera_plan": camera_plan,
                    "motion_plan": motion_plan,
                    "emotion_plan": emotion_plan,
                },
                character_profiles=character_profiles,
                api_key=deepseek_api_key,
            )
            ai_character_prompts = _normalize_prompt_entries(ai_character_prompts_raw)
        except Exception as exc:
            logger.warning("AI 角色提示词生成失败 shot=%s: %s", shot_id, exc)
            ai_character_prompts = []
        character_prompts.extend(ai_character_prompts)
        if ai_character_prompts and story:
            for entry in ai_character_prompts:
                _ensure_character_version(story.id, entry.get("name", ""), entry.get("prompt", ""))

    # 视频提示词：只使用已保存的 shot.video_prompt，不自动回退到故事版提示词
    video_prompt = shot.video_prompt or ""

    update_shot(
        shot_id,
        camera_plan=camera_plan,
        motion_plan=motion_plan,
        emotion_plan=emotion_plan,
        continuity_notes=continuity_notes,
        storyboard_json=storyboard_json,
        storyboard_prompt=storyboard_prompt,
        video_prompt=video_prompt,
        character_prompts_json=character_prompts,
        scene_prompt=scene_prompt,
        prop_prompts_json=prop_prompts,
        error_message=None,
    )

    logger.info(
        "镜头提示词补全完成 shot=%s storyboard=%s video=%s characters=%s props=%s",
        shot_id,
        bool(storyboard_prompt),
        bool(video_prompt),
        len(character_prompts or []),
        len(prop_prompts or []),
    )

    return {
        "shot_id": shot_id,
        "camera_plan": camera_plan,
        "motion_plan": motion_plan,
        "emotion_plan": emotion_plan,
        "continuity_notes": continuity_notes,
        "storyboard_prompt": storyboard_prompt,
        "video_prompt": video_prompt,
        "character_prompts": character_prompts,
        "scene_prompt": scene_prompt,
        "prop_prompts": prop_prompts,
    }


async def generate_videos_for_shots(
    workflow_id: int,
    shot_ids: list[int] | None = None,
    image_api_key: str | None = None,
    deepseek_api_key: str | None = None,
    video_api_key: str | None = None,
    video_base_url: str | None = None,
    video_model: str | None = None,
    video_capabilities: dict | None = None,
    adapter_type: str = "lingdong_video",
    task_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
    shot_id: int | None = None,
    **kwargs,
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
                api_key=video_api_key,
                base_url=video_base_url,
                model=video_model,
                video_capabilities=video_capabilities,
                adapter_type=adapter_type,
                duration_seconds=max(1, min(60, int(getattr(shot, "duration_seconds", None) or 15))),
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
    """将 reference asset IDs 解析为可用于参考图输入的本地路径或远程 URL。"""
    if not ref_ids:
        return None
    from models import VideoAsset
    db = SessionLocal()
    try:
        assets = db.query(VideoAsset).filter(
            VideoAsset.id.in_(ref_ids),
            VideoAsset.status == "active",
        ).all()
        resolved: list[str] = []
        video_dir = get_video_output_dir()
        backend_root = Path(__file__).resolve().parent.parent
        manga_dir = backend_root / "manga_outputs"
        for a in assets:
            fp = (a.file_path or "").strip()
            if not fp:
                continue
            media_kind = "manga" if fp.startswith("/static/manga/") else "video"
            resolved_input = resolve_reference_input(fp, media_kind)
            if resolved_input:
                resolved.append(resolved_input)
                continue
            if fp.startswith("/static/manga/"):
                candidate = str(manga_dir / fp[len("/static/manga/"):])
                if os.path.isfile(candidate):
                    resolved.append(candidate)
                    continue
            # /static/video/ 前缀 → 转 video_outputs 下文件
            if fp.startswith("/static/video/"):
                candidate = str(video_dir / fp[len("/static/video/"):])
                if os.path.isfile(candidate):
                    resolved.append(candidate)
                    continue
            # 相对路径 → video_outputs/ 下
            candidate = str(video_dir / fp)
            if os.path.isfile(candidate):
                resolved.append(candidate)
                continue
            # 相对路径 → 项目根下
            candidate = str(backend_root / fp)
            if os.path.isfile(candidate):
                resolved.append(candidate)
                continue
            # 已经是绝对路径
            if os.path.isabs(fp) and os.path.isfile(fp):
                resolved.append(fp)
                continue
        return resolved if resolved else None
    finally:
        db.close()


def _load_owned_visual_assets(
    story_id: int,
    ref_ids: list[int],
    *,
    include_storyboard: bool = False,
) -> list[tuple[VideoAsset, str]]:
    """按用户选择顺序加载当前作品的角色、场景和道具资产。"""
    real_ids = _positive_reference_ids(ref_ids)
    if not real_ids:
        return []
    owned_assets: list[tuple[VideoAsset, str]] = []
    db = SessionLocal()
    try:
        assets = {
            asset.id: asset
            for asset in db.query(VideoAsset).filter(
                VideoAsset.id.in_(real_ids),
                VideoAsset.status == "active",
            ).all()
        }
        role_map = {
            "character_reference": "character",
            "story_character_reference": "character",
            "scene_reference": "scene",
            "prop_reference": "prop",
            "style_reference": "style",
            "style": "style",
        }
        if include_storyboard:
            role_map["storyboard_frame"] = "storyboard"
        for ref_id in real_ids:
            asset = assets.get(ref_id)
            role = role_map.get(asset.asset_type if asset else "")
            if not asset or not role:
                continue

            linked_story_ids: set[int] = set()
            if asset.story_id is not None:
                linked_story_ids.add(asset.story_id)
            if asset.chapter_id is not None:
                chapter = db.get(Chapter, asset.chapter_id)
                if chapter:
                    linked_story_ids.add(chapter.story_id)
            if asset.scene_id is not None:
                scene = db.get(ScriptScene, asset.scene_id)
                chapter = db.get(Chapter, scene.chapter_id) if scene else None
                if chapter:
                    linked_story_ids.add(chapter.story_id)
            if asset.shot_id is not None:
                video_shot = db.get(VideoShot, asset.shot_id)
                chapter = db.get(Chapter, video_shot.scene.chapter_id) if video_shot and video_shot.scene else None
                if chapter:
                    linked_story_ids.add(chapter.story_id)
            if linked_story_ids != {story_id}:
                logger.warning("跳过跨作品或归属不明的故事板参考资产 asset_id=%s", ref_id)
                continue
            owned_assets.append((asset, role))
    finally:
        db.close()

    return owned_assets


def _resolve_video_asset_references(
    story_id: int,
    ref_ids: list[int],
    context_text: str,
) -> list[tuple[Path, str, str]]:
    """将已校验的视觉资产本地化，供图片模型读取。"""
    entries: list[dict[str, object]] = []
    for asset, role in _load_owned_visual_assets(story_id, ref_ids):
        for raw_path in _resolve_ref_image_paths(story_id, [asset.id]) or []:
            local_path = raw_path
            if raw_path.lower().startswith(("http://", "https://")):
                local_path = ensure_local_media_path(raw_path, "manga") or ""
            if not local_path:
                continue
            path = Path(local_path)
            if not path.exists():
                continue
            entries.append({
                "path": path,
                "label": asset.name or "",
                "kind": role,
                "is_required": True,
            })

    selected = [
        (reference.path, reference.label, reference.role)
        for reference in select_visual_references(context_text, entries, max_items=8)
    ]
    return selected


def _resolve_video_asset_inputs(
    story_id: int,
    ref_ids: list[int],
) -> list[tuple[str, str, str]]:
    """解析视频 API 参考输入，保留 URL 或可用路径及用户选择顺序。"""
    resolved: list[tuple[str, str, str]] = []
    for asset, role in _load_owned_visual_assets(story_id, ref_ids, include_storyboard=True):
        input_value = (
            resolve_reference_input(asset.file_path, "video")
            or resolve_reference_input(asset.file_path, "manga")
        )
        if not input_value:
            paths = _resolve_ref_image_paths(story_id, [asset.id]) or []
            input_value = paths[0] if paths else ""
        if input_value:
            resolved.append((str(input_value), asset.name or "", role))
    return resolved


def _resolve_style_ref_local_path(style_reference_image_url: str | None) -> str | None:
    """将工作流风格参考图 URL 解析为本地文件路径。"""
    if not style_reference_image_url:
        return None
    return ensure_local_media_path(style_reference_image_url, "manga")


def _resolve_style_reference_input(style_reference_image_url: str | None) -> str | None:
    """保留公开风格图 URL，仅将相对路径解析为本地文件。"""
    raw = (style_reference_image_url or "").strip()
    if not raw:
        return None
    if raw.lower().startswith(("http://", "https://")):
        return resolve_reference_input(raw, "manga")
    return _resolve_style_ref_local_path(raw)


def _resolve_storyboard_local_path(storyboard_url: str | None) -> str | None:
    """将故事版 URL 解析为本地文件路径。"""
    if not storyboard_url:
        return None
    return ensure_local_media_path(storyboard_url, "manga")


def assemble_video_prompt_text(
    shot_id: int,
    ref_asset_ids: list[int] | None = None,
    prompt_override: str | None = None,
) -> dict:
    """组装三段式视频 prompt 文本（仅预览，不提交生成）。

    返回 {"assembled_prompt": str, "parts": {"part1": str, "part2": str, "part3": str | None}}。
    """
    shot = get_shot(shot_id)
    if not shot:
        return {"assembled_prompt": "", "parts": {"part1": "", "part2": "", "part3": None}}

    workflow = get_workflow(shot.workflow_id)
    if ref_asset_ids is not None:
        effective_ref_ids = list(ref_asset_ids)
    else:
        effective_ref_ids = list(dict.fromkeys(
            list(shot.character_reference_ids or [])
            + list(getattr(shot, "scene_reference_ids", None) or [])
            + list(getattr(shot, "prop_reference_ids", None) or [])
        ))

    from models import VideoAsset
    ref_details: list[tuple[int, str]] = []
    asset_type_map: dict[int, str] = {}

    real_asset_ids = [rid for rid in effective_ref_ids if rid != -1]
    if real_asset_ids:
        db = SessionLocal()
        try:
            assets = db.query(VideoAsset).filter(
                VideoAsset.id.in_(real_asset_ids),
                VideoAsset.status == "active",
            ).all()
            for a in assets:
                asset_type_map[a.id] = a.asset_type or "reference"
        finally:
            db.close()

    for rid in effective_ref_ids:
        if rid in asset_type_map:
            ref_details.append((rid, asset_type_map[rid]))
        elif rid == -1 or rid == shot.id:
            ref_details.append((rid, "storyboard"))
        else:
            ref_details.append((rid, "reference"))

    has_storyboard_ref = any(rt in {"storyboard", "storyboard_frame"} for _, rt in ref_details)

    system_prompt_parts: list[str] = []
    image_index = 1
    for _rid, ref_type in ref_details:
        if ref_type in {"storyboard", "storyboard_frame"}:
            system_prompt_parts.append(
                f"使用 @image{image_index} 作为故事版构图参考：场景布局、镜头角度、人物站位必须严格匹配这张图。"
            )
            image_index += 1
        elif ref_type in ("character_reference", "character"):
            system_prompt_parts.append(
                f"使用 @image{image_index} 作为角色外观参考：角色面貌、服装、体型必须在视频中保持一致。"
            )
            image_index += 1
        elif ref_type in ("scene_reference", "scene"):
            system_prompt_parts.append(
                f"使用 @image{image_index} 作为场景参考：环境布局、空间关系以这张图为准。"
            )
            image_index += 1
        elif ref_type in ("prop_reference", "prop"):
            system_prompt_parts.append(
                f"使用 @image{image_index} 作为道具参考：道具外观、材质以这张图为准。"
            )
            image_index += 1
        else:
            system_prompt_parts.append(
                f"使用 @image{image_index} 作为参考图。"
            )
            image_index += 1

    has_style_ref = False
    style_ref_source = workflow.style_reference_image_url if workflow else None
    if style_ref_source:
        has_style_ref = True
    if not has_style_ref and workflow:
        try:
            db_for_style = SessionLocal()
            from models import Chapter, VideoStylePreset
            chapter = db_for_style.query(Chapter).filter(Chapter.id == workflow.chapter_id).first()
            if chapter and chapter.video_style_preset_id:
                preset = db_for_style.get(VideoStylePreset, chapter.video_style_preset_id)
                if preset and preset.image_url:
                    has_style_ref = True
        finally:
            db_for_style.close()
    if has_style_ref:
        system_prompt_parts.append(
            f"使用 @image{image_index} 作为画面风格参考：画风、色调、光影、渲染质感以这张图为准。"
        )

    if not system_prompt_parts:
        system_prompt_parts.append("本次生成未使用参考图片。")
    part1 = "\n".join(system_prompt_parts)

    video_prompt = prompt_override or shot.video_prompt
    if video_prompt and "===" in video_prompt:
        video_prompt = video_prompt.split("===")[0].strip()
    if not video_prompt:
        video_prompt = ""

    if prompt_override:
        part2 = prompt_override
    elif has_storyboard_ref:
        part2 = (
            f"按照故事版图片中的分镜脚本内容生成{int(getattr(shot, 'duration_seconds', None) or 15)}秒视频。"
            "严格遵循分镜中每个时间段指定的镜头运动、画面内容、人物动作和情绪变化。"
            "不得添加分镜中未描述的元素，不得改变分镜中的场景关系和叙事逻辑。"
        )
    else:
        part2 = video_prompt or "生成15秒视频，保持画面流畅自然。"

    part3 = None
    if has_style_ref:
        part3 = "本视频的画风、色彩、光影以风格参考图为准，保持画面风格稳定统一。"
        if has_storyboard_ref:
            part3 += "\n故事版仅提供构图和动作参考，视频色彩、光影、渲染质感不受故事版影响，完全以风格参考图为准。"

    sections = [part1, part2]
    if part3:
        sections.append(part3)
    assembled = "\n\n".join(sections)

    return {
        "assembled_prompt": assembled,
        "parts": {"part1": part1, "part2": part2, "part3": part3},
    }


def _to_storyboard_static_url(image_path: str | None) -> str:
    """将 generate_manga_image 返回的本地路径标准化为可访问的静态 URL。"""
    if not image_path:
        return ""
    normalized = image_path.replace("\\", "/")
    if normalized.startswith("/static/manga/") or normalized.startswith("http"):
        return normalized
    if normalized.startswith("manga_outputs/"):
        normalized = normalized[len("manga_outputs/"):]
    return f"/static/manga/{normalized}"


def _strip_storyboard_style_directives(prompt: str) -> str:
    """移除旧故事版提示词中遗留的风格预设字段。"""
    cleaned = re.sub(r"\s*\|\s*【风格】[^|\n]*", "", str(prompt or ""))
    cleaned = re.sub(
        r"(?im)^\s*(?:visual\s+style|style|画面风格|风格预设)\s*[:：]\s*[^，,；;。.\n]*(?:[，,；;。. ]\s*)?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)(?:整体画风约束|视觉风格要求|风格参考图|风格预设约束)\s*[:：]?\s*[^，,；;。|\n]*[，,；;。|]?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)(?:写实电影感|日式动漫风|3A游戏渲染|水墨国风|水彩手绘风|暗黑哥特风|复古胶片感|科技赛博风|线稿电影感)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"([，,；;。|])\s*(?:[，,；;。|]\s*)+", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s*[，,；;。|]\s*|\s*[，,；;。|]\s*$", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _pick_style_anchor_image(workflow_id: int, current_shot_id: int) -> str | None:
    """从同一工作流的其他已成功生成的镜头中，选取第一张故事版图片作为风格锚点。

    这张图片不参与角色参考，而是作为画风参考，确保同一章节内所有镜头
    的视觉风格（线条、着色、色彩、光影处理）保持一致。
    """
    db = SessionLocal()
    try:
        try:
            anchor = (
                db.query(ChapterVideoShot)
                .filter(
                    ChapterVideoShot.workflow_id == workflow_id,
                    ChapterVideoShot.id != current_shot_id,
                    ChapterVideoShot.status == "storyboard_ready",
                    ChapterVideoShot.storyboard_image_url.isnot(None),
                    ChapterVideoShot.storyboard_image_url != "",
                )
                .order_by(ChapterVideoShot.shot_index.asc())
                .first()
            )
        except Exception as exc:
            logger.warning("加载风格锚点失败 workflow=%s shot=%s: %s", workflow_id, current_shot_id, exc)
            return None
        if anchor and anchor.storyboard_image_url:
            local_path = _resolve_storyboard_local_path(anchor.storyboard_image_url)
            if local_path:
                return local_path
        return None
    finally:
        db.close()


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
    base_url: str | None = None,
    model: str | None = None,
    max_poll_seconds: int = 7200,
    poll_interval: float = 5.0,
    adapter_type: str = "lingdong_video",
) -> str | None:
    """轮询视频任务直到完成，返回视频 URL。"""
    import asyncio

    start = datetime.now(timezone.utc)
    while (datetime.now(timezone.utc) - start).total_seconds() < max_poll_seconds:
        status = await video_gen_service.query_job_status(
            provider=provider,
            provider_job_id=provider_job_id,
            api_key=api_key,
            base_url=base_url,
            model=model,
            adapter_type=adapter_type,
        )
        if status.get("status") == "succeeded":
            # 获取最终结果
            result = await video_gen_service.fetch_job_result(
                provider=provider,
                provider_job_id=provider_job_id,
                shot_id=0,
                api_key=api_key,
                base_url=base_url,
                model=model,
                adapter_type=adapter_type,
            )
            video_path = result.get("video_path", "")
            if video_path:
                if video_path.startswith("/static/video/") or video_path.startswith("http"):
                    return video_path
                # 计算相对于 video_outputs 的路径（保留 shot_{id}/ 子目录）
                video_dir = get_video_output_dir()
                try:
                    rel = Path(video_path).resolve().relative_to(video_dir.resolve())
                    return f"/static/video/{rel.as_posix()}"
                except ValueError:
                    return f"/static/video/{Path(video_path).name}"
            return status.get("video_url", "")
        elif status.get("status") == "failed":
            error = str(status.get("error") or status.get("message") or "Unknown video task failure")
            raise UpstreamServiceError(
                error,
                retryable=False,
                provider=provider,
            )
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"视频任务超时（{max_poll_seconds}s）")


# ── 后台任务启动 ──────────────────────────────────────────


# ── 单镜头重新生成 ────────────────────────────────────────


async def regenerate_shot_storyboard(
    shot_id: int,
    api_key: str | None = None,
    prompt_override: str | None = None,
    ref_asset_ids: list[int] | None = None,
) -> ChapterVideoShot | None:
    """重新生成单镜头的故事版图片。

    数据流：
    1. 如果已有 storyboard_prompt（用户已触发过"重新分析提示词"），直接用它
    2. 否则调用 DeepSeek（故事版导演角色）生成，并存入 DB
    3. 将这段提示词直接发给图片 API，不做任何包装
    """
    shot = get_shot(shot_id)
    if not shot:
        return None

    # 1. 确认最终使用的提示词
    workflow = get_workflow(shot.workflow_id)
    style_preset = None

    director_prompt = prompt_override or shot.storyboard_prompt
    if director_prompt:
        # 校验现有提示词是否有效，防止复用被污染的元响应内容
        is_valid, reason = deepseek_service.is_valid_storyboard_prompt(director_prompt)
        if not is_valid:
            logger.warning("现有 storyboard_prompt 无效 (%s)，强制重新生成", reason)
            director_prompt = None

    if not director_prompt:
        # 从故事版导演角色生成并持久化
        shot_context = _build_shot_narrative_context(workflow, shot.shot_index)
        director_prompt = await deepseek_service.generate_shot_storyboard_prompt({
            "shot_index": shot.shot_index,
            "scene_location": shot.scene_location,
            "time_of_day": shot.time_of_day,
            "characters": shot.characters,
            "screenplay_scene_id": shot.screenplay_scene_id,
            "screenplay_beat_id": shot.screenplay_beat_id,
            "narrative_purpose": shot.narrative_purpose,
            "beat_density": shot.beat_density,
            "transition_to_next": shot.transition_to_next,
            "story_summary": shot.story_summary,
            "dialogue_or_narration": shot.dialogue_or_narration,
            "source_text_span": shot.source_text_span,
            "camera_plan": shot.camera_plan,
            "motion_plan": shot.motion_plan,
            "emotion_plan": shot.emotion_plan,
            "style_preset": style_preset,
            "shot_context": shot_context,
            "screenplay_context": build_screenplay_context_for_shot(workflow, shot),
            "storyboard_json": shot.storyboard_json,
        })
    director_prompt = _strip_storyboard_style_directives(director_prompt)

    chapter_id = getattr(workflow, "chapter_id", 0) if workflow else 0
    story_id = getattr(workflow, "story_id", 0) if workflow else 0
    workflow_id = shot.workflow_id

    # 显式选择覆盖自动引用；默认同时使用镜头关联的角色、场景和道具资产。
    if ref_asset_ids is not None:
        effective_ref_ids = _positive_reference_ids(ref_asset_ids)
    else:
        effective_ref_ids = _positive_reference_ids(
            list(getattr(shot, "character_reference_ids", None) or [])
            + list(getattr(shot, "scene_reference_ids", None) or [])
            + list(getattr(shot, "prop_reference_ids", None) or [])
        )
    logger.info("regenerate_shot_storyboard shot=%s ref_asset_ids=%s effective=%s",
                shot_id, ref_asset_ids, effective_ref_ids)
    resolved_references = _resolve_video_asset_references(story_id, effective_ref_ids, director_prompt)
    ref_image_paths = [str(path).replace("\\", "/") for path, _, _ in resolved_references]
    character_names = [str(name) for name in (shot.characters or []) if str(name).strip()]
    ref_labels = [
        label or (character_names[index] if index < len(character_names) else "")
        for index, (_, label, _) in enumerate(resolved_references)
    ]
    ref_roles = [role for _, _, role in resolved_references]
    safe_ref_paths = [video_api_service.safe_media_url_for_log(path) for path in ref_image_paths]
    logger.info("regenerate_shot_storyboard resolved references=%s", list(zip(ref_labels, ref_roles, safe_ref_paths)))
    for index, ref_path in enumerate(ref_image_paths, start=1):
        logger.info("故事版参考图 %s [local]: %s", index, video_api_service.safe_media_url_for_log(ref_path))

    try:
        update_shot(shot_id, status="storyboard_generating", storyboard_prompt=director_prompt, error_message=None)

        # 视频故事板只使用角色、场景和道具参考，不注入风格预设或自动风格锚点。
        image_result = await image_service.generate_manga_image(
            prompt=director_prompt,
            chapter_id=chapter_id,
            image_number=1000 + shot.shot_index,
            api_key=api_key,
            color_mode="bw",
            size="3840x2160",
            ref_image_paths=ref_image_paths or None,
            ref_labels=ref_labels or None,
            ref_roles=ref_roles or None,
            suppress_default_style=True,
        )

        storyboard_url = _to_storyboard_static_url(image_result.image_path)
        update_shot(shot_id, status="storyboard_ready", storyboard_image_url=storyboard_url)
        if workflow:
            try:
                _persist_chapter_storyboard_asset(
                    workflow=workflow,
                    shot=shot,
                    file_path=storyboard_url,
                    prompt=director_prompt,
                    provider="image2",
                    source_asset_ids=effective_ref_ids,
                    source_type="ai_generated",
                )
            except Exception:
                # 资产目录是派生索引，写入失败不能覆盖已经成功生成的故事板结果。
                logger.exception("故事板资产索引写入失败 shot=%s", shot_id)
    except Exception as exc:
        update_shot(
            shot_id,
            status="failed",
            error_message=public_error_message(exc, "故事版生成失败，请稍后重试"),
        )
        raise

    return get_shot(shot_id)


async def regenerate_shot_video(
    shot_id: int,
    api_key: str | None = None,
    prompt_override: str | None = None,
    ref_asset_ids: list[int] | None = None,
    base_url: str | None = None,
    model: str | None = None,
    deepseek_api_key: str | None = None,
    aspect_ratio: str = DEFAULT_VIDEO_ASPECT_RATIO,
    video_capabilities: dict | None = None,
    adapter_type: str = "lingdong_video",
    duration_seconds: int | None = None,
) -> ChapterVideoShot | None:
    """重新生成单镜头的视频。

    增强逻辑：
    1. 从镜头结构化字段构建场景描述加入 prompt（不引入故事版图像提示词）
    2. 视频 prompt 中加入风格预设文本
    3. 视频 prompt 中加入强约束要求匹配参考图/故事版
    4. 自动将工作流的风格参考图加入 reference_images
    5. 每张参考图在 prompt 中标注用途说明
    """
    shot = get_shot(shot_id)
    if not shot:
        return None
    submitted_duration = int(duration_seconds or getattr(shot, "duration_seconds", None) or 15)

    video_prompt = prompt_override or shot.video_prompt
    # 清理：去除 shot.video_prompt 中残留的旧 enrichments（以 === 开头的内容）
    if video_prompt and "===" in video_prompt:
        video_prompt = video_prompt.split("===")[0].strip()
    # 如果 prompt 为空或残留旧模板，清空（不自动回退到故事版提示词）
    import re
    is_stale_template = bool(video_prompt) and bool(re.search(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?\s*秒", video_prompt))
    if not video_prompt or is_stale_template:
        video_prompt = ""

    workflow = get_workflow(shot.workflow_id)
    story_id = workflow.story_id if workflow else 0
    style_prompt_template = ""
    if workflow:
        db_for_style_prompt = SessionLocal()
        try:
            from models import Chapter, VideoStylePreset
            chapter = db_for_style_prompt.get(Chapter, workflow.chapter_id)
            preset = None
            workflow_style = getattr(workflow, "video_style", None)
            if workflow_style:
                preset = db_for_style_prompt.query(VideoStylePreset).filter(
                    VideoStylePreset.name == workflow_style
                ).first()
            if not preset and chapter and chapter.video_style_preset_id:
                preset = db_for_style_prompt.get(VideoStylePreset, chapter.video_style_preset_id)
            style_prompt_template = (preset.prompt_template or "").strip() if preset else ""
        finally:
            db_for_style_prompt.close()
    if ref_asset_ids is not None:
        effective_ref_ids = list(ref_asset_ids)
    else:
        effective_ref_ids = list(dict.fromkeys(
            list(shot.character_reference_ids or [])
            + list(getattr(shot, "scene_reference_ids", None) or [])
            + list(getattr(shot, "prop_reference_ids", None) or [])
        ))
    # 过滤掉特殊 ID -1（故事版图片），只查询实际的资产 ID
    real_asset_ids = [rid for rid in effective_ref_ids if rid != -1]

    # ── 构建三段式视频 prompt ──────────────────────────
    # 第1步：收集参考图片及其类型
    reference_images: list[str] = []
    has_storyboard_ref = False
    has_character_ref = False
    has_style_ref = False

    reference_image_details: list[tuple[str, str]] = []

    # 旧客户端曾用当前 shot_id 表示故事版；若同号真实资产存在，则优先按资产 ID 解释。
    shot_id_is_visual_asset = bool(
        shot.id in effective_ref_ids
        and _load_owned_visual_assets(story_id, [shot.id], include_storyboard=True)
    )
    if shot.id in effective_ref_ids and not shot_id_is_visual_asset:
        storyboard_remote_path = resolve_reference_input(shot.storyboard_image_url, "manga")
        if storyboard_remote_path:
            reference_images.append(storyboard_remote_path)
            reference_image_details.append(("storyboard", storyboard_remote_path))
            has_storyboard_ref = True
        else:
            local_path = _resolve_storyboard_local_path(shot.storyboard_image_url)
            if local_path:
                reference_images.append(local_path)
                reference_image_details.append(("storyboard", local_path))
                has_storyboard_ref = True
    # 兼容旧的 -1 sentinel 机制
    if not has_storyboard_ref and (-1 in effective_ref_ids):
        storyboard_remote_path = resolve_reference_input(shot.storyboard_image_url, "manga")
        if storyboard_remote_path:
            reference_images.append(storyboard_remote_path)
            reference_image_details.append(("storyboard", storyboard_remote_path))
            has_storyboard_ref = True
        else:
            storyboard_local_path = _resolve_storyboard_local_path(shot.storyboard_image_url)
            if storyboard_local_path:
                reference_images.append(storyboard_local_path)
                reference_image_details.append(("storyboard", storyboard_local_path))
                has_storyboard_ref = True

    content_asset_ids = [
        rid for rid in real_asset_ids
        if rid != shot.id or shot_id_is_visual_asset
    ]
    for path_text, _label, role in _resolve_video_asset_inputs(story_id, content_asset_ids):
        path_text = path_text.replace("\\", "/")
        if path_text in reference_images:
            continue
        reference_images.append(path_text)
        reference_image_details.append((role, path_text))
        if role == "character":
            has_character_ref = True
        elif role == "storyboard":
            has_storyboard_ref = True
        elif role == "style":
            has_style_ref = True

    # 风格参考图：优先从 workflow，回退到章节预设
    style_ref_source = workflow.style_reference_image_url if workflow else None
    resolved_style_preset_id: int | None = None
    style_ref_path = _resolve_style_reference_input(style_ref_source)
    if not style_ref_path and workflow:
        try:
            db_for_style = SessionLocal()
            from models import Chapter, VideoStylePreset
            chapter = db_for_style.query(Chapter).filter(Chapter.id == workflow.chapter_id).first()
            preset = None
            workflow_style = getattr(workflow, "video_style", None)
            if workflow_style:
                preset = db_for_style.query(VideoStylePreset).filter(
                    VideoStylePreset.name == workflow_style
                ).first()
            if not preset and chapter and chapter.video_style_preset_id:
                preset = db_for_style.get(VideoStylePreset, chapter.video_style_preset_id)
            if preset:
                resolved_style_preset_id = preset.id
                logger.info(
                    "读取风格预设参考图: preset_id=%s preset.image_url=%s",
                    preset.id,
                    video_api_service.safe_media_url_for_log(preset.image_url),
                )
                if preset.image_url:
                    style_ref_path = _resolve_style_reference_input(preset.image_url)
        finally:
            db_for_style.close()
    if style_ref_path:
        has_style_ref = True
        if style_ref_path not in reference_images:
            reference_images.append(style_ref_path)
            reference_image_details.append(("style", style_ref_path))
    if style_ref_source:
        logger.info(
            "风格参考图来源: workflow.style_reference_image_url=%s 解析结果=%s",
            video_api_service.safe_media_url_for_log(style_ref_source),
            video_api_service.safe_media_url_for_log(style_ref_path),
        )
    else:
        logger.info(
            "风格参考图来源: 章节预设 (video_style_preset_id=%s) 解析结果=%s",
            getattr(workflow, 'chapter_id', None) if workflow else None,
            video_api_service.safe_media_url_for_log(style_ref_path),
        )

    # 第2步：构建系统提示词（按 reference_image_details 实际顺序，每张图独立说明）
    system_prompt_parts: list[str] = []
    for img_idx, (ref_role, _ref_path) in enumerate(reference_image_details, start=1):
        if ref_role == "storyboard":
            system_prompt_parts.append(
                f"使用 @image{img_idx} 作为故事版构图参考：场景布局、镜头角度、人物站位必须严格匹配这张图。"
            )
        elif ref_role == "character":
            system_prompt_parts.append(
                f"使用 @image{img_idx} 作为角色外观参考：角色面貌、服装、体型必须在视频中保持一致。"
            )
        elif ref_role == "prop":
            system_prompt_parts.append(
                f"使用 @image{img_idx} 作为道具参考：道具外观、材质、细节必须与这张图保持一致。"
            )
        elif ref_role == "scene":
            system_prompt_parts.append(
                f"使用 @image{img_idx} 作为场景参考：场景布局、环境元素、空间关系必须与这张图保持一致。"
            )
        elif ref_role == "style":
            system_prompt_parts.append(
                f"使用 @image{img_idx} 作为画面风格参考：画风、色调、光影、渲染质感以这张图为准。"
            )
        else:
            system_prompt_parts.append(
                f"使用 @image{img_idx} 作为参考图。"
            )
    if not reference_images:
        system_prompt_parts.append("本次生成未使用参考图片。")

    # 第3步：组装三段式 prompt
    prompt_sections: list[str] = []

    # Part 1: 系统提示词 - 参考图说明与约束
    prompt_sections.append("\n".join(system_prompt_parts))

    # Part 2: 视频生成指令
    if prompt_override:
        prompt_sections.append(prompt_override)
    elif has_storyboard_ref:
        prompt_sections.append(
            f"按照故事版图片中的分镜脚本内容生成{submitted_duration}秒视频。"
            "严格遵循分镜中每个时间段指定的镜头运动、画面内容、人物动作和情绪变化。"
            "不得添加分镜中未描述的元素，不得改变分镜中的场景关系和叙事逻辑。"
        )
    else:
        prompt_sections.append(video_prompt or f"生成{submitted_duration}秒视频，保持画面流畅自然。")

    # Part 3: 风格参考图约束（仅当有风格参考图时）
    if has_style_ref:
        style_constraint = "本视频的画风、色彩、光影以风格参考图为准，保持画面风格稳定统一。"
        if has_storyboard_ref:
            style_constraint += "\n故事版仅提供构图和动作参考，视频色彩、光影、渲染质感不受故事版影响，完全以风格参考图为准。"
        prompt_sections.append(style_constraint)

    # 保存核心 prompt 到 DB（不含 enrichments，避免重复累积）
    core_prompt = video_prompt
    # 组装含 enrichments 的完整 prompt 用于提交 API
    video_prompt = "\n\n".join(prompt_sections)
    if style_prompt_template and not has_style_ref:
        video_prompt = f"{video_prompt}\n\nVisual style: {style_prompt_template}"

    try:
        update_shot(
            shot_id,
            status="video_generating",
            video_prompt=core_prompt,
            duration_seconds=submitted_duration,
            error_message=None,
        )

        # ── 将本地参考图上传到 OSS，确保外部 API 可访问 ──
        if reference_images:
            from services import oss as oss_service
            oss_service.auto_configure_from_db()
            oss_uploaded: list[str] = []
            oss_details: list[tuple[str, str]] = []
            for img_path, (role, _orig) in zip(reference_images, reference_image_details):
                if img_path.lower().startswith(("http://", "https://")):
                    oss_uploaded.append(img_path)
                    oss_details.append((role, img_path))
                    continue
                logger.info(
                    "[video_submit] 尝试将本地参考图上传到 OSS: %s",
                    video_api_service.safe_media_url_for_log(img_path),
                )
                oss_url = await run_blocking(oss_service.upload_file, img_path)
                if oss_url:
                    logger.info(
                        "[video_submit] 本地参考图上 OSS 成功: %s → %s",
                        video_api_service.safe_media_url_for_log(img_path),
                        video_api_service.safe_media_url_for_log(oss_url),
                    )
                    oss_uploaded.append(oss_url)
                    oss_details.append((role, oss_url))
                    if role == "style" and img_path == style_ref_path and workflow:
                        persist_db = SessionLocal()
                        try:
                            if style_ref_source:
                                persisted_workflow = persist_db.get(ChapterVideoWorkflow, workflow.id)
                                if persisted_workflow:
                                    persisted_workflow.style_reference_image_url = oss_url
                            elif resolved_style_preset_id:
                                from models import VideoStylePreset

                                persisted_preset = persist_db.get(VideoStylePreset, resolved_style_preset_id)
                                if persisted_preset:
                                    persisted_preset.image_url = oss_url
                            persist_db.commit()
                        finally:
                            persist_db.close()
                else:
                    raise UpstreamServiceError(
                        "参考图无法发布到 OSS，已中止视频提交: "
                        f"{video_api_service.safe_media_url_for_log(img_path)}",
                        retryable=False,
                        provider=DEFAULT_VIDEO_PROVIDER,
                    )
            if oss_uploaded:
                reference_images = oss_uploaded
                reference_image_details = oss_details

        submitted_reference_images = reference_images or None

        # ── 日志输出：提交的提示词和参考图 ──
        logger.info("=" * 60)
        logger.info("[video_submit] shot_id=%s 开始提交视频任务", shot_id)
        logger.info("[video_submit] 最终 video_prompt（长度 %s 字符）:", len(video_prompt))
        for line in video_prompt.splitlines():
            logger.info("[video_submit]   %s", line)
        logger.info("[video_submit] 参考图片列表:")
        if submitted_reference_images:
            for i, (ref_role, img_path) in enumerate(reference_image_details, start=1):
                ref_kind = "remote" if img_path.lower().startswith(("http://", "https://")) else "local"
                logger.info(
                    "[video_submit]   参考图 %s [%s][%s]: %s",
                    i,
                    ref_role,
                    ref_kind,
                    video_api_service.safe_media_url_for_log(img_path),
                )
        else:
            logger.info("[video_submit]   （无参考图）")
        logger.info("[video_submit] 参考资产 ID: %s", effective_ref_ids)
        logger.info(
            "[video_submit] 模型: %s, 提供方: %s, base_url: %s",
            model or DEFAULT_VIDEO_MODEL,
            DEFAULT_VIDEO_PROVIDER,
            video_api_service.safe_media_url_for_log(base_url) if base_url else "默认",
        )
        logger.info("=" * 60)

        result = await video_gen_service.submit_video_job(
            shot_id=shot.id,
            provider=DEFAULT_VIDEO_PROVIDER,
            model=model or DEFAULT_VIDEO_MODEL,
            prompt=video_prompt,
            negative_prompt="",
            duration_seconds=submitted_duration,
            aspect_ratio=aspect_ratio or DEFAULT_VIDEO_ASPECT_RATIO,
            reference_images=submitted_reference_images,
            input_mode="image_to_video",
            api_key=api_key,
            base_url=base_url,
            video_capabilities=video_capabilities,
            adapter_type=adapter_type,
        )

        provider_job_id = result.get("provider_job_id", "")
        if provider_job_id:
            video_url = await _poll_video_job(
                provider=DEFAULT_VIDEO_PROVIDER,
                provider_job_id=provider_job_id,
                api_key=api_key,
                base_url=base_url,
                model=model,
                adapter_type=adapter_type,
            )
            update_shot(shot_id, status="video_ready", video_url=video_url or "")
        else:
            raise UpstreamServiceError(
                str(result.get("error") or result.get("message") or "Video task submission failed"),
                retryable=True,
                provider=DEFAULT_VIDEO_PROVIDER,
            )
    except Exception as exc:
        update_shot(
            shot_id,
            status="failed",
            error_message=public_error_message(exc, "视频生成失败，请稍后重试"),
        )
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


def _log_unavailable_shot_video(shot_index: int, video_url: str | None) -> None:
    """记录不可用视频时移除 URL 中的认证信息和签名参数。"""
    logger.warning(
        "镜头 %s 视频文件不可用: %s",
        shot_index,
        video_api_service.safe_media_url_for_log(video_url),
    )


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
                "duration_seconds": 15,
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
                    _log_unavailable_shot_video(shot.shot_index, shot.video_url)

        if not video_paths:
            raise ValueError("没有可用的视频文件进行拼接")

        if len(video_paths) < 2:
            shot = ready_shots[0]
            return {
                "video_url": shot.video_url,
                "shot_count": 1,
                "duration_seconds": 15,
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


# ── 短剧剧本生成 ──────────────────────────────────────────


async def generate_workflow_screenplay(
    workflow_id: int,
    *,
    deepseek_api_key: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """为工作流生成短剧剧本。

    从 workflow 关联的 chapter.novel_content 读取小说正文，
    调用 DeepSeek 将其转换为短剧剧本 JSON 格式，
    存入 workflow.screenplay_text / screenplay_json。

    Returns:
        {"screenplay_status": str, "scene_count": int}
    """
    logger.info("剧本生成 workflow=%s", workflow_id)

    db = SessionLocal()
    try:
        workflow = (
            db.query(ChapterVideoWorkflow)
            .options(selectinload(ChapterVideoWorkflow.chapter))
            .filter(ChapterVideoWorkflow.id == workflow_id)
            .first()
        )
        if not workflow:
            raise ValueError(f"工作流不存在: {workflow_id}")

        chapter = workflow.chapter
        if not chapter or not chapter.novel_content:
            raise ValueError(f"章节 {workflow.chapter_id} 没有小说正文，无法生成剧本")

        novel_content = chapter.novel_content

        if task_id and task_manager.is_cancellation_requested(task_id):
            return {"screenplay_status": "cancelled", "scene_count": 0}

        # 调用 DeepSeek 生成剧本
        payload = {
            "model": deepseek_service.runtime_model(),
            "messages": [
                {"role": "system", "content": prompts.NOVEL_TO_SHORT_DRAMA_SCREENPLAY_SYSTEM_PROMPT},
                {"role": "user", "content": prompts.NOVEL_TO_SHORT_DRAMA_SCREENPLAY_USER_PROMPT_HEADER + "\n\n" + novel_content},
            ],
            "stream": False,
            "max_tokens": 32768,
            "response_format": {"type": "json_object"},
        }

        async with deepseek_service.httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(deepseek_api_key),
            )
            resp.raise_for_status()
            data = deepseek_service._response_json(resp, context="DeepSeek")
            content = data["choices"][0]["message"]["content"]

        # 解析 JSON（复用轻量拆镜的修复链路）
        screenplay_json = None
        try:
            screenplay_json = deepseek_service._loads_json_lenient(content)
            if not isinstance(screenplay_json, dict):
                raise ValueError(f"剧本返回了非 JSON 对象: {type(screenplay_json).__name__}")
        except Exception:
            from services.deepseek import _extract_json_object, _repair_broken_json_fields, _repair_truncated_json
            try:
                screenplay_json = _extract_json_object(content)
            except ValueError:
                repaired = _repair_broken_json_fields(content)
                if repaired != content:
                    try:
                        screenplay_json = _extract_json_object(repaired)
                    except ValueError as e:
                        raise ValueError(f"剧本 JSON 修复失败: {e}") from e
                else:
                    truncated_repaired = _repair_truncated_json(content)
                    if truncated_repaired != content:
                        try:
                            screenplay_json = _extract_json_object(truncated_repaired)
                        except ValueError as e:
                            raise ValueError(f"剧本 JSON 截断修复后仍无法解析: {e}") from e
                    else:
                        raise ValueError(f"剧本 JSON 解析错误，且未发现可修复的损坏字段")

        if not isinstance(screenplay_json, dict):
            raise ValueError(f"剧本生成返回了非预期的格式: {type(screenplay_json).__name__}")

        scene_count = len(screenplay_json.get("scenes", []))

        # 写入 workflow
        workflow.screenplay_text = content
        workflow.screenplay_json = screenplay_json
        workflow.screenplay_status = "draft"
        workflow.screenplay_version = (workflow.screenplay_version or 0) + 1
        workflow.screenplay_updated_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "剧本生成完成 workflow=%s scenes=%d version=%d",
            workflow_id,
            scene_count,
            workflow.screenplay_version,
        )

        return {"screenplay_status": "draft", "scene_count": scene_count}

    except Exception as exc:
        logger.error("剧本生成失败 workflow=%s: %s", workflow_id, exc)
        db.rollback()
        raise
    finally:
        db.close()


def require_approved_screenplay(workflow: ChapterVideoWorkflow) -> None:
    """校验工作流的剧本状态是否为 approved。

    如果剧本未批准，抛出 ValueError 阻止后续流程继续。
    """
    if workflow.screenplay_status != "approved":
        raise ValueError("请先生成并批准短剧剧本")


def build_shot_source_from_screenplay(workflow: ChapterVideoWorkflow) -> str:
    """从工作流的剧本数据构造拆镜输入文本。

    优先从 screenplay_json 构造结构化文本，回退到 screenplay_text 原始文本。
    screenplay_json 格式由 NOVEL_TO_SHORT_DRAMA_SCREENPLAY_SYSTEM_PROMPT 定义，
    包含 scenes[{scene_id, title, location, time_of_day, characters, scene_purpose,
    visual_anchors, beats[{type, action, dialogue, emotion_shift}], transition_to_next_scene}]。
    """
    screenplay_json = workflow.screenplay_json

    if screenplay_json and isinstance(screenplay_json, dict):
        scenes = screenplay_json.get("scenes")
        if scenes and isinstance(scenes, list) and len(scenes) > 0:
            lines: list[str] = []
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                scene_id = scene.get("scene_id") or scene.get("scene_number", "")
                title = scene.get("title", "")
                location = scene.get("location", "")
                time_of_day = scene.get("time_of_day", "")
                scene_purpose = scene.get("scene_purpose", "")
                characters = scene.get("characters", [])
                transition_next = scene.get("transition_to_next_scene", "")

                header_parts = [f"场景 {scene_id}"]
                if title:
                    header_parts.append(f"：{title}")
                if location:
                    header_parts.append(f" [{location}]")
                if time_of_day:
                    header_parts.append(f" ({time_of_day})")
                lines.append("".join(header_parts))

                if characters and isinstance(characters, list):
                    lines.append(f"  出场角色：{'、'.join(str(c) for c in characters if c)}")

                if scene_purpose:
                    lines.append(f"  场景功能：{scene_purpose}")

                visual_anchors = scene.get("visual_anchors", [])
                if visual_anchors and isinstance(visual_anchors, list):
                    for va in visual_anchors:
                        if isinstance(va, dict):
                            va_type = va.get("type", "")
                            va_desc = va.get("description", "")
                            if va_type and va_desc:
                                lines.append(f"  视觉锚点 [{va_type}]：{va_desc}")
                            elif va_desc:
                                lines.append(f"  视觉锚点：{va_desc}")

                beats = scene.get("beats", [])
                if beats and isinstance(beats, list):
                    for beat in beats:
                        if not isinstance(beat, dict):
                            continue
                        beat_id = beat.get("beat_id", "")
                        beat_type = beat.get("type", "")
                        importance = beat.get("importance", "")
                        action = beat.get("action", "")
                        dialogue = beat.get("dialogue", "")
                        emotion_shift = beat.get("emotion_shift", "")
                        transition_to_next = beat.get("transition_to_next", "")

                        beat_parts = [f"  节拍 {beat_id}"]
                        if beat_type:
                            beat_parts.append(f"[{beat_type}]")
                        if importance:
                            beat_parts.append(f"({importance})")
                        lines.append(" ".join(beat_parts))

                        if action:
                            lines.append(f"    动作：{action}")
                        if dialogue:
                            lines.append(f"    台词：{dialogue}")
                        if emotion_shift:
                            lines.append(f"    情绪变化：{emotion_shift}")
                        if transition_to_next:
                            lines.append(f"    承接：{transition_to_next}")

                if transition_next:
                    lines.append(f"  转场：{transition_next}")

                lines.append("")
            return "\n".join(lines).strip()

    # 回退到 screenplay_text
    if workflow.screenplay_text:
        return workflow.screenplay_text

    return ""


def validate_screenplay_structure(screenplay_json: Any) -> list[str]:
    """校验 screenplay_json 结构是否合法。

    Returns:
        错误信息列表，空列表表示校验通过。
    """
    errors: list[str] = []

    if screenplay_json is None:
        errors.append("screenplay_json 为空")
        return errors

    if not isinstance(screenplay_json, dict):
        errors.append(f"screenplay_json 应为字典类型，实际为 {type(screenplay_json).__name__}")
        return errors

    scenes = screenplay_json.get("scenes")
    if scenes is None:
        errors.append("screenplay_json 缺少 'scenes' 字段")
        return errors

    if not isinstance(scenes, list):
        errors.append(f"scenes 应为列表类型，实际为 {type(scenes).__name__}")
        return errors

    if len(scenes) == 0:
        errors.append("scenes 列表为空，至少需要一个场景")
        return errors

    return errors
