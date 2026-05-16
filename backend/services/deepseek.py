import json
import os
import re
from typing import AsyncGenerator

import httpx
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

NOVEL_SYSTEM_PROMPT = """你是一位才华横溢、文笔细腻的网络小说家。用户会和你讨论小说的主题、风格、角色等。

当用户要求你创作小说时，请遵循以下要求：

## ★★★ 字数要求（最高优先级）★★★
- 每一话必须 4000-6000 中文字。这是硬性要求，不可商量。
- 绝对禁止低于 3500 字。如果你感觉写完了但字数不够，必须回去扩写场景、增加对话、深化心理描写，直到达到 4000 字以上。
- 宁可 5000-6000 字，也不要只写 2000 字就结束。

## 结构指导（确保内容充实）
一话内容应包含 3-5 个完整场景，每个场景至少 800-1500 字，包含：
- 场景转换时的环境描写（视觉、听觉、嗅觉、触觉），至少 150 字
- 人物之间的对话（自然生动，有潜台词，每段对话至少 5-8 个来回）
- 角色的心理活动和内心独白（每个场景至少一段）
- 微表情、小动作、肢体语言的细节描写

## 写作风格
- 描写要细腻丰富，注重氛围营造
- 节奏有张有弛，关键情感节点放慢节奏
- 人物描写立体鲜活，注重微表情、小动作、心理独白
- 避免流水账，避免大段无意义的抽象拒述

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
        "max_tokens": 16384,
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
        "content": "请根据我们的讨论，创作这一话的完整小说内容。请直接输出小说正文。",
    })

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": full_messages,
        "stream": False,
        "max_tokens": 16384,
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


FRAMEWORK_SYSTEM_PROMPT = """你是一位资深的小说策划编辑，擅长为故事构建世界观、角色体系和故事大纲。

## 你的任务
根据用户提供的故事描述，生成完整的小说框架。请严格输出JSON格式，不要输出其他内容。

### 1. tags（标签）
故事的核心标签：
- type: 小说类型 (如"奇幻"、"科幻"、"悬疑"、"言情"、"武侠"等)
- theme: 核心主题 (如"成长"、"复仇"、"救赎"、"爱与牺牲"等)
- style: 写作风格 (如"细腻温情"、"磅礴大气"、"幽默风趣"、"黑暗压抑"等)
- audience: 目标读者 (如"青少年"、"成人"、"全年龄"等)

### 2. characters（角色）
生成3-6个核心角色，每个角色是一个包含以下字段的对象：
- name: 角色名
- role: 角色定位 (如"主角"、"反派"、"导师"、"伙伴"、"恋爱对象"等)
- big_five: 大五人格维度，对象格式 {"openness": 1-10, "conscientiousness": 1-10, "extraversion": 1-10, "agreeableness": 1-10, "neuroticism": 1-10}
- arc: 角色弧线，对象格式 {"start": "初始状态描述", "middle": "转折状态描述", "end": "最终状态描述"}
- relationships: 与其他角色的关系，数组格式 [{"to": "角色名", "type": "关系类型", "description": "关系描述"}]

### 3. outline（大纲）
故事大纲：
- three_acts: 三幕结构数组，每幕包含 {"act": 1|2|3, "title": "幕标题", "summary": "本幕概要", "key_events": ["关键事件1", "关键事件2", ...]}
- themes: 主题线索数组 ["主题1", "主题2"]
- foreshadowing: 伏笔数组 ["伏笔描述1", "伏笔描述2"]

### 4. chapters（章节规划）
- chapters: 章节数组，每章包含 {"chapter_number": 1, "title": "章节标题", "act": "所属幕", "key_events": ["关键事件"]}

JSON输出格式示例：
{
  "tags": {"type": "奇幻", "theme": "成长", "style": "细腻温情", "audience": "青少年"},
  "characters": [{"name": "主角名", "role": "主角", ...}],
  "outline": {"three_acts": [...], "themes": [...], "foreshadowing": [...]},
  "chapters": [{"chapter_number": 1, "title": "章节标题", "act": "第一幕", "key_events": [...]}]
}"""


# ─── Framework service functions ───────────────────────────

async def generate_framework(description: str, api_key: str | None = None) -> dict:
    """Generate a complete story framework: tags, characters, outline, chapters from a description."""
    user_prompt = f"""请根据以下故事描述，生成完整的小说框架：

{description}

请严格输出JSON格式（包含 tags, characters, outline, chapters 四个字段），不要输出其他内容。"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": FRAMEWORK_SYSTEM_PROMPT},
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
        raise ValueError(f"Framework generation failed: {e}")


