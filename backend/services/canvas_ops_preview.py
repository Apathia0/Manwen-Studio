"""画布变更预览：对比修改前后的图，生成逐节点、逐字段的前后差异，供用户确认前审阅。"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

# 单个字段预览的最大字符数，防止超长提示词撑爆审批卡片与数据库
_PREVIEW_VALUE_MAX_CHARS = 4000
# 视为"覆盖已有内容"的节点数据字段之外，其余字段（如 position）不算内容变更
_IGNORED_DATA_KEYS = {"result", "status", "runtime", "thumbnail"}


def node_fingerprint(node: dict[str, Any]) -> str:
    """节点内容指纹（忽略位置与运行产物），用于检测节点在读取后是否被改动。"""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    stable = {key: value for key, value in data.items() if key not in _IGNORED_DATA_KEYS}
    raw = json.dumps({"type": node.get("type"), "data": stable}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def operations_digest(operations: Any) -> str:
    """操作列表的稳定摘要，用于判断两次提案是否等价。"""
    raw = json.dumps(operations, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _PREVIEW_VALUE_MAX_CHARS:
        return value[:_PREVIEW_VALUE_MAX_CHARS] + "…（已截断）"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > _PREVIEW_VALUE_MAX_CHARS:
            return text[:_PREVIEW_VALUE_MAX_CHARS] + "…（已截断）"
    return value


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """把节点 data 展平成 路径→值，config 下一层展开，便于字段级对比。"""
    if isinstance(value, dict) and prefix in {"data", "data.config"}:
        for key, child in value.items():
            if prefix == "data" and key in _IGNORED_DATA_KEYS:
                continue
            _flatten(f"{prefix}.{key}", child, out)
        return
    out[prefix] = value


def _node_label(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(data.get("label") or node.get("id") or "")


def diff_graphs(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """对比前后两张图，返回可直接渲染的差异结构。"""
    before_nodes = {str(node.get("id")): node for node in before.get("nodes", []) if isinstance(node, dict)}
    after_nodes = {str(node.get("id")): node for node in after.get("nodes", []) if isinstance(node, dict)}
    items: list[dict[str, Any]] = []

    for node_id, node in after_nodes.items():
        if node_id not in before_nodes:
            flat: dict[str, Any] = {}
            _flatten("data", node.get("data") if isinstance(node.get("data"), dict) else {}, flat)
            items.append({
                "op": "add_node",
                "node_id": node_id,
                "label": _node_label(node),
                "type": node.get("type"),
                "changes": [{"field": key, "before": None, "after": _clip(value)} for key, value in flat.items() if value not in (None, "", {}, [])],
            })
            continue
        old = before_nodes[node_id]
        old_flat: dict[str, Any] = {}
        new_flat: dict[str, Any] = {}
        _flatten("data", old.get("data") if isinstance(old.get("data"), dict) else {}, old_flat)
        _flatten("data", node.get("data") if isinstance(node.get("data"), dict) else {}, new_flat)
        changes = [
            {"field": key, "before": _clip(old_flat.get(key)), "after": _clip(new_flat.get(key))}
            for key in sorted(set(old_flat) | set(new_flat))
            if old_flat.get(key) != new_flat.get(key)
        ]
        if changes:
            items.append({
                "op": "update_node",
                "node_id": node_id,
                "label": _node_label(old),
                "type": node.get("type"),
                "fingerprint_before": node_fingerprint(old),
                "changes": changes,
            })

    for node_id, node in before_nodes.items():
        if node_id not in after_nodes:
            items.append({
                "op": "delete_node",
                "node_id": node_id,
                "label": _node_label(node),
                "type": node.get("type"),
                "changes": [],
            })

    def edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(edge.get("source")),
            str(edge.get("target")),
            str(edge.get("sourceHandle") or ""),
            str(edge.get("targetHandle") or ""),
        )

    before_edges = {edge_key(edge): edge for edge in before.get("edges", []) if isinstance(edge, dict)}
    after_edges = {edge_key(edge): edge for edge in after.get("edges", []) if isinstance(edge, dict)}
    all_nodes = {**before_nodes, **after_nodes}

    def describe_edge(op: str, key: tuple[str, str, str, str]) -> dict[str, Any]:
        source, target = key[0], key[1]
        return {
            "op": op,
            "source": source,
            "target": target,
            "source_label": _node_label(all_nodes.get(source, {"id": source})),
            "target_label": _node_label(all_nodes.get(target, {"id": target})),
        }

    edge_items = [describe_edge("add_edge", key) for key in after_edges if key not in before_edges]
    edge_items += [describe_edge("delete_edge", key) for key in before_edges if key not in after_edges]

    return {
        "nodes": items,
        "edges": edge_items,
        "summary": {
            "added_nodes": sum(1 for item in items if item["op"] == "add_node"),
            "updated_nodes": sum(1 for item in items if item["op"] == "update_node"),
            "deleted_nodes": sum(1 for item in items if item["op"] == "delete_node"),
            "added_edges": sum(1 for item in edge_items if item["op"] == "add_edge"),
            "deleted_edges": sum(1 for item in edge_items if item["op"] == "delete_edge"),
        },
    }


def build_ops_preview(base_graph: dict[str, Any], operations: list[Any]) -> dict[str, Any]:
    """在基图副本上试运行操作并生成差异；操作无效时返回 errors，不抛异常。"""
    from routers.video_canvas import NODE_CATALOG
    from services.agent_service import _apply_canvas_ops_to_graph

    before = copy.deepcopy(base_graph) if isinstance(base_graph, dict) else {"nodes": [], "edges": []}
    after, errors = _apply_canvas_ops_to_graph(copy.deepcopy(before), operations, NODE_CATALOG)
    preview = diff_graphs(before, after)
    preview["errors"] = errors
    return preview


def operations_overwrite_existing(operations: Any) -> bool:
    """操作是否会覆盖或删除已有节点内容（此类操作即使在自动模式也必须先预览确认）。"""
    if not isinstance(operations, list):
        return False
    for op in operations:
        if not isinstance(op, dict):
            continue
        if op.get("op") == "delete_node":
            return True
        if op.get("op") == "update_node" and (op.get("data") or op.get("config")):
            return True
    return False


def describe_selected_nodes(graph: dict[str, Any], selected_ids: list[str], *, field_max_chars: int = 1500) -> str:
    """把用户在画布上选中的节点完整内容写入上下文，让助手无需猜测"这个节点"指哪个。"""
    nodes = {str(node.get("id")): node for node in graph.get("nodes", []) if isinstance(node, dict)}
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]

    def brief(node_id: str) -> str:
        node = nodes.get(node_id) or {}
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        return f"{data.get('label') or node_id}（{node.get('type')}，{node_id}）"

    blocks: list[str] = []
    for node_id in list(dict.fromkeys(str(item) for item in selected_ids))[:20]:
        node = nodes.get(node_id)
        if node is None:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        clipped = {
            key: (value[:field_max_chars] + "…" if isinstance(value, str) and len(value) > field_max_chars else value)
            for key, value in config.items()
        }
        upstream = [brief(str(edge.get("source"))) for edge in edges if str(edge.get("target")) == node_id]
        downstream = [brief(str(edge.get("target"))) for edge in edges if str(edge.get("source")) == node_id]
        blocks.append(
            f"- 节点 {node_id}｜类型 {node.get('type')}｜标题 {data.get('label') or '（无）'}｜指纹 {node_fingerprint(node)}\n"
            f"  配置: {json.dumps(clipped, ensure_ascii=False)}\n"
            f"  上游: {'；'.join(upstream) or '无'}\n"
            f"  下游: {'；'.join(downstream) or '无'}"
        )
    if not blocks:
        return ""
    return (
        "\n\n## 用户当前在画布上选中的节点\n"
        "用户说“这个/当前/选中的节点”“它”时，指的就是下列节点；除非用户明确点名其他节点，不得改动未选中的节点。\n"
        + "\n".join(blocks)
    )
