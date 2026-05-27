import asyncio
import json
import os
import re
from typing import Any, AsyncGenerator

import httpx
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = (os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com") or "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = (os.getenv("DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat").strip()


def configure_runtime(base_url: str | None = None, model: str | None = None) -> None:
    global DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    if isinstance(base_url, str) and base_url.strip():
        DEEPSEEK_BASE_URL = base_url.strip().rstrip("/")
    if isinstance(model, str) and model.strip():
        DEEPSEEK_MODEL = model.strip()

NOVEL_SYSTEM_PROMPT = """你是一位才华横溢、文笔细腻的网络小说家。用户会和你讨论小说的主题、风格、角色等。

当用户要求你创作小说时，请遵循以下要求：

## ★★★ 字数要求（最高优先级）★★★
- 每一话控制在 2000 字左右（1700-2500 字范围）。这是硬性要求，不可商量。
- 低于 1500 字则内容过于单薄，必须回去补充描写；超过 3000 字则过于冗长，需要精简。
- 2000 字左右要写出完整且有感染力的章节，不能因为字数少就敷衍了事。

## 结构指导
一话内容通常包含 2-3 个场景，每个场景 600-1000 字。场景分配建议：
- 开篇场景（400-600 字）：快速切入情境，可以是一段精彩对话、一个悬念画面或一个动作场景，让读者立即沉浸。
- 推进场景（600-1000 字）：情节发展的核心。展开人物互动、冲突升级或关键信息揭示。此处需要细致描写——人物的微表情、语气变化、肢体动作、环境氛围的渲染。
- 收束场景（400-600 字）：本章的落点，可以是情绪沉淀、悬念埋设或小幅高潮。不要强行断章，要给读者一个自然的停顿点。

## 写作风格
- 描写要细腻有穿透力。不追求字多，追求精准——一个恰到好处的比喻胜过三行平淡的叙述。
- 关键情感节点和重要情节转折处放慢节奏，深化描写和心理刻画；过渡性内容则一笔带过即可。
- 人物对话要自然生动，有潜台词，2-4 个来回即可，重在说出人物的性格和当下情绪。
- 避免流水账，避免空洞的形容词堆砌。每一个细节都应该服务于"塑造人物"或"推进剧情"这两个核心目标。
- 句式和段落长度要有变化，短句制造紧张感，长句用于氛围渲染和情绪铺陈。

## 核心约束：章节间连续性（最高优先级）
- 本章开头必须自然衔接上一章结尾处的情境，不能出现剧情跳跃或角色状态无故重置
- 必须严格参考"故事框架约束"中的"作品连续性记忆"，尤其是 recent_chapter_summaries 中的事件进展
- 已解决的事件仅做必要引用，不可重复描述；未回收的伏笔应在本章适当推进
- 角色状态（性格、关系、能力、情感）必须与连续性记忆保持一致
- 不可在无铺垫的情况下让角色忘记前文发生的关键事件
- 只能参考已实际发生的剧情事实，不得编造或虚构未发生的前情事件

请直接输出小说正文，不要加额外说明或字数统计。"""


def _deepseek_auth_headers(api_key: str | None = None) -> dict[str, str]:
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
            raise ValueError("Scene split response did not contain a JSON array") from first_error
        try:
            return _loads_json_lenient(match.group(0))
        except json.JSONDecodeError as second_error:
            raise ValueError("Scene split response was not valid JSON") from second_error


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

    raise ValueError("Scene split response must be a JSON array of strings")

def _scene_split_prompt(page_count: int = 10) -> str:
    return f"""你是一位专业漫画分镜师。请将小说内容拆分为恰好{page_count}页漫画。

## ★★★ 最重要的规则 ★★★
- 输出JSON数组，恰好{page_count}个元素，每个元素代表一"页"（不是一"格"）
- 每一页必须包含 **4-6 个分镜格**（最少4格，推荐5格），用【第1格】【第2格】【第3格】【第4格】…标记
- 绝对禁止一页只有3个或更少的画面！信息量不足！

## 每页必须包含的内容
- 至少4个【第N格（宽格/窄格/大宽格）】，每格描述：构图+人物+动作+表情
- 多条对话气泡：「角色的台词」（推荐2-4条/页）
- 音效字：唰—、铿！、嗡——、咔嚓、轰隆、噗通（动作或情绪转折场景必须有）
- 节奏变化：远景→中景→特写交替，避免每格景别相同

## 格式示例（必须严格遵守此格式，至少4格。注意：示例中的角色名仅作格式参考，你必须使用小说中实际出现的角色名和剧情）
"第1页：【第1格（大宽格）】远景，某场景的环境全貌，光影氛围。音效：环境音。【第2格（窄格）】特写，角色A的表情和动作细节。对话气泡：「角色A的台词。」【第3格（窄格）】特写，角色B的反应。对话气泡：「角色B的台词。」【第4格（中景）】两人互动的中景画面，肢体语言和情绪表达。音效：动作音效。【第5格（大宽格）】场景转换或高潮画面，动态构图。对话气泡：「关键台词。」音效：氛围音效。"

风格：日式黑白漫画，高对比度，戏剧性光影，精细线条和网点。

请输出JSON数组，不要输出其他任何内容：
[
  "第1页：【第1格...】...【第2格...】...【第3格...】...【第4格...】...（可选第5格）",
  "第2页：【第1格...】...【第2格...】...【第3格...】...【第4格...】...",
  ...
  "第{page_count}页：【第1格...】...【第2格...】...【第3格...】...【第4格...】..."
]"""


async def chat_stream(messages: list[dict], api_key: str | None = None, framework_context: str = "") -> AsyncGenerator[str, None]:
    """Stream chat response from DeepSeek."""
    system_content = NOVEL_SYSTEM_PROMPT
    if framework_context:
        system_content += "\n\n## 故事框架约束\n" + framework_context
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "system", "content": system_content}] + messages,
        "stream": True,
        "max_tokens": 6144,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        async with client.stream(
            "POST",
            f"{DEEPSEEK_BASE_URL}/chat/completions",
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
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def generate_novel(messages: list[dict], api_key: str | None = None, framework_context: str = "") -> str:
    """Generate a full novel chapter (non-streaming)."""
    system_content = NOVEL_SYSTEM_PROMPT
    if framework_context:
        system_content += "\n\n## 故事框架约束\n" + framework_context
    full_messages = [{"role": "system", "content": system_content}] + messages
    full_messages.append({
        "role": "user",
        "content": "请根据我们的讨论，创作这一话的完整小说内容。注意字数严格控制在2000字左右，请直接输出小说正文。",
    })

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": full_messages,
        "stream": False,
        "max_tokens": 6144,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def split_scenes(chat_messages: list[dict], character_profiles: str = "", page_count: int = 10, api_key: str | None = None) -> list[str]:
    """Use DeepSeek to split chat novel content into manga page descriptions."""
    scene_prompt = _scene_split_prompt(page_count)
    if character_profiles:
        scene_prompt += f"\n\n以下是角色外貌设定，分镜描述中必须严格匹配这些外貌特征：\n{character_profiles}"
    async def _request_scene_split(extra_instruction: str = "") -> str:
        prompt = scene_prompt
        if extra_instruction:
            prompt += "\n\n" + extra_instruction
        messages = chat_messages + [
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"你是漫画分镜专家。只输出一个有效JSON对象，格式必须是 "
                        f'{{"scenes": ["...", "..."]}}。scenes 必须恰好有 {page_count} 个字符串元素。'
                        "每个元素代表一整页漫画，且每页包含4-6个分镜格。"
                        "不要输出 Markdown、解释、前后缀或任何非 JSON 文本。"
                    ),
                },
            ] + messages,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload,
                headers=_deepseek_auth_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    raw = ""
    last_error: Exception | None = None
    retry_instructions = (
        "",
        f"重试：严格返回 {{\"scenes\": [...]}}，其中 scenes 必须恰好包含 {page_count} 页，且不要包含任何额外文字。",
    )

    for idx, extra_instruction in enumerate(retry_instructions):
        raw = await _request_scene_split(extra_instruction)
        try:
            scenes = _extract_scenes_payload(raw)
            if len(scenes) != page_count:
                raise ValueError(f"Expected {page_count} scenes, got {len(scenes)}")
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
        raise ValueError("Response is valid JSON but not an object")
    except json.JSONDecodeError as first_error:
        match = re.search(r"\{[\s\S]*\}", raw)
        candidate = match.group(0) if match else _extract_balanced_json_object_text(raw)
        if not candidate:
            raise ValueError("Response did not contain a JSON object") from first_error
        try:
            result = _loads_json_lenient(candidate)
            if isinstance(result, dict):
                return result
            raise ValueError("Extracted JSON is not an object")
        except json.JSONDecodeError as second_error:
            balanced = _extract_balanced_json_object_text(candidate)
            if balanced and balanced != candidate:
                try:
                    result = _loads_json_lenient(balanced)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    pass
            raise ValueError("Response was not valid JSON") from second_error


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
        "model": DEEPSEEK_MODEL,
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
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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
    if story_context.get("tags"):
        parts.append(f"现有标签: {json.dumps(story_context['tags'], ensure_ascii=False)}")
    if story_context.get("characters"):
        parts.append(f"现有角色: {json.dumps(story_context['characters'], ensure_ascii=False)}")
    if story_context.get("outline"):
        parts.append(f"现有大纲: {json.dumps(story_context['outline'], ensure_ascii=False)}")
    if story_context.get("description"):
        parts.append(f"故事描述: {story_context['description']}")
    # Inject story_memory_compact (continuity memory)
    story_memory_compact = story_context.get("story_memory_compact") if isinstance(story_context, dict) else None
    if not isinstance(story_memory_compact, dict) or not story_memory_compact:
        story_memory = story_context.get("story_memory") if isinstance(story_context, dict) else {}
        if isinstance(story_memory, dict) and story_memory:
            compact = {}
            for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
                value = str(story_memory.get(key) or "").strip()
                if value:
                    compact[key] = value
            for key in ("continuity_facts", "open_loops", "resolved_loops"):
                raw = story_memory.get(key)
                if isinstance(raw, list):
                    cleaned = [str(item).strip() for item in raw if str(item).strip()]
                    if cleaned:
                        compact[key] = cleaned[:12]
            recent = story_memory.get("recent_chapter_summaries")
            if isinstance(recent, list):
                compact["recent_chapter_summaries"] = [item for item in recent[-8:] if isinstance(item, dict)]
            story_memory_compact = compact
    if isinstance(story_memory_compact, dict) and story_memory_compact:
        parts.append(f"作品连续性记忆: {json.dumps(story_memory_compact, ensure_ascii=False)}")
    return "\n\n".join(parts)


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
        if isinstance(story_bible, dict):
            creative_brief = story_bible.get("creative_brief") if isinstance(story_bible.get("creative_brief"), dict) else {}
            writing_guidance = story_bible.get("writing_guidance") if isinstance(story_bible.get("writing_guidance"), dict) else {}
            raw_input = story_bible.get("raw_input") if isinstance(story_bible.get("raw_input"), dict) else {}
            import_guidance = story_bible.get("import_guidance") if isinstance(story_bible.get("import_guidance"), dict) else {}
            derived_compact: dict[str, object] = {}
            for key in (
                "project_positioning",
                "one_line_premise",
                "core_hook",
                "protagonist_core",
                "main_conflict",
                "longline_mystery",
                "serial_length_target",
                "reveal_strategy",
                "pacing_strategy",
            ):
                value = str(creative_brief.get(key) or "").strip()
                if value:
                    derived_compact[key] = value
            for key in (
                "opening_strategy",
                "chapter_density_strategy",
                "midgame_engine",
                "late_game_direction",
            ):
                value = str(writing_guidance.get(key) or "").strip()
                if value:
                    derived_compact[key] = value
            must_keep_rules = creative_brief.get("must_keep_rules")
            if isinstance(must_keep_rules, list) and must_keep_rules:
                derived_compact["must_keep_rules"] = [str(item).strip() for item in must_keep_rules if str(item).strip()][:8]
            for key in ("forbidden_patterns", "preferred_plot_patterns"):
                raw = writing_guidance.get(key)
                if isinstance(raw, list) and raw:
                    derived_compact[key] = [str(item).strip() for item in raw if str(item).strip()][:8]
            raw_idea = str(raw_input.get("raw_idea") or "").strip()
            if raw_idea:
                derived_compact["raw_idea"] = raw_idea
            for key in (
                "import_material_type",
                "must_keep",
                "author_goal",
                "adjustment_scope",
                "longline_plan",
                "tone_guardrails",
            ):
                value = str(import_guidance.get(key) or "").strip()
                if value:
                    derived_compact[f"import_{key}"] = value
            bible_compact = derived_compact
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
        for item in characters[:12]:
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
                for index, act in enumerate(acts[-6:])
                if isinstance(act, dict)
            ],
            "recent_chapter_cards": [
                {
                    "chapter_number": item.get("chapter_number"),
                    "title": item.get("title"),
                    "act": item.get("act"),
                    "summary": str(item.get("summary") or "").strip(),
                }
                for item in extracted[-12:]
            ],
        }
    if isinstance(outline_compact, dict) and outline_compact:
        parts.append(f"当前大纲紧凑摘要: {json.dumps(outline_compact, ensure_ascii=False)}")

    outline = story_context.get("outline")
    if include_outline_json and isinstance(outline, dict) and outline:
        serialized_outline = json.dumps(outline, ensure_ascii=False)
        size = len(serialized_outline.encode("utf-8"))
        if size <= 12000:
            parts.append(f"当前大纲JSON: {serialized_outline}")
        else:
            focus_outline = {}
            for key in ("serial_strategy", "themes", "foreshadowing"):
                value = outline.get(key)
                if value not in (None, "", [], {}):
                    focus_outline[key] = value
            acts = outline.get("three_acts") if isinstance(outline.get("three_acts"), list) else []
            if acts:
                focus_outline["three_acts"] = acts[-4:]
            parts.append(f"当前大纲JSON(聚焦版): {json.dumps(focus_outline, ensure_ascii=False)}")

    description = str(story_context.get("description") or "").strip()
    if description:
        parts.append(f"故事描述: {description}")

    return "\n\n".join(parts)


