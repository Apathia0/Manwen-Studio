"""故事框架工具函数：规范化、合并、校验、章节提取。

从 main.py 中拆出的共享函数，供 main.py / agent_service.py / deepseek.py 共同使用。
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from models import Chapter, FrameworkSnapshot

logger = logging.getLogger(__name__)


# ── 章节号协整 ──────────────────────────────────────────────

def _coerce_chapter_number(raw) -> int | None:
    """将各种格式的章节号尝试转为正整数，失败返回 None。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() and raw > 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.isdigit():
            value = int(text)
            return value if value > 0 else None
        match = re.search(r"\d+", text)
        if match:
            value = int(match.group(0))
            return value if value > 0 else None
    return None


# ── 关键事件规范化 ──────────────────────────────────────────

def _normalize_key_events(raw) -> list[str] | None:
    """把 key_events 统一为 list[str] 格式。"""
    if not raw:
        return None
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return items or None
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else None
    return [str(raw).strip()] if str(raw).strip() else None


# ── 章节元数据规范化（白名单） ──────────────────────────────

CHAPTER_META_FIELDS = ("summary", "key_events", "goal", "conflict", "hook", "payoff", "highlight")

def _normalize_chapter_plan_meta(raw: dict | None) -> dict[str, Any]:
    """只保留白名单内的章节元数据字段，丢弃其余所有字段。"""
    raw = raw if isinstance(raw, dict) else {}
    payload: dict[str, Any] = {}

    summary = str(raw.get("summary") or "").strip()
    if summary:
        payload["summary"] = summary

    key_events = _normalize_key_events(raw.get("key_events"))
    if key_events:
        payload["key_events"] = key_events

    for field in ("goal", "conflict", "hook", "payoff", "highlight"):
        value = str(raw.get(field) or "").strip()
        if value:
            payload[field] = value

    return payload


# ── Act 标识归一化 ──────────────────────────────────────────

def _normalize_act_token(value) -> str:
    """把各种 act 写法统一归一化为纯数字字符串或原始文本。"""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\s_\-:：,.，。、()（）\[\]【】]+", "", text)

    _CN_NUM = {
        "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
        "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
    }

    for unit in ("幕", "章", "部分", "卷", "篇"):
        m = re.search(rf"第(.{{1,2}}){unit}", text)
        if m:
            cn = m.group(1)
            return _CN_NUM.get(cn, cn)

    word_map = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
    m_word = re.search(r"act(" + "|".join(word_map) + r")", text)
    if m_word:
        return word_map[m_word.group(1)]

    m_num = re.search(r"act(\d+)", text)
    if m_num:
        return m_num.group(1)

    m_suffix = re.search(r"(\d+)幕", text)
    if m_suffix:
        return m_suffix.group(1)

    if text.isdigit():
        return text

    return text


# ── Act 别名映射 ────────────────────────────────────────────

def _build_act_alias_map(acts: list) -> dict[str, str]:
    """为一个 three_acts 列表建立别名 → 标准标识的映射字典。"""
    alias_map: dict[str, str] = {}
    for index, raw_act in enumerate(acts, start=1):
        if isinstance(raw_act, dict):
            act_entry = raw_act
        else:
            act_entry = {"title": str(raw_act)}
        canonical = str(act_entry.get("act", index))
        aliases = {
            canonical,
            act_entry.get("title", ""),
            act_entry.get("name", ""),
        }
        for alias in aliases:
            normalized = _normalize_act_token(alias)
            if normalized:
                alias_map[normalized] = canonical
    return alias_map


# ── 框架大纲规范化 ──────────────────────────────────────────

def _normalize_framework_outline(outline: dict | None, chapters: list | None) -> dict:
    """将 chapters 列表按 act 分组并合并到 outline.three_acts 中。"""
    normalized = dict(outline or {})
    acts = normalized.get("three_acts")
    if not isinstance(acts, list):
        acts = []
    act_alias_map = _build_act_alias_map(acts)

    chapter_groups: dict[str, list[dict]] = {}
    if isinstance(chapters, list):
        for item in chapters:
            if not isinstance(item, dict):
                continue
            raw_act_key = str(item.get("act") or "").strip()
            act_key = act_alias_map.get(_normalize_act_token(raw_act_key), raw_act_key)
            chapter_number = _coerce_chapter_number(item.get("chapter_number"))
            title = str(item.get("title") or "").strip()
            if chapter_number is None or not title:
                continue
            chapter_entry = {
                "chapter_number": chapter_number,
                "title": title,
                "act": act_key or raw_act_key,
            }
            chapter_entry.update(_normalize_chapter_plan_meta(item))
            chapter_groups.setdefault(act_key, []).append(chapter_entry)

    next_unassigned: list[dict] = chapter_groups.pop("", [])
    merged_acts: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if isinstance(act, dict):
            act_entry = dict(act)
        else:
            act_entry = {"title": str(act)}
        act_label = act_entry.get("act", index)
        act_entry["act"] = act_label
        candidates = None
        for candidate_key in {
            str(act_label),
            _normalize_act_token(act_label),
            _normalize_act_token(act_entry.get("title")),
            _normalize_act_token(act_entry.get("name")),
        }:
            if candidate_key in chapter_groups:
                candidates = chapter_groups.pop(candidate_key)
                break
        if not candidates and next_unassigned:
            candidates = next_unassigned
            next_unassigned = []
        act_entry["chapters"] = sorted(candidates or [], key=lambda item: item["chapter_number"])
        merged_acts.append(act_entry)

    leftover = []
    for items in chapter_groups.values():
        leftover.extend(items)
    leftover.extend(next_unassigned)
    if leftover:
        merged_acts.append({
            "act": len(merged_acts) + 1,
            "title": "章节规划",
            "summary": "",
            "chapters": sorted(leftover, key=lambda item: item["chapter_number"]),
        })

    normalized["three_acts"] = merged_acts
    return normalized


