import copy
import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any

import httpx

from services.chapter_creation_pack import canonical_pack_content
from services.errors import UpstreamServiceError, WriterEmptyContentError


logger = logging.getLogger(__name__)

EDITOR_PASS_SCORE = 90
LOCAL_MIN_CHARS = 2200
LOCAL_MAX_CHARS = 3000
LOCAL_IDEAL_CHARS = 2500
WRITER_TARGET_MIN_CHARS = 2300
WRITER_TARGET_MAX_CHARS = 2700
WRITER_REVISION_TARGET_MAX_CHARS = 3000
LOCAL_SOFT_MAX_CHARS = LOCAL_MAX_CHARS
SCENE_BUDGET_IDEAL_TOTAL = 2100
SCENE_BUDGET_SOFT_MAX_TOTAL = 2200
SCENE_BUDGET_HARD_MAX_TOTAL = 2480
# 正文 Writer 明确关闭思考模式，全部输出预算用于章节正文。
WRITER_MAX_TOKENS = 8192
WRITER_EMPTY_CONTENT_RETRIES = 1
PLOT_BEATS_MAX = 8
PLOT_BEATS_MIN = 6

_DEFAULT_SCENE_BUDGET: tuple[dict[str, Any], ...] = (
    {"scene": "开场承接与目标压迫", "purpose": "直接承接前文状态，交代本章目标和现实压力，不铺设定", "target_chars": 220, "max_chars": 280},
    {"scene": "入场观察与策略形成", "purpose": "让主角用行动、观察或对话确认问题和解法", "target_chars": 320, "max_chars": 390},
    {"scene": "核心冲突与关键转折", "purpose": "集中完成本章最大冲突、失败调整和制胜动作，必须在约1500-1650字前结束胜负", "target_chars": 740, "max_chars": 820},
    {"scene": "兑现回报与必要结算", "purpose": "写清收获、代价、关系变化、材料处理或阶段性结果，是正文主体不是尾声补丁", "target_chars": 560, "max_chars": 560},
    {"scene": "章尾余波与当前钩子", "purpose": "停在当前事件余波、身体代价或未解压力，可留一句模糊伏笔，但不提前兑现后续完整场面", "target_chars": 260, "max_chars": 260},
)


def count_chapter_chars(text: str) -> int:
    """统计章节有效字数，忽略空白。"""
    return len(re.sub(r"\s+", "", text or ""))


def _compact_json(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit] + ("..." if len(text) > limit else "")


def _clip_text(text: str, limit: int) -> str:
    text = text or ""
    return text[:limit] + ("\n[内容已截断]" if len(text) > limit else "")


