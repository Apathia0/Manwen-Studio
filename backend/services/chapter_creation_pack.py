from __future__ import annotations

import hashlib
import json
from typing import Any


SECTION_LABELS = {
    "story_meta": "作品信息",
    "chapter_plan": "章节规划",
    "story_memory": "故事记忆",
    "previous_chapter": "上一章强制衔接",
    "recent_chapters": "前文章节",
    "user_instruction": "用户要求",
    "characters": "人物设定",
    "entities": "本章相关人物与对象",
    "facts": "本章有效事实",
    "open_threads": "伏笔与剧情推进",
    "style_profile": "写作参考与规则",
}

FIELD_LABELS = {
    "name": "姓名",
    "role": "身份",
    "type": "类型",
    "title": "标题",
    "summary": "摘要",
    "goal": "本章目标",
    "conflict": "核心冲突",
    "payoff": "剧情回报",
    "hook": "章末钩子",
    "highlight": "章节亮点",
    "chapter_number": "章节",
    "key_events": "关键事件",
    "aliases": "别名",
    "profile": "人物信息",
    "entity_type": "对象类型",
    "relevance_score": "本章相关度",
    "subject_key": "主体",
    "predicate": "事实类型",
    "object_key": "关联对象",
    "value": "内容",
    "value_text": "内容",
    "description": "说明",
    "status": "状态",
    "priority": "优先级",
    "urgency": "推进状态",
    "setup_chapter": "埋设章节",
    "expected_payoff_from": "预计回收起始章",
    "expected_payoff_to": "预计回收截止章",
    "current": "本章任务",
    "previous": "上一章承接",
    "next": "下一章边界",
    "content": "内容",
    "content_text": "内容",
    "ending_scene": "结尾场景",
    "ending_excerpt": "正文结尾原文",
    "chapter_handoff": "章节交接要求",
    "opening_must_continue": "开头必须承接",
    "active_conflict": "未结束冲突",
    "active_characters": "在场人物",
    "ending_location": "结尾地点",
}

VALUE_LABELS = {
    "acquired": "获得",
    "ally": "同盟",
    "archived": "已归档",
    "character": "人物",
    "completed": "已完成",
    "consumed": "消耗",
    "continuity": "连续性",
    "location": "地点",
    "faction": "势力",
    "item": "物品",
    "concept": "概念",
    "world_concept": "世界概念",
    "world_rule": "世界规则",
    "protagonist": "主角",
    "supporting": "配角",
    "antagonist": "对手",
    "belongs_to": "归属",
    "enemy": "敌对",
    "equipped": "装备",
    "foreshadow": "伏笔",
    "has_money": "持有资金",
    "identity": "身份",
    "improved": "提升",
    "informed": "获知",
    "learned_from": "学自",
    "located_at": "位于",
    "note": "备注",
    "owns": "持有",
    "parent_child": "亲子",
    "possesses": "持有",
    "purchased_from": "购自",
    "relationship": "人物关系",
    "sold_to": "出售给",
    "status": "状态",
    "traded_with": "交易对象",
    "world_story": "世界剧情",
    "due": "本章处理",
    "overdue": "已经逾期",
    "approaching": "临近回收",
    "background": "暂不推进",
    "active": "生效中",
    "resolved": "已完成",
    "open": "待推进",
    "inactive": "未启用",
    "pending": "待处理",
    "cancelled": "已取消",
}

CREATION_PACK_RENDER_VERSION = 7

AI_SECTION_LABELS = {
    "chapter_task": "本章任务",
    "plot_beats": "剧情推进",
    "foreshadowing": "伏笔管理",
    "characters": "人物动机与状态",
    "scenes": "场景设定",
    "continuity": "连续性约束",
    "writing_guide": "写作要点",
}

AI_FIELD_LABELS = {
    "goal": "本章目标",
    "conflict": "核心冲突",
    "payoff": "剧情回报",
    "ending_hook": "章末钩子",
    "order": "顺序",
    "type": "节拍类型",
    "summary": "节拍概述",
    "characters": "出场人物",
    "key_actions": "关键动作",
    "dialogue_hints": "对话要点",
    "title": "伏笔标题",
    "status": "状态",
    "action": "处理方式",
    "note": "安排说明",
    "name": "人物",
    "motivation": "本章动机",
    "current_state": "当前状态",
    "arc": "本章变化",
    "location": "地点",
    "atmosphere": "氛围",
    "key_details": "关键细节",
    "must_keep": "必须保持",
    "avoid": "禁止破坏",
    "boundary_notes": "本章边界",
    "dialogue": "对话要求",
    "emotion": "情绪展示",
    "style": "风格参考",
    "quality_rules": "质量规则",
}