def _build_story_snapshot_tiered(story_context: dict, tier: str = "auto") -> str:
    """Build a tiered textual snapshot of story context, reducing large payloads.

    Tier levels:
    - "full": 保留所有字段的完整 JSON（同 _build_story_snapshot）
    - "auto": 按每个字段的 JSON 大小逐字段决策：
        <2KB  → 全量嵌入
        2-10KB → 摘要（保留结构骨架）
        >10KB  → 仅元数据（如 "N 个角色"）
    """
    if tier == "full":
        return _build_story_snapshot(story_context)
    if tier == "framework_runtime":
        return _build_framework_runtime_brief(story_context, include_outline_json=True)

    parts = []
    story_bible = story_context.get("story_bible")
    if isinstance(story_bible, dict) and story_bible:
        creative_brief = story_bible.get("creative_brief")
        writing_guidance = story_bible.get("writing_guidance")
        if creative_brief:
            parts.append(f"作品圣经-创意理解: {json.dumps(creative_brief, ensure_ascii=False)}")
        if writing_guidance:
            parts.append(f"作品圣经-写作指导: {json.dumps(writing_guidance, ensure_ascii=False)}")

    tags = story_context.get("tags")
    if tags:
        serialized = json.dumps(tags, ensure_ascii=False)
        parts.append(f"现有标签: {serialized}")

    characters = story_context.get("characters")
    if characters:
        serialized = json.dumps(characters, ensure_ascii=False)
        size = len(serialized.encode("utf-8"))
        if size < 2048:
            parts.append(f"现有角色: {serialized}")
        elif size < 10240:
            summary = [{"name": c.get("name", "?"), "role": c.get("role", "?")} for c in characters if isinstance(c, dict)]
            parts.append(f"现有角色(摘要共{len(characters)}个): {json.dumps(summary, ensure_ascii=False)}")
        else:
            parts.append(f"现有角色: {len(characters)} 个角色（已省略详细设定）")

    outline = story_context.get("outline")
    if outline:
        serialized = json.dumps(outline, ensure_ascii=False)
        size = len(serialized.encode("utf-8"))
        if size < 2048:
            parts.append(f"现有大纲: {serialized}")
        elif size < 10240:
            if isinstance(outline, dict):
                summary_outline = {}
                for key, value in outline.items():
                    if key in ("three_acts",):
                        acts = []
                        for act in (value or []):
                            if isinstance(act, dict):
                                acts.append({
                                    "act": act.get("act"),
                                    "title": act.get("title", ""),
                                    "summary": act.get("summary", ""),
                                })
                        summary_outline[key] = acts
                    elif key in ("serial_strategy",):
                        summary_outline[key] = value
                    else:
                        summary_outline[key] = value
                parts.append(f"现有大纲(摘要): {json.dumps(summary_outline, ensure_ascii=False)}")
            else:
                parts.append(f"现有大纲: {serialized[:2000]}...(截断)")
        else:
            stage_count = 0
            if isinstance(outline, dict):
                acts = outline.get("three_acts") or []
                stage_count = len(acts)
            parts.append(f"现有大纲: {stage_count} 个阶段（已省略详细大纲）")

    description = story_context.get("description")
    if description:
        parts.append(f"故事描述: {description}")

    # Inject story_memory_compact (continuity memory)
    story_memory_compact = story_context.get("story_memory_compact") if isinstance(story_context, dict) else None
    if not isinstance(story_memory_compact, dict) or not story_memory_compact:
        story_memory = story_context.get("story_memory") if isinstance(story_context, dict) else {}
        if isinstance(story_memory, dict) and story_memory:
            compact = {}
            for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
                value = str(story_memory.get(key) or "").strip()
                if value:
                    compact[key] = value
            for key in ("continuity_facts", "open_loops", "resolved_loops"):
                raw = story_memory.get(key)
                if isinstance(raw, list):
                    cleaned = [str(item).strip() for item in raw if str(item).strip()]
                    if cleaned:
                        compact[key] = cleaned[:12]
            recent = story_memory.get("recent_chapter_summaries")
            if isinstance(recent, list):
                compact["recent_chapter_summaries"] = [item for item in recent[-8:] if isinstance(item, dict)]
            story_memory_compact = compact
    if isinstance(story_memory_compact, dict) and story_memory_compact:
        parts.append(f"作品连续性记忆: {json.dumps(story_memory_compact, ensure_ascii=False)}")

    return "\n\n".join(parts)


