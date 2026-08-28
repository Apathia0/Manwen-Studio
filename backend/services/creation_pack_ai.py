"""
创作包 AI 生成服务：从知识库检索结果（sections）提炼结构化的「正文创作说明」。

输入：resolve_chapter_context_pack 返回的 context_pack（含 sections） + 章节大纲 chapter_info
输出：结构化的创作说明 JSON（本章任务 / 剧情推进 / 伏笔管理 / 人物动机 / 场景设定 /
      连续性约束 / 写作要点），供 render_ai_creation_pack 渲染成 markdown 后入库。

设计原则（对齐 AGENTS.md 陷阱 18/19）：
1. 调用前必须完成 DeepSeek 运行时配置注入（由调用方 _user_deepseek_api_key 完成）。
2. 容错解析链：_extract_json_object → _repair_broken_json_fields → _repair_truncated_json。
3. 写作质量规范与框架直出同源：从 writing_utils.get_methodology_from_db 注入。
4. 任何失败（网络/JSON/字段缺失）都由调用方回退固定模板，本模块绝不抛未预期异常。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

import services.deepseek as _deepseek
from services.deepseek import (
    _deepseek_auth_headers,
    _extract_json_object,
    _repair_broken_json_fields,
    _repair_truncated_json,
)
from services.writing_utils import get_methodology_from_db

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 14000
REQUEST_TIMEOUT = 300
MAX_OUTPUT_CHARS = 5000
AI_CREATION_PACK_VERSION = 1
# 思考型模型经网关调用会忽略 thinking=disabled，reasoning 与正文共享输出预算。
# 初始预算放大留足思考+输出缓冲；空 content 时按倍数升级重试。
CREATION_PACK_MAX_TOKENS = 16384
_CREATION_PACK_BOOST_FACTOR = 2
_CREATION_PACK_BOOST_MAX_TOKENS = 32768


class _BoostRetry(Exception):
    """内部控制流：思考吃掉输出预算，需要放大 max_tokens 后立即重试。"""


SYSTEM_PROMPT = """你是资深中文网文编辑。根据提供的「本章知识库检索结果」和「章节大纲」，生成一份可直接指导正文 Agent 写作的「正文创作说明」。

要求：
1. 只依据提供的检索结果与大纲，不得凭空编造大纲之外的核心剧情、人物结局或新设定。
2. 必须识别并安排伏笔：区分「已到期需处理」「临近回收」「暂不推进」三类伏笔，并在剧情推进中给出处理方式；可适当埋设新的小伏笔。
3. 人物动机必须与知识库中的角色档案一致；正文 Agent 需要知道本章每个出场角色的目标与状态。
4. 连续性约束必须具体：明确列出本章必须保持的事实、禁止破坏的设定、不得提前预支的内容。
5. 场景设定给出地点、氛围与关键细节提示，帮助正文 Agent 建立画面感。
6. 写作要点对齐平台质量标准：禁破折号、禁情绪词直写、对话口语化等。
7. 输出必须是严格 JSON 对象，不要 Markdown 代码围栏，不要任何解释文字。

输出 JSON schema（所有字段均为中文内容）：
{
  "chapter_task": {
    "goal": "本章核心目标",
    "conflict": "本章核心冲突",
    "payoff": "本章剧情回报（兑现/铺垫）",
    "ending_hook": "章末钩子（悬念）"
  },
  "plot_beats": [
    {
      "order": 1,
      "type": "开篇钩子|推进|转折|高潮|章末钩子",
      "summary": "节拍概述（30-80字）",
      "characters": ["出场人物名"],
      "key_actions": ["关键动作/事件"],
      "dialogue_hints": "对话要点（可选）"
    }
  ],
  "foreshadowing": [
    {
      "title": "伏笔标题",
      "status": "due|overdue|approaching|background|new",
      "action": "本章如何处理（推进/回收/埋设/暂不处理）",
      "note": "具体安排说明"
    }
  ],
  "characters": [
    {
      "name": "人物名",
      "motivation": "本章动机",
      "current_state": "当前状态",
      "arc": "本章人物变化/表现"
    }
  ],
  "scenes": [
    {
      "location": "地点",
      "atmosphere": "氛围",
      "key_details": "关键细节提示"
    }
  ],
  "continuity": {
    "must_keep": ["必须保持的事实/设定"],
    "avoid": ["禁止破坏的设定/预支的内容"],
    "boundary_notes": "本章边界说明"
  },
  "writing_guide": {
    "dialogue": "对话写作要求",
    "emotion": "情绪展示要求",
    "style": "风格参考",
    "quality_rules": ["必须遵守的质量规则"]
  }
}