AI_VALUE_LABELS = {
    "due": "已到期",
    "overdue": "已经逾期",
    "approaching": "临近回收",
    "background": "暂不推进",
    "new": "新埋设",
}

HIDDEN_FIELDS = {
    "key",
    "subject",
    "object",
    "subject_key",
    "object_key",
    "source_type",
    "source_id",
    "source_chapter_id",
    "version",
    "relevance_score",
    "_receipt_key",
    "related_entities",
    "payoff_window",
    "big_five",
    "dimensions",
    "scores",
    "metrics",
}

FIELD_LABELS.update({
    "act": "故事阶段",
    "writing_guidance": "写作指导",
    "subject_name": "主体",
    "object_name": "关联对象",
    "valid_from": "生效章节",
    "valid_to": "失效章节",
    "related_entity_names": "关联人物与地点",
    "expected_payoff_from": "预计回收起始章",
    "expected_payoff_to": "预计回收截止章",
    "identity": "身份",
    "personality": "性格",
    "motivation": "当前动机",
    "ability": "能力",
    "appearance": "外貌特征",
    "current_state": "当前状态",
    "relationships": "本章关系",
    "to": "关系对象",
    "target": "关系对象",
    "relation": "关系",
    "realm": "当前境界",
    "occupation": "职业",
    "faction": "所属势力",
    "location": "当前位置",
    "weakness": "弱点与限制",
})


def creation_pack_source_hash(context_pack: dict[str, Any]) -> str:
    """计算自动创作包的数据来源哈希。"""
    source = {
        "render_version": CREATION_PACK_RENDER_VERSION,
        "story_id": context_pack.get("story_id"),
        "chapter_number": context_pack.get("chapter_number"),
        "chapter_title": context_pack.get("chapter_title"),
        "sections": context_pack.get("sections") if isinstance(context_pack.get("sections"), dict) else {},
    }
    raw = json.dumps(source, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def render_creation_pack(context_pack: dict[str, Any]) -> str:
    """把检索结果确定性渲染成用户与正文 Agent 共用的完整创作包。"""
    chapter_number = int(context_pack.get("chapter_number") or 1)
    chapter_title = str(context_pack.get("chapter_title") or "").strip()
    heading = f"# 第{chapter_number}章创作包"
    if chapter_title:
        heading += f"：{chapter_title}"

    lines = [
        heading,
        "",
        "> 以下内容是本章正文 Agent 实际接收的完整创作包。页面保存后的文本会原样发送，不再压缩、裁剪或二次重组。",
    ]
    sections = context_pack.get("sections") if isinstance(context_pack.get("sections"), dict) else {}
    for key, value in sections.items():
        if value in (None, "", [], {}):
            continue
        lines.extend(("", f"## {SECTION_LABELS.get(str(key), str(key))}", "", _render_value(value)))
    return "\n".join(lines).strip()


def canonical_agent_pack(content: str, chapter_info: dict[str, Any]) -> dict[str, Any]:
    """创建运行时包装；正文 Agent 只读取其中未改写的原文。"""
    return {
        "schema_version": 2,
        "canonical_content": str(content or ""),
        "chapter_task": dict(chapter_info or {}),
    }


def canonical_pack_content(pack: dict[str, Any] | None) -> str | None:
    if not isinstance(pack, dict):
        return None
    content = pack.get("canonical_content")
    return str(content) if isinstance(content, str) and content.strip() else None


def _render_value(value: Any, depth: int = 0) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in HIDDEN_FIELDS or item in (None, "", [], {}):
                continue
            label = FIELD_LABELS.get(normalized_key, str(key).replace("_", " "))
            if isinstance(item, (dict, list)):
                nested = _render_value(item, depth + 1)
                if nested:
                    parts.append(f"{'  ' * depth}- {label}：\n{nested}")
            else:
                parts.append(f"{'  ' * depth}- {label}：{_scalar_text(item)}")
        return "\n".join(parts)
    if isinstance(value, list):
        parts = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, (dict, list)):
                nested = _render_value(item, depth + 1)
                if nested:
                    parts.append(f"{'  ' * depth}{index}.\n{nested}")
            else:
                parts.append(f"{'  ' * depth}{index}. {_scalar_text(item)}")
        return "\n".join(parts)
    return _scalar_text(value)


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value)
    return VALUE_LABELS.get(text.lower(), text)


