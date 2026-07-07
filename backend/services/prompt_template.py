"""提示词模板服务：参数→prompt 转换、模板应用逻辑、系统默认提示词"""

from typing import Any


# 自定义模板通常承载作者最重要的写作约束，不能用 2000 字硬切。
CUSTOM_RULES_MAX_CHARS = 12000
CHAPTER_CUSTOM_STYLE_MAX_CHARS = 16000


def _normalize_custom_prompt(value: Any, *, max_chars: int = CUSTOM_RULES_MAX_CHARS) -> str:
    """整理用户自定义提示词，常规长度完整保留，极端超长时保留首尾关键约束。"""
    custom = str(value or "").strip()
    if len(custom) <= max_chars:
        return custom

    head_len = max_chars // 2
    tail_len = max_chars - head_len
    return (
        custom[:head_len]
        + "\n\n（自定义要求过长，已保留开头和结尾关键约束，中段仅为保护上下文窗口而压缩。）\n\n"
        + custom[-tail_len:]
    )


# ── 映射表 ─────────────────────────────────────────────

ART_STYLE_MAP = {
    "anime": "日式动漫风格，cel-shaded，鲜艳色彩，清晰线条",
    "realistic": "写实风格，电影级光影，自然色彩，高细节",
    "cartoon": "卡通风格，夸张造型，明亮配色，简洁线条",
    "ink": "中国水墨风格，笔触纹理，留白构图，墨色为主调",
}

COLOR_MAP = {
    "monochrome": "黑白单色调",
    "muted": "柔和淡雅配色",
    "balanced": "平衡自然的色彩",
    "vibrant": "鲜艳明亮的色彩",
}

MOOD_MAP = {
    "calm": "平静安宁的氛围",
    "neutral": "中性克制的情绪",
    "intense": "紧张压抑的气氛",
    "epic": "史诗宏大的气势",
}

TONE_MAP = {
    "light": "整体基调轻松愉快，可以加入幽默元素",
    "balanced": "情绪层次丰富，张弛有度",
    "serious": "保持严肃认真的态度，避免过于轻浮的描写",
    "dark": "营造压抑阴暗的氛围，强调人性阴暗面和悲剧感",
}


# ── 核心函数 ────────────────────────────────────────────

def build_prompt_from_params(base_prompt: str, params: dict | None, prompt_type: str) -> str:
    """根据参数化配置生成完整 prompt。

    Args:
        base_prompt: 系统默认的基础 prompt
        params: 参数字典（来自模板的 *_params 字段）
        prompt_type: 提示词类型（framework/chapter/character/manga_style）

    Returns:
        完整的 prompt 文本
    """
    if not params or not isinstance(params, dict):
        return base_prompt

    parts = [base_prompt]

    if prompt_type == "framework" or prompt_type == "framework_editing":
        _build_framework_rules(parts, params)
    elif prompt_type == "chapter":
        _build_chapter_rules(parts, params)
    elif prompt_type == "character":
        _build_character_rules(parts, params)
    elif prompt_type == "manga_style":
        _build_manga_style_rules(parts, params)

    return "\n\n".join(parts)


def _build_framework_rules(parts: list, params: dict):
    rules = []

    if params.get("story_length") == "long":
        rules.append("支持 100+ 章的持续创作，不要在前 20 章内把主线讲完")
    elif params.get("story_length") == "short":
        rules.append("适合 10 万字以内短篇，情节集中在核心冲突上")

    if params.get("pacing") == "slow":
        rules.append("采用慢热节奏，前期重点铺垫世界观和角色关系")
    elif params.get("pacing") == "fast":
        rules.append("采用快节奏，迅速推进情节，避免冗长铺垫")

    if params.get("world_building") == "rich":
        rules.append("构建详细的世界观体系，包括社会结构、历史背景、文化特色")
    elif params.get("world_building") == "simple":
        rules.append("世界观以简洁为主，不要过于复杂")

    tone = params.get("tone", "")
    if tone and tone in TONE_MAP:
        rules.append(TONE_MAP[tone])

    _custom = _normalize_custom_prompt(params.get("custom_rules"))
    if _custom:
        rules.append(f"用户自定义要求：{_custom}")

    if rules:
        parts.append("## 额外要求\n" + "\n".join(f"- {r}" for r in rules))