# ── 从大纲提取扁平章节列表 ──────────────────────────────────

def _extract_outline_chapters(outline: dict | None) -> list[dict]:
    """从 outline.three_acts[].chapters[] 中提取所有有效章节为扁平列表。"""
    if not isinstance(outline, dict):
        return []
    acts = outline.get("three_acts")
    if not isinstance(acts, list):
        return []
    extracted: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if not isinstance(act, dict):
            continue
        act_label = act.get("act", index)
        chapters = act.get("chapters")
        if not isinstance(chapters, list):
            continue
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter_number = _coerce_chapter_number(item.get("chapter_number"))
            title = str(item.get("title") or "").strip()
            if chapter_number is None or not title:
                continue
            chapter_entry = dict(item)
            chapter_entry["chapter_number"] = chapter_number
            chapter_entry["title"] = title
            chapter_entry["act"] = item.get("act", act_label)
            extracted.append(chapter_entry)
    return extracted


# ── 章节规划合并 ────────────────────────────────────────────

def _merge_chapter_plans(existing: list[dict] | None, incoming: list[dict] | None) -> list[dict]:
    """按 chapter_number 合并新旧章节规划。原有章节保留，增量覆盖。"""
    merged: dict[int, dict] = {}

    def _ingest(items: list[dict] | None, *, prefer_existing: bool) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            chapter_number = _coerce_chapter_number(item.get("chapter_number"))
            title = str(item.get("title") or "").strip()
            if chapter_number is None or not title:
                continue
            normalized = dict(item)
            normalized["chapter_number"] = chapter_number
            normalized["title"] = title
            if prefer_existing and chapter_number in merged:
                current = dict(merged[chapter_number])
                current.update({k: v for k, v in normalized.items() if v not in (None, "", [], {})})
                merged[chapter_number] = current
            else:
                current = dict(merged.get(chapter_number, {}))
                current.update(normalized)
                merged[chapter_number] = current

    _ingest(existing, prefer_existing=False)
    _ingest(incoming, prefer_existing=True)
    return [merged[key] for key in sorted(merged)]


def _merge_framework_outline(
    existing_outline: dict | None,
    incoming_outline: dict | None,
    incoming_chapters: list | None,
) -> dict:
    """合并新旧大纲，保留已有章节，AI 的新章节做增量覆盖。

    合并逻辑：
    1. 从 existing_outline 提取已有章节 → existing_chapters
    2. 从 incoming_outline 提取 AI 章节 → incoming_outline_chapters
    3. incoming_chapters（顶层列表）也是 AI 章节 → 与上一步合并
    4. 最终 merged = existing_chapters 为基 + incoming 增量覆盖
    5. 已有 acts 保留，AI 的 acts 覆盖同名 act
    """
    existing_outline = existing_outline if isinstance(existing_outline, dict) else {}
    incoming_outline = incoming_outline if isinstance(incoming_outline, dict) else {}

    existing_chapters = _extract_outline_chapters(existing_outline)
    incoming_outline_chapters = _extract_outline_chapters(incoming_outline)
    combined_incoming = _merge_chapter_plans(incoming_outline_chapters, incoming_chapters)
    merged_chapters = _merge_chapter_plans(existing_chapters, combined_incoming)

    existing_acts = existing_outline.get("three_acts") if isinstance(existing_outline.get("three_acts"), list) else []
    incoming_acts = incoming_outline.get("three_acts") if isinstance(incoming_outline.get("three_acts"), list) else []

    merged_acts: list[dict] = []
    act_index: dict[str, int] = {}

    def _push_act(raw_act, fallback_index: int, *, prefer_incoming: bool) -> None:
        if isinstance(raw_act, dict):
            act_entry = dict(raw_act)
        else:
            act_entry = {"title": str(raw_act)}
        act_label = str(act_entry.get("act", fallback_index))
        act_entry["act"] = act_entry.get("act", fallback_index)
        act_entry.pop("chapters", None)
        if act_label in act_index:
            idx = act_index[act_label]
            current = dict(merged_acts[idx])
            update_data = {k: v for k, v in act_entry.items() if v not in (None, "", [], {})}
            if prefer_incoming:
                current.update(update_data)
            else:
                for key, value in update_data.items():
                    current.setdefault(key, value)
            merged_acts[idx] = current
            return
        act_index[act_label] = len(merged_acts)
        merged_acts.append(act_entry)

    for idx, act in enumerate(existing_acts, start=1):
        _push_act(act, idx, prefer_incoming=False)
    for idx, act in enumerate(incoming_acts, start=1):
        _push_act(act, idx, prefer_incoming=True)

    base_outline = dict(existing_outline)
    base_outline.update({k: v for k, v in incoming_outline.items() if k != "three_acts"})
    base_outline["three_acts"] = merged_acts
    return _normalize_framework_outline(base_outline, merged_chapters)


# ── 章节计数 ────────────────────────────────────────────────

def _count_framework_chapters(framework: dict | None) -> int:
    """计算框架中包含的章节总数。"""
    if not isinstance(framework, dict):
        return 0
    chapters = framework.get("chapters")
    if isinstance(chapters, list) and chapters:
        return len([item for item in chapters if isinstance(item, dict)])
    return len(_extract_outline_chapters(framework.get("outline")))


# ── Big Five 分数规范化 ─────────────────────────────────────

def _normalize_big_five_scores(raw):
    """将大五人格分数归一化到 0-100。"""
    if not isinstance(raw, dict):
        return raw
    key_map = {
        "O": "O", "C": "C", "E": "E", "A": "A", "N": "N",
        "openness": "O", "conscientiousness": "C",
        "extraversion": "E", "agreeableness": "A", "neuroticism": "N",
    }
    normalized = {}
    for key, value in raw.items():
        target = key_map.get(str(key))
        if not target:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric <= 10:
            numeric *= 10
        normalized[target] = max(0, min(100, int(round(numeric))))
    return normalized or raw


