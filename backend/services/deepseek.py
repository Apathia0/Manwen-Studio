import asyncio
import contextvars
import hashlib
import json
import logging
import re
from typing import Any, AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

from services.writing_utils import build_chapter_generation_prompt
from services.framework_utils import _extract_outline_chapters, validate_framework_json
from services.story_state import build_story_bible_compact, build_story_memory_compact, extract_author_profile_sections, extract_report_highlights
from services.token_utils import estimate_tokens, TOKEN_COMPRESS_THRESHOLD, compress_context_parts_if_needed

# 默认值会被 router 层从 PlatformSetting 数据库动态覆盖
DEEPSEEK_API_KEY = ""
DEEPSEEK_BASE_URL = ""
DEEPSEEK_MODEL = ""

_RUNTIME_BASE_URL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "deepseek_runtime_base_url",
    default=None,
)
_RUNTIME_MODEL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "deepseek_runtime_model",
    default=None,
)
_USAGE_ACCUMULATOR: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "deepseek_usage_accumulator",
    default=None,
)

CHAPTER_TARGET_MIN_CHARS = 2200
CHAPTER_TARGET_MAX_CHARS = 2800
CHAPTER_TARGET_IDEAL_CHARS = 2500
CHAPTER_FIRST_PASS_MIN_CHARS = 2300
CHAPTER_FIRST_PASS_MAX_CHARS = 2550
CHAPTER_COMPLETION_MAX_TOKENS = 2816

_RUNTIME_TEMPERATURE: float | None = None
_RUNTIME_TOP_P: float | None = None


class ChapterPipelineQualityError(RuntimeError):
    """三角色章节链路产出正文但未通过编辑质量门禁。"""

    def __init__(self, review: Any | None = None):
        super().__init__("三角色章节链路未达到编辑质量门禁，已拒绝返回未达标候选稿")
        self.review = review


def configure_temperature_top_p(temperature: float | None = None, top_p: float | None = None):
    global _RUNTIME_TEMPERATURE, _RUNTIME_TOP_P
    _RUNTIME_TEMPERATURE = temperature
    _RUNTIME_TOP_P = top_p


def _maybe_configure_temperature_top_p_from_db(db=None):
    global _RUNTIME_TEMPERATURE, _RUNTIME_TOP_P
    if db is None:
        return
    try:
        from models import PlatformSetting
        temp_setting = db.query(PlatformSetting).filter_by(setting_key="deepseek_temperature").first()
        if temp_setting and temp_setting.value_json:
            val = temp_setting.value_json
            if isinstance(val, dict):
                val = val.get("value")
            if val is not None:
                _RUNTIME_TEMPERATURE = float(val)
        top_p_setting = db.query(PlatformSetting).filter_by(setting_key="deepseek_top_p").first()
        if top_p_setting and top_p_setting.value_json:
            val = top_p_setting.value_json
            if isinstance(val, dict):
                val = val.get("value")
            if val is not None:
                _RUNTIME_TOP_P = float(val)
    except Exception:
        pass


def _apply_runtime_params(payload: dict) -> dict:
    if _RUNTIME_TEMPERATURE is not None:
        payload["temperature"] = _RUNTIME_TEMPERATURE
    if _RUNTIME_TOP_P is not None:
        payload["top_p"] = _RUNTIME_TOP_P
    return payload

# 章节生成 base prompt（含世界观一致性，与 NOVEL_PROMPT_SEED 共享写作方法论）
_DEEPSEEK_CHAPTER_BASE = (
    "你是起点白金级网文作家，你的作品长期位居各平台畅销榜首，以逻辑严密、节奏精准、人物鲜活著称。\n"
    "\n"
    "## 核心创作铁律\n"
    "1. **逻辑自洽优先**：每一个情节点都必须有因有果。角色做出的每个决定，都必须有足够的情感动机和信息支撑。\n"
    "   - 不能出现「没有理由就突然改变主意」「明明知道危险还往上冲」这类不合逻辑的行为。\n"
    "   - 如果角色做出了看似不合理的决定，必须在文中给出足够的情感铺垫或信息揭示。\n"
    "\n"
    "2. **世界观一致性**：作品圣经中的世界观设定、势力关系、能力体系、世界历史是**不可违反**的硬约束。\n"
    "   - 所有角色行为、剧情发展都必须符合已建立的世界观框架。\n"
    "   - 如果要引入新设定，必须与现有圣经中的设定兼容，不能制造矛盾。\n"
    "   - 圣经中的「必保留规则」必须严格执行，不能因为剧情方便而绕过。\n"
    "\n"
    "3. **剧情推进要有因果链**：每个事件都必须是前一个事件的合理结果，不能「跳跃式」推进。\n"
    "   - 禁止出现「几天后」「过了段时间」「不知不觉中」这类时间跳跃直接推进剧情。\n"
    "   - 禁止用「突然出现」「突然发生」来制造转折——所有转折都必须有铺垫。\n"
    "   - 如果需要时间过渡，必须用具体场景或细节来展示这段时间发生了什么。\n"
    "\n"
    "4. **人物行为要符合其性格和处境**：角色不能做出与其一贯性格相悖的行为，除非有足够的心理铺垫。\n"
    "   - 内向的角色不能突然变得健谈，除非有特定的情境触发。\n"
    "   - 聪明的角色不能突然做出愚蠢的决定，除非有情绪干扰或信息不对称。\n"
    "\n"
    "## 对话写作要求\n"
    "1. 对话必须符合角色的性格、身份、处境和情绪。\n"
    "2. 禁止所有角色说话风格雷同——必须有明显的语言差异。\n"
    "3. 对话要有潜台词，不能直白地表达所有情感。\n"
    "4. 禁止用对话直接解释剧情——要通过行动和细节来展现。\n"
    "5. 整章至少包含 3 句有效对话，无对话的章节在起点会被认定为「叙述文」而非小说。\n"
    "6. 对话必须包含至少 1 个口语化语气词（行/得了/那啥/嗯/哦/啊/哎/咦/嘿/哈/哼/啧），禁止全部对话用书面语。\n"
    "7. 不同身份角色使用不同口语风格：江湖人用「阁下/在下/道友」、学生用「哥们/姐们/老师」、市井用「大哥/大姐/师傅」、文人用「先生/后学/贤弟」。\n"
    "8. 对话占比建议 30-50%，禁止整章无对话或整章纯对话。对话必须推进剧情或展现性格，禁止「嗯」「好的」等无信息对话单独成段。\n"
     "\n"
     "## 情绪展示要求\n"
     "1. 【禁止】直接写情绪词（愤怒/悲伤/紧张/害怕/委屈/绝望）——用身体反应和行为展现。\n"
     "2. 【禁止】「他感到/他觉得/他意识到/他明白/他知道」等告知式心理描写。\n"
     "3. 【禁止】「心中涌起一股XX」「心头一震」「心底泛起XX」等模板化情绪描写。\n"
     "4. 整章心理活动累计不超过 2 段。心理活动要短、碎、自然，不形成「内心独白」。\n"
    "\n"
    "## 标点规范\n"
    "1. 【禁止破折号】全文禁止使用破折号（——），用逗号、句号或冒号代替。破折号是 AI 生成的典型痕迹，必须消除。\n"
    "2. 禁止滥用省略号，用逗号/句号表示停顿。\n"
    "\n"
    "## 逻辑自检清单（在写完每个场景后检查）\n"
    "- 这个角色为什么会做出这个决定？有足够的情感铺垫吗？\n"
    "- 这个事件的发生合理吗？有前因后果吗？\n"
    "- 这段对话符合角色的性格和处境吗？\n"
    "- 这个情节能让读者信服吗？有没有逻辑漏洞？\n"
    "- 如果我是读者，我会觉得这个发展牵强吗？\n"
    "\n"
    "（关于写作技法、叙事密度、去AI味规则等完整方法论，见下方补充规则。）\n"
    "\n"
    "## 叙事结构对抗规则（对抗 AI 默认倾向，必须遵守）\n"
    "AI 生成小说有 5 大叙事缺陷，以下规则用于对抗这些倾向：\n"
    "\n"
    "### 1. 禁止单线叙事\n"
    "- 每 5 章至少 1 次视角切换或支线穿插，禁止整章只讲一条故事线。\n"
    "- 支线必须与主线有交集点，不能完全平行。\n"
    "\n"
    "### 2. 禁止道德简化\n"
    "- 反派必须有合理动机（复仇/信仰/生存/爱/恐惧），禁止纯粹恶役（为恶而恶）。\n"
    "- 善恶之间必须有灰度地带，配角可以立场摇摆。\n"
    "- 禁止「天生邪恶」「骨子里坏」等先天定性描写。\n"
    "\n"
    "### 3. 禁止主题直白点破\n"
    "- 主题通过事件和人物行为体现，禁止角色说出主题。\n"
    "- 禁止「我终于明白了，这就是成长」「原来真正的力量是……」等点破式台词。\n"
    "- 禁止 narrator 总结升华（「这一刻他明白了……」「故事告诉他……」）。\n"
    "\n"
    "### 4. 禁止时间线性化\n"
    "- 每 20 章至少 1 次时间跳跃或回忆插入，禁止全程线性推进。\n"
    "- 允许倒叙（先写结果再写过程）、插叙（中途闪回）。\n"
    "- 禁止「不知不觉中」「几天后」「过了段时间」等模糊时间跳跃推进剧情。\n"
    "\n"
    "### 5. 主角必须主动\n"
    "- 每章至少 1 个主角主动决策（非被动反应）。\n"
    "- 主角不能只被事件推着走，必须有主动目标和行动。\n"
    "- 禁止「主角莫名其妙卷入」超过 3 次/卷——卷入必须有因果。\n"
)


def _get_chapter_system_prompt(db=None) -> str:
    """动态构建章节 System Prompt（每次调用实时读取方法论）。"""
    return build_chapter_generation_prompt(_DEEPSEEK_CHAPTER_BASE, db=db)


def build_agent_chapter_system_prompt(db=None) -> str:
    """构建 Agent 助手专用的章节写作 System Prompt。

    对标框架直出的 _DEEPSEEK_CHAPTER_BASE + build_chapter_generation_prompt，
    供 Agent 的 System Prompt 注入和 adjust_chapter_by_instruction 的 fallback 使用。
    包含：核心创作铁律 + 标点规范 + 写作技法 + 去AI味规则。
    """
    return build_chapter_generation_prompt(_DEEPSEEK_CHAPTER_BASE, db=db)


def configure_runtime(base_url: str | None = None, model: str | None = None) -> None:
    if isinstance(base_url, str) and base_url.strip():
        _RUNTIME_BASE_URL.set(base_url.strip().rstrip("/"))
    if isinstance(model, str) and model.strip():
        _RUNTIME_MODEL.set(model.strip())


def runtime_base_url() -> str:
    """返回当前请求或任务上下文中的 DeepSeek API 地址。"""
    return _RUNTIME_BASE_URL.get() or DEEPSEEK_BASE_URL


def runtime_model() -> str:
    """返回当前请求或任务上下文中的 DeepSeek 模型。"""
    return _RUNTIME_MODEL.get() or DEEPSEEK_MODEL


def reset_usage_accumulator() -> None:
    """重置当前请求或异步任务的 token 用量累计。"""
    _USAGE_ACCUMULATOR.set({"input_tokens": 0, "output_tokens": 0})


def _record_response_usage(data: dict) -> None:
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return
    current = _USAGE_ACCUMULATOR.get()
    if current is None:
        current = {"input_tokens": 0, "output_tokens": 0}
        _USAGE_ACCUMULATOR.set(current)
    # 子任务会继承同一个累计器对象，原地更新才能把并行调用汇回父任务。
    current["input_tokens"] += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    current["output_tokens"] += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)


def consume_usage_accumulator() -> dict[str, int]:
    """读取并清空当前上下文累计的 token 用量。"""
    usage = dict(_USAGE_ACCUMULATOR.get() or {"input_tokens": 0, "output_tokens": 0})
    _USAGE_ACCUMULATOR.set(None)
    return usage

# NOVEL_SYSTEM_PROMPT 已移至 main.py _seed_system_prompts


def _deepseek_auth_headers(api_key: str | None = None) -> dict[str, str]:
    if not runtime_base_url():
        raise ValueError("DeepSeek API 地址未配置，请在后台设置中配置 API 地址后重试。")
    if not runtime_model():
        raise ValueError("DeepSeek 模型未配置，请在后台设置中配置模型名称后重试。")
    key = (api_key or DEEPSEEK_API_KEY or "").strip()
    if not key:
        from .errors import MissingApiKeyError
        raise MissingApiKeyError("DeepSeek")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _loads_json_lenient(text: str):
    # DeepSeek occasionally returns literal newlines/control chars inside quoted
    # strings. strict=False accepts those without treating the whole response as
    # invalid JSON.
    return json.loads(text, strict=False)


def _response_json(resp: httpx.Response, *, context: str = "DeepSeek") -> dict:
    """Parse upstream JSON with a useful error when proxies return empty/non-JSON bodies."""
    text = getattr(resp, "text", None)
    if text is None:
        json_loader = getattr(resp, "json", None)
        if callable(json_loader):
            data = json_loader()
            if not isinstance(data, dict):
                raise ValueError(f"{context} 服务响应格式异常：顶层不是 JSON 对象")
            _record_response_usage(data)
            return data
        text = ""
    if not text.strip():
        raise ValueError(f"{context} 服务返回空响应，请稍后重试或检查 API 地址、模型与代理配置")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:300].replace("\n", "\\n").replace("\r", "\\r")
        logger.warning(
            "%s returned non-JSON response: status=%s content_type=%s preview=%s",
            context,
            getattr(resp, "status_code", None),
            (getattr(resp, "headers", {}) or {}).get("content-type", ""),
            preview,
        )
        raise ValueError(f"{context} 服务返回了非 JSON 响应，请稍后重试或检查 API 地址、模型与代理配置") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{context} 服务响应格式异常：顶层不是 JSON 对象")
    _record_response_usage(data)
    return data


async def repair_chapter_opening_only(
    *,
    content: str,
    previous_handoff: dict | None,
    story_context: dict | None,
    chapter_info: dict | None,
    api_key: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """只改写章节首句，保留后续正文不变。"""
    original = str(content or "")
    if not original.strip():
        return original

    opening_match = re.search(r"[。！？]\s*", original[:800])
    opening_end = opening_match.end() if opening_match else min(len(original), 240)
    body = original[opening_end:]
    prompt = f"""请只重写下面章节的开头一句，使其自然承接上一章；不要续写正文，不要解释。

上一章交接：{json.dumps(previous_handoff or {}, ensure_ascii=False)}
当前章节：{json.dumps(chapter_info or {}, ensure_ascii=False)}
作品上下文：{json.dumps(story_context or {}, ensure_ascii=False)[:3000]}
待重写开头：{original[:opening_end]}
"""
    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": system_prompt or "你是小说连载编辑，只输出改写后的开头一句。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": 300,
    }
    payload = _apply_runtime_params(payload)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
    response.raise_for_status()
    data = _response_json(response, context="DeepSeek")
    repaired = str(data["choices"][0]["message"]["content"] or "").strip()
    if not repaired:
        return original
    return repaired + body


def _log_shot_summary(logger_obj, content: str, label: str = "拆镜"):
    """解析 JSON 并输出结构化镜头摘要日志，避免原文淹没关键信息。"""
    result = _extract_json_object(content)
    all_shots = result.get("shots", [])
    if not isinstance(all_shots, list):
        logger_obj.info("%s: 返回非数组 shots=%s", label, str(all_shots)[:200])
        return
    parts = []
    for s in all_shots[:5]:
        idx = s.get("shot_index", "?")
        loc = (s.get("scene_location") or "")[:20]
        chars = s.get("characters", [])
        chars_str = ",".join(chars[:3]) if isinstance(chars, list) else str(chars)[:30]
        summary = (s.get("story_summary") or "")[:40]
        parts.append(f"#{idx}[{loc}] {chars_str} | {summary}")
    if len(all_shots) > 5:
        parts.append(f"... 共 {len(all_shots)} 个镜头")
    logger_obj.info("%s 返回 %d 个镜头: %s", label, len(all_shots), "；".join(parts))


def _sanitize_novel_content(text: str) -> str:
    """清理 AI 生成的小说正文中的常见问题。

    处理项：
    1. 移除所有破折号（——），替换为逗号或省略号（根据上下文）
    2. 移除多余的「突然」「忽然」等廉价转折词（保留首次出现，移除后续）
    """
    import re
    if not text:
        return text

    # 处理破折号：—— 前后有标点则直接移除，否则替换为逗号
    # 情况1：句号/问号/感叹号 + —— → 保留前面的标点，移除破折号
    text = re.sub(r'([。！？])——\s*', r'\1', text)
    # 情况2：逗号/顿号 + —— → 保留逗号，移除破折号
    text = re.sub(r'([，、])——\s*', r'\1', text)
    # 情况3：—— 后跟标点 → 保留后面的标点，移除破折号
    text = re.sub(r'\s*——([。！？，、])', r'\1', text)
    # 情况4：独立的破折号（前后无标点）→ 替换为逗号
    text = text.replace('——', '，')

    # 处理廉价转折词：保留第1次，移除后续出现
    cheap_transition_words = ['突然', '忽然', '就在这时', '就在此时']
    for word in cheap_transition_words:
        count = text.count(word)
        if count > 1:
            # 保留第1次，后续替换为逗号分隔
            first_idx = text.index(word)
            result = text[:first_idx + len(word)]
            rest = text[first_idx + len(word):]
            result += rest.replace(word, '，', count - 1)
            text = result

    return text


def _extract_json_array(raw: str) -> list:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        return _loads_json_lenient(raw)
    except json.JSONDecodeError as first_error:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise ValueError("场景分割响应未包含 JSON 数组") from first_error
        try:
            return _loads_json_lenient(match.group(0))
        except json.JSONDecodeError as second_error:
            raise ValueError("场景分割响应不是有效的 JSON") from second_error


def _extract_json_like_string_array(raw: str) -> list[str] | None:
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return None
    text = match.group(0)
    items: list[str] = []
    in_string = False
    escape = False
    current: list[str] = []

    for ch in text:
        if not in_string:
            if ch == '"':
                in_string = True
                current = []
            continue

        if escape:
            if ch == "n":
                current.append("\n")
            elif ch == "r":
                current.append("\r")
            elif ch == "t":
                current.append("\t")
            else:
                current.append(ch)
            escape = False
            continue

        if ch == "\\":
            escape = True
            continue

        if ch == '"':
            items.append("".join(current).strip())
            in_string = False
            current = []
            continue

        current.append(ch)

    cleaned = [item for item in items if item]
    return cleaned or None


def _extract_balanced_json_object_text(raw: str) -> str | None:
    start = raw.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]

    return None


def _extract_scenes_payload(raw: str) -> list[str]:
    """Accept either a raw JSON array or an object like {"scenes": [...]}."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        parsed = _loads_json_lenient(raw)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        scenes = parsed.get("scenes")
        if isinstance(scenes, list) and all(isinstance(scene, str) for scene in scenes):
            return scenes

    if isinstance(parsed, list) and all(isinstance(scene, str) for scene in parsed):
        return parsed

    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            parsed = _loads_json_lenient(match.group(0))
            if isinstance(parsed, list) and all(isinstance(scene, str) for scene in parsed):
                return parsed
        except json.JSONDecodeError:
            fallback = _extract_json_like_string_array(match.group(0))
            if fallback and all(isinstance(scene, str) for scene in fallback):
                return fallback

    raise ValueError("场景分割响应必须是字符串 JSON 数组")

def _scene_split_prompt(page_count: int = 10) -> str:
    return f"""你是一位专业漫画分镜师。请将小说内容拆分为恰好{page_count}页漫画。

## ★★★ 最高原则：叙事完整性优先 ★★★
你的首要任务是**完整覆盖原文所有关键事件**，不能遗漏任何重要情节。
分镜的目的是让读者通过漫画获得与原文等价的故事体验，而非展示画技。

## 两阶段工作流程（必须严格执行）

### 第一步：提取关键事件（内心完成，不输出）
在脑中列出原文的每一个关键事件，包括：
- 推动剧情的动作和决定
- 重要对话和信息揭示
- 冲突升级和转折点
- 角色的关键反应和情绪变化
按时间顺序排列，标注每个事件的重要程度（核心/重要/辅助）。

### 第二步：分配到 {page_count} 页
- 将第一步的事件**均匀分配**到 {page_count} 页中
- **核心事件**必须占据更多格数（2-3格），**辅助事件**可以压缩（1格）
- 每页的主题应明确，不能把不相关的事件混在一页
- 宁可每页信息密度高，也不能用氛围格凑数导致事件遗漏

## 分镜格类型与优先级

每页 4-5 格，按以下优先级分配格数：

| 格类型 | 作用 | 优先级 | 每页上限 |
|--------|------|--------|----------|
| 对话格 | 推进剧情、揭示信息 | ★★★ 最高 | 2-3格 |
| 动作格 | 关键动作、事件、冲突 | ★★★ 最高 | 2-3格 |
| 反应格 | 角色情绪反应、心理变化 | ★★ 中等 | 1格 |
| 氛围格 | 环境、气氛、过渡 | ★ 最低 | 每页最多1格 |

**严禁用多个格子展示同一瞬间的不同角度**——这是最常见的叙事浪费。