约束：
- plot_beats 3-7 个，按顺序排列；characters 只列出本章真正出场的角色；scenes 1-4 个。
- foreshadowing 必须覆盖检索结果中 status 为 due/overdue/approaching 的伏笔。
- 全文字数控制在 {MAX_OUTPUT_CHARS} 字以内。"""


def _compact_sections(sections: dict[str, Any], max_chars: int = MAX_INPUT_CHARS) -> dict[str, Any]:
    """裁剪 sections 到输入上限，优先保留对正文写作最关键的分区。"""
    if not isinstance(sections, dict) or not sections:
        return {}
    priority = [
        "chapter_plan",
        "story_memory",
        "previous_chapter",
        "open_threads",
        "facts",
        "entities",
        "resources",
        "recent_chapters",
        "style_profile",
        "user_instruction",
    ]
    ordered = [key for key in priority if key in sections]
    ordered += [key for key in sections if key not in priority]

    kept: dict[str, Any] = {}
    used = 0
    for key in ordered:
        item = sections[key]
        if item in (None, "", [], {}):
            continue
        text = json.dumps(item, ensure_ascii=False, default=str)
        if used + len(text) > max_chars and kept:
            logger.info("创作包 AI 输入裁剪：跳过分区 %s（已用 %d/%d 字符）", key, used, max_chars)
            continue
        kept[key] = item
        used += len(text)
    return kept


def build_user_prompt(context_pack: dict[str, Any], chapter_info: dict[str, Any]) -> str:
    """把检索结果 + 章节大纲组装成 user prompt。"""
    sections = _compact_sections(context_pack.get("sections") if isinstance(context_pack.get("sections"), dict) else {})
    section_parts: list[str] = []
    for key, value in sections.items():
        section_parts.append(f"## {key}\n{json.dumps(value, ensure_ascii=False, default=str)}")
    retrieval_text = "\n\n".join(section_parts) or "（无检索结果）"

    chapter_parts: list[str] = []
    for key in ("chapter_number", "title", "act", "summary", "goal", "conflict", "hook", "payoff", "highlight", "key_events"):
        if key in chapter_info and chapter_info[key] not in (None, "", [], {}):
            chapter_parts.append(f"- {key}: {json.dumps(chapter_info[key], ensure_ascii=False, default=str)}")
    chapter_text = "\n".join(chapter_parts) or "（无章节大纲）"

    return f"""## 章节大纲
{chapter_text}

## 本章知识库检索结果
{retrieval_text}

