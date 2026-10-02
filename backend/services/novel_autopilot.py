"""Novel Autopilot V2 — 共享工具与 DeepSeek 调用封装。

所有 v2 服务模块均从此模块导入共享常量、鉴权函数和 AI 调用函数。
"""

import json
import os
import re
from typing import Any, AsyncGenerator

import httpx
from dotenv import load_dotenv

load_dotenv()

# ─── DeepSeek 连接配置（与 deepseek.py 保持同一模式）─────────────────────────

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"


# ─── 异常 ────────────────────────────────────────────────────────────────────


class MissingApiKeyError(RuntimeError):
    """上游 API Key 缺失时抛出。"""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(
            f"{provider} API Key 缺失，请在前端设置或后端 .env 中配置。"
        )


# ─── 鉴权 ────────────────────────────────────────────────────────────────────


def _deepseek_auth_headers(api_key: str | None = None) -> dict[str, str]:
    """构建 DeepSeek API 鉴权请求头。"""
    key = (api_key or DEEPSEEK_API_KEY or "").strip()
    if not key:
        raise MissingApiKeyError("DeepSeek")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ─── JSON 解析工具（与 deepseek.py 保持同一模式）─────────────────────────────


def _loads_json_lenient(text: str) -> Any:
    """宽松 JSON 解析，允许控制字符存在于带引号的字符串中。"""
    return json.loads(text, strict=False)


def _extract_json_object(raw: str) -> dict:
    """从 LLM 响应中提取 JSON 对象，去除 Markdown 围栏。"""
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
        raise ValueError("响应是合法 JSON 但不是对象")
    except json.JSONDecodeError as first_error:
        match = re.search(r"\{[\s\S]*\}", raw)
        candidate = match.group(0) if match else _extract_balanced_json_object_text(raw)
        if not candidate:
            raise ValueError("响应中未包含 JSON 对象") from first_error
        try:
            result = _loads_json_lenient(candidate)
            if isinstance(result, dict):
                return result
            raise ValueError("提取的 JSON 不是对象")
        except json.JSONDecodeError:
            balanced = _extract_balanced_json_object_text(candidate)
            if balanced and balanced != candidate:
                try:
                    result = _loads_json_lenient(balanced)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    pass
            raise ValueError("响应不是合法 JSON") from first_error


def _extract_balanced_json_object_text(raw: str) -> str | None:
    """手动扫描成对花括号，提取最外层 JSON 对象文本。"""
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
                return raw[start: idx + 1]
    return None


def _extract_json_array(raw: str) -> list:
    """从 LLM 响应中提取 JSON 数组。"""
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
            raise ValueError("响应中未包含 JSON 数组") from first_error
        try:
            return _loads_json_lenient(match.group(0))
        except json.JSONDecodeError as second_error:
            raise ValueError("响应不是合法 JSON 数组") from second_error


# ─── System Prompt 构建 ──────────────────────────────────────────────────────


