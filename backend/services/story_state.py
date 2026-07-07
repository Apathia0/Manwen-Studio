from __future__ import annotations

import re
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
            compact["must_keep_rules"] = cleaned

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
                compact[key] = cleaned

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
        compact["learned_techniques"] = learned_techniques

    reference_plots = story_bible.get("reference_plots")
    if isinstance(reference_plots, list) and reference_plots:
        compact["reference_plots"] = reference_plots

    reference_rhythm = story_bible.get("reference_rhythm")
    if isinstance(reference_rhythm, dict) and reference_rhythm:
        compact["reference_rhythm"] = reference_rhythm

    reference_emotion_modules = story_bible.get("reference_emotion_modules")
    if isinstance(reference_emotion_modules, dict) and reference_emotion_modules:
        compact["reference_emotion_modules"] = reference_emotion_modules

    reference_author_profile = story_bible.get("reference_author_profile")
    if isinstance(reference_author_profile, dict) and reference_author_profile:
        compact["reference_author_profile"] = reference_author_profile

    reference_author_report = story_bible.get("reference_author_report")
    if isinstance(reference_author_report, str) and reference_author_report.strip():
        compact["reference_author_report"] = extract_report_highlights(reference_author_report)

    reference_style_samples = story_bible.get("reference_style_samples")
    if isinstance(reference_style_samples, list) and reference_style_samples:
        compact["reference_style_samples"] = reference_style_samples

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
                compact[key] = cleaned
    recent_chapter_summaries = story_memory.get("recent_chapter_summaries")
    if isinstance(recent_chapter_summaries, list):
        compact["recent_chapter_summaries"] = [
            item for item in recent_chapter_summaries
            if isinstance(item, dict)
        ]
    long_term = story_memory.get("long_term_foreshadowing")
    if isinstance(long_term, list) and long_term:
        compact["long_term_foreshadowing"] = long_term
    volume_summaries = story_memory.get("volume_summaries")
    if isinstance(volume_summaries, list) and volume_summaries:
        compact["volume_summaries"] = volume_summaries
    snapshots = story_memory.get("character_state_snapshots")
    if isinstance(snapshots, list) and snapshots:
        compact["character_state_snapshots"] = snapshots
    return compact


def extract_author_profile_sections(profile: dict) -> list[str]:
    import json
    parts: list[str] = []
    routine_cards = profile.get("routine_cards")
    if isinstance(routine_cards, list) and routine_cards:
        parts.append(f"可复用写作套路: {json.dumps(routine_cards, ensure_ascii=False)}")
    writing_guide = profile.get("writing_guide")
    if isinstance(writing_guide, dict) and writing_guide:
        parts.append(f"作者写作指南: {json.dumps(writing_guide, ensure_ascii=False)}")
    rhythm_profile = profile.get("rhythm_profile")
    if isinstance(rhythm_profile, dict) and rhythm_profile:
        rhythm_summary = {
            k: v for k, v in rhythm_profile.items()
            if v and k in ("opening_hook", "chapter_end_hooks", "emotion_cycle", "info_release_pattern")
        }
        if rhythm_summary:
            parts.append(f"参考节奏控制: {json.dumps(rhythm_summary, ensure_ascii=False)}")
    style_profile = profile.get("style_profile")
    if isinstance(style_profile, dict) and style_profile:
        parts.append(f"作者风格画像: {json.dumps(style_profile, ensure_ascii=False)}")
    return parts


def extract_report_highlights(report: str) -> str:
    sections = re.split(r'^(#{1,3}\s.+)$', report, flags=re.MULTILINE)
    chunks: list[str] = []
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        body = sections[i + 1].strip() if i + 1 < len(sections) else ""
        bullets = [line.strip() for line in body.split('\n') if line.strip().startswith('*') or line.strip().startswith('-')]
        if bullets:
            chunks.append(f"{heading}\n" + "\n".join(bullets[:3]))
        elif body:
            chunks.append(f"{heading}\n{body[:200]}")
    result = "\n\n".join(chunks)
    return result if result else report