def _normalize_characters_payload(raw):
    """规范化角色列表，处理 big_five 字段。"""
    if not isinstance(raw, list):
        return raw
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        character = dict(item)
        if "big_five" in character:
            character["big_five"] = _normalize_big_five_scores(character.get("big_five"))
        normalized.append(character)
    return normalized


# ═══════════════════════════════════════════════════════════════
# Operation/Patch 白名单与校验 (框架调整结构化编辑)
# ═══════════════════════════════════════════════════════════════

SUPPORTED_FRAMEWORK_OPERATIONS = {
    "update_story_description",
    "update_tags",
    "add_character",
    "update_character",
    "remove_character",
    "update_act_summary",
    "add_act",
    "delete_act",
    "add_chapter",
    "insert_chapter_after",
    "move_chapter_to_act",
    "update_chapter",
    "delete_chapter",
    "replace_outline",
    "replace_tags",
    "replace_characters",
    "replace_act_chapters",
}

SUPPORTED_FRAMEWORK_PATCH_PATHS = {
    "description",
    "tags.type",
    "tags.theme",
    "tags.style",
    "tags.audience",
    "outline.serial_strategy",
    "outline.themes",
    "outline.foreshadowing",
    "outline.three_acts",
}


def _is_valid_patch_path(path: str) -> bool:
    """检查 patch path 是否在白名单或允许的子路径中。"""
    if path in SUPPORTED_FRAMEWORK_PATCH_PATHS:
        return True
    # outline.three_acts 允许子路径，如 outline.three_acts[0].chapters
    if path.startswith("outline.three_acts["):
        return True
    return False


def validate_framework_operations(operations: list | None, patches: list | None) -> list[str]:
    """校验 operation/patch 白名单，返回错误列表。"""
    errors: list[str] = []
    for index, item in enumerate(operations or []):
        # 跳过非字典类型的元素（AI 可能返回字符串）
        if not isinstance(item, dict):
            errors.append(f"operations[{index}] 格式无效: 期望字典，得到 {type(item).__name__}")
            continue
        op = str(item.get("op") or "").strip()
        if op not in SUPPORTED_FRAMEWORK_OPERATIONS:
            errors.append(f"operations[{index}].op 不支持: {op or '<empty>'}")
    for index, item in enumerate(patches or []):
        # 跳过非字典类型的元素（AI 可能返回字符串）
        if not isinstance(item, dict):
            errors.append(f"patches[{index}] 格式无效: 期望字典，得到 {type(item).__name__}")
            continue
        path = str(item.get("path") or "").strip()
        if not _is_valid_patch_path(path):
            errors.append(f"patches[{index}].path 不支持: {path or '<empty>'}")
    return errors


def _apply_framework_patch(framework: dict, path: str, value):
    """对框架的指定路径应用 patch 值。"""
    if path == "description":
        framework["description"] = str(value or "").strip()
        return
    if path.startswith("tags."):
        framework.setdefault("tags", {})[path.split(".", 1)[1]] = value
        return
    if path == "outline.themes":
        framework.setdefault("outline", {})["themes"] = value if isinstance(value, list) else []
        return
    if path == "outline.foreshadowing":
        framework.setdefault("outline", {})["foreshadowing"] = value if isinstance(value, list) else []
        return
    if path == "outline.serial_strategy":
        framework.setdefault("outline", {})["serial_strategy"] = value if isinstance(value, dict) else {}
        return
    if path == "outline.three_acts":
        if not isinstance(value, list):
            return
        new_acts = []
        for act_idx, act in enumerate(value, start=1):
            if not isinstance(act, dict):
                continue
            act_entry = {
                "act": act.get("act", act_idx),
                "title": str(act.get("title") or "").strip(),
                "summary": str(act.get("summary") or "").strip(),
            }
            if "name" in act:
                act_entry["name"] = str(act.get("name") or "").strip()
            chapters = []
            for ch in act.get("chapters", []):
                if not isinstance(ch, dict):
                    continue
                cn = _coerce_chapter_number(ch.get("chapter_number"))
                title = str(ch.get("title") or "").strip()
                if cn is None or not title:
                    continue
                chapter_entry = {"chapter_number": cn, "title": title, "act": str(act_entry["act"])}
                chapter_entry.update(_normalize_chapter_plan_meta(ch))
                chapters.append(chapter_entry)
            act_entry["chapters"] = sorted(chapters, key=lambda x: x["chapter_number"])
            new_acts.append(act_entry)
        framework.setdefault("outline", {})["three_acts"] = new_acts
        return

    # 支持 outline.three_acts[i].chapters / chapter_count 子路径（分配章节到指定幕）
    import re as _re
    m = _re.match(r'^outline\.three_acts\[(\d+)\]\.(.+)$', path)
    if m:
        act_idx = int(m.group(1))
        field = m.group(2)
        acts = framework.setdefault("outline", {}).setdefault("three_acts", [])
        while len(acts) <= act_idx:
            acts.append({"act": str(len(acts) + 1), "title": "", "summary": "", "chapters": []})
        if field == "chapters":
            if not isinstance(value, list):
                return
            chapters = []
            for ch in value:
                if not isinstance(ch, dict):
                    continue
                cn = _coerce_chapter_number(ch.get("chapter_number"))
                title = str(ch.get("title") or "").strip()
                if cn is None or not title:
                    continue
                chapter_entry = {"chapter_number": cn, "title": title, "act": str(act_idx + 1)}
                chapter_entry.update(_normalize_chapter_plan_meta(ch))
                chapters.append(chapter_entry)
            acts[act_idx]["chapters"] = sorted(chapters, key=lambda x: x["chapter_number"])
        # chapter_count 信息性字段，不改变实际数据
        return