请根据以上信息生成正文创作说明 JSON。"""


async def _call_creation_pack_ai(
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """调用 DeepSeek 获取 JSON；关闭思考模式，失败时仅做一次受控重试。

    思考型模型（glm-5.3-flash 等）经网关调用会忽略 thinking=disabled，
    reasoning 吃光输出预算时 HTTP 200 但 content 为空；检测到该情况
    （finish_reason=length + reasoning_tokens 占比超阈值）时放大 max_tokens 重试。
    """
    if not _deepseek.runtime_base_url():
        raise ValueError("DeepSeek API 地址未配置，请先调用配置注入")
    started_at = time.monotonic()
    last_exc: Exception | None = None
    max_attempts = 2
    current_max_tokens = CREATION_PACK_MAX_TOKENS
    for attempt in range(max_attempts):
        payload = {
            "model": _deepseek.runtime_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0.4,
            "max_tokens": current_max_tokens,
            "response_format": {"type": "json_object"},
        }
        payload = _deepseek._apply_runtime_params(payload)
        # 创作包需要直接返回结构化结果，避免推理内容耗尽输出预算后 content 为空。
        payload["thinking"] = {"type": "disabled"}
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{_deepseek.runtime_base_url()}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                response.raise_for_status()
                response_data = _deepseek._response_json(response, context="DeepSeek")
                choices = response_data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("DeepSeek 响应缺少 choices")
                message = choices[0].get("message")
                if not isinstance(message, dict):
                    raise ValueError("DeepSeek 响应缺少 message")
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    # 诊断：HTTP 200 + 空 content 通常是思考型模型 reasoning 吃光输出预算
                    finish_reason = (choices[0] or {}).get("finish_reason")
                    usage = response_data.get("usage") or {}
                    usage_details = usage.get("completion_tokens_details") or {}
                    reasoning_tokens = usage_details.get("reasoning_tokens")
                    logger.warning(
                        "创作包 AI 返回空 content：finish_reason=%s usage=%s 输入字符 system=%d user=%d",
                        finish_reason,
                        usage,
                        len(system_prompt),
                        len(user_prompt),
                    )
                    requested = int(payload.get("max_tokens") or 0)
                    # 判定依据对齐 opencode 的治理经验：不用 token 计数估算（网关可能
                    # 重建 usage、reasoning 计入口径不一），只要"length + 空 content"即视为
                    # 输出预算被思考耗尽，做一次有界的预算升级重试。
                    reasoning_ate_budget = str(finish_reason or "").lower() == "length"
                    if (
                        reasoning_ate_budget
                        and requested < _CREATION_PACK_BOOST_MAX_TOKENS
                        and attempt + 1 < max_attempts
                    ):
                        boosted = min(
                            _CREATION_PACK_BOOST_MAX_TOKENS,
                            requested * _CREATION_PACK_BOOST_FACTOR,
                        )
                        logger.warning(
                            "创作包思考预算升级重试：reasoning_tokens=%s requested=%s boosted=%s",
                            reasoning_tokens,
                            requested,
                            boosted,
                        )
                        last_exc = ValueError("DeepSeek 响应 content 为空（思考消耗输出预算）")
                        current_max_tokens = boosted
                        raise _BoostRetry()
                    raise ValueError("DeepSeek 响应 content 为空")
                return _extract_json_object(content)
        except _BoostRetry:
            continue
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in (403, 524) and attempt + 1 < max_attempts:
                logger.warning("创作包 AI 调用 HTTP %s，准备最后一次重试", status_code)
                await asyncio.sleep(15)
                last_exc = exc
                continue
            raise
        except (httpx.TransportError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt + 1 < max_attempts:
                elapsed = time.monotonic() - started_at
                # httpcore 的超时异常 str 可能为空串，日志里补上异常类型与耗时便于定位。
                detail = str(exc).strip() or f"{type(exc).__name__}"
                logger.warning(
                    "创作包 AI 调用异常，准备最后一次重试：%s elapsed=%.1fs", detail, elapsed,
                )
                await asyncio.sleep(2)
                continue
    final_detail = "未知错误" if last_exc is None else (str(last_exc).strip() or type(last_exc).__name__)
    raise RuntimeError(f"创作包 AI 调用连续 {max_attempts} 次失败：{final_detail}") from last_exc


def _parse_and_repair(content: str) -> dict[str, Any]:
    """四级容错解析：标准提取 → 破损字段修复 → 截断修复 → 抛错。"""
    try:
        return _extract_json_object(content)
    except ValueError:
        repaired = _repair_broken_json_fields(content)
        if repaired != content:
            try:
                return _extract_json_object(repaired)
            except ValueError:
                truncated = _repair_truncated_json(repaired)
                if truncated != repaired:
                    return _extract_json_object(truncated)
        else:
            truncated = _repair_truncated_json(content)
            if truncated != content:
                return _extract_json_object(truncated)
        raise ValueError("创作说明 JSON 解析失败（标准/破损/截断修复均失败）")


def _normalize_brief(raw: dict[str, Any]) -> dict[str, Any]:
    """字段级兜底与归一化，保证渲染层拿到稳定结构。"""
    chapter_task = raw.get("chapter_task")
    if not isinstance(chapter_task, dict):
        chapter_task = {}

    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _as_str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    plot_beats = _as_list(raw.get("plot_beats"))
    for index, beat in enumerate(plot_beats):
        beat.setdefault("order", index + 1)
        beat.setdefault("type", "推进")
        beat.setdefault("summary", "")
        beat.setdefault("characters", _as_str_list(beat.get("characters")))
        beat.setdefault("key_actions", _as_str_list(beat.get("key_actions")))
        beat.setdefault("dialogue_hints", "")

    foreshadowing = _as_list(raw.get("foreshadowing"))
    for item in foreshadowing:
        item.setdefault("title", "")
        item.setdefault("status", "background")
        item.setdefault("action", "")
        item.setdefault("note", "")

    characters = _as_list(raw.get("characters"))
    for item in characters:
        item.setdefault("name", "")
        item.setdefault("motivation", "")
        item.setdefault("current_state", "")
        item.setdefault("arc", "")

    scenes = _as_list(raw.get("scenes"))
    for item in scenes:
        item.setdefault("location", "")
        item.setdefault("atmosphere", "")
        item.setdefault("key_details", "")

    continuity = raw.get("continuity")
    if not isinstance(continuity, dict):
        continuity = {}
    continuity.setdefault("must_keep", _as_str_list(continuity.get("must_keep")))
    continuity.setdefault("avoid", _as_str_list(continuity.get("avoid")))
    continuity.setdefault("boundary_notes", "")

    writing_guide = raw.get("writing_guide")
    if not isinstance(writing_guide, dict):
        writing_guide = {}
    writing_guide.setdefault("dialogue", "")
    writing_guide.setdefault("emotion", "")
    writing_guide.setdefault("style", "")
    writing_guide.setdefault("quality_rules", _as_str_list(writing_guide.get("quality_rules")))

    return {
        "chapter_task": chapter_task,
        "plot_beats": plot_beats,
        "foreshadowing": foreshadowing,
        "characters": characters,
        "scenes": scenes,
        "continuity": continuity,
        "writing_guide": writing_guide,
    }


def _validate_brief(brief: dict[str, Any]) -> None:
    """阻止缺少章节执行信息的空壳结果被当作有效 AI 创作包。"""
    chapter_task = brief.get("chapter_task")
    plot_beats = brief.get("plot_beats")
    continuity = brief.get("continuity")
    if not isinstance(chapter_task, dict) or not any(
        str(chapter_task.get(key) or "").strip()
        for key in ("goal", "conflict", "summary", "hook")
    ):
        raise ValueError("创作说明缺少本章任务")
    if not isinstance(plot_beats, list) or not any(
        isinstance(item, dict) and str(item.get("summary") or "").strip()
        for item in plot_beats
    ):
        raise ValueError("创作说明缺少剧情推进")
    if not isinstance(continuity, dict) or not (
        continuity.get("must_keep")
        or continuity.get("avoid")
        or str(continuity.get("boundary_notes") or "").strip()
    ):
        raise ValueError("创作说明缺少连续性约束")


def _build_system_prompt_with_quality(db) -> str:
    """把平台写作质量规范注入 system prompt（对齐框架直出标准）。"""
    methodology = get_methodology_from_db(db) if db is not None else ""
    if methodology:
        return SYSTEM_PROMPT + "\n\n## 平台写作质量标准（正文 Agent 必须遵守）\n" + str(methodology)[:4000]
    return SYSTEM_PROMPT


async def generate_ai_creation_brief(
    context_pack: dict[str, Any],
    chapter_info: dict[str, Any],
    api_key: str | None,
    db=None,
) -> dict[str, Any] | None:
    """AI 驱动生成正文创作说明 JSON。

    返回结构化的创作说明 dict；任何失败返回 None（调用方回退固定模板）。
    调用方必须已通过 _user_deepseek_api_key 完成运行时配置注入。
    """
    if not api_key:
        logger.info("创作包 AI 生成跳过：无 DeepSeek API Key")
        return None
    try:
        system_prompt = _build_system_prompt_with_quality(db)
        user_prompt = build_user_prompt(context_pack, chapter_info)
        raw = await _call_creation_pack_ai(api_key, system_prompt, user_prompt)
        if not isinstance(raw, dict):
            raise ValueError("创作说明 JSON 顶层不是对象")
        brief = _normalize_brief(raw)
        _validate_brief(brief)
        logger.info(
            "创作包 AI 生成成功：chapter=%s beats=%d 伏笔=%d 人物=%d",
            chapter_info.get("chapter_number"),
            len(brief["plot_beats"]),
            len(brief["foreshadowing"]),
            len(brief["characters"]),
        )
        return brief
    except Exception as exc:  # noqa: BLE001 - 任何失败都回退模板
        logger.warning("创作包 AI 生成失败，将回退固定模板：%s", exc)
        return None
