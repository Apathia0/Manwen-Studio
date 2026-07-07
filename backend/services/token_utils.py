"""Token 估算与智能压缩工具。

当前模型为 DeepSeek V4，支持 1M 上下文 Token。
当 prompt 总量接近或超过 1M Token 时，自动启用智能压缩，
保留关键信息，避免直接截断导致上下文丢失。

核心原则：
1. 正常情况下不做任何截断，保留完整上下文
2. 当总 prompt Token 超过阈值（900K）时，按优先级压缩低优先级字段
3. 压缩策略为"保留关键字段、移除冗余描述"，不是简单字符截断
4. 对话历史压缩使用 AI 摘要，确保记忆不丢失
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# DeepSeek V4 上下文窗口：1M Token
TOKEN_LIMIT = 1_000_000

# 压缩触发阈值：900K Token（留 100K 给 output）
TOKEN_COMPRESS_THRESHOLD = 900_000

# 安全阈值：950K Token（超过则强制激进压缩）
TOKEN_FORCE_COMPRESS_THRESHOLD = 950_000


# ─── Token 估算 ────────────────────────────────────────────


def estimate_tokens(text: str | None) -> int:
    """估算文本的 Token 数。

    DeepSeek V4 使用 BPE tokenizer，近似估算：
    - 中文字符（CJK）：约 1.5 token/字
    - ASCII 字符：约 0.25 token/字符（4 字符 ≈ 1 token）
    - 其他 Unicode：约 0.5 token/字符
    """
    if not text:
        return 0
    chinese_chars = 0
    ascii_chars = 0
    other_chars = 0
    for c in text:
        code = ord(c)
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            chinese_chars += 1
        elif code < 128:
            ascii_chars += 1
        else:
            other_chars += 1
    return int(chinese_chars * 1.5 + ascii_chars * 0.25 + other_chars * 0.5)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算 messages 数组的总 Token 数（含每条消息的 overhead）。"""
    total = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        # 每条消息约 4 token overhead（role + 结构标记）
        total += 4
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    total += estimate_tokens(str(item.get("text", "")))
                else:
                    total += estimate_tokens(str(item))
        # tool_calls 的 token
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    total += estimate_tokens(str(func.get("name", "")))
                    total += estimate_tokens(str(func.get("arguments", "")))
    return total


def should_compress_text(text: str | None, threshold: int = TOKEN_COMPRESS_THRESHOLD) -> bool:
    """判断文本是否需要压缩。"""
    return estimate_tokens(text) > threshold


def should_compress_messages(
    messages: list[dict], threshold: int = TOKEN_COMPRESS_THRESHOLD
) -> bool:
    """判断 messages 数组是否需要压缩。"""
    return estimate_messages_tokens(messages) > threshold


# ─── 智能压缩函数 ──────────────────────────────────────────


