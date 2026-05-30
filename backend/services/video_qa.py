from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _extract_key_terms(text: str) -> set[str]:
    """从文本中提取有意义的特征关键词（去停用词、去标点）。"""
    if not text:
        return set()
    text = re.sub(r"[\u3000-\u303f\uff00-\uffef!\"#\$%&'\(\)\*\+,\-\./:;<=>\?@\[\\\]\^_`\{\|\}~]", " ", text)
    words = text.lower().split()
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare",
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
        "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
        "没有", "看", "好", "自己", "这", "他", "她", "它", "们",
        "with", "from", "that", "this", "these", "those", "and", "or", "but",
        "not", "no", "none", "some", "any", "all", "each", "every", "both",
        "few", "more", "most", "other", "into", "onto", "upon", "about",
    }
    return {w for w in words if len(w) > 1 and w not in stop_words}


def score_character_consistency(
    video_prompt: str,
    character_prompts: list[str],
) -> int:
    """评估视频 prompt 对角色特征的覆盖程度。

    将角色 prompt 中的关键词与视频 prompt 对比，
    返回 0-100 的一致性分数。
    """
    if not video_prompt or not character_prompts:
        return 0
    if not any(cp.strip() for cp in character_prompts):
        return 0

    video_terms = _extract_key_terms(video_prompt)
    if not video_terms:
        return 0

    all_char_terms: set[str] = set()
    for cp in character_prompts:
        all_char_terms |= _extract_key_terms(cp)

    if not all_char_terms:
        return 50

    overlap = video_terms & all_char_terms
    # 计算 Jaccard 相似度，但偏向 recall（角色特征是否被覆盖）
    recall = len(overlap) / len(all_char_terms) if all_char_terms else 0
    precision = len(overlap) / len(video_terms) if video_terms else 0

    # F1 分数转 0-100
    if precision + recall == 0:
        return 0
    f1 = 2 * (precision * recall) / (precision + recall)
    return min(100, int(f1 * 100))


def score_prompt_structure(shot: dict[str, Any]) -> int:
    """评估镜头提示词的结构化完整度。

    检查结构化生产字段是否都有非默认值。
    返回 0-100 的结构化分数。
    """
    structured_fields = [
        "shot_type", "camera_angle", "camera_movement",
        "focal_length", "lighting", "color_palette",
        "transition", "action_segments", "frame_composition",
    ]
    defaults = {
        "shot_type": "medium",
        "camera_angle": "eye_level",
        "camera_movement": "static",
        "focal_length": "standard",
        "lighting": "natural",
        "color_palette": "neutral",
        "transition": "cut",
        "action_segments": "完整动作段落",
        "frame_composition": "主体位置居中",
    }

    filled = 0
    total = len(structured_fields)
    for field in structured_fields:
        value = str(shot.get(field) or "").strip()
        default = defaults.get(field, "")
        if value and value != default:
            filled += 1

    return min(100, int((filled / total) * 100)) if total > 0 else 0


def score_action_alignment(
    action_description: str,
    video_prompt: str,
) -> int:
    """评估动作描述与视频 prompt 的对齐程度。"""
    if not action_description or not video_prompt:
        return 50

    action_terms = _extract_key_terms(action_description)
    video_terms = _extract_key_terms(video_prompt)

    if not action_terms:
        return 50
    if not video_terms:
        return 0

    overlap = video_terms & action_terms
    recall = len(overlap) / len(action_terms) if action_terms else 0
    return min(100, int(recall * 100))


def score_video_shot(
    shot_data: dict[str, Any],
    character_prompts: list[str] | None = None,
) -> dict[str, int]:
    """对一个视频镜头进行全方位质检评分。

    返回包含各维度分数的字典：
    - character_consistency: 角色一致性 0-100
    - prompt_structure: 提示词结构化 0-100
    - action_alignment: 动作对齐 0-100
    - overall: 综合分（加权平均）0-100
    """
    video_prompt = str(shot_data.get("video_prompt") or "").strip()
    action_description = str(shot_data.get("action_description") or "").strip()

    char_score = score_character_consistency(
        video_prompt,
        character_prompts or [],
    )
    struct_score = score_prompt_structure(shot_data)
    action_score = score_action_alignment(action_description, video_prompt)

    # 加权综合：角色一致性权重最高
    overall = int(
        char_score * 0.4 + struct_score * 0.35 + action_score * 0.25
    )

    return {
        "character_consistency": char_score,
        "prompt_structure": struct_score,
        "action_alignment": action_score,
        "overall": overall,
    }


def should_retry(qa_result: dict[str, int], threshold: int = 60) -> bool:
    """判断是否应该因质检分数不足而重试。

    threshold: 综合分低于此值建议重试（默认 60）
    """
    return qa_result.get("overall", 0) < threshold
