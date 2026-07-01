from __future__ import annotations

from copy import deepcopy
from typing import Any


def _is_plain_dict(value: Any) -> bool:
    return isinstance(value, dict)


def deep_merge_dict(existing: dict | None, update: dict | None) -> dict:
    base = deepcopy(existing) if isinstance(existing, dict) else {}
    incoming = update if isinstance(update, dict) else {}
    for key, value in incoming.items():
        if _is_plain_dict(value) and _is_plain_dict(base.get(key)):
            base[key] = deep_merge_dict(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def deep_merge_story_bible(existing: dict | None, update: dict | None) -> dict:
    return deep_merge_dict(existing, update)


async def refresh_chapter_memory_for_content(
    *,
    chapter,
    api_key: str | None,
    story_context_func,
    summarize_chapter_memory_func,
    merge_story_memory_func,
) -> bool:
    if not chapter.novel_content or not chapter.novel_content.strip():
        return False

    chapter_info = {
        "chapter_number": chapter.chapter_number,
        "title": chapter.title or f"第{chapter.chapter_number}话",
        "act": chapter.act or "",
        "key_events": chapter.key_events or [],
    }
    story_context = story_context_func(chapter.story)
    novel_content = chapter.novel_content

    try:
        memory_payload = await summarize_chapter_memory_func(
            story_context,
            chapter_info,
            novel_content,
            api_key=api_key,
        )
    except Exception:
        return False

    chapter_summary = memory_payload.get("chapter_summary") if isinstance(memory_payload.get("chapter_summary"), dict) else {}
    chapter_handoff = memory_payload.get("chapter_handoff") if isinstance(memory_payload.get("chapter_handoff"), dict) else {}
    story_memory_update = memory_payload.get("story_memory_update") if isinstance(memory_payload.get("story_memory_update"), dict) else {}

    chapter.memory_summary = {
        "chapter_summary": chapter_summary,
        "chapter_handoff": chapter_handoff,
        "summary": chapter_summary.get("summary"),
        "ending_scene": chapter_summary.get("ending_scene"),
    } if (chapter_summary or chapter_handoff) else None

    chapter.story.story_memory = merge_story_memory_func(
        chapter.story.story_memory,
        story_memory_update,
        chapter,
        chapter_summary,
    )
    return True


def build_story_bible_compact(story_bible: dict | None) -> dict[str, Any]:
    """构建作品圣经的精简版，移除非关键字段。与原 main._build_story_bible_compact 行为完全一致。"""
    if not isinstance(story_bible, dict):
        return {}
    creative_brief = story_bible.get("creative_brief") if isinstance(story_bible.get("creative_brief"), dict) else {}
    raw_input = story_bible.get("raw_input") if isinstance(story_bible.get("raw_input"), dict) else {}
    writing_guidance = story_bible.get("writing_guidance") if isinstance(story_bible.get("writing_guidance"), dict) else {}
    import_guidance = story_bible.get("import_guidance") if isinstance(story_bible.get("import_guidance"), dict) else {}

    compact: dict[str, Any] = {}
    for key in (
        "project_positioning",
        "one_line_premise",
        "core_hook",
        "protagonist_core",
        "main_conflict",
        "longline_mystery",
        "serial_length_target",
        "reveal_strategy",
        "pacing_strategy",
        "world_setting",
        "open_story_notes",
    ):
        value = str(creative_brief.get(key) or "").strip()
        if value:
            compact[key] = value

    must_keep_rules = creative_brief.get("must_keep_rules")
    if isinstance(must_keep_rules, list):
        cleaned = [str(item).strip() for item in must_keep_rules if str(item).strip()]
        if cleaned:
            compact["must_keep_rules"] = cleaned[:8]

    for key in (
        "opening_strategy",
        "chapter_density_strategy",
        "midgame_engine",
        "late_game_direction",
    ):
        value = str(writing_guidance.get(key) or "").strip()
        if value:
            compact[key] = value

    for key in ("forbidden_patterns", "preferred_plot_patterns"):
        raw = writing_guidance.get(key)
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            if cleaned:
                compact[key] = cleaned[:8]

    for key in ("raw_idea", "raw_length_goal", "raw_must_keep", "raw_hidden_setting"):
        value = str(raw_input.get(key) or "").strip()
        if value:
            compact[key] = value

    for key in (
        "import_material_type",
        "must_keep",
        "author_goal",
        "adjustment_scope",
        "longline_plan",
        "tone_guardrails",
    ):
        value = str(import_guidance.get(key) or "").strip()
        if value:
            compact[f"import_{key}"] = value

    # 拆书引用数据：让 AI 可以参考已拆书作品的写作手法和剧情模式
    learned_techniques = story_bible.get("learned_techniques")
    if isinstance(learned_techniques, list) and learned_techniques:
        compact["learned_techniques"] = learned_techniques[:10]

    reference_plots = story_bible.get("reference_plots")
    if isinstance(reference_plots, list) and reference_plots:
        compact["reference_plots"] = reference_plots[:5]

    reference_rhythm = story_bible.get("reference_rhythm")
    if isinstance(reference_rhythm, dict) and reference_rhythm:
        compact["reference_rhythm"] = reference_rhythm

    reference_emotion_modules = story_bible.get("reference_emotion_modules")
    if isinstance(reference_emotion_modules, dict) and reference_emotion_modules:
        compact["reference_emotion_modules"] = reference_emotion_modules

    # 拆书作品概要（多个引用时合并）
    decon_titles = []
    for key, value in story_bible.items():
        if key.startswith("deconstruction_") and isinstance(value, dict):
            title = value.get("title")
            if title:
                decon_titles.append(title)
    if decon_titles:
        compact["referenced_deconstruction_works"] = decon_titles

    return compact


def build_story_memory_compact(story_memory: dict | None) -> dict[str, Any]:
    """构建连续性记忆的精简版，保留 recent_chapter_summaries。与原 main._build_story_memory_compact 行为完全一致。"""
    if not isinstance(story_memory, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
        value = str(story_memory.get(key) or "").strip()
        if value:
            compact[key] = value
    for key in ("continuity_facts", "open_loops", "resolved_loops"):
        raw = story_memory.get(key)
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            if cleaned:
                compact[key] = cleaned[:12]
    recent_chapter_summaries = story_memory.get("recent_chapter_summaries")
    if isinstance(recent_chapter_summaries, list):
        compact["recent_chapter_summaries"] = [
            item for item in recent_chapter_summaries[-8:]
            if isinstance(item, dict)
        ]
    return compact