## 每页格式要求
- 4-5 个分镜格，用【第1格】【第2格】…标记
- 每格描述：构图类型（大宽格/中景/窄格/特写）+ 画面内容
- 对话气泡：用「」标记，每页 2-4 条
- 音效字：仅在动作/情绪转折场景使用，不要每格都加
- 景别交替：远景→中景→特写，避免连续 3 格相同景别

## 格式示例
"第1页：【第1格（大宽格）】场景环境全貌。【第2格（中景）】角色A和B面对面对话。对话气泡：「A的台词。」【第3格（窄格）】角色B的反应和动作。对话气泡：「B的回应。」【第4格（大宽格）】关键事件发生的动态画面。音效：动作音效。"

视觉风格由后续生成阶段的参考图决定；本分镜只负责构图、镜头和叙事信息。

## 禁止事项
1. 禁止用氛围格/特写格凑数——每格都必须有叙事功能
2. 禁止用多个格子展示同一瞬间的不同角度
3. 禁止遗漏原文中的核心事件和关键对话
4. 禁止在每格都加音效字——只在关键动作/转折处使用

请输出JSON数组，不要输出其他任何内容：
[
  "第1页：【第1格...】...【第2格...】...【第3格...】...【第4格...】...",
  "第2页：【第1格...】...【第2格...】...【第3格...】...【第4格...】...",
  ...
  "第{page_count}页：【第1格...】...【第2格...】...【第3格...】...【第4格...】..."
]"""


async def chat_stream(messages: list[dict], api_key: str | None = None, framework_context: str = "", system_prompt: str | None = None) -> AsyncGenerator[str, None]:
    """Stream chat response from DeepSeek."""
    system_content = system_prompt or ""
    if framework_context:
        system_content += "\n\n## 故事框架约束\n" + framework_context
    payload = {
        "model": runtime_model(),
        "messages": [{"role": "system", "content": system_content}] + messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 6144,
    }
    payload = _apply_runtime_params(payload)

    async with httpx.AsyncClient(timeout=600) as client:
        async with client.stream(
            "POST",
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    _record_response_usage(data)
                    if not data.get("choices"):
                        continue
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def generate_novel(messages: list[dict], api_key: str | None = None, framework_context: str = "", system_prompt: str | None = None) -> str:
    """非流式生成一章完整小说正文。"""
    system_content = system_prompt or ""
    if framework_context:
        system_content += "\n\n## 故事框架约束\n" + framework_context
    full_messages = [{"role": "system", "content": system_content}] + messages
    full_messages.append({
        "role": "user",
        "content": (
            f"请根据我们的讨论，创作这一话的完整小说正文。正文字数目标约 {CHAPTER_TARGET_IDEAL_CHARS} 字，"
            f"建议 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字；低于 {CHAPTER_TARGET_MIN_CHARS} 字视为展开不足，"
            f"超过 {CHAPTER_TARGET_MAX_CHARS} 字视为超出标准，必须删去无效铺垫并自行收束。"
            f"首轮请优先写到 {CHAPTER_FIRST_PASS_MIN_CHARS}-{CHAPTER_FIRST_PASS_MAX_CHARS} 字，按 9-10 个自然段组织，"
            "每段约 200-240 字，章末钩子完成后立刻停笔，不追加尾声、总结或下一章预告。"
            "叙事边界硬闸：只能完成当前章节目标，不能提前完成后续章节的核心行动、资源收获、冲突解决或爽点兑现；"
            "后续章节信息只能作为设定边界，最多用一句未解线索承接，不能写成完整场面。"
            "场景经济、对话有信息量、章末必须有钩子。"
            "直接输出正文，不要标题和说明。"
        ),
    })

    async def _complete_once(messages_for_call: list[dict]) -> str:
        payload = {
            "model": runtime_model(),
            "messages": messages_for_call,
            "stream": False,
            "max_tokens": CHAPTER_COMPLETION_MAX_TOKENS,
        }
        payload = _apply_runtime_params(payload)

        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                f"{runtime_base_url()}/chat/completions",
                json=payload,
                headers=_deepseek_auth_headers(api_key),
            )
            resp.raise_for_status()
            data = _response_json(resp, context="DeepSeek")
            return _sanitize_novel_content(data["choices"][0]["message"]["content"])

    boundary_scope = _extract_chapter_scope_from_text(framework_context)
    content = await _complete_once(full_messages)
    boundary_issues = _detect_chapter_boundary_issues(content, boundary_scope)
    if boundary_issues:
        retry_messages = full_messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "上一版疑似提前写完后续章节事件，必须完整重写。\n"
                    "越界点：\n- " + "\n- ".join(boundary_issues) + "\n"
                    "重写要求：只完成当前章节任务卡；后续章节只能保留一句以内未解线索，"
                    f"不得写成完整场面；正文字数控制在 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字。"
                    "只输出重写后的正文，不要解释。"
                ),
            },
        ]
        retry_content = await _complete_once(retry_messages)
        retry_issues = _detect_chapter_boundary_issues(retry_content, boundary_scope)
        if len(retry_issues) <= len(boundary_issues):
            content = retry_content
            boundary_issues = retry_issues
        if boundary_issues:
            logging.warning("聊天正文生成仍疑似预支后续章节: %s", boundary_issues)

    char_count = len(content.replace(" ", "").replace("\n", "").replace("\r", ""))
    if CHAPTER_TARGET_MIN_CHARS <= char_count <= CHAPTER_TARGET_MAX_CHARS:
        return content

    retry_reason = (
        f"上一版约 {char_count} 字，低于 {CHAPTER_TARGET_MIN_CHARS} 字，展开不足。"
        if char_count < CHAPTER_TARGET_MIN_CHARS
        else f"上一版约 {char_count} 字，超过 {CHAPTER_TARGET_MAX_CHARS} 字，节奏偏散。"
    )
    retry_messages = full_messages + [
        {"role": "assistant", "content": content},
        {
            "role": "user",
            "content": (
                f"{retry_reason}请完整重写为 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字。"
                "必须保留当前章节核心因果链，但删除跨章预支、重复心理活动、无效环境描写和总结升华。"
                "只能输出修订后的完整正文，不要解释。"
            ),
        },
    ]
    retry_content = await _complete_once(retry_messages)
    retry_count = len(retry_content.replace(" ", "").replace("\n", "").replace("\r", ""))
    if abs(retry_count - CHAPTER_TARGET_IDEAL_CHARS) <= abs(char_count - CHAPTER_TARGET_IDEAL_CHARS):
        return retry_content
    return content


async def split_scenes(chat_messages: list[dict], character_profiles: str = "", page_count: int = 10, api_key: str | None = None) -> list[str]:
    """Use DeepSeek to split chat novel content into manga page descriptions."""
    scene_prompt = _scene_split_prompt(page_count)
    if character_profiles:
        scene_prompt += f"\n\n以下是角色外貌设定，分镜描述中必须严格匹配这些外貌特征：\n{character_profiles}"

    # 计算上下文总长度，如果过长则在提示词前加入聚焦指令
    total_content_len = sum(len(str(m.get("content") or "")) for m in chat_messages)
    if total_content_len > 3000:
        scene_prompt = (
            "【重要提示】原文内容较长，你必须先通读全文，提取所有关键事件（剧情转折、重要对话、冲突、揭示），"
            f"然后将这些事件均匀分配到 {page_count} 页中。"
            "宁可每页信息密度高，也绝不能遗漏任何核心事件。\n\n"
            + scene_prompt
        )

    async def _request_scene_split(extra_instruction: str = "") -> str:
        prompt = scene_prompt
        if extra_instruction:
            prompt += "\n\n" + extra_instruction
        messages = chat_messages + [
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": runtime_model(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"你是漫画分镜专家，首要任务是确保叙事完整性——覆盖原文所有关键事件。"
                        f'只输出一个有效JSON对象，格式必须是 {{"scenes": ["...", "..."]}}。'
                        f"scenes 必须恰好有 {page_count} 个字符串元素。"
                        f"每个元素代表一整页漫画，每页包含4-5个分镜格。"
                        f"严禁遗漏核心事件，严禁用氛围格凑数。"
                        f"不要输出 Markdown、解释、前后缀或任何非 JSON 文本。"
                    ),
                },
            ] + messages,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{runtime_base_url()}/chat/completions",
                json=payload,
                headers=_deepseek_auth_headers(api_key),
            )
            resp.raise_for_status()
            data = _response_json(resp, context="DeepSeek")
            return data["choices"][0]["message"]["content"]

    raw = ""
    last_error: Exception | None = None
    retry_instructions = (
        "",
        f"重试：严格返回 {{\"scenes\": [...]}}，其中 scenes 必须恰好包含 {page_count} 页。"
        f"再次强调：必须覆盖原文所有关键事件，不能遗漏任何核心情节。每个格子必须有叙事功能，不能用氛围格凑数。",
    )

    for idx, extra_instruction in enumerate(retry_instructions):
        raw = await _request_scene_split(extra_instruction)
        try:
            scenes = _extract_scenes_payload(raw)
            if len(scenes) != page_count:
                raise ValueError(f"期望 {page_count} 个场景，实际得到 {len(scenes)} 个")
            return scenes
        except ValueError as exc:
            last_error = exc
            if idx == len(retry_instructions) - 1:
                break

    preview = raw[:500].replace("\n", "\\n")
    raise ValueError(f"{last_error}; raw={preview}")


# ─── Framework helpers ─────────────────────────────────────

def _extract_json_object(raw: str) -> dict:
    """Extract a JSON object from LLM response, stripping markdown fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        result = _loads_json_lenient(raw)
        if isinstance(result, dict):
            return result
        raise ValueError("响应是有效的 JSON 但不是对象")
    except json.JSONDecodeError as first_error:
        match = re.search(r"\{[\s\S]*\}", raw)
        candidate = match.group(0) if match else _extract_balanced_json_object_text(raw)
        if not candidate:
            raise ValueError("响应未包含 JSON 对象") from first_error
        try:
            result = _loads_json_lenient(candidate)
            if isinstance(result, dict):
                return result
            raise ValueError("提取的 JSON 不是对象")
        except json.JSONDecodeError as second_error:
            balanced = _extract_balanced_json_object_text(candidate)
            if balanced and balanced != candidate:
                try:
                    result = _loads_json_lenient(balanced)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    pass
            raise ValueError("响应不是有效的 JSON") from second_error


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return cleaned.strip()


def _is_brief_confirmation(text: str) -> bool:
    normalized = re.sub(r"[\s，。！？!?,；;、~～]+", "", (text or "").strip().lower())
    return normalized in {
        "是的",
        "是",
        "对",
        "对的",
        "没错",
        "嗯",
        "嗯嗯",
        "好的",
        "好",
        "可以",
        "行",
        "没问题",
        "确认",
    }


def _infer_onboarding_next_step(collected_info: dict[str, str]) -> int:
    ordered_fields = [
        "story_concept",
        "genre_audience",
        "core_hook",
        "target_length",
        "must_keep",
    ]
    completed = sum(1 for field in ordered_fields if str(collected_info.get(field, "")).strip())
    return min(completed + 1, 5)


def _extract_candidate_genre(raw_content: str) -> str:
    text = (raw_content or "").replace("\n", " ")
    patterns = [
        r"更偏(?:向)?([^，。！？?]{2,24})，?对吗",
        r"听起来你的故事更偏(?:向)?([^，。！？?]{2,24})",
        r"像是一部([^，。！？?]{2,24})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip("：:，,。. ")
    return ""


# DEPRECATED: 旧的 collected_info 合并逻辑，已被 understanding 替代
# 保留用于向后兼容，新代码不要使用
def _merge_onboarding_collected_info(
    previous_collected_info: dict[str, str] | None,
    current_step: int | None,
    messages: list[dict],
    raw_content: str,
) -> dict[str, str]:
    collected = {
        key: str(value).strip()
        for key, value in (previous_collected_info or {}).items()
        if str(value).strip()
    }
    step_to_field = {
        1: "story_concept",
        2: "genre_audience",
        3: "core_hook",
        4: "target_length",
        5: "must_keep",
    }
    latest_user_text = ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            latest_user_text = str(msg.get("content", "")).strip()
            if latest_user_text:
                break

    active_step = int(current_step or _infer_onboarding_next_step(collected))
    field = step_to_field.get(active_step)
    if field and latest_user_text and not _is_brief_confirmation(latest_user_text):
        collected[field] = latest_user_text
    elif field == "genre_audience" and not collected.get("genre_audience"):
        candidate = _extract_candidate_genre(raw_content)
        if candidate:
            collected["genre_audience"] = candidate

    if not collected.get("story_concept"):
        first_long_user = next(
            (
                str(msg.get("content", "")).strip()
                for msg in messages
                if isinstance(msg, dict)
                and msg.get("role") == "user"
                and len(str(msg.get("content", "")).strip()) >= 20
            ),
            "",
        )
        if first_long_user:
            collected["story_concept"] = first_long_user

    return collected


def _build_onboarding_fallback_response(
    messages: list[dict],
    raw_content: str,
    previous_collected_info: dict[str, str] | None = None,
    current_step: int | None = None,
) -> dict:
    collected_info = _merge_onboarding_collected_info(
        previous_collected_info,
        current_step,
        messages,
        raw_content,
    )
    step = _infer_onboarding_next_step(collected_info)
    reply = _strip_code_fences(raw_content)
    forbidden_leaks = [
        "根据对话历史推断出的 collected_info 默认值",
        "根据对话历史推断出的 step 默认值",
        "当前原始回复",
    ]
    if any(marker in reply for marker in forbidden_leaks):
        reply = ""
    if not reply:
        fallback_questions = {
            1: "先和我说说，你想写一个怎样的故事？主角是什么样的人，大概会发生什么？",
            2: "这个故事的核心感觉我已经抓到了。它更偏男频、女频、轻小说、悬疑，还是其他方向？",
            3: "这个设定已经有亮点了。你最希望读者先被哪一点吸引住，是主角身份、机制爽点，还是世界观反转？",
            4: "接下来我帮你定一下体量。你更想把它写成短篇、中篇、长篇，还是五百章起的超长篇？",
            5: "最后再确认一下，有没有哪些设定是你绝对不希望被改掉的？比如结局真相、角色关系或世界规则。",
        }
        reply = fallback_questions.get(step, fallback_questions[1])
    return {
        "reply": reply,
        "collected_info": collected_info,
        "step": step,
        "total_steps": 5,
        "is_complete": step >= 5 and bool(str(collected_info.get("must_keep", "")).strip()),
    }


async def _repair_onboarding_response(
    raw_content: str,
    messages: list[dict],
    api_key: str | None = None,
) -> dict:
    fallback = _build_onboarding_fallback_response(messages, raw_content)
    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 JSON 修复助手。"
                    "请把用户提供的引导建书 AI 回复，重写成一个严格有效的 JSON 对象。"
                    "禁止输出 Markdown、解释、代码块或额外文本。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请基于这段 AI 回复内容，输出一个 JSON 对象，字段必须为 "
                    '{"reply": "...", "collected_info": {...}, "step": 1, "total_steps": 5, "is_complete": false}。'
                    f"\n当前原始回复：\n{raw_content}\n"
                    f"\n根据对话历史推断出的 collected_info 默认值：\n{json.dumps(fallback['collected_info'], ensure_ascii=False)}\n"
                    f"根据对话历史推断出的 step 默认值：{fallback['step']}\n"
                    "如果原始回复里没有足够信息，请沿用这些默认值。"
                ),
            },
        ],
        "stream": False,
        "max_tokens": 4096,
    }
    payload = _apply_runtime_params(payload)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
    resp.raise_for_status()
    data = _response_json(resp, context="DeepSeek")
    content = data["choices"][0]["message"]["content"]

    result = _extract_json_object(content)
    collected_info = result.get("collected_info")
    if not isinstance(collected_info, dict):
        result["collected_info"] = fallback["collected_info"]
    result["reply"] = _strip_code_fences(str(result.get("reply", ""))) or fallback["reply"]
    result["step"] = int(result.get("step", fallback["step"]))
    result["total_steps"] = int(result.get("total_steps", 5))
    result["is_complete"] = bool(result.get("is_complete", fallback["is_complete"]))
    return result


# ─── Framework service functions ───────────────────────────


def _as_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _build_chapter_outline_scope(outline: dict, current_chapter_number: int) -> dict[str, Any]:
    """为正文生成提取当前章节边界，避免模型偷用后续章节事件。"""
    if not isinstance(outline, dict) or current_chapter_number <= 0:
        return {}

    acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
    chapter_cards: list[dict[str, Any]] = []
    for act_index, act in enumerate(acts, start=1):
        if not isinstance(act, dict):
            continue
        act_label = act.get("act", act_index)
        chapters = act.get("chapters") if isinstance(act.get("chapters"), list) else []
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter_number = _as_positive_int(item.get("chapter_number"))
            if chapter_number is None:
                continue
            chapter_cards.append(
                {
                    "chapter_number": chapter_number,
                    "title": str(item.get("title") or "").strip(),
                    "act": item.get("act", act_label),
                    "summary": str(item.get("summary") or "").strip(),
                    "goal": str(item.get("goal") or "").strip(),
                    "conflict": str(item.get("conflict") or "").strip(),
                    "hook": str(item.get("hook") or "").strip(),
                    "payoff": str(item.get("payoff") or "").strip(),
                    "highlight": str(item.get("highlight") or "").strip(),
                }
            )

    if not chapter_cards:
        return {}

    chapter_cards.sort(key=lambda item: item["chapter_number"])
    current = next((item for item in chapter_cards if item["chapter_number"] == current_chapter_number), None)
    previous = [
        {
            "chapter_number": item["chapter_number"],
            "title": item.get("title"),
            "summary": item.get("summary"),
        }
        for item in chapter_cards
        if item["chapter_number"] < current_chapter_number
    ][-2:]
    upcoming = [
        {
            "chapter_number": item["chapter_number"],
            "title": item.get("title"),
            "summary": item.get("summary"),
        }
        for item in chapter_cards
        if item["chapter_number"] > current_chapter_number
    ][:6]

    scope: dict[str, Any] = {
        "current_chapter_number": current_chapter_number,
        "current_chapter_card": current or {},
        "previous_chapters_for_continuity": previous,
        "future_chapters_for_boundary_only": upcoming,
        "boundary_rule": "只能写 current_chapter_card 内的本章事件；future_chapters_for_boundary_only 仅用于防止预支后文，禁止提前完成其中任何事件。",
    }
    return scope


_BOUNDARY_TERM_STOPWORDS = {
    "本章", "主角", "故事", "剧情", "世界", "发现", "面对", "开始", "通过", "进行", "获得",
    "关键", "核心", "冲突", "目标", "线索", "行动", "危机", "选择", "能力", "资源", "身份",
    "人物", "关系", "铺垫", "推进", "进入", "解决", "完成", "引出", "展现", "揭示", "明确",
    "活动范围", "官方开放", "方开放的", "开放的", "范围", "地方", "东西", "里面",
}

_BOUNDARY_STRONG_SHORT_TERMS = {
    "擂台", "秘境", "荒域", "异兽", "灵草", "灵药", "奖金", "赌斗", "试炼", "遗迹",
}


def _is_strong_boundary_term(term: str) -> bool:
    """判断词项是否足以代表后续章节核心事件，而非普通动作短语。"""
    if term in _BOUNDARY_STRONG_SHORT_TERMS:
        return True
    if len(term) < 4:
        return False
    return any(core in term for core in _BOUNDARY_STRONG_SHORT_TERMS)


def _compact_boundary_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_compact_boundary_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_compact_boundary_text(item) for item in value)
    return str(value or "")


def _boundary_terms_from_text(text: str) -> set[str]:
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", text or "")
    terms: set[str] = set()
    for raw in cleaned.split():
        token = raw.strip()
        if not token:
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", token):
            if len(token) >= 4:
                terms.add(token)
            continue
        if len(token) >= 3 and token not in _BOUNDARY_TERM_STOPWORDS:
            terms.add(token[:16])
        if len(token) >= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", token):
            for size in (4, 3, 2):
                for index in range(0, len(token) - size + 1):
                    term = token[index:index + size]
                    if term not in _BOUNDARY_TERM_STOPWORDS:
                        terms.add(term)
    return terms


def _extract_chapter_scope_from_text(text: str) -> dict[str, Any]:
    marker = "章节大纲边界:"
    if not text or marker not in text:
        return {}
    start = text.find(marker) + len(marker)
    fragment = text[start:].lstrip()
    try:
        scope, _ = json.JSONDecoder().raw_decode(fragment)
    except Exception:
        return {}
    return scope if isinstance(scope, dict) else {}


def _chapter_scope_from_context(story_context: dict) -> dict[str, Any]:
    if not isinstance(story_context, dict):
        return {}
    outline = story_context.get("outline")
    current_chapter = story_context.get("current_chapter") if isinstance(story_context.get("current_chapter"), dict) else {}
    chapter_number = _as_positive_int(current_chapter.get("chapter_number") if current_chapter else None)
    if isinstance(outline, dict) and chapter_number:
        return _build_chapter_outline_scope(outline, chapter_number)
    return {}


