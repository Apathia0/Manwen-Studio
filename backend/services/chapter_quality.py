import hashlib
import json
import logging
import re
from typing import Any

import httpx

from services.errors import public_error_message


logger = logging.getLogger(__name__)

MIN_CHAPTER_CHARS = 1800
MAX_CHAPTER_CHARS = 3500
IDEAL_CHAPTER_CHARS = 3000

FORBIDDEN_PHRASES = {
    "眼中闪过": "模板化表情",
    "嘴角勾起": "模板化表情",
    "深吸一口气": "模板化动作",
    "心中一动": "模板化心理",
    "心头一震": "模板化心理",
    "心中暗道": "模板化心理",
    "不由得": "告知式过渡",
    "不由自主": "告知式过渡",
    "情不自禁": "告知式过渡",
    "显而易见": "总结式判断",
    "毫无疑问": "总结式判断",
    "他不知道的是": "空泛预告",
    "她不知道的是": "空泛预告",
    "命运的齿轮": "AI味套话",
}

SIMILE_PHRASES = {"仿佛", "犹如", "宛若"}

FORBIDDEN_PATTERNS: list[tuple[str, str, str]] = [
    ("ai_flavor.not_a_but_b", r"不是[^。！？\n]{1,40}[而]?是", "不是A而是B句式"),
    ("ai_flavor.tell_emotion", r"[他她][^。！？\n]{0,8}(感到|觉得|意识到|明白|知道)", "告知式心理"),
    ("ending.empty_forecast", r"他不知道的是|她不知道的是|更大的[风浪风暴]|真正的考验", "空泛预告"),
]

WEAK_OPENING_PATTERN = re.compile(
    r"^\s*(清晨|早上|凌晨|上午|中午|午后|傍晚|黄昏|夜里|夜色|晨曦|阳光|月光|雨|风|雪|雾|天空|天色|夕阳|朝阳|暮色|晚霞|青石板|街道|山林)"
)

DASH_PATTERN = re.compile(r"——|—{1,2}|\.{2,}|……")


def count_content_chars(text: str) -> int:
    """统计正文有效字数，忽略所有空白字符。"""
    return len(re.sub(r"\s+", "", text or ""))