def _clip_value(value: Any, limit: int) -> str:
    """把复杂字段压缩成可控文本，供创作包 agent 按需读取。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return _clip_text(value, limit)
    return _clip_text(json.dumps(value, ensure_ascii=False, default=str), limit)


def _digest_section(value: Any, limit: int) -> tuple[str, int]:
    text = _clip_value(value, limit)
    return text, len(text)


def _first_present(context: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = context.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def chapter_creation_pack_fingerprint(
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    system_rules: str | None,
    previous_chapter_summary: str = "",
) -> str:
    """计算创作包全部有效输入的稳定指纹。"""
    context_pack = story_context.get("chapter_context_pack")
    if not isinstance(context_pack, dict):
        context_pack = {}
    payload = {
        "story_meta": {
            "id": story_context.get("id") or story_context.get("story_id"),
            "title": story_context.get("title") or story_context.get("name"),
            "genre": story_context.get("genre"),
            "description": story_context.get("description"),
            "tags": story_context.get("tags"),
        },
        "outline": story_context.get("outline"),
        "story_bible": story_context.get("story_bible"),
        "story_memory": _first_present(
            story_context,
            ("story_memory_compact", "story_memory", "memory", "continuity_memory"),
        ),
        "characters": story_context.get("characters"),
        "reference_takeaways": story_context.get("reference_takeaways"),
        "deconstruction_report": story_context.get("deconstruction_report"),
        "chapter": {
            key: chapter_info.get(key)
            for key in (
                "chapter_number", "title", "act", "key_events", "summary",
                "goal", "conflict", "hook", "payoff", "highlight", "user_instruction",
            )
        },
        "knowledge": {
            "revision": context_pack.get("knowledge_revision") or story_context.get("knowledge_revision"),
            "context_hash": context_pack.get("context_hash"),
        },
        "previous_chapter_summary": previous_chapter_summary,
        "system_rules": system_rules or "",
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def reusable_chapter_creation_pack(
    quality_score: Any,
    *,
    expected_fingerprint: str,
    instruction: str = "",
) -> dict[str, Any] | None:
    """仅在全部输入一致时复用持久化创作包。"""
    if not isinstance(quality_score, dict):
        return None
    creation_pack = quality_score.get("creation_pack")
    if not isinstance(creation_pack, dict) or not creation_pack:
        return None
    stored_fingerprint = str(quality_score.get("creation_pack_fingerprint") or "").strip()
    if not stored_fingerprint or stored_fingerprint != expected_fingerprint:
        return None

    reusable = copy.deepcopy(creation_pack)
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
        return reusable
    chapter_task = reusable.get("chapter_task")
    if not isinstance(chapter_task, dict):
        chapter_task = {}
        reusable["chapter_task"] = chapter_task
    previous_instruction = str(chapter_task.get("user_instruction") or "").strip()
    chapter_task["user_instruction"] = normalized_instruction

    requirements = reusable.get("hard_requirements")
    if not isinstance(requirements, list):
        requirements = []
    normalized_requirements = [
        str(item).strip()
        for item in requirements
        if str(item).strip() and str(item).strip() != previous_instruction
    ]
    reusable["hard_requirements"] = [normalized_instruction, *normalized_requirements][:6]
    return reusable


def _build_creation_pack_source_digest(
    *,
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    previous_chapter_summary: str,
    chapter_scope: dict[str, Any],
    system_rules: str | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """只提取写当前章会出错的关键信息，避免创作包阶段吞全量上下文。"""
    context = story_context if isinstance(story_context, dict) else {}
    story_meta = {
        "id": context.get("id") or context.get("story_id"),
        "title": context.get("title") or context.get("name"),
        "genre": context.get("genre"),
        "description": context.get("description"),
        "tags": context.get("tags"),
    }
    current_scope = chapter_scope if isinstance(chapter_scope, dict) else {}
    previous_cards = current_scope.get("previous_chapters_for_continuity")
    if isinstance(previous_cards, list):
        previous_cards = previous_cards[-3:]
    future_cards = current_scope.get("future_chapters_for_boundary_only")
    if isinstance(future_cards, list):
        future_cards = future_cards[:5]

    sections: dict[str, Any] = {
        "story_meta": story_meta,
        "current_chapter_task": chapter_info,
        "current_chapter_card": current_scope.get("current_chapter_card") if current_scope else {},
        "previous_chapters_for_continuity": previous_cards or [],
        "previous_chapter_summary": previous_chapter_summary or "",
        "continuity_memory": _first_present(context, ("story_memory_compact", "story_memory", "memory", "continuity_memory")),
        "story_bible": _first_present(context, ("story_bible_compact", "story_bible", "bible", "world_bible")),
        "outline_or_plan": _first_present(context, ("chapter_plan", "chapter_planning", "outline_summary", "outline")),
        "characters": context.get("characters"),
        "knowledge_entities": context.get("knowledge_entities"),
        "knowledge_facts": context.get("knowledge_facts"),
        "open_threads": context.get("open_threads"),
        "reference_takeaways_source": _first_present(
            context,
            (
                "reference_takeaways",
                "deconstruction_report",
                "analysis_report",
                "book_report",
                "style_reference",
            ),
        ),
        "future_chapters_for_boundary_only": future_cards or [],
        "system_rules_digest": system_rules or "",
    }
    limits = {
        "story_meta": 900,
        "current_chapter_task": 1800,
        "current_chapter_card": 1600,
        "previous_chapters_for_continuity": 1600,
        "previous_chapter_summary": 1200,
        "continuity_memory": 1600,
        "story_bible": 1500,
        "outline_or_plan": 1800,
        "characters": 1400,
        "knowledge_entities": 1800,
        "knowledge_facts": 2400,
        "open_threads": 1800,
        "reference_takeaways_source": 1000,
        "future_chapters_for_boundary_only": 1200,
        "system_rules_digest": 1200,
    }
    digest: dict[str, Any] = {}
    budget: dict[str, int] = {}
    for key, value in sections.items():
        text, size = _digest_section(value, limits.get(key, 1000))
        if text:
            digest[key] = text
        budget[key] = size
    digest["digest_policy"] = (
        "仅保留当前章节创作必需信息；后续章节用于判断伏笔上限和兑现边界；"
        "knowledge_facts 是连续性硬约束，knowledge_entities 是人物当前状态，open_threads 按 urgency 决定推进强度；"
        "正文可以保留一句以内模糊钩子，但不得把 future_chapters_for_boundary_only 写成当前章完整行动。"
    )
    budget["total"] = len(json.dumps(digest, ensure_ascii=False, default=str))
    return digest, budget


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _chapter_label(chapter_info: dict[str, Any] | None) -> str:
    info = chapter_info if isinstance(chapter_info, dict) else {}
    number = info.get("chapter_number") or info.get("number") or "?"
    title = str(info.get("title") or "").strip()
    return f"第{number}章《{title}》" if title else f"第{number}章"


def _list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _normalize_scene_budget(pack: dict[str, Any] | None) -> list[dict[str, Any]]:
    """标准化场景字数预算，让正文 agent 有明确节奏边界。"""
    if not isinstance(pack, dict):
        return [dict(item) for item in _DEFAULT_SCENE_BUDGET]
    raw_budget = pack.get("scene_budget")
    normalized: list[dict[str, Any]] = []
    if isinstance(raw_budget, list):
        for item in raw_budget[:7]:
            if not isinstance(item, dict):
                continue
            scene = str(item.get("scene") or item.get("name") or "").strip()
            purpose = str(item.get("purpose") or item.get("goal") or "").strip()
            try:
                target_chars = int(item.get("target_chars") or item.get("target") or 0)
            except (TypeError, ValueError):
                target_chars = 0
            try:
                max_chars = int(item.get("max_chars") or item.get("max") or 0)
            except (TypeError, ValueError):
                max_chars = 0
            if not scene or target_chars <= 0:
                continue
            target_chars = max(120, min(target_chars, 1050))
            max_chars = max(target_chars, min(max_chars or target_chars + 80, target_chars + 80, 1120))
            normalized.append({
                "scene": scene[:40],
                "purpose": purpose[:120],
                "target_chars": target_chars,
                "max_chars": max_chars,
            })
    if not normalized:
        normalized = [dict(item) for item in _DEFAULT_SCENE_BUDGET]

    total_target = sum(int(item["target_chars"]) for item in normalized)
    if total_target > SCENE_BUDGET_SOFT_MAX_TOTAL:
        ratio = SCENE_BUDGET_IDEAL_TOTAL / max(total_target, 1)
        for item in normalized:
            item["target_chars"] = max(120, int(int(item["target_chars"]) * ratio))
            item["max_chars"] = max(
                item["target_chars"],
                min(int(int(item["max_chars"]) * ratio), int(item["target_chars"]) + 80, LOCAL_SOFT_MAX_CHARS),
            )
    total_target = sum(int(item["target_chars"]) for item in normalized)
    if total_target < SCENE_BUDGET_IDEAL_TOTAL and normalized:
        normalized[-1]["target_chars"] += SCENE_BUDGET_IDEAL_TOTAL - total_target
        normalized[-1]["max_chars"] = max(normalized[-1]["max_chars"], normalized[-1]["target_chars"] + 60)

    max_total = sum(int(item["max_chars"]) for item in normalized)
    if max_total > SCENE_BUDGET_HARD_MAX_TOTAL:
        overflow = max_total - SCENE_BUDGET_HARD_MAX_TOTAL
        for item in sorted(normalized, key=lambda value: int(value["max_chars"]) - int(value["target_chars"]), reverse=True):
            room = max(0, int(item["max_chars"]) - int(item["target_chars"]))
            cut = min(room, overflow)
            item["max_chars"] = int(item["max_chars"]) - cut
            overflow -= cut
            if overflow <= 0:
                break
    return normalized


def _ensure_scene_budget(pack: dict[str, Any]) -> dict[str, Any]:
    if isinstance(pack, dict):
        pack["scene_budget"] = _normalize_scene_budget(pack)
    return pack


_PLOT_BEAT_REQUIRED_GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("核心冲突", "胜负", "制胜", "阶段性结果", "关键转折"),
        "核心冲突在约1600-1800字前完成胜负或阶段性结果，为回报结算留出篇幅。",
    ),
    (
        ("回报", "结算", "采集", "清点", "材料", "收获", "代价", "撤离"),
        "写清当前章回报结算：材料采集、清点、身体代价或压力变化，不能留到最后200字。",
    ),
    (
        ("余波", "章尾", "当前事件", "当下压力", "身体代价"),
        "章尾停在当前事件余波、身体代价或当下压力，可留一句模糊伏笔，但不提前写后续章节的完整行动、交易或地点推进。",
    ),
)


def _matches_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_plot_beats(pack: dict[str, Any]) -> dict[str, Any]:
    """把创作包情节点压到 6-8 个，防止正文 agent 被过密任务拖成残稿。"""
    if not isinstance(pack, dict):
        return pack
    raw_beats = pack.get("plot_beats")
    cleaned: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_beats, list):
        for item in raw_beats:
            text = str(item).strip()
            if not text:
                continue
            text = re.sub(r"\s+", " ", text)[:180]
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)

    if not cleaned:
        task = pack.get("chapter_task") if isinstance(pack.get("chapter_task"), dict) else {}
        goal = str(task.get("goal") or task.get("summary") or "完成当前章节任务").strip()
        cleaned = [
            f"开场直接承接前文状态，明确本章目标：{goal[:80]}",
            "主角通过观察、行动或短对白确认眼前问题和可行策略。",
            "核心冲突集中爆发，主角用已建立能力解决当前事件。",
        ]

    for keywords, fallback in _PLOT_BEAT_REQUIRED_GROUPS:
        if not any(_matches_any_keyword(item, keywords) for item in cleaned):
            cleaned.append(fallback)

    tail_items: list[str] = []
    for keywords, fallback in _PLOT_BEAT_REQUIRED_GROUPS:
        selected = next((item for item in reversed(cleaned) if _matches_any_keyword(item, keywords)), fallback)
        if selected not in tail_items:
            tail_items.append(selected)

    head: list[str] = []
    for item in cleaned:
        if item in tail_items:
            continue
        if len(head) + len(tail_items) >= PLOT_BEATS_MAX:
            break
        head.append(item)

    result = head + tail_items
    while len(result) < PLOT_BEATS_MIN:
        filler = "用一两句完成必要过渡，立刻回到当前章节核心因果。"
        if filler in result:
            filler = "保留角色当下选择和压力变化，不展开新地点、新交易或新任务。"
        result.insert(max(0, len(result) - len(tail_items)), filler)
    if len(result) > PLOT_BEATS_MAX:
        result = result[: PLOT_BEATS_MAX - len(tail_items)] + tail_items
    pack["plot_beats"] = result[:PLOT_BEATS_MAX]
    return pack


def _pack_log_summary(pack: dict[str, Any]) -> dict[str, Any]:
    boundary = pack.get("chapter_boundary") if isinstance(pack.get("chapter_boundary"), dict) else {}
    sanitization = pack.get("boundary_sanitization") if isinstance(pack.get("boundary_sanitization"), dict) else {}
    return {
        "plot_beats": _list_len(pack.get("plot_beats")),
        "continuity": _list_len(pack.get("continuity")),
        "must_keep": _list_len(pack.get("must_keep")),
        "do_not_write": _list_len(pack.get("do_not_write")),
        "future_boundary_terms": pack.get("future_boundary_terms") or [],
        "sanitized_fields": list((sanitization.get("fields") or {}).keys()),
        "future_cards": _list_len(boundary.get("future_chapters_for_boundary_only")),
        "target": pack.get("target"),
        "scene_budget_total": sum(int(item.get("target_chars") or 0) for item in _normalize_scene_budget(pack)),
        "acceptance_checklist": _list_len(pack.get("acceptance_checklist")),
        "hard_requirements": _list_len(pack.get("hard_requirements")),
        "closure_requirements": _list_len(pack.get("closure_requirements")),
        "missing_if_absent": _list_len(pack.get("missing_if_absent")),
    }


def _take_log_items(value: Any, *, limit: int = 3, item_limit: int = 90) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            items.append(text[:item_limit] + ("..." if len(text) > item_limit else ""))
    return items


def _pack_log_zh_summary(pack: dict[str, Any]) -> dict[str, Any]:
    """生成便于真实回归时人工阅读的中文创作包摘要。"""
    task = pack.get("chapter_task") if isinstance(pack.get("chapter_task"), dict) else {}
    target = pack.get("target") if isinstance(pack.get("target"), dict) else {}
    contract = pack.get("completion_contract") if isinstance(pack.get("completion_contract"), dict) else {}
    budget = _normalize_scene_budget(pack)
    scene_budget_total = sum(int(item.get("target_chars") or 0) for item in budget)
    title = str(task.get("title") or "").strip()
    chapter_number = task.get("chapter_number") or task.get("number") or "?"
    return {
        "章节任务": f"第{chapter_number}章《{title}》" if title else f"第{chapter_number}章",
        "目标字数": (
            f"{target.get('min', LOCAL_MIN_CHARS)}-{target.get('max', LOCAL_MAX_CHARS)} 字，"
            f"正文 agent 写作目标 {WRITER_TARGET_MIN_CHARS}-{WRITER_TARGET_MAX_CHARS} 字"
        ),
        "场景预算总字数": scene_budget_total,
        "场景预算": [
            f"{item.get('scene')}：约{item.get('target_chars')}字，上限{item.get('max_chars')}字"
            for item in budget[:6]
        ],
        "编辑通过分": contract.get("pass_score", EDITOR_PASS_SCORE),
        "连续性摘要": _take_log_items(pack.get("continuity"), limit=4),
        "硬性动作": _take_log_items(pack.get("hard_requirements"), limit=6),
        "闭环要求": _take_log_items(pack.get("closure_requirements"), limit=6),
        "执行顺序": _take_log_items(pack.get("writer_execution_order"), limit=7),
        "缺失必打回": _take_log_items(pack.get("missing_if_absent"), limit=6),
        "核心情节点": _take_log_items(pack.get("plot_beats"), limit=5),
        "禁写边界": _take_log_items(pack.get("do_not_write"), limit=5),
        "验收清单": _take_log_items(pack.get("acceptance_checklist"), limit=6),
    }


def _length_revision_guidance(char_count: int) -> tuple[str, list[str], list[str]]:
    """根据当前字数生成定向返修提示，避免整章重写导致字数震荡。"""
    if char_count > LOCAL_MAX_CHARS:
        return (
            "trim",
            [f"模型输出触发 length 截断且当前 {char_count} 字超出上限，需要以上一版为底稿做删减式返修。"],
            [
                f"以上一版为底稿做删减式返修，目标 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字；不新增场景、不改核心因果，优先压缩重复观察、环境描写、尾声复盘和解释句。",
                "保留当前章节要求的关键动作、冲突、结算和钩子，同时一次性处理编辑 agent 已指出的所有问题。",
            ],
        )
    if char_count < LOCAL_MIN_CHARS:
        return (
            "expand",
            [f"模型输出触发 length 截断且当前 {char_count} 字低于下限，需要以上一版为底稿做补写式返修。"],
            [
                f"以上一版为底稿做补写式返修，目标 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字；只补当前章节内缺失的动作反馈、奖惩结算、身体代价、人物反应或必要交锋。",
                "禁止为了补字数新增后续章节地点、资源、路线、探索或交易的完整场面；补写必须服务当前章节创作包和编辑问题包。",
            ],
        )
    return (
        "close",
        [f"模型输出触发 length 截断但当前 {char_count} 字在合格区间，需要补齐收束而不是整章重写。"],
        [
            f"保留上一版主体，只补完整断句、章末收束和必要钩子，目标保持 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字；可以保留一句以内模糊伏笔，不要新增完整事件线。",
            "同时处理编辑 agent 已指出的边界、逻辑、节奏和 AI 味问题，完成后立即停笔。",
        ],
    )


def _content_looks_truncated(content: str) -> bool:
    """粗判正文是否像被模型截断，只作为 length finish_reason 的辅助证据。"""
    text = (content or "").strip()
    if not text:
        return True
    if text.endswith(("。", "！", "？", "”", "」", "』", ".", "!", "?")):
        return False
    tail = text[-80:]
    if re.search(r"(说道|问道|喊道|低声说|开口|抬手|转身|伸手|盯着|看着|听见|发现|准备|继续|只见)$", tail):
        return True
    if re.search(r"[\u4e00-\u9fff]$", tail):
        return True
    return bool(re.search(r"[，、：；]$", tail))


_SENTENCE_END_RE = re.compile(r"[。！？!?；;”’」』）)]")


def _repair_truncated_tail_locally(content: str) -> tuple[str, bool]:
    """剪掉模型截断造成的末尾残句，避免小尾巴触发整章重写。"""
    text = (content or "").rstrip()
    if not text or not _content_looks_truncated(text):
        return content, False
    matches = list(_SENTENCE_END_RE.finditer(text))
    if not matches:
        return content, False
    cut_index = matches[-1].end()
    repaired = text[:cut_index].rstrip()
    removed_chars = count_chapter_chars(text) - count_chapter_chars(repaired)
    repaired_chars = count_chapter_chars(repaired)
    if removed_chars <= 0 or removed_chars > 180:
        return content, False
    if not (LOCAL_MIN_CHARS <= repaired_chars <= LOCAL_MAX_CHARS):
        return content, False
    return repaired, True


_TAIL_BOUNDARY_PATTERN = re.compile(
    r"(市场价|卖到|卖钱|售出|估价|行情|来钱|出手|交易|变现|黑市|摊位|买家|"
    r"后续利用|计划利用|利用方式|使用或出售|"
    r"明天|明日|明早|明晚|翌日|后天|下一步|接下来|入口|坐标|深处|遗迹|乱石坡)"
)

_NEUTRAL_TAIL_SENTENCE = (
    "陈玄把包口扎紧，左臂伤口仍在发热。至少这一趟，他证明了自己能靠技术从危险里拿回东西。"
)


def _tail_boundary_hits(content: str, *, tail_chars: int = 900) -> list[str]:
    """只检查章尾漂移，避免正文中作为否定语境出现的边界词误伤全章。"""
    tail = (content or "").strip()[-tail_chars:]
    return sorted(set(_TAIL_BOUNDARY_PATTERN.findall(tail)), key=len, reverse=True)


def _repair_boundary_tail_locally(content: str) -> tuple[str, bool, list[str]]:
    """本地替换章尾越界句，优先保护已经接近通过的正文主体。"""
    text = (content or "").rstrip()
    if not text:
        return content, False, []
    tail_start = max(0, len(text) - 900)
    tail = text[tail_start:]
    match = _TAIL_BOUNDARY_PATTERN.search(tail)
    if not match:
        return content, False, []

    hit_abs = tail_start + match.start()
    cut_candidates = [
        text.rfind("\n", 0, hit_abs),
        text.rfind("。", 0, hit_abs),
        text.rfind("！", 0, hit_abs),
        text.rfind("？", 0, hit_abs),
        text.rfind("”", 0, hit_abs),
    ]
    cut_at = max(cut_candidates)
    if cut_at < max(0, hit_abs - 260):
        cut_at = hit_abs
    if cut_at > 0 and text[cut_at] in "。！？”":
        cut_at += 1
    repaired = text[:cut_at].rstrip()
    if repaired and not repaired.endswith(("。", "！", "？", "”")):
        repaired = repaired.rstrip("，、；： ")
    if repaired and not repaired.endswith(_NEUTRAL_TAIL_SENTENCE):
        repaired = f"{repaired}\n\n{_NEUTRAL_TAIL_SENTENCE}"
    repaired_chars = count_chapter_chars(repaired)
    if not (LOCAL_MIN_CHARS <= repaired_chars <= LOCAL_MAX_CHARS):
        return content, False, _tail_boundary_hits(content)
    remaining_hits = _tail_boundary_hits(repaired)
    if remaining_hits:
        return content, False, remaining_hits
    return repaired, True, _tail_boundary_hits(content)


def _should_force_length_revision(finish_reason: Any, review: dict[str, Any], content: str) -> tuple[bool, str]:
    """判断 length 是否需要强制返修，避免把编辑已通过的完整稿误打回。"""
    if finish_reason != "length":
        return False, "not_length"
    char_count = count_chapter_chars(content)
    if _review_is_hard_pass(review, content):
        return False, "editor_approved_overrides_length"
    if char_count < LOCAL_MIN_CHARS:
        return True, "too_short"
    if char_count > LOCAL_MAX_CHARS:
        return True, "too_long"
    if _content_looks_truncated(content):
        return True, "truncated_tail"
    return True, "model_length_finish"


def _review_is_hard_pass(review: dict[str, Any], content: str) -> bool:
    return (
        bool(review.get("approved"))
        and _score(review.get("overall_score")) >= EDITOR_PASS_SCORE
        and not _review_has_real_blocking_issue(review, content)
    )


def _compact_items(value: Any, *, item_limit: int = 220, list_limit: int = 14) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:list_limit]:
        text = str(item)
        items.append(text[:item_limit] + ("..." if len(text) > item_limit else ""))
    return items


def _pack_log_detail(pack: dict[str, Any]) -> dict[str, Any]:
    canonical_content = canonical_pack_content(pack)
    if canonical_content is not None:
        section_titles = re.findall(r"^##\s+(.+?)\s*$", canonical_content, flags=re.MULTILINE)
        return {
            "schema_version": pack.get("schema_version"),
            "chapter_task": pack.get("chapter_task"),
            "canonical_content_chars": len(canonical_content),
            "canonical_content_sha256": hashlib.sha256(canonical_content.encode("utf-8")).hexdigest(),
            "canonical_sections": section_titles[:20],
        }
    boundary = pack.get("chapter_boundary") if isinstance(pack.get("chapter_boundary"), dict) else {}
    current_card = boundary.get("current_chapter_card") if isinstance(boundary.get("current_chapter_card"), dict) else {}
    future_cards = boundary.get("future_chapters_for_boundary_only")
    if not isinstance(future_cards, list):
        future_cards = []
    future_digest = [
        {
            "chapter_number": card.get("chapter_number"),
            "title": card.get("title"),
            "goal": card.get("goal"),
            "conflict": card.get("conflict"),
        }
        for card in future_cards[:8]
        if isinstance(card, dict)
    ]
    return {
        "chapter_task": pack.get("chapter_task"),
        "continuity": _compact_items(pack.get("continuity")),
        "character_states": _compact_items(pack.get("character_states")),
        "plot_beats": _compact_items(pack.get("plot_beats"), list_limit=16),
        "emotion_goal": pack.get("emotion_goal"),
        "payoff_plan": pack.get("payoff_plan"),
        "hard_requirements": _compact_items(pack.get("hard_requirements"), item_limit=260, list_limit=8),
        "closure_requirements": _compact_items(pack.get("closure_requirements"), item_limit=260, list_limit=8),
        "writer_execution_order": _compact_items(pack.get("writer_execution_order"), item_limit=260, list_limit=10),
        "missing_if_absent": _compact_items(pack.get("missing_if_absent"), item_limit=260, list_limit=8),
        "opening_strategy": pack.get("opening_strategy"),
        "ending_hook": pack.get("ending_hook"),
        "style_brief": pack.get("style_brief"),
        "writing_rules": _compact_items(pack.get("writing_rules"), item_limit=260, list_limit=12),
        "scene_budget": _normalize_scene_budget(pack),
        "completion_contract": pack.get("completion_contract"),
        "acceptance_checklist": _compact_items(pack.get("acceptance_checklist"), item_limit=260, list_limit=14),
        "must_keep": _compact_items(pack.get("must_keep")),
        "do_not_write": _compact_items(pack.get("do_not_write"), item_limit=260, list_limit=18),
        "review_focus": _compact_items(pack.get("review_focus")),
        "future_boundary_terms": pack.get("future_boundary_terms") or [],
        "boundary_term_filter": pack.get("boundary_term_filter"),
        "boundary_sanitization": pack.get("boundary_sanitization"),
        "boundary_priority": pack.get("boundary_priority"),
        "current_chapter_card": current_card,
        "future_chapters_for_boundary_only": future_digest,
        "target": pack.get("target"),
    }


def _agent_pack_view(pack: dict[str, Any]) -> dict[str, Any]:
    view = dict(pack) if isinstance(pack, dict) else {}
    boundary = dict(view.get("chapter_boundary")) if isinstance(view.get("chapter_boundary"), dict) else {}
    future_cards = boundary.get("future_chapters_for_boundary_only")
    if isinstance(future_cards, list):
        boundary["future_chapters_for_boundary_only"] = [
            {
                "chapter_number": card.get("chapter_number"),
                "title": card.get("title"),
            }
            for card in future_cards[:8]
            if isinstance(card, dict)
        ]
    view["chapter_boundary"] = boundary
    return view


def _creation_pack_prompt_text(pack: dict[str, Any], legacy_limit: int) -> str:
    """规范创作包始终原样发送；旧格式仅保留兼容期裁剪。"""
    canonical_content = canonical_pack_content(pack)
    if canonical_content is not None:
        return canonical_content
    return _compact_json(_agent_pack_view(pack), legacy_limit)


def _default_completion_contract() -> dict[str, Any]:
    return {
        "pass_score": EDITOR_PASS_SCORE,
        "target_chars": {"min": LOCAL_MIN_CHARS, "ideal": LOCAL_IDEAL_CHARS, "max": LOCAL_MAX_CHARS},
        "writer_output": "每一轮都必须输出完整章节全文，不输出补丁、差异片段或续写尾巴。",
        "revision_policy": "编辑问题包一次性处理：字数、边界、剧情执行、因果逻辑、节奏、角色声音和 AI 味同轮完成。",
        "boundary_policy": "当前章节事件必须闭环；后续章节信息可作为一句以内模糊伏笔，但不得提前兑现完整场面、路线、交易或战斗结果。",
        "execution_policy": "正文必须先完成 hard_requirements，再完成 closure_requirements；只完成核心冲突、战斗或交锋不算章节完成。",
    }


def _default_acceptance_checklist(pack: dict[str, Any] | None) -> list[str]:
    task = pack.get("chapter_task") if isinstance(pack, dict) else {}
    goal = ""
    if isinstance(task, dict):
        goal = str(task.get("goal") or task.get("summary") or "").strip()
    checklist = [
        f"当前章节核心任务已完整闭环：{goal[:120] or '按章节任务卡完成起因、冲突、转折、结果和章尾余波'}",
        f"正文有效字数落在 {LOCAL_MIN_CHARS}-{LOCAL_MAX_CHARS} 字，优先 {WRITER_TARGET_MIN_CHARS}-{WRITER_TARGET_MAX_CHARS} 字。",
        "plot_beats 中的关键情节点按因果顺序完成，不能只写开端或只写结尾。",
        "hard_requirements 中列出的硬性动作必须逐项落地；缺任一项都不能视为完成当前章。",
        "closure_requirements 中的回报结算、处理动作和章尾余波必须写成正文主体，不能当作最后一句补丁。",
        "核心冲突、胜负或阶段性结果必须在约1600-1800字前完成，不能挤掉后半段结算。",
        "正文75%前必须进入回报结算；回报结算不能留到最后200字用一句话补丁处理。",
        "must_keep 中的事实、角色状态和收益代价全部兑现。",
        "do_not_write 与 chapter_boundary 中的后续章节内容没有被提前兑现成完整场面；若作为钩子，只保留一句以内模糊压力或方向。",
        "每个场景预算对应的功能都已完成，核心冲突和回报结算没有被前置铺垫挤掉。",
        "章尾停在当前事件余波、身体代价、现实压力或当下选择；可以预留模糊伏笔，但不展开后续具体行动。",
        "输出前自检：若只剩轻微表达问题，可以小幅润色；若缺剧情闭环，必须重写完整章节。",
    ]
    return checklist


def _normalize_contract_list(value: Any, *, limit: int = 8, item_limit: int = 180) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        text = text[:item_limit]
        key = re.sub(r"\s+", "", text).casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _default_hard_requirements(pack: dict[str, Any]) -> list[str]:
    task = pack.get("chapter_task") if isinstance(pack.get("chapter_task"), dict) else {}
    goal = str(task.get("goal") or task.get("summary") or task.get("title") or "").strip()
    beats = _normalize_contract_list(pack.get("plot_beats"), limit=4, item_limit=120)
    must_keep = _normalize_contract_list(pack.get("must_keep"), limit=3, item_limit=120)
    requirements = [
        f"完整完成当前章节核心任务：{goal[:120] or '按章节任务卡完成起因、冲突、转折、结果和当前章余波'}。",
        "核心冲突结束后必须继续完成当前章回报、代价、清点、撤离或关系变化，不能把胜负当作章节终点。",
    ]
    requirements.extend(f"落实情节点：{item}" for item in beats[:3])
    requirements.extend(f"正文必须保留：{item}" for item in must_keep[:2])
    return requirements[:6]


def _default_closure_requirements(pack: dict[str, Any]) -> list[str]:
    payoff = str(pack.get("payoff_plan") or "").strip()
    requirements = [
        "写清当前章节的回报结算：收获、材料/线索/奖励、代价、身体状态或现实压力变化至少落地两项。",
        "写清核心动作后的处理：采集、清理、撤离、归置、清点或阶段性结果，按本章题材选择，不得只用一句话带过。",
        "章尾停在当前事件余波、人物当下选择、身体代价或未解压力；后续章节信息最多作为一句以内模糊钩子。",
    ]
    if payoff:
        requirements.insert(0, f"兑现 payoff_plan：{payoff[:140]}。")
    return requirements[:5]


def _ensure_execution_contract_fields(pack: dict[str, Any]) -> dict[str, Any]:
    hard_requirements = _normalize_contract_list(pack.get("hard_requirements"), limit=6)
    if not hard_requirements:
        hard_requirements = _default_hard_requirements(pack)
    closure_requirements = _normalize_contract_list(pack.get("closure_requirements"), limit=6)
    if not closure_requirements:
        closure_requirements = _default_closure_requirements(pack)
    plot_order = _normalize_contract_list(pack.get("plot_beats"), limit=8, item_limit=120)
    writer_order = _normalize_contract_list(pack.get("writer_execution_order"), limit=10)
    if not writer_order:
        writer_order = plot_order[:5] + [
            "在正文约70%-75%前结束核心冲突、胜负或阶段性结果。",
            "按 closure_requirements 完成回报结算和当前事件收束。",
            "完成章尾余波或一句以内模糊钩子后立刻停笔。",
        ]
    missing_if_absent = _normalize_contract_list(pack.get("missing_if_absent"), limit=8)
    if not missing_if_absent:
        missing_if_absent = [
            "任一 hard_requirements 未被正文明确执行。",
            "任一 closure_requirements 仅被一句话补丁处理或完全缺失。",
            "正文只完成核心冲突/战斗/交锋，却没有写回报结算、处理动作和章尾余波。",
            "正文提前兑现 do_not_write 或 chapter_boundary 中的后续完整场面。",
        ]

    pack["hard_requirements"] = hard_requirements[:6]
    pack["closure_requirements"] = closure_requirements[:6]
    pack["writer_execution_order"] = writer_order[:10]
    pack["missing_if_absent"] = missing_if_absent[:8]
    return pack


def _ensure_completion_fields(pack: dict[str, Any]) -> dict[str, Any]:
    pack = _normalize_plot_beats(pack)
    pack = _ensure_execution_contract_fields(pack)
    default_contract = _default_completion_contract()
    contract = pack.get("completion_contract")
    if not isinstance(contract, dict):
        contract = {}
    merged_contract = {**default_contract, **contract}
    target = merged_contract.get("target_chars")
    if not isinstance(target, dict):
        target = {}
    merged_contract["target_chars"] = {
        "min": LOCAL_MIN_CHARS,
        "ideal": LOCAL_IDEAL_CHARS,
        "max": LOCAL_MAX_CHARS,
        **{key: value for key, value in target.items() if key not in {"min", "ideal", "max"}},
    }
    merged_contract["target_chars"]["min"] = LOCAL_MIN_CHARS
    merged_contract["target_chars"]["ideal"] = LOCAL_IDEAL_CHARS
    merged_contract["target_chars"]["max"] = LOCAL_MAX_CHARS
    merged_contract["pass_score"] = EDITOR_PASS_SCORE
    for key, value in default_contract.items():
        if key not in merged_contract or not merged_contract.get(key):
            merged_contract[key] = value
    pack["completion_contract"] = merged_contract
    pack["target"] = {
        "min": LOCAL_MIN_CHARS,
        "ideal": LOCAL_IDEAL_CHARS,
        "max": LOCAL_MAX_CHARS,
    }

    raw_checklist = pack.get("acceptance_checklist")
    existing = [str(item).strip() for item in raw_checklist] if isinstance(raw_checklist, list) else []
    defaults = _default_acceptance_checklist(pack)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in defaults + existing:
        if not item:
            continue
        text = item[:220]
        key = re.sub(r"\s+", "", text).casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= 10:
            break
    pack["acceptance_checklist"] = normalized[:10]
    return pack


def _inject_resolved_knowledge_constraints(
    pack: dict[str, Any],
    story_context: dict[str, Any],
) -> dict[str, Any]:
    """把已检索知识确定性注入创作合同，避免前置 Agent 遗漏。"""
    facts = story_context.get("knowledge_facts") if isinstance(story_context, dict) else []
    entities = story_context.get("knowledge_entities") if isinstance(story_context, dict) else []
    threads = story_context.get("open_threads") if isinstance(story_context, dict) else []

    continuity = _normalize_contract_list(pack.get("continuity"), limit=8)
    must_keep = _normalize_contract_list(pack.get("must_keep"), limit=10)
    for item in facts[:8] if isinstance(facts, list) else []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        value_text = _clip_value(value, 100) if value not in (None, "", [], {}) else ""
        statement = " ".join(str(part).strip() for part in (
            item.get("subject"), item.get("predicate"), item.get("object"), value_text
        ) if str(part or "").strip())
        if statement and statement not in continuity:
            continuity.append(statement[:180])
        if statement and statement not in must_keep:
            must_keep.append(f"连续性事实：{statement[:150]}")

    character_states = _normalize_contract_list(pack.get("character_states"), limit=8)
    for item in entities[:6] if isinstance(entities, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("key") or "").strip()
        profile = _clip_value(item.get("profile"), 120)
        state = f"{name}：{profile}" if name and profile else name
        if state and state not in character_states:
            character_states.append(state[:180])

    review_focus = _normalize_contract_list(pack.get("review_focus"), limit=8)
    for item in threads[:8] if isinstance(threads, list) else []:
        if not isinstance(item, dict):
            continue
        urgency = str(item.get("urgency") or "background")
        if urgency not in {"due", "overdue", "approaching"}:
            continue
        title = str(item.get("title") or item.get("key") or "未命名伏笔").strip()
        instruction = f"伏笔{title}已{ {'due': '进入回收窗口', 'overdue': '逾期', 'approaching': '临近回收'}.get(urgency) }，本章需推进或明确延后"
        if instruction not in review_focus:
            review_focus.append(instruction[:180])
        if urgency in {"due", "overdue"} and instruction not in must_keep:
            must_keep.append(instruction[:180])

    pack["continuity"] = continuity[:8]
    pack["must_keep"] = must_keep[:10]
    pack["character_states"] = character_states[:8]
    pack["review_focus"] = review_focus[:8]
    return pack


def _writer_max_tokens(previous_char_count: int, has_feedback: bool) -> int:
    return WRITER_MAX_TOKENS


def _review_log_summary(review: dict[str, Any]) -> dict[str, Any]:
    local = review.get("local_safety") if isinstance(review.get("local_safety"), dict) else {}
    hard_failures = local.get("hard_failures") if isinstance(local.get("hard_failures"), list) else []
    soft_warnings = local.get("soft_warnings") if isinstance(local.get("soft_warnings"), list) else []
    return {
        "approved": review.get("approved"),
        "overall_score": review.get("overall_score"),
        "findings": _list_len(review.get("findings")),
        "rewrite_brief": _list_len(review.get("rewrite_brief")),
        "local_ok": local.get("ok"),
        "char_count": local.get("char_count"),
        "hard_failure_codes": [item.get("code") for item in hard_failures if isinstance(item, dict)],
        "soft_warning_codes": [item.get("code") for item in soft_warnings if isinstance(item, dict)],
        "skipped_editor": review.get("skipped_editor"),
        "skip_reason": review.get("skip_reason"),
    }


def _review_log_detail(review: dict[str, Any]) -> dict[str, Any]:
    raw = review.get("raw") if isinstance(review.get("raw"), dict) else {}
    local = review.get("local_safety") if isinstance(review.get("local_safety"), dict) else {}
    return {
        "findings": _compact_items(review.get("findings"), item_limit=240, list_limit=10),
        "rewrite_brief": _compact_items(review.get("rewrite_brief"), item_limit=260, list_limit=16),
        "local_soft_warnings": local.get("soft_warnings") if isinstance(local.get("soft_warnings"), list) else [],
        "length_action": raw.get("length_action"),
        "blocking_issues": _compact_items(raw.get("blocking_issues"), item_limit=240, list_limit=10),
        "keep": _compact_items(raw.get("keep"), item_limit=220, list_limit=8),
        "fill": _compact_items(raw.get("fill"), item_limit=220, list_limit=8),
        "cut": _compact_items(raw.get("cut"), item_limit=220, list_limit=8),
        "forbid": _compact_items(raw.get("forbid"), item_limit=220, list_limit=8),
        "rewrite_targets": _compact_items(raw.get("rewrite_targets"), item_limit=240, list_limit=10),
        "revision_plan": _compact_items(raw.get("revision_plan"), item_limit=240, list_limit=10),
    }


def _strip_generated_heading(text: str) -> str:
    """移除模型偶发输出的章节标题或 Markdown 标题。"""
    lines = (text or "").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""
    first = lines[0].strip()
    heading_like = first.startswith("#") or bool(re.match(r"^第[一二三四五六七八九十百千万\d]+章[：:\s《].{0,40}$", first))
    if heading_like:
        return "\n".join(lines[1:]).lstrip()
    return "\n".join(lines)


def _score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0 <= number <= 10:
        number *= 10
    return max(0.0, min(number, 100.0))


def _coerce_string_list(value: Any, *, limit: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if str(item).strip()]


def _normalize_review(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    normalized_scores = {str(key): _score(value) for key, value in scores.items()}
    overall = _score(data.get("overall_score") or normalized_scores.get("overall") or data.get("score"))
    if overall <= 0 and normalized_scores:
        overall = sum(normalized_scores.values()) / len(normalized_scores)
    approved = bool(data.get("approved")) and overall >= EDITOR_PASS_SCORE
    revision_notes = data.get("revision_notes")
    if not isinstance(revision_notes, list):
        revision_notes = data.get("findings") if isinstance(data.get("findings"), list) else []
    rewrite_brief = data.get("rewrite_brief")
    if not isinstance(rewrite_brief, list):
        rewrite_brief = revision_notes
    structured_brief: list[str] = []
    for field in ("length_action", "blocking_issues", "revision_plan", "rewrite_targets", "keep", "fill", "cut", "forbid"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            structured_brief.append(f"{field}: {value.strip()}")
        else:
            structured_brief.extend(f"{field}: {item}" for item in _coerce_string_list(value, limit=8))
    normalized = {
        "approved": approved,
        "overall_score": overall,
        "scores": normalized_scores or {"overall": overall},
        "findings": _coerce_string_list(revision_notes, limit=10),
        "rewrite_brief": (structured_brief + _coerce_string_list(rewrite_brief, limit=10))[:16],
        "raw": data,
    }
    if _review_has_real_blocking_issue(normalized):
        normalized["approved"] = False
    return normalized


def _soften_review_dialogue_blockers(review: dict[str, Any]) -> dict[str, Any]:
    """把单纯对话数量问题从编辑硬阻断中降级。"""
    raw = review.get("raw") if isinstance(review.get("raw"), dict) else {}
    blocking = raw.get("blocking_issues")
    if not isinstance(blocking, list) or not blocking:
        return review
    dialogue_items = [str(item) for item in blocking if _is_dialogue_quota_issue(item)]
    if not dialogue_items:
        return review
    remaining = [item for item in blocking if str(item) not in dialogue_items]
    raw["blocking_issues"] = remaining
    review["raw"] = raw
    for field in ("findings", "rewrite_brief"):
        value = review.get(field)
        if isinstance(value, list):
            review[field] = [
                item for item in value
                if not _is_dialogue_quota_issue(item)
            ]
    review.setdefault("findings", [])
    if isinstance(review["findings"], list) and _DIALOGUE_SOFT_RULE not in review["findings"]:
        review["findings"].append(_DIALOGUE_SOFT_RULE)
    local = review.get("local_safety") if isinstance(review.get("local_safety"), dict) else {}
    if not remaining and local.get("ok") and _score(review.get("overall_score")) >= EDITOR_PASS_SCORE:
        review["approved"] = True
        scores = dict(review.get("scores")) if isinstance(review.get("scores"), dict) else {}
        scores["overall"] = review["overall_score"]
        review["scores"] = scores
    return review


def _promote_near_pass_review(review: dict[str, Any], content: str) -> dict[str, Any]:
    """保留原始审稿分数，低于 90 分不得自动提升为通过。"""
    if _score(review.get("overall_score")) < EDITOR_PASS_SCORE:
        review["approved"] = False
    return review


def _local_safety_review(content: str, chapter_scope: dict[str, Any] | None) -> dict[str, Any]:
    """只保留底线安全检查，边界伏笔由编辑 agent 做语义判断。"""
    issues: list[dict[str, Any]] = []
    soft_warnings: list[dict[str, Any]] = []
    char_count = count_chapter_chars(content)
    if not (content or "").strip():
        issues.append({
            "code": "content.empty",
            "message": "正文为空，无法通过本地安全检查",
        })
    if chapter_scope:
        boundary_hits = _tail_boundary_hits(content)
        if boundary_hits:
            soft_warnings.append({
                "code": "boundary.future_event_candidate",
                "message": f"章尾包含后续事件候选词：{', '.join(boundary_hits)}",
            })
    return {
        "ok": not issues,
        "char_count": char_count,
        "target": {"min": LOCAL_MIN_CHARS, "ideal": LOCAL_IDEAL_CHARS, "max": LOCAL_MAX_CHARS},
        "hard_failures": issues,
        "soft_warnings": soft_warnings,
    }


def _should_skip_remote_editor(local: dict[str, Any]) -> tuple[bool, str]:
    hard_failures = local.get("hard_failures") if isinstance(local.get("hard_failures"), list) else []
    failure_codes = {
        str(item.get("code"))
        for item in hard_failures
        if isinstance(item, dict) and item.get("code")
    }
    if failure_codes and all(code.startswith("length.") for code in failure_codes):
        return True, "local_length_hard_failure"
    return False, ""


def _local_failure_review(local: dict[str, Any], *, skip_reason: str) -> dict[str, Any]:
    local_notes = [str(item.get("message")) for item in local.get("hard_failures", []) if isinstance(item, dict)]
    if not local_notes:
        local_notes = ["正文未通过本地底线检查，需要按创作包重新输出完整章节全文。"]
    char_count = int(local.get("char_count") or 0)
    if char_count < LOCAL_MIN_CHARS:
        length_guidance = [
            f"在保留当前正文主体的前提下补写到 {LOCAL_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字。",
            "只补当前章节内缺失的动作反馈、因果衔接、回报结算、身体代价或人物反应，不新增后续章节场景。",
        ]
    else:
        length_guidance = [
            f"删减到 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字；超过 {LOCAL_MAX_CHARS} 字会继续硬失败。",
            "不要新增场景、人物、路线或解释句；优先合并观察、战斗复盘、采集细节和返程动作。",
        ]
    return {
        "approved": False,
        "overall_score": 0,
        "scores": {"overall": 0},
        "findings": local_notes,
        "rewrite_brief": local_notes + [
            "必须输出完整章节全文，不能只输出补丁、片段、说明或结尾续写。",
            *length_guidance,
            "保留核心因果、回报结算、身体代价和章尾余波，用更短句子完成。",
        ],
        "local_safety": local,
        "skipped_editor": True,
        "skip_reason": skip_reason,
    }


_WRITER_LOCAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("深吸一口气，", ""),
    ("深吸了一口气，", ""),
    ("深吸一口气", ""),
    ("深吸了一口气", ""),
    ("这一瞬间", "此刻"),
    ("一瞬间", "片刻间"),
    ("在瞬间", "当场"),
    ("猛地", "立刻"),
    ("突然", ""),
    ("忽然", ""),
    ("瞬间", ""),
    ("——", "，"),
    ("--", "，"),
)


def _sanitize_writer_output_locally(content: str) -> tuple[str, list[str]]:
    cleaned = str(content or "")
    changes: list[str] = []
    for old, new in _WRITER_LOCAL_REPLACEMENTS:
        if old in cleaned:
            cleaned = cleaned.replace(old, new)
            changes.append(old)
    cleanup_rules: tuple[tuple[str, str], ...] = (
        (r"这一这时", "此刻"),
        (r"在这时", "此时"),
        (r"这时这时", "这时"),
        (r"另一个方向，另一个方向", "而是从另一个方向"),
        (r"，{2,}", "，"),
    )
    for pattern, replacement in cleanup_rules:
        updated = re.sub(pattern, replacement, cleaned)
        if updated != cleaned:
            changes.append(pattern)
            cleaned = updated
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, changes


def _looks_like_fragment_revision(previous_content: str, new_content: str, has_feedback: bool) -> bool:
    if not has_feedback:
        return False
    previous_chars = count_chapter_chars(previous_content)
    new_chars = count_chapter_chars(new_content)
    if previous_chars < 1800 or previous_chars > LOCAL_MAX_CHARS:
        return False
    return new_chars < max(1400, int(previous_chars * 0.72))


def _fragment_revision_review(content: str, creation_pack: dict[str, Any]) -> dict[str, Any]:
    local = _local_safety_review(content, creation_pack.get("chapter_boundary"))
    return {
        "approved": False,
        "overall_score": 70 if local.get("ok") else 0,
        "scores": {"overall": 70 if local.get("ok") else 0},
        "findings": ["本轮返修疑似只输出了片段，已拒绝该片段并保留上一版正文。"],
        "rewrite_brief": [
            "上一轮返修只输出了片段，下一轮必须基于上一版正文输出完整章节全文。",
            "如果只是补完整断句、替换一处表达或微调节奏，也必须输出完整章节全文。",
            "保留上一版主体，只处理编辑明确指出的硬伤；可留一句以内模糊伏笔，但不要新增后续章节地点、路线、交易或探索的完整场面。",
        ],
        "local_safety": local,
        "skipped_editor": True,
        "skip_reason": "fragment_revision_rejected",
    }


def _truncated_generation_review(content: str, creation_pack: dict[str, Any], finish_reason: Any) -> dict[str, Any]:
    """模型输出被截断时先本地打回，避免编辑 agent 浪费在残稿上。"""
    local = _local_safety_review(content, creation_pack.get("chapter_boundary"))
    char_count = count_chapter_chars(content)
    if char_count > LOCAL_MAX_CHARS:
        rewrite_brief = [
            f"上一版超长且触发模型截断，下一轮必须压缩成 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字完整章节全文，禁止续写结尾或新增场景。",
            "优先删除重复观察、等待、走位、解释性复盘和环境描写；保留完整猎杀、采集、撤离、章尾余波。",
            "按场景预算重排篇幅：开场和观察合计不超过 650 字，核心冲突不超过 950 字，必须给结算和章尾留下 450 字左右。",
        ]
    elif char_count < LOCAL_MIN_CHARS:
        rewrite_brief = [
            f"上一版偏短且触发模型截断，下一轮必须输出 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字完整章节全文，禁止只续写尾巴或输出补丁。",
            "优先补当前章节缺失的核心交锋、回报结算、身体代价和章尾余波；可留一句以内模糊伏笔，不新增后续章节地点、路线、交易或探索的完整场面。",
            "如果已经进入核心冲突，必须先完成当前事件闭环，再用一两段完成采集和收束。",
        ]
    else:
        rewrite_brief = [
            "上一版触发模型截断，下一轮必须输出完整章节全文，禁止只续写结尾或输出补丁。",
            f"只做收束式返修：保留有效动作链，补完整断句、结算和章尾余波，目标 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字。",
            "完成当前章节核心因果后立刻停笔；可留一句以内模糊伏笔，不新增后续章节地点、路线、交易或探索的完整场面。",
        ]
    return {
        "approved": False,
        "overall_score": 0,
        "scores": {"overall": 0},
        "findings": [
            f"正文生成被模型截断，finish_reason={finish_reason}，当前约 {char_count} 字，尾句未完整收束。",
            "当前稿不能交给编辑定稿，下一轮必须在上一版基础上输出完整章节全文。",
        ],
        "rewrite_brief": rewrite_brief,
        "local_safety": local,
        "skipped_editor": True,
        "skip_reason": "writer_finish_reason_length_truncated",
    }


async def _chat_completion(
    *,
    messages: list[dict[str, str]],
    api_key: str | None,
    max_tokens: int,
    response_format: dict[str, str] | None = None,
    _empty_content_retry: int = 0,
) -> tuple[str, str | None]:
    from services import deepseek as deepseek_service

    payload: dict[str, Any] = {
        "model": deepseek_service.runtime_model(),
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format
    payload = deepseek_service._apply_runtime_params(payload)
    payload["thinking"] = {"type": "disabled"}

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
        resp.raise_for_status()
        data = deepseek_service._response_json(resp, context="DeepSeek")
    except httpx.TimeoutException as exc:
        raise UpstreamServiceError(
            "正文模型响应超时，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=504,
            code="writer_upstream_timeout",
        ) from exc
    except httpx.HTTPStatusError as exc:
        status_code = int(exc.response.status_code)
        raise UpstreamServiceError(
            "正文模型暂时不可用，请稍后重试",
            retryable=status_code in {408, 409, 425, 429, 500, 502, 503, 504},
            provider="DeepSeek",
            status_code=status_code,
            code="writer_upstream_http_error",
            diagnostics={"upstream_status_code": status_code},
        ) from exc
    except httpx.RequestError as exc:
        raise UpstreamServiceError(
            "正文模型网络连接失败，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="writer_upstream_network_error",
        ) from exc
    except ValueError as exc:
        raise UpstreamServiceError(
            "正文模型响应格式异常，请稍后重试",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="writer_invalid_response",
        ) from exc
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        if _empty_content_retry < WRITER_EMPTY_CONTENT_RETRIES:
            logger.warning(
                "chapter_pipeline.writer.invalid_choices_retry model=%s choices_count=%s attempt=%s",
                deepseek_service.runtime_model(),
                len(choices) if isinstance(choices, list) else 0,
                _empty_content_retry + 1,
            )
            return await _chat_completion(
                messages=messages,
                api_key=api_key,
                max_tokens=max_tokens,
                response_format=response_format,
                _empty_content_retry=_empty_content_retry + 1,
            )
        raise WriterEmptyContentError(
            model=deepseek_service.runtime_model(),
            max_tokens=max_tokens,
            choices_count=len(choices) if isinstance(choices, list) else 0,
        )
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    finish_reason = choice.get("finish_reason")
    reasoning_content = message.get("reasoning_content") or ""
    # 读取 usage 中的 reasoning_tokens（若存在），供后续诊断推理模型思考消耗
    usage = data.get("usage") or {}
    usage_details = usage.get("completion_tokens_details") or {}
    reasoning_tokens = usage_details.get("reasoning_tokens")
    if reasoning_tokens is not None:
        logger.debug(
            "chapter_pipeline.chat_completion usage reasoning_tokens=%s finish_reason=%s content_len=%s",
            reasoning_tokens,
            finish_reason,
            len(content or ""),
        )
    if not isinstance(content, str) or not content.strip():
        if _empty_content_retry < WRITER_EMPTY_CONTENT_RETRIES:
            logger.warning(
                "chapter_pipeline.writer.empty_content_retry model=%s finish_reason=%s reasoning_content_len=%s reasoning_tokens=%s attempt=%s",
                deepseek_service.runtime_model(),
                finish_reason,
                len(reasoning_content),
                reasoning_tokens,
                _empty_content_retry + 1,
            )
            return await _chat_completion(
                messages=messages,
                api_key=api_key,
                max_tokens=max_tokens,
                response_format=response_format,
                _empty_content_retry=_empty_content_retry + 1,
            )
        raise WriterEmptyContentError(
            finish_reason=finish_reason,
            model=deepseek_service.runtime_model(),
            max_tokens=max_tokens,
            reasoning_content_len=len(reasoning_content),
            reasoning_tokens=reasoning_tokens,
            choices_count=len(choices),
        )
    return content, finish_reason


def _fallback_creation_pack(
    *,
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    previous_chapter_summary: str = "",
) -> dict[str, Any]:
    try:
        from services import deepseek as deepseek_service

        chapter_scope = deepseek_service._chapter_scope_from_context(story_context)
    except Exception:
        chapter_scope = {}
    pack = {
        "chapter_task": chapter_info,
        "continuity": previous_chapter_summary,
        "chapter_boundary": chapter_scope,
        "writer_brief": "只写当前章节任务卡中的事件，承接前文状态，保留章末钩子。",
        "must_keep": [],
        "do_not_write": ["不得提前兑现后续章节核心事件、资源收获、战斗胜负或冲突解决。"],
        "style_brief": "起点商业连载正文，冲突前置，对话推动，少解释，少总结。",
        "writing_rules": [
            f"正文有效字数验收区间为 {LOCAL_MIN_CHARS}-{LOCAL_MAX_CHARS} 字；正文 agent 写作目标 {WRITER_TARGET_MIN_CHARS}-{WRITER_TARGET_MAX_CHARS} 字，给模型自然扩写预留余量。",
            "只写当前章节任务，不提前兑现后续章节地点、资源、路线、探索、战斗或交易。",
            "章尾只停在当前事件余波、人物状态或未解压力上。",
        ],
        "target": {"min": LOCAL_MIN_CHARS, "ideal": LOCAL_IDEAL_CHARS, "max": LOCAL_MAX_CHARS},
        "scene_budget": _normalize_scene_budget(None),
    }
    return _ensure_completion_fields(pack)


_NEUTRAL_ENDING_HOOK = "章尾停在当前事件的即时结果、现实压力暂缓、身体代价、旁人注意或主角当下选择上。"

_PACK_BOUNDARY_STRONG_TERMS = {
    "黑吃黑", "黑市", "黑市交易", "交易变现", "残破阵基", "寂灭异兆",
    "寂灭仙力", "淬体突破", "淬体初成", "母亲病情", "母亲病情好转",
    "天机阁", "秘境深处", "入口坐标", "具体路线",
    "市场价", "卖价", "卖到", "卖钱", "售出", "估价", "行情", "来钱",
    "兑成", "换成现金", "出手材料", "摊位", "买家", "西北方向", "乱石坡",
    "明早", "明晚", "后天",
}

_PACK_BOUNDARY_GENERIC_TERMS = {
    "荒域", "秘境", "地图", "路线", "灵草", "灵药", "异兽", "猎杀",
    "采集", "采灵草", "精血", "兽骨", "交易", "探索", "战斗", "资源",
    "变现", "分布", "遗迹", "试炼",
}

_DIALOGUE_SOFT_RULE = (
    "对话要求：如当前场景自然出现其他人物，可安排1-3句短对白推动信息；"
    "独行、潜伏、战斗或采集章节不把对话句数作为硬性阻断，优先保证动作、因果和章节完成度。"
)

_DIALOGUE_HARD_PATTERN = re.compile(r"(缺少|至少|必须|补.*对话|[13三一]句|有效对话)")

_SOFT_BLOCKING_PATTERN = re.compile(
    r"(无|暂无|没有|无需|无须|不需要|不用|直接通过|可通过|仅|只需|轻微|微调|建议|保留建议|非阻断|不触发返修|无需返修|无须返修)",
    re.IGNORECASE,
)

_REAL_BLOCKING_PATTERN = re.compile(
    r"(剧情任务缺失|任务缺失|核心任务|核心事件|未完成|没有完成|缺少(?!对话)|缺失(?!对话)|"
    r"逻辑断裂|因果断裂|跑偏|偏离|越界|提前写|提前兑现|预支|后续章节完整场面|"
    r"字数.*(低于|不足|超出|过长|过短)|截断|断尾|残句|"
    r"必须(补|重写|返修|修复)|硬伤|阻断|不符合|不达标|未兑现|完整场面|交易流程|价格结算|"
    r"入口坐标|具体路线|实地踏入|资源闭环)",
    re.IGNORECASE,
)


def _pack_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_pack_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_pack_text(item) for item in value)
    return str(value or "")


def _is_dialogue_quota_issue(text: Any) -> bool:
    value = str(text or "")
    return "对话" in value and bool(_DIALOGUE_HARD_PATTERN.search(value))


def _blocking_payload(text: Any) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^(blocking_issues|rewrite_targets|revision_plan|findings|keep|fill|cut|forbid|length_action)\s*[:：]\s*", "", value, flags=re.IGNORECASE)
    return value.strip()


def _is_soft_blocking_text(text: Any) -> bool:
    """识别编辑报告里的软建议，避免把“无需返修”误当成硬伤。"""
    payload = _blocking_payload(text)
    if not payload:
        return True
    if payload.lower() in {"[]", "none", "no", "null", "n/a"}:
        return True
    if _is_dialogue_quota_issue(payload):
        return True
    has_soft_marker = bool(_SOFT_BLOCKING_PATTERN.search(payload))
    has_real_marker = bool(_REAL_BLOCKING_PATTERN.search(payload))
    return has_soft_marker and not has_real_marker


def _is_real_blocking_text(text: Any) -> bool:
    """只把会破坏正文可用性的意见视为硬阻断。"""
    payload = _blocking_payload(text)
    if not payload or _is_soft_blocking_text(payload):
        return False
    if _is_dialogue_quota_issue(payload):
        return False
    return bool(_REAL_BLOCKING_PATTERN.search(payload))


def _review_has_real_blocking_issue(review: dict[str, Any], content: str = "") -> bool:
    """统一判断编辑结果是否存在需要正文 agent 返修的真阻断。"""
    if not isinstance(review, dict):
        return True
    local = review.get("local_safety") if isinstance(review.get("local_safety"), dict) else {}
    hard_failures = local.get("hard_failures") if isinstance(local.get("hard_failures"), list) else []
    if hard_failures:
        return True
    if local and not bool(local.get("ok")):
        return True
    if content:
        char_count = count_chapter_chars(content)
        if char_count and not (LOCAL_MIN_CHARS <= char_count <= LOCAL_MAX_CHARS):
            return True
        if _content_looks_truncated(content):
            return True
    raw = review.get("raw") if isinstance(review.get("raw"), dict) else {}
    for field in ("blocking_issues", "length_action"):
        value = raw.get(field)
        values = value if isinstance(value, list) else [value]
        if any(_is_real_blocking_text(item) for item in values if item is not None):
            return True
    hard_values = review.get("hard_failures")
    if isinstance(hard_values, list) and hard_values:
        return True
    rewrite_brief = review.get("rewrite_brief") if isinstance(review.get("rewrite_brief"), list) else []
    for item in rewrite_brief:
        text = str(item)
        if any(marker in text for marker in ("blocking_issues", "硬伤", "必须重写", "必须返修")) and _is_real_blocking_text(text):
            return True
    return False


def _review_mentions_boundary_issue(review: dict[str, Any]) -> bool:
    """只有编辑明确指出边界兑现问题时，才启用本地章尾裁剪。"""
    if not isinstance(review, dict):
        return False
    raw = review.get("raw") if isinstance(review.get("raw"), dict) else {}
    texts: list[str] = []
    for field in ("blocking_issues", "rewrite_targets", "revision_plan", "cut", "length_action"):
        value = raw.get(field)
        if isinstance(value, list):
            texts.extend(str(item) for item in value if str(item).strip())
        elif str(value or "").strip():
            texts.append(str(value))
    for field in ("findings", "rewrite_brief", "revision_notes"):
        value = review.get(field)
        if isinstance(value, list):
            texts.extend(str(item) for item in value if str(item).strip())
    joined = "\n".join(texts)
    if not joined:
        return False
    return bool(re.search(r"(越界|预支|提前兑现|提前写|完整场面|交易流程|价格结算|入口坐标|具体路线|资源闭环)", joined))


def _is_usable_candidate(review: dict[str, Any], content: str) -> bool:
    if not content or _content_looks_truncated(content):
        return False
    return _score(review.get("overall_score")) >= 70


def _candidate_rank(review: dict[str, Any], content: str) -> tuple[float, int, int]:
    score = _score(review.get("overall_score"))
    char_count = count_chapter_chars(content)
    distance = abs(char_count - LOCAL_IDEAL_CHARS)
    approved_bonus = 100 if _review_is_hard_pass(review, content) else 0
    return score + approved_bonus, -distance, char_count


def _select_better_candidate(
    current: dict[str, Any] | None,
    *,
    content: str,
    review: dict[str, Any],
    attempts: int,
    finish_reason: Any,
    source: str,
) -> dict[str, Any] | None:
    if not _is_usable_candidate(review, content):
        return current
    candidate = {
        "content": content,
        "review": dict(review),
        "attempts": attempts,
        "finish_reason": finish_reason,
        "source": source,
    }
    if not current:
        return candidate
    if _candidate_rank(review, content) > _candidate_rank(current.get("review") or {}, current.get("content") or ""):
        return candidate
    return current


def _term_matches_current_scope_variant(term: str, current_text: str = "") -> bool:
    """识别后续边界词是否只是当前章节任务的短语变体。"""
    normalized = re.sub(r"\s+", "", str(term or ""))
    scope_text = re.sub(r"\s+", "", str(current_text or ""))
    if not normalized or not scope_text:
        return False
    if normalized in scope_text:
        return True
    if len(normalized) > 8:
        return False
    chunks = {
        normalized[index : index + 2]
        for index in range(max(0, len(normalized) - 1))
        if len(normalized[index : index + 2]) == 2
    }
    meaningful_hits = [
        chunk
        for chunk in chunks
        if re.search(r"[\u4e00-\u9fff]{2}", chunk) and chunk in scope_text
    ]
    return len(meaningful_hits) >= 2


def _is_useful_future_boundary_term(term: str, current_text: str = "") -> bool:
    """过滤碎片词和当前章通用领域词，只保留明确后续专有边界。"""
    term = re.sub(r"\s+", "", str(term or ""))
    if not term:
        return False
    if _term_matches_current_scope_variant(term, current_text):
        return False
    if term in _PACK_BOUNDARY_STRONG_TERMS:
        return True
    if term in _PACK_BOUNDARY_GENERIC_TERMS:
        return not (current_text and term in current_text)
    if len(term) < 3 or len(term) > 14:
        return False
    if re.search(r"[，。！？；：、（）【】《》\"'“”]", term):
        return False
    if term.startswith(("同时", "然后", "并且", "以及")):
        return False
    return True


def _future_boundary_terms(chapter_scope: dict[str, Any]) -> set[str]:
    """从后续章节卡中提取供伏笔上限与兑现边界判断的强边界词。"""
    if not isinstance(chapter_scope, dict):
        return set()
    future_cards = chapter_scope.get("future_chapters_for_boundary_only")
    if not isinstance(future_cards, list) or not future_cards:
        return set()

    allowed_text = _pack_text(chapter_scope.get("current_chapter_card"))
    allowed_text += " " + _pack_text(chapter_scope.get("previous_chapters_for_continuity"))
    terms: set[str] = set()
    source_texts: list[str] = []
    for card in future_cards[:6]:
        if not isinstance(card, dict):
            continue
        source_text = _pack_text({
            "title": card.get("title"),
            "summary": card.get("summary"),
            "goal": card.get("goal"),
            "conflict": card.get("conflict"),
            "payoff": card.get("payoff"),
            "highlight": card.get("highlight"),
        })
        source_texts.append(source_text)
        for anchor in set(_PACK_BOUNDARY_STRONG_TERMS) | set(_PACK_BOUNDARY_GENERIC_TERMS):
            if anchor in source_text and anchor not in allowed_text:
                terms.add(anchor)

    try:
        from services import deepseek as deepseek_service

        allowed_terms = deepseek_service._boundary_terms_from_text(allowed_text)
        for source_text in source_texts:
            for term in deepseek_service._boundary_terms_from_text(source_text) - allowed_terms:
                if (
                    deepseek_service._is_strong_boundary_term(term)
                    or term in _PACK_BOUNDARY_STRONG_TERMS
                ):
                    terms.add(term)
        return {term for term in terms if _is_useful_future_boundary_term(term, allowed_text)}
    except Exception as exc:
        logger.warning("创作包边界词提取失败: %s", exc)
        return {term for term in terms if _is_useful_future_boundary_term(term, allowed_text)}


def _boundary_hits(value: Any, terms: set[str]) -> list[str]:
    text = _pack_text(value)
    return sorted((term for term in terms if term and term in text), key=len, reverse=True)


def _text_has_future_drift(text: Any) -> bool:
    hook = str(text or "")
    if not hook:
        return False
    return bool(re.search(
        r"(明天|明日|明早|明晚|翌日|后天|改天|下一步|接下来|更长的路|未来行动|"
        r"黑市|交易|变现|路线|坐标|入口|深处|遗迹|突破|"
        r"市场价|卖价|卖到|卖钱|售出|估价|行情|来钱|出手|换钱|折现|兑成|换成现金|"
        r"后续利用|计划利用|利用方式|使用或出售|出售本次收获|"
        r"摊位|买家|西北方向|乱石坡|顶一阵|顶上一阵)",
        hook,
    ))


def _is_negative_boundary_context(text: str) -> bool:
    return any(marker in text for marker in (
        "禁止", "不得", "不要", "不能", "不可", "不应", "删除", "删去", "删掉", "移除", "压缩",
        "避免", "禁写", "预支", "边界", "不提前", "不能提前", "不得提前",
    ))


def _text_has_future_realization(text: Any) -> bool:
    """识别把后续章节直接兑现成行动的文本，区别于一句伏笔。"""
    value = str(text or "")
    if not value or _is_negative_boundary_context(value):
        return False
    future_time_or_action = re.search(
        r"(明天|明日|明早|明晚|翌日|后天|下一步|接下来|随后|准备去|打算去|计划去|前去|进入|找到|记下|"
        r"路线|坐标|入口|摊位|买家|黑市|交易|变现|卖到|卖钱|售出|估价|市场价|卖价|行情|出手|换钱|折现)",
        value,
    )
    completion_marker = re.search(
        r"(完成|解决|拿到|获得|采集|猎杀|战斗|兑现|卖出|换成|补上|顶上|闭环|资源|收获|变现|交易|去|前往|进入|路线|坐标|入口|乱石坡|深处|遗迹)",
        value,
    )
    if future_time_or_action and completion_marker:
        return True
    return bool(re.search(
        r"(明天|明日|明早|翌日|后天).{0,18}(去|前往|进入).{0,18}(黑市|摊位|买家|入口|坐标|路线|乱石坡|深处|遗迹)|"
        r"(明天|明日|明早|翌日|后天).{0,18}(黑市|交易|变现|摊位|买家|入口|坐标|路线|探索)|"
        r"(黑市|交易|变现|估价|市场价|卖价|卖到|按斤算).{0,24}(药费缺口|补上|顶上|换成|现金|资源闭环)|"
        r"(入口坐标|实地踏入|完成交易|交易变现|资源闭环|黑市变现)",
        value,
    ))


def _sanitize_list_field(items: Any, terms: set[str]) -> tuple[list[Any], list[str]]:
    if not isinstance(items, list):
        return [], []
    cleaned: list[Any] = []
    removed: list[str] = []
    for item in items:
        hits = _boundary_hits(item, terms)
        if _text_has_future_realization(item) or _text_mentions_boundary_terms(item, terms):
            removed.extend(hits or ["future_realization"])
        else:
            cleaned.append(item)
    return cleaned, sorted(set(removed), key=len, reverse=True)


def _text_mentions_boundary_terms(text: Any, terms: set[str]) -> bool:
    if not terms:
        return False
    hits = _boundary_hits(text, terms)
    if not hits:
        return False
    return not _is_negative_boundary_context(str(text or ""))


def _sanitize_scene_budget_field(items: Any, terms: set[str]) -> tuple[list[Any], list[str]]:
    if not isinstance(items, list):
        return [], []
    cleaned: list[Any] = []
    removed: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry_text = _pack_text({
            "scene": entry.get("scene"),
            "purpose": entry.get("purpose"),
            "goal": entry.get("goal"),
        })
        hits = _boundary_hits(entry_text, terms) if terms else []
        if _text_has_future_realization(entry_text) or _text_mentions_boundary_terms(entry_text, terms):
            removed.extend(hits or ["future_realization"])
            entry["scene"] = "当前事件余波与必要结算"
            entry["purpose"] = "只处理当前章节已经发生的结果、代价和压力；可留一句模糊伏笔，但不展开后续地点、交易或探索场面。"
            entry.pop("goal", None)
        cleaned.append(entry)
    return cleaned, sorted(set(removed), key=len, reverse=True)


def _sanitize_creation_pack_boundary(pack: dict[str, Any], chapter_scope: dict[str, Any]) -> dict[str, Any]:
    """净化创作包中误混入可写字段的后续章节信息。"""
    if not isinstance(pack, dict):
        return pack
    terms = _future_boundary_terms(chapter_scope)
    current_task_text = _pack_text({
        "current_chapter_card": chapter_scope.get("current_chapter_card") if isinstance(chapter_scope, dict) else {},
        "chapter_task": pack.get("chapter_task"),
    })
    raw_terms = set(terms)
    terms = {term for term in terms if _is_useful_future_boundary_term(term, current_task_text)}
    filtered_terms = sorted(raw_terms - terms, key=len, reverse=True)
    if filtered_terms:
        pack["boundary_term_filter"] = {
            "filtered_as_current_or_generic": filtered_terms,
        }

    removed_by_field: dict[str, list[str]] = {}
    for field in (
        "plot_beats",
        "hard_requirements",
        "closure_requirements",
        "writer_execution_order",
        "missing_if_absent",
        "must_keep",
        "reference_takeaways",
        "review_focus",
        "writing_rules",
        "acceptance_checklist",
        "rewrite_targets",
    ):
        cleaned, removed = _sanitize_list_field(pack.get(field), terms)
        if removed:
            pack[field] = cleaned
            removed_by_field[field] = removed
    cleaned_budget, removed_budget = _sanitize_scene_budget_field(pack.get("scene_budget"), terms)
    if removed_budget:
        pack["scene_budget"] = cleaned_budget
        removed_by_field["scene_budget"] = removed_budget

    if not terms:
        if _text_has_future_realization(pack.get("ending_hook")):
            pack["ending_hook"] = _NEUTRAL_ENDING_HOOK
            removed_by_field["ending_hook"] = ["future_realization"]
        if removed_by_field:
            pack["boundary_sanitization"] = {
                "removed_terms": sorted({term for values in removed_by_field.values() for term in values}, key=len, reverse=True),
                "fields": removed_by_field,
                "fallback_ending_hook": _NEUTRAL_ENDING_HOOK,
            }
        return pack

    string_fallbacks = {
        "ending_hook": _NEUTRAL_ENDING_HOOK,
        "style_brief": "起点商业连载正文，冲突前置，对话推动，少解释，少总结；章尾只停在当前事件余波。",
        "payoff_plan": "只兑现当前章节任务卡里的即时收益、压力缓解或关系变化；后续信息只能作为一句以内模糊伏笔，不提前展开场面。",
        "opening_strategy": "第一段直接进入当前章节动作、对白、冲突或异常，不用后续章节核心场面开场。",
    }
    for field, fallback in string_fallbacks.items():
        hits = _boundary_hits(pack.get(field), terms)
        if _text_has_future_realization(pack.get(field)) or _text_mentions_boundary_terms(pack.get(field), terms):
            pack[field] = fallback
            removed_by_field[field] = sorted(set(hits or ["future_realization"]), key=len, reverse=True)

    blocked_terms = sorted(
        (set(terms) | {term for values in removed_by_field.values() for term in values}) - {"future_drift", "future_realization"},
        key=len,
        reverse=True,
    )
    do_not_write = pack.get("do_not_write")
    if not isinstance(do_not_write, list):
        do_not_write = []
    boundary_note = "后续信息可作一句以内模糊伏笔，但禁止写进正文成为完整场面、路线、交易、战斗或资源闭环；编辑按语义审核：" + "、".join(blocked_terms[:16])
    if boundary_note not in do_not_write:
        do_not_write.insert(0, boundary_note)
    pack["do_not_write"] = do_not_write
    pack["future_boundary_terms"] = blocked_terms
    pack["future_foreshadowing_policy"] = (
        "允许正文在章尾或人物判断中保留一句以内后续压力/方向/危险感作为钩子；"
        "不允许把后续章节的地点推进、交易流程、价格结算、战斗胜负或资源闭环提前写成完整行动。"
    )
    if removed_by_field:
        pack["boundary_sanitization"] = {
            "removed_terms": sorted({term for values in removed_by_field.values() for term in values}, key=len, reverse=True),
            "fields": removed_by_field,
            "fallback_ending_hook": _NEUTRAL_ENDING_HOOK,
        }
    return pack


def _soften_dialogue_hard_rules(pack: dict[str, Any]) -> dict[str, Any]:
    """把对话硬指标降级，避免独行章节被不必要地打回。"""
    if not isinstance(pack, dict):
        return pack

    def soften_item(item: Any) -> str:
        text = str(item)
        if "对话" not in text:
            return text
        if _DIALOGUE_HARD_PATTERN.search(text) or re.search(r"(至少|必须|不少于|达到)", text):
            return _DIALOGUE_SOFT_RULE
        return text

    for field in ("writing_rules", "review_focus"):
        value = pack.get(field)
        if not isinstance(value, list):
            continue
        softened: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = soften_item(item).strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                softened.append(text)
        pack[field] = softened
    return pack


def _sanitize_editor_feedback(feedback: list[str], creation_pack: dict[str, Any]) -> list[str]:
    """过滤编辑意见中误引入的后续章节补写建议。"""
    terms = set(creation_pack.get("future_boundary_terms") or [])
    terms.update(_future_boundary_terms(creation_pack.get("chapter_boundary") or {}))

    cleaned: list[str] = []
    removed_terms: set[str] = set()
    dialogue_softened = False
    for item in feedback:
        text = str(item)
        hits = _boundary_hits(text, terms) if terms else []
        future_realization = _text_has_future_realization(text)
        if future_realization:
            removed_terms.update(hits or ["future_realization"])
            continue
        if "对话" in text and re.search(r"(至少|必须|不少于|达到|[13三一]句|有效对话)", text):
            dialogue_softened = True
            continue
        cleaned.append(text)
    if removed_terms:
        cleaned.insert(
            0,
            "忽略任何要求把后续章节地点、资源、探索、地图、路线、估价、黑市或交易写成完整场面的意见；忽略任何要求新增后续章节地点、资源、路线、探索或交易的完整场面；允许保留一句以内模糊伏笔，补字数只能补当前章节内的行动反馈、交锋、采集清点、结算和人物反应。",
        )
    if dialogue_softened:
        cleaned.insert(0, _DIALOGUE_SOFT_RULE)
    return cleaned


def _revision_feedback_for_writer(
    review: dict[str, Any],
    creation_pack: dict[str, Any],
    content: str,
) -> list[str]:
    """将编辑审阅压缩成正文 agent 只需要处理的真问题。"""
    if not isinstance(review, dict) or _review_is_hard_pass(review, content):
        return []
    if not content and not review:
        return []

    raw = review.get("raw") if isinstance(review.get("raw"), dict) else {}
    local = review.get("local_safety") if isinstance(review.get("local_safety"), dict) else {}
    char_count = count_chapter_chars(content)
    score = _score(review.get("overall_score"))
    source_items: list[str] = []
    for field in ("length_action", "blocking_issues", "keep", "fill", "cut", "forbid", "rewrite_targets", "revision_plan"):
        value = raw.get(field)
        if isinstance(value, str) and value.strip():
            source_items.append(f"{field}: {value.strip()}")
        elif isinstance(value, list):
            source_items.extend(f"{field}: {item}" for item in value if str(item).strip())
    if isinstance(review.get("rewrite_brief"), list):
        source_items.extend(str(item) for item in review["rewrite_brief"] if str(item).strip())
    elif isinstance(review.get("findings"), list):
        source_items.extend(str(item) for item in review["findings"] if str(item).strip())

    hard_failure_messages = [
        str(item.get("message") or item.get("code") or "").strip()
        for item in (local.get("hard_failures") if isinstance(local.get("hard_failures"), list) else [])
        if isinstance(item, dict) and str(item.get("message") or item.get("code") or "").strip()
    ]
    if hard_failure_messages:
        source_items = [f"blocking_issues: {item}" for item in hard_failure_messages] + source_items

    has_real_blocking = _review_has_real_blocking_issue(review, content)

    if not has_real_blocking and score >= EDITOR_PASS_SCORE and LOCAL_MIN_CHARS <= char_count <= LOCAL_MAX_CHARS:
        return []

    if _content_looks_truncated(content) and char_count > LOCAL_MAX_CHARS:
        source_items.insert(0, f"blocking_issues: 上一版超长且尾句疑似截断，必须压缩成 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字完整章节全文；禁止续写残尾或新增场景。")
    elif _content_looks_truncated(content):
        source_items.insert(0, "blocking_issues: 正文尾句疑似截断，必须在上一版全文基础上补完句子和章节收束，禁止只输出补丁。")
    elif score >= 75 and LOCAL_MIN_CHARS <= char_count <= LOCAL_MAX_CHARS:
        source_items.insert(0, "返修方式：上一版主体已可用，只做最小必要修复；必须输出完整章节全文，可以保留一句以内模糊伏笔，禁止新增后续章节完整事件。")
    elif content:
        source_items.insert(0, "返修方式：保留上一版有效正文为底稿，按下列阻断问题一次性修完；禁止只输出新增片段。")

    cleaned = _sanitize_editor_feedback(source_items, creation_pack)
    priority_markers = (
        "blocking_issues:",
        "length_action:",
        "cut:",
        "rewrite_targets:",
        "revision_plan:",
        "返修方式",
        "正文尾句疑似截断",
        "字数",
    )
    result: list[str] = []
    seen: set[str] = set()
    for item in cleaned:
        text = str(item).strip()
        if not text:
            continue
        if any(marker in text for marker in ("无须修改", "无需修改", "直接通过", "无需返修")):
            continue
        if _is_dialogue_quota_issue(text):
            continue
        if "blocking_issues" in text and not _is_real_blocking_text(text):
            continue
        if not has_real_blocking and not any(marker in text for marker in priority_markers):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= 10:
            break
    return result


async def build_chapter_creation_pack(
    *,
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    previous_chapter_summary: str = "",
    api_key: str | None = None,
    system_rules: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """前置创作 agent：把系统内置信息提炼成可执行创作包。"""
    started_at = time.perf_counter()
    trace = trace_id or uuid.uuid4().hex[:8]
    if api_key == "test":
        pack = _fallback_creation_pack(
            story_context=story_context,
            chapter_info=chapter_info,
            previous_chapter_summary=previous_chapter_summary,
        )
        pack = _inject_resolved_knowledge_constraints(pack, story_context)
        logger.info(
            "chapter_pipeline.pack.fallback trace_id=%s chapter=%s elapsed_ms=%s reason=test_api_key summary=%s",
            trace,
            _chapter_label(chapter_info),
            _elapsed_ms(started_at),
            _pack_log_summary(pack),
        )
        logger.info(
            "chapter_pipeline.pack.summary.zh trace_id=%s chapter=%s detail=%s",
            trace,
            _chapter_label(chapter_info),
            _compact_json(_pack_log_zh_summary(pack), 12000),
        )
        return pack

    from services import deepseek as deepseek_service

    chapter_scope = deepseek_service._chapter_scope_from_context(story_context)
    source_digest, input_budget = _build_creation_pack_source_digest(
        story_context=story_context,
        chapter_info=chapter_info,
        previous_chapter_summary=previous_chapter_summary,
        chapter_scope=chapter_scope,
        system_rules=system_rules,
    )
    logger.info(
        "chapter_pipeline.pack.start trace_id=%s chapter=%s source_digest_chars=%s rules_chars=%s previous_summary_chars=%s future_cards=%s",
        trace,
        _chapter_label(chapter_info),
        input_budget.get("total", 0),
        input_budget.get("system_rules_digest", 0),
        len(previous_chapter_summary or ""),
        _list_len(chapter_scope.get("future_chapters_for_boundary_only") if isinstance(chapter_scope, dict) else None),
    )
    logger.info(
        "chapter_pipeline.pack.input_budget trace_id=%s chapter=%s detail=%s",
        trace,
        _chapter_label(chapter_info),
        _compact_json(input_budget, 4000),
    )

    source_digest_prompt = _compact_json(source_digest, 9000)
    logger.info(
        "chapter_pipeline.pack.prompt_budget trace_id=%s chapter=%s source_digest_prompt_chars=%s",
        trace,
        _chapter_label(chapter_info),
        len(source_digest_prompt),
    )

    user_prompt = f"""请把下面所有素材整理成“当前章节创作包”。你不是正文作者，不写正文，只做提炼、取舍、避雷。