def _detect_chapter_boundary_issues(content: str, chapter_scope: dict[str, Any]) -> list[str]:
    """检测正文是否疑似提前写完后续章节卡中的核心事件。"""
    if not content or not isinstance(chapter_scope, dict):
        return []
    future_cards = chapter_scope.get("future_chapters_for_boundary_only")
    if not isinstance(future_cards, list) or not future_cards:
        return []

    allowed_text = _compact_boundary_text(chapter_scope.get("current_chapter_card"))
    allowed_text += " " + _compact_boundary_text(chapter_scope.get("previous_chapters_for_continuity"))
    allowed_terms = _boundary_terms_from_text(allowed_text)
    future_term_counts: dict[str, int] = {}
    card_terms_cache: list[tuple[dict, set[str]]] = []
    for card in future_cards[:6]:
        if not isinstance(card, dict):
            continue
        source_text = _compact_boundary_text({
            "title": card.get("title"),
            "summary": card.get("summary"),
            "goal": card.get("goal"),
            "conflict": card.get("conflict"),
            "payoff": card.get("payoff"),
            "highlight": card.get("highlight"),
        })
        terms = _boundary_terms_from_text(source_text) - allowed_terms
        card_terms_cache.append((card, terms))
        for term in terms:
            future_term_counts[term] = future_term_counts.get(term, 0) + 1

    issues: list[str] = []
    for card, raw_terms in card_terms_cache:
        terms = sorted(
            [term for term in raw_terms if future_term_counts.get(term, 0) < 3],
            key=len,
            reverse=True,
        )
        matched = [term for term in terms if term and term in content]
        strong_matches = [term for term in matched if _is_strong_boundary_term(term)]
        if strong_matches:
            chapter_label = card.get("chapter_number") or "后续"
            title = str(card.get("title") or "").strip()
            shown = "、".join(strong_matches[:4])
            issues.append(f"疑似预支第{chapter_label}章《{title}》：{shown}")
        if len(issues) >= 5:
            break
    return issues


def _build_story_snapshot(story_context: dict) -> str:
    """Build a textual snapshot of the current story context for regeneration prompts."""
    parts = []
    story_bible = story_context.get("story_bible")
    if isinstance(story_bible, dict) and story_bible:
        creative_brief = story_bible.get("creative_brief")
        writing_guidance = story_bible.get("writing_guidance")
        if creative_brief:
            parts.append(f"作品圣经-创意理解: {json.dumps(creative_brief, ensure_ascii=False)}")
        if writing_guidance:
            parts.append(f"作品圣经-写作指导: {json.dumps(writing_guidance, ensure_ascii=False)}")
        import_guidance = story_bible.get("import_guidance")
        if isinstance(import_guidance, dict) and import_guidance:
            parts.append(f"导入作品作者约束: {json.dumps(import_guidance, ensure_ascii=False)}")
        # 拆书引用数据（模型支持 1M token，不再截断）
        learned_techniques = story_bible.get("learned_techniques")
        if isinstance(learned_techniques, list) and learned_techniques:
            parts.append(f"参考写作手法: {json.dumps(learned_techniques, ensure_ascii=False)}")
        reference_plots = story_bible.get("reference_plots")
        if isinstance(reference_plots, list) and reference_plots:
            parts.append(f"参考剧情模式: {json.dumps(reference_plots, ensure_ascii=False)}")
        reference_rhythm = story_bible.get("reference_rhythm")
        if isinstance(reference_rhythm, dict) and reference_rhythm:
            parts.append(f"参考节奏控制: {json.dumps(reference_rhythm, ensure_ascii=False)}")
        reference_emotion_modules = story_bible.get("reference_emotion_modules")
        if isinstance(reference_emotion_modules, dict) and reference_emotion_modules:
            parts.append(f"参考情绪模块: {json.dumps(reference_emotion_modules, ensure_ascii=False)}")
        reference_author_profile = story_bible.get("reference_author_profile")
        if isinstance(reference_author_profile, dict) and reference_author_profile:
            profile_parts = extract_author_profile_sections(reference_author_profile)
            parts.extend(profile_parts)
        reference_author_report = story_bible.get("reference_author_report")
        if isinstance(reference_author_report, str) and reference_author_report.strip():
            highlights = extract_report_highlights(reference_author_report)
            parts.append(f"作者画像参考报告（核心要点）:\n{highlights}")
        reference_style_samples = story_bible.get("reference_style_samples")
        if isinstance(reference_style_samples, list) and reference_style_samples:
            parts.append(f"作者原文风格示例: {json.dumps(reference_style_samples, ensure_ascii=False)}")
    if story_context.get("tags"):
        parts.append(f"现有标签: {json.dumps(story_context['tags'], ensure_ascii=False)}")
    if story_context.get("characters"):
        parts.append(f"现有角色: {json.dumps(story_context['characters'], ensure_ascii=False)}")
    outline = story_context.get("outline")
    current_chapter = story_context.get("current_chapter") if isinstance(story_context.get("current_chapter"), dict) else {}
    current_chapter_number = _as_positive_int(current_chapter.get("chapter_number") if current_chapter else None)
    if isinstance(outline, dict) and outline:
        if current_chapter_number:
            outline_scope = _build_chapter_outline_scope(outline, current_chapter_number)
            if outline_scope:
                parts.append(f"章节大纲边界: {json.dumps(outline_scope, ensure_ascii=False)}")
        else:
            parts.append(f"现有大纲: {json.dumps(outline, ensure_ascii=False)}")
    if story_context.get("description"):
        parts.append(f"故事描述: {story_context['description']}")
    # Inject story_memory_compact (continuity memory)
    story_memory_compact = story_context.get("story_memory_compact") if isinstance(story_context, dict) else None
    if not isinstance(story_memory_compact, dict) or not story_memory_compact:
        story_memory = story_context.get("story_memory") if isinstance(story_context, dict) else {}
        story_memory_compact = build_story_memory_compact(story_memory)
    if isinstance(story_memory_compact, dict) and story_memory_compact:
        parts.append(f"作品连续性记忆: {json.dumps(story_memory_compact, ensure_ascii=False)}")
    result = "\n\n".join(parts)
    if estimate_tokens(result) > TOKEN_COMPRESS_THRESHOLD:
        parts = compress_context_parts_if_needed(parts, full_context=story_context, current_chapter_number=None)
        result = "\n\n".join(parts)
    return result


def _build_framework_runtime_brief(story_context: dict, include_outline_json: bool = True) -> str:
    parts: list[str] = []

    stats = story_context.get("framework_stats")
    if isinstance(stats, dict) and stats:
        parts.append(f"当前框架统计: {json.dumps(stats, ensure_ascii=False)}")

    user_instruction = str(story_context.get("user_instruction") or "").strip()
    if user_instruction:
        parts.append(f"本轮用户指令: {user_instruction}")

    bible_compact = story_context.get("story_bible_compact")
    if not isinstance(bible_compact, dict) or not bible_compact:
        story_bible = story_context.get("story_bible")
        bible_compact = build_story_bible_compact(story_bible)
    if isinstance(bible_compact, dict) and bible_compact:
        parts.append(f"作品圣经紧凑摘要: {json.dumps(bible_compact, ensure_ascii=False)}")

    story_memory_compact = story_context.get("story_memory_compact")
    if isinstance(story_memory_compact, dict) and story_memory_compact:
        parts.append(f"作品连续性记忆: {json.dumps(story_memory_compact, ensure_ascii=False)}")

    tags = story_context.get("tags")
    if isinstance(tags, dict) and tags:
        parts.append(f"现有标签: {json.dumps(tags, ensure_ascii=False)}")

    characters = story_context.get("characters")
    if isinstance(characters, list) and characters:
        compact_characters = []
        for item in characters:
            if not isinstance(item, dict):
                continue
            record = {
                "name": str(item.get("name") or "").strip(),
                "role": str(item.get("role") or "").strip(),
            }
            for key in ("arc", "relationships"):
                if item.get(key):
                    record[key] = item.get(key)
            compact_characters.append(record)
        if compact_characters:
            parts.append(f"现有角色摘要: {json.dumps(compact_characters, ensure_ascii=False)}")

    outline_compact = story_context.get("outline_compact")
    if (not isinstance(outline_compact, dict) or not outline_compact) and isinstance(story_context.get("outline"), dict):
        outline = story_context.get("outline") or {}
        acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
        extracted = []
        for index, act in enumerate(acts, start=1):
            if not isinstance(act, dict):
                continue
            act_label = act.get("act", index)
            act_chapters = act.get("chapters") if isinstance(act.get("chapters"), list) else []
            for item in act_chapters:
                if not isinstance(item, dict):
                    continue
                chapter_number = item.get("chapter_number")
                title = str(item.get("title") or "").strip()
                if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                    continue
                extracted.append(
                    {
                        "chapter_number": chapter_number,
                        "title": title,
                        "act": item.get("act", act_label),
                        "summary": str(item.get("summary") or "").strip(),
                    }
                )
        outline_compact = {
            "stage_count": len(acts),
            "chapter_count": len(extracted),
            "acts": [
                {
                    "act": act.get("act", index + 1),
                    "title": str(act.get("title") or act.get("name") or "").strip(),
                    "summary": str(act.get("summary") or "").strip(),
                }
                for index, act in enumerate(acts)
                if isinstance(act, dict)
            ],
            "recent_chapter_cards": [
                {
                    "chapter_number": item.get("chapter_number"),
                    "title": item.get("title"),
                    "act": item.get("act"),
                    "summary": str(item.get("summary") or "").strip(),
                }
                for item in extracted
            ],
        }
    if isinstance(outline_compact, dict) and outline_compact:
        parts.append(f"当前大纲紧凑摘要: {json.dumps(outline_compact, ensure_ascii=False)}")

    outline = story_context.get("outline")
    if include_outline_json and isinstance(outline, dict) and outline:
        serialized_outline = json.dumps(outline, ensure_ascii=False)
        parts.append(f"当前大纲JSON: {serialized_outline}")

    description = str(story_context.get("description") or "").strip()
    if description:
        parts.append(f"故事描述: {description}")

    result = "\n\n".join(parts)
    if estimate_tokens(result) > TOKEN_COMPRESS_THRESHOLD:
        parts = compress_context_parts_if_needed(parts, full_context=story_context, current_chapter_number=None)
        result = "\n\n".join(parts)
    return result


def _build_story_snapshot_tiered(story_context: dict, tier: str = "auto") -> str:
    """构建故事快照文本。当前模型支持 1M token，不再需要分层截断。"""
    return _build_story_snapshot(story_context)


async def regenerate_tags(story_context: dict, api_key: str | None = None, system_prompt: str | None = None) -> dict:
    """Regenerate only the tags based on existing story context.

    Args:
        system_prompt: Custom system prompt (from DB). Empty string falls back to basic instruction.
    """
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成标签（tags）。

{snapshot}

请严格输出只包含 tags 的JSON对象，格式：{{"tags": {{"type": "...", "theme": "...", "style": "...", "audience": "..."}}}}"""

    system_content = system_prompt or "你是小说策划编辑。基于已有的故事框架，输出仅包含 tags 的JSON对象。"

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }
    payload = _apply_runtime_params(payload)

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("tags", result)
    except ValueError as e:
        raise ValueError(f"标签重新生成失败: {e}")


async def regenerate_characters_with_variance(story_context: dict, api_key: str | None = None, system_prompt: str | None = None) -> dict:
    """Regenerate characters with explicit personality variance constraints."""
    snapshot = _build_story_snapshot_tiered(story_context, "auto")
    user_prompt = f"""请基于以下故事框架信息，重新生成一组更贴合大纲的人物设定（characters）。

{snapshot}

硬性要求：
1. 只输出 JSON，对象格式为 {{"characters": [{{"name": "...", "role": "...", "big_five": {{}}, "arc": {{}}, "relationships": []}}]}}。
2. 每个角色的 `big_five` 必须完整包含 `openness`、`conscientiousness`、`extraversion`、`agreeableness`、`neuroticism` 五个维度，分值为 1-10。
3. 每个角色的大五人格必须依据其人物身份、剧情功能、主要欲望、核心缺陷和外在行为单独设计。
4. 不要给所有角色使用平均值、模板值或中庸值，禁止出现"几乎所有角色都 50/50/50/50/50"这一类结果。
5. 主角、盟友、导师、反派、幕后势力至少要在 2-3 个维度上形成明显反差，并且能从数值上看出差异。
6. 数值要能支撑大纲里的人设。比如谨慎克制型人物不应外向性过高，偏执控制型人物不应所有维度都温和。
"""

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": system_prompt or (
                    "你是小说人物设定编辑。你的任务不是平均分配性格数值，而是根据故事大纲和人物功能，"
                    "生成彼此有明显差异、能够支撑剧情的角色设定。只输出包含 characters 的 JSON 对象。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("characters", result)
    except ValueError as e:
        raise ValueError(f"Character regeneration with variance failed: {e}")


async def generate_character_profiles_from_framework(story_context: dict, api_key: str | None = None, system_prompt: str | None = None) -> str:
    """Generate manga-facing appearance cards from framework characters."""
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是当前故事的框架信息，请把其中的角色设定扩写成可直接用于漫画分镜与生图的固定角色外貌卡。

{snapshot}

要求：
1. 只输出纯文本，不要输出 JSON，不要解释。
2. 每个角色单独成段，必须覆盖当前故事里的所有核心角色。
3. 每个角色都要包含：角色名、身份定位、三视图特征（正面/侧面/背面，各视角关键外貌差异）、外貌描述、发型发色、眼睛特征、体型特征、服装细则（上装/下装/外套/鞋子，每项具体款式材质颜色）、配饰清单（头饰/首饰/武器/道具，佩戴位置和样式）、表情集（常态/高兴/愤怒/悲伤，每种表情的具体变化特征）、动作习惯、神态气质、漫画绘制注意点。
4. 要把小说角色性格映射成稳定外貌特征，例如冷静的人更克制、张扬的人更有攻击性视觉符号。
5. 描述必须具体、可视化、便于后续所有章节保持角色一致。
6. 如果原始框架没写明某个外貌细节，请基于题材和角色定位合理补全，但保持统一风格。

输出格式示例：
角色名：林墨
身份定位：主角
三视图特征：
  正面：身高约175cm的青少年体型，肩膀略宽，站姿挺拔
  侧面：鼻梁挺直，下颌线条清晰，黑色短发脑后微翘
  背面：后颈露出黑色短发末梢，肩胛骨轮廓隐约可见，常背单肩挎包
外貌描述：五官清秀略带英气，肤色偏白，眉形锋锐
发型发色：黑色短发，刘海向右偏分，发尾微翘
眼睛特征：深褐色杏仁眼，眼尾微上挑，注视时目光锐利
体型特征：青少年偏瘦体型，身高175cm，肩宽腰窄
服装细则：
  上装：白色立领制服衬衫，袖口收拢
  下装：黑色直筒长裤，裤脚微收
  外套：深蓝色短款立领外套，左胸有银色徽章
  鞋子：黑色系带短靴，鞋底略厚
配饰清单：
  头饰：无
  首饰：左手腕戴一条黑色编织手绳
  武器/道具：腰间挂一把短剑，剑鞘为深棕色皮革
表情集：
  常态：嘴唇微抿，眼神平静专注
  高兴：嘴角微微上扬，眼神柔和
  愤怒：眉头紧锁，眼神凌厉，牙关微咬
  悲伤：眉毛下垂，眼神低垂，嘴唇微颤
动作习惯：思考时右手托下巴，紧张时左手握剑柄
神态气质：沉静内敛，行动果断，带有少年侠客的清冷感
漫画绘制注意点：面部务必保持杏仁眼和锋锐眉形，短靴不可省略，深蓝色外套为标志性服装
"""

    char_system_prompt = system_prompt or ""
    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": char_system_prompt,
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        return str(data["choices"][0]["message"]["content"] or "").strip()


async def generate_character_profiles_from_content(chapter_content: str, api_key: str | None = None) -> str:
    """从章节正文内容中提取角色外貌描述，生成角色卡。"""
    if not chapter_content or not chapter_content.strip():
        return ""

    # 截取前3000字符，避免token过长
    content_excerpt = chapter_content[:3000]

    user_prompt = f"""以下是小说的章节正文内容，请从中分析并提取所有出现的角色，为每个角色生成可用于漫画分镜与生图的固定角色外貌卡。

章节内容：
{content_excerpt}

要求：
1. 只输出纯文本，不要输出 JSON，不要解释。
2. 从正文中提取所有出现的角色名，为每个角色生成外貌卡。
3. 每个角色都要包含：角色名、身份定位、三视图特征（正面/侧面/背面，各视角关键外貌差异）、外貌描述、发型发色、眼睛特征、体型特征、服装细则（上装/下装/外套/鞋子，每项具体款式材质颜色）、配饰清单（头饰/首饰/武器/道具，佩戴位置和样式）、表情集（常态/高兴/愤怒/悲伤，每种表情的具体变化特征）、动作习惯、神态气质、漫画绘制注意点。
4. 如果正文中没有明确描述某个外貌细节，请基于上下文和角色定位合理推断补全。
5. 描述必须具体、可视化、便于后续章节保持角色一致。
6. 如果正文中有多个角色，按出场顺序排列。

输出格式示例：
角色名：林墨
身份定位：主角
三视图特征：
  正面：身高约175cm的青少年体型，肩膀略宽，站姿挺拔
  侧面：鼻梁挺直，下颌线条清晰，黑色短发脑后微翘
  背面：后颈露出黑色短发末梢，肩胛骨轮廓隐约可见，常背单肩挎包
外貌描述：五官清秀略带英气，肤色偏白，眉形锋锐
发型发色：黑色短发，刘海向右偏分，发尾微翘
眼睛特征：深褐色杏仁眼，眼尾微上挑，注视时目光锐利
体型特征：青少年偏瘦体型，身高175cm，肩宽腰窄
服装细则：
  上装：白色立领制服衬衫，袖口收拢
  下装：黑色直筒长裤，裤脚微收
  外套：深蓝色短款立领外套，左胸有银色徽章
  鞋子：黑色系带短靴，鞋底略厚
配饰清单：
  头饰：无
  首饰：左手腕戴一条黑色编织手绳
  武器/道具：腰间挂一把短剑，剑鞘为深棕色皮革
表情集：
  常态：嘴唇微抿，眼神平静专注
  高兴：嘴角微微上扬，眼神柔和
  愤怒：眉头紧锁，眼神凌厉，牙关微咬
  悲伤：眉毛下垂，眼神低垂，嘴唇微颤
动作习惯：思考时右手托下巴，紧张时左手握剑柄
神态气质：沉静内敛，行动果断，带有少年侠客的清冷感
漫画绘制注意点：面部务必保持杏仁眼和锋锐眉形，短靴不可省略，深蓝色外套为标志性服装
"""

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业漫画角色设定师，擅长从小说正文内容中分析角色特征，"
                    "并转成稳定、具体、可复用的角色外貌卡。"
                    "你输出的内容会直接作为分镜和生图提示词的一部分，所以必须高度具体、统一、可视化。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        return str(data["choices"][0]["message"]["content"] or "").strip()


# FRAMEWORK_SYSTEM_PROMPT 种子数据已移至 main.py _seed_system_prompts


def _long_form_framework_rules() -> str:
    return """
1. 任何大纲生成/调整都只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和关键里程碑，不要求输出每章明细。绝对禁止一次性输出所有卷的章节规划。
2. 默认按长篇节奏规划（100章以上潜力），不要在前 10 章内写完主要矛盾。
3. 核心冲突至少预留三次升级空间，每次升级改变角色处境和故事格局，但后续升级只需在幕级描述中标明方向。
4. 终局方向可以标注，但不要强制写出结局——保留开放扩展空间，让作者后续逐步完善。
5. 章节规划体现「铺垫→升级→扩盘→反转→决战→余波」节奏，但只在第一个阶段用满章节明细。
6. 角色成长渐进，不要把人物弧光一夜完成。
7. 世界观揭秘分层递进，每次只给读者部分真相。
8. 感情线、友情线、敌对线都要有独立的发展曲线。
9. 每章必须标注 summary, goal, conflict, hook, payoff, highlight（缺一不可），这些是 AI 生成正文时的唯一叙事指南。缺少任何一个字段都会导致正文偏离大纲。
10. 后续阶段不要强制写出终局结局——用 serial_strategy 标注故事发展方向即可。
""".strip()


def _medium_form_framework_rules() -> str:
    return """
1. 任何大纲生成/调整都只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和方向，不要求输出每章明细。绝对禁止一次性输出所有卷的章节规划。
2. 核心冲突升级 2-3 次，每次升级改变角色处境和故事格局，后续升级在幕级描述中标明方向即可。
3. 阶段结构 3-5 个，每个阶段标注核心冲突方向和关键情节点。
4. 阶段间要有明确的转折点，不能平铺直叙地过渡。
5. 角色成长渐进，每个阶段角色至少有一个关键变化。
6. 世界观分 2-3 层揭秘，不要一次性交代完毕。
7. 中段要保留升级空间和悬念递进，不能让故事在中段塌陷。
8. 感情线、友情线、敌对线都要有独立的发展曲线。
9. 每章必须标注 summary, goal, conflict, hook, payoff, highlight（缺一不可），这些是 AI 生成正文时的唯一叙事指南。缺少任何一个字段都会导致正文偏离大纲。
10. 不要强制写出终局结局——用 serial_strategy 标注故事发展方向即可。
""".strip()


