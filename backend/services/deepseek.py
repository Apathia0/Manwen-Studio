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
            pass

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
        if not match:
            raise ValueError("Response did not contain a JSON object") from first_error
        try:
            result = _loads_json_lenient(match.group(0))
            if isinstance(result, dict):
                return result
            raise ValueError("Extracted JSON is not an object")
        except json.JSONDecodeError as second_error:
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
