"""
写作参考文件工具模块。

从 backend/references/writing/ 读取写作方法论文件，提供统一的读取接口。
所有参考文件的修改只需改 .md 文件，代码自动同步。

用法:
    from services.writing_utils import (
        get_banned_words, get_banned_patterns,
        get_writing_craft, get_anti_ai_guide,
        get_quality_checklist, get_chapter_writing_methodology,
    )
"""

import os
import re

# ── 参考文件目录 ──────────────────────────────────────────

_WRITING_DIR = os.path.join(os.path.dirname(__file__), "..", "references", "writing")


def _read_ref(filename: str) -> str:
    """读取参考文件内容，文件不存在时返回空字符串。"""
    filepath = os.path.join(_WRITING_DIR, filename)
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ── 缓存 ──────────────────────────────────────────────────

_banned_words_cache: list[str] | None = None
_banned_patterns_cache: list[dict] | None = None
_writing_craft_cache: str | None = None
_anti_ai_guide_cache: str | None = None
_quality_checklist_cache: str | None = None
_methodology_cache: str | None = None


# ── 禁用词解析 ────────────────────────────────────────────

def get_banned_words() -> list[str]:
    """从 banned-words.md 解析 AI 高频禁用词表。

    返回格式: ["眼中闪过一丝", "深吸一口气", "嘴角勾起一抹", ...]
    """
    global _banned_words_cache
    if _banned_words_cache is not None:
        return _banned_words_cache

    content = _read_ref("banned-words.md")
    words: list[str] = []

    # 解析一级禁用词区域（情态类/动作类/表情类/心理类/判断类/形容类/过渡类）
    # 格式: "仿佛、犹如、宛若、如同、一丝、一抹、些许、几分、隐约"
    in_banned_section = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## 一级禁用词"):
            in_banned_section = True
            continue
        if stripped.startswith("## 二级禁用词") or stripped.startswith("## 禁用句式"):
            in_banned_section = False
            continue
        if in_banned_section and "、" in stripped and not stripped.startswith("#"):
            # 提取中文词（2字以上）
            for word in re.findall(r"[\u4e00-\u9fff]{2,}", stripped):
                words.append(word)

    # 解析最毒禁用句式（第12-29行表格 + 禁用句式模板表格）
    # 格式: | "眼中闪过一丝……" / "嘴角勾起一抹……" | "..."
    # 格式: | "不是A，而是B" | "他不是冷漠，而是绝望" | 最毒；直接写 B |
    pattern_tables = [
        r"\|\s*★+\s*\|\s*「([^」]+)」",
        r"\|\s*★+\s*\|\s*\"([^\"]+)\"",
        r'\|\s*★+\s*\|\s*"([^"]+)"',
    ]
    for pat in pattern_tables:
        for m in re.finditer(pat, content):
            phrase = m.group(1).strip()
            if phrase and phrase not in words:
                words.append(phrase)

    # 解析禁用句式模板表格中的完整句式
    # 格式: | "眼中闪过一丝XX" | "眼中闪过一丝悲伤" | 模板化 |
    for m in re.finditer(r'\|\s*"([^"]+)"\s*\|\s*"[^"]*"\s*\|\s*(?:模板化|AI|最毒)', content):
        phrase = m.group(1).strip()
        if "XX" in phrase:
            phrase = phrase.replace("XX", "").replace("xx", "").strip()
        if phrase and phrase not in words:
            words.append(phrase)

    # 添加升华句式
    for m in re.finditer(r"- \"([^\"]+)\"", content):
        phrase = m.group(1).strip()
        if phrase and phrase not in words:
            words.append(phrase)

    _banned_words_cache = list(set(words))
    return _banned_words_cache