## 需要整理的信息
1. 上下文连续性记忆、作品圣经、角色设定、大纲设定、章节规划。
2. 拆书报告或作者画像引用，如果有，只提取本章可复用的情绪模块、节奏、语言风格。
3. 用户自定义提示词和系统内置规则，只提炼为少量写作提醒。⚠️ 但以下 4 条核心禁令必须在 writing_rules 中逐字保留至少一条："全文禁止破折号（——）"、"禁止模板化短语（眼中闪过一丝/嘴角勾起一抹/心中涌起/心头一震/心底泛起/深吸一口气）"、"禁止情绪词直写（愤怒/悲伤/害怕/紧张/委屈/绝望），用身体反应代替"、"禁止突然/忽然/瞬间/猛地/仿佛/犹如/宛若/不禁/不由自主/不由得"。
4. 后续章节信息用于判断“伏笔上限”和“兑现边界”：可以提炼成一句以内模糊钩子，但不能写成当前章必须完成的 plot_beats、must_keep 或后续完整场面。
5. 必须把字数要求、章节边界、返修优先级、文风节奏限制整理成 writing_rules，供正文 agent 直接执行。
6. 创作包要足够完整，让正文 agent 首稿就能完成高质量正文，避免靠多轮返修补救。
7. 创作包不是大纲摘要，而是正文验收合同：必须把“本章必须发生什么、必须结算什么、缺什么必打回”拆成可检查条目。
8. hard_requirements 必须列出 3-6 个当前章硬性动作，优先来自章节规划、当前章节任务卡、连续性记忆和大纲，不要写泛泛的“保持节奏”。
9. closure_requirements 必须列出 3-5 个闭环动作，例如采集/清理/撤离/归置/清点/代价/压力变化/关系变化；按本章题材选择具体动作。
10. writer_execution_order 必须给正文 agent 一个执行顺序，确保核心冲突完成后仍继续写回报结算和章尾余波。
11. missing_if_absent 必须写清哪些缺失会被编辑打回；尤其“只写完战斗/交锋但未写回报结算和处理动作”必须打回。
12. plot_beats 必须 6-8 个，最多 8 个；每个情节点必须承载动作、冲突、信息变化或结算功能，不要把可一句带过的过场拆成多个情节点。
13. scene_budget 目标总和优先 {SCENE_BUDGET_IDEAL_TOTAL}-{SCENE_BUDGET_SOFT_MAX_TOTAL} 字，上限总和不得超过 {SCENE_BUDGET_HARD_MAX_TOTAL} 字，且第4、5个场景是硬场景，不是可选尾声，必须为“兑现回报与必要结算 + 章尾余波”预留 500-650 字。
14. acceptance_checklist 必须 6-10 条，必须覆盖硬性动作、剧情闭环、字数、边界、连续性、回报结算、章尾余波和输出完整章节全文。
15. source_digest 已经是系统筛过的章节相关信息；如果字段缺失，不要从后续章节补当前章内容。
16. 第5个场景/章尾优先写当前压力、身体代价、材料入袋/清点和即时余波；如需使用后续章节信息，只能作为一句以内模糊伏笔，不能提前完成交易、估价、路线、探索或战斗兑现。
17. **用户指令优先**：如果 current_chapter_task 包含 user_instruction 字段，该指令是用户明确提出的创作要求，必须作为 hard_requirements 的首项写入，并在 plot_beats、writing_rules、style_brief 和 acceptance_checklist 中逐项落实。不可降级为建议，不可因字数或结构原因忽略。
18. **核心禁令保护**：writing_rules 中必须包含至少一条破折号禁止（全文禁止破折号——）和至少一条模板化AI短语禁止（眼中闪过一丝/嘴角勾起一抹/心中涌起等），优先级高于其他写作提醒。如果 writing_rules 已满 6 条，用核心禁令替换最低优先级条目。