def _short_form_framework_rules() -> str:
    return """
1. 全书控制在 10-30 章以内，节奏紧凑，不要拖沓。
2. 聚焦单一核心冲突，不要引入过多支线和副线。
3. 阶段结构 2-3 个即可：建立冲突 → 升级/反转 → 高潮/解决。
4. 高密度情节推进——每一章都必须有明确的叙事功能（推进剧情/揭示真相/制造转折），不能有纯过渡章。
5. 世界观简洁明了，只保留服务核心冲突的必要设定，不要过度展开。
6. 角色精简（3-5 个核心角色），每个角色都要有明确的叙事功能。
7. 第二章前必须进入核心冲突，不要用太多篇幅铺垫。
8. 中段要有一个关键反转或真相揭示，推动故事走向高潮。
9. 结局要紧凑有力，回收所有主要伏笔，不要拖尾。
10. 每章必须标注 summary, goal, conflict, hook, payoff, highlight（缺一不可），确保全书节奏紧凑、每章有明确叙事功能。
""".strip()


def _infer_story_length(story_context: dict, description: str = "", messages: list | None = None) -> str:
    """从故事上下文、用户描述、对话消息中推断篇幅类型：short / medium / long。

    优先级：story_bible > description 文本 > messages 文本 > story_context 字段 > 默认 long。
    story_bible 优先是因为它代表用户经过引导建书确认的明确选择。
    """
    if not isinstance(story_context, dict):
        story_context = {}

    def _classify_length_text(text: str) -> str | None:
        """从文本中推断篇幅类型，返回 None 表示无法判断。"""
        t = text.strip().lower()
        if not t:
            return None
        # 明确关键词匹配
        if any(k in t for k in ("短篇", "短", "short")):
            return "short"
        if any(k in t for k in ("中篇", "中", "medium")):
            return "medium"
        if any(k in t for k in ("长篇", "超长", "long")):
            return "long"
        # 数字匹配：提取第一个数字进行范围判断
        import re
        nums = re.findall(r"\d+", t)
        if nums:
            n = int(nums[0])
            if n <= 30:
                return "short"
            if n <= 100:
                return "medium"
            return "long"
        return None

    # 优先级 1：从 story_bible 中提取（代表用户确认过的目标篇幅）
    story_bible = story_context.get("story_bible")
    if isinstance(story_bible, dict):
        creative_brief = story_bible.get("creative_brief")
        if isinstance(creative_brief, dict):
            target = str(creative_brief.get("serial_length_target") or "").strip()
            result = _classify_length_text(target)
            if result:
                return result
        raw_input = story_bible.get("raw_input")
        if isinstance(raw_input, dict):
            raw_goal = str(raw_input.get("raw_length_goal") or "").strip()
            result = _classify_length_text(raw_goal)
            if result:
                return result

    # 优先级 2：从用户描述文本中提取（用户直接在描述中写明篇幅）
    result = _classify_length_text(description)
    if result:
        return result

    # 优先级 3：从对话消息中提取（用户在聊天中提到篇幅要求）
    if isinstance(messages, list):
        # 从后往前搜索，用户最新消息的篇幅要求优先
        for msg in reversed(messages):
            if isinstance(msg, dict):
                content = str(msg.get("content") or "").strip()
                result = _classify_length_text(content)
                if result:
                    return result

    # 优先级 4：从 story_context 直接字段提取
    for key in ("target_length", "story_length"):
        val = str(story_context.get(key) or "").strip()
        result = _classify_length_text(val)
        if result:
            return result

    return "long"


def _framework_rules_for_length(story_length: str) -> str:
    """根据篇幅类型返回对应的创作规则。"""
    if story_length == "short":
        return _short_form_framework_rules()
    if story_length == "medium":
        return _medium_form_framework_rules()
    return _long_form_framework_rules()


def _framework_messages_with_long_form(system_text: str, user_text: str, story_length: str = "long") -> list[dict]:
    return [
        {"role": "system", "content": system_text},
        {"role": "system", "content": _framework_rules_for_length(story_length)},
        {"role": "user", "content": user_text},
    ]