def get_banned_patterns() -> list[dict]:
    """从 banned-words.md 解析禁用句式模式（用于 check_ai_flavor 的 pattern_checks）。

    返回格式: [{"name": "先否定再肯定翻转", "patterns": ["不是……而是", "并非……而是"]}, ...]
    """
    global _banned_patterns_cache
    if _banned_patterns_cache is not None:
        return _banned_patterns_cache

    content = _read_ref("banned-words.md")
    patterns: list[dict] = []

    # 最毒禁用句式
    top_patterns = {
        "先否定再肯定翻转": [],
        "万能状语'……，带着……'": [],
        "AI 惯用声音描写": [],
        "仿佛/犹如/宛若 比喻": [],
        "眼中闪过一丝/嘴角勾起一抹": [],
        "心中涌起一股/心头一震": [],
        "章末预告": [],
    }

    for line in content.split("\n"):
        stripped = line.strip()
        if "不是A，（而）是B" in stripped or '"不是A，而是B"' in stripped:
            top_patterns["先否定再肯定翻转"].extend(["不是……而是", "并非……而是", "不是……只是"])
        elif "，带着……" in stripped or '"，带着"' in stripped:
            top_patterns["万能状语'……，带着……'"].append("，带着")
        elif "声音不大" in stripped:
            top_patterns["AI 惯用声音描写"].extend(["声音不大", "声音很低", "声音很轻"])
        elif "仿佛/犹如/宛若" in stripped or "仿佛能" in stripped:
            top_patterns["仿佛/犹如/宛若 比喻"].extend(["仿佛", "犹如", "宛若", "如同"])
        elif "眼中闪过一丝" in stripped or "嘴角勾起一抹" in stripped:
            top_patterns["眼中闪过一丝/嘴角勾起一抹"].extend(["眼中闪过一丝", "嘴角勾起一抹"])
        elif "心中涌起一股" in stripped or "心头一震" in stripped:
            top_patterns["心中涌起一股/心头一震"].extend(["心中涌起一股", "心头一震"])
        elif "他不知道的是" in stripped:
            top_patterns["章末预告"].append("他不知道的是")

    # 升华句式
    closing_patterns = []
    for m in re.finditer(r'- "([^"]+)"', content):
        phrase = m.group(1).strip()
        if any(kw in phrase for kw in ["这一刻", "他知道", "她明白", "这就是"]):
            closing_patterns.append(phrase)
    if closing_patterns:
        top_patterns["章末总结升华"] = closing_patterns

    for name, pats in top_patterns.items():
        if pats:
            patterns.append({"name": name, "patterns": list(set(pats))})

    _banned_patterns_cache = patterns
    return _banned_patterns_cache


# ── 全文读取 ──────────────────────────────────────────────

def get_writing_craft() -> str:
    """获取写作技法全文（writing-craft.md）。"""
    global _writing_craft_cache
    if _writing_craft_cache is None:
        _writing_craft_cache = _read_ref("writing-craft.md")
    return _writing_craft_cache


def get_anti_ai_guide() -> str:
    """获取去AI味完整指南全文（anti-ai-writing.md）。"""
    global _anti_ai_guide_cache
    if _anti_ai_guide_cache is None:
        _anti_ai_guide_cache = _read_ref("anti-ai-writing.md")
    return _anti_ai_guide_cache


def get_quality_checklist() -> str:
    """获取质量检查清单全文（quality-checklist.md）。"""
    global _quality_checklist_cache
    if _quality_checklist_cache is None:
        _quality_checklist_cache = _read_ref("quality-checklist.md")
    return _quality_checklist_cache


# ── 章节写作方法论（精简版，用于 System Prompt 注入）───────

def get_chapter_writing_methodology() -> str:
    """从参考文件提取章节写作方法论精简版，用于注入 System Prompt。

    修改 writing-craft.md 和 anti-ai-writing.md 后，此函数自动同步。
    """
    global _methodology_cache
    if _methodology_cache is not None:
        return _methodology_cache

    craft = get_writing_craft()
    anti_ai = get_anti_ai_guide()

    parts: list[str] = []

    # 从 writing-craft.md 提取关键技法（精确节标题匹配）
    def add_section(source: str, start: str, end: str, title: str) -> None:
        text = _extract_between(source, start, end)
        if text:
            parts.append(f"### {title}\n{text}")

    parts.append("## 写作技法（来自 writing-craft.md）")
    add_section(craft, "## 1. 身体细节替代情绪词", "## 2. 贯穿道具系统", "身体细节替代情绪词")
    add_section(craft, "## 5. 一动一静节奏", "## 6.", "一动一静节奏控制")

    parts.append("## 去AI味规则（来自 anti-ai-writing.md）")
    add_section(anti_ai, "## AI写作指纹（必须避免）", "## 核心规则", "AI写作指纹（必须避免）")
    add_section(anti_ai, "## Show Don't Tell 原则", "## 质量维度检查", "Show Don't Tell 原则")
    add_section(anti_ai, "## 系统性去AI三遍法", "## 去AI味补充技法", "系统性去AI三遍法")

    _methodology_cache = "\n\n".join(parts) if parts else ""
    return _methodology_cache


def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
    """从文本中提取两个标记之间的内容（不含标记行本身）。"""
    start_idx = text.find(start_marker)
    if start_idx == -1:
        return ""
    content_start = text.find("\n", start_idx) + 1
    end_idx = text.find(end_marker, content_start)
    if end_idx == -1:
        return text[content_start:].strip()
    return text[content_start:end_idx].strip()