## 输出体积硬限制
- JSON 总长度必须控制在 3600-5200 个汉字以内，宁可短而准，不能写成长篇分析。
- 每个数组条目必须是可执行短句，单条不超过 36 个汉字；禁止解释原因、禁止展开世界观。
- continuity 最多3条，character_states最多4条，plot_beats固定6条，hard_requirements最多5条，closure_requirements最多4条。
- writer_execution_order最多6条，missing_if_absent最多5条，writing_rules最多6条，acceptance_checklist最多8条。
- reference_takeaways最多3条，must_keep最多6条，do_not_write最多5条，review_focus最多5条。
- style_brief不超过100字，opening_strategy/ending_hook/payoff_plan/emotion_goal各不超过60字。
- scene_budget 固定5项，总 target_chars 约 {SCENE_BUDGET_IDEAL_TOTAL} 字；不要自行增加场景。

## 章节相关信息包 source_digest
{source_digest_prompt}

请只输出 JSON：
{{
  "chapter_task": {{}},
  "continuity": ["承接前文时必须保留的事实"],
  "character_states": ["本章相关人物当前状态"],
  "plot_beats": ["按正文顺序排列的 6-8 个情节点，每点写清动作、冲突、信息变化或结算功能"],
  "emotion_goal": "本章要交付的读者情绪",
  "payoff_plan": "本章爽点/回报如何兑现，若无显性爽点则写功能",
  "hard_requirements": ["当前章必须完成的 3-6 个硬性动作，必须具体到动作或结果，缺任一项编辑应打回"],
  "closure_requirements": ["当前章必须完成的 3-5 个闭环动作，例如采集、清理、撤离、归置、清点、代价、压力变化或关系变化"],
  "writer_execution_order": ["正文 agent 必须按顺序执行的写作步骤，必须包含核心冲突后进入回报结算、章尾余波后停笔"],
  "missing_if_absent": ["正文缺少这些内容时编辑必须打回的项目，尤其包含回报结算、处理动作、章尾余波和边界越界"],
  "opening_strategy": "第一段如何直接进入动作、对白、冲突或异常",
  "ending_hook": "章尾停在当前章节事件的余波、人物选择或未解压力上；可留一句以内模糊伏笔，但不能提前兑现后续章节完整场面",
  "style_brief": "给正文作者的文风和节奏提醒，控制在 100 字内",
  "writing_rules": ["正文 agent 必须遵守的创作规则，包含字数区间、章节边界、返修优先级、禁止事项和节奏要求"],
  "scene_budget": [
    {{"scene": "开场承接与目标压迫", "purpose": "本场景功能", "target_chars": 220, "max_chars": 280}},
    {{"scene": "入场观察与策略形成", "purpose": "本场景功能", "target_chars": 320, "max_chars": 390}},
    {{"scene": "核心冲突与关键转折", "purpose": "本场景功能，必须在约1500-1650字前结束胜负", "target_chars": 740, "max_chars": 820}},
    {{"scene": "兑现回报与必要结算", "purpose": "本场景功能，不是尾声补丁", "target_chars": 560, "max_chars": 560}},
    {{"scene": "章尾余波与当前钩子", "purpose": "本场景功能，可留一句以内模糊伏笔，但不展开估价、交易、黑市、明日行动或后续地点场面", "target_chars": 260, "max_chars": 260}}
  ],
  "completion_contract": {{
    "pass_score": {EDITOR_PASS_SCORE},
    "target_chars": {{"min": {LOCAL_MIN_CHARS}, "ideal": {LOCAL_IDEAL_CHARS}, "max": {LOCAL_MAX_CHARS}}},
    "writer_target_chars": {{"min": {WRITER_TARGET_MIN_CHARS}, "ideal": {LOCAL_IDEAL_CHARS}, "max": {WRITER_TARGET_MAX_CHARS}}},
    "writer_output": "每轮必须输出完整章节全文，不输出补丁或续写尾巴",
    "revision_policy": "编辑问题包一次性处理，避免先改字数再二次审稿",
    "boundary_policy": "当前章节必须闭环；后续章节可作一句以内模糊伏笔，不提前兑现完整场面",
    "execution_policy": "正文必须先完成 hard_requirements，再完成 closure_requirements；只完成核心冲突不算章节完成"
  }},
  "acceptance_checklist": [
    "正文写完前必须逐项自检的验收项，6-10条，包含剧情闭环、字数、边界、连续性、爽点/回报、章尾余波和完整全文输出"
  ],
  "reference_takeaways": ["拆书/作者画像可用技巧，没有则为空数组"],
  "must_keep": ["必须写进正文的关键因果"],
  "do_not_write": ["不得提前兑现成完整场面的后续事件、地点推进、资源获取或冲突解决"],
  "chapter_boundary": {{}},
  "target": {{"min": {LOCAL_MIN_CHARS}, "ideal": {LOCAL_IDEAL_CHARS}, "max": {LOCAL_MAX_CHARS}}},
  "review_focus": ["编辑审阅时重点检查什么"]
}}"""

    content, finish_reason = await _chat_completion(
        messages=[
            {"role": "system", "content": "你是小说创作前置统筹，擅长从复杂素材中提炼当前章节创作包。只输出严格 JSON。"},
            {"role": "user", "content": user_prompt},
        ],
        api_key=api_key,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )
    try:
        pack = deepseek_service._extract_json_object(content)
    except Exception as exc:
        logger.warning("创作包 agent 输出解析失败，使用本地创作包兜底: %s", exc)
        logger.warning(
            "chapter_pipeline.pack.parse_failed trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s error=%s",
            trace,
            _chapter_label(chapter_info),
            _elapsed_ms(started_at),
            finish_reason,
            exc,
        )
        pack = None
        if finish_reason == "length":
            retry_prompt = f"""上一次创作包 JSON 输出过长被截断。请基于同一份 source_digest 重新输出极简但可执行的当前章节创作包。