async def regenerate_tags(story_context: dict, api_key: str | None = None) -> dict:
    """Regenerate only the tags based on existing story context."""
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成标签（tags）。

{snapshot}

请严格输出只包含 tags 的JSON对象，格式：{{"tags": {{"type": "...", "theme": "...", "style": "...", "audience": "..."}}}}"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是小说策划编辑。基于已有的故事框架，输出仅包含 tags 的JSON对象。"},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("tags", result)
    except ValueError as e:
        raise ValueError(f"Tag regeneration failed: {e}")


async def regenerate_characters_with_variance(story_context: dict, api_key: str | None = None) -> dict:
    """Regenerate characters with explicit personality variance constraints."""
    snapshot = _build_story_snapshot_tiered(story_context, "auto")
    user_prompt = f"""请基于以下故事框架信息，重新生成一组更贴合大纲的人物设定（characters）。

{snapshot}

硬性要求：
1. 只输出 JSON，对象格式为 {{"characters": [{{"name": "...", "role": "...", "big_five": {{}}, "arc": {{}}, "relationships": []}}]}}。
2. 每个角色的 `big_five` 必须完整包含 `openness`、`conscientiousness`、`extraversion`、`agreeableness`、`neuroticism` 五个维度，分值为 1-10。
3. 每个角色的大五人格必须依据其人物身份、剧情功能、主要欲望、核心缺陷和外在行为单独设计。
4. 不要给所有角色使用平均值、模板值或中庸值，禁止出现“几乎所有角色都 50/50/50/50/50”这一类结果。
5. 主角、盟友、导师、反派、幕后势力至少要在 2-3 个维度上形成明显反差，并且能从数值上看出差异。
6. 数值要能支撑大纲里的人设。比如谨慎克制型人物不应外向性过高，偏执控制型人物不应所有维度都温和。
"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("characters", result)
    except ValueError as e:
        raise ValueError(f"Character regeneration with variance failed: {e}")


async def generate_character_profiles_from_framework(story_context: dict, api_key: str | None = None) -> str:
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

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业漫画角色设定师，擅长把小说角色设定转成稳定、具体、可复用的角色外貌卡。"
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"] or "").strip()


FRAMEWORK_SYSTEM_PROMPT = """你是一位资深的小说策划编辑，擅长构建世界观、角色体系和长篇故事大纲。

