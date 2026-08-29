"""漫剧画布 AI 导演服务：把已审核场景动态编排为视频单元方案。

两条独立角色阶段：
1. 剧情导演（节奏编排）：合并/拆分剧情节拍，决定单元顺序与动态时长；
2. 镜头导演（生成提示词）：为每个单元写 video_prompt 与可选故事板脚本。

设计红线（区别于生产章节工作流）：
- 不固定 15 秒 / 10 秒；单元时长由内容密度决定（3-60s 服务层安全区间），
  提交前的最终归一化交给模型能力配置（video_duration.normalize_video_duration）。
- 不直接调用图片/视频生成；本服务只产出可审阅方案。
- 所有剧本对白/旁白必须保留原文；beat 覆盖必须完整可追溯。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from services.errors import UpstreamServiceError

logger = logging.getLogger(__name__)

DIRECTOR_TIMEOUT_SECONDS = 600
PLAN_VERSION = 1
# 服务层安全区间：过短不成镜、过长超上游可控范围；provider 能力归一在运行时提交前完成。
MIN_UNIT_DURATION = 3
MAX_UNIT_DURATION = 60


DIRECTOR_PLAN_SYSTEM_PROMPT = """# ROLE

你是短剧导演兼剪辑总监，负责把已审核的分场剧本编排成一组"视频单元"（每个单元 = 一条最终成片里的连续视频片段）。

你的职责边界：
- 只做节奏编排：决定把哪些节拍（Beat）合并进同一个视频单元、在哪里切开、每个单元多少秒。
- 不写运镜细节、不写画面提示词、不生成故事板；那些由后续阶段负责。

# 动态时长规则（最重要）

每个单元的时长必须由剧情内容决定，写入 duration_seconds（整数，参考区间 3-60 秒）：
- 按动作完成时间估算：一个完整动作 2-4 秒。
- 按对白/旁白语速估算：中文每秒 3-4 字（15 字≈4 秒，30 字≈8 秒，50 字≈13 秒）。
- 按情绪转折点决定切分：转折即切，不硬拖。
- 宁短勿水：禁止为凑时长添加空镜、慢动作、重复描写；信息不足就缩短，而不是灌水。
- 禁止所有单元等长，禁止把总时长凑成某个固定数字，禁止假设每单元 15 秒或 10 秒。
- 单元之间时长可以差异很大：3 秒的特写反应和 20 秒的连续对峙都是合法输出。

# 拆分与合并规则

默认合并：同一场景、同一组角色、同一对话线程的连续节拍 → 一个单元。
仅在以下情况切开：
1. 合并后预估时长超过 60 秒（在容量边界处切开）；
2. 单段旁白 ≥ 50 字（独占单元）；
3. 剧情高潮的情绪断崖（绝望→希望、崩溃→决心）；
4. 场景/地点跳转；
5. 信息揭示或反转需要独立成镜以强化节奏。

# 短剧节奏要求

- 第一个单元必须快速建立钩子（冲突、悬念或异常），禁止以静态环境铺垫开场。
- 单元切换点优先落在：动作完成点、台词收尾点、情绪转折点、场景切换点。
- 相邻单元必须在 from_previous / to_next 中写清楚承接：动作惯性、视线方向、道具状态、空间关系、情绪延续。
- 每个单元承担一个完整剧情推进（开始→发展→结果），禁止把一个节拍拆成多个碎片单元。

# 输出格式

输出纯 JSON 对象：
{
  "pacing_strategy": "一两句话说明整体节奏设计",
  "units": [
    {
      "unit_id": "u-001",
      "sequence": 1,
      "scene_ids": [1],
      "beat_ids": ["1.1", "1.2"],
      "title": "单元短标题",
      "narrative_purpose": "该单元承担的核心剧情任务",
      "duration_seconds": 7,
      "duration_reason": "为什么是这个时长（动作数/对白字数/情绪转折）",
      "story_summary": "该单元剧情概要",
      "transition_in": "与上一单元的衔接方式（第一单元写'开场'）",
      "transition_out": "交给下一单元的衔接方式（最后一单元写'收束'）",
      "continuity": {"from_previous": "承接上一单元的画面/情绪要点", "to_next": "留给下一单元的画面/情绪要点", "anchor": "本单元必须保持的连续性锚点"}
    }
  ]
}

# 硬性要求

- sequence 从 1 开始连续递增，禁止跳号或重复。
- beat_ids 使用 "场景ID.节拍ID" 格式；所有场景的所有节拍必须被覆盖，禁止遗漏、禁止重复覆盖。
- 剧本中的对白/旁白原文必须原样保留在所属单元的 dialogue_or_narration 字段中，禁止改写或省略。
  （dialogue_or_narration 汇总该单元覆盖节拍的全部对白/旁白原文）
