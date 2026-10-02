"""画布级风格：整张画布统一的画风（风格预设或自定义参考图），用于保证资产、分镜、视频画面不飘。

存放在图的 metadata.canvas_style，结构与节点级风格字段一致：
  style_preset_id / style_snapshot / style_reference_asset_id / style_reference_url
节点自己设置了风格（预设或参考图）时优先用节点的；否则在运行时补入画布风格。
风格也参与"定义指纹"，所以更换风格后，旧风格生成的结果不会被误当成可复用输出。
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

STYLE_KEYS = ("style_preset_id", "style_snapshot", "style_reference_asset_id", "style_reference_url")
# 只有这些节点会生成画面，风格只对它们生效
STYLED_NODE_TYPES = frozenset({"image", "video", "image_generation", "storyboard", "video_generation"})


def raw_canvas_style(graph: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """读取 metadata 里保存的画布风格原始数据（不看开关），用于展示与提示。"""
    metadata = (graph or {}).get("metadata")
    raw = metadata.get("canvas_style") if isinstance(metadata, Mapping) else None
    return raw if isinstance(raw, Mapping) else None


def describe_canvas_style(graph: Mapping[str, Any] | None) -> str:
    """给助手看的一句话：画布当前的画风与开关状态，避免助手在提示词里重复或另起画风。"""
    raw = raw_canvas_style(graph)
    if raw is None:
        return "画布画风：用户还没有选择。开始制作前请提醒用户选择画风（画布顶部的画风按钮），否则各图画风可能不一致。"
    snapshot = raw.get("style_snapshot") if isinstance(raw.get("style_snapshot"), Mapping) else None
    name = str((snapshot or {}).get("name") or "自定义参考图")
    if raw.get("enabled") is False:
        return f"画布画风：{name}（全局画风开关已关闭：未单独设置风格的图片和视频不会使用它）。"
    return f"画布画风：{name}（全局画风已开启：所有未单独设置风格的图片和视频会自动使用，提示词里无需再重复描述画风）。"


ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4")


def canvas_aspect(graph: Mapping[str, Any] | None) -> str | None:
    """读取画布级画面比例（开局选定，存在 metadata.production_settings.aspect_ratio）；未设置返回 None。"""
    metadata = (graph or {}).get("metadata") if isinstance((graph or {}).get("metadata"), Mapping) else {}
    settings = metadata.get("production_settings") if isinstance(metadata.get("production_settings"), Mapping) else {}
    value = str(settings.get("aspect_ratio") or "")
    return value if value in ASPECT_RATIOS else None


def describe_canvas_aspect(graph: Mapping[str, Any] | None) -> str:
    """给助手看的一句话：画布统一的画面比例，新建 / 调整图片与视频节点时必须沿用。"""
    aspect = canvas_aspect(graph)
    if aspect is None:
        return "画布画面比例：未设置，默认 16:9（横屏）。"
    return f"画布画面比例：{aspect}（用户已选定）。新建或调整图片、视频节点时 aspect_ratio 必须沿用它，canvas_stage 不要传 aspect_ratio；只有用户明确要求改某个节点的比例时才单独修改该节点。"


def canvas_style(graph: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """读取并校验画布风格；没有有效风格、或全局画风开关已关闭时返回 None。"""
    raw = raw_canvas_style(graph)
    if raw is None or raw.get("enabled") is False:
        return None
    snapshot = raw.get("style_snapshot")
    reference_id = raw.get("style_reference_asset_id")
    has_snapshot = isinstance(snapshot, Mapping) and bool(snapshot)
    has_reference = isinstance(reference_id, int) and not isinstance(reference_id, bool)
    if not has_snapshot and not has_reference:
        return None
    return {
        "style_preset_id": raw.get("style_preset_id") if isinstance(raw.get("style_preset_id"), int) else None,
        "style_snapshot": dict(snapshot) if has_snapshot else None,
        "style_reference_asset_id": reference_id if has_reference else None,
        "style_reference_url": str(raw.get("style_reference_url") or "") or None,
    }


def has_own_style(config: Mapping[str, Any]) -> bool:
    """节点是否自己设置了风格：设置过就不被画布风格覆盖。"""
    snapshot = config.get("style_snapshot")
    reference_id = config.get("style_reference_asset_id")
    return (isinstance(snapshot, Mapping) and bool(snapshot)) or (isinstance(reference_id, int) and not isinstance(reference_id, bool))


def apply_canvas_style(node_type: str, config: Mapping[str, Any], style: Mapping[str, Any] | None) -> dict[str, Any]:
    """返回补入画布风格后的配置副本；不需要补入时返回原配置的浅拷贝。"""
    result = dict(config)
    if not style or node_type not in STYLED_NODE_TYPES or has_own_style(result):
        return result
    for key in STYLE_KEYS:
        if style.get(key) is not None:
            result[key] = deepcopy(style[key])
    return result


# 提示词里的“风格行”：统一视觉风格 / 画面风格 / 画风 / 风格要求 / Visual style 等开头的整行
_STYLE_LINE = re.compile(r"(?im)^[ \t]*(?:统一视觉风格|视觉风格|画面风格|整体画风|画风|风格要求|风格预设|visual\s*style|art\s*style)[ \t]*[:：].*(?:\n|$)")
_STYLE_TAG = re.compile(r"\s*\|?\s*【风格】[^|\n]*")


def strip_style_text(prompt: str) -> str:
    """去掉提示词里的风格文字（风格行、【风格】标签）。

    画风只由风格参考图（图生图）控制，提示词只描述内容；否则旧的风格文字会压过参考图，
    用户中途更换风格参考图也不起作用。风格预设没有示例图时，运行时会按当前风格动态补一句文字，不依赖这里残留的旧文字。
    """
    text = _STYLE_TAG.sub("", _STYLE_LINE.sub("", str(prompt or "")))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def style_prompt_hint(style: Mapping[str, Any] | None) -> str:
    """给文本模型看的风格描述：预设名 + 风格提示词；只有参考图时说明以参考图为准。"""
    if not style:
        return ""
    snapshot = style.get("style_snapshot") if isinstance(style.get("style_snapshot"), Mapping) else None
    if snapshot:
        name = str(snapshot.get("name") or "").strip()
        template = str(snapshot.get("prompt_template") or "").strip()
        return "：".join(part for part in (name, template) if part)
    return "以用户上传的风格参考图为准"