def compress_outline(outline: dict | None, current_chapter_number: int | None = None) -> dict:
    """压缩 outline，保留当前幕 + 前后幕的完整章节，其他幕只保留标题和摘要。

    这不是简单截断，而是按叙事结构优先级保留关键章节信息：
    - 当前章节所在幕 + 前 1 幕 + 后 1 幕：保留完整章节卡
    - 更远的幕：只保留章节号和标题（骨架导航）
    - 元数据（themes/foreshadowing/serial_strategy）：始终保留
    """
    if not isinstance(outline, dict):
        return {}
    result: dict[str, Any] = {}
    # 保留元数据字段
    for key in ("themes", "foreshadowing", "serial_strategy"):
        value = outline.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    # 压缩 three_acts
    acts = outline.get("three_acts")
    if not isinstance(acts, list):
        return result

    # 定位当前章节所在幕
    current_act: int | None = None
    if isinstance(current_chapter_number, int):
        for act in acts:
            if not isinstance(act, dict):
                continue
            chapters = act.get("chapters", [])
            if not isinstance(chapters, list):
                continue
            for ch in chapters:
                if isinstance(ch, dict) and ch.get("chapter_number") == current_chapter_number:
                    act_val = act.get("act")
                    if isinstance(act_val, int):
                        current_act = act_val
                    elif isinstance(act_val, str) and act_val.isdigit():
                        current_act = int(act_val)
                    break
            if current_act is not None:
                break

    compressed_acts = []
    for act in acts:
        if not isinstance(act, dict):
            continue
        act_number = act.get("act")
        act_num: int | None = None
        if isinstance(act_number, int):
            act_num = act_number
        elif isinstance(act_number, str) and act_number.isdigit():
            act_num = int(act_number)

        # 当前幕 + 前 1 幕 + 后 1 幕保留完整章节
        if current_act is not None and act_num is not None:
            if abs(act_num - current_act) <= 1:
                compressed_acts.append(act)
                continue

        # 更远的幕：只保留骨架
        compressed_act: dict[str, Any] = {
            "act": act.get("act"),
            "title": act.get("title", ""),
            "summary": act.get("summary", ""),
            "chapters": [
                {
                    "chapter_number": ch.get("chapter_number"),
                    "title": ch.get("title", ""),
                    "act": ch.get("act", ""),
                }
                for ch in (act.get("chapters") or [])
                if isinstance(ch, dict)
            ],
        }
        compressed_acts.append(compressed_act)

    result["three_acts"] = compressed_acts
    return result


def compress_characters(characters: list | None, keep_full: int = 8) -> list:
    """压缩角色列表，前 keep_full 个角色保留完整信息，其他角色只保留基本信息。

    策略：主角和主要配角（通常前 5-8 个）保留完整 arc/relationships/background，
    次要角色只保留 name/role/appearance/personality（出场时仍可识别）。
    """
    if not isinstance(characters, list):
        return []
    result = []
    for i, char in enumerate(characters):
        if not isinstance(char, dict):
            continue
        if i < keep_full:
            result.append(char)
        else:
            # 次要角色只保留基本信息
            compact_char: dict[str, Any] = {
                "name": char.get("name", ""),
                "role": char.get("role", ""),
            }
            for key in ("appearance", "personality", "motivation"):
                value = char.get(key)
                if value:
                    compact_char[key] = value
            result.append(compact_char)
    return result