def _resolve_existing_creation_pack(
    story_context: dict[str, Any],
    existing_creation_pack: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """读取可复用的创作包，减少终检阶段重复调用前置 agent。"""
    if isinstance(existing_creation_pack, dict) and existing_creation_pack:
        return existing_creation_pack
    if isinstance(story_context, dict):
        cached = story_context.get("_last_creation_pack")
        if isinstance(cached, dict) and cached:
            return cached
    return None


def _content_sha256(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _resolve_cached_pipeline_result(
    story_context: dict[str, Any],
    content: str,
    deterministic: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """命中刚完成的三角色结果时，终检直接复用审阅结论，避免重复远程编辑。"""
    if not deterministic.get("ok"):
        return None, "deterministic_failed"
    if not isinstance(story_context, dict):
        return None, "invalid_story_context"
    cached = story_context.get("_last_chapter_pipeline_result")
    if not isinstance(cached, dict):
        return None, "missing_cache"
    if cached.get("content_sha256") != _content_sha256(content):
        return None, "hash_mismatch"
    if cached.get("char_count") != deterministic.get("char_count"):
        return None, "char_count_mismatch"
    return cached, "cache_hit"


def _latest_failed_pipeline_result(story_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(story_context, dict):
        return None
    cached = story_context.get("_last_chapter_pipeline_result")
    if not isinstance(cached, dict):
        return None
    if cached.get("ok") is False:
        return cached
    return None


def _cached_review_has_local_hard_failure(review: dict[str, Any]) -> bool:
    local = review.get("local_safety") if isinstance(review.get("local_safety"), dict) else {}
    hard_failures = local.get("hard_failures") if isinstance(local.get("hard_failures"), list) else []
    return bool(hard_failures) or (bool(local) and not bool(local.get("ok")))


def _cached_review_has_blocking_issue(review: dict[str, Any]) -> bool:
    """识别编辑结构化报告中的硬伤，避免把真实阻断问题误判为软通过。"""
    if not isinstance(review, dict):
        return True
    try:
        from services.chapter_agents import _review_has_real_blocking_issue

        return _review_has_real_blocking_issue(review)
    except Exception as exc:
        logger.warning("复用三角色审阅阻断判断失败，回退本地规则: %s", exc)
    hard_failures = review.get("hard_failures")
    if isinstance(hard_failures, list) and hard_failures:
        return True
    raw = review.get("raw") if isinstance(review.get("raw"), dict) else {}
    blocking_issues = raw.get("blocking_issues") if isinstance(raw.get("blocking_issues"), list) else []
    if any(str(item).strip() and not re.search(r"^\s*(无|暂无|没有|空|\[\]|none|no|null)", str(item), re.IGNORECASE) for item in blocking_issues):
        return True
    rewrite_brief = review.get("rewrite_brief") if isinstance(review.get("rewrite_brief"), list) else []
    for item in rewrite_brief:
        text = str(item).lower()
        if ("blocking_issues" in text or "硬伤" in text or "必须重写" in text) and not re.search(
            r"(无需|无须|暂无|没有|仅|轻微|建议|保留建议|不触发返修|none|no)",
            text,
            re.IGNORECASE,
        ):
            return True
    return False


def _cached_pipeline_is_acceptable(cached: dict[str, Any], deterministic: dict[str, Any]) -> tuple[bool, str]:
    review = cached.get("review") if isinstance(cached.get("review"), dict) else {}
    score = _normalize_score(review.get("overall_score"))
    if not deterministic.get("ok") or _cached_review_has_local_hard_failure(review):
        return False, "hard_failure"
    if _cached_review_has_blocking_issue(review):
        return False, "editor_blocking_issue"
    if cached.get("ok") and review.get("approved") and score >= 90:
        return True, "editor_hard_pass"
    if score >= 90 and review.get("approved"):
        return True, "editor_score_pass"
    return False, "score_below_editor_pass"


def _issue(code: str, message: str, *, severity: str = "hard", evidence: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message, "severity": severity}
    if evidence:
        item["evidence"] = evidence[:160]
    return item


def _extract_chapter_number(chapter_info: dict[str, Any] | None) -> int | None:
    if not isinstance(chapter_info, dict):
        return None
    value = chapter_info.get("chapter_number")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _first_non_empty_line(content: str) -> str:
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _last_chars(content: str, size: int = 320) -> str:
    compact = re.sub(r"\s+", "", content or "")
    return compact[-size:]


def _line_context(content: str, term: str) -> str:
    index = content.find(term)
    if index < 0:
        return ""
    start = max(0, index - 45)
    end = min(len(content), index + len(term) + 45)
    return re.sub(r"\s+", " ", content[start:end])


def _chapter_scope_from_story_context(story_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(story_context, dict):
        return {}
    try:
        from services.deepseek import _chapter_scope_from_context

        scope = _chapter_scope_from_context(story_context)
        return scope if isinstance(scope, dict) else {}
    except Exception as exc:
        logger.warning("章节边界上下文提取失败: %s", exc)
        return {}


def _detect_boundary_issues(content: str, chapter_scope: dict[str, Any] | None) -> list[str]:
    if not chapter_scope:
        return []
    try:
        from services.deepseek import _detect_chapter_boundary_issues

        return _detect_chapter_boundary_issues(content, chapter_scope)
    except Exception as exc:
        logger.warning("章节边界检测失败: %s", exc)
        return []


def run_deterministic_gate(
    content: str,
    chapter_info: dict[str, Any] | None,
    chapter_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行本地确定性质量门禁，返回硬失败和软警告。"""
    text = content or ""
    char_count = count_content_chars(text)
    hard_failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if char_count < MIN_CHAPTER_CHARS:
        hard_failures.append(_issue("length.too_short", f"正文字数低于 {MIN_CHAPTER_CHARS} 字，当前约 {char_count} 字"))
    elif char_count > MAX_CHAPTER_CHARS:
        hard_failures.append(_issue("length.too_long", f"正文字数超过 {MAX_CHAPTER_CHARS} 字，当前约 {char_count} 字"))

    first_line = _first_non_empty_line(text)
    if WEAK_OPENING_PATTERN.search(first_line):
        chapter_number = _extract_chapter_number(chapter_info)
        chapter_label = "第一章" if chapter_number == 1 else "章节"
        warnings.append(
            _issue(
                "opening.weak_time_or_scenery_opening",
                f"{chapter_label}禁止以时间、天气或景物开篇，应直接进入事件、动作、对话、冲突或异常",
                severity="warning",
                evidence=first_line,
            )
        )

    if DASH_PATTERN.search(text):
        warnings.append(_issue("punctuation.dash_or_ellipsis", "正文含破折号或省略号，属于高频 AI 味标点", severity="warning"))

    for phrase, label in FORBIDDEN_PHRASES.items():
        if phrase in text:
            warnings.append(
                _issue(
                    "ai_flavor.forbidden_phrase",
                    f"出现禁用短语「{phrase}」：{label}",
                    severity="warning",
                    evidence=_line_context(text, phrase),
                )
            )

    for phrase in SIMILE_PHRASES:
        if phrase in text:
            warnings.append(
                _issue(
                    "ai_flavor.simile",
                    f"出现高频比喻词「{phrase}」，容易形成 AI 味",
                    severity="warning",
                    evidence=_line_context(text, phrase),
                )
            )

    for code, pattern, label in FORBIDDEN_PATTERNS:
        match = re.search(pattern, text)
        if match:
            warnings.append(_issue(code, label, severity="warning", evidence=_line_context(text, match.group(0))))

    for boundary_issue in _detect_boundary_issues(text, chapter_scope):
        hard_failures.append(
            _issue(
                "boundary.future_event",
                boundary_issue,
                evidence=boundary_issue,
            )
        )


    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if paragraphs and max(count_content_chars(item) for item in paragraphs) > 520:
        warnings.append(_issue("density.paragraph_too_long", "存在超过 520 字的超长段落，阅读节奏偏闷", severity="warning"))

    dialogue_count = len(re.findall(r"“[^”]{2,80}”", text))
    if dialogue_count < 3:
        warnings.append(_issue("dialogue.too_few", "有效对话少于 3 句，章节可能偏叙述文", severity="warning"))

    tail = _last_chars(text)
    if re.search(r"终于明白|这一刻|注定|人生|命运|真正的开始", tail):
        warnings.append(_issue("ending.summary_like", "章末存在总结升华或空泛预告倾向", severity="warning", evidence=tail))

    hard_failures = _dedupe_issues(hard_failures)
    warnings = _dedupe_issues(warnings)
    return {
        "ok": not hard_failures,
        "char_count": char_count,
        "target": {"min": MIN_CHAPTER_CHARS, "ideal": IDEAL_CHAPTER_CHARS, "max": MAX_CHAPTER_CHARS},
        "hard_failures": hard_failures,
        "warnings": warnings,
    }


def _dedupe_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("code")), str(item.get("message")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _compact_json(value: Any, limit: int = 3200) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit] + ("..." if len(text) > limit else "")


def _normalize_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0 <= score <= 10:
        return score * 10
    return max(0.0, min(score, 100.0))


def _issue_line(item: Any) -> str:
    if isinstance(item, dict):
        code = str(item.get("code") or "quality.issue")
        message = str(item.get("message") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        line = f"- {code}: {message}" if message else f"- {code}"
        if evidence:
            line += f"｜证据：{evidence[:120]}"
        return line
    return f"- {item}"


def _review_hard_failures(review_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(review_report, dict):
        return []
    hard_failures = review_report.get("hard_failures")
    if isinstance(hard_failures, list):
        return [item for item in hard_failures if isinstance(item, dict)]
    return []


async def review_chapter_for_qidian(
    content: str,
    story_context: dict[str, Any] | None = None,
    chapter_info: dict[str, Any] | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """按起点编辑标准做结构化 AI 审稿；无密钥时不阻塞确定性门禁。"""
    if api_key == "test":
        return {"ok": True, "scores": {"overall": 80}, "findings": [], "skipped": True}

    story_context = story_context or {}
    chapter_info = chapter_info or {}
    chapter_scope = _chapter_scope_from_story_context(story_context)
    deterministic = run_deterministic_gate(content, chapter_info, chapter_scope=chapter_scope)
    content_sample = content[:14000] if len(content) > 14000 else content
    review_prompt = f"""你是起点资深责编，请按商业连载正文标准审稿。只输出 JSON，不要解释。

## 审稿目标
- 判断这一章是否值得保存为正式正文。
- 重点看：逻辑因果、上下文连续性、叙事密度、AI味、起点可读性、章节边界。
- 如果写到了后续章节的关键事件、地点、资源收获、冲突解决或爽点兑现，必须判定不通过。

## 当前章节任务卡
{_compact_json(chapter_info, 1800)}

## 章节边界
{_compact_json(chapter_scope, 3600)}

## 本地确定性门禁
{_compact_json(deterministic, 2400)}

## 正文
{content_sample}

请严格输出如下 JSON：
{{
  "ok": true,
  "scores": {{
    "logic": 0,
    "continuity": 0,
    "density": 0,
    "ai_flavor": 0,
    "qidian_readability": 0,
    "boundary_control": 0,
    "overall": 0
  }},
  "hard_failures": [
    {{"code": "boundary.future_event", "message": "提前写到了后续章节事件", "evidence": "原文证据"}}
  ],
  "findings": ["具体问题，不要泛泛而谈"],
  "rewrite_brief": ["重写时必须执行的动作"]
}}

判定规则：
- overall 低于 75 判定 ok=false。
- logic、continuity、density、ai_flavor、qidian_readability、boundary_control 任一低于 70 判定 ok=false。
- hard_failures 非空判定 ok=false。
- finding 必须具体到正文问题或章节任务偏离点。"""

    try:
        from services import deepseek as deepseek_service

        payload = {
            "model": deepseek_service.runtime_model(),
            "messages": [
                {"role": "system", "content": "你是起点资深责编，只输出严格 JSON。"},
                {"role": "user", "content": review_prompt},
            ],
            "stream": False,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        payload = deepseek_service._apply_runtime_params(payload)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
        resp.raise_for_status()
        data = deepseek_service._response_json(resp, context="DeepSeek")
        assessment = deepseek_service._extract_json_object(data["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("AI 章节审稿失败，降级为确定性门禁: %s", exc)
        return {
            "ok": True,
            "scores": {"overall": 0},
            "findings": [public_error_message(exc, "质量检查暂时不可用，请稍后重试")],
            "skipped": True,
        }

    scores = assessment.get("scores") if isinstance(assessment, dict) else {}
    normalized_scores = {str(key): _normalize_score(value) for key, value in scores.items()} if isinstance(scores, dict) else {}
    overall_score = normalized_scores.get("overall", 0.0)
    core_keys = ("logic", "continuity", "density", "ai_flavor", "qidian_readability", "boundary_control")
    hard_failures = _review_hard_failures(assessment)
    low_core = any(normalized_scores.get(key, 100.0) < 70 for key in core_keys)
    ok = bool(assessment.get("ok", True)) and overall_score >= 75 and not low_core and not hard_failures
    findings: list[str] = []
    rewrite_brief: list[str] = []
    if isinstance(assessment, dict):
        raw_findings = assessment.get("findings")
        if isinstance(raw_findings, list):
            findings = [str(item) for item in raw_findings[:8]]
        suggestions = assessment.get("suggestions")
        if not findings and isinstance(suggestions, list):
            findings = [str(item) for item in suggestions[:8]]
        raw_brief = assessment.get("rewrite_brief")
        if isinstance(raw_brief, list):
            rewrite_brief = [str(item) for item in raw_brief[:8]]
    return {
        "ok": ok,
        "scores": normalized_scores or {"overall": overall_score},
        "hard_failures": hard_failures,
        "findings": findings,
        "rewrite_brief": rewrite_brief,
        "raw": assessment,
    }


async def repair_chapter_to_pass_quality_gate(
    *,
    content: str,
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    deterministic_report: dict[str, Any],
    review_report: dict[str, Any] | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
    source: str = "",
) -> str:
    """要求模型完整重写问题稿，而不是局部补丁。"""
    if api_key == "test":
        return content

    issues = deterministic_report.get("hard_failures") if isinstance(deterministic_report, dict) else []
    warnings = deterministic_report.get("warnings") if isinstance(deterministic_report, dict) else []
    review_findings = review_report.get("findings") if isinstance(review_report, dict) else []
    review_failures = _review_hard_failures(review_report)
    review_brief = review_report.get("rewrite_brief") if isinstance(review_report, dict) else []
    chapter_scope = _chapter_scope_from_story_context(story_context)
    issue_lines = []
    for item in list(issues or [])[:8]:
        issue_lines.append(_issue_line(item))
    for item in list(warnings or [])[:4]:
        issue_lines.append(_issue_line(item))
    for item in list(review_failures or [])[:6]:
        issue_lines.append(_issue_line(item))
    for item in list(review_findings or [])[:4]:
        issue_lines.append(f"- AI审稿: {item}")
    for item in list(review_brief or [])[:4]:
        issue_lines.append(f"- 重写指令: {item}")
    if not issue_lines:
        issue_lines.append("- 章节未达到起点正文质量门禁")

    boundary_block = ""
    if chapter_scope:
        boundary_block = (
            "\n\n章节边界硬约束：\n"
            f"{_compact_json(chapter_scope, 3600)}\n"
            "只能写 current_chapter_card 内的事件。future_chapters_for_boundary_only 只能用来避雷，"
            "正文不得出现其中的完整行动、地点推进、资源收获、战斗、秘境、擂台、捡漏、药材兑现或冲突解决。"
        )

    instruction = (
        "请按起点资深编辑审稿意见完整重写本章正文，不要解释，不要输出标题。\n"
        f"目标字数必须落在 {MIN_CHAPTER_CHARS}-{MAX_CHAPTER_CHARS} 字，优先写到 2300-2450 字，不要贴近上限。\n"
        "必须保留本章任务卡的核心因果，不得提前兑现后续章节爽点。\n"
        "第一句必须直接写人物动作、对白、冲突或异常，不得以时间、天气、景物、街巷、山林、光线或空气起笔。\n"
        "删除模板化 AI 味、破折号、省略号、总结升华、无效景物描写、重复心理活动、战后尾声和无关的下一章短信/传闻式钩子。\n"
        "如果当前稿超过 2800 字，必须优先删掉战斗结束后的生活尾声、解释性复盘、路程转场和重复观众反应，不得压缩核心因果后保留尾声。\n"
        "如果驳回原因里出现了具体词句或证据，重写正文中必须完全避开这些词句和对应场面。\n"
        "本次驳回原因：\n" + "\n".join(issue_lines) + boundary_block
    )

    from services.deepseek import adjust_chapter_content

    return await adjust_chapter_content(
        story_context,
        chapter_info,
        content,
        instruction,
        api_key=api_key,
        system_prompt=system_prompt,
    )


async def finalize_generated_chapter_content(
    *,
    content: str,
    story_context: dict[str, Any],
    chapter_info: dict[str, Any],
    api_key: str | None = None,
    system_prompt: str | None = None,
    source: str = "",
    max_attempts: int = 3,
    existing_creation_pack: dict[str, Any] | None = None,
    allow_pipeline_rerun: bool = True,
) -> dict[str, Any]:
    """生成后质量终检；由创作包、正文、编辑三角色循环完成返修。"""
    current = content or ""
    chapter_scope = _chapter_scope_from_story_context(story_context)
    deterministic = run_deterministic_gate(current, chapter_info, chapter_scope=chapter_scope)
    cached_pipeline, cache_reason = _resolve_cached_pipeline_result(story_context, current, deterministic)
    if cached_pipeline:
        cached_ok, reuse_reason = _cached_pipeline_is_acceptable(cached_pipeline, deterministic)
        logger.info(
            "章节终检命中三角色缓存 source=%s chapter=%s chars=%s score=%s ok=%s reason=%s",
            source,
            chapter_info.get("chapter_number") if isinstance(chapter_info, dict) else None,
            deterministic.get("char_count"),
            (cached_pipeline.get("review") or {}).get("overall_score") if isinstance(cached_pipeline.get("review"), dict) else None,
            cached_ok,
            reuse_reason,
        )
        return {
            "ok": cached_ok,
            "content": current,
            "attempts": cached_pipeline.get("attempts", 0),
            "report": {
                "deterministic": deterministic,
                "review": cached_pipeline.get("review") if isinstance(cached_pipeline.get("review"), dict) else {},
                "creation_pack": cached_pipeline.get("creation_pack"),
                "finish_reason": cached_pipeline.get("finish_reason"),
                "reused_pipeline_result": True,
                "reused_pipeline_reason": reuse_reason,
                "cache_reason": cache_reason,
            },
            "source": source,
        }
    logger.info(
        "章节终检未命中三角色缓存 source=%s chapter=%s chars=%s deterministic_ok=%s reason=%s allow_pipeline_rerun=%s",
        source,
        chapter_info.get("chapter_number") if isinstance(chapter_info, dict) else None,
        deterministic.get("char_count"),
        deterministic.get("ok"),
        cache_reason,
        allow_pipeline_rerun,
    )
    if not allow_pipeline_rerun:
        failed_pipeline = _latest_failed_pipeline_result(story_context)
        if failed_pipeline:
            review = failed_pipeline.get("review") if isinstance(failed_pipeline.get("review"), dict) else {}
            logger.warning(
                "章节终检发现最近三角色链路失败，拒绝用确定性门禁放行 source=%s chapter=%s reason=%s score=%s",
                source,
                chapter_info.get("chapter_number") if isinstance(chapter_info, dict) else None,
                cache_reason,
                review.get("overall_score"),
            )
            return {
                "ok": False,
                "content": current,
                "attempts": failed_pipeline.get("attempts", 0),
                "report": {
                    "deterministic": deterministic,
                    "review": {**review, "skipped": True, "reason": "previous_pipeline_failed"},
                    "creation_pack": failed_pipeline.get("creation_pack"),
                    "finish_reason": failed_pipeline.get("finish_reason"),
                    "reused_pipeline_result": False,
                    "cache_miss_reason": cache_reason,
                    "pipeline_rerun_skipped": True,
                    "previous_pipeline_failed": True,
                },
                "source": source,
            }
        logger.info(
            "章节终检跳过三角色重跑 source=%s chapter=%s reason=%s ok=%s",
            source,
            chapter_info.get("chapter_number") if isinstance(chapter_info, dict) else None,
            cache_reason,
            deterministic.get("ok"),
        )
        return {
            "ok": deterministic["ok"],
            "content": current,
            "attempts": 0,
            "report": {
                "deterministic": deterministic,
                "review": {"skipped": True, "reason": "pipeline_rerun_disabled"},
                "reused_pipeline_result": False,
                "cache_miss_reason": cache_reason,
                "pipeline_rerun_skipped": True,
            },
            "source": source,
        }
    if not api_key:
        return {
            "ok": deterministic["ok"],
            "content": current,
            "attempts": 0,
            "report": {
                "deterministic": deterministic,
                "review": {"skipped": True, "reason": "missing_api_key"},
                "cache_miss_reason": cache_reason,
            },
            "source": source,
        }

    try:
        from services.chapter_agents import run_chapter_creation_pipeline

        reusable_pack = _resolve_existing_creation_pack(story_context, existing_creation_pack)
        if reusable_pack:
            logger.info(
                "章节终检复用创作包 source=%s chapter=%s",
                source,
                chapter_info.get("chapter_number") if isinstance(chapter_info, dict) else None,
            )
        pipeline = await run_chapter_creation_pipeline(
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            system_rules=system_prompt,
            initial_content=current,
            creation_pack=reusable_pack,
            max_revisions=max_attempts,
        )
    except Exception as exc:
        logger.warning("三角色章节终检失败，降级为旧编辑审稿: %s", exc)
        review = await review_chapter_for_qidian(
            current,
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            system_prompt=system_prompt,
        )
        return {
            "ok": deterministic["ok"] and review.get("ok", True),
            "content": current,
            "attempts": 0,
            "report": {"deterministic": deterministic, "review": review, "pipeline_error": str(exc)},
            "source": source,
        }

    final_content = str(pipeline.get("content") or current)
    final_deterministic = run_deterministic_gate(final_content, chapter_info, chapter_scope=chapter_scope)
    review = pipeline.get("review") if isinstance(pipeline.get("review"), dict) else {}
    return {
        "ok": bool(pipeline.get("ok")) and final_deterministic["ok"],
        "content": final_content,
        "attempts": pipeline.get("attempts", 0),
        "report": {
            "deterministic": final_deterministic,
            "review": review,
            "creation_pack": pipeline.get("creation_pack"),
            "finish_reason": pipeline.get("finish_reason"),
        },
        "source": source,
    }


def format_quality_gate_detail(result: dict[str, Any]) -> dict[str, Any]:
    """整理给 API 返回的质量门禁失败详情。"""
    report = result.get("report") if isinstance(result, dict) else {}
    deterministic = report.get("deterministic") if isinstance(report, dict) else {}
    review = report.get("review") if isinstance(report, dict) else {}
    hard_failures = deterministic.get("hard_failures") if isinstance(deterministic, dict) else []
    warnings = deterministic.get("warnings") if isinstance(deterministic, dict) else []
    review_failures = review.get("hard_failures") if isinstance(review, dict) else []
    review_findings = review.get("findings") if isinstance(review, dict) else []
    rewrite_brief = review.get("rewrite_brief") if isinstance(review, dict) else []
    return {
        "message": "生成正文未通过质量门禁，已阻止保存。请调整章节任务卡或重试生成。",
        "source": result.get("source"),
        "attempts": result.get("attempts"),
        "char_count": deterministic.get("char_count") if isinstance(deterministic, dict) else None,
        "hard_failures": hard_failures[:8] if isinstance(hard_failures, list) else [],
        "warnings": warnings[:6] if isinstance(warnings, list) else [],
        "review_hard_failures": review_failures[:6] if isinstance(review_failures, list) else [],
        "review_findings": review_findings[:6] if isinstance(review_findings, list) else [],
        "rewrite_brief": rewrite_brief[:6] if isinstance(rewrite_brief, list) else [],
        "raw": json.dumps(report, ensure_ascii=False)[:4000],
    }