def apply_framework_operations(existing_framework: dict, operations: list | None, patches: list | None) -> dict:
    """对现有框架执行 operations/patches，返回应用后的框架和操作记录。"""
    framework = {
        "description": str(existing_framework.get("description") or "").strip(),
        "tags": dict(existing_framework.get("tags") or {}),
        "characters": [dict(item) for item in (existing_framework.get("characters") or []) if isinstance(item, dict)],
        "outline": dict(existing_framework.get("outline") or {}),
    }
    applied_operations: list[str] = []
    warnings: list[str] = []
    errors = validate_framework_operations(operations, patches)
    if errors:
        return {
            "framework": framework,
            "applied_operations": applied_operations,
            "warnings": warnings,
            "errors": errors,
        }

    for item in operations or []:
        op = item.get("op")
        changes = item.get("changes") or {}

        # ── update_story_description ─────────────────────────
        if op == "update_story_description":
            if "description" in changes:
                framework["description"] = str(changes["description"] or "").strip()
                applied_operations.append("update_story_description")
            else:
                warnings.append("update_story_description 缺少 changes.description")

        # ── update_tags ──────────────────────────────────────
        if op == "update_tags":
            for key in ("type", "theme", "style", "audience"):
                if key in changes:
                    framework["tags"][key] = changes[key]
            applied_operations.append("update_tags")

        # ── add_character ────────────────────────────────────
        if op == "add_character":
            name = str((changes.get("name") or "")).strip()
            if name:
                framework["characters"].append(changes)
                applied_operations.append(f"add_character:{name}")
            else:
                warnings.append("add_character 缺少 changes.name")

        # ── remove_character ─────────────────────────────────
        if op == "remove_character":
            target_name = str(((item.get("target") or {}).get("name") or "")).strip()
            original_len = len(framework["characters"])
            framework["characters"] = [
                c for c in framework["characters"]
                if str(c.get("name") or "").strip() != target_name
            ]
            if len(framework["characters"]) < original_len:
                applied_operations.append(f"remove_character:{target_name}")
            else:
                warnings.append(f"未找到角色: {target_name}")

        # ── update_act_summary ───────────────────────────────
        if op == "update_act_summary":
            act_id = str(((item.get("target") or {}).get("act") or "")).strip()
            summary = changes.get("summary")
            matched = False
            for act_item in framework["outline"].get("three_acts", []):
                if str(act_item.get("act") or "").strip() == act_id:
                    act_item["summary"] = summary
                    applied_operations.append(f"update_act_summary:{act_id}")
                    matched = True
                    break
            if not matched:
                warnings.append(f"未找到幕: {act_id}")

        # ── add_act ───────────────────────────────────────────
        if op == "add_act":
            title = str(changes.get("title") or "").strip()
            summary = str(changes.get("summary") or "").strip()
            after_act = str(((item.get("target") or {}).get("after_act") or "")).strip()
            acts = framework.setdefault("outline", {}).setdefault("three_acts", [])
            existing_nums = {a.get("act") for a in acts if a.get("act")}
            # 计算下一个全局可用编号，保证不重复
            next_num = max((int(a.get("act", 0)) for a in acts if str(a.get("act", "")).isdigit()), default=0) + 1
            if after_act and after_act in existing_nums:
                insert_idx = next((i for i, a in enumerate(acts) if str(a.get("act")) == after_act), -1)
                if insert_idx >= 0:
                    new_num = str(next_num)
                    new_act = {"act": new_num, "title": title, "summary": summary, "chapters": []}
                    acts.insert(insert_idx + 1, new_act)
                    # 后移后续幕号
                    for i in range(insert_idx + 1, len(acts)):
                        acts[i]["act"] = str(int(acts[i - 1]["act"]) + 1)
                    applied_operations.append(f"add_act:{new_num}")
                else:
                    warnings.append(f"add_act 未找到插入锚点幕: {after_act}")
            else:
                # 追加到末尾
                new_num = str(next_num)
                new_act = {"act": new_num, "title": title, "summary": summary, "chapters": []}
                acts.append(new_act)
                applied_operations.append(f"add_act:{new_num}")

        # ── delete_act ────────────────────────────────────────
        if op == "delete_act":
            target_act = str((item.get("target") or {}).get("act") or "").strip()
            if not target_act:
                warnings.append("delete_act 缺少 target.act")
            else:
                acts = framework.get("outline", {}).get("three_acts", [])
                new_acts = [a for a in acts if str(a.get("act", "")).strip() != target_act]
                if len(new_acts) == len(acts):
                    warnings.append(f"delete_act 未找到 target.act={target_act}")
                else:
                    # 重排剩余幕号
                    for i, a in enumerate(new_acts):
                        a["act"] = str(i + 1)
                    framework["outline"]["three_acts"] = new_acts
                    applied_operations.append(f"delete_act:{target_act}")

        # ── replace_outline ──────────────────────────────────
        if op == "replace_outline":
            next_outline = changes.get("outline") if isinstance(changes, dict) else None
            if isinstance(next_outline, dict):
                framework["outline"] = _normalize_framework_outline(next_outline, _extract_outline_chapters(next_outline))
                applied_operations.append("replace_outline")
            else:
                warnings.append("replace_outline 缺少 changes.outline")
            continue

        # ── replace_tags ─────────────────────────────────────
        if op == "replace_tags":
            next_tags = changes.get("tags") if isinstance(changes, dict) else None
            if isinstance(next_tags, dict):
                framework["tags"] = next_tags
                applied_operations.append("replace_tags")
            else:
                warnings.append("replace_tags 缺少 changes.tags")
            continue

        # ── replace_characters ───────────────────────────────
        if op == "replace_characters":
            next_chars = changes.get("characters") if isinstance(changes, dict) else None
            if isinstance(next_chars, list):
                framework["characters"] = _normalize_characters_payload(next_chars)
                applied_operations.append("replace_characters")
            else:
                warnings.append("replace_characters 缺少 changes.characters")
            continue

        # ── replace_act_chapters ─────────────────────────────
        if op == "replace_act_chapters":
            target_act = (changes.get("target") or {}).get("act") if isinstance(changes, dict) else None
            next_chapters = changes.get("chapters") if isinstance(changes, dict) else None
            if target_act and isinstance(next_chapters, list):
                acts = framework["outline"].get("three_acts") if isinstance(framework["outline"].get("three_acts"), list) else []
                found = False
                for act_item in acts:
                    if isinstance(act_item, dict) and str(act_item.get("act", "")) == str(target_act):
                        act_item["chapters"] = next_chapters
                        found = True
                        break
                if found:
                    framework["outline"]["three_acts"] = acts
                    applied_operations.append(f"replace_act_chapters:{target_act}")
                else:
                    warnings.append(f"replace_act_chapters 未找到 act: {target_act}")
            else:
                warnings.append("replace_act_chapters 缺少 target.act 或 changes.chapters")
            continue

        # ── add_chapter ──────────────────────────────────────
        if op == "add_chapter":
            act_id = str(((item.get("target") or {}).get("act") or "")).strip()
            target_act = None
            for act_item in framework["outline"].get("three_acts", []):
                if str(act_item.get("act") or "").strip() == act_id:
                    target_act = act_item
                    break
            if not target_act and framework["outline"].get("three_acts"):
                target_act = framework["outline"]["three_acts"][0]

            if target_act is not None:
                new_chapter = {k: v for k, v in changes.items() if v not in (None, "")}
                new_chapter["act"] = str(target_act.get("act") or act_id or "").strip()
                cn = _coerce_chapter_number(new_chapter.get("chapter_number"))
                if cn is None:
                    cn = max(
                        (c.get("chapter_number") or 0 for c in target_act.get("chapters", [])),
                        default=0,
                    ) + 1
                    new_chapter["chapter_number"] = cn
                else:
                    # ★ 避免 chapter_number 重复：当指定编号已被占用时后移后续章节
                    chapters = _extract_outline_chapters(framework["outline"])
                    existing_numbers = {ch.get("chapter_number") for ch in chapters if isinstance(ch.get("chapter_number"), int)}
                    if cn in existing_numbers:
                        for ch in chapters:
                            if isinstance(ch.get("chapter_number"), int) and ch["chapter_number"] >= cn:
                                ch["chapter_number"] += 1
                        framework["outline"] = _normalize_framework_outline(framework["outline"], chapters)
                target_act = None
                for act_item in framework["outline"].get("three_acts", []):
                    if str(act_item.get("act") or "").strip() == new_chapter.get("act", act_id):
                        target_act = act_item
                        break
                if target_act is not None:
                    target_act.setdefault("chapters", []).append(new_chapter)
                    target_act["chapters"] = sorted(target_act["chapters"], key=lambda x: x.get("chapter_number", 0))
                applied_operations.append(f"add_chapter:{cn}")
            else:
                warnings.append("add_chapter 未找到可用的幕")

        # ── insert_chapter_after ─────────────────────────────
        if op == "insert_chapter_after":
            target_number = _coerce_chapter_number((item.get("target") or {}).get("chapter_number"))
            new_chapter = {k: v for k, v in changes.items() if v not in (None, "")}
            new_cn = _coerce_chapter_number(new_chapter.get("chapter_number"))
            if new_cn is None and target_number is not None:
                new_cn = target_number + 1
            if new_cn is not None:
                new_chapter["chapter_number"] = new_cn
                target_act_key = None
                target_chapter = None
                for ch in _extract_outline_chapters(framework["outline"]):
                    if ch.get("chapter_number") == target_number:
                        target_chapter = ch
                        target_act_key = ch.get("act")
                        break
                if target_act_key:
                    new_chapter["act"] = target_act_key
                chapters = _extract_outline_chapters(framework["outline"])
                # ★ 避免 chapter_number 重复：仅当 new_cn 已被占用时才后移后续章节
                existing_numbers = {ch.get("chapter_number") for ch in chapters if isinstance(ch.get("chapter_number"), int)}
                if new_cn in existing_numbers:
                    for ch in chapters:
                        if isinstance(ch.get("chapter_number"), int) and ch["chapter_number"] >= new_cn:
                            ch["chapter_number"] += 1
                chapters.append(new_chapter)
                framework["outline"] = _normalize_framework_outline(framework["outline"], chapters)
                applied_operations.append(f"insert_chapter_after:{new_cn}")
            else:
                warnings.append("insert_chapter_after 无法确定新章节编号")

        # ── update_character ─────────────────────────────────
        if op == "update_character":
            target_name = str(((item.get("target") or {}).get("name") or "")).strip()
            for character in framework["characters"]:
                if str(character.get("name") or "").strip() == target_name:
                    character.update({k: v for k, v in (item.get("changes") or {}).items() if v not in (None, "")})
                    applied_operations.append(f"update_character:{target_name}")
                    break
            else:
                warnings.append(f"未找到角色: {target_name}")

        # ── move_chapter_to_act ──────────────────────────────
        if op == "move_chapter_to_act":
            target_number = _coerce_chapter_number((item.get("target") or {}).get("chapter_number"))
            new_act = str(((item.get("target") or {}).get("act") or "")).strip()
            if not new_act:
                warnings.append("move_chapter_to_act 缺少 target.act")
            elif target_number is None:
                warnings.append("move_chapter_to_act 缺少 target.chapter_number")
            else:
                chapters = _extract_outline_chapters(framework["outline"])
                moved = False
                for ch in chapters:
                    if ch.get("chapter_number") == target_number:
                        ch["act"] = new_act
                        moved = True
                        break
                if moved:
                    framework["outline"] = _normalize_framework_outline(framework["outline"], chapters)
                    applied_operations.append(f"move_chapter_to_act:{target_number}")
                else:
                    warnings.append(f"未找到章节: {target_number}")

        # ── update_chapter ───────────────────────────────────
        if op == "update_chapter":
            target_number = _coerce_chapter_number((item.get("target") or {}).get("chapter_number"))
            chapters = _extract_outline_chapters(framework["outline"])
            for chapter in chapters:
                if chapter.get("chapter_number") == target_number:
                    chapter.update({k: v for k, v in (item.get("changes") or {}).items() if v not in (None, "")})
                    framework["outline"] = _normalize_framework_outline(framework["outline"], chapters)
                    applied_operations.append(f"update_chapter:{target_number}")
                    break
            else:
                warnings.append(f"未找到章节: {target_number}")

        # ── delete_chapter ───────────────────────────────────
        if op == "delete_chapter":
            target_number = _coerce_chapter_number((item.get("target") or {}).get("chapter_number"))
            remaining = [ch for ch in _extract_outline_chapters(framework["outline"])
                         if ch.get("chapter_number") != target_number]
            if len(remaining) == len(_extract_outline_chapters(framework["outline"])):
                warnings.append(f"未找到章节: {target_number}")
            else:
                framework["outline"] = _normalize_framework_outline(framework["outline"], remaining)
                applied_operations.append(f"delete_chapter:{target_number}")

    for item in patches or []:
        path = str((item or {}).get("path") or "").strip()
        if path in SUPPORTED_FRAMEWORK_PATCH_PATHS:
            _apply_framework_patch(framework, path, (item or {}).get("value"))
            applied_operations.append(f"patch:{path}")

    return {
        "framework": framework,
        "applied_operations": applied_operations,
        "warnings": warnings,
        "errors": [],
    }


