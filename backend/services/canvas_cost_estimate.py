"""画布生成成本预估：与运行时计费口径一致（逐节点按图片张数/视频秒数），只读不扣费。

两种计费模式：
- platform：平台账户，按模型积分价预估并对比可用积分；
- user_key：用户自带 API Key，平台不扣积分，只返回待生成数量与时长，费用由上游服务商结算。
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from services.ai.catalog import get_active_price
from services.ai.resolver import resolve_credential_mode, resolve_model
from services.canvas_run_reuse import _reusable_outputs, scope_node_ids
from services.points import accounts as points_accounts
from services.points.pricing import ZERO, estimate_points, quantize_points

_MODALITY_BY_TYPE = {
    "image": "image", "image_generation": "image", "storyboard": "image",
    "video": "video", "video_generation": "video",
}


def _config(node: dict[str, Any]) -> dict[str, Any]:
    return (node.get("data") or {}).get("config") or {}


def _video_seconds(config: dict[str, Any], model, warnings: list[str], label: str) -> float:
    """时长口径与运行时一致：动态时长默认 6 秒，否则 15 秒，并按模型档位归一。"""
    from services.video_canvas_runtime import _validated_video_duration

    capabilities = (model.capabilities_json or {}).get("video") if isinstance(model.capabilities_json, dict) else None
    try:
        return float(_validated_video_duration(config, model.model_key, capabilities if isinstance(capabilities, dict) else None))
    except RuntimeError as exc:
        warnings.append(f"「{label}」{exc}")
        requested = config.get("duration_seconds")
        return float(requested) if isinstance(requested, (int, float)) and not isinstance(requested, bool) and requested > 0 else 15.0


def _warn_audio_support(graph: dict[str, Any], node_id: str, model, label: str, warnings: list[str]) -> None:
    """视频节点连了音频但模型没有声明音频参考能力时，提前在预估里提示（运行时会拒绝提交）。"""
    audio_count = sum(
        1 for edge in graph.get("edges") or []
        if isinstance(edge, dict) and edge.get("target") == node_id and edge.get("targetHandle") == "audio"
        and not (isinstance(edge.get("data"), dict) and edge["data"].get("disabled"))
    )
    if not audio_count:
        return
    capabilities = (model.capabilities_json or {}).get("video") if isinstance(model.capabilities_json, dict) else None
    limits = capabilities.get("limits") if isinstance(capabilities, dict) else None
    limit = limits.get("max_reference_audios") if isinstance(limits, dict) else None
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        warnings.append(f"「{label}」连接了音频，但所选视频模型未声明音频参考能力，提交时会被拒绝")
    elif audio_count > limit:
        warnings.append(f"「{label}」连接了 {audio_count} 个音频，超过模型上限 {limit} 个")


def estimate_canvas_cost(
    graph: dict[str, Any],
    *,
    canvas_id: int,
    user_id: int,
    db,
    target_node_ids: list[str] | None = None,
    rerun_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    graph = deepcopy(graph or {})
    from services.canvas_video_model import apply_auto_video_models

    apply_auto_video_models(graph, db, user_id)
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id")]
    by_id = {str(n["id"]): n for n in nodes}
    requested = {str(i) for i in (target_node_ids or []) if str(i) in by_id}
    if target_node_ids and not requested:
        raise HTTPException(422, "目标节点不存在")
    if not requested:
        requested = {i for i, n in by_id.items() if n.get("type") in _MODALITY_BY_TYPE and not _config(n).get("stale")}

    # 与网关/运行时同口径：定义未变且已成功生成的节点会被复用，不重复计费。
    _reusable_outputs(graph, canvas_id, db, {str(i) for i in (rerun_node_ids or [])})
    by_id = {str(n["id"]): n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    scope: set[str] = set()
    for node_id in requested:
        scope |= scope_node_ids(graph, node_id)

    mode = resolve_credential_mode(db, user_id, None)
    warnings: list[str] = []
    models: dict[tuple[str, Any], Any] = {}
    items: list[dict[str, Any]] = []
    reused = 0
    total = ZERO

    for node_id in sorted(scope):
        node = by_id.get(node_id)
        if not node or node.get("type") not in _MODALITY_BY_TYPE:
            continue
        config = _config(node)
        if config.get("stale"):
            continue
        if isinstance(config.get("asset_id"), int):
            reused += 1
            continue
        modality = _MODALITY_BY_TYPE[str(node["type"])]
        label = str((node.get("data") or {}).get("label") or node_id)
        model_id = config.get("model_id") if isinstance(config.get("model_id"), int) else None
        key = (modality, model_id)
        if key not in models:
            try:
                models[key] = resolve_model(db, user_id, modality=modality, model_id=model_id, task_type=f"video_canvas.{node['type']}")
            except HTTPException as exc:
                models[key] = None
                warnings.append(f"「{label}」没有可用的{'图片' if modality == 'image' else '视频'}模型：{exc.detail}")
        model = models[key]
        seconds = _video_seconds(config, model, warnings, label) if modality == "video" and model else 0.0
        if modality == "video" and model:
            _warn_audio_support(graph, node_id, model, label, warnings)
        item: dict[str, Any] = {
            "node_id": node_id, "label": label, "modality": modality,
            "model_id": model.id if model else None, "model_name": getattr(model, "display_name", None) or getattr(model, "model_key", None) if model else None,
            "video_seconds": seconds if modality == "video" else None, "points": None, "priced": False,
        }
        if mode == "platform" and model:
            price = get_active_price(db, model.id)
            if not price:
                warnings.append(f"「{label}」使用的模型未配置积分价格，无法预估")
            else:
                points = estimate_points(
                    billing_type=price.billing_type, price_config=price.price_config_json,
                    image_count=1, video_seconds=seconds, use_estimate_defaults=True,
                )
                item.update(points=float(points), priced=True)
                total += points
        items.append(item)

    result: dict[str, Any] = {
        "credential_mode": mode,
        "image_count": sum(1 for i in items if i["modality"] == "image"),
        "video_count": sum(1 for i in items if i["modality"] == "video"),
        "video_seconds": sum(i["video_seconds"] or 0 for i in items),
        "reused_count": reused,
        "items": items,
        "warnings": warnings,
        "total_points": None,
        "available_points": None,
        "sufficient": None,
    }
    if mode == "platform":
        account = points_accounts.ensure_account(db, user_id)
        db.commit()
        available = quantize_points(Decimal(account.available_points))
        total = quantize_points(total)
        result.update(
            total_points=float(total), available_points=float(available),
            sufficient=available >= total and not any(not i["priced"] for i in items),
        )
    return result
