"""画布助手的文本化读取能力：大纲、搜索、按字段精读、节点生成状态。

对齐 Codex / OpenCode 一类编码 agent 的工作方式：
  大纲（≈ ls/tree）→ 搜索（≈ grep）→ 精读指定节点与字段（≈ 按行读文件）→ 带差异预览地修改（≈ apply_patch）。
节点有没有出图、是否失败、产物是否已随提示词修改而过期，都以文本状态给出；
只有需要判断画面是否符合提示词、质量是否过关时，才调用 inspect_canvas_media 看图。
"""

from __future__ import annotations

import json
import re
from typing import Any

from models import VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion
from services.canvas_ops_preview import node_fingerprint

MEDIA_NODE_TYPES = {"image", "video", "image_generation", "storyboard", "video_generation", "concat"}
_PROMPT_KEYS = ("prompt", "content", "storyboard_prompt", "video_prompt", "text")
_STATUS_LABELS = {
    "succeeded": "已生成",
    "failed": "失败",
    "running": "生成中",
    "queued": "排队中",
    "awaiting_approval": "待确认",
    "cancelled": "已取消",
    "cancel_requested": "取消中",
    "skipped": "已跳过",
}


def _data(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("data") if isinstance(node.get("data"), dict) else {}


def _config(node: dict[str, Any]) -> dict[str, Any]:
    config = _data(node).get("config")
    return config if isinstance(config, dict) else {}


def primary_text(node: dict[str, Any]) -> str:
    """节点的主要文本（提示词 / 剧本正文等），用于大纲摘要与搜索。"""
    config = _config(node)
    for key in _PROMPT_KEYS:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _definition_hash(graph: dict[str, Any], node_id: str) -> str | None:
    node = next((item for item in graph.get("nodes", []) if isinstance(item, dict) and str(item.get("id")) == node_id), None)
    return node_fingerprint(node) if node else None


def node_status_map(db, canvas_id: int, graph: dict[str, Any], node_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """每个媒体节点最近一次生成尝试的文本状态（不读图片文件）。

    stale=True 表示产物是按旧的节点定义生成的（之后改过提示词/配置），画面不能代表当前提示词。
    """
    wanted = {
        str(node.get("id"))
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("type") in MEDIA_NODE_TYPES
    }
    if node_ids is not None:
        wanted &= {str(item) for item in node_ids}
    if not wanted:
        return {}
    runs = (
        db.query(VideoCanvasRun)
        .filter(VideoCanvasRun.canvas_id == canvas_id)
        .order_by(VideoCanvasRun.id.desc())
        .limit(50)
        .all()
    )
    found: dict[str, tuple[Any, Any]] = {}
    for run in runs:
        remaining = wanted - set(found)
        if not remaining:
            break
        rows = (
            db.query(VideoCanvasRunNode)
            .filter(VideoCanvasRunNode.run_id == run.id, VideoCanvasRunNode.node_id.in_(remaining))
            .order_by(VideoCanvasRunNode.attempt.desc(), VideoCanvasRunNode.id.desc())
            .all()
        )
        for row in rows:
            found.setdefault(row.node_id, (run, row))
    version_graphs: dict[int, dict[str, Any]] = {}
    result: dict[str, dict[str, Any]] = {}
    for node_id in wanted:
        if node_id not in found:
            result[node_id] = {"status": "not_generated", "status_label": "未生成"}
            continue
        run, row = found[node_id]
        if run.canvas_version_id not in version_graphs:
            version = db.get(VideoCanvasVersion, run.canvas_version_id) if run.canvas_version_id else None
            version_graphs[run.canvas_version_id] = version.graph_json if version and isinstance(version.graph_json, dict) else {}
        run_hash = _definition_hash(version_graphs[run.canvas_version_id], node_id)
        output = row.output_snapshot_json if isinstance(row.output_snapshot_json, dict) else {}
        entry: dict[str, Any] = {
            "status": row.status,
            "status_label": _STATUS_LABELS.get(row.status, row.status),
            "run_id": run.id,
            "has_media": bool(output.get("url") or output.get("file_path") or output.get("asset_id")),
            "stale": bool(run_hash and run_hash != _definition_hash(graph, node_id)),
        }
        if row.error_message:
            entry["error"] = str(row.error_message)[:200]
        if output.get("url"):
            entry["media_url"] = output.get("url")
        result[node_id] = entry
    return result


def build_outline(
    graph: dict[str, Any],
    statuses: dict[str, dict[str, Any]],
    *,
    node_types: list[str] | None = None,
    status_filter: list[str] | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    """画布大纲：每个节点一行的关键信息，不含提示词全文。"""
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    incoming: dict[str, int] = {}
    outgoing: dict[str, int] = {}
    for edge in edges:
        incoming[str(edge.get("target"))] = incoming.get(str(edge.get("target")), 0) + 1
        outgoing[str(edge.get("source"))] = outgoing.get(str(edge.get("source")), 0) + 1
    type_set = {str(item) for item in node_types or [] if str(item).strip()}
    status_set = {str(item) for item in status_filter or [] if str(item).strip()}
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for node in nodes:
        node_id = str(node.get("id"))
        node_type = str(node.get("type"))
        counts[node_type] = counts.get(node_type, 0) + 1
        status = statuses.get(node_id)
        if type_set and node_type not in type_set:
            continue
        if status_set and (not status or status.get("status") not in status_set) and not ("stale" in status_set and status and status.get("stale")):
            continue
        text = primary_text(node)
        row: dict[str, Any] = {
            "id": node_id,
            "type": node_type,
            "label": _data(node).get("label"),
            "text_head": text[:60] + ("…" if len(text) > 60 else ""),
            "text_chars": len(text),
            "in": incoming.get(node_id, 0),
            "out": outgoing.get(node_id, 0),
        }
        if status:
            row["status"] = status["status_label"] + ("（产物已过期）" if status.get("stale") else "")
            if status.get("error"):
                row["error"] = status["error"]
        if _config(node).get("stale"):
            row["node_stale"] = True
        rows.append(row)
    total = len(rows)
    page = rows[max(0, offset): max(0, offset) + max(1, limit)]
    return {
        "total_nodes": len(nodes),
        "type_counts": counts,
        "matched": total,
        "offset": offset,
        "returned": len(page),
        "has_more": offset + len(page) < total,
        "nodes": page,
        "edge_count": len(edges),
    }


def _flatten_fields(node: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    label = _data(node).get("label")
    if isinstance(label, str):
        fields.append(("label", label))
    for key, value in _config(node).items():
        if isinstance(value, str):
            fields.append((key, value))
        elif isinstance(value, (dict, list)):
            fields.append((key, json.dumps(value, ensure_ascii=False)))
    return fields


def search_nodes(
    graph: dict[str, Any],
    query: str,
    *,
    regex: bool = False,
    node_types: list[str] | None = None,
    fields: list[str] | None = None,
    limit: int = 50,
    context_chars: int = 40,
) -> dict[str, Any]:
    """在节点标题与配置里搜索（≈ grep），返回命中的节点、字段与上下文片段。"""
    query = str(query or "").strip()
    if not query:
        return {"error": "query 不能为空"}
    try:
        pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    except re.error as exc:
        return {"error": f"正则表达式无效：{exc}"}
    type_set = {str(item) for item in node_types or [] if str(item).strip()}
    field_set = {str(item) for item in fields or [] if str(item).strip()}
    matches: list[dict[str, Any]] = []
    total = 0
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if type_set and str(node.get("type")) not in type_set:
            continue
        for field, text in _flatten_fields(node):
            if field_set and field not in field_set:
                continue
            for match in pattern.finditer(text):
                total += 1
                if len(matches) >= limit:
                    continue
                start = max(0, match.start() - context_chars)
                end = min(len(text), match.end() + context_chars)
                matches.append({
                    "node_id": node.get("id"),
                    "type": node.get("type"),
                    "label": _data(node).get("label"),
                    "field": field,
                    "snippet": ("…" if start else "") + text[start:end] + ("…" if end < len(text) else ""),
                    "offset": match.start(),
                })
    return {"query": query, "total_matches": total, "returned": len(matches), "truncated": total > len(matches), "matches": matches}


def select_fields(node: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """按字段精读（≈ 只读文件的某几行）：fields 为空时返回完整 data。"""
    data = _data(node)
    wanted = [str(item) for item in fields or [] if str(item).strip()]
    if not wanted:
        return data
    config = _config(node)
    picked: dict[str, Any] = {}
    missing: list[str] = []
    for key in wanted:
        if key == "label":
            picked["label"] = data.get("label")
        elif key in config:
            picked[key] = config[key]
        else:
            missing.append(key)
    result: dict[str, Any] = {"label": data.get("label"), "config": picked, "available_fields": sorted(config)}
    if missing:
        result["missing_fields"] = missing
    return result