def validate_applied_framework_consistency(framework: dict) -> list[str]:
    """校验应用后的框架一致性：重复 chapter_number、章节结构问题。"""
    errors: list[str] = []

    if not isinstance(framework, dict):
        return ["框架 JSON 必须是对象"]

    outline = framework.get("outline")
    if isinstance(outline, dict):
        three_acts = outline.get("three_acts")
        if isinstance(three_acts, list):
            chapter_numbers: list[int] = []
            for act_idx, act in enumerate(three_acts):
                if not isinstance(act, dict):
                    errors.append(f"three_acts[{act_idx}] 必须是对象")
                    continue
                for ch_idx, ch in enumerate(act.get("chapters", [])):
                    if not isinstance(ch, dict):
                        errors.append(f"three_acts[{act_idx}].chapters[{ch_idx}] 必须是对象")
                        continue
                    cn = ch.get("chapter_number")
                    if not isinstance(cn, int) or cn <= 0:
                        errors.append(f"three_acts[{act_idx}].chapters[{ch_idx}].chapter_number 必须是正整数")
                    else:
                        chapter_numbers.append(cn)
                    if not str(ch.get("title") or "").strip():
                        errors.append(f"three_acts[{act_idx}].chapters[{ch_idx}].title 不能为空")
            if len(chapter_numbers) != len(set(chapter_numbers)):
                errors.append("chapter_number 存在重复")

    return errors


