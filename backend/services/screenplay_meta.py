"""剧本头部信息（标题、一句话梗概等）识别：这类行不是对白，也不是可拍摄的画面。

Agent 写的剧本常在正文前带"《标题》""一句话梗概：…"。它们含冒号，会被当成"说话人：台词"，
导致导演阶段要求把梗概当对白塞进镜头，时长永远不够而校验失败。这里统一识别并剔除。
"""

from __future__ import annotations

import re
from typing import Any

# 标签以这些词结尾即视为元信息（一句话梗概、故事简介、片名、题材、画幅、时长……）
_META_LABEL_SUFFIXES = ("梗概", "简介", "概要", "概述", "标题", "片名", "剧名", "题材", "类型", "风格", "画幅", "时长", "格式", "主题", "备注", "说明", "提示", "字数")
_META_LABELS = {"logline", "title", "synopsis", "genre", "style", "note", "notes"}
_TITLE_LINE_RE = re.compile(r"^\s*[《【\[].{1,40}[》】\]]\s*$")
_LABEL_LINE_RE = re.compile(r"^\s*([^\s：:，。！？]{1,16})\s*[:：]")


def is_meta_label(name: str) -> bool:
    """标签本身是否为元信息名称（用于说话人识别时排除）。"""
    text = str(name or "").strip()
    return text.lower() in _META_LABELS or text.endswith(_META_LABEL_SUFFIXES)


def is_meta_line(line: str) -> bool:
    """单行是否为标题行或"元信息标签：内容"行。"""
    text = str(line or "")
    if _TITLE_LINE_RE.match(text):
        return True
    match = _LABEL_LINE_RE.match(text)
    return bool(match and is_meta_label(match.group(1)))


def is_meta_text(text: str) -> bool:
    """整段文本的每个非空行都是元信息才算（混有真实台词或动作的不算）。"""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return bool(lines) and all(is_meta_line(line) for line in lines)


def strip_meta_beats(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回不含元信息节拍的场景副本；节拍全被剔除的场景整体丢弃。不修改入参。"""
    result: list[dict[str, Any]] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        beats = [b for b in scene.get("beats") or [] if isinstance(b, dict)]
        kept = [b for b in beats if not is_meta_text(str(b.get("source_text") or b.get("action") or ""))]
        if beats and not kept:
            continue
        result.append({**scene, "beats": kept})
    return result