硬限制：
- 只输出 JSON，不输出解释。
- 总长度不超过 4200 汉字；每条数组项不超过 32 汉字。
- plot_beats 固定6条；hard_requirements 4-5条；closure_requirements 3-4条；acceptance_checklist 6-8条。
- 必须保留当前章硬动作、回报结算、字数、边界和章尾余波。

source_digest:
{source_digest_prompt}

JSON 字段：
chapter_task, continuity, character_states, plot_beats, emotion_goal, payoff_plan,
hard_requirements, closure_requirements, writer_execution_order, missing_if_absent,
opening_strategy, ending_hook, style_brief, writing_rules, scene_budget,
completion_contract, acceptance_checklist, reference_takeaways, must_keep,
do_not_write, chapter_boundary, target, review_focus。"""
            try:
                retry_content, retry_finish_reason = await _chat_completion(
                    messages=[
                        {"role": "system", "content": "你是小说创作前置统筹。只输出紧凑、合法、可解析 JSON。"},
                        {"role": "user", "content": retry_prompt},
                    ],
                    api_key=api_key,
                    max_tokens=8192,
                    response_format={"type": "json_object"},
                )
                pack = deepseek_service._extract_json_object(retry_content)
                logger.info(
                    "chapter_pipeline.pack.retry_done trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s summary=%s",
                    trace,
                    _chapter_label(chapter_info),
                    _elapsed_ms(started_at),
                    retry_finish_reason,
                    _pack_log_summary(pack),
                )
            except Exception as retry_exc:
                logger.warning(
                    "chapter_pipeline.pack.retry_failed trace_id=%s chapter=%s elapsed_ms=%s error=%s",
                    trace,
                    _chapter_label(chapter_info),
                    _elapsed_ms(started_at),
                    retry_exc,
                )
        if not isinstance(pack, dict):
            pack = _fallback_creation_pack(
                story_context=story_context,
                chapter_info=chapter_info,
                previous_chapter_summary=previous_chapter_summary,
            )
            pack = _inject_resolved_knowledge_constraints(pack, story_context)
            logger.info(
                "chapter_pipeline.pack.fallback trace_id=%s chapter=%s elapsed_ms=%s reason=parse_failed summary=%s",
                trace,
                _chapter_label(chapter_info),
                _elapsed_ms(started_at),
                _pack_log_summary(pack),
            )
            logger.info(
                "chapter_pipeline.pack.summary.zh trace_id=%s chapter=%s detail=%s",
                trace,
                _chapter_label(chapter_info),
                _compact_json(_pack_log_zh_summary(pack), 12000),
            )
            return pack
    pack_boundary = pack.get("chapter_boundary")
    if (
        (not isinstance(pack_boundary, dict) or not pack_boundary.get("future_chapters_for_boundary_only"))
        and chapter_scope
    ):
        pack["chapter_boundary"] = chapter_scope
    pack = _sanitize_creation_pack_boundary(pack, pack.get("chapter_boundary") if isinstance(pack.get("chapter_boundary"), dict) else chapter_scope)
    pack = _soften_dialogue_hard_rules(pack)
    pack = _ensure_scene_budget(pack)
    pack = _ensure_completion_fields(pack)
    do_not_write = pack.get("do_not_write")
    if not isinstance(do_not_write, list):
        do_not_write = []
    boundary_reminder = "可用一句以内模糊伏笔承接后续压力，但不得提前写后续地点的入口坐标、具体路线、实地踏入、资源采集、异兽遭遇、战斗兑现或交易变现。"
    if boundary_reminder not in do_not_write:
        do_not_write.append(boundary_reminder)
    pack["do_not_write"] = do_not_write
    pack["boundary_priority"] = (
        "do_not_write 和 chapter_boundary 是章节边界合同，高于 plot_beats、ending_hook、style_brief，"
        "也高于编辑意见中误加入的后续章节补写建议；编辑打回意见只能在当前章节边界内执行。"
        "如果创作包或编辑意见内部出现冲突，正文作者必须删去后续章节的完整行动兑现，"
        "但可以保留一句以内模糊伏笔，章尾优先停在当前事件余波、人物状态或未解压力上。"
    )
    pack.setdefault("chapter_task", chapter_info)
    pack.setdefault("target", {"min": LOCAL_MIN_CHARS, "ideal": LOCAL_IDEAL_CHARS, "max": LOCAL_MAX_CHARS})
    pack = _ensure_scene_budget(pack)
    pack = _ensure_completion_fields(pack)
    pack = _inject_resolved_knowledge_constraints(pack, story_context)
    pack.setdefault(
        "writing_rules",
        [
            f"正文有效字数必须控制在 {LOCAL_MIN_CHARS}-{LOCAL_MAX_CHARS} 字，理想约 {LOCAL_IDEAL_CHARS} 字。",
            "只写当前章节任务；后续内容可作一句以内模糊伏笔，不提前兑现 do_not_write 或 chapter_boundary 中标记的完整事件。",
            "返修时一次性处理字数、边界、剧情执行、节奏、角色声音和 AI 味。",
        ],
    )
    logger.info(
        "chapter_pipeline.pack.done trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s summary=%s",
        trace,
        _chapter_label(chapter_info),
        _elapsed_ms(started_at),
        finish_reason,
        _pack_log_summary(pack),
    )
    logger.info(
        "chapter_pipeline.pack.detail trace_id=%s chapter=%s detail=%s",
        trace,
        _chapter_label(chapter_info),
        _compact_json(_pack_log_detail(pack), 20000),
    )
    logger.info(
        "chapter_pipeline.pack.summary.zh trace_id=%s chapter=%s detail=%s",
        trace,
        _chapter_label(chapter_info),
        _compact_json(_pack_log_zh_summary(pack), 12000),
    )
    return pack


async def write_chapter_from_pack(
    *,
    creation_pack: dict[str, Any],
    api_key: str | None = None,
    editor_feedback: list[str] | None = None,
    previous_draft: str = "",
    trace_id: str | None = None,
) -> dict[str, Any]:
    """正文 agent：只基于创作包写正文或返修。"""
    started_at = time.perf_counter()
    trace = trace_id or uuid.uuid4().hex[:8]
    chapter_task = creation_pack.get("chapter_task") if isinstance(creation_pack, dict) else {}
    previous_char_count = count_chapter_chars(previous_draft)
    feedback_count = _list_len(editor_feedback)
    max_tokens = _writer_max_tokens(previous_char_count, bool(editor_feedback))
    logger.info(
        "chapter_pipeline.writer.start trace_id=%s chapter=%s revision=%s feedback_count=%s previous_chars=%s max_tokens=%s scene_budget_total=%s",
        trace,
        _chapter_label(chapter_task),
        bool(editor_feedback or previous_draft),
        feedback_count,
        previous_char_count,
        max_tokens,
        sum(int(item.get("target_chars") or 0) for item in _normalize_scene_budget(creation_pack)),
    )
    if api_key == "test":
        text = previous_draft or "林墨推开门，血腥味从院子里扑出来。"
        filler = "他抬手按住门框，听见屋内有人低声叫他的名字。"
        while count_chapter_chars(text) < 2300:
            text += filler
        logger.info(
            "chapter_pipeline.writer.done trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s chars=%s heading_stripped=%s test_mode=%s",
            trace,
            _chapter_label(chapter_task),
            _elapsed_ms(started_at),
            "stop",
            count_chapter_chars(text),
            False,
            True,
        )
        return {"content": text, "finish_reason": "stop"}

    feedback_block = ""
    if editor_feedback:
        editor_feedback = _sanitize_editor_feedback([str(item) for item in editor_feedback[:12]], creation_pack)
        logger.info(
            "chapter_pipeline.writer.feedback trace_id=%s chapter=%s detail=%s",
            trace,
            _chapter_label(chapter_task),
            _compact_json(_compact_items(editor_feedback, item_limit=260, list_limit=12), 8000),
        )
        feedback_block = "\n## 编辑打回意见\n- " + "\n- ".join(editor_feedback)
        feedback_block += (
            "\n\n## 本轮综合返修原则\n"
            "- 编辑意见是一份完整问题包，必须一次性处理字数、边界、剧情执行、节奏、角色声音、逻辑和 AI 味，不允许只修其中一项。\n"
            "- 返修输出仍然必须是完整章节全文，不是补丁、不是新增片段、不是结尾续写；上一版有效正文默认保留并做最小必要改动。\n"
            "- 如果编辑意见包含“无需修改”“直接通过”“只补一句”“微调”等内容，也必须在上一版全文基础上输出完整章节，禁止只输出被修改的句子。\n"
            f"- 如果上一版已经在 {LOCAL_MIN_CHARS}-{LOCAL_MAX_CHARS} 字内且编辑意见接近通过，只做最小修复：补完整断句、替换禁用词或微调一两处表达，必须保留上一版全文主体。\n"
            "- 返修顺序：先守住 do_not_write/chapter_boundary 的兑现边界和字数硬线，再修剧情漏点与因果，再压节奏、去总结腔、补角色反应。\n"
            "- 如果上一版超长，先做结构性删减，再在保留下来的场景里完成所有编辑要求；不要通过新增场景解决问题。\n"
            "- 如果上一版偏短，只补当前章节内的必要交锋、结算、选择、身体代价和旁人反应；可以保留一句以内模糊伏笔，禁止补后续章节资源或探索的完整场面。"
        )
        if any("预支" in str(item) or "future" in str(item).lower() or "边界" in str(item) for item in editor_feedback):
            feedback_block += (
                "\n\n## 本轮边界返修优先级\n"
                "- 这是边界返修，do_not_write 和编辑意见高于创作包里的 ending_hook 或 plot_beats。\n"
                "- 删除编辑指出的后续章节完整场面、探索行动、资源兑现、具体路线和交易流程；不要换个同义词继续写。\n"
                "- 章尾改停在当前事件余波：奖金、药费、身体代价、旁人注意、主角当下选择或未解压力；如需钩子，只保留一句以内模糊压力或方向。"
            )
        if previous_char_count > LOCAL_MAX_CHARS or any("字数" in str(item) or "length" in str(item) or "超过" in str(item) for item in editor_feedback):
            feedback_block += (
                "\n\n## 本轮返修优先级\n"
                f"- 这是综合减法返修，不是扩写重写；压缩到 {WRITER_TARGET_MIN_CHARS}-{WRITER_REVISION_TARGET_MAX_CHARS} 字的同时完成编辑指出的剧情、节奏、角色和边界问题。\n"
                "- 优先删除战斗后的尾声复盘、重复观众反应、重复走位、测力/报名的旁枝细节。\n"
                "- 保留核心因果链，不要为了凑字新增场景、地点、人物或设定解释。"
            )
    previous_block = ""
    if previous_draft:
        label = "上一版超长正文（只供删减取材，不要扩写）" if previous_char_count > LOCAL_MAX_CHARS else "上一版正文（只用于按编辑意见返修，不要机械复述）"
        previous_block = f"\n## {label}\n" + _clip_text(previous_draft, 11000)
    canonical_content = canonical_pack_content(creation_pack)
    scene_budget = [] if canonical_content is not None else _normalize_scene_budget(creation_pack)
    scene_budget_lines = [
        f"- {item['scene']}：目标约 {item['target_chars']} 字，上限 {item['max_chars']} 字；{item.get('purpose') or '只完成本场景功能'}"
        for item in scene_budget
    ]
    scene_budget_block = "\n## 场景字数预算\n" + "\n".join(scene_budget_lines) if scene_budget_lines else ""
    pack_prompt = _creation_pack_prompt_text(creation_pack, 14000)
    canonical_requirements = "" if canonical_content is not None else (
        "- 写完前必须在内部按 completion_contract 和 acceptance_checklist 自检一遍，但不要把自检过程输出。\n"
        "- 动笔前先读取 hard_requirements、closure_requirements、writer_execution_order、missing_if_absent；正文必须逐项完成这些硬合同。\n"
        "- 核心冲突、战斗、交锋或胜负结束不等于章节完成；只有回报结算、处理动作、当前事件余波都写完才算完成。\n"
        "- closure_requirements 里的采集、清理、撤离、归置、清点、确认安全等动作必须用正文显性动作写出来，不能只用心理判断、总结句或一句“处理完毕”代替。"
    )

    user_prompt = f"""你只需要根据“创作包”写出当前章节正文。

