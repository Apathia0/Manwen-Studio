"""画布质量评审：三个审核点（剧本 / 资产 / 分镜）的自动检查，以及局部重做的影响预览。

评审只读画布图、不调用模型、不扣费，结果可重复计算：
- 自动评审员逐项检查，问题分为 error（必须处理）与 warning（建议处理），并标出能靠重跑某一阶段自动修复的项；
- 用户只需要在三个审核点上看"有没有问题 + 确认"，不必逐节点翻找；
- 局部重做只让某个场景从指定阶段起重新生成，其余场景保持不动。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CHECKPOINTS = ("script", "assets", "storyboard")
CHECKPOINT_LABELS = {"script": "剧本与拆分", "assets": "角色与资产", "storyboard": "分镜与镜头"}
REDO_STAGES = ("director", "assets", "compile")
# 上游模型能接受的镜头时长范围（秒）；超出的镜头提交前会被归一化，评审提前提示
MIN_SHOT_SECONDS = 2
MAX_SHOT_SECONDS = 15
# 单个场景的镜头数量过多时，后续出图/视频成本和一致性风险都会放大
MAX_SHOTS_PER_SCENE = 12


def _config(node: dict[str, Any]) -> dict[str, Any]:
    return (node.get("data") or {}).get("config") or {}


def _label(node: dict[str, Any]) -> str:
    return str((node.get("data") or {}).get("label") or node.get("id") or "")


def _live(nodes: list[dict[str, Any]], kind: str | None = None) -> list[dict[str, Any]]:
    return [n for n in nodes if isinstance(n, dict) and (kind is None or n.get("type") == kind) and not _config(n).get("stale")]


def _names(values: Any) -> list[str]:
    """镜头里的 characters 可能是名字列表，也可能是带 name 字段的对象列表。"""
    result: list[str] = []
    for value in values or []:
        name = value.get("name") if isinstance(value, dict) else value
        if isinstance(name, str) and name.strip():
            result.append(name.strip())
    return result


def _issue(checkpoint: str, code: str, severity: str, message: str, node_ids: list[str], *, scene_node_id: str | None = None, redo_stage: str | None = None, action: str | None = None) -> dict[str, Any]:
    return {
        "id": f"{code}:{scene_node_id or ''}:{','.join(node_ids[:3])}",
        "checkpoint": checkpoint,
        "code": code,
        "severity": severity,
        "message": message,
        "node_ids": node_ids,
        "scene_node_id": scene_node_id,
        # 能靠"从某阶段重做该场景"自动修复的问题才带这个字段
        "redo_stage": redo_stage,
        # 不需要重做阶段、一键即可修好的问题（如 bind_references：补连角色参考图）
        "action": action,
    }


def _scene_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    """场景审核聚合节点把场景放在 config.scenes 里；旧版单场景节点则内容直接在 config 上。"""
    scenes = config.get("scenes")
    if isinstance(scenes, list):
        return [item for item in scenes if isinstance(item, dict)]
    return [config]


def _has_content(item: dict[str, Any]) -> bool:
    return bool(item.get("beats") or item.get("content") or item.get("summary") or item.get("scene_purpose") or item.get("title"))


def _review_script(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    scenes = _live(nodes, "scene")
    if not scenes:
        return [_issue("script", "no_scene", "error", "剧本还没有拆分出场景", [])]
    for scene in scenes:
        items = _scene_items(_config(scene))
        if not any(_has_content(item) for item in items):
            issues.append(_issue("script", "empty_scene", "error", f"场景「{_label(scene)}」没有任何内容", [scene["id"]], scene_node_id=scene["id"]))
        for item in items:
            beats = item.get("beats") or []
            if isinstance(beats, list) and len(beats) > 40:
                name = item.get("title") or _label(scene)
                issues.append(_issue("script", "scene_too_long", "warning", f"场景「{name}」包含 {len(beats)} 个节拍，建议拆成更小的场景", [scene["id"]], scene_node_id=scene["id"]))
    return issues


def _review_assets(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    live = _live(nodes)
    assets = [n for n in live if n.get("type") == "image" and _config(n).get("asset_role") in {"character", "scene", "prop"}]
    character_names = {str(_config(n).get("asset_name") or "").strip() for n in assets if _config(n).get("asset_role") == "character"}
    # 分镜里出现、但没有对应角色资产的人物：生成分镜时会凭空长相，跨镜头无法保持一致
    for scene in _live(nodes, "scene"):
        plan = _config(scene).get("director_plan") or {}
        missing: set[str] = set()
        units = [u for u in plan.get("units") or [] if isinstance(u, dict)]
        # 导演记录的“出场角色”会混进“级别”“石碑上亮起五个大字”这类非角色的词：只把像人名（不超过 6 个字）、
        # 且在这个分场景的镜头文字里至少出现 2 次的名字当作缺失的角色
        body = " ".join(json.dumps({k: v for k, v in u.items() if k != "characters"}, ensure_ascii=False, default=str) for u in units)
        for unit in units:
            missing.update(name for name in _names(unit.get("characters")) if name not in character_names and len(name) <= 6 and body.count(name) >= 2)
        if missing:
            issues.append(_issue("assets", "character_missing_asset", "warning", f"场景「{_label(scene)}」的角色 {'、'.join(sorted(missing))} 没有角色资产，跨镜头形象可能不一致", [scene["id"]], scene_node_id=scene["id"], redo_stage="assets"))
    for asset in assets:
        config = _config(asset)
        if not str(config.get("prompt") or "").strip() and not config.get("asset_id"):
            issues.append(_issue("assets", "asset_empty_prompt", "error", f"资产「{config.get('asset_name') or _label(asset)}」没有描述，无法生成", [asset["id"]], scene_node_id=config.get("asset_scene_node")))
    seen: dict[tuple[str, str], str] = {}
    for asset in assets:
        config = _config(asset)
        key = (str(config.get("asset_role")), str(config.get("asset_name") or "").strip())
        if key[1] and key in seen:
            issues.append(_issue("assets", "asset_duplicate", "warning", f"{'角色' if key[0] == 'character' else '资产'}「{key[1]}」出现了重复节点，建议合并，避免形象分叉", [seen[key], asset["id"]]))
        else:
            seen[key] = asset["id"]
    return issues


# 总时长比内容预估长出这么多（且至少多出这么多秒），就提示“时长被拉长”。内容预估是各节拍的最少秒数，本身偏小，所以留出余量
INFLATION_RATIO = 1.6
INFLATION_MIN_EXTRA_SECONDS = 30


def _duration_inflation_issues(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """导演方案的总时长远超剧本内容本身需要的时长：常见于所选视频模型只有单一时长档位（例如只能出 15 秒），
    每个镜头都被“延展”到这个固定时长。提示用户换支持多档时长的模型后重做导演编排。"""
    from services.canvas_director_quality import minimum_seconds

    issues: list[dict[str, Any]] = []
    for scene in _live(nodes, "scene"):
        config = _config(scene)
        plan = config.get("director_plan") or {}
        units = [u for u in plan.get("units") or [] if isinstance(u, dict)]
        beats = [b for item in config.get("scenes") or [] if isinstance(item, dict) for b in item.get("beats") or [] if isinstance(b, dict)]
        total = sum(float(u.get("duration_seconds") or 0) for u in units)
        content = minimum_seconds(beats) if beats else 0
        if not units or content <= 0 or total < content * INFLATION_RATIO or total - content < INFLATION_MIN_EXTRA_SECONDS:
            continue
        options = [o for o in (plan.get("production_policy") or {}).get("duration_options") or [] if isinstance(o, int)]
        cause = f"这份方案生成时只有 {options[0]} 秒一档，每个镜头都被延展到这个时长" if len(options) == 1 else "镜头被拆得太细或时长分配偏长"
        issues.append(_issue(
            "storyboard", "duration_inflated", "warning",
            f"场景「{_label(scene)}」导演方案共 {len(units)} 个镜头、合计 {round(total)} 秒，比内容本身需要的约 {round(content)} 秒长了 {round((total / content - 1) * 100)}%（{cause}）。"
            "导演现在统一按 4 到 15 秒拆分、视频节点自动推荐合适的模型，重做导演编排可以省下约 " + str(round(total - content)) + " 秒的视频费用",
            [scene["id"]], scene_node_id=scene["id"], redo_stage="director",
        ))
    return issues


def _review_storyboard(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    live = _live(nodes)
    storyboards = [n for n in live if n.get("type") == "image" and _config(n).get("node_role") == "storyboard"]
    videos = [n for n in live if n.get("type") == "video" and _config(n).get("unit_id")]
    scene_ids = {n["id"] for n in _live(nodes, "scene")}
    per_scene: dict[str, int] = {}
    for shot in videos:
        config = _config(shot)
        scene_id = str(config.get("source_scene_node") or "")
        per_scene[scene_id] = per_scene.get(scene_id, 0) + 1
        if not str(config.get("prompt") or "").strip():
            issues.append(_issue("storyboard", "shot_empty_prompt", "error", f"{_label(shot)} 没有视频提示词", [shot["id"]], scene_node_id=scene_id or None, redo_stage="compile"))
        seconds = config.get("duration_seconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and not MIN_SHOT_SECONDS <= seconds <= MAX_SHOT_SECONDS:
            issues.append(_issue("storyboard", "shot_duration", "warning", f"{_label(shot)} 时长 {seconds} 秒，超出 {MIN_SHOT_SECONDS}-{MAX_SHOT_SECONDS} 秒，提交前会被调整", [shot["id"]], scene_node_id=scene_id or None, redo_stage="director"))
        has_frame = any(e.get("target") == shot["id"] and e.get("targetHandle") == "image" for e in edges)
        if not has_frame:
            issues.append(_issue("storyboard", "shot_no_storyboard", "warning", f"{_label(shot)} 没有连接分镜图，将按纯文字生成，画面一致性较差", [shot["id"]], scene_node_id=scene_id or None, redo_stage="compile"))
    # 视频节点没有连出场角色的参考图：图生视频只看分镜图，角色形象容易走样
    characters = {str(_config(n).get("asset_name")): n["id"] for n in live if n.get("type") == "image" and _config(n).get("asset_role") == "character"}
    from services.canvas_stage_gateway import _shot_text

    for shot in videos:
        text = _shot_text(_config(shot))
        names = [name for name in characters if name and name in text]
        linked = {e.get("source") for e in edges if e.get("target") == shot["id"]}
        missing = [name for name in names if characters[name] not in linked]
        if missing:
            issues.append(_issue("storyboard", "video_missing_character_ref", "warning", f"{_label(shot)} 没有连接角色 {'、'.join(missing)} 的参考图，视频里角色形象可能不一致", [shot["id"]], scene_node_id=_config(shot).get("source_scene_node"), action="bind_references"))
    for shot in storyboards:
        config = _config(shot)
        if not str(config.get("prompt") or "").strip():
            issues.append(_issue("storyboard", "storyboard_empty_prompt", "error", f"{_label(shot)} 没有分镜提示词", [shot["id"]], scene_node_id=config.get("source_scene_node"), redo_stage="compile"))
            continue
    issues.extend(_duration_inflation_issues(nodes))
    for scene_id, count in per_scene.items():
        if count > MAX_SHOTS_PER_SCENE and scene_id in scene_ids:
            issues.append(_issue("storyboard", "too_many_shots", "warning", f"一个场景被拆成 {count} 个镜头（建议不超过 {MAX_SHOTS_PER_SCENE}），生成成本和一致性风险较高", [scene_id], scene_node_id=scene_id))
    return issues


def _fingerprint(nodes: list[dict[str, Any]], key: str) -> str:
    """审核点对应内容的指纹：用户确认后内容再变动，确认自动失效，需要重新确认。"""
    live = _live(nodes)
    if key == "script":
        items = [(n["id"], [(i.get("beats") or i.get("content") or i.get("summary") or i.get("title")) for i in _scene_items(_config(n))]) for n in live if n.get("type") == "scene"]
    elif key == "assets":
        items = [(n["id"], _config(n).get("prompt"), _config(n).get("asset_id")) for n in live if n.get("type") == "image" and _config(n).get("asset_role")]
    else:
        items = [(n["id"], _config(n).get("prompt"), _config(n).get("duration_seconds")) for n in live if _config(n).get("unit_id")]
    return hashlib.sha1(json.dumps(sorted(items, key=lambda x: str(x[0])), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def review_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """对画布做三个审核点的检查，并合并用户已确认的记录。只读，不修改入参。"""
    nodes = [n for n in (graph or {}).get("nodes") or [] if isinstance(n, dict)]
    edges = [e for e in (graph or {}).get("edges") or [] if isinstance(e, dict)]
    by_checkpoint = {
        "script": _review_script(nodes),
        "assets": _review_assets(nodes),
        "storyboard": _review_storyboard(nodes, edges),
    }
    approvals = ((graph or {}).get("metadata") or {}).get("review_approvals") or {}
    has_shots = bool(_live(nodes, "video"))
    has_assets = any(_config(n).get("asset_role") for n in _live(nodes, "image"))
    ready = {"script": bool(_live(nodes, "scene")), "assets": has_assets, "storyboard": has_shots}
    checkpoints: dict[str, Any] = {}
    for key in CHECKPOINTS:
        issues = by_checkpoint[key]
        errors = sum(1 for i in issues if i["severity"] == "error")
        approval = approvals.get(key) if isinstance(approvals.get(key), dict) else None
        fingerprint = _fingerprint(nodes, key)
        if not ready[key]:
            status = "pending"
        elif errors:
            status = "blocked"
        elif approval and approval.get("fingerprint") == fingerprint:
            status = "approved"
        else:
            status = "ready"
        checkpoints[key] = {
            "key": key,
            "label": CHECKPOINT_LABELS[key],
            "status": status,
            "error_count": errors,
            "warning_count": len(issues) - errors,
            "issues": issues,
            "fingerprint": fingerprint,
            "approved_at": (approval or {}).get("approved_at") if status == "approved" else None,
        }
    return {
        "checkpoints": checkpoints,
        "issue_count": sum(len(v) for v in by_checkpoint.values()),
        "error_count": sum(c["error_count"] for c in checkpoints.values()),
        # 三个审核点都通过（无错误）才建议提交出图和视频
        "ready_to_generate": all(checkpoints[k]["status"] in {"ready", "approved"} for k in CHECKPOINTS),
    }


def repair_targets(review: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """把"可通过重做某阶段修复"的问题归并成 {(场景节点, 阶段): 问题说明}，供自动质量循环使用。"""
    order = {stage: i for i, stage in enumerate(REDO_STAGES)}
    targets: dict[tuple[str, str], list[str]] = {}
    for checkpoint in (review.get("checkpoints") or {}).values():
        for issue in checkpoint.get("issues") or []:
            stage, scene_id = issue.get("redo_stage"), issue.get("scene_node_id")
            if issue.get("severity") != "error" or stage not in order or not scene_id:
                continue
            targets.setdefault((scene_id, stage), []).append(issue["message"])
    # 同一场景里同时需要重做多个阶段时，只保留最靠前的（它会带动后面的阶段重新生成）
    earliest: dict[str, str] = {}
    for scene_id, stage in targets:
        if scene_id not in earliest or order[stage] < order[earliest[scene_id]]:
            earliest[scene_id] = stage
    return {(scene_id, stage): targets[(scene_id, stage)] for scene_id, stage in earliest.items()}


def _downstream(graph: dict[str, Any], scene_id: str, from_stage: str) -> dict[str, list[dict[str, Any]]]:
    """从某阶段起重做会作废的节点（未失效的、未锁定的）。"""
    nodes = _live([n for n in graph.get("nodes") or [] if isinstance(n, dict)])
    assets = [n for n in nodes if _config(n).get("asset_scene_node") == scene_id and _config(n).get("asset_role") and not _config(n).get("locked")]
    shots = [n for n in nodes if _config(n).get("source_scene_node") == scene_id and _config(n).get("unit_id")]
    if from_stage == "director":
        return {"assets": assets, "shots": shots}
    if from_stage == "assets":
        return {"assets": assets, "shots": []}
    return {"assets": [], "shots": shots}


def redo_preview(graph: dict[str, Any], scene_id: str, from_stage: str) -> dict[str, Any]:
    """局部重做的影响预览：会作废多少节点、其中多少已经生成过（重做后需要重新计费）。"""
    if from_stage not in REDO_STAGES:
        raise ValueError("不支持的重做阶段")
    scene = next((n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id") == scene_id and n.get("type") == "scene"), None)
    if scene is None:
        raise ValueError("场景节点不存在")
    groups = _downstream(graph, scene_id, from_stage)
    affected = [n for group in groups.values() for n in group]
    generated = [n for n in affected if _config(n).get("asset_id")]
    locked = [
        n for n in _live([n for n in graph.get("nodes") or [] if isinstance(n, dict)])
        if _config(n).get("asset_scene_node") == scene_id and _config(n).get("locked")
    ]
    return {
        "scene_node_id": scene_id,
        "scene_label": _label(scene),
        "from_stage": from_stage,
        "asset_count": len(groups["assets"]),
        "shot_count": len(groups["shots"]),
        "generated_count": len(generated),
        "kept_locked_count": len(locked),
        "node_ids": [n["id"] for n in affected],
    }


def apply_redo(graph: dict[str, Any], scene_id: str, from_stage: str) -> dict[str, Any]:
    """把受影响节点标记为失效（原地修改 graph），并清掉导演方案；返回同 redo_preview 的摘要。"""
    summary = redo_preview(graph, scene_id, from_stage)
    affected_ids = set(summary["node_ids"])
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("id") in affected_ids:
            node.setdefault("data", {}).setdefault("config", {})["stale"] = True
    if from_stage == "director":
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("id") == scene_id:
                config = node.setdefault("data", {}).setdefault("config", {})
                config.pop("director_plan", None)
                config.pop("director_plan_hash", None)
    return summary
