from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


ZERO = Decimal("0")
Q4 = Decimal("0.0001")


def _d(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def quantize_points(value: Decimal) -> Decimal:
    return value.quantize(Q4, rounding=ROUND_HALF_UP)


def estimate_points(
    *,
    billing_type: str,
    price_config: dict[str, Any] | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    image_count: int = 1,
    video_seconds: float | Decimal = 0,
    use_estimate_defaults: bool = True,
) -> Decimal:
    cfg = price_config or {}
    btype = (billing_type or "per_call").strip()

    if btype == "per_call":
        points = _d(cfg.get("points_per_call"), "1")
    elif btype == "per_1k_tokens":
        in_rate = _d(cfg.get("input_points_per_1k"), "0")
        out_rate = _d(cfg.get("output_points_per_1k"), "0")
        est_out = int(cfg.get("estimate_default_output_tokens") or 2000)
        actual_in = max(0, int(input_tokens or 0))
        actual_out = max(0, int(output_tokens or 0))
        if use_estimate_defaults and actual_out <= 0:
            actual_out = est_out
        if use_estimate_defaults and actual_in <= 0:
            actual_in = int(cfg.get("estimate_default_input_tokens") or 1000)
        points = (Decimal(actual_in) / Decimal(1000)) * in_rate + (Decimal(actual_out) / Decimal(1000)) * out_rate
        min_pts = _d(cfg.get("min_points_per_call"), "0")
        if points < min_pts:
            points = min_pts
    elif btype == "per_image":
        per = _d(cfg.get("points_per_image"), "1")
        count = max(1, int(image_count or 1))
        points = per * Decimal(count)
    elif btype == "per_second":
        per = _d(cfg.get("points_per_second"), "1")
        seconds = _d(video_seconds, "0")
        if use_estimate_defaults and seconds <= 0:
            seconds = _d(cfg.get("estimate_default_seconds"), "15")
        points = per * seconds
    else:
        points = _d(cfg.get("points_per_call"), "1")

    return quantize_points(max(ZERO, points))


def reserve_points_from_estimate(estimated: Decimal, safety_factor: Decimal = Decimal("1.0")) -> Decimal:
    raw = estimated * safety_factor
    return quantize_points(max(estimated, raw))


def price_snapshot(billing_type: str, price_config: dict[str, Any] | None, price_id: int | None = None) -> dict[str, Any]:
    return {
        "price_id": price_id,
        "billing_type": billing_type,
        "price_config": dict(price_config or {}),
    }