def _build_chapter_rules(parts: list, params: dict):
    rules = []

    if params.get("writing_style") == "descriptive":
        rules.append("注重场景描写和细节刻画，营造沉浸式阅读体验")
    elif params.get("writing_style") == "concise":
        rules.append("行文简洁明快，用最少的文字传达最多的信息")

    if params.get("dialogue_ratio") == "high":
        rules.append("以对话为主要推进手段，通过人物对话展现情节和性格")
    elif params.get("dialogue_ratio") == "low":
        rules.append("以叙述为主，对话仅用于关键情节节点")

    if params.get("inner_monologue") == "extensive":
        rules.append("大量使用内心独白，深入展现角色的内心世界")
    elif params.get("inner_monologue") == "minimal":
        rules.append("通过行为和对话展现角色，减少直接内心描写")

    if params.get("vocabulary_level") == "advanced":
        rules.append("使用文学性强的词汇和修辞手法")
    elif params.get("vocabulary_level") == "simple":
        rules.append("使用通俗易懂的语言，避免生僻词汇")

    _custom = _normalize_custom_prompt(
        params.get("custom_style_notes"),
        max_chars=CHAPTER_CUSTOM_STYLE_MAX_CHARS,
    )
    if _custom:
        rules.append(f"风格要求：{_custom}")

    if rules:
        parts.append("## 写作风格\n" + "\n".join(f"- {r}" for r in rules))


def _build_character_rules(parts: list, params: dict):
    rules = []

    if params.get("detail_level") == "high":
        rules.append("详细描写角色的外貌特征，包括发型、五官、体型、神态")
    elif params.get("detail_level") == "basic":
        rules.append("只保留核心外貌特征，简洁明确")

    if params.get("personality_depth") == "deep":
        rules.append("深入刻画角色性格，包括行为模式、价值观、内心矛盾")

    if params.get("arc_planning") == "complete":
        rules.append("明确角色的成长弧光：起始状态 → 触发事件 → 变化过程 → 最终状态")

    _custom = _normalize_custom_prompt(params.get("custom_requirements"))
    if _custom:
        rules.append(f"自定义要求：{_custom}")

    if rules:
        parts.append("## 角色塑造要求\n" + "\n".join(f"- {r}" for r in rules))


def _build_manga_style_rules(parts: list, params: dict):
    rules = []

    art = params.get("art_style", "")
    if art and art in ART_STYLE_MAP:
        rules.append(f"画风：{ART_STYLE_MAP[art]}")

    color = params.get("color_scheme", "")
    if color and color in COLOR_MAP:
        rules.append(f"配色：{COLOR_MAP[color]}")

    mood = params.get("mood", "")
    if mood and mood in MOOD_MAP:
        rules.append(f"氛围：{MOOD_MAP[mood]}")

    if params.get("composition") == "dynamic":
        rules.append("采用动态构图，大胆的角度和透视")
    elif params.get("composition") == "static":
        rules.append("采用静态平衡构图，工整对称")

    if params.get("lighting") == "dramatic":
        rules.append("使用戏剧化光影，强对比明暗")
    elif params.get("lighting") == "natural":
        rules.append("使用自然柔和的光线")

    _custom = _normalize_custom_prompt(params.get("custom_style_prompt"))
    if _custom:
        rules.append(f"风格补充：{_custom}")

    if rules:
        parts.append("## 画面风格指令\n" + "\n".join(f"- {r}" for r in rules))


# ── 模板应用逻辑 ────────────────────────────────────────

def get_template_story_length(story_id: int, db) -> str | None:
    """获取模板绑定中的 story_length 参数。

    Returns:
        story_length 值（如 "short"/"medium"/"long"），无模板或无该参数时返回 None。
    """
    from models import StoryTemplateBinding

    binding = db.query(StoryTemplateBinding).filter_by(story_id=story_id).first()
    if not binding or not binding.template:
        return None

    template = binding.template
    # 优先从 framework_params 中提取
    params = getattr(template, "framework_params", None)
    if isinstance(params, dict):
        val = str(params.get("story_length") or "").strip().lower()
        if val in ("short", "medium", "long"):
            return val
    # 从 framework_prompt 全文中推断（作为 fallback）
    full_prompt = getattr(template, "framework_prompt", None)
    if full_prompt and isinstance(full_prompt, str):
        t = full_prompt.lower()
        if "短篇" in t or "short" in t:
            return "short"
        if "中篇" in t or "medium" in t:
            return "medium"
        if "长篇" in t or "long" in t:
            return "long"
    return None