## 创作包
{pack_prompt}
{scene_budget_block}
{feedback_block}
{previous_block}

## 输出要求
- 直接输出正文，不要标题、Markdown、说明、JSON、字数统计。
{canonical_requirements}
- 自检未通过时直接在本轮正文内修完，不要把问题留给编辑 agent；尤其不能缺剧情闭环、结算和章尾余波。
- 如果这是返修轮，仍然输出完整章节全文；禁止只输出新增段落、差异片段、修改说明或续写尾巴。
- 如果编辑反馈写着“无需修改”“直接通过”“只补一句”“微调”，请直接以上一版正文为底稿输出完整全文，只做对应最小修复。
- 正文目标约 {LOCAL_IDEAL_CHARS} 字，推荐落在 {WRITER_TARGET_MIN_CHARS}-{WRITER_TARGET_MAX_CHARS} 字；{LOCAL_MAX_CHARS} 字是绝对上限，超过会被编辑打回。
- 首稿强目标是 {WRITER_TARGET_MIN_CHARS}-{WRITER_TARGET_MAX_CHARS} 字；不要把正文写到上限附近再匆忙收尾。
- 首稿必须按“场景字数预算”分配篇幅：前置准备和入场观察不得挤占核心冲突，必须给兑现回报、必要结算和章尾余波预留 400-600 字。
- 核心冲突最多占总字数 40%-45%；前置准备加入场观察合计尽量不超过 650-750 字。
- 如果某个预算场景写完功能但未到目标字数，直接进入下一场景；不要为了凑满预算追加解释、复盘、环境描写或同类动作。
- 首稿不要把每个情节点都铺满，优先用 {WRITER_TARGET_MIN_CHARS}-{WRITER_TARGET_MAX_CHARS} 字完成完整因果；重要动作写实，过场和环境一句带过。
- 必须先写完回报结算和章尾余波再停；接近 2500 字后只允许收束，不再新增动作链、地点、人物或设定。
- 写到 1600-1800 字必须结束核心冲突、胜负或阶段性结果，并进入回报结算；正文 75% 前必须开始结算。
- 写到约 2000 字后，优先检查 missing_if_absent 和 closure_requirements；若还有缺项，立刻压缩战斗复盘和解释句，把篇幅交给闭环动作。
- 回报结算不能留到最后 200 字，也不能只用一句话补丁处理；必须写清当前章节的收获、采集/清点、身体代价或压力变化。
- 写到 2400 字后只能收束，禁止继续展开战斗或新动作链。
- 优先级：do_not_write/chapter_boundary > 编辑意见里的新增建议 > plot_beats/ending_hook；编辑意见只能在当前章节边界内执行，若建议补后续地点、资源、地图、路线、探索或交易的完整场面，必须忽略。
- 优先写人物行动、对话、冲突、选择和后果；少解释设定，少景物铺陈。
- 每个功能场景只写必要细节：入场/报名/观察/交锋/兑现/钩子都要有，但不要把同类动作反复展开。
- 收到编辑打回时，必须把编辑问题包当成一次性返修任务：同一版里同时解决字数、边界、剧情缺口、节奏拖沓、角色声音和 AI 味。
- 如果写到章末钩子时正文已接近 2400 字，完成钩子后立刻停笔，不要追加复盘、感慨或路上尾声。
- 返修时只保留上一版中真正有效的动作和对话，禁止新增创作包没有要求的回家、翻笔记、入口坐标、具体路线等尾声。
- 只能完成创作包里的当前章节事件；后续信息可作为一句以内模糊伏笔，不要提前兑现 do_not_write 中的完整事件。
- 如果创作包指定钩子已经展开 do_not_write 或后续章节完整场面，改成当前事件余波或一句以内模糊伏笔，完成后立刻停笔。"""

    content, finish_reason = await _chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是起点白金作家，长于商业连载正文。你不负责审稿，也不重新规划大纲，"
                    "只把前置创作包写成有冲突、有节奏、有角色声音的完整正文。"
                    "你必须把 hard_requirements、closure_requirements、writer_execution_order 和 missing_if_absent 当作写作合同；"
                    "闭环动作必须用可见动作落地，尤其采集、清理、撤离、清点和确认安全不能省略；"
                    "只写完核心冲突但漏掉结算、处理动作或章尾余波，视为失败稿。"
                    "返修时必须按编辑完整问题包一次性解决，不能只修字数或只修某一个问题；禁止输出章节标题。"
                    "当创作包与编辑意见或禁止清单冲突时，必须服从编辑意见和禁止清单的兑现边界。"
                    "\n\n## 🚫 写作禁令（不可绕过，违规即废稿）\n"
                    "1. 全文禁止任何破折号（——），用逗号、句号或冒号代替。\n"
                    "2. 禁止突然/忽然/瞬间/猛地/仿佛/犹如/宛若/不禁/不由自主/不由得。\n"
                    "3. 禁止模板化短语：眼中闪过一丝/嘴角勾起一抹/心中涌起/心头一震/心底泛起/深吸一口气。\n"
                    "4. 禁止情绪词直写（愤怒/悲伤/害怕/紧张/委屈/绝望），用身体反应和行为展现。\n"
                    "5. 禁止「他感到/他觉得/他意识到/他明白/他知道」等告知式心理描写。\n"
                    "6. 禁止以时间/天气/景色开篇，第一句必须是事件/对话/冲突/异常。\n"
                    "7. 禁止总结式结尾、哲理升华收束章节，章末必须是动作、余波或钩子。\n"
                    "8. 禁止连续3句以上纯景物描写。\n"
                    "9. 对话必须口语化，禁止所有角色说话风格雷同；整章至少3句有效对话。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        api_key=api_key,
        max_tokens=max_tokens,
    )
    from services import deepseek as deepseek_service

    cleaned = _strip_generated_heading(deepseek_service._sanitize_novel_content(content))
    cleaned, local_changes = _sanitize_writer_output_locally(cleaned)
    if local_changes:
        logger.info(
            "chapter_pipeline.writer.local_sanitize trace_id=%s chapter=%s changes=%s chars=%s",
            trace,
            _chapter_label(chapter_task),
            sorted(set(local_changes)),
            count_chapter_chars(cleaned),
        )
    logger.info(
        "chapter_pipeline.writer.done trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s chars=%s heading_stripped=%s test_mode=%s",
        trace,
        _chapter_label(chapter_task),
        _elapsed_ms(started_at),
        finish_reason,
        count_chapter_chars(cleaned),
        cleaned != content,
        False,
    )
    return {"content": cleaned, "finish_reason": finish_reason}


async def review_chapter_with_editor_agent(
    *,
    creation_pack: dict[str, Any],
    content: str,
    api_key: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """编辑 agent：结合创作包和正文审阅，90 分以上才通过。"""
    started_at = time.perf_counter()
    trace = trace_id or uuid.uuid4().hex[:8]
    chapter_task = creation_pack.get("chapter_task") if isinstance(creation_pack, dict) else {}
    local = _local_safety_review(content, creation_pack.get("chapter_boundary"))
    logger.info(
        "chapter_pipeline.editor.start trace_id=%s chapter=%s chars=%s local_ok=%s hard_failure_codes=%s soft_warning_codes=%s",
        trace,
        _chapter_label(chapter_task),
        local.get("char_count"),
        local.get("ok"),
        [item.get("code") for item in local.get("hard_failures", []) if isinstance(item, dict)],
        [item.get("code") for item in local.get("soft_warnings", []) if isinstance(item, dict)],
    )
    skip_remote, skip_reason = _should_skip_remote_editor(local)
    if skip_remote:
        review = _local_failure_review(local, skip_reason=skip_reason)
        logger.info(
            "chapter_pipeline.editor.skipped trace_id=%s chapter=%s elapsed_ms=%s reason=%s summary=%s",
            trace,
            _chapter_label(chapter_task),
            _elapsed_ms(started_at),
            skip_reason,
            _review_log_summary(review),
        )
        logger.info(
            "chapter_pipeline.editor.detail trace_id=%s chapter=%s detail=%s",
            trace,
            _chapter_label(chapter_task),
            _compact_json(_review_log_detail(review), 12000),
        )
        return review
    if api_key == "test":
        review = {
            "approved": local["ok"],
            "overall_score": 95 if local["ok"] else 60,
            "scores": {"overall": 95 if local["ok"] else 60},
            "findings": [item["message"] for item in local["hard_failures"]],
            "rewrite_brief": [item["message"] for item in local["hard_failures"]],
            "local_safety": local,
            "skipped": True,
        }
        logger.info(
            "chapter_pipeline.editor.done trace_id=%s chapter=%s elapsed_ms=%s test_mode=%s summary=%s",
            trace,
            _chapter_label(chapter_task),
            _elapsed_ms(started_at),
            True,
            _review_log_summary(review),
        )
        logger.info(
            "chapter_pipeline.editor.detail trace_id=%s chapter=%s detail=%s",
            trace,
            _chapter_label(chapter_task),
            _compact_json(_review_log_detail(review), 12000),
        )
        return review

    user_prompt = f"""你是起点资深编辑，请结合“创作包”和“正文”审阅。只输出 JSON。