请根据用户提供的故事描述，生成完整的小说框架，并严格只输出 JSON，不要输出额外说明。

输出结构要求：
1. `tags`：包含 `type`、`theme`、`style`、`audience`
2. `characters`：3-6 个核心角色，每个角色包含 `name`、`role`、`big_five`、`arc`、`relationships`
3. `outline`：包含 `three_acts`、`themes`、`foreshadowing`
4. `chapters`：章节规划数组，每章包含 `chapter_number`、`title`、`act`、`key_events`

其中：
- `outline.three_acts` 是“分阶段大纲数组”的兼容字段名，不代表必须只有三幕
- 阶段数量可以根据题材自由决定，通常应为 2 个及以上主要阶段
- 每个阶段都应包含 `act`、`title`、`summary`、`key_events`，并尽量附带 `chapters`
- `chapters[].act` 应与对应阶段标识保持一致
"""


def _long_form_framework_rules() -> str:
    return """
你正在为“可持续创作的长篇小说”规划故事框架。
硬性要求：
1. 首次框架生成要优先保证整体大纲完整，而不是把主线在几十章内快速讲完。
2. 默认按长篇网文或长篇小说节奏规划，除非用户明确要求短篇、中篇或快节奏。
3. 核心矛盾、角色成长、关系变化、世界观揭秘都应分阶段兑现，不要过早回收。
4. 真正的终局高潮应位于整体规划后段，而不是前 20-40 章内。
5. `outline` 要覆盖整部小说的主要阶段、阶段目标、冲突升级、关键反转与终局方向，但阶段数量不固定，不必强制三幕。
6. `chapters` 要提供一版完整章节规划，但允许前半段更细、后半段更概括，仍然要覆盖完整主线。
7. 章节规划要体现“铺垫 -> 升级 -> 扩盘 -> 反转 -> 决战 -> 余波”的长篇节奏。
8. 不要把角色一夜成长完成，不要把世界观谜底一次性揭穿，不要把感情线过早定局。
9. 如果题材天然适合多阶段、多篇章展开，优先给出更灵活的阶段结构，而不是硬套三幕。
10. 整体目标是：大纲第一次生成就要完整、稳、可扩展，章节规划要支撑后续持续创作。
""".strip()


def _framework_messages_with_long_form(system_text: str, user_text: str) -> list[dict]:
    return [
        {"role": "system", "content": system_text},
        {"role": "system", "content": _long_form_framework_rules()},
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
) -> dict:
    """Generate a complete story framework with flexible stage structure."""
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
        launch_ready_hint = """