# ── 章节生成 Prompt 构建 ──────────────────────────────────

# PlatformSetting 键名 → 文件回退映射
_METHODOLOGY_KEYS = {
    "writing_craft": "methodology.writing_craft",
    "anti_ai_writing": "methodology.anti_ai_writing",
    "quality_checklist": "methodology.quality_checklist",
    "banned_words": "methodology.banned_words",
}

_METHODOLOGY_FILE_FALLBACK = {
    "writing_craft": get_writing_craft,
    "anti_ai_writing": get_anti_ai_guide,
    "quality_checklist": get_quality_checklist,
    "banned_words": lambda: _read_ref("banned-words.md"),
}


def _read_single_methodology(db, key: str) -> str:
    """从 DB 读取单个方法论组件，兜底到文件。"""
    try:
        from models import PlatformSetting
        setting = db.query(PlatformSetting).filter_by(setting_key=_METHODOLOGY_KEYS[key]).first()
        if setting and setting.value_json and setting.value_json.get("value"):
            return setting.value_json["value"]
    except Exception:
        pass
    return _METHODOLOGY_FILE_FALLBACK[key]()


def get_all_methodology_from_db(db) -> dict[str, str]:
    """读取全部四个方法论组件（DB 优先，文件兜底）。

    返回: {"writing_craft": "...", "anti_ai_writing": "...", "quality_checklist": "...", "banned_words": "..."}
    """
    return {key: _read_single_methodology(db, key) for key in _METHODOLOGY_KEYS}


def save_methodology_to_db(db, key: str, content: str) -> None:
    """保存单个方法论组件到数据库。

    Args:
        db: SQLAlchemy 会话
        key: writing_craft / anti_ai_writing / quality_checklist / banned_words
        content: 组件内容
    """
    if key not in _METHODOLOGY_KEYS:
        raise ValueError(f"未知的方法论组件: {key}，支持: {', '.join(_METHODOLOGY_KEYS)}")
    from models import PlatformSetting
    setting_key = _METHODOLOGY_KEYS[key]
    setting = db.query(PlatformSetting).filter_by(setting_key=setting_key).first()
    if setting:
        setting.value_json = {"value": content}
    else:
        db.add(PlatformSetting(setting_key=setting_key, value_json={"value": content}))
    db.commit()


def get_methodology_from_db(db) -> str:
    """从 DB 读取组合后的写作方法论（用于 System Prompt 注入）。

    优先级：DB → 文件兜底。
    组件来源：writing_craft（DB） + anti_ai_writing（DB）→ 提取精简版。
    """
    try:
        craft = _read_single_methodology(db, "writing_craft")
        anti_ai = _read_single_methodology(db, "anti_ai_writing")

        parts: list[str] = []

        def add_section(source: str, start: str, end: str, title: str) -> None:
            text = _extract_between(source, start, end)
            if text:
                parts.append(f"### {title}\n{text}")

        parts.append("## 写作技法（来自 writing-craft.md）")
        add_section(craft, "## 1. 身体细节替代情绪词", "## 2. 贯穿道具系统", "身体细节替代情绪词")
        add_section(craft, "## 5. 一动一静节奏", "## 6.", "一动一静节奏控制")

        parts.append("## 去AI味规则（来自 anti-ai-writing.md）")
        add_section(anti_ai, "## AI写作指纹（必须避免）", "## 核心规则", "AI写作指纹（必须避免）")
        add_section(anti_ai, "## Show Don't Tell 原则", "## 质量维度检查", "Show Don't Tell 原则")
        add_section(anti_ai, "## 系统性去AI三遍法", "## 去AI味补充技法", "系统性去AI三遍法")

        combined = "\n\n".join(parts) if parts else ""
        if combined:
            return combined
    except Exception:
        pass

    return get_chapter_writing_methodology()


def build_chapter_generation_prompt(base_prompt: str, db=None) -> str:
    """构建完整的章节生成 System Prompt。

    优先级：DB（管理员可编辑）→ 文件兜底。

    Args:
        base_prompt: 基础 prompt（如 _BASE_NOVEL_PROMPT）
        db: SQLAlchemy 会话（可选，传入时优先从 DB 读取方法论）

    Returns:
        合并后的完整 System Prompt
    """
    methodology = get_methodology_from_db(db) if db else get_chapter_writing_methodology()
    if not methodology:
        return base_prompt
    return base_prompt + "\n\n" + methodology