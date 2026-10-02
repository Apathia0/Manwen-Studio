"""画布智能连线：按规则补齐 / 重排节点之间的连线，并检查连线健康度。

适用场景：换了视频模型（参考图上限变了）、后来新增或重做了角色 / 场景资产、手动删错了线。
不调用模型、不生成、不扣费；先出预览（会新增 / 移除哪些线、还有哪些问题），确认后再写入新版本。

规则（与编排阶段一致）：
1. 场景节点 → 分镜图（shot → prompt）；
2. 分镜图 → 同一镜头的视频节点（image → image，必须排在视频的参考图连线最前面）；
3. 出场角色 / 场景 / 道具资产 → 分镜图的参考图；角色 / 场景 → 视频节点的参考图，
   数量按所选视频模型声明的上限分配（最大 9）。系统生成的资产连线每次整体重算，所以换模型后会自动裁剪或补齐；
   用户手动拉的线不会被动。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.canvas_stage_gateway import _bind_assets, _config, _connect, _video_reference_limit


def _label(node: dict[str, Any]) -> str:
    return str((node.get("data") or {}).get("label") or _config(node).get("asset_name") or node.get("id") or "")


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(edge.get("source")), str(edge.get("target")), str(edge.get("sourceHandle") or ""), str(edge.get("targetHandle") or ""))


def change_key(edge: dict[str, Any]) -> str:
    """一条变更的稳定标识（新增连线的 id 每次预览都会重新生成，不能当标识）：来源|目标|目标端口。"""
    return f"{edge.get('source')}|{edge.get('target')}|{edge.get('targetHandle') or ''}"


def apply_selection(original: dict[str, Any], planned: dict[str, Any], skip_added: set[str], skip_removed: set[str]) -> dict[str, Any]:
    """按用户的勾选结果取舍：不想新增的连线从新图里去掉，不想移除的连线放回去。返回新图，入参不被修改。"""
    result = deepcopy(planned)
    old_by_key = {change_key(e): e for e in original.get("edges") or [] if isinstance(e, dict)}
    new_keys = {change_key(e) for e in result.get("edges") or [] if isinstance(e, dict)}
    result["edges"] = [e for e in result.get("edges") or [] if not (isinstance(e, dict) and change_key(e) in skip_added and change_key(e) not in old_by_key)]
    for key in skip_removed:
        if key in old_by_key and key not in new_keys:
            result["edges"].append(deepcopy(old_by_key[key]))
    return result


def _live(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in graph.get("nodes") or [] if isinstance(n, dict) and not _config(n).get("stale")]


def _repair_structure(graph: dict[str, Any]) -> None:
    """补齐 场景 → 分镜图、分镜图 → 视频 这两类骨架连线（必须在重算资产连线之前，保证分镜图排在视频参考图最前）。"""
    nodes = _live(graph)
    edges = graph.setdefault("edges", [])
    # 判断"这条线是否已存在"时不看 sourceHandle：旧图 / 手动连线可能没写端口名
    existing = {(str(e.get("source")), str(e.get("target")), str(e.get("targetHandle") or "")) for e in edges}
    scenes = {n["id"]: n for n in nodes if n.get("type") == "scene"}
    storyboards = {
        (str(_config(n).get("source_scene_node")), str(_config(n).get("unit_id"))): n
        for n in nodes if n.get("type") == "image" and _config(n).get("node_role") == "storyboard" and _config(n).get("unit_id")
    }
    for board in storyboards.values():
        scene = scenes.get(str(_config(board).get("source_scene_node")))
        if scene and (scene["id"], board["id"], "prompt") not in existing:
            _connect(graph, scene, board, "shot", "prompt")
            existing.add((scene["id"], board["id"], "prompt"))
    for video in nodes:
        config = _config(video)
        if video.get("type") != "video" or not config.get("unit_id"):
            continue
        board = storyboards.get((str(config.get("source_scene_node")), str(config.get("unit_id"))))
        if board and (board["id"], video["id"], "image") not in existing:
            _connect(graph, board, video, "image", "image")
            existing.add((board["id"], video["id"], "image"))


def _health_issues(graph: dict[str, Any], db) -> list[dict[str, Any]]:
    """重算后仍然存在的问题：需要用户处理或只能提示。"""
    nodes = _live(graph)
    by_id = {n["id"]: n for n in graph.get("nodes") or [] if isinstance(n, dict)}
    edges = [e for e in graph.get("edges") or [] if isinstance(e, dict)]
    issues: list[dict[str, Any]] = []

    for edge in edges:
        if edge.get("source") not in by_id or edge.get("target") not in by_id:
            issues.append({"severity": "error", "code": "dangling_edge", "message": "有一条连线指向不存在的节点", "node_ids": []})
    outgoing = {e.get("source") for e in edges}
    for asset in nodes:
        config = _config(asset)
        if asset.get("type") == "image" and config.get("asset_role") in {"character", "scene", "prop"} and asset["id"] not in outgoing:
            kind = {"character": "角色", "scene": "场景", "prop": "道具"}[config["asset_role"]]
            issues.append({"severity": "info", "code": "orphan_asset", "message": f"{kind}「{config.get('asset_name') or _label(asset)}」没有被任何镜头使用", "node_ids": [asset["id"]]})

    character_by_name = {str(_config(n).get("asset_name")): n for n in nodes if n.get("type") == "image" and _config(n).get("asset_role") == "character"}
    for video in nodes:
        config = _config(video)
        if video.get("type") != "video" or not config.get("unit_id"):
            continue
        incoming = [e for e in edges if e.get("target") == video["id"] and e.get("targetHandle") == "image"]
        limit = _video_reference_limit(config, db)
        if len(incoming) > limit:
            issues.append({"severity": "warning", "code": "over_reference_limit", "message": f"{_label(video)} 连了 {len(incoming)} 张参考图，所选模型最多 {limit} 张，提交会失败，请删掉多余的连线", "node_ids": [video["id"]]})
        linked = {e.get("source") for e in incoming}
        names = [str(v.get("name") if isinstance(v, dict) else v) for v in config.get("characters", [])]
        dropped = [name for name in names if name in character_by_name and character_by_name[name]["id"] not in linked]
        if dropped:
            issues.append({"severity": "info", "code": "reference_slots_full", "message": f"{_label(video)} 受模型参考图上限 {limit} 张限制，未连接角色 {'、'.join(dropped)}", "node_ids": [video["id"]]})
        if not any(by_id.get(e.get("source"), {}).get("type") == "image" and _config(by_id[e["source"]]).get("node_role") == "storyboard" for e in incoming):
            issues.append({"severity": "warning", "code": "video_no_storyboard", "message": f"{_label(video)} 没有对应的分镜图，将按纯文字生成", "node_ids": [video["id"]]})
    return issues


def plan_smart_connect(graph: dict[str, Any], db=None) -> dict[str, Any]:
    """计算智能连线结果。入参不被修改；返回新图、新增 / 移除的连线说明，以及仍存在的问题。"""
    before = deepcopy(graph or {})
    after = deepcopy(before)
    _repair_structure(after)
    _bind_assets(after, db)

    nodes = {n["id"]: n for n in after.get("nodes") or [] if isinstance(n, dict)}
    old_keys = {_edge_key(e): e for e in before.get("edges") or [] if isinstance(e, dict)}
    new_keys = {_edge_key(e): e for e in after.get("edges") or [] if isinstance(e, dict)}

    def describe(edge: dict[str, Any], source_nodes: dict[str, Any]) -> dict[str, Any]:
        source, target = source_nodes.get(edge.get("source"), {}), source_nodes.get(edge.get("target"), {})
        return {
            "key": change_key(edge), "edge_id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target"),
            "source_handle": edge.get("sourceHandle") or "", "target_handle": edge.get("targetHandle") or "",
            "source_label": _label(source) if source else "", "target_label": _label(target) if target else "",
        }

    before_nodes = {n["id"]: n for n in before.get("nodes") or [] if isinstance(n, dict)}
    added = [describe(e, nodes) for key, e in new_keys.items() if key not in old_keys]
    removed = [describe(e, before_nodes) for key, e in old_keys.items() if key not in new_keys]
    return {"graph": after, "added": added, "removed": removed, "issues": _health_issues(after, db), "changed": bool(added or removed)}
