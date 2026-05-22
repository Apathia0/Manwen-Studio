"""Service layer for shot breakdown and prompt engineering."""

from __future__ import annotations

import re
from typing import Any

import httpx

from . import deepseek as deepseek_service

SHOT_TYPES = ["wide", "full", "medium", "close_up", "extreme_close_up"]
CAMERA_ANGLES = ["eye_level", "high_angle", "low_angle", "over_shoulder"]
CAMERA_MOVEMENTS = ["static", "pan", "dolly", "track", "handheld"]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_shot(raw_shot: dict[str, Any], index: int, default_duration: int) -> dict[str, Any]:
    return {
        "shot_number": int(raw_shot.get("shot_number") or index),
        "title": _clean_text(raw_shot.get("title")) or f"镜头 {index}",
        "shot_type": _clean_text(raw_shot.get("shot_type")) or SHOT_TYPES[min(index - 1, len(SHOT_TYPES) - 1)],
        "camera_angle": _clean_text(raw_shot.get("camera_angle")) or "eye_level",
        "camera_movement": _clean_text(raw_shot.get("camera_movement")) or "static",
        "composition": _clean_text(raw_shot.get("composition")) or "主体明确，构图稳定",
        "action_description": _clean_text(raw_shot.get("action_description")) or "呈现场景推进动作",
        "dialogue": _clean_text(raw_shot.get("dialogue")),
        "sound_design": _clean_text(raw_shot.get("sound_design")) or "环境声与情绪音效",
        "duration_seconds": int(raw_shot.get("duration_seconds") or default_duration),
        "storyboard_prompt": _clean_text(raw_shot.get("storyboard_prompt")),
        "video_prompt": _clean_text(raw_shot.get("video_prompt")),
        "negative_prompt": _clean_text(raw_shot.get("negative_prompt")),
        "continuity_notes": _clean_text(raw_shot.get("continuity_notes")) or "保持角色造型、服装、场景连续性",
        "status": _clean_text(raw_shot.get("status")) or "draft",
    }