def render_ai_creation_pack(brief: dict[str, Any], context_pack: dict[str, Any]) -> str:
    """把 AI 生成的创作说明 JSON 确定性渲染成 markdown。

    保持与 render_creation_pack 相同的排版契约（# 标题 / ## 分区 / - 字段 / 1. 编号），
    使消费端（正文 Agent 全文注入、前端 parseCreationPack 正则解析）零改动。
    """
    chapter_number = int(context_pack.get("chapter_number") or brief.get("chapter_number") or 1)
    chapter_title = str(context_pack.get("chapter_title") or "").strip()
    heading = f"# 第{chapter_number}章创作包"
    if chapter_title:
        heading += f"：{chapter_title}"

    lines = [
        heading,
        "",
        "> 以下内容是 AI 从知识库检索后生成的本章正文创作说明。页面保存后的文本会原样发送，不再压缩、裁剪或二次重组。",
    ]

    def _field_label(key: str) -> str:
        normalized = str(key).strip().lower()
        return AI_FIELD_LABELS.get(normalized, str(key).replace("_", " "))

    def _value_label(value: Any) -> str:
        text = str(value)
        return AI_VALUE_LABELS.get(text.lower(), text)

    def _render_item(item: Any, depth: int) -> str:
        if isinstance(item, dict):
            parts: list[str] = []
            for key, value in item.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in HIDDEN_FIELDS or value in (None, "", [], {}):
                    continue
                label = _field_label(key)
                if normalized_key == "order":
                    continue
                if isinstance(value, list):
                    nested = _render_item(value, depth + 1)
                    if nested:
                        parts.append(f"{'  ' * depth}- {label}：\n{nested}")
                elif isinstance(value, dict):
                    nested = _render_item(value, depth + 1)
                    if nested:
                        parts.append(f"{'  ' * depth}- {label}：\n{nested}")
                else:
                    parts.append(f"{'  ' * depth}- {label}：{_value_label(value)}")
            return "\n".join(parts)
        if isinstance(item, list):
            parts = []
            for index, entry in enumerate(item, start=1):
                if isinstance(entry, (dict, list)):
                    nested = _render_item(entry, depth + 1)
                    if nested:
                        parts.append(f"{'  ' * depth}{index}.\n{nested}")
                else:
                    text = _value_label(entry)
                    if text:
                        parts.append(f"{'  ' * depth}{index}. {text}")
            return "\n".join(parts)
        return _value_label(item)

    ordered_sections = ["chapter_task", "plot_beats", "foreshadowing", "characters", "scenes", "continuity", "writing_guide"]
    for key in ordered_sections:
        value = brief.get(key)
        if value in (None, "", [], {}):
            continue
        rendered = _render_item(value, 0)
        if not rendered:
            continue
        lines.extend(("", f"## {AI_SECTION_LABELS.get(str(key), str(key))}", "", rendered))
    sections_raw = context_pack.get("sections")
    sections = sections_raw if isinstance(sections_raw, dict) else {}
    prev = sections.get("previous_chapter")
    prev_handoff = {}
    if isinstance(prev, dict):
        raw_handoff = prev.get("chapter_handoff")
        if isinstance(raw_handoff, dict):
            prev_handoff = raw_handoff
    bridge_lines = []
    for key, label in (
        ("opening_must_continue", "上一章必须承接"),
        ("ending_location", "当前开场位置"),
        ("active_conflict", "即时冲突"),
    ):
        value = str(prev_handoff.get(key) or "").strip()
        if value:
            bridge_lines.append(f"- {label}：{value}")
    if bridge_lines:
        lines.extend(("", f"## {SECTION_LABELS['previous_chapter']}", "", "\n".join(bridge_lines)))
    return "\n".join(lines).strip()
