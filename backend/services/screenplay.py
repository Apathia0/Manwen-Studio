"""Service layer for screenplay generation."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import deepseek as deepseek_service
from .errors import MissingApiKeyError


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _chunk_sentences(content: str, chunk_count: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", content) if part.strip()]
    if not paragraphs:
        paragraphs = [part.strip() for part in re.split(r"(?<=[。！？!?])", content) if part.strip()]
    if not paragraphs:
        return []

    chunk_count = max(1, min(chunk_count, len(paragraphs)))
    chunk_size = max(1, len(paragraphs) // chunk_count)
    chunks: list[str] = []

    for start in range(0, len(paragraphs), chunk_size):
        piece = " ".join(paragraphs[start : start + chunk_size]).strip()
        if piece:
            chunks.append(piece)

    if len(chunks) > chunk_count:
        head = chunks[: chunk_count - 1]
        tail = " ".join(chunks[chunk_count - 1 :]).strip()
        chunks = [*head, tail]

    return chunks[:chunk_count]


def _infer_location(text: str) -> str:
    candidates = [
        ("学校", ["教室", "操场", "宿舍", "图书馆", "学校"]),
        ("医院", ["病房", "医院", "诊室"]),
        ("街道", ["街道", "巷子", "马路", "路口"]),
        ("家中", ["家里", "客厅", "卧室", "厨房"]),
        ("山林", ["树林", "山谷", "荒野", "森林"]),
        ("办公室", ["会议室", "办公室", "公司"]),
    ]
    for label, keywords in candidates:
        if any(keyword in text for keyword in keywords):
            return label
    return "未明确地点"


def _infer_time_of_day(text: str) -> str:
    mapping = [
        ("夜", ["深夜", "夜里", "夜色", "月光", "凌晨"]),
        ("黄昏", ["黄昏", "傍晚", "夕阳"]),
        ("清晨", ["清晨", "黎明", "天亮", "晨光"]),
    ]
    for label, keywords in mapping:
        if any(keyword in text for keyword in keywords):
            return label
    return "白天"


def _extract_characters(text: str) -> list[str]:
    names = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    results: list[str] = []
    for name in names:
      if name in {"他们", "她们", "这里", "那里", "自己", "已经", "开始", "时候", "因为", "如果", "没有"}:
          continue
      if name not in results:
          results.append(name)
      if len(results) >= 4:
          break
    return results


def _build_fallback_scene(index: int, chunk: str, duration_seconds: int) -> dict[str, Any]:
    summary = _clean_text(chunk)
    title_source = re.split(r"[，。；！？!?]", summary, maxsplit=1)[0].strip() or f"场景 {index}"
    title = title_source[:14]
    characters = _extract_characters(summary)
    return {
        "scene_number": index,
        "title": title or f"场景 {index}",
        "location": _infer_location(summary),
        "time_of_day": _infer_time_of_day(summary),
        "characters": characters,
        "summary": summary,
        "dialogue": [],
        "voiceover": "",
        "mood": "紧张" if any(token in summary for token in ["冲突", "危险", "追", "杀", "惊"]) else "叙事推进",
        "estimated_duration_seconds": duration_seconds,
    }


def _build_fallback_screenplay(chapter_content: str, scene_count_hint: int, target_duration_seconds: int) -> dict[str, Any]:
    chunks = _chunk_sentences(chapter_content, scene_count_hint) or [chapter_content.strip()]
    duration = max(8, target_duration_seconds // max(1, len(chunks)))
    scenes = [
        _build_fallback_scene(index + 1, chunk, duration)
        for index, chunk in enumerate(chunks)
    ]
    screenplay = "\n\n".join(
        [
            f"【场次{scene['scene_number']}】{scene['location']} / {scene['time_of_day']}\n"
            f"人物：{('、'.join(scene['characters']) if scene['characters'] else '待补充')}\n"
            f"剧情：{scene['summary']}"
            for scene in scenes
        ],
    )
    return {"screenplay": screenplay, "scenes": scenes}


def _normalize_scene(raw_scene: dict[str, Any], index: int, default_duration: int) -> dict[str, Any]:
    summary = _clean_text(raw_scene.get("summary")) or f"场次 {index} 的剧情推进。"
    location = _clean_text(raw_scene.get("location")) or _infer_location(summary)
    time_of_day = _clean_text(raw_scene.get("time_of_day")) or _infer_time_of_day(summary)
    characters = [str(item).strip() for item in (raw_scene.get("characters") or []) if str(item).strip()]
    dialogue = []
    for item in raw_scene.get("dialogue") or []:
        if not isinstance(item, dict):
            continue
        speaker = _clean_text(item.get("speaker"))
        text = _clean_text(item.get("text"))
        if speaker or text:
            dialogue.append({"speaker": speaker or "角色", "text": text})

    return {
        "scene_number": int(raw_scene.get("scene_number") or index),
        "title": _clean_text(raw_scene.get("title")) or f"场景 {index}",
        "location": location,
        "time_of_day": time_of_day,
        "characters": characters,
        "summary": summary,
        "dialogue": dialogue,
        "voiceover": _clean_text(raw_scene.get("voiceover")),
        "mood": _clean_text(raw_scene.get("mood")) or "叙事推进",
        "estimated_duration_seconds": int(raw_scene.get("estimated_duration_seconds") or default_duration),
    }


async def _generate_screenplay_with_llm(
    chapter_content: str,
    style: str,
    scene_count_hint: int,
    target_duration_seconds: int,
    api_key: str,
    story_memory: dict | None = None,
    chapter_memory_summary: dict | None = None,
    story_outline: dict | None = None,
) -> dict[str, Any]:
    # 注入上下文信息
    context_sections = ""
    if story_memory is not None:
        context_sections += f"故事级连续性记忆：{json.dumps(story_memory, ensure_ascii=False)}\n\n"
    if chapter_memory_summary is not None:
        context_sections += f"本章节记忆摘要：{json.dumps(chapter_memory_summary, ensure_ascii=False)}\n\n"
    if story_outline is not None:
        context_sections += f"故事大纲定位：{json.dumps(story_outline, ensure_ascii=False)}\n\n"

    prompt = f"""请把下面的小说章节内容转换成适合短剧视频生产的影视剧本，并拆成结构化场次。

