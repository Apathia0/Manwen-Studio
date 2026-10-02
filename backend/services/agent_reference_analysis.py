"""参考素材（图片/视频关键帧）风格分析：独立于工具循环的预分析，结论持久化后供后续轮次复用。

设计要点：
- 预分析不带工具，因此可以放心开启模型思考；主 Agent 工具循环仍保持 thinking 关闭以保证工具协议稳定。
- 结论写入附件元数据，历史压缩后也不会丢失；后续轮次无需再次传图即可引用。
- 可通过环境变量 AGENT_VISION_BASE_URL / AGENT_VISION_MODEL / AGENT_VISION_API_KEY 配置独立视觉模型；
  配置后主模型即使不支持视觉，也能凭分析文本继续工作（图片不再进入主模型输入）。
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any

import httpx
from sqlalchemy.orm import Session

from models import AgentAttachment
from services.agent_media import multimodal_content

logger = logging.getLogger(__name__)

_ANALYSIS_MAX_CHARS = 3000
_BASE_OUTPUT_TOKENS = 6144
_MAX_OUTPUT_TOKENS = 24576

_ANALYSIS_SYSTEM_PROMPT = (
    "你是资深影视美术与视觉风格分析师。用户给出参考图片（或按时间顺序排列的视频关键帧），"
    "你要把它们的视觉风格拆解成可直接写进 AI 图片/视频生成提示词的要点。"
    "只描述画面中真实可见的内容，不要臆测看不到的信息（如音轨、对白、画外剧情）。"
)

_ANALYSIS_USER_PROMPT = (
    "请分析以下参考素材，并严格按下列小节输出（中文，总长不超过 1200 字）：\n"
    "【内容概述】画面主体、场景、动作。\n"
    "【画风与媒介】如 2D 赛璐璐/厚涂/写实摄影/3D 渲染/水彩等，线条与材质特征。\n"
    "【色彩与光影】主色调、对比度、光源方向与质感。\n"
    "【构图与镜头】景别、机位、透视、画幅感；视频请补充镜头运动与节奏。\n"
    "【人物与造型】发型、服饰、表情、比例特征（若有）。\n"
    "【氛围情绪】整体情绪基调。\n"
    "【风格关键词】不超过 40 个中文词，逗号分隔，可直接拼进提示词。\n"
    "【建议负面提示词】应避免的风格偏差，逗号分隔。\n"
    "用户补充说明：{user_text}"
)


def vision_model_config() -> dict[str, str] | None:
    """读取独立视觉模型配置；三项齐全才视为已配置。"""
    base_url = (os.getenv("AGENT_VISION_BASE_URL") or "").strip().rstrip("/")
    model = (os.getenv("AGENT_VISION_MODEL") or "").strip()
    api_key = (os.getenv("AGENT_VISION_API_KEY") or "").strip()
    if base_url and model and api_key:
        return {"base_url": base_url, "model": model, "api_key": api_key}
    return None


def is_visual_attachment(item: dict[str, Any]) -> bool:
    return item.get("media_kind") in {"image", "video"}


def _extract_content(data: dict[str, Any]) -> tuple[str, str | None]:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return str(content or "").strip(), choice.get("finish_reason")


async def analyze_reference_media(
    attachments: list[dict[str, Any]],
    *,
    user_text: str,
    api_key: str,
    base_url: str,
    model: str,
    headers_factory,
) -> dict[str, Any] | None:
    """调用（视觉）模型生成风格分析；任何失败都返回 None，由主流程按原路径继续。"""
    visual = [item for item in attachments if is_visual_attachment(item)]
    if not visual:
        return None
    vision = vision_model_config()
    target_base = vision["base_url"] if vision else base_url
    target_model = vision["model"] if vision else model
    target_key = vision["api_key"] if vision else api_key
    prompt = _ANALYSIS_USER_PROMPT.format(user_text=(user_text or "无").strip()[:500])
    try:
        user_content = multimodal_content(prompt, visual)
    except Exception as exc:
        logger.warning("参考素材预分析构建输入失败: %s", exc)
        return None

    max_tokens = _BASE_OUTPUT_TOKENS
    thinking_enabled = True
    for attempt in range(3):
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "max_tokens": max_tokens,
        }
        if thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    f"{target_base}/chat/completions",
                    json=payload,
                    headers=headers_factory(target_key),
                )
        except httpx.HTTPError as exc:
            logger.warning("参考素材预分析请求失败: %s", exc)
            return None
        if response.status_code in {400, 422}:
            if thinking_enabled:
                # 上游不接受 thinking 字段：关闭思考后重试一次。
                thinking_enabled = False
                continue
            logger.warning("参考素材预分析被上游拒绝 status=%s", response.status_code)
            return None
        if response.is_error:
            logger.warning("参考素材预分析上游错误 status=%s", response.status_code)
            return None
        text, finish_reason = _extract_content(response.json())
        if text:
            return {
                "analysis": text[:_ANALYSIS_MAX_CHARS],
                "used_vision_model": bool(vision),
                "thinking": thinking_enabled,
            }
        if finish_reason == "length" and max_tokens < _MAX_OUTPUT_TOKENS:
            # 思考占满输出预算导致正文为空：放大预算重试。
            max_tokens = min(_MAX_OUTPUT_TOKENS, max_tokens * 2)
            continue
        return None
    return None


def persist_reference_analysis(db: Session, attachment_ids: list[str], analysis: str) -> None:
    """把分析结论写入附件元数据（整体替换 JSON，保证 ORM 感知变更）。"""
    if not attachment_ids or not analysis:
        return
    stamp = datetime.datetime.utcnow().isoformat()
    for record in db.query(AgentAttachment).filter(AgentAttachment.id.in_(attachment_ids)).all():
        metadata = dict(record.metadata_json) if isinstance(record.metadata_json, dict) else {}
        metadata["reference_analysis"] = analysis
        metadata["reference_analyzed_at"] = stamp
        record.metadata_json = metadata
    db.commit()


def load_conversation_reference_analyses(
    db: Session,
    *,
    owner_user_id: int,
    story_id: int,
    conversation_id: int,
    exclude_ids: list[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """读取本会话此前已分析过的参考素材，按分析文本去重，最新在前。"""
    excluded = set(exclude_ids or [])
    records = (
        db.query(AgentAttachment)
        .filter(
            AgentAttachment.owner_user_id == owner_user_id,
            AgentAttachment.story_id == story_id,
            AgentAttachment.conversation_id == conversation_id,
        )
        .order_by(AgentAttachment.created_at.desc())
        .all()
    )
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        if record.id in excluded:
            continue
        metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
        analysis = str(metadata.get("reference_analysis") or "").strip()
        if not analysis or analysis in seen:
            continue
        seen.add(analysis)
        result.append({
            "attachment_id": record.id,
            "filename": record.original_name,
            "media_kind": metadata.get("media_kind", "image"),
            "analysis": analysis,
        })
        if len(result) >= limit:
            break
    return result


def format_reference_context(items: list[dict[str, Any]], *, title: str) -> str:
    """把分析结论格式化为注入系统上下文的文本。"""
    if not items:
        return ""
    blocks = [f"### {item['filename']}（{item['media_kind']}）\n{item['analysis']}" for item in items]
    return (
        f"\n\n## {title}\n"
        "以下是对用户参考素材的风格分析结论。需要“按参考图风格优化节点提示词”时以此为准："
        "只替换/补充画风、色彩、光影、镜头、材质等风格描述，保持节点原有的主体与剧情。\n"
        + "\n\n".join(blocks)
    )