def _build_story_snapshot(story_context: dict) -> str:
    """Build a textual snapshot of the current story context for regeneration prompts."""
    parts = []
    if story_context.get("tags"):
        parts.append(f"现有标签: {json.dumps(story_context['tags'], ensure_ascii=False)}")
    if story_context.get("characters"):
        parts.append(f"现有角色: {json.dumps(story_context['characters'], ensure_ascii=False)}")
    if story_context.get("outline"):
        parts.append(f"现有大纲: {json.dumps(story_context['outline'], ensure_ascii=False)}")
    if story_context.get("description"):
        parts.append(f"故事描述: {story_context['description']}")
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


async def regenerate_characters(story_context: dict, api_key: str | None = None) -> dict:
    """Regenerate only the characters based on existing story context."""
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成角色（characters）。

{snapshot}

请严格输出只包含 characters 的JSON对象，格式：{{"characters": [{{"name": "...", "role": "...", ...}}]}}"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是小说策划编辑。基于已有的故事框架，输出仅包含 characters 的JSON数组对象。"},
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
        raise ValueError(f"Character regeneration failed: {e}")


async def regenerate_outline(story_context: dict, api_key: str | None = None) -> dict:
    """Regenerate only the outline based on existing story context."""
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是故事当前的全部框架信息。请基于这些信息，重新生成大纲（outline）。

{snapshot}

请严格输出只包含 outline 的JSON对象，格式：{{"outline": {{"three_acts": [...], "themes": [...], "foreshadowing": [...]}}}}"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是小说策划编辑。基于已有的故事框架，输出仅包含 outline 的JSON对象。"},
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
        return result.get("outline", result)
    except ValueError as e:
        raise ValueError(f"Outline regeneration failed: {e}")


async def generate_character_profiles_from_framework(story_context: dict, api_key: str | None = None) -> str:
    """Generate manga-facing appearance cards from framework characters."""
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是当前故事的框架信息，请把其中的角色设定扩写成可直接用于漫画分镜与生图的固定角色外貌卡。

{snapshot}

要求：
1. 只输出纯文本，不要输出 JSON，不要解释。
2. 每个角色单独成段，必须覆盖当前故事里的所有核心角色。
3. 每个角色都要包含：角色名、性别/年龄感、体型、脸部特征、发色与发型、眼睛、常穿服装、配饰/武器、神态气质、动作习惯、漫画绘制注意点。
4. 要把小说角色性格映射成稳定外貌特征，例如冷静的人更克制、张扬的人更有攻击性视觉符号。
5. 描述必须具体、可视化、便于后续所有章节保持角色一致。
6. 如果原始框架没写明某个外貌细节，请基于题材和角色定位合理补全，但保持统一风格。

输出格式示例：
角色名：林墨
身份定位：主角
外貌描述：……
服装要点：……
气质与表情：……
绘制注意：……
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


async def adjust_framework_with_chat(story_context: dict, messages: list[dict], api_key: str | None = None) -> dict:
    """Adjust the existing framework based on iterative chat feedback."""
    snapshot = _build_story_snapshot(story_context)
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

    user_prompt = f"""请根据下面的小说创意，生成一个完整可用的小说框架 JSON。

故事创意：
{description}

硬性要求：
1. 顶层必须完整返回 `tags`、`characters`、`outline`、`chapters` 四个字段。
2. `tags` 里必须有非空的 `type`、`theme`、`style`、`audience`。
3. `characters` 必须有 3-6 个核心角色；每个角色都必须包含 `name`、`role`、`big_five`、`arc`、`relationships`。
4. `big_five` 必须完整包含 `openness`、`conscientiousness`、`extraversion`、`agreeableness`、`neuroticism`，分值为 1-10。
5. `outline.three_acts` 必须有 3 幕；每一幕都必须包含 `act`、`title`、`summary`、`key_events`、`chapters`。
6. 每一幕的 `chapters` 至少生成 2 个章节，章节对象必须包含 `chapter_number`、`title`、`summary`、`key_events`。
7. 顶层 `chapters` 必须是完整平铺的章节列表，覆盖所有幕中的章节，`chapter_number` 从 1 连续递增。
8. 不要返回空字符串、空数组占位，也不要省略任何字段。
9. 只输出 JSON，不要输出解释。
"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位小说策划编辑，正在和用户一起迭代小说框架。"
                    "你必须参考现有框架和对话历史，做增量调整，而不是完全偏离原设定。"
                    "请始终输出一个 JSON 对象，格式为"
                    '{"reply": "给用户的简短说明", "framework": {"description": "...", "tags": {...}, "characters": [...], "outline": {...}, "chapters": [...]}}。'
                    "reply 用自然中文简要说明这次改了什么、保留了什么。"
                    "framework 必须返回完整可用的最新框架。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "以下是当前故事框架，请以此为基础进行修改。\n\n"
                    f"{snapshot}\n\n"
                    "下面是我和你的最新讨论，请根据这些讨论调整框架。"
                ),
            },
            *safe_messages,
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
        result = _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Framework adjustment failed: {e}")

    framework = result.get("framework")
    if not isinstance(framework, dict):
        raise ValueError("Framework adjustment failed: missing framework object")

    reply = str(result.get("reply") or "").strip() or "已根据你的建议调整框架。"
    framework["description"] = str(framework.get("description") or story_context.get("description") or "").strip()
    return {"reply": reply, "framework": framework}


async def continue_framework(story_context: dict, api_key: str | None = None) -> dict:
    """Continue the existing story framework with new arcs, chapters, and characters when needed."""
    snapshot = _build_story_snapshot(story_context)
    user_prompt = f"""以下是当前故事的完整框架信息。请基于这些信息，重新生成一个完整的 `outline`。

