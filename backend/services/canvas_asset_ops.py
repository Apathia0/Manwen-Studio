"""画布资产补建：把「候选资产」或用户点名的新资产一次转成资产节点操作。

背景：canvas_stage(assets) 是整批重新分析，只处理分析入选的资产；未入选的候选（asset_candidates，
如“剑”）不会因为再跑一次阶段就变成节点，反而白白消耗一次分析并让助手误以为已补齐。
这里提供与界面“添加候选资产”一致、但更完整的确定性路径：建节点 + 自动连到文字里提到它的分镜/视频节点。

纯函数：只读传入的图，返回 apply_canvas_ops 可直接执行的操作与结构化回执，不访问数据库。
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

ROLES = ("character", "scene", "prop")
ROLE_LABEL = {"character": "角色", "scene": "场景", "prop": "道具"}
_ROLE_ALIASES = {
    "character": "character", "角色": "character", "人物": "character",
    "scene": "scene", "场景": "scene", "场地": "scene",
    "prop": "prop", "道具": "prop", "物品": "prop",
}


def _config(node: dict) -> dict:
    return (node.get("data") or {}).get("config") or {}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_role(value: Any) -> str | None:
    return _ROLE_ALIASES.get(_clean(value).lower()) if _clean(value) else None


def _pick_scene_node(graph: dict, scene_node_id: str | None) -> tuple[dict | None, str | None]:
    scenes = [n for n in graph.get("nodes", []) if isinstance(n, dict) and n.get("type") == "scene" and not _config(n).get("stale")]
    if scene_node_id:
        found = next((n for n in scenes if n.get("id") == scene_node_id), None)
        return (found, None) if found else (None, f"找不到场景审核节点 {scene_node_id}")
    if not scenes:
        return None, "画布上还没有场景审核节点，请先完成剧本拆分"
    if len(scenes) == 1:
        return scenes[0], None
    with_candidates = [n for n in scenes if _config(n).get("asset_candidates")]
    if len(with_candidates) == 1:
        return with_candidates[0], None
    ids = "、".join(str(n.get("id")) for n in scenes)
    return None, f"画布有多个场景审核节点（{ids}），请用 scene_node_id 指明要把资产补到哪一个"


def _asset_prompt(role: str, name: str, desc: str) -> str:
    tail = {
        "character": "全身正面站姿，干净背景，画面风格统一。",
        "scene": "无人物的空镜场景，画面统一。",
        "prop": "单个物体特写，干净背景。",
    }[role]
    head = {"character": "角色设定参考图", "scene": "空镜场景参考图", "prop": "道具参考图"}[role]
    return f"{head}：{name}。" + (f"{desc}。" if desc else "") + tail


def _node_id(scene_id: str, role: str, name: str) -> str:
    digest = hashlib.sha1(f"{scene_id}:{role}:{name}".encode("utf-8")).hexdigest()[:8]
    return f"ast-{scene_id}-{role}-{digest}"[:64]


def build_asset_operations(graph: dict, assets: Any, scene_node_id: str | None = None) -> dict[str, Any]:
    """生成补建资产的画布操作。

    assets: [{"name": "剑", "role": "prop", "description": "..."}]；role 可省略（取自候选资产）。
    返回 {operations, added, skipped, scene_node_id}；无法继续时返回 {"error": ...}。
    """
    from services.canvas_stage_gateway import (
        ASSET_CELL_W, ASSET_SCENE_GAP, SCENE_DEFAULT_W, _ASSET_COLUMN_ORDER, _avoid_overlaps, _bind_assets, _rect,
    )

    if not isinstance(assets, list) or not assets:
        return {"error": "assets 不能为空：请列出要补建的资产（name，必要时 role 与 description）"}
    if len(assets) > 20:
        return {"error": "一次最多补建 20 个资产，请分批"}
    scene, error = _pick_scene_node(graph, scene_node_id)
    if scene is None:
        return {"error": error}
    scene_id = str(scene["id"])
    scene_config = _config(scene)
    candidates = [c for c in (scene_config.get("asset_candidates") or []) if isinstance(c, dict)]
    candidate_by_name = {_clean(c.get("name")): c for c in candidates if _clean(c.get("name"))}

    working = copy.deepcopy(graph)
    nodes = working.setdefault("nodes", [])
    original_edge_ids = {str(e.get("id")) for e in working.get("edges", []) or []}
    settings = (working.get("metadata") or {}).get("production_settings") or {}
    aspect = str(settings.get("aspect_ratio") or "16:9")

    def live_assets() -> list[dict]:
        return [n for n in nodes if n.get("type") == "image" and not _config(n).get("stale") and _config(n).get("asset_role") in ROLES]

    added: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    new_nodes: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in assets:
        spec = raw if isinstance(raw, dict) else {"name": raw}
        name = _clean(spec.get("name"))
        if not name:
            skipped.append({"name": "", "reason": "缺少资产名称"})
            continue
        candidate = candidate_by_name.get(name) or {}
        role = normalize_role(spec.get("role")) or normalize_role(candidate.get("role"))
        if role is None:
            skipped.append({"name": name, "reason": "不在候选资产里，且没有给出 role（character 角色 / scene 场景 / prop 道具）"})
            continue
        key = (role, name)
        if key in seen:
            continue
        seen.add(key)
        existing = next((n for n in live_assets() if _config(n).get("asset_role") == role and _clean(_config(n).get("asset_name")) == name), None)
        if existing is not None:
            skipped.append({"name": name, "reason": f"已有{ROLE_LABEL[role]}资产节点 {existing.get('id')}，无需重复补建"})
            continue
        desc = _clean(spec.get("description")) or _clean(candidate.get("desc") or candidate.get("description"))
        scene_ids = [str(v) for v in (candidate.get("scene_ids") or spec.get("scene_ids") or [])]
        node = {
            "id": _node_id(scene_id, role, name),
            "type": "image",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": f"{ROLE_LABEL[role]}·{name}",
                "nodeType": "image",
                "config": {
                    "node_role": "asset", "asset_role": role, "asset_name": name, "manual_added": True,
                    "asset_scene_node": scene_id, "source_scene_node": scene_id, "scene_ids": scene_ids,
                    "prompt": _asset_prompt(role, name, desc), "size": "1920x1080",
                    "aspect_ratio": aspect, "model_id": settings.get("image_model_id"),
                },
            },
        }
        if any(str(n.get("id")) == node["id"] for n in nodes):
            skipped.append({"name": name, "reason": f"节点 {node['id']} 已存在"})
            continue
        # 摆位：与资产阶段一致的三栏（角色 / 道具 / 场景），接在同类已有资产下方
        scene_rect = _rect(scene)
        width = float(((scene.get("data") or {}).get("ui") or {}).get("width") or SCENE_DEFAULT_W)
        same_role = [n for n in live_assets() if _config(n).get("asset_role") == role and _config(n).get("asset_scene_node") == scene_id]
        column = _ASSET_COLUMN_ORDER.index(role)
        if same_role:
            x = min(_rect(n)[0] for n in same_role)
            y = max(_rect(n)[3] for n in same_role) + 40
        else:
            x = scene_rect[0] + width + ASSET_SCENE_GAP + column * ASSET_CELL_W
            y = scene_rect[1]
        node["position"] = {"x": x, "y": y}
        nodes.append(node)
        new_nodes.append(node)
        added.append({"name": name, "role": role, "node_id": node["id"]})
    if new_nodes:
        _avoid_overlaps(working, new_nodes)

    operations: list[dict[str, Any]] = []
    for node in new_nodes:
        operations.append({"op": "add_node", "node": {"id": node["id"], "type": "image", "position": node["position"], "data": node["data"]}})

    # 自动连线：复用资产阶段的“镜头文字里提到才连”规则，只追加新边（已有边不动）
    linked: dict[str, set[str]] = {}
    if new_nodes:
        _bind_assets(working, None)
        new_ids = {n["id"] for n in new_nodes}
        for edge in working.get("edges", []) or []:
            if str(edge.get("id")) in original_edge_ids or edge.get("source") not in new_ids:
                # 只关心“由新资产引出”的新连线；其它重建出来的同 id 边视为原有
                continue
            operations.append({"op": "add_edge", "edge": {
                "id": edge["id"], "source": edge["source"], "target": edge["target"],
                "sourceHandle": edge.get("sourceHandle"), "targetHandle": edge.get("targetHandle"),
                "data": {"agent_asset_binding": True},
            }})
            linked.setdefault(str(edge["source"]), set()).add(str(edge["target"]))
    for item in added:
        item["linked_shots"] = len(linked.get(item["node_id"], set()))
    return {"operations": operations, "added": added, "skipped": skipped, "scene_node_id": scene_id}