"""

DIRECTOR_PLAN_USER_HEADER = """请把下面已审核的场景剧本编排成视频单元方案。

{user_constraints}## 已审核场景（JSON）

{scenes_json}

## 输出要求

按系统指令输出纯 JSON：pacing_strategy + units[]。每个 unit 必须带 duration_seconds（按内容密度动态决定）、duration_reason、beat_ids（场景ID.节拍ID）、dialogue_or_narration（覆盖节拍的对白/旁白原文汇总）、transition_in/out、continuity。"""


DIRECTOR_PROMPT_SYSTEM_PROMPT = """# ROLE

你是镜头导演，负责为已经编排好的视频单元撰写可执行的 AI 视频生成提示词。

每个单元是一条独立视频，时长已由编排阶段决定（各单元不同）。你按单元自己的 duration_seconds 设计内容，禁止套用固定时长模板。

# 每个单元输出

- video_prompt：一段完整、可直接用于 AI 视频生成的中文提示词，必须包含：
  1. 场景环境（地点、时间、光线）
  2. 出场角色与其动作/姿态/表情（禁止描述角色外貌、服装颜色等外观设定，外观由参考图决定）
  3. 核心动作推进与情绪变化（在该单元时长内可完成）
  4. 对白/旁白原文（如有，用「角色名：「台词」」格式，原样保留）
  5. 与前后单元的衔接提示（承接上一单元的动作惯性/情绪，结尾为下一单元留出动势）
  6. 景别与运镜（推拉摇移跟随内容节奏）
- storyboard_json（可选）：该单元内部的时间分段脚本，格式：
  {"segments": [{"start_second": 0, "end_second": 3.5, "story_task": "...", "visual_action": "...", "dialogue_or_narration": "原文或空串", "camera_direction": "..."}]}
  分段数量由内容决定（不固定 3/5/6 段），所有段落的起止时间必须连续并恰好覆盖 [0, duration_seconds]。

# 硬性要求

- 对白/旁白必须原样保留，禁止改写、缩写、翻译。
- 禁止输出角色外貌描述。
- 禁止元响应（"好的""以下是"等开场白）；直接输出 JSON。
- 视频提示词必须与该单元的 story_summary、narrative_purpose 一致，不得新增剧情。

输出纯 JSON：
{
  "units": [
    {"unit_id": "u-001", "video_prompt": "...", "storyboard_prompt": "（可选）", "storyboard_json": {"segments": [...]}}
  ]
}
"""

DIRECTOR_PROMPT_USER_HEADER = """请为以下视频单元撰写生成提示词。

## 整体节奏策略

{pacing_strategy}

## 视频单元（按顺序）

{units_json}

## 输出要求