def compress_reference_fields(story_bible: dict | None) -> dict:
    """压缩 story_bible 中的 reference_*（拆书引用）字段。

    按信息优先级压缩：
    - reference_style_samples: 保留前 2 个样本，每个文本截断到 2000 字符
    - reference_rhythm: 只保留关键节奏字段（opening_hook/chapter_end_hooks 等）
    - reference_emotion_modules: 保留键名，值压缩到 500 字符
    - reference_author_profile: 保留 routine_cards[:3] + writing_guide 核心字段
    - reference_author_report: 已有 extract_report_highlights 处理
    - learned_techniques / reference_plots: 保留前 5/3 条
    """
    if not isinstance(story_bible, dict):
        return {}
    updates: dict[str, Any] = {}

    # reference_style_samples: 保留前 2 个，每个截断到 2000 字符
    samples = story_bible.get("reference_style_samples")
    if isinstance(samples, list) and samples:
        compressed_samples = []
        for sample in samples[:2]:
            if isinstance(sample, str):
                compressed_samples.append(sample[:2000])
            elif isinstance(sample, dict):
                compact_sample: dict[str, Any] = {}
                for k, v in sample.items():
                    if isinstance(v, str):
                        compact_sample[k] = v[:2000]
                    else:
                        compact_sample[k] = v
                compressed_samples.append(compact_sample)
        updates["reference_style_samples"] = compressed_samples

    # reference_rhythm: 只保留关键节奏字段
    rhythm = story_bible.get("reference_rhythm")
    if isinstance(rhythm, dict) and rhythm:
        updates["reference_rhythm"] = {
            k: v for k, v in rhythm.items()
            if k in ("opening_hook", "chapter_end_hooks", "emotion_cycle", "info_release_pattern")
            and v
        }

    # reference_emotion_modules: 保留键名，值压缩到 500 字符
    emotions = story_bible.get("reference_emotion_modules")
    if isinstance(emotions, dict) and emotions:
        updates["reference_emotion_modules"] = {
            k: (v[:500] if isinstance(v, str) else str(v)[:500])
            for k, v in emotions.items()
        }

    # reference_author_profile: 保留 routine_cards[:3] + writing_guide 核心字段
    profile = story_bible.get("reference_author_profile")
    if isinstance(profile, dict) and profile:
        compact_profile: dict[str, Any] = {}
        routine_cards = profile.get("routine_cards")
        if isinstance(routine_cards, list):
            compact_profile["routine_cards"] = routine_cards[:3]
        writing_guide = profile.get("writing_guide")
        if isinstance(writing_guide, dict):
            compact_profile["writing_guide"] = {
                k: v for k, v in writing_guide.items()
                if k in ("opening_strategy", "midgame_engine", "late_game_direction")
                and v
            }
        style_profile = profile.get("style_profile")
        if isinstance(style_profile, dict):
            compact_profile["style_profile"] = style_profile
        rhythm_profile = profile.get("rhythm_profile")
        if isinstance(rhythm_profile, dict):
            compact_profile["rhythm_profile"] = {
                k: v for k, v in rhythm_profile.items()
                if k in ("opening_hook", "chapter_end_hooks", "emotion_cycle", "info_release_pattern")
                and v
            }
        updates["reference_author_profile"] = compact_profile

    # learned_techniques: 保留前 5 条
    learned = story_bible.get("learned_techniques")
    if isinstance(learned, list) and learned:
        updates["learned_techniques"] = learned[:5]

    # reference_plots: 保留前 3 条
    ref_plots = story_bible.get("reference_plots")
    if isinstance(ref_plots, list) and ref_plots:
        updates["reference_plots"] = ref_plots[:3]

    return updates


def compress_story_bible(story_bible: dict | None) -> dict:
    """全面压缩 story_bible，保留核心字段，移除冗余描述。

    优先级：creative_brief > writing_guidance > import_guidance > reference_*
    """
    if not isinstance(story_bible, dict):
        return {}
    result = dict(story_bible)

    # 压缩 reference_* 字段
    ref_updates = compress_reference_fields(result)
    result.update(ref_updates)

    # 压缩 creative_brief（保留核心叙事字段，移除长描述）
    creative_brief = result.get("creative_brief")
    if isinstance(creative_brief, dict):
        core_brief: dict[str, Any] = {}
        for key in (
            "project_positioning", "one_line_premise", "core_hook",
            "protagonist_core", "main_conflict", "longline_mystery",
            "world_setting", "must_keep_rules", "open_story_notes",
            "reveal_strategy", "pacing_strategy", "serial_length_target",
        ):
            value = creative_brief.get(key)
            if value not in (None, "", [], {}):
                core_brief[key] = value
        result["creative_brief"] = core_brief

    # 压缩 writing_guidance（保留核心策略字段）
    writing_guidance = result.get("writing_guidance")
    if isinstance(writing_guidance, dict):
        core_guidance: dict[str, Any] = {}
        for key in (
            "opening_strategy", "midgame_engine", "late_game_direction",
            "forbidden_patterns", "preferred_plot_patterns",
            "chapter_density_strategy",
        ):
            value = writing_guidance.get(key)
            if value not in (None, "", [], {}):
                core_guidance[key] = value
        result["writing_guidance"] = core_guidance

    # 压缩 open_story_notes（限制到 1000 字符）
    open_notes = result.get("open_story_notes")
    if isinstance(open_notes, str) and len(open_notes) > 1000:
        result["open_story_notes"] = open_notes[:1000]

    return result