def _fallback_shot_templates(scene_summary: str, scene_dialogue: list[dict[str, str]], shot_count_hint: int, duration_budget_seconds: int) -> list[dict[str, Any]]:
    duration = max(3, duration_budget_seconds // max(1, shot_count_hint))
    dialogue_lines = [str(item.get("text") or "").strip() for item in scene_dialogue if isinstance(item, dict)]
    templates = [
        ("建立场", "wide", "eye_level", "static", "交代空间关系与人物站位"),
        ("动作推进", "medium", "over_shoulder", "track", "突出角色动作与互动"),
        ("情绪反应", "close_up", "eye_level", "static", "给到角色表情与情绪波动"),
        ("关键细节", "extreme_close_up", "low_angle", "pan", "强调道具、眼神或关键动作"),
        ("收束镜头", "full", "high_angle", "dolly", "完成节奏收束或转场"),
    ]
    shots: list[dict[str, Any]] = []
    for index in range(min(shot_count_hint, len(templates))):
        label, shot_type, angle, movement, action = templates[index]
        shots.append(
            {
                "shot_number": index + 1,
                "title": label,
                "shot_type": shot_type,
                "camera_angle": angle,
                "camera_movement": movement,
                "composition": f"{label}，围绕“{scene_summary[:24]}”组织画面重心",
                "action_description": f"{action}。场景核心内容：{scene_summary[:80]}",
                "dialogue": dialogue_lines[index] if index < len(dialogue_lines) else "",
                "sound_design": "保留环境声，并用音乐加强当前情绪",
                "duration_seconds": duration,
                "storyboard_prompt": "",
                "video_prompt": "",
                "negative_prompt": "",
                "continuity_notes": "保持场景光线、人物服装和站位连续",
                "status": "draft",
            },
        )
    return shots


async def generate_shots(
    scene_title: str,
    scene_summary: str,
    scene_dialogue: list[dict[str, str]],
    scene_mood: str,
    shot_count_hint: int = 4,
    duration_budget_seconds: int = 18,
    style: str = "cinematic",
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Break down a scene into individual shots."""
    cleaned_summary = _clean_text(scene_summary)
    if not cleaned_summary:
        raise ValueError("Scene summary is empty")

    if api_key:
        prompt = f"""请把下面这个场次拆解成可执行的视频镜头列表。

要求：
1. 只输出 JSON 对象，格式必须为 {{"shots": [{{...}}]}}。
2. 每个 shot 必须包含：
   shot_number, title, shot_type, camera_angle, camera_movement, composition,
   action_description, dialogue, sound_design, duration_seconds,
   storyboard_prompt, video_prompt, negative_prompt, continuity_notes, status
3. 镜头数量控制在 {shot_count_hint} 个左右。
4. 总时长预算约 {duration_budget_seconds} 秒。
5. 风格要求：{style}。
6. 每个镜头都必须服务于剧情推进，不能输出空泛占位描述。
7. shot_type 优先使用：wide/full/medium/close_up/extreme_close_up。
8. status 统一返回 draft。

场次标题：{scene_title}
场次情绪：{scene_mood}
场次摘要：{cleaned_summary}
对白：{scene_dialogue}
"""
        payload = {
            "model": deepseek_service.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "你是一名影视分镜导演与提示词工程师，只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    f"{deepseek_service.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=deepseek_service._deepseek_auth_headers(api_key),
                )
                response.raise_for_status()
                data = response.json()
                content = str(data["choices"][0]["message"]["content"] or "").strip()
            result = deepseek_service._extract_json_object(content)
            raw_shots = result.get("shots")
            if isinstance(raw_shots, list) and raw_shots:
                default_duration = max(3, duration_budget_seconds // max(1, len(raw_shots)))
                return [
                    _normalize_shot(shot, index + 1, default_duration)
                    for index, shot in enumerate(raw_shots)
                    if isinstance(shot, dict)
                ]
        except Exception:
            pass

    return _fallback_shot_templates(cleaned_summary, scene_dialogue, shot_count_hint, duration_budget_seconds)


async def generate_shot_prompts(
    shot_info: dict[str, Any],
    style: str,
    provider: str,
    continuity_notes: str,
    api_key: str | None = None,
) -> dict[str, str]:
    """Generate storyboard and video prompts for a single shot."""
    shot_type = _clean_text(shot_info.get("shot_type")) or "medium"
    camera_angle = _clean_text(shot_info.get("camera_angle")) or "eye_level"
    camera_movement = _clean_text(shot_info.get("camera_movement")) or "static"
    action_description = _clean_text(shot_info.get("action_description")) or "呈现场景关键动作"
    continuity = _clean_text(continuity_notes) or "保持角色与场景连续性"

    if api_key:
        prompt = f"""请为一个视频镜头生成 storyboard_prompt、video_prompt 和 negative_prompt。

要求：
1. 只输出 JSON 对象。
2. 格式必须为：
{{
  "storyboard_prompt": "...",
  "video_prompt": "...",
  "negative_prompt": "..."
}}
3. storyboard_prompt 适合生成关键帧参考图。
4. video_prompt 适合直接喂给 {provider} 视频模型。
5. 必须体现镜头语言、动作、风格、一致性约束。

镜头类型：{shot_type}
机位角度：{camera_angle}
运镜方式：{camera_movement}
动作描述：{action_description}
连续性要求：{continuity}
整体风格：{style}
"""
        payload = {
            "model": deepseek_service.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "你是一名影视提示词工程师，只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{deepseek_service.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=deepseek_service._deepseek_auth_headers(api_key),
                )
                response.raise_for_status()
                data = response.json()
                content = str(data["choices"][0]["message"]["content"] or "").strip()
            result = deepseek_service._extract_json_object(content)
            storyboard_prompt = _clean_text(result.get("storyboard_prompt"))
            video_prompt = _clean_text(result.get("video_prompt"))
            negative_prompt = _clean_text(result.get("negative_prompt"))
            if storyboard_prompt and video_prompt:
                return {
                    "storyboard_prompt": storyboard_prompt,
                    "video_prompt": video_prompt,
                    "negative_prompt": negative_prompt or "blurry, distorted, deformed, low detail, broken anatomy",
                }
        except Exception:
            pass

    return {
        "storyboard_prompt": (
            f"{style} storyboard frame, {shot_type} shot, {camera_angle} angle, {camera_movement} camera. "
            f"{action_description}. {continuity}. cinematic lighting, clear subject, production-ready frame."
        ),
        "video_prompt": (
            f"{style} short film shot, {shot_type} framing, {camera_angle} viewpoint, {camera_movement} movement. "
            f"{action_description}. {continuity}. natural motion, dramatic lighting, high detail, coherent action."
        ),
        "negative_prompt": "blurry, low quality, deformed, duplicated limbs, inconsistent costume, broken motion",
    }
