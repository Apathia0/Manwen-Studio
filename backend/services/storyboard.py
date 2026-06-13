"""Service layer for shot breakdown and prompt engineering."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import deepseek as deepseek_service

SHOT_TYPES = ["wide", "full", "medium", "close_up", "extreme_close_up"]
CAMERA_ANGLES = ["eye_level", "high_angle", "low_angle", "over_shoulder"]
CAMERA_MOVEMENTS = ["static", "pan", "dolly", "track", "handheld"]
FOCAL_LENGTHS = ["wide_angle", "standard", "telephoto", "macro"]
LIGHTING_SETUPS = ["natural", "dramatic", "soft", "hard", "backlit", "low_key", "high_key"]
COLOR_PALETTES = ["warm", "cool", "neutral", "high_contrast", "pastel", "monochrome"]
TRANSITION_TYPES = ["cut", "fade_in", "fade_out", "dissolve", "whip_pan", "match_cut"]


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
        "character_involvement": _clean_text(raw_shot.get("character_involvement")),
        "scene_mood": _clean_text(raw_shot.get("scene_mood")),
        "focal_length": _clean_text(raw_shot.get("focal_length")) or "standard",
        "lighting": _clean_text(raw_shot.get("lighting")) or "natural",
        "color_palette": _clean_text(raw_shot.get("color_palette")) or "neutral",
        "transition": _clean_text(raw_shot.get("transition")) or "cut",
        "action_segments": _clean_text(raw_shot.get("action_segments")) or "完整动作段落",
        "frame_composition": _clean_text(raw_shot.get("frame_composition")) or "主体位置居中",
        "status": _clean_text(raw_shot.get("status")) or "draft",
    }


def _fallback_shot_templates(scene_summary: str, scene_dialogue: list[dict[str, str]], shot_count_hint: int, duration_budget_seconds: int) -> list[dict[str, Any]]:
    duration = min(10, max(3, duration_budget_seconds // max(1, shot_count_hint)))
    dialogue_lines = [str(item.get("text") or "").strip() for item in scene_dialogue if isinstance(item, dict)]
    
    templates = [
        ("建立镜头", "wide", "eye_level", "static", "交代场景和人物站位"),
        ("推进镜头", "medium", "over_shoulder", "track", "突出角色动作与互动"),
        ("高潮镜头", "close_up", "eye_level", "static", "给到角色表情与情绪波动"),
        ("转折镜头", "extreme_close_up", "low_angle", "pan", "强调道具、眼神或关键动作"),
        ("收束镜头", "full", "high_angle", "dolly", "完成节奏收束或转场"),
    ]
    
    shots: list[dict[str, Any]] = []
    for index in range(min(shot_count_hint, len(templates))):
        label, shot_type, angle, movement, action = templates[index]
        start_sec = index * duration
        end_sec = min((index + 1) * duration, duration_budget_seconds)
        time_range = f"{start_sec}s-{end_sec}s"
        shots.append(
            {
                "shot_number": index + 1,
                "title": label,
                "shot_type": shot_type,
                "camera_angle": angle,
                "camera_movement": movement,
                "composition": f"{label}，围绕'{scene_summary[:24]}'组织画面重心",
                "action_description": f"{action}。场景核心内容：{scene_summary[:80]}",
                "dialogue": dialogue_lines[index] if index < len(dialogue_lines) else "",
                "sound_design": "保留环境声，并用音乐加强当前情绪",
                "duration_seconds": duration,
                "storyboard_prompt": "",
                "video_prompt": "",
                "negative_prompt": "",
                "continuity_notes": "保持场景光线、人物服装和站位连续",
                "character_involvement": None,
                "scene_mood": None,
                "focal_length": "standard",
                "lighting": "natural",
                "color_palette": "neutral",
                "transition": "cut",
                "action_segments": "完整动作段落",
                "frame_composition": "主体位置居中",
                "status": "draft",
                "time_range": time_range,
                "rhythm_mood": "紧张" if index == 2 else "舒缓" if index in [0, 4] else "推进",
            },
        )
    return shots


async def generate_shots(
    scene_title: str,
    scene_summary: str,
    scene_dialogue: list[dict[str, str]],
    scene_mood: str,
    shot_count_hint: int = 4,
    duration_budget_seconds: int = 40,
    style: str = "cinematic",
    api_key: str | None = None,
    character_profiles: str | None = None,
    scene_characters: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Break down a scene into individual shots."""
    cleaned_summary = _clean_text(scene_summary)
    if not cleaned_summary:
        raise ValueError("Scene summary is empty")

    if api_key:
        # 注入角色上下文
        character_context = ""
        if character_profiles:
            character_context += f"角色外貌描述：{character_profiles[:500]}\n"
        if scene_characters:
            character_context += f"出场角色：{json.dumps(scene_characters, ensure_ascii=False)}\n"

        prompt = f"""请把下面这个场次拆解成可执行的视频镜头列表。

要求：
1. 只输出 JSON 对象，格式必须为 {{"shots": [{{...}}]}}。
2. 每个 shot 必须包含以下字段（严格按此列表输出，不可省略）：
   shot_number, title, shot_type, camera_angle, camera_movement, composition,
   action_description, dialogue, sound_design, duration_seconds,
   storyboard_prompt, video_prompt, negative_prompt, continuity_notes,
   character_involvement, scene_mood, status,
   focal_length, lighting, color_palette, transition, action_segments, frame_composition
3. 镜头数量控制在 {shot_count_hint} 个左右。
4. 总时长预算约 {duration_budget_seconds} 秒。
5. 风格要求：{style}。
6. 每个镜头都必须服务于剧情推进，不能输出空泛占位描述。
7. shot_type 使用：{json.dumps(SHOT_TYPES, ensure_ascii=False)}。
8. focal_length 使用：{json.dumps(FOCAL_LENGTHS, ensure_ascii=False)}。
9. lighting 使用：{json.dumps(LIGHTING_SETUPS, ensure_ascii=False)}。
10. color_palette 使用：{json.dumps(COLOR_PALETTES, ensure_ascii=False)}。
11. transition 为转场方式，使用：{json.dumps(TRANSITION_TYPES, ensure_ascii=False)}。
12. action_segments 描述镜头内动作的起承转合分段，以分号分隔。
13. frame_composition 描述画面构图（主体位置、视觉引导线、前景/背景关系）。
14. status 统一返回 draft。

场次标题：{scene_title}
场次情绪：{scene_mood}
场次摘要：{cleaned_summary}
对白：{scene_dialogue}
{character_context}"""
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
            async with httpx.AsyncClient(timeout=300) as client:
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
        focal_length = _clean_text(shot_info.get("focal_length")) or "standard"
        lighting = _clean_text(shot_info.get("lighting")) or "natural"
        color_palette = _clean_text(shot_info.get("color_palette")) or "neutral"
        transition = _clean_text(shot_info.get("transition")) or "cut"
        action_segments = _clean_text(shot_info.get("action_segments")) or "完整动作段落"
        frame_composition = _clean_text(shot_info.get("frame_composition")) or "主体位置居中"

        prompt = f"""请为一个视频镜头生成专业分镜提示词。

【分镜提示词生成框架】
请按照以下4大模块结构化生成提示词：

一、场景氛围设定（Scene Atmosphere）
- 建立场景全景定调：地点、时间、天气、光影氛围
- 确定视觉风格：3D动画/写实/赛博朋克/奇幻等
- 色彩基调：冷暖对比、饱和度、主色调

二、角色一致性控制（Character Consistency）
- 角色外貌描述：体型、面部特征、发型、年龄
- 服装细节：款式、颜色、材质、配饰
- 角色姿态：站姿、动作、表情
- 三视图参考：前视图、侧视图、后视图（确保跨镜头一致）

三、镜头分解表（Shot Breakdown Table）
每个镜头必须包含：
- 时间轴：0s-3s、3s-6s 等精确分段
- 景别：全景/中景/近景/特写
- 运镜方式：固定/推/拉/摇/移/跟/环绕
- 内容描述：角色动作、环境互动、剧情推进
- 音效设计：环境声、动作音效、情绪音乐
- 节奏曲线：紧张/舒缓/高潮/转折

四、视频规格标注（Video Specifications）
- 模型适配：{provider}
- 画面比例：16:9
- 渲染风格：3D CG/写实/动画
- 光影风格：史诗级/柔和/戏剧性
- 核心提示：保持角色一致性、画面质量、无文字错乱

【结构化生产字段】
镜头类型：{shot_type}
机位角度：{camera_angle}
运镜方式：{camera_movement}
焦段：{focal_length}
光线设置：{lighting}
色调：{color_palette}
转场方式：{transition}
动作分段：{action_segments}
画面构图：{frame_composition}

动作描述：{action_description}
连续性要求：{continuity}
整体风格：{style}

【输出格式】
请输出 JSON 格式，包含以下字段：
{{
  "scene_atmosphere": "场景氛围描述",
  "character_consistency": "角色一致性要点",
  "shot_breakdown": [
    {{
      "time_range": "0s-3s",
      "shot_type": "全景",
      "camera_movement": "缓慢推进",
      "content_description": "详细内容描述",
      "sound_design": "音效设计",
      "rhythm_mood": "情绪氛围"
    }}
  ],
  "video_specs": "视频规格说明",
  "storyboard_prompt": "完整分镜提示词（英文）",
  "video_prompt": "视频生成提示词（英文，含动作和运镜）",
  "negative_prompt": "负面提示词（英文）"
}}
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
            async with httpx.AsyncClient(timeout=300) as client:
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
                    "negative_prompt": negative_prompt or "blurry, distorted, deformed, low detail, broken anatomy, extra limbs, extra hands, extra feet, six fingers, asymmetric face, merged characters",
                }
        except Exception:
            pass

    focal_length = _clean_text(shot_info.get("focal_length")) or "standard"
    lighting = _clean_text(shot_info.get("lighting")) or "natural"
    color_palette = _clean_text(shot_info.get("color_palette")) or "neutral"
    transition = _clean_text(shot_info.get("transition")) or "cut"
    action_segments = _clean_text(shot_info.get("action_segments")) or "完整动作段落"
    frame_composition = _clean_text(shot_info.get("frame_composition")) or "主体位置居中"

    return {
        "storyboard_prompt": (
            f"{style} storyboard frame, {shot_type} shot, {camera_angle} angle, "
            f"{camera_movement} camera, {focal_length} lens, {lighting} lighting, "
            f"{color_palette} color palette. Composition: {frame_composition}. "
            f"Action: {action_segments}. {action_description}. {continuity}. "
            f"Production-ready frame, clear subject."
        ),
        "video_prompt": (
            f"{style} short film shot, {shot_type} framing, {camera_angle} viewpoint, "
            f"{camera_movement} movement, {focal_length} lens, {lighting} lighting, "
            f"{color_palette} color palette. {transition} transition. "
            f"Action beats: {action_segments}. {action_description}. {continuity}. "
            f"Natural motion, dramatic lighting, high detail, coherent action."
        ),
        "negative_prompt": "blurry, low quality, deformed, duplicated limbs, inconsistent costume, broken motion, extra hands, extra feet, six fingers, asymmetric face, distorted face, merged characters, overlapping body parts, cropped limbs, distorted proportions, split screen, multi panel, text on figure, watermark, label",
    }