## 审阅标准
- 必须确认正文是否完整执行创作包，不跑偏，不提前兑现后续章节核心事件。
- 必须逐项核对 hard_requirements、closure_requirements、writer_execution_order、missing_if_absent；任一硬性动作或闭环动作缺失，都必须写入 blocking_issues。
- 即使本地底线检查已经发现字数过短、过长或边界软提示，也必须继续完整审阅剧情执行、因果逻辑、节奏密度、角色声音、AI 味和商业阅读感；不要只返回字数问题。
- do_not_write 和 chapter_boundary 是审稿参考边界：允许一句以内模糊伏笔或压力钩子，但不得为了补字数建议新增后续章节地点、资源、地图、路线、探索或交易的完整场面。
- 如果字数不足，只能建议补当前章节内的报名、等待、观察、交锋、奖金结算、人物反应和身体代价。
- 如果字数超长，必须指出优先删除哪些段落功能或重复信息，同时保留哪些核心因果、冲突和角色动作。
- 不得建议新增后续交易、估价、黑市、明日处理、后续地点、路线或探索的完整场面；如果正文只是轻量伏笔，按商业连载钩子质量评分，如果已经提前完成后续爽点，应要求删除或改为当前事件余波。
- 看商业连载阅读感：开篇是否抓人、冲突是否清楚、因果是否成立、对话是否像人说话、节奏是否拖沓。
- 看正文是否有明显 AI 味、总结腔、模板化句式、过度描写。
- 必须对照创作包里的 completion_contract 和 acceptance_checklist 审稿：剧情闭环、字数、边界兑现程度、连续性、回报结算和章尾余波都达标才可通过。
- 如果正文只完成核心冲突、战斗、交锋、刺杀、获胜或阶段性胜负，却漏掉收获处理、清理撤离、清点归置、代价变化、现实压力变化或章尾余波，brief_execution 不得高于 70，approved 必须为 false。
- 如果 missing_if_absent 中任一项目缺失，brief_execution 不得高于 70；如果缺失的是回报结算或闭环处理，overall_score 不得高于 75。
- 对话是阅读质感项，不是所有章节的硬门槛；独行、潜伏、战斗、采集章节只要动作因果完整，不得仅因对话少或无对话打回。
- blocking_issues 只写不修就无法过关的硬伤：剧情任务缺失、提前兑现后续完整场面、明显逻辑断裂、严重 AI 味或正文残缺；轻微润色建议或字数偏差放入 findings，不得仅因字数拉低 overall_score 到 85 以下。
- 如果正文已经完成创作包核心任务、没有提前兑现后续完整场面、无明显逻辑断裂，只存在轻微表达、个别句式、少量对话或可选润色建议，应在 overall_score>=90 时 approved=true；这些建议只能放入 findings/revision_notes，blocking_issues 必须为空。
- approved=true 且 overall_score>=90 时，rewrite_brief 可以写"无需返修，仅保留建议"，不得给出会触发整章返修的执行清单。
- 字数硬区间为 {LOCAL_MIN_CHARS}-{LOCAL_MAX_CHARS} 字，理想约 {LOCAL_IDEAL_CHARS} 字；如果缺回报结算，应优先要求压缩前置观察或战斗重复动作来腾出篇幅，而不是继续扩写到上限。
- 本地底线检查里的 soft_warnings 不是自动失败原因；你必须从编辑视角判断：一句以内钩子、未解压力、模糊方向可通过，提前写完后续章节核心场面、交易流程、路线坐标、战斗胜负或资源闭环才算边界硬伤。
- 只在总分 {EDITOR_PASS_SCORE} 分以上且无底线问题时 approved=true。
- 如果不通过，必须给正文 agent 一份完整问题包：阻断问题、保留内容、删除内容、重写目标、执行顺序都要写清楚，让下一轮尽量一次性修完。
- 返修包必须按“保留什么、补齐什么、压缩什么、禁止什么、执行顺序”组织，避免正文 agent 只补尾巴导致超长或二次打回。