要求：
1. 只输出一个 JSON 对象，不要输出解释或 Markdown。
2. JSON 格式必须为：
{{
  "screenplay": "完整影视剧本文本",
  "scenes": [
    {{
      "scene_number": 1,
      "title": "场次标题",
      "location": "场景地点",
      "time_of_day": "白天/夜晚/黄昏/清晨",
      "characters": ["角色A", "角色B"],
      "summary": "这一场的剧情概述，包含冲突和推进",
      "dialogue": [{{"speaker": "角色A", "text": "对白"}}],
      "voiceover": "可选旁白",
      "mood": "情绪氛围",
      "estimated_duration_seconds": 18
    }}
  ]
}}
3. 场次数量尽量控制在 {scene_count_hint} 场左右。
4. 总时长目标约 {target_duration_seconds} 秒。
5. 风格要求：{style}。
6. screenplay 字段必须是真正可读的影视剧本文本，不要只重复 summary。
7. scene.summary 必须具体，不允许出现"根据章节内容自动生成"这类占位描述。
8. 如果原文有角色冲突、目标、转折，请体现在场次中。

{context_sections}章节正文：
{chapter_content}
"""

    payload = {
        "model": deepseek_service.DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一名经验丰富的影视编剧和分场编辑，擅长把小说正文转换成短剧可执行剧本。"
                    "你必须输出严格可解析的 JSON。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }

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
    raw_scenes = result.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Screenplay generation returned no scenes")

    default_duration = max(8, target_duration_seconds // max(1, len(raw_scenes)))
    scenes = [
        _normalize_scene(scene, index + 1, default_duration)
        for index, scene in enumerate(raw_scenes)
        if isinstance(scene, dict)
    ]
    screenplay_text = _clean_text(result.get("screenplay"))
    if not screenplay_text:
        screenplay_text = "\n\n".join(
            f"【场次{scene['scene_number']}】{scene['location']} / {scene['time_of_day']}\n剧情：{scene['summary']}"
            for scene in scenes
        )
    return {"screenplay": screenplay_text, "scenes": scenes}


async def generate_screenplay(
    chapter_content: str,
    style: str = "cinematic",
    scene_count_hint: int = 5,
    target_duration_seconds: int = 90,
    api_key: str | None = None,
    story_memory: dict | None = None,
    chapter_memory_summary: dict | None = None,
    story_outline: dict | None = None,
) -> dict[str, Any]:
    """Generate screenplay and scenes from chapter content."""
    cleaned_content = str(chapter_content or "").strip()
    if not cleaned_content:
        raise ValueError("Chapter content is empty")

    try:
        if api_key:
            return await _generate_screenplay_with_llm(
                chapter_content=cleaned_content,
                style=style,
                scene_count_hint=scene_count_hint,
                target_duration_seconds=target_duration_seconds,
                api_key=api_key,
                story_memory=story_memory,
                chapter_memory_summary=chapter_memory_summary,
                story_outline=story_outline,
            )
        raise MissingApiKeyError("DeepSeek")
    except MissingApiKeyError:
        return _build_fallback_screenplay(cleaned_content, scene_count_hint, target_duration_seconds)
    except Exception:
        return _build_fallback_screenplay(cleaned_content, scene_count_hint, target_duration_seconds)


async def regenerate_scenes(
    existing_screenplay: str,
    instruction: str,
    scene_count_hint: int = 4,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Regenerate scenes based on screenplay and user instruction."""
    base_text = str(existing_screenplay or "").strip()
    if not base_text:
        raise ValueError("Screenplay content is empty")

    if api_key:
        prompt = f"""你将收到一段现有影视剧本和一条修改指令，请重新输出场次列表。

要求：
1. 只输出 JSON 对象。
2. 格式必须是 {{"scenes": [{{...}}]}}。
3. 每个 scene 仍然包含 scene_number/title/location/time_of_day/characters/summary/dialogue/voiceover/mood/estimated_duration_seconds。
4. scene.summary 必须具体，不能出现占位文案。
5. 目标场次数量控制在 {scene_count_hint} 场左右。

修改指令：{instruction}

现有剧本：
{base_text}
"""
        payload = {
            "model": deepseek_service.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "你是一名影视分场编辑，只输出严格 JSON。"},
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
            raw_scenes = result.get("scenes")
            if isinstance(raw_scenes, list) and raw_scenes:
                default_duration = 15
                return [
                    _normalize_scene(scene, index + 1, default_duration)
                    for index, scene in enumerate(raw_scenes)
                    if isinstance(scene, dict)
                ]
        except Exception:
            pass

    fallback = _build_fallback_screenplay(base_text, scene_count_hint, scene_count_hint * 15)
    return fallback["scenes"]