按系统指令输出纯 JSON：units[]，每个 unit 带 unit_id + video_prompt（+ 可选 storyboard_prompt / storyboard_json）。"""


def _build_beat_index(scenes: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, tuple[dict[str, Any], dict[str, Any]]]]:
    """建立节拍别名索引：beat_id 原样与 "场景ID.节拍ID" 两种写法都可命中同一节拍。

    规范键统一为 "场景ID.节拍ID"，避免不同场景出现同名 beat_id 时互相覆盖。
    """
    alias_to_canonical: dict[str, str] = {}
    beats: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for scene in scenes:
        scene_id = scene.get("scene_id")
        for beat in scene.get("beats") or []:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("beat_id") or "").strip()
            if not beat_id:
                continue
            canonical = f"{scene_id}.{beat_id}"
            beats[canonical] = (scene, beat)
            for alias in {beat_id, canonical}:
                alias_to_canonical.setdefault(alias, canonical)
    return alias_to_canonical, beats


def _dialogue_lines(dialogue: Any) -> list[str]:
    """把 beat.dialogue 归一为台词文本列表（保留原文）。"""
    lines: list[str] = []
    if isinstance(dialogue, str):
        text = dialogue.strip()
        if text:
            lines.append(text)
    elif isinstance(dialogue, list):
        for item in dialogue:
            if isinstance(item, dict):
                character = str(item.get("character") or "").strip()
                line = str(item.get("line") or "").strip()
                text = f"{character}：{line}" if character and line else (line or character)
                if text:
                    lines.append(text)
            elif str(item or "").strip():
                lines.append(str(item).strip())
    return lines


def _normalize_visual_anchors(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                desc = str(item.get("description") or "").strip()
                if desc:
                    items.append({"type": str(item.get("type") or "细节").strip() or "细节", "description": desc})
            elif str(item or "").strip():
                items.append({"type": "细节", "description": str(item).strip()})
    elif isinstance(value, str) and value.strip():
        for line in value.splitlines():
            line = line.strip().strip(",")
            if not line:
                continue
            match = re.match(r"^['\"]?type['\"]?\s*[:：]\s*['\"]?([\w-]+)['\"]?[,，]\s*['\"]?description['\"]?\s*[:：]\s*['\"]?(.+?)['\"]?\s*$", line)
            if match:
                items.append({"type": match.group(1), "description": match.group(2)})
            else:
                items.append({"type": "细节", "description": line})
    return items


def build_director_plan_user_prompt(scenes: list[dict[str, Any]], user_constraints: str | None = None) -> str:
    import json as _json

    constraints = f"## 用户节奏约束\n\n{user_constraints.strip()}\n\n" if user_constraints and user_constraints.strip() else ""
    return DIRECTOR_PLAN_USER_HEADER.format(
        user_constraints=constraints,
        scenes_json=_json.dumps(scenes, ensure_ascii=False, indent=2),
    )


def build_director_prompt_user_prompt(plan: dict[str, Any]) -> str:
    import json as _json

    units = [
        {key: unit.get(key) for key in (
            "unit_id", "sequence", "title", "duration_seconds", "narrative_purpose",
            "story_summary", "dialogue_or_narration", "characters", "transition_in", "transition_out", "continuity",
        )}
        for unit in plan.get("units") or []
        if isinstance(unit, dict)
    ]
    return DIRECTOR_PROMPT_USER_HEADER.format(
        pacing_strategy=str(plan.get("pacing_strategy") or ""),
        units_json=_json.dumps(units, ensure_ascii=False, indent=2),
    )


async def _call_deepseek_json(*, system: str, user: str, api_key: str | None, max_tokens: int = 32768) -> dict[str, Any]:
    """调用 DeepSeek 拿 JSON 对象；错误统一映射为 UpstreamServiceError。"""
    from services import deepseek as deepseek_service

    payload: dict[str, Any] = {
        "model": deepseek_service.runtime_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    try:
        async with httpx.AsyncClient(timeout=DIRECTOR_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
        resp.raise_for_status()
        data = deepseek_service._response_json(resp, context="DeepSeek")
    except httpx.TimeoutException as exc:
        raise UpstreamServiceError("导演编排响应超时，请稍后重试", retryable=True, provider="DeepSeek", status_code=504, code="director_plan_timeout") from exc
    except httpx.HTTPStatusError as exc:
        status_code = int(exc.response.status_code)
        raise UpstreamServiceError(
            "导演编排服务暂时不可用，请稍后重试",
            retryable=status_code in {408, 409, 425, 429, 500, 502, 503, 504},
            provider="DeepSeek",
            status_code=status_code,
            code="director_plan_failed",
            diagnostics={"upstream_status_code": status_code},
        ) from exc
    except httpx.RequestError as exc:
        raise UpstreamServiceError("导演编排网络连接失败，请稍后重试", retryable=True, provider="DeepSeek", status_code=502, code="director_plan_network_error") from exc

    content = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    try:
        result = deepseek_service._extract_json_object(content)
    except ValueError:
        repaired = deepseek_service._repair_truncated_json(content)
        try:
            result = deepseek_service._extract_json_object(repaired)
        except ValueError as exc:
            raise UpstreamServiceError(
                "导演编排返回的 JSON 无法解析，请重试",
                retryable=True,
                provider="DeepSeek",
                status_code=502,
                code="director_plan_invalid_json",
                diagnostics={"raw_head": content[:300]},
            ) from exc
    if not isinstance(result, dict):
        raise UpstreamServiceError("导演编排返回格式异常，请重试", retryable=True, provider="DeepSeek", status_code=502, code="director_plan_invalid_shape")
    return result


def _empty_continuity() -> dict[str, str]:
    return {"from_previous": "", "to_next": "", "anchor": ""}


def _normalize_unit(raw: Any, index: int, warnings: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    unit: dict[str, Any] = {}
    unit["unit_id"] = str(raw.get("unit_id") or "").strip() or f"u-{index + 1:03d}"
    sequence = raw.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        try:
            sequence = int(sequence)
        except (TypeError, ValueError):
            sequence = index + 1
            warnings.append(f"单元 {unit['unit_id']} 缺少有效 sequence，已按顺序补齐")
    unit["sequence"] = sequence
    unit["title"] = str(raw.get("title") or "").strip()
    unit["narrative_purpose"] = str(raw.get("narrative_purpose") or "").strip()
    unit["story_summary"] = str(raw.get("story_summary") or "").strip()
    duration = raw.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        unit["duration_seconds"] = None
        unit["duration_requested"] = None
    else:
        unit["duration_requested"] = duration
        unit["duration_seconds"] = int(duration)
    unit["duration_reason"] = str(raw.get("duration_reason") or "").strip()
    dialogue = raw.get("dialogue_or_narration")
    unit["dialogue_or_narration"] = dialogue.strip() if isinstance(dialogue, str) else str(dialogue or "").strip()
    beat_ids = raw.get("beat_ids")
    if isinstance(beat_ids, list):
        unit["beat_ids"] = [str(item).strip() for item in beat_ids if str(item or "").strip()]
    elif isinstance(beat_ids, str) and beat_ids.strip():
        unit["beat_ids"] = [item.strip() for item in re.split(r"[,，;；\s]+", beat_ids.strip()) if item.strip()]
    else:
        unit["beat_ids"] = []
    scene_ids = raw.get("scene_ids")
    if isinstance(scene_ids, list):
        unit["scene_ids"] = [item for item in scene_ids if isinstance(item, (int, str)) and str(item).strip()]
    else:
        unit["scene_ids"] = []
    unit["characters"] = [str(c).strip() for c in (raw.get("characters") or []) if str(c or "").strip()]
    unit["visual_anchors"] = _normalize_visual_anchors(raw.get("visual_anchors"))
    unit["action_plan"] = str(raw.get("action_plan") or "").strip()
    unit["camera_plan"] = str(raw.get("camera_plan") or "").strip()
    unit["emotion_plan"] = str(raw.get("emotion_plan") or "").strip()
    unit["transition_in"] = str(raw.get("transition_in") or "").strip()
    unit["transition_out"] = str(raw.get("transition_out") or "").strip()
    continuity = raw.get("continuity")
    if isinstance(continuity, dict):
        normalized = _empty_continuity()
        for key in normalized:
            normalized[key] = str(continuity.get(key) or "").strip()
    elif isinstance(continuity, str) and continuity.strip():
        normalized = _empty_continuity()
        normalized["anchor"] = continuity.strip()
    else:
        normalized = _empty_continuity()
    unit["continuity"] = normalized
    unit["video_prompt"] = str(raw.get("video_prompt") or "").strip()
    unit["storyboard_prompt"] = str(raw.get("storyboard_prompt") or "").strip()
    storyboard = raw.get("storyboard_json")
    unit["storyboard_json"] = storyboard if isinstance(storyboard, dict) else None
    unit_warnings = [str(w).strip() for w in (raw.get("warnings") or []) if str(w or "").strip()]
    if unit_warnings:
        unit["warnings"] = unit_warnings
    return unit


def _validate_segments(unit: dict[str, Any], errors: list[str]) -> None:
    storyboard = unit.get("storyboard_json")
    if not isinstance(storyboard, dict):
        return
    segments = storyboard.get("segments")
    if segments in (None, [], ""):
        return
    if not isinstance(segments, list):
        errors.append(f"单元 {unit['unit_id']} 的 storyboard_json.segments 必须是数组")
        return
    duration = unit.get("duration_seconds")
    if not isinstance(duration, int):
        return
    cursor = 0.0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(f"单元 {unit['unit_id']} 第 {index + 1} 段格式无效")
            return
        try:
            start = float(segment.get("start_second"))
            end = float(segment.get("end_second"))
        except (TypeError, ValueError):
            errors.append(f"单元 {unit['unit_id']} 第 {index + 1} 段起止时间无效")
            return
        if start < cursor - 0.05 or start > cursor + 0.05 or end <= start + 0.01:
            errors.append(f"单元 {unit['unit_id']} 第 {index + 1} 段时间轴断裂、重叠或倒退")
            return
        cursor = end
    if cursor < duration - 0.51 or cursor > duration + 0.51:
        errors.append(f"单元 {unit['unit_id']} 分段时间总和 {cursor:g}s 与时长 {duration}s 不符")


def _estimate_unit_duration(beat_entries: list[dict[str, Any]]) -> int:
    """按节拍动作与对白语速确定性估算时长（动作 3s/个，对白每 3.5 字 1s）。"""
    seconds = 0.0
    for beat in beat_entries:
        if str(beat.get("action") or "").strip():
            seconds += 3
        for line in _dialogue_lines(beat.get("dialogue")):
            seconds += max(2.0, len(line) / 3.5)
    return int(max(MIN_UNIT_DURATION, min(MAX_UNIT_DURATION, round(seconds) or MIN_UNIT_DURATION)))


def _make_remedial_unit(
    sequence: int,
    scene_id: str,
    scene: dict[str, Any],
    entries: list[tuple[str, dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """为漏覆盖节拍生成确定性补充单元：字段全部来自剧本原文，可审阅可编辑。"""
    beat_ids = [canonical for canonical, _scene, _beat in entries]
    beats_only = [beat for _canonical, _scene, beat in entries]
    dialogue_parts: list[str] = []
    action_parts: list[str] = []
    for beat in beats_only:
        action = str(beat.get("action") or "").strip()
        if action:
            action_parts.append(action)
        for line in _dialogue_lines(beat.get("dialogue")):
            dialogue_parts.append(line)
    duration = _estimate_unit_duration(beats_only)
    characters = [str(c).strip() for c in (scene.get("characters") or []) if str(c or "").strip()]
    unit: dict[str, Any] = {
        "unit_id": f"u-r{sequence:03d}",
        "sequence": sequence,
        "scene_ids": [scene.get("scene_id", scene_id)],
        "beat_ids": beat_ids,
        "title": f"补充单元（{scene.get('title') or f'场景 {scene_id}'}）",
        "narrative_purpose": str(scene.get("scene_purpose") or "承接场景剧情"),
        "duration_seconds": duration,
        "duration_reason": "自动补充：按节拍动作与对白语速估算",
        "story_summary": "；".join(action_parts) or f"{scene.get('title') or scene_id} 的补充剧情",
        "dialogue_or_narration": "\n".join(dialogue_parts),
        "characters": characters,
        "visual_anchors": _normalize_visual_anchors(scene.get("visual_anchors")),
        "action_plan": "；".join(action_parts),
        "camera_plan": "",
        "emotion_plan": "",
        "transition_in": "承接上一单元",
        "transition_out": str(scene.get("transition_to_next_scene") or ""),
        "continuity": {"from_previous": "承接上一单元画面与情绪", "to_next": "", "anchor": ""},
        "video_prompt": "",
        "storyboard_prompt": "",
        "storyboard_json": None,
    }
    unit["video_prompt"] = _fallback_video_prompt(unit, {str(scene.get("scene_id")): scene})
    return unit


def normalize_and_validate_director_plan(
    raw_plan: Any,
    scenes: list[dict[str, Any]],
    *,
    source_screenplay_hash: str,
    source_scene_node_id: str,
    source_scene_revision: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """确定性质量门：归一方案结构并**自动修复**可修复问题。

    修复优先于拒绝：节拍漏覆盖自动补单元、时长越界自动钳制、提示词为空自动兜底、
    对白原文缺失自动回填、分段时间轴断裂自动丢弃（可选字段）。
    只有结构级失败（非 JSON 对象 / 没有任何有效单元）才返回 errors；
    其余修复动作全部记入 warnings，随方案返回给用户审阅。
    """
    if not isinstance(raw_plan, dict):
        return None, ["导演编排结果必须是 JSON 对象"]
    warnings: list[str] = []
    units_raw = raw_plan.get("units")
    if not isinstance(units_raw, list) or not units_raw:
        return None, ["导演编排没有输出任何视频单元"]

    units: list[dict[str, Any]] = []
    for index, raw in enumerate(units_raw):
        unit = _normalize_unit(raw, index, warnings)
        if unit is not None:
            units.append(unit)
    if not units:
        return None, ["导演编排的视频单元全部无效"]

    # ── 自动修复 1：unit_id 去重 ──
    seen_ids: set[str] = set()
    for unit in units:
        unit_id = unit["unit_id"]
        if unit_id in seen_ids:
            unit["unit_id"] = f"{unit_id}-d{len(seen_ids)}"
            warnings.append(f"检测到重复 unit_id，已重命名为 {unit['unit_id']}")
        seen_ids.add(unit["unit_id"])

    # ── 自动修复 2：sequence 重复/跳号 → 按原始顺序重新编号 ──
    units.sort(key=lambda item: item["sequence"])
    for position, unit in enumerate(units, start=1):
        if unit["sequence"] != position:
            warnings.append(f"单元 {unit['unit_id']} 的 sequence 已由 {unit['sequence']} 修正为 {position}")
            unit["sequence"] = position

    # ── beat 归一：别名 → 规范键；未知引用丢弃；重复覆盖保留首个 ──
    alias_to_canonical, beats = _build_beat_index(scenes)
    covered: dict[str, str] = {}
    for unit in units:
        normalized_ids: list[str] = []
        for beat_key in unit["beat_ids"]:
            canonical = alias_to_canonical.get(beat_key)
            if canonical is None:
                warnings.append(f"单元 {unit['unit_id']} 引用了不存在的节拍 {beat_key}，已忽略")
                continue
            if canonical in covered:
                warnings.append(f"节拍 {canonical} 被多个单元重复覆盖，保留 {covered[canonical]} 的覆盖")
                continue
            covered[canonical] = unit["unit_id"]
            normalized_ids.append(canonical)
        unit["beat_ids"] = normalized_ids

    # ── 自动修复 3：未覆盖节拍 → 按场景生成补充单元（确定性字段 + 兜底提示词）──
    uncovered_by_scene: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    for canonical, (scene, beat) in beats.items():
        if canonical not in covered:
            uncovered_by_scene.setdefault(str(scene.get("scene_id")), []).append((canonical, scene, beat))
    scene_map_by_id = {str(scene.get("scene_id")): scene for scene in scenes}
    if uncovered_by_scene:
        next_sequence = len(units) + 1
        for scene_id, entries in uncovered_by_scene.items():
            scene = scene_map_by_id.get(scene_id, {})
            remedial = _make_remedial_unit(next_sequence, scene_id, scene, entries)
            units.append(remedial)
            covered.update({canonical: remedial["unit_id"] for canonical, _scene, _beat in entries})
            next_sequence += 1
        warnings.append("导演方案未覆盖部分节拍，已自动生成补充单元：" + "、".join(sorted(uncovered_by_scene)))

    # ── 自动修复 4：时长缺失按节拍密度估算，越界钳制 ──
    canonical_beats_by_unit: dict[str, list[dict[str, Any]]] = {}
    for canonical, (scene, beat) in beats.items():
        owner = covered.get(canonical)
        if owner:
            canonical_beats_by_unit.setdefault(owner, []).append(beat)
    for unit in units:
        duration = unit.get("duration_seconds")
        if not isinstance(duration, int) or isinstance(duration, bool):
            estimated = _estimate_unit_duration(canonical_beats_by_unit.get(unit["unit_id"]) or [])
            unit["duration_seconds"] = estimated
            unit["duration_reason"] = unit["duration_reason"] or "时长缺失，已按节拍动作与对白语速自动估算"
            warnings.append(f"单元 {unit['unit_id']} 缺少时长，已自动估算为 {estimated}s")
        elif not (MIN_UNIT_DURATION <= duration <= MAX_UNIT_DURATION):
            clamped = max(MIN_UNIT_DURATION, min(MAX_UNIT_DURATION, duration))
            warnings.append(f"单元 {unit['unit_id']} 的时长 {duration}s 超出安全区间，已钳制为 {clamped}s")
            unit["duration_seconds"] = clamped
        if not unit["duration_reason"]:
            unit["duration_reason"] = f"按 {len(unit['beat_ids']) or 1} 个节拍估算"

    # ── 自动修复 5：video_prompt 缺失/过短 → 用编排字段兜底 ──
    for unit in units:
        prompt = unit.get("video_prompt") or ""
        if len(prompt) < 12:
            fallback = _fallback_video_prompt(unit, scene_map_by_id)
            if fallback:
                warnings.append(f"单元 {unit['unit_id']} 的视频提示词缺失或过短，已按编排信息生成基础提示词")
                unit["video_prompt"] = fallback if not prompt else f"{prompt}。{fallback}"

    # ── 自动修复 6：对白原文回填（只增不改）──
    for unit in units:
        merged_text = " ".join(filter(None, [unit.get("dialogue_or_narration"), unit.get("story_summary"), unit.get("video_prompt")]))
        missing_lines: list[str] = []
        for canonical in unit["beat_ids"]:
            entry = beats.get(canonical)
            if not entry:
                continue
            for line in _dialogue_lines(entry[1].get("dialogue")):
                core = line.split("：", 1)[-1].strip()
                if len(core) >= 6 and core not in merged_text and line not in missing_lines:
                    missing_lines.append(line)
        if missing_lines:
            unit["dialogue_or_narration"] = "\n".join(filter(None, [unit.get("dialogue_or_narration"), *missing_lines]))
            warnings.append(f"单元 {unit['unit_id']} 缺失的对白原文已自动回填")

    # ── 自动修复 7：分段时间轴断裂 → 丢弃可选 storyboard_json ──
    for unit in units:
        segment_errors: list[str] = []
        _validate_segments(unit, segment_errors)
        if segment_errors:
            unit["storyboard_json"] = None
            warnings.append(f"单元 {unit['unit_id']} 的分段时间轴不完整，已丢弃该可选脚本")

    # ── 连续性承接：缺失仅提示，不阻断 ──
    ordered = sorted(units, key=lambda item: item["sequence"])
    for position, unit in enumerate(ordered):
        continuity = unit["continuity"]
        if position > 0 and not continuity["from_previous"]:
            warnings.append(f"单元 {unit['unit_id']} 未说明与上一单元的承接")
        if position < len(ordered) - 1 and not continuity["to_next"]:
            warnings.append(f"单元 {unit['unit_id']} 未说明交给下一单元的衔接")

    plan = {
        "plan_version": PLAN_VERSION,
        "pacing_strategy": str(raw_plan.get("pacing_strategy") or "").strip(),
        "units": ordered,
        "warnings": list(dict.fromkeys(warnings)),
        "meta": {
            "source_screenplay_hash": source_screenplay_hash,
            "source_scene_node_id": source_scene_node_id,
            "source_scene_revision": source_scene_revision,
        },
    }
    return plan, []


def _fallback_storyboard_prompt(unit: dict[str, Any], scene_map: dict[str, dict[str, Any]]) -> str:
    """分镜提示词兜底：用编排字段拼出可直接生成故事板线稿图的提示词。"""
    scene = scene_map.get(str((unit.get("scene_ids") or [""])[0])) or {}
    parts: list[str] = ["一张完整的电影级故事板线稿展示图，黑白线条，清晰轮廓，适合后续上色"]
    location = str(scene.get("location") or "").strip()
    time_of_day = str(scene.get("time_of_day") or "").strip()
    if location or time_of_day:
        parts.append(f"场景环境：{location or '未明确地点'}，{time_of_day or '时间未明确'}，光线与空间布局清晰")
    action = unit.get("action_plan") or unit.get("story_summary")
    if action:
        parts.append(f"核心画面：{action}，人物只表现动作姿态与表情，不描绘外貌服装")
    if unit.get("emotion_plan"):
        parts.append(f"情绪氛围：{unit['emotion_plan']}")
    anchors = [item.get("description") for item in (unit.get("visual_anchors") or []) if isinstance(item, dict) and item.get("description")]
    if anchors:
        parts.append("画面锚点：" + "；".join(str(item) for item in anchors[:6]))
    if unit.get("dialogue_or_narration"):
        parts.append(f"分镜格下方标注文字「对白：{unit['dialogue_or_narration']}」")
    if unit.get("camera_plan"):
        parts.append(f"景别与构图：{unit['camera_plan']}")
    return "\n".join(parts)


def _compact_unit_warnings(warnings: list[str]) -> list[str]:
    """把逐单元重复的警告聚合为一条计数提示，避免提示风暴淹没界面。"""
    unit_pattern = re.compile(r"^单元\s+(\S+)\s+(.+)$")
    grouped: dict[str, int] = {}
    group_order: list[str] = []
    plain: list[str] = []
    for warning in warnings:
        text = str(warning or "").strip()
        if not text:
            continue
        match = unit_pattern.match(text)
        if match:
            key = match.group(2)
            if key not in grouped:
                grouped[key] = 0
                group_order.append(key)
            grouped[key] += 1
        elif text not in plain:
            plain.append(text)
    out = list(plain)
    for key in group_order:
        count = grouped[key]
        out.append(f"{count} 个单元：{key}" if count > 1 else key)
    return out



def _fallback_video_prompt(unit: dict[str, Any], scene_map: dict[str, dict[str, Any]]) -> str:
    """镜头导演阶段失败时的确定性兜底：用编排字段拼出可用提示词。"""
    parts: list[str] = []
    scene = scene_map.get(str((unit.get("scene_ids") or [""])[0])) or {}
    location = str(scene.get("location") or "").strip()
    time_of_day = str(scene.get("time_of_day") or "").strip()
    if location or time_of_day:
        parts.append(f"场景：{location or '未明确地点'}，{time_of_day or '时间未明确'}")
    if unit.get("story_summary"):
        parts.append(str(unit["story_summary"]))
    if unit.get("action_plan"):
        parts.append(str(unit["action_plan"]))
    if unit.get("emotion_plan"):
        parts.append(f"情绪：{unit['emotion_plan']}")
    if unit.get("dialogue_or_narration"):
        parts.append(f"对白/旁白（原样保留）：{unit['dialogue_or_narration']}")
    if unit.get("transition_out"):
        parts.append(f"结尾衔接：{unit['transition_out']}")
    if unit.get("duration_seconds"):
        parts.append(f"本段时长约 {unit['duration_seconds']} 秒，动作与对白必须在该时长内完成")
    return "\n".join(parts) or str(unit.get("title") or "视频单元")


async def orchestrate_scene_video_units(
    *,
    scenes: list[dict[str, Any]],
    source_screenplay_hash: str,
    source_scene_node_id: str,
    source_scene_revision: str,
    api_key: str | None = None,
    user_constraints: str | None = None,
) -> dict[str, Any]:
    """两阶段编排：剧情导演拆单元 + 镜头导演写提示词，质量门失败自动修复一次。"""
    if not scenes:
        raise ValueError("没有已审核场景，无法编排")

    plan_user = build_director_plan_user_prompt(scenes, user_constraints)
    raw_plan = await _call_deepseek_json(system=DIRECTOR_PLAN_SYSTEM_PROMPT, user=plan_user, api_key=api_key)
    plan, errors = normalize_and_validate_director_plan(
        raw_plan, scenes,
        source_screenplay_hash=source_screenplay_hash,
        source_scene_node_id=source_scene_node_id,
        source_scene_revision=source_scene_revision,
    )
    if plan is None:
        repair_user = (
            plan_user
            + "\n\n## 上一次输出未通过校验，必须修复以下问题后重新输出完整 JSON\n\n"
            + "\n".join(f"- {item}" for item in errors)
        )
        raw_plan = await _call_deepseek_json(system=DIRECTOR_PLAN_SYSTEM_PROMPT, user=repair_user, api_key=api_key)
        plan, errors = normalize_and_validate_director_plan(
            raw_plan, scenes,
            source_screenplay_hash=source_screenplay_hash,
            source_scene_node_id=source_scene_node_id,
            source_scene_revision=source_scene_revision,
        )
        if plan is None:
            raise UpstreamServiceError(
                "导演编排仍未生成有效方案（" + "；".join(errors[:5]) + "），请重试或换模型",
                retryable=True,
                provider="DeepSeek",
                status_code=502,
                code="director_plan_quality_failed",
                diagnostics={"issues": errors[:10]},
            )

    # 阶段二：镜头导演补提示词（失败时用编排字段确定性兜底，不浪费阶段一结果）
    scene_map = {str(scene.get("scene_id")): scene for scene in scenes}
    try:
        prompt_user = build_director_prompt_user_prompt(plan)
        prompt_result = await _call_deepseek_json(system=DIRECTOR_PROMPT_SYSTEM_PROMPT, user=prompt_user, api_key=api_key, max_tokens=32768)
        items = [item for item in (prompt_result.get("units") or []) if isinstance(item, dict)]
        by_id = {
            str(item.get("unit_id") or "").strip(): item
            for item in items
            if str(item.get("unit_id") or "").strip()
        }
        # 模型常改写 unit_id：按 id 匹配率过低时退回按顺序一一对应
        matched = sum(1 for unit in plan["units"] if unit["unit_id"] in by_id)
        use_positional = matched < max(1, len(plan["units"]) // 2)
        if use_positional:
            logger.info("镜头导演 unit_id 匹配率低（%s/%s），按顺序回退匹配", matched, len(plan["units"]))
        prompt_map = {} if use_positional else by_id
    except UpstreamServiceError as exc:
        logger.warning("镜头导演阶段失败，使用编排字段兜底: %s", exc)
        items = []
        prompt_map = {}
        use_positional = False
    if not prompt_map and not (use_positional and len(items) == len(plan["units"])):
        plan["warnings"] = list(dict.fromkeys([*(plan.get("warnings") or []), "镜头提示词阶段失败，已使用编排信息生成基础提示词"]))

    for index, unit in enumerate(plan["units"]):
        detail = prompt_map.get(str(unit["unit_id"])) or {}
        if not detail and use_positional and len(items) == len(plan["units"]):
            detail = items[index] or {}
        video_prompt = str(detail.get("video_prompt") or "").strip()
        if not video_prompt:
            video_prompt = _fallback_video_prompt(unit, scene_map)
            plan["warnings"] = list(dict.fromkeys([*(plan.get("warnings") or []), f"单元 {unit['unit_id']} 视频提示词缺失，已生成基础提示词"]))
        unit["video_prompt"] = video_prompt
        storyboard_prompt = str(detail.get("storyboard_prompt") or "").strip()
        if storyboard_prompt:
            unit["storyboard_prompt"] = storyboard_prompt
        storyboard_json = detail.get("storyboard_json")
        if isinstance(storyboard_json, dict):
            probe: list[str] = []
            unit["storyboard_json"] = storyboard_json
            _validate_segments(unit, probe)
            if probe:
                unit["storyboard_json"] = None
                plan["warnings"] = list(dict.fromkeys([*(plan.get("warnings") or []), f"单元 {unit['unit_id']} 镜头阶段返回的时间轴不完整，已丢弃该可选脚本"]))

    # 分镜提示词兜底：无论镜头阶段成败，保证每个单元都有可用于生成故事板的提示词
    for unit in plan["units"]:
        if not unit.get("storyboard_prompt"):
            unit["storyboard_prompt"] = _fallback_storyboard_prompt(unit, scene_map)
            plan["warnings"] = list(dict.fromkeys([*(plan.get("warnings") or []), f"单元 {unit['unit_id']} 缺少分镜提示词，已生成基础分镜提示词"]))

    plan["warnings"] = _compact_unit_warnings(plan["warnings"])
    return plan