## 本地底线检查
{_compact_json(local, 2400)}

## 创作包
{_creation_pack_prompt_text(creation_pack, 10000)}

## 正文
{_clip_text(content, 16000)}

输出 JSON：
{{
  "approved": false,
  "overall_score": 0,
  "scores": {{"brief_execution": 0, "logic": 0, "readability": 0, "overall": 0}},
  "findings": ["具体问题"],
  "length_action": "字数是否合格；若不合格，明确压缩或补写到哪个区间以及怎么处理",
  "blocking_issues": ["不修就不能通过的问题，含字数、边界、剧情执行、逻辑、AI 味"],
  "keep": ["返修时必须保留的有效正文内容或核心因果"],
  "fill": ["必须补齐的当前章硬性动作、闭环动作、结算或余波"],
  "cut": ["返修时优先删除或压缩的内容类型"],
  "forbid": ["返修时禁止新增或展开的后续章节内容、重复动作或无效解释"],
  "rewrite_brief": ["给正文 agent 的综合返修清单，必须覆盖所有阻断问题"]
}}"""

    raw_content, _finish_reason = await _chat_completion(
        messages=[
            {"role": "system", "content": "你是起点资深责编，只输出严格 JSON。即使字数不合格，也必须完成综合审稿并给出一次性返修包。"},
            {"role": "user", "content": user_prompt},
        ],
        api_key=api_key,
        max_tokens=3072,
        response_format={"type": "json_object"},
    )
    from services import deepseek as deepseek_service

    try:
        parsed = deepseek_service._extract_json_object(raw_content)
    except Exception as exc:
        logger.warning(
            "chapter_pipeline.editor.parse_failed trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s error=%s",
            trace,
            _chapter_label(chapter_task),
            _elapsed_ms(started_at),
            _finish_reason,
            exc,
        )
        retry_prompt = f"""上一次编辑审阅输出不是合法 JSON。请重新审阅并只输出一个可解析的紧凑 JSON，不要解释。

## 硬限制
- 总长度不超过 2200 汉字。
- 必须综合判断剧情执行、字数、边界、逻辑、节奏、AI 味和商业阅读感。
- 如果不通过，必须把所有问题合并成一次性返修包，避免正文 agent 多轮返工。
- soft_warnings 只是提示；一句以内模糊钩子可通过，提前兑现后续完整场面才算硬伤。

## 本地底线检查
{_compact_json(local, 1600)}

## 创作包简版
{_creation_pack_prompt_text(creation_pack, 5200)}

## 正文
{_clip_text(content, 10000)}

只输出 JSON，字段必须包含：
approved, overall_score, scores, findings, revision_notes, length_action,
blocking_issues, keep, fill, cut, forbid, rewrite_targets, revision_plan, rewrite_brief。"""
        try:
            retry_content, retry_finish_reason = await _chat_completion(
                messages=[
                    {"role": "system", "content": "你是起点资深责编。只输出紧凑、合法、可解析 JSON。"},
                    {"role": "user", "content": retry_prompt},
                ],
                api_key=api_key,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            parsed = deepseek_service._extract_json_object(retry_content)
            logger.info(
                "chapter_pipeline.editor.retry_done trace_id=%s chapter=%s elapsed_ms=%s finish_reason=%s summary=%s",
                trace,
                _chapter_label(chapter_task),
                _elapsed_ms(started_at),
                retry_finish_reason,
                _review_log_summary(_normalize_review(parsed)),
            )
        except Exception as retry_exc:
            logger.warning(
                "chapter_pipeline.editor.retry_failed trace_id=%s chapter=%s elapsed_ms=%s error=%s",
                trace,
                _chapter_label(chapter_task),
                _elapsed_ms(started_at),
                retry_exc,
            )
            parsed = {
                "approved": False,
                "overall_score": 0,
                "findings": [f"编辑审阅解析失败: {exc}"],
                "revision_notes": ["重新按创作包完整输出，保持章节边界和正文长度。"],
            }
    review = _normalize_review(parsed)
    if not local["ok"]:
        review["approved"] = False
        review["overall_score"] = min(review["overall_score"], 70)
        local_notes = [item["message"] for item in local["hard_failures"]]
        review["findings"] = local_notes + review.get("findings", [])
        review["rewrite_brief"] = local_notes + review.get("rewrite_brief", [])
    review["local_safety"] = local
    review = _soften_review_dialogue_blockers(review)
    review = _promote_near_pass_review(review, content)
    logger.info(
        "chapter_pipeline.editor.done trace_id=%s chapter=%s elapsed_ms=%s test_mode=%s summary=%s",
        trace,
        _chapter_label(chapter_task),
        _elapsed_ms(started_at),
        False,
        _review_log_summary(review),
    )
    logger.info(
        "chapter_pipeline.editor.detail trace_id=%s chapter=%s detail=%s",
        trace,
        _chapter_label(chapter_task),
        _compact_json(_review_log_detail(review), 12000),
    )
    return review


async def run_chapter_creation_pipeline(
    *,
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    api_key: str | None = None,
    previous_chapter_summary: str = "",
    system_rules: str | None = None,
    initial_content: str | None = None,
    creation_pack: dict[str, Any] | None = None,
    max_revisions: int = 3,
    skip_initial_review: bool = False,
) -> dict[str, Any]:
    """两阶段链路：构建或复用创作包，再由正文 Agent 单次生成。"""
    started_at = time.perf_counter()
    trace_id = uuid.uuid4().hex[:8]
    logger.info(
        "chapter_pipeline.start trace_id=%s story_id=%s story_title=%s chapter=%s mode=two_stage has_initial_content=%s has_creation_pack=%s",
        trace_id,
        story_context.get("id") or story_context.get("story_id"),
        story_context.get("title") or story_context.get("name"),
        _chapter_label(chapter_info),
        bool(initial_content),
        isinstance(creation_pack, dict) and bool(creation_pack),
    )
    pack_reused = isinstance(creation_pack, dict) and bool(creation_pack)
    if pack_reused:
        if canonical_pack_content(creation_pack) is None:
            creation_pack = _ensure_scene_budget(creation_pack)
            creation_pack = _ensure_completion_fields(creation_pack)
        logger.info(
            "chapter_pipeline.pack.reused trace_id=%s chapter=%s summary=%s",
            trace_id,
            _chapter_label(chapter_info),
            _pack_log_summary(creation_pack),
        )
        logger.info(
            "chapter_pipeline.pack.detail trace_id=%s chapter=%s detail=%s",
            trace_id,
            _chapter_label(chapter_info),
            _compact_json(_pack_log_detail(creation_pack), 20000),
        )
        logger.info(
            "chapter_pipeline.pack.summary.zh trace_id=%s chapter=%s detail=%s",
            trace_id,
            _chapter_label(chapter_info),
            _compact_json(_pack_log_zh_summary(creation_pack), 12000),
        )
    else:
        creation_pack = await build_chapter_creation_pack(
            story_context=story_context,
            chapter_info=chapter_info,
            previous_chapter_summary=previous_chapter_summary,
            api_key=api_key,
            system_rules=system_rules,
            trace_id=trace_id,
        )
        logger.info(
            "chapter_pipeline.pack.ready trace_id=%s chapter=%s summary=%s",
            trace_id,
            _chapter_label(chapter_info),
            _pack_log_summary(creation_pack),
        )
        logger.info(
            "chapter_pipeline.pack.summary.zh trace_id=%s chapter=%s detail=%s",
            trace_id,
            _chapter_label(chapter_info),
            _compact_json(_pack_log_zh_summary(creation_pack), 12000),
        )
    direct_feedback = None
    if initial_content and str(chapter_info.get("user_instruction") or "").strip():
        direct_feedback = [str(chapter_info["user_instruction"]).strip()]
    draft = await write_chapter_from_pack(
        creation_pack=creation_pack,
        api_key=api_key,
        editor_feedback=direct_feedback,
        previous_draft=initial_content or "",
        trace_id=trace_id,
    )
    content = str(draft.get("content") or "")
    finish_reason = draft.get("finish_reason")
    tail_repaired = False
    if finish_reason == "length" and _content_looks_truncated(content):
        content, tail_repaired = _repair_truncated_tail_locally(content)

    from services.chapter_quality import run_deterministic_gate

    chapter_scope = creation_pack.get("chapter_boundary") if isinstance(creation_pack, dict) else None
    deterministic = run_deterministic_gate(content, chapter_info, chapter_scope=chapter_scope)
    local_safety = _local_safety_review(content, chapter_scope)
    generation_hard_failures: list[dict[str, Any]] = []
    if finish_reason == "length":
        generation_hard_failures.append({
            "code": "generation.token_limit",
            "message": "正文生成达到模型 token 上限，可能存在内容截断",
            "severity": "hard",
        })
        deterministic = {
            **deterministic,
            "ok": False,
            "hard_failures": [
                *(deterministic.get("hard_failures") if isinstance(deterministic.get("hard_failures"), list) else []),
                *generation_hard_failures,
            ],
        }
    # 字数和表达问题只作为写作提示；空正文、截断和章节越界才阻止保存。
    ok = bool(deterministic.get("ok")) and finish_reason != "length"
    review = {
        "skipped": True,
        "reason": "editor_agent_removed",
        "deterministic": deterministic,
        "local_safety": local_safety,
        "hard_failures": generation_hard_failures,
    }
    logger.info(
        "chapter_pipeline.complete trace_id=%s chapter=%s ok=%s chars=%s finish_reason=%s elapsed_ms=%s editor_review_skipped=true",
        trace_id,
        _chapter_label(chapter_info),
        ok,
        count_chapter_chars(content),
        finish_reason,
        _elapsed_ms(started_at),
    )
    return {
        "ok": ok,
        "content": content,
        "creation_pack": creation_pack,
        "review": review,
        "attempts": 1,
        "finish_reason": finish_reason,
        "stages": {
            "creation_pack": "reused" if pack_reused else "built",
            "writer": "completed",
            "deterministic_gate": "passed" if ok else "failed",
            "editor_review": "skipped",
        },
        "editor_review_skipped": True,
        "tail_repaired_locally": tail_repaired,
    }