# ═══════════════════════════════════════════════════════════════
# validate_framework_json — 完整的框架 JSON 校验
# ═══════════════════════════════════════════════════════════════

def _extract_chapter_numbers(outline: dict | None) -> set[int]:
    """从 outline.three_acts 中提取所有 chapter_number 的集合。"""
    from_main = _extract_outline_chapters(outline)
    return {ch["chapter_number"] for ch in from_main if isinstance(ch.get("chapter_number"), int)}


def validate_framework_json(
    framework: dict | None,
    *,
    existing_chapter_numbers: set[int] | None = None,
    required_min_chapters: int | None = None,
) -> list[str]:
    """校验 AI 返回的完整框架 JSON 的结构完整性和内容一致性。

    返回错误描述列表，空列表 = 校验通过。
    校验维度：
      1. 顶级结构（description / tags / characters / outline）
      2. tags 各字段
      3. characters 各字段
      4. outline + three_acts 嵌套结构
      5. 每章规划字段完整性
      6. chapter_number 连续性/去重
      7. 数据丢失（现有章节不在输出中）
      8. 最少章节数要求
    """
    errors: list[str] = []

    if not isinstance(framework, dict):
        return ["框架 JSON 必须是对象"]

    # ── 1. 顶级字段 ─────────────────────────────────────────
    required_top = ("description", "tags", "characters", "outline")
    for field in required_top:
        if field not in framework:
            errors.append(f"缺少顶级字段：{field}")

    if errors:
        # 顶级字段都不全，无法继续检查
        return errors

    # ── 1a. description ──────────────────────────────────────
    desc = framework.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("description 必须是非空字符串")

    # ── 1b. tags ─────────────────────────────────────────────
    tags = framework.get("tags")
    if not isinstance(tags, dict):
        errors.append("tags 必须是对象")
    else:
        for key in ("type", "theme", "style", "audience"):
            val = tags.get(key)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"tags.{key} 必须是非空字符串")

    # ── 1c. characters ───────────────────────────────────────
    characters = framework.get("characters")
    if not isinstance(characters, list):
        errors.append("characters 必须是数组")
    elif not characters:
        errors.append("characters 不能为空数组")
    else:
        for idx, char in enumerate(characters):
            if not isinstance(char, dict):
                errors.append(f"characters[{idx}] 必须是对象")
                continue
            for field in ("name", "role"):
                val = char.get(field)
                if not isinstance(val, str) or not val.strip():
                    errors.append(f"characters[{idx}].{field} 必须是非空字符串")
            # big_five 可选校验（支持列表 [O,C,E,A,N] 和字典 {O,C,E,A,N} 两种格式）
            if "big_five" in char:
                bf = char["big_five"]
                if isinstance(bf, list):
                    if len(bf) != 5:
                        errors.append(f"characters[{idx}].big_five 数组长度须为 5（O/C/E/A/N）")
                    else:
                        for bi, bv in enumerate(bf):
                            if not isinstance(bv, (int, float)) or bv < 0 or bv > 100:
                                errors.append(f"characters[{idx}].big_five[{bi}] 值须在 0~100 之间")
                elif isinstance(bf, dict):
                    for dim in ("O", "C", "E", "A", "N"):
                        if dim in bf:
                            val = bf[dim]
                            if not isinstance(val, (int, float)) or val < 0 or val > 100:
                                errors.append(f"characters[{idx}].big_five.{dim} 值须在 0~100 之间")
                else:
                    errors.append(f"characters[{idx}].big_five 必须是数组或对象")

    # ── 1d. outline ──────────────────────────────────────────
    outline = framework.get("outline")
    if not isinstance(outline, dict):
        errors.append("outline 必须是对象")
        return errors

    three_acts = outline.get("three_acts")
    if not isinstance(three_acts, list):
        errors.append("outline.three_acts 必须是数组")
        return errors
    if not three_acts:
        errors.append("outline.three_acts 不能为空数组")
        return errors

    # ── 2. three_acts 内的章节校验 ──────────────────────────
    all_numbers_raw: list[int] = []
    seen_numbers: set[int] = set()

    for act_idx, act in enumerate(three_acts):
        if not isinstance(act, dict):
            errors.append(f"three_acts[{act_idx}] 必须是对象")
            continue

        # act 级必填字段
        act_val = act.get("act")
        if not isinstance(act_val, (str, int)) or (isinstance(act_val, str) and not act_val.strip()):
            errors.append(f"three_acts[{act_idx}].act 必须是正整数或非空字符串")
        title_val = act.get("title")
        if not isinstance(title_val, str) or not title_val.strip():
            errors.append(f"three_acts[{act_idx}].title 必须是非空字符串")

        chapters = act.get("chapters")
        if not isinstance(chapters, list):
            errors.append(f"three_acts[{act_idx}].chapters 必须是数组")
            continue

        for ch_idx, chapter in enumerate(chapters):
            if not isinstance(chapter, dict):
                errors.append(f"three_acts[{act_idx}].chapters[{ch_idx}] 必须是对象")
                continue

            # chapter_number: 必须为正整数
            cn = chapter.get("chapter_number")
            if not isinstance(cn, int) or cn < 1:
                errors.append(
                    f"章节规划 #{ch_idx + 1} 的 chapter_number 必须是正整数（>0），"
                    f"当前值: {cn!r}"
                )
            else:
                all_numbers_raw.append(cn)
                if cn in seen_numbers:
                    errors.append(f"章节编号 {cn} 重复出现（请去重或调整编号）")
                seen_numbers.add(cn)

            # title: 必须为非空字符串
            title = chapter.get("title")
            if not isinstance(title, str) or not title.strip():
                errors.append(
                    f"章节 #{cn if isinstance(cn, int) else ch_idx + 1} 的 title 必须是非空字符串"
                )

            # summary / goal / conflict / hook / payoff: 强烈建议非空
            for field in ("summary", "goal", "conflict", "hook", "payoff"):
                val = chapter.get(field)
                if not isinstance(val, str) or not val.strip():
                    label = {"summary": "摘要", "goal": "目标", "conflict": "冲突",
                             "hook": "钩子", "payoff": "回报"}.get(field, field)
                    errors.append(
                        f"章节 #{cn if isinstance(cn, int) else ch_idx + 1} 的 {field}（{label}）"
                        f"必须是非空字符串，请补充具体内容"
                    )

    # ── 3. 章节连续性/去重（已在上面的循环中处理重复） ──────
    sorted_numbers = sorted(set(all_numbers_raw))

    if sorted_numbers and sorted_numbers[0] != 1:
        errors.append(f"章节编号应从 1 开始，实际从 {sorted_numbers[0]} 开始")

    # ── 4. 数据丢失检测 ─────────────────────────────────────
    if existing_chapter_numbers:
        output_set = set(sorted_numbers)
        missing = existing_chapter_numbers - output_set
        if missing:
            sorted_missing = sorted(missing)
            errors.append(
                f"输出大纲缺少已有章节规划：{sorted_missing}，"
                f"请重新输出完整章节列表，不要遗漏任何已有的章节"
            )

    # ── 5. 最少章节数 ────────────────────────────────────────
    if required_min_chapters and len(sorted_numbers) < required_min_chapters:
        errors.append(
            f"章节总数 {len(sorted_numbers)} 不满足最少 {required_min_chapters} 章的要求，"
            f"请在 outline.three_acts 中创建或补齐章节"
        )

    return errors