def _build_system_prompt(type: str, creative_profile: dict | None = None) -> str:
    """根据服务类型和创作画像，构建平台导向的系统提示。

    Args:
        type: 服务类型，如 "framework"、"opening"、"volume"、"chapter_goal"、"publishing"。
        creative_profile: 创作画像字典，包含 platform_mode、audience_mode、genre、pace_mode 等。

    Returns:
        针对该服务类型和平台模式的系统提示字符串。
    """
    profile = creative_profile or {}
    platform = (profile.get("platform_mode") or "通用").strip()
    audience = (profile.get("audience_mode") or "通用").strip()
    genre = (profile.get("custom_genre") or profile.get("genre") or "").strip()
    pace = (profile.get("pace_mode") or "适中").strip()
    target_length = (profile.get("target_length") or "").strip()
    goal = (profile.get("creation_goal") or "").strip()

    # 平台风格描述
    platform_style_map: dict[str, str] = {
        "起点读书": "- 节奏爽快，升级体系清晰，世界观架构宏大\n- 擅长埋设长期伏笔，适合 200 章以上的长篇连载\n- 重视战斗体系、等级制度、势力格局的完整性",
        "番茄小说": "- 开篇即高潮，前三章必须有强钩子\n- 节奏紧凑，每章结尾留悬念\n- 偏重情绪输出和即时爽感，适合快节奏连载",
        "晋江文学城": "- 情感描写细腻，注重人物关系和心理变化\n- 文笔要求较高，氛围感强\n- 情节推动以人物关系为核心",
        "纵横中文网": "- 东方玄幻、西方奇幻、历史军事等题材擅长\n- 世界观设定严谨，力量体系完整\n- 节奏稳健，偏重长篇铺垫",
        "飞卢小说网": "- 创意新颖，切入点刁钻\n- 节奏明快，爽点密集\n- 擅长脑洞大开的世界观设定",
        "豆瓣阅读": "- 偏重文学性和现实题材\n- 人物立体，情感真实\n- 不刻意追求爽感，注重故事内核",
        "微信读书": "- 适合各类题材，但要求质量稳定\n- 开篇吸引人，整体节奏把控好\n- 适合中长篇（30-150 章）完整故事",
        "个人创作": "- 以创作者的个性化表达为核心\n- 不限制平台格式要求\n- 保持创作自由度的同时注重故事完整性",
    }
    platform_desc = platform_style_map.get(platform, "- 保持创作自由度，注重故事完整性")

    # 受众模式描述
    audience_desc_map: dict[str, str] = {
        "大众向": "- 覆盖最广泛读者群体，避免过于小众或极端的设定",
        "女性向": "- 情感描写充分，人物关系细腻，注重角色互动氛围",
        "男性向": "- 节奏爽快，升级成长线清晰，冲突对抗激烈",
        "全年龄": "- 内容健康向上，适合各年龄段读者",
        "悬疑推理爱好者": "- 逻辑严密，线索铺垫充分，反转合理",
        "奇幻玄幻爱好者": "- 世界观宏大，力量体系完整，想象力丰富",
    }
    audience_desc = audience_desc_map.get(audience, "- 覆盖目标读者群体喜好")

    # 节奏模式描述
    pace_desc_map: dict[str, str] = {
        "极快": "- 开篇即爆发冲突，前三章完成铺垫\n- 每 3-5 章一个小高潮，每 10-15 章一个大高潮\n- 悬念密度极高，适合快节奏网文",
        "较快": "- 开篇有强吸引力，第一章内建立核心冲突\n- 每 5-8 章一个小高潮\n- 节奏明快但不失细节",
        "适中": "- 开篇有足够吸引力，前 3 章完成世界观和主角引入\n- 有张有弛，情节推进和细节描写平衡\n- 每 8-12 章一个小高潮",
        "较慢": "- 注重世界观的渐进展开和人物的深度刻画\n- 开篇可以较慢热，但必须有持续的吸引力\n- 适合高质量长篇创作",
        "史诗级": "- 慢热但宏大的叙事节奏，适合超长篇连载\n- 注重时代氛围、势力博弈和群像刻画\n- 每一卷都是独立又相互关联的史诗篇章",
    }
    pace_desc = pace_desc_map.get(pace, "- 节奏张弛有度，保证持续阅读吸引力")

    # 创作目标
    goal_desc = ""
    if goal:
        goal_desc = f"\n- 创作目标：{goal}"

    # 字数规模
    length_desc = ""
    if target_length:
        length_desc = f"\n- 总篇幅规划：{target_length}"

    type_prompts: dict[str, str] = {
        "framework": (
            "你是一位深谙网络小说平台的资深策划编辑，擅长为不同平台、不同受众群体量身定制"
            "世界观架构、角色体系和长篇连载大纲。"
        ),
        "opening": (
            "你是一位精通网文开篇节奏的资深编辑，擅长设计能最大化读者留存率的开篇方案。"
            "你知道不同类型平台对开篇的要求——有的需要前三章定生死，有的允许慢热但必须有持续的钩子。"
        ),
        "volume": (
            "你是一位经验丰富的长篇网文架构师，擅长将完整的故事规划拆分成多个彼此关联"
            "又各自独立的卷/篇章，确保每一卷都有完整的起承转合和持续吸引力。"
        ),
        "chapter_goal": (
            "你是一位细致的章节策划编辑，擅长为每个章节设计明确的目标和情感预期，"
            "确保每一章都推动故事前进、深化人物或制造悬念。"
        ),
        "publishing": (
            "你是一位熟悉各大网文平台投稿规则的出版策划编辑，擅长为故事包装出具"
            "吸引力的书名、简介、卖点和投稿方案。"
        ),
    }
    base_role = type_prompts.get(type, "你是一位资深网文创作专家。")

    return f"""{base_role}

## 平台与受众信息
- 目标平台：{platform}
- 目标受众：{audience}
- 题材类型：{genre or "未指定"}
- 节奏模式：{pace}{goal_desc}{length_desc}

## 平台风格要求
{platform_desc}

## 受众要求
{audience_desc}

{pace_desc}

## 输出要求
- 所有输出内容使用中文
- 严格按照指定的 JSON 格式输出，不要输出额外文字
- 确保内容适合长期连载，可持续创作
- 注重故事吸引力和平台匹配度
"""


