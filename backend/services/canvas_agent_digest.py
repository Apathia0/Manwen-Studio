"""画布要点摘要：随每轮对话注入，让助手不必为“看一眼现状”反复调用读取工具。

只汇总图里已有的结构化信息（阶段进度、资产清单与出图状态、未建节点的候选资产），
不含提示词全文；节点内容仍以 get_canvas_nodes 精读为准。纯函数，不访问数据库。
"""
from __future__ import annotations

from typing import Any

_ROLE_ORDER = (("character", "角色"), ("prop", "道具"), ("scene", "场景"))
_MAX_ASSETS = 40


def _config(node: dict) -> dict:
    return (node.get("data") or {}).get("config") or {}


def _has_media(node: dict) -> bool:
    config = _config(node)
    result = (node.get("data") or {}).get("result")
    if isinstance(result, dict) and (result.get("url") or result.get("file_path") or result.get("asset_id")):
        return True
    if isinstance(config.get("asset_id"), int) and not isinstance(config.get("asset_id"), bool):
        return True
    return bool(config.get("existing_url") or config.get("preview_url"))


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def describe_canvas_digest(graph: dict | None) -> str:
    if not isinstance(graph, dict):
        return ""
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict) and not _config(n).get("stale")]
    if not nodes:
        return ""

    screenplays = [n for n in nodes if n.get("type") == "screenplay"]
    scenes = [n for n in nodes if n.get("type") == "scene"]
    assets = [n for n in nodes if n.get("type") == "image" and _config(n).get("asset_role") in {"character", "scene", "prop"}]
    boards = [n for n in nodes if n.get("type") == "image" and _config(n).get("node_role") == "storyboard"]
    videos = [n for n in nodes if n.get("type") == "video" and _config(n).get("unit_id")]
    concats = [n for n in nodes if n.get("type") == "concat"]

    approved = sum(1 for n in scenes if _config(n).get("approved"))
    directed = sum(1 for n in scenes if _config(n).get("director_plan"))
    parts = [
        f"剧本 {len(screenplays)}",
        f"场景审核 {len(scenes)}（已批准 {approved}，已导演编排 {directed}）",
        f"资产 {len(assets)}（已出图 {sum(1 for n in assets if _has_media(n))}）",
        f"分镜 {len(boards)}（已出图 {sum(1 for n in boards if _has_media(n))}）",
        f"视频 {len(videos)}（已生成 {sum(1 for n in videos if _has_media(n))}）",
    ]
    if concats:
        parts.append(f"合片 {len(concats)}（已生成 {sum(1 for n in concats if _has_media(n))}）")
    lines = ["## 画布要点（服务端按当前图汇总，可直接据此回答；要改节点内容再用 get_canvas_nodes 精读）", "阶段进度：" + " · ".join(parts)]

    listed = 0
    for role, label in _ROLE_ORDER:
        group = [n for n in assets if _config(n).get("asset_role") == role]
        if not group:
            continue
        items = []
        for n in group:
            if listed >= _MAX_ASSETS:
                break
            listed += 1
            items.append(f"{_clean(_config(n).get('asset_name') or (n.get('data') or {}).get('label'))}（{'已出图' if _has_media(n) else '未出图'}，{n.get('id')}）")
        lines.append(f"{label}资产：" + "、".join(items))
    if not assets and scenes:
        lines.append("资产：尚未建立资产节点")

    built = {(_config(n).get("asset_role"), _clean(_config(n).get("asset_name"))) for n in assets}
    missing: list[str] = []
    labels = {key: value for key, value in _ROLE_ORDER}
    for scene in scenes:
        for candidate in _config(scene).get("asset_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            name = _clean(candidate.get("name"))
            role = candidate.get("role")
            if name and (role, name) not in built:
                missing.append(f"{labels.get(role, '资产')}「{name}」")
    if missing:
        lines.append("已识别但未建节点的候选资产：" + "、".join(dict.fromkeys(missing)) + "（补建用 add_canvas_assets，不要用 canvas_stage(assets)）")
    return "\n".join(lines)