def compress_story_memory(story_memory: dict | None) -> dict:
    """全面压缩 story_memory，保留核心连续性信息。

    压缩策略：
    - 单值字段（story_state 等）：始终保留
    - 列表字段：保留最近 N 条（比 compact 版更激进）
    - recent_chapter_summaries: 最近 5 章（compact 版是 8 章）
    - long_term_foreshadowing: 最近 30 条（compact 版是 100 条）
    """
    if not isinstance(story_memory, dict):
        return {}
    result: dict[str, Any] = {}

    # 保留单值字段
    for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
        value = story_memory.get(key)
        if value:
            result[key] = value

    # 列表字段保留最近 N 条
    for key in ("continuity_facts", "open_loops", "resolved_loops"):
        raw = story_memory.get(key)
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            result[key] = cleaned[:8]

    # recent_chapter_summaries: 保留最近 5 章
    recent = story_memory.get("recent_chapter_summaries")
    if isinstance(recent, list):
        result["recent_chapter_summaries"] = recent[-5:]

    # long_term_foreshadowing: 保留最近 30 条
    long_term = story_memory.get("long_term_foreshadowing")
    if isinstance(long_term, list):
        result["long_term_foreshadowing"] = long_term[-30:]

    # character_state_snapshots: 保留最近 3 个
    snapshots = story_memory.get("character_state_snapshots")
    if isinstance(snapshots, list):
        result["character_state_snapshots"] = snapshots[-3:]

    # volume_summaries: 保留
    volume = story_memory.get("volume_summaries")
    if isinstance(volume, list):
        result["volume_summaries"] = volume

    return result


# ─── 对话历史压缩 ──────────────────────────────────────────


def split_messages_for_compression(
    messages: list[dict], keep_recent: int = 20
) -> tuple[list[dict], list[dict]]:
    """将 messages 分割为 (需要压缩的旧消息, 保留的最近消息)。

    保留最近 keep_recent 条消息不压缩，确保近期上下文完整。
    其余旧消息将被 AI 压缩为一条摘要消息。
    """
    if len(messages) <= keep_recent:
        return [], messages
    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]
    return old_messages, recent_messages


def build_history_summary_prompt(old_messages: list[dict]) -> str:
    """构建对话历史压缩的 user prompt。

    将旧消息序列化为文本，要求 AI 提取关键信息生成摘要。
    """
    history_text = ""
    for msg in old_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # 处理 content 为数组的情况（如 multimodal messages）
            content = " ".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        # 限制单条消息长度，避免历史文本本身过长
        if len(content) > 3000:
            content = content[:3000] + "..."
        history_text += f"[{role}]: {content}\n\n"

    return f"""请将以下对话历史压缩为一条简洁的结构化摘要，保留所有关键信息：

1. 讨论的核心主题和目标
2. 做出的重要决定和修改
3. 涉及的角色、章节、情节点
4. 用户明确表达的偏好和要求
5. 当前任务的进展状态
6. 未解决的问题和待办事项
7. AI 调用的工具和结果摘要

对话历史：
{history_text}

请输出一份结构化摘要（中文），不超过 2000 字。直接输出摘要内容，不要包含其他说明。"""


def build_history_summary_system_prompt() -> str:
    """构建对话历史压缩的 system prompt。"""
    return (
        "你是一个对话历史压缩助手。你的任务是将长对话历史压缩为简洁的结构化摘要，"
        "确保压缩后的摘要保留所有关键信息，包括：讨论主题、决定、修改内容、用户偏好、"
        "任务进展、未解决问题等。摘要应该足够详细，让 AI 助手在阅读后能无缝继续对话。"
    )


# ─── 通用压缩入口 ──────────────────────────────────────────