# ─── AI 调用封装 ─────────────────────────────────────────────────────────────


async def _call_deepseek(
    messages: list[dict],
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 16384,
    response_format: dict | None = None,
) -> str:
    """非流式调用 DeepSeek API。

    Args:
        messages: 消息列表（通常已包含 system role）。
        api_key: DeepSeek API Key，不传则使用环境变量。
        temperature: 温度参数（0.0-1.0），默认 0.7。
        max_tokens: 最大输出 token 数，默认 16384。
        response_format: 可选的 response_format 参数，如 {"type": "json_object"}。

    Returns:
        AI 返回的文本内容。
    """
    payload: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_deepseek_stream(
    messages: list[dict],
    api_key: str | None = None,
) -> AsyncGenerator[str, None]:
    """流式调用 DeepSeek API。

    Args:
        messages: 消息列表（通常已包含 system role）。
        api_key: DeepSeek API Key，不传则使用环境变量。

    Yields:
        每段增量文本内容。
    """
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
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


def _build_story_snapshot(story_data: dict) -> str:
    """将故事数据字典转为文本快照，用于 AI prompt 上下文注入。

    Args:
        story_data: 包含 description、tags、characters、outline、chapters 等字段的字典。

    Returns:
        格式化后的文本摘要。
    """
    parts: list[str] = []
    if story_data.get("description"):
        parts.append(f"故事描述: {story_data['description']}")
    if story_data.get("tags"):
        parts.append(f"标签: {json.dumps(story_data['tags'], ensure_ascii=False)}")
    if story_data.get("characters"):
        parts.append(f"角色: {json.dumps(story_data['characters'], ensure_ascii=False)}")
    if story_data.get("outline"):
        parts.append(f"大纲: {json.dumps(story_data['outline'], ensure_ascii=False)}")
    if story_data.get("chapters"):
        chapters_info = [
            f"  第{c['chapter_number']}章: {c.get('title', '')}" for c in story_data["chapters"]
        ]
        parts.append(f"章节规划 ({len(story_data['chapters'])} 章):\n" + "\n".join(chapters_info))
    if story_data.get("opening_plan"):
        parts.append(f"开篇规划: {json.dumps(story_data['opening_plan'], ensure_ascii=False)}")
    if story_data.get("volumes"):
        parts.append(f"卷规划: {json.dumps(story_data['volumes'], ensure_ascii=False)}")
    if story_data.get("creative_profile"):
        parts.append(
            f"创作画像: {json.dumps(story_data['creative_profile'], ensure_ascii=False)}"
        )
    if story_data.get("publishing_package"):
        parts.append(
            f"发布包: {json.dumps(story_data['publishing_package'], ensure_ascii=False)}"
        )
    return "\n\n".join(parts)
