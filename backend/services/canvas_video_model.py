"""画布视频节点的模型自动推荐。

导演拆分镜头时不再看视频模型的时长规格（统一按 4 到 15 秒的任意整数秒拆分，保证拆分质量）；
选哪个视频模型是之后的事：每个视频节点按「自己的时长、画幅、参考图数量」从可用的视频模型里挑一个合适的。

规则（从先到后）：
1. 只考虑已启用、对用户可见的视频模型；
2. 必须支持该节点的时长（模型声明了离散档位就必须在档位内，声明了连续区间就必须在区间内；
   没有声明时长规格的模型视为“可能支持”，排在明确支持的后面）；
3. 画幅、参考图张数在模型声明了上限时也必须满足；
4. 都满足时：用户设置里的默认视频模型优先，其次按后台配置的排序（sort_order）和编号；
5. 没有任何模型完全满足时，退而选「最接近该时长」的模型，运行前仍会按模型档位校验并给出明确提示。
"""

from __future__ import annotations

from typing import Any

from services.video_duration import _duration_options, _duration_range

# 导演统一按这个区间拆分镜头（含两端），与具体视频模型无关
DIRECTOR_MIN_SECONDS = 4
DIRECTOR_MAX_SECONDS = 15
DEFAULT_UNIT_SECONDS = 6


def _config(node: dict[str, Any]) -> dict[str, Any]:
    return (node.get("data") or {}).get("config") or {}


def _video_capabilities(model: Any) -> dict[str, Any]:
    raw = getattr(model, "capabilities_json", None)
    video = raw.get("video") if isinstance(raw, dict) else None
    return video if isinstance(video, dict) else {}


def duration_fit(capabilities: dict[str, Any], seconds: int) -> tuple[int, int]:
    """返回 (匹配等级, 与支持时长的差距秒数)：等级 0 = 明确支持，1 = 未声明（可能支持），2 = 明确不支持。"""
    options = _duration_options(capabilities)
    if options:
        return (0, 0) if seconds in options else (2, min(abs(o - seconds) for o in options))
    low, high = _duration_range(capabilities)
    if low is not None or high is not None:
        if (low is None or seconds >= low) and (high is None or seconds <= high):
            return 0, 0
        gap = (low - seconds) if low is not None and seconds < low else (seconds - high)
        return 2, int(gap)
    return 1, 0


def _meets_limits(capabilities: dict[str, Any], aspect_ratio: str | None, reference_count: int) -> bool:
    limits = capabilities.get("limits") if isinstance(capabilities.get("limits"), dict) else {}
    ratios = limits.get("aspect_ratios")
    if aspect_ratio and isinstance(ratios, list) and ratios and aspect_ratio not in ratios:
        return False
    max_refs = limits.get("max_reference_images")
    if isinstance(max_refs, int) and not isinstance(max_refs, bool) and max_refs >= 0 and reference_count > max_refs:
        return False
    return True


def candidate_video_models(db) -> list[Any]:
    from models import AiModel

    return (
        db.query(AiModel)
        .filter(AiModel.modality == "video", AiModel.enabled.is_(True), AiModel.user_visible.is_(True))
        .order_by(AiModel.sort_order.asc(), AiModel.id.asc())
        .all()
    )


def _user_default_video_model_id(db, user_id: int | None) -> int | None:
    if not user_id:
        return None
    try:
        from services.ai.resolver import _pref

        pref = _pref(db, user_id)
        value = getattr(pref, "default_video_model_id", None) if pref else None
        return int(value) if value else None
    except Exception:  # noqa: BLE001 - 取不到用户偏好不影响推荐
        return None


def recommend_video_model(db, user_id: int | None, seconds: int, aspect_ratio: str | None = None, reference_count: int = 0, models: list[Any] | None = None) -> Any | None:
    """给一个视频节点推荐模型；没有任何可用视频模型时返回 None。"""
    candidates = models if models is not None else candidate_video_models(db)
    if not candidates:
        return None
    preferred = _user_default_video_model_id(db, user_id)
    scored = []
    for index, model in enumerate(candidates):
        capabilities = _video_capabilities(model)
        level, gap = duration_fit(capabilities, seconds)
        meets = _meets_limits(capabilities, aspect_ratio, reference_count)
        # 排序键：时长匹配等级（含差距）→ 画幅 / 参考图满足 → 用户默认 → 后台排序
        scored.append(((level, gap, 0 if meets else 1, 0 if getattr(model, "id", None) == preferred else 1, index), model))
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def node_unit_seconds(config: dict[str, Any]) -> int:
    value = config.get("duration_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return DEFAULT_UNIT_SECONDS
    return int(round(value))


def is_auto_video_node(node: dict[str, Any]) -> bool:
    config = _config(node)
    return node.get("type") in {"video", "video_generation"} and not config.get("stale") and bool(config.get("model_auto"))


def apply_auto_video_models(graph: dict[str, Any], db, user_id: int | None) -> list[dict[str, Any]]:
    """给图里标记为“自动推荐”的视频节点填上推荐的模型（原地修改，返回变更清单）。用户手动选过模型的节点不动。"""
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict)]
    auto_nodes = [n for n in nodes if is_auto_video_node(n)]
    if not auto_nodes:
        return []
    models = candidate_video_models(db)
    edges = [e for e in graph.get("edges") or [] if isinstance(e, dict)]
    changes: list[dict[str, Any]] = []
    for node in auto_nodes:
        config = node.setdefault("data", {}).setdefault("config", {})
        refs = sum(1 for e in edges if e.get("target") == node.get("id") and e.get("targetHandle") == "image")
        model = recommend_video_model(db, user_id, node_unit_seconds(config), str(config.get("aspect_ratio") or "") or None, refs, models)
        if model is None or config.get("model_id") == model.id:
            continue
        previous = config.get("model_id")
        config["model_id"] = model.id
        config["model"] = model.model_key
        changes.append({"node_id": node.get("id"), "from": previous, "to": model.id, "model": model.display_name})
    return changes