def compress_context_parts_if_needed(
    parts: list[str],
    full_context: dict | None = None,
    current_chapter_number: int | None = None,
) -> list[str]:
    """当 parts 拼接后的 token 超过阈值时，按优先级压缩各部分。

    Args:
        parts: 文本片段列表（如 _build_framework_context 的输出）
        full_context: 完整的 story_context dict（含 outline/characters/story_bible 等），
                      用于智能压缩。如果为 None 则只做文本级压缩。
        current_chapter_number: 当前章节号，用于 outline 压缩时定位当前幕

    Returns:
        压缩后的 parts（如果未超限则原样返回）
    """
    full_text = "\n".join(parts)
    if estimate_tokens(full_text) <= TOKEN_COMPRESS_THRESHOLD:
        return parts

    logger.info(
        "上下文 token 估算 %d 超过阈值 %d，启用智能压缩",
        estimate_tokens(full_text),
        TOKEN_COMPRESS_THRESHOLD,
    )

    # 如果有完整 context，使用结构化压缩
    if full_context and isinstance(full_context, dict):
        compressed_parts = _apply_structured_compression(
            parts, full_context, current_chapter_number
        )
        compressed_text = "\n".join(compressed_parts)
        if estimate_tokens(compressed_text) <= TOKEN_COMPRESS_THRESHOLD:
            return compressed_parts
        # 如果仍然超限，启用激进压缩
        logger.warning("结构化压缩后仍超限，启用激进压缩")
        return _apply_aggressive_compression(compressed_parts)

    # 无完整 context，启用文本级压缩
    return _apply_aggressive_compression(parts)


def _apply_structured_compression(
    parts: list[str],
    full_context: dict,
    current_chapter_number: int | None = None,
) -> list[str]:
    """使用结构化信息进行智能压缩。"""
    import json as _json

    compressed = list(parts)

    # 优先级 1：压缩 outline（如果有完整 outline JSON）
    outline = full_context.get("outline")
    if isinstance(outline, dict) and outline:
        compressed_outline = compress_outline(outline, current_chapter_number)
        outline_json = _json.dumps(compressed_outline, ensure_ascii=False)
        for i, part in enumerate(compressed):
            if "故事大纲" in part and _json.dumps(outline, ensure_ascii=False) in part:
                compressed[i] = part.replace(
                    _json.dumps(outline, ensure_ascii=False),
                    outline_json,
                )
                break

    # 优先级 2：压缩 characters
    characters = full_context.get("characters")
    if isinstance(characters, list) and characters:
        compressed_chars = compress_characters(characters)
        chars_json = _json.dumps(compressed_chars, ensure_ascii=False)
        original_chars_json = _json.dumps(characters, ensure_ascii=False)
        for i, part in enumerate(compressed):
            if "角色设定" in part and original_chars_json in part:
                compressed[i] = part.replace(original_chars_json, chars_json)
                break

    # 优先级 3：压缩 story_bible 中的 reference_* 字段
    story_bible = full_context.get("story_bible")
    if isinstance(story_bible, dict) and story_bible:
        ref_updates = compress_reference_fields(story_bible)
        for field, compressed_value in ref_updates.items():
            original_value = story_bible.get(field)
            if original_value is None:
                continue
            original_json = _json.dumps(original_value, ensure_ascii=False)
            compressed_json = _json.dumps(compressed_value, ensure_ascii=False)
            for i, part in enumerate(compressed):
                if original_json in part and len(original_json) > len(compressed_json):
                    compressed[i] = part.replace(original_json, compressed_json)

    return compressed


def _apply_aggressive_compression(parts: list[str]) -> list[str]:
    """激进压缩：移除最大的片段中的详细描述，只保留关键信息。"""
    # 找到最大的几个片段，尝试压缩
    indexed = sorted(enumerate(parts), key=lambda x: len(x[1]), reverse=True)
    compressed = list(parts)
    for idx, part in indexed[:3]:  # 只处理最大的 3 个片段
        if estimate_tokens(part) > 5000:
            # 保留片段的前 2000 字符 + "..."
            if len(part) > 2000:
                compressed[idx] = part[:2000] + "\n...（已压缩）"
    return compressed