# prompt_type → system prompt key 映射
_PROMPT_TYPE_TO_SYSTEM_KEY = {
    "framework": "prompt.framework_generation",
    "framework_editing": "prompt.framework_editing",
    "chapter": "prompt.chapter_generation",
    "character": "prompt.reference_character",
    "manga_style": "prompt.reference_manga_style",
    "tag_generation": "prompt.tag_generation",
}


def get_effective_prompt(story_id: int, prompt_type: str, db) -> str:
    """获取作品实际使用的 prompt。

    优先级：模板完整 prompt > 模板参数生成 > 系统默认（数据库）
    章节类型（chapter）自动追加写作方法论作为兜底。

    Args:
        story_id: 作品 ID
        prompt_type: framework/framework_editing/chapter/character/manga_style/tag_generation
        db: SQLAlchemy 数据库会话

    Returns:
        实际使用的 prompt 文本
    """
    from models import StoryTemplateBinding

    binding = db.query(StoryTemplateBinding).filter_by(story_id=story_id).first()

    prompt: str = ""
    if binding and binding.template:
        template = binding.template

        full_prompt = getattr(template, f"{prompt_type}_prompt", None)
        if full_prompt and full_prompt.strip():
            prompt = full_prompt
        else:
            system_default = _get_db_default(prompt_type, db)
            params = getattr(template, f"{prompt_type}_params", None)
            if params and isinstance(params, dict):
                prompt = build_prompt_from_params(system_default, params, prompt_type)
            else:
                prompt = system_default
    else:
        prompt = _get_db_default(prompt_type, db)

    if prompt_type == "chapter" and prompt:
        from services.writing_utils import get_methodology_from_db
        methodology = get_methodology_from_db(db)
        if methodology and methodology not in prompt:
            prompt = prompt + "\n\n" + methodology

    return prompt


def _get_db_default(prompt_type: str, db) -> str:
    """根据 prompt_type 从数据库读取系统默认提示词。"""
    setting_key = _PROMPT_TYPE_TO_SYSTEM_KEY.get(prompt_type, f"prompt.{prompt_type}")
    return get_system_prompt(setting_key, db)


# ── 系统默认提示词（数据库存储） ──────────────────────────

# PlatformSetting key 前缀
_SYSTEM_PROMPT_KEY_PREFIX = "prompt."

# 运行时系统提示词的 key 列表
SYSTEM_PROMPT_KEYS = {
    "chapter_generation": "prompt.chapter_generation",
    "framework_generation": "prompt.framework_generation",
    "framework_editing": "prompt.framework_editing",
    "framework_continuation": "prompt.framework_continuation",
    "onboarding": "prompt.onboarding",
    "import_context": "prompt.import_context",
    "build_import_brief": "prompt.build_import_brief",
    "build_brief": "prompt.build_brief",
    "build_story_bible": "prompt.build_story_bible",
    "tag_generation": "prompt.tag_generation",
    # 参考提示词（用户创建模板时看到的内置参考）
    "reference_framework": "prompt.reference_framework",
    "reference_chapter": "prompt.reference_chapter",
    "reference_character": "prompt.reference_character",
    "reference_manga_style": "prompt.reference_manga_style",
}


def get_system_prompt(key: str, db) -> str:
    """从数据库读取系统默认提示词。

    Args:
        key: SYSTEM_PROMPT_KEYS 中的键或完整 setting_key。
        db: SQLAlchemy 数据库会话。

    Returns:
        提示词文本，不存在时返回空字符串。
    """
    from models import PlatformSetting

    setting_key = SYSTEM_PROMPT_KEYS.get(key, key)
    setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == setting_key
    ).first()
    if setting and setting.value_json:
        return str(setting.value_json.get("value") or "")
    return ""


def set_system_prompt(key: str, value: str, db) -> None:
    """写入系统默认提示词到数据库。

    Args:
        key: SYSTEM_PROMPT_KEYS 中的键或完整 setting_key。
        value: 提示词正文。
        db: SQLAlchemy 数据库会话。
    """
    from models import PlatformSetting

    setting_key = SYSTEM_PROMPT_KEYS.get(key, key)
    setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == setting_key
    ).first()
    if setting:
        setting.value_json = {"value": value}
    else:
        db.add(PlatformSetting(setting_key=setting_key, value_json={"value": value}))
