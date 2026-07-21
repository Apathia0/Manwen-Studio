"""漫画与视频共用的角色、场景、道具资产生成能力。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from . import image2


SUPPORTED_VISUAL_ROLES = {"character", "scene", "prop", "style"}


@dataclass(frozen=True)
class VisualReference:
    path: Path
    label: str
    role: str
    priority: int = 0
    is_required: bool = False


def normalize_visual_role(value: object) -> str:
    role = str(value or "").strip().lower().replace("_reference", "")
    return role if role in SUPPORTED_VISUAL_ROLES else "character"


def label_matches_visual_context(label: str, context_text: str) -> bool:
    if not label or not context_text:
        return False
    if label in context_text:
        return True
    return any(
        len(segment) >= 2 and segment in context_text
        for segment in (
            item.strip()
            for item in re.split(r"[·•・,、/／\s（）()\[\]【】]+", label)
        )
    )


def select_visual_references(
    context_text: str,
    entries: Iterable[Mapping[str, object]],
    *,
    max_items: int = 8,
) -> list[VisualReference]:
    """按分镜或镜头内容选择角色、场景、道具参考图。"""
    ranked: list[tuple[int, int, int, VisualReference]] = []
    for index, entry in enumerate(entries):
        raw_path = entry.get("path")
        path = raw_path if isinstance(raw_path, Path) else Path(str(raw_path or ""))
        if not str(raw_path or "").strip() or not path.exists():
            continue
        label = str(entry.get("label") or "").strip()
        role = normalize_visual_role(entry.get("kind") or entry.get("role"))
        required = bool(entry.get("is_required"))
        matches = bool(label and label_matches_visual_context(label, context_text or ""))
        if not (required or not label or matches):
            continue
        priority = int(entry.get("priority") or 0)
        rank = 3 if required else 2 if matches else 1
        ranked.append((rank, priority, -index, VisualReference(path, label, role, priority, required)))

    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2]))
    selected: list[VisualReference] = []
    seen: set[str] = set()
    for _, _, _, reference in ranked:
        key = str(reference.path.resolve())
        if key in seen:
            continue
        seen.add(key)
        selected.append(reference)
        if len(selected) >= max(1, max_items):
            break
    return selected


async def generate_visual_asset_image(
    *,
    prompt: str,
    output_path: Path,
    asset_type: str,
    api_key: str | None = None,
    size: str = "1920x1080",
    reference_paths: list[str] | None = None,
    reference_labels: list[str] | None = None,
    reference_roles: list[str] | None = None,
) -> str:
    """统一生成角色、场景或道具资产图，不注入任何风格预设。"""
    role = normalize_visual_role(asset_type)
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("视觉资产提示词不能为空")
    return await image2.generate_reference_image(
        prompt=clean_prompt,
        output_path=output_path,
        api_key=api_key,
        size=size,
        ref_image_paths=reference_paths or None,
        ref_type=role,
        ref_labels=reference_labels or None,
        ref_roles=reference_roles or None,
    )