{snapshot}

硬性要求：
1. 只输出一个包含 `outline` 的 JSON 对象。
2. `outline.three_acts` 必须包含 3 幕。
3. 每一幕都必须包含 `act`、`title`、`summary`、`key_events`、`chapters`。
4. 每一幕里的 `chapters` 至少有 2 个章节，每个章节都必须包含 `chapter_number`、`title`、`summary`、`key_events`。
5. 所有章节编号必须从 1 连续递增，且和三幕结构一致。
6. 不要省略章节列表。
"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位资深小说策划编辑。请基于现有故事框架继续往后扩展剧情，"
                    "补充后续大纲、后续章节规划，并在确有必要时新增角色或更新标签。"
                    "请始终输出一个 JSON 对象，格式为 "
                    '{"reply":"...", "framework":{"description":"...", "tags":{...}, "characters":[...], "outline":{...}, "chapters":[...]}}。'
                    "framework 中至少要包含可新增到现有故事后的大纲和章节规划。"
                    "章节编号必须严格延续现有最大 chapter_number 之后继续编号，不能重置或回退。"
                    "不要删掉原有设定，不要缩减已有章节，只做续写扩展。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请在以下现有故事框架的基础上继续续写后续发展。\n\n"
                    f"{snapshot}\n\n"
                    "要求：\n"
                    "1. 继续补完后续幕、后续剧情推进和章节列表；\n"
                    "2. 如果后续剧情需要新人物，请把新人物加入 characters；\n"
                    "3. 如果故事方向因此扩展，也可以微调 tags；\n"
                    "4. 不要删除现有章节和现有角色，只向后扩展。"
                ),
            },
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
        result = _extract_json_object(content)
    except ValueError as e:
        raise ValueError(f"Framework continuation failed: {e}")

    framework = result.get("framework")
    if not isinstance(framework, dict):
        raise ValueError("Framework continuation failed: missing framework object")

    reply = str(result.get("reply") or "").strip() or "已续写后续大纲与章节规划。"
    framework["description"] = str(framework.get("description") or story_context.get("description") or "").strip()
    return {"reply": reply, "framework": framework}


async def expand_chapter_to_content(story_context: dict, chapter_info: dict, api_key: str | None = None) -> str:
    """Expand a chapter outline entry into full novel content using story framework constraints."""
    snapshot = _build_story_snapshot(story_context)
    chapter_details = json.dumps(chapter_info, ensure_ascii=False)

    user_prompt = f"""请根据以下故事框架和章节信息，创作这一话的完整小说内容。

## 故事框架
{snapshot}

## 本章信息
{chapter_details}

## ★★★ 字数要求（最高优先级）★★★
- 必须 4000-6000 中文字。这是硬性要求，不可商量。
- 绝对禁止低于 3500 字。

## 写作指导
- 请根据本章在故事大纲中的位置（所属幕、关键事件），合理推进剧情
- 角色行为需符合角色设定和角色弧线
- 描写要细腻丰富，注重氛围营造
- 请直接输出小说正文，不要加额外说明或字数统计。"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位才华横溢、文笔细腻的网络小说家。请严格遵循故事框架约束，创作符合大纲要求的小说内容。"},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
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


async def rewrite_selection(selected_text: str, chapter_context: str, api_key: str | None = None) -> str:
    """Rewrite a selected portion of novel text with improved quality."""
    user_prompt = f"""请改写以下小说片段，保持原有情节和人物不变，但提升文笔质量：

## 章节上下文
{chapter_context if chapter_context else "无额外上下文"}

## 需要改写的文本
{selected_text}

## 改写要求
- 保持原有情节、人物对话和关键信息不变
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
        "max_tokens": 16384,
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
    snapshot = _build_story_snapshot(story_context)
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
            {"role": "system", "content": "你是一位资深网文编辑，擅长根据编辑意见直接修改整章正文，并保持剧情与设定统一。"},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
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