# ── 框架快照 / 回滚 ──────────────────────────────────


def _save_framework_snapshot(story_id: int, snapshot_data: dict, source: str,
                             reply_summary: str | None, db: Session) -> FrameworkSnapshot:
    """保存一条框架快照。"""
    snap = FrameworkSnapshot(
        story_id=story_id,
        snapshot_data=snapshot_data,
        source=source,
        reply_summary=(reply_summary or "")[:255] if reply_summary else None,
    )
    db.add(snap)
    db.flush()
    return snap


def _enforce_framework_snapshot_limit(story_id: int, max_count: int, db: Session) -> None:
    """保留最近 max_count 条快照，删除更早的记录。"""
    ids_to_keep = (
        db.query(FrameworkSnapshot.id)
        .filter(FrameworkSnapshot.story_id == story_id)
        .order_by(FrameworkSnapshot.created_at.desc())
        .limit(max_count)
        .all()
    )
    if ids_to_keep:
        keep_set = {row[0] for row in ids_to_keep}
        db.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story_id,
            ~FrameworkSnapshot.id.in_(keep_set),
        ).delete(synchronize_session="fetch")


def _build_current_snapshot_data(story) -> dict:
    """从 Story 对象提取当前框架状态作为快照数据。"""
    return {
        "description": story.description or "",
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }


def _cleanup_chapters_beyond_outline(story, db: Session) -> None:
    """删除超出恢复后大纲范围的孤立 Chapter 记录及其磁盘文件。

    回退框架快照后，大纲中的章节数可能少于数据库中已创建的 Chapter 记录数。
    如果不清理这些孤立记录，后续框架调整/续写会出现章节编号断层。
    """
    outline = story.outline if isinstance(story.outline, dict) else {}
    chapters_in_outline = _extract_outline_chapters(outline)
    if not chapters_in_outline:
        return

    max_outline_number = max(
        (ch.get("chapter_number") for ch in chapters_in_outline if isinstance(ch.get("chapter_number"), int)),
        default=0,
    )
    if max_outline_number <= 0:
        return

    # 查找超出大纲范围的 Chapter 记录
    orphaned = (
        db.query(Chapter)
        .filter(Chapter.story_id == story.id, Chapter.chapter_number > max_outline_number)
        .all()
    )
    if not orphaned:
        return

    logger.info(
        "快照回滚清理：故事 #%d 恢复大纲至第 %d 章，删除 %d 个孤立章节记录（#%s ~ #%s）",
        story.id,
        max_outline_number,
        len(orphaned),
        min(c.chapter_number for c in orphaned),
        max(c.chapter_number for c in orphaned),
    )

    base_dir = Path(__file__).resolve().parent.parent / "manga_outputs"
    for ch in orphaned:
        # 删除章节磁盘目录
        chapter_dir = base_dir / f"chapter_{ch.id}"
        if chapter_dir.exists():
            try:
                shutil.rmtree(chapter_dir)
            except OSError as exc:
                logger.warning("清理孤立章节目录失败 chapter_%d: %s", ch.id, exc)
        # 删除章节记录（images/messages/script_scenes 通过 cascade 自动删除）
        db.delete(ch)


def restore_framework_snapshot(story, snapshot_id: int, db: Session) -> dict:
    """将故事框架恢复到指定快照的状态。

    回滚前自动保存当前状态为快照（source='auto_before_restore'）。
    返回恢复后的 snapshot_data。
    """
    snap = db.query(FrameworkSnapshot).filter(
        FrameworkSnapshot.id == snapshot_id,
        FrameworkSnapshot.story_id == story.id,
    ).first()
    if not snap:
        raise ValueError("快照不存在或不属于当前故事")

    # 自动保存当前状态
    current_data = _build_current_snapshot_data(story)
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data=current_data,
        source="auto_before_restore",
        reply_summary=f"回滚前自动保存（目标快照 #{snapshot_id}）",
        db=db,
    )

    # 恢复快照
    data = snap.snapshot_data
    story.description = str(data.get("description") or "").strip()
    story.tags = data.get("tags") if isinstance(data.get("tags"), dict) else story.tags
    story.characters = _normalize_characters_payload(data.get("characters"))
    story.outline = data.get("outline") if isinstance(data.get("outline"), dict) else story.outline
    db.flush()

    # 清理超出恢复后大纲范围的孤立 Chapter 记录
    _cleanup_chapters_beyond_outline(story, db)

    _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

    return _build_current_snapshot_data(story)


def _build_outline_compact(outline: dict | None, recent_chapter_limit: int = 12) -> dict:
    """生成大纲精简版（含每幕摘要、最近章节卡片），供 AI 上下文使用。"""
    if not isinstance(outline, dict):
        return {}

    acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
    compact_acts: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if not isinstance(act, dict):
            continue
        compact_acts.append({
            "act": act.get("act", index),
            "title": str(act.get("title") or act.get("name") or "").strip(),
            "summary": str(act.get("summary") or "").strip(),
            "chapter_count": len([item for item in (act.get("chapters") or []) if isinstance(item, dict)]),
        })

    all_chapters = _extract_outline_chapters(outline)
    recent_chapters = sorted(all_chapters, key=lambda item: item["chapter_number"])[-recent_chapter_limit:]
    recent_cards: list[dict] = []
    for chapter in recent_chapters:
        card = {
            "chapter_number": chapter.get("chapter_number"),
            "title": chapter.get("title"),
            "act": chapter.get("act"),
        }
        for key in ("summary", "goal", "conflict", "hook", "payoff", "highlight"):
            value = str(chapter.get(key) or "").strip()
            if value:
                card[key] = value
        key_events = chapter.get("key_events")
        if isinstance(key_events, list):
            cleaned = [str(item).strip() for item in key_events if str(item).strip()]
            if cleaned:
                card["key_events"] = cleaned[:6]
        recent_cards.append(card)

    compact: dict = {
        "stage_count": len(compact_acts),
        "chapter_count": len(all_chapters),
        "acts": compact_acts,
        "recent_chapter_cards": recent_cards,
    }
    serial_strategy = outline.get("serial_strategy")
    if isinstance(serial_strategy, dict) and serial_strategy:
        compact["serial_strategy"] = serial_strategy
    themes = outline.get("themes")
    if isinstance(themes, list) and themes:
        compact["themes"] = [str(item).strip() for item in themes if str(item).strip()][:8]
    foreshadowing = outline.get("foreshadowing")
    if isinstance(foreshadowing, list) and foreshadowing:
        compact["foreshadowing"] = [str(item).strip() for item in foreshadowing if str(item).strip()][:8]
    return compact