async def generate_framework(
    description: str,
    api_key: str | None = None,
    required_min_chapters: int | None = None,
    story_bible: dict | None = None,
    story_context: dict | None = None,
    launch_ready_required: bool = False,
    quality_feedback: list[str] | None = None,
    system_prompt: str | None = None,
    story_length: str | None = None,
) -> dict:
    """Generate a complete story framework with flexible stage structure.

    Args:
        system_prompt: Custom system prompt, None uses built-in default.
        story_length: 篇幅类型 short/medium/long，None 自动推断。"""
    # 推断篇幅类型
    effective_length = story_length or _infer_story_length(story_context or {"story_bible": story_bible})

    min_chapter_requirement = (
        f"\n7. `chapters` 的实际返回数量必须不少于 {required_min_chapters} 章，不能只口头说明会扩展。"
        if required_min_chapters and required_min_chapters >= 20
        else ""
    )
    story_bible_hint = ""
    if isinstance(story_context, dict) and story_context:
        context_hint = _build_framework_runtime_brief(story_context, include_outline_json=False)
        if context_hint:
            story_bible_hint = (
                "\n生成时必须优先遵守以下运行时上下文，尤其是作品圣经紧凑摘要中的定位、悬念、篇幅、禁区与必保留设定：\n"
                + context_hint
            )
    elif isinstance(story_bible, dict) and story_bible:
        context_hint = _build_framework_runtime_brief(
            {
                "description": description,
                "story_bible": story_bible,
            },
            include_outline_json=False,
        )
        if context_hint:
            story_bible_hint = (
                "\n生成时必须优先遵守以下运行时上下文，尤其是作品圣经紧凑摘要中的定位、悬念、篇幅、禁区与必保留设定：\n"
                + context_hint
            )
    launch_ready_hint = ""
    if launch_ready_required:
        if effective_length == "short":
            launch_ready_hint = """
9. 这次是"平台可发布级开书框架"生成，必须达到开书可用标准，而不是只给概念草稿。
10. 短篇必须一次性给出完整的章节规划（10-30 章），不能留待后续扩展。
11. 每章必须尽量细到能直接写，补齐 `summary`，并给出 `goal`、`conflict`、`hook`、`payoff`、`highlight`。
12. `outline` 至少要有 2 个主要阶段，明确开篇阶段和高潮/结局阶段。
13. `outline.serial_strategy` 至少给出 `positioning`、`opening_hook`、`first_3_chapter_hook`。
14. 第 1 章必须有强钩子，快速进入核心冲突。
""".strip()
        else:
            launch_ready_hint = """
9. 这次是"平台可发布级开书框架"生成，必须达到开书可用标准，而不是只给概念草稿。
10. 初始大纲只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和方向，不要求输出每章明细。
11. 章节必须尽量细到能直接写，每章要补齐 `summary`，并给出 `goal`、`conflict`、`hook`、`payoff`、`highlight`。
12. `outline` 至少要有 2 个以上主要阶段，明确开书阶段和后续扩展阶段；如果能拆到 3 个以上更好。
13. `outline.serial_strategy` 至少完整给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`，其余字段尽量补充。
14. 第 1 章必须有强钩子，第 3 章前要建立明确追读动力，第 10 章要有小高潮。
15. 不要强制写出终局结局——用 `serial_strategy.late_game_direction` 标注故事发展方向即可，保留开放扩展空间。
""".strip()
    quality_feedback_hint = ""
    if quality_feedback:
        quality_feedback_hint = "\n上一版未达标的问题如下，请逐项修正后再输出：\n- " + "\n- ".join(quality_feedback)

    # 根据篇幅类型生成不同的 user_prompt
    if effective_length == "short":
        user_prompt = f"""请根据以下故事描述，生成一版适合短篇创作的完整小说框架：

{description}
{story_bible_hint}

额外要求：
1. `outline` 覆盖完整主线，阶段结构 2-3 个：建立冲突 → 升级/反转 → 高潮/解决。
2. `chapters` 总数控制在 10-30 章，每章都要有明确的叙事功能，不要有纯过渡章。
3. 节奏紧凑——第二章前进入核心冲突，中段有关键反转，结尾回收所有主要伏笔。
4. 每个 `chapters` 条目除 `chapter_number`、`title`、`act` 外，**必须**包含 `summary`、`goal`、`conflict`、`hook`、`payoff`、`highlight`（缺一不可），`key_events` 可选。这些字段是后续 AI 生成章节正文时的唯一叙事指南。{min_chapter_requirement}
5. `outline` 中必须额外包含 `serial_strategy` 对象，至少给出 `positioning`、`opening_hook`、`first_3_chapter_hook`。
6. 只输出 JSON，包含 `tags`、`characters`、`outline`、`chapters` 四个字段。
{launch_ready_hint}
{quality_feedback_hint}"""
    elif effective_length == "medium":
        user_prompt = f"""请根据以下故事描述，生成一版适合中篇创作的扩展型小说框架：

{description}
{story_bible_hint}

额外要求：
1. `outline` 覆盖开书阶段和后续发展，阶段结构 3-5 个，核心冲突升级 2-3 次。
2. 初始大纲只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和方向，不要求输出每章明细。
3. 后续阶段不需要输出终局章节明细，用 `serial_strategy` 的 `midgame_engine` 和 `late_game_direction` 标注发展方向。
4. 每个 `chapters` 条目除 `chapter_number`、`title`、`act` 外，**必须**包含 `summary`、`goal`、`conflict`、`hook`、`payoff`、`highlight`（缺一不可），`key_events` 可选。这些字段是后续 AI 生成章节正文时的唯一叙事指南。{min_chapter_requirement}
5. `outline` 中必须额外包含 `serial_strategy` 对象，至少给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`。
6. 只输出 JSON，包含 `tags`、`characters`、`outline`、`chapters` 四个字段。
{launch_ready_hint}
{quality_feedback_hint}"""
    else:
        user_prompt = f"""请根据以下故事描述，生成一版适合长篇创作的扩展型小说框架：

{description}
{story_bible_hint}

额外要求：
1. 初始大纲只规划前 10 章详细章节，后续章节只以幕/卷级大纲给出核心冲突线和关键里程碑，不要求输出每章明细。
2. 阶段数量不固定，可以是 3 幕、4 幕、5 个篇章或其他更适合题材的结构，不要为了形式强行写成三幕。
3. 章节必须细化到"能直接写"的粒度，每章**必须**标注 summary, goal, conflict, hook, payoff, highlight（缺一不可）。
4. 后续阶段（第二幕及以后）的 `chapters` 可以为空数组或只包含 3-5 个里程碑章节——这些阶段的核心冲突方向和关键情节点只需在 `act.summary` 中描述清楚即可。
5. 不要强制写出终局结局，保留开放扩展空间。如果规划到后期，用 `serial_strategy.late_game_direction` 标注大致故事发展方向，不需要在 chapters 中产出终结性章节。
6. `outline` 中必须额外包含 `serial_strategy` 对象，至少给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`、`midgame_engine`，`late_game_direction` 可选。
7. 所有 `chapters` 条目除 `chapter_number`、`title`、`act` 外，**必须**包含 `summary`、`goal`、`conflict`、`hook`、`payoff`、`highlight`（缺一不可），`key_events` 可选。这些字段是后续 AI 生成章节正文时的唯一叙事指南，让它更像章节任务卡而不是纯标题目录。{min_chapter_requirement}
8. 后期阶段的 `chapters` 如有则标注核心里程碑（如"主角失去力量"、"真相揭示"等大事件），无需细节执行信息。
9. 只输出 JSON，包含 `tags`、`characters`、`outline`、`chapters` 四个字段。
{launch_ready_hint}
{quality_feedback_hint}"""

    payload = {
        "model": runtime_model(),
        "messages": _framework_messages_with_long_form(system_prompt or "", user_prompt, effective_length),
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Framework generation failed: {e}")


async def regenerate_outline(story_context: dict, api_key: str | None = None, story_length: str | None = None, system_prompt: str | None = None) -> dict:
    """Regenerate outline with length-appropriate pacing and flexible stage count."""
    effective_length = story_length or _infer_story_length(story_context)
    snapshot = _build_story_snapshot_tiered(story_context, "framework_runtime")

    if effective_length == "short":
        user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成一版更适合短篇创作的 `outline`。
{snapshot}

额外要求：
1. 大纲要服务于短篇节奏（10-30 章），紧凑有力，不要拖沓。
2. 阶段结构 2-3 个：建立冲突 → 升级/反转 → 高潮/解决。
3. 每一章都要有明确的叙事功能，不要有纯过渡章。
4. 真正的高潮应放在中后段，但不要太远——短篇需要快速进入核心。
5. 开书段要明确：在 `outline.serial_strategy` 中给出 `positioning`、`opening_hook`、`first_3_chapter_hook`。
6. 只输出 `{{"outline": ...}}` JSON 对象。"""
    elif effective_length == "medium":
        user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成一版更适合中篇创作的 `outline`。
{snapshot}

额外要求：
1. 大纲要服务于中篇小说节奏（50-100 章），不要让主线在几十章内快速收束。
2. 阶段结构 3-5 个，每个阶段至少 10 章。
3. 中段要保留升级空间、悬念递进和关系变化空间。
4. 开书段要明确：在 `outline.serial_strategy` 中给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`、`chapter_20_payoff`。
5. 只输出 `{{"outline": ...}}` JSON 对象。"""
    else:
        user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成一版更适合长篇创作的 `outline`。
{snapshot}

额外要求：
1. 大纲要服务于长篇小说节奏，不要让主线在几十章内快速收束。
2. 阶段结构必须完整，但阶段数量不固定；请根据题材自由决定分成几个主要阶段更合适。
3. 中段要保留足够的升级空间、悬念递进和关系变化空间。
4. 真正的终局高潮应放在整体规划后段，不要过早揭秘、过早满级、过早完结。
        5. 开书段要明确：在 `outline.serial_strategy` 中给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`、`chapter_20_payoff`。
6. 可以把前中期写得更细，把后期写成更高层级的阶段目标与冲突推进，但整体方向必须完整。
7. 只输出 `{{"outline": ...}}` JSON 对象。"""

    payload = {
        "model": runtime_model(),
        "messages": _framework_messages_with_long_form(
            system_prompt or "你是小说策划编辑。基于已有故事框架，只输出包含 outline 的 JSON 对象。",
            user_prompt,
            effective_length,
        ),
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("outline", result)
    except ValueError as e:
        raise ValueError(f"Outline regeneration failed: {e}")


def _extract_framework_adjustment_plan(result: dict) -> dict:
    """从 AI JSON 输出中提取结构化编辑计划（operations/patches/warnings）。"""
    reply = str(result.get("reply") or "").strip() or "已根据你的建议调整框架。"
    operations = result.get("operations") if isinstance(result.get("operations"), list) else []
    patches = result.get("patches") if isinstance(result.get("patches"), list) else []
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    return {
        "reply": reply,
        "operations": operations,
        "patches": patches,
        "warnings": [str(item).strip() for item in warnings if str(item).strip()],
    }


async def adjust_framework_with_chat(
    story_context: dict,
    messages: list[dict],
    api_key: str | None = None,
    required_min_chapters: int | None = None,
    existing_framework: dict | None = None,
    system_prompt: str | None = None,
    story_length: str | None = None,
) -> dict:
    """根据自然语言指令输出结构化编辑计划（operations/patches），不再返回完整框架。

    Args:
        system_prompt: Custom system prompt, None uses built-in default.
        story_length: 篇幅类型 short/medium/long，None 自动推断。"""
    effective_length = story_length or _infer_story_length(story_context)
    snapshot = _build_story_snapshot_tiered(story_context, "framework_runtime")
    description = str(story_context.get("description") or "").strip()
    safe_messages = [
        {
            "role": "assistant" if str(item.get("role")) == "assistant" else "user",
            "content": str(item.get("content") or "").strip(),
        }
        for item in messages
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    if not safe_messages:
        raise ValueError("至少需要一条对话消息")

    min_chapter_requirement = (
        f"\n- 如果用户要求至少 {required_min_chapters} 章，你必须在 operations 中用 add_chapter 或 insert_chapter_after 补到该数量，不能只在 reply 里承诺。"
        if required_min_chapters and required_min_chapters >= 20
        else ""
    )

    user_prompt = f"""请根据下面的对话，对现有小说框架输出结构化编辑计划。

故事创意：{description}

当前框架 JSON：
{snapshot}

修改要求：
- 输出 reply + operations + patches + warnings。
- reply 只说明实际执行范围，不要说"我会"。
- 禁止输出完整 framework JSON。
- **章节数量限制（强制）**：绝对禁止一次性输出所有卷的章节规划。每次只规划一卷的章节（每章必须含 summary/goal/conflict/hook/payoff/highlight），后续卷只规划幕级大纲（act/title/summary，chapters 设为空数组）。单次调整最多添加 15 章 add_chapter 操作。
- **⚠️ 任务卡字段强制要求（非协商，不可省略）**：每章 changes 中必须有 summary/goal/conflict/hook/payoff/highlight 全部 6 个字段，值不能为空字符串或 null。这些字段是 AI 生成章节正文时的唯一叙事指南，缺少任一字段将导致生成质量下降和系统告警。如果原始需求中某章缺少任务卡信息，**必须根据上下文合理推断补充，不允许留空或省略**。

支持的 operation 类型（每个 operation 是 {{"op": "类型", "changes": {{...}}}}）：

【增量类操作】用于"增加/补充/添加/续写/修改/调整"场景：
- update_story_description: 修改故事简述，changes 包含 description
- update_tags: 修改标签，changes 可包含 type/theme/style/audience
- add_character: 添加角色，changes 包含角色完整信息（name 必填）
- update_character: 更新角色，target.name 指定角色，changes 包含更新字段
- remove_character: 删除角色，target.name 指定角色名
- update_act_summary: 更新幕摘要，target.act 指定幕号，changes.summary 为摘要
- add_act: 新增一幕，changes.title/summary 指定标题和摘要；target.after_act 可选，指定在哪个幕之后插入（不指定则追加到末尾）
- delete_act: 删除一幕并重排剩余幕号，target.act 指定要删除的幕号（删除后后续幕号自动前移）
- add_chapter: 在指定幕末尾添加章节，target.act 指定幕号，changes 包含 chapter_number/title 等
- insert_chapter_after: 在指定章节后插入，target.chapter_number 指定位置，changes 包含新章节
- move_chapter_to_act: 移动章节到另一幕，target.chapter_number 指定章节，target.act 指定目标幕
- update_chapter: 更新章节内容，target.chapter_number 指定章节，changes 包含更新字段
- delete_chapter: 删除章节，target.chapter_number 指定要删除的章节

【替换类操作】用于"重写/替换/重新规划/重新设计/改成"场景：
- replace_outline: 完全替换整个大纲（而非增量追加），在 changes.outline 中传入完整的 new outline JSON
- replace_tags: 完全替换所有标签，在 changes.tags 中传入完整的新标签对象
- replace_characters: 完全替换角色列表，在 changes.characters 中传入完整的新角色数组
- replace_act_chapters: 只替换指定 act 的章节列表，不影响其他 act；changes.target.act 指定目标幕号，changes.chapters 传入新章节数组

何时使用替换 vs 增量：
- 用户说"重写/替换/重新规划/重新设计/改成/换成" → 使用 replace_* 操作
- 用户说"增加/补充/添加/续写/修改/调整" → 使用增量操作
- 返回 reply 时必须明确说明执行的是替换还是增量操作

⚠️ 大规模结构调整建议（合并幕、压缩幕数、重新划分章节）：使用一个 outline.three_acts patch 直接替换整个三幕数组，而不是用大量 move_chapter_to_act 操作。patch 方式一次完成且不会出错。
示例：{{"path": "outline.three_acts", "value": [{{"act": "1", "title": "...", "summary": "...", "chapters": [...]}}, ...]}}

支持的 patch path 格式（每个 patch 是 {{"path": "路径", "value": 值}}）：
- description: 直接设定故事简述
- tags.type / tags.theme / tags.style / tags.audience: 修改单个标签
- outline.serial_strategy: 替换连载策略对象
- outline.themes: 替换主题列表
- outline.foreshadowing: 替换伏笔列表
- outline.three_acts: 替换三幕结构（必须为数组）
- outline.three_acts[N].chapters: 替换第 N 幕的章节列表（N 从 0 开始）
- 注意：path 不要以 / 开头，用点号分隔层级，数组用 [下标] 访问
{min_chapter_requirement}"""

    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES + 1):
        payload = {
            "model": runtime_model(),
            "messages": _framework_messages_with_long_form(system_prompt or "", user_prompt, effective_length) + safe_messages,
            "stream": False,
            "max_tokens": 95536,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(
                    f"{runtime_base_url()}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = _response_json(resp, context="DeepSeek")
                content = data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            if attempt < MAX_RETRIES:
                continue
            raise ValueError(f"DeepSeek API 返回错误：{e.response.status_code}") from e

        try:
            result = _extract_json_object(content)
        except ValueError as e:
            if attempt < MAX_RETRIES:
                safe_messages.append({"role": "assistant", "content": content})
                safe_messages.append({
                    "role": "user",
                    "content": f"你输出的 JSON 解析失败：{e}。请修复后重新输出有效的结构化编辑计划。",
                })
                continue
            raise ValueError(f"Framework adjustment failed: {e}")

        plan = _extract_framework_adjustment_plan(result)

        if not plan["operations"] and not plan["patches"]:
            if attempt < MAX_RETRIES:
                safe_messages.append({"role": "assistant", "content": content})
                safe_messages.append({
                    "role": "user",
                    "content": "输出缺少 operations 或 patches（至少一项），请重新输出结构化编辑计划。",
                })
                continue

        return plan


async def continue_framework(story_context: dict, api_key: str | None = None, story_length: str | None = None) -> dict:
    """Continue the framework without rushing to an ending.

    Returns {"reply": ..., "changes": {"outline": ..., "chapters": [...]}}
    where changes only contains the extended outline and chapters.
    """
    return await continue_framework_with_chat(story_context, [], api_key=api_key, story_length=story_length)


async def continue_framework_with_chat(
    story_context: dict,
    messages: list[dict],
    api_key: str | None = None,
    story_length: str | None = None,
    system_prompt: str | None = None,
) -> dict:
    """根据对话上下文续写框架，返回结构化编辑计划。"""
    effective_length = story_length or _infer_story_length(story_context)
    snapshot = _build_story_snapshot_tiered(story_context, "auto")

    safe_messages = [
        {
            "role": "assistant" if str(item.get("role")) == "assistant" else "user",
            "content": str(item.get("content") or "").strip(),
        }
        for item in messages
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]

    system_prompt = system_prompt or ""

    user_prompt = f"""请在以下现有故事框架的基础上继续续写后续发展。

当前框架 JSON：
{snapshot}

请输出结构化编辑计划（reply + operations + patches + warnings）。

支持的 operation 类型（每个 operation 是 {{"op": "类型", "changes": {{...}}}}）：

【增量类操作】用于"增加/补充/添加/续写/修改/调整"场景：
- update_story_description: 修改故事简述，changes 包含 description
- update_tags: 修改标签，changes 可包含 type/theme/style/audience
- add_character: 添加角色，changes 包含角色完整信息（name 必填）
- update_character: 更新角色，target.name 指定角色，changes 包含更新字段
- remove_character: 删除角色，target.name 指定角色名
- update_act_summary: 更新幕摘要，target.act 指定幕号，changes.summary 为摘要
- add_act: 新增一幕，changes.title/summary 指定标题和摘要；target.after_act 可选，指定在哪个幕之后插入（不指定则追加到末尾）
- delete_act: 删除一幕并重排剩余幕号，target.act 指定要删除的幕号
- add_chapter: 在指定幕末尾添加章节，target.act 指定幕号，changes 包含 chapter_number/title 等
- insert_chapter_after: 在指定章节后插入，target.chapter_number 指定位置，changes 包含新章节
- move_chapter_to_act: 移动章节到另一幕，target.chapter_number 指定章节，target.act 指定目标幕
- update_chapter: 更新章节内容，target.chapter_number 指定章节，changes 包含更新字段
- delete_chapter: 删除章节，target.chapter_number 指定要删除的章节

【替换类操作】用于"重写/替换/重新规划/重新设计/改成"场景：
- replace_outline: 完全替换整个大纲，在 changes.outline 中传入完整的新 outline JSON
- replace_tags: 完全替换所有标签，在 changes.tags 中传入完整的新标签对象
- replace_characters: 完全替换角色列表，在 changes.characters 中传入完整的新角色数组
- replace_act_chapters: 只替换指定 act 的章节列表；changes.target.act 指定目标幕号，changes.chapters 传入新章节数组

⚠️ 大规模结构调整建议（合并幕、压缩幕数、重新划分章节）：使用一个 outline.three_acts patch 直接替换整个三幕数组，而不是用大量 move_chapter_to_act 操作。
示例：{{"path": "outline.three_acts", "value": [{{"act": "1", "title": "...", "summary": "...", "chapters": [...]}}, ...]}}

支持的 patch path 格式（每个 patch 是 {{"path": "路径", "value": 值}}）：
- description: 直接设定故事简述
- tags.type / tags.theme / tags.style / tags.audience: 修改单个标签
- outline.serial_strategy: 替换连载策略对象
- outline.themes: 替换主题列表
- outline.foreshadowing: 替换伏笔列表
- outline.three_acts: 替换三幕结构（必须为数组）
- outline.three_acts[N].chapters: 替换第 N 幕的章节列表（N 从 0 开始）
- 注意：path 不要以 / 开头，用点号分隔层级，数组用 [下标] 访问"""

    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES + 1):
        payload = {
            "model": runtime_model(),
            "messages": _framework_messages_with_long_form(system_prompt or "", user_prompt, effective_length) + safe_messages,
            "stream": False,
            "max_tokens": 95536,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(
                    f"{runtime_base_url()}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = _response_json(resp, context="DeepSeek")
                content = data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            if attempt < MAX_RETRIES:
                continue
            raise ValueError(f"DeepSeek API 返回错误：{e.response.status_code}") from e

        try:
            result = _extract_json_object(content)
        except ValueError as e:
            if attempt < MAX_RETRIES:
                safe_messages.append({"role": "assistant", "content": content})
                safe_messages.append({
                    "role": "user",
                    "content": f"你输出的 JSON 解析失败：{e}。请修复后重新输出有效的结构化编辑计划。",
                })
                continue
            raise ValueError(f"Framework continuation failed: {e}")

        plan = _extract_framework_adjustment_plan(result)

        if not plan["operations"] and not plan["patches"]:
            if attempt < MAX_RETRIES:
                safe_messages.append({"role": "assistant", "content": content})
                safe_messages.append({
                    "role": "user",
                    "content": "输出缺少 operations 或 patches（至少一项），请重新输出结构化编辑计划。",
                })
                continue

        return plan


async def summarize_chapter_memory(
    story_context: dict,
    chapter_info: dict,
    chapter_content: str,
    api_key: str | None = None,
) -> dict:
    """Generate compact, persistent memory for a chapter and story continuity."""
    runtime_brief = _build_framework_runtime_brief(story_context, include_outline_json=False)
    chapter_payload = json.dumps(chapter_info, ensure_ascii=False)
    content_sample = chapter_content[:12000] if len(chapter_content) > 12000 else chapter_content

    user_prompt = f"""请根据以下上下文，为这一章生成可持久化的连续性记忆 JSON。

## 运行时上下文
{runtime_brief}

## 章节信息
{chapter_payload}

## 章节正文
{content_sample}

 只输出 JSON，对象结构如下：
{{
  "chapter_summary": {{
    "summary": "120字内本章摘要",
    "major_events": ["关键事件1", "关键事件2"],
    "character_changes": ["角色状态变化1"],
    "new_facts": ["新确认事实1"],
    "open_loops": ["尚未回收的悬念1"],
    "resolved_loops": ["本章回收的悬念1"],
    "ending_scene": "本章结尾场景描写（100-200字，如无可省略）"
  }},
  "chapter_handoff": {{
    "ending_location": "本章结尾时角色所在的地点和场景（概括性描述，用于下一章承接）",
    "active_conflict": "当前最紧迫的冲突或矛盾",
    "active_characters": ["本章结尾时在场的角色名称列表"],
    "character_states": ["关键角色的当前状态或情绪"],
    "immediate_open_loops": ["下一章应立即推进的悬念或剧情线"],
    "opening_must_continue": "下一章开头必须承接的具体情境或事件（一句话概括，便于新章节检查是否承接上了）"
  }},
  "story_memory_update": {{
    "story_state": "当前故事推进到什么局面",
    "current_arc_focus": "当前阶段核心推进点",
    "current_tone": "当前整体氛围",
    "next_payoff_target": "下一步最值得回收/推进的目标",
    "continuity_facts": ["全局应牢记的事实1"],
    "open_loops": ["全局未回收悬念1"],
    "resolved_loops": ["全局已回收悬念1"]
  }}
}}

要求：
1. 信息要短、准、可复用，避免文学化空话。
2. 只保留后续创作真正需要记住的事实。
3. 如果某项没有内容，返回空字符串或空数组。
4. 禁止输出 Markdown、解释或额外文本。"""

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是长篇小说连续性编辑。请把章节正文压缩成后续创作可复用的结构化记忆，只输出 JSON。\n\n"
                    "特别注意：\n"
                    "1. 请从章节正文中提取本章结尾场景的详细描写（约 100-200 字），"
                    "在输出的 JSON 的 chapter_summary 中放入 ending_scene 字段。\n"
                    "2. 必须生成 chapter_handoff（章节交接包），它记录了本章结尾时的位置、冲突、"
                    "在场角色和他们的状态，以及下一章应立即推进的剧情线——这些是下一章创作时"
                    "需要准确承接的连续性信息。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Chapter memory summarization failed: {e}")


_SETTING_KEYWORDS = (
    "力量体系", "境界", "修炼", "灵力", "真气", "斗气", "灵根", "丹田",
    "势力", "门派", "家族", "组织", "联盟", "宗门", "商会",
    "大陆", "帝国", "王国", "城邦", "星域", "位面",
    "历史", "传说", "古籍", "神话", "纪元",
    "规则", "法则", "天赋", "血脉", "命格", "因果",
)


def _estimate_setting_ratio(content: str) -> float:
    if not content:
        return 0.0
    total = len(content)
    setting_chars = 0
    for kw in _SETTING_KEYWORDS:
        idx = 0
        while True:
            idx = content.find(kw, idx)
            if idx == -1:
                break
            start = max(0, idx - 10)
            end = min(total, idx + len(kw) + 10)
            setting_chars += (end - start)
            idx += len(kw)
    return min(setting_chars / total, 1.0) if total else 0.0


def _check_setting_ratio(content: str, chapter_number: int) -> dict:
    ratio = _estimate_setting_ratio(content)
    if chapter_number <= 3 and ratio > 0.15:
        return {"exceed": True, "ratio": ratio, "threshold": 0.15,
                "message": f"设定占比 {ratio:.1%} 超过前 3 章 15% 红线"}
    if chapter_number <= 10 and ratio > 0.20:
        return {"exceed": True, "ratio": ratio, "threshold": 0.20,
                "message": f"设定占比 {ratio:.1%} 超过前 10 章 20% 警戒线"}
    if ratio > 0.30:
        return {"exceed": True, "ratio": ratio, "threshold": 0.30,
                "message": f"设定占比 {ratio:.1%} 超过 30% 警戒线"}
    return {"exceed": False, "ratio": ratio}


def _get_genre_prompt_addon(story_context: dict) -> str:
    """根据题材类型返回题材特定的写作要求。"""
    tags = story_context.get("tags") if isinstance(story_context, dict) else None
    if not isinstance(tags, dict):
        return ""
    genre = str(tags.get("type") or "").strip()
    genre_lower = genre.lower()

    if any(k in genre for k in ("玄幻", "仙侠", "修真")):
        return (
            "\n\n## 玄幻/仙侠题材要求\n"
            "- 升级节奏：前 10 章必须有至少 2 次境界提升或能力突破\n"
            "- 金手指展示：每 5 章至少 1 次金手指新用法展示\n"
            "- 战斗描写：每 10 章至少 1 场完整战斗，侧重策略而非纯力量碾压\n"
            "- 世界观揭秘：分 3 层（凡人界→修真界→更高层次），不要一次性交代\n"
        )
    elif any(k in genre for k in ("都市", "现代")):
        return (
            "\n\n## 都市题材要求\n"
            "- 打脸节奏：前 10 章至少 3 次打脸/装逼名场面\n"
            "- 金手指应用：每 3 章至少 1 次金手指在日常生活中发挥作用\n"
            "- 社交场景：每 5 章至少 1 个新社交场景（宴会/职场/校园/商场）\n"
            "- 信息差设计：主角必须掌握其他人不知道的关键信息\n"
        )
    elif any(k in genre for k in ("科幻", "末世", "星际")):
        return (
            "\n\n## 科幻题材要求\n"
            "- 设定融合：科技设定必须影响社会结构和人物关系，不是装饰\n"
            "- 揭秘节奏：每 10 章揭示 1 个科技背后的真相或阴谋\n"
            "- 硬核与情感平衡：每章技术描写不超过 20%，必须有情感主线\n"
            "- 反转设计：每 20 章至少 1 个重大科幻反转\n"
        )
    elif any(k in genre for k in ("历史", "穿越", "古代")):
        return (
            "\n\n## 历史/穿越题材要求\n"
            "- 历史细节：每章至少 1 个符合时代背景的细节（服饰/饮食/礼仪/称谓）\n"
            "- 改变历史：主角的每个决策必须有历史因果链，不能随意改变\n"
            "- 权谋节奏：每 10 章至少 1 次政治博弈或权力洗牌\n"
            "- 文化冲突：穿越者与现代思维的碰撞每 5 章至少 1 次\n"
        )
    elif any(k in genre for k in ("悬疑", "推理", "侦探")):
        return (
            "\n\n## 悬疑/推理题材要求\n"
            "- 线索投放：每章至少 1 条有效线索（真线索或红鲱鱼）\n"
            "- 反转节奏：每 10 章至少 1 次推理反转\n"
            "- 信息控制：读者获取的信息量必须少于主角，制造悬念\n"
            "- 逻辑严密：所有推理必须有前文铺垫，禁止突然揭秘\n"
        )
    return ""


def _build_chapter_prompt_by_position(chapter_number: int | None, base_prompt: str) -> str:
    """按章节位置注入特殊规则（黄金三章强化）。"""
    if not isinstance(chapter_number, int) or chapter_number < 1:
        return base_prompt

    if chapter_number == 1:        return base_prompt + (
            "\n\n## 第一章开篇铁律（签约生死线，必须遵守）\n"
            "1. 主角必须在第一段出现，第一句包含主角名或主角视角。\n"
            "2. 第一段必须扔出冲突或危机，禁止平淡叙述开篇。\n"
            "3. 前 300 字必须包含至少 3 个事件单元（动作/对话/信息投放）。\n"
            "4. 设定信息占比 ≤15%（力量体系/势力/地理名词总字数 ≤300 字），设定通过事件自然展现。\n"
            "5. 第一章必须有至少 1 个剧情反转或意外事件。\n"
            "6. 第一章必须暗示金手指存在（异常感知/特殊物品/神秘梦境/天赋觉醒征兆）。\n"
            "7. 章末必须有强度 ≥4 的钩子（悬念/冲突升级/爽点预告）。\n"
            "8. 禁止大段世界观介绍——读者第一眼要看到的是「谁在经历什么」而非「这个世界是怎样的」。\n"
            "\n### 前 100 字事件密度要求\n"
            "前 100 字必须包含至少 3 个事件单元：\n"
            "- 事件 = 动作 + 对象 + 结果（如「林墨推开门，看见师父倒在血泊中」）\n"
            "- 禁止纯环境描写开头\n"
            "- 禁止纯心理活动开头\n"
            "- 禁止纯设定介绍开头\n"
        )
    elif chapter_number == 2:
        return base_prompt + (
            "\n\n## 第二章立人设铁律\n"
            "1. 主角必须有至少 1 个「反差标签」（如杀手怕毛茸茸、学霸怕社交、废柴有隐藏天赋）。\n"
            "2. 金手指必须有进一步展示（但不能完全揭示，保留悬念）。\n"
            "3. 出场角色不超过 4 个，每个配角必须有明确功能定位。\n"
            "4. 必须推进核心冲突，禁止纯日常过渡章。\n"
            "5. 章末钩子强度 ≥3。\n"
        )
    elif chapter_number == 3:
        return base_prompt + (
            "\n\n## 第三章钩子铁律\n"
            "1. 金手指必须正式亮相（不再是暗示，读者明确知道主角的特殊能力）。\n"
            "2. 核心危机必须明确化（主角面对的最大威胁清晰可感）。\n"
            "3. 必须建立「追读理由」——读者为什么看第 4 章（未解悬念/即将到来的冲突/爽点预告）。\n"
            "4. 章末钩子强度 ≥4。\n"
            "5. 出场角色不超过 5 个。\n"
        )
    return base_prompt


async def expand_chapter_to_content(
    story_context: dict, chapter_info: dict,
    api_key: str | None = None,
    previous_chapter_summary: str = "",
    system_prompt: str | None = None,
    db=None,
    _retry_count: int = 0,
    _retry_reason: str | None = None,
    _previous_content: str = "",
    _best_content: str | None = None,
    _best_distance: int | None = None,
) -> str:
    """按故事框架约束把章节大纲扩写成完整正文。

    目标约 2500 字。低于下限时补足重试，超过上限时保留情节做收束重写。
    """
    if _retry_count == 0 and not _retry_reason:
        try:
            from services.chapter_agents import run_chapter_creation_pipeline

            pipeline_result = await run_chapter_creation_pipeline(
                story_context=story_context,
                chapter_info=chapter_info,
                api_key=api_key,
                previous_chapter_summary=previous_chapter_summary,
                system_rules=_get_chapter_system_prompt(db=db) if not system_prompt else system_prompt,
                max_revisions=3,
            )
            if isinstance(story_context, dict) and isinstance(pipeline_result.get("creation_pack"), dict):
                story_context["_last_creation_pack"] = pipeline_result["creation_pack"]
            if isinstance(story_context, dict) and pipeline_result.get("content"):
                pipeline_content = str(pipeline_result.get("content") or "")
                story_context["_last_chapter_pipeline_result"] = {
                    "ok": bool(pipeline_result.get("ok")),
                    "content_sha256": hashlib.sha256(pipeline_content.encode("utf-8")).hexdigest(),
                    "char_count": len(pipeline_content.replace(" ", "").replace("\n", "").replace("\r", "")),
                    "review": pipeline_result.get("review") if isinstance(pipeline_result.get("review"), dict) else {},
                    "creation_pack": pipeline_result.get("creation_pack") if isinstance(pipeline_result.get("creation_pack"), dict) else None,
                    "attempts": pipeline_result.get("attempts", 0),
                    "finish_reason": pipeline_result.get("finish_reason"),
                }
            if pipeline_result.get("content") and pipeline_result.get("ok"):
                return str(pipeline_result["content"])
            if pipeline_result.get("content"):
                raise ChapterPipelineQualityError(pipeline_result.get("review"))
            logging.warning("三角色章节链路未产出正文，回退旧章节扩写链路: %s", pipeline_result.get("review"))
        except ChapterPipelineQualityError:
            raise
        except Exception as exc:
            logging.warning("三角色章节链路执行失败，回退旧章节扩写链路: %s", exc)

    MAX_RETRIES = 2

    def _is_valid_fallback_candidate(text: str, scope: dict[str, Any]) -> bool:
        """只把长度合格、未越界的正文纳入最终回退候选。"""
        count = len((text or "").replace(" ", "").replace("\n", "").replace("\r", ""))
        if count < CHAPTER_TARGET_MIN_CHARS or count > CHAPTER_TARGET_MAX_CHARS:
            return False
        return not _detect_chapter_boundary_issues(text, scope)

    snapshot = _build_story_snapshot(story_context)
    boundary_scope = _chapter_scope_from_context(story_context)
    chapter_details = json.dumps(chapter_info, ensure_ascii=False)

    previous_block = ""
    if previous_chapter_summary and previous_chapter_summary.strip():
        previous_block = f"\n## 上集回顾\n{previous_chapter_summary}\n"

    boundary_detail = ""
    if boundary_scope:
        boundary_detail = (
            "\n## 当前章节边界卡（必须遵守）\n"
            f"{json.dumps(boundary_scope, ensure_ascii=False)}\n"
            "- 只能写 current_chapter_card 里的本章事件。\n"
            "- future_chapters_for_boundary_only 只用于避雷，不是素材库。\n"
            "- 正文不得提前出现后续章节的完整行动、地点推进、资源收获、战斗兑现、秘境/擂台/捡漏等核心场面。\n"
            "- 如果某个名词只存在于后续章节摘要里，除非当前任务卡明确要求，否则不要写入正文。\n"
        )

    # Parse chapter task card hook structure
    hook_info = ""
    if isinstance(chapter_info, dict):
        parts = []
        for key, label in [("goal", "本章目标"), ("conflict", "核心冲突"), ("hook", "开篇钩子"),
                           ("payoff", "本章回收"), ("highlight", "本章亮点")]:
            val = str(chapter_info.get(key) or "").strip()
            if val:
                parts.append(f"- {label}：{val}")
        if parts:
            hook_info = "## 本章结构要求（必须执行）\n" + "\n".join(parts)

        payoff_type = str(chapter_info.get("payoff_type") or "").strip()
        payoff_intensity = chapter_info.get("payoff_intensity")
        micro_payoffs = chapter_info.get("micro_payoffs")
        hook_intensity = chapter_info.get("hook_intensity")
        payoff_hint_parts = []
        if payoff_type:
            payoff_hint_parts.append(f"- 本章爽点类型：{payoff_type}")
        if isinstance(payoff_intensity, (int, float)) and payoff_intensity > 0:
            payoff_hint_parts.append(f"- 本章爽点强度：{int(payoff_intensity)}/5")
        if isinstance(micro_payoffs, list) and micro_payoffs:
            payoff_hint_parts.append(f"- 本章必须包含的微爽点：{micro_payoffs}")
        if isinstance(hook_intensity, (int, float)) and hook_intensity > 0:
            payoff_hint_parts.append(f"- 章末钩子强度目标：{int(hook_intensity)}/5")
        if payoff_hint_parts:
            hook_info += "\n## 爽点节奏提示\n" + "\n".join(payoff_hint_parts) + "\n- 提醒：爽点是网文追读率的核心，本章必须让读者感受到明确的满足感或期待感。"

    user_prompt = f"""请根据以下故事框架和章节任务卡，创作本章正文。

## 故事框架
{snapshot}

以上「作品圣经」中的创意理解、写作指导和导入约束是**不可违反的核心设定**，所有创作必须严格遵守，不得与圣经中的设定冲突。
如已引用作者画像参考报告，则当作品圣经、写作要求与作者画像在句式节奏、语言风格、描写密度上冲突时，一律以作者画像为准。

## 本章任务卡
{chapter_details}
{hook_info}
{boundary_detail}
{previous_block}
## 叙事边界硬闸（起点编辑审稿标准）
- 本章只能完成「本章任务卡」中明示的目标、冲突、回收和亮点。
- 作品圣经、全书大纲、后续章节摘要只能作为设定背景和连续性边界，禁止把后续章节的关键事件提前写完。
- 禁止为了制造爽点跨章透支：不能提前完成下一章的核心行动、不能提前兑现后续章节的资源收获、不能提前解决后续章节的主要冲突。
- 如果需要提到后续线索，只能作为一句以内的未解悬念或行动方向，不能写成完整场面。
- 本章结尾必须停在「当前章节自然形成的下一步选择/风险/发现」上，不得把下一章剧情直接演完。

## ⚠️ 字数要求（最优先）
- **正文字数目标约 {CHAPTER_TARGET_IDEAL_CHARS} 字**，建议 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字。
- 低于 {CHAPTER_TARGET_MIN_CHARS} 字视为展开不足，必须补足关键场面、对话和因果推进；超过 {CHAPTER_TARGET_MAX_CHARS} 字视为超出标准，必须自行删去无效铺垫并收束。
- 不要为了凑篇幅重复心理活动、环境描写、路程转场或设定解释；也不要为了压篇幅砍掉关键因果、有效对话和章末钩子。
- 这不是梗概扩写，必须写成完整网文章节：有开篇钩子、过程冲突、情绪推进和章末钩子。
- 每句话都必须推进剧情或建立人设。删除所有对推进剧情无贡献的句子。

## 首轮篇幅结构（用于一次命中）
- 首轮优先写到 {CHAPTER_FIRST_PASS_MIN_CHARS}-{CHAPTER_FIRST_PASS_MAX_CHARS} 字，给校验留余量，不要贴着 2800 字上限写。
- 全章控制在 9-10 个自然段，每段约 200-240 字，最长段落不要超过 280 字。
- 段落功能建议：开篇危机 1 段，冲突铺垫 2 段，行动推进 4-5 段，爽点或转折 1 段，章末钩子 1 段。
- 章末钩子完成后立刻停笔，禁止追加尾声、总结、感悟、下一章预告或重复解释。

## 起点白金级写作规范

### 开篇铁律（前 200 字决定留存率）
- 【禁止】以时间、天气、景色描写开头。开篇第一句必须是"事件/对话/冲突/异常"之一。
- 主角必须在第 1 段出场并面临一个具体问题或决定。
- 前 100 字必须让读者知道"发生了什么/谁在经历/有什么风险"。

### 叙事密度
- 每 200 字内必须发生剧情推进或角色关系变化。
- 每段传递且仅传递一个有效信息。写完这个信息就换段或换话题。
- 【禁止】纯过渡段落——"他走了几分钟""过了一会儿""不知不觉""就这样"。跳过无信息的时间段。
- 【禁止】叠加式描写——同一动作/情绪分三步写（发生层→感知层→反应层）。合并为一段连续正文。

### 对话要求
- 本章至少有 3 句有效对话。对话必须推进剧情或展现角色性格。
- 对话要口语化，不同角色说话方式必须不同。禁止所有角色用同一种"书面腔"说话。
- 禁止"嗯""啊""好的"等无信息对话单独成段。

### 场景经济性
- 一个场景只完成一个叙事功能。功能完成立刻切走。
- 禁止同一场景写超过 300 字而不发生任何剧情变化。
- 新场景出现时：最多 2 句建立氛围，立刻转入剧情。
- 环境必须通过角色感知来呈现，禁止作者旁白式环境描写。

### 章末钩子（强制）
- 最后 100 字必须制造翻页冲动。有效钩子：信息差揭示、冲突升级、角色面临抉择、意外发现。
- 【禁止】总结升华（"他终于明白了……"）、空泛预告（"他不知道的是……"）、哲理收尾（"人生就是这样……"）。

### 情绪展示（Show Don't Tell）
- 【禁止】直接写"他很愤怒/悲伤/紧张/害怕/委屈/绝望"——用身体反应和行为展示：手在抖/杯子摔了/沉默/转身/锁门。
- 【禁止】"他感到/他觉得/他意识到/他知道/他明白"等告知式心理描写。
- 【禁止】"心中涌起一股XX""心头一震""心底泛起XX"等模板化情绪描写。
- 【禁止】大段纯心理描写。整章心理活动累计不超过 2 段。

## 🚫 零容忍清单（出现任何一项即视为 AI 写作，全章作废）
1. 【破折号】全文禁止任何破折号（——），用逗号/句号/冒号代替
2. 【时间/天气/景色】禁止以任何形式的时间、天气、景色描写开篇
3. 【突然/忽然/瞬间/猛地】全文完全禁止使用——不设"不超过N次"的例外
4. 【不是A而是B】禁止否定-肯定句式（"他不是冷漠，而是绝望"→直接写B）
5. 【让X感到Y】禁止（"让他感到一阵寒意"→用动作代替）
6. 【仿佛/犹如/宛若】全文禁止使用，用白描代替
7. 【眼中闪过一丝/嘴角勾起一抹/深吸一口气】禁止任何模板化表情/动作短语
8. 【他不知道的是/这一切才刚刚开始】禁止模板化悬念
9. 【深深地/无比地/极其//缓缓/微微/淡淡/轻轻】禁止，或全文不超过 1 次
10. 【他知道/他明白/他意识到】禁止告知式写法，用行为展示认知变化
11. 【不禁/不由自主/不由得】全文禁止
12. 【叠加强调】禁止"三连排比"式写法——事情说一遍就够了，不说三遍
13. 【大段描写】禁止连续 3 句以上的对外部景物/环境的纯描写
14. 【总结式结尾】禁止以总结性感悟、哲理升华收束章节

直接输出正文。不要标题、不要章节号、不要章节名、不要字数统计、不要任何额外说明。只输出正文本身。"""

    if _retry_reason == "short":
        user_prompt += (
            "\n\n## ⚠️ 上一版本被驳回：正文展开不足\n"
            f"上一版低于 {CHAPTER_TARGET_MIN_CHARS} 字，像梗概或半章内容。\n"
            f"本次必须补足到 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字，理想约 {CHAPTER_TARGET_IDEAL_CHARS} 字。\n"
            "- 核心情节、人物、关键对话保持不偏题\n"
            "- 优先补足冲突铺垫、角色反应、关键对话、爽点兑现和章末钩子\n"
            "- 按 10 个自然段输出，每段约 210-240 字\n"
            "- 不要用总结、设定说明或水段落凑字数\n"
        )
    elif _retry_reason == "long":
        previous_excerpt = _previous_content[:12000]
        if len(_previous_content) > 12000:
            previous_excerpt += "\n\n[中间内容略去，收束重写时仍以本章任务卡为准保留完整因果链。]"
        user_prompt += (
            "\n\n## ⚠️ 上一版本被驳回：正文超过标准\n"
            f"上一版超过 {CHAPTER_TARGET_MAX_CHARS} 字，节奏偏散。请基于上一版做完整重写，"
            f"收束到 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字，理想约 {CHAPTER_TARGET_IDEAL_CHARS} 字。\n"
            "- 禁止直接截断，必须保留开篇钩子、核心冲突、关键因果、必要对话、爽点兑现和章末钩子\n"
            "- 删除重复心理活动、解释性设定、路程转场、无变化的观察和无信息寒暄\n"
            "- 合并功能重复的场景，让每 200 字都有新行动、新信息或关系变化\n"
            "- 改成 9-10 个自然段，每段约 200-230 字，最长段落不超过 260 字\n"
            "- 只输出收束后的完整正文，不要说明删改过程\n"
            "\n## 上一版正文（用于保留情节并收束重写）\n"
            f"{previous_excerpt}\n"
        )
    elif _retry_reason == "boundary":
        previous_excerpt = _previous_content[:12000]
        if len(_previous_content) > 12000:
            previous_excerpt += "\n\n[中间内容略去，边界重写时仍以本章任务卡为唯一剧情范围。]"
        previous_boundary_issues = _detect_chapter_boundary_issues(_previous_content, boundary_scope)
        issue_block = "\n- ".join(previous_boundary_issues) if previous_boundary_issues else "上一版疑似提前写完后续章节事件"
        user_prompt += (
            "\n\n## ⚠️ 上一版本被驳回：章节边界越界\n"
            "上一版把后续章节的核心事件、资源收获、冲突解决或爽点兑现提前写进了本章。\n"
            f"越界点：\n- {issue_block}\n"
            "- 本次必须完整重写，不是局部修补。\n"
            "- 只能完成本章任务卡，不能提前演完后续章节。\n"
            "- 后续线索最多作为一句以内的未解悬念或行动方向，不能写成完整场面。\n"
            "- 章末停在本章自然形成的下一步选择/风险/发现上。\n"
            "\n## 上一版正文（仅用于识别并删除越界内容）\n"
            f"{previous_excerpt}\n"
        )

    chapter_system_prompt = _get_chapter_system_prompt(db=db)
    effective_system = system_prompt if system_prompt else chapter_system_prompt
    chapter_number = chapter_info.get("chapter_number") if isinstance(chapter_info, dict) else None
    effective_system = _build_chapter_prompt_by_position(chapter_number, effective_system)
    effective_system = effective_system + _get_genre_prompt_addon(story_context)
    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": CHAPTER_COMPLETION_MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice["message"]["content"]
        content = _sanitize_novel_content(content)
        _char_count = len(content.replace(" ", "").replace("\n", "").replace("\r", ""))
        _distance = abs(_char_count - CHAPTER_TARGET_IDEAL_CHARS)
        boundary_issues = _detect_chapter_boundary_issues(content, boundary_scope)
        if _is_valid_fallback_candidate(content, boundary_scope) and (
            _best_content is None or _best_distance is None or _distance < _best_distance
        ):
            _best_content = content
            _best_distance = _distance
        if finish_reason == "length":
            logging.warning("章节正文生成触发 length 截断风险，当前正文约 %d 字", _char_count)
            if _retry_count < MAX_RETRIES:
                return await expand_chapter_to_content(
                    story_context=story_context,
                    chapter_info=chapter_info,
                    api_key=api_key,
                    previous_chapter_summary=previous_chapter_summary,
                    system_prompt=system_prompt,
                    db=db,
                    _retry_count=_retry_count + 1,
                    _retry_reason="long",
                    _previous_content=content,
                    _best_content=_best_content,
                    _best_distance=_best_distance,
                )
        if boundary_issues and _retry_count < MAX_RETRIES:
            logging.warning("章节正文疑似预支后续章节，边界重写第 %d 次: %s", _retry_count + 1, boundary_issues)
            return await expand_chapter_to_content(
                story_context=story_context,
                chapter_info=chapter_info,
                api_key=api_key,
                previous_chapter_summary=previous_chapter_summary,
                system_prompt=system_prompt,
                db=db,
                _retry_count=_retry_count + 1,
                _retry_reason="boundary",
                _previous_content=content,
                _best_content=_best_content,
                _best_distance=_best_distance,
            )
        if _char_count < CHAPTER_TARGET_MIN_CHARS and _retry_count < MAX_RETRIES:
            logging.warning("章节正文 %d 字，不足 %d 字，补足重试第 %d 次", _char_count, CHAPTER_TARGET_MIN_CHARS, _retry_count + 1)
            return await expand_chapter_to_content(
                story_context=story_context,
                chapter_info=chapter_info,
                api_key=api_key,
                previous_chapter_summary=previous_chapter_summary,
                system_prompt=system_prompt,
                db=db,
                _retry_count=_retry_count + 1,
                _retry_reason="short",
                _previous_content=content,
                _best_content=_best_content,
                _best_distance=_best_distance,
            )
        if _char_count > CHAPTER_TARGET_MAX_CHARS and _retry_count < MAX_RETRIES:
            logging.warning("章节正文 %d 字，超过 %d 字标准上限，收束重写第 %d 次", _char_count, CHAPTER_TARGET_MAX_CHARS, _retry_count + 1)
            return await expand_chapter_to_content(
                story_context=story_context,
                chapter_info=chapter_info,
                api_key=api_key,
                previous_chapter_summary=previous_chapter_summary,
                system_prompt=system_prompt,
                db=db,
                _retry_count=_retry_count + 1,
                _retry_reason="long",
                _previous_content=content,
                _best_content=_best_content,
                _best_distance=_best_distance,
            )
        if _char_count > CHAPTER_TARGET_MAX_CHARS:
            logging.warning("章节正文 %d 字，仍超过 %d 字标准上限（重试%d次后）", _char_count, CHAPTER_TARGET_MAX_CHARS, _retry_count)
        elif _char_count < CHAPTER_TARGET_MIN_CHARS:
            logging.warning("章节正文 %d 字，仍不足 %d 字（重试%d次后）", _char_count, CHAPTER_TARGET_MIN_CHARS, _retry_count)
        if (
            (_char_count < CHAPTER_TARGET_MIN_CHARS or _char_count > CHAPTER_TARGET_MAX_CHARS)
            and _best_content
            and _best_content != content
            and _best_distance is not None
            and _best_distance < _distance
        ):
            logging.warning(
                "章节多次重试后仍未完全命中目标，返回已通过长度与边界的候选版本（接近 %d 字，偏差 %d 字）",
                CHAPTER_TARGET_IDEAL_CHARS,
                _best_distance,
            )
            content = _best_content
        setting_check = _check_setting_ratio(content, chapter_number if isinstance(chapter_number, int) else 0)
        if setting_check.get("exceed"):
            logging.warning("章节设定占比超标: %s", setting_check.get("message", ""))
        ai_quick_issues = _quick_ai_flavor_check(content)
        if ai_quick_issues:
            logging.warning("章节 AI 味快速检测发现问题: %s", ai_quick_issues)
        boundary_issues = _detect_chapter_boundary_issues(content, boundary_scope)
        if boundary_issues:
            logging.warning("章节正文多次重试后仍疑似预支后续章节: %s", boundary_issues)
        return content


def _quick_ai_flavor_check(content: str) -> list[str]:
    """生成后轻量级 AI 味检测（不调用 API，仅本地模式匹配）。"""
    issues = []
    if not content:
        return issues
    if "——" in content:
        count = content.count("——")
        issues.append(f"破折号残留 {count} 处")
    sudden_count = content.count("突然") + content.count("忽然") + content.count("猛地")
    if sudden_count > 3:
        issues.append(f"突然/忽然/猛地 共 {sudden_count} 次（建议 ≤3）")
    tell_count = sum(content.count(w) for w in ["他感到", "她感觉", "他意识到", "他明白", "他知道"])
    if tell_count > 5:
        issues.append(f"告知式心理描写 {tell_count} 处")
    simile_count = sum(content.count(w) for w in ["仿佛", "犹如", "宛若"])
    if simile_count > 0:
        issues.append(f"明喻词 {simile_count} 处（禁止使用）")
    return issues


async def rewrite_selection(
    selected_text: str,
    chapter_context: str,
    story_context: dict | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """在不改变情节的前提下改写选中的小说片段。"""
    snapshot = _build_story_snapshot_tiered(story_context or {}, "auto") if isinstance(story_context, dict) else ""
    story_snapshot_block = f"\n## 故事约束\n{snapshot}\n" if snapshot else ""
    user_prompt = f"""请改写以下小说片段，保持原有情节和人物不变，但提升文笔质量：

{story_snapshot_block}
## 章节上下文
{chapter_context if chapter_context else "无额外上下文"}

## 需要改写的文本
{selected_text}

## 改写要求
- 保持原有情节、人物对话和关键信息不变
- 如已引用作者画像参考报告，改写时必须保持作者画像中记录的句式节奏和语言特征，即使这与"提升文笔"的通用标准冲突，以作者画像为准
- 如作品圣经、角色设定、故事大纲与片段细节存在冲突，优先遵守最新的作品圣经和故事约束
- 提升描写的细腻度和画面感
- 增强人物微表情、小动作、心理活动的描写
- 优化句式节奏，避免单调
- 逻辑自洽：确保改写后的情节转折有因有果，角色行为符合其性格和处境
- 禁止使用破折号（——），用逗号、句号或省略号代替
- 禁止使用「突然」「忽然」等廉价转折词
- 直接输出改写后的文本，不要加额外说明"""

    HARDCODED_REWRITE_SYSTEM = (
        "你是白金级小说编辑，擅长在不改变情节的前提下提升文笔质量。\n"
        "## 核心约束\n"
        "1. 逻辑自洽优先：改写后的内容必须有清晰的因果链。\n"
        "2. 禁止使用破折号（——），用逗号、句号或省略号代替。\n"
        "3. 禁止使用「突然」「忽然」等廉价转折词。"
    )
    effective_system = system_prompt if system_prompt else HARDCODED_REWRITE_SYSTEM

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": CHAPTER_COMPLETION_MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        return _sanitize_novel_content(data["choices"][0]["message"]["content"])


async def adjust_chapter_content(
    story_context: dict,
    chapter_info: dict,
    chapter_content: str,
    instruction: str,
    api_key: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """Adjust the full chapter content according to a user instruction."""
    snapshot = _build_story_snapshot_tiered(story_context, "auto")
    boundary_scope = _chapter_scope_from_context(story_context)
    chapter_details = json.dumps(chapter_info, ensure_ascii=False)

    # 提取章节任务卡结构（对标 expand_chapter_to_content）
    hook_info = ""
    if isinstance(chapter_info, dict):
        parts = []
        for key, label in [("goal", "本章叙事目标"), ("conflict", "核心冲突"),
                           ("hook", "开篇钩子"), ("payoff", "本章回报/高潮"),
                           ("highlight", "本章最大亮点")]:
            val = str(chapter_info.get(key) or "").strip()
            if val:
                parts.append(f"- {label}：{val}")
        if parts:
            hook_info = "## 本章任务卡（必须执行）\n" + "\n".join(parts) + "\n\n⚠️ 以上任务卡是本章的叙事指南。生成正文时，必须让读者感受到 goal 所描述的核心卖点、conflict 所描述的对抗张力、payoff 所描述的阅读满足感。不得偏离任务卡自由发挥。\n"

    boundary_detail = ""
    if boundary_scope:
        boundary_detail = (
            "\n## 当前章节边界卡（必须遵守）\n"
            f"{json.dumps(boundary_scope, ensure_ascii=False)}\n"
            "- 只能写 current_chapter_card 里的本章事件。\n"
            "- future_chapters_for_boundary_only 只用于避雷，不是素材库。\n"
            "- 正文不得提前出现后续章节的完整行动、地点推进、资源收获、战斗兑现、秘境/擂台/捡漏等核心场面。\n"
            "- 如果某个名词只存在于后续章节摘要里，除非当前任务卡明确要求，否则不要写入正文。\n"
        )

    user_prompt = f"""请根据以下故事框架、章节任务卡和修改要求，创作本章正文。

## 故事框架
{snapshot}

以上「作品圣经」中的创意理解、写作指导和导入约束是**不可违反的核心设定**，所有创作必须严格遵守，不得与圣经中的设定冲突。
如已引用作者画像参考报告，则当作品圣经、写作要求与作者画像在句式节奏、语言风格、描写密度上冲突时，一律以作者画像为准。

## 本章信息
{chapter_details}
{hook_info}
{boundary_detail}
## 当前正文（参考，除非用户要求保留否则可全部重写）
{chapter_content}

## 用户修改要求
{instruction}

## 🚫 零容忍清单（出现任何一项即全章作废，优先级最高）
1. 【破折号】全文禁止任何破折号（——），用逗号/句号/冒号代替
2. 【突然/忽然/瞬间/猛地】全文完全禁止使用——不设"不超过N次"的例外
3. 【不是A而是B】禁止否定-肯定句式（"他不是冷漠，而是绝望"→直接写B）
4. 【仿佛/犹如/宛若】全文禁止使用，用白描代替
5. 【眼中闪过一丝/嘴角勾起一抹/深吸一口气】禁止模板化表情动作短语
6. 【他不知道的是/这一切才刚刚开始】禁止模板化悬念
7. 【他知道/他明白/他意识到】禁止告知式写法，用行为展示认知变化
8. 【不禁/不由自主/不由得】全文禁止
9. 【心中涌起/心头一震/心底泛起】禁止模板化情绪描写
10. 【叠加强调】禁止三连排比
11. 【大段描写】禁止连续3句以上纯景物描写
12. 【总结式结尾】禁止以总结性感悟、哲理升华收束章节
13. 【时间/天气/景色开篇】禁止，开篇第一句须是事件/对话/冲突/异常
14. 【让X感到Y】禁止（"让他感到一阵寒意"→用动作代替）

## 写作规范
- 每句话都必须推进剧情或建立人设。删除无贡献句子。
- 对话要口语化，不同角色说话方式必须不同。
- 情绪用身体反应和行为展示，禁止直接写情绪词。
- 章末100字须制造翻页冲动，禁止总结升华。

直接输出正文。不要标题、不要章节号、不要章节名、不要字数统计、不要任何额外说明。只输出正文本身。"""

    HARDCODED_CHAPTER_ADJUST_SYSTEM = (
        "你是起点白金级网文编辑，审稿标准对齐起点铂金签约审核。\n"
        "## 字数要求（最优先）\n"
        f"正文字数目标约 {CHAPTER_TARGET_IDEAL_CHARS} 字，建议 {CHAPTER_TARGET_MIN_CHARS}-{CHAPTER_TARGET_MAX_CHARS} 字；"
        f"低于 {CHAPTER_TARGET_MIN_CHARS} 字视为展开不足，超过 {CHAPTER_TARGET_MAX_CHARS} 字视为超出标准，必须删去无效铺垫并自行收束。"
        "优先写到 2300-2450 字，按 9-10 个自然段组织，每段约 200-240 字。每句话必须推进剧情或建立人设。\n"
        "## 开篇铁律\n"
        "【禁止】以时间、天气、景色开头。第一句必须是事件/对话/冲突/异常。主角第1段出场。\n"
        "## 叙事密度\n"
        "每段只传递一个有效信息。禁止纯过渡段落。禁止叠加式描写。\n"
        "## 对话要求\n"
        "本章至少 3 句有效对话。对话推进剧情或展现性格。口语化，不同角色说话方式不同。\n"
        "## 场景经济性\n"
        "一个场景一个功能。同一场景不超过 300 字无剧情变化。新场景最多 2 句建立氛围。\n"
        "## 章末钩子（强制）\n"
        "最后 100 字必须制造翻页冲动。禁止总结升华、空泛预告、哲理收尾。\n"
        "## 情绪展示\n"
        "身体反应代替情绪词。禁止「他感到/他觉得/他意识到/他明白」等告知式写法。\n"
        "## 🚫 零容忍\n"
        "1. 禁止破折号（——）\n"
        "2. 禁止以时间/天气/景色开篇\n"
        "3. 【突然/忽然/瞬间/猛地】全文完全禁止\n"
        "4. 禁止「不是A而是B」句式\n"
        "5. 禁止「仿佛/犹如/宛若」\n"
        "6. 禁止模板化短语（眼中闪过一丝/嘴角勾起一抹/心中涌起）\n"
        "7. 禁止「不禁/不由自主/不由得」\n"
        "8. 禁止「他知道/他明白/他意识到」告知式\n"
        "9. 禁止三连排比\n"
        "10. 禁止大段景物描写（连续3句以上）\n"
        "11. 禁止总结式结尾"
    )
    effective_system = system_prompt if system_prompt else HARDCODED_CHAPTER_ADJUST_SYSTEM

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": CHAPTER_COMPLETION_MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        return _sanitize_novel_content(data["choices"][0]["message"]["content"])


async def quality_assess(chapter_content: str, api_key: str | None = None) -> dict:
    """Assess chapter quality across 5 dimensions, returning scores and suggestions."""
    # Truncate extremely long content to avoid token overflow
    content_sample = chapter_content[:16000] if len(chapter_content) > 16000 else chapter_content
    user_prompt = f"""请对以下小说章节进行质量评估，从5个维度打分（1-10分）：

## 章节内容
{content_sample}

请输出JSON格式：
{{
  "scores": {{
    "content": <内容充实度 1-10>,
    "writing": <文笔质量 1-10>,
    "character": <角色塑造 1-10>,
    "plot": <情节推进 1-10>,
    "overall": <整体质量 1-10>
  }},
  "suggestions": ["改进建议1", "改进建议2", ...],
  "overall_comment": "整体评价"
}}"""

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": "你是一位资深文学评论家，对小说进行客观、专业的质量评估。请输出JSON格式。"},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Quality assessment failed: {e}")


async def analyze_content_framework(content: str, api_key: str | None = None) -> dict:
    """Analyze existing novel content to extract tags, characters, and outline framework."""
    # Truncate if too long to avoid token limits
    content_sample = content[:32000] if len(content) > 32000 else content
    user_prompt = f"""请分析以下小说正文内容，提取出完整的故事框架信息。

## 小说正文
{content_sample}

请严格输出JSON格式，包含以下三个字段：

### 1. tags（标签）
故事的核心标签：
- type: 小说类型（如"奇幻"、"科幻"、"悬疑"、"言情"、"武侠"等）
- theme: 核心主题（如"成长"、"复仇"、"救赎"、"爱与牺牲"等）
- style: 写作风格（如"细腻温情"、"磅礴大气"、"幽默风趣"、"黑暗压抑"等）
- audience: 目标读者（如"青少年"、"成人"、"全年龄"等）

### 2. characters（角色）
提取3-6个核心角色，每个角色是一个包含以下字段的对象：
- name: 角色名
- role: 角色定位（如"主角"、"反派"、"导师"、"伙伴"等）
- big_five: 大五人格维度，对象格式 {{"openness": 1-10, "conscientiousness": 1-10, "extraversion": 1-10, "agreeableness": 1-10, "neuroticism": 1-10}}
- arc: 角色弧线，对象格式 {{"start": "初始状态", "middle": "转折状态", "end": "最终状态"}}
- relationships: 与其他角色的关系，数组格式 [{{"to": "角色名", "type": "关系类型", "description": "关系描述"}}]

### 3. outline（大纲）
故事大纲：
- three_acts: 三幕结构数组，每幕包含 {{"act": 1|2|3, "title": "幕标题", "summary": "本幕概要", "key_events": ["关键事件1", "关键事件2", ...]}}
- themes: 主题线索数组 ["主题1", "主题2"]
- foreshadowing: 伏笔数组 ["伏笔描述1", "伏笔描述2"]

JSON输出格式示例：
{{{{
  "tags": {{"type": "奇幻", "theme": "成长", "style": "细腻温情", "audience": "青少年"}},
  "characters": [{{"name": "角色名", "role": "主角", "big_five": {{"openness": 7, "conscientiousness": 6, "extraversion": 5, "agreeableness": 8, "neuroticism": 4}}, "arc": {{"start": "初始", "middle": "转折", "end": "成长"}}, "relationships": [{{"to": "另一角色", "type": "友情", "description": "描述"}}]}}],
  "outline": {{"three_acts": [{{"act": 1, "title": "开端", "summary": "故事开始", "key_events": ["事件1"]}}], "themes": ["主题1"], "foreshadowing": ["伏笔1"]}}
}}}}

请仅输出JSON，不要包含其他文字。"""

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位资深小说策划编辑，擅长从已完成的正文内容中分析提取故事框架。"
                    "请基于实际内容提取标签、角色设定和大纲，不要凭空编造。"
                    "只输出JSON格式，不要输出其他内容。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Content framework analysis failed: {e}")


async def analyze_import_material(content: str, api_key: str | None = None) -> dict:
    """Analyze imported outline/manuscript material and generate a usable framework."""
    content_sample = content[:48000] if len(content) > 48000 else content
    user_prompt = f"""请分析以下导入材料，并将其整理成可直接用于小说创作的完整框架。

材料类型可能是：
1. 小说正文或章节初稿
2. 小说大纲、策划案、设定稿
3. 世界观、角色、分卷规划混合文档

请先判断它属于哪一类：
- `outline_source`：大纲、设定稿、策划案，不应把小标题误判成真实章节
- `chapter_manuscript`：真实小说正文或按章节整理的正文稿

无论属于哪一类，都要输出一版完整可用的小说框架。

特别要求：
1. 如果它是 `outline_source`，不要把"故事总览 / 世界观设定 / 角色设定 / 分卷大纲 / 节奏建议 / 亮点 / 写作提醒"之类标题当成真实章节。
2. 如果它是 `outline_source`，你需要根据材料内容重新拟出真正的故事大纲和章节规划。
3. 如果它是 `chapter_manuscript`，你需要基于正文提炼大纲与角色，并给出合理的章节规划。
4. `chapters` 字段必须是可以直接用于创作的章节规划，不能照抄目录型标题。
5. 只输出 JSON，不要输出解释。

导入材料：
{content_sample}

JSON 顶层必须包含：
{{
  "content_type": "outline_source" | "chapter_manuscript",
  "tags": {{
    "type": "...",
    "theme": "...",
    "style": "...",
    "audience": "..."
  }},
  "characters": [
    {{
      "name": "...",
      "role": "...",
      "big_five": {{
        "openness": 1-10,
        "conscientiousness": 1-10,
        "extraversion": 1-10,
        "agreeableness": 1-10,
        "neuroticism": 1-10
      }},
      "arc": {{}},
      "relationships": []
    }}
  ],
  "outline": {{
    "three_acts": [
      {{
        "act": "阶段1",
        "title": "...",
        "summary": "...",
        "key_events": ["..."],
        "chapters": [
          {{
            "chapter_number": 1,
            "title": "...",
            "summary": "...",
            "key_events": ["..."]
          }}
        ]
      }}
    ],
    "themes": ["..."],
    "foreshadowing": ["..."]
  }},
  "chapters": [
    {{
      "chapter_number": 1,
      "title": "...",
      "act": "阶段1",
      "key_events": ["..."]
    }}
  ]
}}
"""

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位资深小说策划编辑，擅长把导入材料整理成可用的小说框架。"
                    "你必须先判断它是大纲源材料还是正文稿。"
                    "如果是大纲、设定稿或策划案，绝对不能把小标题误判成真实章节。"
                    "只输出 JSON。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        response_content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(response_content)
    except ValueError as e:
        raise ValueError(f"Import material analysis failed: {e}")


async def scenes_from_selection(selected_text: str, character_profiles: str = "", page_count: int = 4, api_key: str | None = None) -> list[str]:
    """Generate manga scene descriptions from selected novel text.
    
    Reuses the existing split_scenes pattern but focused on the selected text only.
    """
    chat_messages = [{"role": "user", "content": selected_text}]
    return await split_scenes(
        chat_messages,
        character_profiles=character_profiles,
        page_count=page_count,
        api_key=api_key,
    )


# ─── Onboarding / Story Bible ───────────────────────────────

# ONBOARDING_SYSTEM_PROMPT 种子数据已移至 main.py _seed_system_prompts


async def generate_onboarding_response(
    messages: list[dict],
    understanding: dict[str, str] | None = None,
    api_key: str | None = None,
    max_retries: int = 2,
    system_prompt: str | None = None,
) -> dict:
    """生成引导建书对话中 AI 的下一轮回复，含自动重试韧性"""
    last_error: Exception | None = None
    understanding_snapshot = json.dumps(understanding or {}, ensure_ascii=False)
    onboarding_state_hint = (
        "\n\n## 当前已确认理解\n"
        f"- current_understanding: {understanding_snapshot}\n"
        "更新 understanding 时遵守：对于「是的/嗯/对」这类确认回答，"
        "保留上一轮已判断出的内容，不要清空。"
    )

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "model": runtime_model(),
                "messages": [
                    {"role": "system", "content": (system_prompt or "") + onboarding_state_hint},
                    *messages,
                ],
                "stream": False,
                "max_tokens": 500,
            }

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{runtime_base_url()}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = _response_json(resp, context="DeepSeek")
                content = data["choices"][0]["message"]["content"]

            try:
                result = _extract_json_object(content)
            except ValueError:
                # 尝试从可能不完整的JSON中提取reply字段
                reply_match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
                if reply_match:
                    reply_text = reply_match.group(1).replace('\\"', '"').replace('\\n', '\n')
                    return {
                        "reply": reply_text,
                        "understanding": understanding or {},
                        "understanding_depth": 0,
                        "phase": "extracting",
                        "has_brief": False,
                        "creative_brief": None,
                    }
                # fallback：返回纯文本内容
                return {
                    "reply": content.strip(),
                    "understanding": understanding or {},
                    "understanding_depth": 0,
                    "phase": "extracting",
                    "has_brief": False,
                    "creative_brief": None,
                }

            # 验证必要字段
            reply = result.get("reply", "")
            if not reply.strip():
                raise ValueError("AI 返回空回复")

            # 提取 understanding
            ai_understanding = result.get("understanding", {})
            if not isinstance(ai_understanding, dict):
                ai_understanding = {}

            # 合并：AI 输出的 understanding 覆盖旧值
            merged_understanding = {**(understanding or {}), **ai_understanding}

            return {
                "reply": reply,
                "understanding": merged_understanding,
                "understanding_depth": int(result.get("understanding_depth", 0)),
                "phase": str(result.get("phase", "extracting")),
                "has_brief": bool(result.get("has_brief", False)),
                "creative_brief": None,  # 后端 confirm 时自动构建，AI 不输出
            }

        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as e:
            last_error = e
            if attempt < max_retries:
                wait = 1.5 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            raise ValueError(f"Onboarding response generation failed after {max_retries + 1} attempts: {last_error}")

    raise ValueError(f"Onboarding response generation failed: {last_error}")


def _infer_import_context_next_step(collected_info: dict[str, Any]) -> int:
    if not collected_info.get("import_material_type"):
        return 1
    if not collected_info.get("must_keep"):
        return 2
    if not collected_info.get("author_goal"):
        return 3
    if not collected_info.get("adjustment_scope"):
        return 4
    return 4


# IMPORT_CONTEXT_SYSTEM_PROMPT 种子数据已移至 main.py _seed_system_prompts


async def generate_import_guidance_response(
    messages: list[dict[str, str]],
    import_context: dict[str, Any],
    previous_collected_info: dict[str, Any] | None = None,
    current_step: int | None = None,
    api_key: str | None = None,
    max_retries: int = 2,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    current_snapshot = json.dumps(previous_collected_info or {}, ensure_ascii=False)
    context_snapshot = json.dumps(import_context or {}, ensure_ascii=False, indent=2)
    step_hint = int(current_step or _infer_import_context_next_step(previous_collected_info or {}))
    runtime_hint = (
        "\n\n## 当前导入作品上下文\n"
        f"{context_snapshot}\n\n"
        "## 当前采集状态\n"
        f"- current_step: {step_hint}\n"
        f"- current_collected_info: {current_snapshot}\n"
        "请在此基础上补全 collected_info，并继续追问最关键的一项。"
    )

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "model": runtime_model(),
                "messages": [
                    {"role": "system", "content": (system_prompt or "") + runtime_hint},
                    *messages,
                ],
                "stream": False,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            }

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{runtime_base_url()}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = _response_json(resp, context="DeepSeek")
                content = data["choices"][0]["message"]["content"]

            result = _extract_json_object(content)
            reply = str(result.get("reply") or "").strip()
            if not reply:
                raise ValueError("AI 返回空回复")

            collected_info = result.get("collected_info", {})
            if not isinstance(collected_info, dict):
                collected_info = {}

            return {
                "reply": reply,
                "collected_info": collected_info,
                "step": int(result.get("step", step_hint)),
                "total_steps": 4,
                "is_complete": bool(result.get("is_complete", False)),
            }
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as e:
            last_error = e
            if attempt < max_retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise ValueError(f"Import guidance response generation failed after {max_retries + 1} attempts: {last_error}")

    raise ValueError(f"Import guidance response generation failed: {last_error}")


BUILD_IMPORT_BRIEF_PROMPT = """你是一位职业网文策划编辑。现在作者已经导入了一部已有作品，请基于"导入内容摘要"和"作者补充要求"，生成一份结构化的创意理解卡。

导入内容摘要：
{import_context}

作者补充要求：
{collected_info}

要求：
1. 不能脱离已导入内容，要把作者本轮补充视为后续创作和框架调整的硬约束。
2. 若导入的是旧正文，优先总结其现有卖点、主线、人物关系，再结合作者目标给出后续方向。
3. 若导入的是旧大纲，优先固化设定边界、阶段结构和后续扩写目标。
4. 输出 JSON，对象中必须包含 creative_brief 字段，结构与常规创意理解卡一致。"""


async def build_import_creative_brief(
    import_context: dict[str, Any],
    collected_info: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, Any]:
    user_prompt = BUILD_IMPORT_BRIEF_PROMPT.format(
        import_context=json.dumps(import_context, ensure_ascii=False, indent=2),
        collected_info=json.dumps(collected_info, ensure_ascii=False, indent=2),
    )
    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": "你是一位小说策划编辑。请根据导入作品摘要和作者补充要求生成 creative_brief。只输出 JSON。",
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    result = _extract_json_object(content)
    return result.get("creative_brief", result)


BUILD_BRIEF_PROMPT = """你是一位小说策划编辑。根据以下引导建书过程中收集到的作者创意信息，生成一份结构化的"创意理解卡"。

请基于以下信息，填充 JSON 中的各个字段：

{collected_info}

要求：
1. 理解并提炼作者的创作意图
2. 对模糊的地方做合理推断
3. 保持对作者原始创意的忠实
4. 输出 JSON 格式，包含以下字段：
{{
  "creative_brief": {{
    "project_positioning": "作品定位 - 一句话说清这本书是什么",
    "genre": "题材（如：奇幻、科幻、悬疑、言情）",
    "audience": "目标读者群体",
    "tone": "风格基调（如：轻松幽默、黑暗压抑、温情细腻）",
    "core_hook": "核心卖点 - 最吸引人的亮点",
    "one_line_premise": "一句话梗概",
    "protagonist_core": "主角核心设定",
    "main_conflict": "主线矛盾",
    "longline_mystery": "长线悬念/终极秘密",
    "serial_length_target": "目标篇幅",
    "must_keep_rules": ["必保留设定列表"],
    "reveal_strategy": "揭秘策略",
    "pacing_strategy": "节奏策略"
  }}
}}"""


async def build_creative_brief(
    collected_info: dict,
    api_key: str | None = None,
) -> dict:
    """根据收集到的创意信息生成结构化创意理解卡"""
    info_str = json.dumps(collected_info, ensure_ascii=False, indent=2)
    user_prompt = BUILD_BRIEF_PROMPT.format(collected_info=info_str)

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": "你是一位小说策划编辑。根据作者创意信息生成结构化的创意理解卡。只输出JSON。",
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("creative_brief", result)
    except ValueError as e:
        raise ValueError(f"Creative brief generation failed: {e}")


BUILD_STORY_BIBLE_PROMPT = """你是一位小说策划编辑。基于以下创意理解卡和原始对话记录，生成一份完整的"作品圣经"(Story Bible)。

创意理解卡：
{creative_brief}

原始创意输入：
{raw_input}

作品圣经包含三层结构：
1. raw_input: 原始创意输入（保留用户原始表述）
2. creative_brief: 结构化立项结果（来自创意理解卡）
3. writing_guidance: 生成指导信息（供后续模型直接读取）

writing_guidance 需要额外生成以下字段：
- opening_strategy: 开书策略（如何开篇吸引读者）
- chapter_density_strategy: 章节密度策略（每章承载多少内容）
- midgame_engine: 中段驱动力（维持中期连载节奏的核心机制）
- late_game_direction: 后期方向（后期剧情走向）
- forbidden_patterns: ["需要避免的创作模式"]
- preferred_plot_patterns: ["推荐使用的情节模式"]

## world_setting 结构化要求
creative_brief 中的 world_setting 字段请按以下 5 个维度输出为嵌套 JSON 对象（而非平铺字符串）。每个维度写 1-3 句具体描述，非空则填字符串，暂未确定的字段留空字符串 ""：
- power_system: 力量体系的核心规则、触发方式、等级划分、能力分类与限制条件
- society_structure: 掌握力量者与普通人的社会关系、相关组织/势力、政府管控方式
- key_locations: 故事核心场景、重要地标及其特点
- world_history: 世界观背景历史、关键时间节点与重大事件
- hidden_truths: 只有主角/部分角色知道的深层真相或世界秘密

请输出完整的故事圣经 JSON。"""


async def build_story_bible(
    creative_brief: dict,
    raw_input: dict,
    api_key: str | None = None,
) -> dict:
    """从创意理解卡生成完整的 Story Bible"""
    brief_str = json.dumps(creative_brief, ensure_ascii=False, indent=2)
    raw_str = json.dumps(raw_input, ensure_ascii=False, indent=2)
    user_prompt = BUILD_STORY_BIBLE_PROMPT.format(
        creative_brief=brief_str,
        raw_input=raw_str,
    )

    payload = {
        "model": runtime_model(),
        "messages": [
            {
                "role": "system",
                "content": "你是一位资深小说策划编辑。根据创意理解卡生成完整的作品圣经 JSON。只输出JSON，包含 story_bible 顶级字段。",
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("story_bible", result)
    except ValueError as e:
        raise ValueError(f"Story Bible generation failed: {e}")


# ─── 章节视频工作流：正文 → 10s 镜头解析 ────────────────


def _repair_missing_commas(content: str) -> str:
    """修复 JSON 中缺少逗号的问题。"""
    # 修复数组中对象之间缺少逗号: } {
    content = re.sub(r'\}\s*\{', '}, {', content)
    # 修复对象中键值对之间缺少逗号
    content = re.sub(r'"\s*\n\s*"', '",\n"', content)
    content = re.sub(r'(\d)\s*\n\s*"', r'\1,\n"', content)
    content = re.sub(r'(true|false|null)\s*\n\s*"', r'\1,\n"', content)
    # 修复 "value" { 的情况
    content = re.sub(r'"\s*\n\s*\{', '",\n{', content)
    # 修复 } "key": 的情况
    content = re.sub(r'\}\s*\n\s*"', '},\n"', content)
    return content


def _repair_trailing_commas(content: str) -> str:
    """修复 JSON 中数组/对象末尾多余逗号。"""
    content = re.sub(r',\s*\}', '}', content)
    content = re.sub(r',\s*\]', ']', content)
    return content


def _repair_truncated_json(content: str) -> str:
    """修复 DeepSeek 返回中被截断的 JSON（缺少结尾引号/括号），尝试补齐。"""
    stripped = content.rstrip()
    if not stripped:
        return content

    try:
        json.loads(stripped)
        return content
    except json.JSONDecodeError:
        pass

    in_string = False
    escaped = False
    # 使用栈追踪正确的闭合顺序（LIFO），避免计数器方案在嵌套结构中出现错误顺序
    stack: list[str] = []

    for ch in stripped:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            stack.append("{")
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
        elif ch == "[":
            stack.append("[")
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()

    if in_string:
        stripped += '"'

    for opener in reversed(stack):
        if opener == "{":
            stripped += "}"
        elif opener == "[":
            stripped += "]"

    if not stripped.endswith("}"):
        stripped += "}"

    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass

    # 从右向左查找被截断的键名：找到 " 后跟随可选空白再接闭括号的位置，插入 :null
    for end_idx in range(len(stripped) - 1, 0, -1):
        if stripped[end_idx] in '}])':
            # 向左跳过空白，查找紧邻的 "
            j = end_idx - 1
            while j >= 0 and stripped[j] in ' \t\n\r':
                j -= 1
            if j >= 0 and stripped[j] == '"':
                candidate = stripped[:j + 1] + ':null' + stripped[end_idx:]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    continue

    return stripped


def _repair_broken_json_fields(content: str) -> str:
    """修复 DeepSeek 返回中损坏的 JSON。

    处理三类问题：
    1. 缺少逗号分隔符（通过 _repair_missing_commas 修复）
    2. 数组/对象末尾多余逗号（通过 _repair_trailing_commas 修复）
    3. 损坏的嵌套字段（如 storyboard_json，替换为 null）
    """
    content = _repair_missing_commas(content)
    content = _repair_trailing_commas(content)

    idx = content.find('"storyboard_json"')
    if idx < 0:
        return content
    open_brace = content.find('{', idx)
    if open_brace < 0:
        return content
    close_brace = content.find('}', open_brace)
    if close_brace < 0:
        return content
    return content[:open_brace] + 'null' + content[close_brace:]


# 单段拆镜输入最大安全字符数
MAX_LITE_PARSE_INPUT_CHARS = 4000


def _split_text_at_paragraph_boundaries(text: str, max_chars: int) -> list[str]:
    """按段落边界拆分文本，每段不超过 max_chars 字符。"""
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if para_len > max_chars:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            for i in range(0, para_len, max_chars):
                chunks.append(para[i:i + max_chars])
            continue
        if current_chunk and current_len + para_len > max_chars:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [para]
            current_len = para_len
        else:
            current_chunk.append(para)
            current_len += para_len

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks or [text]


async def _parse_lite_chunk(
    chunk_text: str,
    character_profiles: str = "",
    api_key: str | None = None,
    chunk_label: str = "",
) -> list[dict]:
    """对单段正文调用 DeepSeek 进行轻量拆镜。"""
    from services.video_chapter_prompts import SHOT_PARSE_LITE_SYSTEM_PROMPT, SHOT_PARSE_LITE_USER_PROMPT_HEADER

    if chunk_label:
        user_prompt = f"{chunk_label}\n\n{SHOT_PARSE_LITE_USER_PROMPT_HEADER}{chunk_text}"
    else:
        user_prompt = SHOT_PARSE_LITE_USER_PROMPT_HEADER + chunk_text
    if character_profiles:
        user_prompt += f"\n\n## 角色外貌设定（参考）\n{character_profiles}"

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": SHOT_PARSE_LITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 95536,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]
        try:
            _log_shot_summary(logger, content, f"轻量拆镜{chunk_label or ''}")
        except Exception:
            logger.info("轻量拆镜原始返回: %s", content[:500])

    try:
        result = _extract_json_object(content)
    except ValueError:
        # DeepSeek 偶发返回 JSON 数组 [shot, ...] 而非 {"shots": [...]}
        try:
            raw_parsed = _loads_json_lenient(content)
        except json.JSONDecodeError:
            raw_parsed = None
        if isinstance(raw_parsed, list) and all(isinstance(item, dict) for item in raw_parsed):
            result = {"shots": raw_parsed}
        else:
            repaired = _repair_broken_json_fields(content)
            if repaired != content:
                try:
                    result = _extract_json_object(repaired)
                except ValueError as e:
                    truncated_repaired = _repair_truncated_json(repaired)
                    if truncated_repaired != repaired:
                        try:
                            result = _extract_json_object(truncated_repaired)
                        except ValueError as truncated_error:
                            raise ValueError(f"轻量拆镜失败（{chunk_label or '单段'}）：JSON 截断修复后仍无法解析 — {truncated_error}\n原始响应：{content[:500]}") from truncated_error
                    else:
                        raise ValueError(f"轻量拆镜失败（{chunk_label or '单段'}）：JSON 解析错误 — {e}\n原始响应：{content[:500]}") from e
            else:
                truncated_repaired = _repair_truncated_json(content)
                if truncated_repaired != content:
                    try:
                        result = _extract_json_object(truncated_repaired)
                    except ValueError as e:
                        raise ValueError(f"轻量拆镜失败（{chunk_label or '单段'}）：JSON 截断修复后仍无法解析 — {e}\n原始响应：{content[:500]}") from e
                else:
                    raise ValueError(f"轻量拆镜失败（{chunk_label or '单段'}）：JSON 解析错误，且未发现可修复的损坏字段\n原始响应：{content[:500]}")

    shots = result.get("shots", [])
    if not isinstance(shots, list) or len(shots) == 0:
        raise ValueError(f"轻量拆镜失败（{chunk_label or '单段'}）：shots 数组为空或格式错误 — {content[:500]}")

    return shots


async def parse_chapter_to_shots_lite(
    chapter_text: str,
    character_profiles: str = "",
    api_key: str | None = None,
) -> list[dict]:
    """轻量拆镜：只输出 7 个基础字段。正文超出 MAX_LITE_PARSE_INPUT_CHARS 时自动分段。"""
    if len(chapter_text) <= MAX_LITE_PARSE_INPUT_CHARS:
        return await _parse_lite_chunk(chapter_text, character_profiles, api_key)

    chunks = _split_text_at_paragraph_boundaries(chapter_text, MAX_LITE_PARSE_INPUT_CHARS)
    all_shots: list[dict] = []
    shot_offset = 0
    errors: list[str] = []

    for i, chunk in enumerate(chunks):
        chunk_label = f"（第 {i + 1}/{len(chunks)} 段）"
        try:
            chunk_shots = await _parse_lite_chunk(chunk, character_profiles, api_key, chunk_label)
        except ValueError as e:
            errors.append(str(e))
            continue

        for shot in chunk_shots:
            idx = shot.get("shot_index", 1)
            shot["shot_index"] = idx + shot_offset
        shot_offset += len(chunk_shots)
        all_shots.extend(chunk_shots)

    if not all_shots:
        error_detail = "\n".join(errors[:3]) if errors else "未知错误"
        raise ValueError(f"分段拆镜失败：所有段落均未返回有效镜头\n分段详情：{len(chunks)} 段，{len(errors)} 段失败\n{error_detail}")

    return all_shots


def is_valid_storyboard_prompt(text: str) -> tuple[bool, str]:
    """校验故事板导演生成的提示词是否有效（无元响应、格式完整）。

    用于防止 AI 输出元响应（角色扮演对话）替代实际提示词，
    并确保输出格式统一包含必需的五个区域。

    返回 (is_valid: bool, reason: str)
    """
    if not text or len(text) < 200:
        return False, "内容过短或为空"

    head = text[:400]

    # ── 检查元响应特征（AI 对用户说话而非输出提示词） ──
    meta_patterns = [
        "你提出的要求", "好的，", "好的 ", "以下是根据",
        "我会严格遵循", "交给我来处理", "作为您指定的",
        "已经收到", "已完整接收", "作为你的", "听从你的指示",
        "按照你的要求", "我理解你的", "明白你的需求",
        "以下是为你定制的", "以下是为你生成的",
        "让我来", "我来为你", "交给我",
    ]
    for pat in meta_patterns:
        if pat in head:
            return False, f"检测到元响应前缀: '{pat}'"

    # ── 检查是否以提示词格式开头 ──
    # 合法的开头模式：'#' / '电影级故事板' / '一张' / '```'
    valid_starts = False
    stripped = text.lstrip()
    for prefix in ("#", "电影级故事板", "一张完整", "```", "电影故事板", "## 项目"):
        if stripped.startswith(prefix):
            valid_starts = True
            break
    if not valid_starts:
        return False, "开头格式不符合提示词规范"

    # ── 检查必需的区域标识 ──
    required_markers = ["项目总设定栏", "核心分镜故事板"]
    for marker in required_markers:
        if marker not in text:
            return False, f"缺少必需区域: '{marker}'"

    # ── 检查是否包含画面描述类内容 ──
    content_markers = ["景别", "镜头运动", "画面", "构图"]
    if not any(m in text for m in content_markers):
        return False, "缺少画面描述内容"

    return True, ""


# 重试时追加到 user_message 末尾的强化指令（不修改模板本身）
_STORYBOARD_RETRY_REINFORCEMENT = """

## ⚠️ 输出格式强制要求（必须遵守）

直接输出 AI 绘图提示词本身，禁止输出任何开场白、解释、角色扮演回复、自我介绍、说明性文字。

禁止输出以下元内容：
- ❌ "好的，" / "好的 " / "以下是根据" / "我会严格遵循"
- ❌ "交给我来处理" / "作为您指定的" / "已经收到"
- ❌ "作为你的" / "听从你的指示" / "按照你的要求"
- ❌ "我理解你的" / "明白你的需求" / "以下是为你定制的"
- ❌ "让我来" / "我来为你" / "交给我" / "已完整接收"

必须以以下格式之一开头：
- '# 电影故事板生成提示词'
- '# 电影级故事板'
- '## 项目'
- '电影级故事板'
- '一张完整'

必须包含以下五个区域（缺一不可）：
1. 项目总设定栏（顶部窄栏）
2. 角色/主体设定区（左上部）
3. 场景与环境设定区（右上部）
4. 核心分镜故事板（中部主区域）
5. 灯光/镜头/剪辑/声音设计区（底部）"""


async def generate_shot_storyboard_prompt(
    shot_data: dict,
    api_key: str | None = None,
) -> str:
    """调用 DeepSeek（故事版导演角色）为单个镜头生成完整的 AI 绘图提示词。

    返回的文本是纯净的中文提示词，可直接发送给图片生成 API，
    不需要任何后续系统模板包装。

    校验机制：
    - 自动检测并过滤 AI 元响应（角色扮演对话）
    - 检测到无效内容时自动重试（追加强化格式指令）
    - 重试仍失败时记录警告并返回原始结果
    """
    from services.video_chapter_prompts import build_storyboard_director_messages

    # ── 从 storyboard_json 中提取分段内容 ──
    sj = shot_data.get("storyboard_json")
    shot_segments_content = None
    additional_sj_reference = ""
    if isinstance(sj, dict):
        segments = sj.get("segments")
        if segments and isinstance(segments, list):
            parts = []
            for seg in segments:
                start = seg.get("start_second", 0)
                end = seg.get("end_second", 0)
                task = seg.get("story_task", "")
                visual = seg.get("visual_action", "")
                dialogue = seg.get("dialogue_or_narration", "") or ""
                inner = seg.get("inner_thoughts", "") or ""
                line = f"- {start}-{end}s：{task}"
                if visual:
                    line += f"，动作：{visual}"
                if dialogue:
                    line += f"，对白：「{dialogue}」"
                if inner:
                    line += f"，内心：「{inner}」"
                parts.append(line)
            if parts:
                shot_segments_content = "\n".join(parts)
        # storyboard_json 的非 segments 字符串字段作为补充参考
        sj_values = [v for v in sj.values() if isinstance(v, str) and v.strip() and v != str(segments)]
        if sj_values:
            additional_sj_reference = "\n\n## 故事板导演分析参考\n\n" + "\n".join(sj_values)

    system_prompt, user_message = build_storyboard_director_messages(
        scene_location=shot_data.get("scene_location"),
        time_of_day=shot_data.get("time_of_day"),
        characters=shot_data.get("characters"),
        story_summary=shot_data.get("story_summary"),
        dialogue_or_narration=shot_data.get("dialogue_or_narration"),
        camera_plan=shot_data.get("camera_plan"),
        motion_plan=shot_data.get("motion_plan"),
        emotion_plan=shot_data.get("emotion_plan"),
        style_preset=shot_data.get("style_preset"),
        duration_seconds=shot_data.get("duration_seconds", 15),
        source_text_span=shot_data.get("source_text_span"),
        shot_context=shot_data.get("shot_context"),
        shot_segments_content=shot_segments_content,
        screenplay_context=shot_data.get("screenplay_context"),
    )

    if additional_sj_reference:
        user_message += additional_sj_reference

    supplemental_fields = (
        ("连续性备注", shot_data.get("continuity_notes")),
        ("叙事目的", shot_data.get("narrative_purpose")),
        ("节奏密度", shot_data.get("beat_density")),
        ("下一镜转场", shot_data.get("transition_to_next")),
    )
    supplemental_lines = [
        f"{label}：{str(value).strip()}"
        for label, value in supplemental_fields
        if value is not None and str(value).strip()
    ]
    if supplemental_lines:
        user_message += "\n\n## 补充分镜约束\n\n" + "\n".join(supplemental_lines)

    # 如果 shot_context 中包含连续性要求，追加到 system prompt 末尾
    ctx = shot_data.get("shot_context")
    if ctx and "前后镜头衔接" in ctx:
        continuity_rules = """
## 镜头间连续性规则（必须遵守）

由于当前镜头在完整剧情序列中不是孤立存在的，生成故事版时必须遵守以下规则：

1. **情绪连续性**：角色情绪必须从前一镜头的终点状态自然发展而来，不能跳跃
2. **时间连续性**：如果时间发生了跳跃（如夜间→白天），画面必须有时间流逝的视觉暗示（光线变化、角色状态变化等）
3. **空间连续性**：如果场景发生了切换，画面的叙事逻辑必须清晰表达角色如何到达新场景
4. **动作连续性**：角色的动作和状态应延续自前一镜头，不能出现不合理的动作断裂
5. **道具连续性**：关键道具（手机、戒指等）的状态必须与前后镜头一致"""
        system_prompt += continuity_rules

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "max_tokens": 8192,
    }

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{runtime_base_url()}/chat/completions",
                json=payload,
                headers=_deepseek_auth_headers(api_key),
            )
            resp.raise_for_status()
            data = _response_json(resp, context="DeepSeek")
            content = str(data["choices"][0]["message"]["content"] or "").strip()
            if not content:
                return user_message

            # ── 校验输出 ──
            is_valid, reason = is_valid_storyboard_prompt(content)
            if is_valid:
                return content

            # ── 校验失败，重试一次 ──
            logger.warning("故事版提示词校验失败 (%s)，重试中...", reason)
            retry_payload = {
                **payload,
                "messages": [
                    payload["messages"][0],
                    {"role": "user", "content": user_message + _STORYBOARD_RETRY_REINFORCEMENT},
                ],
            }
            try:
                resp2 = await client.post(
                    f"{runtime_base_url()}/chat/completions",
                    json=retry_payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp2.raise_for_status()
                data2 = resp2.json()
                content2 = str(data2["choices"][0]["message"]["content"] or "").strip()
                is_valid2, reason2 = is_valid_storyboard_prompt(content2)
                if is_valid2:
                    return content2
                logger.warning("重试后仍无效 (%s)，使用原始结果", reason2)
            except Exception as exc2:
                logger.warning("重试也失败: %s，使用原始结果", exc2)

            return content
    except Exception as exc:
        logger.warning("故事版导演角色生成失败: %s，使用备用内容", exc)
        # 降级：直接返回组装好的镜头信息作为提示词
        return user_message


def generate_shot_storyboard_content(
    shot_data: dict,
) -> str:
    """生成仅含镜头内容的简洁故事版描述（不含 LLM 生成）。

    供工作台初始回显。
    """
    from services.video_chapter_prompts import build_storyboard_director_messages

    _, user_message = build_storyboard_director_messages(
        scene_location=shot_data.get("scene_location"),
        time_of_day=shot_data.get("time_of_day"),
        characters=shot_data.get("characters"),
        story_summary=shot_data.get("story_summary"),
        dialogue_or_narration=shot_data.get("dialogue_or_narration"),
        camera_plan=shot_data.get("camera_plan"),
        motion_plan=shot_data.get("motion_plan"),
        emotion_plan=shot_data.get("emotion_plan"),
        style_preset=shot_data.get("style_preset"),
        duration_seconds=shot_data.get("duration_seconds", 15),
        source_text_span=shot_data.get("source_text_span"),
        screenplay_context=shot_data.get("screenplay_context"),
    )
    return user_message


async def generate_shot_details(
    chapter_text: str,
    shots_basic_info: list[dict],
    character_profiles: str = "",
    api_key: str | None = None,
) -> list[dict]:
    """为已拆分的镜头批量生成详细信息（运镜/动作/情绪/故事版等），最多 5 个。"""
    from services.video_chapter_prompts import SHOT_DETAIL_SYSTEM_PROMPT, build_shot_detail_user_prompt

    if len(shots_basic_info) > 5:
        raise ValueError(f"批量详情生成最多支持 5 个镜头，当前 {len(shots_basic_info)} 个")

    user_prompt = build_shot_detail_user_prompt(chapter_text, shots_basic_info, character_profiles)

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": SHOT_DETAIL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16392,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
    except ValueError:
        repaired = _repair_broken_json_fields(content)
        if repaired != content:
            try:
                result = _extract_json_object(repaired)
            except ValueError as e:
                raise ValueError(f"批量详情生成失败：JSON 解析错误 — {e}\n原始响应：{content[:500]}") from e
        else:
            raise ValueError(f"批量详情生成失败：JSON 解析错误，且未发现可修复的损坏字段\n原始响应：{content[:500]}")

    shots = result.get("shots", [])
    if not isinstance(shots, list) or len(shots) == 0:
        raise ValueError(f"批量详情生成失败：shots 数组为空或格式错误 — {content[:500]}")

    return shots


async def generate_shot_scene_prop_prompts(
    shot_data: dict,
    api_key: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """为单个镜头生成场景描述和道具提示词。"""
    from services.video_chapter_prompts import SHOT_SCENE_PROP_SYSTEM_PROMPT, build_shot_scene_prop_user_prompt

    style_preset = shot_data.get("style_preset")
    system_prompt = SHOT_SCENE_PROP_SYSTEM_PROMPT
    if style_preset:
        system_prompt += f"\n\n📌 当前风格参考图：{style_preset}\n场景和道具的画风必须与「{style_preset}」风格完全一致，色调、线条、笔触质感、整体氛围都必须与风格参考图匹配。"

    user_prompt = build_shot_scene_prop_user_prompt(
        scene_location=shot_data.get("scene_location"),
        time_of_day=shot_data.get("time_of_day"),
        story_summary=shot_data.get("story_summary"),
        dialogue_or_narration=shot_data.get("dialogue_or_narration"),
        camera_plan=shot_data.get("camera_plan"),
        motion_plan=shot_data.get("motion_plan"),
        continuity_notes=shot_data.get("continuity_notes"),
        key_props=shot_data.get("key_props"),
        scene_asset_candidates=shot_data.get("scene_asset_candidates"),
    )

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
    except ValueError:
        repaired = _repair_broken_json_fields(content)
        try:
            result = _extract_json_object(repaired)
        except ValueError:
            truncated = _repair_truncated_json(content)
            try:
                result = _extract_json_object(truncated)
            except ValueError:
                return "", []

    scene_prompt = result.get("scene_prompt", "") or ""
    prop_prompts = result.get("prop_prompts", []) or []
    if not isinstance(prop_prompts, list):
        prop_prompts = []

    return scene_prompt, prop_prompts


async def generate_shot_character_prompts_ai(
    shot_data: dict,
    character_profiles: str = "",
    api_key: str | None = None,
) -> list[dict[str, str]]:
    """使用 DeepSeek 为镜头中的每个角色生成详细的 AI 绘图提示词。"""
    from services.video_chapter_prompts import SHOT_CHARACTER_SYSTEM_PROMPT, build_shot_character_user_prompt

    characters = shot_data.get("characters", [])
    if not characters:
        return []

    user_prompt = build_shot_character_user_prompt(
        characters=characters,
        scene_location=shot_data.get("scene_location"),
        time_of_day=shot_data.get("time_of_day"),
        story_summary=shot_data.get("story_summary"),
        source_text_span=shot_data.get("source_text_span"),
        chapter_text=shot_data.get("chapter_text"),
        shot_context=shot_data.get("shot_context"),
        screenplay_context=shot_data.get("screenplay_context"),
        key_props=shot_data.get("key_props"),
        scene_asset_candidates=shot_data.get("scene_asset_candidates"),
        dialogue_or_narration=shot_data.get("dialogue_or_narration"),
        camera_plan=shot_data.get("camera_plan"),
        motion_plan=shot_data.get("motion_plan"),
        emotion_plan=shot_data.get("emotion_plan"),
        character_profiles=character_profiles,
    )

    payload = {
        "model": runtime_model(),
        "messages": [
            {"role": "system", "content": SHOT_CHARACTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{runtime_base_url()}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = _response_json(resp, context="DeepSeek")
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
    except ValueError:
        repaired = _repair_broken_json_fields(content)
        try:
            result = _extract_json_object(repaired)
        except ValueError:
            truncated = _repair_truncated_json(content)
            try:
                result = _extract_json_object(truncated)
            except ValueError:
                return []

    prompts = result.get("character_prompts", []) or []
    if not isinstance(prompts, list):
        prompts = []

    return prompts