9. 这次是“平台可发布级开书框架”生成，必须达到开书可用标准，而不是只给概念草稿。
10. 不要求一次性列完未来全部 200-500 章，但必须至少给出前 10 章的完整开书规划；如果能做到，前 20 章更好。
11. 前 10 章必须尽量细到能直接写，至少 6 章要补齐 `summary`，并尽量给出 `goal`、`conflict`、`hook`、`payoff`、`highlight`。
12. `outline` 至少要有 2 个以上主要阶段，明确开书阶段和后续扩展阶段；如果能拆到 3 个以上更好。
13. `outline.serial_strategy` 至少完整给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`，其余字段尽量补充。
14. 第 1 章必须有强钩子，第 3 章前要建立明确追读动力，第 10 章要有小高潮。
15. 如果你觉得整本书篇幅很长，可以把 10 章之后转为卷级/阶段级规划，但不能缺少可发布的开书结构。
""".strip()
    quality_feedback_hint = ""
    if quality_feedback:
        quality_feedback_hint = "\n上一版未达标的问题如下，请逐项修正后再输出：\n- " + "\n- ".join(quality_feedback)
    user_prompt = f"""请根据以下故事描述，生成一版适合长篇创作的完整小说框架：

{description}
{story_bible_hint}

额外要求：
1. `outline` 要尽量完整，覆盖整部小说的主要阶段、阶段目标、冲突升级和终局方向。
2. 阶段数量不固定，可以是 2 幕、4 幕、5 个篇章或其他更适合题材的结构，不要为了形式强行写成三幕。
3. `chapters` 要提供一版完整章节规划，但不要把节奏做得过快，不要在前几十章内把整部小说讲完。
4. 前 1-30 章尽量细化到“能直接写”的粒度；31-100 章保持较细规划；100 章后可逐步转为阶段性推进，但仍要覆盖完整主线。
5. `outline` 中必须额外包含 `serial_strategy` 对象，至少给出 `positioning`、`opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`、`chapter_20_payoff`、`midgame_engine`、`late_game_direction`。
6. 每个 `chapters` 条目除 `chapter_number`、`title`、`act` 外，还应尽量包含 `summary`、`goal`、`conflict`、`hook`、`payoff`、`highlight`、`key_events`，让它更像章节任务卡而不是纯标题目录。{min_chapter_requirement}
7. 如果题材天然适合长篇连载，请优先规划成更有延展性的长篇，而不是短篇速通。
8. 只输出 JSON，包含 `tags`、`characters`、`outline`、`chapters` 四个字段。
{launch_ready_hint}
{quality_feedback_hint}"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": _framework_messages_with_long_form(FRAMEWORK_SYSTEM_PROMPT, user_prompt),
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Framework generation failed: {e}")


async def regenerate_outline(story_context: dict, api_key: str | None = None) -> dict:
    """Regenerate outline with long-form pacing and flexible stage count."""
    snapshot = _build_story_snapshot_tiered(story_context, "framework_runtime")
    user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成一版更适合长篇创作的 `outline`。
{snapshot}

额外要求：
1. 大纲要服务于长篇小说节奏，不要让主线在几十章内快速收束。
2. 阶段结构必须完整，但阶段数量不固定；请根据题材自由决定分成几个主要阶段更合适。
3. 中段要保留足够的升级空间、悬念递进和关系变化空间。
4. 真正的终局高潮应放在整体规划后段，不要过早揭秘、过早满级、过早完结。
5. 开书段要明确：在 `outline.serial_strategy` 中给出 `opening_hook`、`first_3_chapter_hook`、`chapter_10_climax`、`chapter_20_payoff`。
6. 可以把前中期写得更细，把后期写成更高层级的阶段目标与冲突推进，但整体方向必须完整。
7. 只输出 `{{"outline": ...}}` JSON 对象。"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": _framework_messages_with_long_form(
            "你是小说策划编辑。基于已有故事框架，只输出包含 outline 的 JSON 对象。",
            user_prompt,
        ),
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("outline", result)
    except ValueError as e:
        raise ValueError(f"Outline regeneration failed: {e}")


async def adjust_framework_with_chat(
    story_context: dict,
    messages: list[dict],
    api_key: str | None = None,
    required_min_chapters: int | None = None,
    existing_framework: dict | None = None,
) -> dict:
    """Return minimal, deterministic edit operations for the framework JSON."""
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
        raise ValueError("At least one chat message is required")

    min_chapter_requirement = (
        f"\n- 如果用户要求至少 {required_min_chapters} 章，你必须用多条 upsert_chapter 操作真实创建或更新到该数量，不能只在 reply 里承诺。"
        if required_min_chapters and required_min_chapters >= 20
        else ""
    )

    system_prompt = """你是职业作者发布平台的“故事框架 JSON 编辑器”，不是泛泛聊天助手。
你的任务是读取现有框架 JSON，严格按作者最后的明确指令输出最小可执行补丁。

只允许输出 JSON 对象，格式：
{
  "reply": "一句话说明你实际准备改什么",
  "operations": [
    {"op": "set_description", "value": "新的作品描述"},
    {"op": "set_tags", "value": {"type": "...", "theme": "...", "style": "...", "audience": "..."}},
    {"op": "upsert_character", "name": "角色名", "value": {"name": "角色名", "role": "...", "arc": {}, "relationships": []}},
    {"op": "delete_character", "name": "角色名"},
    {"op": "upsert_act", "act": "阶段标识", "value": {"act": "阶段标识", "title": "...", "summary": "...", "key_events": []}},
    {"op": "delete_act", "act": "阶段标识"},
    {"op": "upsert_chapter", "chapter_number": 12, "act": "阶段标识", "value": {"title": "...", "summary": "...", "goal": "...", "conflict": "...", "hook": "...", "payoff": "...", "highlight": "...", "key_events": []}},
    {"op": "delete_chapter", "chapter_number": 12},
    {"op": "replace_outline_meta", "value": {"themes": [], "foreshadowing": [], "serial_strategy": {}}}
  ]
}

硬规则：
1. 只输出 operations，不要输出 changes/framework/完整故事框架。
2. 用户只要求局部修改时，只返回相关操作，不要重写无关角色、阶段或章节。
3. 不要为了“显得完整”扩写一大堆无关内容。精准执行比丰富更重要。
4. upsert_chapter 必须包含 chapter_number；章节号必须是数字。
5. 如果用户要求“第 N 章改成...”就只对第 N 章使用 upsert_chapter。
6. 如果用户要求新增后续章节，才追加新的 upsert_chapter。
7. 如果用户要求删除，使用 delete_* 操作，不要用空值覆盖。
8. 保留作者原设定，不主动改题材、主角、核心悬念，除非用户明确要求。
9. 禁止 Markdown、代码块、解释性前后缀。"""

    user_prompt = f"""请根据下面的对话，对现有小说框架 JSON 做精准补丁修改。

故事创意：{description}

当前框架 JSON：
{snapshot}

补丁要求：
- 按用户最后一条明确指令生成最小 operations。
- 所有 value 必须是可以直接写入当前框架 JSON 的干净结构。
- reply 只说明实际执行范围，不要说“我会”。
{min_chapter_requirement}"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": _framework_messages_with_long_form(system_prompt, user_prompt) + safe_messages,
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Framework adjustment failed: {e}")

    operations = result.get("operations") if isinstance(result.get("operations"), list) else []
    if not operations:
        raise ValueError("Framework adjustment failed: missing operations array")

    reply = str(result.get("reply") or "").strip() or "已根据你的建议调整框架。"
    return {"reply": reply, "operations": operations}


async def continue_framework(story_context: dict, api_key: str | None = None) -> dict:
    """Continue the framework without rushing to an ending.

    Returns {"reply": ..., "changes": {"outline": ..., "chapters": [...]}}
    where changes only contains the extended outline and chapters.
    """
    snapshot = _build_story_snapshot_tiered(story_context, "auto")
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": _framework_messages_with_long_form(
            (
                "你是一位资深小说策划编辑。请基于现有故事框架继续向后扩展剧情，"
                "补充后续大纲和后续章节规划。"
                "请始终输出一个 JSON 对象，格式为 "
                '{"reply":"...","changes":{"outline":{},"chapters":[]}}。'
                "changes 中只包含 outline 和 chapters。"
                "changes.outline 中每个 act（阶段）必须包含 title、summary 和 chapters 三个字段。"
                "章节编号必须严格延续现有主线，不要把故事过早收束。"
                "必须保留或补齐 outline.serial_strategy，并让新增章节尽量包含 goal、conflict、hook、payoff、highlight。"
            ),
            (
                "请在以下现有故事框架的基础上继续续写后续发展。\n\n"
                f"{snapshot}\n\n"
                "要求：\n"
                "1. 继续补完后续阶段、后续剧情推进和章节列表；\n"
                "2. 如有需要可以新增人物与势力，但不要删除原有主线；\n"
                "3. 不要把长篇故事压缩成短篇结局；\n"
                "4. 保持后续仍有升级、扩盘、反转和终局回收空间；\n"
                "5. 阶段结构不固定，不必强制写成三幕；\n"
                "6. 新增章节要更像作者可执行的任务卡，而不是只有标题。"
            ),
        ),
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Framework continuation failed: {e}")

    changes = result.get("changes") if isinstance(result.get("changes"), dict) else {}
    if not changes:
        raise ValueError("Framework continuation failed: missing changes object")

    reply = str(result.get("reply") or "").strip() or "已继续扩展后续大纲与章节规划。"
    return {"reply": reply, "changes": changes}


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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        return _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Chapter memory summarization failed: {e}")


async def expand_chapter_to_content(story_context: dict, chapter_info: dict, api_key: str | None = None, previous_chapter_summary: str = "") -> str:
    """Expand a chapter outline entry into full novel content using story framework constraints."""
    snapshot = _build_story_snapshot(story_context)
    chapter_details = json.dumps(chapter_info, ensure_ascii=False)

    previous_block = ""
    if previous_chapter_summary and previous_chapter_summary.strip():
        previous_block = f"\n## 上集回顾\n{previous_chapter_summary}\n"

    user_prompt = f"""请根据以下故事框架和章节信息，创作这一话的完整小说内容。

## 故事框架
{snapshot}

## 本章信息
{chapter_details}
{previous_block}
## ★★★ 字数要求（最高优先级）★★★
- 每一话控制在 2000 字左右（1700-2500 字范围）。这是硬性要求，不可商量。
- 低于 1500 字则内容过于单薄，必须回去补充描写；超过 3000 字则过于冗长，需要精简。
- 2000 字左右要写出完整且有感染力的章节，不能因为字数少就敷衍了事。

## 写作指导
- 本章通常包含 2-3 个场景：开篇快速切入（400-600 字）→ 核心推进（600-1000 字，细致描写人物互动、冲突）→ 收束落点（400-600 字，情绪沉淀或悬念）
- 请根据本章在故事大纲中的位置（所属幕、关键事件），合理推进剧情
- 角色行为需符合角色设定和角色弧线
- 如果上下文中包含"导入作品作者约束"或"作品圣经紧凑摘要"，优先遵守其中的必须保留项、后续目标和调整范围
- 描写要细腻有穿透力，关键处深化，过渡处从简。每一个细节服务于"塑造人物"或"推进剧情"
- 请直接输出小说正文，不要加额外说明或字数统计。"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位才华横溢、文笔细腻的网络小说家。请严格遵循故事框架约束，创作符合大纲要求的小说内容。\n\n"
                    "## 章节间连续性\n"
                    "本章开头必须自然衔接上一章结尾的情境。请参考下方\u201c前情提要\u201d中的故事状态和近期章节摘要，"
                    "确保本章与已发布章节在剧情推进、角色状态、悬念等方面无缝衔接。"
                    "只能参考已实际发生的剧情事实，不得编造或虚构未发生的前情事件。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 6144,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def rewrite_selection(
    selected_text: str,
    chapter_context: str,
    story_context: dict | None = None,
    api_key: str | None = None,
) -> str:
    """Rewrite a selected portion of novel text with improved quality."""
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
- 如作品圣经、角色设定、故事大纲与片段细节存在冲突，优先遵守最新的作品圣经和故事约束
- 提升描写的细腻度和画面感
- 增强人物微表情、小动作、心理活动的描写
- 优化句式节奏，避免单调
- 直接输出改写后的文本，不要加额外说明"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位资深小说编辑，擅长在不改变情节的前提下提升文笔质量。"},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 8192,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def adjust_chapter_content(
    story_context: dict,
    chapter_info: dict,
    chapter_content: str,
    instruction: str,
    api_key: str | None = None,
) -> str:
    """Adjust the full chapter content according to a user instruction."""
    snapshot = _build_story_snapshot_tiered(story_context, "auto")
    chapter_details = json.dumps(chapter_info, ensure_ascii=False)

    user_prompt = f"""请根据以下故事框架、章节信息、当前正文和修改要求，直接改写整章正文。

## 故事框架
{snapshot}

## 本章信息
{chapter_details}

## 当前正文
{chapter_content}

## 用户修改要求
{instruction}

## 改写要求
- 保留当前章节已经成立的主要剧情信息，除非用户明确要求重做
- 优先根据用户要求调整节奏、情绪、冲突、人物互动、伏笔、描写重点
- 保持人物设定、世界观和大纲约束一致
- 直接输出修改后的完整正文，不要解释，不要摘要，不要额外说明"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位资深网文编辑，擅长根据编辑意见直接修改整章正文，并保持剧情与设定统一。字数控制在2000字左右。"},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 6144,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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
1. 如果它是 `outline_source`，不要把“故事总览 / 世界观设定 / 角色设定 / 分卷大纲 / 节奏建议 / 亮点 / 写作提醒”之类标题当成真实章节。
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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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

ONBOARDING_SYSTEM_PROMPT = """你是「灵感捕手」——一位资深的小说创作顾问，擅长通过对话引导作者梳理创意。

## 你的定位
你不是表单填写工具，而是一个有温度的创作伙伴。通过自然对话，帮作者把模糊的想法变成清晰可执行的创作方向。

## 引导流程（共5步）
你需要在对话中渐进式收集信息，不要一次性问完所有问题：

### 第1步：故事概念
用温暖、开放的方式邀请作者描述ta想写的故事。比如：
- "说说你想写一个怎样的故事？"
- "主角是什么样的人？"
- "大概会发生什么？"

### 第2步：题材与读者方向
在作者描述后，判断适合的题材方向并让作者确认：
- 判断方向：男频 / 女频 / 轻小说 / 悬疑 / 群像 / 其他
- 语气应是："听起来你的故事更偏向XXX风格，是这样吗？"

### 第3步：核心卖点
帮作者提炼最吸引人的亮点：
- 是主角设定特别？
- 世界观机制有趣？
- 爽点机制独特？
- 还是谜题设计精妙？

### 第4步：目标体量
了解作者想写多长：
- 短篇（10-30章）
- 中篇（50-100章）
- 长篇（200-300章）
- 超长篇（500章起）

### 第5步：必须保留的设定
了解哪些设定是作者绝不希望被改掉的：
- 后期真相
- 关键角色关系
- 特殊世界规则
- 结局方向

## 对话原则
1. 每次只推进1个步骤，不要跳步
2. 用自然语言提问，不要列出结构化表单
3. 在用户回答后，先肯定/理解，再自然过渡到下一个问题
4. 当用户给出足够信息时，可以简要总结ta说的内容再问下一个
5. 保持亲切、鼓励的语气，尊重作者的每一个创意
6. 在每步结束时，把收集到的信息更新到 collected_info 中

## 输出格式
你必须始终输出JSON格式的回复：
{
  "reply": "你给用户的自然语言回复",
  "collected_info": {
    "story_concept": "已收集的故事概念",
    "genre_audience": "已确定的题材方向",
    "core_hook": "已提炼的核心卖点",
    "target_length": "已确定的目标体量",
    "must_keep": "已记录的必保留设定"
  },
  "step": 当前步骤编号(1-5),
  "total_steps": 5,
  "is_complete": false
}

当5步全部完成时，设置 is_complete: true，并在 reply 中总结所有收集到的信息，邀请用户进入确认环节。"""


async def generate_onboarding_response(
    messages: list[dict],
    previous_collected_info: dict[str, str] | None = None,
    current_step: int | None = None,
    api_key: str | None = None,
    max_retries: int = 2,
) -> dict:
    """生成引导建书对话中 AI 的下一轮回复，含自动重试韧性"""
    last_error: Exception | None = None
    current_snapshot = json.dumps(previous_collected_info or {}, ensure_ascii=False)
    step_hint = int(current_step or _infer_onboarding_next_step(previous_collected_info or {}))
    onboarding_state_hint = (
        "\n\n## 当前已确认信息\n"
        f"- current_step: {step_hint}\n"
        f"- current_collected_info: {current_snapshot}\n"
        "请在此基础上更新 collected_info。对于“是的/嗯/对”这类确认回答，不要把这些确认词直接写入字段，"
        "而应保留上一轮你已经判断出的内容。"
    )

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": ONBOARDING_SYSTEM_PROMPT + onboarding_state_hint},
                    *messages,
                ],
                "stream": False,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            }

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

            try:
                result = _extract_json_object(content)
            except ValueError:
                fallback = _build_onboarding_fallback_response(
                    messages,
                    content,
                    previous_collected_info=previous_collected_info,
                    current_step=current_step,
                )
                if fallback.get("reply"):
                    return fallback
                raise

            # 验证必要字段
            reply = result.get("reply", "")
            if not reply.strip():
                raise ValueError("Empty reply from AI")

            return {
                "reply": reply,
                "collected_info": result.get("collected_info", {}),
                "step": int(result.get("step", 1)),
                "total_steps": int(result.get("total_steps", 5)),
                "is_complete": bool(result.get("is_complete", False)),
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


IMPORT_CONTEXT_SYSTEM_PROMPT = """你是一位职业网文策划编辑，正在帮助作者补充“导入作品”的创作上下文。

你的目标不是重新立项，而是围绕作者已经导入的大纲/正文，快速补齐后续创作最关键的信息。

请严格遵守：
1. 一次只追问一个最关键的问题，避免长篇分析。
2. 优先确认：导入内容类型、必须保留项、后续创作目标、允许调整范围。
3. 语气专业、简洁，适合熟练作者快速填写。
4. 输出 JSON 对象，字段必须包含：
{
  "reply": "给作者的简短回复",
  "collected_info": {
    "import_material_type": "",
    "must_keep": "",
    "author_goal": "",
    "adjustment_scope": "",
    "longline_plan": "",
    "tone_guardrails": ""
  },
  "step": 1,
  "total_steps": 4,
  "is_complete": false
}
5. 如果作者只是在确认、补充或修正，保留已经收集到的有效信息，不要被“是/对/可以”覆盖掉。
6. 当以下四项都已经明确时，可视为完成：
   - import_material_type
   - must_keep
   - author_goal
   - adjustment_scope
7. longline_plan 和 tone_guardrails 有则记录，没有也可以完成。"""


async def generate_import_guidance_response(
    messages: list[dict[str, str]],
    import_context: dict[str, Any],
    previous_collected_info: dict[str, Any] | None = None,
    current_step: int | None = None,
    api_key: str | None = None,
    max_retries: int = 2,
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
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": IMPORT_CONTEXT_SYSTEM_PROMPT + runtime_hint},
                    *messages,
                ],
                "stream": False,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            }

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

            result = _extract_json_object(content)
            reply = str(result.get("reply") or "").strip()
            if not reply:
                raise ValueError("Empty reply from AI")

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


BUILD_IMPORT_BRIEF_PROMPT = """你是一位职业网文策划编辑。现在作者已经导入了一部已有作品，请基于“导入内容摘要”和“作者补充要求”，生成一份结构化的创意理解卡。

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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
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
        "model": DEEPSEEK_MODEL,
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
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    try:
        result = _extract_json_object(content)
        return result.get("story_bible", result)
    except ValueError as e:
        raise ValueError(f"Story Bible generation failed: {e}")
